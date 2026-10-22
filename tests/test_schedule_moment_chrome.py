"""The day and the time of day of the schedule form are the house's own fields,
in a real browser.

``ScheduleMoment.svelte`` is built as shipped on the stub of
``tests/image_window_page.py``: the day field opens a month, the time field
takes a typed time and opens a list of the quarter hours. Skipped where there
is no Chrome or no node.
"""

from __future__ import annotations

from unittest import mock

import pytest

from tests import image_window_page as harness
from tests.image_window_page import needs_browser, run_cases

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    needs_browser,
]

SHELL = """<script>
  import ScheduleMoment from '../../src/teile/ScheduleMoment.svelte'

  let day = $state('2026-10-21')
  let time = $state('')
  window.__state = () => ({ day, time })
  window.__escapes = 0
</script>

<div style="width: 340px; margin: 40px auto 0;" onkeydown={(e) => { if (e.key === 'Escape') window.__escapes += 1 }}>
  <ScheduleMoment mode="day" label="Day" bind:value={day} />
  <div style="height: 12px"></div>
  <ScheduleMoment mode="time" label="Time" bind:value={time} />
</div>

<style>
  /* The stub page does not carry the global style sheet; the two outlines the test compares are set here. */
  :global(:root) {
    --feldstrich: #928057;
    --rot: #b4544c;
    --glass-button: #3a3a37;
    --glass-dropdown: #2f2f2c;
    --glass-button-edge: #55554f;
    --glass-hover: #4a4a46;
    --text: #eeeeea;
  }
</style>
"""

CASES = r"""
const dayField = () => document.querySelector('button[role="combobox"]')
const timeInput = () => document.querySelector('input[role="combobox"]')
const timeChevron = () => document.querySelector('.zeit .winkel')
const pop = () => document.querySelector('.klapp:popover-open')
const press = (node) => node.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))
const key = (node, name) => node.dispatchEvent(new KeyboardEvent('keydown', { key: name, bubbles: true, cancelable: true }))
const state = () => window.__state()

// The day field: the chosen day in words, a month under it.
report.dayText = dayField().textContent.replace(/\s+/g, ' ').trim()
dayField().click()
await wait(400)
report.month = {
  open: Boolean(pop()),
  heads: pop().querySelectorAll('.wt').length,
  cells: pop().querySelectorAll('.tag').length,
  chosen: [...pop().querySelectorAll('.tag.gewaehlt')].map((n) => n.textContent.trim()),
  today: pop().querySelectorAll('.tag.heutig').length,
  title: pop().querySelector('.titel').textContent.trim(),
  fieldOutline: getComputedStyle(dayField()).borderTopColor,
}
const titleBefore = report.month.title
pop().querySelector('button[aria-label="cronjobs.month_next"]').click()
await wait(200)
report.next = { title: pop().querySelector('.titel').textContent.trim(), stillOpen: Boolean(pop()) }
const five = [...pop().querySelectorAll('.tag:not(.fremd)')].find((n) => n.textContent.trim() === '5')
five.click()
await wait(300)
report.picked = { state: state().day, closed: !pop(), text: dayField().textContent.replace(/\s+/g, ' ').trim(), titleBefore }

// Escape belongs to the open month: nothing around it hears it.
dayField().click()
await wait(300)
report.escapeOpen = { before: window.__escapes }
key(pop().querySelector('.tag'), 'Escape')
await wait(200)
report.escapeOpen.after = window.__escapes
report.escapeOpen.closed = !pop()

// The time field: a typed time is read, an impossible one is marked and no value.
const input = timeInput()
const typeText = (text) => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, text)
  input.dispatchEvent(new Event('input', { bubbles: true }))
}
typeText('9:07')
await wait(200)
report.typed = { value: state().time, invalid: input.getAttribute('aria-invalid') }
input.dispatchEvent(new FocusEvent('blur'))
await wait(200)
report.settled = input.value
typeText('25:00')
await wait(200)
report.bad = { value: state().time, invalid: input.getAttribute('aria-invalid'), edge: getComputedStyle(input.parentElement).borderTopColor }
typeText('9:60')
await wait(200)
report.bad2 = { value: state().time, invalid: input.getAttribute('aria-invalid') }
typeText('')
await wait(200)
report.empty = { value: state().time, invalid: input.getAttribute('aria-invalid') }

// The list: ninety-six quarter hours, a pick is the value and the text.
timeChevron().click()
await wait(400)
const options = [...pop().querySelectorAll('[role="option"]')]
report.list = { open: true, count: options.length, first: options[0].textContent.trim(), last: options[options.length - 1].textContent.trim() }
options.find((n) => n.textContent.trim() === '10:15').click()
await wait(300)
report.chosen = { value: state().time, text: input.value, closed: !pop() }

// A time that is not in the list opens it at the quarter before it.
typeText('9:07')
await wait(200)
timeChevron().click()
await wait(400)
report.near = [...pop().querySelectorAll('[role="option"].dran')].map((n) => n.textContent.trim())
// A press on another field shuts the open list.
press(dayField())
await wait(200)
report.otherShuts = !pop()

// Escape on the field with the list open is the list's; with none open it goes on up.
timeChevron().click()
await wait(300)
const before = window.__escapes
key(input, 'Escape')
await wait(200)
report.escapeList = { closed: !pop(), heard: window.__escapes - before }
key(input, 'Escape')
await wait(100)
report.escapeShut = window.__escapes - before

// The arrows walk the list and Enter takes the entry walked to.
key(input, 'ArrowDown')
await wait(300)
const at = [...pop().querySelectorAll('[role="option"].dran')].map((n) => n.textContent.trim())
key(input, 'ArrowDown')
await wait(150)
const next = [...pop().querySelectorAll('[role="option"].dran')].map((n) => n.textContent.trim())
key(input, 'Enter')
await wait(300)
report.walk = { at, next, value: state().time, closed: !pop() }
"""


