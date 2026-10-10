"""Browser sign-in for hosted MCP servers (OAuth 2.1 with PKCE).

The proof runs against a real, tiny provider inside the test process
(ASGITransport): metadata, registration, code exchange with PKCE
verification, refresh. Only the browser step itself is shortcut — the test
plays the provider that issues the code after sign-in.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from app.i18n import t
from app.tools import mcp_auth
from app.tools.mcp_auth import (
    AuthSpeicher,
    MCPAnmeldeFehler,
    OAuthVermittler,
    _pkce_paar,
)

RUECKLEITUNG = "http://127.0.0.1:8090/api/v1/tools/oauth/callback"


class Anbieter:
    """A provider with metadata, registration and token issuance.

    It actually verifies the PKCE checksum — an exchange with the wrong
    verifier is caught, just like with a real provider.
    """

    def __init__(self, mit_registrierung: bool = True) -> None:
        self.mit_registrierung = mit_registrierung
        self.registrierungen = 0
        self.ausgestellter_code: str | None = None
        self.erwartete_challenge: str | None = None
        self.erneuerungen = 0

    def app(self) -> Starlette:
        routen = [
            Route("/.well-known/oauth-protected-resource/mcp", self.ressource),
            Route("/.well-known/oauth-authorization-server", self.metadaten),
            Route("/token", self.token, methods=["POST"]),
        ]
        if self.mit_registrierung:
            routen.append(Route("/register", self.registrieren, methods=["POST"]))
        return Starlette(routes=routen)

    async def ressource(self, request: Request) -> Response:
        return JSONResponse(
            {
                "resource": "http://testserver/mcp",
                "authorization_servers": ["http://testserver"],
                "scopes_supported": ["lesen", "schreiben"],
            }
        )

    async def metadaten(self, request: Request) -> Response:
        daten = {
            "issuer": "http://testserver",
            "authorization_endpoint": "http://testserver/authorize",
            "token_endpoint": "http://testserver/token",
        }
        if self.mit_registrierung:
            daten["registration_endpoint"] = "http://testserver/register"
        return JSONResponse(daten)

    async def registrieren(self, request: Request) -> Response:
        self.registrierungen += 1
        anfrage = json.loads(await request.body())
        assert RUECKLEITUNG in anfrage["redirect_uris"]
        return JSONResponse({"client_id": "dyn-123"}, status_code=201)

    def code_ausstellen(self, anmelde_url: str) -> tuple[str, str]:
        """The shortcut browser step: reads the authorization URL and
        issues a code, bound to the PKCE checksum."""
        anfrage = parse_qs(urlsplit(anmelde_url).query)
        assert anfrage["response_type"] == ["code"]
        assert anfrage["code_challenge_method"] == ["S256"]
        assert anfrage["redirect_uri"] == [RUECKLEITUNG]
        assert anfrage["resource"] == ["http://testserver/mcp"]
        self.erwartete_challenge = anfrage["code_challenge"][0]
        self.ausgestellter_code = "code-abc"
        return anfrage["state"][0], self.ausgestellter_code

    async def token(self, request: Request) -> Response:
        felder = parse_qs((await request.body()).decode("utf-8"))
        art = felder["grant_type"][0]
        if art == "authorization_code":
            if felder["code"][0] != self.ausgestellter_code:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            pruefsumme = (
                base64.urlsafe_b64encode(
                    hashlib.sha256(felder["code_verifier"][0].encode()).digest()
                )
                .rstrip(b"=")
                .decode()
            )
            if pruefsumme != self.erwartete_challenge:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            return JSONResponse(
                {
                    "access_token": "zugang-1",
                    "refresh_token": "erneuer-1",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                }
            )
        if art == "refresh_token":
            if felder["refresh_token"][0] != "erneuer-1":
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            self.erneuerungen += 1
            return JSONResponse(
                {
                    "access_token": f"zugang-{1 + self.erneuerungen}",
                    "refresh_token": "erneuer-1",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                }
            )
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)


def vermittler(anbieter: Anbieter, tmp_path) -> OAuthVermittler:
    return OAuthVermittler(
        AuthSpeicher(tmp_path / "mcp_auth.json"),
        rueckleitung=RUECKLEITUNG,
        transport=httpx.ASGITransport(app=anbieter.app()),
    )


# --- PKCE ------------------------------------------------------------------


def test_pkce_pruefsumme_ist_s256():
    verifier, challenge = _pkce_paar()
    assert 43 <= len(verifier) <= 128
    erwartet = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert challenge == erwartet


# --- The dance -------------------------------------------------------------


async def test_anmelde_url_registriert_und_traegt_alles(tmp_path):
    anbieter = Anbieter()
    v = vermittler(anbieter, tmp_path)
    url = await v.anmelde_url("recraft", "http://testserver/mcp")

    assert anbieter.registrierungen == 1
    anfrage = parse_qs(urlsplit(url).query)
    assert anfrage["client_id"] == ["dyn-123"]
    assert anfrage["scope"] == ["lesen schreiben"]
    assert url.startswith("http://testserver/authorize?")


async def test_rueckruf_tauscht_speichert_und_schuetzt(tmp_path):
    anbieter = Anbieter()
    v = vermittler(anbieter, tmp_path)
    url = await v.anmelde_url("recraft", "http://testserver/mcp")
    state, code = anbieter.code_ausstellen(url)

    server = await v.rueckruf(state, code)
    assert server == "recraft"

    eintrag = v.speicher.eintrag("recraft")
    assert eintrag["access_token"] == "zugang-1"
    assert eintrag["refresh_token"] == "erneuer-1"
    assert eintrag["client_id"] == "dyn-123"
    assert eintrag["expires_at"] > time.time()

    # Permissions 0600 — the file belongs to the user account alone.
    if os.name == "posix":  # Windows keeps no permission bits of this kind
        rechte = stat.S_IMODE((tmp_path / "mcp_auth.json").stat().st_mode)
        assert rechte == 0o600

    # The state is single-use: the same callback goes nowhere.
    with pytest.raises(MCPAnmeldeFehler) as caught:
        await v.rueckruf(state, code)
    assert caught.value.key == "mcp_signin.unknown_flow"


async def test_falscher_state_tauscht_nichts(tmp_path):
    v = vermittler(Anbieter(), tmp_path)
    with pytest.raises(MCPAnmeldeFehler) as caught:
        await v.rueckruf("erfunden", "code-abc")
    assert caught.value.key == "mcp_signin.unknown_flow"
    assert "unbekannt oder abgelaufen" in caught.value.text("de")
    assert v.speicher.alle() == {}


async def test_handkennung_ueberspringt_registrierung(tmp_path):
    anbieter = Anbieter(mit_registrierung=False)
    v = vermittler(anbieter, tmp_path)
    url = await v.anmelde_url(
        "gmail", "http://testserver/mcp", client_id="meine-kennung"
    )
    assert anbieter.registrierungen == 0
    assert parse_qs(urlsplit(url).query)["client_id"] == ["meine-kennung"]


async def test_ohne_registrierung_und_ohne_kennung_klare_meldung(tmp_path):
    v = vermittler(Anbieter(mit_registrierung=False), tmp_path)
    with pytest.raises(MCPAnmeldeFehler) as caught:
        await v.anmelde_url("gmail", "http://testserver/mcp")
    assert caught.value.key == "mcp_signin.no_registration"
    assert "Kennung" in caught.value.text("de")


# --- Refresh ---------------------------------------------------------------


async def test_abgelaufener_zugang_wird_still_erneuert(tmp_path):
    anbieter = Anbieter()
    v = vermittler(anbieter, tmp_path)
    v.speicher.setzen(
        "recraft",
        access_token="zugang-1",
        refresh_token="erneuer-1",
        token_endpoint="http://testserver/token",
        client_id="dyn-123",
        resource="http://testserver/mcp",
        expires_at=time.time() - 10,
    )
    zugang = await v.gueltiges_token("recraft")
    assert zugang == "zugang-2"
    assert anbieter.erneuerungen == 1
    assert v.speicher.eintrag("recraft")["access_token"] == "zugang-2"


async def test_frischer_zugang_wird_nicht_angefasst(tmp_path):
    anbieter = Anbieter()
    v = vermittler(anbieter, tmp_path)
    v.speicher.setzen(
        "recraft",
        access_token="zugang-1",
        refresh_token="erneuer-1",
        token_endpoint="http://testserver/token",
        expires_at=time.time() + 3600,
    )
    assert await v.gueltiges_token("recraft") == "zugang-1"
    assert anbieter.erneuerungen == 0


async def test_ohne_erneuerungs_merkmal_kommt_none(tmp_path):
    v = vermittler(Anbieter(), tmp_path)
    v.speicher.setzen(
        "recraft", access_token="zugang-1", expires_at=time.time() - 10
    )
    assert await v.gueltiges_token("recraft") is None


async def test_unbekannter_server_kommt_none(tmp_path):
    v = vermittler(Anbieter(), tmp_path)
    assert await v.gueltiges_token("nie-gesehen") is None


async def test_vergessen_wirft_die_merkmale_weg(tmp_path):
    v = vermittler(Anbieter(), tmp_path)
    v.speicher.setzen("recraft", access_token="zugang-1")
    v.vergessen("recraft")
    assert v.speicher.eintrag("recraft") is None
    assert v.status() == {}


# --- Via the API -----------------------------------------------------------


@pytest.fixture
def http_serverdatei(config, tmp_path):
    """A registered http server without a fixed key — the OAuth case."""
    pfad = tmp_path / "mcp_servers.json"
    pfad.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "recraft": {
                        "type": "http",
                        "url": "http://testserver/mcp",
                        "enabled": True,
                    },
                    "github": {
                        "type": "http",
                        "url": "http://testserver/mcp",
                        "api_key_env": "GITHUB_TOKEN",
                        "enabled": True,
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    config.mcp.servers_file = str(pfad)
    return pfad


async def test_api_voller_tanz(client, http_serverdatei, tmp_path):
    anbieter = Anbieter()
    client.app.state.mcp_oauth = vermittler(anbieter, tmp_path)

    antwort = client.post("/api/v1/tools/oauth/start", json={"server": "recraft"})
    assert antwort.status_code == 200
    url = antwort.json()["url"]

    state, code = anbieter.code_ausstellen(url)
    rueckruf = client.get(
        "/api/v1/tools/oauth/callback", params={"state": state, "code": code}
    )
    assert rueckruf.status_code == 200
    assert "Verbunden" in rueckruf.text and "recraft" in rueckruf.text

    status = client.get("/api/v1/tools/oauth/status").json()
    assert status == [
        {
            "server": "recraft",
            "verbunden": True,
            "laeuft_ab": pytest.approx(time.time() + 3600, abs=30),
        }
    ]


async def test_api_unbekannter_server_ist_404(client, http_serverdatei, tmp_path):
    client.app.state.mcp_oauth = vermittler(Anbieter(), tmp_path)
    antwort = client.post("/api/v1/tools/oauth/start", json={"server": "erfunden"})
    assert antwort.status_code == 404


async def test_api_fester_schluessel_hat_nichts_zu_verbinden(
    client, http_serverdatei, tmp_path
):
    client.app.state.mcp_oauth = vermittler(Anbieter(), tmp_path)
    antwort = client.post("/api/v1/tools/oauth/start", json={"server": "github"})
    assert antwort.status_code == 400
    assert "GITHUB_TOKEN" in antwort.json()["detail"]


async def test_api_kaputter_rueckruf_zeigt_fehlerseite(client, tmp_path):
    client.app.state.mcp_oauth = vermittler(Anbieter(), tmp_path)
    antwort = client.get(
        "/api/v1/tools/oauth/callback", params={"state": "erfunden", "code": "x"}
    )
    assert antwort.status_code == 400
    assert "Nicht verbunden" in antwort.text


async def test_api_anbieter_lehnt_ab_zeigt_fehlerseite(client, tmp_path):
    client.app.state.mcp_oauth = vermittler(Anbieter(), tmp_path)
    antwort = client.get(
        "/api/v1/tools/oauth/callback", params={"error": "access_denied"}
    )
    assert antwort.status_code == 400
    assert "access_denied" in antwort.text


# --- The page after signing in speaks the language the sign-in was started in ---

# What the page says by itself, per language: heading and line for a sign-in
# that worked, heading and line for one that did not.
PAGE_WORDS = {
    "de": (
        "<h1>Verbunden</h1>",
        "„recraft“ ist verbunden. Dieses Fenster kann geschlossen werden.",
        "<h1>Nicht verbunden</h1>",
        "Die Anmeldung wurde nicht abgeschlossen.",
    ),
    "en": (
        "<h1>Connected</h1>",
        "“recraft” is connected. You can close this window.",
        "<h1>Not connected</h1>",
        "The sign-in did not complete.",
    ),
}
OTHER = {"de": "en", "en": "de"}


def _started(client, anbieter: Anbieter, language: str) -> tuple[str, str]:
    """A sign-in started from an interface showing `language`."""
    antwort = client.post(
        "/api/v1/tools/oauth/start",
        json={"server": "recraft"},
        headers={"X-Ui-Language": language},
    )
    assert antwort.status_code == 200
    return anbieter.code_ausstellen(antwort.json()["url"])


@pytest.mark.parametrize("language", ["de", "en"])
async def test_api_callback_page_speaks_the_language_of_the_sign_in(
    client, http_serverdatei, tmp_path, language
):
    anbieter = Anbieter()
    client.app.state.mcp_oauth = vermittler(anbieter, tmp_path)
    state, code = _started(client, anbieter, language)

    # The browser comes back from the provider's page: it says nothing of
    # the app's language, and its own may be the other one.
    seite = client.get(
        "/api/v1/tools/oauth/callback",
        params={"state": state, "code": code},
        headers={"Accept-Language": OTHER[language]},
    )
    assert seite.status_code == 200
    assert f'<html lang="{language}">' in seite.text
    heading, line, _, _ = PAGE_WORDS[language]
    assert heading in seite.text and line in seite.text
    for words in PAGE_WORDS[OTHER[language]]:
        assert words not in seite.text


@pytest.mark.parametrize("language", ["de", "en"])
async def test_api_refused_sign_in_says_so_in_the_language_of_the_sign_in(
    client, http_serverdatei, tmp_path, language
):
    """The provider refuses: the state names the flow, and with it the
    language — the reason the provider gave stands on the page as it came."""
    anbieter = Anbieter()
    client.app.state.mcp_oauth = vermittler(anbieter, tmp_path)
    state, _ = _started(client, anbieter, language)

    seite = client.get(
        "/api/v1/tools/oauth/callback",
        params={"state": state, "error": "access_denied"},
        headers={"Accept-Language": OTHER[language]},
    )
    assert seite.status_code == 400
    _, _, heading, line = PAGE_WORDS[language]
    assert heading in seite.text and line in seite.text
    reason = {"de": "Anbietermeldung: access_denied", "en": "Provider message: access_denied"}
    assert reason[language] in seite.text
    assert reason[OTHER[language]] not in seite.text
    for words in PAGE_WORDS[OTHER[language]]:
        assert words not in seite.text


@pytest.mark.parametrize("language", ["de", "en"])
async def test_api_unknown_state_takes_the_language_of_the_request(
    client, tmp_path, language
):
    """Silence probe: no flow is known under the state, so no language
    travelled — with the interface left to the device, the page takes the
    language the request itself names, and still shows one language only."""
    client.app.state.mcp_oauth = vermittler(Anbieter(), tmp_path)
    seite = client.get(
        "/api/v1/tools/oauth/callback",
        params={"state": "erfunden", "code": "x"},
        headers={"Accept-Language": language},
    )
    assert seite.status_code == 400
    _, _, heading, line = PAGE_WORDS[language]
    assert heading in seite.text and line in seite.text
    for words in PAGE_WORDS[OTHER[language]]:
        assert words not in seite.text


@pytest.mark.parametrize("language", ["de", "en"])
async def test_api_reason_on_the_page_is_said_in_the_language_too(
    client, http_serverdatei, tmp_path, language
):
    """The reason over the fixed line — the provider's refusal, a flow
    nobody knows — comes from the catalogue like the line itself."""
    anbieter = Anbieter()
    client.app.state.mcp_oauth = vermittler(anbieter, tmp_path)
    state, _ = _started(client, anbieter, language)
    refused = client.get(
        "/api/v1/tools/oauth/callback", params={"state": state, "error": "access_denied"}
    )
    assert t("mcp_signin.provider_says", language, error="access_denied") in refused.text
    assert t("mcp_signin.provider_says", OTHER[language], error="access_denied") not in refused.text

    unknown = client.get(
        "/api/v1/tools/oauth/callback",
        params={"state": "erfunden", "code": "x"},
        headers={"Accept-Language": language},
    )
    words = {
        "de": "Der Anmeldevorgang ist unbekannt oder abgelaufen — bitte erneut versuchen.",
        "en": "This sign-in has expired — please try again.",
    }
    assert words[language] in unknown.text
    assert words[OTHER[language]] not in unknown.text


@pytest.mark.parametrize("language", ["de", "en"])
async def test_api_refused_token_reaches_the_page_as_text(
    client, http_serverdatei, tmp_path, language
):
    """The provider refuses the exchange: its status and its answer stand in
    the reason, in the language of the sign-in — and the answer, which is
    the provider's to write, as text."""
    anbieter = Anbieter()
    client.app.state.mcp_oauth = vermittler(anbieter, tmp_path)
    state, _ = _started(client, anbieter, language)
    seite = client.get(
        "/api/v1/tools/oauth/callback", params={"state": state, "code": "falsch"}
    )
    assert seite.status_code == 400
    words = {
        "de": "Der Anbieter hat das Token abgelehnt (HTTP 400): ",
        "en": "The provider refused the token (HTTP 400): ",
    }
    assert words[language] + "{&quot;error&quot;:&quot;invalid_grant&quot;}" in seite.text
    assert words[OTHER[language]] not in seite.text
    assert '{"error"' not in seite.text


