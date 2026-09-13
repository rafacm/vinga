"""The provider types: what builds each one, and what it accepts.

A provider entry's options are everything it carries beyond `type`,
`api_key_env` and `reach`, and until this module existed they were
read key by key inside the type's own builder: a ladder of
`OptionsReader` calls that named a rule per key, refused the leftovers,
and was invisible to every surface that documents the configuration.
A type that declares a model here states the same contract in one
place, and the write path, the builder, the JSON Schema and the
refusals all read it from that place (#88).

Three things live here and nothing else. The model CLASSES; the
`PROVIDER_TYPES` table, which is the one statement of which types exist,
where each one is built and which of them declares a model; and the
SANITIZER, the one function that turns a stage, a type and a mapping
into either a validated instance or a value-free refusal, so the write
path, the read-back and the build path consult one implementation rather
than three.

One topology, and everything derives from it: `providers/registry.py`
builds its registrations by resolving this table's factory names, the
documentation renders its per-type sections out of the same entries, and
the refusal that lists a stage's known types counts the same keys. There
is no second mapping to hold against this one and no test bridging two.

It weighs pydantic and `config.models` and nothing else: no provider
package, no engine, no database driver, no cryptography. A factory is
named rather than imported, which is what lets the topology live at an
address the documentation can afford. Three committed pins depend on
that, and each of them is a promise this repository makes about where
its code can run.

- The reference and the JSON Schema render from the models alone, in a
  child interpreter with no database and no key
  (`test_config_docgen.py`). They document these options now, so this
  module is on that path.
- Rendering the OpenAPI document loads no part of a conversation
  (`test_onboarding_import_weight.py`). It carries these models as
  components now.
- `vinga-server config` loads no engine. It prints these fields in the
  epilog of `set provider`, built when the command table is.

A home inside the provider package could satisfy none of the three: the
package's `__init__` re-exports the whole provider layer, so importing
one pydantic module from it pulls in the engine base classes, the
provider world and, through the secret store, cryptography. Hence this
address. What lives on the provider side is what genuinely runs there:
resolving a name into a callable, putting an entry's secrets in force,
constructing, and the reading of a validated instance inside a builder.

Field descriptions carry the example fragment's factual sentence, which
is what makes the schema and the reference say what the fragment says.
The narrative prose (the measurements, the tuning ladders, the reasons
behind a default) stays in the fragment under `examples/`, per the
standing documentation decision.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    GetJsonSchemaHandler,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    WithJsonSchema,
    model_validator,
)
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema

from vinga_server.config.models import (
    PROVIDER_STAGES,
    FieldProblem,
    FieldProblemsError,
    json_pointer,
    validation_problems,
)

# What a coercion rule says when it refuses.
#
# The reader these models replace accepted a narrow set and said so in a
# fixed sentence: a bool is not a number however happily Python treats
# it as one, "5" is not an integer, and an empty list is not a ladder.
# Ordinary pydantic fields are wider than that in lax mode, so the rules
# are stated as validators and the sentences are these, which name the
# rule and never the value: an option that fails one of them is as good
# a place for a pasted credential as any other.
NUMBER_RULE = "must be a number"

NUMBERS_RULE = "must be a number or a non-empty list of numbers"

# A required name with nothing in it is the same mistake as a missing
# one, and the reader said so: `required_string` refused a blank as
# loudly as an absent key. Said as a rule rather than as a value,
# because the value is the blank.
NONBLANK_RULE = "must not be blank"

# The formats this stage can pass through. Only the PCM ones are usable:
# the TTS interface's contract is s16le PCM, and decoding mp3 or opus
# just to re-encode it would add both a dependency and latency.
# `pcm_44100` and up need a paid vendor tier, which is the API's error to
# report rather than ours to predict.
PCM_FORMAT_RULE = "must be one of the pcm_<rate> formats, since this stage streams raw PCM"

# The same two rules in the vocabulary a published schema has for a
# string, which is the only one it has: a pattern.
#
# Written once each and used twice each, because a rule a document
# states and a rule a validator runs are one contract and this is the
# seam they come apart at. The refusals stay the validators' own, so an
# operator reads "must not be blank" rather than a regex; the patterns
# are what a client generating from the document is held to, and the
# cases in `test_provider_options.py` assert that what the document
# publishes is what the model accepts.
#
# `pattern` is unanchored in JSON Schema, so `\S` says "holds a
# non-whitespace character", which is `value.strip()` being truthy. The
# format one anchors itself and has no capture group: the rate is read
# off the validated string with `removeprefix`, so nothing needs one.
NONBLANK_PATTERN = r"\S"

PCM_FORMAT_PATTERN = r"^pcm_[0-9]+$"

_PCM_FORMAT = re.compile(PCM_FORMAT_PATTERN)

# What a list of spoken languages has to be, and what each entry in it
# has to look like.
#
# A shape rather than a membership test, and that is the decision rather
# than a shortcut. `events/values.py::LanguageTag` is the type these
# codes become downstream, and it accepts `not-a-language` and `de-DE`
# and refuses only what fails its syntax; a rule here claiming to check
# ISO 639-1 membership would claim more than the repository's own value
# type does, and a registry copied into this file goes stale silently
# while reading as authority.
#
# The empty list and the duplicate are refused for one reason: neither
# is something the endpoint can act on, and an operator who wrote one
# meant something. Order is kept and sent as written, since the endpoint
# is free to weigh it, and case is left alone for the same reason: both
# are the endpoint's to decide and normalizing either here would be this
# repository inventing a policy on its behalf.
LANGUAGE_RULE = "must be a language code, such as sv or en-US"

LANGUAGES_RULE = "must be a non-empty list of language codes, each written once"

# The `LANGUAGE` syntax from `events/values.py`, restated for the reason
# `base_url`'s default is restated below: that module is not on this
# one's import list. The events catalog is deliberately outside the
# written-down set of modules the configuration CLI may load
# (`test_cli_import_weight.py`, where widening the inventory is "a
# review event with a name"), so importing it to reach one regular
# expression would buy the constant and pay for the tier. Pinned against
# the syntax it restates by a case in `test_providers_openai_asr.py`,
# which is on the side that may import both.
LANGUAGE_PATTERN = r"^[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{1,8})*$"

LANGUAGE_MAX_LENGTH = 16

_LANGUAGE = re.compile(LANGUAGE_PATTERN)


def _as_number(value: object) -> object:
    """A number the way the reader took one: an int or a float, never a
    bool, normalized to a float so a builder gets one type."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(NUMBER_RULE)
    return float(value)


