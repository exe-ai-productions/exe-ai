"""The video tool: the model asks for a short video, from words or from a
picture it names.

``draw_video`` goes the drawing tool's way — it asks this service's own
picture route, this time for a video. These tests hold which model it takes,
with whose values, what it answers the model with, and that the tool is
nowhere while no video model is installed.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import bildmodellwerte, grundprompt
from app.bildrunner import Bildrunner
from app.tools import bild_werkzeug, video_tool
from app.tools.aufbau import registry_bauen
from app.tools.registry import WerkzeugRegistry, WerkzeugVerboten
from tests.conftest import Antwort, Bilddienst
from tests.test_video import _safetensors

PICTURE = "picture.safetensors"
VIDEO = "video.safetensors"
SECOND = "second.safetensors"
# What the route answers a video model's start with (``/bild/vorgaben``).
START = {
    "family": "wan22_ti2v", "breite": 832, "hoehe": 480, "schritte": 30, "cfg": 5.0,
    "sampler": "euler", "flow_shift": 5.0, "video_frames": 81, "fps": 24,
    "vae_format": "", "rng": "", "switches": {}, "model_args": "",
}


def _service(window: dict | None = None, *, models=None, families=None, **more) -> Bilddienst:
    """The picture service with one picture model and one video model, and
    the chat's picture window standing at ``window``."""
    families = families or {PICTURE: "sdxl", VIDEO: "wan22_ti2v"}
    return Bilddienst(
        {"c1": window if window is not None else {"modell": PICTURE}},
        modelle=models or list(families), familien=families,
        vorgaben=lambda model: dict(START), **more,
    )


def _registry(tmp_path: Path, *, video_ready=lambda: True) -> WerkzeugRegistry:
    return WerkzeugRegistry(
        [], bild_zugang=("http://x", tmp_path / "pictures", "testschluessel"),
        video_ready=video_ready,
    )


def _call(tmp_path, monkeypatch, service, arguments=None, *, folders=(), **more) -> str:
    """One call of the tool through the registry, as a chat makes it."""
    seen: dict = {}

    def client(timeout, headers):
        seen["timeout"] = timeout
        return service

    monkeypatch.setattr(video_tool.httpx, "AsyncClient", client)
    service.client_made_with = seen
    return asyncio.run(
        _registry(tmp_path).ausfuehren(
            video_tool.WERKZEUG_NAME, {"prompt": "a dog runs", **(arguments or {})},
            ordner=[str(folder) for folder in folders],
            **{"chat_id": "c1", "antwort_id": "answer-1", **more},
        )
    )


# --- Which model, with whose values ------------------------------------------


def test_a_video_from_words_runs_on_the_video_model_s_own_start(tmp_path, monkeypatch):
    """The window stands at a picture model: the one installed video model
    makes the video, with its family's start — never with the size, steps or
    guidance of the picture model. The route is asked for a video, the answer
    names the file's path, and the window is left as it stands."""
    service = _service({"modell": PICTURE, "breite": 1024, "hoehe": 1024, "schritte": 8, "cfg": 1})
    text = _call(tmp_path, monkeypatch, service)

    body = service.gezeichnet[-1]
    assert body["video"] is True and body["modell"] == VIDEO and body["familie"] == "wan22_ti2v"
    assert (body["breite"], body["hoehe"], body["schritte"], body["cfg"]) == (832, 480, 30, 5.0)
    assert (body["video_frames"], body["fps"]) == (81, 24)
    assert body["prompt"] == "a dog runs" and "startbild" not in body
    assert (body["chat_id"], body["lauf_kennung"]) == ("c1", "answer-1")
    assert text == (
        f"The video was made (model {VIDEO}, 832×480 pixels, 81 frames), is "
        f"attached to this answer and saved as {tmp_path / 'pictures' / 'out.png'}."
    )
    # Nothing was written anywhere but the draw itself.
    assert [url.rsplit("/", 1)[-1] for url, _ in service.aufrufe] == ["bild"]
    # A video has no time limit.
    assert service.client_made_with == {"timeout": None}


