"""``/model`` and the model server behind it: the files of the model folder
stand in the selection, a file chosen there brings the server up with it,
and what goes wrong on the way is said."""

from __future__ import annotations

import io
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from rich.console import Console

from cli import commands, servers
from cli.interfaces import Asker, Context, Entry
from cli.texts import Texts
from tests.cli.conftest import RecordingRenderer, RecordingScreen
from tests.cli.stub_service import StubService, model

WAIT_SECONDS = 5.0
CHAT = "chat-1"

START = "POST /api/v1/runner/start"
STOP = "POST /api/v1/runner/stop"
FILES = [
    {"name": "small.gguf", "groesse_gb": 1.2},
    {"name": "large.gguf", "groesse_gb": 4.7},
]


class Answering(Asker):
    """Stands in for the selection: keeps what it is shown and answers with
    the entry a test names. A question — a selection with a head — is
    answered by ``yes``."""

    def __init__(self) -> None:
        self.shown: list[list[Entry]] = []
        self.heads: list[str] = []
        self.pick: int | None = None
        self.yes = True
        # Runs when the selection of models has been answered.
        self.after: Callable[[], None] | None = None
        # The answers of a command that asks one selection after the
        # other, in turn; once they are used up the rest answers.
        self.queue: list[int | None] = []

    def choose(self, entries: Any, head: str = "") -> int | None:
        listed = list(entries)
        self.shown.append(listed)
        self.heads.append(head)
        if self.queue:
            return self.queue.pop(0)
        if head:
            return 0 if self.yes else 1
        if self.after is not None:
            self.after()
        return self.pick

    def rows(self) -> list[list[str]]:
        return [[text for _, text in entry.cells] for entry in self.shown[-1]]


class Watching(RecordingScreen):
    """Keeps what the activity line said, in order."""

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self.activities: list[str | None] = []

    def set_activity(self, text: Any) -> None:
        self.activities.append(text)


class Lines(RecordingRenderer):
    def __init__(self) -> None:
        super().__init__()
        self.shell_lines: list[str] = []

    def shell_line(self, text: str) -> None:
        self.shell_lines.append(text)


@pytest.fixture(autouse=True)
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    """The beat the service is asked at, cut down to nothing a test waits
    for."""
    monkeypatch.setattr(servers, "POLL_SECONDS", 0.01)


@pytest.fixture
def folder(stub: StubService) -> StubService:
    """A service with two files in its model folder and one chat open."""
    stub.runner_files = [dict(entry) for entry in FILES]
    stub.chats[CHAT] = {
        "id": CHAT,
        "title": "A chat",
        "endpoint_id": "local",
        "created_at": "2000-01-01T00:00:00",
        "updated_at": "2000-01-01T00:00:00",
    }
    stub.messages[CHAT] = []
    return stub


@pytest.fixture
def tool(
    folder: StubService, wire: Callable[[httpx.Client], Context], stub_http: httpx.Client
) -> Context:
    context = wire(stub_http)
    context.asker = Answering()
    context.screen = Watching(context)
    context.renderer = Lines()
    context.session.chat = dict(folder.chats[CHAT])
    context.session.health = {"version": "9.8.7"}
    context.commands = commands.build_commands(context)
    return context


def count(stub: StubService, request: str) -> int:
    return stub.requests.count(request)


def texts() -> Texts:
    return Texts("en")


# --- The selection ---------------------------------------------------------------------


def test_the_selection_lists_the_files_of_the_model_folder_behind_the_models(tool, folder):
    tool.commands.run("/model")
    rows = tool.asker.rows()
    assert rows[0][0] == "Local Model"
    assert rows[1:] == [
        ["small.gguf", texts().t("modell.server"), texts().t("status.inaktiv"), "1.2 GB"],
        ["large.gguf", texts().t("modell.server"), texts().t("status.inaktiv"), "4.7 GB"],
    ]
    assert count(folder, START) == 0


def test_the_size_of_a_file_has_no_no_break_space_in_german_either(tool, folder):
    tool.texts = Texts("de")
    tool.commands.run("/model")
    assert tool.asker.rows()[1][3] == "1.2 GB"


def test_the_file_the_server_carries_stands_once_and_not_as_a_file(tool, folder):
    folder.model_server_running = True
    folder.runner_model = "small.gguf"
    folder.runner_connected = True
    tool.commands.run("/model")
    names = [row[0] for row in tool.asker.rows()]
    assert names == ["Local Model", "small.gguf", "large.gguf"]
    # The first of the two is the server's own model, listed by the service;
    # only the other one is a file the server does not carry.
    assert tool.asker.rows()[1][2] == texts().t("status.erreichbar")
    assert tool.asker.rows()[2][2] == texts().t("status.inaktiv")


