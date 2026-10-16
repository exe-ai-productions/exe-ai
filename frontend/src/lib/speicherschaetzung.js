/* A rough answer to "will this fit?" before the server starts.

   The model needs its file size in memory. The conversation on top — the
   KV cache — grows with context length AND with model size; the factor
   below is a rule of thumb calibrated against published f16 cache sizes:
   roughly 8 KB per token of context for every gigabyte of model file. It
   is an estimate and is shown as one — the point is the order of
   magnitude, not the decimal.

   Two things stand on top of it. With the 8-bit cache the same conversation
   takes a bit more than half: measured at the engine's own start line, one
   model (28 layers) and one window (8192 tokens), once with the f16 cache
   and once with 8-bit — 896 MiB against 476 MiB, so 476 / 896. And a vision
   projector is a passenger like the draft: its file size, in full. */
export const EIGHT_BIT_CACHE_SHARE = 476 / 896

/* Whether a stored cache type is the 8-bit step. The older, smaller step the
   engine's levers once offered counts as it (app/feineinstellungen.py
   `KV_ALT`): whoever stored it was saving memory on purpose. */
export function isEightBitCache(kvCache) {
  return kvCache === 'q8_0' || kvCache === 'q4_0'
}

export function speicherSchaetzung(
  modellGb,
  kontext,
  drafterGb = 0,
  { eightBit = false, projectorGb = 0 } = {},
) {
  const kv = ((kontext * 8 * modellGb) / 1e6) * (eightBit ? EIGHT_BIT_CACHE_SHARE : 1)
  return {
    modell: modellGb,
    drafter: drafterGb,
    projector: projectorGb,
    kv,
    gesamt: modellGb + drafterGb + projectorGb + kv,
  }
}

/* One server's share of that answer, from the files it can see and the
   choice standing in front of it.

   Both server pages asked this same question with the same four lines, and
   the window's head now asks it a third and fourth time for whichever page
   is NOT open — the two servers run at once, on the same memory, so the head
   has to carry both whether or not anybody is looking at them. Four copies
   of one calculation is how two of them end up disagreeing, and a head that
   disagrees with the form below it is worse than a head that says nothing.

   Null means "nothing to add here": no file chosen, none of that name in the
   folder, or no window to hold a conversation in. */
export function serverAnteil(
  dateien,
  module,
  { modell, kontext, drafter, eightBit = false, vision = '', projectors = {} } = {},
) {
  const haupt = (dateien ?? []).find((m) => m.name === modell)
  if (!haupt || !kontext) return null
  const beifahrer =
    (dateien ?? []).find((m) => m.name === drafter)
    ?? (module ?? []).find((m) => m.name === drafter)
  const projectorGb = vision ? (projectors?.[vision] ?? 0) : 0
  return speicherSchaetzung(haupt.groesse_gb, kontext, beifahrer?.groesse_gb ?? 0, {
    eightBit,
    projectorGb,
  })
}
