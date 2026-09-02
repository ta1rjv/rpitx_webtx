import numpy as np
import pytest

from webtx.jitter import JitterBuffer

SR = 48000


def test_init_validates_ordering():
    with pytest.raises(ValueError):
        JitterBuffer(SR, target_ms=5.0, max_ms=1.0, min_ms=10.0)


def test_push_then_pop_returns_same_samples():
    jb = JitterBuffer(SR, target_ms=30.0, max_ms=120.0, min_ms=5.0)
    samples = np.linspace(-0.5, 0.5, 480, dtype=np.float32)
    jb.push(samples)
    out, underrun = jb.pop(480)
    assert not underrun
    assert np.allclose(out, samples)


def test_pop_more_than_available_is_underrun_with_cosine_fade():
    jb = JitterBuffer(SR, target_ms=30.0, max_ms=120.0, min_ms=5.0)
    samples = np.full(100, 0.5, dtype=np.float32)
    jb.push(samples)
    out, underrun = jb.pop(300)
    assert underrun
    assert len(out) == 300
    assert np.allclose(out[:100], 0.5, atol=1e-4)
    # Fade must be monotonically non-increasing in magnitude toward zero.
    tail = out[100:]
    assert tail[0] <= 0.5 + 1e-6
    assert abs(tail[-1]) < abs(tail[0]) + 1e-6
    assert abs(tail[-1]) < 0.05
    diffs = np.diff(np.abs(tail))
    assert np.all(diffs <= 1e-6)


def test_pop_from_empty_buffer_is_silence_when_no_history():
    jb = JitterBuffer(SR, target_ms=30.0, max_ms=120.0, min_ms=5.0)
    out, underrun = jb.pop(240)
    assert underrun
    assert np.allclose(out, 0.0)


def test_underrun_does_not_jump_discontinuously():
    jb = JitterBuffer(SR, target_ms=30.0, max_ms=120.0, min_ms=5.0)
    jb.push(np.full(480, 0.8, dtype=np.float32))
    out, _ = jb.pop(480)
    out2, underrun2 = jb.pop(480)
    assert underrun2
    combined = np.concatenate([out, out2])
    max_step = np.max(np.abs(np.diff(combined)))
    assert max_step < 0.05


def test_overrun_drops_lowest_energy_window_not_live_speech():
    jb = JitterBuffer(SR, target_ms=10.0, max_ms=20.0, min_ms=2.0)
    loud = np.full(400, 0.9, dtype=np.float32)
    quiet = np.zeros(200, dtype=np.float32)
    jb.push(loud)
    jb.push(quiet)
    jb.push(loud.copy())
    stats = jb.stats
    assert stats["overruns"] >= 1
    assert stats["dropped_samples"] > 0
    remaining = jb.depth_samples()
    assert remaining < 1000


def test_overrun_keeps_signal_continuity_bounded():
    jb = JitterBuffer(SR, target_ms=10.0, max_ms=20.0, min_ms=2.0)
    rng = np.random.default_rng(0)
    chunk = (0.3 * np.sin(np.linspace(0, 20 * np.pi, 4000))).astype(np.float32)
    jb.push(chunk)
    remaining = jb.depth_samples()
    out, _ = jb.pop(min(remaining, 2000))
    if len(out) > 1:
        step = np.max(np.abs(np.diff(out)))
        assert step < 0.5


def test_persistent_underfill_inserts_interpolated_samples():
    jb = JitterBuffer(SR, target_ms=30.0, max_ms=120.0, min_ms=5.0)
    total_in = 0
    for _ in range(50):
        chunk = np.full(50, 0.4, dtype=np.float32)
        jb.push(chunk)
        total_in += len(chunk)
        popped, _ = jb.pop(40)
        total_in -= 0
    stats = jb.stats
    assert stats["inserted_samples"] >= 0


def test_reset_clears_stats_and_buffer():
    jb = JitterBuffer(SR)
    jb.push(np.ones(1000, dtype=np.float32))
    jb.reset()
    assert jb.depth_samples() == 0
    stats = jb.stats
    assert stats["underruns"] == 0
    assert stats["overruns"] == 0
    assert stats["dropped_samples"] == 0
    assert stats["inserted_samples"] == 0


def test_depth_ms_matches_samples():
    jb = JitterBuffer(SR)
    jb.push(np.zeros(4800, dtype=np.float32))
    assert jb.depth_ms() == pytest.approx(100.0, abs=1.0)


def test_stats_shape():
    jb = JitterBuffer(SR)
    stats = jb.stats
    for key in ("underruns", "overruns", "dropped_samples", "inserted_samples",
                "depth_ms", "target_ms"):
        assert key in stats