def _as_numbers(value: object) -> object:
    """A non-empty list of numbers, with a single number taken as a list
    of one, which is what the reader's `numbers()` accepted."""
    if value is None:
        return None
    if not isinstance(value, bool) and isinstance(value, (int, float)):
        return [float(value)]
    if (
        isinstance(value, list)
        and value
        and all(not isinstance(item, bool) and isinstance(item, (int, float)) for item in value)
    ):
        return [float(item) for item in value]
    raise ValueError(NUMBERS_RULE)


def _as_optional_number(value: object) -> object:
    """A number, or nothing at all: the reader's `optional_number`, for a
    knob whose absence means the vendor's own default rather than one of
    ours, and which an operator may therefore write as an explicit
    null."""
    return None if value is None else _as_number(value)


def _nonblank(value: str) -> str:
    """A string with something in it, which is what the reader's
    `required_string` demanded."""
    if not value.strip():
        raise ValueError(NONBLANK_RULE)
    return value


def _as_pcm_format(value: str) -> str:
    """An output format this stage can stream, refused by the rule rather
    than by quoting what was written."""
    if _PCM_FORMAT.match(value) is None:
        raise ValueError(PCM_FORMAT_RULE)
    return value


def _as_languages(value: list[str] | None) -> list[str] | None:
    """A non-empty list of distinct language codes, or nothing written at
    all, refused by the rule rather than by quoting a code back.

    Three refusals and one of them is the syntax, asked of the pattern
    above rather than of a membership list, for the reason stated there.
    The other two are about a list that says nothing: an empty one gives
    the endpoint nothing to weigh, and a repeated code is a set written
    twice, and in both cases the operator meant something the value does
    not say.
    """
    if value is None:
        return None
    if not value or len(set(value)) != len(value):
        raise ValueError(LANGUAGES_RULE)
    for code in value:
        if len(code) > LANGUAGE_MAX_LENGTH or _LANGUAGE.match(code) is None:
            raise ValueError(LANGUAGE_RULE)
    return value


# The shapes a declared option comes in, as annotations rather than as a
# rule repeated per field. The strict spellings are pydantic's own and
# their messages name the type they wanted; the numeric ones are ours,
# because lax pydantic would take a bool for a number and a numeric
# string for an integer and the reader never did.
Number = Annotated[float, BeforeValidator(_as_number)]

# The same rule with nothing written as a legal answer, for a knob whose
# absence means the vendor's own default rather than one of ours. No
# input type is declared beside it, unlike the ladder below, because
# there is nothing to declare: what the validator takes and what the
# annotation says are both "a number, or null".
OptionalNumber = Annotated[float | None, BeforeValidator(_as_optional_number)]

# What a validator accepts and what the schema says it accepts are two
# statements of one contract, and a `BeforeValidator` is exactly where
# they come apart: the annotation describes what comes OUT of it, so
# without the input type below the published schema said "an array of
# numbers, or null" while the validator took a bare number and refused
# an empty array. A client generating from the document would have
# written the one form the ladder refuses and omitted the one an
# operator most often writes.
#
# So the input type is declared, and it is the rule itself in the
# schema's own vocabulary: a number, or an array of at least one, or
# null. `min_length` on the array branch is `minItems`, which is the
# half `_as_numbers` refuses an empty list for.
Numbers = Annotated[
    list[float] | None,
    BeforeValidator(
        _as_numbers,
        json_schema_input_type=float | Annotated[list[float], Field(min_length=1)] | None,
    ),
]

# The two string rules, each carrying the schema that states it.
#
# `WithJsonSchema` is to an `AfterValidator` what `json_schema_input_type`
# is to a `BeforeValidator`: the annotation alone describes an
# unrestricted string, because a validator is code and a schema is not,
# so a document generated from it would tell a client that any string
# will do and the server would then refuse what the client wrote. The
# constraint is published rather than enforced twice: pydantic's own
# pattern message names a regex, and what an operator should read is the
# rule in this repository's words.
Nonblank = Annotated[
    StrictStr,
    AfterValidator(_nonblank),
    WithJsonSchema({"type": "string", "pattern": NONBLANK_PATTERN}),
]

PcmFormat = Annotated[
    StrictStr,
    AfterValidator(_as_pcm_format),
    WithJsonSchema({"type": "string", "pattern": PCM_FORMAT_PATTERN}),
]

# The list rule with the schema that states it, which for this one is
# four keywords rather than a pattern: what a document has to carry is
# the non-empty half, the each-written-once half and the shape of an
# entry, because a client generating from it would otherwise send the
# three values the model refuses. The published pattern is anchored
# because the rule is a full match; `NONBLANK_PATTERN` above is not, and
# the difference is the rule rather than an inconsistency.
Languages = Annotated[
    list[StrictStr] | None,
    AfterValidator(_as_languages),
    WithJsonSchema(
        {
            "anyOf": [
                {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "pattern": LANGUAGE_PATTERN,
                        "maxLength": LANGUAGE_MAX_LENGTH,
                    },
                    "minItems": 1,
                    "uniqueItems": True,
                },
                {"type": "null"},
            ]
        }
    ),
]


