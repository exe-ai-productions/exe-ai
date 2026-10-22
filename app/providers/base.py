"""Common interface of all model providers.

Adding a new provider means: write one file that implements ``Provider`` and
register it in the registry. The rest of the application — routes, database,
frontend — remains untouched. That is exactly why cloud models later are an
addition, not a rework.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal

import httpx

from app import i18n
from app.config import EndpointConfig
from app.kontextverbrauch import als_zahl

StueckSorte = Literal[
    "content",
    "reasoning",
    "stats",
    "error",
    "tool_call",
    "tool_call_laeuft",
    "kontext",
    "denktempo",
    # A finished item of the Responses wire that the next tool round of the
    # same turn hands back (app/providers/openai_responses.py).
    "response_item",
    # A content block of an Anthropic answer, in the order the answer
    # brought it: thinking blocks whole, text and tool calls as markers of
    # their place (app/providers/anthropic.py).
    "anthropic_block",
]


@dataclass
class Werkzeugaufruf:
    """A tool the model wants executed."""

    id: str
    name: str
    argumente: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatNachricht:
    role: str
    content: str
    # Only with role='assistant': which tools the model requested.
    werkzeugaufrufe: list[Werkzeugaufruf] = field(default_factory=list)
    # Only with role='tool': which call the result belongs to.
    werkzeugaufruf_id: str | None = None
    # Only with role='assistant', only on the Responses wire to OpenAI: the
    # round's sealed thinking and its text items with their `phase`, handed
    # back in the next round of the same turn
    # (app/providers/openai_responses.py). They live in the request only —
    # never stored, never carried past the turn — and no other wire reads
    # them.
    reasoning_items: list[dict[str, Any]] = field(default_factory=list)
    message_items: list[dict[str, Any]] = field(default_factory=list)
    # Only with role='assistant', only on the Anthropic wire: the round's
    # content blocks in the order the answer brought them — its thinking
    # blocks with their signature exactly as received, its text and tool
    # calls as markers of their place. The API wants a round's thinking
    # back unchanged and in order while its tool calls are answered
    # (app/providers/anthropic.py). The answer's tool log keeps them with
    # the round's first call, so an answer that failed and is asked again
    # hands them back; the history of earlier answers never carries them,
    # and no other wire reads them.
    anthropic_blocks: list[dict[str, Any]] = field(default_factory=list)
    # Only with role='user': an image as a data URL (vision). The provider
    # builds the OpenAI image format from it; endpoints without vision never
    # get one.
    bild_url: str | None = None
    # Several images on one message. The provider sends every entry as its
    # own image part; `bild_url` above stays for single-image callers and is
    # merged in by `alle_bild_urls` below.
    bild_urls: list[str] = field(default_factory=list)
    # The documents whose text this message carries, as the request builder
    # attached them (app/verlaufsbau.py). Never sent to a provider: a fold of
    # the list in memory reads it to say which documents leave the request
    # with the stretch it replaces (app/verdichtung.py), the way the fold of
    # a chat's rows does.
    dokumente: list[Any] = field(default_factory=list)
    # Where the pictures of this message came from, when a TOOL read them
    # (app/werkzeugbild.py): one path per image, in the same order. Empty for
    # everything a user attached — which is what tells the two apart where a
    # request retires old tool pictures (app/werkzeugkuerzung.py). Never sent
    # to a provider; it lives in the request only.
    werkzeugbilder: list[str] = field(default_factory=list)
    # A report the SERVICE wrote and hands over as the user's side of the
    # conversation — a finished background run's report, or the note a stop
    # leaves behind (stored as `art` "werkzeugmeldung",
    # app/verlaufsbau.py). It travels as a user message without being
    # anything the user said, so the environment block never goes in front
    # of it (app/grundprompt.restore_environment_block). Never sent to a
    # provider; it lives in the request only.
    service_report: bool = False
    # A summary a fold left in place of an earlier stretch — a summary row
    # of the chat (stored as `art` "verdichtung", app/verlaufsbau.py) or the
    # one a fold of the request in memory just wrote (app/verdichtung.py).
    # Marked by what it IS, never read off its text: a clock sentence or an
    # instruction set in front of the text hides the preamble it begins
    # with. Never sent to a provider; it lives in the request only.
    compacted_summary: bool = False

    def alle_bild_urls(self) -> list[str]:
        """Every image of this message, single and list merged, no doubles."""
        urls = list(self.bild_urls)
        if self.bild_url and self.bild_url not in urls:
            urls.insert(0, self.bild_url)
        return urls


@dataclass
class Generierungsanfrage:
    nachrichten: list[ChatNachricht]
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    modell: str | None = None
    # Further parameters under our own names (see app/parameter.py).
    # The provider translates them into its backend's names.
    parameter: dict[str, Any] = field(default_factory=dict)
    # Tools in OpenAI format. Empty = the model is offered none.
    werkzeuge: list[dict[str, Any]] = field(default_factory=list)
    zusatz: dict[str, Any] = field(default_factory=dict)


@dataclass
class Stueck:
    """One chunk from the answer stream."""

    sorte: StueckSorte
    text: str = ""
    daten: dict[str, Any] = field(default_factory=dict)
    # Only filled with sorte='tool_call'.
    werkzeugaufrufe: list[Werkzeugaufruf] = field(default_factory=list)


def zeitlimit(
    timeout: float, timeout_enabled: bool, read_timeout: float | None = None
) -> httpx.Timeout:
    """The read timeout is what `EndpointConfig.timeout_enabled` switches —
    off drops it so a long-silent server is never cut off mid-answer. The
    connect timeout stays either way: a server that cannot even be reached
    has nothing to wait for. Shared by every provider that builds its own
    `httpx.AsyncClient` for the model call, not just the OpenAI-compatible
    one.

    `read_timeout` lifts the read timeout alone, for a server that may go
    quiet for long while it works (a model on this machine reading a long
    prompt): the connect timeout is still `timeout`. With the switch off
    there is no read timeout at all, whatever this says."""
    if timeout_enabled:
        return httpx.Timeout(timeout, read=read_timeout or timeout)
    return httpx.Timeout(timeout, read=None)


class WerkzeugFortschrittsDrossel:
    """Decides how often a tool call still being written may report itself.

    While the model writes a long argument, nothing reaches the window: the
    call is only complete at the end of the stream. Measured with oMLX at 17
    token/s and an argument of 8804 characters that is 2.5 to 3 minutes of
    complete silence, although data flows the entire time.

    Reporting every fragment would be the other extreme — thousands of events
    for a single call. So a report goes out when the argument has actually
    grown **and** either ``mindestabstand`` seconds have passed since the last
    one or it has grown by ``mindestzuwachs`` characters — whichever comes
    first. The first report of a call always goes out at once: the name is
    already in the first packet and is the most valuable thing there is.

    The clock is handed in (``jetzt``) instead of read here. The callers
    already measure monotonic time for their own statistics, and this way the
    throttle can be tested without waiting.
    """

    def __init__(self, mindestabstand: float = 0.2, mindestzuwachs: int = 200) -> None:
        self.mindestabstand = mindestabstand
        self.mindestzuwachs = mindestzuwachs
        self._gemeldet: dict[int, tuple[float, int]] = {}

    def faellig(self, index: int, zeichen: int, jetzt: float) -> bool:
        """Whether this state may be reported — and notes it as reported."""
        letzte = self._gemeldet.get(index)
        if letzte is None:
            self._gemeldet[index] = (jetzt, zeichen)
            return True
        zeitpunkt, gemeldet = letzte
        if zeichen <= gemeldet:
            return False
        if (
            jetzt - zeitpunkt < self.mindestabstand
            and zeichen - gemeldet < self.mindestzuwachs
        ):
            return False
        self._gemeldet[index] = (jetzt, zeichen)
        return True


def zaehlung(wert: Any) -> int | None:
    """A token count a model server reported, or ``None`` — never a crash.

    These fields come straight off a server's response, a boundary no
    provider controls, and a malformed one there must cost the one reading it
    belongs to rather than the round it arrived with. The reading itself is
    ``kontextverbrauch.als_zahl``, the one place that knows what a usable
    count is; what this adds is the one rule of this program's own: a
    negative number is not a count.

    Here rather than in one provider: every reader of these numbers needs the
    same answer, and the two OpenAI wires and the Anthropic one all pass
    through this module.
    """
    zahl = als_zahl(wert)
    if zahl is None or zahl < 0:
        return None
    return zahl


def kontext_stueck(
    prompt_tokens: int | None, prompt_genau: bool, erzeugte_tokens: int
) -> Stueck:
    """One live reading of how full the context is, mid-answer.

    The shape lives here rather than in each provider so the three of them
    cannot drift apart on it. What the three fields promise:

      * ``prompt_tokens`` — the prompt of THIS round, as far as this
        provider knows it. ``None`` means it does not know; nothing is
        invented to fill the hole, the same way this file answers every
        other question it cannot answer.
      * ``prompt_genau`` — whether that number is the server's own complete
        count. ``False`` marks a floor: a count that leaves something out
        and can only be too small, never too large. A reader may raise a
        floor, never lower a complete count.
      * ``erzeugte_tokens`` — what this round has produced so far. Counted
        by us while the stream runs, so an estimate until the round's own
        metrics replace it at the end.

    Deliberately NOT a running total across rounds: the prompt of round N
    already contains every round before it and every tool result in
    between, so each round reports the whole standing on its own. Adding
    them up would count the same tokens once per round.
    """
    return Stueck(
        sorte="kontext",
        daten={
            "prompt_tokens": prompt_tokens,
            "prompt_genau": prompt_genau,
            "erzeugte_tokens": erzeugte_tokens,
        },
    )


class KontextDrossel:
    """Decides how often a running answer may report its context reading.

    The reading changes with every token, and one event per token is
    thousands of events for a single answer. So a reading goes out when it
    has actually changed **and** ``mindestabstand`` seconds have passed
    since the last one — half a second, which is as fast as an eye reads a
    bar and slow enough that a long answer costs a few hundred events
    rather than tens of thousands.

    Two readings jump the queue, for the same reason the tool throttle lets
    a call's name through at once: the very first one, and the one where
    the prompt stops being unknown. The prompt is by far the larger half of
    the sum, so a bar that waits its turn for it says nothing while it
    waits.

    The clock is handed in (``jetzt``) instead of read here — same as
    ``WerkzeugFortschrittsDrossel`` above, and for the same two reasons:
    the callers already measure monotonic time for their own statistics,
    and a throttle that reads its own clock cannot be tested without
    waiting for it.
    """

    def __init__(self, mindestabstand: float = 0.5) -> None:
        self.mindestabstand = mindestabstand
        self._zeitpunkt = 0.0
        self._gemeldet: tuple[int | None, int] | None = None

    def faellig(
        self, prompt_tokens: int | None, erzeugte_tokens: int, jetzt: float
    ) -> bool:
        """Whether this reading may go out — and notes it as gone out."""
        stand = (prompt_tokens, erzeugte_tokens)
        if self._gemeldet is None:
            self._zeitpunkt, self._gemeldet = jetzt, stand
            return True
        if stand == self._gemeldet:
            return False
        # The prompt becoming known at all is news of its own. A prompt that
        # merely CHANGES afterwards waits its turn like everything else: mlx
        # repeats its timings block on every single chunk, and a number that
        # wobbles there must not buy itself an event each time it does.
        neu_bekannt = self._gemeldet[0] is None and prompt_tokens is not None
        if not neu_bekannt and jetzt - self._zeitpunkt < self.mindestabstand:
            return False
        self._zeitpunkt, self._gemeldet = jetzt, stand
        return True


class ProviderFehler(Exception):
    """Error while talking to a model server.

    Carries the answer as well as the sentence built from it. One caller has
    to decide what went wrong, and it needs the status code and the body the
    server actually sent — reconstructing those from a formatted sentence
    would be guesswork.

    It has two readers with two languages. ``str()`` is English, because the
    model is one of them: a job's report says why the run ended, and a model
    handed the window's German answers in German. The person at the window
    reads ``text(sprache)`` — the same sentence from the same catalogue
    entry, in the language of their page. What the server itself said stands
    behind the colon and travels unchanged in both: a rewritten error hides
    what really happened.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        rohtext: str | None = None,
        key: str = "",
        **values: object,
    ) -> None:
        # ``message``, not ``text``: a catalogue entry names its placeholder
        # ``{text}`` (the provider's own words), and a keyword argument may
        # not collide with the parameter holding the sentence itself.
        super().__init__(message)
        self.status = status
        self.rohtext = rohtext
        self.key = key
        self.values = values

    def text(self, language: str) -> str:
        """The sentence for one reader. Without a catalogue key (a caller
        that built its own words) the English text is what there is.

        For the default language this IS ``str(self)``, not the same sentence
        rendered a second time: one source, so the two cannot drift apart.
        """
        if not self.key or language == i18n.STANDARDSPRACHE:
            return str(self)
        return i18n.t(self.key, language, **self.values)


