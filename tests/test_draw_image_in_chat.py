"""A picture the model draws in a chat goes the picture window's way.

`draw_image` asks the same picture route the window asks, naming the chat and
the answer being written: the route writes every finished picture into that
answer's own run at once — the same run row, the same tiles — instead of the
tool saving it a second time, hanging it on the answer (each one replacing
the last) and filing the lot as a run only once the answer was over. A
service that died before that end kept the last picture only.

The tool is driven against the real service here, in-process: the drawing
itself is the only stand-in, everything between the call and the database is
the code that runs.
"""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.bildrunner import Bildrunner
from app.config import Config
from app.providers import MockProvider, mock_endpunkt
from app.providers.base import Werkzeugaufruf
from app import bildwahlen, image_families
from app.tools import bild_werkzeug
from app.tools.registry import WerkzeugRegistry, WerkzeugVerboten
from tests.conftest import Bilddienst, provider_setzen


class _ToTheService:
    """``httpx.AsyncClient``'s shape, answered by the service under test.

    The tool calls its own service over HTTP; here every call goes to the
    app the test client holds, session key included."""

    def __init__(self, client: TestClient):
        self._client = client

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def get(self, url, params=None, **_):
        return self._client.get(url, params=params)

    async def post(self, url, json=None, **_):
        return self._client.post(url, json=json)


@pytest.fixture
def painter(config: Config, client: TestClient, monkeypatch, tmp_path: Path):
    """A model in the folder and a painter that writes a file per picture.
    ``painter["crash_at"]`` makes that picture's drawing die halfway."""
    config.app.bildmodelle_verzeichnis = str(tmp_path / "bildmodelle")
    ordner = tmp_path / "bildmodelle"
    ordner.mkdir(parents=True)
    (ordner / "base.safetensors").write_bytes(b"x")
    # The chat names no model of its own: the picture server's default draws.
    client.app.state.repositories.einstellungen.setzen(
        "global", "bild_standardmodell", "base.safetensors",
    )
    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))
    state: dict = {"count": 0, "crash_at": None, "jobs": []}

    def draw(self, auftrag, ziel):
        state["count"] += 1
        state["jobs"].append(auftrag)
        if state["count"] == state["crash_at"]:
            raise RuntimeError("the service went down halfway through this picture")
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(b"PNG" + str(state["count"]).encode())
        return ziel

    monkeypatch.setattr(Bildrunner, "erzeugen", draw)
    monkeypatch.setattr(
        bild_werkzeug.httpx, "AsyncClient", lambda timeout, headers: _ToTheService(client)
    )
    return state


def _answer_being_written(client: TestClient, chat_id: str):
    """The user's question and the answer row a chat run writes into."""
    repositories = client.app.state.repositories
    repositories.messages.speichern(chat_id=chat_id, role="user", content="Draw two dogs.")
    return repositories.messages.speichern(chat_id=chat_id, role="assistant", content="")


def _draw(client: TestClient, tmp_path: Path, chat_id, antwort_id):
    return asyncio.run(
        bild_werkzeug.ausfuehren(
            {"prompt": "a dog"}, "/api/v1", tmp_path / "bilder",
            client.app.state.sitzungsschluessel,
            antwort_id=antwort_id, chat_id=chat_id,
        )
    )


def test_each_drawn_picture_joins_the_answers_run_at_once(painter, client, chat_id, tmp_path):
    """After the first picture the run already stands in the chat, with that
    one picture; the second takes the next place in the SAME row. No question
    row is written — the user's own message is the question."""
    antwort = _answer_being_written(client, chat_id)
    repositories = client.app.state.repositories

    text = _draw(client, tmp_path, chat_id, antwort.id)
    assert text.startswith("The image was generated"), text
    run = repositories.messages.run_row(chat_id=chat_id, lauf_kennung=antwort.id)
    assert run is not None
    assert run.art == "bildlauf"
    assert len(run.bild_dateien()) == 1
    assert run.stats["von"] == 1

    _draw(client, tmp_path, chat_id, antwort.id)
    run = repositories.messages.run_row(chat_id=chat_id, lauf_kennung=antwort.id)
    assert len(run.bild_dateien()) == 2
    assert run.stats["von"] == 2
    assert len(run.stats["seeds"]) == 2

    rows = repositories.messages.auflisten(chat_id=chat_id)
    assert [r.role for r in rows] == ["user", "assistant", "assistant"]
    assert rows[1].id == antwort.id and rows[1].bild is None
    assert rows[2].id == run.id