class VadParameters(BaseModel):
    """The engine's own voice-activity tuning, forwarded as written.

    The one model in this file whose door stays open, and it is open on
    purpose. `vad_parameters` has always been handed to
    `WhisperModel.transcribe` unread, the example documents one key of
    it, and faster-whisper's VAD takes several more that a deployment
    may already have written. Closing the hatch on the evidence of one
    documented key would make a running deployment's valid setting
    unreadable on upgrade, so the model declares what vinga vouches for
    and says here that everything else still travels.

    What travels is what was written: the mapping is dumped with
    `exclude_unset=True` on the way to the engine, so an operator's
    explicit values (nulls included) reach it and an injected default
    does not.
    """

    model_config = ConfigDict(extra="allow")

    min_silence_duration_ms: StrictInt | None = Field(
        default=None,
        description=(
            "How much silence ends a speech segment, in milliseconds. Any other key "
            "written here is passed to the engine's VAD unread, which is what this "
            "section is for."
        ),
    )


def _without_blank_spellings(data: object, unwritten: frozenset[str]) -> object:
    """One fragment with the listed options' blank spellings removed, so
    that writing one of them means nobody wrote the option.

    The mechanism both converted types need, in one place because it is
    one rule. Which keys a type lists is the type's own fact, read off
    the reader it replaced; what happens to a blank one is not.

    Dropping the key rather than substituting the value is what keeps
    one statement of each default: what a field holds when nobody wrote
    it is the field's own `default`, said once. It also keeps
    `model_fields_set` honest, which the nested sections depend on: an
    empty one must not travel to an engine or into a request body, and
    `exclude_unset` is what stops it.

    Deliberately not in any published schema. What a schema states is
    what an operator should write, and `device: ""` is not that; it is a
    spelling that used to work and still does.
    """
    if not isinstance(data, Mapping):
        return data
    return {
        key: value
        for key, value in data.items()
        if key not in unwritten or value not in (None, "")
    }


# The faster_whisper options whose absence had more than one spelling.
#
# Four ended the reader's ladder with `or <default>`, so an empty string
# and an explicit null both fell through to the default, and
# `vad_parameters` was read through a call that answered an empty
# mapping for a key that was not there. Listed rather than marked per
# field because what they have in common is a fact about the reader they
# replace, not a fact about any of them.
_WHISPER_BLANK_IS_UNWRITTEN = frozenset(
    {"model", "device", "compute_type", "language_detect", "vad_parameters"}
)


class FasterWhisperOptions(BaseModel):
    """The options the `faster_whisper` ASR type accepts.

    The decode options mirror `WhisperModel.transcribe` arguments of the
    same name and keep the engine's defaults when unset, with one
    exception: `beam_size` defaults to greedy decoding, because beam
    search buys little accuracy on short spoken commands and costs a
    multiple of the CPU time (#19).
    """

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _blank_reads_as_unwritten(cls, data: object) -> object:
        """A spelling of absence this type has always accepted, kept.

        The reader these fields replace ended four of them with
        `or <default>` and read `vad_parameters` through a call that
        answered an empty mapping for a missing key, so `model: ""`,
        `device: null` and `vad_parameters: null` were all ways of
        saying nothing and were all read as the default. A deployment
        that wrote one of them has a configuration that boots today, and
        this batch prices a break at zero only where the break is a
        typo being caught.

        What a blank means, and why it is dropped rather than
        substituted, is on `_without_blank_spellings`, which is the same
        rule the second converted type reads its own list through.
        """
        return _without_blank_spellings(data, _WHISPER_BLANK_IS_UNWRITTEN)

    model: StrictStr = Field(
        default="small",
        description=(
            "Whisper model size (tiny, base, small, medium, large-v3, or a Hugging "
            "Face model id); weights download at server startup."
        ),
    )
    language: StrictStr | None = Field(
        default=None,
        description=(
            "Language hint (ISO 639-1, such as sv or en); omit to auto-detect per "
            "utterance. Detection costs a constant encoder pass per utterance, "
            "several seconds of it on a small CPU."
        ),
    )
    device: StrictStr = Field(
        default="cpu",
        description=(
            "Where the engine runs inference, in faster-whisper's own vocabulary "
            "(cpu, cuda, auto)."
        ),
    )
    compute_type: StrictStr = Field(
        default="int8",
        description=(
            "The quantization the weights are loaded with, in faster-whisper's own "
            "vocabulary (int8, int8_float16, float16, float32)."
        ),
    )
    beam_size: StrictInt = Field(
        default=1,
        description=(
            "Greedy decoding by default: beam search costs a multiple of the CPU "
            "time and buys little accuracy on short spoken commands."
        ),
    )
    download_dir: StrictStr | None = Field(
        default=None,
        description=(
            "Where the model weights are cached; unset leaves the engine its own "
            "cache location."
        ),
    )
    cpu_threads: StrictInt = Field(
        default=0,
        description=(
            "Threads for CPU inference. The engine sizes its pool from the host's "
            "core count and ignores container CPU quotas, so inside a limit set this "
            "to the quota (0 keeps the engine default)."
        ),
    )
    vad_filter: StrictBool = Field(
        default=False,
        description=(
            "Strip non-speech inside the ASR call before decoding. Cuts both latency "
            "and hallucinations on silence-padded utterances; recommended on."
        ),
    )
    vad_parameters: VadParameters = Field(
        default_factory=VadParameters,
        description=(
            "Tuning for the engine's own voice-activity filter, forwarded to it as "
            "written. Only what the fragment sets is sent."
        ),
    )
    condition_on_previous_text: StrictBool = Field(
        default=True,
        description=(
            "Feeding each window's text into the next is the documented cause of "
            "repetition loops; false is the standard mitigation."
        ),
    )
    temperature: Numbers = Field(
        default=None,
        description=(
            "Fallback ladder for failed decodes, as one number or a non-empty list "
            "of them. The engine's six-step default can retry one bad utterance six "
            "times over; a short ladder bounds worst-case latency, which a voice UI "
            "feels."
        ),
    )
    language_detect: Literal["every_utterance", "once"] = Field(
        default="every_utterance",
        description=(
            "Detection scope. every_utterance detects fresh on each turn; once "
            "detects until a confident answer arrives and then reuses that language "
            "for the rest of the session, so later turns skip the detection pass."
        ),
    )
    language_fallback: StrictStr | None = Field(
        default=None,
        description=(
            "The language to decode in when a detection falls below the confidence "
            "floor; unset means the low-confidence detection is used as it is."
        ),
    )
    language_confidence_floor: Number = Field(
        default=0.6,
        description=(
            "Below this detection confidence, distrust the guess: use "
            "language_fallback instead when one is set, and never lock a session to "
            "it. Misdetections cluster at low confidence, and a wrong language costs "
            "extra decode time on top of being wrong."
        ),
    )


