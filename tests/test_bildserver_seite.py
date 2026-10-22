"""The picture server page: the default model, the kit of each model, the
machine's memory and devices, and converting only into a smaller copy
(app/bildstandardmodell.py, app/bildmodellwerte.py, app/bildgeraete.py,
app/model_convert.py)."""

from __future__ import annotations

import asyncio
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import bildgeraete, bildmodellwerte, bildwahlen, model_convert
from app.bildrunner import Bildrunner
from app.config import Config
from app.tools import bild_werkzeug
from tests.conftest import Antwort, Bilddienst
from tests.test_bild_bausatz_api import _kopf, hand_start  # noqa: F401 - the fixture is used by name


# --- The default model -------------------------------------------------------


def _ordner(config: Config, tmp_path: Path, *namen: str) -> Path:
    ordner = tmp_path / "bildmodelle"
    config.app.bildmodelle_verzeichnis = str(ordner)
    ordner.mkdir(parents=True, exist_ok=True)
    for name in namen:
        (ordner / name).write_bytes(b"x")
    return ordner


def _standard(client: TestClient, name: str) -> None:
    antwort = client.put("/api/v1/settings/global/bild_standardmodell", json={"wert": name})
    assert antwort.status_code < 300, antwort.text


def test_the_default_model_is_named_while_it_is_in_the_folder(config, client, tmp_path):
    _ordner(config, tmp_path, "a.safetensors", "b.safetensors")
    assert client.get("/api/v1/bild/modelle").json()["standardmodell"] == ""
    _standard(client, "b.safetensors")
    assert client.get("/api/v1/bild/modelle").json()["standardmodell"] == "b.safetensors"
    # Gone from the folder: no model stands chosen, the first one neither.
    _standard(client, "weg.safetensors")
    assert client.get("/api/v1/bild/modelle").json()["standardmodell"] == ""


def test_the_model_list_names_each_file_s_size(config, client, tmp_path):
    """The studio shows a model's size beside its name and reads it from the
    list it reads anyway."""
    folder = _ordner(config, tmp_path)
    (folder / "small.safetensors").write_bytes(b"x" * 7)
    (folder / "large.gguf").write_bytes(b"x" * 4096)
    answer = client.get("/api/v1/bild/modelle").json()
    assert answer["sizes"] == {
        name: (folder / name).stat().st_size for name in answer["modelle"]
    }
    assert answer["sizes"] == {"small.safetensors": 7, "large.gguf": 4096}


def test_the_file_list_of_the_picture_server_page_is_as_it_was(config, client, tmp_path):
    """Silence: the page's own list still names every file with its size and
    the types it can be converted into."""
    folder = _ordner(config, tmp_path)
    (folder / "small.safetensors").write_bytes(b"x" * 7)
    files = client.get("/api/v1/bild/model-files").json()
    assert [(entry["name"], entry["size"]) for entry in files] == [("small.safetensors", 7)]
    assert files[0]["convert_types"] == []


def test_a_request_without_a_scheduler_sends_none_to_sd_cli(config, client, tmp_path, monkeypatch):
    """A drawing that names no scheduler leaves the choice to sd.cpp, as it
    does for the sampler: neither switch stands in the command."""
    _ordner(config, tmp_path, "base.safetensors")
    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))
    commands = []

    def _draw(self, job, target):
        commands.append(self.befehl(job, target))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"PNG")
        return target

    monkeypatch.setattr(Bildrunner, "erzeugen", _draw)
    body = {"prompt": "x", "modell": "base.safetensors"}
    assert client.post("/api/v1/bild", json=body).status_code == 201
    assert "--scheduler" not in commands[-1]
    assert "--sampling-method" not in commands[-1]
    # Silence: a scheduler that is named stands in the command.
    assert client.post("/api/v1/bild", json={**body, "scheduler": "karras"}).status_code == 201
    at = commands[-1].index("--scheduler")
    assert commands[-1][at + 1] == "karras"


def _draw(tmp_path, monkeypatch, service, chat_id=None) -> str:
    monkeypatch.setattr(bild_werkzeug.httpx, "AsyncClient", lambda timeout, headers: service)
    return asyncio.run(bild_werkzeug.ausfuehren(
        {"prompt": "a dog"}, "http://x", tmp_path, "testschluessel", chat_id=chat_id,
    ))


