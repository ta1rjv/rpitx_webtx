"""aiohttp application: WebSocket protocol, audio worker thread, HTTP routes.

Replaces Flask + flask-socketio + the Werkzeug development server (ADR-002)
with aiohttp and a raw binary WebSocket at /ws. One dedicated audio worker
thread owns the DSP modulator and the IQ sink; the asyncio event loop only
handles network I/O and hands audio off to the worker through a JitterBuffer,
so a slow or bursty network never directly stalls the real-time audio path.

The wire protocol is documented in the project contract and in README.md.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import os
import struct
import threading
import time
from collections import deque

import numpy as np
from aiohttp import web

from . import __version__
from .config import Config
from .dsp import MODES, ModConfig, Modulator, make_silence_iq
from .jitter import JitterBuffer
from .metrics import LatencyTracker, RateMeter, Stage
from .tx import IQSink, SinkError, TxConfig

logger = logging.getLogger("webtx.server")

BANDS = [
    {"name": "160m", "freq_hz": 1900000},
    {"name": "80m", "freq_hz": 3700000},
    {"name": "40m", "freq_hz": 7100000},
    {"name": "30m", "freq_hz": 10120000},
    {"name": "20m", "freq_hz": 14200000},
    {"name": "17m", "freq_hz": 18100000},
    {"name": "15m", "freq_hz": 21200000},
    {"name": "12m", "freq_hz": 24940000},
    {"name": "10m", "freq_hz": 28400000},
    {"name": "6m", "freq_hz": 50150000},
    {"name": "2m", "freq_hz": 145500000},
    {"name": "70cm", "freq_hz": 433500000},
]

_AUDIO_TIMEOUT_S = 0.5
_HEADER = struct.Struct("<Id")  # uint32 seq, float64 client_ts_ms


class _Client:
    _counter = 0

    def __init__(self, ws):
        _Client._counter += 1
        self.id = _Client._counter
        self.ws = ws


class WebTXApp:
    """Holds all server-side state for one running webtx instance."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        audio_cfg = cfg.data["audio"]
        rf_cfg = cfg.data["rf"]

        self.sample_rate = int(audio_cfg["sample_rate"])
        self.frame_ms = float(audio_cfg["frame_ms"])
        self.frame_samples = max(1, int(round(self.sample_rate * self.frame_ms / 1000.0)))

        self.mode = rf_cfg["default_mode"]
        self.freq_hz = float(rf_cfg["default_freq_hz"])
        self.mic_gain = 1.0
        self.tx_power = min(1.0, float(rf_cfg["max_power"]))

        target_ms = float(audio_cfg["jitter_target_ms"])
        max_ms = float(audio_cfg["jitter_max_ms"])
        min_ms = max(self.frame_ms, target_ms / 4.0)
        self.jitter = JitterBuffer(self.sample_rate, target_ms=target_ms, max_ms=max_ms, min_ms=min_ms)

        self._tx_cfg = TxConfig.from_app_config(cfg)
        self.sink = IQSink(self._tx_cfg)
        self.latency = LatencyTracker()
        self.rate_meter = RateMeter()

        self.modulator: Modulator = None
        self._set_mode(self.mode)

        self.clients = set()
        self.tx_owner = None

        self._lock = threading.RLock()
        self._tx_active_event = threading.Event()
        self._worker_stop = threading.Event()
        self._worker_thread = None
        self._loop = None

        self._offset_window = deque(maxlen=500)
        self._last_audio_push_time = 0.0
        self._audio_rms = 0.0
        self._last_cpu_sample = None
        self._start_wall_time = time.time()
        self._dropped_frames = 0

    # -- DSP / mode management ------------------------------------------

    def _make_dsp_config(self) -> ModConfig:
        d = self.cfg.data["dsp"]
        return ModConfig(
            ssb_low_hz=d["ssb_low_hz"],
            ssb_high_hz=d["ssb_high_hz"],
            fm_deviation_hz=d["fm_deviation_hz"],
            am_modulation_index=d["am_modulation_index"],
            am_carrier_level=d["am_carrier_level"],
            audio_hpf_hz=d["audio_hpf_hz"],
            hilbert_taps=d["hilbert_taps"],
            limiter_enabled=d["limiter_enabled"],
            agc_enabled=d["agc_enabled"],
            agc_target=d["agc_target"],
            agc_attack_ms=d["agc_attack_ms"],
            agc_release_ms=d["agc_release_ms"],
        )

    def _set_mode(self, mode: str) -> None:
        """Swap the modulator for a new mode. Never touches the sink: mode is
        purely a DSP-layer concept here since we generate IQ ourselves (unlike
        the old csdr pipeline, the transmitter process does not know or care
        about mode)."""
        if mode not in MODES:
            return
        new_mod = Modulator(mode, self.sample_rate, self._make_dsp_config())
        new_mod.set_gain(self.mic_gain)
        self.modulator = new_mod
        self.mode = mode

    # -- validation -------------------------------------------------------

    def _validate_params(self, freq_hz, mode, mic_gain, tx_power) -> list:
        errors = []
        rf = self.cfg.data["rf"]
        if freq_hz is not None:
            if not (rf["min_freq_hz"] <= freq_hz <= rf["max_freq_hz"]):
                errors.append(f"freq_hz out of range [{rf['min_freq_hz']}, {rf['max_freq_hz']}]")
            allowed = rf.get("allowed_ranges") or []
            if allowed and not any(lo <= freq_hz <= hi for lo, hi in allowed):
                errors.append("freq_hz is outside the configured allowed_ranges")
        if mode is not None and mode not in MODES:
            errors.append(f"mode must be one of {MODES}")
        if mic_gain is not None and not (0.0 <= mic_gain <= 4.0):
            errors.append("mic_gain must be between 0.0 and 4.0")
        if tx_power is not None and not (0.0 < tx_power <= rf["max_power"]):
            errors.append(f"tx_power must be between 0 (exclusive) and {rf['max_power']}")
        return errors

    # -- messaging ----------------------------------------------------------

    async def _send(self, client: _Client, msg: dict) -> None:
        try:
            await client.ws.send_json(msg)
        except (ConnectionResetError, RuntimeError):
            pass

    async def broadcast(self, msg: dict) -> None:
        dead = []
        for client in list(self.clients):
            try:
                await client.ws.send_json(msg)
            except (ConnectionResetError, RuntimeError):
                dead.append(client)
        for d in dead:
            self.clients.discard(d)

    def build_state_message(self) -> dict:
        return {
            "type": "state",
            "tx": self.tx_owner is not None,
            "keyed": self.tx_owner is not None,
            "mode": self.mode,
            "freq_hz": self.freq_hz,
            "mic_gain": self.mic_gain,
            "tx_power": self.tx_power,
            "sink": "running" if self.sink.is_running else "stopped",
            "sample_rate": self.sample_rate,
        }

    async def broadcast_state(self) -> None:
        await self.broadcast(self.build_state_message())

    def _update_total_latency(self) -> None:
        snap = self.latency.snapshot()
        total_ms = (snap["net"]["last"] + snap["jitter"]["last"]
                    + snap["dsp"]["last"] + snap["sink"]["last"])
        self.latency.observe(Stage.TOTAL, total_ms)

    def build_metrics_message(self) -> dict:
        snap = self.latency.snapshot()
        jitter_stats = self.jitter.stats
        sink_stats = self.sink.stats()
        fps, bps = self.rate_meter.rate()
        return {
            "type": "metrics",
            "latency": {k: snap[k] for k in ("net", "jitter", "dsp", "sink", "total")},
            "jitter": jitter_stats,
            "iq_peak": self.modulator.peak_iq() if self.modulator else 0.0,
            "audio_rms": self._audio_rms,
            "cpu_percent": self._cpu_percent(),
            "frames_per_s": fps,
            "bytes_per_s": bps,
            "sink": sink_stats,
            "tx_seconds": sink_stats.get("tx_seconds", 0.0),
            "dropped_frames": self._dropped_frames,
        }

    def _cpu_percent(self) -> float:
        now = time.monotonic()
        times = os.times()
        proc_cpu = times.user + times.system
        if self._last_cpu_sample is None:
            self._last_cpu_sample = (now, proc_cpu)
            return 0.0
        last_wall, last_cpu = self._last_cpu_sample
        wall_delta = now - last_wall
        self._last_cpu_sample = (now, proc_cpu)
        if wall_delta <= 0:
            return 0.0
        cpu_count = os.cpu_count() or 1
        return max(0.0, min(100.0 * (proc_cpu - last_cpu) / wall_delta, 100.0 * cpu_count))

    # -- TX lifecycle -----------------------------------------------------

    def _stop_tx_internal(self, reason: str) -> None:
        with self._lock:
            self.tx_owner = None
        self._tx_active_event.clear()
        try:
            self.sink.stop()
        except Exception:
            logger.exception("error stopping sink")
        self.jitter.reset()
        logger.info("TX stopped: %s", reason)

    def _request_stop_tx_threadsafe(self, reason: str) -> None:
        self._stop_tx_internal(reason)
        if self._loop is not None and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast_state(), self._loop)

    async def _handle_hello(self, client: _Client, data: dict) -> None:
        await self._send(client, {
            "type": "hello_ack",
            "sample_rate": self.sample_rate,
            "frame_samples": self.frame_samples,
            "modes": list(MODES),
            "bands": BANDS,
            "server_version": __version__,
            "sink_kind": self._tx_cfg.sink_kind,
            "max_freq_hz": self.cfg.data["rf"]["max_freq_hz"],
            "min_freq_hz": self.cfg.data["rf"]["min_freq_hz"],
        })
        await self._send(client, self.build_state_message())

    async def _handle_start_tx(self, client: _Client, data: dict) -> None:
        if self.tx_owner is not None and self.tx_owner is not client:
            await self._send(client, {
                "type": "error", "code": "tx_busy",
                "message": "Another operator is currently transmitting.", "fatal": False,
            })
            return

        try:
            freq_hz = float(data.get("freq_hz", self.freq_hz))
            mode = data.get("mode", self.mode)
            mic_gain = float(data.get("mic_gain", self.mic_gain))
            tx_power = float(data.get("tx_power", self.tx_power))
        except (TypeError, ValueError):
            await self._send(client, {
                "type": "error", "code": "invalid_params",
                "message": "freq_hz, mic_gain and tx_power must be numeric", "fatal": False,
            })
            return

        errors = self._validate_params(freq_hz, mode, mic_gain, tx_power)
        if errors:
            await self._send(client, {
                "type": "error", "code": "invalid_params",
                "message": "; ".join(errors), "fatal": False,
            })
            return

        with self._lock:
            self.freq_hz = freq_hz
            if mode != self.mode:
                self._set_mode(mode)
            self.mic_gain = mic_gain
            self.modulator.set_gain(self.mic_gain)
            self.tx_power = tx_power
            self.jitter.reset()
            self._last_audio_push_time = time.monotonic()

        try:
            self.sink.start(freq_hz=self.freq_hz, sample_rate=self.sample_rate, power=self.tx_power)
        except SinkError as exc:
            await self._send(client, {
                "type": "error", "code": "sink_error", "message": str(exc), "fatal": True,
            })
            return

        self.tx_owner = client
        self._tx_active_event.set()
        logger.info("TX started by client %s: %.0f Hz %s", client.id, self.freq_hz, self.mode)
        await self.broadcast_state()

    async def _handle_stop_tx(self, client: _Client, data: dict) -> None:
        if self.tx_owner is not client:
            return
        self._stop_tx_internal("operator stop")
        await self.broadcast_state()

    async def _handle_set_params(self, client: _Client, data: dict) -> None:
        with self._lock:
            if "mic_gain" in data:
                try:
                    mg = float(data["mic_gain"])
                except (TypeError, ValueError):
                    await self._send(client, {"type": "error", "code": "invalid_params",
                                               "message": "mic_gain must be numeric", "fatal": False})
                    return
                if not (0.0 <= mg <= 4.0):
                    await self._send(client, {"type": "error", "code": "invalid_params",
                                               "message": "mic_gain must be between 0.0 and 4.0",
                                               "fatal": False})
                    return
                self.mic_gain = mg
                self.modulator.set_gain(mg)

            if "tx_power" in data:
                try:
                    tp = float(data["tx_power"])
                except (TypeError, ValueError):
                    await self._send(client, {"type": "error", "code": "invalid_params",
                                               "message": "tx_power must be numeric", "fatal": False})
                    return
                max_power = self.cfg.data["rf"]["max_power"]
                if not (0.0 < tp <= max_power):
                    await self._send(client, {"type": "error", "code": "invalid_params",
                                               "message": f"tx_power must be between 0 (exclusive) and {max_power}",
                                               "fatal": False})
                    return
                # Never restarts the sink here: takes effect on the next start().
                self.tx_power = tp

            if "mode" in data:
                mode = data["mode"]
                if mode not in MODES:
                    await self._send(client, {"type": "error", "code": "invalid_params",
                                               "message": f"mode must be one of {MODES}", "fatal": False})
                    return
                if mode != self.mode:
                    self._set_mode(mode)

            if "freq_hz" in data:
                try:
                    new_freq = float(data["freq_hz"])
                except (TypeError, ValueError):
                    await self._send(client, {"type": "error", "code": "invalid_params",
                                               "message": "freq_hz must be numeric", "fatal": False})
                    return
                errs = self._validate_params(new_freq, None, None, None)
                if errs:
                    await self._send(client, {"type": "error", "code": "invalid_params",
                                               "message": "; ".join(errs), "fatal": False})
                    return
                self.freq_hz = new_freq
                if self.sink.is_running and not self.sink.set_frequency(new_freq):
                    await self._send(client, {
                        "type": "log", "level": "info",
                        "message": "Retuning: brief transmit gap while the sink restarts.",
                    })
                    self.sink.stop()
                    try:
                        self.sink.start(freq_hz=new_freq, sample_rate=self.sample_rate,
                                         power=self.tx_power)
                    except SinkError as exc:
                        self.tx_owner = None
                        self._tx_active_event.clear()
                        await self._send(client, {"type": "error", "code": "sink_error",
                                                   "message": str(exc), "fatal": True})
                        await self.broadcast_state()
                        return

        await self.broadcast_state()

    async def _handle_ping(self, client: _Client, data: dict) -> None:
        await self._send(client, {"type": "pong", "t": data.get("t"), "server_ts_ms": time.time() * 1000.0})

    _HANDLERS = ("hello", "start_tx", "stop_tx", "set_params", "ping")

    async def handle_text(self, client: _Client, raw) -> None:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            await self._send(client, {"type": "error", "code": "bad_json",
                                       "message": "malformed message", "fatal": False})
            return
        if not isinstance(data, dict):
            await self._send(client, {"type": "error", "code": "bad_json",
                                       "message": "message must be a JSON object", "fatal": False})
            return
        msg_type = data.get("type")
        dispatch = {
            "hello": self._handle_hello,
            "start_tx": self._handle_start_tx,
            "stop_tx": self._handle_stop_tx,
            "set_params": self._handle_set_params,
            "ping": self._handle_ping,
        }
        handler = dispatch.get(msg_type)
        if handler is None:
            await self._send(client, {"type": "error", "code": "unknown_type",
                                       "message": f"unknown message type {msg_type!r}", "fatal": False})
            return
        await handler(client, data)

    def handle_audio_frame(self, client: _Client, data: bytes) -> None:
        if self.tx_owner is not client:
            return
        if len(data) < _HEADER.size:
            return
        try:
            seq, client_ts_ms = _HEADER.unpack_from(data, 0)
        except struct.error:
            return
        pcm = np.frombuffer(data, dtype="<i2", offset=_HEADER.size)
        if pcm.size == 0:
            return
        audio = pcm.astype(np.float32) / 32768.0

        server_recv_ms = time.time() * 1000.0
        offset = server_recv_ms - client_ts_ms
        self._offset_window.append(offset)
        baseline = min(self._offset_window)
        net_latency_ms = max(0.0, offset - baseline)
        self.latency.observe(Stage.NET, net_latency_ms)

        rms = float(np.sqrt(np.mean(np.square(audio)))) if audio.size else 0.0
        alpha = 0.3
        self._audio_rms = (1 - alpha) * self._audio_rms + alpha * rms

        self._last_audio_push_time = time.monotonic()
        self.rate_meter.mark(len(data))
        self.jitter.push(audio)

    # -- audio worker thread ------------------------------------------------

    def _audio_worker(self) -> None:
        frame_samples = self.frame_samples
        frame_interval = frame_samples / self.sample_rate
        next_deadline = time.monotonic()
        try:
            while not self._worker_stop.is_set():
                if not self._tx_active_event.wait(timeout=0.5):
                    next_deadline = time.monotonic()
                    continue
                if self._worker_stop.is_set():
                    break

                now = time.monotonic()
                if self.tx_owner is not None and now - self._last_audio_push_time > _AUDIO_TIMEOUT_S:
                    logger.warning("no audio for %.0f ms while keyed; stopping TX", _AUDIO_TIMEOUT_S * 1000)
                    self._request_stop_tx_threadsafe("audio timeout")
                    next_deadline = time.monotonic()
                    continue

                audio, _underrun = self.jitter.pop(frame_samples)
                with self._lock:
                    modulator = self.modulator

                t_dsp0 = time.monotonic()
                try:
                    iq = modulator.process(audio)
                except Exception:
                    logger.exception("modulator error; substituting silence")
                    iq = make_silence_iq(frame_samples)
                dsp_ms = (time.monotonic() - t_dsp0) * 1000.0

                if not self._tx_active_event.is_set():
                    # A stop was already requested/completed (e.g. operator
                    # released PTT) while we were doing the jitter/DSP work
                    # above. Writing now would just race IQSink.stop() and
                    # raise SinkError for a completely expected reason, so
                    # skip the write silently instead of treating it as a
                    # failure.
                    next_deadline = time.monotonic()
                    continue

                try:
                    self.sink.write(iq)
                except SinkError as exc:
                    if self._tx_active_event.is_set():
                        logger.error("sink write failed: %s", exc)
                        self._request_stop_tx_threadsafe(f"sink error: {exc}")
                    # else: the event was cleared in the vanishingly small
                    # window between the check above and this write() call -
                    # same expected race as above, not a genuine failure.
                    next_deadline = time.monotonic()
                    continue

                jitter_stats = self.jitter.stats
                sink_stats = self.sink.stats()
                self.latency.observe(Stage.JITTER, jitter_stats["depth_ms"])
                self.latency.observe(Stage.DSP, dsp_ms)
                sink_depth_ms = sink_stats["depth_ms"]
                if not sink_depth_ms:
                    # Stock sendiq does not report FIFO depth; fall back to the
                    # configured steady-state estimate (see docs/LATENCY.md).
                    sink_depth_ms = 1000.0 * self._tx_cfg.fifo_samples * 0.75 / self.sample_rate
                self.latency.observe(Stage.SINK, sink_depth_ms)

                next_deadline += frame_interval
                sleep_for = next_deadline - time.monotonic()
                if sleep_for > 0:
                    time.sleep(sleep_for)
                else:
                    next_deadline = time.monotonic()
        except Exception:
            logger.exception("audio worker crashed; forcing TX off")
        finally:
            if self.tx_owner is not None:
                self._request_stop_tx_threadsafe("worker thread exiting")

    async def _metrics_broadcaster(self) -> None:
        try:
            while True:
                await asyncio.sleep(0.5)
                self._update_total_latency()
                await self.broadcast(self.build_metrics_message())
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("metrics broadcaster crashed")


