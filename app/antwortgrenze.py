"""How long one answer may be — one function for the order decided for it,
so no caller works it out a second way.

There is no shipped ceiling any more. What the user set wins outright; where
nothing is set the answer is "Auto", and Auto means the largest number that
still fits:

    min(the provider's own limit for this model, window - input - margin)

The provider's limit is left out where nobody names one, and then the window
alone decides. The input is an ESTIMATE — every piece measured by
``app/tokenmass.py``'s ``tokens`` — because there is no tokenizer on this
side. An estimate that falls short is caught one layer
further on: the provider refuses, ``app/kontextvoll.py`` reads the refusal,
and the request goes again with a lower ceiling or a folded history.

What "Auto" means depends on the WIRE the request goes out on. On the
Anthropic wire it means the largest number that still fits: that server
rejects a request without ``max_tokens``, so one always travels, and the
calculation above keeps it inside the window. On the OpenAI wire — OpenAI,
vLLM, llama.cpp, oMLX, Ollama — Auto means NO number at all: the server
decides how long an answer may be, and a number is sent only where
something was set. A number this side guesses at can only be smaller
than what the server would have allowed, and a guess that falls short cuts
an answer off for no reason anybody chose.

Beside that one calculation this module carries the provider's own limit —
one number per model from the model list (``app/discovery.py``,
``hersteller_max_tokens`` and ``answer_limit_per_model``)
and one that a refusal named (:class:`Zug`). The second is a fact about ONE
answer of a chat, or one job run: held by that answer or run alone, written
where a refusal was read and applied to every request it sends from then on —
the retry, and every tool round after it — so ten rounds are not turned down
ten times for the same number. No other answer or run at the same address — a
second chat, a job, a fold — reads it or clears it (``geltender_deckel``).
Never written to the settings and never to the endpoint's shared state — a
stored number outlived the answer it was learned in and went on to bind every
later request and every model behind the same address. The context window
beside it (``app/fenstergroesse.py``) stays learned, because a smaller window
is a fact about the model and not about one answer.
"""

from __future__ import annotations

import dataclasses
import json
import logging

from app import kontextdruck, kontextvoll
from app.tokenmass import tokens as tokenmass_tokens

log = logging.getLogger(__name__)

# The smallest ceiling the house's own request schema accepts
# (``app/api/v1/schemas.py``, ``max_tokens: int | None = Field(..., ge=1)``).
# Not a default and not a floor to aim for: it is the edge. An input large
# enough to reach it has already been folded by the time it gets here
# (app/chatverdichtung.py, app/verdichtung.py); this only keeps the request
# sendable, because ``max_tokens: null`` fails as a format error that no
# "too long" pattern recognizes and therefore nothing can retry.
MINDESTWERT = 1

# The provider class that needs a number (``app/providers/__init__.py``).
# Anthropic refuses a request without ``max_tokens``; every other wire this
# house speaks leaves the length to the server.
ANTHROPIC_DRAHT = "anthropic"


