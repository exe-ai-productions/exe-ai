"""How long one answer may be — "Auto" and everything around it.

There is no shipped ceiling any more. What is set wins. Where nothing is
set, the wire decides: on the Anthropic wire the largest number that still
fits (``min(the provider's own limit, window - input - margin)``), on the
OpenAI wire no number at all — the server decides.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import antwortgrenze, kontextdruck, kontextvoll
from app.providers import MockProvider, ProviderFehler, mock_endpunkt
from app.providers.base import ChatNachricht, Stueck, Werkzeugaufruf
from app.tokenmass import tokens as tokenmass_tokens
from tests.conftest import provider_setzen

ABSTAND = kontextvoll.SICHERHEITSABSTAND


# --- The calculation -------------------------------------------------------


def test_eine_eingestellte_grenze_gewinnt():
    """The slider, the agent head, the settings — whatever named a number
    wins outright, whatever else would have fitted, on either wire."""
    assert antwortgrenze.aufloesen(4_000, 128_000, 200_000, 50_000, anthropic=True) == 4_000
    assert antwortgrenze.aufloesen(4_000, None, 8_192, 8_000, anthropic=True) == 4_000
    assert antwortgrenze.aufloesen(4_000, 128_000, 200_000, 50_000, anthropic=False) == 4_000
    assert antwortgrenze.aufloesen(4_000, None, 8_192, 8_000, anthropic=False) == 4_000


def test_auf_dem_openai_draht_reist_ohne_einstellung_keine_zahl():
    """Auto on the OpenAI wire is no number at all: the server decides how
    long an answer may be. Whatever the window, the input or a provider
    limit says — nothing goes out."""
    assert antwortgrenze.aufloesen(None, 128_000, 200_000, 50_000, anthropic=False) is None
    assert antwortgrenze.aufloesen(None, None, 8_192, 1_000, anthropic=False) is None
    assert antwortgrenze.aufloesen(None, None, 8_192, 100_000, anthropic=False) is None


def test_auto_nimmt_das_kleinere_von_hersteller_und_fenster():
    """Window 200k, an estimated 50k of input, and a provider that allows
    128k out: the provider's own limit is what binds."""
    assert antwortgrenze.aufloesen(None, 128_000, 200_000, 50_000, anthropic=True) == 128_000


def test_ohne_herstellerwert_entscheidet_das_fenster():
    """Nobody names an output limit — then only the window does."""
    assert (
        antwortgrenze.aufloesen(None, None, 200_000, 50_000, anthropic=True)
        == 150_000 - ABSTAND
    )


def test_der_rand_gibt_nie_none():
    """On the wire that needs a number, an input leaving less than one token
    of room still yields a sendable one: the smallest the house's own schema
    accepts (app/api/v1/schemas.py, ``ge=1``)."""
    assert (
        antwortgrenze.aufloesen(None, None, 8_192, 8_190, anthropic=True)
        == antwortgrenze.MINDESTWERT
    )
    assert (
        antwortgrenze.aufloesen(None, None, 8_192, 100_000, anthropic=True)
        == antwortgrenze.MINDESTWERT
    )


def test_schweigeprobe_mit_platz_kommt_nie_der_rand_heraus():
    """The silence probe for the line above: where there is room, the edge
    value never appears."""
    assert antwortgrenze.aufloesen(None, None, 8_192, 1_000, anthropic=True) == 7_192 - ABSTAND
    assert (
        antwortgrenze.aufloesen(None, None, 8_192, 1_000, anthropic=True)
        != antwortgrenze.MINDESTWERT
    )


def test_der_rand_sagt_es_jetzt_auch():
    """The edge is still sendable — and it is now also ASKABLE. A ceiling of
    1 and a ceiling of 1 look the same coming out of ``aufloesen``, whether
    the window left one token or thirty thousand short of one; this is how a
    caller tells those apart before it sends anything."""
    assert antwortgrenze.reicht_nicht(None, None, 8_192, 8_190, anthropic=True)
    assert antwortgrenze.reicht_nicht(None, None, 8_192, 100_000, anthropic=True)


def test_auf_dem_openai_draht_gibt_es_keinen_rand():
    """No number, no edge: what does not fit comes back as the provider's
    own refusal, and the fold and the lowering live there
    (app/kontextvoll.py)."""
    assert not antwortgrenze.reicht_nicht(None, None, 8_192, 8_190, anthropic=False)
    assert not antwortgrenze.reicht_nicht(None, None, 8_192, 100_000, anthropic=False)


def test_genau_ein_token_platz_ist_kein_platz():
    """A window that leaves exactly one token would send the edge as a
    ceiling — an answer of one token. That is no room, and the caller folds
    first. Two tokens are room: the line has not merely moved."""
    ein_token = 8_192 - ABSTAND - 1
    zwei_token = 8_192 - ABSTAND - 2
    assert antwortgrenze.reicht_nicht(None, None, 8_192, ein_token, anthropic=True)
    assert not antwortgrenze.reicht_nicht(None, None, 8_192, zwei_token, anthropic=True)
    # The same with a provider limit above what the window leaves.
    assert antwortgrenze.reicht_nicht(None, 64_000, 8_192, ein_token, anthropic=True)
    assert not antwortgrenze.reicht_nicht(None, 64_000, 8_192, zwei_token, anthropic=True)


def test_schweigeprobe_mit_platz_reicht_es():
    """The silence probe: an ordinary chat never meets this."""
    assert not antwortgrenze.reicht_nicht(None, None, 8_192, 1_000, anthropic=True)
    assert not antwortgrenze.reicht_nicht(None, 128_000, 200_000, 50_000, anthropic=True)


def test_eine_eingestellte_grenze_reicht_immer():
    """A number somebody set is never "not enough": it is what was asked
    for. An input too large for it is refused by the provider, and the
    lowering and the fold already live there."""
    assert not antwortgrenze.reicht_nicht(4_000, None, 8_192, 100_000, anthropic=True)


def test_der_herstellerwert_nimmt_den_platz_nie_weg():
    """The provider's own limit binds the same sum, but only downwards to
    itself — and it is a real number of tokens, so it can never be what
    leaves nothing at all."""
    assert not antwortgrenze.reicht_nicht(None, 1, 200_000, 50_000, anthropic=True)


def test_der_draht_kommt_von_der_anbieterklasse():
    """Which wire an endpoint speaks is its provider CLASS, not its
    parameter dialect: the dialect only names the fields."""

    class _Zustand:
        def __init__(self, provider, dialekt="openai"):
            self.endpunkt = type(
                "E", (), {"provider": provider, "parameter_dialect": dialekt}
            )()

    assert antwortgrenze.anthropic_draht(_Zustand("anthropic")) is True
    assert antwortgrenze.anthropic_draht(_Zustand("openai_compatible")) is False
    assert antwortgrenze.anthropic_draht(_Zustand("mock")) is False
    # A dialect named "anthropic" on an OpenAI-compatible endpoint is not
    # the Anthropic wire.
    assert antwortgrenze.anthropic_draht(_Zustand("openai_compatible", "anthropic")) is False


def test_die_eingabe_wird_gemessen():
    """No tokenizer on this side, but the text IS measured rather than
    divided (app/tokenmass.py, ``tokens``). The tool definitions count too —
    they travel in the same request."""
    nachrichten = [ChatNachricht(role="user", content="x" * 400)]
    assert antwortgrenze.eingabe_schaetzen(nachrichten) == 100
    mit_werkzeug = antwortgrenze.eingabe_schaetzen(nachrichten, [{"a": "y" * 400}])
    assert mit_werkzeug > 100


def test_ein_werkzeugaufruf_wiegt_mit():
    """A tool round's bulk lives in ``werkzeugaufrufe``, not in ``content``:
    a write call carrying kilobytes of arguments leaves the text untouched
    and still goes out in the same request."""
    text = ChatNachricht(role="user", content="x" * 400)
    argumente = {"pfad": "bericht.md", "inhalt": "y" * 8_000}
    aufruf = ChatNachricht(
        role="assistant",
        content="",
        werkzeugaufrufe=[
            Werkzeugaufruf(id="w1", name="datei_schreiben", argumente=argumente)
        ],
    )
    erwartet = 100 + tokenmass_tokens("datei_schreiben") + tokenmass_tokens(
        json.dumps(argumente, ensure_ascii=False)
    )
    assert antwortgrenze.eingabe_schaetzen([text, aufruf]) == erwartet


