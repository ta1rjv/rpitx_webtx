"""Audio-to-IQ modulator core: USB, LSB, FM and AM.

Replaces the old csdr shell pipeline (convert_i16_f | gain_ff | dsb_fc |
bandpass_fir_fft_cc) with in-process NumPy FIR/IIR DSP. This removes four
process hops, their pipe buffers, and the FFT overlap-add block latency of the
old chain (see docs/LATENCY.md section 1.4).

All phase/frequency state uses float64 (RF engineering rule: never use float32
for accumulated phase, it loses precision over a multi-minute transmission).
Audio and IQ payloads use float32/complex64, matching the wire format sent to
the transmitter sink.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Tuple

import numpy as np

MODES: Tuple[str, ...] = ("USB", "LSB", "FM", "AM")


@dataclass
class ModConfig:
    ssb_low_hz: float = 300.0
    ssb_high_hz: float = 2700.0
    fm_deviation_hz: float = 2500.0
    am_modulation_index: float = 0.85
    am_carrier_level: float = 0.5
    audio_hpf_hz: float = 200.0
    hilbert_taps: int = 129
    limiter_enabled: bool = True
    agc_enabled: bool = True
    agc_target: float = 0.35
    agc_attack_ms: float = 5.0
    agc_release_ms: float = 300.0


def make_silence_iq(n: int) -> np.ndarray:
    """Return n complex64 zero samples (used to prime the sink before audio arrives)."""
    return np.zeros(n, dtype=np.complex64)


def _design_hilbert(taps: int) -> np.ndarray:
    """Windowed-sinc Hilbert transformer, odd length, Blackman window.

    h[k] = 2/(pi*k) for odd k, 0 for even k, k in [-(taps-1)/2, (taps-1)/2].
    This is a Type III linear-phase FIR with group delay (taps-1)/2 samples.
    """
    if taps % 2 == 0:
        raise ValueError("hilbert_taps must be odd")
    half = (taps - 1) // 2
    k = np.arange(-half, half + 1, dtype=np.float64)
    h = np.zeros_like(k)
    odd_mask = (k.astype(np.int64) % 2 != 0)
    h[odd_mask] = 2.0 / (np.pi * k[odd_mask])
    window = np.blackman(taps)
    return (h * window).astype(np.float64)


def _design_bandpass(low_hz: float, high_hz: float, sample_rate: int, taps: int) -> np.ndarray:
    """Windowed-sinc bandpass FIR, odd length, Hamming window, unity passband gain."""
    if taps % 2 == 0:
        taps += 1
    half = (taps - 1) // 2
    n = np.arange(-half, half + 1, dtype=np.float64)
    low_norm = low_hz / sample_rate
    high_norm = high_hz / sample_rate

    def sinc(x, f):
        out = np.full_like(x, 2.0 * f)
        nz = x != 0
        out[nz] = np.sin(2.0 * np.pi * f * x[nz]) / (np.pi * x[nz])
        return out

    h = sinc(n, high_norm) - sinc(n, low_norm)
    window = np.hamming(taps)
    h = h * window
    # Normalize to unity gain at the band center frequency.
    center = (low_norm + high_norm) / 2.0
    phase = 2.0 * np.pi * center * n
    gain = np.abs(np.sum(h * np.exp(-1j * phase)))
    if gain > 1e-12:
        h = h / gain
    return h.astype(np.float64)


class _OverlapFIR:
    """Stateful FIR filter: continuous output across successive process() calls.

    Keeps the last (len(taps)-1) input samples as history so that frame
    boundaries do not introduce clicks or discontinuities (verified in
    tests/test_dsp.py by comparing one-shot vs. framed processing).
    """

    def __init__(self, taps: np.ndarray):
        self._taps = taps.astype(np.float64)
        self._ntaps = len(taps)
        self._history = np.zeros(self._ntaps - 1, dtype=np.float64)

    @property
    def group_delay_samples(self) -> int:
        return (self._ntaps - 1) // 2

    def reset(self) -> None:
        self._history[:] = 0.0

    def process(self, x: np.ndarray) -> np.ndarray:
        extended = np.concatenate([self._history, x])
        y = np.convolve(extended, self._taps, mode="valid")
        self._history = extended[-(self._ntaps - 1):] if self._ntaps > 1 else self._history
        return y.astype(np.float64)


class _DelayLine:
    """Pure sample delay, used to time-align the in-phase path with a Hilbert filter."""

    def __init__(self, delay_samples: int):
        self._delay = delay_samples
        self._history = np.zeros(delay_samples, dtype=np.float64)

    def reset(self) -> None:
        self._history[:] = 0.0

    def process(self, x: np.ndarray) -> np.ndarray:
        if self._delay == 0:
            return x.astype(np.float64)
        extended = np.concatenate([self._history, x])
        out = extended[: len(x)]
        self._history = extended[len(x):len(x) + self._delay]
        return out.astype(np.float64)


def _soft_limit(iq: np.ndarray) -> np.ndarray:
    """Soft-knee magnitude limiter.

    Scales each complex sample by a real factor so |iq| approaches but never
    exceeds 1.0. Scaling by a real factor preserves instantaneous phase, so
    unlike clipping I and Q independently, this does not introduce phase
    discontinuities (which would splatter energy outside the intended
    passband). Samples already within the linear region are untouched.
    """
    threshold = 0.98
    mag = np.abs(iq)
    over = mag > threshold
    if np.any(mag_over := mag[over]):
        headroom = 1.0 - threshold
        excess = mag_over - threshold
        compressed = threshold + headroom * np.tanh(excess / headroom)
        scale = compressed / mag_over
        iq = iq.copy()
        iq[over] = iq[over] * scale
    return iq


class Modulator:
    """Converts a stream of mono float32 audio frames into complex64 IQ frames.

    Stateful and must be called with consecutive, contiguous audio frames of
    any length for a given transmission; internal filter and AGC/phase state
    carries over between calls so there are no clicks at frame boundaries.
    """

    def __init__(self, mode: str, sample_rate: int, config: ModConfig = None):
        if mode not in MODES:
            raise ValueError(f"unknown mode: {mode!r}, expected one of {MODES}")
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        self._mode = mode
        self._sample_rate = int(sample_rate)
        self._cfg = config if config is not None else ModConfig()
        self._gain = 1.0
        self._peak_iq = 0.0

        hilbert_taps = self._cfg.hilbert_taps
        if hilbert_taps % 2 == 0:
            hilbert_taps += 1
        self._hilbert = _OverlapFIR(_design_hilbert(hilbert_taps))
        self._audio_bp = _OverlapFIR(
            _design_bandpass(self._cfg.ssb_low_hz, self._cfg.ssb_high_hz, self._sample_rate, 129)
        )
        self._i_delay = _DelayLine(self._hilbert.group_delay_samples)

        # FM phase accumulator: float64 radians, wrapped modulo 2*pi.
        self._fm_phase = 0.0

        # AGC state (float64 envelope follower).
        self._agc_env = 1e-6
        self._agc_attack = 1.0 - math.exp(-1.0 / (max(self._cfg.agc_attack_ms, 0.01) * 1e-3 * self._sample_rate))
        self._agc_release = 1.0 - math.exp(-1.0 / (max(self._cfg.agc_release_ms, 0.01) * 1e-3 * self._sample_rate))

        self._algorithmic_delay = self._audio_bp.group_delay_samples + self._hilbert.group_delay_samples

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def latency_samples(self) -> int:
        if self._mode in ("USB", "LSB"):
            return self._algorithmic_delay
        return 0

    @property
    def latency_ms(self) -> float:
        return 1000.0 * self.latency_samples / self._sample_rate

    def set_gain(self, gain: float) -> None:
        self._gain = float(max(0.0, min(4.0, gain)))

    def reset(self) -> None:
        self._hilbert.reset()
        self._audio_bp.reset()
        self._i_delay.reset()
        self._fm_phase = 0.0
        self._agc_env = 1e-6
        self._peak_iq = 0.0

    def peak_iq(self) -> float:
        return self._peak_iq

    def _apply_agc(self, audio: np.ndarray) -> np.ndarray:
        """Block-rate peak-tracking AGC.

        The envelope follower is updated once per call using the block peak
        rather than per-sample, which keeps this well under the 2 ms/10 ms-
        frame budget in pure Python while still tracking speech dynamics
        correctly at the attack/release time constants configured (both are
        specified in milliseconds, i.e. many blocks at a 10 ms frame size).
        """
        if not self._cfg.agc_enabled:
            return audio * self._gain
        block_peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        coeff = self._agc_attack if block_peak > self._agc_env else self._agc_release
        self._agc_env += (block_peak - self._agc_env) * coeff
        env = max(self._agc_env, 1e-6)
        agc_gain = self._cfg.agc_target / env
        agc_gain = max(0.05, min(20.0, agc_gain))
        return audio * (self._gain * agc_gain)

    def process(self, audio: np.ndarray) -> np.ndarray:
        """Modulate one contiguous audio frame. audio: float32 (n,) in [-1, 1].

        Returns complex64 (n,) IQ samples. Safe to call with any frame length,
        including the 10 ms frames used by the server, with continuous filter
        and phase state across calls.
        """
        x = np.asarray(audio, dtype=np.float64)
        x = self._apply_agc(x)

        if self._mode in ("USB", "LSB"):
            bp = self._audio_bp.process(x)
            q = self._hilbert.process(bp)
            i = self._i_delay.process(bp)
            if self._mode == "USB":
                iq = (i + 1j * q).astype(np.complex64)
            else:
                iq = (i - 1j * q).astype(np.complex64)
        elif self._mode == "FM":
            dev_rad_per_sample = 2.0 * np.pi * self._cfg.fm_deviation_hz / self._sample_rate
            phase_inc = dev_rad_per_sample * x
            phase = self._fm_phase + np.cumsum(phase_inc)
            self._fm_phase = float(np.mod(phase[-1], 2.0 * np.pi)) if phase.size else self._fm_phase
            phase = np.mod(phase, 2.0 * np.pi)
            iq = (np.cos(phase) + 1j * np.sin(phase)).astype(np.complex64)
        else:  # AM
            envelope = self._cfg.am_carrier_level + self._cfg.am_modulation_index * x
            envelope = np.clip(envelope, 0.0, 1.0)
            iq = envelope.astype(np.complex64)

        if self._cfg.limiter_enabled and self._mode in ("USB", "LSB"):
            # FM's envelope is exactly 1.0 by construction (cos+j*sin of a real
            # phase) and AM's envelope is already hard-clipped to [0, 1] above;
            # limiting either would only add needless compression at a boundary
            # they already respect. Only USB/LSB can exceed unity (AGC/gain
            # applied before an unbounded Hilbert pair), so only they are limited.
            iq = _soft_limit(iq)

        self._peak_iq = float(np.max(np.abs(iq))) if iq.size else 0.0
        return iq
