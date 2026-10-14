"""Fetching a model file.

Nothing is downloaded here — the answer is faked. What is tested is our
side: which names are allowed through, that a half file never looks like a
model, and that a failure leaves nothing behind.
"""

from __future__ import annotations

import time

import httpx
import pytest

from app import modelldownload
from app.modelldownload import DownloadFehler, Modelldownload


class FalscherStrom:
    """Stands in for httpx.stream and hands out fixed bytes. With
    ``with_range`` it answers a range request with the rest of the bytes,
    as the hub does; ``requests`` holds the headers of every request."""

    def __init__(
        self,
        daten: bytes,
        fehler: Exception | None = None,
        with_range: bool = False,
        etag: str | None = None,
    ):
        self._daten = daten
        self._fehler = fehler
        self._with_range = with_range
        # The version of the file the faked hub holds; ``None`` sends none.
        self.etag = etag
        self._served = daten
        self.status_code = 200
        self.headers = {"content-length": str(len(daten))}
        self.adresse: str | None = None
        self.requests: list[dict[str, str]] = []

    def __call__(self, methode, adresse, **kwargs):
        self.adresse = adresse
        sent = dict(kwargs.get("headers") or {})
        self.requests.append(sent)
        self.status_code = 200
        self._served = self._daten
        self.headers = {"content-length": str(len(self._daten))}
        if self.etag:
            self.headers["etag"] = self.etag
        wanted = sent.get("Range")
        if wanted and self._with_range:
            start = int(wanted[len("bytes="):].rstrip("-"))
            if start >= len(self._daten):
                self.status_code = 416
            else:
                self.status_code = 206
                self._served = self._daten[start:]
                self.headers = {
                    "content-length": str(len(self._served)),
                    "content-range": f"bytes {start}-{len(self._daten) - 1}/{len(self._daten)}",
                }
                if self.etag:
                    self.headers["etag"] = self.etag
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        if self._fehler:
            raise self._fehler

    def iter_bytes(self, groesse):
        for i in range(0, len(self._served), groesse):
            yield self._served[i : i + groesse]


def warten_bis(bedingung, sekunden=3.0):
    """The download runs in a thread; the test waits for it, briefly."""
    ende = time.time() + sekunden
    while time.time() < ende:
        if bedingung():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def strom(monkeypatch):
    def setzen(daten=b"x" * 5000, fehler=None, with_range=False, etag=None):
        falsch = FalscherStrom(daten, fehler, with_range, etag)
        monkeypatch.setattr(modelldownload.httpx, "stream", falsch)
        return falsch
    return setzen


# --- The normal case ------------------------------------------------------


def test_ein_modell_landet_im_ordner(tmp_path, strom):
    falsch = strom(b"y" * 4096)
    download = Modelldownload(tmp_path)
    download.starten("prism-ml/Bonsai-27B-gguf", "Bonsai-27B-Q1_0.gguf")

    assert warten_bis(lambda: download.stand().fertig)
    ziel = tmp_path / "Bonsai-27B-Q1_0.gguf"
    assert ziel.read_bytes() == b"y" * 4096
    assert falsch.adresse.endswith("/prism-ml/Bonsai-27B-gguf/resolve/main/Bonsai-27B-Q1_0.gguf")


def test_waehrend_es_laeuft_heisst_die_datei_anders(tmp_path, strom):
    strom(b"z" * 3_000_000)
    download = Modelldownload(tmp_path)
    download.starten("repo", "gross.gguf")

    # A half file must never look like a model — the runner would take it.
    assert warten_bis(lambda: list(tmp_path.glob("gross.gguf.*.teil")) or download.stand().fertig)
    assert warten_bis(lambda: download.stand().fertig)
    assert list(tmp_path.glob("*.teil")) == []


# --- Where it has to refuse -----------------------------------------------


@pytest.mark.parametrize(
    "datei", ["../weg.gguf", "unter/../weg.gguf", ".versteckt.gguf", "/weg.gguf", "unter/.geheim.gguf"]
)
def test_ein_name_ist_nie_ein_pfad(tmp_path, datei):
    """A traversal, a leading slash or dot, or a hidden segment is refused —
    on the remote name too, even though a plain sub-folder is now allowed."""
    with pytest.raises(DownloadFehler) as fehler:
        Modelldownload(tmp_path).starten("repo", datei)
    assert fehler.value.grund == "name"


def test_ein_remote_unterordner_ist_erlaubt(tmp_path, strom):
    """A drafter lives at MTP/…gguf on the hub — the remote name may sit in a
    sub-folder. The local file keeps only the flat last segment; the folder
    never rides along."""
    strom(b"m" * 4096)
    download = Modelldownload(tmp_path)
    download.starten("repo", "MTP/mtp-modell.gguf")
    assert warten_bis(lambda: download.stand().fertig)
    assert (tmp_path / "mtp-modell.gguf").is_file()
    assert not (tmp_path / "MTP").exists()


