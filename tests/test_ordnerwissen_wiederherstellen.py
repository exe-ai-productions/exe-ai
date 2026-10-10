"""Getting a deleted exe.md back — the module, then the route.

The copy has been written on every request since the delete protection was
built, and for just as long the only thing that ever read it was a test.
What is checked here is the way out: that the copy really lands back on
disk, that a folder without one is told so instead of being told nothing,
and that notes saying something else are never quietly thrown away for an
older text.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app import atomic_file, ordnerwissen


@pytest.fixture(autouse=True)
def sauber():
    ordnerwissen.vergessen()
    yield
    ordnerwissen.vergessen()


def _mit_sicherung(tmp_path: Path, text: str = "was drinstand"):
    """A shared folder whose notes have been copied once."""
    ordner = tmp_path / "geteilt"
    ordner.mkdir()
    (ordner / ordnerwissen.DATEINAME).write_text(text, encoding="utf-8")
    daten = tmp_path / "daten"
    ordnerwissen.sichern(ordnerwissen.lesen([str(ordner)]), daten)
    return ordner, daten


# --- Putting it back ----------------------------------------------------------


def test_die_geloeschte_datei_ist_danach_wieder_da(tmp_path):
    ordner, daten = _mit_sicherung(tmp_path)
    (ordner / ordnerwissen.DATEINAME).unlink()

    ergebnis = ordnerwissen.wiederherstellen(str(ordner), daten)

    assert ergebnis.ergebnis == ordnerwissen.ZURUECK
    assert ergebnis.erfolg
    assert (ordner / ordnerwissen.DATEINAME).read_text(encoding="utf-8") == (
        "was drinstand"
    )


def test_eine_leergeraeumte_datei_gilt_als_geloescht(tmp_path):
    """Truncating and deleting are the same accident with different tools."""
    ordner, daten = _mit_sicherung(tmp_path)
    (ordner / ordnerwissen.DATEINAME).write_text("\n\n   ", encoding="utf-8")

    ergebnis = ordnerwissen.wiederherstellen(str(ordner), daten)

    assert ergebnis.ergebnis == ordnerwissen.ZURUECK
    assert (ordner / ordnerwissen.DATEINAME).read_text(encoding="utf-8") == (
        "was drinstand"
    )


def test_das_register_haelt_fest_dass_zurueckgeholt_wurde(tmp_path):
    """Outside the shared folder, so dropping a file in cannot change it."""
    import json

    ordner, daten = _mit_sicherung(tmp_path)
    (ordner / ordnerwissen.DATEINAME).unlink()
    ordnerwissen.wiederherstellen(str(ordner), daten)

    stand = json.loads((daten / ordnerwissen.REGISTER).read_text(encoding="utf-8"))
    assert stand[str(ordner)]["wiederhergestellt"]


# --- Answering honestly when there is nothing ---------------------------------


def test_ohne_sicherung_wird_nichts_erfunden(tmp_path):
    ordner = tmp_path / "geteilt"
    ordner.mkdir()

    ergebnis = ordnerwissen.wiederherstellen(str(ordner), tmp_path / "daten")

    assert ergebnis.ergebnis == ordnerwissen.KEINE_SICHERUNG
    assert not ergebnis.erfolg
    assert ergebnis.text == ""
    assert not (ordner / ordnerwissen.DATEINAME).exists()


def test_ohne_datenordner_gibt_es_nichts_zurueckzuholen(tmp_path):
    """No data folder means no register and no copy — the same answer, and
    never a crash on the way to it."""
    ordner = tmp_path / "geteilt"
    ordner.mkdir()

    ergebnis = ordnerwissen.wiederherstellen(str(ordner), None)

    assert ergebnis.ergebnis == ordnerwissen.KEINE_SICHERUNG


# --- The refusal --------------------------------------------------------------


def test_neu_geschriebene_notizen_werden_nicht_ueberschrieben(tmp_path):
    """The copy is older than whatever stands there now, and older text does
    not win by being available."""
    ordner, daten = _mit_sicherung(tmp_path)
    (ordner / ordnerwissen.DATEINAME).write_text("etwas ganz anderes", encoding="utf-8")

    ergebnis = ordnerwissen.wiederherstellen(str(ordner), daten)

    assert ergebnis.ergebnis == ordnerwissen.IM_WEG
    assert not ergebnis.erfolg
    assert (ordner / ordnerwissen.DATEINAME).read_text(encoding="utf-8") == (
        "etwas ganz anderes"
    )
    # And the copy itself is still there for a second, deliberate decision.
    assert ordnerwissen.sicherung(str(ordner), daten) == "was drinstand"


def test_eine_unlesbare_datei_zaehlt_als_besetzt(tmp_path):
    """What cannot be read cannot be weighed, so it is never written over."""
    ordner, daten = _mit_sicherung(tmp_path)
    (ordner / ordnerwissen.DATEINAME).write_bytes(b"\xff\xfe\x00kaputt")

    ergebnis = ordnerwissen.wiederherstellen(str(ordner), daten)

    assert ergebnis.ergebnis == ordnerwissen.IM_WEG
    assert (ordner / ordnerwissen.DATEINAME).read_bytes() == b"\xff\xfe\x00kaputt"


def test_eine_gleiche_datei_wird_nicht_angefasst(tmp_path):
    """Nothing was lost, so nothing is written — an offer to restore must
    not become a change of its own."""
    ordner, daten = _mit_sicherung(tmp_path)
    ziel = ordner / ordnerwissen.DATEINAME
    zuerst = ziel.stat().st_mtime_ns

    ergebnis = ordnerwissen.wiederherstellen(str(ordner), daten)

    assert ergebnis.ergebnis == ordnerwissen.UNVERAENDERT
    assert not ergebnis.erfolg
    assert ziel.stat().st_mtime_ns == zuerst


@pytest.mark.platforms("posix", reason="a folder closed by its rights")
def test_ein_nicht_beschreibbarer_ordner_sagt_es(tmp_path):
    ordner, daten = _mit_sicherung(tmp_path)
    (ordner / ordnerwissen.DATEINAME).unlink()
    ordner.chmod(0o500)
    try:
        ergebnis = ordnerwissen.wiederherstellen(str(ordner), daten)
        assert ergebnis.ergebnis == ordnerwissen.NICHT_SCHREIBBAR
        assert not (ordner / ordnerwissen.DATEINAME).exists()
    finally:
        ordner.chmod(0o700)


# --- The route ----------------------------------------------------------------


@pytest.fixture
def wissensclient(client):
    """The API client with the folder-knowledge router mounted.

    app/api/v1/__init__.py does not list this router yet — listing it is one
    import and one line, and it belongs with the window that will call it.
    Mounting it here only when it is missing keeps these tests true on both
    sides of that line instead of turning green into red the day it lands.

    The new routes are then moved to the front, and that detail is the whole
    reason the real listing has to happen: app/main.py mounts the static
    files on "/" last, and that mount answers every path there is. A route
    registered behind it is never reached — it answers 405, not 404, which
    is the confusing shape a late registration takes.
    """
    from app.api.v1 import ordnerwissen as route

    schon_da = any(
        getattr(eintrag, "path", "").startswith("/api/v1/ordnerwissen")
        for eintrag in client.app.router.routes
    )
    if not schon_da:
        vorher = len(client.app.router.routes)
        client.app.include_router(route.router, prefix="/api/v1")
        neu = client.app.router.routes[vorher:]
        del client.app.router.routes[vorher:]
        client.app.router.routes[0:0] = neu
    return client


def _freigeben(wissensclient, chat_id: str, ordner: Path) -> str:
    """Shares a folder with a chat and reports the path as the chat now
    carries it — the check on the routes compares those strings exactly."""
    antwort = wissensclient.patch(
        f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(ordner)]}
    )
    assert antwort.status_code == 200
    return antwort.json()["working_dirs"][0]


def test_die_route_holt_die_sicherung_zurueck(wissensclient, chat_id, tmp_path):
    ordner = tmp_path / "geteilt"
    ordner.mkdir()
    (ordner / ordnerwissen.DATEINAME).write_text("was drinstand", encoding="utf-8")
    freigegeben = _freigeben(wissensclient, chat_id, ordner)
    daten = wissensclient.app.state.config.datenverzeichnis
    ordnerwissen.sichern(ordnerwissen.lesen([freigegeben]), daten)
    (ordner / ordnerwissen.DATEINAME).unlink()

    antwort = wissensclient.post(
        "/api/v1/ordnerwissen/wiederherstellen",
        json={"chat_id": chat_id, "pfad": freigegeben},
    )

    assert antwort.status_code == 200
    assert antwort.json()["ergebnis"] == ordnerwissen.ZURUECK
    assert (ordner / ordnerwissen.DATEINAME).read_text(encoding="utf-8") == (
        "was drinstand"
    )


def test_die_route_sagt_wenn_es_keine_sicherung_gibt(wissensclient, chat_id, tmp_path):
    ordner = tmp_path / "geteilt"
    ordner.mkdir()
    freigegeben = _freigeben(wissensclient, chat_id, ordner)

    stand = wissensclient.get(
        "/api/v1/ordnerwissen/sicherung",
        params={"chat_id": chat_id, "pfad": freigegeben},
    )
    assert stand.status_code == 200
    assert stand.json()["sicherung"] is False
    # Sharing the folder put the scaffold in it, so there ARE notes.
    assert stand.json()["notiz"] is True

    holen = wissensclient.post(
        "/api/v1/ordnerwissen/wiederherstellen",
        json={"chat_id": chat_id, "pfad": freigegeben},
    )
    assert holen.status_code == 200
    assert holen.json()["ergebnis"] == ordnerwissen.KEINE_SICHERUNG


def test_die_route_ueberschreibt_keine_neuen_notizen(wissensclient, chat_id, tmp_path):
    ordner = tmp_path / "geteilt"
    ordner.mkdir()
    (ordner / ordnerwissen.DATEINAME).write_text("alt", encoding="utf-8")
    freigegeben = _freigeben(wissensclient, chat_id, ordner)
    daten = wissensclient.app.state.config.datenverzeichnis
    ordnerwissen.sichern(ordnerwissen.lesen([freigegeben]), daten)
    (ordner / ordnerwissen.DATEINAME).write_text("neu und anders", encoding="utf-8")

    antwort = wissensclient.post(
        "/api/v1/ordnerwissen/wiederherstellen",
        json={"chat_id": chat_id, "pfad": freigegeben},
    )

    assert antwort.status_code == 200
    assert antwort.json()["ergebnis"] == ordnerwissen.IM_WEG
    assert (ordner / ordnerwissen.DATEINAME).read_text(encoding="utf-8") == (
        "neu und anders"
    )


def test_ein_fremder_ordner_wird_abgewiesen(wissensclient, chat_id, tmp_path):
    ordner = tmp_path / "geteilt"
    ordner.mkdir()
    _freigeben(wissensclient, chat_id, ordner)

    antwort = wissensclient.post(
        "/api/v1/ordnerwissen/wiederherstellen",
        json={"chat_id": chat_id, "pfad": "/etc"},
    )
    assert antwort.status_code == 403


def test_ohne_chat_gibt_es_nichts_zurueckzuholen(wissensclient, tmp_path):
    antwort = wissensclient.post(
        "/api/v1/ordnerwissen/wiederherstellen",
        json={"chat_id": "gibtsnicht", "pfad": str(tmp_path)},
    )
    assert antwort.status_code == 404


# --- The window has a sentence for every ending -------------------------------


def test_jedes_ende_hat_einen_satz_in_beiden_katalogen():
    """Every outcome key can be said out loud, in both languages.

    The route answers with a key and never with a sentence, and the window
    turns that key into one out of its own catalogue. That only works while
    the two sides know the same five endings: a key without an entry shows
    the key itself, and the one ending most likely to be added later
    ("nothing was kept") is exactly the one nobody would notice missing —
    it is the quiet case.
    """
    katalog = Path(__file__).resolve().parent.parent / "app" / "locales"
    enden = {
        ordnerwissen.ZURUECK,
        ordnerwissen.KEINE_SICHERUNG,
        ordnerwissen.UNVERAENDERT,
        ordnerwissen.IM_WEG,
        ordnerwissen.NICHT_SCHREIBBAR,
    }
    for sprache in ("de", "en"):
        texte = json.loads((katalog / f"{sprache}.json").read_text(encoding="utf-8"))
        fehlend = enden - set(texte["ordnerwissen"])
        assert not fehlend, f"{sprache}: {sorted(fehlend)}"
        for ende in enden:
            # Which folder it was about, or five sentences that all look the
            # same in a window that offers several folders at once.
            assert "{ordner}" in texte["ordnerwissen"][ende]


# --- Byte for byte ------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        b"# Notes\n\nfirst line\nlast line\n",
        b"  indented start\r\nwindows lines\r\n\r\n",
    ],
)
def test_the_file_put_back_is_the_file_that_was_there(tmp_path, raw):
    """Kept, deleted, put back: the same bytes, the last line break and the
    line endings included."""
    ordner = tmp_path / "shared"
    ordner.mkdir()
    datei = ordner / ordnerwissen.DATEINAME
    datei.write_bytes(raw)
    daten = tmp_path / "data"
    ordnerwissen.sichern(ordnerwissen.lesen([str(ordner)]), daten)
    datei.unlink()

    assert ordnerwissen.wiederherstellen(str(ordner), daten).erfolg
    assert datei.read_bytes() == raw


def test_the_system_message_still_gets_the_trimmed_text(tmp_path):
    """The silence probe: what the prompt carries is unchanged — plain line
    endings, no whitespace at either end."""
    ordner = tmp_path / "shared"
    ordner.mkdir()
    (ordner / ordnerwissen.DATEINAME).write_bytes(b"\n  first\r\nsecond  \r\n\n")

    [notiz] = ordnerwissen.lesen([str(ordner)])

    assert notiz.text == "first\nsecond"


def test_an_unchanged_windows_file_is_left_alone(tmp_path):
    """A file with Windows line endings that still says what the copy says
    is not "in the way" of its own copy."""
    ordner = tmp_path / "shared"
    ordner.mkdir()
    (ordner / ordnerwissen.DATEINAME).write_bytes(b"same\r\ntext\r\n")
    daten = tmp_path / "data"
    ordnerwissen.sichern(ordnerwissen.lesen([str(ordner)]), daten)

    ergebnis = ordnerwissen.wiederherstellen(str(ordner), daten)

    assert ergebnis.ergebnis == ordnerwissen.UNVERAENDERT


def test_a_file_that_only_changed_its_line_endings_is_left_alone(tmp_path):
    """Re-saved with Windows line endings, same words: still the file the
    copy holds, not notes that are in its way."""
    ordner = tmp_path / "shared"
    ordner.mkdir()
    datei = ordner / ordnerwissen.DATEINAME
    datei.write_bytes(b"same\ntext\n")
    daten = tmp_path / "data"
    ordnerwissen.sichern(ordnerwissen.lesen([str(ordner)]), daten)
    datei.write_bytes(b"same\r\ntext\r\n")

    ergebnis = ordnerwissen.wiederherstellen(str(ordner), daten)

    assert ergebnis.ergebnis == ordnerwissen.UNVERAENDERT
    assert datei.read_bytes() == b"same\r\ntext\r\n"


def test_a_copy_kept_as_trimmed_text_still_matches_its_file(tmp_path):
    """A copy written before copies were kept byte for byte holds the trimmed
    text. The file it came from is unchanged and must count as such."""
    ordner = tmp_path / "shared"
    ordner.mkdir()
    datei = ordner / ordnerwissen.DATEINAME
    datei.write_bytes(b"a\nb\n")
    daten = tmp_path / "data"
    ordnerwissen.sichern(ordnerwissen.lesen([str(ordner)]), daten)
    [kopie] = (daten / ordnerwissen.SICHERUNGEN).glob("*.md")
    kopie.write_bytes(b"a\nb")
    datei.write_bytes(b"a\r\nb\r\n")

    ergebnis = ordnerwissen.wiederherstellen(str(ordner), daten)

    assert ergebnis.ergebnis == ordnerwissen.UNVERAENDERT


def test_new_line_endings_make_a_new_copy(tmp_path):
    """The copy follows the file byte for byte: a file that only switched to
    Windows line endings is kept again, so putting it back gives that file."""
    ordner = tmp_path / "shared"
    ordner.mkdir()
    datei = ordner / ordnerwissen.DATEINAME
    daten = tmp_path / "data"
    datei.write_bytes(b"same\ntext\n")
    ordnerwissen.sichern(ordnerwissen.lesen([str(ordner)]), daten)
    datei.write_bytes(b"same\r\ntext\r\n")
    ordnerwissen.sichern(ordnerwissen.lesen([str(ordner)]), daten)
    datei.unlink()

    assert ordnerwissen.wiederherstellen(str(ordner), daten).erfolg
    assert datei.read_bytes() == b"same\r\ntext\r\n"


def test_old_mac_line_endings_reach_the_prompt_as_plain_lines(tmp_path):
    ordner = tmp_path / "shared"
    ordner.mkdir()
    (ordner / ordnerwissen.DATEINAME).write_bytes(b"first\rsecond\r")

    [notiz] = ordnerwissen.lesen([str(ordner)])

    assert notiz.text == "first\nsecond"


def test_the_routes_count_the_text_the_prompt_carries(wissensclient, chat_id, tmp_path):
    """Line endings and trailing blank lines are in the copy, not in the
    number the window shows for it."""
    ordner = tmp_path / "shared"
    ordner.mkdir()
    datei = ordner / ordnerwissen.DATEINAME
    datei.write_bytes(b"ab\r\ncd\r\n\r\n")
    freigegeben = _freigeben(wissensclient, chat_id, ordner)
    daten = wissensclient.app.state.config.datenverzeichnis
    ordnerwissen.sichern(ordnerwissen.lesen([freigegeben]), daten)
    datei.unlink()

    stand = wissensclient.get(
        "/api/v1/ordnerwissen/sicherung",
        params={"chat_id": chat_id, "pfad": freigegeben},
    )
    holen = wissensclient.post(
        "/api/v1/ordnerwissen/wiederherstellen",
        json={"chat_id": chat_id, "pfad": freigegeben},
    )

    assert stand.json()["zeichen"] == len("ab\ncd")
    assert holen.json()["zeichen"] == len("ab\ncd")
    assert datei.read_bytes() == b"ab\r\ncd\r\n\r\n"


def test_a_damaged_copy_is_no_copy_and_the_next_request_mends_it(tmp_path):
    """A copy that is no longer UTF-8 cannot be offered. The file it came
    from is still there and unchanged, so the next read writes a sound copy
    rather than trusting the remembered one."""
    ordner = tmp_path / "shared"
    ordner.mkdir()
    datei = ordner / ordnerwissen.DATEINAME
    datei.write_bytes(b"notes\n")
    daten = tmp_path / "data"
    ordnerwissen.sichern(ordnerwissen.lesen([str(ordner)]), daten)
    [kopie] = (daten / ordnerwissen.SICHERUNGEN).glob("*.md")
    kopie.write_bytes(b"\xff\xfe")

    assert ordnerwissen.sicherung(str(ordner), daten) is None
    ordnerwissen.sichern(ordnerwissen.lesen([str(ordner)]), daten)
    assert kopie.read_bytes() == b"notes\n"


# --- Whole or not at all ------------------------------------------------------


def _write_fails_halfway(monkeypatch):
    """A full disk: the bytes are handed over, then the disk refuses them."""

    def fsync(fd):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(atomic_file.os, "fsync", fsync)


def test_a_backup_that_fails_halfway_leaves_the_previous_one_whole(tmp_path, monkeypatch):
    ordner = tmp_path / "shared"
    ordner.mkdir()
    datei = ordner / ordnerwissen.DATEINAME
    datei.write_bytes(b"first version\n")
    daten = tmp_path / "data"
    ordnerwissen.sichern(ordnerwissen.lesen([str(ordner)]), daten)
    [kopie] = (daten / ordnerwissen.SICHERUNGEN).glob("*.md")

    datei.write_bytes(b"second version, a good deal longer\n")
    _write_fails_halfway(monkeypatch)
    ordnerwissen.sichern(ordnerwissen.lesen([str(ordner)]), daten)

    assert kopie.read_bytes() == b"first version\n"
    assert sorted(p.name for p in kopie.parent.iterdir()) == [kopie.name]


def test_a_restore_that_fails_halfway_leaves_no_cut_off_file(tmp_path, monkeypatch):
    ordner, daten = _mit_sicherung(tmp_path)
    datei = ordner / ordnerwissen.DATEINAME
    datei.unlink()
    _write_fails_halfway(monkeypatch)

    ergebnis = ordnerwissen.wiederherstellen(str(ordner), daten)

    assert ergebnis.ergebnis == ordnerwissen.NICHT_SCHREIBBAR
    assert sorted(p.name for p in ordner.iterdir()) == []


def test_a_backup_is_still_the_file_byte_for_byte(tmp_path):
    """Silence probe: a write that goes through keeps the file as it is."""
    ordner = tmp_path / "shared"
    ordner.mkdir()
    raw = b"\xef\xbb\xbfnotes\r\nmore\r\n"
    (ordner / ordnerwissen.DATEINAME).write_bytes(raw)
    daten = tmp_path / "data"
    ordnerwissen.sichern(ordnerwissen.lesen([str(ordner)]), daten)
    [kopie] = (daten / ordnerwissen.SICHERUNGEN).glob("*.md")

    assert kopie.read_bytes() == raw


# --- A byte order mark is not a word ------------------------------------------


def test_a_bom_does_not_reach_the_system_message(tmp_path):
    ordner = tmp_path / "shared"
    ordner.mkdir()
    (ordner / ordnerwissen.DATEINAME).write_bytes(b"\xef\xbb\xbfnotes\n")

    [notiz] = ordnerwissen.lesen([str(ordner)])

    assert notiz.text == "notes"
    assert notiz.raw.startswith("\ufeff")


def test_the_same_words_with_a_bom_are_the_same_notes(tmp_path):
    """Re-saved by an editor that adds a BOM: still the file the copy holds."""
    ordner = tmp_path / "shared"
    ordner.mkdir()
    datei = ordner / ordnerwissen.DATEINAME
    datei.write_bytes(b"same\ntext\n")
    daten = tmp_path / "data"
    ordnerwissen.sichern(ordnerwissen.lesen([str(ordner)]), daten)
    datei.write_bytes(b"\xef\xbb\xbfsame\ntext\n")

    ergebnis = ordnerwissen.wiederherstellen(str(ordner), daten)

    assert ergebnis.ergebnis == ordnerwissen.UNVERAENDERT
    assert datei.read_bytes() == b"\xef\xbb\xbfsame\ntext\n"


def test_a_bom_and_whitespace_is_an_empty_file(tmp_path):
    ordner = tmp_path / "shared"
    ordner.mkdir()
    (ordner / ordnerwissen.DATEINAME).write_bytes(b"\xef\xbb\xbf \r\n\n")

    assert ordnerwissen.lesen([str(ordner)]) == []


def test_a_restore_through_a_link_keeps_the_link(tmp_path):
    """A shared exe.md that is a link stays one: the file it points to is
    what comes back."""
    ordner, daten = _mit_sicherung(tmp_path)
    datei = ordner / ordnerwissen.DATEINAME
    real_target = tmp_path / "elsewhere.md"
    real_target.write_bytes(b"")
    datei.unlink()
    datei.symlink_to(real_target)

    assert ordnerwissen.wiederherstellen(str(ordner), daten).ergebnis == ordnerwissen.ZURUECK
    assert datei.is_symlink()
    assert real_target.read_text(encoding="utf-8") == "was drinstand"


@pytest.mark.platforms("posix", reason="permission bits")
def test_a_restore_keeps_the_permission_bits(tmp_path):
    ordner, daten = _mit_sicherung(tmp_path)
    datei = ordner / ordnerwissen.DATEINAME
    datei.write_bytes(b"")
    datei.chmod(0o664)

    assert ordnerwissen.wiederherstellen(str(ordner), daten).ergebnis == ordnerwissen.ZURUECK
    assert datei.stat().st_mode & 0o777 == 0o664


def test_an_interrupted_restore_leaves_no_side_file(tmp_path, monkeypatch):
    """Not only a failed write: an interrupt halfway takes the side file too."""
    ordner, daten = _mit_sicherung(tmp_path)
    (ordner / ordnerwissen.DATEINAME).unlink()

    def fsync(fd):
        raise KeyboardInterrupt

    monkeypatch.setattr(atomic_file.os, "fsync", fsync)
    with pytest.raises(KeyboardInterrupt):
        ordnerwissen.wiederherstellen(str(ordner), daten)

    assert sorted(p.name for p in ordner.iterdir()) == []


def test_a_read_only_file_stays_refused(tmp_path):
    """The rename only asks the folder; a file made read-only is still not
    written, as the write in place refused it."""
    ordner, daten = _mit_sicherung(tmp_path)
    datei = ordner / ordnerwissen.DATEINAME
    datei.write_bytes(b"")
    datei.chmod(0o444)

    ergebnis = ordnerwissen.wiederherstellen(str(ordner), daten)

    assert ergebnis.ergebnis == ordnerwissen.NICHT_SCHREIBBAR
    assert datei.read_bytes() == b""
    assert sorted(p.name for p in ordner.iterdir()) == [ordnerwissen.DATEINAME]


# --- The register -------------------------------------------------------------


def test_the_register_is_written_whole_and_an_interrupted_write_keeps_the_copy_findable(
    tmp_path, monkeypatch
):
    """The register maps a folder to its copy. Written in place, a write that
    broke off left half a JSON file, the register read as empty, and the copy
    beside it was reported missing. It goes through the one way now
    (app/atomic_file.py): never in place, and a write that fails leaves the
    previous register whole — the copy stays findable."""
    ordner, daten = _mit_sicherung(tmp_path)
    register = ordnerwissen._register_datei(daten)
    assert json.loads(register.read_text(encoding="utf-8"))

    in_place: list[Path] = []
    real_write_text = Path.write_text
    real_open = Path.open

    def write_text(self, *args, **kwargs):
        if self == register:
            in_place.append(self)
        return real_write_text(self, *args, **kwargs)

    def open_(self, mode="r", *args, **kwargs):
        if self == register and "w" in mode:
            in_place.append(self)
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", write_text)
    monkeypatch.setattr(Path, "open", open_)

    real_replace = os.replace

    def broken(side, target):
        raise OSError("no rename here")

    monkeypatch.setattr(atomic_file.os, "replace", broken)
    ordnerwissen._eintragen(str(ordner), daten, probe="x")

    assert in_place == [], "the register was written in place"
    assert json.loads(register.read_text(encoding="utf-8"))
    assert not list(register.parent.glob(".*.tmp"))
    (ordner / ordnerwissen.DATEINAME).unlink()
    monkeypatch.setattr(atomic_file.os, "replace", real_replace)
    ergebnis = ordnerwissen.wiederherstellen(str(ordner), daten)
    assert ergebnis.ergebnis == ordnerwissen.ZURUECK
