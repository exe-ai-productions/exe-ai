/*
  The curated catalogue — which model to suggest for a machine, and in
  which build.

  Its own module because it is data, not markup, and the one place a name
  changes when a better model comes along. The search next to it finds
  everything; this list answers what the search cannot: *which of the
  thousands is the one for my machine.*

  A card is a MODEL, not a file. One card can carry several builds
  (`fassungen`) — a 4-bit that fits a laptop and an 8-bit that wants a
  workstation — and the one that suits the machine is pre-picked. Every
  build is one GGUF file that can be fetched with one button and started
  with another; nothing here asks anybody to open a terminal.

  Each build carries the exact companion names, all checked against the
  repository they name — a recommendation that 404s looks like a broken
  program, not a wrong list:
    `mmproj` is the vision projector as the repository names it,
    `mmproj_ziel` the name it gets locally (several repositories call
    theirs plainly `mmproj-F16.gguf`, and two of those in one folder would
    overwrite each other).
    `drafter` is the speed module that makes answers faster — a prediction
    module (mtp) trained alongside the model, or a tiny sibling where the
    family ships one, never a mid-sized model. `drafter_ziel` names it
    locally, `drafter_repo` says where it lives when that is not the
    model's own repository.
    `bis` is the memory step the build is the pick for.

  Every card here is checked against Hugging Face. More arrive by data
  care, never by guessing — a card whose repository or file name was not
  verified is left out on purpose.
*/

import { speicherSchaetzung } from './speicherschaetzung.js'

/* The catalogue's tabs. Each is its own search on the server side
   (see app/api/v1/modellsuche.py) and its own curated list here — a chat
   model, an embedding model and an image model are different things to
   run, and a merged list offers each one where it cannot work. A video model
   lies in the picture folder and is drawn by the picture server, so its tab
   fetches into the picture side (`dienstArt`). */
export const ARTEN = ['chat', 'einbettung', 'sprache', 'bild', 'video', 'zubehoer']

/* The kind the service files a tab's models under: the video tab downloads
   into the picture folder, whose server draws them. */
export const dienstArt = (art) => (art === 'video' ? 'bild' : art)

/* Where each accessory kind is downloaded to — a sub-folder of its server, so
   each folder shows only its own kind and the file appears where it belongs at
   once. VAE, text encoder, LoRA and the face detector are image-side; a drafter and a
   projector are chat-side and also carry the companion role that writes the
   folder manifest. */
export const ZUBEHOER_ZIEL = {
  vae: { art: 'bild', unterordner: 'vae' },
  text_encoder: { art: 'bild', unterordner: 'text_encoders' },
  lora: { art: 'bild', unterordner: 'lora' },
  adetailer: { art: 'bild', unterordner: 'adetailer' },
  mmproj: { art: 'chat', unterordner: 'vision', rolle: 'mmproj' },
  mtp: { art: 'chat', unterordner: 'mtp', rolle: 'mtp' },
}

/* The accessory tab shows one column per kind, in this order. A generic
   mechanism, not a special case per tab: the gallery filters the cards by
   `sorte` into these columns and puts an "open folder" button on each. */
export const SPALTEN_ZUBEHOER = ['lora', 'vae', 'adetailer', 'mtp', 'mmproj']

/* Which server folder each accessory column opens, and on which side. */
export const ZUBEHOER_ORDNER = {
  lora: { seite: 'bild', unter: 'lora' },
  vae: { seite: 'bild', unter: 'vae' },
  adetailer: { seite: 'bild', unter: 'adetailer' },
  mtp: { seite: 'chat', unter: 'mtp' },
  mmproj: { seite: 'chat', unter: 'vision' },
}

/* The tabs whose search box does something. The curated accessory tab hides
   the box entirely — a search that always returns nothing is worse than no
   box. */
export const SUCHBARE_ARTEN = ['chat', 'einbettung', 'sprache', 'bild', 'video']

/* The colour each accessory kind wears on its card. The design rule of the
   house: one capability, one colour, EVERYWHERE. MTP is the blue of its
   speed-module bolt, mmproj the violet of the vision eye in the input bar —
   so tag and live indicator read as one thing wherever they appear.

   Named from the palette, never as a literal: a hex value here carries one
   appearance's tone into all three and beats every theme rule. The three
   image-side kinds have no palette name yet and stay literal for now. */
export const SORTE_FARBE = {
  lora: '#bd7a53',
  vae: '#4e8f8b',
  adetailer: '#b56d84',
  mtp: 'var(--blau)',
  mmproj: 'var(--violett)',
}

/* A weaker take of one of the colours above, for a border or a tinted
   ground. Written as a mix because a palette name is not a hex value: the
   old form appended `55` or `18` to the string, which only ever worked
   while every colour here was a literal — and silently produced invalid
   CSS for the `var(--text-leise)` fallback. */
export function farbton(farbe, prozent) {
  return `color-mix(in srgb, ${farbe} ${prozent}%, transparent)`
}

/* The capability colours — same guide, one capability, one colour,
   everywhere: bulb gold, bolt blue, eye violet, wrench olive, wherever
   they appear, and each by its palette name. */
export const FAEHIGKEIT_FARBE = {
  gluehbirne: 'var(--gelb)',
  blitz: 'var(--blau)',
  auge: 'var(--violett)',
  werkzeug: 'var(--oliv)',
}

/* The i18n key for each accessory kind's label — one place, so the card and
   the detail view cannot disagree and a new kind is added once. */
export const SORTE_LABEL = {
  vae: 'katalog.sorte_vae',
  lora: 'katalog.sorte_lora',
  adetailer: 'katalog.sorte_adetailer',
  mmproj: 'katalog.sorte_mmproj',
  mtp: 'katalog.sorte_mtp',
}

/* The context the fit estimate assumes — the everyday case, not the model's
   ceiling. A build "fits" when its file plus a conversation of this size
   plus its speed module stay under the machine's memory. */
const STANDARD_KONTEXT = 32768

/* A rough weight for a speed module that rides along — a few hundred
   megabytes. The estimate is an order of magnitude, not a decimal. */
const DRAFTER_GB = 0.4

/* The machine sizes an honest "needs a bigger machine" rounds up to. */
const MASCHINEN = [8, 16, 32, 64, 128]

