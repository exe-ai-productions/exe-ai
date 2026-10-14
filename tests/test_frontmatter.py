"""The header of a skill or an agent file ends at its closing line.

Three readers and two writers share one cut and one escape
(``app/frontmatter.py``). A value with three hyphens in it must neither end
the header nor be written raw, and a file with a byte order mark is a
healthy file.
"""

from __future__ import annotations

import pytest
import yaml

from app import agentenfelder, skills
from app.agenten import AgentDateiKaputt, agent_aus_text
from app.tools import skill

def _header_of(file_text: str) -> str:
    """The header of a file the form wrote: between its first line and the
    first line that is the marker alone."""
    return file_text.removeprefix("---\n").split("\n---\n", 1)[0]


HEADER_WITH_HYPHENS = '---\ndescription: "A---B"\n---\n\nDo the thing.\n'


# --- the cut ---------------------------------------------------------------


def test_the_header_ends_at_the_closing_line_not_at_three_hyphens():
    from app import frontmatter

    head, body = frontmatter.split(HEADER_WITH_HYPHENS)

    assert yaml.safe_load(head) == {"description": "A---B"}
    assert body.strip() == "Do the thing."


@pytest.mark.parametrize(
    "text",
    [
        "---\ndescription: Da\n---\n\nBody.\n",
        "---\r\ndescription: Da\r\n---\r\n\r\nBody.\r\n",
        "---\ndescription: Da\n---   \n\nBody.\n",
        "---\ndescription: Da\n---",
        "﻿---\ndescription: Da\n---\n\nBody.\n",
        "---\ndescription: Da\n---\n\nBody.\n---\nmore\n",
    ],
    ids=["plain", "crlf", "trailing-space", "no-newline-after", "bom", "marker-in-body"],
)
def test_silence_the_files_that_read_today_read_the_same(text):
    from app import frontmatter

    head, body = frontmatter.split(text)

    assert yaml.safe_load(head) == {"description": "Da"}
    assert body.lstrip().startswith("Body.") or body == ""
    # The body keeps a marker line of its own whole.
    if "more" in text:
        assert "---\nmore" in body


@pytest.mark.parametrize(
    "text",
    [
        "description: Da\n---\nBody\n",
        "",
        "----\ndescription: Da\n---\nBody\n",
    ],
)
def test_a_text_without_an_opening_line_is_refused(text):
    from app import frontmatter

    with pytest.raises(frontmatter.NoFrontMatter):
        frontmatter.split(text)


@pytest.mark.parametrize(
    "text",
    ["---\ndescription: Da\n", "---\ndescription: Da\n---Body\n", "---"],
)
def test_a_text_without_a_closing_line_is_refused(text):
    from app import frontmatter

    with pytest.raises(frontmatter.NoClosingLine):
        frontmatter.split(text)


# --- the three readers -----------------------------------------------------


def test_a_skill_with_hyphens_in_a_value_loads(tmp_path):
    folder = tmp_path / "probe"
    folder.mkdir()
    (folder / skills.SKILL_DATEI).write_text(HEADER_WITH_HYPHENS, encoding="utf-8")

    read = skills.skill_lesen(folder)

    assert read.beschreibung == "A---B"
    assert read.anleitung == "Do the thing."


def test_an_agent_with_hyphens_in_a_value_loads():
    agent = agent_aus_text("probe", HEADER_WITH_HYPHENS)

    assert agent.description == "A---B"
    assert agent.prompt == "Do the thing."


def test_the_form_writes_a_field_into_such_a_file_without_moving_the_body():
    written = agentenfelder.felder_anwenden(HEADER_WITH_HYPHENS, {"max_rounds": 7})

    agent = agent_aus_text("probe", written)
    assert agent.description == "A---B"
    assert agent.prompt == "Do the thing."
    assert agent.runden == 7


