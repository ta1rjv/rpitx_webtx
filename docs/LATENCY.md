# Latency Analysis and Root Cause

Status: MEASURED (source analysis) + IMPLEMENTED (fixes)
Scope: microphone -> browser -> WebSocket -> modulator -> RF sink -> antenna port

This document records the evidence-based root cause of the reported behaviour:

> "When I key TX, a tune tone is transmitted first, then my voice arrives late.
> The same happens in LSB, USB, FM and AM."

Both symptoms have the **same** root cause chain. They are not two separate bugs.

---

## 1. Evidence

All line references are to upstream sources fetched at analysis time:

* `F5OEO/rpitx` -> `src/sendiq.cpp`
* `F5OEO/librpitx` -> `src/iqdmasync.cpp`, `src/dma.cpp`
* `ha7ilm/csdr` -> `csdr.c`, `libcsdr.c`

### 1.1 The carrier is enabled before any sample exists (the "tune tone")

`librpitx/src/iqdmasync.cpp`, constructor:

```cpp
iqdmasync::iqdmasync(uint64_t TuneFrequency,uint32_t SR,int Channel,uint32_t FifoSize,int Mode)
    :bufferdma(Channel,FifoSize,4,3)
{
    ...
    clkgpio::SetCenterFrequency(TuneFrequency,SampleRate); // Write Mult Int and Frac : FixMe carrier is already there
    clkgpio::SetFrequency(0);
    clkgpio::enableclk(4);          // <-- carrier ON here, before any IQ data
```

Upstream itself flags this with `FixMe carrier is already there`. The GPIO clock
output is enabled the moment the object is constructed. Until modulated samples
reach the DMA FIFO, what is radiated is an unmodulated carrier - which is exactly
what an operator hears as a "tune tone".

### 1.2 librpitx deliberately keeps the DMA FIFO three-quarters full

`librpitx/src/iqdmasync.cpp`, `SetIQSamples()`:

```cpp
int Available=GetBufferAvailable();
int TimeToSleep=1e6*((int)buffersize*3/4-Available)/(float)SampleRate; // Sleep for theorically fill 3/4 of Fifo
if(TimeToSleep>0) usleep(TimeToSleep);
```

This is a hard, by-design steady-state delay of `0.75 * buffersize / SampleRate`.

### 1.3 sendiq chooses a very large FIFO and a very large read burst

`rpitx/src/sendiq.cpp`:

```cpp
#define IQBURST 4000
int FifoSize=IQBURST*4;                    // = 16000 samples
iqdmasync iqtest(SetFrequency,SampleRate,14,FifoSize,MODE_IQ);
...
int nbread=fread(IQBuffer,sizeof(float),IQBURST*2,iqfile);   // blocks for 4000 complex samples
```

At 48 kHz:

| Source | Samples | Latency |
|---|---:|---:|
| DMA FIFO target (3/4 of 16000) | 12000 | **250.0 ms** |
| `fread` burst granularity (4000) | 4000 | **83.3 ms** |

### 1.4 The csdr chain adds four processes of block and pipe buffering

The previous `server.py` built, per keyed transmission, a four-stage shell pipeline:

```
csdr convert_i16_f | csdr gain_ff | csdr dsb_fc | csdr bandpass_fir_fft_cc 0.003 0.065 0.01 | sudo sendiq ...
```

`csdr.c` `bandpass_fir_fft_cc` uses FFT overlap-add. With `transition_bw = 0.01`:

* `firdes_filter_len(0.01)` -> `4.0/0.01 = 400`, made odd -> **401 taps**
* `next_pow2(401)` -> 512; `512 - 401 = 111 < 200` so `fft_size <<= 1` -> **1024**
* `input_size = fft_size - taps_length + 1` = **624 samples** = 13.0 ms per block

Each stage additionally holds a libc stdio buffer and a 4 KB kernel pipe buffer
(`initialize_buffers()` sets `F_SETPIPE_SZ` to 4096), and each of the four
processes must be scheduled before a sample advances. On a Pi Zero this is both a
latency and a CPU cost, for DSP that is a few hundred multiply-accumulates per
sample.

### 1.5 The old server added latency and dropouts of its own

Previous `server.py`:

* fed the pipeline in 1024-byte chunks from a 2 ms polling loop;
* on overflow executed `del audio_buffer[:-2048]`, discarding roughly 6 KB
  (~64 ms) of speech instantly - audible as a dropout, and it does not reduce
  steady-state latency, it only masks the symptom;
* started the transmitter **lazily on the first audio chunk**, so the sendiq
  process start (mmap `/dev/mem`, PLL setup, DMA ring construction) happened
  *after* the operator pressed PTT, adding process-startup time on top;
* used `flask_socketio` with `async_mode='threading'` on the Werkzeug development
  server, which has high per-message overhead and is explicitly not a production
  WebSocket server;
* changed transmit parameters by killing and restarting the whole pipeline,
  re-paying the entire startup cost mid-transmission.

### 1.6 Total

