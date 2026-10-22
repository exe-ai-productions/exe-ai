/*
  Whether the work bar stands open over the chat, and on which tool. Its own
  piece of state: the desktop's column keeps its tool in a saved layout that
  a phone must not write.
*/
import { pickTab } from './work.js'

export const work = $state({ open: false, tab: 'terminal' })

export function workOpen(tab) {
  if (tab) work.tab = pickTab(tab)
  work.open = true
}

export function workClose() {
  work.open = false
}

export function workTab(name) {
  work.tab = pickTab(name)
}
