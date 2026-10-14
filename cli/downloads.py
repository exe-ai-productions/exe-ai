"""``/download``: search a model, choose one of its files, fetch it — and
set or remove the Hugging Face token.

The service fetches one file at a time and says how far it is. The client
only names the file the way the window does (``/runner/download``), looks at
the state every few seconds and says it. In the chat the fetch goes on beside
it — the line above the status line shows how far it is and the input stays
free; from outside the command waits for the end and ends with it.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from cli import glyphs, servers
from cli.client import ServiceError, ServiceUnreachable
from cli.interfaces import Context, Entry

# The words behind ``/download`` that are no part of the search.
STOP = "stop"
TOKEN = "token"
REMOVE = "remove"

# The word that names the kind of model, and the tab of the catalogue it
# means. Any other first word belongs to the search.
KINDS = {"embedding": "einbettung", "speech": "sprache"}
CHAT = "chat"

# The longest search the service takes.
_QUERY_LIMIT = 100

# What the state of a fetch names as its reason when it was ended on
# purpose; any other reason is a failure.
_CANCELLED = "abgebrochen"

# How often the state is asked after a cancel before the end is said anyway.
_END_POLLS = 10


@dataclass
class _Run:
    """The fetch this client has going: the follower's thread watches it, and
    ``/download stop`` marks it, so that the stop is said once."""

    stopped: bool = False
    cancel: threading.Event = field(default_factory=threading.Event)


_run: _Run | None = None
_lock = threading.Lock()


def run_command(ctx: Context, argument: str) -> None:
    """``/download``: ``stop`` and ``token`` act at once; ``embedding`` or
    ``speech`` in front of the words names the kind of model; any other
    words are the search. Without words the user is asked for them."""
    words = argument.split()
    first = words[0].lower() if words else ""
    if first == STOP and len(words) == 1:
        _stop(ctx)
        return
    if first == TOKEN and len(words) == 1:
        _set_token(ctx)
        return
    if first == TOKEN and len(words) == 2 and words[1].lower() == REMOVE:
        _remove_token(ctx)
        return
    art, query = CHAT, " ".join(words)
    if first in KINDS:
        art, query = KINDS[first], " ".join(words[1:])
    if not query:
        asked = ctx.asker.ask_text(ctx.texts.t("cli.download_ask"))
        query = " ".join(asked.split()) if asked else ""
        if not query:
            return
    hit = _pick_hit(ctx, query[:_QUERY_LIMIT], art)
    if hit is None:
        return
    chosen = _pick_file(ctx, hit, art)
    if chosen is None:
        return
    _fetch(ctx, hit, chosen[0], chosen[1], art)


# --- Search and choice -----------------------------------------------------------


def _short(number: Any) -> str:
    """A number of downloads as the window words it: thousands as ``12k``."""
    if not isinstance(number, (int, float)) or isinstance(number, bool):
        return ""
    return f"{round(number / 1000)}k" if number >= 1000 else str(int(number))


def _pick_hit(ctx: Context, query: str, art: str) -> dict[str, Any] | None:
    texts = ctx.texts
    ctx.screen.set_activity(texts.t("modell.suche_laeuft"))
    try:
        found = ctx.client.get("/models/search", params={"q": query, "art": art})
    finally:
        servers.settle_activity(ctx)
    hits = [
        hit
        for hit in (found if isinstance(found, list) else [])
        if isinstance(hit, dict) and isinstance(hit.get("id"), str)
    ]
    if not hits:
        ctx.renderer.notice(texts.t("modell.keine_treffer"))
        return None
    arrow = glyphs.glyph("download")
    picked = ctx.asker.choose(
        [
            Entry(
                cells=[
                    ("text", hit["id"]),
                    ("muted", f"{_short(hit.get('ladungen'))} {arrow}".strip()),
                ]
            )
            for hit in hits
        ]
    )
    return None if picked is None else hits[picked]


def _flat(path: str) -> str:
    """The name a file of a repository lies under in the folder: its last
    segment."""
    return path.rsplit("/", 1)[-1]


def _local(file: dict[str, Any]) -> str:
    """The name the file is kept under in the model folder, as the service
    names it."""
    given = file.get("local_name")
    return given if isinstance(given, str) and given else _flat(str(file.get("datei", "")))


def _is_there(file: dict[str, Any]) -> bool:
    return bool(file.get("da")) and not file.get("collision")


def _pick_file(
    ctx: Context, hit: dict[str, Any], art: str
) -> tuple[dict[str, Any], dict[str, Any] | None] | None:
    """The file of the hit the user picked and the repository's vision
    module, if it names one."""
    texts = ctx.texts
    ctx.screen.set_activity(texts.t("modell.dateien_laden"))
    try:
        listed = ctx.client.get("/models/files", params={"repo": hit["id"], "art": art})
    finally:
        servers.settle_activity(ctx)
    listed = listed if isinstance(listed, dict) else {}
    names = listed.get("dateien")
    files = [
        file
        for file in (names if isinstance(names, list) else [])
        if isinstance(file, dict) and isinstance(file.get("datei"), str)
    ]
    if not files:
        ctx.renderer.notice(texts.t("modell.keine_dateien"))
        return None
    vision = listed.get("mmproj") if isinstance(listed.get("mmproj"), dict) else None
    entries = []
    for file in files:
        cells = [("text", _flat(file["datei"])), ("muted", servers.size_text(texts, file.get("groesse_gb")))]
        parts = file.get("teile")
        cells.append(
            ("muted", texts.t("modell.teile", zahl=parts) if isinstance(parts, int) and parts > 1 else "")
        )
        cells.append(("muted", texts.t("modell.augen") if vision else ""))
        cells.append(("green", texts.t("katalog.im_ordner")) if _is_there(file) else ("muted", ""))
        entries.append(Entry(cells=cells))
    picked = ctx.asker.choose(entries)
    return None if picked is None else (files[picked], vision)


# --- Fetching ---------------------------------------------------------------------


def _vision_name(model: str, vision_file: str) -> str:
    """The name a repository's vision module is kept under: the model's own
    stem and the module's tail, so that the two are tied together."""
    stem = model[:-5] if model.lower().endswith(".gguf") else model
    tail = _flat(vision_file)
    position = tail.lower().find("mmproj")
    return f"{stem}-{tail[position:] if position >= 0 else tail}"


