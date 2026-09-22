"""Reading an answer.

What a body has to be to be read as one is the shape the API declared
it would send, which is a model in `responses.py` that the API itself
answers with. There is no second encoding of it here: a rule this
module kept by hand is a rule that goes stale the day a field is
renamed, and the two files that would then disagree both say they are
describing the same thing.

What its callers stop knowing: which tolerances this client keeps
against a server of another age. An act names a shape and a refusal
sentence and is handed the answer read as that shape, or the refusal;
that a newer server's extra field is dropped, that a token it has never
heard of is left as the string it arrived as, and that a sequence of
tokens is read whole or not at all are decisions taken here and
nowhere else.

Two readers and one reading. `_understood` answers the mappings a
renderer walks and `encoded` answers a document a program reads, and
what differs between them is the mode the validated result is dumped
in: a body one of them refuses is a body the other refuses, in the same
sentence, because they refuse it in the same place.
"""

import json
from collections.abc import Mapping
from enum import Enum, StrEnum
from typing import Any, Literal, get_args, get_origin

import yaml
from pydantic import BaseModel, TypeAdapter

from vinga_server.config.loader import ConfigError

# What an answer nobody vouched for can provoke out of the libraries
# this reading is built on, which is the set this module's boundary is
# defined by rather than one exception type of it.
#
# `config/transport.py` names the same class from the other side: "a
# TypeError, a ValueError or a RecursionError with a traceback, in place
# of the sentence this file exists to produce". A body can be everything
# a shape declares and still be something no encoder can write, and a
# document nested past what the dump will walk is exactly that: valid,
# and a `ValueError` out of a library. `ValidationError` is a
# `ValueError` in pydantic, so the strict reading's own refusal is this
# same arm rather than a second one beside it, and PyYAML's failures are
# not exceptions of Python's at all.
#
# `ConfigError` is not in it and is not caught by it: it is an
# `Exception` of this project's own, so a refusal composed further in
# passes through with its own words.
_UNWRITABLE = (TypeError, ValueError, RecursionError, yaml.YAMLError)


def _understood(shape: object, answer: object, refusal: str) -> Any:
    """One answer, read as the shape the API says it sends, or refused.

    Strict, so nothing is coerced on the way in: a body is free to put
    `true` where a size belongs or an object where a word does, and a
    renderer that printed the coercion would be printing something
    nobody sent. Extra fields are dropped rather than refused, which is
    the one tolerance this keeps deliberately: a newer server that
    answers more than this client knows about is readable, and what it
    said beyond the shape is not printed, because it was not rendered.

    Answered back as the mappings the renderers read, which is the shape
    a renderer takes: a token stays the member it was validated into, a
    date stays a date, and a renderer that prints either prints the
    thing rather than a spelling of it. That mode is the whole of what
    this reader and `encoded` below differ by; the reading itself, and
    the refusal discipline around it, are `_read`'s.

    Answers `Any` rather than `object` because what comes back is the
    shape that was asked for, and every caller reads it as one.
    """
    return _read(shape, answer, refusal, "python")


def _read(shape: object, answer: object, refusal: str, mode: Literal["python", "json"]) -> Any:
    """The reading both readers do, with the dump mode the whole of what
    they differ by.

    One function rather than two that have to agree: what a body must be
    to be read at all is one rule, and a second copy of it would be a
    second place for the strictness, the declaration filtering and the
    refusal to drift apart. What a caller chooses is the mode, which is
    a fact about who is going to read the result rather than about what
    the answer had to be.

    Dumping a validated model is also what leaves the extras behind:
    only what the shape declares is written back out.

    The dump is inside the arm and not only the validation, because the
    two fail for different reasons and only one of them is about the
    shape: a body can be everything the shape declares and still be
    something the dump cannot write, which `_UNWRITABLE` above is the
    set of. The answer either reads as the shape and comes back, or it
    is the act's one sentence.

    The refusal is built inside the handler and raised after it, and the
    exception itself is not bound to a name: `ValidationError.errors()`
    retains the input it rejected, which for this API can be a
    credential someone pasted into a fragment, and an exception raised
    while another is being handled keeps that one as its `__context__`
    for anything walking the chain to find.
    """
    problem: str | None = None
    try:
        adapter = TypeAdapter(shape)
        return adapter.dump_python(
            adapter.validate_python(_declared(shape, answer), strict=True), mode=mode
        )
    except _UNWRITABLE:
        problem = refusal
    raise ConfigError(problem)


