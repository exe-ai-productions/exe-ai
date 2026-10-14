/*
  How the run behind an answer ended.

  `fertig`, `abgebrochen` or `fehler` — `laeuft` while it is still going,
  and nothing for a row no run stands behind. The column says it; a message
  stored before the column existed says it only in its metrics blob, so the
  blob is read where the column is empty and such a message keeps saying
  what it always said.

  One fact, one file: the bubble draws its state from it, the arrow under
  the last answer takes its label from it — "Regenerate" or, under a failed
  answer, "Try again" — and the press reads it again to decide which of the
  two requests goes out. The service reads a row the same way
  (app/answer_redo.py), so the window and the service never disagree about
  which answer is a failed one.
*/
export function answerEnding(nachricht) {
  const stats = nachricht?.stats || {}
  return nachricht?.zustand
    ?? (stats.fehler ? 'fehler' : stats.abgebrochen ? 'abgebrochen' : null)
}
