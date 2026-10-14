"""The chat: which one is open, what its history says, and one round of it
— a message goes out, the answer comes back as a stream of events, and
every event is handed to whoever shows it.

A round runs in the screen's worker and blocks it until the answer is over.
That is what makes a second message wait its turn.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Iterator, Mapping
from typing import Any
from urllib.parse import quote

from cli import service, themes
from cli.client import ServiceError, ServiceUnreachable
from cli.interfaces import Context, Event
from cli.render import clock

# How many chats the search for a title may bring back at once — the most the
# service hands out in one page.
_CHAT_PAGE = 500

# A chat is named after the first line of its first message, cut to at most
# this many characters at a word end — the rule the window holds as well.
_TITLE_LENGTH = 48

# The words the service gives a chat it creates without a title.
_FRESH_TITLE = "chat.unbenannt"


# --- Which chat is open ---------------------------------------------------------


def new_chat(ctx: Context) -> None:
    """Makes a new chat the open one.

    The service is not told. A chat comes into being there with the first
    thing that is written into it (``service_chat``), the way the window
    makes its chats: a client that is started and left again, or a new chat
    nobody wrote into, leaves nothing in the list of chats. Until then the
    status line names it the way the service names a fresh chat.
    """
    ctx.session.chat = None
    ctx.session.unnamed = True
    ctx.screen.update_status(chat_title=fresh_title(ctx))


def fresh_title(ctx: Context) -> str:
    """What a new chat goes by until its first message names it: the words
    the service gives a chat it creates without a title."""
    return ctx.texts.t(_FRESH_TITLE)


def service_chat(ctx: Context) -> dict[str, Any]:
    """The open chat as the service has it — created there now, where the
    open one is a new chat: something is about to be written into it.

    No title is sent: the service names a fresh chat itself, in the language
    of the request, and its first message names it after that. The model
    goes along, so the window shows the chat with the same one. The folder
    the client was started in follows at once, as the folder the chat
    works in (``_work_in_start_folder``).
    """
    session = ctx.session
    if session.chat is None:
        wanted = {"endpoint_id": session.endpoint_id} if session.endpoint_id else {}
        created: dict[str, Any] = ctx.client.post("/chats", json=wanted)
        session.chat = created
        ctx.screen.update_status(chat_title=created.get("title"))
        _work_in_start_folder(ctx, created)
    return session.chat


def _work_in_start_folder(ctx: Context, created: Mapping[str, Any]) -> None:
    """Makes the folder the client was started in the working folder of the
    chat it has just created, on the way the window shares a folder with a
    chat: the model then works where the user is, not in the chat's own
    folder among the program's data. The client never leaves the folder
    it was started in, so that is the one it stands in now.

    Only in a terminal of the user's own, and only at a service that runs
    on this machine. Started by the window, the client stands in no folder
    the user chose: there a new chat keeps its own folder, and the user
    shares others in the window. And a service elsewhere checks a folder
    on its own machine, where this one does not lie. Where the service
    runs, the name of its address does not say: a forwarded port answers
    under a name of this machine, and this machine's service under any of
    its addresses. So the service is asked which process it is, and the
    folder goes out only where that process is one of this machine
    (``service.runs_here``). A chat that is opened, not created, never
    comes by here and keeps the folders it has.

    A folder the service refuses costs the chat nothing: the service's
    sentence stands above the input field, and the message goes out.
    """
    if themes.WINDOW_VARIABLE in os.environ:
        return
    try:
        folder = os.getcwd()
    except OSError:
        # The folder is gone from under the client: there is none to share.
        return
    try:
        if not service.runs_here(ctx.client.get("/health")):
            return
    except (ServiceError, ServiceUnreachable):
        # A service that does not say which process it is gets no folder;
        # what keeps it from saying so, the message that follows meets too.
        return
    try:
        ctx.session.chat = ctx.client.patch(
            f"/chats/{created['id']}", json={"working_dirs": [folder]}
        )
    except ServiceError as error:
        ctx.renderer.notice(error.detail)
    except ServiceUnreachable:
        # If the service is really gone, the message that follows says so.
        return


def find_chat(ctx: Context, wanted: str) -> dict[str, Any] | None:
    """The chat a user names: by its id, else by its title, upper and lower
    case aside.

    Returns ``None`` where nothing or more than one chat answers to the
    name, after saying so — and, where there are several, listing them.
    """
    try:
        found = read_chat(ctx, wanted)
    except ServiceError as error:
        if error.status != 404:
            raise
    else:
        if isinstance(found, dict) and found.get("id") == wanted:
            return found
    listed = ctx.client.get("/chats", params={"suche": wanted, "limit": _CHAT_PAGE})
    matches = [
        chat
        for chat in listed
        if str(chat.get("title") or "").casefold() == wanted.casefold()
    ]
    if len(matches) == 1:
        match: dict[str, Any] = matches[0]
        return match
    if not matches:
        ctx.renderer.error(ctx.texts.t("cli.chat_unbekannt", name=wanted))
        return None
    for chat in matches:
        ctx.renderer.remark(f"{chat.get('title')}  {chat.get('id')}  {chat.get('updated_at')}")
    return None


def read_chat(ctx: Context, chat_id: str) -> Any:
    """The chat of that id as the service has it right now."""
    # Quoted, so that whatever was typed stays one piece of the address.
    return ctx.client.get(f"/chats/{quote(chat_id, safe='')}")


def open_chat(ctx: Context, chat: Mapping[str, Any]) -> None:
    """Makes ``chat`` the open one and writes its newest messages into the
    history, under one line that says how many of all of them these are."""
    enter_chat(ctx, chat)
    show_history(ctx, chat)


def enter_chat(ctx: Context, chat: Mapping[str, Any]) -> None:
    """Makes ``chat`` the open one: the next message goes into it, and to
    the model it remembers where the service lists that one. It keeps the
    name it has."""
    session = ctx.session
    session.chat = dict(chat)
    session.unnamed = False
    ctx.screen.update_status(chat_title=chat.get("title"))
    _settle_model(ctx)


def show_history(ctx: Context, chat: Mapping[str, Any]) -> int:
    """Writes the chat's newest messages into the history, under one line
    that says how many of all of them these are, and returns how many it
    wrote. A chat nobody has written into has nothing to count: it gets no
    line at all."""
    page, headers = ctx.client.get_with_headers(
        f"/chats/{chat['id']}/messages", params={"neueste": "true"}
    )
    messages = page.get("nachrichten") if isinstance(page, dict) else None
    if not isinstance(messages, list) or not messages:
        return 0
    # The status line shows how full the chat is from the first moment, not
    # only after the next answer: the number its newest message carries.
    tokens = stored_context_tokens(messages)
    if tokens is not None:
        ctx.screen.update_status(context_tokens=tokens)
    total = headers.get("X-Nachrichten-Gesamt") or str(len(messages))
    ctx.renderer.remark(f"{len(messages)}/{total} {ctx.texts.t('cli.messages')}")
    for message in messages:
        ctx.renderer.stored_message(message)
    return len(messages)


def stored_context_tokens(messages: list[Any]) -> int | float | None:
    """The tokens the context held at the newest message that carries a
    number — read in the order the window of Exe AI reads it: the message's
    own count, else the one in its statistics, else the usage's total, else
    the usage's two halves added (either half alone counts). ``None`` where
    no message carries one: nothing is made up."""
    for message in reversed(messages):
        if not isinstance(message, Mapping):
            continue
        tokens = _tokens_of(message)
        if tokens is not None:
            return tokens
    return None


def _number(value: Any) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _tokens_of(message: Mapping[str, Any]) -> int | float | None:
    own = _number(message.get("gesamt_tokens"))
    if own is not None:
        return own
    stats = message.get("stats")
    if not isinstance(stats, Mapping):
        return None
    counted = _number(stats.get("gesamt_tokens"))
    if counted is not None:
        return counted
    usage = stats.get("nutzung")
    if not isinstance(usage, Mapping):
        return None
    total = _number(usage.get("total_tokens"))
    if total is not None:
        return total
    prompt, completion = _number(usage.get("prompt_tokens")), _number(usage.get("completion_tokens"))
    if prompt is None and completion is None:
        return None
    return (prompt or 0) + (completion or 0)


def follow_context_size(ctx: Context) -> None:
    """Reads anew how large the service says the context of the model in
    use is, and hands that to the status line: the size can be changed in
    the service while this client runs. A model the service does not list
    right now — its server does not answer — keeps the size it had, and a
    service that does not answer changes nothing."""
    session = ctx.session
    try:
        listed = ctx.client.get("/models")
    except (ServiceError, ServiceUnreachable):
        return
    for model in listed if isinstance(listed, list) else []:
        if isinstance(model, dict) and model.get("id") == session.endpoint_id:
            size = model.get("context_tokens")
            # The entry kept from the last listing says the same from now
            # on: opening a chat reads the size from there.
            kept = session.model()
            if kept is not None:
                kept["context_tokens"] = size
            ctx.screen.update_status(context_window=size)
            return


def _settle_model(ctx: Context) -> None:
    """One model for the chat and for the next message.

    A chat that remembers a model the service lists keeps it, and the next
    message goes there. A chat that remembers none is given the model in
    use, so the window opens the same chat with the same model. A chat that
    remembers a model the service does not list right now is left as it is:
    opening a chat changes nothing about it. The next message goes to the
    model in use, and the service writes that to the chat when it does.
    """
    session = ctx.session
    chat = session.chat or {}
    remembered = chat.get("endpoint_id")
    for model in session.models:
        if remembered and model.get("id") == remembered:
            session.endpoint_id = remembered
            ctx.screen.update_status(
                model_name=model.get("name"), context_window=model.get("context_tokens")
            )
            return
    if not remembered and session.endpoint_id:
        session.chat = ctx.client.patch(
            f"/chats/{chat['id']}", json={"endpoint_id": session.endpoint_id}
        )


def _title_of(text: str) -> str:
    """The name a message gives a new chat: its first line, white space drawn
    to single blanks. A longer one ends at the last word end that fits and
    carries "…" behind it; one without a word end in the first
    ``_TITLE_LENGTH`` characters is cut at the limit."""
    line = re.split(r"\r\n|\r|\n", text.strip(), maxsplit=1)[0]
    words = " ".join(line.split())
    if len(words) <= _TITLE_LENGTH:
        return words
    head = words[:_TITLE_LENGTH]
    # A blank right behind the limit: the head already ends at a word end.
    end = len(head) if words[_TITLE_LENGTH] == " " else head.rfind(" ")
    return (head[:end] if end > 0 else head) + "…"


def _name_after(ctx: Context, text: str) -> None:
    """Names a fresh chat after its first message, the way the window does —
    otherwise every chat started here would sit in the window's list under
    the same placeholder. Called once the service has taken the message: a
    message it refused names nothing."""
    session = ctx.session
    chat = session.chat
    if not session.unnamed or chat is None:
        return
    session.unnamed = False
    title = _title_of(text)
    try:
        session.chat = ctx.client.patch(f"/chats/{chat['id']}", json={"title": title})
    except ServiceError as error:
        # The name is a convenience; the answer goes on without it.
        ctx.renderer.error(error.detail)
        return
    except ServiceUnreachable:
        # If the service is really gone, the answer's own stream says so.
        return
    ctx.screen.update_status(chat_title=title)


# --- One round ----------------------------------------------------------------


def send(ctx: Context, text: str) -> None:
    """Sends one message and follows the answer to its end. The first one
    of a new chat is what creates that chat on the service."""
    session = ctx.session
    ctx.renderer.user_message(text)
    chat = service_chat(ctx)
    message: dict[str, Any] = {"chat_id": chat["id"], "content": text}
    if session.endpoint_id:
        message["endpoint_id"] = session.endpoint_id
    if session.thinking is not None:
        message["thinking"] = session.thinking
    session.answering = True
    ctx.screen.set_activity(ctx.texts.t("status.erzeugt_antwort"))
    try:
        _Round(ctx, text).follow(ctx.client.stream("/chat/completions", message))
    finally:
        session.answering = False
        session.generation_id = None
        ctx.asker.cancel()
        ctx.screen.set_activity(None)


def stop(ctx: Context) -> None:
    """Asks the service to end the running answer of the open chat. The
    answer's own stream then closes with its last event, as always."""
    chat = ctx.session.chat
    if chat is None:
        return
    try:
        ctx.client.post("/chat/stop", json={"chat_id": chat["id"]})
    except ServiceUnreachable as error:
        ctx.renderer.error(ctx.texts.t("fehler.dienst_antwortet_nicht", error=error.address))
    except ServiceError as error:
        ctx.renderer.error(error.detail)


