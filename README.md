# SpectraSDR

## Overview
A software-defined radio receiver for RTL-SDR hardware, driven over `rtl_tcp`.
It shows a live spectrum and waterfall, demodulates AM, FM, NFM and SSB, scans
bands and saved bookmarks, records audio and raw IQ, and decodes POCSAG paging
and ADS-B aircraft traffic through a plugin system.

Runs in the browser against the Python backend, or as a standalone desktop app
via the Electron shell.

![SpectraSDR receiving an FM broadcast station, showing the spectrum plot and waterfall](docs/screenshot.png)

*Receiving a broadcast FM station at 88.7 MHz. Saved bookmarks are blurred.*

## Features
- **High Performance**: Optimized DSP pipeline using FIR filters and polyphase decimation.
- **Stable Streaming**: Ring-buffered audio path for low latency without dropouts.
- **Audio & IQ Recording**:
  - Record demodulated audio to WAV.
  - Capture raw IQ data for offline analysis.
- **Scanning**:
  - **Frequency Scanning**: Sweep a range of frequencies (Start/End/Step) to find active signals.
  - **Memory Scanning**: Cycle through saved bookmarks.
- **Demodulation**:
  - **WBFM**: Wideband FM (Broadcast Radio).
  - **NBFM**: Narrowband FM (Walkie Talkies, Emergency Services).
  - **AM**: Amplitude Modulation (Air Traffic).
  - **USB / LSB**: Single sideband.
- **Decoders** (plugin system with auto-discovery and lifecycle hooks):
  - **POCSAG**: Pager traffic, with BCH(31,21) 2-bit error correction.
  - **ADS-B**: Aircraft positions via `dump1090`, plotted on a live map.
  - Third-party decoders can be dropped in; see [docs/PLUGIN_AUTHORING.md](docs/PLUGIN_AUTHORING.md).
- **Scan history**: Hits logged to SQLite with time-range filters and CSV/JSON export.
- **Configuration**: User-space configuration via `src/backend/config.json`.

## Structure
- `src/backend`: Python SDR interface, DSP pipeline and WebSocket/HTTP server.
- `src/backend/decoders`: Decoder plugins (POCSAG, ADS-B) and the plugin manager.
- `src/frontend`: Web UI — spectrum, waterfall, controls and aircraft map.
- `electron-app`: Electron desktop shell that wraps the backend and UI.
- `tests`: Unit and integration tests.
- `docs`: Project documentation.
- `scripts`: AppImage build script.
- `recordings`: Directory where Audio/IQ files are saved.

## Roadmap
- **Phase 1 (Complete)**: Stable RTL-TCP connection, minimal DSP, basic waterfall/spectrum visualization.
- **Phase 2 (Complete)**: Audio demodulation (WBFM/NBFM), Audio/IQ Recording, and upgraded FIR-based DSP.
- **Phase 3 (Complete)**:
  - Connection manager profiles with persisted host/port settings.
  - Scanner hit logging (SQLite) + frontend history panel, time-range filters, CSV export.
  - Decoder lifecycle hooks + plugin auto-discovery + plugin status UI.
  - ADS-B via `dump1090` subprocess orchestration and aircraft event normalization
    (`src/backend/decoders/adsb_wrapper.py`).
  - POCSAG BCH(31,21) 2-bit error correction with known-good fixtures.
- **Phase 4 (In progress)**:
  - ADS-B map UI (complete): Leaflet aircraft map in a movable, resizable
    window, shown only while the ADS-B decoder is enabled.
  - POCSAG inverted-polarity search and DC-offset-tolerant bit slicing.
  - Per-profile scan analytics.
  - TV/ATV experimental decoder path.

## Getting Started

### Prerequisites
- Python 3.9+
- RTL-SDR dongle (and `rtl_tcp` running or accessible)
- Node.js — only for the optional Electron desktop shell
- `dump1090` — only for the ADS-B decoder

### Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/EvalAlan/SpectraSDR.git
   cd SpectraSDR
   ```
2. Create a virtual environment (recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### Configuration
1. Copy the example configuration:
   ```bash
   cp src/backend/config.json.example src/backend/config.json
   ```
2. Edit `src/backend/config.json` to match your environment (e.g., `rtl_host`, `rtl_port`).

### Running
1. Start the backend server:
   ```bash
   python src/backend/server.py
   ```
2. Open the frontend in your browser:
   ```
   http://localhost:5555
   ```

The HTTP port is `http_port` in `config.json`; the WebSocket stream uses
`ws_port` separately.

### Desktop app
The Electron shell starts the backend itself and opens the UI in its own
window, so there is no browser step:

```bash
cd electron-app
npm install
npm start
```

To build a self-contained Linux AppImage:

```bash
cd electron-app && npm install && npm run build
cd .. && ./scripts/build_electron_appimage.sh
```

The AppImage is written to the repository root. It bundles a relocatable
CPython from [python-build-standalone](https://github.com/astral-sh/python-build-standalone)
along with the backend's dependencies, so it does not require Python on the
host — the only runtime requirement is a reachable `rtl_tcp`.
