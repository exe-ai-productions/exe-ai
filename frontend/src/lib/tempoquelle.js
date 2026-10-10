/*
  Where a speed reading came from, and what it therefore counted.

  The tokens-per-second figure stands in the foot under an answer
  (Nachricht.svelte): live while it runs, measured once it is done. Which
  readings may be shown at all, and what each one says it measured, stand
  here once.
*/

/* Only a reading that was MEASURED may be shown: the service reports no
   speed for a counted-chunks run, and a chunk is not a token. A name is
   cheaper to check than to trust — anything not on this list carries no
   figure a display may show, whatever number travels beside it. */
export const TEMPO_QUELLEN = ['server', 'gemessen']

export function tempoGemessen(quelle) {
  return TEMPO_QUELLEN.includes(quelle)
}

/* The `server` tier measures the WHOLE generation, the chain of thought
   included; everything else measures the writing of the answer. The figure
   stays as it is — what it counts is said beside it. */
export function tempoTitelSchluessel(quelle) {
  return quelle === 'server' ? 'eingabe.tps_titel_server' : 'eingabe.tps_titel_antwort'
}
