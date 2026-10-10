"""Endpoint discovery and provider abstraction."""

from __future__ import annotations

import asyncio

import pytest

from app import antwortgrenze, fenstergroesse
from app.config import Config
from app.db import Database, repositories_erstellen
from app.discovery import Discovery, reasoning_effort_werte_im_template
from app.events import Ereignisse, EventBus
from app.providers import (
    MockProvider,
    ProviderFehler,
    bekannte_provider,
    mock_endpunkt,
    provider_bauen,
    provider_registrieren,
)


# --- Registry ------------------------------------------------------------


def test_bekannte_provider_enthalten_openai_und_mock():
    assert {"openai_compatible", "mock"} <= set(bekannte_provider())


def test_unbekannter_provider_meldet_sich_deutlich():
    endpunkt = mock_endpunkt("x")
    endpunkt = endpunkt.model_copy(update={"provider": "gibtsnicht"})
    with pytest.raises(ProviderFehler) as fehler:
        provider_bauen(endpunkt)
    assert "gibtsnicht" in str(fehler.value)


def test_die_erlaubten_effort_woerter_kommen_aus_der_vorlage():
    """A template that rejects any other value names the ones it accepts
    right there — the same idiom real chat templates use, only shorter."""
    schnipsel = (
        "{%- set resolved_reasoning_effort = reasoning_effort|default('xhigh') %}\n"
        "{%- if resolved_reasoning_effort not in ('xhigh', 'medium', 'low') %}\n"
        "    {{- raise_exception('Unexpected reasoning effort.') }}\n"
        "{%- endif %}\n"
    )
    assert reasoning_effort_werte_im_template(schnipsel) == ["xhigh", "medium", "low"]


# The opening of the chat template in `tokenizer_config.json` of
# mobbitxt/Kolibri-1-oQ4e, verbatim up to its stage branches: the effort is
# copied into a variable of its own and then compared in four places.
KOLIBRI_VORLAGE = (
    "{%- set _sv_reasoning_effort = reasoning_effort | default(none) -%}\n"
    "{%- set _sv_thinking_disabled = false -%}\n"
    "{%- if _sv_reasoning_effort is not none -%}\n"
    "    {%- set _sv_thinking_disabled = _sv_reasoning_effort == 'none' -%}\n"
    "{%- elif enable_thinking is defined and enable_thinking is false -%}\n"
    "    {%- set _sv_thinking_disabled = true -%}\n"
    "{%- endif -%}\n"
    "{%- set _sv_reasoning_sentence = _sv_high_reasoning_sentence -%}\n"
    "{%- if _sv_thinking_disabled -%}\n"
    "    {%- set _sv_reasoning_sentence = _sv_no_reasoning_sentence -%}\n"
    "{%- elif _sv_reasoning_effort in ['minimal', 'low'] -%}\n"
    "    {%- set _sv_reasoning_sentence = _sv_low_reasoning_sentence -%}\n"
    "{%- elif _sv_reasoning_effort == 'medium' -%}\n"
    "    {%- set _sv_reasoning_sentence = _sv_medium_reasoning_sentence -%}\n"
    "{%- elif _sv_reasoning_effort in ['high', 'xhigh', 'max'] or _sv_reasoning_effort is none -%}\n"
    "    {%- set _sv_reasoning_sentence = _sv_high_reasoning_sentence -%}\n"
    "{%- endif -%}\n"
)


def test_every_comparison_of_the_effort_counts_not_only_the_first():
    """A template that branches on its effort names its words across
    several comparisons; reading only the first one offered three of them."""
    assert reasoning_effort_werte_im_template(KOLIBRI_VORLAGE) == [
        "none", "minimal", "low", "medium", "high", "xhigh", "max",
    ]


def test_the_template_stages_reach_the_control_in_stage_order():
    """The same template without a catalogue row, through the whole lookup."""
    from app import denkstufen
    from app.config import Capabilities, EndpointConfig

    endpunkt = EndpointConfig(
        id="x", base_url="http://127.0.0.1:9/v1", parameter_dialect="llama_cpp",
        capabilities=Capabilities(),
    )
    erkannt = {"thinking": {
        "supports_reasoning_effort": None,
        "vorlage_variablen": ["reasoning_effort", "enable_thinking"],
        "effort_werte": reasoning_effort_werte_im_template(KOLIBRI_VORLAGE),
    }}
    profil = denkstufen.stufen_fuer(endpunkt, "unbenannt.gguf", erkannt)
    assert profil.stufen == ["off", "minimal", "low", "medium", "high", "xhigh", "max"]


def test_schweigeprobe_one_enumeration_reads_as_before():
    schnipsel = (
        "{%- if reasoning_effort not in ('xhigh', 'medium', 'low') %}"
        "{{- raise_exception('Unexpected reasoning effort.') }}{%- endif %}"
    )
    assert reasoning_effort_werte_im_template(schnipsel) == ["xhigh", "medium", "low"]