export const KATALOG = [
  {
    /* Accio's agent MoE on Qwen3.6 35B A3B, in IsValorum's APEX-I MiniPlus
       build. Repository, file names, sizes and context verified against
       Hugging Face; the repository ships the vision projector beside the
       model. */
    id: 'occamy-1',
    name: 'Occamy 1.0',
    von: 'Accio',
    logo: 'O',
    marke: 'accio',
    satz: 'katalog.satz_occamy',
    langsatz: 'katalog.lang_occamy',
    faehigkeiten: ['werkzeug', 'auge', 'gluehbirne'],
    kontext: 262144,
    fassungen: [
      {
        id: 'IsValorum/Occamy-1.0-APEX-I-MiniPlus-V2.1-GGUF',
        name: 'APEX-I MiniPlus V2.1',
        datei: 'Occamy-1.0.APEX-I-MiniPlus-V2.1.gguf',
        groesse: 14.8,
        mmproj: 'mmproj-Accio-Lab_occamy-1.0-Q8_0.gguf',
        mmproj_ziel: 'mmproj-Accio-Lab_occamy-1.0-Q8_0.gguf',
      },
    ],
  },
  {
    /* OpenAI's gpt-oss-20b with its released weights unchanged, in SoAI's
       build: a corrected chat template for clean tool calls and an image
       projector. Repository, file names, sizes and context verified against
       Hugging Face. */
    id: 'gpt-oss-20b-vision',
    name: 'GPT-OSS 20B Vision V2',
    von: 'OpenAI',
    logo: 'G',
    marke: 'openai',
    satz: 'katalog.satz_gptoss',
    langsatz: 'katalog.lang_gptoss',
    faehigkeiten: ['werkzeug', 'auge', 'gluehbirne'],
    kontext: 131072,
    fassungen: [
      {
        id: 'SoAIHQ/gpt-oss-20b-VISION-v2-GGUF',
        name: 'MXFP4',
        datei: 'gpt-oss-20b-VISION-v2-MXFP4.gguf',
        groesse: 13.8,
        mmproj: 'mmproj-gpt-oss-20b-VISION-v2-f16.gguf',
        mmproj_ziel: 'mmproj-gpt-oss-20b-VISION-v2-f16.gguf',
      },
    ],
  },
  {
    /* Qwen3.8 27B with vision, quantised by ISTA-DASLab with its GSQ-RCO
       method. Repository, file names, sizes and context verified against
       Hugging Face; the plain file, not the one with the MTP head inside,
       until the runner is measured using it. */
    id: 'qwen38-27b',
    name: 'Qwen3.8 27B',
    von: 'ISTA-DASLab',
    logo: 'I',
    marke: 'ista',
    satz: 'katalog.satz_qwen38',
    langsatz: 'katalog.lang_qwen38',
    faehigkeiten: ['werkzeug', 'auge', 'gluehbirne'],
    kontext: 262144,
    fassungen: [
      {
        id: 'ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF',
        name: '3-Bit · IQ3_S',
        datei: 'Qwen3.8-27B-GSQ-RCO-IQ3_S.gguf',
        groesse: 11.8,
        mmproj: 'mmproj-Qwen3.8-27B-BF16.gguf',
        mmproj_ziel: 'mmproj-Qwen3.8-27B-BF16.gguf',
      },
    ],
  },
  {
    /* A dense 9B with vision from Ornith AI. Repository, file names, sizes
       and context verified against Hugging Face. */
    id: 'ornith-15-9b',
    name: 'Ornith 1.5 9B',
    von: 'Ornith AI',
    logo: 'O',
    marke: 'ornith',
    satz: 'katalog.satz_ornith',
    langsatz: 'katalog.lang_ornith',
    faehigkeiten: ['werkzeug', 'auge'],
    kontext: 262144,
    fassungen: [
      {
        id: 'ornith-ai/Ornith-1.5-9B-GGUF',
        name: '4-Bit · Q4_K_M',
        datei: 'Ornith-1.5-9B-Q4_K_M.gguf',
        groesse: 5.8,
        mmproj: 'mmproj-Ornith-1.5-9B-BF16.gguf',
        mmproj_ziel: 'mmproj-Ornith-1.5-9B-BF16.gguf',
      },
    ],
  },
  {
    /* SparkLLM's dense 4B with a native million-token context, in the
       Sharp-Spark build (imatrix quantisation, repaired chat template). Its
       architecture needs llama.cpp from September 2026 on, which the bundled
       runner is. Repository, file names, sizes and context verified against
       Hugging Face. */
    id: 'spark-x25-4b',
    name: 'Spark-X2.5 4B',
    von: 'SparkLLM',
    logo: 'S',
    marke: 'sparkllm',
    satz: 'katalog.satz_spark',
    langsatz: 'katalog.lang_spark',
    faehigkeiten: ['werkzeug', 'gluehbirne'],
    kontext: 1048576,
    fassungen: [
      {
        id: 'peculiar-ragdoll/Sharp-Spark-X2.5-4B-GGUF',
        name: '6-Bit · Q6_K_XL',
        datei: 'Sharp-Spark-X2.5-4B-Q6_K_XL.gguf',
        groesse: 3.6,
      },
    ],
  },
  {
    /* Google's smallest Gemma 4, in Unsloth's quantisation-aware mobile
       build, with its MTP drafter. Repository, file names, sizes and
       context verified against Hugging Face. */
    id: 'gemma-4-E2B',
    name: 'Gemma 4 E2B',
    von: 'Unsloth',
    logo: 'G',
    marke: 'unsloth',
    satz: 'katalog.satz_gemmae2b',
    langsatz: 'katalog.lang_gemmae2b',
    faehigkeiten: ['werkzeug', 'auge', 'blitz'],
    kontext: 131072,
    fassungen: [
      {
        id: 'unsloth/gemma-4-E2B-it-qat-mobile-GGUF',
        name: '2-Bit QAT · UD-Q2_K_XL',
        datei: 'gemma-4-E2B-it-qat-UD-Q2_K_XL.gguf',
        groesse: 2.2,
        mmproj: 'mmproj-F16.gguf',
        mmproj_ziel: 'gemma-4-E2B-it-qat-mmproj-F16.gguf',
        drafter: 'mtp-gemma-4-E2B-it.gguf',
        drafter_ziel: 'mtp-gemma-4-E2B-it.gguf',
      },
    ],
  },
  {
    /* NVIDIA's current 30B mixture of experts with 3B active parameters, in
       ggml-org's Q4_0 build with its own MTP file. Repository, file names and
       sizes verified against Hugging Face; the context is the one the hub
       reads from the file. */
    id: 'nemotron-35-lightning',
    name: 'Nemotron 3.5 Lightning',
    von: 'NVIDIA',
    logo: 'N',
    marke: 'nvidia',
    satz: 'katalog.satz_nemotron',
    faehigkeiten: ['werkzeug', 'blitz'],
    kontext: 1048576,
    fassungen: [
      {
        id: 'ggml-org/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-GGUF',
        name: '4-Bit · Q4_0',
        datei: 'NVIDIA-Nemotron-3.5-Lightning-30B-A3B-Q4_0.gguf',
        groesse: 18.9,
        drafter: 'mtp-NVIDIA-Nemotron-3.5-Lightning-30B-A3B-Q4_0.gguf',
        drafter_ziel: 'mtp-NVIDIA-Nemotron-3.5-Lightning-30B-A3B-Q4_0.gguf',
      },
    ],
  },
  {
    /* Google's Gemma 4 12B in Unsloth's GGUF build, with its projector and
       its MTP drafter from the same repository. Repository, file names,
       sizes and context verified against Hugging Face. */
    id: 'gemma-4-12b',
    name: 'Gemma 4 12B',
    von: 'Google',
    logo: 'G',
    marke: 'google',
    satz: 'katalog.satz_gemma12b',
    faehigkeiten: ['werkzeug', 'auge', 'blitz'],
    kontext: 131072,
    fassungen: [
      {
        id: 'unsloth/gemma-4-12b-it-GGUF',
        name: '4-Bit · Q4_K_M',
        datei: 'gemma-4-12b-it-Q4_K_M.gguf',
        groesse: 7.1,
        mmproj: 'mmproj-F16.gguf',
        mmproj_ziel: 'gemma-4-12b-it-mmproj-F16.gguf',
        drafter: 'mtp-gemma-4-12b-it.gguf',
        drafter_ziel: 'mtp-gemma-4-12b-it.gguf',
      },
    ],
  },
  {
    /* Ornith AI's 35B mixture of experts with vision, the big sibling of the
       9B. Repository, file names, sizes and context verified against
       Hugging Face. */
    id: 'ornith-15-35b',
    name: 'Ornith 1.5 35B-A3B',
    von: 'Ornith AI',
    logo: 'O',
    marke: 'ornith',
    satz: 'katalog.satz_ornith35b',
    faehigkeiten: ['werkzeug', 'auge'],
    kontext: 262144,
    fassungen: [
      {
        id: 'ornith-ai/Ornith-1.5-35B-A3B-GGUF',
        name: '4-Bit · Q4_K_M',
        datei: 'Ornith-1.5-35B-Q4_K_M.gguf',
        groesse: 21.7,
        mmproj: 'mmproj-Ornith-1.5-35B-BF16.gguf',
        mmproj_ziel: 'Ornith-1.5-35B-mmproj-BF16.gguf',
      },
    ],
  },
  {
    /* Liquid AI's 24B mixture of experts with 2B active, in the
       quantisation-aware 4-bit build; it reasons before every answer.
       Repository, file name, size and context verified against Hugging
       Face. */
    id: 'lfm25-24b-a2b',
    name: 'LFM2.5 24B-A2B',
    von: 'Liquid AI',
    logo: 'L',
    satz: 'katalog.satz_lfm25_24b',
    faehigkeiten: ['werkzeug', 'gluehbirne'],
    kontext: 131072,
    fassungen: [
      {
        id: 'LiquidAI/LFM2.5-24B-A2B-GGUF',
        name: '4-Bit QAD · Q4_0',
        datei: 'LFM2.5-24B-A2B-QAD-Q4_0.gguf',
        groesse: 13.6,
      },
    ],
  },
]

