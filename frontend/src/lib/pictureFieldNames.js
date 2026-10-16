/* The words for the dials of a picture, as the terminal's picture card
   shows them.

   A drawing request names its fields the way the service does (`hoehe`,
   `diffusion_model`, `hires_width`). The studio and the picture server
   already carry a word for almost every one of them; a few are filed under
   another name (`hires_width` stands as `bild.hires_breite`), a few in the
   studio's own group. This file is the table from field to that word and
   nothing else: it makes no word of its own.

   Every key stands here as a whole string, so the catalogue guard sees each
   one being read. A field with no word anywhere stays under its own name
   (the caller gets the field back) and is listed in `WITHOUT_LABEL`, so
   a new field of the request cannot slip in unseen
   (tests/test_picture_card_terminal.py).
*/

/* Field -> the catalogue key that says it. */
export const FIELD_WORD = {
  ad_confidence: 'bild.ad_confidence',
  ad_loras: 'bild.ad_lora',
  ad_modell: 'bild.adetailer',
  ad_negativ: 'bild.ad_negativ',
  ad_prompt: 'bild.ad_prompt',
  audio_encoder: 'bild.audio_encoder',
  audio_vae: 'bild.audio_vae',
  breite: 'bild.breite',
  canny: 'bild.canny',
  cfg: 'bild.cfg',
  clip_g: 'bild.clip_g',
  clip_l: 'bild.clip_l',
  clip_skip: 'bild.clip_skip',
  control_net: 'bild.control_net',
  control_strength: 'bild.control_strength',
  diffusion_model: 'bild.diffusion_model',
  embeddings_connectors: 'bild.embeddings_connectors',
  end_bild: 'bild.letztes_bild',
  eta: 'bild.eta',
  extra_sample_args: 'bild.extra_sample_args',
  familie: 'bild.familie',
  flow_shift: 'bild.flow_shift',
  fps: 'bild.fps',
  guidance: 'bild.guidance',
  hires: 'bild.hires',
  hires_denoise: 'bild.hires_denoise',
  hires_height: 'bild.hires_hoehe',
  hires_scale: 'studio.hires_faktor',
  hires_steps: 'bild.hires_steps',
  hires_upscaler: 'bild.hires_upscaler',
  hires_width: 'bild.hires_breite',
  hoehe: 'bild.hoehe',
  img_cfg: 'bild.img_cfg',
  increase_ref_index: 'bild.increase_ref_index',
  live_preview: 'bild.live_preview',
  llm: 'bild.llm',
  llm_vision: 'bild.llm_vision',
  lora_apply_mode: 'bild.lora_modus',
  loras: 'bild.lora',
  maske: 'studio.maske',
  mode: 'bild.art',
  model_args: 'bild.model_args',
  modell: 'bild.modell',
  negativ: 'bild.negativ',
  prediction: 'bild.prediction',
  preview_interval: 'bild.preview_interval',
  preview_noisy: 'bild.preview_noisy',
  pulid_id_embedding: 'bild.pulid_embedding',
  pulid_id_weight: 'bild.pulid_id_weight',
  pulid_weights: 'bild.pulid',
  ref_bilder: 'studio.referenzbilder',
  ref_image_args: 'bild.ref_image_args',
  rng: 'bild.rng',
  sampler: 'bild.sampler',
  scheduler: 'bild.scheduler',
  schritte: 'bild.schritte',
  seed: 'bild.seed',
  sigmas: 'bild.sigmas',
  skip_layer_end: 'bild.skip_layer_end',
  skip_layer_start: 'bild.skip_layer_start',
  skip_layers: 'bild.skip_layers',
  slg_scale: 'bild.slg_scale',
  staerke: 'bild.staerke',
  startbild: 'bild.startbild',
  stil_text: 'studio.stil',
  t5xxl: 'bild.t5xxl',
  taesd: 'bild.taesd',
  tokenizer: 'bild.tokenizer',
  uncond_diffusion_model: 'bild.uncond_modell',
  upscale_model: 'bild.upscaler',
  vae: 'bild.vae',
  vae_format: 'bild.vae_format',
  video_frames: 'bild.video_frames',
  weight_type: 'bild.weight_type',
}

/* Fields no catalogue key says yet. Their own name stands in the card. */
export const WITHOUT_LABEL = [
  'control_image',
  'high_noise_diffusion_model',
  'pm_klasse',
  'ref_video_frames',
  'steuerbilder',
  'stil_negativ',
  'switches',
  'video',
]

/** The word to show for a field of a picture request. `t` is the catalogue
 *  lookup, which hands back the key itself for one it does not know; a field
 *  the table does not name stands under its own name. */
export function pictureFieldName(field, t) {
  if (!Object.hasOwn(FIELD_WORD, field)) return field
  const key = FIELD_WORD[field]
  const word = t(key)
  return word === key ? field : word
}
