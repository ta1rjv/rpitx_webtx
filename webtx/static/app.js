"use strict";

// webtx dashboard client. Vanilla JS, no frameworks, no external CDN -
// everything here must work with no internet access on the Raspberry Pi.
//
// Wire protocol (must match webtx/server.py exactly):
//   binary frame: uint32 seq (LE) + float64 client_ts_ms (LE) + int16[] PCM
//   text frames: JSON {type: ...}; see docs/PROTOCOL notes in README.md

(function () {
  const $ = (id) => document.getElementById(id);

  // -- DOM refs -----------------------------------------------------------
  const connectionChip = $("connectionChip");
  const tuneChip = $("tuneChip");
  const latencyTotalValue = $("latencyTotalValue");
  const rttValue = $("rttValue");

  const vfoReadout = $("vfoReadout");
  const vfoABtn = $("vfoABtn");
  const vfoBBtn = $("vfoBBtn");
  const vfoSwapBtn = $("vfoSwapBtn");
  const freqRangeHint = $("freqRangeHint");
  const bandSelect = $("bandSelect");

  const modeSwitch = $("modeSwitch");

  const micChip = $("micChip");
  const micEnableBtn = $("micEnableBtn");
  const micDeviceRow = $("micDeviceRow");
  const micDeviceSelect = $("micDeviceSelect");
  const vuCanvas = $("vuCanvas");
  const sampleRateHint = $("sampleRateHint");

  const micGainSlider = $("micGainSlider");
  const micGainValue = $("micGainValue");
  const txPowerSlider = $("txPowerSlider");
  const txPowerValue = $("txPowerValue");

  const pttButton = $("pttButton");
  const pttLabel = $("pttLabel");
  const txLockToggle = $("txLockToggle");
  const txChip = $("txChip");

  const telSink = $("telSink");
  const telJitterDepth = $("telJitterDepth");
  const telUnderruns = $("telUnderruns");
  const telOverruns = $("telOverruns");
  const telFrames = $("telFrames");
  const telIqPeak = $("telIqPeak");
  const telCpu = $("telCpu");
  const telDropped = $("telDropped");
  const telElapsed = $("telElapsed");
  const telServerVersion = $("telServerVersion");

  const toastContainer = $("toastContainer");

  // -- state ----------------------------------------------------------------
  let ws = null;
  let wsReady = false;
  let reconnectDelay = 500;
  const RECONNECT_MAX_MS = 5000;

  let serverSampleRate = 48000;
  let serverFrameSamples = 480;
  let serverFrameMs = 10;
  let minFreqHz = 5000;
  let maxFreqHz = 1500000000;
  let digitPlaces = []; // powers of ten, most-significant first

  let currentVfo = "A";
  const vfoFreqs = { A: 14200000, B: 14200000 };
  let currentFreqHz = vfoFreqs.A;
  let currentMode = "USB";

  let keyed = false;
  let lockMode = false;

  let micReady = false;
  let audioContext = null;
  let micStream = null;
  let micNode = null;
  let seqCounter = 0;
  let droppedFrames = 0;

  let pingSentAt = 0;
  let pingTimer = null;

  let lastPeakDb = -90, lastRmsDb = -90, peakHoldDb = -90, peakHoldTime = 0;

  // -- small helpers ----------------------------------------------------------

  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  function send(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(obj));
    }
  }

  function showToast(level, message, sticky) {
    const el = document.createElement("div");
    el.className = "toast";
    el.dataset.level = level || "info";
    el.textContent = message;
    el.addEventListener("click", () => el.remove());
    toastContainer.appendChild(el);
    if (!sticky) {
      setTimeout(() => el.remove(), 5000);
    }
  }

  function setChip(el, state, label) {
    el.dataset.state = state;
    el.querySelector(".chip-label").textContent = label;
  }

  // -- WebSocket connection, with capped exponential backoff -----------------

  function connect() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    setChip(connectionChip, wsReady ? "reconnecting" : "connecting",
            wsReady ? "Reconnecting" : "Connecting");
    ws = new WebSocket(`${proto}//${location.host}/ws`);
    ws.binaryType = "arraybuffer";

    ws.onopen = () => {
      wsReady = true;
      reconnectDelay = 500;
      setChip(connectionChip, "online", "Online");
      send({
        type: "hello",
        sample_rate: audioContext ? audioContext.sampleRate : 0,
        frame_samples: serverFrameSamples,
        ua: navigator.userAgent,
      });
      startPingLoop();
      updatePttEnabled();
    };

    ws.onclose = () => {
      wsReady = false;
      keyed = false;
      applyTxUi(false);
      setChip(connectionChip, "reconnecting", "Reconnecting");
      stopPingLoop();
      updatePttEnabled();
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX_MS);
    };

    ws.onmessage = (ev) => {
      if (typeof ev.data === "string") {
        try {
          handleServerMessage(JSON.parse(ev.data));
        } catch (err) {
          // malformed message from the server; ignore rather than crash the UI
        }
      }
    };
  }

  function startPingLoop() {
    stopPingLoop();
    pingTimer = setInterval(() => {
      pingSentAt = performance.now();
      send({ type: "ping", t: pingSentAt });
    }, 2000);
  }

  function stopPingLoop() {
    if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
  }

  // -- server message handling -------------------------------------------

  function handleServerMessage(msg) {
    switch (msg.type) {
      case "hello_ack": applyHelloAck(msg); break;
      case "state": applyState(msg); break;
      case "metrics": applyMetrics(msg); break;
      case "error": handleServerError(msg); break;
      case "log": showToast(msg.level, msg.message); break;
      case "pong": handlePong(); break;
    }
  }

  function applyHelloAck(msg) {
    serverSampleRate = msg.sample_rate || serverSampleRate;
    serverFrameSamples = msg.frame_samples || serverFrameSamples;
    serverFrameMs = (1000 * serverFrameSamples) / serverSampleRate;
    minFreqHz = msg.min_freq_hz != null ? msg.min_freq_hz : minFreqHz;
    maxFreqHz = msg.max_freq_hz != null ? msg.max_freq_hz : maxFreqHz;
    telServerVersion.textContent = msg.server_version || "--";
    telSink.textContent = msg.sink_kind || "--";
    freqRangeHint.textContent =
      `${(minFreqHz / 1e6).toFixed(3)} - ${(maxFreqHz / 1e6).toFixed(3)} MHz`;

    buildVfoDigits();
    renderVfo();

    if (Array.isArray(msg.bands)) {
      bandSelect.innerHTML = "";
      for (const band of msg.bands) {
        const opt = document.createElement("option");
        opt.value = String(band.freq_hz);
        opt.textContent = band.name;
        bandSelect.appendChild(opt);
      }
    }
    updatePttEnabled();
  }

  function applyState(msg) {
    if (typeof msg.freq_hz === "number") {
      currentFreqHz = msg.freq_hz;
      vfoFreqs[currentVfo] = currentFreqHz;
      renderVfo();
    }
    if (msg.mode) {
      currentMode = msg.mode;
      for (const btn of modeSwitch.querySelectorAll(".mode-btn")) {
        btn.classList.toggle("is-active", btn.dataset.mode === currentMode);
      }
    }
    if (typeof msg.mic_gain === "number") {
      micGainSlider.value = String(msg.mic_gain);
      micGainValue.textContent = `${msg.mic_gain.toFixed(2)}x`;
    }
    if (typeof msg.tx_power === "number") {
      txPowerSlider.value = String(msg.tx_power);
      txPowerValue.textContent = msg.tx_power.toFixed(1);
    }
    const wasKeyed = keyed;
    keyed = !!msg.tx;
    applyTxUi(keyed);
    if (!wasKeyed && keyed) {
      showTunePriming();
    }
    if (msg.sink) {
      telSink.textContent = msg.sink;
    }
  }

  function applyMetrics(msg) {
    if (msg.latency) {
      let total = 0;
      for (const stage of ["net", "jitter", "dsp", "sink"]) {
        const row = document.querySelector(`.latency-row[data-stage="${stage}"]`);
        const stats = msg.latency[stage];
        if (!row || !stats) continue;
        const ms = stats.last || 0;
        row.querySelector(".latency-fill").style.width = `${clamp((ms / 200) * 100, 0, 100)}%`;
        row.querySelector(".latency-num").textContent = `${ms.toFixed(1)} ms`;
      }
      total = msg.latency.total ? msg.latency.total.last : 0;
      latencyTotalValue.textContent = `${total.toFixed(0)} ms`;
    }
    if (msg.jitter) {
      telJitterDepth.textContent = `${msg.jitter.depth_ms.toFixed(0)} ms`;
      telUnderruns.textContent = String(msg.jitter.underruns);
      telOverruns.textContent = String(msg.jitter.overruns);
    }
    if (typeof msg.frames_per_s === "number") {
      telFrames.textContent = msg.frames_per_s.toFixed(0);
    }
    if (typeof msg.iq_peak === "number") {
      telIqPeak.textContent = msg.iq_peak.toFixed(2);
    }
    if (typeof msg.cpu_percent === "number") {
      telCpu.textContent = `${msg.cpu_percent.toFixed(0)}%`;
    }
    if (msg.sink) {
      const label = msg.sink.kind + (msg.sink.running ? " (running)" : " (stopped)");
      telSink.textContent = label;
    }
    if (typeof msg.tx_seconds === "number") {
      telElapsed.textContent = formatElapsed(msg.tx_seconds);
    }
    telDropped.textContent = String(droppedFrames);
  }

  function handleServerError(msg) {
    showToast(msg.fatal ? "fatal" : "error", msg.message, !!msg.fatal);
  }

  function handlePong() {
    const rtt = performance.now() - pingSentAt;
    rttValue.textContent = `${rtt.toFixed(0)} ms`;
  }

  function formatElapsed(seconds) {
    const s = Math.max(0, Math.floor(seconds));
    const mm = String(Math.floor(s / 60)).padStart(2, "0");
    const ss = String(s % 60).padStart(2, "0");
    return `${mm}:${ss}`;
  }

  function showTunePriming() {
    tuneChip.hidden = false;
    setChip(tuneChip, "priming", "Priming");
    setTimeout(() => { tuneChip.hidden = true; }, 400);
  }

  // -- VFO digit display --------------------------------------------------

  function buildVfoDigits() {
    const digitCount = Math.max(4, String(Math.floor(maxFreqHz)).length);
    digitPlaces = [];
    vfoReadout.innerHTML = "";
    for (let i = digitCount - 1; i >= 0; i--) {
      if (i < digitCount - 1 && (i + 1) % 3 === 0) {
        const sep = document.createElement("span");
        sep.className = "vfo-sep";
        sep.textContent = ".";
        vfoReadout.appendChild(sep);
      }
      const span = document.createElement("span");
      span.className = "vfo-digit";
      span.dataset.place = String(i);
      span.tabIndex = 0;
      span.setAttribute("role", "spinbutton");
      span.setAttribute("aria-label", `10^${i} Hz digit`);
      span.addEventListener("click", onDigitClick);
      span.addEventListener("wheel", onDigitWheel, { passive: false });
      span.addEventListener("keydown", onDigitKeydown);
      vfoReadout.appendChild(span);
      digitPlaces.push(i);
    }
    const unit = document.createElement("span");
    unit.className = "vfo-unit";
    unit.textContent = "Hz";
    vfoReadout.appendChild(unit);
  }

  function renderVfo() {
    const digits = vfoReadout.querySelectorAll(".vfo-digit");
    let firstNonZeroSeen = false;
    digits.forEach((span) => {
      const place = parseInt(span.dataset.place, 10);
      const digit = Math.floor(currentFreqHz / Math.pow(10, place)) % 10;
      span.textContent = String(digit);
      const dim = digit === 0 && !firstNonZeroSeen;
      if (digit !== 0) firstNonZeroSeen = true;
      span.classList.toggle("is-leading", dim);
    });
  }

  function stepDigit(place, delta) {
    // Plain integer arithmetic (not a divide/round/multiply round-trip):
    // all values here are exact integer Hz within float64's safe range, and
    // a round-trip through division would truncate any digits below `place`
    // whenever currentFreqHz wasn't already an exact multiple of the step.
    const step = Math.pow(10, place);
    const next = clamp(currentFreqHz + delta * step, minFreqHz, maxFreqHz);
    if (next === currentFreqHz) return;
    currentFreqHz = next;
    vfoFreqs[currentVfo] = currentFreqHz;
    renderVfo();
    onFrequencyChanged();
  }

  function onDigitClick(ev) {
    const rect = ev.currentTarget.getBoundingClientRect();
    const upperHalf = (ev.clientY - rect.top) < rect.height / 2;
    stepDigit(parseInt(ev.currentTarget.dataset.place, 10), upperHalf ? 1 : -1);
  }

  function onDigitWheel(ev) {
    ev.preventDefault();
    stepDigit(parseInt(ev.currentTarget.dataset.place, 10), ev.deltaY < 0 ? 1 : -1);
  }

  function onDigitKeydown(ev) {
    if (ev.key === "ArrowUp") { ev.preventDefault(); stepDigit(parseInt(ev.currentTarget.dataset.place, 10), 1); }
    else if (ev.key === "ArrowDown") { ev.preventDefault(); stepDigit(parseInt(ev.currentTarget.dataset.place, 10), -1); }
  }

  let freqSendTimer = null;
  function onFrequencyChanged() {
    if (!keyed) return; // takes effect on the next start_tx otherwise
    clearTimeout(freqSendTimer);
    freqSendTimer = setTimeout(() => send({ type: "set_params", freq_hz: currentFreqHz }), 150);
  }

  // -- VFO A/B, band select -------------------------------------------------

  vfoABtn.addEventListener("click", () => switchVfo("A"));
  vfoBBtn.addEventListener("click", () => switchVfo("B"));
  vfoSwapBtn.addEventListener("click", () => {
    const a = vfoFreqs.A;
    vfoFreqs.A = vfoFreqs.B;
    vfoFreqs.B = a;
    currentFreqHz = vfoFreqs[currentVfo];
    renderVfo();
    onFrequencyChanged();
  });

  function switchVfo(which) {
    currentVfo = which;
    vfoABtn.classList.toggle("is-active", which === "A");
    vfoBBtn.classList.toggle("is-active", which === "B");
    currentFreqHz = vfoFreqs[which];
    renderVfo();
    onFrequencyChanged();
  }

  bandSelect.addEventListener("change", () => {
    const hz = parseInt(bandSelect.value, 10);
    if (!Number.isFinite(hz)) return;
    currentFreqHz = clamp(hz, minFreqHz, maxFreqHz);
    vfoFreqs[currentVfo] = currentFreqHz;
    renderVfo();
    onFrequencyChanged();
  });

  // -- mode switch -----------------------------------------------------------

  modeSwitch.addEventListener("click", (ev) => {
    const btn = ev.target.closest(".mode-btn");
    if (!btn) return;
    currentMode = btn.dataset.mode;
    for (const b of modeSwitch.querySelectorAll(".mode-btn")) {
      b.classList.toggle("is-active", b === btn);
    }
    if (keyed) {
      send({ type: "set_params", mode: currentMode });
    }
  });

  // -- levels -----------------------------------------------------------------

  let lastGainSendAt = 0;
  micGainSlider.addEventListener("input", () => {
    const v = parseFloat(micGainSlider.value);
    micGainValue.textContent = `${v.toFixed(2)}x`;
    const now = performance.now();
    if (now - lastGainSendAt > 80) {
      lastGainSendAt = now;
      send({ type: "set_params", mic_gain: v });
    }
  });

  let lastPowerSendAt = 0;
  txPowerSlider.addEventListener("input", () => {
    const v = parseFloat(txPowerSlider.value);
    txPowerValue.textContent = v.toFixed(1);
    const now = performance.now();
    if (now - lastPowerSendAt > 80) {
      lastPowerSendAt = now;
      send({ type: "set_params", tx_power: v });
    }
  });

  // -- PTT: pointer events (mouse + touch unified) + spacebar + lock -------

  function applyTxUi(isKeyed) {
    pttButton.classList.toggle("is-keyed", isKeyed);
    pttButton.setAttribute("aria-pressed", String(isKeyed));
    pttLabel.textContent = isKeyed ? "TRANSMITTING" : "PTT";
    setChip(txChip, isKeyed ? "tx" : "rx", isKeyed ? "TX" : "RX");
  }

  function updatePttEnabled() {
    pttButton.disabled = !(micReady && wsReady);
  }

  function pttPress() {
    if (pttButton.disabled) return;
    if (lockMode) {
      if (keyed) send({ type: "stop_tx" }); else sendStartTx();
    } else {
      sendStartTx();
    }
  }

  function pttRelease() {
    if (lockMode) return;
    send({ type: "stop_tx" });
  }

  function sendStartTx() {
    send({
      type: "start_tx",
      freq_hz: currentFreqHz,
      mode: currentMode,
      mic_gain: parseFloat(micGainSlider.value),
      tx_power: parseFloat(txPowerSlider.value),
    });
  }

  pttButton.addEventListener("pointerdown", (ev) => {
    ev.preventDefault();
    try { pttButton.setPointerCapture(ev.pointerId); } catch (err) { /* ignore */ }
    pttPress();
  });
  pttButton.addEventListener("pointerup", pttRelease);
  pttButton.addEventListener("pointercancel", pttRelease);
  pttButton.addEventListener("contextmenu", (ev) => ev.preventDefault());

  txLockToggle.addEventListener("change", () => {
    lockMode = txLockToggle.checked;
  });

  window.addEventListener("keydown", (ev) => {
    if (ev.code !== "Space" || ev.repeat) return;
    const tag = (document.activeElement && document.activeElement.tagName) || "";
    if (["INPUT", "SELECT", "TEXTAREA"].includes(tag)) return;
    ev.preventDefault();
    pttPress();
  });
  window.addEventListener("keyup", (ev) => {
    if (ev.code !== "Space") return;
    const tag = (document.activeElement && document.activeElement.tagName) || "";
    if (["INPUT", "SELECT", "TEXTAREA"].includes(tag)) return;
    ev.preventDefault();
    pttRelease();
  });

  // -- microphone capture --------------------------------------------------

  function nextPow2(n) {
    let p = 256;
    while (p < n) p *= 2;
    return Math.min(p, 16384);
  }

  async function enableMic() {
    if (!window.isSecureContext) {
      showToast("error",
        "Microphone access requires HTTPS (or http://localhost). Open this page "
        + "over https:// - see README.md for certificate setup.", true);
      setChip(micChip, "error", "Insecure context");
      return;
    }
    try {
      setChip(micChip, "prompting", "Requesting...");
      micStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
          channelCount: 1,
          sampleRate: serverSampleRate,
        },
      });

      audioContext = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: serverSampleRate,
      });
      const actualRate = audioContext.sampleRate;
      sampleRateHint.textContent = `Sample rate: ${actualRate} Hz`;
      if (actualRate !== serverSampleRate) {
        showToast("warn",
          `Browser is capturing at ${actualRate} Hz; server expects ${serverSampleRate} Hz. `
          + "Audio pitch/timing may be affected.");
      }

      const source = audioContext.createMediaStreamSource(micStream);

      if (audioContext.audioWorklet) {
        await audioContext.audioWorklet.addModule("/static/mic-processor.js");
        micNode = new AudioWorkletNode(audioContext, "mic-processor", {
          processorOptions: { frameMs: serverFrameMs },
        });
        micNode.port.onmessage = (ev) => handleMicFrame(ev.data);
        source.connect(micNode);
      } else {
        // Fallback for browsers without AudioWorklet support.
        const frameSamples = Math.round(actualRate * serverFrameMs / 1000);
        const bufferSize = nextPow2(frameSamples);
        micNode = audioContext.createScriptProcessor(bufferSize, 1, 1);
        micNode.onaudioprocess = (ev) => {
          const input = ev.inputBuffer.getChannelData(0);
          let peak = 0, sumSq = 0;
          const pcm = new Int16Array(input.length);
          for (let i = 0; i < input.length; i++) {
            const s = clamp(input[i], -1, 1);
            peak = Math.max(peak, Math.abs(s));
            sumSq += s * s;
            pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
          }
          handleMicFrame({ samples: pcm.buffer, peak, rms: Math.sqrt(sumSq / input.length) });
        };
        const silence = audioContext.createGain();
        silence.gain.value = 0;
        source.connect(micNode);
        micNode.connect(silence);
        silence.connect(audioContext.destination);
      }

      micReady = true;
      setChip(micChip, "granted", "Enabled");
      micEnableBtn.disabled = true;
      await populateMicDevices();
      micDeviceRow.hidden = false;
      updatePttEnabled();
    } catch (err) {
      setChip(micChip, "error", "Error");
      showToast("error", `Microphone access failed: ${err.message}`, true);
    }
  }

  async function populateMicDevices() {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      micDeviceSelect.innerHTML = "";
      for (const d of devices) {
        if (d.kind !== "audioinput") continue;
        const opt = document.createElement("option");
        opt.value = d.deviceId;
        opt.textContent = d.label || "Microphone";
        micDeviceSelect.appendChild(opt);
      }
    } catch (err) {
      // enumerateDevices is best-effort; the default device still works.
    }
  }

  function handleMicFrame(data) {
    updateVuLevels(data.peak, data.rms);
    if (!keyed || !wsReady || !ws) return;
    const pcmBytes = new Uint8Array(data.samples);
    const out = new Uint8Array(12 + pcmBytes.byteLength);
    const header = new DataView(out.buffer);
    seqCounter = (seqCounter + 1) >>> 0;
    header.setUint32(0, seqCounter, true);
    header.setFloat64(4, performance.timeOrigin + performance.now(), true);
    out.set(pcmBytes, 12);
    if (ws.bufferedAmount > 65536) {
      droppedFrames++;
      return;
    }
    ws.send(out.buffer);
  }

  micEnableBtn.addEventListener("click", enableMic);

  // -- VU meter -------------------------------------------------------------

  function linearToDb(x) {
    if (x <= 0.0000316) return -90;
    return 20 * Math.log10(x);
  }

  function updateVuLevels(peak, rms) {
    lastPeakDb = linearToDb(peak);
    lastRmsDb = linearToDb(rms);
    if (lastPeakDb > peakHoldDb) {
      peakHoldDb = lastPeakDb;
      peakHoldTime = performance.now();
    }
  }

  function drawVu() {
    requestAnimationFrame(drawVu);
    const now = performance.now();
    if (now - peakHoldTime > 1500 && peakHoldDb > -90) {
      peakHoldDb = Math.max(-90, peakHoldDb - 0.6);
    }
    const ctx = vuCanvas.getContext("2d");
    if (!ctx) return;
    const w = vuCanvas.width, h = vuCanvas.height;
    ctx.clearRect(0, 0, w, h);

    const minDb = -60, maxDb = 0;
    const xFor = (db) => (clamp(db, minDb, maxDb) - minDb) / (maxDb - minDb) * w;

    const grad = ctx.createLinearGradient(0, 0, w, 0);
    grad.addColorStop(0, "#4fc4b8");
    grad.addColorStop(0.75, "#e0a15c");
    grad.addColorStop(0.92, "#e0463f");
    ctx.fillStyle = grad;
    ctx.fillRect(0, h * 0.25, xFor(lastRmsDb), h * 0.5);

    const peakX = xFor(peakHoldDb);
    ctx.fillStyle = "#e7ecf1";
    ctx.fillRect(Math.max(0, peakX - 1), 4, 2, h - 8);

    const clipX = xFor(-6);
    ctx.strokeStyle = "rgba(224,70,63,0.6)";
    ctx.beginPath();
    ctx.moveTo(clipX, 0);
    ctx.lineTo(clipX, h);
    ctx.stroke();
  }

  // -- bootstrap --------------------------------------------------------------

  buildVfoDigits();
  renderVfo();
  micGainValue.textContent = `${parseFloat(micGainSlider.value).toFixed(2)}x`;
  txPowerValue.textContent = parseFloat(txPowerSlider.value).toFixed(1);
  connect();
  requestAnimationFrame(drawVu);
})();
