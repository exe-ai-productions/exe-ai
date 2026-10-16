"""The one field: which model drives an agent or cron run.

Before this there were four places that said which model a scheduled run
uses — the agent file's ``model:`` head field, the start window's pick, the
Extended-Workflow slot, and "the first endpoint that answers". Four answers
to one question is three too many: every one of them raised "and which of
them counts right now?".

There are two left. This field is one of them, and it applies to everything
that runs without an explicit pick — every cron firing, every agent start
with no model chosen. The other is the hand pick in the start window, which
is the exception for ONE run and is stored nowhere.

Three kinds of answer fit in the one field, and deliberately in ONE field
rather than a switch plus a list:

    slot     a local model file, loaded into this program's own second
             process (app/agentenserver.py) — the program loads it, keeps it
             loaded, and it answers on 127.0.0.1
    kennung  any id the discovery can resolve — ``runner`` for the main
             server's currently loaded model (nothing loads on top), or
             ``endpunkt:modell`` for a cloud provider

The point of that split being this small: all three end up as ONE id handed
to ``discovery.aufloesen``. The slot registers itself with the discovery at
start and unregisters at stop, exactly like the main runner, so there is no
second resolution path anywhere and nothing has to ask "is this a slot?" at
run time. What that also means, and it is wanted: the slot's model shows up
in the chat's model picker — a small model that is loaded is a model one can
talk to.

Stored as an object, like every other switch in the house: the settings
route reads a falsy value as "nothing set" and lets the scope above take
over, so a bare ``False`` could never switch anything OFF.

The same object also carries HOW the slot runs — window, layers, port, the
speed module and projector of each model file, and the engine levers. That
is deliberate and it is the one place they may live:

  * The slot starts by itself at every program start (app/main.py), and at
    that moment there is no browser. A value only a page knows is a value the
    autostart would replace with a default. The main model's own numbers did
    live in ``localStorage`` until they moved into a key of their own
    for the same reason (app/runnermodellwahl.py).
  * One place, not two. The file this slot loads and the window it loads it
    into are one decision; splitting them across two settings keys is how
    "and which of them counts now?" gets asked a second time.

Every one of those values is therefore stored, and NONE of them stands in the
code any more. What used to happen instead — the route sending only the file
name and the runner's own keyword defaults deciding the rest — is exactly the
bug this fixes: an 8192 nobody chose and nobody could change.

The choice is the consent. The slot starts by itself at every program start
(app/main.py) exactly while this field names a model file — a file somebody
picked is a file somebody wants loaded, and no switch beside it has to say so
a second time. An empty field names the main model, and the main model needs
no slot: there is nothing this field can ask for that would load a second
process unasked.
"""

from __future__ import annotations

from typing import Any

from app import modellkennung
from app.db.repositories.einstellungen import GLOBAL, WriteRefused
from app.feineinstellungen import Feineinstellungen

SCHLUESSEL = "agentenmodell"

# The window the slot loads its model into when nobody has chosen one yet.
#
# It has to be at least the 8192 that stood here before, because that number
# was already in force on every machine — a default that shrinks somebody's
# running setup is not a default, it is a regression. Beyond that the choice
# is 16384 for a measured reason: the system prompt of an agent run with
# fifteen tools takes about 6300 tokens, so 8192 leaves roughly 1800 for the
# task, the tool results and the answer together. 16384 is the next rung of
# the ladder the window offers, it is the first one where the run has more
# room for its work than for its own preamble (~10000 left), and it costs
# little — the KV cache grows by roughly 0.13 GB for a 2 GB model file.
#
# It is a starting point, not a limit. The whole point of this key is that
# the number is the user's to change.
KONTEXT_VORGABE = 16384

