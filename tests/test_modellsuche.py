"""Searching the model catalogue.

Nothing here talks to Hugging Face: the answer is faked, because what is
being tested is our side — which kinds we allow, what we make of an entry,
and what happens when somebody else's server has a bad day.
"""

from __future__ import annotations

import httpx
import pytest

from app.api.v1 import modellsuche


class FalscheAntwort:
    def __init__(self, daten, fehler=None):
        self._daten = daten
        self._fehler = fehler

    def raise_for_status(self):
        if self._fehler:
            raise self._fehler

    def json(self):
        return self._daten


class FalscherKlient:
    """Stands in for httpx and remembers what it was asked for."""

    letzte_parameter: dict | None = None
    alle_parameter: list[dict] = []

    def __init__(self, daten, fehler=None):
        self._antwort = FalscheAntwort(daten, fehler)

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, adresse, params=None):
        FalscherKlient.letzte_parameter = params
        FalscherKlient.alle_parameter.append(params)
        if isinstance(self._antwort._fehler, httpx.HTTPError):
            raise self._antwort._fehler
        return self._antwort


@pytest.fixture
def katalog(monkeypatch):
    def setzen(daten, fehler=None):
        FalscherKlient.letzte_parameter = None
        FalscherKlient.alle_parameter = []
        monkeypatch.setattr(modellsuche.httpx, "AsyncClient", FalscherKlient(daten, fehler))
    return setzen


EINTRAG = {
    "modelId": "lmstudio-community/Qwen3.6-27B-MLX-6bit",
    "downloads": 829410,
    "likes": 14,
    "pipeline_tag": "text-generation",
}


# --- What comes back ------------------------------------------------------


def test_ein_eintrag_wird_zu_einem_fund(client, katalog):
    katalog([EINTRAG])
    antwort = client.get("/api/v1/models/search?q=qwen3")
    assert antwort.status_code == 200

    fund = antwort.json()[0]
    assert fund["anbieter"] == "lmstudio-community"
    assert fund["name"] == "Qwen3.6-27B-MLX-6bit"
    assert fund["ladungen"] == 829410
    assert fund["beliebt"] == 14
    assert "art" not in fund


def test_ein_name_ohne_anbieter_bleibt_ganz(client, katalog):
    katalog([{"modelId": "einzelname", "downloads": 5}])
    fund = client.get("/api/v1/models/search?q=x").json()[0]
    assert fund["anbieter"] == ""
    assert fund["name"] == "einzelname"


def test_muell_im_katalog_wird_uebergangen(client, katalog):
    katalog([EINTRAG, "kein Eintrag", None])
    assert len(client.get("/api/v1/models/search?q=x").json()) == 1


# --- What we ask for ------------------------------------------------------


def test_gesucht_wird_nach_ladungen_sortiert(client, katalog):
    katalog([])
    client.get("/api/v1/models/search?q=qwen&art=chat&anzahl=5")
    parameter = FalscherKlient.letzte_parameter
    assert parameter["filter"] == "gguf"
    assert parameter["sort"] == "downloads"
    assert parameter["limit"] == 5


def test_chat_sucht_ohne_etikett_und_haelt_die_anderen_arten_draussen(client, katalog):
    """The chat tab queries WITHOUT a pipeline tag — most community quant
    repositories carry none, and a hard tag filter would hide them — and
    drops the kinds the other tabs own from the answer instead."""
    katalog([
        EINTRAG,
        {"modelId": "leise/ohne-etikett", "downloads": 7},
        {"modelId": "fremd/einbettung", "downloads": 9, "pipeline_tag": "feature-extraction"},
        {"modelId": "fremd/aehnlichkeit", "downloads": 9, "pipeline_tag": "sentence-similarity"},
        {"modelId": "fremd/bild", "downloads": 9, "pipeline_tag": "text-to-image"},
    ])
    antwort = client.get("/api/v1/models/search?q=x&art=chat").json()
    assert "pipeline_tag" not in FalscherKlient.letzte_parameter
    assert [f["id"] for f in antwort] == [EINTRAG["modelId"], "leise/ohne-etikett"]