def test_der_lokale_name_bleibt_flach(tmp_path):
    """`ziel` names a file in our folder — it must never be a path."""
    with pytest.raises(DownloadFehler) as fehler:
        Modelldownload(tmp_path).starten("repo", "MTP/x.gguf", ziel="unter/x.gguf")
    assert fehler.value.grund == "name"


@pytest.mark.parametrize("datei", ["modell.safetensors", "modell.bin", "modell"])
def test_nur_gguf_wird_geholt(tmp_path, datei):
    """Default (chat/embedding): GGUF only, the one form the runner starts."""
    with pytest.raises(DownloadFehler) as fehler:
        Modelldownload(tmp_path).starten("repo", datei)
    assert fehler.value.grund == "endung"


def test_bild_darf_safetensors_holen(tmp_path, strom):
    """An image model is safetensors — the image folder accepts it, and the
    endings the caller allows decide, not a hardcoded .gguf."""
    from app.modelldownload import BILD_ENDUNGEN
    strom(b"abc")
    download = Modelldownload(tmp_path)
    download.starten("repo/bild", "CyberRealisticXL.safetensors", endungen=BILD_ENDUNGEN)
    assert warten_bis(lambda: download.stand().fertig)
    assert (tmp_path / "CyberRealisticXL.safetensors").is_file()


def test_bild_lehnt_eine_zip_trotzdem_ab(tmp_path):
    """The set is the image forms, not everything — a .zip is still refused."""
    from app.modelldownload import BILD_ENDUNGEN
    with pytest.raises(DownloadFehler) as fehler:
        Modelldownload(tmp_path).starten("repo", "modell.zip", endungen=BILD_ENDUNGEN)
    assert fehler.value.grund == "endung"


def test_was_schon_da_ist_wird_nicht_nochmal_geholt(tmp_path):
    (tmp_path / "da.gguf").write_bytes(b"schon da")
    with pytest.raises(DownloadFehler) as fehler:
        Modelldownload(tmp_path).starten("repo", "da.gguf")
    assert fehler.value.grund == "schon_da"


# --- Another file under the name -------------------------------------------


def test_another_file_under_the_name_makes_the_new_one_take_the_second_name(tmp_path, strom):
    """The name alone is no proof: with the size the hub states, a file of the
    same name and another size is another file. The new one is kept as
    ``<repo>-<name>`` (the repo without its owner); the old one is untouched."""
    (tmp_path / "diffusion_pytorch_model.safetensors").write_bytes(b"alt" * 100)
    strom(b"n" * 4096)
    download = Modelldownload(tmp_path)
    download.starten(
        "krea/Krea-2-Turbo", "vae/diffusion_pytorch_model.safetensors",
        endungen=modelldownload.BILD_ENDUNGEN, size=4096,
    )
    assert warten_bis(lambda: download.stand().fertig)
    assert download.stand().datei == "Krea-2-Turbo-diffusion_pytorch_model.safetensors"
    assert (tmp_path / "Krea-2-Turbo-diffusion_pytorch_model.safetensors").read_bytes() == b"n" * 4096
    assert (tmp_path / "diffusion_pytorch_model.safetensors").read_bytes() == b"alt" * 100


def test_the_same_name_and_size_is_still_there(tmp_path):
    (tmp_path / "da.gguf").write_bytes(b"x" * 4096)
    with pytest.raises(DownloadFehler) as fehler:
        Modelldownload(tmp_path).starten("wer/Repo", "da.gguf", size=4096)
    assert fehler.value.grund == "schon_da"


def test_the_second_name_with_the_same_size_is_there(tmp_path):
    (tmp_path / "m.gguf").write_bytes(b"alt")
    (tmp_path / "Repo-m.gguf").write_bytes(b"x" * 4096)
    with pytest.raises(DownloadFehler) as fehler:
        Modelldownload(tmp_path).starten("wer/Repo", "m.gguf", size=4096)
    assert fehler.value.grund == "schon_da"


def test_both_names_held_by_other_files_make_the_third_name(tmp_path, strom):
    """Its own name and ``<repo>-<name>`` are held by other files: the new
    one is kept as ``<owner>-<repo>-<name>`` and nothing else is touched."""
    (tmp_path / "m.gguf").write_bytes(b"eins")
    (tmp_path / "Repo-m.gguf").write_bytes(b"zwei")
    strom(b"n" * 4096)
    download = Modelldownload(tmp_path)
    download.starten("wer/Repo", "m.gguf", size=4096)
    assert warten_bis(lambda: download.stand().fertig)
    assert download.stand().datei == "wer-Repo-m.gguf"
    assert (tmp_path / "wer-Repo-m.gguf").read_bytes() == b"n" * 4096
    assert (tmp_path / "m.gguf").read_bytes() == b"eins"
    assert (tmp_path / "Repo-m.gguf").read_bytes() == b"zwei"


def test_the_third_name_with_the_same_size_is_there(tmp_path):
    (tmp_path / "m.gguf").write_bytes(b"eins")
    (tmp_path / "Repo-m.gguf").write_bytes(b"zwei")
    (tmp_path / "wer-Repo-m.gguf").write_bytes(b"x" * 4096)
    with pytest.raises(DownloadFehler) as fehler:
        Modelldownload(tmp_path).starten("wer/Repo", "m.gguf", size=4096)
    assert fehler.value.grund == "schon_da"


