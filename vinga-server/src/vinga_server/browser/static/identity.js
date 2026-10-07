// Who this browser is, as a device: kept in its own storage, and only
// ever handed to it by the server (#613, D1, D4, D5).
//
// Two requests hand an identity over. An invite link's token, read from the
// page's fragment, is redeemed with one same-origin POST, which answers
// the identity and the onboarding path to check in at. A browser that
// holds no identity and no link starts from the onboarding URL instead,
// pasted once, and asks the server to mint one under it, which it then
// pairs with by the code its check-in shows. No script here invents a
// MAC.
//
// The device token is not kept: the page checks in before every
// conversation, as a board does at boot, and holds the token it is
// handed in memory for that conversation alone.

import * as urls from "./urls.js";

// One key, so clearing it is clearing the device: a cleared browser is
// a new, unbound one.
const STORAGE_KEY = "vinga.browser";

export class Refused extends Error {}

export function stored() {
  let kept = null;
  try {
    kept = JSON.parse(localStorage.getItem(STORAGE_KEY));
  } catch {
    return null;
  }
  if (kept === null || typeof kept !== "object") {
    return null;
  }
  const onboardingPath = urls.onboardingPath(kept.onboarding_path);
  if (typeof kept.mac !== "string" || typeof kept.client_id !== "string" || onboardingPath === null) {
    return null;
  }
  return { mac: kept.mac, clientId: kept.client_id, onboardingPath };
}

// Kept as the path the onboarding path resolves to on this origin,
// prefix included, which is the shape the page has stored it in since
// the invite link first did; read back through `urls.onboardingPath`, which
// takes either shape.
function keep(answer, onboardingPath) {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        mac: answer.mac,
        client_id: answer.client_id,
        onboarding_path: urls.onboarding(onboardingPath).pathname,
      }),
    );
  } catch {
    throw new Refused(
      "This browser will not keep what the server handed it, so it cannot join. Allow this site to store data and try again.",
    );
  }
  return { mac: answer.mac, clientId: answer.client_id, onboardingPath };
}

async function answered(request, fallback) {
  let answer;
  try {
    answer = await request;
  } catch {
    throw new Refused("This page could not reach the server. Check the connection and try again.");
  }
  let body = null;
  try {
    body = await answer.json();
  } catch {
    body = null;
  }
  if (!answer.ok || body === null || typeof body.mac !== "string" || typeof body.client_id !== "string") {
    throw new Refused(body !== null && typeof body.error === "string" ? body.error : fallback);
  }
  return body;
}

// Spend an invite link's token. What comes back is this browser's identity
// and the onboarding path it checks in at.
export async function redeem(token) {
  const body = await answered(
    fetch(urls.redeem(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
      cache: "no-store",
      credentials: "omit",
      referrerPolicy: "no-referrer",
    }),
    "This invite link cannot be used.",
  );
  const onboardingPath = urls.onboardingPath(body.onboarding_path);
  if (onboardingPath === null) {
    throw new Refused("This invite link cannot be used.");
  }
  return keep(body, onboardingPath);
}

// Ask the server for an identity under the onboarding URL a person
// pasted. The server mints one on every deployment; what admits the
// browser is the claim of the code it is shown next.
export async function start(pasted) {
  const onboardingPath = urls.pasted(pasted.trim());
  if (onboardingPath === null) {
    throw new Refused(
      "That is not this server's onboarding address: paste the whole URL its operator gave you, " +
        "and open this page at the address it names if it names another address than this one.",
    );
  }
  const body = await answered(
    fetch(urls.onboarding(onboardingPath, "try-identity"), {
      method: "POST",
      cache: "no-store",
      credentials: "omit",
      referrerPolicy: "no-referrer",
    }),
    "This server did not accept that onboarding address.",
  );
  return keep(body, onboardingPath);
}
