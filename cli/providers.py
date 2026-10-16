"""The cloud providers from the client's side: adding one, removing one, and
setting the context size, the time limit and the capabilities of one.

Nothing here decides how a provider is stored or checked: the service writes
its configuration and its key file and says whether the provider answers.
The key is asked for hidden and goes to the service in the one request that
adds the provider; it stands in no line the client writes, and a refusal of
the service that repeats it is shown with the key taken out.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from cli import servers
from cli.client import ServiceError
from cli.interfaces import Context, Entry

# The kinds of provider the service knows; ``CUSTOM`` is the one that takes
# a name and an address of its own.
ANTHROPIC = "anthropic"
OPENAI = "openai"
CUSTOM = "eigen"

# The words behind ``/provider``, and the English word that also names the
# custom kind.
ADD = "add"
REMOVE = "remove"
_CUSTOM_WORD = "custom"

# The group of the entries that run on this machine: no cloud provider.
_LOCAL = "local"

# What a row of a provider's own selection stands for.
_CONTEXT = "context"
_TIME_LIMIT = "time_limit"
_VISION = "vision"
_REASONING = "reasoning"
_TOOL_CALLS = "tool_calls"
_REMOVE_ROW = "remove"


@dataclass
class House:
    """One provider, as the service's model list describes it."""

    id: str
    name: str
    reachable: bool
    key_set: bool
    # Whether the key leaves the key file with the provider.
    key_goes: bool
    vision: bool
    reasoning: bool
    tool_calls: bool
    time_limit: bool
    # The context size said by hand, ``None`` where the server is asked.
    own_context: int | None


def houses(ctx: Context) -> list[House]:
    """Every cloud provider the service lists — also one that does not
    answer — in the order of the list. The models of a provider carry the
    same answers; the first one speaks for it."""
    listed = ctx.client.get("/models", params={"alle": "true"})
    found: dict[str, House] = {}
    for entry in listed if isinstance(listed, list) else []:
        if not isinstance(entry, dict) or entry.get("group") == _LOCAL:
            continue
        identifier = entry.get("anbieter")
        if not isinstance(identifier, str) or not identifier or identifier in found:
            continue
        capabilities = entry.get("capabilities")
        capabilities = capabilities if isinstance(capabilities, dict) else {}
        own = entry.get("kontext_eigen")
        found[identifier] = House(
            id=identifier,
            name=str(entry.get("anbieter_name") or identifier),
            reachable=bool(entry.get("erreichbar")),
            key_set=bool(entry.get("schluessel_gesetzt")),
            key_goes=bool(entry.get("key_goes_with_provider")),
            vision=bool(capabilities.get("vision")),
            reasoning=bool(capabilities.get("thinking")),
            tool_calls=bool(capabilities.get("tool_calls")),
            time_limit=entry.get("timeout_enabled") is not False,
            own_context=own if isinstance(own, int) and not isinstance(own, bool) else None,
        )
    return list(found.values())


def run_command(ctx: Context, argument: str) -> None:
    """``/provider``: without a word, the selection of the providers with
    the entry that adds one on top. ``add`` and ``remove`` act on the
    provider that follows them, or open the selection that picks one. Any
    other word is said, and the service is not asked."""
    word, _, rest = argument.strip().partition(" ")
    word, rest = word.lower(), rest.strip()
    if not word:
        _choose(ctx)
    elif word == ADD:
        _add(ctx, rest)
    elif word == REMOVE:
        _remove(ctx, rest)
    else:
        ctx.renderer.error(ctx.texts.t("cli.unknown_choice", name=argument.strip()))


# --- The selection --------------------------------------------------------------------


def _choose(ctx: Context) -> None:
    texts = ctx.texts
    listed = houses(ctx)
    entries = [Entry(cells=[("text", texts.t("modell.anbieter_hinzufuegen"))])]
    for house in listed:
        key = (
            f"{texts.t('modell.schluessel')} {texts.t('modell.schluessel_gesetzt')}"
            if house.key_set
            else texts.t("modell.schluessel_fehlt")
        )
        entries.append(
            Entry(
                cells=[
                    ("text", house.name),
                    (
                        "green" if house.reachable else "red",
                        texts.t("status.erreichbar" if house.reachable else "status.nicht_erreichbar"),
                    ),
                    ("green" if house.key_set else "red", key),
                ]
            )
        )
    picked = ctx.asker.choose(entries)
    if picked is None:
        return
    if picked == 0:
        _add(ctx, "")
        return
    _detail(ctx, listed[picked - 1].id)


def _on_off(ctx: Context, on: bool) -> tuple[str, str]:
    return ("blue" if on else "muted", ctx.texts.t("status.aktiv" if on else "status.inaktiv"))


