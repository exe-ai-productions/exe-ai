"""The assignable microphone key (frontend/src/lib/microphoneKey.js).

Run in node, like tests/test_diktatabgleich.py: what is asserted is what the
real module answers for a sequence of key events.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")

MODULE = Path(__file__).resolve().parent.parent / "frontend/src/lib/microphoneKey.js"
SHORTCUT_LIST = MODULE.with_name("shortcutList.js")


def _node(script: str):
    source = re.sub(r"^export ", "", MODULE.read_text(encoding="utf-8"), flags=re.M)
    run = subprocess.run(["node", "-e", f"{source}\n{script}"], capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _map(layout: dict[str, str]) -> str:
    """A layout map as JavaScript, the way navigator.keyboard hands it over."""
    return f"new Map(Object.entries({json.dumps(layout)}))"


def _hits(combo: str, *events: str, layout: dict[str, str] | None = None) -> list[int]:
    """Feeds events like "+MetaLeft" (down) and "-MetaLeft" (up) and returns
    the positions of the events the recogniser answered true on. With a
    ``layout`` the recogniser asks for it at every press, the way it asks
    the browser for the switched-on one; without one it runs as it does
    where there is no map to have."""
    reader = "" if layout is None else f", () => {_map(layout)}"
    script = f"""
const r = recogniser({json.dumps(combo)}{reader})
const out = [];
{json.dumps(list(events))}.forEach((e, i) => {{
  const ev = {{ code: e.slice(1), repeat: e.endsWith('*') }}
  ev.code = ev.code.replace('*', '')
  if ((e[0] === '+' ? r.down(ev) : r.up(ev))) out.push(i)
}})
console.log(JSON.stringify(out))
"""
    return _node(script)


def _recorded(*events: str, system: str | None = None) -> list[str | None]:
    given = "" if system is None else f"() => null, {json.dumps(system)}"
    script = f"""
const r = recorder({given})
console.log(JSON.stringify({json.dumps(list(events))}.map((e) =>
  e[0] === '+' ? r.down({{ code: e.slice(1) }}) : r.up({{ code: e.slice(1) }}))))
