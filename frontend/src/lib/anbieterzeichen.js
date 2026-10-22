/*
  Which embedded mark a search hit carries.

  The mark answers what model family a hit is, not who uploaded it: people
  search by family name, and most GGUF builds come from quantisers — a Qwen
  build under an unsloth name still reads as Qwen. The small line under the
  model name keeps naming the publisher, so nobody is claimed to be the
  maker. Only families with an original vector in lib/logos.js appear here;
  everything else stays the honest dashed letter, a mark is never guessed.

  Matched against name and publisher in one pass: the family word usually
  sits in the model name, and for first-party repositories it is the
  organisation name itself.
*/

import { LOGOS } from './logos.js'

/* Mistral names its sizes and trades by their own words, all of one
   house. List order decides nothing — see the position rule below. The
   long words may sit anywhere in a name (codellama, tinyllama); the short
   ones marked strict must start the name or follow a separator, because
   they hide inside other words — "phi-" inside Delphi, "ibm-" inside
   libm. A bare "meta" stays out entirely, it would claim MetaMath. */
const FAMILIEN = [
  ['qwen', 'qwen'],
  ['qwq', 'qwen'],
  ['qvq', 'qwen'],
  ['deepseek', 'deepseek'],
  ['mistral', 'mistral'],
  ['mixtral', 'mistral'],
  ['ministral', 'mistral'],
  ['magistral', 'mistral'],
  ['devstral', 'mistral'],
  ['codestral', 'mistral'],
  ['mathstral', 'mistral'],
  ['pixtral', 'mistral'],
  ['gemma', 'google'],
  ['llama', 'meta'],
  ['phi-', 'microsoft', true],
  ['phi3', 'microsoft', true],
  ['phi4', 'microsoft', true],
  ['bitnet', 'microsoft'],
  ['microsoft', 'microsoft'],
  ['gpt-oss', 'openai'],
  ['gpt2', 'openai', true],
  ['gpt-2', 'openai', true],
  ['whisper', 'openai'],
  ['openai', 'openai'],
  ['granite', 'ibm'],
  ['ibm-', 'ibm', true],
  ['smollm', 'huggingface'],
  ['smolvlm', 'huggingface'],
  ['kimi', 'kimi'],
  ['moonshot', 'kimi'],
  ['cohere', 'cohere'],
  ['command-r', 'cohere'],
  ['c4ai', 'cohere'],
  ['aya-', 'cohere', true],
  ['glm', 'zhipu'],
  ['zhipu', 'zhipu'],
  ['zai-org', 'zhipu'],
  ['grok', 'grok'],
  ['nemotron', 'nvidia'],
  ['nvidia', 'nvidia'],
  ['bonsai', 'prism'],
  ['prism', 'prism'],
  ['olmo', 'allenai', true],
  ['molmo', 'allenai'],
  ['tulu', 'allenai', true],
  ['allenai', 'allenai'],
  ['openelm', 'apple'],
  ['fastvlm', 'apple'],
  ['apple', 'apple', true],
  ['mimo', 'xiaomi', true],
  ['xiaomi', 'xiaomi'],
  ['exaone', 'lg'],
  ['occamy', 'accio'],
  ['hermes', 'nous'],
  ['nous', 'nous', true],
  // The picture and video makers: the owner's name on Hugging Face, as the
  // hit's name or publisher says it.
  ['stabilityai', 'stabilityai'],
  ['black-forest-labs', 'black-forest-labs'],
  ['krea', 'krea', true],
  ['lightricks', 'lightricks'],
  ['tencent', 'tencent'],
  ['minimaxai', 'minimaxai'],
  ['baidu', 'baidu'],
  ['meituan-longcat', 'meituan-longcat'],
  ['ideogram-ai', 'ideogram-ai'],
  ['sensenova', 'sensenova'],
  ['tongyi-mai', 'tongyi-mai'],
  ['openmoss', 'openmoss-team'],
  ['speridlabs', 'speridlabs'],
  ['boogu', 'boogu', true],
  ['pixart', 'pixart-alpha'],
  ['robbyant', 'robbyant'],
  ['purplesmartai', 'purplesmartai'],
  ['stableyogi', 'stableyogi'],
  ['rundiffusion', 'rundiffusion'],
  ['wan-ai', 'wan-ai'],
  ['aidc-ai', 'aidc-ai'],
]

/* The first occurrence a strict word may count is one at a word start —
   the beginning, or right after a character that separates words. */
function stelleVon(heu, wort, streng) {
  let von = 0
  for (;;) {
    const i = heu.indexOf(wort, von)
    if (i < 0) return -1
    if (!streng || i === 0 || !/[a-z0-9]/.test(heu[i - 1])) return i
    von = i + 1
  }
}

/** The embedded mark for a model name plus publisher, or null. The
    earliest family word in the name wins: a DeepSeek distill onto a Qwen
    base names DeepSeek first and is DeepSeek's model, not Qwen's. */
export function modellMarke(name, anbieter) {
  const heu = `${name || ''} ${anbieter || ''}`.toLowerCase()
  let beste = null
  for (const [wort, marke, streng] of FAMILIEN) {
    const stelle = stelleVon(heu, wort, streng)
    if (stelle >= 0 && (beste === null || stelle < beste.stelle)) beste = { stelle, marke }
  }
  return beste ? LOGOS[beste.marke] : null
}

/* Picture and video families whose maker their name does not say: Microsoft
   publishes Lens and Mage-Flow, Stability AI the Stable Diffusion line.
   Families without a vector of their maker are not listed and stay the
   letter. Keyed by the family's own name
   (app/image_families.py); a family not listed is matched by its label, like
   a search hit. */
const BILDFAMILIEN = {
  lens: 'microsoft',
  mage_flow: 'microsoft',
  sd15: 'stabilityai',
  sd2: 'stabilityai',
  sdxl: 'stabilityai',
  sd3: 'stabilityai',
  sdxl_pix2pix: 'stabilityai',
  flux: 'black-forest-labs',
  flux2: 'black-forest-labs',
  flux2_klein: 'black-forest-labs',
  flux3_klein: 'black-forest-labs',
  sdxs: 'xiaomi',
  pid: 'nvidia',
  moss_image: 'openmoss-team',
  iris: 'speridlabs',
  zimage: 'tongyi-mai',
  krea2: 'krea',
  sensenova_u1: 'sensenova',
  longcat: 'meituan-longcat',
  ernie: 'baidu',
  boogu: 'boogu',
  ideogram4: 'ideogram-ai',
  pixart: 'pixart-alpha',
  ltx: 'lightricks',
  minimax_h3: 'minimaxai',
  hunyuan_video: 'tencent',
  lingbot_video: 'robbyant',
  wan: 'wan-ai',
  wan22_i2v: 'wan-ai',
  wan22_ti2v: 'wan-ai',
  wan22_s2v: 'wan-ai',
  ovis: 'aidc-ai',
}

/** The embedded mark of a picture family, or null. The family's mark, never
    the mark of whoever fine-tuned or uploaded a file of it. */
export function bildFamilienMarke(name, label) {
  const marke = BILDFAMILIEN[name]
  return marke ? LOGOS[marke] : modellMarke(label, '')
}
