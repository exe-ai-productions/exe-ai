"""One module for the bar, the fold trigger and the proactive handoff.

Three readers used to ask two different modules. The bar and the fold
trigger read ``app/kontextdruck.py``; the handoff compared
``app/kontextverbrauch.py``'s reading against its own 90 per cent. Both
answer the same question at the handoff's moment — nothing has been
appended to the request since the round's own reading — but "the same
answer today" is not the same as "one way of asking", and the two rounded
separately.

What the two modules are NOT is interchangeable at the end of a round:
there ``kontextdruck`` answers what the NEXT request will carry, which is
larger by the round's own tool results. Measured at window 114688: 96000
tokens answered plus 8000 returned reads 83.7 per cent at the handoff and
90.7 at the trigger. Two questions, one module — and the fold at 80 per
cent (``app/verdichtungswahl.py``) exists so the handoff rarely has to
happen at all.
"""

from __future__ import annotations

import json

from app import fenstergroesse, kontextdruck, kontextverbrauch, zwischenstand
from app.providers import MockProvider, mock_endpunkt
from app.providers.base import Stueck, Werkzeugaufruf
from tests.conftest import provider_setzen
from tests.test_auftraege_api import agent_schreiben, auf_ende_warten

FENSTER = 10_000
# Above the handoff's threshold on the round's own measured reading: 92.0
# per cent of the window.
VOLL = 9_200
# Comfortably below it, and below the fold threshold too (80 per cent), so
# nothing at all fires: 65.0 per cent.
LEER = 6_500


class MitWerkzeugen(MockProvider):
    """Answers with one tool call, then plainly, reporting a fixed total."""

    def __init__(self, *args, gesamt: int, **kwargs):
        super().__init__(*args, **kwargs)
        self.gesamt = gesamt
        self.runden = 0

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        self.runden += 1
        if self.runden == 1:
            yield Stueck("content", text="looking")
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[
                    Werkzeugaufruf(id="w1", name="werkzeug_1", argumente={"a": 1})
                ],
            )
        else:
            yield Stueck("content", text="answer")
        yield Stueck(
            "stats",
            daten={
                "dauer_sekunden": 0.0,
                "haeppchen": 1,
                "endpunkt": self.id,
                "nutzung": {"total_tokens": self.gesamt},
                "ende_grund": "tool_calls" if self.runden == 1 else "stop",
            },
        )


def _lauf(client, config, gesamt: int) -> dict:
    agent_schreiben(config, kopf="model: test\nmax_rounds: 20")
    provider_setzen(client, MitWerkzeugen(mock_endpunkt("test"), gesamt=gesamt))
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.context_tokens = FENSTER
    zustand.kontext_quelle = fenstergroesse.QUELLE_EINGETRAGEN
    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Go"}
    ).json()["id"]
    return auf_ende_warten(client, kennung)


def _kontextzahlen(daten: dict) -> list[float]:
    """Every reading the bar was given, in the order it was given them."""
    return [
        json.loads(s["inhalt"])["prozent"]
        for s in daten["schritte"]
        if s["typ"] == "kontext"
    ]


def test_die_uebergabe_liest_durch_kontextdruck(client, config, monkeypatch):
    """The handoff asks the same module the bar and the trigger ask.

    Recognisable without reading the source: at the handoff's moment
    nothing has been appended since the round's reading, so it asks for a
    share with ZERO new tokens — a call the fold trigger at the end of the
    round never makes, because by then the round's tool results are new.
    Against the old stand no such call exists at all, and this test fails.
    """
    rufe: list[tuple[int | None, int]] = []
    echt = kontextdruck.stand

    def mitschreiben(letzter_stand, neu_tokens, fenster):
        rufe.append((letzter_stand, neu_tokens))
        return echt(letzter_stand, neu_tokens, fenster)

    monkeypatch.setattr(kontextdruck, "stand", mitschreiben)

    daten = _lauf(client, config, VOLL)

    assert (VOLL, 0) in rufe, rufe
    # And it acted on it: the run hands its work on rather than ending as a
    # failure (`unterbrochen` is this program's word for "can be resumed").
    assert daten["end_reason"] == "kontext_voll"
    assert daten["state"] == "unterbrochen"


def test_die_leiste_zeigt_die_zahl_bei_der_uebergeben_wird(client, config):
    """"One number, one truth": the last reading the bar was given before
    the run ended IS the number the handoff compared — 92.0 per cent of the
    10000-token window, rounded the one way `kontextdruck.stand` rounds."""
    daten = _lauf(client, config, VOLL)

    zahlen = _kontextzahlen(daten)
    assert zahlen[-1] == 92.0
    assert zahlen[-1] >= zwischenstand.SCHWELLE_PROZENT
    assert daten["end_reason"] == "kontext_voll"


def test_ein_lauf_unter_der_schwelle_uebergibt_nicht(client, config):
    """The silence test: 65 per cent is below the handoff's 90 and below the
    fold's 80, so neither fires and the run finishes the way it always did."""
    daten = _lauf(client, config, LEER)

    assert max(_kontextzahlen(daten)) < zwischenstand.SCHWELLE_PROZENT
    assert daten["end_reason"] == "fertig"
    assert daten["state"] == "fertig"


def test_beide_module_runden_gleich_und_nennen_dieselbe_zahl():
    """Why the change moves no number: at the handoff's moment the two
    modules answer identically, digit for digit, and that is the whole
    claim of this clean-up. Rounding included — `prozent` alone would not
    round, and 89.96 would be handed to a comparison the bar already shows
    as 90.0.
    """
    for tokens in (0, 1, 8_996, 9_000, 9_200, 89_960, 100_000):
        fenster = 100_000
        gemessen = kontextverbrauch.stand({"gesamt_tokens": tokens}, fenster)
        gelesen = kontextdruck.stand(tokens, 0, fenster)
        # Both guarded, not just one: either module answering `None` here is
        # the regression this test is about, and an AttributeError would
        # hide which of the two it was.
        assert gemessen is not None
        assert gelesen is not None
        assert gelesen.prozent == gemessen.prozent
        assert gelesen.tokens == gemessen.tokens

    # The unrounded share is the one that would disagree: 8996 of 10000 is
    # 89.96, which the bar shows as 90.0 and a raw comparison would keep
    # below the threshold.
    assert kontextdruck.prozent(8_996, 0, 10_000) < zwischenstand.SCHWELLE_PROZENT
    stand = kontextdruck.stand(8_996, 0, 10_000)
    assert stand is not None
    assert stand.prozent >= zwischenstand.SCHWELLE_PROZENT
