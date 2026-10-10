"""Load and validate the configuration.

Two sources, clearly separated:
  * config.yaml — everything non-secret, kept under version control.
  * .env        — secrets and machine-specific overrides.

The caller obtains the configuration via ``get_config()``. On the first call
it is loaded and cached afterwards.
"""

from __future__ import annotations

import logging
import os
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

from app import atomic_file
from app.configwanderung import wandern
from app.paketierung import aufloesen, eigene_wurzel
from dotenv import load_dotenv
from pydantic import BaseModel, Field, PrivateAttr, field_validator

log = logging.getLogger(__name__)

PROJEKT_WURZEL = Path(__file__).resolve().parent.parent

ReasoningFormat = Literal["native", "harmony", "think", "none"]

# The two endpoints this program starts itself: the main model server
# (app/api/v1/runner.py, RUNNER_ID) and the agent server (app/agentenserver.py,
# ENDPUNKT_ID). Every other endpoint is a provider reached over the network,
# and "local" is a statement about who started the server rather than about
# where it stands - a llama.cpp on this desk that somebody else launched is
# still a provider to this program. Written out here because this is where
# the question is answered; the two modules own their own ids, and this is
# that same pair, not a third opinion about it.
LOKALE_ENDPUNKTE = ("runner", "agentenmodell")


class Capabilities(BaseModel):
    """What an endpoint can do. The frontend shows controls accordingly."""

    streaming: bool = True
    # The same pattern applies to tool_calls, vision and thinking:
    # None = discovery detects it natively (llama.cpp /props — tools and
    # the thinking switch live in the chat template, vision in `modalities`).
    # An explicit entry here ALWAYS wins — even a "no"
    # (safety rule: Gemma's tool_calls-off must not be overruled by
    # detection).
    tool_calls: bool | None = None
    vision: bool | None = None
    # Thinking is the one of the three that is not a yes/no: a model may
    # offer several depths, and a list of them says so. The bare boolean
    # stays valid — it is what the hand switch could say before there were
    # stages, and it reads as a plain on/off control.
    thinking: bool | list[str] | None = None


class EndpointConfig(BaseModel):
    id: str
    # Only a display fallback. Normally leave empty: the name comes from
    # /v1/models on the server itself so nobody has to maintain it in two
    # places. If both are missing, the id is shown.
    name: str | None = None
    # Which model this endpoint means. Leave empty for a local server: it has
    # exactly one model loaded and reports it under /v1/models, so nothing has
    # to be maintained twice.
    #
    # Cloud providers are the other case. OpenAI answers the same question
    # with its entire catalogue — embeddings, speech, image models — and the
    # first entry is whatever it happens to be. Without this field the
    # terminal picked that one and offered an embedding model to chat with.
    modell: str | None = None
    provider: str = "openai_compatible"
    base_url: str
    health_path: str = "/models"
    reasoning_format: ReasoningFormat = "none"
    # Which parameters the server knows and what it calls them.
    # "llama_cpp" for llama-server, "mlx" for mlx_lm.server, "anthropic" for
    # the Messages API, "openai" for the rest and anything unknown.
    # See app/parameter.py.
    parameter_dialect: Literal["llama_cpp", "mlx", "openai", "anthropic"] = "openai"
    # Request usage data in the stream. Without this most servers send no
    # token counts, and the context display would stay empty.
    send_usage_option: bool = True
    # How many tokens fit into the context. Leave empty: the server is then
    # asked (llama.cpp answers this via /props). Only set it when the server
    # does not reveal it itself — e.g. mlx_lm.server.
    context_tokens: int | None = None
    # Endpoints set to false are never even checked and appear nowhere.
    # Meant for switching one off without losing the entry.
    enabled: bool = True
    # Access key for cloud providers (OpenAI and anything speaking its
    # interface). This NEVER holds the value itself, only the name of the
    # environment variable — exactly like the tool servers. The value belongs
    # in .env and is never versioned and never displayed.
    #
    #     api_key_env: "OPENAI_API_KEY"
    #
    # Leave empty for local servers: llama.cpp and mlx_lm want none.
    api_key_env: str | None = None
    # Where this endpoint runs, and what follows from that: the model picker
    # groups by it, and the memory switch asks it whether a request stays on
    # this machine (app/gedaechtnis.py) - a memory that rides along to a
    # provider is not the same act as one that stays here.
    #   local  this program ran the server itself - see LOKALE_ENDPUNKTE below
    #   cloud  a provider, reached over the network: a paid service, or one on
    #          somebody else's machine. Nothing said means this.
    #   extra  an OpenAI-compatible side door of a vendor whose own protocol
    #          we do not speak (Anthropic, Gemini) - works, but is not their
    #          native interface
    #
    # "local" is not a choice the configuration file can make: what makes a
    # server local here is that this program started it, and it starts
    # exactly two. An entry describing a server on this machine - llama.cpp,
    # LM Studio, Ollama - is a provider like any other, because this program
    # did not start it and knows nothing about it (validator below).
    group: Literal["local", "cloud", "extra"] = "cloud"
    # Whether a model call to this endpoint is cut off after `timeout`
    # seconds of silence. On by default — the 600 s a cloud call has
    # always had. Switched off for a server trusted to eventually
    # answer, however long a quiet stretch takes — `group` alone cannot say
    # that: a self-hosted server the validator below still resolves to
    # "cloud" (its id is not one of the two this program starts itself)
    # needs the same trust a genuinely local one would get. The connect
    # timeout is untouched either way: a server that cannot even be
    # reached has nothing to wait for.
    timeout_enabled: bool = True
    capabilities: Capabilities = Field(default_factory=Capabilities)

    @field_validator("base_url")
    @classmethod
    def _kein_schrägstrich_am_ende(cls, wert: str) -> str:
        return wert.rstrip("/")

    @field_validator("group")
    @classmethod
    def _lokal_nur_mit_eigenem_server(cls, wert: str, info) -> str:
        """An endpoint is local when THIS program runs it, not when a file
        says so.

        The two local ones are built in code (app/api/v1/runner.py,
        app/agentenserver.py) and carry their ids; everything that arrives
        over the network is a provider, however its address reads. A
        ``group: local`` in the configuration is therefore read as what the
        entry is - a provider - rather than refused: a line a user wrote must
        not keep the program from starting, and the entry keeps working, it
        is only no longer counted among the servers this program controls.
        The line in the log says so, so the
        difference is not silent.
        """
        if wert == "local" and info.data.get("id") not in LOKALE_ENDPUNKTE:
            log.info(
                "Endpoint '%s' comes from the configuration: it is a provider, "
                "not one of the two local servers - its 'group: local' is not read",
                info.data.get("id"),
            )
            return "cloud"
        return wert


