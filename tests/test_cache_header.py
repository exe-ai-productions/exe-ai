"""HTML must never come blindly from the browser cache.

index.html carries the reference to the current bundle — if it comes
from the cache, the app keeps running on an old version after an update
("the app doesn't update"). no-cache forces a check with the server;
everything that is not a file of the static folder stays untouched, the
bundles cache via their changing file names. The files of the static folder
whose names do not change from one version to the next — the sounds, the
signs, the manifest — are checked back with the server as well: a stored
copy would otherwise be taken for fresh long after an update.
"""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from app.static_revalidate import RevalidatingStaticFiles, is_hashed


def test_html_traegt_no_cache(client):
    antwort = client.get("/app/")
    assert antwort.status_code == 200
    assert antwort.headers["cache-control"] == "no-cache"


def test_nicht_html_bleibt_unangetastet(client):
    antwort = client.get("/health")
    assert antwort.status_code == 200
    assert "cache-control" not in antwort.headers


def test_a_sound_is_checked_back_with_the_server(client):
    response = client.get("/klaenge/fertig.wav")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["etag"]


def test_a_file_with_an_unchanging_name_is_checked_back_when_it_is_asked_for_again(client):
    """The answer to a request that carries the ETag is a 304, and it carries
    the rule too: the stored copy is kept in the browser under it."""
    first = client.get("/klaenge/fertig.wav")
    second = client.get("/klaenge/fertig.wav", headers={"If-None-Match": first.headers["etag"]})
    assert second.status_code == 304
    assert second.headers["cache-control"] == "no-cache"


def test_the_signs_and_the_manifest_are_checked_back_too(client):
    for address in ("/favicon.svg", "/manifest.webmanifest"):
        response = client.get(address)
        assert response.status_code == 200, address
        assert response.headers["cache-control"] == "no-cache", address


def test_a_bundle_with_a_checksum_in_its_name_keeps_its_stored_copy(tmp_path):
    """The silent case: what changes its name with every build is left as it
    was, so it is not asked for again at every visit — while a file beside it
    is. Run on a folder of its own, so it does not need a built frontend."""
    (tmp_path / "app" / "assets").mkdir(parents=True)
    (tmp_path / "app" / "assets" / "index-abc123.js").write_text("1", encoding="utf-8")
    (tmp_path / "sound.wav").write_bytes(b"RIFF")
    folder = TestClient(Starlette(routes=[Mount("/", RevalidatingStaticFiles(directory=tmp_path))]))
    bundle = folder.get("/app/assets/index-abc123.js")
    assert bundle.status_code == 200
    assert "cache-control" not in bundle.headers
    assert folder.get("/sound.wav").headers["cache-control"] == "no-cache"


def test_the_folder_of_the_bundles_is_told_by_either_separator():
    """The mount hands the path over with the separators of the system."""
    assert is_hashed("app/assets/index-abc123.js")
    assert is_hashed("app\\assets\\index-abc123.js")
    assert not is_hashed("klaenge/fertig.wav")
    assert not is_hashed("app/index.html")
