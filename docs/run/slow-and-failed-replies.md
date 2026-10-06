# Masking slow replies and saying when one fails

At the end of this guide you will have chosen whether an agent fills a
slow reply's silence with a short phrase, and after how long, and what
it says when a reply fails outright, or that it says nothing; and you
will know what each costs at a server start and at an apply.

Both are sections of an agent's configuration, set once on
`agent_defaults` and overridden per agent: their fields and defaults
are in the domain configuration reference under
[Filler](../reference/domain-config.md#filler) and
[Fallback](../reference/domain-config.md#fallback). The first-token
watchdog both of them meet, `llm_first_token_timeout_s`, is in
[Setting limits and probes](limits-and-probes.md#limits).

## Masking reply latency

The silence between the end of an utterance and the first audio of the
reply is where the assistant feels dead: healthy field turns run 1.5
to 3 s of it, and a slow provider stretches it well past the point
where users ask "are you there?". Humans hold exactly this gap with a
filled pause, and an agent can too. `set` replaces the whole
`agent_defaults` entry, the stage fields it names included, so the
section is added to the entry as it stands rather than written alone,
and nothing changes until it is applied:

```bash
vinga-server config agent-defaults export > agent-defaults.yaml
"${EDITOR:-vi}" agent-defaults.yaml    # add the filler section below
vinga-server config agent-defaults set -f agent-defaults.yaml
vinga-server config apply
```

```yaml
filler:
  # off by default
  enabled: true
  delay_ms: 1800
  phrases:
    - "Hmm, let me see..."
    - "Good question..."
```

When a reply's first audio has not started within `delay_ms` of the
utterance being transcribed, the session plays one of the phrases,
rotating through them, and the real reply queues behind the clip's
tail. The clips are synthesized ahead of time in each agent's own voice
and cached as PCM, never at fire time: synthesis at the moment of
masking would add TTS latency to the exact gap being masked, and a
cached clip keeps working when the TTS provider is the thing being
slow. Ahead of time is the server start and every `vinga-server config
apply` after it, which re-synthesizes the agents whose effective
`filler` section or whose voice moved, whichever field of the section it
was, and hands the result to the next conversation; one already open
keeps the clips it opened with. A synthesis failure logs a
warning and leaves the feature off for that agent rather than failing
the boot or refusing the apply.

The filler is honest assistant speech: it moves the device into its
speaking state, counts as the turn's `speaking_started`, lands on
capture channel 1, and enters the barge-in gates like any reply audio,
so talking over it interrupts the reply, which is the correct reading.
One filler per turn, logged as a `filler_played` event; a turn that
outlives both the filler and the first-token watchdog resolves through
the watchdog's give-up path (see below), the filler being the soft
early threshold and the watchdog the hard late one. Write the phrases
in each agent's own language; an agent's own `filler` section replaces
the inherited one wholly, like the stage fields, and the reasoning
behind the default delay is in
[`examples/agent-defaults.yaml`](../../vinga-server/examples/agent-defaults.yaml).

The mask yields to the user. At fire time the timer stands down, with
a `filler_skipped` event, when the endpointer holds unresolved speech
or a barge-in confirmation has the outgoing frames paused. Both mean
the turn ended at a premature endpoint and the user is already mid
continuation: the reply in flight is about to be cancelled, and a
clip played into that would talk over them (field round 2 measured
exactly this on dictation-style turns). The skip consumes no phrase,
and the reply that answers the completed sentence arms its own timer.

## When a reply fails

The other end of the same turn. A reply that fails outright, on a
provider that is down or a model that never answers, used to be
silence: the failure was logged and nothing reached the speaker or the
display, so from the couch a broken pipeline and a slow one were the
same turn. Every agent therefore has a fixed phrase for it, cached the
same way the filled pauses above are, and written the same way, into
the exported entry:

```yaml
fallback:
  # on by default
  enabled: true
  phrase: "I ran into a problem and could not answer. The server log has the details."
```

It is spoken and shown: the sentence goes out as a `tts sentence_start`,
so it renders on the display, and the cached clip follows it, so it is
heard. It is vinga's own words rather than the agent's, and it goes no
further than that turn: it never enters the reply's spoken sentences,
the conversation history or the stored conversation, and `replied`
keeps its meaning of model speech that went out. What says it happened
is a `reply_fallback` event, carrying the reason and whether the phrase
was heard as well as shown, never the words themselves. The phrase is
fixed configuration and is never the failure's own message, which
arrives from the far side of a network and is not this server's to
speak.

Only a terminal failure speaks. A device that went away is told
nothing, because there is nobody left to tell, and a reply cancelled by
a barge-in says nothing either, because a cancellation means the user
is talking. Neither reads the section.

**This one is on by default, unlike the filler above.** The silent turn
is at its worst during onboarding, where a misconfiguration is
likeliest and nobody has a log open, so a deployment that would rather
have silence is the one that says so: `fallback: {enabled: false}`, on
`agent_defaults` or on a single agent. Being on by default has a cost
worth knowing, and it is per start rather than per upgrade: **every**
server start synthesizes one short phrase for every agent that has not
switched the section off, through the configured TTS provider, before
the server begins serving. That is one provider call per agent, a few
seconds of startup, and, on a metered voice, a few seconds of billed
synthesis, paid again at every restart, redeploy and container
replacement. Nothing is cached across processes: a start has no previous
world to keep a clip from. What reuse there is lives inside one running
process, across `vinga-server config apply`: an agent whose `fallback`
section and whose voice are both unchanged keeps the clip it already
had, and each of the two kinds of clip is re-synthesized only when its
own section or its voice moves, so applying a prompt edit costs no
synthesis at all. Fallback synthesis is bounded, ten seconds per agent
and one agent after another, so a provider that hangs delays a start by
seconds per agent rather than indefinitely; the filler's synthesis is
not bounded, so with the filler on, a voice that hangs can hold a start
or an apply open. A fallback phrase that will not synthesize in time,
or at all, degrades to the display alone, with a
`fallback_degraded` event naming the agent. That turn still shows the
sentence and still closes with its `tts stop`, and only the audio is
lost.
