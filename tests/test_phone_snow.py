"""Snow on the phone page.

The phone page draws Exe, Pearl and Snow. Snow is offered in the list of the
look settings and at the first start, a Snow chosen on the desktop is shown
as Snow, and "auto" on a light device wears Snow, as it does on the desktop.
The other looks of the desktop (Dark Matter, Heaven, Moune, own gradient)
stay Exe on the phone.

The rule is a pure function in an import-free module, so it runs here exactly
as the page runs it.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from tests.conftest import node_script

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend" / "src"
PHONE = FRONTEND / "phone"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")


def _run(module: str, body: str):
    script = f"""
import * as m from {json.dumps((PHONE / module).as_uri())}
const result = (() => {{
{body}
}})()
console.log(JSON.stringify(result))
"""
    done = node_script(script)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


@needs_node
def test_snow_stays_snow_on_a_dark_and_on_a_light_device():
    result = _run("look.js", "return [m.phoneLook('snow', true), m.phoneLook('snow', false)]")
    assert result == ["snow", "snow"]


@needs_node
def test_auto_wears_exe_on_a_dark_device_and_snow_on_a_light_one():
    result = _run("look.js", "return [m.phoneLook('auto', true), m.phoneLook('auto', false)]")
    assert result == ["dunkel", "snow"]


@needs_node
def test_silence_pearl_and_the_looks_the_phone_does_not_draw_are_what_they_were():
    result = _run(
        "look.js",
        """
        return {
          pearl: [m.phoneLook('hell', true), m.phoneLook('hell', false)],
          exe: [m.phoneLook('dunkel', true), m.phoneLook('dunkel', false)],
          others: ['darkmatter', 'heaven', 'moune', 'eigen'].map((mode) => m.phoneLook(mode, false)),
        }
        """,
    )
    assert result == {"pearl": ["hell", "hell"], "exe": ["dunkel", "dunkel"], "others": ["dunkel"] * 4}


@needs_node
def test_the_settings_row_names_snow_as_snow_and_the_other_looks_as_before():
    result = _run(
        "settings.js",
        """
        return {
          snow: m.shownLook('snow'),
          kept: ['auto', 'hell'].map((mode) => m.shownLook(mode)),
          others: ['dunkel', 'darkmatter', 'heaven', 'moune', 'eigen'].map((mode) => m.shownLook(mode)),
        }
        """,
    )
    assert result == {"snow": "snow", "kept": ["auto", "hell"], "others": ["dunkel"] * 5}


def test_the_constant_of_snow_stands_beside_the_other_two():
    source = (PHONE / "look.js").read_text(encoding="utf-8")
    assert "export const LOOK_SNOW = 'snow'" in source
    assert "export const LOOK_EXE = 'dunkel'" in source and "export const LOOK_PEARL = 'hell'" in source


def test_the_look_page_offers_snow_with_the_name_of_the_desktop():
    page = (PHONE / "settings" / "Look.svelte").read_text(encoding="utf-8").split("</script>")[0]
    assert re.findall(r"value: '(\w+)'", page) == ["auto", "dunkel", "hell", "snow"]
    assert "{ value: 'snow', label: t('einstellungen.snow') }" in page


def test_the_first_start_offers_exe_pearl_and_snow_side_by_side():
    page = (PHONE / "FirstStart.svelte").read_text(encoding="utf-8")
    assert "import { LOOK_EXE, LOOK_PEARL, LOOK_SNOW } from './look.js'" in page
    assert "aria-pressed={look === LOOK_SNOW} onclick={() => onlook(LOOK_SNOW)}" in page
    assert page.index("LOOK_EXE)}") < page.index("LOOK_PEARL)}") < page.index("LOOK_SNOW)}")


@pytest.mark.parametrize("language", ["de", "en"])
def test_the_name_of_snow_stands_in_both_catalogues(language: str):
    catalogue = json.loads((ROOT / "app" / "locales" / f"{language}.json").read_text(encoding="utf-8"))
    assert catalogue["einstellungen"]["snow"] == "Snow"


def test_silence_the_desktop_does_not_read_the_phone_rule():
    for folder in ("teile", "lib"):
        for path in (FRONTEND / folder).rglob("*"):
            if path.suffix in {".svelte", ".js"}:
                assert "phone/look.js" not in path.read_text(encoding="utf-8"), path.name
