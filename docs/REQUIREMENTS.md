# Requirements

Traceable requirement set for rpitx_webtx v2. Each requirement has an ID, a
verification method, and the artifact that verifies it.

## Functional - RF and audio

| ID | Requirement | Verification |
|---|---|---|
| F-01 | The system transmits microphone audio in USB, LSB, FM and AM. | `tests/test_dsp.py` per mode; on-air check by the operator. |
| F-02 | Opposite-sideband suppression in USB and LSB is at least 40 dB at 1 kHz. | Automated FFT assertion in `tests/test_dsp.py`. |
| F-03 | FM output has a constant envelope (`abs(IQ) == 1`) while keyed. | Automated assertion in `tests/test_dsp.py`. |
| F-04 | AM output never exceeds an IQ magnitude of 1.0. | Automated assertion in `tests/test_dsp.py`. |
| F-05 | Frame-by-frame modulation is bit-identical to modulating the same signal in one call, after the filter transient. | Continuity test in `tests/test_dsp.py`. |
| F-06 | Transmit frequency, mode, microphone gain and drive level are operator-controllable from the browser. | `tests/test_server.py`, UI. |
| F-07 | Changing microphone gain or drive level does not interrupt an active transmission. | `tests/test_server.py`. |
| F-08 | No unmodulated carrier is radiated between key-down and the first audio. | `webtx_iq --ptt-gate`; NOT VERIFIED on hardware. |

## Non-functional - latency

| ID | Requirement | Verification |
|---|---|---|
| L-01 | Glass-to-air latency with default settings is below 100 ms at 48 kHz. | Derived in `docs/LATENCY.md` section 2 from source analysis plus measured DSP timings. NOT MEASURED on air. |
| L-02 | The modulator processes a 10 ms frame with headroom to spare: under 2 ms on x86 (fast regression guard), under 6 ms on ARM (measured ~3.96-3.98 ms on Raspberry Pi 2/armv7l, see `docs/LATENCY.md` section 2.1). | Platform-aware timed assertion in `tests/test_dsp.py` (`FRAME_TIME_BUDGET_MS`). |
| L-03 | Per-stage latency is measured at runtime and shown to the operator. | `webtx/metrics.py`, metrics message, UI latency panel. |
| L-04 | Latency is tunable by configuration, with the underrun tradeoff documented. | `sink.fifo_samples`, `audio.jitter_target_ms`; `native/README.md`. |
| L-05 | Reported network latency is not a raw comparison of two unsynchronised clocks. | Baseline-offset method plus separate ping/pong RTT. |

## Non-functional - stability

| ID | Requirement | Verification |
|---|---|---|
| S-01 | The transmitter subprocess is always reaped: on stop, on client disconnect, on audio timeout, on exception, and on server shutdown. | `tests/test_tx.py`, `tests/test_server.py`, signal and atexit handlers. |
| S-02 | No orphaned process may be left holding the carrier on air. | Same as S-01. |
| S-03 | Clock drift between the browser and the DMA clock is corrected without audible dropouts. | `tests/test_jitter.py`. |
| S-04 | Only one client can key the transmitter at a time. | `tests/test_server.py`. |
| S-05 | The client reconnects automatically and returns to a safe unkeyed state on disconnect. | UI reconnect logic with capped backoff. |
| S-06 | The whole application, including tests, runs on a non-Pi machine with the `null` sink. | `python3 -m pytest tests/` on x86. |

## Non-functional - security and compliance

| ID | Requirement | Verification |
|---|---|---|
| C-01 | No subprocess is launched through a shell, and no command is built by string interpolation. | Code review, `tests/test_tx.py` argv assertions. |
| C-02 | Frequency, mode and drive level are validated before reaching the transmitter; out-of-range values are rejected, not clamped silently. | `tests/test_config.py`, `tests/test_server.py`. |
| C-03 | The operator can restrict transmission to specific frequency ranges. | `rf.allowed_ranges`. |
| C-04 | Nothing in this project raises RF output beyond what stock rpitx permits. | ADR-008, code review. |
| C-05 | The mandatory harmonic filtering requirement is stated prominently in the README. | `README.md`. |

## Operational

| ID | Requirement | Verification |
|---|---|---|
| O-01 | Installation is a single command on a clean Raspberry Pi OS system. | `install.sh`; NOT VERIFIED on hardware. |
| O-02 | Configuration is a file, not a source edit. | `webtx/config.py`, `webtx.example.json`. |
| O-03 | The service can run under systemd and restart automatically. | `systemd/webtx.service`. |
| O-04 | Logs are structured, levelled, and optionally written to a file. | `webtx/config.py` `log` section. |
| O-05 | Documentation covers installation, operation, configuration, troubleshooting and latency tuning. | `README.md`, `docs/`. |
