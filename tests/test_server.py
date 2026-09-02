import asyncio
import logging
import struct
import threading

import numpy as np
from aiohttp.test_utils import TestClient, TestServer

from webtx.config import Config
from webtx.server import create_app, WEBTX_KEY
from webtx.tx import SinkError

_HEADER = struct.Struct("<Id")


def _make_config() -> Config:
    cfg = Config()
    cfg.data["sink"]["kind"] = "null"
    cfg.data["tls"]["enabled"] = False
    cfg.validate()
    return cfg


def _make_audio_frame(seq: int, client_ts_ms: float, samples: np.ndarray) -> bytes:
    pcm = np.clip(samples * 32767.0, -32768, 32767).astype("<i2")
    return _HEADER.pack(seq, client_ts_ms) + pcm.tobytes()


def run_scenario(scenario) -> None:
    async def _runner():
        app = create_app(_make_config())
        async with TestClient(TestServer(app)) as client:
            await scenario(client)

    asyncio.run(_runner())


def test_health_endpoint():
    async def scenario(client):
        resp = await client.get("/api/health")
        assert resp.status == 200
        data = await resp.json()
        assert data["ok"] is True
        assert data["sink_kind"] == "null"

    run_scenario(scenario)


def test_metrics_endpoint():
    async def scenario(client):
        resp = await client.get("/api/metrics")
        assert resp.status == 200
        data = await resp.json()
        assert data["type"] == "metrics"
        assert "latency" in data

    run_scenario(scenario)


def test_hello_returns_hello_ack_then_state():
    async def scenario(client):
        ws = await client.ws_connect("/ws")
        await ws.send_json({"type": "hello", "sample_rate": 48000, "frame_samples": 480, "ua": "pytest"})
        ack = await ws.receive_json()
        assert ack["type"] == "hello_ack"
        assert ack["sample_rate"] == 48000
        assert "USB" in ack["modes"] and "LSB" in ack["modes"]
        assert "FM" in ack["modes"] and "AM" in ack["modes"]
        state = await ws.receive_json()
        assert state["type"] == "state"
        assert state["tx"] is False
        await ws.close()

    run_scenario(scenario)


def test_start_tx_then_state_then_stop():
    async def scenario(client):
        ws = await client.ws_connect("/ws")
        await ws.send_json({"type": "start_tx", "freq_hz": 14200000, "mode": "USB",
                             "mic_gain": 1.0, "tx_power": 1.0})
        state = await ws.receive_json()
        assert state["type"] == "state"
        assert state["tx"] is True
        assert state["sink"] == "running"
        assert state["mode"] == "USB"

        await ws.send_json({"type": "stop_tx"})
        state2 = await ws.receive_json()
        assert state2["type"] == "state"
        assert state2["tx"] is False
        assert state2["sink"] == "stopped"
        await ws.close()

    run_scenario(scenario)


def test_binary_audio_frame_accepted_while_keyed():
    async def scenario(client):
        ws = await client.ws_connect("/ws")
        await ws.send_json({"type": "start_tx", "freq_hz": 14200000, "mode": "USB",
                             "mic_gain": 1.0, "tx_power": 1.0})
        await ws.receive_json()

        import time
        samples = (0.2 * np.sin(np.linspace(0, 4 * np.pi, 480))).astype(np.float32)
        frame = _make_audio_frame(1, time.time() * 1000.0, samples)
        await ws.send_bytes(frame)
        await asyncio.sleep(0.1)

        app = client.app[WEBTX_KEY]
        assert app.jitter.stats["target_ms"] > 0  # buffer alive and reporting

        await ws.send_json({"type": "stop_tx"})
        await ws.receive_json()
        await ws.close()

    run_scenario(scenario)


def test_ping_pong():
    async def scenario(client):
        ws = await client.ws_connect("/ws")
        await ws.send_json({"type": "ping", "t": 123.5})
        msg = await ws.receive_json()
        assert msg["type"] == "pong"
        assert msg["t"] == 123.5
        assert "server_ts_ms" in msg
        await ws.close()

    run_scenario(scenario)


def test_invalid_frequency_returns_error():
    async def scenario(client):
        ws = await client.ws_connect("/ws")
        await ws.send_json({"type": "start_tx", "freq_hz": -5.0, "mode": "USB",
                             "mic_gain": 1.0, "tx_power": 1.0})
        msg = await ws.receive_json()
        assert msg["type"] == "error"
        assert msg["code"] == "invalid_params"
        await ws.close()

    run_scenario(scenario)