async def test_api_unknown_state_speaks_the_language_chosen_for_the_interface(
    client, tmp_path
):
    """No flow, so no language travelled — and the browser that comes back
    speaks the system's language, which need not be the interface's. The
    choice stored for the interface goes first."""
    client.app.state.mcp_oauth = vermittler(Anbieter(), tmp_path)
    stored = client.put("/api/v1/settings/global/sprache", json={"wert": {"sprache": "en"}})
    assert stored.status_code < 300
    seite = client.get(
        "/api/v1/tools/oauth/callback",
        params={"state": "erfunden", "code": "x"},
        headers={"Accept-Language": "de"},
    )
    assert "<h1>Not connected</h1>" in seite.text
    assert "Nicht verbunden" not in seite.text


@pytest.mark.parametrize("language", ["de", "en"])
async def test_api_start_says_why_it_failed_in_the_language_of_the_app(
    client, http_serverdatei, tmp_path, language
):
    """A provider without automatic registration: the interface shows the
    reason as a notice, so it is said in the interface's language."""
    client.app.state.mcp_oauth = vermittler(Anbieter(mit_registrierung=False), tmp_path)
    antwort = client.post(
        "/api/v1/tools/oauth/start",
        json={"server": "recraft"},
        headers={"X-Ui-Language": language},
    )
    assert antwort.status_code == 400
    reason = {
        "de": "Der Anbieter kann keine automatische Registrierung — Kennung (client_id) von Hand eintragen",
        "en": "The provider has no automatic registration — enter the client ID yourself.",
    }
    assert antwort.json()["detail"] == reason[language]


