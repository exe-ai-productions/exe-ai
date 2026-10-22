"""The settings page of the phone: the groups and their order against the
desktop's own list, and how the pages are wired to the shared parts.

The phone's table (`phone/settings.js`) has no imports, so it runs here as it
ships; so does the desktop's list (`lib/einstellungsliste.js`). Nothing may be
missing on the phone — and the check itself is shown to notice a missing row
(the silence test), because a check that cannot fail proves nothing.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SRC = FRONTEND / "src"
PHONE = SRC / "phone"
DESKTOP = SRC / "teile" / "SystemPrompt.svelte"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")


def _phone_table() -> dict:
    driver = FRONTEND / f"phone_settings.{os.getpid()}.check.mjs"
    driver.write_text(
        "import { ENTRIES, GROUPS, TEXT_KINDS } from './src/phone/settings.js'\n"
        "console.log(JSON.stringify({ ENTRIES, GROUPS, TEXT_KINDS }))\n",
        encoding="utf-8",
    )
    try:
        done = subprocess.run(
            ["node", driver.name], cwd=FRONTEND, capture_output=True, text=True, timeout=60
        )
    finally:
        driver.unlink(missing_ok=True)
    assert done.returncode == 0, (done.stdout + done.stderr)[-2000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def _desktop_table() -> dict:
    """The pages and the groups of the desktop's list of the settings: the
    rows that lead to a page of the settings window, as the list names them
    (`lib/einstellungsliste.js`, plain data like the phone's table)."""
    driver = FRONTEND / f"desktop_settings.{os.getpid()}.check.mjs"
    driver.write_text(
        "import { GRUPPEN, SEITEN } from './src/lib/einstellungsliste.js'\n"
        "console.log(JSON.stringify({ GRUPPEN, SEITEN }))\n",
        encoding="utf-8",
    )
    try:
        done = subprocess.run(
            ["node", driver.name], cwd=FRONTEND, capture_output=True, text=True, timeout=60
        )
    finally:
        driver.unlink(missing_ok=True)
    assert done.returncode == 0, (done.stdout + done.stderr)[-2000:]
    table = json.loads(done.stdout.strip().splitlines()[-1])
    # A page marked desktop-only has no row on the phone.
    desktop_only = {
        row["ziel"]["art"] for group in table["GRUPPEN"] for row in group["zeilen"] if row.get("desktopOnly")
    }
    entries = {
        key: {"sign": page["zeichen"], "title": page["titel"]}
        for key, page in table["SEITEN"].items()
        if key not in desktop_only
    }
    groups = []
    for group in table["GRUPPEN"]:
        pages = [
            row["ziel"]["art"]
            for row in group["zeilen"]
            if row["ziel"].get("art") and not row.get("desktopOnly")
        ]
        # A group with no page of the settings (the models) has no row here.
        if pages:
            groups.append({"name": group["name"], "title": group["titel"], "entries": pages})
    return {"ENTRIES": entries, "GROUPS": groups, "DESKTOP_ONLY": sorted(desktop_only)}


def _differences(desktop: dict, phone: dict) -> list[str]:
    """What the phone lacks or says differently, in words; empty when equal."""
    found = []
    if [g["name"] for g in phone["GROUPS"]] != [g["name"] for g in desktop["GROUPS"]]:
        found.append("the groups differ in name or order")
    for group in desktop["GROUPS"]:
        mine = next((g for g in phone["GROUPS"] if g["name"] == group["name"]), None)
        if mine is None:
            continue
        if mine["title"] != group["title"]:
            found.append(f"group {group['name']}: other title")
        if mine["entries"] != group["entries"]:
            found.append(f"group {group['name']}: the rows differ in content or order")
    for key, entry in desktop["ENTRIES"].items():
        if phone["ENTRIES"].get(key) != entry:
            found.append(f"entry {key}: missing or another sign or title")
    return found


# ——— the groups and their order ———


@needs_node
def test_the_phone_lists_every_group_and_row_of_the_desktop_in_its_order():
    desktop, phone = _desktop_table(), _phone_table()
    # the read itself found something: four groups with pages, fourteen entries
    assert len(desktop["GROUPS"]) == 4 and len(desktop["ENTRIES"]) == 14
    # the flag is read where the list spells it: a page left out for that reason is found
    assert desktop["DESKTOP_ONLY"] == ["web_app"]
    assert _differences(desktop, phone) == []


@needs_node
def test_silence_a_missing_or_moved_row_is_noticed():
    desktop, phone = _desktop_table(), _phone_table()
    gone = json.loads(json.dumps(phone))
    gone["GROUPS"][1]["entries"].remove("cronjobs")
    assert _differences(desktop, gone)
    moved = json.loads(json.dumps(phone))
    moved["GROUPS"][0]["entries"].reverse()
    assert _differences(desktop, moved)
    unnamed = json.loads(json.dumps(phone))
    del unnamed["ENTRIES"]["skills"]
    assert _differences(desktop, unnamed)
    resigned = json.loads(json.dumps(phone))
    resigned["ENTRIES"]["system"]["sign"] = "other"
    assert _differences(desktop, resigned)


@needs_node
def test_every_row_of_a_group_has_an_entry_and_every_entry_stands_in_a_group():
    phone = _phone_table()
    rows = [key for group in phone["GROUPS"] for key in group["entries"]]
    assert sorted(rows) == sorted(phone["ENTRIES"])
    assert len(rows) == len(set(rows))
    # the entries that are a text kept as a whole
    assert phone["TEXT_KINDS"] == ["system", "memory", "konfiguration", "zugangsdaten", "tools_datei"]


# ——— the wiring of the page ———


def _page() -> str:
    return (PHONE / "pages" / "Settings.svelte").read_text(encoding="utf-8")


def test_the_page_stands_in_the_foot_of_the_drawer_and_reads_the_table():
    page = _page()
    assert "place: 'foot'" in page and "name: 'settings'" in page
    assert "from '../settings.js'" in page
    assert "{#each GROUPS as group (group.name)}" in page


def test_each_row_opens_a_view_with_its_way_back_and_the_tools_open_their_own_page():
    page = _page()
    assert "<SubHead title={t(ENTRIES[at].title)} onback={back} />" in page
    # leaving a page with an unsaved text asks first
    assert "if (dirty && !(await discard())) return" in page
    assert "const discard = () => frage(t('agenten.verwerfen_frage'))" in page
    assert "pageOpen('tools')" in page
    for view in ("Language", "Look", "Meldewahl", "Shortcuts", "Skillmaske", "Cronjobs", "Agents", "Verbindungen", "TextFile"):
        assert f"<{view}" in page


def test_the_look_page_offers_only_auto_exe_pearl_and_snow_and_the_page_that_owns_the_look_saves_it():
    look = (PHONE / "settings" / "Look.svelte").read_text(encoding="utf-8")
    offered = re.findall(r"value: '(\w+)'", look.split("</script>")[0])
    assert offered == ["auto", "dunkel", "hell", "snow"]
    # a pick goes to the holder of the look, never around it
    assert "onpick={pickLook}" in look
    holder = (PHONE / "Phone.svelte").read_text(encoding="utf-8")
    assert "lookPick.mode = mode" in holder
    assert "if (lookPick.count) untrack(() => chooseLook(lookPick.value))" in holder
    store = (PHONE / "phone.svelte.js").read_text(encoding="utf-8")
    assert "export const lookPick" in store and "export function pickLook" in store


def test_the_numbers_and_switches_of_the_texts_are_the_desktops_one_holder():
    file = (PHONE / "settings" / "TextFile.svelte").read_text(encoding="utf-8")
    assert "useSettingsValues" in file
    # no second copy of the rules for the numbers
    assert "api.einstellungAufgeloest" not in file
    desktop = DESKTOP.read_text(encoding="utf-8")
    assert "useSettingsValues" in desktop
    values = (SRC / "lib" / "settingsvalues.svelte.js").read_text(encoding="utf-8")
    for name in ("werkzeugRundenLaden", "befehlZeitLaden", "verdichtungSchwelleLaden", "gedaechtnisSchalten"):
        assert name in values
        assert f"function {name}" not in desktop


def test_the_system_prompt_and_the_other_texts_load_and_save_through_the_same_calls_as_the_desktop():
    file = (PHONE / "settings" / "TextFile.svelte").read_text(encoding="utf-8")
    for call in ("api.systemPrompt()", "api.systemPromptSichern(", "api.gedaechtnis()", "api.gedaechtnisSichern(",
                 "api.werkzeugKonfiguration()", "api.werkzeugKonfigurationSichern(", "api.datei(kind)"):
        assert call in file
    # the field shows what the service stored after a save
    assert "loaded = data.text" in file


def test_a_form_field_on_the_phone_is_never_smaller_than_the_size_that_makes_the_page_zoom():
    page = (PHONE / "Phone.svelte").read_text(encoding="utf-8")
    assert "html[data-phone]" in page
    rule = re.search(r"html\[data-phone\][^{]*\{[^}]*font-size:\s*16px\s*!important", page, re.S)
    assert rule
    assert "setAttribute('data-phone'" in page


def test_the_texts_of_the_phone_page_exist_in_both_catalogues():
    de = json.loads((ROOT / "app" / "locales" / "de.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "app" / "locales" / "en.json").read_text(encoding="utf-8"))
    table = _phone_table()
    keys = [e["title"] for e in table["ENTRIES"].values()] + [g["title"] for g in table["GROUPS"]]
    for key in keys + ["menue.settings", "menue.hilfe", "agenten.verwerfen_frage"]:
        for catalogue in (de, en):
            node = catalogue
            for part in key.split("."):
                assert part in node, key
                node = node[part]
            assert isinstance(node, str) and node


# ——— nothing unsaved is lost, nothing unread is overwritten ———


def test_leaving_the_page_by_its_back_button_or_the_drawer_asks_while_something_is_unsaved():
    page, store = _page(), (PHONE / "pages.svelte.js").read_text(encoding="utf-8")
    drawer = (PHONE / "Drawer.svelte").read_text(encoding="utf-8")
    assert "pageLeave.guard = discard" in page
    assert "pageLeave.guard === discard" in page
    # with nothing unsaved the page is left at once; otherwise after the answer
    assert "if (!pageLeave.guard) return go()" in store
    assert "pageLeave.guard().then((ok) => (ok ? go() : false))" in store
    # a chat, a new chat and a tool row each ask before an open page goes
    assert drawer.count("if (!(await pageClose())) return") == 3


def test_a_text_that_could_not_be_read_is_not_offered_as_an_empty_one():
    file = (PHONE / "settings" / "TextFile.svelte").read_text(encoding="utf-8")
    assert "failed = true" in file
    assert "disabled={busy || failed}" in file
    assert "onclick={save} disabled={!dirty || failed}" in file


def test_the_counts_on_the_list_are_read_again_when_a_view_is_left():
    page = _page()
    back = re.search(r"async function back\(\) \{\n(.*?)\n  \}", page, re.S)
    assert back and "countsRead()" in back.group(1)


def test_the_look_row_names_the_look_the_page_is_drawn_in():
    page = _page()
    assert "t('einstellungen.' + shownLook(lookPick.mode))" in page
    table = (PHONE / "settings.js").read_text(encoding="utf-8")
    assert "export function shownLook" in table
