/*
  The working folders of a chat — state and actions in one place.

  Split out of the component so the view (the input bar's folder chip,
  FolderChip.svelte) draws and the logic lives here: one truth about which
  folders a chat has.
*/

import { cubicOut } from 'svelte/easing'

import { api } from './api.js'
import { t } from './texte.svelte.js'
import { zustand, aktuellerChat, chatSichern, chatsLaden, melde } from './zustand.svelte.js'
import { gemeldetWird } from './meldewesen.svelte.js'

/* How a pill appears and goes: a short fade with a touch of scale. This
   was the FALLBACK of a crossfade between two spots; with one spot left a
   departure could never meet an arrival, so every pill took the fallback
   anyway — and a pair of transitions keyed for a flight that cannot happen
   was two maps of pending senders and receivers kept for nothing. */
export function erscheinen() {
  return {
    duration: 200,
    easing: cubicOut,
    css: (t) => `opacity: ${t}; transform: scale(${0.96 + 0.04 * t})`,
  }
}

export const ordnerZustand = $state({
  /* Whether this machine has a folder dialog at all. Asked once at startup;
     without one, only the path field remains in the window. */
  dialogDa: false,
  maskeOffen: false,
  laeuft: false,
  /* The shared folders of the open chat that are no longer on the disk —
     the service's answer, asked once when the chat is opened. They STAY in
     the chat's list: nothing is removed here, because tomorrow nobody would
     know what had once been shared. */
  fehlend: [],
  /* Set while the user is naming the new place of ONE missing folder: the
     old path. The next path that arrives — from the system dialog or the
     field, the two ways the mask has always had — is its new place, not
     one more share. That is the pair, and it comes from the button rather
     than from comparing the old list with the new one: with two folders
     missing at once, no comparison can say which new one replaces which. */
  ersatzZiel: null,
  /* The shared folders whose ``exe.md`` is gone while the program still has
     a copy of it. Exactly that pair, because it is the only state an offer
     to put the copy back says anything in: with the notes still there the
     copy is not needed, and without a copy there is nothing to offer.
     Filled by ``ordnerstandPruefen`` and never on its own: the answer about
     a MISSING folder decides whether one may appear here at all, so the two
     always travel together, at every one of the four moments the run
     counter below lists. */
  notizverlust: [],
  /* The folder a restore is running for, while it runs — and it runs until
     the check after it has answered. Without it the button of the folder
     just put back stays live for up to five round trips, and a second click
     answers "it already says exactly what the copy says": a correct
     sentence about a question nobody asked. */
  holtZurueck: '',
  /* How the last "get the notes back" attempt ended — read and shown inside
     the folder window itself: that window's veil covers the
     toast stack (Fenster.svelte z-index 70 against Meldungen.svelte's 25),
     so a toast about this would appear half hidden behind it. Cleared when
     the window closes and when a new attempt starts. */
  zurueckMeldung: null,
})

/* Which run of ``ordnerstandPruefen`` is the youngest — only it may write.
   Four things start one (a chat switch, a changed folder list, the folder
   window opening, a restore), and each takes up to five requests one after
   another. Comparing the chat is not enough: two runs of the SAME chat
   overlap easily, and the older one would write the state it collected
   BEFORE the restore back over the newer one's — the folder would reappear
   with its button, and the next click would answer "it already says exactly
   that". */
let lauf = 0

/* Which chat the two lists above are about. What they hold is only thrown
   away when this changes; asking the same chat again leaves them standing
   until the new answer replaces them. */
let standChat = null

export function ordnerListe() {
  return aktuellerChat()?.working_dirs ?? []
}

/* Only the folder name, not the whole path — the working directory is known
   anyway. The full path stays in the tooltip, so the short form never has to
   lie about where something is. */
export function ordnerName(pfad) {
  const teile = String(pfad).split('/').filter(Boolean)
  return teile[teile.length - 1] || '/'
}

export async function dialogPruefen() {
  try {
    const auskunft = await api.ordnerDialogAuskunft()
    ordnerZustand.dialogDa = Boolean(auskunft?.verfuegbar)
  } catch {
    ordnerZustand.dialogDa = false
  }
}

/* What is wrong with this chat's folders — both halves, in one go: which of
   them are no longer there, and which of the remaining ones lost their notes
   while the program still keeps a copy.

   One function on purpose. The second answer only means anything on top of
   the first: a folder that is GONE reads exactly like one whose notes were
   deleted (nothing to read, copy kept), and offering to put the copy back
   there would write into a folder that does not exist — the service says
   "the folder refused the write", which is not what happened. Two functions
   meant two runs, two counters and two ways for one to overtake the other.

   Asked when a chat is opened, when the folder list changed, when the folder
   window opens, and after a restore. Nothing is run and nothing is removed;
   the window says it and the user decides. */
