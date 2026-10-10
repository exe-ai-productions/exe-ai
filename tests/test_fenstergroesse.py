"""Which context window applies: the priority order, and remembering what a
refusal named — the two things app/fenstergroesse.py owns."""

from __future__ import annotations

import pytest

from app import fenstergroesse, kontextvoll


# --- Priority order ----------------------------------------------------------


def test_eingetragen_schlaegt_alles():
    tokens, quelle = fenstergroesse.aufloesen(
        "gpt-4o", eingetragen=4096, server=32768, gelernt=16384
    )
    assert (tokens, quelle) == (4096, fenstergroesse.QUELLE_EINGETRAGEN)


def test_server_schlaegt_gelernt():
    tokens, quelle = fenstergroesse.aufloesen(
        "gpt-4o", eingetragen=None, server=32768, gelernt=16384
    )
    assert (tokens, quelle) == (32768, fenstergroesse.QUELLE_SERVER)


def test_gelernt_schlaegt_tabelle():
    tokens, quelle = fenstergroesse.aufloesen(
        "claude-sonnet-5", eingetragen=None, server=None, gelernt=16384
    )
    assert (tokens, quelle) == (16384, fenstergroesse.QUELLE_GELERNT)


def test_tabelle_schlaegt_ersatz():
    tokens, quelle = fenstergroesse.aufloesen(
        "claude-sonnet-5", eingetragen=None, server=None, gelernt=None
    )
    assert (tokens, quelle) == (200_000, fenstergroesse.QUELLE_TABELLE)


def test_ohne_alles_kommt_der_ersatzwert():
    tokens, quelle = fenstergroesse.aufloesen(
        "ein-unbekanntes-modell", eingetragen=None, server=None, gelernt=None
    )
    assert (tokens, quelle) == (fenstergroesse.ERSATZ, fenstergroesse.QUELLE_ERSATZ)
    assert fenstergroesse.ERSATZ == 128_000


# --- Learning ------------------------------------------------------------


def test_gelernt_wird_gemerkt_und_wiedergefunden(repos):
    assert fenstergroesse.gelernt_holen(repos, "omlx", "qwen") is None
    fenstergroesse.gelernt_merken(repos, "omlx", "qwen", 32768)
    assert fenstergroesse.gelernt_holen(repos, "omlx", "qwen") == 32768


def test_gelernt_ist_je_endpunkt_und_modell(repos):
    fenstergroesse.gelernt_merken(repos, "omlx", "qwen", 32768)
    assert fenstergroesse.gelernt_holen(repos, "omlx", "anderes-modell") is None
    assert fenstergroesse.gelernt_holen(repos, "anderer-endpunkt", "qwen") is None


class _Endpunkt:
    def __init__(self, id: str, modell: str | None = None, context_tokens: int | None = None):
        self.id = id
        self.modell = modell
        self.context_tokens = context_tokens


class _Zustand:
    """A stand-in for discovery.EndpunktZustand — only the fields
    aus_fehler_lernen and modellschluessel read and write."""

    def __init__(
        self,
        endpunkt_id: str,
        kontext_quelle: str | None,
        context_tokens=None,
        gemeldeter_name: str | None = "ornith",
        modell: str | None = None,
        eingetragen: int | None = None,
        provider=None,
    ):
        self.endpunkt = _Endpunkt(endpunkt_id, modell, eingetragen)
        self.kontext_quelle = kontext_quelle
        self.context_tokens = context_tokens
        self.gemeldeter_name = gemeldeter_name
        self.provider = provider


class _Provider:
    def __init__(self, kontextgroesse: int | None = None, wirft: bool = False):
        self._kontextgroesse = kontextgroesse
        self._wirft = wirft

    async def kontextgroesse(self, timeout: float, modellname: str | None = None) -> int | None:
        if self._wirft:
            raise RuntimeError("Verbindung verweigert")
        return self._kontextgroesse


class _Refusal(Exception):
    def __init__(self, text: str, rohtext: str = ""):
        super().__init__(text)
        self.rohtext = rohtext
        self.status = 400


def test_aus_fehler_lernen_merkt_und_uebernimmt_sofort(repos):
    zustand = _Zustand("omlx", kontext_quelle=fenstergroesse.QUELLE_ERSATZ)
    fehler = _Refusal(
        'Prompt too long: 300000 tokens exceeds max context window of 65536 tokens'
    )
    fenstergroesse.aus_fehler_lernen(repos, zustand, fehler)

    assert zustand.context_tokens == 65536
    assert zustand.kontext_quelle == fenstergroesse.QUELLE_GELERNT
    assert fenstergroesse.gelernt_holen(repos, "omlx", "ornith") == 65536