def test_ein_bild_wiegt_die_eine_hausschaetzung():
    """Images are priced by ``app/kontextdruck.py``'s one per-image estimate
    — the same number the fold trigger reckons with — and NOT by the length
    of the data URL, which is the transport rather than what the model is
    billed for. Counted apart, a chat with a picture asked for a ceiling the
    size of the whole window and was refused on every single request."""
    text = ChatNachricht(role="user", content="x" * 400)
    mit_bild = ChatNachricht(
        role="user", content="x" * 400, bild_url="data:image/png;base64," + "A" * 200_000
    )
    assert antwortgrenze.eingabe_schaetzen([mit_bild]) == (
        100 + kontextdruck.BILD_TOKEN_SCHAETZUNG
    )
    # Two images on one message weigh twice, single and list merged the way
    # the provider sends them (`ChatNachricht.alle_bild_urls`).
    zwei = ChatNachricht(
        role="user", content="x" * 400, bild_url="data:image/png;base64,A",
        bild_urls=["data:image/png;base64,B"],
    )
    assert antwortgrenze.eingabe_schaetzen([zwei]) == (
        100 + 2 * kontextdruck.BILD_TOKEN_SCHAETZUNG
    )
    assert antwortgrenze.eingabe_schaetzen([text]) == 100


def test_schweigeprobe_reiner_text_zaehlt_unveraendert():
    """The silence probe for both lines above: a message with neither a tool
    call nor a picture weighs exactly what its characters weigh — the two
    new parts add nothing where there are none."""
    nachrichten = [
        ChatNachricht(role="user", content="x" * 400),
        ChatNachricht(role="assistant", content="y" * 800),
        ChatNachricht(role="tool", content="z" * 400, werkzeugaufruf_id="w1"),
    ]
    assert antwortgrenze.eingabe_schaetzen(nachrichten) == 400


def test_der_kleinere_der_beiden_werte_gewinnt():
    """A refusal is a hard upper bound: the provider has already turned a
    request down for that number. A model list only publishes what an
    endpoint claims, and a claim above what the model takes costs every
    single request a failed attempt — so the smaller one binds, whichever
    source it came from."""
    assert antwortgrenze.hoechstwert(server=32_000, gelernt=4_096) == 4_096
    assert antwortgrenze.hoechstwert(server=4_096, gelernt=8_192) == 4_096


def test_schweigeprobe_ist_nur_einer_da_gilt_dieser():
    """Nothing is invented where one of the two has nothing to say, and
    nothing at all where neither has — then the window alone decides."""
    assert antwortgrenze.hoechstwert(server=128_000, gelernt=None) == 128_000
    assert antwortgrenze.hoechstwert(server=None, gelernt=4_096) == 4_096
    assert antwortgrenze.hoechstwert(server=None, gelernt=None) is None


def test_ein_alter_gespeicherter_wert_wirkt_nicht_mehr(client):
    """The output limit a refusal names holds for the RUN, and
    nothing about it is stored. A value an older installation left in the
    settings is not read anywhere — this test writes exactly such a row and
    shows it changes nothing.

    The window beside it stays learned, and that difference is the point: a
    smaller window is a fact about the model, a smaller answer length is
    what ONE request was just turned down for. Kept, it went on to bind
    every other model behind the same address (app/fenstergroesse.py keeps
    its own pair of functions for the half that stays).
    """
    import asyncio

    zustand = client.app.state.discovery.zustaende["test"]
    repositories = client.app.state.repositories

    # The row an older version would have written.
    from app import fenstergroesse

    repositories.einstellungen.setzen(
        "gelernte_antwortgrenzen",
        f"test:{fenstergroesse.modellschluessel(zustand) or ''}",
        4_096,
    )

    class _ListeNenntZuViel(MockProvider):
        async def hoechste_antwort(self, timeout=3.0, modellname=None):
            return 32_000

    provider_setzen(client, _ListeNenntZuViel(mock_endpunkt("test")))
    aufgeloest = asyncio.run(
        antwortgrenze.serverseitig_aufloesen(zustand, repositories, 1.0)
    )
    # The list's own number stands: no stored value walks back in.
    assert aufgeloest == 32_000


def test_serverseitig_aufloesen_faltet_keine_ablehnung_ein(client):
    """The SERVER's number, and nothing else.

    The value a refusal named belongs to one request; the field this route
    fills is the one the model list writes, and it stands for every request.
    Folding the pass value in here would write it back into
    that field through the back door — in a catalogue endpoint, where this
    route runs once per model and the field is shared, it would bind every
    other model behind the same address.
    """
    import asyncio

    zustand = client.app.state.discovery.zustaende["test"]
    repositories = client.app.state.repositories

    class _ListeNenntZweiunddreissig(MockProvider):
        async def hoechste_antwort(self, timeout=3.0, modellname=None):
            return 32_000

    provider_setzen(client, _ListeNenntZweiunddreissig(mock_endpunkt("test")))
    abgelehnt = antwortgrenze.Zug(max_tokens=4_096)
    aufgeloest = asyncio.run(
        antwortgrenze.serverseitig_aufloesen(zustand, repositories, 1.0)
    )
    assert aufgeloest == 32_000
    # And the pass value stays where it belongs, untouched beside it.
    assert abgelehnt.max_tokens == 4_096


def test_der_fluechtige_wert_gilt_fuer_die_aufloesung_dieses_zugs(client):
    """The other half: what a refusal of THIS request put on the state does
    bind — that is what makes the retry go out with an acceptable number.

    And the silence of the same pair: the number the MODEL LIST names is
    untouched by it and is what binds again one request later. That is the
    whole difference the two numbers carry."""
    zustand = client.app.state.discovery.zustaende["test"]
    # The list's own number, as the discovery writes it, and beside it the
    # smaller one a refusal of this request named.
    zustand.hersteller_max_tokens = 32_000
    zug = antwortgrenze.Zug(max_tokens=4_096)

    # The smaller binds while the request runs — one reader, both numbers.
    assert antwortgrenze.geltender_deckel(zustand, None, zug) == 4_096

    # A new request has a holder of its own: the list's number stands.
    assert zustand.hersteller_max_tokens == 32_000
    assert antwortgrenze.geltender_deckel(zustand, None, antwortgrenze.Zug()) == 32_000
    assert antwortgrenze.geltender_deckel(zustand) == 32_000


# --- The chat --------------------------------------------------------------


def _senden(client, chat_id: str, **felder) -> None:
    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Frage", **felder},
    )
    assert antwort.status_code == 200
    antwort.text  # drain the stream so the run finishes


def _anthropic_draht(client, kennung: str = "test") -> None:
    """Puts the test endpoint on the ANTHROPIC wire — the only wire a number
    still travels on under Auto (app/antwortgrenze.py). The provider class
    stays the mock: these tests are about the arithmetic, not about the body
    a provider writes."""
    zustand = client.app.state.discovery.zustaende[kennung]
    zustand.endpunkt = mock_endpunkt(kennung, provider="anthropic")


def _erwartet(anfrage, fenster: int, hersteller: int | None = None) -> int:
    eingabe = antwortgrenze.eingabe_schaetzen(anfrage.nachrichten, anfrage.werkzeuge)
    passt = fenster - eingabe - ABSTAND
    return min(hersteller, passt) if hersteller else passt


def test_chat_auf_dem_openai_draht_traegt_keine_zahl(client, chat_id):
    """Auto on the OpenAI wire: the body carries no ``max_tokens`` at all,
    and the answer comes back whole — the server decides its length."""
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test")))
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.context_tokens = 200_000
    zustand.hersteller_max_tokens = 128_000

    _senden(client, chat_id)

    assert provider.letzte_anfrage.max_tokens is None


def test_chat_unberuehrt_nimmt_das_groesste_was_passt(client, chat_id):
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test")))
    _anthropic_draht(client)
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.context_tokens = 200_000
    zustand.hersteller_max_tokens = None

    _senden(client, chat_id)

    gesendet = provider.letzte_anfrage
    assert gesendet.max_tokens == _erwartet(gesendet, 200_000)


def test_chat_bleibt_unter_dem_herstellerwert(client, chat_id):
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test")))
    _anthropic_draht(client)
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.context_tokens = 200_000
    zustand.hersteller_max_tokens = 128_000

    _senden(client, chat_id)

    assert provider.letzte_anfrage.max_tokens == 128_000


def test_chat_eine_eingestellte_grenze_gewinnt(client, chat_id):
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test")))
    client.app.state.discovery.zustaende["test"].context_tokens = 200_000

    _senden(client, chat_id, max_tokens=4_000)

    assert provider.letzte_anfrage.max_tokens == 4_000


