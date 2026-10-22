"""What the modules of the terminal client may expect from each other.

Every part that can be swapped — what the history looks like, which
commands exist, how a question is asked, what the status line says, what
happens with the service's own events — is described here as a protocol
whose methods do nothing by default. A module fills in the ones it has
something to say about and inherits the rest, so a method added here later
never breaks a module written before it.

All of them are handed the same ``Context`` and reach each other through
it. The context is filled once at start (``cli/main.py``); a module keeps
it and looks up what it needs at the moment it needs it, never earlier.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, TypeAlias, TypeVar

if TYPE_CHECKING:
    from pathlib import Path

    from prompt_toolkit.completion import Completer
    from prompt_toolkit.formatted_text import StyleAndTextTuples
    from prompt_toolkit.key_binding import KeyBindingsBase
    from rich.console import RenderableType

    from cli.client import ServiceClient
    from cli.texts import Texts

_T = TypeVar("_T")

# One event of a stream, as the service sent it: ``typ`` plus its own fields.
Event = Mapping[str, Any]

# Text for the fixed block at the bottom: (style, text) pairs. A style names
# its classes as ``class:<name>``; the names are the ones ``cli/themes.py``
# lists, so the same word colours a piece of the status line and a line of
# the history.
Fragments: TypeAlias = "StyleAndTextTuples"

# One piece of a line shown above the input field: the name of its style —
# one of those ``cli/themes.py`` lists, without a prefix — and its text.
Piece = tuple[str, str]


class Screen(Protocol):
    """The terminal as the other modules may use it: the history that runs
    upwards and the fixed block below it. Safe to call from any thread."""

    def print_above(self, *renderables: RenderableType) -> None:
        """Adds to the history, above the fixed block — every renderable on
        lines of its own."""
        return None

    def invalidate(self) -> None:
        """Asks for the fixed block to be drawn again."""
        return None

    def set_activity(self, text: str | Callable[[], str] | None) -> None:
        """What the line above the status line says while something runs;
        the spinner turns beside its first line. A function is asked anew
        for every frame, so a running clock needs no caller of its own.
        ``None`` clears it — the line is empty and nothing is redrawn until
        something changes."""
        return None

    def set_notice(self, text: str | None) -> None:
        """A quiet word of the client in the line above the input field — a
        chat opened, a model chosen, a file saved. It stands there until the
        next line is sent or the next notice comes, and never goes into the
        history. While something runs, what runs stands in front of it."""
        return None

    def update_status(self, **fields: Any) -> None:
        """Hands the fields to the status line and draws it again."""
        return None

    def clear(self) -> None:
        """Empties the terminal window. The chat stays as it is. The
        emptying takes its place among the pieces of the history, whoever
        calls: what was written before goes with the window — a piece that
        is still on its way to the terminal included — and what is written
        after, such as an answer that still runs, stands in the emptied
        one."""
        return None

    def redraw(self) -> None:
        """Empties the terminal window and writes the open chat's history
        again, in the look in use now — the head, where nothing has been
        said in that chat yet. Beside a running answer the window is emptied
        at once and the history follows once the answer is over. What is
        kept for ``export`` begins anew with it."""
        return None

    def tool_finished(self) -> None:
        """The last open tool call of the running answer is over. A message
        that waited for it may cut the answer short now."""
        return None

    def exit(self) -> None:
        """Leaves the client."""
        return None

    def open_chat(self, chat: Mapping[str, Any]) -> None:
        """Makes that chat the open one and shows its history. While an
        answer runs, the switch waits for its end."""
        return None

    def new_chat(self) -> None:
        """Makes a new chat the open one — one the service does not have
        yet. While an answer runs, the switch waits for its end."""
        return None

    def export(self, path: Path) -> None:
        """Writes the history as it was shown since it was last written
        again, as an HTML page, to ``path``."""
        return None

    def queue(self, work: Callable[[], None]) -> None:
        """Hands ``work`` to the worker, behind what already waits: it runs
        in its turn, like a message typed now."""
        return None

    def hand_over(self, work: Callable[[], _T]) -> _T:
        """Gives the terminal to ``work`` for as long as it runs — a program
        that draws on it itself, such as an editor — and takes it back
        afterwards: the fixed block steps aside and is drawn again, and
        what would be added to the history meanwhile is written after it.
        Returns what ``work`` returns."""
        return work()

    def rows_for_question(self) -> int | None:
        """How many rows the window has above the rest of the fixed block,
        as that block stands right now — the room whatever is shown above
        the input field can take. ``None`` where nobody knows."""
        return None


class Renderer(Protocol):
    """Writes the history. Every method adds lines above the fixed block."""

    # --- The client's own lines ---

    def header(self, version: str, address: str) -> None:
        """The head shown once at start: the program, the service's version
        and its address."""
        return None

    def notice(self, text: str) -> None:
        """A quiet word of the client for the moment — a chat opened, a
        model chosen, a file saved. It stands above the input field until
        the next line goes in, never in the history."""
        return None

    def remark(self, text: str) -> None:
        """A quiet line of the client in the history — what heads a stretch
        of it, or what is listed before the client ends."""
        return None

    def shell_line(self, text: str) -> None:
        """One line a shell command printed, as it came."""
        return None

    def error(self, text: str) -> None:
        """Something failed; also the ``error`` event of an answer."""
        return None

    def user_message(self, text: str) -> None:
        """What the user just sent."""
        return None

    # --- One answer, event by event, in the order the service sends them ---

    def start(self, event: Event) -> None:
        """An answer begins (``generation_id``, ``message_id``)."""
        return None

    def content(self, text: str) -> None:
        """The next piece of the answer's text."""
        return None

    def reasoning(self, text: str) -> None:
        """The next piece of the model's thinking."""
        return None

    def tool_call(self, event: Event) -> None:
        """A tool was called (``name``, ``server``, ``argumente``,
        ``aufruf_id``)."""
        return None

    def tool_result(self, event: Event) -> None:
        """The call came back (``name``, ``aufruf_id``, ``fehlgeschlagen``,
        ``text``, ``dauer_sekunden``)."""
        return None

    def stats(self, data: Mapping[str, Any]) -> None:
        """The answer's numbers: duration, tokens, marks."""
        return None

    def done(self, event: Event) -> None:
        """The answer is over (``abgebrochen``, ``zustand``). Whatever text
        is still held back is written now."""
        return None

    # --- A chat that already has messages ---

    def stored_message(self, message: Mapping[str, Any]) -> None:
        """One message of an opened chat, as the service stores it
        (``role``, ``content``, ``reasoning``, ``stats``)."""
        return None