def test_einbettung_fragt_beide_etiketten_und_meldet_jeden_fund_einmal(client, katalog):
    """Half the known embedding repositories say "sentence-similarity"
    instead of "feature-extraction" — one tag alone loses them. A repo
    carrying both tags may come back twice and must be answered once."""
    katalog([{"modelId": "nomic/embed", "downloads": 12, "pipeline_tag": "feature-extraction"}])
    antwort = client.get("/api/v1/models/search?q=x&art=einbettung").json()
    etiketten = {p.get("pipeline_tag") for p in FalscherKlient.alle_parameter}
    assert etiketten == {"feature-extraction", "sentence-similarity"}
    assert [f["id"] for f in antwort] == ["nomic/embed"]


def test_sprache_fragt_beide_etiketten_und_meldet_jeden_fund_einmal(client, katalog):
    """Speech models come with two tags, listening and speaking; the tab asks
    for both with the file filter kept, and a repository that carries both
    comes back once. The chat tab, which asks without a tag, drops them."""
    katalog([{"modelId": "kokoro/tts", "downloads": 12, "pipeline_tag": "text-to-speech"}])
    antwort = client.get("/api/v1/models/search?q=gguf&art=sprache").json()
    etiketten = {p.get("pipeline_tag") for p in FalscherKlient.alle_parameter}
    assert etiketten == {"automatic-speech-recognition", "text-to-speech"}
    assert all(p["filter"] == "gguf" for p in FalscherKlient.alle_parameter)
    assert [f["id"] for f in antwort] == ["kokoro/tts"]
    katalog([{"modelId": "kokoro/tts", "downloads": 12, "pipeline_tag": "text-to-speech"}])
    assert client.get("/api/v1/models/search?q=gguf&art=chat").json() == []


def test_bild_fragt_nur_sein_eigenes_etikett(client, katalog):
    katalog([])
    client.get("/api/v1/models/search?q=x&art=bild")
    assert [p.get("pipeline_tag") for p in FalscherKlient.alle_parameter] == ["text-to-image"]


def test_bild_sucht_ohne_gguf_zwang(client, katalog):
    """The shipped drawer reads safetensors too, and the big image
    checkpoints live on HF almost only as safetensors — a gguf filter hid
    exactly what people came for. Chat and embedding keep the filter."""
    katalog([])
    client.get("/api/v1/models/search?q=cyber&art=bild")
    assert "filter" not in FalscherKlient.letzte_parameter
    katalog([])
    client.get("/api/v1/models/search?q=qwen&art=chat")
    assert FalscherKlient.letzte_parameter["filter"] == "gguf"
    katalog([])
    client.get("/api/v1/models/search?q=nomic&art=einbettung")
    assert FalscherKlient.letzte_parameter["filter"] == "gguf"


def test_der_alte_name_gguf_zaehlt_als_chat(client, katalog):
    # A page from before the tabs still asks with art=gguf. It meant what
    # the chat tab means now, and it must not be told "unknown kind".
    katalog([EINTRAG])
    antwort = client.get("/api/v1/models/search?q=x&art=gguf")
    assert antwort.status_code == 200
    assert "pipeline_tag" not in FalscherKlient.letzte_parameter


@pytest.mark.parametrize("art", ["safetensors", "pytorch", "onnx", "mlx", ""])
def test_andere_arten_werden_abgelehnt(client, katalog, art):
    # Only what the program can fetch as one file and start by itself —
    # everything else would be a promise we cannot keep. MLX is on this
    # list for the same reason it left the runner.
    katalog([])
    assert client.get(f"/api/v1/models/search?q=x&art={art}").status_code == 400


def test_ohne_suchbegriff_geht_nichts(client, katalog):
    katalog([])
    assert client.get("/api/v1/models/search?q=").status_code == 422


# --- When the other side has a bad day ------------------------------------


def test_katalog_antwortet_nicht(client, katalog):
    katalog(None, httpx.ConnectError("weg"))
    assert client.get("/api/v1/models/search?q=x").status_code == 502


def test_katalog_antwortet_unsinn(client, katalog):
    # An empty list means "nothing found"; something that is not a list at
    # all means the catalogue is broken, and that must not look the same.
    katalog({"unerwartet": True})
    assert client.get("/api/v1/models/search?q=x").status_code == 502


# --- The tab vocabulary lives in three places; this keeps them one ---------