/* The embedding catalogue — small single-purpose models for the embedding
   server. Same care as the chat list: every repository, file name, size
   and context checked against Hugging Face. One
   build per card — an embedding model is fetched once and forgotten, a
   row of quants would be noise. */
export const KATALOG_EINBETTUNG = [
  {
    id: 'emb-qwen3', name: 'Qwen3 Embedding 0.6B', von: 'Alibaba',
    logo: 'Q', marke: 'qwen', faehigkeiten: [], kontext: 32768,
    satz: 'katalog.satz_emb_qwen3',
    fassungen: [{ id: 'Qwen/Qwen3-Embedding-0.6B-GGUF', name: '8-Bit · Q8_0', datei: 'Qwen3-Embedding-0.6B-Q8_0.gguf', groesse: 0.64 }],
  },
  {
    id: 'emb-nomic', name: 'Nomic Embed v1.5', von: 'Nomic AI',
    logo: 'N', marke: 'nomic', faehigkeiten: [], kontext: 2048,
    satz: 'katalog.satz_emb_nomic',
    fassungen: [{ id: 'nomic-ai/nomic-embed-text-v1.5-GGUF', name: '8-Bit · Q8_0', datei: 'nomic-embed-text-v1.5.Q8_0.gguf', groesse: 0.15 }],
  },
  {
    id: 'emb-gemma', name: 'EmbeddingGemma 300M', von: 'Google',
    logo: 'G', marke: 'google', faehigkeiten: [], kontext: 2048,
    satz: 'katalog.satz_emb_gemma',
    fassungen: [{ id: 'unsloth/embeddinggemma-300m-GGUF', name: '8-Bit · Q8_0', datei: 'embeddinggemma-300M-Q8_0.gguf', groesse: 0.33 }],
  },
  {
    id: 'emb-bgem3', name: 'BGE-M3', von: 'BAAI',
    logo: 'B', marke: 'baai', faehigkeiten: [], kontext: 8192,
    satz: 'katalog.satz_emb_bgem3',
    fassungen: [{ id: 'gpustack/bge-m3-GGUF', name: '8-Bit · Q8_0', datei: 'bge-m3-Q8_0.gguf', groesse: 0.64 }],
  },
  {
    id: 'emb-mxbai', name: 'mxbai-embed-large', von: 'Mixedbread',
    logo: 'M', marke: 'mixedbread', faehigkeiten: [], kontext: 512,
    satz: 'katalog.satz_emb_mxbai',
    fassungen: [{ id: 'ChristianAzinn/mxbai-embed-large-v1-gguf', name: '8-Bit · Q8_0', datei: 'mxbai-embed-large-v1.Q8_0.gguf', groesse: 0.36 }],
  },
  {
    id: 'emb-minilm', name: 'All-MiniLM L6 v2', von: 'Sentence Transformers',
    logo: 'S', marke: 'sentencetransformers', faehigkeiten: [], kontext: 512,
    satz: 'katalog.satz_emb_minilm',
    fassungen: [{ id: 'second-state/All-MiniLM-L6-v2-Embedding-GGUF', name: '8-Bit · Q8_0', datei: 'all-MiniLM-L6-v2-Q8_0.gguf', groesse: 0.03 }],
  },
  {
    id: 'emb-qwen3-4b', name: 'Qwen3-Embedding 4B', von: 'Alibaba',
    logo: 'Q', marke: 'qwen', faehigkeiten: [], kontext: 32768,
    satz: 'katalog.satz_emb_qwen3_4b',
    fassungen: [{ id: 'Qwen/Qwen3-Embedding-4B-GGUF', name: '8-Bit · Q8_0', datei: 'Qwen3-Embedding-4B-Q8_0.gguf', groesse: 4.3 }],
  },
  {
    id: 'emb-qwen3-8b', name: 'Qwen3-Embedding 8B', von: 'Alibaba',
    logo: 'Q', marke: 'qwen', faehigkeiten: [], kontext: 32768,
    satz: 'katalog.satz_emb_qwen3_8b',
    fassungen: [{ id: 'Qwen/Qwen3-Embedding-8B-GGUF', name: '8-Bit · Q8_0', datei: 'Qwen3-Embedding-8B-Q8_0.gguf', groesse: 8.0 }],
  },
  {
    id: 'emb-bgelarge', name: 'BGE-Large-EN v1.5', von: 'BAAI',
    logo: 'B', marke: 'baai', faehigkeiten: [], kontext: 512,
    satz: 'katalog.satz_emb_bgelarge',
    fassungen: [{ id: 'CompendiumLabs/bge-large-en-v1.5-gguf', name: '8-Bit · Q8_0', datei: 'bge-large-en-v1.5-q8_0.gguf', groesse: 0.36 }],
  },
  {
    // The context is the card's `max_seq_length`; the file's header says more.
    id: 'emb-lfm25-350m', name: 'LFM2.5-Embedding 350M', von: 'Liquid AI',
    logo: 'L', faehigkeiten: [], kontext: 512,
    satz: 'katalog.satz_emb_lfm25',
    fassungen: [{ id: 'LiquidAI/LFM2.5-Embedding-350M-GGUF', name: '8-Bit · Q8_0', datei: 'LFM2.5-Embedding-350M-Q8_0.gguf', groesse: 0.38 }],
  },
]

/* The image catalogue — single-file checkpoints for the local drawer
   (sd.cpp), each repository and file name checked against the real thing
   on Hugging Face when this list was written. Not the chat card's shape: an
   image model has no context window and no KV cache, so a card carries its
   CLASS (which decides the resolution it opens at) and one file, not a row
   of GGUF builds. `bild: true` tells the card to draw itself that way.

   Two rows by intent: the first three are photoreal, the last three are the
   stylised ones. safetensors is the standard form — full quality, exactly
   what ComfyUI runs. `datei` is the exact file the download fetches into the
   image folder. `vae` names a companion for a model shipped without one. */
