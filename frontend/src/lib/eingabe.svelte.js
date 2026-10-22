/*
  What the bar under a chat holds before it is sent: the words, one draft
  per chat, the pictures and documents attached to them, the thinking stage
  of the chosen model, the send itself and the words that come in by dictation.

  It lives here, not in a window: the desktop bar and the phone bar fill and
  send the same draft. A page hands its view over with `ansicht()` — the
  field, what focuses it, whether a question card hides the bar, and what
  ends the live mirror of a dictation — and reads the state through the
  getters.
*/

import { untrack } from 'svelte'
import { compactTopic, skillAmAnfang } from './skills.svelte.js'
import { einreihen } from './warteschlange.svelte.js'
import { chosenModelOff } from './modelle.svelte.js'
import { placeWords } from './dictationMirror.js'
import { wordsInFront } from './giveBackWords.js'
import { api } from './api.js'
import { bildZeigen } from './bildschau.svelte.js'
import { t } from './texte.svelte.js'
import { benutzerfrageBeantworten, chatSichern, laufVon, melde, zustand } from './zustand.svelte.js'
import { meldeText } from './meldewesen.svelte.js'
import { diktat, standLaden as diktatStandLaden } from './diktat.svelte.js'
import { chatRun } from './chatlauf.svelte.js'

