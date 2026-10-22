"""Model parameters: translation, validation, storage (3.2)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app import parameter as parameter_modul
from app.config import EndpointConfig
from app.i18n import LOCALES_VERZEICHNIS, _nachschlagen
from app.parameter import (
    DIALEKTE, GRUND_ALLGEMEIN, GRUENDE, MODELL_OHNE_REASONING, NACH_NAME, NO_EFFECT_AT_OPENAI,
    PARAMETER, pruefen, uebersetzen, unterstuetzte,
)
from app.providers.openai_responses import CHAT_ONLY_FIELDS
from app.providers.openai_kompatibel import OpenAIKompatiblerProvider
from app.providers.base import ChatNachricht, Generierungsanfrage


# --- Translation ----------------------------------------------------------


def test_gleiche_funktion_heisst_je_backend_anders():
    """The heart of the matter: llama.cpp and MLX name the same thing differently."""
    werte = {"repeat_penalty": 1.1, "repeat_last_n": 128}
    assert uebersetzen("llama_cpp", werte) == {"repeat_penalty": 1.1, "repeat_last_n": 128}
    assert uebersetzen("mlx", werte) == {"repetition_penalty": 1.1, "repetition_context_size": 128}


def test_unbekanntes_faellt_beim_uebersetzen_weg():
    """Only llama.cpp knows typical_p — it must not be sent to MLX."""
    assert "typical_p" in uebersetzen("llama_cpp", {"typical_p": 0.9})
    assert uebersetzen("mlx", {"typical_p": 0.9}) == {}


def test_erfundene_namen_werden_nicht_durchgereicht():
    assert uebersetzen("llama_cpp", {"gibt_es_nicht": 5}) == {}


def test_leere_werte_werden_ausgelassen():
    assert uebersetzen("llama_cpp", {"top_k": None, "min_p": 0.05}) == {"min_p": 0.05}


def test_ganzzahlen_bleiben_ganzzahlig():
    ergebnis = uebersetzen("llama_cpp", {"top_k": 40.0, "max_tokens": 2048.0})
    assert isinstance(ergebnis["top_k"], int)
    assert isinstance(ergebnis["max_tokens"], int)


def test_unbekannter_dialekt_faellt_auf_openai_zurueck():
    ergebnis = uebersetzen("gibtsnicht", {"temperature": 0.5, "top_k": 40})
    assert ergebnis == {"temperature": 0.5}   # the common denominator doesn't know top_k


def test_jeder_dialekt_kennt_die_drei_hauptwerte():
    for name, tabelle in DIALEKTE.items():
        assert {"temperature", "top_p", "max_tokens"} <= set(tabelle), name


def test_alle_dialekt_eintraege_sind_bekannte_parameter():
    for name, tabelle in DIALEKTE.items():
        unbekannt = set(tabelle) - set(NACH_NAME)
        assert not unbekannt, f"{name}: {unbekannt}"


# --- Validation -----------------------------------------------------------


def test_werte_werden_auf_ihren_bereich_begrenzt():
    assert pruefen({"temperature": 99})["temperature"] == 2
    assert pruefen({"temperature": -5})["temperature"] == 0
    assert pruefen({"top_p": 3})["top_p"] == 1


def test_unsinn_wird_verworfen():
    assert pruefen({"temperature": "heiß"}) == {}
    assert pruefen({"erfunden": 1}) == {}
    assert pruefen({"top_k": None}) == {}


def test_unterstuetzte_liste_haelt_die_reihenfolge():
    namen = [p.name for p in unterstuetzte("llama_cpp")]
    assert namen[:3] == ["temperature", "top_p", "max_tokens"]
    assert all(p.gruppe == "sichtbar" for p in unterstuetzte("llama_cpp")[:3])


def test_mlx_hat_kein_typical_p():
    assert "typical_p" not in [p.name for p in unterstuetzte("mlx")]
    assert "typical_p" in [p.name for p in unterstuetzte("llama_cpp")]


def test_jeder_parameter_hat_einen_sinnvollen_bereich():
    for p in PARAMETER:
        assert p.minimum < p.maximum


# --- The texts live in the catalogues, the rows say the same as before -----

# What the rows said, word for word, before their texts moved out of this
# module into the catalogues: every row of the list per dialect and per
# situation, in both languages, as the window and the CLI receive them.
_VORHER = json.loads('''
{
  "frei_llama_cpp": {
    "de": [
      {"name": "temperature", "label": "Temperatur", "hinweis": "Wie frei das Modell seine Antworten formuliert", "minimum": 0, "maximum": 2, "schritt": 0.05, "gruppe": "sichtbar", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "top_p", "label": "Top-P", "hinweis": "Umfang der zugelassenen Wortauswahl", "minimum": 0, "maximum": 1, "schritt": 0.01, "gruppe": "sichtbar", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "max_tokens", "label": "Antwortlänge", "hinweis": "Höchstzahl an Token", "minimum": 256, "maximum": 1000000, "schritt": 256, "gruppe": "sichtbar", "ganzzahl": true, "aktiv": true, "grund": null},
      {"name": "reasoning_budget", "label": "Denklänge", "hinweis": "Wie lange das Modell vor der Antwort nachdenken darf", "minimum": -1, "maximum": 1000000, "schritt": 256, "gruppe": "sichtbar", "ganzzahl": true, "aktiv": true, "grund": null},
      {"name": "top_k", "label": "Top-K", "hinweis": "Nur die K wahrscheinlichsten Wörter; 0 deaktiviert diese Begrenzung.", "minimum": 0, "maximum": 200, "schritt": 1, "gruppe": "mehr", "ganzzahl": true, "aktiv": true, "grund": null},
      {"name": "min_p", "label": "Min-P", "hinweis": "Schließt unwahrscheinliche Wörter aus", "minimum": 0, "maximum": 1, "schritt": 0.01, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "repeat_penalty", "label": "Wiederholungsbremse", "hinweis": "1,0 deaktiviert die Wiederholungsbremse.", "minimum": 1, "maximum": 2, "schritt": 0.01, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "repeat_last_n", "label": "Bremse wirkt auf", "hinweis": "Anzahl der vorhergehenden Token, die berücksichtigt werden", "minimum": 0, "maximum": 2048, "schritt": 16, "gruppe": "mehr", "ganzzahl": true, "aktiv": true, "grund": null},
      {"name": "presence_penalty", "label": "Themenwechsel", "hinweis": "Höhere Werte begünstigen neue Themen.", "minimum": -2, "maximum": 2, "schritt": 0.05, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "frequency_penalty", "label": "Wortwiederholung", "hinweis": "Höhere Werte verringern Wortwiederholungen.", "minimum": -2, "maximum": 2, "schritt": 0.05, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "typical_p", "label": "Typical-P", "hinweis": "Bevorzugt erwartbare Formulierungen", "minimum": 0, "maximum": 1, "schritt": 0.01, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "seed", "label": "Startwert", "hinweis": "Derselbe Wert erzeugt dieselbe Antwort. -1 wählt einen zufälligen Wert.", "minimum": -1, "maximum": 2147483647, "schritt": 1, "gruppe": "mehr", "ganzzahl": true, "aktiv": true, "grund": null}
    ],
    "en": [
      {"name": "temperature", "label": "Temperature", "hinweis": "How freely the model phrases its responses", "minimum": 0, "maximum": 2, "schritt": 0.05, "gruppe": "sichtbar", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "top_p", "label": "Top-P", "hinweis": "Range of permitted word choices", "minimum": 0, "maximum": 1, "schritt": 0.01, "gruppe": "sichtbar", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "max_tokens", "label": "Response length", "hinweis": "Maximum number of tokens", "minimum": 256, "maximum": 1000000, "schritt": 256, "gruppe": "sichtbar", "ganzzahl": true, "aktiv": true, "grund": null},
      {"name": "reasoning_budget", "label": "Thinking length", "hinweis": "How long the model may reason before responding", "minimum": -1, "maximum": 1000000, "schritt": 256, "gruppe": "sichtbar", "ganzzahl": true, "aktiv": true, "grund": null},
      {"name": "top_k", "label": "Top-K", "hinweis": "Only the top K words; 0 disables this limit.", "minimum": 0, "maximum": 200, "schritt": 1, "gruppe": "mehr", "ganzzahl": true, "aktiv": true, "grund": null},
      {"name": "min_p", "label": "Min-P", "hinweis": "Excludes unlikely words", "minimum": 0, "maximum": 1, "schritt": 0.01, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "repeat_penalty", "label": "Repetition penalty", "hinweis": "1.0 disables the penalty.", "minimum": 1, "maximum": 2, "schritt": 0.01, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "repeat_last_n", "label": "Penalty window", "hinweis": "Number of preceding tokens considered", "minimum": 0, "maximum": 2048, "schritt": 16, "gruppe": "mehr", "ganzzahl": true, "aktiv": true, "grund": null},
      {"name": "presence_penalty", "label": "Presence penalty", "hinweis": "Higher values encourage new topics.", "minimum": -2, "maximum": 2, "schritt": 0.05, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "frequency_penalty", "label": "Frequency penalty", "hinweis": "Higher values reduce word repetition.", "minimum": -2, "maximum": 2, "schritt": 0.05, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "typical_p", "label": "Typical-P", "hinweis": "Prefers expected phrasing", "minimum": 0, "maximum": 1, "schritt": 0.01, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "seed", "label": "Seed", "hinweis": "The same value produces the same response. -1 selects a random value.", "minimum": -1, "maximum": 2147483647, "schritt": 1, "gruppe": "mehr", "ganzzahl": true, "aktiv": true, "grund": null}
    ]
  },
  "mlx": {
    "de": [
      {"name": "temperature", "label": "Temperatur", "hinweis": "Wie frei das Modell seine Antworten formuliert", "minimum": 0, "maximum": 2, "schritt": 0.05, "gruppe": "sichtbar", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "top_p", "label": "Top-P", "hinweis": "Umfang der zugelassenen Wortauswahl", "minimum": 0, "maximum": 1, "schritt": 0.01, "gruppe": "sichtbar", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "max_tokens", "label": "Antwortlänge", "hinweis": "Höchstzahl an Token", "minimum": 256, "maximum": 1000000, "schritt": 256, "gruppe": "sichtbar", "ganzzahl": true, "aktiv": true, "grund": null},
      {"name": "reasoning_budget", "label": "Denklänge", "hinweis": "Wie lange das Modell vor der Antwort nachdenken darf", "minimum": -1, "maximum": 1000000, "schritt": 256, "gruppe": "sichtbar", "ganzzahl": true, "aktiv": false, "grund": "Dieser Server unterstützt keine einstellbare Denklänge."},
      {"name": "top_k", "label": "Top-K", "hinweis": "Nur die K wahrscheinlichsten Wörter; 0 deaktiviert diese Begrenzung.", "minimum": 0, "maximum": 200, "schritt": 1, "gruppe": "mehr", "ganzzahl": true, "aktiv": true, "grund": null},
      {"name": "min_p", "label": "Min-P", "hinweis": "Schließt unwahrscheinliche Wörter aus", "minimum": 0, "maximum": 1, "schritt": 0.01, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "repeat_penalty", "label": "Wiederholungsbremse", "hinweis": "1,0 deaktiviert die Wiederholungsbremse.", "minimum": 1, "maximum": 2, "schritt": 0.01, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "repeat_last_n", "label": "Bremse wirkt auf", "hinweis": "Anzahl der vorhergehenden Token, die berücksichtigt werden", "minimum": 0, "maximum": 2048, "schritt": 16, "gruppe": "mehr", "ganzzahl": true, "aktiv": true, "grund": null},
      {"name": "presence_penalty", "label": "Themenwechsel", "hinweis": "Höhere Werte begünstigen neue Themen.", "minimum": -2, "maximum": 2, "schritt": 0.05, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "frequency_penalty", "label": "Wortwiederholung", "hinweis": "Höhere Werte verringern Wortwiederholungen.", "minimum": -2, "maximum": 2, "schritt": 0.05, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "seed", "label": "Startwert", "hinweis": "Derselbe Wert erzeugt dieselbe Antwort. -1 wählt einen zufälligen Wert.", "minimum": -1, "maximum": 2147483647, "schritt": 1, "gruppe": "mehr", "ganzzahl": true, "aktiv": true, "grund": null}
    ],
    "en": [
      {"name": "temperature", "label": "Temperature", "hinweis": "How freely the model phrases its responses", "minimum": 0, "maximum": 2, "schritt": 0.05, "gruppe": "sichtbar", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "top_p", "label": "Top-P", "hinweis": "Range of permitted word choices", "minimum": 0, "maximum": 1, "schritt": 0.01, "gruppe": "sichtbar", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "max_tokens", "label": "Response length", "hinweis": "Maximum number of tokens", "minimum": 256, "maximum": 1000000, "schritt": 256, "gruppe": "sichtbar", "ganzzahl": true, "aktiv": true, "grund": null},
      {"name": "reasoning_budget", "label": "Thinking length", "hinweis": "How long the model may reason before responding", "minimum": -1, "maximum": 1000000, "schritt": 256, "gruppe": "sichtbar", "ganzzahl": true, "aktiv": false, "grund": "This server does not support a configurable thinking length."},
      {"name": "top_k", "label": "Top-K", "hinweis": "Only the top K words; 0 disables this limit.", "minimum": 0, "maximum": 200, "schritt": 1, "gruppe": "mehr", "ganzzahl": true, "aktiv": true, "grund": null},
      {"name": "min_p", "label": "Min-P", "hinweis": "Excludes unlikely words", "minimum": 0, "maximum": 1, "schritt": 0.01, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "repeat_penalty", "label": "Repetition penalty", "hinweis": "1.0 disables the penalty.", "minimum": 1, "maximum": 2, "schritt": 0.01, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "repeat_last_n", "label": "Penalty window", "hinweis": "Number of preceding tokens considered", "minimum": 0, "maximum": 2048, "schritt": 16, "gruppe": "mehr", "ganzzahl": true, "aktiv": true, "grund": null},
      {"name": "presence_penalty", "label": "Presence penalty", "hinweis": "Higher values encourage new topics.", "minimum": -2, "maximum": 2, "schritt": 0.05, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "frequency_penalty", "label": "Frequency penalty", "hinweis": "Higher values reduce word repetition.", "minimum": -2, "maximum": 2, "schritt": 0.05, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "seed", "label": "Seed", "hinweis": "The same value produces the same response. -1 selects a random value.", "minimum": -1, "maximum": 2147483647, "schritt": 1, "gruppe": "mehr", "ganzzahl": true, "aktiv": true, "grund": null}
    ]
  },
  "openai": {
    "de": [
      {"name": "temperature", "label": "Temperatur", "hinweis": "Wie frei das Modell seine Antworten formuliert", "minimum": 0, "maximum": 2, "schritt": 0.05, "gruppe": "sichtbar", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "top_p", "label": "Top-P", "hinweis": "Umfang der zugelassenen Wortauswahl", "minimum": 0, "maximum": 1, "schritt": 0.01, "gruppe": "sichtbar", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "max_tokens", "label": "Antwortlänge", "hinweis": "Höchstzahl an Token", "minimum": 256, "maximum": 1000000, "schritt": 256, "gruppe": "sichtbar", "ganzzahl": true, "aktiv": true, "grund": null},
      {"name": "reasoning_budget", "label": "Denklänge", "hinweis": "Wie lange das Modell vor der Antwort nachdenken darf", "minimum": -1, "maximum": 1000000, "schritt": 256, "gruppe": "sichtbar", "ganzzahl": true, "aktiv": false, "grund": "Dieser Server unterstützt keine einstellbare Denklänge."},
      {"name": "presence_penalty", "label": "Themenwechsel", "hinweis": "Höhere Werte begünstigen neue Themen.", "minimum": -2, "maximum": 2, "schritt": 0.05, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "frequency_penalty", "label": "Wortwiederholung", "hinweis": "Höhere Werte verringern Wortwiederholungen.", "minimum": -2, "maximum": 2, "schritt": 0.05, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "seed", "label": "Startwert", "hinweis": "Derselbe Wert erzeugt dieselbe Antwort. -1 wählt einen zufälligen Wert.", "minimum": -1, "maximum": 2147483647, "schritt": 1, "gruppe": "mehr", "ganzzahl": true, "aktiv": true, "grund": null}
    ],
    "en": [
      {"name": "temperature", "label": "Temperature", "hinweis": "How freely the model phrases its responses", "minimum": 0, "maximum": 2, "schritt": 0.05, "gruppe": "sichtbar", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "top_p", "label": "Top-P", "hinweis": "Range of permitted word choices", "minimum": 0, "maximum": 1, "schritt": 0.01, "gruppe": "sichtbar", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "max_tokens", "label": "Response length", "hinweis": "Maximum number of tokens", "minimum": 256, "maximum": 1000000, "schritt": 256, "gruppe": "sichtbar", "ganzzahl": true, "aktiv": true, "grund": null},
      {"name": "reasoning_budget", "label": "Thinking length", "hinweis": "How long the model may reason before responding", "minimum": -1, "maximum": 1000000, "schritt": 256, "gruppe": "sichtbar", "ganzzahl": true, "aktiv": false, "grund": "This server does not support a configurable thinking length."},
      {"name": "presence_penalty", "label": "Presence penalty", "hinweis": "Higher values encourage new topics.", "minimum": -2, "maximum": 2, "schritt": 0.05, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "frequency_penalty", "label": "Frequency penalty", "hinweis": "Higher values reduce word repetition.", "minimum": -2, "maximum": 2, "schritt": 0.05, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "seed", "label": "Seed", "hinweis": "The same value produces the same response. -1 selects a random value.", "minimum": -1, "maximum": 2147483647, "schritt": 1, "gruppe": "mehr", "ganzzahl": true, "aktiv": true, "grund": null}
    ]
  },
  "anthropic": {
    "de": [
      {"name": "temperature", "label": "Temperatur", "hinweis": "Wie frei das Modell seine Antworten formuliert", "minimum": 0, "maximum": 1, "schritt": 0.05, "gruppe": "sichtbar", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "top_p", "label": "Top-P", "hinweis": "Umfang der zugelassenen Wortauswahl", "minimum": 0, "maximum": 1, "schritt": 0.01, "gruppe": "sichtbar", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "max_tokens", "label": "Antwortlänge", "hinweis": "Höchstzahl an Token", "minimum": 256, "maximum": 1000000, "schritt": 256, "gruppe": "sichtbar", "ganzzahl": true, "aktiv": true, "grund": null},
      {"name": "reasoning_budget", "label": "Denklänge", "hinweis": "Wie lange das Modell vor der Antwort nachdenken darf", "minimum": -1, "maximum": 1000000, "schritt": 256, "gruppe": "sichtbar", "ganzzahl": true, "aktiv": false, "grund": "Dieser Server unterstützt keine einstellbare Denklänge."},
      {"name": "top_k", "label": "Top-K", "hinweis": "Nur die K wahrscheinlichsten Wörter; 0 deaktiviert diese Begrenzung.", "minimum": 0, "maximum": 200, "schritt": 1, "gruppe": "mehr", "ganzzahl": true, "aktiv": true, "grund": null}
    ],
    "en": [
      {"name": "temperature", "label": "Temperature", "hinweis": "How freely the model phrases its responses", "minimum": 0, "maximum": 1, "schritt": 0.05, "gruppe": "sichtbar", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "top_p", "label": "Top-P", "hinweis": "Range of permitted word choices", "minimum": 0, "maximum": 1, "schritt": 0.01, "gruppe": "sichtbar", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "max_tokens", "label": "Response length", "hinweis": "Maximum number of tokens", "minimum": 256, "maximum": 1000000, "schritt": 256, "gruppe": "sichtbar", "ganzzahl": true, "aktiv": true, "grund": null},
      {"name": "reasoning_budget", "label": "Thinking length", "hinweis": "How long the model may reason before responding", "minimum": -1, "maximum": 1000000, "schritt": 256, "gruppe": "sichtbar", "ganzzahl": true, "aktiv": false, "grund": "This server does not support a configurable thinking length."},
      {"name": "top_k", "label": "Top-K", "hinweis": "Only the top K words; 0 disables this limit.", "minimum": 0, "maximum": 200, "schritt": 1, "gruppe": "mehr", "ganzzahl": true, "aktiv": true, "grund": null}
    ]
  },
  "modell_ohne_reasoning": {
    "de": [
      {"name": "temperature", "label": "Temperatur", "hinweis": "Wie frei das Modell seine Antworten formuliert", "minimum": 0, "maximum": 2, "schritt": 0.05, "gruppe": "sichtbar", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "top_p", "label": "Top-P", "hinweis": "Umfang der zugelassenen Wortauswahl", "minimum": 0, "maximum": 1, "schritt": 0.01, "gruppe": "sichtbar", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "max_tokens", "label": "Antwortlänge", "hinweis": "Höchstzahl an Token", "minimum": 256, "maximum": 1000000, "schritt": 256, "gruppe": "sichtbar", "ganzzahl": true, "aktiv": true, "grund": null},
      {"name": "reasoning_budget", "label": "Denklänge", "hinweis": "Wie lange das Modell vor der Antwort nachdenken darf", "minimum": -1, "maximum": 1000000, "schritt": 256, "gruppe": "sichtbar", "ganzzahl": true, "aktiv": false, "grund": "Dieses Modell unterstützt kein Reasoning. Daher lässt sich keine Denklänge einstellen."},
      {"name": "top_k", "label": "Top-K", "hinweis": "Nur die K wahrscheinlichsten Wörter; 0 deaktiviert diese Begrenzung.", "minimum": 0, "maximum": 200, "schritt": 1, "gruppe": "mehr", "ganzzahl": true, "aktiv": true, "grund": null},
      {"name": "min_p", "label": "Min-P", "hinweis": "Schließt unwahrscheinliche Wörter aus", "minimum": 0, "maximum": 1, "schritt": 0.01, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "repeat_penalty", "label": "Wiederholungsbremse", "hinweis": "1,0 deaktiviert die Wiederholungsbremse.", "minimum": 1, "maximum": 2, "schritt": 0.01, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "repeat_last_n", "label": "Bremse wirkt auf", "hinweis": "Anzahl der vorhergehenden Token, die berücksichtigt werden", "minimum": 0, "maximum": 2048, "schritt": 16, "gruppe": "mehr", "ganzzahl": true, "aktiv": true, "grund": null},
      {"name": "presence_penalty", "label": "Themenwechsel", "hinweis": "Höhere Werte begünstigen neue Themen.", "minimum": -2, "maximum": 2, "schritt": 0.05, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "frequency_penalty", "label": "Wortwiederholung", "hinweis": "Höhere Werte verringern Wortwiederholungen.", "minimum": -2, "maximum": 2, "schritt": 0.05, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "typical_p", "label": "Typical-P", "hinweis": "Bevorzugt erwartbare Formulierungen", "minimum": 0, "maximum": 1, "schritt": 0.01, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "seed", "label": "Startwert", "hinweis": "Derselbe Wert erzeugt dieselbe Antwort. -1 wählt einen zufälligen Wert.", "minimum": -1, "maximum": 2147483647, "schritt": 1, "gruppe": "mehr", "ganzzahl": true, "aktiv": true, "grund": null}
    ],
    "en": [
      {"name": "temperature", "label": "Temperature", "hinweis": "How freely the model phrases its responses", "minimum": 0, "maximum": 2, "schritt": 0.05, "gruppe": "sichtbar", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "top_p", "label": "Top-P", "hinweis": "Range of permitted word choices", "minimum": 0, "maximum": 1, "schritt": 0.01, "gruppe": "sichtbar", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "max_tokens", "label": "Response length", "hinweis": "Maximum number of tokens", "minimum": 256, "maximum": 1000000, "schritt": 256, "gruppe": "sichtbar", "ganzzahl": true, "aktiv": true, "grund": null},
      {"name": "reasoning_budget", "label": "Thinking length", "hinweis": "How long the model may reason before responding", "minimum": -1, "maximum": 1000000, "schritt": 256, "gruppe": "sichtbar", "ganzzahl": true, "aktiv": false, "grund": "This model does not support reasoning, so its thinking length cannot be configured."},
      {"name": "top_k", "label": "Top-K", "hinweis": "Only the top K words; 0 disables this limit.", "minimum": 0, "maximum": 200, "schritt": 1, "gruppe": "mehr", "ganzzahl": true, "aktiv": true, "grund": null},
      {"name": "min_p", "label": "Min-P", "hinweis": "Excludes unlikely words", "minimum": 0, "maximum": 1, "schritt": 0.01, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "repeat_penalty", "label": "Repetition penalty", "hinweis": "1.0 disables the penalty.", "minimum": 1, "maximum": 2, "schritt": 0.01, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "repeat_last_n", "label": "Penalty window", "hinweis": "Number of preceding tokens considered", "minimum": 0, "maximum": 2048, "schritt": 16, "gruppe": "mehr", "ganzzahl": true, "aktiv": true, "grund": null},
      {"name": "presence_penalty", "label": "Presence penalty", "hinweis": "Higher values encourage new topics.", "minimum": -2, "maximum": 2, "schritt": 0.05, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "frequency_penalty", "label": "Frequency penalty", "hinweis": "Higher values reduce word repetition.", "minimum": -2, "maximum": 2, "schritt": 0.05, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "typical_p", "label": "Typical-P", "hinweis": "Prefers expected phrasing", "minimum": 0, "maximum": 1, "schritt": 0.01, "gruppe": "mehr", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "seed", "label": "Seed", "hinweis": "The same value produces the same response. -1 selects a random value.", "minimum": -1, "maximum": 2147483647, "schritt": 1, "gruppe": "mehr", "ganzzahl": true, "aktiv": true, "grund": null}
    ]
  },
  "openai_ohne_wirkung": {
    "de": [
      {"name": "temperature", "label": "Temperatur", "hinweis": "Wie frei das Modell seine Antworten formuliert", "minimum": 0, "maximum": 2, "schritt": 0.05, "gruppe": "sichtbar", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "top_p", "label": "Top-P", "hinweis": "Umfang der zugelassenen Wortauswahl", "minimum": 0, "maximum": 1, "schritt": 0.01, "gruppe": "sichtbar", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "max_tokens", "label": "Antwortlänge", "hinweis": "Höchstzahl an Token", "minimum": 256, "maximum": 1000000, "schritt": 256, "gruppe": "sichtbar", "ganzzahl": true, "aktiv": true, "grund": null},
      {"name": "reasoning_budget", "label": "Denklänge", "hinweis": "Wie lange das Modell vor der Antwort nachdenken darf", "minimum": -1, "maximum": 1000000, "schritt": 256, "gruppe": "sichtbar", "ganzzahl": true, "aktiv": false, "grund": "Dieser Server unterstützt keine einstellbare Denklänge."},
      {"name": "presence_penalty", "label": "Themenwechsel", "hinweis": "Höhere Werte begünstigen neue Themen.", "minimum": -2, "maximum": 2, "schritt": 0.05, "gruppe": "mehr", "ganzzahl": false, "aktiv": false, "grund": "Wirkt bei OpenAI nicht, wenn Werkzeuge oder Denken aktiv sind."},
      {"name": "frequency_penalty", "label": "Wortwiederholung", "hinweis": "Höhere Werte verringern Wortwiederholungen.", "minimum": -2, "maximum": 2, "schritt": 0.05, "gruppe": "mehr", "ganzzahl": false, "aktiv": false, "grund": "Wirkt bei OpenAI nicht, wenn Werkzeuge oder Denken aktiv sind."},
      {"name": "seed", "label": "Startwert", "hinweis": "Derselbe Wert erzeugt dieselbe Antwort. -1 wählt einen zufälligen Wert.", "minimum": -1, "maximum": 2147483647, "schritt": 1, "gruppe": "mehr", "ganzzahl": true, "aktiv": false, "grund": "Wirkt bei OpenAI nicht, wenn Werkzeuge oder Denken aktiv sind."}
    ],
    "en": [
      {"name": "temperature", "label": "Temperature", "hinweis": "How freely the model phrases its responses", "minimum": 0, "maximum": 2, "schritt": 0.05, "gruppe": "sichtbar", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "top_p", "label": "Top-P", "hinweis": "Range of permitted word choices", "minimum": 0, "maximum": 1, "schritt": 0.01, "gruppe": "sichtbar", "ganzzahl": false, "aktiv": true, "grund": null},
      {"name": "max_tokens", "label": "Response length", "hinweis": "Maximum number of tokens", "minimum": 256, "maximum": 1000000, "schritt": 256, "gruppe": "sichtbar", "ganzzahl": true, "aktiv": true, "grund": null},
      {"name": "reasoning_budget", "label": "Thinking length", "hinweis": "How long the model may reason before responding", "minimum": -1, "maximum": 1000000, "schritt": 256, "gruppe": "sichtbar", "ganzzahl": true, "aktiv": false, "grund": "This server does not support a configurable thinking length."},
      {"name": "presence_penalty", "label": "Presence penalty", "hinweis": "Higher values encourage new topics.", "minimum": -2, "maximum": 2, "schritt": 0.05, "gruppe": "mehr", "ganzzahl": false, "aktiv": false, "grund": "Has no effect with OpenAI when tools or thinking are active."},
      {"name": "frequency_penalty", "label": "Frequency penalty", "hinweis": "Higher values reduce word repetition.", "minimum": -2, "maximum": 2, "schritt": 0.05, "gruppe": "mehr", "ganzzahl": false, "aktiv": false, "grund": "Has no effect with OpenAI when tools or thinking are active."},
      {"name": "seed", "label": "Seed", "hinweis": "The same value produces the same response. -1 selects a random value.", "minimum": -1, "maximum": 2147483647, "schritt": 1, "gruppe": "mehr", "ganzzahl": true, "aktiv": false, "grund": "Has no effect with OpenAI when tools or thinking are active."}
    ]
  }
}
''')


def _lagen() -> dict:
    return {
        "frei_llama_cpp": lambda: unterstuetzte("llama_cpp"),
        "mlx": lambda: unterstuetzte("mlx"),
        "openai": lambda: unterstuetzte("openai"),
        "anthropic": lambda: unterstuetzte("anthropic"),
        # The wire would carry the number, the model cannot think.
        "modell_ohne_reasoning": lambda: unterstuetzte("llama_cpp", None, {"reasoning": False}),
        # At OpenAI's own host the three that the Responses wire drops.
        "openai_ohne_wirkung": lambda: unterstuetzte("openai", None, None, CHAT_ONLY_FIELDS),
    }


@pytest.mark.parametrize("lage", sorted(_VORHER))
@pytest.mark.parametrize("sprache", ["de", "en"])
def test_die_reihen_sagen_wortgleich_dasselbe_wie_vor_dem_umzug(lage, sprache, caplog):
    with caplog.at_level("WARNING", logger="app.i18n"):
        reihen = [p.als_dict(sprache) for p in _lagen()[lage]()]
    assert reihen == _VORHER[lage][sprache]
    assert "Translation missing" not in caplog.text


def test_jeder_regler_und_jeder_sperrgrund_ist_ein_schluessel_in_beiden_katalogen():
    """Looked up per catalogue, not through t(), which would hand back the
    other language or the key itself and hide a hole."""
    schluessel = [PARAMETER_TEXT for p in PARAMETER for PARAMETER_TEXT in (p.label, p.hinweis)]
    schluessel += [NO_EFFECT_AT_OPENAI, MODELL_OHNE_REASONING, GRUND_ALLGEMEIN]
    for gruende in GRUENDE.values():
        schluessel += gruende.values()
    for sprache in ("de", "en"):
        katalog = json.loads((LOCALES_VERZEICHNIS / f"{sprache}.json").read_text("utf-8"))
        for eintrag in schluessel:
            text = _nachschlagen(katalog, eintrag)
            assert text, (sprache, eintrag)
            assert eintrag.startswith("parameter."), eintrag


def test_ein_freier_regler_hat_keinen_grund():
    for p in unterstuetzte("llama_cpp"):
        assert p.grund == ""
        assert p.als_dict("de")["grund"] is None


def test_nach_dem_umzug_steht_kein_deutscher_text_mehr_im_quelltext():
    quelltext = Path(parameter_modul.__file__).read_text("utf-8")
    assert not [z for z in quelltext.splitlines() if re.search("[äöüßÄÖÜ]", z)]


# --- In the request body --------------------------------------------------


def _koerper(dialekt: str, **parameter):
    endpunkt = EndpointConfig.model_validate(
        {"id": "p", "name": "P", "base_url": "http://x/v1", "parameter_dialect": dialekt}
    )
    anfrage = Generierungsanfrage(
        nachrichten=[ChatNachricht(role="user", content="hi")], parameter=parameter
    )
    return OpenAIKompatiblerProvider(endpunkt)._koerper_bauen(anfrage)


def test_parameter_landen_uebersetzt_im_koerper():
    koerper = _koerper("mlx", repeat_penalty=1.15, top_k=30)
    assert koerper["repetition_penalty"] == 1.15
    assert koerper["top_k"] == 30
    assert "repeat_penalty" not in koerper


def test_unpassender_parameter_wird_nicht_mitgeschickt():
    """Otherwise the server rejects the entire request as an error."""
    assert "typical_p" not in _koerper("mlx", typical_p=0.9)


def test_hauptwerte_gehen_weiterhin_mit():
    endpunkt = EndpointConfig.model_validate(
        {"id": "p", "name": "P", "base_url": "http://x/v1", "parameter_dialect": "llama_cpp"}
    )
    anfrage = Generierungsanfrage(
        nachrichten=[ChatNachricht(role="user", content="hi")],
        temperature=0.4, top_p=0.8, max_tokens=1024, parameter={"top_k": 20},
    )
    koerper = OpenAIKompatiblerProvider(endpunkt)._koerper_bauen(anfrage)
    assert koerper["temperature"] == 0.4
    assert koerper["top_p"] == 0.8
    assert koerper["max_tokens"] == 1024
    assert koerper["top_k"] == 20


# --- Storage in the cascade -----------------------------------------------
# Parameters used to live on the chat, so every new conversation started at
# the endpoint's bare defaults. They are settings now and sit in the cascade:
# global, then per model, then per chat — the most specific value that is
# actually set wins.


def test_parameter_ueberleben_die_datenbank(repos):
    repos.einstellungen.setzen("modell:qwen", "parameter", {"top_k": 30, "min_p": 0.07})
    assert repos.einstellungen.holen("modell:qwen", "parameter") == {"top_k": 30, "min_p": 0.07}


def test_ein_modell_erbt_was_global_gilt(repos):
    """The point of a cascade: override one knob, keep the rest."""
    repos.einstellungen.setzen("global", "parameter", {"temperature": 0.7, "top_p": 0.9})
    repos.einstellungen.setzen("modell:qwen", "parameter", {"temperature": 0.3})
    aufgeloest = repos.einstellungen.zusammengefuehrt("parameter", modell="qwen")
    assert aufgeloest == {"temperature": 0.3, "top_p": 0.9}


def test_ein_chat_schlaegt_sein_modell(repos):
    repos.einstellungen.setzen("modell:qwen", "parameter", {"temperature": 0.3})
    repos.einstellungen.setzen("chat:abc", "parameter", {"temperature": 1.0})
    assert repos.einstellungen.zusammengefuehrt(
        "parameter", modell="qwen", chat="abc"
    ) == {"temperature": 1.0}


def test_herkunft_sagt_woher_jeder_wert_kommt(repos):
    """Without this the cascade is a black box — a number with no origin."""
    repos.einstellungen.setzen("global", "parameter", {"top_p": 0.9})
    repos.einstellungen.setzen("modell:qwen", "parameter", {"temperature": 0.3})
    woher = repos.einstellungen.value_and_origin("parameter", modell="qwen")[1]
    assert woher == {"top_p": "global", "temperature": "modell:qwen"}


def test_nichts_gesetzt_heisst_nicht_leer_gesetzt(repos):
    """An unset scope steps aside instead of blanking the one above it."""
    repos.einstellungen.setzen("global", "parameter", {"temperature": 0.7})
    assert repos.einstellungen.zusammengefuehrt(
        "parameter", modell="unbekannt", chat="auch-nicht"
    ) == {"temperature": 0.7}


def test_geloeschter_chat_nimmt_seine_werte_mit(repos):
    chat = repos.chats.erstellen(user_id="benutzer", title="Test")
    repos.einstellungen.setzen(f"chat:{chat.id}", "parameter", {"top_k": 30})
    repos.chats.loeschen(chat.id)
    assert repos.einstellungen.holen(f"chat:{chat.id}", "parameter") is None


# --- Via the API ----------------------------------------------------------


def test_parameter_ueber_die_api(client):
    antwort = client.put(
        "/api/v1/settings/modell:qwen/parameter", json={"wert": {"top_k": 25}}
    )
    assert antwort.status_code == 200
    assert antwort.json()["wert"] == {"top_k": 25}


def test_unsinn_kommt_auch_ueber_die_api_nicht_durch(client):
    client.put("/api/v1/settings/global/parameter", json={"wert": {"quatsch": 1}})
    assert client.get("/api/v1/settings/global/parameter").json()["wert"] is None


def test_unbekannter_bereich_wird_abgewiesen(client):
    antwort = client.put("/api/v1/settings/irgendwo/parameter", json={"wert": {"top_k": 5}})
    assert antwort.status_code == 400


def test_aufgeloeste_route_zeigt_wert_und_herkunft(client):
    client.put("/api/v1/settings/global/parameter", json={"wert": {"top_p": 0.9}})
    client.put("/api/v1/settings/modell:qwen/parameter", json={"wert": {"temperature": 0.3}})
    daten = client.get("/api/v1/settings/resolved/parameter?modell=qwen").json()
    assert daten["wert"] == {"top_p": 0.9, "temperature": 0.3}
    assert daten["herkunft"]["temperature"] == "modell:qwen"


def test_modelle_melden_ihre_eigenen_regler(client):
    daten = client.get("/api/v1/models").json()[0]
    assert daten["parameter"], "Every model must report its controls"
    sichtbar = [p["name"] for p in daten["parameter"] if p["gruppe"] == "sichtbar"]
    assert sichtbar == ["temperature", "top_p", "max_tokens", "reasoning_budget"]


def test_eingestellte_parameter_gehen_an_das_modell(client, chat_id):
    """The whole reason for the rebuild: set the model once, it holds."""
    from app.providers import MockProvider, mock_endpunkt
    from tests.conftest import provider_setzen

    provider = provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    client.put("/api/v1/settings/modell:test/parameter", json={"wert": {"top_k": 33}})
    client.post("/api/v1/chat/completions",
                json={"chat_id": chat_id, "endpoint_id": "test", "content": "hi"})
    assert provider.letzte_anfrage.parameter["top_k"] == 33


def test_ein_neuer_chat_erbt_die_modelleinstellung(client):
    """No more setting the model again for every new conversation."""
    from app.providers import MockProvider, mock_endpunkt
    from tests.conftest import provider_setzen

    provider = provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    client.put("/api/v1/settings/modell:test/parameter", json={"wert": {"temperature": 0.25}})
    neuer = client.post("/api/v1/chats", json={"title": "Frisch"}).json()["id"]
    client.post("/api/v1/chat/completions",
                json={"chat_id": neuer, "endpoint_id": "test", "content": "hi"})
    assert provider.letzte_anfrage.temperature == 0.25