def test_chat_der_rand_schickt_eine_eins_statt_nichts(client, chat_id):
    """A window so small that the input fills it: on the wire that needs a
    number the request still carries a sendable ceiling. What makes room is
    the fold, one layer on."""
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test")))
    _anthropic_draht(client)
    client.app.state.discovery.zustaende["test"].context_tokens = 8_192
    repositories = client.app.state.repositories
    repositories.messages.speichern(
        chat_id=chat_id, role="user", content="x" * (8_190 * 4)
    )

    _senden(client, chat_id)

    assert provider.letzte_anfrage.max_tokens == antwortgrenze.MINDESTWERT


# --- What a message carries besides its text --------------------------------
#
# Counted against what the estimate came to while it read `content` alone:
# that number is what these two parts used to be missing from, and a test
# that recomputed the estimate with the same function would prove nothing.

# 8000 characters of arguments are 2000 tokens of the house proxy — far too
# many to hide inside a rounding difference.
SCHREIB_ARGUMENTE = {"pfad": "bericht.md", "inhalt": "y" * 8_000}
AUFRUF_TOKENS = 2_000


def _nur_inhalt(nachrichten) -> int:
    """What the estimate came to counting `content` alone."""
    return sum(tokenmass_tokens(n.content) for n in nachrichten)


def _bild_ablegen(config, name: str = "foto.png") -> None:
    """One picture in the picture folder, so a stored attachment really
    reaches the request as a data URL (app/verlaufsbau.py)."""
    from app.api.v1.bilder import bilder_verzeichnis

    ordner = bilder_verzeichnis(config)
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / name).write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)