def test_the_answer_names_a_path_that_points_at_the_drawn_file(
    painter, client, config, chat_id
):
    """In a chat and in a job alike the model reads where the file lies —
    in the pictures folder, one of the folders every run may read. Only the
    chat's answer says the picture is attached."""
    from app import dokumentablage
    from app.speicherorte import ort
    from app.tools import grenzen

    antwort = _answer_being_written(client, chat_id)
    key = client.app.state.sitzungsschluessel
    in_chat = asyncio.run(bild_werkzeug.ausfuehren(
        {"prompt": "a dog"}, "/api/v1", ort(config, "images"), key,
        antwort_id=antwort.id, chat_id=chat_id,
    ))
    in_job = asyncio.run(bild_werkzeug.ausfuehren(
        {"prompt": "a dog"}, "/api/v1", ort(config, "images"), key,
        deliver_with="deliver_file",
    ))
    assert "attached to this response, and saved as " in in_chat
    assert in_job.endswith(
        " If this image is a deliverable for the user, deliver it using "
        "deliver_file with this path."
    )
    assert "is attached" not in in_job.replace("it is not attached", "")
    roots = grenzen.wurzeln(dokumentablage.program_folders(config))
    for text in (in_chat, in_job):
        named = text.split("saved as ", 1)[1].split(".png", 1)[0] + ".png"
        assert Path(named).is_file(), text
        assert grenzen.liegt_innerhalb(Path(named), roots)
    # Silence: a file beside the pictures folder is in none of those folders.
    assert not grenzen.liegt_innerhalb(ort(config, "images").parent / "other.png", roots)


def test_a_hard_end_in_the_second_picture_keeps_the_first(painter, client, chat_id, tmp_path):
    """The service dies while the second picture is drawn: the first one is
    in the chat already — written when it was finished, not at the answer's
    end, which never comes."""
    antwort = _answer_being_written(client, chat_id)
    painter["crash_at"] = 2

    _draw(client, tmp_path, chat_id, antwort.id)
    with pytest.raises(RuntimeError):
        _draw(client, tmp_path, chat_id, antwort.id)

    run = client.app.state.repositories.messages.run_row(
        chat_id=chat_id, lauf_kennung=antwort.id
    )
    assert run is not None
    assert len(run.bild_dateien()) == 1
    assert run.stats["von"] == 1


def test_a_run_key_of_another_chats_answer_is_a_single_picture(painter, client, chat_id):
    """The silence check of the answer rule: a run key that is an answer of a
    DIFFERENT chat names no answer here, and a single picture stays the
    single picture it always was — question and picture row."""
    other = client.post("/api/v1/chats", json={"title": "Other"}).json()["id"]
    fremde = client.app.state.repositories.messages.speichern(
        chat_id=other, role="assistant", content=""
    )
    antwort = client.post(
        "/api/v1/bild",
        json={"prompt": "x", "modell": "base.safetensors", "chat_id": chat_id,
              "lauf_kennung": fremde.id},
    )
    assert antwort.status_code == 201, antwort.text
    rows = client.app.state.repositories.messages.auflisten(chat_id=chat_id)
    assert [(r.role, r.art) for r in rows] == [("user", "nachricht"), ("assistant", "bild")]
    assert rows[1].bild == antwort.json()["bild"]


