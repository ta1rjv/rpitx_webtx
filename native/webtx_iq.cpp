/*
 * webtx_iq - low-latency IQ transmitter for Raspberry Pi (rpitx/librpitx).
 *
 * Derived from rpitx's src/sendiq.cpp, rebuilt for minimum latency and to fix
 * the "tune tone at key-down" behaviour. Root cause and full arithmetic are in
 * ../docs/LATENCY.md; summary:
 *
 *   1. librpitx/src/iqdmasync.cpp's constructor calls clkgpio::enableclk(4)
 *      before any IQ sample exists, so the GPIO clock (the carrier) is
 *      already radiating while the caller is still filling its FIFO. This is
 *      the unmodulated "tune tone" heard at every key-down. Upstream flags
 *      this itself with a "FixMe carrier is already there" comment.
 *   2. librpitx paces SetIQSamples() to keep the DMA FIFO 3/4 full, so
 *      steady-state latency is 0.75 * fifo_samples / samplerate. Stock
 *      sendiq uses fifo_samples = IQBURST*4 = 16000 -> 250 ms at 48 kHz.
 *   3. Stock sendiq reads IQBURST = 4000 samples (83 ms) per fread(), adding
 *      further latency before any data reaches the FIFO pacing loop at all.
 *
 * This program exposes fifo_samples (-F) and burst_samples (-b) as flags with
 * much lower defaults (2048 / 512, ~32 ms and ~11 ms respectively), and adds
 * --ptt-gate, which uses clkgpio::disableclk(4)/enableclk(4) - the same
 * primitive the constructor itself uses - to hold the carrier off until the
 * first non-silent block is ready to transmit, instead of reconstructing the
 * whole DMA/PLL object (which would be far more invasive).
 *
 * Wire format: interleaved little-endian float32 I,Q samples on stdin -
 * identical to `sendiq -t float`.
 */

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <complex>
#include <csignal>
#include <vector>

#include <fcntl.h>
#include <getopt.h>
#include <unistd.h>

#include <librpitx/librpitx.h>

namespace {

volatile sig_atomic_t g_running = 1;

void on_signal(int) {
    g_running = 0;
}

void print_usage(const char *prog) {
    std::fprintf(stderr,
        "webtx_iq - low-latency IQ transmitter for Raspberry Pi (rpitx/librpitx)\n"
        "\n"
        "Usage: %s -f <freq_hz> -s <samplerate> -p <power> [options]\n"
        "\n"
        "Required:\n"
        "  -f <float>   center frequency in Hz (5000 to 1500000000)\n"
        "  -s <int>     IQ sample rate in Hz (1000 to 250000)\n"
        "  -p <float>   drive power level (0.00 to 7.00)\n"
        "\n"
        "Options:\n"
        "  -h <int>     harmonic number (default 1)\n"
        "  -b <int>     burst size in samples read per iteration (default 512,\n"
        "               ~10.7 ms at 48 kHz; stock sendiq uses 4000, ~83 ms)\n"
        "  -F <int>     DMA FIFO size in samples (default 2048, steady-state\n"
        "               latency 0.75*F/samplerate = ~32 ms; stock sendiq uses\n"
        "               16000, ~250 ms). Smaller is lower-latency but more\n"
        "               sensitive to scheduling jitter - see README.md.\n"
        "  --ptt-gate   hold the carrier off until the first non-silent block\n"
        "               is ready, instead of radiating an unmodulated tone\n"
        "               from process start (see the file header comment)\n"
        "  -v           print periodic stats to stderr as:\n"
        "               STAT depth=<fifo_occupancy_samples> under=<underrun_count>\n"
        "  -?           show this help\n"
        "\n"
        "Reads interleaved little-endian float32 I,Q samples from stdin.\n"
        "Must run as root (needs /dev/mem for GPIO/DMA access).\n",
        prog);
}

double g_silence_threshold = 1e-4;

} // namespace

