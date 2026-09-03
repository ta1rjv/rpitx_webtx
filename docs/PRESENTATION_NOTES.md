# Presentation Notes - rpitx_webtx (30 slides)

Speaker notes for `presentation.html` and the per-slide files in `slides/`
(`1.html` .. `30.html`). English and ASCII only, per `.claude/CLAUDE.md`.
The slides themselves are in Turkish, at the user's explicit direction.

## How to run the deck

| Action | How |
|---|---|
| Open the full deck | Open `presentation.html` in any browser. Works offline, from `file://`. |
| Next / previous | `ArrowRight` / `Space` / `PageDown`, `ArrowLeft` / `PageUp` |
| First / last | `Home` / `End` |
| Presenter panel | `P` (checklists, demo sequence, failure recovery). `P` or `Esc` closes it. |
| Jump to a slide | Append the fragment: `presentation.html#slide-17` |
| One slide alone | Open `slides/17.html` |
| External player hook | `window.deck.go(n)`, `.next()`, `.prev()`, `.current()`, `.total`, `.autofit()` |

Slide selection is done in CSS with `:target`, so the deck still works with
JavaScript disabled. JavaScript only adds keyboard navigation, the progress
chrome, the presenter panel, two canvas animations, and the autofit safety net.

Regenerate the per-slide files after editing the deck:

```
python3 tools/build-slides.py
```

## Status vocabulary used on the slides

The deck uses one fixed set of chips. Keep the distinction when speaking; it is
the reason an RF audience can trust the rest of the talk.

| Chip | Means |
|---|---|
| `Implemented` | Exists in this repository's source. |
| `Validated - Pi 2` | Actually executed on the real Raspberry Pi 2 on 2026-09-02. |
| `Not verified` / `Not measured` / `Assumed` | Stated as unproven by the project's own docs. |
| `External HW` | Possible only with hardware outside this project. |
| `Future` | An idea. Not implemented, not planned work in the repo. |
| `Upstream` | An rpitx property, not verified here, and not automatically a webtx feature. |

## Timing

Section A (slides 1-15) is the accessible half; budget about 45-60 seconds per
slide. Section B (16-30) is denser; slides 20, 21 and 24 deserve 2 minutes each,
the rest about a minute. Total roughly 35-45 minutes plus the live demo.

Cut list if time runs short: 13 (10 GHz), 14 (roadmap), 17 (repo layout).
Never cut: 3 (the story), 20 (latency), 24 (SSB), 27 (harmonics), 29 (validation).

---

## Slide-by-slide

### 01 - Title
Set the frame: this is a Raspberry Pi, a browser and an RF chain, built by an
amateur radio operator. Do not explain anything technical yet. Say the sentence
the whole talk pays off: "the Pi is not just the computer here, it is the signal
source." Transition: "So what is it, actually?"

### 02 - What is this project?
One sentence, ten seconds: speak into the microphone of whatever device is in
front of you, and a Raspberry Pi on the network turns it into a real USB, LSB,
FM or AM signal in real time. Point at the four-box chain. Stress what is NOT
needed: no extra transmitter, no sound card, no mixer, no SDR hardware.
Transition: "It did not start out working this well."

### 03 - How the story started
Use the git history honestly. The 2026-07-06 prototype was Flask +
Flask-SocketIO with a four-process `csdr` shell pipeline feeding stock `sendiq`.
It worked, and it had one specific, serious problem: at every key-down an
unmodulated carrier went out first, then audio arrived several hundred
milliseconds late, in every mode. The fix was not guessed. `docs/LATENCY.md`
records the diagnosis with upstream file and line references. v2 is commit
`786be45` (2026-09-02); v2.0.1 followed after the first real hardware test found
three more bugs. Transition: "To follow the rest, we need three things: what a
Raspberry Pi is, how it can make RF at all, and what this project actually does."

### 04 - What is a Raspberry Pi?
Assume nothing. Small computer, real Linux, network, USB, CPU, and - the part
that matters - GPIO: physical pins under direct software control. Mention the
validated target: Raspberry Pi 2 Model B Rev 1.1, BCM2836, armv7l, Ubuntu
22.04.5. End on the line on the slide: in this project the Pi is an active part
of the RF chain, not just a computer.

### 05 - How does a computer make RF?
The first "wow" moment. The Pi's clock generator (PLL) can be programmed to a
chosen frequency and routed straight to a GPIO pin. That pin stops being a
digital output and becomes an RF source. Contrast with a conventional
transceiver: no mixer, no PA, no output filter inside the box. The square-wave
spectrum bars are the textbook ideal 1/n odd-harmonic series and are labelled as
such - they are not a measurement. Do NOT mention DMA yet; that is slide 26.
Transition: "So what can we actually do with it?"

