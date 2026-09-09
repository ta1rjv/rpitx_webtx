# Architecture

Status: IMPLEMENTED (see docs/STATUS.md for what is/is not hardware-verified)

## Signal path

```
microphone --getUserMedia--> AudioWorklet (mic-processor.js)
    -- 10ms Int16 frames + peak/rms --> app.js
    -- binary WS frame (seq, ts, PCM) --> webtx/server.py (asyncio, /ws)
    -- push --> webtx/jitter.py (JitterBuffer, thread-safe)
                                              |
                          webtx-audio worker thread (webtx/server.py)
                                              |
                       pop 10ms --> webtx/dsp.py (Modulator: USB/LSB/FM/AM)
                                              |
                              complex64 IQ --> webtx/tx.py (IQSink)
                                              |
                        interleaved float32 stdin --> native/webtx_iq
                                                        (or stock sendiq, or null)
                                              |
                                    librpitx DMA/GPIO --> RF output --> filter --> antenna/load
```

## Why a dedicated worker thread

The asyncio event loop only ever does network I/O. All DSP and the blocking
write to the transmitter subprocess happen on one dedicated thread
(`WebTXApp._audio_worker` in `webtx/server.py`), paced to real time by its
own clock (`next_deadline += frame_interval`) with the sink's blocking
`write()` as a secondary throttle under genuine overload. This means a
bursty or slow network can never directly stall the real-time audio path -
it can only starve the jitter buffer, which degrades to a cosine-faded
silence (see `webtx/jitter.py`) instead of blocking anything.

## Component map

| File | Responsibility |
|---|---|
| `webtx/dsp.py` | `Modulator`: USB/LSB/FM/AM, AGC, soft limiter. Pure NumPy, stateful across frames. |
| `webtx/jitter.py` | `JitterBuffer`: adaptive latency buffer with click-free drift correction. |
| `webtx/metrics.py` | `LatencyTracker` (per-stage rolling stats) and `RateMeter`. |
| `webtx/config.py` | `Config`: JSON load/merge/validate, `TxConfig` derivation. |
| `webtx/tx.py` | `IQSink`: resolves and manages the transmitter subprocess (webtx_iq/sendiq/null). |
| `webtx/server.py` | aiohttp app, WebSocket protocol, `WebTXApp` state, the audio worker thread. |
| `webtx/__main__.py` | CLI: config resolution, TLS, logging, `web.run_app`. |
| `webtx/templates/index.html`, `webtx/static/*` | The dashboard UI (no build step, no external CDN). |
| `native/webtx_iq.cpp` | Standalone low-latency transmitter linking librpitx directly. |
| `vendor/librpitx` | Vendored, unmodified copy of upstream librpitx (GPL-3.0) - see `vendor/NOTICE.md` and ADR-009. Built automatically by `native/Makefile` when no system install is found. |
| `vendor/rpitx-src` | Vendored copy of upstream rpitx's outer `src/` tree (GPL-3.0, excluding the nested `librpitx` already covered above) - see `vendor/NOTICE.md` and ADR-010. Only `sendiq.cpp` is modified (the same low-latency `-b`/`-F` change as the patch below, applied directly, with a top-of-file notice) and built, as `native/webtx-sendiq`, by `native/Makefile`; every other file is unmodified and source-available only, with no build target. |
| `patches/sendiq-lowlatency.patch` | Optional minimal patch adding `-b`/`-F` to stock `sendiq` (for users who install full upstream rpitx and want its `sendiq` patched too). |

## Why csdr and Socket.IO were removed

See `docs/DECISIONS.md` ADR-001 and ADR-002 for the full reasoning; in
short, both added latency and process/framing overhead that a NumPy
modulator and a raw WebSocket avoid entirely, and removing csdr drops an
external dependency this project no longer needs.

## Concurrency and safety invariants

- Only one client may hold `tx_owner` at a time (enforced in
  `WebTXApp._handle_start_tx`, synchronously, no `await` between the check
  and the assignment - see the code comment for why this is race-free).
- `IQSink.stop()` is idempotent and always fully reaps the child process
  (SIGTERM, then SIGKILL on timeout); it is called from the normal stop
  path, on client disconnect, on a 500ms audio timeout while keyed, on any
  worker-thread exception (a hard watchdog), and from `atexit`/aiohttp's
  `on_cleanup` - no path can leave a carrier keyed with nothing driving it.
- `webtx/tx.py` never uses `shell=True`, string-built commands, or
  `preexec_fn` (unsafe with threads); every subprocess argv is a list
  built from validated, range-checked values.

## Extending this project

- New mode: add it to `webtx/dsp.py`'s `MODES` tuple and `Modulator.process`,
  add tests in `tests/test_dsp.py`, and add a button in
  `webtx/templates/index.html` + `webtx/static/app.js`'s `modeSwitch`
  handler. The server and sink need no changes - mode is a DSP-only concept.
- New sink backend: implement the same argv-list-building pattern in
  `webtx/tx.py`'s `_resolve`/`_build_argv`, add a `sink.kind` value, and
  extend `docs/DECISIONS.md` if the design tradeoff is non-obvious.