def test_the_window_s_own_video_model_runs_with_the_window_s_values(tmp_path, monkeypatch):
    """Two video models installed and the window stands at one of them: that
    one is taken, and what the person set at it wins over the model's start —
    the video's length among it. A start picture and a mask of the window
    never travel."""
    service = _service(
        {"modell": SECOND, "breite": 640, "hoehe": 384, "schritte": 12, "video_frames": "33",
         "startbild": "window.png", "maske": "mask.png"},
        families={PICTURE: "sdxl", VIDEO: "wan22_ti2v", SECOND: "wan22_ti2v"},
    )
    text = _call(tmp_path, monkeypatch, service)
    body = service.gezeichnet[-1]
    assert body["modell"] == SECOND
    assert (body["breite"], body["hoehe"], body["schritte"], body["video_frames"]) == (640, 384, 12, 33)
    assert body["fps"] == 24  # not set at the window: the model's start
    assert "startbild" not in body and "maske" not in body
    assert f"model {SECOND}" in text and "33 frames" in text


def test_among_several_video_models_nothing_chooses_by_itself(tmp_path, monkeypatch):
    """Silence: several video models and the window names none of them — no
    video, and the model reads what the user has to do."""
    service = _service(families={PICTURE: "sdxl", VIDEO: "wan22_ti2v", SECOND: "ltx"})
    assert _call(tmp_path, monkeypatch, service) == video_tool.MODEL_NOT_CHOSEN
    assert service.gezeichnet == []


def test_a_kind_the_model_cannot_make_is_refused_in_words(tmp_path, monkeypatch):
    """A family that makes video from words only is not handed a picture, and
    one that starts from a picture is not asked without one."""
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "dog.png").write_bytes(b"PNG")
    words_only = _service(families={VIDEO: "hunyuan_video"})
    text = _call(tmp_path, monkeypatch, words_only, {"image": str(shared / "dog.png")}, folders=[shared])
    assert text == (
        "The video was not made: the video model in use — HunyuanVideo 1.5 — makes "
        "videos from words only. Call again without an image."
    )
    from_a_picture = _service(families={VIDEO: "wan22_i2v"})
    text = _call(tmp_path, monkeypatch, from_a_picture)
    assert text == (
        "The video was not made: the video model in use — Wan 2.2 I2V A14B — needs a "
        "picture to start from. Pass its path as image."
    )
    assert words_only.gezeichnet == [] and from_a_picture.gezeichnet == []
    assert words_only.handed_in == []


# --- From a picture -----------------------------------------------------------


def test_a_video_from_a_picture_starts_from_its_content(tmp_path, monkeypatch):
    """The named picture goes to the service as its bytes and the request
    names it as the first frame; it is not copied into the pictures folder."""
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "dog.png").write_bytes(b"PNG-bytes-of-a-dog")
    service = _service()
    text = _call(tmp_path, monkeypatch, service, {"image": str(shared / "dog.png")}, folders=[shared])
    assert service.handed_in == [b"PNG-bytes-of-a-dog"]
    body = service.gezeichnet[-1]
    assert body["startbild"] == "handed-in.png" and body["video"] is True
    assert "started from dog.png" in text
    assert not (tmp_path / "pictures").exists()


def test_a_picture_outside_the_run_s_folders_is_refused(tmp_path, monkeypatch):
    """Silence: a path outside the run's folders is refused before anything
    is asked of the service; a file that is no picture is answered in words,
    said of the video."""
    shared, outside = tmp_path / "shared", tmp_path / "outside"
    shared.mkdir()
    outside.mkdir()
    (outside / "secret.png").write_bytes(b"x")
    (shared / "notes.txt").write_text("no picture")
    service = _service()
    with pytest.raises(WerkzeugVerboten):
        _call(tmp_path, monkeypatch, service, {"image": str(outside / "secret.png")}, folders=[shared])
    assert service.aufrufe == []
    text = _call(tmp_path, monkeypatch, service, {"image": str(shared / "notes.txt")}, folders=[shared])
    assert text == "The video was not made: notes.txt is not a PNG, JPEG or WebP picture."
    assert service.gezeichnet == []


# --- What the model reads -----------------------------------------------------


