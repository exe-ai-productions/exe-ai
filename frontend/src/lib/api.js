/*
  All access to the API in one place.

  No component talks to the server on its own. That keeps error handling
  uniform and makes it easy to hook something in later — say, authentication
  once login arrives.
*/

const BASIS = '/api/v1'

/* How many messages one page of a chat holds. The same number the route
   defaults to (app/api/v1/chats.py), written down here because the window
   now names it — a page it did not ask for is a page it cannot ask for the
   one before. */
const SEITE = 500

/* The session key (Schritt 25): stitched into the served page itself by
   app/main.py, so the frontend never has to ask for it and the user never
   sees it happen. Every /api/v1 call needs it now, reading included —
   without it, any program on this machine could call the API directly and
   read every chat, the same way curl could before this. */
let SCHLUESSEL = typeof window !== 'undefined' ? window.__SITZUNGSSCHLUESSEL__ : undefined

/* A page served without a key — the service demands a password and the
   key is not in the page — gets it from the sign-in (teile/Anmeldung.svelte)
   and keeps it here from then on: for every call, and for the two
   addresses the browser loads itself. */
export function setSessionKey(key) {
  SCHLUESSEL = key || undefined
}

/* For the two places a browser cannot attach a custom header at all —
   EventSource and a plain <img src>/href. */
function mitSchluessel(url) {
  if (!SCHLUESSEL) return url
  return `${url}${url.includes('?') ? '&' : '?'}schluessel=${encodeURIComponent(SCHLUESSEL)}`
}

/* A refused key means one thing: the service was restarted, and this page
   still carries the key of the one before it. Every call is refused from
   then on — and the page kept asking for the rest of the day. Measured on
   2026-09-09: one window, 27 000 refused calls in seven hours, "model could
   not be loaded" on screen, and nothing said that a reload would heal it.

   So the page reloads itself, which fetches the new key with the new page.
   ONCE: a refusal within a minute of the last reload means the key is wrong
   for another reason, and a loop would only hide that. What is typed but
   not sent is handed to the input bar first (`exe-ai:vor-neuladen`), which
   parks it and puts it back after the reload. Returns whether a reload was
   set off, so a caller can tell "on its way out" from "refused for good". */
const NEULADE_MARKE = 'exe-ai:sitzung-neu-geladen'
const NEULADE_SPERRE_MS = 60_000
/* Beyond the minute: a key that stays wrong after a reload — a cached page
   still carrying the old one — is not healed by reloading again, and a page
   that reloaded itself every minute all day threw away whatever stood on
   it each time. So at most a few reloads in a longer stretch, then the
   refusal is left standing where it can be seen. */
const NEULADE_FENSTER_MS = 10 * 60_000
const NEULADE_HOECHSTENS = 3
export function sitzungNeuLaden() {
  if (typeof window === 'undefined') return false
  /* A page that never had a key has none to be stale: a refusal there is a
     wrong password at the sign-in, which the sign-in shows — a reload would
     only throw the typed word away and ask it again. */
  if (!SCHLUESSEL) return false
  let bisher = []
  try {
    const gemerkt = JSON.parse(sessionStorage.getItem(NEULADE_MARKE) || '[]')
    bisher = Array.isArray(gemerkt) ? gemerkt.map(Number).filter(Number.isFinite) : []
  } catch {
    bisher = []
  }
  const jetzt = Date.now()
  const juengste = bisher.filter((zeit) => jetzt - zeit < NEULADE_FENSTER_MS)
  const zuletzt = juengste.length ? Math.max(...juengste) : 0
  if (jetzt - zuletzt < NEULADE_SPERRE_MS) return false
  if (juengste.length >= NEULADE_HOECHSTENS) return false
  /* The mark has to be written before the page goes, or the next page
     cannot tell "just reloaded" from "never". Where the tab's storage is
     not there to hold it — site data blocked, some private windows —
     there is no lock at all, and a reload without one is the loop this
     mark exists to prevent. Then the refusal stands instead. */
  try {
    sessionStorage.setItem(NEULADE_MARKE, JSON.stringify([...juengste, jetzt]))
  } catch {
    return false
  }
  window.dispatchEvent(new CustomEvent('exe-ai:vor-neuladen'))
  window.location.reload()
  return true
}

/* The language the interface runs in. The browser's own header says the
   system language — whoever switched the app in the settings would get
   answers in the wrong one. Set once the catalogue is there (texte.svelte.js),
   so it is always the language on screen and never one being switched TO; a
   plain variable instead of an import, because the text module imports this
   one. */
let sprache = null

/* The header every request carries it in. Named once: the one call that has
   to speak a language the window does not show yet (`uebersetzungen`) and
   `sprachkopf` below would otherwise spell it twice. */
const LANGUAGE_HEADER = 'X-Ui-Language'

export function spracheMerken(neue) {
  sprache = neue
}

/* The language the interface shows, for the service's own sentences (a
   confirmation's reason, an error). Every fetch carries it, the chat
   streams included; the browser's Accept-Language only knows the system's
   language (app/api/abhaengigkeiten.py, hole_sprache). Addresses the
   browser loads itself (EventSource, an image's src, a download link)
   cannot carry a header and keep the system's language. Set once the
   catalogue is there (texte.svelte.js) — which means: it is always the
   language on screen, never one being switched to. The single call that
   needs the other one carries it for itself (`uebersetzungen`). */
function sprachkopf() {
  return sprache ? { [LANGUAGE_HEADER]: sprache } : {}
}

/* The two sentences the page has to be able to show before the catalogue is
   there: the message of a start that failed and the name of a refusal that
   came without a reason. The page carries them itself, in the language the
   service knows for the interface — stitched in beside the session key by
   app/main.py. A sentence of this file's own must NOT stand here: one
   language read off a hard-coded German line is what these replaced. */
const PRE_CATALOGUE = (typeof window !== 'undefined' && window.__TEXTE__) || {}

/* The page's sentence with its placeholder filled. Every occurrence, the
   same way `t()` fills a catalogue text once the window is standing
   (texte.svelte.js) — one key, one wording, however it is written. Without
   a sentence — a page from the dev server carries none — the bare value
   stands: an empty spot says more than a sentence in the wrong language. */
function fillSentence(template, field, value) {
  if (typeof template !== 'string') return String(value)
  return template.split(`{${field}}`).join(String(value))
}

/* The boot message for main.js — the one text of this file another module
   needs. It is shown when the catalogue itself did not arrive, so it cannot
   come from the catalogue. */
export function bootMessage(fehler) {
  return fillSentence(PRE_CATALOGUE.dienst_antwortet_nicht, 'error', fehler?.message ?? fehler)
}

