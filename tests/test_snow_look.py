"""Snow, the white look: Pearl without its hue, one step lighter.

Twenty values differ from Pearl's, everything else is inherited from the root
block. The look that follows a light device wears Snow too, the one that
follows a dark device stays Exe. The sheet is read in a real browser (the
cascade, the dark device emulated); the lists, the names and the command-line
table are read from their sources.

Skipped where there is no Chrome, like the other browser tests.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest

from app import appfenster, moduswahl, prozessstopp
from cli import themes

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SHEET = FRONTEND / "src/stil/global.css"

SNOW = {
    "--bg": "#eaeaea",
    "--rahmen-vorgabe-1": "#eaeaea",
    "--rahmen-vorgabe-2": "#eaeaea",
    "--rahmen-vorgabe-3": "#eaeaea",
    "--rahmen-vorgabe-4": "#eaeaea",
    "--bg-leiste": "#e2e2e2",
    "--bg-seite": "#e2e2e2",
    "--bg-erhoben": "#f7f7f7",
    "--bg-hoch": "#ffffff",
    "--blase": "#e5e5e5",
    "--code-bg": "#f4f4f4",
    "--linie": "#d2d2d2",
    "--linie-stark": "#b8b8b8",
    "--kontrast": "#b8b8b8",
    "--text": "#1c1c1c",
    "--text-leise": "#424242",
    "--feldstrich": "#828282",
    "--indicator-empty": "#7a7a7a",
    "--sx-komm": "#7a7a7a",
    "--code-vordergrund": "#272727",
}

PEARL = {
    "--bg": "#e0d7c3",
    "--rahmen-vorgabe-1": "#e0d7c3",
    "--bg-leiste": "#d9cfba",
    "--bg-seite": "#d9cfba",
    "--bg-erhoben": "#ece4d3",
    "--bg-hoch": "#f3ecdc",
    "--blase": "#dbd2bd",
    "--code-bg": "#eae1cf",
    "--linie": "#cabfa6",
    "--linie-stark": "#b1a687",
    "--kontrast": "#b1a687",
    "--text": "#201c14",
    "--text-leise": "#484135",
    "--feldstrich": "#928057",
    "--indicator-empty": "#817776",
    "--sx-komm": "#7d7a71",
    "--code-vordergrund": "#2a2620",
}

EXE_GROUND = "#1c1c1a"
EXE_TEXT = "#ecebe6"


def _sheet() -> str:
    return SHEET.read_text(encoding="utf-8")


def _block(selector: str) -> dict[str, str]:
    """The declarations of the rule whose selector list is exactly `selector`."""
    found = re.search(re.escape(selector) + r" \{\n([\s\S]*?)\n\}", _sheet())
    assert found, f"no rule for {selector}"
    return dict(re.findall(r"^\s*(--[a-z0-9-]+): ([^;]+);", found.group(1), re.M))


def test_snow_sets_exactly_the_twenty_values_and_no_other():
    block = _block(":root[data-modus='snow'],\n:root:not([data-modus])")
    assert block == SNOW


def test_snow_stands_after_pearl_and_before_the_dark_sets():
    sheet = _sheet()
    snow = sheet.index(":root[data-modus='snow'],")
    assert sheet.index(":root {") < snow < sheet.index(":root[data-modus='dunkel'] {")
    assert snow < sheet.index("@media (prefers-color-scheme: dark)")


def test_a_dark_device_leaves_snow_alone_as_it_leaves_pearl_alone():
    rule = ":root:not([data-modus='hell'], [data-modus='snow'], [data-eigen='hell']) {"
    assert rule in _sheet()


def test_snow_is_in_the_list_of_the_service_and_of_the_page():
    assert "snow" in moduswahl.MODI
    assert moduswahl.wahl_pruefen({"modus": "snow"}) == {"modus": "snow"}
    modes = (FRONTEND / "src/lib/anzeige.js").read_text(encoding="utf-8")
    assert "'moune', 'snow', 'eigen'" in modes


@pytest.mark.parametrize("name", ["Erststart", "SystemPrompt"])
def test_snow_is_offered_where_the_look_is_chosen(name):
    source = (FRONTEND / f"src/teile/{name}.svelte").read_text(encoding="utf-8")
    assert "['snow', 'einstellungen.snow']" in source
    assert source.index("'einstellungen.moune'") < source.index("'einstellungen.snow'")


def test_snow_has_its_name_and_its_picture():
    for language in ("en", "de"):
        catalogue = json.loads((ROOT / f"app/locales/{language}.json").read_text(encoding="utf-8"))
        assert catalogue["einstellungen"]["snow"] == "Snow"
        assert "snow" in catalogue["cli"]["theme_auto"]
        assert "pearl" not in catalogue["cli"]["theme_auto"]
    preview = (FRONTEND / "src/lib/looksvorschau.js").read_text(encoding="utf-8")
    assert "grund: '#eaeaea'" in preview
    assert "tinte: '28, 28, 28'" in preview
    assert "snow: 'snow'" in preview
    picture = (FRONTEND / "src/teile/Looksvorschau.svelte").read_text(encoding="utf-8")
    assert "VORSCHAU.snow, ausschnitt: 'inset(0 50% 0 0)'" in picture
    assert "VORSCHAU.pearl" not in picture


def test_the_look_that_follows_a_light_device_is_snow_in_every_reader():
    state = (FRONTEND / "src/lib/zustand.svelte.js").read_text(encoding="utf-8")
    assert "return geraet.dunkel ? 'dunkel' : 'snow'" in state
    assert "if (schema === 'hell') return attr === 'hell'" in state
    assert "if (schema === 'snow') return attr === 'snow' || (attr === null && !geraet.dunkel)" in state
    terminal = (FRONTEND / "src/lib/windowTerminal.js").read_text(encoding="utf-8")
    assert "snow: 'snow'" in terminal
    assert "? 'exe' : 'snow'" in terminal
    # The own gradient that stands light keeps Pearl's name in the terminal.
    assert "=== 'hell' ? 'pearl' : 'exe'" in terminal


def test_the_command_line_has_snow_after_pearl_and_follows_a_light_machine_with_it():
    names = list(themes.available())
    assert names.index("snow") == names.index("pearl") + 1
    snow = themes.get("snow")
    assert snow.colours["ground"] == "#eaeaea"
    assert snow.colours["text"] == "#1c1c1c"
    assert themes._AUTO_LIGHT.colours == snow.colours
    assert themes._AUTO_DARK.colours == themes.get("exe").colours
    assert themes.get("pearl").colours["ground"] == "#e0d7c3"


# --- The sheet, in a browser ------------------------------------------------------------

needs_chrome = pytest.mark.skipif(appfenster._programm() is None, reason="no Chrome on this machine")

CASES = [
    # (attributes on the root, device scheme)
    ({"data-modus": "snow"}, "light"),
    ({"data-modus": "snow"}, "dark"),
    ({}, "light"),
    ({}, "dark"),
    ({"data-modus": "hell"}, "light"),
    ({"data-modus": "hell"}, "dark"),
    ({"data-modus": "eigen", "data-eigen": "hell"}, "light"),
]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _measure(port: int) -> list[dict[str, str]]:
    websockets = pytest.importorskip("websockets")
    end = time.monotonic() + 60
    address = None
    while time.monotonic() < end and address is None:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2) as response:
                for page in json.load(response):
                    if page.get("type") == "page" and "sheet.html" in page.get("url", ""):
                        address = page["webSocketDebuggerUrl"]
        except OSError:
            pass
        if address is None:
            await asyncio.sleep(0.2)
    assert address, "Chrome did not open the page"
    names = sorted(set(SNOW) | set(PEARL))
    answers: list[dict[str, str]] = []
    async with websockets.connect(address, max_size=16 * 1024 * 1024) as connection:
        counter = 0

        async def call(method: str, params: dict) -> dict:
            nonlocal counter
            counter += 1
            number = counter
            await connection.send(json.dumps({"id": number, "method": method, "params": params}))
            while True:
                answer = json.loads(await connection.recv())
                if answer.get("id") == number:
                    return answer

        for attributes, scheme in CASES:
            await call("Emulation.setEmulatedMedia", {
                "features": [{"name": "prefers-color-scheme", "value": scheme}],
            })
            script = f"""(() => {{
                const root = document.documentElement
                for (const name of ['data-modus', 'data-eigen']) root.removeAttribute(name)
                for (const [name, value] of Object.entries({json.dumps(attributes)})) root.setAttribute(name, value)
                const style = getComputedStyle(root)
                return JSON.stringify(Object.fromEntries({json.dumps(names)}.map((n) => [n, style.getPropertyValue(n).trim()])))
            }})()"""
            answer = await call("Runtime.evaluate", {"expression": script, "returnByValue": True})
            assert "exceptionDetails" not in answer["result"], answer["result"]
            answers.append(json.loads(answer["result"]["result"]["value"]))
    return answers


@pytest.fixture(scope="module")
def measured() -> list[dict[str, str]]:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = Path(tempfile.mkdtemp(prefix="snow-look-"))
    try:
        page = folder / "sheet.html"
        page.write_text(
            f"<!doctype html><meta charset=utf-8><style>{_sheet()}</style><p>x</p>",
            encoding="utf-8",
        )
        port = _free_port()
        browser = subprocess.Popen(
            [
                program, "--headless=new", "--disable-gpu", "--no-first-run", "--mute-audio",
                "--disable-background-networking", "--allow-file-access-from-files",
                f"--remote-debugging-port={port}", f"--user-data-dir={folder / 'profile'}",
                page.as_uri(),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            return asyncio.run(_measure(port))
        finally:
            prozessstopp.beenden(browser, frist=5)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _case(measured: list[dict[str, str]], attributes: dict, scheme: str) -> dict[str, str]:
    return measured[CASES.index((attributes, scheme))]


@needs_chrome
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_snow_chosen_by_name_is_white_on_a_light_and_on_a_dark_device(measured, scheme):
    got = _case(measured, {"data-modus": "snow"}, scheme)
    assert {name: got[name] for name in SNOW} == SNOW


@needs_chrome
def test_the_look_that_follows_the_device_is_snow_on_a_light_one_and_exe_on_a_dark_one(measured):
    light = _case(measured, {}, "light")
    assert {name: light[name] for name in SNOW} == SNOW
    dark = _case(measured, {}, "dark")
    assert dark["--bg"] == EXE_GROUND
    assert dark["--text"] == EXE_TEXT


@needs_chrome
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_pearl_keeps_every_value(measured, scheme):
    got = _case(measured, {"data-modus": "hell"}, scheme)
    assert {name: got[name] for name in PEARL} == PEARL


@needs_chrome
def test_the_light_own_gradient_still_wears_pearls_values(measured):
    got = _case(measured, {"data-modus": "eigen", "data-eigen": "hell"}, "light")
    # Its frame is its own gradient; every other value is Pearl's.
    pearl = {name: value for name, value in PEARL.items() if name != "--rahmen-vorgabe-1"}
    assert {name: got[name] for name in pearl} == pearl
