"""The card for what waits on the user (`frontend/src/teile/QuestionBox.svelte`):
a tool's permission, the model's own question and an agent's question stand
as one glass card in the middle of the chat column, on a veil that blurs the
chat behind it. Source probes: what the card is drawn with, what it says,
and that the keys still do what they did."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARD = ROOT / "frontend" / "src" / "teile" / "QuestionBox.svelte"
BAR = ROOT / "frontend" / "src" / "teile" / "Eingabeleiste.svelte"
LOCALES = ROOT / "app" / "locales"


def _source() -> str:
    return CARD.read_text(encoding="utf-8")


def _markup() -> str:
    source = _source()
    return source[source.index("</script>") + len("</script>"):source.index("<style>")]


def _style() -> str:
    source = _source()
    return source[source.index("<style>"):]


def _rule(selector: str) -> str:
    """The body of the one rule that starts with `selector`."""
    found = re.findall(r"(?m)^  " + re.escape(selector) + r" \{(.*?)^  \}", _style(), re.S)
    assert len(found) == 1, f"{len(found)} rules start with {selector}"
    return found[0]


def _catalogue(language: str) -> dict:
    return json.loads((LOCALES / f"{language}.json").read_text(encoding="utf-8"))


def test_the_card_stands_in_a_frosted_veil_over_the_chat_column():
    markup = _markup()
    veil = markup.index('class="veil"')
    card = markup.index('class="card"')
    assert veil < card, "the card is written inside the veil"
    assert markup.rstrip().endswith("  </div>\n</div>"), "the veil closes after the card"

    rule = _rule(".veil")
    assert "position: absolute" in rule and "inset: 0" in rule
    assert "backdrop-filter: var(--kachel-frost)" in rule
    assert "color-mix(in srgb, var(--bg) 45%, transparent)" in rule
    # In the middle of the column.
    assert "align-items: center" in rule and "justify-content: center" in rule


def test_the_veil_hangs_itself_into_the_chat_column():
    """Written inside the bar, whose layer ends below the chat's head, the
    veil would cover the bar's own strip only."""
    source = _source()
    assert "use:intoColumn" in _markup()
    body = source[source.index("function intoColumn(node)"):source.index("function holdFocus")]
    assert "node.closest('main')" in body
    assert "column?.appendChild(node)" in body
    # It takes itself out again: nothing of the block that wrote it holds it.
    assert "node.remove()" in body


def test_the_card_is_glass_in_the_raised_ground_with_one_radius():
    rule = _rule(".card")
    assert "width: min(100%, 520px)" in rule
    assert "border-radius: 9px" in rule
    assert "color-mix(in srgb, var(--bg-erhoben) 70%, transparent)" in rule
    assert "backdrop-filter: var(--kachel-frost)" in rule
    assert "inset 0 0 0 1px var(--glass-card-line)" in rule
    assert "0 28px 70px -12px rgba(0, 0, 0, 0.55)" in rule


def test_every_colour_of_the_card_is_a_token_of_the_look():
    """No colour of its own: a hex value in the card would stay the same in
    every look. The two shadows are black at an opacity, as everywhere."""
    style = re.sub(r"/\*.*?\*/", "", _style(), flags=re.S)
    assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", style)
    assert set(re.findall(r"rgba?\([^)]*\)", style)) == {"rgba(0, 0, 0, 0.55)", "rgba(0, 0, 0, 0.5)"}


def test_the_badge_draws_the_question_mark_in_the_pill_colour():
    markup = _markup()
    badge = markup[markup.index('class="badge"'):markup.index('class="asker"')]
    assert 'd="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"' in badge
    assert 'd="M12 17h.01"' in badge
    assert 'stroke="currentColor"' in badge and 'stroke-width="2"' in badge
    rule = _rule(".badge")
    assert "width: 52px" in rule and "height: 52px" in rule
    assert "background: var(--glass-button)" in rule
    assert "var(--glass-button-edge)" in rule
    assert "color: var(--blau)" in rule


def test_the_pill_counts_the_question_in_blue():
    source = _source()
    pill = source[source.index("const pill = $derived.by"):source.index("/* A tool's arguments as pairs")]
    assert "t('benutzerfrage.nummer', { zahl: question.nummer })" in pill
    assert "t('question_box.agent_position'" in pill
    assert "t('werkzeug.permission_label')" in pill
    assert '{#if pill}<div class="pill">{pill}</div>{/if}' in _markup()
    rule = _rule(".pill")
    assert "color: var(--blau)" in rule
    assert "color-mix(in srgb, var(--blau) 12%, var(--bg))" in rule
    assert "border-radius: 9px" in rule


