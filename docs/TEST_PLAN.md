# Test Plan

Status: VALIDATED for everything listed under "Automated (passing)" - on
x86 (null sink) and, since 2026-09-02, on a real Raspberry Pi 2 as well
(see "Validated on real hardware" below). NOT VERIFIED for anything still
listed under "Requires hardware" (see docs/STATUS.md for the full,
itemized breakdown).

## Automated (passing)

Run with: `python3 -m pytest tests/ -q`
Result at last run: **110 passed**, 0 skipped, 0 failed - both on x86 (null
sink) and on a real Raspberry Pi 2 (Ubuntu 22.04, armv7l), including the
tests that specifically exercise real ARM binaries (`tests/test_tx.py`).
Runs on any x86 or ARM Linux machine with `numpy`, `aiohttp` (>=3.9 - see
`docs/ASSUMPTIONS.md` A-12), `pytest` installed - no Raspberry Pi or rpitx
required, because `sink.kind: "null"` discards IQ instead of driving
hardware.

| File | Covers |
|---|---|
| `tests/test_dsp.py` | USB/LSB opposite-sideband suppression (>=40 dB, FFT-measured), FM constant envelope, AM envelope formula and clipping, frame-vs-one-shot continuity (proves no click at frame boundaries), soft limiter bounds, AGC response, platform-aware per-frame timing budget (<2ms x86, <6ms ARM - see `docs/LATENCY.md` 2.1). |
| `tests/test_jitter.py` | Normal push/pop, underrun cosine fade and continuity, overrun lowest-energy-window drop, persistent-underfill interpolation, stats correctness, reset. |
| `tests/test_metrics.py` | `LatencyTracker` rolling stats (last/avg/p95/max), window bounding, `RateMeter` windowed rate and pruning. |
| `tests/test_config.py` | Defaults, deep merge, CLI/env/cwd precedence, every validation rule (each tested to actually fire), `default_json_text()` round-trip. |
| `tests/test_tx.py` | Null-sink lifecycle, idempotent double-start, safe stop-without-start, restart-after-stop, exact argv construction for both `webtx_iq` and `sendiq`, no `shell=True`/`preexec_fn`, non-root refusal, exact interleaved-float32 byte layout. |
| `tests/test_server.py` | Full WebSocket protocol against a real aiohttp app (null sink): hello/hello_ack/state, start_tx/stop_tx, binary audio frames, ping/pong, every validation error path, single-TX-owner enforcement, disconnect force-stops TX, gain/mode changes never replace the sink object. |

## Manual (performed during development)

- `webtx/static/app.js` and `mic-processor.js`: `node --check` (no syntax
  errors). Not yet exercised in a real browser - see "Requires hardware".

## Validated on real hardware (Raspberry Pi 2 Model B Rev 1.1, Ubuntu 22.04.5 LTS, armv7l - 2026-09-02)

See `docs/STATUS.md` for the complete, itemized breakdown. Summary:

- `native/webtx_iq` and `native/webtx-sendiq`: not just syntax-checked -
  actually compiled and linked with zero external rpitx download,
  confirmed as valid ARM ELF binaries with all runtime dependencies
  resolved (`file`, `ldd`).
- `install.sh` end-to-end, including a self-healing fix for an aiohttp
  version gap found during this run (see `docs/CHANGELOG.md` v2.0.1).
- The full test suite (110/110) and the WebSocket protocol against a live
  server and a real client.
- `systemd/webtx.service` install/start/status/stop.
- One real RF keydown: `native/webtx_iq --ptt-gate` at 145.5 MHz, USB,
  through the full real server, ~9 s of a 440 Hz tone, zero crashes or
  errors. This proves the software path executes correctly end-to-end; it
  does **not** by itself prove RF was received - see "Requires hardware".

## Requires hardware (NOT run by this project)

These require further work on a physical Raspberry Pi with a receiver or
dummy load, and are listed so nobody mistakes their absence for a pass:

- Independent confirmation that the 145.5 MHz USB keydown above was
  actually received/decoded correctly (the user monitored with their own
  SDR at the time; this was not reported back to this session).
- FM, LSB, and AM on air (FM was attempted but blocked by a Claude Code
  platform-level permission gate, not a project defect; LSB/AM were never
  attempted).
- `--ptt-gate` actually suppressing the carrier, confirmed by an
  instrument rather than by the process exiting cleanly (checking
  `/sys/kernel/debug/clk` was tried and found to be the wrong instrument -
  `enableclk`/`disableclk` poke `/dev/mem` directly and never touch the
  Linux clock framework debugfs reflects).
- A receiver-side check of audio quality and opposite-sideband suppression
  in the real RF domain (as opposed to the FFT check on the baseband IQ in
  `test_dsp.py`).
- The actual measured glass-to-air latency (docs/LATENCY.md's numbers are
  derived from source analysis, unit-test timings, and now one real
  frame-processing measurement - not an on-air clock).
- Underrun behavior and CPU headroom at the recommended `fifo_samples`
  under sustained transmission, on this or other Pi models.
- Browser behavior specifically on a real device (VU meter, AudioWorklet,
  PTT input methods, mic permission flow, reconnect behavior) - the user
  has said they will test this themselves once the project is complete;
  no browser or display is available in this environment.

## Regression policy

Any change to `webtx/dsp.py`, `webtx/jitter.py`, or `webtx/tx.py` must keep
`python3 -m pytest tests/ -q` fully green before being considered done.
Any change to the WebSocket protocol in `webtx/server.py` must have a
corresponding scenario added to `tests/test_server.py` in the same change.