def test_aus_fehler_lernen_ueberschreibt_nie_eingetragen_oder_server(repos):
    for quelle in (fenstergroesse.QUELLE_EINGETRAGEN, fenstergroesse.QUELLE_SERVER):
        zustand = _Zustand("omlx", kontext_quelle=quelle, context_tokens=8192)
        fehler = _Refusal("This model's maximum context length is 4096 tokens.")
        fenstergroesse.aus_fehler_lernen(repos, zustand, fehler)
        assert zustand.context_tokens == 8192
        assert zustand.kontext_quelle == quelle
        assert fenstergroesse.gelernt_holen(repos, "omlx", "ornith") is None


def test_aus_fehler_lernen_ohne_lesbare_zahl_tut_nichts(repos):
    zustand = _Zustand("omlx", kontext_quelle=None)
    fehler = _Refusal("Prefill memory exceeded")
    fenstergroesse.aus_fehler_lernen(repos, zustand, fehler)
    assert zustand.context_tokens is None
    assert zustand.kontext_quelle is None


# --- The model key: written and read the same way everywhere ------------


def test_modellschluessel_bevorzugt_den_gemeldeten_namen():
    zustand = _Zustand("omlx", None, gemeldeter_name="claude-opus-5", modell="konfiguriert")
    assert fenstergroesse.modellschluessel(zustand) == "claude-opus-5"


def test_modellschluessel_faellt_auf_konfiguriertes_modell_zurueck():
    zustand = _Zustand("omlx", None, gemeldeter_name=None, modell="konfiguriert")
    assert fenstergroesse.modellschluessel(zustand) == "konfiguriert"


def test_gelernte_groesse_landet_unter_dem_schluessel_den_discovery_wieder_abfragt(repos):
    """The regression this closes: a value learned for the model a refusal
    actually named used to be stored under a DIFFERENT key than the one
    discovery's own re-poll looks it up under for a catalogue endpoint (no
    ``modell:`` pinned) — silently discarding it on the very next pass.
    Both sides now go through :func:`fenstergroesse.modellschluessel`."""
    zustand = _Zustand("omlx", kontext_quelle=fenstergroesse.QUELLE_ERSATZ, gemeldeter_name="ornith")
    fehler = _Refusal("This model's maximum context length is 32768 tokens.")

    fenstergroesse.aus_fehler_lernen(repos, zustand, fehler)

    schluessel_beim_lernen = fenstergroesse.modellschluessel(zustand)
    assert fenstergroesse.gelernt_holen(repos, "omlx", schluessel_beim_lernen) == 32768


def test_jeder_gemessene_wortlaut_wird_gelernt():
    llama = kontextvoll.grenze_aus_fehler(
        _Refusal(
            'request (755 tokens) exceeds the available context size (256 tokens), '
            'try increasing it'
        )
    )
    omlx = kontextvoll.grenze_aus_fehler(
        _Refusal("Prompt too long: 300000 tokens exceeds max context window of 262144 tokens")
    )
    openai = kontextvoll.grenze_aus_fehler(
        _Refusal("This model's maximum context length is 4096 tokens.")
    )
    assert (llama, omlx, openai) == (256, 262144, 4096)


# --- vLLM's further forms ------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "max_model_len (32768)",
        "max_model_len: 32768",
        "max_model_len is 32768",
        "The engine prompt length 40000 exceeds the max_model_len 32768. Please reduce prompt.",
    ],
)
def test_vllm_forms_are_learned_over_the_fallback(repos, text):
    zustand = _Zustand(
        "vllm", kontext_quelle=fenstergroesse.QUELLE_ERSATZ, context_tokens=fenstergroesse.ERSATZ
    )
    fenstergroesse.aus_fehler_lernen(repos, zustand, _Refusal(text))

    assert zustand.context_tokens == 32768
    assert zustand.kontext_quelle == fenstergroesse.QUELLE_GELERNT
    assert fenstergroesse.gelernt_holen(repos, "vllm", "ornith") == 32768