class _ErstWerkzeugDannText(MockProvider):
    """One round asking for a tool with heavy arguments, then an answer.
    The tool does not exist — nothing is executed, and the assistant turn
    carrying the call still joins the history the next round is sent with."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.grenzen: list[int | None] = []
        self.verlaeufe: list[list] = []

    async def streamen(self, anfrage):
        from app.providers.base import Stueck

        self.grenzen.append(anfrage.max_tokens)
        self.verlaeufe.append(list(anfrage.nachrichten))
        if len(self.grenzen) == 1:
            yield Stueck("content", text="Looking. ")
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[
                    Werkzeugaufruf(
                        id="w1", name="kein_solches_werkzeug", argumente=SCHREIB_ARGUMENTE
                    )
                ],
            )
            return
        yield Stueck("content", text="Done.")


def test_chat_ein_werkzeugaufruf_der_vorrunde_wiegt_mit(client, chat_id):
    """The second round of a chat is sent with the first round's tool call in
    its history. Its arguments grow only there, never in `content`, so an
    estimate reading `content` alone asked for a ceiling that the round's own
    input had already taken."""
    provider = provider_setzen(client, _ErstWerkzeugDannText(mock_endpunkt("test")))
    _anthropic_draht(client)
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.context_tokens = 200_000
    zustand.hersteller_max_tokens = None

    _senden(client, chat_id)

    assert len(provider.grenzen) == 2
    zweiter = provider.verlaeufe[1]
    assert any(n.werkzeugaufrufe for n in zweiter)
    nur_text = 200_000 - _nur_inhalt(zweiter) - ABSTAND
    assert provider.grenzen[1] <= nur_text - AUFRUF_TOKENS


def test_chat_ein_bild_wiegt_mit(config, client, chat_id):
    """A picture in the history is worth the house's one per-image estimate.
    Weighed at nothing, a chat with a picture in it asked for a ceiling the
    size of the whole window on every single request."""
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test")))
    _anthropic_draht(client)
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.context_tokens = 200_000
    zustand.hersteller_max_tokens = None
    zustand.faehigkeiten_erkannt = {"vision": True}
    _bild_ablegen(config)
    client.app.state.repositories.messages.speichern(
        chat_id=chat_id, role="user", content="Was ist das?", anhaenge=["foto.png"]
    )

    _senden(client, chat_id)

    gesendet = provider.letzte_anfrage
    assert any(n.alle_bild_urls() for n in gesendet.nachrichten)
    assert gesendet.max_tokens == (
        200_000
        - _nur_inhalt(gesendet.nachrichten)
        - kontextdruck.BILD_TOKEN_SCHAETZUNG
        - ABSTAND
    )


def test_schweigeprobe_chat_ohne_bild_und_werkzeug_bleibt_wie_es_war(client, chat_id):
    """The silence probe for both: a plain text chat still gets exactly the
    ceiling the character count alone gives it."""
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test")))
    _anthropic_draht(client)
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.context_tokens = 200_000
    zustand.hersteller_max_tokens = None

    _senden(client, chat_id)

    gesendet = provider.letzte_anfrage
    assert gesendet.max_tokens == (
        200_000 - _nur_inhalt(gesendet.nachrichten) - ABSTAND
    )


def test_auftrag_ein_werkzeugaufruf_der_vorrunde_wiegt_mit(config, client):
    """The same for a job: every round works the ceiling out again from its
    own, longer history (app/api/v1/auftraege.py), and a tool round's
    arguments are part of it."""
    from tests.test_auftraege_api import agent_schreiben, auf_ende_warten

    agent_schreiben(config)
    provider = provider_setzen(client, _ErstWerkzeugDannText(mock_endpunkt("test")))
    _anthropic_draht(client)
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.context_tokens = 200_000
    zustand.hersteller_max_tokens = None

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    auf_ende_warten(client, kennung)

    assert len(provider.grenzen) == 2
    zweiter = provider.verlaeufe[1]
    assert any(n.werkzeugaufrufe for n in zweiter)
    nur_text = 200_000 - _nur_inhalt(zweiter) - ABSTAND
    assert provider.grenzen[1] <= nur_text - AUFRUF_TOKENS


def test_schweigeprobe_auftrag_ohne_werkzeugaufruf_bleibt_wie_es_war(config, client):
    from tests.test_auftraege_api import agent_schreiben, auf_ende_warten

    agent_schreiben(config)
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test")))
    _anthropic_draht(client)
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.context_tokens = 200_000
    zustand.hersteller_max_tokens = None

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    auf_ende_warten(client, kennung)

    gesendet = provider.letzte_anfrage
    assert gesendet.max_tokens == (
        200_000 - _nur_inhalt(gesendet.nachrichten) - ABSTAND
    )


# --- The provider's own limit, out of a model list --------------------------


def _aus_liste(eintrag: dict) -> int | None:
    """What the real OpenAI-compatible provider reads out of such a list."""
    import asyncio

    from app.providers.openai_kompatibel import OpenAIKompatiblerProvider

    class _Liste(OpenAIKompatiblerProvider):
        async def _json_holen(self, url: str, timeout: float):
            return {"data": [{"id": "test", **eintrag}]}

    return asyncio.run(_Liste(mock_endpunkt("test")).hoechste_antwort(1.0, "test"))


def test_ein_anderer_anbieter_nennt_seinen_hoechstwert_in_der_modellliste():
    """The three names an OpenAI-shaped model list uses for it, in the order
    they are read."""
    assert _aus_liste({"max_completion_tokens": 4_096}) == 4_096
    assert _aus_liste({"max_output_tokens": 8_192}) == 8_192
    assert _aus_liste({"max_tokens": 16_384}) == 16_384
    # The first one an entry carries wins.
    assert _aus_liste({"max_output_tokens": 8_192, "max_tokens": 16_384}) == 8_192


def test_schweigeprobe_eine_liste_ohne_das_feld_aendert_nichts():
    """A model list that names no limit leaves the window alone to decide —
    no number is invented for it."""
    assert _aus_liste({}) is None
    assert _aus_liste({"max_model_len": 32_768}) is None


# --- Learning a limit out of a refusal --------------------------------------

# Quoted by users of the live API in OpenAI's own developer forum; OpenAI's
# documentation carries no text for this case.
OPENAI_ZU_GROSS = (
    '{"error":{"message":"max_tokens is too large: 86000. This model supports at '
    'most 4096 completion tokens, whereas you provided 86000.",'
    '"type":"invalid_request_error","param":"max_tokens","code":null}}'
)


class _ZuGrossDannGut(MockProvider):
    """Refuses the first answer request with a stated output limit, then
    answers."""

    def __init__(self, *args, rohtext: str = OPENAI_ZU_GROSS, **kwargs):
        super().__init__(*args, **kwargs)
        self.rohtext = rohtext
        self.grenzen: list[int | None] = []

    async def streamen(self, anfrage):
        self.grenzen.append(anfrage.max_tokens)
        if len(self.grenzen) == 1:
            raise ProviderFehler(
                f"provider answered with 400: {self.rohtext}",
                status=400,
                rohtext=self.rohtext,
            )
        async for stueck in super().streamen(anfrage):
            yield stueck


def test_die_ablehnung_gilt_nur_im_laufenden_zug(client, chat_id):
    """The retry goes out with the number the provider named — and the NEXT
    request goes out with what the model list says, not with that number.

    One request costs one rejection; that it stays at one is the whole
    order: the ceiling is lowered for the running request
    only. Kept on the
    endpoint, the name of one model's refusal went on to bind every request
    after it and every model behind the same address.

    On the ANTHROPIC wire: that is where Auto still asks for a number and a
    provider limit can bind it. On the OpenAI wire no number goes out under
    Auto, so this refusal can only follow a ceiling somebody set — and then
    that setting wins anyway (app/antwortgrenze.py)."""
    provider = provider_setzen(client, _ZuGrossDannGut(mock_endpunkt("test")))
    _anthropic_draht(client)
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.context_tokens = 200_000

    _senden(client, chat_id)

    # Lowered for this request, and the answer came.
    assert provider.grenzen[0] > 4_096
    assert provider.grenzen[1] == 4_096
    # The number stands as the REQUEST's own — and only there: nothing of it
    # is on the shared endpoint state, and the field the model list writes
    # stays empty, so the next request begins where it should.
    assert not hasattr(zustand, "zug_max_tokens")
    assert zustand.hersteller_max_tokens is None
    # And nothing of it is stored: read under the key the old
    # writer would have used, ``endpunkt:modell`` with an empty model name
    # where there is none.
    from app import fenstergroesse

    assert client.app.state.repositories.einstellungen.holen(
        "gelernte_antwortgrenzen",
        f"test:{fenstergroesse.modellschluessel(zustand) or ''}",
    ) is None

    # The second request — a new one, not the retry — goes out LARGER again:
    # the refusal was about the request before it and is over. Same window,
    # same endpoint, nothing set by hand.
    zweiter = provider_setzen(client, MockProvider(mock_endpunkt("test")))
    _anthropic_draht(client)
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.context_tokens = 200_000
    _senden(client, chat_id)
    # The window decides again, not the refusal and not something between:
    # 4 096 would be the number the provider named, and the retry went out
    # with it — this one is two hundred thousand.
    assert zweiter.letzte_anfrage.max_tokens > 100_000
    assert provider.grenzen[1] == 4_096


def test_schweigeprobe_ein_fremder_400er_lernt_nichts(client, chat_id):
    fehler = ProviderFehler(
        'provider answered with 400: {"error":{"message":"invalid_api_key"}}',
        status=400,
        rohtext='{"error":{"message":"invalid_api_key"}}',
    )
    zustand = client.app.state.discovery.zustaende["test"]
    zug = antwortgrenze.Zug()
    antwortgrenze.aus_fehler_lernen(client.app.state.repositories, zustand, fehler, zug)
    assert zug.max_tokens is None
    assert zustand.hersteller_max_tokens is None
    from app import fenstergroesse

    assert fenstergroesse.gelernt_holen(
        client.app.state.repositories, "test", fenstergroesse.modellschluessel(zustand)
    ) is None


# --- Thinking items handed back on the Responses wire -----------------------

DENK_ITEM = {
    "type": "reasoning",
    "summary": [{"type": "summary_text", "text": "Checking the folder first."}],
    "encrypted_content": "gAAAAB" + "x" * 40_000,
}


def test_denk_items_wiegen_mit():
    """A round's sealed thinking goes back out with the next round, so it
    weighs on the input — counted with its ciphertext blanked."""
    ohne = ChatNachricht(role="assistant", content="Antwort")
    mit = ChatNachricht(role="assistant", content="Antwort", reasoning_items=[DENK_ITEM])

    assert antwortgrenze.eingabe_schaetzen([mit]) > antwortgrenze.eingabe_schaetzen([ohne])
    # The ciphertext adds nothing: a thousand times as much of it weighs the
    # same.
    larger = {**DENK_ITEM, "encrypted_content": DENK_ITEM["encrypted_content"] * 1_000}
    with_larger = ChatNachricht(
        role="assistant", content="Antwort", reasoning_items=[larger]
    )
    assert antwortgrenze.eingabe_schaetzen([with_larger]) == antwortgrenze.eingabe_schaetzen(
        [mit]
    )


def test_the_items_are_weighed_without_being_copied_or_serialized(monkeypatch):
    """The estimate is asked several times per round: an item is walked
    where it stands, never copied to blank its cipher and written out as
    JSON again on every call."""
    calls: list[object] = []
    real = json.dumps

    def counting(obj, *args, **kwargs):
        calls.append(obj)
        return real(obj, *args, **kwargs)

    monkeypatch.setattr(antwortgrenze.json, "dumps", counting)
    with_items = ChatNachricht(role="assistant", content="Answer", reasoning_items=[DENK_ITEM])
    antwortgrenze.eingabe_schaetzen([with_items])
    assert calls == []


def test_schweigeprobe_text_items_zaehlen_nicht_doppelt():
    """A message without items weighs what it did; its text items are its
    ``content`` already and add nothing."""
    ohne = ChatNachricht(role="assistant", content="Antwort")
    mit_text = ChatNachricht(
        role="assistant",
        content="Antwort",
        message_items=[{
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "Antwort"}],
        }],
    )
    assert antwortgrenze.eingabe_schaetzen([ohne]) == tokenmass_tokens("Antwort")
    assert antwortgrenze.eingabe_schaetzen([mit_text]) == antwortgrenze.eingabe_schaetzen([ohne])


# --- Thinking blocks handed back on the Anthropic wire -----------------------

THINKING_TEXT = "Let me look at the folder before I touch anything. " * 80


def _round(blocks):
    return ChatNachricht(
        role="assistant",
        content="I looked.",
        werkzeugaufrufe=[Werkzeugaufruf(id="toolu_1", name="read_file", argumente={"path": "a"})],
        anthropic_blocks=blocks,
    )


def test_the_thinking_text_of_a_round_weighs():
    """The round's thinking goes back with its tool results, so its text
    claims room in the next request."""
    without = _round([])
    with_thinking = _round([{"type": "thinking", "thinking": THINKING_TEXT, "signature": "sig"}])
    two = _round([
        {"type": "thinking", "thinking": THINKING_TEXT, "signature": "a"},
        {"type": "thinking", "thinking": THINKING_TEXT, "signature": "b"},
    ])

    base = antwortgrenze.eingabe_schaetzen([without])
    one = antwortgrenze.eingabe_schaetzen([with_thinking]) - base
    assert one == tokenmass_tokens(THINKING_TEXT)
    assert antwortgrenze.eingabe_schaetzen([two]) - base == 2 * one


def test_silence_the_seals_and_the_markers_add_nothing():
    """A signature and the data of a redacted block are the provider's seal;
    the text and tool_use blocks only mark their place."""
    without = antwortgrenze.eingabe_schaetzen([_round([])])
    blocks = [
        {"type": "thinking", "thinking": "", "signature": "s" * 100_000},
        {"type": "redacted_thinking", "data": "d" * 100_000},
        {"type": "text", "text": "I looked."},
        {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {"path": "a"}},
    ]

    assert antwortgrenze.eingabe_schaetzen([_round(blocks)]) == without


def test_silence_a_message_without_blocks_weighs_what_it_weighed():
    message = ChatNachricht(role="assistant", content="Answer")

    assert antwortgrenze.eingabe_schaetzen([message]) == tokenmass_tokens("Answer")


def test_the_blocks_are_weighed_without_being_serialized(monkeypatch):
    calls: list[object] = []
    real = json.dumps

    def counting(obj, *args, **kwargs):
        calls.append(obj)
        return real(obj, *args, **kwargs)

    monkeypatch.setattr(antwortgrenze.json, "dumps", counting)
    antwortgrenze.eingabe_schaetzen(
        [ChatNachricht(
            role="assistant", content="Answer",
            anthropic_blocks=[{"type": "thinking", "thinking": THINKING_TEXT, "signature": "s"}],
        )]
    )

    assert calls == []


# --- DashScope's two wordings of a stated output limit -----------------------

# Both are read: the upper bound of the range is the limit, and so is the
# number in brackets.
DASHSCOPE_BEREICH = (
    '{"error":{"message":"<400> InternalError.Algo.InvalidParameter: Range of '
    'max_tokens should be [1, 4096]","type":"invalid_request_error"}}'
)
DASHSCOPE_AUSGABE = (
    '{"error":{"message":"max_tokens 8192 exceeds model\'s maximum output tokens '
    '(4096)","type":"invalid_request_error"}}'
)
STATED_LIMITS = [DASHSCOPE_BEREICH, DASHSCOPE_AUSGABE, OPENAI_ZU_GROSS]


def _ablehnung(rohtext: str, status: int = 400) -> ProviderFehler:
    return ProviderFehler(
        f"provider answered with {status}: {rohtext}", status=status, rohtext=rohtext
    )


@pytest.mark.parametrize("rohtext", STATED_LIMITS)
def test_der_chat_geht_nach_der_ablehnung_mit_der_genannten_grenze_hinaus(
    client, chat_id, rohtext
):
    """A set answer length above what the model allows, on the OpenAI wire:
    the refusal is read as one about the answer's ceiling, and the retry
    goes out with the number it names — for DashScope's wordings as for
    OpenAI's."""
    provider = provider_setzen(client, _ZuGrossDannGut(mock_endpunkt("test"), rohtext=rohtext))
    client.app.state.discovery.zustaende["test"].context_tokens = 200_000

    _senden(client, chat_id, max_tokens=8_192)

    assert provider.grenzen == [8_192, 4_096]


