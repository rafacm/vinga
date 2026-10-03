"""Stored turns in, messages out, with a budget in between.

Input to output and no database, which is what the module is shaped for:
the thread store hands it rows, so everything it decides can be asserted
by writing turns down and reading messages back.

What the assertions are about is the three properties a rebuilt context
has to have. It alternates roles and opens with the user, whatever
shape the stored turns are in, because that is what a provider is
willing to be handed. It ends with the newest turn, because that is
what a conversation is resumed into. And it says what it could not
bring: the turns it could not read anywhere in the thread, and whether
there were more of them than the budget had room for.

The section on tool exchanges is #599's: a turn's calls come back as
the rounds the session kept, priced at the largest form a later request
can send them in. The last two sections are the recap's. A checkpoint
is a head that truncation may not reach, and the range a rebuilt
context actually read is what a checkpoint is allowed to claim it
covers.

Sizes are written as characters and read as tokens through
`ESTIMATED_CHARS_PER_TOKEN`, so a budget in this file is arithmetic
rather than a guess about a tokenizer.
"""

import json
from typing import Any

from vinga_server.conversations.hydration import (
    ESTIMATED_CHARS_PER_TOKEN,
    MILESTONE_NOTE,
    hydrated,
)
from vinga_server.conversations.records import StoredCall, StoredTurn
from vinga_server.providers import Turn
from vinga_server.runtime.history import (
    CLEARED_NOTE,
    DEGRADED_END,
    DEGRADED_PREFIX,
    as_sent,
)

# A budget nothing in this file reaches, for the cases that are not
# about truncation.
PLENTY = 6000


