"""The device record: who mints its identity, and what keeps it.

#449 turns `devices.<mac>` from a list of agent names into a record with
a server-minted id, a name an agent says out loud, and a place. The id
is the point of the change, and everything here is about the two claims
that make it worth having:

- **It is minted in the repository, under the domain writer lock, and
  never in a validator.** A `mode="before"` validator that minted would
  make parsing non-deterministic and `apply` non-idempotent, because
  re-reading one document would produce a new identity every time. The
  repository can consult the stored row, so a stored id wins, an absent
  id on a MAC that already has a row adopts it, and re-applying an
  unchanged document writes nothing.
- **Every device ingress goes through that.** The plan's first draft
  claimed the ingresses inherited the record shape from one validator;
  parsing does and writing does not. `bind`, the pending claim, `apply`
  and `import`, the API writes and stored-row loading are each driven
  here, by name, because each of them is a separate write path.

The name's uniqueness is checked in the repository too, on the state a
write would leave, with the functional unique index behind it; the fold
those two share is proved equal against the database in
`test_device_name_fold.py`, and what is here is the refusal an operator
meets rather than the fold itself.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.support.config_cli import chain
from tests.support.stores import bindings, stored_row
from vinga_server.config import ConfigError, views
from vinga_server.config.api import build_api
from vinga_server.config.loader import (
    DeviceAlreadyBoundError,
    DeviceNameConflictError,
    UnknownEntityError,
)
from vinga_server.config.models import (
    DEVICE_LOCATION_BLANK,
    DatabaseConfig,
    DeviceRecord,
    fold_device_name,
    is_device_id,
)
from vinga_server.config.secrets import MASTER_KEY_ENV, generate_key, load_keys
from vinga_server.config.store import (
    DEVICE_ID_FIXED,
    DEVICE_ID_TAKEN,
    DEVICE_NAME_IN_FLIGHT,
    DEVICE_NAME_RESERVED,
    DEVICE_NAME_TAKEN,
    DEVICE_TEXT_CREDENTIAL,
    ConfigStore,
)
from vinga_server.db import open_database, schema

MAC = "aa:bb:cc:dd:ee:ff"
SHOUTED = "AA-BB-CC-DD-EE-FF"
OTHER_MAC = "11:22:33:44:55:66"

# The name a record takes when nobody names it. Full MAC and not a tail
# of it, because the leading octets are the vendor OUI and a fleet
# shares them.
DEFAULT_NAME = f"Device {MAC}"


# The token the API is built with, which every request here carries.
TOKEN = "tok-test-6d1c8b47-never-a-real-secret"


@pytest.fixture
def keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """The master key, in the environment before anything opens the
    database, because the API derives its keys when its lifespan opens
    the engine."""
    monkeypatch.setenv(MASTER_KEY_ENV, generate_key())


@pytest.fixture
def store(keys: None) -> Iterator[ConfigStore]:
    engine = open_database(DatabaseConfig())
    try:
        yield ConfigStore(engine, load_keys())
    finally:
        engine.dispose()


@pytest.fixture
def api(keys: None) -> FastAPI:
    return build_api(TOKEN, DatabaseConfig())


@pytest.fixture
def client(api: FastAPI) -> Iterator[TestClient]:
    """Entered rather than merely constructed: the API's engine is
    opened by the lifespan a `TestClient` runs as a context manager."""
    with TestClient(api, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        yield client


def _agents(store: ConfigStore) -> None:
    """Two agents, so a binding resolves and a document can move a board
    from one to the other."""
    store.set_agent("sam", {"prompt": "You are Sam."})
    store.set_agent("nadia", {"prompt": "You are Nadia."})


def _record(store: ConfigStore, mac: str = MAC) -> DeviceRecord:
    return store.read_device(mac).entry


def _row(store: ConfigStore, mac: str) -> dict[str, Any]:
    """One stored row, read underneath the repository, so a claim about
    what the database holds is not a claim about what the repository
    says it holds."""
    return stored_row(store, select(schema.devices).where(schema.devices.c.mac == mac))


# --- minting, and the shape of what is minted -------------------------


def test_a_bind_mints_an_identity_and_a_default_name(store: ConfigStore) -> None:
    _agents(store)

    bound = store.bind_device(SHOUTED, ["sam"])

    assert is_device_id(bound.id)
    assert bound.mac == MAC
    assert bound.name == DEFAULT_NAME
    assert bound.location is None
    assert bound.agents == ("sam",)


def test_the_minted_identity_is_in_the_row_and_not_only_in_the_answer(
    store: ConfigStore,
) -> None:
    _agents(store)

    bound = store.bind_device(MAC, ["sam"])

    row = _row(store, MAC)
    assert row["id"] == bound.id
    assert row["name"] == DEFAULT_NAME
    assert row["location"] is None
    assert row["agents"] == ["sam"]


def test_two_devices_get_two_identities(store: ConfigStore) -> None:
    _agents(store)

    first = store.bind_device(MAC, ["sam"])
    second = store.bind_device(OTHER_MAC, ["sam"])

    assert first.id != second.id


def test_rebinding_a_device_keeps_the_identity_it_had(store: ConfigStore) -> None:
    """The whole point of minting under the lock rather than in a
    parser: the second write consults the row the first one left."""
    _agents(store)
    first = store.bind_device(MAC, ["sam"])

    again = store.bind_device(MAC, ["sam", "nadia"])

    assert again.id == first.id
    assert again.agents == ("sam", "nadia")


def test_a_claim_by_code_mints_the_same_way_a_bind_does(store: ConfigStore) -> None:
    """The pending claim is a separate ingress and is changed
    explicitly: a board claimed by the six digits on its screen gets a
    record, not a bare binding."""
    _agents(store)

    claimed = store.claim_device(MAC, ["sam"])

    assert is_device_id(claimed.id)
    assert claimed.name == DEFAULT_NAME
    assert _record(store).id == claimed.id


def test_a_claim_still_refuses_a_device_the_configuration_has_spoken_about(
    store: ConfigStore,
) -> None:
    """The condition the claim exists for, unchanged by the record."""
    _agents(store)
    store.bind_device(MAC, ["sam"])

    with pytest.raises(DeviceAlreadyBoundError):
        store.claim_device(MAC, ["nadia"])


# --- the record's two writable halves ---------------------------------


def test_a_rename_moves_the_name_and_nothing_else(store: ConfigStore) -> None:
    _agents(store)
    bound = store.bind_device(MAC, ["sam"])
    store.relocate_device(MAC, "the kitchen")

    renamed = store.rename_device(MAC, "Kitchen Speaker")

    assert renamed.id == bound.id
    assert renamed.name == "Kitchen Speaker"
    assert renamed.location == "the kitchen"
    assert renamed.agents == ("sam",)


def test_the_stored_name_is_exactly_what_was_typed(store: ConfigStore) -> None:
    """Case and spacing are folded for UNIQUENESS and not for storage:
    the agent says the name out loud, and a slug reads badly in
    speech."""
    _agents(store)
    store.bind_device(MAC, ["sam"])

    store.rename_device(MAC, "  Sam's  Desk  ")

    assert _row(store, MAC)["name"] == "  Sam's  Desk  "


def test_a_relocation_moves_the_place_and_nothing_else(store: ConfigStore) -> None:
    _agents(store)
    bound = store.bind_device(MAC, ["sam"])
    store.rename_device(MAC, "Kitchen Speaker")

    located = store.relocate_device(MAC, "the kitchen")

    assert located.id == bound.id
    assert located.name == "Kitchen Speaker"
    assert located.location == "the kitchen"


def test_a_location_is_cleared_by_its_own_verb(store: ConfigStore) -> None:
    _agents(store)
    store.bind_device(MAC, ["sam"])
    store.relocate_device(MAC, "the kitchen")

    cleared = store.clear_device_location(MAC)

    assert cleared.location is None
    assert _row(store, MAC)["location"] is None


def test_clearing_a_location_that_was_never_set_changes_nothing(
    store: ConfigStore,
) -> None:
    """Idempotent, like clearing the default agent: there is no such
    thing as a location that was already not set."""
    _agents(store)
    store.bind_device(MAC, ["sam"])

    assert store.clear_device_location(MAC).location is None
    assert store.clear_device_location(MAC).location is None


@pytest.mark.parametrize(
    "act",
    [
        lambda store: store.rename_device(MAC, "Kitchen Speaker"),
        lambda store: store.relocate_device(MAC, "the kitchen"),
        lambda store: store.clear_device_location(MAC),
    ],
    ids=["rename", "relocate", "clear-location"],
)
def test_the_record_verbs_refuse_a_mac_with_no_record(store: ConfigStore, act) -> None:
    """A device record is what a name and a place are fields of, so a
    MAC nothing has bound addresses nothing. Minting a record is an
    operator's act through `bind`, not a side effect of naming one."""
    _agents(store)

    with pytest.raises(UnknownEntityError) as caught:
        act(store)

    assert MAC not in str(caught.value)