def test_a_run_without_a_chat_draws_with_the_default_not_the_first(tmp_path, monkeypatch):
    service = Bilddienst(modelle=["a.safetensors", "b.safetensors"], standardmodell="b.safetensors")
    _draw(tmp_path, monkeypatch, service)
    assert [body["modell"] for body in service.gezeichnet] == ["b.safetensors"]


def test_without_a_default_model_nothing_is_drawn(tmp_path, monkeypatch):
    service = Bilddienst(modelle=["a.safetensors", "b.safetensors"], standardmodell="")
    text = _draw(tmp_path, monkeypatch, service)
    assert text == bild_werkzeug.NO_DEFAULT_MODEL
    assert service.gezeichnet == []


def test_a_chat_draws_with_the_default_model_whatever_it_stored(tmp_path, monkeypatch):
    """The default model draws for every chat; the model an older chat
    stored for its picture window is not asked for."""
    service = Bilddienst(
        modelle=["a.safetensors", "b.safetensors"], standardmodell="b.safetensors",
        answers={"/settings/resolved/bildfenster": Antwort({"wert": {"modell": "a.safetensors"}})},
    )
    _draw(tmp_path, monkeypatch, service, chat_id="c1")
    assert [body["modell"] for body in service.gezeichnet] == ["b.safetensors"]


# --- The kit of each model ---------------------------------------------------


def test_a_part_chosen_at_the_model_is_drawn_and_started_with(hand_start, client, tmp_path):  # noqa: F811
    """Two Qwen3 4B in the folder: the folder offers the first, the one
    chosen at the model wins — in the start values and at the tile."""
    ordner = tmp_path / "bildmodelle"
    _kopf(ordner / "text_encoders" / "zweite-qwen3-4b.gguf", {"token_embd.weight": [151936, 2560]}, "qwen3")
    vorher = client.get("/api/v1/bild/vorgaben", params={"modell": "z_image_turbo.gguf"}).json()
    assert vorher["parts"]["llm"] == "qwen3-4b.gguf"
    client.patch("/api/v1/settings/global/bildmodellwerte", json={"wert": {
        "z_image_turbo.gguf": {"llm": "zweite-qwen3-4b.gguf"},
    }})
    v = client.get("/api/v1/bild/vorgaben", params={"modell": "z_image_turbo.gguf"}).json()
    assert v["parts"]["llm"] == "zweite-qwen3-4b.gguf"
    antwort, befehl = hand_start("z_image_turbo.gguf", vae="ae.safetensors")
    assert antwort.status_code == 200, antwort.text
    assert befehl[befehl.index("--llm") + 1] == str(ordner / "text_encoders" / "zweite-qwen3-4b.gguf")


def test_a_drawing_takes_the_model_s_kit(hand_start, client, tmp_path, monkeypatch):  # noqa: F811
    """The window and the tool name no parts: the draw route assembles the
    model from its kit, the VAE given at the model included."""
    ordner = tmp_path / "bildmodelle"
    client.patch("/api/v1/settings/global/bildmodellwerte", json={"wert": {
        "z_image_turbo.gguf": {"vae": "ae.safetensors"},
    }})
    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))
    gefangen = {}

    def _erzeugen(self, auftrag, ziel):
        gefangen["auftrag"] = auftrag
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(b"PNG")
        return ziel

    monkeypatch.setattr(Bildrunner, "erzeugen", _erzeugen)
    antwort = client.post("/api/v1/bild", json={"prompt": "x", "modell": "z_image_turbo.gguf"})
    assert antwort.status_code == 201, antwort.text
    auftrag = gefangen["auftrag"]
    assert auftrag.diffusion_model == ordner / "z_image_turbo.gguf"
    assert auftrag.llm == ordner / "text_encoders" / "qwen3-4b.gguf"
    assert auftrag.vae == ordner / "vae" / "ae.safetensors"


# --- Memory and devices ------------------------------------------------------


