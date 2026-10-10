"""Two decisions of 02.09., in one file because both are about a rule the
program had written down in one place and then quietly broken in five or six
others.

**"log" means silent.** Five notifications used to go out no matter what
``deliver`` said, and the code said so in as many words. They are the endings
nobody would otherwise notice — a schedule waiting ten minutes for a model, a
script that cannot start, the failure limit, a one-off that found nothing, a
goal nobody has reported in N runs — and every one of those reasons is about
being FINDABLE, not about popping up. The log line, the entry's own state and
the lamp are written before the notification is ever reached, and none of them
moved. What moved is that ``log`` now means what it says, sound included.

**The debt block is the program's own, on the two ways ``9246f30`` missed.**
The block (``app/zwischenstand.py``) is how a run tells its continuation which
deliveries it still owes the agent dock. Every piece of model prose that goes
into a task text is scrubbed of it first — that was the point of ``9246f30``,
and two ways in were not covered: the row a service restart reads the debt back
out of, and the task text of a cron entry a model wrote itself.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import cronablauf, cronmeldung, skriptlauf, zwischenstand
from app.db import Database, repositories_erstellen
from app.main import app_erstellen
from app.providers import MockProvider, mock_endpunkt
from app.providers.base import Stueck
from app.tools import agentendock as ablage_werkzeug
from app.tools.cronjob import ausfuehren as cronjob_ausfuehren
from tests.conftest import provider_setzen
from tests.test_agentendock import _ablage_ruf

AUFGABE = "Ins Postfach sehen"


# --- Aufgabe 1 · "log" heisst still -----------------------------------------


@pytest.fixture
def befehle(monkeypatch):
    """Every command ``cronmeldung`` would run, recorded instead of run.

    One level below ``melden`` on purpose: the sound and the notification are
    two separate subprocess calls inside it (``afplay``, ``osascript``), and
    the decision names both. Patching ``melden`` would prove only that the
    module was not entered; this proves that neither half of it happened.
    """
    gesehen: list[str] = []
    monkeypatch.setattr(cronmeldung.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(cronmeldung.sys, "platform", "darwin")
    monkeypatch.setattr(
        cronmeldung.subprocess, "run",
        lambda befehl, **kwargs: gesehen.append(befehl[0])
        or type("Ergebnis", (), {"returncode": 0})(),
    )
    return gesehen


def eintrag_anlegen(repos, **felder):
    felder.setdefault("zeitplan", "*/15 * * * *")
    return repos.cronjobs.erstellen(
        agent="a", task=AUFGABE, herkunft="chat", **felder
    )


LAGEN = ("warten", "skript", "grenze", "einmalig", "ohne_ziel")


async def _lage_ausloesen(lage: str, repos, deliver: str) -> str:
    """One of the five, driven to the exact point where it announces.

    Returns the entry's id so the caller can read the state back — because
    that is the other half of the decision: silent is not invisible.
    """
    from datetime import timedelta

    from app.db.connection import jetzt_iso

    jetzt = cronablauf.datetime.fromisoformat(jetzt_iso().replace("Z", "+00:00"))

    if lage == "warten":
        eintrag = eintrag_anlegen(repos, deliver=deliver)
        # Called directly rather than through a tick of the clock: the
        # notification is ten minutes into an outage, and a test that waited
        # for them would be a test nobody runs.
        await cronablauf._warten_vermerken(eintrag, jetzt)
        await cronablauf._warten_vermerken(
            eintrag, jetzt + timedelta(seconds=cronablauf.WARTEMELDUNG_SEKUNDEN)
        )
        return eintrag.id

    if lage == "skript":
        eintrag = eintrag_anlegen(repos, deliver=deliver, skript="sicherung.sh")
        fehlt = skriptlauf.SkriptVerboten(
            "fehler.skript_fehlt", name="sicherung.sh", ordner="/wo/anders"
        )
        await cronablauf._skriptfehler_vermerken(eintrag, fehlt, jetzt)
        await cronablauf._skriptfehler_vermerken(
            eintrag, fehlt,
            jetzt + timedelta(seconds=cronablauf.WARTEMELDUNG_SEKUNDEN),
        )
        return eintrag.id

    if lage == "grenze":
        eintrag = eintrag_anlegen(repos, deliver=deliver, fehlergrenze=1)
        await cronablauf.ausgang_verbuchen(
            repos, eintrag.id, AUFGABE, erfolgreich=False
        )
        return eintrag.id

    if lage == "einmalig":
        eintrag = eintrag_anlegen(
            repos, deliver=deliver, einmalig=True, ziel="Eine Mail von Müller"
        )
        repos.cronjobs.aktiv_setzen(eintrag.id, False)  # a fired one-off
        await cronablauf.ziel_verbuchen(
            repos, eintrag.id, AUFGABE, bericht=None, erfolgreich=True
        )
        return eintrag.id

    eintrag = eintrag_anlegen(
        repos, deliver=deliver, fehlergrenze=2, ziel="Eine Mail von Müller"
    )
    for _ in range(2):
        await cronablauf.ziel_verbuchen(
            repos, eintrag.id, AUFGABE, bericht=None, erfolgreich=True
        )
    return eintrag.id


@pytest.mark.parametrize("lage", LAGEN)
async def test_auf_log_kommt_keine_mitteilung_und_kein_ton(lage, repos, befehle, caplog):
    """The decision itself, one case at a time.

    Each of the five had its own comment saying it went out "no matter what
    ``deliver`` says". Together they meant somebody who asked for a quiet
    schedule still got a system notification and a sound out of it — and on a
    machine running a second copy of this program, out of that one too.
    """
    with caplog.at_level("INFO"):
        eintrag_id = await _lage_ausloesen(lage, repos, "log")

    assert befehle == []
    # And the reason is still there to be found: the log took it either way.
    assert caplog.records
    assert repos.cronjobs.holen(eintrag_id) is not None


@pytest.mark.parametrize("lage", LAGEN)
async def test_auf_announce_kommt_sie_weiterhin_genau_einmal(lage, repos, befehle):
    """The counter-proof, and the half that must not have moved: on
    ``announce`` all five still speak, with the sound, and exactly once per
    thing — which is the rule four separate builds worked on last night."""
    await _lage_ausloesen(lage, repos, "announce")

    assert befehle == ["afplay", "osascript"]


async def test_still_heisst_nicht_unsichtbar(repos, befehle):
    """The other half of the decision, spelled out: everything the five
    situations do BESIDES announcing is untouched on ``log``.

    This is the line the whole build stands on. Take it away and "log" would
    mean a schedule can die without leaving a trace anywhere — which is what
    the five were built to prevent, and rightly."""
    warten = await _lage_ausloesen("warten", repos, "log")
    skript = await _lage_ausloesen("skript", repos, "log")
    grenze = await _lage_ausloesen("grenze", repos, "log")

    assert befehle == []
    # The mask's own "waiting for a model" state, per entry.
    assert cronablauf.wartet_auf_modell(warten) is True
    # The sentence the user needs to go and fix the script, in their own
    # language — the refusal travels as a catalogue key now.
    assert "sicherung.sh" in (cronablauf.skript_nicht_startbar(skript, "de") or "")
    assert "There is no script" in (cronablauf.skript_nicht_startbar(skript, "en") or "")
    # And the entry that ran itself to death really is off.
    frisch = repos.cronjobs.holen(grenze)
    assert frisch.aktiv is False
    assert frisch.fehlversuche == 1


async def test_der_abschlussfilter_verhaelt_sich_unveraendert(repos, befehle):
    """``melde_wenn_faellig`` is where the ``log`` filter always lived, and it
    is the one of the six that is not supposed to change. Same answer on both
    settings, and the goal exemption still its own."""
    still = eintrag_anlegen(repos, deliver="log")
    await cronablauf.melde_wenn_faellig(repos, still.id, AUFGABE, erfolgreich=True)
    assert befehle == []

    laut = eintrag_anlegen(repos, deliver="announce")
    await cronablauf.melde_wenn_faellig(repos, laut.id, AUFGABE, erfolgreich=True)
    assert befehle == ["afplay", "osascript"]

    befehle.clear()
    # An entry with a goal is exempt whatever ``deliver`` says — that filter
    # is this function's own and did not move.
    mit_ziel = eintrag_anlegen(repos, deliver="announce", ziel="Eine Mail")
    await cronablauf.melde_wenn_faellig(repos, mit_ziel.id, AUFGABE, erfolgreich=True)
    assert befehle == []


async def test_die_grenze_meldet_weiterhin_genau_einmal(repos, befehle):
    """The "exactly once" rule of e959e99, on the path this build touched:
    the limit speaks on the run that reaches it, and the run's own closing
    notification steps aside for it (``schon_gemeldet``)."""
    eintrag = eintrag_anlegen(repos, deliver="announce", fehlergrenze=1)

    angehalten = await cronablauf.ausgang_verbuchen(
        repos, eintrag.id, AUFGABE, erfolgreich=False
    )
    await cronablauf.melde_wenn_faellig(
        repos, eintrag.id, AUFGABE, erfolgreich=False, schon_gemeldet=angehalten
    )

    assert angehalten is True
    assert befehle == ["afplay", "osascript"]


# --- Aufgabe 2 · the two ways into the debt block ---------------------------


BLOCK = zwischenstand.offene_ablagen_text(["phantom.md"])


def _ableger_schreiben(config) -> None:
    ordner = Path(config.app.agenten_verzeichnis)
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "ableger.md").write_text(
        f"---\ntools: [{ablage_werkzeug.WERKZEUG_NAME}]\n---\n\nLegt ab.\n",
        encoding="utf-8",
    )


def _lauf(config, *, task="Los", haeppchen=None, aufrufe=()):
    """One job on the real service, run to its end — the same harness the
    debt-block tests of ``9246f30`` use."""
    config.features.mcp = True
    config.mcp.servers_file = str(Path(config.app.data_dir) / "keine_server.json")
    _ableger_schreiben(config)

    with TestClient(app_erstellen(config)) as client:
        client.headers["X-Sitzungsschluessel"] = client.app.state.sitzungsschluessel
        client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
        provider_setzen(
            client,
            MockProvider(
                mock_endpunkt("test"),
                werkzeugaufrufe=list(aufrufe),
                **({} if haeppchen is None else {"haeppchen": haeppchen}),
            ),
        )
        kennung = client.post(
            "/api/v1/jobs", json={"agent": "ableger", "task": task}
        ).json()["id"]
        frist = time.time() + 8
        while time.time() < frist:
            daten = client.get(f"/api/v1/jobs/{kennung}").json()
            if daten.get("state") in {
                "fertig", "abgebrochen", "gescheitert", "unterbrochen"
            }:
                break
            time.sleep(0.05)
    return daten


def _repos_auf_platte(config):
    """The database as the next service start finds it — the restart path
    reads the row from disk, not from the client that just wrote it."""
    return repositories_erstellen(Database(str(config.datenbankpfad)))


# The restart reads the job row RAW


def test_ein_nachgeplapperter_block_ueberlebt_den_neustart_nicht(config):
    """A model that echoes the block into its own text, then ``kill -9``.

    Measured before the fix, with ``nach_neustart_fortsetzen`` really called:
    the continuation owed ``{'phantom.md'}`` — as a block of the PROGRAM, so
    the run would open owing a file nobody ever recorded, be unable to pay
    it, and end ``ablage_gescheitert``. The context-overflow path returned
    ``set()`` for the very same text, because ``naechste_aufgabe`` scrubs the
    status on the way in. The restart read the row before any of that.

    The row itself is what is checked, not only the continuation: that is the
    thing a hard restart finds, and the fix is that the last block on it is
    always the program's own.
    """
    daten = _lauf(config, haeppchen=["Fertig.\n\n", BLOCK])
    assert daten["state"] == "fertig"

    repos = _repos_auf_platte(config)
    zeile = repos.auftraege.holen(daten["id"]).zwischenstand or ""
    assert "Fertig." in zeile  # the model's own words are not touched
    assert zwischenstand.offene_ablagen_lesen(zeile) == set()

    # And now the restart, on the row as it stands on disk. The row is put
    # back on ``laeuft`` first, because that is the state a ``kill -9``
    # leaves behind and the only one ``beim_start_aufraeumen`` picks up —
    # a TestClient always shuts its runs down cleanly. The live measurement
    # of this build did the real thing with a real signal.
    repos.auftraege.zustand_setzen(daten["id"], "laeuft")
    repos.auftraege.beim_start_aufraeumen()
    assert zwischenstand.nach_neustart_fortsetzen(config, repos) == 1
    (kette,) = repos.cronjobs.auflisten()
    assert zwischenstand.offene_ablagen_lesen(kette.task) == set()
    assert "phantom.md" not in kette.task


def test_eine_echte_schuld_ueberlebt_den_neustart_weiterhin(config, monkeypatch):
    """The counter-check without which the fix would be a loss: a run that
    really was refused a delivery, cut off in the same moment, still comes
    back owing the file. That case
    has to keep working with the scrubbing in front of it.
    """
    import app.agentendock as modul

    monkeypatch.setattr(modul, "MAX_BYTES", 8)
    daten = _lauf(
        config,
        haeppchen=["Konnte nicht abgeben.\n\n", BLOCK],
        aufrufe=[_ablage_ruf("zugross", 40, name="echt.csv")],
    )

    repos = _repos_auf_platte(config)
    zeile = repos.auftraege.holen(daten["id"]).zwischenstand or ""
    # The program's own block, and only its own name in it.
    assert zwischenstand.offene_ablagen_lesen(zeile) == {"echt.csv"}

    repos.auftraege.zustand_setzen(daten["id"], "laeuft")
    repos.auftraege.beim_start_aufraeumen()
    assert zwischenstand.nach_neustart_fortsetzen(config, repos) == 1
    (kette,) = repos.cronjobs.auflisten()
    assert zwischenstand.offene_ablagen_lesen(kette.task) == {"echt.csv"}


# The entry's own task text


async def test_ein_gefaelschter_block_kommt_nicht_auf_einen_cron_eintrag(repos, tmp_path):
    """A model writing the block into a schedule it sets itself is the bitter
    shape of this hole: a firing glues the entry's task in FRONT of note and
    goal, so the faked block would be the last genuine one of every single
    run — each opening owing a file nobody recorded, ending
    ``ablage_gescheitert``, until ``fehlergrenze`` switched the entry off.

    Both ways onto the row, because both take model text: ``create`` and
    ``update``.
    """
    await cronjob_ausfuehren(
        {"action": "create", "time": "08:00", "task": f"Postfach lesen\n\n{BLOCK}"},
        repos.cronjobs, (tmp_path,), herkunft="chat", agent=None,
    )
    (eintrag,) = repos.cronjobs.auflisten()
    assert eintrag.task == "Postfach lesen"
    assert zwischenstand.offene_ablagen_lesen(eintrag.task) == set()

    await cronjob_ausfuehren(
        {"action": "update", "id": eintrag.id, "task": f"Neu\n\n{BLOCK}"},
        repos.cronjobs, (tmp_path,), herkunft="chat", agent=None,
    )
    frisch = repos.cronjobs.holen(eintrag.id)
    assert frisch.task == "Neu"
    assert zwischenstand.offene_ablagen_lesen(frisch.task) == set()


async def test_der_eintragstext_bleibt_sonst_woertlich(repos, tmp_path):
    """And nothing else is taken out. A schedule is a person's or an agent's
    own words, and the scrubbing may only ever remove what this program
    itself writes."""
    text = "## Done\n- eins\n- zwei\n\nWeiter so."
    await cronjob_ausfuehren(
        {"action": "create", "time": "08:00", "task": text},
        repos.cronjobs, (tmp_path,), herkunft="chat", agent=None,
    )
    (eintrag,) = repos.cronjobs.auflisten()
    assert eintrag.task == text


def test_ein_gefaelschter_block_im_auftragstext_erfindet_keine_schuld(config, repos, tmp_path):
    """The firing's own text, end to end: an entry made through the tool with
    a faked block in its task, glued together the way ``auftragstext`` glues
    it, carries no debt into the run."""
    import asyncio

    asyncio.run(
        cronjob_ausfuehren(
            {"action": "create", "time": "08:00",
             "task": f"Postfach lesen\n\n{BLOCK}"},
            repos.cronjobs, (tmp_path,), herkunft="chat", agent=None,
        )
    )
    (eintrag,) = repos.cronjobs.auflisten()
    repos.cronjobs.notiz_setzen(eintrag.id, "Reported so far:\n- mail from A")

    text = cronablauf.auftragstext(repos.cronjobs.holen(eintrag.id))
    assert zwischenstand.offene_ablagen_lesen(text) == set()

    # And the run that opens with it finishes, instead of failing over a file
    # nobody asked for.
    daten = _lauf(config, task=text)
    assert daten["state"] == "fertig"


class _TextDannAblage(MockProvider):
    """Text in round one, a refused delivery in round two, done in round three.

    The stock dummy answers tool calls on its FIRST pass only, so a run's
    text always arrives after every call it makes. The one write site this
    file could otherwise not reach needs the other order: text on the row
    already, and a delivery refused after it.
    """

    async def streamen(self, anfrage):
        self.durchlaeufe += 1
        if self.durchlaeufe == 1:
            # Text AND a call, or the run would end right here: a round with
            # no tool call in it is the last round.
            yield Stueck("content", f"Zwischenstand.\n\n{BLOCK}")
            yield Stueck(
                "tool_call", werkzeugaufrufe=[_ablage_ruf("klein", 4, name="ok.md")]
            )
            return
        if self.durchlaeufe == 2:
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[_ablage_ruf("zugross", 40, name="echt.csv")],
            )
            return
        yield Stueck("content", "Fertig.")


def test_keine_einzige_zeilenschreibung_traegt_einen_fremden_block(config, monkeypatch):
    """Every write onto the job row, not only the last one.

    A run writes its status twice per round in the worst case — once at the
    end of the round, once the moment a delivery is refused — and a ``kill
    -9`` can land after either. So it is not enough for the row to be right
    when the run finishes: it has to be right after every single write, or
    the restart reads a phantom out of the narrow window between two of them.

    Which is also why the second site is fixed at all. It is only reachable
    with text already on the row and a refusal after it, and the stock dummy
    cannot produce that order — hence the provider above.
    """
    import app.agentendock as modul
    from app.db.repositories.auftraege import AuftragRepository

    monkeypatch.setattr(modul, "MAX_BYTES", 8)
    geschrieben: list[str | None] = []
    echt = AuftragRepository.zwischenstand_setzen

    def mitschreiben(self, auftrag_id, text):
        geschrieben.append(text)
        return echt(self, auftrag_id, text)

    monkeypatch.setattr(AuftragRepository, "zwischenstand_setzen", mitschreiben)

    config.features.mcp = True
    config.mcp.servers_file = str(Path(config.app.data_dir) / "keine_server.json")
    _ableger_schreiben(config)
    with TestClient(app_erstellen(config)) as client:
        client.headers["X-Sitzungsschluessel"] = client.app.state.sitzungsschluessel
        client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
        provider_setzen(client, _TextDannAblage(mock_endpunkt("test")))
        kennung = client.post(
            "/api/v1/jobs", json={"agent": "ableger", "task": "Los"}
        ).json()["id"]
        frist = time.time() + 8
        while time.time() < frist:
            daten = client.get(f"/api/v1/jobs/{kennung}").json()
            if daten.get("state") in {
                "fertig", "abgebrochen", "gescheitert", "unterbrochen"
            }:
                break
            time.sleep(0.05)

    # The run really went through both sites, in that order.
    mit_text = [t for t in geschrieben if t]
    assert len(mit_text) >= 2
    assert any("Zwischenstand." in t for t in mit_text)
    # And not one of them ever named the file the model made up, while the
    # one it really owes is on every write after the refusal.
    for text in mit_text:
        assert "phantom.md" not in text
        assert zwischenstand.offene_ablagen_lesen(text) in (set(), {"echt.csv"})
    assert zwischenstand.offene_ablagen_lesen(mit_text[-1]) == {"echt.csv"}
