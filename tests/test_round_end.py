"""The one step between two rounds of a chat answer or a job run
(app/round_end.py): report, clear, report again, fold — and every reading it
reports is where the next ones estimate from.

Two faults it closes, both in the context bar: a live reading of the next
round estimated from the total BEFORE this round's tool results, so the bar
jumped back below the number just reported; and a fold that left the reading
of the longer request standing, so the next answer folded again at once over
a number that was gone.
"""

from __future__ import annotations

from app import antwortgrenze, round_end, verdichtung, werkzeugkuerzung
from app.kontextverbrauch import Kontextstand
from app.providers import ChatNachricht, ProviderFehler, mock_endpunkt
from app.providers.base import Stueck, Werkzeugaufruf
from tests.conftest import (
    FENSTER,
    GROSS,
    UEBER_DER_SCHWELLE,
    UNTER_DER_SCHWELLE,
    GrosseWerkzeugkette,
    GrossesErgebnis,
    provider_setzen,
    senden,
)
from tests.test_auftraege_api import mcp_client as _mcp_client

mcp_client = _mcp_client


def _readings(events: list[dict]) -> list[int]:
    return [e["gesamt_tokens"] for e in events if e["typ"] == "kontext"]


class _FloorOnlyChain(GrosseWerkzeugkette):
    """A server that counts only what was not cached (llama.cpp's
    ``prompt_n``): the first round reports its whole total, every later one
    only a small floor while it writes, and nothing exact at its end."""

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        self.echte_runden += 1
        if self.echte_runden == 1:
            yield Stueck("content", text="step 1")
            yield Stueck("stats", daten={"nutzung": {"total_tokens": self.stand}})
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[Werkzeugaufruf(id="w1", name="riesig", argumente={})],
            )
            return
        yield Stueck(
            "kontext",
            daten={"prompt_tokens": 500, "prompt_genau": False, "erzeugte_tokens": 20},
        )
        yield Stueck("content", text="done")


def test_the_next_round_estimates_from_the_reading_just_reported(mcp_client):
    """After the round's results were reported, the next round's live
    reading starts from that number — the bar does not fall back below it."""
    mcp_client.app.state.werkzeuge = GrossesErgebnis(gross="y" * 40_000)
    provider_setzen(
        mcp_client, _FloorOnlyChain(mock_endpunkt("test"), runden=1, stand=UNTER_DER_SCHWELLE)
    )
    mcp_client.app.state.discovery.zustaende["test"].context_tokens = FENSTER
    chat_id = mcp_client.post("/api/v1/chats", json={"title": "x"}).json()["id"]

    readings = _readings(senden(mcp_client, chat_id))

    between = next(r for r in readings if r > UNTER_DER_SCHWELLE)
    after = readings[readings.index(between) + 1:]
    assert after, readings
    assert all(r >= between for r in after), readings


def test_silent_a_round_without_tools_reports_its_own_reading(mcp_client):
    """No round end, no extra reading, nothing raised."""
    mcp_client.app.state.werkzeuge = GrossesErgebnis(gross=GROSS)
    provider_setzen(
        mcp_client,
        GrosseWerkzeugkette(mock_endpunkt("test"), runden=0, stand=UNTER_DER_SCHWELLE),
    )
    mcp_client.app.state.discovery.zustaende["test"].context_tokens = FENSTER
    chat_id = mcp_client.post("/api/v1/chats", json={"title": "x"}).json()["id"]

    assert _readings(senden(mcp_client, chat_id)) == [UNTER_DER_SCHWELLE]


class _FoldsThenFails(GrosseWerkzeugkette):
    """One tool round over the threshold — the fold between the rounds
    happens — and the round after it fails before it reports anything."""

    async def streamen(self, anfrage):
        last = anfrage.nachrichten[-1]
        if last.role == "user" and (last.content or "").startswith(
            verdichtung.ANFRAGE_TEXT
        ):
            self.faltungen += 1
            yield Stueck("content", text="summary")
            return
        self.echte_runden += 1
        if self.echte_runden == 1:
            yield Stueck("content", text="step 1 " + "z" * 60_000)
            yield Stueck("stats", daten={"nutzung": {"total_tokens": self.stand}})
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[Werkzeugaufruf(id="w1", name="riesig", argumente={})],
            )
            return
        raise ProviderFehler("connection refused")


def test_after_a_fold_the_reading_is_the_folded_request(mcp_client):
    """The fold between the rounds took the middle out: the reading reported
    after it is what the folded request weighs, and that is what the answer
    keeps when the next round never reports — not the longer request's."""
    mcp_client.app.state.werkzeuge = GrossesErgebnis(gross=GROSS)
    provider = provider_setzen(
        mcp_client, _FoldsThenFails(mock_endpunkt("test"), runden=1, stand=UEBER_DER_SCHWELLE)
    )
    mcp_client.app.state.discovery.zustaende["test"].context_tokens = FENSTER
    chat_id = mcp_client.post("/api/v1/chats", json={"title": "x"}).json()["id"]
    repositories = mcp_client.app.state.repositories
    for number in range(12):
        repositories.messages.speichern(
            chat_id=chat_id, role="user", content=f"question {number} " + "x" * 8_000
        )
        repositories.messages.speichern(
            chat_id=chat_id, role="assistant", content=f"answer {number} " + "x" * 8_000,
            zustand="fertig",
        )

    readings = _readings(senden(mcp_client, chat_id))

    assert provider.faltungen == 1, readings
    trigger = max(readings)
    assert readings[-1] < trigger, readings
    stored = mcp_client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"][-1]
    assert stored["gesamt_tokens"] == readings[-1]


