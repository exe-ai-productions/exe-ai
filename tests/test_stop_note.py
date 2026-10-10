"""The turn after a stopped reply tells the model that reply was stopped
(app/stop_note.py) — once, in front of the user's words, in the request only:
never stored and never shown. In a chat, and in work a job carries on after
its previous run was stopped.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from app import stop_note, zwischenstand
from app.agenten import agenten_laden
from app.api.v1.auftraege import auftrag_anstossen
from app.diktatsprachewahl import UNTERBRECHUNGSHINWEIS
from app.providers import MockProvider, mock_endpunkt
from tests.conftest import provider_setzen

ENDE = {"fertig", "abgebrochen", "gescheitert", "unterbrochen"}


def _send(client, chat_id: str, **fields):
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    response = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Go on", **fields},
    )
    assert response.status_code == 200
    return provider.letzte_anfrage


def _previous(client, chat_id: str, state: str) -> None:
    """The reply before the new turn. A reply the user stopped went through
    its closing write, which marks its figures stopped."""
    repositories = client.app.state.repositories
    repositories.messages.speichern(chat_id=chat_id, role="user", content="Tell me")
    repositories.messages.speichern(
        chat_id=chat_id,
        role="assistant",
        content="Half an ans",
        zustand=state,
        stats={"abgebrochen": True} if state == "abgebrochen" else None,
    )


def _newest_user(request) -> str:
    return [n for n in request.nachrichten if n.role == "user"][-1].content


def _all_text(request) -> str:
    return "\n".join(n.content or "" for n in request.nachrichten)


def test_the_turn_after_a_stopped_reply_carries_the_note(client, chat_id):
    _previous(client, chat_id, "abgebrochen")

    request = _send(client, chat_id)

    newest = _newest_user(request)
    assert f"{stop_note.STOP_NOTE}\n\nGo on" in newest
    assert _all_text(request).count(stop_note.STOP_NOTE) == 1
    # Never stored, never shown.
    rows = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"]
    assert all(stop_note.STOP_NOTE not in (r["content"] or "") for r in rows)


def test_silent_a_finished_reply_gets_no_note(client, chat_id):
    _previous(client, chat_id, "fertig")

    request = _send(client, chat_id)

    assert stop_note.STOP_NOTE not in _all_text(request)


def test_the_note_is_said_once_not_on_every_later_turn(client, chat_id):
    """The turn after the stopped reply carries it; the next turn follows a
    finished reply and does not."""
    _previous(client, chat_id, "abgebrochen")
    _send(client, chat_id)

    request = _send(client, chat_id, content="And then?")

    assert stop_note.STOP_NOTE not in _all_text(request)


def test_a_spoken_reply_cut_short_says_so_in_its_own_words_only(client, chat_id):
    """A spoken reply the user interrupted already carries the voice's note;
    the stop note does not come on top of it."""
    _previous(client, chat_id, "abgebrochen")

    request = _send(client, chat_id, gespraech=True, unterbrochen=True)

    text = _all_text(request)
    assert UNTERBRECHUNGSHINWEIS in text
    assert stop_note.STOP_NOTE not in text


def test_a_report_after_the_stopped_reply_is_not_followed_directly(client, chat_id):
    """Schweigeprobe: the service wrote after the stopped reply (a
    background run's report), so the new turn does not follow it directly."""
    _previous(client, chat_id, "abgebrochen")
    client.app.state.repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content="[run #1 finished]",
        art="werkzeugmeldung", zustand="fertig",
    )

    request = _send(client, chat_id)

    assert stop_note.STOP_NOTE not in _all_text(request)


# --- Work a job carries on --------------------------------------------------


async def _continued_run(
    client,
    config,
    origin_state: str,
    end_reason: str | None = None,
    *,
    between: tuple[str, str | None] | None = None,
):
    """A job run fired by the continuation of a run that ended in
    ``origin_state``; the request it sent. ``between`` is a run the same
    entry fired in the meantime — (its state, its ending) — which makes the
    new run the third in the chain."""
    folders = Path(config.app.agenten_verzeichnis)
    folders.mkdir(parents=True, exist_ok=True)
    (folders / "recherche.md").write_text("---\nmodel: test\n---\n\nResearch.\n", encoding="utf-8")
    repositories = client.app.state.repositories
    origin = repositories.auftraege.erstellen(user_id="standard", agent="recherche", auftrag="Sort")
    repositories.auftraege.zwischenstand_setzen(origin.id, "Half sorted.")
    origin = repositories.auftraege.holen(origin.id)
    assert zwischenstand.fortsetzung_planen(config, repositories, origin)
    repositories.auftraege.zustand_setzen(origin.id, origin_state, ende_grund=end_reason)
    (eintrag,) = repositories.cronjobs.auflisten()
    if between is not None:
        second = repositories.auftraege.erstellen(
            user_id="standard", agent="recherche", auftrag="Sort", cronjob_id=eintrag.id
        )
        repositories.auftraege.zustand_setzen(second.id, between[0], ende_grund=between[1])
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    job = auftrag_anstossen(
        config=client.app.state.config,
        repositories=repositories,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen,
        registry=None,
        agent=agenten_laden(folders)["recherche"],
        task=eintrag.task,
        endpoint_id=None,
        user_id="standard",
        sprache="de",
        cronjob_id=eintrag.id,
    )
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        row = repositories.auftraege.holen(job.id)
        if row is not None and row.zustand in ENDE:
            break
        await asyncio.sleep(0.01)
    return provider.letzte_anfrage, repositories.auftraege.holen(job.id)


async def test_work_carried_on_after_a_stopped_run_is_told_so(client, config):
    request, job = await _continued_run(
        client, config, "abgebrochen", stop_note.USER_STOP
    )

    newest = _newest_user(request)
    assert stop_note.STOP_NOTE in newest
    # The task as stored stays as it was given.
    assert stop_note.STOP_NOTE not in job.auftrag


async def test_silent_work_carried_on_after_a_handoff_is_not(client, config):
    request, _auftrag = await _continued_run(client, config, "unterbrochen")

    assert stop_note.STOP_NOTE not in _all_text(request)


async def test_silent_a_run_its_parent_ended_is_no_stop_of_the_user(client, config):
    request, _auftrag = await _continued_run(client, config, "abgebrochen", "eltern_abbruch")

    assert stop_note.STOP_NOTE not in _all_text(request)


def test_silent_a_reply_set_aside_at_start_is_no_stop_of_the_user(client, chat_id):
    # An answer still being written when the service went down; the next
    # start sets it aside as cut off.
    _previous(client, chat_id, "laeuft")
    repositories = client.app.state.repositories
    assert repositories.messages.beim_start_aufraeumen() == 1
    assert repositories.messages.letzte(chat_id=chat_id, role="assistant").zustand == "abgebrochen"

    assert stop_note.STOP_NOTE not in _all_text(_send(client, chat_id))


async def test_a_third_run_follows_the_second_not_the_first(client, config):
    """The first run was stopped, the second ended on its own: the third
    follows the second, so it is told nothing."""
    request, _auftrag = await _continued_run(
        client, config, "abgebrochen", stop_note.USER_STOP, between=("unterbrochen", None)
    )

    assert stop_note.STOP_NOTE not in _all_text(request)


async def test_a_third_run_after_a_stopped_second_is_told_so(client, config):
    request, _auftrag = await _continued_run(
        client, config, "unterbrochen", between=("abgebrochen", stop_note.USER_STOP)
    )

    assert stop_note.STOP_NOTE in _newest_user(request)