# --- the relocation a conversation makes, addressed by the record ------
#
# `relocate_device` is what an operator types, holding the board and
# reading the MAC off a label. A conversation cannot address it that
# way: it attached to one RECORD at its connect and has to go on meaning
# that record, because the MAC it stands at can be deleted and bound
# again, or moved to another record, while it is still talking. The
# cases below are the difference between the two addresses, which is
# invisible until the two part company.


def test_a_relocation_by_id_writes_the_record_that_holds_the_id(
    store: ConfigStore,
) -> None:
    _agents(store)
    bound = store.bind_device(MAC, ["sam"])
    store.rename_device(MAC, "Kitchen Speaker")

    located = store.relocate_device_by_id(bound.id, "the office")

    assert located.id == bound.id
    assert located.mac == MAC
    assert located.name == "Kitchen Speaker"
    assert located.location == "the office"
    assert _row(store, MAC)["location"] == "the office"


def test_a_relocation_by_id_leaves_the_record_now_at_that_mac_alone(
    store: ConfigStore,
) -> None:
    """The falsifying case for the whole of this addressing, and the
    only one that tells the two apart.

    A board is bound, named and placed; the operator deletes it and
    binds the same board again, which mints a SECOND record at the same
    MAC. A conversation that attached to the first one then says it has
    moved. Addressed by MAC, that write lands on the record that is
    there now, renaming nothing and relocating somebody else's device;
    addressed by the id, it refuses, and the new record is untouched.
    """
    _agents(store)
    gone = store.bind_device(MAC, ["sam"]).id
    store.delete_device(MAC)
    now = store.bind_device(MAC, ["sam"])

    with pytest.raises(UnknownEntityError):
        store.relocate_device_by_id(gone, "the office")

    assert _record(store).id == now.id
    assert _record(store).location is None
    assert _row(store, MAC)["location"] is None


