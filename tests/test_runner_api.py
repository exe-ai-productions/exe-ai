"""The model server, seen from the API.

The runner itself is tested next door (test_modellrunner.py); here stands
what the endpoints add on top — above all that a started server joins the
model list by itself and leaves it when stopped. That link is the last one
in the chain "fetch, start, chat", and it was the one that broke.
"""

from __future__ import annotations

from pathlib import Path

from app import runnermodellwahl
from app.api.v1 import runner as runner_api
from app.feineinstellungen import Feineinstellungen
from app.modellrunner import Lauf, RunnerFehler


class StummerRunner:
    """Stands in for the real runner: keeps the story, starts nothing."""

    def __init__(self, ordner: Path = Path("/tmp")):
        self.ordner = ordner
        self.programm = Path("/bin/echo")
        self._lauf = None
        # The port this server answers on when nobody moved it — the real
        # runner's own property, which the route reads to answer "what would
        # a start take?" while nothing runs.
        self.port_vorgabe = 8080
        self.gestartet_mit = None

    def modelle(self):
        return []

    def mmproj(self):
        return []

    def mtp(self):
        return []

    def laeuft(self):
        return self._lauf is not None

    def lauf(self):
        return self._lauf

    def belegt_gb(self):
        return None

    def protokoll(self):
        return []

    def flash_attn_zustand(self):
        return None

    def unknown_architecture(self):
        return None

    def mtp_zustand(self):
        return None

    def starten(self, modell, *, kontext=8192, schichten=99, port=None, drafter=None,
                fein=None, vision=None):
        # Everything that arrived is kept, so a test can look at what the
        # route actually handed the runner — the point of the setting is that
        # none of it comes out of the request any more.
        self.fein = fein
        self.vision = vision
        self.gestartet_mit = {
            "modell": modell, "kontext": kontext, "schichten": schichten,
            "port": port, "drafter": drafter, "vision": vision, "fein": fein,
        }
        self._lauf = Lauf(
            modell=modell, kontext=kontext, schichten=schichten,
            port=self.port_vorgabe if port is None else port,
        )
        return self._lauf

    def stoppen(self):
        self._lauf = None
        return True


class KaputterRunner(StummerRunner):
    def starten(self, modell, **_):
        raise RunnerFehler("kein_modell")


def _wahl_setzen(client, wert):
    client.app.state.repositories.einstellungen.setzen(
        "global", runnermodellwahl.SCHLUESSEL, wert
    )


def test_start_meldet_den_server_bei_der_discovery_an(client):
    client.app.state.modellrunner = StummerRunner()
    _wahl_setzen(client, {"port": 8123})
    antwort = client.post("/api/v1/runner/start", json={"modell": "m.gguf"})
    assert antwort.status_code == 200

    zustand = client.app.state.discovery.zustaende.get("runner")
    assert zustand is not None
    assert zustand.endpunkt.base_url == "http://127.0.0.1:8123/v1"
    assert zustand.endpunkt.group == "local"
    assert zustand.endpunkt.parameter_dialect == "llama_cpp"


def test_stop_meldet_ihn_wieder_ab(client):
    client.app.state.modellrunner = StummerRunner()
    _wahl_setzen(client, {"port": 8123})
    client.post("/api/v1/runner/start", json={"modell": "m.gguf"})
    client.post("/api/v1/runner/stop")
    assert "runner" not in client.app.state.discovery.zustaende


# --- The start choice lives on the server, not in a browser ------


def test_der_start_nimmt_die_gespeicherte_wahl_und_nicht_den_rumpf(client):
    """Window, layers, port and the module for exactly this file all come out
    of the setting — and a number smuggled into the request body changes
    nothing, because the body no longer carries one."""
    runner = StummerRunner()
    client.app.state.modellrunner = runner
    _wahl_setzen(client, {
        "kontext": 65536,
        "schichten": 40,
        "port": 8125,
        "module": {"m.gguf": {"drafter": "mtp-m.gguf", "vision": "m-mmproj.gguf"}},
    })

    antwort = client.post(
        "/api/v1/runner/start",
        json={"modell": "m.gguf", "kontext": 4096, "port": 9999},
    )
    assert antwort.status_code == 200
    assert runner.gestartet_mit == {
        "modell": "m.gguf", "kontext": 65536, "schichten": 40, "port": 8125,
        "drafter": "mtp-m.gguf", "vision": "m-mmproj.gguf",
        "fein": runner.gestartet_mit["fein"],
    }
    assert isinstance(runner.gestartet_mit["fein"], Feineinstellungen)
    zustand = client.app.state.discovery.zustaende.get("runner")
    assert zustand.endpunkt.base_url == "http://127.0.0.1:8125/v1"


