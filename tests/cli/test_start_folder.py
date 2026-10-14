"""Where a new chat works: in the folder the client was started in — at a
service that runs on the client's own machine, and at no other. Whether it
runs there is what the service's process says, not the name of its address:
a forwarded port answers under a name of this machine, and this machine's
service answers under any of its addresses."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from cli import chat, themes
from cli.client import KEY_HEADER, ServiceClient
from cli.interfaces import Context
from test_stream import ENTER, KEY, Calls, Service, Step, context

from tests.cli.program import Run, run_client
from tests.cli.stub_service import StubService, a_process_elsewhere, eventually, this_process

START: Step = {"typ": "start", "generation_id": "g1", "message_id": "m1"}
DONE: Step = {"typ": "done", "message_id": "m1", "abgebrochen": False}

# A name of this machine, and addresses that are none of its names: one of
# its network, one of a private network laid over it, and a name of a host.
LOOPBACK = "http://127.0.0.1:8123"
NO_NAME_OF_THIS_MACHINE = [
    "http://192.168.1.20:8123",
    "http://100.100.0.9:8123",
    "http://machine.example:8123",
]

# The whole of a chat's address at the stand-in, and where it is asked which
# process it is.
CHAT_ONE = "/api/v1/chats/chat-1"
HEALTH = "/api/v1/health"


def at(address: str, service: Service, renderer: Calls | None = None) -> Context:
    """The parts of a client that reached the stand-in at ``address``, with
    a new chat open."""
    ctx = context(service, renderer=renderer or Calls())
    ctx.client = ServiceClient(
        address, "en", http=httpx.Client(transport=httpx.MockTransport(service))
    )
    ctx.client.connect()
    chat.new_chat(ctx)
    return ctx


def since_the_chat_was_made(service: Service) -> list[str]:
    """What the client asked for from the creation of the chat on."""
    asked = service.paths()
    return asked[asked.index("POST /api/v1/chats") :]


def a_process_that_is_gone() -> dict[str, Any]:
    """A process this machine does not have: one that has ended, with the
    beginning of one that runs."""
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    return {"pid": gone.pid, "began": this_process()["began"]}


@pytest.fixture(autouse=True)
def a_terminal_of_the_users_own(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    """The client stands in a folder of its own and was not started by the
    window. Returns the folder as the system names it."""
    monkeypatch.delenv(themes.WINDOW_VARIABLE, raising=False)
    monkeypatch.chdir(tmp_path)
    return os.getcwd()


@pytest.mark.parametrize(
    "named", [a_process_that_is_gone, a_process_elsewhere], ids=["no such process", "another beginning"]
)
def test_a_service_elsewhere_gets_no_folder_although_it_answers_under_a_name_of_this_machine(
    named: Callable[[], dict[str, Any]],
) -> None:
    """Falls over without the fix: the name of the address was all the
    client went by, so a port forwarded from another machine was sent the
    folder — to be refused there at every new chat, or to share a folder of
    the same name on the other machine."""
    service = Service([[START, DONE]])
    service.process = lambda host: named()
    calls = Calls()
    ctx = at(LOOPBACK, service, calls)

    chat.send(ctx, "Hello")

    assert since_the_chat_was_made(service) == [
        "POST /api/v1/chats",
        f"GET {HEALTH}",
        "POST /api/v1/chat/completions",
        f"PATCH {CHAT_ONE}",
    ]
    assert service.bodies(CHAT_ONE) == [{"title": "Hello"}]
    assert "working_dirs" not in service.chats["chat-1"]
    assert not any(name in ("error", "notice") for name, _ in calls.calls)


@pytest.mark.parametrize("address", NO_NAME_OF_THIS_MACHINE)
def test_the_service_of_this_machine_gets_the_folder_under_any_of_its_addresses(
    address: str, a_terminal_of_the_users_own: str
) -> None:
    """Falls over without the fix: reached under an address of its network,
    this machine's own service counted as one elsewhere, and the new chat
    got no folder."""
    here = a_terminal_of_the_users_own
    service = Service([[START, DONE], [START, DONE]])
    service.process = lambda host: this_process()
    ctx = at(address, service)

    chat.send(ctx, "Hello")

    # Asked once, after the chat is there and before the folder goes out.
    assert since_the_chat_was_made(service) == [
        "POST /api/v1/chats",
        f"GET {HEALTH}",
        f"PATCH {CHAT_ONE}",
        "POST /api/v1/chat/completions",
        f"PATCH {CHAT_ONE}",
    ]
    assert service.bodies(CHAT_ONE) == [{"working_dirs": [here]}, {"title": "Hello"}]
    assert ctx.session.chat is not None and ctx.session.chat["working_dirs"] == [here]

    # The second message of the same chat asks nothing and sets nothing anew.
    chat.send(ctx, "And again")
    assert since_the_chat_was_made(service).count(f"GET {HEALTH}") == 1
    assert service.bodies(CHAT_ONE) == [{"working_dirs": [here]}, {"title": "Hello"}]


class Older(Service):
    """A stand-in that says how it is the way a service did before it named
    its process."""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == HEALTH and request.headers.get(KEY_HEADER) == KEY:
            self.seen.append(request)
            return httpx.Response(200, json={"status": "ok", "version": "9.8.6"})
        return super().__call__(request)


@pytest.mark.parametrize("says", ["nothing", "no word of it"])
def test_a_service_that_names_no_process_gets_no_folder(says: str) -> None:
    if says == "nothing":
        service = Service([[START, DONE]])
        service.process = lambda host: None
    else:
        service = Older([[START, DONE]])
    calls = Calls()
    ctx = at(LOOPBACK, service, calls)

    chat.send(ctx, "Hello")

    assert service.bodies(CHAT_ONE) == [{"title": "Hello"}]
    assert "working_dirs" not in service.chats["chat-1"]
    assert not any(name in ("error", "notice") for name, _ in calls.calls)


class SaysNothingOfItself(Service):
    """A stand-in that fails where it is asked how it is: with a refusal, or
    by not answering at all."""

    def __init__(self, how: str, answers: list[list[Step]]) -> None:
        super().__init__(answers)
        self.how = how

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == HEALTH and request.headers.get(KEY_HEADER) == KEY:
            if self.how == "refuses":
                return httpx.Response(500, json={"detail": "The service is unwell."})
            raise httpx.ConnectError("connection refused", request=request)
        return super().__call__(request)


@pytest.mark.parametrize("how", ["refuses", "does not answer"])
def test_a_service_that_cannot_say_which_process_it_is_gets_no_folder_and_the_message_goes_out(
    how: str,
) -> None:
    """What kept the service from saying so is no sentence about a folder:
    nothing stands above the input, and the message is sent."""
    service = SaysNothingOfItself(how, [[START, {"typ": "content", "text": "An answer.\n"}, DONE]])
    calls = Calls()
    ctx = at(LOOPBACK, service, calls)

    chat.send(ctx, "Hello")

    assert service.bodies(CHAT_ONE) == [{"title": "Hello"}]
    assert not any(name in ("error", "notice") for name, _ in calls.calls)
    assert [body["content"] for body in service.bodies("/api/v1/chat/completions")] == ["Hello"]
    assert ("content", "An answer.\n") in calls.calls


def test_silence_probe_in_the_windows_tab_the_service_of_this_machine_is_not_even_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Started by the window, the client stands in no folder the user chose
    — wherever the service runs."""
    monkeypatch.setenv(themes.WINDOW_VARIABLE, "1")
    service = Service([[START, DONE]])
    service.process = lambda host: this_process()
    ctx = at(LOOPBACK, service)

    chat.send(ctx, "Hello")

    assert since_the_chat_was_made(service) == [
        "POST /api/v1/chats",
        "POST /api/v1/chat/completions",
        f"PATCH {CHAT_ONE}",
    ]
    assert "working_dirs" not in service.chats["chat-1"]


