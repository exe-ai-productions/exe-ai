"""The start window's model row: two servers, and the line the server answers.

The row used to carry the field's meaning beside every model of the
catalogue, and the window worked out for itself where a run would land —
"the first reachable endpoint that can call tools". That prediction could
part company with the order the server really walks
(``agentenmodellwahl.lauf_kennung``), and it named a paid provider among
others: the preview said X while the run went to Y.

So the row names the two servers a run may take — the main model first, the
agent server below it, the agent server preselected — and what stands
beneath each of them is what the SERVER answers for it.
The detour notice stays, and it hangs on the one question the server asks as
well: a server that answers but cannot call the tools this agent needs.

There is no test runner for Svelte in this repo. These guards read the
source, which is enough for the shape of the thing; the behaviour itself is
measured against a running service with a real browser (see the report).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
QUELLE = WURZEL / "frontend" / "src" / "teile" / "AuftragStarten.svelte"
DIENST = WURZEL / "app" / "api" / "v1" / "auftraege.py"
SCHLUESSEL = "laeuft_auf"


@pytest.fixture(scope="module")
def text():
    if not QUELLE.exists():
        pytest.skip("frontend sources not present")
    return QUELLE.read_text(encoding="utf-8")


def _block(text: str, anfang: str, ende: str = "\n  )") -> str:
    """One block of the component, from the line that opens it to its end.

    Refuses loudly: a guard that cannot find what it is about has to say
    WHICH piece moved, not raise a bare ValueError from a string index.
    """
    stelle = text.find(anfang)
    assert stelle >= 0, f"Not found: {anfang!r}"
    rest = text[stelle + len(anfang) :]
    schluss = rest.find(ende)
    assert schluss >= 0, f"No end {ende!r} after {anfang!r}"
    return rest[:schluss]


# --- The row names the two servers, and nothing else ------------------------


def test_die_zeile_kennt_genau_die_zwei_server(text):
    """Two servers, and exactly the two a run may take, nothing else:
    the main model and the agent server."""
    treffer = re.search(r"const SERVER = \[(.*?)\]", text, re.S)
    assert treffer, "The line no longer knows the two servers"
    assert "HAUPTMODELL" in treffer.group(1)
    assert "SLOT_ENDPUNKT" in treffer.group(1)


def test_die_liste_zeigt_die_beiden_server_und_keinen_modellkatalog(text):
    """Exactly two entries: the main model stands
    first in the list, and unfolding it leaves the agent server and nothing
    else."""
    block = _block(text, "const auswahl = $derived([", "\n  ])")
    assert "HAUPTMODELL" in block and "SLOT_ENDPUNKT" in block
    assert "verfuegbar" not in block, (
        "The line appends the model catalogue — then there are no longer two "
        "entries"
    )
    assert "zustand.modelle" not in block


def test_die_liste_traegt_die_beschriftungen_des_hauses(text):
    """The names come from the catalogs, not from the component — and they
    are the ones the house already uses for these two servers."""
    block = _block(text, "const auswahl = $derived([", "\n  ])")
    assert "t('modell.agentenmodell_hauptmodell')" in block
    assert "t('agentserver.titel')" in block


def test_die_wahlzeile_zeigt_diese_liste(text):
    # The picker row, not the row that only says no model is reachable.
    zeile = text[text.index("bind:wert={endpointId}") :]
    zeile = zeile[: zeile.index("/>")]
    assert "eintraege={auswahl}" in zeile, (
        "The line shows something other than the built list"
    )


def test_der_agentenserver_ist_vorausgewaehlt(text):
    """The agent server is preselected, and the main model
    takes over when it is not there."""
    assert re.search(r"let endpointId = \$state\(SLOT_ENDPUNKT\)", text), (
        "The line does not stand on the agent server"
    )
    oeffnen = text[text.index("if (!offen) return") :]
    assert "endpointId = SLOT_ENDPUNKT" in oeffnen[:700], (
        "The preselection is not set on opening"
    )


# --- The second line under each entry is the server's answer ----------------


def test_der_zweite_eintrag_kommt_vom_server(text):
    """Read, not computed: the same answer the start books the
    run with, asked of the same place."""
    assert re.search(r"\.laufmodell\(", text), (
        "The line does not ask the server — then the window keeps working out the "
        "preview itself"
    )
    block = _block(text, "const auswahl = $derived([", "\n  ])")
    assert block.count("lauf[") == 2, (
        "Not both entries carry the server's answer"
    )
    assert "quelle:" in block, (
        "Without the menu's second line the entry does not say where the "
        "run goes"
    )


def test_die_vorschau_wird_nicht_ein_zweites_mal_gerechnet(text):
    """The window no longer walks the order itself. Kept as a guard because
    the old shape is a tempting one: it needs nothing but the list it already
    holds, and it is wrong exactly when it matters.

    ``umgeleitet`` stays and is checked separately — it describes the one case
    the server's answer does not tell by itself."""
    assert "const laufModell" not in text
    assert "const zeilenModell" not in text
    assert "const stehtAufFeld" not in text
    assert "const verfuegbar" not in text, (
        "The list of reachable models is read again"
    )


