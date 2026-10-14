"""A service that wants a password and no longer takes a running client's
key — it was started again, and the key belonged to the run before — ends
the client: one sentence, a code other than zero, and no attempt after
attempt. Only the password buys a new key, and the next start asks for it.
A service that hands its key out with its page is another matter: there
the client reads the new key and goes on, as it always did."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from cli import prefs
from cli.client import ServiceClient, ServiceError
from cli.texts import Texts
from tests.cli.program import ENTER, Run, run_client
from tests.cli.stub_service import AppTransport, StubService, eventually

REMOTE = "http://100.100.0.9:8090"
PASSWORD = "the-right-password"
SIGN_IN_PAGE = (
    "<html><head><title>x</title><script>window.__ANMELDUNG__=true;"
    "window.__DIAGNOSE__=false;</script></head><body></body></html>"
)
REFUSAL = "Invalid or missing session key"
STREAM = "GET /api/v1/events/stream"


class BehindAPassword(httpx.BaseTransport):
    """In front of the stand-in: a service beyond the loopback address. Its
    page carries no key and asks to sign in; the key is handed out against
    the password, and everything else is the stand-in's own."""

    def __init__(self, stub: StubService) -> None:
        self._stub = stub
        self._answers = AppTransport(stub, stub._loop)
        self.pages = 0
        self.passwords: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/app/":
            self.pages += 1
            return httpx.Response(200, text=SIGN_IN_PAGE, request=request)
        if request.url.path == "/api/v1/login":
            sent = json.loads(request.content).get("password")
            self.passwords.append(sent)
            if sent != PASSWORD:
                return httpx.Response(401, json={"detail": "Wrong password"}, request=request)
            return httpx.Response(200, json={"key": self._stub.key}, request=request)
        return self._answers.handle_request(request)


def restarted(stub: StubService) -> None:
    """The service started again: a new key, and every stream dropped."""
    stub.key = "the-key-after-the-restart"
    stub.break_events()


def signed_in(stub: StubService, outside: BehindAPassword) -> ServiceClient:
    client = ServiceClient(REMOTE, "en", http=httpx.Client(transport=outside))
    client.connect()
    client.login(PASSWORD)
    return client


# --- The client's door -----------------------------------------------------------


def test_a_key_the_guarded_service_no_longer_takes_signs_the_client_out(stub: StubService) -> None:
    outside = BehindAPassword(stub)
    client = signed_in(stub, outside)
    told: list[str] = []
    client.on_signed_out = lambda: told.append("signed out")
    assert client.get("/health")["status"] == "ok"
    assert client.signed_out is False

    restarted(stub)
    asked = len(stub.requests)
    with pytest.raises(ServiceError) as refused:
        client.get("/health")

    assert refused.value.status == 401 and refused.value.detail == REFUSAL
    assert client.signed_out is True
    assert told == ["signed out"]
    # One quiet look at the page, then the refusal: the request was not
    # sent a second time without a key.
    assert outside.pages == 2
    assert len(stub.requests) == asked + 1


def test_a_stream_the_guarded_service_refuses_signs_the_client_out_as_well(stub: StubService) -> None:
    outside = BehindAPassword(stub)
    client = signed_in(stub, outside)
    told: list[str] = []
    client.on_signed_out = lambda: told.append("signed out")

    restarted(stub)
    asked = len(stub.requests)
    with pytest.raises(ServiceError) as refused:
        list(client.stream("/events/stream", method="GET", params={"schluessel": client.key}))

    assert refused.value.status == 401
    assert client.signed_out is True
    assert told == ["signed out"]
    assert len(stub.requests) == asked + 1


def test_whoever_asked_is_told_once_however_many_requests_are_refused(stub: StubService) -> None:
    outside = BehindAPassword(stub)
    client = signed_in(stub, outside)
    told: list[str] = []
    client.on_signed_out = lambda: told.append("signed out")

    restarted(stub)
    for _ in range(3):
        with pytest.raises(ServiceError):
            client.get("/health")

    assert told == ["signed out"]


def test_signing_in_again_takes_the_mark_away(stub: StubService) -> None:
    outside = BehindAPassword(stub)
    client = signed_in(stub, outside)
    restarted(stub)
    with pytest.raises(ServiceError):
        client.get("/health")
    assert client.signed_out is True

    client.login(PASSWORD)

    assert client.signed_out is False
    assert client.get("/health")["status"] == "ok"


