# Decoder plugin authoring guide

SpectraSDR discovers decoder classes from `src/backend/decoders/`. A plugin can
consume demodulated audio or raw IQ and emit structured events to every
connected client.

The exact API is summarized in the [plugin interface](PLUGIN_INTERFACE.md).
This guide focuses on building and testing a new decoder.

## Quick start

Create `src/backend/decoders/morse.py`:

```python
from collections import deque

import numpy as np

from .base import BaseDecoder, DecoderResult, InputType


class MorseDecoder(BaseDecoder):
    name = "morse"
    description = "Morse code decoder"
    input_type = InputType.AUDIO
    version = "0.1.0"

    def __init__(self, sample_rate: int = 48_000):
        super().__init__(sample_rate=sample_rate)
        self._history = deque(maxlen=200)

    def process_audio(self, samples: np.ndarray):
        # Replace this placeholder with real detection and decoding.
        if not samples.size or float(np.max(np.abs(samples))) < 0.5:
            return

        result = DecoderResult(
            decoder=self.name,
            type="message",
            summary="Detected Morse activity",
            data={"peak": float(np.max(np.abs(samples)))},
        )
        self._history.append(result.to_dict())
        self.emit(result)

    def get_history(self, limit: int = 50) -> list[dict]:
        return list(self._history)[-limit:]

    def reset(self):
        self._history.clear()
```

Restart the backend or reload plugins from Settings → Plugins. The new decoder
appears by its `name` and `description`.

## Choose the input type

Use `InputType.AUDIO` for protocols that operate after audio demodulation, such
as pager or tone decoders. Implement `process_audio(samples)`. Samples are
float32 and normally arrive at 48 kHz.

Use `InputType.IQ` when the decoder needs phase, quadrature, or its own RF
channel filtering. Implement `process_iq(iq_samples)`. Samples are complex64 at
the active radio sample rate.

The current host passes `sample_rate=48_000` to every decoder constructor,
including IQ decoders. Until source metadata is added to the plugin interface,
an IQ plugin must obtain its actual RF sample rate from its own configuration
instead of `self.sample_rate`.

Processing runs inline with the single DSP worker. Keep each call short and
maintain incremental state between chunks. A plugin that performs file, model,
network, or subprocess I/O should move that work to a resource owned by its
lifecycle hooks.

The ADS-B wrapper is a useful example: it declares IQ input for integration
purposes but performs live ingestion on a subprocess-reader thread instead of
processing the server's IQ chunks.

## Emit structured events

Use `DecoderResult` rather than inventing a message envelope:

```python
self.emit(DecoderResult(
    decoder=self.name,
    type="pager",
    summary=f"Page from {address}",
    data={"address": address, "text": text},
    raw=raw_bits,
))
```

Choose a stable `type` value such as `message`, `pager`, `aircraft`, `alert`, or
`measurement`. Keep `summary` short enough for a log row, put machine-readable
fields in `data`, and reserve `raw` for optional diagnostic text.

If the UI needs recent results after reconnecting, append `result.to_dict()` to
a bounded history collection and return it from `get_history()`.

## Manage lifecycle resources

The plugin manager constructs the decoder and calls `init()` while loading it.
Return `False` from `init()` when a required, static dependency is unavailable
and the decoder should be omitted entirely.

`on_enable()` and `on_disable()` run for each user toggle. They should be
idempotent and should own session resources such as threads, sockets, or child
processes. An exception leaves the decoder disabled in the `error` state.

`cleanup()` runs when an instance is unloaded. It must release anything that
could survive `on_disable()`. `reset()` is the public contract for clearing
buffers and history; call it in plugin-specific workflows when a fresh decode
window is required.

Example:

```python
def on_enable(self):
    self._stop.clear()
    self._thread = threading.Thread(target=self._reader, daemon=True)
    self._thread.start()

def on_disable(self):
    self._stop.set()
    if self._thread:
        self._thread.join(timeout=2)
        self._thread = None

def cleanup(self):
    self.on_disable()
```

Override `health_check()` when an `idle`/`running` state is not enough to
diagnose the integration. Start with `super().health_check()` and add fields:

```python
def health_check(self):
    status = super().health_check()
    status["lines_received"] = self._lines_received
    return status
```

## Configuration

Use `appenv.env()` for environment settings so both the current
`SPECTRASDR_` prefix and the migration-only `EVILSDR_` prefix work:

```python
from appenv import env

command = env("MY_DECODER_CMD", "").strip()
```

Users then set `SPECTRASDR_MY_DECODER_CMD`.

For structured configuration, keep a decoder-specific JSON file below the
shared application data directory:

```python
import json

from appenv import data_root


def init(self, **kwargs) -> bool:
    path = data_root() / f"{self.name}.json"
    self._config = json.loads(path.read_text()) if path.exists() else {}
    return True
```

Do not write secrets into emitted events, logs, `spec()`, or `health_check()`.

Plugins cannot register their own HTTP routes or WebSocket commands today.
Changes to those protocols must be added to `SDRServer`.

## Test the plugin

Place tests in `tests/test_morse.py` and import the backend package the same way
as the existing test suite:

```python
from pathlib import Path
import sys

import numpy as np

BACKEND = Path(__file__).resolve().parents[1] / "src" / "backend"
sys.path.insert(0, str(BACKEND))

from decoders.base import DecoderState
from decoders.morse import MorseDecoder


def test_silence_does_not_emit():
    decoder = MorseDecoder()
    emitted = []
    decoder.add_callback(emitted.append)
    decoder.enabled = True

    decoder.process_audio(np.zeros(4_800, dtype=np.float32))

    assert emitted == []


def test_lifecycle_error_is_isolated():
    decoder = MorseDecoder()
    decoder.on_enable = lambda: (_ for _ in ()).throw(RuntimeError("boom"))

    decoder.enabled = True

    assert decoder.enabled is False
    assert decoder.state is DecoderState.ERROR
```

Run the focused test, then the complete suite:

```bash
pytest tests/test_morse.py -q
pytest tests -q
```

Useful additional cases include chunk-boundary handling, empty input, history
limits, malformed configuration, repeat enable/disable cycles, callback
failures, and cleanup after a partial startup.

## Develop with hot reload

The plugin manager checks `src/backend/decoders/*.py` for changes every two
seconds. A change unloads all old instances and creates a fresh plugin set.
Reloaded decoders currently return disabled, so re-enable the decoder in the
UI after each reload.

The current reload path does not evict existing modules from Python's import
cache. Adding or removing a module is detected, but restart the backend to
guarantee that edits to an already-imported module take effect.

Use the Reload All button or send this WebSocket message for a manual reload:

```json
{"type": "RELOAD_DECODERS"}
```

Disable file watching for deterministic test or diagnostic runs:

```bash
SPECTRASDR_DISABLE_WATCHER=1 python src/backend/server.py
```

## Deployment checklist

- The file lives directly in `src/backend/decoders/` and does not begin with
  `_`.
- The class has a unique lowercase `name`.
- The matching `process_audio()` or `process_iq()` method is implemented.
- `get_history()` and `reset()` are implemented.
- Events use `DecoderResult` and contain no secrets.
- Enable, disable, failure, and cleanup paths are tested.
- The full Python test suite passes.
- The plugin appears in Settings → Plugins and reports useful health data.

Dropping in a module is sufficient for a source checkout or writable unpacked
application. A read-only packaged AppImage must be rebuilt to include a new
plugin.