def test_ein_positives_in_wird_auch_gelesen():
    schnipsel = "{%- if reasoning_effort in [\"low\", \"medium\", \"high\"] %}"
    assert reasoning_effort_werte_im_template(schnipsel) == ["low", "medium", "high"]


def test_eine_vorlage_ohne_die_aufzaehlung_bleibt_ohne_antwort():
    """Nothing found means nothing invented — the caller falls back to what
    else it knows, rather than being handed a guessed list."""
    assert reasoning_effort_werte_im_template("") is None
    assert reasoning_effort_werte_im_template("{{ enable_thinking }}") is None


def test_ein_wert_mit_der_anderen_anfuehrung_wird_nicht_abgeschnitten():
    """The closing quote has to match the opening one: a double-quoted value
    carrying an apostrophe does not parse as a clean enumeration — read as
    nothing found rather than as a stage silently cut at that apostrophe."""
    schnipsel = "{%- if reasoning_effort not in (\"can't\", 'ok') %}"
    assert reasoning_effort_werte_im_template(schnipsel) is None


def test_unpassende_klammern_zaehlen_nicht_als_aufzaehlung():
    """A mismatched opening and closing delimiter is not read as a clean
    enumeration — the source itself is broken there, and hiding that behind
    a well-formed answer is worse than reporting nothing."""
    schnipsel = '{%- if reasoning_effort not in ("low", "medium"] %}'
    assert reasoning_effort_werte_im_template(schnipsel) is None


def test_neuer_provider_laesst_sich_nachtragen():
    """A new provider is one file plus one entry — no rebuild."""

    class EigenerProvider(MockProvider):
        pass

    provider_registrieren("eigener", EigenerProvider)
    endpunkt = mock_endpunkt("y").model_copy(update={"provider": "eigener"})
    assert isinstance(provider_bauen(endpunkt), EigenerProvider)


def test_faehigkeiten_kommen_aus_der_konfiguration():
    endpunkt = mock_endpunkt("z")
    provider = provider_bauen(endpunkt)
    assert provider.faehigkeiten["streaming"] is True
    # thinking arrived with the thinking switch (interface milestone A):
    # None in the config means "discovery detects it natively".
    assert set(provider.faehigkeiten) == {"streaming", "tool_calls", "vision", "thinking"}
    assert provider.faehigkeiten["thinking"] is None


# --- Discovery -----------------------------------------------------------


@pytest.fixture
def discovery(config: Config) -> Discovery:
    return Discovery(config, EventBus())


@pytest.mark.asyncio
async def test_erreichbarkeit_wird_geprueft(discovery: Discovery):
    await discovery.einmal_pruefen()
    erreichbar = {zustand.endpunkt.id for zustand in discovery.erreichbare()}
    # The dummy answers, the real endpoint on port 9 does not.
    assert erreichbar == {"test"}


@pytest.mark.asyncio
async def test_abgeschaltete_endpunkte_kommen_gar_nicht_vor(config: Config):
    config.endpoints[0].enabled = False
    discovery = Discovery(config, EventBus())
    assert "test" not in discovery.zustaende


@pytest.mark.asyncio
async def test_zustandswechsel_loest_ereignis_aus(config: Config):
    bus = EventBus()
    meldungen = []
    bus.abonnieren(
        Ereignisse.ENDPUNKT_STATUS_GEAENDERT,
        lambda **daten: meldungen.append(daten),
    )
    discovery = Discovery(config, bus)

    await discovery.einmal_pruefen()
    assert {"endpoint_id": "test", "erreichbar": True} in meldungen

    # Second pass with no change: no new notification.
    vorher = len(meldungen)
    await discovery.einmal_pruefen()
    assert len(meldungen) == vorher

    # Now the dummy goes down — and stays reachable at first. One silence is
    # not an outage: a provider whose model list hangs every other request
    # would otherwise make its models appear and vanish while you look at them.
    discovery.zustaende["test"].provider = MockProvider(ist_erreichbar=False)
    await discovery.einmal_pruefen()
    assert discovery.zustaende["test"].erreichbar, "one dropout does not throw it out yet"
    assert {"endpoint_id": "test", "erreichbar": False} not in meldungen

    # Only when the silence repeats does it count.
    await discovery.einmal_pruefen()
    await discovery.einmal_pruefen()
    assert {"endpoint_id": "test", "erreichbar": False} in meldungen


async def test_wer_nie_geantwortet_hat_gilt_nicht_als_erreichbar(config: Config):
    """The tolerance is for outages, not for endpoints that were never there.

    Without this an unconfigured provider would show up in the picker for its
    first three checks — a model you cannot talk to.
    """
    discovery = Discovery(config, EventBus())
    for zustand in discovery.zustaende.values():
        zustand.provider = MockProvider(ist_erreichbar=False)

    await discovery.einmal_pruefen()
    assert not any(z.erreichbar for z in discovery.zustaende.values())