def test_a_relocation_by_id_refuses_an_id_no_record_has(store: ConfigStore) -> None:
    """What a conversation whose device was deleted under it meets. The
    id is not quoted back, the rule every device refusal here keeps."""
    _agents(store)
    store.bind_device(MAC, ["sam"])
    absent = "0" * 32

    with pytest.raises(UnknownEntityError) as caught:
        store.relocate_device_by_id(absent, "the office")

    assert absent not in chain(caught.value)
    assert _record(store).location is None


def test_a_relocation_by_id_is_held_to_the_rules_the_mac_one_is(
    store: ConfigStore,
) -> None:
    """One validation for both addresses, which is the whole reason this
    verb reaches `_device_write` rather than the columns: a location
    that folds to nothing is refused whoever asked for it."""
    _agents(store)
    bound = store.bind_device(MAC, ["sam"])

    with pytest.raises(ConfigError) as caught:
        store.relocate_device_by_id(bound.id, "\u00a0 \t ")

    assert DEVICE_LOCATION_BLANK in str(caught.value)
    assert _record(store).location is None


# --- what a name has to be --------------------------------------------


def test_two_devices_may_not_hold_one_name_once_it_is_folded(
    store: ConfigStore,
) -> None:
    _agents(store)
    store.bind_device(MAC, ["sam"])
    store.bind_device(OTHER_MAC, ["sam"])
    store.rename_device(MAC, "Kitchen Speaker")

    with pytest.raises(DeviceNameConflictError) as caught:
        store.rename_device(OTHER_MAC, "  kitchen   SPEAKER ")

    assert str(caught.value) == DEVICE_NAME_TAKEN
    assert _record(store, OTHER_MAC).name == DEFAULT_NAME.replace(MAC, OTHER_MAC)


