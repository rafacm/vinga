"""The grammar: the command registry, and the tree it builds.

One row per command: where it sits in the command tree, what it does,
and how it declares its arguments. The table is the whole of the
grammar and `command()` is the only reader of a row, so adding a
command is a row rather than a paragraph of parser construction.

What its callers stop knowing: everything about the parser. One
function answers with the whole tree, built per call so that nothing is
stateful, and the committed reference is rendered from that same tree
rather than from a second description of it.

The generated half of `docs/reference/cli.md` is here rather than in
`docgen` because what it renders is the command tree, and the command
tree is this module: a renderer of it that lived anywhere else would
import the app to reach what its neighbour already has, which is the
pass-through the design guide deletes.
"""

import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from typing import Annotated, Any

import typer
from typer._click.core import Context
from typer._click.exceptions import NoArgsIsHelpError
from typer.core import TyperCommand, TyperGroup

from vinga_server.config import docgen, entities, server_reference
from vinga_server.config.loader import CONFIG_ENV_VAR, load_environment_file
from vinga_server.config.models import API_MOUNT_PATH, PROVIDER_STAGES
from vinga_server.logs import quiet_vendor_libraries
from vinga_server.simulator import board, capabilities

from .acts import Act, _performed
from .deployment import (
    APPLY,
    COUNTS,
    DIFF,
    EXPORT_ALL,
    IDENTITY,
    IMPORT,
    LIST,
    SHOW_ALL,
    _contacted,
)
from .devices import (
    ADD_DEVICE,
    BIND_DEVICE,
    CLEAR_DEVICE_LOCATION,
    DELETE_DEVICE,
    PENDING,
    RELOCATE_DEVICE,
    RENAME_DEVICE,
    REPLACE_DEVICE,
    SHOW_DEVICE,
)
from .entities import (
    CLEAR_DEFAULT_AGENT,
    CLEAR_SECRET,
    DELETE_ENTITY,
    EXPORT_ENTITY,
    PROMPT,
    RENAME_AGENT,
    SET_DEFAULT_AGENT,
    SET_ENTITY,
    SET_SECRET,
    SHOW_ENTITY,
    STATUS,
)
from .events import (
    EVENTS_DEVICE_HELP,
    EVENTS_LEVEL_HELP,
    EVENTS_SESSION_HELP,
    FOLLOW_HELP,
    TAIL_HELP,
    _events_tail,
)
from .input import _permitted_to_destroy
from .invocation import Invocation
from .local import CHECK_HELP, _check, _openapi, _ota_url, _reference, _schema
from .reach import API_URL_ENV, PROGRAM, Reached, _reached
from .records import (
    CLEAR_AGENT_MEMORY,
    CLEAR_DEVICE_MEMORY,
    CLEAR_STATE,
    CORRECT_AGENT_FACT,
    CORRECT_DEVICE_FACT,
    DELETE_CONVERSATION,
    DELETE_SESSION,
    FORGET_AGENT_FACT,
    FORGET_DEVICE_FACT,
    LIST_AGENT_MEMORIES,
    LIST_CONVERSATION_MEMORIES,
    LIST_CONVERSATIONS,
    LIST_DEVICE_MEMORIES,
    LIST_METRICS,
    LIST_SESSIONS,
    PURGE_SESSIONS,
    READ_AGENT_MEMORY,
    READ_DEVICE_MEMORY,
    READ_DIALOGUE,
    READ_STATE,
    SHOW_CONVERSATION,
    SHOW_METRIC,
    SHOW_SESSION,
    _memory_correction,
    _memory_deletion,
    _memory_listing,
)
from .simulator import (
    CLAIM_HELP,
    ENDPOINT_HELP,
    MAC_HELP,
    RUN_HELP,
    _simulator_check_in,
    _simulator_run,
)

# What `--version` answers with. The distribution's name rather than
# either invocation's, and the version read off the installed
# distribution rather than written here, so the two halves of a
# deployment can be compared without either of them being asked to
# remember a number. It is the same string whichever way this was
# reached, because a version is a fact about the artifact.
DISTRIBUTION = "vinga-server"

# And what it says when there is no installed distribution to ask, which
# is a tree on `sys.path` with nothing installed from it. A fixed word
# rather than a guess: a version this code invented would be worse than
# no version at all, since the whole point of the read is comparing two
# halves.
VERSION_UNKNOWN = "unknown (nothing is installed under this name)"


# What the context holds after a group has parsed its own options: the
# word that would name a command, and the words after it. Click reads
# exactly these two to decide whether a command was named at all, and
# `_Grouped` reads them for the same decision.
#
# Named rather than felt for, like the exception classes at the top of
# this module and for the same reason: the leading underscore is Typer's
# copy of Click's private spelling, and a release that renames it must
# fail loudly here (an `AttributeError` on the first invocation, which
# every test of this grammar makes) rather than quietly answer False and
# turn every invocation into a bare one.
_LEFT_TO_RESOLVE = ("_protected_args", "args")


class _Grouped(TyperGroup):
    """Every group of this grammar: the root, and one per noun path.

    What it adds is the answer to an invocation that reached a group and
    named no command under it. `vinga`, `vinga provider` and `vinga
    device pending` are each a page of the grammar with nothing chosen
    off it, and what the reader needs there is the list of what they
    could have chosen, without typing a second command to see it. So the
    group raises `NoArgsIsHelpError`, which is Click's own class for
    exactly that meaning, and the boundary prints its context's page the
    way it prints every other answer to an invocation that was not a
    completed command: on stderr, exiting 1.

    Raised here rather than left to Click for two reasons, and the first
    is the load-bearing one. Click states this mistake as a sentence on
    the base `UsageError` ("Missing command."), which is the same class
    and the same shape as an unknown command and an argument too many,
    both of which quote what was typed; a boundary that told them apart
    by wording could be handed the wording. Raising it here makes the
    class the answer. And Click's own `no_args_is_help` sees only the
    case where nothing at all followed, while `vinga --api-url URL` also
    named no command and is also owed the page.

    The library's flag stays off, so this is the one place the decision
    is made.
    """

    def invoke(self, ctx: Context) -> Any:
        if not any(getattr(ctx, held) for held in _LEFT_TO_RESOLVE):
            raise NoArgsIsHelpError(ctx)
        return super().invoke(ctx)


def _cli_reference(args: Invocation) -> None:
    """The generated half of the committed CLI reference, the fourth
    artifact CI diffs its committed copy against. Renders the command
    tree and reads the example fragments, and opens nothing else."""
    print(cli_reference(), end="")


# The committed command reference
#
# `docs/reference/cli.md` is half written and half generated, and the
# generated half is this. It lives here rather than in `docgen` because
# what it renders is the command tree, and the command tree is this
# module: a renderer of it that lived anywhere else would import the app
# to reach what its neighbour already has, which is the pass-through the
# design guide deletes. That is the second deliberate exception to
# `docgen`'s no-application rule, beside `openapi()`, and it is the same
# exception: rendering help opens no database, reads no configuration
# file and needs no key, so the command in front of this is as read-only
# as its three neighbours.
#
# Deterministic, because CI diffs it byte for byte. Click's help
# formatter sizes itself to the terminal it is printing into and colors
# what it prints, and neither of those may reach a committed file, so
# every page below is rendered through a context that states its width
# and refuses color. Nothing else about the output depends on the
# machine: the tree is built from the table, and the table is a literal.

# Where the generated region of the committed page begins and ends. The
# hand-written half around it is prose nobody generates (installing the
# thing, reaching a server, rebuilding one), so the drift check
# compares the region between these two markers and leaves the rest
# alone.
REFERENCE_BEGIN = "<!-- generated: cli reference -->"

REFERENCE_END = "<!-- end generated: cli reference -->"

# And a pair inside that pair, around the recipes alone.
#
# Not decoration and not a second copy of the outer lane. The outer check
# regenerates the whole region through the page composer below, so a
# composer that dropped, truncated or reordered the recipes would move
# the committed page and the fresh render together and pass. The inner
# check compares the same bytes against the recipe renderer directly,
# which is the only reader that can tell those two apart, and it is what
# the plan asks the recipes to have of their own.
RECIPES_BEGIN = "<!-- generated: cli recipes -->"

RECIPES_END = "<!-- end generated: cli recipes -->"

# What every help page is wrapped at, stated rather than discovered. 80
# is the width the rest of the generated documentation wraps prose at,
# two columns wider, and it is what keeps a help page inside a fenced
# block on a page somebody reads on a phone.
REFERENCE_WIDTH = 80

# Both spellings of the request for help, on every page of the tree.
# `-h` is the one half the world types first, and a program that answers
# only the long one answers nothing to that.
#
# Named rather than written into the app, because two readers need the
# same answer: the live tree takes it as a context setting, and the
# renderer below builds its own root context by hand and would otherwise
# render pages listing a spelling the live tree does not have, or the
# other way round. Every page under the root inherits it from its
# parent context.
HELP_OPTION_NAMES = ["-h", "--help"]

REFERENCE_INTRO = (
    "Generated by `{program} cli-reference`. Do not edit anything between the two "
    "markers around it by hand: CI regenerates this region and fails on any "
    "difference, so an edit here is reverted by the next run. Everything outside them "
    "is written by hand and generated by nothing."
)

RECIPES_INTRO = (
    "One topic at a time, in the order the whole list runs in against an empty "
    "database. Every line below is read out of the example file it names, so a recipe "
    "cannot come to name a file that moved or an entity name a fragment no longer "
    "uses, and every line but one is run against a live server on every build. The "
    f"exception is the `{PROGRAM} apply` a preset's recipe ends with: installing a "
    "preset builds what it names, which is a download of speech models for one of "
    "them and a vendor endpoint for the other, so the build imports both presets and "
    "installs neither. Everything else here is run exactly as it is printed."
)

COMMANDS_INTRO = (
    "Every command of the group, with the page its own `--help` prints. A command "
    "takes `--config` and `--api-url` before the command word as well as after it, "
    "and a value given before it survives a command that was not given one."
)


def cli_reference() -> str:
    """The generated region of `docs/reference/cli.md`.

    Two halves, because a reference answers two questions. The recipes
    say what to type to configure a deployment, read out of the example
    fragments by `docgen`. The command pages say what every command
    takes, read off the command tree here. Neither is written twice.
    """
    lines = [
        *_paragraph(REFERENCE_INTRO.format(program=PROGRAM)),
        "",
        "## Recipes",
        "",
        *_paragraph(RECIPES_INTRO),
        "",
        RECIPES_BEGIN,
        *cli_recipes().splitlines(),
        RECIPES_END,
        "",
        "## Every command",
        "",
        *_paragraph(COMMANDS_INTRO),
        "",
        *_help_pages(command(), (PROGRAM,), None),
    ]
    return "\n".join(lines).rstrip("\n") + "\n"


def cli_recipes() -> str:
    """The recipes alone, exactly as they sit between their own markers
    on the committed page.

    The composer above pastes this between the markers rather than
    building the recipes itself, and the inner drift check compares the
    page's own bytes against this, so what the check reads and what the
    page carries are the same rendering rather than two of them. The
    leading blank line is part of it: a paragraph pressed against an
    HTML comment is swallowed into the comment's block by every markdown
    renderer there is, and the extraction is "the lines between the two
    markers", which has to be able to say so exactly.
    """
    return "\n".join(["", *docgen.recipe_lines()]) + "\n"