class _Round:
    """One answer while it streams in: counts its events, hands each one on
    and keeps the line above the status line saying what goes on."""

    def __init__(self, ctx: Context, text: str) -> None:
        self._ctx = ctx
        # The message this round answers.
        self._text = text
        # How many events of the run have arrived — the position a broken
        # stream is picked up from.
        self._seen = 0
        self._done = False
        # What the line above the status line says right now.
        self._said: str | None = None
        # The call the open question belongs to, while one is open.
        self._asked: Any = None

    def follow(self, events: Iterator[dict[str, Any]]) -> None:
        """Reads the stream to its last event. A stream that breaks off
        before that is attached to again, as long as each attempt brings
        the answer further; one that brings nothing ends the round with the
        sentence for a broken connection.

        Where not one event arrived, no answer ever began: what went wrong
        then is raised, for whoever sent the message to say."""
        ctx = self._ctx
        while True:
            before = self._seen
            try:
                for event in events:
                    self._seen += 1
                    self._handle(event)
                    if self._done:
                        return
            except ServiceUnreachable:
                if not self._seen:
                    raise
            except ServiceError as error:
                if not self._seen:
                    raise
                # The service no longer hands out the rest of this answer.
                self._break_off(error.detail)
                return
            finally:
                # Closes the connection now, not whenever the iterator
                # happens to be collected.
                closing = getattr(events, "close", None)
                if closing is not None:
                    closing()
            generation_id = ctx.session.generation_id
            if generation_id is None or self._seen == before:
                self._break_off(ctx.texts.t("fehler.strom_abriss"))
                return
            events = ctx.client.stream(
                f"/chat/stream/{generation_id}", method="GET", params={"ab": self._seen}
            )

    def _break_off(self, said: str) -> None:
        """Ends a round whose last event never came: says why, and closes
        the answer, so what had arrived of it is written out."""
        self._ctx.renderer.error(said)
        self._ctx.renderer.done({"typ": "done"})

    def _handle(self, event: Event) -> None:
        ctx = self._ctx
        kind = event.get("typ")
        if kind == "start":
            ctx.session.generation_id = event.get("generation_id")
            _name_after(ctx, self._text)
            ctx.renderer.start(event)
        elif kind == "content":
            self._say(ctx.texts.t("status.erzeugt_antwort"))
            ctx.renderer.content(str(event.get("text") or ""))
        elif kind == "reasoning":
            self._say_thinking()
            ctx.renderer.reasoning(str(event.get("text") or ""))
        elif kind == "tool_call_laeuft":
            self._say_tool(event)
        elif kind == "tool_call":
            self._say_tool(event)
            ctx.renderer.tool_call(event)
        elif kind == "tool_result":
            if event.get("aufruf_id") == self._asked:
                # The call the question was about is over — answered, or the
                # service stopped waiting. Another call's result leaves the
                # question standing.
                self._asked = None
                ctx.asker.cancel()
            self._say(ctx.texts.t("status.erzeugt_antwort"))
            ctx.renderer.tool_result(event)
        elif kind in ("tool_confirm", "user_ask"):
            self._ask(event)
        elif kind == "kontext":
            ctx.screen.update_status(context_tokens=event.get("gesamt_tokens"))
        elif kind == "error":
            ctx.renderer.error(str(event.get("text") or ""))
        elif kind == "stats":
            data = event.get("daten")
            ctx.renderer.stats(data if isinstance(data, Mapping) else {})
        elif kind == "done":
            self._done = True
            ctx.renderer.done(event)

    # --- The line above the status line ---

    def _say(self, text: str) -> None:
        """Sets the line, once per change — not once per piece of text."""
        if self._said != text:
            self._said = text
            self._ctx.screen.set_activity(text)

    def _say_thinking(self) -> None:
        """The line while the model thinks, with the time since it began."""
        if self._said == "thinking":
            return
        self._said = "thinking"
        since = time.monotonic()
        texts = self._ctx.texts
        self._ctx.screen.set_activity(
            lambda: texts.t("nachricht.gedankengang_laeuft", zeit=clock(time.monotonic() - since))
        )

    def _say_tool(self, event: Event) -> None:
        name = str(event.get("name") or "")
        key = f"tool:{event.get('aufruf_id') or name}"
        if self._said == key:
            return
        self._said = key
        since = time.monotonic()
        running = self._ctx.texts.t("werkzeug.laeuft", name=name)
        self._ctx.screen.set_activity(lambda: f"{running} {clock(time.monotonic() - since)}")

    # --- Questions ---

    def _ask(self, event: Event) -> None:
        """Puts a question of the service to the user without holding up
        the stream: the answer is awaited on a thread of its own, and the
        round goes on reading — so it sees it when the service gives up
        waiting, or the user stops the answer, and withdraws the question."""
        ctx = self._ctx
        generation_id = ctx.session.generation_id
        self._asked = event.get("aufruf_id")

        def answer() -> None:
            asked = ctx.asker.confirm_tool if event.get("typ") == "tool_confirm" else ctx.asker.ask_user
            given = asked(event)
            if given is None or generation_id is None:
                return
            reply = {"generation_id": generation_id, "aufruf_id": event.get("aufruf_id"), **given}
            if event.get("name"):
                reply["name"] = event.get("name")
            try:
                ctx.client.post("/chat/confirm", json=reply)
            except ServiceUnreachable as error:
                ctx.renderer.error(
                    ctx.texts.t("fehler.dienst_antwortet_nicht", error=error.address)
                )
            except ServiceError as error:
                ctx.renderer.error(error.detail)

        threading.Thread(target=answer, daemon=True).start()
