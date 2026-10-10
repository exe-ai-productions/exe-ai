"""A tool round hands the model only what THAT round said.

The history entry written after a round used to carry the whole answer so
far — every round, the text of every round before it. A run of forty rounds
showed the model its own opening forty times, each copy longer than the last,
and the prompt grew with the square of the round count. Measured: one
stored answer with its own first paragraph thirteen times
inside it, 112k prompt tokens on a chat with two questions. A small model
takes that shape for the rule and writes the answer from the top again — and
the recap then lands in the row AND in the next history entry.

The first test nails the premise the old code got wrong: whichever round it
is, the opening sentence stands in the model's request ONCE. The second checks
that nothing is lost on the way — the rounds' texts together are still the
whole answer, on the stream and in the stored row.
"""

from __future__ import annotations

import json
from typing import AsyncIterator

from app.providers import MockProvider, mock_endpunkt
from app.providers.base import Generierungsanfrage, Stueck, Werkzeugaufruf
from app.verlaufsbau import _verlauf_bauen
from tests.conftest import provider_setzen
from tests.test_frage_werkzeug import _spaeter_antworten


class _Drehbuch(MockProvider):
    """A model that speaks and calls a tool twice, then only speaks.

    The request's message list is the very object the loop appends to, so a
    reference kept from an earlier call would show the final history for
    every round. Each call therefore takes a copy of what it was shown.
    """

    def __init__(self) -> None:
        super().__init__(mock_endpunkt("test"))
        self.runden = [
            ("Erstens. ", [Werkzeugaufruf(id="a1", name="zaehlen", argumente={"n": 1})]),
            ("Zweitens. ", [Werkzeugaufruf(id="a2", name="zaehlen", argumente={"n": 2})]),
            ("Drittens.", []),
        ]
        # Per call: (role, content, ids of the calls it carries) for every
        # message the model was shown.
        self.gesehen: list[list[tuple[str, str, list[str]]]] = []

    async def streamen(self, anfrage: Generierungsanfrage) -> AsyncIterator[Stueck]:
        self.gesehen.append(
            [
                (n.role, n.content, [a.id for a in n.werkzeugaufrufe])
                for n in anfrage.nachrichten
            ]
        )
        text, aufrufe = self.runden[len(self.gesehen) - 1]
        yield Stueck("content", text)
        if aufrufe:
            yield Stueck("tool_call", werkzeugaufrufe=aufrufe)
        yield Stueck(
            "stats", daten={"dauer_sekunden": 0.0, "haeppchen": 1, "endpunkt": self.id}
        )


class _Zaehlwerk:
    """The one tool the script calls — answers at once, needs no confirmation."""

    def als_openai_werkzeuge(self, nur=None, shell_zeitgrenze=None, bild_fenster=None, **_options):
        return [{"type": "function", "function": {"name": "zaehlen", "parameters": {}}}]

    def braucht_bestaetigung(self, name, argumente=None, ordner=None):
        return False

    def server_von(self, name):
        return ""

    def bestaetigungsgrund(self, name, argumente=None, ordner=None):
        return ""

    async def ausfuehren(
        self, name, argumente, bild_senke=None, ordner=None, chat_id=None,
        shell_zeitgrenze=None, **_rest,
    ):
        return f"gezaehlt bis {argumente['n']}"


def _drei_runden(client, chat_id):
    client.app.state.werkzeuge = _Zaehlwerk()
    client.app.state.config.features.mcp = True
    modell = provider_setzen(client, _Drehbuch())
    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Zähl mal."},
    )
    ereignisse = [
        json.loads(z[5:].strip()) for z in antwort.text.splitlines() if z.startswith("data:")
    ]
    return modell, ereignisse


def _assistent(runde):
    return [(content, ids) for role, content, ids in runde if role == "assistant"]