def _help_pages(shape: Any, words: tuple[str, ...], parent: Any) -> list[str]:
    """One command's help page, and the pages of the commands under it.

    The context is built with its width and its color stated, which is
    the whole of what makes this deterministic: left to itself Click
    measures the terminal it is printing into, and a document that
    wrapped differently on a laptop and on a runner would fail its own
    drift check on an unrelated change.
    """
    context = Context(
        shape,
        info_name=words[-1],
        parent=parent,
        terminal_width=REFERENCE_WIDTH,
        max_content_width=REFERENCE_WIDTH,
        color=False,
        help_option_names=HELP_OPTION_NAMES,
    )
    lines = [
        f"### `{' '.join(words)}`",
        "",
        "```",
        *shape.get_help(context).splitlines(),
        "```",
        "",
    ]
    for word, under in getattr(shape, "commands", {}).items():
        lines += _help_pages(under, (*words, word), context)
    return lines


def _paragraph(text: str) -> list[str]:
    """One paragraph of the generated region, wrapped where the rest of
    the generated documentation wraps its prose."""
    return textwrap.wrap(
        text, width=docgen.PROSE_WIDTH, break_long_words=False, break_on_hyphens=False
    )


# What each of the two global options says, and the two positions they
# are accepted in. Both readings are natural: `vinga-server --config
# path` is how the server takes it, and options after their subcommand
# is how everything else does.
CONFIG_HELP = (
    f"path to the YAML config file naming server.port and server.api.secret_env "
    f"(default: ${CONFIG_ENV_VAR})"
)

API_URL_HELP = (
    f"base URL of the configuration API (default: ${API_URL_ENV}, then "
    f"http://127.0.0.1:<server.port>{API_MOUNT_PATH})"
)

FILE_HELP = (
    "YAML fragment for this entity, or - to read it from stdin; the alternative to "
    "key=value arguments, and never both (default: none, and one of the two forms "
    "must be given)"
)

DOCUMENT_HELP = (
    "YAML document to import, or - to read it from stdin: the sections of the domain "
    "configuration, with the entities in each written as they are for set"
)

PAIRS_HELP = (
    "the entity written inline, one key=value per field; a dotted key nests "
    "(filler.enabled=true) and a value reads as one YAML scalar. The alternative to "
    "-f, and never both"
)

# What the help page of every `set` command opens with. The store
# already refuses a plaintext credential by the shape of the key it was
# written under, whichever way the entity was written; what this adds is
# the reason an inline value is the wrong place for one even when the
# key would have been accepted.
SECRET_NOT_A_PAIR = (
    f"A credential is never a key=value argument: arguments land in shell history and "
    f"in the process list. Store one with `{PROGRAM} <kind> secret set`, which reads "
    "it from stdin or from the variable --from-env names, and never echoes it."
)

FROM_ENV_HELP = (
    "read the value from this variable (default: stdin, read without echo at a terminal)"
)

FORCE_HELP = (
    "answer the confirmation a destructive command asks at a terminal, so it does not "
    "ask (default: it asks)"
)

NO_INPUT_HELP = (
    "never prompt: a destructive command refuses rather than asking, and a secret is "
    "read from stdin or --from-env (default: prompt at a terminal)"
)

STAGE_HELP = ", ".join(PROVIDER_STAGES)

PROVIDER_SLOT_HELP = "the option it fills, such as api_key"

MCP_SLOT_HELP = "env.<KEY> or headers.<KEY>"

# The agent noun's one payload word. It is not an address and the line
# says what it is instead: the name the agent is to have, and the rule
# that decides whether it can have it.
RENAME_TO_HELP = (
    "the name to give it, which no agent, no remembered facts and no recorded "
    "conversations may already be under"
)

DEVICE_NAME_HELP = (
    "the name to give it, free-form and spoken aloud by the agent, which no other "
    "device may already answer to once case and spacing are folded together"
)

DEVICE_LOCATION_HELP = "where the board stands, free-form, as a person would say it"

DEVICE_SWAP_HELP = (
    "the MAC of the board this device is to answer at from now on, which no other "
    "device may already be bound to and nothing may already have been remembered about"
)

SESSION_HELP = "the session's uuid hex, as a listing prints it"

DEVICE_FILTER_HELP = "only the sessions of this board, by MAC (default: every board)"

LIMIT_HELP = "how many rows this page may hold (default: the API's own, 50)"

BEFORE_HELP = (
    "only the sessions that began before this UTC day, as YYYY-MM-DD (default: "
    "however far back the store goes)"
)

CONVERSATION_HELP = "the conversation's uuid hex, as a listing prints it"

AGENT_FILTER_HELP = "only the conversations of this agent, by name (default: every agent)"

SELECTED_SESSION_HELP = (
    "only this session, by its uuid hex (default: every session the other selectors "
    "leave)"
)

# The memory noun's address, one line per segment, in the order the
# routes' own paths carry them.
MEMORY_SCOPE_HELP = "which memory: agent, device or conversation"

MEMORY_OWNER_HELP = (
    "whose memory: the agent's name, the board's MAC, or the conversation's uuid hex"
)

MEMORY_ID_HELP = "the fact's number, as the listing prints it beside the fact"

MEMORY_ALL_HELP = "the whole of that memory rather than one fact of it"

MEMORY_CURSOR_HELP = (
    "carry on after this, as the previous page's own notice printed it (default: the "
    "first page)"
)

# What addresses one named aggregate, and what bounds the answer.
#
# The view is the positional because it is the address: `/metrics/{view}`
# is the route and the word is its last segment. The three flags are not
# an address at all, so they are flags, the way `--device` and `--limit`
# are on a session listing.
#
# None of the three says what a value may be beyond the shape it is
# written in. What a day has to be, how far apart two of them may sit
# and which breakdowns exist are the API's rules, said in the API's own
# fixed sentences, and a second vocabulary for them here would be a
# second sentence per refusal.
METRIC_VIEW_HELP = "which aggregate, by the word metric list prints for it"

METRIC_SINCE_HELP = (
    "the first UTC day of the window, as YYYY-MM-DD and inside it (default: the "
    "API's own, 30 days before the last)"
)

METRIC_UNTIL_HELP = (
    "the last UTC day of the window, as YYYY-MM-DD and inside it (default: the API's "
    "own, the server's current UTC day)"
)

METRIC_GROUP_HELP = (
    "how to break the rows down, from the set the API publishes (default: the API's "
    "own, the view's own dimensions and no further)"
)

METRIC_DEVICE_HELP = (
    "only the rows of this board, by MAC, which needs a --group that breaks the rows "
    "down by device (default: every board)"
)

# The two that follow `schema provider`. A provider type is addressed by
# its stage and its name together everywhere else in this command group,
# and its options are addressed the same way for the same reason: one
# type name lives in more than one stage.
SCHEMA_STAGE_HELP = "with TYPE, the options of one provider type: llm, asr, tts or vad"

SCHEMA_TYPE_HELP = "with STAGE, the provider type whose options to print"

# The first thing anybody reads of this grammar, so it is written in the
# vocabulary of the person reading it rather than in this repository's.
# "The domain half" is a real distinction here (the file half boots a
# server, the domain half is what it serves) and it is a distinction
# nobody has met yet at the moment they run `vinga` for the first time:
# a sentence that opens with it says what this command group is NOT
# before it has said what it is. What it is, is the thing they came to
# do.
DESCRIPTION = (
    "Configure a running vinga server: providers, MCP servers, agents, "
    "devices and their secrets. Commands go through the configuration API."
)

# The declared copy of each option, as one annotation apiece, so a
# command that takes them says so in two lines and cannot come to spell
# one of them differently from its siblings.
#
# `None` is the not-given value, and it is an answer rather than a
# sentinel of convenience: neither option can be typed as None, so the
# merge below reproduces argparse's `default=SUPPRESS` dance exactly. A
# sentinel object of this module's own would read back as its repr in
# the help, which is the one place these defaults are published.
ConfigOption = Annotated[str | None, typer.Option("--config", metavar="PATH", help=CONFIG_HELP)]

ApiUrlOption = Annotated[str | None, typer.Option("--api-url", metavar="URL", help=API_URL_HELP)]

# The two prompt-control options, and `bool | None` is the load-bearing
# part rather than a nicety. They ride `Globals` like the two above, so
# an absent copy at the command position must not overwrite what the
# root position said; an ordinary boolean default would arrive as False
# and make `vinga --no-input agent delete kids` prompt.
ForceOption = Annotated[bool | None, typer.Option("--force", help=FORCE_HELP)]

NoInputOption = Annotated[bool | None, typer.Option("--no-input", help=NO_INPUT_HELP)]

# The two ways a write's entity is given, declared once apiece for the
# same reason the three globals are: a `set` command says so in two
# lines and cannot come to spell one of them differently from its
# siblings. Neither is required on its own, because either satisfies the
# command; what refuses neither and both is `_written_entity`, which is
# the only place that can see the pair of them.
FileOption = Annotated[str, typer.Option("-f", "--file", metavar="PATH", help=FILE_HELP)]

# The same flag on the memory noun, with its own sentence: what it names
# there is not a fragment and there is no key=value form beside it, so
# the fragment's help would describe a command this one is not.
MEMORY_FILE_HELP = (
    "read the corrected fact from this file, or from - for standard input (default: "
    "standard input); never an argument, because a remembered fact is content"
)

MemoryFileOption = Annotated[
    str, typer.Option("-f", "--file", metavar="PATH", help=MEMORY_FILE_HELP)
]

PairsArgument = Annotated[
    list[str] | None, typer.Argument(metavar="KEY=VALUE", help=PAIRS_HELP)
]


@dataclass(frozen=True, kw_only=True)
class Globals:
    """The two options, as far as the positions so far have resolved
    them.

    The root callback builds the first answer and every position under
    it folds its own copies in, so a value given before the command
    survives a command that was not given one. That survival is the
    load-bearing half: without it `--config path show provider` would
    read the default file, because the command's own empty copy would
    overwrite what came before it.
    """

    config: str | None = None
    api_url: str | None = None
    force: bool | None = None
    no_input: bool | None = None

    def merged(
        self,
        *,
        config: str | None,
        api_url: str | None,
        force: bool | None = None,
        no_input: bool | None = None,
    ) -> "Globals":
        """The same options with one more position's copies folded in,
        each winning only where it was given.

        The two booleans fold on `is not None` for the reason the two
        strings fold on `is None`: what is being preserved is the
        distinction between "said false" and "said nothing", and a
        plain boolean has only one of those.
        """
        return Globals(
            config=self.config if config is None else config,
            api_url=self.api_url if api_url is None else api_url,
            force=self.force if force is None else force,
            no_input=self.no_input if no_input is None else no_input,
        )


