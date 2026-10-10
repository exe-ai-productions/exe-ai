"""The endpoint of the test configuration that is not there.

Nearly every test starts the service against an endpoint nothing listens on.
The refusal comes from the HTTP transport itself (``tests/conftest.py``), so
that it costs the same on every system — Windows takes a second or two to
refuse a connection, and the suite asks thousands of times.
"""

from __future__ import annotations

import http.server
import socket
import threading

import httpx
import pytest

from tests.conftest import ABSENT_ENDPOINT

URL = "http://%s:%d/v1/models" % ABSENT_ENDPOINT


@pytest.fixture
def no_network(monkeypatch):
    def asked(*args, **kwargs):
        raise AssertionError("the network was asked")

    monkeypatch.setattr(socket.socket, "connect", asked)
    monkeypatch.setattr(socket.socket, "connect_ex", asked)


def test_the_absent_endpoint_refuses_without_asking_the_network(no_network):
    with pytest.raises(httpx.ConnectError):
        httpx.get(URL)


async def test_the_absent_endpoint_refuses_the_async_client_too(no_network):
    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.ConnectError):
            await client.get(URL)


class _Quiet(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


def test_an_address_where_something_listens_is_still_reached():
    """The silence probe: only the absent endpoint is answered here."""
    server = http.server.HTTPServer(("127.0.0.1", 0), _Quiet)
    threading.Thread(target=server.handle_request, daemon=True).start()
    try:
        answer = httpx.get(f"http://127.0.0.1:{server.server_port}/", timeout=10)
    finally:
        server.server_close()
    assert answer.status_code == 204
