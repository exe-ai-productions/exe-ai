"""The storage locations in the system message of every run.

A model that is not told where Exe AI keeps its files guesses the default
folder; with a location moved, the file then lies where nothing looks for it.
The section "Where files belong" draws the tree of the program's folders with
the rule of each, names the folders in force now, marks the ones this run's
tools cannot reach as closed, and rebuilds when the user moves one.
"""

from __future__ import annotations

import re

from app import (
    bildrunner,
    bildwahlen,
    checkpoint_hooks,
    dokumentablage,
    grundprompt,
    image_switches,
    modellrunner,
    speicherorte,
    storage_prompt,
)
from app.tools import grenzen
from app.providers import MockProvider, mock_endpunkt
from tests.conftest import lokaler_endpunkt
from tests.test_system_message import ENDPOINT, _ask
from tests.test_systemprompt_stand_job import _request


def _line(text: str, folder: str) -> str:
    """What the tree says after the arrow of one location: its path, with the
    mark of a closed folder, and the description that follows it."""
    (found,) = [line for line in text.splitlines() if line.startswith(f"    ├── {folder}/")]
    return found.split("→ ", 1)[1]


def _subfolders(text: str) -> list[str]:
    """The names of the sub-folders the tree draws under the image models."""
    return re.findall(r"^    │   [├└]── (\S+)/ ", text, flags=re.M)


def _defaults_in_data_folder(config) -> None:
    """The test configuration keeps the model folders beside the data folder;
    the installed program keeps them in it, which is where they are closed."""
    data = config.datenverzeichnis
    config.app.modelle_verzeichnis = str(data / "models")
    config.app.bildmodelle_verzeichnis = str(data / "image_models")
    config.app.einbettungsmodelle_verzeichnis = str(data / "embedding_models")
    config.app.sprachmodelle_verzeichnis = str(data / "speech_models")


def _run_folders(config) -> list[str]:
    dock, images = dokumentablage.program_folders(config)
    return [dock, images]


def test_every_location_of_the_program_has_its_place_in_the_tree():
    """A location added to the program without a line here would be the one
    folder a model still has to guess."""
    assert {name for name, _sub in storage_prompt.STORAGE_FOLDERS} == {
        place.name for place in speicherorte.ORTE
    }
    for name, _sub in storage_prompt.STORAGE_FOLDERS:
        assert "{" + name + "}" in storage_prompt.FILES_BELONG_TREE, name


def test_a_moved_folder_stands_with_its_new_path_and_the_default_ones_are_closed(
    config, tmp_path
):
    _defaults_in_data_folder(config)
    moved = tmp_path / "elsewhere" / "models"
    speicherorte.setzen(config, "image_models", moved)
    text = storage_prompt.block(config, _run_folders(config))

    assert _line(text, "image_models") == moved.resolve().as_posix()
    assert "lora/" in text and "text_encoders/" in text
    # The default folders below the data folder are private to the tools of
    # a run, except the ones the run was given and the scripts.
    assert _line(text, "speech_models").endswith(" (closed)")
    assert _line(text, "models").endswith(" (closed)")
    assert "(closed)" not in _line(text, "scripts")
    assert "(closed)" not in _line(text, "images")
    assert "(closed)" not in _line(text, "agent_dock")
    assert storage_prompt.STORAGE_CLOSED_NOTE in text


def test_the_note_about_closed_folders_stands_only_with_one(config, tmp_path):
    for name in ("models", "embedding_models", "speech_models", "image_models"):
        speicherorte.setzen(config, name, tmp_path / "out" / name)
    text = storage_prompt.block(config, _run_folders(config))
    assert "(closed)" not in text
    assert storage_prompt.STORAGE_CLOSED_NOTE not in text


def test_the_paragraph_is_in_a_prompt_built_with_no_tools_at_all(config):
    block = storage_prompt.block(config, _run_folders(config))
    assert block in grundprompt.bauen(storage=block)
    assert "Where files belong" not in grundprompt.bauen()


def test_a_chat_reads_the_folder_the_user_moved_at_its_next_message(
    client, chat_id, tmp_path
):
    config = client.app.state.config
    _defaults_in_data_folder(config)
    provider = lokaler_endpunkt(
        client, MockProvider(mock_endpunkt(ENDPOINT), haeppchen=["ok"])
    )
    default = speicherorte.standard(config, "image_models").as_posix()
    first = _ask(client, chat_id, provider)
    assert f"→ {default} (closed)" in first

    moved = tmp_path / "scratch" / "image-models"
    speicherorte.setzen(config, "image_models", moved)
    second = _ask(client, chat_id, provider)
    assert f"→ {moved.resolve().as_posix()}\n" in second
    assert default not in second


async def test_a_job_reads_the_same_paragraph(client, config, tmp_path):
    moved = tmp_path / "scratch" / "image-models"
    speicherorte.setzen(config, "image_models", moved)
    request, _folder = await _request(client, config, tmp_path)
    text = request.nachrichten[0].content
    assert f"→ {moved.resolve().as_posix()}\n" in text
    assert "│   ├── vae/                standalone VAE files" in text


