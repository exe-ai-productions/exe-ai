"""The storage-locations route: read, set, reset, and the guard rails."""

from __future__ import annotations

import pytest


def test_uebersicht_listet_jeden_ort(client):
    antwort = client.get("/api/v1/speicherorte")
    assert antwort.status_code == 200
    namen = {z["name"] for z in antwort.json()}
    assert namen == {
        "images", "image_models", "models", "embedding_models", "speech_models",
        "scripts", "agent_dock",
    }
    for zeile in antwort.json():
        assert zeile["ist_standard"] is True
        assert zeile["pfad"] == zeile["standard"]


def test_setzen_wirkt_und_zuruecksetzen_kehrt_zurueck(client, tmp_path):
    ziel = tmp_path / "meine-bilder"
    gesetzt = client.put("/api/v1/speicherorte/images", json={"pfad": str(ziel)})
    assert gesetzt.status_code == 200
    assert gesetzt.json()["ist_standard"] is False
    assert gesetzt.json()["pfad"] == str(ziel.resolve())

    # A fresh read sees it too — it is really stored, not only echoed.
    jetzt = {z["name"]: z for z in client.get("/api/v1/speicherorte").json()}
    assert jetzt["images"]["pfad"] == str(ziel.resolve())

    zurueck = client.delete("/api/v1/speicherorte/images")
    assert zurueck.status_code == 200
    assert zurueck.json()["ist_standard"] is True


def test_unbekannter_ort_gibt_404(client, tmp_path):
    assert client.put(
        "/api/v1/speicherorte/gibtsnicht", json={"pfad": str(tmp_path)}
    ).status_code == 404
    assert client.delete("/api/v1/speicherorte/gibtsnicht").status_code == 404


def test_pfad_auf_eine_datei_wird_abgewiesen(client, tmp_path):
    datei = tmp_path / "eine-datei.txt"
    datei.write_text("kein ordner", encoding="utf-8")
    antwort = client.put("/api/v1/speicherorte/images", json={"pfad": str(datei)})
    assert antwort.status_code == 400


def test_leerer_pfad_wird_abgewiesen(client):
    assert client.put(
        "/api/v1/speicherorte/images", json={"pfad": "   "}
    ).status_code == 400


# --- The scripts folder is there after a start --------------------------------


def test_der_skriptordner_wird_beim_start_angelegt(client, config):
    """Nothing in the program ever writes into the scripts folder — a cron
    entry only reads it, the settings screen only shows it. So it was the one
    location that could be missing while the window named its path and listed
    nothing under it. The start makes it."""
    from app.speicherorte import ort

    assert ort(config, "scripts").is_dir()


def test_die_uebrigen_orte_legt_der_start_nicht_an(client, config):
    """The silence probe: only the scripts folder. Every other location is
    made by whatever writes into it — a picture being saved, a model being
    downloaded, a file landing on the shelf — and a start that made all of
    them would put seven empty folders on disk nobody asked for."""
    from app.speicherorte import ORTE, ort

    uebrig = [o.name for o in ORTE if o.name != "scripts"]
    assert uebrig, "the sample needs at least one other location"
    assert not any(ort(config, name).exists() for name in uebrig)


def test_the_data_folder_itself_is_refused(client):
    daten = client.app.state.config.datenverzeichnis
    antwort = client.put("/api/v1/speicherorte/agent_dock", json={"pfad": str(daten)})
    assert antwort.status_code == 400, antwort.text


def test_a_folder_above_the_data_folder_is_refused(client):
    daten = client.app.state.config.datenverzeichnis
    antwort = client.put("/api/v1/speicherorte/images", json={"pfad": str(daten.parent)})
    assert antwort.status_code == 400, antwort.text


def test_a_folder_inside_the_data_folder_is_taken(client):
    """Silence probe: every location lies inside the data folder by
    default, and a new one there is fine."""
    daten = client.app.state.config.datenverzeichnis
    ziel = daten / "elsewhere"
    antwort = client.put("/api/v1/speicherorte/agent_dock", json={"pfad": str(ziel)})
    assert antwort.status_code == 200, antwort.text


# --- Only an absolute path is taken --------------------------------------------


@pytest.mark.parametrize("pfad", ["bilder-relativ", "./neu", "a/b", "../nebenan", '"relativ/in-anfuehrungszeichen"'])
def test_a_relative_path_is_refused_with_its_own_sentence_and_makes_nothing(
    client, tmp_path, monkeypatch, pfad
):
    arbeit = tmp_path / "arbeitsverzeichnis"
    arbeit.mkdir()
    monkeypatch.chdir(arbeit)
    vorher = client.get("/api/v1/speicherorte").json()

    english = client.put(
        "/api/v1/speicherorte/images", json={"pfad": pfad}, headers={"X-Ui-Language": "en"}
    )
    german = client.put(
        "/api/v1/speicherorte/images", json={"pfad": pfad}, headers={"X-Ui-Language": "de"}
    )

    assert english.status_code == 400 and german.status_code == 400
    assert english.json()["detail"] == "Enter an absolute folder path"
    assert german.json()["detail"] == "Bitte einen absoluten Ordnerpfad angeben"
    # Nothing was made where the service happens to run, and nothing stored.
    assert list(arbeit.iterdir()) == []
    assert client.get("/api/v1/speicherorte").json() == vorher


def test_silence_an_absolute_path_the_same_in_quotes_and_with_a_tilde_are_taken(
    client, tmp_path, monkeypatch
):
    monkeypatch.setenv("HOME", str(tmp_path))
    # The folder ``~`` stands for is named by this variable on Windows.
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    plain = tmp_path / "plain"
    quoted = tmp_path / "quoted dir"

    for text, wanted in (
        (str(plain), plain),
        (f'"{quoted}"', quoted),
        ("~/home-relative", tmp_path / "home-relative"),
    ):
        answer = client.put("/api/v1/speicherorte/images", json={"pfad": text})
        assert answer.status_code == 200, (text, answer.text)
        assert answer.json()["pfad"] == str(wanted.resolve())
        assert wanted.is_dir()
    client.delete("/api/v1/speicherorte/images")


def test_silence_an_empty_path_stays_empty_and_a_file_stays_a_file(client, tmp_path):
    for text in ("", "   "):
        answer = client.put(
            "/api/v1/speicherorte/images", json={"pfad": text}, headers={"X-Ui-Language": "en"}
        )
        assert answer.status_code == 400
        assert answer.json()["detail"] == "Enter a folder path"
    datei = tmp_path / "datei.txt"
    datei.write_text("x", encoding="utf-8")
    answer = client.put(
        "/api/v1/speicherorte/images", json={"pfad": str(datei)}, headers={"X-Ui-Language": "en"}
    )
    assert answer.json()["detail"] == "This path already points to a file, not a folder"
