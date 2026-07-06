# WebTX Web Interface

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

WebTX, Raspberry Pi üzerinde `rpitx` ve `csdr` kütüphanelerini kullanarak geliştirilmiş, tarayıcı tabanlı, düşük gecikmeli bir SDR verici kontrol arayüzüdür.

## Kurulum Adımları

# Hardware

| Raspberry Model      | Status  |
| ---------------------|:-------:|
| Pizero|OK|
| PizeroW|OK|
| PiA+|OK|
| PiB|Partial|
| PiB+|OK|
| P2B|OK|
| Pi3B|OK|
| Pi3B+|OK|
| Pi4|In beta mode|


### 1. Bağımlılıkları Yükle
Sisteminizde `csdr` ve temel derleme araçlarının yüklü olduğundan emin olun:

```
sudo apt-get update
sudo apt-get install libffi-dev python3-dev build-essential csdr
pip3 install flask flask-socketio
```

**Öncelikle** aşağıdaki komutla bu projenin temel aldığı `rpitx` kütüphanesini ve bu projeyi Raspberry Pi'nize klonlayın:

F5OEO/rpitx
```
git clone https://github.com/F5OEO/rpitx.git
cd rpitx
sudo ./install.sh
```
TA1RJV/rpitx_webtx
```
git clone https://github.com/ta1rjv/rpitx_webtx.git
cd rpitx_webtx
```

### 2. Yapılandırma

server.py dosyasını açın:
`
nano server.py
`
```
RPITX_PATH = "/home/selim/rpitx"
```
satırını bulun.

Eğer rpitx klasörünüz farklı bir yoldaysa, bu yolu kendi dizininize göre güncelleyin.

### 3. Güvenlik ve Sertifika

Tarayıcıların mikrofon izni vermesi için yerel bir SSL sertifikasına ihtiyacınız vardır:

```
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes -subj "/CN=10.10.10.38"
```

(Not: IP adresiniz farklıysa /CN= kısmını kendi IP adresinizle değiştirin.)

### 4. Çalıştırma
```
sudo python3 server.py
```
Tarayıcınızdan https://<IP_ADRESINIZ>:5000 adresine gidin. Tarayıcı uyarı verirse; "Gelişmiş" -> "İlerle (güvenli değil)" seçeneğine tıklayarak arayüze erişebilirsiniz.

```
📂 Proje Dizini
web_tx/
├── server.py
├── static/
│   └── mic-processor.js
└── templates/
    └── index.html
```

### 💡 Geliştirme Notları

Ses Hızı: Eğer ses hızıyla ilgili sorun yaşarsanız server.py içerisindeki sample_rate = 48000 değerini 44100 olarak güncelleyin.
Performans: PTT gecikmesini minimize etmek için işlemci önceliğini şu komutla artırabilirsiniz:
   ```
    sudo chrt -f 99 python3 server.py
   ```
Mikrofon Erişimi: Mikrofon erişimi `HTTP` üzerinden çalışmaz, mutlaka oluşturduğunuz sertifika ile `HTTPS` üzerinden giriş yapın.

## ⚠️ Yasal Uyarı ve Sorumluluk Reddi

![bpf](/img/bpf-warning.png)


Bu proje **araştırma, geliştirme ve eğitim amaçlıdır**. Aşağıdaki kurallara eksiksiz uyun:

- **Testleri kontrollü ortamda yapın.** Anten yerine **dummy load (suni yük)** kullanarak dış ortama anlamlı RF enerjisi yaymayın.
- Düşük çıkış gücü kullanın.
- RF spektrumu sınırlı ve ortak kullanımdadır; **tüm deneylerinizi ilgili teknik standartlara ve yürürlükteki yasal düzenlemelere uygun şekilde yapın**.
- Bu yazılım, izinsiz yayın veya yasal ihlal amacıyla kullanılamaz.
- **Bu aracı kullanarak gerçekleştireceğiniz her türlü uygulamanın hukuki, idari, cezai ve mali sorumluluğu tamamen size aittir.** Geliştiriciler, olası ihlal veya zararlardan sorumlu değildir.
