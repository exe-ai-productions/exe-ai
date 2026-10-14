"""What the picture window was left standing at, per conversation.

Switching to another chat and back used to hand back an empty window — the
sentence, the negative and the seed plan were simply gone. The round trip
through the real route is what matters: without an entry in PRUEFER the
window would appear to save and be empty again on the next open.
"""

from __future__ import annotations

import re
from pathlib import Path

from app import bildfensterwahl


def test_alles_kommt_durch():
    assert bildfensterwahl.wahl_pruefen(
        {
            "prompt": "ein hund am strand",
            "negativ": "unscharf",
            "cfg": 9,
            "bilder_je_lauf": 4,
            "seed": "12345",
            "seed_modus": "plus",
        }
    ) == {
        "prompt": "ein hund am strand",
        "negativ": "unscharf",
        "cfg": 9,
        "bilder_je_lauf": 4,
        "seed": "12345",
        "seed_modus": "plus",
    }


def test_der_prompt_bleibt_ganz():
    """The draw route and sd.cpp take a prompt of any length, so the stored
    one is kept whole."""
    lang = bildfensterwahl.wahl_pruefen({"prompt": "x" * 5000, "negativ": "y" * 3000})
    assert len(lang["prompt"]) == 5000
    assert len(lang["negativ"]) == 3000


def test_die_regler_bleiben_in_den_grenzen_von_sdcpp():
    """No upper limit, as sd.cpp sets none; nothing below what it takes."""
    geklemmt = bildfensterwahl.wahl_pruefen({"cfg": 99, "bilder_je_lauf": 99})
    assert geklemmt == {"cfg": 99, "bilder_je_lauf": 99}
    geklemmt = bildfensterwahl.wahl_pruefen({"cfg": -5, "bilder_je_lauf": 0})
    assert geklemmt == {"cfg": 0, "bilder_je_lauf": 1}


def test_der_seed_ist_leer_oder_eine_ganze_zahl():
    """Only a whole number ever reaches the generator — anything else would
    be silently ignored there and look like the seed had been taken."""
    assert bildfensterwahl.wahl_pruefen({"seed": ""}) == {"seed": ""}
    assert bildfensterwahl.wahl_pruefen({"seed": "42"}) == {"seed": "42"}
    assert bildfensterwahl.wahl_pruefen({"seed": "12x"}) is None
    assert bildfensterwahl.wahl_pruefen({"seed": "-4"}) is None
    assert bildfensterwahl.wahl_pruefen({"seed": 42}) is None


def test_nur_die_vier_seed_plaene():
    for modus in ("zufall", "fest", "plus", "minus"):
        assert bildfensterwahl.wahl_pruefen({"seed_modus": modus}) == {"seed_modus": modus}
    assert bildfensterwahl.wahl_pruefen({"seed_modus": "rueckwaerts"}) is None


def test_muell_faellt_raus():
    assert bildfensterwahl.wahl_pruefen("ein hund") is None
    assert bildfensterwahl.wahl_pruefen({"offen": "ja"}) is None
    # A boolean is not a number — otherwise True would land as 1.
    assert bildfensterwahl.wahl_pruefen({"cfg": True}) is None
    assert bildfensterwahl.wahl_pruefen({}) is None


def test_no_built_in_value_stands_behind_a_stored_one():
    """A value a chat does not store is the start value of its model
    (app/image_families.py): the service lays no CFG of its own, nor any
    other value, behind what is stored. What is stored comes back as it
    is, and nothing stored is nothing."""
    assert bildfensterwahl.wahl_pruefen(None) is None
    assert bildfensterwahl.wahl_pruefen({"prompt": "a dog"}) == {"prompt": "a dog"}
    assert not hasattr(bildfensterwahl, "VORGABE")
    assert not hasattr(bildfensterwahl, "aufgeloest")


def test_jeder_chat_haelt_seinen_eigenen_stand(client):
    client.put(
        "/api/v1/settings/chat:c1/bildfenster",
        json={"wert": {"prompt": "ein hund", "cfg": 3}},
    )
    client.put(
        "/api/v1/settings/chat:c2/bildfenster",
        json={"wert": {"prompt": "eine katze"}},
    )

    eins = client.get("/api/v1/settings/resolved/bildfenster?chat=c1").json()
    assert eins["wert"] == {"prompt": "ein hund", "cfg": 3}
    assert eins["herkunft"]["prompt"] == "chat:c1"

    zwei = client.get("/api/v1/settings/resolved/bildfenster?chat=c2").json()
    assert zwei["wert"] == {"prompt": "eine katze"}


