"""How deeply a model is asked to think — which settings it has, and where.

One model, one answer: ``stufen_fuer()`` resolves a single endpoint plus a
single model name into a :class:`Denkprofil` — the stages that may be
offered, which of them is the default, what kind of control that is, and
which source the answer came from.

The stages themselves are a closed vocabulary (:data:`STUFEN`). They are
display keys, not request words: what a provider actually wants to read
(``none``, ``disabled``, ``false``, ``adaptive`` …) hangs off the profile in
``nativ`` and is put into the request by ``app/denkschalter.py``.

Five sources answer the question, and the first one that speaks wins:

1. the configuration's own ``capabilities.thinking`` — a hand entry always
   beats detection, the same safety rule vision and tools follow;
2. the provider itself, where it says so — an Anthropic model list carries
   ``capabilities.effort`` and ``capabilities.thinking.types`` per model;
3. what a local server gives away — the chat template's own variables, or
   the model family an MLX server reports natively;
4. the catalogue, by provider and model name;
5. the catalogue again, but only by provider — every stage it knows for that
   provider anywhere, so a model nobody has entered yet still has a working
   control instead of a dead one.

Sixth and last: the model cannot think.

The catalogue is a data file (``app/daten/denkstufen.yaml``), not constants
in here. Adding a model is then an edit to a table, not a change to code.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

import yaml

log = logging.getLogger(__name__)

# Every word the control may show, in the order a list shows them. `off` and
# `on` are the display keys of a plain switch; the rest are depths.
STUFEN: tuple[str, ...] = (
    "off",
    "on",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)

# The stages on one scale, weakest first: "off" at the bottom, every depth
# above it. "on" names no depth and stands nowhere on it. The one order
# every comparison of stages reads.
SCALE: tuple[str, ...] = tuple(s for s in STUFEN if s != "on")

# Two states that are not stages: the model thinks and nothing switches it,
# or it cannot think at all. Both are shown as a word, never as a dead
# control.
ALWAYS = "immer"
NEVER = "nie"

# What a catalogue entry may call the "off" position. Written as `none` in
# every provider table that uses that word, mapped onto the display key here
# so a list never shows two words for one thing.
AUS_ROH = "none"

KATALOGDATEI = Path(__file__).resolve().parent / "daten" / "denkstufen.yaml"

# Where a stage lands in the request when nothing else is known: the plain
# OpenAI field. Anything else is named in the catalogue.
FELD_VORGABE = "reasoning_effort"

# The source of a profile that knows nothing about the host but the plain
# OpenAI field: the only profile whose default stage, refused, is sent once
# more without it (app/api/v1/generierung.py).
SOURCE_OPENAI_FIELD = "openai_field"


@dataclass(frozen=True)
class Denkprofil:
    """What one model offers, and how the control has to look."""

    stufen: list[str] = field(default_factory=list)
    standard: str | None = None
    # stufen | schalter | immer | nie
    art: str = NEVER
    # katalog | anbieter | vorlage | hand | openai_field | unbekannt
    quelle: str = "unbekannt"
    # Display key -> the word that goes into the request. Only filled where
    # the two differ; a depth is its own word everywhere.
    nativ: dict[str, str] = field(default_factory=dict)
    # The chat template's own name for its thinking variable, where one was
    # found in it. Filled only from `quelle == "vorlage"`, and only where the
    # word is a boolean variable — `/no_think` is a token in the text and a
    # budget is a number. `None` means nobody found a name and the house
    # default stands.
    vorlage_wort: str | None = None

    @property
    def schaltbar(self) -> bool:
        """Is there anything for a hand to set?"""
        return self.art in ("stufen", "schalter") and bool(self.stufen)

    def als_dict(self) -> dict[str, Any]:
        """The profile as the window gets it.

        ``standard`` goes out RESOLVED, not as the raw catalogue entry: the
        rule for a provider that documents no default belongs on this side,
        once, and a window that had to work it out again would be a second
        copy of it waiting to drift.
        """
        return {
            "stufen": list(self.stufen),
            "standard": standardstufe(self),
            "art": self.art,
            "quelle": self.quelle,
            "nativ": dict(self.nativ),
        }


NIE_PROFIL = Denkprofil(art=NEVER, quelle="unbekannt")


# --- The catalogue ---------------------------------------------------------


@lru_cache(maxsize=1)
def katalog() -> dict[str, Any]:
    """The data file, read once.

    A missing or broken file is not worth a crash: the control then falls
    back to what the endpoint itself gives away, which is exactly what it
    did before there was a catalogue.
    """
    try:
        roh = yaml.safe_load(KATALOGDATEI.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        log.exception("Thinking stage catalogue cannot be read: %s", KATALOGDATEI)
        return {"wirte": {}, "vorlagen_muster": [], "familien": {}, "anbieter": {}}
    if not isinstance(roh, dict):
        return {"wirte": {}, "vorlagen_muster": [], "familien": {}, "anbieter": {}}
    for name in ("wirte", "familien", "anbieter"):
        if not isinstance(roh.get(name), dict):
            roh[name] = {}
    if not isinstance(roh.get("vorlagen_muster"), list):
        roh["vorlagen_muster"] = []
    return roh


def vorlagen_muster() -> list[dict[str, Any]]:
    """The words worth looking for in a chat template, in the order they
    are allowed to decide."""
    return [m for m in katalog()["vorlagen_muster"] if isinstance(m, dict) and m.get("sucht")]


def stage_fields() -> tuple[str, ...]:
    """Every request field the catalogue names as carrying a stage or the
    switch: each provider's and model's `feld` and `schalter`, each family
    row's `feld`, each template pattern's `feld` and `kwarg`. Dotted names
    stay dotted (`thinking.type`, `output_config.effort`)."""
    gefunden: list[str] = []

    def nehmen(zeile: Any, *schluessel: str) -> None:
        if not isinstance(zeile, dict):
            return
        for name in schluessel:
            wert = zeile.get(name)
            if isinstance(wert, str) and wert.strip() and wert.strip().lower() not in gefunden:
                gefunden.append(wert.strip().lower())

    daten = katalog()
    for eintrag in daten["anbieter"].values():
        nehmen(eintrag, "feld", "schalter")
        modelle = eintrag.get("modelle") if isinstance(eintrag, dict) else None
        for zeile in (modelle.values() if isinstance(modelle, dict) else ()):
            nehmen(zeile, "feld", "schalter")
    for zeile in daten["familien"].values():
        nehmen(zeile, "feld", "schalter")
    for muster in daten["vorlagen_muster"]:
        nehmen(muster, "feld", "kwarg")
    return tuple(gefunden)


def wirt_von(adresse: str) -> str:
    """The host of an address, lowercased — the path does NOT count.

    Searched in the WHOLE address, `https://proxy.test/api.openai.com/v1`
    read as OpenAI: a path anybody may choose decided which provider an
    endpoint belongs to, and with it which thinking switches its model is
    handed. So only the host is compared.

    An entry written without a scheme — `api.openai.com/v1`, the way a hand
    types it into a configuration file — still has a host; it is only the
    parser that cannot see one without `//` in front. Handing the whole
    string back instead would have let `proxy.test/api.openai.com/v1`
    through the very hole this closes. The `//` prefix makes the parser
    read the first segment as the host.

    Empty where there is really nothing to read — no endpoint loses its
    catalogue row over that, because a string with no host matched no host
    row before either.
    """
    roh = (adresse or "").strip()
    try:
        wirt = urlsplit(roh if "://" in roh else f"//{roh}").hostname
    except ValueError:
        # A malformed authority (an unbalanced IPv6 bracket, say). Nothing
        # readable as a host, and guessing one would be worse than none.
        wirt = None
    # The absolute-FQDN spelling (`api.openai.com.`, a trailing dot meaning
    # "this and nothing below the root") names the exact same host as
    # `api.openai.com` — `urlsplit` keeps that dot in `.hostname` rather
    # than dropping it, and a caller comparing hosts for equality or a dot
    # boundary must not see two different hosts where there is only one.
    return (wirt or "").lower().rstrip(".")


def ist_wirt(wirt: str, eigener: str) -> bool:
    """Is `wirt` the provider's own host `eigener` — the host itself or a
    real sub-domain of it, and nothing else?

    `api.openai.com.example.net` is somebody else's machine; it reads as a
    name that merely contains the provider's. Both providers that ask
    "is this the maker's own server" ask it here, so the rule lives once.
    """
    return wirt == eigener or wirt.endswith(f".{eigener}")


def _wirt_treffer(wirt: str, adresse: str) -> bool:
    """Whether a catalogue row's host names actually reaches `adresse`,
    anchored to a dot boundary rather than to any substring of it —
    `api.openai.com.example` must not inherit OpenAI's row just because the
    row's name happens to occur somewhere inside a longer host.

    A row with a dot in it (`api.openai.com`) is a whole host or the tail of
    one (`sub.api.openai.com` too, never `evilapi.openai.com`). A row
    without one (`dashscope`, `aliyuncs`, `moonshot`) is deliberately only
    PART of a host, so it is compared to a whole dot-delimited segment
    instead — equality would switch those three off without a word.
    """
    if "." in wirt:
        return ist_wirt(wirt=adresse, eigener=wirt)
    return wirt in adresse.split(".")


def anbieter_schluessel(endpunkt: Any) -> str | None:
    """Which provider an endpoint belongs to.

    The Anthropic dialect names itself. Everything else speaks the OpenAI
    dialect at its own address, and only the host in that address says who
    is on the other end — the configuration does not carry it.
    """
    dialekt = getattr(endpunkt, "parameter_dialect", "openai")
    if dialekt == "anthropic":
        return "anthropic"
    adresse = wirt_von(getattr(endpunkt, "base_url", "") or "")
    treffer: tuple[int, str] | None = None
    for wirt, name in katalog()["wirte"].items():
        wirt_klein = wirt.lower()
        if _wirt_treffer(wirt_klein, adresse) and (treffer is None or len(wirt) > treffer[0]):
            treffer = (len(wirt), str(name))
    return treffer[1] if treffer else None


def anbieter_eintrag(name: str | None) -> dict[str, Any]:
    eintrag = katalog()["anbieter"].get(name or "")
    return eintrag if isinstance(eintrag, dict) else {}


def modellzeile(endpunkt: Any, modellname: str | None) -> dict[str, Any]:
    """The catalogue row of one model, for the flags only it carries.

    Two models need more than a stage list: one refuses the switch object
    outright, another knows no depth at all and wants a token budget
    instead. Both are single rows in the table, read here so no provider
    name has to appear in the translator.
    """
    return _modell_nachschlagen(anbieter_eintrag(anbieter_schluessel(endpunkt)), modellname) or {}


# --- Matching names --------------------------------------------------------

_TRENNER = re.compile(r"[^a-z0-9]+")


def _teile(name: str) -> list[str]:
    """A name cut into its own pieces: lower case, separators gone."""
    return [t for t in _TRENNER.split((name or "").lower()) if t]


def _familientreffer(kandidat: str, schluessel: str) -> int:
    """How well a family key fits a name, or 0 for not at all.

    Every piece of the key has to turn up in the name, in order, and a piece
    may be spelled across several of the name's own pieces: ``gemma4`` is
    the family key, ``gemma-4-31b-it`` the name, and the two belong
    together. That is also what lets one table serve three sources at once —
    an MLX server's ``config_model_type`` (``qwen3_5``), llama.cpp's
    architecture metadatum and a plain file name all reduce to the same
    pieces.

    The answer is the number of characters the key spends, so the longest
    match can win: ``qwen3-thinking`` beats a bare ``qwen3`` on the same
    name, which is the whole point of having both.
    """
    teile = _teile(schluessel)
    namensteile = _teile(kandidat)
    if not teile or not namensteile:
        return 0
    stelle = 0
    for teil in teile:
        gefunden = -1
        for anfang in range(stelle, len(namensteile)):
            zusammen = ""
            for ende in range(anfang, len(namensteile)):
                zusammen += namensteile[ende]
                if zusammen == teil:
                    gefunden = ende + 1
                    break
                if not teil.startswith(zusammen):
                    break
            if gefunden >= 0:
                break
        if gefunden < 0:
            return 0
        stelle = gefunden
    return sum(len(t) for t in teile)


def familie_nachschlagen(*kandidaten: str | None) -> dict[str, Any] | None:
    """The family row for the first candidate that hits, longest key first."""
    familien = katalog()["familien"]
    for kandidat in kandidaten:
        if not kandidat:
            continue
        bester: tuple[int, dict[str, Any]] | None = None
        for schluessel, zeile in familien.items():
            if not isinstance(zeile, dict):
                continue
            gewicht = _familientreffer(kandidat, str(schluessel))
            if gewicht and (bester is None or gewicht > bester[0]):
                bester = (gewicht, zeile)
        if bester:
            return bester[1]
    return None


def model_key(modellname: str | None) -> str:
    """A model name the way the catalogue rows are written: lower case,
    without surrounding blanks and without a provider prefix (``minimax/``).
    The one reading for every lookup of a model's row."""
    return (modellname or "").strip().lower().rsplit("/", 1)[-1]


