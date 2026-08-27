import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "src" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from decoders.pocsag import POCSAGDecoder


def test_pocsag_dedup_signature_blocks_repeat_emit():
    dec = POCSAGDecoder()
    emitted = []
    dec.add_callback(lambda m: emitted.append(m))

    bits = [1,0,1,0] * 12
    dec._emit_message(1001, 0, bits, 1200)
    dec._emit_message(1001, 0, bits, 1200)

    assert len(emitted) <= 1