@pytest.fixture(scope="module")
def report() -> dict:
    with mock.patch.object(harness, "SHELL", SHELL):
        return run_cases(CASES, limit=240.0, window="900,900")


def test_the_day_field_opens_a_month_of_whole_weeks_with_the_chosen_day_lit(report):
    month = report["month"]
    assert month["open"] and month["heads"] == 7, month
    assert month["cells"] % 7 == 0 and month["cells"] >= 28, month
    assert month["chosen"] == ["21"], month
    assert "2026" in month["title"], month
    assert "2026" in report["dayText"] and "21" in report["dayText"], report["dayText"]


def test_the_arrows_move_the_month_and_a_day_clicked_is_the_answer(report):
    assert report["next"]["title"] != report["month"]["title"] and report["next"]["stillOpen"], report["next"]
    picked = report["picked"]
    assert picked["state"] == "2026-11-05" and picked["closed"], picked
    assert "5" in picked["text"] and "2026" in picked["text"], picked


def test_escape_belongs_to_the_open_month_and_to_the_open_list(report):
    month = report["escapeOpen"]
    assert month["closed"] and month["after"] == month["before"], month
    assert report["escapeList"]["closed"] and report["escapeList"]["heard"] == 0, report["escapeList"]


def test_a_typed_time_is_the_value_and_is_set_in_its_own_form_on_leaving(report):
    assert report["typed"] == {"value": "09:07", "invalid": None}, report["typed"]
    assert report["settled"] == "09:07"


def test_a_time_that_cannot_be_read_is_marked_and_is_no_value(report):
    for name in ("bad", "bad2"):
        assert report[name]["value"] == "" and report[name]["invalid"] == "true", report[name]
    # The outline of a failure, not the house's field outline.
    assert report["bad"]["edge"] != report["month"]["fieldOutline"], report["bad"]
    # An empty field is no failure, only no value.
    assert report["empty"] == {"value": "", "invalid": None}, report["empty"]


def test_the_list_has_every_quarter_hour_and_a_pick_is_the_value(report):
    assert report["list"] == {"open": True, "count": 96, "first": "00:00", "last": "23:45"}, report["list"]
    assert report["chosen"] == {"value": "10:15", "text": "10:15", "closed": True}, report["chosen"]


def test_a_time_between_two_entries_opens_the_list_at_the_one_before(report):
    assert report["near"] == ["09:00"], report["near"]


def test_the_arrows_walk_the_list_and_enter_takes_the_entry(report):
    walk = report["walk"]
    assert walk["next"] != walk["at"] and walk["closed"], walk
    assert walk["value"] == walk["next"][0], walk


def test_silence_a_press_on_another_field_shuts_an_open_list_and_escape_with_none_open_goes_on(report):
    assert report["otherShuts"] is True
    assert report["escapeShut"] == 1, report["escapeShut"]
