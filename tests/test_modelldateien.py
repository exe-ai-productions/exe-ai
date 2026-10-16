"""The file list of a found repository.

Nothing here talks to Hugging Face: the answer is faked, because what is
being tested is our side — which files we consider startable, in which
order they come back, and what happens when the other side has a bad day.
"""

from __future__ import annotations

import httpx
import pytest

from app.api.v1 import modelldateien
from tests.conftest import sized_file


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

    # The front of a file is asked for by range, as a stream; the faked hub
    # answers from ``HEAD_FILES`` (path → the file's bytes), and writes every
    # request down in ``REQUESTS``.
    def stream(self, methode, adresse, headers=None, follow_redirects=None):
        REQUESTS.append({"url": adresse, "headers": dict(headers or {}), "follow": follow_redirects})
        return FakeStream(adresse, dict(headers or {}))

    # The size of one part of a kit is asked for with a POST; the faked hub
    # answers it from ``SIZES``, by repository and path.
    async def post(self, adresse, data=None):
        repo = adresse.split("/api/models/")[1].split("/paths-info")[0]
        pfad = data["paths"]
        groesse = SIZES.get((repo, pfad))
        zeilen = [] if groesse is None else [{"type": "file", "path": pfad, "size": groesse}]
        return FalscheAntwort(zeilen)


SIZES: dict[tuple[str, str], int] = {}
# What the faked hub holds of each file, by the path inside the repository,
# and what was asked of it.
HEAD_FILES: dict[str, bytes] = {}
REQUESTS: list[dict] = []
# Set to a host name: the first answer is a redirect to it, as the hub does
# for the bytes of a file.
REDIRECT: dict[str, str] = {}
# Set to a status: every range request is answered with it.
STATUS: dict[str, int] = {}


class FakeStream:
    """One streamed answer of the faked hub."""

    def __init__(self, adresse, headers):
        self.adresse = adresse
        self.headers: dict[str, str] = {}
        self.status_code = 404
        self._daten = b""
        pfad = adresse.split("/resolve/main/")[-1] if "/resolve/main/" in adresse else ""
        host = adresse.split("/")[2]
        if "huggingface.co" in host and REDIRECT.get("host"):
            self.status_code = 302
            self.headers = {"location": f"https://{REDIRECT['host']}/bytes/{pfad}"}
            return
        pfad = pfad or adresse.split("/bytes/")[-1]
        if STATUS.get("code"):
            self.status_code = STATUS["code"]
            return
        daten = HEAD_FILES.get(pfad)
        if daten is None:
            return
        bereich = headers.get("Range", "")
        if bereich.startswith("bytes="):
            von, bis = bereich[6:].split("-")
            self._daten = daten[int(von): int(bis) + 1]
            self.status_code = 206
        else:
            self._daten = daten
            self.status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def aiter_bytes(self):
        yield self._daten


@pytest.fixture(autouse=True)
def _clear_sizes():
    SIZES.clear()
    HEAD_FILES.clear()
    REQUESTS.clear()
    REDIRECT.clear()
    STATUS.clear()


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
        {
            "datei": "einzeln.gguf", "groesse_gb": 2.0, "bytes": 2_000_000_000,
            "local_name": "einzeln.gguf", "da": False, "collision": False, "teile": 1, "bausatz": None,
            "art": None, "familie": None,
        },
        {
            # The size that counts for a split model is that of part 1.
            "datei": "Q2_0/m-Q2_0-00001-of-00002.gguf", "groesse_gb": 66.4,
            "bytes": 37_623_740_192, "local_name": "m-Q2_0-00001-of-00002.gguf", "da": False,
            "collision": False, "teile": 2, "bausatz": None, "art": None, "familie": None,
        },
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


def _picture_list(client, repo="wer/was"):
    """The list alone, as the window gets it before any head is read."""
    return client.get(f"/api/v1/models/files?repo={repo}&art=bild").json()["dateien"]


def _head_of(client, row, repo="wer/was"):
    return client.post("/api/v1/models/files/head", json={"repo": repo, "datei": row}).json()


def _picture_files(client, repo="wer/was"):
    """The list with every row's head read, one request per row, as the
    window asks for them."""
    return [_head_of(client, row, repo) for row in _picture_list(client, repo)]