def test_die_eroeffnung_steht_in_jeder_runde_genau_einmal_im_verlauf(client, chat_id):
    """The wrong premise, nailed: the third round must not see 'Erstens.' twice.

    Under the old code the third request carried the assistant entries
    'Erstens. ' and 'Erstens. Zweitens. ' — the opening once per round.
    """
    modell, _ = _drei_runden(client, chat_id)
    assert len(modell.gesehen) == 3
    dritte = modell.gesehen[2]
    assert sum(content.count("Erstens.") for _, content, _ in dritte) == 1
    # Each later round starts one blank line below the one before
    # (app/reasoning.paragraph_break) — in the answer and in its own turn.
    assert _assistent(dritte) == [("Erstens. ", ["a1"]), ("\n\nZweitens. ", ["a2"])]


def test_die_runden_zusammen_sind_weiterhin_die_ganze_antwort(client, chat_id):
    """Nothing lost: the stream and the stored row carry every round's text,
    and the history keeps its shape — each call answered before the next turn."""
    modell, ereignisse = _drei_runden(client, chat_id)
    inhalt = "".join(e.get("text", "") for e in ereignisse if e["typ"] == "content")
    assert inhalt == "Erstens. \n\nZweitens. \n\nDrittens."
    zeile = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"][1]
    assert zeile["content"] == inhalt
    rollen = [role for role, _, _ in modell.gesehen[2]][-4:]
    assert rollen == ["assistant", "tool", "assistant", "tool"]


class _ZweiAntworten(MockProvider):
    """Three rounds in the first answer, one in the second — and a copy of
    every message list the model was shown, calls and all."""

    def __init__(self) -> None:
        super().__init__(mock_endpunkt("test"))
        self.runden = [
            ("Erstens. ", [Werkzeugaufruf(id="call_1", name="zaehlen", argumente={"n": 1})]),
            ("Zweitens. ", [Werkzeugaufruf(id="call_2", name="zaehlen", argumente={"n": 2})]),
            ("Drittens.", []),
            ("Viertens.", []),
        ]
        self.gesehen: list[list[tuple[str, str, list[tuple[str, str, dict]]]]] = []

    async def streamen(self, anfrage: Generierungsanfrage) -> AsyncIterator[Stueck]:
        self.gesehen.append(
            [
                (
                    n.role,
                    n.content,
                    [(a.id, a.name, dict(a.argumente)) for a in n.werkzeugaufrufe],
                )
                for n in anfrage.nachrichten
            ]
        )
        text, aufrufe = self.runden[len(self.gesehen) - 1]
        yield Stueck("content", text)
        if aufrufe:
            yield Stueck("tool_call", werkzeugaufrufe=aufrufe)
        yield Stueck(
            "stats", daten={"dauer_sekunden": 0.0, "haeppchen": 1, "endpunkt": self.id}
        )


def _zwei_antworten(client, chat_id):
    client.app.state.werkzeuge = _Zaehlwerk()
    client.app.state.config.features.mcp = True
    # tool_calls is undetermined until a real /props probe answers it — the
    # test endpoint never gets one, so the capability is pinned by hand,
    # the same way test_grundprompt.py and test_werkzeugwahl.py do it.
    client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
    modell = provider_setzen(client, _ZweiAntworten())
    for frage in ("Zähl mal.", "Und noch einmal."):
        client.post(
            "/api/v1/chat/completions",
            json={"chat_id": chat_id, "endpoint_id": "test", "content": frage},
        )
    return modell


def test_der_werkzeuglauf_geht_bei_der_naechsten_nachricht_wie_gesendet_zurueck(
    client, chat_id
):
    """The run's last request and the next answer's first one, byte for byte.

    Only then does the model server find what it already read: a rebuilt
    round with ids of its own, with cut results or in another order made it
    read everything from the first tool round on again — measured on a
    35B model, 3,051 of 11,713 tokens read again in the round that followed.
    """
    modell = _zwei_antworten(client, chat_id)

    assert len(modell.gesehen) == 4
    letzte_der_ersten = modell.gesehen[2]
    erste_der_zweiten = modell.gesehen[3]
    # Every message of the last request, then the closing text as its own
    # turn, then the new question — nothing else, nothing reordered.
    assert erste_der_zweiten[: len(letzte_der_ersten) + 1] == letzte_der_ersten + [
        ("assistant", "\n\nDrittens.", [])
    ]
    assert erste_der_zweiten[len(letzte_der_ersten) + 1][0] == "user"
    assert erste_der_zweiten[len(letzte_der_ersten) + 1][1].endswith("Und noch einmal.")
    assert len(erste_der_zweiten) == len(letzte_der_ersten) + 2
    # The calls come back under the ids the server gave them, in their own
    # round, each with its own result.
    assert [(i, n) for _, _, aufrufe in erste_der_zweiten for i, n, _ in aufrufe] == [
        ("call_1", "zaehlen"),
        ("call_2", "zaehlen"),
    ]



