#!/usr/bin/env python3
"""rtl_tcp source - the original SpectraSDR transport.

A direct port of the former rtl_client.RTLTCPClient behind BaseSDRSource. The
handshake, the 5-byte command encoding and the order of the initial setup calls
are all unchanged, because this is the path every existing install depends on.
"""

from __future__ import annotations

import asyncio
import logging
import struct

from .base import BaseSDRSource, Capabilities, SampleFormat

logger = logging.getLogger(__name__)

CMD_SET_FREQ = 0x01
CMD_SET_SAMPLE_RATE = 0x02
CMD_SET_GAIN_MODE = 0x03
CMD_SET_GAIN = 0x04
CMD_SET_AGC = 0x08

# From the 12-byte rtl_tcp handshake. The protocol reports a tuner id and a
# count of gain steps, but not the gain values themselves, so gains cannot be
# enumerated over this transport -- see capabilities() below.
TUNER_NAMES = {
    1: "E4000", 2: "FC0012", 3: "FC0013",
    4: "FC2580", 5: "R820T", 6: "R828D",
}

# Tuning limits differ per tuner; these are the widest sensible defaults and
# match what the UI assumed before capabilities existed.
TUNER_FREQ_RANGE = {
    "E4000": (52_000_000, 2_200_000_000),
    "FC0012": (22_000_000, 948_600_000),
    "FC0013": (22_000_000, 1_100_000_000),
    "FC2580": (146_000_000, 924_000_000),
    "R820T": (24_000_000, 1_766_000_000),
    "R828D": (24_000_000, 1_766_000_000),
}


class RTLTCPSource(BaseSDRSource):
    name = "rtl_tcp"
    description = "RTL-SDR over an rtl_tcp server"
    sample_format = SampleFormat.UINT8

    def __init__(self, **config):
        super().__init__(**config)
        self.host = config.get("host", "127.0.0.1")
        self.port = int(config.get("port", 1234))
        self.reader = None
        self.writer = None
        self.tuner_type = "unknown"
        self.gain_count = 0

    async def connect(self) -> None:
        self.reader, self.writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), timeout=5
        )
        data = await asyncio.wait_for(self.reader.readexactly(12), timeout=5)
        if data[:4] != b"RTL0":
            raise ConnectionError(f"Invalid rtl_tcp magic: {data[:4]}")

        tuner_type = struct.unpack(">I", data[4:8])[0]
        self.gain_count = struct.unpack(">I", data[8:12])[0]
        self.tuner_type = TUNER_NAMES.get(tuner_type, f"unknown({tuner_type})")
        self.connected = True
        logger.info(f"Connected: tuner={self.tuner_type}, gains={self.gain_count}")

        # Order preserved from the original client: rate, frequency, manual gain
        # mode, then gain. Some rtl_tcp builds ignore a gain set while still in
        # automatic mode, so the mode must be set first.
        await self.set_sample_rate(self.sample_rate)
        await self.set_center_freq(self.center_freq)
        await self.set_gain_mode(True)
        await self.set_gain(400)

    async def _send_cmd(self, cmd_id: int, param: int) -> None:
        if self.writer:
            self.writer.write(struct.pack(">BI", cmd_id, param))
            await self.writer.drain()

    async def read(self, nbytes: int) -> bytes:
        if not self.reader:
            raise ConnectionError("rtl_tcp source is not connected")
        return await self.reader.readexactly(nbytes)

    def capabilities(self) -> Capabilities:
        lo, hi = TUNER_FREQ_RANGE.get(self.tuner_type, (24_000_000, 1_766_000_000))
        return Capabilities(
            freq_range=(lo, hi),
            sample_rates=[250_000, 1_024_000, 1_536_000, 1_920_000,
                          2_048_000, 2_400_000, 2_560_000],
            # Deliberately the existing slider's bounds. rtl_tcp reports how many
            # gain steps the tuner has but never what they are, so a discrete
            # list is not obtainable here; reporting the current continuous range
            # is what keeps the UI identical to before.
            gain_range=(0, 500),
            gain_step=10,
            gain_values=None,
            tuner=self.tuner_type,
            driver=self.name,
            device_label=f"RTL-SDR {self.tuner_type} ({self.host}:{self.port})",
            # No bias_tee: the command exists only in some rtl_tcp forks and the
            # protocol gives no way to ask which, so advertising it would produce
            # a control that silently does nothing on stock builds.
            controls=["freq", "sample_rate", "gain", "gain_mode", "agc"],
        )

    async def set_center_freq(self, hz: int) -> int:
        self.center_freq = int(hz)
        await self._send_cmd(CMD_SET_FREQ, self.center_freq)
        # rtl_tcp never acknowledges, so the requested value is all we have.
        return self.center_freq

    async def set_sample_rate(self, hz: int) -> int:
        self.sample_rate = int(hz)
        await self._send_cmd(CMD_SET_SAMPLE_RATE, self.sample_rate)
        return self.sample_rate

    async def set_gain(self, tenths_db: int) -> None:
        await self._send_cmd(CMD_SET_GAIN, int(tenths_db))

    async def set_gain_mode(self, manual: bool) -> None:
        await self._send_cmd(CMD_SET_GAIN_MODE, 1 if manual else 0)

    async def set_agc(self, enabled: bool) -> None:
        await self._send_cmd(CMD_SET_AGC, 1 if enabled else 0)

    async def disconnect(self) -> None:
        if self.writer:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except Exception:
                pass
        self.reader = None
        self.writer = None
        self.connected = False
        self._shutdown_io_executor()
