"""The chat on the phone: when the history follows a growing answer, and how
the page's parts are wired to the shared run.

The follow rule lives in an import-free module (`follow.js`), so it runs here
exactly as it ships. The rest checks the shape of the files: the phone page
brings its own view but no run of its own, the arrow is the stop sign only
while nothing is typed, the sheets send what is chosen to the shared store,
and the plus sheet carries the model.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
PHONE = FRONTEND / "src" / "phone"
LOCALES = ROOT / "app" / "locales"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")


def _run(body: str) -> object:
    driver = FRONTEND / f"phone_chat.{os.getpid()}.check.mjs"
    driver.write_text(
        "import * as follow from './src/phone/follow.js'\n"
        "const box = (top, height = 1000, view = 600) =>\n"
        "  ({ scrollTop: top, scrollHeight: height, clientHeight: view })\n"
        + textwrap.dedent(body),
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


def _source(name: str) -> str:
    return (PHONE / name).read_text(encoding="utf-8")


# ——— following the end ———


@needs_node
def test_the_distance_to_the_end_is_what_is_left_below_the_box():
    out = _run("console.log(JSON.stringify([follow.distanceToFloor(box(400)), follow.distanceToFloor(box(0))]))")
    assert out == [0, 400]


@needs_node
def test_a_finger_going_up_ends_the_following_and_it_stays_ended_far_from_the_end():
    out = _run(
        """
        console.log(JSON.stringify([
          follow.followAfterScroll(400, box(300), true),
          follow.followAfterScroll(300, box(300), false),
          follow.followAfterScroll(300, box(310), false),
        ]))
        """
    )
    assert out == [False, False, False]


@needs_node
def test_the_end_comes_back_only_within_seventy_pixels_of_it():
    out = _run(
        """
        // the box stands 70 px, then 71 px above the end; before it was higher up
        console.log(JSON.stringify([
          follow.FOLLOW_PX,
          follow.followAfterScroll(200, box(330), false),
          follow.followAfterScroll(200, box(329), false),
        ]))
        """
    )
    assert out == [70, True, False]


@needs_node
def test_the_rubber_band_beyond_the_end_is_not_a_finger_going_up():
    out = _run(
        """
        // pulled past the end, the box springs back: scrollTop falls, nobody scrolled up
        console.log(JSON.stringify(follow.followAfterScroll(420, box(400), true)))
        """
    )
    assert out is True


@needs_node
def test_silence_a_box_that_did_not_move_keeps_what_it_was():
    out = _run(
        """
        console.log(JSON.stringify([
          follow.followAfterScroll(100, box(100), true),
          follow.followAfterScroll(100, box(100), false),
          // a history shorter than the box has its end in view at all times
          follow.followAfterScroll(0, box(0, 300, 600), false),
        ]))
        """
    )
    assert out == [True, False, True]


# ——— the wiring of the page ———


def test_the_phone_page_brings_no_run_of_its_own():
    chat, bar = _source("ChatView.svelte"), _source("InputBar.svelte")
    assert "from '../lib/chatlauf.svelte.js'" in chat
    assert "from '../lib/eingabe.svelte.js'" in bar
    # sending, the answer and the queue are the shared run's, never written out here
    for source in (chat, bar):
        assert not re.search(r"\bfetch\(|api\.chatSenden|EventSource", source)
    assert "chatRun.ansicht({ runter, eingabe: bar })" in chat


def test_a_running_answer_of_the_open_chat_is_attached_to_again_exactly_once():
    chat = _source("ChatView.svelte")
    assert re.search(r"const \{[^}]*\bantwortWiederAnhaengen\b[^}]*\} = chatRun", chat)
    # only the entry of the chat on screen, taken out before it is acted on
    assert "zustand.wiederanhaengen[chatId]" in chat
    taken, acted = (
        chat.index("delete zustand.wiederanhaengen[chatId]"),
        chat.index("antwortWiederAnhaengen(wiederanhang)"),
    )
    assert taken < acted
    # what the attached answer reads and writes does not trigger the effect again
    assert "untrack(() => antwortWiederAnhaengen(wiederanhang))" in chat
    # the way is the shared run's: nothing of it is written out on this page
    assert not re.search(r"zusehenStrom|chat/stream", chat)


def test_the_history_follows_by_the_rule_and_a_round_button_brings_the_reader_back():
    chat = _source("ChatView.svelte")
    assert "followAfterScroll(lastTop, box, following)" in chat
    assert "onglidegrow={holdFloor}" in chat
    assert re.search(r"class=\"to-floor\" onclick=\{backToFloor\}", chat)
    assert "away = Boolean(box) && !following && distanceToFloor(box) > FOLLOW_PX" in chat
    # growth under a reader who stayed above the end offers the way back too
    holder = re.search(r"function holdFloor\(\) \{\n(.*?)\n  \}", chat, re.S)
    assert holder and "refreshAway()" in holder.group(1)
    # a card that arrives is brought into view
    assert re.search(r"if \(questions\.cardStands\) untrack\(\(\) => runter\(true\)\)", chat)


def test_the_arrow_is_the_stop_sign_only_while_nothing_is_typed():
    bar = _source("InputBar.svelte")
    assert "const stops = $derived(busy && nothing)" in bar
    assert re.search(r"if \(stops\) chatRun\.abbrechenVonHand\(\)\s+else if \(!locked\) chatEingabe\.absenden\(\)", bar)


def test_the_sheet_hands_what_is_chosen_to_the_shared_store():
    attach = _source("AttachSheet.svelte")
    assert attach.count("onchange={chosen}") == 3
    assert "chatEingabe.filesChosen(" in attach
    assert "capture=\"environment\"" in attach
    assert "berechtigungsmodusSetzen('chat'" in attach
    assert "modellWaehlen(id)" in attach
    assert "chatEingabe.denkenSetzen(stage)" in attach


def test_the_page_shows_pictures_and_is_sized_to_what_is_seen():
    page = _source("Phone.svelte")
    assert "<Bildschau />" in page
    # the keyboard covers the page on a phone: the page is sized to what is seen
    assert "window.visualViewport" in page


def test_the_question_card_answers_through_the_shared_question_store():
    card = _source("QuestionCard.svelte")
    for call in ("questions.answerTool(true)", "questions.answerTool(true, true)", "questions.answerTool(false)",
                 "questions.answerAsk(option.label)", "questions.later"):
        assert call in card


def test_the_texts_of_the_sheets_exist_in_both_catalogues():
    for name in ("en.json", "de.json"):
        section = json.loads((LOCALES / name).read_text(encoding="utf-8"))["phone_chat"]
        assert set(section) == {"camera", "photos", "files"}
    en = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))["phone_chat"]
    de = json.loads((LOCALES / "de.json").read_text(encoding="utf-8"))["phone_chat"]
    assert all(en[key] != de[key] for key in en)


def test_the_phone_card_takes_back_words_of_an_answer_that_could_not_be_sent():
    card = _source("QuestionCard.svelte")
    effect = re.search(r"let takenBack = null\n  \$effect\.pre\(\(\) => \{\n(.*?)\n  \}\)", card, re.S)
    assert effect and "question.zurueck" in effect.group(1) and "if (!own.trim())" in effect.group(1)


def test_the_sheet_does_not_reset_itself_while_its_lists_load():
    attach = _source("AttachSheet.svelte")
    reset = re.search(r"\$effect\(\(\) => \{\n    if \(!open\) return\n(.*?)\n  \}\)", attach, re.S)
    assert reset and "untrack(() => {" in reset.group(1)
    assert "section = null" in reset.group(1) and "step = 'main'" in reset.group(1)
    # the model list is read anew at every opening, not once
    assert "void auswahlLaden()" in reset.group(1) and "modellwahl.geladen" not in reset.group(1)


def test_a_pinch_zoom_is_not_taken_for_the_keyboard_and_the_mark_is_cleaned_up():
    page = _source("Phone.svelte")
    assert "zoomed: viewport.scale > 1.01" in page
    assert "!seen.zoomed" in page
    assert "removeAttribute('data-keyboard')" in page


def test_a_document_tile_on_the_phone_opens_nothing_on_the_machine():
    bar = _source("InputBar.svelte")
    assert "dokumentOeffnen" not in bar


def test_the_skill_row_lists_the_commands_of_the_window_before_the_skills():
    attach = _source("AttachSheet.svelte")
    assert "gefiltert('')" in attach
    assert "onskill?.(name)" in attach