# -- HTTP / WebSocket routing --------------------------------------------------

WEBTX_KEY = web.AppKey("webtx", WebTXApp)
METRICS_TASK_KEY = web.AppKey("metrics_task", asyncio.Task)


async def _index_handler(request: web.Request) -> web.StreamResponse:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "index.html")
    return web.FileResponse(path)


async def _health_handler(request: web.Request) -> web.Response:
    app: WebTXApp = request.app[WEBTX_KEY]
    return web.json_response({
        "ok": True,
        "version": __version__,
        "uptime_s": time.time() - app._start_wall_time,
        "sink_kind": app._tx_cfg.sink_kind,
    })


async def _metrics_handler(request: web.Request) -> web.Response:
    app: WebTXApp = request.app[WEBTX_KEY]
    return web.json_response(app.build_metrics_message())


async def _ws_handler(request: web.Request) -> web.WebSocketResponse:
    app: WebTXApp = request.app[WEBTX_KEY]
    ws = web.WebSocketResponse(heartbeat=30.0)
    await ws.prepare(request)
    client = _Client(ws)
    app.clients.add(client)
    logger.info("client connected: %s", client.id)
    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                await app.handle_text(client, msg.data)
            elif msg.type == web.WSMsgType.BINARY:
                app.handle_audio_frame(client, msg.data)
            elif msg.type == web.WSMsgType.ERROR:
                logger.warning("websocket error for client %s: %s", client.id, ws.exception())
    finally:
        app.clients.discard(client)
        if app.tx_owner is client:
            app._stop_tx_internal("client disconnected")
            await app.broadcast_state()
        logger.info("client disconnected: %s", client.id)
    return ws


