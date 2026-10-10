"""Reading a GGUF file's own header for embedded multi-token-prediction
weights.

No real model file is downloaded here — a handful of bytes in the exact
shape llama.cpp writes is the whole test. What matters is that the reader
trusts only the header's own key, never the name of the file it opened,
and that a header which is not what it claims to be answers "no" instead
of raising.
"""

from __future__ import annotations

import struct
from pathlib import Path

from app.ggufmtp import BEIFAHRER, MODELL, dateiart, traegt_eingebettetes_mtp

_ZEICHENKETTE = 8
_FELD = 9
_U32 = 4


def _wert_bytes(art: int, wert) -> bytes:
    if art == _ZEICHENKETTE:
        rohdaten = wert.encode("utf-8")
        return struct.pack("<Q", len(rohdaten)) + rohdaten
    if art == _U32:
        return struct.pack("<I", wert)
    if art == _FELD:
        elementart, werte = wert
        return (
            struct.pack("<I", elementart)
            + struct.pack("<Q", len(werte))
            + b"".join(_wert_bytes(elementart, eintrag) for eintrag in werte)
        )
    raise ValueError(f"unhandled type in this test's own builder: {art}")


def _gguf_bytes(
    paare: list[tuple[str, int, object]], *, version: int = 3, tensors: tuple[str, ...] = ()
) -> bytes:
    """The bytes of a minimal GGUF header, built the same way the real
    format is laid out — never the shortcuts an eager parser would allow.
    `tensors` are the names in the tensor table after the metadata, each a
    two-dimensional F32 entry."""
    kopf = bytearray(b"GGUF")
    kopf += struct.pack("<I", version)
    kopf += struct.pack("<Q", len(tensors))
    kopf += struct.pack("<Q", len(paare))
    for schluessel, art, wert in paare:
        roh = schluessel.encode("utf-8")
        kopf += struct.pack("<Q", len(roh)) + roh
        kopf += struct.pack("<I", art)
        kopf += _wert_bytes(art, wert)
    for name in tensors:
        roh = name.encode("utf-8")
        kopf += struct.pack("<Q", len(roh)) + roh
        kopf += struct.pack("<I", 2) + struct.pack("<QQ", 16, 16)
        kopf += struct.pack("<I", 0) + struct.pack("<Q", 0)
    return bytes(kopf)


def _datei(tmp_path: Path, inhalt: bytes) -> Path:
    pfad = tmp_path / "modell.gguf"
    pfad.write_bytes(inhalt)
    return pfad


def test_eingebettetes_mtp_wird_am_schluessel_erkannt(tmp_path):
    inhalt = _gguf_bytes([
        ("general.architecture", _ZEICHENKETTE, "qwen35moe"),
        ("qwen35moe.block_count", _U32, 41),
        ("qwen35moe.nextn_predict_layers", _U32, 1),
    ])
    assert traegt_eingebettetes_mtp(_datei(tmp_path, inhalt)) is True


def test_ein_gewoehnliches_modell_traegt_kein_mtp(tmp_path):
    inhalt = _gguf_bytes([
        ("general.architecture", _ZEICHENKETTE, "qwen35moe"),
        ("qwen35moe.block_count", _U32, 41),
    ])
    assert traegt_eingebettetes_mtp(_datei(tmp_path, inhalt)) is False


def test_die_schicht_null_zaehlt_nicht_als_eingebettet(tmp_path):
    # Present but zero is the architecture saying "I could, this build
    # doesn't" — the same as not being there at all.
    inhalt = _gguf_bytes([("qwen35moe.nextn_predict_layers", _U32, 0)])
    assert traegt_eingebettetes_mtp(_datei(tmp_path, inhalt)) is False


def test_ein_grosses_feld_davor_wird_sauber_uebersprungen(tmp_path):
    # A vocabulary-sized string array standing before the marker — the
    # shape every real chat model's header actually has.
    woerter = [f"tok{i}" for i in range(500)]
    inhalt = _gguf_bytes([
        ("tokenizer.ggml.tokens", _FELD, (_ZEICHENKETTE, woerter)),
        ("deepseek2.nextn_predict_layers", _U32, 1),
    ])
    assert traegt_eingebettetes_mtp(_datei(tmp_path, inhalt)) is True