def test_tab_namen_laufen_ueberall_gleich():
    """The kinds are named in the backend (ARTEN), in the frontend tab row
    (modellempfehlungen.js ARTEN) and as locale labels (katalog.art_*).
    Nothing ties them together at runtime — this test does.

    A kind may deliberately have NO tab (the sibling Exe programs share this
    search); it is declared here so a missing tab stays a choice, not an
    accident. Today every searchable kind has its tab, the video kind
    included."""
    import json
    import re
    from pathlib import Path

    OHNE_TAB: set[str] = set()

    wurzel = Path(__file__).resolve().parent.parent
    js = (wurzel / "frontend/src/lib/modellempfehlungen.js").read_text(encoding="utf-8")
    treffer = re.search(r"export const ARTEN = \[([^\]]*)\]", js)
    assert treffer, "frontend ARTEN not found"
    vorn = re.findall(r"'([a-z]+)'", treffer.group(1))

    hinten = [art for art in modellsuche.ARTEN if art not in OHNE_TAB]
    assert vorn == hinten, "frontend tabs != backend kinds (without the tabless ones)"

    for sprache in ("de", "en"):
        texte = json.loads((wurzel / f"app/locales/{sprache}.json").read_text(encoding="utf-8"))
        for art in vorn:
            assert texte["katalog"].get(f"art_{art}"), f"{sprache}: katalog.art_{art} is missing"


# --- The catalogue's own source, where no test runner reaches --------------


def _quelle(pfad: str) -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parent.parent / pfad).read_text(encoding="utf-8")


def test_ein_begleiter_bekommt_seinen_unterordner_mit():
    """A companion used to land in the model folder's root and was only
    sorted into vision/ or mtp/ at the next service start — until then the
    model reported "no projector". The job now carries the sub-folder its
    role belongs in, and the job's own value wins over the tab's.

    Read out of the source, because the window has no test runner: what is
    checked is the VALUE each role resolves to, not how the line is typed."""
    import re

    js = _quelle("frontend/src/lib/modellempfehlungen.js")
    svelte = _quelle("frontend/src/teile/Katalog.svelte")

    ziele = re.search(r"export const ZUBEHOER_ZIEL = \{(.*?)\n\}", js, re.S)
    assert ziele, "ZUBEHOER_ZIEL not found"
    unterordner = dict(
        re.findall(r"(\w+):\s*\{[^}]*unterordner:\s*'([^']+)'", ziele.group(1))
    )
    assert unterordner["mmproj"] == "vision"
    assert unterordner["mtp"] == "mtp"

    jobs = re.search(r"function begleiterJobs\(f\) \{(.*?)\n  \}", svelte, re.S)
    assert jobs, "begleiterJobs not found"
    for rolle in ("mmproj", "mtp"):
        # Over the whole pushed object, not one physical line: these calls
        # are long enough that a formatter would wrap them.
        push = re.search(
            r"jobs\.push\(\{[^}]*rolle: '" + rolle + r"'[^}]*\}\)", jobs.group(1), re.S
        )
        assert push, f"{rolle}: no jobs.push with this role"
        assert f"unterordner: ZUBEHOER_ZIEL.{rolle}.unterordner" in push.group(0)

    # And the job's own sub-folder beats the tab's, the way its role does.
    assert re.search(
        r"unterordner:\s*j\.unterordner\s*\?\?\s*ziel\.unterordner\s*\?\?\s*null", svelte
    )


def test_die_karte_traegt_keine_eigene_zustandsfarbe():
    """Blue, yellow, violet and olive are palette names, not hex values: a
    literal here carries one appearance's tone into all three. The three
    image-side accessory kinds have no palette name yet and are the only
    literals left."""
    import re

    js = _quelle("frontend/src/lib/modellempfehlungen.js")
    block = re.search(r"export const SORTE_FARBE = \{(.*?)\}", js, re.S)
    faehig = re.search(r"export const FAEHIGKEIT_FARBE = \{(.*?)\}", js, re.S)
    assert block and faehig
    assert set(re.findall(r"#[0-9a-f]{6}", block.group(1))) == {
        "#bd7a53",
        "#4e8f8b",
        "#b56d84",
    }
    assert not re.findall(r"#[0-9a-f]{6}", faehig.group(1))
    for name in ("--blau", "--violett", "--gelb", "--oliv"):
        assert f"var({name})" in js

    # One capability, one colour, everywhere: the bolt and the eye in the
    # server row wear the same names, or the tag and the live indicator
    # drift apart in every appearance but the light one. Checked as "no
    # colour literal anywhere", not as two exact spellings: a re-indent
    # must not fail, and a re-cased `#5B8DBE` must not pass.
    regler = _quelle("frontend/src/teile/Serverregler.svelte")
    assert "var(--blau)" in regler and "var(--violett)" in regler
    assert not re.search(r"color:\s*#[0-9a-fA-F]{3,8}", regler)


