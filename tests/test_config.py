"""Configuration: loading, validation, derived paths."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import yaml
from pydantic import BaseModel, ValidationError

from app.config import Config, EndpointConfig, config_laden


def test_mitgelieferte_config_ist_gueltig():
    """The config in place must always be loadable.

    The port is checked for being a port, not for being one particular
    number: config.yaml is not versioned, it belongs to whoever runs the
    program, and moving the service to another port is their business. What
    the number should be on a fresh install is asserted one test below, on
    the template — that file IS versioned, so a claim about it holds.
    """
    config = config_laden()
    assert 1 <= config.app.port <= 65535
    assert config.app.language in {"de", "en"}
    # Deliberately NOT "there has to be an endpoint": a fresh installation
    # has none. Providers are added in the cloud window, and a shipped file
    # that already named one would be somebody else's setup.
    assert isinstance(config.endpoints, list)


def test_die_testfixture_biegt_modellordner_auf_tmp_path_um(config, tmp_path):
    """Startup runs modellrunner.aufraeumen() against modelle_verzeichnis,
    which can delete a real .modellserver.pid note and kill a real running
    server if the test fixture left it pointing at the installed default.
    """
    assert Path(config.app.modelle_verzeichnis).is_relative_to(tmp_path)
    assert Path(config.app.bildmodelle_verzeichnis).is_relative_to(tmp_path)


def test_die_vorlage_liefert_den_hausport():
    """What a fresh installation starts on, checked where it is versioned."""
    vorlage = Path(__file__).resolve().parent.parent / "config.example.yaml"
    daten = yaml.safe_load(vorlage.read_text(encoding="utf-8"))
    assert Config.model_validate(daten).app.port == 8090


def test_die_vorlage_kennt_jeden_schluessel_des_schemas():
    """The template is the target state, like schema.sql is for the database.

    An existing config.yaml is grown from this file (app/configwanderung.py),
    so a setting that only the schema knows about would never reach anybody's
    file: it would work, and nobody could find it. Whoever adds a field to
    the model writes it in here too, with the sentence that explains it.
    """
    vorlage = Path(__file__).resolve().parent.parent / "config.example.yaml"
    daten = yaml.safe_load(vorlage.read_text(encoding="utf-8"))

    fehlend: list[str] = []
    for abschnitt, feld in Config.model_fields.items():
        if abschnitt not in daten:
            fehlend.append(abschnitt)
            continue
        unter = feld.annotation
        if not (isinstance(unter, type) and issubclass(unter, BaseModel)):
            continue
        for name in unter.model_fields:
            if name not in (daten[abschnitt] or {}):
                fehlend.append(f"{abschnitt}.{name}")

    assert not fehlend, (
        "Missing from config.example.yaml: "
        + ", ".join(fehlend)
        + " — every new key belongs in the template with an explaining comment."
    )


def test_endpunkt_kennungen_sind_eindeutig():
    with pytest.raises(ValidationError):
        Config.model_validate(
            {
                "endpoints": [
                    {"id": "doppelt", "name": "A", "base_url": "http://a"},
                    {"id": "doppelt", "name": "B", "base_url": "http://b"},
                ]
            }
        )


def test_ungueltiger_port_wird_abgewiesen():
    with pytest.raises(ValidationError):
        Config.model_validate({"app": {"port": 99999}})


def test_basis_url_ohne_schraegstrich_am_ende():
    config = Config.model_validate(
        {"endpoints": [{"id": "a", "name": "A", "base_url": "http://host:8080/v1/"}]}
    )
    assert config.endpoints[0].base_url == "http://host:8080/v1"


def test_an_address_without_a_scheme_is_read_with_http_in_front():
    config = Config.model_validate(
        {"endpoints": [{"id": "a", "name": "A", "base_url": "localhost:8080/v1"}]}
    )
    assert config.endpoints[0].base_url == "http://localhost:8080/v1"


def test_an_address_without_a_scheme_and_with_a_slash_at_the_end():
    config = Config.model_validate(
        {"endpoints": [{"id": "a", "name": "A", "base_url": "localhost:8080/v1/"}]}
    )
    assert config.endpoints[0].base_url == "http://localhost:8080/v1"


async def test_the_model_list_of_an_address_without_a_scheme_is_fetched(monkeypatch):
    """httpx refuses a URL without a scheme, so before the address was
    completed the fetch never left the machine and the list came back empty."""
    from app.providers.openai_kompatibel import OpenAIKompatiblerProvider

    asked: list[str] = []

    def handler(request):
        asked.append(str(request.url))
        return httpx.Response(200, json={"data": [{"id": "stub-model"}]})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real_client(transport=transport, **kw)
    )
    config = Config.model_validate(
        {"endpoints": [{"id": "a", "name": "A", "base_url": "localhost:8080/v1"}]}
    )

    models = await OpenAIKompatiblerProvider(config.endpoints[0]).modelle_auflisten(1.0)

    assert asked == ["http://localhost:8080/v1/models"]
    assert models == ["stub-model"]


@pytest.mark.parametrize(
    ("written", "read"),
    [
        ("https://api.openai.com/v1/", "https://api.openai.com/v1"),
        ("http://127.0.0.1:8080/v1", "http://127.0.0.1:8080/v1"),
    ],
)
def test_schweigeprobe_an_address_with_a_scheme_stays_as_written(written, read):
    config = Config.model_validate(
        {"endpoints": [{"id": "a", "name": "A", "base_url": written}]}
    )
    assert config.endpoints[0].base_url == read


def test_schweigeprobe_the_window_still_rejects_an_address_without_a_scheme(client):
    answer = client.post(
        "/api/v1/providers",
        json={
            "art": "eigen",
            "kennung": "eigene",
            "url": "localhost:8080/v1",
            "schluessel": "sk-test-1234",
        },
    )
    assert answer.status_code == 400


def test_relative_pfade_werden_absolut(config: Config):
    assert config.datenbankpfad.is_absolute()
    assert config.datenverzeichnis.is_absolute()


def test_endpunkt_nachschlagen(config: Config):
    assert config.endpunkt("test") is not None
    assert config.endpunkt("gibtsnicht") is None


def test_ein_eintrag_aus_der_konfiguration_ist_ein_anbieter():
    """An entry that says nothing about where it runs is a provider, not a
    local server: this program did not start it, and "local" is a statement
    about who started a server, not about an address."""
    config = Config.model_validate(
        {"endpoints": [{"id": "irgendwas", "base_url": "http://127.0.0.1:8080/v1"}]}
    )
    assert config.endpoints[0].group == "cloud"


def test_ein_group_local_in_der_konfiguration_zaehlt_als_cloud():
    """Even a handwritten ``group: local`` does not make an entry local.

    This is the shape both endpoints of the test service have (llama.cpp on
    this machine, the model server under a tunnel), and it is exactly the
    mixture the separation is about: one line in a file, read by the model
    picker, by the memory question and by the run's order alike, making a
    provider look like one of the program's own servers. The entry keeps
    working — it is read as the provider it is."""
    config = Config.model_validate(
        {
            "endpoints": [
                {
                    "id": "omlx",
                    "group": "local",
                    "base_url": "http://127.0.0.1:8000/v1",
                }
            ]
        }
    )
    assert config.endpoints[0].group == "cloud"


def test_die_beiden_eigenen_server_sind_lokal():
    """The other half: the main model server and the agent server carry
    ``local``, and they are the only two that may.

    They are built in code (app/api/v1/runner.py, app/agentenserver.py), so
    the rule is stated over the ids: a stranger asking for the same word is
    read as a provider."""
    from app.api.v1.runner import RUNNER_ID
    from app.agentenserver import ENDPUNKT_ID

    for kennung in (RUNNER_ID, ENDPUNKT_ID):
        endpunkt = EndpointConfig(
            id=kennung, base_url="http://127.0.0.1:8080/v1", group="local"
        )
        assert endpunkt.group == "local"

    fremd = EndpointConfig(
        id="llama-cpp", base_url="http://127.0.0.1:8080/v1", group="local"
    )
    assert fremd.group == "cloud"


def test_fehlende_datei_meldet_klar(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        config_laden(tmp_path / "nicht-vorhanden.yaml")


def test_reasoning_format_wird_geprueft(tmp_path: Path):
    datei = tmp_path / "config.yaml"
    datei.write_text(
        yaml.safe_dump(
            {
                "endpoints": [
                    {
                        "id": "a",
                        "name": "A",
                        "base_url": "http://a",
                        "reasoning_format": "quatsch",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        config_laden(datei)


def test_alle_drei_reasoning_formate_erlaubt():
    for format_name in ("native", "harmony", "think", "none"):
        config = Config.model_validate(
            {
                "endpoints": [
                    {
                        "id": format_name,
                        "name": format_name,
                        "base_url": "http://a",
                        "reasoning_format": format_name,
                    }
                ]
            }
        )
        assert config.endpoints[0].reasoning_format == format_name


def test_host_vorgabe_ist_loopback():
    # A bare schema must bind locally — the network is opt-in, never a
    # fallback.
    from app.config import AppConfig

    assert AppConfig().host == "127.0.0.1"


def test_abgelegte_schluessel_wachsen_nicht_ueber_mehrere_laeufe(tmp_path: Path):
    """What the load found is what the LAST load found.

    The note about a retired setting waits in module state until there is a
    log to write it to (``app/main.py``, ``app_erstellen``). The
    configuration, though, is read more often than an app is built — a test
    run, a repeated load — and appended to instead of replaced, the same
    finding stacked up once per read until the next report wrote it out as
    many times over.
    """
    from app import config as configmodul

    quelle = tmp_path / "config.yaml"
    quelle.write_text("app:\n  port: 8090\n  default_max_tokens: 8192\n", encoding="utf-8")

    config_laden(quelle)
    nach_dem_ersten = list(configmodul._ABGELEGTE_GEFUNDEN)
    config_laden(quelle)
    nach_dem_zweiten = list(configmodul._ABGELEGTE_GEFUNDEN)

    assert nach_dem_ersten == [(quelle, "default_max_tokens")]
    assert nach_dem_zweiten == nach_dem_ersten