def test_kein_gguf_ist_kein_absturz(tmp_path):
    pfad = _datei(tmp_path, b"not a gguf file at all, just some bytes")
    assert traegt_eingebettetes_mtp(pfad) is False


def test_ein_abgeschnittener_kopf_ist_kein_absturz(tmp_path):
    voll = _gguf_bytes([("qwen35moe.nextn_predict_layers", _U32, 1)])
    inhalt = voll[: len(voll) - 5]
    assert traegt_eingebettetes_mtp(_datei(tmp_path, inhalt)) is False


def test_eine_unbekannte_version_wird_abgelehnt(tmp_path):
    inhalt = _gguf_bytes([("qwen35moe.nextn_predict_layers", _U32, 1)], version=1)
    assert traegt_eingebettetes_mtp(_datei(tmp_path, inhalt)) is False


def test_eine_fehlende_datei_ist_kein_absturz(tmp_path):
    assert traegt_eingebettetes_mtp(tmp_path / "gibtsnicht.gguf") is False


# --- Drafter or model: the architecture in the header decides --------------


def test_die_gemessene_beifahrer_architektur_ist_ein_beifahrer(tmp_path: Path):
    pfad = tmp_path / "irgendein-name.gguf"
    pfad.write_bytes(_gguf_bytes([
        ("general.architecture", _ZEICHENKETTE, "gemma4-assistant"),
        ("gemma4-assistant.nextn_predict_layers", _U32, 4),
    ]))
    assert dateiart(pfad) == BEIFAHRER


def test_ein_modell_mit_eingebautem_mtp_und_mtp_im_namen_ist_ein_modell(tmp_path: Path):
    pfad = tmp_path / "Qwen3.8-27B-mtp.gguf"
    pfad.write_bytes(_gguf_bytes([
        ("general.architecture", _ZEICHENKETTE, "qwen35"),
        ("qwen35.nextn_predict_layers", _U32, 1),
    ], tensors=("token_embd.weight", "blk.0.attn_norm.weight", "blk.64.nextn.eh_proj.weight")))
    assert dateiart(pfad) == MODELL


def test_a_prediction_head_without_the_first_layer_is_a_drafter(tmp_path: Path):
    """A Nemotron head: its architecture announces prediction layers and the
    file has no first layer of a model — the way llama.cpp tells a
    prediction-only file apart (`mtp_only`)."""
    pfad = tmp_path / "mtp-NVIDIA-Nemotron-3.5-Lightning-30B-A3B-Q4_K_M.gguf"
    pfad.write_bytes(_gguf_bytes([
        ("general.architecture", _ZEICHENKETTE, "nemotron_h_moe"),
        ("tokenizer.ggml.tokens", _FELD, (_ZEICHENKETTE, [f"tok{i}" for i in range(300)])),
        ("nemotron_h_moe.nextn_predict_layers", _U32, 1),
    ], tensors=("blk.52.nextn.eh_proj.weight", "blk.52.attn_norm.weight")))
    assert dateiart(pfad) == BEIFAHRER


def test_a_model_without_prediction_layers_stays_a_model(tmp_path: Path):
    """Silence probe: no prediction layers announced — a model, whatever
    its tensor table holds."""
    ohne = tmp_path / "ohne.gguf"
    ohne.write_bytes(_gguf_bytes([
        ("general.architecture", _ZEICHENKETTE, "nemotron_h_moe"),
    ], tensors=("blk.52.attn_norm.weight",)))
    null = tmp_path / "null.gguf"
    null.write_bytes(_gguf_bytes([
        ("general.architecture", _ZEICHENKETTE, "nemotron_h_moe"),
        ("nemotron_h_moe.nextn_predict_layers", _U32, 0),
    ]))
    assert dateiart(ohne) == MODELL
    assert dateiart(null) == MODELL