int main(int argc, char **argv) {
    double freq_hz = 0.0;
    int sample_rate = 0;
    double power = -1.0;
    int harmonic = 1;
    int burst_samples = 512;
    int fifo_samples = 2048;
    bool ptt_gate = false;
    bool verbose = false;
    bool have_freq = false, have_rate = false, have_power = false;

    static const struct option long_opts[] = {
        {"ptt-gate", no_argument, nullptr, 1000},
        {"help", no_argument, nullptr, '?'},
        {nullptr, 0, nullptr, 0},
    };

    int opt;
    while ((opt = getopt_long(argc, argv, "f:s:p:h:b:F:v?", long_opts, nullptr)) != -1) {
        switch (opt) {
            case 'f': freq_hz = std::atof(optarg); have_freq = true; break;
            case 's': sample_rate = std::atoi(optarg); have_rate = true; break;
            case 'p': power = std::atof(optarg); have_power = true; break;
            case 'h': harmonic = std::atoi(optarg); break;
            case 'b': burst_samples = std::atoi(optarg); break;
            case 'F': fifo_samples = std::atoi(optarg); break;
            case 'v': verbose = true; break;
            case 1000: ptt_gate = true; break;
            case '?':
                print_usage(argv[0]);
                return 0;
            default:
                print_usage(argv[0]);
                return 2;
        }
    }

    if (!have_freq || !have_rate || !have_power) {
        std::fprintf(stderr, "webtx_iq: -f, -s and -p are all required\n");
        print_usage(argv[0]);
        return 2;
    }
    if (freq_hz < 5000.0 || freq_hz > 1500000000.0) {
        std::fprintf(stderr, "webtx_iq: freq_hz %.1f out of range [5000, 1500000000]\n", freq_hz);
        return 2;
    }
    if (sample_rate < 1000 || sample_rate > 250000) {
        std::fprintf(stderr, "webtx_iq: samplerate %d out of range [1000, 250000]\n", sample_rate);
        return 2;
    }
    if (power < 0.0 || power > 7.0) {
        std::fprintf(stderr, "webtx_iq: power %.2f out of range [0.00, 7.00]\n", power);
        return 2;
    }
    if (burst_samples <= 0 || burst_samples > 65536) {
        std::fprintf(stderr, "webtx_iq: burst_samples %d out of range (0, 65536]\n", burst_samples);
        return 2;
    }
    if (fifo_samples <= 0 || fifo_samples > 1000000) {
        std::fprintf(stderr, "webtx_iq: fifo_samples %d out of range (0, 1000000]\n", fifo_samples);
        return 2;
    }
    if (harmonic < 1) {
        std::fprintf(stderr, "webtx_iq: harmonic must be >= 1\n");
        return 2;
    }

    if (geteuid() != 0) {
        std::fprintf(stderr,
            "webtx_iq: must run as root to access /dev/mem for GPIO/DMA transmission "
            "(run under systemd as root, or with sudo)\n");
        return 1;
    }

    std::signal(SIGINT, on_signal);
    std::signal(SIGTERM, on_signal);

    // Shrink stdin's pipe buffer to slightly more than one burst. Without
    // this, Linux's default 64 KB pipe buffer lets the writer queue several
    // bursts (~170 ms at the default burst size) before this process's own
    // pacing (below) ever creates backpressure, silently hiding that latency.
#ifdef F_SETPIPE_SZ
    {
        long target = static_cast<long>(burst_samples) * 2 * static_cast<long>(sizeof(float)) * 2;
        if (target < 4096) target = 4096;
        fcntl(STDIN_FILENO, F_SETPIPE_SZ, target);
    }
#endif

    iqdmasync tx(static_cast<uint64_t>(freq_hz), static_cast<uint32_t>(sample_rate),
                 harmonic, static_cast<uint32_t>(fifo_samples), MODE_IQ);
    tx.SetPLLMasterLoop(3, 4, 0);

    // See the file header: the constructor above already enabled the GPIO
    // clock output (the carrier). With --ptt-gate, turn it back off right
    // away and only re-enable it once real audio is ready to transmit.
    bool carrier_on = true;
    if (ptt_gate) {
        tx.disableclk(4);
        carrier_on = false;
    }

    std::vector<std::complex<float>> buffer(static_cast<size_t>(burst_samples));
    unsigned long underrun_count = 0;
    struct timespec last_stat_time;
    clock_gettime(CLOCK_MONOTONIC, &last_stat_time);

    while (g_running) {
        size_t got = 0;
        while (got < static_cast<size_t>(burst_samples) && g_running) {
            size_t want = static_cast<size_t>(burst_samples) - got;
            size_t n = std::fread(buffer.data() + got, sizeof(std::complex<float>), want, stdin);
            if (n == 0) {
                if (std::feof(stdin) || std::ferror(stdin)) {
                    g_running = 0;
                }
                break;
            }
            got += n;
        }
        if (got == 0) {
            break;
        }

        if (ptt_gate && !carrier_on) {
            float peak = 0.0f;
            for (size_t i = 0; i < got; i++) {
                float mag = std::abs(buffer[i]);
                if (mag > peak) peak = mag;
            }
            if (peak > static_cast<float>(g_silence_threshold)) {
                tx.enableclk(4);
                carrier_on = true;
            }
        }

        if (tx.GetBufferAvailable() <= 0) {
            underrun_count++;
        }

        tx.SetIQSamples(buffer.data(), got, harmonic);

        if (verbose) {
            struct timespec now;
            clock_gettime(CLOCK_MONOTONIC, &now);
            double elapsed_ms = (now.tv_sec - last_stat_time.tv_sec) * 1000.0
                              + (now.tv_nsec - last_stat_time.tv_nsec) / 1.0e6;
            if (elapsed_ms >= 500.0) {
                int depth = fifo_samples - tx.GetBufferAvailable();
                if (depth < 0) depth = 0;
                std::fprintf(stderr, "STAT depth=%d under=%lu\n", depth, underrun_count);
                std::fflush(stderr);
                last_stat_time = now;
            }
        }
    }

    if (ptt_gate && carrier_on) {
        tx.disableclk(4);
    }

    return 0;
}