export async function ordnerstandPruefen() {
  const chatId = zustand.aktiverChat
  const meiner = ++lauf
  /* A different chat: what stands here belongs to the one before, down to
     the paths — cleared at once, because until the new answers arrive it
     would be on screen and clickable, and a click would send this chat's id
     with the other chat's path (403). The SAME chat keeps what it has while
     it is asked again: the window is opened for that very block, and a list
     that empties itself for four round trips reads as "nothing here". */
  if (chatId !== standChat) {
    standChat = chatId
    ordnerZustand.fehlend = []
    ordnerZustand.notizverlust = []
  }
  if (!chatId) return

  let fehlend = []
  try {
    const stand = await api.chatOrdnerstand(chatId)
    fehlend = stand?.fehlend ?? []
  } catch {
    /* A question that could not be asked is not an answer: rather say
       nothing than paint a warning nobody can act on — and rather say
       nothing than go on. What follows reads this very list to decide which
       folder may be offered its notes back; with an empty list from a failed
       request, the folder that moved away is exactly the one that gets the
       offer. */
    if (meiner !== lauf) return
    ordnerZustand.fehlend = []
    ordnerZustand.notizverlust = []
    return
  }
  if (meiner !== lauf) return

  /* The folder list AFTER the first answer, not before it: read before the
     first ``await``, the reading itself would bind every ``$effect`` that
     calls this function to the whole chat list — and that list is replaced
     whenever an answer finishes, so four shared folders would pay five
     requests for every reply the model gives. The four moments named above
     are the ones that were meant.

     One question per folder — the route answers about one folder, and
     asking about a list would be a second route for the same thing. A folder that is not there any more is the
     other block's business and is skipped here; a question that failed
     drops that folder out of the offer rather than leaving it standing
     there with a promise nobody can keep. */
  const ordner = ordnerListe()
  const verschwunden = new Set(fehlend)
  /* Both halves are written in the same breath, because between them lies
     everything the loop below asks: a folder that has just gone would
     otherwise stand under "say where it went" AND under "put the notes
     back" at the same time, and the second one would write into a folder
     that is not there. What the old answer still holds is narrowed to what
     can still be true — never widened. */
  ordnerZustand.fehlend = fehlend
  ordnerZustand.notizverlust = ordnerZustand.notizverlust.filter(
    (pfad) => ordner.includes(pfad) && !verschwunden.has(pfad),
  )

  const verloren = []
  for (const pfad of ordner) {
    if (verschwunden.has(pfad)) continue
    try {
      const stand = await api.ordnerwissenStand(chatId, pfad)
      if (stand?.sicherung && !stand?.notiz) verloren.push(pfad)
    } catch {
      // Say nothing about this folder.
    }
  }
  // Only the youngest run writes — see ``lauf``.
  if (meiner !== lauf) return
  ordnerZustand.notizverlust = verloren
}

export function maskeOeffnen() {
  ordnerZustand.maskeOffen = true
}

/* The button on one missing folder: from here on, the mask is asking where
   THAT folder went. */
export function ersatzBeginnen(pfad) {
  ordnerZustand.ersatzZiel = pfad
  ordnerZustand.maskeOffen = true
}

async function sichern(liste, ersatz = null) {
  try {
    const chat = await chatSichern()
    if (!chat) return
    const daten = { working_dirs: liste }
    // Only when this save really replaces a folder that is gone. Without the
    // pair the service rewrites no document path — a changed list of folders
    // on its own means nothing but a changed list of folders.
    if (ersatz) daten.ordner_ersatz = ersatz
    const geaendert = await api.chatAendern(chat.id, daten)
    // Write back into the list the state holds, so every view that reads the
    // chat sees the new folders — not just the one that changed them.
    chat.working_dirs = geaendert.working_dirs
    // In a project the folders are every chat's: the list is read again so
    // the other chats of the project carry them too.
    if (geaendert.project_id) void chatsLaden()
    /* A folder that was re-chosen or let go is not missing any more. NOT
       awaited: this check makes up to five requests one after another, and
       the line below closes the window — waiting for them would leave it
       standing open with its buttons live. */
    void ordnerstandPruefen()
  } catch (fehler) {
    melde(fehler.message || t('fehler.allgemein'), 'fehler')
  }
}

/* A folder the model made and shared with the tool `create_folder` is the
   chat's (or its project's) now, stored by the service: the chats are read
   again so the header shows it at once, and the folder state is checked the
   way a share from the chip is. */
export function sharedByModel() {
  void chatsLaden()
  void ordnerstandPruefen()
}

