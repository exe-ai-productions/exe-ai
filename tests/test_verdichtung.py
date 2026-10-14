"""Compacting a job's own history in place — an addition
beside the context-full handoff (app/zwischenstand.py), not a replacement
for it.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any

import pytest

from app import (
    antwortgrenze,
    faltbitte,
    faltpause,
    kontextvoll,
    verdichtung,
    verlaufsbau,
)
from app.providers import ChatNachricht, Stueck
from app.providers.base import Werkzeugaufruf

# The run these tests compact for. One key for the whole file, cleared
# around every test: the fold pause lives in the module for the life of the
# process, and a pause one test booked would otherwise silently make the
# next one skip its request.
SCHLUESSEL = "lauf"


class _Uhr:
    """A clock the test moves itself, so a pause can be waited out without
    waiting."""

    def __init__(self):
        self.jetzt = 0.0

    def __call__(self) -> float:
        return self.jetzt

    def weiter(self, sekunden: float) -> None:
        self.jetzt += sekunden


@pytest.fixture(autouse=True)
def uhr(monkeypatch):
    faltpause.freigeben(SCHLUESSEL)
    gestellt = _Uhr()
    monkeypatch.setattr(faltpause, "uhr", gestellt)
    yield gestellt
    faltpause.freigeben(SCHLUESSEL)


def _nachricht(rolle: str, text: str, *, aufruf_id: str | None = None) -> ChatNachricht:
    return ChatNachricht(role=rolle, content=text, werkzeugaufruf_id=aufruf_id)


# How much one message weighs in these histories.
#
# The verbatim tail is a TOKEN budget now, not a message count, so a
# history of seven-character messages has no middle at all: the whole thing
# fits in the tail. Each message here is sized so that exactly twenty of
# them fill the budget — the boundary every test below was written around
# stays where it was, and the tests keep saying what they always said.
JE_NACHRICHT = verdichtung.LETZTE_ZEICHEN // 20


def _nachricht_gross(rolle: str, marke: str) -> ChatNachricht:
    """One message of the standard weight, still recognisable by its mark."""
    fuellung = "x" * (JE_NACHRICHT - len(marke))
    return _nachricht(rolle, f"{marke}{fuellung}")


def _lauf(anzahl: int) -> list[ChatNachricht]:
    """A plain back-and-forth of ``anzahl`` user/assistant pairs — no tool
    calls, the simple case every boundary test builds on."""
    nachrichten = []
    for i in range(anzahl):
        nachrichten.append(_nachricht_gross("user", f"frage {i}"))
        nachrichten.append(_nachricht_gross("assistant", f"antwort {i}"))
    return nachrichten


@dataclass
class _Anfrage:
    nachrichten: list[ChatNachricht]
    werkzeuge: list = field(default_factory=list)
    max_tokens: int | None = None
    modell: str | None = None
    parameter: dict = field(default_factory=dict)
    zusatz: dict = field(default_factory=dict)


class _StummerProvider:
    """Never answers — used where ``verdichten`` must return before it
    would ever call the provider at all."""

    async def streamen(self, anfrage):
        raise AssertionError("must not be called")
        yield  # pragma: no cover - makes this an async generator


class _Zusammenfasser:
    def __init__(self, antwort: str = "gerafft"):
        self.antwort = antwort
        self.gesehene_anfragen: list = []

    async def streamen(self, anfrage):
        self.gesehene_anfragen.append(anfrage)
        if self.antwort:
            yield Stueck("content", text=self.antwort)


def _ohne_schalter():
    """An endpoint whose model cannot be asked about thinking."""
    from app.providers import mock_endpunkt

    return mock_endpunkt("test")


def _anthropic_draht():
    """The same endpoint on the ANTHROPIC wire — the only wire where Auto
    still asks for a number (app/antwortgrenze.py)."""
    from app.providers import mock_endpunkt

    return mock_endpunkt("test", provider="anthropic")


@dataclass
class _Zustand:
    provider: object
    # `Any` and not `object`: a duck-typed stand-in — the tests below reach
    # for its attributes (capabilities, ...), which `object` does not name.
    endpunkt: Any = field(default_factory=_ohne_schalter)
    gemeldeter_name: str | None = None
    faehigkeiten_erkannt: dict | None = None
    # A reachable endpoint always has a resolved window (app/fenstergroesse.py),
    # and the summarizing request's own ceiling is worked out against it.
    # Large enough here that the tests below are about the boundary they are
    # each named for, not about the ceiling.
    context_tokens: int | None = 200_000
    hersteller_max_tokens: int | None = None

    def denkprofil(self, modell: str | None = None, abgelehnt=()):
        """What the real state answers about a hand-set thinking switch: off
        means this model cannot think at all, on means it can be switched
        (app/denkstufen.py). Asked since a thinking length may only travel
        where the knob is open."""
        from app.denkstufen import NEVER, Denkprofil

        art = NEVER if self.endpunkt.capabilities.thinking is False else "schalter"
        return Denkprofil(art=art)

    def _capabilities_aufloesen(self, modell: str | None = None, abgelehnt=()) -> dict:
        """The plain yes/no behind that profile, as the real state hands it to
        the wire question (app/discovery.py) — the same source the model list
        reads, so this stand-in cannot answer the two differently."""
        from app.denkstufen import NEVER

        profil = self.denkprofil(modell, abgelehnt)
        return {"reasoning": profil.art != NEVER, "thinking": profil.stufen}


class _Abgeschnittener:
    """Answers, and then says the ceiling cut the answer short."""

    async def streamen(self, anfrage):
        yield Stueck("content", text="## Done\n- half of")
        yield Stueck("stats", daten={"abgeschnitten": True, "ende_grund": "length"})


class _KontextfensterVoller:
    """Answers, and then says the whole context window ran out — a
    different reason than the answer's own length ceiling, but the same
    boolean the brake below reads."""

    async def streamen(self, anfrage):
        yield Stueck("content", text="## Done\n- half of")
        yield Stueck(
            "stats",
            daten={
                "abgeschnitten": True,
                "ende_grund": "model_context_window_exceeded",
            },
        )


async def test_die_faltung_erbt_die_antwortlaenge_des_nutzers_nicht():
    """A job's own ceiling is the user's choice for ANSWERS; a summary cut
    off by it would be stored whole and fold away rows it never got to speak
    for. So the summarizing request never carries it — on the OpenAI wire it
    carries no number at all, and the server decides."""
    fasser = _Zusammenfasser()
    nachrichten = _lauf(30)
    anfrage = _Anfrage(nachrichten=nachrichten, max_tokens=500)
    ergebnis = await verdichtung.verdichten(_Zustand(fasser), anfrage, schluessel=SCHLUESSEL)
    assert ergebnis.angewendet is True
    gesendet = fasser.gesehene_anfragen[0]
    assert gesendet.max_tokens is None


async def test_die_faltbitte_im_speicher_traegt_keine_werkzeuge():
    """The summary request offers no tools, as on the rows path: offered the
    run's tools, a model could answer with a call, and the fold reads that
    as an empty summary. Silence probe: the run's own request keeps them."""
    werkzeuge = [{"type": "function", "function": {"name": "read_file", "parameters": {}}}]
    fasser = _Zusammenfasser()
    anfrage = _Anfrage(nachrichten=_lauf(30), werkzeuge=list(werkzeuge))

    ergebnis = await verdichtung.verdichten(_Zustand(fasser), anfrage, schluessel=SCHLUESSEL)

    assert ergebnis.angewendet is True
    assert fasser.gesehene_anfragen[0].werkzeuge == []
    assert anfrage.werkzeuge == werkzeuge


async def test_der_deckel_der_faltbitte_rechnet_ohne_die_werkzeuge():
    """Tool definitions that alone would fill the window: the summary request
    does not carry them, so they take no room from it, and the model is
    asked."""
    werkzeuge = [
        {"type": "function", "function": {"name": "riesig", "description": "d" * 1_000_000}}
    ]
    fasser = _Zusammenfasser()
    anfrage = _Anfrage(nachrichten=_lauf(30), werkzeuge=werkzeuge)

    ergebnis = await verdichtung.verdichten(_Zustand(fasser), anfrage, schluessel=SCHLUESSEL)

    assert len(fasser.gesehene_anfragen) == 1
    assert ergebnis.angewendet is True


async def test_die_faltung_auf_dem_anthropic_draht_rechnet_wie_eine_antwort():
    """On the wire that needs a number the summary gets "Auto" measured
    against its own input — neither the run's number nor any fixed one."""
    fasser = _Zusammenfasser()
    nachrichten = _lauf(30)
    anfrage = _Anfrage(nachrichten=nachrichten, max_tokens=500)
    zustand = _Zustand(fasser, endpunkt=_anthropic_draht())
    ergebnis = await verdichtung.verdichten(zustand, anfrage, schluessel=SCHLUESSEL)
    assert ergebnis.angewendet is True
    gesendet = fasser.gesehene_anfragen[0]
    assert gesendet.max_tokens != 500
    eingabe = antwortgrenze.eingabe_schaetzen(gesendet.nachrichten)
    assert gesendet.max_tokens == 200_000 - eingabe - kontextvoll.SICHERHEITSABSTAND


async def test_die_faltung_bleibt_unter_dem_herstellerwert():
    """Where the provider names an output limit for this model, the
    summary's own ceiling is capped by it just like an answer's — on the
    wire that carries a number."""
    fasser = _Zusammenfasser()
    zustand = _Zustand(fasser, endpunkt=_anthropic_draht())
    zustand.hersteller_max_tokens = 8_000
    ergebnis = await verdichtung.verdichten(zustand, _Anfrage(nachrichten=_lauf(30)), schluessel=SCHLUESSEL)
    assert ergebnis.angewendet is True
    assert fasser.gesehene_anfragen[0].max_tokens == 8_000


