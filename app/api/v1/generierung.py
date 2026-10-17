"""Streaming proxy and cancellation.

Flow of a request:

  1. Save the user message (if one comes along).
  2. Fetch the history from the database, prepend the system prompt.
  3. Stream from the chosen provider and pass every chunk on immediately.
  4. At the end, save the complete answer including reasoning and metrics
     and publish ``model_response_finished``.

If cancelled, step 4 still applies — the text produced up to that point is
not lost but saved with the ``abgebrochen`` marker. So there are no empty
gray bubbles.

The stream is Server-Sent Events. Each event is one line of JSON with a
``typ`` field: ``start``, ``content``, ``reasoning``, ``tool_confirm``,
``tool_call``, ``tool_result``, ``stats``, ``error``, ``done``.

Tools listed under ``needs_confirmation`` are not simply executed: the
stream sends ``tool_confirm`` and pauses until a decision comes in via
``/api/v1/chat/confirm``. If nobody answers, after ``BESTAETIGUNG_WARTEZEIT``
seconds the rejection applies — silence must never lead to execution.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from pathlib import Path
from typing import Any, AsyncGenerator, AsyncIterator
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.api.abhaengigkeiten import hole_benutzer_id, hole_config, hole_repositories, hole_sprache
from app.config import Config
from app.api.v1.schemas import (
    AbbruchAnfrage,
    AbbruchAntwort,
    BestaetigungAnfrage,
    BestaetigungAntwort,
    GenerierungAnfrage,
    NachrichtAntwort,
)
from app.db import Repositories
from app.db.models import Chat
from app.db.repositories.messages import ist_dienstbericht
from app.discovery import Discovery
from app.events import Ereignisse, bus
from app.generationen import Generierung, Generierungsverwaltung
from app.answer_sections import SectionLog
from app import answer_redo, answer_replay, replay_as_question
from app.cache_over_rounds import cache_over_rounds
from app.own_folder_line import with_own_folder_last
from app.tempo_without_text import without_tempo
from app.i18n import t
from app import ablehnungslernen, antwortende, antwortgrenze, denkablehnung, denkschalter, sent_stage
from app import denkenwahl, denkstufen
from app import reasoning
from app import helper, parameter
from app.speicherorte import ort
from app.providers import ChatNachricht, Generierungsanfrage, ProviderFehler, openai_responses
from app.providers.anthropic import THINKING_BLOCKS
# The two floors a speed has to clear before it means anything — the
# smallest number of tokens it may be computed from, and the shortest
# stretch of time it may be divided by. Shared rather than repeated: the
# division happens here as well as per round, and a floor written on one
# side is a floor the other side lifts again.
from app.providers.openai_kompatibel import (
    KLEINSTE_MESSBARE_MENGE,
    KLEINSTE_MESSBARE_ZEIT,
    display_model,
)
from app.tools import WerkzeugRegistry, WerkzeugVerboten
from app.tools import auftrag_werkzeug, bild_werkzeug, dateiwerkzeuge, frage_werkzeug, memory
from app.tools import video_tool, ziel_werkzeug
from app.tools import agentendock as delivery_tool
from app.tools import hintergrund, shell, skill
from app.tools import datei_aendern, datei_schreiben, grenzen
from app.agenten import agenten_laden
from app.discovery import denklaenge_erlaubt, refusal_key
from app import anrede, diktatsprachewahl, dokumentablage, gedaechtnis, grundprompt, ordnerwissen
from app import round_end, stop_note, task_images, werkzeugvorpruefung
from app import skills, skillwahl, tokenmass, werkzeugwahl
from app import (
    befehlszeitwahl,
    chatverdichtung,
    faltpause,
    kontextdruck,
    kontextverbrauch,
    kontextvoll,
    verdichtung,
    verdichtungswahl,
    werkzeugbild,
    werkzeugkuerzung,
    werkzeugrundenwahl,
)
from app import aufgaben, dokumentbudget, dokumentcache
from app import verlaufsbau
from app.verlaufsbau import _verlauf_bauen, on_users_side, werkzeuggewicht, zeilentext
from app import hintergrundmeldung, hintergrundwecken
from app import immererlauben

log = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["generierung"])

# How often the model may request tools within one answer is no longer a
# constant here — it is a setting (app/werkzeugrundenwahl.py), resolved per run
# from the cascade so a task across many files is not cut off after ten rounds.

# How much of a tool result travels into the stream, the stored message AND
# the model's own copy. Cut ONCE, where the result is handed over — the log,
# the live request and the row carry the same text, so a later request
# rebuilds the run exactly as it went out (app/verlaufsbau.py). Matches the shell tool's own ceiling
# (app/tools/shell.py, `_kuerzen`, which counts its exit note into the same
# figure) and the history cap this feeds into.
WERKZEUGERGEBNIS_GRENZE = 20_000


def _modellfassung(anzeige: str, modell: str) -> dict[str, str]:
    """The model's copy for a stored tool result — but only where it differs.

    A stored tool entry carries the sentence the window shows, and
    ``app/verlaufsbau.py`` falls back to it for the model. Where both are the
    same string — every tool whose text is English anyway — a second copy of
    the same 20 KB in every row buys nothing. Where they DO differ (the
    refusal of a call, whose sentence the window reads in its own language),
    the row has to name the model's copy: a later request of this chat
    rebuilds the turn from this entry.

    Handed over as it is: the caller has cut once already, at the ceiling
    above (``WERKZEUGERGEBNIS_GRENZE``), and a second cut here would be the
    very second length this entry must not have.
    """
    if modell == anzeige:
        return {}
    return {"ergebnis_modell": modell}

# How often a running answer writes its state so far into the database.
# Coarse on purpose: a round takes 45–90 s, so one write every few seconds
# costs nothing, while a hundred-millisecond beat would write the same
# growing text hundreds of times for the same benefit.
ZWISCHENSTAND_TAKT = 3.0

# The tools whose work goes into the answer a chat is writing: a drawn
# picture or video joins that answer's run, a delivered file hangs on its
# row. Each is handed the answer's id (`_werkzeug_ausfuehren`).
ANSWER_TOOLS = video_tool.DRAWING_TOOLS | {delivery_tool.WERKZEUG_NAME}


# From the best to the weakest origin of the speed figure. Across several
# rounds the weakest one applies: one round without a server measurement
# makes the total inaccurate, and the figure should admit that too.
#
# Three entries and no more, because these three are the whole of what
# `tempo_ermitteln` can answer — and every provider goes through it, the
# Anthropic route included since it stopped doing its own arithmetic. A
# vendor's name has no place in this table even when a provider emits one:
# the ranking is about how a number was ARRIVED at, and "anthropic" says
# nothing about that, so there is no rank it could honestly be given. The
# `.get(q, 9)` below stays as the guard for a value that should not exist —
# `max` picks the largest rank, so anything unknown drags the whole run
# down to "weakest", which is the safe direction for a thing nobody
# planned.
_QUELLEN_RANG = {"server": 0, "gemessen": 1, "geschaetzt": 2}


def _restore_environment_block_on_rows(
    repositories, zeilen: list, block: str
) -> bool:
    """Hands the block to the newest row of ``zeilen`` that is the user
    speaking — where no such row among them carries one yet.

    The request route asks this before an answer goes out: a turn that would
    otherwise leave the whole request reading no day at all gets the block,
    and the first message of a chat, the first of a new day and the first
    after a fold that swallowed the last one all fall out of that one
    question. A fold in the middle of an answer asks the very same thing
    again for the rows it rebuilds the request from — the row that carried
    the block is
    not the newest one any more once the answer has run, and a fold pins only
    the newest row, so it can take the only reading of today out of the
    history for the rest of that answer (app/grundprompt.restore_environment_block).

    Written onto the row and not merely into the request: the next request is
    built from the rows, and a block that only ever stood in one request
    would move to another row there — one row in the middle of the history
    handed back differently, and the server reads a request again from the
    first byte that differs, everything behind that row with it.

    What counts as carrying it is the whole block, date AND zone and not the
    date alone: a row of the former clock SENTENCE names a minute in the
    user's own voice — exactly what this block replaced — and a row from
    before a timezone change names the old zone, from which "in ten minutes"
    would be computed hours off. Both must count as "this request does not
    carry today's surroundings".

    Empty-handed where any row already carries it: a second block in one
    request would say the same thing twice. Returns whether a row was given
    one.
    """
    # Every row, not only the ones the block may go on: a row that somehow
    # carries it — and a message the service wrote can quote it like any
    # other text — is enough to make a second one say the same thing twice.
    if any(
        block in str((row.stats or {}).get("clock_sentence") or "") for row in zeilen
    ):
        return False
    row = next((r for r in reversed(zeilen) if on_users_side(r)), None)
    if row is None:
        return False
    repositories.messages.set_clock_sentence(row.id, block)
    # The rows handed in were read before this write and do not carry it yet,
    # so the row's own object is brought in line by hand. The alternative —
    # reading the history a second time — would cost every request a second
    # full read of itself, and the request that went out would not be the one
    # this decision was made for.
    row.stats["clock_sentence"] = block
    return True


def _block_went_back(chat) -> None:
    """One line in the protocol when a fold took the turn that carried the
    block and it had to go back in.

    Written where the repair happens rather than inside the two places that
    do it, so a chat's record shows the same sentence whichever fold took the
    turn — and shows it at all: without it the request that goes out after
    such a fold differs from every request before it, and nothing in the
    record would say why.
    """
    log.info(
        "Chat %s: a fold took the turn that carried the block, the newest user "
        "turn takes it over",
        chat.id,
    )


def _runde_im_protokoll(
    protokoll: list[dict],
    runde: int,
    text: list[str],
    denkteile: list[dict] | None = None,
    textteile: list[dict] | None = None,
    blocks: list[dict] | None = None,
) -> dict:
    """What a later request needs to rebuild this call's round as it went
    out (``app/verlaufsbau.py``, ``_werkzeugzuege``): the number of the
    round it belongs to, and — once, on the round's first call — the text
    the round produced. The server's own call id travels beside them.

    On the Responses wire a round carries more than its text: the encrypted
    thinking and the text parts with their ``phase`` go back out with it
    (``app/providers/openai_responses.py``), and a rebuilt round without
    them differs from the run exactly there — a server that has no record
    of its own thinking answers as if it had never thought, and the model
    does the work again. Left out where the round carried none: the chat
    route never has any, and two empty lists beside every call would name
    nothing.

    The same holds on Anthropic's wire for a round that thought: its content
    blocks (the thinking blocks whole, the rest as markers of their place)
    are stored beside the text, under ``blocks``, so that a failed answer
    asked again hands them back as the API wants them within a tool turn
    (``app/verlaufsbau.py``, ``app/providers/anthropic.py``). Left out where
    the round did not think.

    Stored with the call rather than in a place of its own: the tool log is
    the row's record of the run, and a second list beside it would have to
    be kept in step with this one for no gain.
    """
    kennung: dict = {"runde": runde}
    if not protokoll or protokoll[-1].get("runde") != runde:
        kennung["text"] = "".join(text)
        if denkteile:
            kennung["denkteile"] = denkteile
        if textteile:
            kennung["textteile"] = textteile
        if blocks:
            kennung["blocks"] = blocks
    return kennung


def _messwerte_mergen(alt: dict | None, neu: dict, wrote_text: bool = True) -> dict:
    """Sum metrics across tool rounds.

    Each round delivers its own numbers — until now the last one simply won,
    and a run of two and a half minutes showed up as "23 s" in the bubble.
    Duration and chunks are added up, the speed is
    recalculated from the totals; the first token counts from the first round.

    For the speed, tokens and **generation time** are summed separately and
    only divided afterwards. The waiting time between rounds —
    tool execution and processing of the grown prompt — is thus included in
    the total duration but not in the speed. That is exactly how llama.cpp
    and mlx separate it too.

    Separately, but as a PAIR: only the tokens of a round that also brought
    a generation time go into the speed's numerator. See ``tempo_tokens``
    below — summing the two fields independently was its own defect.

    A round that wrote no answer text (``wrote_text`` False: it only called a
    tool) is no part of the speed at all — see ``without_tempo``. The cache
    share is the cached tokens over all tokens read, over every round
    (``cache_over_rounds``); the waiting time stays the first round's.
    """
    if not wrote_text:
        neu = without_tempo(neu)
    if not alt:
        return neu
    dauer = round((alt.get("dauer_sekunden") or 0) + (neu.get("dauer_sekunden") or 0), 3)
    haeppchen = (alt.get("haeppchen") or 0) + (neu.get("haeppchen") or 0)
    tokens = (alt.get("erzeugte_tokens") or 0) + (neu.get("erzeugte_tokens") or 0)
    erzeugungszeit = round(
        (alt.get("erzeugungs_sekunden") or 0) + (neu.get("erzeugungs_sekunden") or 0), 3
    )
    # The tokens the SPEED is made of, which is not every token produced.
    #
    # A round whose generation time rounded away to nothing still reports
    # its count — the count is true and the window shows it — but it has no
    # seconds to put under it, and the sum above adds none for it. Adding
    # the two fields independently therefore carried those tokens into the
    # numerator while their time stayed out of the denominator: measured,
    # three rounds of one token with the time of two of them rounded away
    # came out at 1500 tok/s, though each of the three on its own had
    # reported no speed at all. It grows with the round, not with the
    # defect: two silent rounds of forty tokens beside one measured round of
    # forty read as 60 tok/s where the truth is 20.
    #
    # Carried in the result because only the running total knows which
    # rounds had a divisor. Where it is missing — the raw stats of the very
    # first round, which comes through the early return above untouched —
    # the pairing is still readable off the round itself.
    #
    # And the fallback reads the tier as well. A round whose count is CHUNKS
    # (`tempo_quelle` "geschaetzt") has no tokens to contribute: chunks in
    # the numerator over real seconds in the denominator is the eightfold
    # error rebuilt one layer up — measured, two such rounds
    # added up to 8.08 tok/s while each of them on its own reported none.
    #
    # Both halves at once, for the same reason: the seconds of a round whose
    # tokens were dropped stayed in the divisor by themselves, and a silent
    # chunk round of 19.3 s beside a real one of 0.634 s reported 2.56 tok/s
    # for an answer that ran at 78.85. What is not counted is not timed.
    def _zaehlbar(runde: dict) -> tuple[int, float]:
        # The fields themselves where they exist — their absence is what
        # marks the older shape, and `None` in them is an ANSWER: this round
        # counted no tokens. Reading them with `.get()` treated the two the
        # same and let a chunk count back in through the fallback below.
        if "tempo_tokens" in runde:
            return (
                runde["tempo_tokens"] or 0,
                (runde.get("tempo_sekunden") or 0)
                if runde["tempo_tokens"]
                else 0,
            )
        if runde.get("tempo_quelle") == "geschaetzt":
            return 0, 0
        if not runde.get("erzeugungs_sekunden"):
            return 0, 0
        return runde.get("erzeugte_tokens") or 0, runde["erzeugungs_sekunden"]

    alt_tempo_tokens, alt_tempo_zeit = _zaehlbar(alt)
    neu_tempo_tokens, neu_tempo_zeit = _zaehlbar(neu)
    tempo_tokens = (alt_tempo_tokens or 0) + (neu_tempo_tokens or 0)
    tempo_zeit = round((alt_tempo_zeit or 0) + (neu_tempo_zeit or 0), 3)
    # Whose reading the sum is, which is only the rounds that are IN it: a
    # round contributing no tokens has no say in what the figure counts, and
    # letting it speak anyway put "counted chunks" on a figure divided
    # entirely out of a server's own pair — and the display drops that name
    # on sight. Where no round contributed, every name is kept: then there
    # is no figure and the field only says how far this answer got.
    beitragende = [
        q
        for q, beitrag in (
            (alt.get("tempo_quelle"), alt_tempo_tokens),
            (neu.get("tempo_quelle"), neu_tempo_tokens),
        )
        if q and beitrag
    ]
    quellen = [q for q in (alt.get("tempo_quelle"), neu.get("tempo_quelle")) if q]
    # Only a round that actually PUT TOKENS into the sum may lift the floors
    # off it. A round whose server merely stated a rate has nothing in this
    # numerator, and letting its name free the sum let a one-token round
    # beside it report 1000 tok/s — the very number the floors exist for.
    ohne_grenzen = bool(
        (alt.get("tempo_quelle") == "server" and alt_tempo_tokens)
        or (neu.get("tempo_quelle") == "server" and neu_tempo_tokens)
    )
    summen_tempo = (
        round(tempo_tokens / tempo_zeit, 2)
        if tempo_zeit
        and tempo_tokens
        and (
            ohne_grenzen
            or (
                tempo_tokens >= KLEINSTE_MESSBARE_MENGE
                and tempo_zeit >= KLEINSTE_MESSBARE_ZEIT
            )
        )
        else None
    )
    # Nothing to sum, but the last round's server said a number outright:
    # that one is kept rather than dropped — it was counted and timed at the
    # source, and no arithmetic here can improve on it.
    genannte = (
        neu.get("tokens_pro_sekunde") if neu.get("tempo_quelle") == "server" else None
    )
    rang = beitragende or quellen
    schwaechste = max(rang, key=lambda q: _QUELLEN_RANG.get(q, 9)) if rang else None
    if summen_tempo is not None:
        tempo_wert, tempo_quelle = summen_tempo, schwaechste
    elif genannte:
        tempo_wert, tempo_quelle = genannte, "server"
    else:
        tempo_wert, tempo_quelle = None, schwaechste
    return {
        **neu,
        **cache_over_rounds(alt, neu),
        "dauer_sekunden": dauer,
        "haeppchen": haeppchen,
        "erzeugte_tokens": tokens or None,
        "erzeugungs_sekunden": erzeugungszeit or None,
        "tempo_tokens": tempo_tokens or None,
        "tempo_sekunden": tempo_zeit or None,
        # The same two floors the single round applies, applied again over
        # the sum. Without them the merge lifts them right back off: an
        # answer whose first round was a bare tool call and whose second
        # wrote one chunk came out at 1000 tok/s again — the very number the
        # floors exist for.
        #
        # The token floor alone was not enough, and could not be: measured,
        # three rounds of one token each add up to three tokens over three
        # milliseconds, clear a count of three, and report the same 1000.
        # Every one of those rounds was individually judged unmeasurable and
        # the sum let them back in — because what makes the number absurd is
        # the tiny DIVISOR, and no count of tokens says anything about that.
        #
        # Neither floor for a reading the SERVER measured: that one is a
        # fact however few tokens and however few milliseconds it counts.
        "tokens_pro_sekunde": tempo_wert,
        # The name belongs to the NUMBER, not to the answer: a summed
        # reading is as good as its weakest round (the worst rank wins,
        # which is what `max` picks here), while a rate the server stated
        # outright is a server reading whatever else the answer contains.
        # Anything else puts "measured over the answer" on a figure that
        # timed the thinking too, which is the very mix-up this guards
        # against.
        "tempo_quelle": tempo_quelle,
        "erstes_token_nach_sekunden": alt.get("erstes_token_nach_sekunden")
        or neu.get("erstes_token_nach_sekunden"),
    }


def _kontextstand(daten: dict, letzter_stand: int | None) -> int | None:
    """How full the context is right now, from one provider reading.

    Prompt of this round plus what this round has written so far — and
    explicitly NOT a sum over rounds, unlike the metrics above. The prompt
    of round N already carries every round before it and every tool result
    in between, so each round reports the whole standing on its own; adding
    them would count the same tokens once per round.

    Three cases, and which one applies is the provider's word, not a guess
    made here:

      * The provider counted the prompt and counted it whole
        (``prompt_genau``): Anthropic's ``input_tokens``, a server's own
        ``usage``. Used as it stands, raised by nothing — a chat that was
        just compacted has a SMALLER prompt than the reading before it, and
        anything that only ever grows would keep showing the old number.
      * The provider has a floor, or nothing at all. **Then this is an
        ESTIMATE.** ``letzter_stand`` — the last reading known before this
        round — stands in for the prompt, because the new prompt is the old
        total plus whatever the tool result added. ``timings.prompt_n`` from
        llama.cpp/mlx is a floor of the same kind seen from the other side:
        it counts only what was not already in the cache (measured, see
        ``openai_kompatibel.py``: 524 instead of 1501 with 977 cached). Both
        are lower bounds on the same number, so the larger of the two is the
        better one. The two are weak in opposite situations, which is why
        they are used together: on the first request of a chat the cache is
        cold and ``prompt_n`` is complete, and by the time the cache makes it
        short there is a previous total to raise it with.
      * Neither half is known — ``None``. The first round of a fresh chat on
        a server that reports no prompt is exactly that, and a count of the
        output alone is not a context reading.

    Every estimate is replaced by the server's own count when the round
    ends; see where the ``stats`` chunk is handled.
    """
    erzeugt = daten.get("erzeugte_tokens") or 0
    prompt = daten.get("prompt_tokens")
    if daten.get("prompt_genau") and prompt:
        return int(prompt) + erzeugt
    untergrenzen = [w for w in (prompt, letzter_stand) if w]
    if not untergrenzen:
        return None
    return max(int(w) for w in untergrenzen) + erzeugt


def _ganzer_stand(daten: dict) -> int | None:
    """The round's own reading — but only where it is genuinely WHOLE.

    ``kontextverbrauch.tokens_aus_messwerten`` deliberately adds up a single
    half when that is all a server sent: as the per-round display of a job
    it is better to show one side than nothing. As an ABSOLUTE context
    standing it is wrong, and quietly so — a round reporting
    ``{"completion_tokens": 120}`` and nothing else turns a context of
    12,000 into 120, and that number then becomes the column, the event, and
    the estimate the next round builds on.

    So the halves are required here, and where they are missing the caller
    falls back to the estimate, which at least knows it is one.

    Read with ``kontextverbrauch.als_zahl``, the same reading the helper
    applies — not with ``is None``. A gate that only asked "is the field
    there" let a half that was there but unusable through: a proxy that
    sends ``"prompt_tokens": "1500"`` passed it, the helper then dropped the
    string and added up the other half alone, and the one-sided number this
    function exists to refuse became the column after all.
    """
    gesamt = kontextverbrauch.als_zahl(daten.get("gesamt_tokens"))
    if gesamt is not None:
        return gesamt
    nutzung = daten.get("nutzung")
    if not isinstance(nutzung, dict):
        return None
    gesamt = kontextverbrauch.als_zahl(nutzung.get("total_tokens"))
    if gesamt is not None:
        return gesamt
    # Both halves, or nothing. One of them is not a standing.
    eingang = kontextverbrauch.als_zahl(nutzung.get("prompt_tokens"))
    ausgang = kontextverbrauch.als_zahl(nutzung.get("completion_tokens"))
    if eingang is None or ausgang is None:
        return None
    return eingang + ausgang


# How long to wait for the user's answer before the confirmation prompt
# counts as rejected. Generous: they may not be sitting in front of it. In
# between, we check at intervals whether anyone is still listening at all.
BESTAETIGUNG_WARTEZEIT = 300.0
BESTAETIGUNG_PRUEFTAKT = 0.5


def _display_name(registry: Any, name: str) -> str:
    """The name a window and a transcript show for a call: what the server
    calls its tool (the server stands beside it), any other tool as it is
    called. The model-facing name stays the one the gates and the history
    read."""
    display_name = getattr(registry, "display_name", None)
    return display_name(name) if display_name is not None else name


async def _werkzeug_ausfuehren(
    registry: WerkzeugRegistry | None, aufruf, sprache: str, bild_senke=None,
    ordner: list[str] | None = None, chat_id: str | None = None,
    herkunft: str = "chat", agent=None, shell_zeitgrenze: int | None = None,
    cronjob_id: str | None = None, ziel_gemeldet: bool = False, modellbild=None,
    gedaechtnis_zeigen: bool = False, rules_of: str | None = None,
    antwort_id: str | None = None, abbruch: asyncio.Event | None = None,
) -> tuple[str, bool, bool, bool]:
    """Executes a tool. Returns (result text, failed, rejected).

    Errors are not raised but returned to the model as text — it should get
    the chance to handle them or tell the user about them.

    The confirmation requirement is no longer an issue here: that has been
    decided before this function is even called. Tor 3 (see
    ``app/berechtigungen.py``) still runs inside ``ausfuehren`` regardless —
    a ``nein`` surfaces as ``WerkzeugVerboten``, caught below like any other
    refusal.

    ``ordner`` are the chat's shared working folders — the shell tool runs in
    them. They come from the chat row, never from the model's arguments.

    ``herkunft``/``agent`` say who is asking — a job passes its own
    ``Agent`` and ``herkunft="agent"``; a chat leaves both at their default.

    ``shell_zeitgrenze`` is the command time limit that applies to this run
    (app/befehlszeitwahl.py) — resolved once by the caller, read only by the
    shell tool.

    ``cronjob_id`` is the schedule entry that fired this run —
    read only by ``cron_note``, and left out by a chat, which has no entry a
    note could belong to.

    ``ziel_gemeldet`` is whether a goal report already went out in this run
    — read only by ``goal``, which refuses a second
    one rather than announcing the same finding again.

    ``modellbild`` takes (file name, data URL) for a picture the model is to
    LOOK at — ``read_file`` on an image is the one caller. A run whose model
    cannot see images leaves it out, and the tool then says so rather than
    handing back a description of something nobody looked at.

    ``gedaechtnis_zeigen`` is whether the memory travels to this run's model
    — ``memory_save`` shows its entries only then (app/tools/memory.py).

    ``rules_of`` is whose mode and rules judge the call where not
    ``herkunft``'s own — ``"chat"`` for an agent the chat model sent off
    (``WerkzeugRegistry.ausfuehren``).

    ``antwort_id`` is the answer a chat is writing, handed only to the
    tools that put something into it: the painters, whose pictures join
    that answer's run in the chat, and ``deliver_file``, whose file hangs
    on it.

    ``rejected`` (the third value) is ``True`` only for a Tor 3 refusal —
    never for a tool that ran and genuinely failed, which is a different
    problem with a different shape. The loop guard
    (``app/schleifenwaechter.py``) reads it in a job run.

    ``at_path`` (the fourth) is ``True`` for a refusal about the PATH the
    call names (``WerkzeugVerboten.about_path``) — never for one about the
    tool itself. Chat and job run read it to tell a refused file call where
    a moved folder went (``with_move_note``).
    """
    if registry is None:
        # Always English, not `sprache`: this is what reaches the model as
        # the tool's own result (see below), and it is the one call site
        # this helper shares with a job run (app/api/v1/auftraege.py),
        # which has no card of its own to show a second, localized copy on.
        return t("fehler.werkzeug_verboten", "en", name=aufruf.name), True, True, False

    zusatz: dict[str, Any] = {}
    if herkunft != "chat":
        zusatz["herkunft"] = herkunft
    if agent is not None:
        zusatz["agent"] = agent
    if cronjob_id is not None:
        zusatz["cronjob_id"] = cronjob_id
    if ziel_gemeldet:
        zusatz["ziel_gemeldet"] = True
    if modellbild is not None:
        zusatz["modellbild"] = modellbild
    if gedaechtnis_zeigen:
        zusatz["gedaechtnis_zeigen"] = True
    if rules_of is not None:
        zusatz["rules_of"] = rules_of
    if antwort_id is not None:
        zusatz["antwort_id"] = antwort_id
    # Handed to the tools whose work would outlive a stop on its own: the
    # painters, whose picture keeps drawing, and the shell, whose command
    # keeps running — every other tool ends with the call itself.
    if abbruch is not None and (
        aufruf.name in video_tool.DRAWING_TOOLS or aufruf.name == shell.WERKZEUG_NAME
    ):
        zusatz["abbruch"] = abbruch

    try:
        log.info("Tool '%s' is running: %s", aufruf.name, aufruf.argumente)
        return await registry.ausfuehren(
            aufruf.name, aufruf.argumente, bild_senke, ordner=ordner, chat_id=chat_id,
            shell_zeitgrenze=shell_zeitgrenze, **zusatz,
        ), False, False, False
    except WerkzeugVerboten as fehler:
        # The first paragraph only: a refusal of memory_save carries the
        # stored entries after it, and those do not belong in a log file.
        log.warning("Declined: %s", str(fehler).split("\n\n", 1)[0])
        return str(fehler), True, True, getattr(fehler, "about_path", False)
    except Exception as fehler:  # noqa: BLE001 - a broken tool must not shoot down the chat
        log.exception("Tool '%s' failed", aufruf.name)
        return f"Error in '{aufruf.name}': {fehler}", True, False, False


async def _auf_entscheidung_warten(
    generierung: Generierung, aufruf_id: str, name: str
) -> bool | str | None:
    """Waits for the yes or no on a tool — or for an answer to ask_user.

    ``True``/``False`` is the user's decision, a string their answer.
    ``None`` means: none came —
    because the wait time is up, the run was cancelled, or nobody is hanging
    on the other end anymore. In all three cases nothing is executed.

    We wait in small steps instead of one big one: otherwise the run would
    still hang for five minutes on a window that has long been closed.

    ``name`` is the tool this particular prompt is actually about — held alongside the future so the confirm route can tell a
    genuine "always allow" from one naming a different tool.
    """
    zukunft = generierung.bestaetigung_erwarten(aufruf_id, name)
    rest = BESTAETIGUNG_WARTEZEIT
    try:
        while rest > 0:
            try:
                # shield: when the tick runs out, the waiting should end —
                # but the decision itself must not be lost because of it.
                return await asyncio.wait_for(
                    asyncio.shield(zukunft), timeout=BESTAETIGUNG_PRUEFTAKT
                )
            except asyncio.TimeoutError:
                rest -= BESTAETIGUNG_PRUEFTAKT
            except asyncio.CancelledError:
                if zukunft.cancelled():
                    return None
                raise
            if generierung.soll_abbrechen:
                return None
        log.info("No answer came to the confirmation for '%s'", aufruf_id)
        return None
    finally:
        generierung.bestaetigung_ablegen(aufruf_id)


def hole_discovery(request: Request) -> Discovery:
    return request.app.state.discovery


def hole_generierungen(request: Request) -> Generierungsverwaltung:
    return request.app.state.generierungen


def _document_cards(repositories, message_id: str) -> list[dict]:
    """The document cards of one row as it stands now — the same cards the
    message list hands out for it (app/api/v1/chats.py)."""
    from app.api.v1.dokumente import meta_bauen

    row = repositories.messages.holen(message_id)
    cards = []
    for document_id in row.dokument_ids() if row is not None else []:
        document = repositories.documents.holen(document_id)
        if document is not None:
            cards.append(meta_bauen(document).model_dump())
    return cards


def _sse(typ: str, **felder) -> str:
    # Every event carries the moment the service reported it, in the same
    # unit `Date.now()` already uses — a reattach replays the whole history
    # at once, and only this lets the clock over a running section start
    # from when it actually began instead of from the replay itself.
    zeitpunkt_ms = round(time.time() * 1000)
    return f"data: {json.dumps({'typ': typ, 'zeitpunkt_ms': zeitpunkt_ms, **felder}, ensure_ascii=False)}\n\n"


# How often to check whether the browser is still there. Chats only.
VERBINDUNG_PRUEFTAKT = 0.5

# The connection watchdogs, one per bound run. Held on purpose, for the
# reason ``EventBus.veroeffentlichen_ohne_warten`` spells out (app/events.py):
# the loop keeps only a weak reference to a task, so one that nobody holds
# may be collected mid-flight — and this one is the only thing that notices a
# browser that went away while the run sits on a confirmation prompt writing
# nothing.
#
# Measured on the shipped interpreter: a task of this shape survives a forced
# collection today, because ``asyncio.sleep`` parks the future it waits on in
# the loop's own timer heap, and the future holds the task. That is an
# implementation detail, not a promise — asyncio's own documentation says the
# reference is ours to keep — so it is kept. Nothing is retrieved from these
# tasks on the way out, and nothing needs to be: ``_waechter`` swallows every
# exception itself and lets only cancellation through, which carries none.
_wachen: set[asyncio.Task] = set()


async def _waechter(lauf: Generierung, request: Request) -> None:
    """Sets the cancel signal as soon as the owning request is gone.

    This check used to sit in the middle of the loop. But it has to live
    here, because the loop no longer knows the request — and it has to
    **check actively**: if a run is currently hanging on a confirmation
    prompt, it writes nothing, and a vanished browser would otherwise go
    unnoticed.
    """
    try:
        while not lauf.fertig.is_set():
            if await request.is_disconnected():
                lauf.signal.set()
                return
            await asyncio.sleep(VERBINDUNG_PRUEFTAKT)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - the watchdog must not drag down the run
        log.debug("Connection watcher for %s ended", lauf.id, exc_info=True)


async def _zusehen(
    lauf: Generierung, request: Request | None = None, ab: int = 0
) -> AsyncIterator[str]:
    """Delivers the events of a run — first what was missed, then live.

    With ``request`` it is the **owning** request: if it goes away and the
    run is bound to it, the run is cancelled. Without ``request`` someone is
    just watching; if they leave, the run carries on unmoved.
    """
    if request is not None and lauf.an_verbindung_gebunden:
        # Do NOT clean this up again in the finally. If the connection drops,
        # Starlette closes this generator — so the finally runs at exactly
        # the moment the watchdog is needed. Cancelling it there kills it
        # before it can report anything. Exactly this bug existed once: the
        # chat simply kept running after the browser was closed.
        #
        # The watchdog ends by itself as soon as the run is finished — and
        # the reference is let go of exactly then, not before. See `_wachen`.
        aufgaben.halten(_waechter(lauf, request), name=f"wache-{lauf.id}", menge=_wachen)
    async for zeile in lauf.zuschauen(ab):
        yield zeile


# A folder a chat's owner re-chose after the old one moved, kept only for as
# long as this process runs — a heads-up sentence for the model, not a fact
# the database has to carry forever: the document rows themselves already
# point at the new place (app/db/repositories/documents.py, `pfade_umziehen`,
# called from `app/api/v1/chats.py`). Without this the model kept calling
# `read_file` with the old path from its own history and ran into a refusal
# instead of an answer — a saved seam (`app/chatverdichtung.py`) naming the
# old path hits the very same wall, and needs the very same sentence.
# Per chat: the old place, as compared, to the pair (old place, new place)
# as they were reported — the sentence names them as the user chose them.
_ordner_umzuege: dict[str, dict[str, tuple[str, str]]] = {}


def _place_key(pfad: str) -> str:
    """A place as two spellings of it compare: resolved — a link such as
    /tmp to /private/tmp, a trailing slash, a ``~`` — and with the letter
    case aside, the way the gate reads "under" (``grenzen.inside``)."""
    try:
        return str(Path(pfad).expanduser().resolve()).casefold()
    except (OSError, RuntimeError, ValueError):
        return pfad.rstrip("/").casefold()


def ordner_umzug_melden(chat_id: str, alt: str, neu: str) -> None:
    """Records that the folder at ``alt`` now lives at ``neu``.

    One target per old place, the latest: a chain is resolved at once, so
    a place moved on again (A to B, then B to C) points straight at C, and
    a place that is a target again (A to B, then B back to A) is no old
    place any more — it would otherwise send the model to the stale B.
    Places are compared by :func:`_place_key`, so another spelling of the
    same place still closes the chain.
    """
    moves = _ordner_umzuege.setdefault(chat_id, {})
    old_key, new_key = _place_key(alt), _place_key(neu)
    for key, (old, target) in list(moves.items()):
        if _place_key(target) == old_key:
            moves[key] = (old, neu)
    moves.pop(new_key, None)
    if old_key != new_key:
        moves[old_key] = (alt, neu)


def ordner_umzug_vergessen(chat_id: str) -> None:
    # This chat's row and everything the database holds for it goes with
    # `repositories.chats.loeschen` — what lives only in memory has to be
    # told separately, the same way `app/api/v1/chats.py`'s `chat_loeschen`
    # already tells `laeufe.vergessen`: without this call the entry is kept
    # for the life of the process for a conversation nobody can open again.
    _ordner_umzuege.pop(chat_id, None)


def _move_sentence(alt: str, neu: str) -> str:
    return (
        f"The shared folder '{alt}' has moved to '{neu}'. Resolve paths under the old location "
        "against the new location."
    )


def _ordner_umzug_satz(chat_id: str) -> str:
    umzuege = _ordner_umzuege.get(chat_id)
    if not umzuege:
        return ""
    return " ".join(_move_sentence(alt, neu) for alt, neu in umzuege.values())


def move_note(
    chat_id: str | None, name: str, argumente: dict | None, ordner: list[str] | None
) -> str:
    """The move sentence for a refused file call aimed under a moved folder.

    The sentence in the system message alone was not enough: a model still
    calling the old path from its own history read only "outside the shared
    folders" or "does not exist" and gave up on the file. The refusal it
    reads for THIS call now says where the folder went — the same sentence,
    only for the move the path really lies under: the note travels in the
    tool result.

    Only a move whose new place lies in the folders of THIS run: a job run
    working in other folders than its chat would be sent to a place it
    cannot reach, and a sentence that leads nowhere only costs another
    refused call.

    File tools only — they name one path in ``path``; a shell command's text
    names none that could be told apart reliably. The path is read the way
    the tools and the gate read it (``app/tools/grenzen.py``): relative ones
    against the first shared folder, "under" with the disk's letter case
    aside. Without a shared folder no file tool works on a path at all. A
    path the disk cannot take at all (a NUL byte, say) gets no sentence:
    the refusal stays as it is without one.
    """
    moves = _ordner_umzuege.get(chat_id or "")
    if not moves or not ordner or dateiwerkzeuge.modul(name) is None:
        return ""
    raw = str((argumente or {}).get("path") or "").strip()
    if not raw:
        return ""
    try:
        roots = grenzen.wurzeln(ordner)
        meant = grenzen.aufgeloest(raw, roots[0])
        matches = [
            _move_sentence(alt, neu)
            for alt, neu in moves.values()
            if grenzen.inside(meant, grenzen.aufgeloest(alt, roots[0]))
            and any(grenzen.inside(Path(neu), root) for root in roots)
        ]
    except (OSError, RuntimeError, ValueError):
        return ""
    return " ".join(matches)


def with_move_note(
    text: str,
    *,
    refused: bool,
    werkzeuge_an: bool,
    chat_id: str | None,
    aufruf,
    ordner: list[str] | None,
) -> str:
    """The model's copy of one call's result, with the move sentence after it
    when the program refused the call under a moved folder.

    One condition for the chat and the job run alike: a refusal by the
    program — at the folder boundary, or a path that is not there — and
    tools that are on at all; "tools are turned off" is no matter of where
    a folder went. A call the USER declined is not such a refusal and
    never gets the sentence: the user's no stands as it is, a blocked call
    goes back with nothing but the block, and a hint where
    the same file lies would only invite the model around that no.
    Appended to the model's copy only, after any cut, so the sentence is
    never cut off and the window and the log keep their text.
    """
    if not refused or not werkzeuge_an:
        return text
    note = move_note(chat_id, aufruf.name, aufruf.argumente, ordner)
    return f"{text}\n{note}" if note else text


# The system message of each chat, built once and handed out again until
# something in it changes — kept for as long as this process runs. A request
# is only read again from the first byte that differs, and the system message
# is the first thing in it: built fresh for every answer, a memory entry the
# model just saved or a line it wrote into an exe.md moved the very front of
# the request, and the server read the whole chat again (Anthropic, "What
# breaks the cache": any change to the system text drops everything after it).
#
# Keyed by chat; the value is the fingerprint of what the USER can change in
# it, and the text. A different fingerprint builds anew at the next send —
# a folder, the user's own prompt or its switch, the form of address, the
# model, the tool offer, the access mode, the tool rounds, the memory
# switch, the self-picking of skills, a skill the user wrote, a document,
# a moved folder. What the MODEL changes — the memory, an exe.md, a skill it
# saved — is not in the fingerprint and waits for the next fold, which
# forgets the entry (`forget_system_message`), or the next chat.
#
# In memory and not in the database: after a restart the message is built
# once anew, and nothing about it is worth a column.
_system_messages: dict[str, tuple[tuple, str]] = {}


def forget_all_system_messages() -> None:
    """Drops every chat's system message — for a change of the user's that
    can stand in any number of chats, like an exe.md restored in a folder
    several chats share (app/api/v1/ordnerwissen.py)."""
    _system_messages.clear()


def forget_system_message(chat_id: str) -> None:
    """Drops a chat's system message, so the next send builds it anew —
    after a fold, and when the chat is deleted (app/api/v1/chats.py)."""
    _system_messages.pop(chat_id, None)


def _system_bauen(
    app,
    repositories,
    chat,
    zustand,
    *,
    frische_warnungen: list | None = None,
    werkzeugrunden: int = 0,
    modellname: str | None = None,
) -> str:
    """The whole system message for one request, in three layers — built
    once per chat and reused (`_system_messages`).

    A skill the user picked does not go in here any more: it travels in
    front of their message (app/verlaufsbau.py), so picking one leaves the
    front of the request alone.
    """
    config = app.state.config
    registry = getattr(app.state, "werkzeuge", None)
    werkzeuge_da = bool(
        registry is not None
        and config.features.mcp
        and zustand.kann("tool_calls")
        and registry.als_openai_werkzeuge()
    )
    gedaechtnis_da = gedaechtnis.mitschicken(repositories, zustand)

    # Which of the new sentences apply: each one only when the tool it talks
    # about is actually being offered to this model right now.
    #
    # Asked with the default image model, the same one the offer itself is
    # built with (further down): where it is a family that cannot draw from
    # text, draw_image is offered to nobody — and this sentence must not
    # promise it either. The overview names the tools of THIS run, no more
    # and no less.
    angeboten = {
        w["function"]["name"]
        for w in (
            registry.als_openai_werkzeuge(
                bild_fenster=lambda: bild_werkzeug.fensterbild(repositories, config),
                memory_shown=gedaechtnis_da,
            )
            if werkzeuge_da
            else []
        )
    }
    # The names, not a yes: the sentence about the file tools lists them, and
    # listing one this run does not have sends the model at a refusal.
    dateiwerkzeuge_da = [n for n in dateiwerkzeuge.NAMEN if n in angeboten]
    befehle_da = shell.WERKZEUG_NAME in angeboten
    fragen_da = frage_werkzeug.WERKZEUG_NAME in angeboten
    skills_schreiben_da = skill.SCHREIBEN in angeboten
    agenten_da = auftrag_werkzeug.WERKZEUG_NAME in angeboten
    gedaechtnis_schreiben_da = memory.WERKZEUG_NAME in angeboten

    # "This conversation has a document", not "this message does": an
    # attachment travels through the whole history, and the follow-up
    # question three messages later needs the sentence just as much. A
    # count, not a listing: the listing reads every body. The count itself
    # goes into the fingerprint below — every document the user attaches is
    # a change of theirs and builds the message anew.
    document_count = repositories.documents.anzahl(chat_id=chat.id)
    anhaenge_da = document_count > 0

    # Whether the model itself is on this machine — the same reading the
    # memory switch uses (app/gedaechtnis.py): a "local" group means the
    # endpoint runs here, anything else is a provider.
    lokal = getattr(zustand.endpunkt, "group", None) == "local"

    # What the permission rules answer for a chat, said in the prompt —
    # imported lazily for the same reason the registry does it: the
    # permission module imports the tool modules this one imports too.
    zugriff = None
    # The dock and the picture folder, which every run sees beside the
    # chat's own folders — named apart in the prompt unless the user shared
    # one of them as well.
    dock_folder, image_folder = dokumentablage.program_folders(config)
    ordner_offen = dokumentablage.ordner_dieses_chats(
        config.datenverzeichnis,
        chat.working_dirs,
        chat.id,
        [dock_folder, image_folder],
    )
    if ordner_offen:
        from app import berechtigungen
        from app.berechtigungsregeln import laden as regeln_laden

        zugriff = berechtigungen.zugriffslage(
            "chat",
            regeln=regeln_laden(getattr(registry, "berechtigungen_pfad", None)),
        )
    own_folder = dokumentablage.own_folder_in(
        config.datenverzeichnis, chat.id, chat.working_dirs, ordner_offen
    )
    # The maintenance duty names write_file and edit_file, so it only rides
    # along when both are actually on the table — and only where there is a
    # folder to keep notes about.
    exemd_pflegen = bool(chat.working_dirs) and {
        datei_schreiben.WERKZEUG_NAME,
        datei_aendern.WERKZEUG_NAME,
    } <= angeboten
    # Whether the model may reach for skills by itself — the switch, asked
    # now; the catalogue itself is read only when the message is built.
    self_pick = bool(
        skill.LADEN in angeboten
        and skillwahl.selbst_waehlen(repositories, modell=zustand.endpunkt.id, chat=chat.id)
    )
    # The user's prompt is the only part `prompt_aus` suspends. Read on
    # every send: the user's own layer changes the message at once.
    benutzer = "" if chat.prompt_aus else config.system_prompt_lesen()
    address = anrede.lesen(repositories)
    umzug_satz = _ordner_umzug_satz(chat.id)
    model_label, provider_label = grundprompt.model_lines(zustand, modellname)
    vision = zustand.kann("vision")

    # Everything the user can change, and nothing the model can: the memory
    # and the exe.md notes are read only when the message is built below.
    fingerprint = (
        werkzeuge_da,
        tuple(sorted(angeboten)),
        werkzeugrunden,
        gedaechtnis_da,
        document_count,
        tuple(chat.working_dirs),
        tuple(ordner_offen),
        own_folder,
        zugriff,
        lokal,
        self_pick,
        # The memory as the user edited it in the window — their change, at
        # their next message (app/gedaechtnis.py, `user_edit_count`).
        gedaechtnis.user_edit_count() if gedaechtnis_da else None,
        # Only where the catalogue is in the message at all: a skill edited
        # in the window changes nothing in a chat that lists none.
        skills.user_edit_count() if self_pick else None,
        benutzer,
        address,
        umzug_satz,
        model_label,
        provider_label,
        vision,
    )
    cached = _system_messages.get(chat.id)
    if cached is not None and cached[0] == fingerprint:
        return cached[1]

    # What the user wrote down about each shared folder — read once per
    # build, like the memory beside it: a file the model writes takes effect
    # at the next fold or in the next chat, so the front of the request
    # stays the same bytes meanwhile.
    notizen = ordnerwissen.lesen(chat.working_dirs)
    # Our own copy, before anything can destroy the file — written only when
    # the file actually changed (app/ordnerwissen.py). And the 4 KB warning,
    # fired once per chat and folder; the file travels whole either way.
    ordnerwissen.sichern(notizen, config.datenverzeichnis)
    # Asked BEFORE `melden`, because afterwards everything over the line is
    # marked as warned and the answer would always be "old news". What is new
    # here is what the window gets to say once — `melden`'s own return is the
    # state and repeats at every sentence, which is not a warning.
    #
    # The line in the window was named a separate job in that docstring, and
    # this is it: the event on the bus reaches the log and nothing else, there
    # being no road from the bus to a browser, so the warning rides out on the
    # stream that is opening anyway.
    if frische_warnungen is not None:
        frische_warnungen.extend(
            notiz
            for notiz in notizen
            if notiz.zu_gross and not ordnerwissen.schon_gewarnt(chat.id, notiz.ordner)
        )
    ordnerwissen.melden(chat.id, notizen)

    # Only skills the model may reach for by itself, and only when the tools
    # exist to reach with — a catalogue without skill_load names doors that
    # cannot be opened, and so does a skill whose own tool is not offered.
    skill_katalog: list[tuple[str, str]] = []
    if self_pick:
        skill_katalog = [
            (s.name, s.beschreibung)
            for s in skills.automatische(
                skills.skills_laden(*config.skillverzeichnisse), angeboten
            )
        ]

    dock_named = dock_folder if dock_folder not in (chat.working_dirs or []) else None
    images_named = image_folder if image_folder not in (chat.working_dirs or []) else None
    grund = grundprompt.bauen(
        werkzeuge=werkzeuge_da,
        zugriff=zugriff,
        # The same number the runner holds itself to, resolved once by the
        # caller — the prompt naming a different budget than the cut-off
        # enforces would be the prompt lying about the machinery.
        werkzeugrunden=werkzeugrunden,
        # Including this chat's own document folder where it has one: the
        # prompt names the folders the gate actually lets through, or it
        # would send the model at a refusal that is not there.
        ordner=ordner_offen,
        # This chat's own folder, when it is in that list: named to the
        # model as the chat's own, not as something the user shared.
        own_folder=own_folder,
        dock=dock_named,
        images=images_named,
        skills=skill_katalog,
        dateiwerkzeuge=dateiwerkzeuge_da,
        befehle=befehle_da,
        fragen=fragen_da,
        skills_schreiben=skills_schreiben_da,
        # The rail beside the chat draws documents, always — it ships with
        # the program rather than being a setting.
        vorschau=True,
        lokal=lokal,
        kann=grundprompt.faehigkeiten(angeboten, in_chat=True),
        suche=grundprompt.hat_suche(angeboten),
        anhaenge=anhaenge_da,
        # Whether this model can see an attached image at all — the same
        # capability reading the request builder uses further down.
        bilder=vision,
        agenten=agenten_da,
        gedaechtnis_schreiben=gedaechtnis_schreiben_da,
        ordnerwissen=ordnerwissen.fuer_prompt(notizen),
        ordnerwissen_pflegen=exemd_pflegen,
        model_name=model_label,
        provider_name=provider_label,
        tool_names=angeboten,
        memory_travels=gedaechtnis_da,
    )
    text = anrede.anhaengen(
        gedaechtnis.anhaengen(
            grundprompt.mit_benutzerprompt(grund, benutzer),
            config.memory_lesen() if gedaechtnis_da else "",
        ),
        address,
    )
    if umzug_satz:
        text = f"{text}\n\n{umzug_satz}"
    # The one paragraph that differs in every new chat goes behind all the
    # rest, so that everything before it is the same for each of them and the
    # model server keeps it in its cache.
    text = with_own_folder_last(text, ordner_offen, own_folder, dock_named, images_named)
    _system_messages[chat.id] = (fingerprint, text)
    return text


@router.post("/completions", summary="Generate a response (Server-Sent Events)")
async def completions(
    daten: GenerierungAnfrage,
    request: Request,
    repositories: Repositories = Depends(hole_repositories),
    discovery: Discovery = Depends(hole_discovery),
    generierungen: Generierungsverwaltung = Depends(hole_generierungen),
    user_id: str = Depends(hole_benutzer_id),
    sprache: str = Depends(hole_sprache),
) -> StreamingResponse:
    # Everything arriving here is the user being present — they typed, or
    # they pressed the regenerate arrow. That is what sets the wake counter
    # back to zero, and it happens in the ROUTE rather than in the function
    # below because the function is also what a finished background run
    # calls: a wake must never clear the brake that is counting it.
    #
    # AFTER the answer has actually started, not before. Clearing it also
    # drops a postponed wake, on the reasoning that the user's own message
    # rebuilds the history with the report in it — and that reasoning only
    # holds if the message arrives. A request that ends in a 404 or a 409
    # cleared the postponement anyway, and the report then lay unread until
    # somebody typed again: exactly what the wake exists to prevent.
    lauf = await antwort_anstossen(
        app=request.app,
        daten=daten,
        repositories=repositories,
        discovery=discovery,
        generierungen=generierungen,
        user_id=user_id,
        sprache=sprache,
        # A closed tab, a reload, a laptop going to sleep — none of these are
        # the stop button, so none of them should end the answer (a chat now
        # keeps running like a job does). Chats used to be bound by default;
        # the wake path (app/hintergrundwecken.py) already runs unbound for
        # exactly the same reason it now applies here too. The window that
        # opens this chat again finds the run still going and reattaches to
        # it (frontend/src/lib/zustand.svelte.js, `wiederanhaengen`) — the
        # same path a cold reload onto a JOB's own answer already uses.
        an_verbindung_gebunden=False,
    )
    if lauf is None:
        # Stopped while it was still being set up: there is no run, so there
        # is nothing to watch and nothing that could carry the report a
        # postponed wake is waiting to be read in. The brake is left alone —
        # clearing it here would drop that wake for an answer that never
        # came (the rule is spelled out a few lines above, and this is one
        # more way for a request to end without producing an answer).
        return StreamingResponse(
            _gestoppter_strom(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )
    hintergrundwecken.zuruecksetzen(daten.chat_id)
    return StreamingResponse(
        _zusehen(lauf, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # in case nginx ends up in front after all
            "Connection": "keep-alive",
        },
    )


async def antwort_anstossen(
    *,
    app,
    daten: GenerierungAnfrage,
    repositories: Repositories,
    discovery: Discovery,
    generierungen: Generierungsverwaltung,
    user_id: str,
    sprache: str,
    an_verbindung_gebunden: bool = True,
    systemhinweis: str | None = None,
) -> Generierung | None:
    """Starts an answer and hands the run back — without an HTTP request.

    Split off the route the same way the job path was split
    (``auftrag_anstossen`` beside ``auftrag_starten``, app/api/v1/auftraege.py),
    and for the same reason: a run has to be startable from inside the
    service. Until this split, ``completions`` was the only door, and it
    needs a ``Request`` — so a finished background command could put its
    result into the chat but had no way to make the model read it.

    Calling our own service over HTTP was the other way out and is a dead
    end: such a run is bound to that connection, and ``_waechter`` cancels
    it the moment the connection goes.

    ``app`` instead of the request, because the body only ever reached
    through the request for ``app.state``. Errors still leave as
    ``HTTPException`` — the route passes them on, an internal caller catches
    them.

    What is left here is the door and the doorkeeper: find the chat, claim
    it, and hand the claim back whatever happens. The work itself is
    ``_antwort_aufsetzen`` below — split out for the claim's sake, so that
    the one rule this function now enforces fits on a screen instead of
    being a ``try`` at line one and a ``finally`` a thousand lines later.
    """
    chat = repositories.chats.holen(daten.chat_id, user_id=user_id)
    if chat is None:
        raise HTTPException(404, t("fehler.chat_nicht_gefunden", sprache))

    # One answer per chat, said here rather than only in the window.
    #
    # It was true by construction until a finished background command
    # learned to start one: an answer began only when somebody pressed
    # something, and the window greys out sending while it streams. Now
    # answers begin BEHIND the window, so the two can meet — the wake starts
    # one, the user presses send in the same second, and both write into the
    # same chat. The history then carries two assistant turns in a row and a
    # cold window attaches to whichever row it finds.
    #
    # `generationen.py` already says this is how it works ("Only ever one at
    # a time in practice"); this is the sentence that makes it so.
    #
    # Asked and CLAIMED in one call, not merely asked. Asking alone held
    # only as long as the answer started in the same breath, and it no
    # longer does: setting the answer up waits on an embedding model for a
    # cut-up document, and on a whole model request once the history has
    # grown past the compaction threshold. Two callers both got their answer
    # from a window that was open for seconds, both were told the chat was
    # free, and both started. Measured: two runs, two rows marked `laeuft`,
    # and `fuer_chat` handing out only the first of them.
    #
    # The claim is taken HERE, before the waits, rather than the question
    # being asked a second time after them. Two reasons, and the second is
    # the one that decides it:
    #
    # * A second check closes the window it remembers. The compaction wait
    #   was added in front of the registration long after this guard was
    #   written, and nothing said a word; the next one would be just as
    #   quiet. A claim is closed by construction, wherever the waiting ends
    #   up.
    # * The loser of a late check would have paid for the whole setup and
    #   then thrown it away — and not only compute. The user's message is
    #   saved below, and the compaction rewrites the history for good. A
    #   409 after that leaves the chat folded and the message stored for an
    #   answer that never ran. Claimed first, the loser is turned away
    #   before it has touched anything, which is exactly what this guard did
    #   on the day it was written.
    #
    # What the caller sees is unchanged: the same 409, the same sentence.
    #
    # A wake that walks into a claimed chat (app/hintergrundwecken.py) is
    # turned away here rather than postponed, because its own check ran a
    # moment too early to see the claim. That is the right outcome for the
    # case this closes: the chat is claimed by somebody who is TYPING, and
    # their answer builds its history from the database further down — the
    # report the wake wanted read is in there, and gets read. It is the same
    # reasoning `hintergrundwecken.zuruecksetzen` gives for dropping a
    # postponed wake when the user sends something.
    if not generierungen.reservieren(chat.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, t("fehler.antwort_laeuft_schon", sprache)
        )

    try:
        # One document read per document for the whole setup: the document
        # plan, the fold, and the prompt all walk the same rows.
        with dokumentcache.aktiv():
            return await _antwort_aufsetzen(
                app=app,
                chat=chat,
                daten=daten,
                repositories=repositories,
                discovery=discovery,
                generierungen=generierungen,
                user_id=user_id,
                sprache=sprache,
                an_verbindung_gebunden=an_verbindung_gebunden,
                systemhinweis=systemhinweis,
            )
    finally:
        # Unconditionally, and that is not a leak: by the time the good path
        # gets here the run is registered, and from `generierungen.starten`
        # to this line there is no await for anyone to slip through — the
        # chat is guarded by the run itself from that moment on.
        #
        # Every other way out is covered by the same line: a model that is
        # not set or not reachable, an attachment this model cannot read, a
        # document that belongs to another chat, a provider that throws
        # while folding the history — and a cancellation, which is what a
        # closing browser hands this function while it waits.
        generierungen.freigeben(chat.id)


async def _gestoppter_strom() -> AsyncIterator[str]:
    """An answer that was stopped before it began: one `done`, and nothing
    else.

    Every complete stream ends with `done`; a body that simply stops is read
    as a torn line (frontend/src/lib/api.js, `sseLesen`), so an empty body
    here would report a deliberate stop as a broken connection — a red dot
    and a held queue for a run somebody stopped. There is no run and no row,
    so the event names neither an id nor a message: it says one thing, that
    this is the end, and the state it ended in.
    """
    yield _sse("done", abgebrochen=True, zustand="abgebrochen")


async def _antwort_aufsetzen(
    *,
    app,
    chat: Chat,
    daten: GenerierungAnfrage,
    repositories: Repositories,
    discovery: Discovery,
    generierungen: Generierungsverwaltung,
    user_id: str,
    sprache: str,
    an_verbindung_gebunden: bool,
    systemhinweis: str | None,
) -> Generierung | None:
    """Everything between the claim and the running answer.

    Takes the ``chat`` row rather than looking it up again: the caller above
    needed it to make the claim, and a second read could answer differently
    from the first.

    Nothing in here may return the run without ``generierungen.starten``
    having created it, and nothing in here hands the claim back — that is
    the caller's ``finally``, which is the only place that sees every way
    out of this function.
    """
    endpoint_id = daten.endpoint_id or chat.endpoint_id
    if not endpoint_id:
        raise HTTPException(400, t("fehler.kein_modell_verfuegbar", sprache))

    # The id names provider and model together (see app/modellkennung.py);
    # what the server is told is the model name alone.
    gefunden = discovery.aufloesen(endpoint_id)
    if gefunden is None:
        raise HTTPException(
            404, t("fehler.modell_nicht_erreichbar", sprache, name=endpoint_id)
        )
    zustand, modellname = gefunden
    if not zustand.erreichbar:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            t("fehler.modell_nicht_erreichbar", sprache, name=zustand.endpunkt.name),
        )

    # Attachments as lists — the list wins over its scalar twin, the scalars
    # stay for older callers.
    bilder = [
        b
        for b in (
            daten.bilder if daten.bilder is not None
            else ([daten.bild] if daten.bild else [])
        )
        if b
    ]
    dokumente = [
        d
        for d in (
            daten.dokumente if daten.dokumente is not None
            else ([daten.dokument] if daten.dokument else [])
        )
        if d
    ]
    # Kept apart from `dokumente`: that name is reassigned further down to
    # the documents referenced across the whole history, for the request
    # about to be built. These ids are only the ones on the message just
    # saved — what the fold trigger below needs to know arrived just now.
    neu_angehaengte_dokumente = dokumente

    if bilder and not zustand.kann("vision"):
        # The UI grays out the attachment without vision — but the API
        # remains the outer boundary and says so itself if need be.
        raise HTTPException(400, t("fehler.kein_vision", sprache))

    for dokument_id in dokumente:
        # Only an id that really belongs to this chat gets linked —
        # the server later builds the meta card itself from the database.
        dokument = repositories.documents.holen(dokument_id)
        if dokument is None or dokument.chat_id != chat.id:
            raise HTTPException(404, t("fehler.dokument_fehlt", sprache))

    # The answer this request names instead of bringing a turn of its own
    # (app/answer_redo.py). Asked before anything is stored: a request naming
    # an answer the chat does not end in — or one that is still being
    # written, or a failed one, which is asked again where it stands — is
    # turned away with the chat untouched.
    replaced = None
    if daten.replaces:
        replaced = answer_redo.named_answer(repositories, chat.id, daten.replaces)
        if replaced is None or not answer_redo.replaceable(replaced):
            raise HTTPException(404, t("fehler.nachricht_nicht_gefunden", sprache))
    # The failed answer whose model call this request asks again, and what
    # that run had already done (app/answer_replay.py). The run goes on in
    # this very row; nothing is deleted and no call of it is made again.
    retried = None
    kept: answer_replay.Kept | None = None
    if daten.retries:
        retried = answer_redo.named_answer(repositories, chat.id, daten.retries)
        if retried is None or answer_redo.run_state(retried) != answer_redo.FAILED:
            raise HTTPException(404, t("fehler.nachricht_nicht_gefunden", sprache))
        kept = answer_replay.kept(retried)
    # The one row a request of either kind names, if it names one.
    named = replaced or retried

    # The row this request's own turn becomes — kept here, because the clock
    # sentence it goes out with is written back onto it a few lines below.
    # A request without a word, an image or a document writes no row and has
    # none to remember it on.
    saved_turn = None
    # What a picked skill puts in front of this row, for the estimate below.
    skill_invocation_text = ""
    if daten.content or bilder or dokumente:
        saved_turn = repositories.messages.speichern(
            id=daten.nachricht_id,
            chat_id=chat.id,
            role="user",
            content=daten.content or "",
            anhaenge=bilder or None,
            dokumente=dokumente or None,
        )
        repositories.chats.zeitstempel_auffrischen(chat.id)
        # A skill the user picked from the slash list goes in front of their
        # words, on this row, and from here on travels with it
        # (app/verlaufsbau.py) — not into the system message, whose bytes
        # stay the same. Looked up rather than trusted: the name travels
        # from the browser, and the only names that exist are the ones on
        # disk; an unknown one lets the message through without it.
        if daten.skill:
            picked = skills.skills_laden(*app.state.config.skillverzeichnisse).get(daten.skill)
            if picked is not None:
                # Words beside the "/name" the window keeps in the text — only
                # then is there an instruction to hand over to.
                words = skills.words_after_command(daten.content or "", picked.name).strip()
                skill_invocation_text = skills.invocation(picked, bool(words))
                repositories.messages.set_skill_invocation(saved_turn.id, skill_invocation_text)

    # What goes in front of this turn's own words on its way to the model,
    # and only there — never stored, never shown (app/verlaufsbau.py, the
    # instruction a request carries): a spoken turn's instruction, and in
    # front of it the note that the model's previous reply was stopped
    # before it finished (app/stop_note.py). That reply is the newest one of
    # the model's own; a request without a turn of its own carries no note,
    # and a spoken reply cut short already says so in its own words.
    turn_prefix = stop_note.with_stop_note(
        diktatsprachewahl.gespraechsvorsatz(repositories, daten.unterbrochen)
        if daten.gespraech
        else None,
        saved_turn is not None
        and not (daten.gespraech and daten.unterbrochen)
        and stop_note.previous_reply_stopped(
            repositories.messages.letzte(chat_id=chat.id, role="assistant")
        ),
    )

    # Remembers the model choice on the chat so it is set next time.
    if chat.endpoint_id != endpoint_id:
        repositories.chats.aktualisieren(chat.id, endpoint_id=endpoint_id)
        chat = repositories.chats.holen(chat.id)

    # What this model is set to, resolved through the cascade: global, then
    # what holds for this model, then what holds for this chat. A new chat
    # therefore starts with the model's settings instead of at the endpoint's
    # bare defaults — which is the whole point of the table.
    eingestellt = repositories.einstellungen.zusammengefuehrt(
        "parameter", modell=endpoint_id, chat=chat.id
    )

    # Which thinking stages this model has already answered with an error.
    # Read once, before the request is built: the stage that goes out must
    # not be one that was refused before, and the same list decides whether
    # a fresh refusal is worth writing down. Kept under the id the model
    # list reads them under (app/discovery.py `refusal_key`), not under the
    # chat's own spelling of the model: an older chat that names a catalogue
    # server alone would otherwise write a list the model list never reads.
    refusal_id = refusal_key(zustand, modellname)
    denken_abgelehnt = denkablehnung.gemerkt(repositories.einstellungen, refusal_id)

    # A spoken conversation does not think: the voice would stay silent for
    # as long as the thinking runs. Off for this one request, through the
    # same switch the fold uses — it knows each provider's form and the
    # model's own refusals. A model that cannot be switched off gets its
    # smallest stage instead, and one that always thinks gets nothing.
    # The chat's own thinking setting is left as it is; a typed message
    # thinks as before.
    #
    # A typed message without a stage of its own gets the one stored for
    # this model, resolved here rather than in the window: the window only
    # sends a stage somebody has just set, so a stored one — "off" above
    # all — holds from the very first message, before the window has read
    # it back. The window stores a pick under the id the model list carries
    # for this model — the same id the refusals are kept under.
    denkprofil = zustand.denkprofil(modellname, denken_abgelehnt)
    gespeichert = repositories.einstellungen.aufgeloest(denkenwahl.SCHLUESSEL, modell=refusal_id)
    denkstufe: str | bool | None
    if daten.gespraech:
        denkstufe = denkschalter.quietest(zustand, modell=modellname, abgelehnt=denken_abgelehnt)
    elif daten.thinking is None:
        denkstufe = denkenwahl.aufgeloest(gespeichert, denkprofil)
    else:
        denkstufe = daten.thinking

    # A host known only by the plain OpenAI field is sent `medium` where
    # nobody picked a stage; a server that refuses it gets the same turn
    # once more without the field, the way a spoken
    # turn does. A stage somebody picked stays theirs: refused, it ends the
    # turn on the provider's own sentence.
    # Two cases are the program's choice and not a pick: the default where
    # no stage of the scale is stored (nothing, the older yes-form, or a word
    # off the scale), and the depth standing in for a stored stage the host
    # no longer takes (app/denkenwahl.py, `nearest_depth`). Refused, either
    # one marks the whole field refused, and the turn goes out once more
    # without it. A stage the request names itself is always somebody's
    # pick, whatever it is.
    field_default = (
        not daten.gespraech
        and daten.thinking is None
        and denkprofil.quelle == denkstufen.SOURCE_OPENAI_FIELD
        and isinstance(denkstufe, str)
        and (
            (
                denkenwahl.nothing_stored(gespeichert)
                and denkstufe.strip().lower() == denkstufen.standardstufe(denkprofil)
            )
            or denkenwahl.is_substitute(gespeichert, denkprofil, denkstufe)
        )
    )
    retry_without_stage = daten.gespraech or field_default
    # The fields this model's route always gets: kept on a repeat without
    # the stage, and never taken for a stage when a refusal is read.
    think_route = denkschalter.route_for(zustand, modell=modellname)

    def stufe_zusatz(max_tokens: int | None) -> dict[str, Any]:
        """The stage's own request fields for the ceiling a round has right
        now. Off goes out the way the fold already sends it,
        which also carries the model's own refusals along;
        every other stage keeps asking for the stage and the ceiling
        together, the way a round's thinking budget has always depended on
        how much room the round has left."""
        if denkschalter.ist_aus(denkstufe):
            # The same switch `ausschalten` builds — asked for it directly
            # rather than re-deriving it here, so the two cannot drift.
            # There is no parameter dict to strip a second time at this
            # point in a round, so an empty one goes in and its answer is
            # thrown away.
            schalter, _ = denkschalter.ausschalten(
                zustand, {}, modell=modellname, abgelehnt=denken_abgelehnt
            )
            return schalter
        return denkschalter.zusatz(
            denkstufe,
            zustand,
            modell=modellname,
            abgelehnt=denken_abgelehnt,
            max_tokens=max_tokens,
        )

    # How many tool rounds this answer may run, from the same cascade. Resolved
    # once here rather than read inside the loop, so the number cannot change
    # mid-answer while the model is still working.
    max_werkzeug_runden = werkzeugrundenwahl.runden(
        repositories, modell=endpoint_id, chat=chat.id
    )

    # How long one shell command may run, from the same cascade — resolved
    # once alongside the rounds, for the same reason: the number must not
    # change mid-answer, and the tool description below has to name the
    # value that actually holds.
    befehl_zeitgrenze = befehlszeitwahl.sekunden(
        repositories, modell=endpoint_id, chat=chat.id
    )

    # Only offer tools if the feature is switched on and the endpoint can
    # do tool calls at all.
    # Filled while the system message is assembled, because that is where the
    # folder notes are read — and the question "which of these has this chat
    # not been told about yet" can only be asked before `melden` marks them
    # all. Handed back out through here so the stream below can say it once.
    zu_grosse_notizen: list = []

    registry = getattr(app.state, "werkzeuge", None)
    werkzeuge_offen = bool(
        registry is not None
        and app.state.config.features.mcp
        and zustand.kann("tool_calls")
    )
    if werkzeuge_offen:
        # What the user switched off is handed in before the list is built,
        # so it is missing from the offer and refused on execution alike.
        #
        # And it happens HERE, before the system message below is assembled:
        # that message asks the registry which tools are being offered, and
        # `registry.abgeschaltet` is an attribute that stays put between runs.
        # Built first, the prompt would describe the state the PREVIOUS run
        # left behind — possibly from another chat — so a tool switched off
        # still got its sentence for one more round, and one switched on got
        # it a round too late. The job path already does it in this order
        # (app/api/v1/auftraege.py, werkzeugwahl.anwenden before
        # grundprompt.bauen); the chat path was the one out of step.
        werkzeugwahl.anwenden(registry, repositories, chat=chat.id)

    # What the user asked for, and nothing else: the request's own number,
    # then the settings cascade. ``None`` means nothing is set — "Auto" — and
    # what that comes to is worked out further down, once the request is
    # built and its input can be measured (app/antwortgrenze.py).
    #
    # The two are kept apart on purpose. The document plan below asks what
    # the ANSWER has been promised, and under Auto the answer has been
    # promised nothing: it takes what is left, so holding a share back for it
    # would spend the same room twice.
    eingestellte_grenze: int | None = (
        daten.max_tokens
        if daten.max_tokens is not None
        else eingestellt.get("max_tokens") or None
    )

    # Shipped instructions, then the user's layer, then what is known about
    # them — ONE system message, because Anthropic takes a single system
    # field and providers disagree about a second.
    #
    # The shipped part is assembled for THIS chat: no tool section without
    # tools, no folder section without shared folders. What does not apply
    # would only dilute attention. Built once and handed out again until
    # the user changes something in it or the chat folds
    # (`_system_messages`).
    #
    # Built here, before the document plan: the plan needs to know how much
    # of the window the text already takes.
    systemtext = _system_bauen(
        app,
        repositories,
        chat,
        zustand,
        frische_warnungen=zu_grosse_notizen,
        # The number resolved above for the runner itself, so the prompt
        # and the cut-off cannot name two different budgets.
        werkzeugrunden=max_werkzeug_runden,
        modellname=modellname,
    )
    # A run nobody asked for says so — behind the report that woke it, in
    # that turn, and from then on with it (app/verlaufsbau.py): the notice
    # goes in as a message. Not in the system message: a
    # wake would move the front of the request, and the server would read
    # the whole chat again. The report travels in the user's voice but is
    # marked as the service's (app/verlaufsbau.py, `_als_modellnachricht`),
    # and the notice itself opens by saying the user started nothing.
    # Only onto a report the service wrote: by the time this runs the user
    # may have sent something, and their row — or an answer to it — is no
    # report a wake was for.
    wake_notice_written = ""
    if systemhinweis:
        report_row = repositories.messages.neueste_fuer_das_modell(chat_id=chat.id)
        if report_row is not None and ist_dienstbericht(report_row.art):
            repositories.messages.set_wake_notice(report_row.id, systemhinweis)
            wake_notice_written = systemhinweis

    # What this request carries of each document IN THE PROMPT, decided
    # against THIS model's window (app/dokumentbudget.py): whole where it
    # fits, nothing where it does not. Only the documents the rows the model
    # sees still point at — one a fold has already spoken for is in no
    # prompt and gets no share. Newest first: the one the user just attached
    # is the one the question is most likely about. Weighed against the rows
    # as they stand before the fold below, which can only make them
    # smaller: a budget read from the larger prompt errs towards leaving
    # room, never towards overrunning.
    #
    # The documents come through the per-answer cache on purpose — one read
    # of each body for the whole answer.
    #
    # And only when the chat has documents at all. A chat without them is
    # the common case, and it must not pay a second reading of its history
    # — the rows go out from the read below, after the fold — for a plan
    # that would be empty.
    zeilen_vorab: list = []
    kennungen: list[str] = []
    if repositories.documents.anzahl(chat_id=chat.id):
        zeilen_vorab = repositories.messages.fuer_das_modell(chat_id=chat.id)
    for zeile in reversed(zeilen_vorab):
        for kennung in reversed(zeile.dokument_ids()):
            if kennung not in kennungen:
                kennungen.append(kennung)
    # Only what has a text to carry. A file the model delivered into the chat
    # hangs on its answer as a file and nothing more: it is in no prompt, so
    # it takes no share of the window and its card is told nothing about one.
    dokumente = [
        d
        for d in (dokumentcache.holen(repositories, k) for k in kennungen)
        if d is not None and d.extracted_text
    ]
    # What this request offers, read out once and here rather than further
    # down: the tool definitions go out with EVERY request and cost the
    # window — 7,688 tokens for the shipped offer, as measured —
    # and the document budget below has to pay for them before it decides
    # what still fits. Built after the off-list was handed in above, so it
    # is the offer this request really carries.
    #
    # The image model is the picture server's default model: the drawing
    # tool's description names the model that will draw, and the values it
    # may send depend on what that family reads (app/tools/bild_werkzeug.py).
    # Read here, not at startup — the registry outlives a chat and several
    # of them, and the default model can change between two questions.
    angebot = (
        registry.als_openai_werkzeuge(
            shell_zeitgrenze=befehl_zeitgrenze,
            # A callable: read only if draw_image is really offered here.
            bild_fenster=lambda: bild_werkzeug.fensterbild(repositories, app.state.config),
            # memory_save promises only what holds for this model's side.
            memory_shown=gedaechtnis.mitschicken(repositories, zustand),
        )
        if werkzeuge_offen and registry is not None
        else []
    )
    dokumentplan: dict | None = None
    # What this answer carries of each document, BY ROW: every row this
    # request wrote a state onto, and what it wrote there. Written onto those
    # rows below and handed to the window with `done`.
    #
    # By row, and not by document id alone as it used to be: flat, the map
    # named a reading without saying whose, so the window laid it over every
    # card of the chat that carried that document. A row this request never
    # sent — a folded one, which `fuer_das_modell` leaves out, or one past
    # its backstop — is not written here and keeps in the table the word of
    # the last answer that DID carry it, while the card on screen showed
    # this answer's. The two then swapped places on the next reload.
    #
    # Kept until the end so the state can be CORRECTED after the answer:
    # written before the request goes out, "whole in the context" is a plan,
    # and a provider that refuses the request turns it into a false
    # statement.
    dokumentstand: dict[str, dict[str, str]] = {}

    def karten_berichtigen() -> None:
        """Takes back every "whole in the context" this request wrote.

        The state is written BEFORE the request goes out, so it is a plan.
        Called from the two places that learn the plan was wrong — the
        provider's refusal and an answer that ran into the wall mid-sentence
        without one — because a card left standing told the user the
        document had travelled while the turn beside it said the context was
        full.
        """
        from app.api.v1.dokumente import ABGELEHNT

        for zeile_id, stand in list(dokumentstand.items()):
            berichtigt = {
                kennung: ABGELEHNT if wert == "ganz" else wert
                for kennung, wert in stand.items()
            }
            if berichtigt != stand:
                repositories.messages.dokumentstand_setzen(zeile_id, berichtigt)
                dokumentstand[zeile_id] = berichtigt
    if dokumente:
        # The rows as they go out, tool calls and results included
        # (app/verlaufsbau.py, `werkzeuggewicht`) — the same reading the
        # fold makes of them.
        belegt = (
            tokenmass.tokens(systemtext)
            + sum(
                tokenmass.tokens(zeilentext(z, repositories, volltext_mitschicken=False))
                # `werkzeuggewicht` answers in CHARACTERS and has no text to
                # hand over, so this is the one place the rough ratio has to
                # do. Measured through `tokens(str(...))` it priced the
                # DIGITS of the number — twenty tool rounds of two thousand
                # characters counted as forty tokens instead of ten thousand.
                + werkzeuggewicht(z, bool(angebot)) // tokenmass.ZEICHEN_JE_TOKEN_ROH
                for z in zeilen_vorab
            )
            # The tool definitions, which travel with every request and were
            # never in this sum: the same file cost 7,688 tokens more with
            # the offer than without it (measured against an oMLX server).
            + sum(tokenmass.tokens(str(w)) for w in angebot)
        )
        assert zustand.context_tokens is not None, (
            "a reachable endpoint always has a resolved window (app/fenstergroesse.py)"
        )
        dokumentplan = dokumentbudget.verteilen(
            dokumente,
            dokumentbudget.budget_tokens(
                zustand.context_tokens, eingestellte_grenze, belegt
            ),
        )
        # What this answer carries of each document, written onto the rows
        # the documents hang on so each card can say it
        # (app/api/v1/dokumente.py, `getragen`) — after a model change or a
        # regenerate the card follows the new answer. Rows outside the prompt
        # are not among these and keep the word of the last answer that
        # carried them. Synchronous writes, before the rows are read below:
        # that stretch must not await.
        for zeile in zeilen_vorab:
            stand: dict[str, str] = {}
            for kennung in zeile.dokument_ids():
                anteil = dokumentplan.get(kennung)
                if anteil is None:
                    continue
                stand[kennung] = "ganz" if anteil.ganz else "kein_platz"
            if stand:
                repositories.messages.dokumentstand_setzen(zeile.id, stand)
                dokumentstand[zeile.id] = stand

    # Where the context reading stood before this run started. It is what a
    # provider that cannot count its own prompt falls back on (see
    # `_kontextstand`): the new prompt is the last total plus whatever this
    # turn added. Read before the placeholder below exists, so the empty row
    # this run is about to create cannot be the one that answers it.
    #
    # Backwards through the chat, not `letzte(role="assistant")`: the newest
    # assistant row may be a picture or a background command's report, and
    # those carry no reading at all — the answer that does may sit behind
    # them.
    #
    # And through the history as the MODEL sees it, not through everything
    # the reader sees: a row a summary already speaks for is no longer in
    # the prompt, so its reading must not stand in for the size of one. This
    # estimate may fall short — the exact number replaces it at the end of
    # the round — but it must never claim room that was just freed.
    #
    # One query for the one integer. Reading the whole history and walking
    # it backwards was the first of three reads of that history per answer.
    vorheriger_stand: int | None = repositories.messages.letzter_tokenstand(
        chat_id=chat.id
    )

    # What arrived since `vorheriger_stand` was read: the message just
    # saved above, priced the rough way `kontextdruck.prozent` counts
    # everything in — text by its length, an attachment by what it costs
    # once turned into the same currency. None of the three has a real
    # token count yet; the round has not gone out.
    #
    # A document counts what THIS request actually carries of it
    # (`dokumentplan`, resolved just above) rather than its whole length —
    # the same reading the request builder and the fold's own weighing use,
    # so a document too large for this model's window does not inflate the
    # trigger past what it will really cost. An image has no length at all,
    # so it counts at the flat estimate `kontextdruck.bild_zeichen` answers
    # for it.
    neu_tokens = tokenmass.tokens(daten.content) + kontextdruck.bild_tokens(len(bilder))
    # The same text `_verlauf_bauen` is about to prefix onto this very
    # message — left out here, the estimate that decides whether to fold
    # BEFORE the request goes out would always read a few hundred tokens
    # light for a conversation turn.
    neu_tokens += tokenmass.tokens(turn_prefix or "")
    # The picked skill, which `_verlauf_bauen` puts in front of this very
    # row (app/verlaufsbau.py, `_with_invocation`) — a long instruction left
    # out here would let the request go out heavier than the fold weighed it.
    neu_tokens += tokenmass.tokens(skill_invocation_text)
    # And a wake's notice, which goes out behind the report it was written
    # onto above — a wake carries no words of its own to count.
    neu_tokens += tokenmass.tokens(wake_notice_written)
    for dokument_id in neu_angehaengte_dokumente:
        dokument = dokumentcache.holen(repositories, dokument_id)
        if dokument:
            neu_tokens += dokumentbudget.beitrag(dokument, dokumentplan)

    # Fold the settled middle away before the request is built, if the chat
    # is ABOUT TO grow past the threshold. Before, not after: what this saves has
    # to be saved in the prompt that is about to go out, and the rows it
    # folds are the ones `_verlauf_bauen` is about to read.
    #
    # It sat AFTER the build for a while, and the comment already said this
    # then — the round that had grown past the threshold went out in full
    # and only the next one was ever smaller, which is precisely the round
    # this exists for. It passed a live test regardless: that test read the
    # DATABASE, which does get folded, and not the request that went out.
    #
    # Once per answer, because this is the fold that is WRITTEN DOWN: the rows
    # it folds are rows, and a chat rebuilds its history from them on every
    # request. A single answer that fills the window inside itself, over many
    # tool rounds, is caught in the round loop instead — old tool results are
    # cleared from the request (app/werkzeugkuerzung.py) and, where that is
    # not enough, the list in memory is folded there, without a row being
    # written mid-answer. There is no 90% net in the chat and there is not
    # meant to be one: the net is that check plus the provider's own "too
    # long", which every round of this answer now answers with a fold or a
    # lower ceiling. The emergency handoff (app/zwischenstand.py) belongs to
    # jobs and is not reached from here.
    #
    # A summary the model cannot write leaves the chat as it found it:
    # nothing is folded, the fold pause books the failure, and a later turn
    # asks again (app/faltpause.py). Nothing is lost either way — a fold is
    # a pointer and every folded row stays readable — so nothing is guarded
    # here beyond letting it say whether it did anything.
    verdichtet_zu = await chatverdichtung.vielleicht_verdichten(
        zustand=zustand,
        repositories=repositories,
        chat=chat,
        endpoint_id=endpoint_id,
        modellname=modellname,
        vorheriger_stand=vorheriger_stand,
        neu_tokens=neu_tokens,
        # A ceiling the user set is reserved out of the same window, so the
        # threshold measures against what is left (app/kontextdruck.py).
        eingestellte_grenze=eingestellte_grenze,
        # No ceiling handed down any more: the summarizing request works out
        # its own against its own input (app/antwortgrenze.py). The answer's
        # ceiling is the user's choice for ANSWERS, and a summary cut off by
        # it is stored as if it were whole.
        #
        # The same reading of the documents the request will carry, so the
        # fold weighs the prompt that really goes out.
        dokumentplan=dokumentplan,
        # And the same rows: the answer a new one is about to replace is in
        # no request, and a failed answer asked again closes the request as
        # its own turns, not as a row — neither is weighed or folded here.
        without=named.id if named is not None else None,
        # Whether the request offers tools: the rows are weighed in the
        # shape their tool calls will have in it.
        offers_tools=bool(angebot),
        # The claim carries the stop button's signal until the run exists:
        # pressed while the summary is being written, the fold request is
        # closed on the spot (app/faltversuche.py).
        stopp=generierungen.anspruch(chat.id),
        # Where the pictures lie, so a picture weighs what it is sent at.
        config=app.state.config,
    )
    if verdichtet_zu:
        # The fold is where what the model wrote meanwhile — the memory, an
        # exe.md — comes into the system message: the next send builds it
        # anew. This answer keeps the one it was set up with.
        forget_system_message(chat.id)
        # The reading the next estimate builds on described a prompt that no
        # longer exists — the fold just made it smaller. Dropped rather than
        # corrected: the round's own numbers replace it within seconds, and
        # a stale high number would keep the bar claiming room that was just
        # freed.
        vorheriger_stand = None

    # The pictures this request will carry are made ready HERE, while awaits
    # are still allowed: the FIRST look at a large picture starts a tool
    # process that may take up to a minute, and it belongs in its own thread
    # so the loop keeps answering (the form the picture routes
    # use, app/api/v1/bild.py). The stretch from the read below to the
    # placeholder expects no await, and in it a picture is only looked up on
    # record (app/model_image.nachschlag) — the copy made here is found with
    # two stat calls. The names come from a light pass of its own
    # (repositories.messages.bildanhaenge) so that the ONE history read stays
    # the one (tests/test_generierung.py::test_die_geschichte_wird_je_antwort
    # _einmal_gelesen); the read below stays the one that counts.
    #
    # It stands BETWEEN the two claim checks on purpose: a stop that is
    # ALREADY set — pressed while the fold ran — skips it entirely, and a
    # stop pressed DURING it is honoured right below. The shrink itself runs
    # to its end like the fold does; nothing follows it.
    if (anspruch := generierungen.anspruch(chat.id)) is not None and anspruch.is_set():
        return None
    anhang_namen = sorted(set(repositories.messages.bildanhaenge(chat_id=chat.id)))
    # The pictures earlier tool reads attached, by the note their rows carry
    # (app/werkzeugbild.py ``READ_IMAGE_PATH``): at most the newest
    # ``OUTBOUND_IMAGE_LIMIT`` ride again in this request
    # (app/verlaufsbau.py), and their copies are made here.
    tool_picture_paths = repositories.messages.tool_entry_values(
        chat_id=chat.id,
        key=werkzeugbild.READ_IMAGE_PATH,
        newest=werkzeugkuerzung.OUTBOUND_IMAGE_LIMIT,
    )
    if (anhang_namen or tool_picture_paths) and zustand.kann("vision"):
        await asyncio.to_thread(verlaufsbau.bilder_vorbereiten, app.state.config,
                                anhang_namen, tool_picture_paths)

    # The stop button, pressed while the fold or the picture warm-up was
    # running. The claim this
    # request took at its very start carries the signal (app/generationen.py)
    # and it is honoured HERE, before anything is stored and before a run
    # exists: no answer begins, the chat is free again, and the question
    # stays without an answer exactly as after a fold that failed. The fold's
    # own model request runs to its end — nothing on that path can be
    # cancelled — but nothing follows it.
    #
    # Without this the press reached nothing at all: a stop walked over the
    # registered runs of the chat, found none (the claim is not a run), and
    # the answer began anyway, out of a window that had just stopped it.
    if (anspruch := generierungen.anspruch(chat.id)) is not None and anspruch.is_set():
        # No run, so nothing to hand back: `None` is what every caller reads
        # as "no answer was set up here" — `completions` answers the stopped
        # end for it and leaves the wake brake alone, the wake reads it as a
        # wake that did not happen and lays its own back
        # (app/hintergrundwecken.py).
        return None

    # The rows the prompt is built from, read HERE and not a line earlier.
    # The fold above awaits a model request, and a background command can
    # report during that wait: a report written before this read is in the
    # prompt, one written after it is not — and that is the rule the wake
    # (app/hintergrundwecken.py) asks the database about when it decides
    # whether a report went unread. From this read to the placeholder saved
    # below nothing awaits, so a report is either before both or after
    # both, never between. An await in that stretch would open a blind
    # spot: a report in it would sit before the placeholder, counted as
    # read, and be in no prompt at all.
    # The finished background runs whose reports the history is about to
    # carry — taken BEFORE the rows are read, so a run that ends a moment
    # later, with its report landing after the read, is not counted as
    # read. A run's report row is written in the same step as its ending,
    # nothing awaited in between (app/tools/shell.py), so "finished before
    # the read" and "report in the request" are one fact here.
    gelesene_laeufe = hintergrund.laeufe.abgeschlossene(chat.id)
    zeilen = repositories.messages.fuer_das_modell(chat_id=chat.id)
    if replaced is not None:
        # The new answer is written on the history without the one it
        # replaces. Only the request leaves that row out: the row itself
        # stays stored until the new answer is finished (the closing write).
        zeilen = [z for z in zeilen if z.id != replaced.id]
    if retried is not None:
        # The request the failed call carried: everything written before
        # the answer's row, by the rule a fold inside an answer reads its
        # rows by — nothing from the row on. A report that landed behind
        # the failed answer was in no request of this run and is in none
        # now; it stays unread, and no run is counted as read for it.
        row_ids = [z.id for z in zeilen]
        if retried.id in row_ids:
            zeilen = zeilen[: row_ids.index(retried.id)]
        else:
            zeilen = [z for z in zeilen if z.created_at < retried.created_at]
        gelesene_laeufe = []

    # The date block in front of this turn — but only when the request would
    # otherwise carry no reading of today at all. Read HERE, after the fold
    # and from the very rows the prompt is built from, and not a step
    # earlier: a fold can take the last block-carrying row away in the same
    # request, and a decision made above it would leave the request with no
    # date at all.
    #
    # Which is why the test is not "is this turn the first" but "does any
    # row already carry today's BLOCK": the first message of a chat, the
    # first of a new day, and the first after a fold that swallowed the last
    # one all fall out of that one question. By the block and not by the
    # date alone, because a row of the former clock SENTENCE names a minute
    # in the user's own voice — the very thing this block replaced — and
    # must not count as a request that knows the day.
    #
    # Written onto the turn it goes out with, so every later request hands
    # that turn back byte for byte (app/verlaufsbau.py reads it there): a
    # fresh block on the next request would move one row in the middle of
    # the history, and the server reads a request again from the first byte
    # that differs — everything behind that row with it.
    # Read once for this answer and kept for every round of it: an answer that
    # runs over midnight keeps the block it began with, and the clock tool is
    # what answers the new day (app/grundprompt.environment_block). The fold
    # below asks the same reading again rather than taking a second one.
    block = grundprompt.environment_block(app.state.config.app.timezone)
    if saved_turn is not None:
        _restore_environment_block_on_rows(repositories, zeilen, block)

    # The offer was already read out above — it has to be known before the
    # document budget, which pays for it, and before the history, which
    # feeds earlier tool calls back as calls only when the model can call
    # tools NOW (see `_verlauf_bauen`).

    # What the failed call carried of its own answer, behind the rows: its
    # finished tool rounds (app/answer_replay.py). Its pictures count with
    # the rows' for the rule of the newest few, the way the run counted them
    # in its own request — one plan for both, so the answer's pictures and
    # the history's are retired from one list.
    carried_answer = (
        answer_replay.carried(retried, kept) if retried is not None and kept is not None else None
    )
    tool_plan = verlaufsbau.tool_picture_plan(
        [*zeilen, carried_answer] if carried_answer is not None else zeilen,
        app.state.config,
        zustand.kann("vision"),
        bool(angebot),
    )
    nachrichten = _verlauf_bauen(
        chat,
        repositories,
        # Built above, before the document plan that needed its length.
        systemtext,
        config=app.state.config,
        vision=zustand.kann("vision"),
        zeilen=zeilen,
        werkzeuge=bool(angebot),
        # What this request carries of each document, decided above
        # against this model's window.
        dokumentplan=dokumentplan,
        gespraechsanweisung=turn_prefix,
        tool_plan=tool_plan,
    )
    if carried_answer is not None and kept is not None:
        # Behind the rows, what this run had done before it failed: its
        # finished tool rounds as calls and results, as the failed call
        # carried them. The model is asked again from exactly there — and
        # the request ends on a turn the model answers, never on one of its
        # own (app/replay_as_question.py).
        nachrichten[:] = replay_as_question.fold_into_question(
            nachrichten,
            verlaufsbau.answer_turns(
                carried_answer, kept.content, werkzeuge=bool(angebot), tool_plan=tool_plan
            ),
        )

    # Whether this request carries the block at all — settled once, with the
    # request itself, and asked again before every send below. A request that
    # went out with a reading of the day keeps one: a fold of the history can
    # take the turn that carried it, and the rounds after that fold would run
    # without a date to the end of the answer. A request that never carried
    # one — "send again", whose turn was written without one — is left alone;
    # handing it a block now would change a turn that has gone out without
    # one all along.
    block_in_request = any(block in (inhalt.content or "") for inhalt in nachrichten)

    # The ceiling this request goes out with. Worked out HERE, and not where
    # the setting was read: under "Auto" the number is the window less what
    # this request weighs, and what it weighs is only settled once the
    # history, the system text and the document plan are all in it.
    #
    # The thinking budget below hangs on the same number — Anthropic's older
    # generation wants one smaller than the ceiling — so both are resolved
    # from this one line rather than from two readings that could drift.
    #
    # For the FIRST round. Every further tool round asks the same question
    # again from its own, longer history (see the round loop below).
    assert zustand.context_tokens is not None, (
        "a reachable endpoint always has a resolved window (app/fenstergroesse.py)"
    )
    antwortdeckel = antwortgrenze.aufloesen(
        eingestellte_grenze,
        antwortgrenze.geltender_deckel(zustand, modellname),
        zustand.context_tokens or 0,
        antwortgrenze.eingabe_schaetzen(nachrichten, angebot),
        anthropic=antwortgrenze.anthropic_draht(zustand),
    )

    # Off goes out the way the fold already sends it (app/denkschalter.py
    # `ausschalten`): the switch and the parameters agree,
    # instead of a stored thinking length riding along beside a switch that
    # says not to think at all — two answers to the same question in one
    # request. Every other stage keeps asking `zusatz` directly, unchanged.
    roh_parameter = {**eingestellt, **(daten.parameter or {})}
    if denkschalter.ist_aus(denkstufe):
        zusatz_wert, roh_parameter = denkschalter.ausschalten(
            zustand, roh_parameter, modell=modellname, abgelehnt=denken_abgelehnt
        )
    else:
        zusatz_wert = stufe_zusatz(antwortdeckel)

    anfrage = Generierungsanfrage(
        nachrichten=nachrichten,
        temperature=(
            daten.temperature if daten.temperature is not None else eingestellt.get("temperature")
        ),
        top_p=daten.top_p if daten.top_p is not None else eingestellt.get("top_p"),
        max_tokens=antwortdeckel,
        # Everything else the cascade resolved, overridable by the request.
        # A thinking length only travels where the knob is open for THIS
        # model — the stored value stays where it is and goes along again
        # the moment a model with a usable thinking length is in use.
        parameter=parameter.ohne_gesperrte_denklaenge(
            roh_parameter,
            freigegeben=denklaenge_erlaubt(zustand, modellname, repositories.einstellungen),
        ),
        # The id the server itself reports under /v1/models — not our
        # endpoint id. This used to say "mana" or "gemma-mac"; mlx_lm.server
        # interprets "model" as a HuggingFace id and answers that with a 404.
        # If nothing is reported, the field is not sent at all — better to
        # omit than to guess.
        modell=modellname,
        # The thinking stage: only goes along where this model really has
        # that stage — otherwise the server keeps its own default. Which
        # field it lands in is the translator's business, not this one's.
        # The ceiling travels with it because one provider generation asks
        # for a thinking budget in tokens and wants it below that ceiling.
        zusatz=zusatz_wert,
    )

    if angebot:
        anfrage.werkzeuge = angebot


    # `zustand="laeuft"` from the first moment: this row is the one answer
    # being written, and it says so itself now. Every other row a chat
    # gains during a run — a finished background command, a picture — is a
    # different `art` and carries no state at all, so nothing has to work
    # out from POSITION which of them is live.
    #
    # Saved with no await between the history read above and here: this
    # row's place in the chat is what says which reports the prompt saw.
    #
    # A failed answer asked again has its row already, and the run goes on
    # in it: only its state changes here. What it holds stays as it is until
    # the repeated call has brought something (`went_on` below).
    platzhalter = (
        repositories.messages.run_again(retried.id) if retried is not None else None
    ) or repositories.messages.speichern(
        chat_id=chat.id,
        role="assistant",
        content="",
        zustand="laeuft",
        # A new answer that takes another one's place names it, so a hard
        # end of the service leaves the chat the way a stop by hand does
        # (app/db/repositories/messages.py, `beim_start_aufraeumen`).
        replaces_id=replaced.id if replaced is not None else None,
    )

    # The generator stays what it was — a sequence of events. What's new is
    # only who reads it: no longer the response to the browser, but the run.
    # That's why the generation now comes in as a parameter instead of from
    # the enclosing namespace.
    # The order the answer happens in, read off the very events the window
    # reads (app/answer_sections.py), so a reloaded answer is drawn as it
    # was streamed. Fed in `arbeit` below; read at both writes.
    sections = SectionLog()

    async def strom(generierung: Generierung) -> AsyncIterator[str]:
        # The summary row of a fold written down at the closing write belongs
        # to the OUTER frame: the fold check before the first request sets
        # this name, and the `done` event reads it. Assigned in here, the
        # name would be a local of this generator — a second writer beside
        # the outer one — so it is declared as the outer variable it is.
        nonlocal verdichtet_zu
        # The folders this run's tool calls may touch — the user's shared
        # ones plus this chat's own document folder, read once for the run
        # the way the system message read it (app/dokumentablage.py).
        werkzeugordner = dokumentablage.ordner_dieses_chats(
            app.state.config.datenverzeichnis,
            chat.working_dirs,
            chat.id,
            dokumentablage.program_folders(app.state.config),
        )
        # Calls refused the moment they began, by id: the reason is what the
        # model gets back as the call's result (see `tool_call_laeuft` below).
        fruehe_absagen: dict[str, str] = {}
        # A failed answer asked again starts with what it had already done
        # (app/answer_replay.py): the text and the thinking of its finished
        # rounds, their calls, and what belongs to them. Every other answer
        # starts empty.
        antwort_text: list[str] = [kept.content] if kept is not None and kept.content else []
        # The text of the round that is running, and nothing before it.
        # `antwort_text` above is the whole answer — what the window shows and
        # the row stores — and it is NOT what the model's history wants. An
        # assistant turn in that history carries what was said in that turn.
        # Handed the whole answer every round, the history held the opening
        # once per round, each copy longer than the last, and a small model
        # took that shape for the rule and wrote the answer from the top
        # again — measured: one row with its own first paragraph thirteen
        # times, 112k prompt tokens on a chat with two questions.
        runden_text: list[str] = []
        gedanke_text: list[str] = (
            [kept.reasoning] if kept is not None and kept.reasoning else []
        )
        kept_stats = (retried.stats or {}) if retried is not None else {}
        # Which of this answer's tool results the clearing replaced in the
        # request, and as which of the two sentences. It goes into the row at
        # the closing write and comes back in the NEXT request's rebuild, so
        # the run and the request after it read the same text
        # (app/verlaufsbau.py).
        geraeumte_ergebnisse: dict[str, str] = dict(kept_stats.get("geraeumt") or {})
        # The summary a fold INSIDE this answer produced, as it stands in the
        # request. It is written down as a row at the closing write, so the
        # next message continues folded instead of folding the same stretch
        # again (app/chatverdichtung.py).
        gefaltete_mitte: str | None = None
        # The thinking of the round that is running, and nothing before it —
        # the same cut `runden_text` makes for the text. It is what the one
        # swap at the end hands over when the answer stood only in the
        # thinking (app/reasoning.denktext_als_antwort): the thought the
        # answer ENDED on, not the deliberation of every tool round before
        # it. Filled in the very branch that fills `gedanke_text`, so it is
        # always that list's tail.
        runden_gedanke: list[str] = []
        messwerte: dict = {}
        werkzeugprotokoll: list[dict] = (
            [dict(call) for call in kept.calls] if kept is not None else []
        )
        # The report of a reached goal, if the `goal` tool was called
        # (app/tools/ziel_werkzeug.py). Kept alongside the tool log rather
        # than merged into the metrics as it happens: the metrics are still
        # being summed across rounds, and the one write in the `finally`
        # is where everything about this answer becomes final.
        ziel_bericht: str | None = kept_stats.get("ziel") if kept is not None else None
        # How much of the three the run started with. A repeated call that
        # has added to none of them has brought nothing yet, and until it
        # does the row is left as the failed answer it was.
        started_with = (len(antwort_text), len(gedanke_text), len(werkzeugprotokoll))

        def went_on() -> bool:
            return (
                len(antwort_text), len(gedanke_text), len(werkzeugprotokoll)
            ) != started_with

        abgebrochen = False
        fehlertext: str | None = None
        # Set when the provider answered that the request did not fit the
        # model's context (app/kontextvoll.py). The answer still ends as the
        # error it is; this is what puts the context-full heading over it.
        kontextfenster_voll = False
        # Set where the provider refused a request whose ANSWER LENGTH the
        # user set is as large as the whole window (app/kontextvoll.py). No
        # fold can help, so the answer ends and says what to change.
        antwortlaenge_zu_gross = False
        quelle = None
        # The context reading: what it stood at before this run, and what
        # was last sent out. The second one exists so an unchanged number
        # costs neither an event nor a write — a provider throttles by TIME
        # and can perfectly well repeat itself across a round boundary.
        letzter_gesamtstand: int | None = vorheriger_stand
        gemeldeter_stand: int | None = None
        # Whether a fold between rounds changed the request after the last
        # round that reported its own numbers: that round's count then
        # describes a longer request than the one the answer ends with, and
        # the reading of the folded request is the one to keep.
        folded_after_reading = False
        # When the live reading last went into the column. The stream reports
        # it about twice a second, and every write is a transaction of its
        # own with a sync behind it — on a ten-minute answer that was more
        # than a thousand commits for one integer whose only off-stream
        # reader is a window opening the chat cold. Written at the pace of
        # the text autosave instead; a round's end and the closing write
        # land the exact number regardless.
        letzte_standschrift = 0.0

        # Images from tool results (Recraft & co.): saved like the generated
        # images under data/images/, the message carries only the name —
        # the same display as in image mode, nothing new invented.
        # A picture the model DRAWS is not one of them: `draw_image` goes
        # the picture window's way, and the picture route writes it into
        # this answer's own run in the chat the moment it is finished
        # (app/tools/bild_werkzeug.py).
        werkzeug_bilder: list[str] = []

        def bild_senke(mime: str, daten_b64: str) -> str:
            # Named like every other image in the house (32 hex + extension) —
            # the delivery under /images/{name} checks exactly this pattern,
            # a custom prefix would fail it (found during Banane 3).
            endung = {
                "image/webp": ".webp",
                "image/png": ".png",
                "image/jpeg": ".jpg",
            }.get(mime)
            if endung is None:
                # Unknown kind: better the short note than a file that
                # would be delivered with a wrong declaration.
                raise ValueError(f"Unknown image type: {mime}")
            name = uuid4().hex + endung
            verzeichnis = ort(app.state.config, "images")
            verzeichnis.mkdir(parents=True, exist_ok=True)
            (verzeichnis / name).write_bytes(base64.b64decode(daten_b64))
            werkzeug_bilder.append(name)
            return name

        # Everything above lives in memory alone. The one write in the
        # `finally` below never runs when the process dies hard — an app
        # swap, a kill — and the placeholder stays empty: on 31.08. a whole
        # tool block and the answer text were lost exactly that way. So the
        # state so far is written along the way too.
        #
        # Called straight from the run, never from a timer task: a
        # background writer could fire AFTER the `finally` and put a half
        # state on top of a finished one. Sequential calls inside this one
        # coroutine cannot — the `finally` is always the last write.
        letzter_zwischenstand = 0.0

        def zwischenstand_sichern(erzwungen: bool = False) -> None:
            """The state so far into the placeholder — half, never broken.

            The same fields the final write uses, so what lands in the
            database reads like a normal answer that is merely shorter.
            """
            nonlocal letzter_zwischenstand
            if not (antwort_text or gedanke_text or werkzeugprotokoll):
                return
            # A failed answer asked again keeps everything it held — what
            # its failed call had begun to write included — until the
            # repeated call brings something to put in its place.
            if retried is not None and not went_on():
                return
            jetzt = time.monotonic()
            if not erzwungen and jetzt - letzter_zwischenstand < ZWISCHENSTAND_TAKT:
                return
            letzter_zwischenstand = jetzt
            # A copy: the metrics are still being summed across rounds, and
            # the tool log belongs in the stored state, not in the running
            # one the next round merges into.
            stand = dict(messwerte or {})
            if werkzeugprotokoll:
                stand["werkzeuge"] = werkzeugprotokoll
            if ziel_bericht:
                stand["ziel"] = ziel_bericht
            text_so_far = "".join(antwort_text)
            reasoning_so_far = "".join(gedanke_text)
            # Not the final write: a stretch still running stays without an end.
            order = sections.stored(text_so_far, reasoning_so_far, final=False)
            if order:
                stand["sections"] = order
            repositories.messages.inhalt_aktualisieren(
                platzhalter.id,
                content=text_so_far,
                reasoning=reasoning_so_far or None,
                stats=stand,
                bild=werkzeug_bilder[-1] if werkzeug_bilder else None,
            )

        def stand_verbuchen(stand: int | None, *, endgueltig: bool) -> str | None:
            """One reading of the context, on its way to the window and the row.

            The round's end and the live stream both report one; this is
            what a report costs, written once for both. Nothing goes out
            for a reading that did not change. The row is written at the
            autosave's pace for a live reading and always for a round's
            own number (``endgueltig``), which is the best there will ever
            be for that round. Returns the event to yield, or None.
            """
            nonlocal gemeldeter_stand, letzte_standschrift
            if stand is None or stand == gemeldeter_stand:
                return None
            gemeldeter_stand = stand
            jetzt = time.monotonic()
            if endgueltig or jetzt - letzte_standschrift >= ZWISCHENSTAND_TAKT:
                letzte_standschrift = jetzt
                repositories.messages.tokenstand_setzen(platzhalter.id, stand)
            return _sse("kontext", message_id=platzhalter.id, gesamt_tokens=stand)

        # The history above was built from the chat's rows, and the report
        # of every background run that had ended by then is one of them:
        # from here on the model has read it. Said on the chat's stream, so
        # the card of the call that started the run can stop pulsing. Only
        # those runs — one that ended between the read and here has its
        # report in no request yet.
        hintergrund.laeufe.als_gelesen_melden(chat.id, gelesene_laeufe)

        yield _sse(
            "start",
            generation_id=generierung.id,
            message_id=platzhalter.id,
            chat_id=chat.id,
            endpoint_id=endpoint_id,
        )
        if kept is not None:
            # A failed answer asked again: what its run had done, said again
            # as the events it was first said in. The window empties the row
            # at `start` and draws it from these, the answer's order is
            # counted from them (`sections`), and a window attaching later
            # finds them in the run's buffer.
            for event in answer_replay.events(kept, goal=ziel_bericht):
                yield _sse(event.pop("typ"), **event)

        # Once per chat and folder, decided by `melden` itself — a warning
        # that repeats at every sentence is not a warning. A file over the
        # line eats the context of every single request, and until now the
        # only place that said so was the log.
        for notiz in zu_grosse_notizen:
            yield _sse(
                "exemd_zu_gross",
                ordner=notiz.ordner,
                zeichen=notiz.zeichen,
            )

        # What a refusal of this answer brought its ceiling down to: an
        # output limit the provider named binds the retry and every tool
        # round after it, so a provider is not turned down once per round for
        # the same number; a ceiling one round's input led to binds that
        # round's retries. Never on the endpoint state another chat, job or
        # fold at the same address reads (app/antwortgrenze.py `Zug`).
        zug = antwortgrenze.Zug()
        # What the request that went out last carried of the thinking stage:
        # its fields and the stage word. A refusal is read against these, not
        # against what was picked — a lowered ceiling can send "off" where a
        # stage was picked (app/sent_stage.py).
        last_sent: dict[str, Any] = {}

        async def faltend_streamen(runde: int) -> AsyncGenerator:
            """One round of this answer, sent again for as long as the
            provider calls it too long — at most ``kontextvoll.FALTVERSUCHE``
            attempts, each either a lower answer ceiling or a forced fold
            (``kontextvoll.abhilfe``).

            EVERY round, not only the first. A server that refuses the
            ceiling it was sent refuses it again in round 1, and until now
            only round 0 was ever lowered: the second request went out with
            the setting's own number, was refused at once, and the answer
            ended with the context-full card while the same cure stood ready
            one round earlier. A job has had the per-round cure all along
            (``app/api/v1/auftraege.py``), so this is that one way, not a
            second one.

            A lower ceiling goes on a copy of the request. The holder of the
            answer keeps it (``zug``): one the window and the input led to
            for the retries of this round, an output limit the refusal named
            for every later send and round of the answer. The setting and
            the stored values keep the ceiling they had.

            Each fold step keeps less of the history word for word
            (``kontextvoll.faltbudget``). A step that folds nothing moves
            straight on to the next, smaller one without sending the refused
            request again: with no known window the first budget is the
            ceiling, and a small model's whole history can fit inside it.
            The request goes out again only after a fold that went through.

            WHERE it folds is the one thing the round decides. In round 0 the
            whole history is rows, so the fold is written down and the request
            is built again from them. From round 1 on the history also carries
            this answer's own tool rounds, which are not rows and never will
            be — those fold in memory, the way a job folds its own list, and
            nothing of them is written down mid-answer.

            A fold whose summary failed folds nothing and books a pause
            (app/faltpause.py), and no further step of the round follows:
            each one would sit inside that pause. The same holds for a step
            that could not ask at all (no room to write a summary in) and
            for one whose summary saved nothing — only a step that found no
            middle at its budget moves on to a smaller one. A refusal after
            it ends the answer.

            Only while nothing has arrived. A refusal after the first chunk
            is not handled here: half an answer is already in the stream and
            a fold cannot unsay it. Whatever is not cured — no middle at any
            step, the attempts used up, nothing left free for an answer, a
            fold step that already ended without a summary — goes on as the
            error it was, and the context-full heading goes over it. A stop
            pressed while folding ends the answer as the stop it is.
            """
            nonlocal verdichtet_zu, letzter_gesamtstand, abgebrochen
            nonlocal antwortlaenge_zu_gross
            gesendet = zeilen
            # Set once a fold step of this answer ended without folding
            # anything a smaller step could still fold: the summary failed,
            # a pause was running, there was no room to write one in, or it
            # saved nothing. No further fold step follows.
            notfall_gefaltet = False
            grundbudget = verdichtung.schwanz_budget(
                zustand.context_tokens,
                verdichtungswahl.schwelle(repositories, modell=endpoint_id, chat=chat.id),
            )
            versuche = 0
            faltungen = 0
            zug.round_begins()
            # The one repeat of a turn whose stage was the program's choice
            # and the server refused (below).
            retried_without_thinking = False

            async def im_speicher_falten() -> bool:
                """The same fold, on the list in memory — the step a round
                past the first takes. ``True`` where something really shrank.

                Nothing is written down here, and nothing may be: this round's
                own tool calls and their results are not rows, and the answer
                is still being written. The fold is exactly the one a job does
                to its own list every round (``app/verdichtung.py``), with the
                same counters and the same shrinking budget as the rows path
                below, so a round cannot fold more often than ``FALTVERSUCHE``
                whichever of the two it took.
                """
                nonlocal versuche, faltungen, notfall_gefaltet
                nonlocal letzter_gesamtstand
                gefaltet = False
                while (
                    not gefaltet
                    and not notfall_gefaltet
                    and versuche < kontextvoll.FALTVERSUCHE
                    and not generierung.soll_abbrechen
                ):
                    versuche += 1
                    faltungen += 1
                    log.info(
                        "Chat %s: forced fold in memory (attempt %d/%d)",
                        chat.id,
                        versuche,
                        kontextvoll.FALTVERSUCHE,
                    )
                    try:
                        ergebnis = await verdichtung.verdichten(
                            zustand,
                            anfrage,
                            kontextvoll.faltbudget(grundbudget, faltungen),
                            schluessel=chat.id,
                            erzwungen=True,
                            einstellungen=repositories.einstellungen,
                            endpoint_id=refusal_id,
                            stopp=generierung.signal,
                        )
                    except Exception:  # noqa: BLE001 - a failed fold ends in the card, not a crash
                        log.warning(
                            "Chat %s: forced fold in memory failed", chat.id, exc_info=True
                        )
                        notfall_gefaltet = True
                        break
                    gefaltet = ergebnis.angewendet
                    # Only a step that found no middle at its budget leaves a
                    # smaller one something to fold.
                    notfall_gefaltet = not gefaltet and not ergebnis.keine_mitte
                if gefaltet:
                    # The reading the next estimate builds on described the
                    # longer prompt. Dropped rather than corrected, the same
                    # as after a fold of the rows: the round about to go out
                    # brings its own count back within seconds, and a stale
                    # high number would keep the round-end check firing
                    # against room that was just freed.
                    letzter_gesamtstand = None
                return gefaltet

            async def falten() -> bool:
                """One fold of this answer's history, and the request rebuilt
                from what is left. ``True`` where something really shrank.

                Both ways into this loop end here: a request the provider
                called too long, and one this side can see will not fit
                before it is sent at all. The step is the same either way —
                that is the point of folding without the detour over the
                server — so it stands once.

                Past the first round the history is no longer rows alone, so
                the fold happens in memory instead; everything around it —
                the counters, the budget, when a step is the last one — is
                the same either way.
                """
                nonlocal versuche, faltungen, gesendet, notfall_gefaltet
                nonlocal verdichtet_zu, letzter_gesamtstand
                if runde:
                    return await im_speicher_falten()
                gefaltet: str | None = None
                while (
                    not gefaltet
                    and not notfall_gefaltet
                    and versuche < kontextvoll.FALTVERSUCHE
                    and not generierung.soll_abbrechen
                ):
                    versuche += 1
                    faltungen += 1
                    log.info(
                        "Chat %s: forced fold (attempt %d/%d)",
                        chat.id,
                        versuche,
                        kontextvoll.FALTVERSUCHE,
                    )
                    try:
                        gefaltet, ergebnis = await chatverdichtung.erzwungen_verdichten(
                            zustand=zustand,
                            repositories=repositories,
                            chat=chat,
                            endpoint_id=endpoint_id,
                            modellname=modellname,
                            zeilen=gesendet,
                            budget=kontextvoll.faltbudget(grundbudget, faltungen),
                            dokumentplan=dokumentplan,
                            offers_tools=bool(angebot),
                            stopp=generierung.signal,
                            config=app.state.config,
                        )
                    except Exception:  # noqa: BLE001 - a failed fold ends in the card, not a crash
                        log.warning("Chat %s: forced fold failed", chat.id, exc_info=True)
                        notfall_gefaltet = True
                        break
                    # The same rule as the fold in memory above.
                    notfall_gefaltet = not gefaltet and not ergebnis.keine_mitte
                if not gefaltet:
                    return False
                # Written: the next send builds the system message anew,
                # the same as after the fold before an answer.
                forget_system_message(chat.id)
                # The request again, from the rows as they stand now, by
                # the same rule the first read kept: everything written
                # before this answer's placeholder, nothing from it on —
                # neither the placeholder itself nor a background report
                # that landed after it. Not "what the first read held":
                # past the reading's cap that read carried a gap notice,
                # and the rows behind it come back once the fold brings
                # the count down. Filtered by that first read they would
                # be left out without a word; read fresh, they travel, or
                # a new notice stands for them.
                frisch = repositories.messages.fuer_das_modell(chat_id=chat.id)
                kennungen = [z.id for z in frisch]
                if platzhalter.id in kennungen:
                    gesendet = frisch[: kennungen.index(platzhalter.id)]
                else:
                    gesendet = [z for z in frisch if z.created_at < platzhalter.created_at]
                if replaced is not None:
                    # Still without the answer this one replaces, as the
                    # first read left it out.
                    gesendet = [z for z in gesendet if z.id != replaced.id]
                # The block before this request is built, and on the row: the
                # fold just swallowed the row that carried it, so the newest
                # user row left — the question being answered — is the one the
                # block goes out with from here on. Every later round of this
                # answer would otherwise run without a date.
                #
                # Only where this request carried one at all: "send again"
                # builds a history without a block, and handing one to an
                # older row here would change a turn that has gone out without
                # one all along — the next request would hand that row back
                # with a date it never carried, and every request after it
                # would read the history again from that row on.
                if block_in_request and _restore_environment_block_on_rows(
                    repositories, gesendet, block
                ):
                    _block_went_back(chat)
                anfrage.nachrichten = _verlauf_bauen(
                    chat,
                    repositories,
                    systemtext,
                    config=app.state.config,
                    vision=zustand.kann("vision"),
                    zeilen=gesendet,
                    werkzeuge=bool(angebot),
                    dokumentplan=dokumentplan,
                    gespraechsanweisung=turn_prefix,
                )
                # The window fetches the fold at the end, and the reading
                # the next estimate builds on described the longer prompt.
                verdichtet_zu = gefaltet
                letzter_gesamtstand = None
                log.info(
                    "Chat %s: the request is built again after a fold (attempt %d/%d, "
                    "%d messages)",
                    chat.id,
                    versuche,
                    kontextvoll.FALTVERSUCHE,
                    len(anfrage.nachrichten),
                )
                return True

            while True:
                # Before the request goes out at all: does Auto still leave
                # room for an answer? Where it does not, the ceiling worked
                # out above is not a ceiling but the bare edge — and a
                # request carrying it is the one failure with no way back.
                # The server does not refuse it; it answers with a single
                # token. Nothing reads that as a problem, so neither the
                # lowering nor the fold below would ever run, and the user
                # is handed a word and a half with nothing saying why.
                #
                # So the same cure a refusal gets, without the detour over
                # the server: fold, then ask the arithmetic again. Not once
                # a refusal lowered the ceiling of this round (`zug`) — that
                # number came out of a refusal and is the one being tried —
                # and not after a fold step that ended without a summary,
                # which is where every other path stops folding too.
                while (
                    zug.round_tokens is None
                    and not notfall_gefaltet
                    and antwortgrenze.reicht_nicht(
                        eingestellte_grenze,
                        antwortgrenze.geltender_deckel(zustand, anfrage.modell, zug),
                        zustand.context_tokens or 0,
                        antwortgrenze.eingabe_schaetzen(
                            anfrage.nachrichten, anfrage.werkzeuge
                        ),
                        anthropic=antwortgrenze.anthropic_draht(zustand),
                    )
                ):
                    log.info(
                        "Chat %s: the input leaves no room for an answer, folding "
                        "before the request goes out",
                        chat.id,
                    )
                    if not await falten():
                        # Nothing left to fold, or the attempts are used up.
                        # The request goes out with the edge rather than not
                        # at all — and the answer it comes back with says
                        # that it stopped at the ceiling
                        # (app/antwortende.py), which is the one thing that
                        # must never be missing.
                        log.info(
                            "Chat %s: nothing left to fold, the request goes out with "
                            "the smallest ceiling there is",
                            chat.id,
                        )
                        break
                    if generierung.soll_abbrechen:
                        break
                    # Folded: the input is smaller, so both numbers of this
                    # request are worked out again from it — the same pair
                    # the round loop resolves together, for the same reason.
                    anfrage.max_tokens = antwortgrenze.aufloesen(
                        eingestellte_grenze,
                        antwortgrenze.geltender_deckel(zustand, anfrage.modell, zug),
                        zustand.context_tokens or 0,
                        antwortgrenze.eingabe_schaetzen(anfrage.nachrichten, anfrage.werkzeuge),
                        anthropic=antwortgrenze.anthropic_draht(zustand),
                    )
                    anfrage.zusatz = stufe_zusatz(anfrage.max_tokens)
                if generierung.soll_abbrechen:
                    abgebrochen = True
                    return
                # The block again in front of the newest user turn, where a
                # fold of this answer's history took the turn that carried it.
                # Asked here because every send of this answer passes this
                # line: the first one, each round after a tool result, and
                # each repeat after a fold or a lowered ceiling — a fold above
                # (the check before sending) and one below (the provider's own
                # refusal) both end here. A fold in memory writes no row the
                # block could be handed to, so the request is the only place
                # left (app/grundprompt.restore_environment_block).
                if block_in_request and grundprompt.restore_environment_block(
                    anfrage.nachrichten, block
                ):
                    _block_went_back(chat)
                # Every send of this answer goes out with no more than the
                # ceiling a refusal brought it down to: the retry, a send
                # after a fold, and every round after it.
                out_request = kontextvoll.mit_grenze(
                    anfrage,
                    antwortgrenze.forced_ceiling(anfrage.max_tokens, zug),
                    zustand,
                )
                last_sent["zusatz"] = out_request.zusatz
                last_sent["stufe"] = sent_stage.sent_stage(
                    denkstufe,
                    anfrage.zusatz,
                    out_request.zusatz,
                    denkschalter.aus_wort(zustand, modell=anfrage.modell),
                )
                innen = zustand.provider.streamen(out_request)
                angekommen = False
                try:
                    async for stueck in innen:
                        angekommen = True
                        yield stueck
                    return
                except ProviderFehler as fehler:
                    # A spoken turn's stage is the program's choice, not the
                    # user's, and so is the default an unknown host is sent
                    # where nobody picked one: refused, it is written down
                    # and the same turn goes out once more at once without a
                    # thinking field, instead of ending on an error. Once per
                    # round; the rounds
                    # after it read the refusal from the list.
                    if (
                        not angekommen
                        and retry_without_stage
                        and not retried_without_thinking
                        and denkablehnung.lernen(
                            repositories.einstellungen, refusal_id, fehler,
                            last_sent["zusatz"], last_sent["stufe"], route=think_route,
                        )
                    ):
                        retried_without_thinking = True
                        if field_default:
                            # Nothing but the plain field was ever known about
                            # this host, and it refused the default: the field
                            # itself is refused. Every stage of it goes on the
                            # list, so no later turn sends it and none needs
                            # a repeat.
                            denkablehnung.refuse_all(
                                repositories.einstellungen, refusal_id, denkprofil.stufen
                            )
                        denken_abgelehnt[:] = denkablehnung.gemerkt(
                            repositories.einstellungen, refusal_id
                        )
                        # Without the stage, but with the fields this
                        # model's route always gets: they say where the
                        # thinking is delivered, not whether there is any.
                        anfrage.zusatz = dict(think_route)
                        log.info(
                            "Chat %s: the thinking stage %r was refused, "
                            "sending the turn once more without one",
                            chat.id,
                            denkstufe,
                        )
                        continue
                    # Asking also learns: both halves of the request take what
                    # the refusal names (app/ablehnungslernen.py).
                    if angekommen or not ablehnungslernen.fenster_voll(
                        repositories, zustand, fehler, zug
                    ):
                        raise
                    # What the request weighs: the one refusal that names the
                    # ceiling and the window without the input is answered
                    # from it (kontextvoll.abhilfe), and a fold below is
                    # measured against it.
                    estimated_input = antwortgrenze.eingabe_schaetzen(
                        anfrage.nachrichten, anfrage.werkzeuge
                    )
                    weg, frei = kontextvoll.abhilfe(
                        fehler,
                        eingestellte_grenze=eingestellte_grenze,
                        fenster=zustand.context_tokens,
                        input_tokens=estimated_input,
                    )
                    if weg == kontextvoll.LIMIT_TOO_LARGE:
                        # The answer length somebody set is as large as the
                        # whole window: folding three times would cost three
                        # summaries and change nothing. The
                        # answer ends here and says what to do about it.
                        log.info(
                            "Chat %s: the set answer length is too large for this "
                            "model, not retrying",
                            chat.id,
                        )
                        antwortlaenge_zu_gross = True
                        raise
                    if weg == kontextvoll.KARTE:
                        # The answer's ceiling fills the window on its own
                        # and the input leaves nothing free for an answer:
                        # no fold makes room and no lower ceiling helps.
                        log.info(
                            "Chat %s: the input leaves no room for an answer, not retrying",
                            chat.id,
                        )
                        raise
                    if weg == kontextvoll.GRENZE:
                        if versuche >= kontextvoll.FALTVERSUCHE:
                            raise
                        versuche += 1
                        zug.lower_round(frei)
                        log.info(
                            "Chat %s: answer ceiling lowered to %d for this request (attempt %d/%d)",
                            chat.id,
                            zug.held(),
                            versuche,
                            kontextvoll.FALTVERSUCHE,
                        )
                        continue
                    if notfall_gefaltet:
                        # A fold step of this answer already ended without a
                        # summary, and the request went out as it was and
                        # came back refused. Every further step would end the
                        # same way — inside the pause that failure booked,
                        # with no room to write a summary in, or with another
                        # summary that saves nothing — so the answer ends
                        # here.
                        log.info(
                            "Chat %s: the fold ended without a summary, "
                            "the answer ends",
                            chat.id,
                        )
                        raise
                    log.info(
                        "Chat %s: provider called the request too long, folding",
                        chat.id,
                    )
                    vor_der_faltung = estimated_input
                    gefaltet = await falten()
                    if generierung.soll_abbrechen:
                        abgebrochen = True
                        return
                    if not gefaltet:
                        log.info("Chat %s: nothing left to fold, the answer ends", chat.id)
                        raise
                    # Folded: a ceiling a refusal brought this round down to
                    # was the room left beside the input before the fold.
                    # The room grew by what the fold freed, and the request's
                    # own ceiling is worked out again from what is left.
                    zug.input_folded(
                        vor_der_faltung
                        - antwortgrenze.eingabe_schaetzen(anfrage.nachrichten, anfrage.werkzeuge)
                    )
                    anfrage.max_tokens = antwortgrenze.aufloesen(
                        eingestellte_grenze,
                        antwortgrenze.geltender_deckel(zustand, anfrage.modell, zug),
                        zustand.context_tokens or 0,
                        antwortgrenze.eingabe_schaetzen(anfrage.nachrichten, anfrage.werkzeuge),
                        anthropic=antwortgrenze.anthropic_draht(zustand),
                    )
                    anfrage.zusatz = stufe_zusatz(anfrage.max_tokens)
                finally:
                    await innen.aclose()

        try:
            # An attempt at the end of a round that did not actually shrink
            # the history means the genuine middle is gone: every further
            # round of this answer would only summarize the previous summary,
            # costing a request each time for nothing. Once that happens the
            # FOLD stops for the rest of THIS answer — the free step before it
            # keeps running, and the next answer is built from rows again and
            # gets its own chance. The same brake, under the same name, that a
            # job keeps for its whole run (app/api/v1/auftraege.py).
            verdichtung_abgeschaltet = False

            # One pass per tool round: the model requests, we execute, the
            # result goes back, the model keeps writing. Bounded so that a
            # model doesn't go in circles.
            #
            # The bound counts the rounds of this request, as it does for
            # every request. A failed answer asked again goes on behind the
            # rounds it had finished: their numbers stay taken in the log
            # (`stored_round`), and the request carries them, so a fold of
            # it happens in memory like any round past the first.
            first_round = kept.next_round if kept is not None else 0
            for runde in range(max_werkzeug_runden + 1):
                stored_round = first_round + runde
                aufrufe: list = []
                runden_text = []
                runden_gedanke = []
                # Whether this round has written a visible character yet: its
                # first one is set a blank line below the text of the rounds
                # before (app/reasoning.paragraph_break).
                round_wrote_visible = False
                # This round's finished items on OpenAI's Responses wire,
                # handed back in the next round and nowhere else
                # (app/providers/openai_responses.py).
                runden_teile: list[dict] = []
                # This round's content blocks on the Anthropic wire, in the
                # order the answer brought them, handed back in the next round
                # and nowhere else (app/providers/anthropic.py).
                round_blocks: list[dict] = []
                # The folder check at the start of a call
                # (app/werkzeugvorpruefung.py). It only checks: the chat's
                # own folder is made when a call runs, not while the model
                # is still writing it.
                vorpruefung = werkzeugvorpruefung.Vorpruefung(
                    werkzeugordner,
                    werkzeugvorpruefung.angebotene_namen(anfrage.werkzeuge),
                    app.state.config.datenverzeichnis,
                )
                # The ceiling for THIS round. Every round is its own request,
                # and each one carries more than the last: a round's tool
                # calls and their results join the history. Under "Auto" the
                # ceiling is what is left of the window, so a ceiling worked
                # out for the first round and kept would, from the second one
                # on, claim room the input has meanwhile taken — and a server
                # that adds the two up (llama.cpp, vLLM, Anthropic) refuses
                # exactly that. The same one calculation, asked again.
                #
                # The thinking budget is resolved from the same number, in
                # the same breath: the Anthropic generation that wants one
                # wants it below the ceiling, and a budget left over from a
                # larger ceiling would be refused with it.
                #
                # What a refusal of an earlier round of this answer named is
                # read here too (`zug`), the same as the job path's rounds
                # (app/antwortgrenze.py `Zug`); a number somebody set is
                # brought down to it where the request goes out
                # (`faltend_streamen`).
                anfrage.max_tokens = antwortgrenze.aufloesen(
                    eingestellte_grenze,
                    antwortgrenze.geltender_deckel(zustand, anfrage.modell, zug),
                    zustand.context_tokens or 0,
                    antwortgrenze.eingabe_schaetzen(anfrage.nachrichten, anfrage.werkzeuge),
                    anthropic=antwortgrenze.anthropic_draht(zustand),
                )
                anfrage.zusatz = stufe_zusatz(anfrage.max_tokens)
                # Every round may fold or lower its ceiling and go out again
                # (see above) — the round number only decides whether that
                # fold is written onto rows or happens in memory.
                quelle = faltend_streamen(stored_round)

                while True:
                    # Not a plain ``async for``: a server that has gone
                    # quiet but not closed the connection (nothing but bare
                    # keepalives, no real Stueck) would otherwise leave this
                    # waiting for the next piece forever, past the point a
                    # stop was pressed — the check right below never runs
                    # again because nothing ever wakes it. This lets a stop
                    # win the race even then, and closes the connection to
                    # the server doing it (Generierung.naechstes_stueck).
                    stueck, abbruch_hat_gewonnen = await generierung.naechstes_stueck(quelle)
                    if stueck is None:
                        abgebrochen = abbruch_hat_gewonnen
                        break

                    if stueck.sorte == "content":
                        # A round's first visible text stands one blank line
                        # below the rounds before it. The break is part of
                        # the round's own text as well: the event carries it,
                        # so the window and the stored section lengths
                        # (app/answer_sections.py) count the very text the
                        # row stores, and the rounds joined are still that
                        # text — the next request finds them in it and
                        # rebuilds the turns as they went out
                        # (app/verlaufsbau.py, `_werkzeugzuege`).
                        piece = stueck.text
                        if not round_wrote_visible and piece.strip():
                            round_wrote_visible = True
                            piece = (
                                reasoning.paragraph_break("".join(antwort_text), piece) + piece
                            )
                        antwort_text.append(piece)
                        runden_text.append(piece)
                        yield _sse("content", text=piece)
                    elif stueck.sorte == "reasoning":
                        gedanke_text.append(stueck.text)
                        runden_gedanke.append(stueck.text)
                        yield _sse("reasoning", text=stueck.text)
                    elif stueck.sorte == "stats":
                        folded_after_reading = False
                        messwerte = _messwerte_mergen(
                            messwerte, stueck.daten, wrote_text=round_wrote_visible
                        )
                        # The round is over, and its own numbers are the
                        # best there will ever be for it. Whatever estimate
                        # was reported while it ran gets replaced here, and
                        # the result is what the NEXT round estimates its
                        # prompt from.
                        #
                        # Normalized the same way the final write below and
                        # a job's per-round reading do it. Where that finds
                        # nothing — a llama.cpp asked for no usage block —
                        # the round's own stats go through the same estimate
                        # as the live readings rather than the reading
                        # freezing until the answer ends.
                        genau = _ganzer_stand(stueck.daten)
                        stand = (
                            genau
                            if genau is not None
                            else _kontextstand(
                                {
                                    "prompt_tokens": stueck.daten.get("prompt_tokens"),
                                    # Whole where the provider read both
                                    # halves of the prompt, as it does live;
                                    # a floor where it named one.
                                    "prompt_genau": bool(stueck.daten.get("prompt_genau")),
                                    # Everything the model produced, thinking
                                    # included, not the answer's pieces the
                                    # speed is counted from.
                                    "erzeugte_tokens": stueck.daten.get(
                                        "kontext_erzeugte_tokens"
                                    )
                                    or stueck.daten.get("erzeugte_tokens"),
                                },
                                letzter_gesamtstand,
                            )
                        )
                        if stand is not None:
                            letzter_gesamtstand = stand
                        meldung = stand_verbuchen(stand, endgueltig=True)
                        if meldung:
                            yield meldung
                    elif stueck.sorte == "kontext":
                        # How full the context is, WHILE the answer is being
                        # written — until now this only ever went out with
                        # the `stats` event, one line before `done`, so the
                        # bar in the window stood still for the entire
                        # answer and then jumped.
                        #
                        # Already throttled where it is sent
                        # (KontextDrossel), so this is roughly two events a
                        # second, not one per token. Sent every time; written
                        # to the row at the autosave's pace: a window that
                        # opens the chat cold mid-run reads the row, not the
                        # stream, and a reading a few seconds old serves it
                        # as well as a fresh one. `tokenstand_setzen` touches
                        # that one column alone so it cannot lose a
                        # concurrent text write.
                        meldung = stand_verbuchen(
                            _kontextstand(stueck.daten, letzter_gesamtstand),
                            endgueltig=False,
                        )
                        if meldung:
                            yield meldung
                    elif stueck.sorte == "tool_call_laeuft":
                        # A tool call is only complete at the end of the
                        # stream, so a model writing a long argument means
                        # minutes in which data flows and the window shows
                        # nothing at all (measured: 2.5 to 3 minutes at 17
                        # token/s for an 8804-character argument). The
                        # providers were already sending this; the switch
                        # simply did not know the kind, so it fell through
                        # to nobody. Already throttled where it is sent
                        # (WerkzeugFortschrittsDrossel), so this is a
                        # handful of events per call, not thousands.
                        yield _sse("tool_call_laeuft", **stueck.daten)
                        # The folder check, as soon as a call that works in
                        # the folders begins — not only once its argument is
                        # complete (app/werkzeugvorpruefung.py). Failing, the
                        # stream is cut here and the call answered with the
                        # reason right away.
                        if vorpruefung.beginnt(stueck.daten):
                            break
                    elif stueck.sorte == "denktempo":
                        # A live speed while the model is still thinking, not
                        # only once the round ends and `stats` names one.
                        # Already throttled where it is sent,
                        # and never folded into the window's own weighted
                        # reading of finished runs — a thinking-only figure
                        # is not a finished run.
                        yield _sse("denktempo", **stueck.daten)
                    elif stueck.sorte == "response_item":
                        runden_teile.append(stueck.daten["eintrag"])
                    elif stueck.sorte == "anthropic_block":
                        round_blocks.append(stueck.daten["block"])
                    elif stueck.sorte == "tool_call":
                        aufrufe = stueck.werkzeugaufrufe
                    elif stueck.sorte == "error":
                        fehlertext = stueck.text

                    # Throttled: while text is streaming, the answer grows a
                    # few words per second and the last few seconds are what
                    # a hard death costs.
                    zwischenstand_sichern()

                await quelle.aclose()
                quelle = None

                # A call cut short by the folder check stands in the history
                # as the call it began as, with no argument, and its result
                # is the reason — the model reads it and can answer it.
                if vorpruefung.absage is not None and not abgebrochen:
                    ersatz, ersatz_grund = vorpruefung.ersatz()
                    fruehe_absagen[ersatz.id] = ersatz_grund
                    aufrufe = [ersatz]

                if abgebrochen or not aufrufe:
                    break

                if runde >= max_werkzeug_runden:
                    fehlertext = t("fehler.werkzeug_grenze", sprache, anzahl=max_werkzeug_runden)
                    break

                # What the model requested goes into the history — with the
                # text of THIS round, not the whole answer so far (see
                # `runden_text` above). The earlier rounds already stand in
                # the history, each in its own turn, followed by its results.
                denkteile, textteile = openai_responses.rundenteile(runden_teile)
                # The round's blocks on Anthropic's wire, for the log: only
                # where it thought, and then all of them in the order they
                # came — a thinking block is handed back whole and in its
                # place, the markers of text and calls say where it was.
                stored_blocks = (
                    list(round_blocks)
                    if any(b.get("type") in THINKING_BLOCKS for b in round_blocks)
                    else []
                )
                anfrage.nachrichten.append(
                    ChatNachricht(
                        role="assistant",
                        content="".join(runden_text),
                        werkzeugaufrufe=aufrufe,
                        reasoning_items=denkteile,
                        message_items=textteile,
                        anthropic_blocks=round_blocks,
                    )
                )

                # Where the round's own answer ends in `anfrage.nachrichten` —
                # remembered here, right after it and before the tool calls
                # below add anything, so the check at the end of the round can
                # tell what arrived AFTER `letzter_gesamtstand` was read from
                # everything that was already inside it, the answer itself
                # included.
                laenge_nach_antwort = len(anfrage.nachrichten)

                # Pictures this round's tools want the model to LOOK at
                # (app/werkzeugbild.py). Collected for the whole round and
                # handed over after it: a call and its result have to stay
                # adjacent, so nothing may be pushed in between them.
                gelesene_bildnamen: list[str] = []
                gelesene_bild_urls: list[str] = []
                # Where each picture came from, so a request that retires it
                # later can say where to read it again (app/werkzeugbild.py).
                gelesene_bildpfade: list[str] = []

                def modellbild(name: str, daten_url: str, pfad: str = "") -> None:
                    gelesene_bildnamen.append(name)
                    gelesene_bild_urls.append(daten_url)
                    gelesene_bildpfade.append(pfad)

                # … then it is executed and the result handed back.
                for aufruf in aufrufe:
                    # Before each call, not after it: a tool can run for a
                    # minute or wait on a click, and the three branches below
                    # each leave the loop their own way. Saving on entry
                    # catches every result of this round except the last —
                    # and the save after the loop catches that one.
                    zwischenstand_sichern(erzwungen=True)
                    # Confirmation-requiring tools first: the question is asked
                    # before 'tool_call' is reported — otherwise the window
                    # would say "running" while in truth nobody has agreed yet.
                    abgelehnt: str | None = None
                    # The English twin of `abgelehnt`: what a tool result
                    # says is read by the model, never by the person at the
                    # window — so this one stays English no matter what
                    # `sprache` says, while `abgelehnt` keeps showing the
                    # window its own language.
                    abgelehnt_modell: str | None = None
                    # Refused while it was still being written: there is
                    # nothing to confirm and nothing to run. The reason is
                    # the tool's own English sentence, for both sides.
                    frueh_grund = fruehe_absagen.get(aufruf.id)
                    if frueh_grund is not None:
                        abgelehnt = abgelehnt_modell = frueh_grund
                    elif registry is not None and registry.braucht_bestaetigung(
                        aufruf.name, aufruf.argumente, werkzeugordner
                    ):
                        # Why this one is being asked about. Without it the
                        # prompt shows a command and expects trust; with it
                        # the decision rests on something visible.
                        # The tool names its own sentence — the shell speaks
                        # of paths outside the shared folders, the memory of
                        # the rule about to be stored. Picking one sentence
                        # for all of them announced a memory entry as if it
                        # were a stray file path.
                        anlass = registry.bestaetigungsgrund(
                            aufruf.name, aufruf.argumente, werkzeugordner
                        )
                        # This sentence has one reader, the window, and it
                        # stands in the window's language (`sprache` below).
                        yield _sse(
                            "tool_confirm",
                            name=_display_name(registry, aufruf.name),
                            argumente=aufruf.argumente,
                            grund=(
                                t(anlass[0], sprache, **{anlass[1]: anlass[2]})
                                if anlass
                                else ""
                            ),
                            # The bare value as well, so the window can set
                            # the path in monospace inside the sentence.
                            grund_wert=anlass[2] if anlass else "",
                            aufruf_id=aufruf.id,
                        )
                        entscheidung = await _auf_entscheidung_warten(
                            generierung, aufruf.id, aufruf.name
                        )
                        if entscheidung is None:
                            if generierung.soll_abbrechen:
                                abgebrochen = True
                                break
                            abgelehnt = t(
                                "fehler.werkzeug_unbeantwortet",
                                sprache,
                                name=_display_name(registry, aufruf.name),
                            )
                            abgelehnt_modell = t(
                                "fehler.werkzeug_unbeantwortet", "en", name=aufruf.name
                            )
                        elif entscheidung is False:
                            log.info("Tool '%s' was declined", aufruf.name)
                            abgelehnt = t(
                                "fehler.werkzeug_abgelehnt",
                                sprache,
                                name=_display_name(registry, aufruf.name),
                            )
                            abgelehnt_modell = t(
                                "fehler.werkzeug_abgelehnt", "en", name=aufruf.name
                            )
                        elif isinstance(entscheidung, str):
                            # A no that carries the user's own words: what
                            # to do instead. The tool does not run, and the
                            # words travel to the model with the refusal. A
                            # string must never fall through to the run
                            # below — it is not a yes.
                            log.info("Tool '%s' was declined with a message", aufruf.name)
                            abgelehnt = t(
                                "fehler.tool_declined_with_words",
                                sprache,
                                name=_display_name(registry, aufruf.name),
                                text=entscheidung,
                            )
                            abgelehnt_modell = t(
                                "fehler.tool_declined_with_words",
                                "en",
                                name=aufruf.name,
                                text=entscheidung,
                            )

                    # A registry that does not exist at all (the feature is
                    # off) is the same outer refusal as Tor 3 — computed
                    # here rather than inside ``_werkzeug_ausfuehren`` so it
                    # gets the same English/window split as the two refusals
                    # above. ask_user and start_job need no registry at all
                    # and are excluded: they run their own way below
                    # regardless of whether one exists.
                    if (
                        registry is None
                        and abgelehnt is None
                        and aufruf.name != frage_werkzeug.WERKZEUG_NAME
                        and aufruf.name != auftrag_werkzeug.WERKZEUG_NAME
                    ):
                        abgelehnt = t("fehler.werkzeug_verboten", sprache, name=aufruf.name)
                        abgelehnt_modell = t(
                            "fehler.werkzeug_verboten", "en", name=aufruf.name
                        )

                    # Measured from here, not from the top of the loop: a
                    # confirmation prompt waits on a click, not on the tool,
                    # and counting that click into "how long the tool took"
                    # would blame a slow command for a slow human.
                    aufruf_beginn = time.monotonic()

                    # ask_user is not executed but answered. The run holds
                    # the call open the way it holds a confirmation open, and
                    # what comes back — a clicked label or a typed sentence —
                    # is the tool's result.
                    if aufruf.name == frage_werkzeug.WERKZEUG_NAME and abgelehnt is None:
                        # The time spent waiting on the person, kept out of
                        # the call's own duration: the call asked, the person
                        # took their time.
                        waited = 0.0
                        # Set only when the person pressed stop while the
                        # question stood: the result then says so, and a
                        # window does not report it as a call that failed.
                        stopped_by_person = False
                        try:
                            frage_text, optionen = frage_werkzeug.gepruefte_frage(
                                aufruf.argumente
                            )
                        except frage_werkzeug.FrageUngueltig as fehler:
                            ergebnis, fehlgeschlagen = str(fehler), True
                            ergebnis_modell = ergebnis
                        else:
                            # Written the moment ask_user is called, cleared
                            # the moment an answer arrives or the wait times
                            # out — the same shape and the same reasoning as
                            # a job's own `frage` column. Without this the
                            # question lived only in `bestaetigungen`, an
                            # in-memory Future: a window that left the chat
                            # or reloaded had nothing left to show it from.
                            #
                            # Written BEFORE the SSE event goes out, not
                            # after: a window can react to that event (a
                            # live reload, a second window already fetching)
                            # before this generator gets to run again, and
                            # would then read the chat row mid-question and
                            # find no answer to it there yet.
                            # A chat deleted under its run has no row left
                            # to hold the question and nobody to answer it:
                            # the run stops instead of writing into nothing.
                            if not repositories.chats.frage_setzen(
                                chat.id,
                                json.dumps(
                                    {
                                        "aufruf_id": aufruf.id,
                                        "frage": frage_text,
                                        "optionen": optionen,
                                    },
                                    ensure_ascii=False,
                                ),
                            ):
                                log.info("Chat %s is gone, its run stops", chat.id)
                                abgebrochen = True
                                break
                            yield _sse(
                                "user_ask",
                                frage=frage_text,
                                optionen=optionen,
                                aufruf_id=aufruf.id,
                            )
                            wait_began = time.monotonic()
                            try:
                                antwort = await _auf_entscheidung_warten(
                                    generierung, aufruf.id, aufruf.name
                                )
                            finally:
                                chat_da = repositories.chats.frage_setzen(chat.id, None)
                            waited = time.monotonic() - wait_began
                            if not chat_da:
                                log.info("Chat %s is gone, its run stops", chat.id)
                                abgebrochen = True
                                break
                            if antwort is None and generierung.soll_abbrechen:
                                # The open call gets its result before the
                                # run ends, so its row does not stay
                                # "running" and every call in the history
                                # has its answer. It takes the shared path
                                # below and the run stops after it.
                                ergebnis = t("nachricht.abgebrochen_kurz", sprache)
                                ergebnis_modell = frage_werkzeug.CANCELLED
                                fehlgeschlagen = True
                                abgebrochen = True
                                stopped_by_person = True
                            else:
                                ergebnis = (
                                    antwort
                                    if isinstance(antwort, str) and antwort.strip()
                                    else frage_werkzeug.OHNE_ANTWORT
                                )
                                # Cut once, here, before it goes anywhere: this
                                # answer IS the model's copy too (no twin), and
                                # the log and the stream must carry what the
                                # model read (the ceiling's comment at the top).
                                ergebnis = ergebnis[:WERKZEUGERGEBNIS_GRENZE]
                                ergebnis_modell = ergebnis
                                fehlgeschlagen = False
                        dauer = max(0.0, round(time.monotonic() - aufruf_beginn - waited, 3))
                        werkzeugprotokoll.append(
                            {
                                "name": _display_name(registry, aufruf.name),
                                "server": registry.server_von(aufruf.name) if registry else "",
                                "argumente": aufruf.argumente,
                                "fehlgeschlagen": fehlgeschlagen,
                                "ergebnis": ergebnis,
                                "bild": None,
                                "dauer_sekunden": dauer,
                                "kennung": aufruf.id,
                                **_modellfassung(ergebnis, ergebnis_modell),
                                **_runde_im_protokoll(
                                    werkzeugprotokoll,
                                    stored_round,
                                    runden_text,
                                    denkteile,
                                    textteile,
                                    blocks=stored_blocks,
                                ),
                            }
                        )
                        yield _sse(
                            "tool_result",
                            name=_display_name(registry, aufruf.name),
                            aufruf_id=aufruf.id,
                            fehlgeschlagen=fehlgeschlagen,
                            text=ergebnis,
                            bild=None,
                            dauer_sekunden=dauer,
                            **({"stopped": True} if stopped_by_person else {}),
                        )
                        anfrage.nachrichten.append(
                            ChatNachricht(
                                role="tool",
                                content=ergebnis_modell,
                                werkzeugaufruf_id=aufruf.id,
                            )
                        )
                        if abgebrochen:
                            break
                        continue

                    # start_job starts at once: sending an agent off never
                    # asks, as handing work to a subagent asks nothing. What
                    # the agent then does is judged call by
                    # call with its own tools but under THIS chat's mode and
                    # rules, as a subagent works in its main session's mode:
                    # a call the chat would ask about is asked about in this
                    # chat (`ask_in_chat`, app/api/v1/auftraege.py), and one
                    # nobody answers is refused alone while the run goes on.
                    # Intercepted rather than run through the registry: the
                    # job needs this chat's world to start in.
                    if aufruf.name == auftrag_werkzeug.WERKZEUG_NAME and abgelehnt is None:
                        fehlgeschlagen = False
                        agent_objekt = None
                        # The started job, for the agent's row in the chat.
                        started_job_id = None
                        # The call, the way every other tool reports one: the
                        # window draws its card from it.
                        yield _sse(
                            "tool_call",
                            name=_display_name(registry, aufruf.name),
                            server=registry.server_von(aufruf.name) if registry else "",
                            argumente=aufruf.argumente,
                            aufruf_id=aufruf.id,
                        )
                        image_names: list[str] = []
                        try:
                            agent_name, task = auftrag_werkzeug.geprueft(aufruf.argumente)
                            try:
                                image_names = task_images.checked(
                                    aufruf.argumente.get("images")
                                )
                            except task_images.TaskImagesInvalid as fehler:
                                raise auftrag_werkzeug.AuftragVerboten(str(fehler)) from fehler
                            if not agent_name or helper.is_helper(agent_name):
                                # No agent named: a helper takes the work
                                # (app/helper.py). Whether one more may run
                                # is asked where the run is made, below.
                                agent_name = helper.HELPER_NAME
                                agent_objekt = helper.helper_agent(repositories, registry)
                            else:
                                agenten = agenten_laden(
                                    *app.state.config.agentenverzeichnisse
                                )
                                agent_objekt = agenten.get(agent_name)
                                if agent_objekt is None:
                                    raise auftrag_werkzeug.AuftragVerboten(
                                        f"No agent named '{agent_name}' was found. Available "
                                        f"agents: {', '.join(sorted(agenten)) or 'none'}."
                                    )
                        except auftrag_werkzeug.AuftragVerboten as fehler:
                            ergebnis, fehlgeschlagen = str(fehler), True
                            # This branch's own words are English already, so
                            # both readers get the same string. Only the
                            # route's refusal below carries a second copy.
                            ergebnis_modell = ergebnis
                        if agent_objekt is not None:
                            # Imported here, not at the top: the jobs
                            # module imports from this one, and the two
                            # only meet inside this handler.
                            from app.api.v1.auftraege import (
                                Refusal,
                                auftrag_anstossen,
                                chat_run_folders,
                                job_could_not_start,
                                run_folders,
                            )

                            # The task and the folders this chat's own
                            # tools work in, never the chat itself — so a
                            # relative path of the run lands where the same
                            # path lands in the chat.
                            job_folders, own_folder = chat_run_folders(
                                app.state.config.datenverzeichnis, chat, agent_objekt
                            )
                            # The pictures handed over, read off the event
                            # loop (a large one is copied smaller first), in
                            # exactly the folders the run gets and only
                            # where the run's own read_file would read them
                            # without asking: judged as the agent's call
                            # under this chat's rules, the way its calls are.
                            folders_of_run = run_folders(job_folders, agent_objekt)
                            judge = registry
                            run_agent = agent_objekt

                            def may_read(path: str) -> bool:
                                return judge is not None and judge.urteil(
                                    "read_file", {"path": path}, folders_of_run,
                                    "agent", run_agent, rules_of="chat",
                                ).antwort == "ja"

                            images = (
                                await asyncio.to_thread(
                                    task_images.prepare,
                                    image_names,
                                    folders_of_run,
                                    app.state.config.datenverzeichnis,
                                    may_read,
                                )
                                if image_names
                                else []
                            )
                            try:
                                auftrag = auftrag_anstossen(
                                    config=app.state.config,
                                    repositories=repositories,
                                    discovery=discovery,
                                    generierungen=generierungen,
                                    registry=registry,
                                    agent=agent_objekt,
                                    task=task,
                                    endpoint_id=None,
                                    ordner=job_folders,
                                    own_folder=own_folder,
                                    user_id=user_id,
                                    sprache=sprache,
                                    chat_id=chat.id,
                                    ask_in_chat=True,
                                    images=images,
                                )
                            except HTTPException as fehler:
                                # The window reads the frame in the user's
                                # language, the model in English. A refusal
                                # of this route carries the model's English
                                # copy of what stands behind the frame
                                # (Refusal); any other has only the
                                # sentence it was raised with.
                                ergebnis = job_could_not_start(fehler.detail, sprache)
                                ergebnis_modell = job_could_not_start(
                                    fehler.model if isinstance(fehler, Refusal) else fehler.detail
                                )
                                fehlgeschlagen = True
                            else:
                                started_job_id = auftrag.id
                                if helper.is_helper(agent_name):
                                    log.info(
                                        "Helper %s started from chat %s with %d tool(s), "
                                        "%d round(s)",
                                        auftrag.id,
                                        chat.id,
                                        len(agent_objekt.werkzeuge or []),
                                        agent_objekt.runden,
                                        extra={"ereignis": "helper_started", "chat": chat.id},
                                    )
                                ergebnis = (
                                    f"Job started: agent '{agent_name}', ID {auftrag.id}. It "
                                    "runs independently. When it finishes, its report will "
                                    "return to this chat, and you will be asked to summarize "
                                    "it for the user."
                                )
                                # One string for both readers here: what
                                # this tool answers is the program's own
                                # English, and no window copy of it
                                # exists. The twin matters only on the
                                # refusal above, where the route's
                                # German sentence is the other copy.
                                ergebnis_modell = ergebnis
                        # Cut once, before it goes anywhere: the log, the
                        # stream and the model's copy carry the same text, so
                        # a later request rebuilds this run as it went out
                        # (the ceiling's comment at the top).
                        ergebnis = ergebnis[:WERKZEUGERGEBNIS_GRENZE]
                        ergebnis_modell = ergebnis_modell[:WERKZEUGERGEBNIS_GRENZE]
                        dauer = max(0.0, round(time.monotonic() - aufruf_beginn, 3))
                        werkzeugprotokoll.append(
                            {
                                "name": _display_name(registry, aufruf.name),
                                "server": registry.server_von(aufruf.name) if registry else "",
                                "argumente": aufruf.argumente,
                                "fehlgeschlagen": fehlgeschlagen,
                                "ergebnis": ergebnis,
                                # Beside the window's sentence where the two
                                # differ, as in the general branch below.
                                **_modellfassung(ergebnis, ergebnis_modell),
                                "bild": None,
                                "dauer_sekunden": dauer,
                                "auftrag_id": started_job_id,
                                "kennung": aufruf.id,
                                **_runde_im_protokoll(
                                    werkzeugprotokoll,
                                    stored_round,
                                    runden_text,
                                    denkteile,
                                    textteile,
                                    blocks=stored_blocks,
                                ),
                            }
                        )
                        yield _sse(
                            "tool_result",
                            name=_display_name(registry, aufruf.name),
                            aufruf_id=aufruf.id,
                            fehlgeschlagen=fehlgeschlagen,
                            text=ergebnis,
                            bild=None,
                            dauer_sekunden=dauer,
                            auftrag_id=started_job_id,
                        )
                        anfrage.nachrichten.append(
                            ChatNachricht(
                                role="tool",
                                # The model's copy, never the window's: this
                                # branch hands its result over and leaves, so
                                # the twin worked out above has to be taken
                                # HERE — nothing later reads it.
                                content=ergebnis_modell,
                                werkzeugaufruf_id=aufruf.id,
                            )
                        )
                        continue

                    # The server travels with the call: the UI picks the
                    # tool's mark by it, and unlike the tool name it is fixed
                    # in the configuration and cannot be guessed wrong.
                    yield _sse(
                        "tool_call",
                        name=_display_name(registry, aufruf.name),
                        server=registry.server_von(aufruf.name) if registry else "",
                        argumente=aufruf.argumente,
                        aufruf_id=aufruf.id,
                    )
                    if abgelehnt is not None:
                        ergebnis, fehlgeschlagen = abgelehnt, True
                        # The model reads the English twin; the window,
                        # the log and the stored row below all keep `ergebnis`
                        # in the user's own language. Set in the same branch
                        # as `abgelehnt` above, always together.
                        assert abgelehnt_modell is not None
                        ergebnis_modell = abgelehnt_modell
                        # Refused as it began, at the folder check — the
                        # program's refusal about the folders, never the
                        # user's no: only that one is told where a moved
                        # folder went.
                        refused = frueh_grund is not None
                    else:
                        bilder_vorher = len(werkzeug_bilder)
                        read_before = len(gelesene_bildpfade)
                        # The third value, whether the call was refused, is
                        # the loop guard's, which watches unattended job
                        # runs, not the live chat — a person is right there
                        # to redirect the model. The fourth says the refusal
                        # was about the call's path: only that one gets the
                        # move sentence below. The chat's own folder is made
                        # by the tool as it runs, where it is missing
                        # (app/tools/grenzen.py `prepare_folders`).
                        ergebnis, fehlgeschlagen, _, refused = await _werkzeug_ausfuehren(
                            registry, aufruf, sprache, bild_senke,
                            ordner=werkzeugordner, chat_id=chat.id,
                            shell_zeitgrenze=befehl_zeitgrenze,
                            # One report per run, here too — a chat turn that already announced
                            # one does not announce a second.
                            ziel_gemeldet=ziel_bericht is not None,
                            # Only where the model has eyes. Without them
                            # `read_file` says it cannot show the picture
                            # instead of handing over one nobody can see.
                            modellbild=modellbild if zustand.kann("vision") else None,
                            # The memory's switch for this model's side: what
                            # does not travel in the prompt is not listed by
                            # the tool either.
                            gedaechtnis_zeigen=aufruf.name == memory.WERKZEUG_NAME
                            and gedaechtnis.mitschicken(repositories, zustand),
                            # The answer a drawn picture or a video joins
                            # as its run, and a delivered file hangs on.
                            antwort_id=platzhalter.id
                            if aufruf.name in ANSWER_TOOLS else None,
                            # The run's stop: a picture being drawn ends with
                            # the run instead of drawing on for nobody.
                            abbruch=generierung.signal,
                        )
                        # A run's own result is already the model's copy —
                        # it never carried a second, localized sentence to
                        # begin with (app/tools/registry.py and friends
                        # already answer in English).
                        ergebnis_modell = ergebnis
                    # Did THIS call save an image? Then the line in the stream
                    # and the log in the message carry it.
                    neues_bild = (
                        werkzeug_bilder[-1]
                        if abgelehnt is None and len(werkzeug_bilder) > bilder_vorher
                        else None
                    )
                    # Did THIS call hand the model a picture to look at? The
                    # row remembers which file, so a later request that
                    # rebuilds the history can attach it again — by this
                    # note and not by the result's words, which a file's own
                    # text could imitate (app/werkzeugbild.py).
                    read_picture = (
                        gelesene_bildpfade[read_before]
                        if abgelehnt is None and len(gelesene_bildpfade) > read_before
                        else None
                    )
                    # A drawing call: this answer's run row as it stands now
                    # rides along in the stream, the tile it may have just
                    # gained included — the picture window's reconcile, for
                    # the one row. None while the run has no picture yet.
                    run_row = None
                    if abgelehnt is None and aufruf.name in video_tool.DRAWING_TOOLS:
                        drawn_run = repositories.messages.run_row(
                            chat_id=chat.id, lauf_kennung=platzhalter.id
                        )
                        if drawn_run is not None:
                            run_row = NachrichtAntwort.aus(drawn_run).model_dump()
                    # A delivered file: the cards of this answer as they
                    # stand now ride along, the new one included, so the
                    # window can show the file without reading the chat
                    # again. The row itself carries it for every later read.
                    delivered = None
                    if (
                        abgelehnt is None
                        and not fehlgeschlagen
                        and aufruf.name == delivery_tool.WERKZEUG_NAME
                    ):
                        delivered = _document_cards(repositories, platzhalter.id)
                    # Cut once, before it goes anywhere: the log, the stream
                    # and the model's copy carry the same text, so a later
                    # request rebuilds this run as it went out (the ceiling's
                    # comment at the top).
                    ergebnis = ergebnis[:WERKZEUGERGEBNIS_GRENZE]
                    ergebnis_modell = ergebnis_modell[:WERKZEUGERGEBNIS_GRENZE]
                    # Every refusal of the program the model reads for a file
                    # call aimed under a folder this chat re-chose carries
                    # where it went — a refusal at the gate, a path that no
                    # longer exists; never a call the user declined. After
                    # the cut, so it is never cut off.
                    ergebnis_modell = with_move_note(
                        ergebnis_modell,
                        refused=refused,
                        werkzeuge_an=registry is not None,
                        chat_id=chat.id,
                        aufruf=aufruf,
                        ordner=werkzeugordner,
                    )
                    dauer = round(time.monotonic() - aufruf_beginn, 3)
                    # Every shell command that actually ran has a run behind
                    # it, and the call's entry gets that run's NUMBER. The
                    # terminal panel pairs call and run by it — by position,
                    # a call refused before it started (no shared folder)
                    # took the next real run's output. For a command sent
                    # to the background the number is also how the ending
                    # is written onto the call later: by the closing write
                    # below if the run ends while this answer is still
                    # going, by app/hintergrundmeldung.py if it ends after.
                    lauf_nummer: int | None = None
                    if aufruf.name == shell.WERKZEUG_NAME and abgelehnt is None:
                        # Asked the way the tool names the run — stripped —
                        # and only for a run that began at THIS call: with
                        # the raw argument a command ending in a newline
                        # never found its own run, and a call that failed
                        # before starting one (no shared folder, a blocked
                        # pattern) was handed the last run of the same
                        # command instead.
                        gestartet = hintergrund.laeufe.juengster(
                            chat.id,
                            str(aufruf.argumente.get("command") or "").strip(),
                            seit=aufruf_beginn,
                        )
                        if gestartet is not None:
                            lauf_nummer = gestartet.nummer
                            # Which answer started it: the row its ending is
                            # written onto once this answer is over
                            # (app/hintergrundmeldung.py). By id rather than
                            # by searching the chat for the number — a
                            # search could land on an older row carrying
                            # the same one.
                            gestartet.antwort_id = platzhalter.id
                    werkzeugprotokoll.append(
                        {
                            "name": _display_name(registry, aufruf.name),
                            # Stored alongside, so a reloaded history shows the
                            # same mark as the live run did.
                            "server": registry.server_von(aufruf.name) if registry else "",
                            "argumente": aufruf.argumente,
                            "fehlgeschlagen": fehlgeschlagen,
                            # Goes into the message so that even after a reload
                            # the history shows what the tool delivered — the
                            # same text the stream carried, as everywhere.
                            "ergebnis": ergebnis,
                            # A later request rebuilds the model's history
                            # from this same row (app/verlaufsbau.py), not
                            # from the live round above — without its own
                            # copy here, the second turn of this chat would
                            # hand the model the window's own language again.
                            **_modellfassung(ergebnis, ergebnis_modell),
                            "bild": neues_bild,
                            **(
                                {werkzeugbild.READ_IMAGE_PATH: read_picture}
                                if read_picture
                                else {}
                            ),
                            "dauer_sekunden": dauer,
                            "kennung": aufruf.id,
                            **_runde_im_protokoll(
                                werkzeugprotokoll,
                                stored_round,
                                runden_text,
                                denkteile,
                                textteile,
                                blocks=stored_blocks,
                            ),
                            **({"lauf_nummer": lauf_nummer} if lauf_nummer is not None else {}),
                        }
                    )
                    yield _sse(
                        "tool_result",
                        name=_display_name(registry, aufruf.name),
                        aufruf_id=aufruf.id,
                        fehlgeschlagen=fehlgeschlagen,
                        text=ergebnis,
                        bild=neues_bild,
                        dauer_sekunden=dauer,
                        **({"lauf_nummer": lauf_nummer} if lauf_nummer is not None else {}),
                        **({"bildlauf": run_row} if run_row is not None else {}),
                        **({"dokumente": delivered} if delivered else {}),
                    )
                    # A goal was reported: the answer gets its finished mark
                    # right now, while the model may still be writing. The
                    # text comes from the tool's own reading of the call, not
                    # from the raw argument — one cleaning, not two.
                    if aufruf.name == ziel_werkzeug.WERKZEUG_NAME and not fehlgeschlagen:
                        try:
                            ziel_bericht = ziel_werkzeug.bericht(aufruf.argumente)
                        except ziel_werkzeug.ZielVerboten:
                            # The call ran, so this cannot normally happen —
                            # and a mark is not worth breaking a good answer
                            # over if it somehow does.
                            log.warning("goal call without a usable report: %s", aufruf.argumente)
                        else:
                            yield _sse("ziel", report=ziel_bericht)
                    anfrage.nachrichten.append(
                        ChatNachricht(
                            role="tool",
                            content=ergebnis_modell,
                            werkzeugaufruf_id=aufruf.id,
                        )
                    )

                # Every result of the round is in place, so a picture one of
                # them read may follow now — as a user turn, the only role an
                # image part is valid on.
                bildzug = werkzeugbild.nachricht(
                    gelesene_bildnamen, gelesene_bild_urls, gelesene_bildpfade
                )
                if bildzug is not None:
                    anfrage.nachrichten.append(bildzug)

                # The round is complete: its last tool result is in the log,
                # and the next model call may take a minute before anything
                # is worth writing again.
                zwischenstand_sichern(erzwungen=True)

                # If cancelled during a confirmation prompt, there is no next
                # round — otherwise the model would set off once more.
                if abgebrochen:
                    break

                # The trigger at the true end of the round: everything the
                # round's own tools just printed is in the history now and in
                # none of its readings, so this is the first moment the next
                # request can be weighed at all. Asked one line earlier — with
                # the round's own numbers — it would fire a round late, on the
                # round AFTER the one that actually grew past the threshold.
                # A job has asked it here all along (app/api/v1/auftraege.py);
                # the chat asked it only once per answer, before the first
                # request, and a chain of forty tool rounds grew unchecked
                # inside that one answer.
                #
                # The whole check runs every round, the fold's own brake
                # below notwithstanding: the free step still has work after
                # the paid one gave up, because the protected end moves on
                # with every round — what was the model's working memory in
                # one round is an old result in the next.
                #
                # `letzter_gesamtstand` is the real total the provider
                # counted for this round, the round's own answer included,
                # so only what was appended after it — this round's own
                # tool results, from `laenge_nach_antwort` on — is new.
                #
                # Report, clear, report again, fold: the one step a job
                # takes between its rounds too (app/round_end.py). Every
                # reading it reports becomes the total the next readings
                # estimate from — the live readings of the next round
                # start from it, so the bar does not fall back to a number
                # that lacks this round's results, and after a fold it
                # stands at what the folded request weighs, not at the
                # longer one before it.
                # Also read where the answer ends: the fold written down
                # there keeps the same tail.
                schwelle = verdichtungswahl.schwelle(
                    repositories, modell=endpoint_id, chat=chat.id
                )
                async for schritt in round_end.between_rounds(
                    zustand,
                    anfrage,
                    last_reading=letzter_gesamtstand,
                    appended_from=laenge_nach_antwort,
                    threshold=schwelle,
                    set_limit=eingestellte_grenze,
                    fold_allowed=not verdichtung_abgeschaltet,
                    key=chat.id,
                    settings=repositories.einstellungen,
                    endpoint_id=refusal_id,
                    stop=generierung.signal,
                ):
                    if isinstance(schritt, kontextverbrauch.Kontextstand):
                        # An estimate, so the row gets it at the live pace.
                        letzter_gesamtstand = schritt.tokens
                        meldung = stand_verbuchen(schritt.tokens, endgueltig=False)
                        if meldung:
                            yield meldung
                    elif isinstance(schritt, round_end.Cleared):
                        # Which results went, and as which sentence: the
                        # answer's row remembers it, so the next request
                        # hands the model the same replacement instead of the
                        # whole result again (app/verlaufsbau.py reads it
                        # back). The rows keep every character — this answer
                        # writes nothing into the database about it.
                        for vorher, nachher in zip(
                            schritt.before, schritt.after, strict=True
                        ):
                            ersetzt = next(
                                (
                                    art
                                    for art, satz in werkzeugkuerzung.ERSETZUNGEN.items()
                                    if satz == nachher.content
                                ),
                                None,
                            )
                            if (
                                ersetzt
                                and vorher.role == "tool"
                                and vorher.content != nachher.content
                                and vorher.werkzeugaufruf_id
                            ):
                                geraeumte_ergebnisse[vorher.werkzeugaufruf_id] = ersetzt
                        log.info(
                            "Chat %s: cleared %d old tool results from the request "
                            "(%d tokens)",
                            chat.id,
                            schritt.count,
                            schritt.saved,
                        )
                    elif schritt.result.angewendet:
                        folded_after_reading = True
                        # A fold of the ROWS is out of the question here:
                        # this answer's tool rounds are not rows, and the
                        # fold would have to write one mid-answer to say so —
                        # so the list in memory is folded, the way a job
                        # folds its own. The summary the fold left in the
                        # request, taken from there rather than asked of the
                        # fold: it is marked as a summary by its kind
                        # (app/verdichtung.py, `compacted_summary`), and the
                        # LAST one of them is this fold's — an earlier
                        # summary the tail protected stands in front of it.
                        gefaltete_mitte = next(
                            (
                                nachricht.content
                                for nachricht in reversed(anfrage.nachrichten)
                                if nachricht.compacted_summary
                            ),
                            gefaltete_mitte,
                        )
                        log.info(
                            "Chat %s: compacted the history in memory between rounds",
                            chat.id,
                        )
                    elif schritt.result.ohne_ersparnis:
                        # The attempt cost a request and saved nothing, so
                        # every further round of THIS answer would cost
                        # another for the same nothing. Only the model-backed
                        # step stops: the free one before it costs no request
                        # and keeps working. The brake a job keeps for its
                        # whole run, kept for this answer — the next answer
                        # starts fresh.
                        verdichtung_abgeschaltet = True
                        log.info(
                            "Chat %s: compacting stopped for this answer — the "
                            "last attempt did not shrink the history",
                            chat.id,
                        )

        except ProviderFehler as fehler:
            # This one goes into the chat bubble, so it is the person's copy
            # and stands in the language of their page. The model's copy of
            # the same error is ``str(fehler)``, English, and travels the job
            # path (app/api/v1/auftraege.py) — one sentence, two readers.
            fehlertext = fehler.text(sprache)
            # Asking also learns: both halves of the request take what the
            # refusal names (app/ablehnungslernen.py).
            kontextfenster_voll = ablehnungslernen.fenster_voll(
                repositories, zustand, fehler
            )
            # The answer's length, not the context, was what the model did
            # not take — its own ending, never "the context is full", which
            # would send the user after the wrong thing
            # (app/kontextvoll.py `is_output_cap`). Only where a length is set:
            # under Auto there is no number for the user to lower, so the
            # turn keeps the ending it always had.
            if (
                kontextfenster_voll
                and eingestellte_grenze is not None
                and kontextvoll.output_cap_error(fehler)
            ):
                kontextfenster_voll = False
                antwortlaenge_zu_gross = True
            # A stage the model does not take. The provider's own sentence
            # goes into the chat word for word — a rewritten one would be a
            # second version of a fact only the provider knows — and the
            # stage leaves this model's list so nobody meets it twice.
            # This turn does not go out again at another depth: the request
            # was not what was asked for, so the choice goes back to the
            # hand. The next turn reads the stored stage again, and with this
            # one off the list it gets the nearest weaker depth the model
            # still offers (app/denkenwahl.py, `nearest_depth`).
            #
            # The one rule for every request that sends a stage
            # (app/denkablehnung.py `lernen`): only a stage whose fields went
            # out is blamed, "off" included in its older yes/no form, and a
            # spoken turn's "off" follows it the same way.
            if denkablehnung.lernen(
                repositories.einstellungen, refusal_id, fehler,
                last_sent.get("zusatz", anfrage.zusatz), last_sent.get("stufe", denkstufe),
                route=think_route,
            ):
                fehlertext = getattr(fehler, "rohtext", None) or fehlertext
            if kontextfenster_voll:
                karten_berichtigen()
            log.warning("Provider %s: %s", endpoint_id, fehler)
        except asyncio.CancelledError:
            abgebrochen = True
            raise
        except Exception:  # noqa: BLE001
            fehlertext = t("fehler.allgemein", sprache)
            log.exception("Unexpected error while streaming from %s", endpoint_id)
        finally:
            # Close the connection to the model server — that is the actual cancellation.
            if quelle is not None:
                await quelle.aclose()

            messwerte = dict(messwerte or {})
            messwerte["abgebrochen"] = abgebrochen
            if fehlertext:
                messwerte["fehler"] = fehlertext
            if antwortlaenge_zu_gross:
                # Its own line, before the window: the refusal was about a
                # number the user can change, and naming the window would
                # send them after the wrong thing.
                messwerte["antwortlaenge_zu_gross"] = True
            elif kontextfenster_voll or antwortende.fenster_voll(
                messwerte.get("ende_grund"),
                gesamt_tokens=kontextverbrauch.tokens_aus_messwerten(messwerte),
                fenster=zustand.context_tokens,
                eigene_grenze=bool(eingestellte_grenze),
            ):
                # The same field an answer cut off by a full window carries
                # (app/antwortende.py), so the window reads one flag for both.
                #
                # Two ways in. The provider's refusal, read above — and the
                # answer's own ending, which is the only evidence there is
                # wherever no refusal ever came: the whole window fills
                # mid-answer and an OpenAI-compatible server calls that an
                # ordinary length stop, so the numbers of the LAST round
                # (the one the merge keeps, which is the one that describes
                # the finished answer) are what tells it from an answer that
                # stopped at a length somebody set.
                messwerte["kontextfenster_voll"] = True
                # The other way into a full window, and the card has to be
                # taken back on this one too: no refusal ever came, the
                # answer simply ran into the wall mid-sentence.
                karten_berichtigen()
            elif antwortende.denken_aufgebraucht(
                messwerte.get("ende_grund"),
                denktext="".join(gedanke_text),
                sichtbarer_text="".join(antwort_text),
            ):
                # BEFORE the plain provider limit below: this is the same
                # ending, read one step closer. Under Auto both are true, and
                # only this one says where the length went — without it the
                # sentence for that case could never appear.
                #
                # The thinking pass spent the whole answer length and not one
                # visible character came after it. Its own field: "cut off at
                # the set length" is true but says nothing about WHERE the
                # length went, and an empty answer with no explanation reads
                # as a broken model (app/antwortende.py).
                #
                # The field carries the catalogue key rather than a bare
                # flag: which of the two sentences is true depends on whose
                # length ran out — a number the user set, or the provider's
                # own — and that is known here, not in the window.
                messwerte["denken_aufgebraucht"] = (
                    "denken_aufgebraucht_eigene_grenze"
                    if eingestellte_grenze
                    else "denken_aufgebraucht"
                )
            elif antwortende.anbietergrenze(
                messwerte.get("ende_grund"),
                gesamt_tokens=kontextverbrauch.tokens_aus_messwerten(messwerte),
                fenster=zustand.context_tokens,
                eigene_grenze=bool(eingestellte_grenze),
            ):
                # The answer ended at a number of the PROVIDER's while the
                # window still had room: a maker's limit, a learned cap, or a
                # server deciding the length itself. Its own field, because
                # the line under the answer has to say something else — a
                # slider the user never touched is not what ended this.
                messwerte["anbietergrenze"] = True
            if faltpause.hinweis_faellig(chat.id):
                # Two folds in a row failed, so automatic compaction is off
                # for this chat until it earns one attempt back
                # (app/faltpause.py). Its own field and its own line under
                # the answer: unlike the two above,
                # which rule each other out, this one can stand beside them
                # — an answer can be cut short AND have lost its compaction.
                messwerte["komprimieren_fehlgeschlagen"] = True
            if werkzeugprotokoll:
                # A background run that ended while this answer was still
                # being written: its ending goes onto the call that started
                # it, now that the log is about to be stored for good. A run
                # that ends later is written in by app/hintergrundmeldung.py.
                hintergrundmeldung.nachtragen(werkzeugprotokoll, chat.id)
                messwerte["werkzeuge"] = werkzeugprotokoll
            if geraeumte_ergebnisse:
                # What this answer's clearing replaced in its request, by the
                # sentence that stood there instead. The next request rebuilds
                # the rounds from these rows (app/verlaufsbau.py) and hands
                # the model the same sentences the run sent.
                messwerte["geraeumt"] = geraeumte_ergebnisse
            # Stored next to the tool log for the same reason: a reloaded
            # history should show the finished mark the live run showed.
            if ziel_bericht:
                messwerte["ziel"] = ziel_bericht
            # Normalized across providers, same as a job's per-round reading
            # (app/kontextverbrauch.py): Anthropic already carries this as
            # gesamt_tokens, an OpenAI-compatible server only as a raw
            # `nutzung` passthrough that may or may not have a usable total.
            # The context display reads this one field regardless of which
            # provider answered.
            # Through the same completeness check the live readings go
            # through, not the raw sum. Half a usage block is a per-round
            # display and not an absolute standing, and this is the write
            # that LASTS: a round reporting only `completion_tokens: 120`
            # turned a context of 12,000 into 120 in the column, which is
            # then what the next answer estimates from and what decides
            # whether a chat ever compacts again. The live path was fixed
            # and this one was left on the raw call, so the number the
            # answer refused mid-flight won at its end.
            gesamt_tokens = _ganzer_stand(messwerte)
            # A fold between rounds changed the request after the last round
            # that counted it: that count is of the longer request, and kept
            # here the next answer would fold again at once over a number
            # that is gone. The reading of the folded request stands instead.
            if folded_after_reading and gemeldeter_stand is not None:
                gesamt_tokens = gemeldeter_stand
            if gesamt_tokens is not None:
                messwerte["gesamt_tokens"] = gesamt_tokens
            # How the run ended, in one word: the column's value, and the
            # word the `done` event carries so the window can write the
            # same one into its row instead of guessing from the blob.
            schluss_zustand = (
                "abgebrochen" if abgebrochen else "fehler" if fehlertext else "fertig"
            )

            # The one swap the thinking owes: a model that ended its answer
            # itself, with a closing round that wrote not one visible
            # character, thought the answer instead of writing it. Then the
            # thought of the round the answer ENDED in is the answer — set
            # behind whatever an earlier tool round wrote before its call,
            # which is no answer to the question — and the deliberation of
            # the tool rounds before it stays in the thinking block, where it
            # was display and never context. A run that was
            # stopped or that failed keeps the two apart however its last
            # round ended, and so does every ending that was not the model's
            # own (app/reasoning.denktext_als_antwort).
            ganze_antwort = "".join(antwort_text)
            antwort_inhalt, gedanke_inhalt = reasoning.denktext_als_antwort(
                ganze_antwort,
                "".join(gedanke_text),
                "".join(runden_gedanke),
                schlusstext="".join(runden_text),
                ende_grund=messwerte.get("ende_grund"),
                zustand=schluss_zustand,
            )
            if antwort_inhalt != ganze_antwort:
                # The answer in this row is not one the model wrote; its own
                # key in the blob, so a stored row can still tell the two
                # apart afterwards, exactly as every reading beside it does.
                messwerte["denktext_als_antwort"] = True

            # The most recent tool image hangs on the answer — the message
            # can carry only one, and the last one is the one the model
            # talked about most recently.
            bild_der_antwort = werkzeug_bilder[-1] if werkzeug_bilder else None
            # A picture the model DREW is not among them: it stands in this
            # answer's own run since the moment it was finished, written by
            # the picture route itself (see `bild_senke` above).

            # Whether the chat is still there, asked once before anything
            # below writes. Deleting a chat waits for its run, so this is
            # not expected to be false; it is the same check the ask_user
            # path makes (`frage_setzen`) for a chat that was removed some
            # other way. The summary row's insert would fail its foreign key
            # and the run would never deregister. Nothing between this and
            # the last write awaits, so the answer holds up to there.
            chat_gone = repositories.chats.holen(chat.id) is None
            if chat_gone:
                log.info("Chat %s is gone, its run stops", chat.id)

            # A fold inside this answer is written down here, BEFORE the
            # answer's own row: the summary takes its place in the seam
            # between the rows it speaks for and this answer, and the row
            # names its fold — the window fetches it like every written fold
            # (app/chatverdichtung.py, the recording the row path uses). A
            # fold that lasted only for this answer made the next message
            # fold the same stretch again.
            #
            # A new answer that took another one's place and did not finish
            # leaves nothing in the chat (below), so its fold is not written
            # down either. One that did finish writes it without the answer
            # it replaces: that row was in no request of this run, and the
            # summary does not speak for it.
            discarded = replaced is not None and schluss_zustand != "fertig"
            if gefaltete_mitte and not discarded and not chat_gone:
                geschrieben = chatverdichtung.faltung_nachtragen(
                    chat=chat,
                    repositories=repositories,
                    zusammenfassung=gefaltete_mitte,
                    budget=verdichtung.schwanz_budget(
                        zustand.context_tokens, schwelle
                    ),
                    ausser_id=platzhalter.id,
                    without=replaced.id if replaced is not None else None,
                )
                # Only where the row path wrote nothing: its summary is the
                # older one of the two, and the window only asks whether a
                # fold happened at all.
                if geschrieben and not verdichtet_zu:
                    verdichtet_zu = geschrieben
                # Written: the next send builds the system message anew,
                # the same as after the fold before an answer.
                if geschrieben:
                    forget_system_message(chat.id)
            # Only the row keeps the order: the live window built its own,
            # so the stats event and the bus do not carry it.
            order = sections.stored(
                antwort_inhalt,
                gedanke_inhalt,
                final=True,
                promoted=bool(messwerte.get("denktext_als_antwort")),
            )
            closing_write: dict[str, Any] = dict(
                content=antwort_inhalt,
                reasoning=gedanke_inhalt or None,
                stats={**messwerte, "sections": order} if order else messwerte,
                bild=bild_der_antwort,
                # The closing state, in the column rather than only as a key
                # inside the metrics blob. A cancelled run is not a failed
                # one, and neither is a run that merely ended — the window
                # used to tell the three apart by which keys happened to be
                # present, which is also what made every foreign row look
                # like an answer still being written.
                zustand=schluss_zustand,
                # The exact number where there is one; otherwise the last
                # live reading, which the throttle above may not have
                # written yet — the column must not end behind the stream.
                gesamt_tokens=gesamt_tokens if gesamt_tokens is not None else gemeldeter_stand,
            )
            # A failed answer asked again whose repeated call brought
            # nothing — it failed again at once, or was stopped before it
            # wrote: the answer stands as it stood before the press, what
            # its failed call had begun to write included. A new failure
            # leaves its own reason; a stop leaves the old one.
            #
            # Read as it stands NOW, not as it was read at the start: this
            # run wrote nothing into it, but the ending of a background
            # command of the earlier run may have been written onto its tool
            # log meanwhile (app/hintergrundmeldung.py).
            if retried is not None and schluss_zustand != "fertig" and not went_on():
                standing = repositories.messages.holen(retried.id) or retried
                schluss_zustand = answer_redo.FAILED
                closing_write = dict(
                    content=standing.content,
                    reasoning=standing.reasoning,
                    stats={**standing.stats, "fehler": fehlertext}
                    if fehlertext
                    else standing.stats,
                    zustand=schluss_zustand,
                )
            if chat_gone:
                # The rows went with the chat; there is nothing to write.
                pass
            elif discarded:
                # The new answer failed or was stopped: the one it was to
                # replace stands as it was, and of the attempt no row is
                # left. Why it ended goes out as the stream's `error` below,
                # in the sentence a failed answer carries.
                repositories.messages.loeschen(platzhalter.id)
            elif replaced is not None:
                # Finished: stored, and the replaced answer deleted in the
                # same step — never both in the chat, never neither.
                repositories.messages.finish_in_place_of(
                    platzhalter.id, replaced.id, **closing_write
                )
            else:
                repositories.messages.inhalt_aktualisieren(platzhalter.id, **closing_write)
            if not chat_gone:
                repositories.chats.zeitstempel_auffrischen(chat.id)
            generierungen.abmelden(generierung.id)

            await bus.veroeffentlichen(
                Ereignisse.ANTWORT_ABGEBROCHEN if abgebrochen else Ereignisse.ANTWORT_FERTIG,
                chat_id=chat.id,
                message_id=platzhalter.id,
                endpoint_id=endpoint_id,
                # Which model answered, beside which server did — the two
                # are not the same question, and the endpoint's id only
                # answers the second. What the provider read off the
                # server's own answer, where it got that far
                # (app/providers/openai_kompatibel.py, ``display_model``).
                #
                # And the name this request was sent with, where it did not:
                # an answer stopped in its first round never reaches the
                # provider's closing piece, and a stopped answer is exactly
                # the one whose log line has the least else in it.
                model=messwerte.get("modell") or display_model(modellname),
                stats=messwerte,
            )

        if fehlertext:
            yield _sse("error", text=fehlertext)
        yield _sse("stats", daten=messwerte)
        # The finished pair, and only where the one swap above moved a
        # thought into the answer (app/reasoning.denktext_als_antwort) — the
        # same flag the row carries, read here rather than the two texts
        # compared a second time. There the pieces the window has been
        # building its bubble from no longer say what the chat's row says,
        # and the answer stood in the thinking block until the chat was
        # opened again; so the window is handed the same two that row was
        # just written with, and lifts what it has drawn the same way. Every
        # other answer sends this event as thin as it was: its pieces
        # already say it, and
        # the closing line stands in the run's replay buffer and in the last
        # fifty finished runs until something drops them.
        # `reasoning` is absent where there is none, like that row's own
        # column.
        closing_pair = (
            {"content": antwort_inhalt, "reasoning": gedanke_inhalt or None}
            if messwerte.get("denktext_als_antwort")
            else {}
        )
        # Whether a fold happened, so the window can go and fetch it. The
        # summary row is written before this stream even opens and the
        # window is never told; without this it keeps drawing the folded
        # stretch as ordinary live context until the chat is reopened, and
        # nothing says the model stopped seeing it.
        #
        # A new answer written in another one's place says which of the two
        # rows is gone: the replaced one where it finished, its own where it
        # did not. The window takes that row down without reading the chat
        # again. Every other answer sends neither field.
        redo: dict[str, Any] = {}
        if replaced is not None:
            redo = {"discarded": True} if discarded else {"replaced": replaced.id}
        yield _sse(
            "done",
            message_id=platzhalter.id,
            abgebrochen=abgebrochen,
            zustand=schluss_zustand,
            verdichtet=verdichtet_zu,
            **closing_pair,
            **redo,
            # What the answer carried of each document, by the id of the row
            # it wrote it onto, so the cards of that row say it without the
            # chat being opened again — those rows already hold the same
            # words for the next reload, and a row this request did not send
            # is not in here and must keep what it says.
            dokumente=dokumentstand or None,
        )

    async def arbeit(generierung: Generierung) -> None:
        async for zeile in strom(generierung):
            sections.record(zeile)
            generierung.melden(zeile)

    # From here on the answer runs in the background. A chat nevertheless
    # stays bound to its request (see _zusehen): nobody should heat up the
    # GPU while no one is watching. A job is later started with
    # an_verbindung_gebunden=False and then keeps running.
    #
    # So is a wake (app/hintergrundwecken.py), and there it is not a
    # nicety: no request asked for that answer, so there is no connection
    # whose going could mean "nobody is watching". Left bound, a window
    # that happens to stand open on the chat would take the answer down
    # with it when it closes — every night this was built for.
    lauf = generierungen.starten(
        chat_id=chat.id,
        endpoint_id=endpoint_id,
        arbeit=arbeit,
        an_verbindung_gebunden=an_verbindung_gebunden,
        # So a window opening this chat cold is TOLD which row is being
        # written instead of deducing it from the list.
        message_id=platzhalter.id,
    )
    # Said out loud on the bus, for the windows: an answer the service
    # started by itself — a finished background command woke the model —
    # was invisible to a window idle on that chat. It typed into a chat the
    # service had claimed, got a 409, and saw the answer only on the next
    # open. The window that started this run ignores the event (it holds
    # the run already); any other attaches through the cold-open door.
    await bus.veroeffentlichen(
        Ereignisse.ANTWORT_BEGONNEN,
        chat_id=chat.id,
        generation_id=lauf.id,
        message_id=platzhalter.id,
    )

    return lauf


def _get_registry(request: Request) -> WerkzeugRegistry | None:
    return getattr(request.app.state, "werkzeuge", None)


@router.post(
    "/confirm",
    response_model=BestaetigungAntwort,
    summary="Answer the question preceding a tool call",
)
def bestaetigen(
    daten: BestaetigungAnfrage,
    generierungen: Generierungsverwaltung = Depends(hole_generierungen),
    config: Config = Depends(hole_config),
    registry: WerkzeugRegistry | None = Depends(_get_registry),
) -> BestaetigungAntwort:
    """No error if nobody is waiting.

    The box may have been left standing while the answer was already over.
    That is no reason for a red message — the tool didn't run anyway.

    "immer erlauben" writes the rule BEFORE the wait is
    resolved — a run that reads it a moment later (a second call, or an
    agent's own run started right after) must never race a file that has
    not been written yet.

    The rule is written only for a genuine match — a call for
    ``daten.name`` really is the one waiting on ``aufruf_id``. Without
    this, ``dauerhaft`` alone could write a rule for any name at all,
    whether or not it belongs to what is actually up on screen. The window
    names a server's tool as the server does (``_display_name``); the rule is
    kept under the name the model calls it by, which is what the gate reads.

    A waiting ``ask_user`` is a question, not a permission: its only answer
    is a text. A bare yes or no is not delivered to it, and "always allow"
    never writes a rule for it — a rule ``ask_user: ja`` would mean nothing
    and hand the model a ``True`` where it asked for words.
    """
    wartend = generierungen.wartender_name(daten.generation_id, daten.aufruf_id)
    if wartend == frage_werkzeug.WERKZEUG_NAME:
        if daten.antwort is None:
            return BestaetigungAntwort(zugestellt=False)
    elif (
        daten.dauerhaft
        and daten.erlaubt
        and daten.name
        and wartend is not None
        and daten.name in (wartend, _display_name(registry, wartend))
    ):
        immererlauben.setzen(config.pfad(config.app.berechtigungen_datei), wartend)
    return BestaetigungAntwort(
        zugestellt=generierungen.bestaetigen(
            daten.generation_id, daten.aufruf_id, daten.erlaubt, daten.antwort
        )
    )


@router.get(
    "/stream/{generation_id}",
    summary="Monitor an ongoing generation (Server-Sent Events)",
)
async def zusehen(
    generation_id: str,
    ab: int = 0,
    generierungen: Generierungsverwaltung = Depends(hole_generierungen),
    sprache: str = Depends(hole_sprache),
) -> StreamingResponse:
    """Attaches to a run that is already underway.

    ``ab`` is the counter from which reading starts. Whoever specifies
    nothing gets the run from the beginning — including everything that
    happened before watching. Whoever lost their connection counts their
    events and picks up where they left off.

    **Watching changes nothing.** Whoever leaves here cancels nothing; only
    the owning request or the stop button can do that.
    """
    lauf = generierungen.holen(generation_id)
    if lauf is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, t("fehler.allgemein", sprache))

    return StreamingResponse(
        _zusehen(lauf, ab=ab),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/stop", response_model=AbbruchAntwort, summary="Cancel response generation")
def stoppen(
    daten: AbbruchAnfrage,
    generierungen: Generierungsverwaltung = Depends(hole_generierungen),
    sprache: str = Depends(hole_sprache),
) -> AbbruchAntwort:
    # The chat first where it is given, because it is the handle that reaches
    # EVERYTHING the chat holds: its registered runs and the claim of a send
    # that is still being set up (app/generationen.py). The run id alone is
    # the older door — it answers for one run, and a run id the service has
    # already dropped would leave a claim standing while the window is told
    # that nothing was stopped.
    if daten.chat_id:
        return AbbruchAntwort(abgebrochen=generierungen.alle_im_chat_abbrechen(daten.chat_id))
    if daten.generation_id:
        return AbbruchAntwort(abgebrochen=int(generierungen.abbrechen(daten.generation_id)))
    raise HTTPException(400, t("fehler.kennung_fehlt", sprache))
