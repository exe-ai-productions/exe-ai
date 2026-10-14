"""The terminal client's one door to the service: the key, the headers,
refusals, streams — and the one sentence where no service answers."""

from __future__ import annotations

import json

import httpx
import pytest

from cli.client import KEY_HEADER, LANGUAGE_HEADER, ServiceClient, ServiceError, ServiceUnreachable
from cli.main import main
from cli.texts import Texts

KEY = "key-of-this-run"
PAGE = (
    "<html><head><title>x</title>"
    f'<script>window.__SITZUNGSSCHLUESSEL__="{KEY}";window.__DIAGNOSE__=false;</script>'
    "</head><body></body></html>"
)


class Service:
    """A stand-in that serves the page with the key and guards its API with
    it, the way the service does. Every request it sees is kept."""

    def __init__(self, key: str = KEY) -> None:
        self.key = key
        self.seen: list[httpx.Request] = []

    def page(self) -> str:
        return PAGE.replace(KEY, self.key)

    def answer(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"path": request.url.path})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        if request.url.path == "/app/":
            return httpx.Response(200, text=self.page())
        if request.headers.get(KEY_HEADER) != self.key:
            return httpx.Response(401, json={"detail": "Invalid or missing session key"})
        return self.answer(request)

    def api_calls(self) -> list[httpx.Request]:
        return [request for request in self.seen if request.url.path.startswith("/api/v1")]


def _client(service: Service, language: str = "de") -> ServiceClient:
    return ServiceClient(
        "http://service.test/", language, http=httpx.Client(transport=httpx.MockTransport(service))
    )


def test_the_key_is_read_from_the_served_page_and_sent_on_every_request():
    service = Service()
    client = _client(service)
    client.connect()
    assert client.key == KEY

    assert client.get("/health") == {"path": "/api/v1/health"}
    client.post("/chats", json={"title": "a"})
    client.put("/settings/a/b", json={"wert": 1})
    client.patch("/chats/1", json={"title": "b"})
    client.delete("/chats/1")

    calls = service.api_calls()
    assert [call.method for call in calls] == ["GET", "POST", "PUT", "PATCH", "DELETE"]
    assert all(call.headers[KEY_HEADER] == KEY for call in calls)
    assert all(call.headers[LANGUAGE_HEADER] == "de" for call in calls)
    assert json.loads(calls[1].content) == {"title": "a"}


def test_the_page_is_asked_for_in_the_clients_language_and_without_a_key():
    service = Service()
    _client(service, "en").connect()
    page_request = service.seen[0]
    assert page_request.url.path == "/app/"
    assert page_request.headers[LANGUAGE_HEADER] == "en"
    assert KEY_HEADER not in page_request.headers


def test_a_changed_language_travels_with_the_next_request():
    service = Service()
    client = _client(service, "de")
    client.connect()
    client.language = "en"
    client.get("/health")
    assert service.api_calls()[-1].headers[LANGUAGE_HEADER] == "en"


def test_a_page_without_a_key_and_a_missing_page_mean_no_service():
    class NoKey(Service):
        def page(self) -> str:
            return "<html><head></head></html>"

    with pytest.raises(ServiceUnreachable) as caught:
        _client(NoKey()).connect()
    assert caught.value.address == "http://service.test"

    def missing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "no interface"})

    client = ServiceClient(
        "http://service.test", "de", http=httpx.Client(transport=httpx.MockTransport(missing))
    )
    with pytest.raises(ServiceUnreachable):
        client.connect()


def test_a_refused_connection_and_an_unusable_address_mean_no_service():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=request)

    client = ServiceClient(
        "http://service.test", "de", http=httpx.Client(transport=httpx.MockTransport(refuse))
    )
    with pytest.raises(ServiceUnreachable):
        client.connect()
    with pytest.raises(ServiceUnreachable):
        ServiceClient("service.test:8090", "de").connect()


