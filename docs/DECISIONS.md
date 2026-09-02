# Architecture Decision Record

Each decision records the option chosen, the alternatives, and the evidence.
Status values: PROPOSED, ACCEPTED, SUPERSEDED.

---

## ADR-001 - Remove the csdr shell pipeline; modulate in-process with NumPy
Status: ACCEPTED

**Context.** v1 built a four-process shell pipeline per keyed transmission
(`csdr convert_i16_f | csdr gain_ff | csdr dsb_fc | csdr bandpass_fir_fft_cc | sendiq`).
`bandpass_fir_fft_cc 0.01` resolves to 401 taps / 1024-point FFT / 624-sample
overlap-add blocks (see `docs/LATENCY.md` 1.4), and each stage carries a libc
stdio buffer plus a 4 KB pipe.

**Decision.** Do the modulation in the server process with NumPy FIR DSP
(`webtx/dsp.py`): a windowed Hilbert transformer for SSB, a phase accumulator for
FM, and an envelope path for AM.

**Alternatives considered.**
* Keep csdr and set `CSDR_FIXED_BUFSIZE` - reduces but does not remove the
  per-stage buffering, keeps four processes on a Pi Zero, and keeps the
  dependency.
* Write a native C DSP stage - faster still, but adds a second build artifact and
  a much larger review surface for a workload NumPy handles in ~1.5 ms per 10 ms
  frame.

**Consequences.** One less system dependency (csdr is not packaged consistently
across Raspberry Pi OS releases), ~30-60 ms less latency, all DSP unit-testable on
x86, and gain changes no longer require restarting anything. NumPy becomes a hard
dependency, which is acceptable: `python3-numpy` is in the Raspberry Pi OS
archive.

---

## ADR-002 - Replace Flask + Flask-SocketIO with aiohttp and a raw WebSocket
Status: ACCEPTED

**Context.** v1 used `flask_socketio` with `async_mode='threading'`, served by the
Werkzeug development server. Werkzeug is explicitly not a production server, and
the Socket.IO framing adds per-message overhead on a path that carries 100
messages per second.

**Decision.** aiohttp with a raw binary WebSocket at `/ws`, a 12-byte header
(`uint32 seq`, `float64 client_ts_ms`) followed by int16 PCM.

**Consequences.** Lower overhead, no CDN dependency in the browser, sequence
numbers and client timestamps available for real latency accounting, and the
whole server is testable with `aiohttp.test_utils`.

---

## ADR-003 - Ship `native/webtx_iq` instead of patching upstream rpitx
Status: ACCEPTED

**Context.** The two dominant latency terms are hardcoded in
`rpitx/src/sendiq.cpp`: `IQBURST 4000` and `FifoSize = IQBURST*4 = 16000`, the
latter combined with librpitx's policy of pacing to keep the DMA FIFO 3/4 full.

**Decision.** Ship a small standalone program in `native/` that links librpitx and
exposes `-b` (burst) and `-F` (FIFO) with low-latency defaults, plus `--ptt-gate`.
Also ship an OPTIONAL minimal patch (`patches/sendiq-lowlatency.patch`) that adds
the same two flags to stock sendiq with upstream-identical defaults, for users who
prefer to patch rather than build a new binary.

**Alternatives considered.**
* Patch librpitx's 3/4 FIFO pacing policy - rejected. It is a shared library used
  by every rpitx tool; changing its pacing would alter the behaviour of unrelated
  programs on the same system, and the same result is achievable by choosing the
  FIFO size, which is already a constructor argument.
* Use stock sendiq unchanged - rejected. It cannot go below ~333 ms.

**Consequences.** Stock rpitx installations are left untouched. The server falls
back to stock `sendiq` automatically when `webtx_iq` is not built, at the stock
latency, and reports which sink is in use.

---

## ADR-004 - Gate the carrier rather than accept the tune tone
Status: ACCEPTED

**Context.** `librpitx/src/iqdmasync.cpp` enables the GPIO clock in the
constructor, before any IQ sample exists; upstream marks this with
`FixMe carrier is already there`. Combined with the 250 ms FIFO fill, the operator
hears an unmodulated carrier at every key-down.

**Decision.** `webtx_iq --ptt-gate` defers enabling the carrier until the first
block whose peak magnitude exceeds a threshold, buffering that block so no audio
is lost.

**Consequences.** No unmodulated carrier at key-down. The first syllable is not
clipped because the triggering block is retained. Deep silence at the start of a
transmission delays carrier onset by at most one block (10.7 ms at the default).

---

## ADR-005 - Adaptive jitter buffer instead of discarding the backlog
Status: ACCEPTED

