"""`ask_user` — the model asks, the run waits.

Two halves, and both matter:

* the **check**, because a question with six options would arrive in a
  window that can only show four, and the two missing ones would silently
  never be offered,
* the **flow**, because the answer has to come back as the tool's result —
  a click and a typed sentence alike. If that link broke, the model would
  ask and then carry on as if nobody had said anything.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.providers import MockProvider, mock_endpunkt
from app.providers.base import Werkzeugaufruf
from app.tools import frage_werkzeug
from tests.conftest import provider_setzen


# --- The check -------------------------------------------------------------


def test_eine_frage_ohne_optionen_ist_erlaubt():
    frage, optionen = frage_werkzeug.gepruefte_frage({"question": "Welcher Weg?"})
    assert frage == "Welcher Weg?"
    assert optionen == []


def test_optionen_behalten_ihre_reihenfolge():
    _, optionen = frage_werkzeug.gepruefte_frage(
        {
            "question": "Welcher Weg?",
            "options": [
                {"label": "A", "description": "empfohlen"},
                {"label": "B"},
            ],
        }
    )
    assert [o["label"] for o in optionen] == ["A", "B"]
    assert optionen[0]["description"] == "empfohlen"
    assert optionen[1]["description"] == ""


def test_ohne_frage_geht_nichts():
    with pytest.raises(frage_werkzeug.FrageUngueltig):
        frage_werkzeug.gepruefte_frage({"question": "   "})


def test_mehr_als_vier_optionen_werden_abgelehnt():
    """Refused, not trimmed: trimming would show the user four of six and
    tell nobody about the other two."""
    with pytest.raises(frage_werkzeug.FrageUngueltig) as fehler:
        frage_werkzeug.gepruefte_frage(
            {
                "question": "Welcher Weg?",
                "options": [{"label": str(n)} for n in range(5)],
            }
        )
    assert "4" in str(fehler.value)


def test_eine_option_ohne_beschriftung_ist_keine():
    with pytest.raises(frage_werkzeug.FrageUngueltig):
        frage_werkzeug.gepruefte_frage(
            {"question": "Welcher Weg?", "options": [{"description": "ohne Namen"}]}
        )


# --- The flow through the chat ---------------------------------------------


class FrageRegistry:
    """Offers ask_user and nothing else. It is never executed — that is the
    point of the tool."""

    def __init__(self, client=None, antwort=None):
        self.ausgefuehrt = []
        self._client = client
        self._antwort = antwort

    def als_openai_werkzeuge(self, **_options):
        return [{"type": "function", "function": {"name": "ask_user", "parameters": {}}}]

    def known_names(self):
        """What this stand could resolve: the one tool it offers."""
        return {"ask_user"}

    def braucht_bestaetigung(self, name, argumente=None, ordner=None):
        # The answer is armed from in here, because this is the first thing
        # the run asks while its event loop is turning.
        if self._antwort is not None:
            _spaeter_antworten(self._client, self._antwort)
        return False

    def server_von(self, name):
        return "shell"

    def bestaetigungsgrund(self, name, argumente=None, ordner=None):
        return ""

    async def ausfuehren(self, name, argumente, bild_senke=None, ordner=None, chat_id=None):
        self.ausgefuehrt.append(name)
        return "sollte nie passieren"


def _spaeter_antworten(client, antwort):
    """Simulates the click, or the typed sentence — both travel one route."""
    verwaltung = client.app.state.generierungen

    def versuchen():
        for generierung in verwaltung.laufende():
            for aufruf_id in list(generierung.bestaetigungen):
                verwaltung.bestaetigen(generierung.id, aufruf_id, True, antwort)
                return True
        return False

    def takt():
        if not versuchen():
            asyncio.get_running_loop().call_later(0.01, takt)

    asyncio.get_running_loop().call_later(0.01, takt)


def _fragendes_modell(client, argumente, antwort=None):
    registry = FrageRegistry(client, antwort)
    client.app.state.werkzeuge = registry
    client.app.state.config.features.mcp = True
    provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["Gut."],
            werkzeugaufrufe=[Werkzeugaufruf(id="a1", name="ask_user", argumente=argumente)],
        ),
    )
    return registry


def _ereignisse(antwort):
    return [
        json.loads(z[5:].strip()) for z in antwort.text.splitlines() if z.startswith("data:")
    ]


def test_die_frage_geht_raus_und_die_antwort_kommt_zurueck(client, chat_id):
    registry = _fragendes_modell(
        client,
        {"question": "Welcher Weg?", "options": [{"label": "Links"}, {"label": "Rechts"}]},
        antwort="Links",
    )

    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "entscheide"},
    )
    ereignisse = _ereignisse(antwort)

    frage = next(e for e in ereignisse if e["typ"] == "user_ask")
    assert frage["frage"] == "Welcher Weg?"
    assert [o["label"] for o in frage["optionen"]] == ["Links", "Rechts"]

    ergebnis = next(e for e in ereignisse if e["typ"] == "tool_result")
    assert ergebnis["text"] == "Links"
    assert ergebnis["fehlgeschlagen"] is False
    # Measured too — how long the user took to answer, not how long a
    # confirmation prompt waited, since ask_user has none of its own.
    assert ergebnis["dauer_sekunden"] is not None
    # Never executed: there is nothing to execute.
    assert registry.ausgefuehrt == []


def test_freier_text_zaehlt_genauso(client, chat_id):
    _fragendes_modell(
        client,
        {"question": "Welcher Weg?", "options": [{"label": "Links"}]},
        antwort="Keins von beidem, nimm den dritten",
    )

    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "entscheide"},
    )
    ergebnis = next(e for e in _ereignisse(antwort) if e["typ"] == "tool_result")
    assert ergebnis["text"] == "Keins von beidem, nimm den dritten"


def test_eine_kaputte_frage_wird_dem_modell_gesagt(client, chat_id):
    """Five options never reach the window — the model is told why instead."""
    _fragendes_modell(
        client,
        {"question": "Welcher Weg?", "options": [{"label": str(n)} for n in range(5)]},
    )

    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "entscheide"},
    )
    ereignisse = _ereignisse(antwort)
    assert not any(e["typ"] == "user_ask" for e in ereignisse)
    ergebnis = next(e for e in ereignisse if e["typ"] == "tool_result")
    assert ergebnis["fehlgeschlagen"] is True
    # Silence probe: a call that really failed is no stop by the person.
    assert "stopped" not in ergebnis


# --- The call's result and its time -----------------------------------------


def _later_cancel(client):
    """Presses stop while the question stands — the run's own cancel."""
    manager = client.app.state.generierungen
    ticks = [0]

    def attempt():
        for run in manager.laufende():
            if run.bestaetigungen:
                manager.abbrechen(run.id)
                return True
        return False

    def tick():
        # Bounded: a question that never comes must not leave a timer
        # spinning on the loop after the test.
        ticks[0] += 1
        if not attempt() and ticks[0] < 500:
            asyncio.get_running_loop().call_later(0.01, tick)

    asyncio.get_running_loop().call_later(0.01, tick)


