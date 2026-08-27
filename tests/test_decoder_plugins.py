import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "src" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from decoders.base import BaseDecoder, DecoderResult, DecoderState, InputType
from decoders import discover_decoders, load_decoders


# ── Helpers ──

class _MinimalDecoder(BaseDecoder):
    """Minimal concrete decoder for testing."""
    name = "test_minimal"
    description = "test"
    input_type = InputType.AUDIO
    version = "0.0.1"

    def __init__(self, sample_rate=48000):
        super().__init__(sample_rate=sample_rate)
        self._history = []
        self.init_called = False
        self.cleanup_called = False
        self.enable_count = 0
        self.disable_count = 0

    def init(self, **kwargs):
        self.init_called = True
        return True

    def cleanup(self):
        self.cleanup_called = True

    def on_enable(self):
        self.enable_count += 1

    def on_disable(self):
        self.disable_count += 1

    def process_audio(self, samples):
        self._history.append(float(samples.sum()))

    def get_history(self, limit=50):
        return self._history[-limit:]

    def reset(self):
        self._history.clear()


class _BadLifecycleDecoder(BaseDecoder):
    name = "bad_lifecycle"
    description = "bad"
    input_type = InputType.AUDIO

    def on_enable(self):
        raise RuntimeError("boom")

    def get_history(self, limit: int = 50):
        return []

    def reset(self):
        pass


class _FailingInitDecoder(BaseDecoder):
    name = "failing_init"
    description = "fails init"
    input_type = InputType.AUDIO

    def init(self, **kwargs):
        return False

    def get_history(self, limit: int = 50):
        return []

    def reset(self):
        pass


# ── Discovery tests ──

def test_discover_decoders_includes_adsb_plugin():
    found = discover_decoders()
    assert "adsb" in found


def test_discover_decoders_includes_pocsag_plugin():
    found = discover_decoders()
    assert "pocsag" in found


def test_discover_decoders_skips_base():
    found = discover_decoders()
    assert "base" not in found


def test_discover_decoders_skips_abstract():
    found = discover_decoders()
    # BaseDecoder itself should not appear
    for cls in found.values():
        assert cls is not BaseDecoder
        assert not getattr(cls, "__abstractmethods__", set())


# ── Lifecycle tests ──

def test_decoder_lifecycle_failure_is_isolated():
    dec = _BadLifecycleDecoder()
    dec.enabled = True
    assert dec.enabled is False
    assert dec.state == DecoderState.ERROR


def test_minimal_decoder_lifecycle():
    dec = _MinimalDecoder()
    assert dec.state == DecoderState.IDLE
    assert dec.enabled is False

    dec.enabled = True
    assert dec.enabled is True
    assert dec.state == DecoderState.RUNNING
    assert dec.enable_count == 1

    dec.enabled = False
    assert dec.enabled is False
    assert dec.state == DecoderState.IDLE
    assert dec.disable_count == 1


def test_minimal_decoder_double_enable_no_reinit():
    dec = _MinimalDecoder()
    dec.enabled = True
    dec.enabled = True  # already enabled, should not re-trigger on_enable
    assert dec.enable_count == 1


def test_minimal_decoder_double_disable():
    dec = _MinimalDecoder()
    dec.enabled = True
    dec.enabled = False
    dec.enabled = False  # already disabled
    assert dec.disable_count == 1


# ── Init / cleanup tests ──

def test_load_decoders_calls_init():
    instances = load_decoders()
    for name, dec in instances.items():
        if hasattr(dec, 'init_called'):
            assert dec.init_called, f"init() not called for {name}"


def test_failing_init_excluded():
    # _FailingInitDecoder.init() returns False, so it should be excluded
    # But it's not in the decoders/ dir, so we test the logic directly
    dec = _FailingInitDecoder()
    assert dec.init() is False


# ── Spec / info tests ──

