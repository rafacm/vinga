"""The commanded kinds: their acts, their renderers and their secrets.

Provider, MCP server, prompt fragment, agent, agent defaults and the
default agent, with the credential slots the first two hold. The five
commanded kinds' rows are built rather than written out: where a kind
is on the API, what addresses one entry of it and which section it
occupies in the configuration document are data on its descriptor, and
the builders here read them straight off it.

What its callers stop knowing: how a kind is addressed, what a masked
entity body looks like on a terminal, and what a document's sections
are. The registry answers the first, the renderers here answer the
second, and `_sections` is the one place any renderer of the whole
configuration learns the third, so a count and a tree cannot come to
walk one document two ways.

`entities` in this module is the registry, `vinga_server.config.entities`,
which is what every other module of this package calls by that name too.
"""

from collections.abc import Callable, Mapping
from typing import Any

from vinga_server.config import entities
from vinga_server.config.models import MASK
from vinga_server.config.printing import printable
from vinga_server.config.responses import (
    Acknowledgement,
    AgentRename,
    AssembledPrompt,
    DefaultAgentName,
    Envelope,
    McpServerStatus,
    SecretValue,
    StoredSecretLocation,
)
from vinga_server.config.transport import check_transportable

from .acts import UNREADABLE_READ, UNREADABLE_WRITE, Act, _path, _printed
from .answers import _understood
from .input import _read_secret, _written_entity
from .invocation import Invocation
from .output import _acknowledged, _inline, _names, _short, _yaml
from .reach import PROGRAM

# How a stored secret is introduced in `show` and `list`. Comment lines
# rather than a mapping: the mask is not a value that could be written
# back, and saying so in the document is more honest than rendering it
# as though it could.
SECRETS_HEADING = f"# stored secrets, set with: {PROGRAM} <kind> secret set"

NOTHING_CONFIGURED = (
    f"this server has no MCP servers configured. An entry is written with "
    f"`{PROGRAM} mcp-server set`, and an agent reaches it by naming it in "
    f"its mcp list"
)


def _secret_path(args: Invocation) -> str:
    if args.kind == "provider":
        return _path("providers", args.stage, args.name, "secrets", args.slot)
    return _path("mcp-servers", args.name, "secrets", args.slot)

EXPORT_SLOTS_HEADING = (
    "# Stored credentials are not exported. These slots hold one, and each is entered\n"
    f"# with `{PROGRAM} <kind> secret set`:"
)


def _exported_entity(kind: entities.EntityDescriptor) -> Callable[[Any], str]:
    """One entity's fragment, as the command that writes one takes it.

    The header names the kind and the command rather than the entity,
    because a fragment does not carry where it goes: what a fragment is
    for is being written somewhere, and the `set` that writes it is
    where that is chosen.
    """
    header = f"# One {kind.title.lower()} ({kind.location}), as written by\n# `{kind.command}`.\n"

    def exported(envelope: Mapping[str, object]) -> str:
        return header + _yaml(envelope["entity"]) + _stored_slot_note(envelope["secrets"])

    return exported


def _stored_slot_note(secrets: Mapping[str, object]) -> str:
    """The slots of one entity that hold a stored credential, named
    rather than commanded: a fragment does not say which entity it is
    for, so neither can the command that fills its slots."""
    if not secrets:
        return ""
    return "\n".join(["", EXPORT_SLOTS_HEADING, *(f"#   {slot}" for slot in secrets)]) + "\n"


def _print_entity(envelope: Mapping[str, object]) -> None:
    """One entity's envelope as YAML: the masked body, and its stored
    slots as comment lines. Comments rather than a mapping, because the
    mask is not a value that could be written back, and saying so in the
    document is more honest than rendering it as though it could."""
    body = envelope["entity"]
    notes = _secret_notes(body, envelope["secrets"])
    print(_yaml(body) + ("\n" + "\n".join(notes) + "\n" if notes else ""), end="")


def _secret_notes(body: Mapping[str, object], secrets: Mapping[str, object]) -> list[str]:
    notes = [
        f"#   {slot}: {MASK}" + _shadow_note(body, marks["shadows"])
        for slot, marks in secrets.items()
    ]
    return [SECRETS_HEADING, *notes] if notes else []


