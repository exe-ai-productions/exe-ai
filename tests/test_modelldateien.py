"""The file list of a found repository.

Nothing here talks to Hugging Face: the answer is faked, because what is
being tested is our side — which files we consider startable, in which
order they come back, and what happens when the other side has a bad day.
"""

from __future__ import annotations

import httpx
import pytest

from app.api.v1 import modelldateien


class FalscheAntwort:
    def __init__(self, daten, fehler=None, links=None):
        self._daten = daten
        self._fehler = fehler
        self.links = links or {}

    def raise_for_status(self):
        if self._fehler:
            raise self._fehler

    def json(self):
        return self._daten


class FalscherKlient:
    letzte_adresse: str | None = None

    def __init__(self, daten, fehler=None):
        self._antwort = FalscheAntwort(daten, fehler)

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, adresse, params=None):
        FalscherKlient.letzte_adresse = adresse
        if isinstance(self._antwort._fehler, httpx.HTTPError):
            raise self._antwort._fehler
        return self._antwort

    # The size of one part of a kit is asked for with a POST; the faked hub
    # answers it from ``SIZES``, by repository and path.
    async def post(self, adresse, data=None):
        repo = adresse.split("/api/models/")[1].split("/paths-info")[0]
        pfad = data["paths"]
        groesse = SIZES.get((repo, pfad))
        zeilen = [] if groesse is None else [{"type": "file", "path": pfad, "size": groesse}]
        return FalscheAntwort(zeilen)


SIZES: dict[tuple[str, str], int] = {}


@pytest.fixture(autouse=True)
def _clear_sizes():
    SIZES.clear()


@pytest.fixture
def baum(monkeypatch):
    def setzen(daten, fehler=None):
        monkeypatch.setattr(
            modelldateien.httpx, "AsyncClient", FalscherKlient(daten, fehler)
        )
    return setzen


def _eintrag(pfad, groesse, art="file"):
    return {"type": art, "path": pfad, "size": groesse}


# --- What counts as a file ------------------------------------------------


def test_nur_startbare_gguf_dateien_kommen_zurueck(client, baum):
    baum(
        [
            _eintrag("README.md", 4000),
            _eintrag("modell-F16.gguf", 20_000_000_000),
            _eintrag("modell-Q4_K_M.gguf", 5_000_000_000),
            # A shard alone is not a model — fetching one produces a file
            # that looks like a model and is not.
            _eintrag("gross-00001-of-00003.gguf", 9_000_000_000),
            # A vision companion is no model either — it rides along in its
            # own field instead.
            _eintrag("mmproj-BF16.gguf", 900_000_000),
            "kein Eintrag",
        ]
    )
    antwort = client.get("/api/v1/models/files?repo=wer/was")
    assert antwort.status_code == 200
    daten = antwort.json()
    assert [d["datei"] for d in daten["dateien"]] == ["modell-Q4_K_M.gguf", "modell-F16.gguf"]
    assert daten["mmproj"]["datei"] == "mmproj-BF16.gguf"


def test_ohne_projektor_bleibt_das_feld_leer(client, baum):
    baum([_eintrag("modell.gguf", 5_000_000_000)])
    assert client.get("/api/v1/models/files?repo=wer/was").json()["mmproj"] is None


def test_der_kleinste_projektor_wird_genannt(client, baum):
    # They only differ in precision, and the small one sees the same.
    baum(
        [
            _eintrag("modell.gguf", 5_000_000_000),
            _eintrag("modell-mmproj-F32.gguf", 1_800_000_000),
            _eintrag("modell-mmproj-Q8_0.gguf", 600_000_000),
        ]
    )
    daten = client.get("/api/v1/models/files?repo=wer/was").json()
    assert daten["mmproj"]["datei"] == "modell-mmproj-Q8_0.gguf"


def test_kleinste_datei_steht_vorn(client, baum):
    # "Which one fits my machine" is answered from small to large.
    baum(
        [
            _eintrag("gross.gguf", 30_000_000_000),
            _eintrag("klein.gguf", 2_000_000_000),
        ]
    )
    dateien = client.get("/api/v1/models/files?repo=wer/was").json()["dateien"]
    assert dateien[0]["datei"] == "klein.gguf"
    assert dateien[0]["groesse_gb"] == 2.0