# The one combination the API itself calls invalid, said where it is
# written.
#
# Two sentences rather than one repeated at two locations, because a
# model-level validator's error is located at the MODEL: the rendering
# puts no field name in front of these lines, so each has to name its
# own field, exactly as the reserved-passthrough rule above does. The
# first carries the rule and the second carries the guidance the issue
# asks for, which is which model wants which form.
#
# Models are named one by one rather than by family, and that is a
# measurement rather than a style. Three were tested against the live
# endpoint on 2026-09-13: `gpt-transcribe` accepted `languages`,
# `whisper-1` and `gpt-4o-mini-transcribe` each answered 400 with a
# message of its own, and all three refused a request naming both.
# `gpt-4o-transcribe` and every compatible endpoint were not tested, so
# nothing here speaks for them.
BOTH_LANGUAGES_RULE = (
    '"language" and "languages" cannot both be set: every model measured answers '
    "400 to a request naming both, so an entry writing both would apply cleanly "
    "and fail on the first real transcription"
)

LANGUAGES_MODEL_RULE = (
    '"languages" is the form gpt-transcribe takes, and it is the one model '
    'measured to accept it; whisper-1 and gpt-4o-mini-transcribe answered 400 to '
    'it and take "language" instead'
)


class OpenaiAsrOptions(BaseModel):
    """The options the `openai` ASR type accepts.

    Six knobs and a door that stays shut, which is what the
    `OptionsReader` ladder in `providers/openai_asr.py` had: every key
    that builder did not read ended its build with `finish()` naming it.

    Two rules are deliberately NOT here, and both live in the builder
    because both are facts about the endpoint rather than about a value.
    `base_url` has to be a URL with a scheme and a host, which
    `providers/openai_endpoint.py` decides for all three types speaking
    this dialect; and `temperature` has to be inside OpenAI's own range
    only when the endpoint IS OpenAI, which is the same module's
    question. This file weighs pydantic and `config.models` and nothing
    else, so it cannot ask it, and restating those URL rules here would
    make this the second home for them.
    """

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _one_language_or_a_set_of_them(self) -> "OpenaiAsrOptions":
        """The two ways of describing what will be spoken, and the rule
        that an entry writes one of them.

        The API's own rule rather than this repository's taxonomy: a
        request carrying both answers 400 on every model measured, and
        `build` speaks to nothing, so an entry writing both applies
        cleanly and fails on the first real transcription of a
        conversation, which is the failure no log explains. Refused
        where it is written instead.

        Raised as `FieldProblemsError` for the reason the reserved-name
        rule above is: a model-level validator's error is located at the
        model, and this is the one place that knows both fields are
        involved, so several problems arrive as one error and the names
        reach the pointers as well as the sentences.

        What counts as set is what was WRITTEN, which is the question a
        written entry can answer. `language: ""` names no language on
        the wire, and the request-time rules below read the value rather
        than the key for exactly that reason; but two options written on
        one entry is one of them too many whatever either holds, and
        the remedy is the same line either way.
        """
        if self.language is not None and self.languages is not None:
            raise FieldProblemsError(
                [
                    FieldProblem(json_pointer(("language",)), BOTH_LANGUAGES_RULE),
                    FieldProblem(json_pointer(("languages",)), LANGUAGES_MODEL_RULE),
                ]
            )
        return self

    # OpenAI's current transcription model, and the one of the three that
    # says which language it heard. The gpt-4o pair it replaced as the
    # default reports none ever and `whisper-1` reports one only in a
    # format this provider does not ask for, so on any of those the
    # `heard` event and the conversation record carry no language at
    # all. That is the one thing an entry naming
    # `gpt-4o-mini-transcribe` gives up: everything else about that
    # model, its accuracy and its per-audio-token billing included, is
    # what a deployment had before this default moved.
    #
    # This model is billed by duration rather than by audio token, which
    # is the unit the `asr` span already reports, and published at
    # $0.0045 per minute of audio (read 2026-09-13).
    #
    # Declared here and nowhere else. The builder used to keep a
    # `DEFAULT_MODEL` constant and read the option through it, and two
    # statements of one default is the version of that bug where the
    # stale one looks authoritative.
    model: StrictStr = Field(
        default="gpt-transcribe",
        description=(
            "The transcription model, in OpenAI's own vocabulary. The default is "
            "the one that reports which language it heard; gpt-4o-transcribe and "
            "gpt-4o-mini-transcribe report none, and whisper-1 is the same Whisper "
            "V2 as the local engine, at roughly twice the latency. A self-hosted "
            "endpoint serves its own names and should be told one here."
        ),
    )
    # `https://api.openai.com/v1`, which is `openai_endpoint`'s own
    # constant and cannot be imported here for the reason the docstring
    # gives. Stated as the string and pinned against that constant by a
    # case in `test_providers_openai_asr.py`, which is on the side that
    # may import both, exactly as the elevenlabs timeout is.
    base_url: StrictStr = Field(
        default="https://api.openai.com/v1",
        description=(
            "The transcription endpoint. Any server implementing "
            "/v1/audio/transcriptions works here, the same way openai_compatible "
            "opens the LLM stage to local models; a keyless self-hosted one can "
            "leave api_key_env out. This is also what decides whether the audio "
            "leaves the host, so the type cannot declare its own reach."
        ),
    )
    language: StrictStr | None = Field(
        default=None,
        description=(
            "Spoken language (ISO 639-1, such as sv or en). Set it for any "
            "deployment that is not English: detection happens inside the model at "
            "no measurable cost, but far-field microphone audio through Opus gives "
            "it far less to go on than clean audio does."
        ),
    )
    # The plural, for a household that speaks more than one. Only
    # `gpt-transcribe` was measured to accept it, and the other two
    # models tested answered 400, which is the endpoint's decision to
    # make and not one this file second-guesses with a table: what this
    # model owns is the refusal of the combination the API itself calls
    # invalid, which is a fact about the request rather than about any
    # model's current feature list.
    languages: Languages = Field(
        default=None,
        description=(
            "The languages spoken here, when there is more than one (ISO 639-1, "
            "such as [sv, en]). Accepted by gpt-transcribe and refused by whisper-1 "
            "and gpt-4o-mini-transcribe, which take language instead; the two "
            "options cannot both be set. A list of one is a way of writing "
            "language, and reports the language heard no more than language does; "
            "a list of two or more leaves the model a choice, and what it chose is "
            "reported."
        ),
    )
    prompt: StrictStr | None = Field(
        default=None,
        description=(
            "Words the transcriber should expect (names, places, the assistant's "
            "own name), and not the agent's instruction, which is the agent's own "
            "entry. Keep it to plain vocabulary: on short or low-content audio the "
            "model hands this string back as the transcript instead of hearing "
            "anything."
        ),
    )
    temperature: OptionalNumber = Field(
        default=None,
        description=(
            "Decoding temperature, which OpenAI itself takes between 0.0 and 1.0. "
            "Raise it only to loosen a decode that is stuck; unset leaves the API "
            "its own default."
        ),
    )
    # 30 seconds is `providers/kit.py`'s default patience, and it cannot
    # be imported here either: the kit speaks httpx. Stated as the
    # number and pinned against the kit's constant beside the base URL.
    timeout_s: Number = Field(
        default=30.0,
        description=(
            "Seconds before a transcription request is abandoned, and a real bound "
            "because the client's own retries are off: the SDK would otherwise try "
            "a failed request three times while the user waits for an answer."
        ),
    )


