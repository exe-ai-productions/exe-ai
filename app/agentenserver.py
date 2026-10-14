"""The agent model slot: the second model this program may load itself.

One of the four processes this program can hold, beside the chat model, the
picture generator and the embedding server. It exists so that agent and cron
runs can have a model of their own — small, loaded once, kept warm — without
occupying the chat model and without loading a second copy of it for every
firing.

It used to be the guardian's server, started only when Extended Workflow was
on, and it carried that job's rules: a tiny window, a model nobody else was
allowed to reach, and an endpoint deliberately kept out of every picker. All
three are gone. What is left is the mechanism, aimed at a new job:

  * How it runs is the user's answer now, not a number in this file. The
    guardian's 4096 first became the runner's own default, and a
    default is still a value nobody chose: an agent run reads files, calls
    tools and carries a history, and how much of that fits is not something
    this module can know. Window, layers, port, speed module, projector and
    the engine levers all come from the one field's setting
    (app/agentenmodellwahl.py) — the same key the model file comes from, so
    the window and the autostart cannot start the slot differently.
  * It registers with the discovery at start and unregisters at stop, exactly
    like the main runner (app/api/v1/runner.py). That is what lets the one
    field (app/agentenmodellwahl.py) hand its three kinds of answer — slot,
    main model, cloud — to the same ``discovery.aufloesen`` call, with no
    second resolution path anywhere.
  * A wanted consequence of that registration, and no longer a danger to
    guard against: the loaded model appears in the chat's model picker. A
    small model that is up is a model one can talk to.

It still hands out an endpoint as well as a runner, and for the reason it
always did: a server nobody has the address of is a server nobody asks.

Started when the field is switched to a slot model — and, unlike before, at
every program start while that field stands (app/main.py). The switched-on
field IS the consent; without the autostart every restart would be a silent
outage until somebody opened the model window.
"""

from __future__ import annotations

import logging

from app import agentenmodellwahl, runnerzustand
from app.config import EndpointConfig
from app.modellrunner import Modellrunner, RunnerFehler

log = logging.getLogger(__name__)

# Its own file, so a service restart can find and end an orphan of its own
# rather than mistaking the chat model's process for one.
# Both names still carry the slot's old spelling, and they stay that way on
# purpose: what stands here is not a name in the code but a handshake with a
# process. The file is how a restart finds an orphan a PREVIOUS version
# started, and the variable is how a server already running was handed its
# key. Renaming them would make exactly one start after an update miss the
# process it is supposed to end.
PID_DATEI = "eew-server.pid"
SCHLUESSEL_VARIABLE = "EXE_EEW_SCHLUESSEL"

# The port it answers on. Its own, because sharing one with the chat model is
# exactly what having a second server is for — and 8083 rather than the 8082
# it started out as: a chat model started by hand lands on 8082 often enough
# that the default collided with real setups on the first machine it met.
#
# There is deliberately NO search for a free port. A server that answers on a
# different port every session is a server nobody can look up, and the refusal
# the runner already gives ("that port is already taken") is the honest answer
# to a clash.
PORT_VORGABE = 8083

# What is chosen when nobody has chosen. Small enough that it may stay
# loaded, and the one file this slot has actually been measured on.
MODELL_VORGABE = "qwen2.5-coder-3b-instruct-q4_k_m.gguf"

# Nothing extra on the command line. The window is NOT set here: the runner
# writes `--ctx-size` itself from what it is started with, and adding a second
# one produced a command line carrying the flag twice. llama.cpp takes the
# last one and it happened to work — the kind of accident that holds until
# somebody reorders the list.
FLAGS = ()


# The id this server appears under wherever an endpoint is named — among the
# models, in the chat's picker, and as what the one field resolves for a slot
# choice. Fixed, so a restart on the same port replaces the entry instead of
# adding one.
ENDPUNKT_ID = "agentenmodell"


def endpunkt_bauen(port: int | None = None) -> EndpointConfig:
    """The endpoint this server answers on.

    Built here rather than written to the configuration, for the same reason
    the chat runner's is: the entry lives exactly as long as the server it
    describes.

    This is also what gets handed to ``discovery.anmelden`` at start, which is what makes the slot reachable by the ordinary id — by cron
    runs through the one field, and by anybody chatting with it. An earlier
    comment in this very place said it "must never show up in a model
    picker". That was true of the guardian, whose server was started for one
    private purpose; it is the opposite of true now.
    """
    return EndpointConfig(
        id=ENDPUNKT_ID,
        base_url=f"http://127.0.0.1:{port or PORT_VORGABE}/v1",
        provider="openai_compatible",
        parameter_dialect="llama_cpp",
        group="local",
        # The runner hands its server a fresh key at every start; requests
        # without it are turned away — the lock against web pages knocking on
        # localhost from inside the user's browser.
        api_key_env=SCHLUESSEL_VARIABLE,
    )