@pytest.mark.asyncio
async def test_ein_kaputter_endpunkt_reisst_die_pruefung_nicht_mit(discovery: Discovery):
    class KaputterProvider(MockProvider):
        async def erreichbar(self, timeout: float = 3.0) -> bool:
            raise RuntimeError("Netzwerk brennt")

    discovery.zustaende["test"].provider = KaputterProvider()
    await discovery.einmal_pruefen()

    assert discovery.zustaende["test"].erreichbar is False
    assert discovery.zustaende["test"].letzter_fehler is not None
    assert "Netzwerk brennt" in discovery.zustaende["test"].letzter_fehler


@pytest.mark.asyncio
async def test_starten_und_stoppen_hinterlaesst_keine_aufgabe(discovery: Discovery):
    await discovery.starten()
    assert discovery._aufgabe is not None
    await discovery.stoppen()
    assert discovery._aufgabe is None


# --- Which context window applies (app/fenstergroesse.py) ----------------


@pytest.mark.asyncio
async def test_ohne_jede_quelle_gilt_der_ersatzwert(discovery: Discovery):
    """A reachable endpoint with no configured size, no server answer, no
    learned value and no table entry — the fallback still gives every
    reader a real window instead of ``None``."""
    await discovery.einmal_pruefen()
    zustand = discovery.zustaende["test"]
    assert zustand.context_tokens == fenstergroesse.ERSATZ
    assert zustand.kontext_quelle == fenstergroesse.QUELLE_ERSATZ


@pytest.mark.asyncio
async def test_der_server_ersetzt_den_ersatzwert_sobald_er_antwortet(discovery: Discovery):
    """The fallback is not sticky: discovery keeps asking while the source
    is not "eingetragen" or "server", so a server that starts answering
    later still wins over the fallback."""
    await discovery.einmal_pruefen()
    zustand = discovery.zustaende["test"]
    assert zustand.kontext_quelle == fenstergroesse.QUELLE_ERSATZ

    class MitFenster(MockProvider):
        async def kontextgroesse(self, timeout: float = 3.0, modellname=None):
            return 32_768

    zustand.provider = MitFenster()
    await discovery.einmal_pruefen()
    assert zustand.context_tokens == 32_768
    assert zustand.kontext_quelle == fenstergroesse.QUELLE_SERVER


@pytest.mark.asyncio
async def test_der_erste_durchgang_fragt_mit_dem_namen(discovery: Discovery):
    """A server that only finds its own model's numbers when it is asked BY
    NAME — oMLX is one — answers on the FIRST pass now: the name is fetched
    before the window, not after it. Asked without it, the
    fallback stood for one whole interval while the real number sat in the
    server's list."""

    class NurMitNamen(MockProvider):
        async def modellname(self, timeout: float = 3.0):
            return "ein-modell"

        async def kontextgroesse(self, timeout: float = 3.0, modellname=None):
            return 262_144 if modellname else None

        async def hoechste_antwort(self, timeout: float = 3.0, modellname=None):
            return 8_192 if modellname else None

    discovery.zustaende["test"].provider = NurMitNamen()

    await discovery.einmal_pruefen()

    zustand = discovery.zustaende["test"]
    assert zustand.gemeldeter_name == "ein-modell"
    assert zustand.context_tokens == 262_144
    assert zustand.kontext_quelle == fenstergroesse.QUELLE_SERVER
    assert zustand.hersteller_max_tokens == 8_192


@pytest.mark.asyncio
async def test_ein_eingetragener_name_reicht_dem_ersten_durchgang(config: Config):
    """The configured name does the same job without asking the server for
    one — on every pass, not only the first: a cloud endpoint's catalogue
    is not asked which model "the" model is, ever."""
    config.endpoints[0].modell = "aus-der-konfiguration"
    gefragt: list[str | None] = []

    class NurMitNamen(MockProvider):
        async def modellname(self, timeout: float = 3.0):
            raise AssertionError("the configured name has to win")

        async def kontextgroesse(self, timeout: float = 3.0, modellname=None):
            gefragt.append(modellname)
            return 262_144 if modellname else None

    discovery = Discovery(config, EventBus())
    discovery.zustaende["test"].provider = NurMitNamen()

    await discovery.einmal_pruefen()
    await discovery.einmal_pruefen()

    assert gefragt == ["aus-der-konfiguration"]
    assert discovery.zustaende["test"].kontext_quelle == fenstergroesse.QUELLE_SERVER


