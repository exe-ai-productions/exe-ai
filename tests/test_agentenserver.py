"""The agent model slot: the program's second model server, from outside."""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app import agentenmodellwahl, agentenserver
from app.modellrunner import Modellrunner


def test_der_platz_ist_ein_eigener():
    """Its own pid file and its own port — sharing either was the whole
    reason the embedding server got a runner of its own."""
    from app import einbettungsserver

    assert agentenserver.PID_DATEI != einbettungsserver.PID_DATEI
    assert agentenserver.SCHLUESSEL_VARIABLE != einbettungsserver.SCHLUESSEL_VARIABLE
    assert agentenserver.PORT_VORGABE == 8083


def test_das_fenster_steht_nicht_mehr_im_quelltext():
    """The window is the user's answer, not a number in a module.

    A rework replaced the guardian's forced 4096 with the runner's own default
    8192 and called it settled. It was not: a default is still a value nobody
    chose. Measured on a real run, the system prompt of an agent with fifteen
    tools takes about 6300 of those 8192 — roughly 1800 left for the task, the
    tool results and the answer together.

    So neither number may stand in this module any more. What is left here is
    the mechanism: no ``--ctx-size`` of its own in the extra flags, so the one
    the runner writes from what it is started with is the only one on the
    command line.
    """
    assert "--ctx-size" not in agentenserver.FLAGS
    quelle = Path(agentenserver.__file__).read_text(encoding="utf-8")
    zuweisungen = re.findall(r"^\s*KONTEXT\w*\s*=", quelle, re.MULTILINE)
    assert not zuweisungen, f"The slot pins a window again: {zuweisungen}"

    zeile = " ".join(
        _runner_attrappe().befehl("m.gguf", 32768, 99, agentenserver.PORT_VORGABE)
    )
    assert zeile.count("--ctx-size") == 1
    assert "--ctx-size 32768" in zeile


def test_jeder_start_oeffnet_auf_demselben_fenster():
    """One question, one answer — in all three places that could answer it.

    16384 is the rung of the ladder the window offers where a run has more
    room for its work than for its own preamble: measured on a real run, the
    system prompt of an agent with fifteen tools takes about 6300 tokens.
    The number is a starting point, not a limit; what a hand puts in the
    field is stored and read back before this one is ever reached.

    The floor below is the value that was in force on every machine before
    any of this: a default that shrinks a running setup is not a default.
    """
    import inspect

    from app import runnermodellwahl

    boden = 8192
    starten = inspect.signature(Modellrunner.starten).parameters["kontext"].default
    assert agentenmodellwahl.KONTEXT_VORGABE == 16384
    assert runnermodellwahl.KONTEXT_VORGABE == agentenmodellwahl.KONTEXT_VORGABE
    assert starten == agentenmodellwahl.KONTEXT_VORGABE
    assert starten >= boden


def test_eine_bestandsinstallation_bekommt_die_vorgabe(client: TestClient):
    """A field stored before these keys existed carries none of them. The
    settings cascade merges the defaults in, so the slot comes up on a window
    rather than on a ``None`` that would reach the command line as a missing
    flag."""
    from tests.conftest import agentenmodell_setzen

    agentenmodell_setzen(client, "klein.gguf", sorte="slot")
    werte = agentenmodellwahl.slot_startwerte(client.app.state.repositories)
    assert werte["kontext"] == agentenmodellwahl.KONTEXT_VORGABE
    # No layer count named: the slot is started without the flag (auto).
    assert werte["schichten"] is None
    # None means "the slot's own port" — the number belongs to the server.
    assert werte["port"] is None


def test_der_gewaehlte_kontext_erreicht_den_prozess(client: TestClient, monkeypatch):
    """The whole point: what the page stored is what the command line gets.

    Checked on the start route, because that is the path a hand takes — the
    autostart's is checked separately below, and the two must not be able to
    disagree.
    """
    from tests.conftest import agentenmodell_setzen

    agentenmodell_setzen(client, "klein.gguf", sorte="slot")
    client.put(
        "/api/v1/settings/global/agentenmodell",
        json={"wert": {"an": True, "sorte": "slot", "wert": "klein.gguf",
                       "kontext": 65536, "schichten": 40}},
    )
    gesehen: list[dict] = []
    runner = client.app.state.agentenrunner
    monkeypatch.setattr(runner, "starten", lambda modell, **kw: gesehen.append(kw))
    monkeypatch.setattr(runner, "lauf", lambda: None)

    client.post("/api/v1/agentenmodell/start", json={"modell": "klein.gguf"})
    assert gesehen and gesehen[0]["kontext"] == 65536
    assert gesehen[0]["schichten"] == 40