class AppConfig(BaseModel):
    # Loopback by schema default: a missing config file must never mean
    # "reachable by everyone on the network". Serving a whole machine or
    # LAN is a deliberate act — whoever means it writes 0.0.0.0 into
    # config.yaml themselves.
    host: str = "127.0.0.1"
    port: int = 8090
    language: str = "de"
    # The geometry watch in the window (frontend/src/lib/geometriewache.js):
    # a diagnosis harness that records scroll anomalies, paints a report
    # panel over the app and writes marker lines into the access log. A
    # tool for a test service, never for a shipped install — off unless a
    # config turns it on; the flag travels into the page beside the
    # session key (app/main.py).
    diagnose: bool = False
    # The name a system notification carries (app/cronmeldung.py). Same
    # reasoning as the diagnosis flag above: a test service and the shipped
    # install run side by side on one machine, and a schedule fired by the
    # test service announced itself under the shipped program's name — the
    # notification said nothing about which of the two had spoken. Empty
    # means the program's own name, so nothing about a shipped install
    # changes; a test service writes its own.
    meldetitel: str = ""
    data_dir: str = "./data"
    log_dir: str = "./logs"
    # Where the pictures the generator draws are written. A field of its own
    # (not data_dir + "images" spelled out at each call site) so the storage
    # locations module (app/speicherorte.py) has one path to hand out and,
    # later, one path to let the user move. Empty means "under data_dir" — so
    # it follows a moved data folder exactly as the old datenverzeichnis/"bilder"
    # did, instead of a hardcoded path that would strand old pictures.
    bilder_verzeichnis: str = ""
    # Where a cron entry's scripts live. A named location like the
    # pictures above, and for the same two reasons: one path to hand out, and
    # one path the user may move. It is also the security boundary — a cron
    # entry may only start a file that resolves inside THIS folder, so the
    # question "may this run" has one answer in one place instead of a rule
    # per call site. Empty means "under data_dir", so it follows a moved data
    # folder instead of stranding the scripts already in it.
    skripte_verzeichnis: str = ""
    # Where the agents' delivery shelf keeps its files. A named
    # location like the two above, and for the same reason: the shelf used to
    # be data_dir + "agent_dock" spelled out in the module, so nobody could
    # say where their delivered files should go. Empty means "under data_dir",
    # which is byte for byte the old place — an installation that never moves
    # it does not notice the field exists.
    agentendock_verzeichnis: str = ""
    # Where the system prompt lives. Exactly one file for the whole program —
    # it is read fresh on every request and prepended to the history.
    # Deliberately a file and not a database field: the same place should
    # later also be readable by agents and the knowledge base.
    system_prompt_file: str = "./prompts/system.md"
    # The persistent memory (app/gedaechtnis.py) — a second prompt file beside
    # the first, written by the model and by hand, read fresh on every
    # request. Ships empty, like the system prompt.
    memory_file: str = "./prompts/memory.md"
    # Where the agents live — one Markdown file per agent,
    # front matter plus prompt. The folder ships empty.
    agenten_verzeichnis: str = "./prompts/agenten"
    # Shipped agents, same two-layer rule as the skills below: this folder
    # sits next to the program and is replaced by every update, the user's
    # folder above is never touched, and on a name clash the user's file
    # wins.
    agenten_mitgeliefert: str = "./agenten"
    # The permission rules Tor 3 judges by (app/berechtigungen.py). Personal
    # like mcp_servers.json, and resolved the same way: a field of its own so
    # a test (or a moved data folder) can point it elsewhere instead of it
    # always landing next to the running program.
    berechtigungen_datei: str = "./berechtigungen.json"
    # Skills (app/skills.py) live in two places. The shipped ones sit next to
    # the program and are replaced by every update; the user's sit next to
    # their prompts and are never touched. Same name in both: the user's wins.
    skills_mitgeliefert: str = "./skills"
    skills_verzeichnis: str = "./prompts/skills"
    # Where the model files live, and the program that runs them
    # (app/modellrunner.py). The folder is the boundary: only what lies in it
    # can be started. An empty `runner_programm` means "look for it" — in the
    # PATH first, because whoever put it somewhere of their own meant it.
    modelle_verzeichnis: str = "./data/models"
    runner_programm: str | None = None
    # Models that are not language models get folders of their own, and the
    # FOLDER is what says which kind a file is. Telling them apart by name
    # ("embed" somewhere in it) worked for one night and failed as soon as
    # somebody looked: an embedding model turned up in the language model's
    # picker, its start collided with the port the language server holds,
    # and "open model folder" led somewhere else than the file it was about.
    # A folder cannot be guessed wrong.
    einbettungsmodelle_verzeichnis: str = "./data/embedding_models"
    bildmodelle_verzeichnis: str = "./data/image_models"
    # Speech models get a folder of their own for the same reason, and the
    # small text model that tidies a dictation lies in it too: whoever wants
    # a cleaner puts one file next to the other, and which is which is
    # answered by the two picker fields on the panel, not by a name filter.
    sprachmodelle_verzeichnis: str = "./data/speech_models"
    # The embedding server is a small llama-server of its own, so it needs a
    # port of its own — the whole reason the first build collided.
    einbettung_port: int = 8081
    # The speech server and its tidy-up model, again one port each. 8082 is
    # left free on purpose (see app/agentenserver.py) because a chat model
    # started by hand lands there often enough to collide.
    sprache_port: int = 8084
    sprachputz_port: int = 8085
    # No shipped response length here any more. What one answer may write is
    # resolved per request instead (app/antwortgrenze.py): what the user set,
    # or the largest number that still fits this model's window. A number in
    # this file was the same ceiling for an 8k model and a million-token one,
    # and it cut long answers off on both.
    # Time zone for the alarm clock (6.7), e.g. "Europe/Berlin". Times in the
    # agent front matter apply in this zone; if the entry is missing, the
    # server's time zone applies — on a UTC server "08:00" is then 08:00 UTC.
    timezone: str | None = None

    @field_validator("timezone")
    @classmethod
    def _zeitzone_bekannt(cls, wert: str | None) -> str | None:
        # A single config value must never keep the program from starting. If
        # the zone cannot be resolved — a mistyped name, or a host without the
        # time-zone database — it is dropped with a warning instead of raising,
        # and the alarm clock falls back to the host zone (the same behaviour
        # as leaving the field empty).
        if wert is not None:
            from zoneinfo import ZoneInfo

            try:
                ZoneInfo(wert)
            except Exception:
                log.warning("Unknown time zone %r, falling back to host zone", wert)
                return None
        return wert

    @field_validator("port")
    @classmethod
    def _port_im_gueltigen_bereich(cls, wert: int) -> int:
        if not 1 <= wert <= 65535:
            raise ValueError(f"Port {wert} liegt außerhalb von 1-65535")
        return wert


