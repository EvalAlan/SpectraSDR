# SpectraSDR Plugin Authoring Guide

This guide covers everything you need to write, test, and deploy a decoder
plugin for SpectraSDR.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Architecture Overview](#architecture-overview)
3. [BaseDecoder API Reference](#basedecoder-api-reference)
4. [InputType and DecoderResult](#inputtype-and-decoderresult)
5. [Lifecycle Hooks](#lifecycle-hooks)
6. [Configuration Patterns](#configuration-patterns)
7. [Testing Your Plugin](#testing-your-plugin)
8. [Hot-Reload Development](#hot-reload-development)
9. [Deploying a Plugin](#deploying-a-plugin)
10. [Best Practices](#best-practices)

---

## Quick Start

Create a new file in `src/backend/decoders/`:

```python
"""src/backend/decoders/morse.py — Minimal Morse code decoder plugin."""

import numpy as np
from .base import BaseDecoder, InputType, DecoderResult

class MorseDecoder(BaseDecoder):
    name = "morse"
    description = "Morse code decoder (CW)"
    input_type = InputType.AUDIO
    version = "0.1.0"

    def __init__(self, sample_rate: int = 48000):
        super().__init__(sample_rate=sample_rate)
        self._history: list[dict] = []

    def process_audio(self, samples: np.ndarray):
        # Your decode logic here
        result = DecoderResult(
            decoder=self.name,
            type="message",
            summary="Decoded Morse text",
            data={"text": "CQ CQ"},
        )
        self._history.append(result.to_dict())
        self.emit(result)

    def get_history(self, limit: int = 50) -> list[dict]:
        return self._history[-limit:]

    def reset(self):
        self._history.clear()
```

That's it. Drop it in the directory — it will be auto-discovered on next
server start or hot-reload.

---

## Architecture Overview

```
┌──────────────────────────────────────────────┐
│  SDRServer (server.py)                       │
│    │                                         │
│    └── PluginManager (plugin_manager.py)     │
│          ├── discover_decoders()             │
│          ├── load_decoders()                 │
│          │     └── BaseDecoder subclasses    │
│          ├── file watcher thread             │
│          └── reload()                        │
│                                               │
│  Frontend (app.js)                            │
│    └── Plugin status panel                   │
│          ├── dynamic decoder list            │
│          ├── enable/disable toggles           │
│          └── reload button                   │
└──────────────────────────────────────────────┘
```

**Auto-discovery**: `discover_decoders()` uses `pkgutil.iter_modules()` to
scan every `.py` file in `src/backend/decoders/`. Classes that subclass
`BaseDecoder` (and have no remaining abstract methods) are automatically
found and instantiated.

**Naming**: Files starting with `_` or named `base.py` are skipped.
Everything else is imported.

---

## BaseDecoder API Reference

### Class Attributes (Required)

| Attribute | Type | Description |
|-----------|------|-------------|
| `name` | `str` | Unique identifier (e.g. `"pocsag"`) |
| `description` | `str` | Human-readable description |
| `input_type` | `InputType` | `InputType.AUDIO` or `InputType.IQ` |
| `version` | `str` | Semver string, e.g. `"0.1.0"` |
| `author` | `str` | Optional author name |

### Required Abstract Methods

#### `get_history(limit: int = 50) -> list[dict]`
Return the most recent decoded messages as a list of dicts. The UI uses
this to populate the message history panel. Each dict *should* contain at
minimum: `decoder`, `timestamp`, `type`, `summary`.

#### `reset()`
Clear all internal buffers and state. Called when the user flips modes
or the scanner stops.

### Input Processing (Override One)

#### `process_audio(samples: np.ndarray)`
Called when `input_type == InputType.AUDIO`. Receives FM-demodulated
audio samples as a float32 numpy array.

#### `process_iq(iq_samples: np.ndarray)`
Called when `input_type == InputType.IQ`. Receives raw IQ samples as
a complex64 numpy array.

### Emitting Results

#### `emit(message)`
Push a decoded result to all registered callbacks (WebSocket clients).
Accepts either a `dict` or a `DecoderResult` instance.

**Required pattern** — always use `DecoderResult`:
```python
self.emit(DecoderResult(
    decoder=self.name,         # Optional — auto-set from self.name
    type="message",            # Event type for UI filtering/badge
    summary=f"Page from {address}",  # One-line shown in log
    data={"address": address, "text": text},  # Structured payload
    raw="optional hex/text",   # Shown in debug panel (optional))
))
```

The `type` field controls the badge color in the UI. Common values: `"pager"`, `"aircraft"`, `"message"`, `"alert"`, `"measurement"`, `"generic"`.

**Backward compat** — raw dicts still work but lose the type badge, summary line, and structured data panel. All new plugins should use `DecoderResult`.

---

## InputType and DecoderResult

### InputType Enum

- `InputType.AUDIO` — FM-demodulated audio (float32). Use for voice, pager, Morse, etc.
- `InputType.IQ` — Raw complex IQ samples (complex64). Use for protocols that need the RF layer.

### DecoderResult Dataclass

```python
@dataclass
class DecoderResult:
    decoder: str              # Auto-set if you pass to emit()
    timestamp: float          # Auto-set to time.time()
    type: str = "generic"     # Event type for UI filtering
    summary: str = ""         # One-line human-readable
    data: dict = {}           # Decoder-specific payload
    raw: Optional[str] = None # Raw hex/text for debug panel
```

The UI renders `type` as a badge, `summary` in the log, and `data`
in an expandable detail view.

---

## Lifecycle Hooks

```
init() ──► on_enable() ──► process_audio/iq() ──► on_disable() ──► cleanup()
```

### `init(**kwargs) -> bool`
One-time setup. Called once before the first `on_enable()`. Return
`False` to signal the decoder should not be loaded (plugin manager
will skip it with a warning).

Use for: loading ML models, parsing config files, opening databases.

```python
def init(self, **kwargs) -> bool:
    model_path = kwargs.get("model_path", "default_model.pkl")
    if not Path(model_path).exists():
        logger.error(f"Model not found: {model_path}")
        return False
    self._model = load_model(model_path)
    return True
```

### `on_enable()`
Called every time the user enables the decoder. Allocate per-session
resources here. If this raises an exception, the decoder is set to
`ERROR` state and stays disabled.

Use for: starting reader threads, subscribing to external feeds.

### `on_disable()`
Called when the user disables the decoder. Release per-session
resources allocated in `on_enable()`.

Use for: stopping threads, closing connections, flushing buffers.

### `cleanup()`
One-time teardown. Called when the decoder is being permanently
unloaded (hot-reload shutdown or server exit).

Use for: deleting temp files, unregistering from external services.

### `health_check() -> dict`
Return a dict with at minimum `{"healthy": bool, "state": str, "error": str|None}`.
Override for runtime diagnostics (connection alive, model loaded, etc.).

---

## Configuration Patterns

### Environment Variables (recommended for external integrations)

```python
import os

class ADSBWrapperDecoder(BaseDecoder):
    def on_enable(self):
        cmd = os.environ.get("SPECTRASDR_DUMP1090_CMD", "").strip()
        if not cmd:
            return  # UI shows "not configured" via spec()
        # ... start subprocess
```

### Plugin Config File (recommended for complex settings)

Store a `my_decoder.json` in the user's SpectraSDR data directory. Locate it
with `appenv.data_root()` — that resolves `SPECTRASDR_DATA_ROOT`, which both
launchers export to the directory they keep config, bookmarks and recordings
in. Read it in `init()`:

```python
import json
from appenv import data_root

def init(self, **kwargs) -> bool:
    config_path = data_root() / f"{self.name}.json"
    if config_path.exists():
        self._config = json.loads(config_path.read_text())
    else:
        self._config = self.DEFAULT_CONFIG
    return True
```

### Server Command (advanced)

To add custom WebSocket commands from your plugin, register a handler
via the server's message dispatch. This is not directly exposed today —
open an issue if you need it.

---

## Hot-Reload Development

The plugin manager watches `src/backend/decoders/` for file changes
every 2 seconds. When a `.py` file is added, removed, or modified:

1. All old decoder instances are `on_disable()`'d and `cleanup()`'d.
2. The decoders package is re-imported.
3. New instances are `init()`'d and instantiated.
4. Enabled state is preserved for decoders that still exist.
5. All connected clients receive a `DECODER_LIST` update.

### Disable the watcher (for reproducible runs / CI)

```bash
SPECTRASDR_DISABLE_WATCHER=1 python src/backend/server.py
```

### Manual reload (from the frontend)

Click **Reload All** in the Plugins settings tab, or send:
```json
{"type": "RELOAD_DECODERS"}
```

---

## Testing Your Plugin

SpectraSDR uses `pytest`. Place tests in `tests/`:

```python
"""tests/test_morse.py"""
import pathlib
import sys
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "src" / "backend"
sys.path.insert(0, str(BACKEND))

from decoders.morse import MorseDecoder


def test_morse_minimal():
    dec = MorseDecoder(sample_rate=48000)
    assert dec.name == "morse"
    assert dec.input_type.name == "AUDIO"
    assert dec.enabled is False


def test_morse_process_and_history():
    dec = MorseDecoder()
    dec.enabled = True
    # Feed silence — should not crash
    dec.process_audio(np.zeros(4800, dtype=np.float32))
    history = dec.get_history()
    assert isinstance(history, list)


def test_morse_lifecycle_failure():
    """If on_enable raises, decoder should be in ERROR state and disabled."""
    dec = MorseDecoder()
    dec.on_enable = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    dec.enabled = True
    assert dec.enabled is False
    assert dec.state.value == "error"


def test_morse_spec():
    dec = MorseDecoder()
    spec = dec.spec()
    assert "name" in spec
    assert "version" in spec
    assert "state" in spec
```

Run with:
```bash
cd /path/to/SpectraSDR
python -m pytest tests/ -v
```

---

## Deploying a Plugin

1. **Create** your `<name>.py` in `src/backend/decoders/`.
2. **Test**: `python -m pytest tests/test_<name>.py -v`
3. **Restart** the server, or click **Reload All** in the UI.
4. **Verify**: Open Settings → Plugins tab. Your decoder should appear
   with an enable toggle.

That's it. No registration, no config changes, no rebuild.

---

## Best Practices

- **Keep decoders stateless across enable/disable cycles.** Use
  `on_enable()`/`on_disable()` for setup/teardown, and `reset()` for
  clearing decode buffers.

- **Use `DecoderResult` for new plugins.** The structured format gives
  you free UI rendering. Raw dicts still work but miss features.

- **Don't block.** `process_audio()` / `process_iq()` are called from
  the processing thread pool. Heavy computation should be offloaded to
  a background thread or processed in small chunks.

- **Graceful degradation.** If your model file is missing, return `False`
  from `init()`. The UI shows the decoder as unavailable.

- **Name collisions.** The `name` attribute is the unique key. Two
  plugins with the same name will overwrite each other — last one wins.

- **File naming.** Avoid `_` prefix (reserved for internal modules) and
  `base.py` (skipped by discovery).

- **Version your plugin.** The `version` attribute is shown in the UI.
  Use semver so users can tell if a reload picked up a new version.
