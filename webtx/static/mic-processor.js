// AudioWorkletProcessor: buffers mic audio into fixed-size frames matching
// the server's frame duration, converts to Int16 mono, and reports each
// frame's peak/RMS alongside it so the main thread never has to re-scan
// samples just to drive the VU meter.
//
// `sampleRate` is a global provided by AudioWorkletGlobalScope; it always
// reflects the AudioContext's actual rate, even if the browser silently
// ignored the app's requested rate - so the frame length is always correct.
class MicProcessor extends AudioWorkletProcessor {
    constructor(options) {
        super();
        const opts = (options && options.processorOptions) || {};
        const frameMs = opts.frameMs || 10;
        this.frameSamples = Math.max(32, Math.round(sampleRate * frameMs / 1000));
        this.buffer = new Int16Array(this.frameSamples);
        this.offset = 0;
        this.peak = 0;
        this.sumSquares = 0;
    }

    process(inputs) {
        const input = inputs[0];
        if (input && input.length > 0) {
            const channel = input[0];
            for (let i = 0; i < channel.length; i++) {
                let s = channel[i];
                if (s > 1) s = 1;
                else if (s < -1) s = -1;

                const mag = Math.abs(s);
                if (mag > this.peak) this.peak = mag;
                this.sumSquares += s * s;

                this.buffer[this.offset++] = s < 0 ? s * 0x8000 : s * 0x7fff;

                if (this.offset >= this.frameSamples) {
                    const frame = this.buffer.slice();
                    const rms = Math.sqrt(this.sumSquares / this.frameSamples);
                    this.port.postMessage(
                        { samples: frame.buffer, peak: this.peak, rms: rms },
                        [frame.buffer]
                    );
                    this.offset = 0;
                    this.peak = 0;
                    this.sumSquares = 0;
                }
            }
        }
        return true;
    }
}

registerProcessor('mic-processor', MicProcessor);
