/*
  The shared state of the interface.

  Svelte 5 does this with $state: whatever lives here is reactive
  everywhere, without one component having to pass anything through to
  another. That was exactly the tedious part of the one big file — every
  change had to be written into the document by hand in three places.
*/

import { api } from './api.js'
import { farbtonDrehen } from './agentenfarbe.svelte.js'
import {
  VORGABE_DARSTELLUNG, VORGABE_LAYOUT,
  darstellungSpeichern, keptModelName, layoutSpeichern, modellSpeichern, storedModelId,
} from './anzeige.js'
import { chatZustandLaden, chatanzeige } from './chatanzeige.svelte.js'
import { VORGABE_CHATLAYOUT, chatlayoutAnwenden, chatlayoutAusGespeichert, chatlayoutZumSpeichern } from './chatlayout.js'
import { ausFenster, ohneWeg } from './fensterweg.svelte.js'
import { answerPreview } from './answerPreview.js'
import { melde, melden } from './meldewesen.svelte.js'
import { t } from './texte.svelte.js'
import { leeren as warteschlangeLeeren } from './warteschlange.svelte.js'

export const zustand = $state({
  chats: [],
  /* The projects in the list, and what lies in the archive: the projects
     put away with their chats and the chats put away one by one. Loaded
     with the chat list, which is where all three change. */
  projects: [],
  archive: { chats: [], projects: [] },
  modelle: [],
  nachrichten: [],
  /* Which chat `nachrichten` belongs to — `null` for none. A failed
     reopen (`chatOeffnen` below) restores `aktiverChat` to the chat it
     came from without touching the list, which may by then hold a THIRD
     chat's rows from an overtaking open in between. Compared against
     `aktiverChat` wherever the list is drawn: the two only ever agree
     when the rows on screen truly are the selected chat's own. */
  nachrichtenChatId: null,
  version: '',
  aktiverChat: null,
  /* The switch "Suspend instructions for this chat", set in the plus menu
     before any chat exists: the value waits here and goes to the chat with
     the first message (`haltendenWertSetzen`). Leaving for another chat or
     a fresh start lets it go. */
  pendingPromptOff: false,
  /* The placeholder message of a running TEXT answer, held here because
     switching chats replaces `nachrichten` wholesale with the server's
     fetch below, which would otherwise lose the one message still living
     only in the client while its run is in flight. This keeps the actual
     object (with its `abschnitte`) — App.svelte is still writing into it
     by reference, so putting the SAME object back picks the stream up
     exactly where it stood.

     Keyed by chat id: this window follows one run per chat at the same
     time, so a second run cannot overwrite the first one's placeholder. */
  laufenderPlatzhalter: {},
  /* Set by chatOeffnen when the SERVER says a generation is still going for
     a chat that this window has no memory of at all — a plain reload, not a
     chat switch within the same session (that case is `laufenderPlatzhalter`
     above, and needs none of this). App.svelte's own effect watches this,
     starts the actual reattachment, and clears it again — this module holds
     no stream itself, only the word that one is owed.

     Keyed by chat id: opening chat A and then very quickly chat B can no
     longer lose A's owed reattachment — each chat keeps its own entry
     until the window gets around to it. */
  wiederanhaengen: {},
  /* How many more pictures are queued behind the one being drawn. Pressing
     "draw" again while one runs adds to the queue instead of being ignored;
     this count feeds the little house-style badge that says how many are
     still to come. */
  bildWarteschlange: 0,
  /* The studio's pictures still to come, in order: the one drawing first,
     then the waiting ones — `{ id, prompt, running }` each. The studio's
     row of pictures shows them; the queue itself lives in App.svelte, which
     rebuilds this list whenever it changes. */
  pictureQueue: [],
  modellId: '',
  /* The chosen model while it is not among the reachable ones: the entry
     the window had of it, or the one the service still names for it, under
     the name stored with the choice where the window had none, with the
     word of its server. Kept beside `modelle` and not in it — the
     picker offers reachable models only — and read through
     `aktuellesModell()`, so the bar and the strip keep naming the model
     that is chosen instead of another one. */
  unlistedModel: null,
  suche: '',
  // Running text answers, keyed by chat id: { [chatId]: { abbruch,
  // generationId, chatId } }. One entry per chat with a run in flight —
  // read it through `laufVon(chatId)`, never as a bare
  // truthiness check (the object itself is always there now).
  laeuft: {},
  /* Chats whose send is still on its way to a run — the stretch between
     pressing enter and the run existing, which a document upload can make
     seconds long. `laufVon` cannot see it (there is no run yet), and both
     the input bar and the queue must: a second enter in that window used
     to call senden() again and bear a second answer row with the same id. */
  sendet: {},
  seitenleisteOffen: false,
  // Collapsed on the desktop: the sidebar goes away entirely. It used to
  // leave a narrow rail because the toggle lived inside it; the handle sits
  // on the seam now (teile/Seitengriff.svelte). Below 760 px,
  // `seitenleisteOffen` applies instead — there it slides over as a drawer.
  seitenleisteEingeklappt: VORGABE_LAYOUT.seitenleiste_zu,
  // The sidebar's width in px, dragged at the seam and kept across starts.
  // While a drag runs, the width transition pauses so the edge follows the
  // hand instead of easing after it.
  seitenBreite: VORGABE_LAYOUT.seitenleiste_breite,
  seitenZieht: false,
  werkzeuge: { aktiv: false, werkzeuge: [] },
  // Feature switches from the config (GET /meta, interface milestone C).
  // Until the answer arrives, everything counts as on — otherwise the
  // menu entries would flash away at startup and then back on.
  features: { mcp: true, document_upload: true },
  /* The zone the service fires schedules in (/meta); '' reads the
     browser's own clock. */
  timezone: '',
  /* Which colour pack the code blocks wear: `exe` or one of the eight
     editor packs in stil/codefarben.css. */
  codefarben: VORGABE_DARSTELLUNG.codefarben,
  verlauf: VORGABE_DARSTELLUNG.verlauf,
  blasenfarbe: VORGABE_DARSTELLUNG.blasenfarbe,
  /* The chat layout from the layout mode (lib/chatlayout.js), and whether
     its window stands over the chat right now. */
  chatlayout: { ...VORGABE_CHATLAYOUT },
  layoutModusOffen: false,
  // Pending confirmation before a tool runs (1.6). At most one at a time:
  // the server waits as long as it stands.
  /* The menus beside the sidebar (teile/Seitenrahmen.svelte), one flag each:
     local models, cloud providers, the catalogue, and the settings
     (`promptOffen`, below); local and cloud stay two flags because the
     catalogue leads back into the local menu by name. All false: the chat
     shows. */
  lokalOffen: false,
  katalogOffen: false,
  /* Which tab the catalogue should open on when a panel sends the user
     there — read once by the catalogue window, then cleared. `downloads`
     names the page of the downloads. */
  katalogArtWunsch: null,
  /* Which server the local menu should show when a row of the settings list
     sends the user there — read once by the local window, then cleared. */
  lokalWunsch: null,
  cloudOffen: false,
  /* The section column of the menu standing open: handed over by the frame
     its page renders (teile/Menueseite.svelte) and drawn by the sidebar in
     the chat list's place — `{ snippet, label }`, or null while no menu
     stands open. Lives only as long as that page does; never persisted. */
  menuSections: null,
  /* The lowest edge, in the pixels the browser measures, of what the page
     standing open keeps free at its top — its head, or the studio's bars —
     handed over by that page (lib/noticeStart.js); the notices begin under
     it (teile/Meldungen.svelte). Null while nothing asks for it: the notices
     then stand where they stand over the chat. */
  menuHeadBottom: null,
  /* Pending tool confirmation (Tor 3), a map keyed by chat id:
     { [chatId]: { generationId, aufrufId, name, argumente, chatId } }.
     One standing question per chat, so a confirmation in chat B cannot
     overwrite the one still open in chat A. Read as
     `zustand.werkzeugfrage[chatId]` or through `werkzeugfrageVon(chatId)`,
     never as a bare `zustand.werkzeugfrage` truthiness check — the map
     object itself is always there. */
  werkzeugfrage: {}, // { [chatId]: { generationId, aufrufId, name, argumente, chatId } }
  // Chats with a finished answer nobody has looked at yet — the sidebar
  // shows the pulsing dot for them.
  fertigeChats: [],
  /* The model asked something and is waiting (ask_user), a map keyed by
     chat id: { [chatId]: { generationId, aufrufId, frage, optionen,
     chatId, nummer } }. One per chat — read through `benutzerfrageVon(chatId)`
     or as `zustand.benutzerfrage[chatId]`, never as a bare truthiness
     check. */
  benutzerfrage: {},
  /* start_job's editable confirmation, a map keyed by chat id:
     { [chatId]: { generationId, aufrufId, agent, task, chatId } } — the
     run stands until it is answered. One per chat; read through
     `jobfrageVon(chatId)` or as `zustand.jobfrage[chatId]`. */
  jobfrage: {},
  // Which sheet the SIDEBAR shows: 'chats' or 'agenten'. Only the sidebar —
  // the main area is always the chat; jobs live in the work rail's agents
  // module. Deliberately not remembered across starts: after opening, you
  // usually want to chat, not see yesterday's agent list.
  seitenblatt: 'chats',
  auftraege: [],
  // Job clicked in the sidebar: the main area unfolds it.
  auftragAusgewaehlt: null,
  // Search term of the job list. Unlike the chats, filtering happens in
  // the window, not on the server — the list is already there anyway.
  auftragSuche: '',
  // The start dialog lives here because its button sits in the sidebar
  // and the window next to it hangs in the main area.
  auftragStartenOffen: false,
  /* The agent the start dialog opens with preselected — set by the play
     mark on an agent tile, read once when the dialog opens. */
  auftragStartenAgent: null,
  // The prompt/agents window likewise: it is opened from the menu bar,
  // but also from within the job dialog ("no agents yet").
  promptOffen: false,
  // Which source the editor opens with (A6): 'system' or 'tools'.
  // The settings menu has two entries pointing at the same window.
  promptStart: 'system',
  // The house's pending prompt dialog: replaces the bare
  // confirm()/prompt() boxes of the browser. At most one at a time.
  frage: null, // { text, eingabe, okSchluessel, danger, aufloesen }
})

