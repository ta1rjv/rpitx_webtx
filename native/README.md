# native/webtx_iq

A standalone low-latency IQ transmitter for Raspberry Pi, built against
`librpitx`. This is what actually gets rid of the "tune tone, then delayed
audio" problem; everything else in this project (the DSP, the jitter buffer,
the server) reduces latency further, but the two largest terms live here.

**No separate download needed**: `librpitx` is vendored in `../vendor/librpitx`
(see `../vendor/NOTICE.md`), and `make` here builds it automatically if no
system-wide install is found. A system install (from running upstream
rpitx's own `install.sh`) is still preferred when present - see
`../docs/DECISIONS.md` ADR-009 for why, and for the license implications of
linking a GPL-3.0 library.

## Why this exists instead of stock `sendiq`

Full arithmetic and source citations are in `../docs/LATENCY.md`. Summary:

| Parameter | Stock `sendiq` | `webtx_iq` default | Effect |
|---|---:|---:|---|
| DMA FIFO size (`-F` / `fifo_samples`) | 16000 | 2048 | steady-state latency `0.75*F/rate`: 250 ms -> 32 ms at 48 kHz |
| Read burst (`-b` / `burst_samples`) | 4000 | 512 | read granularity: 83.3 ms -> 10.7 ms at 48 kHz |
| Carrier at start | enabled in the `iqdmasync` constructor, before any sample exists | held off by `--ptt-gate` until the first non-silent block | removes the unmodulated "tune tone" at key-down |

librpitx's `iqdmasync::SetIQSamples()` deliberately paces output to keep the
DMA FIFO 3/4 full (see `librpitx/src/iqdmasync.cpp`). That policy is not
changed here - only the FIFO size passed to the constructor - because it is
shared code used by every rpitx tool (see `../docs/DECISIONS.md` ADR-003).

## The tune-tone fix, precisely

`iqdmasync`'s constructor calls `clkgpio::enableclk(4)`, which sets GPIO4's
function-select to route the PLL clock output to the physical pin - i.e. it
turns the carrier on - before the caller has written a single IQ sample.
Upstream's own comment at that line reads `FixMe carrier is already there`.

`--ptt-gate` calls `disableclk(4)` (function-select back to plain input, so
nothing reaches the pin regardless of what the PLL is doing) immediately after
construction, and only calls `enableclk(4)` once a read block's peak magnitude
exceeds a small threshold (1e-4). The carrier is disabled again on shutdown.
This uses the exact same primitive the constructor itself uses, so it costs a
register write and a 100 us sleep, not a PLL/DMA teardown and rebuild.

## FIFO size vs. underrun risk

A smaller FIFO means lower latency but less time for the CPU to refill it
before it runs dry (an underrun does not crash anything - librpitx keeps
outputting the last programmed sample - but it does mean stale/repeated audio
briefly on air). Recommended starting points:

| Board | `fifo_samples` | Steady-state latency @ 48 kHz | Notes |
|---|---:|---:|---|
| Pi Zero / Zero W | 4096 | 64 ms | single core, budget accordingly |
| Pi 3B / 3B+ | 2048 (default) | 32 ms | |
| Pi 4 | 1024 | 16 ms | plenty of headroom |

Watch the `under=` counter from `-v` (surfaced in the UI's sink/underrun
telemetry) after changing this; if it climbs during normal operation, raise
`sink.fifo_samples` in `webtx.json` a notch.

## Building

```
cd native
make                       # builds webtx_iq and webtx-sendiq; the vendored
                           # librpitx is built automatically if no system
                           # install is found; RPITX_PATH is only used to
                           # look for a *system* install (default
                           # /opt/rpitx) and does not need to exist
sudo make install          # installs both to /usr/local/bin
```

`make check` reports which librpitx (system or vendored) would be used,
without building. This only builds on ARM Linux (Raspberry Pi): `librpitx`
itself requires Broadcom's VideoCore headers/libs (`libraspberrypi-dev`,
`/opt/vc/include`, `-lbcm_host`), which do not exist on other platforms. On
any other host, `make` refuses with a clear message; the webtx server
itself still runs everywhere by falling back to stock `sendiq` or the
`null` sink (see `sink.kind` in `webtx.json`).

## webtx-sendiq: a stock-compatible fallback

`make` here also builds `webtx-sendiq`: a build of the vendored,
low-latency-patched copy of rpitx's own `sendiq.cpp`
(`../vendor/rpitx-src/sendiq.cpp` - see `../vendor/NOTICE.md` and
`../docs/DECISIONS.md` ADR-010), linked against the exact same resolved
librpitx as `webtx_iq` above. It exists so the stock-`sendiq`-compatible
fallback sink (`sink.kind: "sendiq"`) also needs zero external download -
previously that required a full, separate upstream rpitx install (see
README.md section 5). It is named `webtx-sendiq`, not `sendiq`, so it never
collides with a system-installed rpitx's own `/opt/rpitx/sendiq`.

`webtx_iq` above remains the primary recommendation - it is the one with
`--ptt-gate` and the much lower default `-b`/`-F` latency values.
`webtx-sendiq` is for operators or configurations that specifically expect
stock `sendiq`'s exact command-line interface and upstream-identical
defaults. `webtx/tx.py`'s sink resolution prefers a built/installed
`webtx-sendiq` over a real separate rpitx install's own `sendiq` when both
are present, but either one resolves to the same `sink.kind: "sendiq"` -
see `../docs/DECISIONS.md` ADR-010.

## Testing standalone

With a dummy load connected (never key into an open antenna during bring-up):

```
sudo /usr/local/bin/webtx_iq -f 14200000 -s 48000 -p 1.0 --ptt-gate -v < /dev/zero
```

`/dev/zero` is all-zero samples, so with `--ptt-gate` the carrier should
**never** come on (verify with a receiver or power meter on the dummy load);
stop with Ctrl+C. To confirm the carrier does come on for real signal, use a
short recording of interleaved float32 IQ instead of `/dev/zero`.

## Command-line reference

```
webtx_iq -f <freq_hz> -s <samplerate> -p <power> [options]

Required:
  -f <float>   center frequency in Hz (5000 to 1500000000)
  -s <int>     IQ sample rate in Hz (1000 to 250000)
  -p <float>   drive power level (0.00 to 7.00)

Options:
  -h <int>     harmonic number (default 1)
  -b <int>     burst size in samples read per iteration (default 512)
  -F <int>     DMA FIFO size in samples (default 2048)
  --ptt-gate   hold the carrier off until the first non-silent block
  -v           print "STAT depth=<n> under=<n>" to stderr every ~500 ms
  -?           show help
```

Reads interleaved little-endian float32 I,Q samples from stdin (identical to
`sendiq -t float`). Must run as root.
