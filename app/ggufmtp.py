"""Whether a GGUF file carries its own multi-token-prediction layers.

Some model releases fold their MTP ("NextN") weights into the main file
instead of shipping them as a separate draft model next to it. The file
name and the repository it came from are both just words somebody chose;
the file's own GGUF header is the only place this is actually written
down.

``read_header`` below is the one GGUF header reader of this program:
``app/bildinhalt.py`` reads image model headers with it instead of keeping
a copy of its own. Keys and tensor names are compared as raw bytes
against pre-encoded constants — GGUF stores strings with no encoding
check, so only a value that is actually used as text is decoded.
"""

from __future__ import annotations

import io
import math
import os
import struct
from pathlib import Path

# GGUF value types, from the format's own spec — only the ones this reader
# has to either read or skip past show up here.
_ZEICHENKETTE = 8
_FELD = 9
_FESTE_GROESSE = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}

# The key llama.cpp writes on every architecture that carries embedded
# next-token-prediction layers — always this suffix behind the
# architecture's own name ("qwen35moe.nextn_predict_layers",
# "deepseek2.nextn_predict_layers", …). Present and greater than zero is
# the only honest signal; a file without it, or with it at zero, carries
# no embedded MTP.
_SCHLUESSEL_ENDUNG = b".nextn_predict_layers"

# A metadata section this large is not a metadata section any more —
# either the file is not a real GGUF or the header is corrupt. Real
# headers, vocabularies included, stay far under this.
_HOECHSTE_SCHLUESSEL_ANZAHL = 100_000


def traegt_eingebettetes_mtp(pfad: Path) -> bool:
    """Does this GGUF file carry its own multi-token-prediction layers?

    Reads only the header at the front of the file, never the tensor data
    behind it — cheap even for a model tens of gigabytes large.
    Anything that is not a current, well-formed GGUF header (wrong magic,
    an unsupported version, a truncated or hand-edited file) answers
    False instead of raising: a broken header proves nothing either way,
    and a model must still be startable without it.
    """
    try:
        return _kopf_lesen(_facts_for(pfad))
    except Exception:
        return False


def _check_remaining(file, needed: int, end: int) -> None:
    """A length or count asking for more bytes than the file still holds
    after this point is a broken header, not a long read — the same verdict
    ``genau`` gives a header that simply ends too early, but given before
    anything is read. Without it a corrupt array count near 2**64 was
    skipped element by element (seeking past the end does not fail), and a
    corrupt string length read the whole rest of a model file into memory.
    ``end`` is the file's size, taken once per header (``_file_end``)."""
    if needed > end - file.tell():
        raise EOFError("The header requests more bytes than the file contains.")


def _file_end(file) -> int:
    return os.fstat(file.fileno()).st_size


def genau(datei, anzahl: int) -> bytes:
    stueck = datei.read(anzahl)
    if len(stueck) != anzahl:
        raise EOFError("The header ended before this value was complete.")
    return stueck


def _u32(datei) -> int:
    return struct.unpack("<I", genau(datei, 4))[0]


def _u64(datei) -> int:
    return struct.unpack("<Q", genau(datei, 8))[0]


def _raw_string(datei, end: int) -> bytes:
    """One string's raw bytes, not decoded — what a key or a tensor name is
    compared as."""
    laenge = _u64(datei)
    # A length within one buffer reads no more than that even when the file
    # is shorter — `genau` then fails on it. Only a longer one is measured
    # first: `tell()` on every token doubled the time to pass a vocabulary.
    if laenge > io.DEFAULT_BUFFER_SIZE:
        _check_remaining(datei, laenge, end)
    return genau(datei, laenge)


def _zeichenkette(datei, end: int) -> str:
    """One string, decoded — only for a value that is used as text."""
    return _raw_string(datei, end).decode("utf-8")


def _zeichenkette_ueberspringen(datei, end: int) -> None:
    """Moves past one string by its length alone — its bytes are neither
    read nor decoded. GGUF stores a string as raw bytes with no encoding
    check, so one vocabulary token that is not valid UTF-8 must not make
    the whole header unreadable when the key looked for comes after it.
    The same length check as `_raw_string`."""
    laenge = _u64(datei)
    if laenge > io.DEFAULT_BUFFER_SIZE:
        _check_remaining(datei, laenge, end)
    datei.seek(laenge, 1)


def _wert_lesen(datei, art: int, end: int) -> int | float | bool | str:
    """The value's own bytes, decoded — only ever called on the keys a
    reader asks for, never on the whole header."""
    if art == _ZEICHENKETTE:
        return _zeichenkette(datei, end)
    if art == _FELD:
        # An array where a plain count was expected is not the marker
        # this reader knows how to trust — treated as "no" by the caller.
        _wert_ueberspringen(datei, art, end)
        return False
    if art == 7:
        return genau(datei, 1)[0] != 0
    rohdaten = genau(datei, _FESTE_GROESSE[art])
    if art in (4, 10):
        return int.from_bytes(rohdaten, "little", signed=False)
    if art in (5, 11):
        return int.from_bytes(rohdaten, "little", signed=True)
    if art == 6:
        return struct.unpack("<f", rohdaten)[0]
    if art == 12:
        return struct.unpack("<d", rohdaten)[0]
    return int.from_bytes(rohdaten, "little", signed=False)