def test_ein_farbton_ueberlebt_einen_palettennamen():
    """The old form appended `55` or `18` to the colour string, which only
    worked while every colour was a literal — and produced invalid CSS for
    the `var(--text-leise)` fallback even then."""
    js = _quelle("frontend/src/lib/modellempfehlungen.js")
    assert "export function farbton(farbe, prozent)" in js
    assert "color-mix(in srgb, ${farbe} ${prozent}%, transparent)" in js
    for pfad in ("frontend/src/teile/Modellkarte.svelte", "frontend/src/teile/Modelldetail.svelte"):
        quelle = _quelle(pfad)
        assert "farbton(farbe," in quelle
        for schwanz in ("${farbe}55", "${farbe}18", "${farbe}66"):
            assert schwanz not in quelle


# --- The picture of a repository's owner ------------------------------------


def _avatar_world(monkeypatch):
    """Names resolve from this table only; no test reaches the network."""
    import socket

    from app import public_host

    names = {"huggingface.co": "34.0.0.1", "cdn-avatars.huggingface.co": "34.0.0.2",
             "inside.example": "10.0.0.5"}

    def resolve(host, *_args, **_kwargs):
        if host not in names:
            raise socket.gaierror(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (names[host], 0))]

    monkeypatch.setattr(public_host.socket, "getaddrinfo", resolve)


def _png_bytes(edge: int = 48) -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (edge, edge), (30, 120, 200)).save(buffer, "PNG")
    return buffer.getvalue()


class _Hugging:
    """A Hugging Face that answers from a table of addresses and keeps what
    it was asked."""

    def __init__(self, answers: dict[str, httpx.Response]):
        self.answers = answers
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.answers.get(str(request.url))
        return answer if answer is not None else httpx.Response(404)

    @property
    def transport(self):
        return httpx.MockTransport(self)

    @property
    def asked(self) -> list[str]:
        return [str(request.url) for request in self.requests]


PICTURE = "https://cdn-avatars.huggingface.co/v1/production/uploads/abc/face.png"


def _overview(address: str | None = PICTURE) -> httpx.Response:
    return httpx.Response(200, json={"name": "x", "avatarUrl": address} if address else {"name": "x"})


def _picture() -> httpx.Response:
    return httpx.Response(200, content=_png_bytes(), headers={"content-type": "image/png"})


@pytest.fixture
def avatar_world(monkeypatch):
    _avatar_world(monkeypatch)


async def test_an_organisation_gets_its_picture_as_a_data_url(avatar_world):
    import base64

    hugging = _Hugging({
        "https://huggingface.co/api/organizations/LiquidAI/overview": _overview(),
        PICTURE: _picture(),
    })

    image = await modellsuche.owner_avatar("LiquidAI", hugging.transport)

    assert image == "data:image/png;base64," + base64.b64encode(_png_bytes()).decode()
    assert hugging.asked == [
        "https://huggingface.co/api/organizations/LiquidAI/overview", PICTURE
    ]


async def test_after_the_organisation_the_user_account_of_that_name_is_asked(avatar_world):
    hugging = _Hugging({
        "https://huggingface.co/api/users/TheDrummer/overview": _overview(),
        PICTURE: _picture(),
    })

    image = await modellsuche.owner_avatar("TheDrummer", hugging.transport)

    assert image and image.startswith("data:image/png;base64,")
    assert hugging.asked == [
        "https://huggingface.co/api/organizations/TheDrummer/overview",
        "https://huggingface.co/api/users/TheDrummer/overview",
        PICTURE,
    ]


async def test_a_picture_named_relative_to_the_site_is_taken(avatar_world):
    hugging = _Hugging({
        "https://huggingface.co/api/organizations/acme/overview": _overview("/avatars/face.png"),
        "https://huggingface.co/avatars/face.png": _picture(),
    })

    assert await modellsuche.owner_avatar("acme", hugging.transport) is not None