def test_the_open_flag_of_the_window_that_is_gone_is_not_kept(client):
    """The picture window is gone, and with it whether it stood open: the
    flag is no value of a chat any more and is dropped where it still
    comes in. What a chat does set beside it is kept."""
    assert "offen" not in bildfensterwahl.FELDER
    assert bildfensterwahl.wahl_pruefen({"offen": True}) is None
    client.put("/api/v1/settings/chat:c1/bildfenster", json={"wert": {"offen": True, "cfg": 3}})
    gelesen = client.get("/api/v1/settings/resolved/bildfenster?chat=c1").json()
    assert gelesen["wert"] == {"cfg": 3}


def test_a_set_cfg_seed_and_count_are_kept_and_read(client):
    """Silence: the values a chat does set — a CFG, a seed with its plan,
    how many pictures a run draws — are stored and read as before."""
    eigen = {"cfg": 3, "seed": "42", "seed_modus": "fest", "bilder_je_lauf": 4}
    client.put("/api/v1/settings/chat:c2/bildfenster", json={"wert": eigen})
    assert client.get("/api/v1/settings/resolved/bildfenster?chat=c2").json()["wert"] == eigen


# --- Every value of the four tabs, per chat ---------------------------------

# One value per field in the shape the window holds it — what chat A was
# left standing at.
CHAT_A = {
    "prompt": "ein hund am strand",
    "stil": "Foto",
    "breite": 1024,
    "hoehe": 768,
    "schritte": 28,
    "sampler": "dpm++2m",
    "scheduler": "karras",
    "stapel": [{"name": "detail.safetensors", "staerke": 0.6}],
    "lora_modus": "auto",
    "modell": "sdxl-basis.safetensors",
    "vae_format": "auto",
    "clip_skip": "2",
    "rng": "cpu",
    "weight_type": "f16",
    "prediction": "v",
    "familie": "flux",
    "guidance": 3.5,
    "startbild": "a" * 32 + ".png",
    "staerke": 0.6,
    "maske": "b" * 32 + ".png",
    "pm_klasse": "man",
    "ad_modell": "face_yolov8n.pt",
    "ad_stapel": [{"name": "gesicht.safetensors", "staerke": 0.8}],
    "ad_prompt": "a detailed face",
    "ad_negativ": "blurry",
    "ad_confidence": 0.4,
    "pulid_weights": "pulid.safetensors",
    "pulid_id_embedding": "gesicht.pulidembd",
    "video_frames": 33,
    "fps": 16,
    "end_bild": "b" * 32 + ".png",
    "model_args": "chroma_use_dit_mask=false",
    "ref_bilder": ["d" * 32 + ".png", "e" * 32 + ".png"],
    "img_cfg": 2.5,
    "ref_image_args": "preset=qwen",
    "increase_ref_index": True,
    "pulid_id_weight": 1.2,
    "control_net": "canny.safetensors",
    "control_image": "d" * 32 + ".png",
    "control_strength": 0.7,
    "canny": True,
    "hires_wahl": "1.5",
    "hires_steps": 12,
    "hires_denoise": 0.45,
    "hires_upscaler": "RealESRGAN",
    "upscale_model": "RealESRGAN_x4.pth",
    "hires_breite": "",
    "hires_hoehe": 1536,
    "slg_scale": 2.5,
    "skip_layers": "7,8,9",
    "skip_layer_start": 0.01,
    "skip_layer_end": 0.2,
    "live_preview": "proj",
    "eta": "",
    "flow_shift": 3,
    "sigmas": "14.6,7.0,0.0",
    "extra_sample_args": "a=1",
    "switches": {"timestep_shift": 250, "circular": True},
    "preview_interval": 2,
    "preview_noisy": True,
    "taesd": "taesd.safetensors",
}

# The five fields of "Memory & devices": the machine, the same for every chat.
SPEICHER_UND_GERAETE = {
    "vramLimit": 8, "offloadToCpu": True, "threads": 4, "splitMode": "row", "backend": "cpu",
}


def test_jeder_wert_der_vier_reiter_kommt_durch():
    # The run's own values beside the prompt have a test each above.
    of_the_run = {"negativ", "cfg", "bilder_je_lauf", "seed", "seed_modus"}
    assert set(CHAT_A) | of_the_run == set(bildfensterwahl.FELDER)
    assert not set(CHAT_A) & of_the_run
    assert bildfensterwahl.wahl_pruefen(CHAT_A) == CHAT_A


