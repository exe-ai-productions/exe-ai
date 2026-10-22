"""The sentence about the shortest password, under the field of the Web App
page (`frontend/src/teile/SettingsWebApp.svelte`): it stands under the open
field before anything is typed, and it is gone while a password stands behind
the lock.

The interface has no DOM library here, so these tests read the page's source:
where the sentence stands, what it is guarded by, and — by running the guard
itself — in which of the four states it shows.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.i18n import t

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "frontend/src/teile/SettingsWebApp.svelte"
LOCALES = ROOT / "app" / "locales"
SENTENCE = "webapp.error_password_too_short"


def _source() -> str:
    return PAGE.read_text(encoding="utf-8")


def _markup() -> str:
    text = _source()
    return text[text.index('<div class="content">'):text.index("<style>")]


def _expression(name: str) -> str:
    """The expression a `$derived` of the page is made of, by name."""
    found = re.search(rf"const {name} = \$derived\((.+)\)\s*$", _source(), re.MULTILINE)
    assert found, f"the page has no `{name}`"
    return found.group(1)


def _run(expression: str, **names) -> bool:
    """Runs one expression of the page for one state. It is translated word
    by word; a name it reads that is not given here stops the run instead of
    passing."""
    python = expression.replace("&&", " and ").replace("||", " or ")
    python = re.sub(r"!(?!=)", " not ", python)
    return bool(eval(python, {"__builtins__": {}}, names))


def _state(**fields):
    return type("State", (), fields)


def _shows(*, password: bool, changing: bool, minimum: int, loaded: bool = True) -> bool:
    """Whether the sentence shows: the page's lock and its guard, both run."""
    locked = _run(_expression("locked"), webapp=_state(password=password), changing=changing)
    return _run(
        _expression("showMinimum"),
        webapp=_state(loaded=loaded, passwordMin=minimum),
        locked=locked,
    )


def test_the_sentence_stands_in_the_markup_with_the_number_from_the_service():
    markup = _markup()

    assert f"t('{SENTENCE}', {{ n: webapp.passwordMin }})" in markup


def test_it_stands_under_the_password_row_and_above_the_address_row():
    markup = _markup()

    password_row = markup.index("onclick={setPassword}")
    sentence = markup.index(f"t('{SENTENCE}', {{ n: webapp.passwordMin }})")
    address_row = markup.index("t('webapp.address')")

    assert password_row < sentence < address_row


def test_the_sentence_is_behind_its_guard():
    markup = _markup()
    sentence = markup.index('id="password-minimum"')
    opening = markup.rindex("{#if", 0, sentence)

    assert markup[opening:].startswith("{#if showMinimum}")


def test_the_field_points_at_the_sentence_only_while_it_shows():
    markup = _markup()

    assert "aria-describedby={showMinimum ? 'password-minimum' : undefined}" in markup


def test_with_no_password_the_sentence_shows_before_anything_is_typed():
    assert _shows(password=False, changing=False, minimum=8) is True


def test_the_pen_opens_the_field_and_the_sentence_with_it():
    assert _shows(password=True, changing=True, minimum=8) is True


def test_silence_with_a_password_standing_the_sentence_does_not_show():
    assert _shows(password=True, changing=False, minimum=8) is False


def test_silence_before_the_service_has_said_the_number_nothing_is_claimed():
    assert _shows(password=False, changing=False, minimum=0) is False
    assert _shows(password=False, changing=False, minimum=8, loaded=False) is False


def test_the_guard_does_not_wait_for_the_typing():
    assert "typed" not in _expression("showMinimum")


def test_the_error_row_after_a_refused_set_is_still_there():
    source = _source()

    assert "password_too_short: 'webapp.error_password_too_short'" in source
    assert '<div class="row failure" role="alert">' in source


@pytest.mark.parametrize(
    ("language", "sentence"),
    [
        ("de", "Das Passwort braucht mindestens 8 Zeichen."),
        ("en", "The password needs at least 8 characters."),
    ],
)
def test_the_sentence_reads_as_the_catalogue_has_it(language, sentence):
    assert t(SENTENCE, language, n=8) == sentence
    catalogue = json.loads((LOCALES / f"{language}.json").read_text(encoding="utf-8"))
    assert "{n}" in catalogue["webapp"]["error_password_too_short"]
