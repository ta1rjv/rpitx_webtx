# patches/sendiq-lowlatency.patch

**Optional.** `native/webtx_iq` (see `../native/README.md`) is the primary,
recommended low-latency transmitter and needs no changes to rpitx at all. This
patch exists only for operators who would rather adjust stock `sendiq`
in place than build a separate binary.

## What it does

Adds two flags to rpitx's `src/sendiq.cpp`:

- `-b <n>`: read burst size in complex samples per `fread()` (1 to 4000).
  Default 4000 - **identical to unpatched upstream** when omitted.
- `-F <n>`: DMA FIFO size in complex samples, passed to the `iqdmasync`
  constructor. Default `IQBURST*4` = 16000 - **identical to unpatched
  upstream** when omitted.

No other behaviour changes. With neither flag passed, the patched binary is
byte-for-byte behaviourally identical to stock sendiq.

## Why (the arithmetic)

See `../docs/LATENCY.md` for the full analysis. In short, `rpitx/src/sendiq.cpp`
hardcodes:

```cpp
#define IQBURST 4000
int FifoSize=IQBURST*4;   // = 16000
```

and `librpitx/src/iqdmasync.cpp`'s `SetIQSamples()` paces output to keep the
DMA FIFO 3/4 full, so steady-state latency is `0.75 * FifoSize / SampleRate`:
`0.75 * 16000 / 48000 = 250 ms` at 48 kHz, plus another 83 ms from the fixed
4000-sample read burst before any data even reaches that pacing loop. This
patch exposes both constants as flags so they can be lowered (webtx's own
launcher uses `-b 512 -F 2048`, giving roughly `10.7 ms + 32.0 ms`) without
touching any other logic. It does not add `--ptt-gate` or FIFO-depth
reporting; those require the constructor-level carrier control and stats loop
that `native/webtx_iq` implements directly, which is a larger change than fits
a minimal patch to a shared upstream file.

## How to apply

```
cd rpitx
patch -p1 < /path/to/rpitx_webtx/patches/sendiq-lowlatency.patch
cd src
make
sudo make install
```

Then set `sink.kind` to `"sendiq"` (or leave `"auto"`, which prefers
`webtx_iq` when present) and lower `sink.fifo_samples` / `sink.burst_samples`
in `webtx.json` - the server passes these to whichever binary is resolved,
including a patched `sendiq`.

## Verification performed

The patch was generated from a clean copy of upstream `rpitx/src/sendiq.cpp`,
applied with `patch -p1` against a fresh copy to confirm it applies without
fuzz, and the result was syntax-checked with
`g++ -fsyntax-only -x c++ -std=c++11` against the `librpitx` headers. It has
**not** been linked, run, or tested on hardware - that requires librpitx's
Broadcom VideoCore build dependencies, which only exist on a Raspberry Pi.
