"""Putting a thinking stage into a request.

The words never change on their way — `low` stays `low`, `high` stays
`high`. What changes is WHERE the word goes: one provider reads it as a
top-level `reasoning_effort`, the next wants an object called `thinking`
beside it, a local server takes it as a chat-template argument, and
Anthropic keeps the depth in `output_config` and the on/off state somewhere
else entirely.

So the decision lives here, once, and it is driven by the catalogue rather
than by a list of provider names in code: which field a provider reads, and
which word it spells "off" with, are rows in `app/daten/denkstufen.yaml`.
Adding a provider is an edit to that table.

Whether a stage may be sent at all is not decided here — `app/denkstufen.py`
answers that, and a stage this model has no room for is simply not sent.
Who needs this: one caller picks a stage, the rest switch thinking off. The
chat is the one that picks — a stage is chosen there, and a request that
works its ceiling out again works the stage out with it, because one provider
generation reads a thinking budget that has to stay below that ceiling. Off
is what the picture-prompt rewrite, the watcher and both folds ask for, the
chat's and a run's: nobody reads the reasoning of a mechanical request, and a
model that thinks spends the ceiling on it before the answer is written. A
run's fold goes through :func:`ausschalten`, which drops the run's own
thinking length as well — beside a switch that says off it would be a
second, contradicting answer. :func:`mit_deckel` serves the request that
already exists, after its ceiling was lowered.
"""

from __future__ import annotations

import logging

from typing import Any, Iterable
from urllib.parse import urlsplit

from app import denkbudget, denkstufen

log = logging.getLogger(__name__)

# The least Anthropic accepts as a thinking budget on the generation that
# wants one. Below it the request is refused, so a request with no more room
# than this goes out without a thinking pass rather than not at all.
MINDEST_BUDGET = 1024

# What the old callers hand in. They have no opinion about depth: they want
# thinking off, or they want whatever the model does by default.
ALTFORM = {False: "off", True: "on"}

# How the "off" state is spelled where the catalogue has nothing to say.
# `app/daten/denkstufen.yaml` carries the same word for this provider
# (`aus_wort: disabled`); it stands here once so the two places that build an
# off state cannot drift into two spellings.
AUS_VORGABE = "disabled"


def _normalisiert(stufe: str | bool | None) -> str | None:
    """``stufe`` in the one lowercase word form the rest of this module
    reads — the older ``True``/``False`` form folded to the word it always
    meant, ``None`` kept as "no opinion". Shared by :func:`zusatz` and
    :func:`ist_aus` so the two cannot read the same value two different
    ways.
    """
    if stufe is None:
        return None
    if isinstance(stufe, bool):
        stufe = ALTFORM[stufe]
    return str(stufe).strip().lower()