def _modell_nachschlagen(eintrag: dict[str, Any], modellname: str | None) -> dict[str, Any] | None:
    """The catalogue row for a model name — prefix match, longest wins."""
    modelle = eintrag.get("modelle")
    if not isinstance(modelle, dict) or not modellname:
        return None
    name = model_key(modellname)
    bester: tuple[int, dict[str, Any]] | None = None
    for schluessel, zeile in modelle.items():
        if not isinstance(zeile, dict):
            continue
        praefix = str(schluessel).lower()
        if name.startswith(praefix) and (bester is None or len(praefix) > bester[0]):
            bester = (len(praefix), zeile)
    return bester[1] if bester else None


# --- Building a profile ----------------------------------------------------


def _off_nach_vorn(stufen: list[str]) -> list[str]:
    """`off`, if present, always leads the list — shared by both cleaners so
    the ordering rule lives in exactly one place."""
    if "off" not in stufen:
        return stufen
    return ["off", *(s for s in stufen if s != "off")]


def _ohne_off(stufen: Iterable[str]) -> list[str]:
    """A stage list with the off position taken out — the one predicate
    behind a row or a family that refuses to be switched off, shared so a
    change to the rule only has to be made once."""
    return [s for s in stufen if s != "off"]


def _stufen_saeubern(roh: Iterable[Any] | None) -> list[str]:
    """Only words from the vocabulary, `none` folded onto `off`, no doubles,
    and `off` always at the head of the list.

    For a hand entry or a catalogue row: both are written by somebody who
    read the vocabulary, so a word outside it is a typo, not a model naming
    a stage nobody catalogued yet — dropped here rather than sent to a
    provider as a broken value. A model's own raw answer goes through
    :func:`_stufen_roh_saeubern` instead, which keeps every word.
    """
    raus: list[str] = []
    for wert in roh or ():
        wort = str(wert).strip().lower()
        if wort == AUS_ROH:
            wort = "off"
        if wort in STUFEN and wort not in raus:
            raus.append(wort)
    return _off_nach_vorn(raus)


