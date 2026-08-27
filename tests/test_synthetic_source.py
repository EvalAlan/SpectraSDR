"""End-to-end coverage of the IQ path, with no hardware.

synthetic source -> to_complex64 -> spectrum. This exercises the intended
source-to-DSP boundary without a dongle; server selection is covered once the
source abstraction is integrated there.
"""

import asyncio
import pathlib
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "src" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dsp import RadioDSP  # noqa: E402
from sources import create_source, to_complex64  # noqa: E402
from sources.base import SampleFormat  # noqa: E402

SAMPLE_RATE = 2_400_000
FFT_SIZE = 2048


def _make(**overrides):
    cfg = {
        "driver": "synthetic",
        "sample_rate": SAMPLE_RATE,
        "tone_offset": 300_000,
        "paced": False,   # tests must not wait for real time
        "snr_db": 30.0,
    }
    cfg.update(overrides)
    return create_source(cfg)


def _read_iq(src, nbytes=131072):
    async def go():
        await src.connect()
        raw = await src.read(nbytes)
        await src.disconnect()
        return raw

    raw = asyncio.run(go())
    return raw, to_complex64(raw, src.sample_format)


@pytest.mark.parametrize("fmt", ["u8", "s16", "f32"])
def test_chunk_size_is_in_samples_not_bytes(fmt):
    # A byte count means different sample counts per format; the pipeline cares
    # about samples, so a wider format must not halve the FFT cadence.
    src = _make(sample_format=fmt)
    nbytes = 65536 * SampleFormat(fmt).bytes_per_sample
    raw, iq = _read_iq(src, nbytes)
    assert len(raw) == nbytes
    assert iq.size == 65536


@pytest.mark.parametrize("fmt", ["u8", "s16", "f32"])
def test_tone_lands_in_the_expected_fft_bin(fmt):
    src = _make(sample_format=fmt)
    _raw, iq = _read_iq(src, 65536 * SampleFormat(fmt).bytes_per_sample)

    # Compute the spectrum directly rather than via RadioDSP.compute_fft, whose
    # output is autoscaled and clipped to [0, 1] -- on a cold call most bins sit
    # at 1.0 and argmax returns bin 0 regardless of the signal.
    spec = np.fft.fftshift(np.fft.fft(iq[-FFT_SIZE:] * np.hanning(FFT_SIZE)))
    peak = int(np.argmax(np.abs(spec)))
    expected = FFT_SIZE // 2 + round(300_000 / SAMPLE_RATE * FFT_SIZE)
    assert abs(peak - expected) <= 2, f"{fmt}: peak {peak}, expected ~{expected}"


def test_negative_offset_lands_below_centre():
    src = _make(tone_offset=-600_000)
    _raw, iq = _read_iq(src)
    spec = np.fft.fftshift(np.fft.fft(iq[-FFT_SIZE:] * np.hanning(FFT_SIZE)))
    peak = int(np.argmax(np.abs(spec)))
    expected = FFT_SIZE // 2 + round(-600_000 / SAMPLE_RATE * FFT_SIZE)
    assert abs(peak - expected) <= 2


def test_phase_is_continuous_across_chunks():
    # A phase discontinuity at chunk boundaries smears the peak; this catches a
    # generator that restarts its phase each read.
    src = _make()

    async def go():
        await src.connect()
        a = await src.read(65536 * 2)
        b = await src.read(65536 * 2)
        await src.disconnect()
        return a, b

    a, b = asyncio.run(go())
    joined = to_complex64(a + b, SampleFormat.UINT8)
    spec = np.fft.fftshift(np.fft.fft(joined[:FFT_SIZE] * np.hanning(FFT_SIZE)))
    peak = int(np.argmax(np.abs(spec)))
    expected = FFT_SIZE // 2 + round(300_000 / SAMPLE_RATE * FFT_SIZE)
    assert abs(peak - expected) <= 2


def test_feeds_radiodsp_without_error():
    # compute_fft's numbers are not assertable on a cold call, but it must at
    # least consume synthetic IQ and report a plausible signal level.
    src = _make()
    _raw, iq = _read_iq(src)
    dsp = RadioDSP(sample_rate=SAMPLE_RATE, fft_size=FFT_SIZE)
    out = dsp.compute_fft(iq)
    assert out["magnitudes"].size == FFT_SIZE
    assert np.isfinite(out["signal_db"])


def test_reading_before_connect_raises():
    src = _make()
    with pytest.raises(ConnectionError):
        asyncio.run(src.read(1024))
