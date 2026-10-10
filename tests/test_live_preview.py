"""The live preview: sd-cli is told where to write it and how often, and
the window can fetch it while the picture is drawn."""

from __future__ import annotations

from pathlib import Path

from app import bildrunner
from app.bildrunner import Auftrag, Bildrunner


def _befehl(tmp_path: Path, monkeypatch, **fields) -> list[str]:
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/somewhere/sd-cli")
    runner = Bildrunner(tmp_path)
    return runner.befehl(Auftrag(modell=tmp_path / "m.gguf", prompt="x", **fields), tmp_path / "a.png")


def test_preview_carries_path_and_rhythm(tmp_path, monkeypatch):
    befehl = _befehl(tmp_path, monkeypatch, live_preview="proj", preview_interval=2,
                     preview_noisy=True)
    assert befehl[befehl.index("--preview") + 1] == "proj"
    path = Path(befehl[befehl.index("--preview-path") + 1])
    assert path.parent == tmp_path and path.suffix == ".png"
    assert befehl[befehl.index("--preview-interval") + 1] == "2"
    assert "--preview-noisy" in befehl


def test_taesd_decodes_the_preview_only(tmp_path, monkeypatch):
    taesd = tmp_path / "taesd.safetensors"
    befehl = _befehl(tmp_path, monkeypatch, live_preview="tae", taesd=taesd)
    assert befehl[befehl.index("--taesd") + 1] == str(taesd)
    assert "--taesd-preview-only" in befehl


def test_silence_without_preview_nothing_is_added(tmp_path, monkeypatch):
    befehl = _befehl(tmp_path, monkeypatch, preview_interval=2, preview_noisy=True)
    for flag in ("--preview", "--preview-path", "--preview-interval", "--preview-noisy", "--taesd"):
        assert flag not in befehl


def test_progress_names_the_newest_preview(tmp_path):
    runner = Bildrunner(tmp_path)
    runner.reservieren()
    try:
        runner._fortschritt = {"anteil": 0.5, "schritt": 5, "gesamt": 10}
        assert runner.fortschritt()["preview"] == 0
        assert runner.preview() is None
        runner.preview_path.write_bytes(b"PNG")
        assert runner.fortschritt()["preview"] > 0
        assert runner.preview() == runner.preview_path
    finally:
        runner.freigeben()
    assert runner.preview() is None


def test_a_half_written_preview_is_not_sent(tmp_path):
    from fastapi import HTTPException

    from app.api.v1 import bild as bildapi

    runner = Bildrunner(tmp_path)

    class Request:
        class app:
            class state:
                bildrunner = runner

    runner.reservieren()
    try:
        runner.preview_path.write_bytes(b"\x89PNG\r\n\x1a\nhalf")
        try:
            bildapi.live_preview_picture(Request, "en")
            raise AssertionError("a half file was sent")
        except HTTPException as error:
            assert error.status_code == 404
        runner.preview_path.write_bytes(b"\x89PNG\r\n\x1a\nwhole\x00\x00\x00\x00IEND\xaeB`\x82")
        assert bildapi.live_preview_picture(Request, "en").status_code == 200
    finally:
        runner.freigeben()


SOURCE = Path(__file__).resolve().parent.parent / "frontend" / "src"


def _function(source: str, head: str) -> str:
    return source.split(head, 1)[1].split("\n}\n", 1)[0]


