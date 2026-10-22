"""A BF16 model file written again with its BF16 weights as FP16: the bytes of
the copy, the way the service offers it, and the way it ends — whole, stopped
or failed (app/fp16_convert.py, app/api/v1/image_tools.py)."""

from __future__ import annotations

import json
import struct
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import fp16_convert
from app.bildrunner import Bildrunner
from app.config import Config

URL = "/api/v1/bild/convert-fp16"
METADATA = {"format": "pt", "note": "kept"}
# Out of FP16's range on both sides: set to its largest value of the sign.
BIG = [1.0, 70144.0, -1.0e5, 1.0e-8]


def _bf16(values: list[float]) -> bytes:
    """The BF16 of each value: the upper half of its float32."""
    return b"".join(struct.pack("<f", value)[2:] for value in values)


def _widened(raw: bytes) -> list[float]:
    return [struct.unpack("<f", b"\0\0" + raw[at:at + 2])[0] for at in range(0, len(raw), 2)]


def _write(path: Path, tensors: list[tuple[str, str, list[int], bytes]], metadata=METADATA) -> None:
    """A safetensors file: the header names each tensor's dtype, shape and
    place, the data follows in the order given."""
    header: dict = {} if metadata is None else {"__metadata__": metadata}
    position = 0
    for name, dtype, shape, data in tensors:
        header[name] = {"dtype": dtype, "shape": shape, "data_offsets": [position, position + len(data)]}
        position += len(data)
    head = json.dumps(header).encode()
    head += b" " * (-len(head) % 8)
    path.write_bytes(struct.pack("<Q", len(head)) + head + b"".join(data for *_, data in tensors))


def _read(path: Path) -> tuple[dict, bytes]:
    raw = path.read_bytes()
    length = struct.unpack("<Q", raw[:8])[0]
    return json.loads(raw[8:8 + length]), raw[8 + length:]


def _sample(folder: Path, name: str = "m.safetensors", values: list[float] | None = None) -> Path:
    """A file of two BF16 tensors and one F32 tensor, mostly BF16."""
    path = folder / name
    _write(path, [
        ("a", "BF16", [4], _bf16(values or BIG)),
        ("b", "BF16", [2, 2], _bf16([0.5, -2.0, 3.0, 0.0])),
        ("c", "F32", [3], struct.pack("<3f", 1.5, -2.5, 1.0e30)),
    ])
    return path


@pytest.fixture
def folder(config: Config, tmp_path: Path) -> Path:
    place = tmp_path / "bildmodelle"
    place.mkdir()
    config.app.bildmodelle_verzeichnis = str(place)
    return place


def test_the_bytes_of_the_copy(tmp_path: Path):
    source = _sample(tmp_path)
    before = source.read_bytes()
    runner = Bildrunner(tmp_path)
    runner.reservieren(stoppable=True)
    out, capped = fp16_convert.convert(runner, source)
    runner.freigeben()

    assert out == tmp_path / "m.fp16.safetensors"
    assert capped == 2
    assert source.read_bytes() == before
    assert not list(tmp_path.glob(".*.tmp"))
    old_header, old_data = _read(source)
    header, data = _read(out)
    # The metadata, the shapes and the places stay; only the dtype of BF16 changes.
    assert header["__metadata__"] == METADATA
    for name in ("a", "b", "c"):
        assert header[name]["shape"] == old_header[name]["shape"]
        assert header[name]["data_offsets"] == old_header[name]["data_offsets"]
    assert (header["a"]["dtype"], header["b"]["dtype"], header["c"]["dtype"]) == ("F16", "F16", "F32")
    assert len(data) == len(old_data)
    # F32 is copied byte for byte.
    begin, end = header["c"]["data_offsets"]
    assert data[begin:end] == old_data[begin:end]
    # The FP16 values are the BF16 values; those out of range are the largest of their sign.
    begin, end = header["a"]["data_offsets"]
    values = struct.unpack("<4e", data[begin:end])
    assert values[0] == 1.0
    assert values[1] == 65504.0
    assert values[2] == -65504.0
    assert values[3] == struct.unpack("<e", struct.pack("<e", _widened(_bf16([1.0e-8]))[0]))[0]
    begin, end = header["b"]["data_offsets"]
    assert struct.unpack("<4e", data[begin:end]) == (0.5, -2.0, 3.0, 0.0)