| Stage | Old |
|---|---:|
| Browser AudioWorklet frame (512 samples) | 10.7 ms |
| WebSocket + Socket.IO + Werkzeug | 5-20 ms |
| Server buffer + 2 ms poll | 10-25 ms |
| csdr chain (4 processes, FFT overlap-add, pipes) | 30-60 ms |
| sendiq `fread` burst | 83.3 ms |
| librpitx DMA FIFO (3/4 of 16000) | 250.0 ms |
| **Total** | **~390-450 ms** |

And at key-down, the carrier is already radiating (1.1) while the 250 ms FIFO
fills with silence - producing the tune tone, followed by delayed audio. This
explains the reported symptom in every mode, because every mode shares the same
sink.

---

## 2. Fixes applied

| # | Fix | Saved |
|---|---|---:|
| 1 | `native/webtx_iq`: `fifo_samples` default 2048 instead of 16000 -> 3/4 of 2048 = 1536 samples | 250.0 -> **32.0 ms** |
| 2 | `native/webtx_iq`: `burst_samples` default 512 instead of 4000 | 83.3 -> **10.7 ms** |
| 3 | `native/webtx_iq --ptt-gate`: the carrier is not enabled until the first non-silent block, removing the tune tone | tune tone eliminated |
| 4 | csdr removed entirely; modulation is done in-process with NumPy FIR DSP (`webtx/dsp.py`) | 30-60 -> **~3 ms** |
| 5 | Socket.IO removed; raw binary WebSocket on aiohttp | 5-20 -> **2-5 ms** |
| 6 | `webtx/jitter.py`: adaptive jitter buffer with energy-aware drop and interpolated insert, replacing the destructive 6 KB flush | dropouts eliminated |
| 7 | Sink starts on `start_tx`, not on the first audio frame; process startup no longer sits inside the PTT path | startup delay removed |
| 8 | Gain and power changes no longer restart the sink | mid-transmission gaps removed |

Expected total after the fixes, at 48 kHz with the default configuration:

| Stage | New |
|---|---:|
| Browser AudioWorklet frame (10 ms) | 10.0 ms |
| WebSocket (LAN) | 2-5 ms |
| Jitter buffer target | 30.0 ms |
| NumPy modulator (129-tap Hilbert) | ~1.5 ms + 1.3 ms group delay |
| `webtx_iq` read burst (512) | 10.7 ms |
| librpitx DMA FIFO (3/4 of 2048) | 32.0 ms |
| **Total** | **~88-92 ms** |

Lowering `audio.jitter_target_ms` to 10 ms and `sink.fifo_samples` to 1024 on a
Pi 3/4 with a wired network reaches roughly **50 ms**, at the cost of a higher
underrun risk. This is a deliberate, documented tradeoff, exposed in the
configuration rather than hardcoded.

### 2.1 Real hardware measurement (Raspberry Pi 2)

Status: MEASURED (2026-09-02, Raspberry Pi 2, armv7l, BCM2836, Ubuntu 22.04)

`tests/test_dsp.py::test_frame_processing_time_budget` measured the NumPy
modulator's average time to process a 10 ms (480-sample) frame on real
target hardware for the first time:

| Mode | Measured avg / frame |
|---|---:|
| USB | 3.977 ms |
| LSB | 3.956 ms |

This is higher than the ~1.5 ms figure used for "NumPy modulator" in the
"Expected total" table above, which was an x86-derived estimate, not
previously validated on target hardware. The ~88-92 ms end-to-end total in
that table is therefore somewhat optimistic on this specific line item. It
remains comfortably real-time-safe: 3.98 ms is still roughly 60% headroom
inside the 10 ms frame period, not the roughly 85% headroom the 1.5 ms
figure implied. `tests/test_dsp.py` now uses a platform-aware time budget
(6 ms on ARM) derived from this measurement instead of the x86-only 2 ms
figure it used before.

---

## 3. What is measured at runtime

`webtx/metrics.py` tracks five stages and the server pushes them to the UI every
500 ms:

* `net` - arrival jitter above the best observed path. **Not** absolute one-way
  delay: the browser and the Pi do not share a clock, so the server tracks the
  minimum observed clock offset over a rolling window and reports each frame
  relative to that baseline. Absolute round-trip time is measured separately by
  the ping/pong pair and shown as RTT.
* `jitter` - current jitter buffer depth in ms.
* `dsp` - measured modulator wall time per frame.
* `sink` - DMA FIFO occupancy in ms, parsed from `webtx_iq -v` `STAT depth=<n>`
  lines. When running against stock `sendiq`, which does not report depth, the
  configured FIFO target is reported instead and is labelled as an estimate.
* `total` - the sum of the above.

---

## 4. Residual limits that cannot be removed

* The browser's own capture path (driver -> WebAudio) contributes 10-30 ms that is
  outside this application's control and varies by OS and browser.
* `0.75 * fifo_samples / sample_rate` is fixed by librpitx's pacing policy in
  `SetIQSamples()`. It can be made smaller only by shrinking the FIFO, which
  increases underrun risk. Changing the 3/4 policy itself would require patching
  librpitx and was deliberately not done - see `docs/DECISIONS.md`.
* Wi-Fi adds highly variable latency. Ethernet or USB gadget networking is
  strongly preferred for low-latency operation.
