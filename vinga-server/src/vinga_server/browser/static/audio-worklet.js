// The two audio processors the client runs on the audio thread (#613,
// D3b), registered under two names from this one module.
//
// "vinga-capture" sits behind the microphone in a 16 kHz AudioContext
// and cuts what it hears into 960-sample blocks, 60 ms each, which is
// the frame a board sends. Each block goes to the main thread as a
// transferred Float32Array; the Opus encoder is WebCodecs', which is a
// window API and is not assumed to exist on this thread.
//
// "vinga-playback" is the speaker. The main thread decodes the server's
// Opus and hands it the samples; this processor owns the jitter buffer,
// the volume the device tool sets, and, only when the page was opened
// with the lane's switch, the running sum of what it rendered. It takes
// three messages: append samples, set the gain, flush.

const BLOCK = 960;

class Capture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.block = new Float32Array(BLOCK);
    this.filled = 0;
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel === undefined) {
      return true;
    }
    let at = 0;
    while (at < channel.length) {
      const take = Math.min(BLOCK - this.filled, channel.length - at);
      this.block.set(channel.subarray(at, at + take), this.filled);
      this.filled += take;
      at += take;
      if (this.filled === BLOCK) {
        this.port.postMessage(this.block, [this.block.buffer]);
        this.block = new Float32Array(BLOCK);
        this.filled = 0;
      }
    }
    return true;
  }
}

// How much has to be waiting before a reply starts to sound: enough to
// ride out the network's unevenness, little enough not to be heard as a
// delay. A reply shorter than this still plays, once it has waited as
// long as the threshold would have taken to fill.
const START_SECONDS = 0.12;

// How often the running sum is reported, in render quanta of 128
// samples: about ten times a second at 24 kHz.
const REPORT_EVERY = 20;

class Playback extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const observed = options && options.processorOptions && options.processorOptions.observe;
    this.observe = observed === true;
    this.queue = [];
    this.offset = 0;
    this.buffered = 0;
    this.playing = false;
    this.waited = 0;
    this.gain = 1;
    this.appended = 0;
    this.consumed = 0;
    this.sum = 0;
    this.quanta = 0;
    this.port.onmessage = (event) => this.receive(event.data);
  }

  receive(message) {
    if (message.type === "append") {
      this.queue.push(message.samples);
      this.buffered += message.samples.length;
      this.appended += 1;
    } else if (message.type === "gain") {
      this.gain = message.gain;
    } else if (message.type === "flush") {
      this.consumed += this.queue.length;
      this.queue = [];
      this.offset = 0;
      this.buffered = 0;
      // Said even when nothing was sounding: what was waiting to start
      // has been played out too, in the only sense the main thread
      // asks about.
      this.playing = true;
      this.stop();
    }
  }

  // The queue ran dry. Said once per stretch of sound rather than per
  // quantum, with how many appends have been played out, so the main
  // thread can tell a reply that has finished sounding from a gap in
  // one it is still sending.
  stop() {
    if (this.playing) {
      this.playing = false;
      this.port.postMessage({ type: "idle", consumed: this.consumed });
    }
    this.waited = 0;
  }

  process(_inputs, outputs) {
    const output = outputs[0][0];
    const threshold = START_SECONDS * sampleRate;
    if (!this.playing && this.buffered > 0) {
      this.waited += output.length;
      if (this.buffered >= threshold || this.waited >= threshold) {
        this.playing = true;
      }
    }
    let written = 0;
    while (this.playing && written < output.length && this.queue.length > 0) {
      const head = this.queue[0];
      const take = Math.min(head.length - this.offset, output.length - written);
      for (let index = 0; index < take; index += 1) {
        const value = head[this.offset + index] * this.gain;
        output[written + index] = value;
        this.sum += Math.abs(value);
      }
      written += take;
      this.offset += take;
      this.buffered -= take;
      if (this.offset === head.length) {
        this.queue.shift();
        this.offset = 0;
        this.consumed += 1;
      }
    }
    output.fill(0, written);
    if (this.playing && this.queue.length === 0) {
      this.stop();
    }
    if (this.observe) {
      this.quanta += 1;
      if (this.quanta % REPORT_EVERY === 0) {
        this.port.postMessage({ type: "sum", sum: this.sum });
      }
    }
    return true;
  }
}

registerProcessor("vinga-capture", Capture);
registerProcessor("vinga-playback", Playback);
