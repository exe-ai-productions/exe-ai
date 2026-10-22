"""The chat tile and a menu page over a gradient: no bands, and both raised.

See-through glass over a flat dark gradient leaves bands one grey level
apart. A look whose frame is a gradient therefore names that gradient a
second time, every colour already mixed with its glass, and the tile and the
menu page draw it themselves, fixed to the window like the frame. Exe and
Dark Matter carry a flat frame with a drawing on it instead, and over one
colour nothing bands: their tile keeps the see-through glass, in the same
share of the look's own dark, so the drawing shows faintly through. The
looks with a flat light frame or with drawings behind a gradient keep the
see-through ground too. Both surfaces wear the same edge and the same shadow
in every look; inside the edge the light looks draw a bright rim, Exe a
faint green line, Dark Matter a faint violet one, and a dark gradient of the
user's own nothing.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHEET = ROOT / "frontend" / "src" / "stil" / "global.css"
APP = ROOT / "frontend" / "src" / "App.svelte"
PAGE = ROOT / "frontend" / "src" / "teile" / "Seitenrahmen.svelte"

# The rule of every look, by its selector in the sheet.
LOOKS = {
    "light": ":root",
    "exe": ":root[data-eigen='dunkel'],\n:root[data-modus='dunkel']",
    "auto": ":root:not([data-modus='hell'], [data-modus='snow'], [data-eigen='hell'])",
    "own": ":root[data-modus='eigen']",
    "own-light": ":root[data-modus='eigen'][data-eigen='hell']",
    "own-dark": ":root[data-modus='eigen'][data-eigen='dunkel']",
    "darkmatter": ":root[data-modus='darkmatter']",
    "heaven": ":root[data-modus='heaven']",
    "moune": ":root[data-modus='moune']",
}
# The looks that mix their gradient into the tile, and the rule that holds
# the frame they mix.
MIXED = {"own-light": "own", "own-dark": "own"}
# The looks whose frame is one flat colour with a drawing on it; their glass
# stays see-through, since one colour under it cannot band.
FLAT = ("exe", "auto", "darkmatter")
# The looks that keep the see-through tile and the frosted menu page although
# the dark set of the system could reach them.
DECLARED_ABSENT = ("own", "heaven", "moune") + FLAT
# What a look draws inside the edge of the tile: a faint line in its accent,
# nothing, or a bright rim.
BARE = ("own-dark",)
LIGHT = ("light", "heaven", "moune")

# A colour of the frame is a variable, or a variable with a variable to fall
# back on: two levels of brackets inside the mix.
NESTED = r"(?:[^()]|\((?:[^()]|\([^()]*\))*\))+"
MIX = re.compile(r"color-mix\(in srgb, (#[0-9a-f]{6}) (\d+)%, (" + NESTED + r")\)")
# The drop shadow every look gives the tile and the menu page.
OUTER = "0 14px 34px -14px rgba(0, 0, 0, 0.55), 0 2px 6px -2px rgba(0, 0, 0, 0.25)"
# One sharp pixel in a fifth of the look's accent: no blur, so it has no
# steps to draw. Green for Exe, violet for Dark Matter.
GREEN_LINE = "inset 0 0 0 1px color-mix(in srgb, var(--gruen) 20%, transparent)"
VIOLET_LINE = "inset 0 0 0 1px color-mix(in srgb, var(--violett) 20%, transparent)"
LINED = {"exe": GREEN_LINE, "auto": GREEN_LINE, "darkmatter": VIOLET_LINE}


def _rule(look: str) -> str:
    sheet = SHEET.read_text(encoding="utf-8")
    found = re.search(r"(?:^|\n)\s*" + re.escape(LOOKS[look]) + r" \{\n([^}]*)\}", sheet)
    assert found, f"the rule of the look {look} is missing"
    return found.group(1)


def _value(look: str, name: str) -> str | None:
    found = re.search(r"^\s*" + re.escape(name) + r": (.+);$", _rule(look), re.MULTILINE)
    return found.group(1) if found else None


def _component_rule(path: Path, selector: str) -> str:
    found = re.search(r"\n  " + re.escape(selector) + r" \{\n(.*?)\n  \}", path.read_text(encoding="utf-8"), re.DOTALL)
    assert found, f"{path.name}: the rule {selector} is missing"
    # Comments explain; only the declarations are read.
    return re.sub(r"/\*.*?\*/", "", found.group(1), flags=re.DOTALL)


def _glass(colour: str) -> tuple[str, int]:
    """A see-through ground as the hex colour and the share a mix needs."""
    found = re.fullmatch(r"rgba\((\d+), (\d+), (\d+), ([\d.]+)\)", colour)
    assert found, f"no see-through colour: {colour}"
    red, green, blue, share = found.groups()
    return f"#{int(red):02x}{int(green):02x}{int(blue):02x}", round(float(share) * 100)


def test_a_look_with_a_gradient_frame_names_it_mixed_with_its_glass():
    """Same angle, same stops as the frame, and every colour mixed with the
    very glass the look gives its chat tile — so the tile shows what the
    see-through glass showed, drawn as one gradient."""
    for look, frame_rule in MIXED.items():
        mixed = _value(look, "--kachel-verlauf")
        assert mixed and mixed.startswith("linear-gradient("), f"{look}: no mixed gradient"
        glass, share = _glass(_value(look, "--kachel-chat") or "")
        mixes = MIX.findall(mixed)
        assert mixes, f"{look}: the gradient mixes nothing"
        assert {(colour, int(part)) for colour, part, _ in mixes} == {(glass, share)}, (
            f"{look}: mixed with {mixes[0][:2]}, the glass is {glass} at {share}"
        )
        # Take the glass out again and the frame's own gradient is left.
        assert MIX.sub(lambda hit: hit.group(3), mixed) == _value(frame_rule, "--frame"), (
            f"{look}: the mixed gradient no longer follows the frame"
        )
        assert _value(look, "--page-frost") == "none", f"{look}: the menu page still blurs its own gradient"


def test_a_look_with_a_flat_frame_keeps_the_see_through_glass_over_it():
    """Over one colour there is nothing to mix and no band to hide: the frame
    is one colour, the tile and the menu page keep the see-through glass,
    and the frost stays on — the drawing on the frame shows through, soft.
    The two dark looks give their glass the same share of their own dark,
    so the tiles differ in colour alone."""
    shares = {}
    for look in FLAT:
        frame = _value(look, "--frame") or ""
        assert re.fullmatch(r"#[0-9a-f]{6}", frame), f"{look}: the frame is not one flat colour: {frame[:40]}"
        assert _value(look, "--kachel-verlauf") == "initial", f"{look}: the tile is not see-through"
        assert _value(look, "--page-frost") == "var(--kachel-frost)", f"{look}: the menu page lost its frost"
        shares[look] = _glass(_value(look, "--kachel-chat") or "")[1]
    assert len(set(shares.values())) == 1, f"the glass of the flat looks differs in share: {shares}"


def test_the_gradient_and_the_frost_are_named_together_in_every_rule():
    """Whatever look the sheet holds, now or later: a rule that mixes its
    gradient turns the frost of the menu page off, and a rule that declares
    the gradient absent gives the frost back. One without the other blurs
    the page's own gradient, or leaves text on see-through glass unfrosted."""
    sheet = SHEET.read_text(encoding="utf-8")
    bodies = [body for body in re.findall(r"\{([^{}]*)\}", sheet) if "--kachel-verlauf:" in body]
    assert len(bodies) == len(MIXED) + len(DECLARED_ABSENT), (
        "a look names the ground of the tile that no check here knows"
    )
    for body in bodies:
        gradient = re.search(r"^\s*--kachel-verlauf: (.+);$", body, re.MULTILINE)
        frost = re.search(r"^\s*--page-frost: (.+);$", body, re.MULTILINE)
        assert gradient and frost, "the mixed gradient stands without the frost of the menu page"
        wanted = "var(--kachel-frost)" if gradient.group(1) == "initial" else "none"
        assert frost.group(1) == wanted, f"gradient {gradient.group(1)[:24]} beside frost {frost.group(1)}"


