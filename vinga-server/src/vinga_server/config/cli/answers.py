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
"""

from collections.abc import Mapping
from enum import Enum
from typing import Any, get_args, get_origin

from pydantic import BaseModel, TypeAdapter, ValidationError

from vinga_server.config.loader import ConfigError


def _understood(shape: object, answer: object, refusal: str) -> Any:
    """One answer, read as the shape the API says it sends, or refused.

    Strict, so nothing is coerced on the way in: a body is free to put
    `true` where a size belongs or an object where a word does, and a
    renderer that printed the coercion would be printing something
    nobody sent. Extra fields are dropped rather than refused, which is
    the one tolerance this keeps deliberately: a newer server that
    answers more than this client knows about is readable, and what it
    said beyond the shape is not printed, because it was not rendered.

    The refusal is built inside the handler and raised after it, and the
    exception itself is not bound to a name: `ValidationError.errors()`
    retains the input it rejected, which for this API can be a
    credential someone pasted into a fragment, and an exception raised
    while another is being handled keeps that one as its `__context__`
    for anything walking the chain to find.

    Answers `Any` rather than `object` because what comes back is the
    shape that was asked for, and every caller reads it as one.
    """
    problem: str | None = None
    try:
        adapter = TypeAdapter(shape)
        # Answered back as the mappings the renderers read, which is the
        # shape a renderer takes. Dumping a validated model is also what
        # leaves the extras behind: only what the shape declares is
        # written back out.
        return adapter.dump_python(adapter.validate_python(_declared(shape, answer), strict=True))
    except ValidationError:
        problem = refusal
    raise ConfigError(problem)


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
