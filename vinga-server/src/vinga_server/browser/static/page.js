// What the person sees, and the order things happen in (#613, D3).
//
// The page is inert until its script runs. A try link is
// `<origin>/try/#<token>`; the token is in the fragment, which the
// browser sends to no server, so this script is the only thing that
// ever reads it: it takes it and clears it from the address bar and
// from this history entry before anything else, then spends it once.
//
// After that: a browser that cannot run the client says what it lacks
// and does nothing more; one without an identity is asked for the
// onboarding URL; one with an identity offers Start. Start opens the
// microphone, checks in, shows a six-digit code while the browser waits
// to be claimed, connects, and listens. The conversation ends when the
// server closes it or the person ends it, and Start begins another.
//
// Two switches are the browser lane's and do nothing unless the page's
// own address names them: `test-observe=1` publishes, as attributes of
// the document, the running sum of what the speaker rendered and the
// gain it applies, and
// `test-echo-cancellation=off` makes the page treat its microphone as
// one without echo cancellation, since a fake capture device always
// reports it on.

import { Microphone, missing, Speaker } from "./audio.js";
import * as identity from "./identity.js";
import * as ota from "./ota.js";
import { Conversation } from "./wire.js";

const token = window.location.hash.slice(1);
if (token !== "") {
  // Before anything else, so the token is gone from the address bar and
  // from the history entry whatever happens next.
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
}

const switches = new URLSearchParams(window.location.search);
const OBSERVE = switches.get("test-observe") === "1";
const ASSUME_NO_ECHO = switches.get("test-echo-cancellation") === "off";

// Where a board's volume starts.
const DEFAULT_VOLUME = 70;

const ENDINGS = {
  idle: "The conversation ended because nobody spoke for a while.",
  ended: "You ended the conversation.",
  closed: "The conversation ended.",
};

const element = (id) => document.getElementById(id);

function say(sentence) {
  element("status").textContent = sentence;
}

function show(id, visible) {
  element(id).hidden = !visible;
}

function line(who, text) {
  if (text === "") {
    return;
  }
  const item = document.createElement("li");
  item.textContent = `${who}: ${text}`;
  element("transcript").append(item);
}

let device = null;
let volume = DEFAULT_VOLUME;
let microphone = null;
let speaker = null;
let conversation = null;
let starting = false;

function setVolume(value) {
  volume = value;
  element("volume").textContent = `Volume ${volume}`;
  if (speaker !== null) {
    speaker.setVolume(volume);
  }
}

// What the device tools reach.
const tools = {
  volume: () => volume,
  setVolume,
  listening: () => conversation !== null && conversation.listening(),
};

function idleControls() {
  show("start", device !== null);
  show("interrupt", false);
  show("end", false);
}

function release() {
  if (microphone !== null) {
    microphone.close();
    microphone = null;
  }
  if (speaker !== null) {
    speaker.close();
    speaker = null;
  }
  conversation = null;
}

async function start() {
  if (starting || conversation !== null) {
    return;
  }
  starting = true;
  show("start", false);
  show("code", false);
  try {
    // The check-in first, and the microphone only once there is a
    // conversation to open it for: a browser waiting to be claimed is
    // not listening to anybody.
    say("Checking in with the server.");
    let reply = await ota.checkIn(device);
    if (reply.access === "denied") {
      reply = await ota.waitForClaim(
        device,
        reply,
        (code) => {
          show("code", code !== null);
          element("code").textContent = code === null ? "" : code;
          say(
            code === null
              ? "This server has no agent for this browser yet. Waiting."
              : "Tell the person who runs this server this code, so they can connect this browser.",
          );
        },
      );
      show("code", false);
    }
    say("Opening the microphone.");
    try {
      microphone = await Microphone.open({
        onPacket: (packet) => conversation !== null && conversation.send(packet),
        assumeNoEcho: ASSUME_NO_ECHO,
      });
    } catch {
      throw new Error("This page cannot use the microphone. Allow it for this site and press Start again.");
    }
    const mode = microphone.echoCancelled ? "realtime" : "auto";
    show("no-interrupt", mode === "auto");
    say("Connecting.");
    conversation = await Conversation.open({
      identity: device,
      token: reply.access === "token" ? reply.websocket.token : "",
      mode,
      device: tools,
      openSpeaker: async (sampleRate) => {
        speaker = await Speaker.open({
          sampleRate,
          volume,
          observe: OBSERVE,
          onObserved: ({ sum, gain }) => {
            document.documentElement.dataset.vingaPcmSum = String(sum);
            document.documentElement.dataset.vingaGain = String(gain);
          },
        });
        return speaker;
      },
      on: {
        transcript: (text) => line("You", text),
        sentence: (text) => line("Reply", text),
        speaking: (speaking) => {
          show("interrupt", speaking);
          say(speaking ? "Speaking." : "Listening.");
        },
        ended: (why) => {
          release();
          say(ENDINGS[why]);
          element("start").textContent = "Start again";
          idleControls();
        },
      },
    });
    show("end", true);
    say("Listening. Say something.");
  } catch (failure) {
    release();
    say(failure.message || "The conversation could not start.");
    element("start").textContent = "Start again";
    idleControls();
  } finally {
    starting = false;
  }
}

async function join() {
  try {
    device = await identity.start(element("onboarding").value);
  } catch (refusal) {
    say(refusal.message);
    return;
  }
  show("pair", false);
  say("This browser is now a device of this server. Press Start to talk.");
  idleControls();
}

async function main() {
  const lacks = await missing();
  if (lacks.length > 0) {
    say(`This browser cannot run vinga's client: it lacks ${lacks.join(", ")}.`);
    return;
  }
  element("start").addEventListener("click", start);
  element("interrupt").addEventListener("click", () => conversation !== null && conversation.interrupt());
  element("end").addEventListener("click", () => conversation !== null && conversation.end());
  element("join").addEventListener("click", join);
  setVolume(DEFAULT_VOLUME);
  if (token !== "") {
    try {
      device = await identity.redeem(token);
      document.documentElement.dataset.vingaBound = "true";
      say("This browser is now a device of this server, bound to its default agent. Press Start to talk.");
    } catch (refusal) {
      say(refusal.message);
    }
  }
  if (device === null) {
    device = identity.stored();
  }
  if (device === null) {
    show("pair", true);
    if (token === "") {
      say("Paste the onboarding URL this server's operator gave you, or open a try link.");
    }
    return;
  }
  if (token === "") {
    say("Press Start to talk.");
  }
  idleControls();
}

main();