def _stufen_roh_saeubern(roh: Iterable[Any] | None) -> list[str]:
    """`none` folded onto `off`, no doubles, `off` at the head — and, unlike
    :func:`_stufen_saeubern`, nothing dropped.

    A word from the closed vocabulary is put in the order the control shows
    stages; a word the vocabulary does not know is kept anyway, after the
    known ones, in the order it arrived. This is for a model's own measured
    answer only: a stage it names is not quietly cut down to the ones the
    catalogue happens to recognise.
    """
    bekannt: list[str] = []
    unbekannt: list[str] = []
    gesehen: set[str] = set()
    for wert in roh or ():
        wort = str(wert).strip().lower()
        if wort == AUS_ROH:
            wort = "off"
        if not wort or wort in gesehen:
            continue
        gesehen.add(wort)
        (bekannt if wort in STUFEN else unbekannt).append(wort)
    bekannt.sort(key=STUFEN.index)
    return _off_nach_vorn(bekannt + unbekannt)


def ist_reiner_schalter(eintrag: dict[str, Any]) -> bool:
    """Does this provider's profile name a plain on/off switch?

    A dotted name does not: `thinking.type` names a field INSIDE an object
    and is written as one. Asked here and in app/denkschalter.py, so the
    word that goes on the wire and the word the window is shown come out of
    the same question — the name used to stand in both places as the literal
    `enable_thinking`, and a provider spelling its switch otherwise got a
    profile that said one thing and a request that said another.
    """
    schalter = eintrag.get("schalter")
    return bool(schalter) and "." not in str(schalter)


