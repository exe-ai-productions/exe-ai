"""The model server, seen from the API.

The runner itself is tested next door (test_modellrunner.py); here stands
what the endpoints add on top — above all that a started server joins the
model list by itself and leaves it when stopped. That link is the last one
in the chain "fetch, start, chat", and it was the one that broke.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import paketierung, runnermodellwahl, serverdownload
from app.api.v1 import runner as runner_api
from app.feineinstellungen import Feineinstellungen
from app.modellrunner import Lauf, RunnerFehler
from app.serverdownload import BUILD, Fortschritt, Serverdownload
from tests.conftest import llama_server_name, sized_file


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

    def projector_sizes(self):
        return {}

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
    assert runner.gestartet_mit["schichten"] is None
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
        "schichten": None,
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
                ordner=None, endungen=(".gguf",), manifest_ordner=None, nach=None,
                size=None):
        from app.modelldownload import Fortschritt

        self.gestartet += 1
        self.rolle = rolle
        self.ziel = ziel
        self.ordner = ordner
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


def _sparse(pfad, groesse):
    pfad.parent.mkdir(parents=True, exist_ok=True)
    sized_file(pfad, groesse)


VAE_BYTES = 335_304_388


def test_a_vae_of_another_size_under_the_name_is_not_tied(client, tmp_path):
    """A file of the same name and another size in vae/ is not the kit's
    VAE: it is never tied. The part comes as ``<repo>-<name>`` into the same
    folder and is tied under that name; the old file stays."""
    _sparse(tmp_path / "vae" / "ae.safetensors", 5)
    fang = FinishingDownload()
    client.app.state.modelldownload = fang
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    antwort = client.post("/api/v1/runner/download", json=_vae_request(size=VAE_BYTES))
    assert antwort.status_code == 200
    assert fang.gestartet == 1
    assert fang.ziel == "z_image_turbo-ae.safetensors"
    assert fang.ordner == str(tmp_path / "vae")
    assert _model_vae(client, "z_image_turbo-Q4_K_M.gguf") == "z_image_turbo-ae.safetensors"
    assert (tmp_path / "vae" / "ae.safetensors").stat().st_size == 5


def test_a_vae_of_the_same_size_is_only_tied(client, tmp_path):
    _sparse(tmp_path / "vae" / "ae.safetensors", VAE_BYTES)
    fang = FinishingDownload()
    client.app.state.modelldownload = fang
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    antwort = client.post("/api/v1/runner/download", json=_vae_request(size=VAE_BYTES))
    assert antwort.status_code == 200 and antwort.json()["fertig"] is True
    assert fang.gestartet == 0
    assert _model_vae(client, "z_image_turbo-Q4_K_M.gguf") == "ae.safetensors"


def test_a_vae_loose_in_the_model_folder_counts_by_name_and_size(client, tmp_path):
    """Where its content names it, a part may lie loose in the model folder:
    the same name and size is it, no sub-folder copy is made."""
    _sparse(tmp_path / "ae.safetensors", VAE_BYTES)
    fang = FinishingDownload()
    client.app.state.modelldownload = fang
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    antwort = client.post("/api/v1/runner/download", json=_vae_request(size=VAE_BYTES))
    assert antwort.status_code == 200 and fang.gestartet == 0


def test_a_vae_with_both_names_held_by_other_files_comes_under_the_third(client, tmp_path):
    """The name and ``<repo>-<name>`` are held by other files: the part is
    fetched under ``<owner>-<repo>-<name>`` and tied under that name."""
    _sparse(tmp_path / "vae" / "ae.safetensors", 5)
    _sparse(tmp_path / "vae" / "z_image_turbo-ae.safetensors", 6)
    fang = FinishingDownload()
    client.app.state.modelldownload = fang
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    antwort = client.post("/api/v1/runner/download", json=_vae_request(size=VAE_BYTES))
    assert antwort.status_code == 200
    assert fang.gestartet == 1
    assert fang.ziel == "Comfy-Org-z_image_turbo-ae.safetensors"
    assert _model_vae(client, "z_image_turbo-Q4_K_M.gguf") == "Comfy-Org-z_image_turbo-ae.safetensors"
    assert (tmp_path / "vae" / "ae.safetensors").stat().st_size == 5
    assert (tmp_path / "vae" / "z_image_turbo-ae.safetensors").stat().st_size == 6


def test_a_vae_with_all_three_names_held_by_other_files_is_refused(client, tmp_path):
    _sparse(tmp_path / "vae" / "ae.safetensors", 5)
    _sparse(tmp_path / "vae" / "z_image_turbo-ae.safetensors", 6)
    _sparse(tmp_path / "vae" / "Comfy-Org-z_image_turbo-ae.safetensors", 7)
    fang = FinishingDownload()
    client.app.state.modelldownload = fang
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    antwort = client.post("/api/v1/runner/download", json=_vae_request(size=VAE_BYTES))
    assert antwort.status_code == 409
    assert fang.gestartet == 0
    assert _model_vae(client, "z_image_turbo-Q4_K_M.gguf") is None


def test_a_model_kept_under_the_second_name_gets_its_parts_at_that_name(client, tmp_path):
    """The model's name in the folder is ``<repo>-<name>``: the parts that lie
    there already are written at that name, which is the one it is kept as."""
    from app import bildmodellwerte

    _sparse(tmp_path / "z_image_turbo-Q4_K_M.gguf", 7)
    _sparse(tmp_path / "vae" / "ae.safetensors", VAE_BYTES)
    fang = FinishingDownload()
    client.app.state.modelldownload = fang
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    antwort = client.post("/api/v1/runner/download", json={
        "repo": "wer/z_image_turbo-GGUF", "datei": "z_image_turbo-Q4_K_M.gguf",
        "art": "bild", "size": 4_500_000_000,
    })
    assert antwort.status_code == 200
    assert fang.ziel == "z_image_turbo-GGUF-z_image_turbo-Q4_K_M.gguf"
    eigene = bildmodellwerte.eigene(
        client.app.state.repositories, "z_image_turbo-GGUF-z_image_turbo-Q4_K_M.gguf"
    )
    assert eigene.get("vae") == "ae.safetensors"


def _krea_head(path):
    """A file whose head is that of a Krea 2 model, under a name that says
    nothing."""
    import json
    import struct

    kopf = {"model.diffusion_model.txtfusion.projector.weight":
            {"dtype": "F16", "shape": [4, 4], "data_offsets": [0, 0]}}
    roh = json.dumps(kopf).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(roh)) + roh)


def test_a_model_of_a_neutral_name_finds_the_parts_its_head_family_names(client, tmp_path):
    """``turbo.safetensors`` comes with a Krea 2 head: the parts of that
    family that lie in the folder already are written at it."""
    from app import bildmodellwerte

    _krea_head(tmp_path / "turbo.safetensors")
    _sparse(tmp_path / "vae" / "wan_2.1_vae.safetensors", 7)
    _sparse(tmp_path / "text_encoders" / "Qwen3VL-4B-Instruct-Q4_K_M.gguf", 7)
    client.app.state.modelldownload = FinishingDownload()
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    antwort = client.post("/api/v1/runner/download", json={
        "repo": "krea/Krea-2-Turbo", "datei": "turbo.safetensors", "art": "bild",
    })
    assert antwort.status_code == 200
    eigene = bildmodellwerte.eigene(client.app.state.repositories, "turbo.safetensors")
    assert eigene.get("vae") == "wan_2.1_vae.safetensors"
    assert eigene.get("llm") == "Qwen3VL-4B-Instruct-Q4_K_M.gguf"


def test_a_part_fetched_for_one_model_of_the_family_reaches_the_other_by_its_head(client, tmp_path):
    """The part belongs to every model whose kit names it — also one that
    lies in the folder as ``turbo.safetensors``."""
    from app import bildmodellwerte

    _krea_head(tmp_path / "turbo.safetensors")
    _krea_head(tmp_path / "krea-dev.safetensors")
    client.app.state.modelldownload = FinishingDownload()
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    antwort = client.post("/api/v1/runner/download", json={
        "repo": "Comfy-Org/Wan_2.1_ComfyUI_repackaged",
        "datei": "split_files/vae/wan_2.1_vae.safetensors", "art": "bild",
        "unterordner": "vae", "ziel": "wan_2.1_vae.safetensors",
        "gehoert_zu": "krea-dev.safetensors", "rolle": "vae",
    })
    assert antwort.status_code == 200
    assert _model_vae(client, "krea-dev.safetensors") == "wan_2.1_vae.safetensors"
    assert bildmodellwerte.eigene(
        client.app.state.repositories, "turbo.safetensors"
    ).get("vae") == "wan_2.1_vae.safetensors"


def test_a_lora_in_the_folder_gets_no_part(client, tmp_path):
    """Silence: a LoRA named like a model of the family gets nothing tied."""
    import json
    import struct

    kopf = {"diffusion_model.double_blocks.0.img_attn.proj.lora_A.weight":
            {"dtype": "F16", "shape": [4, 4], "data_offsets": [0, 0]}}
    roh = json.dumps(kopf).encode("utf-8")
    (tmp_path / "flux-style.safetensors").write_bytes(struct.pack("<Q", len(roh)) + roh)
    _sparse(tmp_path / "vae" / "ae.safetensors", 7)
    client.app.state.modelldownload = FinishingDownload()
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    antwort = client.post("/api/v1/runner/download", json={
        "repo": "wer/flux-style", "datei": "flux-style.safetensors", "art": "bild",
    })
    assert antwort.status_code == 200
    assert _model_vae(client, "flux-style.safetensors") is None


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


def test_an_encoder_of_another_name_is_tied_under_the_name_the_catalogue_gave(client, tmp_path):
    """The catalogue counts a Q8_0 as the part its Q4_K_M stands for and asks
    for it by the name it lies under: nothing is fetched, the bond names it."""
    (tmp_path / "text_encoders").mkdir()
    (tmp_path / "text_encoders" / "Qwen3-4B-Instruct-2507-Q8_0.gguf").write_bytes(b"da")
    fang = FinishingDownload()
    client.app.state.modelldownload = fang
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    antwort = client.post("/api/v1/runner/download", json=_llm_request(
        ziel="Qwen3-4B-Instruct-2507-Q8_0.gguf"
    ))
    assert antwort.status_code == 200 and antwort.json()["fertig"] is True
    assert fang.gestartet == 0
    assert _model_part(client, "z_image_turbo-Q4_K_M.gguf", "llm") == "Qwen3-4B-Instruct-2507-Q8_0.gguf"


def test_a_vision_part_already_there_is_tied_as_the_vision_field(client, tmp_path):
    """The projector lies in text_encoders/ with a vision head: the model
    that came for it gets it under its vision field, and nothing is fetched."""
    from tests.test_bildinhalt import clip_gguf_bytes

    (tmp_path / "text_encoders").mkdir()
    (tmp_path / "text_encoders" / "mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf").write_bytes(
        clip_gguf_bytes(vision=True)
    )
    fang = FinishingDownload()
    client.app.state.modelldownload = fang
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    antwort = client.post("/api/v1/runner/download", json={
        "repo": "Qwen/Qwen3-VL-8B-Instruct-GGUF",
        "datei": "mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf",
        "ziel": "mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf",
        "art": "bild", "unterordner": "text_encoders",
        "gehoert_zu": "qwen-image-2.1-Q4_K_M.gguf", "rolle": "llm_vision",
    })
    assert antwort.status_code == 200 and antwort.json()["fertig"] is True
    assert fang.gestartet == 0
    assert (
        _model_part(client, "qwen-image-2.1-Q4_K_M.gguf", "llm_vision")
        == "mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf"
    )


def test_a_model_that_arrives_finds_the_vision_part_that_is_there(client, tmp_path):
    from tests.test_bildinhalt import clip_gguf_bytes

    (tmp_path / "text_encoders").mkdir()
    (tmp_path / "text_encoders" / "mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf").write_bytes(
        clip_gguf_bytes(vision=True)
    )
    client.app.state.modelldownload = FinishingDownload()
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    antwort = client.post("/api/v1/runner/download", json={
        "repo": "wer/was", "datei": "qwen-image-2.1-turbo-Q4_K_M.gguf", "art": "bild",
    })
    assert antwort.status_code == 200
    assert (
        _model_part(client, "qwen-image-2.1-turbo-Q4_K_M.gguf", "llm_vision")
        == "mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf"
    )


# --- The program itself: its build, a newer one, and the way back ---------

NEWER = "b11541"


def _lay_build(folder: Path, build: str) -> Path:
    """A fetched build as it lies on disk: its folder, the server inside."""
    target = folder / "llama.cpp" / build / "build" / "bin"
    target.mkdir(parents=True)
    server = target / llama_server_name()
    server.write_bytes(b"x")
    return server


class _RecordingDownload:
    """Stands in for the fetch: keeps what it was asked for, fetches nothing."""

    def __init__(self):
        self.calls: list[tuple[str | None, str | None]] = []
        # The variant each fetch was asked for, beside the calls.
        self.variants: list[str | None] = []

    def stand(self):
        return Fortschritt(geladen=0, gesamt=0)

    def starten(self, build=None, previous=None, variante=None):
        self.calls.append((build, previous))
        self.variants.append(variante)
        return Fortschritt(geladen=0, gesamt=0)


def _program(client, monkeypatch, tmp_path, program: Path | None):
    """The program the runner would start, in a data folder of the test."""
    runner = StummerRunner()
    runner.programm = program
    client.app.state.modellrunner = runner
    monkeypatch.setattr(paketierung, "daten", lambda: tmp_path)
    download = _RecordingDownload()
    client.app.state.serverdownload = download
    return download


def _newest(monkeypatch, build: str | None):
    monkeypatch.setattr(serverdownload, "newest_build", lambda: build)


def test_the_status_names_the_build_of_the_program_that_starts(client, tmp_path, monkeypatch):
    _program(client, monkeypatch, tmp_path, _lay_build(tmp_path, BUILD))
    status = client.get("/api/v1/runner").json()
    assert status["version"] == BUILD
    assert status["updatable"] is True
    # The tested build is installed: there is nothing to go back from.
    assert status["restorable"] is False


def test_the_status_names_the_build_an_installed_program_states(client, tmp_path, monkeypatch):
    installed = tmp_path / "elsewhere" / llama_server_name()
    installed.parent.mkdir()
    installed.write_bytes(b"x")
    _program(client, monkeypatch, tmp_path / "data", installed)
    monkeypatch.setattr(serverdownload, "_stated_build", lambda program: 10310)
    status = client.get("/api/v1/runner").json()
    assert status["version"] == "b10310"
    # Not fetched by this program, so not this program's to go back from.
    assert status["restorable"] is False


def test_a_fetched_build_other_than_the_tested_one_can_be_restored(
    client, tmp_path, monkeypatch
):
    _program(client, monkeypatch, tmp_path, _lay_build(tmp_path, NEWER))
    status = client.get("/api/v1/runner").json()
    assert status["version"] == NEWER
    assert status["restorable"] is True


def test_the_check_reports_a_newer_build(client, tmp_path, monkeypatch):
    _program(client, monkeypatch, tmp_path, _lay_build(tmp_path, BUILD))
    _newest(monkeypatch, NEWER)
    answer = client.get("/api/v1/runner/programm/aktualisierung")
    assert answer.status_code == 200
    assert answer.json() == {
        "verfuegbar": True, "bau": NEWER, "aktuell": False, "unreadable": False,
    }


@pytest.mark.parametrize(("installed", "newest"), [(BUILD, BUILD), (NEWER, "b11500")])
def test_the_same_or_a_lower_build_is_up_to_date_and_nothing_is_fetched(
    client, tmp_path, monkeypatch, installed, newest
):
    """Silence probe: a build that is not ahead is no offer — and a click
    that arrives all the same fetches nothing."""
    download = _program(client, monkeypatch, tmp_path, _lay_build(tmp_path, installed))
    _newest(monkeypatch, newest)
    answer = client.get("/api/v1/runner/programm/aktualisierung").json()
    assert answer == {
        "verfuegbar": False, "bau": None, "aktuell": True, "unreadable": False,
    }
    refused = client.post("/api/v1/runner/programm", json={"aktualisieren": True})
    assert refused.status_code == 409
    assert download.calls == []


def test_an_unreadable_release_list_is_not_called_up_to_date(client, tmp_path, monkeypatch):
    """Not up to date, nothing on offer — and the answer says why, so the
    window tells the user the check found nothing to compare."""
    _program(client, monkeypatch, tmp_path, _lay_build(tmp_path, BUILD))
    _newest(monkeypatch, None)
    answer = client.get("/api/v1/runner/programm/aktualisierung").json()
    assert answer == {
        "verfuegbar": False, "bau": None, "aktuell": False, "unreadable": True,
    }


def test_updating_fetches_the_newest_build_read_at_that_moment(client, tmp_path, monkeypatch):
    download = _program(client, monkeypatch, tmp_path, _lay_build(tmp_path, BUILD))
    _newest(monkeypatch, NEWER)
    answer = client.post("/api/v1/runner/programm", json={"aktualisieren": True})
    assert answer.status_code == 200
    assert download.calls == [(NEWER, BUILD)]


def test_restoring_fetches_the_tested_build(client, tmp_path, monkeypatch):
    download = _program(client, monkeypatch, tmp_path, _lay_build(tmp_path, NEWER))
    answer = client.post("/api/v1/runner/programm", json={"restore": True})
    assert answer.status_code == 200
    assert download.calls == [(BUILD, NEWER)]


def test_an_installed_program_is_not_restored_from(client, tmp_path, monkeypatch):
    """Silence probe: a program this one did not fetch is not this
    program's to go back from, on any system."""
    installed = tmp_path / "elsewhere" / llama_server_name()
    installed.parent.mkdir()
    installed.write_bytes(b"x")
    download = _program(client, monkeypatch, tmp_path / "data", installed)
    monkeypatch.setattr(serverdownload, "_stated_build", lambda program: 11500)
    answer = client.post("/api/v1/runner/programm", json={"restore": True})
    assert answer.status_code == 409
    assert download.calls == []