async def test_die_faltung_rechnet_nicht_mit_einer_fremden_ablehnung():
    """A number a refusal named belongs to the request it happened to.
    A fold is its own request and must not inherit a ceiling
    left over from whatever the run asked before it — this is what the
    test of the fold on the Anthropic wire above already measures for the
    silent case (no prior refusal, nothing changes); here one is standing
    when the fold starts.

    And the other way round: the fold does not take that number away from
    the request it belongs to — that request still reads it for its retry."""
    fasser = _Zusammenfasser()
    zustand = _Zustand(fasser, endpunkt=_anthropic_draht())
    abgelehnt = antwortgrenze.Zug(max_tokens=50)
    ergebnis = await verdichtung.verdichten(zustand, _Anfrage(nachrichten=_lauf(30)), schluessel=SCHLUESSEL)
    assert ergebnis.angewendet is True
    gesendet = fasser.gesehene_anfragen[0]
    eingabe = antwortgrenze.eingabe_schaetzen(gesendet.nachrichten)
    assert gesendet.max_tokens == 200_000 - eingabe - kontextvoll.SICHERHEITSABSTAND
    assert antwortgrenze.geltender_deckel(zustand, None, abgelehnt) == 50


async def test_die_faltung_schaltet_das_denken_aus():
    """Whatever the run itself asked for, its summary is asked with thinking
    off where the model can be switched — and the run's own request keeps
    its choice."""
    from app.config import Capabilities, EndpointConfig

    fasser = _Zusammenfasser()
    mlx = EndpointConfig(
        id="o",
        base_url="http://127.0.0.1:8000/v1",
        parameter_dialect="mlx",
        capabilities=Capabilities(thinking=True),
    )
    an = {"chat_template_kwargs": {"enable_thinking": True}}
    anfrage = _Anfrage(nachrichten=_lauf(30), modell="m", zusatz=dict(an))

    ergebnis = await verdichtung.verdichten(_Zustand(fasser, mlx), anfrage, schluessel=SCHLUESSEL)

    assert ergebnis.angewendet is True
    assert fasser.gesehene_anfragen[0].zusatz == {
        "chat_template_kwargs": {"enable_thinking": False}
    }
    assert anfrage.zusatz == an


def _llama(thinking: bool = True):
    from app.config import Capabilities, EndpointConfig

    return EndpointConfig(
        id="l",
        base_url="http://127.0.0.1:9/v1",
        parameter_dialect="llama_cpp",
        capabilities=Capabilities(thinking=thinking),
    )


def _koerper(endpunkt, anfrage) -> dict:
    """What actually goes out for this request, built by the real provider."""
    from app.providers.openai_kompatibel import OpenAIKompatiblerProvider

    return OpenAIKompatiblerProvider(endpunkt)._koerper_bauen(anfrage)


def _lauf_mit_denklaenge(modell: str = "m"):
    from app.providers import Generierungsanfrage

    return Generierungsanfrage(
        nachrichten=_lauf(30),
        modell=modell,
        max_tokens=1000,
        parameter={"reasoning_budget": 2048, "top_k": 40},
    )


async def test_die_faltung_schickt_die_denklaenge_nicht_neben_den_schalter():
    """A run with a thinking length, on a llama.cpp model whose thinking can
    be switched off: its fold goes out with the switch alone — the length
    beside it would be a second, contradicting answer. The run keeps its
    length for its own requests."""
    fasser = _Zusammenfasser()
    llama = _llama()
    anfrage = _lauf_mit_denklaenge()

    ergebnis = await verdichtung.verdichten(_Zustand(fasser, llama), anfrage, schluessel=SCHLUESSEL)

    assert ergebnis.angewendet is True
    faltung = _koerper(llama, fasser.gesehene_anfragen[0])
    assert faltung["reasoning_effort"] == "none"
    assert "reasoning_budget_tokens" not in faltung
    assert faltung["top_k"] == 40
    assert anfrage.parameter == {"reasoning_budget": 2048, "top_k": 40}
    assert _koerper(llama, anfrage)["reasoning_budget_tokens"] == 2048


async def test_ohne_schalter_nimmt_die_faltung_die_parameter_des_laufs():
    """A model that cannot be switched gets no switch, and the fold asks with
    the parameters exactly as the run built them. The run has already dropped
    a thinking length the knob is locked for (the chat and the job filter
    before any fold sees the request, tests/test_denklaenge.py and
    tests/test_auftraege_api.py); the fold does not check a second time.
    """
    fasser = _Zusammenfasser()
    llama = _llama(thinking=False)
    anfrage = _lauf_mit_denklaenge()
    anfrage.parameter = {"top_k": 40}  # as the run filtered it for this model

    await verdichtung.verdichten(_Zustand(fasser, llama), anfrage, schluessel=SCHLUESSEL)

    gefragt = fasser.gesehene_anfragen[0]
    assert gefragt.zusatz == {}
    assert gefragt.parameter == {"top_k": 40}, gefragt.parameter
    assert "reasoning_budget_tokens" not in _koerper(llama, gefragt)
    # A dictionary of its own: an edit to the fold's parameters must never
    # reach the run's.
    assert gefragt.parameter is not anfrage.parameter
    gefragt.parameter["top_k"] = 1
    assert anfrage.parameter == {"top_k": 40}


async def test_mlx_und_openai_bekommen_denselben_koerper_wie_vorher():
    """Neither dialect has a field for the thinking length, so it never went
    out there: the fold's body is the same whether or not the length is
    taken off beside the switch."""
    import dataclasses

    from app.config import Capabilities, EndpointConfig

    faelle = [
        (
            EndpointConfig(
                id="o",
                base_url="http://127.0.0.1:8000/v1",
                parameter_dialect="mlx",
                capabilities=Capabilities(thinking=True),
            ),
            "m",
        ),
        (
            EndpointConfig(id="c", base_url="https://api.openai.com/v1", parameter_dialect="openai"),
            "gpt-5.5",
        ),
    ]
    for endpunkt, modell in faelle:
        fasser = _Zusammenfasser()
        anfrage = _lauf_mit_denklaenge(modell)

        await verdichtung.verdichten(_Zustand(fasser, endpunkt), anfrage, schluessel=SCHLUESSEL)

        neu = fasser.gesehene_anfragen[0]
        alt = dataclasses.replace(neu, parameter=anfrage.parameter)
        assert neu.zusatz, f"{endpunkt.parameter_dialect}: the switch goes out"
        assert _koerper(endpunkt, neu) == _koerper(endpunkt, alt)


class _Zaehlender:
    """Answers each request with the next reply in its list and counts the
    requests — ``None`` in the list stands for a request that breaks,
    ``"cut"`` for a summary cut off at its ceiling."""

    def __init__(self, antworten):
        self.antworten = list(antworten)
        self.anfragen = []

    async def streamen(self, anfrage):
        self.anfragen.append(anfrage)
        antwort = self.antworten[min(len(self.anfragen), len(self.antworten)) - 1]
        if antwort is None:
            raise RuntimeError("provider is down")
        if antwort == "cut":
            yield Stueck("content", text="## Done\n- half of")
            yield Stueck("stats", daten={"abgeschnitten": True, "ende_grund": "length"})
            return
        if antwort:
            yield Stueck("content", text=antwort)


def _buchungen(schluessel: str = SCHLUESSEL) -> int:
    """How many failed folds in a row the fold pause holds for this run."""
    stand = faltpause._staende.get(schluessel)
    return stand.notfaelle if stand else 0


@pytest.mark.parametrize(
    ("antwort", "pause"),
    [
        (None, faltpause.PAUSE_LANG),
        ("", faltpause.PAUSE_KURZ),
        ("cut", faltpause.PAUSE_KURZ),
    ],
    ids=["exception", "empty", "cut-off"],
)
async def test_eine_gescheiterte_zusammenfassung_faltet_nicht(antwort, pause):
    """Each way a summary fails: nothing takes the middle's place, the
    history stays exactly as it was, ONE request went out, and ONE failure
    is booked with the pause its class earns."""
    fasser = _Zaehlender([antwort, "gerafft"])
    nachrichten = _lauf(30)
    anfrage = _Anfrage(nachrichten=list(nachrichten))

    ergebnis = await verdichtung.verdichten(_Zustand(fasser), anfrage, schluessel=SCHLUESSEL)

    assert ergebnis.angewendet is False
    assert ergebnis.notfall is True
    assert ergebnis.ohne_ersparnis is False
    # A smaller step would ask about the same history inside that pause.
    assert ergebnis.keine_mitte is False
    assert anfrage.nachrichten == nachrichten
    assert len(fasser.anfragen) == 1
    assert _buchungen() == 1
    assert faltpause.pausiert(SCHLUESSEL, jetzt=pause - 1)
    assert not faltpause.pausiert(SCHLUESSEL, jetzt=pause)


class _Denker:
    """Answers the fold's request only with thinking and a natural ending —
    the summary that was never written out."""

    def __init__(self):
        self.anfragen: list = []

    async def streamen(self, anfrage):
        self.anfragen.append(anfrage)
        yield Stueck("reasoning", text="Gedachte Mitte")
        yield Stueck("stats", daten={"ende_grund": "stop"})


