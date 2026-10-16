"""``/compact``: folds the middle of the open chat once, now, with the words
behind the command as the topic the summary is to keep to.

The client only asks. The service folds, and says in one word what came of
it; this module turns that word into the line the window would show: the
seam where it folded, or the sentence for why it did not.
"""

from __future__ import annotations

import threading

from cli import chat
from cli.interfaces import Context

# What the service answers with.
FOLDED = "folded"
TOO_SHORT = "too_short"
NO_SAVING = "no_saving"
STOPPED = "stopped"


def run_command(ctx: Context, argument: str) -> None:
    texts = ctx.texts
    session = ctx.session
    opened = session.chat
    if opened is None:
        # A chat the service does not have yet has nothing to fold.
        ctx.renderer.notice(texts.t("eingabe.compact_too_short"))
        return
    if session.answering:
        ctx.renderer.notice(texts.t("fehler.antwort_laeuft_schon"))
        return
    body = {"endpoint_id": session.endpoint_id, "topic": argument.strip() or None}
    # The interrupt key ends the request the way it ends an answer: the
    # service is asked to stop, and answers with ``stopped``. The key is
    # handled on the screen's own thread, so the asking goes off it.
    session.cancel_wait = lambda: threading.Thread(
        target=chat.stop, args=(ctx,), daemon=True
    ).start()
    ctx.screen.set_activity(texts.t("status.komprimiert"))
    try:
        answer = ctx.client.post(f"/chats/{opened['id']}/compact", json=body)
    finally:
        session.cancel_wait = None
        ctx.screen.set_activity(None)
    result = answer.get("result") if isinstance(answer, dict) else None
    if result == FOLDED:
        replaced = answer.get("replaced") if isinstance(answer, dict) else None
        if isinstance(replaced, int) and not isinstance(replaced, bool) and replaced > 0:
            ctx.renderer.remark(texts.t("nachricht.verdichtet", anzahl=replaced))
        else:
            ctx.renderer.remark(texts.t("nachricht.verdichtet_ohne_zahl"))
    elif result == TOO_SHORT:
        ctx.renderer.notice(texts.t("eingabe.compact_too_short"))
    elif result == NO_SAVING:
        ctx.renderer.notice(texts.t("eingabe.compact_no_saving"))
    elif result == STOPPED:
        # Stopped by the person: nothing folded, nothing to say.
        return
    else:
        ctx.renderer.error(texts.t("nachricht.komprimieren_fehlgeschlagen"))