def test_asked_for_both_the_way_back_counts(client, tmp_path, monkeypatch):
    download = _program(client, monkeypatch, tmp_path, _lay_build(tmp_path, NEWER))
    _newest(monkeypatch, "b11600")
    answer = client.post("/api/v1/runner/programm", json={"restore": True, "aktualisieren": True})
    assert answer.status_code == 200
    assert download.calls == [(BUILD, NEWER)]


def test_with_the_tested_build_installed_there_is_nothing_to_restore(
    client, tmp_path, monkeypatch
):
    """Silence probe, through the real fetch: it refuses the build that is
    already the one installed, and starts nothing."""
    _program(client, monkeypatch, tmp_path, _lay_build(tmp_path, BUILD))
    download = Serverdownload(tmp_path)
    client.app.state.serverdownload = download
    answer = client.post("/api/v1/runner/programm", json={"restore": True})
    assert answer.status_code == 409
    assert download.stand() is None


def test_a_program_named_in_the_settings_gets_no_offer(client, tmp_path, monkeypatch):
    """Silence probe: where the settings name the program, a fetched build
    would lie in the folder and never run — so the build is named, nothing
    is looked for, and nothing is fetched."""
    named = tmp_path / "own" / llama_server_name()
    named.parent.mkdir()
    named.write_bytes(b"x")
    download = _program(client, monkeypatch, tmp_path / "data", named)
    monkeypatch.setattr(client.app.state.config.app, "runner_programm", str(named))
    monkeypatch.setattr(serverdownload, "_stated_build", lambda program: 10310)

    def never():
        raise AssertionError("the release list was read although nothing can be offered")

    monkeypatch.setattr(serverdownload, "newest_build", never)
    status = client.get("/api/v1/runner").json()
    assert status["version"] == "b10310"
    assert status["updatable"] is False and status["restorable"] is False
    answer = client.get("/api/v1/runner/programm/aktualisierung").json()
    assert answer == {
        "verfuegbar": False, "bau": None, "aktuell": False, "unreadable": False,
    }
    for body in ({"aktualisieren": True}, {"restore": True}):
        assert client.post("/api/v1/runner/programm", json=body).status_code == 409
    assert download.calls == []