def test_a_head_whose_tensor_table_breaks_off_says_nothing(tmp_path: Path):
    """Silence probe: prediction layers announced, the tensor table cut
    short — the header proves nothing, the file stays where it is."""
    voll = _gguf_bytes([
        ("general.architecture", _ZEICHENKETTE, "nemotron_h_moe"),
        ("nemotron_h_moe.nextn_predict_layers", _U32, 1),
    ], tensors=("blk.52.nextn.eh_proj.weight", "blk.53.attn_norm.weight"))
    pfad = tmp_path / "kurz.gguf"
    pfad.write_bytes(voll[:-30])
    assert dateiart(pfad) is None


def test_ohne_lesbare_architektur_sagt_der_kopf_nichts(tmp_path: Path):
    ohne = tmp_path / "ohne.gguf"
    ohne.write_bytes(_gguf_bytes([("general.name", _ZEICHENKETTE, "x")]))
    kein_text = tmp_path / "zahl.gguf"
    kein_text.write_bytes(_gguf_bytes([("general.architecture", _U32, 7)]))
    abgeschnitten = tmp_path / "halb.gguf"
    abgeschnitten.write_bytes(_gguf_bytes([("general.architecture", _ZEICHENKETTE, "qwen35")])[:30])
    fremd = tmp_path / "fremd.gguf"
    fremd.write_bytes(b"nicht gguf")
    for pfad in (ohne, kein_text, abgeschnitten, fremd):
        assert dateiart(pfad) is None, pfad.name


# --- Lengths the file cannot hold ----------------------------------------


def _header_with_raw_value(key: str, kind: int, raw: bytes) -> bytes:
    """A header whose first key carries ``raw`` as its value bytes, as they
    are — for values no honest builder would write — followed by the
    architecture key the readers are looking for."""
    header = bytearray(b"GGUF") + struct.pack("<I", 3) + struct.pack("<Q", 0)
    header += struct.pack("<Q", 3)
    for name, value_kind, value in (
        (key, kind, raw),
        ("qwen35.nextn_predict_layers", _U32, struct.pack("<I", 1)),
        ("general.architecture", _ZEICHENKETTE, _wert_bytes(_ZEICHENKETTE, "gemma4-assistant")),
    ):
        encoded = name.encode("utf-8")
        header += struct.pack("<Q", len(encoded)) + encoded + struct.pack("<I", value_kind) + value
    return bytes(header)


def _answers_quickly(call, path: Path):
    """The reader's answer, or a failed test when it has none within five
    seconds — without the length check it ran on for good."""
    import threading

    result: list = []

    def run():
        try:
            result.append(call(path))
        except BaseException as error:  # noqa: BLE001 - handed to the test below
            result.append(error)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(5)
    assert not thread.is_alive(), f"{call.__name__} is still reading {path.name}"
    if isinstance(result[0], BaseException):
        raise result[0]
    return result[0]


def test_an_array_count_near_two_to_the_64_is_a_broken_header(tmp_path):
    huge = struct.pack("<I", _U32) + struct.pack("<Q", 2**64 - 1)
    path = _datei(tmp_path, _header_with_raw_value("tokenizer.ggml.token_type", _FELD, huge))
    assert _answers_quickly(traegt_eingebettetes_mtp, path) is False
    assert _answers_quickly(dateiart, path) is None


def test_a_string_longer_than_the_file_is_a_broken_header(tmp_path, monkeypatch):
    """Refused before the read: nothing larger than the file is ever asked
    of it — on a model file of many gigabytes that read was the whole rest
    of the file, pulled into memory only to fail."""
    from app import ggufmtp

    asked: list[int] = []
    read_exactly = ggufmtp.genau

    def recording(file, count):
        asked.append(count)
        return read_exactly(file, count)

    monkeypatch.setattr(ggufmtp, "genau", recording)
    too_long = struct.pack("<Q", 2**40) + b"x"
    path = _datei(tmp_path, _header_with_raw_value("general.name", _ZEICHENKETTE, too_long))
    assert _answers_quickly(traegt_eingebettetes_mtp, path) is False
    assert _answers_quickly(dateiart, path) is None
    assert max(asked) <= path.stat().st_size


