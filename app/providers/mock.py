"""Dummy for tests.

Behaves like a real provider but needs no running model server. This lets
the integration tests of the whole chain (request → proxy → answer →
database) run on any machine, including CI.
"""

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

from app.config import Capabilities, EndpointConfig
from app.providers.base import (
    Generierungsanfrage,
    KontextDrossel,
    Provider,
    ProviderFehler,
    Stueck,
    Werkzeugaufruf,
    kontext_stueck,
)
from app.reasoning import ReasoningParser


def mock_endpunkt(
    kennung: str = "mock",
    reasoning_format: str = "none",
    **felder,
) -> EndpointConfig:
    return EndpointConfig.model_validate(
        {
            "id": kennung,
            "name": f"Attrappe ({kennung})",
            "provider": "mock",
            "base_url": "http://mock.invalid/v1",
            "reasoning_format": reasoning_format,
            "capabilities": Capabilities(streaming=True, tool_calls=True).model_dump(),
            **felder,
        }
    )


class MockProvider(Provider):
    """Emits predefined chunks, with configurable behavior."""

    def __init__(
        self,
        endpunkt: EndpointConfig | None = None,
        *,
        haeppchen: list[str] | None = None,
        ist_erreichbar: bool = True,
        verzoegerung: float = 0.0,
        fehler: str | None = None,
        werkzeugaufrufe: list[Werkzeugaufruf] | None = None,
        modelle: list[str] | None = None,
        kontext_melden: bool = False,
        kontext_prompt: int | None = None,
        kontext_genau: bool = True,
        tor: "asyncio.Event | None" = None,
    ) -> None:
        super().__init__(endpunkt or mock_endpunkt())
        self.haeppchen = haeppchen if haeppchen is not None else ["Hallo ", "Welt"]
        self.ist_erreichbar = ist_erreichbar
        self.verzoegerung = verzoegerung
        self.fehler = fehler
        # Tool calls for the first pass. After that the dummy answers with
        # text — otherwise the loop would never end.
        self.werkzeugaufrufe = werkzeugaufrufe or []
        # The catalogue this dummy claims to offer. Empty means: one address,
        # one model — the way a local server behaves.
        self.modelle = modelle or []
        # Whether this dummy reports how full the context is while it writes.
        # Off unless a test asks for it: the end-to-end tests read the event
        # stream position by position, and a dummy that quietly slid a new
        # kind of event in between would move every one of those readings.
        #
        # `kontext_prompt` is what it claims to know about the round's
        # prompt — `None` stands for a provider that cannot count it at all
        # (a cloud server mid-stream), which is the case where the caller
        # has to estimate. `kontext_genau` says whether the number is a
        # complete count or merely a floor.
        # A gate a test can hold: the stream stops in front of its LAST
        # chunk until the gate is set. Determinism instead of sleeps — a
        # test that needs "the model is still writing" holds the gate,
        # asserts, and lets go, however loaded the machine is.
        self.tor = tor
        self.kontext_melden = kontext_melden
        self.kontext_prompt = kontext_prompt
        self.kontext_genau = kontext_genau
        # Inspectable by tests: was the stream closed prematurely?
        self.abgebrochen = False
        self.ausgegebene_haeppchen = 0
        self.durchlaeufe = 0
        self.letzte_anfrage: Generierungsanfrage | None = None
        self.alle_anfragen: list[Generierungsanfrage] = []

    async def erreichbar(self, timeout: float = 3.0) -> bool:
        return self.ist_erreichbar

    async def modelle_auflisten(self, timeout: float = 3.0) -> list[str]:
        return list(self.modelle)

    async def streamen(self, anfrage: Generierungsanfrage) -> AsyncIterator[Stueck]:
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        self.durchlaeufe += 1
        if self.fehler:
            raise ProviderFehler(self.fehler)

        # Request tools on the first pass, answer normally afterwards.
        if self.werkzeugaufrufe and self.durchlaeufe == 1:
            yield Stueck("tool_call", werkzeugaufrufe=list(self.werkzeugaufrufe))
            return

        parser = ReasoningParser(self.endpunkt.reasoning_format)
        # The real throttle, not a stand-in: a test that drives this dummy
        # is then measuring the same gate the real providers pass through.
        kontextdrossel = KontextDrossel()
        try:
            for nummer, haeppchen in enumerate(self.haeppchen):
                if self.tor is not None and nummer == len(self.haeppchen) - 1:
                    await self.tor.wait()
                if self.verzoegerung:
                    await asyncio.sleep(self.verzoegerung)
                self.ausgegebene_haeppchen += 1
                for sorte, text in parser.feed(haeppchen):
                    yield Stueck(sorte, text)
                if self.kontext_melden and kontextdrossel.faellig(
                    self.kontext_prompt, self.ausgegebene_haeppchen, time.monotonic()
                ):
                    yield kontext_stueck(
                        self.kontext_prompt,
                        self.kontext_genau,
                        self.ausgegebene_haeppchen,
                    )
            for sorte, text in parser.finish():
                yield Stueck(sorte, text)
            yield Stueck(
                "stats",
                daten={
                    "dauer_sekunden": 0.0,
                    "haeppchen": self.ausgegebene_haeppchen,
                    "endpunkt": self.id,
                },
            )
        except (GeneratorExit, asyncio.CancelledError):
            # The consumer closed the stream (a real chunk had already
            # arrived, so the loop noticed the stop and closed it cleanly),
            # cancelled its wait for the next one while this was still
            # asleep producing it (Generierung.naechstes_stueck, the case a
            # keepalive-only stream needs), or a fold's own silence timeout
            # gave up on it (app/faltversuche.py) — every one of these
            # counts as the stream closing prematurely from here.
            self.abgebrochen = True
            raise
