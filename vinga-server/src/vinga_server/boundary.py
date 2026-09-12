"""The one rule behind the local-first promise (#30, #136, #493).

A fully local deployment is first-class, and the product promise makes
that a guarantee enforced rather than documented
(`docs/architecture/product-promises.md`): everything that can carry
session data off the machine declares how far it travels, and
`server.data_boundary` refuses at startup to build one that travels
further. The enforcement used to exist twice, once in the provider
registry and once in the MCP build path, each with its own semantics,
wording and exception type, and the provider half defaulted an
undeclared type to egress, so a type that forgot to declare merely
looked declared enough to boot. A guarantee spread over two
implementations and a default is one nobody can read in a sitting, so
both live here (#136), and neither caller decides anything: they
translate. The third shape arrived with the OTLP exporter (#66), which
is neither a provider class nor an operator-declared entry, and it
landed here for the same reason rather than as a rule of its own beside
the thing it governs.

This module was `egress.py` until #493, and the rename came with the
vocabulary it enforces. The old names faced the wrong audience and the
old marking was a boolean, which forced a dishonest declaration at
exactly the deployments the local promise courts: a GPU box running
Ollama on the LAN had to stretch `egress: false` to mean "off this host
but not off this network". The three reaches below say that honestly,
the boundary is ordered against them, and the one rule is that a reach
exceeding the boundary refuses to build.

Translation is all the callers do because the exception type is each
surface's own contract. This module raises `BoundaryRefusal` carrying
the finished sentence; `build_provider` re-raises it as `ProviderError`
and `_managers_for` as `McpConfigError`, with the message untouched.
Importing either of those here is what a module below both callers
cannot do, and the reason this one sits beside the packages it serves
rather than inside one of them.

It imports the configuration models under `TYPE_CHECKING` only, and
that is load bearing rather than tidy: `config/models.py` needs `Reach`
for its own fields, so a runtime import back would be a cycle. The
functions here read attributes off a model and never construct one, so
the annotations are quoted and the import costs nothing at run time.

The sentences are operator-facing. They name the configuration entry,
the type, the key to write and the operator's own declared boundary,
and never a value read from an entry: the boundary is what the operator
wrote about their whole server, so speaking it violates nothing and is
what makes the sentence plain, while a base_url, a command or an
endpoint stays out of every one of them.
"""

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vinga_server.config.models import McpServerConfig, ProviderConfig


class Reach(StrEnum):
    """How far session data handed to something travels.

    One enum for both sides of the rule, because a boundary IS a reach:
    the outermost reach session data may have on this server. A second
    enum would be two structures required to agree.

    `host` is the machine this process runs on and nothing beyond it.
    `network` is whatever the machine can address without leaving the
    operator's own network, which is the honest declaration for a model
    server on the LAN. `internet` is everything else.
    """

    HOST = "host"
    NETWORK = "network"
    INTERNET = "internet"


# The ordering the rule needs, written out rather than implied by member
# order. Nothing in this tree compared two levels before #493, so the
# order is new information and belongs somewhere a reader can check it:
# a declaration order that happened to be right would be a fact hidden
# in a line nobody reads as a fact.
_RANK: dict[Reach, int] = {Reach.HOST: 0, Reach.NETWORK: 1, Reach.INTERNET: 2}


def _exceeds(reach: Reach, boundary: Reach) -> bool:
    """Whether something reaching this far leaves the declared
    boundary."""
    return _RANK[reach] > _RANK[boundary]


class BoundaryRefusal(Exception):
    """One entry the data boundary refuses, carrying the finished
    sentence. The wording belongs to this module and the exception type
    to whichever surface asked, which is why the callers re-raise rather
    than let this out."""


# Tells a class that declared `reach = None` from one that declared
# nothing: None is a marking here, and the difference between the two is
# the whole point of the check.
_UNDECLARED = object()


def check_provider(
    label: str, config: "ProviderConfig", provider: object, boundary: Reach | None
) -> None:
    """Enforce the data boundary for one built provider (#30, #493).

    The class-level marking is authoritative; the configuration's
    `reach` key exists only for types that cannot know their own (an
    openai_compatible base_url decides), and declaring it on a type that
    knows is refused in any mode.

    `boundary` of None is no declared boundary, which is the default and
    is today's unrestricted behaviour: nothing here refuses on distance.
    An absent or invalid class marking is refused anyway, because that
    is a programming error rather than a deployment's choice.
    """
    marked = _marking(label, config, provider)
    if marked is not None and config.reach is not None:
        raise BoundaryRefusal(
            f'{label}: "reach" is decided by type "{config.type}" and cannot '
            f"be declared in the configuration; remove the key"
        )
    if boundary is None:
        return
    if marked is not None:
        if _exceeds(marked, boundary):
            # The type's own answer, so the type is the remedy: no key on
            # this entry can change it, and saying which reach the type
            # has is naming a fact written in this repository's own
            # source rather than a value an operator typed.
            raise BoundaryRefusal(
                f'{label}: type "{config.type}" reaches the {marked}, but this '
                f"server's data boundary is {boundary}"
            )
        return
    if config.reach is None:
        raise BoundaryRefusal(
            f"{label}: this server declares a data boundary, and whether type "
            f'"{config.type}" stays inside it depends on its base_url; declare '
            f'"reach: host" or "reach: network" on this entry to state where the '
            f"endpoint stays"
        )
    if _exceeds(config.reach, boundary):
        # The operator's own assertion, so the entry is the remedy, and
        # the sentence says which key to edit without quoting back what
        # it holds.
        raise BoundaryRefusal(
            f'{label}: this entry declares a "reach" outside this server\'s data '
            f"boundary, which is {boundary}; narrow the entry's reach, or widen "
            f"the boundary"
        )


