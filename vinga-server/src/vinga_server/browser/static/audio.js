// The microphone and the speaker, as a board has them (#613, D3, D3b).
//
// The microphone is the browser's own capture with echo cancellation
// and noise suppression asked for, resampled to 16 kHz by an
// AudioContext running at that rate, cut into 60 ms blocks by the
// capture processor and encoded by WebCodecs' Opus encoder with a 60 ms
// frame, which is what a board sends and what the server's hello
// expects. The speaker decodes the server's Opus at the rate its hello
// named and plays it through the playback processor.
//
// Nothing here knows the protocol. The microphone hands each packet to
// whoever opened it; the speaker is handed packets and says when what
// it was handed has finished sounding.

const CAPTURE_RATE = 16000;
const FRAME_SAMPLES = 960;
const FRAME_US = 60000;

const WORKLET = new URL("./audio-worklet.js", import.meta.url);

const ENCODER = {
  codec: "opus",
  sampleRate: CAPTURE_RATE,
  numberOfChannels: 1,
  bitrate: 24000,
  opus: { frameDuration: FRAME_US, application: "voip" },
};

function decoderConfig(sampleRate) {
  return { codec: "opus", sampleRate, numberOfChannels: 1 };
}

// What this browser lacks that the client needs, as words a person can
// read, or an empty list. Asked before anything starts, so a browser
// that cannot run the client says so and does nothing half-way.
export async function missing() {
  const lacks = [];
  if (!window.isSecureContext) {
    lacks.push("a secure connection (open this page over https, or on localhost)");
  }
  if (!navigator.mediaDevices || typeof navigator.mediaDevices.getUserMedia !== "function") {
    lacks.push("microphone access");
  }
  if (typeof AudioWorkletNode === "undefined") {
    lacks.push("AudioWorklet");
  }
  if (typeof AudioEncoder === "undefined" || typeof AudioDecoder === "undefined") {
    lacks.push("WebCodecs audio");
  } else {
    const encodes = await AudioEncoder.isConfigSupported(ENCODER).catch(() => null);
    const decodes = await AudioDecoder.isConfigSupported(decoderConfig(24000)).catch(() => null);
    if (encodes === null || !encodes.supported || decodes === null || !decodes.supported) {
      lacks.push("the Opus codec in WebCodecs");
    }
  }
  return lacks;
}

export class Microphone {
  // `echoCancelled` is what the track reports, unless `assumeNoEcho`
  // says to treat it as false: the lane's switch, since a fake capture
  // device always reports true.
  static async open({ onPacket, assumeNoEcho }) {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
      },
    });
    const track = stream.getAudioTracks()[0];
    const reported = track.getSettings().echoCancellation === true;
    const microphone = new Microphone(stream, reported && !assumeNoEcho, onPacket);
    try {
      await microphone.start();
    } catch (failure) {
      // The capture was granted before the rest was built: whatever
      // failed after it, stop every track, or the browser goes on
      // listening for a microphone nothing will ever read.
      microphone.close();
      throw failure;
    }
    return microphone;
  }

  constructor(stream, echoCancelled, onPacket) {
    this.stream = stream;
    this.echoCancelled = echoCancelled;
    this.onPacket = onPacket;
    this.context = null;
    this.encoder = null;
    this.timestamp = 0;
  }

  async start() {
    this.encoder = new AudioEncoder({
      output: (chunk) => {
        const packet = new Uint8Array(chunk.byteLength);
        chunk.copyTo(packet);
        this.onPacket(packet);
      },
      error: () => this.close(),
    });
    this.encoder.configure(ENCODER);
    this.context = new AudioContext({ sampleRate: CAPTURE_RATE });
    await this.context.audioWorklet.addModule(WORKLET);
    const source = this.context.createMediaStreamSource(this.stream);
    const capture = new AudioWorkletNode(this.context, "vinga-capture", {
      numberOfInputs: 1,
      numberOfOutputs: 0,
      channelCount: 1,
      channelCountMode: "explicit",
    });
    capture.port.onmessage = (event) => this.encode(event.data);
    source.connect(capture);
    await this.context.resume();
  }

  encode(samples) {
    if (this.encoder === null || this.encoder.state !== "configured") {
      return;
    }
    const block = new AudioData({
      format: "f32",
      sampleRate: CAPTURE_RATE,
      numberOfFrames: FRAME_SAMPLES,
      numberOfChannels: 1,
      timestamp: this.timestamp,
      data: samples,
    });
    this.timestamp += FRAME_US;
    this.encoder.encode(block);
    block.close();
  }

  close() {
    for (const track of this.stream.getTracks()) {
      track.stop();
    }
    if (this.encoder !== null && this.encoder.state !== "closed") {
      this.encoder.close();
    }
    this.encoder = null;
    if (this.context !== null) {
      this.context.close().catch(() => {});
      this.context = null;
    }
  }
}

