"""What one command was given, as the one type that says it.

The seam between the grammar and everything under it. Every act
addresses its resource and builds its body from one of these, and the
fields are the whole vocabulary the grammar has: the two options
accepted on either side of the command word, and the arguments that
address one entry. Stated as a type rather than as a bag of attributes,
so what a command can be asked is readable in one place and an act that
reads a field nobody sets is a name that is not there.

What its callers stop knowing: nothing at all, which is what makes it
the lowest module of this package. It reads nothing else here and
everything else here reads it, so a seam that is a type rather than an
object two sides mutate has exactly one home.
"""

from dataclasses import dataclass

from vinga_server.config import server_reference


@dataclass(frozen=True, kw_only=True)
class Invocation:
    """One command's arguments, resolved."""

    # The global options, after the merge below: each is what the
    # command position said when it said anything, and what the root
    # position said otherwise. The two booleans are resolved to plain
    # booleans exactly once, by that merge, so nothing below this seam
    # has to know that "not given" was ever a third answer.
    config: str | None = None
    api_url: str | None = None
    force: bool = False
    no_input: bool = False

    # What addresses one entry, under the names the descriptors'
    # `addressing` tuples use, which are the URL's path parameters and
    # the CLI's positionals for the same reason.
    stage: str = ""
    name: str = ""
    # `None` rather than the empty string the fields around it default
    # to, because `mac` is the one of them an optional filter also
    # rides: a `--device` that was not given and a `--device ''` are
    # different questions, and a default of `""` would make the second
    # unsayable.
    mac: str | None = None
    code: str = ""
    slot: str = ""

    # Which kind of entity a command that covers two of them was asked
    # about, which is what decides where a credential is addressed. Read
    # off the row rather than off the words, because a command's noun
    # path and the kind it addresses are not the same thing once the
    # tree is more than two words deep.
    kind: str = ""

    # The rest of what a command can carry: the agents a binding names,
    # the two ways a write's entity is written, the variable a secret is
    # read from, and the entity a schema is asked for.
    agents: tuple[str, ...] = ()
    file: str = ""
    pairs: tuple[str, ...] = ()
    from_env: str | None = None
    entity: str | None = None

    # And the payload that is a name rather than a document: the name a
    # rename is to give the agent it addresses. It sits here rather than
    # among the fields above it because it addresses nothing: the route
    # is `/agents/{name}/rename`, so `name` above is the whole address
    # and this is what the request carries. Spelled as the body's own
    # key, the way `agents` is.
    to: str = ""

    # And where a device is being put, which addresses nothing either:
    # the route is `/devices/{mac}/location`, so `mac` above is the
    # whole address and this is what the request carries. Spelled as the
    # body's own key, the way `agents` and `to` are.
    location: str = ""

    # And the provider type a schema is asked about, which goes with the
    # `stage` above: the two together name one type's options, since the
    # registry holds one type name in more than one stage.
    type_name: str = ""

    # Which half of the configuration a reference is asked for. Its
    # default is the registry's first row rather than a word written
    # here, so the bare verb and the positional cannot come to disagree
    # about what nothing means.
    half: str = server_reference.DEFAULT_HALF

    # The conversation store's session, and the two things a listing and
    # a purge are narrowed by that are not a device. `mac` carries the
    # device for both of them, reused from the verbs that already take
    # one rather than given a second name: what `--device` names is the
    # same board `device show` addresses.
    #
    # `limit` and `before` are text and are not read here. What each has
    # to be is the API's rule, said in the API's own fixed sentence, and
    # a second parser in front of it would be a second vocabulary for
    # one refusal.
    session: str = ""
    limit: str = ""
    before: str = ""

    # And the conversation store's other identity, the thread. Its own
    # field rather than `name`, because the two are addressed at once:
    # `conversation list --agent sam` filters threads by an agent's
    # name, which `name` is already carrying.
    conversation: str = ""

    # What the memory noun addresses beyond the three owners above, which
    # it reuses: `name` is an agent, `mac` is a board and `conversation`
    # is a thread, because those are the words the routes' own path
    # parameters use and one of the three is filled per invocation.
    #
    # `scope` is which of them a command was asked about, taken as the
    # first positional and read by the row to choose the act it performs.
    # `fact` is a fact's number, carried as text because it is a path
    # segment: what a number has to be is the API's rule, said in the
    # API's own fixed sentence, and a second parser here would be a
    # second vocabulary for one refusal.
    #
    # `all_of_it` is the flag that stands in for an absent id on the
    # deletions, so a mistyped number can never mean everything.
    #
    # `cursor` is where a listing carries on from, which this noun has
    # and the record's two do not. The difference is what the listings
    # are of: a session list is a window onto a log that only grows, and
    # what an operator wants of it is the newest page; a memory is a
    # bounded thing being audited, and a page of it that could not be
    # followed would make `list` a claim this grammar cannot keep. Text
    # and not read here, for the reason `limit` is not: what a cursor
    # has to be is the API's rule, said in the API's own fixed sentence.
    scope: str = ""
    fact: str = ""
    all_of_it: bool = False
    cursor: str = ""

    # Which named aggregate a request is about, under the name the
    # route's own path parameter uses: `/metrics/{view}` addresses one
    # view and this is the whole of that address. Its own field rather
    # than `name`, because `name` is an agent everywhere else in this
    # grammar and a view is not one.
    #
    # And the two days that bound the window, which address nothing:
    # they narrow the answer the way `--device` narrows a session
    # listing. Text and not read here, for the reason `limit` is not:
    # what a day has to be is the API's rule, said in the API's own
    # fixed sentence, and a second parser in front of it would be a
    # second vocabulary for one refusal.
    #
    # `group` is how the rows are broken down, and it is text for the
    # same reason. The set it is held to is the API's closed vocabulary,
    # published in the document and refused there; a copy of it here
    # would be a second set to keep in step with the first.
    #
    # Which board a per-device answer is narrowed to rides `mac`, the
    # field every other `--device` on this grammar already uses, because
    # it is the same board `device show` addresses.
    view: str = ""
    since: str = ""
    until: str = ""
    group: str = ""

    # What narrows the live event stream beyond the board and the
    # session above, which `mac` and `session` carry for it: what
    # `--device` names is the same board `device show` addresses, and
    # what `--session` names is the same session `session show` does.
    #
    # `level` is text and is not read here, for the reason `limit` is
    # not: what a level may be is the API's rule, said in the API's own
    # fixed sentence, and a second parser in front of it would be a
    # second vocabulary for one refusal.
    level: str = ""

    # And whether the tail keeps going. The one argument in this grammar
    # that changes when a command stops rather than what it asks for.
    follow: bool = False

    # The address a simulated board checks in to. Its own field rather
    # than `name` or `file`, because it is neither an identity nor a
    # payload: it names the deployment, it is held to the device-facing
    # transport policy rather than to the API's, and it is the one
    # positional in this grammar that addresses no row of anything. The
    # MAC and the agents that go with it are `mac` and `agents`, reused
    # from the device verbs that already take them.
    endpoint: str = ""
