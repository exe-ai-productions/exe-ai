"""A file the way sd.cpp reads an upscaler: the names and shapes of an ESRGAN
that enlarges four times and nothing else. Tests that need an upscaler in the
folder write this instead of a few stray bytes, which the program no longer
offers. A ``.pth`` gets a zip with a pickle that only names its tensors; any
other name gets the header of a safetensors file."""

from __future__ import annotations

import json
import struct
import zipfile
from pathlib import Path

_NAMES = {
    "conv_first.weight": [64, 3, 3, 3],
    "body.0.rdb1.conv1.weight": [32, 64, 3, 3],
    "conv_up1.weight": [64, 64, 3, 3],
    "conv_up2.weight": [64, 64, 3, 3],
}


def _pickle() -> bytes:
    """A dict of tensors, each asked for by the rebuild function with its
    shape; nothing in it runs when it is read the way the program reads it."""
    out = b"\x80\x02}("
    for name, shape in _NAMES.items():
        encoded = name.encode()
        out += b"X" + struct.pack("<I", len(encoded)) + encoded
        out += b"ctorch._utils\n_rebuild_tensor_v2\n(NK\x00(" + b"".join(b"K" + bytes([d]) for d in shape)
        out += b"tNNtR"
    return out + b"u."


def write(path: Path) -> Path:
    """Write the upscaler to ``path``."""
    if path.suffix == ".pth":
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("archive/data.pkl", _pickle())
        return path
    header = {n: {"dtype": "F32", "shape": s, "data_offsets": [0, 0]} for n, s in _NAMES.items()}
    raw = json.dumps(header).encode()
    path.write_bytes(struct.pack("<Q", len(raw)) + raw)
    return path
