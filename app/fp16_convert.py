"""Writing a safetensors file whose weights are mostly BF16 again with those
weights as FP16.

BF16 and FP16 are both two bytes a weight, so every tensor keeps its place:
only the dtype in the header changes, and each BF16 value is converted. Every
other tensor is copied byte for byte, and so are the header's metadata. The
copy is written beside the source as ``<name>.fp16.safetensors``; the source
stays as it is. A value that FP16 cannot hold is set to the largest FP16
value of its sign, and counted, so the caller can say how many there were.

The standard library does the converting (``struct`` knows FP16 as ``e``):
the program ships without a numeric library, and a copy of a few gigabytes is
a matter of minutes.
"""

from __future__ import annotations

import functools
import json
import logging
import struct
from pathlib import Path

from app import atomic_file, model_convert
from app.bildrunner import BildFehler, Bildrunner
from app.model_convert import ConvertError

log = logging.getLogger(__name__)

# Bytes read and written at a time: a stop is looked for between the pieces.
PIECE_BYTES = 4 * 1024 * 1024
# A block of values packed in one call; a block that holds a value FP16
# cannot take is packed value by value instead.
_BLOCK_VALUES = 8192
# The largest finite FP16 value.
FP16_MAX = 65504.0


def target(source: Path) -> Path:
    """The copy's place: beside the source, named after it."""
    return source.with_name(f"{source.stem}.fp16.safetensors")


def convertible(source: Path) -> bool:
    """Whether most of the weights of ``source`` are BF16 — the only file
    that gets a copy in FP16. Read once per file state: the model list asks
    for every file on every listing."""
    if source.suffix.lower() != ".safetensors":
        return False
    try:
        state = source.stat()
    except OSError:
        return False
    return _convertible(str(source), state.st_size, state.st_mtime_ns)


@functools.lru_cache(maxsize=256)
def _convertible(source: str, size: int, mtime_ns: int) -> bool:
    try:
        return model_convert.safetensors_main_dtype(Path(source)) == "BF16"
    except (OSError, ValueError, TypeError):
        return False


def _pack_block(values: tuple[float, ...]) -> tuple[bytes, int]:
    """The values as FP16 and how many of them had to be set to the largest
    value of their sign."""
    try:
        return struct.pack(f"<{len(values)}e", *values), 0
    except OverflowError:
        pass
    packed = bytearray()
    capped = 0
    for value in values:
        try:
            packed += struct.pack("<e", value)
        except OverflowError:
            capped += 1
            packed += struct.pack("<e", FP16_MAX if value > 0 else -FP16_MAX)
    return bytes(packed), capped


def bf16_to_f16(raw: bytes) -> tuple[bytes, int]:
    """BF16 values (little endian) as FP16 values, and how many were out of
    FP16's range. A BF16 value is the upper half of the float32 of the same
    value, so it is widened by laying two zero bytes under it."""
    count = len(raw) // 2
    wide = bytearray(count * 4)
    wide[2::4] = raw[0::2]
    wide[3::4] = raw[1::2]
    values = struct.unpack(f"<{count}f", wide)
    out = bytearray()
    capped = 0
    for start in range(0, count, _BLOCK_VALUES):
        packed, over = _pack_block(values[start:start + _BLOCK_VALUES])
        out += packed
        capped += over
    return bytes(out), capped


def _write(runner: Bildrunner, source: Path, part: Path) -> int:
    """Write the FP16 copy to ``part``; the number of capped values."""
    parsed = model_convert.safetensors_header(source)
    if parsed is None:
        raise ValueError("not a safetensors file")
    length, header = parsed
    metadata = header.pop("__metadata__", None)
    tensors = sorted(header.items(), key=lambda item: item[1]["data_offsets"][0])
    changed: dict = {} if metadata is None else {"__metadata__": metadata}
    for name, entry in tensors:
        changed[name] = {**entry, "dtype": "F16"} if entry["dtype"] == "BF16" else dict(entry)
    head = json.dumps(changed, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    head += b" " * (-len(head) % 8)
    data_start = 8 + length
    total = sum(entry["data_offsets"][1] - entry["data_offsets"][0] for _, entry in tensors)
    capped = 0
    done = 0
    position = 0
    runner.report_progress(0, total)
    with open(source, "rb") as src, open(part, "wb") as dst:
        dst.write(struct.pack("<Q", len(head)))
        dst.write(head)
        for _, entry in tensors:
            begin, end = entry["data_offsets"]
            if begin != position:
                raise ValueError("the tensors do not follow one another")
            bf16 = entry["dtype"] == "BF16"
            if bf16 and (end - begin) % 2:
                raise ValueError("a BF16 tensor of an odd number of bytes")
            src.seek(data_start + begin)
            remaining = end - begin
            while remaining:
                runner.end_if_stopped()
                piece = src.read(min(remaining, PIECE_BYTES))
                if not piece:
                    raise ValueError("the file ends inside a tensor")
                if bf16:
                    piece, over = bf16_to_f16(piece)
                    capped += over
                dst.write(piece)
                remaining -= len(piece)
                done += len(piece)
                runner.report_progress(done, total)
            position = end
    # The last look: from here on a stop no longer reaches the copy.
    runner.end_if_stopped(last=True)
    return capped


def convert(runner: Bildrunner, source: Path) -> tuple[Path, int]:
    """Write the FP16 copy of ``source`` and return it with the number of
    values that were out of FP16's range. The copy is the runner's hold of the
    one-picture lock while it lasts, so a stop ends it like a picture; the
    caller holds the lock. The copy is written to a side file and takes its
    place only when it is whole (app/atomic_file.py)."""
    out = target(source)
    if out.exists():
        raise ConvertError("bild.umwandeln_da")
    part = out.with_name(atomic_file.side_file_name(out.name))
    try:
        capped = _write(runner, source, part)
        atomic_file.rename_onto(part, out)
    except BildFehler as stopped:
        # Stopped, not failed: what was asked for.
        part.unlink(missing_ok=True)
        log.info("Converting %s to FP16 was stopped", source.name)
        raise ConvertError(stopped.grund) from stopped
    except (OSError, ValueError, KeyError, TypeError) as error:
        part.unlink(missing_ok=True)
        log.warning("Converting %s to FP16 failed: %s", source.name, error)
        raise ConvertError("bild.umwandeln_gescheitert", str(error)) from error
    finally:
        runner.clear_progress()
    return out, capped