def _file_of_size(pfad, groesse):
    """A file of exactly ``groesse`` bytes, sparse: nothing of it is written
    (on Windows a plain ``truncate`` writes every byte, so the helper that
    marks the file sparse first does the work)."""
    pfad.parent.mkdir(parents=True, exist_ok=True)
    sized_file(pfad, groesse)


def test_a_z_image_names_its_kit(client, baum, tmp_path):
    SIZES[("unsloth/Qwen3-4B-Instruct-2507-GGUF", "Qwen3-4B-Instruct-2507-Q4_K_M.gguf")] = 2_497_281_120
    SIZES[("Comfy-Org/z_image_turbo", "split_files/vae/ae.safetensors")] = 335_304_388
    _file_of_size(tmp_path / "vae" / "ae.safetensors", 335_304_388)
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


_QWEN_21_LLM = ("Qwen/Qwen3-VL-8B-Instruct-GGUF", "Qwen3VL-8B-Instruct-Q4_K_M.gguf")
_QWEN_21_VAE = ("Comfy-Org/Qwen-Image-2.1", "vae/qwen_image_2.1_vae_bf16.safetensors")
_QWEN_21_EYES = ("Qwen/Qwen3-VL-8B-Instruct-GGUF", "mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf")


def _qwen_21_row(client, baum, tmp_path):
    SIZES[_QWEN_21_LLM] = 5_030_000_000
    SIZES[_QWEN_21_VAE] = 253_806_278
    SIZES[_QWEN_21_EYES] = 752_289_728
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    baum([_eintrag("qwen-image-2.1-turbo-Q4_K_M.gguf", 11_000_000_000)])
    return {teil["feld"] or "modell": teil
            for teil in _picture_files(client)[0]["bausatz"]["teile"]}


def test_an_encoder_of_another_quantisation_counts_as_there(client, baum, tmp_path):
    """The drawing sets in the Qwen3-VL it finds by its head, whatever its
    name or bits: the kit counts it as there and fetches only the rest."""
    from tests.test_image_families import _gguf

    _gguf(tmp_path / "text_encoders" / "Qwen3-VL-8B-Instruct-Q8_0.gguf", "qwen3vl",
          {"token_embd.weight": [151936, 4096]})
    teile = _qwen_21_row(client, baum, tmp_path)
    assert teile["llm"]["da"] is True
    assert teile["llm"]["local_name"] == "Qwen3-VL-8B-Instruct-Q8_0.gguf"
    assert teile["llm"]["collision"] is False
    # What is not found stays to fetch: the model, the VAE and the vision part.
    assert teile["modell"]["da"] is False
    assert teile["vae"]["da"] is False
    assert teile["llm_vision"]["da"] is False


def test_silence_an_encoder_of_another_width_is_not_the_part(client, baum, tmp_path):
    """A Qwen3-VL 4B is 2560 wide: Qwen-Image 2.1 does not read it."""
    from tests.test_image_families import _gguf

    _gguf(tmp_path / "text_encoders" / "Qwen3-VL-4B-Instruct-Q8_0.gguf", "qwen3vl",
          {"token_embd.weight": [151936, 2560]})
    teile = _qwen_21_row(client, baum, tmp_path)
    assert teile["llm"]["da"] is False
    assert teile["llm"]["local_name"] == "Qwen3VL-8B-Instruct-Q4_K_M.gguf"


def test_the_kit_of_qwen_image_2_1_names_the_vision_part(client, baum, tmp_path):
    teile = _qwen_21_row(client, baum, tmp_path)
    eyes = teile["llm_vision"]
    assert eyes["rolle"] == "textleser"
    assert eyes["repo"] == "Qwen/Qwen3-VL-8B-Instruct-GGUF"
    assert eyes["datei"] == "mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf"
    assert eyes["ordner"] == "text_encoders"
    assert eyes["bytes"] == 752_289_728
    assert eyes["da"] is False
    # Its file of this size in the folder is the part.
    _file_of_size(tmp_path / "text_encoders" / "mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf", 752_289_728)
    assert _qwen_21_row(client, baum, tmp_path)["llm_vision"]["da"] is True


def test_a_model_in_the_folder_counts_as_there(client, baum, tmp_path):
    _file_of_size(tmp_path / "z_image_turbo-Q4_K_M.gguf", 4_500_000_000)
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    baum([_eintrag("z_image_turbo-Q4_K_M.gguf", 4_500_000_000)])
    datei = _picture_files(client)[0]
    assert datei["da"] is True and datei["local_name"] == "z_image_turbo-Q4_K_M.gguf"
    assert datei["bausatz"]["teile"][0]["da"] is True


