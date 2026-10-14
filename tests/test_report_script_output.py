"""The reader shows what a script wrote with its lines, and keeps the markdown
reading for an agent's report
(`frontend/src/teile/ModulAgenten.svelte`, `frontend/src/teile/Bildschau.svelte`).

A script's output reached the reader through the markdown path, which folds a
single line break into a space: three lines became one. The run row under
Settings › Cronjobs already shows the same text as text with its breaks.
"""

from __future__ import annotations

import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent / "frontend/src/teile"
AGENTS = (FRONTEND / "ModulAgenten.svelte").read_text(encoding="utf-8")
READER = (FRONTEND / "Bildschau.svelte").read_text(encoding="utf-8")

# The report page of the reader: from its body to the end of that branch.
REPORT = READER.split("{#if report.plain}", 1)[1].split("{:else if bildschau.framed}", 1)[0]
PLAIN, MARKDOWN = REPORT.split("{:else}", 1)


def _open_report() -> str:
    return AGENTS.split("function berichtOeffnen(auftrag) {", 1)[1].split("\n  }\n", 1)[0]


def test_a_script_run_is_marked_plain_when_its_report_opens():
    body = _open_report()
    assert "plain: auftrag.agent === SCRIPT_RUN" in body
    marker = re.search(r"const SCRIPT_RUN = '([^']+)'", AGENTS)
    assert marker and marker.group(1) == "(skript)"


def test_the_marker_is_the_one_the_service_writes():
    """One spelling for the run's agent: the service's marker and the
    interface's word for it (`lib/agentmarke.js`) are the same string."""
    service = (Path(__file__).resolve().parent.parent / "app/skriptlauf.py").read_text(encoding="utf-8")
    assert re.search(r'SKRIPT_AGENT = "\(skript\)"', service)
    words = (Path(__file__).resolve().parent.parent / "frontend/src/lib/agentmarke.js").read_text(
        encoding="utf-8"
    )
    assert "'(skript)': 'cronjobs.kind_script'" in words


def test_a_plain_report_is_text_with_its_line_breaks_not_markdown():
    assert '<p class="prose">{report.text ?? \'\'}</p>' in PLAIN
    assert "dateiTeile" not in PLAIN
    # `.prose` keeps the line breaks and breaks long words (no markdown fold).
    prose = READER.split("  .prose {", 1)[1].split("}", 1)[0]
    assert "white-space: pre-wrap" in prose


def test_an_agents_report_still_goes_through_the_markdown_reader_with_its_cards():
    """Silence probe: head, reason and the file cards are the same branch as
    before; only the body of a plain report differs."""
    assert "{#each dateiTeile(report.text ?? '') as piece, i (i)}" in MARKDOWN
    assert "<Dateikarte" in MARKDOWN
    assert 'class="body berichttext" onclick={copyCode}' in MARKDOWN
    head = READER.split("{#if report.plain}", 1)[0]
    for part in ("{report.task}", "{report.agent}", "{report.time}", "{report.reason}"):
        assert part in head


def test_only_a_report_that_says_plain_is_read_as_plain():
    """The flag is read in two places only — the body and the download — and
    both read it as given: a report that does not set it stays markdown."""
    assert READER.count("{#if report.plain}") == 1
    assert READER.count("report.plain ?") == 1
    assert AGENTS.count("plain:") == 1


def test_the_download_of_a_plain_report_is_plain_text():
    download = READER.split("async function download() {", 1)[1].split("\n  }\n", 1)[0]
    assert "report.plain ? ['txt', 'text/plain'] : ['md', 'text/markdown']" in download
