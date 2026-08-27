#!/usr/bin/env python3
"""Base interface for SDR sample sources.

A source owns everything device-specific: how a connection is established, how
raw sample bytes arrive, and what those bytes mean. This is the interface the
reader loop, DSP, scanner, and decoders are intended to consume once the source
abstraction is wired into the server.

Sources deliberately return *raw device bytes* rather than normalised samples:

- the uint8 -> complex64 conversion is numpy work that already runs in a
  ThreadPoolExecutor, and moving it onto the event loop would put it on the same
  thread as every WebSocket client;
- IQ recording writes device-native bytes, which stay small (2 bytes/sample for
  RTL rather than 8) and remain readable by external tools.

Conversion therefore lives in `to_complex64`, called by the consumer from the
worker thread.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from enum import Enum

import numpy as np


class SampleFormat(Enum):
    """Wire format of the interleaved I/Q bytes a source produces."""

    UINT8 = "u8"      # rtl_tcp and librtlsdr
    INT16 = "s16"     # SoapySDR CS16, the common native device format
    FLOAT32 = "f32"   # SoapySDR CF32

    @property
    def bytes_per_sample(self) -> int:
        """Bytes per complex sample (one I plus one Q)."""
        return {
            SampleFormat.UINT8: 2,
            SampleFormat.INT16: 4,
            SampleFormat.FLOAT32: 8,
        }[self]


def to_complex64(raw: bytes, fmt: SampleFormat) -> np.ndarray:
    """Convert interleaved I/Q bytes to a normalised complex64 array.

    Output is scaled to roughly [-1, 1] per component for every format, so the
    DSP chain sees consistent magnitudes no matter which radio produced it.

    Call this from a worker thread; it allocates and touches the whole buffer.
    """
    if fmt is SampleFormat.UINT8:
        # Unchanged from the original inline implementation, deliberately: this
        # is the path the existing rtl_tcp behaviour depends on.
        arr = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
        arr = (arr - 127.5) / 127.5
    elif fmt is SampleFormat.INT16:
        arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif fmt is SampleFormat.FLOAT32:
        # Already normalised by the driver; copy so the caller does not hold a
        # view onto a buffer that may be reused.
        arr = np.frombuffer(raw, dtype=np.float32).astype(np.float32)
    else:
        raise ValueError(f"unsupported sample format: {fmt}")

    # An odd count would misalign I and Q for every subsequent sample, so drop a
    # trailing orphan rather than silently swapping the channels.
    if arr.size % 2:
        arr = arr[:-1]

    return (arr[0::2] + 1j * arr[1::2]).astype(np.complex64)


@dataclass
class Capabilities:
    """What a connected device can actually do.

    Sent to the frontend so the UI reflects the hardware instead of assuming
    RTL-SDR's ranges. Gains are in tenths of a dB throughout, matching both the
    rtl_tcp SET_GAIN unit and the existing slider (index.html: min=0 max=500
    step=10) -- the defaults below reproduce that slider exactly, so rtl_tcp
    cannot regress in the UI.
    """

    freq_range: tuple[int, int] = (24_000_000, 1_766_000_000)
    sample_rates: list[int] = field(default_factory=list)  # empty => continuous
    gain_range: tuple[int, int] = (0, 500)
    gain_step: int = 10
    gain_values: list[int] | None = None   # discrete gains, if the device lists them
    tuner: str = "unknown"
    driver: str = "unknown"
    device_label: str = ""
    # Which of set_center_freq / set_sample_rate / set_gain / set_gain_mode /
    # set_agc / set_bias_tee / set_ppm actually do something. A list, not a set:
    # this is broadcast over WebSocket and json.dumps() raises on a set, which
    # server.handle_message's blanket except would swallow into a log line.
    controls: list[str] = field(default_factory=lambda: ["freq", "sample_rate", "gain"])

    def to_dict(self) -> dict:
        d = asdict(self)
        # Tuples become lists so this survives a JSON round trip unchanged.
        d["freq_range"] = list(self.freq_range)
        d["gain_range"] = list(self.gain_range)
        return d

    def supports(self, control: str) -> bool:
        return control in self.controls


class SourceUnavailable(RuntimeError):
    """Raised when a source's native dependency is missing at construction."""


class BaseSDRSource(ABC):
    """Interface every SDR source implements.

    Two shapes of device have to fit here: network sources that are naturally
    async (rtl_tcp), and local devices whose reads block (SoapySDR, librtlsdr).
    Blocking implementations must wrap their read in `run_in_executor` so the
    event loop keeps serving clients; `_read_blocking` exists for that.
    """

    name: str = "base"
    description: str = ""
    sample_format: SampleFormat = SampleFormat.UINT8

    def __init__(self, **config):
        self.config = config
        self.connected = False
        self.sample_rate = int(config.get("sample_rate", 2_400_000))
        self.center_freq = int(config.get("center_freq", 100_000_000))
        # Blocking device reads get their own single worker. They must NOT share
        # server._executor, which is max_workers=1 and already saturated by
        # _process_chunk -- routing a multi-hundred-ms device read through it
        # would serialise DSP behind the radio.
        self._io_executor: ThreadPoolExecutor | None = None

    def _executor_for_io(self) -> ThreadPoolExecutor:
        if self._io_executor is None:
            self._io_executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix=f"sdr-{self.name}"
            )
        return self._io_executor

    def _shutdown_io_executor(self) -> None:
        if self._io_executor is not None:
            self._io_executor.shutdown(wait=False)
            self._io_executor = None

    # --- availability -----------------------------------------------------

    @classmethod
    def is_available(cls) -> tuple[bool, str]:
        """Whether this source can be used on this machine.

        Returns (available, reason). Sources with native dependencies override
        this to probe the import, so a missing library hides the source rather
        than raising at connect time. Reported to the UI so the option can be
        shown greyed out with an explanation.
        """
        return True, ""

    # --- lifecycle --------------------------------------------------------

    @abstractmethod
    async def connect(self) -> None:
        """Open the device and apply initial sample rate, frequency and gain."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the device. Must be safe to call when not connected."""

    @abstractmethod
    async def read(self, nbytes: int) -> bytes:
        """Return exactly `nbytes` of interleaved I/Q in `sample_format`.

        Raises on disconnect; the caller treats any exception as a dropped
        connection and retries.
        """

    async def _read_blocking(self, fn, *args) -> bytes:
        """Run a blocking device read off the event loop, on our own worker."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor_for_io(), fn, *args)

    # --- capabilities -----------------------------------------------------

    @abstractmethod
    def capabilities(self) -> Capabilities:
        """Describe the connected device. Only valid after connect()."""

    # --- tuning -----------------------------------------------------------

    # set_center_freq and set_sample_rate return the value the device actually
    # applied, which is not always what was asked for -- Soapy clamps to the
    # nearest supported rate. The caller rebuilds RadioDSP from the return
    # value, because RadioDSP builds its anti-alias filter from the rate
    # (firwin(..., fs=sample_rate)); using the requested rate there would
    # mistune the filter without any visible error.

    @abstractmethod
    async def set_center_freq(self, hz: int) -> int: ...

    @abstractmethod
    async def set_sample_rate(self, hz: int) -> int: ...

    @abstractmethod
    async def set_gain(self, tenths_db: int) -> None: ...

    async def set_gain_mode(self, manual: bool) -> None:
        """Manual vs automatic gain. No-op where the device has no such notion."""
        return None

    async def set_agc(self, enabled: bool) -> None:
        """Digital AGC. No-op where unsupported."""
        return None