def test_a_file_without_an_overflow_counts_nothing(tmp_path: Path):
    """Silence: nothing out of range, nothing counted."""
    source = _sample(tmp_path, values=[1.0, 2.0, -3.0, 4.0])
    runner = Bildrunner(tmp_path)
    runner.reservieren(stoppable=True)
    _, capped = fp16_convert.convert(runner, source)
    runner.freigeben()
    assert capped == 0


def test_a_value_beyond_the_range_costs_only_its_own_block(tmp_path: Path, monkeypatch):
    """The values around it are converted as they are; infinity and the
    not-a-number of the source stay what they are."""
    monkeypatch.setattr(fp16_convert, "_BLOCK_VALUES", 2)
    values = [1.0, 2.0, 1.0e6, 3.0, float("inf"), float("nan")]
    packed, capped = fp16_convert.bf16_to_f16(_bf16(values))
    out = struct.unpack("<6e", packed)
    assert capped == 1
    assert out[:2] == (1.0, 2.0)
    assert out[2] == 65504.0
    assert out[3] == 3.0
    assert out[4] == float("inf")
    assert out[5] != out[5]


def test_only_a_file_of_mostly_bf16_is_offered(tmp_path: Path):
    mostly = _sample(tmp_path, "mostly.safetensors")
    other = tmp_path / "other.safetensors"
    _write(other, [
        ("a", "BF16", [2], _bf16([1.0, 2.0])),
        ("b", "F32", [64], b"\0" * 256),
    ])
    half = tmp_path / "half.safetensors"
    _write(half, [("a", "F16", [4], struct.pack("<4e", 1, 2, 3, 4))])
    gguf = tmp_path / "m.q8_0.gguf"
    gguf.write_bytes(b"GGUF" + b"\0" * 64)
    broken = tmp_path / "broken.safetensors"
    broken.write_bytes(b"not a header")
    assert fp16_convert.convertible(mostly) is True
    assert fp16_convert.convertible(other) is False
    assert fp16_convert.convertible(half) is False
    assert fp16_convert.convertible(gguf) is False
    assert fp16_convert.convertible(broken) is False
    assert fp16_convert.convertible(tmp_path / "missing.safetensors") is False


def test_the_list_says_which_files_get_a_copy(folder: Path, client: TestClient):
    _sample(folder)
    _write(folder / "half.safetensors", [("a", "F16", [4], struct.pack("<4e", 1, 2, 3, 4))])
    files = {entry["name"]: entry for entry in client.get("/api/v1/bild/model-files").json()}
    assert files["m.safetensors"]["fp16_convertible"] is True
    assert files["half.safetensors"]["fp16_convertible"] is False


def test_the_route_writes_the_copy_and_names_the_count(folder: Path, client: TestClient):
    _sample(folder)
    answer = client.post(URL, json={"model": "m.safetensors"})
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"file": "m.fp16.safetensors", "capped": 2}
    assert (folder / "m.fp16.safetensors").is_file()
    # The copy is mostly FP16 now, so it gets no second copy; it gets a smaller one.
    files = {entry["name"]: entry for entry in client.get("/api/v1/bild/model-files").json()}
    assert files["m.fp16.safetensors"]["fp16_convertible"] is False
    assert not client.app.state.bildrunner.laeuft()