def test_all_three_names_held_by_other_files_overwrite_nothing(tmp_path):
    (tmp_path / "m.gguf").write_bytes(b"eins")
    (tmp_path / "Repo-m.gguf").write_bytes(b"zwei")
    (tmp_path / "wer-Repo-m.gguf").write_bytes(b"drei")
    with pytest.raises(DownloadFehler) as fehler:
        Modelldownload(tmp_path).starten("wer/Repo", "m.gguf", size=4096)
    assert fehler.value.grund == "schon_da"
    assert (tmp_path / "m.gguf").read_bytes() == b"eins"
    assert (tmp_path / "Repo-m.gguf").read_bytes() == b"zwei"
    assert (tmp_path / "wer-Repo-m.gguf").read_bytes() == b"drei"


def test_a_repo_without_an_owner_has_no_third_name(tmp_path):
    (tmp_path / "m.gguf").write_bytes(b"eins")
    (tmp_path / "Repo-m.gguf").write_bytes(b"zwei")
    with pytest.raises(DownloadFehler) as fehler:
        Modelldownload(tmp_path).starten("Repo", "m.gguf", size=4096)
    assert fehler.value.grund == "schon_da"
    # By name: the order of two paths follows the host's rules for case
    # (Windows folds it), and only the two names are the point here.
    assert sorted(pfad.name for pfad in tmp_path.iterdir()) == ["Repo-m.gguf", "m.gguf"]


def test_a_free_name_stays_flat(tmp_path, strom):
    """Silence: nothing under the name, so no second name is made."""
    strom(b"n" * 4096)
    download = Modelldownload(tmp_path)
    download.starten("wer/Repo", "m.gguf", size=4096)
    assert warten_bis(lambda: download.stand().fertig)
    assert [pfad.name for pfad in tmp_path.iterdir()] == ["m.gguf"]


def test_a_size_of_zero_is_no_size(tmp_path):
    """The hub that states no size gives 0 on the way here: the name alone
    decides, as without one — no second name is made for a file that is there."""
    (tmp_path / "m.gguf").write_bytes(b"irgendwas")
    with pytest.raises(DownloadFehler) as fehler:
        Modelldownload(tmp_path).starten("wer/Repo", "m.gguf", size=0)
    assert fehler.value.grund == "schon_da"
    assert [pfad.name for pfad in tmp_path.iterdir()] == ["m.gguf"]


def test_without_a_size_the_name_decides_as_before(tmp_path):
    (tmp_path / "m.gguf").write_bytes(b"irgendwas")
    with pytest.raises(DownloadFehler) as fehler:
        Modelldownload(tmp_path).starten("wer/Repo", "m.gguf")
    assert fehler.value.grund == "schon_da"


# --- A half file that is still there --------------------------------------

def _half_file(folder, name, repo="wer/Repo"):
    """The half file the download of ``name`` from ``repo`` writes."""
    return modelldownload._half_file(
        folder, name, f"https://huggingface.co/{repo}/resolve/main/{name}"
    )


def _begun_half(folder, name, data, version="v1", repo="wer/Repo"):
    """A half file left by an earlier run: its bytes, and the version of the
    file in the repository it was begun from."""
    half = _half_file(folder, name, repo)
    half.write_bytes(data)
    if version is not None:
        modelldownload._version_file(half).write_text(version, encoding="utf-8")
    return half


def test_a_half_file_is_continued_from_its_end(tmp_path, strom):
    whole = bytes(range(256)) * 20
    falsch = strom(whole, with_range=True, etag='"v1"')
    _begun_half(tmp_path, "m.gguf", whole[:3000], version='"v1"')
    download = Modelldownload(tmp_path)
    download.starten("wer/Repo", "m.gguf")
    assert warten_bis(lambda: download.stand().fertig)
    assert falsch.requests[0]["Range"] == "bytes=3000-"
    assert (tmp_path / "m.gguf").read_bytes() == whole
    assert list(tmp_path.glob("*.teil*")) == []
    # The bar counts what lay there already, and knows the whole size.
    assert download.stand().geladen == len(whole) == download.stand().gesamt


def test_the_bar_starts_at_the_half_file(tmp_path, strom):
    whole = b"v" * 5000
    strom(whole, with_range=True)
    _half_file(tmp_path, "m.gguf").write_bytes(whole[:4000])
    download = Modelldownload(tmp_path)
    download.starten("wer/Repo", "m.gguf")
    assert warten_bis(lambda: download.stand().fertig)
    assert download.stand().anteil == 1.0


def test_silence_without_a_half_file_there_is_no_range(tmp_path, strom):
    falsch = strom(b"y" * 4096, with_range=True)
    download = Modelldownload(tmp_path)
    download.starten("wer/Repo", "m.gguf")
    assert warten_bis(lambda: download.stand().fertig)
    assert "Range" not in falsch.requests[0]
    assert (tmp_path / "m.gguf").read_bytes() == b"y" * 4096