async def test_der_autostart_nimmt_dieselben_werte(client: TestClient, monkeypatch):
    """A restart must not quietly start the slot on something else.

    At program launch there is no browser, so a value the page had kept to
    itself would be gone — which is exactly why none of them lives in the
    page. Both paths call ``slot_startwerte``; this proves the second one
    does.
    """
    client.put(
        "/api/v1/settings/global/agentenmodell",
        json={"wert": {"an": True, "sorte": "slot", "wert": "klein.gguf",
                       "kontext": 65536, "port": 8099,
                       "module": {"klein.gguf": {"drafter": "mtp-klein.gguf",
                                                 "vision": "seher.gguf"}}}},
    )
    gesehen: list[dict] = []
    runner = client.app.state.agentenrunner
    monkeypatch.setattr(runner, "laeuft", lambda: False)
    monkeypatch.setattr(runner, "starten", lambda modell, **kw: gesehen.append(kw))
    monkeypatch.setattr(runner, "lauf", lambda: None)

    assert await agentenserver.slot_starten_wenn_gewollt(client.app) is True
    assert gesehen[0]["kontext"] == 65536
    assert gesehen[0]["drafter"] == "mtp-klein.gguf"
    assert gesehen[0]["vision"] == "seher.gguf"
    assert gesehen[0]["port"] == 8099


def _runner_attrappe():
    from pathlib import Path

    return agentenserver.runner_bauen(Path("/tmp"), "llama-server")


def test_die_vorgabe_ist_das_gemessene_modell():
    assert agentenserver.MODELL_VORGABE == "qwen2.5-coder-3b-instruct-q4_k_m.gguf"


def test_die_endpunkt_kennung_ist_die_des_einen_feldes():
    """The one field's slot choice resolves to exactly this id, and the id
    is fixed so a restart on the same port replaces the entry rather than
    adding a second one."""
    assert agentenserver.ENDPUNKT_ID == "agentenmodell"
    assert agentenserver.endpunkt_bauen().id == "agentenmodell"


def test_auskunft_nennt_ordner_und_vorgabe(client: TestClient):
    antwort = client.get("/api/v1/agentenmodell")
    assert antwort.status_code == 200
    daten = antwort.json()
    assert daten["laeuft"] is False
    assert daten["vorgabe"] == agentenserver.MODELL_VORGABE
    assert daten["port"] == agentenserver.PORT_VORGABE
    assert isinstance(daten["modelle"], list)


def test_start_ohne_modell_wird_abgewiesen(client: TestClient):
    """A name that is not in the folder never reaches a command line."""
    antwort = client.post(
        "/api/v1/agentenmodell/start", json={"modell": "gibtsnicht.gguf"}
    )
    assert antwort.status_code in (404, 412)


def test_stop_ist_immer_erlaubt(client: TestClient):
    """Stopping something that is not running is the state we wanted."""
    assert client.post("/api/v1/agentenmodell/stop").status_code == 200


def test_die_alte_eew_route_gibt_es_nicht_mehr(client: TestClient):
    """The route was renamed. Nothing may keep answering under the old name —
    a route that outlives its meaning is the next reader's wrong turn."""
    assert client.get("/api/v1/eew").status_code == 404


async def test_ein_laufender_slot_meldet_sich_bei_der_discovery(client: TestClient):
    """The whole reason the one field needs no second resolution path: the
    slot IS an ordinary endpoint while it runs. Which also means it shows up
    in the chat's model picker — wanted, and the opposite of what the
    guardian's comment in this place used to promise.

    Driven through the discovery directly rather than by starting a real
    llama-server: what is being tested is the registration, not the process.
    """
    discovery = client.app.state.discovery
    await discovery.anmelden(agentenserver.endpunkt_bauen())
    assert agentenserver.ENDPUNKT_ID in discovery.zustaende

    await discovery.abmelden(agentenserver.ENDPUNKT_ID)
    assert agentenserver.ENDPUNKT_ID not in discovery.zustaende