# The bounds the window's own fields carry, repeated here because a stored
# value can come from anywhere — an old version, a hand-edited database, a
# direct call on the settings route.
KONTEXT_MIN, KONTEXT_MAX = 512, 1_048_576
# No layer count is named: llama.cpp places the layers itself ("auto"), the
# same rule as the main server's key (app/runnermodellwahl.py).
SCHICHTEN_VORGABE = None
SCHICHTEN_MIN, SCHICHTEN_MAX = 0, 999
PORT_MIN, PORT_MAX = 1024, 65535

# How many model files may carry a remembered module pair — the same cap the
# main server's key holds (app/runnermodellwahl.py). A write that would grow
# the row past it is refused, never shortened.
MODULE_PAIR_LIMIT = 500

VORGABE: dict[str, Any] = {
    "kontext": KONTEXT_VORGABE,
    "schichten": SCHICHTEN_VORGABE,
    # None means "the slot's own port" (app/agentenserver.py). The number is not
    # repeated here: the slot owns its port, this key only records a hand
    # that moved it.
    "port": None,
    # ``{datei: {"drafter": …, "vision": …}}``, kept per model file: this
    # server is switched between files, and the projector that belongs to a
    # vision model is nonsense for the one next to it. Inside an entry
    # ``None`` means "never chosen for this file" and ``""`` means "chosen:
    # none".
    "module": {},
    "fein": Feineinstellungen().als_daten(),
    # Whether the program may bring the slot up by itself at program start,
    # ahead of anybody asking for it (the same lever the main model's own
    # key carries, app/runnermodellwahl.py). Does not touch the
    # slot waking for a due cron entry (app/agentenserver.py
    # ``slot_starten_wenn_gewollt``, ``faellig``) — that is the program
    # answering a run that needs it NOW, not preloading ahead of one.
    #
    # Shipped ON: the slot has always started at every program launch while
    # a model was chosen, and defaulting this off would silently take that
    # away from every installation that has it today.
    "vorladen": True,
}

# The two kinds of answer the value can be. "slot" means the value is a
# model FILE this program loads itself; "kennung" means it is an id the
# discovery already knows about and nothing has to be started for it.
SORTE_SLOT = "slot"
SORTE_KENNUNG = "kennung"
SORTEN = (SORTE_SLOT, SORTE_KENNUNG)

# The id the main server's currently loaded model answers under. Named here
# as well as in the runner route so the settings side does not have to
# import a route module to know what "the main model" is written as.
HAUPTMODELL = "runner"

# A file name in the model folder, or an ``endpunkt:modell`` id. Bounded
# like every other stored string: the settings column holds JSON and cannot
# check anything by itself.
WERT_HOECHSTLAENGE = 200


