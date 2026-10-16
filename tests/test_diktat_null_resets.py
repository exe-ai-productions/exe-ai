"""A dictation value sent as null goes back to the works answer.

An emptied number field ("Pause vor dem Senden", the voice's top-k, its GPU
layers) sent null by PATCH — and the service answered 400, "could not be
saved", because the check drops a null and the write had nothing left. The
field then jumped back to the old number. Now a null takes the key out of the
stored row; the works answer stands, and the field says "Auto" or its works
value again.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

ROW = "/api/v1/settings/global/diktat"
RESOLVED = "/api/v1/settings/resolved/diktat"


def _stored(client: TestClient) -> dict:
    return client.get(RESOLVED).json()["wert"] or {}


def test_a_patched_null_unsets_the_three_values(client: TestClient):
    assert client.patch(ROW, json={"wert": {
        "conversation_pause_seconds": 1.5, "stimmtop_k": 20, "stimmschichten": 12,
    }}).status_code == 200
    stored = _stored(client)
    assert stored["conversation_pause_seconds"] == 1.5
    assert stored["stimmtop_k"] == 20
    assert stored["stimmschichten"] == 12

    answer = client.patch(ROW, json={"wert": {
        "conversation_pause_seconds": None, "stimmtop_k": None, "stimmschichten": None,
    }})
    assert answer.status_code == 200, answer.text
    stored = _stored(client)
    for name in ("conversation_pause_seconds", "stimmtop_k", "stimmschichten"):
        assert name not in stored, name


def test_the_works_answer_stands_after_the_null(client: TestClient):
    client.patch(ROW, json={"wert": {"conversation_pause_seconds": 9.0}})
    client.patch(ROW, json={"wert": {"conversation_pause_seconds": None}})
    shown = client.get("/api/v1/sprachserver").json()["diktat_vorgaben"]
    assert shown["conversation_pause_seconds"] == 3.0
    assert "conversation_pause_seconds" not in _stored(client)


def test_a_null_for_one_value_leaves_the_others_alone(client: TestClient):
    client.patch(ROW, json={"wert": {"conversation_pause_seconds": 2.0, "stimmtop_k": 33}})
    client.patch(ROW, json={"wert": {"conversation_pause_seconds": None}})
    stored = _stored(client)
    assert stored["stimmtop_k"] == 33
    assert "conversation_pause_seconds" not in stored


def test_a_null_on_a_row_that_never_had_the_value_is_not_an_error(client: TestClient):
    assert client.patch(ROW, json={"wert": {"stimmtop_k": None}}).status_code == 200


def test_it_holds_for_every_dictation_value_not_only_the_pause(client: TestClient):
    from app import diktatsprachewahl

    client.patch(ROW, json={"wert": {"sprache": "de", "automatik": True, "putzkontext": 4096}})
    nulls = {name: None for name in diktatsprachewahl.vorgaben()}
    assert client.patch(ROW, json={"wert": nulls}).status_code == 200
    assert _stored(client) == {}


def test_a_value_sent_with_a_number_is_stored_as_before(client: TestClient):
    """The silence check: only a null unsets; a number is judged and stored
    the way it always was."""
    client.patch(ROW, json={"wert": {"stimmtop_k": 40}})
    assert _stored(client)["stimmtop_k"] == 40
    assert client.patch(ROW, json={"wert": {"stimmtop_k": "no number"}}).status_code in (200, 400)


def test_a_key_the_row_does_not_know_is_still_refused(client: TestClient):
    """The other silence check: a null is no way to write a key that is not
    part of the dictation row."""
    answer = client.patch(ROW, json={"wert": {"not_a_dictation_key": None}})
    assert answer.status_code == 400