def test_a_job_draws_into_the_pictures_folder_not_into_a_chat(tmp_path, monkeypatch):
    """A job has no answer for a picture to stand under: even with an answer
    named, the registry hands none on, and the request names no chat and no
    run."""
    dienst = Bilddienst()
    monkeypatch.setattr(bild_werkzeug.httpx, "AsyncClient", lambda timeout, headers: dienst)
    registry = WerkzeugRegistry([], bild_zugang=("http://x", tmp_path, "testschluessel"))
    text = asyncio.run(
        registry.ausfuehren(
            bild_werkzeug.WERKZEUG_NAME, {"prompt": "a dog"}, chat_id="job1",
            herkunft="agent", antwort_id="some-answer",
        )
    )
    koerper = dienst.gezeichnet[0]
    assert "chat_id" not in koerper and "lauf_kennung" not in koerper
    assert "saved as" in text


def test_a_chat_draw_names_its_chat_and_answer(tmp_path, monkeypatch):
    """In a chat the registry hands the answer on, and the request names the
    chat and the answer as its run."""
    dienst = Bilddienst()
    monkeypatch.setattr(bild_werkzeug.httpx, "AsyncClient", lambda timeout, headers: dienst)
    registry = WerkzeugRegistry([], bild_zugang=("http://x", tmp_path, "testschluessel"))
    text = asyncio.run(
        registry.ausfuehren(
            bild_werkzeug.WERKZEUG_NAME, {"prompt": "a dog"}, chat_id="c1",
            antwort_id="answer-1",
        )
    )
    koerper = dienst.gezeichnet[0]
    assert koerper["chat_id"] == "c1"
    assert koerper["lauf_kennung"] == "answer-1"
    assert "attached to this response" in text


# --- The chat run hands its answer to the drawing, and nothing else ----------


class _Tools:
    """A drawing tool that files its picture the way the route does, and a
    tool returning an image block the way an MCP server does."""

    def __init__(self, repositories):
        self.repositories = repositories
        self.antwort_ids: dict[str, str | None] = {}

    def als_openai_werkzeuge(self, nur=None, shell_zeitgrenze=None, **_options):
        return [
            {"type": "function", "function": {"name": name, "parameters": {}}}
            for name in (bild_werkzeug.WERKZEUG_NAME, "make_picture")
        ]

    def braucht_bestaetigung(self, name, argumente=None, ordner=None):
        return False

    def server_von(self, name):
        return bild_werkzeug.SERVER_NAME if name == bild_werkzeug.WERKZEUG_NAME else "pictures"

    def bestaetigungsgrund(self, name, argumente=None, ordner=None):
        return ""

    async def ausfuehren(self, name, argumente, bild_senke=None, chat_id=None, **rest):
        self.antwort_ids[name] = rest.get("antwort_id")
        if name == bild_werkzeug.WERKZEUG_NAME:
            self.repositories.messages.lauf_bild_speichern(
                chat_id=chat_id, lauf_kennung=rest["antwort_id"], nr=None, von=1,
                bild="drawn.png", seed=5,
            )
            return "The picture was drawn and is attached to this answer."
        bild_senke("image/png", base64.b64encode(b"PNG").decode())
        return "Here is a picture."


def _answer_with_two_pictures(client, chat_id):
    tools = _Tools(client.app.state.repositories)
    client.app.state.werkzeuge = tools
    client.app.state.config.features.mcp = True
    provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["Done."],
            werkzeugaufrufe=[
                Werkzeugaufruf(id="a1", name=bild_werkzeug.WERKZEUG_NAME, argumente={"prompt": "dog"}),
                Werkzeugaufruf(id="a2", name="make_picture", argumente={}),
            ],
        ),
    )
    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Draw a dog."},
    )
    events = [json.loads(z[5:].strip()) for z in antwort.text.splitlines() if z.startswith("data:")]
    return tools, events