async def test_the_step_weighs_the_folded_request(monkeypatch):
    """Unit view: after a fold that changed the request, the last outcome
    is the reading of the request as it now stands."""
    messages = [ChatNachricht(role="user", content="q " + "x" * 4_000) for _ in range(6)]
    request = type("Request", (), {})()
    request.nachrichten = messages
    request.werkzeuge = []
    state = type("State", (), {"context_tokens": 10_000})()

    async def folding(state, request, budget, **_named):
        request.nachrichten[:] = [ChatNachricht(role="user", content="summary")]
        return verdichtung.Ergebnis(angewendet=True)

    monkeypatch.setattr(verdichtung, "verdichten", folding)
    monkeypatch.setattr(verdichtung, "noetig", lambda *_a, **_k: True)

    outcomes = [
        step
        async for step in round_end.between_rounds(
            state,
            request,
            last_reading=9_000,
            appended_from=len(messages),
            threshold=50.0,
            set_limit=None,
            fold_allowed=True,
            key="k",
            settings=None,
            endpoint_id="test",
        )
    ]

    assert isinstance(outcomes[0], Kontextstand) and outcomes[0].tokens == 9_000
    assert isinstance(outcomes[-2], round_end.Folded)
    assert isinstance(outcomes[-1], Kontextstand)
    assert outcomes[-1].tokens == antwortgrenze.eingabe_schaetzen(request.nachrichten, [])


async def test_silent_no_fold_no_second_reading(monkeypatch):
    """Under the threshold: one reading, nothing cleared, nothing folded."""
    request = type("Request", (), {})()
    request.nachrichten = [ChatNachricht(role="user", content="q")]
    request.werkzeuge = []
    state = type("State", (), {"context_tokens": 10_000})()

    outcomes = [
        step
        async for step in round_end.between_rounds(
            state,
            request,
            last_reading=1_000,
            appended_from=1,
            threshold=50.0,
            set_limit=None,
            fold_allowed=True,
            key="k",
            settings=None,
            endpoint_id="test",
        )
    ]

    assert len(outcomes) == 1
    assert outcomes[0].tokens == 1_000


def _picture_request(count: int):
    from app import werkzeugbild

    request = type("Request", (), {})()
    request.nachrichten = [ChatNachricht(role="user", content="q")] + [
        werkzeugbild.nachricht(
            [f"bild{n}.png"], [f"data:image/png;base64,AAA{n}"], [f"/ordner/bild{n}.png"]
        )
        for n in range(count)
    ]
    request.werkzeuge = []
    return request


async def test_old_tool_pictures_are_retired_on_every_round_not_only_at_the_threshold():
    """Far below the threshold: one picture over the limit makes the oldest
    batch leave, in the request alone, and the step says so."""
    over = werkzeugkuerzung.OUTBOUND_IMAGE_LIMIT + 1
    batch = werkzeugkuerzung.IMAGE_EVICTION_BATCH
    request = _picture_request(over)
    state = type("State", (), {"context_tokens": 1_000_000})()

    outcomes = [
        step
        async for step in round_end.between_rounds(
            state,
            request,
            last_reading=1_000,
            appended_from=1,
            threshold=50.0,
            set_limit=None,
            fold_allowed=True,
            key="k",
            settings=None,
            endpoint_id="test",
        )
    ]

    cleared = [o for o in outcomes if isinstance(o, round_end.Cleared)]
    assert len(cleared) == 1 and cleared[0].count == batch
    assert len(cleared[0].before) == len(cleared[0].after) == len(request.nachrichten)
    assert len([n for n in request.nachrichten if n.alle_bild_urls()]) == over - batch
    # The readings come before and after it, never in place of it.
    assert isinstance(outcomes[0], Kontextstand)


async def test_silent_three_pictures_below_the_threshold_clear_nothing():
    request = _picture_request(3)
    state = type("State", (), {"context_tokens": 1_000_000})()

    outcomes = [
        step
        async for step in round_end.between_rounds(
            state,
            request,
            last_reading=1_000,
            appended_from=1,
            threshold=50.0,
            set_limit=None,
            fold_allowed=True,
            key="k",
            settings=None,
            endpoint_id="test",
        )
    ]

    assert not [o for o in outcomes if isinstance(o, round_end.Cleared)]
    assert len([n for n in request.nachrichten if n.alle_bild_urls()]) == 3
