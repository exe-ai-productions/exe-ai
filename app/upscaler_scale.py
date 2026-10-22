"""What an upscaler file is: whether sd.cpp can read it, and by how much it enlarges.

sd.cpp reads two kinds of upscaler: ESRGAN (the RRDBNet of ESRGAN and of
Real-ESRGAN's larger models) and MoSR. It takes the factor from the weights,
not from the file name: an ESRGAN that has a second upsampling convolution
enlarges four times, one with only the first twice, any other once; a MoSR's
factor is the square root of the third of the output channels of its upsampler.
Other architectures (Real-ESRGAN's compact models, the transformers SwinIR,
HAT and DAT) are not read: sd.cpp then writes the unchanged picture and says
it succeeded, so such a file is not offered.

The weights are read from the file's header: the header of a safetensors or
GGUF file, and for a ``.pth`` the names and shapes in its pickle. A pickle is a
program; nothing of it is ever run. The opcodes are read with ``pickletools``
and put together by a small machine of our own that builds only dicts,
lists, tuples, numbers and strings, and notes the shape of every tensor the
pickle asks to be rebuilt. A pickle that uses anything else is a file that is
not read.
"""

from __future__ import annotations

import functools
import math
import os
import pickletools
import struct
import zipfile
from pathlib import Path
from typing import BinaryIO

from app import bildinhalt

# The most a pickle may be and do: a state dict of a few hundred weights is
# some tens of kilobytes; nothing here is a reason to read a gigabyte.
_MAX_PICKLE_BYTES = 64_000_000
_MAX_OPCODES = 2_000_000

# Where a state dict hides its weights beside the weights themselves.
_WRAPPER_KEYS = ("params_ema", "params", "state_dict", "model")


class _NotRead(Exception):
    """The pickle does something this reader does not read."""


class _Global:
    """A name the pickle imports; never imported, only remembered."""

    __slots__ = ("path",)

    def __init__(self, path: str):
        self.path = path


class _Tensor:
    """A tensor the pickle asks to be rebuilt: only its shape is kept."""

    __slots__ = ("shape",)

    def __init__(self, shape: list[int]):
        self.shape = shape


class _Opaque:
    """Anything else the pickle builds: kept as nothing."""

    __slots__ = ()


_MARK = object()

_REBUILD_TENSOR = ("_rebuild_tensor_v2", "_rebuild_tensor")


def _call(function: object, args: object) -> object:
    """What a ``REDUCE`` makes of its function and arguments, without
    calling the function."""
    if not isinstance(function, _Global):
        return _Opaque()
    name = function.path.rsplit(".", 1)[-1]
    if name in _REBUILD_TENSOR and isinstance(args, tuple) and len(args) > 2:
        size = args[2]
        if isinstance(size, tuple) and all(isinstance(side, int) for side in size):
            return _Tensor(list(size))
    if name == "_rebuild_parameter" and isinstance(args, tuple) and args:
        return args[0]
    if function.path == "collections.OrderedDict":
        made: dict = {}
        if isinstance(args, tuple) and args and isinstance(args[0], list):
            for pair in args[0]:
                if isinstance(pair, tuple) and len(pair) == 2 and isinstance(pair[0], str):
                    made[pair[0]] = pair[1]
        return made
    return _Opaque()


def _pop_to_mark(stack: list) -> list:
    items: list = []
    while stack:
        item = stack.pop()
        if item is _MARK:
            items.reverse()
            return items
        items.append(item)
    raise _NotRead("a mark is missing")


_CONSTANTS = {
    "NONE": None, "NEWTRUE": True, "NEWFALSE": False, "EMPTY_TUPLE": (),
}
_VALUES = {
    "INT", "BININT", "BININT1", "BININT2", "LONG", "LONG1", "LONG4",
    "FLOAT", "BINFLOAT",
    "STRING", "BINSTRING", "SHORT_BINSTRING", "UNICODE", "BINUNICODE",
    "SHORT_BINUNICODE", "BINUNICODE8", "BINBYTES", "SHORT_BINBYTES",
    "BINBYTES8", "BYTEARRAY8",
}