/* The menus and the flag each one stands on, in the order of the window
   row: `seiteOffenFuer`, `eineSeiteOffen`, `seiteZeigen` and
   `seitenSchliessen` all read this one table, so the flags cannot drift
   apart. Which button stands in the window row and which sign it wears is
   the sidebar's own list — a menu needs both. */
const MENUS = {
  lokal: 'lokalOffen',
  cloud: 'cloudOffen',
  katalog: 'katalogOffen',
  prompt: 'promptOffen',
}

/* Whether the menu a button of the window row stands for is the one open. */
export function seiteOffenFuer(name) {
  const flag = MENUS[name]
  return flag ? zustand[flag] : false
}

/* Whether any menu lies over the main area. */
export function eineSeiteOffen() {
  return Object.keys(MENUS).some((name) => seiteOffenFuer(name))
}

/* The window row's button: a menu has no veil to click beside, so its own
   button takes it away again. */
export function menueFensterOeffnen(name) {
  if (seiteOffenFuer(name)) {
    seitenSchliessen()
    return
  }
  seiteZeigen(name)
}

/* What the sidebar looked like before a menu pulled it up, so the way back
   puts it back the way the user had it. One entry for the whole stretch
   menus stay open (`??=`): switching from one menu to the next must not
   overwrite the state the stretch began with. */
let sidebarBeforeMenu = null

/* A menu is about to stand open. Its sections live in the sidebar, in the
   chat list's place, so a folded sidebar unfolds. On a narrow window the
   sidebar is a drawer lying over the main area, and the menu's content
   must stay in sight there: the drawer closes, and the sections are one
   tap on the icon bar away. `seitenSchliessen` puts back what stood here. */
export function revealSidebar() {
  sidebarBeforeMenu ??= {
    seitenleisteEingeklappt: zustand.seitenleisteEingeklappt,
    seitenleisteOffen: zustand.seitenleisteOffen,
  }
  zustand.seitenleisteEingeklappt = false
  if (istSeitenleisteSchmal()) zustand.seitenleisteOffen = false
}

/* One menu stands open: its flag, and the sidebar up for its sections.
   The one way a menu turns on — the two ways through `katalogOeffnen`
   walk it too. */
function showMenu(name) {
  for (const [menu, flag] of Object.entries(MENUS)) zustand[flag] = menu === name
  revealSidebar()
}

/* The menus are one place each — showing one closes the others. Every way
   into a menu comes through here (the window row, the settings key, an
   agent opened for editing), so two never lie over each other. */
export function seiteZeigen(name) {
  /* A menu reached this way stands on its own — whatever detour was
     remembered before is over, and an arrow pointing back into it would
     point somewhere the hand never was. */
  ohneWeg()
  showMenu(name)
  /* A sheet turned over to the agents gives way to the menu — the same way
     it gives way to the search. */
  if (zustand.seitenblatt !== 'chats') blattWechseln('chats')
}

/* The menu pages give the main area back to the chat. A page covers the
   chat rather than replacing it, so nothing of the conversation is lost on
   the way there and back. Called where the hand asks for something a page
   covers: a chat or a new chat from the sidebar, a run or the agent form on
   the tool surface, Escape, the search, and the menu's own way back. */
export function seitenSchliessen() {
  for (const flag of Object.values(MENUS)) zustand[flag] = false
  /* The sidebar goes back to what the user had before a menu pulled it up —
     a folded one folds again, the drawer closes. */
  if (sidebarBeforeMenu) {
    zustand.seitenleisteEingeklappt = sidebarBeforeMenu.seitenleisteEingeklappt
    /* The drawer only where a drawer is the sidebar's shape: a window that
       widened in the meantime must not take a stale open back (the size
       watcher clears exactly this). */
    zustand.seitenleisteOffen = sidebarBeforeMenu.seitenleisteOffen && istSeitenleisteSchmal()
    sidebarBeforeMenu = null
  }
}

/* From an empty server panel straight to where its models are: the
   catalogue, already on the right tab. The panels live in the local menu,
   so this leaves a way back INTO it — the same trail the first-run steps
   there lay down, so the arrow at the top leads home instead of vanishing
   the way a plain menu jump would. */
export function katalogOeffnen(art) {
  zustand.katalogArtWunsch = art
  ausFenster(
    () => showMenu('katalog'),
    () => showMenu('lokal'),
  )
}

/* A prompt dialog in the house style. Returns a promise:
   without an input field true/false, with an input field the text or null.

     if (!(await frage(t('chat.loeschen_frage')))) return
     const neu = await frage(t('chat.neuer_titel'), { eingabe: alt })

   The bare confirm()/prompt() boxes of the browser are off-limits from
   here on — they were the last foreign body in the interface. */
export function frage(text, { eingabe = null, okSchluessel = 'app.ok', danger = false } = {}) {
  melden({ was: 'wartet', von: 'chat' })
  return new Promise((aufloesen) => {
    zustand.frage = { text, eingabe, okSchluessel, danger, aufloesen }
  })
}

export function frageBeantworten(wert) {
  const offene = zustand.frage
  if (!offene) return
  zustand.frage = null
  offene.aufloesen(wert)
}

/* Chats whose answer finished while the user was looking elsewhere. The
   sidebar marks them with the pulsing dot until they are opened, and the
   card that says so carries the chat's name and the beginning of its answer
   (`answer` is the visible text of the finished message). */
export function chatFertigMerken(id, answer = '') {
  if (id && !zustand.fertigeChats.includes(id)) {
    zustand.fertigeChats.push(id)
    const chat = zustand.chats.find((c) => c.id === id)
    melden({ was: 'fertig', von: 'chat', heading: chat?.title || t('chat.unbenannt'), text: answerPreview(answer) })
  }
}

export function chatFertigGesehen(id) {
  if (id && zustand.fertigeChats.includes(id))
    zustand.fertigeChats = zustand.fertigeChats.filter((c) => c !== id)
}

/* Yes or no to the server. The box disappears immediately — the answer
   has been given, leaving it up would invite a second click. If reporting
   it fails the run is still waiting (it gives up on its own only after the
   service's own deadline), so the question stands again with what was
   written for it: nothing typed is lost, and the notice says why it came
   back. A question that already took its place is not pushed out. */
function frageZurueckstellen(art, chatId, frage, zusatz) {
  melde(t('werkzeug.antwort_kam_nicht_an'), 'fehler')
  /* Only while the run is still there: one that ended meanwhile has nobody
     left to take an answer. */
  if (zustand.laeuft[chatId] && !zustand[art][chatId]) {
    zustand[art][chatId] = { ...frage, ...zusatz }
  }
}

/* The model's own question (ask_user). Same place above the input field as
   the tool confirmation, and answered through the same route — a click
   sends the label, typing sends what was typed. */
export async function benutzerfrageBeantworten(antwort, chatId = zustand.aktiverChat) {
  const frage = zustand.benutzerfrage[chatId]
  if (!frage) return
  delete zustand.benutzerfrage[chatId]
  try {
    await api.werkzeugBestaetigen(frage.generationId, frage.aufrufId, true, antwort)
  } catch {
    frageZurueckstellen('benutzerfrage', chatId, frage, { zurueck: antwort })
  }
}

export async function jobfrageBeantworten(erlaubt, task = null, chatId = zustand.aktiverChat) {
  const frage = zustand.jobfrage[chatId]
  if (!frage) return
  delete zustand.jobfrage[chatId]
  try {
    // The edited task travels as the answer — the server takes the user's
    // word over the model's text. A no starts nothing.
    await api.werkzeugBestaetigen(
      frage.generationId, frage.aufrufId, erlaubt,
      erlaubt ? (task ?? frage.task) : null,
    )
  } catch {
    // The edited task comes back as the task of the question.
    frageZurueckstellen('jobfrage', chatId, frage, { task: task ?? frage.task })
  }
}