def test_another_file_of_the_name_is_not_the_file(client, baum, tmp_path):
    """The name alone is no proof: a file of the same name and another size
    is another file. The row is not there, and says under which name the
    new file would be kept — the repository without its owner before it."""
    _file_of_size(tmp_path / "diffusion_pytorch_model.safetensors", 1_350_989_512)
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    baum([_eintrag("vae/diffusion_pytorch_model.safetensors", 507_591_892)])
    datei = _picture_files(client, "krea/Krea-2-Turbo")[0]
    assert datei["bytes"] == 507_591_892
    assert datei["da"] is False and datei["collision"] is False
    assert datei["local_name"] == "Krea-2-Turbo-diffusion_pytorch_model.safetensors"


def test_the_second_name_with_the_same_size_is_there(client, baum, tmp_path):
    _file_of_size(tmp_path / "diffusion_pytorch_model.safetensors", 1_350_989_512)
    _file_of_size(tmp_path / "Krea-2-Turbo-diffusion_pytorch_model.safetensors", 507_591_892)
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    baum([_eintrag("vae/diffusion_pytorch_model.safetensors", 507_591_892)])
    datei = _picture_files(client, "krea/Krea-2-Turbo")[0]
    assert datei["da"] is True
    assert datei["local_name"] == "Krea-2-Turbo-diffusion_pytorch_model.safetensors"


def test_both_names_held_by_other_files_make_the_third_name(client, baum, tmp_path):
    """The row offers the download under ``<owner>-<repo>-<name>``: the
    button does what it says, nothing is a collision."""
    _file_of_size(tmp_path / "diffusion_pytorch_model.safetensors", 1_350_989_512)
    _file_of_size(tmp_path / "Krea-2-Turbo-diffusion_pytorch_model.safetensors", 7)
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    baum([_eintrag("vae/diffusion_pytorch_model.safetensors", 507_591_892)])
    datei = _picture_files(client, "krea/Krea-2-Turbo")[0]
    assert datei["da"] is False and datei["collision"] is False
    assert datei["local_name"] == "krea-Krea-2-Turbo-diffusion_pytorch_model.safetensors"


def test_the_third_name_with_the_same_size_is_there(client, baum, tmp_path):
    _file_of_size(tmp_path / "diffusion_pytorch_model.safetensors", 1_350_989_512)
    _file_of_size(tmp_path / "Krea-2-Turbo-diffusion_pytorch_model.safetensors", 7)
    _file_of_size(tmp_path / "krea-Krea-2-Turbo-diffusion_pytorch_model.safetensors", 507_591_892)
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    baum([_eintrag("vae/diffusion_pytorch_model.safetensors", 507_591_892)])
    datei = _picture_files(client, "krea/Krea-2-Turbo")[0]
    assert datei["da"] is True and datei["collision"] is False
    assert datei["local_name"] == "krea-Krea-2-Turbo-diffusion_pytorch_model.safetensors"


def test_all_three_names_held_by_other_files_is_a_collision(client, baum, tmp_path):
    _file_of_size(tmp_path / "diffusion_pytorch_model.safetensors", 1_350_989_512)
    _file_of_size(tmp_path / "Krea-2-Turbo-diffusion_pytorch_model.safetensors", 7)
    _file_of_size(tmp_path / "krea-Krea-2-Turbo-diffusion_pytorch_model.safetensors", 9)
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    baum([_eintrag("vae/diffusion_pytorch_model.safetensors", 507_591_892)])
    datei = _picture_files(client, "krea/Krea-2-Turbo")[0]
    assert datei["da"] is False and datei["collision"] is True


def test_silence_a_free_name_stays_flat(client, baum, tmp_path):
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    baum([_eintrag("vae/diffusion_pytorch_model.safetensors", 507_591_892)])
    datei = _picture_files(client, "krea/Krea-2-Turbo")[0]
    assert datei["da"] is False and datei["collision"] is False
    assert datei["local_name"] == "diffusion_pytorch_model.safetensors"


def _three_parts():
    return [
        _eintrag("m-00001-of-00003.gguf", 9_000_000_000),
        _eintrag("m-00002-of-00003.gguf", 8_000_000_000),
        _eintrag("m-00003-of-00003.gguf", 1_000_000_000),
    ]