@dataclass
class Entry:
    """One line of a selection above the input field."""

    # Its columns, the name first. Every column stands below the same
    # column of the other entries.
    cells: list[Piece]
    # A remark behind the columns. Where the line has no room for all of
    # it, it is carried on below its own beginning.
    note: str = ""
    # True for the entry that is in force right now: the selection opens
    # with its mark on it.
    in_use: bool = False
    # What the entry stands for, carried along for whoever made it: a
    # selection that searches replaces its entries, and the one that is
    # picked comes back with its value instead of a position.
    value: Any = None


class Asker(Protocol):
    """Puts the service's questions to the user, and lets the user pick
    from a list a command shows.

    ``confirm_tool`` and ``ask_user`` are called off the screen's own thread
    and block until the user has answered. They return the answer's fields
    as the service's confirm route names them, or ``None`` where no answer
    is to be sent. ``choose`` blocks the same way until an entry is picked
    or the selection is closed. While a question or a selection is open,
    ``pending`` is true, the screen shows ``fragments`` above the input
    field and ``key_bindings`` are in force ahead of the screen's own.
    """

    def confirm_tool(self, event: Event) -> dict[str, Any] | None:
        """A tool waits for permission (``name``, ``argumente``, ``grund``,
        ``aufruf_id``). The answer carries ``erlaubt`` and ``dauerhaft``."""
        return {"erlaubt": False, "dauerhaft": False}

    def ask_user(self, event: Event) -> dict[str, Any] | None:
        """The model asks the user (``frage``, ``optionen``, ``aufruf_id``).
        The answer carries ``antwort``."""
        return None

    def can_ask(self) -> bool:
        """Whether somebody is there to answer a question typed at the
        terminal. A command run from outside without a terminal has nobody:
        the questions it could do without are left out, and one it cannot is
        said and ends the command."""
        return True

    def choose(self, entries: Sequence[Entry], head: str = "") -> int | None:
        """Shows ``entries`` as a selection and returns the position of the
        one the user picked — ``None`` where none was picked: the user
        closed the selection, a question of the service took its place, or
        something stood above the input field already. A selection never
        takes the place of a question. ``head`` is a line above the
        entries: the question the selection answers."""
        return None

    def search(
        self,
        entries: Sequence[Entry],
        find: Callable[[str], Sequence[Entry]],
        head: str = "",
        empty: str = "",
    ) -> Entry | None:
        """Shows ``entries`` as a selection that searches while the user
        types: a word that is no number is handed to ``find`` once the
        typing paused, and what it returns takes the place of the entries —
        renumbered, with ``empty`` standing where nothing was found; an
        empty field or a number shows ``entries`` again. Returns the entry
        that was picked, as ``find`` or the caller made it — ``None``
        where the selection was closed. Without a search of its own an
        asker shows the entries as any selection."""
        picked = self.choose(entries, head)
        return None if picked is None else list(entries)[picked]

    def typed(self, text: str) -> None:
        """The input field holds ``text`` now. Called on every change; a
        selection that searches takes it up, anything else lets it go."""
        return None

    def check(
        self, entries: Sequence[Entry], head: str = "", checked: Collection[int] = ()
    ) -> list[int] | None:
        """Shows ``entries`` as a checklist, with the positions in
        ``checked`` ticked, and returns the positions that are ticked once
        the user confirmed — ``None`` where the list was closed instead:
        nothing is to change then. Otherwise it is asked and closed like a
        selection."""
        return None

    def ask_text(
        self, head: str, *, secret: bool = False, default: str | None = None
    ) -> str | None:
        """Asks for a line of text under ``head`` and returns what was
        typed — ``None`` where the question was closed, nothing was typed or
        none can be asked. With ``secret`` the typed text is not shown, and
        it goes into no line of the history.

        With ``default`` the question shows it as the value that stands, and
        nothing typed takes it: the answer is then ``default`` itself, which
        may be empty — an empty line is an answer of its own there, and only
        closing the question gives ``None``."""
        return None

    def secret(self) -> bool:
        """Whether the question that is open takes its answer hidden: the
        input field then shows no character of what is typed."""
        return False

    def cancel(self) -> None:
        """The service's question is no longer wanted — the answer ended or
        was stopped. A call that still blocks returns ``None``. A selection
        stays: the user opened it, and no answer takes it away."""
        return None

    def close(self) -> None:
        """The client leaves: whatever stands above the input field is
        taken away, a selection as well, and every call that still blocks
        returns ``None``."""
        return None

    def pending(self) -> bool:
        """Whether a question or a selection is open right now."""
        return False

    def fragments(self) -> Fragments:
        """What is open, as the screen shows it above the input field."""
        return []

    def key_bindings(self) -> KeyBindingsBase | None:
        """Keys that answer what is open. They only count while ``pending``
        is true."""
        return None


