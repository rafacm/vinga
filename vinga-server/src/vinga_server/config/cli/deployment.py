"""The deployment as a whole: export, import, apply, diff, list, show, info.

The commands whose subject is the whole stored configuration rather
than one entry of it, with the renderings each of them prints: the
export document, the masked configuration `show` prints, the tree
`list` prints, the counts `info` prints, and the two listings that say
what an apply installed and what is still pending.

What its callers stop knowing: what a document has to say that a read
does not. An export's header is the order a deployment is reproduced
in and its foot is the credentials a read never carries; an apply's
listing is read off the reload result's own models rather than a list
written here, and the comparison's is read off the diff's; and which
boundary a pending change waits at is stated once, with the command
that crosses it, by the module that owns the notice.
"""

import shlex
import sys
from collections.abc import Mapping, Sequence
from typing import Any, Literal, cast, get_args, get_origin

from pydantic import BaseModel

from vinga_server.config import entities
from vinga_server.config.loader import ConfigError
from vinga_server.config.models import MASK, PROVIDER_STAGES, DomainConfig
from vinga_server.config.printing import printable
from vinga_server.config.responses import (
    AppliedDocument,
    Applies,
    ConfigDiff,
    ConfigDocument,
    ConfigReloadResult,
    RuntimeInfo,
)
from vinga_server.config.transport import APPLY_LOCATION, check_transportable

from .acts import UNREADABLE_READ, UNREADABLE_WRITE, Act, _path, _printed
from .answers import _understood
from .devices import _device_summary
from .entities import (
    SECRETS_HEADING,
    _counted,
    _halves,
    _sections,
    _shadow_note,
    _status_block,
    _summarized,
)
from .input import _fragment
from .invocation import Invocation
from .output import INSTALLS, UNBOUNDED, UNNAMEABLE, _imported, _names, _yaml
from .reach import PROGRAM, UNRECOGNIZED_ANSWER, Reached

# What `apply` waits instead, because it is the one request whose
# server-side work is not a database call. The server's envelope is one
# MCP connect timeout plus one prompt-discovery deadline plus small
# change: stops run concurrently under a short bound, starts run
# concurrently under the connect timeout, and an entry that names
# published prompts spends one further bounded phase fetching them, so
# a slow server is reported down rather than waited for. This is
# comfortably above that, because a client that gave up on an install
# the server then carried out would recreate the exact ambiguity the
# whole feature exists to remove: nobody would know what is running.
APPLY_READ_TIMEOUT_S = 60.0

# And what `import` waits, which is the sentence above taken to its
# conclusion where no finite envelope exists.
#
# An import is one transaction, and the transaction loads the whole
# existing configuration and validates the whole resulting one, whose
# size nothing about the request bounds: the document may be small and
# the store it lands in large. So there is no number to derive. What a
# finite bound would buy is the exact thing every timeout here exists to
# prevent, a client that gave up on a write the server then committed,
# leaving nobody able to say what is stored.
#
# So the client waits for the answer, however long the transaction
# takes. The connect timeout stays bounded, because a server that is not
# there must still say so quickly, and the two bounds the server applies
# before it mutates anything (the document's entry count and its body
# size) are where an unbounded request is refused. What is left is
# transport death mid-wait, which is the exposure every write already
# has, and the recovery is the same: read the store back with `export`
# or `show`.
IMPORT_READ_TIMEOUT_S: float | None = None

UNREADABLE_APPLY = f"the configuration API answered the apply with {UNRECOGNIZED_ANSWER}"

# What the apply listing prints for a kind this server cannot apply
# while it runs. The sections are declared complete from the first
# release that has any of them, so that a client generated from the
# contract never meets a grown answer, and a kind whose milestone has
# not landed answers null rather than an empty answer that would claim
# it had been considered.
NOT_APPLIED = "(this server does not apply this kind without a restart)"


# What `info` prints, and what it is careful about
#
# The banner is the maintainer's own string, character for character. A
# plain hyphen and not a dash of any other width: the no-em-dash rule is
# about em-dashes, and none of these characters is one.
BANNER = "vinga - Conversational AI. Sweded."

# The label in front of the address this CLI actually contacted, which
# is the first question `info` exists to answer. It is a different
# question from the onboarding URL below it, and legitimately a
# different answer: a device reaches this deployment on the origin it
# publishes, and an operator reaches the API wherever they exec'd into.
# What is printed is `Address.shown`, never what was typed.
CONTACTED = "configuration API"

# The label in front of the onboarding URL, carrying the provenance, so
# that the URL itself lands on a line of its own with nothing in front
# of it. Deliberate: a terminal wraps a long line wherever it runs out,
# and this is a value an operator types into a captive portal by hand or
# selects whole. The provenance travels with it for the reason the
# banner and `ota-url` carry it: two of the three sources it can come
# from are inferences.
#
# It leads with this codebase's own name for the value, so that the line
# and the noun an operator reads everywhere else are the same word, and
# names the device's word for it in the parenthetical, because the field
# it is typed into is labelled that and nothing else on the board is.
ONBOARDING_URL_LABEL = (
    "onboarding URL (the address a device's captive portal asks for, labelled OTA there)"
)

# And what stands there instead when the answer says onboarding is off.
# The path devices are configured at is named and never printed: it is
# `server.ota_path`, which is this deployment's secret, exactly as the
# derivation's own refusal has it.
ONBOARDING_OFF_HERE = (
    "device onboarding is off (server.onboarding.enabled is false), so this deployment "
    "serves no short URL. Devices are configured at the path server.ota_path names, "
    "which is not printed here, since it is this deployment's secret."
)