def test_speicher_und_geraete_bleiben_fuer_alle_chats_gleich():
    """The silence check: those five are not stored per chat at all, nor the
    memory block's switches, nor the model's kit — the picture server keeps
    them for every chat."""
    assert bildfensterwahl.wahl_pruefen(SPEICHER_UND_GERAETE) is None
    for name in SPEICHER_UND_GERAETE:
        assert name not in bildfensterwahl.FELDER
    assert bildfensterwahl.wahl_pruefen({"switches": {"cache_mode": "easycache"}}) == {"switches": {}}
    for name in ("vae", "diffusion_modell", "t5xxl", "clip_l", "llm", "high_noise_modell"):
        assert name not in bildfensterwahl.FELDER


def test_die_maske_gilt_nur_mit_ihrem_startbild():
    ohne = bildfensterwahl.wahl_pruefen({"maske": "b" * 32 + ".png", "breite": 512})
    assert ohne == {"breite": 512}


def test_falsche_formen_fallen_raus():
    assert bildfensterwahl.wahl_pruefen({"breite": float("nan")}) is None
    assert bildfensterwahl.wahl_pruefen({"canny": "ja"}) is None
    assert bildfensterwahl.wahl_pruefen({"modell": 3}) is None
    assert bildfensterwahl.wahl_pruefen({"unbekannt": "x"}) is None
    gestapelt = bildfensterwahl.wahl_pruefen(
        {"stapel": [{"name": "a", "staerke": 0.5}, {"name": 1}, "b", {"name": "c", "staerke": True}]}
    )
    assert gestapelt == {"stapel": [{"name": "a", "staerke": 0.5}]}


def test_ein_neuer_chat_hat_keine_eigenen_masse():
    """Without values of its own a chat starts from its model's class — the
    window reads that off the measures being absent."""
    assert bildfensterwahl.wahl_pruefen({"prompt": "a dog", "cfg": 3}) == {"prompt": "a dog", "cfg": 3.0}


def test_chat_a_findet_alles_wieder_nach_chat_b(client):
    client.put("/api/v1/settings/chat:a/bildfenster", json={"wert": CHAT_A})
    client.put(
        "/api/v1/settings/chat:b/bildfenster",
        json={"wert": {"breite": 512, "modell": "sd15.safetensors", "stapel": []}},
    )

    a = client.get("/api/v1/settings/resolved/bildfenster?chat=a").json()["wert"]
    b = client.get("/api/v1/settings/resolved/bildfenster?chat=b").json()["wert"]
    assert a == CHAT_A
    assert (b["breite"], b["modell"], b["stapel"]) == (512, "sd15.safetensors", [])


def test_bildnamen_folgen_der_bildroute():
    from app.api.v1.bilder import ERLAUBTE_TYPEN

    assert set(bildfensterwahl.BILDENDUNGEN) == set(ERLAUBTE_TYPEN.values())
    assert bildfensterwahl.wahl_pruefen({"startbild": "../chats/x?"}) is None
    assert bildfensterwahl.wahl_pruefen({"breite": 10**400}) is None
    assert bildfensterwahl.wahl_pruefen({"eta": 10**400}) is None


def test_die_masse_folgen_den_regeln_der_klassenwerte():
    assert bildfensterwahl.wahl_pruefen({"schritte": 999, "sampler": "gibt-es-nicht"}) == {
        "schritte": 999
    }
    assert bildfensterwahl.wahl_pruefen({"schritte": 0, "breite": 1000}) == {
        "schritte": 1, "breite": 1024,
    }


def test_unendliche_zahlen_fallen_raus_statt_umzufallen():
    for wert in (float("inf"), float("nan")):
        assert bildfensterwahl.wahl_pruefen({"breite": wert, "cfg": wert, "bilder_je_lauf": wert}) is None


def test_switches_keep_only_what_their_row_takes():
    """A machine switch, an unknown key and a value its row refuses are
    dropped one by one; the rest stays."""
    kept = bildfensterwahl.wahl_pruefen({"switches": {
        "timestep_shift": 250, "mmap": True, "made_up": 1, "compression_quality": 900,
    }})
    assert kept == {"switches": {"timestep_shift": 250}}


def test_draw_request_carries_switches_but_no_picture():
    request = bildfensterwahl.draw_request(
        {"switches": {"timestep_shift": 250, "ip_adapter_image": "a" * 32 + ".png"}},
    )
    assert request["switches"] == {"timestep_shift": 250}