def test_a_number_or_a_name_behind_the_command_meets_a_file_as_well(tool, folder):
    tool.commands.run("/model large.gguf")
    assert folder.runner_starts == ["large.gguf"]
    assert tool.session.endpoint_id == "runner:large.gguf"


# --- Starting ---------------------------------------------------------------------------


def test_a_file_chosen_while_no_server_runs_starts_it_and_the_model_is_chosen_once_connected(
    tool, folder
):
    folder.runner_loads = 2
    tool.asker.pick = 1
    tool.commands.run("/model")
    assert folder.runner_starts == ["small.gguf"]
    assert count(folder, STOP) == 0
    # While it loads, the activity line says so; it is empty again after.
    started = texts().t("cli.model_starting", name="small.gguf")
    assert tool.screen.activities[0] == started
    assert tool.screen.activities[-1] is None
    # Chosen like any other model: kept with the chat, remembered, said.
    assert folder.changes == [{"chat": CHAT, "endpoint_id": "runner:small.gguf"}]
    assert folder.settings["global"][commands.LAST_MODEL_KEY] == {
        "id": "runner:small.gguf",
        "name": "small.gguf",
    }
    assert tool.session.endpoint_id == "runner:small.gguf"
    assert tool.renderer.notices == [texts().t("cli.modell_gewaehlt", name="small.gguf")]
    assert tool.renderer.errors == []


def test_a_server_that_carries_another_model_and_is_idle_is_stopped_and_started_without_a_question(
    tool, folder
):
    folder.model_server_running = True
    folder.runner_model = "small.gguf"
    folder.runner_connected = True
    tool.asker.pick = 2
    tool.commands.run("/model")
    assert tool.asker.heads == [""]
    assert folder.requests.index(STOP) < folder.requests.index(START)
    assert folder.runner_starts == ["large.gguf"]
    assert tool.session.endpoint_id == "runner:large.gguf"


def test_a_server_that_is_writing_an_answer_is_asked_about_before_it_is_stopped(tool, folder):
    folder.model_server_running = True
    folder.runner_model = "small.gguf"
    folder.runner_connected = True
    folder.runner_server_state = "active"
    tool.asker.pick = 2
    tool.asker.yes = True
    tool.commands.run("/model")
    assert tool.asker.heads == ["", texts().t("cli.model_swap_ask", name="large.gguf")]
    assert count(folder, STOP) == 1 and folder.runner_starts == ["large.gguf"]


def test_a_no_to_that_question_leaves_the_server_and_the_choice_as_they_were(tool, folder):
    folder.model_server_running = True
    folder.runner_model = "small.gguf"
    folder.runner_connected = True
    folder.runner_server_state = "active"
    tool.asker.pick = 2
    tool.asker.yes = False
    tool.commands.run("/model")
    assert count(folder, STOP) == 0 and count(folder, START) == 0
    assert tool.session.endpoint_id == "local"
    assert folder.changes == []
    assert tool.renderer.notices == []


def test_a_file_the_server_already_carries_is_not_started_again(tool, folder):
    tool.commands.run("/model small.gguf")
    assert folder.runner_starts == ["small.gguf"]
    # The list of the first command still names it as a file.
    tool.commands.run("/model small.gguf")
    assert folder.runner_starts == ["small.gguf"]
    assert count(folder, STOP) == 0
    assert tool.session.endpoint_id == "runner:small.gguf"


def test_an_answer_that_runs_beside_the_wait_has_its_own_line_again_after_it(tool, folder):
    tool.session.answering = True
    tool.commands.run("/model small.gguf")
    assert tool.screen.activities[-1] == texts().t("status.erzeugt_antwort")


# --- What goes wrong ---------------------------------------------------------------------


def test_a_server_that_ends_while_it_loads_is_said_with_the_last_ten_lines_of_its_log(
    tool, folder
):
    folder.runner_loads = 1
    folder.runner_dies = True
    folder.runner_log = [f"line {number}" for number in range(1, 26)]
    tool.asker.pick = 2
    tool.commands.run("/model")
    assert tool.renderer.errors == [texts().t("cli.model_start_failed")]
    assert tool.renderer.shell_lines == [f"line {number}" for number in range(16, 26)]
    # The chat's choice stays as it was.
    assert tool.session.endpoint_id == "local"
    assert folder.changes == [] and tool.renderer.notices == []
    assert tool.screen.activities[-1] is None


