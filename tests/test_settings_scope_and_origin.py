"""Three things the settings routes say about scopes.

The permission mode exists once for everybody: outside the global scope a
write is refused, and resolving reads the global scope alone. Asked without
a list of keys, the resolved route answers with every setting of its table.
And a value that is not a set of values names the scope it came from.
"""

from __future__ import annotations

import pytest

from app.api.v1 import einstellungen
from app.api.v1.einstellungen import GLOBAL_ONLY, PRUEFER
from app.berechtigungsregeln import laden
from app.i18n import t

MODE_KEYS = ("berechtigungsmodus_chat", "berechtigungsmodus_agent")


def _rule_file(config):
    return config.pfad(config.app.berechtigungen_datei)


# --- The permission mode: global only ----------------------------------------


def test_the_settings_that_exist_once_are_the_two_permission_modes_and_the_snapshot_switch():
    assert GLOBAL_ONLY == frozenset({*MODE_KEYS, "checkpoints"})


@pytest.mark.parametrize("scope", ["chat:c1", "modell:m1"])
@pytest.mark.parametrize("key", MODE_KEYS)
def test_a_permission_mode_outside_the_global_scope_is_refused_and_nothing_is_stored(
    client, config, scope, key
):
    before = laden(_rule_file(config))

    refused = client.put(f"/api/v1/settings/{scope}/{key}", json={"wert": "restricted"})
    assert refused.status_code == 400
    assert refused.json() == {"detail": t("fehler.setting_only_global", "de", name=key)}

    assert client.app.state.repositories.einstellungen.holen(scope, key) is None
    assert client.get(f"/api/v1/settings/{scope}/{key}").json()["wert"] is None
    after = laden(_rule_file(config))
    assert after.standard == before.standard
    assert after.innerhalb_der_ordner == before.innerhalb_der_ordner
    assert after.ausserhalb_der_ordner == before.ausserhalb_der_ordner


def test_the_refusal_names_the_setting_in_the_requests_language(client):
    refused = client.put(
        "/api/v1/settings/chat:c1/berechtigungsmodus_chat",
        json={"wert": "manuell"},
        headers={"X-Ui-Language": "en"},
    )
    assert refused.status_code == 400
    assert refused.json()["detail"] == (
        "'berechtigungsmodus_chat' can only be set in the scope 'global'"
    )


def test_taking_a_permission_mode_back_outside_the_global_scope_is_refused_as_well(client):
    refused = client.put("/api/v1/settings/chat:c1/berechtigungsmodus_chat", json={"wert": None})
    assert refused.status_code == 400


def test_a_partial_write_of_a_permission_mode_outside_the_global_scope_is_refused(client):
    refused = client.patch(
        "/api/v1/settings/modell:m1/berechtigungsmodus_agent", json={"wert": {"a": 1}}
    )
    assert refused.status_code == 400
    assert refused.json() == {
        "detail": t("fehler.setting_only_global", "de", name="berechtigungsmodus_agent")
    }


@pytest.mark.parametrize(("origin", "key"), [("chat", MODE_KEYS[0]), ("agent", MODE_KEYS[1])])
def test_in_the_global_scope_a_permission_mode_is_stored_and_written_into_the_rule_file(
    client, config, origin, key
):
    """The quiet case: the global write does what it always did."""
    stored = client.put(f"/api/v1/settings/global/{key}", json={"wert": "restricted"})
    assert stored.status_code == 200, stored.text
    assert stored.json() == {"bereich": "global", "schluessel": key, "wert": "restricted"}
    assert client.app.state.repositories.einstellungen.holen("global", key) == "restricted"

    rules = laden(_rule_file(config))
    assert rules.innerhalb_der_ordner[origin] == "fragen"
    assert rules.ausserhalb_der_ordner[origin] == "fragen"


def test_any_other_setting_is_still_taken_in_a_chats_and_a_models_scope(client):
    """The quiet case for every setting that is not global only."""
    for scope in ("chat:c1", "modell:m1"):
        stored = client.put(f"/api/v1/settings/{scope}/klaenge", json={"wert": {"pegel": 7}})
        assert stored.status_code == 200, stored.text
        assert stored.json()["wert"] == {"pegel": 7}


def test_resolving_a_permission_mode_reads_the_global_scope_alone(client):
    """A row an earlier version stored at a chat or a model never applied,
    and resolving does not show it."""
    settings = client.app.state.repositories.einstellungen
    settings.setzen("chat:c1", "berechtigungsmodus_chat", "restricted")
    settings.setzen("modell:m1", "berechtigungsmodus_chat", "restricted")

    address = "/api/v1/settings/resolved/berechtigungsmodus_chat?chat=c1&modell=m1"
    nothing_global = client.get(address).json()
    assert nothing_global["wert"] == {}
    assert nothing_global["scope"] is None

    settings.setzen("global", "berechtigungsmodus_chat", "auto")
    single = client.get(address).json()
    many = client.get(
        "/api/v1/settings/resolved?keys=berechtigungsmodus_chat&chat=c1&modell=m1"
    ).json()["berechtigungsmodus_chat"]
    for answer in (single, many):
        assert answer["wert"] == "auto"
        assert answer["scope"] == "global"


# --- Asked without a list: every setting --------------------------------------


def test_without_keys_the_answer_holds_every_setting_of_the_table_in_its_order(client):
    answer = client.get("/api/v1/settings/resolved")
    assert answer.status_code == 200, answer.text
    assert list(answer.json()) == list(PRUEFER)