export const KATALOG_BILD = [
  {
    id: 'cyberrealistic-xl', name: 'CyberRealistic XL', von: 'Cyberdelia',
    logo: 'C', marke: 'cyberdelia', bild: true, klasse: 'sdxl',
    satz: 'katalog.satz_cyberrealisticxl',
    fassungen: [{
      id: 'cyberdelia/CyberRealisticXL', name: 'safetensors',
      datei: 'CyberRealisticXLPlay_V10.0_FP16.safetensors', groesse: 6.9,
    }],
  },
  {
    id: 'juggernaut-xl', name: 'Juggernaut XL', von: 'RunDiffusion',
    logo: 'J', marke: 'rundiffusion', bild: true, klasse: 'sdxl',
    satz: 'katalog.satz_juggernautxl',
    fassungen: [{
      id: 'RunDiffusion/Juggernaut-XL-v9', name: 'safetensors',
      datei: 'Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors', groesse: 7.1,
    }],
  },
  {
    id: 'animagine-xl', name: 'Animagine XL', von: 'Cagliostro Lab',
    logo: 'A', marke: 'cagliostro', bild: true, klasse: 'sdxl',
    satz: 'katalog.satz_animaginexl',
    fassungen: [{
      id: 'cagliostrolab/animagine-xl-3.1', name: 'safetensors',
      datei: 'animagine-xl-3.1.safetensors', groesse: 6.9,
    }],
  },
  {
    id: 'realistic-vision', name: 'Realistic Vision V6.0', von: 'SG161222',
    logo: 'S', marke: null, bild: true, klasse: 'sd15',
    satz: 'katalog.satz_realisticvision',
    fassungen: [{
      id: 'SG161222/Realistic_Vision_V6.0_B1_noVAE', name: 'safetensors',
      datei: 'Realistic_Vision_V6.0_NV_B1_fp16.safetensors', groesse: 2.1,
    }],
  },
  {
    id: 'pony-v6-xl', name: 'Pony Diffusion V6 XL', von: 'LyliaEngine',
    logo: 'L', marke: 'purplesmartai', bild: true, klasse: 'sdxl',
    satz: 'katalog.satz_ponyv6xl',
    fassungen: [{
      id: 'LyliaEngine/Pony_Diffusion_V6_XL', name: 'safetensors',
      datei: 'ponyDiffusionV6XL_v6StartWithThisOne.safetensors', groesse: 6.9,
    }],
  },
  // The four below are assembled from parts (text encoder, VAE): the download
  // asks the head of the file for its kit, as the search's hits do.
  {
    id: 'qwen-image-21', name: 'Qwen-Image 2.1', von: 'Alibaba Qwen',
    logo: 'Q', marke: 'qwen', bild: true, klasse: 'qwen_image_2_1',
    satz: 'katalog.satz_qwenimage21',
    fassungen: [{
      id: 'unsloth/Qwen-Image-2.1-GGUF', name: '4-Bit · Q4_K_M',
      datei: 'qwen-image-2.1-Q4_K_M.gguf', groesse: 4.2,
    }],
  },
  {
    id: 'flux2-klein-4b', name: 'FLUX.2 klein 4B', von: 'Black Forest Labs',
    logo: 'B', marke: 'black-forest-labs', bild: true, klasse: 'flux2_klein',
    satz: 'katalog.satz_flux2klein',
    fassungen: [{
      id: 'unsloth/FLUX.2-klein-4B-GGUF', name: '4-Bit · Q4_K_M',
      datei: 'flux-2-klein-4b-Q4_K_M.gguf', groesse: 2.6,
    }],
  },
  {
    id: 'z-image-turbo', name: 'Z-Image Turbo', von: 'Tongyi-MAI',
    logo: 'T', marke: 'tongyi-mai', bild: true,
    satz: 'katalog.satz_zimageturbo',
    fassungen: [{
      id: 'unsloth/Z-Image-Turbo-GGUF', name: '4-Bit · Q4_K_M',
      datei: 'z-image-turbo-Q4_K_M.gguf', groesse: 5.0,
    }],
  },
  {
    // The repository is gated: the download needs the Hugging Face key.
    id: 'krea-2-turbo', name: 'Krea 2 Turbo', von: 'Krea',
    logo: 'K', marke: 'krea', bild: true, klasse: 'krea2',
    satz: 'katalog.satz_krea2turbo',
    fassungen: [{
      id: 'krea/Krea-2-Turbo', name: 'safetensors',
      datei: 'turbo.safetensors', groesse: 26.3,
    }],
  },
  {
    // The text encoder, the tokenizer and the VAE come with the family.
    id: 'moss-image-sft', name: 'MOSS-Image SFT', von: 'OpenMOSS',
    logo: 'O', marke: 'openmoss-team', bild: true, klasse: 'moss_image',
    satz: 'katalog.satz_moss_image',
    fassungen: [{
      id: 'leejet/MOSS-Image-SFT-GGUF', name: '4-Bit · Q4_K',
      datei: 'MOSS-Image-SFT-Q4_K.gguf', groesse: 3.3,
    }],
  },
]

/* The video catalogue — models the picture server draws in video mode, as
   families `app/image_families.py` already knows. A card is the one file of a
   family (a Wan 2.2 A14B pair is two: `partner`, the second of the two models
   it draws with); the text encoders and the VAE come with it as the kit. The
   file lies in a sub-folder of its repository; `ziel` is the name it keeps in
   our folder. Every repository, file name and size checked against Hugging
   Face when this list was written. */