@pytest.mark.asyncio
async def test_modellwechsel_ohne_aussetzer_wird_erkannt(discovery: Discovery):
    """A local server can swap its loaded model without ever going silent
    for the three passes reachability forgives — asking for the name on
    every pass, not only while unknown, is what notices that."""
    namen = iter(["modell-a", "modell-a", "modell-b"])
    zahlen = {
        "modell-a": (8_192, 2_048, {"unterstuetzt_denken": False}),
        "modell-b": (32_768, 4_096, {"unterstuetzt_denken": True}),
    }

    class Wechselnd(MockProvider):
        async def modellname(self, timeout: float = 3.0):
            return next(namen)

        async def kontextgroesse(self, timeout: float = 3.0, modellname=None):
            return zahlen[modellname][0] if modellname else None

        async def hoechste_antwort(self, timeout: float = 3.0, modellname=None):
            return zahlen[modellname][1] if modellname else None

        async def denkquellen(self, timeout: float = 3.0):
            name = discovery.zustaende["test"].gemeldeter_name
            return dict(zahlen[name][2]) if name else {}

    discovery.zustaende["test"].provider = Wechselnd()

    await discovery.einmal_pruefen()
    zustand = discovery.zustaende["test"]
    assert zustand.gemeldeter_name == "modell-a"
    assert zustand.context_tokens == 8_192
    assert zustand.hersteller_max_tokens == 2_048
    assert (zustand.faehigkeiten_erkannt or {}).get("unterstuetzt_denken") is False

    # Schweigeprobe: same name again, nothing about the model is asked twice.
    await discovery.einmal_pruefen()
    assert zustand.gemeldeter_name == "modell-a"
    assert zustand.context_tokens == 8_192
    assert zustand.hersteller_max_tokens == 2_048

    # The server now answers as a different model, with no outage in between.
    await discovery.einmal_pruefen()
    assert zustand.gemeldeter_name == "modell-b"
    assert zustand.context_tokens == 32_768
    assert zustand.hersteller_max_tokens == 4_096
    assert (zustand.faehigkeiten_erkannt or {}).get("unterstuetzt_denken") is True


@pytest.mark.asyncio
async def test_a_catalogue_in_a_new_order_is_no_model_change(discovery: Discovery, caplog):
    """A cloud provider lists its whole catalogue, in no promised order: the
    first entry moves from pass to pass. That is no model change — nothing is
    resolved again, nothing is logged, and the name stays."""
    orders = iter([
        ["gpt-a", "gpt-b", "gpt-c"],
        ["gpt-b", "gpt-c", "gpt-a"],
        ["gpt-c", "gpt-a", "gpt-b"],
    ])
    asked: list[str | None] = []

    class Catalogue(MockProvider):
        def __init__(self):
            super().__init__()
            self.current: list[str] = []

        async def modellname(self, timeout: float = 3.0):
            self.current = next(orders)
            return self.current[0]

        async def modelle_auflisten(self, timeout: float = 3.0):
            return list(self.current)

        async def kontextgroesse(self, timeout: float = 3.0, modellname=None):
            asked.append(modellname)
            return 128_000

    discovery.zustaende["test"].provider = Catalogue()
    caplog.set_level("INFO", logger="app.discovery")

    for _ in range(3):
        await discovery.einmal_pruefen()

    state = discovery.zustaende["test"]
    assert state.gemeldeter_name == "gpt-a"
    assert asked == ["gpt-a"], "the window was resolved again for a reordered catalogue"
    assert "model changed" not in caplog.text


@pytest.mark.asyncio
async def test_a_catalogue_whose_first_list_request_failed_is_no_model_change(
    discovery: Discovery, caplog
):
    """The list request fails on the first pass, so no catalogue is on
    record yet when the first entry moves: the list is asked before a change
    is called one, and it names three models."""
    orders = iter([
        ["gpt-a", "gpt-b", "gpt-c"],
        ["gpt-b", "gpt-c", "gpt-a"],
        ["gpt-c", "gpt-a", "gpt-b"],
    ])
    lists = iter([[], ["gpt-b", "gpt-c", "gpt-a"], ["gpt-c", "gpt-a", "gpt-b"]])
    asked: list[str | None] = []

    class Flaky(MockProvider):
        async def modellname(self, timeout: float = 3.0):
            return next(orders)[0]

        async def modelle_auflisten(self, timeout: float = 3.0):
            return next(lists, ["gpt-a", "gpt-b", "gpt-c"])

        async def kontextgroesse(self, timeout: float = 3.0, modellname=None):
            asked.append(modellname)
            return 128_000

    discovery.zustaende["test"].provider = Flaky()
    caplog.set_level("INFO", logger="app.discovery")

    for _ in range(3):
        await discovery.einmal_pruefen()

    state = discovery.zustaende["test"]
    assert state.gemeldeter_name == "gpt-a"
    assert len(state.modelle) == 3
    assert asked == ["gpt-a"]
    assert "model changed" not in caplog.text


