/* What an ended run wrote, for a row that unfolds onto it.

   `job` is a job as the job route hands it out. The answer carries the
   steps of its transcript, and its result where the transcript does not say
   it already. An agent's result is its sentences, round after round, written
   as one text — the transcript shows every one of them, so the result is
   not said a second time. A result that is no sentence stands as text: a
   script's output, or the closing text of a run that was handed on. */
export function runReport(job) {
  const steps = job?.schritte ?? []
  const result = String(job?.result ?? '').trim()
  const sentences = steps
    .filter((step) => step.typ === 'text')
    .map((step) => String(step.inhalt))
    .join('')
  return { steps, text: sentences.trim() === result ? '' : result }
}