def _the_split_row(client):
    return client.get("/api/v1/models/files?repo=wer/was").json()["dateien"][0]


def test_a_split_model_with_only_part_one_is_not_there(client, baum, tmp_path):
    _file_of_size(tmp_path / "m-00001-of-00003.gguf", 9_000_000_000)
    client.app.state.modellordner_je_art = {"chat": str(tmp_path)}
    baum(_three_parts())
    datei = _the_split_row(client)
    assert datei["teile"] == 3 and datei["da"] is False and datei["collision"] is False
    assert datei["local_name"] == "m-00001-of-00003.gguf"


def test_a_split_model_with_parts_one_and_two_is_not_there(client, baum, tmp_path):
    _file_of_size(tmp_path / "m-00001-of-00003.gguf", 9_000_000_000)
    _file_of_size(tmp_path / "m-00002-of-00003.gguf", 8_000_000_000)
    client.app.state.modellordner_je_art = {"chat": str(tmp_path)}
    baum(_three_parts())
    assert _the_split_row(client)["da"] is False


def test_a_split_model_is_there_when_every_part_is(client, baum, tmp_path):
    for name, size in (
        ("m-00001-of-00003.gguf", 9_000_000_000),
        ("m-00002-of-00003.gguf", 8_000_000_000),
        ("m-00003-of-00003.gguf", 1_000_000_000),
    ):
        _file_of_size(tmp_path / name, size)
    client.app.state.modellordner_je_art = {"chat": str(tmp_path)}
    baum(_three_parts())
    datei = _the_split_row(client)
    assert datei["teile"] == 3 and datei["da"] is True
    assert datei["local_name"] == "m-00001-of-00003.gguf"


def test_silence_the_other_parts_without_part_one_do_not_make_it_there(client, baum, tmp_path):
    _file_of_size(tmp_path / "m-00002-of-00003.gguf", 8_000_000_000)
    _file_of_size(tmp_path / "m-00003-of-00003.gguf", 1_000_000_000)
    client.app.state.modellordner_je_art = {"chat": str(tmp_path)}
    baum(_three_parts())
    assert _the_split_row(client)["da"] is False


def test_silence_another_file_under_the_name_of_part_one_is_still_a_collision(client, baum, tmp_path):
    _file_of_size(tmp_path / "m-00001-of-00003.gguf", 7)
    client.app.state.modellordner_je_art = {"chat": str(tmp_path)}
    baum(_three_parts())
    datei = _the_split_row(client)
    assert datei["da"] is False and datei["collision"] is True


def test_silence_a_model_in_one_part_is_there_by_name_and_size(client, baum, tmp_path):
    _file_of_size(tmp_path / "einzeln.gguf", 2_000_000_000)
    client.app.state.modellordner_je_art = {"chat": str(tmp_path)}
    baum([_eintrag("einzeln.gguf", 2_000_000_000)])
    datei = _the_split_row(client)
    assert datei["teile"] == 1 and datei["da"] is True


def test_a_part_of_another_size_in_its_folder_is_not_the_part(client, baum, tmp_path):
    SIZES[("Comfy-Org/z_image_turbo", "split_files/vae/ae.safetensors")] = 335_304_388
    _file_of_size(tmp_path / "vae" / "ae.safetensors", 5)
    client.app.state.modellordner_je_art = {"bild": str(tmp_path)}
    baum([_eintrag("z_image_turbo-Q4_K_M.gguf", 4_500_000_000)])
    vae = _picture_files(client)[0]["bausatz"]["teile"][2]
    assert vae["da"] is False and vae["collision"] is False
    assert vae["bytes"] == 335_304_388
    assert vae["local_name"] == "z_image_turbo-ae.safetensors"


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


# --- The family from the head of the file ---------------------------------


def _safetensors_head(namen, fuellung=0):
    """The front of a safetensors file: the length, the JSON, and ``fuellung``
    bytes standing for the tensor data."""
    import json
    import struct

    kopf = {name: {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]} for name in namen}
    roh = json.dumps(kopf).encode("utf-8")
    return struct.pack("<Q", len(roh)) + roh + b"\0" * fuellung