def test_a_server_that_answers_with_the_whole_file_starts_it_over(tmp_path, strom):
    whole = bytes(range(256)) * 20
    falsch = strom(whole, with_range=False, etag='"v1"')
    _begun_half(tmp_path, "m.gguf", b"halb" * 100, version='"v1"')
    download = Modelldownload(tmp_path)
    download.starten("wer/Repo", "m.gguf")
    assert warten_bis(lambda: download.stand().fertig)
    assert falsch.requests[0]["Range"] == "bytes=400-"
    assert (tmp_path / "m.gguf").read_bytes() == whole
    assert download.stand().geladen == len(whole)


def test_a_half_file_longer_than_the_file_begins_again(tmp_path, strom):
    whole = b"k" * 1000
    falsch = strom(whole, with_range=True, etag='"v1"')
    _begun_half(tmp_path, "m.gguf", b"z" * 5000, version='"v1"')
    download = Modelldownload(tmp_path)
    download.starten("wer/Repo", "m.gguf")
    assert warten_bis(lambda: download.stand().fertig)
    assert [a.get("Range") for a in falsch.requests] == ["bytes=5000-", None]
    assert (tmp_path / "m.gguf").read_bytes() == whole


def test_the_half_file_of_another_repository_is_not_continued(tmp_path, strom):
    """The same name from another repository is another file: the half file
    that lies there is of the other one."""
    whole = b"B" * 4096
    falsch = strom(whole, with_range=True)
    foreign = _half_file(tmp_path, "m.gguf", repo="anders/Repo")
    foreign.write_bytes(b"A" * 2000)
    download = Modelldownload(tmp_path)
    download.starten("wer/Repo", "m.gguf")
    assert warten_bis(lambda: download.stand().fertig)
    assert "Range" not in falsch.requests[0]
    assert (tmp_path / "m.gguf").read_bytes() == whole
    assert foreign.read_bytes() == b"A" * 2000


def test_a_half_file_of_a_replaced_file_begins_again(tmp_path, strom):
    """The repository holds another file under the name now: the end of the
    new one is not hung onto the beginning of the old one."""
    old = bytes(range(256)) * 20
    new = bytes(reversed(range(256))) * 20
    falsch = strom(new, with_range=True, etag='"b"')
    _begun_half(tmp_path, "m.gguf", old[:3000], version='"a"')
    download = Modelldownload(tmp_path)
    download.starten("wer/Repo", "m.gguf")
    assert warten_bis(lambda: download.stand().fertig)
    assert [a.get("Range") for a in falsch.requests] == ["bytes=3000-", None]
    assert (tmp_path / "m.gguf").read_bytes() == new
    assert list(tmp_path.glob("*.teil*")) == []
    assert download.stand().geladen == len(new)


def test_the_same_version_goes_on_with_only_the_rest_over_the_line(tmp_path, strom):
    whole = bytes(range(256)) * 20
    falsch = strom(whole, with_range=True, etag='"a"')
    _begun_half(tmp_path, "m.gguf", whole[:3000], version='"a"')
    download = Modelldownload(tmp_path)
    download.starten("wer/Repo", "m.gguf")
    assert warten_bis(lambda: download.stand().fertig)
    assert [a.get("Range") for a in falsch.requests] == ["bytes=3000-"]
    assert (tmp_path / "m.gguf").read_bytes() == whole


def test_a_half_file_without_a_known_version_begins_again_and_is_not_left(tmp_path, strom):
    whole = b"w" * 4096
    falsch = strom(whole, with_range=True, etag='"a"')
    _begun_half(tmp_path, "m.gguf", b"?" * 1500, version=None)
    download = Modelldownload(tmp_path)
    download.starten("wer/Repo", "m.gguf")
    assert warten_bis(lambda: download.stand().fertig)
    assert "Range" not in falsch.requests[0]
    assert (tmp_path / "m.gguf").read_bytes() == whole
    assert [pfad.name for pfad in tmp_path.iterdir()] == ["m.gguf"]


def test_a_server_that_names_no_version_never_continues(tmp_path, strom):
    """The half file has a version, the answer carries none: nothing proves
    it is the same file."""
    whole = b"q" * 4096
    falsch = strom(whole, with_range=True)
    _begun_half(tmp_path, "m.gguf", b"?" * 1500, version='"a"')
    download = Modelldownload(tmp_path)
    download.starten("wer/Repo", "m.gguf")
    assert warten_bis(lambda: download.stand().fertig)
    assert [a.get("Range") for a in falsch.requests] == ["bytes=1500-", None]
    assert (tmp_path / "m.gguf").read_bytes() == whole


def test_a_failed_download_leaves_neither_half_file_nor_version(tmp_path, strom):
    """Silence probe, next to ``test_ein_fehler_laesst_nichts_liegen``: the
    version file goes with its half file."""
    strom(b"", httpx.HTTPStatusError("weg", request=None, response=None), etag='"a"')
    _begun_half(tmp_path, "m.gguf", b"x" * 100, version='"a"')
    download = Modelldownload(tmp_path)
    download.starten("wer/Repo", "m.gguf")
    assert warten_bis(lambda: download.stand().fehler is not None)
    assert list(tmp_path.iterdir()) == []


