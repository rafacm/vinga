"""The device-name fold, in its three renderings, over one corpus.

A device name is unique once case and spacing are folded together, and
that fold exists three times because it cannot exist once:

- `models.fold_device_name`, the Python rendering, which the repository
  asks under the writer lock so a collision is a refusal an operator can
  act on rather than a sanitized database failure;
- `models.device_name_fold_sql`, the Postgres rendering, which the
  functional unique index on `domain.devices` is built from and which is
  the invariant standing behind that refusal;
- the literal frozen into `3003_device_record`, because a migration is a
  historical record of what ran and one importing a live rule would
  reproduce a behaviour it never had.

Python string operations and a Postgres expression are different
implementations whose whitespace and case behaviour can diverge, so this
file is the proof of equivalence rather than a pretence that there is
one implementation. Every case is driven through all three, and the two
SQL renderings are evaluated by the database rather than compared as
text: what matters is what Postgres does with them, on the instance the
suite is running against.

The corpus is chosen for the places the three can come apart:

- **The Turkish dotted I.** `İ` is the one character Unicode gives an
  unconditional full lowercase mapping that expands, to `i` plus a
  combining dot. A database applies the SIMPLE mapping and answers `i`.
  A whole-string `.lower()` in Python answers two characters, which is
  the divergence this fold's per-character loop exists to avoid.
- **The Greek final sigma.** `ΑΣ`.lower() is `ας` in Python, because the
  whole-string rule is context sensitive; `lower('ΑΣ')` is `ασ` in
  Postgres. Again per character, again no context, again the same
  answer.
- **Whitespace outside ASCII.** No-break space, ideographic space, ogham
  space mark, the en/em quad family, narrow no-break space. What `\\s`
  means to a Postgres regular expression depends on the database's
  ctype, which is why neither rendering uses it.
- **The sharp s.** `ß` case-FOLDS to `ss` and case-MAPS to itself. The
  fold this project uses is the mapping, so two devices called `Straße`
  and `STRASSE` are two devices, and the corpus says so rather than
  leaving it to be discovered.

The last test is the one that makes the other two worth something: the
index really refuses the second insert.
"""

import importlib
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, insert, text

from vinga_server.config.models import (
    DatabaseConfig,
    device_name_fold_sql,
    fold_device_name,
    mint_device_id,
)
from vinga_server.db import open_database, read_engine, schema

# The migration's own module, reached through `import_module` because
# its name starts with a digit and no import statement can spell that.
# Its frozen copy of the fold is what an upgraded database's index was
# built from.
FROZEN_FOLD: str = importlib.import_module(
    "vinga_server.db.migrations.versions.3003_device_record"
).FOLDED_NAME

# One name per line, chosen for a reason the module docstring gives.
# Written with escapes rather than with the characters themselves, so
# that a reader can see which code point each case is about and so that
# an editor cannot silently normalize one away.
CORPUS = [
    "Kitchen Speaker",
    "kitchen speaker",
    "kitchen  speaker",
    "  Kitchen Speaker  ",
    "\tKitchen\nSpeaker\r",
    "\x0bKitchen\x0cSpeaker",
    "\x1cKitchen\x1dSpeaker\x1e\x1f",
    # The whitespace that is not ASCII, one case per family.
    "Kitchen\xa0Speaker",
    "Kitchen\u3000Speaker",
    "Kitchen\u1680Speaker",
    "Kitchen\u2000\u2003Speaker",
    "Kitchen\u200aSpeaker",
    "Kitchen\u202fSpeaker",
    "Kitchen\u205fSpeaker",
    "Kitchen\u2028Speaker\u2029",
    "\x85Kitchen Speaker\x85",
    "\xa0\u3000 Kitchen \t Speaker \xa0",
    # The Turkish pair, and the ASCII letters they are confused with.
    "İstanbul",
    "ıstanbul",
    "Istanbul",
    "istanbul",
    # The Greek final sigma, in and out of word-final position.
    "ΑΣ",
    "ΣΑΣ",
    # The sharp s, which case-folds and case-maps differently.
    "Stra\xdfe",
    "STRASSE",
    # Ordinary names with punctuation and an emoji, because a name is
    # free-form and an operator will write one like this.
    "Sam's desk",
    "Marvin, upstairs",
    "\U0001f50a Kitchen",
    # And the shapes that fold to nothing or to one word.
    "",
    " ",
    "\xa0\u3000\t",
    "one",
]

# The default a record takes when nobody names it, which the migration
# also backfills. In the corpus because the frozen literal has to agree
# with the live rule about exactly this string on every stored row of
# every upgraded deployment.
CORPUS.append("Device aa:bb:cc:dd:ee:ff")

MAC = "aa:bb:cc:dd:ee:ff"
OTHER_MAC = "11:22:33:44:55:66"


@pytest.fixture
def reader() -> Iterator[Engine]:
    engine = read_engine(DatabaseConfig())
    try:
        yield engine
    finally:
        engine.dispose()