def test_invalid_mode_returns_error():
    async def scenario(client):
        ws = await client.ws_connect("/ws")
        await ws.send_json({"type": "start_tx", "freq_hz": 14200000, "mode": "CW",
                             "mic_gain": 1.0, "tx_power": 1.0})
        msg = await ws.receive_json()
        assert msg["type"] == "error"
        await ws.close()

    run_scenario(scenario)


def test_excessive_power_returns_error():
    async def scenario(client):
        ws = await client.ws_connect("/ws")
        await ws.send_json({"type": "start_tx", "freq_hz": 14200000, "mode": "USB",
                             "mic_gain": 1.0, "tx_power": 99.0})
        msg = await ws.receive_json()
        assert msg["type"] == "error"
        await ws.close()

    run_scenario(scenario)


def test_second_client_cannot_key_while_first_holds_tx():
    async def scenario(client):
        ws1 = await client.ws_connect("/ws")
        await ws1.send_json({"type": "start_tx", "freq_hz": 14200000, "mode": "USB",
                              "mic_gain": 1.0, "tx_power": 1.0})
        state1 = await ws1.receive_json()
        assert state1["tx"] is True

        ws2 = await client.ws_connect("/ws")
        await ws2.send_json({"type": "start_tx", "freq_hz": 7100000, "mode": "LSB",
                              "mic_gain": 1.0, "tx_power": 1.0})
        msg2 = await ws2.receive_json()
        assert msg2["type"] == "error"
        assert msg2["code"] == "tx_busy"

        await ws1.send_json({"type": "stop_tx"})
        await ws1.receive_json()
        await ws1.close()
        await ws2.close()

    run_scenario(scenario)


def test_disconnect_stops_tx():
    async def scenario(client):
        ws1 = await client.ws_connect("/ws")
        await ws1.send_json({"type": "start_tx", "freq_hz": 14200000, "mode": "USB",
                              "mic_gain": 1.0, "tx_power": 1.0})
        state1 = await ws1.receive_json()
        assert state1["tx"] is True
        app = client.app[WEBTX_KEY]
        assert app.tx_owner is not None

        await ws1.close()
        await asyncio.sleep(0.2)
        assert app.tx_owner is None
        assert not app.sink.is_running

    run_scenario(scenario)


def test_set_params_gain_does_not_restart_sink_object():
    async def scenario(client):
        ws = await client.ws_connect("/ws")
        await ws.send_json({"type": "start_tx", "freq_hz": 14200000, "mode": "USB",
                             "mic_gain": 1.0, "tx_power": 1.0})
        await ws.receive_json()
        app = client.app[WEBTX_KEY]
        sink_before = app.sink

        await ws.send_json({"type": "set_params", "mic_gain": 2.0})
        state = await ws.receive_json()
        assert state["mic_gain"] == 2.0
        assert app.sink is sink_before
        assert app.sink.is_running

        await ws.send_json({"type": "stop_tx"})
        await ws.receive_json()
        await ws.close()

    run_scenario(scenario)


def test_set_params_mode_change_does_not_restart_sink():
    async def scenario(client):
        ws = await client.ws_connect("/ws")
        await ws.send_json({"type": "start_tx", "freq_hz": 14200000, "mode": "USB",
                             "mic_gain": 1.0, "tx_power": 1.0})
        await ws.receive_json()
        app = client.app[WEBTX_KEY]
        sink_before = app.sink

        await ws.send_json({"type": "set_params", "mode": "FM"})
        state = await ws.receive_json()
        assert state["mode"] == "FM"
        assert app.sink is sink_before
        assert app.sink.is_running
        assert app.modulator.mode == "FM"

        await ws.send_json({"type": "stop_tx"})
        await ws.receive_json()
        await ws.close()

    run_scenario(scenario)


def test_unknown_message_type_returns_error():
    async def scenario(client):
        ws = await client.ws_connect("/ws")
        await ws.send_json({"type": "frobnicate"})
        msg = await ws.receive_json()
        assert msg["type"] == "error"
        assert msg["code"] == "unknown_type"
        await ws.close()

    run_scenario(scenario)


def test_malformed_json_returns_error():
    async def scenario(client):
        ws = await client.ws_connect("/ws")
        await ws.send_str("not json{{{")
        msg = await ws.receive_json()
        assert msg["type"] == "error"
        assert msg["code"] == "bad_json"
        await ws.close()

    run_scenario(scenario)


