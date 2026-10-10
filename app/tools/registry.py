"""Tool registry — what is the model even allowed to touch?

The servers live in ``mcp_servers.json``. This file is the place where the
settings window will later hook in: enter, save, done.

The lockdown is the most important part of this file. Strictly:

  * Only servers from the file are started, and only those with ``enabled``.
  * If a server has ``allowed_tools``, exclusively those are offered —
    everything else the server can otherwise do stays out.
  * Tools under ``needs_confirmation`` are offered to the model but not
    simply executed: the streaming proxy stops and asks back. Without an
    explicit yes, nothing is executed.
  * What is not in the registry is not executed — even if the model asks
    for it.
  * What passes all of the above still goes through ``app/berechtigungen.py``
    (Tor 3) in ``ausfuehren`` — the same check by name here does not see the
    arguments, only whether THIS call, with these arguments, is approved.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from app import image_families
from app.agenten import GELOESCHT_DATEI, agenten_laden
from app.i18n import t
from app.paketierung import ist_eingefroren, programmpfad

if TYPE_CHECKING:
    # Type-only: the Literal itself lives in app.berechtigungen, which this
    # module cannot import at load time (see urteil()'s lazy import below).
    # A TYPE_CHECKING import never runs, so it carries no such cycle.
    from app.berechtigungen import Herkunft

# Which shipped servers the program can be itself. Same list as in
# start.py, and short on purpose: only what travels with the program.
MCP_SERVER = {"websuche", "searxng"}
import httpx

from app.tools import (
    bild_werkzeug, cron_notiz, cronjob, dateiwerkzeuge, frage_werkzeug, grenzen, memory,
    shell, skill, uhr, video_tool, ziel_werkzeug,
)
from app.tools import agentendock as ablage_werkzeug
from app.tools import auftrag_werkzeug
from app.tools.mcp_client import MCPFehler, MCPStdioClient, MCPWerkzeug
from app.tools.mcp_http import MCPHttpClient

log = logging.getLogger(__name__)

# Both variants speak the same language (starten, stoppen, werkzeuge,
# werkzeug_aufrufen) — the registry only distinguishes during setup.
MCPClient = MCPStdioClient | MCPHttpClient


class WerkzeugVerboten(Exception):
    """The model demanded a tool that is not approved.

    ``about_path`` says the refusal is about the PATH the call names — it
    lies outside the shared folders, or it is not there — rather than about
    the tool itself (switched off, not named, a rule against it). Only such
    a refusal is told where a moved folder went
    (app/api/v1/generierung.py, ``with_move_note``).
    """

    def __init__(self, *args: object, about_path: bool = False) -> None:
        super().__init__(*args)
        self.about_path = about_path




@dataclass
class ServerEintrag:
    name: str
    type: str = "stdio"
    command: str = ""
    args: list[str] = None  # type: ignore[assignment]
    env: dict[str, str] = None  # type: ignore[assignment]
    enabled: bool = True
    allowed_tools: list[str] | None = None
    needs_confirmation: list[str] = None  # type: ignore[assignment]
    # The HTTP kind: address of the hosted server …
    url: str | None = None
    # … and the name of the key in the .env (never the key itself) —
    # the same pattern as with the model and image endpoints. If missing,
    # OAuth is attempted (next build step).
    api_key_env: str | None = None

    def __post_init__(self) -> None:
        self.args = self.args or []
        self.env = self.env or {}
        self.needs_confirmation = self.needs_confirmation or []


def server_lesen(pfad: Path) -> list[ServerEintrag]:
    """Reads mcp_servers.json. If the file is missing, there are simply no tools."""
    if not pfad.exists():
        log.info("No MCP configuration under %s — no tools active", pfad)
        return []

    rohdaten = json.loads(pfad.read_text(encoding="utf-8"))
    eintraege = rohdaten.get("mcpServers") or {}
    return [
        ServerEintrag(name=name, **felder)
        for name, felder in eintraege.items()
    ]



# What an environment variable may be called. The name is written into the
# shared .env as `NAME=value`, one per line: a line break in it would write
# a second, foreign variable that every endpoint loads on the next start.
# A hyphen after the first character carries no such risk — python-dotenv
# reads an unquoted key with one — and entries named like `github-token`
# are already on file and have to stay readable and writable.
_UMGEBUNGSNAME = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")

# The fields of a server entry as the editor form (A6) checks them.
# Deliberately its own list instead of derived from the dataclass: `name` is
# a field there, but in the file it is the key.
_ERLAUBTE_FELDER = {
    "type", "command", "args", "env", "enabled",
    "allowed_tools", "needs_confirmation", "url", "api_key_env",
}


def konfiguration_pruefen(text: str, sprache: str) -> str | None:
    """Checks raw ``mcp_servers.json`` content for the editor form (A6).

    Returns the reason if the file is no good — otherwise ``None`` — in the
    language of the page that asked (``sprache``).
    Same approach as with the agent files: it is saved anyway, but the UI
    immediately says what needs fixing, and only what is valid gets applied
    (registry restart).
    """
    try:
        rohdaten = json.loads(text)
    except json.JSONDecodeError as fehler:
        return t("mcp_datei.json", sprache, fehler=fehler)
    if not isinstance(rohdaten, dict):
        return t("mcp_datei.oben", sprache)
    eintraege = rohdaten.get("mcpServers")
    if not isinstance(eintraege, dict):
        return t("mcp_datei.server_fehlen", sprache)

    for name, felder in eintraege.items():
        if not isinstance(felder, dict):
            return t("mcp_datei.eintrag", sprache, name=name)
        unbekannt = set(felder) - _ERLAUBTE_FELDER
        if unbekannt:
            return t(
                "mcp_datei.unbekannte_felder", sprache,
                name=name, felder=", ".join(sorted(unbekannt)),
            )
        typ = felder.get("type", "stdio")
        if not isinstance(typ, str):
            return t("mcp_datei.type_text", sprache, name=name)
        if typ not in ("stdio", "http"):
            # Honest instead of silent: what will never start counts as broken.
            return t("mcp_datei.type_unbekannt", sprache, name=name, typ=typ)
        if not isinstance(felder.get("command", ""), str):
            return t("mcp_datei.command_text", sprache, name=name)
        if not isinstance(felder.get("url", ""), str):
            return t("mcp_datei.url_text", sprache, name=name)
        umgebungsname = felder.get("api_key_env", "")
        if not isinstance(umgebungsname, str) or (
            umgebungsname and not _UMGEBUNGSNAME.fullmatch(umgebungsname)
        ):
            return t("mcp_datei.api_key_env", sprache, name=name)
        if typ == "http" and not felder.get("url"):
            return t("mcp_datei.http_url", sprache, name=name)
        args = felder.get("args", [])
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            return t("mcp_datei.args", sprache, name=name)
        env = felder.get("env", {})
        if not isinstance(env, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in env.items()
        ):
            return t("mcp_datei.env", sprache, name=name)
        if not isinstance(felder.get("enabled", True), bool):
            return t("mcp_datei.enabled", sprache, name=name)
        for listenfeld in ("allowed_tools", "needs_confirmation"):
            wert = felder.get(listenfeld)
            if wert is None:
                continue
            if not isinstance(wert, list) or not all(isinstance(w, str) for w in wert):
                return t("mcp_datei.namensliste", sprache, name=name, feld=listenfeld)
    return None


def program_tool_names() -> set[str]:
    """Every tool name this PROGRAM has, switches and servers aside.

    Not what a run is offered — that is ``namen()`` on an instance, and it
    leaves out what is switched off — but the names a person can mean when
    they write one into an agent file. Read by ``known_names()`` above for
    the job start: a name that exists here and is switched off is a
    configuration, not a mistake, and the run must not be refused over it.
    """
    return {
        ziel_werkzeug.WERKZEUG_NAME,
        uhr.WERKZEUG_NAME,
        shell.WERKZEUG_NAME,
        frage_werkzeug.WERKZEUG_NAME,
        *dateiwerkzeuge.NAMEN,
        memory.WERKZEUG_NAME,
        skill.LADEN,
        skill.SCHREIBEN,
        bild_werkzeug.WERKZEUG_NAME,
        video_tool.WERKZEUG_NAME,
        cronjob.WERKZEUG_NAME,
        cron_notiz.WERKZEUG_NAME,
        ablage_werkzeug.WERKZEUG_NAME,
        auftrag_werkzeug.WERKZEUG_NAME,
    }


@dataclass(frozen=True)
class EverOffered:
    """One of the tools every run is offered, whatever it brought itself.

    ``tool`` is the module that carries it — name, server and description
    all hang on that module. ``widened`` says whether a run that named its
    own tools has this one added to that list anyway: the clock is, in every
    run and every job (nothing else names a minute any more, so "in ten
    minutes" would be a guess without it, app/grundprompt.environment_block),
    the goal only where there is a goal to report — which only a schedule's
    run has (app/api/v1/auftraege.py).

    ``even_empty`` says whether that happens for a list written out as
    ``[]`` too. For the clock it does not: an empty list is somebody saying
    "none of them" on purpose, and widening it would turn the run into one
    that uses tools at all. For the goal it does — the entry IS the
    instruction to report, so a list that leaves the goal out cannot have
    meant "and never report this goal either".

    Read in the order they stand here: a run with ``[]`` and a goal to
    report gets the goal first and is no longer empty by the clock's turn,
    so the clock joins it too. That is the behaviour the tests pin; the
    order of these two lines is what decides it, not a rule above them.
    """

    tool: Any
    widened: bool = True
    even_empty: bool = False
    # What this tool is handed besides the model's own arguments, built from
    # the program's own state — the zone a schedule means, the table a
    # report speaks to. A tool that needs nothing leaves this out and is
    # called with the arguments alone.
    extra_arguments: Callable[[Any, dict], dict] | None = None
    # This tool's own way of saying "not like this" (``ZielVerboten`` in
    # app/tools/ziel_werkzeug.py), translated into the registry's single
    # refusal so a caller reads one kind of no. Empty for a tool that raises
    # none of its own.
    refusals: tuple[type[Exception], ...] = ()


# The tools every run is offered, in one list. Five places have to agree
# about them — the list the settings window switches things off by, the
# offer handed to the model, the mark the window paints, the tools window's
# own list and the widening of a run's own tool list — and kept apart they
# drift exactly where it hurts: a tool offered by one place and refused by
# the next, or one nobody can switch off.
EVER_OFFERED: tuple[EverOffered, ...] = (
    EverOffered(
        ziel_werkzeug,
        widened=False,
        even_empty=True,
        # Whether a report already went out belongs to the run, and the
        # schedule entry that fired it is the caller's — neither can come
        # from the model's arguments (see `ausfuehren` below).
        extra_arguments=lambda registry, state: {
            "schon_gemeldet": state["ziel_gemeldet"],
            "cronjobs_repo": registry.cronjobs_repo,
            "cronjob_id": state["cronjob_id"],
        },
        refusals=(ziel_werkzeug.ZielVerboten,),
    ),
    EverOffered(
        uhr,
        # The zone is a setting, never the model's own choice: a run that
        # could name its own would work out "in ten minutes" in a zone the
        # entry does not fire in.
        extra_arguments=lambda registry, state: {"zeitzone": registry.zeitzone},
    ),
)


class WerkzeugRegistry:
    """Holds the connections to all MCP servers and the tool list."""

    def __init__(
        self,
        eintraege: list[ServerEintrag],
        arbeitsverzeichnis: Path | None = None,
        oauth=None,
        shell_an: bool = False,
        memory_pfad: Path | None = None,
        skills_orte: tuple[Path, Path] | None = None,
        bild_zugang: tuple[str, Path, str] | None = None,
        video_ready: Callable[[], bool] | None = None,
        berechtigungen_pfad: Path | None = None,
        cronjobs_repo: Any | None = None,
        agenten_orte: tuple[Path, ...] | None = None,
        agentendock: Any | None = None,
        zeitzone: str | None = None,
        skripte_ordner: Any | None = None,
        folder_share: Any | None = None,
        chat_delivery: Any | None = None,
    ) -> None:
        self.eintraege = eintraege
        self.arbeitsverzeichnis = arbeitsverzeichnis
        # The shell tool is built in, not an MCP server (see app/tools/shell.py):
        # its working folders belong to the chat and change while the program
        # runs. It is offered like any other tool but travels a shorter path.
        self.shell_an = shell_an
        # Where the memory file lives. Built in for the same reason as the
        # shell tool: the path belongs to the program, and anything handed
        # over as an argument can be forged by the model. None means the
        # tool does not exist.
        self.memory_pfad = memory_pfad
        # The two skill folders, shipped and the user's, for the same reason
        # as the memory path. None means the two skill tools do not exist.
        self.skills_orte = skills_orte
        # This service's own API root, its picture folder, and this run's
        # session key, for the drawing tool. Built in like the
        # memory path: the address and the folder belong to the program,
        # never to a model's argument. None means the tool does not exist.
        self.bild_zugang = bild_zugang
        # Whether a video model is installed, asked each time: the video
        # tool exists only then, and a model can arrive while the service
        # runs. None means the tool does not exist.
        self.video_ready = video_ready
        # Where berechtigungen.json lives — resolved once from
        # config.app.berechtigungen_datei, the same way as memory_pfad above.
        # None means: fall back to the aufloesen()-based default (see
        # app/berechtigungsregeln.py), which is fine for a registry built
        # without a full Config (a handful of tests do exactly that).
        self.berechtigungen_pfad = berechtigungen_pfad
        # The cron table (app/db/repositories/cronjobs.py) and the agent
        # folders (shipped and the user's, like skills_orte), for the
        # cronjob tool. None means the tool does not exist — same convention
        # as memory_pfad and bild_zugang above.
        self.cronjobs_repo = cronjobs_repo
        self.agenten_orte = agenten_orte
        # The agent directory as last read, with the file stamps it was read
        # from (see `agentenverzeichnis`). Two tools name the agents and the
        # tool list is built several times per answer; re-parsing every
        # agent file each time was six directory walks per answer.
        self._agenten_signatur: tuple | None = None
        self._agenten_verzeichnis: Any = None
        # ``config.app.timezone`` — the zone a schedule means, the same one
        # the firing loop reads it in (app/wecker.py, app/terminplan.py).
        # The cronjob tool has to turn down a moment that has already gone
        # by, and "already gone by" is a question about that zone, not
        # about the server's. None means: the server's zone, which is what
        # an unset setting means everywhere else too.
        self.zeitzone = zeitzone
        # Where a cron entry's scripts live — a CALLABLE answering
        # "right now", not a path taken at startup. The folder is a named
        # storage location the user can move while the service runs
        # (app/speicherorte.py), and the firing loop resolves it fresh at
        # every firing; a path frozen here would have the tool check a new
        # entry against a folder nothing runs out of any more. None means
        # this service has no scripts folder, and script entries are refused.
        self.skripte_ordner = skripte_ordner
        # The agent dock (app/agentendock.py) — the shelf a job delivers
        # into. Built in like the memory path: the place belongs to the
        # program, never to a model's argument. None means the tool does
        # not exist.
        self.agentendock = agentendock
        # Keeps a delivery in a chat (app/dokumentablage.py,
        # ``deliver_to_chat``): a chat's own on the answer it is writing, a
        # job's in the chat the job was started from. None means a job's
        # delivery goes onto the dock and a chat is not offered the tool.
        self.chat_delivery = chat_delivery
        # Stores a folder `create_folder` made with the chat it was made for
        # (app/tools/create_folder.py, `ChatFolderShare`): called with the
        # chat's id and the folder, and it names the program's data folder,
        # where no working folder is made. The chat comes from here, never
        # from the model's arguments. None means the folder is shared with
        # the run only, which is what a job run gets anyway.
        self.folder_share = folder_share
        # The OAuthVermittler (mcp_auth) — for hosted servers without a
        # fixed key. None means: such servers remain unconnected.
        self.oauth = oauth
        self.clients: dict[str, MCPClient] = {}
        # Tool name -> (client, tool, needs confirmation)
        self._werkzeuge: dict[str, tuple[MCPClient, MCPWerkzeug, bool]] = {}
        # Switched off by the user (app/werkzeugwahl.py). Not part of the
        # setup: the pick lives in the server entry and is fixed while the
        # registry starts, while this one changes with a click and is handed
        # in fresh per run.
        self.abgeschaltet: set[str] = set()

    # --- Setup -----------------------------------------------------------

    async def starten(self) -> None:
        for eintrag in self.eintraege:
            if not eintrag.enabled:
                continue
            client = self._client_bauen(eintrag)
            if client is None:
                continue
            # Hosted servers without a fixed key run via the browser
            # sign-in: fetch access, silently renewed if needed.
            # Without access the server does not start — the tile shows
            # "reconnect", the model is offered nothing dead.
            if (
                isinstance(client, MCPHttpClient)
                and client.api_key is None
                and not eintrag.api_key_env
            ):
                if self.oauth is None:
                    log.info(
                        "MCP server '%s': no sign-in possible (no "
                        "broker) — skipped",
                        eintrag.name,
                    )
                    continue
                zugang = await self.oauth.gueltiges_token(eintrag.name)
                if zugang is None:
                    log.info(
                        "MCP server '%s': not connected — sign in through "
                        "the settings",
                        eintrag.name,
                    )
                    continue
                client.api_key = zugang
                client.token_erneuern = (
                    lambda name=eintrag.name: self.oauth.token_erneuern(name)
                )
            try:
                await client.starten()
            except (MCPFehler, OSError, asyncio.TimeoutError, httpx.HTTPError) as fehler:
                log.error("MCP server '%s' could not start: %s", eintrag.name, fehler)
                continue

            self.clients[eintrag.name] = client
            self._werkzeuge_uebernehmen(eintrag, client)

        log.info(
            "Tools ready: %d from %d MCP server(s)",
            len(self._werkzeuge),
            len(self.clients),
        )

    def _client_bauen(self, eintrag: ServerEintrag) -> MCPClient | None:
        """Builds the client matching the variant — or explains why not."""
        if eintrag.type == "stdio":
            # Packaged there is no interpreter to start a script with — the
            # program is its own tool server. The entry keeps saying what it
            # says, and the translation happens here, in the one place that
            # actually starts something.
            if ist_eingefroren() and eintrag.name in MCP_SERVER:
                befehl, argumente = str(programmpfad()), ["--mcp", eintrag.name]
            else:
                befehl, argumente = eintrag.command, eintrag.args

            return MCPStdioClient(
                name=eintrag.name,
                command=befehl,
                args=argumente,
                # ${NOTION_TOKEN} and co. are resolved here — the values
                # come from the environment (.env is loaded at service start
                # and before every registry restart). A missing value stays
                # as ${…} and the server fails visibly instead of running
                # silently with an empty secret.
                env={
                    schluessel: os.path.expandvars(wert)
                    for schluessel, wert in eintrag.env.items()
                },
                arbeitsverzeichnis=str(self.arbeitsverzeichnis) if self.arbeitsverzeichnis else None,
            )

        if eintrag.type == "http":
            if not eintrag.url:
                log.error(
                    "MCP server '%s': type 'http' without 'url' — skipped",
                    eintrag.name,
                )
                return None
            schluessel = None
            if eintrag.api_key_env:
                schluessel = os.environ.get(eintrag.api_key_env) or None
                if schluessel is None:
                    # House rule: the model is offered nothing that is sure
                    # to fail. Without a key the server doesn't even start —
                    # the editor form shows the missing name as a red light.
                    log.error(
                        "MCP server '%s': key '%s' is not set (.env) "
                        "— skipped",
                        eintrag.name,
                        eintrag.api_key_env,
                    )
                    return None
            # Without api_key_env, the connection is made unauthenticated —
            # servers that demand OAuth visibly reject that with a 401 until
            # the sign-in flow (next build step) is in place.
            return MCPHttpClient(name=eintrag.name, url=eintrag.url, api_key=schluessel)

        log.warning(
            "MCP server '%s' has type '%s' — there is 'stdio' and 'http', "
            "skipped",
            eintrag.name,
            eintrag.type,
        )
        return None

    def _werkzeuge_uebernehmen(self, eintrag: ServerEintrag, client: MCPClient) -> None:
        for werkzeug in client.werkzeuge:
            if eintrag.allowed_tools is not None:
                if werkzeug.name not in eintrag.allowed_tools:
                    log.info(
                        "Tool '%s' of '%s' is not released and is not offered",
                        werkzeug.name,
                        eintrag.name,
                    )
                    continue
            # The video tool comes and goes with the model folder while
            # this registry lives, so its name is kept free from the start:
            # a server's tool of that name taken over today would stand
            # beside the built-in one the day a video model arrives.
            if werkzeug.name in self.builtin_names() or (
                werkzeug.name == video_tool.WERKZEUG_NAME
                and self.bild_zugang is not None and self.video_ready is not None
            ):
                log.warning(
                    "Tool name '%s' belongs to a built-in tool of this run — the "
                    "entry of '%s' is skipped. Otherwise the name would stand twice in the "
                    "offer (strict OpenAI servers answer that with 400), and only the built-in "
                    "one would be reachable anyway.",
                    werkzeug.name,
                    eintrag.name,
                )
                continue
            if werkzeug.name in self._werkzeuge:
                log.warning(
                    "Tool name '%s' is given twice — the entry of '%s' wins",
                    werkzeug.name,
                    self._werkzeuge[werkzeug.name][1].server,
                )
                continue
            self._werkzeuge[werkzeug.name] = (
                client,
                werkzeug,
                werkzeug.name in eintrag.needs_confirmation,
            )

    async def stoppen(self) -> None:
        for client in self.clients.values():
            await client.stoppen()
        self.clients.clear()
        self._werkzeuge.clear()

    # --- Usage -----------------------------------------------------------

    @property
    def anzahl(self) -> int:
        # The always-offered ones come from their table, not from a number
        # written here: a third entry there would otherwise be offered and
        # never counted.
        return len(self._werkzeuge) + (
            len(EVER_OFFERED) + len(dateiwerkzeuge.NAMEN) if self.shell_an else 0
        )

    def namen(self) -> list[str]:
        # The goal tool depends on nothing and is therefore listed
        # unconditionally: reporting a reached goal needs no folder, no
        # file and no table, and a run that cannot report one is a run
        # whose finish nobody hears. It is switched off like every other
        # tool, through `abgeschaltet`.
        #
        # The clock is listed by the same argument and for a sharper reason:
        # it is now the ONLY place a run can learn what the time is (the
        # sentence at the front of the user turn is a date, not a minute,
        # app/grundprompt.environment_block). Missing from a run's offer, a
        # scheduled run could not work out "in ten minutes" at all.
        return sorted([*self._werkzeuge, *self.builtin_names()])

    def builtin_names(self) -> list[str]:
        """The built-in tools THIS registry offers, given what is switched on.

        One place, read twice: this is the list the settings window switches
        things off by, and it is also the list a server's tool is measured
        against when it is taken over — a name is only ever skipped where a
        built-in of that name is really in the offer. A second, hand-kept
        copy would drift, and the two readings would part company exactly
        where it hurts: a name blocked although nothing carries it (the
        server's tool vanishes) or offered twice (strict OpenAI-compatible
        servers answer that with 400).
        """
        namen = [e.tool.WERKZEUG_NAME for e in EVER_OFFERED]
        if self.shell_an:
            namen += [
                shell.WERKZEUG_NAME, frage_werkzeug.WERKZEUG_NAME,
                *dateiwerkzeuge.NAMEN,
            ]
        if self.bild_zugang is not None:
            namen.append(bild_werkzeug.WERKZEUG_NAME)
        if self._video_on():
            namen.append(video_tool.WERKZEUG_NAME)
        if self.cronjobs_repo is not None:
            namen.append(cronjob.WERKZEUG_NAME)
            # Listed although only a cron-fired run is ever offered it:
            #this is the list the settings window switches
            # things off by, and a tool nobody can switch off would be the
            # one exception to a rule the whole tools window rests on.
            namen.append(cron_notiz.WERKZEUG_NAME)
        if self.agentendock is not None:
            namen.append(ablage_werkzeug.WERKZEUG_NAME)
        if self.agenten_orte is not None:
            namen.append(auftrag_werkzeug.WERKZEUG_NAME)
        if self.memory_pfad is not None:
            namen.append(memory.WERKZEUG_NAME)
        if self.skills_orte is not None:
            namen.append(skill.LADEN)
            namen.append(skill.SCHREIBEN)
        return namen

    def known_names(self) -> set[str] | None:
        """Every tool name this run could resolve — or ``None`` for "open".

        What a run may be OFFERED is ``namen()``: the built-ins given what is
        switched on, plus the tools of the servers that are really connected.
        This is the wider question "could this name mean anything here at
        all", asked by the job start before it refuses a run whose agent
        named something (app/api/v1/auftraege.py). Two things make it wider
        than the offer, and both are about not crying wolf:

        * A built-in that is merely SWITCHED OFF is still a name of this
          program (the file tools with the shell off, say), never a typo.
        * A server entry that declares no ``allowed_tools`` may carry any
          tool it likes, so no name can be judged while one of those is
          configured — the answer is ``None``, "open", and nothing is
          refused.

        A server that declares its tools contributes them whether it is
        connected or not: set up is set up, and a name from there is a name
        somebody configured. Whether the tool can run is a different
        question, answered at the call.
        """
        namen = set(self.namen()) | program_tool_names()
        for eintrag in self.eintraege:
            if not eintrag.allowed_tools:
                return None
            namen.update(eintrag.allowed_tools)
        return namen

    def uebersicht(self, shell_zeitgrenze: int | None = None) -> list[dict[str, Any]]:
        """The tools window's list, description text and all.

        ``shell_zeitgrenze`` is the resolved cascade value
        (``app/befehlszeitwahl.py``), named by the caller — this method has
        no chat or model to resolve one from itself. Left at ``None`` it
        falls back to the shipped default, same as ``werkzeug_beschreibung``
        does on its own.
        """
        # ``builtin`` says where a tool comes from, not what it is called: a
        # server that happens to be named like a built-in one (a server
        # called "clock", say) must not be able to push the built-in row out
        # of the window, and the window may not have to guess by name. Read
        # by frontend/src/lib/werkzeuge.svelte.js.
        eintraege = [
            {
                "name": name,
                "beschreibung": werkzeug.beschreibung,
                "server": werkzeug.server,
                "needs_confirmation": bestaetigung,
                "builtin": False,
            }
            for name, (_, werkzeug, bestaetigung) in self._werkzeuge.items()
        ]
        # The tools every run is offered (EVER_OFFERED above). Neither of
        # them touches anything of the user's: one announces a text, the
        # other reads the clock and hands the reading back. The clock is
        # named in READS_ONLY (app/berechtigungen.py) and therefore never
        # asks; the goal tool is not, so its question is answered by the
        # mode like every other tool's. Visible and switchable in the
        # settings window is their safety net, the same philosophy as
        # memory's.
        for e in EVER_OFFERED:
            beschreibung = e.tool.werkzeug_beschreibung()
            eintraege.append(
                {
                    "name": beschreibung.name,
                    "beschreibung": beschreibung.beschreibung,
                    "server": beschreibung.server,
                    "needs_confirmation": False,
                }
            )
        if self.memory_pfad is not None:
            beschreibung = memory.werkzeug_beschreibung()
            eintraege.append(
                {
                    "name": beschreibung.name,
                    "beschreibung": beschreibung.beschreibung,
                    "server": beschreibung.server,
                    "needs_confirmation": False,
                }
            )
        if self.skills_orte is not None:
            for beschreibung in skill.werkzeug_beschreibungen():
                eintraege.append(
                    {
                        "name": beschreibung.name,
                        "beschreibung": beschreibung.beschreibung,
                        "server": beschreibung.server,
                        "needs_confirmation": False,
                    }
                )
        if self.bild_zugang is not None:
            # No chat and no window here: the settings window lists what
            # the tool CAN be, not what one chat's window makes of it.
            beschreibung = bild_werkzeug.werkzeug_beschreibung()
            eintraege.append(
                {
                    "name": beschreibung.name,
                    "beschreibung": beschreibung.beschreibung,
                    "server": beschreibung.server,
                    # Draws locally into the program's own folders — nothing
                    # leaves the machine and nothing of the user's is touched.
                    "needs_confirmation": False,
                }
            )
        if self._video_on():
            beschreibung = video_tool.werkzeug_beschreibung()
            eintraege.append(
                {
                    "name": beschreibung.name,
                    "beschreibung": beschreibung.beschreibung,
                    "server": beschreibung.server,
                    "needs_confirmation": False,
                }
            )
        if self.cronjobs_repo is not None:
            # The agent names travel into the schema, so the caller can read
            # off which ones exist instead of guessing one and being refused
            # with nothing but its own word back. From disk, like everywhere
            # else here — a list held in memory is wrong the moment a file is
            # added. Where there are no agent folders at all the field simply
            # carries no list.
            beschreibung = cronjob.werkzeug_beschreibung(
                self.agentenverzeichnis() if self.agenten_orte else None
            )
            eintraege.append(
                {
                    "name": beschreibung.name,
                    "beschreibung": beschreibung.beschreibung,
                    "server": beschreibung.server,
                    # Visible and switchable in the settings window is the
                    # safety net here, the same
                    # philosophy as memory's — not an interrupting prompt.
                    "needs_confirmation": False,
                }
            )
            beschreibung = cron_notiz.werkzeug_beschreibung()
            eintraege.append(
                {
                    "name": beschreibung.name,
                    "beschreibung": beschreibung.beschreibung,
                    "server": beschreibung.server,
                    # Writes one text field on one schedule row, and only on
                    # the row whose own run is calling — nothing of the
                    # user's is touched, same philosophy as the drawing
                    # tool's.
                    "needs_confirmation": False,
                }
            )
        if self.agentendock is not None:
            beschreibung = ablage_werkzeug.werkzeug_beschreibung()
            eintraege.append(
                {
                    "name": beschreibung.name,
                    "beschreibung": beschreibung.beschreibung,
                    "server": beschreibung.server,
                    # Writes only into the program's own data folder —
                    # nothing of the user's is touched, same philosophy as
                    # the drawing tool's.
                    "needs_confirmation": False,
                }
            )
        if self.agenten_orte is not None:
            beschreibung = auftrag_werkzeug.werkzeug_beschreibung(
                self.agentenverzeichnis(), helpers=True
            )
            eintraege.append(
                {
                    "name": beschreibung.name,
                    "beschreibung": beschreibung.beschreibung,
                    "server": beschreibung.server,
                    # The confirmation IS the editable task window the chat
                    # shows before anything starts — nothing runs without it.
                    "needs_confirmation": True,
                }
            )
        if self.shell_an:
            beschreibung = shell.werkzeug_beschreibung(shell_zeitgrenze)
            eintraege.append(
                {
                    "name": beschreibung.name,
                    "beschreibung": beschreibung.beschreibung,
                    "server": beschreibung.server,
                    # Not a fixed yes or no: it depends on where the command
                    # reaches. The overview can only say "sometimes", and
                    # says it as "yes" so nobody reads it as unguarded.
                    "needs_confirmation": True,
                }
            )
            for beschreibung in dateiwerkzeuge.beschreibungen():
                eintraege.append(
                    {
                        "name": beschreibung.name,
                        "beschreibung": beschreibung.beschreibung,
                        "server": beschreibung.server,
                        # Same "sometimes" as the shell: it depends on where
                        # the path reaches.
                        "needs_confirmation": True,
                    }
                )
            beschreibung = frage_werkzeug.werkzeug_beschreibung()
            eintraege.append(
                {
                    "name": beschreibung.name,
                    "beschreibung": beschreibung.beschreibung,
                    "server": beschreibung.server,
                    # It IS the question — there is nothing to confirm first.
                    "needs_confirmation": False,
                }
            )
        # Marked in ONE place, and as a default: every entry above is a
        # built-in of this program — only the tools of a server say
        # otherwise, and they say it themselves. A new row added here is
        # therefore a built-in without anyone having to remember it.
        for eintrag in eintraege:
            eintrag.setdefault("builtin", True)
        return sorted(eintraege, key=lambda e: e["name"])

    def agentenverzeichnis(self) -> Any:
        """The agents on disk — re-read only when a file among them changed.

        From disk, like everywhere else here: a list held in memory is wrong
        the moment a file is added. But parsed again only when the folders
        say so — the names, stamps and sizes of the agent files are read on
        every call (a handful of stat calls), the files themselves only when
        that reading differs from the last one. ``None`` where there are no
        agent folders at all, the same convention as ``agenten_orte``.
        """
        if self.agenten_orte is None:
            return None
        stempel: list[tuple[str, int, int]] = []
        for ort in self.agenten_orte:
            try:
                for datei in sorted(ort.glob("*.md")):
                    stand = datei.stat()
                    stempel.append((str(datei), stand.st_mtime_ns, stand.st_size))
                # The deletion notes silence a SHIPPED agent without touching
                # a single .md (app/agenten.py, `loeschung_merken`). Unstamped,
                # a deleted agent stayed on offer for the life of the process.
                notiz = ort / GELOESCHT_DATEI
                if notiz.is_file():
                    vermerk = notiz.stat()
                    stempel.append((str(notiz), vermerk.st_mtime_ns, vermerk.st_size))
            except OSError:
                # A folder that cannot be read right now: stamped with the
                # moment, so this reading never matches the next one and the
                # directory is read again rather than trusted stale for good.
                stempel.append((str(ort), time.monotonic_ns(), -1))
        signatur = tuple(stempel)
        if self._agenten_verzeichnis is None or signatur != self._agenten_signatur:
            self._agenten_verzeichnis = agenten_laden(*self.agenten_orte)
            self._agenten_signatur = signatur
        return self._agenten_verzeichnis

    def als_openai_werkzeuge(
        self, nur: set[str] | None = None,
        shell_zeitgrenze: int | None = None,
        cron_notiz_an: bool = False,
        for_job: bool = False,
        helpers: bool = True,
        bild_fenster: Any | None = None,
        memory_shown: bool = True,
    ) -> list[dict[str, Any]]:
        """The tool list in the form that goes to the model.

        ``nur`` is an agent's allowlist (6.3): what is offered is the
        intersection of it and what the server approves — the registry
        remains the outer boundary. ``None`` means as before: everything
        approved.

        A run whose cron entry carries a ``ziel`` reaches this with ``goal``
        already in ``nur`` (app/api/v1/auftraege.py):
        the entry's goal is added to the run's own allowlist, once, rather
        than being waved through here — this list and the execution gate
        (app/berechtigungen.py) both read that one list, and an exception
        made only here would be offered and then refused.

        ``cron_notiz_an`` is whether this run was started by a schedule.
       Off by default, and that default is the point: the note
        tool belongs to one cron entry, and outside such a run there is no
        entry for it to write to. Offering it in a chat would be an offer
        that cannot be taken — asked for the other way round (a filter after
        the fact, striking the tool out of a list once it is already built) a
        forgotten caller would leak it into every chat instead of into none.

        ``for_job`` tells a job's list from a chat's, for the tools that
        hand something over. ``deliver_file`` is in both, wherever its place
        exists — a job's file goes to the doc folder (the agent dock, or the
        chat the job was started from), a chat's hangs on the answer being
        written (app/tools/agentendock.py) — and its description names the
        place that holds for this list. ``draw_image`` and ``draw_video``
        read it the same way: a job has no answer for a picture to hang on,
        so its picture stays in the pictures folder, and the description
        says so instead of promising it in the answer.

        ``memory_shown`` is whether the memory travels to the model this list
        goes to (app/gedaechtnis.py ``mitschicken``). ``memory_save``'s
        description promises only what holds on that side
        (app/tools/memory.py).

        ``helpers`` is whether ``start_job`` may start a helper without an
        agent (app/helper.py). A chat's list may; the one place a job's list
        is built says it may not.

        ``shell_zeitgrenze`` is the command time limit that applies to this
        run (app/befehlszeitwahl.py) — the shell's description names it, and
        it must name the value that actually holds, not the shipped default.
        ``None`` keeps the default sentence.

        What the user switched off never appears, no matter who asks. A tool
        the model cannot see is one it cannot call, which is the cheapest
        enforcement there is.
        """
        agenten = self.agentenverzeichnis

        liste = [
            werkzeug.als_openai_werkzeug()
            for name, (_, werkzeug, _) in self._werkzeuge.items()
            if (nur is None or name in nur) and name not in self.abgeschaltet
        ]
        if (
            self.shell_an
            and (nur is None or shell.WERKZEUG_NAME in nur)
            and shell.WERKZEUG_NAME not in self.abgeschaltet
        ):
            liste.append(
                shell.werkzeug_beschreibung(shell_zeitgrenze).als_openai_werkzeug()
            )
        if self.shell_an:
            liste += [
                b.als_openai_werkzeug()
                for b in dateiwerkzeuge.beschreibungen()
                if (nur is None or b.name in nur) and b.name not in self.abgeschaltet
            ]
        if (
            self.shell_an
            and (nur is None or frage_werkzeug.WERKZEUG_NAME in nur)
            and frage_werkzeug.WERKZEUG_NAME not in self.abgeschaltet
        ):
            liste.append(frage_werkzeug.werkzeug_beschreibung().als_openai_werkzeug())
        # The tools every run is offered (EVER_OFFERED above), under the same
        # filter as everything else: a run that names its own tools gets the
        # widened ones added to that list before it arrives here
        # (app/api/v1/auftraege.py) — one place widens the list, all three
        # gates of the call read the widened one.
        for e in EVER_OFFERED:
            if (nur is None or e.tool.WERKZEUG_NAME in nur) and (
                e.tool.WERKZEUG_NAME not in self.abgeschaltet
            ):
                liste.append(e.tool.werkzeug_beschreibung().als_openai_werkzeug())
        if (
            self.memory_pfad is not None
            and (nur is None or memory.WERKZEUG_NAME in nur)
            and memory.WERKZEUG_NAME not in self.abgeschaltet
        ):
            liste.append(
                memory.werkzeug_beschreibung(memory_shown).als_openai_werkzeug()
            )
        if self.skills_orte is not None:
            liste += [
                b.als_openai_werkzeug()
                for b in skill.werkzeug_beschreibungen()
                if (nur is None or b.name in nur) and b.name not in self.abgeschaltet
            ]
        if (
            self.bild_zugang is not None
            and (nur is None or bild_werkzeug.WERKZEUG_NAME in nur)
            and bild_werkzeug.WERKZEUG_NAME not in self.abgeschaltet
        ):
            # Where the image model comes from: a CALLABLE, so it is read
            # only when the tool is really being offered — a chat whose draw
            # tool is switched off (or that an agent's allowlist leaves out)
            # must not pay a folder scan for a sentence it never sends. The
            # value is `bild_werkzeug.FensterBild`: the family the drawing
            # will use, and the values the next picture is drawn with.
            fenster = None
            if self.bild_zugang is not None and bild_fenster is not None:
                fenster = bild_fenster() if callable(bild_fenster) else bild_fenster
            familie = getattr(fenster, "familie", None)
            # Offered only where the window really draws from text. Stands it
            # at a family that cannot (editing, video), this run is not
            # offered the tool at all: a tool that is sure to fail is one the
            # model should never see, and a description that has to say "this
            # does nothing" is a promise the tool cannot keep, sent in every
            # request of that run.
            #
            # The same question is asked once more where the drawing happens
            # (app/tools/bild_werkzeug.py, `ausfuehren`): this reading is of
            # the window as it stood when the offer was made, and a run
            # outlives that — the user can turn the window around while an
            # answer is still going. An offer made from an older window is
            # then a call that has to be answered in words instead of drawn,
            # or a video comes back in a picture's place.
            if image_families.draws_from_text(familie):
                beschreibung = bild_werkzeug.werkzeug_beschreibung(
                    familie, in_chat=not for_job,
                    values=getattr(fenster, "values", None),
                )
                liste.append(beschreibung.als_openai_werkzeug())
        if (
            (nur is None or video_tool.WERKZEUG_NAME in nur)
            and video_tool.WERKZEUG_NAME not in self.abgeschaltet
            # Asked last: only a run that may have the tool pays the look
            # into the model folder.
            and self._video_on()
        ):
            liste.append(
                video_tool.werkzeug_beschreibung(in_chat=not for_job).als_openai_werkzeug()
            )
        if (
            self.cronjobs_repo is not None
            and (nur is None or cronjob.WERKZEUG_NAME in nur)
            and cronjob.WERKZEUG_NAME not in self.abgeschaltet
        ):
            # With the agent names, same as the settings-window path above:
            # built without them, the enum and the "Available" sentence were
            # made for the window and never reached the model — the one
            # caller that has to pick a name blind.
            liste.append(
                cronjob.werkzeug_beschreibung(
                    agenten() if self.agenten_orte else None
                ).als_openai_werkzeug()
            )
        if (
            cron_notiz_an
            and self.cronjobs_repo is not None
            and (nur is None or cron_notiz.WERKZEUG_NAME in nur)
            and cron_notiz.WERKZEUG_NAME not in self.abgeschaltet
        ):
            liste.append(cron_notiz.werkzeug_beschreibung().als_openai_werkzeug())
        if (
            self._delivery_place(for_job)
            and (nur is None or ablage_werkzeug.WERKZEUG_NAME in nur)
            and ablage_werkzeug.WERKZEUG_NAME not in self.abgeschaltet
        ):
            liste.append(
                ablage_werkzeug.werkzeug_beschreibung(in_chat=not for_job).als_openai_werkzeug()
            )
        if (
            self.agenten_orte is not None
            and (nur is None or auftrag_werkzeug.WERKZEUG_NAME in nur)
            and auftrag_werkzeug.WERKZEUG_NAME not in self.abgeschaltet
        ):
            liste.append(
                auftrag_werkzeug.werkzeug_beschreibung(
                    agenten(), helpers=helpers
                ).als_openai_werkzeug()
            )
        return liste

    def server_von(self, name: str) -> str:
        """Which server offers this tool. Empty if it is unknown.

        The UI picks the tool's mark by this: the server name is fixed in
        mcp_servers.json and cannot be guessed wrong, while a tool name can
        be anything the server feels like.
        """
        if (
            name == shell.WERKZEUG_NAME
            or name == frage_werkzeug.WERKZEUG_NAME
            or name in dateiwerkzeuge.NAMEN
        ):
            return shell.SERVER_NAME if self.shell_an else ""
        for e in EVER_OFFERED:
            if name == e.tool.WERKZEUG_NAME:
                return e.tool.SERVER_NAME
        if name == memory.WERKZEUG_NAME:
            return memory.SERVER_NAME if self.memory_pfad is not None else ""
        if name in (skill.LADEN, skill.SCHREIBEN):
            return skill.SERVER_NAME if self.skills_orte is not None else ""
        if name == bild_werkzeug.WERKZEUG_NAME:
            return bild_werkzeug.SERVER_NAME if self.bild_zugang is not None else ""
        if name == video_tool.WERKZEUG_NAME:
            return video_tool.SERVER_NAME if self._video_on() else ""
        if name == cronjob.WERKZEUG_NAME:
            return cronjob.SERVER_NAME if self.cronjobs_repo is not None else ""
        if name == cron_notiz.WERKZEUG_NAME:
            return cron_notiz.SERVER_NAME if self.cronjobs_repo is not None else ""
        if name == auftrag_werkzeug.WERKZEUG_NAME:
            return auftrag_werkzeug.SERVER_NAME if self.agenten_orte is not None else ""
        eintrag = self._werkzeuge.get(name)
        return eintrag[1].server if eintrag else ""

    def bestaetigungsgrund(
        self, name: str, argumente: dict[str, Any] | None = None,
        ordner: list[str] | None = None,
    ) -> tuple[str, str, str] | None:
        """What makes THIS call need a confirmation, as (text key, field, value).

        The sentence belongs to the tool, not to whoever asks. Handing back a
        bare string meant the caller had to pick a sentence for all of them,
        and it picked the shell's: a memory rule was announced as "Reaches
        <the rule> — outside the shared folders".

        Only the shell and file tools have a dynamic reason: the path a call
        reaches outside the shared folders. MCP tools are confirmed because
        the configuration says so, which is not something the prompt has to
        explain again.

        A shell/file call can still land on "fragen" with its path INSIDE
        the shared folders — Restricted mode asks even there, and an
        operator's own per-tool rule can too (``app/berechtigungen.py``).
        The caller only reaches this once ``braucht_bestaetigung`` is
        already true, so a missing dynamic reason here means "ask anyway",
        never "do not ask" — the generic sentence below, not ``None``.
        """
        if name == shell.WERKZEUG_NAME:
            grund = shell.aussenpfad(argumente or {}, ordner or []) or ""
            # The shell has two reasons, not one: a folder outside, or an
            # address on the net. It picks; anything it cannot place comes
            # back as the folder sentence.
            schluessel = shell.grundschluessel(argumente or {}, ordner or [])
        elif name in dateiwerkzeuge.NAMEN:
            grund = dateiwerkzeuge.aussenpfad(name, argumente or {}, ordner or []) or ""
            schluessel = shell.GRUND_SCHLUESSEL
        else:
            return None
        if grund:
            return (schluessel, shell.GRUND_PLATZHALTER, grund)
        return ("werkzeug.grund_bestaetigung", shell.GRUND_PLATZHALTER, "")

    def urteil(
        self, name: str, argumente: dict[str, Any] | None = None,
        ordner: list[str] | None = None, herkunft: "Herkunft" = "chat",
        agent: Any | None = None, rules_of: "Herkunft | None" = None,
    ):
        """Tor 3 — ``ja`` / ``fragen`` / ``nein`` for THIS call.

        ``rules_of``: whose mode and rules judge it, where not ``herkunft``'s
        own (``app/berechtigungen.py``, ``urteil``).

        The single decision spot (see ``app/berechtigungen.py``):
        ``braucht_bestaetigung`` and ``ausfuehren`` both go through here, so
        there is one place that reads ``berechtigungen.json``, not two
        judging side by side. Imported lazily — ``app.berechtigungen``
        imports the shell/file-tool modules, which this module also imports,
        and doing that at module load time would be a straight import cycle.
        """
        from app import berechtigungen
        from app.berechtigungsregeln import laden as regeln_laden

        eintrag = self._werkzeuge.get(name)
        return berechtigungen.urteil(
            name, argumente or {}, ordner or [], herkunft, agent,
            regeln=regeln_laden(self.berechtigungen_pfad),
            statisch_bestaetigen=bool(eintrag and eintrag[2]),
            rules_of=rules_of,
        )

    def braucht_bestaetigung(
        self, name: str, argumente: dict[str, Any] | None = None,
        ordner: list[str] | None = None,
    ) -> bool:
        """Whether this call has to be confirmed by the user.

        Only ``fragen`` needs the prompt above the input field. A ``nein``
        is not asked about at all — ``ausfuehren`` refuses it outright and
        explains why, which is the correct answer for something that was
        never going to be allowed.

        ``ask_user`` is never asked about: it is the question itself, the
        person answers it, and a permission box in front of it would put a
        second prompt before the one that was meant. It is no action on the
        machine either — what the person answers is its whole result.
        """
        if name == frage_werkzeug.WERKZEUG_NAME:
            return False
        return self.urteil(name, argumente, ordner).antwort == "fragen"

    def _merkmal_abgeschaltet(self, name: str) -> bool:
        """Whether this tool's own feature switch is off.

        Checked before Tor 3 so a disabled feature reports its own plain
        reason — Tor 3's judgment (a path outside the shared folders, say)
        can otherwise read as advice to fix something that would not help,
        since the feature itself is what is missing.
        """
        if name == memory.WERKZEUG_NAME:
            return self.memory_pfad is None
        if name in (skill.LADEN, skill.SCHREIBEN):
            return self.skills_orte is None
        if name == bild_werkzeug.WERKZEUG_NAME:
            return self.bild_zugang is None
        if name == video_tool.WERKZEUG_NAME:
            return not self._video_on()
        if name in (cronjob.WERKZEUG_NAME, cron_notiz.WERKZEUG_NAME):
            return self.cronjobs_repo is None
        if name == ablage_werkzeug.WERKZEUG_NAME:
            return self.agentendock is None
        if name == auftrag_werkzeug.WERKZEUG_NAME:
            return self.agenten_orte is None
        if name == shell.WERKZEUG_NAME or dateiwerkzeuge.modul(name) is not None:
            return not self.shell_an
        return False

    def _delivery_place(self, for_job: bool) -> bool:
        """Whether ``deliver_file`` has somewhere to put a file for this
        kind of run: the shelf for a job, a chat to keep it in for a chat.
        The shelf is the feature's own switch (``_merkmal_abgeschaltet``),
        so a service without it offers the tool to nobody."""
        if self.agentendock is None:
            return False
        return for_job or self.chat_delivery is not None

    def _deliver_with(self, herkunft: "Herkunft", agent: Any | None) -> str | None:
        """The tool a drawn picture is handed on with, where THIS run has it.

        Only a job is told to: a chat's picture joins its answer by itself.
        And only while the shelf exists, the tool is on and the agent's own
        list does not leave it out — the three things that decide whether a
        job is offered ``deliver_file`` (``als_openai_werkzeuge``). A run
        without it is not told to call it.
        """
        name = ablage_werkzeug.WERKZEUG_NAME
        if herkunft != "agent" or self.agentendock is None or name in self.abgeschaltet:
            return None
        named = getattr(agent, "werkzeuge", None)
        if named is not None and name not in named:
            return None
        return name

    def _video_on(self) -> bool:
        """Whether the video tool exists right now: the picture service is
        reachable for the program's own tools and a video model is
        installed."""
        return (
            self.bild_zugang is not None
            and self.video_ready is not None
            and bool(self.video_ready())
        )

    def _input_picture(self, named: Any, ordner: list[str] | None) -> Path | None:
        """The picture a drawing tool was told to draw from, as a file this
        run may read: inside one of its folders, the pictures folder among
        them. Anything else is refused the way a file to hand on is — a
        drawing has no way to ask."""
        path = str(named or "").strip()
        if not path:
            return None
        folders = list(ordner or [])
        try:
            target = grenzen.ziel(path, folders, getattr(self.folder_share, "data_dir", None))
        except grenzen.GrenzeVerletzt as error:
            raise WerkzeugVerboten(str(error)) from error
        if not grenzen.liegt_innerhalb(target, grenzen.wurzeln(folders)):
            raise WerkzeugVerboten(
                f"'{path}' lies outside the shared folders and the pictures "
                "folder — only a picture inside them can be drawn from."
            )
        if not target.is_file():
            raise WerkzeugVerboten(f"'{path}' is not a file.")
        return target

    async def ausfuehren(
        self, name: str, argumente: dict[str, Any], bild_senke=None,
        ordner: list[str] | None = None, chat_id: str | None = None,
        herkunft: "Herkunft" = "chat", agent: Any | None = None,
        shell_zeitgrenze: int | None = None, cronjob_id: str | None = None,
        ziel_gemeldet: bool = False, modellbild=None, gedaechtnis_zeigen: bool = False,
        rules_of: "Herkunft | None" = None, antwort_id: str | None = None,
        abbruch: asyncio.Event | None = None,
    ) -> str:
        """Executes a tool — but only if it is approved.

        ``antwort_id`` is the answer a chat is writing — read only by the
        tools that put something into it: the ones that paint
        (``draw_image``, ``draw_video``), whose pictures join that answer's
        run in the chat, and ``deliver_file``, whose file hangs on it. It
        comes from here for the reason ``chat_id`` does below.

        ``abbruch`` is the stop signal of the run that calls — read by the
        same tools, whose picture a stop has to end (the painter keeps
        running after the run is gone otherwise, and holds the one-picture
        lock for everybody else), and by the shell, whose command in the
        foreground ends with it.

        ``rules_of`` is whose mode and rules judge the call where that is
        not ``herkunft``'s own: ``"chat"`` for an agent the chat model sent
        off, whose calls are asked about in the chat before they get here
        (app/api/v1/auftraege.py). Only a ``nein`` is refused here, the same
        as for a chat's own call.

        ``gedaechtnis_zeigen`` is whether the memory travels to the model
        asking (app/gedaechtnis.py ``mitschicken``) — read only by
        ``memory_save``, which hands its entries over only then. Left out,
        it hands over none.

        ``bild_senke`` saves image blocks from the result (see
        ``ergebnis_zu_text``) — the chat run passes it through, jobs leave
        it out and get only the note.

        ``modellbild`` is the other direction: a picture the model is to LOOK
        at, handed over as (file name, data URL) and carried to the model by
        ``app/werkzeugbild.py``. Only ``read_file`` uses it, and only a run
        whose model can see images passes one — without it that tool says
        plainly that it cannot show the picture.

        ``ordner`` are the chat's shared working folders. Only the shell tool
        uses them, and it gets them from here rather than as an argument on
        purpose: anything the model can write, the model can forge.

        ``chat_id`` for the same reason: the remembered folder, the live lines
        and a background run's report all belong to a chat, and none of that
        may come out of the model's arguments.

        ``herkunft``/``agent`` are who is asking — a job passes its own
        ``Agent`` and ``herkunft="agent"``.

        ``cronjob_id`` is the schedule entry that fired this run, if any
        — ``cron_note`` reads it, and it comes from here for
        exactly the reason ``chat_id`` does: a note aimed by the model's own
        arguments could be aimed at somebody else's entry. ``goal`` reads it
        too, together with the table itself: the entry is what says
        whether a report may make a sound, and a goal reported out of a chat
        has no entry at all.

        ``ziel_gemeldet`` is whether this run already got a goal report out
        — only ``goal`` reads it, and only the
        caller can answer it, because "this run" is the caller's own idea.

        ``shell_zeitgrenze`` is the command time limit for this run
        (app/befehlszeitwahl.py), resolved by the caller — only the shell
        tool reads it. The origin also decides the shell's background lane:
        a background run reports into a chat, and a job has none, so there
        the shell refuses ``background=true`` plainly instead of starting a
        run whose result reaches nobody.

        This is the one place every call
        must pass through (Tor 3), which is why the judgment happens again
        right here even though most callers already checked it themselves to
        decide whether to show a confirmation prompt first.
        """
        # The second lock on the switch. Not offering a tool already keeps an
        # honest model away from it, but a run can be older than the click and
        # carry a call for something that has since been switched off.
        if name in self.abgeschaltet:
            raise WerkzeugVerboten(f"Tool '{name}' is turned off.")

        # Checked before Tor 3: a feature that is off has its own plain
        # reason, and must not be shadowed by a Tor-3 verdict computed for
        # arguments that were never going to run regardless.
        if self._merkmal_abgeschaltet(name):
            raise WerkzeugVerboten(f"Tool '{name}' is not enabled.")

        urteil = self.urteil(name, argumente, ordner, herkunft, agent, rules_of)
        if urteil.antwort == "nein":
            raise WerkzeugVerboten(
                urteil.grund or f"Tool '{name}' is not allowed.",
                about_path=urteil.about_path,
            )

        # The tools every run is offered (EVER_OFFERED above) are dispatched
        # from their own table, call shape and all. A branch per tool here
        # was a sixth place that had to be remembered whenever that list
        # grew: a third entry would have been offered, drawn in the tools
        # window and never executed — its call falling all the way through
        # to the refusal at the bottom.
        for offered in EVER_OFFERED:
            if offered.tool.WERKZEUG_NAME != name:
                continue
            # Built only for the entry that is really being called: every
            # other tool of this run passes through here too, and none of
            # them reads this.
            zusatz = (
                offered.extra_arguments(
                    self, {"ziel_gemeldet": ziel_gemeldet, "cronjob_id": cronjob_id}
                )
                if offered.extra_arguments
                else {}
            )
            try:
                return await offered.tool.ausfuehren(argumente, **zusatz)
            except offered.refusals as fehler:
                raise WerkzeugVerboten(str(fehler)) from fehler

        if name == memory.WERKZEUG_NAME:
            try:
                return await memory.ausfuehren(
                    argumente, self.memory_pfad, zeigen=gedaechtnis_zeigen
                )
            except memory.MemoryVerboten as fehler:
                raise WerkzeugVerboten(str(fehler)) from fehler

        if name in (skill.LADEN, skill.SCHREIBEN):
            mitgeliefert, eigen = self.skills_orte
            try:
                if name == skill.LADEN:
                    return await skill.laden(argumente, mitgeliefert, eigen)
                return await skill.schreiben(argumente, eigen)
            except skill.SkillVerboten as fehler:
                raise WerkzeugVerboten(str(fehler)) from fehler

        if name == shell.WERKZEUG_NAME:
            try:
                return await shell.ausfuehren(
                    argumente, ordner or [], chat_id,
                    zeitgrenze=shell_zeitgrenze,
                    hintergrund_erlaubt=(herkunft == "chat"),
                    data_dir=getattr(self.folder_share, "data_dir", None),
                    # The run's stop ends a command in the foreground.
                    abbruch=abbruch,
                )
            except shell.ShellVerboten as fehler:
                raise WerkzeugVerboten(str(fehler)) from fehler

        if name == frage_werkzeug.WERKZEUG_NAME:
            # Two runs answer this call, and both do it before it ever gets
            # here: the chat holds it open above the input field
            # (app/api/v1/generierung.py), and a job run holds it open on
            # the run itself (app/auftragsfrage.py), where it stands in the
            # waiting group until somebody comes.
            #
            # So reaching this line means neither did — a call with nobody
            # holding it open, and there is nothing here to execute. A
            # question has no result but an answer.
            raise WerkzeugVerboten(
                "ask_user is answered by the user, not executed. Nothing is "
                "holding this call open."
            )

        if name == auftrag_werkzeug.WERKZEUG_NAME:
            # Two runs start a job, and both do it before the call ever gets
            # here: the chat starts it in its own world
            # (app/api/v1/generierung.py), and a job run starts the child
            # under itself (app/api/v1/auftraege.py) — a part of its own
            # assignment.
            #
            # So reaching this line means neither stood in between: a call
            # with no chat and no assignment behind it at all. That is still
            # a refusal.
            raise WerkzeugVerboten(auftrag_werkzeug.NUR_IM_CHAT)

        if name in video_tool.DRAWING_TOOLS:
            painter = video_tool if name == video_tool.WERKZEUG_NAME else bild_werkzeug
            basis, bilderordner, schluessel = self.bild_zugang
            try:
                # A job run hands its own id in as `chat_id` (for its
                # notes); the tool reads the picture window of the chat the
                # job was started from. Only a chat's own answer takes the
                # picture or the video into the chat.
                return await painter.ausfuehren(
                    argumente, basis, bilderordner, schluessel,
                    antwort_id=antwort_id if herkunft == "chat" else None,
                    chat_id=chat_id if herkunft == "chat" else None,
                    job_id=chat_id if herkunft != "chat" else None,
                    deliver_with=self._deliver_with(herkunft, agent),
                    abbruch=abbruch,
                    input_picture=self._input_picture(argumente.get("image"), ordner),
                )
            except bild_werkzeug.BildWerkzeugFehler as fehler:
                raise WerkzeugVerboten(str(fehler)) from fehler

        if name == cronjob.WERKZEUG_NAME:
            try:
                return await cronjob.ausfuehren(
                    argumente, self.cronjobs_repo, self.agenten_orte,
                    herkunft=herkunft, agent=agent, zeitzone=self.zeitzone,
                    skripte_ordner=self.skripte_ordner,
                )
            except cronjob.CronjobVerboten as fehler:
                raise WerkzeugVerboten(str(fehler)) from fehler

        if name == cron_notiz.WERKZEUG_NAME:
            try:
                return await cron_notiz.ausfuehren(
                    argumente, self.cronjobs_repo, cronjob_id
                )
            except cron_notiz.NotizVerboten as fehler:
                raise WerkzeugVerboten(str(fehler)) from fehler

        if name == ablage_werkzeug.WERKZEUG_NAME:
            # A job's picture stays in the pictures folder, and `draw_image`
            # tells the run to hand it on with this tool by that path. The
            # pictures folder is among the run's own folders
            # (app/dokumentablage.py ``program_folders``), so the copy needs
            # no way of its own.
            try:
                return await ablage_werkzeug.ausfuehren(
                    argumente, self.agentendock, list(ordner or []),
                    herkunft=herkunft, agent=agent,
                    # A job run hands its own id in as `chat_id`.
                    job=chat_id if herkunft == "agent" else None,
                    data_dir=getattr(self.folder_share, "data_dir", None),
                    chat_delivery=self.chat_delivery,
                    # A chat's own call: the chat that asks, and the answer
                    # it is writing, which the file is hung on.
                    chat=chat_id if herkunft == "chat" else None,
                    answer=antwort_id if herkunft == "chat" else None,
                )
            except ablage_werkzeug.AblageVerboten as fehler:
                raise WerkzeugVerboten(str(fehler)) from fehler

        if dateiwerkzeuge.modul(name) is not None:
            # A chat's run shares a new folder with the chat; a job run with
            # itself only. The run's own list is handed over as it is, not
            # copied, so a folder `create_folder` adds counts from the next
            # call of the same run on.
            share = None
            if herkunft == "chat" and chat_id and self.folder_share is not None:
                share = lambda pfad: self.folder_share(chat_id, pfad)  # noqa: E731
            try:
                return await dateiwerkzeuge.ausfuehren(
                    name, argumente, ordner if ordner is not None else [], modellbild, share,
                    getattr(self.folder_share, "data_dir", None),
                )
            except grenzen.GrenzeVerletzt as fehler:
                raise WerkzeugVerboten(str(fehler), about_path=True) from fehler

        eintrag = self._werkzeuge.get(name)
        if eintrag is None:
            raise WerkzeugVerboten(
                f"Tool '{name}' is not enabled. "
                f"Available: {', '.join(self.namen()) or 'none'}"
            )
        client, _, _ = eintrag
        return await client.werkzeug_aufrufen(name, argumente, bild_senke)
