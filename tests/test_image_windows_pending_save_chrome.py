"""A change made just before a window of the picture server closes is kept.

The three parts that keep their settings after a short wait (memory and
devices, the prompt preparation, a model's values) cleared that wait when
they went away, so a value changed and the window closed within the wait was
lost: the next opening showed the old one. Each now writes what is still
waiting when it goes.
"""

from __future__ import annotations

import pytest

from tests.image_window_page import needs_browser, run_cases

pytestmark = pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only")

CASES = r"""
const sent = (key) => backend.calls.filter((c) => c.key === key).map((c) => c.sent)

// Memory and devices: a value changed, the window closed within 50 ms.
await show('devices')
typeInto(document.querySelector('input[aria-label="bild.backend"]'), 'cpu')
await wait(50)
await show('')
await wait(600)
report.devices = { calls: sent('bildgeraete'), stored: backend.settings.bildgeraete.backend }

// The prompt preparation: the instruction typed, the window closed.
await show('preparation')
typeInto(document.querySelector('textarea'), 'my instruction')
await wait(50)
await show('')
await wait(900)
report.preparation = sent('bildaufbereitung')

// A model's values: the trigger words typed, the row closed.
await show('values')
typeInto(document.querySelector('input[id^="bmw-trigger-"]'), 'lighthouse')
await wait(50)
await show('')
await wait(600)
report.values = sent('bildmodellwerte')

// Silence probe: a change that is kept before the window goes is written once.
await show('devices')
typeInto(document.querySelector('input[aria-label="bild.backend"]'), 'cuda0')
await wait(1200)
const before = sent('bildgeraete').length
await show('')
await wait(600)
report.once = { before, after: sent('bildgeraete').length }
"""


@pytest.fixture(scope="module")
def report() -> dict:
    return run_cases(CASES)


@needs_browser
def test_a_device_value_changed_just_before_closing_is_kept(report):
    assert report["devices"]["stored"] == "cpu"
    assert report["devices"]["calls"][-1]["backend"] == "cpu"


@needs_browser
def test_an_instruction_typed_just_before_closing_is_kept(report):
    assert report["preparation"], "nothing was written"
    assert report["preparation"][-1]["anweisungen"] == {"sdxl": "my instruction"}


@needs_browser
def test_a_model_value_changed_just_before_closing_is_kept(report):
    assert report["values"], "nothing was written"
    assert report["values"][-1] == {"model.safetensors": {"trigger": "lighthouse"}}


@needs_browser
def test_a_change_already_kept_is_not_written_again_on_closing(report):
    assert report["once"]["after"] == report["once"]["before"]