class _ZaehlUndFragewerk(_Zaehlwerk):
    """Counting as before, and ask_user beside it — answered with "A" the
    moment the run asks whether it needs a confirmation."""

    def __init__(self, client) -> None:
        self._client = client

    def als_openai_werkzeuge(self, nur=None, shell_zeitgrenze=None, bild_fenster=None, **_options):
        return [
            {"type": "function", "function": {"name": "zaehlen", "parameters": {}}},
            {"type": "function", "function": {"name": "ask_user", "parameters": {}}},
        ]

    def braucht_bestaetigung(self, name, argumente=None, ordner=None):
        if name == "ask_user":
            _spaeter_antworten(self._client, "A")
        return False


class _ZweiAntwortenMitFrage(_ZweiAntworten):
    """The same two answers, the second round asking the user instead of
    counting."""

    def __init__(self) -> None:
        super().__init__()
        self.runden[1] = (
            "Zweitens. ",
            [Werkzeugaufruf(id="call_2", name="ask_user", argumente={"question": "A oder B?"})],
        )


def test_eine_frage_an_den_nutzer_geht_wie_gesendet_zurueck(client, chat_id):
    """A run that asked the user goes back as it went out.

    The run sent the question as a call in its round and the user's answer
    as that call's result. The next answer's first request has to begin
    with those very messages — a sentence "[You asked: …]" in front of the
    rounds made it differ from the first message of that answer on, and the
    model server read all of it again.
    """
    client.app.state.werkzeuge = _ZaehlUndFragewerk(client)
    client.app.state.config.features.mcp = True
    client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
    modell = provider_setzen(client, _ZweiAntwortenMitFrage())
    for frage in ("Zähl mal.", "Und noch einmal."):
        client.post(
            "/api/v1/chat/completions",
            json={"chat_id": chat_id, "endpoint_id": "test", "content": frage},
        )

    assert len(modell.gesehen) == 4
    letzte_der_ersten = modell.gesehen[2]
    erste_der_zweiten = modell.gesehen[3]
    assert erste_der_zweiten[: len(letzte_der_ersten) + 1] == letzte_der_ersten + [
        ("assistant", "\n\nDrittens.", [])
    ]
    assert len(erste_der_zweiten) == len(letzte_der_ersten) + 2
    # The question as a call under its id, the answer as its result.
    assert ("assistant", "\n\nZweitens. ", [("call_2", "ask_user", {"question": "A oder B?"})]) in (
        erste_der_zweiten
    )
    stelle = erste_der_zweiten.index(
        ("assistant", "\n\nZweitens. ", [("call_2", "ask_user", {"question": "A oder B?"})])
    )
    assert erste_der_zweiten[stelle + 1] == ("tool", "A", [])
    assert not any("You asked" in inhalt for _, inhalt, _ in erste_der_zweiten)


def test_ohne_werkzeugangebot_steht_die_frage_genau_einmal_im_text(client, chat_id):
    """Silence probe on the text road: without tools the rounds go back as
    narration, and the question with its answer stands there once."""
    client.app.state.werkzeuge = _ZaehlUndFragewerk(client)
    client.app.state.config.features.mcp = True
    client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
    provider_setzen(client, _ZweiAntwortenMitFrage())
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Zähl mal."},
    )
    repositories = client.app.state.repositories
    verlauf = _verlauf_bauen(repositories.chats.holen(chat_id), repositories, "SYS", werkzeuge=False)
    text = " ".join(n.content for n in verlauf)

    assert text.count("A oder B?") == 1
    assert all(not n.werkzeugaufrufe for n in verlauf)


