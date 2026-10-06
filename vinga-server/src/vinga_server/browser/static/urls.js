// Every address the client reaches, resolved against where this server
// served it (#613).
//
// A deployment may be published under a path (`server.public_url` of
// `https://example.org/vinga`), so nothing here is root-relative: the
// deployment's root is read off this module's own address, which is
// `<root>try/static/<version>/urls.js` however the page itself was
// spelled, and every request is resolved against it. The other modules
// ask here and never build a URL of their own.

const ROOT = new URL("../../../", import.meta.url);

// The onboarding path in the one form the client keeps: relative to the
// root, `x/<key>/` (or `x/` on a keyless deployment). Accepts what a
// redemption hands over and what a person pastes, which is the whole
// onboarding URL `vinga info` printed, and answers null for anything
// that is not one.
export function onboardingPath(value) {
  let path;
  try {
    path = new URL(value, ROOT).pathname;
  } catch {
    return null;
  }
  const at = path.lastIndexOf("/x/");
  if (at === -1) {
    return null;
  }
  const relative = path.slice(at + 1);
  return relative.endsWith("/") ? relative : `${relative}/`;
}

// The onboarding path in an onboarding URL a person pasted, in the same
// relative form, or null when it is not this deployment's. Only a whole
// URL is taken, and only one that names this page's own origin and this
// deployment's root: the key in an onboarding URL is that deployment's
// secret, and the request this path is used for would carry it to
// whatever served this page. A bare path is refused as well, since it
// cannot say which deployment it came from, and what `vinga info`
// prints is always a whole URL.
export function pasted(value) {
  let url;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  const rest = url.pathname.slice(ROOT.pathname.length);
  if (url.origin !== ROOT.origin || !url.pathname.startsWith(ROOT.pathname) || !rest.startsWith("x/")) {
    return null;
  }
  return onboardingPath(rest);
}

// A request under the onboarding path: the check-in itself, `activate`
// and `try-identity`.
export function onboarding(path, segment = "") {
  return new URL(`${path}${segment}`, ROOT);
}

// The redemption of a try link, beside the page.
export function redeem() {
  return new URL("try/redeem", ROOT);
}

// The device socket: the path the server named in the page it served,
// under this deployment's root, over ws or wss to match the page.
export function socket() {
  const meta = document.querySelector('meta[name="vinga-socket"]');
  const url = new URL(meta === null ? "" : meta.content, ROOT);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url;
}
