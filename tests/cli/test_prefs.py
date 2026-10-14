"""What the terminal client remembers between two starts."""

from __future__ import annotations

import json

from cli import prefs


def test_without_a_file_the_defaults_hold(tmp_path):
    assert prefs.load(tmp_path / "cli.json") == prefs.DEFAULTS
    # Reading alone never creates the file.
    assert not (tmp_path / "cli.json").exists()


def test_what_is_written_is_read_back(tmp_path):
    file = tmp_path / "home" / ".exe-ai" / "cli.json"
    prefs.save({"look": "exe", "language": "de", "url": "http://127.0.0.1:8090"}, file)
    assert prefs.load(file) == {
        "look": "exe",
        "language": "de",
        "url": "http://127.0.0.1:8090",
        "keys": None,
    }
    # No draft of the write stays beside the file.
    assert [entry.name for entry in file.parent.iterdir()] == ["cli.json"]


def test_remembering_one_choice_keeps_the_others(tmp_path):
    file = tmp_path / "cli.json"
    prefs.remember(file, language="de")
    assert prefs.remember(file, look="exe") == {
        "look": "exe",
        "language": "de",
        "url": None,
        "keys": None,
    }
    assert json.loads(file.read_text(encoding="utf-8"))["language"] == "de"


def test_an_entry_of_another_module_survives_a_write(tmp_path):
    file = tmp_path / "cli.json"
    file.write_text(json.dumps({"nerd": True, "look": "exe"}), encoding="utf-8")
    assert prefs.remember(file, language="en")["nerd"] is True
    assert json.loads(file.read_text(encoding="utf-8")) == {
        "look": "exe",
        "language": "en",
        "url": None,
        "keys": None,
        "nerd": True,
    }


def test_a_broken_file_and_a_choice_of_the_wrong_kind_read_as_not_chosen(tmp_path):
    file = tmp_path / "cli.json"
    file.write_text("{ not json", encoding="utf-8")
    assert prefs.load(file) == prefs.DEFAULTS
    file.write_text(json.dumps(["a", "list"]), encoding="utf-8")
    assert prefs.load(file) == prefs.DEFAULTS
    file.write_text(json.dumps({"look": 7, "language": "de"}), encoding="utf-8")
    assert prefs.load(file) == {"look": None, "language": "de", "url": None, "keys": None}


def test_the_file_lies_in_the_users_home(monkeypatch, tmp_path):
    monkeypatch.setattr(prefs.Path, "home", lambda: tmp_path)
    assert prefs.default_path() == tmp_path / ".exe-ai" / "cli.json"
    prefs.remember(look="exe")
    assert prefs.load()["look"] == "exe"


def test_the_keys_of_services_that_demanded_a_password_are_kept_per_address(tmp_path):
    """One key per address; a later one for another address stands beside
    it, and ``keys`` of the wrong kind reads as none."""
    file = tmp_path / "cli.json"
    prefs.remember(file, keys={"http://100.100.0.9:8123": "key-one"})
    kept = prefs.load(file)["keys"]
    prefs.remember(file, keys={**kept, "http://100.100.0.10:8123": "key-two"})
    assert prefs.load(file)["keys"] == {
        "http://100.100.0.9:8123": "key-one",
        "http://100.100.0.10:8123": "key-two",
    }
    file.write_text(json.dumps({"keys": "not-a-map"}), encoding="utf-8")
    assert prefs.load(file)["keys"] is None