def wahl_pruefen(wert: Any) -> dict[str, Any]:
    """``agentenmodell``: the kind and the value, before storing.

    Each key survives only when it was sent. An unknown kind is written as
    "no kind" rather than refused — the value is then read as an id, which
    is what every choice but a slot file is, and a settings write that fails
    outright would lose the value along with it. Dropping the key instead
    would leave the PREVIOUS kind standing under the new value, and a stored
    slot would then try to load an id as a file name.

    An empty value IS an answer: "nothing chosen" is a real state of this
    field, and dropping it would let an earlier choice walk back in on the
    next load.

    There is no switch beside them any more. A stored ``an`` from an older
    installation is simply not read: the field has no off state, and what
    no choice names is the main model.
    """
    if not isinstance(wert, dict):
        return {}
    sauber: dict[str, Any] = {}
    if "sorte" in wert:
        sorte = str(wert["sorte"] or "").strip()
        sauber["sorte"] = sorte if sorte in SORTEN else ""
    if "wert" in wert:
        sauber["wert"] = str(wert["wert"] or "").strip()[:WERT_HOECHSTLAENGE]
    # The start values. Clamped rather than refused, the same rule the engine
    # levers already follow: a number out of range is a number to bring into
    # range, and a settings write that failed outright would take the choice
    # down with it.
    if "kontext" in wert:
        sauber["kontext"] = _zahl(
            wert["kontext"], KONTEXT_MIN, KONTEXT_MAX, KONTEXT_VORGABE
        )
    if "schichten" in wert:
        # None survives as None: "no count named" is a real answer here.
        sauber["schichten"] = (
            None if wert["schichten"] is None
            else _zahl(wert["schichten"], SCHICHTEN_MIN, SCHICHTEN_MAX, None)
        )
    if "port" in wert:
        # None survives as None: "the slot's own port" is a real answer here,
        # not a missing one.
        sauber["port"] = (
            None if wert["port"] in (None, "", 0)
            else _zahl(wert["port"], PORT_MIN, PORT_MAX, None)
        )
    if "module" in wert:
        roh = wert["module"] if isinstance(wert["module"], dict) else {}
        module: dict[str, dict[str, str | None]] = {}
        for datei, eintrag in roh.items():
            if not isinstance(eintrag, dict):
                continue
            # Only the role that was sent survives: a row writes one of the
            # two, and filling the other in with ``None`` would make "speed
            # module changed" read as "projector never chosen" the moment
            # the two are merged rather than replaced. A file name, never a
            # path — the runner checks the folder boundary again before it
            # starts anything.
            module[str(datei)[:WERT_HOECHSTLAENGE]] = {
                rolle: _modulname(eintrag[rolle])
                for rolle in ("drafter", "vision")
                if rolle in eintrag
            }
        sauber["module"] = module
    if "fein" in wert:
        # Checked by building the real thing and reading it back, exactly as
        # app/feineinstellungenwahl.py does — the clamping rules live next to
        # the flags they turn into, and writing them twice is how two copies
        # drift apart.
        sauber["fein"] = Feineinstellungen.aus_daten(
            wert["fein"] if isinstance(wert["fein"], dict) else None
        ).als_daten()
    if "vorladen" in wert:
        sauber["vorladen"] = bool(wert["vorladen"])
    return sauber


def _zahl(roh: Any, tief: int, hoch: int, ersatz: int | None) -> int | None:
    try:
        return max(tief, min(hoch, int(roh)))
    except (TypeError, ValueError):
        return ersatz


def _modulname(roh: Any) -> str | None:
    """A stored companion file name, with the difference between the two
    empties kept.

    ``None`` is "nobody has said", ``""`` is "said: none". They are two
    different answers and folding them together is not a shortcut, it is a
    loss: ``None`` is exactly what lets the folder manifest and the name
    heuristic step in (app/modellrunner.py ``starten`` and ``befehl``). A
    projector switched off by hand therefore came back on the command line as
    ``--mmproj``, attached by the heuristic, while the row in the window went
    on saying "none".

    The main model server's key has kept the two apart since the same finding
    was made there (app/runnermodellwahl.py ``_name``); this is that rule on
    the second key.
    """
    if roh is None:
        return None
    return str(roh).strip()[:WERT_HOECHSTLAENGE]


def _module_count(row: Any) -> int:
    module = row.get("module") if isinstance(row, dict) else None
    return len(module) if isinstance(module, dict) else 0


def row_check(old: Any, new: Any) -> None:
    """Refuses a row that a write would grow past ``MODULE_PAIR_LIMIT``
    module pairs, by raising ``WriteRefused``; nothing is written then. Only
    growth is refused, so a row stored larger before the cap was enforced
    still takes a write that adds no module."""
    count = _module_count(new)
    if count > MODULE_PAIR_LIMIT and count > _module_count(old):
        raise WriteRefused("More module pairs are stored than a row can hold.")


def wahl(repositories) -> dict[str, Any]:
    """What the field says right now — global scope only.

    No model or chat scope, unlike the switches that follow the settings
    cascade: this is the answer for runs that have no chat and whose model
    is the very thing being decided. A per-model setting for "which model"
    would be a circle.
    """
    stand = repositories.einstellungen.zusammengefuehrt(
        SCHLUESSEL, vorgabe=dict(VORGABE)
    )
    if not isinstance(stand, dict):
        return dict(VORGABE)
    return stand


