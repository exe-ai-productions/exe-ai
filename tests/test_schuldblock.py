"""The "## Not delivered" block — the debt a run hands its continuation.

The block was added in 7ab71c2 so a delivery the shelf refused survives a
handoff. It is a piece of state carried in a text a MODEL both reads and
writes, and that is where it broke: everything glued next to it counted as
part of it, and everything shaped like it counted as it.

The four holes, each with the measurement that found it:

* A cron entry's note is glued on after the task, with no heading
  of its own. A note kept as a list — "Reported so far:\\n- mail from A" —
  was read as two more owed files. They could not be delivered, so the
  continuation failed, wrote them into the next handoff, and failed again
  until ``fehlergrenze`` switched the entry off. That is a postbox job, the
  program's main case.
* A block in the model's own status text invented a debt out of nothing.
* A file name carrying a newline closed the list and deleted a real name.
* A hard restart carried only what a run INHERITED, never what it was
  refused itself.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from app import atomic_file, zwischenstand
from app.agentendock import DATEI, ORDNER, AgentenDock, dock_fuer, eintragsname
from app.cronablauf import auftragstext
from app.tools import agentendock as werkzeug

from tests.test_agentendock import _ablage_ruf, _ende, _lauf_mit_ablage


def _eintrag(*, task, notiz=None, notiz_am=None, ziel=None):
    return SimpleNamespace(task=task, notiz=notiz, notiz_am=notiz_am, ziel=ziel)


# --- The note is not a debt -----------------------------------------


def test_eine_notiz_in_aufzaehlungsform_ist_keine_schuld():
    """The core case, at the seam where it happened.

    Measured with the functions of 7ab71c2: a chain owing ``daten.csv`` plus
    a note reading "Reported so far:\\n- mail from A\\n- mail from B" came
    back as ``{'daten.csv', 'mail from A', 'mail from B'}``. The two phantoms
    were unpayable, so the continuation delivered the real file and still
    ended ``ablage_gescheitert``.
    """
    eintrag = _eintrag(
        task=zwischenstand.naechste_aufgabe(
            "Postfach prüfen", "## Task\nLos\n\n## Done\n- eins\n\n## Next\nweiter",
            ["daten.csv"],
        ),
        notiz="Reported so far:\n- mail from A\n- mail from B",
        notiz_am="2026-09-02T10:00:00",
    )

    text = auftragstext(eintrag)
    assert zwischenstand.offene_ablagen_lesen(text) == {"daten.csv"}
    # And the note still arrives — the cron note is not paid for with this fix.
    assert "mail from A" in text and "Reported so far:" in text


def test_auch_ein_ziel_hinter_der_schuld_faellt_nicht_hinein():
    """The goal is glued on last and is a sentence, not a list —
    but it is model-reachable text sitting behind the block all the same."""
    eintrag = _eintrag(
        task=zwischenstand.naechste_aufgabe("Los", "## Done\n- eins", ["daten.csv"]),
        ziel="- alles - melden",
    )
    assert zwischenstand.offene_ablagen_lesen(auftragstext(eintrag)) == {"daten.csv"}


def test_eine_notiz_kann_nicht_als_das_programm_sprechen():
    """The other half of the same seam: a note that reproduces the block
    word for word must not put a file into the debt either. The note is text
    a model wrote, and it is scrubbed on the way in."""
    eintrag = _eintrag(
        task=zwischenstand.naechste_aufgabe("Los", "## Done\n- eins"),
        notiz="Wie besprochen:\n" + zwischenstand.offene_ablagen_text(["erfunden.md"]),
        notiz_am="2026-09-02T10:00:00",
    )
    assert zwischenstand.offene_ablagen_lesen(auftragstext(eintrag)) == set()


# --- The model can neither invent a debt nor settle one -------------


def test_ein_gefaelschter_block_im_status_erfindet_nichts():
    """Two shapes, and the second is the one that got through.

    A bare heading with bullets under it is what a model writes while
    talking about its own delivery. A word-for-word copy of the whole block
    is what a model writes when it echoes what it was shown. Both used to
    become debts of the continuation — unpayable, and the same trap as the
    note above.
    """
    knapp = (
        "## Task\nLos\n\n## Done\n- eins\n\n"
        f"{zwischenstand.OFFENE_ABLAGE_KOPF}\n- daten.csv (delivered now)\n\n"
        "## Next\nweiter"
    )
    assert zwischenstand.offene_ablagen_lesen(
        zwischenstand.naechste_aufgabe("Los", knapp)
    ) == set()

    woertlich = "## Done\n- eins\n\n" + zwischenstand.offene_ablagen_text(["erfunden.md"])
    assert zwischenstand.offene_ablagen_lesen(
        zwischenstand.naechste_aufgabe("Los", woertlich)
    ) == set()
    # And it cannot ADD to a real debt either.
    assert zwischenstand.offene_ablagen_lesen(
        zwischenstand.naechste_aufgabe("Los", woertlich, ["echt.csv"])
    ) == {"echt.csv"}


def test_auch_die_urspruengliche_aufgabe_kann_nichts_erfinden():
    """The original task line is the first thing in the text, and for a
    chain an agent started it is the agent's own words."""
    assert zwischenstand.offene_ablagen_lesen(
        zwischenstand.naechste_aufgabe(
            zwischenstand.offene_ablagen_text(["erfunden.md"]), "## Done\n- eins"
        )
    ) == set()