**Context.** v1 handled backlog with `del audio_buffer[:-2048]`, discarding ~6 KB
(~64 ms) of speech at once. This is audible as a dropout and does not reduce
steady-state latency.

**Decision.** `webtx/jitter.py`: a bounded buffer with a latency target, dropping
samples at the lowest-energy point of a window when the depth exceeds the maximum,
inserting interpolated samples when persistently below target, and padding
underruns with a cosine fade rather than hard zeros.

**Consequences.** Clock drift between the browser's audio clock and the Pi's DMA
clock is corrected continuously and inaudibly instead of catastrophically.

---

## ADR-006 - No `shell=True`, argv lists only
Status: ACCEPTED

**Context.** v1 built the transmitter command by interpolating parameters into a
string and running it with `shell=True`.

**Decision.** All subprocess invocation uses argv lists. All RF parameters are
validated and range-checked before use. `preexec_fn` is replaced with
`start_new_session=True`, since `preexec_fn` is unsafe in a multi-threaded process.

---

## ADR-007 - Configuration file instead of editing source
Status: ACCEPTED

**Context.** v1 required editing `RPITX_PATH = "/home/selim/rpitx"` in `server.py`.

**Decision.** A JSON configuration file resolved from `--config`, `$WEBTX_CONFIG`,
or `./webtx.json`, deep-merged over documented defaults, with a `validate()` that
reports every problem at once. `rf.allowed_ranges` lets an operator constrain the
transmitter to the bands they are licensed for.

---

## ADR-008 - RF output limits are not raised
Status: ACCEPTED

**Decision.** The maximum drive level remains the 0..7 range that stock rpitx
accepts, and `rf.max_power` clamps it further. No change in this project increases
RF output beyond what stock rpitx already permits. The work here is latency and
stability only. Harmonic filtering remains mandatory and is documented in the
README.

---

## ADR-009 - Vendor librpitx instead of requiring a separate rpitx download
Status: ACCEPTED

**Context.** `native/webtx_iq` links against `librpitx`. Requiring users to
separately clone and build upstream `rpitx` (which itself clones `librpitx`
as a nested step inside its own `install.sh`) before they can build the
project's own recommended transmitter adds a dependency on an external
repository staying reachable and unchanged, and is an extra step for
something the project can simply include.

**Decision.** Commit a full, unmodified copy of `librpitx/src` (as of commit
`f01bdb64bcdb6207f448379193bc0a8accb9aa22`) under `vendor/librpitx`, with its
original `LICENSE` and copyright notices intact - see `vendor/NOTICE.md`.
`native/Makefile` now builds this vendored copy automatically whenever no
system-wide librpitx install is found, so `native/webtx_iq` builds from a
single `git clone` of this repository alone.

**Alternatives considered.**
* Git submodule - rejected as insufficiently self-contained: a submodule
  still requires a second fetch (`git submodule update --init`, or
  `--recurse-submodules` at clone time) before it is usable, and an
  unfetched submodule is easy to leave silently empty.
* Require a separate rpitx install (the v2.0.0 approach) - rejected because
  it is exactly the extra step this decision removes.

**Consequences.**
* License: `vendor/librpitx` remains GPL-3.0, exactly as upstream. A build
  of `native/webtx_iq` links against it and is therefore itself subject to
  GPL-3.0 (this project already publishes full corresponding source, so
  this is already satisfied). This project's own code (`webtx/`, install
  scripts, docs) remains MIT-licensed and is unaffected, since it talks to
  `native/webtx_iq` over a subprocess pipe, not a library link. See
  `vendor/NOTICE.md` and the root `LICENSE` file for the exact boundary.