def test_the_refusal_quotes_neither_name(store: ConfigStore) -> None:
    """A device name is free text an operator types on a command line,
    so it is a place a paste lands and is never echoed."""
    pasted = "sk-test-4f8b2c9e-never-a-real-credential"
    _agents(store)
    store.bind_device(MAC, ["sam"])
    store.bind_device(OTHER_MAC, ["sam"])
    store.rename_device(MAC, pasted)

    with pytest.raises(DeviceNameConflictError) as caught:
        store.rename_device(OTHER_MAC, pasted.upper())

    assert pasted not in str(caught.value)


def test_renaming_a_device_to_the_name_it_already_has_is_allowed(
    store: ConfigStore,
) -> None:
    """A self-rename is not a collision: the check is about the state
    the write would LEAVE, and that state has one device under the
    name."""
    _agents(store)
    store.bind_device(MAC, ["sam"])
    store.rename_device(MAC, "Kitchen Speaker")

    assert store.rename_device(MAC, "KITCHEN speaker").name == "KITCHEN speaker"


@pytest.mark.parametrize("blank", ["", "   ", " 　\t"])
def test_a_name_that_folds_to_nothing_is_refused(store: ConfigStore, blank: str) -> None:
    _agents(store)
    store.bind_device(MAC, ["sam"])

    with pytest.raises(ConfigError):
        store.rename_device(MAC, blank)

    assert _record(store).name == DEFAULT_NAME


@pytest.mark.parametrize("blank", ["", "   ", "\xa0\u3000\t"], ids=["empty", "spaces", "unicode"])
@pytest.mark.parametrize(
    "act",
    [
        lambda store, value: store.relocate_device(MAC, value),
        lambda store, value: store.apply(
            {"devices": {MAC: {"location": value, "agents": ["sam"]}}}
        ),
    ],
    ids=["relocate", "apply"],
)
def test_a_location_holding_nothing_is_refused(
    store: ConfigStore, act, blank: str
) -> None:
    """There is one way to say a device is nowhere in particular, and it
    is the absence of a location. An empty string would be a second
    spelling of a state that already has one, and it would read as
    somewhere on every surface that tests the field for a value.

    Both write paths, because they are two, and the folded form rather
    than the length, because a location of two no-break spaces is not
    empty to a length check.
    """
    _agents(store)
    store.bind_device(MAC, ["sam"])
    store.relocate_device(MAC, "the kitchen")

    with pytest.raises(ConfigError) as caught:
        act(store, blank)

    assert DEVICE_LOCATION_BLANK in str(caught.value)
    assert _record(store).location == "the kitchen"


def test_the_api_refuses_a_location_holding_nothing(
    client: TestClient, store: ConfigStore
) -> None:
    """The third path to the same field, which is the one an admin UI
    would take: an empty text box is a request to clear, and clearing is
    the DELETE the contract declares."""
    _agents(store)
    store.bind_device(MAC, ["sam"])

    refused = client.put(f"/devices/{MAC}/location", json={"location": "  "})

    assert refused.status_code == 422
    assert client.get(f"/devices/{MAC}").json()["entity"]["location"] is None


def test_the_default_names_of_two_boards_do_not_collide(store: ConfigStore) -> None:
    """The backfill rule, asserted where it is cheapest: the full MAC is
    unique by construction because `mac` is, so two records created
    within a second of each other cannot fight over a default."""
    _agents(store)

    first = store.bind_device(MAC, ["sam"])
    second = store.bind_device(OTHER_MAC, ["sam"])

    assert fold_device_name(first.name) != fold_device_name(second.name)


# --- the spelling the server keeps for itself ---------------------------

# `Device <mac>` is what a bind mints so that no onboarding flow has to
# ask for a name the operator does not yet have, and the agent is told
# the name and says it out loud. So the shape is refused to every writer
# whose own default it is not: a board called `Device aa:bb:cc:dd:ee:ff`
# is one nobody has named, rather than one somebody named that, and the
# refusal is what makes that reading sound instead of a guess.


def test_a_device_may_not_take_another_boards_default_name(
    store: ConfigStore,
) -> None:
    _agents(store)
    store.bind_device(MAC, ["sam"])
    store.bind_device(OTHER_MAC, ["sam"])

    with pytest.raises(ConfigError) as caught:
        store.rename_device(OTHER_MAC, DEFAULT_NAME)

    assert str(caught.value) == DEVICE_NAME_RESERVED
    assert _record(store, OTHER_MAC).name == DEFAULT_NAME.replace(MAC, OTHER_MAC)