def test_der_repo_name_steht_in_der_adresse(client, baum):
    baum([])
    client.get("/api/v1/models/files?repo=wer/was")
    assert "/wer/was/tree/main" in FalscherKlient.letzte_adresse
    # Sub-folders are read too.
    assert FalscherKlient.letzte_adresse.endswith("?recursive=true")


# --- The image tab --------------------------------------------------------


def test_bild_reiter_zeigt_safetensors(client, baum):
    baum(
        [
            _eintrag("krea2_turbo_fp8.safetensors", 12_900_000_000),
            _eintrag("bild-Q4_0.gguf", 7_000_000_000),
            # A split checkpoint is never offered — the image server reads
            # single files.
            _eintrag("gross-00001-of-00003.safetensors", 9_000_000_000),
            _eintrag("gross-00002-of-00003.safetensors", 9_000_000_000),
            _eintrag("gross-00003-of-00003.safetensors", 9_000_000_000),
            _eintrag("notizen.txt", 100),
        ]
    )
    dateien = client.get("/api/v1/models/files?repo=wer/was&art=bild").json()["dateien"]
    assert [d["datei"] for d in dateien] == ["bild-Q4_0.gguf", "krea2_turbo_fp8.safetensors"]
    assert dateien[1]["groesse_gb"] == 12.9


def test_chat_reiter_zeigt_keine_safetensors(client, baum):
    baum(
        [
            _eintrag("krea2_turbo_fp8.safetensors", 12_900_000_000),
            _eintrag("modell.gguf", 5_000_000_000),
        ]
    )
    for adresse in ("/api/v1/models/files?repo=wer/was", "/api/v1/models/files?repo=wer/was&art=chat"):
        dateien = client.get(adresse).json()["dateien"]
        assert [d["datei"] for d in dateien] == ["modell.gguf"]


def test_unbekannte_art_wird_abgelehnt(client, baum):
    baum([])
    assert client.get("/api/v1/models/files?repo=wer/was&art=alles").status_code == 422


# --- Sub-folders ----------------------------------------------------------


def test_dateien_in_unterordnern_erscheinen_mit_ihrem_pfad(client, baum):
    baum(
        [
            _eintrag("IQ2_XS", 0, art="directory"),
            _eintrag("IQ2_XS/x.gguf", 3_000_000_000),
            _eintrag("Q4_K_M/x.gguf", 5_000_000_000),
            _eintrag("mmproj-BF16.gguf", 900_000_000),
        ]
    )
    daten = client.get("/api/v1/models/files?repo=wer/was").json()
    assert [d["datei"] for d in daten["dateien"]] == ["IQ2_XS/x.gguf", "Q4_K_M/x.gguf"]
    assert daten["mmproj"]["datei"] == "mmproj-BF16.gguf"


def test_ein_ordner_der_wie_ein_modell_heisst_ist_keine_datei(client, baum):
    baum([_eintrag("seltsam.gguf", 0, art="directory")])
    assert client.get("/api/v1/models/files?repo=wer/was").json()["dateien"] == []


# --- Split models ---------------------------------------------------------


def test_zwei_teile_werden_eine_zeile(client, baum):
    baum(
        [
            _eintrag("Q2_0/m-Q2_0-00001-of-00002.gguf", 37_623_740_192),
            _eintrag("Q2_0/m-Q2_0-00002-of-00002.gguf", 28_800_138_432),
            _eintrag("einzeln.gguf", 2_000_000_000),
        ]
    )
    dateien = client.get("/api/v1/models/files?repo=wer/was").json()["dateien"]
    assert dateien == [
        {"datei": "einzeln.gguf", "groesse_gb": 2.0, "teile": 1, "bausatz": None},
        {"datei": "Q2_0/m-Q2_0-00001-of-00002.gguf", "groesse_gb": 66.4, "teile": 2, "bausatz": None},
    ]


