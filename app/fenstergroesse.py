"""Which context window applies to an endpoint's model — one function for
the order decided for it, so no caller works it out a second way.

The first of these that has an answer wins:

1. a configured value, entered by hand;
2. a size learned from an earlier "too long" refusal
   (``app/kontextvoll.py``), remembered per endpoint and model — taken only
   where it is smaller than the window in force at that moment, whichever
   source that came from;
3. what the server itself reports (llama.cpp ``/props``, oMLX, a provider's
   own model list);
4. the shipped table of known models (``app/modellkontextgroessen.py``);
5. otherwise the fallback below.

One exception to 2 before 3: where the endpoint is on this machine or its
own network (:func:`is_local_endpoint`), the server's own answer comes first
and replaces a learned size that differs from it — such a server is
restarted with another context size under the same model name, and its
live answer is the true one.

Learned wins over the server: a provider that has already said "too long,
my limit is 32,768" is a truer answer than a larger number its model list
reports for the model in general (a plan or an account can carry a lower
limit than the model), and putting the server first would run every
following request into the very same refusal. The learned size is keyed by
endpoint and model name, so a model swapped behind the same address finds
none. A refusal only ever lowers the window, never raises it: a number
larger than the window in force is not taken. Only a configured value is
never touched by a refusal at all.

Nothing here ever asks a server or a database itself — the callers already
have to reach both for their own reasons, and handing the three numbers in
keeps this the one place the order is decided without tying it to how any
of them were obtained.
"""

from __future__ import annotations

import ipaddress
import logging
from urllib.parse import urlsplit

from app import kontextvoll
from app.db.repositories.einstellungen import GELERNTE_FENSTERGROESSEN
from app.modellkontextgroessen import nachschlagen

log = logging.getLogger(__name__)

# What most cloud models left unnamed by their provider carry today. Too low
# only costs an earlier fold; too high risks a rejected request instead —
# the safer side to guess wrong on.
ERSATZ = 128_000

# Names and ranges that are on this machine or its own network: the machine
# itself, the DNS names container runtimes give their host, and Tailscale's
# shared address range (100.64.0.0/10), which ``ipaddress`` does not count as
# private.
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "0.0.0.0")
_CONTAINER_LOCAL_SUFFIXES = (".docker.internal", ".containers.internal", ".lima.internal")
_TAILSCALE_ADDRESSES = ipaddress.IPv4Network("100.64.0.0/10")

QUELLE_EINGETRAGEN = "eingetragen"
QUELLE_SERVER = "server"
QUELLE_GELERNT = "gelernt"
QUELLE_TABELLE = "tabelle"
QUELLE_ERSATZ = "ersatz"


def is_local_endpoint(base_url: str | None) -> bool:
    """Whether this address is on this machine or its own network: loopback,
    a private or link-local address, Tailscale's shared range, a name
    without a dot (a container's service name, an entry of the hosts file)
    and ``*.local``. A name with dots that is not one of those — a provider's
    domain, a Tailscale MagicDNS name — is not, even where it leads to
    this very machine: nothing about the name says so."""
    if not base_url:
        return False
    try:
        host = urlsplit(base_url if "//" in base_url else f"//{base_url}").hostname
    except ValueError:
        return False
    if not host:
        return False
    if host in _LOCAL_HOSTS or host.endswith(_CONTAINER_LOCAL_SUFFIXES) or host.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # An IPv6 literal has no dot and was handled above as an address; a
        # name without a dot is one on this network by definition.
        return "." not in host
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or (isinstance(address, ipaddress.IPv4Address) and address in _TAILSCALE_ADDRESSES)
    )


def aufloesen(
    modell: str | None,
    *,
    eingetragen: int | None,
    server: int | None,
    gelernt: int | None,
    local: bool = False,
) -> tuple[int, str]:
    """The context window in force, and which of the five sources it came
    from — the window is never ``None``, the fallback sees to that.

    ``local`` is :func:`is_local_endpoint` of the endpoint's address: there,
    and only there, the server's own answer goes before a learned size."""
    if eingetragen:
        return eingetragen, QUELLE_EINGETRAGEN
    if server and local:
        return server, QUELLE_SERVER
    if gelernt:
        return gelernt, QUELLE_GELERNT
    if server:
        return server, QUELLE_SERVER
    tabelle = nachschlagen(modell)
    if tabelle:
        return tabelle, QUELLE_TABELLE
    return ERSATZ, QUELLE_ERSATZ


def modellschluessel(zustand) -> str | None:
    """The model a resolution for this endpoint is keyed on.

    The same reading discovery already asks the server about (the reported
    name, falling back to a configured one) — used both for the server
    question itself and for where a learned window lives, so a size learned
    from a refusal and the size a later poll looks for agree on the key.
    """
    return (
        getattr(zustand, "fenster_modell", None)
        or zustand.gemeldeter_name
        or zustand.endpunkt.modell
    )


def fuer_modell(zustand, modell: str | None, repositories) -> tuple[int, str] | None:
    """The window of one model of a catalogue, with the source it came from —
    ``None`` where the endpoint's own number is the one to use.

    That is so for the model the endpoint resolved its window for, for a
    request that names no model, and for an endpoint whose window was entered
    by hand (it holds for every model behind the address, and a refusal never
    touches it). For every other model the order of :func:`aufloesen` runs
    again, fed with what is known of THAT model: the window learned for it,
    the number the server's list names for it, the table, the fallback.
    """
    if not modell or modell == modellschluessel(zustand):
        return None
    if zustand.endpunkt.context_tokens:
        return None
    gelernt = None
    if repositories is not None:
        gelernt = _read_learned(repositories, zustand.endpunkt.id, modell)
    return aufloesen(
        modell,
        eingetragen=None,
        server=(zustand.context_per_model or {}).get(modell),
        gelernt=gelernt,
        local=is_local_endpoint(zustand.endpunkt.base_url),
    )


