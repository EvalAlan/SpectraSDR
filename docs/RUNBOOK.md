# SpectraSDR runbook

This runbook covers development smoke tests, runtime overrides, migration
behavior, and Linux release checks. Installation and first-run instructions
are in the repository [README](../README.md).

## Backend smoke test

Create a clean environment and launch the server:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python src/backend/server.py
```

Expected startup behavior:

- WebSocket listener on `0.0.0.0:8765`.
- HTTP listener on `0.0.0.0:5555`.
- The UI loads at <http://localhost:5555>.
- `/api/connections`, `/api/scan_hits`, and `/api/adsb` return JSON.
- Failure to reach `rtl_tcp` is reported without preventing the HTTP UI from
  starting.

The bundled frontend assumes WebSocket port `8765`; the Electron launcher
assumes HTTP port `5555`. Non-default values in `config.json` therefore require
matching application changes.

## Test and lint checks

Runtime requirements do not install development tools. Install them explicitly
in the active environment:

```bash
python -m pip install pytest ruff
pytest tests -q
ruff check src tests
cd electron-app && npm test
```

`src/backend/test_thread_safety.py` is a manual stress utility rather than part
of the normal `tests/` suite. With the server running, invoke it separately:

```bash
python src/backend/test_thread_safety.py
```

## Runtime files and overrides

Direct backend runs use repository-local defaults. Electron-based launches set
explicit paths beneath an application data directory.

The backend recognizes these variables:

| Variable | Purpose | Direct-run default |
| --- | --- | --- |
| `SPECTRASDR_CONFIG_FILE` | Main server configuration | `src/backend/config.json` |
| `SPECTRASDR_BOOKMARKS_FILE` | Bookmark data | `src/backend/bookmarks.json` |
| `SPECTRASDR_CONNECTIONS_FILE` | Saved profiles | `src/backend/connections.json` |
| `SPECTRASDR_RECORDINGS_DIR` | WAV and IQ output | `recordings/` |
| `SPECTRASDR_SCAN_HITS_DB` | SQLite history | Beside `connections.json` |
| `SPECTRASDR_SCAN_HITS_RETENTION_DAYS` | Retention window | `30` |
| `SPECTRASDR_DUMP1090_CMD` | ADS-B subprocess command | Unset |
| `SPECTRASDR_DISABLE_WATCHER` | Disable decoder file watching when non-empty | Unset |
| `SPECTRASDR_DATA_ROOT` | Shared base directory for plugin data | `src/backend/` |

The launchers also export `SPECTRASDR_METADATA_PREFS_FILE` for compatibility,
although the current backend does not consume that file.

## Migration from evilSDR

The former `EVILSDR_` environment names remain fallback aliases in
`src/backend/appenv.py`. When both prefixes are set, `SPECTRASDR_` takes
precedence.

The Electron and AppImage launchers attempt a one-time move from the former
`evilSDR` data directory. Migration is skipped when the current SpectraSDR
directory already exists, preventing stale data from replacing a current
installation.

After upgrading an existing installation, verify that connection profiles,
bookmarks, recordings, and scan history still appear before removing any
manual backup of the old data directory.

## ADS-B integration

Set the `dump1090` command before starting the backend:

```bash
export SPECTRASDR_DUMP1090_CMD='dump1090 --net --quiet --write-json /tmp/d1090'
python src/backend/server.py
```

Then enable ADS-B under Settings → Plugins. Check both endpoints while
diagnosing ingestion:

```text
/api/adsb/process_status
/api/adsb?limit=100
```

With no configured command, the plugin loads in an idle state and can still
parse lines supplied by code or tests, but it receives no live subprocess
input.

## Electron development check

From the repository root:

```bash
cd electron-app
npm install
npm start
```

Confirm that the backend starts, the window reaches the UI, closing the window
terminates the child backend, and settings persist across a restart.

## Build and verify the Linux AppImage

The build requires Node.js/npm, `rsync`, `curl`, and `tar`. It downloads a
relocatable CPython runtime and `appimagetool` on the first run.

```bash
cd electron-app
npm ci
npm run build
cd ..
./scripts/build_electron_appimage.sh
```

`electron-builder` writes its unpacked application below `electron-app/dist/`.
The AppImage script assembles `build/electron-appimage/` and writes the final
`*.AppImage` to the repository root.

Release smoke checklist:

- Launch succeeds on a machine without a system Python installation.
- The UI loads and connects to the backend.
- An RTL-TCP profile connects and Start/Stop controls streaming.
- Spectrum, waterfall, and audio update.
- Audio and IQ recordings are created in persistent user storage.
- Scan history loads and exports both CSV and JSON.
- The aircraft map appears only while ADS-B is enabled.
- Bookmarks, profiles, and recordings remain after restarting the app.