def kennung(repositories, *, slot_id: str) -> str | None:
    """The one id a run without an explicit pick resolves — or ``None``.

    ``None`` means "this field has nothing to say", and the caller then takes
    the MAIN model — not the first endpoint that answers, which is what it
    used to do (app/api/v1/auftraege.py). That is the case when
    nothing is chosen: the field has no off state, and "nothing chosen" is
    the state every fresh installation starts in.

    ``slot_id`` is handed in rather than imported so this module stays free
    of the server it names — the slot's endpoint id belongs to the slot.
    """
    stand = wahl(repositories)
    wert = str(stand.get("wert") or "").strip()
    if not wert:
        return None
    if stand.get("sorte") == SORTE_SLOT:
        # The slot answers under its own fixed endpoint id, not under the
        # file name it happens to have loaded — the file is what gets
        # started, the id is what gets asked.
        return slot_id
    return wert


def hauptmodell_gewaehlt(repositories) -> bool:
    """Whether this field points at the main server's model.

    The counterpart of ``slot_datei`` for the other kind the program can
    bring up by itself: that one answers "does a slot need starting?", this
    one answers "may the main model be preloaded?". Both are read from the
    one field and nowhere else, so neither can drift from what the window
    shows.

    Deliberately narrower than ``kennung``: a cloud id also travels as a
    ``kennung``, and there is nothing to load for it. Only this program's own
    main server answers here — ``runner`` and ``runner:<modell>`` alike, the
    two ways ``ist_hauptmodell`` spells the same server.

    Nothing chosen counts as chosen HERE — that is the whole point of the
    field having no off state: the row shows the main model, and
    the main server is the one this answer is about. A chosen slot file and a
    chosen foreign id both answer ``False``.

    This is the field's half of "would the run land on the main server?"; the
    other half is whether the agent server is there to take it instead
    (``hauptmodell_ist_das_ziel`` below). Only the two together answer the
    question the preload asks.

    The empty value is read first, and on its own: a stored row may carry a
    kind beside it — ``wahl_pruefen`` writes one whenever it was sent — and
    "no value" answers the same question as "no kind" (``kennung``,
    ``slot_datei``), so it has to answer the same here.
    """
    stand = wahl(repositories)
    wert = str(stand.get("wert") or "").strip()
    if not wert:
        return True
    return stand.get("sorte") == SORTE_KENNUNG and ist_hauptmodell(wert)


def hauptmodell_ist_das_ziel(repositories, discovery, *, slot_id: str) -> bool:
    """Whether a run without a hand pick would end on the MAIN server.

    The question the preload asks (app/modellvorlauf.py): it
    loads a model ahead of a due time, and it may only do that for the server
    the run would really land on — everything else is memory occupied for
    nothing, a server swapped out from under the chat, or a load started for
    a run that never waits for it.

    Two halves have to hold. The field must not name something of its own
    (``hauptmodell_gewaehlt``: a slot file, or a foreign id) — and then the
    ORDER has to end on the main server, which is the question ``lauf_kennung``
    answers. Asked rather than reproduced, because it has four ways to end
    elsewhere: the agent server answering, the agent server answering the tool
    question where ours does not, a reachable main model that cannot call
    tools, and no candidate at all.

    That last one counts as this server's: with nothing else able to take the
    run, the main model is the one thing that would make it possible, and
    loading it is the whole purpose here. The tools are asked FOR on purpose —
    a run that might need them is the one that waits (``werkzeuge`` above).

    Read fresh on every tick, never remembered: the agent server is started
    and stopped by hand, and the tick a user starts it is the tick the preload
    stops being needed.
    """
    if not hauptmodell_gewaehlt(repositories):
        return False
    antwort = lauf_kennung(repositories, discovery, slot_id=slot_id, werkzeuge=True)
    if antwort is None:
        return True
    return ist_hauptmodell(antwort)