def test_the_chat_hands_its_answer_to_the_drawing_only(client, chat_id):
    """The drawing gets the id of the answer being written — the run its
    picture joins — and the result in the stream carries that run's row as it
    stands, so the window shows the tile at once. The other tool gets no
    answer id, and its picture still hangs on the answer as before (the
    silence check: no seed, no run)."""
    tools, events = _answer_with_two_pictures(client, chat_id)
    rows = client.app.state.repositories.messages.auflisten(chat_id=chat_id)
    answer = next(r for r in rows if r.role == "assistant" and r.art == "nachricht")

    assert tools.antwort_ids[bild_werkzeug.WERKZEUG_NAME] == answer.id
    assert tools.antwort_ids["make_picture"] is None

    drawn = next(e for e in events if e["typ"] == "tool_result" and e["name"] == bild_werkzeug.WERKZEUG_NAME)
    assert drawn["bild"] is None
    assert drawn["bildlauf"]["lauf_id"] == answer.id
    assert drawn["bildlauf"]["bilder"] == ["drawn.png"]
    other = next(e for e in events if e["typ"] == "tool_result" and e["name"] == "make_picture")
    assert "bildlauf" not in other and other["bild"]

    # The drawn picture stands in the run only; the other tool's picture is
    # the answer's own, exactly as before.
    assert answer.bild == other["bild"]
    assert "seed" not in answer.stats
    run = next(r for r in rows if r.art == "bildlauf")
    assert run.lauf_id == answer.id and run.bild_dateien() == ["drawn.png"]


# --- A picture the model names to draw from ----------------------------------


def _draw_from(tmp_path, monkeypatch, named: str, *, folders, family: str = "sdxl"):
    """One call of the tool through the registry, as a chat makes it, with
    the picture ``named`` to draw from and ``folders`` as the run's own."""
    model = "model.safetensors"
    dienst = Bilddienst(
        modelle=[model], familien={model: family},
        vorgaben={"family": family, "standalone": False, "parts": {}},
    )
    monkeypatch.setattr(bild_werkzeug.httpx, "AsyncClient", lambda timeout, headers: dienst)
    registry = WerkzeugRegistry([], bild_zugang=("http://x", tmp_path / "pictures", "testschluessel"))
    arguments = {"prompt": "a dog", **({"image": named} if named else {})}

    async def call() -> str:
        return await registry.ausfuehren(
            bild_werkzeug.WERKZEUG_NAME, arguments,
            ordner=[str(folder) for folder in folders], chat_id="c1", antwort_id="answer-1",
        )

    return dienst, call


def test_a_named_picture_goes_to_the_route_as_its_content(tmp_path, monkeypatch):
    """With an input picture the route is asked to draw from it: its bytes
    are handed in — not copied into the pictures folder — and the request
    names it as the picture to start from. No mask travels."""
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "dog.png").write_bytes(b"PNG-bytes-of-a-dog")
    dienst, call = _draw_from(tmp_path, monkeypatch, str(shared / "dog.png"), folders=[shared])
    text = asyncio.run(call())
    assert dienst.handed_in == [b"PNG-bytes-of-a-dog"]
    body = dienst.gezeichnet[-1]
    assert body["startbild"] == "handed-in.png"
    assert "maske" not in body and "ref_bilder" not in body
    assert "generated from dog.png" in text
    assert not (tmp_path / "pictures").exists()


def test_an_editing_family_reads_the_named_picture_as_its_reference(tmp_path, monkeypatch):
    """Which field the picture gets stands at the family: one that edits
    takes it as a reference image."""
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "dog.webp").write_bytes(b"x")
    dienst, call = _draw_from(
        tmp_path, monkeypatch, str(shared / "dog.webp"), folders=[shared], family="flux2",
    )
    asyncio.run(call())
    body = dienst.gezeichnet[-1]
    assert body["ref_bilder"] == ["handed-in.png"]
    assert "startbild" not in body


def test_a_family_that_edits_only_with_a_lora_starts_from_the_picture(tmp_path, monkeypatch):
    """Its editing needs a LoRA nothing here brings: the picture is the one
    to start from, as for a family that draws picture to picture."""
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "dog.png").write_bytes(b"x")
    dienst, call = _draw_from(
        tmp_path, monkeypatch, str(shared / "dog.png"), folders=[shared], family="krea2",
    )
    asyncio.run(call())
    body = dienst.gezeichnet[-1]
    assert body["startbild"] == "handed-in.png" and "ref_bilder" not in body


