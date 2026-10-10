/* A press anywhere outside `knoten` calls `zu` — for the studio's small
   lists and menus that shut on a click elsewhere. Svelte action:
   `use:draussen={() => (offen = false)}`. */
export function draussen(knoten, zu) {
  let rufe = zu
  const hoeren = (ereignis) => {
    if (!knoten.contains(ereignis.target)) rufe?.()
  }
  window.addEventListener('pointerdown', hoeren, true)
  return {
    update: (neu) => (rufe = neu),
    destroy: () => window.removeEventListener('pointerdown', hoeren, true),
  }
}
