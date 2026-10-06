// The browser lane's instrumentation (#613), added to every page the lane
// opens before any of the page's own scripts run. It watches the
// client from outside, through the browser APIs the client calls, and
// changes nothing the client sees: it records the microphone streams
// the page is handed, when the page sent `listen start` and `abort` and
// received `tts stop`, and what passed between the page and its
// playback processor (the processor's `idle` reports, and every message
// to it but the audio itself). Every record is a timestamp on the page's
// own clock, so the lane can order what the client did against what the
// speaker reported. Nothing here ships: it lives beside the lane.
(() => {
  const lane = { streams: [], listens: [], aborts: [], stops: [], playback: [] };
  window.__lane = lane;
  const now = () => performance.now();

  const media = navigator.mediaDevices;
  if (media && typeof media.getUserMedia === "function") {
    const getUserMedia = media.getUserMedia.bind(media);
    media.getUserMedia = async (constraints) => {
      const stream = await getUserMedia(constraints);
      lane.streams.push(stream);
      return stream;
    };
  }

  const read = (data) => {
    if (typeof data !== "string") {
      return null;
    }
    try {
      return JSON.parse(data);
    } catch {
      return null;
    }
  };

  const NativeSocket = window.WebSocket;
  window.WebSocket = class extends NativeSocket {
    constructor(...args) {
      super(...args);
      this.addEventListener("message", (event) => {
        const message = read(event.data);
        if (message !== null && message.type === "tts" && message.state === "stop") {
          lane.stops.push(now());
        }
      });
    }

    send(data) {
      const message = read(data);
      if (message !== null && message.type === "listen" && message.state === "start") {
        lane.listens.push(now());
      } else if (message !== null && message.type === "abort") {
        lane.aborts.push(now());
      }
      return super.send(data);
    }
  };

  const NativeNode = window.AudioWorkletNode;
  if (NativeNode !== undefined) {
    window.AudioWorkletNode = class extends NativeNode {
      constructor(context, name, options) {
        super(context, name, options);
        if (name !== "vinga-playback") {
          return;
        }
        // Registered before the page sets `onmessage`, which is what
        // starts the port, so both hear every report and this one first.
        this.port.addEventListener("message", (event) => {
          if (event.data && event.data.type === "idle") {
            lane.playback.push(["idle", now()]);
          }
        });
        const post = this.port.postMessage.bind(this.port);
        this.port.postMessage = (message, transfer) => {
          if (message && message.type !== "append") {
            lane.playback.push([message.type, now()]);
          }
          return transfer === undefined ? post(message) : post(message, transfer);
        };
      }
    };
  }
})();