"""
    return _node(script)


def test_cmd_option_alone_fires_once_on_release():
    assert _hits("Meta+Alt", "+MetaLeft", "+AltLeft", "-AltLeft", "-MetaLeft") == [2]


def test_silence_probe_cmd_option_i_opens_the_developer_tools_and_fires_nothing():
    assert _hits("Meta+Alt", "+MetaLeft", "+AltLeft", "+KeyI", "-KeyI", "-AltLeft", "-MetaLeft") == []


def test_silence_probe_cmd_option_d_fires_nothing():
    assert _hits("Meta+Alt", "+MetaLeft", "+AltLeft", "+KeyD", "-KeyD", "-AltLeft", "-MetaLeft") == []


def test_silence_probe_an_extra_modifier_or_one_modifier_fires_nothing():
    assert _hits("Meta+Alt", "+MetaLeft", "+AltLeft", "+ShiftLeft", "-ShiftLeft", "-AltLeft", "-MetaLeft") == []
    assert _hits("Meta+Alt", "+MetaLeft", "-MetaLeft") == []


def test_the_next_press_after_a_spoiled_one_fires_again():
    assert _hits(
        "Meta+Alt",
        "+MetaLeft", "+AltLeft", "+KeyI", "-KeyI", "-AltLeft", "-MetaLeft",
        "+MetaLeft", "+AltLeft", "-MetaLeft", "-AltLeft",
    ) == [8]


def test_a_combination_with_a_key_fires_on_its_keydown_and_not_on_repeat():
    assert _hits("Meta+Shift+KeyD", "+MetaLeft", "+ShiftLeft", "+KeyD", "+KeyD*", "-KeyD", "-ShiftLeft", "-MetaLeft") == [2]
    # The same key without its modifiers is a letter being typed.
    assert _hits("Meta+Shift+KeyD", "+KeyD", "-KeyD") == []


def test_recording_takes_modifiers_alone_or_a_key_with_modifiers():
    assert _recorded("+AltLeft", "+MetaLeft", "-MetaLeft", "-AltLeft") == [None, None, None, "Meta+Alt"]
    assert _recorded("+MetaLeft", "+ShiftLeft", "+KeyD", "-KeyD", "-ShiftLeft", "-MetaLeft") == [
        None, None, "Meta+Shift+KeyD", None, None, None,
    ]


def test_silence_probe_recording_refuses_a_plain_key_and_one_modifier():
    assert _recorded("+KeyD", "-KeyD") == [None, None]
    assert _recorded("+ShiftLeft", "-ShiftLeft") == [None, None]


def test_silence_probe_recording_refuses_typing_and_the_programs_own_shortcuts():
    # Shift or Option with a letter is typing: a capital, a special sign.
    assert _recorded("+ShiftLeft", "+KeyD", "-KeyD", "-ShiftLeft")[1] is None
    assert _recorded("+AltLeft", "+KeyE", "-KeyE", "-AltLeft")[1] is None
    # Copy and New chat already belong to someone.
    assert _recorded("+MetaLeft", "+KeyC", "-KeyC", "-MetaLeft")[1] is None
    assert _recorded("+MetaLeft", "+KeyN", "-KeyN", "-MetaLeft")[1] is None
    # The page's shortcuts answer to Control as well as to Cmd.
    assert _recorded("+ControlLeft", "+KeyN", "-KeyN", "-ControlLeft")[1] is None
    assert _recorded("+ControlLeft", "+KeyD", "-KeyD", "-ControlLeft")[1] == "Control+KeyD"


def test_typing_before_the_key_does_not_spoil_it():
    # A word typed into the field, then Cmd + Option: the first press fires.
    assert _hits("Meta+Alt", "+KeyH", "-KeyH", "+MetaLeft", "+AltLeft", "-AltLeft", "-MetaLeft") == [4]
    # And a stray key before recording does not spoil the recording.
    assert _recorded("+KeyH", "-KeyH", "+MetaLeft", "+AltLeft", "-AltLeft", "-MetaLeft")[-1] == "Meta+Alt"


def test_silence_probe_a_key_without_a_code_records_nothing():
    assert _recorded("+MetaLeft", "+AltLeft", "+", "-AltLeft", "-MetaLeft") == [None, None, None, None, "Meta+Alt"]


def test_the_works_key_is_the_same_on_the_page_and_on_the_service():
    from app.diktatsprachewahl import VORGABE

    assert _node("console.log(JSON.stringify(DEFAULT_KEY))") == VORGABE["microphone_key"]


def test_a_stored_combination_is_read_back_and_shown():
    shown = _node(
        "console.log(JSON.stringify([showCombo(DEFAULT_KEY), showCombo('Alt+Meta+Shift+KeyD'),"
        " parseCombo('KeyD'), parseCombo('Meta+Meta'), parseCombo('')]))"
    )
    assert shown == ["⌘⌥", "⌘⌥⇧D", None, None, None]


# The words on the modifier keys off the Mac, as the page hands them over
# (frontend/src/lib/keyNames.js, here the German ones).
_WORDS = "{ Meta: 'Win', Control: 'Strg', Alt: 'Alt', Shift: 'Umschalt' }"


def test_off_the_mac_a_combination_is_shown_in_the_words_on_its_keys():
    shown = _node(
        f"const names = {_WORDS}\n"
        "console.log(JSON.stringify([showCombo(DEFAULT_KEY, null, names), showCombo('Control+Alt', null, names),"
        " showCombo('Alt+Meta+Shift+KeyD', null, names), showCombo('nonsense', null, names),"
        " showKeys(['Mod', 'Shift'], 'M', names), showKeys(['Shift', 'Mod'], 'Z', names),"
        " showKeys([], 'Esc', names)]))"
    )
    assert shown == ["Win+Alt", "Strg+Alt", "Win+Alt+Umschalt+D", "", "Strg+Umschalt+M", "Strg+Umschalt+Z", "Esc"]


def test_silence_probe_on_the_mac_the_signs_stand_side_by_side_as_before():
    shown = _node(
        "console.log(JSON.stringify([showCombo(DEFAULT_KEY), showCombo('Control+Alt'),"
        " showKeys(['Mod', 'Shift'], 'M'), showKeys(['Shift', 'Mod'], 'Z'), showKeys(['Mod', 'Alt'], 'I'),"
        " showKeys([], 'Esc')]))"
    )
    assert shown == ["⌘⌥", "⌃⌥", "⌘⇧M", "⇧⌘Z", "⌘⌥I", "Esc"]


def test_the_system_is_read_from_the_platform_the_browser_names():
    platforms = ["MacIntel", "macOS", "iPhone", "iPad", "", None, "Win32", "Windows", "Linux x86_64", "Linux", "Android"]
    systems = _node(f"console.log(JSON.stringify({json.dumps(platforms)}.map((p) => systemOf(p ?? undefined))))")
    assert systems == ["mac"] * 6 + ["windows"] * 2 + ["other"] * 3


def _list(system: str, names: str = "null") -> dict[str, dict[str, str]]:
    """The shortcut list for a system (frontend/src/lib/shortcutList.js), run
    behind the module it imports from: each group's title with its rows, a
    row's name with its keys as shown."""
    source = re.sub(r"^(import .*|export )", "", SHORTCUT_LIST.read_text(encoding="utf-8"), flags=re.M)
    groups = _node(f"{source}\nconsole.log(JSON.stringify(shortcutList({json.dumps(system)}, {names})))")
    return {group["title"]: dict(group["rows"]) for group in groups}