export async function werkzeugfrageBeantworten(
  erlaubt, immer = false, chatId = zustand.aktiverChat, words = null,
) {
  const frage = zustand.werkzeugfrage[chatId]
  if (!frage) return
  delete zustand.werkzeugfrage[chatId]
  try {
    // Schritt 12: the standing yes is now a real rule in berechtigungen.json,
    // written by the server itself — Tor 3 reads the file fresh on every
    // call, so the very next request already sees it, chat or agent alike.
    // A no may carry the user's own words — what to do instead; the service
    // declines the call and hands them to the model.
    await api.werkzeugBestaetigen(
      frage.generationId, frage.aufrufId, erlaubt, !erlaubt && words ? words : null,
      immer && erlaubt ? frage.name : null, immer && erlaubt,
    )
  } catch {
    frageZurueckstellen('werkzeugfrage', chatId, frage, { zurueck: words ?? '' })
  }
}

/* The notices themselves live in meldewesen.svelte.js now, with the
   decision about whether anything is shown or heard at all. They are
   handed on from here unchanged so that the forty callers that already
   import `melde` from this file keep importing it from this file — what
   moved is where the code sits, not who may call it. */
export {
  aktualisiereMeldung,
  melde,
  meldungen,
  meldungenZuAuftragSchliessen,
  schliesseMeldung,
} from './meldewesen.svelte.js'

/* The running text answer for one chat, or null. Every reader that used to
   test `zustand.laeuft` for "is something running" goes through here now —
   with the map, "for THIS chat" is what almost all of them actually meant. */
export function laufVon(chatId) {
  return chatId != null ? (zustand.laeuft[chatId] ?? null) : null
}

/* The standing question of one kind for a given chat, or null. Each of the
   three is a map keyed by chat id now, so two runs in two chats can each
   hold one without the second overwriting the first. Read through these,
   never as a bare `zustand.werkzeugfrage` check — the map is always there. */
export function werkzeugfrageVon(chatId) {
  return chatId != null ? (zustand.werkzeugfrage[chatId] ?? null) : null
}

export function benutzerfrageVon(chatId) {
  return chatId != null ? (zustand.benutzerfrage[chatId] ?? null) : null
}

export function jobfrageVon(chatId) {
  return chatId != null ? (zustand.jobfrage[chatId] ?? null) : null
}

export function aktuellerChat() {
  return zustand.chats.find((c) => c.id === zustand.aktiverChat) || null
}

/* Whether the instructions are suspended for what is on screen: the open
   chat's own switch or the value still waiting to go to it — a chat made by
   the first message holds nothing for the few moments before the hand-over,
   and after a refused hand-over the value is still owed. */
export function promptAusgesetzt() {
  const chat = aktuellerChat()
  return Boolean(chat?.prompt_aus) || zustand.pendingPromptOff
}

/* Flips the switch "Suspend instructions for this chat". An open chat keeps
   it in its own row; with no chat the value is only held. Answers whether it
   is set — a refusal of the service is told and leaves the switch as it was. */
export async function promptAusUmschalten() {
  const chat = aktuellerChat()
  const an = !promptAusgesetzt()
  if (!chat) {
    zustand.pendingPromptOff = an
    return true
  }
  try {
    await chatAendern(chat.id, { prompt_aus: an })
    // What was waiting for this chat is settled by this answer, either way.
    zustand.pendingPromptOff = false
    return true
  } catch {
    melde(t('systemprompt.schalter_fehler'), 'fehler')
    return false
  }
}

/* Hands a waiting value to the chat the first message is about to go into.
   Answers false when the service refuses it, so the message is not sent with
   the instructions the person switched off. */
export async function haltendenWertSetzen() {
  if (!zustand.pendingPromptOff) return true
  const chat = aktuellerChat()
  if (!chat) return true
  try {
    await chatAendern(chat.id, { prompt_aus: true })
    zustand.pendingPromptOff = false
    return true
  } catch {
    melde(t('systemprompt.schalter_fehler'), 'fehler')
    return false
  }
}

/* The one way a chat comes into being in this window. It is created and is
   the open chat from then on — for the message list and for everything
   that reads `chatanzeige`. The picture studio takes nothing along and
   gives nothing: it belongs to no chat. */
export async function openNewChat(data) {
  const chat = await api.chatAnlegen(data)
  zustand.aktiverChat = chat.id
  nachrichtenSetzen(chat.id, [])
  chatZustandLaden(chat.id)
  await chatsLaden()
  return chat
}

/* The flow: new chat → plus → set the working folder, or attach a
   document → write the first message. So in the empty start there is no
   chat row yet — this creates one rather than refusing. It stays
   untitled; the first message gives it its name (see App.svelte). */
let chatWirdGesichert = null

export async function chatSichern() {
  const vorhandener = aktuellerChat()
  if (vorhandener) return vorhandener
  // Several documents dropped at once from the empty start each call this
  // before the first chat is created — without sharing the
  // in-flight request, every one of them would create its own chat.
  if (chatWirdGesichert) return chatWirdGesichert
  chatWirdGesichert = (async () => {
    try {
      await openNewChat({ title: t('chat.unbenannt'), endpoint_id: zustand.modellId })
      return aktuellerChat()
    } finally {
      chatWirdGesichert = null
    }
  })()
  return chatWirdGesichert
}
export function aktuellesModell() {
  return (
    zustand.modelle.find((m) => m.id === zustand.modellId)
    || (zustand.unlistedModel?.id === zustand.modellId ? zustand.unlistedModel : null)
  )
}

export async function featuresLaden() {
  try {
    const meta = await api.meta()
    if (meta?.features) zustand.features = meta.features
    if (meta?.version) zustand.version = meta.version
    if (typeof meta?.timezone === 'string') zustand.timezone = meta.timezone
  } catch {
    /* Without an answer, the optimistic default stands — the API locks
       down disabled features itself anyway. */
  }
}

/* The endpoint id of the agent server — the one word `SLOT_ENDPUNKT` in
   agentenserver.svelte.js says, kept here so this module needs no import
   of it (tests pin the two together). Its models are on the list for the
   runs and the agent mask, never for the chat's pick. */
const AGENT_SERVER_ID = 'agentenmodell'

/* The first model the chat may take of its own accord. */
function firstChatModel(list) {
  return list.find((m) => m.anbieter !== AGENT_SERVER_ID) ?? null
}

/* The provider a model id belongs to. The service names a model at a
   provider `provider:model` and a provider that names no model by its bare
   id; provider ids carry no colon (app/modellkennung.py). */
function providerOf(modelId) {
  return String(modelId).split(':')[0]
}

/* Counts the loads of the model list: of several in flight only the one
   started last may write. An outage sets off more than one at once — the
   service's announcement, the regular beat — and an older answer landing
   after a newer one would put the model back that has just dropped out. */
let modelLoadRun = 0

/* The list of reachable models, and what becomes of the chosen one.

   A chosen model that is not reachable stays chosen and stays stored:
   nothing switches by itself, at the start or while the window is open. The
   first model of the list is taken only where none is chosen yet, or where
   the service no longer carries the server of the chosen one — asked of the
   full list, the one that names unreachable servers too.

   The name stored with the choice follows the list: a server may run
   another model behind the same id, or name its model anew, and the stored
   name is what a start with the server away has to show. So where the
   list names the chosen model otherwise than stored, the choice is stored
   again under that name — the same choice, and without a word. Only a name
   the server reports is followed, not the one the configuration gives the
   server, and only while the service still holds this model as the choice:
   a name never changes which model is stored. */
export async function modelleLaden(frisch = false) {
  const run = ++modelLoadRun
  try {
    const known = aktuellesModell()
    const reachable = await api.modelle(frisch)
    if (run !== modelLoadRun) return
    const chosen = zustand.modellId
    const listed = chosen ? reachable.find((m) => m.id === chosen) : null
    if (!chosen || listed) {
      zustand.modelle = reachable
      zustand.unlistedModel = null
      const first = firstChatModel(reachable)
      if (!chosen && first) modellWaehlen(first.id)
      // An entry without a name says nothing about it: the stored one stays.
      // So does one whose name is only the one the configuration gives its
      // server: that names the server, and the model is not what it names.
      if (listed?.name && listed.name_gemeldet && listed.name !== keptModelName(chosen)) {
        // Read again first, and checked in the same breath it is written
        // in: where the service holds another model by now, another load has
        // started, or the window chose again while the read was out, nothing
        // is written and the window keeps showing the model it has.
        const held = await storedModelId()
        if (run === modelLoadRun && zustand.modellId === chosen && held === chosen) {
          modellSpeichern(chosen, listed.name)
        }
      }
      return
    }
    const all = await api.modelleAlle()
    if (run !== modelLoadRun) return
    // Chosen anew while the two requests were out: the list stands, and the
    // next load reads the new choice.
    if (zustand.modellId !== chosen) {
      zustand.modelle = reachable
      return
    }
    const provider = providerOf(chosen)
    const server = all.find((m) => m.id === chosen) || all.find((m) => m.anbieter === provider)
    zustand.modelle = reachable
    if (!server) {
      zustand.unlistedModel = null
      const first = firstChatModel(reachable)
      if (first) modellWaehlen(first.id)
      return
    }
    // The entry the window already had of it, else the one the service
    // still gives for this very id. Its name, in this order: the one the
    // window had, the one stored with the choice, the one of that entry —
    // the service names a server it cannot ask by its configured name, so
    // after a start with the server away the stored one is the only name
    // that is the model's. The word is the server's, as the service says
    // it now, and the model itself is not reachable whatever its entry
    // said while it was listed.
    const had = known?.id === chosen ? known : null
    const entry = had || (server.id === chosen ? server : null)
    const name = had?.name || keptModelName(chosen) || entry?.name
    zustand.unlistedModel = {
      ...entry,
      ...(name && { name }),
      id: chosen,
      anbieter: server.anbieter,
      erreichbar: false,
      server_state: server.server_state,
    }
  } catch {
    melde(t('modell.nicht_geladen'), 'fehler')
  }
}

