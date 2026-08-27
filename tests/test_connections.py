import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "src" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import server


def test_sanitize_connections_round_trip_fields_preserved():
    s = server.SDRServer()
    payload = [{
        "id": "lab-1",
        "name": "Lab",
        "host": "10.0.0.8",
        "port": 1234,
        "driver": "rtl_tcp",
        "sample_rate": 2048000,
    }]
    out = s._sanitize_connections_entries(payload)
    assert out[0]["id"] == "lab-1"
    assert out[0]["host"] == "10.0.0.8"
    assert out[0]["port"] == 1234
    assert out[0]["sample_rate"] == 2048000


def test_sanitize_connections_empty_list_falls_back_to_default():
    s = server.SDRServer()
    out = s._sanitize_connections_entries([])
    assert len(out) == 1
    assert out[0]["id"] == server.DEFAULT_CONNECTION_ID
    assert out[0]["host"]
    assert out[0]["port"] > 0


def test_save_connections_persists_selected_profile(tmp_path):
    old_path = server.CONNECTIONS_FILE
    try:
        server.CONNECTIONS_FILE = tmp_path / "connections.json"
        s = server.SDRServer()
        s.connections = [
            {
                "id": "p1",
                "name": "Profile 1",
                "host": "127.0.0.1",
                "port": 1234,
                "driver": "rtl_tcp",
                "sample_rate": 2400000,
            }
        ]
        s._desired_connection_id = "p1"
        assert s._save_connections() is True

        raw = json.loads(server.CONNECTIONS_FILE.read_text())
        assert raw["selected_id"] == "p1"
        assert raw["connections"][0]["id"] == "p1"
    finally:
        server.CONNECTIONS_FILE = old_path
