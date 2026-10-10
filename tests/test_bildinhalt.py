"""Reading a model file's own header to tell what it actually is.

No real model is downloaded — a handful of bytes in the exact shape GGUF
and safetensors use is the whole test. What matters is that the reader
trusts only the header's own content, never the file's name or extension,
and that anything it cannot identify with confidence answers "unbekannt"
rather than a guess.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from app import bildinhalt
from app.bildinhalt import BILDMODELL, TEXTVERSTEHER, UNBEKANNT, VAE, sorte

_ZEICHENKETTE = 8
_U32 = 4


def _gguf_bytes(paare: list[tuple[str, int, object]], *, version: int = 3) -> bytes:
    """The bytes of a minimal GGUF header — same shape as
    tests/test_ggufmtp.py's own builder, kept separate since the two
    modules' readers are separate too."""
    kopf = bytearray(b"GGUF")
    kopf += struct.pack("<I", version)
    kopf += struct.pack("<Q", 0)  # tensor count — irrelevant to this reader
    kopf += struct.pack("<Q", len(paare))
    for schluessel, art, wert in paare:
        roh = schluessel.encode("utf-8")
        kopf += struct.pack("<Q", len(roh)) + roh
        kopf += struct.pack("<I", art)
        if art == _ZEICHENKETTE:
            rohwert = wert.encode("utf-8")
            kopf += struct.pack("<Q", len(rohwert)) + rohwert
        elif art == _U32:
            kopf += struct.pack("<I", wert)
        else:
            raise ValueError(f"unhandled type in this test's own builder: {art}")
    return bytes(kopf)


def _safetensors_bytes(namen: list[str]) -> bytes:
    """The bytes of a minimal safetensors header — real tensor data is
    never read by the classifier, so the values here are placeholders."""
    kopf = {n: {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]} for n in namen}
    rohkopf = json.dumps(kopf).encode("utf-8")
    return struct.pack("<Q", len(rohkopf)) + rohkopf


def _datei(tmp_path: Path, name: str, inhalt: bytes) -> Path:
    pfad = tmp_path / name
    pfad.write_bytes(inhalt)
    return pfad


# --- GGUF ------------------------------------------------------------------


def test_gguf_flux_architektur_ist_ein_bildmodell(tmp_path):
    inhalt = _gguf_bytes([("general.architecture", _ZEICHENKETTE, "flux")])
    assert sorte(_datei(tmp_path, "modell.gguf", inhalt)) == BILDMODELL


def test_gguf_llama_architektur_ist_ein_textversteher(tmp_path):
    inhalt = _gguf_bytes([("general.architecture", _ZEICHENKETTE, "llama")])
    assert sorte(_datei(tmp_path, "llm.gguf", inhalt)) == TEXTVERSTEHER


@pytest.mark.parametrize("architektur", ["qwen3vl", "qwen2vl", "mistral3"])
def test_gguf_vl_und_mistral_encoder_sind_textversteher(tmp_path, architektur):
    """The encoders of Krea 2 (Qwen3-VL), Qwen-Image (Qwen2.5-VL) and
    ERNIE-Image (Ministral 3), as llama.cpp names them."""
    inhalt = _gguf_bytes([("general.architecture", _ZEICHENKETTE, architektur)])
    assert sorte(_datei(tmp_path, "encoder.gguf", inhalt)) == TEXTVERSTEHER


def test_gguf_t5_architektur_ist_ein_textversteher(tmp_path):
    inhalt = _gguf_bytes([("general.architecture", _ZEICHENKETTE, "t5")])
    assert sorte(_datei(tmp_path, "t5.gguf", inhalt)) == TEXTVERSTEHER


def test_gguf_unbekannte_architektur_bleibt_unbekannt(tmp_path):
    inhalt = _gguf_bytes([("general.architecture", _ZEICHENKETTE, "irgendwas-neues")])
    assert sorte(_datei(tmp_path, "modell.gguf", inhalt)) == UNBEKANNT


