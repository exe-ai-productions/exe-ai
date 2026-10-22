"""Enlarging a finished picture the way sd-cli and the picture server do it.

The factor of an upscaler is read from its weights (``app/upscaler_scale.py``)
the way sd.cpp reads it; only files sd.cpp can read are offered; the repeats
and the tile size go out with the wish; and a result larger than the picture
server returns goes to sd-cli. The weights of a ``.pth`` are read without
running a line of its pickle.
"""

from __future__ import annotations

import base64
import collections
import io
import json
import os
import pickle
import struct
import sys
import types
import zipfile
from pathlib import Path
from typing import Any, cast

import pytest
from PIL import Image
from pydantic import ValidationError

from app import bildrunner, bildturbo, upscaler_scale
from app.api.v1 import bild as bildapi
from app.api.v1.bild import BildWunsch
from app.bildrunner import Auftrag, Bildrunner, upscaler_scales, upscalers
from app.bildturbo import Bildturbo


# --- Small upscaler files ---------------------------------------------------


def _safetensors(path: Path, names: dict[str, list[int]]) -> Path:
    header = {n: {"dtype": "F32", "shape": s, "data_offsets": [0, 0]} for n, s in names.items()}
    raw = json.dumps(header).encode()
    path.write_bytes(struct.pack("<Q", len(raw)) + raw)
    return path


def _rrdb(*, up1: bool = True, up2: bool = True, old: bool = False) -> dict[str, list[int]]:
    """The weights of an ESRGAN: the names of the newer layout, or of the
    older one (``model.N``, ``RDB1`` inside ``sub``)."""
    if old:
        names = {
            "model.0.weight": [64, 3, 3, 3], "model.0.bias": [64],
            "model.1.sub.0.RDB1.conv1.0.weight": [32, 64, 3, 3],
            "model.1.sub.23.weight": [64, 64, 3, 3],
        }
        if up1:
            names["model.3.weight"] = [64, 64, 3, 3]
        if up2:
            names["model.6.weight"] = [64, 64, 3, 3]
        return names
    names = {
        "conv_first.weight": [64, 3, 3, 3],
        "body.0.rdb1.conv1.weight": [32, 64, 3, 3],
        "conv_body.weight": [64, 64, 3, 3],
        "conv_last.weight": [3, 64, 3, 3],
    }
    if up1:
        names["conv_up1.weight"] = [64, 64, 3, 3]
    if up2:
        names["conv_up2.weight"] = [64, 64, 3, 3]
    return names


COMPACT = {"body.0.weight": [64, 3, 3, 3], "body.1.weight": [64], "body.2.weight": [64, 64, 3, 3]}
TRANSFORMER = {
    "relative_position_index_SA": [64, 64], "conv_first.weight": [60, 3, 3, 3],
    "layers.0.attn.qkv.weight": [180, 60],
}


def _mosr(output_channels: int) -> dict[str, list[int]]:
    return {
        "gblocks.0.weight": [64, 64, 3, 3], "upsampler.0.weight": [output_channels, 64, 3, 3],
    }


# --- Pickles built without torch ---------------------------------------------


class _Storage:
    pass


class _Tensor:
    def __init__(self, shape: list[int]):
        self.shape = shape

    def __reduce__(self):
        return (_REBUILD, (_Storage(), 0, tuple(self.shape), (1,), False, collections.OrderedDict()))


def _rebuild_tensor_v2(*args: Any) -> None:  # never called: the reader runs nothing
    raise AssertionError("the reader ran a function of the pickle")


_rebuild_tensor_v2.__module__ = "torch._utils"
_rebuild_tensor_v2.__qualname__ = "_rebuild_tensor_v2"
_REBUILD = _rebuild_tensor_v2


class _Pickler(pickle.Pickler):
    def persistent_id(self, obj):
        if isinstance(obj, _Storage):
            return ("storage", "FloatStorage", "0", "cpu", 1)
        return None


@pytest.fixture(autouse=True)
def _torch_names(monkeypatch):
    """Names ``torch._utils`` for the pickler, as a real checkpoint does."""
    fake = types.ModuleType("torch")
    utils = types.ModuleType("torch._utils")
    utils._rebuild_tensor_v2 = _rebuild_tensor_v2  # type: ignore[attr-defined]
    fake._utils = utils  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "torch", fake)
    monkeypatch.setitem(sys.modules, "torch._utils", utils)


def _dumps(obj: object) -> bytes:
    buffer = io.BytesIO()
    _Pickler(buffer, protocol=2).dump(obj)
    return buffer.getvalue()


def _state(names: dict[str, list[int]]) -> collections.OrderedDict:
    return collections.OrderedDict((name, _Tensor(shape)) for name, shape in names.items())


def _pth_zip(path: Path, names: dict[str, list[int]], *, wrapped: str | None = None) -> Path:
    state: object = _state(names)
    if wrapped:
        state = collections.OrderedDict({wrapped: state})
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("archive/data.pkl", _dumps(state))
        archive.writestr("archive/version", "3\n")
    return path