def zusatz(
    stufe: str | bool | None,
    zustand,
    *,
    modell: str | None = None,
    abgelehnt: Iterable[str] = (),
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """The extra request fields for one thinking stage, or nothing.

    ``None`` means the caller has no opinion — then no stage is sent and the
    model does whatever it does by default. A plain ``True``/``False`` is
    the older form of the same question and reads as on/off.

    The fields a model row names for one route of its provider
    (:func:`route_fields`) go out with every chat answer and every fold, a
    stage or none: they say where the thinking is delivered, not whether
    there is any. A job's own rounds send a stage only where the agent's
    file names one (:func:`for_stage`), and nothing otherwise.

    ``max_tokens`` is the ceiling THIS request goes out with. Only one
    branch reads it (the Anthropic generation that wants a thinking budget
    rather than a depth), and only when thinking is on — everybody asking
    for thinking OFF can leave it out.
    """
    stufe = _normalisiert(stufe)
    endpunkt = zustand.endpunkt
    fixed = route_for(zustand, modell=modell)
    if stufe is None:
        return fixed

    profil = denkstufen.stufen_fuer(
        endpunkt,
        modell or getattr(zustand, "gemeldeter_name", None),
        getattr(zustand, "faehigkeiten_erkannt", None) or {},
        abgelehnt=abgelehnt,
    )
    if not profil.schaltbar or stufe not in profil.stufen:
        return fixed

    dialekt = getattr(endpunkt, "parameter_dialect", "openai")
    name = denkstufen.anbieter_schluessel(endpunkt)
    eintrag = denkstufen.anbieter_eintrag(name)
    zeile = denkstufen.modellzeile(endpunkt, modell or getattr(zustand, "gemeldeter_name", None))
    nativ = profil.nativ

    match dialekt:
        case "anthropic":
            return _anthropic(stufe, nativ, zeile, max_tokens)
        case "llama_cpp" | "mlx":
            return _lokal(stufe, dialekt, profil.vorlage_wort)
        case _:
            return {**_openai_dialekt(stufe, nativ, eintrag, zeile), **fixed}


def route_fields(endpoint, model_name: str | None) -> dict[str, Any]:
    """The fields one model needs on one route of its provider, whatever
    stage it is asked for — or nothing.

    The model's row is found the way every other lookup finds it
    (:func:`denkstufen.modellzeile`, the longest prefix), so a variant such
    as ``MiniMax-M3-highspeed`` is the model's row too; and the fields go
    out only where the endpoint is exactly at the row's ``adresse``. The
    same model anywhere else is left as it is.
    """
    if getattr(endpoint, "parameter_dialect", "openai") in ("anthropic", "llama_cpp", "mlx"):
        return {}
    row = denkstufen.modellzeile(endpoint, model_name)
    fields = row.get("felder")
    if isinstance(fields, dict) and _at_address(endpoint, row.get("adresse")):
        return dict(fields)
    return {}


def route_for(zustand, *, modell: str | None = None) -> dict[str, Any]:
    """The route fields of the model a request goes to — named the way
    :func:`zusatz` names it, ``modell`` or else the name the server reports.
    The one place a caller asks, so the fields a request carries and the
    fields a refusal is read against are always the same model's."""
    return route_fields(zustand.endpunkt, modell or getattr(zustand, "gemeldeter_name", None))


def carries_switch(fields: dict[str, Any] | None, route: dict[str, Any]) -> bool:
    """Whether these request fields carry a stage or the off switch — not
    merely ``route``, the fields the requested model's route always gets
    (:func:`route_fields`), which say where the thinking is delivered and
    nothing about it. Asked of that one model: a name that is a route field
    of one provider may be another provider's switch."""
    return any(name not in route for name in fields or {})


def _at_address(endpoint, address: Any) -> bool:
    """Is this endpoint exactly at ``address`` — the same host and the same
    path, nothing more and nothing less?

    A model row may carry fields that only one route of its provider reads
    (``felder`` in ``app/daten/denkstufen.yaml``). The same model behind any
    other address is left as it is.
    """
    if not address:
        return False
    raw = str(getattr(endpoint, "base_url", "") or "").strip()
    try:
        parts = urlsplit(raw if "://" in raw else f"//{raw}")
        host = (parts.hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return f"{host}{parts.path.rstrip('/').lower()}" == str(address).strip().rstrip("/").lower()


# The one request parameter that also steers thinking: a length for the
# trace (`reasoning_budget`, app/parameter.py). Beside a switch that turns
# thinking off it is a second answer to the same question, and the two
# contradict each other.
DENKLAENGE = "reasoning_budget"


def ausschalten(
    zustand,
    parameter: dict[str, Any],
    *,
    modell: str | None = None,
    abgelehnt: Iterable[str] = (),
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Thinking off for a request made from another one: the switch in the
    one form this model reads, and the other request's parameters without
    the thinking length that would contradict it.

    Where the model cannot be switched, nothing is sent and the parameters
    come back untouched — there is no switch for the length to contradict.

    ``abgelehnt`` is the caller's own remembered refusals, passed straight
    through to :func:`zusatz`: without it, a stage this model
    has already refused could be sent again the moment something asks for
    thinking off, instead of falling back the way a first request would.
    """
    schalter = zusatz(False, zustand, modell=modell, abgelehnt=abgelehnt)
    route = route_for(zustand, modell=modell)
    if not carries_switch(schalter, route):
        return schalter, parameter
    return schalter, {name: wert for name, wert in parameter.items() if name != DENKLAENGE}


def quietest(
    zustand, *, modell: str | None = None, abgelehnt: Iterable[str] = ()
) -> str | None:
    """The least thinking this model can be asked for: "off" where it has a
    switch for that, otherwise the smallest of its depths it has not
    refused, in the order of ``denkstufen.SCALE``. "on" names no depth —
    the model thinks as deep as its default — so it is the answer only for
    a model that offers nothing else. ``None`` for a model with no stage at
    all: one that always thinks gets nothing sent and thinks by its own
    default.
    """
    profile = denkstufen.stufen_fuer(
        zustand.endpunkt,
        modell or getattr(zustand, "gemeldeter_name", None),
        getattr(zustand, "faehigkeiten_erkannt", None) or {},
        abgelehnt=abgelehnt,
    )
    if not profile.schaltbar:
        return None
    if "off" in profile.stufen:
        return "off"
    depths = [s for s in denkstufen.SCALE if s in profile.stufen]
    if depths:
        return depths[0]
    return "on" if "on" in profile.stufen else None


def for_stage(
    stage: str | bool | None,
    zustand,
    *,
    modell: str | None = None,
    abgelehnt: Iterable[str] = (),
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """The request fields a round carries for the stage it was asked with,
    for the ceiling it has right now. The one answer a chat's round and a
    job's round both ask for, so the two cannot send different fields for
    the same stage.

    Off goes out the way the fold sends it (:func:`ausschalten`), which also
    carries the model's own refusals along. Every other stage keeps asking
    for the stage and the ceiling together: one provider generation reads a
    thinking budget that has to stay below the ceiling of that very round.
    There is no parameter dict to strip at this point in a round, so an empty
    one goes in for off and its answer is thrown away.
    """
    if ist_aus(stage):
        schalter, _ = ausschalten(zustand, {}, modell=modell, abgelehnt=abgelehnt)
        return schalter
    return zusatz(stage, zustand, modell=modell, abgelehnt=abgelehnt, max_tokens=max_tokens)


def ist_aus(stufe: str | bool | None) -> bool:
    """Whether ``stufe`` names the switched-off stage, in any of the forms a
    caller may hand in — through the same normalisation :func:`zusatz` uses
    at its own top, so a caller deciding whether to route a request through
    :func:`ausschalten` reads exactly the word :func:`zusatz` would read.
    """
    return _normalisiert(stufe) == "off"


def aus_wort(zustand, *, modell: str | None = None) -> str:
    """The word THIS model's provider spells "off" with.

    Asked through :func:`zusatz` rather than out of the catalogue directly,
    so the word has exactly one origin and the two places that build an off
    state cannot drift into two spellings. A provider that reads "off" as
    something other than a `thinking` object has nothing to say here and
    gets the fallback this module documents.
    """
    schalter = zusatz(False, zustand, modell=modell)
    denken = schalter.get("thinking")
    if isinstance(denken, dict) and denken.get("type"):
        return str(denken["type"])
    return AUS_VORGABE


def mit_deckel(
    zusatz: dict[str, Any], max_tokens: int, aus_wort: str = AUS_VORGABE
) -> dict[str, Any]:
    """``zusatz`` again, with its thinking budget pulled under ``max_tokens``.

    For the one place that lowers a ceiling AFTER the request was built: a
    refusal comes back, the retry goes out with less room
    (``app/kontextvoll.py``), and a budget worked out for the larger ceiling
    would still be sitting beside it. The API this concerns wants the budget
    SMALLER than the ceiling, so that retry is refused in turn — for a
    reason no "too long" pattern recognizes, which means nothing retries it
    again.

    The same two rules :func:`_anthropic` resolves the budget by, applied to
    a request that already exists: the split in :mod:`app.denkbudget`, which
    leaves the visible answer its own room, and below :data:`MINDEST_BUDGET`
    no thinking pass at all rather than a refusal.

    Only a ``thinking`` object that really carries a budget is changed —
    every other shape a provider reads a stage in says nothing about a
    ceiling and comes back saying the same thing. A new dictionary either
    way, including then: the caller is building a COPY of the request, and
    a copy that shares this dictionary with the original is not a copy.

    ``aus_wort`` is what this model's provider calls "off" — the same word
    :func:`_anthropic` takes out of the catalogue when it switches thinking
    off for a fresh request. This function never sees the profile that word
    comes from, so the caller resolves it (:func:`aus_wort`) and hands it
    in. Written hard, it was `disabled` for every provider, and the first
    budget model spelling it differently would have had its retry refused
    with a wording no "too long" pattern recognises.

    Never upwards. The budget this finds was worked out for a LARGER
    ceiling, so it is normally the larger of the two — but a request
    carrying a deliberately small one must not have it stretched to fill a
    ceiling that just shrank, and the split it goes through takes the
    smaller of the two for exactly that reason.
    """
    denken = zusatz.get("thinking")
    if not isinstance(denken, dict) or denken.get("budget_tokens") is None:
        return dict(zusatz)
    budget = denkbudget.teilen(denken["budget_tokens"], max_tokens)
    if budget < MINDEST_BUDGET:
        log.info(
            "Anthropic thinking off for the retry: the lowered ceiling leaves "
            "only %d tokens to think with, the API wants at least %d",
            max(0, budget),
            MINDEST_BUDGET,
        )
        return {**zusatz, "thinking": {"type": aus_wort}}
    return {**zusatz, "thinking": {**denken, "budget_tokens": budget}}


def _anthropic(
    stufe: str, nativ: dict[str, str], zeile: dict[str, Any], max_tokens: int | None = None
) -> dict[str, Any]:
    """Two switches, one list: the state in ``thinking``, the depth beside it."""
    if stufe == "off":
        return {"thinking": {"type": nativ.get("off", AUS_VORGABE)}}
    if zeile.get("budget"):
        # The generation before `effort`: every stage asks for a budget, and
        # there is no depth to name. What a stage asks for and how much of
        # it fits beside the answer are both `app/denkbudget.py`'s to say —
        # the ceiling less one would satisfy the API and starve the answer,
        # which is the whole reason that module exists.
        wunsch = denkbudget.STUFENBUDGETS.get(stufe, denkbudget.STUFENBUDGET)
        budget = denkbudget.teilen(wunsch, max_tokens)
        if budget < MINDEST_BUDGET:
            # Below what the API accepts. This one request goes out without
            # a thinking pass rather than being refused for a budget that
            # cannot be sent.
            log.info(
                "Anthropic thinking off for this request: the ceiling leaves "
                "only %d tokens to think with, the API wants at least %d",
                max(0, budget),
                MINDEST_BUDGET,
            )
            return {"thinking": {"type": nativ.get("off", AUS_VORGABE)}}
        return {"thinking": {"type": "enabled", "budget_tokens": budget}}
    koerper: dict[str, Any] = {"thinking": {"type": nativ.get("on", "adaptive")}}
    if stufe != "on":
        koerper["output_config"] = {"effort": stufe}
    return koerper


# What a chat template's switch is called when nobody found out otherwise.
# The word most templates use; a template that spells it differently says so
# itself, and that name travels in `Denkprofil.vorlage_wort`.
VORLAGE_WORT_VORGABE = "enable_thinking"

# The word "off" travels as on llama.cpp: its own `reasoning_effort` value.
OFF_LOCAL = "none"


def _lokal(stufe: str, dialekt: str, wort: str | None = None) -> dict[str, Any]:
    """A local server reads the chat template's own argument.

    llama.cpp takes a depth as a top-level ``reasoning_effort`` and hands it
    to the template from there, so a stage travels alone — the template that
    reads a depth has no on/off variable to set beside it.

    An MLX server (oMLX, mlx-lm) hands ``chat_template_kwargs`` to the
    template: a depth goes there as ``reasoning_effort``, beside the switch
    set on, and "off" is the switch alone, set off.

    ``wort`` is the name the template uses for that switch, as the sniffing
    found it (app/discovery.py, app/denkstufen.py). It used to be found and
    then dropped: every request set ``enable_thinking``, so a model whose
    template reads ``thinking`` got a variable its template never mentions —
    it kept thinking, and a compaction burned its ceiling in the trace
    instead of writing the summary.

    "Off" on llama.cpp is ``reasoning_effort: "none"``, the field the server
    itself reads: it switches the template's thinking off whatever the
    template calls its switch — one that only reacts to a word in the text
    as well — and a model that cannot think ignores it. A server that
    refuses the field gets the turn again without it (app/denkablehnung.py).
    """
    if dialekt == "llama_cpp" and stufe == "off":
        return {"reasoning_effort": OFF_LOCAL}
    if dialekt == "llama_cpp" and stufe != "on":
        return {"reasoning_effort": stufe}
    if dialekt == "mlx" and stufe not in ("off", "on"):
        return {
            "chat_template_kwargs": {
                wort or VORLAGE_WORT_VORGABE: True,
                "reasoning_effort": stufe,
            }
        }
    return {"chat_template_kwargs": {wort or VORLAGE_WORT_VORGABE: stufe != "off"}}


def _openai_dialekt(
    stufe: str, nativ: dict[str, str], eintrag: dict[str, Any], zeile: dict[str, Any]
) -> dict[str, Any]:
    """Everything that speaks the OpenAI dialect at its own address.

    Three shapes, and the catalogue says which one applies: a plain
    ``reasoning_effort``, a ``thinking`` object with the depth beside it, or
    a plain on/off switch at the top of the body.
    """
    schalter = eintrag.get("schalter")
    feld = eintrag.get("feld")

    # A plain on/off switch. Its NAME comes out of the provider profile, and
    # it stands at the top of the body: that is where an SDK's `extra_body`
    # ends up too, merged in flat, so no request ever carries a key literally
    # called `extra_body`. A dotted name is not this shape — it names a field
    # inside an object and is answered below.
    if denkstufen.ist_reiner_schalter(eintrag) and not zeile.get("ohne_schalter"):
        koerper: dict[str, Any] = {str(schalter): stufe != "off"}
        # A depth beside the switch, the same way the object form carries
        # one: a profile that offers stages and names a field for them gets
        # both, instead of the depth falling silently away.
        if stufe not in ("off", "on") and feld:
            koerper[feld] = stufe
        return koerper

    if schalter == "thinking.type" and not zeile.get("ohne_schalter"):
        zustandswort = nativ.get("off") if stufe == "off" else nativ.get("on", "enabled")
        koerper = {"thinking": {"type": zustandswort or "disabled"}}
        if stufe not in ("off", "on") and feld:
            koerper[feld] = stufe
        return koerper

    # The plain form. "On" has no word of its own here: leaving the field
    # out IS the request to think, and a value nobody documented would only
    # be a guess.
    if stufe == "on":
        return {}
    wort = nativ.get("off", denkstufen.AUS_ROH) if stufe == "off" else stufe
    return {feld or denkstufen.FELD_VORGABE: wort}


# --- The stage on OpenAI's own host ----------------------------------------
#
# There, a request carrying tools AND a stage cannot travel on
# `chat/completions`: the server answers 400 and names its Responses API as
# the way out (app/providers/openai_responses.py). The stage is the same word
# on both wires — what differs is where it stands.

# The fields a stage travels under on an OpenAI-compatible wire: the plain
# one the chat route reads, and the object the Responses route reads.
STUFENFELDER: tuple[str, ...] = ("reasoning_effort", "reasoning")


def traegt_stufe(koerper: dict[str, Any]) -> bool:
    """Does this finished request body carry a thinking stage?

    Asked of the BODY, never of a setting: what decides whether a provider
    needs its other wire is what really goes out, and a stage this model has
    no room for never reaches the body at all (:func:`zusatz`).
    """
    return any(feld in koerper for feld in STUFENFELDER)


def fuer_antworten(zusatz: dict[str, Any]) -> dict[str, Any]:
    """The same request fields, with the stage in the shape ``/v1/responses``
    reads: one object called ``reasoning``, the stage as its ``effort``.

    The word itself does not change — ``low`` stays ``low``, and "off" is
    already ``none`` by the time a stage stands in the body (the word the
    catalogue keeps for this provider, ``app/daten/denkstufen.yaml``). Only
    its place changes. Every other field is copied unchanged, and a request
    without a stage comes back as it was.

    A new dictionary either way: the caller is building a COPY of its request,
    and a copy that shares this dictionary with the original is not a copy.
    """
    if "reasoning_effort" not in zusatz:
        return dict(zusatz)
    ohne = {name: wert for name, wert in zusatz.items() if name != "reasoning_effort"}
    vorhanden = zusatz.get("reasoning")
    # An object already standing there keeps everything it carries — only its
    # `effort` is this stage's to say. Written over whole, a `summary` or an
    # `include` from the same request would disappear without a word.
    if isinstance(vorhanden, dict):
        return {**ohne, "reasoning": {**vorhanden, "effort": zusatz["reasoning_effort"]}}
    return {**ohne, "reasoning": {"effort": zusatz["reasoning_effort"]}}