def test_a_missing_program_is_asked_about_fetched_with_its_progress_and_the_start_is_made_again(
    tool, folder
):
    folder.runner_program = False
    folder.program_steps = [
        {"anteil": 0.25, "fertig": False, "fehler": None},
        {"anteil": 0.75, "fertig": False, "fehler": None},
        {"anteil": 1.0, "fertig": True, "fehler": None},
    ]
    tool.asker.pick = 1
    tool.commands.run("/model")
    assert tool.asker.heads == ["", texts().t("cli.program_missing_ask")]
    fetching = texts().t("modell.server_holen")
    assert f"{fetching} 25 %" in tool.screen.activities
    assert f"{fetching} 75 %" in tool.screen.activities
    assert folder.runner_starts == ["small.gguf"]
    assert tool.session.endpoint_id == "runner:small.gguf"


def test_a_no_to_the_missing_program_makes_no_start(tool, folder):
    folder.runner_program = False
    tool.asker.pick = 1
    tool.asker.yes = False
    tool.commands.run("/model")
    assert folder.runner_starts == []
    assert count(folder, "POST /api/v1/runner/programm") == 0
    assert tool.session.endpoint_id == "local"


def test_a_fetch_that_fails_says_what_the_window_says_and_not_the_reason_word(tool, folder):
    folder.runner_program = False
    # The state names a reason, not a sentence.
    folder.program_steps = [{"anteil": 0.1, "fertig": False, "fehler": "fehlgeschlagen"}]
    tool.asker.pick = 1
    tool.commands.run("/model")
    assert tool.renderer.errors == [texts().t("bildserver.generator_fehler")]
    assert folder.runner_starts == []


def test_a_refusal_of_the_start_is_shown_as_the_service_says_it(tool, folder):
    # The file is gone between the list and the start.
    tool.asker.pick = 1
    tool.asker.after = lambda: setattr(folder, "runner_files", [])
    with pytest.raises(servers.ServiceError) as refused:
        tool.commands.run("/model")
    assert refused.value.status == 404
    assert tool.session.endpoint_id == "local"


# --- Walking away -------------------------------------------------------------------------


def wait_for(condition: Callable[[], Any]) -> None:
    deadline = time.monotonic() + WAIT_SECONDS
    while not condition():
        assert time.monotonic() < deadline, "the other thread never got there"
        time.sleep(0.005)


def test_the_interrupt_key_ends_the_wait_and_stops_the_server_this_command_started(tool, folder):
    # A model that never connects, and a server that keeps running.
    folder.runner_loads = 10**9
    tool.asker.pick = 1
    worker = threading.Thread(target=lambda: tool.commands.run("/model"), daemon=True)
    worker.start()
    wait_for(lambda: tool.session.cancel_wait is not None)
    tool.session.cancel_wait()
    worker.join(WAIT_SECONDS)
    assert not worker.is_alive()
    assert folder.runner_starts == ["small.gguf"]
    assert count(folder, STOP) == 1
    assert tool.session.cancel_wait is None
    assert tool.session.endpoint_id == "local"
    assert folder.changes == [] and tool.renderer.notices == []
    assert tool.renderer.errors == []


def test_the_interrupt_key_while_the_program_is_fetched_ends_the_wait_and_starts_nothing(
    tool, folder
):
    folder.runner_program = False
    # A fetch that never ends.
    folder.program_steps = [{"anteil": 0.1, "fertig": False, "fehler": None}]
    tool.asker.pick = 1
    worker = threading.Thread(target=lambda: tool.commands.run("/model"), daemon=True)
    worker.start()
    fetching = f"{texts().t('modell.server_holen')} 10 %"
    wait_for(lambda: fetching in tool.screen.activities)
    tool.session.cancel_wait()
    worker.join(WAIT_SECONDS)
    assert not worker.is_alive()
    assert folder.runner_starts == [] and count(folder, STOP) == 0
    assert tool.session.endpoint_id == "local"


def test_a_server_that_still_loads_the_file_is_waited_for_and_not_started_again(tool, folder):
    # The list of an earlier command still names the file as one to start;
    # meanwhile the window has started it.
    tool.commands.run("/model")
    folder.model_server_running = True
    folder.runner_model = "small.gguf"
    folder.runner_loads = 2
    tool.commands.run("/model small.gguf")
    assert count(folder, START) == 0 and count(folder, STOP) == 0
    assert tool.session.endpoint_id == "runner:small.gguf"


