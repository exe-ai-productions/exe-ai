"""The upkeep sentence of the base prompt names the headings a fresh
``exe.md`` is laid out under. The scaffold writes those headings into the
file; the model reads them in the sentence. Both must say the same, or the
model looks for a heading the file does not have."""

from __future__ import annotations

import re

from app import grundprompt, ordnerwissen


def _named_in_the_sentence() -> list[str]:
    """The headings the upkeep sentence quotes, in its order."""
    paragraph = next(
        part
        for part in grundprompt.EXEMD_PFLEGEN.split("\n\n")
        if part.startswith("A fresh `exe.md` is laid out under")
    )
    # The paragraph is wrapped; a heading may run over the end of a line.
    return re.findall(r'"([^"]+)"', " ".join(paragraph.split()))


def _written_by_the_scaffold() -> list[str]:
    return [
        line[3:] for line in ordnerwissen.GERUEST.splitlines() if line.startswith("## ")
    ]


def test_the_upkeep_sentence_names_exactly_the_headings_of_the_scaffold():
    assert _named_in_the_sentence() == _written_by_the_scaffold()


def test_the_sentence_counts_as_many_headings_as_it_names():
    assert len(_named_in_the_sentence()) == 4
    assert "under four headings" in " ".join(grundprompt.EXEMD_PFLEGEN.split())


def test_the_headings_reach_the_prompt_a_model_reads():
    """Where the upkeep block is part of the prompt, every heading of the
    scaffold stands in it."""
    prompt = " ".join(
        grundprompt.bauen(werkzeuge=True, ordner=["/one"], ordnerwissen_pflegen=True).split()
    )
    for heading in _written_by_the_scaffold():
        assert f'"{heading}"' in prompt
