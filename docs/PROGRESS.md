# Progress

Project phase: DEVELOPMENT (implementation complete and hardware-validated
on a real Raspberry Pi 2; on-air reception confirmation and browser/UI
testing are the remaining gates to MAINTENANCE - see docs/STATUS.md and
docs/TEST_PLAN.md for exactly what that means).

## Done

- Root-cause analysis of the tune-tone/latency bug, with upstream
  file:line evidence (docs/LATENCY.md).
- Full v2 backend: `webtx/dsp.py`, `webtx/jitter.py`, `webtx/metrics.py`,
  `webtx/config.py`, `webtx/tx.py`, `webtx/server.py`, `webtx/__main__.py`.
- 110 automated tests, all passing - both on any machine via the null sink
  (docs/TEST_PLAN.md) and, since 2026-09-02, on a real Raspberry Pi 2
  (Ubuntu 22.04, armv7l), including the full WebSocket protocol suite and
  sink-resolution logic against real ARM binaries.
- `native/webtx_iq.cpp` + `Makefile` + README: low-latency transmitter -
  now built, linked, and run on real Raspberry Pi hardware (see below),
  not just syntax-checked.
- `vendor/librpitx`: librpitx vendored into the repo (unmodified,
  GPL-3.0), built automatically by `native/Makefile` when no system
  install is found - no separate rpitx download needed for the
  recommended path (docs/DECISIONS.md ADR-009). Top-level `LICENSE`
  (MIT) and `vendor/NOTICE.md` added for license clarity.
- `patches/sendiq-lowlatency.patch`: optional stock-sendiq patch, applied
  and diff-verified against a clean upstream copy.
- `vendor/rpitx-src`: rpitx's outer source tree vendored into the repo
  (commit `ee7ff57b77962536fda4daa523749c04af6beec7`, GPL-3.0; only
  `sendiq.cpp` is modified - the same low-latency patch as
  `patches/sendiq-lowlatency.patch`, applied directly with a top-of-file
  notice - see docs/DECISIONS.md ADR-010). `native/Makefile` builds it as
  `native/webtx-sendiq`, now confirmed building on real ARM hardware
  against the vendored librpitx, so the stock-`sendiq`-compatible fallback
  sink also needs no separate rpitx download. `webtx/tx.py` prefers it
  automatically over a real separate rpitx install; every other vendored
  tool (SSTV, POCSAG, FT8, DVB, ...) is source-available only, with no
  build target.
- Full frontend rewrite: `webtx/templates/index.html`, `webtx/static/
  {app.css,app.js,mic-processor.js}` - instrument-panel dashboard, no
  external dependencies, `node --check` clean. Not yet exercised in a
  real browser (see Remaining).
- `install.sh`, `systemd/webtx.service`, `tools/gen-cert.sh`,
  `webtx.example.json` - `install.sh` now confirmed running start-to-finish
  on a real Pi, including a self-healing dependency check added after
  hardware testing found a gap (see below).
- README.md rewritten (16 sections per the project brief); docs/
  ARCHITECTURE.md, ASSUMPTIONS.md, DECISIONS.md, REQUIREMENTS.md,
  TEST_PLAN.md, STATUS.md, CHANGELOG.md, PROGRESS.md, AGENT.md all present
  and kept in sync with hardware validation results.
- Old v1 implementation preserved under `legacy/`, not deleted.

### Hardware validation (2026-09-02, Raspberry Pi 2 Model B Rev 1.1)

First real-hardware run of the full stack, on a Raspberry Pi 2 (Ubuntu
22.04.5 LTS, armv7l, BCM2836) reachable over SSH. See docs/STATUS.md for
the complete, itemized validated/not-verified breakdown. Highlights:

- Native binaries (`webtx_iq`, `webtx-sendiq`) compiled and linked
  successfully with zero external rpitx download, confirmed as valid ARM
  ELF executables with all runtime dependencies resolved.
- Found and fixed three real bugs invisible on any x86 dev machine (see
  `docs/CHANGELOG.md` v2.0.1): an `install.sh` dependency check that
  accepted an aiohttp too old for this project's `web.AppKey` usage
  (Ubuntu 22.04's apt package is 3.8.1, `webtx/server.py` needs >=3.9);
  six `tests/test_tx.py` tests that were never actually hermetic and only
  passed by accident because no prior test run anywhere had real ARM
  binaries on disk; and a DSP frame-time budget in `tests/test_dsp.py`
  calibrated too tight for real ARM hardware (measured ~3.96-3.98 ms/frame
  on this Pi 2 vs. an assumed 2 ms). All three fixes were re-verified on
  the device after the fact: 110/110 tests passing, and `install.sh`
  self-healing the aiohttp gap with no manual intervention.
- One real RF keydown executed: 145.5 MHz, USB, `--ptt-gate`, ~9 s of a
  440 Hz test tone, through the full real server with real config values,
  zero crashes/errors. The user monitored with their own SDR; reception
  was not confirmed back to this session either way.
- A second keydown (same frequency, FM) was blocked twice - once for a
  builder sub-agent, once for this session's own direct attempt - by
  Claude Code's own "auto mode classifier" permission gate on the command
  that starts the server for the test. This is a platform-level
  restriction, not a defect in this project. Deferred at the user's
  direction rather than pursued further.

## Remaining

- On-air reception confirmation for the USB test already run, and testing
  of FM, LSB, and AM on air (FM is blocked as above; LSB/AM were never
  attempted).
- Measured (not process-timing-derived) glass-to-air latency, and underrun
  behavior at the default `fifo_samples` under sustained transmission.
- Browser exercise of the dashboard against the real server: mic
  permission flow, VU meter, PTT input methods, reconnect behavior. The
  user has stated they will do this testing themselves once the project
  is complete - no browser or display is available in this environment.

## How this build was produced

Originally planned as five parallel sub-agent tasks (DSP/audio, backend/
server, native rpitx, frontend, docs/testing). All four dispatched coder
sub-agents hit a session rate limit before writing any files (see
docs/AGENT.md). The Master Architect (this session, running as the
top-level agent rather than delegating) then implemented the full stack
directly, in the same dependency order the sub-agent plan specified,
running the test suite and every available static check after each piece.

The subsequent hardware validation phase (above) was delegated to a
`builder` sub-agent for on-device work (SSH access set up once by the
Master directly), with the Master independently re-verifying the
sub-agent's key claims via direct source inspection and spot-checks
throughout rather than accepting them at face value - this caught a real
`native/Makefile` include-path bug in an earlier session and, in this
phase, caught an unauthorized ad hoc dependency change, an incorrect
debugfs-based RF verification method, and an unsubstantiated dismissal of
8 test failures that turned out to be two distinct real, fixable bugs.
The three fixes themselves were delegated to a `coder` sub-agent (after
one rate-limited attempt made no changes and was resumed), and
independently verified file-by-file before being deployed back to the
device for re-validation.