def _shadow_note(body: Mapping[str, object], shadows: object) -> str:
    """What a stored secret displaces, when the entity also carries a
    reference for the same slot. Ciphertext wins, and making that
    visible is what keeps the precedence from being silent.

    Both halves of the note come out of the answer, so both are
    rendered rather than interpolated: the key through the display door,
    and the value the entity writes under it through the same rule a
    body's values are rendered by anywhere else, so a structure there is
    named rather than opened.
    """
    reference = _reference_value(body, str(shadows)) if shadows else None
    if not reference:
        return ""
    return f"  (used instead of {printable(str(shadows))}: {_short(reference)})"


def _reference_value(body: Mapping[str, object], key: str) -> object:
    """What an entity writes under one of its reference-carrying keys,
    addressed the way a stored secret addresses it: a dotted key reaches
    into an MCP server's env or headers, a bare one is a provider's own
    key. Masked already, because the body it reads is."""
    group, dotted, name = key.partition(".")
    if not dotted:
        return body.get(key)
    nested = body.get(group)
    return nested.get(name) if isinstance(nested, Mapping) else None


def _status_block(entries: Mapping[str, Mapping[str, object]]) -> str:
    """What every configured MCP server is doing, one block each.

    A block rather than a row of columns, because two of the three
    things worth reading are lists: the tools the server published, and
    the agents that may reach it. A column holding a list is a column
    that wraps, and the pending listing's shape only works because every
    one of its fields is short.

    One function and not two: the apply answers one of these inside its
    own shape, and the reading is the act's either way, so there is
    nothing left for a second entry point to do.
    """
    if not entries:
        return f"{NOTHING_CONFIGURED}\n"
    lines: list[str] = []
    for name, entry in entries.items():
        reason = entry["reason"]
        lines.append(
            f"{printable(name)}: {entry['state']} since {printable(str(entry['since']))}"
            + (f" ({printable(str(reason))})" if reason is not None else "")
        )
        lines.append("  tools: " + (_names(entry["tools"]) or "(none)"))
        lines.append("  agents: " + (_granted(entry["grants"]) or "(none)"))
    return "\n".join(lines) + "\n"


def _granted(grants: Mapping[str, object]) -> str:
    """Which agents may reach the server, and how much of it: a bare
    name is the whole server, and a name followed by tools in
    parentheses is the allow list that agent was given. Sorted by agent
    name, so two reads of an unchanged world print the same block."""
    return ", ".join(
        f"{printable(agent)} ({allowed})" if (allowed := _names(tools)) else printable(agent)
        for agent, tools in sorted(grants.items())
    )


def _prompt_listing(body: Mapping[str, Any]) -> str:
    """The assembled prompt, block by block, and its total size.

    Every block is printed whole. This command exists to show what the
    model is given, so a concealed tail is exactly what the operator
    came to see, which is why nothing here goes through `printable`:
    that renderer strips a value and cuts it at `GLIMPSE_LENGTH`, which
    is right for an acknowledgement and fatally wrong here.

    The counts printed are the ones the server reported, which count
    what is stored and sent, so a replaced character below never
    falsifies the accounting.
    """
    lines: list[str] = []
    for block in body["blocks"]:
        named = block.get("name")
        lines.append(
            f"{_block(str(block['provenance']))} ({block['characters']} characters)"
            + (
                ""
                if named is None
                else f", the server prompt named {_block(str(named))}"
            )
        )
        lines.append(_block(str(block["text"])))
        lines.append("")
    lines.append(f"total: {body['characters']} characters")
    return "\n".join(lines) + "\n"


def _block(value: str) -> str:
    """A whole block of prompt text, made safe for a terminal and
    nothing else.

    Newlines and tabs pass, because a prompt is written in them.
    Everything else unprintable is replaced rather than dropped, so an
    escape sequence cannot drive the terminal and a block that arrived
    mangled reads as mangled. Nothing is truncated, ever: this is an
    inspection command, and a renderer that quietly cut the text would
    make it lie about the one thing it exists to show.

    Applied to the provenance and to a block's name as well as to its
    text. The provenance names an entry an operator wrote; the name is a
    prompt name a server chose and an operator copied, so nothing bounds
    what it holds, and it is exactly the string a hostile server would
    put an escape sequence in.
    """
    return "".join(
        character if character.isprintable() or character in "\n\t" else "?"
        for character in value
    )


