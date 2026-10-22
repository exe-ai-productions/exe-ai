/*
  What a server page hands up to the head of its page (ModelleLokal.svelte): its
  start button, the short line beside its name and its port.

  Every server page keeps these three itself — it is the one that knows whether
  its server runs and how it is started. The head only draws them. The page
  names itself (`page` is the name of its entry in the settings list), so what
  a page left behind is never taken for the next one's, and it takes its
  entry back when it goes, so a button of a page that no longer exists cannot
  be pressed.

  Called while a page is being set up:

    serverHead('bild', (value) => (head = value), () => ({ tat, line: '', port }))
*/

/**
 * @param {string} page   the name of the page's entry in the settings list
 * @param {(value: object | null) => void} set   hands the value up
 * @param {() => { tat: object | null, line: string, port: number | null }} read
 */
export function serverHead(page, set, read) {
  $effect(() => {
    set({ page, ...read() })
  })
  $effect(() => () => set(null))
}