def test_ohne_werkzeugangebot_gehen_die_runden_als_text_zurueck(client, chat_id):
    """The silent case: a request that offers no tools reads the rounds as
    text, the way it always did — the calls are then narration, not calls."""
    client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
    _drei_runden(client, chat_id)
    repositories = client.app.state.repositories
    chat = repositories.chats.holen(chat_id)
    verlauf = _verlauf_bauen(chat, repositories, "SYS", werkzeuge=False)
    assert all(n.role != "tool" for n in verlauf)
    assert all(not n.werkzeugaufrufe for n in verlauf)
    assert "gezaehlt bis 1" in " ".join(n.content for n in verlauf)


class _Vielwerk:
    """A tool whose answer is longer than the ceiling a result travels with."""

    def als_openai_werkzeuge(self, nur=None, shell_zeitgrenze=None, bild_fenster=None, **_options):
        return [{"type": "function", "function": {"name": "viel", "parameters": {}}}]

    def braucht_bestaetigung(self, name, argumente=None, ordner=None):
        return False

    def server_von(self, name):
        return ""

    def bestaetigungsgrund(self, name, argumente=None, ordner=None):
        return ""

    async def ausfuehren(
        self, name, argumente, bild_senke=None, ordner=None, chat_id=None,
        shell_zeitgrenze=None, **_rest,
    ):
        return "\n".join(f"Zeile {n}: {'x' * 60}" for n in range(1, 451))


class _EinAufruf(MockProvider):
    """One tool round, then the closing text — and a second turn after it."""

    def __init__(self, name: str) -> None:
        super().__init__(mock_endpunkt("test"))
        self.runden = [
            ("Los. ", [Werkzeugaufruf(id="v1", name=name, argumente={})]),
            ("Fertig.", []),
            ("Nochmal.", []),
        ]
        self.gesehen: list[list[tuple[str, str, list[str]]]] = []

    async def streamen(self, anfrage: Generierungsanfrage) -> AsyncIterator[Stueck]:
        self.gesehen.append(
            [
                (n.role, n.content, [a.id for a in n.werkzeugaufrufe])
                for n in anfrage.nachrichten
            ]
        )
        text, aufrufe = self.runden[len(self.gesehen) - 1]
        yield Stueck("content", text)
        if aufrufe:
            yield Stueck("tool_call", werkzeugaufrufe=aufrufe)
        yield Stueck(
            "stats", daten={"dauer_sekunden": 0.0, "haeppchen": 1, "endpunkt": self.id}
        )


def test_ein_langes_ergebnis_geht_wie_gesendet_bei_der_naechsten_nachricht_zurueck(
    client, chat_id
):
    """The result is cut ONCE, where it arises — not a second time later.

    A result longer than the ceiling reached the model whole inside the run
    and truncated out of the row; the next request rebuilt the round from the
    row and handed back 20,000 characters where the model had read 30,000 —
    its own result, twice, and the prompt cache had nothing to reuse. Falls today: 30,000 against 20,000.
    """
    from app.api.v1.generierung import WERKZEUGERGEBNIS_GRENZE

    client.app.state.werkzeuge = _Vielwerk()
    client.app.state.config.features.mcp = True
    client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
    modell = provider_setzen(client, _EinAufruf("viel"))
    for frage in ("Lies mal.", "Und noch einmal."):
        client.post(
            "/api/v1/chat/completions",
            json={"chat_id": chat_id, "endpoint_id": "test", "content": frage},
        )

    assert len(modell.gesehen) == 3
    im_lauf = [c for r, c, _ in modell.gesehen[1] if r == "tool"]
    im_nachbau = [c for r, c, _ in modell.gesehen[2] if r == "tool"]
    assert len(im_lauf) == 1 and len(im_nachbau) == 1
    assert len(im_lauf[0]) == WERKZEUGERGEBNIS_GRENZE, "the result is not even shortened"
    assert im_nachbau[0] == im_lauf[0]