def test_ohne_gespeicherte_wahl_gelten_die_vorgaben(client):
    """Nothing stored is the fresh install: the fallbacks come from the one
    module that owns them, and the port stays the server's own."""
    runner = StummerRunner()
    client.app.state.modellrunner = runner
    antwort = client.post("/api/v1/runner/start", json={"modell": "m.gguf"})
    assert antwort.status_code == 200
    assert runner.gestartet_mit["kontext"] == runnermodellwahl.KONTEXT_VORGABE
    assert runner.gestartet_mit["schichten"] == runnermodellwahl.SCHICHTEN_VORGABE
    # None: the runner falls back to its own port rather than to a number
    # written down a second time here.
    assert runner.gestartet_mit["port"] is None
    assert runner.gestartet_mit["drafter"] is None
    assert antwort.json()["port"] == runner.port_vorgabe


def test_ein_start_merkt_sich_die_datei_als_hauptmodell(client):
    """Whatever started IS the main model afterwards — the record every start
    path passes, so a start from the catalogue cannot leave the choice
    pointing at the file before it."""
    client.app.state.modellrunner = StummerRunner()
    _wahl_setzen(client, {"modell": "alt.gguf", "kontext": 16384})
    client.post("/api/v1/runner/start", json={"modell": "neu.gguf"})

    repositories = client.app.state.repositories
    assert runnermodellwahl.modell(repositories) == "neu.gguf"
    # And it kept the rest of the choice standing.
    assert runnermodellwahl.wahl(repositories)["kontext"] == 16384


def test_die_auskunft_nennt_die_vorgaben(client):
    """The page is told what an unset field falls back to instead of writing
    the numbers down a second time."""
    client.app.state.modellrunner = StummerRunner()
    daten = client.get("/api/v1/runner").json()
    assert daten["vorgaben"] == {
        "kontext": runnermodellwahl.KONTEXT_VORGABE,
        "schichten": runnermodellwahl.SCHICHTEN_VORGABE,
        "port": None,
        # May the program bring this server up ahead of a due cron entry?
        # Shipped on, so an installation that has never seen the tick box
        # preloads exactly as it did before the box existed.
        "vorladen": True,
    }


def test_die_wahl_ueberlebt_ohne_browser(client):
    """The core of the stage: what was chosen is readable from the backend,
    with nothing but the database — no page, no request body, no session."""
    _wahl_setzen(client, {"modell": "gross.gguf", "kontext": 65536, "schichten": 40})
    repositories = client.app.state.repositories
    assert runnermodellwahl.modell(repositories) == "gross.gguf"
    werte = runnermodellwahl.startwerte(repositories, "gross.gguf")
    assert werte["kontext"] == 65536
    assert werte["schichten"] == 40


def test_ein_fehlstart_meldet_nichts_an(client):
    client.app.state.modellrunner = KaputterRunner()
    antwort = client.post("/api/v1/runner/start", json={"modell": "fehlt.gguf"})
    assert antwort.status_code == 404
    assert "runner" not in client.app.state.discovery.zustaende


def test_download_legt_zubehoer_in_den_unterordner(client):
    """A companion with `unterordner` lands in that sub-folder of its art — the
    endpoint joins the folder before handing the download off, so a VAE reaches
    data/bildmodelle/vae/ and shows up in the picture window at once."""
    from app.modelldownload import Fortschritt

    gefangen = {}

    class FangDownload:
        def starten(self, repo, datei, ziel=None, gehoert_zu=None, rolle=None,
                    ordner=None, endungen=(".gguf",), manifest_ordner=None, nach=None):
            gefangen["ordner"] = ordner
            return Fortschritt(datei=datei, geladen=0, gesamt=0)

        def stand(self):
            return Fortschritt(datei="vae.safetensors", geladen=0, gesamt=1)

    client.app.state.modelldownload = FangDownload()
    client.app.state.modellordner_je_art = {
        "bild": "/data/bildmodelle", "chat": "/data/modelle",
    }
    antwort = client.post(
        "/api/v1/runner/download",
        json={"repo": "r", "datei": "vae.safetensors", "art": "bild", "unterordner": "vae"},
    )
    assert antwort.status_code == 200
    assert gefangen["ordner"] == str(Path("/data/bildmodelle", "vae"))