def test_die_vorschau_wird_fuer_beide_eintraege_gefragt(text):
    """Both, and not only the row's own: the menu carries a line under each of
    them, and a line that is only right for the one nobody picked is worse
    than none."""
    frage = _block(text, "const braucht = werkzeugeMoeglich", "\n  })")
    assert "SERVER" in frage, (
        "The query runs through the line instead of through the two servers"
    )
    assert "void zustand.modelle.length" in text, (
        "Without the reachable list a server that comes up while the "
        "window is open stays invisible to the line"
    )
    assert "lauf = {}" in text, (
        "Without an empty start the window shows the answer of the previous opening"
    )


# --- The run gets the id the row carries ------------------------------------


def test_der_lauf_bekommt_die_kennung_der_zeile(text):
    """One value, one way out. Which of the two servers really takes the run
    is not decided here — it is the server's own order, and that
    is why the pick can go out unchanged even though nobody chose it."""
    assert "endpoint_id: endpointId" in text
    assert "FELD_WAHL" not in text, "The old field entry is still in the line"
    assert "handModell" not in text, "The old choice by hand is still in the line"


# --- The notice stays, on the one question that is left ---------------------


def test_die_maske_nennt_den_endpunkt_wenn_er_ein_anderer_ist(text):
    assert "const umgeleitet = $derived" in text
    assert f"t('jobs.{SCHLUESSEL}'" in text, (
        "The run goes elsewhere and nothing of it is on screen"
    )


def test_der_hinweis_haengt_an_der_zweiten_antwort(text):
    """The notice is about ONE reason: this agent needs tools and the server in
    the row cannot give them.

    Told from the SERVER, by asking the same question twice — once the way the
    run is booked, once without the tool rule. The two answers differ exactly
    when that rule moved the run. A row whose server is simply not there is
    the fallback the second line already names: there both
    answers agree, and the notice stays away."""
    block = _block(text, "const umgeleitet = $derived(")
    assert "laufOhne" in block and "lauf[endpointId]" in block, (
        "The redirect no longer compares the service's two answers"
    )
    assert "capabilities" not in block, (
        "The redirect is worked out from the 30-second list again — "
        "that list and the service's answer drift apart"
    )
    frage = _block(text, "const reihe = endpointId", "\n  })")
    assert ".laufmodell(reihe, false)" in frage, (
        "The second question is not asked without the tool rule"
    )


def test_der_hinweis_setzt_modell_und_zeilennamen_ein(text):
    stelle = text.index("t('jobs.laeuft_auf'")
    zeile = text[stelle : stelle + 220]
    assert "lauf[endpointId]?.name" in zeile, (
        "The hint does not name the model the run lands on"
    )
    assert "feld: zeilenName" in zeile, (
        "The hint does not name the server shown in the line"
    )


# --- The catalogs -----------------------------------------------------------


@pytest.mark.parametrize("sprache", ["de", "en"])
def test_der_hinweis_steht_in_beiden_katalogen(sprache):
    katalog = json.loads((WURZEL / "app" / "locales" / f"{sprache}.json").read_text(encoding="utf-8"))
    satz = katalog["jobs"][SCHLUESSEL]
    assert "{modell}" in satz and "{feld}" in satz, (
        f"{sprache}.json: the hint must insert the model and server names"
    )


@pytest.mark.parametrize("sprache", ["de", "en"])
def test_die_namen_der_beiden_eintraege_stehen_in_beiden_katalogen(sprache):
    """The name of an entry belongs to the catalogs, not to the component."""
    katalog = json.loads((WURZEL / "app" / "locales" / f"{sprache}.json").read_text(encoding="utf-8"))
    assert katalog["modell"]["agentenmodell_hauptmodell"].strip()
    assert katalog["agentserver"]["titel"].strip()


# --- What the window shows is the service's own answer ----------------------


def test_die_vorschau_und_der_lauf_fragen_dieselbe_stelle():
    """A drift guard, not a rule of its own: the window shows what the route
    answers, and the route asks exactly what the start asks.

    Two questions that grow their own answers are how a preview turns into a
    second opinion — the window named an endpoint the run then never went to.
    The order itself lives in ``agentenmodellwahl.lauf_kennung``
    because the cron pre-check has to ask the same question before it calls a
    due schedule ready; the start and the route keep asking that one function
    and never grow one of their own again."""
    quelle = DIENST.read_text(encoding="utf-8")
    assert '"/jobs/laufmodell"' in quelle, "The preview route is missing"
    assert quelle.count("agentenmodellwahl.lauf_kennung(") >= 2, (
        "Start and preview route no longer ask the same place"
    )
    assert 'kann("tool_calls")' in quelle