def test_a_large_honest_vocabulary_is_still_skipped(tmp_path):
    """The silence probe: a real vocabulary-sized array in front of the key
    is passed as before — strings one by one, fixed-size values at once."""
    path = _datei(tmp_path, _gguf_bytes([
        ("tokenizer.ggml.tokens", _FELD, (_ZEICHENKETTE, [f"tok{i}" for i in range(50_000)])),
        ("tokenizer.ggml.token_type", _FELD, (_U32, list(range(50_000)))),
        ("general.architecture", _ZEICHENKETTE, "gemma4-assistant"),
        ("gemma4-assistant.nextn_predict_layers", _U32, 4),
    ]))
    assert traegt_eingebettetes_mtp(path) is True
    assert dateiart(path) == BEIFAHRER


def test_a_string_array_count_the_file_cannot_hold_is_a_broken_header(tmp_path):
    huge = struct.pack("<I", _ZEICHENKETTE) + struct.pack("<Q", 2**63)
    path = _datei(tmp_path, _header_with_raw_value("tokenizer.ggml.tokens", _FELD, huge))
    assert _answers_quickly(traegt_eingebettetes_mtp, path) is False
    assert _answers_quickly(dateiart, path) is None


def test_a_file_not_readable_for_a_moment_is_asked_again(tmp_path: Path, monkeypatch):
    """A file held open by another program cannot be read for a moment; the
    answer is not remembered, and the next look reads it."""
    import builtins

    import app.ggufmtp as ggufmtp

    pfad = tmp_path / "kopf.gguf"
    pfad.write_bytes(_gguf_bytes([
        ("general.architecture", _ZEICHENKETTE, "gemma4-assistant"),
    ]))
    echt = builtins.open

    def gesperrt(*args, **kwargs):
        raise PermissionError("held by another program")

    monkeypatch.setattr(ggufmtp, "open", gesperrt, raising=False)
    assert dateiart(pfad) is None
    monkeypatch.setattr(ggufmtp, "open", echt, raising=False)
    assert dateiart(pfad) == BEIFAHRER


# --- Strings that are not valid UTF-8 -------------------------------------


def _raw_string(raw: bytes) -> bytes:
    return struct.pack("<Q", len(raw)) + raw


def _header_with_raw_strings(entries: list[tuple[bytes, int, bytes]], tensors: tuple[str, ...] = ()) -> bytes:
    """A header whose keys and values are given as their raw bytes — for
    strings no honest UTF-8 builder would write."""
    header = bytearray(b"GGUF") + struct.pack("<I", 3) + struct.pack("<Q", len(tensors))
    header += struct.pack("<Q", len(entries))
    for key, kind, value in entries:
        header += _raw_string(key) + struct.pack("<I", kind) + value
    for name in tensors:
        header += _raw_string(name.encode()) + struct.pack("<I", 2) + struct.pack("<QQ", 16, 16)
        header += struct.pack("<I", 0) + struct.pack("<Q", 0)
    return bytes(header)


def _vocabulary_with_invalid_token() -> bytes:
    tokens = [b"tok0", b"\xff\xfe", b"tok2"]
    return (
        struct.pack("<I", _ZEICHENKETTE)
        + struct.pack("<Q", len(tokens))
        + b"".join(_raw_string(token) for token in tokens)
    )


def test_a_token_that_is_not_utf8_before_the_keys_is_skipped(tmp_path):
    """A skipped string is passed by its length — one vocabulary token that
    is not valid UTF-8 no longer makes the whole header unreadable."""
    path = _datei(tmp_path, _header_with_raw_strings([
        (b"tokenizer.ggml.tokens", _FELD, _vocabulary_with_invalid_token()),
        (b"general.architecture", _ZEICHENKETTE, _raw_string(b"qwen35")),
        (b"qwen35.nextn_predict_layers", _U32, struct.pack("<I", 1)),
    ], tensors=("blk.0.attn_norm.weight",)))
    assert traegt_eingebettetes_mtp(path) is True
    assert dateiart(path) == MODELL


