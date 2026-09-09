"""JSON-file configuration with documented defaults and eager validation.

Replaces the old requirement to edit RPITX_PATH directly inside server.py
(docs/DECISIONS.md ADR-007). Resolution order for the config file path:
1. the --config CLI argument (handled in __main__.py),
2. the $WEBTX_CONFIG environment variable,
3. ./webtx.json in the current working directory,
4. built-in defaults only, if none of the above exist.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from typing import Any, List, Optional


class ConfigError(ValueError):
    """Raised with every validation problem collected, not just the first."""


DEFAULTS: dict = {
    "host": "0.0.0.0",
    "port": 5000,
    "tls": {
        "enabled": True,
        "cert": "certs/cert.pem",
        "key": "certs/key.pem",
    },
    "rpitx_path": "/opt/rpitx",
    "sink": {
        "kind": "auto",
        "binary": "",
        "fifo_samples": 2048,
        "burst_samples": 512,
        "ppm": 0.0,
        "harmonic": 1,
        "dry_run": False,
    },
    "audio": {
        "sample_rate": 48000,
        "frame_ms": 10,
        "jitter_target_ms": 30,
        "jitter_max_ms": 120,
    },
    "rf": {
        "min_freq_hz": 5000,
        "max_freq_hz": 1500000000,
        "max_power": 7.0,
        "default_freq_hz": 14200000,
        "default_mode": "USB",
        "allowed_ranges": [],
    },
    "dsp": {
        "ssb_low_hz": 300.0,
        "ssb_high_hz": 2700.0,
        "fm_deviation_hz": 2500.0,
        "am_modulation_index": 0.85,
        "am_carrier_level": 0.5,
        "audio_hpf_hz": 200.0,
        "hilbert_taps": 129,
        "limiter_enabled": True,
        "agc_enabled": True,
        "agc_target": 0.35,
        "agc_attack_ms": 5.0,
        "agc_release_ms": 300.0,
    },
    "log": {
        "level": "INFO",
        "file": "",
    },
}

_VALID_MODES = ("USB", "LSB", "FM", "AM")
_VALID_SINK_KINDS = ("auto", "webtx_iq", "sendiq", "null")
_VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def _deep_merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def resolve_config_path(cli_path: Optional[str] = None) -> Optional[str]:
    """Return the config file path to load, honoring the documented precedence,
    or None if none of the candidates exist on disk."""
    candidates = []
    if cli_path:
        candidates.append(cli_path)
    env_path = os.environ.get("WEBTX_CONFIG")
    if env_path:
        candidates.append(env_path)
    candidates.append("webtx.json")
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    if cli_path or env_path:
        # An explicit path was requested but does not exist: surface that
        # loudly instead of silently falling back to defaults.
        return cli_path or env_path
    return None


@dataclass
class Config:
    data: dict = field(default_factory=lambda: copy.deepcopy(DEFAULTS))

    @classmethod
    def load(cls, cli_path: Optional[str] = None) -> "Config":
        path = resolve_config_path(cli_path)
        merged = copy.deepcopy(DEFAULTS)
        if path:
            if not os.path.isfile(path):
                raise ConfigError(f"config file not found: {path}")
            with open(path, "r", encoding="utf-8") as fh:
                try:
                    user_data = json.load(fh)
                except json.JSONDecodeError as exc:
                    raise ConfigError(f"invalid JSON in {path}: {exc}") from exc
            if not isinstance(user_data, dict):
                raise ConfigError(f"config file {path} must contain a JSON object")
            merged = _deep_merge(merged, user_data)
        cfg = cls(data=merged)
        cfg.validate()
        return cfg

    @staticmethod
    def default_json_text() -> str:
        return json.dumps(DEFAULTS, indent=2, sort_keys=False) + "\n"

    def validate(self) -> None:
        errors: List[str] = []
        d = self.data

        def require_type(path, value, types, label=None):
            if not isinstance(value, types):
                errors.append(f"{path} must be {label or types}, got {type(value).__name__}")

        require_type("host", d.get("host"), str)
        require_type("port", d.get("port"), int)
        if isinstance(d.get("port"), int) and not (0 < d["port"] < 65536):
            errors.append("port must be between 1 and 65535")

        tls = d.get("tls", {})
        require_type("tls", tls, dict)
        if isinstance(tls, dict):
            require_type("tls.enabled", tls.get("enabled"), bool)
            require_type("tls.cert", tls.get("cert"), str)
            require_type("tls.key", tls.get("key"), str)

        require_type("rpitx_path", d.get("rpitx_path"), str)

        sink = d.get("sink", {})
        require_type("sink", sink, dict)
        if isinstance(sink, dict):
            if sink.get("kind") not in _VALID_SINK_KINDS:
                errors.append(f"sink.kind must be one of {_VALID_SINK_KINDS}, got {sink.get('kind')!r}")
            require_type("sink.binary", sink.get("binary"), str)
            require_type("sink.fifo_samples", sink.get("fifo_samples"), int)
            if isinstance(sink.get("fifo_samples"), int) and sink["fifo_samples"] <= 0:
                errors.append("sink.fifo_samples must be positive")
            require_type("sink.burst_samples", sink.get("burst_samples"), int)
            if isinstance(sink.get("burst_samples"), int) and sink["burst_samples"] <= 0:
                errors.append("sink.burst_samples must be positive")
            require_type("sink.harmonic", sink.get("harmonic"), int)
            require_type("sink.dry_run", sink.get("dry_run"), bool)

        audio = d.get("audio", {})
        require_type("audio", audio, dict)
        if isinstance(audio, dict):
            require_type("audio.sample_rate", audio.get("sample_rate"), int)
            if isinstance(audio.get("sample_rate"), int) and not (8000 <= audio["sample_rate"] <= 192000):
                errors.append("audio.sample_rate must be between 8000 and 192000")
            require_type("audio.frame_ms", audio.get("frame_ms"), (int, float))
            require_type("audio.jitter_target_ms", audio.get("jitter_target_ms"), (int, float))
            require_type("audio.jitter_max_ms", audio.get("jitter_max_ms"), (int, float))
            if (isinstance(audio.get("jitter_target_ms"), (int, float))
                    and isinstance(audio.get("jitter_max_ms"), (int, float))
                    and audio["jitter_target_ms"] > audio["jitter_max_ms"]):
                errors.append("audio.jitter_target_ms must not exceed audio.jitter_max_ms")

        rf = d.get("rf", {})
        require_type("rf", rf, dict)
        if isinstance(rf, dict):
            require_type("rf.min_freq_hz", rf.get("min_freq_hz"), (int, float))
            require_type("rf.max_freq_hz", rf.get("max_freq_hz"), (int, float))
            if (isinstance(rf.get("min_freq_hz"), (int, float))
                    and isinstance(rf.get("max_freq_hz"), (int, float))
                    and rf["min_freq_hz"] >= rf["max_freq_hz"]):
                errors.append("rf.min_freq_hz must be less than rf.max_freq_hz")
            require_type("rf.max_power", rf.get("max_power"), (int, float))
            if isinstance(rf.get("max_power"), (int, float)) and not (0 < rf["max_power"] <= 7.0):
                errors.append("rf.max_power must be between 0 (exclusive) and 7.0")
            require_type("rf.default_freq_hz", rf.get("default_freq_hz"), (int, float))
            if rf.get("default_mode") not in _VALID_MODES:
                errors.append(f"rf.default_mode must be one of {_VALID_MODES}, got {rf.get('default_mode')!r}")
            ranges = rf.get("allowed_ranges", [])
            require_type("rf.allowed_ranges", ranges, list)
            if isinstance(ranges, list):
                for i, r in enumerate(ranges):
                    if (not isinstance(r, (list, tuple)) or len(r) != 2
                            or not all(isinstance(v, (int, float)) for v in r) or r[0] >= r[1]):
                        errors.append(f"rf.allowed_ranges[{i}] must be a [low_hz, high_hz] pair with low < high")

        dsp = d.get("dsp", {})
        require_type("dsp", dsp, dict)
        if isinstance(dsp, dict):
            if isinstance(dsp.get("hilbert_taps"), int) and dsp["hilbert_taps"] % 2 == 0:
                errors.append("dsp.hilbert_taps must be odd")
            for key in ("ssb_low_hz", "ssb_high_hz", "fm_deviation_hz", "audio_hpf_hz",
                        "agc_attack_ms", "agc_release_ms"):
                if key in dsp and not isinstance(dsp[key], (int, float)):
                    errors.append(f"dsp.{key} must be numeric")
            if (isinstance(dsp.get("ssb_low_hz"), (int, float))
                    and isinstance(dsp.get("ssb_high_hz"), (int, float))
                    and dsp["ssb_low_hz"] >= dsp["ssb_high_hz"]):
                errors.append("dsp.ssb_low_hz must be less than dsp.ssb_high_hz")

        log = d.get("log", {})
        require_type("log", log, dict)
        if isinstance(log, dict):
            if log.get("level") not in _VALID_LOG_LEVELS:
                errors.append(f"log.level must be one of {_VALID_LOG_LEVELS}, got {log.get('level')!r}")
            require_type("log.file", log.get("file"), str)

        if errors:
            raise ConfigError("invalid configuration:\n  - " + "\n  - ".join(errors))

    def get(self, *path, default=None):
        node: Any = self.data
        for key in path:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def apply_overrides(self, host=None, port=None, no_tls=False, sink_kind=None,
                         log_level=None, dry_run=False) -> None:
        if host is not None:
            self.data["host"] = host
        if port is not None:
            self.data["port"] = port
        if no_tls:
            self.data["tls"]["enabled"] = False
        if sink_kind is not None:
            self.data["sink"]["kind"] = sink_kind
        if log_level is not None:
            self.data["log"]["level"] = log_level
        if dry_run:
            self.data["sink"]["dry_run"] = True
