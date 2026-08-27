import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "src" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from decoders.adsb_wrapper import ADSBWrapperDecoder


def test_adsb_sbs_parse_emits_aircraft_fields():
    dec = ADSBWrapperDecoder()
    emitted = []
    dec.add_callback(lambda m: emitted.append(m))

    dec.feed_raw_line("MSG,3,111,11111,A3C1AA,111111,2026/05/22,00:00:00.000,2026/05/22,00:00:00.000,CALL123 ,35000,420,180,40.1,-73.9,,,0,0,0,0")

    assert emitted
    evt = emitted[-1]
    # Emitted events are DecoderResult dicts; payload is in "data"
    data = evt.get("data", evt)
    assert data["icao"] == "A3C1AA"
    assert data["callsign"] == "CALL123"
    assert data["altitude"] == 35000
    assert data["speed"] == 420


def test_adsb_json_payload_updates_aircraft_cache():
    dec = ADSBWrapperDecoder()
    dec.feed_raw_line('{"hex":"abcd12","flight":"UAL42 ","alt_baro":12000,"gs":250}')
    ac = dec.get_aircraft(limit=5)
    assert ac
    assert ac[0]["icao"] == "ABCD12"
    assert ac[0]["callsign"] == "UAL42"


def test_adsb_sbs_squawk_extracted():
    dec = ADSBWrapperDecoder()
    emitted = []
    dec.add_callback(lambda m: emitted.append(m))
    dec.feed_raw_line("MSG,3,111,11111,A3C1AA,111111,2026/05/22,00:00:00.000,2026/05/22,00:00:00.000,CALL123 ,35000,420,180,40.1,-73.9,,,0,0,7700,0")
    evt = emitted[-1]
    data = evt.get("data", evt)
    assert data.get("squawk") == "7700"


def test_adsb_json_squawk_extracted():
    dec = ADSBWrapperDecoder()
    dec.feed_raw_line('{"hex":"abcd12","flight":"UAL42 ","squawk":"7600"}')
    ac = dec.get_aircraft(limit=5)
    assert ac
    assert ac[0]["squawk"] == "7600"


def test_adsb_emergency_squawk_normalized():
    dec = ADSBWrapperDecoder()
    dec.feed_raw_line('{"hex":"abcd12","flight":"UAL42 ","squawk":"7777"}')
    ac = dec.get_aircraft(limit=5)
    assert ac
    assert ac[0]["squawk"] == "7700"


def test_adsb_hijack_squawk_normalized():
    dec = ADSBWrapperDecoder()
    dec.feed_raw_line('{"hex":"abcd12","flight":"UAL42 ","squawk":"7501"}')
    ac = dec.get_aircraft(limit=5)
    assert ac
    assert ac[0]["squawk"] == "7500"


def test_adsb_process_status_idle_when_not_configured():
    dec = ADSBWrapperDecoder()
    status = dec.get_process_status()
    assert status["status"] == "idle"
    assert status["pid"] is None
    assert status["lines_received"] == 0


def test_adsb_process_status_after_lines():
    dec = ADSBWrapperDecoder()
    dec.feed_raw_line("MSG,3,111,11111,A3C1AA,111111,2026/05/22,00:00:00.000,2026/05/22,00:00:00.000,CALL123 ,35000,420,180,40.1,-73.9,,,0,0,0,0")
    dec.feed_raw_line('{"hex":"abcd12","flight":"UAL42 ","alt_baro":12000}')
    status = dec.get_process_status()
    assert status["lines_received"] == 2
    assert status["parse_errors"] == 0


def test_adsb_parse_error_counted():
    dec = ADSBWrapperDecoder()
    dec.feed_raw_line("this is not a valid line")
    status = dec.get_process_status()
    assert status["parse_errors"] == 1
    assert status["lines_received"] == 1


def test_adsb_aircraft_ttl_pruning():
    dec = ADSBWrapperDecoder()
    dec.feed_raw_line('{"hex":"abcd12","flight":"UAL42 ","alt_baro":12000,"lat":40.0,"lon":-74.0}')
    # Manually set last_seen to very old
    dec.aircraft["ABCD12"]["last_seen"] = 0  # epoch
    ac = dec.get_aircraft(limit=50)
    # Should be pruned (TTL=300s, last_seen=epoch)
    assert len(ac) == 0


