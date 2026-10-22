"""Where the two panels stand, in the settings cascade.

Both panels are dragged and both remember where they were left. That memory
sat in browser storage, so a second window on the same service started over
at the defaults.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app import layoutwahl


def test_alles_kommt_durch():
    assert layoutwahl.wahl_pruefen(
        {
            "leiste_offen": True,
            "leiste_modul": "cli",
            "leiste_breite": 420,
            "seitenleiste_zu": True,
            "seitenleiste_breite": 340,
        }
    ) == {
        "leiste_offen": True,
        "leiste_modul": "cli",
        "leiste_breite": 420,
        "seitenleiste_zu": True,
        "seitenleiste_breite": 340,
    }


def test_die_breiten_bleiben_in_ihren_grenzen():
    """The same bounds the seam clamps the hand to — a width arriving from
    anywhere else must not put a panel in a shape no drag could produce."""
    geklemmt = layoutwahl.wahl_pruefen({"leiste_breite": 9999, "seitenleiste_breite": 10})
    assert geklemmt == {"leiste_breite": 900, "seitenleiste_breite": 285}

    geklemmt = layoutwahl.wahl_pruefen({"leiste_breite": 1, "seitenleiste_breite": 9999})
    assert geklemmt == {"leiste_breite": 364, "seitenleiste_breite": 400}

    # The column's former lower bound and default, as every layout written
    # before the seventh sign carries it: it comes back at the width the
    # row of signs needs today.
    assert layoutwahl.wahl_pruefen({"leiste_breite": 314}) == {"leiste_breite": 364}

    # Silence probe: widths inside the bounds stay as they are.
    geklemmt = layoutwahl.wahl_pruefen({"leiste_breite": 400, "seitenleiste_breite": 340})
    assert geklemmt == {"leiste_breite": 400, "seitenleiste_breite": 340}


def test_nur_bekannte_module():
    assert layoutwahl.wahl_pruefen({"leiste_modul": "gibtsnicht"}) is None
    assert layoutwahl.wahl_pruefen({"leiste_modul": "cronjobs"}) == {"leiste_modul": "cronjobs"}
    # The doc folder is a tool of the rail of its own now, beside the
    # pictures: its name has to survive the cascade like every other one.
    assert layoutwahl.wahl_pruefen({"leiste_modul": "docfolder"}) == {
        "leiste_modul": "docfolder"
    }
    # The guardian module is retired (Stage 7). A layout stored while it
    # still existed must not keep the rail pointing at a panel that is gone —
    # the unknown name is dropped and `aufgeloest` hands out the default.
    assert layoutwahl.wahl_pruefen({"leiste_modul": "waechter"}) is None
    assert layoutwahl.aufgeloest({"leiste_modul": "waechter"})["leiste_modul"] == "cli"


def test_muell_faellt_raus():
    assert layoutwahl.wahl_pruefen("auf") is None
    assert layoutwahl.wahl_pruefen({"leiste_offen": "auf"}) is None
    # A boolean is not a width — otherwise True would land as 1 and clamp
    # itself to the minimum.
    assert layoutwahl.wahl_pruefen({"leiste_breite": True}) is None


def test_die_vorgabe_steht_dahinter():
    """Nothing stored: the sidebar stands folded and the right column stands
    open on the CLI tab at the width that draws the whole wordmark."""
    assert layoutwahl.aufgeloest(None) == {
        "leiste_offen": True,
        "leiste_modul": "cli",
        "leiste_breite": 512,
        "seitenleiste_zu": True,
        "seitenleiste_breite": 285,
    }


def test_a_stored_choice_wins_over_the_default():
    """The silence check: whoever unfolded the sidebar finds it unfolded,
    whoever folded the column finds it folded at the width they left it, and
    what was never stored beside it still comes from the defaults."""
    resolved = layoutwahl.aufgeloest({"seitenleiste_zu": False})
    assert resolved["seitenleiste_zu"] is False
    assert resolved["leiste_offen"] is True
    folded = layoutwahl.aufgeloest({"leiste_offen": False, "leiste_modul": "bilder", "leiste_breite": 400})
    assert (folded["leiste_offen"], folded["leiste_modul"], folded["leiste_breite"]) == (False, "bilder", 400)
    assert folded["seitenleiste_zu"] is True


INTERFACE_DEFAULTS = Path(__file__).resolve().parent.parent / "frontend/src/lib/anzeige.js"


def _literal(value: str) -> bool | int | str:
    """One value of the interface's object as the service would write it."""
    if value in ("true", "false"):
        return value == "true"
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    if value == "PANEL_DEFAULT_WIDTH":
        named = re.search(r"^export const PANEL_DEFAULT_WIDTH = (\d+)$", INTERFACE_DEFAULTS.read_text(encoding="utf-8"), re.M)
        assert named, "anzeige.js names no PANEL_DEFAULT_WIDTH"
        return int(named.group(1))
    assert value.isdigit(), f"anzeige.js holds a default this test cannot read: {value}"
    return int(value)