class DatabaseConfig(BaseModel):
    backend: Literal["sqlite"] = "sqlite"
    path: str = "./data/exe-ai-terminal.db"


class FeatureFlags(BaseModel):
    mcp: bool = False
    document_upload: bool = False
    # The shell tool (app/tools/shell.py): lets the model run commands in the
    # folders the user shared with a chat. Shipped on, because the guard sits
    # in the tool itself: sharing a folder is the permission, without one it
    # stays shut, and any command reaching outside the share asks first.
    shell_tool: bool = True


class MCPConfig(BaseModel):
    """Where the MCP servers are registered.

    A separate file instead of a section in config.yaml, because the format
    matches what other programs use as well — an existing server list can be
    adopted without rewriting it.
    """

    servers_file: str = "./mcp_servers.json"
    # The rotating OAuth credentials of the hosted servers. Separate from the
    # server list (the user edits that one, the program edits this one) and
    # separate from .env (which holds FIXED keys — refreshing would keep
    # rewriting it at runtime). Permissions 0600, git-ignored.
    auth_file: str = "./data/mcp_auth.json"


class DiscoveryConfig(BaseModel):
    interval_seconds: int = 15
    timeout_seconds: int = 3


class LoggingConfig(BaseModel):
    level: str = "INFO"
    # "text" reads well in the journal, "json" is machine-parseable.
    format: Literal["text", "json"] = "text"
    # File name in the log directory. Empty = console (journal) only.
    file: str = "exe-ai-terminal.log"
    # Rotate at this size; this many old files are kept around.
    max_bytes: int = 10 * 1024 * 1024
    file_count: int = 5


