"""Drawn marks carry no colour of their own.

A hand-mixed hex value in a component looks right in exactly one appearance —
the one it was picked in. The program has six, so a drawn sign either names a
palette variable or inherits the text colour. The palette file is where the
values live.

The third rule here is the neighbour of the first two: a list scrolls, but it
never draws its own scrollbar. The fourth is the same thought about shape
instead of colour — a sign is drawn once, in Hauszeichen.svelte, and every
other component asks for it by name.
"""

from __future__ import annotations

import re
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
TEILE = WURZEL / "frontend" / "src" / "teile"
PALETTE = WURZEL / "frontend" / "src" / "stil" / "global.css"

# Three, four, six or eight digits — `#fff`, `#fffc`, `#feffff` and
# `#feffffcc` are all equally fixed. Anchored on a boundary in FRONT only: a
# trailing boundary would let the eight-digit form through, because the six
# digit branch would end in the middle of a word.
HEXWERT = re.compile(
    r"(?<![\w#])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![0-9a-fA-F])"
)
# `url(#tachoKat)` names a paint server, not a colour. A gradient id that
# happens to read as hex would otherwise fail a file for nothing.
VERWEIS = re.compile(r"url\(\s*#[^)]*\)")


def hexwerte(quelle: str) -> list[str]:
    return HEXWERT.findall(VERWEIS.sub("url()", quelle))

# The three state colours, as global.css sets them.
AMPEL = {"--gruen": "#6b8e6f", "--gelb": "#c9a227", "--rot": "#b4544c"}


def test_die_stille_wahl_zeigt_keinen_rollbalken():
    """The list scrolls; it does not draw a bar while doing so."""
    quelle = (TEILE / "StilleWahl.svelte").read_text(encoding="utf-8")
    assert "scrollbar-width: none;" in quelle
    assert "scrollbar-width: thin" not in quelle
    assert "::-webkit-scrollbar-thumb" not in quelle
    # It still scrolls — hiding the bar must not have taken the overflow with
    # it, or the lower entries become unreachable.
    assert "overflow-y: auto;" in quelle


def test_die_palette_bleibt_der_ort_der_farbwerte():
    """The silence probe, and it can fail: move or recolour one of the three
    and this is the test that says so, instead of three green components
    quietly drawing something else."""
    quelle = PALETTE.read_text(encoding="utf-8")
    for name, wert in AMPEL.items():
        assert f"{name}: {wert};" in quelle, name


def test_das_ordnerzeichen_wird_nur_einmal_gezeichnet():
    """One sign, one file. A hand-copied path keeps its old shape when the
    original is redrawn, and the same folder then looks different in the
    picture window than in the catalogue."""
    kopien = sorted(
        pfad.relative_to(WURZEL).as_posix()
        for pfad in (WURZEL / "frontend" / "src").rglob("*.svelte")
        if "M3.75 18 V6 H9.75" in pfad.read_text(encoding="utf-8")
    )
    assert kopien == ["frontend/src/teile/Hauszeichen.svelte"], kopien


# --- Two colours an order decided -------------------------------------------


def _regel(quelle: str, name: str) -> str:
    treffer = re.search(rf"{re.escape(name)} \{{([\s\S]*?)\}}", quelle)
    assert treffer, f"the rule {name} is missing"
    return treffer.group(1)


def test_the_thinking_mark_wears_the_quietest_text_step():
    """The head of a block says that the answer thought and did something
    before its text. It is no state, it is a name: it carries the quietest
    step of the interface's text (`--text-neben`), the same one as the
    thinking and the calls under it, and its shimmer while the block goes is
    that same colour lit up — not the blue of "something runs", which the
    dot on the line says already."""
    quelle = (TEILE / "Nachricht.svelte").read_text(encoding="utf-8")
    kopf = _regel(quelle, ".block-head")
    assert "color: var(--text-neben)" in kopf, (
        "the head of a block no longer carries the quietest text step"
    )
    assert "--blau-text" not in kopf, "the head of a block carries the blue again"
    glanz = _regel(quelle, ".leucht")
    assert "var(--text-neben)" in glanz, "the shimmer is no longer the head's colour"
    assert "--blau" not in glanz, "the shimmer carries the blue again"
    assert "gedanke-kopf" not in quelle, "the old blue mark is back"