async def _on_startup(app: web.Application) -> None:
    webtx_app: WebTXApp = app[WEBTX_KEY]
    webtx_app._loop = asyncio.get_running_loop()
    webtx_app._worker_thread = threading.Thread(
        target=webtx_app._audio_worker, daemon=True, name="webtx-audio"
    )
    webtx_app._worker_thread.start()
    app[METRICS_TASK_KEY] = asyncio.create_task(webtx_app._metrics_broadcaster())
    logger.info(
        "webtx server ready: sample_rate=%d frame_samples=%d sink.kind=%s",
        webtx_app.sample_rate, webtx_app.frame_samples, webtx_app._tx_cfg.sink_kind,
    )


async def _on_cleanup(app: web.Application) -> None:
    webtx_app: WebTXApp = app[WEBTX_KEY]
    task = app.get(METRICS_TASK_KEY)
    if task:
        task.cancel()
    webtx_app._worker_stop.set()
    webtx_app._tx_active_event.set()
    if webtx_app._worker_thread is not None:
        webtx_app._worker_thread.join(timeout=2.0)
    try:
        webtx_app.sink.stop()
    except Exception:
        logger.exception("error stopping sink during cleanup")


def _atexit_stop_sink(webtx_app: WebTXApp) -> None:
    try:
        webtx_app.sink.stop()
    except Exception:
        pass


def create_app(cfg: Config) -> web.Application:
    app = web.Application(client_max_size=1024 * 1024)
    webtx_app = WebTXApp(cfg)
    app[WEBTX_KEY] = webtx_app

    app.router.add_get("/", _index_handler)
    app.router.add_get("/api/health", _health_handler)
    app.router.add_get("/api/metrics", _metrics_handler)
    app.router.add_get("/ws", _ws_handler)
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
    app.router.add_static("/static/", static_dir, show_index=False)

    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    atexit.register(_atexit_stop_sink, webtx_app)
    return app