def test_the_folder_of_the_chat_is_named_after_the_paragraph(client, chat_id):
    """The line with the chat's own folder stays the last of the message."""
    provider = lokaler_endpunkt(
        client, MockProvider(mock_endpunkt(ENDPOINT), haeppchen=["ok"])
    )
    text = _ask(client, chat_id, provider)
    assert text.index("# Where files belong") < text.rindex("Relative paths resolve against")
    assert text.rstrip().endswith("Relative paths resolve against this folder.")


# --- the tree "Where files belong" ---------------------------------------------

RULES = """Rules: A VAE, text encoder or vision file lying loose in the image models
folder is recognised by its content; every other companion must be in its
sub-folder, or the program does not offer it. You may move a file into one
of these folders only when that folder lies outside the data folder; inside
it, tell the user where to put it, or send them to the catalog, which puts
every download in the right place by itself."""


def test_the_tree_shows_the_moved_folders_and_the_first_line_carries_no_mark(config, tmp_path):
    _defaults_in_data_folder(config)
    moved = tmp_path / "elsewhere" / "image-models"
    speicherorte.setzen(config, "image_models", moved)
    text = storage_prompt.block(config, _run_folders(config))

    assert text.startswith("# Where files belong\nExe AI keeps its files in fixed folders.")
    # The program's own settings folder opens the tree, with no word about
    # what the tools can reach there; the data folder stands under it.
    settings = config.pfad(config.app.berechtigungen_datei).parent.as_posix()
    (first,) = [line for line in text.splitlines() if line.startswith(settings)]
    assert first == f"{settings}                  program settings"
    assert "closed to your tools" not in text
    assert f"└── {config.datenverzeichnis.as_posix()}                  the program's data" in text
    assert f"    ├── image_models/           → {moved.resolve().as_posix()}\n" in text
    assert text.endswith(RULES)


def test_every_subfolder_of_the_tree_is_a_constant_of_the_code(config):
    text = storage_prompt.block(config, _run_folders(config))
    assert sorted(_subfolders(text)) == sorted([
        bildrunner.TEXTVERSTEHER_ORDNER, bildrunner.VAE_ORDNER, bildwahlen.LORA_ORDNER,
        bildwahlen.EMBEDDING_ORDNER, bildrunner.UPSCALER_ORDNER, bildrunner.YOLO_ORDNER,
        bildrunner.PULID_ORDNER, bildrunner.CONTROLNET_ORDNER, bildrunner.TAESD_FOLDER,
        bildwahlen.PHOTOMAKER_ORDNER, bildwahlen.GESICHTER_ORDNER,
        image_switches.IP_ADAPTER_FOLDER, image_switches.MOTION_FOLDER, image_switches.AUDIO_FOLDER,
    ])
    # The three of the videos and the IP-Adapter stand in the tree with the text they had.
    assert "│   ├── ipadapter/          IP-Adapter models" in text
    assert "│   ├── animatediff/        AnimateDiff motion modules" in text
    assert "│   └── audio/              sound files for videos" in text
    # The folders named inside the prose and below the data folder too.
    assert f"projectors go to {modellrunner.VISION_ORDNER}/, speed modules to {modellrunner.MTP_ORDNER}/" in text
    assert f"├── {dokumentablage.CHATDATEIEN}/<chat>/" in text
    assert f"└── {bildrunner.ORDNER}/, {checkpoint_hooks.FOLDER_NAME}/" in text


def test_the_prompts_folder_in_the_tree_is_the_one_the_program_reads(config):
    """The names of the settings folder are literal in the tree; they follow
    the defaults of the configuration."""
    text = storage_prompt.block(config, _run_folders(config))
    shipped = type(config.app).model_fields
    assert shipped["system_prompt_file"].default == "./prompts/system.md"
    assert shipped["memory_file"].default == "./prompts/memory.md"
    assert shipped["skills_verzeichnis"].default == "./prompts/skills"
    assert shipped["agenten_verzeichnis"].default == "./prompts/agenten"
    for line in ("├── prompts/", "│   ├── system.md", "│   ├── memory.md",
                 "│   ├── skills/<name>/SKILL.md", "│   └── agenten/<Name>.md"):
        assert line in text, line
    names = [name for name in grenzen.PRIVATE_FILES if not name.endswith(".sicherung")]
    assert f"├── {', '.join(names)}\n" in text


def test_a_folder_that_is_open_for_the_run_says_open_and_never_closed(config, tmp_path):
    _defaults_in_data_folder(config)
    text = storage_prompt.block(config, _run_folders(config))
    for folder in ("images", "scripts", "agent_dock"):
        assert "(closed)" not in _line(text, folder), folder
    assert _line(text, "images").endswith("every generated and attached picture (open)")
    assert _line(text, "scripts").endswith("scripts a cron job may start (open)")
    # The same run without the picture folder: the folder is closed to it, and
    # the line says so once — the mark of the tree, not an "(open)" beside it.
    dock, _images = dokumentablage.program_folders(config)
    closed = storage_prompt.block(config, [dock])
    images = _line(closed, "images")
    assert "(closed)" in images and "(open)" not in images
    assert _line(closed, "scripts").endswith("(open)")


def test_the_section_is_the_same_for_a_chat_and_a_job_built_from_the_same_config(config):
    folders = _run_folders(config)
    assert storage_prompt.block(config, folders) == storage_prompt.block(config, list(folders))
