"""The folder manifest that binds a model to its companions.

What is tested is the part that has to hold: a bond written down comes back
the same, a corrupt note is treated as no note, a name that reaches outside
the folder is refused, and a companion that has since been deleted disappears
from the answer.
"""

from __future__ import annotations

from pathlib import Path

from app import modellzuordnung


# --- Round trip -----------------------------------------------------------


def test_ein_eintrag_kommt_gleich_zurueck(tmp_path: Path):
    (tmp_path / "vision").mkdir()
    (tmp_path / "vision" / "modell-mmproj-BF16.gguf").write_bytes(b"x")
    (tmp_path / "mtp").mkdir()
    (tmp_path / "mtp" / "modell-mtp-Q8.gguf").write_bytes(b"x")

    modellzuordnung.eintragen(tmp_path, "modell.gguf", "mmproj", "modell-mmproj-BF16.gguf")
    modellzuordnung.eintragen(tmp_path, "modell.gguf", "mtp", "modell-mtp-Q8.gguf")

    assert modellzuordnung.fuer(tmp_path, "modell.gguf") == {
        "mmproj": "modell-mmproj-BF16.gguf",
        "mtp": "modell-mtp-Q8.gguf",
    }


def test_ein_zweiter_eintrag_ersetzt_die_rolle(tmp_path: Path):
    (tmp_path / "vision").mkdir()
    (tmp_path / "vision" / "alt-mmproj.gguf").write_bytes(b"x")
    (tmp_path / "vision" / "neu-mmproj.gguf").write_bytes(b"x")

    modellzuordnung.eintragen(tmp_path, "modell.gguf", "mmproj", "alt-mmproj.gguf")
    modellzuordnung.eintragen(tmp_path, "modell.gguf", "mmproj", "neu-mmproj.gguf")

    assert modellzuordnung.fuer(tmp_path, "modell.gguf")["mmproj"] == "neu-mmproj.gguf"


def test_ohne_note_ist_alles_leer(tmp_path: Path):
    assert modellzuordnung.lade(tmp_path) == {}
    assert modellzuordnung.fuer(tmp_path, "modell.gguf") == {"mmproj": None, "mtp": None}


# --- A note that cannot be trusted ----------------------------------------


def test_eine_kaputte_note_gilt_als_keine(tmp_path: Path):
    (tmp_path / modellzuordnung.ZUORDNUNG_DATEI).write_text("{ this is not json")
    # A corrupt file must never raise — the runner falls back to its heuristic.
    assert modellzuordnung.lade(tmp_path) == {}
    assert modellzuordnung.fuer(tmp_path, "modell.gguf") == {"mmproj": None, "mtp": None}


def test_ein_name_der_hinausfuehrt_wird_verworfen(tmp_path: Path):
    modellzuordnung.eintragen(tmp_path, "../boese.gguf", "mmproj", "gut.gguf")
    modellzuordnung.eintragen(tmp_path, "modell.gguf", "mmproj", "../boese.gguf")
    modellzuordnung.eintragen(tmp_path, "modell.gguf", "mmproj", "unter/tief.gguf")
    modellzuordnung.eintragen(tmp_path, "modell.gguf", "mmproj", ".versteckt.gguf")
    # None of the four unsafe names may have been written.
    assert modellzuordnung.lade(tmp_path) == {}


def test_eine_unbekannte_rolle_wird_ignoriert(tmp_path: Path):
    (tmp_path / "modell-mmproj.gguf").write_bytes(b"x")
    modellzuordnung.eintragen(tmp_path, "modell.gguf", "sonstwas", "modell-mmproj.gguf")
    assert modellzuordnung.lade(tmp_path) == {}


# --- A companion that is gone ---------------------------------------------


def test_ein_geloeschter_begleiter_faellt_raus(tmp_path: Path):
    (tmp_path / "vision").mkdir()
    begleiter = tmp_path / "vision" / "modell-mmproj-BF16.gguf"
    begleiter.write_bytes(b"x")
    modellzuordnung.eintragen(tmp_path, "modell.gguf", "mmproj", "modell-mmproj-BF16.gguf")
    assert modellzuordnung.fuer(tmp_path, "modell.gguf")["mmproj"] == "modell-mmproj-BF16.gguf"

    # The file leaves; the answer forgets it, though the note still holds it.
    begleiter.unlink()
    assert modellzuordnung.fuer(tmp_path, "modell.gguf")["mmproj"] is None
    assert "modell.gguf" in modellzuordnung.lade(tmp_path)


