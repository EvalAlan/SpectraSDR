#!/usr/bin/env python3
"""SDR source discovery and construction.

Deliberately the same shape as decoders/__init__.py: walk the package, find
concrete BaseSDRSource subclasses, key them by their `name` class attribute --
which is also the value stored in a connection profile's "driver" field.

Every module here must import cleanly on a machine with no SDR libraries
installed. Sources that need a native library probe for it in is_available(),
never at import time, otherwise a missing library would make the driver vanish
from the UI instead of appearing with an explanation.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import Type

from .base import (
    BaseSDRSource,
    Capabilities,
    SampleFormat,
    SourceUnavailable,
    to_complex64,
)

logger = logging.getLogger(__name__)

__all__ = [
    "BaseSDRSource", "Capabilities", "SampleFormat", "SourceUnavailable",
    "to_complex64", "discover_sources", "create_source", "list_drivers",
    "DEFAULT_DRIVER",
]

DEFAULT_DRIVER = "rtl_tcp"


def discover_sources() -> dict[str, Type[BaseSDRSource]]:
    """Return {driver_name: class} for every concrete source in this package."""
    found: dict[str, Type[BaseSDRSource]] = {}
    package_path = str(Path(__file__).parent)

    for _finder, module_name, _ispkg in pkgutil.iter_modules([package_path]):
        if module_name.startswith("_") or module_name == "base":
            continue
        try:
            mod = importlib.import_module(f".{module_name}", package=__package__)
        except Exception:
            # A source module failing to import must not take the others with
            # it; the remaining drivers stay usable.
            logger.exception(f"Failed to import source module: {module_name}")
            continue

        for attr_name in dir(mod):
            obj = getattr(mod, attr_name)
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseSDRSource)
                and obj is not BaseSDRSource
                and not getattr(obj, "__abstractmethods__", set())
            ):
                found[obj.name] = obj
                logger.debug(f"Discovered SDR source: {obj.name} ({obj.__name__})")

    return found


def list_drivers() -> list[dict]:
    """Describe every driver for the UI, including ones that cannot run here.

    Unavailable drivers are still listed, with a reason, so the connection
    dialog can eventually show them greyed out rather than silently omitting
    them. The server/frontend capability path is not wired yet.
    """
    out = []
    for name, cls in sorted(discover_sources().items()):
        try:
            available, reason = cls.is_available()
        except Exception as exc:
            # is_available must never raise, but a third-party source might.
            available, reason = False, f"availability check failed: {exc}"
        out.append({
            "driver": name,
            "description": cls.description,
            "available": bool(available),
            "reason": reason,
        })
    return out


def create_source(config: dict) -> BaseSDRSource:
    """Build the source named by config["driver"].

    Falls back to rtl_tcp for a missing or unknown driver so that existing
    profiles -- which predate this field being honoured -- keep working.
    """
    sources = discover_sources()
    driver = (config or {}).get("driver") or DEFAULT_DRIVER

    cls = sources.get(driver)
    if cls is None:
        logger.warning(f"Unknown driver {driver!r}; falling back to {DEFAULT_DRIVER}")
        cls = sources.get(DEFAULT_DRIVER)
        if cls is None:
            raise SourceUnavailable(f"no driver {driver!r} and no {DEFAULT_DRIVER} fallback")

    available, reason = cls.is_available()
    if not available:
        raise SourceUnavailable(f"{driver} is unavailable: {reason}")

    kwargs = {k: v for k, v in (config or {}).items() if k != "driver"}
    return cls(**kwargs)