### 06 - What can it do?
This is the capability dashboard. Read the left three panels quickly, then slow
down on the two on the right. The point of the slide is the third column: what
the project does NOT have. There is no user authentication, no receive path, no
digital modes, and no gap-free retune while transmitting. TLS exists (a
self-signed certificate) but TLS is not authentication. Saying this out loud
early buys credibility for everything after it.

### 07 - Frequency range
Keep the three layers separate, out loud. (1) What this project configures and
enforces: 5 kHz to 1 500 MHz, default 14.200 MHz USB, enforced twice - in the
Python server and again in `native/webtx_iq`. Out-of-range values are rejected,
not silently clamped, and `rf.allowed_ranges` lets an operator narrow it to the
bands they are licensed for. (2) Upstream rpitx's own declared coverage: not
verified here. (3) What external conversion hardware can reach: slides 12 and 13.
The green marker is the default; the amber marker at 145.5 MHz is the only
frequency this project has ever actually keyed.

### 08 - HF bands
The band list comes straight from `BANDS` in `webtx/server.py`. Note the honest
detail: 60 m is inside the configured range but has no preset in this build.
State plainly that no HF band has a confirmed on-air transmission from this
project, and that there is no digital-mode and no beacon/keyer support.

### 09 - Modulations
Four blocks, beginner language, no equations yet - the maths is slides 22-24.
Each block carries two statuses: implemented in software, and what was actually
tried on air. Only USB was ever keyed, and even that was not confirmed received.
FM was blocked by a platform permission gate; LSB and AM were never attempted.

### 10 - From phone to RF
Walk the real workflow from README section 9. Two things to mention because
people hit them: the certificate warning has to be accepted once, and browsers
will not grant microphone access over plain `http://` to an IP address - a
secure context is mandatory. Also: mic gain and TX power can be changed while
transmitting, but changing frequency while keyed restarts the sink and causes a
brief gap. That is a known, documented limitation.

### 11 - Is it only for repeaters?
Say "No" and then say why: this is one capability - a network-controlled,
modulated RF source - wearing different names. Keep the left column (works
today) and the right column (needs external hardware, or is just an idea)
visibly separate. Close on the red line: capability is not authorisation.

### 12 - QO-100
The disclaimer is the slide. Say it in your own words: this is an example of an
external RF chain architecture, not a claim that the Raspberry Pi generates the
final 2.4 GHz signal. The strongest supporting fact is from the project's own
config: the configured ceiling is 1.5 GHz, so 2.4 GHz is above it by definition.
Then talk through the roles: source, conversion (mixer plus LO), filtering and
power. Mention that a satellite transponder is narrow and LO drift lands
directly on the carrier.

### 13 - 10 GHz
Same structure, harder physics. Direct 10 GHz output does not exist here. The
`20*log10(N)` phase-noise penalty and the "1 ppm is 10 kHz at 10 GHz" figure are
general RF engineering, explicitly labelled as such on the slide - they are not
measurements from this repository. The takeaway: every defect in the source is
carried up the chain and amplified, which is why GHz work starts with filtering
the source.

### 14 - Roadmap
The two left columns come from the repository: implemented, and the project's
own "Remaining" / "NOT VERIFIED" lists. The two right columns are ideas and are
chipped `Future`. Do not blur that boundary while speaking.

### 15 - The big picture
One diagram, then the hinge line: "now let us look inside." Blue boxes are
external hardware. Pause here; this is where the audience is handed from the
accessible half to the technical half.

### 16 - Full system architecture
Three domains: browser JavaScript, Python on the Pi, native C++ and hardware.
Every box maps to a real file. The important architectural point is the middle
column: the asyncio event loop only does network I/O; all DSP and the blocking
write to the transmitter happen on one dedicated `webtx-audio` thread paced by
its own clock. A bursty network can starve the jitter buffer but can never stall
the real-time audio path.

### 17 - Software architecture
Repository layout plus who owns what. Two points worth saying out loud: mode is
purely a DSP-layer concept - because webtx generates IQ itself, the transmitter
process does not know whether it is sending USB or FM, so changing mode never
touches the sink. And the licence boundary: the project's own code is MIT, the
vendored `librpitx` and `rpitx-src` are GPL-3.0, and Python talks to the native
binary over a subprocess pipe rather than a library link.

