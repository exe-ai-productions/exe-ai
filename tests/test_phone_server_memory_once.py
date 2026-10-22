"""A running server on the phone page says "Memory" once.

The used memory of a running server stands as the first line inside the group
that holds the memory numbers, as a bare size; the word itself is the heading
of that group. A server without memory numbers (embedding, cleanup) has no such
group, so its line keeps the word and stays in the first group.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIEW = (ROOT / "frontend" / "src" / "phone" / "servers" / "ServerView.svelte").read_text(encoding="utf-8")

MEMORY_GROUP = "<Group title={t('modell.gruppe_speicher')}>"


def _blocks() -> tuple[str, str, str]:
    """The text before, inside and after the memory group."""
    before, rest = VIEW.split(MEMORY_GROUP, 1)
    inside, after = rest.split("\n  </Group>", 1)
    return before, inside, after


def test_the_used_memory_stands_inside_the_memory_group_as_its_first_line():
    _, inside, _ = _blocks()
    line = inside.index("<Line label={usedMemory} />")
    first_field = inside.index("{#each memoryFields")
    assert line < first_field
    assert "{#if usedMemory}" in inside
    assert "row.running && report?.belegt_gb != null ? gbLabel(report.belegt_gb) : ''" in VIEW


def test_the_word_memory_stands_once_over_a_running_server_with_memory_numbers():
    before, inside, _ = _blocks()
    # Inside the group the line is a bare size: no second "Memory" label.
    assert "kopf.speicher" not in inside
    assert "modell.im_speicher" not in inside
    # Before the group the first group no longer repeats it for such a server.
    assert re.search(r"!memoryFields\.length", before)
    assert before.count("kopf.speicher") == 1


def test_a_server_without_memory_numbers_keeps_the_line_in_the_first_group():
    before, _, _ = _blocks()
    first_group = before.split("<Group>", 1)[1].split("</Group>", 1)[0]
    assert "kopf.speicher" in first_group
    assert "modell.im_speicher" in first_group
    assert "{#if usedMemory && !memoryFields.length}" in first_group


def test_the_memory_group_only_exists_for_servers_with_memory_numbers():
    assert "{#if memoryFields.length}\n  " + MEMORY_GROUP in VIEW