def test_every_reason_of_the_sign_in_stands_in_both_catalogues():
    """Each key a failed sign-in may name is a text of its own in both
    languages — a missing one would show the bare key on the page."""
    quelle = Path(mcp_auth.__file__).read_text(encoding="utf-8")
    keys = set(re.findall(r'MCPAnmeldeFehler\(\s*"(mcp_signin\.[a-z_]+)"', quelle))
    assert len(keys) == 7
    for key in sorted(keys | {"mcp_signin.provider_says"}):
        german, english = t(key, "de"), t(key, "en")
        assert german != key and english != key, key
        assert german != english, key


async def test_api_callback_page_writes_the_reason_as_text(client, tmp_path):
    """The provider's error word arrives in the address: it stands on the
    page as text, never as markup."""
    client.app.state.mcp_oauth = vermittler(Anbieter(), tmp_path)
    seite = client.get(
        "/api/v1/tools/oauth/callback",
        params={"error": "<script>alert(1)</script>"},
    )
    assert seite.status_code == 400
    assert "<script>" not in seite.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in seite.text


async def test_the_language_of_a_flow_is_read_without_using_the_state_up(tmp_path):
    anbieter = Anbieter()
    v = vermittler(anbieter, tmp_path)
    url = await v.anmelde_url("recraft", "http://testserver/mcp", language="en")
    state, code = anbieter.code_ausstellen(url)
    assert v.language_of(state) == "en"
    assert v.language_of(state) == "en"
    assert await v.rueckruf(state, code) == "recraft"
    # Used up with the exchange, and never known for a state nobody started.
    assert v.language_of(state) is None
    assert v.language_of("erfunden") is None


async def test_api_vergessen(client, http_serverdatei, tmp_path):
    v = vermittler(Anbieter(), tmp_path)
    v.speicher.setzen("recraft", access_token="zugang-1")
    client.app.state.mcp_oauth = v
    antwort = client.delete("/api/v1/tools/oauth/recraft")
    assert antwort.status_code == 204
    assert v.speicher.eintrag("recraft") is None
