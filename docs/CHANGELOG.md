# Changelog

## v2.0.1 - 2026-09-02

Three issues found during the first real hardware test of the full stack,
on a Raspberry Pi 2 (Ubuntu 22.04, armv7l, BCM2836). All three are
install/test/documentation issues, not RF or DSP correctness bugs.

### Fixed

- `install.sh`: the aiohttp dependency check only verified that `aiohttp`
  imports, not that it was new enough. Ubuntu 22.04's apt package
  (`python3-aiohttp` = 3.8.1) imports fine but lacks `aiohttp.web.AppKey`
  (added in aiohttp 3.9.0), which `webtx/server.py` uses, so the server
  crashed at startup with `AttributeError: module 'aiohttp.web' has no
  attribute 'AppKey'` even after install.sh reported success. The check now
  verifies `aiohttp.web.AppKey` exists and pip-installs/upgrades to
  `aiohttp>=3.9` when it does not; see `docs/ASSUMPTIONS.md` A-12.
- `tests/test_tx.py`: 6 sink-resolution tests
  (`test_auto_resolution_falls_back_to_sendiq`,
  `test_find_sendiq_prefers_vendored_native_build`,
  `test_find_sendiq_falls_back_to_rpitx_path_when_no_vendored_binary`,
  `test_auto_resolution_raises_when_nothing_found`,
  `test_explicit_webtx_iq_missing_raises`,
  `test_explicit_sendiq_missing_raises`) implicitly assumed
  `native/webtx_iq`/`native/webtx-sendiq` do not exist on the machine
  running the suite - true by accident on every x86 dev machine so far,
  false on the Pi 2, where these ARM-only binaries were built for the first
  time. Fixed by masking `os.path.isfile()` for those global candidate
  paths in the affected tests, so resolution is hermetic regardless of
  ambient binaries on disk.
- `tests/test_dsp.py`: `test_frame_processing_time_budget` asserted every
  mode modulates a 10 ms frame in under 2 ms, a bound calibrated on x86 and
  never validated on target hardware. Measured on the Pi 2: USB averaged
  3.977 ms/frame, LSB averaged 3.956 ms/frame - still well inside the 10 ms
  frame period (~60% margin) but over the old 2 ms bound. The budget is now
  platform-aware: unchanged (tight, 2 ms) on x86, ~6 ms on `arm*`/`aarch64`
  (see `docs/LATENCY.md`).

Found via the first real Raspberry Pi 2 hardware test of the full stack.

## v2.0.0 - 2026-09-02

Full rewrite. Root cause of the reported "tune tone, then delayed audio"
behavior identified and fixed at its source - see `docs/LATENCY.md`.

### Fixed

- Unmodulated carrier radiated at every key-down before audio was ready
  (`native/webtx_iq --ptt-gate`, gating the same GPIO clock-enable call
  librpitx's `iqdmasync` constructor itself uses).
- ~400ms steady-state audio delay, present in every mode (USB/LSB/FM/AM
  share the same sink): librpitx's DMA FIFO pacing (`0.75*fifo/rate`) and
  sendiq's fixed 4000-sample read burst accounted for ~333ms of it; the
  csdr shell pipeline and the old server's polling loop accounted for the
  rest. New defaults (`fifo_samples=2048`, `burst_samples=512`) plus
  removing csdr bring this to an estimated ~90ms; see docs/LATENCY.md for
  the full arithmetic and what is/is not measured on real hardware.
- Audible dropouts from the old buffer-overflow handling
  (`del audio_buffer[:-2048]`, discarding ~64ms of live speech at once),
  replaced by an adaptive jitter buffer with inaudible drift correction
  (`webtx/jitter.py`).
- Transmitter process previously started lazily on the first audio chunk
  (after PTT was already pressed), adding process-startup latency inside
  the PTT path. It now starts immediately on `start_tx`.
- Gain and power changes previously killed and restarted the whole
  pipeline mid-transmission; they no longer touch the sink at all.

### Changed

- Backend: Flask + flask-socketio + Werkzeug dev server -> aiohttp + a raw
  binary WebSocket (`/ws`). See `docs/DECISIONS.md` ADR-002.
- DSP: the four-process `csdr` shell pipeline -> in-process NumPy
  modulator (`webtx/dsp.py`), Hilbert-transformer SSB, phase-accumulator
  FM, clipped-envelope AM. See ADR-001. AM is a new mode.
- Configuration: hardcoded `RPITX_PATH` in `server.py` -> `webtx.json`
  (JSON file, validated, documented in `webtx.example.json`). See ADR-007.
- Frontend: complete redesign as an instrument-panel dashboard (per-digit
  VFO, VU meter, live per-stage latency panel, connection/telemetry
  chips), still zero external dependencies/CDN/build step.
- Transmitter subprocess: `shell=True` and string-built commands ->
  argv lists only, `start_new_session=True` instead of `preexec_fn`. ADR-006.

### Added

- `native/webtx_iq`: a from-scratch low-latency transmitter linking
  librpitx directly, with `-b`/`-F` latency tuning and `--ptt-gate`.
- `vendor/librpitx`: librpitx is now vendored directly in this repository
  (unmodified, GPL-3.0, see `vendor/NOTICE.md` and ADR-009), so building
  `native/webtx_iq` needs no separate clone of any rpitx/librpitx
  repository. Installing full upstream rpitx (README section 5) is now
  optional, only needed for the stock-`sendiq` fallback sink or rpitx's
  other tools.
- `patches/sendiq-lowlatency.patch`: an optional minimal patch giving
  stock `sendiq` the same `-b`/`-F` flags (upstream-identical defaults).
- `vendor/rpitx-src`: rpitx's own outer source tree (`src/`, excluding the
  nested `librpitx` subdirectory already vendored separately above) is now
  also vendored directly in this repository (commit
  `ee7ff57b77962536fda4daa523749c04af6beec7`, GPL-3.0, see
  `vendor/NOTICE.md` and ADR-010). Only `sendiq.cpp` is built
  (`native/webtx-sendiq`, via `make -C native`, linking the same resolved
  librpitx as `webtx_iq`); it carries the same low-latency `-b`/`-F`
  change as `patches/sendiq-lowlatency.patch`, applied directly with a
  prominent top-of-file modification notice. Every other vendored tool
  (SSTV, POCSAG, FT8, DVB, morse, ...) is source-available only, not
  built by this project. Installing full upstream rpitx (README section 5)
  is now optional only for those other, unrelated tools - even the
  stock-`sendiq` fallback sink no longer needs it. `webtx/tx.py` prefers
  this vendored build automatically (see ADR-010); the resolved sink kind
  stays `"sendiq"`.
- `sink.kind: "null"`: a dry-run sink so the entire application and its
  test suite run on any machine with no RF hardware.
- 108 automated tests across DSP, jitter, metrics, config, sink lifecycle,
  and the full WebSocket protocol (see `docs/TEST_PLAN.md`).
- `install.sh`, `systemd/webtx.service`, `tools/gen-cert.sh`.
- Live latency telemetry: `webtx/metrics.py`, pushed to the browser every
  500ms, plus ping/pong RTT.

### Notes

- The original v1 implementation is preserved under `legacy/` for
  reference, not deleted.
- rpitx/librpitx's own DMA FIFO pacing policy (keep the FIFO 3/4 full) was
  deliberately left unpatched - see ADR-003 for why.