def test_download_ohne_unterordner_bleibt_in_der_wurzel(client):
    from app.modelldownload import Fortschritt

    gefangen = {}

    class FangDownload:
        def starten(self, repo, datei, ziel=None, gehoert_zu=None, rolle=None,
                    ordner=None, endungen=(".gguf",), manifest_ordner=None, nach=None):
            gefangen["ordner"] = ordner
            return Fortschritt(datei=datei, geladen=0, gesamt=0)

        def stand(self):
            return Fortschritt(datei="m.gguf", geladen=0, gesamt=1)

    client.app.state.modelldownload = FangDownload()
    client.app.state.modellordner_je_art = {"chat": "/data/modelle"}
    antwort = client.post(
        "/api/v1/runner/download", json={"repo": "r", "datei": "m.gguf", "art": "chat"}
    )
    assert antwort.status_code == 200
    assert gefangen["ordner"] == "/data/modelle"


def test_der_modellordner_laesst_sich_zeigen(client, tmp_path, monkeypatch):
    client.app.state.modellrunner = StummerRunner(ordner=tmp_path / "modelle")
    gezeigt = []
    monkeypatch.setattr(runner_api, "ordner_oeffnen", gezeigt.append)

    antwort = client.post("/api/v1/runner/folder")
    assert antwort.status_code == 200
    assert gezeigt == [tmp_path / "modelle"]


def test_ohne_dateimanager_kommt_ein_satz(client, monkeypatch):
    client.app.state.modellrunner = StummerRunner()

    def geht_nicht(_):
        raise runner_api.OeffnenNichtMoeglich()

    monkeypatch.setattr(runner_api, "ordner_oeffnen", geht_nicht)
    assert client.post("/api/v1/runner/folder").status_code == 501


def test_ein_textleser_landet_in_text_encoders(client):
    """A kit's text encoder goes to text_encoders/, the folder the picture
    side reads its encoders from, not loose into the main folder."""
    from app.modelldownload import Fortschritt

    gefangen = {}

    class FangDownload:
        def starten(self, repo, datei, ziel=None, gehoert_zu=None, rolle=None,
                    ordner=None, endungen=(".gguf",), manifest_ordner=None, nach=None):
            gefangen["ordner"] = ordner
            return Fortschritt(datei=datei, geladen=0, gesamt=0)

        def stand(self):
            return Fortschritt(datei="qwen_3_4b.safetensors", geladen=0, gesamt=1)

    client.app.state.modelldownload = FangDownload()
    client.app.state.modellordner_je_art = {"bild": "/data/bildmodelle"}
    antwort = client.post("/api/v1/runner/download", json={
        "repo": "r", "datei": "qwen_3_4b.safetensors", "art": "bild", "unterordner": "text_encoders",
    })
    assert antwort.status_code == 200
    assert gefangen["ordner"] == str(Path("/data/bildmodelle", "text_encoders"))


def test_ein_geteilter_textleser_wird_nicht_zweimal_geladen(client, tmp_path):
    """Two kits naming the same encoder: the second download finds it in
    text_encoders/ and fetches nothing."""
    from app.modelldownload import Modelldownload

    (tmp_path / "text_encoders").mkdir()
    (tmp_path / "text_encoders" / "qwen_3_4b.safetensors").write_bytes(b"schon da")
    client.app.state.modelldownload = Modelldownload(tmp_path)
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    antwort = client.post("/api/v1/runner/download", json={
        "repo": "r", "datei": "qwen_3_4b.safetensors", "art": "bild", "unterordner": "text_encoders",
    })
    assert antwort.status_code == 409


def _vae_request(**anders):
    wunsch = {
        "repo": "Comfy-Org/z_image_turbo", "datei": "split_files/vae/ae.safetensors",
        "art": "bild", "unterordner": "vae", "ziel": "ae.safetensors",
        "gehoert_zu": "z_image_turbo-Q4_K_M.gguf", "rolle": "vae",
    }
    wunsch.update(anders)
    return wunsch


def _model_vae(client, modell):
    from app import bildmodellwerte

    return bildmodellwerte.eigene(client.app.state.repositories, modell).get("vae")


