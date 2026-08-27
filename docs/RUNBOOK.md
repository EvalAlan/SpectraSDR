# SpectraSDR Runbook

## Backend smoke test

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python src/backend/server.py
```

Expect:
- WS on `:8765`
- HTTP on `:5555`
- `/api/connections`, `/api/scan_hits`, `/api/adsb` return JSON

## Test + lint gates

```bash
ruff check src tests
pytest tests -q
cd electron-app && npm test    # data-migration coverage
```

## Renamed from evilSDR

The project was `evilSDR` through Phase 3. Two things moved, and both stay
backward compatible so an existing install upgrades without manual steps.

**Settings prefix** is now `SPECTRASDR_`. The old `EVILSDR_` names are still
read as a fallback (`src/backend/appenv.py`), so existing shell profiles keep
working. `SPECTRASDR_` wins when both are set. Affected variables:
`CONFIG_FILE`, `BOOKMARKS_FILE`, `CONNECTIONS_FILE`, `METADATA_PREFS_FILE`,
`RECORDINGS_DIR`, `SCAN_HITS_DB`, `SCAN_HITS_RETENTION_DAYS`, `DUMP1090_CMD`,
`DISABLE_WATCHER`, `DATA_ROOT`.

`SPECTRASDR_DATA_ROOT` is the user data directory itself, exported by both
launchers to the same path the variables above point into. Decoder plugins read
it via `appenv.data_root()` to locate their own config file; see
[PLUGIN_AUTHORING.md](PLUGIN_AUTHORING.md). Unset, it falls back to
`src/backend/`, matching where the other defaults land when the backend is run
directly rather than through a launcher.

**User data directory** moved, because `productName` changed:

| Launcher | Before | After |
| --- | --- | --- |
| Electron (`npm start`, unpacked build) | `<appData>/evilsdr-electron/evilSDR` | `<appData>/SpectraSDR/SpectraSDR` |
| AppImage | `~/.config/evilSDR` | `~/.config/SpectraSDR` |

Both launchers move the old directory into place on first run, carrying
settings, bookmarks, connections and recordings. The move is skipped if the new
directory already exists, so a current install is never overwritten by a stale
one. To verify after upgrading, confirm your bookmarks and recordings are still
listed in the UI.

## ADS-B integration

Set dump1090 command before start:

```bash
export SPECTRASDR_DUMP1090_CMD='dump1090 --net --quiet --write-json /tmp/d1090'
python src/backend/server.py
```

(If command is unset, ADS-B decoder still loads but only parses externally fed lines.)

## AppImage sanity check

After building AppImage, verify:

`scripts/build_electron_appimage.sh` writes the AppImage to the repo root, not
to `dist/` (`dist/` only holds electron-builder's unpacked output).

```bash
./SpectraSDR-x86_64.AppImage --appimage-extract
./SpectraSDR-x86_64.AppImage --version || true
```

Then launch and confirm:
- UI loads
- Start/Stop stream button works
- Scan hits panel loads and CSV export downloads
- Aircraft map window appears when the ADS-B decoder is enabled, and stays
  hidden for every other decoder