def test_learned_then_smaller_is_learned_again(repos):
    zustand = _Zustand(
        "vllm", kontext_quelle=fenstergroesse.QUELLE_ERSATZ, context_tokens=fenstergroesse.ERSATZ
    )
    fenstergroesse.aus_fehler_lernen(repos, zustand, _Refusal("max_model_len (65536)"))
    fenstergroesse.aus_fehler_lernen(repos, zustand, _Refusal("max_model_len (32768)"))

    assert zustand.context_tokens == 32768
    assert zustand.kontext_quelle == fenstergroesse.QUELLE_GELERNT
    assert fenstergroesse.gelernt_holen(repos, "vllm", "ornith") == 32768


def test_learned_then_larger_keeps_the_learned_window(repos):
    zustand = _Zustand(
        "vllm", kontext_quelle=fenstergroesse.QUELLE_GELERNT, context_tokens=32768
    )
    fenstergroesse.gelernt_merken(repos, "vllm", "ornith", 32768)
    fenstergroesse.aus_fehler_lernen(repos, zustand, _Refusal("max_model_len (65536)"))

    assert zustand.context_tokens == 32768
    assert fenstergroesse.gelernt_holen(repos, "vllm", "ornith") == 32768


def test_without_a_known_window_a_larger_number_is_compared_with_the_fallback(repos):
    zustand = _Zustand("vllm", kontext_quelle=None, context_tokens=None)
    fehler = _Refusal(
        "User-specified max_model_len (300000) is greater than the derived "
        "max_model_len (262144)"
    )
    fenstergroesse.aus_fehler_lernen(repos, zustand, fehler)

    assert zustand.context_tokens is None
    assert zustand.kontext_quelle is None
    assert fenstergroesse.gelernt_holen(repos, "vllm", "ornith") is None


def test_without_a_known_window_a_window_learned_before_is_compared(repos):
    fenstergroesse.gelernt_merken(repos, "vllm", "ornith", 32768)
    zustand = _Zustand("vllm", kontext_quelle=None, context_tokens=None)
    fenstergroesse.aus_fehler_lernen(repos, zustand, _Refusal("max_model_len (65536)"))

    assert zustand.context_tokens is None
    assert fenstergroesse.gelernt_holen(repos, "vllm", "ornith") == 32768


