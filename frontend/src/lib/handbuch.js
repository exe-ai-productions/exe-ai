/*
  The manual: where "Help" leads until the help of its own arrives.

  A plain window.open — in a browser tab it opens a tab, and the desktop
  shell (fenster-electron/main.js) catches the address and gives the manual
  a window of its own, raising it on a second click instead of stacking
  another.
*/
export function handbuchOeffnen() {
  window.open('/help/', '_blank')
}