def test_cancelling_removes_the_half_file(tmp_path, strom):
    whole = b"c" * 3_000_000
    falsch = strom(whole, with_range=True, etag='"a"')
    _begun_half(tmp_path, "m.gguf", whole[:1_000_000], version='"a"')
    download = Modelldownload(tmp_path)
    original = falsch.iter_bytes

    def cancelling(groesse):
        for piece in original(groesse):
            download.abbrechen()
            yield piece

    falsch.iter_bytes = cancelling
    download.starten("wer/Repo", "m.gguf")
    assert warten_bis(lambda: download.stand().fehler is not None)
    assert download.stand().fehler == "abgebrochen"
    assert list(tmp_path.iterdir()) == []


def test_a_split_model_continues_its_half_part(tmp_path, teile_server):
    server = teile_server(
        {"m-00001-of-00002.gguf": b"a" * 3000, "m-00002-of-00002.gguf": b"b" * 2000}
    )
    url = f"{modelldownload.BASIS}/wer/was/resolve/main/Q2_0/m-00001-of-00002.gguf"
    half = modelldownload._half_file(tmp_path, "m-00001-of-00002.gguf", url)
    half.write_bytes(b"a" * 1000)
    download = Modelldownload(tmp_path)
    server.download = download
    download.starten("wer/was", "Q2_0/m-00001-of-00002.gguf")
    assert warten_bis(lambda: download.stand().fertig)
    # The faked hub does not know ranges: it answers whole, and the file is whole.
    assert (tmp_path / "m-00001-of-00002.gguf").read_bytes() == b"a" * 3000
    assert (tmp_path / "m-00002-of-00002.gguf").read_bytes() == b"b" * 2000
    assert download.stand().geladen == 5000


def test_a_half_file_under_the_plain_name_is_removed(tmp_path, strom):
    strom(b"n" * 100)
    (tmp_path / "m.gguf.teil").write_bytes(b"alt")
    download = Modelldownload(tmp_path)
    download.starten("wer/Repo", "m.gguf")
    assert warten_bis(lambda: download.stand().fertig)
    assert [pfad.name for pfad in tmp_path.iterdir()] == ["m.gguf"]


# --- When it goes wrong ---------------------------------------------------


def test_ein_fehler_laesst_nichts_liegen(tmp_path, strom):
    strom(b"", httpx.HTTPStatusError("weg", request=None, response=None))
    download = Modelldownload(tmp_path)
    download.starten("repo", "kaputt.gguf")

    assert warten_bis(lambda: download.stand().fehler is not None)
    assert download.stand().fehler == "fehlgeschlagen"
    assert list(tmp_path.iterdir()) == []


def test_der_anteil_bleibt_bei_null_ohne_groesse(tmp_path):
    stand = modelldownload.Fortschritt(datei="x.gguf", geladen=5, gesamt=0)
    assert stand.anteil == 0.0


def test_der_anteil_rechnet(tmp_path):
    stand = modelldownload.Fortschritt(datei="x.gguf", geladen=25, gesamt=100)
    assert stand.anteil == 0.25


def test_der_zielname_darf_vom_fernen_abweichen(tmp_path, strom):
    # Several repositories call their projector plainly mmproj-BF16.gguf;
    # the local name carries the model, so two of those never collide.
    falsch = strom(b"abc")
    download = Modelldownload(tmp_path)
    download.starten("wer/was", "mmproj-BF16.gguf", ziel="modell-mmproj-BF16.gguf")
    assert warten_bis(lambda: download.stand().fertig)
    assert (tmp_path / "modell-mmproj-BF16.gguf").read_bytes() == b"abc"
    assert not (tmp_path / "mmproj-BF16.gguf").exists()
    # The address keeps the remote name — only the local file is renamed.
    assert falsch.adresse.endswith("/wer/was/resolve/main/mmproj-BF16.gguf")


def test_auch_der_zielname_ist_nie_ein_pfad(tmp_path):
    download = Modelldownload(tmp_path)
    try:
        download.starten("wer/was", "gut.gguf", ziel="../boese.gguf")
        raise AssertionError("no error")
    except DownloadFehler as fehler:
        assert fehler.grund == "name"


def test_schon_da_zaehlt_fuer_den_zielnamen(tmp_path):
    (tmp_path / "da-mmproj.gguf").write_bytes(b"x")
    download = Modelldownload(tmp_path)
    try:
        download.starten("wer/was", "mmproj-BF16.gguf", ziel="da-mmproj.gguf")
        raise AssertionError("no error")
    except DownloadFehler as fehler:
        assert fehler.grund == "schon_da"


# --- The bond into the folder manifest ------------------------------------