class FinishingDownload:
    """A download that finishes on the spot: it only runs ``nach``."""

    def __init__(self):
        self.gestartet = 0

    def starten(self, repo, datei, ziel=None, gehoert_zu=None, rolle=None,
                ordner=None, endungen=(".gguf",), manifest_ordner=None, nach=None):
        from app.modelldownload import Fortschritt

        self.gestartet += 1
        self.rolle = rolle
        if nach is not None:
            nach()
        return Fortschritt(datei=ziel or datei, geladen=1, gesamt=1, fertig=True)

    def stand(self):
        from app.modelldownload import Fortschritt

        return Fortschritt(datei="ae.safetensors", geladen=1, gesamt=1, fertig=True)


def test_the_fetched_vae_is_written_at_the_model(client, tmp_path):
    """A VAE fetched with the model it came for is that model's VAE: it
    stands in the model's own values once the file is in place."""
    fang = FinishingDownload()
    client.app.state.modelldownload = fang
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    assert _model_vae(client, "z_image_turbo-Q4_K_M.gguf") is None
    antwort = client.post("/api/v1/runner/download", json=_vae_request())
    assert antwort.status_code == 200
    assert fang.gestartet == 1
    # The bond is the model's own value, not a companion of the folder manifest.
    assert fang.rolle is None
    assert _model_vae(client, "z_image_turbo-Q4_K_M.gguf") == "ae.safetensors"


def test_the_vae_is_written_only_after_the_fetch(client, tmp_path):
    """A fetch that never finishes leaves no bond behind."""

    class Haengt(FinishingDownload):
        def starten(self, *args, nach=None, **kwargs):
            from app.modelldownload import Fortschritt

            return Fortschritt(datei="ae.safetensors", geladen=0, gesamt=1)

    client.app.state.modelldownload = Haengt()
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    assert client.post("/api/v1/runner/download", json=_vae_request()).status_code == 200
    assert _model_vae(client, "z_image_turbo-Q4_K_M.gguf") is None


def test_a_vae_already_there_is_only_tied(client, tmp_path):
    """The kit's VAE lies in vae/ already: nothing is fetched, the bond is
    written and the answer says it is done — no 409 for a VAE that is there."""
    (tmp_path / "vae").mkdir()
    (tmp_path / "vae" / "ae.safetensors").write_bytes(b"schon da")
    fang = FinishingDownload()
    client.app.state.modelldownload = fang
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    antwort = client.post("/api/v1/runner/download", json=_vae_request())
    assert antwort.status_code == 200
    assert antwort.json()["fertig"] is True
    assert fang.gestartet == 0
    assert _model_vae(client, "z_image_turbo-Q4_K_M.gguf") == "ae.safetensors"


def test_another_model_does_not_get_the_vae(client, tmp_path):
    """Silence: the bond names one model; every other keeps its values."""
    client.app.state.modelldownload = FinishingDownload()
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    client.post("/api/v1/runner/download", json=_vae_request())
    assert _model_vae(client, "flux1-dev-Q8_0.gguf") is None


def test_a_part_without_a_role_ties_nothing(client, tmp_path):
    """Silence: only the VAE role writes a bond at the model."""
    client.app.state.modelldownload = FinishingDownload()
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    client.post("/api/v1/runner/download", json=_vae_request(
        rolle=None, gehoert_zu=None, unterordner="text_encoders", datei="qwen.gguf", ziel="qwen.gguf",
    ))
    assert _model_vae(client, "z_image_turbo-Q4_K_M.gguf") is None


def test_a_vae_name_with_a_path_is_not_tied(client, tmp_path):
    """Silence: a name that climbs out of the folder is neither probed nor tied;
    the download refuses it."""
    (tmp_path / "geheim.safetensors").write_bytes(b"x")
    fang = FinishingDownload()
    client.app.state.modelldownload = fang
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    client.post("/api/v1/runner/download", json=_vae_request(ziel="../geheim.safetensors"))
    assert _model_vae(client, "z_image_turbo-Q4_K_M.gguf") is None


def test_a_vae_chosen_by_hand_stays_when_tying(client, tmp_path):
    """Silence: the kit's VAE was lying there all along and the model carries
    a VAE chosen by hand — tying does not replace it."""
    from app import bildmodellwerte

    (tmp_path / "vae").mkdir()
    (tmp_path / "vae" / "ae.safetensors").write_bytes(b"schon da")
    client.app.state.modelldownload = FinishingDownload()
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    bildmodellwerte.set_part(
        client.app.state.repositories, "z_image_turbo-Q4_K_M.gguf", "vae", "eigene.safetensors"
    )
    assert client.post("/api/v1/runner/download", json=_vae_request()).status_code == 200
    assert _model_vae(client, "z_image_turbo-Q4_K_M.gguf") == "eigene.safetensors"