async def test_eine_gedachte_zusammenfassung_faltet_die_mitte():
    """A summary the model thought instead of writing folds the middle —
    the same swap chat and job make (app/reasoning.denktext_als_antwort)."""
    fasser = _Denker()
    nachrichten = _lauf(30)
    anfrage = _Anfrage(nachrichten=list(nachrichten))

    ergebnis = await verdichtung.verdichten(_Zustand(fasser), anfrage, schluessel=SCHLUESSEL)

    assert ergebnis.angewendet is True
    assert len(fasser.anfragen) == 1
    assert any("Gedachte Mitte" in (n.content or "") for n in anfrage.nachrichten)
    assert _buchungen() == 0


async def test_ein_volles_kontextfenster_faltet_auch_nicht():
    """A different end reason than an answer's own length cap, the same
    outcome: this is what a job's folding request sees when the model's whole
    context window ran out before it could finish summarizing."""
    nachrichten = _lauf(30)
    anfrage = _Anfrage(nachrichten=list(nachrichten))
    ergebnis = await verdichtung.verdichten(
        _Zustand(_KontextfensterVoller()), anfrage, schluessel=SCHLUESSEL
    )
    assert ergebnis.angewendet is False
    assert ergebnis.notfall is True
    assert anfrage.nachrichten == nachrichten
    assert _buchungen() == 1


class _Ausfall:
    """Refuses every request the way a dead model server does, and counts
    them — so a test can say how many fold requests really left the house."""

    def __init__(self):
        self.anfragen = []

    async def streamen(self, anfrage):
        self.anfragen.append(anfrage)
        raise RuntimeError("provider is down")
        yield  # pragma: no cover - makes this an async generator


async def test_zwei_gescheiterte_durchgaenge_schliessen_die_sperre(uhr):
    """A dead model: no fold, the pause; once the pause has run out, one more
    request, a second failure — and the block is on, its notice due once."""
    ausfall = _Ausfall()
    erste = await verdichtung.verdichten(
        _Zustand(ausfall), _Anfrage(nachrichten=_lauf(30)), schluessel=SCHLUESSEL
    )

    assert erste.angewendet is False
    assert erste.notfall is True
    assert faltpause.pausiert(SCHLUESSEL) is True
    assert faltpause.automatik_gesperrt(SCHLUESSEL, jetzt=faltpause.PAUSE_LANG) is False

    uhr.weiter(faltpause.PAUSE_LANG)
    zweite = await verdichtung.verdichten(
        _Zustand(ausfall), _Anfrage(nachrichten=_lauf(30)), schluessel=SCHLUESSEL
    )

    assert zweite.notfall is True
    assert len(ausfall.anfragen) == 2
    assert faltpause.automatik_gesperrt(SCHLUESSEL) is True
    assert faltpause.hinweis_faellig(SCHLUESSEL) is True
    assert faltpause.hinweis_faellig(SCHLUESSEL) is False


async def test_der_eine_versuch_nach_der_sperre_ist_eine_anfrage(uhr):
    """After the block and its recovery window one attempt stands ready. It
    is spent by the next fold that asks a model — one request — and the
    failure it comes back with puts the block straight back."""
    ausfall = _Ausfall()
    await verdichtung.verdichten(
        _Zustand(ausfall), _Anfrage(nachrichten=_lauf(30)), schluessel=SCHLUESSEL
    )
    uhr.weiter(faltpause.PAUSE_LANG)
    await verdichtung.verdichten(
        _Zustand(ausfall), _Anfrage(nachrichten=_lauf(30)), schluessel=SCHLUESSEL
    )
    assert len(ausfall.anfragen) == 2
    assert faltpause.automatik_gesperrt(SCHLUESSEL) is True

    uhr.weiter(faltpause.PAUSE_LANG)
    assert faltpause.automatik_gesperrt(SCHLUESSEL) is True
    uhr.weiter(faltpause.WIEDERAUFNAHME_SEKUNDEN)

    await verdichtung.verdichten(
        _Zustand(ausfall), _Anfrage(nachrichten=_lauf(30)), schluessel=SCHLUESSEL
    )

    assert len(ausfall.anfragen) == 3, "the one attempt was already spent"

    uhr.weiter(faltpause.PAUSE_LANG)
    await verdichtung.verdichten(
        _Zustand(ausfall), _Anfrage(nachrichten=_lauf(30)), schluessel=SCHLUESSEL
    )

    assert len(ausfall.anfragen) == 3, "the block let a second one through"


async def test_erzwungen_in_der_pause_fragt_nicht_und_bucht_nichts(uhr):
    """Forced inside a running pause: no request, nothing folded — and
    nothing booked, because nothing was learned about the model. Nothing
    failed either, so no failure is reported, and no smaller step is
    offered: it would sit inside the same pause."""
    await verdichtung.verdichten(
        _Zustand(_Ausfall()), _Anfrage(nachrichten=_lauf(30)), schluessel=SCHLUESSEL
    )
    assert _buchungen() == 1
    nachrichten = _lauf(30)
    anfrage = _Anfrage(nachrichten=list(nachrichten))

    ergebnis = await verdichtung.verdichten(
        _Zustand(_StummerProvider()), anfrage, schluessel=SCHLUESSEL, erzwungen=True
    )

    assert ergebnis.angewendet is False
    assert ergebnis.notfall is False
    assert ergebnis.keine_mitte is False
    assert anfrage.nachrichten == nachrichten
    assert _buchungen() == 1


async def test_ohne_platz_fuer_eine_zusammenfassung_fragt_nicht_und_bucht_nichts():
    """A window the summarizing request does not fit into: no request goes
    out, nothing is folded, nothing is booked — no failure is reported, and
    no smaller step is offered."""
    nachrichten = _lauf(30)
    anfrage = _Anfrage(nachrichten=list(nachrichten))
    zustand = _Zustand(_StummerProvider(), context_tokens=1_000)

    ergebnis = await verdichtung.verdichten(
        zustand, anfrage, schluessel=SCHLUESSEL, erzwungen=True
    )

    assert ergebnis.angewendet is False
    assert ergebnis.notfall is False
    assert ergebnis.keine_mitte is False
    assert anfrage.nachrichten == nachrichten
    assert _buchungen() == 0
    assert faltpause.pausiert(SCHLUESSEL) is False


async def test_ein_kleines_fenster_fragt_das_modell_mit_gesenktem_deckel():
    """A window far smaller than the history: the request's ceiling comes
    down to the window, the model IS asked, and the summary keeps its
    reserve free — where the fixed ceiling left no room and asked nobody.
    On the Anthropic wire, where a number still travels."""
    fenster = 32_768
    anfrage = _Anfrage(nachrichten=_lauf(60))
    fasser = _Zusammenfasser()

    ergebnis = await verdichtung.verdichten(
        _Zustand(fasser, endpunkt=_anthropic_draht(), context_tokens=fenster),
        anfrage,
        schluessel=SCHLUESSEL,
    )

    assert len(fasser.gesehene_anfragen) == 1
    assert ergebnis.angewendet is True
    gefragt = fasser.gesehene_anfragen[0]
    assert len(gefragt.nachrichten[0].content) < faltbitte.BITTE_MAX
    reserve = faltbitte.reserve(fenster)
    eingabe = antwortgrenze.eingabe_schaetzen(gefragt.nachrichten, gefragt.werkzeuge)
    assert eingabe <= fenster - reserve - kontextvoll.SICHERHEITSABSTAND
    # On the wire that carries a number, the reserve is what the summary
    # gets to be written in. On the OpenAI wire no number goes out and the
    # reserve is room in the window, nothing more.
    assert gefragt.max_tokens >= reserve


async def test_passt_kein_zeichen_verlauf_fragt_nicht_auch_wenn_platz_waere(monkeypatch):
    """A window that leaves the history not one character: no request, nothing
    folded, nothing booked — decided by the ceiling itself, not by the "no
    room" arithmetic, which is told here that there is room."""
    monkeypatch.setattr(antwortgrenze, "reicht_nicht", lambda *_, **__: False)
    nachrichten = _lauf(30)
    anfrage = _Anfrage(nachrichten=list(nachrichten))

    ergebnis = await verdichtung.verdichten(
        _Zustand(_StummerProvider(), context_tokens=2_048),
        anfrage,
        schluessel=SCHLUESSEL,
        erzwungen=True,
    )

    assert ergebnis.angewendet is False
    assert ergebnis.notfall is False
    assert ergebnis.keine_mitte is False
    assert anfrage.nachrichten == nachrichten
    assert _buchungen() == 0
    assert faltpause.pausiert(SCHLUESSEL) is False


async def test_nach_dem_fehlschlag_faltet_der_naechste_zug_wie_vorher(uhr):
    """Silence test: once the model answers again, the next fold after the
    pause is the ordinary one — the summary goes in, and the pause and the
    row towards the block are cleared."""
    await verdichtung.verdichten(
        _Zustand(_Ausfall()), _Anfrage(nachrichten=_lauf(30)), schluessel=SCHLUESSEL
    )
    uhr.weiter(faltpause.PAUSE_LANG)
    anfrage = _Anfrage(nachrichten=_lauf(30))

    ergebnis = await verdichtung.verdichten(
        _Zustand(_Zusammenfasser()), anfrage, schluessel=SCHLUESSEL
    )

    assert ergebnis.angewendet is True
    assert ergebnis.notfall is False
    assert ergebnis.keine_mitte is False
    assert anfrage.nachrichten[3].content == f"{verdichtung.VORSPANN}\n\ngerafft"
    assert _buchungen() == 0
    assert faltpause.hinweis_faellig(SCHLUESSEL) is False


