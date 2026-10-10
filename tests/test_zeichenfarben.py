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


def _palette_wert(modus: str, name: str) -> str:
    """One colour out of one appearance block — read, never repeated.

    ``modus`` empty means the base block, the light appearance.
    """
    quelle = PALETTE.read_text(encoding="utf-8")
    kopf = ":root {" if not modus else f":root[data-modus='{modus}'] {{"
    block = re.search(rf"{re.escape(kopf)}([\s\S]*?)\n\}}", quelle)
    assert block, f"the block for {modus or 'light'} is missing"
    treffer = re.search(rf"{re.escape(name)}:\s*(#[0-9a-fA-F]{{6}})", block.group(1))
    assert treffer, f"{name} is missing in {modus or 'light'}"
    return treffer.group(1)


def test_die_denken_marke_traegt_das_hausblau():
    """The mark that says an answer thought first
    carries the blue this interface already spends on "something runs" —
    not the still grey of a subtitle, which is the tone for what may be
    skipped. The unfolded thought below keeps its own quieter colour: the
    mark says something IS there, the text is what it says."""
    quelle = (TEILE / "Nachricht.svelte").read_text(encoding="utf-8")
    kopf = _regel(quelle, ".gedanke-kopf")
    assert "color: var(--blau-text)" in kopf, (
        "the thinking mark no longer carries the house blue"
    )
    assert "var(--text-still)" not in kopf, (
        "the thinking mark carries the quiet grey again"
    )
    text = _regel(quelle, ".gedanke-text")
    assert "color: var(--text-leise)" in text, (
        "the expanded thought text lost its own colour"
    )
    # The name alone is not the rule: the mark is drawn in `--blau-text`,
    # and THAT value has to stay readable in every appearance. Checked here
    # for all six, against each one's own ground.
    for bild, grund in (
        ("", "#e0d7c3"),                  # light, the base block
        ("dunkel", "#131312"),
        ("darkmatter", "#0b0817"),
        ("heaven", "#e8eef8"),
        ("moune", "#f3fbe9"),
    ):
        farbe = _palette_wert(bild, "--blau-text")
        k = _kontrast(farbe, grund)
        assert k >= 3.0, (
            f"the thinking mark in {bild or 'light'}: only {k:.2f} : 1 on {grund}"
        )


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
        r"  :root:not\(\[data-modus='hell'\], \[data-eigen='hell'\]\) \{([\s\S]*?)\n  \}",
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


# The warm tone every look mixes into its own quiet ink for a tool call.
TOOL_TONE = "#c98a5a"
# Parts of that tone out of a hundred. The light base block takes two fewer:
# at 45 its mix came to 4.39 : 1 on the raised ground, under what text needs.
TOOL_SHARE = {"": 43, "dunkel": 45, "auto": 45, "darkmatter": 45, "heaven": 45, "moune": 45}


def _mix(tone: str, ink: str, share: int) -> str:
    """Two colours mixed channel by channel in sRGB, as `color-mix` does."""
    one = [int(tone[i : i + 2], 16) for i in (1, 3, 5)]
    two = [int(ink[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(
        f"{round((a * share + b * (100 - share)) / 100):02x}" for a, b in zip(one, two, strict=True)
    )


def _look_values(look: str) -> dict[str, str]:
    if look == "auto":
        return _auto_werte()
    return {
        name: _palette_wert(look, name)
        for name in ("--werkzeug", "--text-leise", "--bg-erhoben")
    }


def test_the_tool_colour_is_a_quiet_sand_in_every_look():
    """A tool call keeps a colour of its own, and a quiet one: the same warm
    tone mixed into the quiet ink of each look, set as a fixed value. As
    text on the raised ground of its look it has to carry what a line of
    type needs."""
    for look, share in TOOL_SHARE.items():
        values = _look_values(look)
        colour = values["--werkzeug"].lower()
        expected = _mix(TOOL_TONE, values["--text-leise"], share)
        assert colour == expected, (
            f"{look or 'light'}: the tool colour is {colour}, the mix of {share} parts is {expected}"
        )
        k = _kontrast(colour, values["--bg-erhoben"])
        assert k >= 4.5, f"{look or 'light'}: only {k:.2f} : 1 on the raised ground"
    # The counter-check: the light look at the share of the others falls short.
    light = _look_values("")
    assert _kontrast(_mix(TOOL_TONE, light["--text-leise"], 45), light["--bg-erhoben"]) < 4.5, (
        "45 parts carry in the light look after all — then it needs no share of its own"
    )


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
    already wears for "once more" — one drawing, asked for by name, and the
    same path and the same sharp corner in both places."""
    signs = (TEILE / "Hauszeichen.svelte").read_text(encoding="utf-8")
    branch = re.search(r"\{:else if zeichen === 'neu_laden'\}([\s\S]*?)\{:else if", signs)
    assert branch, "the sign neu_laden is missing"
    paths = re.findall(r"<path ([^>]*?)\s*/>", branch.group(1))
    assert len(paths) == 1, paths
    path = re.search(r'd="([^"]+)"', paths[0])
    assert path and 'stroke-linejoin="miter"' in paths[0], paths[0]
    # Under an answer the arrow is either that very path or the sign itself,
    # asked for by name — never a second drawing of its own.
    message = (TEILE / "Nachricht.svelte").read_text(encoding="utf-8")
    arrows = re.findall(r'<path d="(M20 11a[^"]*)"', message)
    by_name = 'zeichen="neu_laden"' in message
    assert arrows or by_name, "the arrow under an answer is gone"
    assert all(d == path.group(1) for d in arrows), (
        "the arrow under an answer is no longer the drawing neu_laden carries"
    )
