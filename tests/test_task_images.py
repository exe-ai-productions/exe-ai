"""Pictures a chat hands to the agent it sends off (app/task_images.py)."""

from __future__ import annotations

import time

import pytest

from app import task_images
from app.providers import MockProvider, mock_endpunkt
from app.providers.base import Werkzeugaufruf
from tests.conftest import png_bytes, provider_setzen
from tests.test_auftrag_werkzeug import StartRegistry, _agent_anlegen

URL = "https://example.com/mock.png"


def _yes(_path: str) -> bool:
    return True


def _data_url() -> str:
    import base64

    return "data:image/png;base64," + base64.b64encode(png_bytes()).decode()


# --- The field ----------------------------------------------------------------


def test_missing_or_empty_is_no_pictures():
    assert task_images.checked(None) == []
    assert task_images.checked([]) == []
    assert task_images.checked(["  ", URL]) == [URL]


def test_more_than_eight_is_refused():
    with pytest.raises(task_images.TaskImagesInvalid, match="At most 8"):
        task_images.checked([URL] * 9)
    assert len(task_images.checked([URL] * 8)) == 8


def test_a_field_that_is_no_list_of_strings_is_refused():
    with pytest.raises(task_images.TaskImagesInvalid):
        task_images.checked([1, 2])


# --- Reading ------------------------------------------------------------------


def test_a_picture_in_the_shared_folder_is_read_and_others_are_skipped(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "shot.png").write_bytes(png_bytes())
    (shared / "notes.txt").write_text("no picture", encoding="utf-8")
    outside = tmp_path / "outside.png"
    outside.write_bytes(png_bytes())

    images = task_images.prepare(
        ["shot.png", "missing.png", "notes.txt", str(outside), URL, _data_url(), "data:text/plain,x"],
        [str(shared)],
        tmp_path / "data",
        _yes,
    )

    assert [(i.kind, bool(i.data_url)) for i in images] == [
        ("path", True), ("url", False), ("data", True),
    ]
    assert images[0].source == str((shared / "shot.png").resolve())
    assert images[0].data_url.startswith("data:image/png;base64,")


def test_without_a_shared_folder_no_local_picture_is_read(tmp_path):
    (tmp_path / "shot.png").write_bytes(png_bytes())

    assert task_images.prepare([str(tmp_path / "shot.png")], [], tmp_path, _yes) == []


def test_an_unexpected_failure_leaves_plain_text(tmp_path, monkeypatch):
    def broken(*_args):
        raise KeyError("boom")

    monkeypatch.setattr(task_images, "_local", broken)

    assert task_images.prepare(["shot.png"], [str(tmp_path)], tmp_path, _yes) == []


# --- What the model gets ------------------------------------------------------


def _three():
    return [
        task_images.TaskImage(source="/w/shot.png", kind="path", data_url="data:image/png;base64,AA"),
        task_images.TaskImage(source=URL, kind="url"),
        task_images.TaskImage(source="data:image/png;base64,BB", kind="data", data_url="data:image/png;base64,BB"),
    ]


def test_a_model_that_sees_gets_the_pictures():
    urls, lines = task_images.for_model(_three(), vision=True)

    assert urls == ["data:image/png;base64,AA", "data:image/png;base64,BB"]
    # An address is named, never fetched.
    assert lines == [f"[Image attached: {URL}]"]


def test_silent_a_model_without_eyes_gets_lines_and_no_pictures():
    urls, lines = task_images.for_model(_three(), vision=False)

    assert urls == []
    assert lines == ["[Image attached at: /w/shot.png]", f"[Image attached: {URL}]"]


# --- From the chat to the run --------------------------------------------------


def _write_agent(config, folders: list[str]) -> None:
    from pathlib import Path

    agents = Path(config.app.agenten_verzeichnis)
    agents.mkdir(parents=True, exist_ok=True)
    listed = "".join(f"\n  - {folder}" for folder in folders)
    (agents / "bote.md").write_text(
        "---\nmodel: test\nmax_rounds: 1\ntools: []\n"
        + (f"folders:{listed}\n" if folders else "")
        + "---\n\nDeliver things.\n",
        encoding="utf-8",
    )