export function createEingabe() {
  /* The view of the page that is showing the bar right now. */
  let view = null
  let feld = null
  let fokus = () => {}
  let questionHidden = () => false
  let mitlesenBeenden = () => {}
  let zwischenWeg = () => {}
  let ansichtBereich = () => null
  const { senden, compactChat } = chatRun



  let text = $state('')

  /* One draft per conversation: the words AND what was attached to them.
     What is picked and not sent belongs to the chat it was picked in —
     switching away parks it here, switching back restores it, and a foreign
     chat never shows another chat's words or pictures.

     Session-only on purpose: a draft is a thought, not a document. An image
     is still a File the browser holds until the message is sent — nothing
     uploaded, nothing a stored name could point at, so its object URL is
     kept alive across the switch rather than revoked; sending is what
     releases it. A document (4.1) is uploaded the moment it is attached
     instead, so its entry in the draft already carries the stored copy's
     own id — the switch parks that id, not a File. */
  const entwuerfe = new Map()

  const LEERER_ENTWURF = { text: '', anhaenge: [], dokumentAnhaenge: [] }

  let entwurfChat = zustand.aktiverChat

  /* What was typed and not sent survives the page reloading itself after a
     service restart (lib/api.js, `sitzungNeuLaden`): the bar parks the
     words in the tab's own storage on the way out and takes them back on
     the way in. Only the words — attachments are Files the old page held,
     and they are gone with it. */
  const NEULADE_ENTWURF = 'exe-ai:entwurf-vor-neuladen'

  try {
    const geparkt = sessionStorage.getItem(NEULADE_ENTWURF)
    if (geparkt) {
      sessionStorage.removeItem(NEULADE_ENTWURF)
      /* The words come back WITH the chat they were typed in. The page
         starts with no chat open; words put straight into the field here
         belonged to whichever chat was opened next and were filed under
         the empty start the moment one was — gone from the screen. Filed
         under their own chat instead, they are in the field the moment
         that chat is opened, the way any draft is. A bare string is a
         page from before the chat was parked alongside. */
      let wieder = { text: geparkt, chat: null }
      try {
        const gelesen = JSON.parse(geparkt)
        if (gelesen && typeof gelesen === 'object' && typeof gelesen.text === 'string') {
          wieder = { text: gelesen.text, chat: gelesen.chat ?? null }
        }
      } catch {
        /* a plain string — the old shape */
      }
      if (wieder.chat === null || wieder.chat === entwurfChat) text = wieder.text
      else entwuerfe.set(wieder.chat, { ...LEERER_ENTWURF, text: wieder.text })
    }
  } catch {
    /* no storage — nothing parked, nothing to take back */
  }

  /* Vision: image attachments as pills above the field — several per
     message. ✕ removes one, all are sent along with the text. The caps
     are DISPLAY limits so the pill rows stay readable, never a context
     judgment: one row of six for images, two rows for documents. */
  let anhaenge = $state([]) // [{ datei, url }]
  const MAX_BILDER = 6

  const MAX_DOKUMENTE = 12


  const laeuftGerade = $derived(
    // A send that is still uploading is as busy as a run: the answer row
    // is already born, and a second send in that window would collide
    // with it (same placeholder id). Queued instead, like during a run.
    Boolean(laufVon(zustand.aktiverChat)) || Boolean(zustand.sendet[zustand.aktiverChat]),
  )

  /* What the chosen model offers in the way of thinking: the stages, the
     default, what kind of control that has to be, and the word each stage
     travels under. Reported by the service (app/denkstufen.py) and shown as
     reported — the window keeps no list of its own and works nothing out
     from a boolean. */
  const modellEintrag = $derived(zustand.modelle.find((m) => m.id === zustand.modellId))

  const denkprofil = $derived(modellEintrag?.denkprofil ?? null)

  const denkFaehig = $derived(
    denkprofil?.art === 'stufen' || denkprofil?.art === 'schalter',
  )

  /* How deeply the model is asked to think. It belongs to the MODEL, not to
     the chat: somebody who set it low for a small local model does not mean
     it for the big one in the next chat. It lives in the settings cascade
     under `modell:<id>` (app/denkenwahl.py) — it used to sit in browser
     storage, where the program itself could not see it and a second window
     started over.

     Older rows hold `{an: true|false}`, from the days of two positions.
     Nothing is renamed or migrated; the reader translates, exactly as the
     service does on its own side. */
  /* The stage, together with the model it belongs to — so a value read or
     set for one model can never apply to another, not even for one frame
     after a switch. `picked` marks a stage set by hand since it was read:
     only that one travels with a request. */
  let denken = $state({ modell: null, stufe: null, picked: false })

  /* Counts the stages set by hand. A read that went out before the last one
     answers with what was stored before it, and must not put that back. */
  let denkWahlen = 0

  /* The stage in force: the one stored or set for THIS model, as far as it
     still offers it — otherwise the stage the service sends for it
     (`thinking_sent`: the nearest weaker one for a stage the model dropped,
     the model's own default where nothing usable is stored), which also
     stands until the stored stage has been read. The switch shows it; a
     request carries it only once it was set by hand (see the send below),
     and otherwise leaves the stored stage to the service. */
  const denkStufe = $derived(
    denken.modell === zustand.modellId && denkprofil?.stufen?.includes(denken.stufe)
      ? denken.stufe
      : modellEintrag?.thinking_sent ?? denkprofil?.standard ?? null,
  )

  function denkenSetzen(stufe) {
    if (!denkFaehig) return
    denkWahlen += 1
    denken = { modell: zustand.modellId, stufe, picked: true }
    api
      .einstellungSetzen('modell:' + zustand.modellId, 'denken', { stufe })
      .catch(() => {})
  }

  const BILD_TYPEN = ['image/png', 'image/jpeg', 'image/webp']

  /* Document attachments (4.1), a list like the images. No vision
     requirement: every model can read text. */
  let dokumentAnhaenge = $state([]) // [{ id, datei, dokument }]
  /* The endings the window treats as documents — the upload route
     (app/api/v1/dokumente.py) accepts the same set; one test holds the
     two lists equal. */
  const DOKUMENT_ENDUNGEN = [
    '.pdf',
    '.txt', '.md', '.markdown', '.csv', '.tsv', '.log', '.json', '.jsonl', '.ndjson', '.xml',
    '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf', '.properties', '.html', '.htm',
    '.css', '.scss', '.sass', '.less', '.py', '.pyi', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx',
    '.sh', '.bash', '.zsh', '.fish', '.ps1', '.bat', '.c', '.h', '.cpp', '.cc', '.hpp', '.cs',
    '.java', '.kt', '.go', '.rs', '.rb', '.php', '.pl', '.lua', '.r', '.jl', '.swift', '.m',
    '.scala', '.clj', '.ex', '.exs', '.erl', '.sql', '.graphql', '.proto', '.tf', '.hcl',
    '.dockerfile', '.makefile', '.cmake', '.gradle', '.rst', '.tex', '.srt', '.vtt', '.diff',
    '.patch', '.svg',
  ]

  // A plain object handed to $state gets wrapped the moment it enters a
  // reactive array — reads through the array return that wrapper, not the
  // original reference this function still holds. Writing straight onto
  // that original later (`eintrag.dokument = …`) lands on data nothing
  // reads anymore: the wrapper's own copy never sees it, forever. Every
  // async result below crosses back in through an indexed write to
  // whichever array — live or parked — currently holds the matching `id`
  // instead, which Svelte does track. Promises stay off the entry for the
  // same reason: a value assigned after the fact would suffer the same
  // fate as `dokument` above.
  let dokUploads = new Map() // id -> Promise

  function dokEintragSetzen(id, patch) {
    const i = dokumentAnhaenge.findIndex((e) => e.id === id)
    if (i !== -1) {
      dokumentAnhaenge[i] = { ...dokumentAnhaenge[i], ...patch }
      return true
    }
    // Switching chats mid-upload parks the draft's whole array into
    // `entwuerfe` (see the draft-park effect above) — the entry is still
    // wanted, just not by the chat on screen right now.
    for (const entwurf of entwuerfe.values()) {
      const j = entwurf.dokumentAnhaenge.findIndex((e) => e.id === id)
      if (j !== -1) {
        entwurf.dokumentAnhaenge[j] = { ...entwurf.dokumentAnhaenge[j], ...patch }
        return true
      }
    }
    return false
  }

  // The removal side of the same search: a failed upload has to come out
  // of whichever array — live or parked — still holds it, for the same
  // reason `dokEintragSetzen` looks in both.
  function dokEintragEntfernen(id) {
    if (dokumentAnhaenge.some((e) => e.id === id)) {
      dokumentAnhaenge = dokumentAnhaenge.filter((e) => e.id !== id)
      return
    }
    for (const entwurf of entwuerfe.values()) {
      if (entwurf.dokumentAnhaenge.some((e) => e.id === id)) {
        entwurf.dokumentAnhaenge = entwurf.dokumentAnhaenge.filter((e) => e.id !== id)
        return
      }
    }
  }

  function istDokument(datei) {
    const name = (datei?.name || '').toLowerCase()
    return DOKUMENT_ENDUNGEN.some((endung) => name.endsWith(endung))
  }

  /* Uploaded the moment it is attached, not on send: the card
     needs a stored path to open the same second it exists, and the system
     never sees a document that is only "about to be sent". A chat may not
     exist yet at this point — the empty start defers it exactly like
     setting a working folder already did (arbeitsordner.svelte.js). */
  async function dokumentSetzen(datei) {
    // The drop path also respects the feature switch from the config —
    // and says so instead of letting the file vanish without a word.
    if (!zustand.features.document_upload) {
      melde(t('fehler.funktion_aus'), 'fehler')
      return
    }
    if (!datei || !istDokument(datei)) {
      if (datei) melde(t('fehler.dokument_typ'), 'fehler')
      return
    }
    if (dokumentAnhaenge.length >= MAX_DOKUMENTE) {
      meldeText('eingabe.dokumente_voll', { anzahl: MAX_DOKUMENTE }, 'hinweis')
      return
    }
    // Not `crypto.randomUUID()`: a page reached over plain HTTP (a
    // Tailscale or LAN address) is not a secure context, where that
    // function does not exist at all.
    const id = `dok-${Math.random().toString(36).slice(2, 9)}`
    dokumentAnhaenge = [...dokumentAnhaenge, { id, datei, dokument: null }]
    // Read by absenden(), which awaits every attachment's own upload
    // before it builds the list it sends, so a document dragged in a
    // split second before Enter still makes the message instead of
    // silently missing it.
    dokUploads.set(
      id,
      (async () => {
        try {
          const chat = await chatSichern()
          const { dokument } = await api.dokumentHochladen(chat.id, datei)
          if (!dokEintragSetzen(id, { dokument })) {
            // Gone from both the live array and every parked draft — the
            // ✕ already dropped it. The copy landed anyway, so it goes
            // the same way the ✕ would have sent it.
            api.dokumentLoeschen(dokument.id).catch(() => {})
          }
        } catch (fehler) {
          dokEintragEntfernen(id)
          melde(String(fehler.message || fehler), 'fehler')
        } finally {
          dokUploads.delete(id)
        }
      })(),
    )
  }

  function dokumentEntfernen(index) {
    const eintrag = dokumentAnhaenge[index]
    dokumentAnhaenge = dokumentAnhaenge.filter((_, n) => n !== index)
    // Best effort: the card is gone from the draft either way, and a
    // stray row from a delete that failed is no worse than one from a
    // draft nobody ever came back to finish.
    if (eintrag?.dokument?.id) api.dokumentLoeschen(eintrag.dokument.id).catch(() => {})
  }

  async function dokumentOeffnen(index) {
    const eintrag = dokumentAnhaenge[index]
    if (!eintrag?.dokument) return
    try {
      await api.dokumentOeffnen(eintrag.dokument.id)
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    }
  }

  /* Only offer what the chosen model can actually see — the capability
     comes from the endpoint's configuration, never from guesswork. */
  const visionFaehig = $derived(
    Boolean(zustand.modelle.find((m) => m.id === zustand.modellId)?.capabilities?.vision),
  )

  function anhangSetzen(datei) {
    if (!datei || !BILD_TYPEN.includes(datei.type)) {
      /* The refusal names the kind the file was: an image — by its type,
         or by its name where the type is missing, as drags out of many
         programs deliver none — is an image question, everything else is
         a kind of document the window does not read; a picture list is no
         answer for a Word file. */
      if (datei) {
        const name = (datei.name || '').toLowerCase()
        const istBild = datei.type.startsWith('image/') ||
          BILD_TYPEN.some((typen) => name.endsWith('.' + typen.split('/')[1]))
        melde(t(istBild ? 'fehler.bild_typ' : 'fehler.dokument_typ'), 'fehler')
      }
      return
    }
    if (!visionFaehig) {
      melde(t('fehler.kein_vision'), 'hinweis')
      return
    }
    if (anhaenge.length >= MAX_BILDER) {
      meldeText('eingabe.bilder_voll', { anzahl: MAX_BILDER }, 'hinweis')
      return
    }
    anhaenge = [...anhaenge, { datei, url: URL.createObjectURL(datei) }]
  }

  function anhangEntfernen(index) {
    const eintrag = anhaenge[index]
    if (eintrag) URL.revokeObjectURL(eintrag.url)
    anhaenge = anhaenge.filter((_, n) => n !== index)
  }

  function anhaengeLeeren() {
    for (const eintrag of anhaenge) URL.revokeObjectURL(eintrag.url)
    anhaenge = []
    dokumentAnhaenge = []
  }

  function bildOeffnen(index) {
    const eintrag = anhaenge[index]
    if (eintrag) bildZeigen(eintrag.url)
  }

  // Keyed by chat, not one flag for the whole bar: the stretch between
  // Enter and the message actually clearing the field can take real time
  // (a pending document upload) — a bare boolean would leave a send
  // pending in one chat blocking a completely unrelated send the hand
  // starts in another while it waits, the same way `zustand.sendet` is
  // already keyed rather than a single flag.
  let sendetGerade = new Set()

  /* What each send took out of the bar, keyed by the id of the message it
     became (`senden` takes the bar's id as the question's own): the
     pictures and the documents. Kept for the one case that
     wants them back — a send the service refused because its chat was taken
     (App.svelte, `belegt`) — and dropped once that send is over, handed back
     or not, so nothing comes back twice and a later send in another chat
     cannot stand in for it. Window memory only; nothing of it is stored. */
  const zurueckbehalten = new Map()

  /* Whether these words answer a question a running answer waits on: only
     words do, and only a question that stands in this window and is not
     hidden. ONE rule for Enter (`absenden`) and for the arrow: the arrow is
     locked exactly where Enter sends nothing. */
  function antwortetOffeneFrage(inhalt) {
    return Boolean(inhalt && zustand.benutzerfrage[zustand.aktiverChat])
      && !questionHidden(zustand.aktiverChat)
  }

  async function absenden() {
    const inhalt = text.trim()
    if (!inhalt && !anhaenge.length && !dokumentAnhaenge.length) return
    /* The chat's model is switched off: nothing goes out, and the words stay
       in the field — "Model disabled" stands in the bar and opens the
       picker, and with a model that is on, the same Enter sends. Answering a
       question a running answer waits on is not a new send: that run was
       started before the switch, and it would otherwise wait forever. Only
       words answer it, as `senden` (App.svelte) takes them: a send of
       nothing but attachments is a new send, which `senden` turns down
       while the model is off — and the bar, already cleared, would have
       lost them without a word. */
    const answersQuestion = antwortetOffeneFrage(inhalt)
    if (chosenModelOff() && !answersQuestion) return
    /* No model can be reached: nothing can go out, so the words and what is
       attached stay in the bar and the notice says why. A first message
       typed before any model is set up must not vanish behind that notice.
       Answering a standing question is not a new send and passes. */
    if (!zustand.modellId && !answersQuestion) {
      melde(t('fehler.kein_modell_verfuegbar'), 'fehler')
      return
    }
    const chatBeimStart = zustand.aktiverChat
    if (sendetGerade.has(chatBeimStart)) return
    sendetGerade.add(chatBeimStart)
    try {
      /* `/compact` is the window's own command: the line is not a message and
         never goes to the model. Where an answer is running the line stays in
         the field, for the same hint every busy send gets — the fold would
         rewrite the history the answer is being written from. What was
         attached stays in the bar. */
      const topic = compactTopic(inhalt)
      if (topic !== null) {
        if (laeuftGerade) {
          melde(t('fehler.antwort_laeuft_schon'))
          return
        }
        text = ''
        compactChat(topic)
        return
      }
      const bilder = anhaenge.map((a) => a.datei)
      // Snapshot now: `dokumentAnhaenge` (and `text`/`anhaenge`, read again
      // below) is swapped out from under this function the moment the chat
      // changes underneath it — the draft-park effect reassigns it whole.
      // Reading it again after the await would build the message out of
      // whichever chat happens to be on screen once the upload resolves,
      // not the one it was typed for.
      const dokEintraege = dokumentAnhaenge
      // Every document is already uploaded (dokumentSetzen) or on its way —
      // one dropped in a split second before Enter still makes the message.
      await Promise.all(dokEintraege.map((d) => dokUploads.get(d.id)))
      if (zustand.aktiverChat !== chatBeimStart) {
        // The hand moved to another chat while the upload was still in
        // flight. Nothing is lost — the draft-park effect already parked
        // this exact text and these exact attachments under the chat that
        // was on screen when it fired — but sending now would deliver them
        // into whichever chat is showing today, not the one they were
        // typed for.
        melde(t('eingabe.chat_gewechselt_waehrend_senden'))
        return
      }
      const dokumente = dokEintraege.map((d) => d.dokument).filter(Boolean)
      /* The entries themselves, not what goes to the model: they are what a
         refusal has to hand back, exactly as they stood — the stored
         document and the File behind each picture. Taken before the bar is
         cleared, because clearing is what drops them. */
      const kept = { bilder: anhaenge, dokumente: dokEintraege }
      text = ''
      /* Words typed while the model waits on a question in this chat answer
         it, and `senden` takes nothing else then (App.svelte). What was
         attached stays in the bar, neither sent nor lost: it goes with the
         next message. */
      if (inhalt && zustand.benutzerfrage[chatBeimStart] && !questionHidden(chatBeimStart)) {
        senden(inhalt)
        return
      }
      anhaengeLeeren()
      /* The picked skill travels beside the message, not inside it. The
         "/name" stays in the text on purpose: it is what was typed, so it is
         what gets stored, and the chat still shows it after a reload. */
      const skill = skillAmAnfang(inhalt)?.name ?? null
      /* The thinking stage only goes along if the model really has one, and
         only when it was set by hand for this model since it was read: the
         service resolves the stored stage itself (app/denkenwahl.py), so
         one stored as "off" holds even before the window has read it. */
      const stagePicked = denkFaehig && denken.picked && denken.modell === zustand.modellId
      const auftrag = { inhalt, bilder, dokumente, denken: stagePicked ? denkStufe : null, skill }
      /* An answer is still running: the message lines up instead of being
         swallowed. The field empties either way, so typing on feels the same
         whether something runs or not.

         Unless the model is the one waiting HERE: a standing question holds
         the run open, so `laeuftGerade` is true — but what was typed IS the
         answer to that question, not a new message. Queueing it would leave
         the run waiting for something that is sitting in a queue waiting for
         the run. `senden` knows what to do with it. A question standing in
         ANOTHER chat does not turn this chat's typing into its answer. */
      const frageHier = Boolean(zustand.benutzerfrage[chatBeimStart]) && !questionHidden(chatBeimStart)
      if (laeuftGerade && !frageHier) {
        einreihen(chatBeimStart, { ...auftrag, kept })
        /* A question pushed away with "later" is not the one being answered:
           what was typed is a message of its own and lines up like any
           other while the run goes on. The hidden question closes with an
           empty answer — the model gets its own "no answer" line and goes
           on with an assumption instead of waiting on words that were meant
           for something else. */
        if (questionHidden(chatBeimStart)) benutzerfrageBeantworten('', chatBeimStart)
        return
      }
      // The same shape as the id `senden` would make itself.
      const messageId = Math.random().toString(36).slice(2, 9)
      const release = keep(messageId, kept)
      senden(auftrag.inhalt, bilder, dokumente, auftrag.denken, skill, false, messageId)
        .finally(release)
    } finally {
      sendetGerade.delete(chatBeimStart)
    }
  }

  /* What a send took out of the bar, kept under the send's id until the send
     is over — whoever sends (the bar itself, or the queue handing on a
     message it held) hands the entries in, and `zurueckgeben` finds them by
     that id. Returns the way to let go of them again. */
  function keep(messageId, kept) {
    zurueckbehalten.set(messageId, kept)
    return () => zurueckbehalten.delete(messageId)
  }

  /* A send that did not reach the service — its chat was taken, an answer
     the service started by itself was going (App.svelte, `belegt`), or it
     ended before the request (no model, a picture that would not upload):
     the words AND what was attached to them come back, so nothing typed and
     nothing picked is lost and nothing stands twice. The words only into an
     empty field; whatever was typed since stays. */
  function zurueckgeben(inhalt, chat = entwurfChat, messageId = null) {
    /* The refused message's own attachments, found by its id — the id alone
       proves they belong to this refusal, so no chat is compared (a send
       from a fresh chat started with none and was refused under the one it
       made). A send this bar did not make (the queue dispatching a message
       it held) has no entry: its words come back, nothing else. Dropped
       either way — what was not handed back now is not handed back
       tomorrow. */
    const behalten = zurueckbehalten.get(messageId)
    zurueckbehalten.delete(messageId)
    /* No count check on the way back: MAX_BILDER and MAX_DOKUMENTE bound
       what the person PICKS (anhangSetzen/dokumentSetzen), never what a
       refused send returns — a send that carried six pictures has to be
       able to give its six back, and one that carried two has to give them
       beside the three picked meanwhile. */
    const zurueckBilder = () =>
      (behalten?.bilder ?? []).map((e) => ({ datei: e.datei, url: URL.createObjectURL(e.datei) }))
    const zurueckDokumente = () => behalten?.dokumente ?? []
    /* Into the field only while its chat is the one they belong to; after a
       switch they go to that chat's draft and are in the field when it is
       opened again. */
    if (chat !== entwurfChat) {
      const bisher = entwuerfe.get(chat) ?? LEERER_ENTWURF
      entwuerfe.set(chat, {
        text: bisher.text.trim() ? bisher.text : inhalt,
        anhaenge: [...bisher.anhaenge, ...zurueckBilder()],
        dokumentAnhaenge: [...bisher.dokumentAnhaenge, ...zurueckDokumente()],
      })
      return
    }
    anhaenge = [...anhaenge, ...zurueckBilder()]
    dokumentAnhaenge = [...dokumentAnhaenge, ...zurueckDokumente()]
    if (!text.trim()) text = inhalt
  }

  /* Messages that waited in the line come back into the field of their chat —
     the ✕ on a bubble gives one back, a stop by hand gives back all of them:
     what was attached comes with each, and their words stand in front of
     whatever has been typed since, in the order they were written. A chat
     that is not the open one gets them in its draft. */
  function takeBackAll(entries, chat = entwurfChat) {
    if (!entries.length) return
    const getippt = text
    for (const entry of entries) {
      const entryId = `queue-${entry.id}`
      keep(entryId, entry.kept)
      zurueckgeben('', chat, entryId)
    }
    if (chat === entwurfChat) {
      text = wordsInFront(entries, getippt)
      fokus()
      return
    }
    const draft = entwuerfe.get(chat) ?? LEERER_ENTWURF
    entwuerfe.set(chat, { ...draft, text: wordsInFront(entries, draft.text) })
  }

  function takeBack(entry) {
    takeBackAll([entry])
  }

  /* --- Dictation ---------------------------------------------------------

     Press, speak, press. The words land in the field and stay there: Enter
     sends, exactly as it always has, and nothing about that changes because
     the words arrived through a microphone rather than a keyboard. It is
     also the reason nothing here filters what a speech model invents out of
     silence — the sentence is on screen before anybody sends it. Unless
     "Auto-send dictation" is on: then the words go out unread, which is
     what that switch is for, and it ships switched off. */
  let holtText = $state(false)

  /* The pass after the stop, while it runs: Escape aborts it through this
     (`cancelTranscription` below). No deadline of its own — a long
     recording on a slow machine takes as long as it takes. */
  let transcriptionAbort = null

  /* Where the words go is decided in lib/dictationMirror.js; what is left
     here is the field: its text, its focus and its cursor. */
  function diktatEinfuegen(neu, bereich = null) {
    const stueck = (neu ?? '').trim()
    if (!stueck) return false
    const imFeld = feld && document.activeElement === feld
    const platz = placeWords(text, {
      range: bereich,
      cursor: imFeld ? { start: feld.selectionStart, end: feld.selectionEnd } : null,
      spoken: stueck,
    })
    text = platz.text
    fokus()
    /* After the field has been redrawn with the new text — setting the
       selection on the old value would put the cursor somewhere else. */
    queueMicrotask(() => feld?.setSelectionRange(platz.caret, platz.caret))
    return true
  }

  async function diktatHolen(blob) {
    mitlesenBeenden()
    if (!blob) {
      zwischenWeg()
      return
    }
    holtText = true
    const chatBeimStopp = zustand.aktiverChat
    const controller = new AbortController()
    transcriptionAbort = controller
    try {
      const antwort = await api.spracheTranskribieren(blob, { signal: controller.signal })
      // Answered: from here on there is nothing left for Escape to abort.
      transcriptionAbort = null
      // The last pass, over the whole recording and tidied, replaces what
      // was shown while it was still being spoken.
      const bereich = ansichtBereich()
      zwischenWeg()
      const eingefuegt = diktatEinfuegen(antwort?.text, bereich)
      // "Auto-send dictation": the words go out the moment they are in,
      // the same way Enter would send them — read fresh, since the switch
      // may have been turned in another window since this page loaded it.
      // Only into the chat the words were spoken for: another chat opened
      // meanwhile gets them in its field, with its own draft, unsent.
      await diktatStandLaden(true)
      if (eingefuegt && diktat.automatik && zustand.aktiverChat === chatBeimStopp) absenden()
      /* Said out loud, and only where it is true: a clean-up that was
         switched off skipped nothing. The answer says which of the two it
         was, because this page's own copy of that setting is as old as the
         last time the panel was open. */
      if (antwort?.bereinigung !== 'aus' && !antwort?.bereinigt) {
        melde(t('sprache.bereinigung_uebersprungen'))
      }
    } catch (fehler) {
      zwischenWeg()
      // Thrown away on purpose: the field keeps what stood in it before the
      // dictation, and there is nothing to report.
      if (fehler?.name === 'AbortError') return
      melde(String(fehler.message || fehler), 'fehler')
    } finally {
      holtText = false
      if (transcriptionAbort === controller) transcriptionAbort = null
    }
  }

  /* Called from App.svelte's Escape handler: a pass after the stop that is
     still waiting for the speech service is thrown away, the way Escape
     throws away a running recording. The mirror goes, the field and the
     microphone button are free again. */
  function transcribing() {
    return transcriptionAbort !== null
  }

  function cancelTranscription() {
    transcriptionAbort?.abort()
  }



  /* Files for the plus menu's one entry: pictures where the model sees them,
     documents where the feature is on. */
  const acceptedFiles = $derived(
    [
      ...(visionFaehig ? BILD_TYPEN : []),
      ...(zustand.features.document_upload ? DOKUMENT_ENDUNGEN : []),
    ].join(','),
  )

  const filesHint = $derived(
    zustand.features.document_upload
      ? t(visionFaehig ? 'eingabe.attach_files_hint' : 'eingabe.dokument_hinweis')
      : t(visionFaehig ? 'eingabe.anhang_hinweis' : 'fehler.kein_vision'),
  )

  function filesChosen(files) {
    for (const datei of files) {
      if (istDokument(datei)) dokumentSetzen(datei)
      else anhangSetzen(datei)
    }
  }

  /* The page leaving the tab for a reload parks the words in the tab's own
     storage; the same words come back on the way in (see above). */
  function neuladeParken() {
    const parken = () => {
      try {
        if (text.trim()) {
          sessionStorage.setItem(
            NEULADE_ENTWURF,
            JSON.stringify({ text, chat: entwurfChat }),
          )
        }
      } catch {
        /* no storage — the words go with the page */
      }
    }
    window.addEventListener('exe-ai:vor-neuladen', parken)
    return () => window.removeEventListener('exe-ai:vor-neuladen', parken)
  }

  /* The chat on screen changed: park this chat's draft, restore the one of
     the chat opened. */
  function chatWechseln(chat) {
    if (chat === entwurfChat) return
    untrack(() => {
      // The transition out of the empty start (no chat yet, key `null`) is
      // not always a chat switch. Choosing a working folder or sending the
      // first message creates the chat and points `aktiverChat` at it in
      // the same breath, before `chatsLaden()` has a chance to add it to
      // `zustand.chats` — so a brand-new id, still missing from that list
      // at this exact moment, means this is the empty start getting its
      // first id, the same conversation rather than a different one.
      // Relabelling keeps the words in the field and files them under the
      // chat they actually belong to. An id ALREADY in `zustand.chats` is a
      // real switch to a chat that has its own draft (or none) waiting —
      // picking one from the sidebar while the start is still empty must
      // still load that chat's own words, not carry the empty start's over.
      if (entwurfChat === null && chat !== null && !zustand.chats.some((c) => c.id === chat)) {
        // The words moved to the new chat with the label. Anything parked
        // under the empty start earlier belongs to that same hand and has
        // just been carried over — left behind, it would be handed to the
        // NEXT fresh start as if it had been typed there.
        entwuerfe.delete(null)
        entwurfChat = chat
        return
      }
      entwuerfe.set(entwurfChat, { text, anhaenge, dokumentAnhaenge })
      const geparkt = entwuerfe.get(chat) ?? LEERER_ENTWURF
      text = geparkt.text
      anhaenge = geparkt.anhaenge
      dokumentAnhaenge = geparkt.dokumentAnhaenge
      entwurfChat = chat
    })
  }

  /* Reads the stage stored for the chosen model; run inside an effect that
     follows the model and whether it thinks at all. */
  function denkenLaden() {
    const modellId = zustand.modellId
    if (!modellId || !denkFaehig) return
    const wahlBeimLesen = denkWahlen
    api
      .einstellungAufgeloest('denken', { modell: modellId })
      .then((gelesen) => {
        /* The model may have been switched again while this was in flight —
           the answer for the previous one must not push out the new one's —
           or a stage set by hand since is newer than what it brings back. */
        if (untrack(() => zustand.modellId) !== modellId) return
        if (denkWahlen !== wahlBeimLesen) return
        const wert = gelesen.wert || {}
        /* What was stored. Whether this model still offers it is
           `denkStufe`'s to decide, below; a plain "yes, think" from the old
           shape lands on the default there too — on a scale it says no more
           than that. */
        denken = {
          modell: modellId,
          stufe: wert.stufe ?? (typeof wert.an === 'boolean' ? (wert.an ? 'on' : 'off') : null),
          picked: false,
        }
      })
      .catch(() => {})
  }

  return {
    /* The page hands over its view and gets back what takes it away again;
       a page that is gone leaves nothing behind, and a newer view is not
       taken away by an older one. */
    ansicht(hand) {
      view = hand
      feld = hand.feld ?? null
      fokus = hand.fokus ?? (() => {})
      questionHidden = hand.questionHidden ?? (() => false)
      mitlesenBeenden = hand.mitlesenBeenden ?? (() => {})
      zwischenWeg = hand.zwischenWeg ?? (() => {})
      ansichtBereich = hand.bereich ?? (() => null)
      return () => {
        if (view !== hand) return
        view = null
        feld = null
        fokus = () => {}
        questionHidden = () => false
        mitlesenBeenden = () => {}
        zwischenWeg = () => {}
        ansichtBereich = () => null
      }
    },
    neuladeParken,
    chatWechseln,
    denkenLaden,
    BILD_TYPEN,
    DOKUMENT_ENDUNGEN,
    get text() {
      return text
    },
    set text(wert) {
      text = wert
    },
    get anhaenge() {
      return anhaenge
    },
    get dokumentAnhaenge() {
      return dokumentAnhaenge
    },
    get holtText() {
      return holtText
    },
    get laeuftGerade() {
      return laeuftGerade
    },
    get visionFaehig() {
      return visionFaehig
    },
    get modellEintrag() {
      return modellEintrag
    },
    get denkprofil() {
      return denkprofil
    },
    get denkFaehig() {
      return denkFaehig
    },
    get denkStufe() {
      return denkStufe
    },
    denkenSetzen,
    get acceptedFiles() {
      return acceptedFiles
    },
    get filesHint() {
      return filesHint
    },
    filesChosen,
    istDokument,
    anhangSetzen,
    anhangEntfernen,
    anhaengeLeeren,
    bildOeffnen,
    dokumentSetzen,
    dokumentEntfernen,
    dokumentOeffnen,
    antwortetOffeneFrage,
    absenden,
    diktatEinfuegen,
    diktatHolen,
    keep,
    zurueckgeben,
    takeBack,
    takeBackAll,
    transcribing,
    cancelTranscription,
  }
}

export const chatEingabe = createEingabe()