@dataclass(frozen=True, kw_only=True)
class Command:
    """One command of the grammar."""

    # Where it sits: the words that name it, root first. One word is a
    # command of the group itself; anything longer is a command under
    # the noun path its leading words name, and every such path is a
    # key of `GROUPS`.
    words: tuple[str, ...]

    # Which entity kind it addresses, for the commands that cover more
    # than one. An explicit fact rather than a position in `words`: a
    # provider's secret rows are three words deep and their kind is the
    # first of them, while `device pending claim` is three words deep
    # and its kind is the device the first word names, so no positional
    # rule reads both correctly.
    kind: str = ""

    # What it does. An act is a request to the configuration API; a
    # tuple of them is a command whose one output is assembled from more
    # than one read, in the order they are written; the commands that
    # reach no API carry their own function instead.
    #
    # A tuple rather than a second row, because what an operator asked
    # for is one thing: `conversation show` prints a thread's header and
    # then its dialogue, and the API answers those as two resources
    # because one of them is paginated and the other is not.
    does: "Act | tuple[Act, ...] | Callable[[Invocation], None]"

    # What it prints before its first request, for the one command whose
    # answer starts with something no server can supply. `info` opens
    # with the banner and with the address this CLI is about to contact,
    # and a renderer cannot say either: an act's renderer is handed the
    # answer and nothing else, which is what keeps a rendering a function
    # of what came back. So the fact about the invocation is printed by
    # the row that knows it, before any act runs, rather than smuggled
    # into an act that would then be two things.
    # Given what this invocation resolved as well as its arguments,
    # because what `info` opens with is where its requests are about to
    # go. A row with no acts resolves nothing and therefore opens with
    # nothing: there would be no address to name and no token to demand.
    opens: "Callable[[Invocation, Reached], None] | None" = None

    # Which of the acts above one invocation runs, for the rows where an
    # option decides. The memory reads and writes are the ones: which
    # scope was addressed decides which route is asked.
    #
    # A hook from the invocation rather than a tuple cut down after the
    # fact, because the two things that vary are not the same thing.
    # What a row CAN reach is what `acts()` answers and what the
    # contract check enumerates coverage from, and it does not change
    # with a flag. What one invocation ran is this, and it is also
    # where the rendering is chosen, since an act's renderer is handed
    # the answer and nothing else.
    selects: "Callable[[Invocation], tuple[Act, ...]] | None" = None

    # How its arguments are declared, which is a function Typer reads a
    # signature off. One per argument shape rather than one per command,
    # and the row is handed to it, so what a command performs is read
    # off the row rather than closed over a second time.
    declare: "Callable[[Command], Callable[..., None]]"

    # What the command listing says about it, which is also the heading
    # of its own help page.
    help: str

    # What follows that page, for the commands that take a fragment: the
    # fields the fragment may carry, rendered from the models.
    epilog: str | None = None

    # Whether this verb's effect cannot be undone by running another
    # command with information the operator still has. A delete destroys
    # the body; a `set` does not, as long as an `export` exists, which is
    # why replacement writes and rebindings are not here. A fact on the
    # registration rather than a list beside it, so the confirmation is
    # driven by the same table everything else about a command is.
    destroys: bool = False

    def acts(self) -> "tuple[Act, ...]":
        """The requests this command makes, in the order it makes them,
        and none for a command that reaches no API.

        Read off the row rather than reconstructed by whoever asks: the
        contract check holds every act against the committed document
        and would otherwise carry a second copy of the rule below, which
        is exactly how a command that grew a second request comes to be
        a request nobody compared.
        """
        if isinstance(self.does, Act):
            return (self.does,)
        if isinstance(self.does, tuple):
            return self.does
        return ()

    def performs(self, args: Invocation) -> "tuple[Act, ...]":
        """The acts this invocation runs, which for every row but one
        are the acts the row has: see `selects`."""
        if self.selects is None:
            return self.acts()
        return self.selects(args)

    def perform(self, args: Invocation) -> None:
        """What this command does, once its arguments are in hand."""
        if self.destroys:
            _permitted_to_destroy(args)
        if self.acts():
            # Once, in front of every act and of the opener, so that
            # what this command says about where it is reaching is true
            # of every request it then makes (`Reached`).
            reached = _reached(args)
            if self.opens is not None:
                self.opens(args, reached)
            _performed(args, self.performs(args), reached)
            return
        # No acts is the third arm of `does`: a command that reaches no
        # API, carrying its own function.
        self.does(args)


class _Verbatim(TyperCommand):
    """Every leaf of this grammar: one command, about to run.

    Two things it does that Click's own command class does not, and they
    are unrelated except in being true of every command here.

    Its epilog is printed as it was laid out. Click rewraps an epilog
    paragraph by paragraph, which would reflow the field listing under a
    `set` command into prose. That listing is generated already wrapped,
    at a width narrower than a terminal, for exactly the reason
    argparse's raw formatter was asked for before this: a line that
    wraps on its own is worse than one wrapped on purpose.

    And the `.env` file is read here, which is the last moment before a
    command runs and the first moment it is known that one will. Every
    command of this group needs the environment (the API address, the
    token, the config path and the master key are all read from it) and
    no invocation that runs no command does: a bare `vinga` is answered
    with a help page, and `--help` and `--version` are answered without
    one, so none of the three may be turned into a sentence about a
    `.env` the reader may not have written. Reading it at the boundary's
    mouth made that failure the answer to every invocation, including
    the ones whose whole purpose is to work when nothing else does.

    It is read on the way in rather than by each command body for the
    reason the boundary exists: forty-odd bodies reading it is forty-odd
    chances to forget, and the environment has to be loaded before the
    first thing looks at it whichever command that is.

    And the floor under the libraries that narrate somebody else's bytes
    is applied here, in the same breath and for the same reason. It was
    `vinga_server.main`'s alone, which every `vinga-server config`
    invocation passes through and no `vinga` invocation does: the
    console script is its own entry point and reaches `cli.main`
    directly. That gap was harmless while every command of this grammar
    was an HTTP request, since the request path takes the libraries down
    itself around the call (`quieted`, `REQUEST_LOGGERS`). `check` is
    what made it matter: it opens and migrates a database, and a
    SQLAlchemy engine whose logger is enabled for INFO echoes every
    statement with the parameters bound to it, which for this store is
    the stored configuration. So the floor is applied where a command is
    about to run, whichever word started it, and the two spellings are
    once again the same program.

    Here rather than beside the boot read, which is the shape that would
    have said this is one command's problem: any command that grows a
    database open or a socket inherits the floor by being a command. And
    here rather than at the boundary's mouth, for the reason the `.env`
    read moved: an invocation that runs no command touches no library.
    The call is idempotent and never lowers a level, so applying it on
    both entry points costs an installation nothing.
    """

    def invoke(self, ctx: Any) -> Any:
        load_environment_file()
        quiet_vendor_libraries()
        return super().invoke(ctx)

    def format_epilog(self, ctx: Any, formatter: Any) -> None:
        if not self.epilog:
            return
        formatter.write_paragraph()
        for line in self.epilog.splitlines():
            formatter.write(f"{line}\n")


def _version(shown: bool) -> None:
    """The installed version, printed and done.

    Eager, so it is answered while the command line is still being
    parsed and does not need a command word after it. It leaves the way
    `--help` leaves, through the exit the boundary carries out of its
    handler, because asking is not failing.

    Rarely reached at all, since `main` answers the same question in
    front of the parse and this one is what answers it if that
    recognizer ever stops recognizing a spelling. Both print through
    `_print_version` rather than one of them formatting the line again,
    and `test_the_version_is_the_same_bytes_through_either_spelling`
    holds them to it. Neither needs the environment: no `.env` is read
    until a command is about to run.
    """
    if not shown:
        return
    _print_version()
    raise typer.Exit(0)


def _print_version() -> None:
    print(f"{DISTRIBUTION} {installed_version()}")


def installed_version() -> str:
    """What the packaging system says is installed under this name.

    Answered rather than raised for a tree nothing was installed from,
    which is a real state a contributor can be in and not a failure of
    the command they asked for.
    """
    try:
        return metadata.version(DISTRIBUTION)
    except metadata.PackageNotFoundError:
        return VERSION_UNKNOWN


VersionOption = Annotated[
    bool,
    typer.Option(
        "--version",
        is_eager=True,
        callback=_version,
        help="print the installed version and exit",
    ),
]


def _root(
    context: typer.Context,
    config: ConfigOption = None,
    api_url: ApiUrlOption = None,
    force: ForceOption = None,
    no_input: NoInputOption = None,
    version: VersionOption = False,
) -> None:
    """The global options in the position before the command word.

    Their answer is put on the context rather than passed, because the
    positions under this one add to it: a group callback folds its own
    copies in and a command folds its own in after that, and each of
    them reads one object.
    """
    context.obj = Globals(
        config=config, api_url=api_url, force=force, no_input=no_input
    )


def _resolved(context: typer.Context) -> Globals:
    """What the positions above this one made of the two options.

    Answered as an empty `Globals` when there is nothing there, which is
    what a command reached without the root callback having run would
    see. Nothing in this grammar reaches one, and defaulting is cheaper
    than a branch every command would have to carry.
    """
    resolved = context.obj
    return resolved if isinstance(resolved, Globals) else Globals()


def _invocation(
    row: Command,
    context: typer.Context,
    config: str | None = None,
    api_url: str | None = None,
    force: bool | None = None,
    no_input: bool | None = None,
    **addressed: Any,
) -> Invocation:
    """One command's arguments, with the two global options resolved.

    The two come in as this command's own copies, which is one of the
    positions they are accepted in; what the positions above it made of
    them is on the context, and the merge is what lets a value given
    before the command survive a command that was not given one.
    """
    resolved = _resolved(context).merged(
        config=config, api_url=api_url, force=force, no_input=no_input
    )
    return Invocation(
        config=resolved.config,
        api_url=resolved.api_url,
        force=bool(resolved.force),
        no_input=bool(resolved.no_input),
        # Which kind a command that covers several of them was asked
        # about, declared on the row: see `Command.kind`.
        kind=row.kind,
        **addressed,
    )


# How each shape of command declares its arguments
#
# Typer reads a signature, so an argument shape is a function and a
# command is one of these applied to its row. There are fewer of them
# than there are commands because the grammar repeats itself: five kinds
# addressed by a name, one addressed by a stage and a name, two settings
# addressed by a MAC and by six digits on a screen.


def _plain(row: Command) -> Callable[..., None]:
    """A command that addresses nothing: the reads of the whole
    configuration and of the running server, the apply, and the
    singleton, which is the one entity there is only one of."""

    def run(
        context: typer.Context,
        config: ConfigOption = None,
        api_url: ApiUrlOption = None,
        force: ForceOption = None,
        no_input: NoInputOption = None,
    ) -> None:
        row.perform(_invocation(row, context, config, api_url, force, no_input))

    return run


def _named(row: Command) -> Callable[..., None]:
    """A command addressing one entry by its name."""

    def run(
        context: typer.Context,
        name: Annotated[str, typer.Argument(metavar="NAME")],
        config: ConfigOption = None,
        api_url: ApiUrlOption = None,
        force: ForceOption = None,
        no_input: NoInputOption = None,
    ) -> None:
        row.perform(_invocation(row, context, config, api_url, force, no_input, name=name))

    return run


