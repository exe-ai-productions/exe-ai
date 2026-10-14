"""The frame around a refused job start.

A chat's model calls ``start_job`` and the start is refused. The sentence
goes two ways: the window shows it to the user, in the user's language, and
the model reads it as the result of its own call, always in English.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from app import helper
from app.api.v1 import auftraege
from app.api.v1.auftraege import Refusal, job_could_not_start
from app.i18n import t
from app.providers import MockProvider, mock_endpunkt
from app.providers.base import Werkzeugaufruf
from tests.conftest import provider_setzen
from tests.test_auftrag_werkzeug import StartRegistry, _ereignisse
from tests.test_helper import NamedRegistry

FRAME = {
    "en": "The job could not be started: ",
    "de": "Der Auftrag konnte nicht gestartet werden: ",
}

# What the refusal behind the frame names: the tool nobody has, and the agent.
REFUSED = {"namen": "no_such_tool", "agent": "courier"}


def _refused_start(client, chat_id, config, language: str) -> tuple[str, str]:
    """A chat's model starts an agent that names a tool nobody has: the
    start is refused. Returns what the window was shown and what the model
    read."""
    folder = Path(config.app.agenten_verzeichnis)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "courier.md").write_text(
        "---\nmax_rounds: 1\ntools: [no_such_tool]\n---\n\nDeliver things.\n",
        encoding="utf-8",
    )
    return _start(client, chat_id, language, {"agent": "courier", "task": "Collect the notes."})


def _start(client, chat_id, language: str, arguments: dict, registry=None) -> tuple[str, str]:
    """A chat's model calls ``start_job`` and the start is refused. Returns
    what the window was shown and what the model read."""
    client.app.state.werkzeuge = registry or StartRegistry(client)
    client.app.state.config.features.mcp = True
    provider = provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["Good."],
            werkzeugaufrufe=[Werkzeugaufruf(id="a1", name="start_job", argumente=arguments)],
        ),
    )
    answer = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "send it off"},
        headers={"X-Ui-Language": language},
    )
    shown = next(e for e in _ereignisse(answer) if e["typ"] == "tool_result")
    assert shown["fehlgeschlagen"] is True
    read = [m.content for m in provider.letzte_anfrage.nachrichten if m.role == "tool"]
    assert len(read) == 1
    return shown["text"], read[0]


def test_the_frame_is_one_catalogue_sentence_in_both_languages():
    assert t("jobs.could_not_start", "en", text="x") == FRAME["en"] + "x"
    assert t("jobs.could_not_start", "de", text="x") == FRAME["de"] + "x"


def test_with_a_german_window_the_user_reads_the_frame_in_german_and_the_model_in_english(
    client, chat_id, config
):
    shown, read = _refused_start(client, chat_id, config, "de")
    inside = t("fehler.werkzeug_unbekannt", "de", **REFUSED)
    assert shown == FRAME["de"] + inside
    assert read == FRAME["en"] + t("fehler.werkzeug_unbekannt", "en", **REFUSED)
    assert inside not in read


def test_with_an_english_window_both_read_the_sentence_as_they_always_did(
    client, chat_id, config
):
    """The quiet case."""
    shown, read = _refused_start(client, chat_id, config, "en")
    whole = FRAME["en"] + t("fehler.werkzeug_unbekannt", "en", **REFUSED)
    assert shown == whole
    assert read == whole


@pytest.mark.parametrize("language", ["en", "de"])
def test_a_copy_for_a_model_names_no_language_and_is_english(language):
    """A running job that tries to start another reads the frame as the
    result of its own call: English, whatever language the run carries."""
    refusal = Refusal(400, "fehler.kein_modell_verfuegbar", language)
    assert job_could_not_start(refusal.model) == (
        FRAME["en"] + t("fehler.kein_modell_verfuegbar", "en")
    )
    assert job_could_not_start(refusal.detail, language) == (
        FRAME[language] + t("fehler.kein_modell_verfuegbar", language)
    )


# One helper runs and one may: the next start is refused with 409.
AT_THE_LIMIT = {"running": 1, "limit": 1}


def _helper_at_the_limit(client) -> None:
    repos = client.app.state.repositories
    repos.einstellungen.setzen("global", helper.AT_ONCE_KEY, 1)
    repos.auftraege.erstellen(
        user_id="standard", agent=helper.HELPER_NAME, auftrag="A", zustand="laeuft"
    )


def test_a_helper_over_the_limit_reads_german_in_the_window_and_english_for_the_model(
    client, chat_id
):
    _helper_at_the_limit(client)

    shown, read = _start(
        client, chat_id, "de", {"task": "Collect the notes."},
        # The names a helper's tool list is made from.
        registry=NamedRegistry(client, True, None),
    )

    inside = t("jobs.helper_limit", "de", **AT_THE_LIMIT)
    assert shown == FRAME["de"] + inside
    assert read == FRAME["en"] + t("jobs.helper_limit", "en", **AT_THE_LIMIT)
    assert inside not in read
    assert len(client.get("/api/v1/jobs").json()) == 1


def test_every_refusal_of_a_start_carries_the_models_copy():
    """A model reads ``Refusal.model``. A refusal raised any other way has
    no English copy, and whoever asked would read the user's language."""
    source = ast.parse(inspect.getsource(auftraege.auftrag_anstossen))
    raised = [
        ast.unparse(node.exc.func)
        for node in ast.walk(source)
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)
    ]
    assert raised
    assert set(raised) == {"Refusal"}