_MAC_LIST = {
    "shortcuts.group_window": {
        "shortcuts.new_chat": "⌘N", "shortcuts.settings": "⌘,", "shortcuts.sidebar": "⌘B",
        "shortcuts.tools": "⌘J", "shortcuts.cli": "⌃`", "shortcuts.search": "⌘K",
        "shortcuts.close": "Esc",
    },
    "shortcuts.group_app": {
        "shortcuts.reload": "⌘R", "shortcuts.devtools": "⌘⌥I", "shortcuts.zoom_in": "⌘+",
        "shortcuts.zoom_out": "⌘−", "shortcuts.actual_size": "⌘0", "shortcuts.minimize": "⌘M",
        "shortcuts.close_window": "⌘W", "shortcuts.quit": "⌘Q",
    },
    "shortcuts.group_edit": {
        "shortcuts.undo": "⌘Z", "shortcuts.redo": "⇧⌘Z", "shortcuts.cut": "⌘X",
        "shortcuts.copy": "⌘C", "shortcuts.paste": "⌘V", "shortcuts.select_all": "⌘A",
    },
}


def test_off_the_mac_the_shortcut_list_names_the_keys_the_program_answers_to_there():
    windows = _list("windows", _WORDS)
    assert windows["shortcuts.group_window"] == {
        "shortcuts.new_chat": "Strg+N", "shortcuts.settings": "Strg+,", "shortcuts.sidebar": "Strg+B",
        "shortcuts.tools": "Strg+J", "shortcuts.cli": "Strg+`", "shortcuts.search": "Strg+K",
        "shortcuts.close": "Esc",
    }
    # The menu's roles answer to other keys there, and it has no Quit.
    assert windows["shortcuts.group_app"] == {
        "shortcuts.reload": "Strg+R", "shortcuts.devtools": "Strg+Umschalt+I", "shortcuts.zoom_in": "Strg++",
        "shortcuts.zoom_out": "Strg+−", "shortcuts.actual_size": "Strg+0",
        # Off the Mac there is no Dock to lay a window into: the row has its
        # own name there.
        "shortcuts.minimize_windows": "Strg+M",
        "shortcuts.close_window": "Strg+W",
    }
    assert windows["shortcuts.group_edit"] == {
        "shortcuts.undo": "Strg+Z", "shortcuts.redo": "Strg+Y", "shortcuts.cut": "Strg+X",
        "shortcuts.copy": "Strg+C", "shortcuts.paste": "Strg+V", "shortcuts.select_all": "Strg+A",
    }
    # Anywhere else Redo keeps its key; the rest is as on Windows.
    other = _list("other", _WORDS)
    assert other["shortcuts.group_edit"]["shortcuts.redo"] == "Strg+Umschalt+Z"
    assert other["shortcuts.group_app"] == windows["shortcuts.group_app"]
    assert {**other["shortcuts.group_edit"], "shortcuts.redo": "Strg+Y"} == windows["shortcuts.group_edit"]


