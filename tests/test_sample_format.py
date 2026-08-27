"""Wire-format conversion for SDR sources.

The uint8 case is the important one: it is the path every existing rtl_tcp
install depends on, and it was previously inlined in server._process_chunk.
It is pinned here against that exact expression so the refactor is provably
behaviour-preserving rather than merely believed to be.
"""

import pathlib
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "src" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sources.base import SampleFormat, to_complex64  # noqa: E402


def _legacy_uint8(data: bytes) -> np.ndarray:
    """The expression that lived at server.py:682-684 before the refactor."""
    raw = np.frombuffer(data, dtype=np.uint8).astype(np.float32)
    raw = (raw - 127.5) / 127.5
    return raw[0::2] + 1j * raw[1::2]


def test_uint8_matches_the_original_inline_conversion_exactly():
    data = np.random.default_rng(1).integers(0, 256, size=8192, dtype=np.uint8).tobytes()
    np.testing.assert_array_equal(
        to_complex64(data, SampleFormat.UINT8),
        _legacy_uint8(data).astype(np.complex64),
    )


def test_uint8_endpoints_map_to_full_scale():
    # 0x00 -> -1.0, 0xFF -> +1.0; the midpoint sits just above zero because the
    # bias is 127.5, not 128.
    out = to_complex64(bytes([0x00, 0xFF, 0x80, 0x80]), SampleFormat.UINT8)
    assert out[0].real == pytest.approx(-1.0)
    assert out[0].imag == pytest.approx(1.0)
    assert out[1].real == pytest.approx(0.5 / 127.5, abs=1e-6)


@pytest.mark.parametrize("fmt", list(SampleFormat))
def test_output_is_always_complex64(fmt):
    # complex128 would silently double FFT cost and memory for every chunk.
    raw = bytes(fmt.bytes_per_sample * 64)
    assert to_complex64(raw, fmt).dtype == np.complex64


@pytest.mark.parametrize("fmt", list(SampleFormat))
def test_sample_count_matches_bytes_per_sample(fmt):
    n = 128
    raw = bytes(n * fmt.bytes_per_sample)
    assert to_complex64(raw, fmt).size == n


def test_int16_is_scaled_by_full_scale():
    raw = np.array([32767, -32768, 0, 16384], dtype=np.int16).tobytes()
    out = to_complex64(raw, SampleFormat.INT16)
    assert out[0].real == pytest.approx(0.99997, abs=1e-4)
    assert out[0].imag == pytest.approx(-1.0)
    assert out[1].real == pytest.approx(0.0)
    assert out[1].imag == pytest.approx(0.5)


def test_float32_passes_through_unscaled():
    raw = np.array([0.25, -0.5, 1.0, -1.0], dtype=np.float32).tobytes()
    out = to_complex64(raw, SampleFormat.FLOAT32)
    assert out[0] == pytest.approx(0.25 - 0.5j)
    assert out[1] == pytest.approx(1.0 - 1.0j)


def test_odd_trailing_value_is_dropped_not_misaligned():
    # Losing the orphan is right; keeping it would swap I and Q for every
    # subsequent sample in the chunk.
    out = to_complex64(bytes([10, 20, 30]), SampleFormat.UINT8)
    assert out.size == 1


def test_empty_input_yields_empty_output():
    assert to_complex64(b"", SampleFormat.UINT8).size == 0