def _folder_names(ctx: Context) -> set[str]:
    """The files that lie in the model folder, as the service lists them."""
    state = ctx.client.get("/runner")
    listed = state.get("modelle") if isinstance(state, dict) else None
    return {
        entry["name"]
        for entry in (listed if isinstance(listed, list) else [])
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    }


def _fetch(
    ctx: Context,
    hit: dict[str, Any],
    file: dict[str, Any],
    vision: dict[str, Any] | None,
    art: str,
) -> None:
    """Starts the fetch of the file — then of the vision module, where the
    file is not there yet and the repository has one — and follows it. A
    file that lies in the folder starts nothing."""
    if _is_there(file):
        return
    global _run
    model = _local(file)
    repo = hit["id"]
    jobs = [
        {
            "repo": repo,
            "datei": file["datei"],
            "ziel": None if model == _flat(file["datei"]) else model,
            "gehoert_zu": None,
            "rolle": None,
            "art": art,
            "unterordner": None,
        }
    ]
    if vision is not None and isinstance(vision.get("datei"), str):
        target = _vision_name(model, vision["datei"])
        if target not in _folder_names(ctx):
            jobs.append(
                {
                    "repo": repo,
                    "datei": vision["datei"],
                    "ziel": target,
                    "gehoert_zu": model,
                    "rolle": "mmproj",
                    "art": art,
                    "unterordner": None,
                }
            )
    # The first request is made here: what the service refuses stands as its
    # own sentence, raised to the screen.
    ctx.client.post("/runner/download", json=jobs[0])
    run = _Run()
    with _lock:
        _run = run
    if ctx.blocking:
        _follow(ctx, run, jobs, model)
        return
    threading.Thread(
        target=_follow_quietly, args=(ctx, run, jobs, model), daemon=True, name="cli-download"
    ).start()


def _follow_quietly(ctx: Context, run: _Run, jobs: list[dict[str, Any]], model: str) -> None:
    """The fetch beside the chat: whatever goes wrong on the way is said, and
    the thread ends."""
    try:
        _follow(ctx, run, jobs, model)
    except ServiceUnreachable as error:
        ctx.renderer.error(ctx.texts.t("fehler.dienst_antwortet_nicht", error=error.address))
    except ServiceError as error:
        ctx.renderer.error(error.detail)


