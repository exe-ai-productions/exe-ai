"""Every request works with the window of its own catalogue model.

An endpoint with a catalogue lists a window per model. The state discovery
keeps holds the number of the ONE model it asked the server about, and the
fold, the answer's ceiling and the document budget used to read it for every
model behind the address — while the model list showed each model its own.
A refusal "too long" learned under another model's name and lowered the
window of the whole address.

The state a request gets (``Discovery.fuer_modell``) is made for its model;
the order of sources is the one of app/fenstergroesse.py, fed with what is
known of that model.
"""

from __future__ import annotations

from app import fenstergroesse
from app.config import Config
from app.db import Database, repositories_erstellen
from app.discovery import Discovery
from app.events import EventBus
from app.providers import MockProvider, ProviderFehler, mock_endpunkt
from tests.conftest import provider_setzen
from tests.test_antwortgrenze import _anthropic_draht, _senden

CLOUD = "https://api.example.com/v1"

REFUSAL = ProviderFehler(
    "provider answered with 400: This model's maximum context length is 100000 tokens.",
    status=400,
)


def _catalogue(config: Config, base_url: str = CLOUD):
    """A discovery over one endpoint with a catalogue: the reported model
    ``mittel`` (131072, the number the endpoint resolved), and two more."""
    db = Database(":memory:")
    db.schema_einrichten()
    repositories = repositories_erstellen(db)
    discovery = Discovery(config, EventBus(), repositories)
    zustand = discovery.zustaende["test"]
    zustand.endpunkt = zustand.endpunkt.model_copy(update={"base_url": base_url})
    zustand.gemeldeter_name = "mittel"
    zustand.modelle = ["mittel", "klein", "gross"]
    zustand.context_tokens = 131_072
    zustand.kontext_quelle = fenstergroesse.QUELLE_SERVER
    zustand.context_per_model = {"mittel": 131_072, "klein": 65_536, "gross": 262_144}
    return db, repositories, discovery, zustand


def test_a_request_gets_the_window_of_its_own_model(config: Config):
    db, _, discovery, zustand = _catalogue(config)

    gross, name = discovery.aufloesen("test:gross")
    klein, _ = discovery.aufloesen("test:klein")

    assert name == "gross"
    assert (gross.context_tokens, gross.kontext_quelle) == (
        262_144, fenstergroesse.QUELLE_SERVER
    )
    assert klein.context_tokens == 65_536
    # What discovery keeps stays what it was.
    assert zustand.context_tokens == 131_072
    db.schliessen()


def test_the_list_shows_the_number_the_request_works_with(config: Config):
    db, _, discovery, _ = _catalogue(config)

    view = discovery.fuer_modell(discovery.zustaende["test"], "gross")

    assert view.als_dict("gross")["context_tokens"] == 262_144
    db.schliessen()


def test_a_refusal_lowers_the_window_of_its_model_and_no_other(config: Config):
    db, repositories, discovery, zustand = _catalogue(config)
    view, _ = discovery.aufloesen("test:gross")

    fenstergroesse.aus_fehler_lernen(repositories, view, REFUSAL)

    # The request goes on at once with the lower window …
    assert (view.context_tokens, view.kontext_quelle) == (
        100_000, fenstergroesse.QUELLE_GELERNT
    )
    # … learned for ``gross`` alone.
    assert fenstergroesse.gelernt_holen(repositories, "test", "gross") == 100_000
    assert fenstergroesse.gelernt_holen(repositories, "test", "klein") is None
    assert fenstergroesse.gelernt_holen(repositories, "test", "mittel") is None
    assert zustand.context_tokens == 131_072
    klein, _ = discovery.aufloesen("test:klein")
    assert klein.context_tokens == 65_536

    # The next request for ``gross`` and its entry in the list agree.
    again, _ = discovery.aufloesen("test:gross")
    assert (again.context_tokens, again.kontext_quelle) == (
        100_000, fenstergroesse.QUELLE_GELERNT
    )
    assert again.als_dict("gross")["context_tokens"] == 100_000
    db.schliessen()


def test_a_model_without_a_number_from_its_server_takes_the_table(config: Config):
    db, _, discovery, zustand = _catalogue(config)
    zustand.context_per_model = {"mittel": 131_072}

    # The table knows this one by name (app/modellkontextgroessen.py).
    zustand.modelle.append("claude-sonnet-4-5")
    view, _ = discovery.aufloesen("test:claude-sonnet-4-5")

    assert view.kontext_quelle == fenstergroesse.QUELLE_TABELLE
    assert view.context_tokens == fenstergroesse.nachschlagen("claude-sonnet-4-5")
    db.schliessen()


def test_silence_the_model_the_endpoint_resolved_is_the_state_itself(config: Config):
    """What is written to it still lands where discovery reads."""
    db, _, discovery, zustand = _catalogue(config)

    gefunden, name = discovery.aufloesen("test:mittel")
    ohne_modell, _ = discovery.aufloesen("test")

    assert gefunden is zustand
    assert ohne_modell is zustand
    assert name == "mittel"
    db.schliessen()


def test_silence_a_window_entered_by_hand_holds_for_every_model(config: Config):
    db, repositories, discovery, zustand = _catalogue(config)
    zustand.endpunkt = zustand.endpunkt.model_copy(update={"context_tokens": 50_000})
    zustand.context_tokens = 50_000
    zustand.kontext_quelle = fenstergroesse.QUELLE_EINGETRAGEN

    gross, _ = discovery.aufloesen("test:gross")
    fenstergroesse.aus_fehler_lernen(repositories, gross, REFUSAL)

    assert gross is zustand
    assert zustand.context_tokens == 50_000
    assert fenstergroesse.gelernt_holen(repositories, "test", "gross") is None
    db.schliessen()


def test_silence_an_endpoint_with_one_model_works_as_before(config: Config):
    db, repositories, discovery, zustand = _catalogue(config)
    zustand.modelle = ["mittel"]
    zustand.context_per_model = None

    view, _ = discovery.aufloesen("test:mittel")
    fenstergroesse.aus_fehler_lernen(repositories, view, REFUSAL)

    assert view is zustand
    assert zustand.context_tokens == 100_000
    assert fenstergroesse.gelernt_holen(repositories, "test", "mittel") == 100_000
    db.schliessen()


def test_chat_the_answer_ceiling_is_worked_out_against_the_window_of_the_model(client, chat_id):
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test")))
    _anthropic_draht(client)
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.gemeldeter_name = "mittel"
    zustand.modelle = ["mittel", "klein", "gross"]
    zustand.context_tokens = 131_072
    zustand.kontext_quelle = fenstergroesse.QUELLE_SERVER
    zustand.context_per_model = {"mittel": 131_072, "klein": 20_000, "gross": 262_144}
    zustand.hersteller_max_tokens = None

    _senden(client, chat_id, endpoint_id="test:gross")
    gross = provider.letzte_anfrage.max_tokens
    _senden(client, chat_id, endpoint_id="test:klein")
    klein = provider.letzte_anfrage.max_tokens
    _senden(client, chat_id, endpoint_id="test:mittel")
    mittel = provider.letzte_anfrage.max_tokens

    # Auto sends the most that fits: the window less what the request weighs.
    assert klein < 20_000
    assert 100_000 < mittel < 131_072
    assert 200_000 < gross < 262_144
    # Each request came from its own window, so the three ceilings differ.
    assert klein < mittel < gross
