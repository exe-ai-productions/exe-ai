"""The copy of a model's chat template: read out of the GGUF header, written
once into the data folder, opened in the text editor, shown in the file
manager — and never written over once the user has it.

The GGUF files here are a header and nothing else, written by hand: a few
metadata keys and no tensors.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import chat_template_copy, ggufmtp
from app.config import Config

TEMPLATE = "{% for m in messages %}<|{{ m.role }}|>{{ m.content }}\n{% endfor %}"


def _text(wert: bytes) -> bytes:
    return struct.pack("<Q", len(wert)) + wert


def gguf(pfad: Path, *, template: bytes | None = TEMPLATE.encode(), keys_after: bool = True) -> Path:
    """A GGUF v3 file with an architecture, a vocabulary-like array ahead of
    the template (the reader must walk past it) and, when given, the
    template."""
    eintraege = [
        _text(b"general.architecture") + struct.pack("<I", 8) + _text(b"llama"),
        _text(b"tokenizer.ggml.tokens") + struct.pack("<I", 9) + struct.pack("<IQ", 8, 2)
        + _text(b"a") + _text(b"b"),
    ]
    if template is not None:
        eintraege.append(_text(b"tokenizer.chat_template") + struct.pack("<I", 8) + _text(template))
    if keys_after:
        eintraege.append(_text(b"general.name") + struct.pack("<I", 8) + _text(b"m"))
    kopf = b"GGUF" + struct.pack("<I", 3) + struct.pack("<QQ", 0, len(eintraege))
    pfad.write_bytes(kopf + b"".join(eintraege))
    return pfad


def test_the_reader_finds_the_template_whatever_stands_around_it(tmp_path: Path):
    assert ggufmtp.chat_template(gguf(tmp_path / "a.gguf")) == TEMPLATE
    assert ggufmtp.chat_template(gguf(tmp_path / "b.gguf", keys_after=False)) == TEMPLATE


def test_a_file_without_a_template_or_without_a_header_answers_none(tmp_path: Path):
    assert ggufmtp.chat_template(gguf(tmp_path / "a.gguf", template=None)) is None
    (tmp_path / "b.gguf").write_bytes(b"not a gguf at all")
    assert ggufmtp.chat_template(tmp_path / "b.gguf") is None
    assert ggufmtp.chat_template(gguf(tmp_path / "c.gguf", template=b"  \n")) is None


def test_a_byte_that_is_no_utf8_does_not_make_the_header_unreadable(tmp_path: Path):
    """The model list reads every file's header; the template is read by its
    own pass and never changes what those readers answer."""
    datei = gguf(tmp_path / "a.gguf", template=b"{{ x }}\xff{{ y }}")
    assert ggufmtp.chat_template(datei) == "{{ x }}�{{ y }}"
    assert ggufmtp.dateiart(datei) == ggufmtp.MODELL


def test_the_other_readers_do_not_carry_the_template(tmp_path: Path):
    """A long text kept for every model of the folder on every listing is
    what this pass exists to avoid."""
    header = ggufmtp.read_header(gguf(tmp_path / "a.gguf"))
    assert header is not None and ggufmtp.CHAT_TEMPLATE_SCHLUESSEL not in header[0]


def test_the_copy_is_made_once_byte_for_byte_and_then_left_alone(tmp_path: Path, config: Config):
    datei = gguf(tmp_path / "m.gguf", template=b"line one\r\nline two\n")
    kopie = chat_template_copy.ensure_copy(config, "m.gguf", datei)
    assert kopie == config.datenverzeichnis / "chat_templates" / "m.gguf.jinja"
    assert kopie.read_bytes() == b"line one\r\nline two\n", "no line ending of this system"
    kopie.write_text("my own words", encoding="utf-8")
    assert chat_template_copy.ensure_copy(config, "m.gguf", datei) == kopie
    assert kopie.read_text(encoding="utf-8") == "my own words"


def test_a_model_without_a_template_makes_no_copy(tmp_path: Path, config: Config):
    datei = gguf(tmp_path / "m.gguf", template=None)
    with pytest.raises(chat_template_copy.TemplateError) as fehler:
        chat_template_copy.ensure_copy(config, "m.gguf", datei)
    assert fehler.value.reason == "keine_vorlage"
    assert not (config.datenverzeichnis / "chat_templates").exists()


def test_show_points_at_the_copy_where_there_is_one_else_at_the_model(tmp_path: Path, config: Config):
    datei = gguf(tmp_path / "m.gguf")
    assert chat_template_copy.file_to_show(config, "m.gguf", datei) == datei
    kopie = chat_template_copy.ensure_copy(config, "m.gguf", datei)
    assert chat_template_copy.file_to_show(config, "m.gguf", datei) == kopie


# --- The two doors of the row, on both servers --------------------------------------

ROUTEN = ("/api/v1/runner", "/api/v1/agentenmodell")


@pytest.fixture
def geoeffnet(monkeypatch) -> dict:
    """What the doors asked the system to do, instead of doing it."""
    getan: dict = {"editor": [], "zeigen": []}
    monkeypatch.setattr(
        "app.chat_template_doors.open_file_in_editor", lambda pfad: getan["editor"].append(Path(pfad))
    )
    monkeypatch.setattr("app.chat_template_doors.show_file", lambda pfad: getan["zeigen"].append(Path(pfad)))
    return getan


@pytest.mark.parametrize("route", ROUTEN)
def test_edit_makes_the_copy_opens_it_and_answers_where_it_lies(
    client: TestClient, config: Config, geoeffnet: dict, route: str
):
    ordner = Path(config.app.modelle_verzeichnis)
    ordner.mkdir(parents=True, exist_ok=True)
    gguf(ordner / "m.gguf")
    antwort = client.post(f"{route}/chat-template/edit", json={"modell": "m.gguf"})
    assert antwort.status_code == 200, antwort.text
    kopie = Path(antwort.json()["pfad"])
    assert kopie == config.datenverzeichnis / "chat_templates" / "m.gguf.jinja"
    assert kopie.read_text(encoding="utf-8") == TEMPLATE
    assert geoeffnet["editor"] == [kopie]
    # Asked again, the same file opens, with what the user wrote in it.
    kopie.write_text("mine", encoding="utf-8")
    client.post(f"{route}/chat-template/edit", json={"modell": "m.gguf"})
    assert kopie.read_text(encoding="utf-8") == "mine" and geoeffnet["editor"] == [kopie, kopie]


@pytest.mark.parametrize("route", ROUTEN)
def test_edit_takes_only_a_model_the_folder_lists(
    client: TestClient, config: Config, geoeffnet: dict, route: str
):
    ordner = Path(config.app.modelle_verzeichnis)
    ordner.mkdir(parents=True, exist_ok=True)
    gguf(ordner / "m.gguf", template=None)
    (ordner.parent / "outside.gguf").write_bytes(b"x")
    for name in ("nope.gguf", "../outside.gguf", "/etc/passwd"):
        assert client.post(f"{route}/chat-template/edit", json={"modell": name}).status_code == 404, name
    # Listed, but it carries no template: nothing is copied, nothing opens.
    antwort = client.post(f"{route}/chat-template/edit", json={"modell": "m.gguf"})
    assert antwort.status_code == 422
    assert geoeffnet["editor"] == [] and not (config.datenverzeichnis / "chat_templates").exists()


@pytest.mark.parametrize("route", ROUTEN)
def test_reveal_shows_the_copy_or_the_model_file(
    client: TestClient, config: Config, geoeffnet: dict, route: str
):
    ordner = Path(config.app.modelle_verzeichnis)
    ordner.mkdir(parents=True, exist_ok=True)
    gguf(ordner / "m.gguf")
    assert client.post(f"{route}/chat-template/reveal", json={"modell": "m.gguf"}).json() is True
    assert geoeffnet["zeigen"] == [ordner / "m.gguf"]
    kopie = chat_template_copy.copy_path(config, "m.gguf")
    kopie.parent.mkdir(parents=True)
    kopie.write_text("x", encoding="utf-8")
    client.post(f"{route}/chat-template/reveal", json={"modell": "m.gguf"})
    assert geoeffnet["zeigen"][-1] == kopie
    assert client.post(f"{route}/chat-template/reveal", json={"modell": "../x"}).status_code == 404