def test_in_a_job_the_video_is_saved_and_named_but_not_attached(tmp_path, monkeypatch):
    """A job has no answer a video could hang on: the sentence names the
    path in the pictures folder and says it is not attached."""
    service = _service(jobs={"job-1": "c1"})
    text = _call(
        tmp_path, monkeypatch, service, chat_id="job-1", antwort_id=None, herkunft="agent",
    )
    assert f"saved as {tmp_path / 'pictures' / 'out.png'}" in text
    assert "it is not attached to your report" in text and "is attached to this answer" not in text
    assert "deliver it with" not in text

    # With the delivery tool the job is told how to pass the video on.
    registry = _registry(tmp_path)
    monkeypatch.setattr(registry, "_deliver_with", lambda origin, agent: "deliver_file")
    monkeypatch.setattr(video_tool.httpx, "AsyncClient", lambda timeout, headers: service)
    text = asyncio.run(registry.ausfuehren(
        video_tool.WERKZEUG_NAME, {"prompt": "a dog runs"}, chat_id="job-1", herkunft="agent",
    ))
    assert text.endswith(
        "it is not attached to your report. When it is meant for the user as a result "
        "of this job, deliver it with deliver_file, passing this path."
    )
    assert "lauf_kennung" not in service.gezeichnet[-1]


def test_a_refusal_of_the_route_reaches_the_model_as_the_route_wrote_it(tmp_path, monkeypatch):
    service = _service(answers={"/bild": Antwort({"detail": "The VAE is missing."}, 400)})
    assert _call(tmp_path, monkeypatch, service) == (
        "The video could not be made: The VAE is missing."
    )


def test_a_failed_call_on_the_way_is_said_of_the_video(tmp_path, monkeypatch):
    """The calls shared with the drawing tool speak of what this tool makes:
    a window that could not be read stops the video, in the video's words."""
    service = _service(
        answers={"/settings/resolved/bildfenster": Antwort({"detail": "No such chat."}, 500)}
    )
    assert _call(tmp_path, monkeypatch, service) == "The video could not be made: No such chat."
    assert service.gezeichnet == []


def test_a_stopped_run_asks_for_no_video(tmp_path, monkeypatch):
    stop = asyncio.Event()
    stop.set()
    service = _service()
    assert _call(tmp_path, monkeypatch, service, abbruch=stop) == (
        "The video was not made: the run was stopped."
    )
    assert service.gezeichnet == []


def test_the_sentences_the_model_reads_stand_word_for_word():
    """The fixed sentences of both tools that paint, each in full: a change
    to one of them is a change somebody decided, never a slip."""
    seen = "do not describe its contents afterwards — you have not seen it."
    assert bild_werkzeug.IN_CHAT == (
        "The finished picture appears in your answer by itself, and the result names "
        "its file and path; " + seen
    )
    assert bild_werkzeug.IN_JOB == (
        "The finished picture is saved in the pictures folder, which the user sees "
        "under Images, and the answer names its file; " + seen
    )
    assert bild_werkzeug.INPUT_PICTURE["description"] == (
        "Optional: the path of a picture to draw from — a file you may read, in a "
        "shared folder or in the pictures folder. With it, the picture is drawn from "
        "that one instead of from scratch."
    )
    assert video_tool.IN_CHAT == (
        "The finished video appears in your answer by itself, and the result names "
        "its file and path; " + seen
    )
    assert video_tool.IN_JOB == (
        "The finished video is saved in the pictures folder, which the user sees "
        "under Images, and the answer names its file; " + seen
    )
    assert video_tool.MODEL_NOT_CHOSEN == (
        "The video was not made: several video models are installed, and this chat "
        "has none of them chosen. Ask the user to choose one under Images › Video."
    )
    assert video_tool.NO_VIDEO_MODEL == (
        "No video model is installed. The user can add one under Images or from the "
        "catalogue."
    )
    # Silence probe: the sentences nobody asked to change are what they were.
    assert video_tool.UNUSABLE_ANSWER == (
        "The video could not be made: the picture service sent an answer that could "
        "not be used."
    )
    assert video_tool.werkzeug_beschreibung().beschreibung == (
        "Makes a short video with the video model installed on this machine — from "
        "words alone, or from a picture when you pass its path as image. Write the "
        "prompt in ENGLISH: what is seen and how it moves. A video takes minutes and "
        "has no time limit; it ends when it is finished or when the user stops the "
        "run. " + video_tool.IN_CHAT
    )
    fields = video_tool.werkzeug_beschreibung().schema["properties"]
    assert fields["prompt"]["description"] == (
        "What the video shows and how it moves. Write it in English."
    )
    assert fields["negative_prompt"]["description"] == "What must stay out of the video. Optional."
    assert fields["image"]["description"] == (
        "Optional: the path of a picture the video starts from — a file you may read, "
        "in a shared folder or in the pictures folder."
    )