def test_adsb_info_includes_process_status():
    dec = ADSBWrapperDecoder()
    info = dec.spec()
    assert "process_status" in info
    assert "lines_received" in info
    assert "aircraft_count" in info
    assert info["version"] == "0.4.0"


def test_adsb_reset_clears_stats():
    dec = ADSBWrapperDecoder()
    dec.feed_raw_line('{"hex":"abcd12","flight":"UAL42 ","alt_baro":12000}')
    dec.reset()
    status = dec.get_process_status()
    assert status["lines_received"] == 0
    assert status["parse_errors"] == 0


def test_adsb_callback_receives_decoder_result_dict():
    """Emit wraps events in DecoderResult; callbacks get .to_dict() payloads."""
    dec = ADSBWrapperDecoder()
    received = []
    dec.add_callback(lambda m: received.append(m))

    dec.feed_raw_line('{"hex":"aabbcc","flight":"TEST1","alt_baro":25000,"gs":300,"track":90,"lat":42.0,"lon":-78.0,"squawk":"7700"}')

    assert len(received) == 1
    evt = received[0]
    # DecoderResult.to_dict() puts payload under "data"
    assert "data" in evt
    assert evt["data"]["icao"] == "AABBCC"
    assert evt["data"]["callsign"] == "TEST1"
    assert evt["type"] == "aircraft"
    assert evt["decoder"] == "adsb"


def test_adsb_emergency_squawk_via_callback():
    """Emergency squawk normalization flows through to callback payload."""
    dec = ADSBWrapperDecoder()
    received = []
    dec.add_callback(lambda m: received.append(m))

    dec.feed_raw_line('{"hex":"abcd12","flight":"UAL42","squawk":"7777"}')
    evt = received[-1]
    assert evt["data"]["squawk"] == "7700"


def test_adsb_sbs_callback_structure():
    """SBS-1 lines also produce DecoderResult dicts via callback."""
    dec = ADSBWrapperDecoder()
    received = []
    dec.add_callback(lambda m: received.append(m))

    dec.feed_raw_line("MSG,3,111,11111,A3C1AA,111111,2026/05/22,00:00:00.000,2026/05/22,00:00:00.000,CALL123 ,35000,420,180,40.1,-73.9,,,0,0,7600,0")

    evt = received[-1]
    assert evt["type"] == "aircraft"
    assert evt["data"]["icao"] == "A3C1AA"
    assert evt["data"]["squawk"] == "7600"


def test_adsb_log_aircraft_integration(tmp_path):
    """End-to-end: decoder callback + _log_aircraft_event persists to SQLite."""
    db = tmp_path / "test_aircraft.sqlite3"

    from scan_history import ScanHistoryStore
    store = ScanHistoryStore(db, retention_days=30)

    dec = ADSBWrapperDecoder()

    # Simulate what server.py does: register a logging callback
    def log_cb(event):
        data = event.get("data")
        payload = data if isinstance(data, dict) and "icao" in data else event
        if payload.get("type") != "aircraft":
            return
        icao = payload.get("icao")
        if not icao:
            return
        store.log_aircraft(
            icao=icao,
            callsign=payload.get("callsign"),
            altitude=payload.get("altitude"),
            speed=payload.get("speed"),
            track=payload.get("track"),
            lat=payload.get("lat"),
            lon=payload.get("lon"),
            squawk=payload.get("squawk"),
            source=payload.get("source"),
        )

    dec.add_callback(log_cb)

    # Feed a JSON line
    dec.feed_raw_line('{"hex":"aabbcc","flight":"TEST1","alt_baro":25000,"gs":300,"track":90,"lat":42.0,"lon":-78.0}')
    # Feed an SBS line
    dec.feed_raw_line("MSG,3,111,11111,A3C1AA,111111,2026/05/22,00:00:00.000,2026/05/22,00:00:00.000,CALL123 ,35000,420,180,40.1,-73.9,,,0,0,0,0")

    events = store.list_aircraft_events(limit=10)
    assert len(events) == 2
    icaos = {e["icao"] for e in events}
    assert "AABBCC" in icaos
    assert "A3C1AA" in icaos