export const KATALOG_VIDEO = [
  {
    id: 'wan21-t2v-13b', name: 'Wan 2.1 T2V 1.3B', von: 'Alibaba Wan-AI',
    logo: 'W', marke: 'wan-ai', bild: true, klasse: 'wan',
    satz: 'katalog.satz_wan21_t2v',
    fassungen: [{
      id: 'Comfy-Org/Wan_2.1_ComfyUI_repackaged', name: 'safetensors',
      datei: 'split_files/diffusion_models/wan2.1_t2v_1.3B_fp16.safetensors',
      ziel: 'wan2.1_t2v_1.3B_fp16.safetensors', groesse: 2.8,
    }],
  },
  {
    id: 'wan21-i2v-14b', name: 'Wan 2.1 I2V 14B', von: 'Alibaba Wan-AI',
    logo: 'W', marke: 'wan-ai', bild: true, klasse: 'wan',
    satz: 'katalog.satz_wan21_i2v',
    fassungen: [{
      id: 'Comfy-Org/Wan_2.1_ComfyUI_repackaged', name: 'safetensors',
      datei: 'split_files/diffusion_models/wan2.1_i2v_480p_14B_fp8_e4m3fn.safetensors',
      ziel: 'wan2.1_i2v_480p_14B_fp8_e4m3fn.safetensors', groesse: 16.4,
    }],
  },
  {
    id: 'wan22-ti2v-5b', name: 'Wan 2.2 TI2V 5B', von: 'Alibaba Wan-AI',
    logo: 'W', marke: 'wan-ai', bild: true, klasse: 'wan22_ti2v',
    satz: 'katalog.satz_wan22_ti2v',
    fassungen: [{
      id: 'Comfy-Org/Wan_2.2_ComfyUI_Repackaged', name: 'safetensors',
      datei: 'split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors',
      ziel: 'wan2.2_ti2v_5B_fp16.safetensors', groesse: 10.0,
    }],
  },
  {
    id: 'wan22-t2v-a14b', name: 'Wan 2.2 T2V A14B', von: 'Alibaba Wan-AI',
    logo: 'W', marke: 'wan-ai', bild: true, klasse: 'wan',
    satz: 'katalog.satz_wan22_t2v',
    fassungen: [{
      id: 'Comfy-Org/Wan_2.2_ComfyUI_Repackaged', name: 'safetensors',
      datei: 'split_files/diffusion_models/wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors',
      ziel: 'wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors',
      partner: {
        datei: 'split_files/diffusion_models/wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors',
        ziel: 'wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors',
      },
      groesse: 28.6,
    }],
  },
  {
    id: 'wan22-i2v-a14b', name: 'Wan 2.2 I2V A14B', von: 'Alibaba Wan-AI',
    logo: 'W', marke: 'wan-ai', bild: true, klasse: 'wan22_i2v',
    satz: 'katalog.satz_wan22_i2v',
    fassungen: [{
      id: 'Comfy-Org/Wan_2.2_ComfyUI_Repackaged', name: 'safetensors',
      datei: 'split_files/diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors',
      ziel: 'wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors',
      partner: {
        datei: 'split_files/diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors',
        ziel: 'wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors',
      },
      groesse: 28.6,
    }],
  },
  {
    id: 'wan22-s2v-14b', name: 'Wan 2.2 S2V 14B', von: 'Alibaba Wan-AI',
    logo: 'W', marke: 'wan-ai', bild: true, klasse: 'wan22_s2v',
    satz: 'katalog.satz_wan22_s2v',
    fassungen: [{
      id: 'Comfy-Org/Wan_2.2_ComfyUI_Repackaged', name: 'safetensors',
      datei: 'split_files/diffusion_models/wan2.2_s2v_14B_fp8_scaled.safetensors',
      ziel: 'wan2.2_s2v_14B_fp8_scaled.safetensors', groesse: 16.4,
    }],
  },
  {
    id: 'ltx-23', name: 'LTX-2.3', von: 'Lightricks',
    logo: 'L', marke: 'lightricks', bild: true, klasse: 'ltx',
    satz: 'katalog.satz_ltx23',
    fassungen: [{
      id: 'unsloth/LTX-2.3-GGUF', name: '4-Bit · Q4_K_M',
      datei: 'ltx-2.3-22b-dev-Q4_K_M.gguf', groesse: 14.3,
    }],
  },
  {
    id: 'minimax-h3', name: 'MiniMax-H3', von: 'MiniMax',
    logo: 'M', marke: 'minimaxai', bild: true, klasse: 'minimax_h3',
    satz: 'katalog.satz_minimaxh3',
    fassungen: [{
      id: 'unsloth/MiniMax-H3-GGUF', name: '4-Bit · Q4_K',
      datei: 'minimax_h3_fl2va_pruned-Q4_K.gguf', groesse: 11.4,
    }],
  },
  {
    id: 'hunyuanvideo-15', name: 'HunyuanVideo 1.5', von: 'Tencent',
    logo: 'T', marke: 'tencent', bild: true, klasse: 'hunyuan_video',
    satz: 'katalog.satz_hunyuan15',
    fassungen: [{
      id: 'Comfy-Org/HunyuanVideo_1.5_repackaged', name: 'safetensors',
      datei: 'split_files/diffusion_models/hunyuanvideo1.5_480p_t2v_cfg_distilled_fp8_scaled.safetensors',
      ziel: 'hunyuanvideo1.5_480p_t2v_cfg_distilled_fp8_scaled.safetensors', groesse: 8.3,
    }],
  },
  {
    // The file lies in a sub-folder of its repository; the local name carries
    // the family's name, which is how the picture server finds the family.
    id: 'lingbot-video-13b', name: 'LingBot-Video 1.3B', von: 'Robbyant',
    logo: 'R', marke: 'robbyant', bild: true, klasse: 'lingbot_video',
    satz: 'katalog.satz_lingbot_video',
    fassungen: [{
      id: 'robbyant/lingbot-video-dense-1.3b', name: 'safetensors',
      datei: 'transformer/diffusion_pytorch_model.safetensors',
      ziel: 'lingbot-video-dense-1.3b.safetensors', groesse: 2.8,
    }],
  },
]

/* The accessories: small companion files, not models. Each carries a `sorte`
   that decides its column, its tag colour and the folder it lands in
   (ZUBEHOER_ZIEL). `bild: true` reuses the single-file card layout. Every
   repository and file name was checked against Hugging Face; a `ziel` is set
   whenever two repositories name their file the same, and the drafter/projector
   `ziel` names obey the runner's name heuristic so the bond holds without a
   manifest. Names are kept short so a card never wraps. */
const _zub = (id, name, von, logo, sorte, repo, datei, groesse, ziel, klasse) => ({
  id, name, von, logo, marke: null, bild: true, zubehoer: true, sorte,
  // The model class this file belongs to — 'sd15' | 'sdxl', or nothing for
  // the class-neutral kinds (detectors work on any picture; drafters and
  // projectors are bound to their chat model by name instead). The card
  // wears it as a pill, so nobody pairs an SD-1.5 file with an XL model
  // again without noticing (house rule after exactly that mishap).
  ...(klasse ? { klasse } : {}),
  satz: `katalog.satz_zub_${sorte}`,
  // The version is named after the format of its file, as the image models
  // above are: `safetensors`, `gguf`. The format is an identifier, never
  // translated.
  fassungen: [{
    id: repo, name: datei.slice(datei.lastIndexOf('.') + 1), datei,
    ...(ziel ? { ziel } : {}), groesse,
  }],
})

