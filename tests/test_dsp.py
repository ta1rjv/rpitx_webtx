import platform
import time

import numpy as np
import pytest

from webtx.dsp import Modulator, ModConfig, MODES, make_silence_iq


SAMPLE_RATE = 48000
FRAME = 480  # 10 ms

# Frame-processing time budget for test_frame_processing_time_budget below.
# Tight (2 ms) on x86: a fast-regression guard, still valid there and left
# unchanged. Looser (6 ms) on ARM (Raspberry Pi and similar): measured on a
# real Raspberry Pi 2 (armv7l, BCM2836, Ubuntu 22.04, 2026-09-02), this same
# test averaged USB 3.977 ms/frame and LSB 3.956 ms/frame (see
# docs/LATENCY.md). The 10 ms frame period (FRAME = 480 samples @ 48 kHz)
# still leaves ~60% real-time margin at that measured cost, so 6 ms is a
# measured-headroom regression guard, not an arbitrary number - the old 2 ms
# figure was only ever calibrated against x86 and was never valid on target
# hardware. Detected the same way native/Makefile picks UNAME_M (arm%/aarch64).
_MACHINE = platform.machine().lower()
_IS_ARM = _MACHINE.startswith("arm") or _MACHINE == "aarch64"
FRAME_TIME_BUDGET_MS = 6.0 if _IS_ARM else 2.0


def tone(freq_hz, n, sample_rate=SAMPLE_RATE, amp=0.5):
    t = np.arange(n) / sample_rate
    return (amp * np.sin(2 * np.pi * freq_hz * t)).astype(np.float32)


def test_modes_tuple():
    assert MODES == ("USB", "LSB", "FM", "AM")


def test_make_silence_iq():
    z = make_silence_iq(100)
    assert z.dtype == np.complex64
    assert z.shape == (100,)
    assert np.all(z == 0)


@pytest.mark.parametrize("mode", MODES)
def test_process_shape_and_dtype(mode):
    mod = Modulator(mode, SAMPLE_RATE)
    audio = tone(1000, FRAME)
    out = mod.process(audio)
    assert out.dtype == np.complex64
    assert out.shape == (FRAME,)


@pytest.mark.parametrize("mode", MODES)
def test_no_nan_or_inf(mode):
    mod = Modulator(mode, SAMPLE_RATE)
    mod.set_gain(2.0)
    audio = tone(1500, FRAME, amp=0.9)
    for _ in range(20):
        out = mod.process(audio)
        assert np.all(np.isfinite(out.real))
        assert np.all(np.isfinite(out.imag))


def test_fm_constant_envelope():
    mod = Modulator("FM", SAMPLE_RATE)
    audio = tone(800, FRAME * 10, amp=0.8)
    out = mod.process(audio)
    mag = np.abs(out)
    assert np.allclose(mag, 1.0, atol=1e-5)


def test_am_never_exceeds_unity():
    cfg = ModConfig(am_carrier_level=0.5, am_modulation_index=0.85)
    mod = Modulator("AM", SAMPLE_RATE, cfg)
    audio = tone(1000, FRAME * 5, amp=1.0)
    out = mod.process(audio)
    assert np.all(np.abs(out) <= 1.0 + 1e-6)
    assert np.all(out.imag == 0)


def test_am_envelope_matches_formula():
    cfg = ModConfig(am_carrier_level=0.5, am_modulation_index=0.85, limiter_enabled=False,
                     agc_enabled=False)
    mod = Modulator("AM", SAMPLE_RATE, cfg)
    audio = tone(1000, FRAME, amp=0.3)
    out = mod.process(audio)
    expected = np.clip(0.5 + 0.85 * audio.astype(np.float64), 0.0, 1.0)
    assert np.allclose(out.real, expected, atol=1e-5)


@pytest.mark.parametrize("mode,other_sideband_mult", [("USB", -1), ("LSB", 1)])
def test_ssb_opposite_sideband_suppression(mode, other_sideband_mult):
    """Analytic-signal check: USB must suppress the negative-frequency image
    and LSB must suppress the positive-frequency image by >= 40 dB at 1 kHz."""
    cfg = ModConfig(limiter_enabled=False, agc_enabled=False)
    mod = Modulator(mode, SAMPLE_RATE, cfg)
    n = 48000 * 2
    audio = tone(1000, n, amp=0.5)
    # Feed in 10 ms frames to exercise the real streaming path.
    out = np.concatenate([mod.process(audio[i:i + FRAME]) for i in range(0, n, FRAME)])
    # Discard the filter transient (first 4096 samples).
    out = out[4096:]
    spectrum = np.fft.fft(out)
    freqs = np.fft.fftfreq(len(out), d=1.0 / SAMPLE_RATE)

    def bin_at(f):
        return int(np.argmin(np.abs(freqs - f)))

    wanted_bin = bin_at(1000.0 if mode == "USB" else -1000.0)
    image_bin = bin_at(-1000.0 if mode == "USB" else 1000.0)
    wanted_mag = np.abs(spectrum[wanted_bin])
    image_mag = np.abs(spectrum[image_bin])
    suppression_db = 20 * np.log10(wanted_mag / max(image_mag, 1e-9))
    assert suppression_db >= 40.0, f"{mode} suppression only {suppression_db:.1f} dB"


