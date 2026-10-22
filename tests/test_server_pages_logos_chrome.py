"""The model and agent server pages, in a real browser: a maker's mark or the
first letter in front of every file in the choice fields (the field and its
open list), sizes with the decimal sign of the language, and the three
first-start steps drawn with the wordmark at 40, 70 and 100 per cent.

The real windows are built as they ship (``tests/model_windows_page.py``); only
the service's answers are replaced.

Skipped where there is no Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

import pytest

from tests.model_windows_page import BROWSER_TESTS_POSSIBLE, run_cases

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        not BROWSER_TESTS_POSSIBLE, reason="no node or no frontend dependencies on this machine"
    ),
]

CASES = r"""
const report = {}
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
const stub = window.__stub
texte.katalog = germanTexts
// A file the catalogue and the family list know (a logo), beside two they do not (a letter).
stub.extraFiles = [{ name: 'qwen-8b.gguf', groesse_gb: 4.5 }]

const markOf = (node) => ({
  logo: Boolean(node.querySelector('svg.logo')),
  letter: node.querySelector('.letter')?.textContent ?? null,
})
const comboAt = (index) => [...document.querySelectorAll('button[role="combobox"]')][index]
// The drafter and vision fields by their ids: the chat template field stands between them and the model.
const drafterField = () => document.getElementById('rs-drafter')
const visionField = () => document.getElementById('rs-vision')
const options = () =>
  [...document.querySelectorAll('[role="option"]')].map((o) => ({
    text: o.textContent.replace(/\s+/g, ' ').trim(), ...markOf(o),
    // The mark stands before the text.
    markFirst: o.querySelector('.logo, .letter') === [...o.children].find((c) => c.matches('.logo, .letter')),
  }))
const fieldOf = (combo) => ({ text: combo.querySelector('.text').textContent.trim(), ...markOf(combo) })
const settle = async () => {
  for (let k = 0; k < 80 && !comboAt(0); k += 1) await wait(50)
  await wait(500)
}

// 1. The model server: the open model field, the closed drafter and vision fields.
scene.show = 'modell'
await settle()
report.model_field = fieldOf(comboAt(0))
report.drafter_field = fieldOf(drafterField())
report.vision_field = fieldOf(visionField())
comboAt(0).click()
await wait(400)
report.model_options = options()
document.body.click()
await wait(200)
visionField().click()
await wait(400)
report.vision_options = options()
document.body.click()
await wait(200)
scene.show = null
await wait(300)

// 2. The agent server: "Main model" first, with nothing before it.
scene.show = 'agent'
await settle()
comboAt(0).click()
await wait(400)
report.agent_options = options()
document.body.click()
await wait(200)
scene.show = null
await wait(300)

// 3. The first start: no model in the folder, the program there (step 1 is done) and not there.
for (const noProgram of [false, true]) {
  stub.noModels = true
  stub.noProgram = noProgram
  scene.show = 'modell'
  for (let k = 0; k < 80 && !document.querySelector('.reisekarte'); k += 1) await wait(50)
  await wait(400)
  report[noProgram ? 'steps_without_program' : 'steps_with_program'] = {
    cards: document.querySelectorAll('.reisekarte').length,
    pill: Boolean(document.querySelector('.pille.gruen')),
    marks: [...document.querySelectorAll('.reisekarte .nr')].map((nr) => {
      const box = nr.getBoundingClientRect()
      const drawing = nr.querySelector('svg')
      const drawingBox = drawing ? drawing.getBoundingClientRect() : { width: 0, height: 0 }
      const style = getComputedStyle(nr)
      return {
        opacity: Number(style.opacity),
        text: nr.textContent.trim(),
        hidden: nr.getAttribute('aria-hidden'),
        border: style.borderTopWidth,
        radius: style.borderTopLeftRadius,
        box: [Math.round(box.width * 10) / 10, Math.round(box.height * 10) / 10],
        drawing: [Math.round(drawingBox.width * 10) / 10, Math.round(drawingBox.height * 10) / 10],
        viewBox: drawing ? drawing.getAttribute('viewBox') : null,
      }
    }),
  }
  scene.show = null
  await wait(300)
}
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


@pytest.fixture(scope="module")
def report() -> dict:
    return run_cases(CASES)


def _plain(text: str) -> str:
    return text.replace(" ", " ")


def test_the_open_model_field_shows_a_letter_or_a_logo_before_each_file_and_sizes_with_a_comma(report):
    first, a, b, qwen = report["model_options"]
    # The empty choice carries nothing.
    assert first["text"] == "-" and not first["logo"] and first["letter"] is None
    # A file nothing knows wears its first letter, in front of the name.
    assert (a["letter"], a["logo"], a["markFirst"]) == ("A", False, True)
    assert (b["letter"], b["logo"]) == ("B", False)
    assert _plain(a["text"]) == "A a.gguf · 2,0 GB"
    assert _plain(b["text"]).endswith("b.gguf · 3,0 GB")
    # A file the family list knows wears the logo, no letter, and the comma.
    assert (qwen["logo"], qwen["letter"], qwen["markFirst"]) == (True, None, True)
    assert _plain(qwen["text"]) == "qwen-8b.gguf · 4,5 GB"


def test_the_closed_fields_show_the_mark_of_the_chosen_file_and_none_for_the_empty_choice(report):
    assert report["model_field"]["letter"] == "A" and not report["model_field"]["logo"]
    assert _plain(report["model_field"]["text"]) == "a.gguf · 2,0 GB"
    assert report["drafter_field"] == {"text": "-", "logo": False, "letter": None}
    assert report["vision_field"]["letter"] == "A" and report["vision_field"]["text"] == "a-mmproj-f16.gguf"


def test_the_vision_list_carries_a_mark_before_each_projector_and_none_before_the_empty_choice(report):
    empty, projector = report["vision_options"]
    assert empty["text"] == "-" and not empty["logo"] and empty["letter"] is None
    assert projector["letter"] == "A" and projector["markFirst"]


def test_the_agent_list_keeps_the_main_model_first_without_a_mark(report):
    main, *files = report["agent_options"]
    assert main["text"] == "Hauptmodell" and not main["logo"] and main["letter"] is None
    assert [_plain(f["text"]) for f in files if f["letter"] or f["logo"]][0] == "A a.gguf · 2,0 GB"
    # Every file of the slot carries a mark, and the size has the comma.
    for entry in files:
        assert entry["logo"] or entry["letter"], entry
        assert " GB" in _plain(entry["text"]) and "." not in _plain(entry["text"]).split("·")[-1]


@pytest.mark.parametrize("key", ["steps_with_program", "steps_without_program"])
def test_the_three_first_start_steps_wear_the_wordmark_at_40_70_and_100_per_cent(report, key):
    steps = report[key]
    assert steps["cards"] == 3
    assert [round(m["opacity"], 2) for m in steps["marks"]] == [0.4, 0.7, 1.0]
    for mark in steps["marks"]:
        # The wordmark without lettering, 32 by 25.6, and nothing else in the place of the number.
        assert mark["drawing"] == [32.0, 25.6], mark
        assert mark["viewBox"] == "0 0 35 28"
        assert mark["text"] == ""
        # No circle and no border.
        assert mark["border"] == "0px" and mark["radius"] == "0px"
        # A decoration: hidden from screen readers.
        assert mark["hidden"] == "true"


def test_the_pill_of_the_done_step_stays_only_when_the_program_is_there(report):
    assert report["steps_with_program"]["pill"] is True
    assert report["steps_without_program"]["pill"] is False