class CancellingRegistry(FrageRegistry):
    """Arms a stop instead of an answer."""

    def braucht_bestaetigung(self, name, argumente=None, ordner=None):
        _later_cancel(self._client)
        return False


def test_a_cancelled_question_gets_its_result(client, chat_id, monkeypatch):
    """Stopped while it waits on the person: the open call still gets a
    failed result before the run ends, so its row turns red instead of
    staying blue."""
    from app.api.v1 import generierung as chat_module
    from app.i18n import t

    monkeypatch.setattr(chat_module, "BESTAETIGUNG_PRUEFTAKT", 0.01)
    # A stop that never fires fails fast instead of after the whole wait.
    monkeypatch.setattr(chat_module, "BESTAETIGUNG_WARTEZEIT", 5)
    _fragendes_modell(client, {"question": "Welcher Weg?", "options": [{"label": "Links"}]})
    client.app.state.werkzeuge = CancellingRegistry(client)

    response = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "entscheide"},
    )
    events = _ereignisse(response)

    results = [e for e in events if e["typ"] == "tool_result"]
    assert len(results) == 1
    assert results[0]["aufruf_id"] == "a1"
    assert results[0]["fehlgeschlagen"] is True
    assert results[0]["bild"] is None
    assert results[0]["text"] == t("nachricht.abgebrochen_kurz", "de")
    # The result says the person stopped it, for every window that watches:
    # nothing failed, so none of them reports a failure.
    assert results[0]["stopped"] is True
    assert isinstance(results[0]["dauer_sekunden"], float)
    # The result comes after the question and before the run's end.
    kinds = [e["typ"] for e in events]
    assert kinds.index("user_ask") < kinds.index("tool_result") < kinds.index("done")

    # Stored for the next turn with the model's own copy: the window's word
    # is in the window's language, and a bare "stopped" does not tell the
    # model that the call never ran to an answer.
    rows = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"]
    entry = [z for z in rows if z["role"] == "assistant"][-1]["stats"]["werkzeuge"][0]
    assert entry["fehlgeschlagen"] is True
    assert entry["ergebnis"] == t("nachricht.abgebrochen_kurz", "de")
    assert entry["ergebnis_modell"] == "Tool execution cancelled"