def test_silence_probe_on_the_mac_the_shortcut_list_reads_as_before():
    assert _list("mac") == _MAC_LIST


def test_the_page_and_the_overview_show_the_keys_in_the_words_of_the_system():
    """Both places that show the microphone key hand the words on the keys
    to showCombo and take them from the one module that reads the system, so
    the overview and the page cannot name the same key differently; the page
    takes its rows from the list by system and writes no key itself."""
    lib = MODULE.parent
    page = (lib.parent / "teile" / "Shortcuts.svelte").read_text(encoding="utf-8")
    overview = (lib / "settingsState.svelte.js").read_text(encoding="utf-8")
    names = (lib / "keyNames.js").read_text(encoding="utf-8")
    assert "const names = $derived(keyNames())" in page
    assert "shortcutList(system, names)" in page
    assert "showCombo(current, layout.map, names)" in page
    assert "showKeys(['Mod', 'Shift'], 'M', names)" in page
    assert "⌘" not in page
    assert "showCombo(diktat.microphone_key || DEFAULT_KEY, layout.map, keyNames())" in overview
    assert "systemOf(navigator.userAgentData?.platform || navigator.platform)" in names
    assert "if (system === 'mac') return null" in names
    for key in ("key_win", "key_ctrl", "key_alt", "key_shift"):
        assert f"t('shortcuts.{key}')" in names


# What the keys write, as navigator.keyboard.getLayoutMap() answers on a
# German and on a US layout (only the keys the tests press).
_GERMAN = {"BracketRight": "+", "Slash": "-", "Minus": "ß", "KeyZ": "y", "KeyY": "z", "KeyD": "d"}
_US = {"Equal": "=", "Minus": "-", "BracketRight": "]", "Slash": "/", "KeyZ": "z", "KeyY": "y", "KeyD": "d"}


def _with_layout(layout: dict[str, str] | None, expression: str):
    given = "null" if layout is None else _map(layout)
    return _node(f"const layout = {given}\nconsole.log(JSON.stringify({expression}))")


def _usable(layout: dict[str, str] | None, combo: str) -> bool:
    mods, key = combo.rsplit("+", 1)
    return _with_layout(layout, f"isUsable({json.dumps(mods.split('+'))}, {json.dumps(key)}, layout)")


def test_on_a_german_layout_zoom_in_and_out_are_refused_and_shown_by_their_character():
    # "+" and "-" sit on BracketRight and Slash there; both belong to the
    # shell's Zoom In and Zoom Out.
    assert _usable(_GERMAN, "Meta+BracketRight") is False
    assert _usable(_GERMAN, "Meta+Slash") is False
    # Not so with Control: the shell's accelerators read CommandOrControl,
    # which is Command on macOS, and the page has no Control shortcut but
    # its own five — Control + "+" runs nothing of the program's and stays
    # takeable (measured at both revisions).
    assert _usable(_GERMAN, "Control+BracketRight") is True
    assert _with_layout(_GERMAN, "showCombo('Meta+BracketRight', layout)") == "⌘+"
    assert _with_layout(_GERMAN, "showCombo('Meta+Shift+Slash', layout)") == "⌘⇧−"
    # Recording goes by the same rule.
    recorded = _with_layout(
        _GERMAN,
        "(() => { const r = recorder(() => layout); r.down({ code: 'MetaLeft' });"
        " return r.down({ code: 'BracketRight' }) })()",
    )
    assert recorded is None


