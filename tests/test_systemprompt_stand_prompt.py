"""What the model reads about the program has to be true of the program.

Each test here pins one sentence that used to promise something the code
does not do — a guard that only runs in a job, a picture that never reaches
an answer, a folder named as shared that the user never shared — and the
silence probe beside it: the case where the sentence must still stand.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app import grundprompt, helper, skills
from app.agenten import Agent
from app.agentendock import AgentenDock
from app.schleifenwaechter import Schleifenwaechter
from app.tools import agentendock, bild_werkzeug, memory
from app.tools.registry import WerkzeugRegistry, WerkzeugVerboten
from tests.conftest import Bilddienst

PROJEKT = Path(__file__).resolve().parent.parent


def _flat(text: str) -> str:
    """Line breaks folded: where a template wraps is layout, not wording."""
    return " ".join(text.split())


def _job(**felder) -> grundprompt.Agentenlauf:
    return grundprompt.Agentenlauf(runden=8, minuten=20, **felder)


# --- The loop guard is a job's ------------------------------------------------


def test_a_chat_is_not_told_of_a_guard_it_does_not_have():
    """The guard that ends a run after the same refusal three times runs in
    a job only (app/schleifenwaechter.py); a chat has none."""
    chat = _flat(grundprompt.bauen(werkzeuge=True))
    assert "identical refusals" not in chat
    # The advice itself stays for everybody.
    assert "do not repeat a refused call unchanged" in chat


def test_a_job_with_tools_is_told_of_the_guard_with_its_number():
    job = _flat(grundprompt.bauen(werkzeuge=True, agentenlauf=_job()))
    assert f"After {Schleifenwaechter.GRENZE} identical refusals" in job
    # A job without tools has nothing that could be refused.
    without = _flat(grundprompt.bauen(agentenlauf=_job()))
    assert "identical refusals" not in without


# --- Handing work on: nobody reads the task first ----------------------------


def test_the_task_of_a_started_run_is_read_by_nobody_first():
    text = _flat(grundprompt.bauen(werkzeuge=True, agentenlauf=_job(beauftragen=True)))
    assert "the user reads it first" not in text
    assert "Nobody sees or edits the task on the way" in text
    # Nor is the job said to be one the user confirmed: it starts at once.
    assert "the user already confirmed" not in text


def test_the_cost_of_a_second_run_names_no_slots_and_no_half():
    """Two slots sharing one window half each holds for one kind of local
    server only; the sentence has to hold for every endpoint."""
    text = _flat(grundprompt.bauen(werkzeuge=True, agentenlauf=_job(beauftragen=True)))
    assert "half the context" not in text
    assert "slots" not in text
    assert "It is not free" in text


# --- Asking in the chat that sent the run off ---------------------------------


def test_a_run_the_chat_sent_off_is_told_its_calls_are_asked_about():
    asked = _flat(grundprompt.bauen(werkzeuge=True, agentenlauf=_job(ask_in_chat=True)))
    assert "put to them in the chat this job was started from" in asked
    assert "rejected outright" not in asked
    assert "no confirmation prompt in a job" not in asked


def test_any_other_run_is_still_told_its_calls_are_refused():
    """The silence probe: started by hand, by a schedule or by another run,
    nobody is asked."""
    refused = _flat(grundprompt.bauen(werkzeuge=True, agentenlauf=_job()))
    assert "rejected outright" in refused
    assert "put to them in the chat" not in refused


def test_a_helper_is_not_told_to_stop_for_a_permission():
    """A helper's call that needs a yes is asked about in its chat; stopping
    the run to report it would be stopping for nothing."""
    assert "permission" not in helper.PROMPT
    assert "a choice or a missing fact" in helper.PROMPT


# --- The memory promises only what holds -------------------------------------


def test_replacing_an_entry_is_asked_for_only_where_the_entries_are_in_sight():
    shown = _flat(grundprompt.bauen(gedaechtnis_schreiben=True, memory_travels=True))
    hidden = _flat(grundprompt.bauen(gedaechtnis_schreiben=True, memory_travels=False))
    assert "replace it instead of adding a second one" in shown
    assert "replace it instead of adding a second one" not in hidden
    # The saving itself is asked for in both.
    assert memory.WERKZEUG_NAME in hidden


def test_the_memory_tool_says_when_an_entry_is_in_front_of_the_model():
    shown = memory.werkzeug_beschreibung(True).beschreibung
    assert "every conversation from now on" not in shown
    assert "in the next conversation, not immediately" in shown
    assert "lists the entries you have stored" in shown


def test_the_memory_tool_promises_no_sight_where_the_memory_stays_away():
    hidden = memory.werkzeug_beschreibung(False).beschreibung
    assert memory.VERBORGEN in hidden
    assert "in front of you" not in hidden
    assert "lists the entries" not in hidden
    assert "a short part of" not in hidden
    assert "full existing text" in hidden


def test_the_offer_carries_the_description_for_this_side(tmp_path):
    registry = WerkzeugRegistry([], memory_pfad=tmp_path / "memory.md")

    def description(shown: bool) -> str:
        (eintrag,) = [
            w for w in registry.als_openai_werkzeuge(memory_shown=shown)
            if w["function"]["name"] == memory.WERKZEUG_NAME
        ]
        return eintrag["function"]["description"]

    assert memory.VERBORGEN in description(False)
    assert memory.VERBORGEN not in description(True)


# --- The dock is the program's, not a share ----------------------------------


def test_the_dock_is_named_apart_and_last():
    text = grundprompt.bauen(
        werkzeuge=True, ordner=["/u/a", "/d/dock"], dock="/d/dock",
        dateiwerkzeuge=["read_file"],
    )
    shared = text.split("The user has shared these working folders with you:\n\n")[1]
    assert shared.split("\n\n")[0] == "- /u/a"
    assert "The dock folder holds finished files delivered to the user" in text
    # Listed after the share, so "the first one" is the user's folder.
    assert text.index("- /u/a") < text.index("- /d/dock")


def test_a_run_with_only_the_dock_hears_of_no_share():
    text = grundprompt.bauen(
        werkzeuge=True, ordner=["/d/dock"], dock="/d/dock", dateiwerkzeuge=["read_file"],
    )
    assert "The user has shared" not in text
    assert "- /d/dock" in text


def test_a_folder_without_dock_reads_as_before():
    """The silence probe: no dock passed, every folder is a share."""
    text = grundprompt.bauen(
        werkzeuge=True, ordner=["/u/a", "/d/dock"], dateiwerkzeuge=["read_file"],
    )
    shared = text.split("The user has shared these working folders with you:\n\n")[1]
    assert shared.split("\n\n")[0] == "- /u/a\n- /d/dock"
    assert "The dock folder" not in text


# --- Where delivered files are seen, and where the manual is -----------------


def test_delivered_files_are_in_the_doc_folder_not_on_a_shelf():
    text = _flat(grundprompt.bauen(
        werkzeuge=True, agenten=True,
        kann=grundprompt.faehigkeiten({agentendock.WERKZEUG_NAME}),
        agentenlauf=_job(ablegen=True),
    ))
    assert "shelf" not in text
    assert "deliver files to the Doc folder" in text
    assert "appear in the Doc folder" in text
    assert "finds them in the Doc folder" in text


def test_the_manual_is_the_entry_called_help():
    assert "the entry called Help at the bottom of the settings" in _flat(grundprompt.bauen())


# --- The overview names what servers bring ------------------------------------


def test_the_overview_names_a_web_search_and_further_server_tools():
    both = grundprompt.faehigkeiten({"read_file", "web_search", "read_webpage"})
    assert grundprompt.ABILITY_WEB_SEARCH in both
    assert grundprompt.ABILITY_SERVER_TOOLS in both
    assert grundprompt.faehigkeiten({"web_search"})[-1] == grundprompt.ABILITY_WEB_SEARCH
    assert grundprompt.ABILITY_WEB_SEARCH not in grundprompt.faehigkeiten({"notion_query"})
    assert grundprompt.ABILITY_SERVER_TOOLS in grundprompt.faehigkeiten({"notion_query"})


def test_the_overview_of_the_programs_own_tools_names_no_server():
    """The silence probe: the file search is the program's, not a web search."""
    own = grundprompt.faehigkeiten({"read_file", "search_files", "run_command"})
    assert grundprompt.ABILITY_WEB_SEARCH not in own
    assert grundprompt.ABILITY_SERVER_TOOLS not in own


