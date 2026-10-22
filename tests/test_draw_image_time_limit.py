"""The drawing tool waits for the picture route as long as the route takes.

The picture route ends a picture at the time limit of the image-server page,
and with none set a picture ends with the image or with the run's stop. The
tool used to put a read bound of its own on the request (15 minutes); a long
picture ended in "Image generation timed out" while the painter went on and
the picture never reached the chat.

A bound is only enforced on a real socket, so these tests run the tool
against a small HTTP server of their own, in the same event loop, with the
bound cut down to a fraction of a second.
"""

from __future__ import annotations

import asyncio
import json

from app.tools import bild_werkzeug

# The tool's bound (``ZEITFENSTER_S``) in these tests, and how long the route
# keeps the picture: several times the bound.
BOUND_S = 0.3
DRAWING_S = 1.2


class _PictureRoute:
    """A picture route that answers over a real socket.

    ``/bild`` answers after ``drawing_s``, or earlier when a stop reached
    ``/bild/stop`` — with the status the real route gives a stopped picture.
    """

    def __init__(self, drawing_s: float, models_delay_s: float = 0.0):
        self.drawing_s = drawing_s
        self.models_delay_s = models_delay_s
        self.stops = 0
        self.drawn: list[dict] = []
        self.started = asyncio.Event()
        self._stopped = asyncio.Event()
        self._server: asyncio.AbstractServer | None = None

    async def __aenter__(self) -> str:
        self._server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        port = self._server.sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}"

    async def __aexit__(self, *exception) -> bool:
        assert self._server is not None
        self._server.close()
        await self._server.wait_closed()
        return False

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = (await reader.readuntil(b"\r\n\r\n")).decode("latin-1")
            method, target = head.split("\r\n", 1)[0].split(" ")[:2]
            length = 0
            for line in head.split("\r\n")[1:]:
                if line.lower().startswith("content-length:"):
                    length = int(line.split(":", 1)[1])
            body = json.loads(await reader.readexactly(length)) if length else None
            status, answer = await self._answer(method, target.split("?")[0], body)
            payload = json.dumps(answer).encode()
            writer.write(
                f"HTTP/1.1 {status} X\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode()
                + payload
            )
            await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    async def _answer(self, method: str, path: str, body):
        if path.endswith("/bild/modelle"):
            if self.models_delay_s:
                await asyncio.sleep(self.models_delay_s)
            return 200, {
                "programm_da": True, "modelle": ["a.safetensors"], "families": {},
                "standardmodell": "a.safetensors",
            }
        if path.endswith("/bild/prompt"):
            return 200, {"prompt": body["prompt"], "negativ": body.get("negativ", "")}
        if path.endswith("/bild/stop"):
            self.stops += 1
            self._stopped.set()
            return 200, True
        if path.endswith("/bild") and method == "POST":
            self.drawn.append(body)
            self.started.set()
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self.drawing_s)
            except asyncio.TimeoutError:
                return 200, {"bild": "out.png", "seed": 7}
            return 499, {"detail": "Image generation canceled"}
        return 200, {}


def test_a_picture_that_takes_longer_than_the_old_bound_still_arrives(tmp_path, monkeypatch):
    """The route answers only after the tool's bound has long passed: the tool
    waits, and the picture is reported — not a timeout."""
    monkeypatch.setattr(bild_werkzeug, "ZEITFENSTER_S", BOUND_S)

    async def run() -> tuple[str, _PictureRoute]:
        route = _PictureRoute(DRAWING_S)
        async with route as basis:
            text = await asyncio.wait_for(
                bild_werkzeug.ausfuehren({"prompt": "a dog"}, basis, tmp_path, "key"),
                timeout=10,
            )
        return text, route

    text, route = asyncio.run(run())
    assert text.startswith("The image was generated"), text
    assert "timed out" not in text
    # One request only: the route drew once and was not asked again.
    assert len(route.drawn) == 1


def test_a_stop_while_the_picture_waits_ends_it_as_before(tmp_path, monkeypatch):
    """Without a read bound the stop is the way out: the route is asked to
    end the picture and answers with the sentence for a stopped one."""
    monkeypatch.setattr(bild_werkzeug, "ZEITFENSTER_S", BOUND_S)
    monkeypatch.setattr(bild_werkzeug, "STOPP_TAKT_S", 0.05)

    async def run() -> tuple[str, _PictureRoute]:
        route = _PictureRoute(drawing_s=60)
        async with route as basis:
            stop = asyncio.Event()
            task = asyncio.ensure_future(
                bild_werkzeug.ausfuehren(
                    {"prompt": "a dog"}, basis, tmp_path, "key", chat_id="c1", abbruch=stop,
                )
            )
            await asyncio.wait_for(route.started.wait(), timeout=10)
            # Past the old bound, and the tool is still waiting.
            await asyncio.sleep(BOUND_S * 2)
            assert not task.done()
            stop.set()
            text = await asyncio.wait_for(task, timeout=10)
        return text, route

    text, route = asyncio.run(run())
    assert text == "The image could not be generated: Image generation canceled"
    assert route.stops >= 1


def test_the_other_calls_keep_their_bound(tmp_path, monkeypatch):
    """Only the picture request is left without a read bound: the model list
    that does not answer within the bound is still a failure with its reason."""
    monkeypatch.setattr(bild_werkzeug, "ZEITFENSTER_S", BOUND_S)

    async def run() -> tuple[str, _PictureRoute]:
        route = _PictureRoute(drawing_s=0.0, models_delay_s=DRAWING_S)
        async with route as basis:
            text = await asyncio.wait_for(
                bild_werkzeug.ausfuehren({"prompt": "a dog"}, basis, tmp_path, "key"),
                timeout=10,
            )
        return text, route

    text, route = asyncio.run(run())
    assert text == "The image could not be generated: ReadTimeout"
    assert route.drawn == []
