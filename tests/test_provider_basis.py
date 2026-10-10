"""The provider base class's own defaults — what every provider inherits
unless it overrides it."""

from __future__ import annotations

import pytest

from app.providers import MockProvider, mock_endpunkt
from app.providers.base import KontextDrossel, kontext_stueck


@pytest.mark.asyncio
async def test_konfigurierte_kontextgroesse_wird_uebernommen():
    provider = MockProvider(mock_endpunkt("test", context_tokens=8192))
    assert await provider.kontextgroesse() == 8192


@pytest.mark.asyncio
async def test_null_gilt_als_nicht_konfiguriert():
    """Nobody means a context of zero — the same reading the
    openai_kompatibel and anthropic overrides already give it."""
    provider = MockProvider(mock_endpunkt("test", context_tokens=0))
    assert await provider.kontextgroesse() is None


@pytest.mark.asyncio
async def test_ohne_konfiguration_gibt_es_nichts():
    provider = MockProvider(mock_endpunkt("test"))
    assert await provider.kontextgroesse() is None


# --- The context throttle -------------------------------------------------
#
# How often a running answer may say how full the context is. The clock is
# handed in, so none of this waits for anything.


def test_die_erste_meldung_geht_sofort_raus():
    """The same rule the tool throttle keeps for a call's name: the first
    thing that is known is the most valuable thing there is."""
    assert KontextDrossel(0.5).faellig(1500, 0, 100.0) is True


def test_derselbe_stand_meldet_sich_nicht_noch_einmal():
    """Time alone is not a reason to send. Nothing changed, nothing to say."""
    drossel = KontextDrossel(0.5)
    drossel.faellig(1500, 3, 100.0)
    assert drossel.faellig(1500, 3, 200.0) is False


def test_innerhalb_des_mindestabstands_bleibt_es_still():
    drossel = KontextDrossel(0.5)
    drossel.faellig(1500, 3, 100.0)
    assert drossel.faellig(1500, 4, 100.3) is False
    assert drossel.faellig(1500, 5, 100.6) is True


def test_der_abstand_zaehlt_ab_der_letzten_meldung():
    """A reading that was held back must not move the clock — otherwise a
    stream arriving faster than the interval would push the next report
    away over and over and the bar would never move at all."""
    drossel = KontextDrossel(0.5)
    drossel.faellig(1500, 1, 100.0)
    for i in range(2, 10):
        drossel.faellig(1500, i, 100.0 + i * 0.05)
    assert drossel.faellig(1500, 20, 100.55) is True


def test_ein_erstmals_bekannter_prompt_darf_vordraengeln():
    """The prompt is by far the larger half of the sum and it lands once. A
    bar that waits its turn for it says nothing while it waits."""
    drossel = KontextDrossel(0.5)
    drossel.faellig(None, 1, 100.0)
    assert drossel.faellig(1500, 2, 100.01) is True


def test_ein_wackelnder_prompt_draengelt_nicht():
    """mlx repeats its timings block on every single chunk. A number that
    moves there must not buy itself an event each time it does."""
    drossel = KontextDrossel(0.5)
    drossel.faellig(1500, 1, 100.0)
    assert drossel.faellig(1490, 2, 100.01) is False
    assert drossel.faellig(1502, 3, 100.6) is True


def test_das_stueck_traegt_die_drei_zusagen():
    """The shape lives in one place so the three providers cannot drift."""
    stueck = kontext_stueck(1500, False, 42)
    assert stueck.sorte == "kontext"
    assert stueck.daten == {
        "prompt_tokens": 1500,
        "prompt_genau": False,
        "erzeugte_tokens": 42,
    }


def test_ein_unbekannter_prompt_bleibt_unbekannt():
    """None, not zero: a zero would be a claim, and this is the absence of
    one."""
    assert kontext_stueck(None, False, 7).daten["prompt_tokens"] is None