def test_gguf_ohne_architekturschluessel_bleibt_unbekannt(tmp_path):
    inhalt = _gguf_bytes([("general.file_type", _U32, 2)])
    assert sorte(_datei(tmp_path, "modell.gguf", inhalt)) == UNBEKANNT


def test_ein_abgeschnittener_gguf_kopf_ist_kein_absturz(tmp_path):
    voll = _gguf_bytes([("general.architecture", _ZEICHENKETTE, "flux")])
    inhalt = voll[: len(voll) - 5]
    assert sorte(_datei(tmp_path, "modell.gguf", inhalt)) == UNBEKANNT


# --- safetensors -------------------------------------------------------


def test_safetensors_vae_namen_werden_erkannt(tmp_path):
    inhalt = _safetensors_bytes([
        "encoder.down.0.block.0.norm1.weight",
        "decoder.up.0.block.0.norm1.weight",
        "post_quant_conv.weight",
    ])
    assert sorte(_datei(tmp_path, "vae.safetensors", inhalt)) == VAE


def test_safetensors_clip_namen_werden_erkannt(tmp_path):
    inhalt = _safetensors_bytes([
        "text_model.embeddings.token_embedding.weight",
        "text_model.encoder.layers.0.self_attn.k_proj.weight",
    ])
    assert sorte(_datei(tmp_path, "clip_l.safetensors", inhalt)) == TEXTVERSTEHER


def test_safetensors_t5_namen_werden_erkannt(tmp_path):
    inhalt = _safetensors_bytes([
        "shared.weight",
        "encoder.block.0.layer.0.SelfAttention.k.weight",
    ])
    assert sorte(_datei(tmp_path, "t5xxl.safetensors", inhalt)) == TEXTVERSTEHER


def test_ein_vollstaendiger_t5_ist_kein_vae(tmp_path):
    """T5 is itself an encoder-decoder model — a complete T5 (not just the
    encoder-only distribution the Flux ecosystem ships) carries both an
    encoder. and a decoder. prefix, the same shape the VAE rule looks for."""
    inhalt = _safetensors_bytes([
        "shared.weight",
        "encoder.block.0.layer.0.SelfAttention.q.weight",
        "decoder.block.0.layer.0.SelfAttention.q.weight",
    ])
    assert sorte(_datei(tmp_path, "t5_voll.safetensors", inhalt)) == TEXTVERSTEHER


def test_safetensors_diffusionsmodell_namen_werden_erkannt(tmp_path):
    inhalt = _safetensors_bytes([
        "double_blocks.0.img_attn.qkv.weight",
        "single_blocks.0.linear1.weight",
    ])
    assert sorte(_datei(tmp_path, "flux1-dev.safetensors", inhalt)) == BILDMODELL


def test_safetensors_voller_sdxl_checkpoint_ist_ein_bildmodell(tmp_path):
    inhalt = _safetensors_bytes([
        "model.diffusion_model.input_blocks.0.0.weight",
        "cond_stage_model.transformer.text_model.embeddings.token_embedding.weight",
    ])
    assert sorte(_datei(tmp_path, "sdxl.safetensors", inhalt)) == BILDMODELL


def test_safetensors_llm_ist_ein_textversteher(tmp_path):
    """A Qwen2.5-VL, Qwen3 or Ministral encoder in safetensors: its first
    decoder layer under ``model.layers.0.self_attn.`` (measured on the
    files sd.cpp's docs name)."""
    inhalt = _safetensors_bytes([
        "model.embed_tokens.weight", "model.layers.0.self_attn.q_proj.weight",
        "visual.blocks.0.attn.qkv.weight",
    ])
    assert sorte(_datei(tmp_path, "qwen_2.5_vl_7b.safetensors", inhalt)) == TEXTVERSTEHER


def test_ein_bildmodell_mit_eigenem_sprachmodell_ist_kein_textversteher(tmp_path):
    """The silence probe: HiDream-O1 carries its language model under
    ``model.language_model.`` and stays a model to draw with."""
    inhalt = _safetensors_bytes([
        "model.language_model.layers.0.self_attn.q_proj.weight", "model.x_embedder.proj1.weight",
    ])
    assert sorte(_datei(tmp_path, "hidream.safetensors", inhalt)) != TEXTVERSTEHER