def test_the_interrupt_key_leaves_a_server_alone_that_this_command_did_not_start(tool, folder):
    tool.commands.run("/model")
    folder.model_server_running = True
    folder.runner_model = "small.gguf"
    folder.runner_loads = 10**9
    worker = threading.Thread(target=lambda: tool.commands.run("/model small.gguf"), daemon=True)
    worker.start()
    wait_for(lambda: tool.session.cancel_wait is not None)
    tool.session.cancel_wait()
    worker.join(WAIT_SECONDS)
    assert not worker.is_alive()
    assert count(folder, STOP) == 0 and folder.model_server_running


# --- Nothing to do ------------------------------------------------------------------------


def test_a_model_of_the_service_is_chosen_without_a_call_to_the_server(tool, folder):
    tool.asker.pick = 0
    tool.commands.run("/model")
    assert count(folder, START) == 0 and count(folder, STOP) == 0
    assert tool.session.cancel_wait is None


def test_the_running_local_model_is_chosen_without_a_call_to_the_server(tool, folder):
    folder.model_server_running = True
    folder.runner_model = "small.gguf"
    folder.runner_connected = True
    tool.commands.run("/model runner:small.gguf")
    assert count(folder, START) == 0 and count(folder, STOP) == 0
    assert tool.session.endpoint_id == "runner:small.gguf"


def test_an_empty_model_folder_leaves_the_list_as_it_was(tool, folder):
    folder.runner_files = []
    tool.commands.run("/model")
    assert [row[0] for row in tool.asker.rows()] == ["Local Model"]


def test_a_service_without_a_model_server_leaves_the_list_as_it_was(tool, folder):
    folder.models = [model("cloud", "Cloud Model")]
    folder.runner_files = []
    tool.commands.run("/model")
    assert [row[0] for row in tool.asker.rows()] == ["Cloud Model"]


# --- /server -------------------------------------------------------------------------------

AGENT = "/agentenmodell"
EMBEDDING = "/einbettungsserver"
SPEECH = "/sprachserver"
CLEANUP = "/bereinigungsserver"
WORDS_OF_SERVERS = {
    "model": "modell.server",
    "agent": "agentserver.titel",
    "embedding": "einbettungsserver.titel",
    "speech": "sprachserver.titel",
    "cleanup": "bereinigungsserver.titel",
    "image": "bildserver.titel",
}


@pytest.fixture
def agent(folder: StubService):
    """The agent server, with two files in its folder."""
    server = folder.servers[AGENT]
    server.files = [{"name": "agent.gguf", "groesse_gb": 0.6}, {"name": "other.gguf", "groesse_gb": 1.9}]
    server.log = ["loading", "ready"]
    return server


def title(word: str) -> str:
    return texts().t(WORDS_OF_SERVERS[word])


def written(ctx: Context) -> str:
    """What the screen was handed, as the reader sees it."""
    console = Console(file=io.StringIO(), width=100, record=True)
    for renderable in ctx.screen.printed:
        console.print(renderable)
    return console.export_text()


def test_the_selection_names_the_six_servers_in_the_order_of_the_page_with_their_state(tool, folder, agent):
    tool.commands.run("/server")
    rows = tool.asker.rows()
    assert [row[0] for row in rows] == [title(word) for word in WORDS_OF_SERVERS]
    assert all(row[1] == texts().t("status.inaktiv") for row in rows)
    assert all(row[2:] == ["", "", ""] for row in rows)


def test_a_server_that_runs_names_its_file_its_port_and_its_memory(tool, folder, agent):
    agent.running, agent.model, agent.port, agent.memory = True, "agent.gguf", 8101, 1.5
    tool.commands.run("/server")
    row = tool.asker.rows()[1]
    assert row == [
        title("agent"),
        texts().t("status.aktiv"),
        "agent.gguf",
        f"{texts().t('kopf.port')} 8101",
        texts().t("modell.im_speicher", gb=1.5),
    ]


def test_a_server_that_stands_still_names_no_file_though_its_state_does(tool, folder):
    cleanup = folder.servers[CLEANUP]
    cleanup.running, cleanup.model = False, "kept.gguf"
    tool.commands.run("/server")
    assert tool.asker.rows()[4][2] == ""


def test_the_enter_key_on_a_server_opens_its_own_selection_under_its_line(tool, folder, agent):
    tool.asker.queue = [1, None]
    tool.commands.run("/server")
    assert tool.asker.rows() == [[texts().t("modell.server_starten")], [texts().t("modell.protokoll")]]
    assert tool.asker.heads[-1] == f"{title('agent')}  {texts().t('status.inaktiv')}"
    # Nothing was picked in it: nothing was asked of the server.
    assert agent.starts == [] and agent.stops == 0


