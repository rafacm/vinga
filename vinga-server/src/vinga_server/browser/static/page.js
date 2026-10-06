// The browser client's page (#613). Two things so far: it proves a page
// served at /try/ can import a module from its versioned static path
// under the page's Content-Security-Policy, and it redeems a try link.
//
// A try link is `<origin>/try/#<token>`. The token is in the fragment,
// which the browser sends to no server, so this script is the only
// thing that ever reads it: it takes it, clears it from the address bar
// and from this history entry before doing anything else, and spends it
// with one same-origin POST. What comes back is this browser's identity
// and the onboarding path it checks in at, kept in this browser's own
// storage and nowhere else. The page's address stays /try/ throughout.
document.documentElement.dataset.vingaAssets = "loaded";

// Where the identity is kept. One key, so clearing it is clearing the
// device: a cleared browser is a new, unbound one.
const STORAGE_KEY = "vinga.browser";

const REDEEM_PATH = "/try/redeem";

function say(sentence) {
  const status = document.getElementById("status");
  if (status !== null) {
    status.textContent = sentence;
  }
}

async function redeem(token) {
  let answer;
  try {
    answer = await fetch(REDEEM_PATH, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
      cache: "no-store",
      credentials: "omit",
      referrerPolicy: "no-referrer",
    });
  } catch {
    say("This page could not reach the server. Check the connection and open the link again.");
    return;
  }
  let body = null;
  try {
    body = await answer.json();
  } catch {
    body = null;
  }
  if (!answer.ok || body === null || typeof body.mac !== "string") {
    say(body !== null && typeof body.error === "string" ? body.error : "This try link cannot be used.");
    return;
  }
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        mac: body.mac,
        client_id: body.client_id,
        onboarding_path: body.onboarding_path,
      }),
    );
  } catch {
    say("This browser will not keep what the server handed it, so it cannot join. Allow this site to store data and ask for a new link.");
    return;
  }
  document.documentElement.dataset.vingaBound = "true";
  say("This browser is now a device of this server, bound to its default agent.");
}

const token = window.location.hash.slice(1);
if (token !== "") {
  // Before anything else, so the token is gone from the address bar and
  // from the history entry whatever happens next.
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
  redeem(token);
}
