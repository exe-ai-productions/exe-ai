"""Request and response formats of the API.

Separate from the database's data objects: what goes to the outside should
be able to evolve independently of the internals.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.agenten import Agent
from app.db.models import Auftrag, AuftragSchritt, Chat, Cronjob, Document, Message

log = logging.getLogger(__name__)


class ChatAnlegen(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    endpoint_id: str | None = None


class ChatCompact(BaseModel):
    """Compacts a chat by hand.

    ``endpoint_id`` names the model that writes the summary, as a chat
    request does; absent, the chat's own model is used. ``topic`` is the
    focus the user typed behind the command — the summary records what
    relates to it in full and the rest briefly.
    """

    endpoint_id: str | None = None
    topic: str | None = None


class ChatCompactResult(BaseModel):
    """What a manual compaction did, as one word.

    ``folded`` says the middle of the chat is now one summary and ``replaced``
    how many messages it replaced; the other three leave the chat as it was:
    ``too_short`` (there is no middle to fold), ``no_saving`` (the summary
    would not have been shorter than what it replaces) and ``failed`` (no
    summary came back). ``stopped`` says the person pressed stop while the
    summary was being written: nothing was folded and nothing was booked.
    """

    result: Literal["folded", "too_short", "no_saving", "failed", "stopped"]
    replaced: int = 0


class OrdnerOeffnen(BaseModel):
    """Which chat, and which of its shared folders. Never a free path — the
    handler only accepts one that is already in the chat's list. Without a
    path it opens the chat's own folder, whose place the server builds from
    the chat's id and the data folder, so the client never names it."""

    chat_id: str
    pfad: str | None = None


class OrdnerErsatz(BaseModel):
    """A folder that is gone, and the place the user says it lies now.

    The pair travels as ONE thing on purpose. Comparing the old list of
    shares with the new one would look like an answer — one path out, one
    path in — and stops being one the moment two folders are missing at
    once: nothing in the two lists says which of the new ones replaces
    which of the old. The window asks per missing folder instead, and this
    is that answer.
    """

    alt: str
    neu: str


class OrdnerStand(BaseModel):
    """Which of a chat's shared folders are no longer there."""

    fehlend: list[str] = Field(default_factory=list)