def _send_with_images(
    client, chat_id, config, tmp_path, images, *, vision: bool, registry=None,
    share: bool = True, agent_folders: list[str] | None = None,
):
    shared = tmp_path / "shared"
    shared.mkdir(exist_ok=True)
    (shared / "shot.png").write_bytes(png_bytes())
    if share:
        client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(shared)]})
    _write_agent(config, agent_folders or [])
    client.app.state.werkzeuge = registry or _JudgingRegistry(client, "ja")
    client.app.state.config.features.mcp = True
    client.app.state.discovery.zustaende["test"].endpunkt.capabilities.vision = vision
    provider = provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["Good."],
            werkzeugaufrufe=[
                Werkzeugaufruf(
                    id="a1", name="start_job",
                    argumente={"agent": "bote", "task": "Collect the notes.", "images": images},
                )
            ],
        ),
    )
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "send it off"},
    )
    deadline = time.time() + 8
    while time.time() < deadline:
        firsts = [
            n
            for a in provider.alle_anfragen
            for n in a.nachrichten
            if n.role == "user" and "Collect the notes." in (n.content or "")
        ]
        if firsts:
            return firsts[0], client.get("/api/v1/jobs").json()
        time.sleep(0.05)
    raise AssertionError("the job never sent its first request")


def test_pictures_from_the_chat_travel_in_the_runs_first_message(
    client, chat_id, config, tmp_path
):
    first, _jobs = _send_with_images(
        client, chat_id, config, tmp_path, ["shot.png", URL], vision=True
    )

    assert len(first.bild_urls) == 1
    assert first.bild_urls[0].startswith("data:image/png;base64,")
    assert f"[Image attached: {URL}]" in first.content


def test_a_run_whose_model_cannot_see_is_told_where_the_picture_is(
    client, chat_id, config, tmp_path
):
    first, _jobs = _send_with_images(client, chat_id, config, tmp_path, ["shot.png"], vision=False)

    assert first.bild_urls == []
    assert f"[Image attached at: {(tmp_path / 'shared' / 'shot.png').resolve()}]" in first.content


def test_too_many_pictures_start_no_job(client, chat_id, config, tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    _agent_anlegen(config)
    client.app.state.werkzeuge = StartRegistry(client, True, None)
    client.app.state.config.features.mcp = True
    provider = provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["Good."],
            werkzeugaufrufe=[
                Werkzeugaufruf(
                    id="a1", name="start_job",
                    argumente={"agent": "bote", "task": "Collect.", "images": [URL] * 9},
                )
            ],
        ),
    )
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "send it off"},
    )

    assert client.get("/api/v1/jobs").json() == []
    tool = [n for n in provider.letzte_anfrage.nachrichten if n.role == "tool"][-1]
    assert "At most 8" in tool.content


def test_a_picture_the_permission_check_refuses_is_not_read(tmp_path, monkeypatch):
    """Refused as read_file would be refused: skipped, and never opened."""
    from app.tools import datei_lesen

    (tmp_path / "shot.png").write_bytes(png_bytes())
    asked: list[str] = []
    read: list = []
    monkeypatch.setattr(datei_lesen, "_bild_bereiten", lambda *a: read.append(a) or ("x", 0))

    def no(path: str) -> bool:
        asked.append(path)
        return False

    assert task_images.prepare(["shot.png"], [str(tmp_path)], tmp_path, no) == []
    assert asked == [str((tmp_path / "shot.png").resolve())]
    assert read == []


def test_a_file_that_is_no_picture_is_never_read_whole(tmp_path, monkeypatch):
    """Extension and signature decide before the file is read, as in
    read_file: a large file named .png that is no picture is not loaded."""
    from app.tools import datei_lesen

    (tmp_path / "fake.png").write_bytes(b"not a picture" * 1000)
    (tmp_path / "shot.gif").write_bytes(png_bytes())
    read: list = []
    monkeypatch.setattr(datei_lesen, "_bild_bereiten", lambda *a: read.append(a) or ("x", 0))

    assert task_images.prepare(["fake.png", "shot.gif"], [str(tmp_path)], tmp_path, _yes) == []
    assert read == []


