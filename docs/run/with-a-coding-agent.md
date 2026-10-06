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
is. `/healthz` needs no
token:

```bash
curl -s http://192.168.1.10:8003/healthz
# {"status":"ok","version":"0.1.0","revision":"a1b2c3d4e5f6"}
```

`vinga info` prints the same revision in brackets on its `server:`
line. Then decide where to read by what the revision looks like
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
- **Anything else**: a name with `-g<hash>` in it, a `-dirty` suffix,
  a hash of another length. The server runs from a checkout, and the
  revision is `git describe --always --dirty` output, which is not a
  reference GitHub can resolve. Read the checkout itself, at its
  `HEAD`, after confirming that `git rev-parse --short HEAD` in it is
  the hash after `-g`; when it is not, the server is running other code
  than the checkout holds, so say so and ask. If you cannot reach the
  checkout, take the hash (after `-g`,
  where there is one) and read at it on the checkout's remote only
  after confirming the commit exists there: for this repository,
  `https://github.com/rafacm/vinga/commit/<hash>` answers 200 rather
  than 404. A fork's commit is on the fork's remote, not on this one.
- **A `-dirty` suffix you cannot see the tree behind.** The running
  code is not any commit. Say so, and ask the person.
- **`unknown`.** The build does not know what it is. Ask the person
  which image tag or commit they installed.

**When this page is not there at that revision** (GitHub answers 404),
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

**Files and the client follow the same revision.** A file you fetch
for a deployment that already runs (the compose file,
`deploy/postgres-init.sql`, an example fragment) comes from the raw
URL at the server's revision, not from `main`. Run the `vinga` client
the image ships, from the directory the compose file is in, since it
was built with the server and cannot disagree with it:

```bash
docker compose exec -T vinga vinga info
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
uv run --no-sync --project <checkout>/vinga-server vinga info
```

From here on this page writes `vinga` for whichever of these you use.

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
board's NVS file. A secret you receive is in your transcript and in
your provider's logs, and it cannot be taken back from either. The
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

- **The deployment's own secrets.** Getting Started's `.env` block in
  step 1 generates the API token and the device-auth secret straight
  into a file only the person can read. The person runs it. The check
  is `vinga info` answering once the server is up.
- **The master key**, needed only when a credential is stored
  encrypted: [The master key](security.md#the-master-key) generates it
  into the deployment's env file (Getting Started's is `.env`, where
  that page writes `vinga.env`), and the server is restarted to read
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
vinga info
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
   prompt, and either a binding to their board or becoming the
   `default_agent`; which of the two is their choice, not yours.

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

**Diff again immediately before the apply.** `vinga apply` installs
everything stored, not only what you wrote. If `vinga diff` lists
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
would and names both.
It needs the server's half of the package, so run it in the
container (`docker compose exec -T vinga vinga check`) or from a
checkout. A fresh store with agents and no device bound needs a
`default_agent`, and that is the refusal you are most likely to meet
first.

## 7. Closing the loop

A configuration is not done when the apply succeeds. Show the person a
reply coming back.

**What the simulator needs.** `vinga simulator run` checks in to an
OTA URL as a board would, says one packaged sentence, and prints the
transcript and the reply. The image's client runs it as it is, and
so does a workstation client installed as section 1 says; one
installed without the `sim` extra names the extra and stops
([Installing it](../reference/cli.md#installing-it)). It also needs the
OTA URL. `vinga info` prints one, the onboarding URL, when onboarding
is on, and that URL is yours to use: the API prints it to whoever
holds its token. When it prints a sentence saying onboarding is off
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

# Then, with the URL vinga info printed:
vinga simulator run http://192.168.1.10:8003/x/AB2C4D5E/
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
`pkill -f "events tail"` also matches the shell that runs it. What
each event carries is the [event reference](../reference/events.md),
and when each fires is [Reading logs and traces](logs-and-traces.md).

**When the reply is the fallback phrase or nothing**, the stream says
which stage failed:
`provider_failed` names the entry and the kind of error, `llm_retry` is
a stalled model being asked again, `reply_fallback` is the fixed phrase
said instead of a reply, and `sentence_withheld` is a model writing a
tool call into its speech. The guide for that stage says what each
means for it. Where the deployment records conversations, which is off
by default ([Recording conversations](conversation-store.md)), the
record keeps what the stream did not:

```bash
vinga session list
vinga session show <session>
vinga conversation list
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
check what answers at the address it was given.

## Where to go next

Every other task has its own guide, listed in
[the task guides' index](README.md). Read the index at the server's
revision, pick the guide for what the person asked, and keep to the
rules above while you follow it.