def _art_bestimmen(stufen: list[str]) -> str:
    if not stufen:
        return NEVER
    return "schalter" if set(stufen) <= {"off", "on"} else "stufen"


def _nativ_bauen(dialekt: str, eintrag: dict[str, Any], stufen: list[str]) -> dict[str, str]:
    """The word each display key travels under.

    A depth is its own word everywhere; only the two ends of the scale are
    spelled differently from provider to provider.
    """
    nativ = {s: s for s in stufen if s not in ("off", "on")}
    aus = eintrag.get("aus_wort")
    an = eintrag.get("an_wort")
    if dialekt in ("llama_cpp", "mlx") or ist_reiner_schalter(eintrag):
        aus, an = "false", "true"
    if "off" in stufen:
        nativ["off"] = str(aus or AUS_ROH)
    if "on" in stufen and an:
        nativ["on"] = str(an)
    return nativ


def _profil_aus_zeile(
    zeile: dict[str, Any],
    quelle: str,
    dialekt: str,
    eintrag: dict[str, Any],
    ruecklage: Iterable[Any] | None = None,
) -> Denkprofil:
    """One catalogue or family row turned into a profile."""
    if zeile.get("immer"):
        return Denkprofil(art=ALWAYS, quelle=quelle)
    if zeile.get("nie"):
        return Denkprofil(art=NEVER, quelle=quelle)
    stufen = _stufen_saeubern(zeile.get("stufen") or ruecklage)
    # A provider with a switch of its own can always be switched off, whether
    # or not its depth list happens to carry a word for it — the two live in
    # different fields there. The list is where the two become one, so the
    # off position belongs in it unless the model refuses it outright.
    if eintrag.get("schalter") and stufen and zeile.get("aus") is not False:
        stufen = _stufen_saeubern(["off", *stufen])
    if zeile.get("aus") is False:
        stufen = _ohne_off(stufen)
    if not stufen:
        return Denkprofil(art=NEVER, quelle=quelle)
    # A row that names no standard at all has no answer to give here. Handing
    # the missing value to the sanitiser would turn it into the word "none",
    # which the sanitiser folds onto "off" — and a row carrying an off
    # position would then start every answer without thinking, unasked. Only
    # a standard the row actually spells out is read; `standard: none` stays
    # the deliberate off it is.
    roh_standard = zeile.get("standard")
    standard = _stufen_saeubern([roh_standard]) if roh_standard is not None else []
    return Denkprofil(
        stufen=stufen,
        standard=standard[0] if standard and standard[0] in stufen else None,
        art=_art_bestimmen(stufen),
        quelle=quelle,
        nativ=_nativ_bauen(dialekt, eintrag, stufen),
    )