def test_silence_probe_a_chat_that_is_opened_is_asked_nothing_and_keeps_its_folders() -> None:
    old = {
        "id": "c9", "title": "An old chat", "endpoint_id": "local",
        "working_dirs": ["/a/folder/shared/before"],
    }
    service = Service([[START, DONE]], chats=[old])
    service.process = lambda host: this_process()
    ctx = at(NO_NAME_OF_THIS_MACHINE[0], service)
    chat.enter_chat(ctx, service.chats["c9"])

    chat.send(ctx, "Go on.")

    assert f"GET {HEALTH}" not in service.paths()
    assert not any(request.method == "PATCH" for request in service.seen)
    assert service.chats["c9"]["working_dirs"] == ["/a/folder/shared/before"]


class TakesNoFolder(Service):
    """A stand-in that refuses every working folder it is sent."""

    SAID = "The working directory does not exist."

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH" and b"working_dirs" in request.content:
            return httpx.Response(400, json={"detail": self.SAID})
        return super().__call__(request)


def test_silence_probe_a_folder_this_machines_service_refuses_costs_the_message_nothing() -> None:
    service = TakesNoFolder([[START, {"typ": "content", "text": "An answer.\n"}, DONE]])
    service.process = lambda host: this_process()
    calls = Calls()
    ctx = at(NO_NAME_OF_THIS_MACHINE[1], service, calls)

    chat.send(ctx, "Hello")

    assert ("notice", TakesNoFolder.SAID) in calls.calls
    assert not any(name == "error" for name, _ in calls.calls)
    assert [body["content"] for body in service.bodies("/api/v1/chat/completions")] == ["Hello"]
    assert ("content", "An answer.\n") in calls.calls
    assert "working_dirs" not in service.chats["chat-1"]


