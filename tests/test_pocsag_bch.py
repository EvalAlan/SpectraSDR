"""BCH(31,21) fixtures and error-correction coverage for the POCSAG decoder."""

import itertools
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "src" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from decoders.pocsag import (  # noqa: E402
    POCSAG_IDLE,
    POCSAG_SYNC,
    POCSAGDecoder,
    _BCH_SYNDROME_TABLE,
    _bch_check,
    _bch_correct,
    _bch_syndrome,
)


def encode_codeword(data21: int) -> int:
    """Build a valid 32-bit POCSAG codeword from 21 data bits."""
    shifted = (data21 & 0x1FFFFF) << 10
    word31 = shifted | _bch_syndrome(shifted)
    codeword = word31 << 1
    if bin(codeword).count("1") % 2:
        codeword |= 1
    return codeword


def corrupt(codeword: int, positions) -> int:
    for pos in positions:
        codeword ^= 1 << pos
    return codeword


# --- known-good fixtures -----------------------------------------------------
# SYNC and IDLE are fixed by the POCSAG spec and are valid BCH words with even
# parity. They pin the generator polynomial and parity convention to an external
# source of truth, independent of our own encoder.


def test_spec_constants_are_valid_codewords():
    assert _bch_check(POCSAG_SYNC)
    assert _bch_check(POCSAG_IDLE)


def test_spec_constants_have_zero_syndrome_and_even_parity():
    for word in (POCSAG_SYNC, POCSAG_IDLE):
        assert _bch_syndrome(word >> 1) == 0
        assert bin(word).count("1") % 2 == 0


def test_encoder_agrees_with_checker():
    random.seed(1234)
    for _ in range(200):
        assert _bch_check(encode_codeword(random.getrandbits(21)))


def test_single_bit_corruption_of_spec_constants_is_recovered():
    for word in (POCSAG_SYNC, POCSAG_IDLE):
        for pos in range(32):
            assert not _bch_check(corrupt(word, [pos]))
            assert _bch_correct(corrupt(word, [pos])) == word


# --- syndrome table ----------------------------------------------------------


def test_syndrome_table_is_collision_free_over_all_weight_two_patterns():
    patterns = {(1 << a) | (1 << b) for a in range(31) for b in range(a, 31)}
    syndromes = {_bch_syndrome(p) for p in patterns}
    assert len(patterns) == 496
    assert len(syndromes) == len(patterns), "distinct error patterns must not share a syndrome"
    assert len(_BCH_SYNDROME_TABLE) == 496


# --- correction capability ---------------------------------------------------


def test_all_single_bit_errors_are_corrected():
    random.seed(99)
    for _ in range(25):
        word = encode_codeword(random.getrandbits(21))
        for pos in range(32):
            assert _bch_correct(corrupt(word, [pos])) == word


def test_all_double_bit_errors_are_corrected():
    """BCH(31,21) has distance 5, so every 2-bit error must be recoverable."""
    random.seed(5150)
    for _ in range(10):
        word = encode_codeword(random.getrandbits(21))
        for a, b in itertools.combinations(range(32), 2):
            assert _bch_correct(corrupt(word, [a, b])) == word


def test_triple_bit_errors_are_rejected_not_miscorrected():
    """Past two errors a confident wrong answer is worse than no answer."""
    random.seed(2024)
    for _ in range(60):
        word = encode_codeword(random.getrandbits(21))
        for _ in range(40):
            bad = corrupt(word, random.sample(range(32), 3))
            result = _bch_correct(bad)
            assert result is None or result == word


def test_corrected_output_is_always_self_consistent():
    """Whatever comes back must itself pass the checker."""
    random.seed(31337)
    for _ in range(150):
        word = encode_codeword(random.getrandbits(21))
        for nerr in (1, 2, 3):
            result = _bch_correct(corrupt(word, random.sample(range(32), nerr)))
            assert result is None or _bch_check(result)


# --- end-to-end batch fixture ------------------------------------------------


