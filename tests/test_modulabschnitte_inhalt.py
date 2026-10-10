"""Every panel built from sections has to hand its sections something.

``Modulabschnitte.svelte`` renders each section with
``{@render inhalt?.(a.name)}``. The question mark is what makes a missing
snippet cost nothing to notice: no error in the console, no empty prop
warning, just headings over blank surfaces — which is exactly what the
cronjobs panel showed while a schedule of the user's went on firing every
five minutes behind it, with the only switch to stop it on that very
surface.

So the guard is here rather than in a comment. A panel that takes the shared
section frame either passes ``inhalt``, or this test names it.
"""

from __future__ import annotations

import re
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
TEILE = WURZEL / "frontend/src/teile"

# The tag as it is written when the frame is used, however the attributes are
# spread over the line.
BENUTZT = re.compile(r"<Modulabschnitte\b[^>]*>", re.S)
# `inhalt` handed over, in either spelling: shorthand or named.
UEBERGIBT = re.compile(r"\{\s*inhalt\s*\}|inhalt\s*=\s*\{")


def test_jede_leiste_mit_abschnitten_uebergibt_inhalt():
    ohne: list[str] = []
    benutzer: list[str] = []
    for datei in sorted(TEILE.glob("*.svelte")):
        if datei.name == "Modulabschnitte.svelte":
            continue
        quelle = datei.read_text(encoding="utf-8")
        for stelle in BENUTZT.findall(quelle):
            benutzer.append(datei.name)
            if not UEBERGIBT.search(stelle):
                ohne.append(f"{datei.name}: {stelle.strip()}")

    # The test has to fail when it finds nothing to look at, or a rename of
    # the frame would turn it into a green light that checks nothing.
    assert benutzer, "Modulabschnitte is used nowhere -- is the name still right?"
    assert not ohne, (
        "These bars hand their sections no content, "
        "and that stays silent on screen: " + " | ".join(ohne)
    )


# --- One column that scrolls as a whole -------------------------------------
#
# The sections used to sit between seams the hand could drag, each with a
# scroll area of its own. The agents view is one column now, and the whole
# surface scrolls: every part stands at the height its content has, so no
# part can end up squeezed shut behind a seam.

RAHMEN = TEILE / "Modulabschnitte.svelte"


def test_die_spalte_scrollt_als_ganzes_und_hat_keine_naehte():
    quelle = RAHMEN.read_text(encoding="utf-8")
    spalte = quelle.split(".abschnitte {", 1)[1].split("}", 1)[0]
    assert "overflow-y: auto" in spalte, "the column no longer scrolls as a whole"
    assert "naht" not in quelle, "a seam is back between the sections"
    assert "hoehen" not in quelle, "the sections carry heights of their own again"


# --- The schedules view: two columns, one part that folds --------------------


def test_ein_klappbarer_abschnitt_zeigt_seinen_inhalt_nur_geoeffnet():
    quelle = RAHMEN.read_text(encoding="utf-8")
    assert "{#if !a.klapp || a.klapp.offen}" in quelle, "a folded part renders its content"
    assert "aria-expanded={a.klapp.offen}" in quelle, "the fold button no longer says its state"


def test_die_zeitplaene_stehen_links_und_was_geschah_rechts():
    quelle = (TEILE / "ModulCronjobs.svelte").read_text(encoding="utf-8")
    abschnitte = quelle.split("const ABSCHNITTE = $derived([", 1)[1].split("])", 1)[0]
    spalten = dict(
        zip(
            re.findall(r"name: '(\w+)'", abschnitte),
            re.findall(r"spalte: (\d)", abschnitte),
            strict=True,
        )
    )
    # The calendar on the left, the chosen day's runs on the right; the
    # history and the failed runs left the rail with the scripts for
    # Settings › Schedules.
    assert spalten == {"kalender": "1", "tag": "2"}
    assert "zweispaltig={flaeche.zweispaltig}" in quelle, "the view never asks for two columns"
    # Schweigeprobe: the surface hands the view nothing of its own any more.
    leiste = (TEILE / "Arbeitsleiste.svelte").read_text(encoding="utf-8")
    assert "CRON_ABSCHNITTE" not in leiste
