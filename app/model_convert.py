"""sd-cli's tools beside drawing: converting a model file to GGUF, and the
list of devices it can compute on.

Converting (``sd-cli -M convert``) writes a new file beside the old one and
never touches the old one; an importance matrix collected for the model
(``app.bildrunner.imatrix_path``) is used when there is one, so the weights
that matter most keep more of their precision (sd.cpp docs/imatrix.md).

Only into a smaller copy: a type with fewer bits per weight than the type
most of the file's weights are stored in. A copy as large or larger, and a
16-bit or 32-bit copy, is never offered and never made.
"""

from __future__ import annotations

import functools
import json
import logging
import struct
import subprocess
from pathlib import Path

from app import ggufmtp
from app.bildrunner import BildFehler, Bildrunner, imatrix_path
from app.bildwahlen import WEIGHT_TYPES
from app.no_console import no_window

log = logging.getLogger(__name__)

# Converting a large model takes minutes; the ceiling only catches a hang.
CONVERT_TIMEOUT = 3600
# Listing the devices is a moment.
DEVICES_TIMEOUT = 60


# Bits per weight of each type a copy can be written in, from the block
# layout ggml stores it in (ggml.c ``type_traits``: bytes per block over
# weights per block); the two float8 types are one byte a weight.
TARGET_BITS = {
    "f32": 32.0, "f16": 16.0, "bf16": 16.0, "f8_e4m3": 8.0, "f8_e5m2": 8.0,
    "q8_0": 8.5, "q6_K": 6.5625, "q5_1": 6.0, "q5_0": 5.5, "q5_K": 5.5,
    "q4_1": 5.0, "q4_0": 4.5, "q4_K": 4.5, "q3_K": 3.4375, "q2_K": 2.625,
}
# The same for a GGUF's stored types, by their number in ggml.h.
_GGML_BITS = {
    0: 32.0, 1: 16.0, 2: 4.5, 3: 5.0, 6: 5.5, 7: 6.0, 8: 8.5, 9: 9.0,
    10: 2.625, 11: 3.4375, 12: 4.5, 13: 5.5, 14: 6.5625, 15: 9.125, 30: 16.0,
}
# The same for a safetensors file's dtypes.
_SAFETENSORS_BITS = {
    "F64": 64.0, "F32": 32.0, "F16": 16.0, "BF16": 16.0, "F8_E4M3": 8.0, "F8_E5M2": 8.0,
}
# A copy in 16 bits or more is no smaller copy of any model worth drawing.
_FLOAT_COPY = 16.0
# A safetensors header longer than this is no header.
_SAFETENSORS_HEADER_MAX = 100 * 1024 * 1024


def safetensors_header(source: Path) -> tuple[int, dict] | None:
    """The length of a safetensors file's JSON header and the header itself,
    or None when the file has no header of that kind."""
    with open(source, "rb") as file:
        start = file.read(8)
        if len(start) != 8:
            return None
        length = struct.unpack("<Q", start)[0]
        if not 0 < length < _SAFETENSORS_HEADER_MAX:
            return None
        header = json.loads(file.read(length))
    return (length, header) if isinstance(header, dict) else None


def safetensors_main_dtype(source: Path) -> str | None:
    """The dtype most of a safetensors file's weights are stored in."""
    parsed = safetensors_header(source)
    if parsed is None:
        return None
    weights: dict[str, int] = {}
    for name, entry in parsed[1].items():
        if name == "__metadata__" or not isinstance(entry, dict):
            continue
        count = 1
        for size in entry.get("shape") or []:
            count *= int(size)
        dtype = str(entry.get("dtype"))
        weights[dtype] = weights.get(dtype, 0) + count
    if not weights:
        return None
    return max(weights, key=lambda dtype: weights[dtype])


def _safetensors_bits(source: Path) -> float | None:
    """The bits per weight most of a safetensors file's weights hold."""
    dtype = safetensors_main_dtype(source)
    return None if dtype is None else _SAFETENSORS_BITS.get(dtype)