def runner_bauen(modellordner, programm: str | None, port: int | None = None) -> Modellrunner:
    """The slot's runner — the same class as the others, another kind."""
    return Modellrunner(
        modellordner,
        programm,
        port=port or PORT_VORGABE,
        pid_datei=PID_DATEI,
        schluessel_variable=SCHLUESSEL_VARIABLE,
        zusatzflags=FLAGS,
        # It samples and it is handed no tools: the sampling lore of the
        # model family applies, the tool template does not matter.
        sampling_flags=True,
        zustand_callback=runnerzustand.melder(runnerzustand.AGENT),
    )


async def slot_starten_wenn_gewollt(app, *, faellig: bool = False) -> bool:
    """Brings the slot process in line with the one field — start only.

    Called at program start (app/main.py) and again from the tick whenever a
    due entry finds nothing to run on (app/cronablauf.py). Both are the same
    question: the field asks for a slot model, so is it up? — except for one
    difference, which ``faellig`` carries: the program-start call is a BLIND
    autostart, brought up whether or not anything is about to use it, while
    the tick's call is the program reacting to a run that needs the slot
    RIGHT NOW.

    Only the first of those is gated by the slot's own preload switch
    (``agentenmodellwahl.vorladen_erlaubt`` — the counterpart of
    the main model's own switch, app/runnermodellwahl.py). Switched off,
    the field's consent to a slot model still stands, but the program no
    longer brings it up unasked at every launch; a due entry wakes it all
    the same, on ``faellig=True``, exactly as it always could — the entry
    that actually needs it is the one moment "off" does not answer for.

    **Start only, and no auto-stop.** A loaded slot stays loaded until the
    field points somewhere else, whether or not any entry currently needs it.
    The alternative — unload it when nothing is scheduled — makes the
    program's memory use depend on the calendar, and turns every firing into
    a cold start. Naming another model is what unloads it, and that is the
    window's job (app/api/v1/agentenserver.py), not this one's.

    The autostart itself is a deliberate break with the rule this module was
    written under ("nothing here starts by itself"). The chosen model file IS
    the consent: without the autostart every restart would be a
    silent outage until somebody opened the model window, which is exactly
    the kind of failure nobody attributes to the right cause.

    Returns whether the slot is up afterwards. ``False`` also for "the field
    does not ask for a slot at all" and for "switched off and not due" — the
    caller wants to know whether it has a slot to run on, and none of those
    is a case it treats any differently.
    """
    runner = getattr(app.state, "agentenrunner", None)
    if runner is None:
        return False
    datei = agentenmodellwahl.slot_datei(app.state.repositories)
    if datei is None:
        return False
    if runner.laeuft():
        return True
    if not faellig and not agentenmodellwahl.vorladen_erlaubt(app.state.repositories):
        return False
    try:
        # Started with what the user chose, not with defaults. The values come
        # from the same key the file name does (app/agentenmodellwahl.py), for
        # the one reason that decides this: at program start there is no
        # browser, so anything the window kept to itself would be gone by the
        # time this runs — and the slot would come up on numbers nobody picked.
        startwerte = agentenmodellwahl.slot_startwerte(app.state.repositories)
        lauf = runner.starten(datei, **startwerte)
    except RunnerFehler as fehler:
        # Not an error worth stopping anything for: the field stays as it is,
        # a due entry waits visibly, and the next tick tries again. The file
        # may simply not be there yet, or the port may still be held by a
        # server on its way down.
        log.warning(
            "Agent model '%s' not started (%s) — scheduled runs wait",
            datei, fehler,
            extra={"ereignis": "agentenmodell_start_fehlgeschlagen", "modell": datei},
        )
        return False
    # The port comes out of the start itself, not out of ``lauf()`` afterwards:
    # that one answers None for a process that has already died, and what used
    # to stand behind it was the slot's DEFAULT port — which registers a wrong
    # address whenever the start choice names another one. Behind the start's
    # own answer stands the port that was ASKED for.
    await app.state.discovery.anmelden(
        endpunkt_bauen(lauf.port if lauf else startwerte.get("port"))
    )
    # The window is named in the line, not only in the process table: the
    # autostart happens without anybody watching, and "which context did it
    # come up with?" is the first question asked when a run runs out of room.
    log.info(
        "Agent model '%s' started — port %s, context %s",
        datei, lauf.port if lauf else PORT_VORGABE,
        lauf.kontext if lauf else None,
        extra={"ereignis": "agentenmodell_gestartet", "modell": datei},
    )
    return True