def _renamed_to(row: Command) -> Callable[..., None]:
    """A command addressing one entry by its name, with the name it is
    to be given behind it.

    The address first and the payload second, which is the route's own
    order: `/agents/{name}/rename` addresses the agent by the name it
    has, and the name it is to have travels in the body. One payload
    word rather than a group, so the line reads left to right as the
    act does.
    """

    def run(
        context: typer.Context,
        name: Annotated[str, typer.Argument(metavar="NAME")],
        to: Annotated[str, typer.Argument(metavar="NEW", help=RENAME_TO_HELP)],
        config: ConfigOption = None,
        api_url: ApiUrlOption = None,
        force: ForceOption = None,
        no_input: NoInputOption = None,
    ) -> None:
        row.perform(
            _invocation(row, context, config, api_url, force, no_input, name=name, to=to)
        )

    return run


def _staged(row: Command) -> Callable[..., None]:
    """A command addressing one provider, which takes two words because
    two stages may hold the same name."""

    def run(
        context: typer.Context,
        stage: Annotated[str, typer.Argument(metavar="STAGE", help=STAGE_HELP)],
        name: Annotated[str, typer.Argument(metavar="NAME")],
        config: ConfigOption = None,
        api_url: ApiUrlOption = None,
        force: ForceOption = None,
        no_input: NoInputOption = None,
    ) -> None:
        row.perform(
            _invocation(
                row, context, config, api_url, force, no_input, stage=stage, name=name
            )
        )

    return run


def _by_mac(row: Command) -> Callable[..., None]:
    """A command addressing one device by the address it connects
    with."""

    def run(
        context: typer.Context,
        mac: Annotated[str, typer.Argument(metavar="MAC")],
        config: ConfigOption = None,
        api_url: ApiUrlOption = None,
        force: ForceOption = None,
        no_input: NoInputOption = None,
    ) -> None:
        row.perform(_invocation(row, context, config, api_url, force, no_input, mac=mac))

    return run


def _written(row: Command) -> Callable[..., None]:
    """The singleton's write: an entity and nothing to address it
    with."""

    def run(
        context: typer.Context,
        pairs: PairsArgument = None,
        file: FileOption = "",
        config: ConfigOption = None,
        api_url: ApiUrlOption = None,
        force: ForceOption = None,
        no_input: NoInputOption = None,
    ) -> None:
        row.perform(
            _invocation(
                row, context, config, api_url, force, no_input,
                file=file, pairs=_given(pairs),
            )
        )

    return run


def _named_write(row: Command) -> Callable[..., None]:
    """One named entity's write, from a fragment or from inline
    fields."""

    def run(
        context: typer.Context,
        name: Annotated[str, typer.Argument(metavar="NAME")],
        pairs: PairsArgument = None,
        file: FileOption = "",
        config: ConfigOption = None,
        api_url: ApiUrlOption = None,
        force: ForceOption = None,
        no_input: NoInputOption = None,
    ) -> None:
        row.perform(
            _invocation(
                row, context, config, api_url, force, no_input,
                name=name, file=file, pairs=_given(pairs),
            )
        )

    return run


def _staged_write(row: Command) -> Callable[..., None]:
    """One provider's write, from a fragment or from inline fields."""

    def run(
        context: typer.Context,
        stage: Annotated[str, typer.Argument(metavar="STAGE", help=STAGE_HELP)],
        name: Annotated[str, typer.Argument(metavar="NAME")],
        pairs: PairsArgument = None,
        file: FileOption = "",
        config: ConfigOption = None,
        api_url: ApiUrlOption = None,
        force: ForceOption = None,
        no_input: NoInputOption = None,
    ) -> None:
        row.perform(
            _invocation(
                row, context, config, api_url, force, no_input,
                stage=stage, name=name, file=file, pairs=_given(pairs),
            )
        )

    return run


def _imported_document(row: Command) -> Callable[..., None]:
    """The whole configuration in one file. No inline fields here: a
    document is several entities and the sections around them, which is
    what a file is for."""

    def run(
        context: typer.Context,
        file: Annotated[
            str, typer.Option("-f", "--file", metavar="PATH", help=DOCUMENT_HELP)
        ],
        config: ConfigOption = None,
        api_url: ApiUrlOption = None,
        force: ForceOption = None,
        no_input: NoInputOption = None,
    ) -> None:
        row.perform(
            _invocation(row, context, config, api_url, force, no_input, file=file)
        )

    return run


def _given(pairs: list[str] | None) -> tuple[str, ...]:
    """A variadic argument as the seam holds it. Click answers an
    absent one with None or with an empty tuple depending on the
    version, and the seam's field is one thing: the pairs that were
    written."""
    return tuple(pairs or ())


def _by_session(row: Command) -> Callable[..., None]:
    """A command addressing one recorded session by its id."""

    def run(
        context: typer.Context,
        session: Annotated[str, typer.Argument(metavar="SESSION", help=SESSION_HELP)],
        config: ConfigOption = None,
        api_url: ApiUrlOption = None,
        force: ForceOption = None,
        no_input: NoInputOption = None,
    ) -> None:
        row.perform(
            _invocation(row, context, config, api_url, force, no_input, session=session)
        )

    return run


def _filtered_sessions(row: Command) -> Callable[..., None]:
    """The session listing, narrowed by a board and bounded by a count.

    Both are flags rather than positionals, because neither addresses a
    session: one says which board's sessions to show and the other how
    many. No cursor flag, deliberately: one invocation prints one page,
    and walking the whole record backwards is what the API is for.
    """

    def run(
        context: typer.Context,
        device: Annotated[
            str | None, typer.Option("--device", metavar="MAC", help=DEVICE_FILTER_HELP)
        ] = None,
        limit: Annotated[
            str | None, typer.Option("--limit", metavar="N", help=LIMIT_HELP)
        ] = None,
        config: ConfigOption = None,
        api_url: ApiUrlOption = None,
        force: ForceOption = None,
        no_input: NoInputOption = None,
    ) -> None:
        row.perform(
            _invocation(
                row,
                context,
                config,
                api_url,
                force,
                no_input,
                # Passed through rather than defaulted, because absent
                # and explicitly empty are different questions here:
                # `--device ''` travels and meets the API's own MAC
                # refusal instead of quietly widening to every board.
                mac=device,
                limit=limit or "",
            )
        )

    return run


def _over_a_window(row: Command) -> Callable[..., None]:
    """One named aggregate, over a window of whole UTC days.

    The view is a positional because it is the address the route is
    written in, and it leads for the reason every address here leads.
    The four that follow are flags because none of them addresses a
    view: two say which days to answer about, one says how to break the
    rows down and one narrows the breakdown to a board, which is what
    `--device` and `--limit` are to a session listing.
    """

    def run(
        context: typer.Context,
        view: Annotated[str, typer.Argument(metavar="VIEW", help=METRIC_VIEW_HELP)],
        since: Annotated[
            str | None, typer.Option("--since", metavar="DAY", help=METRIC_SINCE_HELP)
        ] = None,
        until: Annotated[
            str | None, typer.Option("--until", metavar="DAY", help=METRIC_UNTIL_HELP)
        ] = None,
        group: Annotated[
            str | None, typer.Option("--group", metavar="HOW", help=METRIC_GROUP_HELP)
        ] = None,
        device: Annotated[
            str | None, typer.Option("--device", metavar="MAC", help=METRIC_DEVICE_HELP)
        ] = None,
        config: ConfigOption = None,
        api_url: ApiUrlOption = None,
        force: ForceOption = None,
        no_input: NoInputOption = None,
    ) -> None:
        row.perform(
            _invocation(
                row,
                context,
                config,
                api_url,
                force,
                no_input,
                view=view,
                since=since or "",
                until=until or "",
                group=group or "",
                # Passed through rather than defaulted, because absent
                # and explicitly empty are different questions here:
                # `--device ''` travels and meets the API's own MAC
                # refusal instead of quietly widening to every board.
                mac=device,
            )
        )

    return run


def _tailed(row: Command) -> Callable[..., None]:
    """The event tail: three filters and the one option that says when
    it stops.

    Every one of them a flag, because none of them addresses anything: a
    tail with no filters is the whole server's traffic, which is the
    reading it is opened for most often, and `--follow` is about this
    invocation rather than about what is being asked for.

    The three filters are the query's own words, so what an operator
    types and what the API parses are one vocabulary. What each may be
    is the API's rule and its refusal, said there and not restated here.
    """

    def run(
        context: typer.Context,
        device: Annotated[
            str | None, typer.Option("--device", metavar="MAC", help=EVENTS_DEVICE_HELP)
        ] = None,
        session: Annotated[
            str | None, typer.Option("--session", metavar="ID", help=EVENTS_SESSION_HELP)
        ] = None,
        level: Annotated[
            str | None, typer.Option("--level", metavar="LEVEL", help=EVENTS_LEVEL_HELP)
        ] = None,
        follow: Annotated[bool, typer.Option("--follow", help=FOLLOW_HELP)] = False,
        config: ConfigOption = None,
        api_url: ApiUrlOption = None,
        force: ForceOption = None,
        no_input: NoInputOption = None,
    ) -> None:
        row.perform(
            _invocation(
                row,
                context,
                config,
                api_url,
                force,
                no_input,
                # Passed through rather than defaulted, because absent
                # and explicitly empty are different questions here:
                # `--device ''` travels and meets the API's own MAC
                # refusal instead of quietly widening a board's traffic
                # to the whole server's.
                mac=device,
                session=session or "",
                level=level or "",
                follow=follow,
            )
        )

    return run


def _selected_sessions(row: Command) -> Callable[..., None]:
    """The purge's three selectors, every one of them a flag.

    A selector is not an address: a purge names a set, and the set is
    narrowed by every selector that was written. All three are optional
    here and at least one is required, which is the API's rule and its
    sentence rather than a second copy of it in the grammar.
    """

    def run(
        context: typer.Context,
        session: Annotated[
            str | None,
            typer.Option("--session", metavar="ID", help=SELECTED_SESSION_HELP),
        ] = None,
        device: Annotated[
            str | None, typer.Option("--device", metavar="MAC", help=DEVICE_FILTER_HELP)
        ] = None,
        before: Annotated[
            str | None, typer.Option("--before", metavar="YYYY-MM-DD", help=BEFORE_HELP)
        ] = None,
        config: ConfigOption = None,
        api_url: ApiUrlOption = None,
        force: ForceOption = None,
        no_input: NoInputOption = None,
    ) -> None:
        row.perform(
            _invocation(
                row,
                context,
                config,
                api_url,
                force,
                no_input,
                session=session or "",
                # Passed through rather than defaulted, for the reason
                # `_purge_selectors` states: an empty value that vanished
                # here would leave `--before` alone with the set and
                # widen an erasure to every board.
                mac=device,
                before=before or "",
            )
        )

    return run


def _by_conversation(row: Command) -> Callable[..., None]:
    """A command addressing one recorded thread by its id."""

    def run(
        context: typer.Context,
        conversation: Annotated[
            str, typer.Argument(metavar="CONVERSATION", help=CONVERSATION_HELP)
        ],
        config: ConfigOption = None,
        api_url: ApiUrlOption = None,
        force: ForceOption = None,
        no_input: NoInputOption = None,
    ) -> None:
        row.perform(
            _invocation(
                row, context, config, api_url, force, no_input, conversation=conversation
            )
        )

    return run