export async function ordnerHinzufuegen(pfad) {
  if (!pfad) return
  /* Both ways into the mask end here, and this is where the two meanings
     part: with a replacement running, the path that arrives is where a
     missing folder WENT — it takes that folder's place in the list and
     travels with it as a pair. Otherwise it is simply one more share. */
  const alt = ordnerZustand.ersatzZiel
  if (alt) {
    ordnerZustand.ersatzZiel = null
    await sichern(
      ordnerListe().map((eintrag) => (eintrag === alt ? pfad : eintrag)),
      { alt, neu: pfad },
    )
    ordnerZustand.maskeOffen = false
    return
  }
  if (ordnerListe().includes(pfad)) {
    ordnerZustand.maskeOffen = false
    return
  }
  await sichern([...ordnerListe(), pfad])
  ordnerZustand.maskeOffen = false
}

export async function ordnerLoesen(pfad) {
  await sichern(ordnerListe().filter((eintrag) => eintrag !== pfad))
}

/* A click on the chip shows the folder in the file manager — the shortest
   way from "the model works in there" to "let me get a file out of there".
   The path is not sent as a wish: the service takes it from the chat's own
   list, and anything else is refused. Without a path it is the chat's own
   folder — the one the program keeps for it — whose place only the service
   knows; it is created there if it does not exist yet. */
export async function ordnerZeigen(pfad = null) {
  try {
    await api.ordnerOeffnen(zustand.aktiverChat, pfad)
  } catch (fehler) {
    melde(fehler.message || t('fehler.allgemein'), 'fehler')
  }
}

/* The system dialog blocks as long as it is open — the service answers only
   once it is closed. `laeuft` keeps a second click out meanwhile. */
export async function systemdialog() {
  if (ordnerZustand.laeuft) return
  ordnerZustand.laeuft = true
  try {
    /* Where the dialog opens: the last folder shared. Not while a missing
       one is being replaced — that path leads nowhere, which is the whole
       reason the user is standing here. */
    const liste = ordnerZustand.ersatzZiel ? [] : ordnerListe()
    const antwort = await api.ordnerDialogOeffnen(
      t('arbeitsordner.dialog_titel'),
      liste[liste.length - 1] || null,
    )
    // No path means cancelled. Nothing happened — say nothing.
    if (antwort?.pfad) await ordnerHinzufuegen(antwort.pfad)
  } catch (fehler) {
    melde(fehler.message || t('fehler.allgemein'), 'fehler')
  } finally {
    ordnerZustand.laeuft = false
  }
}

/* Puts one folder's kept copy back. Every ending is reported, the good one
   included: the service answers with a key from app/ordnerwissen.py and the
   sentence for it stands in the catalogue, so "nothing was kept" and "your
   own notes were left alone" do not arrive as the same shrug. Only a real
   write is success — the rest is a notice.

   Asked again afterwards, because the answer changes the pair this offer
   hangs on: a folder that has its notes back is not missing them. */
export async function notizenZurueckholen(pfad) {
  const chatId = zustand.aktiverChat
  if (!chatId || ordnerZustand.holtZurueck) return
  ordnerZustand.holtZurueck = pfad
  ordnerZustand.zurueckMeldung = null
  try {
    const antwort = await api.ordnerwissenZurueckholen(chatId, pfad)
    /* Out of the offer at once, not only after the check that follows: that
       check can be overtaken by a younger run and then writes nothing at
       all, and the button would come back for a folder whose notes are
       already back — the second click answering "it already says exactly
       that". This one folder is known here for certain. */
    if (antwort.ergebnis === 'zurueck') {
      ordnerZustand.notizverlust = ordnerZustand.notizverlust.filter(
        (eintrag) => eintrag !== pfad,
      )
    }
    // The window may have closed while this was in flight — its own state
    // is not a place for a sentence about a folder nobody is looking at any
    // more, and the next opening would otherwise show it as if it just
    // happened.
    if (ordnerZustand.maskeOffen) {
      ordnerZustand.zurueckMeldung = {
        text: t(`ordnerwissen.${antwort.ergebnis}`, { ordner: ordnerName(pfad) }),
        art: antwort.ergebnis === 'zurueck' ? 'erfolg' : 'hinweis',
      }
    }
  } catch (fehler) {
    // The same switch every other failure notice in the house respects
    // (melde(), art 'fehler') — shown in the window instead of a toast, but
    // still a 'fehler' occurrence the user may have turned off.
    if (ordnerZustand.maskeOffen && gemeldetWird('fehler')) {
      ordnerZustand.zurueckMeldung = { text: fehler.message || t('fehler.allgemein'), art: 'fehler' }
    }
  }
  try {
    await ordnerstandPruefen()
  } finally {
    ordnerZustand.holtZurueck = ''
  }
}
