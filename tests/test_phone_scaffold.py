"""The phone page's scaffold: when it is shown, which look it wears, and
what a swipe from the left edge does.

All three are pure functions in import-free modules (`frontend/src/phone/`),
so they run here exactly as the page runs them.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests.conftest import node_script

PHONE = Path(__file__).resolve().parent.parent / "frontend" / "src" / "phone"
LIB = PHONE.parent / "lib"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")


def _run(module: str, body: str, folder: Path = PHONE):
    script = f"""
import * as m from {json.dumps((folder / module).as_uri())}
const result = (() => {{
{body}
}})()
console.log(JSON.stringify(result))
"""
    done = node_script(script)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_the_page_mounts_the_phone_page_where_the_switch_says_so():
    """The switch is only worth something if main.js asks it — at the start
    and on every change of the answer."""
    source = (PHONE.parent / "main.js").read_text(encoding="utf-8")
    assert "mount(isPhoneNow() ? Phone : App" in source
    assert "watchDevice((phone) => {" in source
    assert "mount(phone ? Phone : App" in source


def test_the_switch_cuts_at_600_wide_without_touch():
    result = _run(
        "device.js",
        """
        return {
          narrow: m.isPhone(599, false),
          edge: m.isPhone(600, false),
          wide: m.isPhone(1440, false),
        }
        """,
    )
    assert result == {"narrow": True, "edge": False, "wide": False}


def _touch_window(width: int, height: int, touch: bool) -> str:
    """A window object as the page sees it: its size, and whether the main
    input is a finger (what `matchMedia('(pointer: coarse)')` answers)."""
    return f"""{{
      innerWidth: {width}, innerHeight: {height},
      matchMedia: (query) => ({{ matches: query === '(pointer: coarse)' && {str(touch).lower()} }}),
    }}"""


def test_every_touch_device_gets_the_phone_page_a_tablet_included():
    result = _run(
        "device.js",
        f"""
        return {{
          ipadUpright: m.isPhoneNow({_touch_window(1024, 1366, True)}),
          ipadSideways: m.isPhoneNow({_touch_window(1366, 1024, True)}),
          phoneSideways: m.isPhoneNow({_touch_window(852, 393, True)}),
          phoneUpright: m.isPhoneNow({_touch_window(393, 852, True)}),
        }}
        """,
    )
    assert result == {
        "ipadUpright": True, "ipadSideways": True, "phoneSideways": True, "phoneUpright": True,
    }


def test_silence_a_window_without_touch_stays_on_the_desktop_page_above_600():
    result = _run(
        "device.js",
        f"""
        return {{
          mac: m.isPhoneNow({_touch_window(1440, 900, False)}),
          small: m.isPhoneNow({_touch_window(700, 900, False)}),
          narrow: m.isPhoneNow({_touch_window(500, 900, False)}),
        }}
        """,
    )
    assert result == {"mac": False, "small": False, "narrow": True}


def test_a_browser_without_the_media_query_is_judged_by_its_window_alone():
    result = _run(
        "device.js",
        """
        return {
          narrow: m.isPhoneNow({ innerWidth: 500 }),
          wide: m.isPhoneNow({ innerWidth: 1280 }),
        }
        """,
    )
    assert result == {"narrow": True, "wide": False}


def test_the_watch_reports_a_change_of_the_main_input():
    """A tablet with a trackpad attached stops being a touch device: the
    media query fires `change`, and the page swaps to the desktop page."""
    result = _run(
        "device.js",
        """
        const queryListeners = {}
        let touch = true
        const win = {
          innerWidth: 1024,
          matchMedia: () => ({
            get matches() { return touch },
            addEventListener: (name, fn) => { queryListeners[name] = fn },
            removeEventListener: (name) => { delete queryListeners[name] },
          }),
          addEventListener: () => {},
          removeEventListener: () => {},
        }
        const calls = []
        const stop = m.watchDevice((phone) => calls.push(phone), win)
        touch = false; queryListeners.change()   // trackpad attached
        touch = true; queryListeners.change()    // detached again
        stop()
        return { calls, left: Object.keys(queryListeners) }
        """,
    )
    assert result == {"calls": [False, True], "left": []}


def test_the_watch_reports_only_a_change_of_the_answer():
    result = _run(
        "device.js",
        """
        const listeners = {}
        const win = {
          innerWidth: 1280,
          screen: { width: 1920, height: 1080 },
          addEventListener: (name, fn) => { listeners[name] = fn },
          removeEventListener: (name) => { delete listeners[name] },
        }
        const calls = []
        const stop = m.watchDevice((phone) => calls.push(phone), win)
        win.innerWidth = 1000; listeners.resize()   // still desktop
        win.innerWidth = 500; listeners.resize()    // crosses the line
        win.innerWidth = 480; listeners.resize()    // still phone
        win.innerWidth = 700; listeners.resize()    // back
        stop()
        return { calls, left: Object.keys(listeners) }
        """,
    )
    assert result == {"calls": [True, False], "left": []}


def test_the_phone_page_wears_exe_pearl_or_snow_and_nothing_else():
    result = _run(
        "look.js",
        """
        return {
          exe: m.phoneLook('dunkel', false),
          pearl: m.phoneLook('hell', true),
          snow: [m.phoneLook('snow', true), m.phoneLook('snow', false)],
          autoDark: m.phoneLook('auto', true),
          autoLight: m.phoneLook('auto', false),
          others: ['darkmatter', 'heaven', 'moune', 'eigen'].map((mode) => m.phoneLook(mode, false)),
        }
        """,
    )
    assert result == {
        "exe": "dunkel",
        "pearl": "hell",
        "snow": ["snow", "snow"],
        "autoDark": "dunkel",
        "autoLight": "snow",
        "others": ["dunkel"] * 4,
    }


def test_only_a_wide_enough_swipe_from_the_edge_opens_the_list():
    result = _run(
        "swipe.js",
        """
        const go = (from, to, open) => m.swipeDirection(from, to, open)
        return {
          fromEdge: go({ x: 6, y: 400 }, { x: 140, y: 410 }, false),
          notFromEdge: go({ x: 120, y: 400 }, { x: 260, y: 410 }, false),
          tooShort: go({ x: 6, y: 400 }, { x: 40, y: 400 }, false),
          scroll: go({ x: 6, y: 400 }, { x: 80, y: 600 }, false),
          closes: go({ x: 250, y: 400 }, { x: 120, y: 405 }, true),
          closedSwipeLeft: go({ x: 250, y: 400 }, { x: 120, y: 405 }, false),
        }
        """,
    )
    assert result == {
        "fromEdge": "open",
        "notFromEdge": None,
        "tooShort": None,
        "scroll": None,
        "closes": "close",
        "closedSwipeLeft": None,
    }


def test_the_swipe_ear_tells_what_the_finger_did_and_lets_go_when_stopped():
    result = _run(
        "swipe.js",
        """
        const listeners = {}
        const win = {
          addEventListener: (name, fn) => { listeners[name] = fn },
          removeEventListener: (name) => { delete listeners[name] },
        }
        let open = false
        const told = []
        const stop = m.listenForSwipes(() => open, (direction) => told.push(direction), win)
        listeners.touchstart({ touches: [{ clientX: 4, clientY: 300 }] })
        listeners.touchend({ changedTouches: [{ clientX: 160, clientY: 310 }] })
        open = true
        listeners.touchstart({ touches: [{ clientX: 280, clientY: 300 }] })
        listeners.touchend({ changedTouches: [{ clientX: 100, clientY: 300 }] })
        // An end with no start (a touch that began elsewhere) says nothing.
        listeners.touchend({ changedTouches: [{ clientX: 100, clientY: 300 }] })
        stop()
        return { told, left: Object.keys(listeners) }
        """,
    )
    assert result == {"told": ["open", "close"], "left": []}


def test_a_second_finger_or_a_cancelled_touch_is_no_swipe():
    result = _run(
        "swipe.js",
        """
        const listeners = {}
        const win = {
          addEventListener: (name, fn) => { listeners[name] = fn },
          removeEventListener: (name) => { delete listeners[name] },
        }
        const told = []
        m.listenForSwipes(() => false, (direction) => told.push(direction), win)
        // Two fingers down: a pinch, not a swipe.
        listeners.touchstart({ touches: [{ clientX: 4, clientY: 300 }, { clientX: 200, clientY: 300 }] })
        listeners.touchend({ changedTouches: [{ clientX: 160, clientY: 300 }] })
        // A touch the system cancelled.
        listeners.touchstart({ touches: [{ clientX: 4, clientY: 300 }] })
        listeners.touchcancel({})
        listeners.touchend({ changedTouches: [{ clientX: 160, clientY: 300 }] })
        return told
        """,
    )
    assert result == []


def test_both_sidebars_read_the_same_list_of_pinned_project_and_day_chats():
    result = _run(
        "chatliste.js",
        """
        const now = new Date(2026, 9, 18, 12).getTime()
        const at = (day, hour = 9) => new Date(2026, 9, day, hour).toISOString()
        const chats = [
          { id: 'a', title: 'a', updated_at: at(18), created_at: at(18), pinned: true, project_id: null },
          { id: 'b', title: 'b', updated_at: at(18, 8), created_at: at(18, 8), pinned: false, project_id: 'p1' },
          { id: 'c', title: 'c', updated_at: at(18, 7), created_at: at(18, 7), pinned: false, project_id: 'p1' },
          { id: 'd', title: 'd', updated_at: at(17), created_at: at(17), pinned: false, project_id: 'gone' },
          { id: 'e', title: 'e', updated_at: at(17), created_at: at(17), pinned: false, project_id: null },
        ]
        const projects = [{ id: 'p1' }]
        const plain = m.chatListe(chats, projects, false, now)
        const found = m.chatListe(chats, projects, true, now)
        const ids = (groups) => groups.flatMap((group) => group.chats.map((chat) => chat.id))
        return {
          pinned: ids(plain.pinned),
          days: ids(plain.days),
          byProject: plain.byProject.p1.map((chat) => chat.id),
          searchDays: ids(found.days).sort(),
        }
        """,
        LIB,
    )
    # A project's chats stand under the project, oldest first; a chat whose
    # project is unknown stands in the days; a search puts every hit in the days.
    assert result == {
        "pinned": ["a"],
        "days": ["d", "e"],
        "byProject": ["c", "b"],
        "searchDays": ["b", "c", "d", "e"],
    }
