"""What a finished background run leaves behind in the chat.

The run itself lives in ``app/tools/hintergrund.py`` and knows nothing about
the database — a tool that writes messages would be a tool that can write
anything. The service hangs this handler in at startup, and it does the one
thing the run cannot: put the result where both the user and the model will
see it.

Both at once, on purpose. A note only the window shows would be invisible to
the model at the next question, and a result only the model sees would look
to the user as if nothing had happened.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable

from app.db import Repositories
from app.tools.hintergrund import FEHLER, LAEUFT, Lauf, laeufe

log = logging.getLogger(__name__)

# As much as a tool result carries in the message log — beyond that nobody
# reads it and the context pays for it.
MAX_ZEICHEN = 2_000


def _text(lauf: Lauf, antwort: str) -> str:
    """The line above, and the raw output below it inside a fence.

    Without the fence the output is read as Markdown on its way to the
    window: the lines of a paragraph are glued together with a space, a row
    of dashes turns into a rule, a line beginning with "- " into a list item,
    and the indentation is dropped — an `ls -la` arrives as one long
    sentence. The fence also says plainly to the model that this is what a
    command wrote, not prose.

    `console` and not `bash`: output is not source. The highlighter does not
    know that name and leaves the text exactly as it is, which is the point —
    colouring output would invent a syntax that is not in it.
    """
    ausgang = "finished" if lauf.code == 0 else f"failed with exit code {lauf.code}"
    kopf = f"[background run #{lauf.nummer} {ausgang}: {lauf.befehl}]"

    gekappt = antwort[:MAX_ZEICHEN]
    # A run that wrote nothing gets no empty box to show for it.
    if not gekappt.strip():
        return kopf

    # The fence has to be longer than every run of backticks in the output,
    # otherwise the output closes it halfway and the rest of the message
    # falls apart — a grep for fences does exactly that. Measured on the
    # CUT text: what was thrown away can no longer close anything.
    laengste = max((len(fund) for fund in re.findall("`+", gekappt)), default=0)
    zaun = "`" * max(3, laengste + 1)

    # The cut can land anywhere, in the middle of a line included, so the
    # closing fence is put on a line of its own. A fence left open would
    # swallow everything drawn after it.
    umbruch = "" if gekappt.endswith("\n") else "\n"
    return f"{kopf}\n\n{zaun}console\n{gekappt}{umbruch}{zaun}"


def am_aufruf_nachtragen(
    eintrag: dict[str, Any], lauf: Lauf, antwort: str | None = None
) -> None:
    """The run's ending, written onto the tool-log entry of the call that
    started it.

    The call's own result was the sentence "started as run #N" — true when
    it was written, useless once the run is over. The reader wants the
    output where the command stands, not in a row of its own under a
    growing answer: that row still exists (the model reads it, the wake
    hangs on it), the window no longer draws it. Same fields as the row's
    entry, so a card reads the same whichever of the two filled it.
    """
    ausgabe = (antwort if antwort is not None else lauf.ausgabe)[:MAX_ZEICHEN]
    eintrag["lauf_nummer"] = lauf.nummer
    eintrag["exit_code"] = lauf.code
    # The state as well as the code: a run stopped at the time limit, one
    # cut off by a shutdown and one the user stopped all end with no code,
    # and a card reading the code alone took every one of them for "still
    # running" once the run had left memory — for good. And "failed" is
    # what the state says, not what a missing code implies: a stopped run
    # is a fact, not a fault.
    eintrag["lauf_zustand"] = lauf.zustand
    eintrag["fehlgeschlagen"] = lauf.zustand == FEHLER
    eintrag["dauer_sekunden"] = lauf.dauer_sekunden
    # An empty output is an empty output: the card says "nothing written"
    # for an empty string and "still running" only for None.
    #
    # The window wants the output where the command stands; the MODEL does
    # not read it here — the ending reaches it in the report row of its own
    # ("[background run #N finished …]", ``fertig`` below, and
    # ``app/verlaufsbau.py`` hands that row over as a service report). The
    # call's copy for the model therefore stays the sentence the run itself
    # sent ("Started in the background as run #N …", ``app/tools/shell.py``):
    # that is what it read inside the run, and rewriting it here made the
    # next request differ from the run at exactly this call — with the
    # output standing in it twice.
    vorher = eintrag.get("ergebnis", "")
    eintrag["ergebnis"] = ausgabe if ausgabe.strip() else ""
    if vorher:
        eintrag.setdefault("ergebnis_modell", vorher)


def nachtragen(protokoll: list[dict[str, Any]], chat_id: str) -> None:
    """Every entry of a tool log whose background run has since ended gets
    that ending — for the answer's own closing write, where the log is still
    in memory and would overwrite anything written into the row from
    outside.

    Background runs only. A foreground command carries a run number too
    (the panel pairs by it), but its entry already holds the tool's own
    answer — output, stderr, exit code, or "(done, no output)" — and is
    always finished by the time the answer closes; rewriting it from the
    raw run turned "(done, no output)" into nothing and an exit code of one
    into a failure the tool had not called one.
    """
    for eintrag in protokoll:
        nummer = eintrag.get("lauf_nummer")
        if nummer is None:
            continue
        lauf = laeufe.holen(chat_id, nummer)
        if lauf is None or not lauf.hintergrund or lauf.zustand == LAEUFT:
            continue
        am_aufruf_nachtragen(eintrag, lauf)


def _aufruf_nachtragen(repositories: Repositories, lauf: Lauf, antwort: str) -> None:
    """The stored answer that started this run gets the ending on its entry.

    Only an answer that has already ended: one still being written keeps
    its log in memory and writes it at its own end (``nachtragen`` above),
    and a row rewritten from here would be overwritten a moment later.

    The row is the one the run was stamped with when its call returned
    (``Lauf.antwort_id``), not the newest row carrying the number: numbers
    are per chat, a stored row from before a restart can carry the same
    one, and a search that walked the chat from the front stopped at its
    five-hundredth row anyway. A run without a stamp was not started by an
    answer this service wrote — there is no card to fill.
    """
    if not lauf.antwort_id:
        return
    try:
        zeile = repositories.messages.holen(lauf.antwort_id)
    except Exception:  # noqa: BLE001 - a missing card is not worth the service
        log.exception("Answer to background run #%s cannot be read", lauf.nummer)
        return
    if zeile is None or zeile.role != "assistant" or zeile.art != "nachricht":
        return
    if zeile.zustand == "laeuft":
        return
    werkzeuge = list((zeile.stats or {}).get("werkzeuge") or [])
    eintrag = next(
        (w for w in werkzeuge if isinstance(w, dict) and w.get("lauf_nummer") == lauf.nummer),
        None,
    )
    if eintrag is None:
        return
    am_aufruf_nachtragen(eintrag, lauf, antwort)
    stats = dict(zeile.stats or {})
    stats["werkzeuge"] = werkzeuge
    try:
        repositories.messages.inhalt_aktualisieren(
            zeile.id, content=zeile.content, reasoning=zeile.reasoning, stats=stats
        )
    except Exception:  # noqa: BLE001 - the report row is written; the card heals on the next run
        log.exception(
            "End of background run #%s not noted at its call", lauf.nummer
        )


def anmelden(
    repositories: Repositories,
    wecken: Callable[[str], Any] | None = None,
) -> None:
    """From now on every finished background run reports into its chat.

    ``wecken`` is the second handle, and the service hangs it in for the
    same reason it hangs in this one: a run that could start a model run
    would be a tool that can start model runs. Without it the report is
    written and left lying — which is exactly how it was, and why a chat
    fell silent the moment the model handed work off
    (``app/hintergrundwecken.py``).
    """

    def fertig(lauf: Lauf, antwort: str) -> None:
        # A run whose chat was deleted mid-flight: the row is gone, the
        # insert below could only fail its foreign key. Nothing to report,
        # nobody to report to.
        if lauf.vergessen:
            return
        try:
            repositories.messages.speichern(
                chat_id=lauf.chat_id,
                # Still an assistant turn as far as the model's history is
                # concerned — the next request has to read what the command
                # wrote — but `art` says out loud that it is a tool report
                # and not something the model said.
                #
                # Without it this row was indistinguishable from an answer
                # still being written: assistant, and no cancel mark in the
                # metrics. A window opening the chat mid-run adopted it as
                # the answer, emptied it and refilled it from the replayed
                # stream; "send again" would have deleted it; the regenerate
                # arrow attached itself to it; and the reader saw the same
                # output twice, once in the tool card and once as text.
                role="assistant",
                content=_text(lauf, antwort),
                art="werkzeugmeldung",
                stats={
                    "werkzeuge": [
                        {
                            "name": "run_command",
                            "server": "shell",
                            "argumente": {"command": lauf.befehl, "background": True},
                            "fehlgeschlagen": lauf.zustand == FEHLER,
                            # Which run, and what it exited with. Both used
                            # to travel in the header line of the text
                            # ("[background run #3 failed with exit code
                            # 1: ...]"); once that line stopped being drawn
                            # -- it repeated the command a second time --
                            # they were nowhere at all. THAT a run failed
                            # was still visible, WHICH one and how was not.
                            #
                            # So they belong in the entry rather than in
                            # prose: the card can then say "#3" beside the
                            # name and "exit 1" where the word
                            # "fehlgeschlagen" stood, and the command stays
                            # written exactly once.
                            "lauf_nummer": lauf.nummer,
                            "exit_code": lauf.code,
                            "lauf_zustand": lauf.zustand,
                            "ergebnis": antwort[:MAX_ZEICHEN],
                            # Same raw text, not a translated one — the
                            # model's own copy (app/verlaufsbau.py).
                            "ergebnis_modell": antwort[:MAX_ZEICHEN],
                        }
                    ]
                },
            )
        except Exception:  # noqa: BLE001 - a lost note must not take the service with it
            log.exception("Result of a background run could not be stored")
            # And no wake either. What the woken answer would read is the
            # report — a run started over a report that was never written
            # would send the model back into a history that has not changed.
            return
        # And onto the call that started it, where the reader looks for it.
        _aufruf_nachtragen(repositories, lauf, antwort)
        if wecken is not None:
            wecken(lauf.chat_id)

    laeufe.abschluss = fertig
    # And where a chat's numbering continues from: after the highest number
    # its rows already carry, so a restart does not hand a new run the
    # number of a stored call (see ``Laufverwaltung.nummernstart``).
    laeufe.nummernstart = lambda chat_id: repositories.messages.hoechste_laufnummer(
        chat_id=chat_id
    )