def test_the_shape_is_reserved_however_it_is_spelled(store: ConfigStore) -> None:
    """The fold is what the refusal reads, so capitalizing the word or
    padding it does not get a placeholder past: those names fold onto
    the default and would collide with it in the index anyway."""
    _agents(store)
    store.bind_device(MAC, ["sam"])
    store.bind_device(OTHER_MAC, ["sam"])

    with pytest.raises(ConfigError) as caught:
        store.rename_device(OTHER_MAC, f"  DEVICE   {MAC.upper()} ")

    assert str(caught.value) == DEVICE_NAME_RESERVED


def test_the_reserved_refusal_quotes_neither_the_name_nor_the_mac(
    store: ConfigStore,
) -> None:
    _agents(store)
    store.bind_device(MAC, ["sam"])
    store.bind_device(OTHER_MAC, ["sam"])

    with pytest.raises(ConfigError) as caught:
        store.rename_device(OTHER_MAC, DEFAULT_NAME)

    assert MAC not in str(caught.value) and OTHER_MAC not in str(caught.value)


def test_a_document_may_not_name_a_device_after_another_board(
    store: ConfigStore,
) -> None:
    """The ingress the CLI does not go through, held to the same rule:
    an applied document is a writer like any other."""
    _agents(store)
    store.bind_device(OTHER_MAC, ["sam"])

    with pytest.raises(ConfigError) as caught:
        store.apply(_document(agents=["sam"], name=DEFAULT_NAME.replace(MAC, OTHER_MAC)))

    # Wrapped in the sentence an apply refuses a whole document with,
    # which is the shape every repository refusal takes on that path.
    assert DEVICE_NAME_RESERVED in str(caught.value)


def test_a_device_may_be_named_back_to_its_own_default(store: ConfigStore) -> None:
    """The exemption, and it is two things at once: the honest way to
    say "take the name back off this board", and what keeps an exported
    document applicable, since an export of a board nobody has named
    carries exactly this string."""
    _agents(store)
    store.bind_device(MAC, ["sam"])
    store.rename_device(MAC, "Kitchen Speaker")

    store.rename_device(MAC, DEFAULT_NAME)

    assert _record(store).name == DEFAULT_NAME


def test_a_document_carrying_the_minted_name_applies_and_writes_nothing(
    store: ConfigStore,
) -> None:
    """What an export of an unnamed board is, applied back: the
    reservation must not make a round trip refuse the document it
    produced."""
    _agents(store)
    store.bind_device(MAC, ["sam"])
    minted = _record(store)

    applied = store.apply(_document(agents=["sam"], id=minted.id, name=DEFAULT_NAME))

    assert [entry.wrote for entry in applied] == [False]
    assert _record(store) == minted


def test_binding_a_board_still_mints_the_reserved_name(store: ConfigStore) -> None:
    """The one writer the reservation is not about. Binding names no
    device: the server does, and what it writes is the placeholder every
    other writer is refused."""
    _agents(store)

    store.bind_device(MAC, ["sam"])

    assert _record(store).name == DEFAULT_NAME


# --- what a stored string may carry ------------------------------------
#
# A device name and a device location are stored exactly as written and
# read back on every surface that shows the record, which makes them the
# same shape of hazard a provider's `base_url` is: a URL carrying a
# credential names nothing suspicious and would sit in the
# configuration rather than in the encrypted store.
#
# Leaving it to the display would not do, and the export is why. A read
# strips the credential on its way out, so a name stored with one and
# re-applied from an export would come back as a DIFFERENT name, which
# is the one thing a document a deployment is rebuilt from may not do.

# Not real credentials, and shaped so a substring hunt for either cannot
# match by accident.
IN_AUTHORITY = "https://user:pw-test-51c8fa03-never-real@example.invalid/room"

IN_QUERY = "https://example.invalid/room?api_key=pw-test-9b4e27dd-never-real"

# The control beside them: a URL that carries no credential at all. It is
# a lawful name and a lawful location, and it has to survive the round
# trip byte for byte, which is the property the refusals above protect.
WITHOUT_CREDENTIAL = "https://example.invalid/the-kitchen"