def _pth_legacy(path: Path, names: dict[str, list[int]]) -> Path:
    """The format before the zip: the magic number, the protocol and the
    system information as three pickles, then the weights, then the keys of
    the storages, then the raw data."""
    with open(path, "wb") as stream:
        for head in (0x1950A86A20F9469CFC6C, 1001, {"protocol_version": 1001}):
            stream.write(_dumps(head))
        stream.write(_dumps(_state(names)))
        stream.write(_dumps(["0"]))
        stream.write(b"\x00" * 64)
    return path


# --- The factor and what sd.cpp can read -----------------------------------------


@pytest.mark.parametrize(("names", "factor"), [
    (_rrdb(), 4),
    (_rrdb(up2=False), 2),
    (_rrdb(up1=False, up2=False), 1),
    (_rrdb(old=True), 4),
    (_rrdb(old=True, up2=False), 2),
    (_mosr(48), 4),
    (_mosr(12), 2),
])
def test_the_factor_is_read_from_the_weights_of_a_safetensors_file(tmp_path, names, factor):
    path = _safetensors(tmp_path / "up.safetensors", names)
    assert upscaler_scale.scale(path) == factor


@pytest.mark.parametrize("names", [COMPACT, TRANSFORMER, _mosr(13), {"weight": [1]}])
def test_a_file_sd_cpp_does_not_read_has_no_factor(tmp_path, names):
    assert upscaler_scale.scale(_safetensors(tmp_path / "up.safetensors", names)) is None


@pytest.mark.parametrize("writer", [_pth_zip, _pth_legacy])
@pytest.mark.parametrize(("names", "factor"), [
    (_rrdb(), 4), (_rrdb(up2=False), 2), (_rrdb(old=True), 4), (_mosr(48), 4),
    (COMPACT, None), (TRANSFORMER, None),
])
def test_a_pth_gives_the_same_factors_in_both_of_its_formats(tmp_path, writer, names, factor):
    assert upscaler_scale.scale(writer(tmp_path / "up.pth", names)) == factor


def test_the_weights_a_training_wrapper_keeps_are_read(tmp_path):
    path = _pth_zip(tmp_path / "up.pth", _rrdb(), wrapped="params_ema")
    assert upscaler_scale.scale(path) == 4


def test_a_broken_file_has_no_factor(tmp_path):
    (tmp_path / "up.pth").write_bytes(b"not a checkpoint at all")
    (tmp_path / "up.safetensors").write_bytes(b"\x01\x02")
    (tmp_path / "empty.pth").write_bytes(b"")
    assert upscaler_scale.scale(tmp_path / "up.pth") is None
    assert upscaler_scale.scale(tmp_path / "up.safetensors") is None
    assert upscaler_scale.scale(tmp_path / "empty.pth") is None
    assert upscaler_scale.scale(tmp_path / "gone.pth") is None


def test_nothing_of_a_pickle_is_ever_run(tmp_path):
    """A pickle is a program. This one asks for a shell command and a call of
    the rebuild function between its weights: the weights are read, the
    marker file is never written, and the rebuild function never called."""
    marker = tmp_path / "marker"

    class Bomb:
        def __reduce__(self):
            return (os.system, (f"touch {marker}",))

    state = _state(_rrdb())
    state["x"] = cast(Any, Bomb())
    with zipfile.ZipFile(tmp_path / "up.pth", "w") as archive:
        archive.writestr("archive/data.pkl", _dumps(state))
    assert upscaler_scale.scale(tmp_path / "up.pth") == 4
    assert not marker.exists()


# --- The offered files ----------------------------------------------------------


def _folder(tmp_path: Path) -> Path:
    folder = tmp_path / bildrunner.UPSCALER_ORDNER
    folder.mkdir()
    _pth_zip(folder / "a-esrgan.pth", _rrdb())
    _pth_legacy(folder / "b-old.pth", _rrdb(old=True))
    _safetensors(folder / "c-x2.safetensors", _rrdb(up2=False))
    _safetensors(folder / "d-mosr.safetensors", _mosr(48))
    _pth_zip(folder / "e-compact.pth", COMPACT)
    _pth_zip(folder / "f-transformer.pth", TRANSFORMER)
    (folder / "g-broken.pth").write_bytes(b"garbage")
    (folder / "notes.md").write_text("not a model")
    return tmp_path


def test_only_the_files_sd_cpp_can_read_are_offered(tmp_path):
    folder = _folder(tmp_path)
    assert upscalers(folder) == ["a-esrgan.pth", "b-old.pth", "c-x2.safetensors", "d-mosr.safetensors"]
    assert upscaler_scales(folder) == {
        "a-esrgan.pth": 4, "b-old.pth": 4, "c-x2.safetensors": 2, "d-mosr.safetensors": 4,
    }


def test_the_files_that_do_not_fit_stay_in_the_folder(tmp_path):
    folder = _folder(tmp_path)
    upscalers(folder)
    assert (folder / bildrunner.UPSCALER_ORDNER / "e-compact.pth").is_file()
    assert (folder / bildrunner.UPSCALER_ORDNER / "f-transformer.pth").is_file()