export const KATALOG_ZUBEHOER = [
  // — LoRA —
  _zub('lora-lcm-15', 'LCM', 'Latent Consistency', 'L', 'lora',
    'latent-consistency/lcm-lora-sdv1-5', 'pytorch_lora_weights.safetensors', 0.14, 'lcm-lora-sdv1-5.safetensors', 'sd15'),
  _zub('lora-hyper-15', 'Hyper-SD', 'ByteDance', 'B', 'lora',
    'ByteDance/Hyper-SD', 'Hyper-SD15-8steps-lora.safetensors', 0.27, null, 'sd15'),
  // Krea 2 draws edits only with a LoRA; this one also halves 8 steps to 4.
  { ..._zub('lora-krea2-4step', 'Krea 2 Turbo 4-Step', 'lvladikov', 'K', 'lora',
    'lvladikov/Krea2-Turbo-Distill-4step-LoRA', 'krea2_turbo_4step_rank_64_lora_comfyui.safetensors', 0.44, null, 'krea2'),
    satz: 'katalog.satz_zub_krea2_lora' },
  _zub('lora-light-xl', 'Lightning', 'ByteDance', 'B', 'lora',
    'ByteDance/SDXL-Lightning', 'sdxl_lightning_8step_lora.safetensors', 0.39, null, 'sdxl'),
  // Quality detailers, straight from the author's own repositories.
  _zub('lora-multidet-xl', 'Multi Detailer', 'Stable Yogi', 'Y', 'lora',
    'Stableyogi/Detailers', 'Super_Multi_Detailer_By_Stable_Yogi_A1.safetensors', 0.23, null, 'sdxl'),
  _zub('lora-skindet-15', 'Skin Detailer', 'Stable Yogi', 'Y', 'lora',
    'Stableyogi/Super-Skin-Detailer', 'Super_Skin_Detailer_By_Stable_Yogi_SD0_V1.safetensors', 0.12, null, 'sd15'),
  // — VAE —
  _zub('vae-mse-15', 'MSE', 'Stability AI', 'S', 'vae',
    'stabilityai/sd-vae-ft-mse-original', 'vae-ft-mse-840000-ema-pruned.safetensors', 0.34, null, 'sd15'),
  _zub('vae-ema-15', 'EMA', 'Stability AI', 'S', 'vae',
    'stabilityai/sd-vae-ft-ema-original', 'vae-ft-ema-560000-ema-pruned.safetensors', 0.34, null, 'sd15'),
  _zub('vae-fp16-xl', 'fp16-fix', 'madebyollin', 'M', 'vae',
    'madebyollin/sdxl-vae-fp16-fix', 'sdxl_vae.safetensors', 0.34, 'sdxl-vae-fp16-fix.safetensors', 'sdxl'),
  _zub('vae-orig-xl', 'Original', 'Stability AI', 'S', 'vae',
    'stabilityai/sdxl-vae', 'sdxl_vae.safetensors', 0.34, 'sdxl-vae-original.safetensors', 'sdxl'),
  // Flux's VAE (Z-Image decodes with it too). The repository is gated: the
  // download needs the Hugging Face key.
  { ..._zub('vae-flux-ae', 'Flux AE', 'Black Forest Labs', 'B', 'vae',
    'black-forest-labs/FLUX.1-dev', 'ae.safetensors', 0.34, null, 'flux'),
    satz: 'katalog.satz_zub_flux_ae' },
  // Qwen-Image 2.1 has a VAE of its own; the 1.0 one cannot stand in for it.
  { ..._zub('vae-qwen-image-21', 'Qwen-Image 2.1 VAE', 'Alibaba Qwen', 'Q', 'vae',
    'Comfy-Org/Qwen-Image-2.1', 'vae/qwen_image_2.1_vae_bf16.safetensors', 0.68,
    'qwen_image_2.1_vae_bf16.safetensors', 'qwen_image_2_1'),
    satz: 'katalog.satz_zub_qwen_vae', avatarOwner: 'Qwen' },
  // — ADetailer —
  // The raw Bingsu .pt files use a torch pickle the generator cannot read;
  // the catalogue hands out the same weights repackaged as safetensors from
  // the house repository, so every card downloads a file that actually loads.
  // (The person segmentation model stays out: never converted, never tested.)
  // A detector is named after what it finds, a word of the interface's
  // language: `nameKey` is the catalogue key the card reads instead of `name`.
  { ..._zub('ad-face-n', 'Faces v8n', 'Bingsu', 'B', 'adetailer',
    'exeterminal/adetailer-yolov8-safetensors', 'face_yolov8n.safetensors', 0.01),
    nameKey: 'katalog.name_ad_face_n', avatarOwner: 'Bingsu' },
  { ..._zub('ad-face-s', 'Faces v8s', 'Bingsu', 'B', 'adetailer',
    'exeterminal/adetailer-yolov8-safetensors', 'face_yolov8s.safetensors', 0.02),
    nameKey: 'katalog.name_ad_face_s', avatarOwner: 'Bingsu' },
  { ..._zub('ad-face-m', 'Faces v8m', 'Bingsu', 'B', 'adetailer',
    'exeterminal/adetailer-yolov8-safetensors', 'face_yolov8m.safetensors', 0.05),
    nameKey: 'katalog.name_ad_face_m', avatarOwner: 'Bingsu', satz: 'katalog.satz_ad_face_m' },
  { ..._zub('ad-hand-n', 'Hands v8n', 'Bingsu', 'B', 'adetailer',
    'exeterminal/adetailer-yolov8-safetensors', 'hand_yolov8n.safetensors', 0.01),
    nameKey: 'katalog.name_ad_hand_n', avatarOwner: 'Bingsu' },
  { ..._zub('ad-hand-s', 'Hands v8s', 'Bingsu', 'B', 'adetailer',
    'exeterminal/adetailer-yolov8-safetensors', 'hand_yolov8s.safetensors', 0.02),
    nameKey: 'katalog.name_ad_hand_s', avatarOwner: 'Bingsu', satz: 'katalog.satz_ad_hand_s' },
  { ..._zub('ad-face-n2', 'Faces v8n v2', 'Bingsu', 'B', 'adetailer',
    'exeterminal/adetailer-yolov8-safetensors', 'face_yolov8n_v2.safetensors', 0.01),
    nameKey: 'katalog.name_ad_face_n2', avatarOwner: 'Bingsu', satz: 'katalog.satz_ad_face_n2' },
  // — MTP — the speed module of a chat model. The file names carry the model's
  // name, so the runner pairs each with its model by name.
  { ..._zub('mtp-occamy', 'Occamy MTP', 'Accio', 'A', 'mtp',
    'IsValorum/Occamy-1.0-APEX-I-MiniPlus-V2.1-GGUF', 'occamy-1.0-mtp-Q4_K_M.gguf', 1.3),
    satz: 'katalog.satz_zub_mtp_occamy' },
  { ..._zub('mtp-qwen38', 'Qwen3.8 MTP', 'Unsloth', 'U', 'mtp',
    'unsloth/Qwen3.8-27B-GGUF', 'MTP/mtp-Qwen3.8-27B-Q4_0.gguf', 1.4, 'mtp-Qwen3.8-27B-Q4_0.gguf'),
    satz: 'katalog.satz_zub_mtp_qwen38' },
  { ..._zub('mtp-ornith-9b', 'Ornith MTP-Head', 'protoLabsAI', 'P', 'mtp',
    'protoLabsAI/Ornith-1.5-9B-MTP-GGUF', 'mtp-head/mtp-Ornith-1.5-9B-head-Q8_0.gguf', 2.4,
    'mtp-Ornith-1.5-9B-head-Q8_0.gguf'),
    satz: 'katalog.satz_zub_mtp_ornith' },
  { ..._zub('mtp-gemma-e2b', 'Gemma 4 E2B MTP', 'Unsloth', 'U', 'mtp',
    'unsloth/gemma-4-E2B-it-qat-mobile-GGUF', 'mtp-gemma-4-E2B-it.gguf', 0.06),
    satz: 'katalog.satz_zub_mtp_gemma_e2b' },
  { ..._zub('mtp-gemma-12b', 'Gemma 4 12B MTP', 'Unsloth', 'U', 'mtp',
    'unsloth/gemma-4-12b-it-GGUF', 'mtp-gemma-4-12b-it.gguf', 0.47),
    satz: 'katalog.satz_zub_mtp_gemma_12b' },
  { ..._zub('mtp-nemotron', 'Nemotron MTP', 'ggml-org', 'G', 'mtp',
    'ggml-org/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-GGUF',
    'mtp-NVIDIA-Nemotron-3.5-Lightning-30B-A3B-Q4_0.gguf', 1.2),
    satz: 'katalog.satz_zub_mtp_nemotron' },
  // — Vision (mmproj) — the projector of a chat model, named after the model's
  // own file so the runner pairs the two by name.
  { ..._zub('mmproj-occamy', 'Occamy Vision', 'Accio', 'A', 'mmproj',
    'IsValorum/Occamy-1.0-APEX-I-MiniPlus-V2.1-GGUF', 'mmproj-Accio-Lab_occamy-1.0-Q8_0.gguf', 0.61,
    'Occamy-1.0.APEX-I-MiniPlus-V2.1-mmproj-Q8_0.gguf'),
    satz: 'katalog.satz_zub_mmproj_occamy' },
  { ..._zub('mmproj-gptoss', 'GPT-OSS Vision', 'SoAI', 'S', 'mmproj',
    'SoAIHQ/gpt-oss-20b-VISION-v2-GGUF', 'mmproj-gpt-oss-20b-VISION-v2-f16.gguf', 0.65,
    'gpt-oss-20b-VISION-v2-mmproj-f16.gguf'),
    satz: 'katalog.satz_zub_mmproj_gptoss' },
  { ..._zub('mmproj-qwen38', 'Qwen3.8 Vision', 'Qwen', 'Q', 'mmproj',
    'ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF', 'mmproj-Qwen3.8-27B-BF16.gguf', 0.93,
    'Qwen3.8-27B-mmproj-BF16.gguf'),
    satz: 'katalog.satz_zub_mmproj_qwen38', avatarOwner: 'Qwen' },
  { ..._zub('mmproj-ornith-9b', 'Ornith 9B Vision', 'Ornith AI', 'O', 'mmproj',
    'ornith-ai/Ornith-1.5-9B-GGUF', 'mmproj-Ornith-1.5-9B-BF16.gguf', 0.92,
    'Ornith-1.5-9B-mmproj-BF16.gguf'),
    satz: 'katalog.satz_zub_mmproj_ornith_9b' },
  { ..._zub('mmproj-ornith-35b', 'Ornith 35B Vision', 'Ornith AI', 'O', 'mmproj',
    'ornith-ai/Ornith-1.5-35B-A3B-GGUF', 'mmproj-Ornith-1.5-35B-BF16.gguf', 0.9,
    'Ornith-1.5-35B-mmproj-BF16.gguf'),
    satz: 'katalog.satz_zub_mmproj_ornith_35b' },
  { ..._zub('mmproj-gemma-12b', 'Gemma 4 12B Vision', 'Google', 'G', 'mmproj',
    'unsloth/gemma-4-12b-it-GGUF', 'mmproj-F16.gguf', 0.18, 'gemma-4-12b-it-mmproj-F16.gguf'),
    satz: 'katalog.satz_zub_mmproj_gemma_12b', avatarOwner: 'google' },
]

