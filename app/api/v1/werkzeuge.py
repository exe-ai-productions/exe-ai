"""Which tools are available — and their editor form (A6).

Shows only what remains after the lockdown — i.e. exactly what the model
actually gets offered. Since A6 the administration hangs here as well:
``GET/PUT /tools/config`` read and write the ``mcp_servers.json`` raw, with
a broken-check like the agent files. Saving means applying: a valid file
restarts the registry in the background.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re

from dotenv import dotenv_values, load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app import aufgaben, befehlszeitwahl, sprachwahl
from app.api.abhaengigkeiten import hole_config, hole_repositories, hole_sprache
from app.config import Config
from app.db import Repositories
from app.env_datei import env_schreiben
from app.i18n import t
from app.paketierung import aufloesen
from app.tools import WerkzeugRegistry, server_lesen
from app.tools.aufbau import registry_bauen
from app.tools.mcp_auth import MCPAnmeldeFehler, OAuthVermittler
from app.tools.mcp_client import MCPFehler
from app.tools.mcp_sondierung import sondieren
from app.tools.registry import konfiguration_pruefen

log = logging.getLogger(__name__)

router = APIRouter(tags=["werkzeuge"])

# If the file does not exist yet, the editor form shows this skeleton.
KONFIG_VORLAGE = '{\n  "mcpServers": {}\n}\n'

PLATZHALTER_MUSTER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

# Two quick saves in a row must not brawl over app.state.
_neustart_sperre = asyncio.Lock()


class WerkzeugAntwort(BaseModel):
    name: str
    beschreibung: str
    server: str
    needs_confirmation: bool
    # Which of the two this tool is (app/tools/registry.py, ``uebersicht``):
    # a built-in of this program, or one a connected server brings. The
    # tools window groups by it — by NAME it cannot, because a server that
    # happens to be called like a built-in one (a server called "clock", or
    # one called "shell") would silently take that row over.
    #
    # Left out means a server's, not a built-in: were it the other way
    # round, a tool of somebody's server would stand among the built-ins as
    # if it came with the program. Same direction the tools window reads it
    # (frontend/src/lib/werkzeuge.svelte.js, ``quellen``).
    builtin: bool = False


class WerkzeugeAntwort(BaseModel):
    aktiv: bool
    server: list[str]
    werkzeuge: list[WerkzeugAntwort]


def hole_registry(request: Request) -> WerkzeugRegistry | None:
    return getattr(request.app.state, "werkzeuge", None)


@router.get("/tools", response_model=WerkzeugeAntwort, summary="Allowed tools")
def werkzeuge(
    registry: WerkzeugRegistry | None = Depends(hole_registry),
    config: Config = Depends(hole_config),
    repositories: Repositories = Depends(hole_repositories),
) -> WerkzeugeAntwort:
    if registry is None:
        return WerkzeugeAntwort(aktiv=False, server=[], werkzeuge=[])
    # No chat or model is in scope here — this is the global tools window,
    # not a running conversation — so only the global layer of the cascade
    # applies, same as showing no override at all would.
    shell_zeitgrenze = befehlszeitwahl.sekunden(repositories)
    return WerkzeugeAntwort(
        aktiv=config.features.mcp,
        server=sorted(registry.clients),
        werkzeuge=[
            WerkzeugAntwort(**eintrag)
            for eintrag in registry.uebersicht(shell_zeitgrenze)
        ],
    )


# --- The editor form (A6): reading and writing mcp_servers.json -------------


class PlatzhalterAntwort(BaseModel):
    name: str
    gesetzt: bool


class WerkzeugKonfiguration(BaseModel):
    content: str
    kaputt: str | None
    platzhalter: list[PlatzhalterAntwort]


class WerkzeugKonfigurationSchreiben(BaseModel):
    content: str


def _platzhalter(text: str) -> list[PlatzhalterAntwort]:
    """The ${…} placeholders with their traffic light: set or missing.

    The .env is read fresh on every request — a token just entered via SSH
    shows green immediately, without restarting the service.
    The values themselves never leave the server (the UI has no login).
    """
    env_datei = dotenv_values(aufloesen(".env", schreibbar=True))
    namen = set(PLATZHALTER_MUSTER.findall(text))
    # `api_key_env` points to the same place (.env), just without the
    # ${…} notation — the traffic light should show it just the same.
    try:
        rohdaten = json.loads(text)
        for felder in (rohdaten.get("mcpServers") or {}).values():
            if isinstance(felder, dict):
                wert = felder.get("api_key_env")
                if isinstance(wert, str) and wert:
                    namen.add(wert)
    except (json.JSONDecodeError, AttributeError):
        pass  # a broken file has its own message
    return [
        PlatzhalterAntwort(
            name=name, gesetzt=bool(os.environ.get(name) or env_datei.get(name))
        )
        for name in sorted(namen)
    ]


def _konfig_antwort(text: str, sprache: str) -> WerkzeugKonfiguration:
    return WerkzeugKonfiguration(
        content=text, kaputt=konfiguration_pruefen(text, sprache), platzhalter=_platzhalter(text)
    )


@router.get(
    "/tools/config",
    response_model=WerkzeugKonfiguration,
    summary="The raw tool configuration (for the form)",
)
def werkzeug_konfiguration(
    config: Config = Depends(hole_config),
    sprache: str = Depends(hole_sprache),
) -> WerkzeugKonfiguration:
    pfad = config.pfad(config.mcp.servers_file)
    text = pfad.read_text(encoding="utf-8") if pfad.exists() else KONFIG_VORLAGE
    return _konfig_antwort(text, sprache)


@router.put(
    "/tools/config",
    response_model=WerkzeugKonfiguration,
    summary="Save and apply the tool configuration",
)
async def werkzeug_konfiguration_schreiben(
    daten: WerkzeugKonfigurationSchreiben,
    request: Request,
    config: Config = Depends(hole_config),
    sprache: str = Depends(hole_sprache),
) -> WerkzeugKonfiguration:
    """Always saves — it is the user's file.

    If it's no good, the reason goes into ``kaputt`` and nothing is applied.
    If it's good, the tool servers restart in the background — the response
    does not wait for that (an npx cold start can take a while), the form's
    read display fetches the result via ``GET /tools``.
    """
    pfad = config.pfad(config.mcp.servers_file)
    pfad.write_text(daten.content, encoding="utf-8")
    antwort = _konfig_antwort(daten.content, sprache)
    if antwort.kaputt is None and config.features.mcp:
        aufgaben.halten(
            _registry_neustarten(request.app, config), name="registry-neustart"
        )
    return antwort


# --- The server entries, structured (for the tile gallery) ------------------
#
# The gallery writes mcp_servers.json in structured form instead of raw: an
# entry is created, toggled, or removed without anyone typing JSON.
# The file remains the single truth — the text field behind it works
# unchanged, both paths write to the same place.


class WerkzeugKurz(BaseModel):
    name: str
    beschreibung: str


class ServerUebersicht(BaseModel):
    name: str
    type: str
    url: str | None
    enabled: bool
    api_key_env: str | None
    allowed_tools: list[str] | None
    needs_confirmation: list[str]
    # Is the server currently alive in the registry?
    laeuft: bool
    # Only with api_key_env: is the key present in the .env?
    schluessel_gesetzt: bool | None
    # If it is running: ALL tools the server offers — the checkbox list
    # shows them in full, approved is the intersection.
    alle_werkzeuge: list[WerkzeugKurz]


class MCPSondierungAnfrage(BaseModel):
    url: str


class MCPSondierungAntwort(BaseModel):
    # None once the server answered outright; otherwise what it asked for.
    verlangt: str | None
    name: str | None


@router.post(
    "/tools/mcp/sondieren",
    response_model=MCPSondierungAntwort,
    summary="Ask an MCP address that is not entered yet what it requires",
)
async def mcp_sondieren(daten: MCPSondierungAnfrage) -> MCPSondierungAntwort:
    try:
        ergebnis = await sondieren(daten.url)
    except MCPFehler as fehler:
        raise HTTPException(400, str(fehler)) from None
    return MCPSondierungAntwort(**ergebnis)


class ServerSchreiben(BaseModel):
    type: str | None = None
    url: str | None = None
    command: str | None = None
    args: list[str] | None = None
    enabled: bool | None = None
    api_key_env: str | None = None
    allowed_tools: list[str] | None = None
    needs_confirmation: list[str] | None = None
    # Never stored: written straight to .env and left out of the file, the
    # same split the provider window already keeps between config.yaml and
    # .env (app/api/v1/anbieter.py). `api_key_env` is what lands in the file.
    # One line, like the name beside it: a line break inside the key would
    # write a second, foreign variable into the shared .env.
    api_key: str | None = Field(default=None, pattern=r"^[^\r\n]*$")


def _rohdaten_lesen(config: Config, sprache: str) -> dict:
    """The server file, for a change made through the gallery.

    A file this side cannot read (no JSON, no object `mcpServers`) is
    refused, never read as empty: written back from an empty start, every
    other entry in it would be gone. The answer is the check's own reason,
    the one the text field shows for the same file.
    """
    pfad = config.pfad(config.mcp.servers_file)
    if not pfad.exists():
        return {"mcpServers": {}}
    text = pfad.read_text(encoding="utf-8")
    if not text.strip():
        # An empty file holds nothing that could be lost.
        return {"mcpServers": {}}
    try:
        daten = json.loads(text)
    except json.JSONDecodeError:
        daten = None
    if not isinstance(daten, dict) or not isinstance(daten.get("mcpServers"), dict):
        raise HTTPException(409, konfiguration_pruefen(text, sprache))
    return daten


def _schluessel_gesetzt(name: str | None) -> bool | None:
    if not name:
        return None
    env_datei = dotenv_values(aufloesen(".env", schreibbar=True))
    return bool(os.environ.get(name) or env_datei.get(name))


@router.get(
    "/tools/servers",
    response_model=list[ServerUebersicht],
    summary="The server entries with their live state (for the gallery)",
)
def server_uebersicht(
    registry: WerkzeugRegistry | None = Depends(hole_registry),
    config: Config = Depends(hole_config),
) -> list[ServerUebersicht]:
    uebersicht = []
    for eintrag in server_lesen(config.pfad(config.mcp.servers_file)):
        client = registry.clients.get(eintrag.name) if registry else None
        uebersicht.append(
            ServerUebersicht(
                name=eintrag.name,
                type=eintrag.type,
                url=eintrag.url,
                enabled=eintrag.enabled,
                api_key_env=eintrag.api_key_env,
                allowed_tools=eintrag.allowed_tools,
                needs_confirmation=eintrag.needs_confirmation,
                laeuft=client is not None,
                schluessel_gesetzt=_schluessel_gesetzt(eintrag.api_key_env),
                alle_werkzeuge=[
                    WerkzeugKurz(name=w.name, beschreibung=w.beschreibung)
                    for w in (client.werkzeuge if client else [])
                ],
            )
        )
    return sorted(uebersicht, key=lambda e: e.name)


@router.put(
    "/tools/servers/{name}",
    response_model=WerkzeugKonfiguration,
    summary="Create or change a server entry (for the gallery)",
)
async def server_schreiben(
    name: str,
    daten: ServerSchreiben,
    request: Request,
    neu: bool = Query(default=False),
    config: Config = Depends(hole_config),
    sprache: str = Depends(hole_sprache),
) -> WerkzeugKonfiguration:
    """Only named fields are touched; an explicit null deletes the field
    (allowed_tools: null again means: offer everything).

    ``neu`` is a server being added, not one being changed. Its id is made
    from its name alone, so "GitHub" becomes ``github`` and can meet an entry
    already on file — merged into it, two servers' address and key would
    stand side by side without a word. A new one is refused instead, naming
    the id that is taken.

    Unlike the raw text field, what would be broken is NOT saved here —
    the gallery types no JSON, so there is no honest reason to accept a
    broken file.
    """
    rohdaten = _rohdaten_lesen(config, sprache)
    if neu and name in rohdaten["mcpServers"]:
        raise HTTPException(409, t("mcp_datei.schon_eingetragen", sprache, name=name))
    eintrag = rohdaten["mcpServers"].setdefault(name, {})
    felder = daten.model_dump(exclude_unset=True)
    api_key = felder.pop("api_key", None)
    for feld, wert in felder.items():
        if wert is None:
            eintrag.pop(feld, None)
        else:
            eintrag[feld] = wert

    text = json.dumps(rohdaten, ensure_ascii=False, indent=2) + "\n"
    kaputt = konfiguration_pruefen(text, sprache)
    if kaputt is not None:
        raise HTTPException(400, kaputt)

    config.pfad(config.mcp.servers_file).write_text(text, encoding="utf-8")

    # The key last, same order as the provider window: an entry without a
    # key shows a red lamp and can be repaired, a key without an entry
    # belongs to nothing and is only lying around.
    if api_key:
        umgebungsname = eintrag.get("api_key_env")
        if umgebungsname:
            env_schreiben(config.pfad("./.env"), umgebungsname, api_key.strip())
            os.environ[umgebungsname] = api_key.strip()

    if config.features.mcp:
        aufgaben.halten(
            _registry_neustarten(request.app, config), name="registry-neustart"
        )
    return _konfig_antwort(text, sprache)


@router.delete(
    "/tools/servers/{name}",
    status_code=204,
    response_model=None,
    response_class=Response,
    summary="Remove a server entry (with its access)",
)
async def server_entfernen(
    name: str,
    request: Request,
    config: Config = Depends(hole_config),
    sprache: str = Depends(hole_sprache),
) -> None:
    rohdaten = _rohdaten_lesen(config, sprache)
    if name not in rohdaten["mcpServers"]:
        raise HTTPException(404, t("mcp_datei.nicht_eingetragen", sprache, name=name))
    del rohdaten["mcpServers"][name]
    text = json.dumps(rohdaten, ensure_ascii=False, indent=2) + "\n"
    config.pfad(config.mcp.servers_file).write_text(text, encoding="utf-8")
    # Whoever throws away the entry doesn't want to keep the access either.
    vermittler = getattr(request.app.state, "mcp_oauth", None)
    if vermittler is not None:
        vermittler.vergessen(name)
    if config.features.mcp:
        aufgaben.halten(
            _registry_neustarten(request.app, config), name="registry-neustart"
        )


# --- The browser sign-in (OAuth) for hosted servers -------------------------


def hole_oauth(request: Request) -> OAuthVermittler:
    return request.app.state.mcp_oauth


class OAuthStartAnfrage(BaseModel):
    server: str
    # The manual route (Google & co.): a client id created by hand at the
    # provider. Empty means: dynamic registration.
    client_id: str | None = None
    client_secret: str | None = None


class OAuthStartAntwort(BaseModel):
    url: str


class OAuthStatusAntwort(BaseModel):
    server: str
    verbunden: bool
    laeuft_ab: float | None


@router.post(
    "/tools/oauth/start",
    response_model=OAuthStartAntwort,
    summary="Begin the browser sign-in at a hosted MCP server",
)
async def oauth_start(
    daten: OAuthStartAnfrage,
    vermittler: OAuthVermittler = Depends(hole_oauth),
    config: Config = Depends(hole_config),
    sprache: str = Depends(hole_sprache),
) -> OAuthStartAntwort:
    """Prepares the sign-in dance and returns the address for the browser.

    The UI does the opening — the server opens no windows.
    """
    eintraege = {
        e.name: e for e in server_lesen(config.pfad(config.mcp.servers_file))
    }
    eintrag = eintraege.get(daten.server)
    if eintrag is None or eintrag.type != "http" or not eintrag.url:
        raise HTTPException(404, t("mcp_datei.kein_http", sprache, name=daten.server))
    if eintrag.api_key_env:
        raise HTTPException(
            400,
            t("mcp_datei.fester_schluessel", sprache, name=daten.server, env=eintrag.api_key_env),
        )
    try:
        url = await vermittler.anmelde_url(
            daten.server,
            eintrag.url,
            daten.client_id,
            daten.client_secret,
            language=sprache,
        )
    except MCPAnmeldeFehler as fehler:
        raise HTTPException(400, fehler.text(sprache)) from None
    return OAuthStartAntwort(url=url)


def _rueckruf_seite(gelungen: bool, text: str, language: str) -> str:
    """The small page the browser lands on after signing in.

    It speaks the language the sign-in was started in. ``text`` is the
    server's name, or the reason the sign-in failed; either may come from
    outside — the provider's error word arrives in the address — so it is
    written as text, never as markup.
    """
    text = html.escape(text)
    if gelungen:
        titel = t("mcp_signin.connected", language)
        zeile = t("mcp_signin.connected_line", language, name=text)
    else:
        titel = t("mcp_signin.not_connected", language)
        zeile = f'{text}<br><span class="note">{t("mcp_signin.not_completed", language)}</span>'
    return f"""<!doctype html>