@pytest.mark.asyncio
async def test_a_server_with_one_model_still_reports_a_swap(discovery: Discovery, caplog):
    """Silence probe: a server naming exactly one model that swaps it for
    another is a model change, resolved and logged as before."""
    names = iter(["model-a", "model-a", "model-b"])
    asked: list[str | None] = []

    class Single(MockProvider):
        current = ""

        async def modellname(self, timeout: float = 3.0):
            self.current = next(names)
            return self.current

        async def modelle_auflisten(self, timeout: float = 3.0):
            return [self.current]

        async def kontextgroesse(self, timeout: float = 3.0, modellname=None):
            asked.append(modellname)
            return 8_192

    discovery.zustaende["test"].provider = Single()
    caplog.set_level("INFO", logger="app.discovery")

    for _ in range(3):
        await discovery.einmal_pruefen()

    assert discovery.zustaende["test"].gemeldeter_name == "model-b"
    assert asked == ["model-a", "model-b"]
    assert "model changed from model-a to model-b" in caplog.text


@pytest.mark.asyncio
async def test_ein_modellwechsel_laesst_das_fenster_nie_leer_stehen(discovery: Discovery):
    """A request already in flight reads `zustand` between two `await`
    points of the same pass — `context_tokens` must never read as `None`
    while `erreichbar` is still True, not even for the width of one await
    inside the re-resolution a model swap triggers itself, or the assert in
    generierung.py/auftraege.py crashes that request (review finding)."""
    namen = iter(["modell-a", "modell-b"])
    beobachtet: list[tuple[bool, int | None]] = []

    class Wechselnd(MockProvider):
        async def modellname(self, timeout: float = 3.0):
            return next(namen)

        async def kontextgroesse(self, timeout: float = 3.0, modellname=None):
            zustand = discovery.zustaende["test"]
            beobachtet.append((zustand.erreichbar, zustand.context_tokens))
            return 32_768

        async def hoechste_antwort(self, timeout: float = 3.0, modellname=None):
            return 4_096

    discovery.zustaende["test"].provider = Wechselnd()
    await discovery.einmal_pruefen()
    await discovery.einmal_pruefen()  # the model changes here

    assert beobachtet, "kontextgroesse() was never called"
    for erreichbar, tokens in beobachtet:
        if erreichbar:
            assert tokens is not None, "reachable, but the window read empty mid-pass"


@pytest.mark.asyncio
async def test_ein_leerer_name_loescht_den_bekannten_nicht(discovery: Discovery):
    """A single pass where the model name cannot be read must not blank a
    name that is still probably right — the same tolerance every other
    silent source in this file already gets."""

    class MalOhneNamen(MockProvider):
        def __init__(self):
            super().__init__()
            self.antworten = iter(["modell-a", None, None])

        async def modellname(self, timeout: float = 3.0):
            return next(self.antworten)

    discovery.zustaende["test"].provider = MalOhneNamen()

    await discovery.einmal_pruefen()
    zustand = discovery.zustaende["test"]
    assert zustand.gemeldeter_name == "modell-a"

    await discovery.einmal_pruefen()
    assert zustand.gemeldeter_name == "modell-a"
    assert zustand.context_tokens is not None, "an empty name must not delete anything"


@pytest.mark.asyncio
async def test_ohne_namensdienst_bleibt_der_durchgang_heil(discovery: Discovery):
    """A provider whose name lookup throws: the pass goes on and resolves the
    window the way it does without a name — nothing breaks."""

    class OhneNamen(MockProvider):
        async def modellname(self, timeout: float = 3.0):
            raise RuntimeError("kein Namensdienst")

    discovery.zustaende["test"].provider = OhneNamen()

    await discovery.einmal_pruefen()

    zustand = discovery.zustaende["test"]
    assert zustand.gemeldeter_name is None
    assert zustand.context_tokens == fenstergroesse.ERSATZ
    assert zustand.erreichbar is True


@pytest.mark.asyncio
async def test_eine_gelernte_groesse_schlaegt_den_ersatzwert(config: Config):
    """A window learned from an earlier refusal (app/kontextvoll.py) applies
    before the fallback, as soon as a repository is there to read it from."""
    db = Database(":memory:")
    db.schema_einrichten()
    repositories = repositories_erstellen(db)
    fenstergroesse.gelernt_merken(repositories, "test", None, 16_384)
    discovery = Discovery(config, EventBus(), repositories)

    await discovery.einmal_pruefen()

    zustand = discovery.zustaende["test"]
    assert zustand.context_tokens == 16_384
    assert zustand.kontext_quelle == fenstergroesse.QUELLE_GELERNT
    db.schliessen()


@pytest.mark.asyncio
async def test_ohne_repository_wird_nichts_gelernt(discovery: Discovery):
    """A Discovery built without one (most tests, and every call site before
    a database exists) simply never learns — the same "nothing invented"
    reading every other unanswered source already gets."""
    assert discovery.repositories is None
    await discovery.einmal_pruefen()
    assert discovery.zustaende["test"].kontext_quelle == fenstergroesse.QUELLE_ERSATZ