async def test_ohne_feld_startet_nichts_von_selbst(client: TestClient):
    """The autostart is the switched-on field's doing and nothing else's.
    Shipped off, so a fresh install loads no gigabyte nobody asked for."""
    assert await agentenserver.slot_starten_wenn_gewollt(client.app) is False
    assert client.app.state.agentenrunner.laeuft() is False


async def test_mit_feld_startet_der_slot_beim_programmstart(
    client: TestClient, monkeypatch
):
    """The deliberate break with "nothing here starts by itself": a
    field that names a slot model brings it up without anybody opening the
    model window, because otherwise every restart is a silent outage."""
    from tests.conftest import agentenmodell_setzen

    agentenmodell_setzen(client, "klein.gguf", sorte="slot")
    gestartet: list[str] = []
    runner = client.app.state.agentenrunner
    monkeypatch.setattr(runner, "laeuft", lambda: False)
    monkeypatch.setattr(runner, "starten", lambda modell, **kw: gestartet.append(modell))
    monkeypatch.setattr(runner, "lauf", lambda: None)

    assert await agentenserver.slot_starten_wenn_gewollt(client.app) is True
    assert gestartet == ["klein.gguf"]


async def test_eine_kennungswahl_startet_keinen_prozess(client: TestClient, monkeypatch):
    """The main model and a cloud endpoint have nothing to load — that is
    what choosing them means."""
    from tests.conftest import agentenmodell_setzen

    agentenmodell_setzen(client, "runner")
    gestartet: list[str] = []
    monkeypatch.setattr(
        client.app.state.agentenrunner, "starten", lambda modell, **kw: gestartet.append(modell)
    )

    assert await agentenserver.slot_starten_wenn_gewollt(client.app) is False
    assert gestartet == []


def test_die_feldliste_bietet_kein_nichts_mehr_an():
    """The row's first entry used to be "none — first reachable" with an
    EMPTY value, and an empty value means "on but nothing chosen, which
    behaves exactly like off" (app/agentenmodellwahl.py `wahl_pruefen`):
    whoever picked it got no agent server and a refused start. An entry that
    promises something it does not do is gone; the main model stands first,
    and the slot entries stay behind it.

    Read from the source because the list lives in a Svelte component — the
    same way the window's own numbers are read above.
    """
    quelle = (
        Path(__file__).resolve().parent.parent
        / "frontend/src/teile/Agentserver.svelte"
    ).read_text(encoding="utf-8")
    liste = quelle.split("const modellauswahl = $derived([", 1)[1]
    # Up to the list's own closing bracket, not the first one at all: the
    # entries carry bracket pairs of their own.
    liste = liste.split("\n  ])", 1)[0]

    assert "wert: ''" not in liste, "the list offers an empty value again"
    assert "agentenmodell_keins" not in quelle
    eintraege = re.findall(r"wert: ([^,]+),", liste)
    assert eintraege[0] == "HAUPTMODELL_WAHL", eintraege
    assert "`slot:${m.name}`" in liste, "the slot entries dropped out of the list"
    assert quelle.count("const HAUPTMODELL_WAHL = `kennung:${HAUPTMODELL}`") == 1


def test_der_klammertext_am_hauptmodell_ist_weg():
    """The entry reads "Hauptmodell",
    without the bracket that said which one it is."""
    for datei, erwartet in (
        ("app/locales/de.json", "Hauptmodell"),
        ("app/locales/en.json", "Main model"),
    ):
        katalog = json.loads(
            (Path(__file__).resolve().parent.parent / datei).read_text(encoding="utf-8")
        )
        assert katalog["modell"]["agentenmodell_hauptmodell"] == erwartet
        assert "agentenmodell_keins" not in katalog["modell"]