# The label in front of the build that answered. One line and not two:
# a version and the revision it was cut from are one fact about one
# process, and a reader who has the first without the second has half an
# answer either way.
BUILD = "server"

# The prefix on the one line the stored half is told in. A count and not
# the tree: what `info` answers is orientation, and `vinga list` is the
# tree.
CONFIGURED = "configured:"

# And what stands after that prefix when there is nothing to count. An
# empty line would read as a command that failed to answer, and the
# deployment this is true of is precisely the one an operator is looking
# at while they follow Getting Started's step 2.
NOTHING_YET = "nothing yet"


def _show_everything(document: Mapping[str, object]) -> str:
    """The whole domain configuration in one document, in the shape the
    YAML file has today, with the stored secrets listed as masks
    underneath it.

    Read through the gate every rendering of this document reads through,
    which is what keeps a section that is not one out of here as a
    traceback with the answer inside it.

    The shapes preserve what they read rather than projecting it. This
    rendering IS the document: a shape that flattened a body would print
    a configuration nobody has, so what the gate adds is that the
    sections are the mappings the registry says they are, and the bodies
    under them travel through undescribed exactly as they do in the
    answer.
    """
    config, secrets = _halves(document)
    notes = _all_secret_notes(_sections(config), secrets)
    return _yaml(config) + ("\n" + "\n".join(notes) + "\n" if notes else "")


# Export
#
# The importable projection of what a read already answers. There is no
# new read behind it: #207 made every read derive from the descriptor
# registry and stay write-shaped, and #192's marker made the display
# envelope the writable projection, so this is assembly rather than
# translation. The whole-configuration read is already the document
# `import` takes, section for section, and one entity's envelope already
# carries the fragment `set` takes.
#
# What export adds is the two things a document has to say that a read
# does not. The header says how to reproduce the deployment, in order.
# And the stored credentials become comment annotations naming the
# command that enters each of them, because a credential never travels
# in a read: it is not in the exported bodies at all, and the mask is
# not a value a creating write would accept, so injecting one would make
# an export fail to import onto an empty store, which is the one place
# it most has to work.

EXPORT_HEADER = f"""\
# The domain configuration of this deployment, in the shape
# `{PROGRAM} import` takes. Reproduce it in three steps, in this order:
#
#   1. {PROGRAM} import -f <this file>
#   2. the secret set commands at the foot of this file, if any
#   3. {PROGRAM} apply
#
# A stored credential never travels in a read, which is what the second
# step is for, and why it comes before the third: an apply builds the
# engines the document names, and their credentials are not in the
# store until the second step has run. Importing is additive: a section
# this document does not name is left alone, and nothing in it deletes.
"""

# The foot of an export, and the one line of it that has to agree with
# the header above: the header numbers the steps and this is the step 2
# in it, so a sentence that put the credentials on the wrong side of the
# apply would be the file contradicting itself. It said "after applying"
# while applying meant writing, and #371 moved that word to the install,
# which is what makes the order explicit here now. A test holds this
# sentence to naming both verbs in the header's order.
EXPORT_SECRETS_HEADING = (
    f"# Stored credentials are not exported. Enter each of them after the "
    f"`{PROGRAM} import`\n"
    f"# and before the `{PROGRAM} apply`:"
)

# Which kind holds a stored secret of each addressable kind, read off
# the registry: the noun a secret command sits under and the parameters
# that address one entry of it are the descriptor's, so the command an
# annotation names cannot come to disagree with the command that exists.
# Read from `entities` rather than derived again, since the store and a
# location's own description ask the same question.
_SECRET_HOLDER = entities.SECRET_HOLDERS

# And the closed set of kinds a stored location may name, as a shape the
# gate can read a location's `kind` against. Built from the mapping
# above rather than written beside it, so a kind that gains secret slots
# is admitted here by existing.
#
# A shape and not a lookup with a guard, because a subscript is what
# this used to be: `_SECRET_HOLDER[kind]` raised a `KeyError` whose one
# argument was the kind the answer supplied, which is a value nobody has
# vouched for leaving the boundary inside an exception. Read as a shape
# it meets the one fixed sentence instead, exactly as every other
# unreadable answer does.
HOLDER_KIND = Literal[tuple(_SECRET_HOLDER)]


def _exported(document: Mapping[str, object]) -> str:
    """The whole stored configuration as one applicable document, read
    through the gate `show` reads it through and for the same reasons.

    The foot is rendered before the head, though it is printed after it.
    A location this client cannot write down refuses the whole document,
    and building the document first would mean building it to throw it
    away: nothing of it would reach an operator either way, since the
    export is one string printed at once, but a refusal that comes after
    the work reads as an afterthought and invites a later edit to print
    the head early.
    """
    config, secrets = _halves(document)
    commands = _secret_commands(secrets)
    return EXPORT_HEADER + _yaml(config) + commands


def _secret_commands(secrets: Sequence[Mapping[str, object]]) -> str:
    """Every stored credential as the command that enters it, in the
    fixed order the store lists its locations in, so two exports of one
    configuration are the same bytes."""
    if not secrets:
        return ""
    lines = [
        "#   " + " ".join(shlex.quote(word) for word in _set_secret_words(stored))
        for stored in secrets
    ]
    return "\n".join(["", EXPORT_SECRETS_HEADING, *lines]) + "\n"