def build_batch(address: int, text: str, function: int = 0) -> list:
    """Assemble a full 16-codeword POCSAG batch carrying one alpha message.

    encode_codeword() places its 21 data bits at codeword bits 31..11, so those
    21 bits are the flag bit followed by the 20-bit payload.
    """
    frame = address & 0x7
    codewords = [POCSAG_IDLE] * 16
    codewords[frame * 2] = address_codeword(address, function)

    slot = frame * 2 + 1
    for payload in text_payload_chunks(text):
        if slot >= 16:
            break
        codewords[slot] = message_codeword(payload)
        slot += 1

    return codewords_to_bits(codewords)


def address_codeword(address: int, function: int = 0) -> int:
    return encode_codeword((((address >> 3) & 0x3FFFF) << 2) | (function & 0x3))


def message_codeword(payload20: int) -> int:
    return encode_codeword((1 << 20) | (payload20 & 0xFFFFF))


def text_payload_chunks(text: str) -> list:
    """7-bit ASCII, LSB first, packed into 20-bit message-codeword payloads."""
    bits = []
    for ch in text:
        bits.extend((ord(ch) >> b) & 1 for b in range(7))
    while len(bits) % 20:
        bits.append(0)

    chunks = []
    for i in range(0, len(bits), 20):
        value = 0
        for bit in bits[i:i + 20]:
            value = (value << 1) | bit
        chunks.append(value)
    return chunks


def codewords_to_bits(codewords: list) -> list:
    bits = []
    for cw in codewords:
        bits.extend((cw >> (31 - i)) & 1 for i in range(32))
    return bits


def pager_payloads(emitted: list) -> list:
    """Pager fields sit under DecoderResult.data once emit() serializes them."""
    return [event["data"] for event in emitted]


def test_batch_fixture_decodes_to_expected_address_and_text():
    address = 1234568
    text = "TEST PAGE"
    dec = POCSAGDecoder()
    emitted = []
    dec.add_callback(emitted.append)

    dec._decode_batch(build_batch(address, text), 1200)

    assert emitted, "batch should produce a message"
    assert emitted[0]["decoder"] == "pocsag"
    assert emitted[0]["type"] == "pager"

    payload = pager_payloads(emitted)[0]
    assert payload["address"] == address
    assert payload["content"].startswith(text)


def test_batch_fixture_survives_one_bit_error_per_codeword():
    """Every codeword takes a hit; BCH should repair all of them transparently."""
    address = 1234568
    text = "TEST PAGE"
    clean = build_batch(address, text)

    corrupted = list(clean)
    for cw_idx in range(16):
        corrupted[cw_idx * 32 + (cw_idx % 32)] ^= 1

    dec = POCSAGDecoder()
    emitted = []
    dec.add_callback(emitted.append)
    dec._decode_batch(corrupted, 1200)

    assert emitted
    payload = pager_payloads(emitted)[0]
    assert payload["address"] == address
    assert payload["content"].startswith(text)


def test_corrupted_idle_does_not_latch_phantom_address():
    """A repairable bit error in an IDLE separator must not read as an address.

    IDLE has a clear flag bit, so classifying it before running BCH correction
    latches a spurious address, and any message codewords that follow get
    attributed to that phantom instead of being dropped as orphans.
    """
    address = 1234568  # frame 0, so the address codeword lands in slot 0
    codewords = [POCSAG_IDLE] * 16

    codewords[0] = address_codeword(address)
    real = text_payload_chunks("REAL")
    for i, payload in enumerate(real):
        codewords[1 + i] = message_codeword(payload)

    # Orphan message codewords sitting after the IDLE separator, as a noisy
    # stream can easily produce.
    idle_slot = 1 + len(real)
    for i, payload in enumerate(text_payload_chunks("GHOST")):
        codewords[idle_slot + 1 + i] = message_codeword(payload)

    bits = codewords_to_bits(codewords)
    bits[idle_slot * 32 + 7] ^= 1  # single repairable hit on the separator

    dec = POCSAGDecoder()
    emitted = []
    dec.add_callback(emitted.append)
    dec._decode_batch(bits, 1200)

    payloads = pager_payloads(emitted)
    assert {m["address"] for m in payloads} == {address}
    assert not any("GHOST" in m["content"] for m in payloads)
