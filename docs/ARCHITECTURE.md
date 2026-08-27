# SpectraSDR architecture

This document describes the current tracked implementation. Historical design
ideas live in the phase documents and may not match the running application.

## Runtime overview

```text
rtl_tcp
   │ unsigned 8-bit interleaved IQ
   ▼
RTLTCPClient ──► raw asyncio queue ──► DSP worker
                                           │
                   ┌───────────────────────┼──────────────────────┐
                   ▼                       ▼                      ▼
             FFT / spectrum          demodulated audio      raw IQ capture
                   │                       │
                   │               ┌───────┼─────────┐
                   │               ▼       ▼         ▼
                   │           WAV file  scanner  audio decoders
                   │                                 │
                   └───────────────┬─────────────────┘
                                   ▼
                         WebSocket broadcasts
                                   ▼
                         static browser frontend
```

[`server.py`](../src/backend/server.py) owns the application lifecycle and
connects all of these components.

## Backend components

### Server and transport

The backend runs one asyncio event loop with two network listeners:

- HTTP on port `5555` serves `src/frontend/` and JSON/export endpoints.
- WebSocket on port `8765` carries control messages and real-time spectrum,
  audio, scanner, connection, and decoder events.

The ports come from `config.json`, although the bundled frontend and Electron
shell currently expect the defaults.

### Radio and DSP

[`rtl_client.py`](../src/backend/rtl_client.py) implements the `rtl_tcp`
protocol and radio controls. Raw chunks enter a bounded asyncio queue.

[`dsp.py`](../src/backend/dsp.py) converts IQ samples into FFT bins and
demodulated 48 kHz audio. CPU-bound chunk processing runs through a
single-worker `ThreadPoolExecutor`, preserving sample order.

### Scanning and persistence

[`scanner.py`](../src/backend/scanner.py) supports bookmark-category and
frequency-range scans. It tunes through the same RTL-TCP client used by normal
streaming and emits status and hit callbacks.

[`scan_history.py`](../src/backend/scan_history.py) stores scan hits and ADS-B
aircraft observations in SQLite. The HTTP API provides filters, analytics,
retention pruning, and CSV/JSON export.

### Decoder plugins

[`decoders/__init__.py`](../src/backend/decoders/__init__.py) discovers
concrete `BaseDecoder` subclasses. The
[`PluginManager`](../src/backend/decoders/plugin_manager.py) loads them,
attaches broadcast callbacks, exposes lifecycle controls, and watches the
decoder directory during development.

Audio plugins receive demodulated float32 samples. IQ plugins receive complex64
samples. Decoder output is normalized through `DecoderResult` before being
broadcast to clients.

The built-in plugins are:

- POCSAG, implemented fully in Python.
- ADS-B, implemented as a wrapper around an optional `dump1090` subprocess.

## Frontend

The frontend is static HTML, CSS, and JavaScript with no compilation step.
[`app.js`](../src/frontend/app.js) manages receiver controls, WebSocket state,
spectrum/waterfall rendering, scanning, history, and plugins.
[`map.js`](../src/frontend/map.js) manages the ADS-B aircraft map.
[`audio-processor.js`](../src/frontend/audio-processor.js) is the Web Audio
worklet used for playback.

## Electron shell

[`electron-app/src/main.js`](../electron-app/src/main.js) creates a desktop
window, prepares persistent user data, starts `server.py`, waits for HTTP port
`5555`, and loads the backend URL. Packaged builds prefer the bundled Python
runtime; source runs prefer `.venv/bin/python` and otherwise fall back to
`python3`.

## Concurrency model

- Asyncio owns sockets, client queues, connection management, and scanner
  coordination.
- A single DSP executor worker processes radio chunks in order.
- Locks protect client state, DSP mutations, recordings, and saved connection
  profiles across the event-loop and worker threads.
- Decoder-specific background work, such as the ADS-B subprocess reader, is
  owned by that decoder's lifecycle hooks.

See [`THREAD_SAFETY.md`](../src/backend/THREAD_SAFETY.md) for the historical
thread-safety refactor record.

## Persistent data

Direct source runs default to repository-local files. Electron-based launches
set environment overrides to an application data directory. The backend uses
the following data:

| Data | Default for a direct source run |
| --- | --- |
| Main configuration | `src/backend/config.json` |
| Bookmarks | `src/backend/bookmarks.json` |
| Connection profiles | `src/backend/connections.json` |
| Scan history | Beside `connections.json` as `scan_hits.sqlite3` |
| Recordings | `recordings/` |

`appenv.py` resolves `SPECTRASDR_*` variables and accepts the former
`EVILSDR_*` names as fallback aliases.

## Extension boundaries

- Add signal decoders through the documented `BaseDecoder` interface.
- Add HTTP or WebSocket commands in `SDRServer`; plugins cannot register custom
  commands independently today.
- A source abstraction and synthetic driver exist under `src/backend/sources/`,
  but the tracked server still connects through `RTLTCPClient`. Completing
  multi-source support requires integration at the server, scanner, connection
  profile, and frontend capability boundaries.
