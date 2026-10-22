/* Option lists the picture window and the picture server's per-model values
   share, so both offer the same choices.

   sd-cli's own `--prediction` override names (app/bildwahlen.py,
   PREDICTION_WERTE); "auto" sends no flag and lets the program read the
   type from the model. */
export const PREDICTIONEN = [
  'eps', 'v', 'edm_v', 'sd3_flow', 'flux_flow', 'sefi_flow',
  'minit2i_flow', 'sensenova_u1_flow',
]

/* What a tiny autoencoder (TAE) of the `taesd` folder is called where a VAE is
   chosen: its file name behind this word (app/bildbausatz.py, TAE_PREFIX), so
   a name of one folder is never taken for a name of the other. */
export const TAE_PREFIX = 'taesd:'
export const istTae = (name) => typeof name === 'string' && name.startsWith(TAE_PREFIX)
