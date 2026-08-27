#!/usr/bin/env bash
set -euo pipefail

APP_NAME=SpectraSDR
APPDIR=build/electron-appimage
RELEASE_DIR_DEFAULT=electron-app/dist/linux-unpacked
ICON_SOURCE=assets/SpectraSDR.png
APPIMAGETOOL_VERSION="continuous"
APPIMAGETOOL_CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/spectrasdr"
APPIMAGETOOL_PATH="${APPIMAGETOOL:-}"

# Relocatable CPython from python-build-standalone. A stock `python3 -m venv`
# symlinks bin/python at the interpreter that created it, and that symlink ships
# inside the AppImage, so the bundle only ran where the build host's Python
# minor version happened to exist. This interpreter is self-contained and
# resolves its stdlib relative to its own binary, so the AppImage no longer
# depends on the host having any Python at all.
# Baseline x86_64/aarch64 builds are used deliberately; the v2/v3/v4 variants
# require newer CPU instruction sets.
PYTHON_VERSION="3.12.14"
PYTHON_STANDALONE_TAG="20260825"

# Logs go to stderr: resolve_appimagetool and resolve_standalone_python return
# their paths on stdout via $(...), so anything logged on stdout ends up
# concatenated into the caller's variable.
log() { echo "[build-appimage] $*" >&2; }
fail() { echo "[build-appimage] ERROR: $*" >&2; exit 1; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"
}

detect_arch() {
  local m
  m="$(uname -m)"
  case "$m" in
    x86_64|amd64) echo "x86_64" ;;
    aarch64|arm64) echo "aarch64" ;;
    *) fail "unsupported architecture: $m" ;;
  esac
}

resolve_appimagetool() {
  local arch url dst

  if [[ -n "$APPIMAGETOOL_PATH" && -x "$APPIMAGETOOL_PATH" ]]; then
    echo "$APPIMAGETOOL_PATH"
    return
  fi

  if command -v appimagetool >/dev/null 2>&1; then
    command -v appimagetool
    return
  fi

  arch="$(detect_arch)"
  mkdir -p "$APPIMAGETOOL_CACHE_DIR"
  dst="$APPIMAGETOOL_CACHE_DIR/appimagetool-${arch}.AppImage"

  if [[ ! -x "$dst" ]]; then
    url="https://github.com/AppImage/AppImageKit/releases/download/${APPIMAGETOOL_VERSION}/appimagetool-${arch}.AppImage"
    log "downloading appimagetool (${arch}) from ${url}"
    curl -fL "$url" -o "$dst"
    chmod +x "$dst"
  else
    log "using cached appimagetool at $dst"
  fi

  echo "$dst"
}

resolve_standalone_python() {
  local arch url dst
  arch="$(detect_arch)"
  mkdir -p "$APPIMAGETOOL_CACHE_DIR"
  dst="$APPIMAGETOOL_CACHE_DIR/cpython-${PYTHON_VERSION}-${arch}.tar.gz"

  if [[ ! -f "$dst" ]]; then
    url="https://github.com/astral-sh/python-build-standalone/releases/download/${PYTHON_STANDALONE_TAG}/cpython-${PYTHON_VERSION}+${PYTHON_STANDALONE_TAG}-${arch}-unknown-linux-gnu-install_only.tar.gz"
    log "downloading relocatable CPython ${PYTHON_VERSION} (${arch})"
    # Download to a temp name so an interrupted run cannot leave a truncated
    # archive that later builds would treat as cached.
    curl -fL "$url" -o "$dst.part"
    mv "$dst.part" "$dst"
  else
    log "using cached CPython at $dst"
  fi

  echo "$dst"
}

need_cmd rsync
need_cmd curl
need_cmd tar

resolve_release_dir() {
  if [[ -d "$RELEASE_DIR_DEFAULT" ]]; then
    echo "$RELEASE_DIR_DEFAULT"
    return
  fi

  local candidate
  candidate="$(find electron-app/dist -maxdepth 1 -type d -name '*unpacked' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n1 | cut -d' ' -f2-)"
  if [[ -n "$candidate" && -d "$candidate" ]]; then
    echo "$candidate"
    return
  fi

  fail "missing electron-app/dist/*unpacked (run: cd electron-app && npm ci && npm run build)"
}

RELEASE_DIR="$(resolve_release_dir)"
[[ -f "$ICON_SOURCE" ]] || fail "missing icon: $ICON_SOURCE"

