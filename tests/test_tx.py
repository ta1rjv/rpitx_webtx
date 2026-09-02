import os
import struct
import subprocess
from pathlib import Path

import numpy as np
import pytest

import webtx.tx as tx_module
from webtx.tx import IQSink, SinkError, TxConfig


def make_executable(path):
    path.write_text("#!/bin/sh\nexit 0\n")
    os.chmod(path, 0o755)


def _hide_ambient_binaries(monkeypatch, *, webtx_iq=False, sendiq=False):
    """Make os.path.isfile() report False for the real-world global
    candidate paths webtx.tx._find_webtx_iq()/_find_sendiq() check (the
    repo-relative native/ build output and /usr/local/bin installs), so
    "auto"/explicit resolution tests are hermetic regardless of whether a
    real ARM build genuinely exists on the machine running this suite -
    true on a real Raspberry Pi with native/webtx_iq and
    native/webtx-sendiq built, false by accident on every x86 dev machine
    so far. Every other path (including tmp_path fixtures) is still
    checked for real. webtx/tx.py's resolution logic itself is untouched -
    this only controls what "exists on disk" looks like to it.
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(tx_module.__file__)))
    hidden = set()
    if webtx_iq:
        hidden.add(os.path.join(repo_root, "native", "webtx_iq"))
        hidden.add("/usr/local/bin/webtx_iq")
    if sendiq:
        hidden.add(os.path.join(repo_root, "native", "webtx-sendiq"))
        hidden.add("/usr/local/bin/webtx-sendiq")
    real_isfile = os.path.isfile
    monkeypatch.setattr(
        os.path, "isfile", lambda p: False if p in hidden else real_isfile(p)
    )


class _FakeStdin:
    def __init__(self):
        self.written = bytearray()
        self.closed = False

    def write(self, data):
        self.written.extend(data)

    def flush(self):
        pass

    def close(self):
        self.closed = True

    def fileno(self):
        return -1


class _FakeStderr:
    def readline(self):
        return b""


class _FakeProc:
    def __init__(self, argv):
        self.argv = argv
        self.stdin = _FakeStdin()
        self.stderr = _FakeStderr()
        self.stdout = None
        self._returncode = None

    def poll(self):
        return self._returncode

    def terminate(self):
        self._returncode = -15

    def kill(self):
        self._returncode = -9

    def wait(self, timeout=None):
        return self._returncode


def test_null_sink_lifecycle():
    sink = IQSink(TxConfig(sink_kind="null"))
    assert not sink.is_running
    sink.start(freq_hz=14200000, sample_rate=48000, power=1.0)
    assert sink.is_running
    sink.write(np.zeros(10, dtype=np.complex64))
    stats = sink.stats()
    assert stats["kind"] == "null"
    assert stats["running"] is True
    sink.stop()
    assert not sink.is_running


def test_double_start_is_idempotent():
    sink = IQSink(TxConfig(sink_kind="null"))
    sink.start(14200000, 48000, 1.0)
    sink.start(14200000, 48000, 1.0)
    assert sink.is_running
    sink.stop()


def test_stop_without_start_is_safe():
    sink = IQSink(TxConfig(sink_kind="null"))
    sink.stop()
    assert not sink.is_running


def test_restart_after_stop_works():
    sink = IQSink(TxConfig(sink_kind="null"))
    sink.start(14200000, 48000, 1.0)
    sink.stop()
    sink.start(14200000, 48000, 1.0)
    assert sink.is_running
    sink.stop()


def test_write_without_start_raises():
    sink = IQSink(TxConfig(sink_kind="null"))
    with pytest.raises(SinkError):
        sink.write(np.zeros(10, dtype=np.complex64))


def test_power_out_of_range_raises():
    sink = IQSink(TxConfig(sink_kind="null", max_power=7.0))
    with pytest.raises(SinkError):
        sink.start(14200000, 48000, power=99.0)
    with pytest.raises(SinkError):
        sink.start(14200000, 48000, power=0.0)


def test_auto_resolution_prefers_webtx_iq_over_sendiq(tmp_path):
    rpitx_dir = tmp_path / "rpitx"
    rpitx_dir.mkdir()
    make_executable(rpitx_dir / "sendiq")
    webtx_iq_bin = tmp_path / "webtx_iq"
    make_executable(webtx_iq_bin)

    cfg = TxConfig(sink_kind="auto", rpitx_path=str(rpitx_dir), binary=str(webtx_iq_bin))
    kind, binary = IQSink(cfg)._resolve()
    assert kind == "webtx_iq"
    assert binary == str(webtx_iq_bin)


def test_auto_resolution_falls_back_to_sendiq(tmp_path, monkeypatch):
    _hide_ambient_binaries(monkeypatch, webtx_iq=True, sendiq=True)
    rpitx_dir = tmp_path / "rpitx"
    rpitx_dir.mkdir()
    make_executable(rpitx_dir / "sendiq")
    cfg = TxConfig(sink_kind="auto", rpitx_path=str(rpitx_dir), binary="")
    kind, binary = IQSink(cfg)._resolve()
    assert kind == "sendiq"
    assert binary == str(rpitx_dir / "sendiq")


def test_find_sendiq_prefers_vendored_native_build(tmp_path, monkeypatch):
    """A vendored build at native/webtx-sendiq (vendor/rpitx-src/sendiq.cpp,
    built by `make -C native` with zero external download - see
    docs/DECISIONS.md ADR-010) is preferred over a real, separate
    rpitx_path/sendiq install. The resolved kind stays "sendiq" either way -
    this is a resolution-order change only, not a new sink.kind value."""
    _hide_ambient_binaries(monkeypatch, webtx_iq=True)
    rpitx_dir = tmp_path / "rpitx"
    rpitx_dir.mkdir()
    make_executable(rpitx_dir / "sendiq")

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(tx_module.__file__)))
    vendored = os.path.join(repo_root, "native", "webtx-sendiq")
    pre_existing = os.path.exists(vendored)
    if not pre_existing:
        make_executable(Path(vendored))
    try:
        cfg = TxConfig(sink_kind="auto", rpitx_path=str(rpitx_dir), binary="")
        sink = IQSink(cfg)
        assert sink._find_sendiq() == vendored
        kind, binary = sink._resolve()
        assert kind == "sendiq"
        assert binary == vendored
    finally:
        if not pre_existing:
            os.remove(vendored)


def test_find_sendiq_falls_back_to_rpitx_path_when_no_vendored_binary(tmp_path, monkeypatch):
    """With native/webtx-sendiq and /usr/local/bin/webtx-sendiq both made to
    look absent (regardless of whether a real vendored build genuinely
    exists on the machine running this test - see _hide_ambient_binaries),
    resolution still falls back to rpitx_path/sendiq, unchanged from before
    that binary existed."""
    _hide_ambient_binaries(monkeypatch, webtx_iq=True, sendiq=True)
    rpitx_dir = tmp_path / "rpitx"
    rpitx_dir.mkdir()
    make_executable(rpitx_dir / "sendiq")

    cfg = TxConfig(sink_kind="auto", rpitx_path=str(rpitx_dir), binary="")
    sink = IQSink(cfg)
    assert sink._find_sendiq() == str(rpitx_dir / "sendiq")
    kind, binary = sink._resolve()
    assert kind == "sendiq"
    assert binary == str(rpitx_dir / "sendiq")


def test_auto_resolution_raises_when_nothing_found(tmp_path, monkeypatch):
    _hide_ambient_binaries(monkeypatch, webtx_iq=True, sendiq=True)
    cfg = TxConfig(sink_kind="auto", rpitx_path=str(tmp_path / "nope"), binary="")
    with pytest.raises(SinkError):
        IQSink(cfg)._resolve()


def test_explicit_webtx_iq_missing_raises(tmp_path, monkeypatch):
    _hide_ambient_binaries(monkeypatch, webtx_iq=True)
    cfg = TxConfig(sink_kind="webtx_iq", binary=str(tmp_path / "missing"))
    with pytest.raises(SinkError):
        IQSink(cfg)._resolve()


def test_explicit_sendiq_missing_raises(tmp_path, monkeypatch):
    _hide_ambient_binaries(monkeypatch, sendiq=True)
    cfg = TxConfig(sink_kind="sendiq", rpitx_path=str(tmp_path / "missing"))
    with pytest.raises(SinkError):
        IQSink(cfg)._resolve()


def test_webtx_iq_argv_construction(tmp_path):
    binary = tmp_path / "webtx_iq"
    make_executable(binary)
    cfg = TxConfig(sink_kind="webtx_iq", binary=str(binary), fifo_samples=2048,
                    burst_samples=512, harmonic=1)
    sink = IQSink(cfg)
    sink._freq_hz = 14200000.0
    sink._sample_rate = 48000
    sink._power = 1.5
    argv = sink._build_argv("webtx_iq", str(binary))
    assert argv == [
        str(binary),
        "-f", "14200000.0",
        "-s", "48000",
        "-p", "1.5",
        "-h", "1",
        "-b", "512",
        "-F", "2048",
        "--ptt-gate",
        "-v",
    ]


def test_sendiq_argv_construction(tmp_path):
    binary = tmp_path / "sendiq"
    make_executable(binary)
    cfg = TxConfig(sink_kind="sendiq", rpitx_path=str(tmp_path))
    sink = IQSink(cfg)
    sink._freq_hz = 7100000.0
    sink._sample_rate = 44100
    sink._power = 7.0
    argv = sink._build_argv("sendiq", str(binary))
    assert argv == [
        str(binary),
        "-i", "/dev/stdin",
        "-f", "7100000.0",
        "-s", "44100",
        "-t", "float",
        "-p", "7.0",
    ]


def test_start_uses_argv_list_no_shell_no_preexec_fn(tmp_path, monkeypatch):
    binary = tmp_path / "webtx_iq"
    make_executable(binary)
    cfg = TxConfig(sink_kind="webtx_iq", binary=str(binary))
    sink = IQSink(cfg)
    captured = {}

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return _FakeProc(argv)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(os, "geteuid", lambda: 0)

    sink.start(14200000, 48000, 1.0)
    assert isinstance(captured["argv"], list)
    assert captured["kwargs"].get("shell", False) is False
    assert captured["kwargs"].get("start_new_session") is True
    assert "preexec_fn" not in captured["kwargs"]
    sink.stop()


def test_non_root_refuses_real_sink(tmp_path, monkeypatch):
    binary = tmp_path / "webtx_iq"
    make_executable(binary)
    cfg = TxConfig(sink_kind="webtx_iq", binary=str(binary))
    sink = IQSink(cfg)
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    with pytest.raises(SinkError):
        sink.start(14200000, 48000, 1.0)


def test_write_produces_correct_interleaved_bytes(tmp_path, monkeypatch):
    binary = tmp_path / "webtx_iq"
    make_executable(binary)
    cfg = TxConfig(sink_kind="webtx_iq", binary=str(binary))
    sink = IQSink(cfg)

    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: _FakeProc(argv))
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    sink.start(14200000, 48000, 1.0)

    iq = np.array([1.0 + 0.5j, -0.25 - 0.75j], dtype=np.complex64)
    sink.write(iq)
    expected = struct.pack("<4f", 1.0, 0.5, -0.25, -0.75)
    assert bytes(sink._proc.stdin.written) == expected
    sink.stop()


def test_set_frequency_returns_false():
    sink = IQSink(TxConfig(sink_kind="null"))
    sink.start(14200000, 48000, 1.0)
    assert sink.set_frequency(7100000) is False
    sink.stop()


def test_stats_reports_kind_and_running_false_initially():
    sink = IQSink(TxConfig(sink_kind="null"))
    stats = sink.stats()
    assert stats["running"] is False
