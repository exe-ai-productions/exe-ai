"""``/image``: a picture from one sentence — the sentence alone goes to the
service, the progress stands in the line above the status line, the
interrupt key stops it, and at the end the path of the picture is said.
Nothing is opened. The service is the stand-in; nothing is drawn."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from cli import commands, servers
from cli.client import ServiceError
from cli.interfaces import Asker, Context, Entry
from cli.texts import Texts
from tests.cli.conftest import RecordingRenderer, RecordingScreen
from tests.cli.stub_service import StubService, model

CHAT = "chat-1"
PATH = "/data/images/lighthouse.png"


def texts() -> Texts:
    return Texts("en")


class Asking(Asker):
    def __init__(self) -> None:
        self.shown: list[list[Entry]] = []
        self.heads: list[str] = []
        self.queue: list[int | None] = []
        self.typed: list[str | None] = []
        self.questions: list[str] = []

    def choose(self, entries: Any, head: str = "") -> int | None:
        self.shown.append(list(entries))
        self.heads.append(head)
        return self.queue.pop(0) if self.queue else None

    def ask_text(
        self, head: str, *, secret: bool = False, default: str | None = None
    ) -> str | None:
        self.questions.append(head)
        return self.typed.pop(0) if self.typed else None

    def rows(self) -> list[list[str]]:
        return [[text for _, text in entry.cells] for entry in self.shown[-1]]


class Watching(RecordingScreen):
    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self.activities: list[Any] = []

    def set_activity(self, text: Any) -> None:
        self.activities.append(text)


@pytest.fixture(autouse=True)
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(servers, "POLL_SECONDS", 0.02)


@pytest.fixture
def drawn(
    stub: StubService, wire: Callable[[httpx.Client], Context], stub_http: httpx.Client
) -> Context:
    stub.models = [model("local", "Local Model")]
    stub.image.files = [{"name": "draw.safetensors", "groesse_gb": 3.4}]
    stub.settings["global"] = {"bild_standardmodell": "draw.safetensors"}
    stub.chats[CHAT] = {"id": CHAT, "title": "A chat", "working_dirs": [], "project_id": None}
    context = wire(stub_http)
    context.asker = Asking()
    context.screen = Watching(context)
    context.renderer = RecordingRenderer()
    context.session.chat = dict(stub.chats[CHAT])
    context.commands = commands.build_commands(context)
    return context


def posts(stub: StubService) -> list[str]:
    return [request for request in stub.requests if request.startswith("POST ")]


def test_only_the_sentence_and_the_chat_go_out_and_the_path_stands_at_the_end(drawn, stub):
    stub.image.draw_seconds = 0.2
    stub.image.progress_steps = [{"laeuft": True, "anteil": 0.4, "schritt": 4, "gesamt": 10}]
    drawn.commands.run("/image a lighthouse at dusk")
    assert stub.image.draws == [{"prompt": "a lighthouse at dusk", "chat_id": CHAT}]
    assert drawn.renderer.notices == [PATH]
    assert drawn.renderer.errors == []


def test_the_progress_stands_in_the_line_above_the_status_line(drawn, stub):
    stub.image.draw_seconds = 0.3
    stub.image.progress_steps = [{"laeuft": True, "anteil": 0.4}]
    drawn.commands.run("/image a lighthouse at dusk")
    said = [text for text in drawn.screen.activities if isinstance(text, str)]
    assert f"{texts().t('nachricht.bild_laeuft')} 40 %" in said
    assert said[0] == texts().t("nachricht.bild_laeuft")


def test_nothing_is_opened_and_nothing_else_is_asked_for_beyond_the_draw(drawn, stub):
    drawn.commands.run("/image a lighthouse at dusk")
    assert posts(stub) == ["POST /api/v1/bild/satz"]
    assert not [r for r in stub.requests if "open" in r or r.startswith("DELETE")]


def test_a_new_chat_is_created_for_the_picture_first(drawn, stub):
    drawn.session.chat = None
    drawn.commands.run("/image a lighthouse")
    created = posts(stub).index("POST /api/v1/chats")
    assert created < posts(stub).index("POST /api/v1/bild/satz")
    assert stub.image.draws[0]["chat_id"] == drawn.session.chat["id"]


def test_the_interrupt_key_stops_the_picture_and_says_it_was_stopped(drawn, stub):
    stub.image.draw_seconds = 10.0
    stub.image.progress_steps = [{"laeuft": True, "anteil": 0.2}]
    timer = threading.Timer(
        0.2, lambda: drawn.session.cancel_wait and drawn.session.cancel_wait()
    )
    timer.start()
    drawn.commands.run("/image a lighthouse at dusk")
    timer.join()
    assert stub.image.draw_stops == 1
    assert drawn.renderer.notices == [texts().t("bild.abgebrochen")]
    assert PATH not in drawn.renderer.notices


def test_a_refusal_of_the_service_is_raised_with_its_own_sentence(drawn, stub):
    stub.image.refuse_draw = "No default image model is chosen."
    with pytest.raises(ServiceError) as refused:
        drawn.commands.run("/image a lighthouse")
    assert refused.value.detail == "No default image model is chosen."
    assert drawn.renderer.notices == []


def test_without_a_sentence_it_is_asked_for_and_an_empty_answer_draws_nothing(drawn, stub):
    drawn.asker.typed = [None]
    drawn.commands.run("/image")
    assert drawn.asker.questions == [texts().t("cli.cmd_image").split("\n", 1)[0]]
    assert stub.image.draws == []
    drawn.asker.typed = ["  a boat  "]
    drawn.commands.run("/image")
    assert stub.image.draws == [{"prompt": "a boat", "chat_id": CHAT}]


def test_without_the_program_it_is_offered_and_fetched_before_the_picture(drawn, stub):
    stub.image.program = False
    stub.image.program_steps = [
        {"geladen": 4, "gesamt": 10, "anteil": 0.4, "fertig": False, "fehler": None},
        {"geladen": 10, "gesamt": 10, "anteil": 1.0, "fertig": True, "fehler": None},
    ]
    drawn.asker.queue = [0]
    drawn.commands.run("/image a lighthouse")
    assert drawn.asker.rows() == [[texts().t("bildserver.generator_holen")]]
    assert stub.image.program_posts == [None]
    said = [text for text in drawn.screen.activities if isinstance(text, str)]
    assert f"{texts().t('bildserver.generator_laedt')} 40 %" in said
    assert stub.image.draws == [{"prompt": "a lighthouse", "chat_id": CHAT}]
    assert drawn.renderer.notices == [PATH]


def test_closing_the_offer_of_the_program_draws_nothing(drawn, stub):
    stub.image.program = False
    drawn.asker.queue = [None]
    drawn.commands.run("/image a lighthouse")
    assert stub.image.program_posts == [] and stub.image.draws == []


def test_without_a_default_model_nothing_is_offered_nothing_is_sent_and_the_sentence_says_where(drawn, stub):
    stub.settings["global"] = {}
    stub.image.program = False
    drawn.commands.run("/image a lighthouse")
    assert drawn.renderer.notices == [texts().t("cli.no_image_model")]
    assert drawn.renderer.errors == []
    assert drawn.asker.shown == []
    assert stub.image.program_posts == [] and stub.image.draws == []
    assert not [request for request in stub.requests if "bild/satz" in request or "bild/programm" in request]


def test_without_a_default_model_a_sentence_typed_afterwards_sends_nothing(drawn, stub):
    stub.settings["global"] = {}
    drawn.asker.typed = ["a lighthouse"]
    drawn.commands.run("/image")
    assert drawn.renderer.notices == [texts().t("cli.no_image_model")]
    assert stub.image.draws == []


def test_the_sentence_of_the_command_names_the_server_and_not_a_page_of_the_window():
    assert Texts("en").t("cli.no_image_model") == "No image model selected. Choose one with /server image."
    assert Texts("de").t("cli.no_image_model") == "Kein Bildmodell ausgewählt. Bitte mit /server image eines auswählen."