/* How a refusal with no reason of its own is named — "Fehler 502" in the
   interface's language, not the service's. A text, so it comes from the
   catalogue; the catalogue cannot be imported here (texte.svelte.js imports
   this file), so it arrives the same way the language does: pushed in once
   the catalogue is there (`rememberStatusText`). Until then the page's own
   sentence stands (app/main.py). */
let statusText = (status) => fillSentence(PRE_CATALOGUE.status, 'status', status)

/* What a stream that ends without `done` says. The page carries it the same
   way it carries the two boot sentences (app/main.py) and for the same
   reason: the catalogue cannot be imported here. Read at the moment it is
   needed, not once at load: the page may have been handed its sentences
   late, and the window only ever shows this where the answer really
   failed. Before that sentence is there, the English one stands — a
   sentence in the wrong language would be worse. */
function abrissText() {
  return PRE_CATALOGUE.strom_abriss || 'The connection was lost while receiving the response.'
}

export function rememberStatusText(neuer) {
  statusText = neuer
}

export class ApiFehler extends Error {
  constructor(nachricht, status) {
    super(nachricht)
    this.status = status
  }
}

/* The refusal an answer carries, read in ONE place for every way a request
   can end (rufRoh, antwortStrom, zusehenStrom): the reason the service
   sends, otherwise the number in the interface's language. Reading it three
   times meant it was read differently three times — the stream that
   resumes a running chat threw the translated reason away and showed the
   number instead. */
async function errorFrom(antwort) {
  // The key of a service that is gone: the page fetches itself anew.
  if (antwort.status === 401) sitzungNeuLaden()
  /* A body that parses to `null` is no body either: without the fallback the
     read below would end in a TypeError instead of an ApiFehler. A caller's
     own abort has to stay recognisable as one — swallowing it here would
     turn a stop into a failure further up (App.svelte reads the name). */
  const daten = await antwort.json().catch((grund) => {
    if (grund?.name === 'AbortError') throw grund
    return {}
  })
  const rumpf = daten ?? {}
  /* A validation error (422) carries `detail` as an array of objects —
     anything but a plain string would surface as "[object Object]". */
  let meldung = rumpf.detail
  if (Array.isArray(meldung)) meldung = meldung.map((f) => f?.msg ?? '').filter(Boolean).join('; ')
  if (typeof meldung !== 'string' || !meldung) meldung = statusText(antwort.status)
  return new ApiFehler(meldung, antwort.status)
}

/* The call itself, up to and including "did the server say no". Split out
   from `ruf` for the one reader that needs more than the body — the message
   page carries how long the whole chat is in a header — so that reader does
   not have to repeat the session key, the language header or the error
   translation to get at it. Everything else keeps asking `ruf` and keeps
   getting the parsed body and nothing else. */
async function rufRoh(pfad, optionen = {}) {
  /* A caller's own `headers` (raw-byte uploads set their own Content-Type)
     must ADD to these, not replace them — spreading `optionen` after this
     object once overwrote the whole `headers` key at once, silently
     dropping the session key from every such call. */
  const { headers: eigeneHeader, ...rest } = optionen
  const antwort = await fetch(BASIS + pfad, {
    ...rest,
    headers: {
      ...(optionen.body ? { 'Content-Type': 'application/json' } : {}),
      ...sprachkopf(),
      ...(SCHLUESSEL ? { 'X-Sitzungsschluessel': SCHLUESSEL } : {}),
      ...eigeneHeader,
    },
  })
  if (!antwort.ok) throw await errorFrom(antwort)
  return antwort
}

async function ruf(pfad, optionen = {}) {
  const antwort = await rufRoh(pfad, optionen)
  return antwort.status === 204 ? null : antwort.json()
}

const alsText = (wert) => JSON.stringify(wert)

/* The most rows one request for a list may ask for: the chat route allows
   500 at most (`le=500`, app/api/v1/chats.py). Asking for that many keeps
   a list of up to 500 rows a single request. */
const LIST_PAGE = 500

/* Reads a whole list from a route that hands it out one page at a time.
   The chat and job lists answer with their newest rows only, so a window
   that asks once misses every older one: an old chat of a project, the tail
   of the archive, a waiting agent's question behind many newer jobs. Pages
   are asked for until one comes back shorter than asked for — the service's
   way of saying "that was the last one". `fetchPage(limit, offset)` resolves
   to one page, newest first. Rows are told apart by `id`: a row touched
   between two requests moves to the front and would show up on two pages. */
export async function allPages(fetchPage, size = LIST_PAGE) {
  const rows = []
  const seen = new Set()
  let offset = 0
  for (;;) {
    const page = await fetchPage(size, offset)
    let added = 0
    for (const row of page) {
      if (seen.has(row.id)) continue
      seen.add(row.id)
      rows.push(row)
      added += 1
    }
    /* A full page that brought nothing new means the service ignores
       `offset`, which would ask for ever. */
    if (page.length < size || added === 0) return rows
    offset += page.length
  }
}

/* The storage-location list is read by every folder row — the pictures
   module and the three server panels — which mount together. Share one
   in-flight request so their near-simultaneous reads collapse into a single
   call; it clears the moment it resolves, so a read after a change is always
   fresh, never a stale cache. */
let orteLauf = null