async def test_nach_dem_freien_versuch_steht_der_hinweis_wieder_genau_einmal(uhr):
    """The notice belongs to the answer the block engages in, once per
    block: two failures engage it, and when the one attempt after the
    recovery window fails too, the block engages again — and says so again,
    exactly once, not twice and not never."""
    ausfall = _Ausfall()

    async def falten():
        await verdichtung.verdichten(
            _Zustand(ausfall), _Anfrage(nachrichten=_lauf(30)), schluessel=SCHLUESSEL
        )

    await falten()
    assert faltpause.hinweis_faellig(SCHLUESSEL) is False
    uhr.weiter(faltpause.PAUSE_LANG)
    await falten()
    assert faltpause.hinweis_faellig(SCHLUESSEL) is True
    assert faltpause.hinweis_faellig(SCHLUESSEL) is False

    # The block holds, its recovery window runs out, the one attempt goes.
    uhr.weiter(faltpause.PAUSE_LANG)
    await falten()
    uhr.weiter(faltpause.WIEDERAUFNAHME_SEKUNDEN)
    await falten()

    assert len(ausfall.anfragen) == 3
    assert faltpause.automatik_gesperrt(SCHLUESSEL) is True
    assert faltpause.hinweis_faellig(SCHLUESSEL) is True
    assert faltpause.hinweis_faellig(SCHLUESSEL) is False


