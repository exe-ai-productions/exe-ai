/*
  Which script was picked off the wall, so the schedule form can fill itself
  in with it.

  The wall and the form used to sit in one block, and a click could reach
  straight into a variable beside it. They are two sections of the rail now,
  each with its own seam — the wall can be pulled open while the form stays
  small, or the other way round — and two sections cannot see each other's
  state. This is the one thing they have to share, so it is the only thing
  in here.

  A COUNT rather than a flag, and that is the whole design: clicking the same
  script twice has to open the form twice. A boolean would be true already
  the second time and nothing would happen — which is exactly how a click
  that "sometimes does nothing" gets built.
*/

export const skriptwahl = $state({
  /* The file name, exactly as it stands in the folder. */
  name: '',
  /* Bumped on every pick, including a repeat of the same name. */
  lauf: 0,
})

export function skriptWaehlen(name) {
  skriptwahl.name = name
  skriptwahl.lauf += 1
}

/* The pick is spent once the form it opened is closed — saved or cancelled.
   Left standing, it opened the next form by itself and kept its ring on the
   wall long after the schedule was made. */
export function skriptWahlLeeren() {
  skriptwahl.name = ''
}
