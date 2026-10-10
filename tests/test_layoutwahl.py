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
    assert geklemmt == {"leiste_breite": 900, "seitenleiste_breite": 314}

    geklemmt = layoutwahl.wahl_pruefen({"leiste_breite": 1, "seitenleiste_breite": 9999})
    assert geklemmt == {"leiste_breite": 314, "seitenleiste_breite": 400}

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
    assert layoutwahl.aufgeloest({"leiste_modul": "waechter"})["leiste_modul"] == "terminal"


def test_muell_faellt_raus():
    assert layoutwahl.wahl_pruefen("auf") is None
    assert layoutwahl.wahl_pruefen({"leiste_offen": "auf"}) is None
    # A boolean is not a width — otherwise True would land as 1 and clamp
    # itself to the minimum.
    assert layoutwahl.wahl_pruefen({"leiste_breite": True}) is None


def test_die_vorgabe_steht_dahinter():
    """Nothing stored: both panels stand folded, the basic state a fresh
    installation opens in."""
    assert layoutwahl.aufgeloest(None) == {
        "leiste_offen": False,
        "leiste_modul": "terminal",
        "leiste_breite": 314,
        "seitenleiste_zu": True,
        "seitenleiste_breite": 314,
    }


def test_a_stored_choice_wins_over_the_folded_default():
    """The silence check: whoever unfolded the sidebar finds it unfolded,
    and what was never stored beside it still comes from the defaults."""
    resolved = layoutwahl.aufgeloest({"seitenleiste_zu": False})
    assert resolved["seitenleiste_zu"] is False
    assert resolved["leiste_offen"] is False
    assert layoutwahl.aufgeloest({"leiste_offen": True})["seitenleiste_zu"] is True


INTERFACE_DEFAULTS = Path(__file__).resolve().parent.parent / "frontend/src/lib/anzeige.js"


def _literal(value: str) -> bool | int | str:
    """One value of the interface's object as the service would write it."""
    if value in ("true", "false"):
        return value == "true"
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
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
    script = module.group(1).replace("export function", "function") + (
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