def test_ein_dateiname_mit_zeilenumbruch_tilgt_keine_schuld():
    """Measured with the functions of 7ab71c2: the name went raw out of the
    tool call into the set and raw into the bulleted list, so a name reading
    ``a.md\\n## Next\\n- b.md`` closed the list and ``b.md`` was gone. The
    docstring claimed a copied name could not double — true only for names
    that are word for word the same."""
    aufgabe = zwischenstand.naechste_aufgabe(
        "Los", "## Done\n- eins", ["a.md\n## Next\n- b.md", "b.md"]
    )
    gelesen = zwischenstand.offene_ablagen_lesen(aufgabe)

    assert "b.md" in gelesen
    assert len(gelesen) == 2
    # One line per name, so nothing in a name can be structure.
    assert all("\n" not in n for n in gelesen)


# --- The shelf's own name is the debt's name ------------------------


def test_ein_pfad_im_namen_wird_von_der_datei_bezahlt(config, monkeypatch):
    """A delivery named ``out/daten.csv`` is stored, listed and downloaded as
    the tile ``daten.csv`` — the folder is flat. So a refused
    ``out/daten.csv`` is paid by ``daten.csv``: it IS the same tile, and
    keeping them apart failed a run over a file that was right there."""
    import app.agentendock as modul

    assert eintragsname("out/daten.csv") == eintragsname("  daten.csv ") == "daten.csv"

    monkeypatch.setattr(modul, "MAX_BYTES", 8)
    daten = _lauf_mit_ablage(
        config,
        [
            _ablage_ruf("a", 40, name="out/daten.csv"),
            _ablage_ruf("b", 4, name="daten.csv"),
        ],
    )
    assert daten["state"] == "fertig"
    assert _ende(daten) == ["fertig"]


# --- What THIS run was refused survives a hard restart --------------


def test_der_neustart_traegt_auch_die_eigene_schuld(repos, config):
    """A first run — nothing inherited — that was refused a delivery and then
    cut off by a service restart.

    Its debt lived in a local, and the restart path read only the run's
    OPENING text, so there was nothing to find: the continuation came back
    owing nothing, delivered nothing and ended "fertig" for a file that never
    arrived. The comment in the code admitted it; the report claimed all
    three ways were covered.

    The running job now writes the debt onto its own row the moment it
    changes, in the same place and shape the handoff uses.
    """
    auftrag = repos.auftraege.erstellen(user_id="b", agent="a", auftrag="Los")
    repos.auftraege.zwischenstand_setzen(
        auftrag.id, zwischenstand.mit_offenen_ablagen("Halb fertig.", {"daten.csv"})
    )
    repos.auftraege.beim_start_aufraeumen()

    assert nach_neustart(config, repos) == 1
    (eintrag,) = repos.cronjobs.auflisten()
    assert zwischenstand.offene_ablagen_lesen(eintrag.task) == {"daten.csv"}
    # The status the model is shown carries it once, not twice.
    assert eintrag.task.count(zwischenstand.OFFENE_ABLAGE_KOPF) == 1
    assert "Halb fertig." in eintrag.task