### 18 - From microphone to WebSocket
The audio is produced in an AudioWorklet, on the audio thread, so a stall on the
main thread cannot disturb timing. 10 ms frames, 480 samples at 48 kHz, 100
frames per second. Show the 12-byte header byte by byte: `uint32 seq` then
`float64 client_ts_ms`, then int16 PCM - `setUint32`/`setFloat64` on one side,
`struct.Struct("<Id")` on the other. No resampling happens anywhere in the
chain.

### 19 - Jitter buffer
The framing sentence: the network is not uniform, the DMA clock is - it wants
exactly 480 samples every 10 ms. Then the three real mechanisms: drop the
lowest-energy 5 ms window on overrun, insert one interpolated sample per ~20 ms
on persistent underfill, and fade out with a cosine tail on underrun rather than
jumping to zero. Contrast with v1's `del audio_buffer[:-2048]`, which threw away
about 64 ms of live speech at once and did not reduce steady-state latency at
all.

### 20 - Where does the latency come from?
The centrepiece of the engineering story. Both ladders are drawn to the same
250 ms scale so the contrast is visual, not rhetorical. Old: about 390-450 ms,
dominated by librpitx's DMA FIFO (250.0 ms) and `sendiq`'s 4000-sample read
burst (83.3 ms). New: about 88-92 ms. Be explicit about evidence levels. The
3.98 ms bar is the only measured item - measured on the real Pi 2 - and it is
higher than the 1.5 ms x86 estimate the docs originally used, which makes the
88-92 ms total slightly optimistic. Glass-to-air latency has never been measured
on air. Close with the residual limits that cannot be removed.

### 21 - DSP pipeline
The exact order in `Modulator.process()`, with real parameters. Worth saying:
filter state carries across frames, so frame-by-frame processing gives the same
result as one-shot processing after the transient - asserted by a unit test
(F-05). The time budget is measured: 3.977 ms per 10 ms frame for USB on the
Pi 2, about 60 percent headroom.

### 22 - How AM is made
Introduce the equation, then map it onto the code line by line. The key honest
detail: the code produces only the complex baseband envelope. Q is zero, and the
`cos(2*pi*f_c*t)` term is supplied by the PLL/GPIO hardware, not by Python.
Because the envelope is clipped to [0, 1] before it ever reaches the carrier, it
cannot go negative, so a phase reversal - classic overmodulation splatter - is
structurally impossible here. F-04 asserts it.

### 23 - How FM is made
Instantaneous frequency, then phase accumulation, then `cos + j*sin`. Two things
to stress: the phase accumulator is carried between frames (otherwise there is a
click every 10 ms), and it is float64 - never float32 for accumulated phase,
which is one of this project's explicit RF rules. Constant envelope means no
limiter is needed. The 2500 Hz deviation is an assumption (A-07), never checked
against a deviation meter; say so.

### 24 - How USB and LSB are made
The flagship technical slide. Hilbert transform gives a -90 degree shift at
every frequency; the analytic signal `m(t) + j*m_hat(t)` has energy on one side
of zero only; adding I and jQ makes one sideband constructive and the other
destructive. The difference between USB and LSB in the code is literally one
minus sign. Mention the matched 64-sample delay on the I path: the 129-tap
Type III FIR has exactly that group delay, and if the two paths are not aligned
the cancellation degrades. The >= 40 dB figure is measured by FFT on the
baseband IQ in `tests/test_dsp.py`. Say clearly that this is a software
measurement; there is no on-air sideband suppression measurement in this
project.

### 25 - What is IQ?
Keep it intuitive. I and Q describe amplitude and phase at the same time; that
is complex baseband, the carrier taken out of the equation. Use the rotating
phasor to show what each mode looks like: AM changes radius only, FM keeps the
radius constant and changes the rotation rate, USB and LSB rotate in opposite
directions. Note the animation is conceptual, not a live signal.

### 26 - From IQ to GPIO
The native path with real file names. `IQSink.write()` interleaves I and Q as
little-endian float32 - the same format as `sendiq -t float` - and writes it to
the child's stdin as an argv-list subprocess, never through a shell. `webtx_iq`
reads bursts of 512 samples and hands them to `iqdmasync`, which paces the DMA
FIFO. Explain the pipe shrink: Linux's default 64 KB pipe buffer would let the
writer queue about 170 ms of audio before it ever felt back-pressure, hiding
that latency, so the pipe is shrunk on both sides. Telemetry flows back as
`STAT depth= under=` on stderr and ends up in the browser.