@pytest.mark.parametrize("rohtext", STATED_LIMITS)
def test_der_auftrag_geht_nach_der_ablehnung_mit_der_genannten_grenze_hinaus(
    config, client, rohtext
):
    """The same for a job whose agent head sets the answer length."""
    from tests.test_auftraege_api import agent_schreiben, auf_ende_warten

    agent_schreiben(config, kopf="model: test\nmax_tokens: 8192")
    provider = provider_setzen(client, _ZuGrossDannGut(mock_endpunkt("test"), rohtext=rohtext))
    client.app.state.discovery.zustaende["test"].context_tokens = 200_000

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(client, kennung)

    assert daten["state"] == "fertig"
    assert provider.grenzen == [8_192, 4_096]


@pytest.mark.parametrize("rohtext", [DASHSCOPE_BEREICH, DASHSCOPE_AUSGABE])
def test_schweigeprobe_eine_ratengrenze_mit_demselben_wortlaut_bleibt_ein_fehler(rohtext):
    """A 429 is never a full context, whatever its words: it stays the
    ordinary error, and nothing is read out of it."""
    assert kontextvoll.ist_kontext_voll(429, rohtext) is False
    assert kontextvoll.bei_fehler(_ablehnung(rohtext, status=429)) is False


@pytest.mark.parametrize("rohtext", STATED_LIMITS)
def test_jeder_wortlaut_fuellt_die_zahl_des_zugs(rohtext):
    """Whatever wording named the limit, the refused request's own holder
    takes it, and it binds that request's ceiling."""
    zustand = SimpleNamespace(
        endpunkt=mock_endpunkt("test"), gemeldeter_name=None,
        hersteller_max_tokens=None, answer_limit_per_model=None,
    )
    zug = antwortgrenze.Zug()

    antwortgrenze.aus_fehler_lernen(None, zustand, _ablehnung(rohtext), zug)

    assert zug.max_tokens == 4_096
    assert antwortgrenze.geltender_deckel(zustand, None, zug) == 4_096


def test_schweigeprobe_auf_dem_openai_draht_reist_unter_auto_weiter_keine_zahl():
    """The number a refusal named binds the request's ceiling — but Auto on
    the OpenAI wire still sends none at all; the server decides."""
    zustand = SimpleNamespace(
        endpunkt=mock_endpunkt("test"), gemeldeter_name=None,
        hersteller_max_tokens=None, answer_limit_per_model=None,
    )
    zug = antwortgrenze.Zug()
    antwortgrenze.aus_fehler_lernen(None, zustand, _ablehnung(DASHSCOPE_BEREICH), zug)

    assert antwortgrenze.aufloesen(
        None, antwortgrenze.geltender_deckel(zustand, None, zug), 200_000, 1_000,
        anthropic=False,
    ) is None


def test_eine_fremde_anfrage_nimmt_dem_zug_seine_zahl_nicht():
    """Request A is refused with a stated limit; then request B begins at
    the same endpoint — a second chat, a job, a fold. A still reads its
    number for its retry, and B reads the model list alone."""
    zustand = SimpleNamespace(
        endpunkt=mock_endpunkt("test"), gemeldeter_name=None,
        hersteller_max_tokens=32_000, answer_limit_per_model=None,
    )
    a = antwortgrenze.Zug()
    antwortgrenze.aus_fehler_lernen(None, zustand, _ablehnung(OPENAI_ZU_GROSS), a)

    b = antwortgrenze.Zug()
    assert antwortgrenze.geltender_deckel(zustand, None, b) == 32_000
    assert antwortgrenze.geltender_deckel(zustand) == 32_000

    assert antwortgrenze.geltender_deckel(zustand, None, a) == 4_096
    # A's next request has a holder of its own and starts without the number.
    assert antwortgrenze.geltender_deckel(zustand, None, antwortgrenze.Zug()) == 32_000


# --- Anthropic's two "input plus ceiling" refusals ---------------------------

# The canonical wording of Anthropic's error for this case.
ANTHROPIC_AVAILABLE = (
    '{"type":"error","error":{"type":"invalid_request_error","message":'
    '"max_tokens: 32768 > context_window: 200000 - input_tokens: 190000 '
    '= available_tokens: 10000"}}'
)
ANTHROPIC_EXCEED = (
    '{"type":"error","error":{"type":"invalid_request_error","message":'
    '"input length and max_tokens exceed context limit: 188240 + 21333 > 200000, '
    'decrease input length or max_tokens and try again"}}'
)


def _fehler(rohtext: str) -> ProviderFehler:
    return ProviderFehler(
        f"Claude answered with 400: {rohtext}", status=400, rohtext=rohtext
    )


def test_beide_anthropic_formen_werden_erkannt():
    assert kontextvoll.bei_fehler(_fehler(ANTHROPIC_AVAILABLE))
    assert kontextvoll.bei_fehler(_fehler(ANTHROPIC_EXCEED))


def test_beide_anthropic_formen_senken_statt_zu_falten():
    """Both name the ceiling we sent, so lowering it is the fix. The old
    rule — "the ceiling alone has to fill the window" — read them as an
    input problem and folded a history that folding cannot save."""
    assert kontextvoll.abhilfe(_fehler(ANTHROPIC_AVAILABLE)) == (
        kontextvoll.GRENZE, 200_000 - 190_000 - ABSTAND
    )
    assert kontextvoll.abhilfe(_fehler(ANTHROPIC_EXCEED)) == (
        kontextvoll.GRENZE, 200_000 - 188_240 - ABSTAND
    )


def test_die_openai_form_senkt_auf_die_genannte_zahl():
    """This one names the limit itself rather than the window it overran."""
    assert kontextvoll.abhilfe(_fehler(OPENAI_ZU_GROSS)) == (kontextvoll.GRENZE, 4_096)
    assert kontextvoll.hersteller_deckel_aus_fehler(_fehler(OPENAI_ZU_GROSS)) == 4_096


def test_schweigeprobe_ein_fremder_anthropic_400er_wird_nicht_gesenkt():
    fremd = (
        '{"type":"error","error":{"type":"authentication_error",'
        '"message":"invalid x-api-key"}}'
    )
    assert not kontextvoll.ist_kontext_voll(401, fremd)
    assert kontextvoll.hersteller_deckel_aus_fehler(_fehler(fremd)) is None
    assert kontextvoll.abhilfe(_fehler(fremd)) == (kontextvoll.FALTEN, None)


def test_eine_anthropic_ablehnung_ohne_deckel_faltet_weiter():
    """The second silence probe: "prompt is too long" says nothing about the
    ceiling, so it stays a fold."""
    roh = (
        '{"type":"error","error":{"type":"invalid_request_error",'
        '"message":"prompt is too long: 1000500 tokens > 1000000 maximum"}}'
    )
    assert kontextvoll.abhilfe(_fehler(roh)) == (kontextvoll.FALTEN, None)


# --- A number always travels ------------------------------------------------