def test_entfernen_loescht_den_ganzen_eintrag(tmp_path: Path):
    (tmp_path / "modell-mmproj.gguf").write_bytes(b"x")
    modellzuordnung.eintragen(tmp_path, "modell.gguf", "mmproj", "modell-mmproj.gguf")
    modellzuordnung.entfernen(tmp_path, "modell.gguf")
    assert "modell.gguf" not in modellzuordnung.lade(tmp_path)


# --- A sibling model as the draft -----------------------------------------
# The catalogue fetches a draft into mtp/; the next start puts a whole model
# back into the model folder. The note finds it in both places, mtp/ first.


def test_a_sibling_draft_in_the_model_folder_is_found(tmp_path: Path):
    (tmp_path / "modell.gguf").write_bytes(b"x")
    (tmp_path / "geschwister.gguf").write_bytes(b"x")
    modellzuordnung.eintragen(tmp_path, "modell.gguf", "mtp", "geschwister.gguf")
    assert modellzuordnung.fuer(tmp_path, "modell.gguf")["mtp"] == "geschwister.gguf"


def test_a_draft_in_mtp_still_counts(tmp_path: Path):
    (tmp_path / "mtp").mkdir()
    (tmp_path / "mtp" / "modul.gguf").write_bytes(b"x")
    modellzuordnung.eintragen(tmp_path, "modell.gguf", "mtp", "modul.gguf")
    assert modellzuordnung.fuer(tmp_path, "modell.gguf")["mtp"] == "modul.gguf"


def test_a_draft_that_lies_nowhere_drops_out(tmp_path: Path):
    modellzuordnung.eintragen(tmp_path, "modell.gguf", "mtp", "weg.gguf")
    assert modellzuordnung.fuer(tmp_path, "modell.gguf")["mtp"] is None


def test_the_model_itself_and_a_projector_are_no_draft(tmp_path: Path):
    (tmp_path / "modell.gguf").write_bytes(b"x")
    (tmp_path / "modell-mmproj-F16.gguf").write_bytes(b"x")
    modellzuordnung.eintragen(tmp_path, "modell.gguf", "mtp", "modell.gguf")
    assert modellzuordnung.fuer(tmp_path, "modell.gguf")["mtp"] is None
    modellzuordnung.eintragen(tmp_path, "modell.gguf", "mtp", "modell-mmproj-F16.gguf")
    assert modellzuordnung.fuer(tmp_path, "modell.gguf")["mtp"] is None


def test_a_projector_still_counts_only_in_its_own_folder(tmp_path: Path):
    (tmp_path / "modell-mmproj-F16.gguf").write_bytes(b"x")
    modellzuordnung.eintragen(tmp_path, "modell.gguf", "mmproj", "modell-mmproj-F16.gguf")
    assert modellzuordnung.fuer(tmp_path, "modell.gguf")["mmproj"] is None


def test_a_name_with_a_path_stays_refused(tmp_path: Path):
    (tmp_path / "geschwister.gguf").write_bytes(b"x")
    modellzuordnung.eintragen(tmp_path, "modell.gguf", "mtp", "../geschwister.gguf")
    assert modellzuordnung.fuer(tmp_path, "modell.gguf")["mtp"] is None


def test_a_link_leading_out_of_the_folder_is_no_draft(tmp_path: Path):
    """The same boundary as the runner's: the file itself, resolved, must lie
    in the model folder — a start would refuse the link, so the note must not
    offer it."""
    ausserhalb = tmp_path / "ausserhalb"
    ausserhalb.mkdir()
    (ausserhalb / "geschwister.gguf").write_bytes(b"x")
    ordner = tmp_path / "modelle"
    ordner.mkdir()
    (ordner / "modell.gguf").write_bytes(b"x")
    (ordner / "link.gguf").symlink_to(ausserhalb / "geschwister.gguf")
    modellzuordnung.eintragen(ordner, "modell.gguf", "mtp", "link.gguf")
    assert modellzuordnung.fuer(ordner, "modell.gguf")["mtp"] is None
