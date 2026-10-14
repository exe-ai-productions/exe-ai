"""The ONE place a ``WerkzeugRegistry`` gets built.

There are two moments a registry comes into being: at startup
(``app/main.py``) and after the settings were saved
(``app/api/v1/werkzeuge.py`` — saving means applying). Both handed in
their own argument list, and the two lists drifted apart: the restart
after saving forgot ``bild_zugang``, ``cronjobs_repo``, ``agenten_orte``,
``agentendock`` and ``zeitzone``, so ``draw_image``, ``cronjob``,
``start_job`` and ``deliver_file`` silently vanished from the offering
until the next restart of the service.

A list maintained twice drifts apart again, so it is maintained once —
here. Everything the registry needs beyond the config comes off
``app.state``, which both callers have in hand at that moment.
"""

from __future__ import annotations

import functools
import ipaddress

from app import dokumentablage, mcp_name_move
from app.agentendock import dock_fuer
from app.config import PROJEKT_WURZEL, Config
from app.speicherorte import ort
from app.tools import create_folder, video_tool
from app.tools.registry import WerkzeugRegistry, program_tool_names, server_lesen


# A service listening on every address is reached on loopback of the same
# family; one bound to a single address only answers there. An IPv6
# wildcard socket may refuse IPv4 (Windows sets IPV6_V6ONLY), so it is
# reached on IPv6 loopback.
def dial_host(host: str) -> str:
    """The host to connect to for a service bound to ``host``: a wildcard
    (or nothing) is reached on loopback, a single address on itself."""
    host = host.strip() or "0.0.0.0"
    try:
        address = ipaddress.ip_address(host.split("%")[0])
    except ValueError:
        address = None
    if address is not None and address.is_unspecified:
        host = "::1" if address.version == 6 else "127.0.0.1"
    return host


def service_url(host: str, port: int) -> str:
    """The base URL of a service bound to ``host`` on ``port``, as it is
    reached from this machine."""
    reached = dial_host(host)
    if ":" in reached:
        reached = f"[{reached}]"
    return f"http://{reached}:{port}"


def own_address(config: Config) -> str:
    """The base URL this very service answers on, for its own tools."""
    return service_url(config.app.host, config.app.port)


def _move_names(app, config: Config):
    """What the registry calls with a server's tool names once the server has
    started: the lists and rules that still name them as the server does are
    moved to the names the model is offered (``app/mcp_name_move.py``)."""
    marker = config.pfad(config.mcp.servers_file).with_name("mcp_namen.json")

    def move(server: str, tools: list[str]) -> None:
        mcp_name_move.move_for_server(
            server,
            tools,
            built_in=program_tool_names(),
            repositories=app.state.repositories,
            agent_folder=config.pfad(config.app.agenten_verzeichnis),
            rules_path=config.pfad(config.app.berechtigungen_datei),
            marker=marker,
        )

    return move


def registry_bauen(app, config: Config) -> WerkzeugRegistry:
    """Builds the registry — not started yet, ``starten()`` is the caller's."""
    return WerkzeugRegistry(
        server_lesen(config.pfad(config.mcp.servers_file)),
        arbeitsverzeichnis=PROJEKT_WURZEL,
        oauth=getattr(app.state, "mcp_oauth", None),
        shell_an=config.features.shell_tool,
        memory_pfad=config.pfad(config.app.memory_file),
        skills_orte=config.skillverzeichnisse,
        berechtigungen_pfad=config.pfad(config.app.berechtigungen_datei),
        # The drawing tool talks to this very service's picture API and
        # hands the finished file over from the picture folder. Its own
        # session key too — being the service's own tool is
        # not an exemption from the guard every other caller meets. It is
        # reached where the service listens: bound to one address only, it
        # does not answer on 127.0.0.1.
        bild_zugang=(
            f"{own_address(config)}/api/v1",
            ort(config, "images"),
            app.state.sitzungsschluessel,
        ),
        # The video tool exists only while a video model lies in the model
        # folder — asked at each listing, because a model can arrive or the
        # folder can move while the service runs.
        video_ready=lambda: video_tool.video_model_installed(ort(config, "image_models")),
        cronjobs_repo=app.state.repositories.cronjobs,
        agenten_orte=config.agentenverzeichnisse,
        # The agents' delivery shelf (app/agentendock.py). Its folder is a
        # named storage location now, so the shelf is asked for
        # rather than built here — the user may move it while the service
        # runs, and the next delivery has to land in the new place.
        agentendock=dock_fuer(config),
        # The zone a schedule is meant in — the cronjob tool decides
        # "already in the past" in it, the firing loop reads it in it.
        zeitzone=config.app.timezone,
        # Where a cron entry's scripts live. Handed over as a
        # question rather than as an answer: unlike the picture folder above,
        # this one is a security boundary, and it is the folder as it stands
        # AT THE MOMENT OF THE CALL that decides — the user may move it from
        # the schedule list while the service is running.
        skripte_ordner=lambda: ort(config, "scripts"),
        # Where a folder `create_folder` made is stored: with the chat, or its
        # project — the path the folder chip takes.
        folder_share=create_folder.ChatFolderShare(app.state.repositories, config.datenverzeichnis),
        # A chat delivers into its own folder, and a job started from a chat
        # into that chat's, so the delivery goes with the chat; a job
        # without a chat onto the dock above.
        chat_delivery=functools.partial(
            dokumentablage.deliver_to_chat,
            app.state.repositories,
            config.datenverzeichnis,
        ),
        # Where the stored names of a server's tools are moved to the ones
        # the model is offered, once for each server.
        on_tool_list=_move_names(app, config),
    )