def _wert_ueberspringen(datei, art: int, end: int) -> None:
    """Moves the file position past one value without decoding it — most
    of the header, and the only part a vocabulary-sized array costs."""
    if art == _ZEICHENKETTE:
        _zeichenkette_ueberspringen(datei, end)
        return
    if art == _FELD:
        elementart = _u32(datei)
        anzahl = _u64(datei)
        if elementart in _FESTE_GROESSE:
            # Fixed-size elements: checked and passed in one step.
            _check_remaining(datei, anzahl * _FESTE_GROESSE[elementart], end)
            datei.seek(anzahl * _FESTE_GROESSE[elementart], 1)
            return
        # A string takes at least its 8-byte length, an array at least its
        # 4-byte type and 8-byte count — the least each element can cost.
        _check_remaining(datei, anzahl * (8 if elementart == _ZEICHENKETTE else 12), end)
        for _ in range(anzahl):
            _wert_ueberspringen(datei, elementart, end)
        return
    datei.seek(_FESTE_GROESSE[art], 1)


def _header_counts(datei) -> tuple[int, int] | None:
    """Reads the fixed start of a GGUF header: how many tensors and how many
    metadata keys follow — or None when this is not a current, sane GGUF
    header."""
    if genau(datei, 4) != b"GGUF":
        return None
    if _u32(datei) not in (2, 3):
        return None
    tensors = _u64(datei)
    keys = _u64(datei)
    return (tensors, keys) if keys <= _HOECHSTE_SCHLUESSEL_ANZAHL else None


# More tensors than any real model file holds — a corrupt count, refused
# before the table is walked.
_MAX_TENSOR_COUNT = 1_000_000
# ggml holds at most four dimensions (GGML_MAX_DIMS in ggml.h); a larger
# count is a broken or foreign file, not a long read.
_MAX_DIMS = 4

Header = tuple[dict[bytes, int | float | bool | str], list[tuple[bytes, list[int]]]]


def _walk_header(
    datei, types: dict[int, int] | None = None, end: int | None = None
) -> Header | None:
    """The whole header: every metadata key and every tensor entry, never
    the tensor data behind it — the way llama.cpp itself reads one before it
    trusts it. A file that ends before its header does is not a header that
    happens to lack the rest: an answer read from its front would be
    remembered for a half-downloaded file.

    Answers the values of the keys a reader here asks for (``_wanted``), by
    their raw bytes, and each tensor's raw name with its dimensions as
    stored. None when this is not a current, sane GGUF header — a key that
    appears twice included, which llama.cpp refuses as well; raises when the
    file ends early or a count cannot be true. ``types``, when given,
    collects how many weights each ggml type holds. ``end`` is the file's
    size when ``datei`` holds only the front of a file that lives elsewhere
    (``bildinhalt.header_from_bytes``); otherwise it is read from the file.
    """
    end = _file_end(datei) if end is None else end
    counts = _header_counts(datei)
    if counts is None:
        return None
    tensor_count, key_count = counts
    if tensor_count > _MAX_TENSOR_COUNT:
        return None
    values: dict[bytes, int | float | bool | str] = {}
    seen: set[bytes] = set()
    for _ in range(key_count):
        key = _raw_string(datei, end)
        if key in seen:
            return None
        seen.add(key)
        kind = _u32(datei)
        if _wanted(key):
            values[key] = _wert_lesen(datei, kind, end)
        else:
            _wert_ueberspringen(datei, kind, end)
    # Each tensor entry: its name, its dimension count and dimensions, its
    # type and its offset — at least 24 bytes.
    _check_remaining(datei, tensor_count * 24, end)
    tensors: list[tuple[bytes, list[int]]] = []
    for _ in range(tensor_count):
        name = _raw_string(datei, end)
        dims = _u32(datei)
        if dims > _MAX_DIMS:
            raise ValueError("A tensor has more dimensions than ggml supports.")
        _check_remaining(datei, dims * 8 + 12, end)
        shape = [_u64(datei) for _ in range(dims)]
        if types is None:
            datei.seek(4 + 8, 1)  # type and offset
        else:
            kind = _u32(datei)
            datei.seek(8, 1)  # offset
            types[kind] = types.get(kind, 0) + math.prod(shape)
        tensors.append((name, shape))
    # Skipped values and each tensor's type and offset are passed by seeking,
    # and seeking past the end does not fail: zero bytes still to come is
    # the check that the position is not past the end. One check per header,
    # not one per token.
    _check_remaining(datei, 0, end)
    return values, tensors


def _wanted(key: bytes) -> bool:
    """The keys any reader here looks at: the architecture, the
    prediction-layer marker and the vision-encoder flag."""
    return (
        key == ARCHITEKTUR_SCHLUESSEL or key == SEHTEIL_SCHLUESSEL
        or key.endswith(_SCHLUESSEL_ENDUNG)
    )


