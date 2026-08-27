"""Environment lookup with pre-rename compatibility.

The project was renamed from evilSDR to SpectraSDR, which moved the settings
prefix from EVILSDR_ to SPECTRASDR_. Existing installs have the old names baked
into shell profiles and launcher scripts, and a missed variable fails silently
by falling back to a default path, so the old prefix stays supported.
"""

import os
from pathlib import Path

LEGACY_PREFIX = "EVILSDR_"
PREFIX = "SPECTRASDR_"

BACKEND_DIR = Path(__file__).resolve().parent


def env(name, default=None):
    """Read SPECTRASDR_<name>, falling back to the legacy EVILSDR_<name>."""
    value = os.environ.get(PREFIX + name)
    if value is None:
        value = os.environ.get(LEGACY_PREFIX + name)
    return default if value is None else value


def data_root():
    """Directory the launchers keep user data in.

    Both launchers export SPECTRASDR_DATA_ROOT to the directory they already
    write config, bookmarks and recordings into. Plugins storing their own
    config file should use this rather than guessing a path. Falls back to the
    backend directory, which is where server.py's own defaults land when the
    backend is started directly instead of through a launcher.
    """
    return Path(env("DATA_ROOT", BACKEND_DIR))