def _aus_anthropic_capabilities(
    caps: dict[str, Any], dialekt: str, eintrag: dict[str, Any], modellname: str | None
) -> Denkprofil | None:
    """What an Anthropic model list says about one model.

    ``capabilities.effort.<stage>.supported`` names the depths,
    ``capabilities.thinking.types.adaptive.supported`` the plain switch.
    Whether the model also takes ``disabled`` is the one thing the answer
    never carries — that stays a catalogue row.
    """
    if not isinstance(caps, dict):
        return None
    denken = caps.get("thinking") if isinstance(caps.get("thinking"), dict) else {}
    aufwand = caps.get("effort") if isinstance(caps.get("effort"), dict) else {}
    if not denken.get("supported") and not aufwand.get("supported"):
        return None

    stufen: list[str] = []
    for name in ("minimal", "low", "medium", "high", "xhigh", "max"):
        blatt = aufwand.get(name)
        if isinstance(blatt, dict) and blatt.get("supported"):
            stufen.append(name)
    typen = denken.get("types") if isinstance(denken.get("types"), dict) else {}
    adaptiv = typen.get("adaptive") if isinstance(typen.get("adaptive"), dict) else {}
    if not stufen and adaptiv.get("supported"):
        stufen = ["on"]
    if not stufen:
        return None

    zeile = _modell_nachschlagen(eintrag, modellname) or {}
    if zeile.get("aus") is not False:
        stufen = ["off"] + stufen
    standard = None
    for wunsch in (zeile.get("standard"), eintrag.get("standard")):
        if wunsch in stufen:
            standard = wunsch
            break
    return Denkprofil(
        stufen=stufen,
        standard=standard,
        art=_art_bestimmen(stufen),
        quelle="anbieter",
        nativ=_nativ_bauen(dialekt, eintrag, stufen),
    )