def _read_pickle(stream: BinaryIO) -> object:
    """One pickle of the stream, read to its end and put together without
    running anything of it. Raises ``_NotRead`` for what it does not read."""
    stack: list = []
    memo: dict = {}
    for count, (opcode, argument, _position) in enumerate(pickletools.genops(stream)):
        if count > _MAX_OPCODES:
            raise _NotRead("too many opcodes")
        name = opcode.name
        if name in ("PROTO", "FRAME"):
            continue
        if name == "STOP":
            return stack.pop() if stack else None
        if name in _CONSTANTS:
            stack.append(_CONSTANTS[name])
        elif name in _VALUES:
            stack.append(argument)
        elif name == "MARK":
            stack.append(_MARK)
        elif name == "POP":
            stack.pop()
        elif name == "POP_MARK":
            _pop_to_mark(stack)
        elif name == "DUP":
            stack.append(stack[-1])
        elif name in ("PUT", "BINPUT", "LONG_BINPUT"):
            memo[argument] = stack[-1]
        elif name == "MEMOIZE":
            memo[len(memo)] = stack[-1]
        elif name in ("GET", "BINGET", "LONG_BINGET"):
            stack.append(memo[argument])
        elif name == "TUPLE":
            stack.append(tuple(_pop_to_mark(stack)))
        elif name in ("TUPLE1", "TUPLE2", "TUPLE3"):
            size = int(name[-1])
            items = stack[-size:]
            del stack[-size:]
            stack.append(tuple(items))
        elif name == "EMPTY_LIST":
            stack.append([])
        elif name == "LIST":
            stack.append(_pop_to_mark(stack))
        elif name == "EMPTY_DICT":
            stack.append({})
        elif name == "DICT":
            items = _pop_to_mark(stack)
            stack.append({
                key: value for key, value in zip(items[::2], items[1::2], strict=False)
                if isinstance(key, str)
            })
        elif name == "APPEND":
            item = stack.pop()
            if isinstance(stack[-1], list):
                stack[-1].append(item)
        elif name == "APPENDS":
            items = _pop_to_mark(stack)
            if isinstance(stack[-1], list):
                stack[-1].extend(items)
        elif name == "SETITEM":
            value, key = stack.pop(), stack.pop()
            if isinstance(stack[-1], dict) and isinstance(key, str):
                stack[-1][key] = value
        elif name == "SETITEMS":
            items = _pop_to_mark(stack)
            if isinstance(stack[-1], dict):
                for key, value in zip(items[::2], items[1::2], strict=False):
                    if isinstance(key, str):
                        stack[-1][key] = value
        elif name == "GLOBAL":
            stack.append(_Global(str(argument).replace(" ", ".", 1)))
        elif name == "STACK_GLOBAL":
            member, module = stack.pop(), stack.pop()
            stack.append(_Global(f"{module}.{member}"))
        elif name == "REDUCE":
            args, function = stack.pop(), stack.pop()
            stack.append(_call(function, args))
        elif name == "BUILD":
            stack.pop()
        elif name in ("NEWOBJ", "NEWOBJ_EX"):
            del stack[-(3 if name == "NEWOBJ_EX" else 2):]
            stack.append(_Opaque())
        elif name == "OBJ":
            _pop_to_mark(stack)
            stack.append(_Opaque())
        elif name == "INST":
            _pop_to_mark(stack)
            stack.append(_Opaque())
        elif name in ("BINPERSID", "PERSID"):
            stack.pop()
            stack.append(_Opaque())
        else:
            raise _NotRead(f"opcode {name}")
    raise _NotRead("a pickle without its end")


def _state_dict(top: object) -> dict[str, list[int]] | None:
    """The weights a pickle holds, by name with their shapes: the top
    dict itself, or the one a training wrapper keeps them in."""
    if not isinstance(top, dict):
        return None
    for key in _WRAPPER_KEYS:
        inner = top.get(key)
        if isinstance(inner, dict) and any(isinstance(v, _Tensor) for v in inner.values()):
            top = inner
            break
    weights = {
        name.removeprefix("module."): value.shape
        for name, value in top.items()
        if isinstance(name, str) and isinstance(value, _Tensor)
    }
    return weights or None


def _pickle_weights(path: Path) -> dict[str, list[int]] | None:
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                member = next(
                    (info for info in archive.infolist() if info.filename.endswith("data.pkl")),
                    None,
                )
                if member is None or member.file_size > _MAX_PICKLE_BYTES:
                    return None
                with archive.open(member) as stream:
                    return _state_dict(_read_pickle(stream))  # type: ignore[arg-type]
        # The format before the zip: four pickles one after the other (the
        # magic number, the protocol, the system information, then the
        # weights), the raw storages after them.
        with open(path, "rb") as stream:
            for _ in range(3):
                _read_pickle(stream)
            return _state_dict(_read_pickle(stream))
    except OSError:
        raise
    except (_NotRead, zipfile.BadZipFile, IndexError, KeyError, ValueError, TypeError,
            struct.error, EOFError, RecursionError):
        return None


def _weights(path: Path) -> dict[str, list[int]] | None:
    if path.suffix == ".pth" or path.suffix == ".pt":
        return _pickle_weights(path)
    read = bildinhalt.tensors(path)
    return read[0] if read else None


def scale_of(weights: dict[str, list[int]]) -> int | None:
    """The factor of an upscaler with these weights, or None when sd.cpp
    does not read such a file."""
    if "gblocks.0.weight" in weights:
        # MoSR: the upsampler holds the colour channels times factor squared.
        shape = weights.get("upsampler.0.weight")
        if not shape or shape[0] % 3:
            return None
        factor = math.isqrt(shape[0] // 3)
        return factor if factor >= 1 and factor * factor * 3 == shape[0] else None
    lowered = {name.lower() for name in weights}
    rrdb_net = any("rdb1" in name for name in lowered) and (
        "conv_first.weight" in lowered or "model.0.weight" in lowered
    )
    if not rrdb_net:
        return None
    if lowered & {"conv_up2.weight", "upconv2.weight", "model.6.weight"}:
        return 4
    if lowered & {"conv_up1.weight", "upconv1.weight", "model.3.weight"}:
        return 2
    return 1


@functools.lru_cache(maxsize=128)
def _scale_cached(path: str, size: int, mtime_ns: int) -> int | None:
    weights = _weights(Path(path))
    return scale_of(weights) if weights else None


def scale(path: Path) -> int | None:
    """The factor of the upscaler file, or None when sd.cpp cannot read it
    (or the file cannot be read now). Read once per file state."""
    try:
        state = os.stat(path)
        return _scale_cached(str(path), state.st_size, state.st_mtime_ns)
    except OSError:
        return None