@dataclasses.dataclass
class Zug:
    """One answer of a chat, or one job run, and every request it sends —
    the one holder of what a refusal brought its ceiling down to.

    Two numbers, each with its own life, and nothing else holds either:

    * ``max_tokens`` — the output limit a refusal NAMED for the model
      (:func:`aus_fehler_lernen`). A fact about the model, so it binds every
      later request of the answer: the retry and every tool round after it.
      Ten rounds are not turned down ten times for the same number.
    * ``round_tokens`` — a ceiling worked out from the window and the input
      a refusal named (``kontextvoll.abhilfe``). A fact about the input of
      ONE round, which the next round no longer sends; it holds for the
      retries of that round and goes at :meth:`round_begins`.

    Made once where the answer or the run begins and handed to every round
    it sends; read by :func:`geltender_deckel`, :func:`forced_ceiling` and
    :func:`capped_setting`. Both numbers only ever come down. It lives with
    that answer and nowhere else: the endpoint state is shared by every
    chat, job and fold at the same address, and a number kept there was read
    and cleared by requests it had nothing to do with. The next answer makes
    a new one and starts over from the model list.
    """

    max_tokens: int | None = None
    round_tokens: int | None = None

    def lower(self, tokens: int | None) -> bool:
        """Takes a stated output limit where it is below what is held, or
        nothing is held yet. True where the held number changed."""
        if not tokens or tokens < 1:
            return False
        if self.max_tokens is not None and self.max_tokens <= tokens:
            return False
        self.max_tokens = tokens
        return True

    def lower_round(self, tokens: int | None) -> None:
        """Takes a ceiling for the round being sent, where it is below the
        one the round already holds."""
        if tokens and tokens >= 1 and (
            self.round_tokens is None or tokens < self.round_tokens
        ):
            self.round_tokens = tokens

    def input_folded(self, freed: int) -> None:
        """The round's input was folded and is ``freed`` tokens lighter.
        A round ceiling was the room a refusal left beside the larger
        input; that room grew by what the fold freed. Worked out from the
        refusal's own numbers, not from the window held for the model: the
        refusal is what the server said about this very request."""
        if self.round_tokens is not None and freed > 0:
            self.round_tokens += freed

    def round_begins(self) -> None:
        """A new round: what the last round's input was turned down for
        does not bind it."""
        self.round_tokens = None

    def held(self) -> int | None:
        """The lowest ceiling held for the request being sent, or None."""
        numbers = [n for n in (self.max_tokens, self.round_tokens) if n]
        return min(numbers) if numbers else None


def forced_ceiling(ceiling: int | None, zug: Zug | None) -> int | None:
    """The ceiling a request of this answer has to go out with instead of
    the one it was built with (``ceiling``), or ``None`` to send it as built.

    The held number wins where the request carries none or a larger one —
    also over a number somebody SET: the provider has already turned this
    answer down for anything above it, and sending the set number again
    costs one more refused request per round and changes nothing. Where the
    request already carries less, it stays as it is.
    """
    held = zug.held() if zug is not None else None
    if not held:
        return None
    if ceiling is None or held < ceiling:
        return held
    return None


def capped_setting(setting: int | None, zug: Zug | None) -> int | None:
    """The set answer length with the held output limit as its upper bound —
    for a request of this answer that is built apart from its rounds (the
    handoff of a job, ``app/zwischenstand.py``), which takes a setting only
    as an upper bound anyway (:func:`hoechste_passende`). Only the stated
    limit: what one round's input was turned down for says nothing about
    the handoff's own room, which that request works out itself."""
    held = zug.max_tokens if zug is not None else None
    if not held:
        return setting
    return min(setting, held) if setting else held


def eingabe_schaetzen(nachrichten, werkzeuge=()) -> int:
    """What a built request weighs on the way in, in tokens.

    Characters divided by the house proxy, the same currency
    ``app/kontextdruck.py`` and ``app/dokumentbudget.py`` already count in.
    A tool definition is counted WHOLE — the length of the Python
    representation of the definition, which carries its name, its
    description and the JSON schema of its parameters alike. That is not
    the exact string a provider finally sends, since punctuation and key
    order differ per provider, but every part of it does travel: a schema
    with twenty parameters weighs many times a one-line tool, and counting
    the prose alone would leave out the part that grows.

    A message is more than its ``content``. Further parts of
    ``ChatNachricht`` (``app/providers/base.py``) travel in the very same
    request and are counted here with it:

    * ``werkzeugaufrufe`` — a tool round's own bulk. The name and the JSON
      arguments go out exactly as the provider serializes them
      (``app/providers/openai_kompatibel.py``, ``_nachricht_bauen``), and a
      write call carrying kilobytes of arguments grows only there, never in
      ``content``.
    * images — priced by :func:`app.kontextdruck.bild_zeichen`, the one
      per-image estimate the fold trigger already reckons with. NOT by the
      length of the data URL: that is the transport, not what the model is
      billed for.
    * ``reasoning_items`` — a round's sealed thinking, handed back whole in
      the next round on OpenAI's Responses wire
      (``app/providers/openai_responses.py``). Counted without its
      ``encrypted_content`` (:func:`_item_weight`). Its text items
      (``message_items``) are not counted again: their text is the
      message's ``content`` already.

    Counted apart, a chat with a picture in it weighed nothing at all for
    its image and asked for a ceiling the size of the whole window — one
    refusal on every single request of that chat, lowered a layer later by
    ``app/kontextvoll.py`` instead of never happening.
    """
    zeichen = 0
    for nachricht in nachrichten:
        zeichen += tokenmass_tokens(nachricht.content)
        for aufruf in getattr(nachricht, "werkzeugaufrufe", None) or ():
            zeichen += tokenmass_tokens(aufruf.name) + tokenmass_tokens(
                json.dumps(aufruf.argumente or {}, ensure_ascii=False, default=str)
            )
        bilder = getattr(nachricht, "alle_bild_urls", None)
        if bilder is not None:
            zeichen += kontextdruck.bild_tokens(len(bilder()))
        for teil in getattr(nachricht, "reasoning_items", None) or ():
            zeichen += _item_weight(teil)
    for werkzeug in werkzeuge or ():
        zeichen += tokenmass_tokens(str(werkzeug))
    return zeichen


