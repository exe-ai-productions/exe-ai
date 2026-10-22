"""The catalogue after the extension: ten cards on each model page, six in
each accessory column, and a Video tab.

Run rather than read: the catalogue module is loaded by Node and its lists
are asked, so a card built in a helper is seen the way the page reads it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app import image_families

WURZEL = Path(__file__).resolve().parent.parent
FRONTEND = WURZEL / "frontend"
LOCALES = WURZEL / "app" / "locales"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")

PAGES = ("chat", "einbettung", "sprache", "bild", "video")
ACCESSORY_KINDS = ("lora", "vae", "adetailer", "mtp", "mmproj")

# What every card that was in the catalogue before the tenth ones came carried: id -> repository,
# file and size of each build. The new cards add to the lists; none of these may move.
BEFORE = {
    "occamy-1": "IsValorum/Occamy-1.0-APEX-I-MiniPlus-V2.1-GGUF|Occamy-1.0.APEX-I-MiniPlus-V2.1.gguf|14.8",
    "gpt-oss-20b-vision": "SoAIHQ/gpt-oss-20b-VISION-v2-GGUF|gpt-oss-20b-VISION-v2-MXFP4.gguf|13.8",
    "qwen38-27b": "ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF|Qwen3.8-27B-GSQ-RCO-IQ3_S.gguf|11.8",
    "ornith-15-9b": "ornith-ai/Ornith-1.5-9B-GGUF|Ornith-1.5-9B-Q4_K_M.gguf|5.8",
    "spark-x25-4b": "peculiar-ragdoll/Sharp-Spark-X2.5-4B-GGUF|Sharp-Spark-X2.5-4B-Q6_K_XL.gguf|3.6",
    "gemma-4-E2B": "unsloth/gemma-4-E2B-it-qat-mobile-GGUF|gemma-4-E2B-it-qat-UD-Q2_K_XL.gguf|2.2",
    "nemotron-35-lightning": "ggml-org/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-GGUF|NVIDIA-Nemotron-3.5-Lightning-30B-A3B-Q4_0.gguf|18.9",
    "gemma-4-12b": "unsloth/gemma-4-12b-it-GGUF|gemma-4-12b-it-Q4_K_M.gguf|7.1",
    "ornith-15-35b": "ornith-ai/Ornith-1.5-35B-A3B-GGUF|Ornith-1.5-35B-Q4_K_M.gguf|21.7",
    "emb-qwen3": "Qwen/Qwen3-Embedding-0.6B-GGUF|Qwen3-Embedding-0.6B-Q8_0.gguf|0.64",
    "emb-nomic": "nomic-ai/nomic-embed-text-v1.5-GGUF|nomic-embed-text-v1.5.Q8_0.gguf|0.15",
    "emb-gemma": "unsloth/embeddinggemma-300m-GGUF|embeddinggemma-300M-Q8_0.gguf|0.33",
    "emb-bgem3": "gpustack/bge-m3-GGUF|bge-m3-Q8_0.gguf|0.64",
    "emb-mxbai": "ChristianAzinn/mxbai-embed-large-v1-gguf|mxbai-embed-large-v1.Q8_0.gguf|0.36",
    "emb-minilm": "second-state/All-MiniLM-L6-v2-Embedding-GGUF|all-MiniLM-L6-v2-Q8_0.gguf|0.03",
    "emb-qwen3-4b": "Qwen/Qwen3-Embedding-4B-GGUF|Qwen3-Embedding-4B-Q8_0.gguf|4.3",
    "emb-qwen3-8b": "Qwen/Qwen3-Embedding-8B-GGUF|Qwen3-Embedding-8B-Q8_0.gguf|8",
    "emb-bgelarge": "CompendiumLabs/bge-large-en-v1.5-gguf|bge-large-en-v1.5-q8_0.gguf|0.36",
    "asr-qwen3-06": "unslothai/Qwen3-ASR-0.6B-GGUF|Qwen3-ASR-0.6B-Q8_0.gguf|0.8",
    "asr-qwen3-17": "ggml-org/Qwen3-ASR-1.7B-GGUF|Qwen3-ASR-1.7B-Q8_0.gguf|2.2",
    "asr-voxtral-3b": "ggml-org/Voxtral-Mini-3B-2507-GGUF|Voxtral-Mini-3B-2507-Q4_K_M.gguf|2.5",
    "tts-qwen3-17b": "ggml-org/Qwen3-TTS-12Hz-1.7B-Base-GGUF|Qwen3-TTS-12Hz-1.7B-Base-Q4_K_M.gguf|1",
    "tts-qwen3-06b-base": "Serveurperso/Qwen3-TTS-GGUF|qwen-talker-0.6b-base-Q4_K_M.gguf|0.63",
    "tts-qwen3-06b-custom": "Serveurperso/Qwen3-TTS-GGUF|qwen-talker-0.6b-customvoice-Q4_K_M.gguf|0.6",
    "tts-qwen3-17b-custom": "Serveurperso/Qwen3-TTS-GGUF|qwen-talker-1.7b-customvoice-Q4_K_M.gguf|1.2",
    "tts-qwen3-17b-design": "Serveurperso/Qwen3-TTS-GGUF|qwen-talker-1.7b-voicedesign-Q4_K_M.gguf|1.2",
    "asr-voxtral-4b-realtime": "ggml-org/Voxtral-Mini-4B-Realtime-2602-GGUF|Voxtral-Mini-4B-Realtime-2602-Q4_K_M.gguf|2.6",
    "cyberrealistic-xl": "cyberdelia/CyberRealisticXL|CyberRealisticXLPlay_V10.0_FP16.safetensors|6.9",
    "juggernaut-xl": "RunDiffusion/Juggernaut-XL-v9|Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors|7.1",
    "animagine-xl": "cagliostrolab/animagine-xl-3.1|animagine-xl-3.1.safetensors|6.9",
    "realistic-vision": "SG161222/Realistic_Vision_V6.0_B1_noVAE|Realistic_Vision_V6.0_NV_B1_fp16.safetensors|2.1",
    "pony-v6-xl": "LyliaEngine/Pony_Diffusion_V6_XL|ponyDiffusionV6XL_v6StartWithThisOne.safetensors|6.9",
    "qwen-image-21": "unsloth/Qwen-Image-2.1-GGUF|qwen-image-2.1-Q4_K_M.gguf|4.2",
    "flux2-klein-4b": "unsloth/FLUX.2-klein-4B-GGUF|flux-2-klein-4b-Q4_K_M.gguf|2.6",
    "z-image-turbo": "unsloth/Z-Image-Turbo-GGUF|z-image-turbo-Q4_K_M.gguf|5",
    "krea-2-turbo": "krea/Krea-2-Turbo|turbo.safetensors|26.3",
    "wan21-t2v-13b": "Comfy-Org/Wan_2.1_ComfyUI_repackaged|split_files/diffusion_models/wan2.1_t2v_1.3B_fp16.safetensors|2.8",
    "wan21-i2v-14b": "Comfy-Org/Wan_2.1_ComfyUI_repackaged|split_files/diffusion_models/wan2.1_i2v_480p_14B_fp8_e4m3fn.safetensors|16.4",
    "wan22-ti2v-5b": "Comfy-Org/Wan_2.2_ComfyUI_Repackaged|split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors|10",
    "wan22-t2v-a14b": "Comfy-Org/Wan_2.2_ComfyUI_Repackaged|split_files/diffusion_models/wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors|28.6",
    "wan22-i2v-a14b": "Comfy-Org/Wan_2.2_ComfyUI_Repackaged|split_files/diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors|28.6",
    "wan22-s2v-14b": "Comfy-Org/Wan_2.2_ComfyUI_Repackaged|split_files/diffusion_models/wan2.2_s2v_14B_fp8_scaled.safetensors|16.4",
    "ltx-23": "unsloth/LTX-2.3-GGUF|ltx-2.3-22b-dev-Q4_K_M.gguf|14.3",
    "minimax-h3": "unsloth/MiniMax-H3-GGUF|minimax_h3_fl2va_pruned-Q4_K.gguf|11.4",
    "hunyuanvideo-15": "Comfy-Org/HunyuanVideo_1.5_repackaged|split_files/diffusion_models/hunyuanvideo1.5_480p_t2v_cfg_distilled_fp8_scaled.safetensors|8.3",
    "lora-lcm-15": "latent-consistency/lcm-lora-sdv1-5|pytorch_lora_weights.safetensors|0.14",
    "lora-hyper-15": "ByteDance/Hyper-SD|Hyper-SD15-8steps-lora.safetensors|0.27",
    "lora-krea2-4step": "lvladikov/Krea2-Turbo-Distill-4step-LoRA|krea2_turbo_4step_rank_64_lora_comfyui.safetensors|0.44",
    "lora-light-xl": "ByteDance/SDXL-Lightning|sdxl_lightning_8step_lora.safetensors|0.39",
    "lora-multidet-xl": "Stableyogi/Detailers|Super_Multi_Detailer_By_Stable_Yogi_A1.safetensors|0.23",
    "lora-skindet-15": "Stableyogi/Super-Skin-Detailer|Super_Skin_Detailer_By_Stable_Yogi_SD0_V1.safetensors|0.12",
    "vae-mse-15": "stabilityai/sd-vae-ft-mse-original|vae-ft-mse-840000-ema-pruned.safetensors|0.34",
    "vae-ema-15": "stabilityai/sd-vae-ft-ema-original|vae-ft-ema-560000-ema-pruned.safetensors|0.34",
    "vae-fp16-xl": "madebyollin/sdxl-vae-fp16-fix|sdxl_vae.safetensors|0.34",
    "vae-orig-xl": "stabilityai/sdxl-vae|sdxl_vae.safetensors|0.34",
    "vae-flux-ae": "black-forest-labs/FLUX.1-dev|ae.safetensors|0.34",
    "vae-qwen-image-21": "Comfy-Org/Qwen-Image-2.1|vae/qwen_image_2.1_vae_bf16.safetensors|0.68",
    "ad-face-n": "exeterminal/adetailer-yolov8-safetensors|face_yolov8n.safetensors|0.01",
    "ad-face-s": "exeterminal/adetailer-yolov8-safetensors|face_yolov8s.safetensors|0.02",
    "ad-face-m": "exeterminal/adetailer-yolov8-safetensors|face_yolov8m.safetensors|0.05",
    "ad-hand-n": "exeterminal/adetailer-yolov8-safetensors|hand_yolov8n.safetensors|0.01",
    "ad-hand-s": "exeterminal/adetailer-yolov8-safetensors|hand_yolov8s.safetensors|0.02",
    "ad-face-n2": "exeterminal/adetailer-yolov8-safetensors|face_yolov8n_v2.safetensors|0.01",
    "mtp-occamy": "IsValorum/Occamy-1.0-APEX-I-MiniPlus-V2.1-GGUF|occamy-1.0-mtp-Q4_K_M.gguf|1.3",
    "mtp-qwen38": "unsloth/Qwen3.8-27B-GGUF|MTP/mtp-Qwen3.8-27B-Q4_0.gguf|1.4",
    "mtp-ornith-9b": "protoLabsAI/Ornith-1.5-9B-MTP-GGUF|mtp-head/mtp-Ornith-1.5-9B-head-Q8_0.gguf|2.4",
    "mtp-gemma-e2b": "unsloth/gemma-4-E2B-it-qat-mobile-GGUF|mtp-gemma-4-E2B-it.gguf|0.06",
    "mtp-gemma-12b": "unsloth/gemma-4-12b-it-GGUF|mtp-gemma-4-12b-it.gguf|0.47",
    "mtp-nemotron": "ggml-org/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-GGUF|mtp-NVIDIA-Nemotron-3.5-Lightning-30B-A3B-Q4_0.gguf|1.2",
    "mmproj-occamy": "IsValorum/Occamy-1.0-APEX-I-MiniPlus-V2.1-GGUF|mmproj-Accio-Lab_occamy-1.0-Q8_0.gguf|0.61",
    "mmproj-gptoss": "SoAIHQ/gpt-oss-20b-VISION-v2-GGUF|mmproj-gpt-oss-20b-VISION-v2-f16.gguf|0.65",
    "mmproj-qwen38": "ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF|mmproj-Qwen3.8-27B-BF16.gguf|0.93",
    "mmproj-ornith-9b": "ornith-ai/Ornith-1.5-9B-GGUF|mmproj-Ornith-1.5-9B-BF16.gguf|0.92",
    "mmproj-ornith-35b": "ornith-ai/Ornith-1.5-35B-A3B-GGUF|mmproj-Ornith-1.5-35B-BF16.gguf|0.9",
    "mmproj-gemma-12b": "unsloth/gemma-4-12b-it-GGUF|mmproj-F16.gguf|0.18",
}


def _catalogue() -> dict:
    driver = FRONTEND / f"nine-{os.getpid()}.pruefung.mjs"
    driver.write_text(
        "import { ARTEN, SUCHBARE_ARTEN, KATALOG_ZUBEHOER, SPALTEN_ZUBEHOER, dienstArt, katalogFuer }"
        " from './src/lib/modellempfehlungen.js'\n"
        "const pages = {}\n"
        f"for (const art of {json.dumps(list(PAGES))}) pages[art] = katalogFuer(art)\n"
        "console.log('---REPORT---' + JSON.stringify({\n"
        "  arten: ARTEN, suchbar: SUCHBARE_ARTEN, spalten: SPALTEN_ZUBEHOER,\n"
        "  dienst: ARTEN.map((art) => [art, dienstArt(art)]),\n"
        "  pages, zubehoer: KATALOG_ZUBEHOER,\n"
        "}))\n",
        encoding="utf-8",
    )
    try:
        run = subprocess.run(["node", driver.name], cwd=FRONTEND, capture_output=True, text=True, timeout=60)
    finally:
        driver.unlink(missing_ok=True)
    assert run.returncode == 0, (run.stdout + run.stderr)[-3000:]
    return json.loads(run.stdout.split("---REPORT---", 1)[1].strip())


def _locale(language: str) -> dict:
    return json.loads((LOCALES / f"{language}.json").read_text(encoding="utf-8"))["katalog"]


def _all_cards(data: dict) -> list[dict]:
    return [card for art in PAGES for card in data["pages"][art]] + data["zubehoer"]


@needs_node
def test_every_model_page_has_ten_cards_and_every_accessory_column_six():
    data = _catalogue()
    for art in PAGES:
        assert len(data["pages"][art]) == 10, art
    assert data["spalten"] == list(ACCESSORY_KINDS)
    for kind in ACCESSORY_KINDS:
        assert len([c for c in data["zubehoer"] if c["sorte"] == kind]) == 6, kind
    assert len(data["zubehoer"]) == 30


@needs_node
def test_no_card_is_listed_twice_and_each_names_a_repository_and_a_file():
    data = _catalogue()
    ids = [card["id"] for card in _all_cards(data)]
    assert len(ids) == len(set(ids))
    for card in _all_cards(data):
        assert card["fassungen"], card["id"]
        for build in card["fassungen"]:
            assert "/" in build["id"], card["id"]
            assert build["datei"], card["id"]
            assert build["groesse"] > 0, card["id"]


@needs_node
def test_the_video_tab_stands_before_the_accessories_and_is_searchable():
    data = _catalogue()
    assert data["arten"] == ["chat", "einbettung", "sprache", "bild", "video", "zubehoer"]
    assert "video" in data["suchbar"]
    assert "zubehoer" not in data["suchbar"]


@needs_node
def test_a_video_download_goes_to_the_picture_side_and_nothing_else_moves():
    """The service has one place for picture and video models; only the tab
    is new. The silence probe: every other kind keeps its own word."""
    data = _catalogue()
    dienst = dict(map(tuple, data["dienst"]))
    assert dienst["video"] == "bild"
    for art in ("chat", "einbettung", "sprache", "bild", "zubehoer"):
        assert dienst[art] == art, art


@needs_node
def test_each_video_card_is_a_picture_card_of_a_video_family():
    """No second path: a video model is looked up in the families the service
    already loads, and its file name resolves to one of them."""
    data = _catalogue()
    for card in data["pages"]["video"]:
        assert card["bild"] is True, card["id"]
        family = image_families.get(card["klasse"])
        assert family is not None and family.video, card["id"]
        for build in card["fassungen"]:
            name = build.get("ziel") or build["datei"].split("/")[-1]
            found = image_families.family_of_file(name)
            assert found is not None and found.video, name


@needs_node
def test_a_pair_of_models_brings_its_second_model():
    """Wan 2.2 A14B runs on a high-noise and a low-noise model."""
    cards = {card["id"]: card for card in _catalogue()["pages"]["video"]}
    for card_id in ("wan22-t2v-a14b", "wan22-i2v-a14b"):
        build = cards[card_id]["fassungen"][0]
        assert "low_noise" in build["datei"], card_id
        assert "high_noise" in build["partner"]["datei"], card_id
        assert build["partner"]["ziel"], card_id
    assert not any("partner" in b for b in cards["wan22-ti2v-5b"]["fassungen"])


@needs_node
def test_all_six_detectors_come_from_the_repack_repository():
    """The three new ones (Faces v8m, Hands v8s, Faces v8n v2) stand next to the
    three that were there; all six are files in one repository."""
    adetailer = {c["id"]: c for c in _catalogue()["zubehoer"] if c["sorte"] == "adetailer"}
    assert {"ad-face-m", "ad-hand-s", "ad-face-n2"} <= set(adetailer)
    assert len(adetailer) == 6
    for card in adetailer.values():
        build = card["fassungen"][0]
        assert build["id"] == "exeterminal/adetailer-yolov8-safetensors", card["id"]
        assert build["datei"].endswith(".safetensors"), card["id"]


@needs_node
def test_each_text_of_a_card_exists_in_both_languages_and_they_differ():
    data = _catalogue()
    german, english = _locale("de"), _locale("en")
    for card in _all_cards(data):
        keys = [card.get("satz"), card.get("langsatz"), card.get("nameKey")]
        for key in filter(None, keys):
            word = key.removeprefix("katalog.")
            assert word in german and word in english, key
            assert german[word] != english[word], key


@needs_node
def test_the_tab_has_its_word_in_both_languages():
    for language in ("de", "en"):
        texts = _locale(language)
        assert texts["art_video"] and texts["vorauswahl_video"], language


def test_the_page_downloads_a_picture_card_through_the_one_kit_path():
    page = (FRONTEND / "src" / "teile" / "Katalog.svelte").read_text(encoding="utf-8")
    assert "bildFassungHolen" in page
    assert "kitJobs(" in page
    assert re.search(r"const ziel = \{ art: dienstArt\(art\) \}", page)
    phone = (FRONTEND / "src" / "phone" / "pages" / "Catalog.svelte").read_text(encoding="utf-8")
    assert "value: 'video'" in phone and "video: 'katalog.vorauswahl_video'" in phone


def test_a_context_under_a_thousand_tokens_is_not_rounded_up_to_a_thousand():
    """512 tokens used to read "1k Kontext" on three embedding cards."""
    card = (FRONTEND / "src" / "teile" / "Modellkarte.svelte").read_text(encoding="utf-8")
    assert "karte.kontext < 1024 ? formatNumber(karte.kontext / 1024, 1, texte.sprache)" in card


def test_a_pair_of_models_is_ready_only_with_both_models():
    page = (FRONTEND / "src" / "teile" / "Katalog.svelte").read_text(encoding="utf-8")
    assert "(!f.partner || istDa(f.partner.ziel))" in page
    phone = (FRONTEND / "src" / "phone" / "catalog.js").read_text(encoding="utf-8")
    assert "(!build.partner || present.includes(build.partner.ziel))" in phone


def test_a_picture_card_without_a_family_draws_no_empty_pill():
    card = (FRONTEND / "src" / "teile" / "Modellkarte.svelte").read_text(encoding="utf-8")
    assert '{#if familyName}<span class="klassepille">{familyName}</span>{/if}' in card


@needs_node
def test_the_qwen38_card_shows_the_thinking_bulb_and_the_others_stay_as_they_were():
    cards = {c["id"]: c for c in _catalogue()["pages"]["chat"]}
    assert cards["qwen38-27b"]["faehigkeiten"] == ["werkzeug", "auge", "gluehbirne"]
    # The two Ornith cards keep their signs, without the bulb.
    assert cards["ornith-15-9b"]["faehigkeiten"] == ["werkzeug", "auge"]
    assert cards["ornith-15-35b"]["faehigkeiten"] == ["werkzeug", "auge"]


@needs_node
def test_the_tenth_card_of_every_model_page_is_the_one_measured():
    pages = _catalogue()["pages"]
    last = {art: pages[art][-1] for art in PAGES}
    assert [last[art]["id"] for art in PAGES] == [
        "lfm25-24b-a2b", "emb-lfm25-350m", "asr-voxtral-small-24b", "moss-image-sft", "lingbot-video-13b",
    ]
    chat = last["chat"]["fassungen"][0]
    assert (chat["id"], chat["datei"], chat["groesse"]) == ("LiquidAI/LFM2.5-24B-A2B-GGUF", "LFM2.5-24B-A2B-QAD-Q4_0.gguf", 13.6)
    assert last["chat"]["faehigkeiten"] == ["werkzeug", "gluehbirne"] and last["chat"]["kontext"] == 131072
    emb = last["einbettung"]["fassungen"][0]
    assert (emb["id"], emb["datei"], emb["groesse"]) == ("LiquidAI/LFM2.5-Embedding-350M-GGUF", "LFM2.5-Embedding-350M-Q8_0.gguf", 0.38)
    # The card's own `max_seq_length`, not the larger number of the file's header.
    assert last["einbettung"]["kontext"] == 512
    speech = last["sprache"]["fassungen"][0]
    assert (speech["id"], speech["groesse"]) == ("bartowski/mistralai_Voxtral-Small-24B-2507-GGUF", 14.3)
    assert last["sprache"]["kontext"] == 32768
    image = last["bild"]
    assert (image["bild"], image["klasse"], image["marke"]) == (True, "moss_image", "openmoss-team")
    assert (image["fassungen"][0]["id"], image["fassungen"][0]["datei"]) == ("leejet/MOSS-Image-SFT-GGUF", "MOSS-Image-SFT-Q4_K.gguf")
    video = last["video"]
    assert (video["bild"], video["klasse"], video["marke"]) == (True, "lingbot_video", "robbyant")
    build = video["fassungen"][0]
    assert build["id"] == "robbyant/lingbot-video-dense-1.3b"
    assert build["datei"] == "transformer/diffusion_pytorch_model.safetensors"
    assert "lingbot-video" in build["ziel"] and build["groesse"] == 2.8


@needs_node
def test_the_picture_families_of_the_new_cards_are_found_by_their_local_names():
    pages = _catalogue()["pages"]
    for art, family in (("bild", "moss_image"), ("video", "lingbot_video")):
        card = pages[art][-1]
        build = card["fassungen"][0]
        name = build.get("ziel") or build["datei"].split("/")[-1]
        found = image_families.family_of_file(name)
        assert found is not None and found.name == family, name


@needs_node
def test_the_projector_of_every_speech_card_is_paired_with_its_model(tmp_path):
    """The projector's local name must begin with the model file's name, or
    `passende_mmproj` cannot say whose ears it is. The Voxtral Small card is
    the case that had to be written out; the speech cards before it are
    checked with it."""
    from app.modellrunner import VISION_ORDNER, passende_mmproj

    seen = 0
    for card in _catalogue()["pages"]["sprache"]:
        for build in card["fassungen"]:
            if not build.get("mmproj"):
                continue
            seen += 1
            folder = tmp_path / card["id"]
            (folder / VISION_ORDNER).mkdir(parents=True)
            (folder / VISION_ORDNER / build["mmproj_ziel"]).write_bytes(b"x")
            found = passende_mmproj(folder, build["datei"].split("/")[-1])
            assert found is not None and found.name == build["mmproj_ziel"], card["id"]
    assert seen == 10


@needs_node
def test_silence_the_cards_that_were_there_keep_their_repository_file_and_size():
    data = _catalogue()
    now = {
        card["id"]: " ; ".join(f"{b['id']}|{b['datei']}|{b['groesse']}" for b in card["fassungen"])
        for card in _all_cards(data)
    }
    assert {key: now.get(key) for key in BEFORE} == BEFORE
    assert len(now) == len(BEFORE) + 5


@needs_node
def test_silence_the_recommendation_for_a_machine_does_not_move():
    """The new chat card is not a better first model for any machine size the
    onboarding names; the pick stays what it was."""
    driver = FRONTEND / f"pick-{os.getpid()}.pruefung.mjs"
    driver.write_text(
        "import { empfehlungFuer } from './src/lib/modellempfehlungen.js'\n"
        "const out = {}\n"
        "for (const g of [8, 16, 18, 24, 32, 64, 128]) { const e = empfehlungFuer(g); out[g] = e && e.karte.id }\n"
        "console.log('---REPORT---' + JSON.stringify(out))\n",
        encoding="utf-8",
    )
    try:
        run = subprocess.run(["node", driver.name], cwd=FRONTEND, capture_output=True, text=True, timeout=60)
    finally:
        driver.unlink(missing_ok=True)
    assert run.returncode == 0, (run.stdout + run.stderr)[-3000:]
    picked = json.loads(run.stdout.split("---REPORT---", 1)[1].strip())
    assert picked == {
        "8": "ornith-15-9b", "16": "qwen38-27b", "18": "gpt-oss-20b-vision", "24": "occamy-1",
        "32": "ornith-15-35b", "64": "ornith-15-35b", "128": "ornith-15-35b",
    }
