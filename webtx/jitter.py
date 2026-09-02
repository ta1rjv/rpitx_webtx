"""Adaptive low-latency jitter buffer with drift correction.

Replaces the old server.py behaviour of deleting the oldest ~6 KB of audio
whenever the buffer exceeded 8 KB (`del audio_buffer[:-2048]`), which produced
an audible dropout on every overflow and did nothing to correct the underlying
clock drift between the browser's audio clock and the transmitter's DMA clock
(see docs/LATENCY.md section 1.5 and docs/DECISIONS.md ADR-005).

This buffer instead:
  - drops excess samples at the lowest-energy point of a short window when the
    buffer grows past `max_ms` (inaudible, because it removes a near-silent
    span instead of a fixed-position slice of live speech);
  - inserts a single interpolated sample every ~20 ms when the buffer is
    persistently below `target_ms` (a diameter correction far too small to be
    heard, rather than a fixed early return);
  - pads underruns with a cosine-faded tail from the last real sample instead
    of a hard jump to zero, avoiding a click.
"""

from __future__ import annotations

import threading

import numpy as np


class JitterBuffer:
    """Thread-safe FIFO of float32 mono audio samples with latency bounds.

    push() is expected to be called from the network/IO side, pop() from the
    audio worker thread that feeds the modulator at a constant frame rate;
    both are protected by an internal lock.
    """

    def __init__(self, sample_rate: int, target_ms: float = 30.0,
                 max_ms: float = 120.0, min_ms: float = 5.0):
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if not (0 < min_ms <= target_ms <= max_ms):
            raise ValueError("require 0 < min_ms <= target_ms <= max_ms")
        self._sample_rate = int(sample_rate)
        self.target_ms = float(target_ms)
        self.max_ms = float(max_ms)
        self.min_ms = float(min_ms)

        self._buf = np.zeros(0, dtype=np.float32)
        self._last_sample = 0.0
        self._lock = threading.Lock()

        self._underruns = 0
        self._overruns = 0
        self._dropped_samples = 0
        self._inserted_samples = 0
        self._insert_countdown = self._ms_to_samples(20.0)

    def _ms_to_samples(self, ms: float) -> int:
        return max(1, int(round(ms * self._sample_rate / 1000.0)))

    def reset(self) -> None:
        with self._lock:
            self._buf = np.zeros(0, dtype=np.float32)
            self._last_sample = 0.0
            self._underruns = 0
            self._overruns = 0
            self._dropped_samples = 0
            self._inserted_samples = 0
            self._insert_countdown = self._ms_to_samples(20.0)

    def push(self, samples: np.ndarray) -> None:
        """Append float32 mono samples. Trims oldest low-energy audio if the
        buffer has grown past max_ms."""
        samples = np.asarray(samples, dtype=np.float32).reshape(-1)
        with self._lock:
            self._buf = np.concatenate([self._buf, samples])
            max_samples = self._ms_to_samples(self.max_ms)
            if len(self._buf) > max_samples:
                self._overruns += 1
                target_samples = self._ms_to_samples(self.target_ms)
                self._drop_excess_locked(len(self._buf) - target_samples)

    def _drop_excess_locked(self, n_to_drop: int) -> None:
        n_to_drop = max(0, min(n_to_drop, len(self._buf)))
        window = self._ms_to_samples(5.0)
        remaining = n_to_drop
        while remaining > 0 and len(self._buf) > 0:
            w = min(window, remaining, len(self._buf))
            if w <= 0:
                break
            sq = self._buf.astype(np.float64) ** 2
            csum = np.concatenate([[0.0], np.cumsum(sq)])
            energies = csum[w:] - csum[:-w]
            if energies.size == 0:
                break
            idx = int(np.argmin(energies))
            self._buf = np.concatenate([self._buf[:idx], self._buf[idx + w:]])
            self._dropped_samples += w
            remaining -= w

    def _maybe_insert_locked(self, n_consumed: int) -> None:
        self._insert_countdown -= n_consumed
        if self._insert_countdown > 0:
            return
        self._insert_countdown += self._ms_to_samples(20.0)
        target_samples = self._ms_to_samples(self.target_ms)
        if len(self._buf) < target_samples and len(self._buf) >= 2:
            mid = len(self._buf) // 2
            interpolated = (self._buf[mid - 1] + self._buf[mid]) / 2.0
            self._buf = np.insert(self._buf, mid, np.float32(interpolated))
            self._inserted_samples += 1

    def pop(self, n: int) -> tuple:
        """Return (float32 array of length n, underrun_flag).

        On underrun, the missing tail is a cosine fade from the last emitted
        sample down to silence rather than a hard zero, so a starved buffer
        degrades to silence smoothly instead of clicking.
        """
        if n <= 0:
            return np.zeros(0, dtype=np.float32), False
        with self._lock:
            self._maybe_insert_locked(n)
            avail = len(self._buf)
            if avail >= n:
                out = self._buf[:n].copy()
                self._buf = self._buf[n:]
                underrun = False
            else:
                out_real = self._buf.copy()
                self._buf = np.zeros(0, dtype=np.float32)
                shortfall = n - avail
                fade = self._make_fade(shortfall)
                out = np.concatenate([out_real, fade]).astype(np.float32)
                self._underruns += 1
                self._inserted_samples += shortfall
                underrun = True
            if len(out):
                self._last_sample = float(out[-1])
            return out, underrun

    def _make_fade(self, shortfall: int) -> np.ndarray:
        if shortfall <= 0:
            return np.zeros(0, dtype=np.float32)
        t = np.arange(shortfall, dtype=np.float64)
        denom = max(shortfall - 1, 1)
        envelope = 0.5 * (1.0 + np.cos(np.pi * t / denom))
        return (self._last_sample * envelope).astype(np.float32)

    def depth_samples(self) -> int:
        with self._lock:
            return len(self._buf)

    def depth_ms(self) -> float:
        with self._lock:
            return 1000.0 * len(self._buf) / self._sample_rate

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "underruns": self._underruns,
                "overruns": self._overruns,
                "dropped_samples": self._dropped_samples,
                "inserted_samples": self._inserted_samples,
                "depth_ms": 1000.0 * len(self._buf) / self._sample_rate,
                "target_ms": self.target_ms,
            }