class VoiceSettings(BaseModel):
    """The vendor's own voice tuning, forwarded as written.

    Five keys and no more, which is the contract the type had before it
    had a model: `read_voice_settings` listed exactly these and refused
    anything else, on the stated grounds that a typo the API silently
    ignores is a knob that never took effect. The door stays shut here
    for that reason, and that is the difference from `VadParameters`,
    the other nested model, whose keys are read by an engine that takes
    more of them than vinga documents.

    What travels is what was written: the mapping is dumped with
    `exclude_unset=True` into the request body, so an operator's explicit
    values reach the API and an injected default does not.
    """

    model_config = ConfigDict(extra="forbid")

    stability: OptionalNumber = Field(
        default=None,
        description="Higher is more monotone and more predictable.",
    )
    similarity_boost: OptionalNumber = Field(
        default=None,
        description="Higher holds the synthesis closer to the reference voice.",
    )
    style: OptionalNumber = Field(
        default=None,
        description="Style exaggeration, applied to voices that carry one.",
    )
    speed: OptionalNumber = Field(
        default=None,
        description="A multiplier around 1.0, which the API caps at 0.7 to 1.2.",
    )
    use_speaker_boost: StrictBool | None = Field(
        default=None,
        description=(
            "Sharpens the resemblance to the reference speaker, and costs latency."
        ),
    )


# The elevenlabs option whose absence had more than one spelling, and it
# is one rather than five.
#
# The list is read off the reader this model replaces, exactly as the
# whisper one is, and that reader was written differently: `model` and
# `output_format` were `string(key, default)` with no `or <default>`
# after them, so a blank was never a way of writing nothing there. It
# travelled, which for `model` meant an empty model id in the request
# and for `output_format` meant a refusal from the format rule.
# `voice_settings` is the exception, and it is the same call
# `vad_parameters` went through: `mapping()` answered `{}` for a key
# that was not there, so a null section was a section nobody wrote.
_ELEVENLABS_BLANK_IS_UNWRITTEN = frozenset({"voice_settings"})


