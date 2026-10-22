"""The one door to the service: every request of the client goes through here.

The service guards its API with a key it mints on every start and stitches
into the page it serves at ``/app/``. The client reads it from that page,
exactly as the window does, and sends it as a header on every request,
together with the language its own sentences should come in.
"""

from __future__ import annotations

import contextlib
import json
import re
import socket
import threading
from collections.abc import Callable, Iterator
from typing import Any

import httpx

API_PREFIX = "/api/v1"
KEY_HEADER = "X-Sitzungsschluessel"
LANGUAGE_HEADER = "X-Ui-Language"

# The key as the served page carries it: a JSON string assigned to one name.
_KEY_PATTERN = re.compile(r'window\.__SITZUNGSSCHLUESSEL__\s*=\s*("(?:[^"\\]|\\.)*")')
# A page without the key that asks to sign in instead: the service stands
# beyond the loopback address and hands the key out only against its
# password (app/anmeldung.py).
_LOGIN_PATTERN = re.compile(r"window\.__ANMELDUNG__\s*=\s*true")
LOGIN_PATH = "/login"

# Connecting is bounded by the HTTP library's own default of five seconds, so
# a wrong address is named quickly. Everything after that is unbounded, like
# the window's own requests: how long an answer takes is the service's call,
# and a pause between two events of a stream is no error.
CONNECT_SECONDS = 5.0
_TIMEOUT = httpx.Timeout(None, connect=CONNECT_SECONDS)


class ServiceUnreachable(Exception):
    """No service answers at the address, or it hands out no key."""

    def __init__(self, address: str) -> None:
        super().__init__(address)
        self.address = address


class InterfaceMissing(ServiceUnreachable):
    """A service answers at the address, but its interface is not built: the
    page the client reads the key from is missing, and the service says so in
    its own sentence. Waiting for it to come up would wait for ever."""

    def __init__(self, address: str, detail: str) -> None:
        super().__init__(address)
        self.detail = detail


