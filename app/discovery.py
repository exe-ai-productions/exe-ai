"""Which models are available right now?

The candidate list lives in the configuration and is maintained by hand.
What is dynamic is *reachability*: a background loop regularly knocks on all
candidates, and the frontend gets only the ones that actually answer via
``/api/v1/models``.

When an endpoint changes state, ``endpoint_status_changed`` is published —
whoever wants to react subscribes on the event bus, without this module
having to know about it.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Iterable

from app import antwortgrenze, denkablehnung, denkstufen, fenstergroesse, modellkennung
from app import dialekterkennung, dialektverdacht
from app.config import Config, EndpointConfig
from app.db.connection import jetzt_iso
from app.events import Ereignisse, EventBus
from app.parameter import denklaenge_freigegeben, unterstuetzte
from app.pfade import ist_pfad, pfad_zu_anzeigename
from app.providers import Provider, provider_bauen

log = logging.getLogger(__name__)

# How many checks in a row may go unanswered before an endpoint counts as
# gone. Three, because a single silence says nothing: OpenAI's model list
# answers in half a second or not at all, and at one strike the models
# appeared and disappeared while you were looking at them. At fifteen seconds
# between checks, a provider now has to stay quiet for the better part of a
# minute before it drops out.
STILLE_BIS_WEG = 3


def denkschalter_im_template(template: str) -> bool:
    """Does the chat template say that thinking is switchable?

    llama.cpp serves the raw template via /props — Qwen-style templates
    carry `enable_thinking` there. Kept as the plain yes/no it always was;
    what a stage control needs is the wider answer below.
    """
    return "enable_thinking" in (template or "")


def denkwoerter_im_template(template: str) -> list[str]:
    """Every word from the catalogue's pattern list this template carries.

    One string was too narrow a question. A template that spells its switch
    `thinking`, one that takes a `reasoning_effort`, one that reads a
    `thinking_budget` and one that only reacts to `/no_think` in the text
    all mean "this model can be asked to think" — and the old search saw
    exactly one of the four.
    """
    text = template or ""
    return [
        str(muster["sucht"]) for muster in denkstufen.vorlagen_muster()
        if str(muster["sucht"]) in text
    ]


# The template's effort variable, under whatever name it gives it (Kolibri
# copies `reasoning_effort` into `_sv_reasoning_effort` first).
_EFFORT_VARIABLE = r"reasoning_(?:effort|strength)\w*"

_EFFORT_AUFZAEHLUNG = re.compile(
    _EFFORT_VARIABLE + r"\s+(?:not\s+)?in\s*"
    r"(?:\((?P<runde>(?:['\"][^'\"]+['\"]\s*,?\s*)+)\)"
    r"|\[(?P<eckige>(?:['\"][^'\"]+['\"]\s*,?\s*)+)\])"
)

_EFFORT_VERGLEICH = re.compile(
    _EFFORT_VARIABLE + r"\s*(?:==|!=)\s*(?P<anf>['\"])(?P<wert>(?:(?!(?P=anf)).)+)(?P=anf)"
)


def reasoning_effort_werte_im_template(template: str) -> list[str] | None:
    """The exact words one template's own checks accept for its effort
    variable, read straight out of its source.

    A template names the accepted values right where it compares its effort
    variable against them — `not in ('xhigh', 'medium', 'low')` for one
    model; for another a chain of branches, `in ['minimal', 'low']`, then
    `== 'medium'`, then `in ['high', 'xhigh', 'max']`. Nothing a server
    reports carries this list, and a fixed one in the catalogue would be
    exactly the filter the house decided against: this is the one place the
    answer can come from.

    A text search, not a parse of the template: every enumeration and every
    `==`/`!=` against the variable counts, each word once, in the order the
    source names them (the caller puts them in the order of the stages).
    """
    text = template or ""
    funde: list[tuple[int, list[str]]] = []
    for treffer in _EFFORT_AUFZAEHLUNG.finditer(text):
        aufzaehlung = treffer.group("runde") or treffer.group("eckige") or ""
        # The closing quote must match the opening one — a value written with
        # the other quote character inside it (`"can't"`) is not cut off there.
        funde.append((
            treffer.start(),
            [wert for _, wert in re.findall(r"(['\"])((?:(?!\1).)*)\1", aufzaehlung)],
        ))
    for treffer in _EFFORT_VERGLEICH.finditer(text):
        funde.append((treffer.start(), [treffer.group("wert")]))
    werte: list[str] = []
    for _, gruppe in sorted(funde, key=lambda fund: fund[0]):
        werte.extend(wert for wert in gruppe if wert not in werte)
    return werte or None


def templates_read(paths: dict[str, str]) -> dict[str, dict[str, Any]]:
    """The thinking words of each model's own chat template, read from the
    model's folder on this machine (``chat_template.jinja`` at the
    ``model_path`` a server's status route names).

    oMLX hands no template out over any route, so a model whose template
    names real depths (``reasoning_effort``: low, medium, xhigh) was offered
    only the family row's on/off. Read the same way as a template /props
    serves (``_faehigkeiten_aus_props``). A folder this machine cannot see —
    the server runs elsewhere — gives nothing, and the family row stands.
    """
    templates: dict[str, dict[str, Any]] = {}
    # An alias names the same folder as its model: read once, given to both.
    per_folder: dict[str, dict[str, Any] | None] = {}
    for model_id, folder in paths.items():
        if folder not in per_folder:
            try:
                text = (Path(folder) / "chat_template.jinja").read_text(encoding="utf-8")
            except (OSError, ValueError):
                per_folder[folder] = None
            else:
                per_folder[folder] = {
                    "supports_reasoning_effort": None,
                    "vorlage_variablen": denkwoerter_im_template(text),
                    "effort_werte": reasoning_effort_werte_im_template(text),
                }
        if per_folder[folder] is not None:
            templates[model_id] = per_folder[folder]
    return templates


def werkzeuge_im_template(template: str) -> bool:
    """Can the chat template shape tool calls?

    Tool-capable templates (Qwen, Mistral, DeepSeek …) carry the `tools`
    key — without it the server cannot build a tool list into the prompt.
    Any further interpretation would be guesswork.
    """
    return "tools" in (template or "")


async def _faehigkeiten_erkennen(
    base_url: str,
    timeout: float,
    api_key_env: str | None,
    endpunkt_id: str,
) -> dict[str, Any] | None:
    """Asks the /props endpoint (llama.cpp) for everything the server
    reveals about itself: the thinking switch and tools live in the chat
    template, vision in `modalities` — as a table of switches or as the list
    of what the server takes (``_vision_aus_modalitaeten``).

    The request carries the endpoint's key — newer llama-server builds
    guard /props like every other route, and an unauthenticated knock
    comes back 401, which used to read as "nothing there". Read fresh
    from the environment on every call, same as the provider does.

    Three answers, and two of them used to look alike.

    ``{}`` means the server ANSWERED and there is nothing here: it replied
    404, so this build has no such route at all (mlx_lm/mlx_vlm), or it
    replied 200 with something unreadable. Settled — asking again every
    pass would knock on a door that is not there.

    ``None`` means no answer came: a timeout, a refused connection, or any
    other status. A 503 while a model file is still being read from disk is
    NOT "this server can nothing", and neither is a 401 issued before the
    key is in the environment; both are asked again. The distinction matters
    wherever an answer is kept: a silence written down as a capability
    follows that server until it stops.
    """
    import httpx

    wurzel = base_url.rstrip("/")
    if wurzel.endswith("/v1"):
        wurzel = wurzel[: -len("/v1")]
    kopf = {}
    if api_key_env and (wert := os.getenv(api_key_env, "").strip()):
        kopf = {"Authorization": f"Bearer {wert}"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            antwort = await client.get(wurzel + "/props", headers=kopf)
    except Exception:  # noqa: BLE001 - no answer at all, asked again later
        return None
    if antwort.status_code == 404:
        # There is no such route on this build. That is an answer, and it
        # does not change while this server runs.
        return {}
    if antwort.status_code != 200:
        # Busy, guarded, or broken — none of which is "can nothing", and all
        # of which pass. Asked again.
        return None
    try:
        daten = antwort.json()
    except ValueError:
        # It answered, and what it said is not readable. That is an answer.
        return {}
    if not isinstance(daten, dict):
        # Readable JSON, but not a table of what the server reveals — a list,
        # a number, a bare word. It answered and this is all it
        # said; asking again would knock at the same door, and a shape nobody
        # can read may not end the pass for it.
        _melde_unlesbare_form("the whole body", daten, endpunkt_id, "nothing")
        return {}
    return _faehigkeiten_aus_props(daten, endpunkt_id)


def _vision_aus_modalitaeten(roh: Any, endpunkt_id: str) -> bool:
    """Whether the server can see — read from either shape of `modalities`.

    Both shapes are in use, and neither is verified against a server in this
    house: llama.cpp's documentation names the LIST of what the server takes
    (``["text", "vision"]``), its client code reads a TABLE of switches
    (``{"vision": true}``). So both are read with the same meaning, and a
    list that does not carry the word really does mean no vision — it is not
    a shape nobody knows.

    A shape neither of those is — a number, a bare word, a nested something —
    is not a "no" that somebody meant: it is an answer this side cannot read.
    It is logged with its shape and read as no vision. Guessing either way
    would be worse than saying so, and nothing a server sends may keep the
    program from starting.

    Inside a table only a real ``True`` counts. ``"false"``, ``"no"``, ``"0"``
    are strings a serialising server can produce, and reading any of them as
    a yes would open the attachment surface for a blind server — the model
    would then invent what it cannot see. A plain ``False`` is an honest no
    and needs no line; anything that is neither is said out loud.
    """
    if isinstance(roh, dict):
        wert = roh.get("vision")
        if wert is True:
            return True
        if wert is None or wert is False:
            # A table that does not mention it has said nothing; a stated
            # `false` is an answer. Neither is worth a line.
            return False
        _melde_unlesbare_form("'vision'", wert, endpunkt_id)
        return False
    if isinstance(roh, list):
        return any(str(eintrag).strip().lower() == "vision" for eintrag in roh)
    if roh is None or roh == "":
        # Nothing said at all. The old `daten.get("modalities") or {}` read
        # this the same way: a server that does not mention it has not
        # refused anything.
        return False
    _melde_unlesbare_form("'modalities'", roh, endpunkt_id)
    return False


def refusal_key(zustand: Any, modell: str | None) -> str:
    """The one id a server's refused thinking stages are kept under.

    The id the model list carries for this entry (:meth:`Discovery.aufgefaechert`):
    a server with a catalogue under endpoint and model, one without under
    the endpoint alone — never under the name it reports, or the fold, the
    chat and the thinking length would each keep a list of their own for one
    server.
    """
    if not zustand.auswaehlbare_modelle:
        return zustand.endpunkt.id
    return modellkennung.bauen(zustand.endpunkt.id, modell)


def denklaenge_erlaubt(
    zustand: Any, modell: str | None = None, einstellungen: Any = None
) -> bool:
    """May a thinking length travel to THIS model of this endpoint?

    The same question the model window answers for its slider, asked once
    for the wire: the backend has to carry a number per request, AND the
    model has to be able to think at all. Both halves come from
    what the list itself reads — the capabilities :meth:`als_dict` builds
    from the thinking profile, and the refusals stored under the id the list
    carries for this model — so wire and display cannot drift apart.

    The id is built HERE, by :func:`refusal_key`, and never handed in by the
    caller: a second spelling of one model is how a refusal ends up written
    under one id and looked for under another.

    ``einstellungen`` is where the refusals are kept. Without it they read
    as none. A caller that HAS the settings may not leave them out: it would
    read a model as switchable that the list already shows as unable to
    think.
    """
    kennung = refusal_key(zustand, modell)
    abgelehnt = denkablehnung.gemerkt(einstellungen, kennung) if einstellungen is not None else []
    faehigkeiten = zustand._capabilities_aufloesen(modell, abgelehnt)  # noqa: SLF001
    return denklaenge_freigegeben(zustand.endpunkt.parameter_dialect, faehigkeiten)


def _melde_unlesbare_form(
    feld: str, wert: Any, endpunkt_id: str, gelesen_als: str = "no vision"
) -> None:
    """One line for a shape nobody can read — and nothing else.

    A capability this side cannot make sense of is not a "no" that somebody
    meant, so it is said rather than guessed at. The line carries the event
    name the run's other structured lines carry, so a reader can find it
    (`app/discovery.py` `fenstergroesse_aufgeloest`, `antwortgrenze_aufgeloest`).

    `gelesen_als` says what the shape was read AS, and it is not always the
    same thing: an unreadable `modalities` costs the picture, an unreadable
    whole body costs everything the answer could have told — thinking and
    tools included. A line that named only the picture there would be a false
    statement in a place somebody reads when something is missing.
    """
    log.info(
        "Endpoint %s: /props answered %s as %s — read as %s",
        endpunkt_id,
        feld,
        type(wert).__name__,
        gelesen_als,
        extra={"ereignis": "props_unlesbare_form", "endpunkt_id": endpunkt_id},
    )


def _faehigkeiten_aus_props(daten: dict[str, Any], endpunkt_id: str) -> dict[str, Any]:
    """What a /props answer reveals, resolved to the three switches.

    Newer builds say it outright in `chat_template_caps`; only where that
    is missing does reading the template remain — older servers serve
    nothing else.

    ``thinking`` is no longer a yes/no here. A stage control has to know
    WHICH answer the template gave: a build that reports
    `supports_reasoning_effort` has stages, one that only carries the word
    `enable_thinking` has a switch, and a template that says nothing at all
    is a different case again from one nobody has looked at.
    """
    template = str(daten.get("chat_template", ""))
    # The same care for this one: it is read as a table, and a build that
    # answers with something else there has simply not claimed anything —
    # the template below still says what it says.
    caps = daten.get("chat_template_caps")
    if not isinstance(caps, dict):
        caps = {}
    werkzeuge = caps.get("supports_tool_calls")
    if werkzeuge is None:
        werkzeuge = werkzeuge_im_template(template)
    return {
        "thinking": {
            "supports_reasoning_effort": caps.get("supports_reasoning_effort"),
            "vorlage_variablen": denkwoerter_im_template(template),
            "effort_werte": reasoning_effort_werte_im_template(template),
        },
        "tool_calls": bool(werkzeuge),
        "vision": _vision_aus_modalitaeten(daten.get("modalities"), endpunkt_id),
    }


@dataclass
class EndpunktZustand:
    endpunkt: EndpointConfig
    provider: Provider
    erreichbar: bool = False
    # How many checks in a row went unanswered. Reset by the first answer.
    stille: int = 0
    # Whether this endpoint has ever answered at all. Only then is a silence
    # worth tolerating — something that was never there cannot be briefly
    # away.
    je_geantwortet: bool = False
    zuletzt_geprueft: str | None = None
    letzter_fehler: str | None = None
    # Asked of the server as soon as it answers for the first time.
    context_tokens: int | None = None
    # Which of app/fenstergroesse.py's five sources ``context_tokens`` came
    # from. ``None`` only until the first resolution — after that it is
    # always one of the module's ``QUELLE_*`` constants, because the
    # fallback source never fails to answer.
    kontext_quelle: str | None = None
    # The window of every model in a catalogue, by model id, as the server
    # names them (``Provider.context_per_model``). ``None`` until the server
    # answered; an entry the mapping does not name shows ``context_tokens``
    # above.
    context_per_model: dict[str, int] | None = None
    # The other half of the same question: the longest answer this model is
    # allowed to write (app/antwortgrenze.py). Asked of the provider's model
    # list — a REGULAR model information, so it stays resolved for every
    # request. ``None`` means nobody names one, and then the window alone
    # decides what fits — not that the limit is zero.
    hersteller_max_tokens: int | None = None
    # The same number for every model of a catalogue, by model id, as its
    # model list names them (``Provider.answer_limit_per_model``). A limit
    # belongs to the model it is listed for: ``hersteller_max_tokens`` is the
    # reported model's, and binds no other model behind the same address.
    # ``None`` until the server answered.
    answer_limit_per_model: dict[str, int] | None = None
    # The same number from the OTHER source — a provider that turned a
    # request down and named the length it would have accepted — is not kept
    # here: it belongs to the request it happened to and its retry, and this
    # state is shared by every request at the address
    # (``antwortgrenze.Zug``).
    # What the model is called on the server. Comes from /v1/models, not from
    # the configuration — nobody should have to maintain model names there.
    gemeldeter_name: str | None = None
    # Every model this provider offers. A local server names the one it has
    # loaded; a provider in the cloud names its catalogue. Asked, never
    # maintained — a list kept by hand is wrong the day after it is written.
    modelle: list[str] = field(default_factory=list)
    # What the server reveals about itself (llama.cpp /props): thinking,
    # tool_calls, vision. Sniffed natively — nobody maintains this in a
    # file. None = not checked yet / says nothing. Two more keys arrive from
    # the provider itself where it has an answer: `familie`, the model family
    # an MLX server names natively, and `anthropic`, the capability block a
    # model list carries per model.
    faehigkeiten_erkannt: dict[str, Any] | None = None
    # Whether /props has ANSWERED — which is not the same as whether it said
    # anything. The field above carries what is known so far and may already
    # hold the model families the provider named on its own; this one says
    # whether the template half is still owed. Without it a server whose
    # /props never answers either keeps everything at "nothing known", or
    # settles a silence as the truth.
    props_beantwortet: bool = False
    # How many /props questions in a row came back with no answer at all
    # (``_faehigkeiten_erkennen`` returning ``None``). The same tolerance
    # ``stille`` gives reachability itself: a brief silence during a dialect
    # re-probe must not blank a known capability, but a route that has
    # stopped answering for good must not go on advertising it forever
    # either. Reset by any answer, settled or not.
    props_stille: int = 0
    # Whether this endpoint looks like a local MLX or vLLM server that is
    # entered under the ``openai`` dialect (app/dialektverdacht.py). Shown as
    # one line, never acted on: the configuration is the user's file, and the
    # thinking switch is what silently stops working when the two disagree.
    dialekt_verdacht: bool = False
    # Whether this endpoint has been asked if it is an oMLX server entered
    # under the plain ``openai`` dialect (app/dialekterkennung.py). Asked once
    # per stretch of reachability, like everything else the discovery learns
    # from the server itself.
    dialekt_geprueft: bool = False

    def denkprofil(
        self, modell: str | None = None, abgelehnt: Iterable[str] = ()
    ) -> denkstufen.Denkprofil:
        """Which thinking stages one model of this endpoint offers."""
        return denkstufen.stufen_fuer(
            self.endpunkt,
            modell or self.gemeldeter_name,
            self.faehigkeiten_erkannt or {},
            abgelehnt=abgelehnt,
        )

    @property
    def thinking_erkannt(self) -> bool | None:
        """Whether thinking can be set by hand at all — the plain answer."""
        if self.faehigkeiten_erkannt is None:
            return None
        return self.denkprofil().schaltbar

    @property
    def quelle(self) -> str:
        """Where the model comes from, in one line.

        **Derived**, not maintained: a field in the configuration would be
        one more line someone would have to fill in — and for third-party
        servers nobody does.

        Deliberately **without the location**. The address does not know
        where the hardware sits: a model on a desktop machine elsewhere may
        be reached via 127.0.0.1 through a tunnel. "local" would simply be
        wrong there. We only name what the address really gives away — the
        engine.
        """
        return {
            "llama_cpp": "llama.cpp",
            "mlx": "MLX",
            "vllm": "vLLM",
            "openai": "OpenAI",
        }.get(self.endpunkt.parameter_dialect, self.endpunkt.parameter_dialect)

    @property
    def anzeigename(self) -> str:
        """Name for the UI — like ``gemeldeter_name``, without private path parts.

        ``gemeldeter_name`` can be a full file path (mlx_vlm.server without
        the HuggingFace cache, e.g. ``/Users/you/models/...``). This full
        path must go to the server unchanged (see
        ``OpenAIKompatiblerProvider.modellname()``) — but in the beta UI it
        would expose the local user name and folder structure. Hence here,
        for display only, the last path segment.
        """
        name = self.gemeldeter_name or self.endpunkt.name or self.endpunkt.id
        return pfad_zu_anzeigename(name) if ist_pfad(name) else name

    @property
    def auswaehlbare_modelle(self) -> list[str]:
        """What can be picked at this provider — one entry at the very least.

        A provider that reports a catalogue is fanned out into its models. One
        that reports nothing stands for itself, exactly as before: an empty
        list here would make a working local server disappear from the picker.
        """
        return list(self.modelle) if self.modelle else []

    def _capabilities_aufloesen(
        self, modell: str | None = None, abgelehnt: Iterable[str] = ()
    ) -> dict[str, Any]:
        """Merge configuration and native detection.

        An explicit entry in the config ALWAYS wins — even a "no", so an
        operator can pin a capability off regardless of what detection
        says. Only where the config is silent does the sniffed result
        count.

        ``thinking`` answers with a LIST of stages rather than a yes: a
        model that can be asked for four different depths and one that can
        only be switched on are not the same capability, and a boolean
        could never tell them apart. An empty list is the honest "no".

        ``reasoning`` is the plain yes/no behind that list, and it is asked
        where the answer is needed as a yes/no: a backend that takes a
        thinking length per request may only offer it for a model that can
        think at all (`app/parameter.py` `unterstuetzte`). It
        comes from the same profile, so there is no second model truth.
        """
        caps = self.endpunkt.capabilities.model_dump()
        erkannt = self.faehigkeiten_erkannt or {}
        for name in ("tool_calls", "vision"):
            if caps.get(name) is None:
                caps[name] = bool(erkannt.get(name))
        profil = self.denkprofil(modell, abgelehnt)
        caps["thinking"] = profil.stufen
        caps["reasoning"] = profil.art != denkstufen.NEVER
        return caps

    def kann(self, name: str) -> bool:
        """Resolved capability for the checkpoints in the backend.

        The same truth the frontend sees via als_dict() — never read
        endpunkt.capabilities directly, it can hold None.
        """
        return bool(self._capabilities_aufloesen().get(name))

    def _catalogue_window(self, modell: str | None) -> int | None:
        """The catalogue's own window for this model — never over a value
        entered by hand for the endpoint, which wins as everywhere."""
        if not modell or self.endpunkt.context_tokens or not self.context_per_model:
            return None
        return self.context_per_model.get(modell)

    def context_for(self, modell: str | None) -> int | None:
        """The window one entry of the model list shows: the catalogue's own
        number for this model, otherwise the endpoint's one window."""
        return self._catalogue_window(modell) or self.context_tokens

    def als_dict(
        self,
        modell: str | None = None,
        sprache: str = "en",
        abgelehnt: Iterable[str] = (),
    ) -> dict[str, Any]:
        """One entry for the model list.

        Without ``modell`` the provider describes itself, the way it always
        did. With one, it describes that single model of its catalogue — same
        address, same capabilities, own id and own name.

        ``sprache`` reaches the parameter labels. English when nobody says
        otherwise — the source language, so a forgotten argument can only
        ever show the original, not a translation in the wrong place.
        """
        return {
            "id": modellkennung.bauen(self.endpunkt.id, modell),
            # Which provider the entry belongs to. The frontend groups by it
            # instead of taking the id apart itself — before, the group was
            # guessed from the host name in the address.
            "anbieter": self.endpunkt.id,
            "anbieter_name": self.endpunkt.name or self.endpunkt.id,
            "modell": modell,
            # The model the configuration names for this provider. A catalogue
            # is picked from and starts empty — but what the configuration
            # points at was picked by whoever wrote it, and unpicking it in the
            # window would leave a provider that works looking unused.
            "angeheftet": bool(modell and modell == self.endpunkt.modell),
            # What the server reports wins. The entry from the configuration
            # is only the fallback when it says nothing.
            # What the server reports, then the entry in the configuration,
            # lastly the id. Nothing is invented.
            "name": (
                (pfad_zu_anzeigename(modell) if ist_pfad(modell) else modell)
                if modell
                else self.anzeigename
            ),
            "quelle": self.quelle,
            "provider": self.endpunkt.provider,
            "dialekt": self.endpunkt.parameter_dialect,
            "reasoning_format": self.endpunkt.reasoning_format,
            "erreichbar": self.erreichbar,
            "zuletzt_geprueft": self.zuletzt_geprueft,
            "context_tokens": self.context_for(modell),
            # The number the CONFIGURATION carries, told apart from the one
            # above. That one is whichever of the two is in force, so a field
            # filled from it shows a measured value as if somebody had typed
            # it, and nobody can tell an own answer from a found one — nor
            # get back to "work it out yourself" once it looks set.
            "kontext_eigen": self.endpunkt.context_tokens or None,
            # Which of the five sources (app/fenstergroesse.py) resolved the
            # window above — only so the Cloud menu can tell a found number
            # from the fallback ("gefunden: N" vs. "Auto"). Nothing else
            # reads this; ``context_tokens`` alone is what every other part
            # of the program calculates against.
            "kontext_quelle": (
                fenstergroesse.QUELLE_SERVER
                if self._catalogue_window(modell)
                else self.kontext_quelle
            ),
            # One line in the card, no colour and no button: the program
            # points at the mismatch, the user decides.
            "dialekt_verdacht": self.dialekt_verdacht,
            "capabilities": self._capabilities_aufloesen(modell, abgelehnt),
            # The stage control's whole answer for THIS model: what it
            # offers, which of it applies unasked, what kind of control that
            # has to be, and where the answer came from. The window draws
            # the pill from this and nothing else — no second list of its
            # own, no guessing from a boolean.
            "denkprofil": self.denkprofil(modell, abgelehnt).als_dict(),
            # local | cloud | extra - see EndpointConfig.group.
            "group": self.endpunkt.group,
            # The "Zeitgrenze" switch - see EndpointConfig.timeout_enabled.
            "timeout_enabled": self.endpunkt.timeout_enabled,
            # Which variable holds the access key, and whether it is filled.
            # Never the key itself — the interface has no login, so no secret
            # ever leaves the server. A provider that answers but rejects the
            # key looks exactly like a dead host from the outside; this pair
            # is what tells the two apart in the window.
            "schluessel_env": self.endpunkt.api_key_env,
            "schluessel_gesetzt": bool(
                self.endpunkt.api_key_env
                and os.environ.get(self.endpunkt.api_key_env, "").strip()
            ),
            # Only knobs this backend actually evaluates — for THIS model,
            # which is why the resolved capabilities travel along: the
            # thinking length is offered by a backend that can carry it and
            # locked for a model that cannot think.
            "parameter": [
                p.als_dict(sprache)
                for p in unterstuetzte(
                    self.endpunkt.parameter_dialect,
                    self.context_for(modell),
                    self._capabilities_aufloesen(modell, abgelehnt),
                )
            ],
        }