def test_a_family_that_draws_from_no_picture_says_so(tmp_path, monkeypatch):
    """Silence: a family that only draws from words is handed nothing and
    draws nothing — the model reads why."""
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "dog.png").write_bytes(b"x")
    dienst, call = _draw_from(
        tmp_path, monkeypatch, str(shared / "dog.png"), folders=[shared], family="sd3",
    )
    text = asyncio.run(call())
    assert text == (
        "The image was not generated: the selected model, SD3, SD3.5, "
        "cannot use an image as input. Call again without an image."
    )
    assert dienst.handed_in == [] and dienst.gezeichnet == []


def test_a_family_that_draws_from_no_text_names_where_the_user_changes_it(tmp_path, monkeypatch):
    """A default model that cannot draw from text draws nothing, and the
    model reads the one place the user can pick another one."""
    family = image_families.get("wan")
    dienst, call = _draw_from(tmp_path, monkeypatch, "", folders=[], family="wan")
    text = asyncio.run(call())
    assert text == (
        f"The image was not generated: the selected model, {family.label}, cannot "
        "generate images from text. It edits existing images or creates videos. Ask the "
        "user to select a text-to-image model as the default on the picture server page and "
        "try again."
    )
    assert "picture window" not in text
    assert dienst.gezeichnet == []


def test_without_a_named_picture_the_draw_is_what_it_was(tmp_path, monkeypatch):
    """Silence: no input picture, nothing handed in, no picture field."""
    dienst, call = _draw_from(tmp_path, monkeypatch, "", folders=[])
    asyncio.run(call())
    assert dienst.handed_in == []
    body = dienst.gezeichnet[-1]
    assert "startbild" not in body and "ref_bilder" not in body


def test_a_picture_outside_the_run_s_folders_is_refused(tmp_path, monkeypatch):
    """Silence: a path outside the shared folders and the pictures folder
    is refused before anything is asked of the service; so is a file that
    is not there. A file that is no picture is answered in words."""
    shared, outside = tmp_path / "shared", tmp_path / "outside"
    shared.mkdir()
    outside.mkdir()
    (outside / "secret.png").write_bytes(b"x")
    (shared / "notes.txt").write_text("no picture")
    for named in (str(outside / "secret.png"), str(shared / "missing.png")):
        dienst, call = _draw_from(tmp_path, monkeypatch, named, folders=[shared])
        with pytest.raises(WerkzeugVerboten):
            asyncio.run(call())
        assert dienst.aufrufe == []
    dienst, call = _draw_from(tmp_path, monkeypatch, str(shared / "notes.txt"), folders=[shared])
    text = asyncio.run(call())
    assert "not a PNG, JPEG, or WebP image" in text
    assert dienst.handed_in == [] and dienst.gezeichnet == []


# --- What the model is told a value is, is what the picture is drawn with ----


def _model_values(client: TestClient, **values) -> None:
    """The values the user set for the folder's model on the picture server
    page — the one place the tool's defaults come from besides its family's
    start."""
    from app import bildmodellwerte

    client.app.state.repositories.einstellungen.setzen(
        "global", bildmodellwerte.SCHLUESSEL, {"base.safetensors": values},
    )


def _fields(client: TestClient, config: Config) -> dict:
    """The fields of the tool as a run is offered it."""
    window = bild_werkzeug.fensterbild(client.app.state.repositories, config)
    tool = bild_werkzeug.werkzeug_beschreibung(window.familie, values=window.values)
    return tool.schema["properties"]


