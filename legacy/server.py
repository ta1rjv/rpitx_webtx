from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import subprocess
import threading
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rpitx-web")

app = Flask(__name__)
socketio = SocketIO(app, async_mode='threading')

# TX Durumu ve Tampon Yönetimi
tx_active = False
pipeline = None
audio_buffer = bytearray()
buffer_lock = threading.Lock()

current_params = {
    "freq": 14.200,
    "mode": "USB",
    "gain": 0.8,
    "tx_power": 7.0
}

RPITX_PATH = "/home/selim/rpitx"
SENDIQ = os.path.join(RPITX_PATH, "sendiq")
CSDR = "csdr"

def build_pipeline():
    freq = current_params["freq"]
    mode = current_params["mode"]
    gain = current_params["gain"]
    tx_power = current_params["tx_power"]
    sample_rate = 48000

    if mode == "USB":
        # 150 Hz - 3100 Hz arası USB filtresi (Düşük gecikmeli keskinlik: 0.01)
        csdr_cmd = (
            f"{CSDR} convert_i16_f | "
            f"{CSDR} gain_ff {gain} | "
            f"{CSDR} dsb_fc | "
            f"{CSDR} bandpass_fir_fft_cc 0.003 0.065 0.01"
        )
    elif mode == "LSB":
        # -3100 Hz ile -150 Hz arası LSB filtresi
        csdr_cmd = (
            f"{CSDR} convert_i16_f | "
            f"{CSDR} gain_ff {gain} | "
            f"{CSDR} dsb_fc | "
            f"{CSDR} bandpass_fir_fft_cc -0.065 -0.003 0.01"
        )
    else:  # FM (NBFM - Dar Bant Temiz FM)
        # Kompleks filtreleme ile DC sapmasını ve dip gürültüsünü yok edip FM modülasyonu uygular
        fm_deviation_scale = gain * 0.15
        csdr_cmd = (
            f"{CSDR} convert_i16_f | "
            f"{CSDR} dsb_fc | "
            f"{CSDR} bandpass_fir_fft_cc 0.006 0.062 0.01 | "
            f"{CSDR} realpart_cf | "
            f"{CSDR} gain_ff {fm_deviation_scale} | "
            f"{CSDR} fmmod_fc"
        )

    cmd = f"{csdr_cmd} | sudo {SENDIQ} -i /dev/stdin -f {freq}e6 -s {sample_rate} -t float -p {tx_power}"
    return cmd

def feed_pipeline():
    global audio_buffer, pipeline
    while tx_active and pipeline:
        chunk = None
        with buffer_lock:
            # Gecikme engelleme: Tamponda ağ gecikmesi nedeniyle 8 KB'tan fazla veri birikirse
            # yankı oluşmaması için en eski verileri temizle.
            if len(audio_buffer) > 8192:
                del audio_buffer[:-2048]
                
            # Gerçek zamanlı akış için eşik değerini 1024 bayta (~5 ms) düşürdük
            if len(audio_buffer) >= 1024:
                chunk = bytes(audio_buffer[:1024])
                del audio_buffer[:1024]

        if chunk:
            try:
                pipeline.stdin.write(chunk)
                pipeline.stdin.flush()
            except (BrokenPipeError, OSError):
                break
        else:
            socketio.sleep(0.002) # 2 ms kısa bekleme

def start_transmitter():
    global pipeline
    if pipeline is not None:
        return True
        
    cmd = build_pipeline()
    logger.info(f"TX başlatılıyor: {cmd}")
    try:
        pipeline = subprocess.Popen(
            cmd, shell=True, stdin=subprocess.PIPE,
            preexec_fn=lambda: os.nice(-10)
        )
        threading.Thread(target=feed_pipeline, daemon=True).start()
        return True
    except Exception as e:
        logger.error(f"TX başlatılamadı: {e}")
        return False

def stop_transmitter(keep_tx_flag=False):
    global tx_active, pipeline
    if not keep_tx_flag:
        tx_active = False
    if pipeline:
        try:
            pipeline.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        try:
            pipeline.terminate()
            pipeline.wait(timeout=1)
        except (subprocess.TimeoutExpired, OSError):
            pipeline.kill()
        pipeline = None
    logger.info("TX durduruldu.")

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('start_tx')
def handle_start_tx(data):
    global tx_active
    current_params["freq"] = float(data.get('freq', 14.200))
    current_params["mode"] = data.get('mode', 'USB')
    current_params["gain"] = float(data.get('gain', 0.8))
    current_params["tx_power"] = float(data.get('tx_power', 1.0)) * 7.0
    
    # Tembel Başlatma (Lazy Initialization):
    # PTT'ye basınca sadece bayrağı açıyoruz, sendiq hemen çalıştırılmıyor.
    # Böylece boşta taşıyıcı basması engelleniyor. Verici ilk ses paketinde açılacak.
    tx_active = True
    with buffer_lock:
        audio_buffer.clear()
    emit('tx_status', {'active': True, 'freq': current_params["freq"]})

@socketio.on('stop_tx')
def handle_stop_tx():
    stop_transmitter(keep_tx_flag=False)
    emit('tx_status', {'active': False})

@socketio.on('update_params')
def handle_update_params(data):
    global tx_active
    current_params["gain"] = float(data.get('gain', current_params["gain"]))
    current_params["tx_power"] = float(data.get('tx_power', 1.0)) * 7.0
    if tx_active and pipeline is not None:
        # TX esnasında parametre değişirse vericiyi kapat;
        # bir sonraki ses paketi geldiğinde yeni ayarlarla otomatik başlayacak.
        stop_transmitter(keep_tx_flag=True)

@socketio.on('audio_chunk')
def handle_audio(chunk):
    global audio_buffer, pipeline, tx_active
    if tx_active and isinstance(chunk, (bytes, bytearray)):
        with buffer_lock:
            audio_buffer.extend(chunk)
            
        # İlk ses paketi geldi ve verici henüz açılmadıysa şimdi başlat
        if pipeline is None:
            start_transmitter()

@socketio.on('disconnect')
def handle_disconnect():
    stop_transmitter(keep_tx_flag=False)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, ssl_context='adhoc')
