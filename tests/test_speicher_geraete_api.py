"""The picture window's Memory & devices fields, on their way
from a request into the Auftrag that reaches the generator — RNG, weight
type, threads, VRAM limit, offload to RAM.

RNG always carries one of its two values, the same way sampler/scheduler
do; the rest default to "leave sd-cli's own behaviour alone" (see
app/bildrunner.py's own comment on the fields).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.bildrunner import Auftrag, Bildrunner
from app.config import Config


@pytest.fixture
def wunsch_senden(config: Config, client: TestClient, monkeypatch, tmp_path: Path):
    """Sends a POST /bild and returns the Auftrag that would have reached
    the generator — Bildrunner.erzeugen is mocked so no real sd-cli is
    needed."""
    config.app.bildmodelle_verzeichnis = str(tmp_path / "bildmodelle")
    bildordner = tmp_path / "bildmodelle"
    bildordner.mkdir(parents=True)
    (bildordner / "base.safetensors").write_bytes(b"x")

    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))

    aufgerufen: dict = {}

    def _erzeugen(self, auftrag: Auftrag, ziel):
        aufgerufen["auftrag"] = auftrag
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(b"PNG")
        return ziel

    monkeypatch.setattr(Bildrunner, "erzeugen", _erzeugen)

    def _senden(**felder):
        body = {"prompt": "x", "modell": "base.safetensors", **felder}
        antwort = client.post("/api/v1/bild", json=body)
        assert antwort.status_code == 201, antwort.text
        return aufgerufen["auftrag"]

    return _senden


def _geraete(client: TestClient, **werte) -> None:
    antwort = client.put("/api/v1/settings/global/bildgeraete", json={"wert": werte})
    assert antwort.status_code < 300, antwort.text


def test_vorgaben_lassen_den_auftrag_wie_heute(wunsch_senden):
    """A request on a machine whose memory and devices were never set
    builds exactly today's Auftrag — no flag appears on the command line by
    accident."""
    auftrag = wunsch_senden()
    assert auftrag.rng == "cuda"
    assert auftrag.weight_type == ""
    assert auftrag.threads == -1
    assert auftrag.vram_limit == ""
    assert auftrag.offload_to_cpu is False
    assert auftrag.split_mode == ""
    assert auftrag.backend == ""


def test_die_werte_kommen_aus_dem_bildserver(wunsch_senden, client: TestClient):
    """Memory and devices are the picture server's, set once for every
    chat (app/bildgeraete.py): every picture is drawn with them."""
    _geraete(
        client, threads=8, vram_limit="cuda0=6,vulkan0=4", offload_to_cpu=True,
        split_mode="diffusion=row,te=layer", backend="clip=cpu,vae=cuda0,diffusion=vulkan0",
    )
    auftrag = wunsch_senden(rng="cpu", weight_type="q8_0")
    assert auftrag.rng == "cpu"
    assert auftrag.weight_type == "q8_0"
    assert auftrag.threads == 8
    assert auftrag.vram_limit == "cuda0=6,vulkan0=4"
    assert auftrag.offload_to_cpu is True
    assert auftrag.split_mode == "diffusion=row,te=layer"
    assert auftrag.backend == "clip=cpu,vae=cuda0,diffusion=vulkan0"


def test_ein_bild_schickt_keinen_speicher_mehr(client: TestClient):
    """A picture carries no memory values of its own: the request names
    them nowhere, and one that does is refused instead of half heard."""
    antwort = client.post(
        "/api/v1/bild",
        json={"prompt": "x", "modell": "base.safetensors", "threads": 4},
    )
    assert antwort.status_code == 422


def test_die_speicherschalter_kommen_aus_dem_bildserver(wunsch_senden, client: TestClient):
    """The memory block's switches are the machine's too: a picture's own
    copy of one is not heard, the stored one is."""
    _geraete(client, switches={"vae_tiling": True, "fa": True})
    auftrag = wunsch_senden(switches={"fa": False, "mmap": True})
    assert auftrag.switches.get("vae_tiling") is True
    assert auftrag.switches.get("fa") is True
    assert "mmap" not in auftrag.switches


def test_unbekannte_werte_fallen_auf_die_vorgabe_zurueck(wunsch_senden):
    """Same shape as sampler/scheduler/lora_apply_mode: an unknown name is
    a value to bring into range, never passed on to sd-cli unchecked."""
    auftrag = wunsch_senden(rng="etwas-erfundenes", weight_type="q99_zzz")
    assert auftrag.rng == "cuda"
    assert auftrag.weight_type == ""


def _patch(client: TestClient, **werte):
    return client.patch("/api/v1/settings/global/bildgeraete", json={"wert": werte})


def _stored(client: TestClient) -> dict:
    return client.get("/api/v1/settings/global/bildgeraete").json()["wert"] or {}


def test_a_memory_switch_turned_off_is_no_longer_kept(wunsch_senden, client: TestClient):
    """The page sends what changed: a switch turned off arrives as false.
    Off is not a value the generator reads, so the switch is taken out of
    the stored set — the write is answered, not refused, also for the last
    switch that was on — and the next picture is drawn without it."""
    assert _patch(client, switches={"fa": True}).status_code == 200
    assert _stored(client)["switches"] == {"fa": True}
    assert wunsch_senden().switches.get("fa") is True

    antwort = _patch(client, switches={"fa": False})
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["wert"]["switches"] == {}
    assert _stored(client)["switches"] == {}
    assert "fa" not in wunsch_senden().switches

    # On again, as before.
    assert _patch(client, switches={"fa": True}).status_code == 200
    assert _stored(client)["switches"] == {"fa": True}


def test_turning_one_switch_off_leaves_the_rest_alone(client: TestClient):
    """The silence check: only the switch sent as off goes. A second switch,
    a switch with a value and the other fields of the set stay as they
    are; a cleared value goes like a switch turned off; a key the table
    does not know is still not kept."""
    _geraete(client, vram_limit="6", threads=8, offload_to_cpu=True,
             switches={"fa": True, "mmap": True, "linear_scale": 0.5})

    assert _patch(client, switches={"fa": False}).status_code == 200
    stand = _stored(client)
    assert stand["switches"] == {"mmap": True, "linear_scale": 0.5}
    assert (stand["vram_limit"], stand["threads"], stand["offload_to_cpu"]) == ("6", 8, True)

    assert _patch(client, switches={"linear_scale": ""}).status_code == 200
    assert _stored(client)["switches"] == {"mmap": True}

    assert _patch(client, switches={"made_up": True}).status_code == 200
    assert _stored(client)["switches"] == {"mmap": True}

    # A field beside the switches is written as before and takes none away.
    assert _patch(client, threads=4).status_code == 200
    stand = _stored(client)
    assert stand["threads"] == 4 and stand["switches"] == {"mmap": True}


def test_two_windows_do_not_undo_each_other_s_switches(client: TestClient):
    """Each window sends the switches it changed, by key: one that still
    shows a switch as on, which the other has turned off meanwhile, does
    not bring it back by setting another."""
    assert _patch(client, switches={"fa": True}).status_code == 200
    # Window one turns it off; window two, opened before, sets another.
    assert _patch(client, switches={"fa": False}).status_code == 200
    assert _patch(client, switches={"mmap": True}).status_code == 200
    assert _stored(client)["switches"] == {"mmap": True}

    page = (Path(__file__).resolve().parent.parent / "frontend" / "src" / "teile" / "BildGeraete.svelte").read_text(
        encoding="utf-8")
    sent = page.split("if (name === 'switches') {", 1)[1].split("} else {", 1)[0]
    assert "const before = gesendet.switches ?? {}" in sent
    assert "JSON.stringify(value) !== JSON.stringify(before[key])" in sent


def test_only_a_set_named_for_it_is_stored_as_the_check_leaves_it(client: TestClient):
    """Everywhere else a partial write still merges: a sent set that the
    check empties is refused and the stored one stays."""
    from app.api.v1.einstellungen import AS_KEPT
    from app.bildgeraete import SCHLUESSEL

    assert AS_KEPT == {SCHLUESSEL: frozenset({"switches"})}
    _geraete(client, switches={"fa": True})
    # Not a set under that key: judged like every other value, nothing is cleared.
    assert _patch(client, switches=None).status_code == 400
    assert _stored(client)["switches"] == {"fa": True}