def _detail(ctx: Context, identifier: str) -> None:
    """What can be set on one provider, under its name. A switch is turned
    over with a pick and the selection opens again with the new state, until
    it is closed or the provider is removed."""
    texts = ctx.texts
    while True:
        house = next((entry for entry in houses(ctx) if entry.id == identifier), None)
        if house is None:
            return
        context = (
            texts.t("parameter.auto") if house.own_context is None else str(house.own_context)
        )
        rows: list[tuple[str, list[tuple[str, str]]]] = [
            (_CONTEXT, [("text", texts.t("modell.kontext_feld")), ("muted", context)]),
            (
                _TIME_LIMIT,
                [("text", texts.t("modell.zeitgrenze_schalter")), _on_off(ctx, house.time_limit)],
            ),
            (_VISION, [("text", texts.t("modell.vision_schalter")), _on_off(ctx, house.vision)]),
            (
                _REASONING,
                [("text", texts.t("modell.denken_schalter")), _on_off(ctx, house.reasoning)],
            ),
            (
                _TOOL_CALLS,
                [("text", texts.t("modell.werkzeuge_schalter")), _on_off(ctx, house.tool_calls)],
            ),
            (_REMOVE_ROW, [("red", texts.t("modell.anbieter_entfernen"))]),
        ]
        picked = ctx.asker.choose([Entry(cells=cells) for _, cells in rows], head=house.name)
        if picked is None:
            return
        row = rows[picked][0]
        if row == _REMOVE_ROW:
            _confirm_and_remove(ctx, house)
            return
        base = f"/providers/{quote(house.id, safe='')}"
        if row == _CONTEXT:
            if not _set_context(ctx, base):
                return
        elif row == _TIME_LIMIT:
            ctx.client.put(f"{base}/timeout", json={"timeout_enabled": not house.time_limit})
        elif row == _VISION:
            ctx.client.put(f"{base}/capabilities", json={"vision": not house.vision})
        elif row == _REASONING:
            ctx.client.put(f"{base}/capabilities", json={"thinking": not house.reasoning})
        else:
            ctx.client.put(f"{base}/capabilities", json={"tool_calls": not house.tool_calls})


def _set_context(ctx: Context, base: str) -> bool:
    """Asks for the context size: a whole number, or nothing for the size
    the server names. ``False`` where the question was closed — nothing was
    changed and the selection ends."""
    typed = ctx.asker.ask_text(ctx.texts.t("modell.kontext_feld"), default="")
    if typed is None:
        return False
    if not typed:
        value: int | None = None
    elif typed.isdecimal():
        value = int(typed)
    else:
        ctx.renderer.error(ctx.texts.t("cli.unknown_choice", name=typed))
        return True
    ctx.client.put(f"{base}/context", json={"context_tokens": value})
    return True


# --- Adding --------------------------------------------------------------------------


def _add(ctx: Context, word: str) -> None:
    """Adds a provider: the kind from the word or the selection, for a custom
    one its name and address, then the key, hidden. What the service says
    about its reaching the provider is said."""
    texts = ctx.texts
    kinds = [
        (ANTHROPIC, "Anthropic", ""),
        (OPENAI, "OpenAI", ""),
        (CUSTOM, texts.t("modell.eigener"), texts.t("modell.eigener_unter")),
    ]
    if word:
        wanted = word.casefold()
        kind = next(
            (
                code
                for code, label, _ in kinds
                if wanted in (code, label.casefold())
                or (code == CUSTOM and wanted == _CUSTOM_WORD)
            ),
            None,
        )
        if kind is None:
            ctx.renderer.error(texts.t("cli.unknown_choice", name=word))
            return
    else:
        picked = ctx.asker.choose(
            [Entry(cells=[("text", label)], note=note) for _, label, note in kinds],
            head=texts.t("modell.anbieter_waehlen"),
        )
        if picked is None:
            return
        kind = kinds[picked][0]
    name = address = None
    if kind == CUSTOM:
        name = ctx.asker.ask_text(texts.t("modell.eigener_name"))
        if name is None:
            return
        address = ctx.asker.ask_text(texts.t("modell.eigener_adresse"))
        if address is None:
            return
    key = ctx.asker.ask_text(texts.t("modell.schluessel"), secret=True)
    if key is None:
        return
    key = key.strip()
    try:
        added = ctx.client.post(
            "/providers",
            json={"art": kind, "schluessel": key, "kennung": name, "url": address},
        )
    except ServiceError as error:
        raise ServiceError(error.status, error.detail.replace(key, "…")) from None
    reachable = isinstance(added, dict) and bool(added.get("erreichbar"))
    ctx.renderer.notice(
        texts.t("modell.anbieter_da" if reachable else "modell.anbieter_da_nicht_erreichbar")
    )


# --- Removing ------------------------------------------------------------------------


def _remove(ctx: Context, word: str) -> None:
    """Removes a provider named by the word or picked from the selection."""
    listed = houses(ctx)
    if word:
        wanted = word.casefold()
        house = next(
            (entry for entry in listed if wanted in (entry.id.casefold(), entry.name.casefold())),
            None,
        )
        if house is None:
            ctx.renderer.error(ctx.texts.t("cli.unknown_choice", name=word))
            return
    else:
        if not listed:
            return
        picked = ctx.asker.choose([Entry(cells=[("text", entry.name)]) for entry in listed])
        if picked is None:
            return
        house = listed[picked]
    _confirm_and_remove(ctx, house)


def _confirm_and_remove(ctx: Context, house: House) -> None:
    """The question of the window before it removes a provider — which of its
    two sentences depends on whether the key goes with it — and the removal,
    said when it is done."""
    texts = ctx.texts
    question = texts.t(
        "modell.anbieter_loeschen_frage_mit_schluessel"
        if house.key_goes
        else "modell.anbieter_loeschen_frage",
        name=house.name,
    )
    if not servers.ask(ctx, question):
        return
    ctx.client.delete(f"/providers/{quote(house.id, safe='')}")
    ctx.renderer.notice(texts.t("modell.anbieter_entfernt"))
