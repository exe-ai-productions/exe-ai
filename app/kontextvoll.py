"""Recognizing a provider's "this request does not fit my context" answer,
and what to do before sending it again — fold, and how hard, or lower the
answer ceiling for that one request — one reading for a chat and a job
alike.

Model servers report a full context only as error text: the OpenAI format
has no error class for it, and every server words it its own way. Hence
patterns rather than a type, and better one too few than a false match —
whatever does not match stays an ordinary error.

Where each pattern comes from:

* llama.cpp answers HTTP 400 before the stream starts:
  ``request (755 tokens) exceeds the available context size (256 tokens),
  try increasing it``, type ``exceed_context_size_error``.
* Anthropic answers 400 ``invalid_request_error`` with "prompt is too long"
  when the input alone exceeds the window.
* OpenAI answers 400 with code ``context_length_exceeded`` and "This
  model's maximum context length is ... tokens".
* oMLX answers 400 ``Prompt too long: N tokens exceeds max context window
  of M tokens`` — caught by "context window".
* "too many tokens": other servers' wording, recognized before this module
  existed.
* Anthropic answers 400 in two further shapes once the input plus the
  answer's ceiling is what overruns the window, rather than the input on its
  own: one naming ``available_tokens``, one saying ``input length and
  max_tokens exceed context limit``. Both name the ceiling we sent, so both
  are answered by lowering it rather than by folding (see :func:`abhilfe`).
* OpenAI answers 400 ``max_tokens is too large: N. This model supports at
  most M completion tokens`` when the ceiling alone is past what the model
  allows, whatever the input. That wording carries the allowed number
  itself, so the retry can use it directly.
* DashScope answers the same case in two wordings of its own, each carrying
  the allowed number too: ``Range of max_tokens should be [1, M]`` and
  ``exceeds model's maximum output tokens (M)``.
* vLLM answers 400 ``max_tokens=Z cannot be greater than max_model_len=W``
  when the answer's ceiling alone is past the model's window
  (``vllm/renderers/params.py``, ``TokenizeParams``). "max_model_len" is
  counted as a full context.

A refusal that names the INPUT is answered by folding, even where an answer
length somebody set is as large as the whole window: what did not fit is the
input, and the card would send the user to a setting that had nothing to do
with it (``_EINGABE_GENANNT``). That is the first question asked of any
recognized refusal, before a single number in it is read — the same wording
also decides whether a refusal is recognized at all
(:func:`ist_kontext_voll`).
"""

from __future__ import annotations

import dataclasses
import re

# Wordings that name the CONTEXT — the window, the model's limit — rather
# than the input. Both families are asked by :func:`ist_kontext_voll`; the
# one naming the input stands once, in ``_EINGABE_GENANNT``, so a wording
# cannot be in one place and missing in the other.
MUSTER = (
    "context length",
    "context_length_exceeded",
    "context window",
    "maximum context",
    "too many tokens",
    "exceed_context_size_error",
    "available_tokens",
    "exceed context limit",
    "max_model_len",
    # vLLM's own prompt check: "The decoder prompt (length 9000) is longer
    # than the maximum model length of 8192." Counted as a full context.
    "maximum model length",
)

# A rate limit is never a full context, however it is worded: a limit on
# tokens PER MINUTE can read a lot like one, and folding the history because
# the account is busy would throw a conversation's detail away for nothing.
RATENGRENZE = 429

# How many times a request the provider called too long is folded, or sent
# with a lower answer ceiling, before the answer ends with the context-full
# card.
FALTVERSUCHE = 3

# What to do about a refusal (see :func:`abhilfe`).
FALTEN = "falten"
GRENZE = "grenze"
KARTE = "karte"
# The answer length somebody SET is on its own as large as the window, or
# larger: no fold can make room for it, so the round stops at once and says
# so: compression cannot fix it. Where the refusal's own words name the
# INPUT instead (``_EINGABE_GENANNT``), folding IS the cure and this ending
# never comes.
LIMIT_TOO_LARGE = "limit_too_large"

