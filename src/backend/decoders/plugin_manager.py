"""Hot-reloadable decoder plugin manager.

Watches the decoders/ directory for file changes and supports runtime reload
via server command (RELOAD_DECODERS). Gracefully swaps old decoder instances
for new ones, preserving callbacks and enabled state.
"""

import asyncio
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from .base import BaseDecoder
from . import discover_decoders, load_decoders

logger = logging.getLogger(__name__)


class PluginManager:
    """Manages decoder plugin lifecycle including discovery, instantiation, and hot-reload."""

    def __init__(self, sample_rate: int = 48000):
        self.sample_rate = sample_rate
        self._decoders: dict[str, BaseDecoder] = {}
        self._callbacks: list[Callable[[dict], None]] = []
        self._lock = threading.RLock()
        self._watch_thread: Optional[threading.Thread] = None
        self._watch_stop = threading.Event()
        self._watch_dir: Optional[Path] = None
        self._last_mtimes: dict[str, float] = {}
        self._on_reload_callback: Optional[Callable[[list[str]], None]] = None

    @property
    def decoders(self) -> dict[str, BaseDecoder]:
        with self._lock:
            return dict(self._decoders)

    def add_callback(self, cb: Callable[[dict], None]):
        """Register a global callback that will be attached to all current and future decoders."""
        with self._lock:
            if cb not in self._callbacks:
                self._callbacks.append(cb)
                for dec in self._decoders.values():
                    dec.add_callback(cb)

    def set_on_reload(self, cb: Optional[Callable[[list[str]], None]]):
        """Set callback invoked after a reload. Argument: list of affected decoder names."""
        self._on_reload_callback = cb

    def load(self):
        """Discover and load all decoder plugins."""
        with self._lock:
            self._decoders = load_decoders(sample_rate=self.sample_rate)
            for dec in self._decoders.values():
                for cb in self._callbacks:
                    dec.add_callback(cb)
        logger.info(f"PluginManager: loaded {len(self._decoders)} decoder(s): {list(self._decoders.keys())}")

    def get(self, name: str) -> Optional[BaseDecoder]:
        with self._lock:
            return self._decoders.get(name)

    def set_enabled(self, name: str, enabled: bool) -> bool:
        """Enable/disable a decoder by name. Returns True if found."""
        with self._lock:
            dec = self._decoders.get(name)
            if dec is None:
                return False
            dec.enabled = enabled
            return True

    def reload(self) -> list[str]:
        """Reload all decoder plugins. Returns list of affected decoder names."""
        with self._lock:
            old_decoders = dict(self._decoders)
            old_names = set(old_decoders.keys())

            # Cleanup old instances
            for dec in old_decoders.values():
                if dec.enabled:
                    try:
                        dec.enabled = False
                    except Exception:
                        pass
                try:
                    dec.cleanup()
                except Exception:
                    logger.exception(f"cleanup() failed for {dec.name}")

            # Discover and load new instances
            new_decoders = load_decoders(sample_rate=self.sample_rate)
            for dec in new_decoders.values():
                for cb in self._callbacks:
                    dec.add_callback(cb)

            # Preserve enabled state from old instances
            for name, new_dec in new_decoders.items():
                old_dec = old_decoders.get(name)
                if old_dec and old_dec.enabled:
                    try:
                        new_dec.enabled = True
                    except Exception:
                        pass

            self._decoders = new_decoders
            new_names = set(new_decoders.keys())

            affected = list(old_names | new_names)
            added = new_names - old_names
            removed = old_names - new_names
            logger.info(
                f"PluginManager: reloaded. {len(new_decoders)} active. "
                f"Added: {added or 'none'}. Removed: {removed or 'none'}."
            )

        if self._on_reload_callback:
            try:
                self._on_reload_callback(affected)
            except Exception:
                logger.exception("on_reload callback failed")

        return affected

    def shutdown(self):
        """Disable and cleanup all decoders."""
        self.stop_watching()
        with self._lock:
            for dec in self._decoders.values():
                if dec.enabled:
                    try:
                        dec.enabled = False
                    except Exception:
                        pass
                try:
                    dec.cleanup()
                except Exception:
                    logger.exception(f"cleanup() failed for {dec.name}")
            self._decoders.clear()

    # --- File watcher for hot-reload ---

    def start_watching(self, interval: float = 2.0):
        """Start a background thread that watches the decoders/ dir for changes."""
        if self._watch_thread and self._watch_thread.is_alive():
            return

        self._watch_dir = Path(__file__).parent
        self._last_mtimes = self._scan_mtimes()
        self._watch_stop.clear()
        self._watch_thread = threading.Thread(
            target=self._watch_loop,
            args=(interval,),
            daemon=True,
            name="plugin-watcher",
        )
        self._watch_thread.start()
        logger.info(f"PluginManager: watching {self._watch_dir} for changes")

    def stop_watching(self):
        """Stop the file watcher thread."""
        if self._watch_thread:
            self._watch_stop.set()
            self._watch_thread.join(timeout=5)
            self._watch_thread = None

    def _scan_mtimes(self) -> dict[str, float]:
        mtimes = {}
        if self._watch_dir:
            for f in self._watch_dir.glob("*.py"):
                try:
                    mtimes[f.name] = f.stat().st_mtime
                except OSError:
                    pass
        return mtimes

    def _watch_loop(self, interval: float):
        while not self._watch_stop.is_set():
            self._watch_stop.wait(interval)
            if self._watch_stop.is_set():
                break
            current = self._scan_mtimes()
            if current != self._last_mtimes:
                added = set(current.keys()) - set(self._last_mtimes.keys())
                removed = set(self._last_mtimes.keys()) - set(current.keys())
                changed = [
                    k for k in set(current.keys()) & set(self._last_mtimes.keys())
                    if current[k] != self._last_mtimes[k]
                ]
                if added or removed or changed:
                    logger.info(
                        f"PluginManager: detected changes — "
                        f"added: {added}, removed: {removed}, changed: {changed}"
                    )
                    self._last_mtimes = current
                    self.reload()
                else:
                    self._last_mtimes = current
