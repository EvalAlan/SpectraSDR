# SpectraSDR Decoder Plugin Interface

> **New here?** Read the full [Plugin Authoring Guide](PLUGIN_AUTHORING.md) first.
> This document is the concise reference for the minimal contract.

This is the minimal contract any new decoder plugin must satisfy so it can slot into the phase‑4 decoder pipeline without touching the rest of the stack.

## Anatomy

* **Base class:** `backend.decoders.base.BaseDecoder` (exported by `backend.decoders`).
* **Discovery:** `backend.decoders.__init__.discover_decoders()` scans `backend/decoders/` for any concrete `BaseDecoder` subclasses and uses `load_decoders()` to instantiate them with the current sample rate.
* **Input types:** The core accepts either `InputType.AUDIO` (FM demodulated audio) or `InputType.IQ` (raw complex samples). Set `input_type` accordingly.
* **Callbacks:** Plugins **must** emit `DecoderResult` instances via `self.emit(...)`. Raw dicts are accepted for backward compat but lose UI features (type badge, summary line, structured data panel). See [DecoderResult](#dataclass-decoderresult).
* **Hot-reload:** The `PluginManager` watches the decoders/ directory and supports runtime reload via the `RELOAD_DECODERS` WebSocket command.

## Minimal skeleton

```python
from backend.decoders.base import BaseDecoder, InputType, DecoderResult
import numpy as np

class TemplateDecoder(BaseDecoder):
    """Minimal plugin entry point for testing. """

    name = "template"
    description = "Example decoder that echoes peak values."
    input_type = InputType.AUDIO
    version = "0.1.0"

    def __init__(self, sample_rate: int = 48000):
        super().__init__(sample_rate=sample_rate)
        self._history: list[dict] = []

    def process_audio(self, samples: np.ndarray):
        peak = float(np.max(np.abs(samples))) if samples.size else 0.0
        result = DecoderResult(
            decoder=self.name,
            type="measurement",
            summary=f"peak={peak:.3f}",
            data={"peak": peak},
        )
        self._history.append(result.to_dict())
        self.emit(result)

    def get_history(self, limit: int = 50) -> list[dict]:
        return self._history[-limit:]

    def reset(self):
        self._history.clear()
```

## Lifecycle

```
init() ──► on_enable() ──► process_audio/iq() ──► on_disable() ──► cleanup()
```

- `init()` — one-time setup, return False to skip loading
- `on_enable()` / `on_disable()` — per-session resource management
- `cleanup()` — one-time teardown on unload
- `reset()` — clear decode buffers (called on mode change / scanner stop)
- `health_check()` — return `{"healthy": bool, "state": str, "error": str|None}`
- `spec()` — return full capability descriptor (used by UI)

## Hooking into the server

1. The backend `server.py` uses `PluginManager` which calls `load_decoders()` once during startup.
2. Each decoder's callbacks are automatically attached to the WebSocket broadcast.
3. Keep decoder state idempotent: `reset()` is invoked whenever the scanner stops or the user flips modes.
4. Hot-reload is automatic — edit a `.py` file in `backend/decoders/` and changes apply within ~2 seconds.

Drop new plugins under `backend/decoders/`. They will be auto-discovered (just avoid `template`/test helpers if you don't want them loaded in production).

## Server Protocol

| Direction | Message | Purpose |
|-----------|---------|---------|
| C→S | `LIST_DECODERS` | Request all decoder specs |
| S→C | `DECODER_LIST` | Response with `[{name, description, version, input_type, state, ...}]` |
| C→S | `TOGGLE_DECODER` `{name, value}` | Enable/disable a decoder |
| S→C | `DECODER_STATE` `{name, enabled}` | State change notification |
| C→S | `GET_DECODER_STATUS` `{name?}` | Query health (all if no name) |
| S→C | `DECODER_STATUS` `{status: {name, state, healthy, error}}` or `{all: [...]}` | Health response |
| C→S | `RELOAD_DECODERS` | Hot-reload all plugins |

## Dataclass DecoderResult

```python
@dataclass
class DecoderResult:
    decoder: str              # Auto-set from self.name if omitted
    timestamp: float          # Auto-set to time.time()
    type: str = "generic"     # Event type: "pager", "aircraft", "message", etc.
    summary: str = ""         # One-line human-readable (shown in log)
    data: dict = {}           # Full payload (shown in expandable detail)
    raw: Optional[str] = None # Raw hex/text for debug panel
```

The UI renders `type` as a colored badge, `summary` in the message log, and `data` in an expandable JSON viewer.