@pytest.mark.parametrize("carried", [IN_AUTHORITY, IN_QUERY], ids=["authority", "query"])
@pytest.mark.parametrize(
    ("what", "act"),
    [
        ("name", lambda store, value: store.rename_device(MAC, value)),
        ("location", lambda store, value: store.relocate_device(MAC, value)),
        (
            "name",
            lambda store, value: store.apply(
                {"devices": {MAC: {"name": value, "agents": ["sam"]}}}
            ),
        ),
        (
            "location",
            lambda store, value: store.apply(
                {"devices": {MAC: {"location": value, "agents": ["sam"]}}}
            ),
        ),
    ],
    ids=["rename", "relocate", "apply-name", "apply-location"],
)
def test_a_credential_bearing_url_is_refused_on_every_write(
    store: ConfigStore, what: str, act, carried: str
) -> None:
    """Both fields, both shapes of credential, and both the direct verb
    and the applied document, because they are different write paths and
    the review found the check on none of them."""
    _agents(store)
    store.bind_device(MAC, ["sam"])

    with pytest.raises(ConfigError) as caught:
        act(store, carried)

    assert DEVICE_TEXT_CREDENTIAL.format(what=what) in str(caught.value)
    # Not on the sentence, and not behind it either: a refusal raised
    # inside a handler keeps the exception it was handling, and a
    # validation error holds the whole rejected value.
    assert carried not in chain(caught.value)
    # And nothing was written, which is what makes the refusal a refusal.
    assert _record(store).name == DEFAULT_NAME
    assert _record(store).location is None


@pytest.mark.parametrize("field", ["name", "location"])
def test_a_url_that_carries_no_credential_survives_an_export_and_a_reapply(
    store: ConfigStore, field: str
) -> None:
    """The property the refusals protect, asserted rather than assumed.

    The display strips a credential from a URL on its way out, so a
    field that could hold one would come back from an export as
    something else and an apply of that export would CHANGE the row.
    A URL with no credential passes the display untouched, so the round
    trip is exact, and this is what says the two are the same question.
    """
    _agents(store)
    store.bind_device(MAC, ["sam"])
    if field == "name":
        store.rename_device(MAC, WITHOUT_CREDENTIAL)
    else:
        store.relocate_device(MAC, WITHOUT_CREDENTIAL)
    before = _record(store)

    exported = views.config(store.load())["config"]["devices"][MAC]
    assert exported[field] == WITHOUT_CREDENTIAL
    applied = store.apply({"devices": {MAC: exported}})

    assert [entry.wrote for entry in applied] == [False]
    assert _record(store) == before


# --- apply and import, which is the ingress the plan calls out ---------


def _document(**device: object) -> dict[str, object]:
    return {"devices": {MAC: device}}


def test_the_bare_agent_list_and_the_record_form_normalize_alike(
    store: ConfigStore,
) -> None:
    """The value-shape union, absorbed in `normalize_device_bindings`.
    Every configuration written before #449 uses the bare list, and it
    means a record naming only those agents."""
    _agents(store)

    store.apply({"devices": {MAC: ["sam"]}})
    shorthand = _record(store)
    store.delete_device(MAC)
    store.apply(_document(agents=["sam"]))
    spelled = _record(store)

    assert shorthand.agents == spelled.agents == ["sam"]
    assert shorthand.name == spelled.name == DEFAULT_NAME
    assert shorthand.location is spelled.location is None
    # The ids differ, and that is the point rather than a wrinkle: the
    # row was deleted between them, so the second is a different device
    # record about the same board.
    assert shorthand.id != spelled.id


def test_applying_a_document_twice_writes_nothing_the_second_time(
    store: ConfigStore,
) -> None:
    """`apply`'s idempotence, which is what minting under the lock
    buys. A parser that minted would report a write every time, because
    the record it staged would differ from the stored one by its id."""
    _agents(store)
    document = {"devices": {MAC: ["sam"]}}

    first = store.apply(document)
    minted = _record(store).id
    second = store.apply(document)

    assert [entry.wrote for entry in first] == [True]
    assert [entry.wrote for entry in second] == [False]
    assert _record(store).id == minted


def test_an_exported_document_applied_back_is_a_no_op(store: ConfigStore) -> None:
    """The same claim over the document a deployment actually round
    trips: the export carries the id, and applying it back writes
    nothing."""
    _agents(store)
    store.bind_device(MAC, ["sam"])
    store.rename_device(MAC, "Kitchen Speaker")
    store.relocate_device(MAC, "the kitchen")
    record = _record(store)

    applied = store.apply(
        {
            "devices": {
                MAC: {
                    "id": record.id,
                    "name": record.name,
                    "location": record.location,
                    "agents": list(record.agents),
                }
            }
        }
    )

    assert [entry.wrote for entry in applied] == [False]
    assert _record(store) == record


