// One conversation over the device socket, spoken as a stock board
// speaks it (#613, Q3, Q4, D3, D9).
//
// The credential: a browser's WebSocket cannot set a header, so the
// identity and the token a board sends in `Device-Id`, `Client-Id` and
// `Authorization` are offered as subprotocols instead, beside the
// versioned protocol the server selects. With device authentication off
// the check-in hands over no token and none is offered.
//
// The rest is the board's: a hello naming Opus at 16 kHz in 60 ms
// frames and MCP among its features, the server's hello naming the
// rate its replies come at, one `listen start` in the mode this
// browser can support, Opus both ways, and the server's `stt`, `tts`
// and `mcp` messages. Which mode is the echo canceller's to decide, as
// it is a board's: with echo cancellation a realtime session keeps the
// microphone open through a reply, which is what lets a person cut in;
// without it the browser listens in auto mode, sends nothing while a
// reply plays, and asks to listen again once the reply has finished
// sounding, so it never hears itself.
//
// The ending is the server's close. An idle timeout closes a realtime
// session nobody is talking in; the person is told that, and anything
// else as an ordinary end, and may start again.

import * as tools from "./tools.js";
import * as urls from "./urls.js";

const PROTOCOL = "vinga.device.v1";

// How long a board waits for the server's hello before giving up.
const HELLO_TIMEOUT_MS = 10000;

// What the server's close says when it hung up on a quiet session. Its
// own words, in `device/session.py`.
const IDLE_REASON = "idle timeout";

const NORMAL_CLOSURE = 1000;

const HELLO = {
  type: "hello",
  version: 1,
  features: { mcp: true },
  transport: "websocket",
  audio_params: { format: "opus", sample_rate: 16000, channels: 1, frame_duration: 60 },
};

function subprotocols(identity, token) {
  const offered = [
    PROTOCOL,
    `vinga.mac.${identity.mac.replaceAll(":", "")}`,
    `vinga.client.${identity.clientId}`,
  ];
  if (token) {
    offered.push(`vinga.token.${token}`);
  }
  return offered;
}

export class Ended extends Error {}

export class Conversation {
  // `token` is the check-in's, or empty. `mode` is `realtime` or `auto`.
  // `openSpeaker(rate)` builds the speaker once the server has named
  // its rate. `device` is what the tools reach. `on` is told what the
  // person should see: `transcript`, `sentence`, `speaking`, `ended`.
  static open({ identity, token, mode, openSpeaker, device, on }) {
    return new Promise((resolve, reject) => {
      const socket = new WebSocket(urls.socket(), subprotocols(identity, token));
      socket.binaryType = "arraybuffer";
      const conversation = new Conversation(socket, mode, device, on);
      const timer = setTimeout(() => {
        socket.close();
        reject(new Ended("The server did not answer this browser's hello."));
      }, HELLO_TIMEOUT_MS);
      socket.onopen = () => socket.send(JSON.stringify(HELLO));
      socket.onclose = (event) => {
        clearTimeout(timer);
        reject(new Ended(event.code === 1006 ? "The server refused this browser's connection." : event.reason));
      };
      // What arrives between the server's hello and the speaker being
      // ready: the server opens its MCP exchange right after its hello,
      // and a board answers that whenever it reads it, so nothing here
      // may be dropped while the speaker starts.
      const early = [];
      let greeted = false;
      socket.onmessage = async (event) => {
        if (greeted) {
          early.push(event.data);
          return;
        }
        let hello;
        try {
          hello = JSON.parse(event.data);
        } catch {
          return;
        }
        if (hello.type !== "hello" || hello.transport !== "websocket") {
          return;
        }
        greeted = true;
        clearTimeout(timer);
        try {
          const rate = (hello.audio_params && hello.audio_params.sample_rate) || 24000;
          await conversation.begin(hello.session_id || "", await openSpeaker(rate), early);
        } catch (failure) {
          socket.close();
          reject(failure);
          return;
        }
        resolve(conversation);
      };
    });
  }