def _gguf_head(architektur, tensoren=("blk.0.attn_norm.weight",)):
    import struct

    def zeichenkette(text):
        roh = text.encode("utf-8")
        return struct.pack("<Q", len(roh)) + roh

    kopf = bytearray(b"GGUF")
    kopf += struct.pack("<I", 3) + struct.pack("<Q", len(tensoren)) + struct.pack("<Q", 1)
    kopf += zeichenkette("general.architecture") + struct.pack("<I", 8) + zeichenkette(architektur)
    for name in tensoren:
        kopf += zeichenkette(name) + struct.pack("<I", 1) + struct.pack("<Q", 1)
        kopf += struct.pack("<I", 0) + struct.pack("<Q", 0)
    return bytes(kopf)


KREA_HEAD_NAMES = [
    "model.diffusion_model.txtfusion.projector.weight",
    "model.diffusion_model.blocks.0.attn.qkv.weight",
]


def _kit_of_row(client, repo="wer/was"):
    return _picture_files(client, repo)[0]["bausatz"]


def test_a_neutral_name_shows_its_family_at_the_head(client, baum):
    """``turbo.safetensors`` says nothing; its head says Krea 2, and the row
    carries the kit of that family."""
    SIZES[("Qwen/Qwen3-VL-4B-Instruct-GGUF", "Qwen3VL-4B-Instruct-Q4_K_M.gguf")] = 2_497_281_120
    SIZES[("Comfy-Org/Wan_2.1_ComfyUI_repackaged", "split_files/vae/wan_2.1_vae.safetensors")] = 253_806_278
    HEAD_FILES["turbo.safetensors"] = _safetensors_head(KREA_HEAD_NAMES, fuellung=500)
    baum([_eintrag("turbo.safetensors", 26_283_332_608)])
    # The head is read from the file's size the hub states, not from what
    # the faked answer holds — the request stays inside it.
    bausatz = _kit_of_row(client, "krea/Krea-2-Turbo")
    assert bausatz["familie"] == "krea2"
    assert [teil["name"] for teil in bausatz["teile"]] == [
        "turbo.safetensors", "Qwen3VL-4B-Instruct-Q4_K_M.gguf", "wan_2.1_vae.safetensors",
    ]


def test_a_neutral_gguf_name_shows_its_family_at_the_head(client, baum):
    HEAD_FILES["weights-Q4_K_M.gguf"] = _gguf_head("flux") + b"\0" * 300
    baum([_eintrag("weights-Q4_K_M.gguf", 7_000_000_000)])
    assert _kit_of_row(client)["familie"] == "flux"


def test_the_first_request_is_a_range_of_100000_bytes_and_the_token_stays_at_the_hub(
    client, baum, monkeypatch
):
    """The token goes to huggingface.co only: the hop to the host the hub
    redirects to carries none."""
    monkeypatch.setenv("HF_TOKEN", "hf_geheim")
    REDIRECT["host"] = "cdn.example"
    HEAD_FILES["turbo.safetensors"] = _safetensors_head(KREA_HEAD_NAMES, fuellung=500)
    baum([_eintrag("turbo.safetensors", 26_283_332_608)])
    _picture_files(client, "krea/Krea-2-Turbo")
    hub, umgeleitet = REQUESTS[0], REQUESTS[1]
    assert hub["url"].startswith("https://huggingface.co/krea/Krea-2-Turbo/resolve/main/turbo.safetensors")
    assert hub["headers"]["Range"] == "bytes=0-99999"
    assert hub["headers"]["Authorization"] == "Bearer hf_geheim"
    assert hub["follow"] is False
    assert umgeleitet["url"].startswith("https://cdn.example/")
    assert "Authorization" not in umgeleitet["headers"]


def test_a_longer_safetensors_header_is_fetched_with_a_second_request(client, baum):
    namen = KREA_HEAD_NAMES + [f"model.diffusion_model.blocks.{n}.weight" for n in range(2500)]
    kopf = _safetensors_head(namen)
    assert len(kopf) > 100_000
    HEAD_FILES["turbo.safetensors"] = kopf + b"\0" * 100
    baum([_eintrag("turbo.safetensors", len(kopf) + 100)])
    assert _kit_of_row(client, "krea/Krea-2-Turbo")["familie"] == "krea2"
    ranges = [a["headers"]["Range"] for a in REQUESTS]
    assert ranges == ["bytes=0-99999", f"bytes=100000-{len(kopf) - 1}"]


def test_an_unreadable_head_leaves_the_name_to_decide(client, baum):
    """401 (a locked repository without a token): the name decides as it
    always did."""
    STATUS["code"] = 401
    baum([_eintrag("z_image_turbo-Q4_K_M.gguf", 4_500_000_000)])
    assert _kit_of_row(client)["familie"] == "zimage"


