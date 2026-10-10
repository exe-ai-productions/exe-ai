"""The dot's one remaining property must leave every existing caller alone.

`atmet` is off by default; its sibling
`gross` was removed again once the last caller was gone. A regex over the
source would confirm the prop exists, not that a caller who never passes it
still gets the disc it always got — so the component is compiled with
Svelte's own compiler and rendered for real, the same way
tests/test_warteschlange.py runs the queue module.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
FRONTEND = WURZEL / "frontend"
QUELLE = FRONTEND / "src" / "teile" / "Leuchtpunkt.svelte"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)


def _gerendert(props: dict) -> str:
    """Compile Leuchtpunkt.svelte for the server and render it with `props`
    — the markup a caller actually gets, not a guess from reading the file."""
    treiber = FRONTEND / "leuchtpunkt.pruefung.mjs"
    gebaut = FRONTEND / "leuchtpunkt.gebaut.mjs"
    treiber.write_text(
        textwrap.dedent(
            """
            import { compile } from 'svelte/compiler'
            import { render } from 'svelte/server'
            import { readFileSync, writeFileSync } from 'fs'
            const quelle = readFileSync(%r, 'utf-8')
            const gebaut = compile(quelle, { filename: 'Leuchtpunkt.svelte', generate: 'server' })
            writeFileSync(%r, gebaut.js.code)
            const { default: Leuchtpunkt } = await import(%r)
            const aus = render(Leuchtpunkt, { props: %s })
            console.log('---BERICHT---' + JSON.stringify({ body: aus.body }))
            """
        )
        % (str(QUELLE), str(gebaut), "./" + gebaut.name, json.dumps(props)),
        encoding="utf-8",
    )
    try:
        lauf = subprocess.run(
            ["node", treiber.name],
            cwd=FRONTEND,
            capture_output=True,
            text=True,
            timeout=60,
        )
    finally:
        treiber.unlink(missing_ok=True)
        gebaut.unlink(missing_ok=True)
    assert lauf.returncode == 0, (lauf.stdout + lauf.stderr)[-2000:]
    marke = "---BERICHT---"
    assert marke in lauf.stdout, lauf.stdout[-2000:]
    return json.loads(lauf.stdout.split(marke, 1)[1].strip())["body"]


def _erzeugtes_css() -> str:
    """The CSS Svelte actually emits for the component — not a slice of the
    source picked out by a regex, which a rule outside that slice (the plain
    `.scheibe { ... }` block, say) could slip straight past."""
    treiber = FRONTEND / "leuchtpunkt.css.mjs"
    treiber.write_text(
        textwrap.dedent(
            """
            import { compile } from 'svelte/compiler'
            import { readFileSync } from 'fs'
            const quelle = readFileSync(%r, 'utf-8')
            const gebaut = compile(quelle, { filename: 'Leuchtpunkt.svelte', generate: 'server' })
            console.log('---BERICHT---' + JSON.stringify({ css: gebaut.css.code }))
            """
        )
        % str(QUELLE),
        encoding="utf-8",
    )
    try:
        lauf = subprocess.run(
            ["node", treiber.name],
            cwd=FRONTEND,
            capture_output=True,
            text=True,
            timeout=60,
        )
    finally:
        treiber.unlink(missing_ok=True)
    assert lauf.returncode == 0, (lauf.stdout + lauf.stderr)[-2000:]
    marke = "---BERICHT---"
    assert marke in lauf.stdout, lauf.stdout[-2000:]
    return json.loads(lauf.stdout.split(marke, 1)[1].strip())["css"]


def _masse(markup: str) -> dict:
    svg = re.search(r'<svg class="([^"]*)"[^>]*width="(\d+)"[^>]*height="(\d+)"', markup)
    kreis = re.search(r'<circle[^>]*r="([\d.]+)"', markup)
    return {
        "klassen": svg.group(1).split(),
        "kasten": int(svg.group(2)),
        "hoehe": int(svg.group(3)),
        "radius": float(kreis.group(1)),
    }


def test_ohne_die_neue_eigenschaft_bleibt_alles_wie_es_war():
    """The exact case every existing caller is in: `atmet` never passed at
    all, same as before this step."""
    m = _masse(_gerendert({"farbe": "gruen", "groesse": 10}))
    assert "atmet" not in m["klassen"]
    assert m["kasten"] == m["hoehe"] == 12  # the disc and one pixel of air around it
    assert m["radius"] == 5  # groesse is the diameter that is drawn


# The three sizes the dot was drawn in while its number still meant "two
# pixels less than the disc": the box and the disc each of them had, measured
# then. A caller now says the disc's diameter and gets exactly these.
DRAWN = {9: (11, 4.5), 10: (12, 5), 11: (13, 5.5)}


@pytest.mark.parametrize("diameter", sorted(DRAWN))
def test_the_size_is_the_diameter_that_is_drawn(diameter):
    box, radius = DRAWN[diameter]
    m = _masse(_gerendert({"farbe": "gruen", "groesse": diameter}))
    assert m["kasten"] == m["hoehe"] == box
    assert m["radius"] == radius == diameter / 2


@pytest.mark.parametrize("diameter", sorted(DRAWN))
def test_the_dot_that_says_nothing_stays_two_pixels_smaller(diameter):
    """Silence probe: the quiet dot keeps its box and its smaller disc."""
    box, radius = DRAWN[diameter]
    quiet = _masse(_gerendert({"farbe": "leer", "groesse": diameter}))
    assert quiet["kasten"] == quiet["hoehe"] == box
    assert quiet["radius"] == radius - 1


def test_a_caller_that_names_no_size_gets_the_dot_it_always_got():
    m = _masse(_gerendert({"farbe": "gruen"}))
    assert m["kasten"] == m["hoehe"] == 12
    assert m["radius"] == 5


def test_atmet_setzt_nur_die_klasse_die_fuellung_bleibt_unberuehrt():
    m = _masse(_gerendert({"farbe": "rot", "groesse": 9, "atmet": True}))
    assert "atmet" in m["klassen"]
    # The fill itself is a plain data-farbe lookup, never a computed opacity —
    # the property that would make the disc half-invisible has nothing to
    # attach itself to.
    quelle = QUELLE.read_text()
    fuellungsblock = re.search(r"\.scheibe\[data-farbe='rot'\][^}]*\}", quelle).group(0)
    assert "opacity" not in fuellungsblock


def test_der_atmende_schein_haengt_nie_an_der_deckkraft_der_scheibe():
    """The keyframes may only ever touch `filter` — the moment one of them
    reaches for `opacity` on the disc, this is the exact bug the design
    order rejected (the old "half the time half-invisible" dot)."""
    quelle = QUELLE.read_text()
    keyframes = re.findall(r"@keyframes atmen-\w+\s*\{.*?\n  \}", quelle, re.S)
    assert len(keyframes) == 4  # one per colour the dot can carry
    for block in keyframes:
        assert "filter" in block
        assert "opacity" not in block


def test_opacity_kommt_im_ganzen_erzeugten_css_nirgends_vor():
    """The narrower checks above only look inside the fill rule and the
    keyframes — a stray `opacity` on the plain `.scheibe { ... }` rule, or
    anywhere else in the stylesheet, would pass both and still make the
    disc half-invisible half the time, exactly the fallen-through preview
    variant this step exists to rule out. Nothing short of the whole
    generated stylesheet closes that gap.

    Comments are stripped first — a comment explaining why opacity is
    avoided is legitimate documentation, not a declaration, and the word
    appearing in prose must not fail a check meant to catch the property."""
    ohne_kommentare = re.sub(r"/\*.*?\*/", "", _erzeugtes_css(), flags=re.S)
    assert "opacity" not in ohne_kommentare


def _spezifitaet(selektor: str) -> tuple[int, int, int]:
    """(IDs, Klassen+Attribute+Pseudoklassen, Elemente) — the three tiers
    that decide a CSS cascade. `@media` changes none of them; it only
    decides whether a rule is in play at all, which is exactly the
    distinction this step's bug turned on."""
    ids = selektor.count("#")
    klassen = selektor.count(".") + selektor.count("[")
    return (ids, klassen, 0)