def test_each_field_defaults_to_the_value_the_next_picture_is_drawn_with(
    painter, client, config, chat_id, tmp_path, monkeypatch
):
    """A model set to 512 × 512 and 8 steps: the schema says so, field by
    field, and a call that names no value is drawn with exactly those. The
    seed is random, and what the model has no value of its own for starts
    where its family starts."""
    from app import bildinhalt

    monkeypatch.setattr(bildinhalt, "family", lambda path: "sdxl")
    _model_values(client, breite=512, hoehe=512, schritte=8)
    fields = _fields(client, config)
    assert [fields[name]["default"] for name in ("width", "height", "steps")] == [512, 512, 8]
    assert "default" not in fields["seed"]
    assert fields["cfg"]["default"] == image_families.get("sdxl").start.cfg
    assert fields["sampler"]["default"] == image_families.get("sdxl").start.sampler

    answer = _answer_being_written(client, chat_id)
    text = _draw(client, tmp_path, chat_id, answer.id)
    assert text.startswith("The image was generated"), text
    job = painter["jobs"][-1]
    assert (job.breite, job.hoehe, job.schritte) == (512, 512, 8)
    assert job.cfg == fields["cfg"]["default"]


def test_a_size_the_user_asked_for_is_still_drawn_and_changes_no_setting(
    painter, client, config, chat_id, tmp_path, monkeypatch
):
    """Silence: a value the model does send goes to the painter for that one
    picture, and the model's own values — and with them the defaults the
    model reads next — stay what they were."""
    from app import bildinhalt

    monkeypatch.setattr(bildinhalt, "family", lambda path: "sdxl")
    _model_values(client, breite=512, hoehe=512, schritte=8)
    answer = _answer_being_written(client, chat_id)
    text = asyncio.run(
        bild_werkzeug.ausfuehren(
            {"prompt": "a dog", "width": 768}, "/api/v1", tmp_path / "bilder",
            client.app.state.sitzungsschluessel, antwort_id=answer.id, chat_id=chat_id,
        )
    )
    assert text.startswith("The image was generated"), text
    job = painter["jobs"][-1]
    assert (job.breite, job.hoehe, job.schritte) == (768, 512, 8)
    fields = _fields(client, config)
    assert (fields["width"]["default"], fields["height"]["default"]) == (512, 512)


def test_a_value_set_for_the_model_itself_is_the_default(
    painter, client, config, chat_id, tmp_path, monkeypatch
):
    """The default model's own values — set for it on the picture server
    page — lie over its family's start. The model reads those, the sentence
    about the negative prompt follows the CFG in force, and the picture is
    drawn with them."""
    from app import bildinhalt

    monkeypatch.setattr(bildinhalt, "family", lambda path: "sdxl")
    _model_values(client, cfg=1, schritte=6)
    repositories = client.app.state.repositories
    window = bild_werkzeug.fensterbild(repositories, config)
    tool = bild_werkzeug.werkzeug_beschreibung(window.familie, values=window.values)
    fields = tool.schema["properties"]
    assert (fields["steps"]["default"], fields["cfg"]["default"]) == (6, 1)
    start = image_families.get("sdxl").start
    assert (fields["width"]["default"], fields["height"]["default"]) == (start.width, start.height)
    assert "At CFG 1, the negative prompt has no effect. Omit it." in tool.beschreibung
    # Silence: without the model's own CFG the family's start decides, as before.
    plain = bild_werkzeug.werkzeug_beschreibung(window.familie)
    assert "At CFG 1" not in plain.beschreibung
    assert all("default" not in entry for entry in plain.schema["properties"].values())

    answer = _answer_being_written(client, chat_id)
    text = _draw(client, tmp_path, chat_id, answer.id)
    assert text.startswith("The image was generated"), text
    job = painter["jobs"][-1]
    assert (job.schritte, job.cfg) == (6, 1)
    assert (job.breite, job.hoehe) == (start.width, start.height)