### 27 - The GPIO RF reality
The RF engineering slide, and the one to slow down on. A GPIO-generated waveform
is not a spectrally clean transmitter output. Harmonics are inherent to the
method, not a software bug: `docs/ASSUMPTIONS.md` A-10 records this as not
software-controllable, and ADR-008 records that this project does not raise
output beyond what stock rpitx already permits. The bars are deliberately
unscaled: no measured harmonic-suppression figure exists in this repository, so
none is quoted. Slide 5's ideal square wave had odd harmonics only; a real
output whose duty cycle is not exactly 50 percent shows even ones too. End on
the image and the line: the filter is not optional, and bring-up is always into
a dummy load.

### 28 - PTT and fail-safe
Walk the normal state machine, then the failure paths. Every one of them ends in
TX OFF: disconnect, a 500 ms audio timeout while keyed, a worker-thread
exception, server shutdown, process exit via atexit, a sink write failure.
`IQSink.stop()` is idempotent and always reaps the child - stdin close, SIGTERM,
2 s, SIGKILL - so no path can leave a carrier on air with nothing driving it.
The single-owner check is race-free because there is no `await` between the
check and the assignment. Parameters are rejected, not silently clamped. Repeat:
only mechanisms that exist in the code are on this slide, and authentication is
not one of them.

### 29 - Test and RF validation
Separate software validation from hardware validation, out loud. 110 automated
tests pass on x86 with the null sink and on the real Pi 2. On hardware: the
native binaries built and linked with zero external download, `install.sh` ran
start to finish, systemd installed and started, a real WebSocket client drove
the live server, and one real keydown ran - 145.5 MHz, USB, `--ptt-gate`, about
9 seconds of a 440 Hz tone, zero errors. That proves the software path executes;
it does not prove RF was received. Then read the not-verified list without
softening it. Finish with the measurement chain and what should be measured.

### 30 - Live demo
Stop presenting and start operating. The chain diagram matches the physical
setup on the table. Follow the twelve-step sequence; the presenter panel (`P`)
has the same list plus failure recovery.

---

## Claim -> source traceability

Every factual claim on a slide maps to one of these. Anything not listed here
does not appear on a slide as fact.