def _filtered_conversations(row: Command) -> Callable[..., None]:
    """The thread listing, narrowed by an agent and bounded by a count.

    `--agent` is a flag and not an address for the reason `--device` is
    one next door: it says whose threads to show rather than naming one
    thread, which is how story 14 of #190 is supplied.
    """

    def run(
        context: typer.Context,
        agent: Annotated[
            str | None, typer.Option("--agent", metavar="NAME", help=AGENT_FILTER_HELP)
        ] = None,
        limit: Annotated[
            str | None, typer.Option("--limit", metavar="N", help=LIMIT_HELP)
        ] = None,
        config: ConfigOption = None,
        api_url: ApiUrlOption = None,
        force: ForceOption = None,
        no_input: NoInputOption = None,
    ) -> None:
        row.perform(
            _invocation(
                row,
                context,
                config,
                api_url,
                force,
                no_input,
                name=agent or "",
                limit=limit or "",
            )
        )

    return run


def _memory_read(row: Command) -> Callable[..., None]:
    """A memory listing: the scope, and the owner where one was named.

    Two positionals in the URL's own order, which is what identity
    addressing means here: `/memory/agents/{name}/facts` is scope then
    owner, so the command is too. The owner is optional because its
    absence is a different question one level up, which the row answers
    by performing a different act.

    The owner is routed to the field whose name is its own path
    parameter, so each act reads what it addresses rather than a shared
    word that would have to be translated twice.
    """

    def run(
        context: typer.Context,
        scope: Annotated[str, typer.Argument(metavar="SCOPE", help=MEMORY_SCOPE_HELP)],
        owner: Annotated[
            str | None, typer.Argument(metavar="OWNER", help=MEMORY_OWNER_HELP)
        ] = None,
        limit: Annotated[
            str | None, typer.Option("--limit", metavar="N", help=LIMIT_HELP)
        ] = None,
        cursor: Annotated[
            str | None, typer.Option("--cursor", metavar="AFTER", help=MEMORY_CURSOR_HELP)
        ] = None,
        config: ConfigOption = None,
        api_url: ApiUrlOption = None,
        force: ForceOption = None,
        no_input: NoInputOption = None,
    ) -> None:
        row.perform(
            _invocation(
                row, context, config, api_url, force, no_input,
                scope=scope, limit=limit or "", cursor=cursor or "",
                **_addressing(scope, owner),
            )
        )

    return run


def _memory_write(row: Command) -> Callable[..., None]:
    """A correction: the scope, the owner and the fact's number, and the
    text from a file or from standard input.

    Three address segments, which is the guide's ceiling and exactly
    what the route's own path has. The text is not among them and is not
    an option's value either: `-f` names where to read it, and nothing
    of the fact itself ever reaches argv.
    """

    def run(
        context: typer.Context,
        scope: Annotated[str, typer.Argument(metavar="SCOPE", help=MEMORY_SCOPE_HELP)],
        owner: Annotated[str, typer.Argument(metavar="OWNER", help=MEMORY_OWNER_HELP)],
        fact: Annotated[str, typer.Argument(metavar="ID", help=MEMORY_ID_HELP)],
        file: MemoryFileOption = "",
        config: ConfigOption = None,
        api_url: ApiUrlOption = None,
        force: ForceOption = None,
        no_input: NoInputOption = None,
    ) -> None:
        row.perform(
            _invocation(
                row, context, config, api_url, force, no_input,
                scope=scope, fact=fact, file=file, **_addressing(scope, owner),
            )
        )

    return run


def _memory_deletion_arguments(row: Command) -> Callable[..., None]:
    """A deletion: the scope, the owner, and either one fact's number or
    `--all`.

    The number is optional and `--all` is the other way to say what to
    delete, never the absence of one: a mistyped number that meant
    everything is the mistake this shape exists to make impossible.
    """

    def run(
        context: typer.Context,
        scope: Annotated[str, typer.Argument(metavar="SCOPE", help=MEMORY_SCOPE_HELP)],
        owner: Annotated[str, typer.Argument(metavar="OWNER", help=MEMORY_OWNER_HELP)],
        fact: Annotated[
            str | None, typer.Argument(metavar="ID", help=MEMORY_ID_HELP)
        ] = None,
        all_of_it: Annotated[bool, typer.Option("--all", help=MEMORY_ALL_HELP)] = False,
        config: ConfigOption = None,
        api_url: ApiUrlOption = None,
        force: ForceOption = None,
        no_input: NoInputOption = None,
    ) -> None:
        row.perform(
            _invocation(
                row, context, config, api_url, force, no_input,
                scope=scope, fact=fact or "", all_of_it=all_of_it,
                **_addressing(scope, owner),
            )
        )

    return run


def _addressing(scope: str, owner: str | None) -> dict[str, str]:
    """The owner positional, under the name the route's own path
    parameter uses.

    Read here rather than carried as one word, because the three paths
    name three different parameters and each act reads the one it
    addresses: an agent is `{name}`, a board is `{mac}` and a thread is
    `{conversation}`. A scope this grammar does not have fills nothing
    and is refused by the row, which is where every other refusal about
    the scope is decided.
    """
    field = {"agent": "name", "device": "mac", "conversation": "conversation"}.get(scope)
    return {} if field is None or not owner else {field: owner}


def _provider_secret(row: Command) -> Callable[..., None]:
    """Storing a credential on one provider. The value is never here: it
    is read from stdin or from the variable `--from-env` names."""

    def run(
        context: typer.Context,
        stage: Annotated[str, typer.Argument(metavar="STAGE", help=STAGE_HELP)],
        name: Annotated[str, typer.Argument(metavar="NAME")],
        slot: Annotated[str, typer.Argument(metavar="SLOT", help=PROVIDER_SLOT_HELP)],
        from_env: Annotated[
            str | None, typer.Option("--from-env", metavar="VAR", help=FROM_ENV_HELP)
        ] = None,
        config: ConfigOption = None,
        api_url: ApiUrlOption = None,
        force: ForceOption = None,
        no_input: NoInputOption = None,
    ) -> None:
        row.perform(
            _invocation(
                row, context, config, api_url, force, no_input,
                stage=stage, name=name, slot=slot, from_env=from_env,
            )
        )

    return run


def _mcp_secret(row: Command) -> Callable[..., None]:
    """The same, on one MCP server."""

    def run(
        context: typer.Context,
        name: Annotated[str, typer.Argument(metavar="NAME")],
        slot: Annotated[str, typer.Argument(metavar="SLOT", help=MCP_SLOT_HELP)],
        from_env: Annotated[
            str | None, typer.Option("--from-env", metavar="VAR", help=FROM_ENV_HELP)
        ] = None,
        config: ConfigOption = None,
        api_url: ApiUrlOption = None,
        force: ForceOption = None,
        no_input: NoInputOption = None,
    ) -> None:
        row.perform(
            _invocation(
                row, context, config, api_url, force, no_input,
                name=name, slot=slot, from_env=from_env,
            )
        )

    return run


def _provider_slot(row: Command) -> Callable[..., None]:
    """Clearing a stored credential from one provider."""

    def run(
        context: typer.Context,
        stage: Annotated[str, typer.Argument(metavar="STAGE", help=STAGE_HELP)],
        name: Annotated[str, typer.Argument(metavar="NAME")],
        slot: Annotated[str, typer.Argument(metavar="SLOT", help=PROVIDER_SLOT_HELP)],
        config: ConfigOption = None,
        api_url: ApiUrlOption = None,
        force: ForceOption = None,
        no_input: NoInputOption = None,
    ) -> None:
        row.perform(
            _invocation(
                row, context, config, api_url, force, no_input,
                stage=stage, name=name, slot=slot,
            )
        )

    return run


def _mcp_slot(row: Command) -> Callable[..., None]:
    """The same, on one MCP server."""

    def run(
        context: typer.Context,
        name: Annotated[str, typer.Argument(metavar="NAME")],
        slot: Annotated[str, typer.Argument(metavar="SLOT", help=MCP_SLOT_HELP)],
        config: ConfigOption = None,
        api_url: ApiUrlOption = None,
        force: ForceOption = None,
        no_input: NoInputOption = None,
    ) -> None:
        row.perform(
            _invocation(
                row, context, config, api_url, force, no_input, name=name, slot=slot
            )
        )

    return run


def _bound_by_mac(row: Command) -> Callable[..., None]:
    """Binding a board whose address is already known, to one agent or
    several."""

    def run(
        context: typer.Context,
        mac: Annotated[str, typer.Argument(metavar="MAC")],
        agents: Annotated[list[str], typer.Argument(metavar="AGENT")],
        config: ConfigOption = None,
        api_url: ApiUrlOption = None,
        force: ForceOption = None,
        no_input: NoInputOption = None,
    ) -> None:
        row.perform(
            _invocation(
                row, context, config, api_url, force, no_input,
                mac=mac, agents=tuple(agents),
            )
        )

    return run


def _bound_by_code(row: Command) -> Callable[..., None]:
    """The same binding, addressed by the six digits on a board's screen
    instead of by a MAC nobody has had to find."""

    def run(
        context: typer.Context,
        code: Annotated[
            str,
            typer.Argument(
                metavar="CODE", help="the six digits the device is showing and speaking"
            ),
        ],
        agents: Annotated[list[str], typer.Argument(metavar="AGENT")],
        config: ConfigOption = None,
        api_url: ApiUrlOption = None,
        force: ForceOption = None,
        no_input: NoInputOption = None,
    ) -> None:
        row.perform(
            _invocation(
                row, context, config, api_url, force, no_input,
                code=code, agents=tuple(agents),
            )
        )

    return run


def _device_renamed_to(row: Command) -> Callable[..., None]:
    """One device addressed by its MAC, with the name it is to be given
    behind it.

    The address first and the payload second, which is the route's own
    order: `/devices/{mac}/rename` addresses the board by the MAC it
    connects with, and the name it is to have travels in the body.
    """

    def run(
        context: typer.Context,
        mac: Annotated[str, typer.Argument(metavar="MAC")],
        to: Annotated[str, typer.Argument(metavar="NAME", help=DEVICE_NAME_HELP)],
        config: ConfigOption = None,
        api_url: ApiUrlOption = None,
        force: ForceOption = None,
        no_input: NoInputOption = None,
    ) -> None:
        row.perform(
            _invocation(row, context, config, api_url, force, no_input, mac=mac, to=to)
        )

    return run


def _device_replaced_by(row: Command) -> Callable[..., None]:
    """One device addressed by the MAC it answers at now, with the MAC it
    is to answer at behind it.

    The address first and the payload second, the route's own order
    again: `/devices/{mac}/replace` addresses the record by the board it
    is losing, and the board it is gaining travels in the body. Both
    positionals are MACs, which is why the second one's metavar says so
    rather than repeating the first's.
    """

    def run(
        context: typer.Context,
        mac: Annotated[str, typer.Argument(metavar="MAC")],
        to: Annotated[str, typer.Argument(metavar="NEW_MAC", help=DEVICE_SWAP_HELP)],
        config: ConfigOption = None,
        api_url: ApiUrlOption = None,
        force: ForceOption = None,
        no_input: NoInputOption = None,
    ) -> None:
        row.perform(
            _invocation(row, context, config, api_url, force, no_input, mac=mac, to=to)
        )

    return run