def _item_weight(item) -> int:
    """What one thinking item weighs as it travels, ``encrypted_content``
    left out.

    The ciphertext is priced by the provider's own count, never by its
    length on this side — it can run to megabytes for a handful of real
    tokens — so its bytes would claim room the request does not take.

    Every other key and value is counted where it stands, walked rather than
    copied and serialized: the estimate is asked several times per round,
    and a copy of each item made only to blank one field and write the rest
    out as JSON was work done again and again for the same items.
    """
    if isinstance(item, dict):
        return sum(
            tokenmass_tokens(str(key)) + _item_weight(value)
            for key, value in item.items()
            if key != "encrypted_content"
        )
    if isinstance(item, (list, tuple)):
        return sum(_item_weight(value) for value in item)
    if item is None:
        return 0
    return tokenmass_tokens(str(item))


def _rechnung(hersteller_max: int | None, fenster: int, eingabe_tokens: int) -> int:
    """Auto's own arithmetic, before the edge below it is applied.

    Kept apart from :func:`aufloesen` because two questions are asked of the
    same sum: what number the request goes out with, and whether that number
    is still a real answer or only the edge. Answering the second one by
    comparing the first against :data:`MINDESTWERT` cannot work — a window
    that leaves exactly one token and one that leaves minus thirty thousand
    both come out of ``aufloesen`` as 1.
    """
    passt = fenster - eingabe_tokens - kontextvoll.SICHERHEITSABSTAND
    if hersteller_max:
        passt = min(hersteller_max, passt)
    return passt


def anthropic_draht(zustand) -> bool:
    """Whether this endpoint's requests go out on the Anthropic wire.

    The provider CLASS decides it, not the parameter dialect: the dialect
    says what the fields and the thinking switch are called, the class is
    what actually writes the body (``app/providers/__init__.py``). Asked of
    the endpoint's configuration, so a mock in a test answers it too.
    """
    endpunkt = getattr(zustand, "endpunkt", None)
    return getattr(endpunkt, "provider", None) == ANTHROPIC_DRAHT


def aufloesen(
    eingestellt: int | None,
    hersteller_max: int | None,
    fenster: int,
    eingabe_tokens: int,
    *,
    anthropic: bool,
) -> int | None:
    """The ceiling this one request goes out with, or ``None`` for none.

    A number somebody set wins outright — the slider, the agent head, the
    settings. Otherwise Auto, and Auto depends on the wire (see the module
    head): on the Anthropic wire the largest number that still fits, capped
    by the provider's own limit for this model wherever one is known; on the
    OpenAI wire no number at all, so the server decides.

    ``anthropic`` is the wire, asked of the endpoint by
    :func:`anthropic_draht`. Named rather than guessed here: this module
    knows nothing about endpoints, and every caller has the state in hand.
    """
    if eingestellt:
        return eingestellt
    if not anthropic:
        return None
    return max(MINDESTWERT, _rechnung(hersteller_max, fenster, eingabe_tokens))