def test_a_freshly_fetched_vae_replaces_the_old_one(client, tmp_path):
    """A download that brings the kit's VAE writes it at the model."""
    from app import bildmodellwerte

    client.app.state.modelldownload = FinishingDownload()
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    bildmodellwerte.set_part(
        client.app.state.repositories, "z_image_turbo-Q4_K_M.gguf", "vae", "eigene.safetensors"
    )
    client.post("/api/v1/runner/download", json=_vae_request())
    assert _model_vae(client, "z_image_turbo-Q4_K_M.gguf") == "ae.safetensors"


# --- The text encoders of a kit, and the family's other models --------------


def _llm_request(**anders):
    wunsch = {
        "repo": "unsloth/Qwen3-4B-Instruct-2507-GGUF",
        "datei": "Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
        "ziel": "Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
        "art": "bild", "unterordner": "text_encoders",
        "gehoert_zu": "z_image_turbo-Q4_K_M.gguf", "rolle": "llm",
    }
    wunsch.update(anders)
    return wunsch


def _model_part(client, modell, feld):
    from app import bildmodellwerte

    return bildmodellwerte.eigene(client.app.state.repositories, modell).get(feld)


def test_the_fetched_text_encoder_is_written_at_the_model(client, tmp_path):
    """A text encoder fetched with the model it came for is written at that
    model, under its own field — nobody picks it by hand."""
    client.app.state.modelldownload = FinishingDownload()
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    assert _model_part(client, "z_image_turbo-Q4_K_M.gguf", "llm") is None
    assert client.post("/api/v1/runner/download", json=_llm_request()).status_code == 200
    assert _model_part(client, "z_image_turbo-Q4_K_M.gguf", "llm") == "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
    # Only its own field: the VAE is another part.
    assert _model_part(client, "z_image_turbo-Q4_K_M.gguf", "vae") is None


def test_a_text_encoder_already_there_is_only_tied(client, tmp_path):
    """The encoder lies in text_encoders/ already: nothing is fetched, the
    bond is written, and no 409 comes back."""
    (tmp_path / "text_encoders").mkdir()
    (tmp_path / "text_encoders" / "Qwen3-4B-Instruct-2507-Q4_K_M.gguf").write_bytes(b"schon da")
    fang = FinishingDownload()
    client.app.state.modelldownload = fang
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    antwort = client.post("/api/v1/runner/download", json=_llm_request())
    assert antwort.status_code == 200 and antwort.json()["fertig"] is True
    assert fang.gestartet == 0
    assert _model_part(client, "z_image_turbo-Q4_K_M.gguf", "llm") == "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"


def test_every_part_of_the_family_table_is_an_accepted_role(client, tmp_path):
    """Every part the family table names a source for can be tied: its field
    is a role the download takes."""
    from app import image_families, kit_bond

    client.app.state.modelldownload = FinishingDownload()
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    felder = {teil.part for f in image_families.FAMILIES for teil in f.kit_parts}
    assert felder == set(kit_bond.FIELDS)
    for feld in felder:
        antwort = client.post("/api/v1/runner/download", json=_llm_request(rolle=feld))
        assert antwort.status_code == 200, feld
    # Silence: a role nobody knows is refused at the door.
    assert client.post("/api/v1/runner/download", json=_llm_request(rolle="lora")).status_code == 422


def test_the_part_also_goes_to_the_other_models_of_the_family(client, tmp_path):
    """A part is shared by the models whose kit names it: a second Z-Image
    in the folder gets both, a Flux the VAE its kit names too and not the
    encoder — and a model whose kit names neither gets nothing."""
    (tmp_path / "z_image_turbo-Q8_0.gguf").write_bytes(b"modell")
    (tmp_path / "flux1-dev-Q8_0.gguf").write_bytes(b"modell")
    (tmp_path / "Krea-2-Raw-Q8_0.gguf").write_bytes(b"modell")
    client.app.state.modelldownload = FinishingDownload()
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    client.post("/api/v1/runner/download", json=_llm_request())
    client.post("/api/v1/runner/download", json=_vae_request())
    assert _model_part(client, "z_image_turbo-Q8_0.gguf", "llm") == "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
    assert _model_part(client, "z_image_turbo-Q8_0.gguf", "vae") == "ae.safetensors"
    assert _model_part(client, "flux1-dev-Q8_0.gguf", "llm") is None
    assert _model_part(client, "flux1-dev-Q8_0.gguf", "vae") == "ae.safetensors"
    assert _model_part(client, "Krea-2-Raw-Q8_0.gguf", "llm") is None
    assert _model_part(client, "Krea-2-Raw-Q8_0.gguf", "vae") is None