def test_the_tile_starts_with_the_stored_memory_and_devices(hand_start, client):  # noqa: F811
    antwort, befehl = hand_start("sdxl.safetensors")
    assert antwort.status_code == 200, antwort.text
    # Silence: nothing stored, no switch.
    for flag in ("--max-vram", "--threads", "--split-mode", "--backend", "--offload-to-cpu", "--sage-attn"):
        assert flag not in befehl
    # The start value of flash attention goes out once, and the fixed flag of
    # the earlier builds does not.
    assert befehl.count("--flash-attn") == 1
    assert befehl[befehl.index("--flash-attn") + 1] == "off,diffusion=on"
    assert "--diffusion-fa" not in befehl
    antwort = client.put("/api/v1/settings/global/bildgeraete", json={"wert": {
        "vram_limit": "cuda0=6", "threads": 8, "offload_to_cpu": True,
        "split_mode": "diffusion=row", "backend": "diffusion=cuda0", "switches": {"sage_attn": True},
    }})
    assert antwort.status_code < 300, antwort.text
    antwort, befehl = hand_start("sdxl.safetensors")
    assert antwort.status_code == 200, antwort.text
    assert befehl[befehl.index("--max-vram") + 1] == "cuda0=6"
    assert befehl[befehl.index("--threads") + 1] == "8"
    assert befehl[befehl.index("--split-mode") + 1] == "diffusion=row"
    assert befehl[befehl.index("--backend") + 1] == "diffusion=cuda0"
    assert "--offload-to-cpu" in befehl and "--sage-attn" in befehl


@pytest.mark.parametrize(("roh", "erwartet"), [
    ("6", "6"), ("0", "0"), ("-2", "-2"), ("6.5", "6.5"),
    ("cuda0=6,vulkan0=4", "cuda0=6,vulkan0=4"), (" cuda0 = 6 ", "cuda0=6"),
    ("viel", ""), ("cuda0=", ""), ("6;rm", ""), (6, ""), (None, ""),
])
def test_the_vram_budget_takes_what_the_generator_takes(roh, erwartet):
    assert bildgeraete.vram_pruefen(roh) == erwartet


@pytest.mark.parametrize(("roh", "erwartet"), [
    ("layer", "layer"), ("row", "row"), ("diffusion=row,te=layer", "diffusion=row,te=layer"),
    ("column", ""), ("diffusion=column", ""), ("", ""), (None, ""),
])
def test_the_split_takes_one_mode_or_one_per_module(roh, erwartet):
    assert bildgeraete.split_pruefen(roh) == erwartet


@pytest.mark.parametrize(("roh", "erwartet"), [
    (8, 8), (512, 512), (0, -1), (-3, -1), (True, -1), ("8", -1), (None, -1),
])
def test_threads_are_a_count_or_the_generator_s_own(roh, erwartet):
    assert bildgeraete.threads_pruefen(roh) == erwartet


def test_only_the_memory_block_s_switches_are_kept():
    assert bildgeraete.switches_pruefen(
        {"sage_attn": True, "vae_tiling": True, "timestep_shift": 250, "made_up": 1, "mmap": "ja"},
    ) == {"sage_attn": True, "vae_tiling": True}


# --- Converting only into a smaller copy -------------------------------------


def _gguf(path: Path, ggml_type: int, weights: int = 4096) -> Path:
    """A GGUF header whose one weight is stored in ``ggml_type``."""
    def text(value: str) -> bytes:
        data = value.encode()
        return struct.pack("<Q", len(data)) + data

    header = bytearray(b"GGUF") + struct.pack("<I", 3) + struct.pack("<Q", 1) + struct.pack("<Q", 0)
    header += text("model.diffusion_model.w") + struct.pack("<I", 1) + struct.pack("<Q", weights)
    header += struct.pack("<I", ggml_type) + struct.pack("<Q", 0)
    path.write_bytes(bytes(header))
    return path


def test_a_q8_gguf_is_never_copied_as_large_or_larger(tmp_path):
    types = model_convert.smaller_types(_gguf(tmp_path / "m.q8.gguf", 8))
    for kind in ("q8_0", "f16", "bf16", "f32"):
        assert kind not in types
    assert "q4_K" in types and "q6_K" in types


def test_a_16_bit_safetensors_file_gets_a_quantised_copy(tmp_path):
    """Silence: a full-width file keeps its offer, never a 16-bit one."""
    path = tmp_path / "m.safetensors"
    _kopf(path, {"model.diffusion_model.w": [64, 64]})
    types = model_convert.smaller_types(path)
    assert "q8_0" in types and "q4_K" in types
    assert "f16" not in types and "bf16" not in types and "f32" not in types


def test_a_q2_gguf_has_no_smaller_copy(tmp_path):
    assert model_convert.smaller_types(_gguf(tmp_path / "m.q2.gguf", 10)) == ()


def test_the_route_refuses_a_copy_that_is_not_smaller(config, client, tmp_path, monkeypatch):
    ordner = _ordner(config, tmp_path)
    _gguf(ordner / "m.gguf", 8)
    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))
    antwort = client.post("/api/v1/bild/convert", json={"model": "m.gguf", "weight_type": "q8_0"})
    assert antwort.status_code == 400
    liste = client.get("/api/v1/bild/model-files").json()
    eintrag = next(e for e in liste if e["name"] == "m.gguf")
    assert "q8_0" not in eintrag["convert_types"] and "q4_K" in eintrag["convert_types"]


