"""The reason shown beside a permission stands in the language of the page.

The page sends its language with every request that starts or reattaches to
a run (``X-Ui-Language``); the run keeps it, so a reason spoken at the
window — the one sentence a person reads before saying yes — is in that
language and not in the configured one.
"""

from __future__ import annotations

import asyncio
import json

from app import berechtigungswahl
from app.i18n import t
from app.providers import MockProvider, mock_endpunkt
from app.providers.base import Werkzeugaufruf
from app.tools import shell
from app.tools.registry import WerkzeugRegistry
from tests.conftest import provider_setzen


class _AntwortetSelbst(WerkzeugRegistry):
    """A registry whose confirmation is answered with a yes as soon as the
    run is waiting for it — the test cannot click while it reads the stream."""

    def __init__(self, *args, verwaltung, **kwargs):
        super().__init__(*args, **kwargs)
        self._verwaltung = verwaltung

    def braucht_bestaetigung(self, name, argumente=None, ordner=None):
        antwort = super().braucht_bestaetigung(name, argumente, ordner)
        if antwort:
            schleife = asyncio.get_running_loop()

            def takt():
                for lauf in self._verwaltung.laufende():
                    for aufruf_id in list(lauf.bestaetigungen):
                        if self._verwaltung.bestaetigen(lauf.id, aufruf_id, True):
                            return
                schleife.call_later(0.01, takt)

            schleife.call_later(0.01, takt)
        return antwort


def _ereignisse(text: str) -> list[dict]:
    return [
        json.loads(zeile.removeprefix("data: "))
        for zeile in text.splitlines()
        if zeile.startswith("data: {")
    ]


def _frage_stellen(client, config, tmp_path, chat_id, sprache_kopf):
    config.app.language = "de"
    regeln = tmp_path / "berechtigungen.json"
    berechtigungswahl.anwenden(regeln, "chat", "manuell")
    client.app.state.config.features.mcp = True
    client.app.state.werkzeuge = _AntwortetSelbst(
        [], shell_an=True, berechtigungen_pfad=regeln,
        verwaltung=client.app.state.generierungen,
    )
    client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
    provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"), haeppchen=["done"],
            werkzeugaufrufe=[Werkzeugaufruf(
                id="a1", name="run_command", argumente={"command": "cat /etc/hosts"},
            )],
        ),
    )
    kopf = {"X-Ui-Language": sprache_kopf} if sprache_kopf else {}
    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "go"},
        headers=kopf,
    )
    assert antwort.status_code == 200, antwort.text
    ereignisse = _ereignisse(antwort.text)
    (frage,) = [e for e in ereignisse if e["typ"] == "tool_confirm"]
    (start,) = [e for e in ereignisse if e["typ"] == "start"]
    return {**frage, "generation_id": start["generation_id"]}


def test_der_grund_steht_in_der_sprache_der_oberflaeche(client, config, tmp_path, chat_id):
    frage = _frage_stellen(client, config, tmp_path, chat_id, "en")

    pfad = frage["grund_wert"]
    assert pfad
    assert frage["grund"] == t(shell.GRUND_SCHLUESSEL, "en", pfad=pfad)
    assert frage["grund"] != t(shell.GRUND_SCHLUESSEL, "de", pfad=pfad)


def test_ohne_sprachkopf_gilt_die_eingestellte_sprache(client, config, tmp_path, chat_id):
    """The silence test: a request that names no language gets the
    configured one — here German."""
    frage = _frage_stellen(client, config, tmp_path, chat_id, None)

    assert frage["grund"] == t(shell.GRUND_SCHLUESSEL, "de", pfad=frage["grund_wert"])


def test_der_grund_bleibt_in_der_gestarteten_sprache_beim_nachholen(
    client, config, tmp_path, chat_id
):
    """A reattach replays the run's own lines: the reason in the history is
    the one the run spoke when it began, whatever the reattaching request says."""
    frage = _frage_stellen(client, config, tmp_path, chat_id, "en")

    nachgeholt = client.get(
        f"/api/v1/chat/stream/{frage['generation_id']}", headers={"X-Ui-Language": "de"}
    )

    assert nachgeholt.status_code == 200
    (wieder,) = [e for e in _ereignisse(nachgeholt.text) if e["typ"] == "tool_confirm"]
    assert wieder["grund"] == frage["grund"]