def test_ein_begleiter_wird_im_manifest_vermerkt(tmp_path, strom):
    from app import modellzuordnung

    # A projector fetched next to a model writes the bond, so the runner
    # later reads it instead of guessing from name prefixes.
    strom(b"abc")
    download = Modelldownload(tmp_path)
    # The projector lands in the vision sub-folder; the bond is written to the
    # model folder (the root), where the runner reads it.
    download.starten(
        "wer/was",
        "mmproj-BF16.gguf",
        ziel="modell-mmproj-BF16.gguf",
        gehoert_zu="modell.gguf",
        rolle="mmproj",
        ordner=tmp_path / "vision",
        manifest_ordner=tmp_path,
    )
    assert warten_bis(lambda: download.stand().fertig)
    assert (tmp_path / "vision" / "modell-mmproj-BF16.gguf").is_file()
    assert (
        modellzuordnung.fuer(tmp_path, "modell.gguf")["mmproj"]
        == "modell-mmproj-BF16.gguf"
    )


def test_ein_schlichter_download_vermerkt_nichts(tmp_path, strom):
    from app import modellzuordnung

    # No parent and no role: nothing but the file itself is left behind.
    strom(b"abc")
    download = Modelldownload(tmp_path)
    download.starten("wer/was", "modell.gguf")
    assert warten_bis(lambda: download.stand().fertig)
    assert modellzuordnung.lade(tmp_path) == {}


def test_ein_anderer_zielordner_bekommt_die_datei(tmp_path, strom):
    """A download routed to another kind's folder lands THERE — an
    embedding model in the chat folder would be invisible to the embedding
    server and a broken entry in the chat list."""
    strom(b"abc")
    chat = tmp_path / "chat"
    einbettung = tmp_path / "einbettung"
    download = Modelldownload(chat)
    download.starten("wer/was", "embed.gguf", ordner=einbettung)
    assert warten_bis(lambda: download.stand().fertig)
    assert (einbettung / "embed.gguf").is_file()
    assert not (chat / "embed.gguf").exists()


def test_schon_da_gilt_im_zielordner(tmp_path, strom):
    strom(b"abc")
    einbettung = tmp_path / "einbettung"
    einbettung.mkdir()
    (einbettung / "embed.gguf").write_bytes(b"alt")
    download = Modelldownload(tmp_path / "chat")
    with pytest.raises(DownloadFehler) as fehler:
        download.starten("wer/was", "embed.gguf", ordner=einbettung)
    assert fehler.value.grund == "schon_da"


def test_der_begleiter_vermerk_folgt_dem_zielordner(tmp_path, strom):
    from app import modellzuordnung

    strom(b"abc")
    einbettung = tmp_path / "einbettung"
    download = Modelldownload(tmp_path / "chat")
    download.starten("wer/was", "mmproj.gguf", ziel="m-mmproj.gguf",
                     gehoert_zu="m.gguf", rolle="mmproj", ordner=einbettung)
    assert warten_bis(lambda: download.stand().fertig)
    assert modellzuordnung.lade(einbettung) != {}
    assert modellzuordnung.lade(tmp_path / "chat") == {}


# --- A split model ---------------------------------------------------------


class TeileServer:
    """Stands in for the hub with one answer per address: HEAD tells the
    size, GET hands out the bytes. ``beim_teil`` runs as a part begins, so a
    test can cancel or fail in the middle of a split download."""

    def __init__(self, teile: dict[str, bytes], beim_teil=None, ohne_groesse=()):
        self._teile = teile
        self._beim_teil = beim_teil
        self._ohne_groesse = ohne_groesse
        self.geholt: list[str] = []
        self.gesamt_beim_ersten_byte: int | None = None
        self.download: Modelldownload | None = None

    def head(self, adresse, **kwargs):
        name = adresse.rsplit("/", 1)[-1]
        if name in self._ohne_groesse:
            return _Antwort({})
        return _Antwort({"content-length": str(len(self._teile[name]))})

    def stream(self, methode, adresse, **kwargs):
        name = adresse.rsplit("/", 1)[-1]
        if self.gesamt_beim_ersten_byte is None and self.download is not None:
            self.gesamt_beim_ersten_byte = self.download.stand().gesamt
        self.geholt.append(name)
        if self._beim_teil:
            self._beim_teil(len(self.geholt), self.download)
        return FalscherStrom(self._teile[name])


class _Antwort:
    def __init__(self, headers):
        self.headers = headers

    def raise_for_status(self):
        return None


@pytest.fixture
def teile_server(monkeypatch):
    def setzen(teile, beim_teil=None, ohne_groesse=()):
        server = TeileServer(teile, beim_teil, ohne_groesse)
        monkeypatch.setattr(modelldownload.httpx, "head", server.head)
        monkeypatch.setattr(modelldownload.httpx, "stream", server.stream)
        return server
    return setzen


def test_zwei_teile_landen_beide_im_ordner(tmp_path, teile_server):
    server = teile_server(
        {"m-00001-of-00002.gguf": b"a" * 3000, "m-00002-of-00002.gguf": b"b" * 2000}
    )
    download = Modelldownload(tmp_path)
    server.download = download
    download.starten("wer/was", "Q2_0/m-00001-of-00002.gguf")

    assert warten_bis(lambda: download.stand().fertig)
    assert (tmp_path / "m-00001-of-00002.gguf").read_bytes() == b"a" * 3000
    assert (tmp_path / "m-00002-of-00002.gguf").read_bytes() == b"b" * 2000
    assert not list(tmp_path.glob("*.teil"))
    assert server.geholt == ["m-00001-of-00002.gguf", "m-00002-of-00002.gguf"]
    # The bar spans both parts, and knows it before the first byte.
    assert server.gesamt_beim_ersten_byte == 5000
    assert download.stand().geladen == 5000