def test_each_kit_part_is_named_once_and_only_where_it_is_read():
    """SD3 reads CLIP-G among its encoders and names it once; a family that
    does not read it, Flux or Krea 2, has no CLIP-G row."""
    from app import image_families
    from app.api.v1.bild import kit_fields

    for family in image_families.FAMILIES:
        fields = kit_fields(family)
        assert len(fields) == len(set(fields)), family.name
    sd3 = next(f for f in image_families.FAMILIES if f.name == "sd3")
    assert kit_fields(sd3).count("clip_g") == 1
    for name in ("flux", "krea2"):
        family = next(f for f in image_families.FAMILIES if f.name == name)
        assert "clip_g" not in kit_fields(family)


def test_a_distilled_model_opens_on_its_own_start_values(hand_start, client, tmp_path):  # noqa: F811
    """The window and the drawing tool both read /bild/vorgaben: the schnell
    file of Flux opens on 4 steps without guidance, the dev file on the
    family's start, and what the user set for the model lies over either."""
    ordner = tmp_path / "bildmodelle"
    for name in ("flux1-schnell-Q4_K_S.gguf", "flux1-dev-Q4_K_S.gguf"):
        _kopf(ordner / name, {"double_blocks.0.img_attn.qkv.weight": [9216, 3072]}, "flux")
    schnell = client.get("/api/v1/bild/vorgaben", params={"modell": "flux1-schnell-Q4_K_S.gguf"}).json()
    dev = client.get("/api/v1/bild/vorgaben", params={"modell": "flux1-dev-Q4_K_S.gguf"}).json()
    assert (schnell["family"], schnell["schritte"], schnell["guidance"]) == ("flux", 4, None)
    assert (dev["family"], dev["schritte"], dev["guidance"]) == ("flux", 20, 3.5)
    client.patch("/api/v1/settings/global/bildmodellwerte", json={"wert": {
        "flux1-schnell-Q4_K_S.gguf": {"schritte": 9},
    }})
    eigen = client.get("/api/v1/bild/vorgaben", params={"modell": "flux1-schnell-Q4_K_S.gguf"}).json()
    assert (eigen["schritte"], eigen["guidance"]) == (9, None)


def test_a_stopped_conversion_is_no_failure_on_the_page():
    """A conversion stopped on request answers 499, as a stopped picture
    does. The page tells nothing then and the file's row stands as before
    the start; every other answer that is no success stays a failure."""
    source = (Path(__file__).resolve().parent.parent / "frontend/src/teile/ImageConvert.svelte").read_text(
        encoding="utf-8")
    start = source.split("async function runConversion(call) {", 1)[1].split("\n  }\n", 1)[0]
    caught = start.split("} catch (error) {", 1)[1]
    assert "if (error.status !== 499) melde(String(error.message || error), 'fehler')" in caught
    # The copy asked for stays chosen; only the running ends.
    assert "converting = null" not in caught and "running = false" in caught
    # The silence check: the block's other job, the switch, tells every failure.
    other = source.split("async function switchImatrix(on) {", 1)[1].split("\n  }\n", 1)[0]
    assert "melde(String(error.message || error), 'fehler')" in other and "499" not in other


def test_a_change_the_service_did_not_take_is_not_shown_as_stored():
    """A field of "Memory & devices" goes to the service a moment after it
    was changed. Where that write fails, the page says so and the field
    shows what is stored again — not the value nobody stored."""
    source = (Path(__file__).resolve().parent.parent / "frontend/src/teile/BildGeraete.svelte").read_text(
        encoding="utf-8")
    write = source.split("async function store(write) {", 1)[1].split("\n  }\n", 1)[0]
    caught = write.split("} catch (fehler) {", 1)[1].split("} finally {", 1)[0]
    assert "melde(String(fehler.message || fehler), 'fehler')" in caught
    # Only the last write puts back: a later one carries the same fields.
    assert "if (write === writes) showStored(geaendert)" in caught
    scheduled = source.split("clearTimeout(zeit)\n    ausstehend = true\n", 1)[1]
    assert scheduled.startswith(
        "    const write = ++writes\n    waiting = write\n    zeit = setTimeout(() => {")
    back = source.split("function showStored(changed) {", 1)[1].split("\n  }\n", 1)[0]
    # Each field of the change, each switch by its key; a limit being typed waits for its field to be left.
    assert (
        "} else if (!(name === 'vram_limit' && vramFokus) && !(name === 'zeitgrenze' && zeitFokus)) {"
    ) in back
    assert "w[name] = gesendet[name]" in back
    assert "if (key in stored) back[key] = stored[key]\n          else delete back[key]" in back
    assert "if (name === 'split_mode') showSplit(gesendet.split_mode)" in back
    # The silence check: a write that came through shows nothing again.
    taken = write.split("} catch (fehler) {", 1)[0]
    assert "showStored" not in taken and "gesendet = { ...gesendet" in taken