# Taken off what the refusal leaves free for the answer, so the retry does
# not land exactly on the edge the provider counts to.
SICHERHEITSABSTAND = 64


def ist_kontext_voll(status: int | None, text: str | None) -> bool:
    """True when this error says the request did not fit the model's context.

    Asked of the whole refusal text, both word families: the one naming the
    context and the one naming the input (``_EINGABE_GENANNT``). A refusal
    this says no to is never handed to :func:`abhilfe` at all — the callers
    end the round as the plain provider error it looks like — so a wording
    missing here is a rule that never runs.
    """
    if status == RATENGRENZE or not isinstance(text, str):
        return False
    klein = text.lower()
    return any(muster in klein for muster in MUSTER) or _eingabe_genannt(klein)


def is_output_cap(status: int | None, text: str | None) -> bool:
    """True when this error says the ANSWER's length is what the model does
    not take — a separate signal from a full context, kept apart from the
    overflow signals.

    A stated output limit (``_HERSTELLER_DECKEL``: OpenAI's "supports at
    most N completion tokens", DashScope's "Range of max_tokens should be
    [1, N]" and "exceeds model's maximum output tokens (N)") in a refusal
    that does not name the input. One that ALSO names the input is a full
    context — folding cures it — whatever limit it quotes beside it.

    Read by its whole sentence rather than as a substring: "supports at
    most" on its own is ordinary refusal wording that also fences pictures,
    tools and attachments. A rate limit is never one either.
    """
    if status == RATENGRENZE or not isinstance(text, str):
        return False
    klein = text.lower()
    return _hersteller_deckel(klein) is not None and not _eingabe_genannt(klein)


def bei_fehler(fehler: BaseException) -> bool:
    """:func:`ist_kontext_voll` asked of a provider error.

    The body the server sent is read where there is one: the error's own
    sentence carries only the first few hundred characters of it. The
    sentence is read too, because an error raised from inside a stream has
    no body at all.
    """
    rohtext = getattr(fehler, "rohtext", None) or ""
    return ist_kontext_voll(getattr(fehler, "status", None), f"{fehler} {rohtext}")


def output_cap_error(fehler: BaseException) -> bool:
    """:func:`is_output_cap` asked of a provider error, read the way
    :func:`bei_fehler` reads one."""
    rohtext = getattr(fehler, "rohtext", None) or ""
    return is_output_cap(getattr(fehler, "status", None), f"{fehler} {rohtext}")


# Refusals that name the window, the input and the answer's share, each as
# an exact count. Read as (window, input, answer); a pattern whose input
# comes in two parts has both added up.
#
# * vLLM, current: "This model's maximum context length is N tokens.
#   However, you requested Z output tokens and your prompt contains Y input
#   tokens, ..." (vllm/renderers/params.py, _token_len_check). Where vLLM
#   writes "contains at least Y" it cut the prompt short while counting, and
#   Y is a floor rather than the input — that wording does not match, and
#   the refusal reads as one without numbers.
# * vLLM 0.10 to 0.12: "'max_tokens' or 'max_completion_tokens' is too
#   large: Z. This model's maximum context length is N tokens and your
#   request has Y input tokens (Z > N - Y)."
#   (vllm/entrypoints/openai/serving_engine.py, _validate_input).
# * vLLM up to 0.8 and the older OpenAI wording: "maximum context length is
#   N tokens. However, you requested T tokens (Y in the messages, Z in the
#   completion)."
# * OpenRouter: "maximum context length is N tokens. However, you requested
#   about T tokens (A of text input, B of tool input, Z in the output)."
_ANTWORTANTEIL = (
    (
        re.compile(
            r"maximum context length is (\d+) tokens\.\s*however, you requested (\d+) output "
            r"tokens and your prompt contains (\d+) input tokens"
        ),
        lambda t: (t[1], t[3], t[2]),
    ),
    (
        re.compile(
            r"is too large: (\d+)\.\s*this model's maximum context length is (\d+) tokens and "
            r"your request has (\d+) input tokens"
        ),
        lambda t: (t[2], t[3], t[1]),
    ),
    (
        re.compile(
            r"maximum context length is (\d+) tokens.*?\((\d+) in the messages,\s*(\d+) in the "
            r"completion\)",
            re.DOTALL,
        ),
        lambda t: (t[1], t[2], t[3]),
    ),
    (
        re.compile(
            r"maximum context length is (\d+) tokens.*?\((\d+) of text input,\s*(\d+) of tool "
            r"input,\s*(\d+) in the output\)",
            re.DOTALL,
        ),
        lambda t: (t[1], t[2] + t[3], t[4]),
    ),
)