# --- Through the whole client ------------------------------------------------------


def two_chats(stub: StubService) -> Callable[[Run, Callable[[str], None]], None]:
    """Types a message into the first chat and one into a chat made with
    ``/new``, then leaves."""

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        ctx = run.parts()
        eventually(lambda: stub.watchers == 1)
        type_in("Hello" + ENTER)
        eventually(lambda: len(stub.sent) == 1 and stub.running() == 0)
        eventually(lambda: not ctx.session.answering)
        type_in("/new" + ENTER)
        # A command runs beside the worker that sends: the message waits
        # until the new chat is the open one.
        eventually(lambda: ctx.session.chat is None)
        type_in("A second chat" + ENTER)
        eventually(lambda: len(stub.sent) == 2 and stub.running() == 0)
        eventually(lambda: not ctx.session.answering)
        type_in("/quit" + ENTER)

    return drive


def test_through_the_whole_client_this_machines_service_is_known_under_another_address(
    stub: StubService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    a_terminal_of_the_users_own: str,
) -> None:
    """Falls over without the fix. The client as it is started, at an
    address that is no name of this machine, where the service names the
    process it really runs in: every new chat gets the folder."""
    here = a_terminal_of_the_users_own
    stub.process = lambda host: this_process()

    with stub.http() as http:
        done = run_client(
            http, tmp_path, monkeypatch, two_chats(stub), address=NO_NAME_OF_THIS_MACHINE[1]
        )

    assert done.code == 0
    assert stub.changes == [
        {"chat": "chat-1", "working_dirs": [here]},
        {"chat": "chat-1", "title": "Hello"},
        {"chat": "chat-2", "working_dirs": [here]},
        {"chat": "chat-2", "title": "A second chat"},
    ]
    # Asked at the start, as ever, and once for each chat that was made.
    assert stub.requests.count(f"GET {HEALTH}") == 3


def test_through_the_whole_client_a_forwarded_port_is_known_under_a_name_of_this_machine(
    stub: StubService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Falls over without the fix. The client as it is started, at a name
    of this machine behind which a service elsewhere answers: no chat gets
    a folder, and nothing is said about one."""
    stub.process = lambda host: a_process_elsewhere()

    with stub.http() as http:
        done = run_client(http, tmp_path, monkeypatch, two_chats(stub), address=LOOPBACK)

    assert done.code == 0
    assert stub.changes == [
        {"chat": "chat-1", "title": "Hello"},
        {"chat": "chat-2", "title": "A second chat"},
    ]
    assert all(not chat.get("working_dirs") for chat in stub.chats.values())