/* The speech catalogue — models the speech server can load. Nothing ships
   with the program: the folder starts empty and this list stands beside it,
   exactly the arrangement the embedding server has.

   Each build carries its projector, because for a speech model that file is
   not an accessory but the other half of the thing — without it the model
   cannot hear at all. The local name is what the runner's pairing reads, so
   `mmproj_ziel` puts the model's own name in front of the word: a bare
   `mmproj-….gguf` belongs to nothing as far as the pairing is concerned.

   Every repository, file name and size checked against Hugging Face when
   this list was written. */
export const KATALOG_SPRACHE = [
  {
    id: 'asr-qwen3-06', name: 'Qwen3-ASR 0.6B', von: 'Alibaba',
    logo: 'Q', marke: 'qwen', faehigkeiten: [], kontext: 4096,
    satz: 'katalog.satz_asr_qwen3_06',
    fassungen: [{
      id: 'unslothai/Qwen3-ASR-0.6B-GGUF', name: '8-Bit · Q8_0',
      datei: 'Qwen3-ASR-0.6B-Q8_0.gguf', groesse: 0.8,
      mmproj: 'mmproj-Qwen3-ASR-0.6B-Q8_0.gguf',
      mmproj_ziel: 'Qwen3-ASR-0.6B-Q8_0-mmproj-Q8_0.gguf',
    }],
  },
  {
    id: 'asr-qwen3-17', name: 'Qwen3-ASR 1.7B', von: 'Alibaba',
    logo: 'Q', marke: 'qwen', faehigkeiten: [], kontext: 4096,
    satz: 'katalog.satz_asr_qwen3_17',
    fassungen: [{
      id: 'ggml-org/Qwen3-ASR-1.7B-GGUF', name: '8-Bit · Q8_0',
      datei: 'Qwen3-ASR-1.7B-Q8_0.gguf', groesse: 2.2,
      mmproj: 'mmproj-Qwen3-ASR-1.7B-Q8_0.gguf',
      mmproj_ziel: 'Qwen3-ASR-1.7B-Q8_0-mmproj-Q8_0.gguf',
    }],
  },
  {
    id: 'asr-voxtral-3b', name: 'Voxtral Mini 3B', von: 'Mistral AI',
    logo: 'M', marke: 'mistral', faehigkeiten: [], kontext: 4096,
    satz: 'katalog.satz_voxtral_3b',
    fassungen: [{
      id: 'ggml-org/Voxtral-Mini-3B-2507-GGUF', name: '4-Bit · Q4_K_M',
      datei: 'Voxtral-Mini-3B-2507-Q4_K_M.gguf', groesse: 2.5,
      mmproj: 'mmproj-Voxtral-Mini-3B-2507-Q8_0.gguf',
      mmproj_ziel: 'Voxtral-Mini-3B-2507-Q4_K_M-mmproj-Q8_0.gguf',
    }],
  },
  {
    id: 'tts-qwen3-17b', name: 'Qwen3-TTS-12Hz 1.7B Base', von: 'Alibaba',
    logo: 'Q', marke: 'qwen', faehigkeiten: [], kontext: 4096,
    satz: 'katalog.satz_tts_qwen3_17',
    fassungen: [{
      id: 'ggml-org/Qwen3-TTS-12Hz-1.7B-Base-GGUF', name: '4-Bit · Q4_K_M',
      datei: 'Qwen3-TTS-12Hz-1.7B-Base-Q4_K_M.gguf', groesse: 1.0,
      mmproj: 'mmproj-Qwen3-TTS-12Hz-1.7B-Base-Q8_0.gguf',
      mmproj_ziel: 'Qwen3-TTS-12Hz-1.7B-Base-Q4_K_M-mmproj-Q8_0.gguf',
    }],
  },
  /* The voices of Serveurperso's repository: one repository for the four
     talkers, and a shared tokenizer file that is the other half of each, so it
     comes beside the voice under the voice's own name. */
  {
    id: 'tts-qwen3-06b-base', name: 'Qwen3-TTS 0.6B Base', von: 'Alibaba',
    logo: 'Q', marke: 'qwen', faehigkeiten: [], kontext: 4096,
    satz: 'katalog.satz_tts_qwen3_06_base',
    fassungen: [{
      id: 'Serveurperso/Qwen3-TTS-GGUF', name: '4-Bit · Q4_K_M',
      datei: 'qwen-talker-0.6b-base-Q4_K_M.gguf', groesse: 0.63,
      mmproj: 'qwen-tokenizer-12hz-Q8_0.gguf',
      mmproj_ziel: 'qwen-talker-0.6b-base-Q4_K_M-mmproj-Q8_0.gguf',
    }],
  },
  {
    id: 'tts-qwen3-06b-custom', name: 'Qwen3-TTS 0.6B CustomVoice', von: 'Alibaba',
    logo: 'Q', marke: 'qwen', faehigkeiten: [], kontext: 4096,
    satz: 'katalog.satz_tts_qwen3_06_custom',
    fassungen: [{
      id: 'Serveurperso/Qwen3-TTS-GGUF', name: '4-Bit · Q4_K_M',
      datei: 'qwen-talker-0.6b-customvoice-Q4_K_M.gguf', groesse: 0.6,
      mmproj: 'qwen-tokenizer-12hz-Q8_0.gguf',
      mmproj_ziel: 'qwen-talker-0.6b-customvoice-Q4_K_M-mmproj-Q8_0.gguf',
    }],
  },
  {
    id: 'tts-qwen3-17b-custom', name: 'Qwen3-TTS 1.7B CustomVoice', von: 'Alibaba',
    logo: 'Q', marke: 'qwen', faehigkeiten: [], kontext: 4096,
    satz: 'katalog.satz_tts_qwen3_17_custom',
    fassungen: [{
      id: 'Serveurperso/Qwen3-TTS-GGUF', name: '4-Bit · Q4_K_M',
      datei: 'qwen-talker-1.7b-customvoice-Q4_K_M.gguf', groesse: 1.2,
      mmproj: 'qwen-tokenizer-12hz-Q8_0.gguf',
      mmproj_ziel: 'qwen-talker-1.7b-customvoice-Q4_K_M-mmproj-Q8_0.gguf',
    }],
  },
  {
    id: 'tts-qwen3-17b-design', name: 'Qwen3-TTS 1.7B VoiceDesign', von: 'Alibaba',
    logo: 'Q', marke: 'qwen', faehigkeiten: [], kontext: 4096,
    satz: 'katalog.satz_tts_qwen3_17_design',
    fassungen: [{
      id: 'Serveurperso/Qwen3-TTS-GGUF', name: '4-Bit · Q4_K_M',
      datei: 'qwen-talker-1.7b-voicedesign-Q4_K_M.gguf', groesse: 1.2,
      mmproj: 'qwen-tokenizer-12hz-Q8_0.gguf',
      mmproj_ziel: 'qwen-talker-1.7b-voicedesign-Q4_K_M-mmproj-Q8_0.gguf',
    }],
  },
  {
    id: 'asr-voxtral-4b-realtime', name: 'Voxtral Mini 4B Realtime', von: 'Mistral AI',
    logo: 'M', marke: 'mistral', faehigkeiten: [], kontext: 4096,
    satz: 'katalog.satz_voxtral_4b_realtime',
    fassungen: [{
      id: 'ggml-org/Voxtral-Mini-4B-Realtime-2602-GGUF', name: '4-Bit · Q4_K_M',
      datei: 'Voxtral-Mini-4B-Realtime-2602-Q4_K_M.gguf', groesse: 2.6,
      mmproj: 'mmproj-Voxtral-Mini-4B-Realtime-2602-Q8_0.gguf',
      mmproj_ziel: 'Voxtral-Mini-4B-Realtime-2602-Q4_K_M-mmproj-Q8_0.gguf',
    }],
  },
  {
    // The projector's local name begins with the model file's name: that is how
    // it is paired with the model.
    id: 'asr-voxtral-small-24b', name: 'Voxtral Small 24B', von: 'Mistral AI',
    logo: 'M', marke: 'mistral', faehigkeiten: [], kontext: 32768,
    satz: 'katalog.satz_voxtral_24b',
    fassungen: [{
      id: 'bartowski/mistralai_Voxtral-Small-24B-2507-GGUF', name: '4-Bit · Q4_K_M',
      datei: 'mistralai_Voxtral-Small-24B-2507-Q4_K_M.gguf', groesse: 14.3,
      mmproj: 'mmproj-mistralai_Voxtral-Small-24B-2507-f16.gguf',
      mmproj_ziel: 'mistralai_Voxtral-Small-24B-2507-Q4_K_M-mmproj-f16.gguf',
    }],
  },
]