def test_a_plain_string_that_is_not_utf8_before_the_keys_is_skipped(tmp_path):
    path = _datei(tmp_path, _header_with_raw_strings([
        (b"general.name", _ZEICHENKETTE, _raw_string(b"name\xff")),
        (b"general.architecture", _ZEICHENKETTE, _raw_string(b"gemma4-assistant")),
        (b"gemma4-assistant.nextn_predict_layers", _U32, struct.pack("<I", 4)),
    ]))
    assert traegt_eingebettetes_mtp(path) is True
    assert dateiart(path) == BEIFAHRER


def test_an_invalid_byte_in_the_architecture_itself_still_makes_it_unreadable(tmp_path):
    """The silence probe: the value that is used as text is still decoded —
    an invalid byte there leaves the header unreadable, as before."""
    in_architecture = _datei(tmp_path, _header_with_raw_strings([
        (b"tokenizer.ggml.tokens", _FELD, _vocabulary_with_invalid_token()),
        (b"general.architecture", _ZEICHENKETTE, _raw_string(b"gemma4-assistant\xff")),
    ]))
    assert dateiart(in_architecture) is None


def test_a_foreign_key_that_is_not_utf8_before_the_architecture_is_passed(tmp_path):
    """Keys are compared as bytes, never decoded: a key nobody looks for
    with an invalid byte in it no longer hides the architecture behind it."""
    path = _datei(tmp_path, _header_with_raw_strings([
        (b"general.n\xffame", _ZEICHENKETTE, _raw_string(b"x")),
        (b"general.architecture", _ZEICHENKETTE, _raw_string(b"gemma4-assistant")),
        (b"gemma4-assistant.nextn_predict_layers", _U32, struct.pack("<I", 4)),
    ]))
    assert dateiart(path) == BEIFAHRER
    assert traegt_eingebettetes_mtp(path) is True


def test_a_tensor_name_that_is_not_utf8_is_compared_as_bytes(tmp_path):
    """The tensor table is compared as bytes too: a name with an invalid
    byte before the first layer does not make the header unreadable."""
    header = bytearray(_header_with_raw_strings([
        (b"general.architecture", _ZEICHENKETTE, _raw_string(b"qwen35")),
        (b"qwen35.nextn_predict_layers", _U32, struct.pack("<I", 1)),
    ]))
    header[8:16] = struct.pack("<Q", 2)
    for name in (b"blk.64.nextn\xff.weight", b"blk.0.attn_norm.weight"):
        header += _raw_string(name) + struct.pack("<I", 2) + struct.pack("<QQ", 16, 16)
        header += struct.pack("<I", 0) + struct.pack("<Q", 0)
    assert dateiart(_datei(tmp_path, bytes(header))) == MODELL


# --- Headers cut off inside the last skipped value -------------------------


def test_a_header_cut_inside_a_last_short_string_says_nothing(tmp_path):
    """A skipped string is passed by seeking, and seeking past the end does
    not fail — the cut-off header must still not read as whole."""
    whole = _gguf_bytes([
        ("general.architecture", _ZEICHENKETTE, "qwen35"),
        ("general.name", _ZEICHENKETTE, "abcdef"),
    ])
    assert dateiart(_datei(tmp_path, whole[:-2])) is None


def test_a_header_cut_inside_a_last_fixed_size_value_says_nothing(tmp_path):
    whole = _gguf_bytes([
        ("general.architecture", _ZEICHENKETTE, "qwen35"),
        ("general.alignment", _U32, 32),
    ])
    assert dateiart(_datei(tmp_path, whole[:-2])) is None


def test_a_whole_header_ending_on_a_skipped_value_is_still_read(tmp_path):
    """The silence probe: a header that ends exactly where its last skipped
    value does answers as before."""
    whole = _gguf_bytes([
        ("general.architecture", _ZEICHENKETTE, "qwen35"),
        ("general.name", _ZEICHENKETTE, "abcdef"),
        ("general.alignment", _U32, 32),
    ])
    assert dateiart(_datei(tmp_path, whole)) == MODELL


