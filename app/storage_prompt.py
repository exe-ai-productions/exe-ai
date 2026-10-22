"""The storage locations of Exe AI, as the system prompt names them.

A model that is not told where the program keeps its files guesses: it
copies a picture model into the default folder under the data folder while
the user moved that folder somewhere else, and the file lies where nothing
looks for it. So every run is told the section "Where files belong": the
tree of the program's folders with the rule of each, and the paths that are
in force now — the locations of ``app/speicherorte.py``, with the override of
the user applied.

Naming a folder opens none of them. What the model may touch stays the list
of folders of the run; a location the program's own protection closes to this
run (``grenzen.private_check``) is marked as closed, so the model tells the
user the path instead of trying to write there.

The text is English and ends up in the system message of every chat and
every job. It changes when the user moves a location, so the caller puts it
into the fingerprint that decides whether the message is built again.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from app import bildrunner, bildwahlen, checkpoint_hooks, dokumentablage, image_switches
from app import modellrunner, speicherorte
from app.tools import grenzen

if TYPE_CHECKING:
    from app.config import Config

FILES_BELONG_HEAD = (
    '# Where files belong\n'
    'Exe AI keeps its files in fixed folders. The paths below are the ones in\n'
    'force on this machine; a folder the user moved shows its new path. When the\n'
    'user asks where a file goes, show the part of this tree that matters as a\n'
    'code block, and give the one rule for that folder.'
)

# The tree. The paths in braces are the ones in force (``speicherorte``); the
# sub-folders of the image models are written from ``STORAGE_FOLDERS`` and the
# few folder names inside the prose from the constants of the code that reads
# them, so the prompt cannot name a folder the program does not look in.
FILES_BELONG_TREE = (
    '{settings_dir}                  program settings\n'
    '├── config.yaml, .env, berechtigungen.json, mcp_servers.json\n'
    '│                               settings, keys, permissions, MCP servers;\n'
    '│                               changed in the settings window, never by a tool\n'
    '├── prompts/\n'
    "│   ├── system.md               the user's instructions\n"
    '│   ├── memory.md               the memory (written with memory_save)\n'
    '│   ├── skills/<name>/SKILL.md  one folder per skill (lower case, digits, hyphens)\n'
    '│   └── agenten/<Name>.md      one Markdown file per agent\n'
    '├── llama.cpp/, voice-library/  program parts; never put files here\n'
    "└── {data_dir}                  the program's data (closed except where noted)\n"
    '    ├── models/                 → {models}\n'
    '    │     chat models: .gguf files lying flat; only files in here can start.\n'
    '    │     vision projectors go to {vision}/, speed modules to {mtp}/ — the\n'
    '    │     program sorts them there itself\n'
    '    ├── embedding_models/       → {embedding_models}\n'
    '    │     embedding models (.gguf) for document search\n'
    '    ├── speech_models/          → {speech_models}\n'
    '    │     speech recognition and voice models (.gguf) and voice samples\n'
    '    │     (.wav), all lying flat; projectors in {vision}/\n'
    '    ├── image_models/           → {image_models}\n'
    '    │     image and video models (.gguf, .safetensors, or a folder of shards)\n'
    '    │     lying flat, and these sub-folders:\n'
    '{image_models_folders}\n'
    '    ├── images/                 → {images}        every generated and attached picture {images_state}\n'
    '    ├── agent_dock/             → {agent_dock}    the Doc folder: files from deliver_file\n'
    '    ├── scripts/                → {scripts}       scripts a cron job may start {scripts_state}\n'
    "    ├── {chat_files}/<chat>/                         each chat's own folder and uploads\n"
    '    └── {sd_cpp}/, {checkpoints}/       program parts; never put files here'
)

FILES_BELONG_RULES = (
    'Rules: A VAE, text encoder or vision file lying loose in the image models\n'
    'folder is recognised by its content; every other companion must be in its\n'
    'sub-folder, or the program does not offer it. You may move a file into one\n'
    'of these folders only when that folder lies outside the data folder; inside\n'
    'it, tell the user where to put it, or send them to the catalog, which puts\n'
    'every download in the right place by itself.'
)

STORAGE_CLOSED_NOTE = (
    "Your tools cannot change a folder marked (closed): tell the user its path so they "
    "can put the file there themselves."
)

CLOSED_MARK = " (closed)"
OPEN_MARK = "(open)"

# Location name -> the subfolders of it that hold a kind of file of their own,
# each with what lies in it, in the order the tree lists them. The names of
# the subfolders are the constants of the code that reads them.
STORAGE_FOLDERS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    ("images", ()),
    (
        "image_models",
        (
            (bildrunner.TEXTVERSTEHER_ORDNER, "T5, CLIP or language-model encoders, tokenizer .json, vision parts"),
            (bildrunner.VAE_ORDNER, "standalone VAE files"),
            (bildwahlen.LORA_ORDNER, "LoRA files (.safetensors, .gguf, .ckpt, .pt)"),
            (bildwahlen.EMBEDDING_ORDNER, "textual-inversion embeddings, called by file name in the prompt"),
            (bildrunner.UPSCALER_ORDNER, "ESRGAN-type upscalers for Hires fix and enlarging"),
            (bildrunner.YOLO_ORDNER, "detector models for ADetailer"),
            (bildrunner.PULID_ORDNER, "PuLID weights and face embeddings (.pulidembd)"),
            (bildrunner.CONTROLNET_ORDNER, "ControlNet models"),
            (bildrunner.TAESD_FOLDER, "tiny autoencoders for the live preview"),
            (bildwahlen.PHOTOMAKER_ORDNER, "the PhotoMaker model"),
            (bildwahlen.GESICHTER_ORDNER, "the user's photos of one face, for PhotoMaker"),
            (image_switches.IP_ADAPTER_FOLDER, "IP-Adapter models"),
            (image_switches.MOTION_FOLDER, "AnimateDiff motion modules"),
            (image_switches.AUDIO_FOLDER, "sound files for videos"),
        ),
    ),
    ("models", ()),
    ("embedding_models", ()),
    ("speech_models", ()),
    ("scripts", ()),
    ("agent_dock", ()),
)

# The width of the column the sub-folder names stand in, as in the tree.
_NAME_WIDTH = 20


def _subfolder_lines(subfolders: tuple[tuple[str, str], ...]) -> str:
    """The sub-folder lines of the image models, drawn as the tree draws them."""
    lines = []
    for number, (folder, what) in enumerate(subfolders):
        branch = "└" if number == len(subfolders) - 1 else "├"
        lines.append(f"    │   {branch}── {(folder + '/').ljust(_NAME_WIDTH)}{what}")
    return "\n".join(lines)


def block(config: "Config", folders: Sequence[str]) -> str:
    """The section naming the storage locations in force, for a run whose
    folders are ``folders``. Paths are written with forward slashes, the way
    the model is told to write them on Windows."""
    private = grenzen.private_check(list(folders), config.datenverzeichnis)
    in_force = {row["name"]: Path(row["pfad"]) for row in speicherorte.uebersicht(config)}
    values = {
        "settings_dir": config.pfad(config.app.berechtigungen_datei).parent.as_posix(),
        "data_dir": config.datenverzeichnis.as_posix(),
        "vision": modellrunner.VISION_ORDNER,
        "mtp": modellrunner.MTP_ORDNER,
        "chat_files": dokumentablage.CHATDATEIEN,
        "sd_cpp": bildrunner.ORDNER,
        "checkpoints": checkpoint_hooks.FOLDER_NAME,
    }
    any_closed = False
    for name, subfolders in STORAGE_FOLDERS:
        folder = in_force[name]
        closed = private is not None and private(folder)
        any_closed = any_closed or closed
        values[name] = f"{folder.as_posix()}{CLOSED_MARK if closed else ''}"
        # The two folders the tree calls open say so where the run really
        # can write there, and nothing where it cannot.
        values[f"{name}_state"] = "" if closed else OPEN_MARK
        values[f"{name}_folders"] = _subfolder_lines(subfolders)
    tree = FILES_BELONG_TREE.format(**values)
    parts = [FILES_BELONG_HEAD, "", tree, ""]
    if any_closed:
        parts += [STORAGE_CLOSED_NOTE, ""]
    parts.append(FILES_BELONG_RULES)
    return "\n".join(line.rstrip() for line in "\n".join(parts).split("\n"))