def test_the_studio_watches_the_live_preview():
    """The preview is only fetched while a surface watches it. The studio's
    generation area and the drawing tile of its row of pictures both show
    it, so both watch — while a picture of the open chat is drawing, and
    keyed by that picture, so a line rebuilt around it does not end the
    watch and start it over."""
    canvas = (SOURCE / "teile" / "StudioCanvas.svelte").read_text(encoding="utf-8")
    rail = (SOURCE / "teile" / "StudioGallery.svelte").read_text(encoding="utf-8")
    for component in (canvas, rail):
        assert "const runningId = $derived(laufend?.id ?? null)" in component
        watch = component.split("const runningId = $derived(laufend?.id ?? null)", 1)[1].split("\n  })\n", 1)[0]
        assert "if (runningId === null) return" in watch
        assert "const stopProgress = watchPictureProgress()" in watch
        assert "const stopPreview = watchPicturePreview(runningId)" in watch
        assert "if (laufend) return watch" not in component
    assert '{#if pictureProgress.previewUrl}<img class="preview" src={pictureProgress.previewUrl} alt="" />{/if}' in canvas
    assert '{#if pictureProgress.previewUrl}<img src={pictureProgress.previewUrl} alt="" />{/if}' in rail
    # Shown inside what stands only while this chat's picture is drawing.
    area = canvas.split("{#if laufend}", 1)[1].split("{/if}\n\n", 1)[0]
    assert 'class="preview"' in area
    # The progress has the empty area to itself: the picture plaque, which
    # stands in the same place, is there only while no picture of this chat
    # is drawn or waits in the line — waiting too, or the plaque would show
    # up between two pictures of one run.
    assert "{#if !bildUrl && !inLine}" in canvas.split('<div class="plaque"', 1)[0].rsplit("{/if}", 1)[1]
    assert "const inLine = $derived(zustand.pictureQueue.some((w) => w.chat_id === chatanzeige.chatId))" in canvas
    # The working frame in the chat shows none and watches none.
    frame = (SOURCE / "teile" / "Bildfuellung.svelte").read_text(encoding="utf-8")
    assert "watchPicturePreview" not in frame and "previewUrl" not in frame


def test_the_preview_is_fetched_once_and_never_held_back():
    """One fetch for every surface, and only for a preview that is newer
    than the one on screen. A fetch no answer has begun for when a newer
    preview is reported is given up for the newer one; an answer that has
    begun is read to its end and shown, and the newest stamp fetched after
    it. The same stamp is never asked for twice. The preview stays while
    the same picture is drawn, whoever stops watching, and goes when the
    counter reports none."""
    progress = (SOURCE / "lib" / "pictureProgress.svelte.js").read_text(encoding="utf-8")
    fetch = _function(progress, "function fetchPreview(stamp) {")
    assert "if (!previewWatchers || stamp <= shownStamp) return" in fetch
    assert fetch.index("if (stamp <= previewFetch.stamp || previewFetch.answering) return") < fetch.index(
        "previewFetch.abort.abort()")
    assert "const fetching = { stamp, abort: new AbortController(), answering: false }" in fetch
    # The answer has begun once the fetch hands it over; its bytes are read after.
    assert fetch.index("api.previewAnswer(fetching.abort.signal)") < fetch.index(
        "fetching.answering = true") < fetch.index("return answer.blob()")
    assert "if (previewFetch !== fetching) return" in fetch
    # After an answer, a stamp reported meanwhile is fetched — a newer one only.
    assert "if (pictureProgress.preview > stamp) fetchPreview(pictureProgress.preview)" in fetch.split(".finally(", 1)[1]
    api = (SOURCE / "lib" / "api.js").read_text(encoding="utf-8")
    assert "previewAnswer: (signal) => rufRoh('/bild/preview', signal ? { signal } : {})," in api
    watch = _function(progress, "export function watchPicturePreview(picture) {")
    stopping = watch.split("return () => {", 1)[1]
    assert "previewWatchers -= 1" in stopping and "clearPreview" not in stopping
    # Another picture is told by the name its watchers give it: its watch
    # clears what stands at once, the same picture's watch keeps it.
    assert watch.index("if (picture !== previewOf) {") < watch.index("clearPreview()") < watch.index(
        "pictureProgress.preview = 0") < watch.index("previewOf = picture") < watch.index(
        "} else {") < watch.index("fetchPreview(untrack(")
    # The silence check: without a stamp nothing is fetched, and what
    # stands is cleared — a picture drawn without a live preview, the next
    # picture, the end of the watch.
    counter = _function(progress, "function set(running, share, step, total, preview = 0) {")
    assert "if (preview) fetchPreview(preview)" in counter
    assert "else if (shownStamp || previewFetch || pictureProgress.previewUrl) clearPreview()" in counter
    ended = _function(progress, "export function watchPictureProgress() {")
    assert "set(false, 0, 0, 0)" in ended
