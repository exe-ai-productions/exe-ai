"""How a stored chat reads to a model — the history as the MODEL sees it.

The ``content`` column is not what a row says. A document's text is not in
it, the row only points at the document; the questions the model asked
inside a turn live in the tool log; an empty answer has to say what it was.
Everything that turns a row into the words a request carries lives here,
once, and every reader of the history goes through it: the request
builder, and compaction, which weighs and summarizes the very same rows.

It used to live in the request route (``app/api/v1/generierung.py``), and
every module that needed it had to be handed a function rather than import
one — the route imports them, and importing back would have closed a
circle. Measured before the two readings were one: compaction weighed
``messages.content`` at 700 characters against a built request of 962,970,
and the chat that needed folding most was the one that never folded.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app import dokumentablage, dokumentcache, faltbitte, skills, werkzeugbild, werkzeugkuerzung
from app.db import Repositories
from app.db.models import Chat
from app.db.repositories.messages import ist_dienstbericht
from app.providers import ChatNachricht
from app.providers.base import Werkzeugaufruf
from app.tools import frage_werkzeug

log = logging.getLogger(__name__)


def _picture_places(config) -> tuple[Path, Path]:
    """Where the pictures live and where the model's copies of them live.

    Read once per history build and once per warm-up, not once per picture:
    the picture folder is looked up in the stored locations (``ort`` reads
    them from disk), and a chat with many pictures would otherwise read that
    file once for each.
    """
    from app import speicherorte
    from app.api.v1.bilder import bilder_verzeichnis

    return bilder_verzeichnis(config), speicherorte.bildkopien_verzeichnis(config)


def _bild_quelle(pictures: Path, name: str) -> Path | None:
    """The file that goes to the model for a message's picture name — as far
    as this system can show it. ONE place, so warming and sending cannot
    drift apart: the warm-up builds copies for exactly what the send path
    would ask for.

    The same guard the picture route uses, so what the window can show and
    what a message can carry are the same set of files — a picture named by
    a run used to be visible on the wall and unattachable to a message.
    """
    from app import ordnerinhalt
    from app.api.v1.bilder import ANZEIGBARE_ENDUNGEN

    quelle = ordnerinhalt.sicherer_pfad(pictures, name)
    if quelle is None or quelle.suffix.lower() not in ANZEIGBARE_ENDUNGEN:
        return None
    return quelle


def _picture_path_sentences(pictures: Path, namen: list[str]) -> str:
    """Where each attached picture lies, said to the model and never shown.

    The picture itself travels as an image and carries no name; the model
    could look at it but not hand it on — to a job it starts, to a tool
    that changes it. So every attached picture that is really there gets one
    sentence with its place in the picture folder, the folder every run may
    read (app/dokumentablage.py ``program_folders``).
    """
    saetze = []
    for name in namen:
        quelle = _bild_quelle(pictures, name)
        if quelle is not None:
            saetze.append(
                f"[The image attached here is kept in the image folder as {quelle} "
                "— name that path when a tool or a job needs this picture.]"
            )
    return "\n".join(saetze)


def _bild_daten_url(places: tuple[Path, Path], name: str | None) -> str | None:
    """Reads an image as a data URL for the OpenAI image format.

    What goes in is the picture the MODEL should see, not necessarily the
    file on the wall: a large original has its smaller copy in the program's
    work folder under the data directory (app/speicherorte.py
    `bildkopien_verzeichnis`), readied OFF the event loop before the prompt
    rows are read (`bilder_vorbereiten`) — the copy is what the ladder in
    app/model_image.py made, not one fixed pass. The wall keeps the original
    untouched. ``places`` is `_picture_places` as the caller read it.

    This function only LOOKS UP (`model_image.nachschlag`): inside the
    request's no-await stretch no tool may start. A missing or unsuitable
    image is not a crash: the message then goes out without an image — the
    history must not fail over a deleted file. The same holds for a file
    whose bytes are no picture at all: it is left out and said in the log,
    never sent under a type it does not have.
    """
    if not name:
        return None
    from app import model_image

    pictures, copies = places
    quelle = _bild_quelle(pictures, name)
    if quelle is None:
        return None
    datei = model_image.nachschlag(quelle, copies)
    try:
        roh = datei.read_bytes()
    except OSError:
        # Gone between the lookup and the read — deleted, a volume dropped.
        # No crash, no image: this used to raise into a 500, and the chat
        # got no answer at all.
        return None
    try:
        return model_image.data_url(roh)
    except ValueError:
        # The name only: the folder is the user's own and stays out of the log.
        log.warning("Picture %s is not a png, jpeg or webp file; it is left out", quelle.name)
        return None


def bilder_vorbereiten(config, namen: list[str]) -> None:
    """Makes every picture a request will carry ready for the model —
    OUTSIDE the event loop: the route calls this through
    ``asyncio.to_thread``, because the FIRST look at a large picture starts
    a tool process that may take up to a minute, and the loop has to keep
    answering meanwhile. Inside the request's no-await stretch the same
    answers are found on record — `_bild_daten_url` only looks up
    (`model_image.nachschlag`), so a picture this warm-up could not prepare
    — a hung tool, a failed run — goes out whole instead of starting the
    tool again on the loop; the next answer's warm-up tries again.

    The source guard is shared with the send path (`_bild_quelle`): warming
    can neither drift wider nor narrower than sending.
    """
    from app import model_image

    if not namen:
        return
    pictures, copies = _picture_places(config)
    for name in namen:
        quelle = _bild_quelle(pictures, name)
        if quelle is None:
            continue
        model_image.kopie(quelle, copies)


def _ersatzsatz(zeile) -> str:
    """What a row that says nothing in words says instead.

    An empty message is not a harmless oddity: image parts are only valid in
    user messages on OpenAI-style servers, and a turn with nothing in it at
    all ends the next request with an error — the chat looks broken from
    then on. So a row that would otherwise travel empty says what it WAS.

    One place, because two callers need the same sentence: the request
    below, and the compaction request in ``app/chatverdichtung.py`` — which
    had no guard of its own and sent an empty message for every picture row
    in the middle.
    """
    eigene = zeile.bild_dateien() if zeile.role == "assistant" else []
    if eigene:
        # A picture the assistant carries was GENERATED, not seen.
        return (
            "[A generated image was shown here.]" if len(eigene) == 1
            else f"[{len(eigene)} generated images were shown here.]"
        )
    anhaenge = zeile.anhang_bilder()
    if anhaenge:
        # Only compaction ever reaches this line. In a live request such a
        # row travels WITH its picture and the picture carries the message,
        # so the empty text is fine there. A request that leaves the
        # pictures behind has to say the row was not blank, or the summary
        # loses the fact that anything was shown at all.
        return (
            "[An image was attached here.]" if len(anhaenge) == 1
            else f"[{len(anhaenge)} images were attached here.]"
        )
    return "[This turn produced no content.]"


def _zeilenworte(
    zeile,
    repositories: Repositories,
    *,
    volltext_mitschicken: bool = True,
    dokumentplan: dict | None = None,
) -> str:
    """The words ONE stored row contributes to a request: its content, the
    questions the model asked inside it, and the documents hanging on it.

    ``dokumentplan`` says per document what this request may carry of it
    (app/dokumentbudget.py): the whole text, or nothing — every document a
    row can name is in it, because discovery always resolves a context
    window before an endpoint counts as reachable, and the plan is built
    from that same window. A document the plan says nothing about (no plan
    at all, or a plan that simply omits it) is read the same safe way as
    one the plan explicitly says does not fit: named, not sent.

    Empty is a real answer here and not a failure — ``_verlauf_bauen`` wants
    to know, because a row that says nothing is worth a trace.
    ``zeilentext`` below is this same answer with ``_ersatzsatz`` applied.

    Split out of ``_verlauf_bauen`` rather than copied, because the same
    reading written twice is a reading that drifts — and it had already
    drifted: compaction was measuring and summarizing ``messages.content``,
    which is not what a row says. A document's text is not in that column;
    the row only POINTS at the document, and the text is prepended here, on
    every single request. Measured on a chat of forty short turns each
    carrying a 24,000-character document: ``content`` said 700 characters,
    the built request said 962,970.
    """
    inhalt = _with_invocation(zeile, zeile.content, ganz=volltext_mitschicken)
    # The model's own questions must survive the run they were asked
    # in: a later request rebuilds the history from stored messages,
    # and question and answer lived only in the tool log. A row that
    # stored its rounds sends them back as the call and result the run
    # sent (`_fragen_als_aufruf`); only an older row folds them into the
    # assistant text, so the model still knows what it asked and what the
    # user decided.
    werkzeuge = (zeile.stats or {}).get("werkzeuge") or []
    fragen = [
        w
        for w in werkzeuge
        if w.get("name") == frage_werkzeug.WERKZEUG_NAME
    ]
    if zeile.role == "assistant" and fragen and not _fragen_als_aufruf(werkzeuge):
        zeilen = "\n".join(
            "[You asked: {frage} — the user answered: {antwort}]".format(
                frage=(w.get("argumente") or {}).get("question", ""),
                antwort=w.get("ergebnis", ""),
            )
            for w in fragen
        )
        inhalt = f"{zeilen}\n{inhalt}" if inhalt else zeilen
    # Documents ride along through the whole history like images: the
    # extracted text is prepended to the message so that follow-up
    # questions can refer to it too. A deleted row is not a crash — the
    # message then goes out without the text. Several documents on one
    # message each prepend their own block; walked in reverse so the
    # first attachment ends up on top.
    for dokument_id in reversed(zeile.dokument_ids()):
        # Through the per-answer cache: this function runs over the same
        # rows several times per answer, and the text is the expensive part.
        dokument = dokumentcache.holen(repositories, dokument_id)
        if not dokument or not dokument.extracted_text:
            continue
        if not volltext_mitschicken:
            # Compaction's view (:func:`faltkopf`). The document is NAMED and
            # its size is stated, and its body stays out — measured
            # accurately above, sent short here, and the two are not in
            # conflict:
            #
            # * measuring it is the only way to know what the row costs in
            #   the prompt this fold is meant to shrink;
            # * sending it would make the compaction request LARGER than
            #   that prompt. A middle holding thirty-five such rows is
            #   840,000 characters, asked of a model whose context is
            #   already past the threshold. That request fails, the failure
            #   is caught as "did nothing", and the chat silently never
            #   folds — the exact failure this whole repair is about,
            #   rebuilt from the other side.
            #
            # What the summary has to carry instead is what the
            # conversation established ABOUT the document; the request text
            # in `app/chatverdichtung.py` asks for exactly that.
            inhalt = f"{faltkopf(dokument)}\n\n{inhalt}"
            continue
        ganz = dokument.extracted_text or ""
        anteil = (dokumentplan or {}).get(dokument_id)
        if anteil is None or not anteil.ganz:
            # Too big for this model's window (app/dokumentbudget.py), or a
            # plan that says nothing about this document at all — read the
            # same safe way, named rather than guessed at with a cut nobody
            # asked for. The model is told the document is attached and how
            # large it is, and told to say so rather than answer as though
            # it knew the content.
            kopf = (
                f'[Attached document "{dokument.filename}" — {len(ganz)} characters, '
                f"too large for this model's context and not included here. Say "
                f"so rather than answering as if you knew its content."
                f"{dokumentablage.nachlesehinweis(dokument.pfad, dokument.pages)}]"
            )
            inhalt = f"{kopf}\n\n{inhalt}" if inhalt else kopf
            continue
        # The plan says it fits: whole, however long.
        kopf = f'[Attached document "{dokument.filename}"]'
        fuss = "[End of document]"
        inhalt = f"{kopf}\n{ganz}\n{fuss}\n\n{inhalt}"
    # What the turn first went out with besides its own words belongs to
    # how the row reads, for the request and the fold alike.
    return _with_wake_notice(zeile, inhalt)


def faltkopf(dokument) -> str:
    """How a compaction request NAMES a document instead of carrying it.

    One line, written once: the fold of a chat's rows builds its request
    through :func:`_zeilenworte` above, the fold of a list in memory
    (``app/verdichtung.py``) has the built message in hand and takes the body
    back out of it (:func:`ohne_dokumentkoerper`). Both ways say the same
    thing about the same document, because it is the same sentence.
    """
    ganz = dokument.extracted_text or ""
    return (
        f'[Attached document "{dokument.filename}" — '
        f"{len(ganz)} characters, not included here. Only what this "
        f"conversation says about it is."
        f"{dokumentablage.nachlesehinweis(dokument.pfad, dokument.pages)}]"
    )


def ohne_dokumentkoerper(inhalt: str, dokumente) -> str:
    """The same message with each document named instead of carried.

    For the fold that works on the list in memory: its messages were built
    by :func:`_zeilenworte` with the bodies in, because that is what the
    round itself sends. A compaction request must not carry them — a middle
    of thirty-five document rows is hundreds of thousands of characters,
    asked of a model whose context is already past the threshold, and the
    request that comes back refused folds nothing.

    The block is the one written above, marker for marker, so nothing here
    guesses where a document begins and ends. A message whose block is not
    found (a document deleted since, a text rebuilt) keeps what it has: less
    is dropped than a guess would drop.
    """
    for dokument in dokumente or ():
        ganz = dokument.extracted_text or ""
        if not ganz:
            continue
        block = f'[Attached document "{dokument.filename}"]\n{ganz}\n[End of document]'
        if block in inhalt:
            inhalt = inhalt.replace(block, faltkopf(dokument))
    return inhalt


def _getragene_dokumente(zeile, repositories: Repositories) -> list:
    """The documents a row carries into a request — the same ones
    :func:`_zeilenworte` writes into its text: attached, and with a text."""
    return [
        dokument
        for dokument in (
            dokumentcache.holen(repositories, kennung) for kennung in zeile.dokument_ids()
        )
        if dokument and dokument.extracted_text
    ]


def zeilentext(
    zeile,
    repositories: Repositories,
    *,
    volltext_mitschicken: bool = True,
    dokumentplan: dict | None = None,
) -> str:
    """What one row says to a model — never nothing.

    The one door for anybody outside this module who needs the history as
    the MODEL sees it rather than as the ``content`` column stores it.
    """
    return _zeilenworte(
        zeile,
        repositories,
        volltext_mitschicken=volltext_mitschicken,
        dokumentplan=dokumentplan,
    ) or _ersatzsatz(zeile)


# How much of an earlier answer's tool result goes back to the model. A
# reader wanting the whole output has the card; the model needs to know
# what came back, not every line of it.
VERLAUF_ERGEBNIS_ZEICHEN = 500


def _ergebnis_im_verlauf(eintrag: dict, grenze: int | None = VERLAUF_ERGEBNIS_ZEICHEN) -> str:
    """What one earlier call returned, as a LATER request reads it.

    The one reading of a chat row's result, in here once and read by every
    caller below: the turns (``_werkzeugzuege``), the text block for a
    request without tools (``_werkzeuge_als_text``), the weight the fold is
    decided on (``werkzeuggewicht``) and the compaction request
    (``werkzeuge_fuer_die_faltung``). The first three go through
    ``_ergebnis_im_zug`` below, which writes the sentence for a result that
    came back empty: a request carries that sentence where this reading
    returns no text. A second reading instead of that one would be a second
    answer to the same question, and the callers would drift apart — which
    is exactly how one of them came to promise a picture nobody was
    sending.

    Two things happen here.

    A result that announced a picture of its own round says where the file is
    instead: the picture rode on a message of that round
    (``app/werkzeugbild.py``) and no later request rebuilds it, so "is
    attached below" was a sentence that had stopped being true. That note
    carries its own length and is NOT held to the ceiling below — cut, it
    would lose the end of the very path it exists to name. The turn that
    carried the image is not rebuilt either: byte for byte cannot hold on a
    round that read a picture, and the note is what stands in its place.

    Every other result is cut to ``VERLAUF_ERGEBNIS_ZEICHEN``, the cut every
    prompt of this chat has already made.

    Anything that is not text is no text: a call whose result was never a
    string returns nothing here, and ``_ergebnis_im_zug`` below writes its
    own sentence where that leaves a gap.

    A refusal carries two copies on the row — ``ergebnis`` for the window's
    own language, ``ergebnis_modell`` in English for exactly this later
    request. Preferred here over ``ergebnis`` so a second turn of the same
    chat does not hand the model back the window's language; a row saved
    before that second copy existed has only ``ergebnis`` and reads as it
    always did.
    """
    ergebnis = eintrag.get("ergebnis_modell", eintrag.get("ergebnis"))
    pfad = werkzeugbild.gelesener_bildpfad(str(eintrag.get("name") or ""), ergebnis)
    if pfad:
        return werkzeugbild.NICHT_MEHR_DABEI + dokumentablage.nachlesehinweis(pfad)
    text = ergebnis if isinstance(ergebnis, str) else ""
    if grenze is not None and len(text) > grenze:
        text = text[:grenze] + " …[truncated]"
    return text


def werkzeuggewicht(zeile) -> int:
    """How many characters a row's tool log adds to a prompt on top of its
    text — what ``_werkzeugzuege`` below sends for it.

    Compaction judges a fold by what the middle really puts into a request
    (app/chatverdichtung.py). Since an answer's calls travel back as calls,
    its text alone undercounts it by every argument and every capped
    result; a middle of twenty calls weighed by prose alone looks ten
    thousand characters lighter than it is, and a summary that saves
    plenty is thrown away as "no saving". Zero for every row that is not
    one of the model's own answers — the same rows the turns are built
    from, and no others.
    """
    if getattr(zeile, "role", None) != "assistant" or getattr(zeile, "art", None) != "nachricht":
        return 0
    eintraege = (zeile.stats or {}).get("werkzeuge") or []
    if not isinstance(eintraege, list):
        return 0
    gewicht = 0
    als_aufruf = _fragen_als_aufruf(eintraege)
    for eintrag in eintraege:
        if not isinstance(eintrag, dict) or not _geht_als_aufruf(eintrag, als_aufruf):
            continue
        argumente = eintrag.get("argumente")
        gewicht += (
            len(json.dumps(argumente, ensure_ascii=False)) if isinstance(argumente, dict) else 2
        )
        # Through the same reading the turns are built from, not through
        # `len(ergebnis)`: a result that announced a picture travels as a
        # note with a path, which is longer than the sentence it replaces,
        # and a weight taken from the stored string would report a saving
        # the request never made.
        gewicht += len(_ergebnis_im_zug(eintrag))
    return gewicht


def _ergebnis_im_zug(eintrag: dict, grenze: int | None = VERLAUF_ERGEBNIS_ZEICHEN) -> str:
    """One earlier call's result as a later request writes it — its text, and
    where there was none the sentence that stands for it.

    One reading for the weight and for the text: the fold trigger used to
    count a result as zero that goes out as a sentence, so every empty tool
    result made the middle look that much lighter than the request really
    is. Both the block and the turns write that sentence, taken from
    ``app/faltbitte.py``, which writes it for the compaction request too —
    that one keeps its own wider ceiling and its own cut, so what the two
    share is the sentence, not the rule around it.

    Empty means empty as ``_ergebnis_im_verlauf`` returns it: a result that
    is nothing but whitespace stays as the cut left it, because the turns
    then carry that cut and not nothing. The text block strips its end, so
    there the same result reads as the cut alone — under the floor the block
    was written for either way.
    """
    text = _ergebnis_im_verlauf(eintrag, grenze)
    return text if text.strip() else faltbitte.OHNE_AUSGABE


def _werkzeuge_als_text(gespeichert, inhalt: str) -> str:
    """An earlier answer's tool calls as text, for a request that offers no
    tools (see ``_verlauf_bauen``).

    The same picks as ``_werkzeugzuege`` — every call, a question to the
    user included where the row stored its rounds (``_fragen_als_aufruf``),
    each result read the same way — written as one block above the answer's
    text. The block weighs about what the turns would have,
    which is what ``werkzeuggewicht`` counts either way.
    """
    eintraege = (gespeichert.stats or {}).get("werkzeuge") or []
    if not isinstance(eintraege, list):
        return inhalt
    zeilen: list[str] = []
    als_aufruf = _fragen_als_aufruf(eintraege)
    for eintrag in eintraege:
        if not isinstance(eintrag, dict) or not _geht_als_aufruf(eintrag, als_aufruf):
            continue
        argumente = eintrag.get("argumente")
        # Stripped: this block promises one line per call, and nearly every
        # shell result ends in a newline.
        zeilen.append(
            f"- {eintrag['name']} "
            + json.dumps(argumente if isinstance(argumente, dict) else {}, ensure_ascii=False)
            + " → "
            + _ergebnis_im_zug(eintrag).strip()
        )
    if not zeilen:
        return inhalt
    # The same header the compaction request writes over its own tool block
    # (app/faltbitte.py), read from there rather than spelled a second time:
    # the block means the same thing in both, and a model that has learned to
    # read one reads the other.
    block = faltbitte.KOPFZEILE + "\n" + "\n".join(zeilen)
    return f"{block}\n\n{inhalt}" if inhalt else block


def werkzeuge_fuer_die_faltung(gespeichert, inhalt: str) -> str:
    """An earlier answer's tool calls as text for a COMPACTION request.

    The same picks as ``_werkzeuge_als_text`` above — every call, and a
    question to the user only where ``_zeilenworte`` did not already fold it
    into the text, where it would otherwise stand twice — written by the
    module that owns what a compaction request may carry
    (``app/faltbitte.py``).

    A separate function rather than a flag on that one, because the block
    is written there and read from a different store here. What a result
    may weigh is the same question in both and gets the same answer: a
    chat row's result goes into the request cut to
    ``VERLAUF_ERGEBNIS_ZEICHEN`` by ``_ergebnis_im_verlauf``, the cut every
    prompt of this chat has already made. The summarizer is the last reader
    of that result, but it is not a better-informed one: since the call ran,
    no prompt has shown the model more than these characters, so a summary
    asked to carry more would be asked to carry what nobody in this chat
    ever saw. A job is the other case and keeps the wider ceiling of
    ``app/faltbitte.py``: there the messages in the store carry the results
    whole, and its request is written from those.

    Zero tool text for every row that is not one of the model's own answers,
    the same set ``werkzeuggewicht`` weighs: a finished background run's
    report row carries a tool entry too, but the model never called it.
    """
    if (
        getattr(gespeichert, "role", None) != "assistant"
        or getattr(gespeichert, "art", None) != "nachricht"
    ):
        return inhalt
    eintraege = (gespeichert.stats or {}).get("werkzeuge") or []
    if not isinstance(eintraege, list):
        return inhalt
    als_aufruf = _fragen_als_aufruf(eintraege)
    return faltbitte.werkzeug_fuer_bitte(
        [
            (
                str(eintrag["name"]),
                eintrag.get("argumente"),
                _ergebnis_im_verlauf(eintrag),
            )
            for eintrag in eintraege
            if isinstance(eintrag, dict) and _geht_als_aufruf(eintrag, als_aufruf)
        ],
        inhalt,
    )


def _werkzeugzuege(gespeichert, inhalt: str) -> list[ChatNachricht]:
    """An earlier answer that used tools, in the shape the model produced it.

    The run builds one assistant turn per tool round — the text of that
    round and its calls — and hands the results back right after it; the
    next request has to begin with exactly those messages, byte for byte,
    or the model server reads everything from the first round on again
    (measured: a run of twelve rounds, the next message re-read
    all of it — 19,763 of 19,770 tokens came from the cache once this
    matched). So the round number, the round's text and the server's own
    call id are stored with each call while the run happens
    (``app/api/v1/generierung.py``, the tool log in the answer's row), and
    this rebuilds the very same turns from them. The closing text — what
    the answer said after its last round — goes back as its own turn, the
    way the run had it.

    This one used to feed such an answer back as its text alone: the model
    saw its own work as narration with gaps and, from the second answer on,
    narrated instead of calling. Measured with a 9B model: 22
    real calls in the first answer, none afterwards, empty fences named
    "applet-title" where the calls should have been.

    A row saved before those three were stored carries none of them: it
    reads the way it always did — every call in one turn, the ids made
    here, each result cut to ``VERLAUF_ERGEBNIS_ZEICHEN``. Providers only
    need call and result to match, so that shape still works; it just is
    not what went out.
    """
    eintraege = (gespeichert.stats or {}).get("werkzeuge") or []
    if not isinstance(eintraege, list):
        return []
    als_aufruf = _fragen_als_aufruf(eintraege)
    brauchbar = [
        e for e in eintraege if isinstance(e, dict) and _geht_als_aufruf(e, als_aufruf)
    ]
    if not brauchbar:
        return []
    if not als_aufruf:
        return _werkzeugzuege_alt(gespeichert, inhalt, brauchbar)

    # The calls of one round together, in the order they were made — grouped
    # over EVERY stored entry, not only over the ones that go back as calls:
    # the round's text and its thinking parts stand at the ROUND
    # (``app/api/v1/generierung.py``, ``_runde_im_protokoll``), on its first
    # entry, whichever that is.
    runden: list[tuple[object, list[dict]]] = []
    for eintrag in eintraege:
        if not isinstance(eintrag, dict):
            continue
        if runden and runden[-1][0] == eintrag.get("runde"):
            runden[-1][1].append(eintrag)
        else:
            runden.append((eintrag.get("runde"), [eintrag]))

    nachrichten: list[ChatNachricht] = []
    runden_texte: list[str] = []
    for runde, gruppe in runden:
        # Anywhere in the round, not only on its first call: an entry without
        # a name goes back as no call, and the round's text must not go with
        # it.
        text = next((e["text"] for e in gruppe if isinstance(e.get("text"), str)), "")
        if text:
            runden_texte.append(text)
        # The Responses wire's round items, stored beside the text by the
        # same first call (``app/api/v1/generierung.py``,
        # ``_runde_im_protokoll``): the encrypted thinking and the text parts
        # with their ``phase`` travel back out with this round, and a server
        # that has no record of its own thinking answers as if the model had
        # never thought. Absent on every other wire, and where they are
        # absent nothing is added.
        denkteile: list[dict] = next(
            (e["denkteile"] for e in gruppe if isinstance(e.get("denkteile"), list)), []
        )
        textteile: list[dict] = next(
            (e["textteile"] for e in gruppe if isinstance(e.get("textteile"), list)), []
        )
        # Row, round and number: the server's ids are unique inside ONE
        # response only, so a rebuilt history can meet the same id twice —
        # and a fallback that is not unique either makes two calls one.
        zuege = [e for e in gruppe if _geht_als_aufruf(e, als_aufruf)]
        aufrufe = [
            _aufruf_von(eintrag, nummer, f"{gespeichert.id[:8]}-{runde}")
            for nummer, eintrag in enumerate(zuege, start=1)
        ]
        # A round whose every entry is filtered out leaves no turn behind. An assistant turn with
        # nothing in it ends the request that follows (``_verlauf_bauen``).
        # Only words and calls count here: the wire's own parts travel with
        # a turn that carries one of those, and no wire sends a turn of
        # parts alone (`openai_responses._eingabe` drops it).
        if not (text or aufrufe):
            continue
        nachrichten.append(
            ChatNachricht(
                role="assistant",
                content=text,
                werkzeugaufrufe=aufrufe,
                reasoning_items=denkteile,
                message_items=textteile,
            )
        )
        nachrichten.extend(
            ChatNachricht(
                role="tool",
                content=_ergebnis_im_zug(eintrag, None),
                werkzeugaufruf_id=aufruf.id,
            )
            # Paired over the same list the calls were built from: an entry
            # of the group that goes back as no call has no result either.
            for eintrag, aufruf in zip(zuege, aufrufe, strict=True)
        )

    # Where the rounds end in the row's text. Not at its first character:
    # an attached document's text is prepended to it (`_zeilenworte`), so
    # such a row does not begin with its rounds.
    gesamt = "".join(runden_texte)
    stelle = inhalt.rfind(gesamt) if gesamt else 0
    if gesamt and stelle < 0:
        # The stored text and the rounds do not line up at all. Rebuilding
        # it round by round would drop text; the old shape carries all of it.
        return _werkzeugzuege_alt(gespeichert, inhalt, brauchbar)
    # What the answer said after its last round is no round of its own: it
    # goes back as its own turn, right behind them.
    schluss = inhalt[stelle + len(gesamt) :]
    # What stands BEFORE the rounds belongs to the row, not to a round — an
    # attached document's text (`_zeilenworte`) — and has no other place.
    kopf = inhalt[:stelle]
    if kopf:
        nachrichten.insert(0, ChatNachricht(role="assistant", content=kopf))
    if schluss:
        nachrichten.append(ChatNachricht(role="assistant", content=schluss))
    return nachrichten


def _fragen_als_aufruf(eintraege) -> bool:
    """Whether a row's questions to the user go back as the calls they were.

    The run sent a question as a call in its round's assistant turn and the
    user's answer as that call's result, under the server's id
    (``app/api/v1/generierung.py``). A row that stored its rounds is rebuilt
    that way, the question included: a sentence in front of the rounds made
    the next request differ from the run's last one from its first message
    on, and the model server read the whole answer again. A row from before
    the round marks has no round to put the call in; its questions stay the
    sentence `_zeilenworte` folds in front of its text.

    The KEY, not its value: rounds are counted from zero, so a row whose
    calls all stand in the first round carries `"runde": 0` — a value that
    is there and false at once.
    """
    return isinstance(eintraege, list) and any(
        isinstance(e, dict) and "runde" in e for e in eintraege
    )


def _geht_als_aufruf(eintrag: dict, fragen_als_aufruf: bool) -> bool:
    """Whether a stored call goes back to the model as a call.

    Not an entry without a name, which is no call at all, and not a question
    to the user where `_zeilenworte` folds it into a sentence instead — it
    would stand twice.
    """
    if not eintrag.get("name"):
        return False
    return fragen_als_aufruf or eintrag["name"] != frage_werkzeug.WERKZEUG_NAME


def _aufruf_von(eintrag: dict, nummer: int, zeilen_kennung: str) -> Werkzeugaufruf:
    """One stored call as the call it was — under the server's own id where
    the row carries it, and under one made here where it does not (an old
    row, or a call the run's log took down before that id existed).
    Providers only need call and result to match each other."""
    kennung = eintrag.get("kennung")
    argumente = eintrag.get("argumente")
    return Werkzeugaufruf(
        id=kennung if isinstance(kennung, str) and kennung else f"{zeilen_kennung}-{nummer}",
        name=str(eintrag["name"]),
        argumente=argumente if isinstance(argumente, dict) else {},
    )


def _werkzeugzuege_alt(gespeichert, inhalt: str, brauchbar: list[dict]) -> list[ChatNachricht]:
    """The shape a row without round marks goes back in — every call in one
    turn, the text as one piece, the ids made here, each result cut to
    ``VERLAUF_ERGEBNIS_ZEICHEN``. What this always did, kept for the rows
    that were written before the run stored round, text and id."""
    aufrufe: list[Werkzeugaufruf] = []
    ergebnisse: list[ChatNachricht] = []
    # Numbered over the row's own log, the way this always did: the entries
    # this rebuild leaves out — a question the run answered itself — keep
    # their number, so an old row goes out under the same ids as before.
    for nummer, eintrag in enumerate(
        [e for e in (gespeichert.stats or {}).get("werkzeuge") or [] if isinstance(e, dict)],
        start=1,
    ):
        if not _geht_als_aufruf(eintrag, False):
            continue
        kennung = f"{gespeichert.id[:8]}-{nummer}"
        argumente = eintrag.get("argumente")
        aufrufe.append(
            Werkzeugaufruf(
                id=kennung,
                name=str(eintrag["name"]),
                argumente=argumente if isinstance(argumente, dict) else {},
            )
        )
        ergebnisse.append(
            ChatNachricht(
                role="tool",
                content=_ergebnis_im_zug(eintrag),
                werkzeugaufruf_id=kennung,
            )
        )
    return [
        ChatNachricht(role="assistant", content=inhalt, werkzeugaufrufe=aufrufe),
        *ergebnisse,
    ]


def _clock_sentence(gespeichert) -> str | None:
    """The clock sentence this turn was first sent with, if it carried one.

    What it carries is the date block of the day that turn went out on
    (``app/grundprompt.environment_block``), or — in rows written before
    that — a sentence naming the very minute. Neither can be worked out
    again afterwards: the date may have turned over, and the minute
    certainly has. A request is only read again from the first byte that
    differs, so a prefix that moves between turns moves a row in the middle
    of the history and with it everything behind it. What the turn carried
    when it went out is written onto the row by the request route
    (``app/api/v1/generierung.py``, metrics key ``clock_sentence``,
    ``app/db/repositories/messages.py``), and this reads it back.

    A row that carries none gets none. Rows written before the sentence was
    remembered went out without one, and a fresh sentence in front of them
    would be exactly the change this exists to avoid.
    """
    satz = (getattr(gespeichert, "stats", None) or {}).get("clock_sentence")
    return satz if isinstance(satz, str) and satz else None


def _with_invocation(zeile, inhalt: str, ganz: bool = True) -> str:
    """A turn the user picked a skill in, as it went out: the note and the
    instruction (``app/skills.py``, ``invocation``) right in front of their
    words, and the "/name" the stored text keeps taken off them. Written onto
    the row once, under its metrics (``skill_invocation``), and read back
    here byte for byte — in the turn and not in the system message, so it
    does not move the front of the request, and every later request carries
    it the way the first did, until a fold takes the row. Documents on the
    row go above all of it, so the hand-over line stands right before the
    words it hands over to.

    The fold's view (``ganz`` false) keeps only the note that the skill was
    invoked, the way it names a document instead of sending its text: the
    instruction is on disk, and sent whole for every such turn it would make
    the request that is meant to shrink the history larger.
    """
    invocation = (getattr(zeile, "stats", None) or {}).get("skill_invocation")
    if not isinstance(invocation, str) or not invocation:
        return inhalt
    if not ganz:
        invocation = invocation.split("\n", 1)[0]
    name = skills.invoked_name(invocation)
    worte = skills.words_after_command(inhalt, name) if name else inhalt
    return f"{invocation}\n\n{worte}" if worte else invocation


def _with_wake_notice(zeile, inhalt: str) -> str:
    """The report a wake was started for, with the notice it went out with
    behind it (``app/hintergrundwecken.py``) — written onto the row once,
    under its metrics (``wake_notice``), and sent with it until a fold takes
    the row. Never a row of its own, so nothing stands as the user's that
    they did not write."""
    notice = (getattr(zeile, "stats", None) or {}).get("wake_notice")
    if not isinstance(notice, str) or not notice:
        return inhalt
    return f"{inhalt}\n\n{notice}" if inhalt else notice


def _als_modellnachricht(gespeichert) -> tuple[str, bool]:
    """How one stored row reaches the model: its role, and who wrote it.

    A finished background run's report is stored as an assistant row so the
    window files it with the answer, but the model never SAID it — the
    service did. Handed back as the model's own words, it took the shape for
    its own and wrote reports of its own making: asked to "wait and see", a
    27B model produced "[background run #2 finished: …]" with a console
    block, ten seconds before the real report existed, saying "finished"
    where the real one said "failed with exit code 127". A report is told to
    the model, the way every other client hands system notices over — as the
    user's side of the conversation.

    The second value says that once more in a form a reader of the finished
    list can still see: `art` is gone by then, and the environment block goes
    in front of a turn the user spoke, never in front of what the service
    wrote in their voice (app/grundprompt.restore_environment_block).

    ONE rule, and every way in asks it: this function, the branch for
    attachments the model cannot see, the branch for a row that carries a
    picture of its own (where a report lands, because `speichern` mirrors its
    first attachment into `bild`), and the fold's own request
    (`app/chatverdichtung.als_bitte`). None of them may hand a report over as
    the model's own words. The word itself stands once, in
    `app/db/repositories/messages.ist_dienstbericht`.
    """
    dienstbericht = ist_dienstbericht(gespeichert.art)
    return ("user" if dienstbericht else gespeichert.role), dienstbericht


def on_users_side(gespeichert) -> bool:
    """Whether a stored row is the user speaking — a turn they wrote, or a
    fold's summary standing in for earlier ones.

    Not the same question as who the row is attributed to. A finished
    background run's report is stored as the model's own answer (``art``
    "werkzeugmeldung") and only LOOKS like the user's side once
    `_verlauf_bauen` hands it over as one; a picture (``art`` "bild",
    "bildlauf") is the model's too. Both are the service talking, and the
    environment block belongs in front of neither
    (app/grundprompt.restore_environment_block). What is left in — a fold's
    summary and the notice standing for a stretch a reading left out
    (``art`` "verdichtung") — is what the user's side of this conversation
    says now; it is what the block stands in front of where no turn of their
    own is left.

    Asked here once because both ends of the build need the same answer: the
    request route picks the row the block is written onto by it
    (app/api/v1/generierung.py), the message built from a row the service
    wrote says so itself through ``ChatNachricht.service_report``, and the
    clock sentence and the dictation anchor below ask it too. A rule stated
    in four places is a rule that drifts in three of them.

    Read by `art` and not by `role` alone: every writer of a report or a
    picture stores it as an assistant row today, so ``role == "user"`` would
    answer the same — by accident, and only until the next writer. The kind
    of row is what the question is about.
    """
    return (
        gespeichert.role == "user"
        and (gespeichert.art or "nachricht") not in {"werkzeugmeldung", "bild", "bildlauf"}
    )


def _verlauf_bauen(
    chat: Chat,
    repositories: Repositories,
    system_prompt: str,
    config=None,
    vision: bool = True,
    zeilen: list | None = None,
    werkzeuge: bool = True,
    dokumentplan: dict | None = None,
    gespraechsanweisung: str | None = None,
) -> list[ChatNachricht]:
    """Builds the message list for a request.

    ``gespraechsanweisung`` — a spoken turn's instruction, the note that
    the model's previous reply was stopped (app/stop_note.py), or both —
    goes in front of the newest user turn's content
    ONLY — the one this call was made for, never an earlier one already
    sitting in ``zeilen``. It touches the ``ChatNachricht`` built here, not
    the stored row: the database keeps exactly what was said, and a fold of
    the history later reads that same unprefixed text
    (app/verdichtung.py). Applied after the loop below rather than passed
    into it, so the ordinary per-row handling — images, tool calls, the
    background-report role swap — never has to know this exists. The clock
    sentences land after it, so the order the two have always had holds:
    the sentence of that turn first, behind it the instruction, then the
    words the user spoke.

    The row it lands on is tracked by the loop itself
    (``letzter_echter_nutzer_index``), not found afterward by scanning for
    ``role == "user"``: a finished background run's report is stored as an
    assistant row and travels as ``role="user"`` too (see the comment on
    that swap below), and can legitimately sort after the turn this
    instruction actually belongs to — the one window the read above the
    loop already lives with. Scanning backward for the first "user" would
    catch that report instead and prefix the instruction onto a sentence
    nobody spoke.

    Every user turn that carries a prefix goes out with the one it was first
    sent with (``_clock_sentence`` above): the request route hands it to the
    row as it sends it, and here it is handed back. That is the date block
    on the row of a day that has one, and the sentence naming a minute in
    rows written before it — a turn in the middle of a day carries neither.
    Worked out again instead, the prefix would change the row every minute
    or at the turn of the day — and a request is only read again from the
    first byte that differs, so everything behind that row would be read
    again with it.

    ``zeilen`` is the model's history as the caller has already read it —
    handed in so one answer reads it once, not once per consumer. Left
    out, it is read here, which is what every other caller does.

    ``werkzeuge`` is whether THIS request offers tools. Only then do
    earlier answers go back as calls and results (``_werkzeugzuege``):
    a request whose messages carry tool calls but whose body names no
    tools is refused by Anthropic ("must define tools"), so a chat that
    once used tools would fail on every turn after they were switched off
    or the model was swapped for one without them. Without the offer the
    answer travels as its text, the way it did before.

    The system prompt is not part of the history and is not stored — it is
    prepended here on every request, as the request route built it: once
    per chat, anew when the user changes something in it or the chat folds
    (app/api/v1/generierung.py, `_system_messages`).

    ``prompt_aus`` on the chat suspends the USER's prompt — their character
    and their own rules. It does not suspend the shipped instructions: those
    describe how this machine works and include the rule that a tool result
    is data and not an order. Switching that off to see a model answer "raw"
    would switch off the guard rails with it, and nothing on the switch says
    so. One control, one job.
    """
    nachrichten: list[ChatNachricht] = []
    if system_prompt:
        nachrichten.append(ChatNachricht(role="system", content=system_prompt))
    # `fuer_das_modell`, not `auflisten`: the reader gets every line of a
    # chat, the model gets every line a summary does not already speak for.
    # They are the same list until something is folded — and the day
    # compaction is switched on, a builder still reading `auflisten` would
    # send the summary IN ADDITION to everything it replaced, so compacting
    # would make the prompt bigger. Read from the right side now, while the
    # two are identical and the change cannot break anything.
    if zeilen is None:
        zeilen = repositories.messages.fuer_das_modell(chat_id=chat.id)
    # Which entry the conversation instruction belongs on, if it lands at
    # all — set only when the STORED row itself was the user's own turn,
    # never when a later branch relabels a different row "user".
    letzter_echter_nutzer_index: int | None = None
    # The clock sentence of every user turn, by its place in `nachrichten`.
    # Hung in front of those rows after the loop — after the instruction, so
    # the instruction keeps standing where it always has (see the docstring).
    clock_sentences: list[tuple[int, str]] = []
    # Where the pictures and their copies live — read at the first picture,
    # then kept for the rest of this build (`_picture_places`).
    picture_places: tuple[Path, Path] | None = None
    for gespeichert in zeilen:
        # The reasoning does not belong in the history — it is display, not
        # context. Everything that DOES belong is one call: `_zeilenworte`
        # above, shared with compaction so the two readings of a row cannot
        # drift apart. Unguarded on purpose — an empty answer is a fact this
        # loop wants, for the trace below.
        inhalt = _zeilenworte(
            gespeichert,
            repositories,
            dokumentplan=dokumentplan,
        )
        eigene_bilder = gespeichert.bild_dateien() if gespeichert.role == "assistant" else []
        if eigene_bilder:
            # A picture the assistant carries was GENERATED, not seen. Image
            # parts are only valid in user messages on OpenAI-style servers,
            # and an assistant turn consisting of nothing but an image (or,
            # for a run, nothing at all — `content` is '' there) ends the
            # next request with an error — the chat looks broken from then
            # on. The model gets a sentence instead: enough to know the
            # picture(s) exist, and never an empty turn.
            #
            # The report rule reaches in here too: `speichern` mirrors the
            # first attachment into the scalar `bild` (app/db/repositories/
            # messages.py:131), so a REPORT row that ever carries an
            # attachment arrives in this branch rather than the one below —
            # and it is a report either way, never the model's own words.
            rolle, dienstbericht = _als_modellnachricht(gespeichert)
            nachrichten.append(
                ChatNachricht(
                    role=rolle,
                    service_report=dienstbericht,
                    content=inhalt or _ersatzsatz(gespeichert),
                )
            )
            continue
        # An answer that used tools goes back in the shape it was made in —
        # calls and results, not prose alone (see `_werkzeugzuege`). Only
        # the model's own answers: a background run's report row carries a
        # tool entry too, but the model never called it, it reads it. And
        # only while the request offers tools at all (see the docstring);
        # without the offer the calls go back as text, because what the
        # tools answered is what the conversation was built on — dropped
        # with the turns, the model read "Done." and had no idea what the
        # commands returned.
        if gespeichert.role == "assistant" and gespeichert.art == "nachricht":
            if werkzeuge:
                werkzeugzuege = _werkzeugzuege(gespeichert, inhalt)
                if werkzeugzuege:
                    nachrichten.extend(werkzeugzuege)
                    continue
            else:
                inhalt = _werkzeuge_als_text(gespeichert, inhalt)
        if gespeichert.role == "assistant" and not inhalt:
            # Every empty assistant row, not just a lauf's
            # own — an aborted answer with no picture at all falls through
            # exactly the same way `bild_dateien()` coming back empty does
            # (a damaged `bilder` value B7a normalized to None, or, in
            # principle, a row with no real filename in it at all, though
            # `lauf_bild_speichern` never actually produces one). An
            # assistant turn with nothing in it ends the next request
            # exactly as one with only a picture would, regardless of
            # which of those reasons caused it — caught here as the
            # general case, not reasoned about case by case.
            #
            # B7e: this branch firing at all is itself worth a trace —
            # it means something about this row was not what it should
            # have been, whether B7a already logged its own reason or not.
            log.warning(
                "Message %s: assistant row without content and without a picture "
                "replaced in the history",
                gespeichert.id,
            )
            # Through `_ersatzsatz` like the branch above, so the sentence
            # lives in one place. It answers "[This turn produced no
            # content.]" for every row that can actually get here: reaching
            # this line at all means `bild_dateien()` came back empty, and
            # `speichern` never writes an attachment list without also
            # filling the scalar that method falls back on.
            nachrichten.append(
                ChatNachricht(role="assistant", content=_ersatzsatz(gespeichert))
            )
            continue
        anhaenge = gespeichert.anhang_bilder()
        # Without a config there is no picture folder to name (a caller of
        # its own, the way the picture URLs below need one too).
        if anhaenge and config is not None:
            if picture_places is None:
                picture_places = _picture_places(config)
            path_sentences = _picture_path_sentences(picture_places[0], anhaenge)
            if path_sentences:
                inhalt = f"{inhalt}\n{path_sentences}" if inhalt else path_sentences
        if anhaenge and not vision:
            # An earlier attachment, but the model at the wheel now cannot
            # see. Saying so beats silently dropping it: asked about the
            # picture, the model can answer honestly instead of inventing
            # its contents.
            hinweis = (
                "[An image was attached here that this model cannot see.]"
                if len(anhaenge) == 1
                else f"[{len(anhaenge)} images were attached here that this model cannot see.]"
            )
            rolle, dienstbericht = _als_modellnachricht(gespeichert)
            nachrichten.append(
                ChatNachricht(
                    role=rolle,
                    service_report=dienstbericht,
                    content=f"{inhalt}\n{hinweis}" if inhalt else hinweis,
                    dokumente=_getragene_dokumente(gespeichert, repositories),
                    compacted_summary=gespeichert.art == "verdichtung",
                )
            )
            if on_users_side(gespeichert):
                letzter_echter_nutzer_index = len(nachrichten) - 1
                if (satz := _clock_sentence(gespeichert)):
                    clock_sentences.append((letzter_echter_nutzer_index, satz))
            continue
        image_urls: list[str] = []
        if anhaenge:
            if picture_places is None:
                picture_places = _picture_places(config)
            image_urls = [
                url
                for url in (_bild_daten_url(picture_places, name) for name in anhaenge)
                if url
            ]
        rolle, dienstbericht = _als_modellnachricht(gespeichert)
        nachrichten.append(
            ChatNachricht(
                # The report question and the environment-block question, one
                # rule for both ways in — see `_als_modellnachricht`.
                role=rolle,
                service_report=dienstbericht,
                content=inhalt,
                # Images remain part of the context: earlier attachments go
                # along again too, otherwise the model cannot refer to them.
                bild_urls=image_urls,
                # Which documents this message carries, for a fold of the
                # list in memory to name them (app/verdichtung.py).
                dokumente=_getragene_dokumente(gespeichert, repositories),
                # A summary row, marked by its kind: a fold of the list in
                # memory passes its document sentences on, and the answer
                # finds its own summary, by this mark alone.
                compacted_summary=gespeichert.art == "verdichtung",
            )
        )
        if on_users_side(gespeichert):
            letzter_echter_nutzer_index = len(nachrichten) - 1
            if (satz := _clock_sentence(gespeichert)):
                clock_sentences.append((letzter_echter_nutzer_index, satz))
    # The instruction first, in front of the newest user turn's content and
    # nowhere else: it belongs to this one request and is never stored, so no
    # later request meets it again. It touches the ``ChatNachricht`` built
    # here, not the stored row, which keeps exactly what was said.
    if gespraechsanweisung and letzter_echter_nutzer_index is not None:
        eintrag = nachrichten[letzter_echter_nutzer_index]
        eintrag.content = (
            f"{gespraechsanweisung}\n\n{eintrag.content}"
            if eintrag.content
            else gespraechsanweisung
        )
    # What an earlier run's clearing replaced in ITS request, and as which of
    # the two sentences. The answer's row remembered it at its closing write
    # (app/api/v1/generierung.py, ``geraeumt``), and the rebuild hands the
    # model the same replacement the run sent: without this the next request
    # carried the whole results again, the request after an answer read
    # differently from the request inside it, and the server read everything
    # from the first cleared round on anew (the same rule as a cut tool
    # result). The rows
    # keep every character; only the prompt is shortened.
    geraeumt: dict[str, str] = {}
    for gespeichert in zeilen:
        geraeumt.update((getattr(gespeichert, "stats", None) or {}).get("geraeumt") or {})
    if geraeumt:
        for nachricht in nachrichten:
            if nachricht.role != "tool" or not nachricht.werkzeugaufruf_id:
                continue
            satz = werkzeugkuerzung.ERSETZUNGEN.get(
                geraeumt.get(nachricht.werkzeugaufruf_id, ""), ""
            )
            if satz:
                nachricht.content = satz
    # And then the clock sentences, last so that they land in FRONT of the
    # instruction — the order they have always had. Every user turn carries
    # the one it was first sent with.
    for stelle, satz in clock_sentences:
        eintrag = nachrichten[stelle]
        eintrag.content = f"{satz}\n\n{eintrag.content}" if eintrag.content else satz
    return nachrichten