# What a rendering of the masked configuration depends on, and what
# says so
#
# `ConfigDocument` declares the document as `dict[str, Any]` and stops
# there, deliberately: the document's shape is its own prose, and the
# entity models cannot validate an entry whose credential-bearing values
# have been replaced by the mask. So the act's answer is read as far as
# the outer mapping and no further, and everything under it is a body
# nobody has vouched for.
#
# Both renderings of that document need more than that: that a section
# is a mapping of entry bodies, that a provider section is a mapping of
# those, that a device is bound to a list of agent names, and that the
# default agent is a name or nothing. Those are read as shapes through
# `_understood`, like every other answer this module renders, so a
# section that is a number, a list or absent meets the one fixed
# sentence a body this client cannot read gets, rather than a
# `TypeError` or a `KeyError` leaving the boundary as a traceback with
# the answer inside it.
#
# One shape per fact and one reading for both renderers, because a
# count and a tree are two renderings of one document and not two
# documents: `_sections` below is the whole of what either of them
# knows about the nesting, so a count that walked a section one way
# while the tree walked it another is a disagreement that cannot be
# written.

# A mapping of keys with nothing said about what any of them holds. One
# entry's masked body is this, and so is the document's own mapping of
# sections, which is read as this for the same reason: what is wanted of
# either is that it is a mapping at all, and what is under it is read
# one key at a time by whatever knows the key.
BODY = dict[str, Any]

ENTRIES = dict[str, BODY]

STAGED_ENTRIES = dict[str, ENTRIES]

# The devices section, which is the one entity-shaped thing in the
# document that is not an entity: a MAC, and the record under it. Read
# as a body for the reason an entry's body is read as one: what is
# wanted of it is that it is a mapping at all, and each key is read by
# whatever knows the key.
BOUND = dict[str, BODY]

NAMED = str | None

# The document's other half, read as the model the API answers it with
# rather than as a second description of it here.
STORED = list[StoredSecretLocation]


def _nesting(kind: entities.EntityDescriptor) -> object:
    """How deep one kind's section sits in the document, read off the
    registry.

    A kind addressed by two segments is a mapping of mappings exactly as
    it is two path parameters on the API, and one addressed by none is
    the singleton, which is one body rather than a mapping of them.
    Which is one fact read off the addressing rather than three written
    down.
    """
    if len(kind.addressing) > 1:
        return STAGED_ENTRIES
    return ENTRIES if kind.addressing else BODY


def _halves(document: object) -> tuple[dict[str, Any], list[Any]]:
    """The masked document's two halves, each read as its shape.

    Where every renderer of the whole configuration starts, and it takes
    `object` rather than a mapping deliberately: the answer is read as a
    mapping BEFORE anything is looked up in it. A `.get` is a method
    call, so a document that answered a string or a list would leave
    this as an `AttributeError` from outside the boundary, which is the
    same traceback the sections used to produce one level down.

    Read here, and not because `ConfigDocument` leaves either half in
    doubt: a renderer whose safety depends on which act called it is
    safe by arrangement, and the arrangement is not in the function.

    The secrets are read even by a rendering that prints none of them.
    The refusal is about the document, not about the line: a body this
    client cannot read is one that did not come from this API, and which
    half of it a particular command would have walked into is not what
    makes that true.
    """
    read = _understood(BODY, document, UNREADABLE_READ)
    return (
        _understood(BODY, read.get("config"), UNREADABLE_READ),
        _understood(STORED, read.get("secrets"), UNREADABLE_READ),
    )


def _sections(config: Mapping[str, object]) -> dict[str, Any]:
    """Every section of the masked document, read as the shape the
    registry says it has.

    The one place any renderer learns what a section is. The kinds and
    their nesting come from the registry, so a kind added there is read
    here by existing; the devices and the default agent are written out
    because neither is an entity, and forcing them into a kind's shape
    would be inventing a generalization rather than finding one.

    `.get` rather than a subscript throughout, so a section the answer
    left out arrives as None and meets the same refusal a malformed one
    does, instead of a `KeyError` from outside the boundary.

    Every section rather than only the ones a given rendering prints,
    for the reason `_halves` reads both halves.
    """
    read = {
        kind.moved_key: _understood(_nesting(kind), config.get(kind.moved_key), UNREADABLE_READ)
        for kind in entities.ENTITIES
    }
    return read | {
        "devices": _understood(BOUND, config.get("devices"), UNREADABLE_READ),
        "default_agent": _understood(NAMED, config.get("default_agent"), UNREADABLE_READ),
    }