class Output(StrEnum):
    """Which shape an act's answer leaves in.

    A member rather than a flag, because the question is which of three
    and not whether to encode: `HUMAN` is the act's own renderer, and
    the other two are documents a program reads. Declared here because
    what a member names is an encoding of an answer, which is this
    module's subject, and because `acts.py` already reads this module.

    The values are the words a command-line flag would use, so the day a
    `--json` reaches the grammar it sets this and nothing else moves.
    """

    HUMAN = "human"
    JSON = "json"
    YAML = "yaml"


def encoded(shape: object, answer: object, refusal: str, output: Output) -> str:
    """One answer, read as the shape the API says it sends and written
    as the document a program reads, or refused.

    The reading is `_understood`'s, exactly: the same strict validation
    over the same declaration filtering, refused with the same sentence,
    which is why the act's refusal is carried in. An answer no renderer
    would have been given is an answer no encoder is given either, and a
    dump of an unvalidated body would be this client publishing
    something nobody vouched for.

    What differs is the dump mode, and it is the whole difference: the
    human reading keeps a token as the member it was validated into,
    which is what its renderers read, and `yaml.safe_dump` has no
    representer for one, so the machine reading takes the JSON mode
    instead. A token leaves as the string it is declared as and a date
    as ISO text, which is what both encoders below can carry.

    Both arms escape to ASCII, on purpose. `printable` is what keeps a
    lone surrogate off stdout on the human path, this path does not go
    through it, and `main()` catches no encoding failure, so a surrogate
    that reached the stream raw would leave as a traceback rather than
    as a sentence. With escaping on, both encoders write it as an escape
    sequence and the bytes are valid whatever the terminal's encoding
    is. The export's `allow_unicode=True` is a choice about a document a
    person reads and this is a stream a program reads, which is why the
    two differ.

    `Output.HUMAN` does not arrive here: the act's own renderer is what
    answers it, and `_act` takes that arm before this is called, so the
    choice below is between the two documents rather than among three
    and this function holds no rendering.

    Ends in exactly one newline, which `yaml.safe_dump` already writes
    and the JSON arm adds, so that one act's answer is one document on
    the stream and the caller prints it without a second one.

    The encoding is inside the same arm the reading is, and for the same
    reason: what a library raises over an answer is a traceback with the
    answer in it, and this boundary answers with one sentence or with a
    document. The sentence is recorded inside the handler and raised
    once it has been left, so nothing of the library's own exception is
    on the chain behind it.
    """
    document = _read(shape, answer, refusal, "json")
    problem: str | None = None
    try:
        return _written(document, output)
    except _UNWRITABLE:
        problem = refusal
    raise ConfigError(problem)


def _written(document: object, output: Output) -> str:
    """The validated document as the format asked for, and nothing about
    whether it could be written: that is the boundary's above."""
    if output is Output.JSON:
        # Sorted, because determinism on stdout is the standing rule and
        # a mapping's order here is whatever the model happened to
        # declare rather than anything the answer said.
        return json.dumps(document, sort_keys=True, ensure_ascii=True) + "\n"
    # Block style and unsorted, which is the export's shape: what a YAML
    # document is read in is the order the shape declares, top to bottom,
    # and flow style would put a whole answer on one line.
    return yaml.safe_dump(document, default_flow_style=False, sort_keys=False, allow_unicode=False)


