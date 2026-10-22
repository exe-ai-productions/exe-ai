"""L2's variant picker (`frontend/src/teile/Bildserver.svelte`) -- two
findings from the round-1 objection, checked at the source since there is
no Svelte runtime harness here.
"""

from __future__ import annotations

import re
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
QUELLE = WURZEL / "frontend/src/teile/Bildserver.svelte"


def test_variantenfehler_bleibt_von_varianten_getrennt():
    """`varianten === null` used to mean three different things at once:
    still loading, the fetch failed, or a legitimate empty list (every
    non-win32 platform). A failed fetch rendered exactly like "nothing to
    choose here" -- silently. `variantenFehler` must be its own flag, set
    on failure, and the failure path must not also reset `varianten` (a
    transient failure during the periodic re-poll must not wipe an
    already-known-good answer)."""
    quelle = QUELLE.read_text(encoding="utf-8")
    assert re.search(r"let variantenFehler = \$state\(false\)", quelle), \
        "variantenFehler is missing as a state of its own"
    fang = re.search(
        r"varianten = await api\.bildProgrammVarianten\(\)\s*"
        r"variantenFehler = false\s*"
        r"\} catch \{\s*"
        r"variantenFehler = true\s*"
        r"\}",
        quelle,
    )
    assert fang, "success/failure of bildProgrammVarianten() not cleanly separated"


def test_variantenfehler_wird_am_bildschirm_angezeigt():
    """`variantenFehler` was set on a failed fetch but never read anywhere
    -- the test above proves the assignment split cleanly from success,
    not that a failure ever reaches the screen. A failed fetch rendered
    exactly like a legitimate empty list, silently.

    Checked structurally, in the absence of a Svelte runtime harness: the
    error branch must be its own `{#if}`, carrying a sentence tied to its
    own text key, and it must be checked ahead of the branches that could
    answer with an older, still-standing list -- otherwise a fetch failure
    that follows an earlier successful load could still fall through to
    stale data. The row carries it now (the drawing's sd.cpp block), not a
    paragraph: one fact per row, the same as every other fact of the
    window."""
    quelle = QUELLE.read_text(encoding="utf-8")
    fehler = re.search(
        r"\{#if variantenFehler\}\s*"
        r"<div class=\"zeile\"><span class=\"name v_fehler\">\{t\('bildserver\.varianten_fehler'\)\}</span></div>",
        quelle,
    )
    assert fehler, "variantenFehler shows no sentence of its own on screen"
    laden = re.search(r"\{:else if varianten === null\}", quelle)
    assert laden, "the still-loading branch is gone"
    assert fehler.start() < laden.start(), \
        "the error branch must stand before the loading branch, otherwise an old interim answer wins"
    # And the missing generator keeps a row of its own -- the state the
    # plain answer used to be lost in: the button, and while it comes down
    # the loading line with its bar.
    assert re.search(
        r"\{#if programmFehlt && !pickerSteht\}\s*"
        r"<div class=\"zeile\">\s*"
        r"\{#if programmLaedt\}\s*"
        r"<span class=\"name\">\{t\('bildserver\.generator_laedt'\)\}</span>",
        quelle,
    ), "the missing generator has no row of its own on screen"


def test_genereller_holen_knopf_weicht_dem_picker():
    """The win32 picker already covers "nothing installed yet" itself --
    each entry is its own get-this-one button. The generic holen row
    used to sit as its own unconditional `{#if programmFehlt}`, so on a
    machine offering several GPU backends, before install, BOTH the
    picker and the generic button rendered at once: one calls
    programmHolen(variante), the other programmHolen() with no variant,
    and both shared the same programmLaedt/programmStand progress bar --
    two bars for one download, and a way to fetch a different backend
    than the one just picked."""
    quelle = QUELLE.read_text(encoding="utf-8")
    assert re.search(
        r"\{#if programmFehlt && !pickerSteht\}\s*"
        r"<div class=\"zeile\">",
        quelle,
    ), "the generic fetch row stands beside the picker instead of giving way to it"


def test_holen_knopf_kehrt_zurueck_wenn_nur_die_variantenroute_scheitert():
    """laden()'s catch deliberately leaves stale `varianten` standing (see
    the earlier test) -- but that means a variant-fetch failure with the
    download route still working left `pickerSteht` true from OLD data,
    hiding the one working way to install: the error text won on
    variantenFehler, and the generic holen block stayed gone because the
    stale list still looked non-empty. A user in that state could never
    install the generator again, on a route that never actually broke."""
    quelle = QUELLE.read_text(encoding="utf-8")
    assert re.search(
        r"const pickerSteht = \$derived\("
        r"Boolean\(varianten\?\.varianten\.length\) && !variantenFehler\)",
        quelle,
    ), "pickerSteht still counts the old list after a fresh failure"


def test_installierte_variante_wird_beim_namen_genannt():
    """The running build already lived in `varianten.installiert` (and its
    build tag on disk) -- the macOS/non-win32 line just never said its
    name, repeating in different words the exact silence L2 exists to end
    (the Windows branch already named it right next to this code). It is
    named now in the sd.cpp block's own version row: the installed build
    by its tag, and a variant row by "Installiert" beside its name."""
    quelle = QUELLE.read_text(encoding="utf-8")
    # The version row stands for every installed program: the tag when one
    # lies on disk, a dash for a build unpacked by hand — never a
    # "Version:" with nothing behind it, and never silence either.
    assert re.search(
        r"\{#if stand\?\.programm_da\}[\s\S]*?"
        r"<span class=\"versionsmarke\">\{stand\.bau \?\? '-'\}</span>",
        quelle,
    ), "the installed build is not named"
    # The variant rows are the shared piece's: it names the installed one,
    # and the page tells it which one that is.
    assert "installed={varianten?.installiert}" in quelle, "the installed variant is not handed over"
    bauzeilen = (QUELLE.parent / "BuildRows.svelte").read_text(encoding="utf-8")
    assert "{t('bildserver.variante_installiert')}" in bauzeilen, "the installed variant is not named"


def test_zweiter_download_bekommt_weiter_fortschritt():
    """`laden()` only refreshed `programmStand` while `!stand.programm_da`
    -- exactly the state a SECOND variant's download starts in once a
    first one is already installed. That download's progress bar was
    stuck at whatever the initial POST answered, forever, because nothing
    ever polled it again."""
    quelle = QUELLE.read_text(encoding="utf-8")
    assert re.search(
        r"if \(!stand\.programm_da \|\| programmLaedt\) programmStand = await api\.bildProgrammStand\(\)",
        quelle,
    ), "laden() no longer polls the progress of a second download"