export class Speaker {
  // `observe` is the lane's switch: only with it does the playback
  // processor report the running sum of what it rendered, and only
  // then does `onSum` ever hear from it.
  static async open({ sampleRate, volume, observe, onSum }) {
    const context = new AudioContext({ sampleRate });
    await context.audioWorklet.addModule(WORKLET);
    const node = new AudioWorkletNode(context, "vinga-playback", {
      numberOfInputs: 0,
      numberOfOutputs: 1,
      outputChannelCount: [1],
      processorOptions: { observe },
    });
    node.connect(context.destination);
    await context.resume();
    const speaker = new Speaker(context, node, sampleRate, onSum);
    speaker.setVolume(volume);
    return speaker;
  }

  constructor(context, node, sampleRate, onSum) {
    this.context = context;
    this.node = node;
    this.posted = 0;
    this.consumed = 0;
    this.whenIdle = [];
    this.decoder = new AudioDecoder({
      output: (data) => this.play(data),
      error: () => {},
    });
    this.decoder.configure(decoderConfig(sampleRate));
    this.node.port.onmessage = (event) => {
      const message = event.data;
      if (message.type === "idle") {
        this.consumed = message.consumed;
        this.settle();
      } else if (message.type === "sum") {
        onSum(message.sum);
      }
    };
    this.timestamp = 0;
  }

  receive(packet) {
    if (this.decoder.state !== "configured") {
      return;
    }
    const chunk = new EncodedAudioChunk({ type: "key", timestamp: this.timestamp, data: packet });
    this.timestamp += FRAME_US;
    this.decoder.decode(chunk);
  }

  play(data) {
    const samples = new Float32Array(data.numberOfFrames);
    data.copyTo(samples, { planeIndex: 0, format: "f32-planar" });
    data.close();
    this.posted += 1;
    this.node.port.postMessage({ type: "append", samples }, [samples.buffer]);
  }

  setVolume(volume) {
    this.node.port.postMessage({ type: "gain", gain: volume / 100 });
  }

  // Whatever has been handed over and not yet heard is dropped: the
  // person interrupted, or the conversation ended.
  flush() {
    this.node.port.postMessage({ type: "flush" });
  }

  // Resolves once everything received so far has been decoded and has
  // finished sounding, which is when a board in auto mode opens its
  // microphone again after a reply.
  async idle() {
    if (this.decoder.state === "configured") {
      await this.decoder.flush().catch(() => {});
    }
    return new Promise((resolve) => {
      this.whenIdle.push(resolve);
      this.settle();
    });
  }

  settle() {
    if (this.consumed < this.posted) {
      return;
    }
    const waiting = this.whenIdle;
    this.whenIdle = [];
    for (const resolve of waiting) {
      resolve();
    }
  }

  close() {
    if (this.decoder.state !== "closed") {
      this.decoder.close();
    }
    this.context.close().catch(() => {});
  }
}
