# rpitx_webtx - Project CLAUDE.md

A browser-controlled, low-latency SDR transmitter control panel for Raspberry Pi, built on the rpitx engine (librpitx). Provides real-time voice transmission via USB, LSB, FM, or AM from any browser microphone with sub-100ms glass-to-air latency.

## Tech Stack

Frontend: HTML/CSS/JavaScript (vanilla, no framework) with WebSocket communication
Backend: Python 3.9+ with aiohttp for WebSocket server
C++ Transmitter: native/webtx_iq (low-latency) and native/webtx-sendiq (stock-compatible fallback)
Vendored Dependencies: librpitx (in vendor/librpitx), rpitx source (in vendor/rpitx-src)
Target Hardware: Raspberry Pi (Zero through 4) with GPIO pin wired through low-pass/band-pass filter

## Hardware

- **GPIO Pin**: Default GPIO4 (configurable via webtx.json)
- **RF Output**: Square wave from GPIO pin (requires external low-pass/band-pass filter for harmonic suppression)
- **Supported Modes**: USB, LSB, FM, AM
- **Latency Target**: Sub-100ms glass-to-air (achieved via adaptive jitter buffer and optimized DSP pipeline)
- **Audio Sample Rate**: 48000 Hz (configurable in webtx.json)

## Existing Code

- `webtx/` - Python WebSocket server and API endpoints
- `native/` - C++ transmitter (webtx_iq low-latency, webtx-sendiq stock-compatible)
- `vendor/librpitx/` - Vendored librpitx library (no external rpitx download needed for core functionality)
- `vendor/rpitx-src/` - Vendored rpitx source for stock sendiq compatibility
- `tools/` - Certificate generation and utility scripts
- `tests/` - Python test suite for DSP and WebSocket functionality
- `docs/` - Complete documentation set (ARCHITECTURE, REQUIREMENTS, ASSUMPTIONS, TEST_PLAN, DECISIONS, STATUS, CHANGELOG, PROGRESS, AGENT)
- `LATENCY.md` - Detailed latency analysis and measurement breakdown

## Build/Test Commands

- Build transmitter: `make -C native`
- Install transmitter: `sudo make -C native install`
- Run server: `sudo python3 -m webtx --config webtx.json`
- Run tests: `python3 -m pytest tests/ -q`
- Dry run (no RF): `python3 -m webtx --dry-run`
- One-command install: `sudo ./install.sh`

## Project Rules

- All transmission requires proper licensing for frequency and power level
- Must use low-pass/band-pass filter on GPIO output to suppress harmonics
- For testing only: use `sink.kind: "null"` to disable RF output
- Browser microphone access requires HTTPS (self-signed certificate acceptable)
- Systemd service available for persistent operation with auto-restart
- All assumptions and decisions documented in `docs/` directory
- No changes to upstream rpitx behavior unless documented in DECISIONS.md

## GitHub Commit Automation

### BEFORE any commit to GitHub:
1. Run documentation-sync skill to verify README.md reflects actual directory structure.
2. Verify no new files are missing from README.md repository structure section.
3. Verify all docs/ files mentioned in README.md actually exist.

### Author rules for GitHub commits:
- **Always** use author: `ta1rjv <amateurta1rjv@gmail.com>`
- Never commit as root or any other author.
- For sub-agent commits, use author: `claude <claude@anthropic.com>` only when explicitly doing Claude-code-only work.

### Commit message rules:
- Commit messages must be descriptive: `type(scope): description`
- Never push empty, "wip", or single-word commits.
- Always push to `main` branch only after README verification.

## Where to Look

- `docs/REQUIREMENTS.md` -- Functional and non-functional requirements
- `docs/ARCHITECTURE.md` -- System overview, data flow, latency breakdown
- `docs/ASSUMPTIONS.md` -- Documented assumptions (audio sample rate, GPIO pin, etc.)
- `docs/DECISIONS.md` -- Architecture decisions (vendor strategy, DSP choices)
- `docs/TEST_PLAN.md` -- Test strategy and verification results
- `docs/STATUS.md` -- Current state and known issues
- `docs/CHANGELOG.md` -- Version history
- `docs/PROGRESS.md` -- Milestone tracking
- `docs/AGENT.md` -- Agent-specific rules for this project
- `docs/LATENCY.md` -- Detailed latency analysis and measurements

## Reference Materials

- `vendor/NOTICE.md` -- Licensing information for vendored components
- `webtx.example.json` -- Configuration file template
- `tools/gen-cert.sh` -- TLS certificate generation script
- `install.sh` -- One-command installation script
- `systemd/` -- Systemd service definitions for persistent operation