def test_start_shows_the_files_of_the_folder_starts_with_the_chosen_one_and_says_how_it_stands(
    tool, folder, agent
):
    tool.asker.queue = [1, 0, 1]
    tool.commands.run("/server")
    assert tool.asker.rows() == [["agent.gguf", "0.6 GB"], ["other.gguf", "1.9 GB"]]
    assert agent.starts == ["other.gguf"]
    assert tool.renderer.notices == [
        f"{title('agent')}  {texts().t('status.aktiv')}  other.gguf  "
        f"{texts().t('kopf.port')} 8101  {texts().t('modell.im_speicher', gb=1.5)}"
    ]


def test_stop_stops_and_says_inactive(tool, folder, agent):
    agent.running, agent.model = True, "agent.gguf"
    tool.asker.queue = [1, 0]
    tool.commands.run("/server")
    assert tool.asker.heads[-1].startswith(title("agent"))
    assert tool.asker.rows() == [[texts().t("modell.server_anhalten")], [texts().t("modell.protokoll")]]
    assert agent.stops == 1
    assert tool.renderer.notices == [f"{title('agent')}  {texts().t('status.inaktiv')}"]


def test_log_writes_the_lines_of_the_service_into_the_history(tool, folder, agent):
    tool.commands.run("/server log agent")
    assert tool.renderer.shell_lines == ["loading", "ready"]


def test_a_log_without_a_line_says_how_the_server_stands(tool, folder, agent):
    agent.log = []
    tool.commands.run("/server log agent")
    assert tool.renderer.shell_lines == []
    assert tool.renderer.notices == [f"{title('agent')}  {texts().t('status.inaktiv')}"]


def test_each_of_the_six_words_meets_its_own_server_and_none_means_the_model_server(tool, folder):
    stub = folder
    for server in stub.servers.values():
        server.running = True
    stub.model_server_running, stub.runner_model = True, "small.gguf"
    stub.image.word, stub.image.model = "bereit", "img.safetensors"
    order = [
        ("model", lambda: count(stub, STOP)),
        ("agent", lambda: stub.servers[AGENT].stops),
        ("embedding", lambda: stub.servers[EMBEDDING].stops),
        ("speech", lambda: stub.servers[SPEECH].stops),
        ("cleanup", lambda: stub.servers[CLEANUP].stops),
        ("image", lambda: stub.image.stops),
    ]
    for word, stops in order:
        before = [count_of() for _, count_of in order]
        tool.commands.run(f"/server stop {word}")
        after = [count_of() for _, count_of in order]
        assert [a - b for a, b in zip(after, before, strict=True)] == [
            1 if name == word else 0 for name, _ in order
        ], word
    # Without a word, the model server — which stands still by now.
    stub.model_server_running = True
    tool.commands.run("/server stop")
    assert count(stub, STOP) == 2


def test_a_word_alone_opens_that_servers_selection(tool, folder, agent):
    tool.asker.queue = [None]
    tool.commands.run("/server agent")
    assert tool.asker.heads[-1].startswith(title("agent"))
    assert agent.starts == [] and agent.stops == 0


def test_a_word_that_is_none_is_said_and_the_service_is_not_asked(tool, folder):
    before = list(folder.requests)
    tool.commands.run("/server tinker")
    tool.commands.run("/server stop tinker")
    assert tool.renderer.errors == [
        texts().t("cli.unknown_choice", name="tinker"),
        texts().t("cli.unknown_choice", name="tinker"),
    ]
    assert folder.requests == before


def test_closing_a_selection_calls_nothing_that_changes_something(tool, folder, agent):
    for queue in ([None], [1, None], [1, 0, None]):
        tool.asker.queue = list(queue)
        tool.commands.run("/server")
    assert agent.starts == [] and agent.stops == 0
    assert all(request.startswith("GET") for request in folder.requests if "/agentenmodell" in request)


def test_a_folder_without_a_file_has_nothing_to_start_and_the_line_says_so(tool, folder):
    # The cleanup server has no model in its folder.
    tool.commands.run("/server start cleanup")
    assert tool.asker.shown == []
    # The sentence that says how to get one stands where the line was.
    assert tool.renderer.notices == [texts().t("cli.no_model_in_folder")]


@pytest.mark.parametrize("word", ["model", "agent", "embedding", "speech", "cleanup", "image"])
def test_every_server_with_nothing_in_its_folder_says_the_same_sentence(tool, folder, word):
    folder.runner_files = []
    for server in folder.servers.values():
        server.files = []
    folder.image.files = []
    tool.commands.run(f"/server start {word}")
    assert tool.asker.shown == []
    assert tool.renderer.notices == [texts().t("cli.no_model_in_folder")]
    assert count(folder, START) == 0


