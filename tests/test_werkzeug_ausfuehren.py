"""``_werkzeug_ausfuehren``'s own contract for the loop guard
(app/schleifenwaechter.py): only a Tor 3 refusal reports as a rejection — a
tool that ran and genuinely failed is a different problem with a different
shape, and mixing the two into the guard's count would end a run that was
still making real progress elsewhere.
"""

from __future__ import annotations

import re

import pytest

from app.api.v1.generierung import _werkzeug_ausfuehren
from app.providers.base import Werkzeugaufruf
from app.tools import WerkzeugVerboten, uhr, ziel_werkzeug
from app.tools import registry
from app.tools.registry import EVER_OFFERED, EverOffered, WerkzeugRegistry
from tests.test_hausregeln import DEUTSCHE_WOERTER

_AUFRUF = Werkzeugaufruf(id="a1", name="web_search", argumente={"query": "x"})


def _deutsche_woerter(text: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[A-Za-zÄÖÜäöüß]+", text)} & DEUTSCHE_WOERTER


class _RegistryDieWirft:
    async def ausfuehren(self, *a, **kw):
        raise RuntimeError("kaputt")


class _RegistryDieVerbietet:
    async def ausfuehren(self, *a, **kw):
        raise WerkzeugVerboten("nicht erlaubt")


async def test_ein_echter_fehler_ist_keine_ablehnung():
    """The mutation that flipped this to True survived
    the whole test run before this test existed — nothing checked the
    generic error path's third value at all."""
    _, fehlgeschlagen, abgelehnt, _ = await _werkzeug_ausfuehren(
        _RegistryDieWirft(), _AUFRUF, "de",
    )
    assert fehlgeschlagen is True
    assert abgelehnt is False


async def test_eine_tor_3_ablehnung_ist_eine_ablehnung():
    _, fehlgeschlagen, abgelehnt, _ = await _werkzeug_ausfuehren(
        _RegistryDieVerbietet(), _AUFRUF, "de",
    )
    assert fehlgeschlagen is True
    assert abgelehnt is True


async def test_keine_registry_ist_eine_ablehnung():
    """No registry at all — the feature is off entirely — is the same
    outer boundary as Tor 3, not a tool that ran and failed."""
    _, fehlgeschlagen, abgelehnt, _ = await _werkzeug_ausfuehren(None, _AUFRUF, "de")
    assert fehlgeschlagen is True
    assert abgelehnt is True


async def test_kein_registry_text_traegt_keine_deutschen_woerter():
    """This text reaches the model as a ``role="tool"`` message — before
    the fix it carried ``sprache`` straight through, so a German window
    handed the model German."""
    text, _, _, _ = await _werkzeug_ausfuehren(None, _AUFRUF, "de")
    assert "not allowed" in text
    assert len(_deutsche_woerter(text)) < 2


async def test_ein_echter_fehler_traegt_keine_deutschen_woerter():
    """The generic exception path used to wrap the tool's own error text
    in a German sentence, reaching the model even though the underlying
    failure has nothing to do with the window's language."""
    text, _, _, _ = await _werkzeug_ausfuehren(_RegistryDieWirft(), _AUFRUF, "de")
    assert "Error in" in text
    assert len(_deutsche_woerter(text)) < 2


# --- The tools every run is offered, out of their own table ------------------


class _NeuesWerkzeug:
    """A tool in the shape ``EVER_OFFERED`` takes — as far as the DISPATCH is
    concerned: a module with a name and an ``ausfuehren``.

    The offering side wants more of a table entry than this (a
    ``werkzeug_beschreibung``, the sentence the model reads); what is shown
    here is that the call reaches it, which used to need a branch of its
    own."""

    WERKZEUG_NAME = "note_to_self"

    @staticmethod
    async def ausfuehren(argumente):
        return f"noted: {argumente.get('text')}"


async def test_a_new_line_in_ever_offered_is_executed_too(monkeypatch):
    """Every tool in ``EVER_OFFERED`` is offered to every run — and has to be
    executed too.

    A branch per tool in ``WerkzeugRegistry.ausfuehren`` was a second list
    that had to be remembered whenever the first one grew: a third entry
    would have been offered, drawn in the tools window and counted — and its
    call would have fallen all the way through to the refusal at the bottom
    (``WerkzeugVerboten``), with nothing saying why. The dispatch reads the
    table now (app/tools/registry.py)."""
    monkeypatch.setattr(
        registry, "EVER_OFFERED", (*EVER_OFFERED, EverOffered(_NeuesWerkzeug))
    )
    reg = WerkzeugRegistry([])

    assert await reg.ausfuehren("note_to_self", {"text": "hallo"}) == "noted: hallo"


async def test_the_clock_is_handed_the_registrys_zone(monkeypatch):
    """Silence probe for the same table: the clock gets the configured zone
    from the registry, exactly as it did when its own branch stood in
    ``ausfuehren`` — a run that could name its own zone would work out "in
    ten minutes" in a zone the entry does not fire in."""
    gesehen: dict = {}

    async def merken(argumente, *, zeitzone=None):
        gesehen["zone"] = zeitzone
        return "the time"

    monkeypatch.setattr(uhr, "ausfuehren", merken)
    reg = WerkzeugRegistry([], zeitzone="Europe/Berlin")

    assert await reg.ausfuehren(uhr.WERKZEUG_NAME, {}) == "the time"
    assert gesehen["zone"] == "Europe/Berlin"


async def test_the_goal_is_handed_this_runs_own_state(monkeypatch):
    """The other half of the same silence probe: the goal gets what belongs
    to the RUN — whether a report already went out, the schedule entry that
    fired it, and the table — and its own refusal still reaches the caller
    as the registry's one kind of no."""
    gesehen: dict = {}

    async def merken(argumente, *, schon_gemeldet=False, cronjobs_repo=None, cronjob_id=None):
        gesehen.update(
            gemeldet=schon_gemeldet, repo=cronjobs_repo, cronjob_id=cronjob_id
        )
        return "reported"

    monkeypatch.setattr(ziel_werkzeug, "ausfuehren", merken)
    reg = WerkzeugRegistry([], cronjobs_repo="TABLE")

    assert (
        await reg.ausfuehren(
            ziel_werkzeug.WERKZEUG_NAME, {}, ziel_gemeldet=True, cronjob_id="c7"
        )
        == "reported"
    )
    assert gesehen == {"gemeldet": True, "repo": "TABLE", "cronjob_id": "c7"}


async def test_the_goals_own_refusal_stays_a_refusal(monkeypatch):
    """And a tool that says no in its own words is still read as the
    registry's refusal — not as a tool that ran and failed."""

    async def nein(argumente, **_):
        raise ziel_werkzeug.ZielVerboten("no goal here")

    monkeypatch.setattr(ziel_werkzeug, "ausfuehren", nein)
    reg = WerkzeugRegistry([])

    with pytest.raises(WerkzeugVerboten, match="no goal here"):
        await reg.ausfuehren(ziel_werkzeug.WERKZEUG_NAME, {})
