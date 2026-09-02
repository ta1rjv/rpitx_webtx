# webtx

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

A browser-controlled, low-latency SDR transmitter control panel for
Raspberry Pi, built on the [rpitx](https://github.com/F5OEO/rpitx) engine
(librpitx). Speak into any microphone connected to the computer or phone
in front of you and transmit it in real time as USB, LSB, FM, or AM, tuned
and keyed from a web dashboard.

**Clone this one repository and you have everything you need to build the
transmitter** - librpitx is vendored in `vendor/librpitx`, and rpitx's own
`sendiq.cpp` (with the same low-latency patch applied directly) is vendored
in `vendor/rpitx-src` (see [vendor/NOTICE.md](vendor/NOTICE.md)), so both
`native/webtx_iq` and its stock-compatible fallback, `native/webtx-sendiq`,
build with no separate download from the upstream rpitx project. A full
upstream rpitx install is only needed for its other tools (SSTV, POCSAG,
FT8, ...), unrelated to webtx - see [section 5](#5-installing-rpitx).

This is a from-scratch rewrite (v2) of the original csdr/Flask-based
prototype. The rewrite exists because the original had a specific, serious
problem: **at every key-down, an unmodulated carrier went out first, then
audio arrived several hundred milliseconds late.** That problem is fixed at
its root here - see [docs/LATENCY.md](docs/LATENCY.md) for the full,
source-cited diagnosis, and "Known issues" below for what remains.

## Table of contents

1. [Description](#1-description)
2. [Features](#2-features)
3. [Requirements](#3-requirements)
4. [Raspberry Pi setup](#4-raspberry-pi-setup)
5. [Installing rpitx](#5-installing-rpitx)
6. [Installing webtx](#6-installing-webtx)
7. [One-command install](#7-one-command-install)
8. [Running](#8-running)
9. [Usage](#9-usage)
10. [Configuration](#10-configuration)
11. [Modes: USB / LSB / FM / AM](#11-modes-usb--lsb--fm--am)
12. [Troubleshooting](#12-troubleshooting)
13. [Latency troubleshooting](#13-latency-troubleshooting)
14. [Known issues](#14-known-issues)
15. [Safe and lawful use](#15-safe-and-lawful-use)
16. [Development and contributing](#16-development-and-contributing)

---

## 1. Description

webtx turns a Raspberry Pi with rpitx into a remote-controlled voice
transmitter: a phone or laptop on the same network opens a web page,
grants microphone access, tunes a frequency, picks a mode, and holds a
PTT button. Audio is captured in the browser, streamed over a WebSocket,
modulated into IQ samples on the Pi, and handed to rpitx's DMA-based RF
output. A live telemetry panel shows exactly where every millisecond of
delay is coming from.

It is intended for **authorized, licensed, test, and educational use**
(see [section 15](#15-safe-and-lawful-use)).

## 2. Features

- USB, LSB, FM, and AM voice transmission from any browser microphone.
- Sub-100ms glass-to-air latency by default (down from ~400ms in v1) -
  see [docs/LATENCY.md](docs/LATENCY.md) for the measured breakdown.
- No audible "tune tone" at key-down: the carrier is held off until real
  audio is ready (`native/webtx_iq --ptt-gate`).
- Adaptive jitter buffer that corrects clock drift inaudibly instead of
  dropping chunks of live speech.
- Live per-stage latency telemetry (network, jitter buffer, DSP, RF sink)
  pushed to the browser twice a second.
- A modern instrument-panel dashboard: per-digit VFO tuning, VU meter,
  connection/latency chips, PTT with mouse/touch/spacebar and a lock mode.
- Runs entirely offline in the browser: no external CDN, no build step.
- A `null` sink lets the whole stack run and be tested on a non-Pi machine
  with no RF hardware at all.
- Config-file driven (no more editing Python source to set a path).
- Automatic reconnect with backoff; a stuck client can never leave the
  transmitter keyed (disconnect, timeout, and crash all force TX off).
- Self-contained: librpitx is vendored, so building the recommended
  transmitter needs no separate clone of any other repository.

## 3. Requirements

- A Raspberry Pi (Zero through 4; see rpitx's own compatibility notes) with
  a GPIO pin wired through **a low-pass or band-pass filter** to whatever
  antenna or dummy load you use for testing. rpitx transmits a square wave
  and radiates strong harmonics without one - a filter is not optional.
- Raspberry Pi OS (Debian-based), with sudo/root access.
- A browser with Web Audio + WebSocket support (any current Chrome,
  Firefox, Edge, or Safari) on the controlling device.
- Python 3.9+, `numpy`, `aiohttp` (installed by `install.sh`).
- A C++11 toolchain and `libraspberrypi-dev` to build `native/webtx_iq`
  (installed by `install.sh`) - **no separate rpitx download needed**,
  since librpitx is vendored in this repository (`vendor/librpitx`).
- [rpitx](https://github.com/F5OEO/rpitx) itself is **optional** - only
  needed for its other tools (SSTV, POCSAG, FT8, ...), unrelated to webtx;
  see [section 5](#5-installing-rpitx). Even the stock-`sendiq` fallback
  sink no longer needs it: `native/webtx-sendiq` builds from this
  repository alone (`vendor/rpitx-src`, installed by the same
  `make -C native` as `native/webtx_iq`).

## 4. Raspberry Pi setup

1. Flash Raspberry Pi OS (32- or 64-bit) and boot the Pi with network access.
2. `sudo apt-get update && sudo apt-get upgrade`.
3. Connect the RF output GPIO (see rpitx's documentation for the pin - GPIO4
   by default) through your low-pass/band-pass filter to a dummy load for
   initial bring-up. **Do not connect an antenna until you have verified
   correct operation on a dummy load and understand your local licensing.**
4. Clone this repository somewhere on the Pi, e.g. `/opt/webtx`:
   ```
   sudo git clone https://github.com/ta1rjv/rpitx_webtx.git /opt/webtx
   cd /opt/webtx
   ```

## 5. Installing rpitx

**This section is optional.** `native/webtx_iq` (the recommended,
low-latency transmitter) and `native/webtx-sendiq` (a stock-`sendiq`-
compatible fallback - see [section 6](#6-installing-webtx)) both build
against source already vendored in this repository (`vendor/librpitx`,
`vendor/rpitx-src`) and need nothing from this section. Install full
upstream rpitx only if you specifically want its other tools (SSTV,
POCSAG, FT8, DVB, ...), unrelated to webtx.

`install.sh` (see [section 7](#7-one-command-install)) asks before doing
this, or by hand:

```
git clone https://github.com/F5OEO/rpitx.git /opt/rpitx
cd /opt/rpitx
sudo ./install.sh
```

rpitx's installer will ask whether to set `gpu_freq=250` in
`/boot/config.txt` (or `/boot/firmware/config.txt` on newer Raspberry Pi
OS) for clock stability - review that prompt yourself; it edits a boot file.

## 6. Installing webtx

Either run [`install.sh`](#7-one-command-install), or by hand:

```
sudo apt-get install -y python3 python3-pip build-essential git openssl \
  libraspberrypi-dev python3-numpy python3-aiohttp python3-pytest
```

If `python3-numpy` or `python3-aiohttp` are not available on your OS
release, install them with pip instead:
`pip3 install --break-system-packages numpy aiohttp pytest`.

Build the low-latency transmitter and its stock-compatible fallback
(recommended - see [docs/LATENCY.md](docs/LATENCY.md) for why it matters).
This builds both `webtx_iq` and `webtx-sendiq` (see
[native/README.md](native/README.md)) against the vendored librpitx
automatically; it does **not** need section 5 at all, unless you already
have a system-wide librpitx install you would rather use instead (which
takes priority if `make` finds one):

```
make -C native
sudo make -C native install
```

Generate a TLS certificate (required for microphone access - see
[section 12](#12-troubleshooting)):

```
tools/gen-cert.sh certs
```

Create your configuration:

```
cp webtx.example.json webtx.json
# edit webtx.json: rpitx_path, rf.max_power, rf.allowed_ranges, etc.
```

## 7. One-command install

```
sudo ./install.sh
```

This runs every step in sections 5-6 for you, asks before cloning/running
rpitx's own installer (which touches `/boot/config.txt`) and before
installing the systemd service, and never overwrites an existing
`webtx.json` or certificate. See `./install.sh --help` for flags
(`--skip-rpitx`, `--skip-native`, `--skip-cert`, `--yes`,
`--install-service`, `--rpitx-path=`).

## 8. Running

Manually:

```
sudo python3 -m webtx --config webtx.json
```

(root is required for GPIO/DMA access, unless `sink.kind` is `"null"`).
Then open `https://<pi-ip-address>:5000` from a browser on the same
network and accept the self-signed certificate warning once.

As a systemd service (auto-restart, starts on boot):

```
sudo ./install.sh --skip-rpitx --skip-native --skip-cert --install-service
# or by hand:
sed "s#__WEBTX_DIR__#$(pwd)#g" systemd/webtx.service | sudo tee /etc/systemd/system/webtx.service
sudo systemctl daemon-reload
sudo systemctl enable --now webtx.service
sudo systemctl status webtx
journalctl -u webtx -f
```

Useful `python3 -m webtx` flags: `--host`, `--port`, `--no-tls` (loopback
testing only), `--sink {auto,webtx_iq,sendiq,null}`, `--dry-run` (force
the null sink, no RF output at all), `--log-level`, `--print-config`.

## 9. Usage

1. Open the page; the connection chip in the top bar turns green ("Online")
   once the WebSocket handshake completes.
2. Click **Enable microphone** and grant the browser permission prompt.
3. Set the frequency: click the upper half of a VFO digit to increase it,
   the lower half to decrease it, or scroll over it; or pick a band from
   the dropdown. VFO A/B and the swap button hold two frequencies at once.
4. Pick a mode (USB/LSB/FM/AM).
5. Adjust mic gain and TX power if needed - these never interrupt an
   active transmission.
6. Hold **PTT** (mouse, touch, or the Space bar) to transmit, or check
   **Lock TX** to make PTT a press-to-toggle switch instead of hold.
7. Watch the latency panel and telemetry strip while transmitting - "Total"
   is the number that matters; the four bars above it show which stage is
   contributing the most.

## 10. Configuration

All settings live in a JSON file (default `webtx.json`, resolved from
`--config`, then `$WEBTX_CONFIG`, then `./webtx.json`). `webtx.example.json`
documents every default. Key fields:

| Field | Meaning |
|---|---|
| `tls.enabled`, `tls.cert`, `tls.key` | HTTPS (required for microphone access on anything but localhost) |
| `rpitx_path` | where rpitx is installed, used to locate stock `sendiq` |
| `sink.kind` | `"auto"` (prefer `webtx_iq`, else `sendiq`, else error), `"webtx_iq"`, `"sendiq"`, or `"null"` (no RF, for testing) |
| `sink.fifo_samples`, `sink.burst_samples` | latency vs. underrun-risk tuning - see [docs/LATENCY.md](docs/LATENCY.md) |
| `audio.sample_rate`, `audio.jitter_target_ms`, `audio.jitter_max_ms` | the audio pipeline's timing |
| `rf.min_freq_hz`, `rf.max_freq_hz`, `rf.max_power`, `rf.allowed_ranges` | hard limits enforced server-side, independent of what the browser sends |
| `dsp.*` | SSB passband, FM deviation, AM modulation index/carrier level, AGC, limiter |
| `log.level`, `log.file` | logging |

Run `python3 -m webtx --print-config` to see the fully-merged, validated
configuration your server will actually use.

## 11. Modes: USB / LSB / FM / AM

- **USB / LSB**: generated with a windowed-sinc Hilbert transformer
  (analytic-signal / phasing method), giving >=40 dB opposite-sideband
  suppression (verified in `tests/test_dsp.py`). Audio is band-limited to
  `dsp.ssb_low_hz`-`dsp.ssb_high_hz` (300-2700 Hz by default) before the
  Hilbert pair.
- **FM**: a float64 phase accumulator gives a constant-envelope signal;
  deviation is `dsp.fm_deviation_hz` (2500 Hz by default, narrowband).
- **AM**: `carrier_level + modulation_index * audio`, clipped to a valid
  envelope, so it can never overmodulate past 100%.

Mic gain includes an optional peak-tracking AGC (`dsp.agc_*`), and a
soft-knee limiter protects USB/LSB from clipping without the phase
discontinuities a hard clip would cause (FM and AM do not need it - see
the comment in `webtx/dsp.py`).

## 12. Troubleshooting

- **Microphone permission fails / button does nothing**: the browser
  requires a secure context. Use `https://` (accept the self-signed
  certificate warning) or `http://localhost` - plain `http://<ip>` will
  not be granted microphone access by any current browser.
- **"webtx must run as root"**: GPIO/DMA needs `/dev/mem`, so the process
  (or the systemd service) must run as root. Use `sink.kind: "null"` only
  if you are testing on a machine with no RF hardware.
- **Certificate warning every time / wrong IP after DHCP renewal**: rerun
  `tools/gen-cert.sh certs <new-ip>` after deleting the old `certs/` dir,
  or give the Pi a static IP/hostname.
- **"sink.kind is 'auto' but neither native/webtx_iq nor .../sendiq could
  be found"**: build `native/webtx_iq` (section 6) or install rpitx, or
  set `sink.kind: "null"` to confirm the rest of the app works first.
- **"Another operator is currently transmitting"**: only one browser can
  hold the transmitter at a time by design - see
  [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) S-04.
- **No sound reaches the receiver but nothing errors**: check the
  telemetry strip's "Sink" and "Underruns" fields; confirm the antenna/
  dummy load and filter wiring; confirm `rf.max_power`/TX power slider
  are not near zero.
- **High CPU / choppy audio on a Pi Zero**: raise `sink.fifo_samples`
  (see [docs/LATENCY.md](docs/LATENCY.md) for the tradeoff) and prefer a
  wired network connection over Wi-Fi.

## 13. Latency troubleshooting

The latency panel shows four stages plus a total:

| Stage | What it means | If it is high |
|---|---|---|
| Network | Arrival jitter relative to the best-observed frame (not absolute delay - see below) | Use Ethernet or a USB network adapter instead of Wi-Fi; check for other traffic saturating the link |
| Jitter buffer | Current buffer depth | Lower `audio.jitter_target_ms`, at the cost of more underruns on a loaded network |
| DSP | Modulator time per 10ms frame | Should be ~1-2 ms; if far higher, the Pi is CPU-starved (check other processes, `telCpu`) |
| RF sink FIFO | DMA FIFO occupancy (or an estimate, if the sink does not report it) | Lower `sink.fifo_samples` - see the table in `native/README.md` for per-model recommendations |

The Network figure is **not** an absolute one-way delay: the browser and
the Pi do not share a clock. It is reported relative to the minimum
offset observed over a rolling window (the best-observed path), which is
a legitimate jitter indicator but not a true latency measurement.
Absolute round-trip time is shown separately as "RTT" (ping/pong).

For the full root-cause analysis of the pre-rewrite ~400ms delay and tune
tone, see [docs/LATENCY.md](docs/LATENCY.md).

## 14. Known issues

- Live frequency retune while keyed always restarts the RF sink (a brief
  transmit gap, logged to the UI) - neither `webtx_iq` nor stock `sendiq`
  are driven through a retune IPC channel in this version. Changing mode,
  mic gain, or TX power never restarts anything.
- `native/webtx_iq` and the `--ptt-gate` carrier behaviour have been
  verified by source analysis and syntax-checked against the librpitx
  headers, but **not run on real Raspberry Pi hardware** by this project's
  automated tests - see `docs/STATUS.md` for exactly what is and is not
  verified.
- FIFO underrun recovery is librpitx's own behaviour (repeats the last
  programmed sample); it is not a crash, but very small `sink.fifo_samples`
  values on an overloaded Pi Zero can produce audible artifacts.
- No resampling is performed anywhere in the pipeline; the browser's
  AudioContext is asked for `audio.sample_rate` (48000 by default) and the
  UI warns if the browser silently uses a different rate.

## 15. Safe and lawful use

![Filtering matters](img/bpf-warning.png)

This software is for **research, development, testing, and education**.
Before transmitting anything, whether from this dashboard or any RF tool:

- **Use a dummy load, not an antenna**, for all bring-up and testing.
- Keep output power low and use the mandatory harmonic filter - rpitx
  drives a GPIO pin with a square wave; without filtering, it radiates
  significant harmonic energy far outside your intended frequency.
- Hold an appropriate license for any frequency and power level you
  transmit on, and comply with your country's spectrum regulations.
- This project does not raise rpitx's output power or bypass any of its
  limits - see [docs/DECISIONS.md](docs/DECISIONS.md) ADR-008. It is a
  latency and stability rewrite, not an RF-output modification.
- **You are solely responsible**, legally and otherwise, for every
  transmission you make with this tool. The authors accept no liability
  for misuse or unlicensed operation.

## 16. Development and contributing

```
python3 -m pytest tests/ -q          # full suite, runs on any machine (null sink)
python3 -m webtx --dry-run           # run the server with no RF hardware
```

Project documentation (architecture, decisions, assumptions, requirements,
test plan, status) lives in [`docs/`](docs/) - read
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) first if you are changing the
audio pipeline, and [docs/DECISIONS.md](docs/DECISIONS.md) before
reversing any of the choices recorded there. `native/README.md` and
`patches/README.md` cover the C++ transmitter and the optional stock-rpitx
patch respectively.

Contributions are welcome: keep changes scoped, add tests for behavior
changes (especially anything touching `webtx/dsp.py`, `webtx/jitter.py`,
or `webtx/tx.py`), and update the relevant `docs/` file alongside any
change that affects requirements, architecture, or known limitations.
