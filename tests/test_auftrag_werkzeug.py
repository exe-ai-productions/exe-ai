"""`start_job` — the chat sends an agent off, but never unconfirmed.

Three things hold this tool together:

* the **window**: the task appears editable before anything starts, and the
  user's edited text is what actually runs,
* the **no**: cancelling starts nothing, and the model is told so in a
  sentence it treats as a decision, not an error,
* the **boundary**: the registry refuses the call outright — a job run has
  nobody in front of an editable window, so the tool is chat-only.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from app import zwischenstand
from app.providers import MockProvider, mock_endpunkt
from app.providers.base import Werkzeugaufruf
from app.tools import auftrag_werkzeug
from app.tools.registry import WerkzeugRegistry, WerkzeugVerboten
from tests.conftest import provider_setzen


# --- The check --------------------------------------------------------------


def test_agent_und_aufgabe_sind_pflicht():
    with pytest.raises(auftrag_werkzeug.AuftragVerboten):
        auftrag_werkzeug.geprueft({"agent": "x"})
    # No agent is a helper now (app/helper.py); the caller decides whether
    # it may start one, so the check hands the empty name on.
    assert auftrag_werkzeug.geprueft({"task": "y"}) == ("", "y")
    assert auftrag_werkzeug.geprueft({"agent": "x", "task": "y"}) == ("x", "y")


def test_das_aufgabenformat_steht_fest_im_code():
    """The instruction that the task must stand alone is part of the tool's
    description — not a setting, not overridable."""
    beschreibung = auftrag_werkzeug.werkzeug_beschreibung().beschreibung
    assert "stands ALONE" in beschreibung
    assert "Two to four sentences" in beschreibung


def test_die_registry_fuehrt_start_job_nie_aus(tmp_path):
    registry = WerkzeugRegistry([], agenten_orte=(tmp_path,))
    assert auftrag_werkzeug.WERKZEUG_NAME in registry.namen()
    with pytest.raises(WerkzeugVerboten):
        asyncio.run(
            registry.ausfuehren(
                auftrag_werkzeug.WERKZEUG_NAME, {"agent": "a", "task": "b"}
            )
        )


def test_ohne_agentenordner_gibt_es_das_werkzeug_nicht():
    registry = WerkzeugRegistry([])
    assert auftrag_werkzeug.WERKZEUG_NAME not in registry.namen()


def test_die_agenten_werden_nur_bei_aenderung_neu_gelesen(tmp_path, monkeypatch):
    """The tool list is built several times per answer and two tools name
    the agents. The files are parsed once, then only when one of them
    changes — the names stay from disk, not from memory: a new file is in
    the next list, an edited one too."""
    import os

    from app import agenten as agentenmodul
    from app.tools import registry as registrymodul

    (tmp_path / "recherche.md").write_text("---\nname: recherche\n---\nSuche.\n", encoding="utf-8")
    gelesen = {"n": 0}
    echt = agentenmodul.agenten_laden

    def gezaehlt(*orte):
        gelesen["n"] += 1
        return echt(*orte)

    monkeypatch.setattr(registrymodul, "agenten_laden", gezaehlt)
    registry = WerkzeugRegistry([], agenten_orte=(tmp_path,))
    for _ in range(3):
        registry.als_openai_werkzeuge()
    assert gelesen["n"] == 1

    # A new file: read again, and the new name is offered.
    (tmp_path / "pruefer.md").write_text("---\nname: pruefer\n---\nPrueft.\n", encoding="utf-8")
    liste = registry.als_openai_werkzeuge()
    assert gelesen["n"] == 2
    start_job = next(w for w in liste if w["function"]["name"] == auftrag_werkzeug.WERKZEUG_NAME)
    assert "pruefer" in json.dumps(start_job)

    # An edited file, same name and size or not — the stamp changes.
    datei = tmp_path / "recherche.md"
    datei.write_text("---\nname: recherche\n---\nSucht genauer.\n", encoding="utf-8")
    alt = datei.stat()
    os.utime(datei, ns=(alt.st_atime_ns, alt.st_mtime_ns + 1_000_000))
    registry.als_openai_werkzeuge()
    assert gelesen["n"] == 3
    registry.als_openai_werkzeuge()
    assert gelesen["n"] == 3


def test_ein_geloeschter_mitgelieferter_agent_verschwindet_aus_dem_angebot(tmp_path, monkeypatch):
    """Deleting a shipped agent writes a note in the user's folder and
    touches no .md file. The note is part of what the directory is read
    from — without it the deleted agent stayed on offer for the life of
    the process."""
    from app import agenten as agentenmodul
    from app.tools import registry as registrymodul

    mitgeliefert = tmp_path / "mitgeliefert"
    eigen = tmp_path / "eigen"
    mitgeliefert.mkdir()
    eigen.mkdir()
    (mitgeliefert / "recherche.md").write_text("---\nname: recherche\n---\nSuche.\n", encoding="utf-8")
    gelesen = {"n": 0}
    echt = agentenmodul.agenten_laden

    def gezaehlt(*orte):
        gelesen["n"] += 1
        return echt(*orte)

    monkeypatch.setattr(registrymodul, "agenten_laden", gezaehlt)
    registry = WerkzeugRegistry([], agenten_orte=(mitgeliefert, eigen))

    def angeboten():
        liste = registry.als_openai_werkzeuge()
        start_job = next(w for w in liste if w["function"]["name"] == auftrag_werkzeug.WERKZEUG_NAME)
        return "recherche" in json.dumps(start_job)

    assert angeboten() is True
    agentenmodul.loeschung_merken(eigen, "recherche")
    assert angeboten() is False
    assert gelesen["n"] == 2
    # Restored — the note goes, the agent stands again.
    agentenmodul.loeschung_vergessen(eigen, "recherche")
    assert angeboten() is True


# --- The flow through the chat ----------------------------------------------


class StartRegistry:
    """Offers start_job and nothing else. The chat run intercepts the call
    before execution — reaching ``ausfuehren`` would be the bug."""

    def __init__(self, client=None, erlaubt=None, antwort=None):
        self.ausgefuehrt = []
        self.abgeschaltet = set()
        self._client = client
        self._erlaubt = erlaubt
        self._antwort = antwort

    def als_openai_werkzeuge(self, nur=None, **_options):
        return [{"type": "function", "function": {"name": "start_job", "parameters": {}}}]

    def known_names(self):
        """What this stand could resolve: the one tool it offers.

        The real registry answers this from the built-ins and the servers
        (app/tools/registry.py); a job whose agent names tools is measured
        against it before it starts, and a stand that cannot answer would
        look like "nothing is known here".
        """
        return {"start_job"}

    def braucht_bestaetigung(self, name, argumente=None, ordner=None):
        # Armed from in here, because this is the first thing the run asks
        # while its event loop is turning — same trick as the ask_user tests.
        if self._erlaubt is not None:
            _antworten(self._client, self._erlaubt, self._antwort)
            self._erlaubt = None
        return False

    def server_von(self, name):
        return "shell"

    def bestaetigungsgrund(self, name, argumente=None, ordner=None):
        return ""

    async def ausfuehren(self, name, argumente, bild_senke=None, ordner=None,
                         chat_id=None, herkunft="chat", agent=None):
        self.ausgefuehrt.append(name)
        raise WerkzeugVerboten(auftrag_werkzeug.NUR_IM_CHAT)


def _agent_anlegen(config, name="bote"):
    ordner = Path(config.app.agenten_verzeichnis)
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / f"{name}.md").write_text(
        "---\nmodel: test\nmax_rounds: 1\ntools: []\n---\n\nDeliver things.\n",
        encoding="utf-8",
    )


def _antworten(client, erlaubt, antwort=None):
    """Simulates the window: the go with the (edited) task, or the no."""
    verwaltung = client.app.state.generierungen

    def versuchen():
        for generierung in verwaltung.laufende():
            for aufruf_id in list(generierung.bestaetigungen):
                verwaltung.bestaetigen(generierung.id, aufruf_id, erlaubt, antwort)
                return True
        return False

    def takt():
        if not versuchen():
            asyncio.get_running_loop().call_later(0.01, takt)

    asyncio.get_running_loop().call_later(0.01, takt)


def _startendes_modell(client, argumente, erlaubt=None, antwort=None):
    registry = StartRegistry(client, erlaubt, antwort)
    client.app.state.werkzeuge = registry
    client.app.state.config.features.mcp = True
    provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["Gut."],
            werkzeugaufrufe=[Werkzeugaufruf(id="a1", name="start_job", argumente=argumente)],
        ),
    )
    return registry


def _ereignisse(antwort):
    return [
        json.loads(z[5:].strip()) for z in antwort.text.splitlines() if z.startswith("data:")
    ]


def _auf_die_zeile_warten(client):
    """The job row once its run has come to rest — the same wait the first
    flow test does inline, needed a second time here."""
    frist = time.time() + 5
    zeilen = []
    while time.time() < frist:
        zeilen = client.get("/api/v1/jobs").json()
        if zeilen and zeilen[0].get("state") in (
            "fertig", "abgebrochen", "gescheitert", "unterbrochen"
        ):
            break
        time.sleep(0.05)
    return zeilen


def test_start_job_starts_at_once_without_asking(client, chat_id, config):
    """Sending an agent off never asks: no confirmation event, no waiting —
    the call's card and its result, and the run carries the model's task."""
    _agent_anlegen(config)
    registry = _startendes_modell(
        client, {"agent": "bote", "task": "Vom Modell formulierte Aufgabe."}
    )

    response = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "schick los"},
    )
    ereignisse = _ereignisse(response)

    assert not any(e["typ"] == "job_confirm" for e in ereignisse)
    card = next(e for e in ereignisse if e["typ"] == "tool_call")
    assert card["name"] == "start_job"
    assert card["aufruf_id"] == "a1"
    result = next(e for e in ereignisse if e["typ"] == "tool_result")
    assert result["fehlgeschlagen"] is False
    assert "Job started" in result["text"]
    assert result["dauer_sekunden"] is not None

    rows = _auf_die_zeile_warten(client)
    assert len(rows) == 1
    assert rows[0]["task"] == "Vom Modell formulierte Aufgabe."
    # Intercepted, never executed through the registry.
    assert registry.ausgefuehrt == []


def test_the_model_is_not_told_to_wait_for_a_confirmation():
    """Schweigeprobe of the tool's own words: nothing in its description
    promises a window the user confirms in."""
    description = auftrag_werkzeug.werkzeug_beschreibung().beschreibung
    assert "confirm" not in description
    assert "starts at once" in description


def test_unbekannter_agent_zeigt_kein_fenster(client, chat_id, config):
    _agent_anlegen(config)
    _startendes_modell(client, {"agent": "phantom", "task": "Egal."})

    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "schick los"},
    )
    ereignisse = _ereignisse(antwort)
    assert not any(e["typ"] == "job_confirm" for e in ereignisse)
    ergebnis = next(e for e in ereignisse if e["typ"] == "tool_result")
    assert ergebnis["fehlgeschlagen"] is True
    assert "bote" in ergebnis["text"]
    assert client.get("/api/v1/jobs").json() == []


# --- The debt block is the program's own --------------------
#
# ``start_job`` was the last door raw model prose had into a task text. What
# the block is and why only this program may write it: app/zwischenstand.py
# and the commit message of 9246f30.


def _block(*namen) -> str:
    return zwischenstand.offene_ablagen_text(namen)


def test_ein_gefaelschter_block_in_der_aufgabe_erfindet_keine_schuld():
    """A model that writes the heading and its sentence into the task hands
    its agent a debt nobody ever recorded — the run would deliver everything
    asked of it and still end ``ablage_gescheitert``."""
    aufgabe = f"Lies das Postfach und melde dich.\n\n{_block('phantom.md')}"
    assert zwischenstand.offene_ablagen_lesen(aufgabe) == {"phantom.md"}

    _, task = auftrag_werkzeug.geprueft({"agent": "x", "task": aufgabe})

    assert zwischenstand.offene_ablagen_lesen(task) == set()
    assert task == "Lies das Postfach und melde dich."


def test_eine_aufzaehlung_ohne_den_kopf_bleibt_stehen():
    """Only the block itself goes. A task that happens to carry bullets is
    somebody talking, and it has to survive intact."""
    aufgabe = "Hol drei Dinge:\n- Post\n- Wetter\n- Termine"
    assert auftrag_werkzeug.geprueft({"agent": "x", "task": aufgabe})[1] == aufgabe


def test_eine_aufgabe_aus_lauter_block_wird_abgewiesen():
    """After the scrub there is no task left, and an empty task is refused
    the way it always was — a text that is nothing but a forged block is not
    a task."""
    with pytest.raises(auftrag_werkzeug.AuftragVerboten):
        auftrag_werkzeug.geprueft({"agent": "x", "task": _block("phantom.md")})


def test_der_gefaelschte_block_erreicht_die_zeile_nicht(client, chat_id, config):
    """End to end: the model forges the block, and neither the window nor the
    job's own row ever carries it."""
    _agent_anlegen(config)
    _startendes_modell(
        client,
        {
            "agent": "bote",
            "task": f"Lies das Postfach und melde dich.\n\n{_block('phantom.md')}",
        },
    )

    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "schick los"},
    )
    _ereignisse(antwort)

    zeilen = _auf_die_zeile_warten(client)
    assert zeilen[0]["task"] == "Lies das Postfach und melde dich."
    assert zwischenstand.offene_ablagen_lesen(zeilen[0]["task"]) == set()