def test_an_answer_that_is_no_range_is_never_read(client, baum):
    """A 200 would be the whole file: not read, the name decides."""
    STATUS["code"] = 200
    baum([_eintrag("z_image_turbo-Q4_K_M.gguf", 4_500_000_000)])
    assert _kit_of_row(client)["familie"] == "zimage"


def test_the_list_stands_before_any_head_is_read(client, baum, monkeypatch):
    """A hub that answers a head only after seconds: the list is there at
    once, every row without what its head says — the heads come per row."""
    import asyncio
    import time

    HEAD_FILES["z_image_turbo-Q4_K_M.gguf"] = _gguf_head("flux") + b"\0" * 300
    original = FakeStream.aiter_bytes

    async def slowly(self):
        await asyncio.sleep(3)
        async for piece in original(self):
            yield piece

    monkeypatch.setattr(FakeStream, "aiter_bytes", slowly)
    baum([
        _eintrag("z_image_turbo-Q4_K_M.gguf", 4_500_000_000),
        _eintrag("weights-Q4_K_M.gguf", 7_000_000_000),
    ])
    start = time.monotonic()
    rows = _picture_list(client)
    assert time.monotonic() - start < 1.5
    assert REQUESTS == []
    assert [z["datei"] for z in rows] == ["z_image_turbo-Q4_K_M.gguf", "weights-Q4_K_M.gguf"]
    assert [(z["art"], z["familie"], z["bausatz"]) for z in rows] == [(None, None, None)] * 2


def test_a_row_asks_for_its_own_head_only(client, baum):
    HEAD_FILES["a.safetensors"] = _safetensors_head(KREA_HEAD_NAMES, fuellung=100)
    HEAD_FILES["b.safetensors"] = _safetensors_head(VAE_HEAD_NAMES, fuellung=100)
    baum([_eintrag("a.safetensors", 5_000_000_000), _eintrag("b.safetensors", 500_000_000)])
    row = next(z for z in _picture_list(client) if z["datei"] == "b.safetensors")
    answer = _head_of(client, row)
    assert (answer["art"], answer["bausatz"]) == ("vae", None)
    assert [a["url"].split("/resolve/main/")[1] for a in REQUESTS] == ["b.safetensors"]


def test_what_the_window_sends_back_is_not_believed(client, baum):
    """Only which file it is counts: a head that says VAE stays a VAE
    whatever the sent row claims, and the kit is not taken from it."""
    HEAD_FILES["a.safetensors"] = _safetensors_head(VAE_HEAD_NAMES, fuellung=100)
    baum([_eintrag("a.safetensors", 500_000_000)])
    row = _picture_list(client)[0]
    row.update({"art": "modell", "familie": "flux", "da": True, "local_name": "x.safetensors"})
    answer = _head_of(client, row)
    assert (answer["art"], answer["familie"], answer["bausatz"]) == ("vae", None, None)
    assert answer["da"] is False and answer["local_name"] == "a.safetensors"


def test_a_head_of_a_path_outside_the_repository_is_not_asked_for(client, baum):
    baum([])
    row = {"datei": "../../andere/repo/x.safetensors", "groesse_gb": 1.0, "bytes": 1_000_000_000}
    answer = _head_of(client, row)
    assert REQUESTS == []
    assert (answer["art"], answer["bausatz"]) == (None, None)


def test_a_head_of_a_bad_repository_is_refused(client, baum):
    baum([])
    row = {"datei": "x.safetensors", "groesse_gb": 1.0, "bytes": 1_000_000_000}
    reply = client.post("/api/v1/models/files/head", json={"repo": "../x", "datei": row})
    assert reply.status_code == 400
    assert REQUESTS == []


def test_a_ckpt_is_not_asked_for_its_head(client, baum):
    baum([_eintrag("flux1-dev.ckpt", 6_000_000_000)])
    _picture_files(client)
    assert REQUESTS == []


def test_a_lora_named_like_a_model_has_no_kit(client, baum):
    """The name shows a family; the head holds LoRA weights, so no kit."""
    HEAD_FILES["flux-style.safetensors"] = _safetensors_head(
        ["diffusion_model.double_blocks.0.img_attn.proj.lora_A.weight",
         "diffusion_model.double_blocks.0.img_attn.proj.lora_B.weight"],
        fuellung=100,
    )
    baum([_eintrag("flux-style.safetensors", 200_000_000)])
    assert _picture_files(client)[0]["bausatz"] is None