def test_without_the_painter_the_model_reads_where_the_user_fetches_it(tmp_path, monkeypatch):
    service = Bilddienst(modelle=[], programm_da=False)
    assert _call(tmp_path, monkeypatch, service) == (
        "No image generator is installed. The user can fetch it under Images (plus menu)."
    )
    assert service.gezeichnet == []


def test_the_description_says_what_the_model_has_to_know():
    in_chat = video_tool.werkzeug_beschreibung()
    in_job = video_tool.werkzeug_beschreibung(in_chat=False)
    assert in_chat.name == "draw_video" and in_chat.server == bild_werkzeug.SERVER_NAME
    assert in_chat.schema["required"] == ["prompt"]
    assert set(in_chat.schema["properties"]) == {"prompt", "negative_prompt", "image"}
    assert "the result names its file and path" in in_chat.beschreibung
    assert "has no time limit" in in_chat.beschreibung
    assert "appears in your answer" not in in_job.beschreibung
    assert "saved in the pictures folder" in in_job.beschreibung


# --- The tool is nowhere without a video model --------------------------------


def _offered(registry: WerkzeugRegistry) -> set[str]:
    return {tool["function"]["name"] for tool in registry.als_openai_werkzeuge()}


def test_without_a_video_model_the_tool_is_nowhere(tmp_path):
    """Silence: no video model installed — the tool is in no list, has no
    server and runs for nobody. The drawing tool beside it is untouched."""
    for not_there in (
        _registry(tmp_path, video_ready=lambda: False),
        _registry(tmp_path, video_ready=None),
    ):
        assert video_tool.WERKZEUG_NAME not in not_there.builtin_names()
        assert video_tool.WERKZEUG_NAME not in _offered(not_there)
        assert video_tool.WERKZEUG_NAME not in {e["name"] for e in not_there.uebersicht()}
        assert not_there.server_von(video_tool.WERKZEUG_NAME) == ""
        assert bild_werkzeug.WERKZEUG_NAME in _offered(not_there)
        with pytest.raises(WerkzeugVerboten):
            asyncio.run(not_there.ausfuehren(video_tool.WERKZEUG_NAME, {"prompt": "x"}))
    # Without the picture service there is no video tool either.
    assert video_tool.WERKZEUG_NAME not in _offered(WerkzeugRegistry([], video_ready=lambda: True))


def test_a_server_s_tool_of_the_same_name_is_never_taken_over(tmp_path):
    """The video tool comes and goes with the model folder, so its name is
    kept free even while no video model is installed — otherwise the name
    would stand twice the day one arrives. A registry that can never have
    the tool takes the server's."""
    from app.tools.mcp_client import MCPWerkzeug
    from app.tools.registry import ServerEintrag

    class _Client:
        werkzeuge = [MCPWerkzeug(name="draw_video", beschreibung="", schema={}, server="other")]

    not_yet = _registry(tmp_path, video_ready=lambda: False)
    not_yet._werkzeuge_uebernehmen(ServerEintrag(name="other"), _Client())
    assert "draw_video" not in not_yet.namen()
    never = _registry(tmp_path, video_ready=None)
    never._werkzeuge_uebernehmen(ServerEintrag(name="other"), _Client())
    assert "draw_video" in never.namen()


def _clock_forward(folder: Path) -> None:
    """Moves the folder's change time one second ahead by hand. Windows
    stamps a change from a clock that ticks every 15.6 ms, and a test of
    this file runs inside one tick: a file written right after the folder was
    made left the folder's time exactly as it was (measured), and the cache
    read "unchanged" off a folder that had changed. The program reads the
    time; the test says when it moved."""
    stamp = folder.stat().st_mtime_ns + 1_000_000_000
    os.utime(folder, ns=(stamp, stamp))


def test_the_folder_is_read_again_only_when_it_changed(tmp_path, monkeypatch):
    """The registry asks at every listing: the folder's own change time
    answers, and its files are looked at again only after something in it
    arrived or left."""
    from app import bildrunner

    folder = tmp_path / "models"
    folder.mkdir()
    looked: list[Path] = []
    real = bildrunner.modelle
    monkeypatch.setattr(
        video_tool.bildrunner, "modelle", lambda f: looked.append(f) or real(f)
    )
    for _ in range(3):
        assert video_tool.video_model_installed(folder) is False
    assert len(looked) == 1
    _safetensors(folder / "wan.safetensors", {
        "blocks.0.cross_attn.norm_k.weight": [1536],
        "patch_embedding.weight": [1536, 16, 1, 2, 2],
    })
    _clock_forward(folder)
    for _ in range(3):
        assert video_tool.video_model_installed(folder) is True
    assert len(looked) == 2
    (folder / "wan.safetensors").unlink()
    assert video_tool.video_model_installed(folder) is False