def test_worker_skips_write_when_stop_races_before_write(monkeypatch, caplog):
    """Regression test for the PTT-release race: _audio_worker only checks
    _tx_active_event once at the top of its loop, then does jitter/DSP work
    before writing to the sink. If a stop (e.g. operator releasing PTT) has
    already cleared the event by the time that work finishes, the worker
    must skip the write silently instead of calling sink.write() and
    treating the resulting SinkError as a genuine failure."""
    caplog.set_level(logging.INFO, logger="webtx.server")

    async def scenario(client):
        app = client.app[WEBTX_KEY]
        orig_pop = app.jitter.pop
        pop_called = threading.Event()
        write_called = threading.Event()

        def fake_pop(n):
            result = orig_pop(n)
            # Simulate _stop_tx_internal() having already run (operator
            # released PTT) while this worker iteration was doing its
            # jitter/DSP work, i.e. after the top-of-loop event check but
            # before the write.
            app._tx_active_event.clear()
            pop_called.set()
            return result

        def fake_write(iq):
            write_called.set()

        stop_calls = []
        # Install all three patches BEFORE start_tx is sent. The audio
        # worker thread is already running (started in _on_startup) and,
        # until start_tx sets _tx_active_event, it is guaranteed to be
        # idly blocked in _tx_active_event.wait(timeout=0.5) - it cannot
        # be mid-iteration on unpatched code. Patching after start_tx
        # would race an already-released worker iteration that may call
        # the *real* jitter.pop()/sink.write() before these patches land,
        # producing a false pass/failure unrelated to the production
        # guard under test.
        monkeypatch.setattr(app.jitter, "pop", fake_pop)
        monkeypatch.setattr(app.sink, "write", fake_write)
        monkeypatch.setattr(app, "_request_stop_tx_threadsafe", lambda reason: stop_calls.append(reason))

        ws = await client.ws_connect("/ws")
        await ws.send_json({"type": "start_tx", "freq_hz": 14200000, "mode": "USB",
                             "mic_gain": 1.0, "tx_power": 1.0})
        await ws.receive_json()

        for _ in range(50):
            if pop_called.is_set():
                break
            await asyncio.sleep(0.02)
        assert pop_called.is_set(), "worker thread never reached jitter.pop()"

        await asyncio.sleep(0.1)  # let the worker reach (or correctly skip) sink.write()

        assert not write_called.is_set(), (
            "sink.write() must be skipped once _tx_active_event was cleared "
            "mid-iteration, not called and then treated as a failure"
        )
        assert stop_calls == [], (
            f"_request_stop_tx_threadsafe must not fire for this expected race, got {stop_calls}"
        )
        error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert not error_records, (
            f"unexpected error-level log records: {[r.getMessage() for r in error_records]}"
        )

        await ws.close()

    run_scenario(scenario)


def test_worker_swallows_sinkerror_from_stop_race_at_write_time(monkeypatch, caplog):
    """Tighter variant of the same race: _tx_active_event is still set when
    _audio_worker's pre-write guard checks it, but gets cleared (by a
    concurrent operator-stop) in the brief window between that check and the
    sink.write() call itself, so sink.write() raises SinkError exactly as
    IQSink.write() does once the sink is no longer active. The worker's
    `except SinkError` handler must re-check the event and treat this as the
    same expected race, not a genuine sink failure."""
    caplog.set_level(logging.INFO, logger="webtx.server")

    async def scenario(client):
        ws = await client.ws_connect("/ws")
        await ws.send_json({"type": "start_tx", "freq_hz": 14200000, "mode": "USB",
                             "mic_gain": 1.0, "tx_power": 1.0})
        await ws.receive_json()

        app = client.app[WEBTX_KEY]
        write_called = threading.Event()

        def fake_write(iq):
            write_called.set()
            # By the time write() actually runs, a concurrent stop has
            # already cleared the event and stopped the sink - this is
            # exactly the SinkError IQSink.write() raises in that case.
            app._tx_active_event.clear()
            raise SinkError("write() called while sink is not running")

        stop_calls = []
        monkeypatch.setattr(app.sink, "write", fake_write)
        monkeypatch.setattr(app, "_request_stop_tx_threadsafe", lambda reason: stop_calls.append(reason))

        for _ in range(50):
            if write_called.is_set():
                break
            await asyncio.sleep(0.02)
        assert write_called.is_set(), "worker thread never reached sink.write()"

        await asyncio.sleep(0.1)  # let the except-handler guard run

        assert stop_calls == [], (
            f"_request_stop_tx_threadsafe must not fire for this expected race, got {stop_calls}"
        )
        error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert not error_records, (
            f"unexpected error-level log records: {[r.getMessage() for r in error_records]}"
        )

        await ws.close()

    run_scenario(scenario)
