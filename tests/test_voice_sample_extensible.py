"""A voice sample in a WAVE_FORMAT_EXTENSIBLE header is read like a plain one.

macOS's `afconvert` writes the tag 65534 with PCM inside. Python 3.11's
`wave` refuses it ("unknown format: 65534") and the kept voice then never
loaded; every piece fell back to `llama-tts`. The worker now reads the two
chunks itself for that one tag.
"""

from __future__ import annotations

import struct
import wave

import pytest

from app.voice_worker import WorkerError, read_speaker

SAMPLES = [0, 12000, -12000, 32767, -32768, 500] * 20


def _plain(path, samples, rate=24000):
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(rate)
        target.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return path


def _extensible(path, samples, rate=24000, *, subtag=1, channels=1, bits=16):
    """The way macOS writes it: tag 65534, a 22-byte extension and the
    sub-format GUID whose first two bytes are the classic tag."""
    audio = struct.pack(f"<{len(samples)}h", *samples)
    guid = struct.pack("<H", subtag) + bytes.fromhex("000000001000800000aa00389b71")
    fmt = struct.pack("<HHIIHH", 0xFFFE, channels, rate, rate * channels * bits // 8, channels * bits // 8, bits)
    fmt += struct.pack("<HHI", 22, bits, 0) + guid
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(audio)) + audio
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return path


def test_the_standard_library_really_refuses_the_header(tmp_path):
    """The premise: without the fix this is what stopped the kept voice."""
    source = _extensible(tmp_path / "e.wav", SAMPLES)
    with pytest.raises(wave.Error, match="unknown format: 65534"):
        wave.open(str(source), "rb")


def test_an_extensible_pcm_sample_gives_the_samples_of_its_plain_twin(tmp_path):
    plain = read_speaker(str(_plain(tmp_path / "p.wav", SAMPLES)), 24000)
    extensible = read_speaker(str(_extensible(tmp_path / "e.wav", SAMPLES)), 24000)
    assert extensible == plain
    assert len(extensible) == len(SAMPLES)


def test_an_extensible_sample_at_another_rate_is_brought_to_the_models_rate(tmp_path):
    source = _extensible(tmp_path / "e.wav", SAMPLES * 10, rate=8000)
    assert len(read_speaker(str(source), 24000)) == len(SAMPLES) * 10 * 3


def test_an_extensible_sample_that_is_not_pcm_inside_is_refused(tmp_path):
    source = _extensible(tmp_path / "e.wav", SAMPLES, subtag=3)  # IEEE float
    with pytest.raises(WorkerError, match="speaker_format"):
        read_speaker(str(source), 24000)


def test_something_that_is_no_wav_is_refused_as_before(tmp_path):
    source = tmp_path / "x.wav"
    source.write_bytes(b"not a wav at all")
    with pytest.raises(WorkerError, match="speaker_format"):
        read_speaker(str(source), 24000)


def test_a_classic_pcm_sample_is_read_unchanged(tmp_path):
    """The silence check: the plain path is the one it always was."""
    floats = read_speaker(str(_plain(tmp_path / "p.wav", [1000, -1000, 2000])), 24000)
    assert floats == pytest.approx([1000 / 32768, -1000 / 32768, 2000 / 32768])