# The provider's own window alone, read out of wordings that never carry
# the input/answer breakdown _ANTWORTANTEIL needs — llama.cpp's and oMLX's
# own checks answer with the window and nothing else.
#
# * llama.cpp: "request (755 tokens) exceeds the available context size
#   (256 tokens), try increasing it" — n_ctx, named as such.
# * oMLX: "Prompt too long: 300000 tokens exceeds max context window of
#   262144 tokens".
# * OpenAI/vLLM wordings all start "... maximum context length is N
#   tokens", with or without the rest _ANTWORTANTEIL reads.
_FENSTER_MUSTER = (
    re.compile(r"exceeds the available context size \((\d+) tokens\)"),
    re.compile(r"max context window of (\d+) tokens"),
    re.compile(r"maximum context length is (\d+) tokens"),
    # vLLM, where the ceiling alone is refused against the window:
    # "max_tokens=70000 cannot be greater than max_model_len=65536".
    re.compile(r"max_model_len=(\d+)"),
)


# vLLM's further forms:
# "max_model_len (32768)", "max_model_len: 32768", "max_model_len is 32768",
# "maximum model length 131072". The first one also reads the responses
# route's own refusal, "The engine prompt length 40000 exceeds the
# max_model_len 32768. Please reduce prompt." A number is taken only where
# it is a plausible window at all (``_VLLM_WINDOW_RANGE``); "is longer than
# the maximum model length of 8192" carries no number either reads.
_VLLM_WINDOW_PATTERNS = (
    # The name, then optionally "is" and one of ":", "=", "(", then a
    # number of four digits or more.
    re.compile(r"max_model_len(?:\s+is)?\s*[:=(]?\s*(\d{4,})"),
    re.compile(r"maximum model length(?:\s+is)?\s*[:=(]?\s*(\d{4,})"),
)
_VLLM_WINDOW_RANGE = (1024, 10_000_000)