def _effort_stufen(eigene_werte: Iterable[Any] | None, vorgabe: Iterable[Any]) -> list[str]:
    """The stage list for an effort-shaped control: the template's own
    measured words if it named any, the pattern's guessed set otherwise —
    both put through the same cleaning."""
    return _stufen_roh_saeubern(["off", *(eigene_werte or vorgabe)])


def _aus_vorlage(
    erkannt: dict[str, Any], dialekt: str, eintrag: dict[str, Any]
) -> Denkprofil | None:
    """What a local server gives away about itself.

    ``chat_template_caps.supports_reasoning_effort`` is the plain answer
    where a build offers it. Otherwise the template's own words decide, in
    the order the catalogue lists them — the bare word ``thinking`` sits
    last there because it is a piece of every other word above it.
    """
    props = erkannt.get("thinking")
    if not isinstance(props, dict):
        return None
    if props.get("supports_reasoning_effort"):
        # The build's own flag says there is a scale; its `effort_werte`
        # (read from the template's source) say which words it accepts —
        # the flag alone never overrides them with a guessed set.
        eigene_werte = props.get("effort_werte")
        stufen = _effort_stufen(eigene_werte, ("low", "medium", "high"))
        return Denkprofil(
            stufen=stufen,
            standard="medium" if eigene_werte is None else None,
            art=_art_bestimmen(stufen),
            quelle="vorlage",
            nativ=_nativ_bauen(dialekt, eintrag, stufen),
        )
    gefunden = {str(w).lower() for w in props.get("vorlage_variablen") or ()}
    if not gefunden:
        return None
    for muster in vorlagen_muster():
        if str(muster["sucht"]).lower() not in gefunden:
            continue
        if muster.get("art") == "stufen":
            # The template's own words win over the catalogue's guess for
            # this pattern — read straight out of its source, not assumed
            # from which keyword matched.
            eigene_werte = props.get("effort_werte")
            stufen = _effort_stufen(eigene_werte, muster.get("stufen") or ())
        else:
            stufen = ["off", "on"]
        return Denkprofil(
            stufen=stufen,
            standard="on" if stufen == ["off", "on"] else None,
            art=_art_bestimmen(stufen),
            quelle="vorlage",
            nativ=_nativ_bauen(dialekt, eintrag, stufen),
        )
    return None


def stufen_fuer(
    endpunkt: Any,
    modellname: str | None = None,
    erkannt: dict[str, Any] | None = None,
    *,
    abgelehnt: Iterable[str] = (),
) -> Denkprofil:
    """Which thinking stages this one model has, and where they come from.

    ``erkannt`` is what discovery sniffed off the server: ``thinking`` holds
    the chat template's own answer, ``familie`` the model family a server
    names natively, ``anthropic`` the capability block of a model list.

    ``abgelehnt`` are stages this model answered with an error once. They
    are taken out of the list and never offered again — the request that
    found out said so in the chat, so nobody is left guessing.
    """
    erkannt = detected_for(erkannt, modellname)
    dialekt = getattr(endpunkt, "parameter_dialect", "openai")
    anbieter = anbieter_schluessel(endpunkt)
    eintrag = anbieter_eintrag(anbieter)

    # A Codex model never takes `minimal`, whichever row or list it inherits
    # its stages from: the Responses API refuses it for every Codex model.
    weg = [*abgelehnt, "minimal"] if "codex" in (modellname or "").lower() else abgelehnt
    profil = _ohne(_aufloesen(endpunkt, modellname, erkannt, dialekt, eintrag, anbieter), weg)
    # Stamped last, and on ANY profile: the template said what its thinking
    # variable is called, and that does not stop being true because a family
    # row answered the question about the STAGES first. Written into each
    # branch instead, the fix reached every model except the two the
    # catalogue names as carriers of the bare word — both stand in
    # `familien`, so the family row always won.
    wort = vorlage_wort_aus(erkannt)
    if wort and profil.vorlage_wort != wort:
        return replace(profil, vorlage_wort=wort)
    return profil