def hoechste_passende(
    eingestellt: int | None,
    hersteller_max: int | None,
    fenster: int,
    eingabe_tokens: int,
) -> int:
    """The largest ceiling one request can carry and still fit the window —
    capped by a number somebody set, but never simply carrying it the way
    :func:`aufloesen` does: here a setting is an upper bound on the answer,
    not a promise that it still fits.

    The one caller (``app/zwischenstand.py``, the context-full handoff) asks
    for this on every wire, unlike :func:`aufloesen` — the handoff fires at
    :data:`app.zwischenstand.SCHWELLE_PROZENT` of the WHOLE window,
    deliberately the same number the context bar itself shows, so by the
    time its own request goes out the ordinary round ceiling routinely no
    longer fits beside the transcript that triggered it — on the OpenAI wire
    as much as the Anthropic one, where Auto otherwise sends no number at
    all and leaves the fit to the server.
    """
    passt = max(MINDESTWERT, _rechnung(hersteller_max, fenster, eingabe_tokens))
    return min(eingestellt, passt) if eingestellt else passt


def reicht_nicht(
    eingestellt: int | None,
    hersteller_max: int | None,
    fenster: int,
    eingabe_tokens: int,
    *,
    anthropic: bool,
) -> bool:
    """Whether Auto has no room left for an answer at all.

    True where window less input less margin no longer goes past
    :data:`MINDESTWERT` — a window that leaves exactly that one token is
    out of room too. Then the request the caller is about to send would
    carry the edge rather than a ceiling, the server would not refuse it —
    it answers with a single token — and neither ``app/kontextvoll.py`` nor
    the fold would ever see that there was a problem. So the caller folds
    FIRST and asks again, which is the same cure a refusal gets, only
    without the detour over the server.

    Only the window decides. The provider's own limit caps the ceiling
    (``hersteller_max``) but is a real number of tokens the model may write,
    never a sign that the input has left no room.

    A number somebody set is never "not enough": it is what the user asked
    for, and an input too large for it is refused by the provider, which is
    where the lowering and the fold already live.

    Neither is Auto on the OpenAI wire: no number goes out there, so there
    is no edge to end up carrying. What does not fit comes back as the
    provider's own refusal, which is where the fold and the lowering already
    live (``app/kontextvoll.py``).
    """
    if eingestellt or not anthropic:
        return False
    return _rechnung(None, fenster, eingabe_tokens) <= MINDESTWERT


def hoechstwert(*, server: int | None, gelernt: int | None) -> int | None:
    """The provider's own limit for this model, or ``None`` where nobody
    names one.

    The SMALLER of the two wins where both have something to say. A refusal
    is a hard upper bound — the provider has already turned a request down
    for the number it named — while a model list only publishes what an
    endpoint claims, and an OpenAI-compatible middleman's list can claim
    more than the model behind it allows. Guessing wrong in that direction
    costs every single request a failed attempt; guessing wrong the other
    way costs answer length and nothing else.

    Nothing is invented where neither has anything to say — then the window
    alone decides what fits.
    """
    if server and gelernt:
        return min(server, gelernt)
    return server or gelernt or None


