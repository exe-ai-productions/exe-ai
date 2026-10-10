/* A rough answer to "will this fit?" before the server starts.

   The model needs its file size in memory. The conversation on top — the
   KV cache — grows with context length AND with model size; the factor
   below is a rule of thumb calibrated against published f16 cache sizes:
   roughly 8 KB per token of context for every gigabyte of model file. It
   is an estimate and is shown as one — the point is the order of
   magnitude, not the decimal. */
export function speicherSchaetzung(modellGb, kontext, drafterGb = 0) {
  const kv = (kontext * 8 * modellGb) / 1e6
  return {
    modell: modellGb,
    drafter: drafterGb,
    kv,
    gesamt: modellGb + drafterGb + kv,
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
export function serverAnteil(dateien, module, { modell, kontext, drafter } = {}) {
  const haupt = (dateien ?? []).find((m) => m.name === modell)
  if (!haupt || !kontext) return null
  const beifahrer =
    (dateien ?? []).find((m) => m.name === drafter)
    ?? (module ?? []).find((m) => m.name === drafter)
  return speicherSchaetzung(haupt.groesse_gb, kontext, beifahrer?.groesse_gb ?? 0)
}