def test_a_controlnet_named_like_a_model_has_no_kit(client, baum):
    HEAD_FILES["flux-union.safetensors"] = _safetensors_head(
        ["controlnet_blocks.0.weight", "double_blocks.0.img_attn.qkv.weight"], fuellung=100
    )
    baum([_eintrag("flux-union.safetensors", 3_000_000_000)])
    assert _picture_files(client)[0]["bausatz"] is None


def test_a_companion_by_its_path_has_no_kit_whatever_its_head_says(client, baum):
    """The path shows a VAE: no kit — and the row still tells what the head
    says it is."""
    HEAD_FILES["vae/diffusion_pytorch_model.safetensors"] = _safetensors_head(VAE_HEAD_NAMES, fuellung=100)
    baum([_eintrag("vae/diffusion_pytorch_model.safetensors", 507_591_892)])
    zeile = _picture_files(client, "krea/Krea-2-Turbo")[0]
    assert zeile["bausatz"] is None
    assert zeile["art"] == "vae"


# --- What each row says it is (the plaque of a file row) -------------------

VAE_HEAD_NAMES = [
    "encoder.conv_in.weight", "decoder.conv_in.weight", "post_quant_conv.weight",
]
T5_HEAD_NAMES = ["encoder.block.0.layer.0.SelfAttention.q.weight", "shared.weight"]
LLM_HEAD_NAMES = ["model.layers.0.self_attn.q_proj.weight", "model.embed_tokens.weight"]


def _kind_and_family(client, repo="krea/Krea-2-Turbo"):
    return {z["datei"]: (z["art"], z["familie"]) for z in _picture_files(client, repo)}


def test_each_row_says_what_its_head_says_it_is(client, baum):
    """Krea 2 model, VAE and text encoder, under names that say nothing."""
    HEAD_FILES["turbo.safetensors"] = _safetensors_head(KREA_HEAD_NAMES, fuellung=100)
    HEAD_FILES["a/model.safetensors"] = _safetensors_head(VAE_HEAD_NAMES, fuellung=100)
    HEAD_FILES["b/model.safetensors"] = _safetensors_head(T5_HEAD_NAMES, fuellung=100)
    HEAD_FILES["c/model.safetensors"] = _safetensors_head(LLM_HEAD_NAMES, fuellung=100)
    baum([
        _eintrag("turbo.safetensors", 26_283_332_608),
        _eintrag("a/model.safetensors", 507_000_000),
        _eintrag("b/model.safetensors", 8_900_000_000),
        _eintrag("c/model.safetensors", 8_900_000_000),
    ])
    assert _kind_and_family(client) == {
        "turbo.safetensors": ("modell", "krea2"),
        "a/model.safetensors": ("vae", None),
        "b/model.safetensors": ("textleser", None),
        "c/model.safetensors": ("textleser", None),
    }


def test_a_gguf_model_and_a_gguf_text_encoder_say_what_they_are(client, baum):
    HEAD_FILES["weights-Q4_K_M.gguf"] = _gguf_head("flux") + b"\0" * 300
    HEAD_FILES["enc-Q4_K_M.gguf"] = _gguf_head("qwen3vl") + b"\0" * 300
    baum([_eintrag("weights-Q4_K_M.gguf", 7_000_000_000), _eintrag("enc-Q4_K_M.gguf", 2_500_000_000)])
    assert _kind_and_family(client, "wer/was") == {
        "weights-Q4_K_M.gguf": ("modell", "flux"),
        "enc-Q4_K_M.gguf": ("textleser", None),
    }


def test_a_model_of_no_known_family_is_a_model_without_a_family(client, baum):
    """A head with a diffusion prefix names a model, but none of the
    program's families: the plaque says only that it is a model."""
    HEAD_FILES["x.safetensors"] = _safetensors_head(
        ["model.diffusion_model.input_blocks.0.0.weight"], fuellung=100
    )
    baum([_eintrag("x.safetensors", 3_000_000_000)])
    assert _kind_and_family(client, "wer/was")["x.safetensors"] == ("modell", None)


