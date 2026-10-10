/*
  What a running answer is doing right now, and since when.

  The stream writes a placeholder's activity ('kontext', 'denkt',
  'werkzeug', 'schreibt') on nearly every event it reads. The waiting mark
  counts its clock from `taetigkeitSeit` (App.svelte, laufMarke), so when
  that start is reset is a rule of its own, kept here once: a new activity
  starts the clock afresh; the same one again leaves it running, unless the
  event itself begins a new stretch (`neu`: a tool starts running, a tool
  result hands the grown context back — each a fresh stretch even straight
  after the same activity). Without a time
  from the service, the moment of reading stands in.
*/

export function taetigkeitSetzen(zeile, art, seit, neu = false) {
  if (neu || zeile.taetigkeit !== art) zeile.taetigkeitSeit = seit ?? Date.now()
  zeile.taetigkeit = art
}