@pytest.mark.asyncio
async def test_erreichbar_wird_erst_nach_den_feldern_geschrieben(discovery: Discovery):
    """A reader landing in the middle of a check never sees a reachable
    endpoint whose window is not resolved yet.

    Every block of one pass asks the server something, and each of those
    awaits is a point where another request gets to run. ``erreichbar`` is
    therefore written last: written first, a request arriving during the
    window question read ``context_tokens`` as ``None`` on an endpoint that
    already called itself reachable — and a document budget then took its
    "no window" path where it never should (``app/dokumentbudget.py``).

    The reading is taken from inside that very gap: the provider holds the
    window answer open, and what the field says at that moment is what a
    parallel request would have seen.
    """
    im_fenster = asyncio.Event()
    weiter = asyncio.Event()

    class HaltendesFenster(MockProvider):
        async def kontextgroesse(self, timeout: float = 3.0, modellname=None):
            im_fenster.set()
            await weiter.wait()
            return 32_768

    zustand = discovery.zustaende["test"]
    zustand.provider = HaltendesFenster()
    assert zustand.erreichbar is False

    lauf = asyncio.create_task(discovery.einmal_pruefen())
    try:
        await asyncio.wait_for(im_fenster.wait(), timeout=10)
        waehrenddessen = (zustand.erreichbar, zustand.context_tokens)
    finally:
        weiter.set()
        await asyncio.wait_for(lauf, timeout=10)

    assert waehrenddessen == (False, None)
    # And the pass itself did what it was there for.
    assert zustand.erreichbar is True
    assert zustand.context_tokens == 32_768


@pytest.mark.asyncio
async def test_nichterreichbar_setzt_die_quelle_ebenfalls_zurueck(discovery: Discovery):
    await discovery.einmal_pruefen()
    zustand = discovery.zustaende["test"]
    assert zustand.kontext_quelle is not None

    zustand.provider = MockProvider(ist_erreichbar=False)
    for _ in range(3):
        await discovery.einmal_pruefen()

    assert zustand.erreichbar is False
    assert zustand.context_tokens is None
    assert zustand.kontext_quelle is None


# --- Capability state across a dialect re-probe (app/discovery.py) -------


@pytest.mark.asyncio
async def test_faehigkeitsstand_bleibt_bei_einer_stummen_zweiten_props_frage_stehen(
    discovery: Discovery, monkeypatch
):
    """A dialect switch's re-probe of /props can come back with no answer at
    all — the same silence ``_faehigkeiten_erkennen`` documents as ``None``,
    distinct from the settled ``{}`` "nothing here". Starting the known
    capability state fresh from a silence would blank ``tool_calls`` and
    ``vision`` for the interval until the next real answer, though nothing
    about the model has changed. A later real answer still
    writes as before — the silence probe."""
    import app.discovery as discovery_modul

    antworten = iter(
        [
            {"tool_calls": True, "vision": True},
            None,
            {"tool_calls": True, "vision": False},
        ]
    )

    async def _gefaelscht(*args, **kwargs):
        return next(antworten)

    monkeypatch.setattr(discovery_modul, "_faehigkeiten_erkennen", _gefaelscht)

    def _erkannt(zustand) -> dict:
        assert zustand.faehigkeiten_erkannt is not None
        return zustand.faehigkeiten_erkannt

    await discovery.einmal_pruefen()
    zustand = discovery.zustaende["test"]
    assert _erkannt(zustand)["tool_calls"] is True
    assert _erkannt(zustand)["vision"] is True

    # A dialect switch forces the question again.
    zustand.props_beantwortet = False
    await discovery.einmal_pruefen()
    assert _erkannt(zustand)["tool_calls"] is True
    assert _erkannt(zustand)["vision"] is True

    # And a real answer still updates the state as before.
    zustand.props_beantwortet = False
    await discovery.einmal_pruefen()
    assert _erkannt(zustand)["vision"] is False


@pytest.mark.asyncio
async def test_faehigkeitsstand_wird_nach_anhaltender_stille_doch_geleert(
    discovery: Discovery, monkeypatch
):
    """The same tolerance ``stille`` gives reachability itself: a route that
    keeps failing has stopped being a brief hiccup, and a capability (say,
    vision) must not go on being advertised forever after the server stopped
    confirming it — the next reader that gates on it (an attachment's 400
    check) would let something through the model can no longer take."""
    import app.discovery as discovery_modul
    from app.discovery import STILLE_BIS_WEG

    async def _stumm(*args, **kwargs):
        return None

    monkeypatch.setattr(
        discovery_modul, "_faehigkeiten_erkennen", lambda *a, **kw: _gefuellt()
    )

    async def _gefuellt():
        return {"tool_calls": True, "vision": True}

    await discovery.einmal_pruefen()
    zustand = discovery.zustaende["test"]
    assert zustand.faehigkeiten_erkannt is not None
    assert zustand.faehigkeiten_erkannt["vision"] is True

    monkeypatch.setattr(discovery_modul, "_faehigkeiten_erkennen", _stumm)
    for _ in range(STILLE_BIS_WEG):
        zustand.props_beantwortet = False
        await discovery.einmal_pruefen()

    assert "vision" not in (zustand.faehigkeiten_erkannt or {})