def test_reduzierte_bewegung_gewinnt_wirklich_gegen_die_farbregeln():
    """A rule inside `@media (prefers-reduced-motion: reduce)` is not
    automatically stronger than the rule it is meant to override — the
    media query only gates whether the rule applies, the cascade still
    decides by specificity and, on a tie, by source order. The previous
    version of this test only checked that the text `animation: none`
    existed somewhere in a reduced-motion block; it would have stayed
    green with a selector too weak to ever win. This one computes the
    actual specificity of every rule in the running argument, on the
    real compiled CSS (post-scoping), the same way a browser would."""
    css = _erzeugtes_css()

    farbregeln = re.findall(
        r"(\.lp\.atmet\[data-farbe='\w+'\][^\{]*)\{\s*animation:\s*[\w-]*atmen-\w+",
        css,
    )
    assert len(farbregeln) == 4  # one per colour, same as the keyframes

    media_block = re.search(
        r"@media \(prefers-reduced-motion: reduce\)\s*\{\s*(.*?\})\s*\}",
        css,
        re.S,
    )
    assert media_block is not None
    aus_regel = re.search(r"([^\{]*)\{\s*animation:\s*none", media_block.group(1))
    assert aus_regel is not None, "no 'animation: none' in the reduced-motion block"
    aus_selektor = aus_regel.group(1)

    aus_spez = _spezifitaet(aus_selektor)
    for regel in farbregeln:
        farb_spez = _spezifitaet(regel)
        assert aus_spez >= farb_spez, (
            f"The switch-off ({aus_selektor.strip()!r}, {aus_spez}) is weaker "
            f"than the colour rule ({regel.strip()!r}, {farb_spez}) — "
            "the animation would go on under reduced motion"
        )

    # Same specificity is only safe if the switch-off rule is declared
    # LATER — the cascade's tie-break. It sits inside its own @media block
    # near the end of the file, so its position in the whole stylesheet
    # must come after every colour rule's.
    letzte_farbregel_ende = max(css.index(r) + len(r) for r in farbregeln)
    assert media_block.start() > letzte_farbregel_ende
