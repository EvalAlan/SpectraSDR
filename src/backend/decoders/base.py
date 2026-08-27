"""Base Decoder class for SpectraSDR plugin architecture.

All signal decoders should subclass BaseDecoder and implement the required methods.
Decoders are automatically discovered and loaded from the decoders/ directory.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Optional
import logging
import numpy as np
import time

logger = logging.getLogger(__name__)


class InputType(Enum):
    """Types of input a decoder can accept."""
    AUDIO = auto()   # FM-demodulated audio samples (float32)
    IQ = auto()      # Raw IQ samples (complex64)


class DecoderState(Enum):
    """Runtime state of a decoder."""
    IDLE = "idle"
    RUNNING = "running"
    ERROR = "error"


@dataclass
class DecoderResult:
    """Standard output container for decoded messages.

    All decoder emit() calls should use this structure so the UI and
    downstream consumers can render uniformly.
    """
    decoder: str                         # decoder name (set automatically)
    timestamp: float = field(default_factory=time.time)
    type: str = "generic"                # event type: "message", "aircraft", "alert", etc.
    summary: str = ""                    # one-line human-readable summary
    data: dict = field(default_factory=dict)  # arbitrary decoder-specific payload
    raw: Optional[str] = None            # optional raw text/hex for debug

    def to_dict(self) -> dict:
        return {
            "decoder": self.decoder,
            "timestamp": self.timestamp,
            "type": self.type,
            "summary": self.summary,
            "data": self.data,
            "raw": self.raw,
        }


class BaseDecoder(ABC):
    """Abstract base class for all signal decoders.

    Subclasses must:
      - Set `name`, `description`, `input_type`, and optionally `version` class attributes.
      - Implement `process_audio()` and/or `process_iq()` depending on `input_type`.
      - Implement `get_history()` to return recently decoded messages.
      - Implement `reset()` to clear internal state.

    The `emit()` helper pushes decoded data to all registered callbacks.
    The `init()` / `cleanup()` lifecycle hooks manage setup/teardown.
    `health_check()` can be overridden for runtime diagnostics.
    """

    # --- Class attributes (override in subclass) ---
    name: str = "base"
    description: str = "Abstract base decoder"
    input_type: InputType = InputType.AUDIO
    version: str = "0.1.0"
    author: str = ""

    def __init__(self, sample_rate: int = 48000):
        self.sample_rate = sample_rate
        self._callbacks: list[Callable[[dict], Any]] = []
        self.state: DecoderState = DecoderState.IDLE
        self._enabled: bool = False
        self._error_message: Optional[str] = None
        self._init_called: bool = False

    # --- Callback management ---

    def add_callback(self, callback: Callable[[dict], Any]):
        """Register a callback that receives decoded messages (dicts)."""
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[dict], Any]):
        """Unregister a callback."""
        try:
            self._callbacks.remove(callback)
        except ValueError:
            pass

    def set_callback(self, callback: Optional[Callable[[dict], Any]]):
        """Convenience: set a single callback (clears previous ones)."""
        self._callbacks.clear()
        if callback is not None:
            self._callbacks.append(callback)

    def emit(self, message):
        """Push a decoded message to all registered callbacks.

        Accepts either a dict or a DecoderResult.
        """
        if isinstance(message, DecoderResult):
            message = message.to_dict()
        message.setdefault("decoder", self.name)
        for cb in self._callbacks:
            try:
                cb(message)
            except Exception:
                logger.exception(f"Callback error in decoder '{self.name}'")

    # --- Enable / disable ---

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        was_enabled = self._enabled
        self._enabled = value
        self.state = DecoderState.RUNNING if value else DecoderState.IDLE
        self._error_message = None
        try:
            if value and not was_enabled:
                self._init_called = True
                self.on_enable()
            elif (not value) and was_enabled:
                self.on_disable()
        except Exception as e:
            logger.exception("Decoder lifecycle hook failed: %s", self.name)
            self.state = DecoderState.ERROR
            self._enabled = False
            self._error_message = str(e)

    @property
    def error_message(self) -> Optional[str]:
        return self._error_message

    # --- Lifecycle hooks ---

    def on_enable(self):
        """Lifecycle hook when decoder is enabled. Override to allocate resources."""
        pass

    def on_disable(self):
        """Lifecycle hook when decoder is disabled. Override to release resources."""
        pass

    def init(self, **kwargs) -> bool:
        """One-time initialization. Called before the first on_enable().

        Override for expensive setup (model loading, config parsing, etc.).
        Return False to signal the decoder should not be loaded.
        """
        return True

    def cleanup(self):
        """One-time teardown. Called when the decoder is being unloaded (hot-reload shutdown)."""
        pass

    def health_check(self) -> dict:
        """Return health/diagnostic info. Override for runtime checks."""
        return {
            "healthy": self.state != DecoderState.ERROR,
            "state": self.state.value,
            "error": self._error_message,
        }

    # --- Input processing ---

    def process_audio(self, samples: np.ndarray):
        """Process FM-demodulated audio samples (float32).

        Override this if input_type includes AUDIO.
        Default implementation is a no-op.
        """
        pass

    def process_iq(self, iq_samples: np.ndarray):
        """Process raw IQ samples (complex64).

        Override this if input_type is IQ.
        Default implementation is a no-op.
        """
        pass

    # --- Required overrides ---

    @abstractmethod
    def get_history(self, limit: int = 50) -> list[dict]:
        """Return recent decoded messages as a list of dicts."""
        ...

    @abstractmethod
    def reset(self):
        """Clear internal buffers and state."""
        ...

    # --- Info ---

    def spec(self) -> dict:
        """Return a full capability descriptor for this decoder.

        Override to declare additional capabilities, config schema, etc.
        """
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "input_type": self.input_type.name.lower(),
            "enabled": self.enabled,
            "state": self.state.value,
            "error": self._error_message,
        }

    def info(self) -> dict:
        """Return metadata about this decoder for the UI. (Backward compat — calls spec().)"""
        return self.spec()

    def __repr__(self):
        return f"<{self.__class__.__name__} name={self.name!r} enabled={self.enabled}>"