def test_die_feldliste_fuehrt_das_hauptmodell_nur_einmal():
    """With `runner` in the discovery the row said
    "Hauptmodell", reported itself open, and rendered an empty anchor where
    the entries belong — Svelte throws `each_key_duplicate` because the list
    is keyed by the value and the fixed first entry carries the same one the
    discovery hands out. The discovery entries have to skip it, the way they
    already skip the slot."""
    quelle = (
        Path(__file__).resolve().parent.parent
        / "frontend/src/teile/Agentserver.svelte"
    ).read_text(encoding="utf-8")
    liste = quelle.split("const modellauswahl = $derived([", 1)[1]
    liste = liste.split("\n  ])", 1)[0]

    assert "!== HAUPTMODELL_WAHL" in liste, (
        "the discovery entries can carry the main model a second time again"
    )
    # By endpoint, not by the whole id: a runner answering with several
    # models is handed out as `runner:<modell>`, and every one of those is
    # the server this row already names.
    assert "String(m.id).split(':')[0]" in liste
    # The silence check: the slot is still skipped as well.
    assert "startsWith('agentenmodell')" in liste


def test_die_wahl_kennt_keinen_aus_zustand():
    """The field has no off state. What the settings route
    stores carries the kind and the value and nothing else: a switch that
    still arrives from an older window is dropped rather than kept, and
    "nothing chosen" is the empty pair — which reads as the main model
    everywhere, not as "switched off"."""
    assert agentenmodellwahl.wahl_pruefen({"an": False}) == {}
    assert agentenmodellwahl.wahl_pruefen({"an": True}) == {}
    assert agentenmodellwahl.wahl_pruefen(
        {"an": True, "sorte": "slot", "wert": "x.gguf"}
    ) == {"sorte": "slot", "wert": "x.gguf"}
    # An empty value IS an answer and stays; an unknown kind is written as
    # "no kind" rather than dropped. Dropping it would leave the PREVIOUS
    # kind standing under the new value — a settings write merges key by
    # key, so a stored slot would then try to load an id as a file name.
    assert agentenmodellwahl.wahl_pruefen({"sorte": "", "wert": ""}) == {
        "sorte": "",
        "wert": "",
    }
    assert agentenmodellwahl.wahl_pruefen(
        {"sorte": "irgendwas", "wert": "pruefstand:gpt-4o"}
    ) == {"sorte": "", "wert": "pruefstand:gpt-4o"}


def test_eine_leere_wahl_gilt_auch_mit_art_als_hauptmodell(client: TestClient):
    """A stored row can carry a kind beside an empty value: ``wahl_pruefen``
    writes one whenever it was sent, and a partial write that sends none
    keeps the one already stored. Empty means the main model in every other
    reading — ``kennung`` and ``slot_datei`` both say "nothing chosen" for
    it — so it has to mean that here too, or a due schedule stays
    unpreloaded while its run lands on the main model all the same."""
    from tests.conftest import agentenmodell_setzen

    repositories = client.app.state.repositories
    agentenmodell_setzen(client, "klein.gguf", sorte="slot")
    # What the merge leaves behind when a later write sends only the value:
    # the old kind, an empty value.
    repositories.einstellungen.zusammenlegen(
        "global", agentenmodellwahl.SCHLUESSEL, {"wert": ""}
    )
    assert agentenmodellwahl.slot_datei(repositories) is None
    assert agentenmodellwahl.kennung(repositories, slot_id="agentenmodell") is None
    assert agentenmodellwahl.hauptmodell_gewaehlt(repositories) is True

    agentenmodell_setzen(client, "", sorte="kennung")
    assert agentenmodellwahl.hauptmodell_gewaehlt(repositories) is True


def test_hauptmodell_ist_nach_jeder_wahl_wieder_waehlbar(client: TestClient):
    """The way back is one pick in the same list, not a switch:
    after a slot file and after a foreign id, the main model can be chosen
    again — and it then behaves like a fresh installation, nothing is loaded
    for it."""
    from tests.conftest import agentenmodell_setzen

    repositories = client.app.state.repositories
    agentenmodell_setzen(client, "klein.gguf", sorte="slot")
    assert agentenmodellwahl.hauptmodell_gewaehlt(repositories) is False
    assert agentenmodellwahl.slot_datei(repositories) == "klein.gguf"

    agentenmodell_setzen(client, "pruefstand:gpt-4o")
    assert agentenmodellwahl.hauptmodell_gewaehlt(repositories) is False

    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    assert agentenmodellwahl.hauptmodell_gewaehlt(repositories) is True
    assert agentenmodellwahl.slot_datei(repositories) is None
