/* Which pictures the studio's row of pictures shows (StudioGallery.svelte).
   The original — the picture that last came from outside — stands on top,
   open or shut. Open, the studio's pictures follow, newest first; shut, one
   stays: the picture drawing now (it has its tile above), or else the
   newest. The original is never shown twice. */
export function rowPictures({ original, names, open, running }) {
  const rest = names.filter((name) => name !== original)
  return { original: original || '', pictures: open ? rest : running ? [] : rest.slice(0, 1) }
}