# --- A shipped skill needs its tool -------------------------------------------


def _shipped() -> dict[str, skills.Skill]:
    return skills.skills_laden(PROJEKT / "skills", PROJEKT / "skills-of-nobody")


def test_a_skill_that_needs_a_tool_is_listed_only_with_that_tool():
    names = [s.name for s in skills.automatische(_shipped(), ())]
    for needing in ("image-generator", "cronjob", "grill-me"):
        assert needing not in names
    # The silence probe: one that needs no tool stays.
    assert "handoff" in names

    offered = set(skills.needed_tools().values())
    with_tools = [s.name for s in skills.automatische(_shipped(), offered)]
    for needing in ("image-generator", "cronjob", "grill-me"):
        assert needing in with_tools


# --- The shell is this machine's ----------------------------------------------


def test_windows_is_named_with_its_processor_and_its_path():
    system, shell_name, python = grundprompt.shell_environment(
        "nt", environ={"COMSPEC": r"C:\Windows\System32\cmd.exe"}
    )
    assert (system, shell_name, python) == ("Windows", "cmd.exe", r".venv\Scripts\python.exe")


def test_a_mac_is_named_with_the_users_shell():
    assert grundprompt.shell_environment(
        "posix", "Darwin", {"SHELL": "/bin/zsh"}
    ) == ("macOS", "zsh", ".venv/bin/python3")
    assert grundprompt.shell_environment("posix", "Linux", {}) == (
        "Linux", "sh", ".venv/bin/python3"
    )