def test_a_key_with_an_invalid_byte_ending_in_the_marker_counts(tmp_path):
    """Keys are compared as bytes: one that ends in the marker counts as the
    marker, whatever invalid byte sits in front of it."""
    path = _datei(tmp_path, _header_with_raw_strings([
        (b"tokenizer.ggml.tokens", _FELD, _vocabulary_with_invalid_token()),
        (b"qwen35\xff.nextn_predict_layers", _U32, struct.pack("<I", 1)),
    ]))
    assert traegt_eingebettetes_mtp(path) is True


# --- The whole header is read ----------------------------------------------


def _model_with_tensors() -> bytes:
    return _gguf_bytes([
        ("general.architecture", _ZEICHENKETTE, "qwen35"),
        ("qwen35.nextn_predict_layers", _U32, 1),
    ], tensors=("blk.0.attn_norm.weight", "blk.64.nextn.eh_proj.weight"))


def test_a_file_ending_inside_the_tensor_table_is_unreadable(tmp_path):
    """The whole header is read before anything is answered — the way
    llama.cpp reads one: a file that ends inside its tensor table is
    unreadable, whatever its front already said."""
    without_layers = tmp_path / "plain.gguf"
    without_layers.write_bytes(_gguf_bytes([
        ("general.architecture", _ZEICHENKETTE, "qwen35"),
    ], tensors=("blk.0.attn_norm.weight", "output.weight"))[:-5])
    assert dateiart(without_layers) is None
    drafter = tmp_path / "drafter.gguf"
    drafter.write_bytes(_gguf_bytes([
        ("general.architecture", _ZEICHENKETTE, "gemma4-assistant"),
    ], tensors=("blk.0.attn_norm.weight",))[:-5])
    assert dateiart(drafter) is None
    cut = tmp_path / "cut.gguf"
    cut.write_bytes(_model_with_tensors()[:-5])
    assert traegt_eingebettetes_mtp(cut) is False
    assert dateiart(cut) is None


def test_a_whole_file_with_a_tensor_table_is_still_read(tmp_path):
    """The silence probe: the same header, whole, answers as before."""
    path = _datei(tmp_path, _model_with_tensors())
    assert traegt_eingebettetes_mtp(path) is True
    assert dateiart(path) == MODELL


def test_a_key_that_appears_twice_is_a_broken_header(tmp_path):
    """llama.cpp refuses a header with the same key twice; so does this
    reader — neither copy is trusted."""
    path = _datei(tmp_path, _gguf_bytes([
        ("general.architecture", _ZEICHENKETTE, "gemma4-assistant"),
        ("gemma4-assistant.nextn_predict_layers", _U32, 4),
        ("general.architecture", _ZEICHENKETTE, "qwen35"),
    ]))
    assert dateiart(path) is None
    assert traegt_eingebettetes_mtp(path) is False


def test_the_header_is_read_once_per_file_state(tmp_path, monkeypatch):
    """Each reader asks the header once per file state — this module for
    its verdicts, the image module for its shapes — however often it is
    asked; a changed file is read again."""
    from app import bildinhalt, ggufmtp

    walks: list[int] = []
    walk = ggufmtp._walk_header

    def counting(file):
        walks.append(1)
        return walk(file)

    monkeypatch.setattr(ggufmtp, "_walk_header", counting)
    path = _datei(tmp_path, _model_with_tensors())
    for _ in range(2):
        assert dateiart(path) == MODELL
        assert traegt_eingebettetes_mtp(path) is True
        assert bildinhalt.sorte(path) == bildinhalt.UNBEKANNT
        assert bildinhalt.tensors(path) is not None
    assert len(walks) == 2
    path.write_bytes(_model_with_tensors() + b"\0")
    assert dateiart(path) == MODELL
    assert len(walks) == 3