# Refusals whose own words name the INPUT as what did not fit: the prompt or
# the request reaching past the window — never the answer's ceiling. These
# fold, whatever answer length somebody set: the ceiling can be as large as
# the whole window and the input would still be the thing that overran, so
# the rule that a set ceiling filling the window cannot be folded away (see
# :func:`_falten_oder_zu_gross`) does not speak about them at all.
#
# * Anthropic: "prompt is too long: 1000500 tokens > 1000000 maximum".
# * oMLX: "Prompt too long: 300000 tokens exceeds max context window of
#   262144 tokens".
# * llama.cpp: "request (755 tokens) exceeds the available context size
#   (256 tokens), try increasing it".
# * OpenAI, older: "However, your messages resulted in 4239 tokens. Please
#   reduce the length of the messages."
# * "input is too long" — the same family, met on other servers.
# * vLLM, responses route: "The engine prompt length 40000 exceeds the
#   max_model_len 32768. Please reduce prompt." — matched as this one
#   sentence rather than by "prompt length" alone, so another refusal that
#   merely mentions a prompt length is not taken for it.
# * vLLM, its own prompt check, for the decoder and the encoder prompt
#   alike: "The decoder prompt (length 9000) is longer than the maximum
#   model length of 8192." Its second form, "... plus the number of
#   requested output tokens (at least 1) is longer than ...", names the
#   answer beside the input and is left to the numbers.
#
# Where the INPUT is named, the output cap is not the diagnosis. Three
# broader phrases are deliberately NOT taken — "input token", "prompt
# contains" and "reduce the length" also stand in refusals that name the ceiling in the same breath
# (vLLM's "you requested 8192 output tokens and your prompt contains at
# least 1 input tokens … reduce the length of the input prompt or the number
# of requested output tokens"), and those keep the answer they were given:
# the numbers decide there, not a word.
#
# What is NOT in here counts as much: a refusal that only says "too many
# tokens for this model" names neither the input nor the ceiling, and it
# keeps the answer it has always had.
#
# This list is asked twice of every refusal: whether it is a full context at
# all (:func:`ist_kontext_voll`, which lets the callers reach the folding at
# all) and which way it is answered (:func:`abhilfe`, where it is asked
# first). Both go through :func:`_eingabe_genannt`, so no wording stands in
# two lists and none has to be carried over by hand.
_EINGABE_GENANNT = (
    re.compile(r"prompt (?:is )?too long"),
    re.compile(r"input is too long"),
    re.compile(r"your messages resulted in"),
    re.compile(r"exceeds the available context size"),
    re.compile(r"engine prompt length \d+ exceeds"),
    re.compile(r"prompt \(length \d+\) is longer than"),
)


# Refusals that name the answer's ceiling EXPLICITLY, together with the
# window and the input. Read as (window, input, answer), like _ANTWORTANTEIL
# — but answered differently: a refusal that quotes the ceiling we sent is
# saying that ceiling is what did not fit, so lowering it is the fix even
# where it is smaller than the whole window. _ANTWORTANTEIL's "the ceiling
# alone fills the window" test would read both of these as an input problem
# and fold a history that folding cannot save.
#
# Both wordings are Anthropic's. The first is its answer when the ceiling
# does not fit beside the input; the second appears wherever a long input
# meets a large ceiling on the same API.
_GENANNTER_DECKEL = (
    (
        re.compile(
            r"max_tokens:\s*(\d+)\s*>\s*context_window:\s*(\d+)\s*-\s*input_tokens:\s*(\d+)"
        ),
        lambda t: (t[2], t[3], t[1]),
    ),
    (
        re.compile(
            r"input length and max_tokens exceed context limit:\s*(\d+)\s*\+\s*(\d+)\s*>\s*(\d+)"
        ),
        lambda t: (t[3], t[1], t[2]),
    ),
)


# A refusal that names the ceiling the model ALLOWS, rather than the window
# it did not fit into. Nothing about the input is said here and nothing needs
# to be: the number is the answer's own limit for this model, so this
# request and its retry are built with it — and no further one: it belongs to
# the request it was read for (``app/antwortgrenze.py``).
#
# * OpenAI: "supports at most N completion tokens" — a wording its own
#   documentation does not carry: the error codes guide names a single 400
#   and neither the chat-completions reference nor the completions guide
#   quotes a text for this case. What is quoted is what users report from
#   the live API in OpenAI's own developer forum.
# * DashScope: "Range of max_tokens should be [1, N]" — the upper bound of
#   the range is the limit — and "exceeds model's maximum output tokens
#   (N)".
#
# A pattern that never matches costs nothing; where one does match, the
# request is lowered instead of failing. One list, read by every question
# asked of a stated limit — whether a refusal is a full context at all,
# which way it is answered, and what the request's own holder learns — so a
# wording cannot be known in one of them and missing in another.
_HERSTELLER_DECKEL = (
    re.compile(r"supports at most (\d+) completion tokens"),
    re.compile(r"range of max_tokens should be\s*\[\s*\d+\s*,\s*(\d+)\s*\]"),
    re.compile(r"exceeds model(?:'s)? maximum output tokens\s*\(?\s*(\d+)\s*\)?"),
)