def test_a_start_at_a_server_that_runs_says_its_line_and_asks_for_nothing(tool, folder, agent):
    agent.running, agent.model = True, "agent.gguf"
    tool.commands.run("/server start agent")
    assert agent.starts == []
    assert tool.asker.shown == []


def test_a_missing_program_at_the_agent_server_is_asked_about_fetched_and_the_start_made(
    tool, folder, agent
):
    agent.program = False
    folder.program_steps = [
        {"anteil": 0.5, "fertig": False, "fehler": None},
        {"anteil": 1.0, "fertig": True, "fehler": None},
    ]
    # The file of the start; and the missing program is answered yes. The
    # program is the one thing the agent server's start refused for: the
    # stand-in gives it back once it was fetched.
    original = folder.servers[AGENT].start

    def start(file: str):
        agent.program = folder.runner_program
        return original(file)

    agent.start = start  # type: ignore[method-assign]
    folder.runner_program = False
    tool.asker.queue = [0]
    tool.asker.yes = True
    tool.commands.run("/server start agent")
    assert tool.asker.heads == ["", texts().t("cli.program_missing_ask")]
    assert agent.starts == ["agent.gguf"]


def test_the_image_server_starts_from_its_own_models_and_asks_for_no_program(tool, folder):
    folder.image.files = [{"name": "draw.safetensors", "groesse_gb": 3.4}]
    tool.asker.queue = [0]
    tool.commands.run("/server start image")
    assert tool.asker.rows() == [["draw.safetensors", "3.4 GB"]]
    assert folder.image.starts == ["draw.safetensors"]
    assert tool.renderer.notices == [
        f"{title('image')}  {texts().t('status.aktiv')}  draw.safetensors"
    ]


# --- the check for a newer program ----------------------------------------------------------


def test_the_check_is_offered_where_the_service_says_so_and_only_there(tool, folder):
    tool.asker.queue = [None]
    tool.commands.run("/server model")
    assert len(tool.asker.rows()) == 2
    folder.runner_updatable = True
    tool.asker.queue = [None]
    tool.commands.run("/server model")
    assert tool.asker.rows()[-1] == [texts().t("bildserver.nach_updates_suchen")]


def test_up_to_date_is_said_in_the_hint_line(tool, folder):
    folder.runner_updatable = True
    folder.program_update = {"verfuegbar": False, "aktuell": True}
    tool.asker.queue = [2]
    tool.commands.run("/server model")
    assert tool.renderer.notices == [texts().t("bildserver.aktuell")]


def test_a_newer_build_brings_the_selection_again_with_the_fetch_and_checks_once_more(tool, folder):
    folder.runner_updatable = True
    folder.program_update = {"verfuegbar": True, "aktuell": False}
    # The check, then — in the selection that comes again — the fetch.
    tool.asker.queue = [2, 2]
    tool.commands.run("/server model")
    assert tool.asker.rows()[-1] == [texts().t("bildserver.generator_aktualisieren")]
    assert folder.program_posts == [{"aktualisieren": True}]
    assert tool.renderer.notices == [texts().t("bildserver.aktuell")]


def test_an_answer_that_says_neither_says_nothing(tool, folder):
    folder.runner_updatable = True
    folder.program_update = {"verfuegbar": False, "aktuell": False}
    tool.asker.queue = [2]
    tool.commands.run("/server model")
    assert tool.renderer.notices == [] and tool.renderer.errors == []


# --- /status ---------------------------------------------------------------------------------


def test_the_overview_has_the_head_the_memory_the_model_and_the_six_servers(tool, folder, agent):
    agent.running, agent.model = True, "agent.gguf"
    tool.status.update(model_name="Local Model")
    tool.commands.run("/status")
    lines = [" ".join(line.split()) for line in written(tool).splitlines() if line.strip()]
    assert lines[0].startswith(f"{texts().t('cli.titel')} 9.8.7")
    assert lines[1] == f"{texts().t('kopf.speicher')} 25/64 GB"
    # The model in use, with how its server stands: the word line 1 gives.
    assert lines[2] == f"{texts().t('modell.titel')} Local Model {texts().t('kopf.bereit')}"
    servers_listed = lines[3:]
    assert len(servers_listed) == 6
    for line, word in zip(servers_listed, WORDS_OF_SERVERS, strict=True):
        assert line.startswith(title(word)), line
    assert "agent.gguf" in servers_listed[1] and "8101" in servers_listed[1]