def test_a_lora_a_controlnet_and_an_unreadable_head_have_no_art(client, baum):
    HEAD_FILES["flux-style.safetensors"] = _safetensors_head(
        ["diffusion_model.double_blocks.0.img_attn.proj.lora_A.weight"], fuellung=100
    )
    HEAD_FILES["flux-union.safetensors"] = _safetensors_head(
        ["controlnet_blocks.0.weight", "double_blocks.0.img_attn.qkv.weight"], fuellung=100
    )
    # No bytes held for this one: the hub answers 404.
    baum([
        _eintrag("flux-style.safetensors", 200_000_000),
        _eintrag("flux-union.safetensors", 3_000_000_000),
        _eintrag("z_image_turbo-Q4_K_M.gguf", 4_500_000_000),
        _eintrag("old.ckpt", 4_000_000_000),
    ])
    assert _kind_and_family(client, "wer/was") == {
        "flux-style.safetensors": (None, None),
        "flux-union.safetensors": (None, None),
        # the name shows a family and gives the kit — but says nothing of
        # what the file is
        "z_image_turbo-Q4_K_M.gguf": (None, None),
        "old.ckpt": (None, None),
    }


def test_the_other_tabs_have_no_art_and_ask_for_no_head(client, baum):
    HEAD_FILES["model.safetensors"] = _safetensors_head(VAE_HEAD_NAMES, fuellung=100)
    baum([_eintrag("model-Q4_K_M.gguf", 4_500_000_000)])
    zeilen = client.get("/api/v1/models/files?repo=wer/was&art=chat").json()["dateien"]
    assert [(z["art"], z["familie"]) for z in zeilen] == [(None, None)]
    assert REQUESTS == []


def test_a_redirect_to_another_scheme_is_not_followed(client, baum):
    REDIRECT["host"] = "cdn.example"
    HEAD_FILES["z_image_turbo-Q4_K_M.gguf"] = _gguf_head("flux") + b"\0" * 300
    original = FakeStream.__init__

    def zu_http(self, adresse, headers):
        original(self, adresse, headers)
        if self.headers.get("location"):
            self.headers["location"] = self.headers["location"].replace("https://", "http://")

    FakeStream.__init__ = zu_http
    try:
        baum([_eintrag("z_image_turbo-Q4_K_M.gguf", 4_500_000_000)])
        assert _kit_of_row(client)["familie"] == "zimage"
    finally:
        FakeStream.__init__ = original
    assert [a["url"].split("/")[2] for a in REQUESTS] == ["huggingface.co"]


def test_heads_not_read_in_time_are_left_to_the_name(client, baum, monkeypatch):
    """A hub that answers too slowly: the list is still there, the names
    decide — the head that would have said Flux is never waited for."""
    from app.api.v1 import modelldateien

    HEAD_FILES["weights-Q4_K_M.gguf"] = _gguf_head("flux") + b"\0" * 300
    monkeypatch.setattr(modelldateien, "HEAD_TIME_LIMIT", 0.05)
    original = FakeStream.aiter_bytes

    async def langsam(self):
        import asyncio

        await asyncio.sleep(5)
        async for stueck in original(self):
            yield stueck

    monkeypatch.setattr(FakeStream, "aiter_bytes", langsam)
    baum([_eintrag("weights-Q4_K_M.gguf", 7_000_000_000), _eintrag("z_image_turbo-Q4_K_M.gguf", 4_500_000_000)])
    zeilen = {z["datei"]: z["bausatz"] for z in _picture_files(client)}
    assert zeilen["weights-Q4_K_M.gguf"] is None
    assert zeilen["z_image_turbo-Q4_K_M.gguf"]["familie"] == "zimage"


def test_a_head_that_never_ends_is_asked_for_only_so_often(client, baum, monkeypatch):
    """A GGUF header that goes on and on is cut at the number of requests
    one head may take."""
    from app.api.v1 import modelldateien

    monkeypatch.setattr(modelldateien, "HEAD_GGUF_PIECE", 1000)
    monkeypatch.setattr(modelldateien, "HEAD_REQUESTS_PER_FILE", 4)
    monkeypatch.setattr(modelldateien, "HEAD_FIRST_REQUEST", 1000)
    HEAD_FILES["weights-Q4_K_M.gguf"] = _gguf_head("flux", tensoren=[f"blk.{n}.w" for n in range(2000)])
    baum([_eintrag("weights-Q4_K_M.gguf", 7_000_000_000)])
    assert _picture_files(client)[0]["bausatz"] is None
    assert len(REQUESTS) == 4