class ChatAendern(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    # Suspends the system prompt for this one chat. The prompt itself lives
    # in a file and is not touched here.
    prompt_aus: bool | None = None
    endpoint_id: str | None = None
    pinned: bool | None = None
    # The working folders (shell tool): absolute paths to existing
    # folders — checked in the handler. An empty list deselects. For a chat
    # in a project the list is the project's and changes for every chat in it.
    working_dirs: list[str] | None = None
    # Into a project (its id) or out of the one it is in (null). Absent
    # leaves it where it is.
    project_id: str | None = None
    # Into the archive or back out of it.
    archived: bool | None = None
    # Set only when the new list replaces a MISSING folder with the place it
    # was moved to: the chat's document paths below the old folder are then
    # rewritten to below the new one. Without it, a changed list of folders
    # rewrites nothing — adding a folder is adding a folder.
    ordner_ersatz: OrdnerErsatz | None = None


class ChatAntwort(BaseModel):
    id: str
    user_id: str
    title: str
    prompt_aus: bool
    endpoint_id: str | None
    pinned: bool
    working_dirs: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
    project_id: str | None = None
    archived: bool = False
    # Not a column — computed from the service's own running generations at
    # the moment of the answer, the same way `LaufendeGenerierung` already is
    # for a single opened chat. False everywhere this is not looked up: a
    # freshly created chat cannot be running, and every caller that CAN
    # report it accurately (the chat list the sidebar's ring reads, a rename
    # or pin of a chat that happens to be running) passes it in explicitly.
    laeuft: bool = False

    @classmethod
    def aus(cls, chat: Chat, *, laeuft: bool = False) -> "ChatAntwort":
        # `frage` is the raw JSON column — delivered on the
        # single chat's own messages page (`NachrichtenSeite.frage`), not
        # repeated on every row of the list this schema also serves.
        felder = {k: v for k, v in chat.__dict__.items() if k != "frage"}
        return cls(**felder, laeuft=laeuft)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    # The folders every chat of the project shares — checked in the handler,
    # the same way a chat's own are. An empty list deselects.
    working_dirs: list[str] | None = None
    archived: bool | None = None


class ProjectAnswer(BaseModel):
    id: str
    name: str
    working_dirs: list[str] = Field(default_factory=list)
    archived: bool
    created_at: str
    # How many chats lie in it — the question before deleting it names it.
    chat_count: int = 0


class NachrichtAnlegen(BaseModel):
    role: Literal["system", "user", "assistant", "tool"] = "user"
    content: str
    reasoning: str | None = None
    stats: dict[str, Any] | None = None


class NachrichtAntwort(BaseModel):
    id: str
    chat_id: str
    role: str
    content: str
    reasoning: str | None
    stats: dict[str, Any]
    created_at: str
    # File name of the attached image (vision) — the UI fetches it via
    # GET /api/v1/images/{name}. Meant to stay mutually exclusive with
    # `bilder` below, but a row with both is a real, reachable state, not
    # a hypothetical one — see `Message.bild`'s own docstring for how.
    bild: str | None = None
    # Images per run: the run's own picture list, one entry per
    # requested position, None where a picture has not finished or did
    # not survive. WINS over `bild` if a row somehow carries both — see
    # `aus` below, which is where that precedence is actually enforced.
    bilder: list[str | None] | None = None
    # Meta card of the attached document (4.1) — built by the server from
    # the documents row; the message itself carries only the id.
    dokument: dict[str, Any] | None = None
    # User attachments as lists (several images / documents on one message).
    # `anhaenge` carries file names, `dokumente` meta cards like `dokument`.
    anhaenge: list[str] | None = None
    dokumente: list[dict[str, Any]] | None = None
    # What this row IS, beyond who said it: `nachricht`, `werkzeugmeldung`,
    # `bild` or `bildlauf`. The window needs it to draw a tool report as a
    # tool report — and, more importantly, to stop treating every empty
    # assistant row as an answer that is still being written.
    art: str = "nachricht"
    # Where the run behind this row stands: `laeuft`, `fertig`,
    # `abgebrochen`, `fehler`, or nothing where there is no run. Together
    # with `lauf_id` this replaces the guesswork the window used to do from
    # a row's POSITION in the list.
    zustand: str | None = None
    lauf_id: str | None = None
    # How full the context was after this message — written while the run
    # goes, so the bar can move during an answer instead of only after it.
    gesamt_tokens: int | None = None
    # Set when a compaction folded this message away: the model gets the
    # summary instead, the reader still sees every line.
    verdichtet_in: str | None = None
    verdichtete_anzahl: int = 0

    @classmethod
    def aus(
        cls,
        nachricht: Message,
        dokument: dict[str, Any] | None = None,
        dokumente: list[dict[str, Any]] | None = None,
    ) -> "NachrichtAntwort":
        daten = dict(nachricht.__dict__)
        # A row is never meant to carry both — the two writers never touch
        # the other's column — but nothing stops some future write path
        # from doing it anyway, and nothing said which one a reader should
        # trust if it did. `bilder` wins, but only carrying real content —
        # Checking only `is not None` let an EMPTY `bilder`
        # beat a real `bild`, losing it with no trace. Same rule
        # `bild_dateien()` already applies; matched here rather than
        # asked of it directly, since this needs to know WHICH of the two
        # raw fields to drop, not the flattened list either returns.
        if nachricht.bild and nachricht.bilder is not None:
            log.warning(
                "Message %s: carries bild AND bilder -- bilder wins when it "
                "has real content",
                nachricht.id,
            )
        if nachricht.bilder is not None and any(nachricht.bilder):
            daten["bild"] = None
        daten["dokument"] = dokument
        # The message row holds document IDS; the API answers with the meta
        # cards the caller can actually show.
        daten["dokumente"] = dokumente
        return cls(**daten)


class LaufendeGenerierung(BaseModel):
    """A run the server already knows about, for a window that does not —
    a plain reload loses the id it only ever had from the stream's own
    `start` event.

    There is no `ab` here on purpose: nothing this run has written lives
    anywhere else yet (the message row stays empty until it ends), so a cold
    reattach can only replay the whole event log from the start — the offset
    was always 0 and carried nothing.
    """

    generation_id: str
    # WHICH row this run is writing. Without it a cold window had to work
    # the answer out from its position — last row, assistant, no cancel mark
    # in the stats blob — and anything appended during the run (a finished
    # background command, a picture) matched that description exactly. The
    # window then adopted the wrong row, emptied it, and replayed the whole
    # answer into it, leaving the real one standing above: the same text
    # twice, and once more for every further reattach.
    message_id: str | None = None


class OffeneFrageOption(BaseModel):
    """One button of an open question — the shape `frage_werkzeug.
    gepruefte_frage` produces, the live `user_ask` SSE event already
    carries, and the question card renders (label plus an optional
    explaining sentence)."""

    label: str
    description: str = ""


class OffeneFrage(BaseModel):
    """The ask_user question this chat is standing on — the
    same shape the live `user_ask` SSE event carries, so the window can
    adopt it into `zustand.benutzerfrage` exactly the way it would a live
    one. No `generation_id`: unlike `LaufendeGenerierung`, this is delivered
    whether or not a run is still going for this chat, so it names none.
    """

    aufruf_id: str
    frage: str
    optionen: list[OffeneFrageOption] = Field(default_factory=list)


class NachrichtenSeite(BaseModel):
    nachrichten: list[NachrichtAntwort]
    laufend: LaufendeGenerierung | None = None
    # Whether the service HOLDS this chat without naming a run for it — a
    # request that is still building its answer (app/generationen.py,
    # `beansprucht`: the fold before the stream costs a whole model request).
    # A window whose own send broke in exactly that stretch has no run id to
    # reattach to and would otherwise call the send failed while the answer
    # it started is still on its way. Deliberately apart from `laufend`,
    # which names a run: a claim has no id to give.
    gehalten: bool = False
    frage: OffeneFrage | None = None


class DokumentAntwort(BaseModel):
    id: str
    chat_id: str
    filename: str
    mime_type: str | None
    size_bytes: int | None
    created_at: str

    @classmethod
    def aus(cls, dokument: Document) -> "DokumentAntwort":
        daten = dict(dokument.__dict__)
        daten.pop("extracted_text", None)
        return cls(**daten)


class ModellAntwort(BaseModel):
    id: str
    name: str
    # Which provider this model sits behind, and what it is called there.
    # The id is built from both (see app/modellkennung.py); these two fields
    # spare the frontend from taking it apart again.
    anbieter: str = ""
    anbieter_name: str = ""
    modell: str | None = None
    # Whether `name` is the model's own — reported by its server or taken
    # from its catalogue — and not the one the configuration gives the
    # server. A client keeps a name with its choice only from a name that is.
    name_gemeldet: bool = False
    # Named by the configuration — picked without anyone having to tick it.
    angeheftet: bool = False
    # Second line in the picker menu. Derived, not maintained.
    quelle: str = ""
    provider: str
    dialekt: str = "openai"
    reasoning_format: str
    erreichbar: bool
    # The server behind this model in one word — active, idle or offline
    # (app/server_state.py): the same word the live line announces, carried
    # here so a client has it before the first announcement.
    server_state: str = ""
    zuletzt_geprueft: str | None
    context_tokens: int | None = None
    # Of the two, the one the configuration itself carries. Empty means
    # the number above was found rather than given.
    kontext_eigen: int | None = None
    # Which of app/fenstergroesse.py's five sources resolved the window —
    # only so the Cloud menu can tell a found number from the fallback
    # ("gefunden: N" vs. "Auto").
    kontext_quelle: str | None = None
    # Set where an endpoint looks like a local MLX or vLLM server but is
    # entered under the `openai` dialect. The card shows one line for it;
    # nothing is corrected, because the file belongs to the user.
    dialekt_verdacht: bool = False
    # `thinking` in here is a LIST of stage keys, the other two stay yes/no.
    # A model that offers four depths and one that can only be switched on
    # are not the same capability, and a boolean cannot tell them apart.
    capabilities: dict[str, Any]
    # The whole answer of the stage control for this model: `stufen`,
    # `standard`, `art` (stufen | schalter | immer | nie), `quelle` and the
    # native word each stage travels under. The window draws its pill from
    # this and keeps no list of its own.
    denkprofil: dict[str, Any] = Field(default_factory=dict)
    # The stage a request carries for this model when nobody names one: the
    # stored stage as far as the model still offers it, else the depth
    # standing in for it. Empty where there is nothing to set. The window
    # shows it, so it never works the rule out again.
    thinking_sent: str | None = None
    # local | cloud | extra - the model picker groups by this so it is
    # visible at a glance whether a request leaves the machine. Local are
    # only the two servers this program starts itself (app/config.py
    # LOKALE_ENDPUNKTE); everything else is a provider, the configuration
    # file's own entries included - which is why that is the value standing
    # here when none arrives.
    group: str = "cloud"
    # Whether a model call to this endpoint is cut off after a long silence
    # - see EndpointConfig.timeout_enabled. The "Zeitgrenze" switch reads
    # and sets this.
    timeout_enabled: bool = True
    # Name of the environment variable holding the access key, and whether it
    # is filled. Never the key itself.
    schluessel_env: str | None = None
    schluessel_gesetzt: bool = False
    # Whether removing the provider takes that key line along — false while
    # another provider reads the same variable. Decides the question the
    # window puts before the removal.
    key_goes_with_provider: bool = False
    parameter: list[dict[str, Any]] = Field(default_factory=list)


class GenerierungAnfrage(BaseModel):
    """Request to the streaming proxy."""

    chat_id: str
    endpoint_id: str | None = None
    content: str | None = Field(
        default=None,
        description="New user message. If omitted, processing continues with the existing "
                    "history, for example when regenerating a response.",
    )
    # The id the interface already gave its own bubble for this question,
    # so the row it becomes here carries the same one. A reload landing
    # while the request is still in flight then finds its own question
    # already among the rows the service just named, instead of a second
    # copy under a different id. Missing (an older interface, the CLI): the
    # service assigns the id as it always has.
    nachricht_id: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    max_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    parameter: dict[str, float] | None = None
    # Vision: file name of an image previously uploaded via POST /images.
    # Only allowed if the endpoint has capabilities.vision.
    bild: str | None = None
    # Document (4.1): the id from POST /documents. The server checks that it
    # belongs to this chat and builds the meta card itself from the database.
    dokument: str | None = None
    # The same two as lists — several attachments on one message. When a
    # list is given it wins over its scalar twin; the scalars stay for
    # older callers.
    bilder: list[str] | None = None
    dokumente: list[str] | None = None
    # Which thinking stage was picked: one key out of app/denkstufen.py's
    # vocabulary ("off", "low", "high" ...). None leaves the server at its
    # own default. A bare true/false is the older form of the same field —
    # there were two positions before there was a scale — and reads as
    # on/off. Only passed through where the model really offers that stage.
    thinking: str | bool | None = None
    # A skill the user picked from the slash list. Its note and instruction go
    # in front of this message's words and are kept on its row, out of the
    # text the chat shows, so later requests carry them the way this one did
    # until a fold (app/verlaufsbau.py). An unknown name is ignored rather
    # than refused: the message itself was still meant.
    skill: str | None = None
    # Whether this message is the spoken side of a live conversation, not a
    # typed one. Turns on the conversation instruction
    # (app/diktatsprachewahl.py), prefixed to the newest user turn on its way
    # to the model (app/verlaufsbau.py) — the stored row and every earlier
    # turn stay exactly as said.
    gespraech: bool = Field(
        default=False,
        description="Whether this message is the spoken part of a conversation.",
    )
    # Whether the user cut the previous spoken answer short. Only read on a
    # conversation turn: it puts one line before the conversation instruction
    # telling the model its last reply was not heard to the end.
    unterbrochen: bool = Field(
        default=False,
        description="Whether the previous spoken answer was interrupted.",
    )
    # The regenerate arrow under a finished or stopped answer: the id of the
    # chat's last answer this request writes a new one for. The new answer
    # is written on the history without that row, and the row stays stored
    # until the new answer is finished and stored — the same step deletes
    # it. A new answer that fails or is stopped leaves it as it was and
    # leaves no row of its own.
    replaces: str | None = Field(
        default=None,
        description="Id of the chat's last answer that a new answer takes the place of "
                    "once it is finished.",
    )
    # The arrow under a failed answer: the id of the chat's last answer whose
    # failed model call is asked again. The request carries what that run
    # had already done — its tool calls with their results and its text —
    # and the run goes on in the same row. Nothing is deleted and no tool
    # call of the run is carried out a second time.
    retries: str | None = Field(
        default=None,
        description="Id of the chat's last answer, a failed one, whose failed model "
                    "call is asked again in the same answer.",
    )

    @model_validator(mode="after")
    def _one_answer_named_and_no_new_turn(self) -> "GenerierungAnfrage":
        """Both fields work on the history as it stands: a request naming an
        answer brings no turn of its own, and it names one answer."""
        if not (self.replaces or self.retries):
            return self
        if self.replaces and self.retries:
            raise ValueError("replaces and retries cannot be sent together")
        if self.content or self.bild or self.dokument or self.bilder or self.dokumente:
            raise ValueError("a request naming an answer carries no message of its own")
        return self


class AbbruchAnfrage(BaseModel):
    generation_id: str | None = None
    chat_id: str | None = None


class AbbruchAntwort(BaseModel):
    abgebrochen: int


class BestaetigungAnfrage(BaseModel):
    """The user's answer to a waiting tool call.

    Two kinds travel this one route: the yes or no before a tool runs, and
    the answer to ``ask_user``. ``antwort`` carries the latter — a clicked
    label or whatever the user typed instead.
    """

    generation_id: str
    aufruf_id: str
    erlaubt: bool = True
    antwort: str | None = None
    # "immer erlauben" needs the tool's name — this route has no
    # other way to learn it, only that SOME call is waiting for an answer.
    name: str | None = None
    dauerhaft: bool = False


class SystemPromptAntwort(BaseModel):
    """The system prompt and whether one is stored at all."""

    text: str
    datei: str


class SystemPromptAnfrage(BaseModel):
    text: str = Field(max_length=100_000)


class GedaechtnisAntwort(BaseModel):
    """The memory file and where it lives."""

    text: str
    datei: str


class GedaechtnisAnfrage(BaseModel):
    text: str = Field(max_length=100_000)


class BestaetigungAntwort(BaseModel):
    zugestellt: bool = Field(
        description="False if no one is waiting for this answer anymore: generation has ended "
                    "or a decision has already been made."
    )


# --- Agents and jobs --------------------------------------------
# Field names in English like the other API shapes; the state values
# themselves are fixed German keys ('laeuft', 'wartet', …) — the
# UI translates them via the catalog.


class AgentAntwort(BaseModel):
    name: str
    # No ``model`` here any more: which model a run uses is said by
    # the one field or by the start window, and an answer still carrying a
    # third one would keep the interface offering a choice that no longer
    # decides anything.
    # None means tools: was left out of the front matter entirely — every
    # approved tool runs. An empty list is the deliberate opposite.
    tools: list[str] | None
    # The complete paths the file tools may reach — the agent's own shares,
    # the same kind of list a chat keeps in working_dirs.
    folders: list[str] = Field(default_factory=list)
    max_rounds: int
    max_minutes: float
    # None means the agent has no opinion — the settings cascade
    # (app/auftragtokenwahl.py) decides. Set means this overrides it outright.
    max_tokens: int | None = None
    # None means nothing is sent and the server keeps its own habit. Zero is
    # a stated wish for no thinking, not an absent value — see
    # app/auftragdenklaengewahl.py.
    reasoning_budget: int | None = None
    # None means the cascade (app/befehlszeitwahl.py) decides. Set means
    # this overrides it outright, with no ceiling of its own.
    max_command_seconds: int | None = None
    # The agent's own colour, wherever its name is written. None: it picked
    # none and wears the shared default, exactly as before this field.
    color: str | None = None
    # What the agent is for, as the chat's model reads it. None: not said.
    description: str | None = None
    # No ``schedule`` here any more: when an agent runs is the cron
    # table's word alone, and an answer that still carried a second schedule
    # would keep the interface offering the way that no longer fires.

    @classmethod
    def aus(cls, agent: Agent) -> "AgentAntwort":
        return cls(
            name=agent.name,
            tools=agent.werkzeuge,
            folders=agent.ordner,
            max_rounds=agent.runden,
            max_minutes=agent.minuten,
            max_tokens=agent.max_tokens,
            reasoning_budget=agent.denklaenge,
            max_command_seconds=agent.befehlssekunden,
            color=agent.farbe,
            description=agent.description,
        )


class AgentDatei(BaseModel):
    """The raw agent file for the editor window (6.6).

    ``kaputt`` carries the reason if the front matter is no good — the file
    is saved anyway (it is the user's file), but the agent is out of play,
    and the window should be able to say so.
    """

    name: str
    content: str
    kaputt: str | None = None
    # The prompt on its own, already split from the front matter. The raw
    # editor works on ``content``; a form cannot, and asking a form to learn
    # YAML to find the text below the header would put the same parser in a
    # second language. None when the front matter is broken — then there is
    # no trustworthy split to hand out, and ``kaputt`` says why.
    prompt: str | None = None


class AgentDateiSchreiben(BaseModel):
    content: str = Field(max_length=100_000)


class AgentFelderSchreiben(BaseModel):
    """The form's save: named fields instead of raw text.

    Only the fields the request actually carries are touched — an absent
    field keeps its lines in the file, an explicit null removes it. That is
    what lets a form with a fixed set of controls save a file that holds
    more than the form shows.
    """

    tools: list[str] | None = None
    folders: list[str] | None = None
    max_rounds: int | None = None
    max_minutes: float | None = None
    max_tokens: int | None = None
    reasoning_budget: int | None = None
    max_command_seconds: int | None = None
    color: str | None = None
    description: str | None = None
    # ``model`` and ``schedule``/``schedule_task`` are
    # gone from the form. A file that carries them keeps them — the form only
    # ever touches the fields it names, so a retired key survives a form save
    # untouched, like a comment.
    prompt: str | None = Field(default=None, max_length=100_000)


class AgentDateiEintrag(BaseModel):
    """One entry of the file list for the editor window — the broken ones too.

    ``GET /agents`` only shows what is playable. The window needs more:
    a broken file that shows up nowhere could never be repaired.
    """

    name: str
    kaputt: str | None = None


class AuftragAnlegen(BaseModel):
    agent: str = Field(min_length=1, max_length=200)
    task: str = Field(min_length=1, max_length=50_000)
    # Overrides the model from the agent's front matter, if set.
    endpoint_id: str | None = None
    # The folders picked in the start window. When set, they win over the
    # agent's own — the same way the window's model wins over the file's. None
    # or empty means: use whatever the agent file shares.
    folders: list[str] | None = None


class SchrittAntwort(BaseModel):
    nummer: int
    typ: str
    inhalt: str
    created_at: str

    @classmethod
    def aus(cls, schritt: AuftragSchritt) -> "SchrittAntwort":
        return cls(
            nummer=schritt.nummer,
            typ=schritt.typ,
            inhalt=schritt.inhalt,
            created_at=schritt.created_at,
        )


def werk_von(auftrag: Auftrag, eintrag: Cronjob | None) -> str:
    """Which piece of WORK a run belongs to — the id every run of one job
    shares, however many runs a restart chain cuts that job into.

    A run carries the cron entry that fired it (``cronjob_id``), and that is
    one run's worth of the answer, not the job's: a context overflow or a
    lost provider writes a continuation on a NEW entry and the rest of the
    work runs there (app/zwischenstand.py). Ten links of one dead-provider
    chain are ten entries' worth of rows about one disturbance.

    The chain already knows the way back — ``ursprung_id``, set on every
    continuation and always pointing at the real origin rather than at the
    immediate predecessor (``kettenfelder``, app/zwischenstand.py). So the
    origin is the name of the work, and the chain's own links answer with
    it. Nothing new is stored for this: the link was already there, and this
    only reads it.

    A run nobody scheduled is its own work, and so is one whose entry has
    been deleted since — there is nothing left to group it by, and grouping
    it with anything else would be a guess. Its continuation is not a guess:
    it names that run as its origin (``kettenfelder``), so the run somebody
    started and the link that finishes its work answer with the same id.
    """
    if eintrag is None:
        return auftrag.cronjob_id or auftrag.id
    return eintrag.ursprung_id or eintrag.id


def _json_objekt_lesen(roh: str | None) -> dict | None:
    """A JSON object a row carries as text — the stored question, the
    context reading — or nothing.

    A row written by an older version, or one somebody edited by hand, must
    not take the whole job list down — an unreadable question is the same as
    no question, and the run's state still says it is waiting.
    """
    if not roh:
        return None
    try:
        wert = json.loads(roh)
    except (TypeError, ValueError):
        return None
    return wert if isinstance(wert, dict) else None


class LaufmodellAntwort(BaseModel):
    """Which model a run started now would land on.

    The start window shows this under its model row instead of working it
    out for itself. ``endpoint_id`` is the id a run would be booked with —
    the same value the start hands to the run, so the window and the run can
    never name two different models. ``name`` is what a reader sees: the
    model as its server reports it.

    Both are empty when nothing is reachable: a run started now would be
    refused, and the window says so instead of naming a model.

    ``denklaenge`` is the thinking-length knob for that model, exactly the
    row `parameter.unterstuetzte()` hands out (`aktiv`, `grund`,
    `minimum`/`maximum`) — the agent mask locks its field on the same two
    conditions the model window locks its slider on and must
    not work them out a second time. It stays `None` where no model is
    known: then nothing has SAID this model cannot think, and "said nothing"
    may not be read as "cannot think" (`app/parameter.py`).
    """

    endpoint_id: str | None = None
    name: str | None = None
    denklaenge: dict[str, Any] | None = None


class AuftragAntwort(BaseModel):
    id: str
    agent: str
    task: str
    state: str
    end_reason: str | None
    result: str | None
    endpoint_id: str | None
    generation_id: str | None
    created_at: str
    updated_at: str
    # The run that started this one, when a run did — None for everything a
    # person or a schedule started. It is what makes the chain visible: a
    # branch nobody can see is a branch nobody can stop.
    parent_id: str | None = None
    # Which piece of work this run belongs to (``werk_von`` above) — what
    # lets the reports list show one dead-provider chain as the one
    # disturbance it is instead of one row per restart. Defaults to the run
    # itself, so a caller that has no cron entries in hand still gets a key
    # that groups nothing but this run.
    work_id: str
    # The cron entry that fired this very run — None for a run started by
    # hand. Not the same as ``work_id``: a continuation's work is its origin,
    # but the entry that fired it is its own chain row, which is the row the
    # cron list shows as running (frontend/src/lib/cronjobampel.svelte.js).
    cronjob_id: str | None = None
    # The question this run is standing on, when it is standing on one:
    # ``{"aufruf_id": …, "frage": …, "optionen": [...]}``. Handed out on the
    # LIST route on purpose — the waiting group has to draw the buttons
    # without fetching every run's transcript first.
    question: dict | None = None
    # The run's newest context reading — ``{"tokens", "kontextgroesse",
    # "prozent"}`` as its last ``kontext`` step wrote it
    # (app/kontextverbrauch.py) — or None before the first one. On the LIST
    # route for the same reason as the question: the tile draws it on every
    # row, running and finished, and fetching every transcript for one number
    # each would be a hundred requests.
    kontext: dict | None = None
    # The chat this job was started from — None for one a schedule or the
    # start window started. It is where the job's report and its questions
    # go, and what the chat's own list marks.
    chat_id: str | None = None
    # The tool the run called last, by name — the step the chat's agent row
    # shows. None before the first call.
    last_tool: str | None = None

    @classmethod
    def aus(
        cls,
        auftrag: Auftrag,
        *,
        werk: str | None = None,
        urspruenglicher_text: str | None = None,
        kontext: str | None = None,
        last_tool: str | None = None,
    ) -> "AuftragAntwort":
        return cls(
            id=auftrag.id,
            agent=auftrag.agent,
            # A restart chain's entry carries the real task on its own row
            # (app/zwischenstand.py ``basisaufgabe``) once one exists — the
            # run's own stored text is by then the wrapped "Continue this
            # job. Original task: …" prompt, not what a reader asked for.
            # A run nobody's chain claims (``urspruenglicher_text`` unset)
            # shows its own text exactly as it always did.
            task=urspruenglicher_text or auftrag.auftrag,
            state=auftrag.zustand,
            end_reason=auftrag.ende_grund,
            result=auftrag.ergebnis,
            endpoint_id=auftrag.endpoint_id,
            generation_id=auftrag.generation_id,
            created_at=auftrag.created_at,
            updated_at=auftrag.updated_at,
            parent_id=auftrag.eltern_id,
            work_id=werk or auftrag.cronjob_id or auftrag.id,
            cronjob_id=auftrag.cronjob_id,
            question=_json_objekt_lesen(auftrag.frage),
            kontext=_json_objekt_lesen(kontext),
            chat_id=auftrag.chat_id,
            last_tool=last_tool,
        )


class AuftragAntwortSchreiben(BaseModel):
    """What the user replied to a run's own question.

    Free text and a clicked label travel the same field, because they are the
    same thing: whoever types instead of choosing has answered. The ceiling is
    the one a message field has — an answer is a sentence, not a document.
    """

    antwort: str = Field(max_length=4000)


class AuftragDetail(AuftragAntwort):
    schritte: list[SchrittAntwort] = Field(default_factory=list)

    @classmethod
    def aus_mit_schritten(
        cls,
        auftrag: Auftrag,
        schritte: list[AuftragSchritt],
        *,
        werk: str | None = None,
        urspruenglicher_text: str | None = None,
    ) -> "AuftragDetail":
        detail = cls(
            **AuftragAntwort.aus(
                auftrag, werk=werk, urspruenglicher_text=urspruenglicher_text
            ).__dict__
        )
        detail.schritte = [SchrittAntwort.aus(schritt) for schritt in schritte]
        return detail
