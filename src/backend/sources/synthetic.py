#!/usr/bin/env python3
"""Synthetic signal source - a radio that needs no radio.

Generates a complex tone plus Gaussian noise at the configured sample rate and
emits it in the same wire formats real hardware uses. It exists so the source
abstraction, the format conversion and the DSP chain can be exercised end to
end with no dongle attached, and so the app is demoable without one.

It is implemented as a real source rather than a test mock so it can exercise
the common runtime path once source selection is integrated into the server.
"""

from __future__ import annotations

import asyncio
import logging
import time

import numpy as np

from .base import BaseSDRSource, Capabilities, SampleFormat

logger = logging.getLogger(__name__)


class SyntheticSource(BaseSDRSource):
    name = "synthetic"
    description = "Generated test signal (no hardware required)"
    sample_format = SampleFormat.UINT8

    def __init__(self, **config):
        super().__init__(**config)
        fmt = config.get("sample_format", "u8")
        self.sample_format = fmt if isinstance(fmt, SampleFormat) else SampleFormat(fmt)
        # Tone offset from centre, in Hz. The DSP test asserts this lands in the
        # expected FFT bin.
        self.tone_offset = int(config.get("tone_offset", 300_000))
        self.snr_db = float(config.get("snr_db", 20.0))
        self.paced = bool(config.get("paced", True))
        self._phase = 0.0
        self._rng = np.random.default_rng(int(config.get("seed", 0)))
        self._last_read = 0.0

    @classmethod
    def is_available(cls) -> tuple[bool, str]:
        return True, ""

    async def connect(self) -> None:
        self.connected = True
        self._last_read = time.monotonic()
        logger.info(
            f"Synthetic source: {self.sample_rate} Sps, tone {self.tone_offset} Hz, "
            f"{self.sample_format.value}"
        )

    async def disconnect(self) -> None:
        self.connected = False
        self._shutdown_io_executor()

    def _generate(self, n_samples: int) -> np.ndarray:
        """Complex tone plus noise, unit-ish amplitude, phase-continuous."""
        t = np.arange(n_samples, dtype=np.float64)
        # Track phase across calls so the tone does not glitch at chunk edges,
        # which would smear the FFT peak the tests look for.
        w = 2.0 * np.pi * self.tone_offset / float(self.sample_rate)
        phases = self._phase + w * t
        self._phase = float((self._phase + w * n_samples) % (2.0 * np.pi))

        signal = 0.5 * np.exp(1j * phases)
        noise_amp = 0.5 * (10.0 ** (-self.snr_db / 20.0))
        noise = noise_amp * (
            self._rng.standard_normal(n_samples) + 1j * self._rng.standard_normal(n_samples)
        )
        return signal + noise

    def _pack(self, iq: np.ndarray) -> bytes:
        """Encode complex samples into the configured wire format."""
        inter = np.empty(iq.size * 2, dtype=np.float64)
        inter[0::2] = iq.real
        inter[1::2] = iq.imag

        if self.sample_format is SampleFormat.UINT8:
            # Inverse of (x - 127.5)/127.5.
            return np.clip(inter * 127.5 + 127.5, 0, 255).astype(np.uint8).tobytes()
        if self.sample_format is SampleFormat.INT16:
            return np.clip(inter * 32768.0, -32768, 32767).astype(np.int16).tobytes()
        if self.sample_format is SampleFormat.FLOAT32:
            return inter.astype(np.float32).tobytes()
        raise ValueError(f"unsupported sample format: {self.sample_format}")

    async def read(self, nbytes: int) -> bytes:
        if not self.connected:
            raise ConnectionError("synthetic source is not connected")

        n_samples = nbytes // self.sample_format.bytes_per_sample
        if self.paced:
            # Deliver at roughly real time so the rest of the pipeline sees the
            # cadence it would from hardware. Tests set paced=False.
            due = self._last_read + n_samples / float(self.sample_rate)
            delay = due - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self._last_read = max(due, time.monotonic() - 1.0)

        return self._pack(self._generate(n_samples))

    def capabilities(self) -> Capabilities:
        return Capabilities(
            freq_range=(0, 6_000_000_000),
            sample_rates=[250_000, 1_024_000, 2_400_000, 10_000_000],
            gain_range=(0, 500),
            gain_step=10,
            tuner="synthetic",
            driver=self.name,
            device_label=f"Synthetic ({self.sample_format.value})",
            controls=["freq", "sample_rate", "gain"],
        )

    async def set_center_freq(self, hz: int) -> int:
        self.center_freq = int(hz)
        return self.center_freq

    async def set_sample_rate(self, hz: int) -> int:
        self.sample_rate = int(hz)
        return self.sample_rate

    async def set_gain(self, tenths_db: int) -> None:
        return None