def test_a_chat_s_own_picture_values_are_not_read(
    painter, client, config, chat_id, tmp_path, monkeypatch
):
    """The picture studio and the chats share nothing: what an older chat
    stored for its picture window changes neither the description the model
    reads nor the picture it draws — the default model and its start do."""
    from app import bildinhalt

    monkeypatch.setattr(bildinhalt, "family", lambda path: "sdxl")
    stored = client.put(
        f"/api/v1/settings/chat:{chat_id}/bildfenster",
        json={"wert": {"modell": "base.safetensors", "familie": "sdxl", "breite": 640,
                       "hoehe": 384, "schritte": 3, "cfg": 2}},
    )
    assert stored.status_code == 200, stored.text
    fields = _fields(client, config)
    start = image_families.get("sdxl").start
    assert [fields[name]["default"] for name in ("width", "height", "steps", "cfg")] == [
        start.width, start.height, start.steps, start.cfg,
    ]
    answer = _answer_being_written(client, chat_id)
    text = _draw(client, tmp_path, chat_id, answer.id)
    assert text.startswith("The image was generated"), text
    job = painter["jobs"][-1]
    assert (job.breite, job.hoehe, job.schritte, job.cfg) == (
        start.width, start.height, start.steps, start.cfg,
    )


def test_the_list_a_run_is_offered_carries_the_defaults():
    """The registry hands the values of the default model's reading on to the
    list the model reads; a caller that read none gets the fields without
    one."""
    registry = WerkzeugRegistry([], bild_zugang=("http://x", None, "testschluessel"))
    window = bild_werkzeug.FensterBild(
        image_families.get("sdxl"), {"width": 512, "height": 512, "steps": 8},
    )
    offered = registry.als_openai_werkzeuge(bild_fenster=lambda: window)
    fields = next(
        tool["function"]["parameters"]["properties"] for tool in offered
        if tool["function"]["name"] == bild_werkzeug.WERKZEUG_NAME
    )
    assert [fields[name]["default"] for name in ("width", "height", "steps")] == [512, 512, 8]
    assert "default" not in fields["cfg"]
    assert "default" not in fields["seed"]


def test_the_sentences_and_fields_of_draw_image_stand_word_for_word(tmp_path, monkeypatch):
    """What the model reads about the values, each in full: what a field is,
    what it defaults to, when to leave it out — and no sentence names a
    part of the interface that is not there."""
    family = image_families.get("flux")
    tool = bild_werkzeug.werkzeug_beschreibung(family)
    setting = "Uses the image model's start value by default."
    assert {name: entry["description"] for name, entry in tool.schema["properties"].items()
            if name not in ("prompt", "negative_prompt", "image")} == {
        "width": f"Image width in pixels. {setting} Omit unless the user requests a specific width.",
        "height": f"Image height in pixels. {setting} Omit unless the user requests a specific height.",
        "steps": f"Number of sampling steps. {setting} Omit unless the user requests a step count.",
        "cfg": f"CFG scale. {setting} Omit unless the user requests a specific value.",
        "sampler": f"Sampler, e.g. euler_a. {setting} Omit unless the user requests a sampler.",
        "scheduler": f"Scheduler, e.g. discrete. {setting} Omit unless the user requests a scheduler.",
        "seed": "Seed. Random by default. Omit unless the user specifies a seed.",
        "guidance": f"Distilled guidance (Flux only). {setting} Omit unless the user requests a specific value.",
    }
    assert f"Generates an image using {family.label}, the default image model." in tool.beschreibung
    assert (
        "Size, steps, CFG, sampler, and seed use the image model's start values by default. "
        "Specify a value only when the user requests it. It applies to this image only and "
        "does not change the settings."
    ) in tool.beschreibung
    assert "picture window" not in json.dumps(tool.als_openai_werkzeug())
    # Silence probe: a family without a distilled guidance has no such field.
    assert "guidance" not in bild_werkzeug.werkzeug_beschreibung(
        image_families.get("sdxl")
    ).schema["properties"]

    def answer(service: Bilddienst, arguments: dict) -> str:
        monkeypatch.setattr(bild_werkzeug.httpx, "AsyncClient", lambda timeout, headers: service)
        return asyncio.run(
            bild_werkzeug.ausfuehren(arguments, "http://x", tmp_path, "testschluessel")
        )

    assert answer(Bilddienst(), {"prompt": "a dog", "width": "wide", "steps": "many"}) == (
        "The image was not generated because these values were invalid: width, steps. "
        "Provide numbers and a supported sampler or scheduler, or omit them to use the "
        "image model's start values."
    )
    assert answer(Bilddienst(modelle=[], programm_da=False), {"prompt": "a dog"}) == (
        "No image generator is installed. The user can download it from the plus menu under Images."
    )
    assert answer(Bilddienst(modelle=[]), {"prompt": "a dog"}) == (
        "No image model is installed. The user can add one under Images or from the "
        "catalogue."
    )