def source_bits(source: Path) -> float | None:
    """The bits per weight of the type most of the file's weights are
    stored in, or None when it cannot be told. A pickled checkpoint holds
    torch's float tensors, never a quantised type, so it counts as 16 bits;
    a GGUF or safetensors file is read from its header."""
    try:
        with open(source, "rb") as file:
            gguf = file.read(4) == b"GGUF"
        if gguf:
            types = ggufmtp.tensor_types(source)
            if not types:
                return None
            return _GGML_BITS.get(max(types, key=lambda kind: types[kind]))
        if source.suffix.lower() == ".safetensors":
            return _safetensors_bits(source)
    except (OSError, ValueError, TypeError):
        return None
    return _FLOAT_COPY


def smaller_types(source: Path) -> tuple[str, ...]:
    """The types a copy of ``source`` gets smaller in, in the order the
    weight type list names them; empty when none does. Read once per file
    state: the model list asks for every file on every listing."""
    try:
        state = source.stat()
    except OSError:
        return ()
    return _smaller_types(str(source), state.st_size, state.st_mtime_ns)


@functools.lru_cache(maxsize=256)
def _smaller_types(source: str, size: int, mtime_ns: int) -> tuple[str, ...]:
    bits = source_bits(Path(source))
    if bits is None:
        return ()
    return tuple(
        kind for kind in WEIGHT_TYPES
        if TARGET_BITS[kind] < min(bits, _FLOAT_COPY)
    )


class ConvertError(Exception):
    def __init__(self, reason: str, log_text: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.log_text = log_text


def target(source: Path, weight_type: str) -> Path:
    """The converted file's place: beside the source, named after it and
    the type, so two conversions of one file never meet."""
    return source.with_name(f"{source.stem}.{weight_type}.gguf")


def converted_type(path: Path) -> str | None:
    """The weight type of ``path`` when it is a file a conversion wrote —
    named ``<stem>.<type>.gguf`` as ``target`` names it, the type one of the
    list a copy is offered in — otherwise None."""
    if path.suffix.lower() != ".gguf":
        return None
    _, dot, kind = path.stem.rpartition(".")
    return kind if dot and kind in WEIGHT_TYPES else None


def command(program: Path, source: Path, weight_type: str) -> list[str]:
    parts = [
        str(program), "-M", "convert", "-m", str(source), "-o", str(target(source, weight_type)),
        "--type", weight_type,
    ]
    matrix = imatrix_path(source)
    if matrix.is_file():
        parts += ["--imat-in", str(matrix)]
    return parts


def convert(runner: Bildrunner, program: Path, source: Path, weight_type: str) -> Path:
    """Convert ``source`` to a GGUF of ``weight_type`` and return the new
    file. The conversion is the runner's process while it lasts, so a stop
    ends it like a picture; the caller holds the one-picture lock."""
    out = target(source, weight_type)
    if out.exists():
        raise ConvertError("bild.umwandeln_da")
    try:
        code, text = runner.run_tool(
            command(program, source, weight_type), timeout=CONVERT_TIMEOUT,
        )
    except BildFehler as stopped:
        # Stopped, not failed: what was asked for. The half-written file
        # goes all the same.
        out.unlink(missing_ok=True)
        log.info("Converting %s to %s was stopped", source.name, weight_type)
        raise ConvertError(stopped.grund) from stopped
    except (OSError, subprocess.TimeoutExpired) as error:
        out.unlink(missing_ok=True)
        raise ConvertError("bild.umwandeln_gescheitert") from error
    if code != 0 or not out.is_file():
        out.unlink(missing_ok=True)
        log.warning("Converting failed (%s): %s", code, text[-500:])
        raise ConvertError("bild.umwandeln_gescheitert", text.strip()[-1200:])
    return out


def devices(program: Path) -> list[dict[str, str]]:
    """The devices sd-cli can compute on, as its ``--list-devices`` names
    them: one ``name<TAB>description`` per line."""
    try:
        run = subprocess.run(
            [str(program), "--list-devices"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=DEVICES_TIMEOUT, check=False,
            **no_window(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    found = []
    for line in (run.stdout or "").splitlines():
        name, tab, description = line.partition("\t")
        if tab and name.strip():
            found.append({"name": name.strip(), "description": description.strip()})
    return found