export const api = {
  /* Signs in to a service that demands a password and keeps the key it
     answers with. Through the one door every call takes: a refusal is the
     wrong password, read like any other refusal — and the reload guard
     stays out of it on a page that has no key yet. */
  signIn: async (password) => {
    const daten = await ruf('/login', { method: 'POST', body: alsText({ password }) })
    setSessionKey(daten.key)
    return daten.key
  },
  /* `frisch` asks the server to knock on every candidate first — for the
     moment right after something was started or added, when the regular
     check has not come around yet. */
  modelle: (frisch = false) => ruf(frisch ? '/models?jetzt_pruefen=true' : '/models'),
  /* Every server the service carries, the unreachable ones too — asked
     only where the chosen model is missing from the list above. */
  modelleAlle: () => ruf('/models?alle=true'),
  meta: () => ruf('/meta'),
  /* The one call that already speaks the language being switched TO: it asks
     for exactly those texts, and the window still shows the old ones while
     it runs. The route takes the language from its path — the header is here
     so this request speaks what it asks for; the session guard's own refusal
     on this path is written in it (app/sitzungsschluessel.py). Every other
     request keeps the language on screen until the texts are there
     (texte.svelte.js). */
  uebersetzungen: (sprache) =>
    ruf(`/translations/${sprache}`, { headers: { [LANGUAGE_HEADER]: sprache } }),
  werkzeuge: () => ruf('/tools'),
  /* The command runs of a chat, and the stream that keeps them current.
     `ab` on the answer is the event count already covered — passed straight
     back into `laeufeStrom` so the stream resumes instead of repeating. */
  laeufe: (chatId) => ruf(`/laeufe/${chatId}`),
  // Stops one running command with everything it started.
  stopRun: (chatId, nummer) => ruf(`/laeufe/${chatId}/${nummer}/stop`, { method: 'POST' }),
  /* The notes and the document dock — the user's own pad beside the chat.
     Both live in the data folder, so they outlive a cleared browser. */
  /* The offline picture generator. `bildmodelle` looks at the data folder,
     `bildZeichnen` blocks for as long as the picture takes — half a minute
     is normal, so no caller may treat a slow answer as a hang. */
  bildmodelle: () => ruf('/bild/modelle'),
  bildProtokoll: () => ruf('/bild/server/log'),
  /* The starting values a model opens on — its family read from the file's
     own header, that family's start values and the companion files that
     fit it. Asked whenever the chosen model changes. */
  bildVorgaben: (modell) => ruf(`/bild/vorgaben${modell ? `?modell=${encodeURIComponent(modell)}` : ''}`),
  /* The one table of model families (app/image_families.py). */
  bildFamilien: () => ruf('/bild/familien'),
  /* The further sd.cpp switches and their files (app/image_switches.py). */
  imageSwitches: () => ruf('/bild/switches'),
  /* The picture server's tools under "Local" (app/api/v1/image_tools.py). */
  imageModelFiles: () => ruf('/bild/model-files'),
  imageDevices: () => ruf('/bild/devices'),
  convertModel: (model, weightType) =>
    ruf('/bild/convert', { method: 'POST', body: alsText({ model, weight_type: weightType }) }),
  collectImatrix: (model, on) => ruf('/bild/imatrix', { method: 'POST', body: alsText({ model, on }) }),
  /* What the program kept for a picture it drew: the prompt, the model and
     the values, by the picture's name. Empty where it kept nothing. */
  drawnWith: (name) => ruf(`/bild/info?name=${encodeURIComponent(name)}`),
  /* What a picture says about how it was made, read from its raw bytes. */
  pictureInfo: (file) =>
    ruf('/bild/info', { method: 'POST', headers: { 'Content-Type': file.type }, body: file }),
  bildordnerOeffnen: () => ruf('/bild/folder', { method: 'POST' }),
  bildZeichnenStoppen: () => ruf('/bild/stop', { method: 'POST' }),
  /* Open a companion sub-folder in the file manager so a hand-picked file can
     be dropped in. The picture side (vae/lora/adetailer) and the chat side
     (mtp/vision) each have their own whitelisted route. */
  bildBegleiterOrdner: (unter) => ruf(`/bild/begleiter-folder/${unter}`, { method: 'POST' }),
  chatBegleiterOrdner: (unter) => ruf(`/runner/begleiter-folder/${unter}`, { method: 'POST' }),
  /* The generator program itself — fetched once on machines without one.
     `variante` only matters on win32, where several GPU backends are on
     offer (see app/sddownload.py); left unset, the server's own default
     applies, unchanged from before this parameter existed. */
  bildProgrammHolen: (variante) =>
    ruf('/bild/programm', { method: 'POST', body: alsText({ variante: variante ?? null }) }),
  /* Fetches whichever release is newest at the moment of the click, not
     the pinned build — the server re-reads the release itself rather than
     trust a build tag this call could pass in. */
  bildProgrammAktualisieren: (variante) =>
    ruf('/bild/programm', {
      method: 'POST',
      body: alsText({ variante: variante ?? null, aktualisieren: true }),
    }),
  /* Fetches the tested build in place of the one installed — the way back
     from an update. Which variant that is, the server reads off the disk. */
  imageProgramRestore: () =>
    ruf('/bild/programm', { method: 'POST', body: alsText({ restore: true }) }),
  bildProgrammStand: () => ruf('/bild/programm'),
  /* Which GPU-backend variants this machine could offer, and which one (if
     any) is on disk right now — empty on every platform but win32, which
     has nothing to choose from. */
  bildProgrammVarianten: () => ruf('/bild/programm/varianten'),
  /* Whether a newer release than the one on disk exists — asked once when
     the panel opens, never on a timer (app/sddownload.py). */
  bildProgrammAktualisierung: () => ruf('/bild/programm/aktualisierung'),
  /* Asks the loaded LANGUAGE model to rewrite a picture prompt in English.
     Nothing to do with the generator — it only happens to serve the same
     window. */
  /* The running picture's honest step counter — feeds the filling frame.
     `signal` lets the caller give up on a question that does not answer. */
  bildFortschritt: (signal) => ruf('/bild/fortschritt', { signal }),

  /* The prompt preparation: the server chosen in the picture server writes
     the prompt for the picture model's family. `cfg` decides whether a
     negative prompt comes back at all. */
  bildPromptVerbessern: ({ prompt, negativ, modell, familie, cfg, stil }) =>
    ruf('/bild/prompt', { method: 'POST', body: alsText({ prompt, negativ: negativ || '', modell: modell || '', familie: familie || '', cfg: cfg ?? null, stil: stil || '' }) }),

  /* What the picture server's "Prompt preparation" block shows: the chosen
     server, the instruction of every family and its works text. Written
     through the settings route. */
  bildAufbereitung: () => ruf('/bild/prompt/aufbereitung'),

  /* The embedding server: its own port, its own folder, its own buttons.
     Started and stopped independently of the language model's server —
     sharing either was the whole reason the first build collided. */
  einbettungAuskunft: () => ruf('/einbettungsserver'),
  einbettungProtokoll: () => ruf('/einbettungsserver/log'),
  einbettungStarten: (modell, port) =>
    ruf('/einbettungsserver/start', { method: 'POST', body: alsText({ modell, port: port ?? null }) }),
  einbettungStoppen: () => ruf('/einbettungsserver/stop', { method: 'POST' }),
  einbettungOrdnerOeffnen: () => ruf('/einbettungsserver/folder', { method: 'POST' }),

  /* The speech server: its own folder, its own port, its own buttons — and,
     in `spracheTranskribieren`, the ONE address the microphone button knows.
     What transcribes behind it is the service's business; the page never
     talks to an engine itself, so a second program for other model families
     can arrive later without the button changing at all.

     The recording travels as raw bytes with its own Content-Type: one blob,
     one request, no multipart and no base64 detour through a JSON string. */
  spracheAuskunft: () => ruf('/sprachserver'),
  spracheProtokoll: () => ruf('/sprachserver/log'),
  spracheStarten: (modell, { port, kontext, schichten, threads } = {}) =>
    ruf('/sprachserver/start', {
      method: 'POST',
      body: alsText({
        modell,
        port: port ?? null,
        kontext: kontext ?? null,
        schichten: schichten ?? null,
        threads: threads ?? null,
      }),
    }),
  spracheStoppen: () => ruf('/sprachserver/stop', { method: 'POST' }),
  spracheOrdnerOeffnen: () => ruf('/sprachserver/folder', { method: 'POST' }),
  /* `bereinigen: false` for the readings taken while somebody still speaks —
     they are replaced a second later, and only the pass after the stop is
     worth a tidy-up. */
  /* `signal` lets the caller give up on a transcription the speech service
     never answers: the dictation's pass after the stop, which Escape throws
     away like a running recording. */
  spracheTranskribieren: (wav, { bereinigen = true, signal } = {}) =>
    ruf(`/sprachserver/transkribieren${bereinigen ? '' : '?bereinigen=false'}`, {
      method: 'POST',
      headers: { 'Content-Type': 'audio/wav' },
      body: wav,
      signal,
    }),
  /* The voice, reading one sentence back — the WAV comes back raw, the same
     shape `spracheTranskribieren` sends in, just the other way round. */
  spracheSprechen: async (text) => {
    const antwort = await rufRoh('/sprachserver/sprechen', {
      method: 'POST',
      body: alsText({ text }),
    })
    return antwort.blob()
  },

  /* The clean-up server: its own window, its own port, its own buttons —
     started and stopped by hand, never with the speech server. Which file
     it runs from and which numbers it runs with are settings the window
     writes as they are touched; the start reads them on the server. */
  bereinigungAuskunft: () => ruf('/bereinigungsserver'),
  bereinigungProtokoll: () => ruf('/bereinigungsserver/log'),
  bereinigungStarten: (modell, port) =>
    ruf('/bereinigungsserver/start', { method: 'POST', body: alsText({ modell, port: port ?? null }) }),
  bereinigungStoppen: () => ruf('/bereinigungsserver/stop', { method: 'POST' }),

  /* The assets view: the saved pictures, and the storage locations behind
     them — one place to see what was drawn and to move where it is kept. */
  /* The saved pictures; with `chat` only that chat's, with `projekt` those
     of every chat in the project. */
  bilderListe: ({ chat, projekt } = {}) => {
    const frage = new URLSearchParams()
    if (chat) frage.set('chat', chat)
    else if (projekt) frage.set('projekt', projekt)
    const anhang = frage.toString()
    return ruf('/bilder' + (anhang ? `?${anhang}` : ''))
  },
  speicherorteLesen: () => {
    if (!orteLauf) orteLauf = ruf('/speicherorte').finally(() => { orteLauf = null })
    return orteLauf
  },
  // A change drops the shared in-flight read, so the very next read starts
  // fresh instead of joining a request begun before the change and handing
  // back the pre-change list.
  speicherortSetzen: (name, pfad) => {
    orteLauf = null
    return ruf(`/speicherorte/${name}`, { method: 'PUT', body: alsText({ pfad }) })
  },
  speicherortZuruecksetzen: (name) => {
    orteLauf = null
    return ruf(`/speicherorte/${name}`, { method: 'DELETE' })
  },
  speicherortOeffnen: (name) => ruf(`/speicherorte/${name}/folder`, { method: 'POST' }),

  /* The model slot: its own small model, and its own routes for the same
     reason the embedding server has its own — two servers that must start
     independently. */
  agentenmodellAuskunft: () => ruf('/agentenmodell'),
  agentenmodellStarten: (modell) =>
    ruf('/agentenmodell/start', { method: 'POST', body: alsText({ modell }) }),
  agentenmodellStoppen: () => ruf('/agentenmodell/stop', { method: 'POST' }),
  agentenmodellProtokoll: () => ruf('/agentenmodell/log'),
  bildZeichnen: (daten) => ruf('/bild', { method: 'POST', body: alsText(daten) }),

  /* The dock — the one shelf for files without a chat. A file the person
     puts into the doc folder goes there as raw bytes with the name as a
     parameter, the same shape as the image and document uploads. `chat` is
     the chat that is open: then the file goes into that chat's own folder
     instead; empty on the start page. Jobs fill the same shelf through the
     deliver_file tool. */
  docFolderAdd: (file, chat = '') =>
    ruf(`/agentendock?name=${encodeURIComponent(file.name)}${chat ? `&chat=${encodeURIComponent(chat)}` : ''}`, {
      method: 'POST',
      headers: { 'Content-Type': file.type || 'application/octet-stream' },
      body: file,
    }),
  agentendockEntfernen: (id) => ruf(`/agentendock/${id}`, { method: 'DELETE' }),
  /* The doc folder: every file in one list, narrowed by project, by who
     brought the file (`origin`: 'user', 'agent' or 'cronjob') and by chat —
     a chat's own files only, every file without one. Each row names the
     path its file is fetched from — the address below for a plain
     <img src> or a link, where no header can travel, and the blob for a
     `fetch`, where it can. */
  docFolder: ({ project = '', origin = '', chat = '' } = {}) => {
    const params = new URLSearchParams()
    if (project) params.set('project', project)
    if (origin) params.set('origin', origin)
    if (chat) params.set('chat', chat)
    const query = params.toString()
    return ruf(`/doc-folder${query ? `?${query}` : ''}`)
  },
  /* Where an open chat's own files lie: what its folder row names. */
  docFolderPlace: (chat) => ruf(`/doc-folder/place?chat=${encodeURIComponent(chat)}`),
  docFolderAddress: (path) => mitSchluessel(`${BASIS}${path}`),
  docFolderBlob: (path) => rufRoh(path).then((answer) => answer.blob()),

  /* Shows a shared working folder in the file manager. */
  ordnerOeffnen: (chatId, pfad) =>
    ruf('/ordner/oeffnen', { method: 'POST', body: alsText({ chat_id: chatId, pfad }) }),
  /* The copy the program keeps of a shared folder's exe.md. The first asks
     whether there is one and whether the folder still holds notes — the
     offer only makes sense out of that pair. The second puts the copy back
     and answers with a key, never a sentence (app/ordnerwissen.py). Which
     folder is not a wish either way: the service takes the path from the
     chat's own list and refuses anything else. */
  ordnerwissenStand: (chatId, pfad) => {
    const frage = new URLSearchParams({ chat_id: chatId, pfad })
    return ruf(`/ordnerwissen/sicherung?${frage}`)
  },
  ordnerwissenZurueckholen: (chatId, pfad) =>
    ruf('/ordnerwissen/wiederherstellen', {
      method: 'POST',
      body: alsText({ chat_id: chatId, pfad }),
    }),
  laeufeStrom: (chatId, ab = 0) => mitSchluessel(`${BASIS}/laeufe/${chatId}/stream?ab=${ab}`),
  /* The second live line, and the one that belongs to no chat: what the
     program as a whole has to say (app/ereignisstrom.py). */
  ereignisStrom: () => mitSchluessel(`${BASIS}/events/stream`),
  /* What the window shows now — its look, its language, or both — told to
     the terminal client inside it. */
  fensterMelden: (felder) =>
    ruf('/events/window-theme', { method: 'POST', body: alsText(felder) }),
  skills: () => ruf('/skills'),
  skillsVerwaltung: () => ruf('/skills/verwaltung'),
  skillSchreiben: (name, inhalt) =>
    ruf('/skills', { method: 'POST', body: alsText({ name, inhalt }) }),
  skillAuto: (name, auto) =>
    ruf(`/skills/${encodeURIComponent(name)}`, { method: 'PATCH', body: alsText({ auto }) }),
  skillDatei: (name) => ruf(`/skills/${encodeURIComponent(name)}`),
  skillSichern: (name, inhalt) =>
    ruf(`/skills/${encodeURIComponent(name)}`, { method: 'PUT', body: alsText({ inhalt }) }),
  skillZuruecksetzen: (name) =>
    ruf(`/skills/${encodeURIComponent(name)}`, { method: 'DELETE' }),
  // Standing schedules (6.7 extension): created via the cronjob tool, only
  // shown and switched here.
  cronjobs: () => ruf('/cronjobs'),
  cronjobAnlegen: (felder) =>
    ruf('/cronjobs', { method: 'POST', body: alsText(felder) }),
  /* Changes only the fields sent, through the tool's own `update`. */
  cronjobChange: (id, felder) =>
    ruf(`/cronjobs/${encodeURIComponent(id)}`, { method: 'PATCH', body: alsText(felder) }),
  /* Per day from `first` to `last` (YYYY-MM-DD): what ran, and what the
     rules plan — one row per schedule and day. */
  cronjobCalendar: (first, last) =>
    ruf(`/cronjobs/calendar?first=${encodeURIComponent(first)}&last=${encodeURIComponent(last)}`),
  /* The next few runs of a schedule that is only typed, not stored. */
  cronjobPreview: (zeitplan) =>
    ruf(`/cronjobs/preview?zeitplan=${encodeURIComponent(zeitplan)}`),
  /* The whole history in one answer — runs, not entries, so a run whose
     schedule was deleted is still in it. */
  cronjobLaeufeAlle: () => ruf('/cronjobs/runs/all'),
  cronjobPausieren: (id) => ruf(`/cronjobs/${encodeURIComponent(id)}/pause`, { method: 'POST' }),
  cronjobFortsetzen: (id) => ruf(`/cronjobs/${encodeURIComponent(id)}/resume`, { method: 'POST' }),
  /* Run it now, without waiting for the next due time — the same run the
     tick would start, entry id and all. */
  cronjobStarten: (id) => ruf(`/cronjobs/${encodeURIComponent(id)}/run`, { method: 'POST' }),
  cronjobLoeschen: (id) => ruf(`/cronjobs/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  // config.yaml and .env, editable in the settings mask.
  datei: (kennung) => ruf(`/dateien/${kennung}`),
  dateiSichern: (kennung, inhalt) =>
    ruf(`/dateien/${kennung}`, { method: 'PUT', body: alsText({ inhalt }) }),
  /* Raw bytes instead of multipart — the server wants it exactly this way.
     `scratch`: a working picture of the studio, made for a draw — it lies
     outside the picture folder and is gone with the service's next start. */
  bildHochladen: (datei, scratch = false) =>
    ruf(`/images${scratch ? '?scratch=true' : ''}`,
      { method: 'POST', headers: { 'Content-Type': datei.type }, body: datei }),
  /* Documents (4.1): raw bytes as well; the name travels along as a
     parameter because the server needs the extension — the type isn't
     reliably present in the Content-Type. */
  /* Adds a cloud provider: key into .env, endpoint into config.yaml. */
  anbieterHinzufuegen: (daten) =>
    ruf('/providers', { method: 'POST', body: alsText(daten) }),
  /* Removes a provider's entry from config.yaml; its key stays in .env. */
  anbieterLoeschen: (id) => ruf(`/providers/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  /* The model server on this machine: what is there, what runs, what it says.
     Fetching a model goes the same way — one button, no command. */
  /* What lies in the scripts folder — the wall under the folder row in the
     schedules mask, so a script is picked instead of typed. */
  skripteListe: () => ruf('/skripte'),
  runnerAuskunft: () => ruf('/runner'),
  /* The machine's one memory pool, for the pill in the header. */
  speicherBlick: () => ruf('/system/speicher'),
  runnerProtokoll: () => ruf('/runner/log'),
  runnerStarten: (daten) => ruf('/runner/start', { method: 'POST', body: alsText(daten) }),
  runnerStoppen: () => ruf('/runner/stop', { method: 'POST' }),
  /* A companion (mmproj/mtp) carries which model it belongs to and its
     role, so the service records the association in a manifest and the
     runner attaches it later without guessing from file names. */
  modellHolen: (
    repo, datei, ziel = null, gehoert_zu = null, rolle = null, art = 'chat',
    unterordner = null,
  ) =>
    ruf('/runner/download', {
      method: 'POST',
      body: alsText({ repo, datei, ziel, gehoert_zu, rolle, art, unterordner }),
    }),
  modellHolenStand: () => ruf('/runner/download'),
  modellHolenAbbrechen: () => ruf('/runner/download', { method: 'DELETE' }),

  /* Searches the model catalogue. Runs on our server, never in the page.
     `art` is one of the catalogue's three tabs — chat, einbettung, bild —
     and scopes the search to that kind alone. */
  modellSuche: (q, art, anzahl = 12) =>
    ruf(`/models/search?q=${encodeURIComponent(q)}&art=${art}&anzahl=${anzahl}`),
  /* The model files of one found repository — what the download can finish.
     `art` is the tab it was found in; it decides which file forms count. */
  modellDateien: (repo, art) =>
    ruf(`/models/files?repo=${encodeURIComponent(repo)}&art=${art}`),
  /* One row of a picture repository's list with what its own head says:
     what the file is, and its kit. Asked per row once the list stands. */
  fileHead: (repo, row) =>
    ruf('/models/files/head', {
      method: 'POST',
      body: alsText({
        repo,
        datei: {
          datei: row.datei, groesse_gb: row.groesse_gb, bytes: row.bytes ?? 0,
          teile: row.teile ?? 1,
        },
      }),
    }),
  /* The Hugging Face token: set once, never handed back out. */
  hfTokenStand: () => ruf('/models/token'),
  hfTokenSetzen: (token) => ruf('/models/token', { method: 'POST', body: alsText({ token }) }),
  hfTokenEntfernen: () => ruf('/models/token', { method: 'DELETE' }),
  /* Shows the model folder in the file manager. Always that one folder. */
  modellordnerOeffnen: () => ruf('/runner/folder', { method: 'POST' }),
  /* The model server itself — fetched once on machines without one.
     `variante` only matters on Windows, where the server comes in several
     builds (see app/serverdownload.py); left unset, the default applies. */
  serverProgrammHolen: (variante) =>
    ruf('/runner/programm', {
      method: 'POST',
      ...(variante ? { body: alsText({ variante }) } : {}),
    }),
  serverProgrammStand: () => ruf('/runner/programm'),
  /* The builds this machine could fetch, and the one that was — empty
     everywhere but Windows on x64. */
  serverProgrammVarianten: () => ruf('/runner/programm/varianten'),
  /* Whether a newer build than the one that starts exists — asked when the
     window's check is pressed, never on a timer (app/serverdownload.py). */
  serverProgramUpdateCheck: () => ruf('/runner/programm/aktualisierung'),
  /* Fetches whichever build is newest at the moment of the click — the
     server reads the release list again rather than trust a build this
     call could pass in. */
  serverProgramUpdate: () =>
    ruf('/runner/programm', { method: 'POST', body: alsText({ aktualisieren: true }) }),
  /* Fetches the tested build in place of a newer one. */
  serverProgramRestore: () =>
    ruf('/runner/programm', { method: 'POST', body: alsText({ restore: true }) }),

  /* The stored text of one document — what the chat's document card opens
     in the preview rail. */
  dokumentLesen: (id) => ruf(`/documents/${encodeURIComponent(id)}`),
  /* The ✕ on a chat attachment: removes ONE image or document from a
     stored message — and with it from the model's context. */
  anhangEntfernen: (chatId, messageId, { bild, dokument } = {}) => {
    const teile = []
    if (bild) teile.push(`bild=${encodeURIComponent(bild)}`)
    if (dokument) teile.push(`dokument=${encodeURIComponent(dokument)}`)
    return ruf(
      `/chats/${chatId}/messages/${messageId}/anhang?${teile.join('&')}`,
      { method: 'DELETE' },
    )
  },
  dokumentHochladen: (chatId, datei) =>
    ruf(
      `/documents?chat_id=${encodeURIComponent(chatId)}&name=${encodeURIComponent(datei.name)}`,
      { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: datei },
    ),
  /* A document uploaded on attaching it (4.1) and dropped again before it
     was ever sent — the stack's own ✕, not the message's. */
  dokumentLoeschen: (id) => ruf(`/documents/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  /* The card's own click: opens the stored file in the system's default
     program for it, same as the model folder's own open button. */
  dokumentOeffnen: (id) => ruf(`/documents/${encodeURIComponent(id)}/open`, { method: 'POST' }),
  /* Where a document's own file is fetched from — for a frame that shows
     it and for the link that saves it, neither of which can send a header. */
  documentFileAddress: (id) => mitSchluessel(`${BASIS}/documents/${encodeURIComponent(id)}/file`),
  /* The file itself as text — for a file a tool handed into the chat, whose
     row holds no text of its own. `null` for a file that is no text (a
     picture, an archive): the reader then shows the page sign instead of
     setting bytes as prose. Text is what reads as UTF-8 without a fault —
     the type the service guesses from the name is empty for half the text
     files there are (.yaml, .toml, a name with no ending). */
  documentFileText: async (id) => {
    const answer = await rufRoh(`/documents/${encodeURIComponent(id)}/file`)
    const bytes = await answer.arrayBuffer()
    try {
      return new TextDecoder('utf-8', { fatal: true }).decode(bytes)
    } catch {
      return null
    }
  },
  bildAdresse: (name) => mitSchluessel(`${BASIS}/images/${name}`),
  /* The running picture's live preview: the answer as soon as it has
     begun, its bytes still to be read (`.blob()`), so the caller can tell
     an answer on its way from none at all. A preview caught half written
     answers 404 and throws. `signal` lets the caller give up on the
     fetch. */
  previewAnswer: (signal) => rufRoh('/bild/preview', signal ? { signal } : {}),
  bildBlob: (name) => rufRoh(`/images/${name}`).then((antwort) => antwort.blob()),
  /* Image-Turbo: the optional persistent picture server. Off by default;
     switched on from the plus menu, which then keeps the model loaded so
     every picture after the first skips the load. */
  turboStand: () => ruf('/bild/turbo'),
  turboReason: (daten) => ruf('/bild/turbo/reason', { method: 'POST', body: alsText(daten) }),
  turboStarten: (modell) => ruf('/bild/turbo/start', { method: 'POST', body: alsText({ modell }) }),
  turboStoppen: () => ruf('/bild/turbo/stop', { method: 'POST' }),
  werkzeugKonfiguration: () => ruf('/tools/config'),
  werkzeugKonfigurationSichern: (content) =>
    ruf('/tools/config', { method: 'PUT', body: alsText({ content }) }),

  /* The tile gallery: server entries in structured form, plus the browser
     sign-in. Same source of truth as the raw text field. */
  mcpSondieren: (url) =>
    ruf('/tools/mcp/sondieren', { method: 'POST', body: alsText({ url }) }),
  serverUebersicht: () => ruf('/tools/servers'),
  /* `neu`: a server being added — the service refuses an id already on file
     instead of merging into it. `shipped`: a server the program starts
     itself — with no entry on file, the one the program ships is put back
     and the fields go on top of it. */
  serverSchreiben: (name, daten, { neu = false, shipped = false } = {}) => {
    const params = new URLSearchParams()
    if (neu) params.set('neu', 'true')
    if (shipped) params.set('shipped', 'true')
    const query = params.toString()
    return ruf(`/tools/servers/${encodeURIComponent(name)}${query ? `?${query}` : ''}`, {
      method: 'PUT',
      body: alsText(daten),
    })
  },
  serverEntfernen: (name) =>
    ruf(`/tools/servers/${encodeURIComponent(name)}`, { method: 'DELETE' }),
  oauthStart: (daten) =>
    ruf('/tools/oauth/start', { method: 'POST', body: alsText(daten) }),
  oauthStatus: () => ruf('/tools/oauth/status'),
  oauthVergessen: (server) =>
    ruf(`/tools/oauth/${encodeURIComponent(server)}`, { method: 'DELETE' }),

  systemPrompt: () => ruf('/system-prompt'),
  systemPromptSichern: (text) =>
    ruf('/system-prompt', { method: 'PUT', body: alsText({ text }) }),
  /* The memory (app/gedaechtnis.py) — a second prompt file, same shape. */
  gedaechtnis: () => ruf('/memory'),
  gedaechtnisSichern: (text) =>
    ruf('/memory', { method: 'PUT', body: alsText({ text }) }),

  /* The system's folder dialog. The browser never hands
     out a real path — the service opens Finder or Explorer instead and
     returns one. `pfad: null` in the answer means the user cancelled; the
     UI treats that as nothing happening, not as an error. */
  ordnerDialogAuskunft: () => ruf('/filesystem/folder-dialog'),
  ordnerDialogOeffnen: (titel, start) =>
    ruf('/filesystem/choose-folder', { method: 'POST', body: alsText({ titel, start }) }),

  /* Settings across their scopes. `aufgeloest` gives what actually applies
     plus where each value comes from; `setzen` writes one scope. `null` as a
     value removes the entry and lets the scope above take over. */
  einstellungAufgeloest: (schluessel, { modell, chat } = {}) => {
    const frage = new URLSearchParams()
    if (modell) frage.set('modell', modell)
    if (chat) frage.set('chat', chat)
    const anhang = frage.toString()
    return ruf(`/settings/resolved/${schluessel}` + (anhang ? `?${anhang}` : ''))
  },
  // One trip for a whole list instead of one per key: the screen needs a
  // dozen of them before it can draw, and each one used to be its own round
  // trip. Answer is keyed by setting name — { schluessel: { wert, herkunft } }.
  einstellungAufgeloestViele: (schluessel, { modell, chat } = {}) => {
    const frage = new URLSearchParams()
    frage.set('keys', schluessel.join(','))
    if (modell) frage.set('modell', modell)
    if (chat) frage.set('chat', chat)
    return ruf(`/settings/resolved?${frage.toString()}`)
  },
  einstellungSetzen: (bereich, schluessel, wert) =>
    ruf(`/settings/${encodeURIComponent(bereich)}/${schluessel}`, {
      method: 'PUT',
      body: alsText({ wert }),
    }),
  /* Only the values named, merged into what the scope already holds — for a
     setting more than one window writes. `setzen` replaces, so each writer
     would have to resend the whole object to keep the parts it did not
     change, and that object is the copy it read when it opened: window B's
     next slider drag would carry its stale copy out over window A's pick. */
  einstellungMischen: (bereich, schluessel, wert) =>
    ruf(`/settings/${encodeURIComponent(bereich)}/${schluessel}`, {
      method: 'PATCH',
      body: alsText({ wert }),
    }),

  /* Every chat, not just the newest 100: the sidebar groups them by project
     and day, so a chat left out of the list is a chat that is not there. */
  chats: (suche) =>
    allPages((limit, offset) =>
      ruf(`/chats?limit=${limit}&offset=${offset}${suche ? `&suche=${encodeURIComponent(suche)}` : ''}`),
    ),
  chatAnlegen: (daten) => ruf('/chats', { method: 'POST', body: alsText(daten) }),
  chatAendern: (id, daten) => ruf(`/chats/${id}`, { method: 'PATCH', body: alsText(daten) }),
  chatLoeschen: (id) => ruf(`/chats/${id}`, { method: 'DELETE' }),
  /* Folds the middle of a chat once, now. The answer is one word —
     `folded` with how many messages it replaced, `too_short`, `no_saving`
     or `failed` — and the request lasts as long as the summary takes. */
  chatCompact: (id, daten) =>
    ruf(`/chats/${id}/compact`, { method: 'POST', body: alsText(daten) }),
  // The archive: the chats put away one by one.
  archivedChats: () =>
    allPages((limit, offset) => ruf(`/chats?archived=true&limit=${limit}&offset=${offset}`)),
  projects: (archived = false) => ruf(`/projects${archived ? '?archived=true' : ''}`),
  projectCreate: (name) => ruf('/projects', { method: 'POST', body: alsText({ name }) }),
  projectUpdate: (id, data) => ruf(`/projects/${id}`, { method: 'PATCH', body: alsText(data) }),
  projectDelete: (id) => ruf(`/projects/${id}`, { method: 'DELETE' }),
  /* Which of a chat's shared folders are no longer there. A look and
     nothing else — the service removes nothing and searches for
     nothing (app/ordnerstand.py). */
  chatOrdnerstand: (id) => ruf(`/chats/${id}/ordnerstand`),

  /* One page of a chat — the NEWEST one, which is not what this used to
     ask for. It sent no `limit` and no `offset` at all, so the route's own
     defaults applied and the window was handed the OLDEST five hundred
     rows: past that point a chat showed its beginning and silently lost its
     end, and after a reload the messages just typed were the ones missing.
     Nothing paged, so nothing ever fetched the rest.

     `offset` counts backwards from the newest end, so `SEITE` is the page
     before the one on screen — the handle a scroll-up pager needs. Nothing
     calls it with one yet; the window renders every row it is given, with
     no windowing of its own, so loading a five-thousand-row chat in one go
     would be a different defect rather than a fix for this one.

     `gesamt` and `ausgelassen` come back beside the rows so the omission is
     a NUMBER the window has rather than something it cannot know. A page
     that is exactly full and a chat that is exactly one page long look the
     same from the body alone, which is how this stayed invisible for as
     long as it did. */
  nachrichten: async (id, { limit = SEITE, offset = 0, signal = null } = {}) => {
    /* `signal` is the caller's bound on the wait. A reader that has to
       release something when this settles — the end-of-run reconcile in
       App.svelte, which holds the chat marked running until it does —
       must not be left waiting on a fetch that never returns. */
    const antwort = await rufRoh(
      `/chats/${id}/messages?neueste=true&limit=${limit}&offset=${offset}`,
      signal ? { signal } : {},
    )
    const seite = await antwort.json()
    /* A header that is missing or unreadable must not cost the chat its
       messages: an older service, or a proxy that drops unknown headers,
       leaves the count unknown — which is what it was before, and the rows
       are the part the reader is waiting for. */
    const gesamt = Number(antwort.headers.get('X-Nachrichten-Gesamt'))
    if (!Number.isFinite(gesamt) || gesamt <= 0) return seite
    return {
      ...seite,
      gesamt,
      ausgelassen: Math.max(0, gesamt - seite.nachrichten.length - offset),
    }
  },

  /* Both ids travel, and the service takes which one it needs: the run's
     own id while there is one, the chat's while there is not yet. Before
     the stream's `start` the window has no run id at all — the chat id is
     then the only handle the stop button has, and without it the press
     reached the service as a request naming nothing it holds
     (app/generationen.py, `alle_im_chat_abbrechen`). */
  abbrechen: (generationId, chatId = null) =>
    ruf('/chat/stop', {
      method: 'POST',
      body: alsText({ generation_id: generationId, chat_id: chatId }),
    }),

  /* Answer to the confirmation prompt before a tool runs. Goes over its own
     connection — the event stream is one-way only, nothing can be sent back
     through it. */
  /* Answers a waiting tool call: the yes or no before a tool runs, or —
     with `antwort` — what the user replied to the model's own question.
     `name` + `dauerhaft` (Schritt 12) ask the server to also write a
     standing rule for this tool — the box has no other way to hand it the
     name, this route only knows that SOME call is waiting. */
  werkzeugBestaetigen: (generationId, aufrufId, erlaubt, antwort = null, name = null, dauerhaft = false) =>
    ruf('/chat/confirm', {
      method: 'POST',
      body: alsText({
        generation_id: generationId,
        aufruf_id: aufrufId,
        erlaubt,
        ...(antwort === null ? {} : { antwort }),
        ...(dauerhaft ? { name, dauerhaft } : {}),
      }),
    }),

  /* Rules saved by "Always allow" (step 12) — seen and taken back. */
  immerErlaubteWerkzeuge: () => ruf('/permissions/always-allow'),
  immerErlaubenEntfernen: (name) =>
    ruf(`/permissions/always-allow/${encodeURIComponent(name)}`, { method: 'DELETE' }),

  /* Agents and jobs (6.5/6.6). `agentDateien` also lists broken ones —
     a file that shows up nowhere could never be repaired. */
  agenten: () => ruf('/agents'),
  agentDateien: () => ruf('/agent-files'),
  agentDatei: (name) => ruf(`/agents/${encodeURIComponent(name)}`),
  agentSichern: (name, content) =>
    ruf(`/agents/${encodeURIComponent(name)}`, { method: 'PUT', body: alsText({ content }) }),
  /* The form's save: named fields instead of raw text. The server touches
     only what is sent and keeps everything else in the file. */
  agentFelderSichern: (name, felder) =>
    ruf(`/agents/${encodeURIComponent(name)}/fields`, { method: 'PUT', body: alsText(felder) }),
  agentLoeschen: (name) => ruf(`/agents/${encodeURIComponent(name)}`, { method: 'DELETE' }),

  /* The hand-set capability of an endpoint — the switch for models whose
     provider reports nothing about what they can see. */
  anbieterFaehigkeiten: (id, felder) =>
    ruf(`/providers/${encodeURIComponent(id)}/capabilities`, { method: 'PUT', body: alsText(felder) }),

  /* The context window of an endpoint, said by hand — for the providers
     whose model list never names one. */
  anbieterKontext: (id, tokens) =>
    ruf(`/providers/${encodeURIComponent(id)}/context`, {
      method: 'PUT', body: alsText({ context_tokens: tokens }),
    }),

  /* The endpoint's "Timeout" setting — on cuts a model call off after
     600 s of silence, off leaves it running as long as the server takes. */
  anbieterZeitgrenze: (id, an) =>
    ruf(`/providers/${encodeURIComponent(id)}/timeout`, {
      method: 'PUT', body: alsText({ timeout_enabled: an }),
    }),

  /* Every job: a waiting agent's question must stay in its chat's box however
     many jobs were touched after it. */
  auftraege: () => allPages((limit, offset) => ruf(`/jobs?limit=${limit}&offset=${offset}`)),
  auftragStarten: (daten) => ruf('/jobs', { method: 'POST', body: alsText(daten) }),
  /* Which model a run started now would land on. The SAME answer the server
     books the run with — the window shows it instead of working it out for
     itself, so the row and the run cannot name two different models.
     `endpunkt` is the row's pick, `brauchtWerkzeuge` whether
     this agent works through tools. */
  laufmodell: (endpunkt, brauchtWerkzeuge) =>
    ruf(
      `/jobs/laufmodell?werkzeuge=${brauchtWerkzeuge ? 'true' : 'false'}` +
        (endpunkt ? `&endpoint_id=${encodeURIComponent(endpunkt)}` : '')
    ),
  auftrag: (id) => ruf(`/jobs/${id}`),
  auftragAbbrechen: (id) => ruf(`/jobs/${id}/cancel`, { method: 'POST' }),

  /* The answer to a question a run asked. ONE way in for both cases — the
     run still holding the call open, and the run a restart took away, whose
     work is carried on from its own status instead. Whoever answers cannot
     see which of the two they are in, and does not have to. */
  auftragBeantworten: (id, antwort) =>
    ruf(`/jobs/${id}/answer`, { method: 'POST', body: alsText({ antwort }) }),
  auftragLoeschen: (id) => ruf(`/jobs/${id}`, { method: 'DELETE' }),
}

/*
  Fetch the answer and deliver it piece by piece.

  Returns an asynchronous stream of events, just as the server sends them:
  start, reasoning, content, tool_call, tool_result, stats, error, done.
  The caller decides what to display from it.

  The AbortController is handed in from outside so the stop button can
  really close the connection — that's what makes the model server stop
  computing.
*/
async function* sseLesen(antwort) {
  const leser = antwort.body.getReader()
  const dekoder = new TextDecoder()
  let rest = ''
  /* Whether the run said it was over. EVERY complete stream ends with
     `done` (app/api/v1/generierung.py, app/api/v1/auftraege.py), so a body
     that simply stops is a torn one: a proxy that reaped the connection,
     a service that died mid-answer. Read as an ordinary end, the window
     hung the green dot on half an answer and let the queue send on; the
     caller is told instead, and treats it exactly like a line that broke. */
  let abgeschlossen = false

  while (true) {
    const { done, value } = await leser.read()
    if (done) break
    rest += dekoder.decode(value, { stream: true })
    const teile = rest.split('\n\n')
    rest = teile.pop()
    for (const roh of teile) {
      if (!roh.startsWith('data:')) continue
      try {
        const ereignis = JSON.parse(roh.slice(5))
        if (ereignis?.typ === 'done') abgeschlossen = true
        yield ereignis
      } catch {
        // A broken packet must not tear down the stream.
      }
    }
  }
  /* An ordinary `Error`, so it carries no `status` — exactly the shape a
     broken fetch has, and the reason the window tells a refusal apart from
     a tear (App.svelte reads `fehler.status`). */
  if (!abgeschlossen) throw new Error(abrissText())
}

export async function* antwortStrom(koerper, signal) {
  const antwort = await fetch(`${BASIS}/chat/completions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...sprachkopf(),
      ...(SCHLUESSEL ? { 'X-Sitzungsschluessel': SCHLUESSEL } : {}),
    },
    body: alsText(koerper),
    signal,
  })
  if (!antwort.ok) throw await errorFrom(antwort)
  yield* sseLesen(antwort)
}

/*
  Attaches to a run already underway — a chat's or a job's, same event
  format either way. `ab` resumes after a dropped connection: it is the
  count of events already delivered on an earlier attempt, so nothing is
  shown twice.
*/
export async function* zusehenStrom(generationId, ab, signal) {
  const antwort = await fetch(`${BASIS}/chat/stream/${generationId}?ab=${ab}`, {
    signal,
    headers: { ...sprachkopf(), ...(SCHLUESSEL ? { 'X-Sitzungsschluessel': SCHLUESSEL } : {}) },
  })
  if (!antwort.ok) throw await errorFrom(antwort)
  yield* sseLesen(antwort)
}