class CommandSet(Protocol):
    """Everything the user can type after a slash."""

    def run(self, line: str) -> None:
        """Runs the command in ``line``, which starts with a slash. Called
        off the screen's own thread; it may wait for the service."""
        return None

    def completer(self) -> Completer | None:
        """Completes a command while it is typed, or ``None`` for none."""
        return None

    def pick_model(self, leading: Sequence[Entry]) -> int | None:
        """The selection of ``/model`` with ``leading`` entries above its
        own. Returns the position of the leading entry that was picked and
        does nothing else for it; a model that was picked is chosen as
        ``/model`` chooses it, and ``None`` is returned."""
        return None


class StatusSource(Protocol):
    """The lines below the input field."""

    def update(self, **fields: Any) -> None:
        """Takes in what changed. The fields in use: ``chat_title``,
        ``model_name``, ``context_window``, ``context_tokens``, ``address``,
        ``look``, ``connection``, ``server_states``, ``unreachable_models``.
        Unknown ones are ignored."""
        return None

    def model_name(self) -> str:
        """The name the first line gives the model in use, empty where it
        names none — for whoever names that model elsewhere, so that it
        goes by one name."""
        return ""

    def refresh(self) -> None:
        """Reads anew from the service what the lines say about it — called
        once at start and after every line the user sent."""
        return None

    def fragments(self, width: int) -> Fragments:
        """The lines as they fit into ``width`` columns, one below the
        other. No line ever wraps."""
        return []