def test_die_anthropic_anfrage_traegt_immer_max_tokens():
    """Anthropic rejects a request without it, and there is no shipped
    number behind it any more."""
    from app.providers import Generierungsanfrage
    from app.providers.anthropic import AnthropicProvider
    from app.config import EndpointConfig

    endpunkt = EndpointConfig.model_validate({
        "id": "anthropic",
        "provider": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "parameter_dialect": "anthropic",
    })
    koerper = AnthropicProvider(endpunkt)._koerper_bauen(
        Generierungsanfrage(
            nachrichten=[ChatNachricht(role="user", content="Hallo")], max_tokens=7_777
        )
    )
    assert koerper["max_tokens"] == 7_777


def test_die_mlx_anfrage_traegt_immer_max_tokens():
    """Without it an MLX server substitutes a tiny default of its own, and a
    model that thinks spends all of it before the answer begins."""
    from app.providers import Generierungsanfrage
    from app.providers.openai_kompatibel import OpenAIKompatiblerProvider
    from app.config import EndpointConfig

    endpunkt = EndpointConfig.model_validate({
        "id": "omlx",
        "base_url": "http://127.0.0.1:8000/v1",
        "parameter_dialect": "mlx",
    })
    koerper = OpenAIKompatiblerProvider(endpunkt)._koerper_bauen(
        Generierungsanfrage(
            nachrichten=[ChatNachricht(role="user", content="Hallo")], max_tokens=7_777
        )
    )
    assert koerper["max_tokens"] == 7_777


# --- The retired setting ----------------------------------------------------


def test_ein_stehengebliebener_schluessel_wird_ignoriert_und_die_datei_bleibt(tmp_path):
    """A config.yaml written before this setting was retired still starts the
    program, says out loud that the key does nothing, and is not rewritten —
    the file belongs to whoever runs this."""
    import logging

    from app import config as configmodul

    quelle = tmp_path / "config.yaml"
    text = "app:\n  port: 8090\n  default_max_tokens: 8192\n"
    quelle.write_text(text, encoding="utf-8")
    vorher = quelle.read_bytes()

    rohdaten = {"app": {"port": 8090, "default_max_tokens": 8192}}
    log = logging.getLogger("app.config")
    protokoll: list[str] = []
    handler = logging.Handler()
    handler.emit = lambda satz: protokoll.append(satz.getMessage())  # type: ignore[method-assign]
    log.addHandler(handler)
    try:
        # Found while the file is read, said once there is a log to say it in
        # — the configuration is loaded before logging exists (app/main.py).
        configmodul._abgelegte_schluessel_sammeln(rohdaten, quelle)
        configmodul.abgelegte_schluessel_melden()
    finally:
        log.removeHandler(handler)

    assert any("default_max_tokens" in zeile for zeile in protokoll)
    # Said once, not on every later call.
    assert configmodul._ABGELEGTE_GEFUNDEN == []
    assert quelle.read_bytes() == vorher
    # And the schema itself no longer knows it.
    fertig = configmodul.Config.model_validate(rohdaten)
    assert not hasattr(fertig.app, "default_max_tokens")


def test_die_beispielkonfiguration_nennt_den_schluessel_nicht_mehr():
    from pathlib import Path

    wurzel = Path(__file__).resolve().parent.parent
    text = (wurzel / "config.example.yaml").read_text(encoding="utf-8")
    assert "default_max_tokens" not in text


# --- The empty field, at the source -----------------------------------------


def _quelle(pfad: str) -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parent.parent / pfad).read_text(encoding="utf-8")


def test_das_zahlenfeld_kennt_ein_leeres_feld():
    """`null` is a value the field can hold; the word stands in for it, a
    chevron on it starts at the minimum, and a typed zero stays a zero."""
    quelle = _quelle("frontend/src/teile/Zahlenfeld.svelte")
    assert "wert = $bindable(null)" in quelle
    assert "const leer = (w) => w === null || w === undefined || w === ''" in quelle
    assert "Boolean(nullwort) && !fokus && leer(wert)" in quelle
    # Clearing commits the empty value where a word stands for it; without
    # one the old clamp to the minimum stays.
    assert "wert = nullwort ? null : min" in quelle
    # A chevron on an empty field starts at the minimum.
    assert "function stufen(richtung)" in quelle


def test_die_parametertafel_hat_keine_vorgabe_fuer_die_beiden_laengen():
    """An untouched response length and thinking length are "Auto", not a
    resting number."""
    quelle = _quelle("frontend/src/teile/Parametertafel.svelte")
    assert "max_tokens:" not in quelle.split("const VORGABEN = {")[1].split("}")[0]
    assert "reasoning_budget" not in quelle.split("const VORGABEN = {")[1].split("}")[0]
    assert "16384" not in quelle
    assert "4096" not in quelle
    # And the empty field draws the word.
    assert "leer(wert) ? t('parameter.auto')" in quelle


def test_jedes_feld_mit_wort_zeigt_dasselbe_wort():
    """One word for the whole program: every field that can stand empty says
    "Auto", never "default", "off" or "like Steps"."""
    import re
    from pathlib import Path

    wurzel = Path(__file__).resolve().parent.parent / "frontend/src/teile"
    gefunden = 0
    for datei in wurzel.glob("*.svelte"):
        if datei.name == "Zahlenfeld.svelte":
            continue
        for treffer in re.findall(r"nullwort=\{([^}]*)\}", datei.read_text("utf-8")):
            gefunden += 1
            assert treffer.strip() == "t('parameter.auto')", f"{datei.name}: {treffer}"
    # Two of them are the helpers' limits in the settings (app/helper.py);
    # one is the model page's MoE layer count, the same word for the same
    # emptiness (the drawing's slider; 0 would be a count, the empty field
    # says Auto); one is the picture server's thread count, where the
    # generator counts its cores itself; three are the picture studio's
    # guidance, frame count and frame rate, ten are its details (image CFG,
    # detection threshold, highres steps, denoise and target edges, skip
    # layer, preview rhythm, eta, flow shift, CLIP skip).
    assert gefunden == 26


def test_ein_geleertes_feld_verliert_seine_herkunft():
    """Clearing a field removes the value, so the origin beside it has to go
    too. The check drops a null before anything is stored
    (app/parameter.py, ``pruefen``), so the answer comes back without that
    key — an origin left standing claimed a scope for a number that was no
    longer set, and the panel read the empty field's word beside "Model"
    until a reload corrected it."""
    quelle = _quelle("frontend/src/lib/einstellungen.svelte.js")
    assert (
        "if (einstellungen.parameter[name] === undefined) "
        "delete einstellungen.herkunft[name]" in quelle
    )
    # And the "not sent" marking reads that same entry, so one removal
    # answers both.
    tafel = _quelle("frontend/src/teile/Parametertafel.svelte")
    assert "class:zahl-unversendet={!einstellungen.herkunft?.[p.name]}" in tafel
    assert "const woher = einstellungen.herkunft?.[p.name]" in tafel


def test_der_pruefer_speichert_einen_leeren_wert_gar_nicht():
    """The other half of the line above, at the source it depends on: a key
    set to ``None`` never reaches the database, which is why the origin for
    it must be dropped rather than rewritten."""
    from app.parameter import pruefen

    assert pruefen({"temperature": 0.7, "max_tokens": None}) == {"temperature": 0.7}


def test_das_wort_steht_in_beiden_katalogen_gleich():
    wurzel = Path(__file__).resolve().parent.parent
    de = json.loads((wurzel / "app/locales/de.json").read_text(encoding="utf-8"))
    en = json.loads((wurzel / "app/locales/en.json").read_text(encoding="utf-8"))
    assert de["parameter"]["auto"] == "Auto"
    assert en["parameter"]["auto"] == "Auto"


# --- Every round is its own request -----------------------------------------


def test_jede_runde_rechnet_neu():
    """A tool round's calls and results join the history, so the next round
    carries more than the last. Under "Auto" the ceiling IS what is left of
    the window, so one kept from the first round would claim room the input
    has since taken — and a server that adds the two up refuses exactly
    that."""
    erste = [ChatNachricht(role="user", content="x" * 4_000)]
    zweite = erste + [ChatNachricht(role="assistant", content="y" * 40_000)]
    deckel_1 = antwortgrenze.aufloesen(
        None, None, 200_000, antwortgrenze.eingabe_schaetzen(erste), anthropic=True
    )
    deckel_2 = antwortgrenze.aufloesen(
        None, None, 200_000, antwortgrenze.eingabe_schaetzen(zweite), anthropic=True
    )
    assert deckel_2 == deckel_1 - 10_000
    # And their sums stay inside the window, which is the whole point.
    assert antwortgrenze.eingabe_schaetzen(zweite) + deckel_2 < 200_000


