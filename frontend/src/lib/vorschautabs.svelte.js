/*
  The tabs of the preview module: which files this chat produced.

  A file the model writes used to open a window over the whole program. That
  window is fine for one look at one file, and wrong for the way people
  actually work — building a page means looking at it while the conversation
  goes on. So the file moves into the rail beside the chat, and stays there
  as a tab.

  Per chat, like everything else in the rail: switching the conversation
  switches what is open. Images keep the old window — a picture wants the
  room, not a column.

  Filing follows ONE rule, and it lives here, not in any caller: whoever
  WRITES a file (the streaming answer) is the source of truth and may
  replace the tab; whoever merely SHOWS one (a card in the transcript)
  only fills gaps — it never replaces an existing tab and never brings
  back one the user closed. The rule sits in this module so every future
  caller — a browser view, a preview tool handed to the model — inherits
  it instead of re-deriving it. See tabOeffnen() and tabEinsortieren().

  A file is in the rail from its first line, not from its last: the writer
  opens the tab when the file begins and then carries each further piece
  into it, so the content arrives beside the chat while the answer is still
  being written. See tabWriter().
*/

import { anbieten } from './arbeitsleiste.svelte.js'
import { zustand } from './zustand.svelte.js'

export const tabs = $state({
  /* chat id -> [{ id, name, art, inhalt, pfad }]; `pfad` is where the file
     lies on disk, empty for a file that only stands in an answer's text. A
     file the browser's own viewer draws (a PDF) carries no text but
     `adresse`, where the file itself is fetched from, and `fakten`, its
     line of facts. */
  proChat: {},
  aktiv: {},
  /* chat id -> { tab id: true } — tabs the user closed by hand. A card
     re-filing on every mount used to bring a closed tab straight back;
     closed now means closed until the file is actually written again. */
  zu: {},
})

function schluessel(name, art) {
  return `${art}:${name}`
}

export function tabsVon(chatId) {
  return tabs.proChat[chatId] ?? []
}

export function aktiverTab(chatId) {
  const liste = tabsVon(chatId)
  return liste.find((e) => e.id === tabs.aktiv[chatId]) ?? liste[liste.length - 1] ?? null
}

/**
 * Puts a freshly WRITTEN file into the rail — the streaming answer's path.
 *
 * A file that is already open is replaced rather than doubled: the model
 * rewriting its page is the same page, and two tabs of one name help
 * nobody. Replaced only when the content actually differs — the identical
 * case must write NOTHING: a caller inside an $effect reads this list on
 * its way in, and an unconditional rewrite made that effect its own
 * trigger, round and round until Svelte pulled the plug
 * (effect_update_depth_exceeded). A rewrite also lifts a user's "closed":
 * a new version of the file has arrived and deserves to be findable again.
 */
export function tabOeffnen(chatId, { name, art, inhalt, pfad = '', adresse = '', fakten = '' }, aufdraengen = true) {
  if (!chatId || !name) return
  const id = schluessel(name, art)
  if (tabs.zu[chatId]?.[id]) delete tabs.zu[chatId][id]
  const liste = tabsVon(chatId)
  const stelle = liste.findIndex((e) => e.id === id)
  if (stelle < 0 || liste[stelle].inhalt !== inhalt) {
    const neu = [...liste]
    const eintrag = { id, name, art, inhalt, pfad, ...(adresse ? { adresse, fakten } : {}) }
    if (stelle >= 0) neu[stelle] = eintrag
    else neu.push(eintrag)
    tabs.proChat[chatId] = neu
  } else if (!liste[stelle].pfad && pfad) {
    /* The same content, and now a place for it: the tab keeps everything it
       holds and takes the path it did not know. */
    tabs.proChat[chatId] = liste.map((e, i) => (i === stelle ? { ...e, pfad } : e))
  }
  /* `aufdraengen` false files the tab without opening a panel over the
     conversation. The newest file still steps to the FRONT of its own
     chat's rail when that chat is off screen — coming back to the chat
     should show what was built, and a background chat's `aktiv` pointer
     is invisible until then, so setting it can take over nobody's screen.
     Only an on-screen chat keeps its current selection. */
  if (!aufdraengen) {
    if (chatId !== zustand.aktiverChat || !tabs.aktiv[chatId]) tabs.aktiv[chatId] = id
    return
  }
  tabs.aktiv[chatId] = id
  anbieten('vorschau')
}

/**
 * Files a file a card is merely SHOWING — the transcript's path.
 *
 * Fills gaps only: an id that is already filed keeps whatever it holds
 * (an older message's card must not shove its version over a newer one),
 * and an id the user closed stays closed. The one gap it fills in a tab
 * that is already there is the path: a tab filed without one takes the
 * path a card knows. Otherwise it writes nothing at all, which is what
 * lets a card call this from an $effect without feeding its own
 * dependencies.
 */
