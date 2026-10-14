"""Asking for a fold's summary once, under two clocks
(app/faltversuche.py)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from app import faltversuche
from app.providers import Stueck


@dataclass
class _Zustand:
    provider: object


class _Folge:
    """Answers each request with the next entry of its list: text, ``""``
    for an empty answer, ``"cut"`` for one cut off at the ceiling, ``None``
    for a request that breaks, ``"gedacht"`` for a summary that came only
    as thinking with a natural ending, ``"beides"`` for thinking beside a
    written answer, ``"gedacht-cut"`` for thinking cut off at the ceiling.
    The last entry repeats."""

    def __init__(self, antworten):
        self.antworten = list(antworten)
        self.anfragen = 0

    async def streamen(self, anfrage):
        self.anfragen += 1
        antwort = self.antworten[min(self.anfragen, len(self.antworten)) - 1]
        if antwort is None:
            raise RuntimeError("provider is down")
        if antwort == "cut":
            yield Stueck("content", text="half of")
            yield Stueck("stats", daten={"abgeschnitten": True})
            return
        if antwort == "gedacht":
            yield Stueck("reasoning", text="Gedachte Zusammenfassung")
            yield Stueck("stats", daten={"ende_grund": "stop"})
            return
        if antwort == "beides":
            yield Stueck("reasoning", text="Nur gedacht")
            yield Stueck("content", text="geschrieben")
            yield Stueck("stats", daten={"ende_grund": "stop"})
            return
        if antwort == "gedacht-cut":
            yield Stueck("reasoning", text="halb gedacht")
            yield Stueck("stats", daten={"abgeschnitten": True, "ende_grund": "length"})
            return
        if antwort:
            yield Stueck("content", text=antwort)


async def test_eine_zusammenfassung_ist_eine_anfrage():
    """Silence test: a summary that comes back is one request, returned as
    it came."""
    provider = _Folge(["summary"])
    assert await faltversuche.anfordern(_Zustand(provider), object()) == "summary"
    assert provider.anfragen == 1


async def test_eine_ausnahme_wird_nicht_wiederholt():
    """A request that breaks is not sent again, even where the next one
    would have worked: the pause between two turns is the retry."""
    provider = _Folge([None, "summary"])
    with pytest.raises(RuntimeError):
        await faltversuche.anfordern(_Zustand(provider), object())
    assert provider.anfragen == 1


async def test_eine_abgeschnittene_antwort_wird_nicht_wiederholt():
    provider = _Folge(["cut", "summary"])
    assert await faltversuche.anfordern(_Zustand(provider), object()) is None
    assert provider.anfragen == 1


async def test_eine_leere_antwort_wird_nicht_wiederholt():
    provider = _Folge(["", "summary"])
    assert await faltversuche.anfordern(_Zustand(provider), object()) == ""
    assert provider.anfragen == 1


async def test_eine_gedachte_zusammenfassung_ist_eine():
    """A summary the model thought instead of writing is a summary — the
    same swap chat and job make (app/reasoning.denktext_als_antwort)."""
    provider = _Folge(["gedacht"])
    assert await faltversuche.anfordern(_Zustand(provider), object()) == (
        "Gedachte Zusammenfassung"
    )
    assert provider.anfragen == 1


async def test_geschriebener_text_schlaegt_den_denktext():
    """Silence test: thinking beside a written summary changes nothing."""
    provider = _Folge(["beides"])
    assert await faltversuche.anfordern(_Zustand(provider), object()) == "geschrieben"


async def test_gedachter_text_an_der_grenze_bleibt_none():
    """A cut answer is no summary, however it was thought."""
    provider = _Folge(["gedacht-cut"])
    assert await faltversuche.anfordern(_Zustand(provider), object()) is None


class _Schweiger:
    """Sends nothing at all — a server that hangs — until it is cancelled;
    after ``stumm`` requests it answers."""

    def __init__(self, stumm: int):
        self.stumm = stumm
        self.anfragen = 0

    async def streamen(self, anfrage):
        self.anfragen += 1
        if self.anfragen <= self.stumm:
            await asyncio.sleep(3600)
        yield Stueck("content", text="summary")


async def test_ein_schweigender_server_endet_nach_der_stille_als_stille(monkeypatch):
    """A request that receives nothing for ``STILLE_SEKUNDEN`` is abandoned
    as a failure — and not asked again."""
    monkeypatch.setattr(faltversuche, "STILLE_SEKUNDEN", 0.01)
    provider = _Schweiger(stumm=1)
    with pytest.raises(faltversuche.Stille):
        await faltversuche.anfordern(_Zustand(provider), object())
    assert provider.anfragen == 1


async def test_the_total_clock_is_not_reported_as_silence(monkeypatch):
    """A server that keeps delivering is not a silent one. The message says
    which of the two clocks ended the request — read as silence, it sends
    whoever looks into the protocol after a hung server that was answering."""
    monkeypatch.setattr(faltversuche, "GESAMT_SEKUNDEN", 0.15)

    class _Tropfen:
        async def streamen(self, anfrage):
            while True:
                await asyncio.sleep(0.005)
                yield Stueck("content", text=".")

    with pytest.raises(faltversuche.Stille) as fehler:
        await faltversuche.anfordern(_Zustand(_Tropfen()), object())
    assert "timed out" in str(fehler.value)


async def test_the_silence_clock_keeps_its_own_words(monkeypatch):
    """The other half of the same distinction: a server that goes quiet is
    reported as silence, with the silence limit — not as a request that ran
    out of time. Without this line, a change that named the wrong clock for
    every ending would go through unnoticed: this is the sentence the job
    exists for."""
    monkeypatch.setattr(faltversuche, "STILLE_SEKUNDEN", 0.01)
    monkeypatch.setattr(faltversuche, "GESAMT_SEKUNDEN", 5.0)

    class _Stumm:
        async def streamen(self, anfrage):
            await asyncio.sleep(60)
            yield Stueck("content", text="never")

    with pytest.raises(faltversuche.Stille) as fehler:
        await faltversuche.anfordern(_Zustand(_Stumm()), object())
    assert "No response from the server for" in str(fehler.value)


def test_the_clocks_keep_their_values():
    assert faltversuche.STILLE_SEKUNDEN == 120.0
    assert faltversuche.GESAMT_SEKUNDEN == 600.0


class _Uhr:
    def __init__(self):
        self.jetzt = 0.0

    def __call__(self) -> float:
        return self.jetzt


async def test_die_gesamtzeit_beendet_auch_einen_strom_der_nie_schweigt(monkeypatch):
    """The 600 seconds cover the whole request: a server that keeps sending
    a little, never silent for long, still ends there."""
    uhr = _Uhr()
    monkeypatch.setattr(faltversuche, "uhr", uhr)

    class _Tropfen:
        anfragen = 0
        stuecke = 0

        async def streamen(self, anfrage):
            _Tropfen.anfragen += 1
            while True:
                # Every piece arrives well inside the silence window, and
                # each one costs a minute of the whole.
                uhr.jetzt += 60.0
                _Tropfen.stuecke += 1
                yield Stueck("content", text=".")

    with pytest.raises(faltversuche.Stille):
        await faltversuche.anfordern(_Zustand(_Tropfen()), object())
    assert _Tropfen.anfragen == 1
    assert _Tropfen.stuecke == int(faltversuche.GESAMT_SEKUNDEN // 60)
