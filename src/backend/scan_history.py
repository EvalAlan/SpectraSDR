#!/usr/bin/env python3
"""SQLite-backed scanner hit history."""

from __future__ import annotations

import csv
import io
import sqlite3
import threading
import time
from pathlib import Path


class ScanHistoryStore:
    def __init__(self, db_path: Path, retention_days: int = 30):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.retention_days = max(1, int(retention_days))
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS scan_hits (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts REAL NOT NULL,
                        freq INTEGER NOT NULL,
                        mode TEXT,
                        label TEXT,
                        scan_mode TEXT,
                        signal_db REAL,
                        profile_id TEXT
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_scan_hits_ts ON scan_hits(ts DESC)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_scan_hits_profile_ts ON scan_hits(profile_id, ts DESC)")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS aircraft_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts REAL NOT NULL,
                        icao TEXT NOT NULL,
                        callsign TEXT,
                        altitude INTEGER,
                        speed INTEGER,
                        track REAL,
                        lat REAL,
                        lon REAL,
                        squawk TEXT,
                        source TEXT
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_aircraft_events_ts ON aircraft_events(ts DESC)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_aircraft_events_icao ON aircraft_events(icao, ts DESC)")
                conn.commit()

    def log_hit(self, *, freq: int, mode: str | None, label: str | None, scan_mode: str | None, signal_db: float | None, profile_id: str | None):
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO scan_hits(ts,freq,mode,label,scan_mode,signal_db,profile_id) VALUES(?,?,?,?,?,?,?)",
                    (time.time(), int(freq), mode, label, scan_mode, signal_db, profile_id),
                )
                conn.commit()

    def log_aircraft(self, *, icao: str, callsign: str | None, altitude: int | None,
                     speed: int | None, track: float | None, lat: float | None,
                     lon: float | None, squawk: str | None, source: str | None):
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO aircraft_events(ts,icao,callsign,altitude,speed,track,lat,lon,squawk,source) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (time.time(), icao, callsign, altitude, speed, track, lat, lon, squawk, source),
                )
                conn.commit()

    def list_aircraft_events(
        self,
        *,
        limit: int = 200,
        icao: str | None = None,
        since_ts: float | None = None,
        until_ts: float | None = None,
    ) -> list[dict]:
        limit = max(1, min(int(limit), 1000))
        clauses = []
        params = []
        if icao:
            clauses.append("icao = ?")
            params.append(icao)
        if since_ts is not None:
            clauses.append("ts >= ?")
            params.append(float(since_ts))
        if until_ts is not None:
            clauses.append("ts <= ?")
            params.append(float(until_ts))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT id, ts, icao, callsign, altitude, speed, track, lat, lon, squawk, source FROM aircraft_events {where} ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def prune_old_hits(self, *, now_ts: float | None = None) -> int:
        cutoff = (now_ts or time.time()) - (self.retention_days * 86400)
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute("DELETE FROM scan_hits WHERE ts < ?", (cutoff,))
                conn.commit()
                return int(cur.rowcount or 0)

    def list_hits(
        self,
        *,
        limit: int = 100,
        mode: str | None = None,
        profile_id: str | None = None,
        scan_mode: str | None = None,
        since_ts: float | None = None,
        until_ts: float | None = None,
    ):
        limit = max(1, min(int(limit), 500))
        clauses = []
        params = []
        if mode:
            clauses.append("mode = ?")
            params.append(mode)
        if profile_id:
            clauses.append("profile_id = ?")
            params.append(profile_id)
        if scan_mode:
            clauses.append("scan_mode = ?")
            params.append(scan_mode)
        if since_ts is not None:
            clauses.append("ts >= ?")
            params.append(float(since_ts))
        if until_ts is not None:
            clauses.append("ts <= ?")
            params.append(float(until_ts))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT id, ts, freq, mode, label, scan_mode, signal_db, profile_id FROM scan_hits {where} ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def export_csv(
        self,
        *,
        limit: int = 1000,
        mode: str | None = None,
        profile_id: str | None = None,
        scan_mode: str | None = None,
        since_ts: float | None = None,
        until_ts: float | None = None,
    ) -> str:
        hits = self.list_hits(
            limit=limit,
            mode=mode,
            profile_id=profile_id,
            scan_mode=scan_mode,
            since_ts=since_ts,
            until_ts=until_ts,
        )
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["id", "ts", "freq", "mode", "label", "scan_mode", "signal_db", "profile_id"])
        for h in hits:
            w.writerow([
                h.get("id"),
                h.get("ts"),
                h.get("freq"),
                h.get("mode"),
                h.get("label"),
                h.get("scan_mode"),
                h.get("signal_db"),
                h.get("profile_id"),
            ])
        return out.getvalue()

    def export_json(
        self,
        *,
        limit: int = 1000,
        mode: str | None = None,
        profile_id: str | None = None,
        scan_mode: str | None = None,
        since_ts: float | None = None,
        until_ts: float | None = None,
    ) -> str:
        hits = self.list_hits(
            limit=limit,
            mode=mode,
            profile_id=profile_id,
            scan_mode=scan_mode,
            since_ts=since_ts,
            until_ts=until_ts,
        )
        import json
        return json.dumps(hits, indent=2)

    def get_analytics(
        self,
        *,
        profile_id: str | None = None,
        since_ts: float | None = None,
        until_ts: float | None = None,
    ) -> dict:
        clauses = []
        params = []
        if profile_id:
            clauses.append("profile_id = ?")
            params.append(profile_id)
        if since_ts is not None:
            clauses.append("ts >= ?")
            params.append(float(since_ts))
        if until_ts is not None:
            clauses.append("ts <= ?")
            params.append(float(until_ts))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        with self._lock:
            with self._connect() as conn:
                total = conn.execute(f"SELECT COUNT(*) FROM scan_hits {where}", params).fetchone()[0]

                # Most active frequencies (top 10, rounded to nearest 100kHz)
                freq_rows = conn.execute(
                    f"""
                    SELECT freq, COUNT(*) as cnt
                    FROM scan_hits {where}
                    GROUP BY freq
                    ORDER BY cnt DESC
                    LIMIT 10
                    """,
                    params,
                ).fetchall()

                # Hit count by profile
                profile_rows = conn.execute(
                    f"""
                    SELECT profile_id, COUNT(*) as cnt
                    FROM scan_hits {where}
                    GROUP BY profile_id
                    ORDER BY cnt DESC
                    """,
                    params,
                ).fetchall()

                # Hit count by mode
                mode_rows = conn.execute(
                    f"""
                    SELECT mode, COUNT(*) as cnt
                    FROM scan_hits {where}
                    GROUP BY mode
                    ORDER BY cnt DESC
                    """,
                    params,
                ).fetchall()

                # Signal stats
                signal_row = conn.execute(
                    f"""
                    SELECT
                        AVG(signal_db) as avg_db,
                        MIN(signal_db) as min_db,
                        MAX(signal_db) as max_db,
                        COUNT(signal_db) as signal_count
                    FROM scan_hits
                    {where} {'AND' if where else 'WHERE'} signal_db IS NOT NULL
                    """,
                    params,
                ).fetchone()

                # Hourly distribution (hits per hour bucket)
                hourly_rows = conn.execute(
                    f"""
                    SELECT
                        CAST((ts - ?) / 3600 AS INTEGER) as hour_bucket,
                        COUNT(*) as cnt
                    FROM scan_hits {where}
                    GROUP BY hour_bucket
                    ORDER BY hour_bucket
                    """,
                    [since_ts or 0] + params,
                ).fetchall()

                # Time span and hit rate
                span_row = conn.execute(
                    f"SELECT MIN(ts), MAX(ts) FROM scan_hits {where}",
                    params,
                ).fetchone()

        # Compute hit_rate (hits per hour over observed span)
        hit_rate = None
        if span_row and span_row[0] is not None and span_row[1] is not None:
            span_hours = max(0.001, (span_row[1] - span_row[0]) / 3600)
            if span_hours > 0:
                hit_rate = round(total / span_hours, 2)

        return {
            "total_hits": total,
            "hit_rate": hit_rate,
            "top_frequencies": [
                {"freq": r[0], "count": r[1], "freq_mhz": round(r[0] / 1e6, 3)}
                for r in freq_rows
            ],
            "by_profile": [
                {"profile_id": r[0], "count": r[1]}
                for r in profile_rows
            ],
            "by_mode": [
                {"mode": r[0], "count": r[1]}
                for r in mode_rows
            ],
            "signal_stats": {
                "avg_db": round(signal_row[0], 2) if signal_row[0] is not None else None,
                "min_db": signal_row[1],
                "max_db": signal_row[2],
                "count_with_signal": signal_row[3],
            },
            "hourly_distribution": [
                {"hour_offset": r[0], "count": r[1]}
                for r in hourly_rows
            ],
        }