def test_the_overview_leaves_out_what_the_service_does_not_name(tool, folder):
    folder.memory = {"belegt_gb": None, "gesamt_gb": None, "anteil": None}
    # No model is in use.
    tool.session.endpoint_id = None
    tool.commands.run("/status")
    text = written(tool)
    assert texts().t("kopf.speicher") not in text
    assert "Local Model" not in text


def test_the_overview_changes_nothing(tool, folder, agent):
    before = len(folder.requests)
    tool.commands.run("/status")
    asked = folder.requests[before:]
    assert asked and all(request.startswith("GET") for request in asked)


# --- the image server's program ----------------------------------------------------------

IMAGE_FILES = [{"name": "draw.safetensors", "groesse_gb": 3.4}]
FETCHING = [
    {"geladen": 4, "gesamt": 10, "anteil": 0.4, "fertig": False, "fehler": None},
    {"geladen": 10, "gesamt": 10, "anteil": 1.0, "fertig": True, "fehler": None},
]


def image_without_program(folder: StubService) -> None:
    folder.image.files = [dict(entry) for entry in IMAGE_FILES]
    folder.image.program = False
    folder.image.program_steps = [dict(step) for step in FETCHING]


def test_the_image_server_without_its_program_offers_it_fetches_it_and_starts(tool, folder):
    image_without_program(folder)
    tool.asker.queue = [0, 0]
    tool.commands.run("/server start image")
    # The offer is one entry, as the window's button is, and no question.
    assert tool.asker.heads == ["", ""]
    assert [[text for _, text in entry.cells] for entry in tool.asker.shown[0]] == [
        [texts().t("bildserver.generator_holen")]
    ]
    assert texts().t("cli.program_missing_ask") not in tool.asker.heads
    assert folder.image.program_posts == [None]
    said = [text for text in tool.screen.activities if isinstance(text, str)]
    assert f"{texts().t('bildserver.generator_laedt')} 40 %" in said
    assert folder.image.starts == ["draw.safetensors"]
    assert count(folder, "POST /api/v1/runner/programm") == 0


def test_where_the_system_offers_builds_each_stands_with_its_size_or_installed(tool, folder):
    image_without_program(folder)
    folder.image.builds = [
        {"variante": "cuda", "groesse": 150 * 1024 * 1024},
        {"variante": "vulkan", "groesse": 40 * 1024 * 1024},
    ]
    tool.asker.queue = [1, 0]
    tool.commands.run("/server start image")
    assert [[text for _, text in entry.cells] for entry in tool.asker.shown[0]] == [
        ["cuda", texts().t("bildserver.variante_holen", groesse="150 MB")],
        ["vulkan", texts().t("bildserver.variante_holen", groesse="40 MB")],
    ]
    assert folder.image.program_posts == [{"variante": "vulkan"}]


def test_a_build_that_is_installed_is_shown_so_and_picking_it_fetches_nothing(tool, folder):
    image_without_program(folder)
    folder.image.builds = [{"variante": "cuda", "groesse": 150 * 1024 * 1024}]
    folder.image.installed = "cuda"
    tool.asker.queue = [0]
    tool.commands.run("/server start image")
    assert [[text for _, text in entry.cells] for entry in tool.asker.shown[0]] == [
        ["cuda", texts().t("bildserver.variante_installiert")]
    ]
    assert folder.image.program_posts == [] and folder.image.starts == []


def test_closing_the_offer_fetches_nothing_and_starts_nothing(tool, folder):
    image_without_program(folder)
    tool.asker.queue = [None]
    tool.commands.run("/server start image")
    assert folder.image.program_posts == [] and folder.image.starts == []


def test_a_fetch_that_fails_says_so_in_the_windows_words_and_starts_nothing(tool, folder):
    image_without_program(folder)
    folder.image.program_steps = [{"geladen": 0, "gesamt": 0, "anteil": 0.0, "fertig": False, "fehler": "net"}]
    tool.asker.queue = [0, 0]
    tool.commands.run("/server start image")
    assert tool.renderer.errors == [texts().t("bildserver.generator_fehler")]
    assert folder.image.starts == []


def test_the_menu_of_the_image_server_offers_the_program_where_it_is_not_there(tool, folder):
    image_without_program(folder)
    tool.asker.queue = [None]
    tool.commands.run("/server image")
    assert [text for entry in tool.asker.shown[0] for _, text in entry.cells] == [
        texts().t("modell.server_starten"),
        texts().t("modell.protokoll"),
        texts().t("bildserver.standardmodell"),
        texts().t("bildserver.generator_holen"),
    ]


