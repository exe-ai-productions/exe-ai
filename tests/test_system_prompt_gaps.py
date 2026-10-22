"""The sentences the system prompt says word for word about failures, the
settings window, setting up an agent and a script, the pictures and the Doc
folder — each one where its subject is in the run, and nowhere else."""

from __future__ import annotations

import json
from pathlib import Path

from app import agenten, gedaechtnis, grundprompt

ROOT = Path(__file__).resolve().parent.parent

LOCAL = "qwen3-8b"
CLAUDE = "claude-sonnet-5-5"

FAILS = (
    "If a tool, install or network call fails and blocks the real path, report the actual error first. Try a "
    "genuinely different approach only when it stays within what the user asked for; never retry the same call "
    "with small variations, and never fabricate output."
)
FINISHING = "Finishing means finishing what was asked — not adding files, code or steps nobody asked for."
HANDOFF = (
    "Handing work to a job with start_job counts as acting; after it, tell the user what was handed off and end "
    "your turn."
)
SEARCH = (
    "- If a search or lookup returns empty, partial, or suspiciously narrow results, retry with a broader or "
    "different query or strategy before concluding."
)
MEMORY = (
    "Your memory describes the user, not the machine you are running on; check the live system before you rely "
    "on it."
)
SETTINGS = (
    "The settings window has five groups: Interface (Appearance, Language, Notifications, Shortcuts), Behavior "
    "(Instructions, Memory, Skills, Cron jobs, Agents), Models (Local models, Cloud providers, Catalog, "
    "Downloads), Servers and connections (Overview, the six servers, MCP Servers, Tools, Web App) and System "
    "(Credentials, Configuration, Tools file, Help, Updates). When you send the user somewhere, name the group "
    "and the page."
)
AGENT = (
    "You can set up an agent for the user. An agent is one Markdown file in /data/agents, named after the "
    "agent, with a front matter (description, tools, folders, max_rounds, max_minutes, max_tokens, "
    "reasoning_budget, reasoning_effort, max_command_seconds) and its instructions below it. Write it with "
    "write_file; the user confirms the write. Then ask the user to check that it appears under Settings → "
    "Behavior → Agents."
)
SCRIPT = (
    "A schedule can only start a script that lies in the scripts folder (/data/scripts). Write the script "
    "there, make it executable with chmod +x, and then create the schedule with cronjob and script."
)
KEY = (
    "If an MCP server needs a key or a sign-in, guide the user step by step: Settings → Servers and connections "
    "→ MCP Servers → choose the service's tile, or Custom server → enter its URL (type http) or its start "
    "command (type stdio) → choose an API key or Sign in through the browser → Apply. Before you name an "
    "address, look up the service's official MCP address with the web search and read the source page. Never "
    "ask the user to paste a key into the chat."
)
PICTURES = (
    "draw_image and draw_video always use the default model chosen on the image server page (Servers and "
    "connections → Image server). You cannot choose another model, a LoRA, a mask, several reference images, "
    "upscaling or face tools, and for video not even size or length. When the user wants any of these, do what "
    "the tool allows and send them to the Images studio for the rest; never imitate the studio with shell "
    "commands."
)


def _local(**extra) -> str:
    return grundprompt.bauen(werkzeuge=True, model_name=LOCAL, **extra)


# --- Failures, hand-off, scope (A) --------------------------------------------


def test_a_failed_call_is_reported_first_and_never_retried_in_small_variations():
    for model in (LOCAL, CLAUDE):
        text = grundprompt.bauen(werkzeuge=True, model_name=model)
        assert FAILS in text
        assert FINISHING in text
    # The old advice to try an alternative or ask is gone.
    assert "try an alternative" not in _local()
    assert text.count(FAILS) == 1


def test_only_a_search_or_a_lookup_is_retried_broader():
    text = _local(tool_names={"search_files"})
    assert SEARCH in text
    assert "If a tool returns empty" not in text


def test_handing_work_to_a_job_counts_as_acting_where_start_job_is_offered():
    with_job = _local(tool_names={"start_job", "run_command"})
    assert HANDOFF in with_job
    # It ends the block about acting, which is the one a local model reads.
    assert with_job.index("Responses that only describe intentions") < with_job.index(HANDOFF)
    # Silence probe: without the tool no sentence; Claude reads no such block.
    assert HANDOFF not in _local(tool_names={"run_command"})
    assert HANDOFF not in grundprompt.bauen(werkzeuge=True, model_name=CLAUDE, tool_names={"start_job"})


# --- The memory (B) ---------------------------------------------------------------


def test_the_memory_describes_the_user_once_for_every_model_that_has_it():
    for model in (LOCAL, CLAUDE):
        prompt = grundprompt.bauen(
            werkzeuge=True, model_name=model, tool_names={"run_command"}, memory_travels=True
        )
        # Not a sentence of the shipped prompt, and not of the execution lines.
        assert MEMORY not in prompt
        assert "Your memory describes the USER" not in prompt
        assert gedaechtnis.anhaengen(prompt, "## Facts\n- Works on a Mac.").count(MEMORY) == 1
    # Silence probe: no memory, no sentence.
    assert MEMORY not in gedaechtnis.anhaengen(prompt, "")


