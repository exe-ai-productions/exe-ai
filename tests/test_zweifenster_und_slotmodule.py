"""What was left of moving the start choice into a setting: the second window, the slot's
modules, the frozen defaults, and the race under the PATCH route.

``8489df5`` built the PATCH route so two windows on one settings row could
stop overwriting each other. It closed the case where the two write DIFFERENT
keys. Three things were still open:

  * both windows writing the SAME key, because each side went on sending
    every field it watched — and a field it had not touched is the copy it
    read when its page opened;
  * ``""`` against ``None`` on the agent slot's two module rows, which is the
    finding the main model server's key had already had: a
    projector switched off by hand came back on the command line;
  * a pre-filled default written back as a choice, so a later change of the
    shipped default never reaches anybody who once opened the page.

And under all three, the read-modify-write the route itself does.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import agentenmodellwahl
from app.modellrunner import Modellrunner
from tests.conftest import fake_server

WURZEL = Path(__file__).resolve().parent.parent
FRONTEND = WURZEL / "frontend"
FILTER = FRONTEND / "src" / "lib" / "nurgeaendert.js"
MODELLSERVER = FRONTEND / "src" / "teile" / "Modellserver.svelte"
AGENTSERVER = FRONTEND / "src" / "teile" / "Agentserver.svelte"


# --- Only what the hand moved leaves the window ----------------
#
# The filter is plain ESM and is run as itself: what the two pages import is
# what is measured here, not a re-implementation of it in Python.


def _filter_laufen(js: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("no Node on this machine")
    treiber = FRONTEND / "nurgeaendert.pruefung.mjs"
    treiber.write_text(
        "import { nurGeaendert } from %s\n"
        "const bericht = (() => {\n%s\n})()\n"
        "console.log('---BERICHT---' + JSON.stringify(bericht))\n"
        # An import wants a URL, not a path: a Windows path is read as a
        # protocol ('c:') and refused.
        % (json.dumps(FILTER.as_uri()), textwrap.indent(js, "  ")),
        encoding="utf-8",
    )
    try:
        lauf = subprocess.run(
            [node, treiber.name], cwd=FRONTEND, capture_output=True, text=True,
            encoding="utf-8", timeout=60,
        )
    finally:
        treiber.unlink(missing_ok=True)
    assert lauf.returncode == 0, (lauf.stdout + lauf.stderr)[-2000:]
    marke = "---BERICHT---"
    assert marke in lauf.stdout, lauf.stdout[-2000:]
    return json.loads(lauf.stdout.split(marke, 1)[1].strip())


def test_zwei_fenster_auf_denselben_zahlen_ueberfahren_sich_nicht_mehr():
    """The finding, as the two windows meet it.

    Window A has set the context to 131072. Window B still shows the 32768 it
    read when it opened and nudges the layers. Before, B's write carried its
    stale context out with it; the merge in the route cannot help, because
    ``kontext`` really is in the request.
    """
    bericht = _filter_laufen(
        """
        /* B's store: what B read when its page opened. */
        const stand = { kontext: 32768, schichten: 99, port: null }
        /* B's form after the hand moved the layers, and nothing else. */
        return nurGeaendert(
          { kontext: 32768, schichten: 40, port: 8080 },
          stand,
          { kontext: 32768, schichten: 99, port: 8080 },
        )
        """
    )
    assert bericht == {"schichten": 40}, bericht


def test_die_zahl_die_bewegt_wurde_geht_hinaus():
    """The other half: a value the hand did move is not held back."""
    bericht = _filter_laufen(
        """
        return nurGeaendert(
          { kontext: 131072, schichten: 99, port: 8080 },
          { kontext: 32768, schichten: 99, port: null },
          { kontext: 32768, schichten: 99, port: 8080 },
        )
        """
    )
    assert bericht == {"kontext": 131072}, bericht


def test_eine_vorgabe_friert_nicht_als_wahl_ein():
    """A fresh install: nothing chosen, the form filled in from `vorgaben`.

    Opening the page must leave the setting as empty as it found it. The port
    had a brake of its own for exactly this; the window, the layers and the
    engine levers did not, so a later change of the shipped default would
    never have reached anybody who once opened the page.
    """
    bericht = _filter_laufen(
        """
        return nurGeaendert(
          { kontext: 32768, schichten: 99, port: 8080, fein: { kv_cache: 'f16' } },
          { kontext: null, schichten: null, port: null, fein: null },
          { kontext: 32768, schichten: 99, port: 8080, fein: { kv_cache: 'f16' } },
        )
        """
    )
    assert bericht == {}, bericht


def test_die_null_bei_den_schichten_bleibt_eine_zahl():
    """Zero layers is a choice somebody makes on purpose — "run this on the
    processor alone". It is not a missing value and must not be read as one.
    """
    bericht = _filter_laufen(
        """
        return {
          /* Stored as 0, form shows 0: nothing to write, and above all no
             fall back to the default. */
          ruhig: nurGeaendert({ schichten: 0 }, { schichten: 0 }, { schichten: 99 }),
          /* Moved to 0 by hand: that goes out. */
          bewegt: nurGeaendert({ schichten: 0 }, { schichten: 99 }, { schichten: 99 }),
        }
        """
    )
    assert bericht == {"ruhig": {}, "bewegt": {"schichten": 0}}, bericht


def test_die_hebel_werden_nach_inhalt_verglichen_nicht_nach_reihenfolge():
    """The engine levers are a set, not a number, and what comes back from
    the service is JSON — the order its keys arrive in is nobody's decision.
    Comparing them as text would make every poll look like a change."""
    bericht = _filter_laufen(
        """
        const gespeichert = { kv_cache: 'q8_0', faeden: 4, moe_auf_cpu: false }
        return {
          gleich: nurGeaendert(
            { fein: { moe_auf_cpu: false, faeden: 4, kv_cache: 'q8_0' } },
            { fein: gespeichert }, {},
          ),
          anders: nurGeaendert(
            { fein: { moe_auf_cpu: false, faeden: 8, kv_cache: 'q8_0' } },
            { fein: gespeichert }, {},
          ),
        }
        """
    )
    assert bericht["gleich"] == {}
    assert bericht["anders"] == {"fein": {"moe_auf_cpu": False, "faeden": 8, "kv_cache": "q8_0"}}


def test_ein_hebel_den_die_form_gar_nicht_hat_zaehlt_nicht_als_aenderung():
    """Measured on the running program, not argued.

    The engine settings the two pages show carry no ``flash_attention`` —
    neither page has a row for it, so the form's object is a subset of what
    the service stores and sends back. Compared as equals, that subset is
    "different" every single time, and opening the agent server's page wrote
    the shipped levers straight into the setting as a choice. Which is the
    same freezing as above, one field further along.
    """
    bericht = _filter_laufen(
        """
        const vorgabe = { kv_cache: 'f16', flash_attention: 'auto', faeden: null,
                          moe_auf_cpu: false, moe_schichten: null,
                          festnageln: false, parallel: null }
        /* What the form holds: the same answers, minus the lever it has no
           row for. */
        const form = { kv_cache: 'f16', moe_auf_cpu: false, festnageln: false,
                       faeden: null, moe_schichten: null, parallel: null }
        return {
          ruhig: nurGeaendert({ fein: form }, { fein: null }, { fein: vorgabe }),
          bewegt: nurGeaendert(
            { fein: { ...form, kv_cache: 'q8_0' } }, { fein: null }, { fein: vorgabe },
          ),
        }
        """
    )
    assert bericht["ruhig"] == {}
    assert bericht["bewegt"]["fein"]["kv_cache"] == "q8_0"


#: The fields both pages hold their own copy of and therefore may only send
#: through the filter. A hand-written object naming any of them is a write of
#: this window's stale copy — see the header of lib/nurgeaendert.js.
GEFILTERTE_FELDER = ("kontext", "schichten", "port", "fein")


def aufrufe(quelle: str, name: str) -> list[str]:
    """Every argument text of ``name(...)`` in a source file.

    Parenthesis-matched rather than pattern-matched, because the argument of
    interest is an object literal and the whole point of this guard is that it
    must not depend on how that literal is laid out.
    """
    gefunden: list[str] = []
    for treffer in re.finditer(rf"\b{re.escape(name)}\(", quelle):
        i = treffer.end()
        tiefe = 1
        while i < len(quelle) and tiefe:
            if quelle[i] in "([{":
                tiefe += 1
            elif quelle[i] in ")]}":
                tiefe -= 1
            i += 1
        gefunden.append(quelle[treffer.end() : i - 1])
    return gefunden


def test_beide_serverseiten_schicken_nur_noch_das_geaenderte():
    """Both pages, and through the same filter.

    A guard on the source because the two watchers live in components: what
    is proved above is the rule, this is that the rule is the one both pages
    apply — and that neither hands the store a hand-written object of every
    field it watches any more.

    Read by NAME and not by layout. The first version of this test looked for
    the literal ``werteSetzen({\\n  kontext,`` and therefore only ever saw a
    watcher — the start button next door wrote ``{ modell, kontext, schichten,
    port }``, with the file first, and walked straight past. One field in
    front of another was the whole difference between caught and missed, which
    is no difference at all. So: every call is taken apart, and none of the
    filtered fields may stand in one by hand, whatever order they come in.
    """
    for datei in (MODELLSERVER, AGENTSERVER):
        quelle = datei.read_text(encoding="utf-8")
        assert "nurGeaendert" in quelle, datei.name
        assert "from '../lib/nurgeaendert.js'" in quelle, datei.name
        # The watcher hands on what the filter returned, never a literal.
        assert re.search(r"werteSetzen\(nachtrag\)", quelle), datei.name
        for argument in aufrufe(quelle, "werteSetzen"):
            # What the filter itself returned may of course be spread in.
            rest = re.sub(r"\.{3}\s*nachtrag", "", argument)
            dabei = [f for f in GEFILTERTE_FELDER if re.search(rf"\b{f}\b", rest)]
            assert not dabei, f"{datei.name}: werteSetzen({argument.strip()}) → {dabei}"


# --- "chosen: none" on the slot, all the way to the command line ---


def test_der_slot_haelt_die_beiden_leeren_auseinander():
    """``""`` is "chosen: none", ``None`` is "nobody said".

    The slot's key folded the first into the second, which is what let the
    name heuristic put a projector back that had been switched off by hand.
    """
    sauber = agentenmodellwahl.wahl_pruefen(
        {"module": {"klein.gguf": {"drafter": "", "vision": ""}}}
    )
    assert sauber == {"module": {"klein.gguf": {"drafter": "", "vision": ""}}}

    sauber = agentenmodellwahl.wahl_pruefen(
        {"module": {"klein.gguf": {"drafter": None, "vision": None}}}
    )
    assert sauber == {"module": {"klein.gguf": {"drafter": None, "vision": None}}}

    # A key that was not sent still does not appear — the row is written in
    # pieces, and a missing piece is not an answer.
    assert agentenmodellwahl.wahl_pruefen({"kontext": 4096}) == {"kontext": 4096}


def test_die_startwerte_des_slots_tragen_das_ausdrueckliche_keins(client: TestClient):
    """Through the store and back: what the page picked is what the start
    path reads, with the difference intact."""
    client.put(
        "/api/v1/settings/global/agentenmodell",
        json={"wert": {"an": True, "sorte": "slot", "wert": "klein.gguf",
                       "module": {"klein.gguf": {"drafter": "", "vision": ""}}}},
    )
    werte = agentenmodellwahl.slot_startwerte(
        client.app.state.repositories, "klein.gguf"
    )
    assert werte["drafter"] == ""
    assert werte["vision"] == ""

    # Nobody said: the defaults leave both at None, so the manifest speaks.
    client.delete("/api/v1/settings/global/agentenmodell")
    client.put(
        "/api/v1/settings/global/agentenmodell",
        json={"wert": {"an": True, "sorte": "slot", "wert": "klein.gguf"}},
    )
    werte = agentenmodellwahl.slot_startwerte(client.app.state.repositories)
    assert werte["drafter"] is None
    assert werte["vision"] is None


def test_die_slotzeilen_zeigen_erst_das_gemerkte_dann_das_erklaerte():
    """The page has to say what would actually start.

    Measured on the running program first: a row that shows "none" while the
    manifest's companion is attached anyway does not merely mislead — it
    makes the choice unreachable. Picking "none" on a row that already reads
    "none" changes nothing, so nothing is written, so ``null`` stays stored
    and the pairing comes back at the next start. The model server's page has
    read the rows in this order all along.
    """
    quelle = AGENTSERVER.read_text(encoding="utf-8")
    assert "function moduleUebernehmen()" in quelle
    koerper = quelle.split("function moduleUebernehmen()", 1)[1].split("\n  }", 1)[0]
    # The remembered answer first (a remembered "" counts, hence ??), then
    # what the manifest declared for this file.
    assert "modul.drafter ?? z?.mtp" in koerper
    assert "modul.vision ?? z?.mmproj" in koerper
    # And re-read when the file changes, because the manifest speaks per file.
    assert quelle.count("moduleUebernehmen()") >= 3


def test_ein_abgewaehlter_projektor_des_slots_bleibt_von_der_zeile_weg(
    tmp_path, client: TestClient, monkeypatch
):
    """The measurement the finding asks for, at the command line.

    A slot model with a matching ``mmproj`` next to it. The user picks
    "none": nothing may reach the line. With ``None`` stored instead — nobody
    said — the heuristic still attaches it, which is the counter-test.
    """
    ordner = tmp_path / "slotmodelle"
    (ordner / "vision").mkdir(parents=True)
    (ordner / "klein.gguf").write_bytes(b"x" * 5)
    (ordner / "vision" / "klein-mmproj-Q8_0.gguf").write_bytes(b"x" * 5)
    (ordner / "mtp").mkdir()
    (ordner / "mtp" / "mtp-klein.gguf").write_bytes(b"x" * 5)
    from app import modellzuordnung

    modellzuordnung.eintragen(ordner, "klein.gguf", "mtp", "mtp-klein.gguf")
    runner = Modellrunner(ordner, programm="llama-server")

    def zeile(**werte) -> str:
        client.put(
            "/api/v1/settings/global/agentenmodell",
            json={"wert": {"an": True, "sorte": "slot", "wert": "klein.gguf",
                           "module": {"klein.gguf": werte}}},
        )
        start = agentenmodellwahl.slot_startwerte(
            client.app.state.repositories, "klein.gguf"
        )
        return " ".join(
            runner.befehl(
                "klein.gguf", start["kontext"], start["schichten"], 8099,
                drafter=start["drafter"], vision=start["vision"], fein=start["fein"],
            )
        )

    # Nobody said: manifest and heuristic step in — both modules appear.
    ohne_wahl = zeile(drafter=None, vision=None)
    assert "--mmproj" in ohne_wahl
    # `befehl` reads the manifest only for the projector; the draft is picked
    # up in `starten`, which is why the pair is measured there as well below.

    # Chosen: none. Neither may come back.
    gewaehlt_keins = zeile(drafter="", vision="")
    assert "--mmproj" not in gewaehlt_keins
    assert "--model-draft" not in gewaehlt_keins


def test_ein_abgewaehltes_tempomodul_des_slots_bleibt_von_der_zeile_weg(
    tmp_path, client: TestClient
):
    """The same for the speed module, where the manifest speaks in
    ``starten`` rather than in ``befehl`` — so the real process is what says
    whether the choice held."""

    from app import modellzuordnung

    ordner = tmp_path / "slotmodelle2"
    (ordner / "mtp").mkdir(parents=True)
    (ordner / "klein.gguf").write_bytes(b"x" * 5)
    (ordner / "mtp" / "mtp-klein.gguf").write_bytes(b"x" * 5)
    modellzuordnung.eintragen(ordner, "klein.gguf", "mtp", "mtp-klein.gguf")
    programm = fake_server(tmp_path / "llama-server-attrappe")

    def gestartet_mit(**werte) -> str | None:
        client.put(
            "/api/v1/settings/global/agentenmodell",
            json={"wert": {"an": True, "sorte": "slot", "wert": "klein.gguf",
                           "module": {"klein.gguf": werte}}},
        )
        start = agentenmodellwahl.slot_startwerte(
            client.app.state.repositories, "klein.gguf"
        )
        runner = Modellrunner(ordner, programm=str(programm))
        try:
            return runner.starten(
                "klein.gguf", kontext=start["kontext"], schichten=start["schichten"],
                port=18471, drafter=start["drafter"], vision=start["vision"],
            ).drafter
        finally:
            runner.stoppen()

    # Nobody said: the manifest's pairing is what starts, exactly as before.
    assert gestartet_mit(drafter=None, vision=None) == "mtp-klein.gguf"
    # Chosen: none. The manifest stays out of it.
    assert gestartet_mit(drafter="", vision="") == ""


# --- Two PATCHes at once, and neither is lost ----------------------


def test_zwei_gleichzeitige_patches_verlieren_keinen_wert(client: TestClient):
    """``zusammenlegen`` is a read then a write, on a connection in autocommit
    mode, in a handler FastAPI runs in a threadpool.

    Without a lock the second read lands before the first write, and one of
    the two keys is simply gone.

    Threads on the repository and not requests through the test client: the
    client drives one ASGI app through one portal and serialises what it
    sends, so the race would never even be attempted there. This is the shape
    the loss really has — the same reasoning the dock's own race test stands
    on (test_agentendock.py).
    """
    laden = client.app.state.repositories.einstellungen
    laden.setzen("global", "runnermodell", {"modell": "gemma.gguf"})

    anzahl = 60
    schreiber = 6
    fehler: list[BaseException] = []
    tor = threading.Barrier(schreiber)

    def schreiben(nummer: int) -> None:
        try:
            tor.wait(timeout=20)
            for lauf in range(anzahl):
                laden.zusammenlegen(
                    "global", "runnermodell", {f"feld{nummer}": lauf}
                )
        except BaseException as ausnahme:  # noqa: BLE001 - reported below
            fehler.append(ausnahme)

    faeden = [threading.Thread(target=schreiben, args=(n,)) for n in range(schreiber)]
    for faden in faeden:
        faden.start()
    for faden in faeden:
        faden.join(timeout=120)

    assert fehler == [], fehler
    stand = laden.holen("global", "runnermodell")
    # Every writer's last word is still there, and so is the value none of
    # them touched.
    assert stand["modell"] == "gemma.gguf"
    for nummer in range(schreiber):
        assert stand.get(f"feld{nummer}") == anzahl - 1, (nummer, stand)


def test_die_route_verliert_auch_nichts(client: TestClient):
    """And the same through the route the two windows really use, so the lock
    is proved to sit under the request and not only under the repository."""
    client.put(
        "/api/v1/settings/global/runnermodell",
        json={"wert": {"modell": "gemma.gguf"}},
    )
    assert client.patch(
        "/api/v1/settings/global/runnermodell", json={"wert": {"kontext": 131072}}
    ).status_code == 200
    assert client.patch(
        "/api/v1/settings/global/runnermodell", json={"wert": {"schichten": 0}}
    ).status_code == 200
    stand = client.app.state.repositories.einstellungen.holen("global", "runnermodell")
    assert stand == {"modell": "gemma.gguf", "kontext": 131072, "schichten": 0}


def test_die_sperre_steht_um_lesen_und_schreiben_zusammen():
    """A guard on the shape, not only on the outcome: the race above is
    timing, and a test that only ever measured the end could go green on a
    machine that happened not to interleave.
    """
    from app.db.repositories import einstellungen as modul

    quelle = Path(modul.__file__).read_text(encoding="utf-8")
    koerper = quelle.split("def zusammenlegen", 1)[1].split("\n    def ", 1)[0]
    assert "with _MISCH_SCHLOSS:" in koerper
    # Read and write both inside it — a lock around only one of the two is
    # the same race with more ceremony.
    innen = koerper.split("with _MISCH_SCHLOSS:", 1)[1]
    assert "self.holen(" in innen
    assert "self.setzen(" in innen