def said(index: int, size: int = 8) -> StoredTurn:
    """One whole turn of a known size, distinguishable by its index, and
    carrying the row id a recap would record it by."""
    return StoredTurn(
        id=index, heard=f"{index}" * size, reply=f"r{index}" * (size // 2)
    )


def roles(turns) -> list[str]:
    return [turn.role for turn in turns]


def texts(turns) -> list[str]:
    return [turn.content for turn in turns]


def test_a_turn_becomes_the_two_messages_it_was() -> None:
    answer = hydrated([StoredTurn(heard="what is the time", reply="Ten past.")], PLENTY)

    assert roles(answer.turns) == ["user", "assistant"]
    assert texts(answer.turns) == ["what is the time", "Ten past."]
    assert (answer.rendered, answer.skipped, answer.over_budget) == (1, 0, False)


def test_the_thread_comes_back_oldest_first() -> None:
    """Read backwards from the newest and answered forwards, because a
    conversation is written in one direction whatever order it was
    chosen in."""
    answer = hydrated([said(1), said(2), said(3)], PLENTY)

    assert roles(answer.turns) == ["user", "assistant"] * 3
    assert texts(answer.turns)[0] == "1" * 8
    assert texts(answer.turns)[-1] == "r3" * 4


def test_a_turn_with_no_stored_text_is_a_gap_and_is_counted() -> None:
    """Text-off keeps the turn and none of the words in it. What that
    leaves is a hole, and the count is what lets a resume say the record
    is partial rather than pretending it is whole."""
    answer = hydrated([said(1), StoredTurn(), said(2)], PLENTY)

    assert roles(answer.turns) == ["user", "assistant"] * 2
    assert (answer.rendered, answer.skipped) == (2, 1)


def test_a_thread_with_no_text_at_all_reports_every_turn_as_a_gap() -> None:
    """The walk does not stop at a hole, which is what makes this
    answer the whole count rather than one."""
    answer = hydrated([StoredTurn(), StoredTurn(), StoredTurn()], PLENTY)

    assert answer.turns == ()
    assert (answer.rendered, answer.skipped, answer.over_budget) == (0, 3, False)


def test_a_turn_that_was_heard_and_never_answered_is_a_gap() -> None:
    """The shape a failed reply leaves: the utterance was recorded where
    `heard` is emitted and the reply provider then failed, so the row
    holds half a turn.

    Rendering that half would put two user messages in a row, which is
    the one thing the alternation rule exists to prevent and which some
    vendors refuse outright. The whole partial turn is a hole instead,
    counted like any other."""
    answer = hydrated(
        [
            StoredTurn(heard="what is the weather", reply="Cloudy."),
            StoredTurn(heard="and tomorrow"),
            StoredTurn(heard="are you there", reply="I am."),
        ],
        PLENTY,
    )

    assert roles(answer.turns) == ["user", "assistant", "user", "assistant"]
    assert texts(answer.turns) == [
        "what is the weather",
        "Cloudy.",
        "are you there",
        "I am.",
    ]
    assert (answer.rendered, answer.skipped) == (2, 1)


def test_an_answer_with_nothing_heard_joins_the_answer_before_it() -> None:
    """The shape a move leaves on the thread it lands on: the round the
    move seeded is a turn with an answer and no utterance, because what
    the user said was said on the thread they were moved off.

    It is not a hole, since nothing about it was lost, and it is not a
    message of its own, since two assistant messages in a row is the
    same refusal as two user ones. It is joined onto the answer before
    it, which is what it was: two things said one after the other with
    nothing from the user in between."""
    answer = hydrated(
        [
            StoredTurn(heard="what is out there", reply="Galaxies."),
            StoredTurn(reply="We were talking about galaxies."),
            StoredTurn(heard="go on", reply="Billions of them."),
        ],
        PLENTY,
    )

    assert roles(answer.turns) == ["user", "assistant", "user", "assistant"]
    assert texts(answer.turns)[1] == "Galaxies.\nWe were talking about galaxies."
    # Nothing was lost, so nothing is reported as a gap, and the joined
    # turn is one of the turns this answer rebuilt.
    assert (answer.rendered, answer.skipped) == (3, 0)


def test_an_answer_with_nothing_before_it_is_not_led_with() -> None:
    """A thread that opens with the greeting a move was answered with
    has nothing for that greeting to follow. The first message a
    provider is handed is the user's, so the history opens on the
    utterance after it rather than on an answer to nobody."""
    answer = hydrated(
        [
            StoredTurn(reply="Starting fresh. What shall we talk about?"),
            StoredTurn(heard="the moon", reply="It is up there."),
        ],
        PLENTY,
    )

    assert roles(answer.turns) == ["user", "assistant"]
    assert texts(answer.turns) == ["the moon", "It is up there."]
    assert (answer.rendered, answer.skipped) == (1, 0)


def test_gaps_are_counted_over_the_whole_thread_and_not_the_window() -> None:
    """What the count answers is whether the record has holes in it,
    which is a fact about the thread rather than about the budget.

    Ordered as the reviewer's case is: a hole, then a turn too big to
    keep beside the newest, then the newest. The walk stops at the
    oversized turn, so a count taken as the walk went would report no
    gaps at all and the resume would claim a whole record it does not
    have."""
    units = [StoredTurn(), said(1, size=400), said(2)]

    answer = hydrated(units, _cost(units[2]))

    assert texts(answer.turns) == ["2" * 8, "r2" * 4]
    assert (answer.rendered, answer.skipped, answer.over_budget) == (1, 1, True)


def test_truncation_drops_whole_units_oldest_first() -> None:
    """The unit is the turn. A budget that fits two of three leaves the
    two newest whole, never a reply without the utterance it answered."""
    units = [said(1), said(2), said(3)]
    room = 2 * _cost(units[0])

    answer = hydrated(units, room)

    assert roles(answer.turns) == ["user", "assistant"] * 2
    assert texts(answer.turns)[0] == "2" * 8
    assert (answer.rendered, answer.skipped, answer.over_budget) == (2, 0, True)


def test_a_backlog_that_fits_exactly_is_not_over_budget() -> None:
    """The boundary is inclusive: a thread the budget has exactly room
    for is a thread that fit."""
    units = [said(1), said(2)]

    answer = hydrated(units, _cost(units[0]) + _cost(units[1]))

    assert (answer.rendered, answer.over_budget) == (2, False)


def test_one_token_less_than_exact_drops_the_oldest() -> None:
    units = [said(1), said(2)]

    answer = hydrated(units, _cost(units[0]) + _cost(units[1]) - 1)

    assert (answer.rendered, answer.over_budget) == (1, True)


def test_the_newest_unit_is_taken_even_when_it_alone_is_too_big() -> None:
    """An empty resume is a worse answer than an over-budget one, and
    the budget is an estimate to begin with. The flag is what says so.
    """
    units = [said(1), said(2, size=400)]

    answer = hydrated(units, 8)

    assert texts(answer.turns) == ["2" * 400, "r2" * 200]
    assert (answer.rendered, answer.over_budget) == (1, True)


def test_gaps_between_kept_units_do_not_spend_the_budget() -> None:
    """A hole costs nothing, so a thread recorded half under text-off
    is rebuilt as far back as its words reach."""
    units = [said(1), StoredTurn(), said(2)]

    answer = hydrated(units, _cost(units[0]) + _cost(units[2]))

    assert (answer.rendered, answer.skipped, answer.over_budget) == (2, 1, False)


def test_an_empty_thread_hydrates_to_nothing() -> None:
    assert hydrated([], PLENTY) == hydrated([], 512)


def test_the_same_rows_answer_the_same_way_twice() -> None:
    """Deterministic, because a resume that read differently on a
    Tuesday would be a conversation nobody could reason about."""
    units = [said(index) for index in range(6)]

    assert hydrated(units, 40) == hydrated(units, 40)


# A turn's tool exchanges (#599)


def row(
    position: int,
    name: str | None = "remember",
    result: str | None = "Saved.",
    source: str = "builtin",
    **fields: Any,
) -> StoredCall:
    """One `tool_invocations` row as the store reads it back. Arguments
    default to one naming the position, so two calls of one tool can be
    told apart."""
    fields.setdefault("arguments", {"text": f"fact {position}"})
    return StoredCall(position=position, source=source, name=name, result=result, **fields)


def calls_of(turns) -> list[tuple[str, str, dict[str, Any]]]:
    return [(one.id, one.name, one.arguments) for turn in turns for one in turn.tool_calls]


def results_of(turns) -> list[tuple[str, str]]:
    return [(one.tool_call_id, one.content) for turn in turns for one in turn.tool_results]


def test_a_turns_calls_come_back_as_the_rounds_they_were_made_in() -> None:
    """Two rounds of two calls, in the order the store wrote them: each
    round is an assistant turn asking and a tool turn answering, before
    the reply, and every call and result carries the id the session
    would have minted for it."""
    answer = hydrated(
        [
            StoredTurn(
                id=1,
                heard="save four things",
                reply="All four saved.",
                calls=(
                    row(0, arguments={"text": "a"}, result="Saved a."),
                    row(1, arguments={"text": "b"}, result="Saved b."),
                    row(0, arguments={"text": "c"}, result="Saved c."),
                    row(1, arguments={"text": "d"}, result="Saved d."),
                ),
            )
        ],
        PLENTY,
    )

    assert roles(answer.turns) == ["user", "assistant", "tool", "assistant", "tool", "assistant"]
    assert [len(turn.tool_calls) for turn in answer.turns] == [0, 2, 0, 2, 0, 0]
    assert calls_of(answer.turns) == [
        ("h0", "remember", {"text": "a"}),
        ("h1", "remember", {"text": "b"}),
        ("h2", "remember", {"text": "c"}),
        ("h3", "remember", {"text": "d"}),
    ]
    assert results_of(answer.turns) == [
        ("h0", "Saved a."),
        ("h1", "Saved b."),
        ("h2", "Saved c."),
        ("h3", "Saved d."),
    ]
    # The rounds carry no preamble: the reply after them is the whole of
    # what was heard, said once.
    assert texts(answer.turns)[1:] == ["", "", "", "", "All four saved."]
    # Where the runtime routed each call travels with it.
    assert {(one.source, one.entry) for turn in answer.turns for one in turn.tool_calls} == {
        ("builtin", None)
    }


def test_ids_count_on_across_turns() -> None:
    """The next call the resumed session keeps is minted after these,
    so no id can repeat across the join."""
    answer = hydrated(
        [
            StoredTurn(id=1, heard="one", reply="Done.", calls=(row(0),)),
            StoredTurn(id=2, heard="two", reply="Done.", calls=(row(0), row(1))),
        ],
        PLENTY,
    )

    assert [one[0] for one in calls_of(answer.turns)] == ["h0", "h1", "h2"]
    assert [one[0] for one in results_of(answer.turns)] == ["h0", "h1", "h2"]


def test_rows_are_grouped_into_rounds_before_any_is_left_out() -> None:
    """The second round's first call never answered. Left out after the
    grouping, it still says where that round began; left out before it,
    the round's other call would fold into the first round."""
    answer = hydrated(
        [
            StoredTurn(
                id=1,
                heard="go",
                reply="Done.",
                calls=(
                    row(0, arguments={"text": "a"}),
                    row(1, arguments={"text": "b"}),
                    row(0, name="self_get_device_status", source="device", result=None),
                    row(1, arguments={"text": "d"}),
                ),
            )
        ],
        PLENTY,
    )

    assert [[one.arguments for one in turn.tool_calls] for turn in answer.turns] == [
        [],
        [{"text": "a"}, {"text": "b"}],
        [],
        [{"text": "d"}],
        [],
        [],
    ]


def test_a_call_with_no_result_or_no_name_is_not_rebuilt() -> None:
    """A successful move answered nothing, a call a cut left running
    never answered, and a row with no name has nothing to be called by.
    None comes back, and a round left with nothing renders nothing."""
    answer = hydrated(
        [
            StoredTurn(
                id=1,
                heard="go to the tutor",
                reply="One moment.",
                calls=(
                    row(0, name="switch_agent", result=None, arguments={"agent": "tutor"}),
                    row(1, name="self_get_device_status", source="device", result=None),
                    row(2, name=None, source="unknown", result="no tool called that"),
                ),
            )
        ],
        PLENTY,
    )

    assert roles(answer.turns) == ["user", "assistant"]
    assert texts(answer.turns) == ["go to the tutor", "One moment."]


def test_a_malformed_call_comes_back_with_no_arguments_and_its_error() -> None:
    """What the store kept of it: no arguments, because the model's
    bytes were not an object, and the error the model was answered
    with. The same shape the session itself keeps."""
    answer = hydrated(
        [
            StoredTurn(
                id=1,
                heard="remember this",
                reply="Let me try that again.",
                calls=(
                    row(
                        0,
                        arguments=None,
                        malformed=True,
                        is_error=True,
                        result="The arguments were not a JSON object.",
                    ),
                ),
            )
        ],
        PLENTY,
    )

    (kept,) = [one for turn in answer.turns for one in turn.tool_calls]
    assert (kept.name, kept.arguments, kept.malformed_arguments) == ("remember", {}, None)
    (result,) = [one for turn in answer.turns for one in turn.tool_results]
    assert result.is_error
    assert result.content == "The arguments were not a JSON object."


def test_a_turn_that_only_ran_tools_ends_on_its_tool_turn() -> None:
    """A reply cut before it spoke kept its exchange, and that is not a
    hole: what it did comes back, and the next utterance follows the
    tool turn exactly as it did in the session."""
    answer = hydrated(
        [
            StoredTurn(id=1, heard="remember tea", calls=(row(0),)),
            StoredTurn(id=2, heard="what do I like?", reply="Tea."),
        ],
        PLENTY,
    )

    assert roles(answer.turns) == ["user", "assistant", "tool", "user", "assistant"]
    assert (answer.rendered, answer.skipped) == (2, 0)


def test_a_joined_turns_calls_stay_structured_after_the_answer_before_it() -> None:
    """The first turn of a thread a move landed on, which ran a tool
    before it answered. Its call stays a call, and the answer it follows
    starts that call's assistant turn rather than standing as a second
    assistant message in a row."""
    answer = hydrated(
        [
            StoredTurn(id=1, heard="what is out there", reply="Galaxies."),
            StoredTurn(
                id=2,
                reply="We were talking about galaxies.",
                calls=(row(0, name="recall", arguments={"query": "galaxies"}, result="M31."),),
            ),
            StoredTurn(id=3, heard="go on", reply="Billions of them."),
        ],
        PLENTY,
    )

    assert roles(answer.turns) == ["user", "assistant", "tool", "assistant", "user", "assistant"]
    asking = answer.turns[1]
    assert asking.content == "Galaxies."
    assert [(one.id, one.name) for one in asking.tool_calls] == [("h0", "recall")]
    assert texts(answer.turns)[3] == "We were talking about galaxies."
    assert (answer.rendered, answer.skipped) == (3, 0)
    # And a request that still offers the tool sends it structured: only
    # an unoffered call is ever turned into a note.
    sent = as_sent(answer.turns, len(answer.turns), {"recall"}).turns
    assert [(one.id, one.name) for one in sent[1].tool_calls] == [("h0", "recall")]
    assert sent[1].content == "Galaxies."


def test_an_answer_joined_after_a_tool_only_turn_follows_its_tool_turn() -> None:
    """The joined answer's text comes after the round it follows, where
    an assistant turn may stand."""
    answer = hydrated(
        [
            StoredTurn(id=1, heard="remember tea", calls=(row(0),)),
            StoredTurn(id=2, reply="Tutor here."),
        ],
        PLENTY,
    )

    assert roles(answer.turns) == ["user", "assistant", "tool", "assistant"]
    assert texts(answer.turns)[-1] == "Tutor here."


def _charged(name: str, arguments: dict[str, Any], result: str, error: bool) -> int:
    """What one kept call is charged, written out from the frame the
    history module publishes rather than asked of it: its degraded note
    with every character outside ASCII as its JSON escape (the bound
    over both translators' structured forms), and the space that joins
    a note to the text before it in its turn."""
    record = {"tool": name, "arguments": arguments, "result": result, "error": error}
    return len(DEGRADED_PREFIX + json.dumps(record) + DEGRADED_END) + len(" ")


def test_a_large_result_is_charged_at_its_cleared_size() -> None:
    """A 10 KiB result goes to every later request as the cleared note,
    so that is what the budget charges, inside the call's degraded note:
    the turn fits a budget sized for that, beside the newest one."""
    big = "s" * 10_240
    older = StoredTurn(
        id=1,
        heard="how is my board",
        reply="Fine.",
        calls=(row(0, name="self_get_device_status", source="device", arguments={}, result=big),),
    )
    newest = said(2)
    cleared = CLEARED_NOTE.format(name="self_get_device_status", size=10_240)
    charged = -(
        -(
            len("how is my board")
            + len("Fine.")
            + _charged("self_get_device_status", {}, cleared, False)
        )
        // ESTIMATED_CHARS_PER_TOKEN
    )

    answer = hydrated([older, newest], charged + _cost(newest))

    assert (answer.rendered, answer.over_budget) == (2, False)
    # Rebuilt whole: clearing it is the request's to do, when one is made.
    assert results_of(answer.turns) == [("h0", big)]
    assert hydrated([older, newest], charged + _cost(newest) - 1).rendered == 1


def test_a_turn_that_would_fit_structured_but_not_as_notes_is_left_out() -> None:
    """Hydration does not know what a later request will offer, so it
    charges every call as the note an unoffered one becomes, which is
    the larger form. A budget with room for the structured call's name,
    arguments and result, and not for the note, leaves the turn out."""
    older = StoredTurn(
        id=1,
        heard="remember tea",
        reply="Saved.",
        calls=(row(0, arguments={"text": "tea"}, result="Saved."),),
    )
    newest = said(2)
    words = len("remember tea") + len("Saved.")
    structured = words + len("remember") + len(json.dumps({"text": "tea"})) + len("Saved.")
    as_note = words + _charged("remember", {"text": "tea"}, "Saved.", False)
    room = -(-structured // ESTIMATED_CHARS_PER_TOKEN) + _cost(newest)
    assert room < -(-as_note // ESTIMATED_CHARS_PER_TOKEN) + _cost(newest)

    answer = hydrated([older, newest], room)

    assert (answer.rendered, answer.over_budget) == (1, True)
    assert answer.turns == (Turn("user", "2" * 8), Turn("assistant", "r2" * 4))


def test_each_call_is_charged_its_note_and_the_space_before_it() -> None:
    """Two calls in one round go to a request that offers neither as
    two notes in one assistant turn, a space apart, so the space is
    charged as well as the notes. The reply is padded so that one
    character more or less moves the rounded token count, which is what
    makes a missing space observable."""
    charged = [
        _charged("remember", {"text": "a"}, "Saved.", False),
        _charged("remember", {"text": "b"}, "Saved.", False),
    ]
    reply = "Saved both."
    while (len("save two") + len(reply) + sum(charged)) % ESTIMATED_CHARS_PER_TOKEN != 1:
        reply += "."
    older = StoredTurn(
        id=1,
        heard="save two",
        reply=reply,
        calls=(
            row(0, arguments={"text": "a"}, result="Saved."),
            row(1, arguments={"text": "b"}, result="Saved."),
        ),
    )
    newest = said(2)
    tokens = -(-(len("save two") + len(reply) + sum(charged)) // ESTIMATED_CHARS_PER_TOKEN)

    assert hydrated([older, newest], tokens + _cost(newest)).rendered == 2
    assert hydrated([older, newest], tokens + _cost(newest) - 1).rendered == 1
    # And at least what the request offering nothing really sends.
    rebuilt = hydrated([older], PLENTY).turns
    sent = as_sent(rebuilt, len(rebuilt), frozenset()).turns
    assert sum(len(turn.content) for turn in sent) <= len("save two") + len(reply) + sum(
        charged
    )


def test_text_outside_ascii_is_charged_at_its_escaped_size() -> None:
    """A structured call's arguments can go to a provider JSON-escaped,
    six characters for each one outside ASCII, which is longer than the
    note that keeps them raw. The charge is the escaped size, so a
    budget with room only for the raw note leaves the turn out."""
    older = StoredTurn(
        id=1,
        heard="remember",
        reply="Saved.",
        calls=(row(0, arguments={"text": "é" * 40}, result="Saved."),),
    )
    newest = said(2)
    record = {"tool": "remember", "arguments": {"text": "é" * 40}}
    record |= {"result": "Saved.", "error": False}
    note = DEGRADED_PREFIX + json.dumps(record, ensure_ascii=False) + DEGRADED_END
    raw = len("remember") + len("Saved.") + len(note) + len(" ")
    escaped = len("remember") + len("Saved.") + _charged(
        "remember", {"text": "é" * 40}, "Saved.", False
    )
    # Six characters for each of the forty, where the raw note has one.
    assert escaped - raw == 5 * 40

    room_for_raw = -(-raw // ESTIMATED_CHARS_PER_TOKEN) + _cost(newest)
    assert hydrated([older, newest], room_for_raw).rendered == 1
    fits = -(-escaped // ESTIMATED_CHARS_PER_TOKEN) + _cost(newest)
    assert hydrated([older, newest], fits).rendered == 2
    assert hydrated([older, newest], fits - 1).rendered == 1


def test_a_result_with_a_lone_surrogate_is_rebuilt_and_priced_like_any_other() -> None:
    """JSON can carry an escaped lone surrogate and a far side can answer
    one; the session keeps such a result with U+FFFD in its place. A row
    holding one is rebuilt in that same form, so measuring and sending
    it raises nothing."""
    answer = hydrated(
        [
            StoredTurn(
                id=1,
                heard="how is my board",
                reply="Fine.",
                calls=(
                    row(
                        0,
                        name="self_get_device_status",
                        source="device",
                        arguments={},
                        result=json.loads('"volume \\ud800 high"'),
                    ),
                ),
            )
        ],
        PLENTY,
    )

    assert results_of(answer.turns) == [("h0", "volume \ufffd high")]
    sent = as_sent(answer.turns, len(answer.turns), frozenset()).turns
    "".join(turn.content for turn in sent).encode("utf-8")


# What a recap checkpoint changes


def test_a_checkpoint_is_the_head_and_the_turns_after_it_the_tail() -> None:
    """Milestone-aware hydration: the caller has already left out the
    turns the checkpoint covers, so what comes back is the recap and
    then whatever was said since."""
    answer = hydrated([said(7), said(8)], PLENTY, milestone="we discussed galaxies")

    assert roles(answer.turns) == ["assistant", "user", "assistant", "user", "assistant"]
    assert texts(answer.turns)[0] == MILESTONE_NOTE.format(text="we discussed galaxies")
    assert (answer.rendered, answer.over_budget) == (2, False)


def test_a_checkpoint_alone_is_the_whole_context_when_nothing_followed_it() -> None:
    """What a consented recap installs at the moment it is made: the
    checkpoint covered everything, so there is no tail yet."""
    answer = hydrated([], PLENTY, milestone="we discussed galaxies")

    assert texts(answer.turns) == [MILESTONE_NOTE.format(text="we discussed galaxies")]
    assert (answer.rendered, answer.skipped, answer.over_budget) == (0, 0, False)
    assert (answer.from_turn, answer.after_turn) == (None, None)


def test_the_checkpoint_survives_a_tail_that_does_not_fit() -> None:
    """The head is pinned: it stands for turns that are not in this list
    at all, so trimming it would delete the oldest part of the thread
    while keeping the newest."""
    units = [said(1), said(2), said(3)]
    recap = "a recap long enough to matter" * 4

    answer = hydrated(units, _cost(units[0]) * 2, milestone=recap)

    assert texts(answer.turns)[0] == MILESTONE_NOTE.format(text=recap)
    assert answer.over_budget is True
    assert answer.rendered < 3


def test_a_checkpoint_charges_the_budget_before_the_tail_does() -> None:
    """Trimmed against the head rather than around it: the same rows
    that fit without a checkpoint do not all fit with one."""
    units = [said(1), said(2)]
    recap = "a recap"
    room = _head(recap) + _cost(units[1])

    assert hydrated(units, room).rendered == 2
    assert hydrated(units, room, milestone=recap).rendered == 1


# The range a recap may claim


def test_the_rendered_range_is_the_turns_actually_read() -> None:
    answer = hydrated([said(4), said(5), said(6)], PLENTY)

    assert (answer.from_turn, answer.after_turn) == (4, 6)


def test_a_backlog_wider_than_the_budget_records_its_true_first_turn() -> None:
    """The finding this field exists for: a bounded recap must not claim
    coverage of the turns its own budget dropped, so what it records is
    where its reading really began."""
    units = [said(index) for index in range(1, 6)]

    answer = hydrated(units, _cost(units[0]) * 2)

    assert answer.over_budget is True
    assert (answer.from_turn, answer.after_turn) == (4, 5)


def test_a_gap_at_the_end_does_not_become_the_range_it_could_not_read() -> None:
    """A turn with no stored text is not a turn a recap read, so the
    range stops at the newest one it could."""
    answer = hydrated([said(1), said(2), StoredTurn(id=3)], PLENTY)

    assert (answer.from_turn, answer.after_turn) == (1, 2)


def _cost(turn: StoredTurn) -> int:
    """What one unit is estimated at, computed the way the module does
    rather than written down: a budget in this file is then arithmetic
    on the input rather than a number that has to be kept in step."""
    characters = len(turn.heard or "") + len(turn.reply or "")
    return -(-characters // ESTIMATED_CHARS_PER_TOKEN)


def _head(text: str) -> int:
    """What the pinned checkpoint costs, framed the way the module
    frames it, for the same reason `_cost` is computed rather than
    written down."""
    characters = len(MILESTONE_NOTE.format(text=text))
    return -(-characters // ESTIMATED_CHARS_PER_TOKEN)