def ist_hauptmodell(kennung: str) -> bool:
    """Does this id name the main model?

    ``runner`` and ``runner:<modell>`` are the same server — the one this
    program starts itself. A run whose model is that one is in the same
    position as a run with nothing chosen at all, and the two take the same
    way out when the server is not up. A slot file or a foreign
    id is not this: those were picked on purpose, and a missing main server
    says nothing about them.
    """
    return modellkennung.zerlegen(kennung or "")[0] == HAUPTMODELL


def _antwort(discovery, endpunkt_id: str, *, werkzeuge: bool) -> str | None:
    """What this ONE server answers as — or ``None`` while it does not.

    Two answers that stay apart on purpose: the agent server is named by its
    own id, because the file it holds is what got started and the id is what
    gets asked (``kennung`` above), while the main server is named by the
    model the discovery read off it. Everything else about the two is the
    same question — does it answer, and (when the run works through tools)
    can it call them.
    """
    gefunden = discovery.aufloesen(endpunkt_id)
    if gefunden is None:
        return None
    zustand, name = gefunden
    if not zustand.erreichbar:
        return None
    if werkzeuge and not zustand.kann("tool_calls"):
        return None
    if endpunkt_id == HAUPTMODELL:
        # The reported name only while the server also offers it: an id
        # naming a model the provider does not list resolves to nothing
        # (app/discovery.py ``aufloesen``), and the caller reports that as
        # unreachable — a run that cannot start because of a name built here.
        if zustand.modelle and name not in zustand.modelle:
            name = None
        return modellkennung.bauen(zustand.endpunkt.id, name)
    return zustand.endpunkt.id


def rueckfall(discovery, *, slot_id: str, werkzeuge: bool = False) -> str | None:
    """The next of OUR TWO servers that answers — the agent server first.

    The one place that knows this order, and the order has exactly two
    entries: the agent server, and behind it the main model
    server. Both are llama.cpp servers this program starts itself, and both
    exist for exactly this — a run belongs on them and nowhere else.

    An endpoint from the configuration is never taken, not even as the only
    one answering and not even when it describes a machine on this desk:
    this program did not start it, it does not know what is
    loaded there, and a cloud provider would cost money and send the run off
    the machine — none of which is a decision a missing main server may make.
    What used to be taken here was ``endpunkt.group == "local"``, and that
    reading is what made a handwritten ``group: local`` on an embedding
    server reachable for an agent.

    ``werkzeuge`` asks for ``kann("tool_calls")`` on top — a run that USES
    tools must not land silently on a model that cannot call them (the case
    the old loop over every endpoint let through).

    ``None`` means neither of the two is there — the refusal stands in that
    case. Start (app/api/v1/auftraege.py) and cron pre-check
    (app/cronablauf.py) have to agree on all three cases, and they do,
    because they ask this one function through ``lauf_kennung``.
    """
    for endpunkt_id in (slot_id, HAUPTMODELL):
        antwort = _antwort(discovery, endpunkt_id, werkzeuge=werkzeuge)
        if antwort:
            return antwort
    return None