def test_fehlt_ein_teil_erscheint_die_fassung_nicht(client, baum):
    baum(
        [
            _eintrag("m-00001-of-00003.gguf", 9_000_000_000),
            _eintrag("m-00003-of-00003.gguf", 9_000_000_000),
        ]
    )
    assert client.get("/api/v1/models/files?repo=wer/was").json()["dateien"] == []


def test_zwei_fassungen_in_zwei_ordnern_bleiben_getrennt(client, baum):
    baum(
        [
            _eintrag("A/m-00001-of-00002.gguf", 1_000_000_000),
            _eintrag("A/m-00002-of-00002.gguf", 1_000_000_000),
            _eintrag("B/m-00001-of-00002.gguf", 3_000_000_000),
        ]
    )
    dateien = client.get("/api/v1/models/files?repo=wer/was").json()["dateien"]
    assert [(d["datei"], d["teile"]) for d in dateien] == [("A/m-00001-of-00002.gguf", 2)]


# --- Pages ----------------------------------------------------------------


class SeitenKlient:
    """Hands out one page per address; the first names the next one."""

    def __init__(self, seiten):
        self._seiten = seiten
        self.adressen: list[str] = []

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, adresse, params=None):
        self.adressen.append(adresse)
        daten, weiter = self._seiten[len(self.adressen) - 1]
        return FalscheAntwort(daten, links={"next": {"url": weiter}} if weiter else None)


def test_eine_lange_liste_wird_bis_zum_ende_gelesen(client, monkeypatch):
    weiter = "https://huggingface.co/api/models/wer/was/tree/main?recursive=true&cursor=abc"
    klient = SeitenKlient(
        [
            ([_eintrag("a.gguf", 1_000_000_000)], weiter),
            ([_eintrag("b.gguf", 2_000_000_000)], None),
        ]
    )
    monkeypatch.setattr(modelldateien.httpx, "AsyncClient", klient)
    dateien = client.get("/api/v1/models/files?repo=wer/was").json()["dateien"]
    assert [d["datei"] for d in dateien] == ["a.gguf", "b.gguf"]
    assert klient.adressen[1] == weiter


def test_eine_fremde_naechste_seite_wird_nicht_gelesen(client, monkeypatch):
    klient = SeitenKlient(
        [([_eintrag("a.gguf", 1_000_000_000)], "https://anderswo.example/tree?cursor=1")]
    )
    monkeypatch.setattr(modelldateien.httpx, "AsyncClient", klient)
    dateien = client.get("/api/v1/models/files?repo=wer/was").json()["dateien"]
    assert [d["datei"] for d in dateien] == ["a.gguf"]
    assert len(klient.adressen) == 1


# --- What does not go into an address -------------------------------------


@pytest.mark.parametrize(
    "repo", ["a..b", "wer", "wer/was/extra", "/wer/was", "wer /was", "wer/was?x=1"]
)
def test_kein_repo_name_kein_aufruf(client, baum, repo):
    baum([])
    antwort = client.get(
        "/api/v1/models/files", params={"repo": repo}
    )
    assert antwort.status_code == 400


# --- When the other side has a bad day ------------------------------------


def test_katalog_antwortet_nicht(client, baum):
    baum(None, httpx.ConnectError("weg"))
    assert client.get("/api/v1/models/files?repo=wer/was").status_code == 502


def test_katalog_antwortet_unsinn(client, baum):
    baum({"unerwartet": True})
    assert client.get("/api/v1/models/files?repo=wer/was").status_code == 502


class WeiterleitungsKlient:
    """Remembers how it was built, then answers like the hub."""

    optionen: dict = {}

    def __init__(self, **optionen):
        WeiterleitungsKlient.optionen = optionen

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, adresse, params=None):
        return FalscheAntwort([_eintrag("a.gguf", 1_000_000_000)])


def test_ein_umbenanntes_repository_wird_weiter_gefunden(client, monkeypatch):
    """The old name answers with a redirect to the new one; the list follows it."""
    monkeypatch.setattr(modelldateien.httpx, "AsyncClient", WeiterleitungsKlient)
    client.get("/api/v1/models/files?repo=alt/name")
    assert WeiterleitungsKlient.optionen.get("follow_redirects") is True


