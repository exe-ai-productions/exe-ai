"""Model parameters — uniformly named, translated per backend.

The backends cannot do the same things and call the same thing by different
names. The repetition penalty is ``repeat_penalty`` in llama.cpp,
``repetition_penalty`` in MLX; ``typical_p`` exists only in llama.cpp,
``logit_bias`` only in MLX.

Hence our own fixed set of names here. Each dialect says which of them it
knows and what it calls them. The frontend queries the list and shows only
knobs that actually do something — a knob that silently grasps at nothing is
worse than no knob at all.

ONE knob is exempt, and only one: ``reasoning_budget``. It is offered by
every dialect, and locked in TWO cases, each with its own line saying why:
the backend has no field for it (the dialect does not know the name), or the
backend has one and THIS MODEL cannot think (``faehigkeiten["reasoning"]``,
app/discovery.py). The rule above still holds — a locked knob does not grasp
at nothing, it names what cannot do it, and which of the two that is decides
where the reader looks — and the gain is that the panel keeps the same shape
whichever model is picked, instead of a row appearing and vanishing as one
switches. ``immer_zeigen`` marks a parameter that travels this way; nothing
else carries it.

The lists are not guessed: llama.cpp was queried via ``/props``, MLX was
looked up in the source of ``mlx_lm/server.py``.

Deliberately not included: mirostat, DRY, XTC, dynatemp and top_n_sigma. They
are rare, partly work against top_p/top_k, and would clutter the menu.
Whoever needs them adds them here — nothing more is required.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal

from app.i18n import t

Gruppe = Literal["sichtbar", "mehr"]


@dataclass(frozen=True)
class Parameter:
    name: str
    # Catalogue keys (app/locales/<language>.json), spelled out in full at
    # every entry; `als_dict` translates them for the reader's language.
    label: str
    hinweis: str
    minimum: float
    maximum: float
    schritt: float
    gruppe: Gruppe = "mehr"
    ganzzahl: bool = False
    # Offered by every dialect, locked where none exists for it. See the
    # module docstring: exactly one parameter is built this way.
    immer_zeigen: bool = False
    # Filled in by `unterstuetzte()` per dialect, never written by hand: does
    # this backend evaluate the knob, and if it does not, the catalogue key
    # of the line that says so.
    aktiv: bool = True
    grund: str = ""

    def als_dict(self, sprache: str = "de") -> dict[str, Any]:
        return {
            "name": self.name,
            "label": t(self.label, sprache),
            "hinweis": t(self.hinweis, sprache),
            "minimum": self.minimum,
            "maximum": self.maximum,
            "schritt": self.schritt,
            "gruppe": self.gruppe,
            "ganzzahl": self.ganzzahl,
            "aktiv": self.aktiv,
            # Only a locked knob carries one. `None` rather than an empty
            # string so the window can test the field itself.
            "grund": t(self.grund, sprache) if self.grund else None,
        }


PARAMETER: list[Parameter] = [
    Parameter("temperature", "parameter.label.temperature", "parameter.hint.temperature",
              0, 2, 0.05, "sichtbar"),
    Parameter("top_p", "parameter.label.top_p", "parameter.hint.top_p",
              0, 1, 0.01, "sichtbar"),
    # The ceiling here is the fallback for a model whose context window is
    # not known — the same 1,000,000 the request schema already allows
    # (app/api/v1/schemas.py). `unterstuetzte()` caps it further to the
    # actual model's window wherever that is known.
    Parameter("max_tokens", "parameter.label.max_tokens", "parameter.hint.max_tokens",
              256, 1_000_000, 256, "sichtbar", ganzzahl=True),
    # Beside the response length, because that is the pot it used to be
    # taken out of: thinking and answering shared one budget, so a model
    # that thought too long had nothing left to answer with, and the whole
    # unfinished thought fell into the visible text. A zero here means no
    # thinking at all, which is how llama.cpp itself reads the number.
    # Left untouched, nothing is sent and the server keeps its own habit.
    # -1 is Auto (no artificial cap, `unrestricted` on llama.cpp) and has to
    # survive `pruefen()` unclamped — a floor of 0 turned a stored -1 into a
    # 0, which reads as "no thinking at all" instead of "no cap".
    Parameter("reasoning_budget", "parameter.label.reasoning_budget", "parameter.hint.reasoning_budget",
              -1, 1_000_000, 256, "sichtbar", ganzzahl=True, immer_zeigen=True),

    Parameter("top_k", "parameter.label.top_k", "parameter.hint.top_k",
              0, 200, 1, ganzzahl=True),
    Parameter("min_p", "parameter.label.min_p", "parameter.hint.min_p",
              0, 1, 0.01),
    Parameter("repeat_penalty", "parameter.label.repeat_penalty", "parameter.hint.repeat_penalty",
              1, 2, 0.01),
    Parameter("repeat_last_n", "parameter.label.repeat_last_n", "parameter.hint.repeat_last_n",
              0, 2048, 16, ganzzahl=True),
    Parameter("presence_penalty", "parameter.label.presence_penalty", "parameter.hint.presence_penalty",
              -2, 2, 0.05),
    Parameter("frequency_penalty", "parameter.label.frequency_penalty", "parameter.hint.frequency_penalty",
              -2, 2, 0.05),
    Parameter("typical_p", "parameter.label.typical_p", "parameter.hint.typical_p",
              0, 1, 0.01),
    Parameter("seed", "parameter.label.seed", "parameter.hint.seed",
              -1, 2147483647, 1, ganzzahl=True),
]

NACH_NAME: dict[str, Parameter] = {p.name: p for p in PARAMETER}


# Which dialect knows which parameter — and under what name.
# If an entry is missing, the parameter is neither offered nor sent along
# for that backend.
DIALEKTE: dict[str, dict[str, str]] = {
    # llama.cpp (llama-server), queried via /props
    "llama_cpp": {
        "temperature": "temperature",
        "top_p": "top_p",
        "max_tokens": "max_tokens",
        # Per request, and it works: measured against build b10331 with a
        # thinking model, a budget of 16 cut the trace from 874 characters
        # to 54, a budget of 0 to nothing at all, and -1 gave back exactly
        # the unrestricted length. `thinking_budget_tokens` is the same
        # field under a second name there; one name is enough.
        "reasoning_budget": "reasoning_budget_tokens",
        "top_k": "top_k",
        "min_p": "min_p",
        "repeat_penalty": "repeat_penalty",
        "repeat_last_n": "repeat_last_n",
        "presence_penalty": "presence_penalty",
        "frequency_penalty": "frequency_penalty",
        "typical_p": "typical_p",
        "seed": "seed",
    },
    # mlx_lm.server, looked up in mlx_lm/server.py
    "mlx": {
        "temperature": "temperature",
        "top_p": "top_p",
        "max_tokens": "max_tokens",
        "top_k": "top_k",
        "min_p": "min_p",
        "repeat_penalty": "repetition_penalty",
        "repeat_last_n": "repetition_context_size",
        "presence_penalty": "presence_penalty",
        "frequency_penalty": "frequency_penalty",
        "seed": "seed",
    },
    # Lowest common denominator of the cloud providers.
    "openai": {
        "temperature": "temperature",
        "top_p": "top_p",
        "max_tokens": "max_tokens",
        "presence_penalty": "presence_penalty",
        "frequency_penalty": "frequency_penalty",
        "seed": "seed",
    },
    # Anthropic's Messages API. Deliberately short: it knows neither the two
    # penalties nor a seed, so those knobs are not offered — a knob that
    # silently grasps at nothing is worse than no knob at all.
    "anthropic": {
        "temperature": "temperature",
        "top_p": "top_p",
        "top_k": "top_k",
        "max_tokens": "max_tokens",
    },
}


# Where a dialect's range differs from the general one. Anthropic caps the
# temperature at 1.0 and rejects anything above with an error — a slider
# running to 2 would offer a setting that cannot be sent.
GRENZEN: dict[str, dict[str, tuple[float, float]]] = {
    "anthropic": {"temperature": (0, 1)},
}


# What a locked knob says about itself, per parameter and per dialect, as the
# catalogue key of the line. Only a parameter marked `immer_zeigen` ever
# reaches this table — everything else a dialect does not know is simply left
# out, as before.
#
# The two cloud providers dropped the budget field and put an effort scale
# in its place, which the thinking button already offers; an MLX server
# swallows the field without an error and then ignores it (measured: a
# budget of 16 tokens left the trace at full length), and it can only be set
# per model in that server's own admin panel.
_KEINE_DENKLAENGE = "parameter.locked.no_thinking_length"
# The second reason a locked thinking length can have, and the narrower one:
# the backend would take the number (its dialect knows the name), the MODEL
# cannot think — so the number would go nowhere. Kept apart from the line
# above on purpose: one is about the wire, the other about the model, and a
# reader who sees the wrong one looks in the wrong place.
MODELL_OHNE_REASONING = "parameter.locked.model_cannot_reason"
# The third reason, and the only one that is about the request rather than the
# backend or the model: at OpenAI's own host every request that carries tools
# or a thinking stage goes over the Responses wire, which has no field for
# the seed and the two penalties. The server would take the numbers on the
# other wire, so they stay stored and offered — only the display says they
# do nothing there.
NO_EFFECT_AT_OPENAI = "parameter.locked.no_effect_at_openai"
GRUENDE: dict[str, dict[str, str]] = {
    "reasoning_budget": {
        "anthropic": _KEINE_DENKLAENGE,
        "openai": _KEINE_DENKLAENGE,
        "mlx": _KEINE_DENKLAENGE,
    },
}

# What a locked knob says when the table above has no line for this dialect
# — a backend nobody has measured yet still has to say something. Today only
# the thinking length is ever shown while locked (`immer_zeigen`), so this
# line is the one a backend without a row in `GRUENDE` reaches.
GRUND_ALLGEMEIN = _KEINE_DENKLAENGE

# The one name this module is asked about from elsewhere: a request may only
# carry a thinking length where the knob is available for the model it goes
# to. Spelled once, so a gate that looks for the knob and the
# knob itself cannot drift apart.
NAME_DENKLAENGE = "reasoning_budget"


def _locked(p: Parameter, reason: str) -> Parameter:
    """The row as the model window draws a knob that does nothing here: locked,
    with the catalogue key of the reason."""
    return replace(p, aktiv=False, grund=reason)


def grund_fuer(name: str, dialekt: str) -> str:
    """The catalogue key of why this parameter is locked for this dialect."""
    return (GRUENDE.get(name) or {}).get(dialekt) or GRUND_ALLGEMEIN


def unterstuetzte(
    dialekt: str,
    kontextfenster: int | None = None,
    faehigkeiten: dict[str, Any] | None = None,
    without_effect_at_openai: tuple[str, ...] = (),
) -> list[Parameter]:
    """All parameters this dialect knows — in the order from above.

    With the dialect's own range where it has one, so the control offers
    exactly what the backend accepts. `kontextfenster`, when known, caps
    `max_tokens` at the model's own window — offering a setting the model
    would immediately reject is worse than not offering it that high. The
    thinking length is capped the same way and for the same reason: it is
    spent out of the same window.

    A parameter marked `immer_zeigen` stays in the list even where the
    dialect has no name for it, carrying `aktiv=False` and the line that
    says why. Nothing is sent for it in that case — `uebersetzen()` drops
    what a dialect does not know, and it does not know this one.

    `faehigkeiten` is what the DISCOVERY knows about the model in question
    (`app/discovery.py` `_capabilities_aufloesen`). Only the thinking length
    reads it, and only ever to lock itself: a number that reaches a model
    which cannot think is a number spent on nothing. It is handed in rather
    than looked up so this module stays free of the discovery — and a
    caller that knows nothing about the model (`None`) gets today's answer
    unchanged: every dialect that knows the name offers it.

    `without_effect_at_openai` names the parameters the model's host drops on
    its Responses wire; the caller hands them in only for a model at OpenAI's
    own host (`app/discovery.py`), so this module neither knows the wire nor
    the host. Those rows stay in the list, locked, with the line that says
    when they do nothing. The stored value is untouched and still goes out
    on the other wire.
    """
    bekannt = DIALEKTE.get(dialekt) or DIALEKTE["openai"]
    grenzen = GRENZEN.get(dialekt) or {}
    raus: list[Parameter] = []
    for p in PARAMETER:
        if p.name not in bekannt:
            if not p.immer_zeigen:
                continue
            p = _locked(p, grund_fuer(p.name, dialekt))
        elif (
            p.name == "reasoning_budget"
            and faehigkeiten is not None
            and faehigkeiten.get("reasoning") is False
        ):
            # The wire would carry it, the model cannot think: locked here,
            # with the reason that names the MODEL and not the server.
            #
            # Only an explicit `False` locks. A caller that hands in a set
            # of capabilities WITHOUT this key has said nothing about
            # thinking — `Capabilities().model_dump()` is exactly such a set
            # — and "said nothing" may not be read as "cannot think", or the
            # knob goes grey for a thinking model and names the wrong
            # culprit.
            p = _locked(p, MODELL_OHNE_REASONING)
        if p.name in without_effect_at_openai and p.aktiv:
            p = _locked(p, NO_EFFECT_AT_OPENAI)
        if p.name in grenzen:
            minimum, maximum = grenzen[p.name]
            p = replace(p, minimum=minimum, maximum=maximum)
        if p.name in ("max_tokens", NAME_DENKLAENGE) and kontextfenster:
            p = replace(p, maximum=min(p.maximum, kontextfenster))
        raus.append(p)
    return raus


def denklaenge_freigegeben(
    dialekt: str, faehigkeiten: dict[str, Any] | None = None
) -> bool:
    """May a thinking length travel to this backend for this model?

    Asked of :func:`unterstuetzte` — the ONE place that decides whether the
    knob is available — so the wire and the display can never disagree about
    it: the backend has to carry a number per request AND the model has to be
    able to think at all.

    `faehigkeiten` is what the discovery knows about the model, exactly as
    the model window hands it in. A caller that knows nothing about the model
    (`None`) gets the answer for the dialect alone — the same reading the
    eight other call sites get, and NOT a "no": "said nothing" may not be
    read as "cannot think".

    The closing `False` is a fallback and nothing else: the knob carries
    `immer_zeigen`, so every dialect hands back a row for it and the loop
    always answers. Should the table ever lose that row, staying silent
    about a number nobody vouched for is the safer of the two wrongs.
    """
    for p in unterstuetzte(dialekt, None, faehigkeiten):
        if p.name == NAME_DENKLAENGE:
            return p.aktiv
    return False


def ohne_gesperrte_denklaenge(
    werte: dict[str, Any], *, freigegeben: bool
) -> dict[str, Any]:
    """The request's parameters, without the thinking length where it is locked.

    The stored value is untouched — it simply does not go out. Coming back to
    a model whose thinking length is available sends it again, unchanged.
    One function for chat and job, and the fold takes the request its run
    already filtered with it — one decision, and no third place that could
    forget it.

    The answer is a dictionary of its own, always — also where nothing is
    dropped. Handing back the caller's own would make one request's
    parameters a second name for another's, and a later edit to either would
    silently reach the other (the fold builds its request out of the run's).
    """
    werte = dict(werte or {})
    if freigegeben or NAME_DENKLAENGE not in werte:
        return werte
    return {name: wert for name, wert in werte.items() if name != NAME_DENKLAENGE}


def uebersetzen(dialekt: str, werte: dict[str, Any]) -> dict[str, Any]:
    """Converts our names into the backend's.

    What the dialect does not know is dropped — better to leave a parameter
    out than to send one the server rejects as an error.
    """
    bekannt = DIALEKTE.get(dialekt) or DIALEKTE["openai"]
    ergebnis: dict[str, Any] = {}
    for name, wert in werte.items():
        if wert is None or name not in bekannt:
            continue
        eintrag = NACH_NAME.get(name)
        if eintrag and eintrag.ganzzahl:
            wert = int(wert)
        ergebnis[bekannt[name]] = wert
    return ergebnis


def pruefen(
    werte: dict[str, Any], kontextfenster: int | None = None
) -> dict[str, Any]:
    """Clamps values to their allowed range, discards anything unknown.

    ``kontextfenster`` caps ``max_tokens`` and the thinking length the same
    way ``unterstuetzte()`` caps them for display — without it, a stored
    value the window cannot hold went through unchanged.
    """
    sauber: dict[str, Any] = {}
    for name, wert in (werte or {}).items():
        eintrag = NACH_NAME.get(name)
        if eintrag is None or wert is None:
            continue
        try:
            zahl = float(wert)
        except (TypeError, ValueError):
            continue
        minimum, maximum = eintrag.minimum, eintrag.maximum
        if kontextfenster and name in ("max_tokens", NAME_DENKLAENGE):
            # The window is what actually fits, not a suggestion — where it
            # falls below the knob's own floor, the floor cannot win, or the
            # clamp would hand back a number the window has no room for.
            maximum = min(maximum, kontextfenster)
            minimum = min(minimum, maximum)
        zahl = max(minimum, min(maximum, zahl))
        sauber[name] = int(zahl) if eintrag.ganzzahl else zahl
    return sauber