def _folded(engine: Engine, expression: str, value: str) -> str:
    """One SQL rendering of the fold, evaluated by the database over one
    value.

    The value arrives bound rather than interpolated, and the expression
    is applied to a column called `name` because that is the column the
    index is on and the column the frozen literal names: a `values` list
    is the smallest way to give an expression written for a table a row
    to run against.
    """
    with engine.connect() as connection:
        return connection.execute(
            text(f"select {expression} from (values (:value)) as t(name)"),
            {"value": value},
        ).scalar_one()


@pytest.mark.parametrize("name", CORPUS, ids=lambda name: repr(name))
def test_the_python_and_sql_renderings_agree(reader: Engine, name: str) -> None:
    assert fold_device_name(name) == _folded(reader, device_name_fold_sql("name"), name)


@pytest.mark.parametrize("name", CORPUS, ids=lambda name: repr(name))
def test_the_frozen_literal_agrees_with_the_live_rule(reader: Engine, name: str) -> None:
    """The migration's copy, over the same corpus.

    It is frozen on purpose, so this is not a check that it was kept in
    sync by anybody: it is the statement that the index an upgraded
    database carries and the index a fresh one carries fold the same
    names together.
    """
    assert fold_device_name(name) == _folded(reader, FROZEN_FOLD, name)


def test_the_two_sql_renderings_are_the_same_expression() -> None:
    """Cheap and worth having beside the two above: they are the same
    text today, so a change to one that a corpus case does not reach is
    still visible."""
    assert device_name_fold_sql("name") == FROZEN_FOLD


def test_the_fold_is_what_the_plan_says_it_is() -> None:
    """The rule itself, in four cases, so the corpus above is a proof of
    agreement rather than the only statement of what is being agreed."""
    assert fold_device_name("Kitchen  Speaker") == "kitchen speaker"
    assert fold_device_name("  kitchen speaker ") == "kitchen speaker"
    assert fold_device_name("Kitchen \u3000Speaker") == "kitchen speaker"
    assert fold_device_name("İstanbul") == "istanbul"


def test_a_name_that_folds_to_nothing_folds_to_the_empty_string() -> None:
    """Which is what makes the model's blank-name refusal expressible:
    a length check would call two no-break spaces a name."""
    assert fold_device_name(" \u3000\t\n") == ""


def test_the_index_refuses_the_second_of_two_names_that_fold_alike() -> None:
    """The invariant behind the repository's refusal, asserted by
    attempting the insert underneath every rule that would have stopped
    it earlier.

    Written straight into the table rather than through a device verb,
    because what is being pinned is the database and not the check in
    front of it: a repository that stopped asking would still leave a
    deployment unable to hold two boards under one name.
    """
    engine = open_database(DatabaseConfig())
    try:
        with engine.begin() as connection:
            connection.execute(
                insert(schema.devices).values(
                    id=mint_device_id(),
                    mac=MAC,
                    name="Kitchen Speaker",
                    agents=["sam"],
                )
            )
        with pytest.raises(Exception) as caught:  # noqa: PT011 - the driver's own
            with engine.begin() as connection:
                connection.execute(
                    insert(schema.devices).values(
                        id=mint_device_id(),
                        mac=OTHER_MAC,
                        name="  kitchen  speaker ",
                        agents=["sam"],
                    )
                )
    finally:
        engine.dispose()
    assert schema.DEVICE_NAME_INDEX in str(caught.value)


def test_two_names_that_fold_apart_both_insert(reader: Engine) -> None:
    """The control beside it, and the sharp s is the case worth having:
    `Strasse` with a sharp s and `STRASSE` fold together under case
    FOLDING and apart under the case MAPPING this project uses, so this
    pins which of the two the index applies."""
    engine = open_database(DatabaseConfig())
    try:
        with engine.begin() as connection:
            for mac, name in ((MAC, "Stra\xdfe"), (OTHER_MAC, "STRASSE")):
                connection.execute(
                    insert(schema.devices).values(
                        id=mint_device_id(), mac=mac, name=name, agents=["sam"]
                    )
                )
        with engine.connect() as connection:
            stored = connection.execute(text("select name from domain.devices")).scalars()
            assert sorted(stored) == ["STRASSE", "Stra\xdfe"]
    finally:
        engine.dispose()


def test_every_whitespace_character_the_fold_declares_is_unicode_whitespace() -> None:
    """The set is written out because `\\s` is not portable, and a set
    written out is a set that can be wrong. This is the statement that
    it is neither short nor long: exactly the characters Python calls
    whitespace."""
    from vinga_server.config.models import DEVICE_NAME_WHITESPACE

    declared = set(DEVICE_NAME_WHITESPACE)
    assert declared == {chr(point) for point in range(0x110000) if chr(point).isspace()}
    # And that the set as written is a bracket expression both engines
    # read literally, which is what lets the two renderings interpolate
    # it unescaped.
    assert not declared & set("]^-\\")