def _hersteller_deckel(klein: str) -> int | None:
    """The output limit these lowercased words state for the model, or
    ``None`` where none of ``_HERSTELLER_DECKEL``'s wordings is in them."""
    for muster in _HERSTELLER_DECKEL:
        treffer = muster.search(klein)
        if treffer:
            return int(treffer.group(1))
    return None


def hersteller_deckel_aus_fehler(fehler: BaseException) -> int | None:
    """The output limit a refusal names for this model, or ``None``.

    Independent of :func:`abhilfe`: that one fixes the single request that
    failed, this number is read into the request that failed and stays with
    it — the next request starts over from the model list
    (``app/antwortgrenze.py``).
    """
    return _read_refusal(fehler, _hersteller_deckel)


def grenze_aus_fehler(fehler: BaseException) -> int | None:
    """The provider's own context window, read out of a "too long" refusal
    — or ``None`` where the wording is not one measured here.

    Independent of :func:`abhilfe`: that one needs the window AND the input
    AND the answer's share to fix the one request that failed. Remembering
    the window for every request after this one needs only the window
    itself, which is all most of these wordings ever carry.

    The wordings measured here (``_FENSTER_MUSTER``) are asked first, then
    vLLM's further forms (``_VLLM_WINDOW_PATTERNS``). Of those, only each
    pattern's first match counts — a match needs at least four digits, so a
    shorter number after the same words is skipped rather than matched.
    Where the number of that first match is not a plausible window
    (``_VLLM_WINDOW_RANGE``), that pattern yields nothing and the next one
    is asked. The body the server sent is searched before the error's own
    sentence, which carries only a cut-off start of it (:func:`_read_refusal`).
    Whether the number read is then taken is not decided here: the reader
    that remembers it takes only a window smaller than the one in force
    (:func:`app.fenstergroesse.aus_fehler_lernen`).
    """
    return _read_refusal(fehler, _window_in)


def _read_refusal(fehler: BaseException, reader):
    """What ``reader`` finds in a provider error, asked of the body the
    server sent first and of the error's own sentence second — or ``None``.

    The order is the point: the sentence carries only the start of the body
    (``app/providers/openai_kompatibel.py``, the first 400 characters), and
    a number cut in half at its end would be read as a different, smaller
    one. ``reader`` takes one lowercased text and answers with something
    falsy where it finds nothing there.
    """
    rohtext = getattr(fehler, "rohtext", None) or ""
    for text in (rohtext, str(fehler)):
        found = reader(text.lower()) if text else None
        if found:
            return found
    return None


def _window_in(lowered: str) -> int | None:
    """The window one lowercased text names, by the order
    :func:`grenze_aus_fehler` describes, or ``None``."""
    for muster in _FENSTER_MUSTER:
        treffer = muster.search(lowered)
        if treffer:
            return int(treffer.group(1))
    lowest, highest = _VLLM_WINDOW_RANGE
    for pattern in _VLLM_WINDOW_PATTERNS:
        match = pattern.search(lowered)
        if match and lowest <= int(match.group(1)) <= highest:
            return int(match.group(1))
    return None


def _eingabe_genannt(klein: str) -> bool:
    """Whether these lowercased words name the INPUT as what did not fit.

    One reading for both questions asked of the list: whether a refusal is a
    full context at all (:func:`ist_kontext_voll`, on the text alone) and
    which way it has to be answered (:func:`abhilfe`, on the error with the
    body). A wording nothing here knows is not this — an unknown refusal
    keeps the answer it has always had (``_EINGABE_GENANNT``).
    """
    return any(muster.search(klein) for muster in _EINGABE_GENANNT)