def test_the_page_s_writes_go_out_one_after_another():
    """Two changes of "Memory & devices" shortly after one another are two
    writes. The second goes out once the first has its answer and carries
    what differs from what the service holds by then, so no earlier answer
    comes in after a later one: after any run of writes the page shows what
    the service holds."""
    source = (Path(__file__).resolve().parent.parent / "frontend/src/teile/BildGeraete.svelte").read_text(
        encoding="utf-8")
    assert "  let line = Promise.resolve()\n" in source
    scheduled = source.split("zeit = setTimeout(() => {", 1)[1].split("}, 350)", 1)[0]
    assert scheduled.strip() == "waiting = 0\n      line = line.then(() => store(write))"
    write = source.split("async function store(write) {", 1)[1].split("\n  }\n", 1)[0]
    # What goes out is read when the write's turn has come, not when it was asked for.
    assert write.lstrip().startswith(
        "let geaendert = {}\n    try {\n      const jetzt = $state.snapshot(w)\n"
        "      geaendert = changedSince(jetzt)\n")
    sent = write.index("await api.einstellungMischen('global', SCHLUESSEL, geaendert)")
    assert write.index("if (!Object.keys(geaendert).length) return") < sent
    # The line never breaks: whatever fails is caught inside the write's own turn.
    assert sent < write.index("} catch (fehler) {") < write.index("} finally {")
    # A field set back while its write was under way goes out next, unless a
    # later write was asked for anyway.
    undone = write.split("const undone = Object.keys(geaendert).some(", 1)[1].split("} catch (fehler) {", 1)[0]
    assert "name !== 'vram_limit' && name !== 'zeitgrenze'" in undone
    assert "JSON.stringify(w[name]) !== JSON.stringify(jetzt[name]))" in undone
    assert "if (undone && write === writes) await store(write)" in undone
    assert sent < write.index("const undone = ")
    # The silence check: a single write stores and shows as before — what
    # was sent counts as held, and the page waits the same moment for it.
    assert "gesendet = { ...gesendet, ...Object.fromEntries(Object.keys(geaendert).map((n) => [n, jetzt[n]])) }" in write
    effect = source.split("  $effect(() => {\n    const jetzt = w ? $state.snapshot(w) : null", 1)[1].split(
        "return () => clearTimeout(zeit)", 1)[0]
    assert "if (!Object.keys(changedSince(jetzt)).length) return" in effect


def test_the_time_limit_is_one_field_that_may_stay_empty_and_goes_out_as_null():
    """Under "Threads" stands the time limit, in seconds, empty from the
    factory. It is a plain input, not a number field: a number field makes
    an empty one its minimum, and empty means no limit. Whatever is typed
    is only digits; empty goes out as null; a value the service did not keep
    shows as empty again once the field is left."""
    source = (Path(__file__).resolve().parent.parent / "frontend/src/teile/BildGeraete.svelte").read_text(
        encoding="utf-8")
    markup = source.split("</script>", 1)[1].split("<style>", 1)[0]
    row = markup.split("<span class=\"name\">{t('mcp.zeitgrenze')}</span>", 1)[1].split("</div>", 1)[0]

    assert markup.index("{t('bild.threads')}") < markup.index("{t('mcp.zeitgrenze')}") < markup.index(
        "{t('bild.split_mode')}")
    # Without a value the field shows a dash, and is empty while it is typed in.
    assert "aria-label={t('mcp.zeitgrenze')}" in row
    assert "value={zeitFokus || w.zeitgrenze != null ? (w.zeitgrenze ?? '') : '-'}" in row
    assert "<span class=\"still\">{t('mcp.zeitgrenze_einheit')}</span>" in row
    assert "Zahlenfeld" not in row
    assert "e.currentTarget.value.replace(/\\D/g, '')" in row
    assert "w.zeitgrenze = ziffern ? Number(ziffern) : null" in row
    assert "if (!ausstehend) w.zeitgrenze = zeitGespeichert" in row
    # Loaded as a number or empty; stored as the service answers it.
    assert (
        "case 'zeitgrenze': return Number.isInteger(v.zeitgrenze) && v.zeitgrenze > 0 ? v.zeitgrenze : null"
    ) in source
    # What the write left in the service is taken over for every field, the
    # limit among them — except while its field is under the fingers.
    adopted = source.split("function adopt(geaendert, jetzt, stored) {", 1)[1].split("\n  }\n", 1)[0]
    assert "zeitgrenze: zeitFokus" in adopted
    assert "if (name === 'zeitgrenze') zeitGespeichert = held" in adopted
    assert "const held = asHeld(name, stored)" in adopted
    # Both labels already stand in the catalogue, in both languages.
    import json

    for sprache in ("de", "en"):
        katalog = json.loads(
            (Path(__file__).resolve().parent.parent / "app/locales" / f"{sprache}.json").read_text(encoding="utf-8"))
        assert katalog["mcp"]["zeitgrenze"] and katalog["mcp"]["zeitgrenze_einheit"]