class _JudgingRegistry(StartRegistry):
    """The chat's start registry with a permission check: ``answer`` for
    every read_file, and every call it judged."""

    def __init__(self, client, answer: str):
        super().__init__(client, True, None)
        self.answer = answer
        self.judged: list[tuple] = []

    def urteil(self, name, argumente=None, ordner=None, herkunft="chat", agent=None,
               rules_of=None):
        from app.berechtigungen import Urteil

        self.judged.append((name, (argumente or {}).get("path"), list(ordner or []),
                            herkunft, rules_of))
        return Urteil(self.answer)


def test_the_chat_refuses_a_picture_its_rules_refuse(client, chat_id, config, tmp_path):
    registry = _JudgingRegistry(client, "nein")
    first, _jobs = _send_with_images(
        client, chat_id, config, tmp_path, ["shot.png"], vision=True, registry=registry
    )

    assert first.bild_urls == []
    shot = str((tmp_path / "shared" / "shot.png").resolve())
    assert registry.judged == [("read_file", shot, [str(tmp_path / "shared")], "agent", "chat")]


def test_pictures_resolve_in_the_folders_the_run_gets(client, chat_id, config, tmp_path):
    """A chat sharing no folder hands the run the agent's own folders: the
    picture is found there, not in the chat's own folder."""
    agent_folder = tmp_path / "agent-folder"
    agent_folder.mkdir()
    (agent_folder / "shot.png").write_bytes(png_bytes())
    first, _jobs = _send_with_images(
        client, chat_id, config, tmp_path, ["shot.png"], vision=False,
        share=False, agent_folders=[str(agent_folder)],
    )

    assert f"[Image attached at: {(agent_folder / 'shot.png').resolve()}]" in first.content


# --- The payload ceiling ------------------------------------------------------


def test_a_picture_above_the_payload_ceiling_is_named_not_attached(tmp_path, monkeypatch):
    """Still too large after the smaller copy: it is not sent, and the
    model reads which picture is missing and why — whether it can see or
    not. The number is the entry's place in the list as given, counting the
    one skipped before it."""
    from app.tools import datei_lesen

    (tmp_path / "huge.png").write_bytes(png_bytes())
    huge = "data:image/png;base64," + "A" * task_images.MAX_PAYLOAD_BYTES
    monkeypatch.setattr(datei_lesen, "_bild_bereiten", lambda *_a: (huge, 0))

    images = task_images.prepare(
        ["missing.png", huge, "huge.png"], [str(tmp_path)], tmp_path, _yes
    )

    for vision in (True, False):
        urls, lines = task_images.for_model(images, vision)
        assert urls == []
        assert len(lines) == 2
        assert lines[0].startswith("[Image number 2 of the images, given inline, was not attached")
        assert f"at {(tmp_path / 'huge.png').resolve()} was not attached" in lines[1]
        assert "larger than 20 MB" in lines[1]


def test_an_inline_picture_is_not_said_to_have_been_made_smaller():
    """A data URL travels as given; its sentence claims no smaller copy."""
    huge = "data:image/png;base64," + "A" * task_images.MAX_PAYLOAD_BYTES

    _urls, (line,) = task_images.for_model(
        task_images.prepare([huge], [], None, _yes), vision=True
    )

    assert "made smaller" not in line
    assert "larger than 20 MB" in line
    assert line.startswith("[Image number 1 of the images, given inline, was not attached")


def test_silent_a_picture_under_the_ceiling_gets_no_sentence(tmp_path):
    (tmp_path / "shot.png").write_bytes(png_bytes())

    images = task_images.prepare(["shot.png", _data_url()], [str(tmp_path)], tmp_path, _yes)
    urls, lines = task_images.for_model(images, vision=True)

    assert len(urls) == 2
    assert lines == []
