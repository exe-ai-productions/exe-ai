"""The memory and the prompt preparation of the picture server in a real
browser: a field with no value shows a dash and is empty while the cursor is
in it, what is typed goes out as before; the instruction is set back by a
30 px sign in its title line; the heads carry their signs; the fold of the
generator's switches has an angle of 14.

The parts are built as shipped on the stub of `tests/image_window_page.py`.
Skipped where there is no Chrome or no node.
"""

from __future__ import annotations

import pytest

from tests.image_window_page import needs_browser, run_cases

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    needs_browser,
]

CASES = r"""
// The page loads no stylesheet of the house: the two colours the dash is read against are set here.
document.documentElement.style.setProperty('--text', 'rgb(236, 235, 230)')
document.documentElement.style.setProperty('--text-leise', 'rgb(208, 206, 199)')
const sentDevices = () => backend.calls.filter((c) => c.key === 'bildgeraete').map((c) => c.sent)
const fire = (node, type) => node.dispatchEvent(new Event(type))
const box = (node) => {
  const r = node.getBoundingClientRect()
  return { w: r.width, h: r.height, left: r.left, right: r.right, top: r.top, bottom: r.bottom }
}

await show('devices')
const time = () => document.querySelector('input[aria-label="mcp.zeitgrenze"]')
const back = () => document.querySelector('input[aria-label="bild.backend"]')
const quiet = (node) => getComputedStyle(node).color
report.empty = { time: time().value, back: back().value, timeWord: time().classList.contains('wort'), backWord: back().classList.contains('wort') }
report.colours = { word: quiet(time()), text: quiet(document.querySelector('.name')) }
report.head = Boolean(document.querySelector('.kopf .zeichen svg'))
report.angle = box(document.querySelector('.winkel svg'))

fire(time(), 'focus'); fire(back(), 'focus')
await wait(150)
report.focused = { time: time().value, back: back().value, timeWord: time().classList.contains('wort'), backWord: back().classList.contains('wort') }

typeInto(time(), '300')
typeInto(back(), 'cpu')
await wait(1500)
report.sent = sentDevices()
fire(time(), 'blur'); fire(back(), 'blur')
await wait(300)
report.filled = { time: time().value, back: back().value, timeWord: time().classList.contains('wort'), backWord: back().classList.contains('wort') }

// Emptied again: the dash comes back and the service is told "no limit".
fire(time(), 'focus'); fire(back(), 'focus')
typeInto(time(), '')
typeInto(back(), '')
await wait(1500)
fire(time(), 'blur'); fire(back(), 'blur')
await wait(300)
report.emptied = { time: time().value, back: back().value, last: sentDevices().at(-1) }
report.stored = { zeitgrenze: backend.settings.bildgeraete.zeitgrenze, backend: backend.settings.bildgeraete.backend }

await show('preparation')
const area = () => document.querySelector('textarea')
const reset = () => document.querySelector('button[aria-label="sprachserver.zuruecksetzen"]')
report.prepHead = Boolean(document.querySelector('.kopf .zeichen svg'))
typeInto(area(), 'my instruction')
await wait(100)
const button = reset()
const label = document.querySelector('label[for="bs-anweisung"]')
report.reset = {
  box: box(button), text: button.textContent.trim(), title: button.getAttribute('title'),
  right: box(button).left >= box(label).right, sameLine: Math.abs((box(button).top + box(button).bottom) / 2 - (box(label).top + box(label).bottom) / 2) <= 2,
  fieldBelow: box(area()).top >= box(button).bottom, sign: Boolean(button.querySelector('svg')),
  before: area().value,
}
button.click()
await wait(200)
report.after = area().value
"""


@pytest.fixture(scope="module")
def report() -> dict:
    return run_cases(CASES)


def test_empty_fields_show_a_dash_in_the_quiet_colour(report):
    assert report["empty"] == {"time": "-", "back": "-", "timeWord": True, "backWord": True}
    assert report["colours"]["word"] != report["colours"]["text"]


def test_with_the_cursor_in_the_field_it_is_empty(report):
    assert report["focused"] == {"time": "", "back": "", "timeWord": False, "backWord": False}


def test_what_is_typed_goes_out_as_before_and_stands_after_leaving(report):
    assert {"zeitgrenze": 300} in report["sent"] or any(s.get("zeitgrenze") == 300 for s in report["sent"])
    assert any(s.get("backend") == "cpu" for s in report["sent"])
    assert report["filled"] == {"time": "300", "back": "cpu", "timeWord": False, "backWord": False}


def test_an_emptied_field_goes_out_empty_and_shows_the_dash_again(report):
    assert report["emptied"]["time"] == "-" and report["emptied"]["back"] == "-"
    assert report["stored"] == {"zeitgrenze": None, "backend": ""}


def test_the_dash_is_never_sent_as_a_value(report):
    assert all(s.get("backend") != "-" and s.get("zeitgrenze") != "-" for s in report["sent"])


def test_the_heads_carry_their_signs(report):
    assert report["head"] is True
    assert report["prepHead"] is True


def test_the_fold_of_the_switches_has_an_angle_of_14(report):
    assert (report["angle"]["w"], report["angle"]["h"]) == (14, 14)


def test_the_instruction_is_set_back_by_a_sign_in_its_title_line(report):
    reset = report["reset"]
    assert (reset["box"]["w"], reset["box"]["h"]) == (30, 30)
    assert reset["sign"] is True and reset["text"] == ""
    assert reset["title"] == "sprachserver.zuruecksetzen"
    assert reset["right"] is True and reset["sameLine"] is True and reset["fieldBelow"] is True


def test_the_sign_sets_the_works_text_back(report):
    assert report["reset"]["before"] == "my instruction"
    assert report["after"] == "works text"