def _set_secret_words(stored: Mapping[str, object]) -> list[str]:
    """One stored credential's location as the command that fills it.

    A location's identity is the dotted join of the parameters that
    address the entity, and the repository owns the inverse: a name
    holding a dot is still one name, and a second spelling of the rule
    here would render a command addressing an entity that does not
    exist.

    `--` after the command's own words, and it is not decoration.
    Nothing about a name forbids a leading dash: the write path refuses
    a slash and a control character, and `--from-env` is a legal
    provider name that a secret write would otherwise read as an option
    and refuse. The marker is the shape an operator has to use to write
    such a name in the first place, so the exported command is the
    command they typed.

    The kind is read as the closed set of kinds that hold a secret, so a
    location naming one this client does not have meets the fixed
    sentence rather than a `KeyError` carrying the name it supplied.

    The identity and the slot are the one thing in these renderings that
    is printed as written rather than through the display door. What
    this builds is a command an operator pastes to address the entity it
    names, and the door bounds at a hundred and twenty characters and
    replaces what it cannot print, so a location put through it would
    address a different entity or none.

    So they are refused instead, which is the same rule the other way
    round: a location this client cannot render as written is one it
    does not render. `shlex.quote` is what makes a line safe to paste,
    and it is not what makes a line safe to READ: quoting keeps a
    newline, and a newline ends the `#` that makes this a comment, so
    the rest of the identity lands on a bare line of a YAML document
    whose own header says to import it. Every other unprintable
    character reaches the terminal as itself for the same reason.

    Refused whole, and not per character: the fixed sentence names
    neither the location nor what was in it, exactly as every other
    unreadable answer's does. The write path refuses a control character
    in a name, so nothing this API stored can meet this; what can is an
    answer that did not come from it, which is what the gate is for.
    """
    holder = _SECRET_HOLDER[_understood(HOLDER_KIND, stored["kind"], UNREADABLE_READ)]
    return [
        *PROGRAM.split(),
        holder.name,
        "secret",
        "set",
        "--",
        *entities.addressed(holder, _as_written(stored["identity"])),
        _as_written(stored["slot"]),
    ]


def _as_written(value: object) -> str:
    """One word of an exported command, as the answer wrote it, or the
    refusal for one that cannot be written down.

    `str.isprintable` is the question, and it is the predicate the
    display door replaces by: what that door turns into a question mark
    is exactly what this refuses. Which is why the rule is not spelled
    out here as a set of characters. It covers the line separators, the
    C0 and C1 controls and DEL, and the format characters a terminal
    obeys silently, of which the right-to-left override is the one that
    makes a pasted command read as something other than what it runs.
    """
    written = str(value)
    if not written.isprintable():
        raise ConfigError(UNREADABLE_READ)
    return written


def _all_secret_notes(
    read: Mapping[str, object], secrets: Sequence[Mapping[str, object]]
) -> list[str]:
    """Every stored secret in the whole-configuration view, each named by
    its location and marked when it shadows a reference written for the
    same slot.

    Every field of a location goes through the display door on its way
    to a line. The three are strings by the shape the API declares them
    with, and a string is not a safe thing: a slot name carrying an
    escape sequence steers the terminal from inside a comment exactly as
    one anywhere else does.

    Looked up as they arrived and printed through the door, the same two
    readings the tree gives an entity name: the body a location points
    at is filed under the identity the store wrote.
    """
    bodies = _bodies(read)
    notes = [
        f"#   {printable(str(stored['kind']))} {printable(str(stored['identity']))} "
        f"{printable(str(stored['slot']))}: {MASK}"
        + _shadow_note(bodies.get((stored["kind"], stored["identity"]), {}), stored["shadows"])
        for stored in secrets
    ]
    return [SECRETS_HEADING, *notes] if notes else []


def _bodies(read: Mapping[str, object]) -> dict[tuple[str, str], Mapping[str, object]]:
    """The masked body of every entity that can hold a stored secret,
    keyed the way a secret location names it.

    Walks the sections already read as their shapes rather than the
    answer's own mapping, so the two levels of a provider section and
    the one of an MCP section are what the registry says they are.
    """
    bodies = {
        ("provider", entities.provider_identity(stage, name)): body
        for stage, entries in read["providers"].items()
        for name, body in entries.items()
    }
    bodies.update((("mcp_server", name), body) for name, body in read["mcp_servers"].items())
    return bodies


# What an apply's answer can say, read off the shapes it is declared in
#
# Three readings of `ConfigReloadResult` and its sections, all of them
# this renderer's: which sections there are, and within one section
# which fields are lists of names and which are yes-or-no answers.
# Written here rather than beside the models because printing is what
# they are for, and the models are the contract two surfaces share.


def outcomes(section: type[BaseModel]) -> tuple[str, ...]:
    """One apply section's outcome lists, in the order it declares
    them: every field that is a list of names.

    Presentation, which is why the answer is a tuple and not a set, but
    presentation of the model's own fields: read off the declaration
    rather than listed again, so an outcome added to a section is one
    line on that section and this prints it. What the rule leaves out is
    every field that is not a list of names, which today is the MCP
    status mapping and the agent-defaults flag; each of those is
    rendered where its own shape is understood.
    """
    return tuple(
        name
        for name, field in section.model_fields.items()
        if get_origin(field.annotation) is list and get_args(field.annotation) == (str,)
    )


