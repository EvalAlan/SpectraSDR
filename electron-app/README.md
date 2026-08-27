# SpectraSDR Electron shell

The Electron shell starts the existing Python backend and loads its web
interface in a desktop window. It does not contain a separate frontend build.

## Run from a checkout

Set up the Python environment at the repository root first:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Then install and start Electron:

```bash
cd electron-app
npm install
npm start
```

For an unpackaged checkout, the launcher uses these Python interpreters in
order:

1. The `PYTHON` environment variable, when set.
2. `<repository>/.venv/bin/python`, when present.
3. `python3` from `PATH`.

The launcher starts `src/backend/server.py`, waits up to ten seconds for
`127.0.0.1:5555`, and then opens the window. HTTP port `5555` is currently a
launcher constant, so keep the default `http_port` in `config.json`.

## Persistent data

Electron stores runtime files below
`path.join(app.getPath("userData"), "SpectraSDR")`. On first launch it copies
available defaults for configuration, bookmarks, connection profiles, and
metadata preferences, then creates a `recordings/` directory.

The child backend receives explicit `SPECTRASDR_*` paths into this directory.
Repository-local configuration is therefore not modified by the Electron app.

The launcher also looks for the former `evilSDR` directory and migrates it only
when the new SpectraSDR directory does not already exist.

## Tests

The Node test suite covers user-data migration behavior:

```bash
cd electron-app
npm test
```

Python backend tests remain in the repository-level `tests/` directory.

## Package the Electron application

Create the unpacked Linux application:

```bash
cd electron-app
npm ci
npm run build
```

This writes an unpacked build below `electron-app/dist/`. It is an intermediate
artifact, not the final self-contained AppImage.

## Build the AppImage

From the repository root, run:

```bash
./scripts/build_electron_appimage.sh
```

The script requires `rsync`, `curl`, and `tar`. It assembles the current
repository and Electron output, downloads and embeds a relocatable CPython,
installs `requirements.txt` into that runtime, and invokes `appimagetool`.

The resulting `*.AppImage` is written to the repository root. Build caches are
stored beneath `${XDG_CACHE_HOME:-$HOME/.cache}/spectrasdr`.

See the project [runbook](../docs/RUNBOOK.md) for the release smoke checklist
and migration checks.
