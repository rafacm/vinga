# An unbound device only pairs

**Status:** Accepted (recorded 2026-10-07, deciding
[#612](https://github.com/rafacm/vinga/issues/612), decision 10).

## Context

Until this record, a device with no binding of its own reached the
deployment's `default_agent` when one was set, and was turned away
otherwise. The rule had two homes that had to agree,
`DeviceBindings._bound` (`device/bindings.py`) and
`Config.agents_for_device` (`config/models.py`), both "the bound list
else the default agent else nothing", and it reached five more places
that existed only because of it:

- the OTA check-in issued a token to any unknown MAC while a default
  agent was set, so whoever held the onboarding path could reach that
  agent with a made-up MAC and no code;
- the boot refused a configuration with agents, no default agent and
  no bound device, because no device could have reached any agent;
- a claim by activation code was refused (`ALREADY_COVERED`) once a
  default agent was set, since the default already covered the board;
- the browser mint refused while a default agent was set (#613, D4a),
  because a browser minted there would have reached the default agent
  unbound, and refused again when it could not find out;
- setting a default agent retired every code in the pending table.

So a default agent was two things at once: the agent a new device
starts with, and an admission rule that let every unknown device in.
The second meaning is what #612 rules out. A deployment that serves a
built-in agent to every device (#612, decisions 1 to 3) cannot also let
every unknown MAC reach whatever the default is: a server reachable
from a public network would then answer anybody who guessed its
onboarding path, and the only way to stop that was to leave the default
unset, which gave up the first meaning to keep the second honest.

## Decision

An unbound device gets pairing and nothing else, on every deployment.

- **The devices map is always the allowlist.** A device reaches the
  agents its own record names and no others. With onboarding on it is
  offered an activation code; with `server.onboarding.enabled: false`
  it gets neither a code nor a token, and is bound by MAC.
- **`default_agent` is the agent a newly bound device starts with.** A
  claim that names no agent binds the board to it, read inside the
  claim's own transaction, and the acknowledgement names the agent it
  bound. It no longer admits anything.
- **The rule has one home.** `Config.bound_to(mac)` is the snapshot's
  binding, and `DeviceBindings` answers the stored row or that, with no
  fallback in either.
- **No localhost exception.** A server on a laptop pairs its boards the
  same way a public one does: one more rule to explain, for a ceremony
  that costs one command, buys less than it costs.

What went with the old meaning: the boot rule (a deployment with agents
and no devices is one awaiting its first claim), the claim's
`ALREADY_COVERED` refusal, both of the browser mint's D4a refusals (a
cleared browser now always pairs), the pending table's "a default agent
covers every device" housekeeping, and the default-agent row in the
live binding read.

## Consequences

- **Boards that reached the default agent unbound show pairing codes
  after the upgrade.** Each costs one command,
  `vinga device pending claim <code>`, which with no agent named binds
  it to the default it was already reaching; `vinga device pending
  list` shows them all. A board bound by MAC is unaffected. The
  changelog fragment carries this as its `Upgrade:` line.
- **The live binding read is one statement, not two.** The byte pin on
  it (`tests/unit/test_live_binding_pin.py`) moved deliberately, in a
  commit of its own, rather than as part of a reshape.
- **A default agent naming an agent the server is not serving changes
  no device's check-in**, so its notice waits at the install alone.
- **Try links are unchanged for now.** A link still binds a browser to
  the default agent and is refused while none is set; #612's later
  milestones replace it with an invite command and make the default
  always exist.
- **Reversing this** would bring back every one of the five sites
  above, and the question #612 settled: what an unknown device on a
  public network may reach without anybody having said so.