def test_the_shell_block_names_the_system_it_was_built_on(monkeypatch):
    monkeypatch.setattr(
        grundprompt, "shell_environment",
        lambda: ("Windows", "cmd.exe", r".venv\Scripts\python.exe"),
    )
    text = _flat(grundprompt.bauen(werkzeuge=True, befehle=True))
    assert "Commands run on Windows, in cmd.exe." in text
    assert r"`.venv\Scripts\python.exe -m pytest`" in text
    assert ".venv/bin/python3" not in text


def test_the_execution_lines_carry_no_posix_command():
    text = grundprompt.execution_discipline({"run_command"}, memory_travels=False)
    assert "sha256sum" not in text


# --- Smaller corrections -------------------------------------------------------


def test_the_execution_lines_speak_of_the_memory_and_ask_for_no_yes():
    text = grundprompt.execution_discipline(
        {"read_file", "list_dir", "run_command"}, memory_travels=True
    )
    assert "user profile" not in text
    assert "confirm scope" not in text
    # The folder listing reports sizes, so it is one of the lookups.
    assert "use read_file, list_dir, or run_command" in text


def test_a_schedule_told_to_finish_quietly_is_not_told_to_speak():
    text = _flat(grundprompt.bauen(agentenlauf=_job()))
    assert "unless your task tells you to finish quietly" in text


def test_the_notes_of_a_folder_are_not_called_the_users_alone():
    text = _flat(grundprompt.bauen(ordner=["/u/a"], ordnerwissen=[("/u/a", "x")]))
    assert "is theirs" not in text
    assert "Each shared folder can carry notes about itself" in text


# --- A job's picture ------------------------------------------------------------


def _draw(tmp_path, monkeypatch, **options) -> str:
    service = Bilddienst({})
    monkeypatch.setattr(bild_werkzeug.httpx, "AsyncClient", lambda timeout, headers: service)
    return asyncio.run(
        bild_werkzeug.ausfuehren(
            {"prompt": "a dog"}, "http://x", tmp_path, "testschluessel", **options
        )
    )