def test_a_service_that_hands_its_key_out_with_the_page_is_read_again_as_ever(
    stub: StubService, stub_http: httpx.Client
) -> None:
    client = ServiceClient("http://stub.test", "en", http=stub_http)
    client.connect()
    told: list[str] = []
    client.on_signed_out = lambda: told.append("signed out")

    stub.key = stub.page_key = "the-key-after-the-restart"

    assert client.get("/health")["status"] == "ok"
    assert client.key == "the-key-after-the-restart"
    assert client.signed_out is False and told == []


# --- The whole client --------------------------------------------------------------


def password_file(tmp_path: Path) -> Path:
    file = tmp_path / "password"
    file.write_text(PASSWORD + "\n", encoding="utf-8")
    return file


def test_a_running_client_ends_with_one_sentence_when_its_key_is_no_longer_taken(
    stub: StubService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    outside = BehindAPassword(stub)

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        run.parts()
        eventually(lambda: stub.watchers == 1)
        restarted(stub)
        # Nothing is typed: the client hears it by itself and leaves.

    with httpx.Client(transport=outside) as http:
        run = run_client(
            http,
            tmp_path,
            monkeypatch,
            drive,
            "--password-file",
            str(password_file(tmp_path)),
            address=REMOTE,
        )

    assert run.code == 1
    said = capsys.readouterr().err
    assert said == Texts("en").t("cli.signed_out", address=REMOTE) + "\n"
    # Signed in once, at the start — and not asked for the password again.
    assert outside.passwords == [PASSWORD]
    # No attempt after attempt: the stream was asked for at the start and
    # at most once more before the client had left.
    assert stub.requests.count(STREAM) <= 2


def test_a_message_sent_after_the_restart_ends_the_client_the_same_way(
    stub: StubService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    outside = BehindAPassword(stub)

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        run.parts()
        eventually(lambda: stub.watchers == 1)
        # The new key without a dropped stream: the listener hears nothing
        # yet, the message is what finds out.
        stub.key = "the-key-after-the-restart"
        type_in(f"Hello{ENTER}")

    with httpx.Client(transport=outside) as http:
        run = run_client(
            http,
            tmp_path,
            monkeypatch,
            drive,
            "--password-file",
            str(password_file(tmp_path)),
            address=REMOTE,
        )

    assert run.code == 1
    assert capsys.readouterr().err == Texts("en").t("cli.signed_out", address=REMOTE) + "\n"
    assert stub.sent == []


def test_the_next_start_buys_a_new_key_with_the_password(
    stub: StubService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = BehindAPassword(stub)
    file = password_file(tmp_path)

    def leave_on_restart(run: Run, type_in: Callable[[str], None]) -> None:
        run.parts()
        eventually(lambda: stub.watchers == 1)
        restarted(stub)

    def leave(run: Run, type_in: Callable[[str], None]) -> None:
        run.parts()
        eventually(lambda: stub.watchers == 1)
        type_in(f"/quit{ENTER}")

    with httpx.Client(transport=outside) as http:
        first = run_client(http, tmp_path, monkeypatch, leave_on_restart, "--password-file", str(file), address=REMOTE)
    assert first.code == 1
    with httpx.Client(transport=outside) as http:
        second = run_client(http, tmp_path, monkeypatch, leave, "--password-file", str(file), address=REMOTE)

    assert second.code == 0
    assert outside.passwords == [PASSWORD, PASSWORD]
    assert prefs.load(tmp_path / "cli.json")["keys"][REMOTE] == "the-key-after-the-restart"


def test_a_local_service_started_again_keeps_its_running_client(
    stub: StubService,
    stub_http: httpx.Client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        ctx = run.parts()
        eventually(lambda: stub.watchers == 1)
        stub.key = stub.page_key = "the-key-after-the-restart"
        stub.break_events()
        eventually(lambda: stub.requests.count(STREAM) >= 2 and stub.watchers == 1)
        type_in(f"Hello{ENTER}")
        eventually(lambda: stub.sent and not ctx.session.answering)
        type_in(f"/quit{ENTER}")

    run = run_client(stub_http, tmp_path, monkeypatch, drive)

    assert run.code == 0
    assert capsys.readouterr().err == ""
    assert [sent["content"] for sent in stub.sent] == ["Hello"]