def _follow(ctx: Context, run: _Run, jobs: list[dict[str, Any]], model: str) -> None:
    """Watches the fetch until it ends: how far it is stands in the line
    above the status line, the end stands in the history."""
    texts = ctx.texts
    waiting = list(jobs[1:])
    try:
        while True:
            state = ctx.client.get("/runner/download")
            if isinstance(state, dict):
                reason = state.get("fehler")
                if reason:
                    if reason == _CANCELLED:
                        if not run.stopped:
                            ctx.renderer.error(texts.t("fehler.download_abgebrochen"))
                    else:
                        ctx.renderer.error(texts.t("bildserver.generator_fehler"))
                    return
                if state.get("fertig"):
                    if waiting:
                        ctx.client.post("/runner/download", json=waiting.pop(0))
                        continue
                    ctx.renderer.notice(texts.t("cli.download_done", file=model))
                    return
                # A running answer keeps the line: what it says is its own.
                if not ctx.session.answering:
                    ctx.screen.set_activity(_progress(ctx, state))
            if run.cancel.wait(servers.POLL_SECONDS):
                return
    except KeyboardInterrupt:
        # From outside, the interrupt key ends the fetch as well.
        _cancel_fetch(ctx, run)
    finally:
        with _lock:
            global _run
            if _run is run:
                _run = None
        servers.settle_activity(ctx)


def _progress(ctx: Context, state: dict[str, Any]) -> str:
    """The file, how much of it is there and the percentage."""
    texts = ctx.texts
    name = str(state.get("datei") or "")
    loaded, total = state.get("geladen"), state.get("gesamt")
    share = state.get("anteil")
    percent = round(float(share) * 100) if isinstance(share, (int, float)) else 0
    parts = [name]
    if isinstance(loaded, (int, float)) and isinstance(total, (int, float)) and total:
        both = servers.size_text(texts, f"{loaded / 1e9:.1f}/{total / 1e9:.1f}")
        parts.append(both)
    parts.append(f"{percent} %")
    return " ".join(part for part in parts if part)


def _cancel_fetch(ctx: Context, run: _Run) -> None:
    """Ends the fetch that runs: the service is asked, and the end is said."""
    run.stopped = True
    run.cancel.set()
    ctx.client.delete("/runner/download")
    ctx.renderer.error(ctx.texts.t("fehler.download_abgebrochen"))


def _stop(ctx: Context) -> None:
    """``/download stop``: asks the service to end the fetch that runs. Where
    none runs, that is said and the service is not asked."""
    state = ctx.client.get("/runner/download")
    running = (
        isinstance(state, dict) and not state.get("fertig") and not state.get("fehler")
    )
    if not running:
        ctx.renderer.notice(ctx.texts.t("downloads.leer"))
        return
    with _lock:
        run = _run
    if run is not None:
        run.stopped = True
        run.cancel.set()
    ctx.client.delete("/runner/download")
    _wait_until_ended(ctx)
    ctx.renderer.error(ctx.texts.t("fehler.download_abgebrochen"))


def _wait_until_ended(ctx: Context) -> None:
    """Gives the service the moment it needs to end the fetch it was asked
    to end: the state is asked until it names an end, for a few seconds at
    the most."""
    pause = threading.Event()
    for _ in range(_END_POLLS):
        state = ctx.client.get("/runner/download")
        if not isinstance(state, dict) or state.get("fertig") or state.get("fehler"):
            return
        pause.wait(servers.POLL_SECONDS)


# --- The token ---------------------------------------------------------------------


def _set_token(ctx: Context) -> None:
    """Asks for the token hidden and hands it to the service. It stands in no
    line: what the service says against it is shown without it."""
    token = ctx.asker.ask_text(ctx.texts.t("modell.hf_token"), secret=True)
    if not token:
        return
    token = token.strip()
    try:
        ctx.client.post("/models/token", json={"token": token})
    except ServiceError as error:
        raise ServiceError(error.status, error.detail.replace(token, "…")) from None
    ctx.renderer.notice(ctx.texts.t("cli.token_saved"))


def _remove_token(ctx: Context) -> None:
    ctx.client.delete("/models/token")
    ctx.renderer.notice(ctx.texts.t("cli.token_removed"))
