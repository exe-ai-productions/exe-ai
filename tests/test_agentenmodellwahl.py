"""The slot's own preload switch.

What this has to get right is the split the order draws: the field's
consent to a slot model still stands when the switch is off, only the BLIND
autostart at program launch stops acting on it by itself — a due cron entry
wakes the slot all the same. Everything else about the field (kontext,
schichten, the two modules) already has its own tests; this file is only
about the one new key.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import agentenmodellwahl as wahl
from app import agentenserver
from app.api.v1.einstellungen import PRUEFER
from app.db.repositories.einstellungen import GLOBAL


def test_der_schluessel_steht_im_pruefer():
    """Without this entry the settings route answers 400 and the switch
    never leaves the page it was set on."""
    assert wahl.SCHLUESSEL in PRUEFER
    assert PRUEFER[wahl.SCHLUESSEL] is wahl.wahl_pruefen


def test_vorladen_ist_ab_werk_erlaubt(repos):
    """Shipped ON: the slot has always started at every program launch
    while a model was chosen, and a different default would silently take
    that away from every installation that already has it."""
    assert wahl.vorladen_erlaubt(repos) is True


def test_vorladen_laesst_sich_abschalten(repos):
    repos.einstellungen.setzen(GLOBAL, wahl.SCHLUESSEL, {"vorladen": False})
    assert wahl.vorladen_erlaubt(repos) is False

    repos.einstellungen.setzen(GLOBAL, wahl.SCHLUESSEL, {"vorladen": True})
    assert wahl.vorladen_erlaubt(repos) is True


def test_vorladen_wird_beim_pruefen_zu_einem_ja_oder_nein():
    assert wahl.wahl_pruefen({"vorladen": 0})["vorladen"] is False
    assert wahl.wahl_pruefen({"vorladen": "ja"})["vorladen"] is True
    assert "vorladen" not in wahl.wahl_pruefen({"kontext": 4096})


def test_vorgaben_nennen_vorladen():
    assert "vorladen" in wahl.VORGABE
    assert wahl.VORGABE["vorladen"] is True


# --- The autostart's own gate (app/agentenserver.py) ------------------------


def _slot_setzen(client: TestClient, datei: str, *, vorladen: bool | None = None) -> None:
    wert: dict[str, object] = {"sorte": wahl.SORTE_SLOT, "wert": datei}
    if vorladen is not None:
        wert["vorladen"] = vorladen
    client.app.state.repositories.einstellungen.setzen(GLOBAL, wahl.SCHLUESSEL, wert)


async def test_ausgeschaltet_startet_der_autostart_nichts(
    client: TestClient, monkeypatch
):
    """The switched-off preload takes back the program's own consent to
    start the slot unasked — the field still names a model, but nothing
    brings it up by itself at program launch."""
    _slot_setzen(client, "klein.gguf", vorladen=False)
    gestartet: list[str] = []
    monkeypatch.setattr(
        client.app.state.agentenrunner, "starten",
        lambda modell, **kw: gestartet.append(modell),
    )

    assert await agentenserver.slot_starten_wenn_gewollt(client.app) is False
    assert gestartet == []


async def test_eingeschaltet_startet_der_autostart_wie_bisher(
    client: TestClient, monkeypatch
):
    """The default (on) must keep today's behaviour exactly — an update
    must not silently take a running autostart away."""
    _slot_setzen(client, "klein.gguf", vorladen=True)
    runner = client.app.state.agentenrunner
    monkeypatch.setattr(runner, "laeuft", lambda: False)
    gestartet: list[str] = []
    monkeypatch.setattr(runner, "starten", lambda modell, **kw: gestartet.append(modell))
    monkeypatch.setattr(runner, "lauf", lambda: None)

    assert await agentenserver.slot_starten_wenn_gewollt(client.app) is True
    assert gestartet == ["klein.gguf"]


async def test_ein_faelliger_termin_weckt_den_slot_trotz_abgeschaltet(
    client: TestClient, monkeypatch
):
    """The one exception the order draws: a due entry that finds nothing to
    run on wakes the slot regardless of the preload switch
    (app/cronablauf.py, ``faellig=True``) — that call is the program
    answering a run that needs the slot right now, not preloading ahead of
    one, and it is not what the switch turns off."""
    _slot_setzen(client, "klein.gguf", vorladen=False)
    runner = client.app.state.agentenrunner
    monkeypatch.setattr(runner, "laeuft", lambda: False)
    gestartet: list[str] = []
    monkeypatch.setattr(runner, "starten", lambda modell, **kw: gestartet.append(modell))
    monkeypatch.setattr(runner, "lauf", lambda: None)

    assert await agentenserver.slot_starten_wenn_gewollt(client.app, faellig=True) is True
    assert gestartet == ["klein.gguf"]


async def test_ein_bereits_laufender_slot_bleibt_unberuehrt(
    client: TestClient, monkeypatch
):
    """Switched off or not, a slot that is already up answers ``True``
    without being touched again — the switch decides whether to START it,
    never whether an already-running one stays."""
    _slot_setzen(client, "klein.gguf", vorladen=False)
    monkeypatch.setattr(client.app.state.agentenrunner, "laeuft", lambda: True)
    gestartet: list[str] = []
    monkeypatch.setattr(
        client.app.state.agentenrunner, "starten",
        lambda modell, **kw: gestartet.append(modell),
    )

    assert await agentenserver.slot_starten_wenn_gewollt(client.app) is True
    assert gestartet == []