def _nennt_die_eingabe(fehler: BaseException) -> bool:
    """The same question asked of a provider error: the error's own text plus
    the body the server sent, quietly lowercased."""
    return bool(_read_refusal(fehler, _eingabe_genannt))


def _zahlen(fehler: BaseException, muster_liste) -> tuple[int, int, int] | None:
    """(window, input, answer) as the refusal counts them, or None where it
    does not name all three in one of ``muster_liste``'s wordings."""
    def read(klein: str) -> tuple[int, int, int] | None:
        for muster, ordnen in muster_liste:
            treffer = muster.search(klein)
            if treffer:
                gruppen = {nr: int(wert) for nr, wert in enumerate(treffer.groups(), start=1)}
                return ordnen(gruppen)
        return None

    return _read_refusal(fehler, read)


def _senken(fenster: int, eingabe: int) -> tuple[str, int | None]:
    """The ceiling the retry gets: the window less the input, less a small
    margin — or the card, where the input leaves nothing free at all.

    An input the refusal counts as LARGER than its window is folded instead:
    no ceiling could make that request fit, and a fold is the one cure left
    ("input length and max_tokens exceed context limit: 250000 + 8192 >
    200000", vLLM's "... your prompt contains 40000 input tokens" under a
    window of 32768). No output budget is read from such numbers: the
    history is folded and sent again until the attempts run out
    (``FALTVERSUCHE``). The card stays for an input that fits the
    window but leaves no room for an answer."""
    if eingabe > fenster:
        return FALTEN, None
    frei = fenster - eingabe - SICHERHEITSABSTAND
    if frei <= 0:
        return KARTE, None
    return GRENZE, frei


def abhilfe(
    fehler: BaseException,
    *,
    eingestellte_grenze: int | None = None,
    fenster: int | None = None,
) -> tuple[str, int | None]:
    """What makes a request the provider called too long fit.

    The refusal's own words are asked before any number is read: where they
    name the INPUT as what did not fit, the answer is ``(FALTEN, None)`` —
    whatever else the sentence carries. A refusal that quotes the ceiling
    beside the input ("prompt is too long: 250000 tokens > 200000 maximum.
    input length and max_tokens exceed context limit: 250000 + 8192 > 200000")
    is still a statement about the input, and the ceiling it quotes is not
    what overran. Answering it with a lowered ceiling — or with the card,
    where the input leaves no room for one — would send the user to a
    setting that had nothing to do with it (``_EINGABE_GENANNT``).

    Everything else is decided by the numbers the refusal names:

    * ``(GRENZE, free)``: the refusal shows the answer's ceiling to be what
      did not fit, so no fold could ever make room — and every fold is
      written down for good. The same request goes again with ``free`` as
      its ceiling. Three ways to get there: the model's own stated output
      limit, a refusal that quotes the ceiling we sent beside the window and
      the input, or the ceiling alone reaching the window.
    * ``(KARTE, None)``: the same, but the input leaves nothing free for an
      answer at all. An input the numbers show past the window itself is
      folded instead (``_senken``).
    * ``(LIMIT_TOO_LARGE, None)``: an answer length somebody SET reaches the
      window on its own — and the refusal did not name the input as what
      overran. Both halves are needed: the numbers say the ceiling fills the
      window, they are not guessed (the window comes out of the refusal
      where it names one, otherwise it is the one the endpoint resolved),
      and a refusal that DOES name the input folds instead, whatever the
      ceiling is (``_EINGABE_GENANNT``). Under "Auto" this cannot happen: no
      number of ours travels on the OpenAI wire, and on the Anthropic wire
      Auto is never larger than the window (``app/antwortgrenze.py``).
    * ``(FALTEN, None)``: everything else — the input is what did not fit,
      or the refusal names no numbers that can be read for sure. Nothing is
      guessed from a window or ceiling known elsewhere.
    """
    if _nennt_die_eingabe(fehler):
        return FALTEN, None
    deckel = hersteller_deckel_aus_fehler(fehler)
    if deckel:
        return GRENZE, deckel
    zahlen = _zahlen(fehler, _GENANNTER_DECKEL)
    if zahlen is not None:
        return _senken(zahlen[0], zahlen[1])
    zahlen = _zahlen(fehler, _ANTWORTANTEIL)
    if zahlen is None:
        return _falten_oder_zu_gross(fehler, eingestellte_grenze, fenster)
    gemeldetes_fenster, eingabe, antwort = zahlen
    if antwort < gemeldetes_fenster:
        return _falten_oder_zu_gross(fehler, eingestellte_grenze, fenster)
    return _senken(gemeldetes_fenster, eingabe)