def test_the_tile_and_the_menu_page_draw_that_gradient_fixed_to_the_window():
    """Both surfaces read the mixed gradient before the see-through ground,
    and hold it to the window as the frame does — set after the ground, or
    the shorthand would take it back."""
    for path, selector in ((APP, "main"), (PAGE, ".seite")):
        lines = [line.strip() for line in _component_rule(path, selector).splitlines()]
        ground = "background: var(--kachel-verlauf, var(--kachel-chat, var(--bg)));"
        assert ground in lines, f"{path.name}: {selector} does not read the mixed gradient"
        assert lines[lines.index(ground) + 1] == "background-attachment: fixed;", (
            f"{path.name}: the gradient of {selector} is not held to the window"
        )
        assert sum(line.startswith("background") for line in lines) == 2, f"{path.name}: a second ground on {selector}"


def test_flat_looks_and_looks_with_drawings_keep_the_see_through_glass():
    """The silence check. The light base names no mixed gradient; the looks
    the dark set of the system can reach declare it absent and their frost
    present, and the menu page takes its blur from that one value."""
    assert _value("light", "--kachel-verlauf") is None
    assert _value("light", "--kachel-frost") == "blur(14px)"
    assert _value("light", "--page-frost") == "var(--kachel-frost)"
    for look in DECLARED_ABSENT:
        assert _value(look, "--kachel-verlauf") == "initial", f"{look}: the dark set's gradient seeps in"
        assert _value(look, "--page-frost") == "var(--kachel-frost)", f"{look}: the menu page lost its frost"
    layer = _component_rule(PAGE, ".seite::before")
    assert "backdrop-filter: var(--page-frost, none);" in layer
    assert "blur(" not in layer, "the frost of the menu page is fixed again instead of following the look"