def test_a_document_that_leaves_the_name_out_keeps_the_stored_one(
    store: ConfigStore,
) -> None:
    _agents(store)
    store.bind_device(MAC, ["sam"])
    store.rename_device(MAC, "Kitchen Speaker")
    store.relocate_device(MAC, "the kitchen")

    store.apply({"devices": {MAC: ["nadia"]}})

    kept = _record(store)
    assert kept.name == "Kitchen Speaker"
    assert kept.location == "the kitchen"
    assert kept.agents == ["nadia"]


def test_a_document_carrying_a_null_location_clears_it(store: ConfigStore) -> None:
    """Absence and an explicit null say different things, the way
    `default_agent` already does: the key left out leaves the place
    alone, and `null` says the device is nowhere in particular."""
    _agents(store)
    store.bind_device(MAC, ["sam"])
    store.relocate_device(MAC, "the kitchen")

    store.apply(_document(agents=["sam"], location=None))

    assert _record(store).location is None


def test_an_id_for_a_mac_with_no_row_is_adopted(store: ConfigStore) -> None:
    """Which is what lets an exported document restore a deployment
    onto an empty database with the identities it had, rather than as a
    set of devices nothing has ever seen before."""
    _agents(store)
    carried = "a" * 32

    store.apply(_document(id=carried, agents=["sam"]))

    assert _record(store).id == carried


def test_an_id_that_disagrees_with_the_stored_one_is_refused(
    store: ConfigStore,
) -> None:
    """Refused rather than silently ignored.

    An id a write could replace would not be an identity: the record
    under that MAC would become a second device rather than an edited
    first one. A caller that asked for something this will not do
    should be told so rather than have it quietly not happen."""
    _agents(store)
    store.bind_device(MAC, ["sam"])

    with pytest.raises(ConfigError) as caught:
        store.apply(_document(id="b" * 32, agents=["sam"]))

    assert DEVICE_ID_FIXED in str(caught.value)


def test_one_id_may_not_be_given_to_two_devices(store: ConfigStore) -> None:
    _agents(store)
    carried = "c" * 32

    with pytest.raises(DeviceNameConflictError) as caught:
        store.apply(
            {
                "devices": {
                    MAC: {"id": carried, "agents": ["sam"]},
                    OTHER_MAC: {"id": carried, "agents": ["sam"]},
                }
            }
        )

    assert str(caught.value) == DEVICE_ID_TAKEN


def test_a_document_naming_two_devices_one_name_is_refused(store: ConfigStore) -> None:
    _agents(store)

    with pytest.raises(DeviceNameConflictError):
        store.apply(
            {
                "devices": {
                    MAC: {"name": "Kitchen Speaker", "agents": ["sam"]},
                    OTHER_MAC: {"name": "kitchen  speaker", "agents": ["sam"]},
                }
            }
        )

    assert bindings(store.load().domain.devices) == {}


def test_a_document_that_swaps_two_names_is_refused_with_a_sentence(
    store: ConfigStore,
) -> None:
    """The end state is fine and the way there is not.

    A unique index is checked statement by statement rather than at
    commit, so whether a swap worked would depend on the order
    `_persist` happened to write two rows in. The repository refuses it
    with a sentence naming the remedy, rather than letting the index
    answer with the generic sanitized database failure and a 500. Doing
    it in two steps works, which the second half asserts.
    """
    _agents(store)
    store.bind_device(MAC, ["sam"])
    store.bind_device(OTHER_MAC, ["sam"])
    store.rename_device(MAC, "Upstairs")
    store.rename_device(OTHER_MAC, "Downstairs")
    swap = {
        "devices": {
            MAC: {"name": "Downstairs", "agents": ["sam"]},
            OTHER_MAC: {"name": "Upstairs", "agents": ["sam"]},
        }
    }

    with pytest.raises(DeviceNameConflictError) as caught:
        store.apply(swap)

    assert DEVICE_NAME_IN_FLIGHT in str(caught.value)
    assert _record(store, MAC).name == "Upstairs"

    store.rename_device(MAC, "In between")
    store.rename_device(OTHER_MAC, "Upstairs")
    store.rename_device(MAC, "Downstairs")
    assert _record(store, MAC).name == "Downstairs"
    assert _record(store, OTHER_MAC).name == "Upstairs"