def test_the_plain_fetch_of_a_machine_without_a_server_is_unchanged(
    client, tmp_path, monkeypatch
):
    """Silence probe: no body, no program — the pinned build is asked for
    exactly as before, and the status offers nothing to look for."""
    download = _program(client, monkeypatch, tmp_path, None)
    status = client.get("/api/v1/runner").json()
    assert status["version"] is None
    assert status["updatable"] is False and status["restorable"] is False
    assert client.post("/api/v1/runner/programm").status_code == 200
    assert download.calls == [(None, None)]


@pytest.mark.parametrize(
    ("platform", "program", "own_first"),
    [
        # The Mac starts the fetched copy before any installed one.
        ("darwin", "installed", True),
        ("darwin", "fetched", True),
        # Elsewhere an installed program comes first: a fetched copy would
        # lie in the folder and never run.
        ("linux", "installed", False),
        ("win32", "installed", False),
        ("linux", "fetched", True),
        ("linux", None, True),
    ],
)
def test_a_fetched_copy_is_offered_only_where_it_would_start(
    config, tmp_path, monkeypatch, platform, program, own_first
):
    """The rule alone, without a running service: another system is played
    only for the one question, never around the service's own threads."""
    fetched = _lay_build(tmp_path, BUILD)
    installed = tmp_path / "elsewhere" / llama_server_name()
    installed.parent.mkdir()
    installed.write_bytes(b"x")
    path = {"installed": installed, "fetched": fetched, None: None}[program]

    fetched_tag = serverdownload.fetched_build(path, tmp_path) if path else None

    def asked() -> bool:
        with monkeypatch.context() as played:
            played.setattr(sys, "platform", platform)
            return runner_api._own_copy_first(config, path, fetched_tag)

    assert asked() is own_first
    # A program the settings name comes before everything, on every system.
    monkeypatch.setattr(config.app, "runner_programm", str(installed))
    assert asked() is False


