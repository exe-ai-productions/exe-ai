"""The guided setup: language, theme, preferred name and model, one step
after the other, each one a selection or a line the commands already have —
and the question at the first start, when no model is set up yet.

The steps share their code with the commands they stand for: the language
and the theme are chosen the way ``/lang`` and ``/theme`` choose them, the
model the way ``/model`` and ``/download`` and ``/provider`` do. What is
set already stands marked in its selection, Enter keeps it, and closing a
step leaves it as it was and goes on.
"""

from __future__ import annotations

from cli import downloads, providers, servers
from cli.client import ServiceError
from cli.interfaces import Context, Entry

# The one step that also runs alone: ``/setup model``.
MODEL = "model"

# How many steps there are, as the counter in front of each says it.
_STEPS = 4

# The setting the service keeps the preferred name in, and the field of it
# this setup writes: the other fields of it are not the setup's to touch.
_NAME_SETTING = "anrede"
_NAME_FIELD = "name"

# The group of the entries that run on this machine.
_LOCAL = "local"


def run_command(ctx: Context, argument: str) -> None:
    """``/setup``: all four steps; ``/setup model``: the last one alone.
    Any other word is said, and nothing is asked."""
    word = argument.strip().lower()
    if not word:
        _run_all(ctx)
    elif word == MODEL:
        _model_step(ctx)
    else:
        ctx.renderer.error(ctx.texts.t("cli.unknown_choice", name=argument.strip()))


def _run_all(ctx: Context) -> None:
    texts = ctx.texts
    ctx.renderer.remark(texts.t("erststart.titel"))
    ctx.renderer.remark(f"1/{_STEPS} · {texts.t('erststart.sprache')}")
    ctx.commands.run("/lang")
    ctx.renderer.remark(f"2/{_STEPS} · {texts.t('cli.theme_title')}")
    ctx.commands.run("/theme")
    ctx.renderer.remark(f"3/{_STEPS} · {texts.t('erststart.anrede')}")
    _name_step(ctx)
    ctx.renderer.remark(f"4/{_STEPS} · {texts.t('modell.titel')}")
    _model_step(ctx)
    ctx.renderer.notice(texts.t("erststart.bereit"))


def _name_step(ctx: Context) -> None:
    """The preferred name: a line that starts out with the name kept, or with
    the one the system suggests. Enter keeps what stands; a different name
    is written into its one field, and nothing else of the setting."""
    texts = ctx.texts
    resolved = ctx.client.get(f"/settings/resolved/{_NAME_SETTING}")
    value = resolved.get("wert") if isinstance(resolved, dict) else None
    kept = str(value.get(_NAME_FIELD) or "") if isinstance(value, dict) else ""
    meta = ctx.client.get("/meta")
    suggested = str(meta.get("system_name") or "") if isinstance(meta, dict) else ""
    proposed = kept or suggested
    head = f"{texts.t('erststart.anrede')}\n{texts.t('erststart.anrede_unter')}"
    typed = ctx.asker.ask_text(head, default=proposed)
    if typed is None or typed == kept:
        return
    ctx.client.patch(
        f"/settings/global/{_NAME_SETTING}", json={"wert": {_NAME_FIELD: typed}}
    )


def _model_step(ctx: Context) -> None:
    """The model: the selection of ``/model`` with two entries above its
    own — the one that adds a provider and the one that searches a model to
    download. Each of them runs the command it stands for."""
    texts = ctx.texts
    leading = [
        Entry(cells=[("text", texts.t("modell.anbieter_hinzufuegen"))]),
        Entry(cells=[("text", texts.t("cli.cmd_download").split("\n", 1)[0])]),
    ]
    picked = ctx.commands.pick_model(leading)
    if picked == 0:
        providers.run_command(ctx, "add")
    elif picked == 1:
        downloads.run_command(ctx, "")


# --- The first start -------------------------------------------------------------------


def needed(ctx: Context) -> bool:
    """Whether nothing is set up to talk to: no model answers, no cloud
    provider is entered — also not one that does not answer — and the model
    folder holds no file. Where the service cannot say, nothing is asked."""
    # The models the service listed at the start: any that answers ends it,
    # and costs no request.
    if ctx.session.models:
        return False
    try:
        listed = ctx.client.get("/models", params={"alle": "true"})
        if isinstance(listed, list) and any(
            isinstance(entry, dict) and entry.get("group") != _LOCAL for entry in listed
        ):
            return False
        files = servers.not_carried(ctx)
    except ServiceError:
        return False
    return not files


def ask_first_start(ctx: Context) -> None:
    """The question at the start: set up now? Yes runs the steps, No leaves
    the chat open without a model."""
    if servers.ask(ctx, ctx.texts.t("cli.setup_ask")):
        run_command(ctx, "")