def provider_error(
    key: str, *, status: int | None = None, rohtext: str | None = None, **values: object
) -> ProviderFehler:
    """The one way to raise this: from a catalogue key, both copies built
    here so they cannot drift apart. ``str()`` is the English one — the
    model reads it — and ``text(sprache)`` the same sentence in the
    language of the window."""
    return ProviderFehler(
        i18n.t(key, i18n.STANDARDSPRACHE, **values),
        status=status,
        rohtext=rohtext,
        key=key,
        **values,
    )


def require_stream_end(end_reason: str | None, provider_name: str) -> None:
    """No stream ends unnamed: one that closes without a single packet having
    said WHY it stopped is a provider that stopped mid-answer, and half an
    answer must never be stored as a whole one.

    The reading is the PROTOCOL, never the text: a finished answer always
    names its end (stop, length, tool calls), and a text pattern would be a
    second, weaker answer to the same question. Each provider reads the
    reason in its own protocol and calls this once its stream is over —
    before any held-back text or assembled tool call is handed out, since
    half a call must not run. The rule, its key and its sentence stand here
    once, so the providers cannot drift apart on them."""
    if end_reason is None:
        raise provider_error("fehler.anbieter_ende_fehlt", name=provider_name)


# The longest sentence of a refusal that is kept: what a provider writes in
# an error is short; a page of markup in its place is not a sentence.
REFUSAL_SENTENCE_LIMIT = 400