/* The colour pack for code. `exe` is the house pack and follows light and
   dark; the other eight bring their own ground, which is the point of them —
   an editor pack that adapts to the app is not that pack anymore. */
export function codefarbenSetzen(paket, speichern = true) {
  zustand.codefarben = paket || 'exe'
  if (zustand.codefarben === 'exe') document.documentElement.removeAttribute('data-codefarben')
  else document.documentElement.setAttribute('data-codefarben', zustand.codefarben)
  if (speichern) darstellungSpeichern({ codefarben: zustand.codefarben })
}
codefarbenSetzen(zustand.codefarben, false)

/* A colour's apparent brightness — one reckoning for the bubble's ink and
   the frame's, threshold and all. */
function luma(farbe) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(farbe.slice(i, i + 2), 16) / 255)
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

/* The user's own bubble colour. Only that one surface — replies, tool
   chips and everything else keep the house palette. The text inside flips
   between the two ink colours by the luminance of the chosen ground, so
   no choice can make a bubble unreadable. */
export function blasenfarbeSetzen(farbe, speichern = true) {
  zustand.blasenfarbe = farbe || ''
  const wurzel = document.documentElement.style
  if (!farbe) {
    wurzel.removeProperty('--blase-eigen')
    wurzel.removeProperty('--blase-eigen-text')
  } else {
    wurzel.setProperty('--blase-eigen', farbe)
    wurzel.setProperty('--blase-eigen-text', luma(farbe) > 0.45 ? '#1a1a18' : '#ecebe6')
  }
  if (speichern) darstellungSpeichern({ blasenfarbe: zustand.blasenfarbe })
}
blasenfarbeSetzen(zustand.blasenfarbe, false)

/* The chat layout: in force at once, so the layout mode shows every change
   on the real chat; stored only when asked, which is the window's "Save". */
export function chatlayoutSetzen(werte, speichern = true) {
  zustand.chatlayout = { ...werte }
  chatlayoutAnwenden(zustand.chatlayout)
  if (speichern) darstellungSpeichern({ chat: chatlayoutZumSpeichern(zustand.chatlayout) })
}
chatlayoutSetzen(zustand.chatlayout, false)

/* The layout mode stands over the chat, so whatever menu was open gives way
   first — the settings it was opened from included. */
export function layoutModusOeffnen() {
  seitenSchliessen()
  zustand.layoutModusOffen = true
}

/* The frame the user repaints: the colours and the angle as properties
   `--frame` reads (its shape and the positions stay in the style sheet),
   the hue turning every colour of the run at once. Only what was changed
   is kept, per look; "Standard" deletes the entry. */
const RAHMEN_FELDER_MAX = 8

/* The device's reported scheme, read by the whole program: the look "auto"
   resolves to hangs on it, and the window's watcher (App) repaints when it
   flips. One state, one watcher — the settings panel reads along. */
export const geraet = $state({
  dunkel: typeof window !== 'undefined'
    ? Boolean(window.matchMedia?.('(prefers-color-scheme: dark)')?.matches)
    : false,
})

/** The look a modus stands on: "auto" follows the device's report. One
 *  rule for the settings panel and the painter, so the two can never edit
 *  and draw different looks. */
export function lookFuer(modus) {
  if (modus !== 'auto') return modus
  return geraet.dunkel ? 'dunkel' : 'snow'
}

/* Whether the document currently shows the look a fresh read would speak
   about: read under another look's sheet, the values belong to the wrong
   look, and kept they would stay wrong for the whole session. */
function stilPasstZu(schema) {
  const attr = document.documentElement.getAttribute('data-modus')
  if (schema === 'hell') return attr === 'hell'
  if (schema === 'snow') return attr === 'snow' || (attr === null && !geraet.dunkel)
  if (schema === 'dunkel') return attr === 'dunkel' || (attr === null && geraet.dunkel)
  return attr === schema
}

/* What a look's sheet brings, read once per look: the count is the first
   gap — a look with three colours marks the fourth absent — and the bound
   is only the loop's guard, never the truth. The sheet cannot change while
   the program runs, so a fitting answer is kept. */
const vorgabenJe = new Map()
const winkelJe = new Map()
const tonJe = new Map()

function vorgabenLesen() {
  const stil = getComputedStyle(document.documentElement)
  const liste = []
  for (let n = 1; n <= RAHMEN_FELDER_MAX; n += 1) {
    const wert = stil.getPropertyValue(`--rahmen-vorgabe-${n}`).trim()
    if (!wert) break
    liste.push(wert)
  }
  return liste
}

export function vorgabenFuer(schema) {
  if (!vorgabenJe.has(schema)) {
    const liste = vorgabenLesen()
    if (stilPasstZu(schema)) vorgabenJe.set(schema, liste)
    return liste
  }
  return vorgabenJe.get(schema)
}

export function winkelVorgabeFuer(schema) {
  if (!winkelJe.has(schema)) {
    const roh = parseInt(
      getComputedStyle(document.documentElement).getPropertyValue('--rahmen-winkel-vorgabe'),
      10,
    )
    const winkel = Number.isNaN(roh) ? 135 : roh
    if (stilPasstZu(schema)) winkelJe.set(schema, winkel)
    return winkel
  }
  return winkelJe.get(schema)
}

/* The hue a look's start turns its colours by: only the own gradient
   starts turned; every other look reads 0. */
export function tonVorgabeFuer(schema) {
  if (!tonJe.has(schema)) {
    const roh = parseInt(
      getComputedStyle(document.documentElement).getPropertyValue('--rahmen-ton-vorgabe'),
      10,
    )
    const ton = Number.isNaN(roh) ? 0 : roh
    if (stilPasstZu(schema)) tonJe.set(schema, ton)
    return ton
  }
  return tonJe.get(schema)
}

/* The one look whose gradient the user sets. */
export const EIGENER_VERLAUF = 'eigen'

/* Only what differs from what stands there is written: an angle drag then
   touches one property instead of repainting the whole viewport gradient
   per pointer event. */
function setzeFallsAnders(wurzel, name, wert) {
  if (wurzel.getPropertyValue(name) !== wert) wurzel.setProperty(name, wert)
}

function nimmFallsDa(wurzel, name) {
  if (wurzel.getPropertyValue(name) !== '') wurzel.removeProperty(name)
}

/* The look whose frame colour the shell heard last. The tone of a fixed
   look hangs on the look alone, so a redraw of the same look asks the sheet
   nothing — a drag on the own gradient redraws once per pointer event, and
   reading a computed style there would recalculate the styles each time.
   The own gradient carries its first colour in the key, as that is what the
   shell is told for it. */
let frameLookTold = ''

/* The window around the page opens before the page is there. So that it
   opens on the colour of the look instead of a dark ground, the page tells
   the shell the solid tone of its frame — at its start and whenever the
   look changes — and the shell keeps it for its next start. Read off the
   sheet as it applies right now, after the attributes the look hangs on are
   set; the own gradient hands in the colour it draws, as the shell opens on
   one colour only. In a browser there is no shell, and nothing is told. */
