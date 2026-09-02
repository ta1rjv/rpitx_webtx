"""Transmitter subprocess management (the IQ sink).

Wraps either native/webtx_iq (preferred, low-latency) or stock rpitx `sendiq`
as a child process fed complex IQ samples on stdin, or a "null" sink that
discards IQ for testing on machines with no RF hardware.

Safety rules enforced here (docs/DECISIONS.md ADR-006, ADR-008):
  - subprocess is always started with an argv list; shell=True is never used
    and no command is ever built by string interpolation.
  - power and sink selection are validated before a process is started.
  - stop() always fully reaps the child (SIGTERM, then SIGKILL on timeout) so
    a restart is always possible and no process can be left holding the
    carrier on air.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

_logger = logging.getLogger("webtx.tx")

_STAT_RE = re.compile(rb"STAT depth=(\d+) under=(\d+)")


class SinkError(RuntimeError):
    """Raised for any sink resolution, start, or write failure."""


@dataclass
class TxConfig:
    rpitx_path: str = "/opt/rpitx"
    sink_kind: str = "auto"  # auto | webtx_iq | sendiq | null
    binary: str = ""
    fifo_samples: int = 2048
    burst_samples: int = 512
    harmonic: int = 1
    ppm: float = 0.0
    dry_run: bool = False
    max_power: float = 7.0

    @classmethod
    def from_app_config(cls, cfg) -> "TxConfig":
        """Build a TxConfig from a webtx.config.Config (duck-typed on .data)."""
        sink = cfg.data.get("sink", {})
        rf = cfg.data.get("rf", {})
        kind = "null" if sink.get("dry_run") else sink.get("kind", "auto")
        return cls(
            rpitx_path=cfg.data.get("rpitx_path", "/opt/rpitx"),
            sink_kind=kind,
            binary=sink.get("binary", ""),
            fifo_samples=int(sink.get("fifo_samples", 2048)),
            burst_samples=int(sink.get("burst_samples", 512)),
            harmonic=int(sink.get("harmonic", 1)),
            ppm=float(sink.get("ppm", 0.0)),
            dry_run=bool(sink.get("dry_run", False)),
            max_power=float(rf.get("max_power", 7.0)),
        )


class IQSink:
    """Manages the lifetime of the transmitter child process."""

    def __init__(self, cfg: TxConfig):
        self._cfg = cfg
        self._proc: Optional[subprocess.Popen] = None
        self._resolved_kind: Optional[str] = None
        self._resolved_binary: Optional[str] = None
        self._sample_rate = 0
        self._freq_hz = 0.0
        self._power = 0.0
        self._active = False  # used for the "null" sink, which has no process
        self._lock = threading.RLock()
        self._stderr_thread: Optional[threading.Thread] = None
        self._stop_stderr = threading.Event()
        self._last_depth_samples = 0
        self._underrun_count = 0
        self._bytes_written = 0
        self._start_time = 0.0

    # -- resolution ---------------------------------------------------

    def _find_webtx_iq(self) -> Optional[str]:
        candidates = []
        if self._cfg.binary:
            candidates.append(self._cfg.binary)
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidates.append(os.path.join(repo_root, "native", "webtx_iq"))
        candidates.append("/usr/local/bin/webtx_iq")
        for c in candidates:
            if c and os.path.isfile(c) and os.access(c, os.X_OK):
                return c
        return None

    def _find_sendiq(self) -> Optional[str]:
        # Preferred over a real separate rpitx install: a vendored build of
        # rpitx's own sendiq.cpp (vendor/rpitx-src/sendiq.cpp, low-latency
        # patched - see vendor/NOTICE.md and docs/DECISIONS.md ADR-010),
        # built by `make -C native` with zero external download, then the
        # same binary installed system-wide by `make -C native install`.
        # Either one still resolves to sink kind "sendiq" (see _resolve) -
        # this only changes which binary path is used, not the kind.
        candidates = []
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidates.append(os.path.join(repo_root, "native", "webtx-sendiq"))
        candidates.append("/usr/local/bin/webtx-sendiq")
        candidates.append(os.path.join(self._cfg.rpitx_path, "sendiq"))
        for c in candidates:
            if c and os.path.isfile(c) and os.access(c, os.X_OK):
                return c
        return None

    def _resolve(self):
        kind = self._cfg.sink_kind
        if kind == "null":
            return "null", None
        if kind == "webtx_iq":
            binary = self._find_webtx_iq()
            if not binary:
                raise SinkError(
                    "sink.kind is 'webtx_iq' but no webtx_iq binary was found; "
                    "build native/webtx_iq (see native/README.md) or set sink.binary"
                )
            return "webtx_iq", binary
        if kind == "sendiq":
            binary = self._find_sendiq()
            if not binary:
                raise SinkError(
                    f"sink.kind is 'sendiq' but {self._cfg.rpitx_path}/sendiq was not "
                    "found; check rpitx_path in the configuration"
                )
            return "sendiq", binary
        # auto: prefer the low-latency native sink, then stock sendiq.
        binary = self._find_webtx_iq()
        if binary:
            return "webtx_iq", binary
        binary = self._find_sendiq()
        if binary:
            return "sendiq", binary
        raise SinkError(
            "sink.kind is 'auto' but neither native/webtx_iq nor "
            f"{self._cfg.rpitx_path}/sendiq could be found. Build native/webtx_iq "
            "(recommended, see native/README.md), install rpitx, or set sink.kind "
            "to 'null' for a dry run with no RF output."
        )

    def _build_argv(self, kind: str, binary: str) -> list:
        if kind == "webtx_iq":
            return [
                binary,
                "-f", str(self._freq_hz),
                "-s", str(self._sample_rate),
                "-p", str(self._power),
                "-h", str(self._cfg.harmonic),
                "-b", str(self._cfg.burst_samples),
                "-F", str(self._cfg.fifo_samples),
                "--ptt-gate",
                "-v",
            ]
        if kind == "sendiq":
            return [
                binary,
                "-i", "/dev/stdin",
                "-f", str(self._freq_hz),
                "-s", str(self._sample_rate),
                "-t", "float",
                "-p", str(self._power),
            ]
        raise SinkError(f"unknown resolved sink kind: {kind}")

    # -- lifecycle ------------------------------------------------------

    @property
    def is_running(self) -> bool:
        with self._lock:
            if self._resolved_kind == "null":
                return self._active
            return self._proc is not None and self._proc.poll() is None

    def start(self, freq_hz: float, sample_rate: int, power: float) -> None:
        with self._lock:
            if self.is_running:
                return  # idempotent: PTT held down / duplicate start_tx
            if not (0 < power <= self._cfg.max_power):
                raise SinkError(f"power {power} out of range (0, {self._cfg.max_power}]")
            if sample_rate <= 0:
                raise SinkError("sample_rate must be positive")

            kind, binary = self._resolve()
            self._resolved_kind = kind
            self._resolved_binary = binary
            self._sample_rate = int(sample_rate)
            self._freq_hz = float(freq_hz)
            self._power = float(power)
            self._underrun_count = 0
            self._last_depth_samples = 0
            self._bytes_written = 0
            self._start_time = time.monotonic()

            if kind == "null":
                self._active = True
                return

            if os.geteuid() != 0:
                raise SinkError(
                    "webtx must run as root to access /dev/mem for GPIO/DMA "
                    "transmission (run under systemd as root, or with sudo). "
                    "Refusing to start the RF sink."
                )

            argv = self._build_argv(kind, binary)
            _logger.info("starting sink: %s", " ".join(argv))
            try:
                self._proc = subprocess.Popen(
                    argv,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    start_new_session=True,
                )
            except OSError as exc:
                self._proc = None
                raise SinkError(f"failed to start sink {argv[0]}: {exc}") from exc

            self._shrink_pipe_buffer()
            self._stop_stderr.clear()
            self._stderr_thread = threading.Thread(
                target=self._read_stderr, args=(self._proc,), daemon=True
            )
            self._stderr_thread.start()

    def _shrink_pipe_buffer(self) -> None:
        """Best-effort: shrink the stdin pipe to slightly more than one burst.

        Without this, Linux's default 64 KB pipe buffer lets Python's write()
        queue several bursts (~170 ms at the default burst size) before it
        ever blocks, hiding that latency from the caller and defeating the
        design goal of having the sink's own pacing set the clock. Not fatal
        if unsupported (non-Linux, insufficient privilege): the write() path
        still works, it just has looser backpressure.
        """
        if self._proc is None or self._proc.stdin is None:
            return
        try:
            import fcntl
            setpipe_sz = getattr(fcntl, "F_SETPIPE_SZ", 1031)
            target = max(4096, self._cfg.burst_samples * 8 * 2)
            fcntl.fcntl(self._proc.stdin.fileno(), setpipe_sz, target)
        except (ImportError, AttributeError, OSError, ValueError):
            pass

    def _read_stderr(self, proc: subprocess.Popen) -> None:
        try:
            if proc.stderr is None:
                return
            for line in iter(proc.stderr.readline, b""):
                if self._stop_stderr.is_set():
                    break
                match = _STAT_RE.search(line)
                if match:
                    with self._lock:
                        self._last_depth_samples = int(match.group(1))
                        self._underrun_count = int(match.group(2))
                    continue
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    _logger.info("sink[%s]: %s", self._resolved_kind, text)
        except (OSError, ValueError):
            pass

    def write(self, iq: np.ndarray) -> None:
        """Write complex64 IQ samples as interleaved little-endian float32."""
        if iq.dtype != np.complex64:
            iq = iq.astype(np.complex64)
        n = len(iq)
        interleaved = np.empty(2 * n, dtype="<f4")
        interleaved[0::2] = iq.real
        interleaved[1::2] = iq.imag
        payload = interleaved.tobytes()

        with self._lock:
            kind = self._resolved_kind
            sample_rate = self._sample_rate or 48000
            proc = self._proc
            active = self._active if kind == "null" else proc is not None

        if not active:
            raise SinkError("write() called while sink is not running")

        if kind == "null":
            if sample_rate > 0 and n > 0:
                time.sleep(n / sample_rate)
            with self._lock:
                self._bytes_written += len(payload)
            return

        try:
            proc.stdin.write(payload)
            proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise SinkError(f"sink pipe write failed: {exc}") from exc
        with self._lock:
            self._bytes_written += len(payload)

    def set_frequency(self, freq_hz: float) -> bool:
        """Attempt a live retune without restarting the sink.

        Always returns False in this version: neither webtx_iq nor stock
        sendiq are driven through a retune IPC channel here (sendiq's shared-
        memory command path is not wired up on the Python side). Callers must
        restart the sink to change frequency, which is a fully supported path
        (see webtx/server.py) and paid for only when the operator retunes
        while keyed, not on every parameter change.
        """
        return False

    def stop(self, timeout: float = 2.0) -> None:
        with self._lock:
            proc = self._proc
            self._proc = None
            was_null = self._resolved_kind == "null"
            self._active = False
        self._stop_stderr.set()
        if was_null or proc is None:
            return
        try:
            if proc.stdin is not None:
                proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        try:
            proc.terminate()
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                _logger.error("sink process did not die even after SIGKILL")
        except OSError:
            pass
        if self._stderr_thread is not None:
            self._stderr_thread.join(timeout=1.0)
            self._stderr_thread = None
        _logger.info("sink stopped")

    def stats(self) -> dict:
        with self._lock:
            depth_ms = (
                1000.0 * self._last_depth_samples / self._sample_rate
                if self._sample_rate else 0.0
            )
            running = self.is_running
            tx_seconds = (time.monotonic() - self._start_time) if running else 0.0
            return {
                "kind": self._resolved_kind or self._cfg.sink_kind,
                "running": running,
                "depth_samples": self._last_depth_samples,
                "depth_ms": depth_ms,
                "underruns": self._underrun_count,
                "bytes_written": self._bytes_written,
                "tx_seconds": tx_seconds,
            }
