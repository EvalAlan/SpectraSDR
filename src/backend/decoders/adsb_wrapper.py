#!/usr/bin/env python3
"""ADSB decoder wrapper with optional dump1090 subprocess integration.

Features:
  - Auto-restart dump1090 on crash (max 5 restarts, 3s backoff)
  - Process health / status reporting
  - Normalized aircraft events (position, altitude, velocity, squawk)
  - Thread-safe aircraft cache with TTL pruning
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from collections import deque

from appenv import env

from .base import BaseDecoder, InputType, DecoderResult

logger = logging.getLogger(__name__)

_MAX_RESTARTS = 5
_RESTART_BACKOFF = 3.0
_AIRCRAFT_TTL = 300  # seconds before pruning stale entries from cache


class ADSBWrapperDecoder(BaseDecoder):
    name = "adsb"
    description = "ADSB wrapper (dump1090 integration)"
    input_type = InputType.IQ
    version = "0.4.0"

    def __init__(self, sample_rate: int = 2_400_000):
        super().__init__(sample_rate=sample_rate)
        self.messages = deque(maxlen=500)
        self.aircraft = {}
        self.last_line_at = None
        self._proc: subprocess.Popen | None = None
        self._reader_thread: threading.Thread | None = None
        self._stop_evt = threading.Event()
        self._restart_count = 0
        self._last_restart_ts = 0.0
        self._restart_lock = threading.Lock()
        self._proc_start_ts: float | None = None
        self._process_status: str = "idle"  # idle | running | crashed | stopped
        self._lines_received = 0
        self._parse_errors = 0

    def reset(self):
        self.messages.clear()
        self.aircraft.clear()
        self.last_line_at = None
        self._lines_received = 0
        self._parse_errors = 0

    def process_iq(self, iq_samples):
        # External-integration strategy: IQ feed not used directly here.
        return

    def on_enable(self):
        self._start_dump1090_if_configured()

    def on_disable(self):
        self._stop_dump1090()
        self._process_status = "stopped"

    def _start_dump1090_if_configured(self):
        cmd = env("DUMP1090_CMD", "").strip()
        if not cmd or self._proc is not None:
            return
        self._stop_evt.clear()
        self._proc = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self._proc_start_ts = time.time()
        self._process_status = "running"
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()
        logger.info(f"dump1090 started (pid={self._proc.pid}, cmd={cmd!r})")

    def _stop_dump1090(self):
        self._stop_evt.set()
        proc = self._proc
        self._proc = None
        self._proc_start_ts = None
        if not proc:
            return
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        logger.info("dump1090 stopped")

    def _reader_loop(self):
        proc = self._proc
        if not proc or not proc.stdout:
            return
        for line in proc.stdout:
            if self._stop_evt.is_set():
                break
            self.feed_raw_line(line)
        # Reader ended — check if process died unexpectedly
        if not self._stop_evt.is_set() and proc is not None:
            retcode = proc.poll()
            if retcode is not None:
                logger.warning(f"dump1090 exited unexpectedly (rc={retcode})")
                self._process_status = "crashed"
                self._maybe_restart()

    def _maybe_restart(self):
        with self._restart_lock:
            if self._stop_evt.is_set():
                return
            if self._restart_count >= _MAX_RESTARTS:
                logger.error(f"dump1090 restart limit reached ({_MAX_RESTARTS})")
                self._process_status = "crashed"
                return
            now = time.time()
            if now - self._last_restart_ts < _RESTART_BACKOFF:
                time.sleep(_RESTART_BACKOFF - (now - self._last_restart_ts))
            self._restart_count += 1
            self._last_restart_ts = now
            logger.info(f"Restarting dump1090 (attempt {self._restart_count}/{_MAX_RESTARTS})")
            self._stop_evt.clear()
            self._start_dump1090_if_configured()

    def _emit_event(self, event: dict):
        event.setdefault("decoder", self.name)
        event.setdefault("timestamp", time.time())
        self.last_line_at = event["timestamp"]
        self.messages.append(event)
        # Wrap raw dict events in DecoderResult for uniform downstream handling
        evt_type = event.get("type", "generic")
        if evt_type == "aircraft":
            icao = event.get("icao", "?")
            callsign = event.get("callsign")
            summary = f"{icao}" + (f" {callsign}" if callsign else "")
        elif evt_type == "raw":
            summary = "raw line"
        elif evt_type == "raw_json":
            summary = "raw JSON"
        else:
            summary = evt_type
        self.emit(DecoderResult(
            decoder=self.name,
            type=evt_type,
            summary=summary,
            data=event,
            raw=event.get("raw"),
        ))

    def feed_raw_line(self, line: str):
        """Accept raw AVR/SBS/JSON line and emit normalized event."""
        line = (line or "").strip()
        if not line:
            return
        self._lines_received += 1

        parsed = self._parse_line(line)
        if not parsed:
            self._parse_errors += 1
            self._emit_event({"type": "raw", "raw": line})
            return

        self._emit_event(parsed)

    def _parse_line(self, line: str):
        if line.startswith("{"):
            try:
                payload = json.loads(line)
                return self._parse_json_payload(payload)
            except Exception:
                return None

        if line.startswith("MSG,"):
            return self._parse_sbs_message(line)

        if line.startswith("*") and line.endswith(";"):
            return self._parse_avr_message(line)

        return None

    def _parse_json_payload(self, payload: dict):
        # dump1090 --write-json style single-aircraft JSON line support
        hex_id = (payload.get("hex") or "").strip().upper()
        if not hex_id:
            return {"type": "raw_json", "payload": payload}

        # Extract squawk from squawk field or emergency status
        squawk = payload.get("squawk") or None
        squawk_emerg = self._is_emergency_squawk(squawk)
        if squawk_emerg:
            squawk = squawk_emerg

        evt = {
            "type": "aircraft",
            "icao": hex_id,
            "callsign": (payload.get("flight") or "").strip() or None,
            "altitude": payload.get("alt_baro") or payload.get("alt_geom"),
            "speed": payload.get("gs"),
            "track": payload.get("track"),
            "lat": payload.get("lat"),
            "lon": payload.get("lon"),
            "squawk": squawk,
            "source": "dump1090-json",
        }
        self._merge_aircraft(hex_id, evt)
        return evt

    def _parse_sbs_message(self, line: str):
        # SBS-1 format, fields are comma separated
        # MSG,type,sessionID,flightID,icao,time,time,callsign,altitude,speed,track,lat,lon,vertRate,squawk,....
        p = line.split(",")
        if len(p) < 22:
            return None
        hex_id = (p[4] or "").strip().upper()
        if not hex_id:
            return None
        callsign = (p[10] or "").strip() or None
        altitude = self._int_or_none(p[11])
        speed = self._int_or_none(p[12])
        track = self._float_or_none(p[13])
        lat = self._float_or_none(p[14])
        lon = self._float_or_none(p[15])
        squawk = (p[20] or "").strip() or None

        evt = {
            "type": "aircraft",
            "icao": hex_id,
            "callsign": callsign,
            "altitude": altitude,
            "speed": speed,
            "track": track,
            "lat": lat,
            "lon": lon,
            "squawk": squawk,
            "source": "sbs",
            "raw": line,
        }
        self._merge_aircraft(hex_id, evt)
        return evt

    def _parse_avr_message(self, line: str):
        # AVR beast-hex line, only expose ICAO from DF17 payload when possible.
        data = line.strip("*;")
        evt = {"type": "avr", "raw": line, "source": "avr"}
        if len(data) >= 8:
            # Best-effort ICAO extraction for common DF17 frame layout
            hex_id = data[2:8].upper()
            if all(c in "0123456789ABCDEF" for c in hex_id):
                evt["icao"] = hex_id
                self._merge_aircraft(hex_id, {"icao": hex_id})
        return evt

    def _merge_aircraft(self, hex_id: str, fields: dict):
        """Merge new fields into aircraft cache, preserving non-None history."""
        now = time.time()
        current = self.aircraft.get(hex_id, {"icao": hex_id})
        merged = {**current, **{k: v for k, v in fields.items() if v is not None}, "last_seen": now}
        self.aircraft[hex_id] = merged
        # Return a copy with last_seen set for the event
        for k in ("altitude", "speed", "track", "lat", "lon", "callsign", "squawk"):
            if merged.get(k) is not None:
                fields.setdefault(k, merged[k])
        fields["last_seen"] = now

    @staticmethod
    def _is_emergency_squawk(squawk: str | None) -> str | None:
        """Return emergency squawk code if recognized, else None."""
        if not squawk:
            return None
        squawk = squawk.strip()
        if squawk in ("7700", "7777"):
            return "7700"  # general emergency
        if squawk == "7600":
            return "7600"  # comms failure
        if squawk.startswith("75"):
            return "7500"  # hijack (normalize)
        return None

    @staticmethod
    def _int_or_none(v):
        try:
            return int(v)
        except Exception:
            return None

    @staticmethod
    def _float_or_none(v):
        try:
            return float(v)
        except Exception:
            return None

    def spec(self) -> dict:
        info = super().spec()
        info["configured"] = bool(env("DUMP1090_CMD", "").strip())
        info["process_status"] = self._process_status
        info["lines_received"] = self._lines_received
        info["parse_errors"] = self._parse_errors
        info["restart_count"] = self._restart_count
        info["aircraft_count"] = len(self.aircraft)
        if not info["configured"] and self.enabled:
            info["note"] = "Set SPECTRASDR_DUMP1090_CMD to a dump1090 command for live ADS-B ingest"
        return info

    def get_history(self, limit: int = 50) -> list[dict]:
        msgs = list(self.messages)[-max(1, limit):]
        return list(msgs)

    def get_aircraft(self, limit: int = 100) -> list[dict]:
        now = time.time()
        entries = [
            a for a in self.aircraft.values()
            if now - a.get("last_seen", 0) < _AIRCRAFT_TTL
        ]
        entries.sort(key=lambda a: a.get("last_seen", 0), reverse=True)
        return entries[: max(1, min(limit, 500))]

    def get_process_status(self) -> dict:
        uptime = None
        if self._proc_start_ts:
            uptime = round(time.time() - self._proc_start_ts, 1)
        pid = self._proc.pid if self._proc else None
        return {
            "status": self._process_status,
            "pid": pid,
            "uptime_seconds": uptime,
            "lines_received": self._lines_received,
            "parse_errors": self._parse_errors,
            "restart_count": self._restart_count,
            "aircraft_tracked": len(self.aircraft),
        }