* A system-wide librpitx (from running upstream rpitx's own installer) is
  still preferred over the vendored copy when present, so a user who has
  patched or customized their own system install is not overridden.
* Installing full upstream rpitx (section 5 of the README) is now clearly
  optional - only needed for the stock-`sendiq` fallback sink or rpitx's
  unrelated tools, not for the recommended `native/webtx_iq` path.
* This project can now patch `vendor/librpitx` directly if a librpitx-side
  bug relevant to webtx is found, without waiting on or forking upstream.
  None has been made: `vendor/NOTICE.md` records that the vendored copy is
  currently unmodified, and that record must be kept accurate if this ever
  changes.

---

## ADR-010 - Vendor rpitx's outer source tree (rpitx-src) the same way, and
build its sendiq.cpp with the low-latency patch applied directly
Status: ACCEPTED

**Context.** ADR-009 vendored `librpitx` so `native/webtx_iq` needs no
external download. The stock-`sendiq` fallback sink (`sink.kind: "sendiq"`)
still required a full, separate upstream `rpitx` clone/install, because
`sendiq.cpp` lives in the outer `F5OEO/rpitx` repository (the "app" project
containing `sendiq.cpp` and many small tools), not in `librpitx` itself.
That is a different upstream repository from the one ADR-009 already
vendors, and installing it (README section 5) was, until now, the only way
to get the fallback sink at all.

**Decision.** Vendor a full copy of upstream `rpitx`'s `src/` directory
under `vendor/rpitx-src` (as of commit
`ee7ff57b77962536fda4daa523749c04af6beec7`), EXCLUDING the nested
`src/librpitx` subdirectory (already vendored separately at
`vendor/librpitx` - not duplicated), with the original top-level `LICENCE`
copied to `vendor/rpitx-src/LICENSE` - see `vendor/NOTICE.md` for the full
inventory and license notes. Of everything vendored there, only
`sendiq.cpp` is built by this project: `native/Makefile` gains a
`webtx-sendiq` target that compiles `vendor/rpitx-src/sendiq.cpp` against
the same resolved `$(LIBRPITX_LIB)`/`$(INCLUDE_DIR)` `webtx_iq` already
uses (system install preferred, vendored `librpitx` otherwise), producing
`native/webtx-sendiq` - deliberately not named plain `sendiq`, so it can
never collide with a system-installed rpitx's own `/opt/rpitx/sendiq`.
Every other vendored tool (SSTV, POCSAG, FT8, DVB, morse, pifmrds, ...) is
source-available for reference and future patchability only; none of them
get a build target, and none of their unrelated dependencies (imagemagick,
libfftw3-dev, ft8_lib, csdr, ...) are added anywhere in this project.

`vendor/rpitx-src/sendiq.cpp` itself carries one modification: the same
low-latency change already reviewed and shipped as
`patches/sendiq-lowlatency.patch` (adds `-b`/`-F` flags for read-burst size
and DMA FIFO size, upstream-identical defaults when neither flag is
passed - see `patches/README.md`) is applied directly to the vendored copy,
with a prominent top-of-file notice comment recording the change, per
GPLv3 section 5(a). `patches/sendiq-lowlatency.patch` itself is unchanged
and still shipped, for operators who have a separate real upstream `rpitx`
install and would rather patch that copy in place than switch to
`webtx-sendiq`.

`webtx/tx.py`'s `_find_sendiq()` candidate order changes to prefer this
vendored build: (1) `<repo_root>/native/webtx-sendiq`, (2)
`/usr/local/bin/webtx-sendiq` (the `make install` location), (3)
`<rpitx_path>/sendiq` (a real separate rpitx install, unchanged). The
resolved sink kind stays `"sendiq"` regardless of which of the three was
found - this is a resolution-order change only, not a new `sink.kind`
value, and `_build_argv` for `"sendiq"` is unchanged (both binaries accept
the same stock `sendiq` command-line interface).

**Alternatives considered.**
* Keep requiring a full upstream rpitx install for the fallback sink -
  rejected as exactly the extra step ADR-009 already removed for
  `webtx_iq`; there is no reason the fallback sink should have a stricter
  dependency than the recommended sink.
* Vendor only `sendiq.cpp` and `tune.cpp` (the files this project actually
  might build) instead of the complete `src/` tree - rejected per explicit
  project direction to vendor the complete outer project for completeness
  and future patchability, not just the one file currently built.
* Patch `vendor/rpitx-src/sendiq.cpp` only when a separate rpitx install is
  detected at build time - rejected as unnecessary complexity; vendoring
  make the external dependency disappear entirely, so there is no scenario
  left where an unpatched copy would need to be built by this project.

**Consequences.**
* Installing full upstream rpitx (README section 5) is now needed only for
  rpitx's other tools (SSTV, POCSAG, FT8, DVB, ...), not even for the
  stock-`sendiq` fallback sink anymore.
* License: identical situation to ADR-009's `vendor/librpitx` - see
  `vendor/NOTICE.md`. `vendor/rpitx-src/**` remains GPL-3.0; a build of
  `native/webtx-sendiq` links `vendor/librpitx` and is therefore itself
  subject to GPL-3.0, already satisfied by this repository publishing full
  corresponding source. This project's own code remains MIT-licensed and
  unaffected, since it talks to `native/webtx-sendiq` over a subprocess
  pipe, not a library link.
* This project can now patch any file under `vendor/rpitx-src` directly if
  a bug relevant to webtx is found there, the same way ADR-009 already
  allows for `vendor/librpitx`. `sendiq.cpp` is the only file where this
  has been done so far; `vendor/NOTICE.md` records that every other
  vendored file is unmodified, and that record must be kept accurate if
  this ever changes.