def lauf_kennung(
    repositories,
    discovery,
    *,
    slot_id: str,
    endpoint_id: str | None = None,
    werkzeuge: bool = False,
) -> str | None:
    """The model one run resolves to — the whole order, in one place.

    Two callers ask this and both have to get the same answer: the agent
    start (app/api/v1/auftraege.py) before it books a run, and the cron
    pre-check (app/cronablauf.py) before it calls a due schedule ready. A
    pre-check that disagrees either way leaves the due time open, books
    nothing and repeats its warning on every tick — and a start that
    disagrees refuses a schedule the pre-check called fine.

    The order, and there is no other:

    1. ``endpoint_id`` — the hand pick in the start window, when one was
       given: the exception for ONE run, stored nowhere. Picked there are
       exactly the two servers from 3, so a pick of the agent server walks
       the same way they do instead of standing alone (below).
    2. The one field (``kennung`` above).
    3. For both of those, when nothing is chosen or the main model is: the
       main server's model, and where that is not there, the next of our two
       servers that answers — the agent server first (``rueckfall``).

    A choice that is neither empty nor the main model stands as it was made
    — a slot file and a foreign id are asked for as they are, and a missing
    main server says nothing about them.

    ``werkzeuge`` is the one requirement that outranks the field: a run that
    works through tools must not land on an endpoint that cannot call them,
    or it answers out of its own head and ends "done". The field
    yields to the main model and then to the fallback for it; an id that
    resolves to nothing yields to neither — that is an answer for the caller
    to report, not a reason to take a different model. The hand pick is
    exempt: somebody chose THIS model for THIS run a second ago.

    The one pick that is not exempt is the agent server's own id, and only as
    a PICK: it is not a choice of one server but the name of the first entry
    in 3, so it is read there — when the agent server does not answer, the run
    goes to the main model rather than being refused (the start window
    preselects the agent server, and a preselection nobody made must
    not be what stops a run).

    A slot FILE in the field is the other thing that answers with this id, and
    it is deliberately not the same: the field says "this program holds this
    file" (``slot_datei``), the autostart brings it up (app/agentenserver.py),
    and a run a person configured waits for it instead of quietly going
    somewhere else. Both answer with ``slot_id``, so the pick and the field
    have to be told apart by WHERE the id came from, not by its value.

    ``None`` means no model at all — the start refuses it with 400, the
    pre-check reads it as "not ready".
    """
    # An empty string is not a pick: it is what a request without a pick looks
    # like after a query string kept its key (``?endpoint_id=``).
    hand = bool(endpoint_id)
    gewaehlt = endpoint_id or kennung(repositories, slot_id=slot_id)
    if (
        hand
        and gewaehlt == slot_id
        and _antwort(discovery, slot_id, werkzeuge=werkzeuge) is None
    ):
        gewaehlt = None
    if gewaehlt and not ist_hauptmodell(gewaehlt):
        if hand or not werkzeuge:
            return gewaehlt
        gefunden = discovery.aufloesen(gewaehlt)
        if gefunden is None or gefunden[0].kann("tool_calls"):
            return gewaehlt
    antwort = _antwort(discovery, HAUPTMODELL, werkzeuge=werkzeuge)
    if antwort:
        # A chosen model name stays: `runner:B` is a choice of B, and writing
        # the reported name over it would start A — the model the server
        # happens to have loaded, not the one that was asked for. Only for the
        # main server's own ids: a foreign id with a model part reached this
        # line by FAILING the tool check above, and handing it the run anyway
        # is the very case that check exists for.
        if gewaehlt and ist_hauptmodell(gewaehlt) and modellkennung.zerlegen(gewaehlt)[1]:
            return gewaehlt
        return antwort
    return rueckfall(discovery, slot_id=slot_id, werkzeuge=werkzeuge)


def slot_datei(repositories) -> str | None:
    """The model file the slot should be holding — or ``None`` when this
    field does not ask for a slot at all.

    The one place that answers "does anything need to be started?": the
    switch-on in the window and the autostart at program launch both read it,
    so neither can drift from the other.
    """
    stand = wahl(repositories)
    if stand.get("sorte") != SORTE_SLOT:
        return None
    return str(stand.get("wert") or "").strip() or None


def module_choice(repositories, datei: str) -> dict[str, str | None]:
    """What was last chosen for exactly this file — speed module, projector.

    ``None`` per entry means "never chosen", which is not the same as
    "chosen: none": the folder manifest's pairing and the name rule step in
    for the first and stay out for the second.
    """
    module = wahl(repositories).get("module")
    eintrag = module.get(datei) if isinstance(module, dict) else None
    if not isinstance(eintrag, dict):
        return {"drafter": None, "vision": None}
    return {
        "drafter": _modulname(eintrag.get("drafter")),
        "vision": _modulname(eintrag.get("vision")),
    }


