from pathlib import Path
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "src" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from scan_history import ScanHistoryStore


def test_scan_history_write_and_filter(tmp_path: Path):
    db = tmp_path / "hits.sqlite3"
    store = ScanHistoryStore(db, retention_days=1)
    store.log_hit(freq=162400000, mode="FM", label="WX", scan_mode="BOOKMARK", signal_db=-45.3, profile_id="p1")
    store.log_hit(freq=118500000, mode="AM", label="ATC", scan_mode="RANGE", signal_db=-38.0, profile_id="p2")

    hits = store.list_hits(limit=10)
    assert len(hits) == 2

    fm_hits = store.list_hits(limit=10, mode="FM")
    assert len(fm_hits) == 1
    assert fm_hits[0]["label"] == "WX"


def test_scan_history_time_filter_and_csv_and_prune(tmp_path: Path):
    db = tmp_path / "hits.sqlite3"
    store = ScanHistoryStore(db, retention_days=1)

    now = time.time()
    store.log_hit(freq=100000000, mode="FM", label="new", scan_mode="RANGE", signal_db=-30, profile_id="p1")

    # insert old row directly for deterministic prune behavior
    with store._connect() as conn:
        conn.execute(
            "INSERT INTO scan_hits(ts,freq,mode,label,scan_mode,signal_db,profile_id) VALUES(?,?,?,?,?,?,?)",
            (now - 86400 * 5, 101000000, "AM", "old", "BOOKMARK", -40, "p2"),
        )
        conn.commit()

    recent = store.list_hits(limit=10, since_ts=now - 60)
    assert all(h["label"] != "old" for h in recent)

    csv_blob = store.export_csv(limit=10)
    assert "freq" in csv_blob and "profile_id" in csv_blob

    removed = store.prune_old_hits(now_ts=now)
    assert removed >= 1


def test_scan_history_export_json(tmp_path: Path):
    db = tmp_path / "hits.sqlite3"
    store = ScanHistoryStore(db, retention_days=30)
    store.log_hit(freq=162400000, mode="FM", label="WX", scan_mode="BOOKMARK", signal_db=-45.3, profile_id="p1")
    store.log_hit(freq=118500000, mode="AM", label="ATC", scan_mode="RANGE", signal_db=-38.0, profile_id="p2")

    import json as _json
    blob = store.export_json(limit=10)
    data = _json.loads(blob)
    assert isinstance(data, list)
    assert len(data) == 2
    freqs = sorted(d["freq"] for d in data)
    assert freqs == [118500000, 162400000]


def test_scan_history_analytics(tmp_path: Path):
    db = tmp_path / "hits.sqlite3"
    store = ScanHistoryStore(db, retention_days=30)
    now = time.time()

    # 3 hits on same freq, different profiles/modes
    store.log_hit(freq=162400000, mode="FM", label="WX", scan_mode="BOOKMARK", signal_db=-45.3, profile_id="p1")
    store.log_hit(freq=162400000, mode="FM", label="WX2", scan_mode="RANGE", signal_db=-42.0, profile_id="p1")
    store.log_hit(freq=118500000, mode="AM", label="ATC", scan_mode="RANGE", signal_db=-38.0, profile_id="p2")

    # insert old row to test time filter
    with store._connect() as conn:
        conn.execute(
            "INSERT INTO scan_hits(ts,freq,mode,label,scan_mode,signal_db,profile_id) VALUES(?,?,?,?,?,?,?)",
            (now - 86400 * 5, 101000000, "AM", "old", "BOOKMARK", -50, "p3"),
        )
        conn.commit()

    # Full analytics (no time filter)
    data = store.get_analytics()
    assert data["total_hits"] == 4
    assert len(data["top_frequencies"]) >= 2
    # Most frequent freq should be 162400000 with count 2
    top = data["top_frequencies"][0]
    assert top["freq"] == 162400000
    assert top["count"] == 2
    assert top["freq_mhz"] == 162.4
    assert len(data["by_profile"]) >= 2
    assert len(data["by_mode"]) >= 2
    assert data["signal_stats"]["count_with_signal"] == 4
    assert data["signal_stats"]["avg_db"] is not None

    # Time-filtered analytics (only recent)
    data_filtered = store.get_analytics(since_ts=now - 60)
    assert data_filtered["total_hits"] == 3
    assert all(p["profile_id"] != "p3" for p in data_filtered["by_profile"])