def test_a_setting_that_stands_only_in_the_table_is_in_the_answer(client, monkeypatch):
    monkeypatch.setitem(einstellungen.PRUEFER, "only_in_the_table", lambda value: value)
    client.put("/api/v1/settings/global/only_in_the_table", json={"wert": "here"})

    answer = client.get("/api/v1/settings/resolved").json()
    assert list(answer)[-1] == "only_in_the_table"
    assert answer["only_in_the_table"] == {"wert": "here", "herkunft": {}, "scope": "global"}


def test_without_keys_the_chat_and_the_model_asked_for_still_count(client):
    client.put("/api/v1/settings/global/klaenge", json={"wert": {"an": True, "pegel": 42}})
    client.put("/api/v1/settings/chat:c1/klaenge", json={"wert": {"pegel": 7}})

    answer = client.get("/api/v1/settings/resolved?chat=c1").json()
    assert answer["klaenge"]["wert"] == {"an": True, "pegel": 7}
    assert answer["klaenge"]["herkunft"] == {"an": "global", "pegel": "chat:c1"}


def test_with_keys_the_route_answers_as_it_always_did(client):
    """The quiet case: the keys asked for, in the order asked, duplicates
    collapsed, and an empty list still a mistake."""
    client.put("/api/v1/settings/global/klaenge", json={"wert": {"an": True}})

    answer = client.get("/api/v1/settings/resolved?keys=parameter,klaenge,,parameter")
    assert answer.status_code == 200, answer.text
    assert list(answer.json()) == ["parameter", "klaenge"]
    assert answer.json()["klaenge"]["wert"] == {"an": True}

    for empty in ("keys=", "keys=,%20,"):
        refused = client.get(f"/api/v1/settings/resolved?{empty}")
        assert refused.status_code == 400
        assert refused.json() == {"detail": t("fehler.einstellung_keys_leer", "de")}


# --- The scope of a value that is not a set ------------------------------------


def test_a_single_value_names_the_scope_it_comes_from(client):
    client.put("/api/v1/settings/global/verdichtung_schwelle", json={"wert": 70})

    for address in (
        "/api/v1/settings/resolved/verdichtung_schwelle",
        "/api/v1/settings/resolved/verdichtung_schwelle?chat=c1&modell=m1",
    ):
        answer = client.get(address).json()
        assert answer["wert"] == 70
        assert answer["herkunft"] == {}
        assert answer["scope"] == "global"

    client.put("/api/v1/settings/modell:m1/verdichtung_schwelle", json={"wert": 60})
    of_the_model = client.get(
        "/api/v1/settings/resolved?keys=verdichtung_schwelle&chat=c1&modell=m1"
    ).json()["verdichtung_schwelle"]
    assert of_the_model == {"wert": 60, "herkunft": {}, "scope": "modell:m1"}

    client.put("/api/v1/settings/chat:c1/verdichtung_schwelle", json={"wert": 50})
    of_the_chat = client.get(
        "/api/v1/settings/resolved?keys=verdichtung_schwelle&chat=c1&modell=m1"
    ).json()["verdichtung_schwelle"]
    assert of_the_chat == {"wert": 50, "herkunft": {}, "scope": "chat:c1"}

    # Another chat does not see this chat's value.
    elsewhere = client.get(
        "/api/v1/settings/resolved?keys=verdichtung_schwelle&chat=c2"
    ).json()["verdichtung_schwelle"]
    assert elsewhere == {"wert": 70, "herkunft": {}, "scope": "global"}


def test_a_list_names_the_scope_it_comes_from(client):
    client.put("/api/v1/settings/global/modelle_aus", json={"wert": ["a"]})
    client.put("/api/v1/settings/chat:c1/modelle_aus", json={"wert": ["b"]})

    answer = client.get("/api/v1/settings/resolved?keys=modelle_aus&chat=c1").json()
    assert answer["modelle_aus"] == {"wert": ["b"], "herkunft": {}, "scope": "chat:c1"}


def test_a_value_no_scope_has_set_names_none(client):
    answer = client.get("/api/v1/settings/resolved?keys=verdichtung_schwelle,parameter").json()
    assert answer["verdichtung_schwelle"] == {"wert": {}, "herkunft": {}, "scope": None}
    assert answer["parameter"] == {"wert": {}, "herkunft": {}, "scope": None}


def test_the_fields_of_a_set_of_values_name_their_scopes_as_they_always_did(client):
    """The quiet case: a set of values is answered field by field, and
    names no scope for itself as a whole."""
    client.put("/api/v1/settings/global/klaenge", json={"wert": {"an": True, "pegel": 42}})
    client.put("/api/v1/settings/chat:c1/klaenge", json={"wert": {"pegel": 7}})

    single = client.get("/api/v1/settings/resolved/klaenge?chat=c1").json()
    many = client.get("/api/v1/settings/resolved?keys=klaenge&chat=c1").json()["klaenge"]
    for answer in (single, many):
        assert answer["wert"] == {"an": True, "pegel": 7}
        assert answer["herkunft"] == {"an": "global", "pegel": "chat:c1"}
        assert answer["scope"] is None


def test_a_set_over_a_single_value_names_fields_and_a_single_value_over_a_set_its_scope(client):
    settings = client.app.state.repositories.einstellungen
    settings.setzen("global", "mixed", ["x"])
    settings.setzen("chat:c1", "mixed", {"a": 1})
    assert settings.value_and_origin("mixed", chat="c1") == ({"a": 1}, {"a": "chat:c1"}, None)

    settings.setzen("global", "mixed", {"a": 1})
    settings.setzen("chat:c1", "mixed", ["x"])
    assert settings.value_and_origin("mixed", chat="c1") == (["x"], {}, "chat:c1")
    assert settings.value_and_origin("mixed") == ({"a": 1}, {"a": "global"}, None)