def _device_located_at(row: Command) -> Callable[..., None]:
    """The same shape for the other half of the record: the board's MAC,
    and where it stands behind it."""

    def run(
        context: typer.Context,
        mac: Annotated[str, typer.Argument(metavar="MAC")],
        location: Annotated[
            str, typer.Argument(metavar="LOCATION", help=DEVICE_LOCATION_HELP)
        ],
        config: ConfigOption = None,
        api_url: ApiUrlOption = None,
        force: ForceOption = None,
        no_input: NoInputOption = None,
    ) -> None:
        row.perform(
            _invocation(
                row, context, config, api_url, force, no_input, mac=mac, location=location
            )
        )

    return run


def _simulated_board(row: Command) -> Callable[..., None]:
    """The simulator's verbs: one URL, and two options about the board
    it pretends to be.

    One positional and everything heterogeneous a flag, which is the
    homogeneity rule. The URL is required rather than derived, and the
    help says where to get one: deriving it would mean reading
    `onboarding.origin`, which is the import that gates `ota-url` on the
    server half, and a headline command that refused on a client install
    would be the one thing this must not be.

    `--config` and `--api-url` apply because `--claim` reaches the
    configuration API. `--force` and `--no-input` are offered because
    they are offered everywhere, and are inert here: neither verb
    prompts and neither destroys.
    """

    def run(
        context: typer.Context,
        endpoint: Annotated[str, typer.Argument(metavar="URL", help=ENDPOINT_HELP)],
        mac: Annotated[
            str,
            # The default is in the help sentence with the reason it was
            # chosen, so Click's own copy of it would be the same string
            # twice on one page.
            typer.Option("--mac", metavar="MAC", help=MAC_HELP, show_default=False),
        ] = board.DEFAULT_MAC,
        claim: Annotated[
            list[str] | None, typer.Option("--claim", metavar="AGENT", help=CLAIM_HELP)
        ] = None,
        config: ConfigOption = None,
        api_url: ApiUrlOption = None,
        force: ForceOption = None,
        no_input: NoInputOption = None,
    ) -> None:
        row.perform(
            _invocation(
                row, context, config, api_url, force, no_input,
                endpoint=endpoint, mac=mac, agents=_given(claim),
            )
        )

    return run


def _from_the_file_half(row: Command) -> Callable[..., None]:
    """The two commands that take `--config` and nothing else.

    Neither contacts a server, so neither has anything to do with
    `--api-url` or the bearer token, and offering the flags would say
    they had. `ota-url` contacts nothing at all; what answers on the URL
    it prints is `vinga-server doctor`, a command of its own since #244.
    `check` reaches the database the file half names, which is what a
    boot reaches and is still not the API.
    """

    def run(context: typer.Context, config: ConfigOption = None) -> None:
        row.perform(_invocation(row, context, config))

    return run


def _of_an_entity(row: Command) -> Callable[..., None]:
    """The schema command, which names one entity kind or none, and one
    provider type's options when a stage and a type follow it.

    Three positionals rather than a flag, because they read as what they
    are: `schema provider asr faster_whisper` is the same
    stage-then-name order every provider command is addressed in.
    """

    def run(
        context: typer.Context,
        entity: Annotated[
            str | None,
            typer.Argument(
                metavar="ENTITY", help=", ".join(docgen.entity_names()) + " (default: domain)"
            ),
        ] = None,
        stage: Annotated[
            str,
            typer.Argument(metavar="STAGE", help=SCHEMA_STAGE_HELP),
        ] = "",
        type_name: Annotated[
            str,
            typer.Argument(metavar="TYPE", help=SCHEMA_TYPE_HELP),
        ] = "",
    ) -> None:
        row.perform(_invocation(row, context, entity=entity, stage=stage, type_name=type_name))

    return run


def _rendered(row: Command) -> Callable[..., None]:
    """The two documents rendered from the routes and from the command
    tree, which take no arguments at all."""

    def run(context: typer.Context) -> None:
        row.perform(_invocation(row, context))

    return run


def _of_a_half(row: Command) -> Callable[..., None]:
    """The markdown reference, which names one half of the configuration
    or neither.

    One optional positional, in the `_of_an_entity` shape and for the
    same reason: the act is one act, and what follows the verb says which
    document of it. Scoped to this row alone, so `openapi` and
    `cli-reference` keep taking no arguments at all; each of those renders
    the one document it is about, and a selector on them would name
    nothing.

    The choices are not listed here. The help lists the registry's keys
    and the default is the registry's first row, so a third half would be
    a row there rather than an edit here, and an unnamed one is refused by
    `render` with the same tuple's words.
    """

    def run(
        context: typer.Context,
        half: Annotated[
            str,
            typer.Argument(
                metavar="HALF",
                help=", ".join(server_reference.half_names())
                + f" (default: {server_reference.DEFAULT_HALF})",
                # The default is in the help sentence beside the names it
                # is one of, so Click's own copy of it would be the same
                # word twice on one line. The `--mac` option is the
                # precedent, and `schema`'s ENTITY reads this way because
                # its default is None.
                show_default=False,
            ),
        ] = server_reference.DEFAULT_HALF,
    ) -> None:
        row.perform(_invocation(row, context, half=half))

    return run


# What a command listing says about one entity kind's command: the verb,
# and where in the configuration document the kind lives. Read off the
# descriptor, so a kind cannot come to be described one way in the help
# and another way in the generated reference.


def _about(verb: str, kind: entities.EntityDescriptor) -> str:
    return f"{verb} {kind.location}"


def _set_epilog(name: str) -> str:
    """What follows a `set` command's help page: the one value that must
    never be typed as an argument, and then the fields the entity may
    carry.

    The second half is generated from the same `Field(description=...)`
    values the reference and the JSON Schema are rendered from, so the
    three cannot disagree and nobody has to remember to update a help
    string when a field changes. The first half is wrapped here at the
    width that half is wrapped at, because the page is printed as it was
    laid out rather than reflowed.
    """
    warning = textwrap.wrap(
        SECRET_NOT_A_PAIR,
        width=docgen.HELP_WIDTH,
        break_long_words=False,
        break_on_hyphens=False,
    )
    return "\n".join([*warning, "", docgen.fragment_help(name)])


# The groups of the tree, keyed by the noun path they sit at
#
# A group's own help is the one fact a leaf row cannot carry, so it is
# stated here; everything else about the shape of the tree is derived
# from the words in the table below, which is what makes a three-word
# row a row rather than a special case.
#
# The five entity nouns are derived, through the same `_about` the rows'
# own help comes from, so a new kind arrives as a noun carrying its four
# verbs rather than as five edits. What stays written out is what the
# registry cannot supply: the device, the boards waiting under it, the
# default agent, and the two secret sub-nouns.
#
# A sub-noun is not invented per command. A path segment followed by an
# identity of its own is a sub-noun (`/providers/{stage}/{name}/secrets/
# {slot}`, `/devices/pending/{code}`); a trailing segment with no
# identity after it is an attribute of its parent, and reading one is a
# verb on the parent, which is what `agent preview` is.
GROUPS: dict[tuple[str, ...], str] = {
    **{(kind.name,): _about("read and write", kind) for kind in entities.ENTITIES},
    ("provider", "secret"): "credentials stored on providers.<stage>.<name>",
    ("mcp-server", "secret"): "credentials stored on mcp_servers.<name>",
    ("device",): "read and write devices.<mac>: a board's name, place and agents",
    ("device", "pending"): "the boards waiting to be claimed, and claiming one",
    ("default-agent",): "the agent an unbound device reaches",
    # A noun with verbs rather than two flat words, because it has a
    # subject: the simulated board, which persists across invocations as
    # its MAC and which more than one verb asks about. `simulate` and
    # `check-in` side by side at the top level would be exactly the list
    # of things-and-actions that noun first exists to remove.
    ("simulator",): "a simulated board, checking in the way one with a screen would",
    # The conversation store's own noun, and singular for the reason the
    # cli-guide's naming rule gives: `show` and `delete` address one
    # entry. The guide is amended by the change that lands this
    # (docs/plans/2026-08-28-first-class-conversations.md), because its
    # examples spelled the noun plural before there was one.
    ("session",): "the sessions this server recorded, and erasing them",
    # And the store's other entity, singular under the same rule: `show`
    # and `delete` address one thread.
    ("conversation",): "the conversations this server recorded, and erasing them",
    # The live counterpart of the two above: the same events those
    # records are assembled from, before anything has been written down.
    # A noun with a verb rather than a flat `tail`, because the noun is
    # what the verb is about and because a second verb over the same
    # subject is where this goes next.
    #
    # The adjacent `vinga-server events reference` is a different
    # program's spelling of the same word and keeps its own home, which
    # the cli-guide's two-spellings section explains: that one prints
    # what the events ARE and needs no server, this one prints what a
    # server is saying and reaches one.
    ("events",): "what the running server is saying right now, as it says it",
    # The named aggregates over the same record, and the reading that
    # answers about days rather than about one session or one thread.
    # Singular under the naming rule, because `show` addresses one of
    # them: a view is an entry of a published vocabulary, the way an
    # agent is an entry of the configuration, and `/metrics/{view}` is
    # the route that says so.
    #
    # `metric latency` would have been shorter and is excluded: a noun
    # in the verb slot reads as a possessive and hides what the command
    # does, and `agent preview` is the precedent for not granting that
    # exception to the first command that asks for it.
    ("metric",): "the aggregates over the record: what each answers, and one over days",
    # What the agents, the boards and the conversations remember.
    # Singular under the naming rule, because its verbs address one
    # memory; one noun rather than three, because the scope is the first
    # segment of every one of the routes' own paths and is therefore
    # part of the address rather than part of the noun.
    ("memory",): "what is remembered about a person, a place and a conversation",
}


def _entity_rows(kind: entities.EntityDescriptor) -> tuple[Command, ...]:
    """One entity kind's four verbs, in the order a reader meets them.

    Built from the descriptor rather than written out, which is the
    whole of what noun first buys here: a kind that arrives in the
    registry arrives in the grammar with a page per verb, and none of
    the four can come to be described one way in the help and another
    way in the reference.
    """
    addressed_write = _staged_write if kind.addressing == ("stage", "name") else (
        _named_write if kind.addressing else _written
    )
    addressed_read = _staged if kind.addressing == ("stage", "name") else (
        _named if kind.addressing else _plain
    )
    rows = [
        Command(
            words=(kind.name, "set"),
            kind=kind.name,
            does=SET_ENTITY[kind.name],
            declare=addressed_write,
            help=_about("create or replace", kind),
            epilog=_set_epilog(kind.name),
        ),
        Command(
            words=(kind.name, "show"),
            kind=kind.name,
            does=SHOW_ENTITY[kind.name],
            declare=addressed_read,
            help=_about("print", kind),
        ),
        Command(
            words=(kind.name, "export"),
            kind=kind.name,
            does=EXPORT_ENTITY[kind.name],
            declare=addressed_read,
            help=_about("export", kind),
        ),
    ]
    if kind.has_delete:
        rows.append(
            Command(
                words=(kind.name, "delete"),
                kind=kind.name,
                does=DELETE_ENTITY[kind.name],
                declare=addressed_read,
                help=_about("delete", kind),
                destroys=True,
            )
        )
    return tuple(rows)


