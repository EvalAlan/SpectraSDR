"""Source discovery, driver dispatch and capability reporting."""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "src" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import json  # noqa: E402

from sources import (  # noqa: E402
    DEFAULT_DRIVER,
    create_source,
    discover_sources,
    list_drivers,
)
from sources.base import BaseSDRSource  # noqa: E402


def test_discovery_finds_the_builtin_drivers():
    found = discover_sources()
    assert "rtl_tcp" in found
    assert "synthetic" in found


def test_discovered_classes_are_concrete_sources():
    for name, cls in discover_sources().items():
        assert issubclass(cls, BaseSDRSource)
        assert not getattr(cls, "__abstractmethods__", set()), f"{name} is abstract"
        assert cls.name == name


def test_is_available_never_raises_and_explains_itself():
    for name, cls in discover_sources().items():
        available, reason = cls.is_available()
        assert isinstance(available, bool)
        if not available:
            assert reason, f"{name} is unavailable but gave no reason"


def test_list_drivers_is_json_serialisable():
    # This is designed for frontend broadcast; a set or enum would make the
    # future server capability message fail during JSON encoding.
    json.dumps(list_drivers())


def test_unknown_driver_falls_back_rather_than_failing():
    # Existing profiles predate the driver field being honoured, so an
    # unrecognised value must not break the connection.
    src = create_source({"driver": "does-not-exist", "host": "127.0.0.1", "port": 1234})
    assert src.name == DEFAULT_DRIVER


def test_missing_driver_defaults_to_rtl_tcp():
    src = create_source({"host": "127.0.0.1", "port": 1234})
    assert src.name == DEFAULT_DRIVER


def test_driver_dispatch_selects_the_named_source():
    assert create_source({"driver": "synthetic"}).name == "synthetic"


def test_construction_does_no_io():
    # Constructing must not touch hardware or the network: tests build an
    # SDRServer directly, and that must work on a machine with no radio.
    src = create_source({"driver": "rtl_tcp", "host": "192.0.2.1", "port": 9})
    assert src.connected is False


def test_rtl_tcp_capabilities_preserve_the_existing_gain_slider():
    # index.html has min=0 max=500 step=10 for #rf-gain-slider. Reporting
    # anything else would move the control under users on the default driver.
    caps = discover_sources()["rtl_tcp"](host="127.0.0.1", port=1234).capabilities()
    assert caps.gain_range == (0, 500)
    assert caps.gain_step == 10


def test_capabilities_round_trip_through_json():
    for name, cls in discover_sources().items():
        caps = cls(host="127.0.0.1", port=1234).capabilities()
        restored = json.loads(json.dumps(caps.to_dict()))
        assert restored["driver"] == name
        assert isinstance(restored["controls"], list)
        assert len(restored["freq_range"]) == 2


def test_unsupported_controls_are_no_ops_not_errors():
    # A stale UI may send a control the device lacks; that must not raise.
    import asyncio

    src = create_source({"driver": "synthetic"})
    assert "agc" not in src.capabilities().controls
    asyncio.run(src.set_agc(True))
    asyncio.run(src.set_gain_mode(True))
