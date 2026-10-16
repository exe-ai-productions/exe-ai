"""The voice process (app/voice_worker.py), as far as it can run without an
engine: the sample it reads, the refusal of a build it does not know, and
the protocol on its pipes. The engine itself is proven live."""

from __future__ import annotations

import json
import struct
import subprocess
import sys
import wave
from pathlib import Path

import pytest

from app import voice_worker
from app.voice_worker import WorkerError, Voice, read_speaker

ROOT = Path(__file__).resolve().parent.parent


def _wave(path: Path, samples: list[int], *, rate: int, channels: int = 1, width: int = 2) -> Path:
    with wave.open(str(path), "wb") as target:
        target.setnchannels(channels)
        target.setsampwidth(width)
        target.setframerate(rate)
        if width == 2:
            target.writeframes(struct.pack(f"<{len(samples)}h", *samples))
        else:
            target.writeframes(bytes(samples))
    return path


def test_a_sample_at_another_rate_is_brought_to_the_models_rate(tmp_path):
    source = _wave(tmp_path / "s.wav", [0, 16384, 32767, 16384, 0, -16384] * 100, rate=8000)
    floats = read_speaker(str(source), 24000)
    assert len(floats) == 1800
    assert max(floats) == pytest.approx(0.99997, abs=1e-3)
    assert min(floats) < -0.4


def test_a_sample_at_the_models_rate_is_not_touched(tmp_path):
    source = _wave(tmp_path / "s.wav", [1000, -1000, 2000], rate=24000)
    floats = read_speaker(str(source), 24000)
    assert floats == pytest.approx([1000 / 32768, -1000 / 32768, 2000 / 32768])


def test_two_channels_are_mixed_to_one(tmp_path):
    source = _wave(tmp_path / "s.wav", [1000, 3000, -2000, 2000], rate=24000, channels=2)
    assert read_speaker(str(source), 24000) == pytest.approx([2000 / 32768, 0.0])


def test_a_sample_that_is_not_sixteen_bit_is_refused_so_llama_tts_speaks(tmp_path):
    source = _wave(tmp_path / "s.wav", [128, 130, 120], rate=24000, width=1)
    with pytest.raises(WorkerError, match="speaker_format"):
        read_speaker(str(source), 24000)


def test_a_sample_without_sound_is_refused(tmp_path):
    source = _wave(tmp_path / "s.wav", [], rate=24000)
    with pytest.raises(WorkerError, match="speaker_empty"):
        read_speaker(str(source), 24000)


class _Block:
    def __init__(self, raw: bytes) -> None:
        self.raw = raw


def _context_defaults(**changes: int) -> _Block:
    raw = bytearray(160)
    struct.pack_into("<4i", raw, 0, 512, 2048, 512, 1)
    raw[0x80:0x86] = bytes([0, 1, 1, 1, 1, 0])
    for offset, value in changes.items():
        struct.pack_into("<i", raw, int(offset[1:]), value)
    return _Block(bytes(raw))


def test_a_build_whose_blocks_look_like_the_known_one_is_accepted():
    model = _Block(struct.pack("<i", -1).rjust(0x14, b"\0").ljust(80, b"\0"))
    Voice()._check_layout(_context_defaults(), model)  # noqa: SLF001 - the point of the test


def test_a_build_whose_blocks_look_different_is_refused_before_anything_is_written():
    model = _Block(bytes(80))
    # A batch size the known build does not have as its default…
    with pytest.raises(WorkerError, match="layout_unknown"):
        Voice()._check_layout(_context_defaults(o4=4096), model)  # noqa: SLF001
    # …or a flag block that is not the known sequence.
    other = bytearray(_context_defaults().raw)
    other[0x80:0x86] = bytes([1, 1, 1, 1, 1, 1])
    with pytest.raises(WorkerError, match="layout_unknown"):
        Voice()._check_layout(_Block(bytes(other)), model)  # noqa: SLF001


def _process() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, str(ROOT / "start.py"), "--voice"], cwd=ROOT,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )


def _ask(process: subprocess.Popen, request: dict) -> dict:
    assert process.stdin and process.stdout
    process.stdin.write(json.dumps(request) + "\n")
    process.stdin.flush()
    return json.loads(process.stdout.readline())


def test_the_process_answers_on_its_pipes_and_ends_when_told():
    process = _process()
    try:
        assert _ask(process, {"op": "speak", "text": "x", "out": "/tmp/never.wav"}) == {
            "ok": False, "error": "not_loaded",
        }
        assert _ask(process, {"op": "dance"}) == {"ok": False, "error": "unknown_operation"}
        refused = _ask(process, {"op": "load", "library_dir": "/nonexistent", "model": "m",
                                  "mmproj": "p", "speaker": None})
        # The refusal names the folder it could not use; how the system words
        # a missing folder is its own business.
        assert refused["ok"] is False and "nonexistent" in refused["error"]
        assert process.stdin
        process.stdin.write(json.dumps({"op": "quit"}) + "\n")
        process.stdin.flush()
        assert process.wait(timeout=10) == 0
    finally:
        if process.poll() is None:
            process.kill()


def test_a_process_whose_input_closes_ends_itself():
    """The service ending closes the pipe: the voice is gone with it."""
    process = _process()
    assert process.stdin
    process.stdin.close()
    assert process.wait(timeout=10) == 0


def test_the_library_names_are_those_of_the_platform(monkeypatch):
    for platform, names in (
        ("win32", ("llama.dll", "mtmd.dll")),
        ("darwin", ("libllama.dylib", "libmtmd.dylib")),
        ("linux", ("libllama.so", "libmtmd.so")),
    ):
        monkeypatch.setattr(voice_worker.sys, "platform", platform)
        assert voice_worker.library_names() == names
