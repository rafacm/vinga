// The check-in, and the wait for a claim, as a board makes them
// (#613, D3, D4).
//
// A board POSTs to its OTA URL at every boot, naming itself in the
// `Device-Id` and `Client-Id` headers, and is answered with where to
// connect and the token to connect with, or with a six-digit code to
// show while it waits to be claimed. A same-origin `fetch` may set both
// headers, so the page makes exactly that request, under the onboarding
// path, before every conversation. `board.type` names it a browser to
// every surface that reports what a device said it was.

import * as urls from "./urls.js";

const BOARD_TYPE = "vinga-browser";

// What a board waits between activation polls, and how many it makes
// before checking in again for a fresh code.
const POLL_MS = 3000;
const POLLS_PER_CHECK_IN = 10;

export class Unreachable extends Error {}

function headers(identity) {
  return {
    "Content-Type": "application/json",
    "Device-Id": identity.mac,
    "Client-Id": identity.clientId,
  };
}

// The OTA reply, or Unreachable. `access` says how to read the token:
// `token` admitted with one, `open` admitted with none to present,
// `denied` not admitted, in which case an `activation` section, when
// present, carries the code to show.
export async function checkIn(identity) {
  let answer;
  try {
    answer = await fetch(urls.onboarding(identity.onboardingPath), {
      method: "POST",
      headers: headers(identity),
      body: JSON.stringify({ board: { type: BOARD_TYPE } }),
      cache: "no-store",
      credentials: "omit",
      referrerPolicy: "no-referrer",
    });
  } catch {
    throw new Unreachable("This page could not reach the server.");
  }
  if (!answer.ok) {
    throw new Unreachable("The server did not accept this browser's check-in.");
  }
  try {
    return await answer.json();
  } catch {
    throw new Unreachable("The server's answer to the check-in could not be read.");
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Poll as the firmware does until the code is claimed, checking in
// again after each burst so the code on screen is always one the
// server still holds. `onCode` is told every code there is to show;
// what resolves is the first check-in that admits this browser.
export async function waitForClaim(identity, reply, onCode, cancelled) {
  let current = reply;
  for (;;) {
    if (current.access !== "denied") {
      return current;
    }
    if (current.activation && typeof current.activation.code === "string") {
      onCode(current.activation.code);
    } else {
      onCode(null);
    }
    for (let poll = 0; poll < POLLS_PER_CHECK_IN; poll += 1) {
      await sleep(POLL_MS);
      if (cancelled()) {
        return null;
      }
      if (current.activation) {
        const polled = await fetch(urls.onboarding(identity.onboardingPath, "activate"), {
          method: "POST",
          headers: { ...headers(identity), "Activation-Version": "1" },
          body: "{}",
          cache: "no-store",
          credentials: "omit",
          referrerPolicy: "no-referrer",
        }).catch(() => null);
        if (polled !== null && polled.status === 200) {
          break;
        }
      }
    }
    current = await checkIn(identity);
  }
}