# --- /api/v1/models ------------------------------------------------------


def test_models_liefert_nur_erreichbare(client):
    daten = client.get("/api/v1/models").json()
    assert [eintrag["id"] for eintrag in daten] == ["test"]
    assert daten[0]["capabilities"]["streaming"] is True
    assert daten[0]["reasoning_format"] == "think"


def test_models_mit_alle_zeigt_auch_die_abwesenden(client):
    daten = client.get("/api/v1/models", params={"alle": True}).json()
    kennungen = {eintrag["id"]: eintrag["erreichbar"] for eintrag in daten}
    assert kennungen == {"test": True, "abwesend": False}


def test_models_kann_frisch_pruefen(client):
    daten = client.get("/api/v1/models", params={"jetzt_pruefen": True}).json()
    assert daten[0]["zuletzt_geprueft"] is not None


# --- Arriving and leaving at runtime --------------------------------------


@pytest.mark.asyncio
async def test_ein_endpunkt_kann_im_lauf_ankommen(config: Config):
    """What the window just added must not wait for a restart."""
    discovery = Discovery(config, EventBus())
    await discovery.anmelden(mock_endpunkt("spaeter"))
    assert "spaeter" in discovery.zustaende
    # The check ran right away — whoever added it is looking at the list.
    assert discovery.zustaende["spaeter"].erreichbar


@pytest.mark.asyncio
async def test_dieselbe_kennung_ersetzt_statt_zu_doppeln(config: Config):
    discovery = Discovery(config, EventBus())
    await discovery.anmelden(mock_endpunkt("runner"))
    erster = discovery.zustaende["runner"]
    await discovery.anmelden(mock_endpunkt("runner"))
    assert discovery.zustaende["runner"] is not erster
    assert sum(1 for kennung in discovery.zustaende if kennung == "runner") == 1


@pytest.mark.asyncio
async def test_abmelden_sagt_bescheid(config: Config):
    bus = EventBus()
    meldungen = []
    bus.abonnieren(
        Ereignisse.ENDPUNKT_STATUS_GEAENDERT,
        lambda **daten: meldungen.append(daten),
    )
    discovery = Discovery(config, bus)
    await discovery.anmelden(mock_endpunkt("kurz"))
    await discovery.abmelden("kurz")
    assert "kurz" not in discovery.zustaende
    assert {"endpoint_id": "kurz", "erreichbar": False} in meldungen


@pytest.mark.asyncio
async def test_abmelden_von_niemandem_ist_still(config: Config):
    discovery = Discovery(config, EventBus())
    await discovery.abmelden("gibtsnicht")


def _two_model_catalogue(windows: dict[str, int]):
    """A server listing two models, each with its own window."""

    class TwoModels(MockProvider):
        async def modellname(self, timeout: float = 3.0):
            return "qwen-4b"

        async def modelle_auflisten(self, timeout: float = 3.0):
            return ["qwen-4b", "qwen-27b"]

        async def kontextgroesse(self, timeout: float = 3.0, modellname=None):
            return windows["qwen-4b"]

        async def context_per_model(self, timeout: float = 3.0):
            return dict(windows)

    return TwoModels()


@pytest.mark.asyncio
async def test_every_catalogue_entry_carries_its_own_window(discovery: Discovery):
    """The window of the first model no longer stands for every model of the
    endpoint: each entry of the model list carries its own."""
    discovery.zustaende["test"].provider = _two_model_catalogue(
        {"qwen-4b": 262144, "qwen-27b": 131071}
    )
    await discovery.einmal_pruefen()
    state = discovery.zustaende["test"]
    assert state.als_dict("qwen-4b")["context_tokens"] == 262144
    assert state.als_dict("qwen-27b")["context_tokens"] == 131071
    assert state.als_dict("qwen-27b")["kontext_quelle"] == fenstergroesse.QUELLE_SERVER


def _catalogue_with_limits(limits: dict[str, int]):
    """The same two-model server, its model list naming an output limit for
    some of its models only."""
    provider = _two_model_catalogue({"qwen-4b": 262144, "qwen-27b": 131071})

    async def hoechste_antwort(timeout: float = 3.0, modellname=None):
        return limits.get(modellname or "")

    async def answer_limit_per_model(timeout: float = 3.0):
        return dict(limits)

    provider.hoechste_antwort = hoechste_antwort
    provider.answer_limit_per_model = answer_limit_per_model
    return provider


@pytest.mark.asyncio
async def test_a_listed_output_limit_binds_only_its_own_model(discovery: Discovery):
    """Only the reported model lists a limit: the other model of the same
    catalogue gets none — the number belongs to the model it is listed for."""
    state = discovery.zustaende["test"]
    state.provider = _catalogue_with_limits({"qwen-4b": 8_192})
    await discovery.einmal_pruefen()
    assert antwortgrenze.geltender_deckel(state, "qwen-27b") is None