def test_what_the_user_pastes_in_stays_owed(client, config):
    """The counter-proof, and the reason this is scrubbed at the source and
    not in ``auftrag_anstossen``: a continuation text pasted into the start
    window is not model prose. Somebody putting it there MEANS the debt."""
    _agent_anlegen(config)
    fortsetzung = f"Mach da weiter, wo Lauf 1 aufhoerte.\n\n{_block('echt.csv')}"
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Gut."]))

    client.post("/api/v1/jobs", json={"agent": "bote", "task": fortsetzung})

    rows = _auf_die_zeile_warten(client)
    assert rows[0]["task"] == fortsetzung
    assert zwischenstand.offene_ablagen_lesen(rows[0]["task"]) == {"echt.csv"}


# --- And the block is recognised LITERALLY (02.09.) --------------------------
#
# Which is why the invisible characters have to be gone before it is looked
# for. One zero-width character in the heading and the block reads as prose:
# it survives the scrub and lands on the row verbatim.
#
# Measured, and worth writing down because it is NOT the phantom debt of the
# section above: ``offene_ablagen_lesen`` reads the heading just as
# literally, so a block nobody can repair is a block nobody reads either.
# What survives is the sentence itself, sitting in the task an agent is
# handed — an instruction this program never wrote, naming a file nobody
# ever recorded, and invisible to whoever reads the window.