def test_a_bad_id_in_a_document_is_refused_by_the_rule_and_not_the_index(
    store: ConfigStore,
) -> None:
    _agents(store)

    with pytest.raises(ConfigError) as caught:
        store.apply(_document(id="not-a-uuid-hex", agents=["sam"]))

    assert "not-a-uuid-hex" not in str(caught.value)


# --- stored-row loading, which is an ingress of its own ----------------


def test_a_stored_record_reads_back_whole(store: ConfigStore) -> None:
    _agents(store)
    store.bind_device(MAC, ["sam", "nadia"])
    store.rename_device(MAC, "Kitchen Speaker")
    store.relocate_device(MAC, "the kitchen")

    loaded = store.load().domain.devices[MAC]

    assert loaded == _record(store)
    assert loaded.agents == ["sam", "nadia"]


def test_an_agent_rename_moves_the_binding_and_leaves_the_record_alone(
    store: ConfigStore,
) -> None:
    """The agent rename rewrites device bindings, which makes it a
    device write too. What it must not rewrite is the rest of the
    record: an agent's name is not a device's name."""
    _agents(store)
    store.bind_device(MAC, ["sam"])
    store.rename_device(MAC, "Kitchen Speaker")
    store.relocate_device(MAC, "the kitchen")
    before = _record(store)

    store.rename_agent("sam", "samuel")

    after = _record(store)
    assert after.id == before.id
    assert after.name == before.name
    assert after.location == before.location
    assert after.agents == ["samuel"]


# --- the API, which is the other ingress that writes -------------------


def test_the_api_writes_go_through_the_same_minting(
    client: TestClient, store: ConfigStore
) -> None:
    _agents(store)

    assert client.put(f"/devices/{MAC}", json={"agents": ["sam"]}).status_code == 200

    read = client.get(f"/devices/{MAC}").json()["entity"]
    assert is_device_id(read["id"])
    assert read["name"] == DEFAULT_NAME
    assert read["location"] is None


def test_the_api_rename_and_relocation_keep_the_identity(
    client: TestClient, store: ConfigStore
) -> None:
    _agents(store)
    store.bind_device(MAC, ["sam"])
    minted = _record(store).id

    assert (
        client.post(f"/devices/{MAC}/rename", json={"to": "Kitchen Speaker"}).status_code
        == 200
    )
    assert (
        client.put(f"/devices/{MAC}/location", json={"location": "the kitchen"}).status_code
        == 200
    )

    read = client.get(f"/devices/{MAC}").json()["entity"]
    assert read == {
        "id": minted,
        "name": "Kitchen Speaker",
        "location": "the kitchen",
        "agents": ["sam"],
    }


def test_the_api_clears_a_location_with_a_delete(
    client: TestClient, store: ConfigStore
) -> None:
    _agents(store)
    store.bind_device(MAC, ["sam"])
    store.relocate_device(MAC, "the kitchen")

    assert client.delete(f"/devices/{MAC}/location").status_code == 200

    assert client.get(f"/devices/{MAC}").json()["entity"]["location"] is None


def test_a_name_another_board_holds_is_a_409(
    client: TestClient, store: ConfigStore
) -> None:
    """A fact about the world rather than a malformed request, which is
    what the status says: retrying will not help and another name
    will."""
    _agents(store)
    store.bind_device(MAC, ["sam"])
    store.bind_device(OTHER_MAC, ["sam"])
    store.rename_device(MAC, "Kitchen Speaker")

    refused = client.post(f"/devices/{OTHER_MAC}/rename", json={"to": "KITCHEN  SPEAKER"})

    assert refused.status_code == 409
    assert "KITCHEN" not in refused.text


def test_naming_a_device_that_is_not_there_is_a_404(client: TestClient) -> None:
    assert client.post(f"/devices/{MAC}/rename", json={"to": "Kitchen"}).status_code == 404
    assert (
        client.put(f"/devices/{MAC}/location", json={"location": "here"}).status_code == 404
    )
    assert client.delete(f"/devices/{MAC}/location").status_code == 404