def test_an_answered_question_has_one_successful_result(client, chat_id):
    """Silence probe: an answer still comes back as the one result it was."""
    _fragendes_modell(
        client, {"question": "Welcher Weg?", "options": [{"label": "Links"}]}, antwort="Links"
    )
    response = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "entscheide"},
    )
    results = [e for e in _ereignisse(response) if e["typ"] == "tool_result"]
    assert [(e["fehlgeschlagen"], e["text"]) for e in results] == [(False, "Links")]
    assert "stopped" not in results[0]
    # The model reads the answer itself, not the words of a cancelled call.
    rows = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"]
    entry = [z for z in rows if z["role"] == "assistant"][-1]["stats"]["werkzeuge"][0]
    assert entry["ergebnis"] == "Links"
    assert "ergebnis_modell" not in entry


def test_the_wait_on_the_person_is_not_the_calls_time(client, chat_id, monkeypatch):
    """The clock jumps a thousand seconds while the question stands; the
    call's time leaves that out."""
    import time
    import types

    from app.api.v1 import generierung as chat_module

    jump = [0.0]
    clock = types.SimpleNamespace(monotonic=lambda: time.monotonic() + jump[0], time=time.time)
    monkeypatch.setattr(chat_module, "time", clock)
    # A confirmation that never comes fails fast instead of after the wait.
    monkeypatch.setattr(chat_module, "BESTAETIGUNG_WARTEZEIT", 5)
    _fragendes_modell(client, {"question": "Welcher Weg?", "options": [{"label": "Links"}]})

    class JumpingRegistry(FrageRegistry):
        def braucht_bestaetigung(self, name, argumente=None, ordner=None):
            manager = self._client.app.state.generierungen

            def tick():
                for run in manager.laufende():
                    for call_id in list(run.bestaetigungen):
                        jump[0] = 1000.0
                        manager.bestaetigen(run.id, call_id, True, "Links")
                        return
                ticks[0] += 1
                # Bounded, like `_later_cancel`.
                if ticks[0] < 500:
                    asyncio.get_running_loop().call_later(0.01, tick)

            ticks = [0]
            asyncio.get_running_loop().call_later(0.01, tick)
            return False

    client.app.state.werkzeuge = JumpingRegistry(client)
    response = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "entscheide"},
    )
    result = next(e for e in _ereignisse(response) if e["typ"] == "tool_result")
    assert result["text"] == "Links"
    assert 0 <= result["dauer_sekunden"] < 100