# --- Width and height of a model ----------------------------------------------


def test_the_model_page_s_edge_sliders_end_at_2048_and_its_fields_at_the_service_s_end():
    """The sliders for width and height run from 256 to 2048 on the grid,
    as the studio's do; the number field beside each ends where the service
    ends, not where the slider does."""
    source = (Path(__file__).resolve().parent.parent / "frontend/src/teile/Bildmodellwerte.svelte").read_text(
        encoding="utf-8")
    assert "const SLIDER_MAX = 2048" in source
    assert "{ length: (SLIDER_MAX - SLIDER_MIN) / EDGE_GRID + 1 }, (_, i) => SLIDER_MIN + i * EDGE_GRID," in source
    assert "import { EDGE_GRID, EDGE_MAX, EDGE_MIN } from '../lib/studio.svelte.js'" in source
    for edge in ("breite", "hoehe"):
        assert f"<Schieberegler bind:wert={{w.{edge}}} stufen={{KANTEN}}" in source
        assert (
            f"<Zahlenfeld bind:wert={{w.{edge}}} min={{EDGE_MIN}} max={{EDGE_MAX}} "
            "schritt={EDGE_GRID} grid={EDGE_GRID} ganzzahlig />"
        ) in source
    # The limits the fields end at are the service's own.
    limits = (Path(__file__).resolve().parent.parent / "frontend/src/lib/studio.svelte.js").read_text(
        encoding="utf-8")
    assert f"export const EDGE_MIN = {bildwahlen.MIN_KANTE}\n" in limits
    assert f"export const EDGE_MAX = {bildwahlen.MAX_KANTE}\n" in limits
    # The silence check: the sliders start at 256 and move in steps of 64.
    assert "const SLIDER_MIN = 256" in source
    assert f"export const EDGE_GRID = {bildwahlen.RASTER}\n" in limits and bildwahlen.RASTER == 64


def test_an_edge_of_a_model_past_the_service_s_end_is_brought_back(
    config: Config, client: TestClient, tmp_path: Path
):
    """The silence check: what the page can now type past 2048 is kept as
    typed up to the service's end, and anything past that end is brought
    back to it, on the grid, as before."""
    assert bildmodellwerte.pruefen({"a.gguf": {"breite": 2048, "hoehe": 2050}}) == {
        "a.gguf": {"breite": 2048, "hoehe": 2112},
    }
    assert bildmodellwerte.pruefen({"a.gguf": {"breite": 5000, "hoehe": 100000}}) == {
        "a.gguf": {"breite": bildwahlen.MAX_KANTE, "hoehe": bildwahlen.MAX_KANTE},
    }
    folder = tmp_path / "bildmodelle"
    folder.mkdir()
    config.app.bildmodelle_verzeichnis = str(folder)
    (folder / "a.safetensors").write_bytes(b"x")
    stored = client.patch(
        "/api/v1/settings/global/bildmodellwerte",
        json={"wert": {"a.safetensors": {"breite": 2048, "hoehe": 5000}}},
    )
    assert stored.status_code == 200, stored.text
    values = client.get("/api/v1/bild/vorgaben", params={"modell": "a.safetensors"}).json()
    assert (values["breite"], values["hoehe"]) == (2048, bildwahlen.MAX_KANTE)