def test_the_question_is_a_heading_and_who_asks_stands_over_it():
    markup = _markup()
    assert markup.index('class="badge"') < markup.index('class="asker"') < markup.index('class="title"')
    assert "<h2 class=\"title\">{kind === 'tool' ? t('werkzeug.permission_question') : question.frage}</h2>" in markup
    rule = _rule(".title")
    assert "font-size: 22px" in rule and "font-weight: 600" in rule
    # A tool's permission still names the tool, in the tool colour.
    asker = markup[markup.index('class="asker"'):markup.index('class="title"')]
    assert '<b class="werkzeugname">{question.name}</b>' in asker
    assert "color: var(--werkzeug)" in _rule(".asker b.werkzeugname")


def test_a_permission_keeps_command_arguments_and_reason():
    markup = _markup()
    details = markup[markup.index('class="details"'):markup.index('class="answers"')]
    assert "{@html commandColoured}" in details
    assert "aria-expanded={argumentsOpen}" in details
    assert '<dl class="arguments"' in details
    assert "{@html reasonText}" in details
    assert "font: 11.5px var(--schrift-fest)" in _style()


def test_the_answers_are_cards_and_the_chosen_one_wears_the_tick():
    markup = _markup()
    answers = markup[markup.index('class="answers"'):markup.index('class="own"')]
    assert 'class="answer" class:active={active === index}' in answers
    assert "onclick={row.pick}" in answers
    assert 'd="M20 6 9 17l-5-5"' in answers
    rule = _rule(".answer")
    assert "min-height: 60px" in rule and "border-radius: 9px" in rule
    assert "background: var(--glass-card)" in rule
    assert "var(--glass-card-line)" in rule
    assert "background: var(--glass-hover)" in _rule(".answer:hover")
    assert "translateY(-1px)" in _rule(".answer:hover")
    assert "inset 0 0 0 1.5px var(--text)" in _rule(".answer.active")
    assert "opacity: 1" in _style()[_style().index(".answer.active .check"):][:80]


def test_an_answer_shows_its_label_alone():
    """Silence probe: nothing stands under an answer — neither what the
    model wrote under one of its own nor a line explaining a permission."""
    source = _source()
    assert "description" not in source
    assert "hint" not in source
    rows = source[source.index("const rows = $derived("):source.index("const pill = $derived.by")]
    assert "label: option.label," in rows
    assert "pick: () => answerAsk(option.label)," in rows
    answers = _markup()[_markup().index('class="answers"'):_markup().index('class="own"')]
    assert answers.count("{row.") == 2, "an answer is drawn with its label and its click"


def test_a_permission_asks_whether_to_allow_the_run():
    """The heading of every permission, in both languages."""
    assert "t('werkzeug.permission_question')" in _markup()
    assert _catalogue("de")["werkzeug"]["permission_question"] == "Ausführen erlauben?"
    assert _catalogue("en")["werkzeug"]["permission_question"] == "Allow this?"


def test_a_permission_offers_this_time_always_and_no():
    source = _source()
    rows = source[source.index("const rows = $derived("):source.index("const pill = $derived.by")]
    assert "{ label: t('werkzeug.just_this_once'), pick: () => answerTool(true) }," in rows
    assert "{ label: t('werkzeug.yes_dont_ask_again'), pick: () => answerTool(true, true) }," in rows
    assert "{ label: t('app.nein'), pick: () => answerTool(false) }," in rows
    words = {
        "de": ("Dieses Mal erlauben", "Immer erlauben", "Nein"),
        "en": ("Allow this time", "Always allow", "No"),
    }
    for language, (once, always, no) in words.items():
        catalogue = _catalogue(language)
        assert catalogue["werkzeug"]["just_this_once"] == once
        assert catalogue["werkzeug"]["yes_dont_ask_again"] == always
        assert catalogue["app"]["nein"] == no
        # The line that explained "always" is gone, and so is the older key
        # that held the same two words and was read nowhere.
        assert "immer_erlauben_hinweis" not in catalogue["werkzeug"]
        assert "immer_erlauben" not in catalogue["werkzeug"]


def test_the_own_answer_has_a_field_and_a_round_button_to_send_it():
    markup = _markup()
    own = markup[markup.index('class="own"'):markup.index('class="later"')]
    assert "bind:value={own}" in own and "oninput={keepDraft}" in own
    assert "onclick={sendOwn} disabled={!own.trim()}" in own
    assert 'd="M12 19V5M5 12l7-7 7 7"' in own
    field = _rule(".field")
    assert "height: 40px" in field and "background: var(--kachel-eingabe)" in field
    send = _rule(".send")
    assert "width: 40px" in send and "height: 40px" in send and "border-radius: 50%" in send
    assert "opacity: 0.35" in _rule(".send:disabled")


