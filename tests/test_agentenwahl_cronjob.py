"""Reaching the agent one meant, through the tool the model actually calls.

The unit rules live beside the resolver; this is the same four cases seen
from the outside — the refusal a caller reads, the capitals it may use, and
the list it can no longer be missing.
"""

from __future__ import annotations

from pathlib import Path

from app.agenten import agenten_laden
from app.tools import cronjob as cronjob_modul
from app.tools.cronjob import CronjobVerboten, ausfuehren

import pytest


def agentdatei(verzeichnis: Path, name: str, kopf: str = "model: test") -> None:
    verzeichnis.mkdir(parents=True, exist_ok=True)
    (verzeichnis / f"{name}.md").write_text(
        f"---\n{kopf}\n---\n\nPrompt.\n", encoding="utf-8"
    )


def vier_agenten(ordner: Path) -> None:
    agentdatei(ordner, "erinnerung", "tools: []")
    agentdatei(ordner, "exe-agent")
    agentdatei(ordner, "nacht-review")
    agentdatei(ordner, "recherche")


async def test_ein_falscher_name_bekommt_die_echten_genannt(repos, tmp_path):
    vier_agenten(tmp_path)
    with pytest.raises(CronjobVerboten) as fehler:
        await ausfuehren(
            {"action": "create", "time": "08:00", "task": "x", "agent": "reminder"},
            repos.cronjobs, (tmp_path,), herkunft="chat", agent=None,
        )
    text = str(fehler.value)
    for name in ("erinnerung", "exe-agent", "nacht-review", "recherche"):
        assert name in text, text


async def test_grosses_R_wird_angenommen_und_klein_gespeichert(repos, tmp_path):
    vier_agenten(tmp_path)
    await ausfuehren(
        {"action": "create", "time": "08:00", "task": "x", "agent": "Recherche"},
        repos.cronjobs, (tmp_path,), herkunft="chat", agent=None,
    )
    (eintrag,) = repos.cronjobs.auflisten()
    assert eintrag.agent == "recherche"


async def test_auch_das_umhaengen_nimmt_die_schreibweise(repos, tmp_path):
    vier_agenten(tmp_path)
    await ausfuehren(
        {"action": "create", "time": "08:00", "task": "x"},
        repos.cronjobs, (tmp_path,), herkunft="chat", agent=None,
    )
    (eintrag,) = repos.cronjobs.auflisten()
    await ausfuehren(
        {"action": "update", "id": eintrag.id, "agent": "Nacht-Review"},
        repos.cronjobs, (tmp_path,), herkunft="chat", agent=None,
    )
    (nachher,) = repos.cronjobs.auflisten()
    assert nachher.agent == "nacht-review"


def test_das_schema_traegt_die_namen_und_sagt_wer_nichts_kann(tmp_path):
    vier_agenten(tmp_path)
    agenten = agenten_laden(tmp_path)
    beschreibung = cronjob_modul.werkzeug_beschreibung(agenten)
    feld = beschreibung.schema["properties"]["agent"]
    assert feld["enum"] == ["erinnerung", "exe-agent", "nacht-review", "recherche"]
    # Leaving it out runs with no agent, and the field says so, with what
    # such a run may and may not do.
    assert "with no agent" in feld["description"]
    assert "except asking the user" in feld["description"]
    # And the one that can only answer says so before it is picked.
    assert "erinnerung (answers only, no tools)" in feld["description"]
    # Silence test: an agent with tools carries no such remark.
    assert "recherche (answers" not in feld["description"]


def test_ohne_agentenordner_traegt_das_feld_keine_liste():
    """A service with no agent folders at all offers no list rather than an
    empty one that would read as 'there are none'."""
    feld = cronjob_modul.werkzeug_beschreibung(None).schema["properties"]["agent"]
    assert "enum" not in feld
