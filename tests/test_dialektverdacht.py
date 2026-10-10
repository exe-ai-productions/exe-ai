"""An endpoint entered under a dialect its server does not speak.

The case this exists for: a local MLX server carried as ``openai``. It
answers everything, so nothing looks broken — but the thinking switch is
written in the wrong words and the model goes on thinking after it is turned
off. Measured against a running server, the same prompt gave a
210-character chain of thought with the OpenAI wording and none with the
MLX one.

Half of what is tested here is the reporting. The other half, and the more
important one, is the silence: a detector that reports on a real cloud
endpoint or on a server that is entered correctly would be worth nothing,
and would be turned off within a week.
"""

from __future__ import annotations

from app import dialektverdacht


# --- The address half ------------------------------------------------------


def test_die_eigene_maschine_wird_erkannt():
    for adresse in (
        "http://127.0.0.1:8000/v1",
        "http://localhost:1234/v1",
        "http://[::1]:8000/v1",
    ):
        assert dialektverdacht.ist_eigene_maschine(adresse), adresse


def test_eine_fremde_adresse_ist_nicht_die_eigene():
    """A server on the network may be an MLX server too, but then it is
    somebody else's and the address no longer says so."""
    for adresse in (
        "https://api.openai.com/v1",
        "https://api.anthropic.com/v1",
        "http://192.168.1.40:8000/v1",
        "http://mein-server.fritz.box:8000/v1",
    ):
        assert not dialektverdacht.ist_eigene_maschine(adresse), adresse


def test_an_address_without_a_scheme_is_read_like_everywhere_else():
    """Typed the way a hand writes it into a configuration file. The host is
    still this machine, as it is when the provider is looked up."""
    for address in ("localhost:8080/v1", "127.0.0.1:8080/v1"):
        assert dialektverdacht.ist_eigene_maschine(address), address


def test_a_foreign_address_without_a_scheme_stays_foreign():
    for address in ("api.openai.com/v1", "proxy.test/localhost/v1"):
        assert not dialektverdacht.ist_eigene_maschine(address), address


def test_the_whole_rule_reads_an_address_without_a_scheme():
    assert dialektverdacht.verdacht("openai", "localhost:8080/v1", spuren=True)


def test_a_malformed_address_is_not_this_machine():
    assert not dialektverdacht.ist_eigene_maschine("http://[::1:8080/v1")


# --- The fingerprint half --------------------------------------------------


def test_max_model_len_ist_eine_spur():
    liste = {"data": [{"id": "a"}, {"id": "b", "max_model_len": 262144}]}
    assert dialektverdacht.spuren_lesen(liste, None)


def test_ein_statusblatt_ist_eine_spur():
    assert dialektverdacht.spuren_lesen(None, [{"id": "a"}])
    assert dialektverdacht.spuren_lesen(None, {"models": [{"id": "a"}]})


def test_eine_blanke_modelliste_ist_keine_spur():
    """What a cloud catalogue looks like: ids and nothing measured."""
    liste = {"data": [{"id": "gpt-5.4", "object": "model"}]}
    assert not dialektverdacht.spuren_lesen(liste, None)
    assert not dialektverdacht.spuren_lesen(liste, {})
    assert not dialektverdacht.spuren_lesen(None, None)


# --- The whole rule --------------------------------------------------------


def test_der_fall_um_den_es_geht():
    assert dialektverdacht.verdacht("openai", "http://127.0.0.1:8000/v1", spuren=True)


def test_ein_richtig_eingetragener_server_schweigt():
    """Whoever wrote `mlx` or `llama_cpp` has thought about it. Reporting
    there would be reporting at somebody who got it right."""
    for dialekt in ("mlx", "llama_cpp"):
        assert not dialektverdacht.verdacht(
            dialekt, "http://127.0.0.1:8000/v1", spuren=True
        )


def test_ein_echter_cloud_endpunkt_schweigt():
    """The half that decides whether this is worth having at all."""
    assert not dialektverdacht.verdacht(
        "openai", "https://api.openai.com/v1", spuren=True
    )


def test_ohne_spuren_kein_verdacht():
    assert not dialektverdacht.verdacht(
        "openai", "http://127.0.0.1:8000/v1", spuren=False
    )