log "using release dir: $RELEASE_DIR"
log "assembling AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR"
cp -r "$RELEASE_DIR"/* "$APPDIR"

# overwrite bundled resources with current repo tree
rm -rf "$APPDIR/resources/$APP_NAME"
mkdir -p "$APPDIR/resources/$APP_NAME"
rsync -a --delete \
  --exclude '.git' \
  --exclude '.github' \
  --exclude '.claude' \
  --exclude 'build' \
  --exclude 'electron-app/node_modules' \
  --exclude 'electron-app/dist' \
  --exclude '*.AppImage' \
  --exclude 'recordings' \
  ./ "$APPDIR/resources/$APP_NAME/"

SPECTRASDR_ROOT="$APPDIR/resources/$APP_NAME"
BACKEND_DIR="$SPECTRASDR_ROOT/src/backend"
VENV_DIR="$BACKEND_DIR/venv"

# Kept at src/backend/venv because both launchers already resolve the
# interpreter there (electron-app/src/main.js resolvePython, and AppRun's PATH).
log "installing relocatable CPython ${PYTHON_VERSION}"
rm -rf "$VENV_DIR"
mkdir -p "$VENV_DIR"
tar -xzf "$(resolve_standalone_python)" -C "$VENV_DIR" --strip-components=1

# The archive ships bin/python3; the launchers look for bin/python.
[[ -e "$VENV_DIR/bin/python" ]] || ln -s python3 "$VENV_DIR/bin/python"

"$VENV_DIR/bin/python" --version >/dev/null || fail "bundled interpreter is not runnable"

log "installing backend dependencies"
"$VENV_DIR/bin/python" -m pip install --no-cache-dir --upgrade pip >/dev/null
"$VENV_DIR/bin/python" -m pip install --no-cache-dir -r "$SPECTRASDR_ROOT/requirements.txt" >/dev/null

# Guard the property this whole approach exists for: nothing in the bundled
# interpreter may point outside the AppDir, or the artifact silently depends on
# the build host again.
if find "$VENV_DIR/bin" -type l -lname '/*' | grep -q .; then
  find "$VENV_DIR/bin" -type l -lname '/*' >&2
  fail "bundled interpreter has absolute symlinks; it would not be relocatable"
fi

cat <<'APP' > "$APPDIR/AppRun"
#!/usr/bin/env bash
set -euo pipefail
here="$(dirname "$(readlink -f "$0")")"
BACKEND_RES="$here/resources/SpectraSDR/src/backend"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
DATA_DIR="$CONFIG_HOME/SpectraSDR"
LEGACY_DATA_DIR="$CONFIG_HOME/evilSDR"

# Carry an existing install across the evilSDR -> SpectraSDR rename.
if [[ ! -d "$DATA_DIR" && -d "$LEGACY_DATA_DIR" ]]; then
  mv "$LEGACY_DATA_DIR" "$DATA_DIR" || cp -a "$LEGACY_DATA_DIR" "$DATA_DIR"
fi

mkdir -p "$DATA_DIR/recordings"
cp -n "$BACKEND_RES/config.json" "$DATA_DIR/config.json" 2>/dev/null || cp -n "$BACKEND_RES/config.json.example" "$DATA_DIR/config.json" 2>/dev/null || true
cp -n "$BACKEND_RES/bookmarks.json" "$DATA_DIR/bookmarks.json" 2>/dev/null || true
cp -n "$BACKEND_RES/connections.json" "$DATA_DIR/connections.json" 2>/dev/null || true
cp -n "$BACKEND_RES/metadata_prefs.json" "$DATA_DIR/metadata_prefs.json" 2>/dev/null || true
export SPECTRASDR_DATA_ROOT="$DATA_DIR"
export SPECTRASDR_CONFIG_FILE="$DATA_DIR/config.json"
export SPECTRASDR_BOOKMARKS_FILE="$DATA_DIR/bookmarks.json"
export SPECTRASDR_CONNECTIONS_FILE="$DATA_DIR/connections.json"
export SPECTRASDR_METADATA_PREFS_FILE="$DATA_DIR/metadata_prefs.json"
export SPECTRASDR_SCAN_HITS_DB="$DATA_DIR/scan_hits.sqlite3"
export SPECTRASDR_RECORDINGS_DIR="$DATA_DIR/recordings"
export PATH="$BACKEND_RES/venv/bin:$PATH"
exec "$here/spectrasdr-electron" "$@"
APP
chmod +x "$APPDIR/AppRun"

mkdir -p "$APPDIR/usr/bin"
ln -sf "../AppRun" "$APPDIR/usr/bin/$APP_NAME"

cat <<'DESK' > "$APPDIR/$APP_NAME.desktop"
[Desktop Entry]
Name=SpectraSDR
Exec=SpectraSDR
Icon=SpectraSDR
Type=Application
Categories=Utility;
StartupNotify=false
DESK

cp "$ICON_SOURCE" "$APPDIR/$APP_NAME.png"
ln -sf "$APP_NAME.png" "$APPDIR/.DirIcon"

APPIMAGETOOL_BIN="$(resolve_appimagetool)"
ARCH="$(detect_arch)"

log "building final AppImage with $APPIMAGETOOL_BIN"
ARCH="$ARCH" "$APPIMAGETOOL_BIN" "$APPDIR"

APPIMAGE_OUT="$(find . -maxdepth 1 -type f -name '*.AppImage' -printf '%T@ %p\n' | sort -nr | head -n1 | cut -d' ' -f2-)"
[[ -n "$APPIMAGE_OUT" ]] || fail "appimagetool completed but no .AppImage was found"

log "done: ${APPIMAGE_OUT#./}"