| Claim on a slide | Source in this repository |
|---|---|
| Modes are USB, LSB, FM, AM only | `webtx/dsp.py` `MODES` |
| Frequency range 5 kHz .. 1 500 MHz, default 14.200 MHz USB | `webtx.example.json` `rf.*`; range re-checked in `native/webtx_iq.cpp` |
| 12 band presets, 160m .. 70cm; no 60m preset | `webtx/server.py` `BANDS` |
| Out-of-range values rejected, not clamped | `webtx/server.py` `_validate_params`; `docs/REQUIREMENTS.md` C-02 |
| SSB: 129-tap Blackman Hilbert, 64-sample group delay (1.33 ms), 300-2700 Hz | `webtx/dsp.py` `_design_hilbert`, `_design_bandpass` |
| Opposite-sideband suppression >= 40 dB (baseband IQ, FFT) | `tests/test_dsp.py`; `docs/REQUIREMENTS.md` F-02 |
| FM: float64 phase accumulator, constant envelope | `webtx/dsp.py`; F-03 |
| FM deviation 2500 Hz is an assumption, not measured | `docs/ASSUMPTIONS.md` A-07 |
| AM: carrier 0.5, index 0.85, envelope clipped to [0,1], `abs(IQ) <= 1` | `webtx/dsp.py`; F-04 |
| Soft limiter (tanh above 0.98) applies to USB/LSB only | `webtx/dsp.py` `_soft_limit` and its comment |
| AGC target 0.35, attack 5 ms, release 300 ms, gain clamp 0.05-20 | `webtx/dsp.py` `_apply_agc`; `webtx.example.json` |
| 10 ms frames, 480 samples at 48 kHz, 100 frames/s | `webtx/static/mic-processor.js`; `webtx/server.py` |
| 12-byte header: uint32 seq + float64 client_ts_ms, then int16 PCM | `webtx/static/app.js`; `webtx/server.py` `_HEADER`; ADR-002 |
| No resampling anywhere | `docs/ASSUMPTIONS.md` A-01 |
| Jitter buffer target 30 ms, max 120 ms; three correction mechanisms | `webtx/jitter.py`; ADR-005 |
| v1 dropped ~64 ms of speech per overflow | `docs/LATENCY.md` 1.5; `legacy/server.py` |
| Old latency ~390-450 ms, per-stage breakdown | `docs/LATENCY.md` 1.6 |
| New latency ~88-92 ms, derived not measured on air | `docs/LATENCY.md` 2; `docs/REQUIREMENTS.md` L-01 |
| Modulator measured 3.977 ms (USB) / 3.956 ms (LSB) per frame on a Pi 2 | `docs/LATENCY.md` 2.1 |
| ~50 ms reachable with jitter_target 10 ms and fifo 1024 on a wired Pi 3/4 | `docs/LATENCY.md` 2 |
| Carrier enabled in the `iqdmasync` constructor ("FixMe carrier is already there") | `docs/ASSUMPTIONS.md` A-03; `vendor/librpitx/iqdmasync.cpp` |
| DMA FIFO paced to 3/4 full: latency = 0.75 * fifo / rate | `docs/ASSUMPTIONS.md` A-02 |
| Stock sendiq: IQBURST 4000, FifoSize 16000 -> 83.3 ms + 250.0 ms | `docs/LATENCY.md` 1.3 |
| webtx_iq defaults -F 2048 (32.0 ms), -b 512 (10.7 ms), `--ptt-gate` | `native/webtx_iq.cpp`; `native/README.md` |
| librpitx's 3/4 pacing policy deliberately left unpatched | `docs/DECISIONS.md` ADR-003 |
| Pipe shrunk on both sides; default 64 KB pipe hides ~170 ms | `webtx/tx.py` `_shrink_pipe_buffer`; `native/webtx_iq.cpp` |
| Fail-safe paths, idempotent stop, SIGTERM then SIGKILL | `webtx/server.py`; `webtx/tx.py`; S-01, S-02 |
| Single TX owner, race-free | `webtx/server.py` `_handle_start_tx`; S-04 |
| 500 ms audio timeout while keyed | `webtx/server.py` `_AUDIO_TIMEOUT_S` |
| No `shell=True`, argv lists only, `start_new_session=True` | `webtx/tx.py`; ADR-006; C-01 |
| Output power not raised beyond stock rpitx | `docs/DECISIONS.md` ADR-008; C-04 |
| Harmonic filtering is mandatory and not software-controllable | `README.md` 3, 15; `docs/ASSUMPTIONS.md` A-10 |
| 110 automated tests pass on x86 and on a real Pi 2 | `docs/TEST_PLAN.md`; `docs/STATUS.md` |
| Hardware validation on Pi 2 Model B Rev 1.1, Ubuntu 22.04.5, armv7l, 2026-09-02 | `docs/STATUS.md`; `docs/PROGRESS.md` |
| One real keydown: 145.5 MHz USB, `--ptt-gate`, ~9 s, zero errors, reception unconfirmed | `docs/STATUS.md` RF keydown rows |
| Live retune while keyed restarts the sink | `webtx/tx.py` `set_frequency()`; `README.md` 14 |
| Project code MIT, vendored librpitx/rpitx-src GPL-3.0 | `LICENSE`; `vendor/NOTICE.md`; ADR-009, ADR-010 |
| v1 was Flask + Flask-SocketIO + csdr + sendiq | `legacy/server.py`; `docs/CHANGELOG.md` v2.0.0 |
| v2 is commit 786be45, 2026-09-02; v2.0.1 followed hardware testing | `git log`; `docs/CHANGELOG.md` |

## Claims deliberately NOT made anywhere in the deck

* That the Raspberry Pi directly transmits QO-100 at 2.4 GHz. Slide 12 states the
  opposite explicitly.
* That 10 GHz operation is built in. Slide 13 states the opposite explicitly.
* Any measured RF performance figure: harmonic suppression, on-air sideband
  suppression, output power, occupied bandwidth, frequency accuracy. None exist
  in this repository.
* Any measured glass-to-air latency. The 88-92 ms figure is derived.
* User authentication, authorisation, or encryption beyond a self-signed TLS
  certificate. None exist.
* Digital modes, a beacon/keyer mode, or a receive path. None exist.
* That an upstream rpitx feature is automatically a rpitx_webtx feature.

## Still requiring physical RF validation

Everything in the `NOT VERIFIED` section of `docs/STATUS.md`, which slide 29
reproduces: on-air reception of the 145.5 MHz USB test, FM/LSB/AM on air,
instrument confirmation that `--ptt-gate` really suppresses the carrier, on-air
sideband-suppression measurement, measured glass-to-air latency, underrun
behaviour under sustained transmission, and the browser UI on a real device.

## Non-ASCII note

`presentation.html` and `slides/*.html` are Turkish and therefore contain
non-ASCII characters, by explicit user direction. This file, the build script,
and every other document in `docs/` remain English and ASCII-only.