def test_die_runde_holt_sich_ihre_grenze_im_quelltext():
    """Pinned at the source, for both paths: the recalculation sits INSIDE
    the round loop, not above it. A live tool round proves the effect;
    this keeps the line from quietly moving back out."""
    chat = _quelle("app/api/v1/generierung.py")
    schleife = chat.split("for runde in range(max_werkzeug_runden + 1):")[1]
    assert "anfrage.max_tokens = antwortgrenze.aufloesen(" in schleife.split("async for")[0]
    # The thinking budget hangs on that number and is resolved with it
    # (app/denkschalter.py `zusatz`, through the round's own `stufe_zusatz`).
    assert "anfrage.zusatz = stufe_zusatz(anfrage.max_tokens)" in schleife.split("async for")[0]

    auftrag = _quelle("app/api/v1/auftraege.py")
    runde = auftrag.split("for runde in range(agent.runden + 1):")[1]
    assert "anfrage.max_tokens = antwortgrenze.aufloesen(" in runde.split("while True:")[0]


# --- Recognition stays narrow -----------------------------------------------


def test_schweigeprobe_supports_at_most_allein_ist_kein_voller_kontext():
    """"supports at most" is ordinary refusal wording — it fences pictures,
    tools and attachments too. Only the whole sentence about completion
    tokens counts, or a chat would fold its history away over an error that
    had nothing to do with its context."""
    fremd = (
        '{"error":{"message":"Invalid request: this model supports at most 8 images '
        'per request.","type":"invalid_request_error"}}'
    )
    assert not kontextvoll.ist_kontext_voll(400, fremd)
    assert not kontextvoll.is_output_cap(400, fremd)
    assert kontextvoll.hersteller_deckel_aus_fehler(_fehler(fremd)) is None
    # The real wording is still recognized — as the answer's length.
    assert kontextvoll.is_output_cap(400, OPENAI_ZU_GROSS)


# --- One holder per answer and per run --------------------------------------


class _RefusedThenTool(MockProvider):
    """Refuses the first answer request with ``rohtext``, answers the one
    sent again with a tool call, then calls a tool ``rounds`` more times and
    ends with text. Records every answer request's ceiling."""

    def __init__(self, *args, rohtext: str = OPENAI_ZU_GROSS, rounds: int = 1, **kwargs):
        super().__init__(*args, **kwargs)
        self.rohtext = rohtext
        self.rounds = rounds
        self.grenzen: list[int | None] = []

    async def streamen(self, anfrage):
        self.grenzen.append(anfrage.max_tokens)
        if len(self.grenzen) == 1:
            raise _ablehnung(self.rohtext)
        if len(self.grenzen) <= 1 + self.rounds:
            nr = len(self.grenzen)
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[Werkzeugaufruf(id=f"t{nr}", name="no_such_tool", argumente={})],
            )
            return
        yield Stueck("content", text="done")


@pytest.mark.parametrize("raw_text", STATED_LIMITS)
def test_the_chat_keeps_the_named_limit_for_every_later_round(client, chat_id, raw_text):
    """A set length of 8192, a refusal naming 4096: the retry AND every tool
    round after it go out with 4096 — not refused once more per round."""
    provider = provider_setzen(
        client, _RefusedThenTool(mock_endpunkt("test"), rohtext=raw_text, rounds=2)
    )
    client.app.state.discovery.zustaende["test"].context_tokens = 200_000

    _senden(client, chat_id, max_tokens=8_192)

    assert provider.grenzen == [8_192, 4_096, 4_096, 4_096]


def test_silent_a_new_answer_starts_without_the_number(client, chat_id):
    """The holder belongs to one answer: the next answer goes out with the
    set length again."""
    provider_setzen(client, _RefusedThenTool(mock_endpunkt("test")))
    client.app.state.discovery.zustaende["test"].context_tokens = 200_000
    _senden(client, chat_id, max_tokens=8_192)

    second = provider_setzen(client, MockProvider(mock_endpunkt("test")))
    _senden(client, chat_id, max_tokens=8_192)

    assert second.letzte_anfrage.max_tokens == 8_192


@pytest.mark.parametrize("raw_text", STATED_LIMITS)
def test_the_job_keeps_the_named_limit_for_every_later_round(config, client, raw_text):
    """The same for a job run: one holder for the run, every round after the
    refusal goes out with the named number."""
    from tests.test_auftraege_api import agent_schreiben, auf_ende_warten

    agent_schreiben(config, kopf="model: test\nmax_tokens: 8192\nmax_rounds: 10")
    provider = provider_setzen(
        client, _RefusedThenTool(mock_endpunkt("test"), rohtext=raw_text, rounds=2)
    )
    state = client.app.state.discovery.zustaende["test"]
    state.context_tokens = 200_000
    state.endpunkt.capabilities.tool_calls = True
    client.app.state.config.features.mcp = True

    job_id = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    data = auf_ende_warten(client, job_id)

    assert data["state"] == "fertig"
    assert provider.grenzen == [8_192, 4_096, 4_096, 4_096]


# Names the INPUT as what did not fit, and states an output limit beside it:
# answered by folding, and the limit is learned all the same.
MIXED = (
    '{"error":{"message":"prompt is too long: 250000 tokens > 200000 maximum. '
    'This model supports at most 4096 completion tokens."}}'
)


def test_the_chat_sends_the_named_limit_after_a_fold(client, chat_id):
    """A refusal that is answered by a fold but names the output limit too:
    the request sent again after the fold carries that limit, not the set
    number it was refused with."""
    from tests.test_kontextvoll import ZuLangDannGut, _chat_mit, _langer_chat

    provider = _chat_mit(client, ZuLangDannGut(mock_endpunkt("test"), zu_lang=1, rohtext=MIXED))
    client.app.state.discovery.zustaende["test"].context_tokens = 200_000
    _langer_chat(client, chat_id)

    _senden(client, chat_id, max_tokens=8_192)

    assert provider.faltungen == 1
    assert provider.grenzen == [8_192, 4_096]


def test_the_job_sends_the_named_limit_after_a_fold(config, client):
    """The same in a job: the round sent again after its fold carries the
    named limit."""
    from tests.test_auftraege_api import agent_schreiben, auf_ende_warten
    from tests.test_kontextvoll import ZuLangImAuftrag

    agent_schreiben(config, kopf="model: test\nmax_rounds: 20\nmax_tokens: 8192")
    from app import fenstergroesse

    provider = provider_setzen(
        client, ZuLangImAuftrag(mock_endpunkt("test"), zu_lang=1, rohtext=MIXED)
    )
    # The small fixed window of the fold tests: the job's short history has
    # a middle to fold there (tests/test_kontextvoll.py, `_auftrag`).
    state = client.app.state.discovery.zustaende["test"]
    state.context_tokens = 2_500
    state.kontext_quelle = fenstergroesse.QUELLE_EINGETRAGEN

    job_id = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Go"}
    ).json()["id"]
    data = auf_ende_warten(client, job_id)

    assert data["state"] == "fertig"
    assert provider.faltungen >= 1
    # Eight build-up rounds, the refused round, the round sent again.
    assert provider.grenzen[8] == 8_192
    assert provider.grenzen[9] == 4_096


def test_the_handoff_is_capped_by_the_named_limit():
    """The handoff of a job takes a setting only as an upper bound: with a
    named limit held, that bound is the limit — with or without a setting.
    Without one held, the setting goes through as it is."""
    zug = antwortgrenze.Zug()
    assert antwortgrenze.capped_setting(8_192, zug) == 8_192
    assert antwortgrenze.capped_setting(None, zug) is None

    zug.lower(4_096)
    assert antwortgrenze.capped_setting(8_192, zug) == 4_096
    assert antwortgrenze.capped_setting(None, zug) == 4_096
    assert antwortgrenze.capped_setting(2_000, zug) == 2_000

    # What one round's input was turned down for is no bound for it.
    other = antwortgrenze.Zug()
    other.lower_round(1_000)
    assert antwortgrenze.capped_setting(8_192, other) == 8_192


def test_the_job_hands_the_capped_setting_to_the_handoff():
    """The job's call of the handoff passes the capped setting (the one
    place the run's holder reaches it)."""
    from pathlib import Path

    source = Path("app/api/v1/auftraege.py").read_text(encoding="utf-8")
    start = source.index("text = await zwischenstand.anfordern(")
    call = source[start:start + 300]
    assert "antwortgrenze.capped_setting(eingestellte_grenze, zug)" in call