def flags(section: type[BaseModel]) -> tuple[str, ...]:
    """One apply section's yes-or-no answers, in the order it declares
    them.

    The sibling of `outcomes` above and the other half of what a section
    can say: a kind there is one of has nothing to name, so what moved
    about it is a boolean. Read off the declaration for the same reason,
    so that a flag added to a section is a flag this prints.
    """
    return tuple(
        name for name, field in section.model_fields.items() if field.annotation is bool
    )


def _section(annotation: object) -> type[BaseModel]:
    """The model behind one section of the result, whether or not the
    section is optional. A section that is not filled yet is declared
    `Model | None`, and what a renderer needs is the model either way."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    return next(
        argument
        for argument in get_args(annotation)
        if isinstance(argument, type) and issubclass(argument, BaseModel)
    )


# Which sections one apply answers with and what shape each of them
# is, read off the result rather than written down beside it: a section
# added to the model is a section this renders, and a field whose shape
# the rendering has no rule for is a failing test rather than output
# that quietly went missing.
APPLY_SECTIONS: dict[str, type[BaseModel]] = {
    name: _section(field.annotation)
    for name, field in ConfigReloadResult.model_fields.items()
}


# What each outcome an apply can report is called, in the words of the
# person who ran it
#
# The field names are the layer that did the work talking to itself:
# `fallback_resynthesized` is a field of the reload result, and an
# operator whose document contains no `fallback` section has no way to
# read it as "the phrase this agent speaks when a reply fails was made
# again in its voice" (#426). So the vocabulary moves to the side that
# talks to people, and each label is written from what its own field's
# description in `responses.py` says the field means.
#
# Keyed by (section, field), because one word means two things in two
# sections: a provider entry that was `reused` is an engine nothing
# rebuilt, and a filler that was `reused` is audio nothing sent to a
# voice. A row whose field name is already the operator's own word for
# it keeps that word; what the table buys is not novelty but totality,
# which a pin asserts over `APPLY_SECTIONS`: a field added to the
# contract without a label here fails a test rather than going missing
# from an answer.
#
# Short, lowercase and fixed text, for the reason every other sentence
# in this module is: what is printed has to be a function of the answer
# alone, and a label is this module's own string rather than anything a
# far side wrote.
APPLY_LABELS: dict[tuple[str, str], str] = {
    ("mcp", "started"): "connection started",
    ("mcp", "restarted"): "connection remade",
    ("mcp", "stopped"): "connection stopped",
    ("mcp", "unchanged"): "connection kept",
    ("prompts", "changed"): "changed",
    ("fillers", "resynthesized"): "filled pause spoken again",
    ("fillers", "reused"): "filled pause kept",
    ("fillers", "disabled"): "filled pause off, synthesis failed",
    ("fillers", "fallback_resynthesized"): "failure phrase spoken again",
    ("fillers", "fallback_reused"): "failure phrase kept",
    ("fillers", "fallback_degraded"): "failure phrase shown, not spoken",
    ("providers", "built"): "engine built",
    ("providers", "reused"): "engine kept",
    ("providers", "retired"): "engine retired",
    ("agents", "added"): "added",
    ("agents", "removed"): "removed",
    ("agents", "defaults_changed"): "agent_defaults changed",
}

# What an apply that moved nothing says. A sentence rather than no
# output at all, for the reason the comparison's own is one: a command
# that printed nothing would read as one that failed to answer. It says
# the state and not the act, because the act is what the success line
# on stderr says, and stdout is the half a pipe reads for what happened.
NOTHING_DIFFERED = "nothing differed from what this server was already serving."

# And what an apply that answered at all says, on stderr, because "it
# worked" is a fact about this invocation rather than about the
# deployment (#426). No duration in it: the elapsed seconds are the
# progress line's, drawn at a terminal and written nowhere else, and a
# wall-clock number here would make two runs against one state different
# bytes.
INSTALLED = "the stored configuration is installed and serving."


def _apply_listing(applied: Mapping[str, Any]) -> str:
    """What the apply installed, kind by kind, and then what is running.

    The outcomes first, because they are the answer to the question that
    was asked, and the MCP status underneath because it is the answer to
    the one that follows: an entry that started is not thereby
    connected, and the block below it says which. The status half is
    asked for only where there are entries to say something about
    (#426): `NOTHING_CONFIGURED` is the whole answer to a question an
    operator asked `mcp-server status`, and advice about a feature not in
    use is not an answer to `apply`.

    A section appears where it has something to say, and within one
    section a list with names in it and a flag that is true (#426): an
    empty list and a false flag are absent rather than enumerated,
    because absence is absence and what an operator is reading for is
    what moved. What is filtered is a function of the answer, so two
    renders of one answer are still the same bytes. A section answered
    null keeps its line: "this build does not touch this kind" is
    content rather than emptiness, and a kind silently missing would
    read as one with nothing to report.

    What each section can say is still read off its own model rather
    than listed here, so a section or an outcome added to the result is
    one the operator sees, and a field shaped like neither a list of
    names nor a flag is a failing test rather than output nobody notices
    is gone. What the labels above add is the vocabulary, held to the
    same models by their own pin.

    Read as one shape, the status half included, which is what the act
    declares: the outcome lists are printed name by name and the status
    half is a document a listing renders, so a stray shape anywhere in
    here would otherwise become output or a traceback.
    """
    lines: list[str] = []
    for section, shape in APPLY_SECTIONS.items():
        body = applied[section]
        if body is None:
            lines.append(f"{section}: {NOT_APPLIED}")
            continue
        said = [
            f"  {APPLY_LABELS[section, outcome]}: {_names(body[outcome])}"
            for outcome in outcomes(shape)
            if body[outcome]
        ] + [f"  {APPLY_LABELS[section, flag]}" for flag in flags(shape) if body[flag]]
        if said:
            lines.append(f"{section}:")
            lines += said
    if not lines:
        lines.append(NOTHING_DIFFERED)
    servers = applied["mcp"]["servers"]
    # The blank line goes with the block it separates, so an answer with
    # no status half ends on the line before it rather than on
    # whitespace.
    if not servers:
        return "\n".join(lines) + "\n"
    return "\n".join(lines) + "\n\n" + _status_block(servers)


# What the database holds that the running server is not serving
#
# What each kind can say is read off its own model, so a field added to
# the comparison is a field this prints, and a field shaped like none of
# the three rules below is a failing test rather than output nobody
# notices is gone.
#
# Three shapes and no fourth. A list of names is a list of names; a
# yes-or-no is a kind there is one of, which has nothing to name; a
# nested model is one kind's answer broken into the moments a
# conversation meets each part at, and each of those moments is a
# labelled fact of the kind that holds it.


def named_lists(section: type[BaseModel]) -> tuple[str, ...]:
    """One diff section's name lists, in the order it declares them."""
    return tuple(
        name
        for name, field in section.model_fields.items()
        if get_origin(field.annotation) is tuple and get_args(field.annotation) == (str, ...)
    )


def nested(section: type[BaseModel]) -> tuple[str, ...]:
    """One diff section's own sub-sections, in the order it declares
    them: the parts of one kind that reach a conversation at different
    moments."""
    return tuple(
        name
        for name, field in section.model_fields.items()
        if isinstance(field.annotation, type) and issubclass(field.annotation, BaseModel)
    )


# Which kinds one comparison answers with and what shape each of them
# is, read off the result rather than written down beside it, exactly as
# the apply's sections are.
DIFF_SECTIONS: dict[str, type[BaseModel]] = {
    name: _section(field.annotation) for name, field in ConfigDiff.model_fields.items()
}


# What this client heads a group of pending kinds with
#
# One head per boundary rather than a label per kind (#425): every kind
# under a head is waiting at the same boundary, and saying so once over
# the group is the whole of what the label said ten times. The words are
# this client's, for the reason `INSTALLS` above states: what an
# operator does about `reload` is run a command, and the command belongs
# to this side's grammar. So the tokens themselves stop being printed,
# and the vocabulary keeps the homes it already has, the generated
# document and this command's own help row.
#
# Total over `DiffApplies`, which is what a pin asserts: a member added
# to that alias without a line here would head its group with nothing,
# and a hole in an answer is worse than a failing test. `check-in` has
# its line for exactly that reason and heads no group this server can
# send, because the two kinds carrying it are `LiveKind`s, which name
# nothing and are answered by the sentence below instead.
HEADS: dict[Applies, str] = {
    Applies.RESTART: "pending, at the next server start:",
    Applies.RELOAD: f"pending, at the next `{INSTALLS}`:",
    Applies.CHECK_IN: "stored, and in effect at each device's next check-in:",
}

# What a comparison that found nothing says. A sentence rather than no
# output at all: a command that printed nothing would read as one that
# failed to answer, and what this answers is that the two worlds agree.
SERVING_THE_STORE = "nothing is pending: this server is serving what the store holds."

# Why two of the kinds are never in a group above, said on every
# comparison because it is a question about every comparison rather than
# about this one's state. It is `LiveKind`'s docstring out loud: what is
# stored for a binding or for the default agent is served by the entity
# reads and is in effect by that device's next check-in, so nothing
# about them can be pending against an apply. The two names in it are
# the `LiveKind` sections of the comparison, which a pin holds it to.
READ_AS_ASKED = (
    "devices and default_agent are read as a device asks for them, so nothing about "
    "them waits for an apply."
)


def _diff_listing(body: Mapping[str, Any]) -> str:
    """The comparison, grouped by the boundary its changes wait at.

    One head per boundary present, in the order `Applies` declares them,
    and under each head one line per kind that has something to say
    (#425): an empty list and a false flag are absent rather than
    enumerated, because absence is absence and what an operator is
    reading for is what moved. What is filtered is a function of the
    two worlds being compared, so two reads of one pair of worlds are
    still the same bytes.

    Names and labels and nothing else, which is what the shape carries:
    no bodies, no values, no masks and no secret marks cross this
    surface, so there is nothing here to filter. The names go through
    `_names` all the same; the heads and the two sentences are this
    module's own words.
    """
    said: dict[Applies, dict[str, list[str]]] = {}
    for section, shape in DIFF_SECTIONS.items():
        for boundary, fact in _diff_facts(shape, body[section]):
            said.setdefault(boundary, {}).setdefault(section, []).append(fact)
    # Two columns, so the answer is read down the left kind by kind,
    # padded to the widest kind printed anywhere in it rather than per
    # group, so that the columns line up across the heads as well. A
    # line exists only where there are facts to put on it, which is what
    # makes trailing whitespace impossible rather than avoided.
    column = max((len(kind) for kinds in said.values() for kind in kinds), default=0)
    blocks: list[str] = []
    for boundary in Applies:
        if boundary not in said:
            continue
        blocks.append(
            "\n".join(
                [HEADS[boundary]]
                + [
                    f"  {kind.ljust(column)}  {'; '.join(facts)}"
                    for kind, facts in said[boundary].items()
                ]
            )
        )
    return "\n\n".join((blocks or [SERVING_THE_STORE]) + [READ_AS_ASKED]) + "\n"


def _diff_facts(
    shape: type[BaseModel], body: Mapping[str, object]
) -> list[tuple[Applies, str]]:
    """What one kind of the comparison has to say, each fact tagged with
    the boundary it is waiting at.

    Tagged rather than returned under the kind's own boundary, because a
    kind's parts do not have to share one: the four under `agents` carry
    their own token each, and a fact belongs in the group of the
    boundary it is actually waiting at. Today they all say `reload` and
    every fact of a kind lands on one line; the day one of them does
    not, it lands under its own head instead of under a wrong one.

    The parts flatten into labelled facts of the kind that holds them
    (`prompt changed: kids`) rather than into indented blocks of their
    own, which is what most of a comparison used to be.
    """
    boundary = cast(Applies, body["applies"])
    # Whether a list has something to say is asked of the list, never of
    # what it rendered to. The shape validated it as a tuple of strings
    # and said nothing about their length, so a name that renders to
    # nothing is a name the store holds; reading presence off the
    # rendered string would drop it, and a kind whose only pending change
    # was that name would fall out of the answer into the sentence saying
    # nothing is pending, which would report an install that never
    # happened.
    facts = [
        (boundary, f"{listed}: {_names(body[listed])}")
        for listed in named_lists(shape)
        if body[listed]
    ]
    # A flag says its own name and nothing after it: a kind there is one
    # of has nothing to name, so `changed` is the whole fact, and `no` is
    # a line that is not printed at all.
    facts += [(boundary, flag) for flag in flags(shape) if body[flag]]
    for under in nested(shape):
        facts += [
            (token, f"{under} {fact}")
            for token, fact in _diff_facts(
                _section(shape.model_fields[under].annotation),
                cast(Mapping[str, object], body[under]),
            )
        ]
    return facts


def _identity_block(info: Mapping[str, object]) -> str:
    """What `info` prints of the server's own answer: which build is
    running, and the URL a board is onboarded at.

    Every value is made printable, like every other value an answer
    carries: what is on the other end of `--api-url` is not this
    command's to vouch for. The build's two values are bounded as well;
    the URL and its provenance are not, and the note on `UNBOUNDED`
    above says why.

    The build is one line, because a version and the revision it was cut
    from are one fact about one process: which build answered. Reading
    them a line apart never told anyone anything the pair did not.

    The URL lands on a line with nothing in front of it, and its
    provenance goes on the label line above it. A terminal wraps a long
    line wherever it happens to run out, and a URL broken across two
    rows is one an operator mistypes; a label in front of it would only
    make it happen sooner. That is why the label was compacted and the
    line break was not: the label may wrap and lose nothing, and the
    line under it may not. With onboarding off there is no URL at all,
    and the sentence that stands there says which switch decides it.

    Everything goes to stdout, this block included. That is not the
    stream split being bent: the whole of what `info` answers is the
    artifact, and the URL in particular must reach the one stream a
    caller can capture, never the one a terminal scrolls past.
    """
    lines = [
        f"{BUILD}: {printable(str(info['version']))} ({printable(str(info['revision']))})",
        "",
    ]
    # Asked of the flag, which is the field whose job the question is.
    # It cannot disagree with the two below it: `RuntimeInfo` refuses a
    # body where the three say different things, so this branch and the
    # value it is about are one fact rather than two that have to be
    # kept in step here.
    if not info["onboarding_enabled"]:
        return "\n".join([*lines, ONBOARDING_OFF_HERE]) + "\n"
    url = info["onboarding_url"]
    provenance = printable(str(info["onboarding_provenance"]), UNBOUNDED)
    return (
        "\n".join(
            [
                *lines,
                f"{ONBOARDING_URL_LABEL}, {provenance}:",
                printable(str(url), UNBOUNDED),
            ]
        )
        + "\n"
    )


def _configured_counts(document: Mapping[str, object]) -> str:
    """What `info` prints of the stored half: how much of each kind
    there is, and which agent an unbound board reaches.

    One line, and only of what has something to say. A kind nothing was
    written of is absent rather than printed as a zero: a column of
    zeroes is a tally an operator has to read to learn nothing, and the
    question this command answers is orientation. A count and not the
    tree, for the same reason: `vinga list` prints the contents.

    The kinds, their order and their nouns come from the registry, so a
    kind added there is counted here by existing and named here in the
    word its own command is spelled with. The plural is that noun with
    an `s`, which is derived rather than listed because it is what every
    merged kind's plural is; a kind whose plural is not would be a kind
    whose command noun this rule has to learn about, and it would say so
    in the first render. A kind addressed by no segment is the
    singleton, which there is exactly one of and so no count to give:
    what is worth saying about it is whether anything is set. One
    addressed by two is nested a level deeper, which is the same fact
    its URL states.

    The devices and the default agent are written out for the reason
    `_summary` writes them out: neither is an entity, and forcing them
    into a kind's shape would be inventing a generalization rather than
    finding one. Both say what is true of nothing rather than being
    dropped when they hold nothing, because an unbound board reaching
    no agent is the fact an operator is looking for, not an empty field
    to hide.

    A deployment with nothing at all says exactly that. Empty output
    would read as a command that failed to answer, and this is the state
    a person is in the first time they run it.

    The document is read as its shapes before any of it is counted, by
    the same two steps the tree reads it with: see the notes above
    `_halves` and `_sections`.
    """
    config, _ = _halves(document)
    read = _sections(config)
    counted = [
        f"{count} {kind.name}" if count == 1 else f"{count} {kind.name}s"
        for kind in entities.ENTITIES
        if kind.addressing and (count := _counted(read[kind.moved_key], kind))
    ]
    # The singletons after the counted kinds, in the registry's order
    # within each half, which is the order the plan states and not the
    # order a single pass would happen to produce.
    counted += [
        f"{kind.moved_key} set"
        for kind in entities.ENTITIES
        if not kind.addressing and read[kind.moved_key]
    ]
    devices = len(read["devices"])
    # Asked of the value the answer carried rather than of what it
    # prints as: a null is a deployment with no default agent, and a
    # name that renders to nothing is one that has one, for the reason
    # `UNNAMEABLE` is there for.
    named = read["default_agent"]
    if not counted and not devices and named is None:
        return f"\n{CONFIGURED} {NOTHING_YET}\n"
    counted.append(
        f"{devices} device{'' if devices == 1 else 's'} bound" if devices else "no devices"
    )
    counted.append(
        "no default agent" if named is None else f"default agent {printable(named) or UNNAMEABLE}"
    )
    return f"\n{CONFIGURED} " + ", ".join(counted) + "\n"


def _summary(document: Mapping[str, object]) -> str:
    """The tree `config list` prints: one line per entity, with the
    slots that hold a stored secret named but never their values.

    Rendered from the same masked document `show` prints, which is what
    a read of the whole configuration answers with, so the summary can
    say nothing the document does not carry. Which also means it can say
    anything the document carries: the sections are read as their shapes
    first, and every value that reaches a line goes through the display
    door, so nothing an answer holds is printed as its repr or gets to
    steer the terminal the tree lands on.

    A name is the one value read twice, and the two readings are not the
    same. It is printed through the door like everything else, and it is
    looked up as it arrived: the identity a stored secret is filed under
    is the one the store wrote, so a lookup through the bounded spelling
    would name the slots of a different entity or of none.
    """
    config, secrets = _halves(document)
    read = _sections(config)
    stored = _stored_slots(secrets)
    lines = ["providers:"]
    for stage in PROVIDER_STAGES:
        lines.append(f"  {stage}:")
        lines += [
            f"    {printable(name)}{_summarized('provider', body)}"
            + _slots(stored, "provider", entities.provider_identity(stage, name))
            for name, body in read["providers"].get(stage, {}).items()
        ] or ["    (none)"]

    lines.append("mcp_servers:")
    lines += [
        f"  {printable(name)}{_summarized('mcp-server', body)}"
        + _slots(stored, "mcp_server", name)
        for name, body in read["mcp_servers"].items()
    ] or ["  (none)"]

    lines.append("prompt_fragments:")
    lines += [
        f"  {printable(name)}{_summarized('prompt-fragment', body)}"
        for name, body in read["prompt_fragments"].items()
    ] or ["  (none)"]

    lines.append("agent_defaults" + _summarized("agent-defaults", read["agent_defaults"]))

    lines.append("agents:")
    lines += [
        f"  {printable(name)}{_summarized('agent', body)}"
        for name, body in read["agents"].items()
    ] or ["  (none)"]

    # The two settings' lines are written here rather than summarized by
    # a descriptor: neither is an entity, a binding reads as the agents
    # it points at and the default agent is one name, and forcing them
    # into a kind's shape would be inventing a generalization rather
    # than finding one.
    lines.append("devices:")
    lines += [
        f"  {printable(mac)} {_device_summary(body)}"
        for mac, body in read["devices"].items()
    ] or ["  (none)"]

    # The tree's word for an unset default agent is the tree's `(none)`,
    # which is the answer every other row of it gives to the same
    # question. `info` says it in a sentence instead, because there it
    # is one clause of one line rather than the foot of a list.
    named = read["default_agent"]
    lines.append(f"default_agent: {printable(named) if named else '(none)'}")
    return "\n".join(lines) + "\n"


def _stored_slots(secrets: Sequence[Mapping[str, object]]) -> dict[tuple[str, str], list[str]]:
    """Which slots hold a stored secret, by the entity holding them.

    Every row is read as `StoredSecretLocation` before it gets here, so
    the three fields are there and each of them is a string: this walks
    a shape rather than trusting a body, which is what keeps a row that
    is a number or a list out of the boundary as a `TypeError`.
    """
    grouped: dict[tuple[str, str], list[str]] = {}
    for stored in secrets:
        grouped.setdefault((stored["kind"], stored["identity"]), []).append(stored["slot"])
    return grouped


def _slots(stored: Mapping[tuple[str, str], list[str]], kind: str, identity: str) -> str:
    slots = stored.get((kind, identity), [])
    return f"  [secrets: {', '.join(printable(slot) for slot in slots)}]" if slots else ""


def _contacted(args: Invocation, reached: Reached) -> None:
    """The banner, and the address this CLI is about to contact.

    What `info` knows before it has asked anything, and the half of its
    answer no server can supply: which server it is talking to. The
    device-facing origin the answer carries and the address an operator
    dialled can legitimately differ, so printing one as though it were
    the other would answer the question wrongly rather than not at all.

    `Address.shown` and never `args.api_url`. The transport policy
    refuses a credential in a URL's userinfo and says nothing about its
    query string, so an accepted address can still hold `?token=...`;
    the display form is the one with that taken out, bounded and made
    printable, and it is the only form anything here may name (#290).

    The address is the one this invocation resolved, handed in rather
    than resolved again here, so the line names where the requests after
    it actually go rather than where a second resolution would have gone
    (`Reached`). Flushed for the reason `_acknowledged` flushes: stderr
    is unbuffered and stdout is not, so a refusal from the first act
    would otherwise land above the lines it followed.
    """
    print(BANNER)
    print(f"{CONTACTED}: {reached.address.shown}")
    sys.stdout.flush()


# The reads that are not of one entity: the whole configuration, the
# boards waiting to be claimed, and the three that ask the running
# server rather than the database. The second of those is the device
# noun's and lives beside it; what is here is the rest.


def _config_path(args: Invocation) -> str:
    return _path("config")


def _apply_path(args: Invocation) -> str:
    return _path("runtime", "config", "reload")


def _info_path(args: Invocation) -> str:
    return _path("runtime", "info")


LIST = Act(
    method="GET",
    path=_config_path,
    answers=ConfigDocument,
    render=_printed(_summary),
)

# The same read, rendered as a count per kind. `info`'s second act: what
# it needs of the stored half is its shape rather than its contents, and
# a read that already answers the whole document can be asked for either
# (`show` and `export` are two more renderings of it).
COUNTS = Act(
    method="GET",
    path=_config_path,
    answers=ConfigDocument,
    render=_printed(_configured_counts),
)

SHOW_ALL = Act(
    method="GET",
    path=_config_path,
    answers=ConfigDocument,
    render=_printed(_show_everything),
)

EXPORT_ALL = Act(
    method="GET",
    path=_config_path,
    answers=ConfigDocument,
    render=_printed(_exported),
)

# The read that says which deployment answered, which none of the reads
# above it does: they say what is stored or what is running, and this
# one says whose. `info`'s first act.
IDENTITY = Act(
    method="GET",
    path=_info_path,
    answers=RuntimeInfo,
    render=_printed(_identity_block),
)


def _applied(answer: Mapping[str, Any]) -> None:
    """One apply read out: what it installed, and then that it worked.

    Two streams rather than one, shaped like the import's renderer above
    and for the same reason (#426): what was installed is the artifact
    and goes to stdout, and that the command succeeded is a fact about
    this invocation and goes to stderr. An action that succeeds says so
    in a line of its own, because a listing that stops is not a
    statement that anything worked, and an apply whose whole listing is
    one sentence is exactly where that reads worst.

    Its own callable rather than `_printed`, which prints one string and
    knows nothing of a second stream. The flush between the halves is
    the discipline `_acknowledged` and `_imported_entries` document:
    stderr is unbuffered and stdout is not, so without it the success
    could land above the listing it is about on a merged terminal.
    """
    print(_apply_listing(answer), end="")
    sys.stdout.flush()
    print(INSTALLED, file=sys.stderr)


# The one act that changes what a server is doing without writing
# anything, and it prints both halves of the answer: what the apply
# installed, and what every configured MCP entry is doing now that it
# has been done.
#
# The CLI's `apply` posts to the API's reload route, and that crossing
# is deliberate rather than an oversight (#371): the API names the
# mechanism, which is that the server re-reads the store and swaps the
# world, and the CLI names the act an operator asked for. Whether the
# API's own vocabulary follows is #287's question, not this row's.
APPLY = Act(
    method="POST",
    path=_apply_path,
    read_timeout_s=APPLY_READ_TIMEOUT_S,
    narrates=True,
    answers=ConfigReloadResult,
    refusal=UNREADABLE_APPLY,
    render=_applied,
)


def _diff_path(args: Invocation) -> str:
    return _path("runtime", "config", "diff")


# The read the other two in this namespace cannot give: they say what is
# running and the entity reads say what is stored, and this is the
# question an operator actually has after a write.
DIFF = Act(
    method="GET",
    path=_diff_path,
    answers=ConfigDiff,
    render=_printed(_diff_listing),
)


# The one write that carries the whole configuration rather than one
# entry of it. The document is checked for what JSON cannot carry before
# it travels, exactly as a fragment is and against the same rule, under
# the location the repository names a refusal about the document as a
# whole with.


def _import_path(args: Invocation) -> str:
    # The CLI's `import` posts to the API's apply route, which is the
    # other half of the seam the act above names (#371): the API's word
    # for writing a whole document does not move because the CLI's verb
    # did, and #287 is where the API's own vocabulary is decided.
    return _path("apply")


def _document_body(args: Invocation) -> object:
    document = _fragment(args.file)
    check_transportable(APPLY_LOCATION, document)
    return document


IMPORT = Act(
    method="POST",
    path=_import_path,
    body=_document_body,
    sends=DomainConfig,
    read_timeout_s=IMPORT_READ_TIMEOUT_S,
    narrates=True,
    answers=AppliedDocument,
    refusal=UNREADABLE_WRITE,
    render=_imported,
)