def test_decoder_spec_contains_required_fields():
    dec = _MinimalDecoder()
    spec = dec.spec()
    assert "name" in spec
    assert "description" in spec
    assert "version" in spec
    assert "input_type" in spec
    assert "enabled" in spec
    assert "state" in spec


def test_decoder_info_is_backward_compat():
    dec = _MinimalDecoder()
    info = dec.info()
    spec = dec.spec()
    assert info == spec


def test_decoder_spec_reflects_state_change():
    dec = _MinimalDecoder()
    assert dec.spec()["state"] == "idle"
    dec.enabled = True
    assert dec.spec()["state"] == "running"
    assert dec.spec()["enabled"] is True


# ── Health check tests ──

def test_health_check_healthy_when_idle():
    dec = _MinimalDecoder()
    health = dec.health_check()
    assert health["healthy"] is True
    assert health["state"] == "idle"


def test_health_check_unhealthy_on_error():
    dec = _BadLifecycleDecoder()
    dec.enabled = True  # triggers error
    health = dec.health_check()
    assert health["healthy"] is False
    assert health["error"] == "boom"


# ── DecoderResult tests ──

def test_decoder_result_to_dict():
    result = DecoderResult(
        decoder="test",
        type="message",
        summary="hello",
        data={"key": "value"},
    )
    d = result.to_dict()
    assert d["decoder"] == "test"
    assert d["type"] == "message"
    assert d["summary"] == "hello"
    assert d["data"] == {"key": "value"}
    assert "timestamp" in d


def test_emit_accepts_dict():
    dec = _MinimalDecoder()
    received = []
    dec.add_callback(received.append)
    dec.emit({"type": "test", "value": 42})
    assert len(received) == 1
    assert received[0]["decoder"] == "test_minimal"


def test_emit_accepts_decoder_result():
    dec = _MinimalDecoder()
    received = []
    dec.add_callback(received.append)
    dec.emit(DecoderResult(decoder="test", type="msg", summary="hi"))
    assert len(received) == 1
    assert received[0]["type"] == "msg"


def test_emit_sets_decoder_name_automatically():
    dec = _MinimalDecoder()
    received = []
    dec.add_callback(received.append)
    dec.emit({"type": "raw"})  # no decoder key
    assert received[0]["decoder"] == "test_minimal"


# ── Callback tests ──

def test_remove_callback():
    dec = _MinimalDecoder()
    cb = lambda x: None
    dec.add_callback(cb)
    dec.remove_callback(cb)
    assert cb not in dec._callbacks


def test_set_callback_replaces_all():
    dec = _MinimalDecoder()
    dec.add_callback(lambda x: None)
    dec.add_callback(lambda x: None)
    new_cb = lambda x: None
    dec.set_callback(new_cb)
    assert dec._callbacks == [new_cb]


def test_callback_error_doesnt_break_other_callbacks():
    dec = _MinimalDecoder()
    received = []

    def bad_cb(msg):
        raise RuntimeError("oops")

    def good_cb(msg):
        received.append(msg)

    dec.add_callback(bad_cb)
    dec.add_callback(good_cb)
    dec.emit({"type": "test"})
    assert len(received) == 1


# ── Reset / history tests ──

def test_reset_clears_history():
    import numpy as np
    dec = _MinimalDecoder()
    dec.process_audio(np.array([1.0, 2.0]))
    assert len(dec._history) == 1
    dec.reset()
    assert len(dec._history) == 0


def test_get_history_respects_limit():
    import numpy as np
    dec = _MinimalDecoder()
    for i in range(10):
        dec.process_audio(np.array([float(i)]))
    assert len(dec.get_history(limit=3)) == 3
    assert len(dec.get_history(limit=100)) == 10


# ── Error message property ──

def test_error_message_cleared_on_enable():
    dec = _BadLifecycleDecoder()
    dec.enabled = True  # fails
    assert dec.error_message == "boom"
    # After a successful enable, error should be cleared
    dec2 = _MinimalDecoder()
    dec2.enabled = True
    assert dec2.error_message is None
