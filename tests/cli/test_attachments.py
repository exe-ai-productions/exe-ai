"""``@path`` in a message: the file or the image that goes with it, the
completion of a path behind ``@`` and a dropped file in the field. The
service is the stand-in; nothing is drawn."""

from __future__ import annotations

import io
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from prompt_toolkit.document import Document

from cli import attachments, chat
from cli.interfaces import Asker, Context
from cli.main import main
from cli.texts import Texts
from tests.cli.conftest import RecordingRenderer, RecordingScreen
from tests.cli.stub_service import StubService, model


class Silent(Asker):
    """An asker that is never asked: nothing here puts a question."""


def texts() -> Texts:
    return Texts("en")


@pytest.fixture
def folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The folder the client runs in, with a note, a picture, a folder and
    a file with a blank in its name."""
    work = tmp_path / "work"
    work.mkdir()
    (work / "notiz.txt").write_text("hello", encoding="utf-8")
    (work / "bild.png").write_bytes(b"\x89PNG-bytes")
    (work / "mein bild.png").write_bytes(b"\x89PNG-two")
    (work / "sub").mkdir()
    (work / "example.com").write_text("not a mail address", encoding="utf-8")
    monkeypatch.chdir(work)
    monkeypatch.setenv("HOME", str(work))
    return work


@pytest.fixture
def tool(
    stub: StubService,
    wire: Callable[[httpx.Client], Context],
    stub_http: httpx.Client,
    folder: Path,
) -> Context:
    seeing = model("local", "Local Model")
    seeing["capabilities"] = {"vision": True}
    stub.models = [seeing]
    context = wire(stub_http)
    context.renderer = RecordingRenderer()
    context.screen = RecordingScreen(context)
    context.asker = Silent()
    return context


def sent(stub: StubService) -> dict[str, Any]:
    assert len(stub.sent) == 1, stub.sent
    return stub.sent[0]


# --- What goes along ----------------------------------------------------------------------


def test_a_file_goes_to_the_chat_as_a_document_and_the_mention_stays_in_the_text(tool, stub):
    chat.send(tool, "read @notiz.txt please")
    assert stub.uploads == [("/documents", "notiz.txt", "", b"hello")]
    message = sent(stub)
    assert message["content"] == "read @notiz.txt please"
    assert message["dokumente"] == ["doc-1"]
    assert "bilder" not in message
    assert tool.renderer.notices == []


def test_an_image_goes_up_as_a_picture_where_the_model_sees(tool, stub):
    chat.send(tool, "what is on @bild.png")
    assert stub.uploads == [("/images", "picture-1.png", "image/png", b"\x89PNG-bytes")]
    assert sent(stub)["bilder"] == ["picture-1.png"]
    assert "dokumente" not in sent(stub)


def test_an_image_for_a_model_that_cannot_see_says_so_and_the_message_goes(tool, stub):
    tool.session.models[0]["capabilities"] = {}
    chat.send(tool, "what is on @bild.png")
    assert stub.uploads == []
    assert tool.renderer.notices == [texts().t("fehler.kein_vision")]
    assert "bilder" not in sent(stub)
    assert sent(stub)["content"] == "what is on @bild.png"


@pytest.mark.parametrize("written", [r"@mein\ bild.png", '@"mein bild.png"'])
def test_a_blank_in_the_name_is_written_with_a_backslash_or_in_quotes(tool, stub, written):
    chat.send(tool, f"look at {written}")
    assert [upload[3] for upload in stub.uploads] == [b"\x89PNG-two"]
    assert sent(stub)["content"] == f"look at {written}"


def test_the_home_folder_is_counted(tool, stub, folder):
    chat.send(tool, "read @~/notiz.txt")
    assert [upload[1] for upload in stub.uploads] == ["notiz.txt"]


def test_a_sentence_that_ends_right_behind_the_path_still_finds_the_file(tool, stub):
    chat.send(tool, "have a look at @notiz.txt.")
    assert [upload[1] for upload in stub.uploads] == ["notiz.txt"]


def test_the_same_file_named_twice_goes_once(tool, stub):
    chat.send(tool, "@notiz.txt and again @notiz.txt")
    assert len(stub.uploads) == 1
    assert sent(stub)["dokumente"] == ["doc-1"]


# --- What is left as text -----------------------------------------------------------------


def test_a_path_that_is_not_there_stays_text_without_a_word(tool, stub):
    chat.send(tool, "read @gibtsnicht.txt")
    assert stub.uploads == []
    assert tool.renderer.notices == []
    assert sent(stub)["content"] == "read @gibtsnicht.txt"
    assert "dokumente" not in sent(stub) and "bilder" not in sent(stub)


def test_a_folder_behind_the_at_stays_text(tool, stub):
    chat.send(tool, "list @sub")
    assert stub.uploads == []
    assert tool.renderer.notices == []


def test_an_address_with_an_at_inside_a_word_is_no_mention(tool, stub):
    # A file called ``example.com`` lies in the folder: the ``@`` stands
    # inside the word, so it is not looked for.
    chat.send(tool, "write to name@example.com")
    assert stub.uploads == []


def test_a_message_without_an_at_carries_neither_pictures_nor_documents(tool, stub):
    chat.send(tool, "just words")
    message = sent(stub)
    assert "bilder" not in message and "dokumente" not in message
    assert stub.uploads == []


def test_a_document_the_service_refuses_stands_with_its_sentence_and_the_message_goes(tool, stub):
    stub.refuse_upload["/documents"] = (415, "This file type is not supported for reading.")
    chat.send(tool, "read @notiz.txt")
    assert tool.renderer.notices == ["This file type is not supported for reading."]
    assert "dokumente" not in sent(stub)
    assert sent(stub)["content"] == "read @notiz.txt"


def test_a_picture_the_service_refuses_stands_with_its_sentence_and_the_message_goes(tool, stub):
    stub.refuse_upload["/images"] = (415, "Only PNG, JPEG or WebP")
    chat.send(tool, "see @bild.png and read @notiz.txt")
    assert tool.renderer.notices == ["Only PNG, JPEG or WebP"]
    assert "bilder" not in sent(stub)
    assert sent(stub)["dokumente"] == ["doc-1"]


def test_exe_p_takes_a_mention_as_text(stub, folder, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    stub.models = [model("local", "Local Model")]
    assert main(["-p", "read @notiz.txt", "--lang", "en"], http=stub.http(),
                prefs_path=tmp_path / "cli.json") == 0
    assert stub.uploads == []
    assert "dokumente" not in stub.sent[0]


# --- The completion behind @ ----------------------------------------------------------------


def complete(typed: str) -> list[tuple[str, int]]:
    found = attachments.MentionCompleter().get_completions(Document(typed), None)  # type: ignore[arg-type]
    return [(completion.text, completion.start_position) for completion in found]


def test_tab_behind_at_no_completes_the_file(folder):
    assert complete("read @no") == [("notiz.txt", -2)]


def test_a_blank_in_a_completed_name_is_written_with_a_backslash(folder):
    assert complete("see @mein") == [("mein\\ bild.png", -4)]


def test_a_folder_is_completed_with_a_slash_and_comes_first(folder):
    assert complete("@")[0] == ("sub/", -0)
    (folder / "sub" / "inner.txt").write_text("x", encoding="utf-8")
    assert complete("@sub/") == [("sub/inner.txt", -4)]


def test_a_hidden_file_is_offered_only_for_a_dot(folder):
    (folder / ".secret").write_text("x", encoding="utf-8")
    assert all(not text.startswith(".") for text, _ in complete("@"))
    assert complete("@.s") == [(".secret", -2)]


def test_the_home_folder_is_completed_too(folder):
    assert ("~/notiz.txt", -3) in complete("@~/n")


def test_nothing_is_completed_without_an_at_or_inside_a_word(folder):
    assert complete("no") == []
    assert complete("name@no") == []
    assert complete("/he") == []


# --- A dropped file -------------------------------------------------------------------------


def test_a_dropped_path_becomes_a_mention(folder):
    path = str(folder / "notiz.txt")
    assert attachments.paths_as_mentions(path) == f"@{path} "


def test_a_dropped_path_with_a_blank_is_written_with_a_backslash(folder):
    dropped = str(folder / "mein bild.png")
    # A terminal writes the blank with a backslash, or the path in quotes.
    for typed in (dropped.replace(" ", "\\ "), f"'{dropped}'"):
        assert attachments.paths_as_mentions(typed) == "@" + dropped.replace(" ", "\\ ") + " "


def test_several_dropped_files_become_several_mentions(folder):
    one, two = str(folder / "notiz.txt"), str(folder / "bild.png")
    assert attachments.paths_as_mentions(f"{one} {two}") == f"@{one} @{two} "


@pytest.mark.parametrize(
    "pasted", ["Hello there, this is a sentence", "notiz.txt", "/no/such/file.txt", "", "  "]
)
def test_any_other_pasted_text_stays_as_it_is(folder, pasted):
    assert attachments.paths_as_mentions(pasted) is None


def test_a_dropped_folder_is_no_file(folder):
    assert attachments.paths_as_mentions(str(folder / "sub")) is None


def test_a_file_dropped_on_the_running_screen_stands_in_the_field_as_a_mention(
    stub, folder, tmp_path, monkeypatch
):
    from tests.cli.program import Run, run_client
    from tests.cli.stub_service import eventually

    stub.models = [model("local", "Local Model")]
    path = str(folder / "notiz.txt")

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        run.parts()
        eventually(lambda: stub.watchers == 1)
        # A terminal that has bracketed paste sends the dropped path
        # between these two marks.
        type_in(f"\x1b[200~{path}\x1b[201~\r")
        eventually(lambda: stub.sent)
        type_in("/quit\r")

    with stub.http() as http:
        run = run_client(http, tmp_path, monkeypatch, drive)
    assert run.code == 0
    assert stub.sent[0]["content"] == f"@{path}"
    assert [upload[1] for upload in stub.uploads] == ["notiz.txt"]
    assert stub.sent[0]["dokumente"] == ["doc-1"]