def _schluessel(endpoint_id: str, modell: str | None) -> str:
    return f"{endpoint_id}:{modell or ''}"


def gelernt_holen(repositories, endpoint_id: str, modell: str | None) -> int | None:
    """The window learned for this endpoint and model, or ``None``."""
    wert = repositories.einstellungen.holen(
        GELERNTE_FENSTERGROESSEN, _schluessel(endpoint_id, modell)
    )
    return wert if isinstance(wert, int) and wert > 0 else None


def _read_learned(repositories, endpoint_id: str, modell: str | None) -> int | None:
    """:func:`gelernt_holen`, where a read that fails counts as nothing
    learned — every caller still has the next source to fall back on."""
    try:
        return gelernt_holen(repositories, endpoint_id, modell)
    except Exception:  # noqa: BLE001 - a read that fails here still resolves via the next source
        log.debug("Learned window size for '%s' cannot be read", endpoint_id)
        return None


def gelernt_merken(repositories, endpoint_id: str, modell: str | None, tokens: int) -> None:
    """Remembers a window a refusal just named — never the user's own
    ``config.yaml``, which stays untouched by design (see the caller)."""
    repositories.einstellungen.setzen(
        GELERNTE_FENSTERGROESSEN, _schluessel(endpoint_id, modell), tokens
    )


def aus_fehler_lernen(repositories, zustand, fehler: BaseException) -> None:
    """Reads a window out of a "too long" refusal and applies it at once —
    one function for the chat path and the job path alike, called wherever
    ``kontextvoll.bei_fehler(fehler)`` is true.

    Keyed by :func:`modellschluessel`, the same reading a later discovery
    poll looks the learned value up under — a value learned under the
    request's own, more specific model name would sit at a key discovery
    never asks for again on a catalogue endpoint (no ``modell:`` pinned),
    and get silently discarded the very next pass.

    A no-op where a configured value is already in force: it is never
    overridden with a number read out of an error message, and the priority
    order in :func:`aufloesen` says so on its own — this check only spares
    the caller a discovery poll's wait for the very same conclusion.

    Otherwise a number is taken only where it is smaller than the window in
    force — whether that came from an earlier refusal, the server, the table
    or the fallback. A smaller number than the server's own answer is
    learned and goes before it from the next poll on, except on a local
    endpoint where the server's answer replaces it again
    (:func:`aufloesen`). Where the endpoint holds no
    window yet, the one compared against is what applies without a server:
    a window learned before, else the table, else the fallback
    (:func:`aufloesen`). A larger number is never learned.
    """
    if zustand.kontext_quelle == QUELLE_EINGETRAGEN:
        return
    tokens = kontextvoll.grenze_aus_fehler(fehler)
    if not tokens:
        return
    in_force = zustand.context_tokens
    if not in_force:
        modell = modellschluessel(zustand)
        in_force, source = aufloesen(
            modell,
            eingetragen=zustand.endpunkt.context_tokens,
            server=None,
            gelernt=_read_learned(repositories, zustand.endpunkt.id, modell),
        )
        if source == QUELLE_EINGETRAGEN:
            # A configured value is never overridden by a refusal, also
            # before discovery has written down where the window came from.
            return
    if tokens >= in_force:
        # Only a window smaller than the one in force is taken: a refusal
        # can quote a larger number that is not the window at all — vLLM's
        # "User-specified max_model_len (300000) is greater than the derived
        # max_model_len (262144)". The same number again, learned by this
        # call or an earlier retry of the same round, would only be a
        # second, identical database row.
        return
    gelernt_merken(repositories, zustand.endpunkt.id, modellschluessel(zustand), tokens)
    zustand.context_tokens = tokens
    zustand.kontext_quelle = QUELLE_GELERNT
    log.info(
        "Endpoint %s: learned context window %d from a 'too long' refusal",
        zustand.endpunkt.id,
        tokens,
        extra={"ereignis": "fenstergroesse_gelernt", "endpoint_id": zustand.endpunkt.id},
    )


async def serverseitig_aufloesen(zustand, repositories, timeout: float) -> tuple[int, str]:
    """Asks the server, reads a learned value, and resolves the window —
    the one sequence discovery's poll and the "clear this field" route both
    need, worked out once here rather than copied inline at every caller.

    ``repositories`` may be ``None`` (a Discovery built before any database
    exists) — then nothing has ever been learned, the same "nothing
    invented" reading every other unanswered source already gets.
    """
    modell = modellschluessel(zustand)
    server_wert: int | None = None
    try:
        server_wert = await zustand.provider.kontextgroesse(timeout, zustand.gemeldeter_name)
    except Exception:  # noqa: BLE001 - purely supplementary information
        log.debug("Context size of '%s' cannot be determined", zustand.endpunkt.id)
    gelernt = None
    if repositories is not None:
        gelernt = _read_learned(repositories, zustand.endpunkt.id, modell)
    return aufloesen(
        modell,
        eingetragen=zustand.endpunkt.context_tokens,
        server=server_wert,
        gelernt=gelernt,
        local=is_local_endpoint(zustand.endpunkt.base_url),
    )