def slot_startwerte(repositories, datei: str | None = None) -> dict[str, Any]:
    """HOW the slot runs — everything but the file itself.

    The one answer both start paths take: the switch-on in the window
    (app/api/v1/agentenserver.py) and the autostart at program launch
    (app/agentenserver.py). Neither may hold a value of its own, or the model
    window and the restart would start the same slot differently — which is
    precisely the failure this replaces.

    Read through ``wahl`` so a stored object that predates these keys gets
    the defaults merged in by the settings cascade rather than a ``None``
    that would travel to the command line as a missing flag.

    The two empties travel on as they are: ``None`` is "never chosen" and
    lets the runner take the folder manifest's pairing, ``""`` is "chosen:
    none" and stops it. Collapsing them here was the one place in this key
    where that difference did not reach the process — the same finding the
    main model server's key had (app/runnermodellwahl.py ``startwerte``), one
    page later.
    """
    stand = wahl(repositories)
    fein = stand.get("fein")
    # The file the modules belong to: the one being started, or — for the
    # start at program launch, which has no request — the one the field
    # names.
    modul = module_choice(repositories, datei or slot_datei(repositories) or "")
    return {
        "kontext": _zahl(
            stand.get("kontext"), KONTEXT_MIN, KONTEXT_MAX, KONTEXT_VORGABE
        ),
        # Nothing named stays nothing: the runner then sends no layer flag.
        "schichten": (
            None if stand.get("schichten") is None
            else _zahl(stand.get("schichten"), SCHICHTEN_MIN, SCHICHTEN_MAX, None)
        ),
        "port": (
            None if stand.get("port") in (None, "", 0)
            else _zahl(stand.get("port"), PORT_MIN, PORT_MAX, None)
        ),
        "drafter": modul["drafter"],
        "vision": modul["vision"],
        "fein": Feineinstellungen.aus_daten(fein if isinstance(fein, dict) else None),
    }


def remember_file(repositories, datei: str) -> None:
    """Records the file that was just started as the slot's chosen one — when
    the field already names a slot file.

    The window writes the choice the moment it is picked, which covers the
    page. This covers every other way a start happens — the command line
    above all, which used to start a file and leave the field naming the one
    before it, so the window said the wrong model about a server that was up.

    Only a field that names a slot file follows the file that runs. Starting
    the slot from outside is no decision about which model the unattended
    runs use: a field that names the main model or a cloud model keeps
    naming it, and the window then says what the runs really go to.
    Written key by key (``zusammenlegen``), never as a whole object: a start
    and a slider are two writers on one row.
    """
    stand = repositories.einstellungen.holen(GLOBAL, SCHLUESSEL)
    if not (isinstance(stand, dict) and stand.get("sorte") == SORTE_SLOT):
        return
    if stand.get("wert") == datei:
        return
    repositories.einstellungen.zusammenlegen(
        GLOBAL, SCHLUESSEL,
        {"sorte": SORTE_SLOT, "wert": datei[:WERT_HOECHSTLAENGE]},
    )


def vorladen_erlaubt(repositories) -> bool:
    """Whether the program may bring the slot up by itself at program start
    — the counterpart of ``runnermodellwahl.vorladen_erlaubt`` for the
    second server this program can hold (the same logic for
    both).

    Answers only for the BLIND autostart at program launch
    (app/agentenserver.py ``slot_starten_wenn_gewollt``, called without
    ``faellig``). A due cron entry that finds no model to run on wakes the
    slot regardless of this field: that call is the program reacting to a
    run that needs it NOW, not preloading ahead of one — the main model has
    no such moment to answer, because nothing brings IT up outside the
    preload in the first place.
    """
    return bool(wahl(repositories).get("vorladen", VORGABE["vorladen"]))