def test_on_a_german_layout_the_character_and_the_code_are_both_compared():
    # Cmd + Z (Undo) sits on the key the US layout calls Y there.
    assert _usable(_GERMAN, "Meta+KeyY") is False
    # The code stays compared as well: a stored key is read back without a
    # layout, and would be dropped there (Minus writes ß, KeyZ writes y).
    assert _usable(_GERMAN, "Meta+Minus") is False
    assert _usable(_GERMAN, "Meta+KeyZ") is False
    assert _usable(_GERMAN, "Meta+KeyD") is True
    # A letter the layout has no capital of in one character stays as it is.
    assert _with_layout(_GERMAN, "showCombo('Meta+Shift+Minus', layout)") == "⌘⇧ß"


def test_silence_probe_a_us_layout_and_no_layout_behave_as_before():
    for layout in (_US, None):
        assert _usable(layout, "Meta+Equal") is False
        assert _usable(layout, "Meta+Minus") is False
        assert _usable(layout, "Meta+KeyZ") is False
        assert _usable(layout, "Meta+BracketRight") is True
        assert _usable(layout, "Meta+Slash") is True
        assert _usable(layout, "Meta+Shift+KeyD") is True
    assert _with_layout(_US, "showCombo('Meta+Shift+KeyD', layout)") == "⌘⇧D"
    assert _with_layout(None, "showCombo('Meta+BracketRight', layout)") == "⌘BracketRight"
    # Off the Mac the key is named by its character as well, behind the words.
    assert _with_layout(_GERMAN, f"showCombo('Control+BracketRight', layout, {_WORDS})") == "Strg++"


def test_cmd_shift_equals_is_taken_by_its_place_and_a_shifted_key_stays_takeable():
    # Zoom In answers to "=" and, on a US keyboard, to Shift + "=" as well
    # ("+" is Shift and "=" together, fenster-electron/main.js): the place
    # alone refuses both, with and without a map.
    assert _usable(_US, "Meta+Shift+Equal") is False
    assert _usable(None, "Meta+Shift+Equal") is False
    # The Keyboard API names the character a key writes WITHOUT Shift, so a
    # shifted key is judged by its place alone: Shift + BracketRight writes
    # "*" on a German layout, which is nothing of the program's, and the
    # combination stays takeable — as it was before this change.
    assert _usable(_GERMAN, "Meta+Shift+BracketRight") is True
    assert _usable(_GERMAN, "Meta+Shift+Slash") is True
    # Its unshifted neighbour is the taken one, and Shift on a key nobody
    # has stays free: the rule does not spill.
    assert _usable(_GERMAN, "Meta+BracketRight") is False
    assert _usable(_US, "Meta+Shift+KeyD") is True
    assert _usable(_US, "Meta+Shift+Minus") is True


def test_control_is_read_as_cmd_only_where_the_page_answers_to_it():
    # The page's own five answer to Control as well as to Cmd
    # (frontend/src/App.svelte): Control + N is New chat too.
    assert _usable(None, "Control+KeyN") is False
    assert _usable(None, "Control+KeyK") is False
    # The shell's keys answer to Cmd alone, so a Control combination of
    # theirs belongs to nobody and stays takeable — also with a map, where
    # the character would fold it onto a Cmd shortcut.
    assert _usable(None, "Control+KeyX") is True
    assert _usable(_GERMAN, "Control+BracketRight") is True
    assert _usable(_US, "Control+BracketRight") is True


def test_on_a_german_layout_the_recogniser_lets_the_program_s_shortcut_win():
    # A key recorded as "]" under a US layout writes "+" (Zoom In) under a
    # German one. On a US layout the press is the microphone's; on a German
    # one the program's shortcut wins and no dictation starts.
    press = "+MetaLeft", "+BracketRight", "-BracketRight", "-MetaLeft"
    assert _hits("Meta+BracketRight", *press, layout=_US) == [1]
    assert _hits("Meta+BracketRight", *press, layout=_GERMAN) == []
    # Silence probes: the same reading does not silence a free key, and a
    # shifted combination whose place is nobody's keeps firing on German —
    # Shift + BracketRight writes "*" there, not "+".
    assert _hits("Meta+KeyD", "+MetaLeft", "+KeyD", "-KeyD", "-MetaLeft", layout=_GERMAN) == [1]
    assert (
        _hits(
            "Meta+Shift+BracketRight",
            "+MetaLeft", "+ShiftLeft", "+BracketRight", "-BracketRight", "-ShiftLeft", "-MetaLeft",
            layout=_GERMAN,
        )
        == [2]
    )


