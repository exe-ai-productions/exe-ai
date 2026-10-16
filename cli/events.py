"""The service's own event stream: what happens there without this client
having asked for it — a model server changing its state, a scheduled run
beginning, a history being compressed.

One thread keeps the stream open for as long as the client runs. What
arrives goes to ``handle``: what concerns the models to the status line,
the rest as one quiet line into the history. When the stream breaks, the
thread waits and connects again, longer after every attempt that failed,
and the status line says that the client is reconnecting until the stream
stands again — and that it is disconnected while the service has never
answered at all.

The stream repeats nothing. So every connection begins by asking for the
one thing it only ever reports as a change: the word for the server behind
each model — active, idle or offline — which rides on the model list.
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
from typing import Any

from cli import glyphs, themes
from cli.client import ServiceError
from cli.interfaces import Context, Event, EventSink
from cli.status import ACTIVE, CONNECTED, DISCONNECTED, IDLE, OFFLINE, RECONNECTING, server_of
from cli.texts import available_languages

EVENT_PATH = "/events/stream"
# Every model the service knows, the unreachable ones included: a server
# that is down right now has a word too, and the line owes it the word.
MODELS_PATH = "/models?alle=true"
# The three words the service uses for the server behind a model.
SERVER_STATES = (ACTIVE, IDLE, OFFLINE)

# On the stream's address the service takes its key as a query parameter.
KEY_PARAMETER = "schluessel"

# How often the service sends a sign of life over a stream with nothing to
# report.
HEARTBEAT_SECONDS = 20.0

# A stream that stayed silent for three of them is dead, whatever the
# connection claims; one or two may simply be late. Every line that arrives
# — a sign of life as much as an event — starts the count again.
READ_TIMEOUT_SECONDS = 3 * HEARTBEAT_SECONDS

# The wait before connecting again: this long after a break, twice as long
# after every further attempt that failed, and never longer than the last.
FIRST_PAUSE_SECONDS = 1.0
LONGEST_PAUSE_SECONDS = 30.0



def build_events(ctx: Context) -> ServiceEvents:
    return ServiceEvents(ctx)


class ServiceEvents(EventSink):
    """Listens to the service's event stream in a thread of its own."""

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx
        self._leaving = threading.Event()
        self._thread: threading.Thread | None = None
        # The models the service reported as gone since this connection
        # began, by their id.
        self._gone: set[str] = set()
        # The word for the server behind each model, by the server's id —
        # asked for once per connection, off the model list, then kept up by
        # the announcements, which name the server.
        self._states: dict[str, str] = {}
        # Whether the service has answered this client at all. Before that,
        # a connection that is not there is one that never was; after it,
        # one that is being made again.
        self._answered = False

    # --- Listening --------------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._listen, name="cli-events", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        # The thread sees it at its next step. Where it waits inside a read,
        # it ends when the read does — at once, where the client hangs up —
        # and nothing it still does is shown.
        self._leaving.set()

    def wait(self, until: float) -> None:
        """Waits until the listening thread is over — no longer than until
        ``until`` on the monotonic clock. For leaving, after the listener
        was stopped and the client has hung up: by then no stream holds the
        thread in a read."""
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(max(0.0, until - time.monotonic()))

    def _listen(self) -> None:
        pause = FIRST_PAUSE_SECONDS
        while not self._leaving.is_set():
            held = self._connection()
            if self._leaving.is_set():
                return
            # What the stream said is only known to hold while it stands.
            self._gone.clear()
            self._states.clear()
            self._ctx.screen.update_status(
                connection=RECONNECTING if self._answered else DISCONNECTED,
                server_states={},
                unreachable_models=frozenset(),
            )
            if held >= pause:
                # A stream that held at least as long as the wait before it
                # was a connection, and the waits start over. One that broke
                # sooner was one more attempt that failed.
                pause = FIRST_PAUSE_SECONDS
            self._leaving.wait(pause)
            pause = min(2 * pause, LONGEST_PAUSE_SECONDS)

    def _connection(self) -> float:
        """One connection, from its first request to its end. Returns how
        long its stream held — nothing where it never got that far."""
        client = self._ctx.client
        opened: float | None = None
        try:
            found = self._arrive()

            def stands() -> None:
                # Only now is the client connected: the service answering a
                # question says that it is there, not that it lets this
                # client listen.
                self._ctx.screen.update_status(connection=CONNECTED, **found)

            opened = time.monotonic()
            events = client.stream(
                EVENT_PATH,
                method="GET",
                params={KEY_PARAMETER: client.key},
                read_timeout=READ_TIMEOUT_SECONDS,
                opened=stands,
            )
            try:
                for event in events:
                    if self._leaving.is_set():
                        break
                    self._take(event)
            finally:
                # Closes the connection now, not whenever the iterator
                # happens to be collected.
                closing = getattr(events, "close", None)
                if closing is not None:
                    closing()
        except Exception:  # noqa: BLE001
            # The service gone, a refusal, a connection closed under the
            # read: whatever ended it, the answer is the same — say that the
            # service is not connected, and try again. A background thread
            # has nobody to raise to.
            pass
        return time.monotonic() - opened if opened is not None else 0.0

    def _take(self, event: Event) -> None:
        """Hands one event on. An event that cannot be shown must not cost
        the connection, and the next one still has to be heard: what went
        wrong is shown in its place."""
        try:
            self.handle(event)
        except Exception as error:  # noqa: BLE001
            # Where even that cannot be written, there is nobody left to tell.
            with contextlib.suppress(Exception):
                self._ctx.renderer.error(f"{type(error).__name__}: {error}")

    def _arrive(self) -> dict[str, Any]:
        """Asks once per connection for what the stream will only report as
        a change, and returns what the status line is to show of it once
        the stream stands. An answer at all says that the service is there."""
        try:
            models = self._ctx.client.get(MODELS_PATH)
        except ServiceError:
            # The service answers, it just does not hand out its model list.
            # The stream is worth having all the same.
            models = None
        self._answered = True
        if not isinstance(models, list):
            return {}
        for model in models:
            if isinstance(model, dict) and isinstance(model.get("id"), str):
                self._remember_state(server_of(model["id"]), model.get("server_state"))
        return {"server_states": dict(self._states)}

    def _remember_state(self, endpoint: Any, state: Any) -> bool:
        """Keeps one server's word, if it is a word the line can show."""
        if not isinstance(endpoint, str) or not endpoint or state not in SERVER_STATES:
            return False
        self._states[endpoint] = state
        return True

    # --- What an event means ----------------------------------------------------

    def handle(self, event: Event) -> None:
        if self._leaving.is_set():
            return
        kind = event.get("typ")
        if kind == "server_state":
            self._server_state(event)
        elif kind == "endpunkt_status":
            self._endpoint(event)
        elif kind == "window_theme":
            self._window_theme(event)
        else:
            line = self._line(str(kind), event)
            if line:
                self._ctx.renderer.notice(line)

    def _window_theme(self, event: Event) -> None:
        """The window page shows another look or another language: inside its
        tab the client follows. A language is switched like ``/language``
        does — the sentences and the language of the requests — and a look
        like ``/theme`` does, writing the history again in the new colours;
        nothing is remembered, and the terminal's ground is left alone, the
        window paints it. A name the client does not know, the one in use,
        ``auto`` (a look read off the machine, not the window) and any event
        outside the window's tab change nothing."""
        if themes.WINDOW_VARIABLE not in os.environ:
            return
        self._follow_language(event.get("language"))
        self._follow_look(event.get("theme"))

    def _follow_language(self, name: Any) -> None:
        ctx = self._ctx
        if not isinstance(name, str) or name not in available_languages():
            return
        if name == ctx.texts.language:
            return
        ctx.texts.set_language(name)
        ctx.client.language = name
        # The fixed lines are written from the sentences again.
        ctx.screen.invalidate()

    def _follow_look(self, name: Any) -> None:
        if not isinstance(name, str) or name == themes.AUTO_LOOK or name not in themes.available():
            return
        if name == themes.current().name:
            return
        themes.set_look(name)
        # The window takes only the cursor from the look: its colour follows
        # the look the page has switched to.
        themes.paint()
        self._ctx.screen.update_status(look=themes.current().name)
        self._ctx.screen.redraw()

    def _server_state(self, event: Event) -> None:
        # One server's word changed. Which server the model in use sits on
        # is the status line's to say: the user may switch models at any time.
        if self._remember_state(event.get("endpoint_id"), event.get("server_state")):
            self._ctx.screen.update_status(server_states=dict(self._states))

    def _endpoint(self, event: Event) -> None:
        endpoint = event.get("endpoint_id")
        if not isinstance(endpoint, str) or not endpoint:
            return
        if event.get("erreichbar"):
            self._gone.discard(endpoint)
        else:
            self._gone.add(endpoint)
        # Which of them is the model in use is the status line's to say: the
        # user may switch models at any time.
        self._ctx.screen.update_status(unreachable_models=frozenset(self._gone))

    def _line(self, kind: str, event: Event) -> str | None:
        """The quiet line an event stands for in the history, or ``None``
        for an event that has none — the ones this client shows elsewhere,
        and the ones that concern another window."""
        texts = self._ctx.texts
        if kind == "verdichtung_laeuft":
            # Only the open chat's: another chat being compressed is the
            # business of whoever looks at that chat.
            if event.get("chat_id") != self._ctx.session.chat_id():
                return None
            return texts.t("status.komprimiert")
        if kind == "termin_gefeuert":
            return texts.t("cronjobs.gestartet")
        if kind == "auftrag_begonnen":
            return self._about_run(event, texts.t("jobs.zustand.laeuft"))
        if kind == "auftrag_fragt":
            if event.get("wartet"):
                agent = str(event.get("agent") or "")
                if not agent:
                    return texts.t("jobs.zustand.wartet")
                return texts.t("jobs.banner", agent=agent)
            # It was given its answer and is going again.
            return self._about_run(event, texts.t("jobs.zustand.laeuft"))
        if kind == "auftrag_beendet":
            return self._about_run(event, self._ending(event))
        return None

    def _ending(self, event: Event) -> str:
        """How a run ended, in words: the reason where there is one beyond
        having finished, else the state it ended in."""
        texts = self._ctx.texts
        outcome = str(event.get("ausgang") or "")
        reason = str(event.get("grund") or "")
        if reason and reason != outcome:
            key = f"jobs.grund.{reason}"
            worded = texts.t(key)
            # A run that died on an error carries the message itself as its
            # reason; that has no sentence in the catalogue and is shown as
            # it came.
            return reason if worded == key else worded
        return texts.t(f"jobs.zustand.{outcome}") if outcome else ""

    def _about_run(self, event: Event, said: str) -> str | None:
        """One line about a run: who, then what."""
        if not said:
            return None
        agent = str(event.get("agent") or "")
        if not agent:
            return said
        return f"{agent} {glyphs.glyph('separator')} {said}"