def _lum(hexwert: str) -> float:
    h = hexwert.lstrip("#")
    kanaele = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [
        c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        for c in kanaele
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _kontrast(eins: str, zwei: str) -> float:
    a, b = _lum(eins), _lum(zwei)
    hell, dunkel = max(a, b), min(a, b)
    return (hell + 0.05) / (dunkel + 0.05)


def _heaven_werte() -> dict[str, str]:
    """The colours and grounds of the heaven appearance, read from the file
    that owns them — not repeated here, where they would go stale."""
    werte = {
        name: wert
        for name, wert in _block_werte("heaven").items()
        if re.fullmatch(r"#[0-9a-fA-F]{6}", wert)
    }
    assert werte.get("--blau"), "heaven has no --blau"
    return werte


def test_das_blau_von_heaven_ist_lesbar():
    """This appearance is itself blue, and the marks
    drawn in `--blau` reached only 2.86 : 1 on the user's own bubble — below
    what a mark that has to be seen needs. The darker blue the theme already
    carries clears every ground it can stand on."""
    werte = _heaven_werte()
    farbe = werte["--blau"]
    assert farbe.lower() == "#3f6da5", (
        f"the blue of heaven is {farbe} again instead of the decided #3f6da5"
    )
    # The counter-check: the value this replaced fails exactly one ground.
    assert _kontrast("#4a7fc1", werte["--blase-eigen-standard"]) < 3.0, (
        "the old value passed the check after all — then the calculation is wrong"
    )
    for name in (
        "--bg", "--bg-erhoben", "--bg-leiste", "--bg-seite", "--bg-hoch",
        "--blase-eigen-standard",
    ):
        grund = werte.get(name)
        assert grund, f"{name} is missing in heaven"
        k = _kontrast(farbe, grund)
        assert k >= 3.0, f"{name}: only {k:.2f} : 1"


def _zeilen_werte(text: str) -> dict[str, str]:
    """Whole declaration lines only — a token named in a comment is prose,
    not a value."""
    werte: dict[str, str] = {}
    for zeile in text.splitlines():
        treffer = re.match(r"\s*(--[\w-]+):\s*(.+);\s*$", zeile)
        if treffer:
            werte[treffer.group(1)] = treffer.group(2)
    return werte


def _block_werte(modus: str) -> dict[str, str]:
    """One appearance's own block, token name to value, read from the file
    that owns them."""
    quelle = PALETTE.read_text(encoding="utf-8")
    block = re.search(rf":root\[data-modus='{modus}'\] \{{([\s\S]*?)\n\}}", quelle)
    assert block, f"the block for {modus} is missing in the palette"
    return _zeilen_werte(block.group(1))


def _auto_werte() -> dict[str, str]:
    """The auto-dark block: at equal specificity it is the rule a missing
    token in a later look would let through."""
    quelle = PALETTE.read_text(encoding="utf-8")
    block = re.search(
        r"@media \(prefers-color-scheme: dark\) \{\n"
        r"  :root:not\(\[data-modus='hell'\], \[data-modus='snow'\], \[data-eigen='hell'\]\) \{([\s\S]*?)\n  \}",
        quelle,
    )
    assert block, "the auto-dark block is missing"
    return _zeilen_werte(block.group(1))


def test_moune_setzt_jedes_token_von_heaven():
    """The newest appearance stands after the auto-dark block, so a token
    it forgot would let the darker system look seep through it. Every name
    the heaven block sets — the template for its build — is set here too,
    and every name of the auto-dark block itself, the rule that really
    seeps at equal specificity."""
    zusammen = set(_block_werte("heaven")) | set(_auto_werte())
    moune = _block_werte("moune")
    fehlend = sorted(zusammen - set(moune))
    assert not fehlend, f"moune misses these tokens: {fehlend}"
    assert "--vek" in moune, "moune has no --vek for its drawings"


def test_no_look_keeps_a_tool_colour():
    """A tool call has no colour of its own: its mark and its name stand in the
    text colour of the look, light in Exe, dark in Pearl. Colour is for
    state alone. The token is in none of the six looks, and nothing in the
    sources reads it."""
    palette = PALETTE.read_text(encoding="utf-8")
    assert "--werkzeug" not in palette
    uses = re.compile(r"var\(\s*--werkzeug|--werkzeug\s*:")
    for path in (WURZEL / "frontend" / "src").rglob("*"):
        if path.suffix in {".svelte", ".js", ".css"}:
            assert not uses.search(path.read_text(encoding="utf-8")), path
    # The marks and names that wore it now say the text colour themselves, or
    # inherit it from their row.
    name = re.search(r"\.werkzeugname \{([^}]*)\}", palette)
    assert name and "color: var(--text)" in name.group(1)
    mark = (TEILE / "Werkzeugzeichen.svelte").read_text(encoding="utf-8")
    assert "color: var(--text);" in mark.split(".zeichen.werkzeug {", 1)[1].split("}", 1)[0]


def test_silence_the_state_colours_of_a_tool_stay():
    """Only the sand went. The name and the outcome of a failed call in the
    terminal are still red, a waiting answer's state still yellow, and the
    kind for everything unknown still grey."""
    terminal = (TEILE / "ModulTerminal.svelte").read_text(encoding="utf-8")
    for part in (".name", ".ausgang"):
        rule = terminal.split(f".werkzeugblock.misslungen {part} {{", 1)[1].split("}", 1)[0]
        assert "color: var(--rot-text)" in rule, part
    window = (TEILE / "Auftragfenster.svelte").read_text(encoding="utf-8")
    assert ".wzzeichen.weitere { color: var(--text-still); }" in window
    message = (TEILE / "Nachricht.svelte").read_text(encoding="utf-8")
    assert ".agent-state.wartet { color: var(--gelb-text); }" in message


def test_the_chat_glass_is_never_frosted():
    """The chat tile is clear glass in every look. A blur behind it smoothed
    away the fine grain a gradient is drawn with and left bands; so no look
    names a blur for the chat any more, and the chat tile draws no layer
    for one. The frosted glass of the question card and its veil is a
    different token and stays."""
    sources = [PALETTE, WURZEL / "frontend" / "src" / "App.svelte", *sorted(TEILE.glob("*.svelte"))]
    named = [p.name for p in sources if "--kachel-blur" in p.read_text(encoding="utf-8")]
    assert not named, f"the chat blur is named again in {named}"
    # Neither the tile nor a layer of its own may blur what lies behind it,
    # whatever the value is called.
    app = (WURZEL / "frontend" / "src" / "App.svelte").read_text(encoding="utf-8")
    tile_rules = re.findall(r"\n  (main(?:::[\w-]+)?) \{([^}]*)\}", app)
    assert tile_rules, "the rule of the chat tile is missing"
    blurred = [name for name, body in tile_rules if "backdrop-filter" in body]
    assert not blurred, f"the chat tile is blurred again in {blurred}"
    # The silence check: the frost that stays is still there to be read.
    assert "--kachel-frost: blur(14px);" in PALETTE.read_text(encoding="utf-8")
    assert "backdrop-filter: var(--kachel-frost)" in (TEILE / "QuestionBox.svelte").read_text(encoding="utf-8")


def test_loading_again_is_the_one_circular_arrow_of_the_house():
    """The sign for loading a page again is the circular arrow an answer
    already wears for "once more" — one drawing, the same two paths and the
    same round corners in both places (the arrow itself is
    tests/test_regenerate_arrow.py's business)."""
    signs = (TEILE / "Hauszeichen.svelte").read_text(encoding="utf-8")
    branch = re.search(r"\{:else if zeichen === 'neu_laden'\}([\s\S]*?)\{:else if", signs)
    assert branch, "the sign neu_laden is missing"
    paths = re.findall(r"<path ([^>]*?)\s*/>", branch.group(1))
    assert len(paths) == 2, paths
    assert all("stroke-linejoin" not in tag for tag in paths), "the sign takes the round join of the grid"
    drawn = [re.search(r'd="([^"]+)"', tag).group(1) for tag in paths]
    # Under an answer the arrow is either those very paths or the sign
    # itself, asked for by name — never a second drawing of its own.
    message = (TEILE / "Nachricht.svelte").read_text(encoding="utf-8")
    arrows = re.findall(r'<path d="(M21 12a9[^"]*)"', message)
    by_name = 'zeichen="neu_laden"' in message
    assert arrows or by_name, "the arrow under an answer is gone"
    assert all(d == drawn[0] for d in arrows), (
        "the arrow under an answer is no longer the drawing neu_laden carries"
    )