def aus_fehler_lernen(repositories, zustand, fehler: BaseException, zug: Zug | None) -> None:
    """Reads an output limit out of a refusal and hands it to the request
    that was turned down — one function for the chat path and the job path
    alike, called wherever ``kontextvoll.bei_fehler(fehler)`` is true.

    The number goes into ``zug``, the request's own holder, and nowhere
    else: not into the settings and not into the endpoint state. That is the
    whole difference to the context window beside it: a smaller window is a
    fact about the model and stays learned (``app/fenstergroesse.py``), a
    smaller answer length is what ONE request just got turned down for. Kept
    in the settings it outlived its turn, and on an endpoint with a
    catalogue a number read from one model's refusal bound every other model
    behind the same address; kept on the endpoint state, a second chat, a
    job or a fold at the same address read it and cleared it. So it is held
    for the one request's turn alone.

    ``zug`` is ``None`` where the request is over and nothing is sent again:
    there is nobody left for the number to bind, and it is dropped. The held
    number only ever comes down (:meth:`Zug.lower`).

    Learned even where the model list already named one, and from then on
    the smaller of the two is what binds (:func:`hoechstwert`): the list
    publishes what an endpoint claims, the refusal is the provider turning
    a request down for a number it will not accept, and a claim above that
    would cost the retry a second failed attempt.

    Every wire alike, and every wording :mod:`app.kontextvoll` reads a stated
    limit out of (``hersteller_deckel_aus_fehler``) — the same reading the
    retry's own lowered ceiling comes from (``kontextvoll.abhilfe``).

    ``repositories`` is still taken so both callers stay symmetric with
    ``fenstergroesse.aus_fehler_lernen`` — this half has nothing to write
    it to. A stored value from an older installation is not read anywhere:
    it simply stops mattering.
    """
    del repositories  # nothing is written down here, on purpose

    if zug is None:
        return
    tokens = kontextvoll.hersteller_deckel_aus_fehler(fehler)
    if not zug.lower(tokens):
        # Nothing named, or already applied by an earlier refusal of the
        # same answer.
        return
    log.info(
        "Endpoint %s: output limit %d from a refusal, for this answer",
        zustand.endpunkt.id,
        tokens,
        extra={"ereignis": "antwortgrenze_gelernt", "endpoint_id": zustand.endpunkt.id},
    )


async def serverseitig_aufloesen(zustand, repositories, timeout: float) -> int | None:
    """Asks the server, reads a learned value, and resolves the limit — the
    twin of ``fenstergroesse.serverseitig_aufloesen``, for the other half of
    the same request.

    ``repositories`` is taken for symmetry with the twin and is not read:
    what the server says needs no database.

    The answer is the SERVER's own number, and nothing else. The value a
    refusal named is a fact about one request, and it is read where a
    request is built (``geltender_deckel``) — folding it in here would write
    it into ``hersteller_max_tokens`` through this back door and give it the
    permanence it must not have.
    """
    del repositories

    try:
        return await zustand.provider.hoechste_antwort(timeout, zustand.gemeldeter_name)
    except Exception:  # noqa: BLE001 - purely supplementary information
        log.debug("Answer limit of '%s' cannot be determined", zustand.endpunkt.id)
        return None


def listengrenze(zustand, modell: str | None = None) -> int | None:
    """What the model list names as the longest answer of the request's
    model. A limit belongs to the model it is listed for:
    ``hersteller_max_tokens`` is the reported model's, and any other model of
    a catalogue reads its own entry in ``answer_limit_per_model`` — a model
    the list names no limit for has none. A server with one model keeps no
    per-model list: its one number is that model's, whatever name the
    request gives it."""
    gemeldet = getattr(zustand, "gemeldeter_name", None)
    je_modell = getattr(zustand, "answer_limit_per_model", None)
    if not modell or modell == gemeldet or je_modell is None:
        return getattr(zustand, "hersteller_max_tokens", None)
    return je_modell.get(modell)


def geltender_deckel(zustand, modell: str | None = None, zug: Zug | None = None) -> int | None:
    """The ceiling that binds the request being built — the one reader.

    ``modell`` is the model the request goes to; without one, the model the
    server reports. ``zug`` is the answer's own holder (:class:`Zug`);
    without one — a fold, a handoff — only the model list speaks.

    Two numbers can be in play and they come from different places: what the
    provider's model list says about this model (``listengrenze``,
    a regular model information that stands for every request), and what a
    refusal of THIS answer named (``zug``). The smaller wins where both say
    something — the refusal is the provider turning a request down, the
    list only publishes what an endpoint claims (``hoechstwert``).

    One reader, because the two belong together and eight call sites read
    them apart: the chat path, the job path, and the two folding paths each
    asked the field directly, so a change to what a field holds had to be
    found in all of them.
    """
    return hoechstwert(
        server=listengrenze(zustand, modell),
        gelernt=zug.max_tokens if zug is not None else None,
    )