def refusal_of(response: httpx.Response, *keys: str) -> tuple[str, str] | None:
    """What a provider says about refusing a request: the kind of the error
    and its sentence, read from the body of the answer. None when the body
    holds no sentence.

    The providers word their errors alike: an object ``error`` with ``message``
    and ``type`` (or ``code``, or ``status``), alone or as the one element of
    a list; a plain string under ``error``; or ``detail`` / ``message`` at the
    top. A ``keys`` value that the sentence repeats is replaced by "…", so the
    sentence can go to the log and the window as it stands.
    """
    try:
        body = response.json()
    except ValueError:
        return None
    if isinstance(body, list) and len(body) == 1:
        body = body[0]
    if not isinstance(body, dict):
        return None
    error = body.get("error")
    kind = ""
    if isinstance(error, dict):
        sentence = error.get("message")
        kind = str(error.get("type") or error.get("status") or error.get("code") or "")
    elif isinstance(error, str):
        sentence = error
    else:
        sentence = body.get("detail") or body.get("message")
    if not isinstance(sentence, str) or not sentence.strip():
        return None
    sentence = sentence.strip()
    for key in keys:
        if key:
            sentence = sentence.replace(key, "…")
    return kind, sentence[:REFUSAL_SENTENCE_LIMIT]


class Provider(ABC):
    """What every provider must be able to do."""

    # Why the last reachability check said no, in the words the server gave
    # (a provider that is told one fills it); None for silence or an answer
    # without a reason.
    letzter_grund: str | None = None
    # The refusal the log last carried a line for (status, kind, sentence):
    # the check repeats every few seconds, and the same answer is told once.
    _gemeldete_ablehnung: tuple[int, str, str] | None = None

    def __init__(self, endpunkt: EndpointConfig) -> None:
        self.endpunkt = endpunkt

    def ablehnung_melden(self, log: logging.Logger, status: int, grund: tuple[str, str] | None) -> None:
        """Writes the line about a refused check — the status and, where the
        body gave one, its kind and sentence. The same refusal as the one
        before is not written again until an answer in between was none."""
        stand = (status, *(grund or ("", "")))
        if stand == self._gemeldete_ablehnung:
            return
        self._gemeldete_ablehnung = stand
        if grund is None:
            log.warning("%s refused the check with %d and gave no reason", self.name, status)
        else:
            kind, sentence = grund
            log.warning(
                "%s refused the check with %d%s: %s",
                self.name, status, f" {kind}" if kind else "", sentence,
            )

    def ablehnung_vorbei(self) -> None:
        """The check was not refused: the next refusal is told again."""
        self._gemeldete_ablehnung = None

    @property
    def id(self) -> str:
        return self.endpunkt.id

    @property
    def name(self) -> str:
        """What the endpoint is called in error messages."""
        return self.endpunkt.name or self.endpunkt.id

    @property
    def faehigkeiten(self) -> dict[str, bool]:
        """What the provider can do — the frontend arranges its controls accordingly."""
        return self.endpunkt.capabilities.model_dump()

    @abstractmethod
    async def erreichbar(self, timeout: float = 3.0) -> bool:
        """Quick check whether the server answers."""

    async def modellname(self, timeout: float = 3.0) -> str | None:
        """What the model is called on the server.

        By default there is none — whoever can answer it overrides this.
        """
        return None

    def ortsspuren(self) -> bool:
        """Whether answers already seen name this a local serving stack.

        Read by the discovery to tell an endpoint entered under the wrong
        dialect from one that is right (app/dialektverdacht.py). Answered by
        whoever sees such answers; by default nobody does.
        """
        return False

    def kontext_vorlaeufig(self) -> bool:
        """Whether the number :meth:`kontextgroesse` answered last is only a
        provisional one — a model that is not loaded yet names the most it
        can take, and its own window comes with the loading.

        Read by the discovery, which asks again on the next pass for as long
        as this holds. Answered by whoever sees such answers; by default
        nobody does, and every number is final.
        """
        return False

    async def kontextgroesse(
        self, timeout: float = 3.0, modellname: str | None = None
    ) -> int | None:
        """How many tokens fit into the context — asked of the server.

        Not every server answers this. Whoever cannot returns None; then the
        value from the configuration applies, if there is one. A configured
        ``0`` counts as none too — nobody means a context of zero, the same
        reading the overrides in ``openai_kompatibel.py`` and
        ``anthropic.py`` already give it.
        """
        return self.endpunkt.context_tokens or None

    async def context_per_model(self, timeout: float = 3.0) -> dict[str, int] | None:
        """The window of every model in a catalogue, by model id.

        A server holding many models names a window for each of them, and a
        catalogue entry picked in the chat is a model of its own: it carries
        its own number rather than the one of whichever model came first.
        An empty mapping is an answer — the list names no window — and every
        entry then shows the endpoint's one window, as it always did.
        ``None`` means the question went unanswered and is worth asking
        again.
        """
        return {}

    async def answer_limit_per_model(self, timeout: float = 3.0) -> dict[str, int] | None:
        """The longest answer of every model in a catalogue, by model id.

        The twin of ``context_per_model``: a limit a model list names belongs
        to the model it is listed for, never to the catalogue as a whole. A
        model the mapping does not name has no limit. An empty mapping is an
        answer; ``None`` means the question went unanswered.
        """
        return {}

    async def hoechste_antwort(
        self, timeout: float = 3.0, modellname: str | None = None
    ) -> int | None:
        """The longest answer this model is allowed to write, asked of the
        provider rather than guessed (app/antwortgrenze.py).

        A different number from the context window: the window is what the
        whole request may weigh, this is what the answer alone may. Providers
        that publish it put it in their model list; most local servers have
        no such limit at all and say nothing, which is not the same as zero.
        """
        return None

    async def denkquellen(self, timeout: float = 3.0) -> dict[str, Any]:
        """What the server itself says about thinking.

        Detection through the chat template only works where there is a
        template to read. A cloud provider has none, and an MLX server
        serves none either — but both answer the question in their own way:
        Anthropic's model list carries the accepted depths per model, an
        MLX server names each model's family. Whoever has such an answer
        overrides this; the rest say nothing, which is not the same as "no".
        """
        return {}

    async def mlx_erkennen(self, timeout: float = 3.0) -> bool | None:
        """Whether this address turns out to be an oMLX server
        (app/dialekterkennung.py).

        Only a provider that speaks the OpenAI interface at an address of
        its own can be one; everyone else answers no without asking. ``None``
        means that no answer came at all, and the discovery asks again.
        """
        return False

    async def modelle_auflisten(self, timeout: float = 3.0) -> list[str]:
        """Every model this provider offers.

        A local server has exactly one loaded and reports that; a provider in
        the cloud has a catalogue. Whoever cannot answer returns an empty list
        — then the endpoint stands for itself, the way it always did.

        Asking rather than maintaining: what a provider offers changes without
        us, and a list kept by hand is wrong the day after it is written.
        """
        return []

    @abstractmethod
    def streamen(self, anfrage: Generierungsanfrage) -> AsyncIterator[Stueck]:
        """Produces the answer chunk by chunk.

        If the call is aborted (``aclose``), the connection to the model
        server must be closed — the stop button depends on this.
        """
