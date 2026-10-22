"""A request the service refuses with 422 says why in the log.

The access line names the status and nothing else, so a request refused by
the checks of its body could not be told from one a route refused for its
content. Both now leave a line of their own at WARNING level with the
method, the path and the reason: the field and the kind of check, or the
sentence the route carries. The value that was refused, and what a file
held, never stand in it; the answer to the window stays as it was.
"""

from __future__ import annotations

import logging

import pytest

from app import input_errors

LOGGER = "app.input_errors"
TOO_LONG = {"name": "probe", "inhalt": "x" * 100_001}


def _refusals(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER and record.levelno == logging.WARNING
    ]


def test_a_request_without_a_required_field_names_the_field_in_the_log(client, caplog):
    chat = client.post("/api/v1/chats", json={"title": "Refusals"}).json()
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        response = client.post(f"/api/v1/documents?chat_id={chat['id']}", content=b"text")

    assert response.status_code == 422
    assert _refusals(caplog) == ["Refused POST /api/v1/documents (422): name missing"]


def test_a_document_of_blanks_names_the_sentence_the_route_carries(client, caplog):
    chat = client.post("/api/v1/chats", json={"title": "Refusals"}).json()
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        response = client.post(
            f"/api/v1/documents?chat_id={chat['id']}&name=blank.txt", content=b"   \n  "
        )

    assert response.status_code == 422
    (line,) = _refusals(caplog)
    assert line == f"Refused POST /api/v1/documents (422): {response.json()['detail']}"


def test_the_refused_value_does_not_stand_in_the_line(client, caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        response = client.post("/api/v1/skills", json=TOO_LONG)

    assert response.status_code == 422
    (line,) = _refusals(caplog)
    assert line == "Refused POST /api/v1/skills (422): inhalt string_too_long"
    # And the answer to the window is the one it always was.
    (entry,) = response.json()["detail"]
    assert entry["type"] == "string_too_long" and "input" not in entry


def test_a_key_nobody_declared_is_named_by_its_kind_only():
    long_name = "k" * 5_000
    entry = {"type": "extra_forbidden", "loc": ("body", long_name)}
    assert input_errors._refused_in_words(entry) == "extra_forbidden"


def test_silence_an_answer_that_is_no_422_writes_no_refusal_line(client, caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        missing = client.get("/api/v1/documents/does-not-exist")
        fine = client.get("/api/v1/chats")

    assert missing.status_code == 404 and fine.status_code == 200
    assert _refusals(caplog) == []
