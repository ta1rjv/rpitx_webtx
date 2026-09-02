import time

import pytest

from webtx.metrics import LatencyTracker, RateMeter, Stage


def test_snapshot_empty_is_zeroed():
    lt = LatencyTracker(window=10)
    snap = lt.snapshot()
    assert snap["frames"] == 0
    for stage in Stage:
        assert snap[stage.value] == {"last": 0.0, "avg": 0.0, "p95": 0.0, "max": 0.0}


def test_observe_updates_last_and_max():
    lt = LatencyTracker(window=10)
    lt.observe(Stage.NET, 5.0)
    lt.observe(Stage.NET, 15.0)
    snap = lt.snapshot()
    assert snap["net"]["last"] == 15.0
    assert snap["net"]["max"] == 15.0


def test_frames_counts_total_observations_only():
    lt = LatencyTracker(window=50)
    lt.observe(Stage.NET, 1.0)
    lt.observe(Stage.DSP, 1.0)
    assert lt.snapshot()["frames"] == 0
    lt.observe(Stage.TOTAL, 10.0)
    assert lt.snapshot()["frames"] == 1
    lt.observe(Stage.TOTAL, 10.0)
    assert lt.snapshot()["frames"] == 2


def test_p95_within_range():
    lt = LatencyTracker(window=100)
    for v in range(1, 101):
        lt.observe(Stage.SINK, float(v))
    snap = lt.snapshot()
    assert 90.0 <= snap["sink"]["p95"] <= 100.0


def test_window_bounds_history():
    lt = LatencyTracker(window=5)
    for v in [1, 2, 3, 4, 5, 100]:
        lt.observe(Stage.JITTER, float(v))
    snap = lt.snapshot()
    assert snap["jitter"]["max"] == 100.0
    assert snap["jitter"]["avg"] == pytest.approx((2 + 3 + 4 + 5 + 100) / 5)


def test_reset_clears_all_stages():
    lt = LatencyTracker()
    lt.observe(Stage.TOTAL, 42.0)
    lt.reset()
    snap = lt.snapshot()
    assert snap["frames"] == 0
    assert snap["total"]["last"] == 0.0


def test_invalid_window_raises():
    with pytest.raises(ValueError):
        LatencyTracker(window=0)


def test_rate_meter_zero_when_empty():
    rm = RateMeter(window_s=1.0)
    fps, bps = rm.rate()
    assert fps == 0.0
    assert bps == 0.0


def test_rate_meter_counts_marks():
    rm = RateMeter(window_s=5.0)
    for _ in range(10):
        rm.mark(1000)
    fps, bps = rm.rate()
    assert fps > 0
    assert bps > 0


def test_rate_meter_prunes_old_events():
    rm = RateMeter(window_s=0.05)
    rm.mark(500)
    time.sleep(0.1)
    fps, bps = rm.rate()
    assert fps == 0.0
    assert bps == 0.0


def test_invalid_rate_meter_window_raises():
    with pytest.raises(ValueError):
        RateMeter(window_s=0)
