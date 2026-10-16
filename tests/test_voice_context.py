"""Both ways of speaking run the voice with the same context length.

Without `-c`, `llama-tts` takes the model's own context (32768) and puts
3.5 GB of attention cache on the graphics card; on a Mac with 8 GB every
sentence then ends in "Insufficient Memory". The kept voice always named its
own context; now the command of `stimme.sprechen` names the same number,
read from one constant.
"""

from __future__ import annotations

import re
from pathlib import Path

from app import stimme, voice_worker

ROOT = Path(__file__).resolve().parent.parent


class _Run:
    returncode = 0
    stderr = ""


def _command(tmp_path, monkeypatch) -> list[str]:
    seen: dict = {}

    def fake(command, **kw):
        seen["command"] = command
        Path(command[command.index("-o") + 1]).write_bytes(b"RIFF")
        return _Run()

    monkeypatch.setattr(stimme, "_laufen", fake)
    stimme.sprechen(
        Path("/bin/llama-tts"), tmp_path / "m.gguf", tmp_path / "mm.gguf", "Hallo.",
        sprache="de", ordner=tmp_path,
    )
    return seen["command"]


def test_the_command_names_the_context_of_the_kept_voice(tmp_path, monkeypatch):
    command = _command(tmp_path, monkeypatch)
    assert "-c" in command
    assert command[command.index("-c") + 1] == "4096"


def test_both_ways_read_the_one_constant():
    assert stimme.VOICE_CONTEXT_SIZE is voice_worker.VOICE_CONTEXT_SIZE
    worker = (ROOT / "app" / "voice_worker.py").read_text(encoding="utf-8")
    assert len(re.findall(r"^VOICE_CONTEXT_SIZE = 4096$", worker, re.M)) == 1
    assert "CONTEXT_SIZE, " not in worker.replace("VOICE_CONTEXT_SIZE", "")
    assert "VOICE_CONTEXT_SIZE" in (ROOT / "app" / "stimme.py").read_text(encoding="utf-8")


def test_the_gpu_layers_are_named_only_when_a_count_is_given(tmp_path, monkeypatch):
    """The silence check: only the context is new on the command; with no
    layer count the flag is not there (the engine places the layers)."""
    command = _command(tmp_path, monkeypatch)
    assert "--n-gpu-layers" not in command