  constructor(socket, mode, device, on) {
    this.socket = socket;
    this.mode = mode;
    this.device = device;
    this.on = on;
    this.sessionId = "";
    this.speaker = null;
    this.speaking = false;
    // Whether microphone frames may go out right now. The one place the
    // mode's rule about a reply is kept: `send` asks nothing else.
    this.micOpen = false;
    // Counts replies, so a reply that starts while the last one is still
    // draining does not have the microphone opened under it.
    this.replies = 0;
    this.ending = null;
  }

  // From here every message is the conversation's: first the ones that
  // arrived while the speaker started, in order, then the rest as they
  // come. One synchronous step, so nothing can arrive in between.
  begin(sessionId, speaker, early) {
    this.sessionId = sessionId;
    this.speaker = speaker;
    this.socket.onmessage = (event) => this.receive(event.data);
    this.socket.onclose = (event) => this.closed(event);
    for (const data of early.splice(0)) {
      this.receive(data);
    }
    this.listen();
  }

  message(body) {
    return JSON.stringify({ session_id: this.sessionId, ...body });
  }

  listen() {
    this.socket.send(this.message({ type: "listen", state: "start", mode: this.mode }));
    this.micOpen = true;
  }

  listening() {
    return this.micOpen;
  }

  // One encoded microphone frame. Dropped while the mode says the
  // microphone is closed: in auto mode, from a reply's `tts start`
  // until it has finished sounding.
  send(packet) {
    if (!this.micOpen || this.socket.readyState !== WebSocket.OPEN) {
      return;
    }
    this.socket.send(packet);
  }

  receive(data) {
    if (data instanceof ArrayBuffer) {
      this.speaker.receive(new Uint8Array(data));
      return;
    }
    let message;
    try {
      message = JSON.parse(data);
    } catch {
      return;
    }
    switch (message.type) {
      case "stt":
        this.on.transcript(String(message.text || ""));
        break;
      case "tts":
        this.tts(message);
        break;
      case "mcp": {
        const reply = tools.answer(message.payload, this.device);
        if (reply !== null) {
          this.socket.send(this.message({ type: "mcp", payload: reply }));
        }
        break;
      }
      default:
        break;
    }
  }

  tts(message) {
    if (message.state === "start") {
      this.speaking = true;
      this.replies += 1;
      if (this.mode === "auto") {
        this.micOpen = false;
      }
      this.on.speaking(true);
    } else if (message.state === "sentence_start") {
      this.on.sentence(String(message.text || ""));
    } else if (message.state === "stop") {
      this.speaking = false;
      this.on.speaking(false);
      if (this.mode === "auto") {
        this.rearm(this.replies);
      }
    }
  }

  // Auto mode's turn back to the person, as the firmware takes it: once
  // what the reply sent has finished sounding, ask to listen again and
  // open the microphone.
  async rearm(reply) {
    await this.speaker.idle();
    if (reply !== this.replies || this.speaking || this.socket.readyState !== WebSocket.OPEN) {
      return;
    }
    this.listen();
  }

  // The person cut the reply short, as a board's button does while it
  // speaks: tell the server, and drop what is still waiting to sound.
  interrupt() {
    if (!this.speaking || this.socket.readyState !== WebSocket.OPEN) {
      return;
    }
    this.socket.send(this.message({ type: "abort" }));
    this.speaker.flush();
  }

  // The person ended the conversation.
  end() {
    this.ending = "ended";
    this.socket.close(NORMAL_CLOSURE);
  }

  closed(event) {
    this.micOpen = false;
    this.speaking = false;
    if (this.speaker !== null) {
      this.speaker.flush();
    }
    let why = "closed";
    if (this.ending !== null) {
      why = this.ending;
    } else if (event.code === NORMAL_CLOSURE && event.reason === IDLE_REASON) {
      why = "idle";
    }
    this.on.ended(why);
  }
}
