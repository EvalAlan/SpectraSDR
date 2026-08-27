"""Prefix fallback and data-root resolution for the pre-rename compat helper."""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "src" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import appenv  # noqa: E402
from appenv import data_root, env  # noqa: E402


def _clear(monkeypatch, name):
    monkeypatch.delenv("SPECTRASDR_" + name, raising=False)
    monkeypatch.delenv("EVILSDR_" + name, raising=False)


def test_env_prefers_new_prefix(monkeypatch):
    _clear(monkeypatch, "CONFIG_FILE")
    monkeypatch.setenv("SPECTRASDR_CONFIG_FILE", "/new/config.json")
    monkeypatch.setenv("EVILSDR_CONFIG_FILE", "/old/config.json")
    assert env("CONFIG_FILE") == "/new/config.json"


def test_env_falls_back_to_legacy_prefix(monkeypatch):
    _clear(monkeypatch, "CONFIG_FILE")
    monkeypatch.setenv("EVILSDR_CONFIG_FILE", "/old/config.json")
    assert env("CONFIG_FILE") == "/old/config.json"


def test_env_returns_default_when_unset(monkeypatch):
    _clear(monkeypatch, "CONFIG_FILE")
    assert env("CONFIG_FILE", "fallback") == "fallback"


def test_data_root_uses_launcher_value(monkeypatch):
    _clear(monkeypatch, "DATA_ROOT")
    monkeypatch.setenv("SPECTRASDR_DATA_ROOT", "/data/SpectraSDR")
    assert data_root() == pathlib.Path("/data/SpectraSDR")


def test_data_root_honours_legacy_variable(monkeypatch):
    """An install predating the rename keeps resolving to its own directory."""
    _clear(monkeypatch, "DATA_ROOT")
    monkeypatch.setenv("EVILSDR_DATA_ROOT", "/data/evilSDR")
    assert data_root() == pathlib.Path("/data/evilSDR")


def test_data_root_defaults_to_backend_dir(monkeypatch):
    """Unset, plugin config lands beside server.py's own default config.json."""
    _clear(monkeypatch, "DATA_ROOT")
    assert data_root() == appenv.BACKEND_DIR