# --- Windows: the variants of the server -----------------------------------


def _windows(monkeypatch) -> None:
    """Windows on x64 for the module that fetches the server, and only for
    it: the rest of the program that answers keeps the system it runs on."""
    monkeypatch.setattr(serverdownload, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(serverdownload.platform, "machine", lambda: "AMD64")


def _lay_windows_build(folder: Path, name: str) -> Path:
    """A fetched build as it lies on disk on Windows, by its folder's name."""
    target = folder / "llama.cpp" / name
    target.mkdir(parents=True)
    server = target / "llama-server.exe"
    server.write_bytes(b"MZ")
    return server


def test_windows_lists_the_four_variants_and_names_the_one_that_was_fetched(
    client, tmp_path, monkeypatch
):
    _windows(monkeypatch)
    server = _lay_windows_build(tmp_path, f"{BUILD}-cuda12")
    _program(client, monkeypatch, tmp_path, server)
    answer = client.get("/api/v1/runner/programm/varianten")
    assert answer.status_code == 200
    assert answer.json() == {
        "varianten": [
            {"variante": "cpu", "groesse": 19_398_918},
            {"variante": "cuda12", "groesse": 264_478_423 + 391_443_627},
            {"variante": "vulkan", "groesse": 33_337_769},
            {"variante": "rocm", "groesse": 256_958_369},
        ],
        "installiert": "cuda12",
    }


def test_the_other_systems_list_no_variant(client, tmp_path, monkeypatch):
    """Silence probe: on a Mac the list is empty and nothing is named."""
    # The test sets the system itself, like its neighbours: run on Windows it
    # would otherwise list the four variants of that system.
    monkeypatch.setattr(serverdownload, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(serverdownload.platform, "machine", lambda: "arm64")
    _program(client, monkeypatch, tmp_path, _lay_build(tmp_path, BUILD))
    answer = client.get("/api/v1/runner/programm/varianten")
    assert answer.status_code == 200
    assert answer.json() == {"varianten": [], "installiert": None}


def test_a_variant_that_is_asked_for_goes_to_the_fetch(client, tmp_path, monkeypatch):
    download = _program(client, monkeypatch, tmp_path, None)
    answer = client.post("/api/v1/runner/programm", json={"variante": "vulkan"})
    assert answer.status_code == 200
    assert download.calls == [(None, None)]
    assert download.variants == ["vulkan"]


def test_updating_keeps_the_variant_that_runs(client, tmp_path, monkeypatch):
    download = _program(client, monkeypatch, tmp_path, _lay_build(tmp_path, f"{BUILD}-cuda12"))
    _newest(monkeypatch, NEWER)
    assert client.post("/api/v1/runner/programm", json={"aktualisieren": True}).status_code == 200
    assert download.calls == [(NEWER, BUILD)]
    assert download.variants == ["cuda12"]


def test_the_way_back_keeps_the_variant_that_runs(client, tmp_path, monkeypatch):
    download = _program(client, monkeypatch, tmp_path, _lay_build(tmp_path, f"{NEWER}-vulkan"))
    assert client.post("/api/v1/runner/programm", json={"restore": True}).status_code == 200
    assert download.calls == [(BUILD, NEWER)]
    assert download.variants == ["vulkan"]


def test_an_update_of_the_plain_build_asks_for_the_default_variant(client, tmp_path, monkeypatch):
    """Silence probe: the build most machines have is the plain one."""
    download = _program(client, monkeypatch, tmp_path, _lay_build(tmp_path, BUILD))
    _newest(monkeypatch, NEWER)
    assert client.post("/api/v1/runner/programm", json={"aktualisieren": True}).status_code == 200
    assert download.variants == ["cpu"]


def test_an_unknown_variant_is_refused_and_nothing_is_fetched(client, tmp_path, monkeypatch):
    _windows(monkeypatch)
    _program(client, monkeypatch, tmp_path, None)
    download = Serverdownload(tmp_path)
    client.app.state.serverdownload = download
    answer = client.post("/api/v1/runner/programm", json={"variante": "cuda99"})
    assert answer.status_code == 400
    assert download.stand() is None