<html lang="{language}"><head><meta charset="utf-8"><title>{titel} — Exe AI</title>
<style>
  body {{ font: 15px/1.6 -apple-system, system-ui, sans-serif; display: grid;
         place-items: center; min-height: 90vh; margin: 0;
         background: #f6f6f4; color: #1a1a18; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #161615; color: #ececea; }} }}
  main {{ text-align: center; padding: 24px; }}
  h1 {{ font-size: 19px; margin: 0 0 8px; }}
  .note {{ opacity: 0.6; font-size: 13px; }}
</style></head>
<body><main><h1>{titel}</h1><p>{zeile}</p></main></body></html>"""


@router.get(
    "/tools/oauth/callback",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def oauth_rueckruf(
    request: Request,
    state: str = "",
    code: str = "",
    error: str = "",
    vermittler: OAuthVermittler = Depends(hole_oauth),
    config: Config = Depends(hole_config),
    repositories: Repositories = Depends(hole_repositories),
) -> HTMLResponse:
    """This is where the browser lands after signing in at the provider.

    Secured by the one-time, time-limited state — without it nothing is
    exchanged. After a successful exchange the tool servers restart in the
    background so the freshly connected one joins in immediately.

    The page speaks the language the sign-in was started in, which the
    flow carries: this request comes from the provider's page and says
    nothing about the app. Only where no flow is known under the state
    does it speak as any page the service hands out does — the language
    chosen for the interface, and the browser's own where the device
    decides. Read before the exchange, which uses the state up.
    """
    language = vermittler.language_of(state) or sprachwahl.page_language(
        repositories, request
    )
    if error:
        return HTMLResponse(
            _rueckruf_seite(
                False, t("mcp_signin.provider_says", language, error=error), language
            ),
            status_code=400,
        )
    try:
        server = await vermittler.rueckruf(state, code)
    except MCPAnmeldeFehler as fehler:
        return HTMLResponse(
            _rueckruf_seite(False, fehler.text(language), language), status_code=400
        )
    if config.features.mcp:
        aufgaben.halten(
            _registry_neustarten(request.app, config), name="registry-neustart"
        )
    return HTMLResponse(_rueckruf_seite(True, server, language))


@router.get(
    "/tools/oauth/status",
    response_model=list[OAuthStatusAntwort],
    summary="Which hosted servers are connected (never the values)",
)
def oauth_status(
    vermittler: OAuthVermittler = Depends(hole_oauth),
) -> list[OAuthStatusAntwort]:
    return [
        OAuthStatusAntwort(server=server, **eintrag)
        for server, eintrag in sorted(vermittler.status().items())
    ]


@router.delete(
    "/tools/oauth/{server}",
    status_code=204,
    # Explicitly NO response model: FastAPI otherwise interprets the
    # "-> None" annotation as a NoneType model and refuses with 204.
    response_model=None,
    response_class=Response,
    summary="Disconnect and forget the access",
)
async def oauth_vergessen(
    server: str,
    request: Request,
    vermittler: OAuthVermittler = Depends(hole_oauth),
    config: Config = Depends(hole_config),
) -> None:
    """Throws away the credentials and rebuilds the registry — the server's
    tools thereby disappear from the offering immediately."""
    vermittler.vergessen(server)
    if config.features.mcp:
        aufgaben.halten(
            _registry_neustarten(request.app, config), name="registry-neustart"
        )


async def _registry_neustarten(app, config: Config) -> None:
    """Rebuilds the registry from the freshly saved file.

    Saving means applying (A6 decision). The old registry is not stopped
    immediately: running runs hold it in hand and finish with the old
    tools — it is wound down as soon as no run is alive anymore.
    """
    async with _neustart_sperre:
        try:
            # Pick up freshly entered secrets. override, because the .env
            # is the authoritative source here — a token changed there
            # should win, not the old value in the process.
            load_dotenv(aufloesen(".env", schreibbar=True), override=True)
            # The SAME builder the startup uses (app/tools/aufbau.py). It
            # used to be a second, shorter argument list here — and the
            # tools it forgot (draw_image, cronjob, start_job,
            # deliver_file) disappeared from the offering after every save
            # until the service was restarted.
            neu = registry_bauen(app, config)
            await neu.starten()
        except Exception:  # noqa: BLE001 - a broken restart must not drag down the service
            log.exception("Registry restart failed — the old one stays in service")
            return
        alt = getattr(app.state, "werkzeuge", None)
        app.state.werkzeuge = neu
        log.info(
            "Tool registry rebuilt: %d tool(s) from %d server(s)",
            neu.anzahl,
            len(neu.clients),
            extra={"ereignis": "registry_neustart", "werkzeuge": neu.anzahl},
        )
        if alt is not None:
            aufgaben.halten(
                _ausklingen(alt, app.state.generierungen), name="registry-ausklingen"
            )


async def _ausklingen(registry: WerkzeugRegistry, generierungen) -> None:
    """Stops the superseded registry as soon as no run is alive anymore.

    Upper bound half an hour — longer than any job restraint. After that it
    is stopped even if something is still running: a tool call to it then
    fails visibly as a failed result, not as a crash.
    """
    schleife = asyncio.get_event_loop()
    frist = schleife.time() + 30 * 60
    while generierungen.laufende() and schleife.time() < frist:
        await asyncio.sleep(10)
    await registry.stoppen()