def test_the_field_marks_a_key_that_the_program_has_under_the_current_layout():
    # What the red word beside the key field goes by: the stored key under
    # the switched-on layout. Recorded on US, switched to German, marked.
    assert _with_layout(_US, "inUse('Meta+BracketRight', layout)") is False
    assert _with_layout(_GERMAN, "inUse('Meta+BracketRight', layout)") is True
    assert _with_layout(_GERMAN, "inUse('Meta+Slash', layout)") is True
    # Silence probes: the works key and a free key are not marked, an
    # unknown text is nothing, and without a map there is nothing to say.
    assert _with_layout(_GERMAN, "inUse('Meta+Alt', layout)") is False
    assert _with_layout(_GERMAN, "inUse('Meta+KeyD', layout)") is False
    assert _with_layout(_GERMAN, "inUse('', layout)") is False
    assert _with_layout(None, "inUse('Meta+BracketRight', layout)") is False


def test_a_stored_key_the_program_has_is_marked_and_still_named():
    # A key the program has may stand in the settings (an older version
    # took it, the API takes any well-formed text): the field names it and
    # the red word stands beside it, instead of a blank field that pretends
    # the key is free. The microphone answers to neither.
    assert _with_layout(_US, "inUse('Meta+Shift+Equal', layout)") is True
    assert _with_layout(_GERMAN, "inUse('Meta+KeyC', layout)") is True
    assert _with_layout(None, "inUse('Meta+Equal', layout)") is True
    named = _with_layout(
        _US,
        "[showCombo('Meta+KeyC', layout), showCombo('Meta+Shift+Equal', layout),"
        " showCombo('nonsense', layout), parseCombo('Meta+Shift+Equal')]",
    )
    assert named == ["⌘C", "⌘⇧=", "", None]


def test_the_layout_reading_answers_null_where_the_browser_has_none():
    # node's navigator has no keyboard, and an engine without the Keyboard
    # API has no such map either: the reading hands back nothing instead of
    # breaking, and everything goes by the code alone.
    assert _node("readLayout().then((map) => console.log(JSON.stringify(map)))") is None
    # An engine without a navigator at all is the same nothing, and so is a
    # refused answer: neither may become an error out of the page.
    assert (
        _node(
            "delete globalThis.navigator;"
            " readLayout().then((map) => console.log(JSON.stringify(map)))"
        )
        is None
    )
    assert (
        _node(
            "navigator.keyboard = { getLayoutMap: () => Promise.reject(new Error('denied')) };"
            " readLayout().then((map) => console.log(JSON.stringify(map)))"
        )
        is None
    )


def test_silence_probe_a_stored_taken_shortcut_still_fires_nothing():
    # Read back without a layout, Copy stays Copy.
    assert _hits("Meta+KeyC", "+MetaLeft", "+KeyC", "-KeyC", "-MetaLeft") == []
    # A layout that arrives only after recording began is used from then on.
    recorded = _node(
        "let layout = null; const r = recorder(() => layout); r.down({ code: 'MetaLeft' });"
        " layout = new Map([['BracketRight', '+']]);"
        " console.log(JSON.stringify(r.down({ code: 'BracketRight' })))"
    )
    assert recorded is None


def _usable_on(system: str, combo: str, layout: dict[str, str] | None = None) -> bool:
    mods, key = combo.rsplit("+", 1)
    return _with_layout(
        layout, f"isUsable({json.dumps(mods.split('+'))}, {json.dumps(key)}, layout, {json.dumps(system)})"
    )


