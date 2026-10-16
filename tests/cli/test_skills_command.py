"""``/skills``: the skills with how they stand, one written and one edited
in the editor, the switch for offering a skill automatically, and a copy of
your own reset or deleted. The service is the stand-in, the editor a
function that hands back a text; nothing is drawn."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from cli import commands, editor, skills
from cli.interfaces import Asker, Context, Entry
from cli.texts import Texts
from tests.cli.conftest import RecordingRenderer, RecordingScreen
from tests.cli.stub_service import StubService, model


def texts() -> Texts:
    return Texts("en")


class Asking(Asker):
    def __init__(self) -> None:
        self.shown: list[list[Entry]] = []
        self.heads: list[str] = []
        self.picks: list[int | None] = []
        self.typed: list[str | None] = []
        self.questions: list[str] = []

    def choose(self, entries: Any, head: str = "") -> int | None:
        self.shown.append(list(entries))
        self.heads.append(head)
        return self.picks.pop(0) if self.picks else None

    def ask_text(
        self, head: str, *, secret: bool = False, default: str | None = None
    ) -> str | None:
        self.questions.append(head)
        return self.typed.pop(0) if self.typed else None

    def rows(self) -> list[list[str]]:
        return [[text for _, text in entry.cells] for entry in self.shown[-1]]


def skill(description: str, *, auto: bool, own: bool, shipped: bool, text: str = "") -> dict[str, Any]:
    return {
        "beschreibung": description, "auto": auto, "eigen": own, "mitgeliefert": shipped,
        "inhalt": text or f"---\ndescription: {description}\nauto: {str(auto).lower()}\n---\n\nDo it.\n",
    }


@pytest.fixture
def skilled(
    stub: StubService, wire: Callable[[httpx.Client], Context], stub_http: httpx.Client
) -> Context:
    stub.models = [model("local", "Local Model")]
    stub.skill_files = {
        "handoff": skill("Hands the work over.", auto=True, own=False, shipped=True),
        "cleanup": skill("Cleans up.", auto=False, own=True, shipped=True),
        "notes": skill("Keeps notes.", auto=True, own=True, shipped=False),
    }
    context = wire(stub_http)
    context.asker = Asking()
    context.renderer = RecordingRenderer()
    context.screen = RecordingScreen(context)
    context.commands = commands.build_commands(context)
    return context


class Editor:
    """What the editor hands back, in turn, and the texts it was opened
    with."""

    def __init__(self) -> None:
        self.results: list[str | None] = []
        self.given: list[str] = []

    def append(self, text: str | None) -> None:
        self.results.append(text)

    def __call__(self, ctx: Any, text: str) -> str | None:
        self.given.append(text)
        return self.results.pop(0) if self.results else None


@pytest.fixture
def editing(monkeypatch: pytest.MonkeyPatch) -> Editor:
    fake = Editor()
    monkeypatch.setattr(editor, "edit", fake)
    return fake


def actions(stub: StubService, what: str) -> list[tuple[str, Any]]:
    return [(name, body) for kind, name, body in stub.skill_actions if kind == what]


# --- The selection -----------------------------------------------------------------------------


def test_the_selection_has_write_on_top_and_each_skill_with_its_state_and_description(skilled):
    skilled.commands.run("/skills")
    assert skilled.asker.rows() == [
        [texts().t("skills.schreiben")],
        ["/cleanup", texts().t("skills.geaendert"), texts().t("status.inaktiv")],
        ["/handoff", "", texts().t("status.aktiv")],
        ["/notes", "", texts().t("status.aktiv")],
    ]
    assert [entry.note for entry in skilled.asker.shown[-1]] == [
        "", "Cleans up.", "Hands the work over.", "Keeps notes."
    ]


def test_without_skills_only_write_stands_there(skilled, stub):
    stub.skill_files.clear()
    skilled.commands.run("/skills")
    assert skilled.asker.rows() == [[texts().t("skills.schreiben")]]


def test_leaving_the_selection_changes_nothing(skilled, stub):
    skilled.commands.run("/skills")
    assert stub.skill_actions == []
    assert skilled.renderer.notices == [] and skilled.renderer.errors == []


# --- Writing -------------------------------------------------------------------------------------


def test_a_new_skill_is_asked_for_its_name_opened_from_the_template_and_created(skilled, stub, editing):
    editing.append("---\ndescription: Mine.\nauto: false\n---\n\nSteps.\n")
    skilled.asker.picks = [0]
    skilled.asker.typed = ["/journal"]
    skilled.commands.run("/skills")
    assert skilled.asker.questions == [texts().t("skills.neu_name")]
    assert editing.given == [
        f"---\n{texts().t('skills.template_description')}\nauto: false\n---\n\n"
        f"{texts().t('skills.template_instructions')}\n"
    ]
    assert actions(stub, "create") == [
        ("journal", {"name": "journal", "inhalt": "---\ndescription: Mine.\nauto: false\n---\n\nSteps.\n"})
    ]
    assert skilled.renderer.notices == [texts().t("skills.geschrieben", name="journal")]


def test_the_list_behind_the_slash_reads_again_after_a_new_skill(skilled, stub, editing):
    assert skilled.commands.skills_matching("jour") == []
    editing.append("---\ndescription: Mine.\nauto: false\n---\n\nSteps.\n")
    skilled.asker.picks = [0]
    skilled.asker.typed = ["journal"]
    skilled.commands.run("/skills")
    assert [entry["name"] for entry in skilled.commands.skills_matching("jour")] == ["journal"]


def test_an_empty_name_or_an_editor_that_hands_back_nothing_sends_nothing(skilled, stub, editing):
    skilled.asker.picks = [0, 0]
    skilled.asker.typed = ["", "journal"]
    skilled.commands.run("/skills")
    assert editing.given == []
    skilled.commands.run("/skills")
    assert editing.given != []
    assert stub.skill_actions == []
    assert skilled.renderer.notices == []


def test_a_refusal_of_the_service_stands_with_its_sentence_and_nothing_is_said_written(skilled, stub, editing):
    stub.refuse_skill = "The header is not a list of fields."
    editing.append("broken")
    skilled.asker.picks = [0]
    skilled.asker.typed = ["journal"]
    skilled.commands.run("/skills")
    assert skilled.renderer.errors == ["The header is not a list of fields."]
    assert skilled.renderer.notices == []


# --- The menu of one skill ----------------------------------------------------------------


def test_a_bundled_skill_without_a_copy_has_neither_reset_nor_delete(skilled):
    skilled.commands.run("/skills handoff")
    assert skilled.asker.rows() == [
        [texts().t("skills.bearbeiten")],
        [texts().t("skills.selbst"), texts().t("status.aktiv")],
    ]


def test_a_changed_bundled_skill_offers_reset_and_one_of_your_own_delete(skilled):
    skilled.commands.run("/skills cleanup")
    assert skilled.asker.rows()[-1] == [texts().t("skills.zuruecksetzen")]
    skilled.commands.run("/skills notes")
    assert skilled.asker.rows()[-1] == [texts().t("skills.loeschen")]


def test_edit_opens_the_file_as_it_lies_and_puts_the_changed_text(skilled, stub, editing):
    before = stub.skill_files["handoff"]["inhalt"]
    editing.append("---\ndescription: Hands it over, again.\nauto: true\n---\n\nNew.\n")
    skilled.asker.picks = [0]
    skilled.commands.run("/skills handoff")
    assert editing.given == [before]
    assert actions(stub, "save") == [
        ("handoff", {"inhalt": "---\ndescription: Hands it over, again.\nauto: true\n---\n\nNew.\n"})
    ]
    assert skilled.renderer.notices == [texts().t("skills.geschrieben", name="handoff")]


def test_edit_with_nothing_back_from_the_editor_sends_nothing(skilled, stub, editing):
    skilled.asker.picks = [0]
    skilled.commands.run("/skills handoff")
    assert stub.skill_actions == []
    assert skilled.renderer.notices == []


def test_the_switch_puts_auto_and_says_the_line_as_it_now_stands(skilled, stub):
    skilled.asker.picks = [1]
    skilled.commands.run("/skills handoff")
    assert actions(stub, "auto") == [("handoff", {"auto": False})]
    assert skilled.renderer.notices == [
        f"/handoff  {texts().t('skills.geaendert')}  {texts().t('status.inaktiv')}  Hands the work over."
    ]


def test_reset_deletes_with_no_question_and_says_the_sentence(skilled, stub):
    skilled.asker.picks = [2]
    skilled.commands.run("/skills cleanup")
    assert actions(stub, "remove") == [("cleanup", None)]
    assert skilled.renderer.notices == [texts().t("skills.zurueckgesetzt", name="cleanup")]
    assert stub.skill_files["cleanup"]["eigen"] is False


def test_delete_asks_and_a_yes_deletes_and_says_it(skilled, stub, monkeypatch):
    asked: list[str] = []
    monkeypatch.setattr(skills.servers, "ask", lambda ctx, question: asked.append(question) or True)
    skilled.asker.picks = [2]
    skilled.commands.run("/skills notes")
    assert asked == [texts().t("skills.loeschen_frage", name="notes")]
    assert actions(stub, "remove") == [("notes", None)]
    assert "notes" not in stub.skill_files
    assert skilled.renderer.notices == [texts().t("skills.geloescht", name="notes")]


def test_a_no_to_the_question_deletes_nothing(skilled, stub, monkeypatch):
    monkeypatch.setattr(skills.servers, "ask", lambda ctx, question: False)
    skilled.asker.picks = [2]
    skilled.commands.run("/skills notes")
    assert stub.skill_actions == []
    assert skilled.renderer.notices == []


def test_leaving_the_menu_sends_nothing(skilled, stub):
    skilled.commands.run("/skills notes")
    assert stub.skill_actions == []


def test_a_refused_switch_stands_with_its_sentence(skilled, stub):
    stub.refuse_skill = "Cannot be written."
    skilled.asker.picks = [1]
    skilled.commands.run("/skills handoff")
    assert skilled.renderer.errors == ["Cannot be written."]
    assert skilled.renderer.notices == []


# --- The words behind the command ----------------------------------------------------------


def test_a_number_counts_into_the_selection_and_one_is_write(skilled):
    skilled.commands.run("/skills 3")
    assert skilled.asker.heads[-1].startswith("/handoff")


def test_a_slash_in_front_of_the_name_is_taken_off(skilled):
    skilled.commands.run("/skills /notes")
    assert skilled.asker.heads[-1].startswith("/notes")


@pytest.mark.parametrize("line", ["/skills 9", "/skills 0", "/skills nothing"])
def test_a_number_that_is_no_skill_and_any_other_word_are_unknown(skilled, line):
    skilled.commands.run(line)
    assert len(skilled.renderer.errors) == 1
    assert skilled.asker.shown == []