def test_safetensors_unbekannte_namen_bleiben_unbekannt(tmp_path):
    inhalt = _safetensors_bytes(["irgendein.tensor.weight"])
    assert sorte(_datei(tmp_path, "modell.safetensors", inhalt)) == UNBEKANNT


def test_ein_abgeschnittener_safetensors_kopf_ist_kein_absturz(tmp_path):
    voll = _safetensors_bytes(["post_quant_conv.weight"])
    inhalt = voll[: len(voll) - 5]
    assert sorte(_datei(tmp_path, "vae.safetensors", inhalt)) == UNBEKANNT


def test_ein_kaputter_safetensors_kopf_ohne_gueltiges_json_ist_kein_absturz(tmp_path):
    kaputt = b"das ist kein json"
    inhalt = struct.pack("<Q", len(kaputt)) + kaputt
    assert sorte(_datei(tmp_path, "modell.safetensors", inhalt)) == UNBEKANNT


# --- Neither format, or nothing at all --------------------------------


def test_weder_gguf_noch_safetensors_bleibt_unbekannt(tmp_path):
    pfad = _datei(tmp_path, "modell.safetensors", b"weder das eine noch das andere")
    assert sorte(pfad) == UNBEKANNT


def test_eine_winzige_datei_ist_kein_absturz(tmp_path):
    assert sorte(_datei(tmp_path, "modell.safetensors", b"x")) == UNBEKANNT


def test_eine_fehlende_datei_ist_kein_absturz(tmp_path):
    assert sorte(tmp_path / "gibtsnicht.safetensors") == UNBEKANNT


# --- GGUF lengths the file cannot hold -------------------------------------

_ARRAY = 9