COMMANDS: tuple[Command, ...] = (
    *(row for kind in entities.ENTITIES for row in _entity_rows(kind)),
    # A stored credential is addressed under the entity that holds it,
    # in the slot it fills, and `secrets` is followed by `{slot}` on the
    # API, so it is a sub-noun of the kind rather than a verb of it.
    Command(
        words=("provider", "secret", "set"),
        kind="provider",
        does=SET_SECRET,
        declare=_provider_secret,
        help="store a credential on providers.<stage>.<name>",
    ),
    Command(
        words=("provider", "secret", "clear"),
        kind="provider",
        does=CLEAR_SECRET,
        declare=_provider_slot,
        help="remove a stored credential from providers.<stage>.<name>",
        destroys=True,
    ),
    Command(
        words=("mcp-server", "secret", "set"),
        kind="mcp-server",
        does=SET_SECRET,
        declare=_mcp_secret,
        help="store a credential on mcp_servers.<name>",
    ),
    Command(
        words=("mcp-server", "secret", "clear"),
        kind="mcp-server",
        does=CLEAR_SECRET,
        declare=_mcp_slot,
        help="remove a stored credential from mcp_servers.<name>",
        destroys=True,
    ),
    # The read of the running server that belongs to the MCP entries:
    # what is stored is `mcp-server show`, and what each entry is doing
    # right now is this. A read of the process rather than of the
    # database, so there is no state to report when there is no server
    # to ask.
    #
    # Under the noun since #341, where it always belonged: it is a verb
    # of the MCP servers and of nothing else, so the flat spelling put a
    # per-noun read at the top level, next to the verbs whose subject is
    # the whole deployment. The word is unchanged and there is no alias,
    # which is the pre-release stance: a board is reflashable and a
    # deployment is this repository's own.
    Command(
        words=("mcp-server", "status"),
        kind="mcp-server",
        does=STATUS,
        declare=_plain,
        help=(
            "what each configured MCP server is doing on the running server: connected, "
            "down, or unused because no agent references it, since when, and which "
            "tools it published"
        ),
    ),
    # The read of the running server that belongs to one agent: what is
    # stored is `agent show`, and what a new session would be sent is
    # this. A verb rather than the noun `prompt`, because a noun in the
    # verb slot reads as a possessive and hides what the command does.
    Command(
        words=("agent", "preview"),
        kind="agent",
        does=PROMPT,
        declare=_named,
        help=(
            "the system prompt a new session as this agent would be sent, block by "
            "block with the size of each and the total; a conversation already running "
            "holds what it assembled when it started"
        ),
    ),
    # The other verb of the agent noun that the registry does not build:
    # one agent given another name, with every live reference to the old
    # one moved in the same transaction. A verb rather than a `set` with
    # a new key, because a rename is a thing that happens rather than a
    # description of what should exist, and a document cannot say it.
    #
    # `destroys=False`, which is the guide's line rather than a feeling
    # about the word: a verb destroys when its effect cannot be undone
    # by running another command with information the operator still
    # has, and this one is undone by vinga agent rename <new> <old>,
    # which carries the memory and the threads back with it. What keeps
    # that true is the refusals: a destination already holding an agent,
    # remembered facts or recorded threads is refused, so a rename can
    # never merge two pasts into one and leave a second rename unable to
    # tell them apart. If a merge is ever licensed, this row grows the
    # confirmation on the day it does.
    Command(
        words=("agent", "rename"),
        kind="agent",
        does=RENAME_AGENT,
        declare=_renamed_to,
        help=(
            "give one agent another name, moving its device bindings, the default "
            "agent if it was one, what it remembered and the conversations it owns "
            "in one transaction; refused whole if the new name is taken anywhere it "
            "would write"
        ),
    ),
    # The device is a noun the registry does not describe: a binding is
    # a domain-level field written with verbs of its own rather than
    # from a fragment.
    #
    # Two ways to bind a board, and which one an operator wants depends
    # on what they are holding: a MAC they already know, or a device in
    # front of them showing six digits. Two verbs of one noun now, on
    # two different sub-nouns, so the pair is told apart by what it
    # addresses rather than by its help text alone.
    Command(
        words=("device", "bind"),
        kind="device",
        does=BIND_DEVICE,
        declare=_bound_by_mac,
        help="bind a device by the MAC you already know, to one or more agents",
    ),
    Command(
        words=("device", "show"),
        kind="device",
        does=SHOW_DEVICE,
        declare=_by_mac,
        help="print devices.<mac>: that board's id, name, place and agents",
    ),
    Command(
        words=("device", "delete"),
        kind="device",
        does=DELETE_DEVICE,
        declare=_by_mac,
        help="delete devices.<mac>, so the board it names reaches the default agent",
        destroys=True,
    ),
    # The other two halves of the device record, each a verb on the
    # device rather than a `location` sub-noun: `/devices/{mac}/location`
    # is a trailing segment with no identity after it, which the
    # cli-guide calls an attribute of its parent, and an attribute in
    # the verb slot reads as a possessive. `preview` is the merged
    # precedent for giving such an act a verb of its own.
    #
    # `rename` is `destroys=False` by the guide's own line: the act is
    # undone by `device rename <mac> <old name>`, which the operator has
    # in the shell history of the command they just typed, and no
    # refusal has to be lifted first because a name freed by a rename is
    # free.
    Command(
        words=("device", "rename"),
        kind="device",
        does=RENAME_DEVICE,
        declare=_device_renamed_to,
        help=(
            "give one device another name, which is what an agent says out loud about "
            "the board it is speaking through; refused if another device answers to it"
        ),
    ),
    # `replace` is the third verb on the device and the only one about
    # the hardware. A verb rather than a sub-noun by the rule the two
    # above are held to: `/devices/{mac}/replace` is a trailing segment
    # with no identity after it, so it is an attribute of its parent and
    # reading or writing one is a verb on the parent.
    #
    # The word is the act's own. What is replaced is the BOARD, which is
    # what the payload names, exactly as `rename` replaces the name the
    # payload names; the device is what survives, which is the whole
    # point and is what the help says. `swap` was the other candidate
    # and is what this milestone is called in prose, and it is the wrong
    # word for a command: a swap is an exchange of two things, and an
    # address another record already answers at is refused rather than
    # exchanged.
    #
    # `destroys=False` by the guide's line, the same line `agent rename`
    # answers to: the act is undone by `device replace <new> <old>`,
    # which the operator has in the shell history of the command they
    # just typed, and no refusal has to be lifted first because the
    # address a swap frees is free. What keeps that true is that both
    # destinations are refused when occupied, so a swap can never merge
    # two records or two memories and leave a second swap unable to tell
    # them apart.
    Command(
        words=("device", "replace"),
        kind="device",
        does=REPLACE_DEVICE,
        declare=_device_replaced_by,
        help=(
            "put one device record on another board, keeping its identity, its name, "
            "where it stands, the agents it reaches and what it remembers; refused if "
            "anything is already bound to or remembered about the new MAC"
        ),
    ),
    Command(
        words=("device", "relocate"),
        kind="device",
        does=RELOCATE_DEVICE,
        declare=_device_located_at,
        help="say where one board stands, free-form and not unique",
    ),
    Command(
        words=("device", "clear-location"),
        kind="device",
        does=CLEAR_DEVICE_LOCATION,
        declare=_by_mac,
        help="unset where one board stands, leaving it nowhere in particular",
        destroys=True,
    ),
    Command(
        words=("device", "pending", "list"),
        kind="device",
        does=PENDING,
        declare=_plain,
        help="the devices showing an activation code, and the code each is showing",
    ),
    Command(
        words=("device", "pending", "claim"),
        kind="device",
        does=ADD_DEVICE,
        declare=_bound_by_code,
        help=(
            "bind the device showing this activation code, which is the six digits on "
            "its screen; use device bind when you know the MAC instead"
        ),
    ),
    # The setting that is a noun with two verbs. `<name>` is payload
    # rather than address: `/default-agent` has no path parameter.
    Command(
        words=("default-agent", "set"),
        does=SET_DEFAULT_AGENT,
        declare=_named,
        help="the agent an unbound device reaches",
    ),
    Command(
        words=("default-agent", "clear"),
        does=CLEAR_DEFAULT_AGENT,
        declare=_plain,
        help="unset it, leaving the devices map as the allowlist",
        destroys=True,
    ),
    # The flat verbs: their subject is the whole deployment, or nothing
    # stored at all. Inventing a noun to put in front of them would
    # invent a word for the thing the program is already about.
    #
    # First of them, because it is the one an operator runs first: which
    # deployment is this, and am I talking to the one I think I am. Two
    # acts in one row for the reason `conversation show` has two: what
    # was asked for is one thing, and the API answers it as two
    # resources because identity is the running server's and the counts
    # are the store's.
    Command(
        words=("info",),
        does=(IDENTITY, COUNTS),
        opens=_contacted,
        declare=_plain,
        help=(
            "what deployment this is: the API this CLI reached, the running server's "
            "version and revision, the URL to type into a device's captive portal, and "
            "how much of each kind is configured"
        ),
    ),
    # The one write that carries the whole configuration. Its own row
    # rather than a flag on a noun's `set`, because what it takes is a
    # document and what it promises is one transaction over all of it.
    #
    # One act, and the verb says which one (#371). It writes the
    # document to the store and stops there; installing it on the
    # running server is `apply`, which is a command rather than the
    # absent half of a flag.
    Command(
        words=("import",),
        does=IMPORT,
        declare=_imported_document,
        help=(
            "write a whole document to the store in one transaction, refused whole if "
            "anything in it will not resolve; additive, never deleting, and waiting "
            "for the answer however long the transaction takes; nothing running "
            f"changes until {PROGRAM} apply"
        ),
    ),
    Command(words=("list",), does=LIST, declare=_plain, help="a summary tree"),
    Command(
        words=("show",),
        does=SHOW_ALL,
        declare=_plain,
        help="print the whole stored configuration, with its stored secrets masked",
    ),
    Command(
        words=("export",),
        does=EXPORT_ALL,
        declare=_plain,
        help="the stored configuration as a document import takes",
    ),
    # The seat #193 reserved. Flat with the three above it, because its
    # subject is the deployment: it compares the whole stored half
    # against the whole running one, and there is no noun to put in
    # front of it that is not the thing the program is already about.
    Command(
        words=("diff",),
        does=DIFF,
        declare=_plain,
        help=(
            "what the stored configuration would change on the running server, kind by "
            "kind, with the boundary each kind's changes reach a conversation at"
        ),
    ),
    # The conversation store's sessions. Reads of a different schema
    # from everything above, and two erasures of it, all of them
    # requests: there is no local-database path here and there is not
    # going to be one (#281, #282).
    Command(
        words=("session", "list"),
        does=LIST_SESSIONS,
        declare=_filtered_sessions,
        help=(
            "the sessions this server recorded, newest first, one page of them; "
            "narrow it with --device and size the page with --limit"
        ),
    ),
    Command(
        words=("session", "show"),
        does=SHOW_SESSION,
        declare=_by_session,
        help=(
            "print one recorded session: the board and agent it ran with, how it "
            "ended, and what it stored"
        ),
    ),
    Command(
        words=("session", "delete"),
        does=DELETE_SESSION,
        declare=_by_session,
        help=(
            "erase one recorded session and everything it holds: its turns wherever "
            "their conversations are, the calls they made, and its events"
        ),
        destroys=True,
    ),
    Command(
        words=("session", "purge"),
        does=PURGE_SESSIONS,
        declare=_selected_sessions,
        help=(
            "erase every session the selectors name, in one transaction; at least one "
            "of --session, --device and --before is required and several are combined"
        ),
        destroys=True,
    ),
    # The conversation store's other entity: the durable thread the same
    # turns project as. Reads and one erasure, requests like the four
    # above them and for the same reason.
    Command(
        words=("conversation", "list"),
        does=LIST_CONVERSATIONS,
        declare=_filtered_conversations,
        help=(
            "the conversations this server recorded, most recently active first, one "
            "page of them; narrow it with --agent and size the page with --limit"
        ),
    ),
    Command(
        words=("conversation", "show"),
        does=(SHOW_CONVERSATION, READ_DIALOGUE),
        declare=_by_conversation,
        help=(
            "print one recorded conversation: whose thread it is, what it is called "
            "and when it ran, and then a page of what was said in it, oldest first"
        ),
    ),
    Command(
        words=("conversation", "delete"),
        does=DELETE_CONVERSATION,
        declare=_by_conversation,
        help=(
            "erase one recorded conversation: its turns out of whatever sessions they "
            "were spoken in, the calls they made, and its recap checkpoints; the "
            "sessions themselves are left with a gap rather than deleted"
        ),
        destroys=True,
    ),
    # The aggregates over the same rows, read as days rather than as
    # one session or one thread. Two reads and no erasure: a view owns
    # nothing and a question cannot be deleted.
    Command(
        words=("metric", "list"),
        does=LIST_METRICS,
        declare=_plain,
        help=(
            "the aggregates this server serves, each with the question it answers, "
            "its denominator, what telemetry storage being off does to it and the "
            "columns a row of it carries, and what holds for all of them"
        ),
    ),
    Command(
        words=("metric", "show"),
        does=SHOW_METRIC,
        declare=_over_a_window,
        help=(
            "one aggregate over a window of whole UTC days, newest day first; bound "
            "it with --since and --until, both of them inside the window, and the "
            "answer says which two days it used"
        ),
    ),
    # What this deployment remembers, and the one noun in this grammar
    # whose verbs reach three resources apiece: the scope is the first
    # address segment, so which act a row performs is read off it
    # (`Command.selects`) and every one of them is what the row can
    # reach, which is what coverage is about.
    Command(
        words=("memory", "list"),
        does=(
            LIST_AGENT_MEMORIES,
            READ_AGENT_MEMORY,
            LIST_DEVICE_MEMORIES,
            READ_DEVICE_MEMORY,
            LIST_CONVERSATION_MEMORIES,
            READ_STATE,
        ),
        selects=_memory_listing,
        declare=_memory_read,
        help=(
            "with no owner, who is remembering anything in that scope and how much; "
            "with one, what that agent, board or conversation holds, oldest first, "
            "with the number each fact is addressed by; one page at a time, and a page "
            "that is not the last says what to give --cursor for the rest"
        ),
    ),
    Command(
        words=("memory", "set"),
        does=(CORRECT_AGENT_FACT, CORRECT_DEVICE_FACT),
        selects=_memory_correction,
        declare=_memory_write,
        help=(
            "correct one remembered fact in place, keeping its number, reading the "
            "corrected text from a file named with -f or from standard input and never "
            "from an argument"
        ),
    ),
    Command(
        words=("memory", "delete"),
        does=(
            FORGET_AGENT_FACT,
            CLEAR_AGENT_MEMORY,
            FORGET_DEVICE_FACT,
            CLEAR_DEVICE_MEMORY,
            CLEAR_STATE,
        ),
        selects=_memory_deletion,
        declare=_memory_deletion_arguments,
        help=(
            "erase one remembered fact by its number, or the whole of one memory with "
            "--all; for a conversation, clear one entry of its ledger by a name read "
            "from standard input, or the whole ledger with --all"
        ),
        destroys=True,
    ),
    # The live half of the two above, and the one row in this table that
    # is not a request with an answer: it opens a stream and prints it
    # until it is told to stop, which is why it carries its own function
    # rather than an act (`_events_tail`).
    Command(
        words=("events", "tail"),
        does=_events_tail,
        declare=_tailed,
        help=TAIL_HELP,
    ),
    # The one command that changes what the server is doing rather than
    # what is stored, which is why it is a verb of its own rather than a
    # flag on a write: an operator writes several entries and grant
    # lists and installs them once.
    #
    # The help is where the three convergence clocks live now (#371).
    # They used to be printed on every domain-half write, which said
    # them nine times for a document that wrote nine entities; here they
    # are read once, by somebody asking what this command does.
    Command(
        words=("apply",),
        does=APPLY,
        declare=_plain,
        help=(
            "install the stored configuration on the running server, without a "
            "restart and without dropping a conversation: a conversation already in "
            "progress meets new tools at its next utterance and new prompt text at "
            "its next activation, while a changed voice reaches the next conversation"
        ),
    ),
    # The diagnosis of the one above, and the only command in this
    # grammar whose subject is the stored configuration and whose answer
    # comes from no server (#443). An apply that the store will not
    # satisfy is refused without a location, on purpose; this is where
    # the location is read, out of the boot's own composition.
    Command(
        words=("check",),
        does=_check,
        declare=_from_the_file_half,
        help=CHECK_HELP,
    ),
    Command(
        words=("ota-url",),
        does=_ota_url,
        declare=_from_the_file_half,
        help=(
            "the URL to type into a device's captive portal; derived from this "
            "configuration and the device-auth secret, and it contacts nothing"
        ),
    ),
    # Read-only and offline: these three render the models and the
    # API's own routes, so they take no --config, open no database,
    # reach no server and need no encryption key. Keep it that way: the
    # documentation lane runs `reference` and `openapi` from a plain
    # sync, with no database, no key and no token anywhere.
    # The board nobody has to own. It reaches the OTA endpoint the way a
    # device does, and reaches the configuration API only when --claim
    # says so, which is why it takes both global options and why the
    # device half works with neither of them set.
    Command(
        words=("simulator", "check-in"),
        does=_simulator_check_in,
        declare=_simulated_board,
        help=(
            "check in to an OTA URL as a board would, and say what a board at that "
            "address would be handed"
        ),
        epilog=capabilities.epilog(docgen.HELP_WIDTH),
    ),
    Command(
        words=("simulator", "run"),
        does=_simulator_run,
        declare=_simulated_board,
        help=RUN_HELP,
        epilog=capabilities.epilog(docgen.HELP_WIDTH),
    ),
    Command(
        words=("schema",),
        does=_schema,
        declare=_of_an_entity,
        help="the JSON Schema of one entity, or of the whole domain half",
    ),
    Command(
        words=("reference",),
        does=_reference,
        declare=_of_a_half,
        help="the markdown reference of one half, generated from the models",
    ),
    Command(
        words=("openapi",),
        does=_openapi,
        declare=_rendered,
        help="the configuration API's OpenAPI document, generated from its routes",
    ),
    Command(
        words=("cli-reference",),
        does=_cli_reference,
        declare=_rendered,
        help=(
            "the generated half of the CLI reference: the recipes read out of the "
            "example fragments, and every command's own help page"
        ),
    ),
)


