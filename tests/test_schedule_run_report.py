"""Settings › Cronjobs: a run under "last runs" unfolds onto what it wrote.

The row is a button that says whether it is open; open, it shows the run's
transcript the way the run card of the agents view does, read off the same
job by the run's id. What of a job is shown (``lib/runreport.js``) is run
under Node; how the page draws it is read off the source, the way the other
interface tests do.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
PAGE = (FRONTEND / "src/teile/SettingsCronjobs.svelte").read_text(encoding="utf-8")
AGENTS = (FRONTEND / "src/teile/ModulAgenten.svelte").read_text(encoding="utf-8")

# The rows of the last runs, from the loop's opening to its end.
ROWS = PAGE.split("{#each eigene.slice(0, LETZTE) as lauf (lauf.id)}", 1)[1].split("{/each}", 1)[0]


def test_a_run_row_is_a_button_that_says_whether_it_is_open():
    assert (
        '<button class="lauf" aria-expanded={lauf.id in reports} '
        "onclick={() => runToggle(lauf.id)}>" in ROWS
    )
    toggle = PAGE.split("function runToggle(id) {", 1)[1].split("\n  }\n", 1)[0]
    # A second click folds the row again; the first one reads the report.
    assert "if (id in reports) return runFold(id)" in toggle
    assert "reports = { ...reports, [id]: null }" in toggle
    assert "reportLoad(id)" in toggle


def test_an_open_row_shows_what_the_run_wrote():
    button, below = ROWS.split("</button>", 1)
    assert "{#if reports[lauf.id]}" in below
    assert "<Agentenverlauf schritte={reports[lauf.id].steps} />" in below
    assert '<p class="report-text">{reports[lauf.id].text}</p>' in below
    # The report stands under the row, not inside the button that opens it.
    assert "Agentenverlauf" not in button
    # The hairline parts the rows, now that a row is more than its button.
    assert ".run + .run {" in PAGE
    assert ".lauf + .lauf" not in PAGE


def test_the_report_is_read_the_way_the_run_card_reads_it():
    """One way for both views: the job itself, by the run's id."""
    load = PAGE.split("async function reportLoad(id) {", 1)[1].split("\n  }\n", 1)[0]
    assert "runReport(await api.auftrag(id))" in load
    # An answer counts only for a row still waiting for it: neither a late
    # report nor a late failure touches a row that was folded meanwhile.
    assert "if (reports[id] === null) reports = { ...reports, [id]: report }" in load
    assert "if (reports[id] !== null) return" in load
    assert "await api.auftrag(id)" in AGENTS
    assert "<Agentenverlauf schritte={protokolle[auftrag.id]}" in AGENTS


def test_time_and_ending_of_a_row_stay_as_they_were():
    """Silence probe: what the row said before, it says inside the button."""
    button = ROWS.split("</button>", 1)[0]
    assert '<span class="moment">{moment(lauf.wann)}</span>' in button
    assert (
        "<span class=\"gescheitert\">{t('jobs.zustand.gescheitert')}"
        "{grund(lauf) ? ` · ${grund(lauf)}` : ''}</span>" in button
    )
    assert "<span>{t('jobs.zustand.fertig')}</span>" in button
    # Five rows as before, and the count beside the heading.
    assert "<span class=\"zahl\">{Math.min(LETZTE, eigene.length)}/{eigene.length}</span>" in PAGE


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")


def _report(job: object) -> dict:
    driver = FRONTEND / f"runreport-{os.getpid()}.check.mjs"
    driver.write_text(
        "import { runReport } from './src/lib/runreport.js'\n"
        f"console.log('---REPORT---' + JSON.stringify(runReport({json.dumps(job)})))\n",
        encoding="utf-8",
    )
    try:
        run = subprocess.run(
            ["node", driver.name], cwd=FRONTEND, capture_output=True, text=True, timeout=60
        )
    finally:
        driver.unlink(missing_ok=True)
    assert run.returncode == 0, (run.stdout + run.stderr)[-3000:]
    return json.loads(run.stdout.split("---REPORT---", 1)[1].strip())


@needs_node
def test_an_agents_last_sentence_is_not_said_twice():
    steps = [
        {"nummer": 1, "typ": "status", "inhalt": "gestartet"},
        {"nummer": 2, "typ": "text", "inhalt": "The notes are summed up.\n"},
        {"nummer": 3, "typ": "ende", "inhalt": "fertig"},
    ]
    report = _report({"result": "The notes are summed up.", "schritte": steps})
    assert report == {"steps": steps, "text": ""}


@needs_node
def test_sentences_of_several_rounds_are_not_said_twice():
    """A run's result is its sentences of every round written as one text;
    the transcript shows each of them already."""
    steps = [
        {"nummer": 1, "typ": "text", "inhalt": "I read the file first."},
        {"nummer": 2, "typ": "tool_call", "inhalt": json.dumps({"name": "read_file"})},
        {"nummer": 3, "typ": "tool_result", "inhalt": json.dumps({"name": "read_file"})},
        {"nummer": 4, "typ": "text", "inhalt": "The notes are summed up."},
    ]
    result = "I read the file first.The notes are summed up."
    assert _report({"result": result, "schritte": steps}) == {"steps": steps, "text": ""}


@needs_node
def test_a_closing_text_that_is_no_sentence_stands_as_text():
    """A run that was handed on closes with a text of its own."""
    steps = [{"nummer": 1, "typ": "text", "inhalt": "I read the file first."}]
    report = _report({"result": "Handed on: half of the notes are read.", "schritte": steps})
    assert report == {"steps": steps, "text": "Handed on: half of the notes are read."}


@needs_node
def test_a_scripts_output_stands_as_text():
    """A script writes no sentence: its output is the result alone."""
    steps = [
        {"nummer": 1, "typ": "status", "inhalt": "Skript gestartet: backup.sh"},
        {"nummer": 2, "typ": "ergebnis", "inhalt": "3 files\ndone\n"},
    ]
    report = _report({"result": "3 files\ndone\n", "schritte": steps})
    assert report == {"steps": steps, "text": "3 files\ndone"}


@needs_node
def test_a_run_that_wrote_nothing_has_nothing_to_show():
    assert _report({"result": None, "schritte": []}) == {"steps": [], "text": ""}
    assert _report({}) == {"steps": [], "text": ""}
    # A run that ended without a result keeps its transcript.
    steps = [{"nummer": 1, "typ": "text", "inhalt": "I read the file first."}]
    assert _report({"result": None, "schritte": steps}) == {"steps": steps, "text": ""}