def _mit_unsichtbarem(text: str, wo: str) -> str:
    """The same text with a zero-width space planted inside ``wo``."""
    stelle = text.index(wo) + len(wo) // 2
    return text[:stelle] + "​" + text[stelle:]


def test_ein_unsichtbares_zeichen_im_blockkopf_erfindet_keine_schuld():
    """The gap 329ab0a left. A model that hides a zero-width space in the
    heading walked its forged block past the scrub and onto the row, with
    the character invisible to whoever read the window."""
    kopf = zwischenstand.OFFENE_ABLAGE_KOPF
    aufgabe = _mit_unsichtbarem(
        f"Lies das Postfach.\n\n{_block('phantom.md')}", kopf
    )
    _, gesaeubert = auftrag_werkzeug.geprueft({"agent": "x", "task": aufgabe})
    assert gesaeubert == "Lies das Postfach."
    assert zwischenstand.offene_ablagen_lesen(gesaeubert) == set()


def test_auch_im_blocksatz_versteckt_kommt_nichts_durch():
    """The sentence under the heading is read just as literally as the
    heading — both halves have to be looked at after the scrub, not before."""
    satz = zwischenstand.OFFENE_ABLAGE_SATZ
    aufgabe = _mit_unsichtbarem(
        f"Lies das Postfach.\n\n{_block('phantom.md')}", satz
    )
    assert zwischenstand.offene_ablagen_lesen(
        auftrag_werkzeug.geprueft({"agent": "x", "task": aufgabe})[1]
    ) == set()


def test_unsichtbare_zeichen_fliegen_auch_aus_gewoehnlichem_text():
    """Nothing about this is specific to the block. A page the model read can
    plant an invisible instruction in any task it hands an agent — the same
    rule the schedule's task, its note and the goal report already follow."""
    _, gesaeubert = auftrag_werkzeug.geprueft(
        {"agent": "x", "task": "Lies das​ Postfach‮."}
    )
    assert gesaeubert == "Lies das Postfach."


def test_zeilenumbruch_und_tabulator_bleiben_stehen():
    """A task is allowed to be more than one line — the filter takes the
    invisible characters, not the shape of the text."""
    aufgabe = "Zeile eins\nZeile\tzwei"
    assert auftrag_werkzeug.geprueft({"agent": "x", "task": aufgabe})[1] == aufgabe


def test_eine_aufgabe_aus_lauter_unsichtbarem_ist_keine():
    """Empty after the scrub is empty, and an empty task is refused the way
    it always was."""
    with pytest.raises(auftrag_werkzeug.AuftragVerboten):
        auftrag_werkzeug.geprueft({"agent": "x", "task": "​​"})