def test_abbruch_nach_teil_eins_laesst_nichts_liegen(tmp_path, teile_server):
    def beim_teil(nummer, download):
        if nummer == 2:
            download.abbrechen()

    server = teile_server(
        {"m-00001-of-00002.gguf": b"a" * 3000, "m-00002-of-00002.gguf": b"b" * 2000},
        beim_teil,
    )
    download = Modelldownload(tmp_path)
    server.download = download
    download.starten("wer/was", "m-00001-of-00002.gguf")

    assert warten_bis(lambda: download.stand().fehler is not None)
    assert download.stand().fehler == "abgebrochen"
    assert list(tmp_path.iterdir()) == []


def test_ein_fehler_im_zweiten_teil_laesst_nichts_liegen(tmp_path, teile_server):
    def beim_teil(nummer, download):
        if nummer == 2:
            raise httpx.ConnectError("weg")

    server = teile_server(
        {"m-00001-of-00002.gguf": b"a" * 3000, "m-00002-of-00002.gguf": b"b" * 2000},
        beim_teil,
    )
    download = Modelldownload(tmp_path)
    server.download = download
    download.starten("wer/was", "m-00001-of-00002.gguf")

    assert warten_bis(lambda: download.stand().fehler is not None)
    assert list(tmp_path.iterdir()) == []


def test_ein_geteiltes_modell_ist_schon_da_wenn_alle_teile_da_sind(tmp_path):
    (tmp_path / "m-00001-of-00002.gguf").write_bytes(b"x")
    (tmp_path / "m-00002-of-00002.gguf").write_bytes(b"y")
    with pytest.raises(DownloadFehler) as fehler:
        Modelldownload(tmp_path).starten("wer/was", "Q2_0/m-00001-of-00002.gguf")
    assert fehler.value.grund == "schon_da"


def test_ein_vorhandener_teil_bleibt_und_wird_nicht_geholt(tmp_path, teile_server):
    """Part 2 of three lies there already: it stays byte for byte, parts 1
    and 3 are fetched, and the bar spans only what is fetched."""
    (tmp_path / "m-00002-of-00003.gguf").write_bytes(b"mein-eigener-teil")
    server = teile_server({
        "m-00001-of-00003.gguf": b"a" * 3000,
        "m-00002-of-00003.gguf": b"b" * 2000,
        "m-00003-of-00003.gguf": b"c" * 1000,
    })
    download = Modelldownload(tmp_path)
    server.download = download
    download.starten("wer/was", "Q2_0/m-00001-of-00003.gguf")

    assert warten_bis(lambda: download.stand().fertig)
    assert (tmp_path / "m-00002-of-00003.gguf").read_bytes() == b"mein-eigener-teil"
    assert (tmp_path / "m-00001-of-00003.gguf").read_bytes() == b"a" * 3000
    assert (tmp_path / "m-00003-of-00003.gguf").read_bytes() == b"c" * 1000
    assert server.geholt == ["m-00001-of-00003.gguf", "m-00003-of-00003.gguf"]
    assert server.gesamt_beim_ersten_byte == 4000
    assert not list(tmp_path.glob("*.teil"))


def test_liegt_nur_teil_eins_da_wird_der_rest_geholt(tmp_path, teile_server):
    """A model whose part 1 lies there and whose other parts do not is not
    there: the rest is fetched, part 1 stays."""
    (tmp_path / "m-00001-of-00002.gguf").write_bytes(b"alt")
    server = teile_server({"m-00001-of-00002.gguf": b"a" * 10, "m-00002-of-00002.gguf": b"b" * 20})
    download = Modelldownload(tmp_path)
    server.download = download
    download.starten("wer/was", "m-00001-of-00002.gguf")

    assert warten_bis(lambda: download.stand().fertig)
    assert (tmp_path / "m-00001-of-00002.gguf").read_bytes() == b"alt"
    assert (tmp_path / "m-00002-of-00002.gguf").read_bytes() == b"b" * 20
    assert server.geholt == ["m-00002-of-00002.gguf"]


def test_ein_abbruch_laesst_den_vorhandenen_teil_liegen(tmp_path, teile_server):
    """A cancelled or failed fetch takes away what it began, never the part
    that was there before."""
    (tmp_path / "m-00002-of-00002.gguf").write_bytes(b"mein-eigener-teil")

    def beim_teil(nummer, download):
        raise httpx.ConnectError("weg")

    server = teile_server(
        {"m-00001-of-00002.gguf": b"a" * 10, "m-00002-of-00002.gguf": b"b" * 20}, beim_teil,
    )
    download = Modelldownload(tmp_path)
    server.download = download
    download.starten("wer/was", "m-00001-of-00002.gguf")

    assert warten_bis(lambda: download.stand().fehler is not None)
    assert [p.name for p in tmp_path.iterdir()] == ["m-00002-of-00002.gguf"]
    assert (tmp_path / "m-00002-of-00002.gguf").read_bytes() == b"mein-eigener-teil"