def _counted(section: Mapping[str, object], kind: entities.EntityDescriptor) -> int:
    """How many entries one section of the masked document holds.

    The section is already read as its shape, so this is arithmetic: a
    staged kind is counted a level deeper because that is where its
    entries are, which is the same fact `_nesting` reads off the
    addressing.
    """
    if len(kind.addressing) > 1:
        return sum(len(under) for under in section.values())
    return len(section)


# How one entry of each kind reads in that tree, after its name: which
# engine a provider is, how an MCP server is reached, what a fragment
# costs, what an agent overrides. Five answers to one question, so the
# tree above asks by kind rather than knowing them, and the table that
# answers is at the foot of this group: it is read here and written here,
# which is the whole of what a per-kind mapping has to be.


def _summarized(kind: str, body: Mapping[str, object]) -> str:
    return _SUMMARY[kind](body)


def _provider_summary(body: Mapping[str, object]) -> str:
    """Its type, which is what a provider is: everything else in the
    entry is options for that type.

    A body is a mapping and nothing is declared about what a key of one
    holds, so the type is whatever answered. It is rendered by `_short`,
    the same rule the inlined bodies below are written with rather than
    a second one here: a word reads as itself through the display door,
    a mapping reads as the fact that it is one, and neither can arrive
    as a repr or steer the terminal. An entry with no type at all reads
    as `None`, which is what it is.
    """
    return f" ({_short(body.get('type'))})"


def _mcp_server_summary(body: Mapping[str, object]) -> str:
    return f" ({_short(body.get('transport'))})"


def _prompt_fragment_summary(body: Mapping[str, object]) -> str:
    """The size rather than the text: this is the tree, and what an
    operator reads it for is which fragments exist and what each of them
    costs the prompt budget. `prompt-fragment show` prints one whole,
    and `agent preview <name>` prints what an agent adds up to.

    The one suffix with nothing of the document on it: what it prints is
    a length this counted, so a fragment whose text is a structure or a
    number reads as a size rather than as itself, and there is nothing
    here for the display door to bound.
    """
    return f" ({len(str(body.get('text', '')))} characters)"


def _agent_summary(body: Mapping[str, object]) -> str:
    """What the agent overrides, which is its body without the prompt:
    that is what the line has room for, and `agent show` is where the
    prompt is read."""
    layer = {key: value for key, value in body.items() if key != "prompt"}
    return f": {_inline(layer)}" if layer else ""


def _agent_defaults_summary(body: Mapping[str, object]) -> str:
    """The singleton, which has no name of its own on the line, so what
    follows the section's own name is all of it. Empty is a state worth
    printing: it means every agent has to name everything itself."""
    return f": {_inline(body) or '(none)'}"


_SUMMARY: dict[str, Callable[[Mapping[str, object]], str]] = {
    "provider": _provider_summary,
    "mcp-server": _mcp_server_summary,
    "prompt-fragment": _prompt_fragment_summary,
    "agent": _agent_summary,
    "agent-defaults": _agent_defaults_summary,
}


def _identity(descriptor: entities.EntityDescriptor, args: Invocation) -> tuple[str, ...]:
    """What addresses one entry of this kind, taken off the command
    line. The descriptor's parameters are the URL's path parameters and
    the CLI's positional arguments, which are the same names for the
    same reason, so a provider's two are read the way every other kind's
    one is."""
    return tuple(getattr(args, parameter) for parameter in descriptor.addressing)


def _entity_path(
    descriptor: entities.EntityDescriptor, *under: str
) -> Callable[[Invocation], str]:
    """Where one entry of this kind is, and what is addressed under it."""

    def path(args: Invocation) -> str:
        return _path(descriptor.route.lstrip("/"), *_identity(descriptor, args), *under)

    return path


def _fragment_body(
    descriptor: entities.EntityDescriptor,
) -> Callable[[Invocation], object]:
    """The entity a write of this kind carries, from a YAML fragment or
    from inline `key=value` arguments, refused before it travels if JSON
    has no way to say what YAML said.

    One body for both ways of writing one, which is the whole of what
    the inline form is: the pairs assemble the mapping the fragment
    would have held, and everything after that is the same.

    Where it is being written is named as the kind's own section and no
    further. The addressed form (`providers.<stage>.<name>`) used to be
    built here, out of the stage and the name this command line carried,
    and a refusal is exactly where those must not be said: the mistake
    that reaches this one is a value nothing has validated, typed where
    an identity or a credential goes.
    """

    def body(args: Invocation) -> object:
        fragment = _written_entity(args)
        check_transportable(descriptor.moved_key, fragment)
        return fragment

    return body


