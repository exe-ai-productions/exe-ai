"""The terminal client reads its sentences from the catalogues on disk."""

from __future__ import annotations

import json

from cli import texts
from cli.texts import Texts, resolve_language


def _catalogue(language: str) -> dict:
    return json.loads((texts.CATALOGUE_DIRECTORY / f"{language}.json").read_text(encoding="utf-8"))


def test_a_sentence_comes_from_the_catalogue_file_of_its_language():
    assert Texts("de").t("cli.titel") == _catalogue("de")["cli"]["titel"]
    assert Texts("de").t("status.erreichbar") == _catalogue("de")["status"]["erreichbar"]
    assert Texts("en").t("status.erreichbar") == _catalogue("en")["status"]["erreichbar"]
    assert Texts("de").t("status.erreichbar") != Texts("en").t("status.erreichbar")


def _sentences(node: object, path: str) -> list[tuple[str, str]]:
    """Every sentence below ``node`` with the key that names it."""
    if isinstance(node, str):
        return [(path, node)]
    if isinstance(node, dict):
        return [found for key, value in node.items() for found in _sentences(value, f"{path}.{key}")]
    return []


def test_no_sentence_of_the_client_carries_a_placeholder_in_brackets():
    """A word in pointed or square brackets is typed with them: what is to
    be typed stands as an example that can be typed as it is."""
    for language in ("en", "de"):
        sentences = _sentences(_catalogue(language)["cli"], "cli")
        assert len(sentences) > 70
        bracketed = [key for key, sentence in sentences if any(sign in sentence for sign in "<>[]")]
        assert bracketed == [], f"{language}: {bracketed}"


def test_the_sentences_that_name_the_program_or_an_address_still_leave_room_for_them():
    """Silence probe: the code fills these two as before."""
    for language in ("en", "de"):
        words = Texts(language)
        # A name no catalogue can carry by itself.
        usage = words.t("cli.help_usage", program="called-so")
        assert "{" not in usage and usage.count("called-so") >= 2
        hint = words.t("cli.password_hint", address="http://host:1")
        assert "{" not in hint and hint.startswith("http://host:1 ")


def test_both_catalogues_carry_the_same_sentences_of_the_client():
    english, german = (
        {key for key, _ in _sentences(_catalogue(language)["cli"], "cli")} for language in ("en", "de")
    )
    assert english == german
    # The commands that went took their sentences with them; the new ones
    # are there in both.
    assert not {"cli.cmd_chat", "cli.chat_fehlt", "cli.cmd_look"} & english
    assert {"cli.cmd_theme", "cli.select_keys", "cli.theme_auto"} <= english


def test_a_missing_key_comes_back_as_the_key():
    assert Texts("de").t("cli.no_such_sentence") == "cli.no_such_sentence"
    # A key that names a whole group is no sentence either.
    assert Texts("de").t("cli") == "cli"


def test_placeholders_are_filled_and_a_missing_one_leaves_the_sentence_standing():
    words = Texts("en")
    sentence = _catalogue("en")["fehler"]["dienst_antwortet_nicht"]
    assert words.t("fehler.dienst_antwortet_nicht", error="http://host:1") == sentence.format(
        error="http://host:1"
    )
    assert words.t("fehler.dienst_antwortet_nicht", other="x") == sentence


def test_a_brace_that_opens_no_placeholder_leaves_the_sentence_standing(tmp_path):
    (tmp_path / "en.json").write_text(json.dumps({"a": "Write {name} as { or }"}), encoding="utf-8")
    assert Texts("en", tmp_path).t("a", name="x") == "Write {name} as { or }"


def test_a_key_missing_in_one_language_is_taken_from_the_default_language(tmp_path):
    (tmp_path / "en.json").write_text(json.dumps({"a": {"b": "from the default"}}), encoding="utf-8")
    (tmp_path / "de.json").write_text(json.dumps({"a": {}}), encoding="utf-8")
    assert Texts("de", tmp_path).t("a.b") == "from the default"


def test_the_language_can_be_switched_while_the_client_runs():
    words = Texts("en")
    english = words.t("status.erreichbar")
    words.set_language("de")
    assert words.t("status.erreichbar") != english


def test_the_language_is_the_asked_one_then_the_remembered_one_then_the_systems(monkeypatch):
    monkeypatch.setattr(texts, "system_language", lambda: "de")
    assert resolve_language("en", "de") == "en"
    assert resolve_language(None, "en") == "en"
    assert resolve_language(None, None) == "de"
    # A language without a catalogue is passed over, wherever it comes from.
    assert resolve_language("xx", "yy") == "de"
    monkeypatch.setattr(texts, "system_language", lambda: None)
    assert resolve_language(None, None) == texts.DEFAULT_LANGUAGE


def test_the_systems_language_is_read_from_a_locale_name(monkeypatch):
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(texts.locale, "getlocale", lambda: (None, None))
    monkeypatch.setattr(texts.sys, "platform", "linux")
    assert texts.system_language() is None
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    assert texts.system_language() == "de"
    # The most specific variable wins.
    monkeypatch.setenv("LC_ALL", "en_US.UTF-8")
    assert texts.system_language() == "en"


def test_a_locale_that_names_no_language_is_passed_over(monkeypatch):
    for name in ("LC_ALL", "LC_MESSAGES"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(texts.sys, "platform", "linux")
    monkeypatch.setattr(texts.locale, "getlocale", lambda: ("German_Germany", "1252"))
    for value in ("C", "C.UTF-8", "POSIX"):
        monkeypatch.setenv("LANG", value)
        assert texts.system_language() is None