def _marking(label: str, config: "ProviderConfig", provider: object) -> Reach | None:
    """What the built provider's own class declares, refused if it
    declared nothing or declared something that is not a marking (#136).

    Read out of the concrete class's namespace rather than through
    `getattr`, which walks the MRO: a subclass that declares nothing
    would otherwise ride its parent's marking, which is the silent
    default again one level down. Validated as membership of the closed
    set rather than by truthiness, so `reach = 0` fails the build
    instead of passing for something. A bare `"host"` fails too, which
    is the closed set taken literally: a `StrEnum` compares and hashes
    equal to its own value, so a lookalike would rank correctly today
    and go on ranking correctly right up until the set grows a member
    nobody spelled the same way.

    Both refusals fire whatever the boundary, because neither is a
    deployment's choice to make: a type that cannot answer the question
    is a hole in the guarantee wherever it runs, and the operator who
    meets it cannot fix it in their configuration. The class name is a
    code identifier rather than a configured value, so naming it keeps
    the message value-free while pointing at the file to edit.
    """
    kind = type(provider)
    marking = vars(kind).get("reach", _UNDECLARED)
    if marking is _UNDECLARED:
        raise BoundaryRefusal(
            f'{label}: type "{config.type}" builds {kind.__name__}, which declares '
            f'no "reach" of its own; every provider class states how far session '
            f"data given to it travels"
        )
    if not (marking is None or isinstance(marking, Reach)):
        raise BoundaryRefusal(
            f'{label}: type "{config.type}" builds {kind.__name__}, whose "reach" '
            f"is none of host, network, internet or null; correct the declaration "
            f"on the class"
        )
    return marking


def check_feature(label: str, reach: Reach, boundary: Reach | None) -> None:
    """Enforce the data boundary for one feature that is not a provider
    and not an MCP entry (#66).

    The third shape the guarantee comes in, and the reason it is here
    rather than where its one caller is: enforcement used to exist twice
    and diverged, which is what put both of the others in this module,
    and a telemetry exporter deciding for itself what a boundary means
    would be the third copy starting the same way.

    The declaration is the argument, because that is the whole of what
    varies. A provider's marking is read off its class and an MCP
    entry's off the operator's configuration; a feature like the OTLP
    exporter has neither, because how far it reaches is a property of
    what it IS rather than of how it was configured. All three callers
    declare `Reach.INTERNET`, fixed and honest: vinga cannot know where
    `OTEL_EXPORTER_OTLP_ENDPOINT` or `LANGFUSE_HOST` point, and there is
    no per-feature entry to carry an operator's assertion about a
    collector on the LAN. The consequence is stated rather than hidden:
    a `network`-bounded server refuses telemetry even toward a LAN
    collector. Taking the reach as an argument is what makes the
    follow-up that gives those sections their own assertion a change of
    argument rather than a change of shape.

    Called before the feature is built, which is the caller's half of
    the contract and the only way the sentence can honestly say nothing
    was constructed. The sentence names the switch, the boundary and the
    key that widens it, and nothing about the endpoint the operator
    wrote, which is exactly the string a refusal about distance must not
    carry.
    """
    if boundary is None or not _exceeds(reach, boundary):
        return
    raise BoundaryRefusal(
        f"{label}: this sends session data to the {reach}, and this server's data "
        f"boundary is {boundary}; widen server.data_boundary, or switch {label} off"
    )


def check_mcp_server(label: str, entry: "McpServerConfig", boundary: Reach | None) -> None:
    """Enforce the data boundary for one referenced MCP server (#30).

    Tool arguments carry conversation-derived data, and no transport
    knows its own reach (a stdio command may proxy anywhere, a url may
    name localhost), so unlike providers there is nothing class-level to
    consult: every referenced entry needs the operator's declaration.

    Called for EVERY referenced entry, with the boundary handed over
    whatever it is. The caller used to guard this behind `local_only`,
    which was a piece of the policy living outside the module that owns
    it; what an absent boundary means is decided here now, in the one
    place that decides what a declared one means (#493).

    Handed the label rather than the name, exactly as `check_provider`
    above is, and for the reason that made this the odd one of the two:
    it joined `mcp_servers.` to the name itself, which is one location
    spelled twice inside one build, since the caller composes the same
    string for the refusal it raises beside this one. The caller
    composes it once now, through `entity_location`, the one home for
    where an entry is written (#420).
    """
    if boundary is None:
        return
    if entry.reach is None:
        raise BoundaryRefusal(
            f"{label}: this server declares a data boundary, and whether an MCP "
            f"server stays inside it cannot be known from its transport; declare "
            f'"reach: host" or "reach: network" on this entry to state where '
            f"whatever its command or URL reaches stays"
        )
    if _exceeds(entry.reach, boundary):
        raise BoundaryRefusal(
            f'{label}: this entry declares a "reach" outside this server\'s data '
            f"boundary, which is {boundary}; narrow the entry's reach, or widen "
            f"the boundary"
        )