# --- The kit of a picture model -------------------------------------------


def _picture_files(client, repo="wer/was"):
    return client.get(f"/api/v1/models/files?repo={repo}&art=bild").json()["dateien"]


def test_a_z_image_names_its_kit(client, baum, tmp_path):
    SIZES[("unsloth/Qwen3-4B-Instruct-2507-GGUF", "Qwen3-4B-Instruct-2507-Q4_K_M.gguf")] = 2_497_281_120
    SIZES[("Comfy-Org/z_image_turbo", "split_files/vae/ae.safetensors")] = 335_304_388
    (tmp_path / "vae").mkdir()
    (tmp_path / "vae" / "ae.safetensors").write_bytes(b"da")
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    baum([_eintrag("z_image_turbo-Q4_K_M.gguf", 4_500_000_000)])
    datei = _picture_files(client)[0]
    assert datei["bausatz"]["familie"] == "zimage"
    teile = {teil["rolle"]: teil for teil in datei["bausatz"]["teile"]}
    assert list(teile) == ["modell", "textleser", "vae"]
    assert teile["modell"]["name"] == "z_image_turbo-Q4_K_M.gguf"
    assert teile["modell"]["repo"] == "wer/was"
    assert teile["modell"]["da"] is False
    assert teile["textleser"]["repo"] == "unsloth/Qwen3-4B-Instruct-2507-GGUF"
    assert teile["textleser"]["name"] == "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
    assert teile["textleser"]["ordner"] == "text_encoders"
    # Each part names the field of the model's kit it fills.
    assert teile["modell"]["feld"] == ""
    assert teile["textleser"]["feld"] == "llm"
    assert teile["vae"]["feld"] == "vae"
    assert teile["textleser"]["groesse_gb"] == 2.5
    assert teile["textleser"]["da"] is False
    # The VAE comes from a repository that hands it out without a login, and
    # lands under its bare name.
    assert teile["vae"]["repo"] == "Comfy-Org/z_image_turbo"
    assert teile["vae"]["datei"] == "split_files/vae/ae.safetensors"
    assert teile["vae"]["name"] == "ae.safetensors"
    assert teile["vae"]["ordner"] == "vae"
    assert teile["vae"]["groesse_gb"] == 0.3
    assert teile["vae"]["da"] is True


def test_a_model_in_the_folder_counts_as_there(client, baum, tmp_path):
    (tmp_path / "z_image_turbo-Q4_K_M.gguf").write_bytes(b"da")
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    baum([_eintrag("z_image_turbo-Q4_K_M.gguf", 4_500_000_000)])
    teile = _picture_files(client)[0]["bausatz"]["teile"]
    assert teile[0]["da"] is True


def test_a_part_without_a_readable_size_stays_in_the_kit(client, baum):
    # The hub refused to state the size: the part stays, without one.
    baum([_eintrag("z_image_turbo-Q4_K_M.gguf", 4_500_000_000)])
    teile = _picture_files(client)[0]["bausatz"]["teile"]
    assert [teil["rolle"] for teil in teile] == ["modell", "textleser", "vae"]
    assert teile[1]["groesse_gb"] is None


def test_an_sdxl_has_no_kit(client, baum):
    # Silence: a name that shows no family gets no block, the download stays
    # as it is.
    baum([_eintrag("sd_xl_base_1.0.safetensors", 6_900_000_000)])
    assert _picture_files(client)[0]["bausatz"] is None


def test_a_family_without_sources_has_no_kit(client, baum):
    # sd.cpp's docs have no page for Qwen Image Layered: no block.
    baum([_eintrag("Qwen-Image-Layered-Q4_K_M.gguf", 2_600_000_000)])
    assert _picture_files(client)[0]["bausatz"] is None