export function tabEinsortieren(chatId, { name, art, inhalt, pfad = '', adresse = '', fakten = '' }) {
  if (!chatId || !name) return
  const id = schluessel(name, art)
  if (tabs.zu[chatId]?.[id]) return
  const liste = tabsVon(chatId)
  const index = liste.findIndex((e) => e.id === id)
  if (index >= 0) {
    /* A gap is the one thing a card fills: a tab filed without a path takes
       the one this card knows. Content, place in the rail and the chosen
       tab stay; a path that stands is not replaced, and nothing is written
       when there is nothing to fill. */
    if (!liste[index].pfad && pfad) {
      tabs.proChat[chatId] = liste.map((e, i) => (i === index ? { ...e, pfad } : e))
    }
    return
  }
  const eintrag = { id, name, art, inhalt, pfad, ...(adresse ? { adresse, fakten } : {}) }
  tabs.proChat[chatId] = [...liste, eintrag]
  if (!tabs.aktiv[chatId]) tabs.aktiv[chatId] = id
}

/**
 * Carries a file that is still being written on into its tab.
 *
 * The answer opens the tab once, when the file begins (tabOeffnen above).
 * From then on every further piece comes through here, and this only ever
 * touches a tab that is THERE: one the user closed in the meantime stays
 * closed, however much more is written, and a file that has no tab gets
 * none from here. Identical content writes nothing — the same guard, for
 * the same reason, as in tabOeffnen.
 */
export function followTab(chatId, { name, art, inhalt }) {
  if (!chatId || !name) return
  const id = schluessel(name, art)
  const liste = tabsVon(chatId)
  const stelle = liste.findIndex((e) => e.id === id)
  if (stelle < 0 || liste[stelle].inhalt === inhalt) return
  const neu = [...liste]
  neu[stelle] = { ...liste[stelle], inhalt }
  tabs.proChat[chatId] = neu
}

/**
 * The writer's hand for ONE answer: every file the answer carries goes
 * through what this returns, as often as the stream likes.
 *
 * The first sight of a file opens its tab (tabOeffnen), every later one only
 * follows it (followTab) — which is what keeps a tab closed that the reader
 * closed while its file was still being written, and what lets a new answer
 * that writes the same file again bring it back. Files are told apart by
 * their name and not by counting them: an open fence can turn out to be
 * something else as the text goes on, and a count would then hand the next
 * file the place of one that never came.
 *
 * `firstSight` runs before a tab is opened and says whether the rail may
 * come forward for it (tabOeffnen's `aufdraengen`).
 */
export function tabWriter(chatId, firstSight = () => true) {
  const seen = new Set()
  return function (file) {
    if (seen.has(file.name)) return followTab(chatId, file)
    seen.add(file.name)
    tabOeffnen(chatId, file, firstSight())
  }
}

export function tabWaehlen(chatId, id) {
  tabs.aktiv[chatId] = id
}

/**
 * Takes the tab of a file that no longer exists out of the rail.
 *
 * Not the user's closing: nothing is remembered in `tabs.zu`, so a file of
 * the same name that is written or shown again files its tab as usual. The
 * tab is found by the address the file is fetched from (`adresse`), which
 * only a file drawn in a frame carries; a tab without one — a text file,
 * which keeps its own text — is not touched. When it was the chosen tab the
 * last remaining one is chosen, as when the user closes it. Where no tab
 * carries the address nothing is written.
 */
export function tabRemoveByAddress(chatId, address) {
  if (!chatId || !address) return
  const liste = tabsVon(chatId)
  if (!liste.some((e) => e.adresse === address)) return
  const rest = liste.filter((e) => e.adresse !== address)
  tabs.proChat[chatId] = rest
  if (!rest.some((e) => e.id === tabs.aktiv[chatId])) {
    tabs.aktiv[chatId] = rest[rest.length - 1]?.id ?? null
  }
}

export function tabSchliessen(chatId, id) {
  const liste = tabsVon(chatId).filter((e) => e.id !== id)
  tabs.proChat[chatId] = liste
  /* Remembered, not just removed: the expanded cards in the transcript
     re-file their tabs on every mount, and without this mark the closed
     tab was back before the click was over. */
  ;(tabs.zu[chatId] ??= {})[id] = true
  if (tabs.aktiv[chatId] === id) {
    tabs.aktiv[chatId] = liste[liste.length - 1]?.id ?? null
  }
}