# The order a reader meets the top level in, which is the table's own:
# the nouns in the registry's order, then the device and the default
# agent, then the flat verbs, of which `info` is the first because it is
# the one an operator runs before they know anything else.
_ORDER = tuple(dict.fromkeys(row.words[0] for row in COMMANDS))


def command() -> TyperGroup:
    """The whole grammar, as the one command that runs it.

    Built per call, the way the parser it replaces was: nothing here is
    stateful, and a fresh tree is what keeps one test reading a command's
    help from depending on what another did to it. A name rather than a
    private because the tree is what the help tests enumerate and what
    the committed command reference will be rendered from.
    """
    app = typer.Typer(
        help=DESCRIPTION,
        # Every group of this grammar is a `_Grouped`, which is where an
        # invocation that named no command is answered with this page.
        cls=_Grouped,
        # And the library's own no-args help stays off, so that decision
        # is made in one place. It would also be the wrong answer twice
        # over: it sees only the case where nothing at all followed, and
        # it is a request for help rather than a failure, while arriving
        # without a command is a failure that this grammar answers
        # helpfully. The page goes to stderr, since stdout is data and
        # this invocation produced none, and the exit stays 1, since a 0
        # would say a command completed when none was typed.
        no_args_is_help=False,
        # Neither of the two options Typer would otherwise add: this
        # group's options are the three below and nothing else.
        add_completion=False,
        # Help formatted by Click rather than by Rich, so that what it
        # prints does not depend on a terminal, on colors, or on whether
        # an optional package happens to be installed.
        rich_markup_mode=None,
        # And `-h` beside `--help`, on every page of the tree: it is the
        # spelling half the world types first, and a program that
        # answers only the long one answers nothing to that.
        context_settings={"help_option_names": HELP_OPTION_NAMES},
    )
    app.callback()(_root)
    # One group per noun path, built before anything is attached, so a
    # row three words deep finds the group its leading words name rather
    # than being registered under the first of them with the word in the
    # middle discarded.
    #
    # The same class and the same flag at every noun as at the root
    # above, so `vinga provider` and `vinga device pending` are answered
    # with their own pages rather than the root's: each group raises
    # from its own context, and the boundary prints the page of whatever
    # context it is handed.
    groups = {
        path: typer.Typer(cls=_Grouped, no_args_is_help=False, rich_markup_mode=None)
        for path in GROUPS
    }
    for row in COMMANDS:
        under = groups[row.words[:-1]] if len(row.words) > 1 else app
        under.command(
            row.words[-1],
            cls=_Verbatim,
            help=row.help,
            # Click shortens a command's help for the listing, cutting
            # it at its first sentence or at the terminal's width. These
            # are one sentence each and the listing is where an operator
            # reads them, so the short form is the same string rather
            # than a truncation of it.
            short_help=row.help,
            epilog=row.epilog,
        )(row.declare(row))
    # Deepest first, so a sub-noun is attached to its parent before that
    # parent is attached to the tree above it.
    for path in sorted(GROUPS, key=len, reverse=True):
        described = GROUPS[path]
        above = groups[path[:-1]] if len(path) > 1 else app
        above.add_typer(
            groups[path], name=path[-1], help=described, short_help=described
        )
    grammar = typer.main.get_command(app)
    # Typer registers every command before every group, which would put
    # `set` and `show` at the foot of the listing whatever the table
    # says. The order a reader meets them in is the table's, so it is
    # restored from the table rather than left to the library.
    grammar.commands = {word: grammar.commands[word] for word in _ORDER}
    return grammar