def test_a_failed_read_of_the_learned_window_compares_without_it(repos, monkeypatch):
    def failing_read(*_args, **_kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(fenstergroesse, "gelernt_holen", failing_read)
    zustand = _Zustand("vllm", kontext_quelle=None, context_tokens=None)
    fenstergroesse.aus_fehler_lernen(repos, zustand, _Refusal("max_model_len (32768)"))

    assert zustand.context_tokens == 32768
    assert zustand.kontext_quelle == fenstergroesse.QUELLE_GELERNT


def test_a_configured_window_is_not_overridden_before_its_source_is_known(repos):
    zustand = _Zustand("vllm", kontext_quelle=None, context_tokens=None, eingetragen=65536)
    fenstergroesse.aus_fehler_lernen(repos, zustand, _Refusal("max_model_len (32768)"))

    assert zustand.context_tokens is None
    assert zustand.kontext_quelle is None
    assert fenstergroesse.gelernt_holen(repos, "vllm", "ornith") is None


def test_without_a_known_window_a_smaller_number_is_learned(repos):
    zustand = _Zustand("vllm", kontext_quelle=None, context_tokens=None)
    fenstergroesse.aus_fehler_lernen(repos, zustand, _Refusal("max_model_len (32768)"))

    assert zustand.context_tokens == 32768
    assert zustand.kontext_quelle == fenstergroesse.QUELLE_GELERNT


@pytest.mark.parametrize(
    "body",
    [
        "x" * 381 + "max_model_len (32768)",
        "x" * 342 + "max_tokens=70000 cannot be greater than max_model_len=32768",
    ],
)
def test_a_number_cut_off_in_the_sentence_is_read_from_the_body(body):
    """The error's own sentence carries only the first 400 characters of
    the body (``app/providers/openai_kompatibel.py``); cut there, 32768
    would read as 3276."""
    fehler = _Refusal(f"provider answered with 400: {body[:400]}", rohtext=body)
    assert kontextvoll.grenze_aus_fehler(fehler) == 32768


def test_only_the_first_match_of_a_pattern_counts():
    """A first number outside the plausible range leaves the pattern
    without a window, a later match is not looked for."""
    fehler = _Refusal("max_model_len (1000) is below what max_model_len (32768) allows")
    assert kontextvoll.grenze_aus_fehler(fehler) is None


def test_a_larger_window_from_a_vllm_refusal_is_not_learned(repos):
    zustand = _Zustand(
        "vllm", kontext_quelle=fenstergroesse.QUELLE_ERSATZ, context_tokens=fenstergroesse.ERSATZ
    )
    fehler = _Refusal(
        "User-specified max_model_len (300000) is greater than the derived "
        "max_model_len (262144)"
    )
    assert kontextvoll.grenze_aus_fehler(fehler) == 300000

    fenstergroesse.aus_fehler_lernen(repos, zustand, fehler)

    assert zustand.context_tokens == fenstergroesse.ERSATZ
    assert zustand.kontext_quelle == fenstergroesse.QUELLE_ERSATZ
    assert fenstergroesse.gelernt_holen(repos, "vllm", "ornith") is None


def test_a_larger_window_from_an_existing_wording_is_not_learned(repos):
    zustand = _Zustand(
        "omlx", kontext_quelle=fenstergroesse.QUELLE_ERSATZ, context_tokens=fenstergroesse.ERSATZ
    )
    fehler = _Refusal("Prompt too long: 300000 tokens exceeds max context window of 262144 tokens")

    fenstergroesse.aus_fehler_lernen(repos, zustand, fehler)

    assert zustand.context_tokens == fenstergroesse.ERSATZ
    assert zustand.kontext_quelle == fenstergroesse.QUELLE_ERSATZ
    assert fenstergroesse.gelernt_holen(repos, "omlx", "ornith") is None


@pytest.mark.parametrize(
    "text",
    [
        "max_model_len (1000)",
        "max_model_len: 512",
        "The engine prompt length 900 exceeds the max_model_len 800. Please reduce prompt.",
        "maximum model length 1000",
    ],
)
def test_vllm_forms_below_1024_read_nothing(text):
    assert kontextvoll.grenze_aus_fehler(_Refusal(text)) is None


def test_vllm_forms_above_ten_million_read_nothing():
    assert kontextvoll.grenze_aus_fehler(_Refusal("max_model_len (10000001)")) is None


def test_maximum_model_length_with_a_number_is_read():
    assert kontextvoll.grenze_aus_fehler(_Refusal("maximum model length 131072")) == 131072


def test_grenze_aus_fehler_ohne_treffer_ergibt_nichts():
    assert kontextvoll.grenze_aus_fehler(_Refusal("invalid_api_key")) is None


# --- The shared resolve step (discovery's poll and the "clear" route) ----


@pytest.mark.asyncio
async def test_serverseitig_aufloesen_nimmt_die_serverantwort(repos):
    zustand = _Zustand("omlx", None, provider=_Provider(kontextgroesse=32_768))
    tokens, quelle = await fenstergroesse.serverseitig_aufloesen(zustand, repos, 1.0)
    assert (tokens, quelle) == (32_768, fenstergroesse.QUELLE_SERVER)


@pytest.mark.asyncio
async def test_serverseitig_aufloesen_faellt_auf_gelernt_zurueck(repos):
    fenstergroesse.gelernt_merken(repos, "omlx", "ornith", 16_384)
    zustand = _Zustand("omlx", None, provider=_Provider(kontextgroesse=None))
    tokens, quelle = await fenstergroesse.serverseitig_aufloesen(zustand, repos, 1.0)
    assert (tokens, quelle) == (16_384, fenstergroesse.QUELLE_GELERNT)


@pytest.mark.asyncio
async def test_serverseitig_aufloesen_ohne_repository_lernt_nichts(repos):
    fenstergroesse.gelernt_merken(repos, "omlx", "ornith", 16_384)
    zustand = _Zustand("omlx", None, provider=_Provider(kontextgroesse=None))
    tokens, quelle = await fenstergroesse.serverseitig_aufloesen(zustand, None, 1.0)
    assert (tokens, quelle) == (fenstergroesse.ERSATZ, fenstergroesse.QUELLE_ERSATZ)


@pytest.mark.asyncio
async def test_serverseitig_aufloesen_uebersteht_einen_kaputten_server(repos):
    zustand = _Zustand("omlx", None, provider=_Provider(wirft=True))
    tokens, quelle = await fenstergroesse.serverseitig_aufloesen(zustand, repos, 1.0)
    assert (tokens, quelle) == (fenstergroesse.ERSATZ, fenstergroesse.QUELLE_ERSATZ)