function frameColourToShell(look, drawn = null) {
  const tell = window.exeHuelle?.frameColour
  if (typeof tell !== 'function' || look === frameLookTold) return
  const colour = (
    drawn ??
    getComputedStyle(document.documentElement).getPropertyValue('--bg-seite')
  ).trim().toLowerCase()
  if (!/^#[0-9a-f]{6}$/.test(colour)) return
  frameLookTold = look
  tell(colour)
}

/* The fixed looks that stand on a dark ground. */
const DARK_LOOKS = ['dunkel', 'darkmatter']

/* The scheme the shell heard last. */
let frameSchemeTold = ''

/* Has the look the service keeps arrived? The page starts on the default
   look and draws the kept one once the service has answered. Said before
   that, the default's scheme would turn the title bar over at every start
   of a light look. A read that fails says nothing — the bar stays as the
   shell kept it, the way a look changed after such a read is not saved. */
let keptLookArrived = false

/* Where the system draws the window's title bar, the shell has it drawn to
   suit the look: `dark` or `light`, and `system` while the look follows the
   device — a forced scheme would also be what this page is told the device
   prefers, and the look could no longer follow it. Told when it changes, and
   on its own: the same look can stand under its own name and under "auto".
   In a browser there is no shell, and nothing is told. */
function frameSchemeToShell(scheme) {
  const tell = window.exeHuelle?.frameScheme
  if (typeof tell !== 'function' || !keptLookArrived || scheme === frameSchemeTold) return
  frameSchemeTold = scheme
  tell(scheme)
}

/** Draw the frame of the look a window is showing. Only the own gradient
 *  is painted here — the user's choice where there is one, its start
 *  otherwise; every fixed look draws the gradient its sheet gives it. The
 *  own gradient also says whether it is dark or light (`data-eigen`), and
 *  the sheet hangs Exe's or Pearl's values on that. Writes only properties
 *  and that one attribute — no rule changes. The shell hears the frame's
 *  colour and its scheme once the look stands. */
export function rahmenNeuZeichnen(modus) {
  const wurzel = document.documentElement.style
  const schema = lookFuer(modus)
  if (schema !== EIGENER_VERLAUF) {
    for (let n = 1; n <= RAHMEN_FELDER_MAX; n += 1) nimmFallsDa(wurzel, `--rahmen-farbe-${n}`)
    nimmFallsDa(wurzel, '--rahmen-winkel')
    nimmFallsDa(wurzel, '--rahmen-text')
    document.documentElement.removeAttribute('data-eigen')
    frameColourToShell(schema)
    /* "auto" is not always named here: a change of the gradient redraws
       under the name of the look "auto" stands on. The root carries no
       `data-modus` exactly while the look follows the device. */
    const follows = modus === 'auto' || !document.documentElement.hasAttribute('data-modus')
    frameSchemeToShell(follows ? 'system' : DARK_LOOKS.includes(schema) ? 'dark' : 'light')
    return
  }
  const wahl = zustand.verlauf[schema] || {}
  const ton = wahl.ton ?? tonVorgabeFuer(schema)
  const farben = (wahl.farben || vorgabenFuer(schema)).map((farbe) => farbtonDrehen(farbe, ton))
  farben.forEach((farbe, i) => setzeFallsAnders(wurzel, `--rahmen-farbe-${i + 1}`, farbe))
  for (let n = farben.length + 1; n <= RAHMEN_FELDER_MAX; n += 1) {
    nimmFallsDa(wurzel, `--rahmen-farbe-${n}`)
  }
  if (wahl.winkel != null) setzeFallsAnders(wurzel, '--rahmen-winkel', `${wahl.winkel}deg`)
  else nimmFallsDa(wurzel, '--rahmen-winkel')
  /* Light or dark by the mean brightness of the turned colours: the ink on
     the frame and the whole set of values follow it. */
  const hell = farben.reduce((summe, farbe) => summe + luma(farbe), 0) / farben.length > 0.45
  setzeFallsAnders(wurzel, '--rahmen-text', hell ? '#1a1a18' : '#ecebe6')
  const art = hell ? 'hell' : 'dunkel'
  if (document.documentElement.getAttribute('data-eigen') !== art) {
    document.documentElement.setAttribute('data-eigen', art)
  }
  /* The own gradient stands on the dark or on the light set of values, and
     the shell opens on the first colour of the gradient as it is drawn. */
  frameColourToShell(`${schema}:${art}:${farben[0] ?? ''}`, farben[0] ?? null)
  frameSchemeToShell(hell ? 'light' : 'dark')
}

/** The user changed one look's gradient; an empty value deletes the choice. */
export function verlaufSetzen(schema, wert, speichern = true) {
  const leer = !wert || (!wert.farben && wert.ton == null && wert.winkel == null)
  if (leer) delete zustand.verlauf[schema]
  else zustand.verlauf[schema] = wert
  rahmenNeuZeichnen(schema)
  if (speichern) darstellungSpeichern({ verlauf: { ...zustand.verlauf } })
}

// The same breakpoint Seitenleiste.svelte's own `@media` rule draws — one
// spelling, read by the toggle below, its watcher and the tool surface
// (flaeche.svelte.js), so none of them can drift to a different width.
export const SEITENLEISTE_SCHMAL_ABFRAGE = '(width < 760px)'

/* Read fresh, not cached: a caller mid-gesture (Seitengriff.svelte) reads
   this once at the gesture's START and hands the answer back in below,
   rather than letting a width crossed mid-drag pick the branch. */
export function istSeitenleisteSchmal() {
  return Boolean(window.matchMedia?.(SEITENLEISTE_SCHMAL_ABFRAGE)?.matches)
}

/* One toggle for every way in: the button beside the mark, the one on the
   folded icon bar, the handle on the seam and ⌘B. On the desktop the
   sidebar folds to the icon bar; below 760px the icon bar always stands
   and this opens and closes the full sidebar as a drawer over the chat
   (`offen` decides there, not `eingeklappt`). Below that width the desktop
   state is left alone and nothing is remembered — the drawer's open state
   is not a preference the way the collapsed sidebar is.

   `schmal` defaults to the width AT THIS CALL — right for ⌘B and a plain
   click, both instantaneous. A gesture spanning time (the seam dragged
   across the breakpoint) hands in the width its OWN start had instead, so
   crossing the breakpoint mid-drag cannot flip which branch the release
   takes. */
export function seitenleisteSchalten(schmal = istSeitenleisteSchmal()) {
  /* The user takes the sidebar into their own hands: what a menu saved
     about it is not theirs to restore any more. */
  sidebarBeforeMenu = null
  if (schmal) {
    zustand.seitenleisteOffen = !zustand.seitenleisteOffen
    return
  }
  zustand.seitenleisteEingeklappt = !zustand.seitenleisteEingeklappt
  zustand.seitenleisteOffen = false
  layoutSpeichern({ seitenleiste_zu: zustand.seitenleisteEingeklappt })
}

/* The search, from anywhere: ⌘K and the magnifier on the folded icon bar.
   The field lives in the full sidebar, so a folded one opens first (the
   drawer, below 760px) and the focus follows once the field stands. A menu
   standing open gives way to it: its sections are standing where the field
   lives, and the search is what was asked for. */
export function sucheZeigen() {
  if (eineSeiteOffen()) seitenSchliessen()
  if (zustand.seitenblatt !== 'chats') blattWechseln('chats')
  if (istSeitenleisteSchmal()) zustand.seitenleisteOffen = true
  else if (zustand.seitenleisteEingeklappt) seitenleisteSchalten(false)
  requestAnimationFrame(() => document.getElementById('suchfeld')?.focus())
}

/* `seitenleisteOffen` used to never become true — nothing ever set it —
   so a window widened back to 760 px or more with the drawer still
   marked open was unreachable. It is reachable now, and the desktop layout
   does not read `offen` at all, so nothing closes it on the way back. Left
   alone, narrowing the window again (no ⌘B in between) would spring the
   drawer open unprompted the moment the media query picks the stale flag
   back up. The query's own `change` event, not a raw `resize`: it fires
   once when the breakpoint is actually crossed, not on every pixel of a
   drag (agentenfarbe.svelte.js's dark-mode watcher uses the same event for
   the same reason).

   Named, not inline: the dev server's HMR can only unregister a listener it
   can name, and an inline arrow handed straight to addEventListener has no
   name to unregister BY — agentenfarbe.svelte.js's own module-flag guard
   does not actually stop this either, since a module re-evaluation resets
   that very flag together with everything else in the module.
   The dispose call is dev-only; a built program never re-evaluates this
   module, so nothing here changes what ships. */
function seitenleisteSchmalGeaendert(ereignis) {
  if (zustand.seitenleisteOffen && !ereignis.matches) {
    zustand.seitenleisteOffen = false
  }
}
if (typeof window !== 'undefined') {
  const seitenleisteSchmalAbfrage = window.matchMedia?.(SEITENLEISTE_SCHMAL_ABFRAGE)
  seitenleisteSchmalAbfrage?.addEventListener?.('change', seitenleisteSchmalGeaendert)
  if (import.meta.hot) {
    import.meta.hot.dispose(() => {
      seitenleisteSchmalAbfrage?.removeEventListener?.('change', seitenleisteSchmalGeaendert)
    })
  }
}

/* The sidebar is dragged, not configured: the seam clamps the hand to what
   the head row can carry (below, the section labels would clip) and to what
   still leaves the chat its room. */
// Five 40px signs of the window row, spread with 12px either side: at this
// width they stand a little over 15px apart, and no sign of the row ever has
// to shrink.
const SEITEN_MIN = 285
const SEITEN_MAX = 400

export function seitenBreiteSetzen(px) {
  zustand.seitenBreite = Math.round(Math.min(SEITEN_MAX, Math.max(SEITEN_MIN, px)))
  layoutSpeichern({ seitenleiste_breite: zustand.seitenBreite })
}

/* Which open is the youngest. `chatOeffnen` is a round trip long, and several
   of them can be in the air at once — a switch on top of a reconnection, or a
   click on a chat whose fetch has not answered yet. Only the youngest one may
   write its rows or say anything about a failure: an older one would drag the
   reader back to a chat they have left, with a list that belongs to it. Not
   part of `zustand`: no window shows this, and it must not be written back. */
let oeffnungsLauf = 0

/* Guards `chatsLaden` the same way `oeffnungsLauf` guards a chat open: it
   now runs on every chat switch too, on top of its older callers
   (search, a finished send), so two calls in flight at once are the normal
   case, not a rare one — the search box changing between two switches, or a
   slower switch's own call landing after a faster later one's. Without this
   the older answer can overwrite `zustand.chats` with what is already a
   stale list. */
let chatsLadenLauf = 0

/* Chooses a model and stores the choice, the name with the id: whatever
   chooses — the picker, a chat's own model, the first of the list — chooses
   among the listed models, and the list names them. */
export function modellWaehlen(id) {
  zustand.modellId = id
  modellSpeichern(id, aktuellesModell()?.name)
}

/* The look and the two panel positions as the service hands them out — set
   without writing them straight back, or the first start would save the
   defaults over what was just read. The attribute logic is the setters'
   own, so applying goes through them rather than around them. */
export function darstellungAnwenden(wert) {
  /* From here on the look drawn is the kept one, and the shell may hear its
     scheme. */
  keptLookArrived = true
  codefarbenSetzen(wert.codefarben, false)
  blasenfarbeSetzen(wert.blasenfarbe, false)
  zustand.verlauf = wert.verlauf && typeof wert.verlauf === 'object' ? wert.verlauf : {}
  chatlayoutSetzen(chatlayoutAusGespeichert(wert.chat), false)
}

export function seitenleisteAnwenden(wert) {
  zustand.seitenleisteEingeklappt = wert.seitenleiste_zu
  zustand.seitenBreite = Math.round(
    Math.min(SEITEN_MAX, Math.max(SEITEN_MIN, wert.seitenleiste_breite)),
  )
}

export function modellAnwenden(id) {
  zustand.modellId = id
}

export async function chatsLaden() {
  const meinLauf = ++chatsLadenLauf
  const suche = zustand.suche.trim()
  /* While searching, the sidebar shows the hits and nothing else, so the
     projects and the archive are not asked for. Each answer stands on its
     own: an archive that cannot be read must not keep the chats themselves
     from arriving. */
  // Through a promise, so a call that throws at once counts as a failed
  // answer too instead of escaping.
  const ask = (call) => Promise.resolve().then(call)
  const [geholt, projects, archivedChats, archivedProjects] = await Promise.allSettled([
    ask(() => api.chats(suche)),
    ask(() => (suche ? null : api.projects())),
    ask(() => (suche ? null : api.archivedChats())),
    ask(() => (suche ? null : api.projects(true))),
  ])
  // A superseded call says nothing about what stands on screen — a younger
  // call may already have applied a fresh list, failed or not.
  if (meinLauf !== chatsLadenLauf) return
  if (geholt.status === 'fulfilled') zustand.chats = geholt.value
  if (!suche && projects.status === 'fulfilled') zustand.projects = projects.value
  if (!suche && archivedChats.status === 'fulfilled' && archivedProjects.status === 'fulfilled')
    zustand.archive = { chats: archivedChats.value, projects: archivedProjects.value }
  if ([geholt, projects, archivedChats, archivedProjects].some((answer) => answer.status === 'rejected'))
    melde(t('chat.nicht_geladen'), 'fehler')
}

/* Replaces the shown list and tags it with the chat it now belongs to —
   the one place that does both, so the two can never drift apart. Every
   fetch or reset that could hand `zustand.nachrichten` a DIFFERENT chat's
   rows goes through this. An edit that only trims or amends the current
   chat's own rows in place (push, splice, a `.filter()` over the same
   list) does not — it never changes which chat the list belongs to, so
   `nachrichtenChatId` has nothing to catch up on. */
export function nachrichtenSetzen(chatId, liste) {
  zustand.nachrichten = liste
  zustand.nachrichtenChatId = chatId
}

/* What the open chat actually shows: `zustand.nachrichten` itself once a
   failed reopen has left it tagged for a chat that is no
   longer the active one. Every reader of the message list that decides
   what belongs to the chat ON SCREEN — the transcript, the context gauge,
   the terminal panel, the status dot — goes through this, not the raw
   field, so a stale list never leaks into any of them. A plain function,
   not `$derived`: read from inside a template or another `$derived` it is
   just as reactive, and unlike `$derived` it stays valid where the state
   fields it reads are stood in for outside a Svelte build (`kontextStand`
   below already reads `zustand.*` the same way for the same reason). */
export function nachrichtenAnzeige() {
  return zustand.nachrichtenChatId === zustand.aktiverChat ? zustand.nachrichten : []
}

/* The one shape of a picture still drawing in a chat — the working tile of
   a model's drawing call. */
function bildlaufPlatzhalter(chatId) {
  return {
    // Own stable key, not null: the list's #each keys on `id`, and a
    // message without one used to fall back to its POSITION — two
    // different pictures taking the same slot one after the other then
    // counted as the same thing and Svelte refilled the old tile instead
    // of building a new one (the second cat appeared where the first one
    // had been). One running picture per chat, so the chat's id makes this
    // unique, and no server id ever looks like it.
    id: `bildlauf-${chatId}`,
    role: 'assistant', content: '', bildLaeuft: true, stats: {}, werkzeuge: [],
  }
}

/* The calls that make a picture or a video while the model answers: both
   stand in the chat the same way — the working tile while they run, the
   finished file at once. One list, so the two places that ask agree. */
export function isDrawingTool(name) {
  return name === 'draw_image' || name === 'draw_video'
}

/* Whether the drawing call this answer is running right now makes a video:
   the word on its working tile says "video" instead of "picture". The
   picture window's own tile has no answer behind it and stays a picture. */
export function drawingMakesVideo(answerId) {
  if (answerId == null) return false
  const answer = zustand.nachrichten.find((n) => n.id === answerId)
  return Boolean(answer?.werkzeuge?.some((w) => w.name === 'draw_video' && w.ergebnis == null))
}

/* The same working tile for a picture or a video the model makes while it
   answers (`draw_image`, `draw_video`), with a key of its own: the picture
   window can be drawing in the same chat at the same time, and two rows
   under one key stop the list from drawing. `answerId` names the answer
   whose run it joins. */
export function answerDrawingTile(chatId, answerId) {
  return { ...bildlaufPlatzhalter(chatId), id: `bildlauf-${answerId}`, answerId }
}

/* The rows a wholesale replace of `nachrichten` would otherwise drop: the
   question bubble of a send still on its way, and — with a document — the
   answer row born before the request. Read before the replace, handed to
   `eigeneZeilenZurueckgeben` after it. Shared by `chatOeffnen` below and
   the picture reconcile in App.svelte, which used to lack this rescue
   entirely — a question sent while a picture was still
   drawing vanished until the upload finished. */
export function eigeneZeilenSichern(chatId) {
  return zustand.sendet[chatId]
    && zustand.nachrichten.some((n) => n.id === `platzhalter-${chatId}`)
    ? zustand.nachrichten.filter(
        (n) => String(n.id).startsWith('eigen-') || n.id === `platzhalter-${chatId}`,
      )
    : []
}

/* The counterpart: puts rows `eigeneZeilenSichern` read back onto the list
   that just replaced them — skipped only when the very same row (by
   identity or by its own id) is already there. Matching by CONTENT used
   to stand here as well, so a second, still-unsaved copy of a question
   already answered once looked like the same question and never
   appeared — sending the same line twice showed only one
   bubble until the second run had saved its own row. Identity is what
   the server tells apart; the wording never was. */
export function eigeneZeilenZurueckgeben(zeilen) {
  for (const zeile of zeilen) {
    /* The question this window sent carries the id it gave the service
       with the request (App.svelte, senden()) under its local `eigen-`
       shape. The very row the fetch above just brought back therefore
       already stands in the list — under that same id, bare, once the
       service has stored it — and is not a different row to rescue. */
    const kennung = String(zeile.id).startsWith('eigen-') ? zeile.id.slice('eigen-'.length) : null
    if (zustand.nachrichten.some((n) => n === zeile || n.id === zeile.id || (kennung && n.id === kennung))) {
      continue
    }
    zustand.nachrichten.push(zeile)
  }
}

export async function chatOeffnen(id) {
  // Without a chat there is nothing to fetch. If this guard were missing,
  // the interface would query `/chats//messages` — with a double slash,
  // because the id is empty — and catch a 404 every few seconds,
  // cluttering the log.
  // Another chat or none: a value waiting for a chat that never came is void.
  zustand.pendingPromptOff = false
  if (!id) {
    zustand.aktiverChat = null
    nachrichtenSetzen(null, [])
    chatZustandLaden(null)
    return
  }
  /* Whatever this chat was owed from an earlier look is void before the new
     look starts. The entry below says "the service is writing an answer here
     that this window has never heard of", and that claim rested on ONE
     observation — the `laufend` field of the fetch further down — which was
     never taken back. A run that ended while a DIFFERENT chat was on screen
     therefore left its entry lying: the effect in App.svelte spends it the
     next time this chat becomes active, replays a generation the service
     dropped long ago (fifty runs on, or a restart — app/generationen.py
     keeps the last fifty), both attempts answer 404, and what is left is an
     empty bubble beside the finished answer under an error notice.

     Withdrawn HERE rather than beside the fetch, and that is the whole
     point: `zustand.aktiverChat = id` on the next line is what wakes that
     effect, and Svelte flushes it on the following microtask — a full round
     trip before any answer from the service arrives. A withdrawal placed
     after the fetch would always come too late to stop the very open that
     triggers it. It has to stand in the same synchronous breath as the
     assignment it guards.

     Nothing is lost by clearing first: if a run really is going, the fetch
     writes the entry again from what the service says right now, and by then
     this chat's rows are in `zustand.nachrichten` — so the resume finds the
     row it is meant to adopt instead of pushing a second placeholder beside
     it. A plain reload mid-run is unaffected: there is no entry to clear,
     and the fetch makes one.

     Only THIS chat's entry goes. Another chat's owed reattachment is none of
     this open's business — that is what the map is for. */
  /* A look at the chat that is ALREADY on screen is not a switch. The
     service is asked again on purpose — a reconnection, or a background run
     that left a report behind (`lib/ereignisstrom.svelte.js`,
     `lib/terminalfenster.svelte.js`) — and what comes back is adopted; but
     the side effects that belong to an OPEN stay out of it: they answer
     "what does this NEW chat start from" (its own picture window, its own
     model), and for the chat already on screen that answer was given.
     Giving it again threw away the sentence just typed into the picture
     window and the model just picked. Only a switch — including
     the first open, where there is no chat yet — does all of it. */
  const meinLauf = ++oeffnungsLauf
  const vorher = zustand.aktiverChat
  /* The model pick is one of them and is put back on the way out: it is set
     for the NEW chat before the fetch has answered, so a failed open has to
     take it back — otherwise the reader sends with the model of a chat that
     never opened. `modellAnwenden` and not `modellWaehlen`: putting the old
     value back is not a choice worth storing. */
  const modellVorher = zustand.modellId
  const wechsel = vorher !== id
  delete zustand.wiederanhaengen[id]
  zustand.aktiverChat = id
  if (wechsel) {
    /* What this conversation left standing — its picture window and where it
       was being read. Started here rather than awaited: the messages are what
       the reader is waiting for, and this must not hold them up. It flushes
       whatever was still waiting for the chat being left, so a sentence typed
       a moment ago stays with the chat it was typed in. */
    chatZustandLaden(id)
    /* The list this window is holding was last current at its own mount, or
       whenever this window itself last sent or watched something — a run
       another window started meanwhile has no way to reach it otherwise.
       Every switch is a natural, cheap place to catch up;
       unawaited for the same reason as the fetch above. */
    chatsLaden()
  } else if (chatanzeige.chatId !== id || !chatanzeige.geladen) {
    /* Not a switch, but this chat's own state is not the one standing here
       either: either the window holds ANOTHER chat's (or none, when the chat
       was activated by a path that never went through this function — a send
       from the queue, the CLI, a shared folder), or the read failed last time
       and is owed. Asking the question "is this chat's state already here?"
       rather than "is this a switch?" is what covers both. */
    chatZustandLaden(id)
  }
  chatFertigGesehen(id)
  if (wechsel) {
    /* The model pick and the drawer are the other two that belong to a
       switch, and they are set HERE, before the fetch: a second open of the
       same chat can arrive while this one is still on its way — a double
       click, or a reconnection falling into the same stretch — and that
       second one reads `wechsel` as false. Applied only after the messages
       had arrived, the chat's own model would then never be picked, and the
       reader would go on sending with the previous chat's model, which the
       service writes down on the chat (App.svelte sends `zustand.modellId`).
       The drawer goes with it for a different reason: on a narrow window it
       lies over the chat, so a chat that was just chosen is behind it until
       it closes. */
    const chat = aktuellerChat()
    const carried = chat?.endpoint_id
      ? zustand.modelle.find((m) => m.id === chat.endpoint_id)
      : null
    if (carried && carried.anbieter !== AGENT_SERVER_ID) {
      modellWaehlen(carried.id)
    } else if (carried) {
      // A chat that carries a model of the agent server takes the first
      // model of the chat's own choice, like a chat whose server is gone.
      const first = firstChatModel(zustand.modelle)
      if (first) modellWaehlen(first.id)
    }
    zustand.seitenleisteOffen = false
  }
  let laufend
  let geholt
  try {
    geholt = await api.nachrichten(id)
  } catch {
    /* A failure of a look nobody is waiting for any more — a younger open
       owns the screen, or the chat was left — says nothing about what stands
       there. For the one that counts, the model goes back to the one from
       before the click, and the notice says that the look failed.

       A switch that failed lands on the start page, as after "New chat":
       no chat is selected and no row is shown, so nothing of another
       conversation stands under the name of the one that was asked for. A
       look at the chat that is already open is not a switch: that chat
       stays selected and its list keeps standing — a chat that was readable
       a moment ago does not become empty because the service did not
       answer. */
    if (meinLauf !== oeffnungsLauf || zustand.aktiverChat !== id) return
    if (wechsel) neuerChat()
    modellAnwenden(modellVorher)
    melde(t('chat.nicht_geoeffnet'), 'fehler')
    return
  }
  /* A fetch that was overtaken — a younger open for another chat — has
     nothing to say about what stands on screen now; its rows belong to a
     conversation the reader has left. */
  if (meinLauf !== oeffnungsLauf || zustand.aktiverChat !== id) return
  /* The rows this window holds and the service does not: the question bubble
     of a send that is on its way, and — with a document — the answer row born
     before the request (`App.svelte`). Read HERE, after the fetch and before
     the list is replaced, so a question typed while the fetch ran is in the
     snapshot as well.

     Taken only while a send of THIS chat is on its way — and only when the
     list standing here is really this chat's list. The answer row born with
     that send carries the chat's own id (`platzhalter-<chat>`), so finding it
     is what proves whose list this is: a list belonging to another chat could
     otherwise be scanned for `eigen-…` rows and have one of them carried over
     into this chat. */
  const eigeneZeilen = eigeneZeilenSichern(id)
  nachrichtenSetzen(id, geholt.nachrichten)
  laufend = geholt.laufend
  /* The open ask_user question, the same shape a live `user_ask` event
     builds (App.svelte) — delivered here so a window that left the chat or
     reloaded shows the question again instead of it being gone for good.
     Only adopted alongside a live run: answering needs a
     `generationId` to send the answer to (`benutzerfrageBeantworten`
     below), and there is none for a question the service remembers but
     nothing is left running to hand it to. */
  if (geholt.frage && laufend) {
    zustand.benutzerfrage[id] = {
      generationId: laufend.generation_id,
      aufrufId: geholt.frage.aufruf_id,
      frage: geholt.frage.frage,
      optionen: geholt.frage.optionen || [],
      chatId: id,
      nummer: 1,
    }
  } else {
    delete zustand.benutzerfrage[id]
  }
  /* Same rescue for a running TEXT answer: the reload above just as freely
     dropped the platzhalter message App.svelte is still writing into. The
     run itself was never touched — it kept going in the background the
     whole time this chat was closed — so putting the SAME object back is
     enough; the rest of its sections just keep arriving. */
  const meinPlatzhalter = zustand.laufenderPlatzhalter[id]
  if (zustand.laeuft[id] && meinPlatzhalter) {
    /* Not `includes`: that asks whether this very OBJECT stands in the
       list, and the fetch above never returns it. What it does return is
       the server's own row for the SAME answer — `generierung.py` writes
       it the moment the run starts and keeps it current while the run goes
       — a different object carrying the same id. Standing the platzhalter
       next to it left two rows under one id, and `App.svelte`'s
       `{#each ... (nachricht.id ?? i)}` answers that with
       `each_key_duplicate`: Svelte stops drawing mid-tree, and a half-drawn
       tree has no valid heights — the history collapses under the input
       zone instead of above it.
       So the stored row is REPLACED by the platzhalter, not joined by it.
       Which of the two has to stay is not a free choice: App.svelte writes
       into the platzhalter by reference, so keeping the server's row would
       freeze the answer at whatever was last flushed to the database. */
    const stelle = zustand.nachrichten.findIndex(
      (n) => n === meinPlatzhalter
        || (meinPlatzhalter.id != null && n.id === meinPlatzhalter.id),
    )
    if (stelle === -1) zustand.nachrichten.push(meinPlatzhalter)
    else if (zustand.nachrichten[stelle] !== meinPlatzhalter) {
      zustand.nachrichten[stelle] = meinPlatzhalter
    }
    /* And a picture or a video that answer's model is making right now
       (`draw_image`, `draw_video`): the same working tile the picture
       window's picture gets back above, for the same reason — it lives here
       alone. */
    if (meinPlatzhalter.werkzeuge?.some((w) => isDrawingTool(w.name) && w.ergebnis == null)
        && !zustand.nachrichten.some((n) => n.answerId === meinPlatzhalter.id)) {
      zustand.nachrichten.push(answerDrawingTile(id, meinPlatzhalter.id))
    }
  } else if (laufend && !zustand.laeuft[id]) {
    /* The rescue above already covers this chat from THIS window's own
       memory — only reached when it does not: nothing here has ever heard
       of THIS run before, which is the reload case. A run in a DIFFERENT
       chat no longer blocks this — every chat gets its own reattachment. */
    /* `messageId` travels with it: the server says WHICH row the run is
       writing, so the resume adopts that row instead of working it out
       from the list. Deducing it was how a background report or a picture
       got adopted as the answer and overwritten. */
    /* A run without a named row should not be possible — every chat run
       registers with one — but the field is nullable all the way down, and
       a resume that cannot name its row pushes a second placeholder next to
       the stored answer and shows the same text twice. That was the whole
       defect this replaced, so it says so out loud rather than failing
       quietly the way the old positional reading did. */
    if (!laufend.message_id) {
      console.warn('Running generation without message_id', laufend.generation_id)
    }
    zustand.wiederanhaengen[id] = {
      chatId: id,
      generationId: laufend.generation_id,
      messageId: laufend.message_id ?? null,
    }
  }
  /* And the rows of a send that is still on its way, each one the fetch did
     not bring: the question bubble, and with a document the answer row born
     before the request. */
  eigeneZeilenZurueckgeben(eigeneZeilen)
}

export function neuerChat() {
  zustand.seitenblatt = 'chats'
  zustand.aktiverChat = null
  zustand.pendingPromptOff = false
  nachrichtenSetzen(null, [])
  // A fresh chat starts on the defaults — and what was still waiting for
  // the one being left goes out first.
  chatZustandLaden(null)
}

/* Jobs (6.5). Loaded on switching over and then on a cadence as long as
   the section is open — the cadence is set by the component, not the
   state. */
/* Which fetch of the job list is the newest. Two can be under way at once —
   a run's last context reading and its end are announced a moment apart —
   and the answers can come back in either order; only the one asked last
   may land, or the list goes back to a state the run has already left. */
let auftragslisteNr = 0

async function auftragslisteHolen() {
  const nr = ++auftragslisteNr
  const liste = await api.auftraege()
  if (nr === auftragslisteNr) zustand.auftraege = liste
}

export async function auftraegeLaden() {
  try {
    await auftragslisteHolen()
  } catch {
    melde(t('jobs.nicht_geladen'), 'fehler')
  }
}

/* The quiet variant, for background cadences (the agents module and its
   sign on the strip): a failed fetch stays silent — a restarting service
   must not answer a mere overview with a toast salvo, and the next tick
   tries again anyway. */
export async function auftraegeStillLaden() {
  try {
    await auftragslisteHolen()
  } catch {
    /* The cadence retries — nothing to say meanwhile. */
  }
}

export async function auftragLoeschen(id) {
  await api.auftragLoeschen(id)
  if (zustand.auftragAusgewaehlt === id) zustand.auftragAusgewaehlt = null
  await auftraegeLaden()
}

export function blattWechseln(blatt) {
  zustand.seitenblatt = blatt
  // The sheet lists the jobs below the agents — fresh on arrival.
  if (blatt === 'agenten') auftraegeLaden()
}

export async function chatAendern(id, daten) {
  const geaendert = await api.chatAendern(id, daten)
  const stelle = zustand.chats.findIndex((c) => c.id === id)
  if (stelle !== -1) zustand.chats[stelle] = geaendert
  await chatsLaden()
  return geaendert
}

/* Projects and the archive. Every change reloads the
   list: a chat moving into a project changes the folders of every chat in
   it, and the list is where the sidebar and the folder chip read them. A
   chat or project put away while it is the one open leaves the window for
   a new chat, the way deleting it always did. */
export async function projectCreate(name) {
  const project = await api.projectCreate(name)
  await chatsLaden()
  return project
}

export async function projectUpdate(id, data) {
  await api.projectUpdate(id, data)
  if (data.archived && aktuellerChat()?.project_id === id) neuerChat()
  await chatsLaden()
}

/* The service answers with the chats that went with the project, and the
   window lets go of each the way it does for one deleted chat. The list is
   read again even when the delete fails half way: some chats may be gone
   already, and asking again deletes the rest. */
export async function projectDelete(id) {
  try {
    const chatIds = await api.projectDelete(id)
    for (const chatId of chatIds || []) forgetChat(chatId)
  } finally {
    await chatsLaden()
  }
}

export async function chatMoveToProject(chatId, projectId) {
  await api.chatAendern(chatId, { project_id: projectId })
  await chatsLaden()
}

export async function chatArchive(chatId, archived) {
  await api.chatAendern(chatId, { archived })
  if (archived && zustand.aktiverChat === chatId) neuerChat()
  await chatsLaden()
}

export async function chatLoeschen(id) {
  await api.chatLoeschen(id)
  forgetChat(id)
  await chatsLaden()
}

/* What the window keeps for a chat, let go once the chat is deleted — one
   chat through the archive's menu, or every chat of a project deleted
   there. */
function forgetChat(id) {
  /* The queue belongs to the chat and goes with it. Left behind, its
     entries would wait for a conversation that no longer exists. */
  warteschlangeLeeren(id)
  /* The per-chat run bookkeeping goes with the chat too. A stream's own
     finally clears most of these when it ends, but a chat deleted before
     that — or one that only ever carried an owed reattachment — would keep
     its entry for the life of the session. */
  delete zustand.laeuft[id]
  delete zustand.sendet[id]
  delete zustand.laufenderPlatzhalter[id]
  delete zustand.wiederanhaengen[id]
  delete zustand.werkzeugfrage[id]
  delete zustand.benutzerfrage[id]
  delete zustand.jobfrage[id]
  if (zustand.aktiverChat === id) neuerChat()
}

/* `gesamt_tokens` rather than `nutzung.total_tokens`: the backend now sets
   it for every provider (app/api/v1/generierung.py), already unified —
   `nutzung` is a raw passthrough of whatever the model server happens to
   call its usage block, and Anthropic never built one at all, which used
   to leave this stuck at zero for every Claude chat regardless of how long
   the conversation grew. Reading only the prompt half instead would
   undercount by the last answer's own length.

   A message saved before this change only has the old field — falling
   back to it, the same way app/kontextverbrauch.py's tokens_aus_messwerten
   does it for a job, keeps an existing long chat's reading from dropping to
   zero until the next answer arrives and refills the new one. Null-safe on
   its own so every caller can just `?? 0` rather than guard the message
   too. */
function gesamtTokensVon(nachricht) {
  /* The row's own column first. It is the only reading a RUNNING answer
     has: the metrics blob is written once, when the answer is over, while
     this one is refilled every half second as the answer grows — by the
     `kontext` event in App.svelte here, and by `tokenstand_setzen` in the
     row on the server, so a window opening the chat cold mid-run finds it
     too. Once an answer is finished the two say the same thing, so nothing
     below this line changes for a stored chat. */
  if (nachricht?.gesamt_tokens != null) return nachricht.gesamt_tokens
  if (nachricht?.stats?.gesamt_tokens != null) return nachricht.stats.gesamt_tokens
  const nutzung = nachricht?.stats?.nutzung
  if (nutzung?.total_tokens != null) return nutzung.total_tokens
  // Either half missing is not the same as both missing — a server that
  // only reported one side still said something usable (mirrors
  // app/kontextverbrauch.py's tokens_aus_messwerten).
  const eingang = nutzung?.prompt_tokens
  const ausgang = nutzung?.completion_tokens
  if (eingang != null || ausgang != null) return (eingang ?? 0) + (ausgang ?? 0)
  return null
}

/* How full is the context?

   The number comes from the usage data of the last answer, the ceiling
   from the model server. Where one of them is missing, nothing is made
   up.

   A RUNNING answer wins as soon as it carries a number, and it is found by
   identity, never by position: `laufenderPlatzhalter` is the very object
   the stream writes into (App.svelte), and `zustand === 'laeuft'` covers a
   run this window did not start, whose row the server marks as live. The
   reverse-search below is the fallback for everything else — a chat with
   nothing running — and it is only a fallback because "the last row in the
   list" is not the same question as "the answer": a picture or a finished
   background command lands behind a live answer just as easily. */
export function kontextStand() {
  const sichtbar = nachrichtenAnzeige()
  const laufend =
    zustand.laufenderPlatzhalter[zustand.aktiverChat]
    ?? sichtbar.find((n) => n.zustand === 'laeuft')
  const letzte = gesamtTokensVon(laufend) != null
    ? laufend
    : [...sichtbar].reverse().find((n) => gesamtTokensVon(n) != null)
  const gesamt = aktuellesModell()?.context_tokens || null
  const genutzt = gesamtTokensVon(letzte) ?? 0
  return {
    genutzt,
    gesamt,
    anteil: gesamt ? Math.min(100, (genutzt / gesamt) * 100) : 0,
  }
}