def test_the_upscale_model_is_kept_per_chat_but_not_drawn_with():
    """The file "Upscale" enlarges with is a choice of the chat, kept like
    the highres upscaler; a drawing does not carry it."""
    kept = bildfensterwahl.wahl_pruefen({"upscale_model": "4x.pth", "hires_upscaler": "RealESRGAN"})
    assert kept == {"upscale_model": "4x.pth", "hires_upscaler": "RealESRGAN"}
    assert "upscale_model" not in bildfensterwahl.draw_request(kept)


def test_a_stored_infinite_switch_value_is_dropped_alone():
    kept = bildfensterwahl.wahl_pruefen({"switches": {"sample_lms_max_order": float("inf"), "fa": True, "timestep_shift": 250}})
    assert kept == {"switches": {"timestep_shift": 250}}


def _studio_fields() -> set[str]:
    quelle = (
        Path(__file__).resolve().parents[1] / "frontend" / "src" / "lib" / "studio.svelte.js"
    ).read_text(encoding="utf-8")
    tabelle = quelle.split("export const ANFANG = {", 1)[1].split("\n}\n", 1)[0]
    return set(re.findall(r"^  ([a-z0-9_]+): ", tabelle, re.MULTILINE))


def test_studio_and_service_know_the_same_fields():
    """The studio's table (frontend/src/lib/studio.svelte.js `ANFANG`) and
    the service's table are kept by hand; a field on one side only would be
    dropped on the way and stand at its start value again on the next
    visit."""
    assert _studio_fields() == set(bildfensterwahl.FELDER)


# What the studio's basics set for one chat, every field it shows.
STUDIO_A = {
    "modell": "flux.gguf", "breite": 1024, "hoehe": 768, "schritte": 100, "cfg": 35,
    "guidance": 3.5, "sampler": "euler", "scheduler": "simple", "seed": "123",
    "seed_modus": "fest", "bilder_je_lauf": 9,
    "video_frames": 33, "fps": 16, "stapel": [{"name": "stil.safetensors", "staerke": -0.5}],
    "lora_modus": "auto", "switches": {"circular": True},
}


def test_a_studio_value_stands_after_another_chat(client):
    client.put("/api/v1/settings/chat:a/bildfenster", json={"wert": STUDIO_A})
    client.put("/api/v1/settings/chat:b/bildfenster", json={"wert": {"breite": 512, "schritte": 20}})

    a = client.get("/api/v1/settings/resolved/bildfenster?chat=a").json()["wert"]
    for name, wert in STUDIO_A.items():
        assert a[name] == wert, name


def test_a_chat_stored_with_the_metadata_field_reads_without_it(client):
    """The studio had a metadata field of its own per chat. Whether the
    settings stay in the file is the one switch's to say now
    (app/bildschutz.py): a chat stored with the old field is read without an
    error, the field is gone, and a drawing asks for nothing of the kind."""
    stored = {**STUDIO_A, "metadaten_wahl": "aus"}
    answer = client.put("/api/v1/settings/chat:a/bildfenster", json={"wert": stored})
    assert answer.status_code < 300, answer.text
    read = client.get("/api/v1/settings/resolved/bildfenster?chat=a").json()["wert"]
    assert "metadaten_wahl" not in read
    assert read["breite"] == STUDIO_A["breite"]
    assert "metadaten" not in bildfensterwahl.draw_request(stored)
    assert "metadaten" not in bildfensterwahl.draw_request(read)


def test_the_lora_mode_the_studio_no_longer_offers_reads_as_its_start():
    """A chat left at "immediately" stands at "at runtime", the mode the
    studio starts with — on the way in and on the way out."""
    kept = bildfensterwahl.wahl_pruefen({"lora_modus": "immediately"})
    assert kept == {"lora_modus": "at_runtime"}
    assert bildfensterwahl.draw_request(kept)["lora_apply_mode"] == "at_runtime"


def test_the_lora_modes_the_studio_offers_stay():
    """Silence: "auto" and "at runtime" are kept as they were set."""
    for mode in ("auto", "at_runtime"):
        assert bildfensterwahl.wahl_pruefen({"lora_modus": mode}) == {"lora_modus": mode}


def test_a_chat_without_studio_values_starts_at_the_start_values(client):
    """Silence: a chat nobody set anything in names no model and no measures
    of its own, so the studio shows the default model and its start values."""
    client.put("/api/v1/settings/chat:a/bildfenster", json={"wert": STUDIO_A})
    leer = client.get("/api/v1/settings/resolved/bildfenster?chat=neu").json()["wert"]
    for name in ("modell", "breite", "hoehe", "schritte", "stapel"):
        assert name not in leer, name