@pytest.mark.asyncio
async def test_a_model_keeps_its_own_listed_output_limit(discovery: Discovery):
    """Silence probe: the model that lists a limit keeps it — the reported one
    and any other model of the catalogue with its own entry."""
    state = discovery.zustaende["test"]
    state.provider = _catalogue_with_limits({"qwen-4b": 8_192, "qwen-27b": 4_096})
    await discovery.einmal_pruefen()
    assert antwortgrenze.geltender_deckel(state, "qwen-4b") == 8_192
    assert antwortgrenze.geltender_deckel(state) == 8_192
    assert antwortgrenze.geltender_deckel(state, "qwen-27b") == 4_096


@pytest.mark.asyncio
async def test_a_window_entered_by_hand_still_wins_on_every_entry(discovery: Discovery):
    """Silence probe: a value entered for the endpoint stands on each entry."""
    state = discovery.zustaende["test"]
    state.endpunkt.context_tokens = 50_000
    state.provider = _two_model_catalogue({"qwen-4b": 262144, "qwen-27b": 131071})
    await discovery.einmal_pruefen()
    assert state.als_dict("qwen-4b")["context_tokens"] == 50_000
    assert state.als_dict("qwen-27b")["context_tokens"] == 50_000


@pytest.mark.asyncio
async def test_a_server_with_one_model_is_not_asked_per_model(discovery: Discovery):
    """Silence probe: one model, one window, as before — the per-model
    question is never put."""
    asked: list[bool] = []

    class Single(MockProvider):
        async def modellname(self, timeout: float = 3.0):
            return "only"

        async def modelle_auflisten(self, timeout: float = 3.0):
            return ["only"]

        async def kontextgroesse(self, timeout: float = 3.0, modellname=None):
            return 8_192

        async def context_per_model(self, timeout: float = 3.0):
            asked.append(True)
            return {"only": 1}

    state = discovery.zustaende["test"]
    state.provider = Single()
    await discovery.einmal_pruefen()
    assert asked == []
    assert state.als_dict()["context_tokens"] == 8_192


@pytest.mark.asyncio
async def test_an_unanswered_window_question_is_asked_again(discovery: Discovery):
    """The first answer per model went missing (`None`): the next pass asks
    again, and the numbers arrive."""
    answers = iter([None, {"qwen-4b": 262144, "qwen-27b": 131071}])
    provider = _two_model_catalogue({"qwen-4b": 262144, "qwen-27b": 131071})

    async def flaky(timeout: float = 3.0):
        return next(answers)

    provider.context_per_model = flaky
    state = discovery.zustaende["test"]
    state.provider = provider
    await discovery.einmal_pruefen()
    assert state.context_per_model is None
    await discovery.einmal_pruefen()
    assert state.als_dict("qwen-27b")["context_tokens"] == 131071


async def _templates_after_a_pass(discovery: Discovery, tmp_path, base_url: str):
    """One pass over a server naming a model folder that holds a template."""
    (tmp_path / "m").mkdir(exist_ok=True)
    (tmp_path / "m" / "chat_template.jinja").write_text(
        "reasoning_effort not in ('low', 'medium')", encoding="utf-8"
    )

    class Shelf(MockProvider):
        async def denkquellen(self, timeout: float = 3.0):
            return {"familien": {"m": "qwen3_5"}, "template_paths": {"m": str(tmp_path / "m")}}

    state = discovery.zustaende["test"]
    state.endpunkt.base_url = base_url
    state.provider = Shelf()
    await discovery.einmal_pruefen()
    return (state.faehigkeiten_erkannt or {}).get("templates")


@pytest.mark.asyncio
async def test_a_template_is_read_from_a_server_on_this_machine(discovery: Discovery, tmp_path):
    templates = await _templates_after_a_pass(discovery, tmp_path, "http://127.0.0.1:8001/v1")
    assert templates["m"]["effort_werte"] == ["low", "medium"]


@pytest.mark.asyncio
async def test_a_server_elsewhere_has_no_template_read(discovery: Discovery, tmp_path):
    """Silence probe: a path a server on another machine names is not read
    here — it may be a different file on this one."""
    templates = await _templates_after_a_pass(discovery, tmp_path, "https://remote.example.net/v1")
    assert templates is None


def test_a_single_model_server_keeps_its_limit_under_another_name():
    """A server with one model keeps no per-model list; a request that names
    its model differently from what the server reports still gets the limit."""
    from types import SimpleNamespace

    from app import antwortgrenze

    zustand = SimpleNamespace(
        gemeldeter_name="model.gguf", hersteller_max_tokens=8192,
        answer_limit_per_model=None,
    )
    assert antwortgrenze.listengrenze(zustand, "my-alias") == 8192