def test_the_holder_only_comes_down():
    zug = antwortgrenze.Zug()
    assert zug.lower(4_096) is True
    assert zug.lower(8_192) is False
    assert zug.max_tokens == 4_096
    zug.lower_round(6_000)
    assert zug.held() == 4_096
    zug.lower_round(1_000)
    assert zug.held() == 1_000
    zug.round_begins()
    assert zug.held() == 4_096
    assert antwortgrenze.forced_ceiling(8_192, zug) == 4_096
    assert antwortgrenze.forced_ceiling(None, zug) == 4_096
    assert antwortgrenze.forced_ceiling(2_000, zug) is None
    assert antwortgrenze.forced_ceiling(8_192, antwortgrenze.Zug()) is None


# --- The answer's length is its own signal -----------------------------------


@pytest.mark.parametrize("raw_text", STATED_LIMITS)
def test_a_stated_output_limit_is_not_a_full_context(raw_text):
    """Two signals, kept apart: a stated output limit says the answer's
    length is the problem, not the context."""
    assert kontextvoll.is_output_cap(400, raw_text)
    assert kontextvoll.output_cap_error(_ablehnung(raw_text))
    assert not kontextvoll.ist_kontext_voll(400, raw_text)
    assert not kontextvoll.bei_fehler(_ablehnung(raw_text))


def test_silent_a_refusal_naming_the_input_stays_a_full_context():
    """A limit quoted beside an input that did not fit is a full context:
    folding cures it."""
    assert kontextvoll.ist_kontext_voll(400, MIXED)
    assert not kontextvoll.is_output_cap(400, MIXED)
    assert not kontextvoll.is_output_cap(429, DASHSCOPE_BEREICH)


class _AlwaysTooLong(MockProvider):
    """Refuses every answer request with ``rohtext``."""

    def __init__(self, *args, rohtext: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.rohtext = rohtext
        self.grenzen: list[int | None] = []

    async def streamen(self, anfrage):
        self.grenzen.append(anfrage.max_tokens)
        raise _ablehnung(self.rohtext)
        yield  # pragma: no cover - makes this a generator


@pytest.mark.parametrize("raw_text", [DASHSCOPE_BEREICH, DASHSCOPE_AUSGABE])
def test_an_unresolved_output_limit_ends_the_chat_as_too_long_an_answer(
    client, chat_id, raw_text
):
    """The attempts are used up and the refusal still stands: the answer
    ends saying the answer's length was too large — not that the context is
    full."""
    provider_setzen(client, _AlwaysTooLong(mock_endpunkt("test"), rohtext=raw_text))
    client.app.state.discovery.zustaende["test"].context_tokens = 200_000

    _senden(client, chat_id, max_tokens=8_192)

    stats = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"][-1]["stats"]
    assert stats.get("antwortlaenge_zu_gross") is True
    assert not stats.get("kontextfenster_voll")


def test_silent_an_unresolved_full_context_still_ends_as_one(client, chat_id):
    """A refusal about the context keeps its own ending."""
    from tests.test_kontextvoll import LLAMA

    provider_setzen(client, _AlwaysTooLong(mock_endpunkt("test"), rohtext=LLAMA))
    client.app.state.discovery.zustaende["test"].context_tokens = 200_000

    _senden(client, chat_id, max_tokens=8_192)

    stats = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"][-1]["stats"]
    assert stats.get("kontextfenster_voll") is True
    assert not stats.get("antwortlaenge_zu_gross")


def test_under_auto_an_output_limit_keeps_the_ending_a_chat_always_had(client, chat_id):
    """No length is set, so there is no number for the user to lower: the
    answer does not end as too long an answer, but as before."""
    provider_setzen(
        client, _AlwaysTooLong(mock_endpunkt("test"), rohtext=DASHSCOPE_AUSGABE)
    )
    client.app.state.discovery.zustaende["test"].context_tokens = 200_000

    _senden(client, chat_id)

    stats = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"][-1]["stats"]
    assert not stats.get("antwortlaenge_zu_gross")
    assert stats.get("kontextfenster_voll") is True


def test_under_auto_an_output_limit_keeps_the_ending_a_job_always_had(config, client):
    from tests.test_auftraege_api import agent_schreiben, auf_ende_warten

    agent_schreiben(config, kopf="model: test")
    provider_setzen(
        client, _AlwaysTooLong(mock_endpunkt("test"), rohtext=DASHSCOPE_AUSGABE)
    )
    client.app.state.discovery.zustaende["test"].context_tokens = 200_000

    job_id = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Go"}
    ).json()["id"]
    data = auf_ende_warten(client, job_id)

    assert data["end_reason"] == "kontext_voll"


@pytest.mark.parametrize("raw_text", [DASHSCOPE_BEREICH, DASHSCOPE_AUSGABE])
def test_an_unresolved_output_limit_ends_the_job_as_too_long_an_answer(
    config, client, raw_text
):
    from tests.test_auftraege_api import agent_schreiben, auf_ende_warten

    agent_schreiben(config, kopf="model: test\nmax_tokens: 8192")
    provider_setzen(client, _AlwaysTooLong(mock_endpunkt("test"), rohtext=raw_text))
    client.app.state.discovery.zustaende["test"].context_tokens = 200_000

    job_id = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    data = auf_ende_warten(client, job_id)

    assert data["end_reason"] == "antwortlaenge_zu_gross"


# --- A fold makes the round's ceiling stale --------------------------------


def _ceiling_named(window: int, input_tokens: int) -> str:
    """A refusal that quotes the ceiling sent beside the window and the
    input: answered with a lowered ceiling for this round."""
    return (
        '{"type":"error","error":{"type":"invalid_request_error","message":'
        f'"input length and max_tokens exceed context limit: {input_tokens} + 8192 > {window}"}}}}'
    )


def test_the_chat_works_the_round_ceiling_out_again_after_a_fold(client, chat_id):
    """First refused for the ceiling (lowered for this round), then for the
    input (folded): the request after the fold no longer sends the input
    the lowered ceiling was worked out for. The room grew by what the fold
    freed — here more than the set length — so it goes out with the set
    length again instead of the stale number."""
    from tests.test_kontextvoll import LLAMA, ZuLangDannGut, _chat_mit, _langer_chat

    provider = _chat_mit(
        client,
        ZuLangDannGut(
            mock_endpunkt("test"), zu_lang=2, rohtext=[_ceiling_named(200_000, 195_000), LLAMA]
        ),
    )
    client.app.state.discovery.zustaende["test"].context_tokens = 200_000
    _langer_chat(client, chat_id)

    _senden(client, chat_id, max_tokens=8_192)

    assert provider.faltungen == 1
    assert provider.grenzen == [8_192, 200_000 - 195_000 - 64, 8_192]


def test_the_job_works_the_round_ceiling_out_again_after_a_fold(config, client):
    from app import fenstergroesse
    from tests.test_auftraege_api import agent_schreiben, auf_ende_warten
    from tests.test_kontextvoll import LLAMA, ZuLangImAuftrag

    agent_schreiben(config, kopf="model: test\nmax_rounds: 20\nmax_tokens: 8192")
    provider = provider_setzen(
        client,
        ZuLangImAuftrag(
            mock_endpunkt("test"), zu_lang=2, rohtext=[_ceiling_named(2_500, 1_500), LLAMA]
        ),
    )
    state = client.app.state.discovery.zustaende["test"]
    state.context_tokens = 2_500
    state.kontext_quelle = fenstergroesse.QUELLE_EINGETRAGEN

    job_id = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Go"}
    ).json()["id"]
    data = auf_ende_warten(client, job_id)

    assert data["state"] == "fertig"
    assert provider.faltungen >= 1
    # Eight build-up rounds, the round refused for its ceiling, the same
    # round refused for its input, the round sent again after the fold —
    # with the room the fold freed added, not the stale number.
    assert provider.grenzen[8:10] == [8_192, 2_500 - 1_500 - 64]
    assert provider.grenzen[10] > 2_500 - 1_500 - 64


def test_a_fold_grows_the_round_ceiling_by_what_it_freed():
    zug = antwortgrenze.Zug()
    zug.input_folded(500)
    assert zug.round_tokens is None  # nothing lowered, nothing to grow
    zug.lower_round(900)
    zug.input_folded(500)
    assert zug.round_tokens == 1_400
    zug.input_folded(-10)
    assert zug.round_tokens == 1_400