def test_the_menu_page_wears_the_edge_and_the_shadow_of_the_chat_tile():
    """One value for both, so a menu page stands off the frame exactly as
    the chat does. Its frost lies one pixel inside, or it would blur the
    fine rim the light looks draw."""
    edge = "box-shadow: var(--chat-edge, none);"
    assert edge in _component_rule(APP, "main")
    assert edge in _component_rule(PAGE, ".seite")
    assert "inset: 1px;" in _component_rule(PAGE, ".seite::before")


def test_the_dark_looks_draw_one_faint_line_of_their_accent_inside_the_edge():
    """One sharp pixel in a fifth of the accent, before the drop shadow —
    green in Exe and in the dark set the system asks for, violet in Dark
    Matter, so both tiles stand off their frame the same way. Sharp on
    purpose: a glow fading inwards is left with a few steps of brightness
    that show as rectangles lying inside one another."""
    for look, line in LINED.items():
        edge = _value(look, "--chat-edge") or ""
        assert edge == line + ", " + OUTER, f"{look}: the edge is not the faint line and the drop shadow: {edge}"


def test_a_dark_own_gradient_draws_nothing_inside_the_edge():
    """The silence check for the faint line: the user's dark gradient, which
    otherwise takes Exe's values, takes the line back."""
    for look in BARE:
        edge = _value(look, "--chat-edge") or ""
        assert "inset" not in edge, f"{look}: the edge draws inside the tile: {edge}"
        assert edge == OUTER, f"{look}: the edge is more than the drop shadow: {edge}"


def test_the_light_looks_keep_their_fine_bright_rim():
    """The silence check for the edge: nothing changes where it was right."""
    for look in LIGHT:
        assert _value(look, "--chat-edge") == "inset 0 0 0 1px rgba(255, 255, 255, 0.85), " + OUTER, look


def test_every_look_wears_the_same_drop_shadow():
    """Whatever look the sheet holds, now or later: an edge it names ends
    with the one drop shadow, so no tile stands off its frame further than
    another."""
    edges = re.findall(r"^\s*--chat-edge: (.+);$", SHEET.read_text(encoding="utf-8"), re.MULTILINE)
    assert len(edges) == len(LINED) + len(BARE) + len(LIGHT), (
        "the looks that name an edge are not the ones checked here"
    )
    for edge in edges:
        assert edge.endswith(OUTER), f"an edge with a drop shadow of its own: {edge}"
