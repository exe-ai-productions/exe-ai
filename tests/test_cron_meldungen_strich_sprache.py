"""The sentences the service itself puts together for a schedule's
notification (app/cronmeldung.py, app/cronablauf.py): their parts are joined
with a hyphen, never a long dash, and the whole sentence is in the language
chosen for the interface.

The catalogue already carries no long dash; what stayed behind was the join
the code makes between the task text and the reason, between a script's name
and its last line, and between the task text and "ran once, goal not
reached". These tests read the finished sentences, not the source of the
join, and one guard reads the source so a new join cannot bring it back.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app import cronablauf, cronmeldung
from app.i18n import t

DASH = "—"
TASK = "Ins Postfach sehen"
APP = Path(__file__).resolve().parent.parent / "app"


@pytest.fixture
def announced(monkeypatch):
    """Announcements, collected instead of played."""
    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        cronablauf.cronmeldung, "melden",
        lambda text, *, erfolgreich, sprache=None: calls.append((text, erfolgreich)),
    )
    return calls


def _entry(repos, **fields):
    fields.setdefault("deliver", "announce")
    return repos.cronjobs.erstellen(
        agent="a", task=TASK, zeitplan="*/15 * * * *", herkunft="chat", **fields
    )


# --- The three joins -------------------------------------------------------


@pytest.mark.parametrize("language", ["en", "de"])
def test_the_reason_is_joined_to_the_task_with_a_hyphen(language):
    reason = t("jobs.grund.zeitgrenze", language)
    assert reason != "jobs.grund.zeitgrenze"

    text = cronmeldung.mit_grund(TASK, "zeitgrenze", language)

    assert text == f"{TASK} - {reason}"
    assert DASH not in text


async def test_the_sentence_of_the_limit_and_its_reason_carry_no_long_dash(repos, announced):
    """The line the finding was made on: the catalogue's hyphen and the
    service's join side by side, which used to put a long dash next to
    the hyphen of "stopped after 1 failed run"."""
    entry = _entry(repos, fehlergrenze=1)

    await cronablauf.ausgang_verbuchen(
        repos, entry.id, TASK, erfolgreich=False, grund="zeitgrenze", sprache="en"
    )

    assert announced == [
        (f"{TASK} - stopped after 1 failed run - time limit reached", False)
    ]
    assert DASH not in announced[0][0]


async def test_a_one_off_without_a_goal_report_joins_its_ending_with_a_hyphen(repos, announced):
    entry = _entry(repos, einmalig=True, ziel="a new mail")
    repos.cronjobs.aktiv_setzen(entry.id, False)

    await cronablauf.ziel_verbuchen(
        repos, entry.id, TASK, bericht=None, erfolgreich=True, sprache="en"
    )

    assert announced == [
        (f"{TASK} - {t(cronablauf.ZIEL_NICHT_ERREICHT, 'en')}", False)
    ]
    assert DASH not in announced[0][0]


async def test_silence_a_sentence_without_a_reason_stays_the_task_text(repos, announced):
    """No reason, nothing to join: the text is the task text byte for byte,
    with no hyphen left dangling behind it."""
    entry = _entry(repos)

    for reason in (None, "", "fertig"):
        assert cronmeldung.mit_grund(TASK, reason, "de") == TASK

    await cronablauf.melde_wenn_faellig(
        repos, entry.id, TASK, erfolgreich=True, sprache="de"
    )

    assert announced == [(TASK, True)]


# --- The language of the whole sentence ------------------------------------


@pytest.mark.parametrize(
    "reason", ["zeitgrenze", "rundengrenze", "anbieter_ausfall", "fehler_allgemein"]
)
async def test_the_stop_sentence_is_wholly_german_in_german(repos, announced, reason):
    entry = _entry(repos, fehlergrenze=1)

    await cronablauf.ausgang_verbuchen(
        repos, entry.id, TASK, erfolgreich=False, grund=reason, sprache="de"
    )

    stop = t("cronjobs.nach_fehlversuchen_gestoppt_eins", "de", aufgabe=TASK)
    why = t(f"jobs.grund.{reason}", "de")
    assert why != f"jobs.grund.{reason}"
    assert announced == [(f"{stop} - {why}", False)]
    english_stop = t("cronjobs.nach_fehlversuchen_gestoppt_eins", "en", aufgabe=TASK)
    assert english_stop not in announced[0][0]
    assert t(f"jobs.grund.{reason}", "en") not in announced[0][0]


async def test_silence_the_stop_sentence_stays_english_in_english(repos, announced):
    entry = _entry(repos, fehlergrenze=1)

    await cronablauf.ausgang_verbuchen(
        repos, entry.id, TASK, erfolgreich=False, grund="zeitgrenze", sprache="en"
    )

    assert "stopped after 1 failed run" in announced[0][0]
    assert t("cronjobs.nach_fehlversuchen_gestoppt_eins", "de", aufgabe=TASK) not in announced[0][0]


async def test_a_one_off_ending_is_german_in_german(repos, announced):
    entry = _entry(repos, einmalig=True, ziel="neue Post")
    repos.cronjobs.aktiv_setzen(entry.id, False)

    await cronablauf.ziel_verbuchen(
        repos, entry.id, TASK, bericht=None, erfolgreich=True, sprache="de"
    )

    assert announced == [(f"{TASK} - {t(cronablauf.ZIEL_NICHT_ERREICHT, 'de')}", False)]
    assert t(cronablauf.ZIEL_NICHT_ERREICHT, "en") not in announced[0][0]


# --- The guard: no join with a long dash is built in the two modules --------


def _text_strings(path: Path) -> list[tuple[int, str]]:
    """The string pieces of a module that can reach a person: everything
    except docstrings and the first argument of a log call (those are for the
    log file, in English, and keep their dash)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                skip.add(id(first.value))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"debug", "info", "warning", "error", "exception"}:
                for argument in node.args[:1]:
                    for part in ast.walk(argument):
                        skip.add(id(part))
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and DASH in node.value
        and id(node) not in skip
    ]


@pytest.mark.parametrize("module", ["cronmeldung.py", "cronablauf.py"])
def test_the_two_modules_build_no_sentence_with_a_long_dash(module):
    assert _text_strings(APP / module) == []


def test_the_guard_sees_a_join_with_a_long_dash(tmp_path):
    """Counter-check: the guard is not blind. A join and a log line side by
    side - only the join is found."""
    probe = tmp_path / "probe.py"
    probe.write_text(
        'def f(log, a):\n'
        '    """A docstring — skipped."""\n'
        '    log.info("a log line — skipped")\n'
        '    return f"{a} — joined"\n',
        encoding="utf-8",
    )

    found = _text_strings(probe)

    assert [line for line, _ in found] == [4]