class EventSink(Protocol):
    """What the client does with the service's own event stream — what
    happens there without this client having asked for it."""

    def start(self) -> None:
        """Begins listening, in the background."""
        return None

    def stop(self) -> None:
        """Stops listening; called once when the client leaves."""
        return None

    def handle(self, event: Event) -> None:
        """One event of the service (``typ`` plus its fields)."""
        return None


@dataclass
class Session:
    """What the next message is sent with, and what is known of the service.

    Plain data any module may read; the commands change it.
    """

    # The open chat as the service describes it (``id``, ``title``,
    # ``endpoint_id`` …), or ``None`` while the open chat is a new one: the
    # service has no such chat until something is written into it.
    chat: dict[str, Any] | None = None
    # True for a new chat nobody has written into yet: its first message
    # gives it its name.
    unnamed: bool = False
    # The name given to a new chat before it exists at the service: it goes
    # out with the creation of the chat.
    pending_title: str | None = None
    # The chats as they were last shown with numbers, in the head or in the
    # list of chats: a number the user types counts into what stood on the
    # screen, not into what the service would list now. ``None`` before any
    # were shown.
    shown_chats: list[dict[str, Any]] | None = None
    # The projects the selection of ``/project`` showed last, in order.
    shown_projects: list[dict[str, Any]] | None = None
    # The names of the tools ``/tools`` showed last, in order.
    shown_tools: list[str] | None = None
    # The MCP servers ``/mcp`` showed last, in order.
    shown_mcp: list[dict[str, Any]] | None = None
    # The skills ``/skills`` showed last, in order.
    shown_skills: list[dict[str, Any]] | None = None
    # The models the service listed last (``id``, ``name``, ``erreichbar`` …).
    models: list[dict[str, Any]] = field(default_factory=list)
    # The model the next message goes to; ``None`` leaves the choice to the
    # service.
    endpoint_id: str | None = None
    # The thinking stage of the next messages; ``None`` leaves the service at
    # its own default.
    thinking: str | bool | None = None
    # The running answer, once the service has named it.
    generation_id: str | None = None
    # True from the moment a message goes out until its answer is over —
    # also in the stretch before the service has named the run.
    answering: bool = False
    # The tool calls announced and not yet answered with a result: while
    # there are any, a message typed meanwhile waits instead of cutting the
    # answer short.
    open_calls: set[Any] = field(default_factory=set)
    # What the service said about itself at start (``status``, ``version``).
    health: dict[str, Any] = field(default_factory=dict)
    # Set while a command waits for something that takes as long as it
    # takes — a model coming up: what ends that wait. The interrupt key
    # calls it before it does anything else with the key.
    cancel_wait: Callable[[], None] | None = None

    def chat_id(self) -> Any:
        """The id of the open chat, or ``None`` while the service has none
        for it yet."""
        return self.chat.get("id") if self.chat else None

    def model(self) -> dict[str, Any] | None:
        """The listed model the next message goes to, if it is known."""
        for model in self.models:
            if model.get("id") == self.endpoint_id:
                return model
        return None


@dataclass
class Context:
    """Everything the modules share, handed to each of them once.

    ``client``, ``texts`` and ``session`` are there from the first moment.
    The rest is set while the client starts, one after the other; nothing
    may be called before ``cli/main.py`` has built all of it.
    """

    client: ServiceClient
    texts: Texts
    session: Session = field(default_factory=Session)
    # The file the choices are remembered in; ``None`` is the user's own.
    prefs_path: Path | None = None
    screen: Screen = None  # type: ignore[assignment]
    renderer: Renderer = None  # type: ignore[assignment]
    asker: Asker = None  # type: ignore[assignment]
    commands: CommandSet = None  # type: ignore[assignment]
    status: StatusSource = None  # type: ignore[assignment]
    events: EventSink = None  # type: ignore[assignment]
    # True where a command runs from outside the chat: it waits for its
    # work and ends with it, instead of leaving the work to go on beside the
    # chat.
    blocking: bool = False