def test_nur_eine_gescheiterte_anfrage_bucht_einen_fehlschlag():
    """Where the row towards the block can move at all: every call of
    ``faltpause.notfall`` in the program, found in the source. After the
    change to not folding there are exactly two, each in the ``_nicht_falten``
    of its path, and both sit behind ``art is not None`` — the class of a
    request that really went out. No path books without a request, so the
    count can only ever climb one at a time and cannot jump past the number
    that engages the block."""
    import ast
    from pathlib import Path

    wurzel = Path(__file__).resolve().parents[1]
    gefunden = []
    for datei in sorted((wurzel / "app").rglob("*.py")):
        baum = ast.parse(datei.read_text(encoding="utf-8"))
        for funktion in ast.walk(baum):
            if not isinstance(funktion, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for knoten in ast.walk(funktion):
                if (
                    isinstance(knoten, ast.Call)
                    and isinstance(knoten.func, ast.Attribute)
                    and knoten.func.attr == "notfall"
                    and isinstance(knoten.func.value, ast.Name)
                    and knoten.func.value.id == "faltpause"
                ):
                    gefunden.append((datei.relative_to(wurzel).as_posix(), funktion.name))
    assert sorted(gefunden) == [
        ("app/chatverdichtung.py", "_nicht_falten"),
        ("app/verdichtung.py", "_nicht_falten"),
    ]


def _werkzeugmitte(paare: int, argument_zeichen: int) -> list[ChatNachricht]:
    """A run whose middle is nothing but tool rounds whose weight sits in the
    ARGUMENTS — a write call carrying a file, say — with a word of text and a
    one-word result each, between the pinned opening and a verbatim tail of
    twenty standard messages."""
    anfang = [
        _nachricht("system", "system"),
        _nachricht("user", "the task"),
        _nachricht("assistant", "on it"),
    ]
    mitte = []
    for nr in range(paare):
        mitte.append(ChatNachricht(
            role="assistant",
            content="x",
            werkzeugaufrufe=[Werkzeugaufruf(
                id=f"w{nr}", name="write_file",
                argumente={"path": f"datei-{nr}.txt", "inhalt": "a" * argument_zeichen},
            )],
        ))
        mitte.append(_nachricht("tool", "ok", aufruf_id=f"w{nr}"))
    return anfang + mitte + _lauf(10)


def test_die_argumente_zaehlen_auf_beiden_wegen_nach_derselben_regel():
    """The job's measure of the middle and the chat's measure of a row read a
    call's arguments the same way — the JSON of the arguments — so the same
    call adds the same characters on both sides. The totals may still differ:
    a chat row also carries documents and pictures, a run does not.

    One difference is deliberate and not a second rule: a row whose call
    never brought a result weighs the eleven characters the request writes
    for one (``app/faltbitte.py``, ``OHNE_AUSGABE``), where the middle of a
    run holds that result as a message of its own and weighs its text there.
    The arguments are what this test compares."""
    import json

    from app import verlaufsbau

    argumente = {"path": "datei.txt", "inhalt": "a" * 900}
    gewicht = len(json.dumps(argumente, ensure_ascii=False))
    mit = [ChatNachricht(
        role="assistant", content="x",
        werkzeugaufrufe=[Werkzeugaufruf(id="w", name="write_file", argumente=argumente)],
    )]
    ohne = [ChatNachricht(role="assistant", content="x")]
    auftrag = verdichtung._ersetzte_laenge(mit, 0, 1) - verdichtung._ersetzte_laenge(ohne, 0, 1)

    class _Zeile:
        role = "assistant"
        art = "nachricht"
        stats = {"werkzeuge": [{"name": "write_file", "argumente": argumente}]}

    from app.faltbitte import OHNE_AUSGABE

    assert auftrag == gewicht
    # The row's call brought no result, so it carries the eleven characters
    # the request writes for one.
    assert verlaufsbau.werkzeuggewicht(_Zeile()) == gewicht + len(OHNE_AUSGABE)


def test_ohne_werkzeugaufrufe_misst_die_mitte_wie_vorher():
    """Silence test: a middle of plain text weighs exactly its text."""
    nachrichten = _lauf(20)
    assert verdichtung._ersetzte_laenge(nachrichten, 3, 20) == sum(
        len(n.content or "") for n in nachrichten[3:20]
    )


async def test_eine_werkzeuglastige_mitte_wird_gefaltet_statt_abgelehnt():
    """The fold the job path used to refuse: ten calls carrying 5,000
    characters of arguments each, a word of text around them, and a summary
    of 20,000 characters. Weighed by text alone the middle came to a few
    dozen characters and the summary "saved nothing"; weighed the way the
    request carries it, the summary replaces some 50,000 characters."""
    nachrichten = _werkzeugmitte(10, 5_000)
    anfrage = _Anfrage(nachrichten=list(nachrichten))
    zustand = _Zustand(provider=_Zusammenfasser("z" * 20_000))

    ergebnis = await verdichtung.verdichten(zustand, anfrage, schluessel=SCHLUESSEL)

    assert ergebnis.ohne_ersparnis is False
    assert ergebnis.angewendet is True
    assert len(anfrage.nachrichten) < len(nachrichten)


@dataclass
class _Dokument:
    """What a request builder attaches to a message: a document with a name
    and a text, and no file to read it from."""

    id: str
    filename: str
    extracted_text: str
    pfad: str | None = None
    pages: int | None = None


def _lauf_mit_dokument(dokument: _Dokument, zweimal: bool = False) -> list[ChatNachricht]:
    """A chat's request in memory: a message carrying ``dokument`` inside the
    middle — twice where asked — before the verbatim tail."""
    nachrichten = _lauf(30)
    nachrichten[4] = dataclasses.replace(nachrichten[4], dokumente=[dokument])
    if zweimal:
        nachrichten[6] = dataclasses.replace(nachrichten[6], dokumente=[dokument])
    return nachrichten


async def test_die_faltung_im_speicher_nennt_das_verdraengte_dokument():
    """A chat folding its request in memory takes a document out of it with
    the stretch it replaces: the summary carries the same note the fold of a
    chat's rows carries — and names a document that two messages carried
    once."""
    dokument = _Dokument(id="d1", filename="vertrag.pdf", extracted_text="T" * 3_000)
    anfrage = _Anfrage(nachrichten=_lauf_mit_dokument(dokument, zweimal=True))

    ergebnis = await verdichtung.verdichten(
        _Zustand(_Zusammenfasser()), anfrage, schluessel=SCHLUESSEL
    )

    assert ergebnis.angewendet is True
    inhalt = anfrage.nachrichten[3].content
    assert inhalt.startswith(f"{verdichtung.VORSPANN}\n\ngerafft")
    assert "Documents attached in the stretch summarized above" in inhalt
    assert inhalt.count('"vertrag.pdf" (3000 characters)') == 1


async def test_die_zweite_faltung_im_speicher_nennt_das_dokument_der_ersten():
    """The summary of the first fold carries the documents it displaced, so
    the fold that takes THAT summary into its own middle names them again —
    where the second fold used to drop the first one's note without a word."""
    dokument = _Dokument(id="d1", filename="vertrag.pdf", extracted_text="T" * 3_000)
    anfrage = _Anfrage(nachrichten=_lauf_mit_dokument(dokument))

    erste = await verdichtung.verdichten(
        _Zustand(_Zusammenfasser()), anfrage, schluessel=SCHLUESSEL
    )
    assert erste.angewendet is True
    assert "vertrag.pdf" in anfrage.nachrichten[3].content
    # The next round's history: the summary plus enough new turns for a
    # middle of its own.
    anfrage.nachrichten.extend(_lauf(30))

    zweite = await verdichtung.verdichten(
        _Zustand(_Zusammenfasser("noch kuerzer")), anfrage, schluessel=SCHLUESSEL
    )

    assert zweite.angewendet is True
    inhalt = anfrage.nachrichten[3].content
    assert inhalt.startswith(f"{verdichtung.VORSPANN}\n\nnoch kuerzer")
    assert inhalt.count('"vertrag.pdf" (3000 characters)') == 1


async def test_die_faltbitte_im_speicher_traegt_den_dokumentkoerper_nicht():
    """The request that asks for the summary NAMES the document instead of
    carrying it — the same view the fold of a chat's rows takes — and it
    carries the rule that asks the model to record what the conversation
    established about it."""
    from app import chatverdichtung, verlaufsbau

    koerper = "K" * 40_000
    dokument = _Dokument(
        id="d1", filename="vertrag.pdf", extracted_text=koerper, pfad="/tmp/vertrag.pdf"
    )
    nachrichten = _lauf_mit_dokument(dokument)
    # The message as the request builder wrote it: the body between its
    # markers, in front of the words (app/verlaufsbau.py).
    nachrichten[4] = dataclasses.replace(
        nachrichten[4],
        content=(
            f'[Attached document "vertrag.pdf"]\n{koerper}\n[End of document]\n\n'
            f"{nachrichten[4].content}"
        ),
    )
    anfrage = _Anfrage(nachrichten=nachrichten)
    fasser = _Zusammenfasser()

    ergebnis = await verdichtung.verdichten(
        _Zustand(fasser), anfrage, schluessel=SCHLUESSEL
    )

    assert ergebnis.angewendet is True
    gefragt = fasser.gesehene_anfragen[0]
    gesamt = "\n".join(n.content or "" for n in gefragt.nachrichten)
    assert koerper not in gesamt
    assert verlaufsbau.faltkopf(dokument) in gesamt
    assert gefragt.nachrichten[-1].content.endswith(chatverdichtung.DOKUMENTREGEL)


async def test_ohne_dokument_bleibt_die_bitte_wie_sie_war():
    """Silence test — a job's messages carry no documents: the request ends
    with the plain ask, without the document rule."""
    anfrage = _Anfrage(nachrichten=_lauf(30))
    fasser = _Zusammenfasser()

    await verdichtung.verdichten(_Zustand(fasser), anfrage, schluessel=SCHLUESSEL)

    assert fasser.gesehene_anfragen[0].nachrichten[-1].content == verdichtung.ANFRAGE_TEXT


async def test_scheitert_die_zusammenfassung_bleibt_das_dokument_ohne_nachweis_stehen():
    """Silence test after not folding: a failed summary replaces nothing, so
    nothing displaces the document and no note is written."""
    dokument = _Dokument(id="d1", filename="vertrag.pdf", extracted_text="T" * 3_000)
    nachrichten = _lauf_mit_dokument(dokument)
    anfrage = _Anfrage(nachrichten=list(nachrichten))

    ergebnis = await verdichtung.verdichten(
        _Zustand(_Zusammenfasser("")), anfrage, schluessel=SCHLUESSEL
    )

    assert ergebnis.angewendet is False
    assert anfrage.nachrichten == nachrichten
    assert not any("Documents attached" in (n.content or "") for n in anfrage.nachrichten)


async def test_eine_mitte_ohne_dokument_bekommt_keinen_nachweis():
    """Silence test — and a job's history is exactly this: its messages carry
    no documents, so the summary is the preamble and the text, nothing else."""
    anfrage = _Anfrage(nachrichten=_lauf(30))

    await verdichtung.verdichten(_Zustand(_Zusammenfasser()), anfrage, schluessel=SCHLUESSEL)

    assert anfrage.nachrichten[3].content == f"{verdichtung.VORSPANN}\n\ngerafft"


def _summary_row(document: _Dokument) -> ChatNachricht:
    """A summary row of the rows path as the request builder hands it over:
    a plain message whose only trace of its documents is the sentence — no
    ``dokumente`` field (app/chatverdichtung.py)."""
    from app import chatverdichtung

    return ChatNachricht(
        role="user",
        content=(
            f"{verdichtung.VORSPANN}\n\nfrueher gerafft\n\n"
            f"{chatverdichtung._dokumentnachweis([document])}"
        ),
        # The mark the request builder sets on a summary row
        # (app/verlaufsbau.py).
        compacted_summary=True,
    )


async def test_the_fold_in_memory_passes_on_the_sentence_of_a_summary_row():
    """A summary row from the database lies in the middle: it carries its
    document sentence and no ``dokumente``. The new summary speaks for it, so
    it carries that sentence on, word for word and once."""
    from app import chatverdichtung

    old = _Dokument(id="d0", filename="angebot.pdf", extracted_text="A" * 1_200)
    messages = _lauf(30)
    messages[4] = _summary_row(old)
    request = _Anfrage(nachrichten=messages)

    result = await verdichtung.verdichten(
        _Zustand(_Zusammenfasser()), request, schluessel=SCHLUESSEL
    )

    assert result.angewendet is True
    content = request.nachrichten[3].content
    sentence = chatverdichtung._dokumentnachweis([old])
    assert content == f"{verdichtung.VORSPANN}\n\ngerafft\n\n{sentence}"
    assert request.nachrichten[3].dokumente == []


async def test_the_old_sentence_comes_before_this_folds_sentence():
    """The same middle with a new document: both sentences, the old one first,
    then the one for the document this fold displaces."""
    from app import chatverdichtung

    old = _Dokument(id="d0", filename="angebot.pdf", extracted_text="A" * 1_200)
    new = _Dokument(id="d1", filename="vertrag.pdf", extracted_text="T" * 3_000)
    messages = _lauf_mit_dokument(new)
    messages[5] = _summary_row(old)
    request = _Anfrage(nachrichten=messages)

    result = await verdichtung.verdichten(
        _Zustand(_Zusammenfasser()), request, schluessel=SCHLUESSEL
    )

    assert result.angewendet is True
    content = request.nachrichten[3].content
    old_sentence = chatverdichtung._dokumentnachweis([old])
    new_sentence = chatverdichtung._dokumentnachweis([new])
    assert content == f"{verdichtung.VORSPANN}\n\ngerafft\n\n{old_sentence}\n\n{new_sentence}"


async def test_a_sentence_the_model_copied_does_not_come_twice():
    """A model that copied the earlier sentence into its summary has carried
    it already: it stands there once."""
    from app import chatverdichtung

    old = _Dokument(id="d0", filename="angebot.pdf", extracted_text="A" * 1_200)
    sentence = chatverdichtung._dokumentnachweis([old])
    messages = _lauf(30)
    messages[4] = _summary_row(old)
    request = _Anfrage(nachrichten=messages)

    await verdichtung.verdichten(
        _Zustand(_Zusammenfasser(f"gerafft\n\n{sentence}")), request, schluessel=SCHLUESSEL
    )

    assert request.nachrichten[3].content.count(sentence) == 1


async def test_two_folds_in_memory_name_each_document_once():
    """Two folds in memory over a summary row (a), a document of the first
    middle (b) and one of the second (c): the first summary carries its
    sentences and no ``dokumente``, so the second names every document
    exactly once — where b used to stand in two sentences."""
    a = _Dokument(id="a", filename="a.pdf", extracted_text="A" * 100)
    b = _Dokument(id="b", filename="b.pdf", extracted_text="B" * 100)
    c = _Dokument(id="c", filename="c.pdf", extracted_text="C" * 100)
    messages = _lauf_mit_dokument(b)
    messages[5] = _summary_row(a)
    request = _Anfrage(nachrichten=messages)

    first = await verdichtung.verdichten(
        _Zustand(_Zusammenfasser()), request, schluessel=SCHLUESSEL
    )
    assert first.angewendet is True
    assert request.nachrichten[3].dokumente == []
    new = _lauf(30)
    new[2] = dataclasses.replace(new[2], dokumente=[c])
    request.nachrichten.extend(new)

    second = await verdichtung.verdichten(
        _Zustand(_Zusammenfasser("noch kuerzer")), request, schluessel=SCHLUESSEL
    )

    assert second.angewendet is True
    content = request.nachrichten[3].content
    for name in ("a.pdf", "b.pdf", "c.pdf"):
        assert content.count(f'"{name}"') == 1


async def test_a_sentence_in_a_user_or_tool_message_is_not_passed_on():
    """Silence test: only a summary's sentence is carried on. A user message
    or a tool result that quotes the sentence — a tool that read the module
    writing it, say — is no summary, and its text is not taken for one."""
    from app import chatverdichtung

    old = _Dokument(id="d0", filename="angebot.pdf", extracted_text="A" * 1_200)
    sentence = chatverdichtung._dokumentnachweis([old])
    messages = _lauf(30)
    messages[4] = _nachricht("user", f"zitiert: {sentence}")
    messages[5] = ChatNachricht(
        role="assistant",
        content="x",
        werkzeugaufrufe=[Werkzeugaufruf(id="w1", name="read_file", argumente={"path": "q.py"})],
    )
    messages.insert(6, _nachricht("tool", f"quelltext {sentence}", aufruf_id="w1"))
    request = _Anfrage(nachrichten=messages)

    result = await verdichtung.verdichten(
        _Zustand(_Zusammenfasser()), request, schluessel=SCHLUESSEL
    )

    assert result.angewendet is True
    assert request.nachrichten[3].content == f"{verdichtung.VORSPANN}\n\ngerafft"


# --- noetig() ---------------------------------------------------------------


def test_noetig_ist_falsch_wenn_alles_hineinpasst():
    nachrichten = _lauf(5)  # 10 messages, and the tail budget holds 20
    assert verdichtung.noetig(nachrichten) is False


def test_noetig_ist_wahr_mit_einer_echten_mitte():
    nachrichten = _lauf(20)  # 40 messages
    assert verdichtung.noetig(nachrichten) is True


def test_noetig_folgt_dem_budget_des_modells():
    """The tail is a budget for the model in hand, not one number for every
    model: forty short messages have no middle under the ceiling, and a
    genuine one once the budget is what a small context can afford."""
    nachrichten = [_nachricht("user" if i % 2 == 0 else "assistant", f"m{i} " + "x" * 40) for i in range(40)]
    assert verdichtung.noetig(nachrichten) is False
    assert verdichtung.noetig(nachrichten, budget=400) is True


# --- schwanz_budget() -------------------------------------------------------


def test_schwanz_budget_bleibt_beim_deckel_fuer_grosse_modelle():
    """A hundred thousand tokens of room: the ceiling is the right tail and
    nothing changes."""
    assert verdichtung.schwanz_budget(128_000, 80.0) == verdichtung.LETZTE_ZEICHEN


def test_schwanz_budget_laesst_einem_kleinen_modell_eine_mitte():
    """Measured shape: 16k context, shipped 80% threshold. The threshold
    fires at 16000 * 4 * 0.8 = 51,200 characters of history; the fixed
    ceiling of 80,000 covered all of it and the middle was empty on every
    turn. Half of the history at the threshold is the tail, so the other
    half is middle."""
    assert verdichtung.schwanz_budget(16_000, 80.0) == 25_600
    assert verdichtung.schwanz_budget(16_000, 80.0) < verdichtung.LETZTE_ZEICHEN


def test_schwanz_budget_ohne_kontextgroesse_ist_der_deckel():
    assert verdichtung.schwanz_budget(None, 80.0) == verdichtung.LETZTE_ZEICHEN
    assert verdichtung.schwanz_budget(0, 80.0) == verdichtung.LETZTE_ZEICHEN
    assert verdichtung.schwanz_budget(16_000, 0) == verdichtung.LETZTE_ZEICHEN


def test_schwanz_budget_ist_nie_null():
    assert verdichtung.schwanz_budget(1, 1.0) >= 1


# --- verdichten() -------------------------------------------------------


async def test_ohne_mitte_passiert_nichts():
    nachrichten = _lauf(5)
    anfrage = _Anfrage(nachrichten=list(nachrichten))
    zustand = _Zustand(provider=_StummerProvider())

    ergebnis = await verdichtung.verdichten(zustand, anfrage, schluessel=SCHLUESSEL)

    assert ergebnis.angewendet is False
    assert ergebnis.ohne_ersparnis is False
    assert ergebnis.notfall is False
    # The one ending a smaller step can still do something about.
    assert ergebnis.keine_mitte is True
    assert anfrage.nachrichten == nachrichten


async def test_die_ersten_drei_bleiben_woertlich():
    nachrichten = _lauf(20)
    anfrage = _Anfrage(nachrichten=list(nachrichten))
    zustand = _Zustand(provider=_Zusammenfasser())

    await verdichtung.verdichten(zustand, anfrage, schluessel=SCHLUESSEL)

    assert anfrage.nachrichten[:3] == nachrichten[:3]


async def test_die_letzten_zwanzig_bleiben_woertlich():
    nachrichten = _lauf(20)
    anfrage = _Anfrage(nachrichten=list(nachrichten))
    zustand = _Zustand(provider=_Zusammenfasser())

    await verdichtung.verdichten(zustand, anfrage, schluessel=SCHLUESSEL)

    assert anfrage.nachrichten[-20:] == nachrichten[-20:]


async def test_die_mitte_wird_zu_einer_nachricht():
    nachrichten = _lauf(20)  # 40 messages: 3 + 1 summary + 20 = 24
    anfrage = _Anfrage(nachrichten=list(nachrichten))
    zustand = _Zustand(provider=_Zusammenfasser("gerafft"))

    ergebnis = await verdichtung.verdichten(zustand, anfrage, schluessel=SCHLUESSEL)

    assert ergebnis.angewendet is True
    assert ergebnis.ohne_ersparnis is False
    assert len(anfrage.nachrichten) == 3 + 1 + 20
    zusammenfassung = anfrage.nachrichten[3]
    assert zusammenfassung.role == "user"
    assert "gerafft" in zusammenfassung.content


async def test_eine_nicht_kuerzere_zusammenfassung_laesst_alles_stehen():
    """The exact case the compaction brake is about: a genuine attempt whose answer is
    not actually shorter than what it replaces — it must not be applied,
    and the caller has to be able to tell this apart from "nothing to do"
    so it can stop retrying for the rest of the run."""
    nachrichten = _lauf(20)
    anfrage = _Anfrage(nachrichten=list(nachrichten))
    # An answer longer than the whole history does the opposite of the
    # everyday case: it is NOT shorter than what it would replace. Sized
    # off the history rather than a fixed number, so it stays longer no
    # matter what one message weighs.
    lange_antwort = "x" * (JE_NACHRICHT * 40)
    zustand = _Zustand(provider=_Zusammenfasser(lange_antwort))

    ergebnis = await verdichtung.verdichten(zustand, anfrage, schluessel=SCHLUESSEL)

    assert ergebnis.angewendet is False
    assert ergebnis.ohne_ersparnis is True
    # A smaller step would ask about the same middle again (a model that
    # answered and saved nothing is not a middle that is missing).
    assert ergebnis.keine_mitte is False
    assert ergebnis.notfall is False
    assert anfrage.nachrichten == nachrichten


async def test_der_vergleich_zaehlt_den_vorspann_der_zusammenfassung_mit():
    """The saved message is not the raw model answer — it is that answer
    behind a fixed preamble. A "shorter" answer that is not shorter once
    the preamble is added back in must still count as no savings, or a
    chain of ever-thinner summaries can keep landing inside the preamble's
    own width while the history quietly grows every round."""
    vorne = [_nachricht("user", "f0"), _nachricht("assistant", "a0"), _nachricht("user", "f1")]
    mitte = [_nachricht("assistant", "x" * 30), _nachricht("user", "x" * 30)]  # the middle: 60 chars
    nachrichten = vorne + mitte + _lauf(10)  # 3 fixed + 2 middle + 20 fixed tail
    anfrage = _Anfrage(nachrichten=list(nachrichten))
    # Shorter than the 60-char middle on its own (10 < 60) — the bug this
    # guards against judged exactly this "shorter" by the raw answer alone.
    # With the fixed 55-char preamble the saved message is 65 chars: longer
    # than what it replaces, not shorter.
    zustand = _Zustand(provider=_Zusammenfasser("y" * 10))

    ergebnis = await verdichtung.verdichten(zustand, anfrage, schluessel=SCHLUESSEL)

    assert ergebnis.angewendet is False
    assert ergebnis.ohne_ersparnis is True
    assert anfrage.nachrichten == nachrichten


async def test_die_zusammenfassungsanfrage_erreicht_die_live_geschichte_nicht():
    """The live conversation must stay untouched while the summary is being
    asked for — only the finished result gets spliced in."""
    nachrichten = _lauf(20)
    anfrage = _Anfrage(nachrichten=list(nachrichten))
    provider = _Zusammenfasser("gerafft")
    zustand = _Zustand(provider=provider)

    await verdichtung.verdichten(zustand, anfrage, schluessel=SCHLUESSEL)

    gesehen = provider.gesehene_anfragen[0]
    assert gesehen.nachrichten[-1].content == verdichtung.ANFRAGE_TEXT
    # The object handed to the provider is not the live request.
    assert gesehen is not anfrage


# --- Never cutting a tool call off from its own result ----------------------


def test_grenze_wandert_ueber_ein_werkzeugergebnis_am_anfang():
    """If message index ERSTE_FEST would land on a tool result, the front
    grows to swallow the whole call-and-result pair instead of cutting it
    in half."""
    nachrichten = [
        _nachricht("user", "auftrag"),
        _nachricht("user", "mehr"),
        ChatNachricht(role="assistant", content="", werkzeugaufrufe=[Werkzeugaufruf(id="w", name="t", argumente={})]),
        _nachricht("tool", "ergebnis", aufruf_id="a1"),
    ] + _lauf(20)
    anfang = verdichtung._nicht_hinter_werkzeugantwort(nachrichten, verdichtung.ERSTE_FEST, +1)
    assert nachrichten[anfang].role != "tool"
    assert anfang == 4  # past the lone tool result


def test_grenze_wandert_ueber_ein_werkzeugergebnis_am_ende():
    nachrichten = (
        _lauf(20)
        + [ChatNachricht(role="assistant", content="", werkzeugaufrufe=[Werkzeugaufruf(id="w", name="t", argumente={})])]
        + [_nachricht("tool", "ergebnis", aufruf_id="a1")]
        + _lauf(1)
    )
    # Where the tail begins is a token budget now, so it is asked for
    # rather than counted back from the end.
    ende = verdichtung._nicht_hinter_werkzeugantwort(
        nachrichten, verdichtung._schwanz_anfang(nachrichten), -1
    )
    assert nachrichten[ende].role != "tool"


async def test_ein_werkzeugpaar_an_der_grenze_bleibt_ganz():
    """End to end: a call-and-result pair whose result would otherwise be
    the very FIRST message of the pinned tail — the exact case the
    boundary math has to catch — ends up wholly in the tail, not split."""
    aufruf = ChatNachricht(
        role="assistant", content="", werkzeugaufrufe=[Werkzeugaufruf(id="w", name="t", argumente={})],
    )
    ergebnis = _nachricht("tool", "ergebnis", aufruf_id="a1")
    # Exactly 19 messages after the pair: the tail's own 20-message window
    # then lands its start precisely on `ergebnis`.
    danach = [_nachricht("assistant", f"weiter {i}") for i in range(19)]
    nachrichten = _lauf(10) + [aufruf, ergebnis] + danach
    anfrage = _Anfrage(nachrichten=list(nachrichten))
    zustand = _Zustand(provider=_Zusammenfasser("gerafft"))

    await verdichtung.verdichten(zustand, anfrage, schluessel=SCHLUESSEL)

    if ergebnis in anfrage.nachrichten:
        assert aufruf in anfrage.nachrichten
    for i, nachricht in enumerate(anfrage.nachrichten):
        if nachricht.role == "tool":
            assert anfrage.nachrichten[i - 1].role == "assistant"


# --- die neueste Nachricht bleibt, egal wie gross ---


def _tail_start_of_texts(inhalte):
    """The boundary over texts: each one weighs its length."""
    return verdichtung.tail_start_from_weights([len(t) for t in inhalte])


def test_eine_riesige_letzte_nachricht_leert_den_schwanz_nicht():
    """Attaching a large file has to stay possible.

    The rule that the message busting the budget is not kept is right in the
    middle of a history and wrong at its end: there it returned the length
    of the list, an EMPTY tail, and the middle then ran all the way to the
    final message. Measured before this: an 80 KB attachment meant the
    question the user had just typed was summarized away before it was ever
    answered.
    """
    riesig = "x" * (verdichtung.LETZTE_ZEICHEN + 10)
    inhalte = ["eins", "zwei", "drei", "vier", riesig]

    assert _tail_start_of_texts(inhalte) == len(inhalte) - 1


def test_eine_einzige_riesige_nachricht_ist_ganz_schwanz():
    riesig = "x" * (verdichtung.LETZTE_ZEICHEN + 10)
    assert _tail_start_of_texts([riesig]) == 0


def test_eine_riesige_nachricht_in_der_mitte_pinnt_sich_nicht_selbst():
    """The original rule, still doing its job where it belongs: a huge tool
    result in the middle must not drag everything behind it into the tail."""
    riesig = "x" * (verdichtung.LETZTE_ZEICHEN + 10)
    inhalte = ["eins", riesig, "drei", "vier", "fuenf"]

    assert _tail_start_of_texts(inhalte) == 2


def test_ohne_inhalte_faengt_der_schwanz_bei_null_an():
    assert _tail_start_of_texts([]) == 0


def test_chat_und_auftrag_ziehen_dieselbe_budgetgrenze():
    """The BUDGET boundary is one function, asked twice — two copies of the
    same walk is how they end up disagreeing.

    The chat lays a second rule on top of it (nothing past the last answer
    is folded, see the test below), so the two only have to match where that
    rule does not bite: a history that ends with an answer.
    """
    from app.chatverdichtung import _mitte_suchen

    class _Zeile:
        def __init__(self, inhalt):
            self.content = inhalt
            self.id = inhalt[:8]
            # Answers throughout, so the chat's own "nothing unread" rule
            # never moves the boundary and the budget alone decides.
            self.role = "assistant"
            self.art = "nachricht"

    riesig = "x" * (verdichtung.LETZTE_ZEICHEN + 10)
    for inhalte in (
        [],
        ["a"],
        ["a", "b", "c"],
        ["a", "b", "c", "d", riesig],
        ["a", riesig, "c", "d", "e"],
        [f"z{i}" + "y" * (verdichtung.LETZTE_ZEICHEN // 5) for i in range(20)],
    ):
        grenze = _tail_start_of_texts(inhalte)
        mitte = _mitte_suchen([_Zeile(t) for t in inhalte])
        erwartet = inhalte[verdichtung.ERSTE_FEST : grenze]
        assert [z.content for z in mitte] == erwartet, inhalte[:2]


def test_der_chat_faltet_nichts_ein_das_noch_niemand_gelesen_hat():
    """A finished command's report is UNREAD until an answer responds to it.

    A 90 KB test log busts the tail budget by itself, so it fell into the
    middle — and the run woken to read that very report was handed a summary
    of it instead. The tail's own "keep the newest" rule does not cover the
    case: a second command finishing while the first wake is still queued
    makes the big one second-to-last.
    """
    from app.chatverdichtung import _mitte_suchen

    class _Zeile:
        def __init__(self, inhalt, rolle="assistant", art="nachricht"):
            self.content = inhalt
            self.id = inhalt[:12]
            self.role = rolle
            self.art = art

    from app.hintergrundmeldung import MAX_ZEICHEN

    je = verdichtung.LETZTE_ZEICHEN // 8
    zeilen = [_Zeile(f"alt {i} " + "x" * je) for i in range(14)]
    # The size a report really has: `hintergrundmeldung` cuts the output at
    # MAX_ZEICHEN, so one is a couple of thousand characters and never the
    # eighty thousand the tail budget is.
    erst = _Zeile("BERICHT EINS " + "y" * MAX_ZEICHEN, art="werkzeugmeldung")
    zweit = _Zeile("BERICHT ZWEI " + "y" * MAX_ZEICHEN, art="werkzeugmeldung")
    alle = zeilen + [erst, zweit]

    mitte = _mitte_suchen(alle)

    kennungen = [z.id for z in mitte]
    assert erst.id not in kennungen, "the unread report was folded away"
    assert zweit.id not in kennungen
    # And there is still a genuine middle to fold — the rule narrows it, it
    # does not switch compaction off.
    assert mitte, "nothing left to fold at all"


def test_ungelesenes_ist_geschuetzt_aber_gedeckelt():
    """Protecting the unread stretch outright took the cap off entirely.

    Reports stack without a wake of their own — the postponement holds chat
    IDS, so twenty commands finishing during one answer make twenty rows and
    a single wake, and the wake brake stops waking long before the report
    writer stops writing. Measured with two hundred stacked reports: 428,387
    characters kept verbatim where the budget says 102,955, and compaction
    could no longer bring the context down at all.

    So the unread stretch is measured against the SAME budget — whole while
    it fits, cut from the front when it does not. The newest reports, the
    ones a wake is about, survive either way.
    """
    from app.chatverdichtung import _mitte_suchen
    from app.hintergrundmeldung import MAX_ZEICHEN

    class _Zeile:
        def __init__(self, inhalt, rolle="assistant", art="nachricht"):
            self.content = inhalt
            self.id = inhalt[:14]
            self.role = rolle
            self.art = art

    je = verdichtung.LETZTE_ZEICHEN // 4
    basis = [_Zeile(f"alt {i} " + "x" * je) for i in range(8)]
    berichte = [
        _Zeile(f"B{i} " + "y" * MAX_ZEICHEN, art="werkzeugmeldung")
        for i in range(200)
    ]
    alle = basis + berichte

    mitte = _mitte_suchen(alle)

    schwanz = alle[verdichtung.ERSTE_FEST + len(mitte):]
    zeichen = sum(len(z.content) for z in schwanz)
    assert zeichen <= verdichtung.LETZTE_ZEICHEN, (
        f"{zeichen} characters verbatim against a budget of "
        f"{verdichtung.LETZTE_ZEICHEN}"
    )
    # The newest report is still there — that is what the rule is for.
    assert schwanz[-1].id == berichte[-1].id


async def test_eine_zusammenfassung_ohne_ersparnis_beendet_die_notfallreihe(uhr):
    """The model ANSWERED — it merely did not save anything. The run of
    emergency folds is about a model that cannot write a summary, so it
    starts over."""
    zustand = _Zustand(provider=_Zusammenfasser(""))
    await verdichtung.verdichten(zustand, _Anfrage(nachrichten=_lauf(20)), schluessel=SCHLUESSEL)
    uhr.weiter(faltpause.PAUSE_LANG)

    # A real answer, far too long to save anything.
    lang = _Zustand(provider=_Zusammenfasser("z" * (JE_NACHRICHT * 40)))
    ergebnis = await verdichtung.verdichten(
        lang, _Anfrage(nachrichten=_lauf(20)), schluessel=SCHLUESSEL
    )
    assert ergebnis.ohne_ersparnis is True

    # So the next failure is the FIRST of its run, not the second.
    assert faltpause.notfall(SCHLUESSEL, faltpause.KURZ) is False


# --- the middle's tool calls, capped and paired ---


async def test_die_bitte_traegt_werkzeuge_gekappt_und_gepaart():
    """A run's tool calls reach the summarizer the way a chat's do: the call
    and what came back in one line of the turn that made it, capped.

    Sent as the provider's own shape, a result travelled WHOLE — one command
    printing a megabyte was the entire request — and a middle beginning
    behind its own call carried a result nothing explained.
    """
    aufruf = ChatNachricht(
        role="assistant",
        content="Erledigt.",
        werkzeugaufrufe=[
            Werkzeugaufruf(id="w1", name="run_command", argumente={"command": "cat log"})
        ],
    )
    ergebnis = _nachricht("tool", "ANFANG" + "Q" * 20_000 + "ENDE", aufruf_id="w1")
    anfrage = _Anfrage(nachrichten=_lauf(4) + [aufruf, ergebnis] + _lauf(20))
    fasser = _Zusammenfasser()

    await verdichtung.verdichten(
        _Zustand(provider=fasser), anfrage, schluessel=SCHLUESSEL
    )

    gefragt = fasser.gesehene_anfragen[0].nachrichten
    # Folded into the turn that called: no message of its own to pair up
    # again, and no call left standing without its answer.
    assert all(nachricht.role != "tool" for nachricht in gefragt)
    assert all(not nachricht.werkzeugaufrufe for nachricht in gefragt)
    text = "\n".join(nachricht.content for nachricht in gefragt)
    assert faltbitte.KOPFZEILE in text
    assert '- run_command {"command": "cat log"} → ANFANG' in text
    assert "ENDE" in text
    assert faltbitte.ERGEBNIS_VERMERK in text
    assert text.count("Q") < 20_000


async def test_ein_auftrag_traegt_mehr_vom_ergebnis_als_ein_chat():
    """A run's request keeps the wider ceiling, and a chat's does not.

    The two hand in different text: a run's messages carry their results
    whole until the request is written, so this IS the last reader of them.
    A chat hands in what its prompts already carried
    (``verlaufsbau.VERLAUF_ERGEBNIS_ZEICHEN``), and nothing here widens
    that again.
    """
    aufruf = ChatNachricht(
        role="assistant",
        content="Erledigt.",
        werkzeugaufrufe=[
            Werkzeugaufruf(id="w1", name="run_command", argumente={"command": "cat log"})
        ],
    )
    ergebnis = _nachricht("tool", "Q" * 25_000, aufruf_id="w1")
    anfrage = _Anfrage(nachrichten=_lauf(4) + [aufruf, ergebnis] + _lauf(20))
    fasser = _Zusammenfasser()

    await verdichtung.verdichten(
        _Zustand(provider=fasser), anfrage, schluessel=SCHLUESSEL
    )

    text = "\n".join(n.content for n in fasser.gesehene_anfragen[0].nachrichten)
    # Cut from the middle, so the front and the end of it are what arrives.
    assert text.count("Q") == faltbitte.ERGEBNIS_KOPF + faltbitte.ERGEBNIS_FUSS
    assert text.count("Q") > verlaufsbau.VERLAUF_ERGEBNIS_ZEICHEN


async def test_die_bitte_verliert_die_bilder_der_mitte_nicht():
    """A message rebuilt for the request keeps what it carried.

    A turn whose whole payload is a picture would otherwise reach the
    summarizer with nothing in it at all, and most OpenAI-compatible servers
    refuse such a message — every fold of the run would end as a caught
    exception and fold nothing.
    """
    mit_bild = ChatNachricht(
        role="user", content="", bild_urls=["data:image/png;base64,QUJD"]
    )
    # Long enough to have a middle at all, short enough that the whole
    # request stays under the ceiling — capped, it would be one message and
    # this test would be about the ceiling instead of about the picture.
    anfrage = _Anfrage(nachrichten=_lauf(2) + [mit_bild] + _lauf(11))
    fasser = _Zusammenfasser()

    await verdichtung.verdichten(
        _Zustand(provider=fasser), anfrage, schluessel=SCHLUESSEL
    )

    gefragt = fasser.gesehene_anfragen[0].nachrichten
    assert len(gefragt) > 2
    assert any(n.bild_urls == ["data:image/png;base64,QUJD"] for n in gefragt)


# --- The refused thinking stages: one list, read and written by the fold ---

ABLEHNUNG = "thinking: this parameter is not supported by this model"


class _Ablehnend(_Zusammenfasser):
    """A server that refuses the fold's thinking switch."""

    def __init__(self, status: int = 400, text: str = ABLEHNUNG):
        super().__init__()
        self.status = status
        self.text = text

    async def streamen(self, anfrage):
        from app.providers import ProviderFehler

        self.gesehene_anfragen.append(anfrage)
        raise ProviderFehler("abgelehnt", status=self.status, rohtext=self.text)
        yield  # pragma: no cover


async def test_eine_gemerkte_ablehnung_von_aus_geht_nicht_mit_in_die_faltung(repos):
    """The fold reads the list its run reads: a switch this server has
    refused before is not sent again."""
    from app import denkablehnung

    denkablehnung.merken(repos.einstellungen, "srv", "off")
    fasser = _Zusammenfasser()

    await verdichtung.verdichten(
        _Zustand(fasser, _llama()), _lauf_mit_denklaenge(), schluessel=SCHLUESSEL,
        einstellungen=repos.einstellungen, endpoint_id="srv",
    )

    assert fasser.gesehene_anfragen[0].zusatz == {}


async def test_ohne_gemerkte_ablehnung_bleibt_der_schalter_in_der_faltung(repos):
    """The silence probe: nothing refused, the switch goes out as before."""
    fasser = _Zusammenfasser()

    await verdichtung.verdichten(
        _Zustand(fasser, _llama()), _lauf_mit_denklaenge(), schluessel=SCHLUESSEL,
        einstellungen=repos.einstellungen, endpoint_id="srv",
    )

    assert fasser.gesehene_anfragen[0].zusatz


async def test_eine_abgelehnte_faltung_merkt_sich_aus_und_fragt_danach_ohne(repos):
    """A server that refuses the fold's "off" has it written down under its
    id — and the next fold on that server goes out without the switch."""
    from app import denkablehnung

    ablehnend = _Ablehnend()
    await verdichtung.verdichten(
        _Zustand(ablehnend, _llama()), _lauf_mit_denklaenge(), schluessel="erster",
        einstellungen=repos.einstellungen, endpoint_id="srv",
    )
    assert ablehnend.gesehene_anfragen[0].zusatz, "no switch went out, nothing to refuse"
    assert denkablehnung.gemerkt(repos.einstellungen, "srv") == ["off"]

    fasser = _Zusammenfasser()
    await verdichtung.verdichten(
        _Zustand(fasser, _llama()), _lauf_mit_denklaenge(), schluessel="zweiter",
        einstellungen=repos.einstellungen, endpoint_id="srv",
    )
    assert fasser.gesehene_anfragen[0].zusatz == {}


async def test_ein_anderer_fehler_der_faltung_merkt_nichts(repos):
    """A server that is down or full is not a refusal of the switch."""
    from app import denkablehnung

    await verdichtung.verdichten(
        _Zustand(_Ablehnend(status=500, text="upstream down"), _llama()),
        _lauf_mit_denklaenge(), schluessel=SCHLUESSEL,
        einstellungen=repos.einstellungen, endpoint_id="srv",
    )

    assert denkablehnung.gemerkt(repos.einstellungen, "srv") == []


async def test_ein_scheiternder_eintrag_beendet_die_faltung_nicht(repos, monkeypatch):
    """The refusal is written inside the handler of a fold that already
    failed; a write that fails too is logged, and the fold still answers
    "nothing folded" instead of ending its run."""
    from app import denkablehnung

    def kaputt(*args, **kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(denkablehnung, "merken", kaputt)

    ergebnis = await verdichtung.verdichten(
        _Zustand(_Ablehnend(), _llama()), _lauf_mit_denklaenge(), schluessel=SCHLUESSEL,
        einstellungen=repos.einstellungen, endpoint_id="srv",
    )

    assert ergebnis.angewendet is False
    assert ergebnis.notfall is True


class _RefusesOnce(_Zusammenfasser):
    """Refuses the switch on the first request, writes a summary on the next."""

    def __init__(self, status: int = 400, text: str = ABLEHNUNG):
        super().__init__()
        self.status = status
        self.text = text

    async def streamen(self, anfrage):
        from app.providers import ProviderFehler

        self.gesehene_anfragen.append(anfrage)
        if len(self.gesehene_anfragen) == 1:
            raise ProviderFehler("refused", status=self.status, rohtext=self.text)
        yield Stueck("content", text=self.antwort)


async def test_a_refused_switch_is_asked_once_more_without_it_and_folds(repos):
    """The refusal is written down, and the same fold goes out once more at
    once without the switch; its summary is used."""
    from app import denkablehnung

    server = _RefusesOnce()
    ergebnis = await verdichtung.verdichten(
        _Zustand(server, _llama()), _lauf_mit_denklaenge(), schluessel="retry",
        einstellungen=repos.einstellungen, endpoint_id="srv",
    )
    assert len(server.gesehene_anfragen) == 2
    assert server.gesehene_anfragen[0].zusatz
    assert server.gesehene_anfragen[1].zusatz == {}
    assert ergebnis.angewendet is True
    assert denkablehnung.gemerkt(repos.einstellungen, "srv") == ["off"]


async def test_another_400_of_the_fold_is_not_asked_again(repos):
    """Silence probe: any other failure stays one request, as before."""
    server = _RefusesOnce(text="invalid_api_key: the key is wrong")
    ergebnis = await verdichtung.verdichten(
        _Zustand(server, _llama()), _lauf_mit_denklaenge(), schluessel="other",
        einstellungen=repos.einstellungen, endpoint_id="srv",
    )
    assert len(server.gesehene_anfragen) == 1
    assert ergebnis.angewendet is False


async def test_a_summary_behind_a_clock_sentence_still_passes_its_sentence_on():
    """A clock sentence in front of a summary row hides the preamble it
    begins with. The summary is known by its mark, not by its text, so its
    document sentence still goes on."""
    from app import chatverdichtung

    old = _Dokument(id="d0", filename="angebot.pdf", extracted_text="A" * 1_200)
    sentence = chatverdichtung._dokumentnachweis([old])
    messages = _lauf(30)
    row = _summary_row(old)
    messages[4] = dataclasses.replace(
        row, content=f"[It is Monday, 10:00.]\n\n{row.content}"
    )
    request = _Anfrage(nachrichten=messages)

    result = await verdichtung.verdichten(
        _Zustand(_Zusammenfasser()), request, schluessel=SCHLUESSEL
    )

    assert result.angewendet is True
    assert request.nachrichten[3].compacted_summary is True
    assert request.nachrichten[3].content.endswith(sentence)


async def test_silent_a_message_only_starting_like_a_summary_is_none():
    """A message that merely begins with the preamble — quoted by the user —
    and carries no mark is no summary: its sentence is not passed on."""
    from app import chatverdichtung

    old = _Dokument(id="d0", filename="angebot.pdf", extracted_text="A" * 1_200)
    sentence = chatverdichtung._dokumentnachweis([old])
    messages = _lauf(30)
    messages[4] = dataclasses.replace(
        _summary_row(old), compacted_summary=False
    )
    request = _Anfrage(nachrichten=messages)

    await verdichtung.verdichten(_Zustand(_Zusammenfasser()), request, schluessel=SCHLUESSEL)

    assert sentence not in request.nachrichten[3].content