def _falten_oder_zu_gross(
    fehler: BaseException, eingestellte_grenze: int | None, fenster: int | None
) -> tuple[str, int | None]:
    """Folding — unless the answer length somebody SET is on its own as
    large as the window.

    Reached where no number in the refusal could be read for sure: the
    refusal says the request was too long and leaves it at that (vLLM's
    "at least Y input tokens", "max_tokens=Z cannot be greater than
    max_model_len=W"). Folding is the right cure for an input that is too
    long — but not where the ceiling ALONE already fills the window: three
    folds would cost three summaries and change nothing, and the numbers say
    so rather than guess it.

    The window comes out of the refusal where it names one, otherwise from
    what the endpoint resolved. Nothing here is halved or estimated: where
    neither is known, the answer is the one it always was.

    A refusal that names the INPUT as what did not fit never reaches this
    question: :func:`abhilfe` asks the words before it reads any number, and
    folds. "Prompt too long: 97902 tokens exceeds max context window of
    65536 tokens" is a statement about the input; the card a set ceiling
    would earn here would send the user to a setting that had nothing to do
    with it.
    """
    gemeldetes_fenster = grenze_aus_fehler(fehler) or fenster
    if (
        eingestellte_grenze
        and gemeldetes_fenster
        and eingestellte_grenze >= gemeldetes_fenster
    ):
        return LIMIT_TOO_LARGE, None
    return FALTEN, None


def mit_grenze(anfrage, grenze: int | None, zustand):
    """``anfrage`` itself, or a copy carrying ``grenze`` as its answer
    ceiling — a copy, so the lowered ceiling holds for the request it was
    worked out for and never reaches the setting or a later request.

    The thinking budget comes down with it. One provider generation asks for
    that budget in tokens and wants it below the answer's own ceiling, so a
    budget left standing from the larger ceiling would have the retry
    refused for the budget instead — and that refusal matches no wording
    read here, so nothing would retry it a second time. The round loops that
    work a ceiling out per round resolve both numbers together for exactly
    this reason (``app/api/v1/generierung.py``); a ceiling lowered here is
    the other way the number can change, and it does the same.

    ``zustand`` is here for one word: where the lowered ceiling leaves no
    room to think at all, the request goes out with thinking switched OFF,
    and which word means off is the model's to say, not this module's.
    It is the only thing read out of it.
    """
    # Imported here rather than at the top: this module is read by the one
    # that estimates a request's input (``app/antwortgrenze.py``), which the
    # thinking switch's own neighbours read in turn, and a module-level line
    # closes that ring.
    from app import denkschalter

    if grenze is None:
        return anfrage
    return dataclasses.replace(
        anfrage,
        max_tokens=grenze,
        zusatz=denkschalter.mit_deckel(
            anfrage.zusatz or {},
            grenze,
            denkschalter.aus_wort(zustand, modell=anfrage.modell),
        ),
    )


def faltbudget(grundbudget: int, faltung: int) -> int:
    """The verbatim tail for the ``faltung``-th forced fold (1, 2, 3): the
    ordinary budget first, then half of it, then a quarter — each attempt
    folds more of the history than the one that did not fit."""
    return max(1, grundbudget >> max(0, faltung - 1))