async def test_nothing_asked_carries_credentials(avatar_world, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_secret")
    hugging = _Hugging({
        "https://huggingface.co/api/organizations/acme/overview": _overview(),
        PICTURE: _picture(),
    })

    await modellsuche.owner_avatar("acme", hugging.transport)

    assert hugging.requests
    for request in hugging.requests:
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers


@pytest.mark.parametrize("address", [
    "http://cdn-avatars.huggingface.co/face.png",  # not https
    "ftp://cdn-avatars.huggingface.co/face.png",
    "https://inside.example/face.png",  # leads to a private place
    "data:image/png;base64,AAAA",
])
async def test_silence_a_picture_that_is_not_a_public_https_one_is_not_asked(avatar_world, address):
    hugging = _Hugging({"https://huggingface.co/api/organizations/acme/overview": _overview(address)})

    assert await modellsuche.owner_avatar("acme", hugging.transport) is None
    assert hugging.asked == ["https://huggingface.co/api/organizations/acme/overview"]


async def test_silence_a_redirect_is_not_followed(avatar_world):
    hugging = _Hugging({
        "https://huggingface.co/api/organizations/acme/overview": _overview(),
        PICTURE: httpx.Response(302, headers={"location": "https://cdn-avatars.huggingface.co/other.png"}),
    })

    assert await modellsuche.owner_avatar("acme", hugging.transport) is None
    assert len(hugging.requests) == 2


async def test_silence_a_redirect_of_the_overview_is_not_followed(avatar_world):
    """The overview itself may not send the request somewhere else either:
    the one address asked of Hugging Face is the one that is answered."""
    hugging = _Hugging({
        "https://huggingface.co/api/organizations/acme/overview": httpx.Response(
            302, headers={"location": "https://elsewhere.example/overview"},
        ),
        "https://elsewhere.example/overview": _overview(),
        PICTURE: _picture(),
    })

    assert await modellsuche.owner_avatar("acme", hugging.transport) is None
    assert hugging.asked == ["https://huggingface.co/api/organizations/acme/overview"]


async def test_silence_a_picture_too_large_or_no_picture_gives_nothing(avatar_world):
    from app.tools import mcp_logo

    big = httpx.Response(200, content=b"\x89PNG\r\n\x1a\n" + b"0" * (mcp_logo.MAX_BYTES + 10))
    not_a_picture = httpx.Response(200, content=b"<html>no</html>")
    for answer in (big, not_a_picture, httpx.Response(500)):
        hugging = _Hugging({
            "https://huggingface.co/api/organizations/acme/overview": _overview(),
            PICTURE: answer,
        })
        assert await modellsuche.owner_avatar("acme", hugging.transport) is None


async def test_silence_an_overview_without_a_picture_or_too_large_gives_nothing(avatar_world):
    huge = httpx.Response(200, content=b"{" + b" " * (modellsuche.MAX_OVERVIEW_BYTES + 10) + b"}")
    for answer in (_overview(None), huge, httpx.Response(200, json=["not", "an", "object"]),
                   httpx.Response(500)):
        hugging = _Hugging({"https://huggingface.co/api/organizations/acme/overview": answer})
        assert await modellsuche.owner_avatar("acme", hugging.transport) is None
        assert PICTURE not in hugging.asked


async def test_an_owner_with_neither_organisation_nor_account_gives_nothing(avatar_world):
    hugging = _Hugging({})

    assert await modellsuche.owner_avatar("nobody", hugging.transport) is None
    assert len(hugging.requests) == 2


@pytest.mark.parametrize("name", ["../etc/passwd", "a/b", "", "-x", "a b", "x" * 97, "a?b=c"])
async def test_silence_a_name_that_is_no_hugging_face_name_asks_nothing(avatar_world, name):
    hugging = _Hugging({})

    assert await modellsuche.owner_avatar(name, hugging.transport) is None
    assert hugging.requests == []


async def test_a_failed_request_gives_nothing_and_raises_nothing(avatar_world):
    def broken(request):
        raise httpx.ConnectError("down")

    assert await modellsuche.owner_avatar("acme", httpx.MockTransport(broken)) is None


def test_the_route_answers_with_the_picture_and_may_be_kept(client, monkeypatch):
    async def fixed(owner, transport=None):
        return "data:image/png;base64,AAAA"

    monkeypatch.setattr(modellsuche, "owner_avatar", fixed)

    answer = client.get("/api/v1/models/avatar/LiquidAI")

    assert answer.status_code == 200
    assert answer.json() == {"image": "data:image/png;base64,AAAA"}
    assert "max-age=86400" in answer.headers["cache-control"]


def test_silence_the_route_answers_not_found_without_a_picture(client, monkeypatch):
    async def none(owner, transport=None):
        return None

    monkeypatch.setattr(modellsuche, "owner_avatar", none)

    answer = client.get("/api/v1/models/avatar/nobody")

    assert answer.status_code == 404