def test_an_older_choice_that_no_longer_fits_is_a_missing_file(tmp_path):
    from app.bildrunner import BildFehler, upscaler_path

    folder = _folder(tmp_path)
    with pytest.raises(BildFehler):
        upscaler_path(folder, "e-compact.pth")
    assert upscaler_path(folder, "a-esrgan.pth").name == "a-esrgan.pth"


def test_a_missing_folder_offers_nothing(tmp_path):
    assert upscalers(tmp_path) == [] and upscaler_scales(tmp_path) == {}


# --- The repeats and the tile size go out with the wish ----------------------------


def _job(tmp_path: Path, **fields) -> Auftrag:
    return Auftrag(
        modell=tmp_path / "m.gguf", prompt="", mode="upscale",
        upscale_model=tmp_path / "up.pth", startbild=tmp_path / "a.png", **fields,
    )


def _line(tmp_path: Path, monkeypatch, **fields) -> list[str]:
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/somewhere/sd-cli")
    return Bildrunner(tmp_path).befehl(_job(tmp_path, **fields), tmp_path / "out.png")


def test_sd_cli_gets_the_repeats_and_the_tile_size(tmp_path, monkeypatch):
    line = _line(tmp_path, monkeypatch, upscale_repeats=2, upscale_tile_size=256)
    assert line[line.index("--upscale-repeats") + 1] == "2"
    assert line[line.index("--upscale-tile-size") + 1] == "256"
    assert line[line.index("-M") + 1] == "upscale"


def test_silence_the_start_values_stay_off_the_command_line(tmp_path, monkeypatch):
    line = _line(tmp_path, monkeypatch)
    assert "--upscale-repeats" not in line and "--upscale-tile-size" not in line
    line = _line(tmp_path, monkeypatch, upscale_repeats=1, upscale_tile_size=128)
    assert "--upscale-repeats" not in line and "--upscale-tile-size" not in line
    assert "--upscale-model" in line


class _Alive:
    pid = 4242

    def poll(self):
        return None


class _Answer:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"images": [{"b64_json": base64.b64encode(b"PNG").decode()}]}


def _server_body(tmp_path: Path, monkeypatch, **fields) -> dict:
    sent: list[dict] = []

    def post(url, json=None, **kwargs):
        sent.append(json)
        return _Answer()

    monkeypatch.setattr(bildturbo.httpx, "post", post)
    turbo = Bildturbo(tmp_path)
    turbo._prozess = cast(Any, _Alive())
    turbo._war_bereit = True
    assert turbo.upscale("AAAA", "up", **fields) == b"PNG"
    return sent[0]


def test_the_server_gets_the_repeats_and_the_tile_size(tmp_path, monkeypatch):
    body = _server_body(tmp_path, monkeypatch, repeats=2, tile_size=256)
    assert body["repeats"] == 2 and body["tile_size"] == 256
    assert body["upscaler"] == "up" and body["image"] == "AAAA"


def test_silence_the_server_body_is_what_it_was(tmp_path, monkeypatch):
    body = _server_body(tmp_path, monkeypatch)
    assert body == {"image": "AAAA", "upscaler": "up", "output_format": "png"}


def test_the_wish_takes_one_to_four_repeats_and_a_positive_tile(tmp_path):
    BildWunsch(modell="m", prompt="", mode="upscale", upscale_repeats=4, upscale_tile_size=1)
    for fields in ({"upscale_repeats": 5}, {"upscale_repeats": 0}, {"upscale_tile_size": 0}):
        with pytest.raises(ValidationError):
            BildWunsch(modell="m", prompt="", mode="upscale", **fields)
    wish = BildWunsch(modell="m", prompt="", mode="upscale")
    assert wish.upscale_repeats == 1 and wish.upscale_tile_size == 128


# --- What is beyond the picture server goes to sd-cli ---------------------------------


def _picture(path: Path, side: int) -> Path:
    Image.new("RGB", (side, side)).save(path)
    return path


@pytest.mark.parametrize(("side", "repeats", "fits"), [
    (1024, 1, True),    # 4096
    (2048, 1, True),    # 8192 exactly
    (2049, 1, False),   # 8196
    (2048, 2, False),   # 32768
    (512, 2, True),     # 8192 exactly
    (512, 3, False),
])
def test_a_result_beyond_8192_pixels_is_not_the_servers(tmp_path, side, repeats, fits, caplog):
    model = _pth_zip(tmp_path / "up.pth", _rrdb())
    job = _job(tmp_path, upscale_repeats=repeats)
    job = Auftrag(**{**job.__dict__, "upscale_model": model, "startbild": _picture(tmp_path / "a.png", side)})
    with caplog.at_level("INFO", logger="app.api.v1.bild"):
        assert bildapi._upscale_fits_the_server(job) is fits
    assert (not fits) == any("beyond" in line for line in caplog.messages)


def test_a_factor_or_a_size_that_is_not_known_leaves_the_server_to_try(tmp_path):
    job = Auftrag(
        modell=tmp_path / "m.gguf", prompt="", mode="upscale",
        upscale_model=tmp_path / "gone.pth", startbild=tmp_path / "gone.png", upscale_repeats=4,
    )
    assert bildapi._upscale_fits_the_server(job) is True