def test_the_interface_holds_the_same_defaults_as_the_service():
    """Two copies of the defaults: the interface's is the one a fresh
    installation draws from, the service's the one `aufgeloest` lays a
    stored value over. Whoever reads either has to read the same."""
    source = INTERFACE_DEFAULTS.read_text(encoding="utf-8")
    block = re.search(r"export const VORGABE_LAYOUT = \{\n(.*?)\n\}", source, re.S)
    assert block, "anzeige.js names no VORGABE_LAYOUT"
    held = {name: _literal(value) for name, value in re.findall(r"^\s*(\w+): (.+?),?$", block.group(1), re.M)}
    assert held == layoutwahl.VORGABE


RAIL = Path(__file__).resolve().parent.parent / "frontend/src/lib/arbeitsleiste.svelte.js"


def test_the_service_clamps_the_column_where_the_seam_does():
    """The seam's lower bound is what the row of signs at the column's foot
    needs. The service clamps to the same number and the default starts at
    or above it: a default below it was clamped up at every load without
    being stored, and the service took a width no drag could produce."""
    source = RAIL.read_text(encoding="utf-8")
    lowest = re.search(r"^export const BREITE_MIN = (\d+)$", source, re.M)
    widest = re.search(r"^const BREITE_MAX = (\d+)$", source, re.M)
    assert lowest and widest, "arbeitsleiste.svelte.js names no bounds for the column"
    assert layoutwahl.LEISTE_MIN == int(lowest.group(1)) == 364
    assert layoutwahl.LEISTE_MIN <= layoutwahl.VORGABE["leiste_breite"] <= layoutwahl.LEISTE_MAX
    # Silence probes: the upper bound stays, and the sidebar on the left
    # keeps its own, smaller measure.
    assert layoutwahl.LEISTE_MAX == int(widest.group(1)) == 900
    assert layoutwahl.SEITE_MIN == layoutwahl.VORGABE["seitenleiste_breite"] == 285
    assert layoutwahl.SEITE_MAX == 400


STATE = Path(__file__).resolve().parent.parent / "frontend/src/lib/zustand.svelte.js"


def test_the_service_clamps_the_sidebar_where_the_seam_does():
    """The seam of the sidebar clamps the hand to what the row of signs at its
    foot needs, and the service clamps a width that arrives from anywhere else
    to the same two numbers; the default starts on the lower one."""
    source = STATE.read_text(encoding="utf-8")
    lowest = re.search(r"^const SEITEN_MIN = (\d+)$", source, re.M)
    widest = re.search(r"^const SEITEN_MAX = (\d+)$", source, re.M)
    assert lowest and widest, "zustand.svelte.js names no bounds for the sidebar"
    assert layoutwahl.SEITE_MIN == int(lowest.group(1)) == 285
    assert layoutwahl.SEITE_MAX == int(widest.group(1)) == 400
    assert layoutwahl.VORGABE["seitenleiste_breite"] == layoutwahl.SEITE_MIN


def test_a_stored_width_of_the_sidebar_between_the_bounds_stays_and_one_below_comes_back_as_the_bound(client):
    """Silence probe: a layout written while the bound was still 314 keeps its
    width (nothing is rewritten), and one below the new bound is raised to it."""
    for stored in (285, 314, 340, 400):
        answer = client.put("/api/v1/settings/global/layout", json={"wert": {"seitenleiste_breite": stored}})
        assert answer.json()["wert"] == {"seitenleiste_breite": stored}, stored
    answer = client.put("/api/v1/settings/global/layout", json={"wert": {"seitenleiste_breite": 250}})
    assert answer.json()["wert"] == {"seitenleiste_breite": 285}


