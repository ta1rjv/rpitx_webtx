"""Per-stage latency tracking and throughput metering.

Used to answer, concretely, "where is the delay": webtx/server.py records one
observation per stage per audio frame (NET, JITTER, DSP, SINK, TOTAL) and pushes
a snapshot to the browser every 500 ms so the operator sees a live breakdown
instead of a single opaque number. See docs/LATENCY.md section 3.
"""

from __future__ import annotations

import time
from collections import deque
from enum import Enum


class Stage(str, Enum):
    NET = "net"
    JITTER = "jitter"
    DSP = "dsp"
    SINK = "sink"
    TOTAL = "total"


class LatencyTracker:
    """Rolling per-stage latency statistics, in milliseconds."""

    def __init__(self, window: int = 200):
        if window <= 0:
            raise ValueError("window must be positive")
        self._window = window
        self._series = {stage: deque(maxlen=window) for stage in Stage}
        self._frames = 0

    def observe(self, stage: Stage, ms: float) -> None:
        """Record one latency sample for `stage`, in milliseconds."""
        self._series[stage].append(float(ms))
        if stage is Stage.TOTAL:
            self._frames += 1

    def reset(self) -> None:
        for dq in self._series.values():
            dq.clear()
        self._frames = 0

    def snapshot(self) -> dict:
        """Return {stage_name: {'last','avg','p95','max'}, ..., 'frames': int}."""
        result: dict = {"frames": self._frames}
        for stage, dq in self._series.items():
            if not dq:
                result[stage.value] = {"last": 0.0, "avg": 0.0, "p95": 0.0, "max": 0.0}
                continue
            values = sorted(dq)
            p95_idx = min(len(values) - 1, int(round(0.95 * (len(values) - 1))))
            result[stage.value] = {
                "last": dq[-1],
                "avg": sum(dq) / len(dq),
                "p95": values[p95_idx],
                "max": values[-1],
            }
        return result


class RateMeter:
    """Sliding-window frames/s and bytes/s meter."""

    def __init__(self, window_s: float = 2.0):
        if window_s <= 0:
            raise ValueError("window_s must be positive")
        self._window_s = window_s
        self._events = deque()  # (timestamp, n_bytes)

    def mark(self, n_bytes: int) -> None:
        now = time.monotonic()
        self._events.append((now, n_bytes))
        self._prune(now)

    def _prune(self, now: float) -> None:
        cutoff = now - self._window_s
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def rate(self) -> tuple:
        now = time.monotonic()
        self._prune(now)
        if not self._events:
            return 0.0, 0.0
        span = max(now - self._events[0][0], 1e-6)
        total_bytes = sum(n for _, n in self._events)
        frames_per_s = len(self._events) / span
        bytes_per_s = total_bytes / span
        return frames_per_s, bytes_per_s