def test_a_copy_that_lies_there_is_not_written_again(folder: Path, client: TestClient):
    _sample(folder)
    (folder / "m.fp16.safetensors").write_bytes(b"mine")
    answer = client.post(URL, json={"model": "m.safetensors"})
    assert answer.status_code == 409
    assert (folder / "m.fp16.safetensors").read_bytes() == b"mine"
    assert not list(folder.glob(".*.tmp"))


def test_the_route_refuses_what_has_no_copy_to_make(folder: Path, client: TestClient):
    _write(folder / "half.safetensors", [("a", "F16", [4], struct.pack("<4e", 1, 2, 3, 4))])
    assert client.post(URL, json={"model": "half.safetensors"}).status_code == 400
    assert client.post(URL, json={"model": "missing.safetensors"}).status_code == 404
    assert not list(folder.glob("*.fp16.*"))


def test_a_picture_in_hand_refuses_the_conversion(folder: Path, client: TestClient):
    _sample(folder)
    runner = client.app.state.bildrunner
    runner.reservieren()
    try:
        assert client.post(URL, json={"model": "m.safetensors"}).status_code == 409
    finally:
        runner.freigeben()
    assert not (folder / "m.fp16.safetensors").exists()


def _slow(monkeypatch, seconds: float, fail_at: int | None = None) -> list[int]:
    """Small pieces, each taking ``seconds``; the piece ``fail_at`` fails."""
    monkeypatch.setattr(fp16_convert, "PIECE_BYTES", 64)
    calls: list[int] = []
    real = fp16_convert.bf16_to_f16

    def slow(raw: bytes):
        calls.append(len(raw))
        if fail_at is not None and len(calls) == fail_at:
            raise OSError("no room left")
        time.sleep(seconds)
        return real(raw)

    monkeypatch.setattr(fp16_convert, "bf16_to_f16", slow)
    return calls


def _wide(folder: Path) -> Path:
    path = folder / "m.safetensors"
    _write(path, [("a", "BF16", [4096], _bf16([1.0] * 4096))])
    return path


def test_a_stop_in_the_middle_ends_the_copy_and_leaves_no_half_file(folder: Path, client: TestClient, monkeypatch):
    _wide(folder)
    calls = _slow(monkeypatch, 0.05)
    runner = client.app.state.bildrunner
    answers: list = []
    thread = threading.Thread(
        target=lambda: answers.append(client.post(URL, json={"model": "m.safetensors"})), daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + 10
    while len(calls) < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    share = (runner.fortschritt() or {}).get("anteil")
    assert share is not None and 0 < share < 1
    assert client.post("/api/v1/bild/stop").json() is True
    thread.join(timeout=20)
    assert not thread.is_alive()
    assert answers[0].status_code == 499
    # It ended at the next piece, not after the last one: 8192 bytes in pieces of 64.
    assert len(calls) < 128
    assert sorted(path.name for path in folder.iterdir()) == ["m.safetensors"]
    assert not runner.laeuft()
    assert runner.fortschritt() is None
    # Nothing is left to stop.
    assert client.post("/api/v1/bild/stop").json() is False


def test_a_failure_in_the_middle_leaves_no_file_and_names_the_reason(folder: Path, client: TestClient, monkeypatch):
    _wide(folder)
    calls = _slow(monkeypatch, 0, fail_at=3)
    answer = client.post(URL, json={"model": "m.safetensors"})
    assert len(calls) == 3
    assert answer.status_code == 503
    assert "no room left" in answer.json()["detail"]
    assert sorted(path.name for path in folder.iterdir()) == ["m.safetensors"]
    assert not client.app.state.bildrunner.laeuft()


def test_a_file_that_ends_inside_a_tensor_is_no_copy(folder: Path, client: TestClient):
    path = _wide(folder)
    path.write_bytes(path.read_bytes()[:-100])
    answer = client.post(URL, json={"model": "m.safetensors"})
    assert answer.status_code == 503
    assert sorted(entry.name for entry in folder.iterdir()) == ["m.safetensors"]