class Config(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    features: FeatureFlags = Field(default_factory=FeatureFlags)
    endpoints: list[EndpointConfig] = Field(default_factory=list)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    # The file this configuration was read from, for the one start-up step
    # that has to change a line in it (app/folder_names.py). None for a
    # configuration built in code, which has no file to change.
    _source: Path | None = PrivateAttr(default=None)

    @field_validator("endpoints")
    @classmethod
    def _kennungen_eindeutig(cls, wert: list[EndpointConfig]) -> list[EndpointConfig]:
        gesehen: set[str] = set()
        for endpunkt in wert:
            if endpunkt.id in gesehen:
                raise ValueError(f"Endpunkt-Kennung '{endpunkt.id}' ist doppelt vergeben")
            gesehen.add(endpunkt.id)
        return wert

    # --- derived paths, always absolute ---------------------------------

    def pfad(self, relativ: str) -> Path:
        """A path from the configuration that belongs to the user.

        Packaged, this is the folder beside their other application data —
        never beside the program, which is read-only, and never relative to
        the working directory, which is whatever the desktop handed over.
        """
        return aufloesen(relativ, schreibbar=True).resolve()

    def mitgeliefert(self, relativ: str) -> Path:
        """A path to something that ships with the program and is only read.

        Separate from `pfad` because the two part company as soon as the
        program is packaged: an update replaces this and must not touch the
        other.
        """
        return aufloesen(relativ).resolve()

    @property
    def datenverzeichnis(self) -> Path:
        return self.pfad(self.app.data_dir)

    @property
    def logverzeichnis(self) -> Path:
        return self.pfad(self.app.log_dir)

    @property
    def skillverzeichnisse(self) -> tuple[Path, Path]:
        """The two skill folders, shipped first, the user's second.

        Always as a pair, because they are only ever meaningful together:
        the second one overrides the first, and asking for one without the
        other would give a wrong answer about which skill is in force.
        """
        return (
            self.mitgeliefert(self.app.skills_mitgeliefert),
            self.pfad(self.app.skills_verzeichnis),
        )

    @property
    def agentenverzeichnisse(self) -> tuple[Path, Path]:
        """The two agent folders, shipped first, the user's second.

        Same pairing rule as the skills above: the second overrides the
        first, and asking for one without the other would give a wrong
        answer about which agent is in force.
        """
        return (
            self.mitgeliefert(self.app.agenten_mitgeliefert),
            self.pfad(self.app.agenten_verzeichnis),
        )

    @property
    def datenbankpfad(self) -> Path:
        return self.pfad(self.database.path)

    def endpunkt(self, kennung: str) -> EndpointConfig | None:
        for endpunkt in self.endpoints:
            if endpunkt.id == kennung:
                return endpunkt
        return None

    def system_prompt_lesen(self) -> str:
        """The system prompt, fresh from disk.

        Called on every request, not cached: a change to the file should take
        effect immediately, including in existing chats. That is the whole
        point of the rework — before, a copy sat in the chat and never saw
        later changes.

        If the file is missing, there simply is no prompt. That is the
        as-shipped state: whoever installs the program finds an empty field
        and fills in what they want themselves.
        """
        datei = self.pfad(self.app.system_prompt_file)
        if not datei.exists():
            return ""
        try:
            return datei.read_text(encoding="utf-8").strip()
        except OSError as fehler:
            log.warning("System prompt cannot be read (%s): %s", datei, fehler)
            return ""

    def memory_lesen(self) -> str:
        """The memory, fresh from disk — same rules as the system prompt.

        A missing file is not an error: that is the as-shipped state, and it
        is also what a user gets who deleted everything the program had
        learned about them.
        """
        datei = self.pfad(self.app.memory_file)
        if not datei.exists():
            return ""
        try:
            return datei.read_text(encoding="utf-8").strip()
        except OSError as fehler:
            log.warning("Memory cannot be read (%s): %s", datei, fehler)
            return ""

    def memory_schreiben(self, text: str) -> None:
        """Writes the memory back — side file first, then rename.

        The same care as with the system prompt, and here it matters more: an
        interrupted write would leave the program having forgotten half of
        what it knew, with nothing to say so.
        """
        datei = self.pfad(self.app.memory_file)
        datei.parent.mkdir(parents=True, exist_ok=True)
        atomic_file.write(datei, text.strip() + ("\n" if text.strip() else ""))

    def system_prompt_schreiben(self, text: str) -> None:
        """Writes the system prompt back to the file.

        First to a side file, then rename: if the write is interrupted, the
        old version stays intact instead of being left half overwritten.
        """
        datei = self.pfad(self.app.system_prompt_file)
        datei.parent.mkdir(parents=True, exist_ok=True)
        atomic_file.write(datei, text.strip() + ("\n" if text.strip() else ""))


# Settings that were retired, with what happens instead. A key left behind
# in a file somebody wrote years ago is not an error and not a reason to
# rewrite their file — but it has to say out loud that it no longer does
# anything, or the number sits there looking like it is in force.
ABGELEGTE_APP_SCHLUESSEL: dict[str, str] = {
    "default_max_tokens": (
        "the response length is now resolved per request — what is set wins, "
        "otherwise the largest number that fits the model's window"
    ),
}


# What the check below found in the LAST load, kept until there is
# somewhere to say it. The configuration is read before logging is set up
# (app/main.py, `app_erstellen`), so a line written at that moment would go
# nowhere.
#
# One load, one list: `config_laden` empties it before it fills it again.
# Appended to across loads it grew without a bound wherever the
# configuration is read more often than an app is built — a test run, a
# repeated `get_config` — and what finally reached the log was the same
# finding stacked as many times as the file had been read.
_ABGELEGTE_GEFUNDEN: list[tuple[Path, str]] = []


def _abgelegte_schluessel_sammeln(rohdaten: dict, quelle: Path) -> None:
    """Notes which retired settings are still in the file. Never writes: the
    configuration belongs to whoever runs this program, and a key that does
    nothing costs them nothing but a line."""
    app = rohdaten.get("app")
    if not isinstance(app, dict):
        return
    for schluessel in ABGELEGTE_APP_SCHLUESSEL:
        if schluessel in app:
            _ABGELEGTE_GEFUNDEN.append((quelle, schluessel))


def abgelegte_schluessel_melden() -> None:
    """Says it, once logging exists. Called from ``app_erstellen`` right
    after the log is set up."""
    while _ABGELEGTE_GEFUNDEN:
        quelle, schluessel = _ABGELEGTE_GEFUNDEN.pop(0)
        log.info(
            "config.yaml (%s): 'app.%s' is no longer read — %s. The file is "
            "left exactly as it is.",
            quelle,
            schluessel,
            ABGELEGTE_APP_SCHLUESSEL[schluessel],
        )


def _umgebung_anwenden(rohdaten: dict) -> dict:
    """Allows targeted overrides from the environment (EXE_AI_*)."""
    app = rohdaten.setdefault("app", {})
    if port := os.getenv("EXE_AI_PORT"):
        app["port"] = int(port)
    if host := os.getenv("EXE_AI_HOST"):
        app["host"] = host
    if sprache := os.getenv("EXE_AI_LANGUAGE"):
        app["language"] = sprache
    if datenbank := os.getenv("EXE_AI_DB_PATH"):
        rohdaten.setdefault("database", {})["path"] = datenbank
    return rohdaten


def erststart_kopie(ziel: Path, vorlage: Path) -> None:
    """Puts a shipped file into the user's folder, once.

    Files like the server list start as ours and become theirs the moment
    they edit one. Packaged, ours lies in a folder that an update replaces,
    so a copy has to move across before anybody writes into it — otherwise
    the first edit is gone with the next version.

    Public: ``app/berechtigungsregeln.py`` reuses it for the same pattern
    with ``berechtigungen.json``.
    """
    if ziel.exists() or not vorlage.exists() or ziel == vorlage:
        return
    ziel.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(vorlage, ziel)
    log.info("First start: %s created", ziel.name)


def config_laden(pfad: str | Path | None = None) -> Config:
    """Reads config.yaml (+ .env) and returns a validated configuration."""
    # With a folder of its own (EXE_AI_DATEN) the program folder's .env belongs to
    # whoever runs the program: loaded first, its keys would win over the user's own.
    # Read once, before any .env: only a folder named from outside says so. One
    # named in the program folder's own .env belongs to the same person as that file.
    eigene = eigene_wurzel()
    if eigene is None:
        load_dotenv(PROJEKT_WURZEL / ".env", override=False)
    # Packaged, the user's .env lives in the writable folder next to
    # config.yaml — the project root inside the bundle is an ephemeral
    # extraction dir, so a key saved at runtime would vanish from the
    # environment on every restart if only the line above ran.
    load_dotenv(aufloesen(".env", schreibbar=True), override=False)

    # The configuration belongs to the user, so packaged it lives next to
    # their data and not inside the program, which is read-only.
    quelle = Path(pfad or os.getenv("EXE_AI_CONFIG") or aufloesen("config.yaml", schreibbar=True))

    # First start: config.yaml does not exist yet because it is not shipped -
    # it holds personal addresses and is git-ignored. What IS shipped is
    # config.example.yaml with commented examples. Copy it once, then the
    # file belongs to the user and is never touched again.
    # Only for the default location. If someone names a file explicitly and
    # it is missing, that is an error and must stay one - silently creating
    # a file at a path the caller chose would hide their typo.
    ausdruecklich = pfad is not None or os.getenv("EXE_AI_CONFIG")
    if not quelle.exists() and not ausdruecklich:
        vorlage = aufloesen("config.example.yaml")
        if vorlage.exists():
            shutil.copy2(vorlage, quelle)
            log.info("First start: %s created from %s", quelle.name, vorlage.name)

    # The server list is personal the moment it is touched: it holds
    # addresses, keys and machines of the person running this. It is
    # therefore git-ignored like config.yaml, and what ships is the example
    # beside it. Copied on first start, then it belongs to the user.
    # With a folder of its own, the program folder's list is somebody else's
    # too: such a person starts from the example.
    if eigene is None:
        erststart_kopie(aufloesen("mcp_servers.json", schreibbar=True),
                        aufloesen("mcp_servers.json"))
    erststart_kopie(aufloesen("mcp_servers.json", schreibbar=True),
                    aufloesen("mcp_servers.example.json"))

    if not quelle.exists():
        raise FileNotFoundError(
            f"Konfigurationsdatei nicht gefunden: {quelle}. "
            "Vorlage liegt als config.example.yaml im Projektverzeichnis."
        )

    # Then the other direction: an existing file gets whatever the program
    # has learned since it was written. A setting only the schema knows about
    # is a setting nobody can find - see app/configwanderung.py. Runs before
    # the file is read, so the additions take effect the same start; it never
    # changes a value that is already there and never raises.
    wandern(quelle, aufloesen("config.example.yaml"), Config)

    rohdaten = yaml.safe_load(quelle.read_text(encoding="utf-8")) or {}
    # Emptied first, so what stands there afterwards is what THIS load
    # found and not everything every earlier load found as well.
    _ABGELEGTE_GEFUNDEN.clear()
    _abgelegte_schluessel_sammeln(rohdaten, quelle)
    config = Config.model_validate(_umgebung_anwenden(rohdaten))
    config._source = quelle
    return config


@lru_cache(maxsize=1)
def get_config() -> Config:
    """Cached configuration for the running process."""
    return config_laden()

