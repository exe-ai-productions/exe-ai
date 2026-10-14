"""The status lines: three lines below the input field that say where the
client stands. The first names the chat, the model, whether the model
server runs and which look is in use; the second names the permission
mode, the thinking stage, how many tools are on, and whether the service
still answers; the third shows how full the context is — its label on the
left, a bar of cells over all the room that is left, and the count against
the model's window ending in the last column, under the connection. The
bar is full blocks for what is used, in the colour of how full the window
is, and shaded blocks for what is free, in the look's quiet tone.

No line ever wraps. Where the window is too narrow for all of it, the
chat's title is cut first. After that the parts leave one by one from the
right end of a line's left block; what says whether the service is still
there stays to the last. The bar takes whatever width the window has; in a
narrow window its label goes, and the bar stays.

What the first and the third line say, the other modules report as it
changes. What the second line says about the mode, the stage and the tools
is read from the service, once at start and again after every line the
user sent: those are the moments it can have changed.
"""

from __future__ import annotations

import math
import sys
from typing import Any

from prompt_toolkit.utils import get_cwidth

from cli import glyphs
from cli.client import ServiceError, ServiceUnreachable
from cli.interfaces import Context, Fragments, StatusSource

# The room that stays free between the left block and the connection at the
# right edge, so the two never read as one — and between the context bar
# and what stands on either side of it.
GAP = 2

# From how many columns on the context bar has its label in front of it.
# In a narrower window the label goes and the bar keeps the room.
LABEL_FROM = 40

# How full the window is decides the colour of the bar's used cells: the
# look's green below the first share, its yellow from there up to the
# second, its red above — both in percent of the window.
YELLOW_FROM = 50
RED_ABOVE = 80

# What stands where a number is not known yet, and what marks a cut title —
# each with the plain form for a console that cannot show the first one.
NO_NUMBER = ("–", "-")
CUT_MARK = ("…", "...")

# One part of a line: the style it is drawn in and what it says.
Part = tuple[str, str]

# The three states of the connection to the service, as the listener
# reports them in the field ``connection``: the stream stands; it broke and
# is being opened again; it has never stood. Each with the sign in front of
# its word, the word's key and the colour it is drawn in. Until the listener
# has said anything, there is no connection to speak of.
CONNECTED = "connected"
RECONNECTING = "reconnecting"
DISCONNECTED = "disconnected"

# The three words the service uses for the server behind a model
# (app/server_state.py); the line shows them as they are.
ACTIVE = "active"
IDLE = "idle"
OFFLINE = "offline"


def server_of(model_id: str) -> str:
    """The server behind a model id. The service names a model at a
    provider ``endpoint:model`` and a provider that names no model by its
    bare id; endpoint ids carry no colon, so the part before the first one
    is the server (app/modellkennung.py)."""
    return model_id.partition(":")[0]
_CONNECTION = {
    CONNECTED: ("connected", "cli.connected", "class:green"),
    RECONNECTING: ("waiting", "cli.reconnecting", "class:yellow"),
    DISCONNECTED: ("disconnected", "cli.disconnected", "class:red"),
}

# The settings the second line is read from: the permission mode of the
# chat, its thinking stage, and the tools that are switched off.
_MODE_KEY = "berechtigungsmodus_chat"
_THINKING_KEY = "denken"
_TOOLS_OFF_KEY = "werkzeuge_aus"

# The word for each permission mode the service knows.
_MODE_WORDS = {
    "manuell": "cli.mode_manuell",
    "auto": "cli.mode_auto",
    "restricted": "cli.mode_restricted",
}


def build_status(ctx: Context) -> StatusSource:
    # Read once, at start: which characters the console can show does not
    # change while the client runs.
    return ServiceStatus(ctx, encoding=getattr(sys.stdout, "encoding", None))


def showable(text: str, plain: str, encoding: str | None) -> str:
    """``text`` where the console can show it, else its plain form."""
    try:
        text.encode(encoding or "utf-8")
    except (UnicodeEncodeError, LookupError):
        return plain
    return text


def one_line(value: Any) -> str:
    """A name as it stands in a line: a line break or a tab inside it is one
    blank, so whatever a chat or a model is called, the line stays one."""
    return " ".join(str(value).split())