def read_header(pfad: Path) -> Header | None:
    """The whole header of the file at ``pfad`` (see ``_walk_header``), or
    None when it is not a whole, sane GGUF header. Not kept: each reader
    keeps only what it needs of it. A file that cannot be opened or read
    right now (a scanner holding a fresh download open) raises ``OSError``.
    """
    with open(pfad, "rb") as datei:
        try:
            return _walk_header(datei)
        except OSError:
            raise
        except Exception:
            return None


def tensor_types(pfad: Path) -> dict[int, int] | None:
    """How many weights each ggml type holds in the file at ``pfad``, by the
    type's number in ggml.h; None when it is not a whole, sane GGUF header.
    A file that cannot be read right now raises ``OSError``."""
    types: dict[int, int] = {}
    with open(pfad, "rb") as datei:
        try:
            if _walk_header(datei, types) is None:
                return None
        except OSError:
            raise
        except Exception:
            return None
    return types


# What this module's two questions need of a header: the values of the keys
# it looks at (the architecture and the prediction-layer markers — a few
# numbers and one name) and whether the model's own first layer is there.
# Never the tensor table itself.
_Facts = tuple[dict[bytes, int | float | bool | str], bool]

# The facts per file path, with the size and modification time they were
# read at — a changed file is read again, one entry per path. The whole
# header is read for them — vocabulary included, a tenth to a quarter of a
# second per model (measured) — and the model list asks for every file on
# every listing.
_facts: dict[str, tuple[int, int, _Facts | None]] = {}


def _facts_for(pfad: Path) -> _Facts | None:
    """The facts of the file at ``pfad``, read once per file state. A file
    that cannot be read right now raises ``OSError`` and is not
    remembered, so the next look reads it."""
    info = os.stat(pfad)
    key = str(pfad)
    stamp = (info.st_size, info.st_mtime_ns)
    known = _facts.get(key)
    if known is not None and known[:2] == stamp:
        return known[2]
    header = read_header(pfad)
    facts = None if header is None else (
        header[0], any(name == _FIRST_LAYER_TENSOR for name, _ in header[1])
    )
    _facts[key] = (*stamp, facts)
    return facts


def _kopf_lesen(facts: _Facts | None) -> bool:
    if facts is None:
        return False
    # Of several marker keys the first decides, as it always did; the same
    # key twice over is a broken header (``_walk_header``).
    wert = next(
        (value for key, value in facts[0].items() if key.endswith(_SCHLUESSEL_ENDUNG)), None
    )
    return isinstance(wert, (int, float)) and not isinstance(wert, bool) and wert > 0


# What a GGUF file is — a standalone multi-token-prediction drafter that
# rides along with a model, or a model of its own. The name says nothing
# (a whole model may carry "mtp" in its name because it has its prediction
# layers built in); the header does, the way llama.cpp itself tells them
# apart when it loads a prediction-only file: the architecture announces
# prediction layers (`<arch>.nextn_predict_layers` above zero) and the file
# lacks the model's own first layer (`blk.0.attn_norm.weight`). A whole
# model with built-in prediction layers carries both. One architecture is a
# drafter by name as well, the one a drafter file was first measured with:
#   gemma4-assistant — unsloth/gemma-4-12B-it-qat-GGUF,
#     MTP/mtp-gemma-4-12B-it-Q4_0.gguf (49 tensors, 423M, 4 prediction
#     layers). The whole models it rides with report their own family.
BEIFAHRER = "beifahrer"
MODELL = "modell"
BEIFAHRER_ARCHITEKTUREN = frozenset({"gemma4-assistant"})
ARCHITEKTUR_SCHLUESSEL = b"general.architecture"
# The flag a vision projector file (mmproj) carries: the weights of a
# vision encoder, which a text encoder of the same architecture lacks.
SEHTEIL_SCHLUESSEL = b"clip.has_vision_encoder"
_FIRST_LAYER_TENSOR = b"blk.0.attn_norm.weight"

def dateiart(pfad: Path) -> str | None:
    """BEIFAHRER, MODELL, or None when the header does not say.

    A header that is not a current, well-formed GGUF, or one without an
    architecture, answers None: it proves nothing either way, so a file with
    such a header is neither moved nor offered as a drafter. The header is
    read once per file state (``_facts_for``).
    """
    try:
        return _art_lesen(_facts_for(pfad))
    except OSError:
        # Not readable right now: asked again next time rather than
        # remembered.
        return None


def _art_lesen(facts: _Facts | None) -> str | None:
    if facts is None:
        return None
    values, has_first_layer = facts
    architecture = values.get(ARCHITEKTUR_SCHLUESSEL)
    if not isinstance(architecture, str):
        return None
    if architecture in BEIFAHRER_ARCHITEKTUREN:
        return BEIFAHRER
    layers = values.get(architecture.encode("utf-8") + _SCHLUESSEL_ENDUNG)
    if isinstance(layers, bool) or not isinstance(layers, (int, float)) or layers <= 0:
        return MODELL
    if has_first_layer:
        return MODELL
    return BEIFAHRER