class ElevenlabsOptions(BaseModel):
    """The options the `elevenlabs` TTS type accepts.

    Every one of them is passed to the vendor's streaming endpoint, whose
    reference documents all of them. The two rules this type has of its
    own are here rather than in the builder: a voice id is required
    because there is nothing to synthesize with without one, and the
    output format has to be a `pcm_<rate>` because the stage streams raw
    PCM and the rate the request asks for is the rate the session
    resamples from.
    """

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _blank_reads_as_unwritten(cls, data: object) -> object:
        """`voice_settings: null` is a section nobody wrote, which is
        what `mapping()` made it and what the builder then acted on: it
        put the key in the request body only when the mapping was
        truthy, so a null section and a missing one produced the same
        request. That still holds, and `exclude_unset` is now what holds
        it."""
        return _without_blank_spellings(data, _ELEVENLABS_BLANK_IS_UNWRITTEN)

    voice_id: Nonblank = Field(
        description=(
            "Voice id from your ElevenLabs voice library: the id, not the display "
            "name, and account-specific even for the stock voices."
        ),
    )
    model: StrictStr = Field(
        default="eleven_flash_v2_5",
        description=(
            "The synthesis model. The default is the low-latency one (~75 ms to "
            "first byte, 32 languages); eleven_multilingual_v2 sounds better and "
            "answers slower, which a conversation feels."
        ),
    )
    output_format: PcmFormat = Field(
        default="pcm_24000",
        description=(
            "Audio asked of the API. Only the pcm_<rate> formats work here, since "
            "the stage streams raw PCM; the default matches the rate devices are "
            "spoken at, so nothing is resampled. pcm_44100 and up need a paid "
            "ElevenLabs tier."
        ),
    )
    language_code: StrictStr | None = Field(
        default=None,
        description=(
            "Pin the spoken language (ISO 639-1) instead of letting the model infer "
            "it from the text."
        ),
    )
    voice_settings: VoiceSettings = Field(
        default_factory=VoiceSettings,
        description=(
            "Voice tuning, passed to the API as given. Only what the fragment sets "
            "is sent."
        ),
    )
    # 30 seconds is what `providers/kit.py` calls a request's default
    # patience, and it cannot be imported here: the kit speaks httpx, and
    # this module is on three paths that load no client library. Stated
    # as the number and pinned against the kit's constant by a case in
    # `test_providers_elevenlabs.py`, which is on the side that may
    # import both.
    timeout_s: Number = Field(
        default=30.0,
        description="Seconds before a synthesis request is abandoned.",
    )

    @property
    def sample_rate(self) -> int:
        """The rate the chosen format produces, which is what the stage
        passes downstream.

        A property rather than a field: it is not an option, it is the
        one thing `output_format` means to everything past the request.
        Safe to read off the string because the field's own validator is
        what admitted the string, so the shape is decided before this
        can be called.
        """
        return int(self.output_format.removeprefix("pcm_"))


# The fields the openai_compatible type composes for every request, and
# therefore the names a passthrough key may not take.
#
# The door the model below keeps open is a door into the request body,
# and a body has fields of its own: `model` is the entry's model,
# `messages` is the conversation so far, `stream` is what makes the call
# a stream at all, `max_tokens` is the declared cap (composed when the
# entry writes one and left out when it does not, which is a decision
# about the request rather than about this set), and the tools pair
# is what the session is about to answer. A key by one of those names
# would not be a server-specific option, it would be a rewrite of the
# request, and the SDK's own `extra_body` merges OVER what the caller
# set rather than under it. So the set is stated once, here, refused
# when the entry is written and dropped again at the seam that builds
# the provider.
#
# Naming which one collided is safe where naming a key an operator
# invented is not: these seven words are this repository's own, they are
# published in the schema on the model below, and a refusal that says
# which was written tells an operator what to remove without repeating
# anything they wrote.
RESERVED_REQUEST_FIELDS = frozenset(
    {"model", "messages", "max_tokens", "stream", "stream_options", "tools", "tool_choice"}
)

RESERVED_RULE = (
    "is a field this type composes for every request, so it cannot also be passed "
    "through as an option; remove it from the entry"
)


