"""``/image``: a picture from one sentence.

The sentence goes to the service as it stands; every other value comes from
the picture window of the chat, as it does when the model draws. While the
picture is made the line above the status line says how far it is; the
interrupt key stops it. At the end the path of the finished picture stands
in the history — nothing is opened.
"""

from __future__ import annotations

import threading
from typing import Any

from cli import chat, servers
from cli.client import ServiceError
from cli.interfaces import Context

# How long the end of the request is waited for once the picture was
# stopped: the service answers the request it was drawing for.
_ENDED_SECONDS = 15.0


def run_command(ctx: Context, argument: str) -> None:
    texts = ctx.texts
    sentence = argument.strip()
    if not sentence:
        # No sentence typed: it is asked for, under the command's own words.
        typed = ctx.asker.ask_text(texts.t("cli.cmd_image").split("\n", 1)[0])
        sentence = (typed or "").strip()
    if not sentence:
        return
    listed = servers.image_listing(ctx)
    # Without a default model there is nothing to draw with: the program is
    # not offered and nothing goes to the service.
    if "standardmodell" in listed and not listed["standardmodell"]:
        ctx.renderer.notice(texts.t("cli.no_image_model"))
        return
    # The program first: where it is not there it is offered and fetched, as
    # `/server image` does, and the picture is drawn afterwards.
    if "programm_da" in listed and not listed["programm_da"]:
        with servers.waiting(ctx) as cancel:
            if not servers.fetch_image_program(ctx, cancel):
                return
    chat_id = str(chat.service_chat(ctx)["id"])
    _draw(ctx, sentence, chat_id)


def _draw(ctx: Context, sentence: str, chat_id: str) -> None:
    texts = ctx.texts
    outcome: dict[str, Any] = {}

    def request() -> None:
        try:
            outcome["answer"] = ctx.client.post(
                "/bild/satz", json={"prompt": sentence, "chat_id": chat_id}
            )
        except BaseException as error:  # handed to the thread that asked
            outcome["error"] = error

    worker = threading.Thread(target=request, daemon=True)
    worker.start()
    cancelled = False
    with servers.waiting(ctx) as cancel:
        ctx.screen.set_activity(texts.t("nachricht.bild_laeuft"))
        while worker.is_alive():
            if cancel.wait(servers.POLL_SECONDS):
                cancelled = True
                break
            _say_progress(ctx)
        if cancelled:
            try:
                ctx.client.post("/bild/stop")
            except ServiceError:
                pass
            worker.join(_ENDED_SECONDS)
    if cancelled:
        ctx.renderer.notice(texts.t("bild.abgebrochen"))
        return
    error = outcome.get("error")
    if error is not None:
        raise error
    answer = outcome.get("answer")
    path = answer.get("pfad") if isinstance(answer, dict) else None
    if isinstance(path, str) and path:
        ctx.renderer.notice(path)


def _say_progress(ctx: Context) -> None:
    """The line above the status line: the picture is being made, and how
    far the service says it is."""
    texts = ctx.texts
    word = texts.t("nachricht.bild_laeuft")
    try:
        state = ctx.client.get("/bild/fortschritt")
    except ServiceError:
        return
    share = state.get("anteil") if isinstance(state, dict) and state.get("laeuft") else None
    if isinstance(share, (int, float)) and not isinstance(share, bool) and share > 0:
        word = f"{word} {texts.t('bild.fortschritt_prozent', zahl=round(share * 100))}"
    ctx.screen.set_activity(word)