# What a field of a shape this client cannot read is worth, which is
# nothing: the key is dropped, and the field takes the default its model
# declares. A sentinel rather than the default itself, because only the
# model above a value knows what its default is, and only the walk below
# knows that a value could not be read.
_UNREADABLE_FIELD = object()


def _declared(shape: object, answer: object) -> object:
    """The answer with anything the shape does not declare left out.

    Every model in `responses.py` forbids extra keys, because the
    document it generates is a contract about what this API sends. This
    client reads that contract from the other side, where an unknown key
    means a server newer than it, so it drops what it does not know
    instead of refusing the whole answer. Guided by the shape and not by
    a list of field names: a mapping keyed by identity is walked into, so
    an entry nested in a listing is treated exactly as one that arrived
    on its own.
    """
    if isinstance(shape, type) and issubclass(shape, Enum):
        # A closed token, which arrives as the string it is declared as
        # and which strict validation will not make a member of. Looked
        # up rather than constructed: a token this client does not know
        # stays the string it was and meets the refusal, where
        # `Applies(answer)` would raise a ValueError out of a boundary
        # that catches validation errors.
        #
        # Only a string is looked up, and that is the same rule stated
        # about the answer rather than about the shape. Nothing bounds
        # what a body puts where a token belongs: a list or an object
        # there is unhashable, and using it as a key would raise a
        # TypeError out of this boundary exactly as constructing the
        # member would have. Every other shape passes through untouched
        # and meets strict validation, which is what turns it into the
        # one fixed sentence a body this client cannot read gets.
        if not isinstance(answer, str):
            return answer
        return {member.value: member for member in shape}.get(answer, answer)
    if isinstance(shape, type) and issubclass(shape, BaseModel):
        if isinstance(answer, Mapping):
            read = {
                name: _declared(field.annotation, answer[name])
                for name, field in shape.model_fields.items()
                if name in answer
            }
            # A field the walk could not read is dropped, which leaves
            # the model's own default in its place. Dropping rather than
            # substituting, because the default is the model's fact and
            # this walk does not hold it, and because a key that is not
            # there is exactly what an older server sent.
            return {
                name: value
                for name, value in read.items()
                if value is not _UNREADABLE_FIELD
            }
        return answer
    origin, arguments = get_origin(shape), get_args(shape)
    if origin is dict and isinstance(answer, Mapping):
        return {key: _declared(arguments[1], value) for key, value in answer.items()}
    if origin is list and isinstance(answer, list):
        return [_declared(arguments[0], item) for item in answer]
    if origin is tuple and arguments[-1] is Ellipsis and isinstance(answer, list):
        # A JSON array is a list, and strict validation will not make a
        # tuple of one. The shape asked for a tuple because what it
        # answers with is fixed once it is answered, which is a fact
        # about the model and not about the wire, so the conversion
        # belongs here with the other shape-guided ones rather than as a
        # tolerance inside the validator.
        read = tuple(_declared(arguments[0], item) for item in answer)
        # And a sequence of a closed token is read whole or not at all.
        #
        # A set of tokens is one fact rather than a list of facts: it
        # says which boundaries a write is waiting at, and a client that
        # kept the members it recognized and dropped the one it did not
        # would act on half of an answer while believing it had all of
        # it. So one unrecognized member makes the whole sequence a fact
        # this client cannot read, and the honest reading of that is the
        # one an older server gives by saying nothing: the field's
        # default.
        #
        # A rule about the shape and not about a field name, which is
        # what this walk is written to be, and deliberately narrower
        # than the scalar branch above: an unknown token where one word
        # is expected still refuses the whole answer, because a value
        # that is printed as itself has no honest default to fall back
        # to.
        if isinstance(arguments[0], type) and issubclass(arguments[0], Enum):
            if any(not isinstance(item, arguments[0]) for item in read):
                return _UNREADABLE_FIELD
        return read
    # Anything else is a leaf as far as this is concerned, including the
    # unions, which carry no model in any of these shapes, and
    # `dict[str, Any]`, which is where a masked entity body travels
    # through undescribed on purpose.
    return answer
