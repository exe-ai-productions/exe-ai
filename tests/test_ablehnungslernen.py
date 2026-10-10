"""One call for "was the window full", and both halves learning from it.

Three calls used to stand side by side at four places. What is checked here
is that the one call does all three, that a route reaches it on the chat
path and on the job path alike, and that neither route calls a learner on
its own any more — which is what makes a fifth call site get all of it
without anybody remembering to add it.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from app import ablehnungslernen, antwortgrenze, fenstergroesse
from app.db import Database, repositories_erstellen
from app.providers import MockProvider, ProviderFehler, mock_endpunkt
from tests.conftest import provider_setzen

# llama.cpp, naming the window and nothing about an output limit.
FENSTER = "request (755 tokens) exceeds the available context size (4096 tokens), try increasing it"
# OpenAI, naming the model's own output limit and nothing about the window.
DECKEL = (
    '{"error":{"message":"max_tokens is too large: 86000. This model supports at '
    'most 4096 completion tokens, whereas you provided 86000."}}'
)
FREMD = '{"error":{"message":"invalid_api_key"}}'


def _fehler(rohtext: str) -> ProviderFehler:
    return ProviderFehler(
        f"provider answered with 400: {rohtext}", status=400, rohtext=rohtext
    )


class _Endpunkt:
    def __init__(self, id: str):
        self.id = id
        self.modell = None
        self.context_tokens = None


class _Zustand:
    """A stand-in for discovery.EndpunktZustand — only the fields the two
    learners read and write."""

    def __init__(self):
        self.endpunkt = _Endpunkt("omlx")
        self.gemeldeter_name = "ornith"
        self.kontext_quelle = fenstergroesse.QUELLE_ERSATZ
        self.context_tokens = None
        self.hersteller_max_tokens = None


def _repos(tmp_path):
    db = Database(tmp_path / "d.db")
    db.schema_einrichten()
    return repositories_erstellen(db)


# --- The one call ----------------------------------------------------------


def test_die_fenstergroesse_wird_gelernt(tmp_path):
    repos, zustand = _repos(tmp_path), _Zustand()

    assert ablehnungslernen.fenster_voll(repos, zustand, _fehler(FENSTER)) is True

    assert zustand.context_tokens == 4_096
    assert zustand.kontext_quelle == fenstergroesse.QUELLE_GELERNT
    assert fenstergroesse.gelernt_holen(repos, "omlx", "ornith") == 4_096


def test_die_antwortgrenze_wird_aus_derselben_ablehnung_gelernt(tmp_path):
    """The half that was once missing at one of the four call sites."""
    repos, zustand = _repos(tmp_path), _Zustand()
    zug = antwortgrenze.Zug()

    assert ablehnungslernen.fenster_voll(repos, zustand, _fehler(DECKEL), zug) is True

    # The number of THIS request, in its own holder — not on the endpoint
    # state, and the field the model list writes stays empty.
    assert zug.max_tokens == 4_096
    assert not hasattr(zustand, "zug_max_tokens")
    assert zustand.hersteller_max_tokens is None
    # And nowhere else: this number holds for the request, it is not stored.
    assert repos.einstellungen.holen("gelernte_antwortgrenzen", "omlx:ornith") is None


def test_schweigeprobe_ein_fremder_400er_lernt_nichts(tmp_path):
    """Not a full window, so nothing is written down and the caller is told
    to treat the error as the ordinary one it is."""
    repos, zustand = _repos(tmp_path), _Zustand()

    assert ablehnungslernen.fenster_voll(repos, zustand, _fehler(FREMD)) is False

    assert zustand.context_tokens is None
    assert zustand.hersteller_max_tokens is None
    assert fenstergroesse.gelernt_holen(repos, "omlx", "ornith") is None


def _aufrufe(quelle: str) -> set[str]:
    """Every ``modul.funktion(...)`` really called in this source — read off
    the syntax tree, so a mention in a comment or a docstring, which is how
    this repository documents where a thing lives, is not mistaken for one."""
    namen = set()
    for knoten in ast.walk(ast.parse(quelle)):
        if isinstance(knoten, ast.Call) and isinstance(knoten.func, ast.Attribute):
            ziel = knoten.func.value
            if isinstance(ziel, ast.Name):
                namen.add(f"{ziel.id}.{knoten.func.attr}")
    return namen


def test_keine_route_lernt_noch_von_hand():
    """What a fifth call site gets for free: the two routes ask this module
    and nothing else, so a new place cannot be left with one learner of the
    two — which is exactly what happened once and had to be found by hand."""
    wurzel = Path(inspect.getfile(ablehnungslernen)).parent / "api" / "v1"
    for name in ("generierung.py", "auftraege.py"):
        gerufen = _aufrufe((wurzel / name).read_text())
        for aufruf in (
            "fenstergroesse.aus_fehler_lernen",
            "antwortgrenze.aus_fehler_lernen",
            "kontextvoll.bei_fehler",
        ):
            assert aufruf not in gerufen, f"{name}: {aufruf}"


# --- Both routes -----------------------------------------------------------


class _ZuLangDannGut(MockProvider):
    """Refuses the first round as too long, then answers."""

    def __init__(self, *args, rohtext: str = FENSTER, **kwargs):
        super().__init__(*args, **kwargs)
        self.rohtext = rohtext
        self.runden = 0

    async def streamen(self, anfrage):
        self.runden += 1
        if self.runden == 1:
            raise _fehler(self.rohtext)
        async for stueck in super().streamen(anfrage):
            yield stueck


def test_chat_lernt_beim_vollen_fenster(client, chat_id):
    provider_setzen(client, _ZuLangDannGut(mock_endpunkt("test")))
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.context_tokens = 200_000
    zustand.kontext_quelle = fenstergroesse.QUELLE_ERSATZ

    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Frage"},
    )
    assert antwort.status_code == 200
    antwort.text  # drain the stream so the run finishes

    assert zustand.context_tokens == 4_096
    assert zustand.kontext_quelle == fenstergroesse.QUELLE_GELERNT


def test_auftrag_lernt_beim_vollen_fenster(config, client):
    from tests.test_auftraege_api import agent_schreiben, auf_ende_warten

    agent_schreiben(config)
    provider_setzen(client, _ZuLangDannGut(mock_endpunkt("test")))
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.context_tokens = 200_000
    zustand.kontext_quelle = fenstergroesse.QUELLE_ERSATZ

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    auf_ende_warten(client, kennung)

    assert zustand.context_tokens == 4_096
    assert zustand.kontext_quelle == fenstergroesse.QUELLE_GELERNT