class ServiceError(Exception):
    """The service refused a request; the message is its own sentence."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _detail(response: httpx.Response) -> str:
    """What the service said about a refused request, in its own words."""
    try:
        body = response.json()
    except ValueError:
        return response.text.strip() or str(response.status_code)
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, str) and detail:
        return detail
    return json.dumps(detail if detail is not None else body, ensure_ascii=False)


def _missing_interface(response: httpx.Response) -> str | None:
    """The sentence a service writes when its page is not built — a plain
    ``{"detail": "<sentence>"}`` with a 404 — or nothing for any other kind
    of 404."""
    try:
        body = response.json()
    except ValueError:
        return None
    detail = body.get("detail") if isinstance(body, dict) else None
    return detail if isinstance(detail, str) and detail else None


def _cut(response: httpx.Response) -> None:
    """Ends an answer that streams in under whoever reads it, from another
    thread. A read that waits on a socket is woken by shutting the socket
    down — closing it leaves the wait standing on some systems. It is the
    socket itself that is shut down, below any encryption on it: the reader
    then meets a connection that ended, whatever it reads through. An
    answer with no socket behind it is closed instead. Whatever goes wrong
    here is left alone: this only hurries an end that comes anyway."""
    with contextlib.suppress(Exception):
        stream = response.extensions.get("network_stream")
        connection = stream.get_extra_info("socket") if stream is not None else None
        if isinstance(connection, socket.socket):
            socket.socket.shutdown(connection, socket.SHUT_RDWR)
        else:
            response.close()


class ServiceClient:
    """Requests to one running service.

    ``http`` takes a ready HTTP client in place of the one built here; tests
    hand in one that never opens a connection.
    """

    def __init__(
        self, address: str, language: str, *, http: httpx.Client | None = None
    ) -> None:
        self.address = address.rstrip("/")
        self.language = language
        self.key: str | None = None
        # Whether the service hands its key out only against a password:
        # known once the page has been read.
        self.login_required = False
        # Set once a service that wants a password no longer takes this
        # client's key: the run the key was bought for is over, and only
        # the password buys a new one.
        self.signed_out = False
        # Called once at that moment, from whichever thread noticed.
        self.on_signed_out: Callable[[], None] | None = None
        self._http = http or httpx.Client(timeout=_TIMEOUT)
        # The answers that are streaming in right now, so that leaving can
        # end them under whoever reads them — and whether it has.
        self._streams: set[httpx.Response] = set()
        self._streams_lock = threading.Lock()
        self._hung_up = False

    def close(self) -> None:
        self._http.close()

    def hang_up(self) -> None:
        """Ends what this client still has open and asks for nothing more:
        every answer still streaming in ends for whoever reads it — in
        whichever thread — the way a service that went away ends it, and
        every later request is refused the same way without being sent.
        For leaving: no thread is left waiting on the service."""
        with self._streams_lock:
            self._hung_up = True
            streams = list(self._streams)
        for response in streams:
            _cut(response)

    @contextlib.contextmanager
    def _held_open(self, response: httpx.Response) -> Iterator[None]:
        """Keeps an answer that streams in where ``hang_up`` finds it, for
        as long as it is read. One that only arrives after the client has
        hung up is not read at all."""
        with self._streams_lock:
            if self._hung_up:
                raise ServiceUnreachable(self.address)
            self._streams.add(response)
        try:
            yield
        finally:
            with self._streams_lock:
                self._streams.discard(response)

    # --- The key --------------------------------------------------------------

    def connect(self) -> None:
        """Reads this run's key from the page the service serves — or
        learns that the page carries none and the service wants a password
        first (``login_required``; the key then comes from ``login``)."""
        try:
            response = self._http.get(
                f"{self.address}/app/", headers={LANGUAGE_HEADER: self.language}
            )
        except (httpx.HTTPError, httpx.InvalidURL) as error:
            raise ServiceUnreachable(self.address) from error
        if response.status_code == 404 and (sentence := _missing_interface(response)):
            raise InterfaceMissing(self.address, sentence)
        if response.status_code != 200:
            raise ServiceUnreachable(self.address)
        found = _KEY_PATTERN.search(response.text)
        if found is not None:
            self.key = json.loads(found.group(1))
            self.login_required = False
            return
        if _LOGIN_PATTERN.search(response.text) is None:
            raise ServiceUnreachable(self.address)
        self.key = None
        self.login_required = True

    def login(self, password: str) -> str:
        """Sends the password and keeps the key the service answers with.
        A wrong password is the service's own refusal (``ServiceError``)."""
        try:
            response = self._http.post(
                f"{self.address}{API_PREFIX}{LOGIN_PATH}",
                json={"password": password},
                headers={LANGUAGE_HEADER: self.language},
            )
        except (httpx.HTTPError, httpx.InvalidURL) as error:
            raise ServiceUnreachable(self.address) from error
        if not response.is_success:
            raise ServiceError(response.status_code, _detail(response))
        body = self._body(response)
        key = body.get("key") if isinstance(body, dict) else None
        if not isinstance(key, str) or not key:
            raise ServiceUnreachable(self.address)
        self.key = key
        self.signed_out = False
        return key

    def _key_refused(self, response: httpx.Response) -> ServiceError:
        """The refusal of a key that reading the page again cannot renew:
        the service wants its password for a new one. Says so, once, to
        whoever asked to be told, and returns what the request raises."""
        first = not self.signed_out
        self.signed_out = True
        if first and self.on_signed_out is not None:
            self.on_signed_out()
        return ServiceError(response.status_code, _detail(response))

    def _headers(self) -> dict[str, str]:
        headers = {LANGUAGE_HEADER: self.language}
        if self.key:
            headers[KEY_HEADER] = self.key
        return headers

    # --- Plain requests -------------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        content: bytes | None = None,
        content_type: str | None = None,
    ) -> httpx.Response:
        """One request below ``/api/v1``; the whole answer, for callers that
        read its headers. A refusal raises ``ServiceError``. ``content`` is
        a body of raw bytes, with its kind in ``content_type``.

        A refused key means the service was restarted and minted a new one:
        the key is read again and the request repeated, once. Where the
        service hands its key out only against a password, the page carries
        none to read: the refusal stands, and the client is signed out.
        """
        url = f"{self.address}{API_PREFIX}{path}"
        if self._hung_up:
            raise ServiceUnreachable(self.address)

        def headers() -> dict[str, str]:
            held = self._headers()
            if content_type:
                held["Content-Type"] = content_type
            return held

        try:
            response = self._http.request(
                method, url, json=json, params=params, content=content, headers=headers()
            )
            if response.status_code == 401:
                self.connect()
                if self.login_required:
                    raise self._key_refused(response)
                response = self._http.request(
                    method, url, json=json, params=params, content=content, headers=headers()
                )
        except (httpx.HTTPError, httpx.InvalidURL) as error:
            raise ServiceUnreachable(self.address) from error
        if not response.is_success:
            raise ServiceError(response.status_code, _detail(response))
        return response

    def _body(self, response: httpx.Response) -> Any:
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as error:
            # Whatever answers there with something that is no JSON is not
            # the service.
            raise ServiceUnreachable(self.address) from error

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return self._body(self.request("GET", path, params=params))

    def get_with_headers(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> tuple[Any, httpx.Headers]:
        """Like ``get``, with the answer's headers beside its body — for what
        the service says about a page next to the page itself."""
        response = self.request("GET", path, params=params)
        return self._body(response), response.headers

    def post(self, path: str, json: Any = None) -> Any:
        return self._body(self.request("POST", path, json=json))

    def upload(
        self,
        path: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Sends ``data`` as the raw body of a POST — a file, not JSON."""
        return self._body(
            self.request("POST", path, params=params, content=data, content_type=content_type)
        )

    def put(self, path: str, json: Any = None) -> Any:
        return self._body(self.request("PUT", path, json=json))

    def patch(self, path: str, json: Any = None) -> Any:
        return self._body(self.request("PATCH", path, json=json))

    def delete(self, path: str) -> Any:
        return self._body(self.request("DELETE", path))

    # --- Streams --------------------------------------------------------------

    def stream(
        self,
        path: str,
        json: Any = None,
        *,
        method: str = "POST",
        params: dict[str, Any] | None = None,
        read_timeout: float | None = None,
        opened: Callable[[], None] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """The events of a Server-Sent-Events answer, one dict per ``data:``
        line, as long as the service keeps sending.

        ``read_timeout`` bounds the wait for the next line; left out, the
        stream may stay silent for as long as it likes. ``opened`` is called
        once the service has answered the request with a stream, before the
        first line of it is read; a request it refuses never calls it.
        Closing the iterator closes the connection.
        """
        url = f"{self.address}{API_PREFIX}{path}"
        timeout = httpx.Timeout(None, connect=_TIMEOUT.connect, read=read_timeout)
        renewed = False
        while True:
            if self._hung_up:
                raise ServiceUnreachable(self.address)
            try:
                with self._http.stream(
                    method,
                    url,
                    json=json,
                    params=params,
                    headers=self._headers(),
                    timeout=timeout,
                ) as response:
                    if response.status_code == 401 and not renewed:
                        renewed = True
                        self.connect()
                        if self.login_required:
                            response.read()
                            raise self._key_refused(response)
                        continue
                    if not response.is_success:
                        response.read()
                        raise ServiceError(response.status_code, _detail(response))
                    with self._held_open(response):
                        if opened is not None:
                            opened()
                        for line in response.iter_lines():
                            event = _event(line)
                            if event is not None:
                                yield event
                    return
            except (httpx.HTTPError, httpx.InvalidURL) as error:
                raise ServiceUnreachable(self.address) from error


def _event(line: str) -> dict[str, Any] | None:
    """The event one line of a stream carries, or ``None`` for every line
    that is none — a blank separator, a comment that only keeps the
    connection warm, a ``data:`` line whose content is no JSON object."""
    if not line.startswith("data:"):
        return None
    try:
        event = json.loads(line[len("data:"):])
    except ValueError:
        return None
    return event if isinstance(event, dict) else None