def test_with_a_video_model_the_tool_is_in_every_list(tmp_path):
    there = _registry(tmp_path)
    assert video_tool.WERKZEUG_NAME in there.builtin_names()
    assert video_tool.WERKZEUG_NAME in _offered(there)
    assert video_tool.WERKZEUG_NAME in {e["name"] for e in there.uebersicht()}
    assert there.server_von(video_tool.WERKZEUG_NAME) == video_tool.SERVER_NAME
    assert not there.braucht_bestaetigung(video_tool.WERKZEUG_NAME, {"prompt": "x"})
    # An agent's own list and the switch in the settings leave it out.
    assert video_tool.WERKZEUG_NAME not in {
        tool["function"]["name"] for tool in there.als_openai_werkzeuge(nur={"draw_image"})
    }


def test_the_model_folder_decides_whether_a_video_model_is_installed(tmp_path):
    """Read from the files' headers: a picture model alone is no video
    model, a Wan model beside it is one."""
    folder = tmp_path / "models"
    folder.mkdir()
    assert video_tool.video_model_installed(folder) is False
    assert video_tool.video_model_installed(tmp_path / "missing") is False
    _safetensors(folder / "sd15.safetensors", {
        "model.diffusion_model.input_blocks.0.0.weight": [320, 4, 3, 3],
        "model.diffusion_model.middle_block.1.norm.weight": [1280],
        "model.diffusion_model.output_blocks.7.1.norm.weight": [640],
        "cond_stage_model.transformer.text_model.embeddings.token_embedding.weight": [49408, 768],
    })
    assert video_tool.video_model_installed(folder) is False
    _safetensors(folder / "wan.safetensors", {
        "blocks.0.cross_attn.norm_k.weight": [1536],
        "patch_embedding.weight": [1536, 16, 1, 2, 2],
    })
    _clock_forward(folder)
    assert video_tool.video_model_installed(folder) is True


def test_the_service_s_own_registry_looks_into_its_model_folder(client: TestClient, config, tmp_path):
    """The registry the service builds asks its own model folder, at each
    listing: the tool appears when a video model arrives while it runs."""
    folder = tmp_path / "models"
    folder.mkdir()
    config.app.bildmodelle_verzeichnis = str(folder)
    registry = registry_bauen(client.app, config)
    assert video_tool.WERKZEUG_NAME not in registry.builtin_names()
    _safetensors(folder / "wan.safetensors", {
        "blocks.0.cross_attn.norm_k.weight": [1536],
        "patch_embedding.weight": [1536, 16, 1, 2, 2],
    })
    _clock_forward(folder)
    assert video_tool.WERKZEUG_NAME in registry.builtin_names()


# --- The runs treat it as a tool that paints ----------------------------------


def test_the_stop_signal_goes_to_the_video_tool_too():
    """A video outlives its answer like a picture: the run's stop is handed
    to both tools that paint — and to the shell, whose command outlives it
    the same way — and to no other."""
    from app.api.v1.generierung import _werkzeug_ausfuehren

    class _Register:
        def __init__(self):
            self.calls: dict[str, dict] = {}

        async def ausfuehren(self, name, argumente, bild_senke=None, **more):
            self.calls[name] = more
            return "ok"

    register = _Register()
    signal = asyncio.Event()

    async def run():
        for name in (
            video_tool.WERKZEUG_NAME, bild_werkzeug.WERKZEUG_NAME, "run_command", "read_file",
        ):
            await _werkzeug_ausfuehren(
                register, SimpleNamespace(name=name, argumente={}), "en", abbruch=signal
            )

    asyncio.run(run())
    assert register.calls[video_tool.WERKZEUG_NAME]["abbruch"] is signal
    assert register.calls[bild_werkzeug.WERKZEUG_NAME]["abbruch"] is signal
    assert register.calls["run_command"]["abbruch"] is signal
    assert "abbruch" not in register.calls["read_file"]