def test_the_kit_is_the_one_of_the_model_the_name_shows(client, baum):
    # Two sizes of one family in one repository: each row names its own
    # encoder, and a row whose name carries no size names no kit at all.
    baum(
        [
            _eintrag("flux-2-klein-4b-Q4_K_M.gguf", 2_600_000_000),
            _eintrag("flux-2-klein-9b-Q4_K_M.gguf", 5_600_000_000),
            _eintrag("flux-2-klein-Q4_K_M.gguf", 9_000_000_000),
        ]
    )
    rows = {row["datei"]: row["bausatz"] for row in _picture_files(client)}
    encoder = {
        name: next(part["name"] for part in kit["teile"] if part["feld"] == "llm")
        for name, kit in rows.items() if kit
    }
    assert encoder == {
        "flux-2-klein-4b-Q4_K_M.gguf": "Qwen3-4B-Q4_K_M.gguf",
        "flux-2-klein-9b-Q4_K_M.gguf": "Qwen3-8B-Q4_K_M.gguf",
    }
    assert rows["flux-2-klein-Q4_K_M.gguf"] is None


def test_a_kit_of_three_text_encoders_names_each(client, baum):
    baum([_eintrag("sd3.5_large-Q4_0.gguf", 5_000_000_000)])
    kit = _picture_files(client)[0]["bausatz"]
    assert kit["familie"] == "sd3"
    assert [(part["rolle"], part["feld"]) for part in kit["teile"]] == [
        ("modell", ""), ("textleser", "clip_l"), ("textleser", "clip_g"), ("textleser", "t5xxl"),
    ]


def test_other_tabs_have_no_kit(client, baum):
    baum([_eintrag("z_image_turbo-Q4_K_M.gguf", 4_500_000_000)])
    antwort = client.get("/api/v1/models/files?repo=wer/was&art=chat").json()
    assert antwort["dateien"][0]["bausatz"] is None


def test_a_companion_of_the_family_has_no_kit(client, baum):
    # Silence: a LoRA, a VAE or a ControlNet carries the family in its name
    # and is still no model — its row gets no kit, whatever folder it lies in.
    baum(
        [
            _eintrag("z_image_turbo_portrait_lora.safetensors", 170_000_000),
            _eintrag("split_files/vae/qwen_image_vae.safetensors", 253_806_246),
            _eintrag("loras/Z-Image-detail.safetensors", 170_000_000),
            _eintrag("flux1-dev-controlnet-union.safetensors", 6_600_000_000),
            _eintrag("flux1-dev-t5xxl_fp8.safetensors", 4_900_000_000),
            _eintrag(
                "split_files/latent_upscale_models/hunyuanvideo15_latent_upsampler_720p.safetensors",
                380_000_000,
            ),
            # Each of the two words alone: the folder's, and the file's own.
            _eintrag("latent_upscale_models/hunyuanvideo1.5_x2.safetensors", 380_000_000),
            _eintrag("hunyuanvideo1.5_latent_upsampler_1080p.safetensors", 380_000_000),
            _eintrag("split_files/diffusion_models/z_image_turbo_bf16.safetensors", 12_300_000_000),
        ]
    )
    nach_name = {d["datei"]: d["bausatz"] for d in _picture_files(client)}
    assert nach_name["latent_upscale_models/hunyuanvideo1.5_x2.safetensors"] is None
    assert nach_name["hunyuanvideo1.5_latent_upsampler_1080p.safetensors"] is None
    assert nach_name[
        "split_files/latent_upscale_models/hunyuanvideo15_latent_upsampler_720p.safetensors"
    ] is None
    assert nach_name["z_image_turbo_portrait_lora.safetensors"] is None
    assert nach_name["split_files/vae/qwen_image_vae.safetensors"] is None
    assert nach_name["loras/Z-Image-detail.safetensors"] is None
    assert nach_name["flux1-dev-controlnet-union.safetensors"] is None
    assert nach_name["flux1-dev-t5xxl_fp8.safetensors"] is None
    # The model beside them keeps its kit, and lies flat in our folder.
    modell = nach_name["split_files/diffusion_models/z_image_turbo_bf16.safetensors"]
    assert modell["familie"] == "zimage"
    assert modell["teile"][0]["name"] == "z_image_turbo_bf16.safetensors"
