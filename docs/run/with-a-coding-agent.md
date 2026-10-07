# Running vinga with a coding agent

This page is written for a [coding agent](../glossary.md#coding-agent),
a program such as Claude Code or Codex, that a person has asked to
install, configure or check a vinga deployment for them. If you are
that person, give your coding agent the address of this page and of
your server, if you have one; everything below is addressed to it.

At the end of this page you, the coding agent, will have read the
documentation that matches the server you are working on, asked the
person what they want in a fixed order, changed only what they asked
for, and shown them a reply coming back from the deployment. You will
also know which steps are theirs to run, because they carry a secret,
and how to hand those over.

Changing vinga's code is a different task with different rules:
[`AGENTS.md`](../../AGENTS.md) and
[Contributing to vinga](../contributing.md). Do not follow them here,
and do not follow this page there.

Work through the sections in order. Each rule says what goes wrong
without it. You may have opened this page at some other revision than
the server's; section 1 is how to tell, so do it before anything else,
and reread the page at the server's revision if the two differ.

## 1. Read the documentation at the server's revision

The documentation changes with the code, so read the version the
person's server was built from: never a newer one, and never your
memory of one. Each page this one links is read at that revision too,
when you reach the step that links it. Ask the server which build it
is; `/healthz` needs no token:

```bash
curl -s http://192.168.1.10:8003/healthz
# {"status":"ok","version":"0.1.0","revision":"a1b2c3d4e5f6"}
```

`vinga info` prints the same revision in brackets on its `server:`
line; run it with its one credential, the onboarding URL, filtered
out, as the end of this section shows. Then decide where to read by what the revision looks like
([Which build is running](upgrading.md#which-build-is-running) says
where each form comes from):

- **Twelve hexadecimal characters and nothing else.** A published
  image, whose `sha-` tag ends in the same twelve. That commit is on
  GitHub, so read this page, and every page it links, at it:

  ```text
  https://github.com/rafacm/vinga/blob/<revision>/docs/run/with-a-coding-agent.md
  https://raw.githubusercontent.com/rafacm/vinga/<revision>/docs/run/with-a-coding-agent.md
  ```

  The second form is the plain Markdown, and the one to fetch. A
  relative link on a page resolves at the same commit when you follow
  it on GitHub.
- **Anything else.** The server runs from a checkout, and the revision
  is that checkout's `git describe --always --dirty`, in one of three
  forms: `<tag>-<n>-g<hash>`, a bare `<tag>` when the commit is the
  tag's, or a bare abbreviated `<hash>` when no tag is reachable, each
  with `-dirty` after it when the tree had uncommitted changes. None of
  them is a reference you can put in a URL as it stands.

  **When you can reach the checkout**, run the same command in it:

  ```bash
  git -C <checkout> describe --always --dirty
  ```

  It must print exactly the server's revision. When it does not, the
  server runs code other than the checkout now holds: say so, and ask
  the person. When it does, read the checkout's working tree, and take
  every file you need from it rather than from a URL. With `-dirty`,
  the working tree is the running code and no commit is.

  **When you cannot reach the checkout**, a `-dirty` revision is the
  end of it: the running code is not any commit, so say so and ask the
  person. Otherwise take the commit it names (the hash after `-g`, the
  bare hash, or the tag) and resolve it to a full commit hash on the
  checkout's remote before reading anything there. For this
  repository, the `sha` field of
  `https://api.github.com/repos/rafacm/vinga/commits/<hash-or-tag>` is
  the full hash, and an answer without one means the commit is not
  there; a fork's commit is on the fork's remote, not on this one.
  Then read and fetch at that full hash, as for a published image.
- **`unknown`.** The build does not know what it is. Ask the person
  which image tag or commit they installed.

**When this page is not there at that commit** (GitHub answers 404),
the deployment is older than this page. Tell the person, and work from
that commit's own `README.md` and the pages it links, at that commit.

In none of these cases do you fall back to `main` and present its
instructions as the ones for this install. A server reading an older
schema refuses keys and commands that `main` documents, and the
person's deployment is left half changed by instructions that were
never its own.

**A fresh install has no server to ask yet.** Start from
[Getting Started](../../README.md#getting-started) as it reads on
`main`, and apply this section from the first `/healthz` that answers.

**Files and the client follow the same revision.** A file you need
for a deployment that already runs (the compose file,
`deploy/postgres-init.sql`, an example fragment) comes from the raw
URL at the published image's revision, or at the full hash a
checkout's revision resolved to, and from the checkout's own working
tree when you can reach it; never from `main`. Run the `vinga` client
the image ships, from the directory the compose file is in, since it
was built with the server and cannot disagree with it:

```bash
docker compose exec -T vinga vinga info | grep -v '/x/'
```

When a client on the workstation is needed instead, install it at the
same revision, with the `sim` extra section 7 uses:

```bash
uv tool install "vinga-server[sim] @ git+https://github.com/rafacm/vinga@<revision>#subdirectory=vinga-server"
```

A server that runs from a checkout has its client in the same
checkout. Run it from the directory the deployment's `.env` is in, so
it finds the address and the token there itself, and with `--no-sync`,
so it uses the environment the server runs from rather than changing
it:

```bash
uv run --no-sync --project <checkout>/vinga-server vinga info | grep -v '/x/'
```

From here on this page writes `vinga` for whichever of these you use.

**Run `vinga info` with one line filtered out, every time**, as the
two commands above do, whichever client you use. That line is a
credential, it sits on a line of its own, and the filter drops exactly
it: **the onboarding URL**, the line carrying `/x/`. Its path segment is
the deployment's onboarding key, which stands in front of the endpoint
that issues device tokens, so the server writes it to no log and a
proxy in front of it must not either
([Exposing a deployment](exposing-a-deployment.md)).

Filtered, it reaches neither your transcript nor your provider's logs,
and the label above it still tells you what you need: that onboarding
is on and where its address came from (a sentence saying onboarding is
off takes its place otherwise). Everything else `vinga info` reports,
the server's revision and the counts of what is configured, is
untouched. Section 7 is how you use the onboarding URL without seeing
it. `vinga info` prints no other credential: it issues no invite link,
and the one command that does, `vinga device invite`, is the person's
to run (section 4).

## 2. Learn the model before the first question

Read [concepts.md](../concepts.md) and [glossary.md](../glossary.md),
at the revision, before you ask the person anything. You cannot ask a
useful question about devices, agents and bindings without them, and
an interview that has to be restarted costs the person's patience.

One word matters at once. In vinga an
[**agent**](../glossary.md#agent) is the voice persona a device talks
to: a name, a prompt, providers, a voice and tools. You are not one.
When you speak to the person, call yourself a coding agent, or by your
program's name, and keep the bare word for theirs; otherwise "the
agent will do it" means two different things in one conversation.

## 3. Three rules

**Facts come from the installed client.** Before you write a command
or a field, check it against the install in front of you:

```bash
vinga --help                    # every noun
vinga agent --help              # one noun's verbs
vinga agent set --help          # one command, with the fields it takes
vinga schema agent              # one entity's fields, as JSON Schema
vinga reference                 # the whole domain reference
```

Where a page and `--help` disagree, `--help` is right for this
install. Without this rule you recommend a command or a field the
install does not have, quoted from another version's documentation or
from memory, and the person meets a refusal you caused.

**State comes from the server.** `vinga info`, `vinga list`,
`vinga show` and `vinga diff` say what is stored and what is serving.
Never infer it from the files you wrote: a write the server refused
stored nothing, and an apply it refused left the previous configuration
serving, so what you sent is not what is there.

**Secrets are typed by the person.** Never ask for a key, a token or a
password, never put one in a command you run, and never open, print or
search a file one was written into: `.env`, another env file, the
board's NVS file. The onboarding URL and an invite link are secrets
too, which is why section 1 filters the first out of `vinga info` and
the second is printed only by a command the person runs. A secret you
receive is in your transcript and in your provider's logs, and it
cannot be taken back from either.

What the rule protects is the value, not the capability. Running a
client that reads the API token from the deployment's `.env` is using
a credential without seeing it, and is yours to do; printing, reading
or typing the token is not. Where a command you run needs a credential
as an argument, pass it by command substitution from the command that
prints it, so it goes from one process to the other and never to your
screen, and only to a command known not to repeat what it was given:
section 7 does this for the onboarding URL. The
server refuses a credential-shaped `key=value` argument, but only after
it has been in the shell's history and the process list. Section 4 is
how you hand those steps over instead.

## 4. Steps the person runs

Two kinds of step are the person's, never yours: generating or
entering a secret, and writing the board's NVS, which carries the
Wi-Fi password. For each, give the person the exact commands from the
page at the revision, say that they carry a secret, wait until the
person says the step is done, and then check it by its effect, never
by reading what was written.

**A restart is an apply.** Two of these steps end in restarting the
server, and a server that starts serves everything stored, not only
what was applied before it stopped: a change someone wrote and never
applied goes live with the restart, exactly as it would with
`vinga apply`. So before you hand over any step that ends in a
restart, run `vinga diff`. If it lists anything you did not write in
this conversation, show the person that list and say the restart will
install it; restart only when they say so, or once they have put the
change back.

- **The deployment's own secrets.** Getting Started's `.env` block in
  step 1 generates the API token and the device-auth secret straight
  into a file only the person can read. The person runs it. The check
  is `vinga info` answering once the server is up.
- **The master key**, needed only when a credential is stored
  encrypted: hand over the block under
  [The master key](security.md#the-master-key) as it stands, with
  `vinga.env` replaced by the deployment's env file (Getting Started's
  is `.env`). It generates the key with the server image's own Python,
  so it needs nothing installed on the host, and it changes the file
  only when generating succeeded. The server is then restarted to read
  it. The check is the `secret set` below being accepted.
- **A vendor's key.** [The key](llm.md#the-key) gives the two forms,
  and the person chooses: a line they type in an editor into the env
  file, followed by a restart, or a command they run at their own
  prompt, which reads the key without echoing it:

  ```bash
  docker compose exec vinga vinga provider secret set llm claude api_key
  ```

  Hand over the command with the entry's real stage and name, never
  the value. It needs a terminal, so it is `docker compose exec`
  without `-T`, in the person's own shell; through a `-T` shell
  function there is no prompt and nothing typed is hidden. The check,
  for the env file, is `vinga apply` succeeding, since an entry whose
  variable the server's environment does not hold refuses the apply,
  naming the entry; for the prompt, it is `vinga show`, which prints
  the stored slot as `********`.
- **The board's NVS.** Getting Started's step 4 writes a CSV holding
  the Wi-Fi password, builds the partition from it and flashes it, and
  the CSV is deleted afterwards. The person runs all of it; the
  procedure on [the common board page](../devices/README.md) is the
  same. The check is the board's check-in, in section 7.
- **An invite link.** The person prints it with `vinga device invite`,
  the client you use run at their own prompt, and opens it in a
  browser; section 7 says when and in which browser. The link is all
  the command prints on stdout, and what it prints on stderr (that it
  worked, or why no link was issued) carries no credential, so the
  person may read that line back to you. The check is that browser's
  check-in on the event stream, never the link.

## 5. The order of the work

**With no deployment yet**, follow
[Getting Started](../../README.md#getting-started) step by step, and
split it like this:

- Before step 0, ask the interview's first question (section 6):
  nothing is stored yet to read first, and step 0 serves only local
  engines.
- Step 0, the local model: yours to run.
- Step 1: fetch the two files and start the server yourself. Find the
  address the boards reach this machine on with the step's own
  command, and confirm it with the person before using it. **The `.env`
  block is the person's** (section 4).
- Step 2: the image's client needs no install; use it as section 1
  says.
- Step 3: run the interview in section 6 first. The step's document is
  one answer to it, the local one.
- Step 4: confirm the serial port and that the board may be
  overwritten before you flash firmware. **The NVS write is the
  person's** (section 4).
- Step 5: the person talks to the board, and you watch (section 7).

**With a deployment that runs**, find the task in
[the task guides' index](README.md), read at the revision, and follow
that guide. The index is the one list of guides; every page it names
links the generated reference for each field and command it uses.
When no guide names the task, such as adding one more agent,
[Configuring a deployment](configuration.md) is the general one, and
the client's `--help` holds the rest.

## 6. The interview

Read what is there before you ask anything:

```bash
vinga info | grep -v '/x/'
vinga list
vinga diff
```

`vinga diff` lists what is stored and not yet serving. Run it before
your first write, so you know what was pending before you came.

Then ask, one question at a time and in this order:

1. **Local engines or a vendor's.** Local runs on this machine and
   needs no account: Getting Started's step 3 document. A vendor needs
   an account and a key (section 4):
   [`presets/cloud-stack.yaml`](../../vinga-server/examples/presets/cloud-stack.yaml)
   is the same deployment on vendor APIs. A mix is one entry per stage;
   [Choosing providers](providers.md) lists which engine serves each.
2. **Which model, and which voice.** Do not restate the guides; read
   them and offer what they offer:
   [Choosing the model an agent thinks with](llm.md),
   [Giving an agent a voice](voices.md), and for hearing,
   [Choosing how an agent hears](speech-recognition.md).
3. **Keep the agents that are stored, or add their own.** Getting
   Started creates one called `assistant`. Their own needs a name and a
   prompt, and a board reaches it only by a binding: claimed by its code
   naming the agent, or claimed naming none once it is the
   `default_agent`, the agent a newly claimed board starts with. Which
   of the two is their choice, not yours.

Four conventions hold for every answer:

- **Show what is stored before you change it**: the entity's current
  values, from `vinga show` or the entity alone.
- **Change only what was asked.** An answer about the voice is not
  permission to tidy the prompt.
- **Write whole entities.** `set` replaces the entity it names, every
  field you leave out included, so export it, edit it and set it back:

  ```bash
  vinga agent export assistant > assistant.yaml
  "${EDITOR:-vi}" assistant.yaml    # change only what was asked
  vinga agent set assistant -f - < assistant.yaml
  ```

  A deployment written from nothing is one document, `vinga import -f`,
  as Getting Started's step 3 does; importing never deletes.
- **When an answer conflicts with what is stored, name the fix and let
  the person decide.** An entry other agents inherit, a binding that
  would point at a removed agent, a default agent that no longer
  exists: say which command would resolve it, and run it only when the
  person says so.

**Diff again immediately before the apply**, and before any restart
(section 4). `vinga apply` installs everything stored, not only what
you wrote. If `vinga diff` lists
anything you did not write in this conversation, show the person that
list and apply only when they say so; otherwise you install a change
nobody here asked for.

```bash
vinga diff
vinga apply
```

**An apply that is refused** changes nothing running, and the write it
refused stays stored, so the next start refuses the same way. Some
refusals name the entry and the rule. One that does not, from
`vinga apply` or from `vinga diff`, which refuses the same store the
same way, is answered by `vinga check`, which reads the store as a boot
would and names both. It needs the server's half of the package, so run
it in the container (`docker compose exec -T vinga vinga check`) or from
a checkout.

## 7. Closing the loop

A configuration is not done when the apply succeeds. Show the person a
reply coming back.

**What the simulator needs.** `vinga simulator run` checks in to an
OTA URL as a board would, says one packaged sentence, and prints the
transcript and the reply. The image's client runs it as it is, and
so does a workstation client installed as section 1 says; one
installed without the `sim` extra names the extra and stops
([Installing it](../reference/cli.md#installing-it)). It also needs the
OTA URL, and the onboarding URL is one, which is a credential
(section 3). So pass it from `vinga info` by command substitution,
below: it goes straight to the simulator and never to your screen. The
simulator never repeats the URL it was given, on success or on a
failure; it says "the supplied OTA endpoint" instead. The URL is in
the simulator's arguments while it runs, as any argument is, and your
shell's history keeps the `$(...)` you typed rather than what it
expanded to. When the filtered `vinga info` says onboarding is off
instead, the URL the boards use is the path `server.ota_path` names
on the deployment's own host, and the server treats that path as the
deployment's secret, so it is a step the person runs (section 4): give
them the simulator line with the URL left for them to fill in, and
watch the events while they run it. Never guess the URL.

**Watch before you act.** The event stream keeps nothing and joins at
the present, and without `--follow` it prints one event and exits. So
start it first, in a second terminal or as a background process whose
output goes to a file you read, and only then run the simulator:

```bash
# First, and left running:
vinga events tail --follow

# Then, with the onboarding URL passed straight from vinga info:
vinga simulator run "$(vinga info | grep '/x/')"
```

Through the image's client the substitution runs on your side, so both
halves are `docker compose exec -T`:

```bash
docker compose exec -T vinga vinga simulator run "$(docker compose exec -T vinga vinga info | grep '/x/')"
```

The simulator prints `heard:` and `said:` lines, and on a turn that
worked the stream shows, among others and in this order, `ota_check`,
`session_open`, `heard`, `llm_round`, `speaking_started`, `replied`
and, when the simulator hangs up, `session_closed`. Judge the turn by
the stream, not by the simulator's exit code: a failed turn still
speaks the agent's fallback phrase, so the simulator prints it after
`said:` and exits 0, and the stream shows `reply_fallback` where
`replied` should be.

Stop the stream once `session_closed` has appeared: Ctrl-C in a
terminal, or, for a background process, a TERM signal to the process
id you started it as (through `uv run`, that is uv's, and TERM to it
ends the client too). A background job of a non-interactive shell
ignores the interrupt Ctrl-C sends, and a pattern match such as
`pkill -f "events tail"` also matches the shell that runs it.

**The image's client is the exception.** Through
`docker compose exec -T`, or Getting Started's shell function, which
is the same thing, a signal stops the client on your side and leaves
the stream running inside the container, where it goes on following
the server with nobody reading it. Either bound it in the container
with `timeout`, which the image carries:

```bash
docker compose exec -T vinga timeout 300 vinga events tail --follow
```

or run it in a terminal without `-T`, where Ctrl-C reaches the stream
itself. What each event carries is the
[event reference](../reference/events.md), and when each fires is
[Reading logs and traces](logs-and-traces.md).

**When the reply is the fallback phrase or nothing**, the stream says
which stage failed: `provider_failed` names the entry and the kind of
error, `llm_retry` is a stalled model being asked again,
`reply_fallback` is the fixed phrase said instead of a reply, and
`sentence_withheld` is a model writing a tool call into its speech. The
guide for that stage says what each means for it.

**The stream is the check; the record is not.** Where the deployment
records conversations, which is off by default
([Recording conversations](conversation-store.md)), the record holds
what people said to its devices, the person's household included:
conversation titles are utterances, and a conversation's page is what
was said. Do not list or read conversations to verify a turn. When the
stream is not enough, read the one session the simulator opened, by
the `session` its `session_open` event carried, which prints its
board, agent, timing and how it ended, and no words:

```bash
vinga session show <session>
```

Its words, the simulator's own conversation by the `conversation` the
same event carried, are read only with the person's consent:

```bash
vinga conversation show <conversation>
```

**A board** is the same loop with the person's hands in it. Start the
stream for that board before they power it on or reset it, with its
MAC from the sticker, or from `vinga device pending list` for a board
waiting with a code on its screen:

```bash
vinga events tail --follow --device aa:bb:cc:dd:ee:ff
```

`ota_check` is its check-in, and its `agents` field names the agents
it reaches. When the person speaks to it, `session_open` names the
agent that answered, followed by the turn events above. A board that
never checks in has the wrong address in its NVS, or is not on the
network; [Onboarding a device](onboarding-a-device.md) says how to
check what answers at the address it was given. That check,
`vinga-server doctor`, prints the address it checked, key included, so
it is the person's to run (section 4), not yours.

**A browser** lets the person hear the agent themselves, with no board
and nothing to install: the page the server serves at `/talk/` is a
device that talks through their computer's microphone and speakers
([the browser client's guide](../devices/browser.md)). It joins with an
invite link, which `vinga device invite` prints and which is the
person's to print and open (section 4). Offer it once the simulator's
turn has worked.

First read whether a link can be issued, from what you already know:
the filtered `vinga info` says whether onboarding is on, and its
`configured:` line names the default agent. A link that names no agent
binds the browser to the default agent, so with none set either the
person names one with `--agent <name>` or sets a default, and which is
the person's answer to section 6, not yours. A named agent has to be
one the server is serving, so one written since the last `vinga apply`
waits for it.

Then ask which computer the person means to open it on. A link names the
deployment's `server.public_url` when that is an `https://` address,
and otherwise `localhost`, when the client reached the server on its
own computer, as the image's client does by default. A `localhost` link
works only in a browser on the server's own computer: anywhere else the page says it
lacks a secure connection and starts nothing. With neither, the command
prints no link and says so. A deployment reached
from other computers gets `https://` through
[Exposing a deployment](exposing-a-deployment.md), which is a change to
propose to the person, not to make.

Start the stream first, as for the simulator, with no `--device`: the
browser's MAC does not exist until the link is opened. Then hand the
step over. Give the person the command to run at their own prompt in
the directory you ran the client from: `vinga device invite`, with
`--agent <name>` for each agent the browser should reach if it is not
to be the default agent (through the image,
`docker compose exec vinga vinga device invite`). Tell them to open the
link it prints, press Start, allow the microphone and say something.
When it prints no link, the line it printed instead says why, and they
may read that line to you. The page has been checked in headless
Chromium alone, so a Chromium-based browser such as Chrome is the
nearest to what was checked. Never ask them to paste the link to you.

Opening the link writes no event; pressing Start does. The stream then
shows `ota_check` with `board` `vinga-browser` and a MAC no board has,
`session_open`, and the turn events above, ending in `session_closed`
when the person presses End, or when nobody has spoken for the idle
timeout. `vinga list` then shows the new device as `Browser <mac>`,
bound to the agents the link named, or to the default agent.

## Where to go next

Every other task has its own guide, listed in
[the task guides' index](README.md). Read the index at the server's
revision, pick the guide for what the person asked, and keep to the
rules above while you follow it.
