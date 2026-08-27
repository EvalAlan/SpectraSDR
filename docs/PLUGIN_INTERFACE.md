# Decoder plugin interface

This is the concise contract for decoder plugins. For a walkthrough and test
examples, see the [plugin authoring guide](PLUGIN_AUTHORING.md).

## Discovery

Plugins are Python modules in `src/backend/decoders/`. Discovery imports every
module except `base.py` and files whose names begin with `_`, then selects each
concrete subclass of `BaseDecoder`. The class-level `name` is the registry key;
duplicate names overwrite one another in discovery order.

Use package-relative imports inside a plugin:

```python
from .base import BaseDecoder, DecoderResult, InputType
```

## Required contract

A useful decoder defines these class attributes:

| Attribute | Type | Meaning |
| --- | --- | --- |
| `name` | `str` | Unique lowercase registry and protocol name |
| `description` | `str` | User-facing description |
| `input_type` | `InputType` | `AUDIO` or `IQ` |
| `version` | `str` | User-facing plugin version |
| `author` | `str` | Optional author name |

Every concrete decoder must implement:

```python
def get_history(self, limit: int = 50) -> list[dict]: ...
def reset(self) -> None: ...
```

Override the processor matching `input_type`:

```python
def process_audio(self, samples: np.ndarray) -> None: ...
def process_iq(self, iq_samples: np.ndarray) -> None: ...
```

`AUDIO` receives demodulated float32 samples, normally at 48 kHz. `IQ`
receives complex64 baseband samples at the active radio sample rate. Processing
runs in the server's single DSP worker, so a plugin must not block for extended
periods.

The current server constructs every plugin with `sample_rate=48000`, including
IQ plugins. IQ authors should not treat `self.sample_rate` as the RF rate until
the host passes source metadata through the plugin API.

## Lifecycle

```text
construct → init → on_enable → process_* → on_disable → cleanup
```

- `init(**kwargs) -> bool` runs once when the plugin is loaded. Returning
  `False` excludes the instance from the registry.
- `on_enable()` and `on_disable()` own per-session resources.
- `reset()` is the public operation for clearing buffered decode state and
  history. The current server does not invoke it automatically.
- `cleanup()` releases resources when a plugin instance is unloaded.
- `health_check()` returns runtime health information.
- `spec()` returns the capability record shown in the UI.

Lifecycle exceptions move the decoder to the `error` state and leave it
disabled.

Editing decoder files triggers a registry reload while the watcher is active.
Current reload behavior creates fresh, disabled instances, so callers should
re-enable any decoder they still need. Existing Python modules are not evicted
from the import cache; restart the backend to guarantee that edits to an
already-loaded module take effect.

## Decoder output

Prefer `DecoderResult` for every emitted event:

```python
DecoderResult(
    decoder="morse",
    type="message",
    summary="CQ CQ",
    data={"text": "CQ CQ"},
    raw=None,
)
```

Its fields are:

| Field | Type | Behavior |
| --- | --- | --- |
| `decoder` | `str` | Required plugin name |
| `timestamp` | `float` | Defaults to `time.time()` |
| `type` | `str` | Event category; defaults to `generic` |
| `summary` | `str` | Short user-facing line |
| `data` | `dict` | Structured plugin-specific payload |
| `raw` | `str \| None` | Optional diagnostic representation |

Call `self.emit(result)` to deliver the event. Raw dictionaries remain
supported for compatibility; `emit()` inserts the decoder name when it is
missing, but structured results provide the most consistent UI data.

## Default capability and health records

`spec()` returns:

```json
{
  "name": "morse",
  "description": "Morse code decoder",
  "version": "0.1.0",
  "author": "",
  "input_type": "audio",
  "enabled": false,
  "state": "idle",
  "error": null
}
```

`health_check()` returns `healthy`, `state`, and `error`. Plugins may extend
either method with decoder-specific fields.

## WebSocket control messages

| Direction | Message | Purpose |
| --- | --- | --- |
| Client → server | `LIST_DECODERS` | Request all plugin specs |
| Server → client | `DECODER_LIST` | Return the current specs |
| Client → server | `TOGGLE_DECODER` with `name`, `value` | Enable or disable a plugin |
| Server → client | `DECODER_STATE` | Announce the requested state change |
| Client → server | `GET_DECODER_STATUS` with optional `name` | Request one or all health records |
| Server → client | `DECODER_STATUS` | Return `status` or `all` records |
| Client → server | `RELOAD_DECODERS` | Replace all plugin instances |

Decoded events are broadcast with the uppercased decoder name as the outer
WebSocket `type` and the plugin payload under `message`.