class Discovery:
    """Continuously checks which endpoints answer."""

    def __init__(self, config: Config, bus: EventBus, repositories=None) -> None:
        self.config = config
        self.bus = bus
        # Where a learned context window (app/fenstergroesse.py) is read
        # from. Optional and defaulting to None for the many call sites —
        # tests among them — that build a Discovery before any database
        # exists: without it, learning simply never applies, the same
        # "nothing invented" reading every other unanswered source gets.
        self.repositories = repositories
        self.zustaende: dict[str, EndpunktZustand] = {}
        self._aufgabe: asyncio.Task | None = None
        self._laeuft = False

        for endpunkt in config.endpoints:
            if not endpunkt.enabled:
                continue
            try:
                self.zustaende[endpunkt.id] = EndpunktZustand(
                    endpunkt=endpunkt, provider=provider_bauen(endpunkt)
                )
            except Exception as fehler:  # noqa: BLE001 - one broken entry must not topple everything
                log.error("Endpoint '%s' skipped: %s", endpunkt.id, fehler)

    # --- Queries ---------------------------------------------------------

    def alle(self) -> list[EndpunktZustand]:
        return list(self.zustaende.values())

    def erreichbare(self) -> list[EndpunktZustand]:
        return [zustand for zustand in self.zustaende.values() if zustand.erreichbar]

    def provider_holen(self, endpoint_id: str) -> Provider | None:
        zustand = self.zustaende.get(endpoint_id)
        return zustand.provider if zustand else None

    def aufgefaechert(self, zustaende: list[EndpunktZustand]) -> list[tuple[EndpunktZustand, str | None]]:
        """One entry per model instead of one per provider.

        A provider that reports a catalogue appears once for each of its
        models; one that reports nothing appears once for itself. That is the
        whole difference between "one address, one model" and "one provider,
        many models" — and it lives in this one place, so nothing else has to
        know about it.
        """
        paare: list[tuple[EndpunktZustand, str | None]] = []
        for zustand in zustaende:
            modelle = zustand.auswaehlbare_modelle
            if modelle:
                paare.extend((zustand, modell) for modell in modelle)
            else:
                paare.append((zustand, None))
        return paare

    def aufloesen(self, kennung: str) -> tuple[EndpunktZustand, str | None] | None:
        """Finds provider and model for a public id.

        An id without a separator is looked up as a provider first — that is
        what chats and agents have stored from before the split, and it must
        keep working. Only then is it taken apart.
        """
        zustand = self.zustaende.get(kennung)
        if zustand is not None:
            return zustand, zustand.gemeldeter_name

        endpunkt_id, modell = modellkennung.zerlegen(kennung)
        zustand = self.zustaende.get(endpunkt_id)
        if zustand is None:
            return None
        # A model the provider does not offer is not silently swapped for
        # another — the caller reports it as not reachable, which it is.
        if modell and zustand.modelle and modell not in zustand.modelle:
            return None
        return zustand, modell or zustand.gemeldeter_name

    # --- Arriving and leaving while the service runs ----------------------

    async def anmelden(self, endpunkt: EndpointConfig) -> None:
        """Adds a candidate without a restart.

        The list is built from the configuration at startup — but a provider
        added in the window and the model server started from the window both
        arrive later, and waiting for a restart would turn both windows into
        dead ends. The check runs right away: whoever just added something is
        looking at the list this very second.

        An id that already exists is replaced, not doubled — the model server
        keeps its id across restarts, only its port may change.
        """
        try:
            zustand = EndpunktZustand(
                endpunkt=endpunkt, provider=provider_bauen(endpunkt)
            )
        except Exception as fehler:  # noqa: BLE001 - one broken entry must not topple everything
            log.error("Endpoint '%s' not registered: %s", endpunkt.id, fehler)
            return
        self.zustaende[endpunkt.id] = zustand
        await self.einmal_pruefen()

    async def abmelden(self, endpoint_id: str) -> None:
        """Removes a candidate — the counterpart of ``anmelden``.

        Whoever was chatting with it sees the model as gone, which is the
        truth; nothing else has to be told.
        """
        zustand = self.zustaende.pop(endpoint_id, None)
        if zustand is None or not zustand.erreichbar:
            return
        await self.bus.veroeffentlichen(
            Ereignisse.ENDPUNKT_STATUS_GEAENDERT,
            endpoint_id=endpoint_id,
            erreichbar=False,
        )

    # --- Checking --------------------------------------------------------

    async def einmal_pruefen(self) -> None:
        """One pass over all candidates — all at the same time."""
        if not self.zustaende:
            return

        zustaende = list(self.zustaende.values())
        ergebnisse = await asyncio.gather(
            *(
                zustand.provider.erreichbar(self.config.discovery.timeout_seconds)
                for zustand in zustaende
            ),
            return_exceptions=True,
        )

        for zustand, ergebnis in zip(zustaende, ergebnisse, strict=True):
            if isinstance(ergebnis, BaseException):
                geantwortet = False
                zustand.letzter_fehler = str(ergebnis)
            else:
                geantwortet = bool(ergebnis)
                zustand.letzter_fehler = None

            # One silence is not an outage. A single missed answer used to drop
            # the endpoint out of the picker immediately, and a provider whose
            # model list hangs every other request made models appear and
            # vanish while you looked at them. An answer counts at once; a
            # silence has to repeat before it counts.
            if geantwortet:
                zustand.stille = 0
                zustand.je_geantwortet = True
            else:
                zustand.stille += 1
            erreichbar = geantwortet or (
                zustand.je_geantwortet and zustand.stille < STILLE_BIS_WEG
            )

            vorher = zustand.erreichbar
            zustand.zuletzt_geprueft = jetzt_iso()

            # Set before the dialect probe, so it also has a value on the
            # passes where that probe is not asked at all.
            dialekt_frisch = False
            # An endpoint under the plain ``openai`` dialect may be an oMLX
            # server that only looks like one of the rest; then its thinking
            # switch has to be written in that server's words
            # (app/dialekterkennung.py). Asked once, as soon as it answers,
            # and before anything below reads the dialect: the hint about a
            # wrong dialect, the model families and the parameters all
            # follow what is found here. Set on the endpoint object the
            # provider and the settings routes share, so it counts everywhere
            # in the running service — and nowhere else: those routes write
            # config.yaml key by key out of the file itself, never out of
            # this object.
            if (
                erreichbar
                and not zustand.dialekt_geprueft
                and zustand.endpunkt.parameter_dialect == dialekterkennung.GEFRAGTER_DIALEKT
            ):
                try:
                    befund = await zustand.provider.mlx_erkennen(
                        self.config.discovery.timeout_seconds
                    )
                except Exception:  # noqa: BLE001 - purely supplementary information
                    befund = None
                # No answer at all is asked again on the next pass; an
                # answer, yes or no, settles it while the endpoint stays
                # reachable.
                zustand.dialekt_geprueft = befund is not None
                if befund:
                    zustand.endpunkt.parameter_dialect = dialekterkennung.ERKANNTER_DIALEKT
                    # Whatever the capabilities probe already found, it found
                    # as a plain openai server — and under that dialect
                    # ``denkquellen`` answers nothing at all. Asked again now
                    # that the address has a name, or the model families of
                    # this server never arrive for the rest of the session.
                    #
                    # A local flag and not a blanked field: what is known now
                    # stays readable across the network rounds between here
                    # and the capability block, and is replaced in one step
                    # once the new answer is in. Blanked here, every request
                    # landing in that stretch read "no tools, no vision, no
                    # thinking" off an endpoint that has all three.
                    dialekt_frisch = True
                    # The hint says the switch does no good under the wrong
                    # dialect; once the right one is in force it would say
                    # something that is no longer true.
                    zustand.dialekt_verdacht = False
                    log.info(
                        "Endpoint %s answers /models/status as an oMLX server: "
                        "dialect mlx for this session",
                        zustand.endpunkt.id,
                    )

            # Ask for the context size as soon as the server answers, and
            # keep asking on every further pass while the window in force is
            # not the server's own answer: the search remembers "no number"
            # per model (see kontextgroesse's docstring), so a server that
            # never answers costs nothing extra, and one that starts
            # answering after a restart is not locked out by a fallback,
            # a learned value or a table entry that arrived first.
            #
            # The name first, because the two questions below need it: the
            # window and the output limit are looked up per model, and a
            # search without the name answers "nothing" and leaves the
            # fallback standing. Fetched once, as soon as the
            # server answers. A model swap on the server is thus noticed the
            # next time it becomes reachable, not only when the service
            # restarts.
            #
            # Unless the endpoint names its model itself. A cloud provider
            # answers /v1/models with its whole catalogue, and asking it which
            # model is "the" model has no sensible answer — the configuration
            # has to say.
            #
            # ``modell_gewechselt`` widens the gates below instead of
            # blanking the fields here and letting them do it: a request
            # already in flight reads ``zustand`` between two ``await``
            # points of THIS pass, and ``erreichbar`` only turns false at
            # the very end of it (below) — a field cleared to ``None`` here
            # would sit there, reachable and window-less, for however long
            # the re-resolution below takes to await its answer, which is
            # exactly the crash `assert context_tokens is not None` in
            # generierung.py/auftraege.py exists to catch.
            modell_gewechselt = False
            if erreichbar and zustand.endpunkt.modell:
                zustand.gemeldeter_name = zustand.endpunkt.modell
            elif erreichbar:
                # Asked on EVERY pass, not only while unknown: a local server
                # can swap its loaded model without ever going silent for the
                # three passes reachability forgives, and only asking again
                # notices that. The previous name is kept until
                # a fresh answer replaces it — a single empty or failed
                # request must not blank a name that is still probably right.
                voriger_name = zustand.gemeldeter_name
                neuer_name = None
                try:
                    neuer_name = await zustand.provider.modellname(
                        self.config.discovery.timeout_seconds
                    )
                except Exception:  # noqa: BLE001 - purely supplementary information
                    log.debug("Model name of '%s' cannot be determined", zustand.endpunkt.id)
                # A server that names more than one model has a catalogue,
                # not a loaded model: a cloud provider lists everything it
                # offers, in no promised order, so its first entry moves
                # from pass to pass. That is no model change — the model
                # comes from the pick in the chat — and the name it first
                # gave stays. Only a server naming exactly one model can
                # swap it. ``zustand.modelle`` holds a list only when the
                # server named more than one (filled further down).
                catalogue = len(zustand.modelle) > 1
                if (
                    not catalogue
                    and voriger_name is not None
                    and neuer_name is not None
                    and neuer_name != voriger_name
                ):
                    # A different name with no catalogue on record: a swap,
                    # or a catalogue whose list request failed so far — that
                    # request is the one that hangs every other time. The
                    # list says which, asked only now that it matters.
                    try:
                        gefunden = await zustand.provider.modelle_auflisten(
                            self.config.discovery.timeout_seconds
                        )
                    except Exception:  # noqa: BLE001 - purely supplementary information
                        gefunden = []
                    if len(gefunden) > 1:
                        zustand.modelle = gefunden
                        catalogue = True
                if neuer_name is not None and not (catalogue and voriger_name is not None):
                    zustand.gemeldeter_name = neuer_name
                modell_gewechselt = (
                    not catalogue
                    and voriger_name is not None
                    and neuer_name is not None
                    and neuer_name != voriger_name
                )
                if modell_gewechselt:
                    log.info(
                        "Endpoint %s: model changed from %s to %s, re-resolving",
                        zustand.endpunkt.id,
                        voriger_name,
                        zustand.gemeldeter_name,
                        extra={"ereignis": "modell_gewechselt", "endpoint_id": zustand.endpunkt.id},
                    )

            # The reported name travels with the question. A server holding
            # many models and no configured name cannot be found in its own
            # list by any other means, and that is not a rare shape: thirty
            # entries, none of them marked, and the window stayed blank while
            # the number sat in the list. The name is fetched ABOVE, in this
            # same pass, so the very first question already carries it: asked
            # without it, the search finds nothing, the fallback stands, and
            # for one whole interval every reckoning — the fold threshold,
            # the answer's ceiling, the compaction request's cap, the
            # document budget — runs against a window the server never
            # reported (measured: 15-16 s after a start).
            if erreichbar and (
                zustand.kontext_quelle
                not in (fenstergroesse.QUELLE_EINGETRAGEN, fenstergroesse.QUELLE_SERVER)
                or modell_gewechselt
            ):
                vorherige_quelle = zustand.kontext_quelle
                zustand.context_tokens, zustand.kontext_quelle = (
                    await fenstergroesse.serverseitig_aufloesen(
                        zustand, self.repositories, self.config.discovery.timeout_seconds
                    )
                )
                if zustand.kontext_quelle != vorherige_quelle:
                    log.info(
                        "Endpoint %s: context window %d, source %s",
                        zustand.endpunkt.id,
                        zustand.context_tokens,
                        zustand.kontext_quelle,
                        extra={
                            "ereignis": "fenstergroesse_aufgeloest",
                            "endpoint_id": zustand.endpunkt.id,
                        },
                    )
                # Read off the answers that search has just seen, never
                # fetched for its own sake. Only ever set, never unset: a
                # later pass that finds the number on the first route sees
                # fewer answers, and that is no reason to withdraw the hint.
                zustand.dialekt_verdacht = zustand.dialekt_verdacht or dialektverdacht.verdacht(
                    zustand.endpunkt.parameter_dialect,
                    zustand.endpunkt.base_url,
                    spuren=zustand.provider.ortsspuren(),
                )

            # And the other half of the same request: how long an answer from
            # this model may be. Asked on the same terms as the window — while
            # it is still unknown, with the reported name along, and remembered
            # by the provider per model so a list that names none costs one
            # request and not one per pass. Unknown is the ordinary case: only
            # a provider that publishes the number in its model list has one,
            # and then "Auto" is capped by it instead of by the window alone.
            if erreichbar and (zustand.hersteller_max_tokens is None or modell_gewechselt):
                zustand.hersteller_max_tokens = await antwortgrenze.serverseitig_aufloesen(
                    zustand, self.repositories, self.config.discovery.timeout_seconds
                )
                if zustand.hersteller_max_tokens is not None:
                    log.info(
                        "Endpoint %s: output limit %d",
                        zustand.endpunkt.id,
                        zustand.hersteller_max_tokens,
                        extra={
                            "ereignis": "antwortgrenze_aufgeloest",
                            "endpoint_id": zustand.endpunkt.id,
                        },
                    )

            # The catalogue, same route: asked once, as soon as the provider
            # answers. Only a provider that offers a choice gets fanned out —
            # a local server with one model reports exactly that one, and
            # naming it twice would help nobody.
            #
            # An empty answer does NOT clear what we already know. The model
            # list is the very request that hangs every other time, and
            # letting a single timeout empty the picker is the flicker this
            # loop is otherwise built to avoid.
            # A pinned model in the configuration says which one the BARE
            # provider id means — it does not say the provider has only that
            # one. Both are asked for separately: the pin answers "what does
            # `openai` alone stand for", the catalogue answers "what else is
            # there to pick".
            if erreichbar and (not zustand.modelle or modell_gewechselt):
                try:
                    gefunden = await zustand.provider.modelle_auflisten(
                        self.config.discovery.timeout_seconds
                    )
                except Exception:  # noqa: BLE001 - purely supplementary information
                    gefunden = []
                if len(gefunden) > 1:
                    zustand.modelle = gefunden
            # A catalogue's models each carry their own window: asked once the
            # list is there, and again on the next pass for as long as the
            # server did not answer (``None``). An answer without numbers
            # (``{}``) is an answer and stays.
            if (
                erreichbar
                and len(zustand.modelle) > 1
                and zustand.context_per_model is None
            ):
                per_model: dict[str, int] | None = None
                try:
                    per_model = await zustand.provider.context_per_model(
                        self.config.discovery.timeout_seconds
                    )
                except Exception:  # noqa: BLE001 - purely supplementary information
                    log.debug("No window per model from '%s'", zustand.endpunkt.id)
                if per_model is not None:
                    zustand.context_per_model = per_model
                    for model_id, window in per_model.items():
                        log.info(
                            "Endpoint %s: context window %d for %s",
                            zustand.endpunkt.id,
                            window,
                            model_id,
                            extra={"ereignis": "context_per_model", "endpoint_id": zustand.endpunkt.id},
                        )
            # And the longest answer of each of them, out of the same list,
            # asked on the same terms.
            if (
                erreichbar
                and len(zustand.modelle) > 1
                and zustand.answer_limit_per_model is None
            ):
                limits: dict[str, int] | None = None
                try:
                    limits = await zustand.provider.answer_limit_per_model(
                        self.config.discovery.timeout_seconds
                    )
                except Exception:  # noqa: BLE001 - purely supplementary information
                    log.debug("No output limit per model from '%s'", zustand.endpunkt.id)
                if limits is not None:
                    zustand.answer_limit_per_model = limits
                    for model_id, limit in limits.items():
                        log.info(
                            "Endpoint %s: output limit %d for %s",
                            zustand.endpunkt.id,
                            limit,
                            model_id,
                            extra={"ereignis": "answer_limit_per_model", "endpoint_id": zustand.endpunkt.id},
                        )
            # Sniff the capabilities once, as soon as the server answers —
            # llama.cpp reveals the chat template (thinking switch, tools)
            # and modalities (vision) via /props.
            if erreichbar and (not zustand.props_beantwortet or dialekt_frisch or modell_gewechselt):
                try:
                    aus_props = await _faehigkeiten_erkennen(
                        zustand.endpunkt.base_url,
                        self.config.discovery.timeout_seconds,
                        zustand.endpunkt.api_key_env,
                        # Only for the line that says a shape could not be
                        # read: without the name it would point at nothing.
                        zustand.endpunkt.id,
                    )
                except Exception:  # noqa: BLE001 - purely supplementary information
                    # The same belt its three siblings wear (mlx_erkennen,
                    # modellname, modelle_auflisten). An answer this side
                    # cannot handle must not end the pass for every endpoint
                    # after this one, and must not keep the program from
                    # starting; `None` means nothing was learned, and the
                    # question is asked again on the next pass.
                    aus_props = None
                # What the provider says about thinking in its own words:
                # an Anthropic model list carries it per model, an MLX
                # server names the model family natively. Its own source,
                # asked whatever /props did — tied to that answer, a server
                # whose /props never replies would never name its families
                # either, and the thinking switch would go back to guessing
                # from the file name.
                try:
                    aus_anbieter = await zustand.provider.denkquellen(
                        self.config.discovery.timeout_seconds
                    )
                except Exception:  # noqa: BLE001 - supplementary only
                    aus_anbieter = {}
                # ``None`` is the silence ``_faehigkeiten_erkennen`` documents
                # as "no answer came" — a dialect switch's re-probe, or an
                # endpoint still settling, can hit exactly that mid-flight.
                # Starting fresh from it would blank what an earlier, settled
                # answer established; ``{}`` is a settled "nothing here" and
                # correctly does start fresh. But only up to the same
                # tolerance ``stille`` gives reachability itself — this gate
                # only re-asks while nothing has settled yet (below), so the
                # cap bounds how long an endpoint that never quite answers may
                # keep showing an earlier stretch's capabilities; it is not a
                # periodic recheck of an endpoint that already settled once
                # (that only bounds silence from one that never quite
                # answers — rechecking an already-settled endpoint stays a
                # separate, wider gap this does not close).
                if aus_props is None:
                    zustand.props_stille += 1
                    if zustand.props_stille < STILLE_BIS_WEG:
                        erkannt = dict(zustand.faehigkeiten_erkannt or {})
                    else:
                        erkannt = {}
                else:
                    zustand.props_stille = 0
                    erkannt = dict(aus_props)
                erkannt.update(aus_anbieter)
                paths = erkannt.pop("template_paths", None)
                # Only for a server on this machine: a path another machine
                # names may be a different file here, or none of its business.
                if isinstance(paths, dict) and dialektverdacht.ist_eigene_maschine(
                    zustand.endpunkt.base_url
                ):
                    erkannt["templates"] = await asyncio.to_thread(templates_read, paths)
                # Written in one step, never blanked first — see the dialect
                # probe above. The template half stays owed until /props
                # really answers; the rest is already worth keeping.
                zustand.faehigkeiten_erkannt = erkannt
                zustand.props_beantwortet = aus_props is not None

            elif not erreichbar:
                zustand.context_tokens = None
                zustand.kontext_quelle = None
                zustand.hersteller_max_tokens = None
                zustand.gemeldeter_name = None
                zustand.modelle = []
                zustand.context_per_model = None
                zustand.answer_limit_per_model = None
                zustand.faehigkeiten_erkannt = None
                # Whatever answers at this address next may be another
                # server, and is asked again.
                zustand.props_beantwortet = False
                zustand.props_stille = 0
                zustand.dialekt_geprueft = False

            # Written last, not first: every block above reads the LOCAL
            # ``erreichbar`` for its own "may I ask this?" check, never this
            # field — so a request landing between those blocks' awaits
            # never sees an endpoint marked reachable with no context window
            # resolved yet. Written earlier, that exact gap let
            # ``zustand.context_tokens`` be read as ``None`` on the very
            # first pass, keeping a document budget's "no window" fallback
            # reachable when it should never be — see dokumentbudget.py.
            zustand.erreichbar = erreichbar

            if vorher != erreichbar:
                await self.bus.veroeffentlichen(
                    Ereignisse.ENDPUNKT_STATUS_GEAENDERT,
                    endpoint_id=zustand.endpunkt.id,
                    erreichbar=erreichbar,
                )

    # --- Background loop -------------------------------------------------

    async def _schleife(self) -> None:
        abstand = max(1, self.config.discovery.interval_seconds)
        while self._laeuft:
            # SLEEPS FIRST, and that is the whole of it. ``starten`` already
            # awaited a full pass before this task existed, so asking here as
            # well means every endpoint is asked TWICE at every service
            # start. The second answer is the expensive one: it arrives at
            # some unpredictable moment shortly after startup and writes
            # endpoint state from the background, so anything that set that
            # state right after start — a window, a test — could find it
            # overwritten underneath itself with no way to see why.
            try:
                await asyncio.sleep(abstand)
            except asyncio.CancelledError:
                raise
            try:
                await self.einmal_pruefen()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the loop must never die
                log.exception("Discovery pass failed")

    async def starten(self) -> None:
        if self._aufgabe is not None:
            return
        self._laeuft = True
        # A first pass right away, so the UI does not have to wait.
        await self.einmal_pruefen()
        self._aufgabe = asyncio.create_task(self._schleife(), name="discovery")
        log.info("Discovery started for %d endpoints", len(self.zustaende))

    async def stoppen(self) -> None:
        self._laeuft = False
        if self._aufgabe is None:
            return
        self._aufgabe.cancel()
        try:
            await self._aufgabe
        except asyncio.CancelledError:
            pass
        finally:
            self._aufgabe = None
