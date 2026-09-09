import json
import os

import pytest

from webtx.config import Config, ConfigError, DEFAULTS, resolve_config_path


def test_defaults_load_without_a_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WEBTX_CONFIG", raising=False)
    cfg = Config.load()
    assert cfg.data["port"] == DEFAULTS["port"]
    assert cfg.data["rf"]["default_mode"] == "USB"


def test_env_override_path(tmp_path, monkeypatch):
    custom = tmp_path / "custom.json"
    custom.write_text(json.dumps({"port": 9999}))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WEBTX_CONFIG", str(custom))
    cfg = Config.load()
    assert cfg.data["port"] == 9999
    # Untouched keys keep their defaults (deep merge, not replace).
    assert cfg.data["rf"]["max_power"] == DEFAULTS["rf"]["max_power"]


def test_cli_path_takes_precedence_over_env(tmp_path, monkeypatch):
    env_file = tmp_path / "env.json"
    env_file.write_text(json.dumps({"port": 1111}))
    cli_file = tmp_path / "cli.json"
    cli_file.write_text(json.dumps({"port": 2222}))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WEBTX_CONFIG", str(env_file))
    cfg = Config.load(cli_path=str(cli_file))
    assert cfg.data["port"] == 2222


def test_default_cwd_file_used_when_no_cli_or_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WEBTX_CONFIG", raising=False)
    (tmp_path / "webtx.json").write_text(json.dumps({"host": "127.0.0.1"}))
    cfg = Config.load()
    assert cfg.data["host"] == "127.0.0.1"


def test_deep_merge_preserves_nested_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "webtx.json").write_text(json.dumps({"dsp": {"fm_deviation_hz": 3000.0}}))
    cfg = Config.load()
    assert cfg.data["dsp"]["fm_deviation_hz"] == 3000.0
    assert cfg.data["dsp"]["ssb_low_hz"] == DEFAULTS["dsp"]["ssb_low_hz"]


def test_missing_explicit_file_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError):
        Config.load(cli_path=str(tmp_path / "does_not_exist.json"))


def test_invalid_json_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(ConfigError):
        Config.load(cli_path=str(bad))


def test_non_object_json_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bad = tmp_path / "list.json"
    bad.write_text("[1, 2, 3]")
    with pytest.raises(ConfigError):
        Config.load(cli_path=str(bad))


@pytest.mark.parametrize("override,expected_fragment", [
    ({"port": 70000}, "port"),
    ({"port": "not-a-number"}, "port"),
    ({"sink": {"kind": "bogus"}}, "sink.kind"),
    ({"sink": {"fifo_samples": -1}}, "fifo_samples"),
    ({"sink": {"burst_samples": 0}}, "burst_samples"),
    ({"audio": {"sample_rate": 1}}, "sample_rate"),
    ({"audio": {"jitter_target_ms": 200, "jitter_max_ms": 50}}, "jitter_target_ms"),
    ({"rf": {"min_freq_hz": 999999999999, "max_freq_hz": 100}}, "min_freq_hz"),
    ({"rf": {"max_power": 50.0}}, "max_power"),
    ({"rf": {"default_mode": "CW"}}, "default_mode"),
    ({"rf": {"allowed_ranges": [[100, 50]]}}, "allowed_ranges"),
    ({"dsp": {"hilbert_taps": 128}}, "hilbert_taps"),
    ({"dsp": {"ssb_low_hz": 3000.0, "ssb_high_hz": 300.0}}, "ssb_low_hz"),
    ({"log": {"level": "VERBOSE"}}, "log.level"),
])
def test_validation_errors(tmp_path, monkeypatch, override, expected_fragment):
    monkeypatch.chdir(tmp_path)
    cfg_file = tmp_path / "webtx.json"
    cfg_file.write_text(json.dumps(override))
    with pytest.raises(ConfigError) as excinfo:
        Config.load(cli_path=str(cfg_file))
    assert expected_fragment in str(excinfo.value)


def test_all_errors_collected_at_once(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_file = tmp_path / "webtx.json"
    cfg_file.write_text(json.dumps({"port": -1, "rf": {"max_power": 99.0}}))
    with pytest.raises(ConfigError) as excinfo:
        Config.load(cli_path=str(cfg_file))
    msg = str(excinfo.value)
    assert "port" in msg
    assert "max_power" in msg


def test_default_json_text_round_trips():
    text = Config.default_json_text()
    data = json.loads(text)
    assert data == DEFAULTS


def test_get_helper_with_dotted_path():
    cfg = Config()
    assert cfg.get("rf", "default_mode") == "USB"
    assert cfg.get("rf", "missing_key", default="fallback") == "fallback"


def test_apply_overrides():
    cfg = Config()
    cfg.apply_overrides(host="1.2.3.4", port=1234, no_tls=True, sink_kind="null",
                         log_level="DEBUG", dry_run=True)
    assert cfg.data["host"] == "1.2.3.4"
    assert cfg.data["port"] == 1234
    assert cfg.data["tls"]["enabled"] is False
    assert cfg.data["sink"]["kind"] == "null"
    assert cfg.data["log"]["level"] == "DEBUG"
    assert cfg.data["sink"]["dry_run"] is True


def test_resolve_config_path_prefers_cli_then_env_then_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WEBTX_CONFIG", raising=False)
    assert resolve_config_path() is None
    (tmp_path / "webtx.json").write_text("{}")
    assert resolve_config_path() == "webtx.json"
