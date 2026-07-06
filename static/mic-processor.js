class MicProcessor extends AudioWorkletProcessor {
    constructor() {
        super();
        // 512 örnek = 48kHz'de ~10.6 ms gecikme (Gerçek zamanlı düşük gecikme)
        this.bufferSize = 512;
        this.buffer = new Int16Array(this.bufferSize);
        this.offset = 0;
    }

    process(inputs) {
        const input = inputs[0];
        if (input && input.length > 0) {
            const channel = input[0];
            for (let i = 0; i < channel.length; i++) {
                // Float[-1.0, 1.0] aralığını Int16 formatına güvenle dönüştür
                let s = Math.max(-1, Math.min(1, channel[i]));
                this.buffer[this.offset++] = s < 0 ? s * 0x8000 : s * 0x7FFF;

                // Tampon dolduğu an gecikmeden gönder ve sıfırla
                if (this.offset >= this.bufferSize) {
                    const outputSlice = this.buffer.slice();
                    this.port.postMessage(outputSlice.buffer, [outputSlice.buffer]);
                    this.offset = 0;
                }
            }
        }
        return true;
    }
}

registerProcessor('mic-processor', MicProcessor);