def test_ein_einzelner_teil_zwei_holt_nur_sich(tmp_path, teile_server):
    """Only part 1 names the whole model; any other name is one file."""
    server = teile_server({"m-00002-of-00002.gguf": b"b" * 10})
    download = Modelldownload(tmp_path)
    server.download = download
    download.starten("wer/was", "m-00002-of-00002.gguf")
    assert warten_bis(lambda: download.stand().fertig)
    assert server.geholt == ["m-00002-of-00002.gguf"]


def test_eine_unbekannte_teilgroesse_macht_das_ganze_unbekannt(tmp_path, teile_server):
    """A partial sum would run the bar past its end."""
    server = teile_server(
        {"m-00001-of-00002.gguf": b"a" * 3000, "m-00002-of-00002.gguf": b"b" * 2000},
        ohne_groesse=("m-00002-of-00002.gguf",),
    )
    download = Modelldownload(tmp_path)
    server.download = download
    download.starten("wer/was", "m-00001-of-00002.gguf")
    assert warten_bis(lambda: download.stand().fertig)
    assert server.gesamt_beim_ersten_byte == 0


def test_all_parts_there_reads_every_part_of_a_split_model(tmp_path):
    name = "sub/m-00001-of-00003.gguf"
    (tmp_path / "m-00001-of-00003.gguf").write_bytes(b"1")
    (tmp_path / "m-00002-of-00003.gguf").write_bytes(b"2")
    assert modelldownload.all_parts_there(tmp_path, name) is False
    (tmp_path / "m-00003-of-00003.gguf").write_bytes(b"3")
    assert modelldownload.all_parts_there(tmp_path, name) is True


def test_silence_all_parts_there_for_a_model_in_one_part_is_the_file_itself(tmp_path):
    assert modelldownload.all_parts_there(tmp_path, "einzeln.gguf") is False
    (tmp_path / "einzeln.gguf").write_bytes(b"x")
    assert modelldownload.all_parts_there(tmp_path, "sub/einzeln.gguf") is True


class _Gone(BaseException):
    """What a killed process looks like to the download: nothing catches it."""


def test_a_half_file_that_is_left_lying_carries_its_version(tmp_path, strom):
    whole = b"s" * 3_000_000
    falsch = strom(whole, with_range=True, etag='"a"')
    original = falsch.iter_bytes

    def dying(groesse):
        for index, piece in enumerate(original(groesse)):
            if index == 1:
                raise _Gone()
            yield piece

    falsch.iter_bytes = dying
    half = _half_file(tmp_path, "m.gguf")
    with pytest.raises(_Gone):
        Modelldownload(tmp_path)._fetch_part(
            "https://huggingface.co/wer/Repo/resolve/main/m.gguf", half, {}, single=True
        )

    assert half.is_file()
    assert modelldownload._version_file(half).read_text(encoding="utf-8") == '"a"'


def test_a_file_replaced_in_the_repository_is_fetched_whole_after_a_stop(tmp_path, strom):
    """The whole way: the first run stops in the middle of version "a"; the
    repository then holds another file under the name, version "b"; the next
    download delivers exactly the new file, byte for byte."""
    old = bytes(range(256)) * 16000
    new = bytes(reversed(range(256))) * 16000
    falsch = strom(old, with_range=True, etag='"a"')
    original = falsch.iter_bytes

    def dying(groesse):
        for index, piece in enumerate(original(groesse)):
            if index == 1:
                raise _Gone()
            yield piece

    falsch.iter_bytes = dying
    half = _half_file(tmp_path, "m.gguf")
    with pytest.raises(_Gone):
        Modelldownload(tmp_path)._fetch_part(
            "https://huggingface.co/wer/Repo/resolve/main/m.gguf", half, {}, single=True
        )
    assert half.is_file()

    falsch = strom(new, with_range=True, etag='"b"')
    download = Modelldownload(tmp_path)
    download.starten("wer/Repo", "m.gguf")
    assert warten_bis(lambda: download.stand().fertig)
    assert (tmp_path / "m.gguf").read_bytes() == new
    assert [pfad.name for pfad in tmp_path.iterdir()] == ["m.gguf"]


def test_an_unreadable_version_file_is_no_version(tmp_path, strom):
    whole = b"u" * 4096
    falsch = strom(whole, with_range=True, etag='"a"')
    half = _begun_half(tmp_path, "m.gguf", b"?" * 1000, version=None)
    modelldownload._version_file(half).write_bytes(b"\xff\xfe\x00\xd8")
    download = Modelldownload(tmp_path)
    download.starten("wer/Repo", "m.gguf")
    assert warten_bis(lambda: download.stand().fertig)
    assert "Range" not in falsch.requests[0]
    assert (tmp_path / "m.gguf").read_bytes() == whole