/* One table carries all lists, keyed by the same names as ARTEN — so the tabs,
   the lookup and the per-kind data cannot disagree. */
const KATALOGE = {
  chat: KATALOG, einbettung: KATALOG_EINBETTUNG, sprache: KATALOG_SPRACHE,
  bild: KATALOG_BILD, video: KATALOG_VIDEO, zubehoer: KATALOG_ZUBEHOER,
}

/** The curated list for a catalogue tab — what `Katalog.svelte` shows when
    that tab is open. Falls back to the chat list for an unknown key so a
    typo never renders an empty gallery silently. */
export const katalogFuer = (art) => KATALOGE[art] ?? KATALOG

/** The memory a build needs to run at the everyday context, in GB. */
export function bedarf(fassung) {
  const beifahrer = fassung.drafter ? DRAFTER_GB : 0
  return speicherSchaetzung(fassung.groesse, STANDARD_KONTEXT, beifahrer).gesamt
}

/** Does this build run comfortably on a machine with this much memory? */
export function passt(fassung, gigabyte) {
  return gigabyte != null && bedarf(fassung) <= gigabyte
}

/** The smallest standard machine size that runs this build. */
export function brauchtMaschine(fassung) {
  const b = bedarf(fassung)
  return MASCHINEN.find((m) => m >= b) ?? MASCHINEN[MASCHINEN.length - 1]
}

/** The build to pre-pick for a machine: the best (largest) that fits, or —
    when none fits — the smallest, so the choice is honest rather than
    empty. */
export function passendeFassung(karte, gigabyte) {
  const passend = karte.fassungen.filter((f) => passt(f, gigabyte))
  const pool = passend.length ? passend : karte.fassungen
  const groesser = passend.length
    ? (a, b) => (b.groesse > a.groesse ? b : a)
    : (a, b) => (b.groesse < a.groesse ? b : a)
  return pool.reduce(groesser)
}

/** Does the card fit the machine at all — has it a build that runs? */
export function kartePasst(karte, gigabyte) {
  return karte.fassungen.some((f) => passt(f, gigabyte))
}

/** The one card to suggest for a fresh machine: the most capable that
    fits, so the first model is the best the machine can carry — the same
    call the onboarding makes. Returns { karte, fassung } or null.

    Builds marked `notnagel` (the 2-bit last resorts) never carry the
    recommendation: a card may offer them for a hand-picked download, but
    the machine's FIRST model must not be a quant its own card warns
    about. */
export function empfehlungFuer(gigabyte) {
  const empfehlbar = (karte) => ({
    ...karte,
    fassungen: karte.fassungen.filter((f) => !f.notnagel),
  })
  const kandidaten = KATALOG.map(empfehlbar).filter((k) => k.fassungen.length)
  const passend = kandidaten.filter((k) => kartePasst(k, gigabyte))
  const pool = passend.length ? passend : kandidaten
  let beste = null
  for (const karte of pool) {
    const fassung = passendeFassung(karte, gigabyte)
    if (!beste || fassung.groesse > beste.fassung.groesse) beste = { karte, fassung }
  }
  return beste
}

/** Kept as a pure recommender: the card recommended for this much memory.
    The onboarding reads it to name a first model for the machine. */
export function stufeFuer(gigabyte) {
  return empfehlungFuer(gigabyte)?.karte ?? null
}
