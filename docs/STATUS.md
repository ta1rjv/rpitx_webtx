# Project Status

Phase: DEVELOPMENT (hardware bring-up substantially complete; on-air
reception confirmation and browser/UI testing are the remaining gates to
MAINTENANCE)
Last updated: 2026-09-02

## Truth levels
PLANNED / IMPLEMENTED / REVIEWED / VALIDATED / MEASURED / UNKNOWN

| Area | State | Evidence |
|---|---|---|
| Latency root cause analysis | MEASURED (source analysis) | `docs/LATENCY.md`, upstream file:line references |
| DSP core (USB/LSB/FM/AM) | VALIDATED on real hardware | `tests/test_dsp.py`, 110/110 passing on a real Raspberry Pi 2 (armv7l), including the ARM-specific frame-time budget (see `docs/LATENCY.md` 2.1) |
| Jitter buffer | VALIDATED on real hardware | `tests/test_jitter.py`, passing on-device |
| Backend server and protocol | VALIDATED on real hardware | `tests/test_server.py` 15/15 on-device; also exercised live against the running server with a real WebSocket client (hello / start_tx / binary audio frames while keyed / stop_tx / clean disconnect) |
| Transmitter sink management | VALIDATED on real hardware | `tests/test_tx.py`, 20/20 on-device; `webtx_iq`/`webtx-sendiq` resolved and launched correctly with real binaries present |
| `native/webtx_iq` / `native/webtx-sendiq` | IMPLEMENTED and VALIDATED (builds, links, runs) | Compiled and linked on a real Raspberry Pi 2 (Ubuntu 22.04, armv7l) with zero external rpitx/librpitx download; confirmed as valid, fully-linked ARM ELF binaries (`file`, `ldd`) |
| `install.sh` | VALIDATED end-to-end, including self-healing dependency logic | Run start-to-finish on a real Pi 2; confirmed it detects Ubuntu 22.04's too-old apt aiohttp (3.8.1) and upgrades to >=3.9 via pip with no manual intervention |
| systemd service | VALIDATED (smoke-tested) | install / daemon-reload / start / status / stop confirmed on-device; not left enabled |
| RF keydown - USB, 145.5 MHz | Software path VALIDATED; on-air reception NOT independently confirmed | `native/webtx_iq --ptt-gate` executed cleanly through the real server with real parameters (145,500,000 Hz, USB, tx_power=1.0, ~9 s of a 440 Hz tone), zero crash/error/SinkError, clean exit. The user monitored with their own SDR at the time; whether the signal was actually received/decoded was not reported back to this session, so it is recorded here as unconfirmed either way, not as a pass. |
| RF keydown - FM, 145.5 MHz | NOT ATTEMPTED (blocked) | Blocked by Claude Code's own "auto mode classifier" permission gate on the command that starts the server for this test - a platform-level restriction, not a defect in this project. Confirmed identically on two independent attempts (a builder subagent, and this session's own direct command). Deferred at the user's explicit direction rather than pursued further. |
| RF keydown - LSB, AM | NOT ATTEMPTED | Only USB was tried; FM was blocked before it ran; LSB and AM were never attempted in any mode |
| Frontend dashboard in a real browser | NOT VERIFIED - deferred to the user | No browser or display is available in this environment. The user has stated they will test the web UI themselves once the project is complete. |
| Actual glass-to-air latency | NOT MEASURED | Only process-execution timing is confirmed on real hardware; no receiver-side latency measurement exists |

## VALIDATED on real hardware (Raspberry Pi 2 Model B Rev 1.1, Ubuntu 22.04.5 LTS, armv7l, BCM2836 - 2026-09-02)

* `install.sh` end-to-end, including a self-healing fix for Ubuntu 22.04's
  apt-shipped aiohttp 3.8.1 (too old for `web.AppKey`; see
  `docs/ASSUMPTIONS.md` A-12);
* native compilation and linking of `webtx_iq` and `webtx-sendiq` with zero
  external rpitx/librpitx download (vendored build - see `docs/DECISIONS.md`
  ADR-009/ADR-010);
* the full automated test suite: 110/110 passing on-device, including the
  complete WebSocket protocol suite (`tests/test_server.py`, 15/15) and
  sink-resolution logic against real binaries (`tests/test_tx.py`, 20/20);
* the real server's WebSocket protocol against a live client;
* systemd service install/start/status/stop;
* one real RF keydown (USB, 145.5 MHz, `--ptt-gate`) executing the complete
  code path with zero errors - see the RF keydown rows above for exactly
  what this does and does not prove.

Three real bugs were found and fixed during this hardware validation - see
`docs/CHANGELOG.md` v2.0.1: an aiohttp version-floor gap in `install.sh`, a
test-isolation bug affecting 6 tests in `tests/test_tx.py` that had never
been exercised against real binaries before (every prior test run, on any
machine, happened to lack the ARM-only binaries these tests check for), and
an ARM-specific DSP frame-time budget that was calibrated too tight against
x86-only measurements.

## NOT VERIFIED

The following remain genuinely unverified and are left for the user's own
follow-up:

* whether the 145.5 MHz USB test signal was actually received and decoded
  correctly on the user's SDR - not reported back to this session;
* FM, LSB, and AM modes on air (FM blocked by a Claude Code permission
  gate; LSB and AM never attempted);
* actual measured (not process-timing-derived) glass-to-air latency;
* underrun behaviour at the default `fifo_samples` under sustained
  transmission, on this or other Pi models;
* the full browser/UI experience on a real device: microphone permission
  flow, VU meter, PTT input methods (mouse/touch/keyboard), reconnect
  behavior - the user has said they will test this directly once the
  project is complete.