def test_where_the_program_is_there_the_menu_has_the_check_and_no_fetch(tool, folder):
    folder.image.files = [dict(entry) for entry in IMAGE_FILES]
    tool.asker.queue = [None]
    tool.commands.run("/server image")
    labels = [text for entry in tool.asker.shown[0] for _, text in entry.cells]
    assert texts().t("bildserver.nach_updates_suchen") in labels
    assert texts().t("bildserver.generator_holen") not in labels


def test_the_check_says_up_to_date_where_it_is(tool, folder):
    folder.image.update = {"verfuegbar": False, "aktuell": True}
    tool.asker.queue = [3]
    tool.commands.run("/server image")
    assert tool.renderer.notices == [texts().t("bildserver.aktuell")]


def test_a_newer_program_brings_the_update_and_fetches_the_newest(tool, folder):
    folder.image.update = {"verfuegbar": True, "bau": "master-999"}
    folder.image.program_steps = [dict(step) for step in FETCHING]
    # The check, then — the menu again with the update in its place — the
    # update; the check that follows it says nothing more.
    tool.asker.queue = [3, 3]
    tool.commands.run("/server image")
    labels = [text for entry in tool.asker.shown[1] for _, text in entry.cells]
    assert texts().t("bildserver.generator_aktualisieren") in labels
    assert folder.image.program_posts == [{"aktualisieren": True}]
    assert count(folder, "POST /api/v1/runner/programm") == 0


def test_a_release_page_that_cannot_be_read_is_not_taken_for_up_to_date(tool, folder):
    folder.image.update = {"verfuegbar": False, "aktuell": False, "unreadable": True}
    tool.asker.queue = [3]
    tool.commands.run("/server image")
    assert tool.renderer.notices == [texts().t("bildserver.updates_nicht_pruefbar")]


def test_the_model_server_still_fetches_its_program_over_its_own_route(tool, folder):
    folder.runner_program = False
    original = folder.program_steps
    folder.program_steps = [dict(step) for step in FETCHING]
    tool.asker.queue = [0]
    tool.asker.yes = True
    tool.commands.run("/server start")
    assert count(folder, "POST /api/v1/runner/programm") == 1
    assert folder.image.program_posts == []
    folder.program_steps = original


def test_the_menu_of_the_image_server_alone_has_the_default_model_after_the_log(tool, folder):
    folder.image.files = [dict(entry) for entry in IMAGE_FILES]
    tool.asker.queue = [None]
    tool.commands.run("/server image")
    labels = [text for entry in tool.asker.shown[0] for _, text in entry.cells]
    assert labels[:3] == [
        texts().t("modell.server_starten"),
        texts().t("modell.protokoll"),
        texts().t("bildserver.standardmodell"),
    ]
    # The other servers have no such entry.
    for word in ("model", "embedding", "speech"):
        tool.asker.queue = [None]
        tool.commands.run(f"/server {word}")
        assert texts().t("bildserver.standardmodell") not in [
            text for entry in tool.asker.shown[-1] for _, text in entry.cells
        ]


def test_the_choice_of_the_default_model_is_written_under_the_key_of_the_window(tool, folder):
    files = [*IMAGE_FILES, {"name": "other.safetensors", "groesse_gb": 2.1}]
    folder.image.files = [dict(entry) for entry in files]
    folder.settings["global"] = {"bild_standardmodell": files[0]["name"]}
    tool.asker.queue = [2, 1]
    tool.commands.run("/server image")
    # The list is the folder's models with their sizes; the held default is the marked row.
    models = tool.asker.shown[1]
    assert [entry.cells[0][1] for entry in models] == [entry["name"] for entry in files]
    assert [entry.in_use for entry in models] == [True] + [False] * (len(files) - 1)
    assert "PUT /api/v1/settings/global/bild_standardmodell" in folder.requests
    assert folder.settings["global"]["bild_standardmodell"] == files[1]["name"]
    assert tool.renderer.notices == [f"{texts().t('bildserver.standardmodell')}: {files[1]['name']}"]


def test_closing_the_list_of_default_models_changes_nothing(tool, folder):
    folder.image.files = [dict(entry) for entry in IMAGE_FILES]
    tool.asker.queue = [2, None]
    tool.commands.run("/server image")
    assert not [request for request in folder.requests if request.startswith("PUT ")]
    assert tool.renderer.notices == []


def test_without_a_model_in_the_folder_the_default_is_not_asked_for_and_nothing_is_written(tool, folder):
    folder.image.files = []
    tool.asker.queue = [2]
    tool.commands.run("/server image")
    assert tool.renderer.notices == [texts().t("cli.no_model_in_folder")]
    assert not [request for request in folder.requests if request.startswith("PUT ")]