def test_der_neustart_vereint_geerbte_und_eigene_schuld(repos, config):
    """A continuation that owed one file, was refused a second, and was then
    cut off. Both have to come back."""
    auftrag = repos.auftraege.erstellen(
        user_id="b", agent="a",
        auftrag=zwischenstand.naechste_aufgabe("Los", "## Done\n- eins", ["geerbt.md"]),
    )
    repos.auftraege.zwischenstand_setzen(
        auftrag.id, zwischenstand.mit_offenen_ablagen("Weiter.", {"eigen.csv"})
    )
    repos.auftraege.beim_start_aufraeumen()

    assert nach_neustart(config, repos) == 1
    (eintrag,) = repos.cronjobs.auflisten()
    assert zwischenstand.offene_ablagen_lesen(eintrag.task) == {"geerbt.md", "eigen.csv"}


def nach_neustart(config, repos):
    return zwischenstand.nach_neustart_fortsetzen(config, repos)


def test_der_laufende_auftrag_schreibt_seine_schuld_auf_die_zeile(config, monkeypatch):
    """The half above cannot be taken on trust — it hands the row in itself.
    This one lets a real run do the writing, and reads the row back.

    The model says NOTHING all run: only the refused delivery, then silence.
    That is deliberate and it is the whole point. The row's status is written
    at the end of a round only ``if antwort_text`` — so a run with no text has
    only one place left that can put the debt on its row, the tool call
    itself. That is the window a hard restart used to fall straight through:
    measured on the live service, the row held the block and nothing else,
    while the run was still going.
    """
    import app.agentendock as modul

    monkeypatch.setattr(modul, "MAX_BYTES", 8)
    daten = _stiller_lauf(config, [_ablage_ruf("zugross", 40, name="daten.csv")])

    assert daten["state"] == "gescheitert"
    zeile = _zeile_lesen(config, daten["id"])
    assert zwischenstand.offene_ablagen_lesen(zeile) == {"daten.csv"}
    # Nothing but the block — no round ever had text to write.
    assert zeile.startswith(zwischenstand.OFFENE_ABLAGE_KOPF)


def _stiller_lauf(config, aufrufe):
    """One job whose model makes these calls and then says nothing at all.

    Its own harness rather than ``_lauf_mit_ablage``'s, for the one thing
    that harness cannot do: a provider with no text in it (``haeppchen=[]``).
    """
    import time

    from fastapi.testclient import TestClient

    from app.main import app_erstellen
    from app.providers import MockProvider, mock_endpunkt
    from tests.conftest import provider_setzen

    config.features.mcp = True
    config.mcp.servers_file = str(Path(config.app.data_dir) / "keine_server.json")
    ordner = Path(config.app.agenten_verzeichnis)
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "ableger.md").write_text(
        f"---\ntools: [{werkzeug.WERKZEUG_NAME}]\n---\n\nLegt ab.\n", encoding="utf-8"
    )

    with TestClient(app_erstellen(config)) as client:
        client.headers["X-Sitzungsschluessel"] = client.app.state.sitzungsschluessel
        client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
        provider_setzen(
            client,
            MockProvider(mock_endpunkt("test"), werkzeugaufrufe=aufrufe, haeppchen=[]),
        )
        kennung = client.post(
            "/api/v1/jobs", json={"agent": "ableger", "task": "Los"}
        ).json()["id"]
        frist = time.time() + 8
        while time.time() < frist:
            daten = client.get(f"/api/v1/jobs/{kennung}").json()
            if daten.get("state") in {"fertig", "abgebrochen", "gescheitert", "unterbrochen"}:
                break
            time.sleep(0.05)
    return daten