def test_a_skill_file_with_a_byte_order_mark_loads_like_one_without(tmp_path):
    plain_folder = tmp_path / "plain"
    marked_folder = tmp_path / "marked"
    for folder, text in (
        (plain_folder, "---\ndescription: Da\nauto: false\n---\n\nTu es.\n"),
        (marked_folder, "﻿---\ndescription: Da\nauto: false\n---\n\nTu es.\n"),
    ):
        folder.mkdir()
        (folder / skills.SKILL_DATEI).write_text(text, encoding="utf-8")

    bom = skills.skill_lesen(marked_folder)
    plain = skills.skill_lesen(plain_folder)

    assert (bom.beschreibung, bom.anleitung, bom.auto) == (
        plain.beschreibung,
        plain.anleitung,
        plain.auto,
    )


def test_silence_a_skill_file_without_a_header_stays_refused(tmp_path):
    folder = tmp_path / "ohne-kopf"
    folder.mkdir()
    (folder / skills.SKILL_DATEI).write_text("﻿Just text.\n", encoding="utf-8")

    with pytest.raises(skills.SkillKaputt) as caught:
        skills.skill_lesen(folder)

    assert caught.value.kind == "kopfteil"


def test_silence_a_file_without_a_closing_line_keeps_its_refusal():
    with pytest.raises(AgentDateiKaputt) as caught:
        agent_aus_text("probe", "---\ndescription: Da\n")

    assert caught.value.key == "closing_missing"


# --- the two writers -------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["Use for A---B and a----b", "Ctrl\x84 x \x9f y \x7f z", "Grüße: #1 yes"],
    ids=["hyphen-runs", "c1-controls", "colon-hash-yes"],
)
def test_the_form_writes_a_text_field_that_reads_back_unchanged(text):
    fresh = agentenfelder.neu_bauen({"description": text}, "Do it.")

    agent = agent_aus_text("probe", fresh)

    assert agent.description == text
    assert agent.prompt == "Do it."
    assert yaml.safe_load(_header_of(fresh))["description"] == text
    fresh.encode("utf-8")


def test_the_form_writes_a_list_entry_that_reads_back_unchanged():
    fresh = agentenfelder.neu_bauen({"tools": ["a b", "x\x9fy"]}, "Do it.")

    assert yaml.safe_load(_header_of(fresh))["tools"] == ["a b", "x\x9fy"]


@pytest.mark.parametrize("text", ["A plain sentence.", "With: a colon", "Grüße und Äpfel"])
def test_silence_ordinary_text_is_written_byte_for_byte_as_before(text):
    import json

    fresh = agentenfelder.neu_bauen({"description": text}, "Do it.")

    assert f"description: {json.dumps(text, ensure_ascii=False)}\n" in fresh


def test_silence_the_skill_writer_still_writes_what_it_wrote():
    text = skills.skill_file_text("Use for A---B", True, "Do it.")

    assert text == (
        '---\ndescription: "Use for A\\u002d\\u002d\\u002dB"\nauto: true\n---\n\nDo it.\n'
    )


# --- the model's auto field ------------------------------------------------


@pytest.mark.parametrize("value", ["false", "False", "no", "0", "", "yes", 1, 0, None, []])
async def test_a_value_that_is_not_true_does_not_switch_auto_on(tmp_path, value):
    own = tmp_path / "own"
    own.mkdir()

    await skill.schreiben(
        {"name": "written", "description": "Da", "instruction": "Tu es.", "auto": value}, own
    )

    assert "auto: false\n" in (own / "written" / skills.SKILL_DATEI).read_text(encoding="utf-8")


@pytest.mark.parametrize("value", [True, "true", "True", "TRUE"])
async def test_silence_true_in_either_form_switches_auto_on(tmp_path, value):
    own = tmp_path / "own"
    own.mkdir()

    await skill.schreiben(
        {"name": "written", "description": "Da", "instruction": "Tu es.", "auto": value}, own
    )

    assert "auto: true\n" in (own / "written" / skills.SKILL_DATEI).read_text(encoding="utf-8")


async def test_silence_leaving_auto_out_and_false_stay_false(tmp_path):
    own = tmp_path / "own"
    own.mkdir()

    await skill.schreiben({"name": "eins", "description": "Da", "instruction": "Tu es."}, own)
    await skill.schreiben(
        {"name": "zwei", "description": "Da", "instruction": "Tu es.", "auto": False}, own
    )

    for name in ("eins", "zwei"):
        assert "auto: false\n" in (own / name / skills.SKILL_DATEI).read_text(encoding="utf-8")