class OpenaiCompatibleOptions(BaseModel):
    """The options the `openai_compatible` LLM type accepts, and the one
    door in this file that stays open to an operator: a key this model
    does not declare is kept and forwarded into the outgoing request.

    The type exists to reach a server this repository has never seen.
    Ollama, LM Studio, llama.cpp, vLLM and every gateway in front of one
    speak the chat-completions dialect and each takes parameters no
    other does, so a model that enumerated the dialect would be a list
    of one vendor's fields presented as the contract of all of them.
    That is the reason `extra="allow"` is here and nowhere else among
    the closed types.

    An accepted key takes EFFECT, which is the half that makes the hatch
    worth having. The extras ride into the request body as the API's own
    escape door takes them, merged UNDER the fields this type composes
    for every request: `top_p` reaches the server, and nothing written
    here can rewrite the conversation, the model, the stream or the
    tools the session is about to answer. A passthrough key naming one
    of those is refused when the entry is written, with the name said
    out loud, and the sentence below this one says which names those
    are.

    What the hatch does not open is a way past the rules every provider
    entry is held to. An extra is still walked for an inline secret and
    still refused if it is a URL carrying a credential, because those
    rules read the fragment rather than the model.
    """

    model_config = ConfigDict(extra="allow")

    @classmethod
    def refused_passthrough(cls) -> tuple[str, ...]:
        """The reserved names a key written here could actually take.

        `RESERVED_REQUEST_FIELDS` states which fields the request
        composes; two of them are options this model declares, so a key
        by one of those names is the option rather than a passthrough
        and cannot collide with anything. What is left is the set a
        fragment can break, and it is derived rather than written down
        twice: the validator refuses exactly these, the published schema
        excludes exactly these, and the sentence the schema carries
        names exactly these.
        """
        return tuple(sorted(RESERVED_REQUEST_FIELDS - set(cls.model_fields)))

    @classmethod
    def __get_pydantic_json_schema__(
        cls, core_schema: CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        """The open door, said in the vocabulary a document has for one.

        `additionalProperties: true` says a key may be written and stops
        there, so a client generating from it would write `messages` and
        meet a refusal the document never mentioned. `propertyNames`
        constrains what a key may be CALLED, which is the shape this
        rule has: every name is legal except the ones the request
        composes for itself. The prose says the same thing in words,
        from the same tuple, because a reader of the reference sees the
        description and a code generator sees the keyword.
        """
        schema = handler(core_schema)
        # A field that is optional without being nullable has no default
        # VALUE, and pydantic has nowhere but the default slot to keep
        # "nothing was written" in, so what it derives is an integer
        # field defaulting to null: a schema whose own default its type
        # forbids, and an invitation to a generated client to send it.
        # Taken back out here rather than papered over at the reader:
        # not required and no default is exactly what the field is, and
        # the description says what omitting it does (#444).
        schema.get("properties", {}).get("max_tokens", {}).pop("default", None)
        refused = list(cls.refused_passthrough())
        schema["propertyNames"] = {"not": {"enum": refused}}
        schema["description"] = (
            f"{schema.get('description', '')}\n\n"
            f"Any key not listed here is passed through to the endpoint as a "
            f"top-level field of the chat completions request body. These names "
            f"cannot be passed through, because this type composes them for every "
            f"request: {', '.join(refused)}."
        ).strip()
        return schema

    @model_validator(mode="after")
    def _no_request_field_is_passed_through(self) -> "OpenaiCompatibleOptions":
        """A passthrough key may not be one of the request's own fields.

        Raised as `FieldProblemsError` rather than as a bare ValueError
        so the name reaches the pointer as well as the sentence: a
        model-level validator's error is located at the model, and this
        is the one place that knows which key it was about.
        """
        taken = sorted(set(self.model_extra or {}) & set(self.refused_passthrough()))
        if taken:
            raise FieldProblemsError(
                [
                    FieldProblem(json_pointer((name,)), f'"{name}" {RESERVED_RULE}')
                    for name in taken
                ]
            )
        return self

    base_url: Nonblank = Field(
        description=(
            "The endpoint's OpenAI-compatible base URL, such as "
            "http://localhost:11434/v1 for a local Ollama; pointing it at "
            "api.openai.com works too. Required, because it is what decides which "
            "server this entry speaks to and whether session data leaves the host."
        ),
    )
    model: Nonblank = Field(
        description=(
            "The model to ask for, in the endpoint's own vocabulary (qwen3:8b on "
            "Ollama, an OpenAI model id on api.openai.com)."
        ),
    )
    # No default, and the absence is the decision (#444). This type
    # reaches a server this repository has never seen, and a cap it
    # composes uninvited is a field that server may not take: OpenAI's
    # current models refuse `max_tokens` outright and answer 400, which
    # made every entry pointing at them unusable however it was written.
    # An endpoint's own default is a better number than one chosen here
    # for all of them, and an operator who wants a cap writes the one
    # their endpoint spells, this field or `max_completion_tokens`
    # through the door beside it.
    # Optional and not nullable, which are two different things and the
    # reason the annotation is the bare `StrictInt` while the field
    # holds None when nothing was written. Absent is a state of the
    # fragment; null is a value, and this type has no blank spelling of
    # an absent option (`base_url` and `model` refuse a blank as loudly
    # as a missing key). A nullable annotation published `int | null`
    # with a null default in all three generated references, so a client
    # generated from the schema could legitimately send the one value
    # the model then answers 422 to. `StrictInt` refuses null itself,
    # and `__get_pydantic_json_schema__` above takes the null default
    # back out of what is published, so what a document promises and
    # what the model accepts are the same thing again.
    #
    # None is therefore this module's private spelling of "nothing was
    # written" rather than a value an operator can produce, and the one
    # reader of it is the builder, which leaves the field out of the
    # request when it is None.
    max_tokens: StrictInt = Field(
        default=None,
        description=(
            "The cap on one reply's length, in tokens. Left out, no cap is sent and "
            "the endpoint's own default applies. An endpoint of the current OpenAI "
            "family refuses this field and takes max_completion_tokens instead, "
            "which is written here like any other passthrough key."
        ),
    )


class OptionsRefused(Exception):
    """One entry's options, refused, in the two renderings a refusal
    needs and in neither of the two a leak needs.

    Its `str` is the sentence, built from the field names the model
    declared and the rules they broke; `problems` is the same walk as
    JSON Pointers, which is what a form acts on. What it does not carry
    is the `ValidationError` it was built from, and that is the whole
    reason this type exists rather than the pydantic one travelling: an
    error's `errors()` hold the rejected input, and a rejected option is
    exactly where a pasted credential lands.

    Each caller wraps it in the refusal of its own surface: a
    `ConfigError` at the write, a `StorageError` on read-back, a
    `ProviderError` at build time. None of them chains this one, for the
    same reason.
    """

    def __init__(self, sentence: str, problems: tuple[FieldProblem, ...]) -> None:
        self.problems = problems
        super().__init__(sentence)


# The provider types, and the one place they are written down
#
# Two facts per type, and they are the two every surface in this
# repository asks about one: where the thing that builds it lives, and
# what it accepts. Both live here, in one table, because the alternative
# has now been tried twice and failed the same way each time. A factory
# table in the provider package with an options mapping beside it is two
# stage-and-type topologies held together by a test, which is the design
# guide's pending bug; putting the models here and leaving the factories
# there was the same shape with a shorter bridge. So there is one table,
# and both halves of a type are one entry of it.
#
# What makes that possible without dragging an engine behind it is that
# a factory is NAMED here rather than imported: `module` and `attribute`
# are strings, resolved by `providers/registry.py` at the moment a
# provider is constructed, which is the same laziness the per-type
# factory functions used to spell out one closure at a time. Importing
# this module therefore costs pydantic and `config.models`, exactly as
# it did when it held models alone, and the three pins that depend on
# that are undisturbed.
_IMPLEMENTATIONS = "vinga_server.providers"


@dataclass(frozen=True)
class ProviderType:
    """One provider type: what builds it, and what it accepts.

    `module` is a name under `vinga_server.providers` and `attribute` is
    the callable in it, so nothing is imported until something is built.
    `extra` is the optional dependency whose absence has to be explained
    rather than raised as an ImportError from the middle of a request,
    and None for a type the core install can always build. `options` is
    the model the type declares, and None for one that declares none,
    which is the ordinary case while the conversion runs type by type
    (#88).
    """

    module: str
    attribute: str = "build"
    options: type[BaseModel] | None = None
    extra: str | None = None

    @property
    def path(self) -> str:
        """The importable name of the module holding the factory."""
        return f"{_IMPLEMENTATIONS}.{self.module}"


# Keyed by stage and then by type because that is how a provider is
# addressed: `openai` is an ASR type and a TTS type, `mock` is all four,
# and a type name on its own addresses nothing in particular.
PROVIDER_TYPES: dict[str, dict[str, ProviderType]] = {
    "llm": {
        "mock": ProviderType("mock", "build_llm"),
        "anthropic": ProviderType("anthropic_llm"),
        "openai_compatible": ProviderType("openai_llm", options=OpenaiCompatibleOptions),
    },
    "asr": {
        "mock": ProviderType("mock", "build_asr"),
        "faster_whisper": ProviderType(
            "faster_whisper", options=FasterWhisperOptions, extra="faster-whisper"
        ),
        # No extra to guard, for the reason the openai TTS type has none:
        # the openai client is a core dependency and transcription is a
        # method on it.
        "openai": ProviderType("openai_asr", options=OpenaiAsrOptions),
    },
    "tts": {
        "mock": ProviderType("mock", "build_tts"),
        # No extra to guard: the provider speaks the API over httpx,
        # which the core install already carries.
        "elevenlabs": ProviderType("elevenlabs_tts", options=ElevenlabsOptions),
        # No extra to guard: the openai client is a core dependency,
        # carried for the openai_compatible LLM type, and speech is a
        # method on it.
        "openai": ProviderType("openai_tts"),
        "piper": ProviderType("piper_tts", extra="piper"),
    },
    "vad": {
        "mock": ProviderType("mock", "build_vad"),
        "silero": ProviderType("silero"),
    },
}


def provider_type(stage: str, type_name: str) -> ProviderType | None:
    """What the table says about one stage's type, or None for a stage
    or a type it does not have."""
    return PROVIDER_TYPES.get(stage, {}).get(type_name)


def options_model(stage: str, type_name: str) -> type[BaseModel] | None:
    """The options model one stage's type declares, or None for a type
    that declares none.

    A type with no model is the ordinary case while the conversion runs
    type by type: the caller falls back to what it did before.
    """
    declared = provider_type(stage, type_name)
    return declared.options if declared is not None else None


def declared_options() -> tuple[tuple[str, str, type[BaseModel]], ...]:
    """Every declared model as stage, type and model, grouped by stage
    in the pipeline's own order and by type name under it.

    The enumeration every rendering reads: the reference's per-type
    tables, the OpenAPI components, the `set provider` epilog and the
    sentence that says which types are declared. Ordered here rather
    than at each of them, because four renderings sorting for themselves
    is four chances for a committed document to move on a dictionary's
    insertion order.
    """
    return tuple(
        (stage, type_name, declared.options)
        for stage in PROVIDER_STAGES
        for type_name, declared in sorted(PROVIDER_TYPES.get(stage, {}).items())
        if declared.options is not None
    )


def component_name(stage: str, type_name: str) -> str:
    """What one type's options are called where a document names its
    shapes: `AsrFasterWhisperOptions`.

    Built from the pair rather than from the class, so the name a reader
    meets carries the two things that address the model and cannot
    collide across stages the way a class name could.
    """
    words = (stage, *type_name.split("_"))
    return "".join(word[:1].upper() + word[1:] for word in words) + "Options"


def checked_options(
    headline: str, stage: str, type_name: str, options: Mapping[str, object]
) -> BaseModel | None:
    """One entry's options as its type's own model, or None where the
    type declares none.

    The one gate. The write funnel, the read-back and the build path all
    call this, so what a stored entry may hold and what a written one
    may hold cannot come apart, and there is one place where the
    sentence an operator reads is composed.

    `headline` is the first line of that sentence, which is the calling
    surface's business: a write says `invalid providers.asr.ears:`, a
    read-back says the row cannot be read. Under it comes one indented
    line per problem, naming the field and the rule.

    Built inside the handler and raised outside it, the rule every
    refusal in this repository is built by: an exception raised inside
    an `except` arm keeps the one being handled as its `__context__`,
    and a `ValidationError`'s errors carry the whole rejected mapping.
    """
    model = options_model(stage, type_name)
    return None if model is None else validated(headline, model, options)


def validated(
    headline: str, model: type[BaseModel], options: Mapping[str, object]
) -> BaseModel:
    """One mapping through one model, refused in this repository's
    words.

    Taken as the model rather than looked up, for the caller that has
    already resolved it: the provider registry holds the model on the
    registration it is about to build with, and resolving it a second
    time from a stage and a type would be a second lookup that can
    answer differently from the first.
    """
    sentence: str | None = None
    problems: tuple[FieldProblem, ...] = ()
    entry: BaseModel | None = None
    try:
        entry = model.model_validate(dict(options))
    except ValidationError as exc:
        sentence, problems = validation_problems(headline, model, exc)
    if entry is None:
        raise OptionsRefused(str(sentence), problems)
    return entry


__all__ = [
    "PROVIDER_TYPES",
    "NONBLANK_PATTERN",
    "NONBLANK_RULE",
    "NUMBERS_RULE",
    "NUMBER_RULE",
    "PCM_FORMAT_PATTERN",
    "PCM_FORMAT_RULE",
    "RESERVED_REQUEST_FIELDS",
    "RESERVED_RULE",
    "ElevenlabsOptions",
    "FasterWhisperOptions",
    "OpenaiAsrOptions",
    "OpenaiCompatibleOptions",
    "OptionsRefused",
    "VadParameters",
    "VoiceSettings",
    "checked_options",
    "ProviderType",
    "component_name",
    "declared_options",
    "options_model",
    "provider_type",
    "validated",
]