def test_off_the_mac_the_shell_s_shortcuts_hang_on_control():
    """The shell's menu answers to Control off the Mac, so that is where a
    microphone key would run two things at once — and the Windows key with
    one of the menu's letters is nobody's there, as Control is on a Mac."""
    for system in ("windows", "other"):
        for taken in ("Control+KeyR", "Control+KeyW", "Control+KeyM", "Control+KeyC", "Control+Digit0",
                      "Control+Equal", "Control+Shift+Equal", "Control+Shift+KeyM"):
            assert _usable_on(system, taken) is False, (system, taken)
        for free in ("Meta+KeyR", "Meta+KeyW", "Meta+KeyC", "Meta+Shift+KeyM", "Control+KeyD"):
            assert _usable_on(system, free) is True, (system, free)
        # The page's own five answer to both modifiers on every system.
        assert _usable_on(system, "Control+KeyN") is False
        assert _usable_on(system, "Meta+KeyN") is False
    # The character a key writes counts there as well: "+" on a German
    # layout is Zoom In, now on Control.
    assert _usable_on("windows", "Control+BracketRight", _GERMAN) is False
    assert _usable_on("windows", "Control+BracketRight", _US) is True


def test_off_the_mac_the_menu_s_other_keys_are_the_taken_ones():
    """Where the menu answers to other keys off the Mac, those are taken
    and the Mac's are free; an entry the menu does not have there takes
    nothing."""
    for system in ("windows", "other"):
        # The developer tools and pasting without the style: Shift, not Option.
        assert _usable_on(system, "Control+Shift+KeyI") is False
        assert _usable_on(system, "Control+Alt+KeyI") is True
        assert _usable_on(system, "Control+Shift+KeyV") is False
        assert _usable_on(system, "Control+Alt+Shift+KeyV") is True
        # Quit, Hide and Hide Others stand in a menu only a Mac has.
        for free in ("Control+KeyQ", "Control+KeyH", "Control+Alt+KeyH"):
            assert _usable_on(system, free) is True, (system, free)
    # Redo is Control + Y on Windows alone.
    assert _usable_on("windows", "Control+KeyY") is False
    assert _usable_on("windows", "Control+Shift+KeyZ") is True
    assert _usable_on("other", "Control+KeyY") is True
    assert _usable_on("other", "Control+Shift+KeyZ") is False


def test_silence_probe_on_the_mac_the_taken_shortcuts_are_the_ones_from_before():
    """The list a Mac had, combination for combination, whether the system
    is named or left out; and Control with one of the shell's letters stays
    takeable there."""
    before = [
        "Meta+KeyN", "Meta+Comma", "Meta+KeyB", "Meta+KeyJ", "Meta+KeyK", "Meta+Shift+KeyM",
        "Meta+KeyR", "Meta+Alt+KeyI", "Meta+Equal", "Meta+Shift+Equal", "Meta+Minus",
        "Meta+Digit0", "Meta+KeyM",
        "Meta+KeyW", "Meta+KeyQ", "Meta+KeyZ", "Meta+Shift+KeyZ", "Meta+KeyX", "Meta+KeyC",
        "Meta+KeyV", "Meta+KeyA", "Meta+KeyH", "Meta+Alt+KeyH", "Meta+Alt+Shift+KeyV",
    ]
    for combo in before:
        assert _usable_on("mac", combo) is False, combo
        assert _usable(None, combo) is False, combo
    for free in ("Control+KeyR", "Control+KeyW", "Control+KeyY", "Meta+KeyY", "Meta+Shift+KeyI", "Meta+Shift+KeyV"):
        assert _usable_on("mac", free) is True, free
        assert _usable(None, free) is True, free


def test_recording_and_recognising_go_by_the_system_they_are_told():
    """The field records no shortcut of its system, the stored key fires on
    none, and the field marks one: all three ask with the system."""
    press = ("+ControlLeft", "+KeyR", "-KeyR", "-ControlLeft")
    assert _recorded(*press, system="windows")[1] is None
    assert _recorded(*press, system="mac")[1] == "Control+KeyR"
    assert _recorded(*press)[1] == "Control+KeyR"
    win = ("+MetaLeft", "+KeyR", "-KeyR", "-MetaLeft")
    assert _recorded(*win, system="windows")[1] == "Meta+KeyR"
    assert _recorded(*win, system="mac")[1] is None
    fired = _node(
        "const press = (system) => { const r = recogniser('Control+KeyR', () => null, system);"
        " r.down({code: 'ControlLeft'}); return r.down({code: 'KeyR'}) }\n"
        "console.log(JSON.stringify([press('windows'), press('other'), press('mac'), press(undefined),"
        " inUse('Control+KeyR', null, 'windows'), inUse('Control+KeyR', null, 'mac'), inUse('Control+KeyR')]))"
    )
    assert fired == [False, False, True, True, True, False, False]


