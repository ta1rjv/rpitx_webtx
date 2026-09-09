# rpitx_webtx-main Project Index

## Project Overview

- **Name**: rpitx_webtx-main
- **Status**: Active (development)
- **Type**: Browser-controlled SDR transmitter control panel
- **Last Updated**: 2026-09-09
- **Primary Focus**: Raspberry Pi SDR transmitter with sub-100ms latency

## Project Structure

```
rpitx_webtx-main/
├── README.md                    # Project overview (377 lines)
├── .claude/
│   └── CLAUDE.md                # Project orchestration instructions
├── docs/                        # Standard documentation set (12/12 files)
│   ├── AGENT.md                 # Project-specific agent rules
│   ├── ARCHITECTURE.md          # System architecture
│   ├── ASSUMPTIONS.md           # Engineering assumptions
│   ├── CHANGELOG.md             # Version history
│   ├── DECISIONS.md             # Architecture decisions
│   ├── LATENCY.md               # Detailed latency analysis
│   ├── PRESENTATION_NOTES.md    # Presentation notes
│   ├── PROGRESS.md              # Milestone tracking
│   ├── REQUIREMENTS.md          # Requirements and status
│   ├── STATUS.md                # Project status
│   └── TEST_PLAN.md             # Test strategy and results
├── native/                      # C++ transmitter (webtx_iq, webtx-sendiq)
├── webtx/                       # Python WebSocket server
├── vendor/                      # Vendored dependencies
│   ├── librpitx/                # Vendored librpitx
│   └── rpitx-src/               # Vendored rpitx source
├── tools/                       # Certificates and utilities
├── systemd/                     # Systemd service definitions
├── tests/                       # Python test suite
├── slides/                      # Presentation slides
├── legacy/                      # Legacy code
├── webtx/                       # Web interface
└── patches/                     # Applied patches
```

## Documentation Completeness

All standard documentation files are present, plus 2 additional docs:

| Document | Status | Description |
|----------|--------|-------------|
| `AGENT.md` | [X] Complete | Project-specific agent rules |
| `ARCHITECTURE.md` | [X] Complete | Web/SDR architecture |
| `ASSUMPTIONS.md` | [X] Complete | Engineering assumptions (validated on Pi 2) |
| `CHANGELOG.md` | [X] Complete | Version history |
| `DECISIONS.md` | [X] Complete | Architecture decisions |
| `LATENCY.md` | [X] Complete | Latency analysis (sub-100ms target) |
| `PRESENTATION_NOTES.md` | [X] Complete | Presentation notes |
| `PROGRESS.md` | [X] Complete | Milestone tracking |
| `REQUIREMENTS.md` | [X] Complete | Requirements and status |
| `STATUS.md` | [X] Complete | Validated on Raspberry Pi 2 |
| `TEST_PLAN.md` | [X] Complete | Test strategy and results |

## Key Features

- **Low Latency**: Sub-100ms glass-to-air latency
- **Multi-Mode**: USB, LSB, FM, AM transmission modes
- **Web Control**: Browser-based control interface via WebSocket
- **Real-Time Voice**: Real-time voice transmission from browser microphone
- **Native C++**: High-performance C++ transmitter (webtx_iq, webtx-sendiq)
- **Vendored Dependencies**: librpitx and rpitx-src bundled (no external download)
- **Self-Healing**: install.sh auto-upgrades apt aiohttp if too old

## Technology Stack

- **Frontend**: HTML/CSS/JavaScript (vanilla)
- **Backend**: Python 3.9+ with aiohttp WebSocket server
- **Transmitter**: C++ (webtx_iq low-latency, webtx-sendiq stock-compatible)
- **Target Hardware**: Raspberry Pi (Zero through 4) with GPIO4
- **Vendored Libraries**: librpitx, rpitx source
- **Testing**: Python test suite (110/110 passing on Pi 2)

## Hardware Configuration

- **GPIO Pin**: Default GPIO4 (configurable via webtx.json)
- **RF Output**: Square wave from GPIO pin
- **Filter Required**: Low-pass/band-pass filter for harmonic suppression
- **Audio**: 48000 Hz sample rate (configurable in webtx.json)
- **Modes**: USB, LSB, FM, AM

## Related Skills and Agents

### Skills
- `sdr-hardware-bringup-testing` - Hardware bring-up and testing
- `rf-engineering` - RF calculation rules
- `rf-link-budget-propagation-analysis` - RF link budget
- `arm-dsp-fft-optimization` - ARM DSP optimization
- `arm-embedded-kernel-debugging` - ARM kernel debugging

### Agents
- `rpitx-specialist` - rpitx/WebTX transmission expertise
- `coder` - Feature implementation
- `planner` - Architecture planning
- `reviewer` - Code and specification review
- `builder` - Compilation, testing, and validation

## Validation Status (2026-09-02)

### Validated on Raspberry Pi 2 (armv7l)
- install.sh end-to-end with self-healing aiohttp fix
- Native compilation: webtx_iq and webtx-sendiq (zero external rpitx download)
- Full test suite: 110/110 passing on-device
- WebSocket protocol suite: 15/15 passing
- Sink resolution: 20/20 tests passing
- Systemd service install/start/status/stop
- RF keydown USB 145.5 MHz (zero crash/error)

### Not Verified
- Actual glass-to-air latency measurement (only process-timing derived)
- 145.5 MHz USB signal received/decoded (user monitored with own SDR)
- FM, LSB, AM modes on air
- Browser/UI experience on real device

## Quick Navigation

### Core Documentation
- `README.md` - Project overview (377 lines)
- `docs/ARCHITECTURE.md` - System architecture
- `docs/STATUS.md` - Validation status (Raspberry Pi 2)
- `docs/PROGRESS.md` - Milestone tracking
- `docs/LATENCY.md` - Latency analysis (sub-100ms target)

### Component Documentation
- `native/` - C++ transmitter sources
- `webtx/` - Python WebSocket server
- `vendor/librpitx/` - Vendored librpitx library
- `vendor/rpitx-src/` - Vendored rpitx source
- `tests/` - Python test suite

### Reference Materials
- See `.claude/README.md` for global skills and agents
- See `USER.md` for user expertise and preferences
- See master index at `/root/claude-code/INDEX.md` for workspace overview