def test_the_overview_names_videos_only_for_a_run_that_has_the_tool():
    with_it = grundprompt.bauen(kann=grundprompt.faehigkeiten({"draw_image", "draw_video"}))
    assert "make short videos with the video model on this machine" in with_it
    without = grundprompt.bauen(kann=grundprompt.faehigkeiten({"draw_image"}))
    assert "videos" not in without and "draw pictures" in without


# --- Against the service itself ------------------------------------------------


class _ToTheService:
    """``httpx.AsyncClient``'s shape, answered by the service under test."""

    def __init__(self, client: TestClient, headers: dict):
        self._client = client
        self._headers = headers

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def get(self, url, params=None, **_):
        return self._client.get(url, params=params, headers=self._headers)

    async def post(self, url, json=None, **more):
        if json is None:
            return self._client.post(
                url, params=more.get("params"), content=more.get("content"),
                headers={**self._headers, **(more.get("headers") or {})},
            )
        return self._client.post(url, json=json, headers=self._headers)


@pytest.fixture
def wan(config, client: TestClient, monkeypatch, tmp_path: Path) -> dict:
    """A Wan model with its parts in the folder and a painter that writes a
    file instead of drawing; ``wan["jobs"]`` holds what it was asked for."""
    folder = tmp_path / "bildmodelle"
    folder.mkdir()
    config.app.bildmodelle_verzeichnis = str(folder)
    _safetensors(folder / "wan.safetensors", {
        "blocks.0.cross_attn.norm_k.weight": [1536],
        "patch_embedding.weight": [1536, 16, 1, 2, 2],
    })
    _safetensors(folder / "text_encoders" / "umt5.safetensors", {
        "encoder.block.0.layer.0.SelfAttention.q.weight": [4096, 4096],
        "shared.weight": [256384, 4096],
    })
    _safetensors(folder / "vae" / "wan_vae.safetensors", {
        "decoder.conv1.weight": [384, 16, 3, 3, 3], "encoder.conv1.weight": [96, 3, 3, 3, 3],
    })
    state: dict = {"jobs": []}

    def make(self, job, target):
        state["jobs"].append(job)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"video")
        return target

    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))
    monkeypatch.setattr(Bildrunner, "erzeugen", make)
    monkeypatch.setattr(
        video_tool.httpx, "AsyncClient",
        lambda timeout, headers: _ToTheService(client, headers),
    )
    return state


def test_the_service_makes_the_video_and_the_path_points_at_the_file(
    wan, client: TestClient, config, chat_id, tmp_path
):
    """The whole way, the painter alone standing in: the route is asked for a
    video of the installed video model, the file lies where the answer says,
    and it stands in the run of the answer being written."""
    from app.speicherorte import ort

    repositories = client.app.state.repositories
    repositories.messages.speichern(chat_id=chat_id, role="user", content="Make a video.")
    answer = repositories.messages.speichern(chat_id=chat_id, role="assistant", content="")
    start = tmp_path / "start.png"
    start.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 16)

    # Nothing tells Wan's video VAE from its header alone: until the model
    # was given one, the route refuses — and the model reads why, in English.
    refused = asyncio.run(
        video_tool.ausfuehren(
            {"prompt": "a dog runs"}, "/api/v1", ort(config, "images"),
            client.app.state.sitzungsschluessel, antwort_id=answer.id, chat_id=chat_id,
        )
    )
    assert refused.startswith("The video could not be made: "), refused
    assert "VAE" in refused and wan["jobs"] == []
    bildmodellwerte.set_part(repositories, "wan.safetensors", "vae", "wan_vae.safetensors")

    for picture in (None, start):
        text = asyncio.run(
            video_tool.ausfuehren(
                {"prompt": "a dog runs"}, "/api/v1", ort(config, "images"),
                client.app.state.sitzungsschluessel,
                antwort_id=answer.id, chat_id=chat_id, input_picture=picture,
            )
        )
        assert text.startswith("The video was made (model wan.safetensors"), text
        path = Path(text.rsplit("saved as ", 1)[1].rstrip("."))
        assert path.is_file() and path.parent == ort(config, "images")
        job = wan["jobs"][-1]
        assert job.video is True
        assert (job.startbild is not None) == (picture is not None)
    run = repositories.messages.run_row(chat_id=chat_id, lauf_kennung=answer.id)
    assert run is not None and len(run.bild_dateien()) == 2