def test_a_job_is_told_where_its_picture_is_and_how_to_hand_it_on(tmp_path, monkeypatch):
    text = _draw(
        tmp_path, monkeypatch, job_id="j1", deliver_with=agentendock.WERKZEUG_NAME
    )
    assert "attached to this response" not in text
    assert f"saved as {tmp_path / 'out.png'}" in text
    assert (
        " If this image is a deliverable for the user, deliver it using "
        f"{agentendock.WERKZEUG_NAME} with this path."
    ) in text


def test_a_job_without_the_delivery_tool_is_not_sent_to_it(tmp_path, monkeypatch):
    text = _draw(tmp_path, monkeypatch, job_id="j1")
    assert f"saved as {tmp_path / 'out.png'}" in text
    assert agentendock.WERKZEUG_NAME not in text


def test_a_chat_still_gets_its_picture_on_the_answer(tmp_path, monkeypatch):
    """The silence probe: in a chat, with its answer named, the picture
    stands under the answer — and the model reads where its file lies, so
    it can name the picture to a later tool."""
    text = _draw(tmp_path, monkeypatch, chat_id="c1", antwort_id="a1")
    assert f"attached to this response, and saved as {tmp_path / 'out.png'}." in text
    assert "deliver it using" not in text


def test_the_job_description_does_not_promise_the_answer():
    family = None
    assert bild_werkzeug.IN_CHAT in bild_werkzeug.werkzeug_beschreibung(family).beschreibung
    job = bild_werkzeug.werkzeug_beschreibung(family, in_chat=False).beschreibung
    assert bild_werkzeug.IN_JOB in job
    assert "appears in your answer" not in job


def test_only_a_job_that_has_the_delivery_tool_is_sent_to_it(tmp_path):
    registry = WerkzeugRegistry([], agentendock=AgentenDock(tmp_path / "dock"))
    name = agentendock.WERKZEUG_NAME
    agent = Agent(name="painter", prompt="")
    assert registry._deliver_with("agent", agent) == name
    assert registry._deliver_with("chat", None) is None
    assert registry._deliver_with("agent", Agent(name="p", prompt="", werkzeuge=["x"])) is None
    registry.abgeschaltet = {name}
    assert registry._deliver_with("agent", agent) is None
    assert WerkzeugRegistry([])._deliver_with("agent", agent) is None


async def test_the_delivery_tool_takes_a_picture_from_the_pictures_folder(tmp_path):
    """What the drawing tool tells a job to do has to work: the picture lies
    in the pictures folder, which is among every run's folders."""
    pictures = tmp_path / "pictures"
    pictures.mkdir()
    (pictures / "out.png").write_bytes(b"\x89PNG")
    work = tmp_path / "work"
    work.mkdir()
    dock = AgentenDock(tmp_path / "dock")
    registry = WerkzeugRegistry(
        [], agentendock=dock, bild_zugang=("http://x", pictures, "key")
    )
    answer = await registry.ausfuehren(
        agentendock.WERKZEUG_NAME,
        {"name": "dog.png", "path": str(pictures / "out.png")},
        ordner=[str(work), str(pictures)], chat_id="j1", herkunft="agent",
        agent=Agent(name="painter", prompt=""),
    )
    assert "Delivered 'dog.png'" in answer
    (eintrag,) = dock.alle()
    assert dock.holen(eintrag["id"])[1].read_bytes() == b"\x89PNG"


async def test_a_picture_outside_the_run_folders_is_not_delivered(tmp_path):
    """Silence probe: the pictures folder needs no way of its own any more —
    a run whose folders leave it out cannot copy from it."""
    pictures = tmp_path / "pictures"
    pictures.mkdir()
    (pictures / "out.png").write_bytes(b"\x89PNG")
    work = tmp_path / "work"
    work.mkdir()
    dock = AgentenDock(tmp_path / "dock")
    registry = WerkzeugRegistry(
        [], agentendock=dock, bild_zugang=("http://x", pictures, "key")
    )
    with pytest.raises(WerkzeugVerboten, match="outside the shared folders"):
        await registry.ausfuehren(
            agentendock.WERKZEUG_NAME,
            {"name": "dog.png", "path": str(pictures / "out.png")},
            ordner=[str(work)], chat_id="j1", herkunft="agent",
            agent=Agent(name="painter", prompt=""),
        )
    assert dock.alle() == []