def _zeile_lesen(config, auftrag_id):
    """The ``auftraege`` row as it stands on disk after the run — the same
    place ``nach_neustart_fortsetzen`` reads it from at the next start."""
    from app.db import Database, repositories_erstellen

    repos = repositories_erstellen(Database(str(config.datenbankpfad)))
    return repos.auftraege.holen(auftrag_id).zwischenstand or ""


# --- The old record cannot land on top of a delivery ----------------


def test_die_uebernahme_ueberschreibt_keine_gleichzeitige_ablage(config, monkeypatch):
    """``_altbestand_uebernehmen`` tested "the folder has no record yet" and
    then moved the old one in — outside the lock every other write is under.

    A delivery landing between the two had its record replaced by the old
    folder's: the entry gone, its file left in the folder as a nameless blob.
    And from then on the test above is false forever, so the old record is
    never adopted at all — the old entries are silently gone too.

    The window is narrow, so it is opened on purpose rather than raced for: a
    delivery is started inside the move itself. With the check and the move
    under one lock the delivery waits and lands on the adopted record; without
    it, it writes its own record and the move lands on top of that.
    """
    daten = Path(config.app.data_dir)
    ordner = daten / ORDNER
    ordner.mkdir(parents=True, exist_ok=True)
    (daten / DATEI).write_text(
        json.dumps([{"id": "alt", "name": "alt.md", "datei": "alt.md",
                     "typ": "text/markdown", "groesse": 1, "agent": "",
                     "abgelegt": "2026-09-02T00:00:00+00:00"}]),
        encoding="utf-8",
    )

    dock = AgentenDock(ordner)
    echt = os.replace
    faeden: list[threading.Thread] = []

    def dazwischen(quelle, ziel):
        # Only the move itself opens the window — the delivery's own rename
        # (side file, then rename) must not open a second one. Both go
        # through the one way of renaming (app/atomic_file.py), so the
        # window is opened there.
        if not faeden:
            faden = threading.Thread(target=lambda: dock.ablegen("neu.md", b"x"))
            faeden.append(faden)
            faden.start()
            time.sleep(0.3)
        return echt(quelle, ziel)

    monkeypatch.setattr(atomic_file.os, "replace", dazwischen)
    dock_fuer(config)
    monkeypatch.undo()
    faeden[0].join(10)

    assert {e["name"] for e in dock.alle()} == {"alt.md", "neu.md"}


# --- Nothing broken ---------------------------------------------------------


def test_die_schuld_bleibt_bezahlbar(config, monkeypatch):
    """The whole point of the text way, and the half a database column could
    never have: a continuation that is told what it owes can DELIVER it. If
    this ever goes red the fix has turned into a trap that paints a chain
    red for good."""
    import app.agentendock as modul

    monkeypatch.setattr(modul, "MAX_BYTES", 8)
    eintrag = _eintrag(
        task=zwischenstand.naechste_aufgabe("Los", "## Done\n- eins", ["daten.csv"]),
        notiz="Reported so far:\n- mail from A\n- mail from B",
        notiz_am="2026-09-02T10:00:00",
    )
    daten = _lauf_mit_ablage(
        config, [_ablage_ruf("a", 4, name="daten.csv")], task=auftragstext(eintrag)
    )

    assert daten["state"] == "fertig"
    assert _ende(daten) == ["fertig"]
    assert {e["name"] for e in dock_fuer(config).alle()} == {"daten.csv"}


def test_ohne_schuld_steht_der_block_nirgends():
    """A run that owes nothing gets no heading at all — the block is not a
    fixture of every task text."""
    schlicht = zwischenstand.naechste_aufgabe("Los", "## Done\n- eins")
    assert zwischenstand.OFFENE_ABLAGE_KOPF not in schlicht
    assert zwischenstand.offene_ablagen_lesen(schlicht) == set()
    assert werkzeug.GRUND_NICHT_ABGELEGT  # the ending this block belongs to