def test_the_path_field_shows_a_mac_path_only_on_the_mac_and_is_named_by_its_label():
    """The example path is a Mac path: the field carries it as a hint on the
    Mac only, with the same switch as the sentence below it. Its name for a
    screen reader is the label that stands above it, not the hint."""
    folders = (MODULE.parent.parent / "teile" / "Arbeitsordner.svelte").read_text(encoding="utf-8")
    field = folders[folders.index('class="pfadfeld"') : folders.index("/>", folders.index('class="pfadfeld"'))]
    assert "placeholder={system === 'mac' ? t('arbeitsordner.pfad_platzhalter') : undefined}" in field
    assert "aria-label={t('arbeitsordner.oder')}" in field
    # Silence: the name is never the example path, and the sentence below
    # still goes by the system.
    assert "aria-label={t('arbeitsordner.pfad_platzhalter')}" not in folders
    assert "{t(system === 'mac' ? 'arbeitsordner.pfad_hilfe' : 'arbeitsordner.pfad_hilfe_windows')}" in folders
    locales = MODULE.parents[3] / "app" / "locales"
    for language in ("de", "en"):
        texts = json.loads((locales / f"{language}.json").read_text(encoding="utf-8"))["arbeitsordner"]
        assert texts["oder"] and texts["pfad_platzhalter"].startswith("/Users/")


def test_the_page_and_the_bar_tell_the_system_and_two_texts_go_by_it():
    """Whoever asks about the microphone key hands the system over, read in
    the one module that reads it; and the two texts that speak of something
    only a Mac has — the Dock, the Finder — have a wording for elsewhere."""
    parts = MODULE.parent.parent / "teile"
    page = (parts / "Shortcuts.svelte").read_text(encoding="utf-8")
    bar = (parts / "Eingabeleiste.svelte").read_text(encoding="utf-8")
    folders = (parts / "Arbeitsordner.svelte").read_text(encoding="utf-8")
    assert "recorder(() => layout.map, system)" in page
    assert "inUse(current, layout.map, system)" in page
    assert "recogniser(diktat.microphone_key || DEFAULT_KEY, () => layout.map, system)" in bar
    for source in (page, bar, folders):
        assert re.search(r"import \{[^}]*\bsystem\b[^}]*\} from '../lib/keyNames.js'", source)
    assert "{t(system === 'mac' ? 'arbeitsordner.pfad_hilfe' : 'arbeitsordner.pfad_hilfe_windows')}" in folders
    # The Mac keeps its row name, every other system gets the other one.
    assert "shortcuts.minimize" in _list("mac")["shortcuts.group_app"]
    for system in ("windows", "other"):
        rows = _list(system, _WORDS)["shortcuts.group_app"]
        assert "shortcuts.minimize_windows" in rows and "shortcuts.minimize" not in rows
    locales = MODULE.parents[3] / "app" / "locales"
    german = json.loads((locales / "de.json").read_text(encoding="utf-8"))
    english = json.loads((locales / "en.json").read_text(encoding="utf-8"))
    assert german["shortcuts"]["minimize"] == "Im Dock ablegen"
    assert (german["shortcuts"]["minimize_windows"], english["shortcuts"]["minimize_windows"]) == ("Minimieren", "Minimize")
    assert "Finder" in german["arbeitsordner"]["pfad_hilfe"] and "⌥⌘C" in german["arbeitsordner"]["pfad_hilfe"]
    for texts in (german, english):
        elsewhere = texts["arbeitsordner"]["pfad_hilfe_windows"]
        assert "Explorer" in elsewhere and "⌘" not in elsewhere and "Finder" not in elsewhere