def _header_with_raw_value(key: str, kind: int, raw: bytes) -> bytes:
    """A header whose first key carries ``raw`` as its value bytes, as they
    are, followed by an architecture this program knows."""
    header = bytearray(b"GGUF") + struct.pack("<I", 3) + struct.pack("<Q", 0)
    header += struct.pack("<Q", 2)
    arch = b"flux"
    for name, value_kind, value in (
        (key, kind, raw),
        ("general.architecture", _ZEICHENKETTE, struct.pack("<Q", len(arch)) + arch),
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


def test_a_gguf_array_count_near_two_to_the_64_is_a_broken_header(tmp_path):
    from app import bildinhalt

    huge = struct.pack("<I", _U32) + struct.pack("<Q", 2**64 - 1)
    path = _datei(tmp_path, "broken.gguf", _header_with_raw_value("tokenizer.ggml.token_type", _ARRAY, huge))
    assert _answers_quickly(sorte, path) == UNBEKANNT
    assert _answers_quickly(bildinhalt.tensors, path) is None


def test_a_gguf_string_longer_than_the_file_is_a_broken_header(tmp_path, monkeypatch):
    """Refused before the read: nothing larger than the file is ever asked
    of it."""
    from app import bildinhalt, ggufmtp

    asked: list[int] = []
    read_exactly = ggufmtp.genau

    def recording(file, count):
        asked.append(count)
        return read_exactly(file, count)

    monkeypatch.setattr(ggufmtp, "genau", recording)
    too_long = struct.pack("<Q", 2**40) + b"x"
    path = _datei(tmp_path, "broken.gguf", _header_with_raw_value("general.name", _ZEICHENKETTE, too_long))
    assert _answers_quickly(sorte, path) == UNBEKANNT
    assert _answers_quickly(bildinhalt.tensors, path) is None
    assert max(asked) <= path.stat().st_size


def test_a_large_honest_gguf_array_is_still_skipped(tmp_path):
    """The silence probe: a vocabulary-sized array in front of the
    architecture is passed as before."""
    count = 50_000
    array = struct.pack("<I", _U32) + struct.pack("<Q", count) + b"\x00" * (4 * count)
    path = _datei(tmp_path, "honest.gguf", _header_with_raw_value("tokenizer.ggml.token_type", _ARRAY, array))
    assert sorte(path) == BILDMODELL


def test_a_large_honest_gguf_string_array_is_still_skipped(tmp_path):
    """The silence probe for the other branch: a vocabulary of strings in
    front of the architecture is passed as before."""
    count = 50_000
    words = b"".join(struct.pack("<Q", 6) + f"t{i:05d}".encode() for i in range(count))
    array = struct.pack("<I", _ZEICHENKETTE) + struct.pack("<Q", count) + words
    path = _datei(tmp_path, "honest.gguf", _header_with_raw_value("tokenizer.ggml.tokens", _ARRAY, array))
    assert sorte(path) == BILDMODELL


def test_a_gguf_string_array_count_the_file_cannot_hold_is_a_broken_header(tmp_path):
    from app import bildinhalt

    huge = struct.pack("<I", _ZEICHENKETTE) + struct.pack("<Q", 2**63)
    path = _datei(tmp_path, "broken.gguf", _header_with_raw_value("tokenizer.ggml.tokens", _ARRAY, huge))
    assert _answers_quickly(sorte, path) == UNBEKANNT
    assert _answers_quickly(bildinhalt.tensors, path) is None


def test_tensors_still_reads_an_honest_header_behind_a_vocabulary(tmp_path):
    from app import bildinhalt

    count = 50_000
    words = b"".join(struct.pack("<Q", 6) + f"t{i:05d}".encode() for i in range(count))
    array = struct.pack("<I", _ZEICHENKETTE) + struct.pack("<Q", count) + words
    path = _datei(tmp_path, "honest.gguf", _header_with_raw_value("tokenizer.ggml.tokens", _ARRAY, array))
    assert bildinhalt.tensors(path) == ({}, "flux")


# --- GGUF strings that are not valid UTF-8 ---------------------------------


def _vocabulary_with_invalid_token() -> bytes:
    tokens = [b"tok0", b"\xff\xfe", b"tok2"]
    return (
        struct.pack("<I", _ZEICHENKETTE)
        + struct.pack("<Q", len(tokens))
        + b"".join(struct.pack("<Q", len(token)) + token for token in tokens)
    )


def test_a_gguf_token_that_is_not_utf8_before_the_architecture_is_skipped(tmp_path):
    """A skipped string is passed by its length — one vocabulary token that
    is not valid UTF-8 no longer makes the whole header unreadable."""
    from app import bildinhalt

    path = _datei(
        tmp_path, "vocabulary.gguf",
        _header_with_raw_value("tokenizer.ggml.tokens", _ARRAY, _vocabulary_with_invalid_token()),
    )
    assert sorte(path) == BILDMODELL
    assert bildinhalt.tensors(path) == ({}, "flux")


def test_a_plain_gguf_string_that_is_not_utf8_before_the_architecture_is_skipped(tmp_path):
    from app import bildinhalt

    raw = b"name\xff"
    path = _datei(
        tmp_path, "name.gguf",
        _header_with_raw_value("general.name", _ZEICHENKETTE, struct.pack("<Q", len(raw)) + raw),
    )
    assert sorte(path) == BILDMODELL
    assert bildinhalt.tensors(path) == ({}, "flux")


def test_an_invalid_byte_in_the_architecture_itself_still_makes_it_unreadable(tmp_path):
    """The silence probe: the value that is actually read is still decoded —
    an invalid byte there leaves the header unreadable, as before."""
    from app import bildinhalt

    arch = b"flux\xff"
    header = bytearray(b"GGUF") + struct.pack("<I", 3) + struct.pack("<Q", 0) + struct.pack("<Q", 2)
    for name, kind, value in (
        (b"tokenizer.ggml.tokens", _ARRAY, _vocabulary_with_invalid_token()),
        (b"general.architecture", _ZEICHENKETTE, struct.pack("<Q", len(arch)) + arch),
    ):
        header += struct.pack("<Q", len(name)) + name + struct.pack("<I", kind) + value
    path = _datei(tmp_path, "arch.gguf", bytes(header))
    assert sorte(path) == UNBEKANNT
    assert bildinhalt.tensors(path) is None


# --- GGUF headers cut off inside the last skipped value ---------------------


def _tensor_entry(name: str) -> bytes:
    encoded = name.encode()
    return (
        struct.pack("<Q", len(encoded)) + encoded
        + struct.pack("<I", 2) + struct.pack("<QQ", 16, 16)
        + struct.pack("<I", 0) + struct.pack("<Q", 0)
    )


def _with_tensors(header: bytes, names: tuple[str, ...]) -> bytes:
    """``header`` from ``_gguf_bytes`` with its tensor count set and the
    tensor table appended."""
    return header[:8] + struct.pack("<Q", len(names)) + header[16:] + b"".join(_tensor_entry(n) for n in names)


def test_a_gguf_header_cut_inside_a_last_short_string_is_a_broken_header(tmp_path):
    """A skipped string is passed by seeking, and seeking past the end does
    not fail — the cut-off header must still not read as whole."""
    from app import bildinhalt

    whole = _gguf_bytes([
        ("general.architecture", _ZEICHENKETTE, "flux"),
        ("general.name", _ZEICHENKETTE, "abcdef"),
    ])
    path = _datei(tmp_path, "cut-string.gguf", whole[:-2])
    assert bildinhalt.tensors(path) is None


def test_a_gguf_header_cut_inside_a_last_fixed_size_value_is_a_broken_header(tmp_path):
    from app import bildinhalt

    whole = _gguf_bytes([
        ("general.architecture", _ZEICHENKETTE, "flux"),
        ("general.alignment", _U32, 32),
    ])
    path = _datei(tmp_path, "cut-value.gguf", whole[:-2])
    assert bildinhalt.tensors(path) is None


def test_a_gguf_header_cut_inside_the_last_tensors_type_and_offset_is_a_broken_header(tmp_path):
    from app import bildinhalt

    whole = _with_tensors(_gguf_bytes([("general.architecture", _ZEICHENKETTE, "flux")]), ("a.weight", "b.weight"))
    path = _datei(tmp_path, "cut-tensor.gguf", whole[:-5])
    assert bildinhalt.tensors(path) is None


def test_a_whole_gguf_header_still_reads_as_before(tmp_path):
    """The silence probe: a header that ends exactly where its last value
    does is read as before."""
    from app import bildinhalt

    header = _gguf_bytes([
        ("general.architecture", _ZEICHENKETTE, "flux"),
        ("general.name", _ZEICHENKETTE, "abcdef"),
        ("general.alignment", _U32, 32),
    ])
    plain = _datei(tmp_path, "whole.gguf", header)
    with_tensors = _datei(tmp_path, "whole-tensors.gguf", _with_tensors(header, ("a.weight",)))
    assert bildinhalt.tensors(plain) == ({}, "flux")
    assert bildinhalt.tensors(with_tensors) == ({"a.weight": [16, 16]}, "flux")
    assert sorte(plain) == BILDMODELL


def test_a_foreign_gguf_key_that_is_not_utf8_before_the_architecture_is_passed(tmp_path):
    """Keys are compared as bytes, never decoded: a key nobody looks for
    with an invalid byte in it no longer hides the architecture behind it."""
    from app import bildinhalt

    arch = b"flux"
    header = bytearray(b"GGUF") + struct.pack("<I", 3) + struct.pack("<Q", 0) + struct.pack("<Q", 2)
    for name, kind, value in (
        (b"general.n\xffame", _ZEICHENKETTE, struct.pack("<Q", 1) + b"x"),
        (b"general.architecture", _ZEICHENKETTE, struct.pack("<Q", len(arch)) + arch),
    ):
        header += struct.pack("<Q", len(name)) + name + struct.pack("<I", kind) + value
    path = _datei(tmp_path, "foreign-key.gguf", bytes(header))
    assert sorte(path) == BILDMODELL
    assert bildinhalt.tensors(path) == ({}, "flux")


def test_a_gguf_file_ending_inside_the_tensor_table_is_unreadable(tmp_path):
    """The whole header is read before anything is answered: the
    architecture at its front no longer vouches for a file that ends inside
    its tensor table."""
    from app import bildinhalt

    whole = _with_tensors(_gguf_bytes([("general.architecture", _ZEICHENKETTE, "flux")]), ("a.weight", "b.weight"))
    path = _datei(tmp_path, "cut-table.gguf", whole[:-5])
    assert sorte(path) == UNBEKANNT
    assert bildinhalt.tensors(path) is None
    assert bildinhalt.family(path) is None


def test_a_whole_gguf_file_with_a_tensor_table_is_still_read(tmp_path):
    """The silence probe: the same header, whole, answers as before."""
    from app import bildinhalt

    whole = _with_tensors(_gguf_bytes([("general.architecture", _ZEICHENKETTE, "flux")]), ("a.weight", "b.weight"))
    path = _datei(tmp_path, "whole-table.gguf", whole)
    assert sorte(path) == BILDMODELL
    assert bildinhalt.tensors(path) == ({"a.weight": [16, 16], "b.weight": [16, 16]}, "flux")


def test_a_gguf_key_that_appears_twice_is_a_broken_header(tmp_path):
    from app import bildinhalt

    path = _datei(tmp_path, "twice.gguf", _gguf_bytes([
        ("general.architecture", _ZEICHENKETTE, "flux"),
        ("general.architecture", _ZEICHENKETTE, "flux"),
    ]))
    assert sorte(path) == UNBEKANNT
    assert bildinhalt.tensors(path) is None


def test_a_file_not_readable_for_a_moment_is_read_the_next_time(tmp_path, monkeypatch):
    """A file held open by another program cannot be read for a moment; that
    answer is not remembered, and the next look reads it."""
    import builtins

    from app import bildinhalt

    path = _datei(tmp_path, "held.gguf", _gguf_bytes([("general.architecture", _ZEICHENKETTE, "flux")]))
    real_open = builtins.open

    def held(file, *args, **kwargs):
        if str(file) == str(path):
            raise PermissionError("held by another program")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", held)
    assert bildinhalt.tensors(path) is None
    monkeypatch.setattr(builtins, "open", real_open)
    assert bildinhalt.tensors(path) == ({}, "flux")


# --- A checkpoint that brings no text encoder --------------------------------


def test_a_checkpoint_without_text_encoders_is_told_by_its_header(tmp_path: Path):
    """SD3.5 Large as a checkpoint: the diffusion model beside the VAE, no
    text encoder — its family's encoders are passed beside it."""
    bare = _datei(tmp_path, "sd3.5_large.safetensors", _safetensors_bytes([
        "model.diffusion_model.joint_blocks.0.x_block.attn.qkv.weight",
        "first_stage_model.decoder.conv_in.weight",
    ]))
    assert bildinhalt.checkpoint_without_text_encoders(bare) is True
    assert bildinhalt.standalone_diffusion_model(bare) is False


def test_a_checkpoint_with_its_encoders_and_a_kit_part_are_not_one(tmp_path: Path):
    """Silence: a checkpoint that carries its text encoders (each of the
    three places a checkpoint holds them), a standalone diffusion model and
    a file that is no model are told apart."""
    for number, encoder in enumerate((
        "text_encoders.clip_l.transformer.text_model.embeddings.token_embedding.weight",
        "cond_stage_model.transformer.text_model.embeddings.token_embedding.weight",
        "conditioner.embedders.0.transformer.text_model.embeddings.token_embedding.weight",
    )):
        whole = _datei(tmp_path, f"whole{number}.safetensors", _safetensors_bytes([
            "model.diffusion_model.joint_blocks.0.x_block.attn.qkv.weight",
            "first_stage_model.decoder.conv_in.weight", encoder,
        ]))
        assert bildinhalt.checkpoint_without_text_encoders(whole) is False
    part = _datei(tmp_path, "part.safetensors", _safetensors_bytes([
        "model.diffusion_model.joint_blocks.0.x_block.attn.qkv.weight",
    ]))
    assert bildinhalt.checkpoint_without_text_encoders(part) is False
    assert bildinhalt.checkpoint_without_text_encoders(_datei(tmp_path, "note.txt", b"x")) is False

