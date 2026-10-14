"""Every drawing a surface asks for exists, and nothing lies around unused.

The window names a drawing by a plain string and the drawing component
resolves it against its table at run time; an unknown name yields an empty
drawing by design, so a typo would cost a look its drawing without any
error. These checks read the sources and fail on such a name, on a table
entry no surface asks for, and on a drawing file nothing imports.
"""

import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "src"
COMPONENT = (FRONTEND / "teile" / "Vektorfeld.svelte").read_text(encoding="utf-8")
WINDOW = (FRONTEND / "App.svelte").read_text(encoding="utf-8")
# Moune is the one look that carries drawings; Pearl, Heaven, Exe and Dark
# Matter carry none (tests/test_wuerfelmuster.py).
LOOKS_WITH_DRAWINGS = ("moune",)
MOUNES_DRAWINGS = {"gras", "huegel", "farn", "pusteblume"}


def _table_names() -> set[str]:
    table = COMPONENT[COMPONENT.index("const ZEICHNUNGEN = {") : COMPONENT.index("let { art }")]
    return {m.group(1) or m.group(2) for m in re.finditer(r"^\s+(?:'([\w-]+)'|([\w-]+)): \{ roh:", table, re.M)}


def _asked_names() -> set[str]:
    literal = set(re.findall(r'<Vektorfeld art="([\w-]+)"', WINDOW))
    derived: set[str] = set()
    for line in WINDOW.splitlines():
        if re.search(r"const \w+Zeichnung = \$derived\(", line):
            derived.update(re.findall(r"'([\w-]+)'", line))
    return literal | derived


def test_every_asked_drawing_is_in_the_table():
    asked, table = _asked_names(), _table_names()
    assert asked, "no drawing names found in the window"
    assert asked <= table, f"asked for but not in the table: {sorted(asked - table)}"


def test_every_table_entry_is_asked_for():
    asked, table = _asked_names(), _table_names()
    assert table <= asked, f"in the table but shown nowhere: {sorted(table - asked)}"


def test_every_drawing_file_is_imported():
    imported = set(re.findall(r"from '\.\./stil/([\w/-]+\.svg)\?raw'", COMPONENT))
    on_disk = {
        f"{look}/{path.name}" for look in LOOKS_WITH_DRAWINGS for path in (FRONTEND / "stil" / look).glob("*.svg")
    }
    assert imported <= on_disk, f"imported but missing: {sorted(imported - on_disk)}"
    assert on_disk <= imported, f"on disk but imported nowhere: {sorted(on_disk - imported)}"


def test_the_table_holds_exactly_the_four_drawings_of_moune():
    assert _table_names() == MOUNES_DRAWINGS


def test_moune_keeps_its_four_drawings_with_the_weights_of_its_design():
    """Silence probe: the four stand as they stood, each at its weight."""
    for name, weight in (("gras", "0.34"), ("huegel", "0.289"), ("farn", "0.34"), ("pusteblume", "0.374")):
        assert f"{name}: {{ roh: {name}, deckkraft: {weight} }}," in COMPONENT, name


def test_a_surface_mounts_a_drawing_under_moune_alone():
    """Every drawing of the window sits under `moune` and under no other
    look; the two named per surface for the bars hold nothing else."""
    for hit in re.finditer(r"<Vektorfeld art=", WINDOW):
        before = WINDOW[max(0, hit.start() - 80):hit.start()]
        assert re.search(r"\{#if moune\}\s*(<!--.*?-->\s*)?$", before, re.S), before
    for name in ("leistenZeichnung", "eingabeZeichnung"):
        line = re.search(rf"const {name} = \$derived\((.+)\)", WINDOW).group(1)
        assert re.fullmatch(r"moune \? '[\w-]+' : false", line), line
    assert not re.search(r"\{:else if (heaven|pearl|exe|darkmatter)\}", WINDOW)
