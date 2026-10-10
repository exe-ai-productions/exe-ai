"""Finding the agent somebody meant.

From a chat that could not create a schedule at all: the model tried
``reminder``, was refused, tried ``Recherche``, was refused again, and then
said the real problem out loud — it did not know which agents exist. Both
guesses were reasonable. The tool's own text called the shipped agent "the
shipped reminder agent" while it is named ``erinnerung``, and ``Recherche``
is how the word is spelled in German, while the names come from file names
and are all lower case.

Four things are tested, and one of them is a refusal that has to STAY a
refusal: capitals are forgiven, and nothing else is.
"""

from __future__ import annotations

from types import SimpleNamespace

from app import agentenname
from app.agenten import Agentenverzeichnis

VORHANDEN = Agentenverzeichnis(
    dict.fromkeys(("erinnerung", "exe-agent", "nacht-review", "recherche"), None)
)


# --- Capitals, and only capitals -------------------------------------------


def test_die_schreibweise_entscheidet_nicht():
    assert VORHANDEN.echter_name("Recherche") == "recherche"
    assert VORHANDEN.echter_name("RECHERCHE") == "recherche"
    assert VORHANDEN.echter_name("Nacht-Review") == "nacht-review"


def test_zurueck_kommt_immer_der_echte_name():
    """Never the word that was typed. Two spellings of one agent would
    otherwise become two entries under two names."""
    assert VORHANDEN.echter_name("  ERINNERUNG  ") == "erinnerung"


def test_ein_anderer_name_bleibt_ein_anderer_name():
    """The half that has to keep refusing. No similarity, no 'did you mean' —
    quietly running something nobody asked for is worse than saying no."""
    for versuch in ("reminder", "recherchen", "rechercheur", "exe agent", "", None):
        assert VORHANDEN.echter_name(versuch) is None, versuch


# --- The refusal says what there is -----------------------------------------


def test_die_absage_nennt_die_vorhandenen():
    text = agentenname.unbekannt_text("reminder", VORHANDEN)
    assert "reminder" in text
    for name in VORHANDEN:
        assert name in text


def test_ohne_agenten_sagt_die_absage_das_auch():
    assert "none" in agentenname.unbekannt_text("x", ())


# --- An agent that can only answer ------------------------------------------


def _agent(name, werkzeuge):
    return SimpleNamespace(name=name, werkzeuge=werkzeuge)


def test_ein_agent_ohne_werkzeuge_wird_benannt():
    """The reminder agent's empty list is deliberate, and the user met it at
    run time in an answer that read like a model failure."""
    agenten = {
        "erinnerung": _agent("erinnerung", []),
        "recherche": _agent("recherche", ["run_command"]),
        "exe-agent": _agent("exe-agent", None),
    }
    assert agentenname.ohne_werkzeuge(agenten) == ["erinnerung"]
    satz = agentenname.auswahl_satz(agenten)
    assert "erinnerung (answers only, no tools)" in satz
    assert "recherche" in satz and "recherche (answers" not in satz


def test_kein_eintrag_heisst_alle_werkzeuge():
    """Left out entirely is the opposite of an empty list, and must not be
    reported as 'no tools'."""
    agenten = {"offen": _agent("offen", None)}
    assert agentenname.ohne_werkzeuge(agenten) == []