def test_a_part_of_another_size_stays_away(client, tmp_path):
    """Silence: the encoder of a Flux.2 klein 4B is no part of a klein 9B in
    the same folder, though both are one family."""
    (tmp_path / "flux-2-klein-9b-Q4_K_M.gguf").write_bytes(b"modell")
    client.app.state.modelldownload = FinishingDownload()
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    client.post("/api/v1/runner/download", json={
        "repo": "unsloth/Qwen3-4B-GGUF", "datei": "Qwen3-4B-Q4_K_M.gguf", "art": "bild",
        "unterordner": "text_encoders", "gehoert_zu": "flux-2-klein-4b-Q4_K_M.gguf",
        "rolle": "llm",
    })
    assert _model_part(client, "flux-2-klein-4b-Q4_K_M.gguf", "llm") == "Qwen3-4B-Q4_K_M.gguf"
    assert _model_part(client, "flux-2-klein-9b-Q4_K_M.gguf", "llm") is None


def test_the_other_model_keeps_its_own_part(client, tmp_path):
    """Silence: a part another model of the family was given by hand stays."""
    from app import bildmodellwerte

    (tmp_path / "z_image_turbo-Q8_0.gguf").write_bytes(b"modell")
    client.app.state.modelldownload = FinishingDownload()
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    bildmodellwerte.set_part(client.app.state.repositories, "z_image_turbo-Q8_0.gguf", "llm", "eigener.gguf")
    client.post("/api/v1/runner/download", json=_llm_request())
    assert _model_part(client, "z_image_turbo-Q8_0.gguf", "llm") == "eigener.gguf"


def test_a_foreign_part_goes_only_to_the_named_model(client, tmp_path):
    """Silence: a file that is not the family's own part is written at the
    model it was asked for and at no other."""
    (tmp_path / "z_image_turbo-Q8_0.gguf").write_bytes(b"modell")
    client.app.state.modelldownload = FinishingDownload()
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    client.post("/api/v1/runner/download", json=_llm_request(datei="anderer.gguf", ziel="anderer.gguf"))
    assert _model_part(client, "z_image_turbo-Q4_K_M.gguf", "llm") == "anderer.gguf"
    assert _model_part(client, "z_image_turbo-Q8_0.gguf", "llm") is None


def test_a_model_that_arrives_finds_the_parts_that_are_there(client, tmp_path):
    """A second model of a family, asked for while the parts were on their way
    for the first: when it arrives, the parts lying there are written at it."""
    (tmp_path / "text_encoders").mkdir()
    (tmp_path / "text_encoders" / "Qwen3-4B-Instruct-2507-Q4_K_M.gguf").write_bytes(b"da")
    (tmp_path / "vae").mkdir()
    (tmp_path / "vae" / "ae.safetensors").write_bytes(b"da")
    client.app.state.modelldownload = FinishingDownload()
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    antwort = client.post("/api/v1/runner/download", json={
        "repo": "leejet/Z-Image-Turbo-GGUF", "datei": "z_image_turbo-Q8_0.gguf", "art": "bild",
    })
    assert antwort.status_code == 200
    assert _model_part(client, "z_image_turbo-Q8_0.gguf", "llm") == "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
    assert _model_part(client, "z_image_turbo-Q8_0.gguf", "vae") == "ae.safetensors"


def test_a_model_that_arrives_gets_no_part_that_is_missing(client, tmp_path):
    """Silence: a part that is not there is not written, and a model without
    a kit gets nothing at all."""
    (tmp_path / "vae").mkdir()
    (tmp_path / "vae" / "ae.safetensors").write_bytes(b"da")
    client.app.state.modelldownload = FinishingDownload()
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    for datei in ("z_image_turbo-Q8_0.gguf", "sd_xl_base_1.0.safetensors"):
        client.post("/api/v1/runner/download", json={"repo": "wer/was", "datei": datei, "art": "bild"})
    assert _model_part(client, "z_image_turbo-Q8_0.gguf", "llm") is None
    assert _model_part(client, "z_image_turbo-Q8_0.gguf", "vae") == "ae.safetensors"
    assert _model_part(client, "sd_xl_base_1.0.safetensors", "vae") is None