def test_ssb_continuity_framed_matches_oneshot():
    """Processing in 10 ms frames must match one-shot processing after the
    initial filter transient, proving overlap-save state carries correctly
    across process() calls (no per-frame clicks)."""
    cfg = ModConfig(limiter_enabled=False, agc_enabled=False)
    n = 48000
    audio = tone(700, n, amp=0.4)

    mod_oneshot = Modulator("USB", SAMPLE_RATE, cfg)
    out_oneshot = mod_oneshot.process(audio)

    mod_framed = Modulator("USB", SAMPLE_RATE, cfg)
    chunks = [mod_framed.process(audio[i:i + FRAME]) for i in range(0, n, FRAME)]
    out_framed = np.concatenate(chunks)

    transient = 512
    assert np.allclose(
        out_oneshot[transient:], out_framed[transient:], atol=1e-4
    )


def test_limiter_keeps_ssb_within_unity():
    cfg = ModConfig(agc_enabled=False)
    mod = Modulator("USB", SAMPLE_RATE, cfg)
    mod.set_gain(4.0)
    audio = tone(1000, FRAME * 4, amp=1.0)
    out = mod.process(audio)
    assert np.all(np.abs(out) <= 1.0 + 1e-6)


def test_agc_brings_quiet_signal_toward_target():
    cfg = ModConfig(agc_enabled=True, agc_target=0.35, agc_attack_ms=5.0, agc_release_ms=50.0,
                     limiter_enabled=False)
    mod = Modulator("AM", SAMPLE_RATE, cfg)
    quiet = tone(1000, FRAME * 200, amp=0.02)
    out = None
    for i in range(0, len(quiet), FRAME):
        out = mod.process(quiet[i:i + FRAME])
    envelope_peak = float(np.max(np.abs(out.real - cfg.am_carrier_level)))
    assert envelope_peak > 0.02  # AGC raised the modulation above the raw quiet level


def test_reset_clears_state():
    mod = Modulator("USB", SAMPLE_RATE)
    audio = tone(1000, FRAME * 5, amp=0.8)
    mod.process(audio)
    mod.reset()
    silence = np.zeros(FRAME, dtype=np.float32)
    out = mod.process(silence)
    assert np.allclose(out, 0.0, atol=1e-3)


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        Modulator("WSPR", SAMPLE_RATE)


def test_latency_ms_reported_for_ssb():
    mod = Modulator("USB", SAMPLE_RATE)
    assert mod.latency_samples > 0
    assert mod.latency_ms == pytest.approx(1000.0 * mod.latency_samples / SAMPLE_RATE)


def test_fm_latency_is_zero():
    mod = Modulator("FM", SAMPLE_RATE)
    assert mod.latency_samples == 0


@pytest.mark.parametrize("mode", MODES)
def test_frame_processing_time_budget(mode):
    """A 10 ms (480-sample) frame must modulate in well under the platform
    budget on average (FRAME_TIME_BUDGET_MS above: 2 ms on x86, 6 ms on ARM,
    the latter a measured-headroom guard from real Raspberry Pi 2 hardware),
    since it runs alongside network I/O and sink writes in the same real-time
    budget (see docs/REQUIREMENTS.md L-02)."""
    mod = Modulator(mode, SAMPLE_RATE)
    audio = tone(1200, FRAME, amp=0.6)
    # Warm up (first calls may pay allocation/cache costs).
    for _ in range(10):
        mod.process(audio)
    iterations = 200
    start = time.perf_counter()
    for _ in range(iterations):
        mod.process(audio)
    elapsed = time.perf_counter() - start
    avg_ms = 1000.0 * elapsed / iterations
    assert avg_ms < FRAME_TIME_BUDGET_MS, (
        f"{mode} average frame time {avg_ms:.3f} ms exceeds "
        f"{FRAME_TIME_BUDGET_MS} ms budget (platform.machine()={platform.machine()!r})"
    )