SET_ENTITY: dict[str, Act] = {
    kind.name: Act(
        method="PUT",
        path=_entity_path(kind),
        body=_fragment_body(kind),
        sends=kind.model,
        answers=Acknowledgement,
        refusal=UNREADABLE_WRITE,
        render=_acknowledged,
    )
    for kind in entities.ENTITIES
}

# The singleton has no delete anywhere, and says so by carrying
# `has_delete=False` rather than by being named as an exception here.
DELETE_ENTITY: dict[str, Act] = {
    kind.name: Act(
        method="DELETE",
        path=_entity_path(kind),
        answers=Acknowledgement,
        refusal=UNREADABLE_WRITE,
        render=_acknowledged,
    )
    for kind in entities.ENTITIES
    if kind.has_delete
}

SHOW_ENTITY: dict[str, Act] = {
    kind.name: Act(
        method="GET",
        path=_entity_path(kind),
        answers=Envelope,
        render=_print_entity,
    )
    for kind in entities.ENTITIES
}


# The one act on a kind that is neither a read nor a write of an entry:
# it gives one agent another name and moves everything still keyed by
# the old one with it, in one transaction. Written out rather than built
# per kind, because the API has this route under the agents and under
# nothing else.
#
# Where it goes still comes off the descriptor, exactly as the four
# above it do, so the noun this verb sits under and the path it
# addresses cannot come to disagree.


def _new_name(args: Invocation) -> object:
    """The name a rename is to give the agent it addresses.

    Sent as it was typed. What a name is allowed to be is the
    repository's decision, made once there and answered in one
    refusal, so nothing here strips it, measures it or looks at it: a
    second reading would be a second vocabulary for one rule.
    """
    return {"to": args.to}


RENAME_AGENT = Act(
    method="POST",
    path=_entity_path(entities.descriptor("agent"), "rename"),
    body=_new_name,
    sends=AgentRename,
    answers=Acknowledgement,
    refusal=UNREADABLE_WRITE,
    render=_acknowledged,
)


def _default_agent_path(args: Invocation) -> str:
    return _path("default-agent")


def _default_agent_name(args: Invocation) -> object:
    return {"name": args.name}

SET_DEFAULT_AGENT = Act(
    method="PUT",
    path=_default_agent_path,
    body=_default_agent_name,
    sends=DefaultAgentName,
    answers=Acknowledgement,
    refusal=UNREADABLE_WRITE,
    render=_acknowledged,
)

CLEAR_DEFAULT_AGENT = Act(
    method="DELETE",
    path=_default_agent_path,
    answers=Acknowledgement,
    refusal=UNREADABLE_WRITE,
    render=_acknowledged,
)


# A stored credential is addressed under the entity that holds it, in
# the slot it fills, which is why these two rows are not an entity's.
# One command covers both kinds, and which sentence follows the entity a
# credential is stored on is the API's answer: it has four secret
# routes, each statically one of them.


def _secret_body(args: Invocation) -> object:
    return {"secret": _read_secret(args)}


SET_SECRET = Act(
    method="PUT",
    path=_secret_path,
    body=_secret_body,
    sends=SecretValue,
    answers=Acknowledgement,
    refusal=UNREADABLE_WRITE,
    render=_acknowledged,
)

CLEAR_SECRET = Act(
    method="DELETE",
    path=_secret_path,
    answers=Acknowledgement,
    refusal=UNREADABLE_WRITE,
    render=_acknowledged,
)


def _running_path(args: Invocation) -> str:
    return _path("runtime", "mcp-servers")


def _assembled_path(args: Invocation) -> str:
    return _path("runtime", "agents", args.name, "prompt")

EXPORT_ENTITY: dict[str, Act] = {
    kind.name: Act(
        method="GET",
        path=_entity_path(kind),
        answers=Envelope,
        render=_printed(_exported_entity(kind)),
    )
    for kind in entities.ENTITIES
}

# A read of the running server rather than of the database: what a
# database says about an entry is what `show mcp-server` prints, and a
# stopped server has no state to report.
STATUS = Act(
    method="GET",
    path=_running_path,
    answers=dict[str, McpServerStatus],
    render=_printed(_status_block),
)

# The other read of the running server: the persona is stored and the
# guidance is stored, but what they add up to is a property of the
# process that loaded them.
PROMPT = Act(
    method="GET",
    path=_assembled_path,
    answers=AssembledPrompt,
    render=_printed(_prompt_listing),
)