def test_a_refusal_carries_the_services_own_sentence():
    class Refusing(Service):
        def answer(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(422, json={"detail": "The value is out of range"})

    client = _client(Refusing())
    client.connect()
    with pytest.raises(ServiceError) as caught:
        client.put("/settings/a/b", json={"wert": 99})
    assert caught.value.status == 422
    assert caught.value.detail == "The value is out of range"
    assert str(caught.value) == "The value is out of range"


def test_a_refused_key_is_read_again_once_and_the_request_repeated():
    service = Service()
    client = _client(service)
    client.connect()
    # The service was restarted: it mints a new key and serves it on its page.
    service.key = "key-after-the-restart"

    assert client.get("/health") == {"path": "/api/v1/health"}
    assert client.key == "key-after-the-restart"
    paths = [request.url.path for request in service.seen]
    assert paths == ["/app/", "/api/v1/health", "/app/", "/api/v1/health"]


def test_a_key_that_stays_refused_ends_in_the_refusal_not_in_a_loop():
    class NeverRight(Service):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            self.seen.append(request)
            if request.url.path == "/app/":
                return httpx.Response(200, text=self.page())
            return httpx.Response(401, json={"detail": "Invalid or missing session key"})

    service = NeverRight()
    client = _client(service)
    client.connect()
    with pytest.raises(ServiceError) as caught:
        client.get("/health")
    assert caught.value.status == 401
    assert len(service.api_calls()) == 2


def test_no_content_reads_as_nothing():
    class Empty(Service):
        def answer(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(204)

    client = _client(Empty())
    client.connect()
    assert client.delete("/chats/1") is None


def test_an_answer_that_is_no_json_does_not_come_from_the_service():
    class Stranger(Service):
        def answer(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>some other program</html>")

    client = _client(Stranger())
    client.connect()
    with pytest.raises(ServiceUnreachable):
        client.get("/health")


def test_the_whole_answer_is_there_for_whoever_reads_its_headers():
    class Counted(Service):
        def answer(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[], headers={"X-Total-Count": "12"})

    client = _client(Counted())
    client.connect()
    response = client.request("GET", "/chats/1/messages", params={"neueste": "true"})
    assert response.headers["X-Total-Count"] == "12"
    assert service_query(response) == "neueste=true"


def test_a_body_can_be_read_together_with_the_headers_beside_it():
    class Counted(Service):
        def answer(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"rows": [1, 2]}, headers={"X-Total-Count": "12"})

    client = _client(Counted())
    client.connect()
    body, headers = client.get_with_headers("/chats/1/messages", params={"neueste": "true"})
    assert body == {"rows": [1, 2]}
    assert headers["X-Total-Count"] == "12"


def test_a_body_read_with_its_headers_is_checked_like_any_other():
    class Stranger(Service):
        def answer(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>some other program</html>")

    client = _client(Stranger())
    client.connect()
    with pytest.raises(ServiceUnreachable):
        client.get_with_headers("/chats/1/messages")


def service_query(response: httpx.Response) -> str:
    return response.request.url.query.decode()


STREAM = (
    'data: {"typ": "start", "generation_id": "g1"}\n\n'
    ": a comment that only keeps the connection warm\n\n"
    'data: {"typ": "content", "text": "Hel"}\n\n'
    "data: not json at all\n\n"
    'data: ["a", "list"]\n\n'
    'data: {"typ": "content", "text": "lo — ö"}\n\n'
    'data: {"typ": "done", "abgebrochen": false}\n\n'
)


class Streaming(Service):
    def answer(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=STREAM.encode("utf-8"), headers={"content-type": "text/event-stream"}
        )


def test_a_stream_yields_one_event_per_data_line_and_nothing_for_the_rest():
    service = Streaming()
    client = _client(service)
    client.connect()
    events = list(client.stream("/chat/completions", {"chat_id": "c1", "content": "hi"}))
    assert [event["typ"] for event in events] == ["start", "content", "content", "done"]
    assert events[2]["text"] == "lo — ö"

    sent = service.api_calls()[-1]
    assert sent.method == "POST"
    assert sent.headers[KEY_HEADER] == KEY
    assert json.loads(sent.content) == {"chat_id": "c1", "content": "hi"}


def test_a_stream_can_be_asked_for_with_get_and_a_query():
    service = Streaming()
    client = _client(service)
    client.connect()
    list(client.stream("/chat/stream/g1", method="GET", params={"ab": 3}))
    sent = service.api_calls()[-1]
    assert sent.method == "GET"
    assert sent.url.query == b"ab=3"


def test_a_refused_stream_raises_the_services_sentence_before_the_first_event():
    class Busy(Service):
        def answer(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(409, json={"detail": "This chat is already answering"})

    client = _client(Busy())
    client.connect()
    with pytest.raises(ServiceError) as caught:
        list(client.stream("/chat/completions", {"chat_id": "c1"}))
    assert caught.value.detail == "This chat is already answering"


def test_a_stream_reads_the_key_again_after_a_restart():
    service = Streaming()
    client = _client(service)
    client.connect()
    service.key = "key-after-the-restart"
    events = list(client.stream("/chat/completions", {"chat_id": "c1"}))
    assert [event["typ"] for event in events][0] == "start"
    assert client.key == "key-after-the-restart"


def test_without_a_service_the_client_ends_with_one_sentence_naming_the_address(capsys, tmp_path):
    """At an address of another machine: at one of this machine the client
    would start the service instead (tests/cli/test_service.py)."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=request)

    code = main(
        ["--url", "http://100.100.0.9:1", "--lang", "en"],
        http=httpx.Client(transport=httpx.MockTransport(refuse)),
        prefs_path=tmp_path / "cli.json",
    )
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert captured.err.strip() == Texts("en").t(
        "fehler.dienst_antwortet_nicht", error="http://100.100.0.9:1"
    )
    assert len(captured.err.strip().splitlines()) == 1
    # An address that reached nothing is not remembered.
    assert not (tmp_path / "cli.json").exists()


# --- A service that demands a password ---------------------------------------
#
# Beyond the loopback address the page carries no key and asks to sign in
# (app/anmeldung.py); the client asks for the password once, buys the key
# with it and remembers the key for the address.

import threading
from pathlib import Path

from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from cli import main as cli_main
from cli import prefs

REMOTE = "http://100.100.0.9:8123"
PASSWORD = "open-sesame"
SIGN_IN_PAGE = (
    "<html><head><title>x</title>"
    "<script>window.__SITZUNGSSCHLUESSEL__=null;window.__ANMELDUNG__=true;"
    "window.__DIAGNOSE__=false;</script></head><body></body></html>"
)


class Guarded(Service):
    """The stand-in beyond the loopback address: no key in the page, the
    key only against the password, and every request kept — with the
    four addresses the client talks to after signing in."""

    def __init__(self, key: str = KEY, password: str = PASSWORD) -> None:
        super().__init__(key)
        self.password = password

    def page(self) -> str:
        return SIGN_IN_PAGE

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        path = request.url.path
        if path == "/app/":
            return httpx.Response(200, text=self.page())
        if path == "/api/v1/login":
            sent = json.loads(request.content).get("password")
            if sent != self.password:
                return httpx.Response(401, json={"detail": "Wrong password"})
            return httpx.Response(200, json={"key": self.key})
        if request.headers.get(KEY_HEADER) != self.key:
            return httpx.Response(401, json={"detail": "Invalid or missing session key"})
        if path == "/api/v1/health":
            return httpx.Response(200, json={"status": "ok", "version": "9.8.7"})
        if path == "/api/v1/models":
            return httpx.Response(200, json=[])
        if path == "/api/v1/chats" and request.method == "POST":
            return httpx.Response(201, json={"id": "chat-1", "title": "A fresh chat"})
        return httpx.Response(404, json={"detail": "No such address"})

    def logins(self) -> list[str]:
        return [
            json.loads(request.content).get("password")
            for request in self.seen
            if request.url.path == "/api/v1/login"
        ]


def test_a_page_that_asks_to_sign_in_leaves_the_client_without_a_key_but_connected():
    client = _client(Guarded())
    client.connect()
    assert client.key is None
    assert client.login_required is True


def test_a_page_with_the_key_means_no_sign_in():
    client = _client(Service())
    client.connect()
    assert client.login_required is False


def test_login_sends_the_password_and_keeps_the_key():
    service = Guarded()
    client = _client(service)
    client.connect()
    assert client.login(PASSWORD) == KEY
    assert client.key == KEY
    assert service.logins() == [PASSWORD]
    # From here on the key travels like one that came with the page.
    client.get("/health")
    assert service.seen[-1].headers[KEY_HEADER] == KEY


def test_a_wrong_password_is_the_services_own_refusal():
    client = _client(Guarded())
    client.connect()
    with pytest.raises(ServiceError) as refused:
        client.login("open-sesam")
    assert refused.value.status == 401
    assert refused.value.detail == "Wrong password"
    assert client.key is None


def test_a_sign_in_answered_without_a_key_does_not_come_from_the_service():
    def odd(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/app/":
            return httpx.Response(200, text=SIGN_IN_PAGE)
        return httpx.Response(200, json={"something": "else"})

    client = ServiceClient("http://service.test", "en", http=httpx.Client(transport=httpx.MockTransport(odd)))
    client.connect()
    with pytest.raises(ServiceUnreachable):
        client.login(PASSWORD)


def _start(typed: str, *arguments: str, service: Guarded, tmp_path: Path) -> int:
    """The whole client against the guarded stand-in, ``typed`` already in
    its input, the choices in a file of this test's own."""
    with create_pipe_input() as pipe:
        pipe.send_text(typed)
        safety_net = threading.Timer(20, pipe.close)
        safety_net.start()
        try:
            with create_app_session(input=pipe, output=DummyOutput()):
                return cli_main.main(
                    ["--url", REMOTE, "--lang", "en", *arguments],
                    http=httpx.Client(transport=httpx.MockTransport(service)),
                    prefs_path=tmp_path / "cli.json",
                )
        finally:
            safety_net.cancel()


@pytest.fixture
def terminal(monkeypatch):
    """A terminal to type the password on: what was typed, counted."""
    asked: list[str] = []

    def ask(prompt: str) -> str:
        asked.append(prompt)
        return getattr(ask, "answer", PASSWORD)

    monkeypatch.setattr(cli_main, "_ask_password", ask)
    return asked


def test_a_remote_service_that_demands_a_password_asks_once_and_remembers_the_key(
    terminal, tmp_path
):
    service = Guarded()
    assert _start("/quit\r", service=service, tmp_path=tmp_path) == 0
    assert terminal == ["Password for http://100.100.0.9:8123: "]
    assert service.logins() == [PASSWORD]
    assert prefs.load(tmp_path / "cli.json")["keys"] == {REMOTE: KEY}

    # The second start: the remembered key, no question, no sign-in.
    again = Guarded()
    assert _start("/quit\r", service=again, tmp_path=tmp_path) == 0
    assert len(terminal) == 1
    assert again.logins() == []
    assert again.seen[-1].headers.get(KEY_HEADER) == KEY


def test_a_remembered_key_the_service_no_longer_takes_is_bought_anew(terminal, tmp_path):
    prefs.save({"keys": {REMOTE: "key-of-a-run-that-is-over"}}, tmp_path / "cli.json")
    service = Guarded(key="key-of-this-run")
    assert _start("/quit\r", service=service, tmp_path=tmp_path) == 0
    assert len(terminal) == 1
    assert service.logins() == [PASSWORD]
    assert prefs.load(tmp_path / "cli.json")["keys"] == {REMOTE: "key-of-this-run"}


def test_a_password_file_signs_in_without_asking(terminal, tmp_path):
    file = tmp_path / "password.txt"
    file.write_text(PASSWORD + "\n", encoding="utf-8")
    service = Guarded()
    assert _start("/quit\r", "--password-file", str(file), service=service, tmp_path=tmp_path) == 0
    assert terminal == []
    assert service.logins() == [PASSWORD]


def test_without_a_terminal_the_client_names_the_password_file_and_ends(
    tmp_path, capsys, monkeypatch
):
    """Under the test runner stdin is no terminal — exactly the case."""
    monkeypatch.setattr(cli_main.sys.stdin, "isatty", lambda: False, raising=False)
    service = Guarded()
    assert _start("", service=service, tmp_path=tmp_path) == 1
    assert service.logins() == []
    err = capsys.readouterr().err
    # The sentence with the address in it, and an example that can be typed
    # as it stands.
    assert "http://100.100.0.9:8123 requires a password" in err
    assert "--password-file password.txt" in err
    assert not (tmp_path / "cli.json").exists()


def test_a_wrong_password_ends_the_client_with_the_services_sentence(
    terminal, tmp_path, capsys
):
    terminal_ask = cli_main._ask_password
    terminal_ask.answer = "open-sesam"
    service = Guarded()
    assert _start("", service=service, tmp_path=tmp_path) == 1
    assert terminal == ["Password for http://100.100.0.9:8123: "]
    assert "Wrong password" in capsys.readouterr().err
    assert not (tmp_path / "cli.json").exists()


def test_a_local_service_never_asks(terminal, tmp_path):
    """The quiet case: the page carries the key, nothing is asked, nothing
    is remembered under ``keys``."""
    service = Service()

    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/health":
            return httpx.Response(200, json={"status": "ok", "version": "9.8.7"})
        if request.url.path == "/api/v1/models":
            return httpx.Response(200, json=[])
        if request.url.path == "/api/v1/chats" and request.method == "POST":
            return httpx.Response(201, json={"id": "chat-1", "title": "A fresh chat"})
        return httpx.Response(404, json={"detail": "No such address"})

    service.answer = answer  # type: ignore[method-assign]
    assert _start("/quit\r", service=service, tmp_path=tmp_path) == 0
    assert terminal == []
    assert prefs.load(tmp_path / "cli.json").get("keys") is None
