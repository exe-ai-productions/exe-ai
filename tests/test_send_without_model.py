"""A message sent while no model can be reached stays in the bar.

The bar clears itself the moment it hands a message on, and the send behind
it turns a message down when there is no model. So the bar asks first: with
no model it says so and keeps the words and the attachments.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BAR = ROOT / "frontend" / "src" / "teile" / "Eingabeleiste.svelte"
APP = ROOT / "frontend" / "src" / "App.svelte"


def _submit() -> str:
    """The bar's own send function, as it stands."""
    source = BAR.read_text(encoding="utf-8")
    start = source.index("  async function absenden() {")
    return source[start : source.index("\n  export function fokus()", start)]


def test_without_a_model_the_bar_says_so_and_keeps_the_words():
    submit = _submit()
    guard = submit.index("if (!zustand.modellId && !answersQuestion) {")
    notice = submit.index("melde(t('fehler.kein_modell_verfuegbar'), 'fehler')", guard)
    # Before anything is taken out of the bar, and before the chat is claimed.
    assert guard < notice < submit.index("sendetGerade.add(chatBeimStart)") < submit.index("text = ''")
    assert notice < submit.index("anhaengeLeeren()")
    assert submit[notice:].lstrip().split("\n")[1].strip() == "return"


def test_the_bar_and_the_send_behind_it_name_the_same_notice():
    """The silence check: the send itself still turns a message down without
    a model, for every caller that is not the bar, with the same words."""
    app = APP.read_text(encoding="utf-8")
    assert app.count("melde(t('fehler.kein_modell_verfuegbar'), 'fehler')") == 1
    assert "if (!zustand.modellId) {" in app


def test_an_answer_to_a_standing_question_still_passes():
    submit = _submit()
    answers = submit.index("const answersQuestion = ")
    assert answers < submit.index("if (!zustand.modellId && !answersQuestion) {")