def test_scan_history_analytics_per_profile(tmp_path: Path):
    db = tmp_path / "hits.sqlite3"
    store = ScanHistoryStore(db, retention_days=30)

    store.log_hit(freq=162400000, mode="FM", label="WX", scan_mode="BOOKMARK", signal_db=-45.3, profile_id="p1")
    store.log_hit(freq=118500000, mode="AM", label="ATC", scan_mode="RANGE", signal_db=-38.0, profile_id="p2")
    store.log_hit(freq=146520000, mode="NFM", label="HAM", scan_mode="RANGE", signal_db=-50.0, profile_id="p1")

    # All profiles
    data_all = store.get_analytics()
    assert data_all["total_hits"] == 3
    assert len(data_all["by_profile"]) == 2

    # Per-profile p1: 2 hits
    data_p1 = store.get_analytics(profile_id="p1")
    assert data_p1["total_hits"] == 2
    assert len(data_p1["by_profile"]) == 1
    assert data_p1["by_profile"][0]["profile_id"] == "p1"

    # Per-profile p2: 1 hit
    data_p2 = store.get_analytics(profile_id="p2")
    assert data_p2["total_hits"] == 1

    # Non-existent profile: 0 hits
    data_p3 = store.get_analytics(profile_id="nonexistent")
    assert data_p3["total_hits"] == 0


def test_scan_history_analytics_hit_rate(tmp_path: Path):
    db = tmp_path / "hits.sqlite3"
    store = ScanHistoryStore(db, retention_days=30)
    now = time.time()

    # Insert hits spread across time to test hit_rate
    with store._connect() as conn:
        for i in range(5):
            conn.execute(
                "INSERT INTO scan_hits(ts,freq,mode,label,scan_mode,signal_db,profile_id) VALUES(?,?,?,?,?,?,?)",
                (now - 7200 + i * 1800, 162400000, "FM", "test", "RANGE", -40.0, "p1"),
            )
        conn.commit()

    data = store.get_analytics()
    assert data["total_hits"] == 5
    assert data["hit_rate"] is not None
    # 5 hits over ~2 hours => ~2.5 hits/hr
    assert data["hit_rate"] > 0


def test_scan_history_scan_mode_filter(tmp_path: Path):
    db = tmp_path / "hits.sqlite3"
    store = ScanHistoryStore(db, retention_days=30)

    store.log_hit(freq=162400000, mode="FM", label="WX", scan_mode="BOOKMARK", signal_db=-45.3, profile_id="p1")
    store.log_hit(freq=118500000, mode="AM", label="ATC", scan_mode="RANGE", signal_db=-38.0, profile_id="p2")

    # All hits
    all_hits = store.list_hits(limit=10)
    assert len(all_hits) == 2

    # Filter by scan_mode=BOOKMARK
    bm_hits = store.list_hits(limit=10, scan_mode="BOOKMARK")
    assert len(bm_hits) == 1
    assert bm_hits[0]["scan_mode"] == "BOOKMARK"

    # Filter by scan_mode=RANGE
    rng_hits = store.list_hits(limit=10, scan_mode="RANGE")
    assert len(rng_hits) == 1
    assert rng_hits[0]["scan_mode"] == "RANGE"

    # Combined filter: mode=FM AND scan_mode=BOOKMARK
    combo = store.list_hits(limit=10, mode="FM", scan_mode="BOOKMARK")
    assert len(combo) == 1

    # No match
    none = store.list_hits(limit=10, scan_mode="MEMORY")
    assert len(none) == 0

    # Export with scan_mode filter
    csv_blob = store.export_csv(limit=10, scan_mode="RANGE")
    assert "ATC" in csv_blob
    assert "WX" not in csv_blob

    json_blob = store.export_json(limit=10, scan_mode="BOOKMARK")
    import json as _json
    data = _json.loads(json_blob)
    assert len(data) == 1
    assert data[0]["scan_mode"] == "BOOKMARK"