def fitting(text: str, cells: int) -> str:
    """As much of ``text``, from its start, as takes at most ``cells`` cells
    of the terminal. Counted in cells, not in characters: some characters
    are two cells wide."""
    kept = ""
    used = 0
    for character in text:
        wide = get_cwidth(character)
        if used + wide > cells:
            break
        kept += character
        used += wide
    return kept


def cut(text: str, cells: int, mark: str) -> str:
    """``text`` shortened so that it and the mark behind it take at most
    ``cells`` cells of the terminal, with no blank before the mark."""
    return fitting(text, cells - get_cwidth(mark)).rstrip() + mark


class ServiceStatus(StatusSource):
    """Line one: title, model, model server and look. Line two: mode,
    thinking stage, tools — and the connection to the service at the right
    edge. Line three: the context as a bar, with the count beside it."""

    def __init__(self, ctx: Context, *, encoding: str | None = None) -> None:
        self._ctx = ctx
        self._fields: dict[str, Any] = {}
        # The chat the context number was reported in. A number belongs to
        # its chat: under another chat's title it would be a wrong number.
        self._counted_chat: Any = None
        self._no_number = showable(*NO_NUMBER, encoding)
        self._cut_mark = showable(*CUT_MARK, encoding)

    def update(self, **fields: Any) -> None:
        """Besides the fields every status line knows, this one takes
        ``unreachable_models``: the ids of the servers the service reported
        as gone. A model is marked by its server's id."""
        if "context_tokens" in fields:
            self._counted_chat = self._ctx.session.chat_id()
        self._fields.update(fields)

    def model_name(self) -> str:
        return one_line(self._fields.get("model_name") or "")

    def refresh(self) -> None:
        """Reads from the service what the second line says: the permission
        mode and the thinking stage that apply to the open chat and its
        model, and how many tools are on. A service that does not answer
        leaves the line as it was; the connection says so by itself."""
        session = self._ctx.session
        scope: dict[str, Any] = {}
        if session.chat is not None:
            scope["chat"] = session.chat["id"]
        if session.endpoint_id:
            scope["modell"] = session.endpoint_id
        client = self._ctx.client
        try:
            resolved = client.get(
                "/settings/resolved",
                params={"keys": ",".join((_MODE_KEY, _THINKING_KEY, _TOOLS_OFF_KEY)), **scope},
            )
            offered = client.get("/tools")
        except (ServiceError, ServiceUnreachable):
            return
        resolved = resolved if isinstance(resolved, dict) else {}
        mode = _resolved_value(resolved, _MODE_KEY)
        stage = _resolved_value(resolved, _THINKING_KEY)
        off = _resolved_value(resolved, _TOOLS_OFF_KEY)
        tools = offered.get("werkzeuge") if isinstance(offered, dict) else None
        names = (
            {str(tool.get("name")) for tool in tools if isinstance(tool, dict)}
            if isinstance(tools, list)
            else set()
        )
        # The tools on, and all of them: all are the ones the list carries; on
        # are those of them that are not switched off. A name switched off
        # that the list does not carry counts nowhere.
        switched_off = {str(name) for name in off} if isinstance(off, list) else set()
        self._fields.update(
            mode=mode if isinstance(mode, str) else None,
            thinking_stage=stage.get("stufe") if isinstance(stage, dict) else None,
            tools_on=len(names - switched_off),
            tools_all=len(names),
        )

    # --- The parts of the first line -------------------------------------------

    def _title(self) -> Part | None:
        title = one_line(self._fields.get("chat_title") or "")
        return ("class:accent", title) if title else None

    def _model(self) -> Part | None:
        name = self.model_name()
        if not name:
            return None
        in_use = self._ctx.session.endpoint_id
        if in_use and server_of(in_use) in (self._fields.get("unreachable_models") or ()):
            # The service reported that the server of the model in use went
            # away — it reports servers, and a catalogue is many models on
            # one. Looked up here, at the moment of drawing: which model is
            # in use can change with any command.
            gone = self._ctx.texts.t("status.nicht_erreichbar")
            return ("class:red", f"{name} {gone}")
        return ("class:text", name)

    def _number(self, value: Any) -> str:
        return str(value) if _is_number(value) else self._no_number

    def _server_state(self) -> Part | None:
        # The server behind the model in use, in the service's word. Looked
        # up at the moment of drawing, like the model's reachability above:
        # which model is in use can change with any command.
        in_use = self._ctx.session.endpoint_id
        states = self._fields.get("server_states") or {}
        state = states.get(server_of(in_use)) if in_use else None
        texts = self._ctx.texts
        if state == ACTIVE:
            # Blue in every look, as the window draws the same state: a look
            # whose accent is its text colour would otherwise show "active"
            # in no colour at all, next to a green "ready".
            return ("class:blue", texts.t("kopf.server_active"))
        if state == IDLE:
            return ("class:green", texts.t("kopf.bereit"))
        if state == OFFLINE:
            # Not reachable is a fact about the machine, no failure: quiet,
            # not red.
            return ("class:muted", texts.t("kopf.server_aus"))
        # Nobody has said yet, or no model is in use; a guess would be a
        # wrong state.
        return None

    def _look(self) -> Part | None:
        look = one_line(self._fields.get("look") or "")
        return ("class:muted", look) if look else None

    # --- The parts of the second line ------------------------------------------

    def _mode(self) -> Part | None:
        key = _MODE_WORDS.get(str(self._fields.get("mode") or ""))
        return ("class:text", self._ctx.texts.t(key)) if key else None

    def _thinking(self) -> Part | None:
        # What the user set for the next messages comes first; otherwise
        # what the service keeps for this chat and this model.
        stage = self._ctx.session.thinking or self._fields.get("thinking_stage")
        if not isinstance(stage, str) or not stage:
            return None
        texts = self._ctx.texts
        key = f"denken.stufe.{stage}"
        word = texts.t(key)
        # A stage the catalogue has no word for stands as the service names it.
        word = stage if word == key else word.lower()
        return ("class:text", texts.t("cli.thinking_stage", stage=word))

    def _tools(self) -> Part | None:
        on, all_of_them = self._fields.get("tools_on"), self._fields.get("tools_all")
        if not isinstance(on, int) or not isinstance(all_of_them, int):
            return None
        return ("class:text", self._ctx.texts.t("cli.tools_count", active=on, total=all_of_them))

    def _connection(self) -> Part:
        state = str(self._fields.get("connection") or DISCONNECTED)
        sign, word, style = _CONNECTION.get(state) or _CONNECTION[DISCONNECTED]
        said = " ".join(piece for piece in (glyphs.glyph(sign), self._ctx.texts.t(word)) if piece)
        return (style, said)

    # --- The third line: the context ---------------------------------------------

    def _count(self) -> tuple[Any, Any]:
        """The context as it was reported: the tokens the open chat's last
        answer counted, and the window of the model in use. A count that
        was reported in another chat is none of this one's."""
        window = self._fields.get("context_window")
        tokens = self._fields.get("context_tokens")
        if self._counted_chat != self._ctx.session.chat_id():
            tokens = None
        return tokens, window

    def _bar(self, cells: int, tokens: Any, window: Any) -> Fragments:
        """The bar: ``cells`` cells — the used share of the window as full
        blocks in the colour of how full it is, the rest as shaded blocks
        in the look's quiet tone. That tone still shows where the terminal
        lies on a surface of the window instead of the look's own ground;
        the look's line colour does not. The two signs differ, so the level
        shows without any colour too. Anything used shows as at least one
        cell; where the count or the window is not known, nothing is used."""
        used, level = 0, "class:green"
        if _is_number(tokens) and _is_number(window) and window > 0 and tokens > 0:
            used = min(cells, math.ceil(cells * tokens / window))
            level = _level(tokens, window)
        return [
            (level, glyphs.glyph("bar_used") * used),
            ("class:muted", glyphs.glyph("bar_free") * (cells - used)),
        ]

    def _context_line(self, width: int) -> Fragments:
        """The label, the bar and the count, filling the width and never
        wrapping: the bar takes every column the label and the count leave,
        so the count ends in the last column whatever its length. In a
        window narrower than the label's width the label goes; narrower
        still, the bar goes and the count is cut."""
        tokens, window = self._count()
        label = self._ctx.texts.t("cli.context_label")
        count = f"{self._number(tokens)}/{self._number(window)}"

        def room(with_label: bool) -> int:
            """The cells left for the bar with a gap on either side of it."""
            taken = get_cwidth(count) + GAP
            if with_label:
                taken += get_cwidth(label) + GAP
            return width - taken

        with_label = width >= LABEL_FROM and room(True) > 0
        cells = room(with_label)
        if cells <= 0:
            cells = 0
            count = cut(count, width, "")

        line: Fragments = []
        if with_label:
            line.append(("class:text", label))
            line.append(("", " " * GAP))
        if cells:
            line.extend(self._bar(cells, tokens, window))
            line.append(("", " " * GAP))
        line.append(("class:text", count))
        return line

    # --- The lines --------------------------------------------------------------

    def fragments(self, width: int) -> Fragments:
        if width <= 0:
            return []
        first = self._line(
            width,
            glyphs.glyph("line_chat"),
            self._title(),
            [self._model(), self._server_state(), self._look()],
            None,
        )
        second = self._line(
            width,
            glyphs.glyph("line_mode"),
            None,
            [self._mode(), self._thinking(), self._tools()],
            self._connection(),
        )
        third = self._context_line(width)
        return [*first, ("", "\n"), *second, ("", "\n"), *third]

    def _line(
        self,
        width: int,
        sign: str,
        title: Part | None,
        rest: list[Part | None],
        right: Part | None,
    ) -> Fragments:
        """One line: the sign, the title and the parts on the left, what
        stands at the right edge — cut to the width, never wrapped."""
        separator = f" {glyphs.glyph('separator')} "
        lead = f"{sign} " if sign else ""
        if get_cwidth(lead) > width:
            # Not even the sign fits whole.
            lead = cut(lead, width, "")
        right_style, right_text = right if right else ("", "")
        parts: list[Part] = [part for part in rest if part is not None]

        def cells(left: list[Part]) -> int:
            """What the line takes with these parts on its left."""
            taken = get_cwidth(lead) + sum(get_cwidth(text) for _, text in left)
            taken += get_cwidth(separator) * max(0, len(left) - 1)
            return taken + (GAP if left and right_text else 0) + get_cwidth(right_text)

        shown = ([title] if title else []) + parts
        if title and cells(shown) > width:
            # The title gives way first: it keeps what the other parts leave.
            room = width - (cells(shown) - get_cwidth(title[1]))
            shortened = cut(title[1], room, self._cut_mark)
            if room > 0 and shortened != self._cut_mark:
                shown[0] = (title[0], shortened)
            else:
                # Not even its first character fits: a mark alone names no chat.
                shown = parts
        while shown and cells(shown) > width:
            shown.pop()
        if not shown and get_cwidth(lead) + get_cwidth(right_text) > width:
            right_text = cut(right_text, max(0, width - get_cwidth(lead)), "")

        line: Fragments = [("class:accent", lead)] if lead else []
        for number, part in enumerate(shown):
            if number:
                line.append(("class:rule", separator))
            line.append(part)
        if right_text:
            # The connection stands at the right edge, whatever is on the left.
            line.append(("", " " * max(0, width - cells(shown) + (GAP if shown else 0))))
            line.append((right_style, right_text))
        return line


def _level(tokens: int, window: int) -> str:
    """The colour that says how full the window is, as the class the used
    cells of the bar are drawn in. Reckoned in whole numbers, so each of
    the two shares lies exactly where it is named."""
    if tokens * 100 < window * YELLOW_FROM:
        return "class:green"
    if tokens * 100 <= window * RED_ABOVE:
        return "class:yellow"
    return "class:red"


def _is_number(value: Any) -> bool:
    """Whether ``value`` is a count one can reckon with — a whole number,
    and not the truth value that Python counts among them."""
    return isinstance(value, int) and not isinstance(value, bool)


def _resolved_value(resolved: dict[str, Any], key: str) -> Any:
    """The value the service resolved for ``key`` — ``None`` where it named
    none."""
    entry = resolved.get(key)
    return entry.get("wert") if isinstance(entry, dict) else None