def detected_for(erkannt: dict[str, Any] | None, modellname: str | None) -> dict[str, Any]:
    """What discovery found, seen from one model of the endpoint.

    A server holding many models may have had each one's own template read
    (app/discovery.py, ``templates_read``): that one answers for this model,
    the same way a template /props serves answers for its one. One place for
    the stage lookup and for the switch that goes out (app/denkschalter.py),
    so the two never read different templates.
    """
    erkannt = erkannt or {}
    templates = erkannt.get("templates")
    if isinstance(templates, dict) and not isinstance(erkannt.get("thinking"), dict):
        own = templates.get(modellname or "")
        if isinstance(own, dict):
            return {**erkannt, "thinking": own}
    return erkannt


def vorlage_wort_aus(erkannt: dict[str, Any]) -> str | None:
    """The chat template's own name for its thinking variable, or ``None``.

    Only where the word IS a boolean variable: the catalogue says so with
    `kwarg`, and `/no_think` (a token in the text) and `thinking_budget` (a
    number) carry none. Same order as the stage lookup, so a template that
    spells both `enable_thinking` and `thinking` is read the same way twice.
    """
    denken = erkannt.get("thinking")
    gefunden = {
        str(w).lower()
        for w in (denken.get("vorlage_variablen") if isinstance(denken, dict) else None) or ()
    }
    if not gefunden:
        return None
    for muster in vorlagen_muster():
        if str(muster["sucht"]).lower() in gefunden and muster.get("kwarg"):
            return str(muster["kwarg"])
    return None


def _aufloesen(
    endpunkt: Any,
    modellname: str | None,
    erkannt: dict[str, Any],
    dialekt: str,
    eintrag: dict[str, Any],
    anbieter: str | None,
) -> Denkprofil:
    # 1 — the hand. An entry in the configuration wins over everything,
    # including a "no": somebody who pinned a capability off means it.
    faehigkeiten = getattr(endpunkt, "capabilities", None)
    hand = getattr(faehigkeiten, "thinking", None)
    if isinstance(hand, list):
        stufen = _stufen_saeubern(hand)
        if not stufen:
            return Denkprofil(art=NEVER, quelle="hand")
        return Denkprofil(
            stufen=stufen,
            standard=None,
            art=_art_bestimmen(stufen),
            quelle="hand",
            nativ=_nativ_bauen(dialekt, eintrag, stufen),
        )
    if hand is False:
        return Denkprofil(art=NEVER, quelle="hand")
    if hand is True:
        # The old form of the hand switch: a plain yes, which was all it
        # could say. Read as the switch it always was.
        stufen = ["off", "on"]
        return Denkprofil(
            stufen=stufen,
            standard="on",
            art="schalter",
            quelle="hand",
            nativ=_nativ_bauen(dialekt, eintrag, stufen),
        )

    # 2 — the provider says it itself.
    anthropisch = erkannt.get("anthropic")
    if isinstance(anthropisch, dict):
        eigen = anthropisch.get(modellname or "") or anthropisch.get("*")
        profil = _aus_anthropic_capabilities(eigen or {}, dialekt, eintrag, modellname)
        if profil:
            return profil

    # 3 — what a local server gives away: the family it names natively, the
    # name of the file it loaded, or the words in its chat template. Only
    # asked where such an answer can exist at all — a cloud address has no
    # template, and a family read off a cloud model name would shadow the
    # catalogue entry that was written for it.
    #
    # The family row still speaks first — it is what catches an always- or
    # never-thinking model, whose template carries no switch at all for a
    # text search to find (see the module docstring in the catalogue). But a
    # row that only knows a plain switch must not silence a template that
    # names real depths of its own: the row is a guess from a name, the
    # template is the model's own answer (measured against
    # Qwen3.8-27B-GSQ-RCO-IQ3_S.gguf, whose family row `qwen3` knows only
    # "off"/"on" while its template accepts `xhigh`, `medium`, `low`).
    lokal = dialekt in ("llama_cpp", "mlx")
    familien = erkannt.get("familien") if isinstance(erkannt.get("familien"), dict) else {}
    familie = familien.get(modellname or "") or erkannt.get("familie")
    if lokal or familie or isinstance(erkannt.get("thinking"), dict):
        zeile = familie_nachschlagen(familie, modellname if lokal else None)
        profil = _aus_vorlage(erkannt, dialekt, eintrag)
        if zeile:
            familienprofil = _profil_aus_zeile(zeile, "vorlage", dialekt, eintrag)
            if familienprofil.art == "schalter" and profil is not None and profil.art == "stufen":
                # The family row still decides whether "off" may be offered
                # at all — a template naming real depths does not undo a row
                # that marks this model as refusing to be switched off.
                if zeile.get("aus") is False and "off" in profil.stufen:
                    engere_stufen = _ohne_off(profil.stufen)
                    profil = replace(
                        profil,
                        stufen=engere_stufen,
                        art=_art_bestimmen(engere_stufen),
                        nativ={k: v for k, v in profil.nativ.items() if k in engere_stufen},
                    )
                # A default the row spells out still applies where the
                # template's own richer list happens to carry that same word.
                if familienprofil.standard in profil.stufen:
                    profil = replace(profil, standard=familienprofil.standard)
                return profil
            return familienprofil
        if profil:
            return profil

    # 4 — the catalogue, by provider and model.
    zeile = _modell_nachschlagen(eintrag, modellname)
    if zeile is not None:
        return _profil_aus_zeile(zeile, "katalog", dialekt, eintrag, eintrag.get("stufen"))

    # 5 — the catalogue by provider alone: every stage it knows for this
    # provider anywhere. A model nobody has entered yet keeps a control that
    # works; a stage the model refuses is reported and remembered.
    union = _stufen_saeubern(eintrag.get("stufen"))
    if union:
        return Denkprofil(
            stufen=union,
            standard=None,
            art=_art_bestimmen(union),
            quelle="unbekannt",
            nativ=_nativ_bauen(dialekt, eintrag, union),
        )

    # 6 — a host no catalogue entry knows, speaking the OpenAI dialect: the
    # plain OpenAI field and its stages, `medium` where nobody picked one. A
    # server that refuses the field is learned from (app/denkablehnung.py),
    # and a turn that went out with the default stage is sent once more
    # without it.
    if anbieter is None and dialekt == "openai":
        stufen = _effort_stufen(None, _openai_field_stages())
        if stufen:
            return Denkprofil(
                stufen=stufen,
                standard="medium" if "medium" in stufen else None,
                art=_art_bestimmen(stufen),
                quelle=SOURCE_OPENAI_FIELD,
                nativ=_nativ_bauen(dialekt, eintrag, stufen),
            )

    # 7 — nothing anywhere says this model can think.
    return Denkprofil(art=NEVER, quelle="unbekannt")