def test_die_route_speichert_und_gibt_zurueck(client):
    antwort = client.put(
        "/api/v1/settings/global/layout",
        json={"wert": {"leiste_offen": True, "leiste_modul": "notiz", "leiste_breite": 5000}},
    )
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["wert"] == {
        "leiste_offen": True,
        "leiste_modul": "notiz",
        "leiste_breite": 900,
    }

    gelesen = client.get("/api/v1/settings/resolved/layout").json()
    assert gelesen["wert"]["leiste_modul"] == "notiz"


def test_the_route_answers_a_width_below_the_bound_with_the_bound(client):
    """What a window wrote while the default was still 314 comes back as
    the width the column can have."""
    answer = client.put("/api/v1/settings/global/layout", json={"wert": {"leiste_breite": 314}})
    assert answer.status_code == 200, answer.text
    assert answer.json()["wert"] == {"leiste_breite": 364}
    assert client.get("/api/v1/settings/resolved/layout").json()["wert"] == {"leiste_breite": 364}

    # Silence probe: the sidebar on the left may still be stored at 314.
    answer = client.put("/api/v1/settings/global/layout", json={"wert": {"seitenleiste_breite": 314}})
    assert answer.json()["wert"] == {"seitenleiste_breite": 314}


def test_a_fresh_service_leaves_the_sidebar_to_the_interface(client):
    """No layout was ever stored: the route answers without one, so the
    defaults the interface holds are what a fresh installation opens in —
    the reason they must be the same as the service's."""
    answer = client.get("/api/v1/settings/resolved/layout")
    assert answer.status_code == 200, answer.text
    assert "seitenleiste_zu" not in (answer.json().get("wert") or {})


def test_zugeklappt_bleibt_zugeklappt(client):
    client.put("/api/v1/settings/global/layout", json={"wert": {"seitenleiste_zu": True}})
    client.put(
        "/api/v1/settings/global/layout",
        json={"wert": {"seitenleiste_zu": False, "seitenleiste_breite": 340}},
    )
    gelesen = client.get("/api/v1/settings/resolved/layout").json()
    assert gelesen["wert"]["seitenleiste_zu"] is False



# --- The seam's drag: the chat keeps its room, equal widths snap -----------

HANDLE = Path(__file__).resolve().parent.parent / "frontend/src/teile/Seitengriff.svelte"


def _width_for(raw: float, other: float | None, window: float) -> float:
    """Run the seam's own `widthFor` from its module script in node."""
    source = HANDLE.read_text(encoding="utf-8")
    module = re.search(r"<script module>\n(.*?)</script>", source, re.S)
    assert module, "Seitengriff.svelte has no module script"
    # The three numbers come from the arithmetic module the seam imports; a
    # plain `node -e` script cannot import, so they are put in front.
    numbers = re.findall(
        r"^export const \w+ = \d+$",
        (HANDLE.parent.parent / "lib/columnRoom.js").read_text(encoding="utf-8"),
        re.M,
    )
    body = re.sub(r"^\s*import .*\n", "", module.group(1), flags=re.M)
    script = "\n".join(n.replace("export ", "") for n in numbers) + body.replace(
        "export function", "function"
    ) + (
        f"\nconsole.log(JSON.stringify(widthFor({json.dumps(raw)}, "
        f"{json.dumps(other)}, {json.dumps(window)})))\n"
    )
    run = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_a_drag_snaps_to_the_other_columns_width():
    # 1440 window, the other column open at 400: 390 and 410 both land on 400.
    assert _width_for(390, 400, 1440) == 400
    assert _width_for(410, 400, 1440) == 400
    # Silence probe: 17 px away stays where the hand is; a folded column
    # (no width) is nothing to snap to.
    assert _width_for(383, 400, 1440) == 383
    assert _width_for(400, None, 1440) == 400


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_a_drag_leaves_the_chat_420_px():
    # 1280 window, the other column at 400: 1280 - 400 - 16 - 420 = 444.
    assert _width_for(900, 400, 1280) == 444
    # Folded, the other side is its 52 px bar: 1280 - 52 - 16 - 420 = 792.
    assert _width_for(900, None, 1280) == 792
    # Silence probe: a width with room to spare stays.
    assert _width_for(320, 400, 1280) == 320