# --- The settings window (C) ----------------------------------------------------------


def test_every_model_knows_the_five_groups_with_and_without_the_help_skill():
    for text in (
        grundprompt.bauen(),
        grundprompt.bauen(skills=[("help", "the manual")]),
        grundprompt.bauen(werkzeuge=True, model_name=CLAUDE),
    ):
        assert text.count(SETTINGS) == 1
    # Directly after the sentences about the manual.
    plain = grundprompt.bauen()
    assert plain.index(grundprompt.MANUAL_SEND_USER) + len(grundprompt.MANUAL_SEND_USER) + 1 == plain.index(SETTINGS)
    with_help = grundprompt.bauen(skills=[("help", "the manual")])
    assert grundprompt.MANUAL_SEND_USER not in with_help
    assert with_help.index("answer from it") < with_help.index(SETTINGS)


# --- Setting up an agent, a script, a key (D) ---------------------------------------------


def test_the_model_is_told_how_to_set_up_an_agent_where_it_can_write_the_file():
    text = _local(dateiwerkzeuge=["read_file", "write_file"], agents_dir="/data/agents")
    assert AGENT in text
    # Every field it names is one the loader knows.
    named = AGENT.split("front matter (")[1].split(")")[0].split(", ")
    assert named and set(named) <= agenten.BEKANNTE_FELDER
    # Silence probe: a run that cannot write a file is not told to.
    assert AGENT not in _local(dateiwerkzeuge=["read_file"], agents_dir="/data/agents")
    assert "set up an agent" not in _local(dateiwerkzeuge=["write_file"])


def test_the_model_is_told_where_a_script_for_a_schedule_belongs_where_it_can_make_one():
    text = _local(tool_names={"cronjob"}, scripts_dir="/data/scripts")
    assert SCRIPT in text
    # Silence probe: without the tool that makes a schedule, nothing.
    assert "scripts folder" not in _local(tool_names={"run_command"}, scripts_dir="/data/scripts")


def test_a_key_or_a_sign_in_is_walked_through_step_by_step_instead_of_a_half_sentence():
    text = _local(command_line="/opt/exe-ai/bin/exe")
    assert KEY in text
    assert text.count(KEY) == 1
    assert "then tell the user to finish it under Settings" not in text
    # Silence probe: no client, no paragraph about it.
    assert KEY not in _local()


# --- Pictures (E) ----------------------------------------------------------------------------


def test_the_limits_of_the_two_drawing_tools_are_said_where_either_is_offered():
    for names in ({"draw_image"}, {"draw_video"}, {"draw_image", "draw_video"}):
        assert PICTURES in _local(tool_names=names)
    # Silence probe: with neither tool the sentence is not there.
    assert PICTURES not in _local(tool_names={"run_command"})
    assert PICTURES not in grundprompt.bauen()


# --- The Doc folder (F) ----------------------------------------------------------------------------


def test_the_prompt_names_the_folder_of_delivered_files_the_doc_folder():
    text = grundprompt.bauen(
        werkzeuge=True,
        ordner=["/u/a", "/data/agent_dock"],
        dock="/data/agent_dock",
        dateiwerkzeuge=["read_file"],
    )
    assert "The Doc folder holds finished files delivered to the user" in text
    assert "dock folder" not in text.lower()


def test_the_interface_names_it_the_same_in_both_languages_and_minimize_stays_the_dock():
    expected = {
        "en": {
            "ablage_gescheitert": "delivery to the Doc folder failed",
            "ordner_titel": "Folder - delivered to the Doc folder",
            "ablage_weg_frage": "Remove “{name}” from the Doc folder?",
            "quelle_dock": "Doc folder",
        },
        "de": {
            "ablage_gescheitert": "Ablegen im Doc-Ordner fehlgeschlagen",
            "ordner_titel": "Ordner - Ablage im Doc-Ordner",
            "ablage_weg_frage": "„{name}“ aus dem Doc-Ordner entfernen?",
            "quelle_dock": "Doc-Ordner",
        },
    }
    for language, texts in expected.items():
        catalogue = json.loads((ROOT / "app" / "locales" / f"{language}.json").read_text(encoding="utf-8"))
        found = _find(catalogue, texts)
        assert found == texts, (language, found)
    german = json.loads((ROOT / "app" / "locales" / "de.json").read_text(encoding="utf-8"))
    # Silence probe: the menu entry that puts a window away keeps its macOS word.
    assert _find(german, {"minimize": ""})["minimize"] == "Im Dock ablegen"


def _find(node, wanted: dict[str, str]) -> dict[str, str]:
    """The values of the wanted keys, wherever in the catalogue they stand."""
    found: dict[str, str] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            if key in wanted and isinstance(value, str):
                found[key] = value
            else:
                found.update(_find(value, wanted))
    return found