def _openai_field_stages() -> list[Any]:
    """The stages the catalogue's template pattern for the plain OpenAI
    field names — the field an unknown host is sent."""
    for muster in vorlagen_muster():
        if muster.get("feld") == FELD_VORGABE and muster.get("art") == "stufen":
            return list(muster.get("stufen") or ())
    return []


def _ohne(profil: Denkprofil, abgelehnt: Iterable[str]) -> Denkprofil:
    """The profile without the stages this model has already refused."""
    weg = {str(s).lower() for s in abgelehnt or ()}
    if not weg or not profil.stufen:
        return profil
    stufen = [s for s in profil.stufen if s not in weg]
    if stufen == profil.stufen:
        return profil
    if not stufen:
        return Denkprofil(art=NEVER, quelle=profil.quelle)
    return Denkprofil(
        stufen=stufen,
        standard=profil.standard if profil.standard in stufen else None,
        art=_art_bestimmen(stufen),
        quelle=profil.quelle,
        nativ={k: v for k, v in profil.nativ.items() if k in stufen},
    )


def standardstufe(profil: Denkprofil) -> str | None:
    """Which stage applies when nobody has picked one.

    The provider's own default first. Where none is documented, the middle
    of the scale: a control that starts at the top spends somebody's budget
    without being asked, one that starts at the bottom makes a thinking
    model look broken.
    """
    if not profil.schaltbar:
        return None
    if profil.standard in profil.stufen:
        return profil.standard
    for wunsch in ("medium", "high", "on"):
        if wunsch in profil.stufen:
            return wunsch
    # Nothing documented, none of the usual middle words offered: a known
    # word still beats an unvetted one `_stufen_roh_saeubern` may have kept
    # after it — an uncatalogued word becomes the silent default otherwise.
    bekannt = [s for s in profil.stufen if s in STUFEN]
    return bekannt[-1] if bekannt else profil.stufen[-1]