# --- A name the program does not know is refused, not swapped -------------------


def _draw_with(tmp_path, monkeypatch, arguments: dict, **dienst_arguments):
    """One call of the drawing tool with the values the model named; answers
    the service stand-in and what the tool said."""
    model = "model.safetensors"
    dienst = Bilddienst(
        modelle=[model], familien={model: "sdxl"},
        vorgaben={"family": "sdxl", "standalone": False, "parts": {}}, **dienst_arguments,
    )
    monkeypatch.setattr(bild_werkzeug.httpx, "AsyncClient", lambda timeout, headers: dienst)
    text = asyncio.run(
        bild_werkzeug.ausfuehren({"prompt": "a cat", **arguments}, "http://x", tmp_path, "testschluessel")
    )
    return dienst, text


def test_an_unknown_scheduler_is_refused_with_the_valid_names_and_nothing_is_drawn(tmp_path, monkeypatch):
    dienst, text = _draw_with(tmp_path, monkeypatch, {"scheduler": "auto"})
    assert dienst.gezeichnet == []
    assert "these values were invalid: scheduler." in text
    assert "Supported schedulers: " + ", ".join(bildwahlen.SCHEDULER) + "." in text
    assert "Supported samplers" not in text


def test_an_unknown_sampler_is_refused_with_the_valid_names_and_nothing_is_drawn(tmp_path, monkeypatch):
    dienst, text = _draw_with(tmp_path, monkeypatch, {"sampler": "dpm++2m_karras"})
    assert dienst.gezeichnet == []
    assert "these values were invalid: sampler." in text
    assert "Supported samplers: " + ", ".join(bildwahlen.SAMPLER) + "." in text
    assert "Supported schedulers" not in text


def test_both_unknown_names_are_listed_together_and_a_number_gets_no_list(tmp_path, monkeypatch):
    _dienst, both = _draw_with(tmp_path, monkeypatch, {"sampler": "x", "scheduler": "y"})
    assert "invalid: sampler, scheduler." in both
    assert "Supported samplers: " in both and "Supported schedulers: " in both
    # Silence probe: a word where a number belongs is refused as before, without a list.
    _dienst, number = _draw_with(tmp_path, monkeypatch, {"steps": "many"})
    assert number == (
        "The image was not generated because these values were invalid: steps. "
        "Provide numbers and a supported sampler or scheduler, or omit them to use the "
        "image model's start values."
    )


def test_known_names_travel_as_they_are_and_without_the_fields_the_start_values_stand(tmp_path, monkeypatch):
    dienst, text = _draw_with(tmp_path, monkeypatch, {"sampler": "euler", "scheduler": "discrete"})
    assert "not generated" not in text
    assert (dienst.gezeichnet[-1]["sampler"], dienst.gezeichnet[-1]["scheduler"]) == ("euler", "discrete")
    plain, _text = _draw_with(tmp_path, monkeypatch, {})
    assert plain.gezeichnet, "without the fields the picture is drawn with the model's start values"


def test_the_description_names_the_input_picture_and_the_path_it_answers_with():
    """The model reads both before it calls: that a picture can be named to
    draw from, and that the result names the drawn picture's file."""
    for family in (None, image_families.get("sdxl")):
        tool = bild_werkzeug.werkzeug_beschreibung(family)
        assert tool.schema["properties"]["image"] == bild_werkzeug.INPUT_PICTURE
        assert "the result includes its filename and path" in tool.beschreibung
        assert tool.schema["required"] == ["prompt"]

