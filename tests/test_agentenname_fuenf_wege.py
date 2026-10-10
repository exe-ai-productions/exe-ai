"""One name, five doors, and they have to agree.

An agent name is looked up in five places: the cronjob tool on create and on
update, the job route, the job tool a chat calls, and the firing loop itself.
Fixing two of them would be worse than fixing none — the same word would
create a schedule and then fail to start the job that schedule fires, and
nothing along the way would say which of the two spellings the program
wanted.

So the rule lives at ``agenten_laden`` and every door is walked here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agenten import Agentenverzeichnis, agenten_laden

# Written the way German writes it, which is the spelling the whole finding
# started with: a model wrote `Recherche` and was refused four times.
GROSS = "Recherche"
ECHT = "recherche"


def vier_agenten(ordner: Path) -> None:
    for name, kopf in (
        ("erinnerung", "tools: []"),
        ("exe-agent", "model: test"),
        ("nacht-review", "model: test"),
        ("recherche", "model: test"),
    ):
        (ordner / f"{name}.md").write_text(
            f"---\n{kopf}\n---\n\nPrompt.\n", encoding="utf-8"
        )


@pytest.fixture
def agenten(tmp_path: Path) -> Agentenverzeichnis:
    vier_agenten(tmp_path)
    return agenten_laden(tmp_path)


# --- The rule itself, once -------------------------------------------------


def test_agenten_laden_gibt_das_verzeichnis_zurueck(agenten):
    """Not a plain dict any more, or none of the five below would inherit
    anything."""
    assert isinstance(agenten, Agentenverzeichnis)


def test_die_schluessel_bleiben_die_echten(agenten):
    """Only looking up forgives the case. What is stored is what is on disk,
    or one agent would land in the table under two names."""
    assert sorted(agenten) == ["erinnerung", "exe-agent", "nacht-review", "recherche"]


# --- The five doors --------------------------------------------------------
#
# Each is exercised the way its own code reaches the mapping: three ask with
# ``.get``, one with ``in``, and the cronjob tool asks for the real spelling
# because it has to store it.


def test_tor_1_cronjob_anlegen(agenten):
    """app/tools/cronjob.py, create."""
    assert agenten.echter_name(GROSS) == ECHT


def test_tor_2_cronjob_umhaengen(agenten):
    """app/tools/cronjob.py, update."""
    assert agenten.echter_name(GROSS) == ECHT
    assert GROSS in agenten


def test_tor_3_die_auftragsroute(agenten):
    """app/api/v1/auftraege.py — `agenten_laden(...).get(daten.agent)`, whose
    None becomes a 404."""
    gefunden = agenten.get(GROSS)
    assert gefunden is not None
    assert gefunden.name == ECHT


def test_tor_4_das_auftragswerkzeug_im_chat(agenten):
    """app/api/v1/generierung.py — the same `.get`, whose None becomes a
    refusal handed back to the model."""
    assert agenten.get(GROSS) is not None


def test_tor_5_das_feuern_selbst(agenten):
    """app/cronablauf.py — `agenten.get(eintrag.agent)`. This one decides
    whether a schedule that was accepted actually runs, which is exactly the
    split two half-fixes would have produced."""
    assert agenten.get(GROSS) is not None


# --- And all five refuse the same non-name ---------------------------------


def test_alle_fuenf_lehnen_dasselbe_ab(agenten):
    """Capitals are forgiven and nothing else is — in every door at once, so
    a name cannot be good enough for one and not for the next."""
    for kein_name in ("reminder", "recherchen", "exe agent"):
        assert agenten.echter_name(kein_name) is None, kein_name
        assert kein_name not in agenten, kein_name
        assert agenten.get(kein_name) is None, kein_name