def test_later_stands_centred_under_the_field_and_the_key_line_is_gone():
    markup = _markup()
    assert markup.index('class="own"') < markup.index('class="later"')
    assert "<button class=\"later\" onclick={onLater}>{t('benutzerfrage.later')}</button>" in markup
    assert "margin: 14px auto 0" in _rule(".later")
    assert "keys_hint" not in _source()
    for language, words in (("de", "Später antworten"), ("en", "Answer later")):
        block = _catalogue(language)["benutzerfrage"]
        assert block["later"] == words
        assert "keys_hint" not in block


def test_the_card_brings_no_text_of_its_own():
    """Every key the card reads stands in both catalogues, and the block of
    the question holds what it held, less the line of keys."""
    keys = set(re.findall(r"\bt\(\s*'([a-z_]+\.[a-z_]+)'", _source()))
    # One key is chosen by the kind of the question.
    keys |= {"werkzeug.no_with_words", "benutzerfrage.eigene_platzhalter"}
    assert "benutzerfrage.later" in keys and "benutzerfrage.eigene_senden" in keys
    for language in ("de", "en"):
        catalogue = _catalogue(language)
        for key in sorted(keys):
            block, name = key.split(".")
            assert name in catalogue[block], f"{language}: {key}"
        assert set(catalogue["benutzerfrage"]) == {
            "frei", "eigene_platzhalter", "eigene_senden", "nummer", "later",
        }


def test_the_card_takes_the_focus_and_tab_stays_in_it():
    source = _source()
    focus = source[source.index("const inSight = $derived("):source.index("function keepDraft()")]
    assert "box?.focus({ preventScroll: true })" in focus
    # Again when a page or the studio that covered the chat is gone.
    assert "const inSight = $derived(!eineSeiteOffen() && !studioSichtbar())" in focus
    assert "if (!identity || !inSight) return" in focus
    tab = source[source.index("if (event.key === 'Tab') {"):source.index("if (event.key === 'ArrowDown'")]
    assert "box.querySelectorAll('button:not(:disabled), input')" in tab
    assert "event.preventDefault()" in tab
    # A click beside the card does not take the focus out of it.
    assert "onmousedown={holdFocus}" in _markup()


def test_the_card_leaves_the_focus_where_something_would_be_lost():
    """Silence probe: a field beside the chat column and whatever lies above
    the page keep the focus — what is typed or confirmed there must not
    land on the card."""
    source = _source()
    focus = source[source.index("const inSight = $derived("):source.index("function keepDraft()")]
    # Taken from nowhere, from the chat column, and from a control of the
    # two columns beside it that is no field ...
    assert "const nowhere = !held || held === document.body" in focus
    assert "const inChat = Boolean(box?.closest('main')?.contains(held))" in focus
    assert "Boolean(held?.closest('aside, nav')) &&" in focus
    assert "!held.closest('input, textarea, select, [contenteditable], [role=textbox], iframe')" in focus
    # ... and from nowhere else: the one call stands behind the three.
    assert "if (nowhere || inChat || besideChat) box?.focus({ preventScroll: true })" in focus
    assert focus.count(".focus(") == 1


def test_the_keys_do_what_they_did():
    source = _source()
    keys = source[source.index("function key(event) {"):source.index("/* Leaving:")]
    escape = keys[keys.index("if (event.key === 'Escape') {"):keys.index("if (event.key === 'Tab')")]
    assert "onLater()" in escape and "event.stopPropagation()" in escape
    assert "if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {" in keys
    assert "const count = rows.length + 1" in keys
    assert "if (event.key === 'Enter' && inOwn) {" in keys
    assert "const row = rows[Number(event.key) - 1]" in keys


def test_a_digit_answers_only_while_an_answer_is_chosen():
    """Silence probe: on the bare card — where the focus lands when the
    question appears — a digit is no answer."""
    source = _source()
    assert "if (!inOwn && active >= 0 && /^[1-9]$/.test(event.key)) {" in source
    assert "if (!inOwn && /^[1-9]$/.test(event.key)) {" not in source


def test_nothing_stands_while_the_question_is_pushed_away():
    """Silence probe: after "later" neither card nor veil is written — the
    bar keeps the chip that brings them back."""
    bar = BAR.read_text(encoding="utf-8")
    assert re.search(r"\{#if standing && !questionDeferred\}\s*<QuestionBox\b", bar)
    assert bar.count("<QuestionBox") == 1
    chip = bar[bar.index("{#if questionDeferred}"):]
    assert 'class="later-chip"' in chip[:200] and "onclick={resume}" in chip[:300]
    # The veil is part of the card's own markup, so it goes with it.
    assert _markup().lstrip().startswith("<!-- svelte-ignore a11y_no_static_element_interactions -->\n<div class=\"veil\"")


def test_the_card_stays_out_of_sight_under_the_picture_studio():
    assert ":global(main.studio) > .veil { visibility: hidden; }" in _style()
