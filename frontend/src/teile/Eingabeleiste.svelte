<script>
  import { flushSync, tick, untrack } from 'svelte'
  import QuestionBox from './QuestionBox.svelte'
  import Mikrofonknopf from './Mikrofonknopf.svelte'
  import VoiceLine from './VoiceLine.svelte'
  import Arbeitsordner from './Arbeitsordner.svelte'
  import FolderChip from './FolderChip.svelte'
  import Modellwahl from './Modellwahl.svelte'
  import Klappwahl from './Klappwahl.svelte'
  import Skillliste from './Skillliste.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import Leuchtpunkt from './Leuchtpunkt.svelte'
  import Denkschalter from './Denkschalter.svelte'
  import Vektorfeld from './Vektorfeld.svelte'
  import {
    berechtigungsmodus, berechtigungsmodusLaden, berechtigungsmodusSetzen, modusOptionen,
  } from '../lib/berechtigungsmodus.svelte.js'
  import {
    gefiltert, compactTopic, skillAmAnfang, skills, skillsLaden,
  } from '../lib/skills.svelte.js'
  import {
    deferQuestion, isDeferred, questionCardStands, questionKey, resumeQuestion, standingWith,
    waitingQuestions,
  } from '../lib/questionbox.svelte.js'
  import { einreihen } from '../lib/warteschlange.svelte.js'
  import { chosenModelOff } from '../lib/modelle.svelte.js'
  import { answerAgentQuestion, openTranscript } from '../lib/agentchat.svelte.js'
  import { ordnerListe } from '../lib/arbeitsordner.svelte.js'
  import {
    aufnahme,
    fehlerschluessel,
    abbrechen as aufnahmeAbbrechen,
    starten as aufnahmeStarten,
    stoppen as aufnahmeStoppen,
    oeffnen as aufnahmeOeffnen,
    schliessen as aufnahmeSchliessen,
    zwischenstand as aufnahmeZwischenstand,
  } from '../lib/aufnahme.svelte.js'
  import {
    abgeschlossen, abgleichen, lesenFaellig, neuerStand, offen, SPRACHPEGEL,
  } from '../lib/diktatabgleich.js'
  import {
    fieldSize, mirrorAfterFieldChange, mirrorParts, mirrorReading, placeWords, startMirror,
  } from '../lib/dictationMirror.js'
  import { DEFAULT_KEY, recogniser } from '../lib/microphoneKey.js'
  import { system } from '../lib/keyNames.js'
  import { layout } from '../lib/keyboardLayout.svelte.js'
  import { api } from '../lib/api.js'
  import { attachPlayback } from '../lib/playbackLevel.js'
  import { neuAusrichten, sprechtextPutzen, stueckeSchneiden } from '../lib/sprechtext.js'
  import { pauseElapsed } from '../lib/conversationPause.js'
  import { bildZeigen } from '../lib/bildschau.svelte.js'
  import { t } from '../lib/texte.svelte.js'
  import {
    zustand, werkzeugfrageBeantworten, benutzerfrageBeantworten, melde, aktuellerChat, eineSeiteOffen,
    chatSichern, laufVon, laeuftIrgendwo, nachrichtenAnzeige, aktuellesModell,
  } from '../lib/zustand.svelte.js'
  import { studioOeffnen, studioSichtbar } from '../lib/studio.svelte.js'
  import { meldeText } from '../lib/meldewesen.svelte.js'
  import { diktat, standLaden as diktatStandLaden } from '../lib/diktat.svelte.js'

  let {
    senden, abbrechen, compactChat, gruss = null, vektoren = false,
  } = $props()

  /* The permission mode for chat calls — Tor 3 (app/berechtigungen.py).
     Loaded once, lazily, the same way the tool switches load on first use. */
  $effect(() => {
    if (!berechtigungsmodus.geladen) berechtigungsmodusLaden()
  })

  let text = $state('')
  let feld = $state(null)
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
  $effect(() => {
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
  })
  $effect(() => {
    const chat = zustand.aktiverChat
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
  })
  /* Vision: image attachments as pills above the field — several per
     message. ✕ removes one, all are sent along with the text. The caps
     are DISPLAY limits so the pill rows stay readable, never a context
     judgment: one row of six for images, two rows for documents. */
  let anhaenge = $state([]) // [{ datei, url }]
  const MAX_BILDER = 6
  const MAX_DOKUMENTE = 12
  /* The one menu of the bar that is open, or '' — the plus, the folder
     chip or the model picker. Opening one closes the others, and a press
     anywhere outside the three closes it — caught on the way down, so a
     click some other part of the window stops on its way does not leave
     the menu standing. No click is stopped here either: the permission
     mode's own list closes on the same outside press. */
  let openMenu = $state('')
  function toggleMenu(name, open) {
    openMenu = open ? name : openMenu === name ? '' : openMenu
  }
  function closeMenuOutside(event) {
    if (!event.target?.closest?.('[data-bar-menu]')) openMenu = ''
  }
  /* A dialog or a page coming up over the bar takes its menu away, so the
     Escape below is never caught for a menu nobody sees while the layer
     on top waits for it. */
  $effect(() => {
    if (zustand.frage || eineSeiteOffen()) openMenu = ''
  })
  /* Escape closes an open menu and ends there — caught on the way down,
     before the window's own Escape (App.svelte) can read it as "stop the
     answer" or "push the question away". The focus goes back to the
     menu's own button, so the next Escape is not one that fell to the
     page. */
  function closeMenuOnEscape(event) {
    if (event.key !== 'Escape' || !openMenu) return
    event.stopPropagation()
    event.preventDefault()
    const name = openMenu
    openMenu = ''
    row?.querySelector(`[data-bar-menu="${name}"] button`)?.focus()
  }
  /* The permission mode's list handles its own Escape; on the way back up
     it ends here, for the same reason as the three menus above. */
  function modeListEscape(event) {
    if (event.key !== 'Escape') return
    if (event.target?.closest?.('.klappwahl') && row?.querySelector('.klappwahl .liste')) {
      event.stopPropagation()
    }
  }
  let dateiwahl = $state(null)
  /* Image mode (part 2): the raw prompt goes to the generator. On
     enabling, the image server is honestly checked — the red line says
     when none is there (reachability is the operator's/arbiter's
     business). */
  /* Image-Turbo: the optional persistent picture server. Here its state is
     only READ, to tint the plus-menu's picture icon. */
  let turboZustand = $state('aus')
  const turboAn = $derived(turboZustand === 'bereit' || turboZustand === 'zeichnet')

  async function turboStandHolen() {
    try {
      turboZustand = (await api.turboStand()).zustand ?? 'aus'
    } catch {
      turboZustand = 'aus'
    }
  }

  /* Whether the local generator is ready to draw at all (program + model) —
     the same "bereit" the Bildserver tile in the local tab shows. */
  let bildStand = $state('')
  async function bildStandHolen() {
    try {
      bildStand = (await api.bildmodelle()).stand ?? ''
    } catch {
      bildStand = ''
    }
  }

  /* The picture icon is a status light: blue (+ pulse) while Turbo runs, else
     GREEN as soon as the generator is ready to draw, else red on a turbo fault,
     else grey. */
  const bildIconFarbe = $derived(
    turboAn
      ? 'var(--blau)'
      : bildStand === 'bereit' || bildStand === 'zeichnet'
        ? 'var(--gruen)'
        : turboZustand === 'fehler'
          ? 'var(--rot)'
          : 'var(--linie-stark)',
  )

  /* While the menu is open, keep the plaque colour fresh — the server may
     still be loading its model (blue → green) after a start. */
  $effect(() => {
    if (openMenu !== 'plus') return
    turboStandHolen()
    bildStandHolen()
    const uhr = setInterval(() => {
      turboStandHolen()
      bildStandHolen()
    }, 2000)
    return () => clearInterval(uhr)
  })

  /* The slash list. It is open only while a slash stands at the very front
     and no space has followed the name yet — from the first space on, the
     rest of the line is the request and the list is in the way. */
  let skillDran = $state(0)
  const skillFilter = $derived(/^\/([a-z0-9-]*)$/.exec(text)?.[1] ?? null)
  const skillTreffer = $derived(skillFilter === null ? [] : gefiltert(skillFilter))
  const skillOffen = $derived(skillTreffer.length > 0)

  $effect(() => {
    void skillFilter
    skillDran = 0
  })

  if (!skills.geladen) skillsLaden()

  function skillWaehlen(eintrag) {
    /* The trailing space is the point: it closes the list and starts the
       request, so picking and typing on are one movement. */
    text = `/${eintrag.name} `
    feld?.focus()
    hoeheAnpassen()
  }


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
  /* Gated on `denkFaehig`, a boolean: the half-minute reload of the model
     list hands over a new profile object and must not read the stored stage
     again, and a model that always or never thinks has none to read. */
  $effect(() => {
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
  })
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

  const leer = $derived(!text.trim() && !anhaenge.length && !dokumentAnhaenge.length)
  /* The action button shows the stop sign only while a run has nothing to
     send beside it — with something in the field, sending (into the queue)
     is what the hand is after. A picture the studio draws is the studio's:
     it never claims this button. */
  const stoppt = $derived(laeuftGerade && leer)
  /* The arrow is locked because the chat's model is switched off in the
     quick choice. It then says so, in the sentence the model choice beside
     it already carries: a locked button that still read "send" named its
     job and not its reason. As the stop button it stays open, and so it
     does where the words in the field answer a question a run is waiting
     on — Enter sends those too, the run was begun before the switch. */
  const gesperrtDurchModell = $derived(
    !stoppt && chosenModelOff() && !antwortetOffeneFrage(text.trim()),
  )
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
    '.patch',
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

  /* When the window runs out of room the words go first — the folder only
     its sign and count, the mode only its dot, the model's name shortened —
     and the row stays one line. Measured, not guessed: the full form is
     laid out and measured, and the row goes narrow only when that does not
     fit. The groups are measured, not the row's scroll width: that one
     reads a few pixels past the content even with room to spare, and
     would keep the row narrow for nothing.
     Measuring waits for the next frame and happens once per frame, before
     that frame is drawn, so the resize observer never sees sizes change
     under its own feet; a full form that does not fit shows for one frame
     at most. While the row is narrow and only the room changed, the width
     the full form needed last is enough; the full form is laid out again
     only when the groups themselves changed, or when words the narrow form
     hides did.
     A second step for a row that is still too wide without its words
     (`tight`): the model's lamps leave the row — they stay on the model's
     line in its menu — and its name is cut shorter still. The microphone
     and the arrow never leave the bar: they are what the bar is for. */
  let row = $state(null)
  let narrow = $state(false)
  let tight = $state(false)
  let fullWidth = 0
  let narrowWidth = 0
  let narrowContent = 0
  let measureQueued = false
  let measureForced = false
  /* The left of the row is a stretching place for the voice line with the
     group inside it; the group is what has a width of its own. */
  function groupOf(child) {
    return child.classList.contains('links-platz') ? child.firstElementChild : child
  }
  function groupsWidth() {
    let sum = 0
    for (const child of row.children) sum += groupOf(child).getBoundingClientRect().width
    return sum
  }
  function neededWidth() {
    const gap = parseFloat(getComputedStyle(row).columnGap) || 0
    return groupsWidth() + gap * Math.max(0, row.children.length - 1)
  }
  function measureRow() {
    const forced = measureForced
    measureQueued = false
    measureForced = false
    if (!row) return
    if (narrow) {
      const unchanged = Math.abs(groupsWidth() - narrowContent) < 0.5
      if (!forced && unchanged && row.clientWidth + 1 < fullWidth) {
        // Not enough room for the full form: the second step comes and
        // goes with the room the narrow form has.
        const needsTight = row.clientWidth + 1 < narrowWidth
        if (needsTight !== tight) {
          tight = needsTight
          flushSync()
          narrowContent = groupsWidth()
        }
        return
      }
      narrow = false
      tight = false
      flushSync()
    }
    fullWidth = neededWidth()
    if (fullWidth > row.clientWidth + 1) {
      narrow = true
      flushSync()
      narrowWidth = neededWidth()
      if (narrowWidth > row.clientWidth + 1) {
        tight = true
        flushSync()
      }
      narrowContent = groupsWidth()
    }
  }
  function queueMeasure(forced = false) {
    measureForced ||= forced
    if (measureQueued) return
    measureQueued = true
    requestAnimationFrame(measureRow)
  }
  $effect(() => {
    if (!row || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(() => queueMeasure())
    /* The row and both of its groups: a group grows when its content does
       (a longer folder name, the "later" chip) while the row keeps its
       width. */
    observer.observe(row)
    for (const child of row.children) observer.observe(groupOf(child))
    return () => observer.disconnect()
  })
  /* Words the narrow form hides can change without any size changing:
     the model picker's label (another model, its name arriving with the
     list, the text for none), the mode's name, the folders. The full form
     is measured afresh when they do, and only then — a list that is
     fetched again with the same words changes nothing. */
  let modelLabel = $state('')
  const hiddenWords = $derived(
    [
      modelLabel,
      modeOptions.find(([value]) => value === berechtigungsmodus.chat)?.[1] ?? '',
      ...ordnerListe(),
    ].join('\n'),
  )
  $effect(() => {
    void hiddenWords
    untrack(() => queueMeasure(true))
  })

  /* The permission mode as a chip in the row: its lamp in the state's own
     colour and the stage's name — Auto red and breathing, Manual green,
     Restricted yellow. */
  const modeOptions = $derived(modusOptionen())
  const MODE_COLOUR = { auto: 'rot', manuell: 'gruen', restricted: 'gelb' }

  /* The question standing in this chat, and whether "later" pushed it
     away. The card and the chip that brings it back both read this. */
  /* The model's own question of this chat is there but was pushed away with
     "later": typing in the field is then not its answer. */
  function questionHidden(chatId) {
    const ask = zustand.benutzerfrage[chatId]
    return Boolean(ask) && isDeferred(chatId, { kind: 'ask', question: ask })
  }
  const waiting = $derived(waitingQuestions(zustand.aktiverChat))
  const standing = $derived(standingWith(zustand.aktiverChat, waiting))
  const questionDeferred = $derived(isDeferred(zustand.aktiverChat, standing))
  const cardStands = $derived(questionCardStands(zustand.aktiverChat))
  /* Every question of the chat that "later" pushed away, one chip each —
     also while another question stands in the card. */
  const pushedAway = $derived(waiting.filter((item) => isDeferred(zustand.aktiverChat, item)))
  const modelName = $derived(aktuellesModell()?.name ?? '')
  /* The card takes the focus along when it goes: after an answer or
     "later" it comes back to the field, so the next keys are typing
     rather than falling to the window. The bar is out of reach while the
     card stands, so the focus waits for the render that gives it back. */
  function focusFieldAfterRender() {
    tick().then(() => feld?.focus())
  }
  function answerTool(allowed, always = false, words = null) {
    werkzeugfrageBeantworten(allowed, always, zustand.aktiverChat, words)
    focusFieldAfterRender()
  }
  function answerAsk(text) {
    if (standing?.kind === 'agent') {
      answerAgentQuestion(standing.question.jobId, standing.question.aufrufId, text)
    }
    else benutzerfrageBeantworten(text)
    focusFieldAfterRender()
  }
  /* An agent's question brings its transcript along in the agents view,
     and the transcript follows when the card moves on to the next agent's.
     Offered, not forced: a view the user closed stays closed. */
  const askingJob = $derived(standing?.kind === 'agent' ? standing.question.jobId : null)
  $effect(() => {
    if (askingJob) untrack(() => openTranscript(askingJob, { asked: false }))
  })
  function later() {
    deferQuestion(zustand.aktiverChat, standing)
    focusFieldAfterRender()
  }
  /* The chip goes when it brings its card back; the focus it held goes to
     the field, and from there the card takes it as it appears. The card
     that stood until now takes the chip's place, so the question brought
     back is the one that shows. */
  function resume(item) {
    if (standing && !questionDeferred && questionKey(standing) !== questionKey(item)) {
      deferQuestion(zustand.aktiverChat, standing)
    }
    resumeQuestion(zustand.aktiverChat, item)
    focusFieldAfterRender()
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

  function einfuegen(ereignis) {
    const eintraege = [...(ereignis.clipboardData?.items || [])].filter((e) =>
      e.type.startsWith('image/'),
    )
    if (!eintraege.length) return
    ereignis.preventDefault()
    for (const eintrag of eintraege) anhangSetzen(eintrag.getAsFile())
  }

  /* The three routes a doc folder file is fetched from (app/docfolder.py);
     "alle" is the listing beside them, not a file. A loose file of a chat's
     folder carries its path as the service writes it with `quote`: parts of
     letters, digits and `_.-~%`, and no part is `.` or `..`, written plain
     or as `%2e`, nor holds an encoded slash — the service refuses those
     too, and so does the window. */
  const FOLDER_FILE =
    /^\/(?:agentendock\/(?!alle$)[\w-]+|documents\/[\w-]+\/file|chat-files\/[\w-]+\/(?:(?!(?:\.|%2[eE]){1,2}(?:\/|$))(?![\w.~%-]*%2[fF])[\w.~%-]+\/)*(?!(?:\.|%2[eE]){1,2}$)(?![\w.~%-]*%2[fF])[\w.~%-]+)$/

  async function fallenlassen(ereignis) {
    ereignis.preventDefault()
    /* A page lies over the chat — Models, Catalogue or the settings — or
       the picture studio stands in its place; a file let go there is not
       meant for the conversation nobody can see under it. In the studio it
       goes where it was laid: the drawing surface, a picture plaque. */
    if (eineSeiteOffen() || studioSichtbar()) return
    /* A file dragged out of the doc folder (DocFolder.svelte): the payload
       carries the path it is fetched from, its name and type, and the
       service hands over the file itself. From there it is an attachment
       like any other — the field does not need to know where it came from.
       A drop that cannot be read attaches nothing and says nothing.

       Only a path of the folder's three file routes is fetched: the payload
       is text any drag source could write, and the fetch carries the
       session key. */
    const fromFolder = ereignis.dataTransfer?.getData('application/x-exe-docfolder')
    if (fromFolder) {
      let entry
      try {
        entry = JSON.parse(fromFolder)
      } catch {
        return
      }
      if (!FOLDER_FILE.test(String(entry?.path ?? ''))) return
      let blob
      try {
        blob = await api.docFolderBlob(entry.path)
      } catch {
        return
      }
      const file = new File([blob], entry.name || 'Datei', {
        type: entry.type || blob.type,
      })
      if (istDokument(file)) dokumentSetzen(file)
      else anhangSetzen(file)
      return
    }
    /* A picture dragged off the picture wall (ModulBilder). Only the name
       travels — the folder is the truth and the route hands the bytes over,
       so nothing here has to carry a copy of a file the wall already has. */
    const ausBildwand = ereignis.dataTransfer?.getData('application/x-exe-bild')
    if (ausBildwand) {
      let blob
      try {
        blob = await api.bildBlob(ausBildwand)
      } catch {
        return
      }
      anhangSetzen(new File([blob], ausBildwand, { type: blob.type }))
      return
    }
    // EVERY dropped file, not just the first — the switch point per file:
    // the endings DOKUMENT_ENDUNGEN lists are documents, everything else
    // tries the image path.
    for (const datei of [...(ereignis.dataTransfer?.files || [])]) {
      if (istDokument(datei)) dokumentSetzen(datei)
      else anhangSetzen(datei)
    }
  }

  /* The field grows with the text. Reset to 'auto' first, otherwise
     scrollHeight only knows the previous state and the field never
     shrinks again on deletion. How tall it may grow for its own text and
     for the mirror comes from lib/dictationMirror.js. */
  /* The tallest the field has been in this dictation, in pixels; zero while
     no mirror stands. While one does, the field only grows (`floorHeight`
     in fieldSize): the grey end of a reading changes its length with every
     pass, and a field that shrinks and grows with it makes the history
     above jump up and down. */
  let diktatHoehe = 0

  function hoeheAnpassen() {
    if (!feld) return
    feld.style.height = 'auto'
    /* An empty field is one line, whatever its width: a placeholder that
       wraps in a narrow field counts towards `scrollHeight` and would make
       the empty field as tall as its wrapped words. Measured without it. */
    const platzhalter = feld.placeholder
    if (!feld.value) feld.placeholder = ''
    /* While dictating, the words on screen are the mirror's, not the
       field's own — the field is as tall as whichever of the two needs.
       The mirror takes the field's width and lettering first, or its height
       is measured at a width it does not have. */
    spiegelAusrichten()
    if (spiegel) spiegel.style.height = 'auto'
    const groesse = fieldSize({
      fieldHeight: feld.scrollHeight,
      mirrorHeight: spiegel?.scrollHeight,
      windowHeight: window.innerHeight,
      floorHeight: spiegel ? diktatHoehe : 0,
    })
    feld.placeholder = platzhalter
    diktatHoehe = spiegel ? parseInt(groesse.height, 10) : 0
    feld.style.height = groesse.height
    feld.style.overflowY = groesse.overflowY
    spiegelAusrichten()
  }

  /* The width of the field changes without the window changing: a column
     gives way, the sidebar folds. The height is measured again then — left
     as measured in a moment the field was narrow, an empty field would stay
     tall, and a text taller than it needs to be. Only a change of width
     counts: the field's own height changing is no reason to measure. */
  $effect(() => {
    if (!feld || typeof ResizeObserver === 'undefined') return
    let breite = feld.clientWidth
    const beobachter = new ResizeObserver(() => {
      if (feld.clientWidth === breite) return
      breite = feld.clientWidth
      hoeheAnpassen()
    })
    beobachter.observe(feld)
    return () => beobachter.disconnect()
  })

  $effect(() => {
    text
    hoeheAnpassen()
    /* Re-measure once the run-up is through: during the ride,
       scrollHeight delivers half-finished values, and the send arrow
       centers on the wrong height — only the first keystroke set it
       straight. This is rule 3.12 (never animate paddings along) from
       the other side: don't animate along AND measure once more after
       the ride. The bug had thus shown up three times. */
    const nachlauf = setTimeout(hoeheAnpassen, 850)
    return () => clearTimeout(nachlauf)
  })

  function taste(ereignis) {
    /* While a dictation runs, the field shows the mirror's words, not its
       own: Enter would send the draft underneath without them. It waits
       for the stop, like every other key does on a read-only field. */
    if (spiegelTeile !== null && ereignis.key === 'Enter') {
      ereignis.preventDefault()
      return
    }
    /* While the list is open the arrow keys and Enter belong to it. Escape
       gets out without clearing what was typed — the slash may well have
       been meant. */
    if (skillOffen) {
      if (ereignis.key === 'ArrowDown') {
        ereignis.preventDefault()
        skillDran = Math.min(skillDran + 1, skillTreffer.length - 1)
        return
      }
      if (ereignis.key === 'ArrowUp') {
        ereignis.preventDefault()
        skillDran = Math.max(skillDran - 1, 0)
        return
      }
      if (ereignis.key === 'Enter' || ereignis.key === 'Tab') {
        ereignis.preventDefault()
        skillWaehlen(skillTreffer[skillDran])
        return
      }
      if (ereignis.key === 'Escape') {
        ereignis.preventDefault()
        text += ' '
        return
      }
    }
    if (ereignis.key === 'Enter' && !ereignis.shiftKey) {
      ereignis.preventDefault()
      absenden()
    }
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
    /* A run with no chat behind it: the chat was left with ⌘N or the "+"
       button while an answer was still going. Queueing here would file the
       message under no conversation at all — it would then be sent by
       nobody and shown in every new chat. The old refusal is the right
       answer in that corner, and the text stays in the field. */
    if (laeuftIrgendwo() && !chatBeimStart) {
      melde(t('eingabe.laeuft_schon'))
      return
    }
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

  export function fokus() {
    feld?.focus()
  }

  /* What a send took out of the bar, kept under the send's id until the send
     is over — whoever sends (the bar itself, or the queue handing on a
     message it held) hands the entries in, and `zurueckgeben` finds them by
     that id. Returns the way to let go of them again. */
  export function keep(messageId, kept) {
    zurueckbehalten.set(messageId, kept)
    return () => zurueckbehalten.delete(messageId)
  }

  /* A send that did not reach the service — its chat was taken, an answer
     the service started by itself was going (App.svelte, `belegt`), or it
     ended before the request (no model, a picture that would not upload):
     the words AND what was attached to them come back, so nothing typed and
     nothing picked is lost and nothing stands twice. The words only into an
     empty field; whatever was typed since stays. */
  export function zurueckgeben(inhalt, chat = entwurfChat, messageId = null) {
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
      const bereich = diktatBereich
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
  export function transcribing() {
    return transcriptionAbort !== null
  }

  export function cancelTranscription() {
    transcriptionAbort?.abort()
  }
  /* --- The text while dictating --------------------------------------------

     The speech model reads only a finished recording, so the recording is
     read again about once a second — VoiceInk's interval — and every
     reading is compared with the ones before (lib/diktatabgleich.js): a
     word three readings agree on stands settled, the rest grey behind it.
     Only while something is said: a second of silence brings no new words,
     and a reading of it would only cost the speech server time. The field
     itself stays as it was until the stop; what is shown in between is a
     mirror laid over it, so nothing half-heard ever lands in a draft. */
  const NACHLESEN_MS = 1000
  // What the mirror shows: the field's own text around the spot the words
  // go, the settled words, the grey rest. Null while nobody dictates.
  /* The one value that says a mirror stands over the field: it is what the
     markup draws, and it is what locks the field and makes its own letters
     transparent. Two values here would leave a visible, untypeable field
     behind the moment they ever disagreed. */
  let zwischen = $state(null)
  let spiegel = $state(null)
  let mitlesen = null
  // The same, with the word gaps in place, ready to be laid over the field.
  const spiegelTeile = $derived(zwischen ? mirrorParts(zwischen) : null)

  function mitlesenBeginnen() {
    const imFeld = feld && document.activeElement === feld
    const von = imFeld ? feld.selectionStart : text.length
    const bis = imFeld ? feld.selectionEnd : text.length
    const anfang = startMirror(text, von, bis)
    const m = {
      ab: 0,
      vorher: [],
      stand: neuerStand(),
      liest: false,
      gehoert: false,
      stilleLesungen: 0,
      takt: null,
    }
    m.takt = setInterval(() => mitlesenRunde(m), NACHLESEN_MS)
    mitlesen = m
    zwischen = anfang.mirror
    diktatBereich = anfang.range
  }

  // Where the dictation goes: the field's text when it began, and the span
  // it replaces. Kept until the last pass has put the words in.
  let diktatBereich = null

  /* Ends the readings. The mirror, and the place the words go, stay until
     the last pass has answered. */
  function mitlesenBeenden() {
    const m = mitlesen
    mitlesen = null
    if (m) clearInterval(m.takt)
  }

  /* The mirror down, and the place it was holding with it. */
  function zwischenWeg() {
    zwischen = null
    diktatBereich = null
  }

  /* The rule lives in lib/dictationMirror.js; the effect only carries it
     out — `untrack` because the function reads what it writes. */
  $effect(() => {
    const jetzt = text
    untrack(() => {
      const bewegt = mirrorAfterFieldChange(zwischen, diktatBereich, jetzt)
      if (!bewegt) return
      zwischen = bewegt.mirror
      diktatBereich = bewegt.range
    })
  })

  function mitlesenPegel(pegel) {
    if (mitlesen && pegel >= SPRACHPEGEL) mitlesen.gehoert = true
  }

  async function mitlesenRunde(m) {
    if (mitlesen !== m || !lesenFaellig({ ...m, offen: offen(m.stand) })) return
    const stueck = aufnahmeZwischenstand(m.ab)
    if (!stueck) return
    m.stilleLesungen = m.gehoert ? 0 : m.stilleLesungen + 1
    m.gehoert = false
    m.liest = true
    try {
      const antwort = await api.spracheTranskribieren(stueck.blob, { bereinigen: false })
      if (mitlesen !== m) return
      const ergebnis = abgleichen(m.stand, antwort?.text)
      m.stand = ergebnis.stand
      if (abgeschlossen(m.stand)) {
        // Nothing left unsettled: the next reading starts behind this one.
        m.vorher.push(ergebnis.fest)
        m.stand = neuerStand()
        m.ab = stueck.bis
      }
      const fest = [...m.vorher, ...m.stand.fest].join(' ')
      zwischen = mirrorReading(zwischen, fest, ergebnis.unsicher)
    } catch {
      /* A reading that failed shows nothing new; the pass after the stop
         decides what lands in the field, and it says so if it fails too. */
    } finally {
      m.liest = false
    }
  }

  /* The newest words are at the bottom, and the field underneath has
     nothing of its own to scroll to — so the mirror keeps its end in view
     by itself once it is taller than the field may grow. */
  function spiegelRollen() {
    if (spiegel) spiegel.scrollTop = spiegel.scrollHeight
  }

  /* The mirror takes the field's own box and lettering, read off the field
     itself: its padding differs between the centred start and the docked
     bar, and a second copy of those numbers here would drift from them. */
  const SPIEGEL_FORM = [
    'boxSizing', 'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft',
    'fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'letterSpacing', 'wordSpacing',
  ]
  function spiegelAusrichten() {
    if (!spiegel || !feld) return
    const form = getComputedStyle(feld)
    for (const name of SPIEGEL_FORM) spiegel.style[name] = form[name]
    spiegel.style.top = feld.offsetTop + 'px'
    spiegel.style.left = feld.offsetLeft + 'px'
    spiegel.style.width = feld.offsetWidth + 'px'
    spiegel.style.height = feld.offsetHeight + 'px'
    spiegelRollen()
  }
  $effect(() => {
    zwischen
    spiegel
    queueMicrotask(hoeheAnpassen)
  })

  async function mikroSchalten() {
    if (holtText) return
    if (aufnahme.laeuft) {
      await diktatHolen(aufnahmeStoppen())
      return
    }
    /* Asked BEFORE the microphone is: a recording nobody can transcribe is
       four minutes of somebody's breath and a refusal at the end of it. The
       button stays visible either way — we hide nothing that can be shown —
       and what it does instead is say why. */
    let stand = null
    try {
      stand = await api.spracheAuskunft()
    } catch {
      stand = null
    }
    if (!stand?.laeuft) {
      melde(t('sprache.server_aus'))
      return
    }
    // A text still being read aloud would talk straight into the dictation.
    vorlesungStoppen()
    try {
      await aufnahmeStarten(diktatHolen, mitlesenPegel)
      // A second press while the permission dialogue still stood returns
      // here without a recording of its own: only the start that actually
      // opened the microphone begins the readings, and only once.
      if (aufnahme.laeuft && !mitlesen) mitlesenBeginnen()
    } catch (fehler) {
      melde(t(fehlerschluessel(fehler)), 'fehler')
    }
  }

  /* The shell's dictation shortcut, when there is a shell. It does exactly
     what a click on the button does. Missing (a plain browser on a dev
     server) it is simply not there, and nothing goes wrong. */
  $effect(() => {
    window.exeHuelle?.aufDiktat(() => mikroSchalten())
  })

  /* The assignable microphone key, while this window is in front: it does
     what a click on the button does (`mikroKlick`, conversation included). Cmd + Option as installed, pressed and
     let go with no other key between (lib/microphoneKey.js); the settings'
     key field takes the presses for itself while it records a new one.
     A window that loses focus never sees the keyups of what was held, so
     the recogniser forgets them then. */
  $effect(() => {
    untrack(() => diktatStandLaden())
    // The layout can be switched while the window stands open, and a key
    // that was free can then write a character the program has a shortcut
    // on ("]" on a US keyboard writes "+", which is Zoom In on a German
    // one): the recogniser asks the one holder for it at every press
    // (lib/keyboardLayout.svelte.js, read again at every focus of the
    // window), so the program's shortcut wins and the microphone key does
    // nothing.
    const listener = recogniser(diktat.microphone_key || DEFAULT_KEY, () => layout.map, system)
    // Not while a page covers the bar: the button cannot be reached then,
    // and a recording nobody sees would run on behind it.
    const down = (event) => {
      if (!listener.down(event) || eineSeiteOffen()) return
      // A key with its modifiers has a default of its own in a text field
      // or the browser (Control + K deletes to the line end); the press is
      // the microphone's alone.
      event.preventDefault()
      mikroKlick()
    }
    const up = (event) => {
      if (listener.up(event) && !eineSeiteOffen()) mikroKlick()
    }
    const forget = () => listener.reset()
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    window.addEventListener('blur', forget)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
      window.removeEventListener('blur', forget)
    }
  })

  /* "Read aloud" in the shell's right-click menu, over marked text. The
     menu entry carries the catalogue's word for it, handed over here
     because the shell has no catalogue of its own; the listener is set
     once, the word again whenever the language changes. */
  $effect(() => window.exeHuelle?.aufVorlesen?.((markiert) => textVorlesen(markiert)))
  /* No entry while the microphone is open or a conversation starts or
     runs: a voice reading then would be heard as the speaker. An empty
     word takes the entry off the menu, rather than leaving one there that
     would do nothing. */
  $effect(() => {
    const frei = !aufnahme.laeuft && !gespraechAn && !gespraechStartet
    window.exeHuelle?.vorlesenBeschriftung?.(frei ? t('sprache.vorlesen') : '')
  })

  /* --- Conversation --------------------------------------------------------

     A free conversation: hold the microphone button for a second to start
     or end one; inside it, a sentence goes out on its own once the speaker
     falls silent, the answer is read aloud, and it listens again — a click
     interrupts whichever of the three is happening.

     Silence detection is a small formula, scaled
     to the 16-bit range `aufnahme.svelte.js` already reports blocks in: a
     level of 200 counts as speech (measured as a block's RMS, not its
     peak), the pause under it (3.0 seconds as shipped, the user's own
     number in the speech server window) — once at least 0.3 seconds of
     speech has actually happened — ends the sentence, and 15 seconds with less than
     0.3 seconds of speech ends the round; three such rounds in a row end
     the conversation itself. */
  const GESPRAECH_MIN_SPRACH_MS = 300
  const GESPRAECH_RUNDE_STILLE_MS = 15000
  const GESPRAECH_RUNDEN_ENDE = 3

  let gespraechAn = $state(false)
  /* 'hoert' | 'denkt' | 'spricht' — only read while `gespraechAn` is true. */
  let gespraechZustand = $state('hoert')

  /* What the voice is doing, for the line that takes the left of the row:
     a dictation, its text being fetched, or a conversation's own state.
     `null` while the voice is not in use — then the left group shows. */
  const lineState = $derived(
    gespraechAn ? gespraechZustand : holtText ? 'holt' : aufnahme.laeuft ? 'diktat' : null,
  )

  // Plain closures, not `$state`: silence timing runs off the worklet's own
  // callback (see aufnahme.svelte.js), not off Svelte's render loop, and
  // reacting to every sample as reactive state would only add a scheduling
  // delay the timing cannot afford.
  let vadSprachMs = 0
  let vadStilleMs = 0
  let vadLetzteZeit = 0
  let vadRundenUhr = null
  let vadFehlrunden = 0
  // Set right before `abbrechen()` is asked to stop a running answer, so the
  // `senden()` this function is still awaiting knows not to read a half
  // answer aloud once the abort resolves it.
  let gespraechAbbruch = false
  let gespraechAudioEl = null
  /* The `await new Promise(...)` inside `stueckAbspielen` settles this
     way on its own once the clip ends — `.pause()` alone fires neither
     `onended` nor `onerror`, so an interrupt has to call this resolver by
     hand or that await (and the blob URL it still holds) never lets go. */
  let gespraechAudioFertig = null

  function gespraechAudioStoppen() {
    gespraechAudioEl?.pause()
    gespraechAudioFertig?.()
    gespraechAudioEl = null
    gespraechAudioFertig = null
  }
  /* Held from the first line of `gespraechUmschalten` until the conversation
     is either running or the check that failed has returned — the same
     door `aufnahme.svelte.js`'s own `startet` shuts on the way in, for the
     same reason: `api.spracheAuskunft()` and `diktatStandLaden()` both
     await, and a second hold landing in that stretch would pass every
     guard below (`gespraechAn` is still false) and start a second,
     overlapping recording. */
  // State, not a plain flag: the "Read aloud" entry above is taken off
  // the menu while a conversation is still starting, not only once it runs.
  let gespraechStartet = $state(false)
  /* The chat the running conversation belongs to — see the chat-switch
     guard below. */
  let gespraechChat = null
  /* True only while the conversation's own first sentence is being sent
     from an empty page — the one moment a new chat id is its own. */
  let gespraechLegtChatAn = false
  /* When a click last cut the voice off mid-answer, on the monotonic clock
     (0 = not since the last conversation turn went out). The next turn sent within
     UNTERBRECHUNG_GILT_MS tells the model its reply was not heard to the
     end; a later one no longer does, the moment has passed. */
  let gespraechUnterbrochenUm = 0
  const UNTERBRECHUNG_GILT_MS = 120_000

  async function gespraechUmschalten() {
    if (gespraechAn) {
      gespraechBeenden()
      return
    }
    if (aufnahme.laeuft || holtText || gespraechStartet) return
    // A marked text still being read aloud would be heard as the first
    // sentence of the conversation.
    vorlesungStoppen()
    gespraechStartet = true
    try {
      let stand = null
      try {
        stand = await api.spracheAuskunft()
      } catch {
        stand = null
      }
      if (!stand?.laeuft) {
        melde(t('sprache.server_aus'))
        return
      }
      await diktatStandLaden()
      if (!diktat.stimme) melde(t('sprache.gespraech_keine_stimme'))
      gespraechChat = zustand.aktiverChat
      gespraechAn = true
      vadFehlrunden = 0
      if (!(await gespraechMikroOeffnen())) return
      voiceKeepStart()
      await gespraechZuhoeren()
    } finally {
      gespraechStartet = false
    }
  }

  /* A spoken sentence that cannot be sent goes into the field, behind
     whatever already stands there. */
  function keepSentenceInField(sentence) {
    text = text.trim() ? `${text.trimEnd()} ${sentence}` : sentence
  }

  /* The voice stays loaded on the service while the conversation lasts: it is
     announced when the conversation begins and again every few seconds (the
     service lets go of it when the announcements stop, so a page that went
     away leaves nothing loaded), and given back when the conversation ends.
     Whether it is kept at all is the service's answer to the first call. */
  const VOICE_HOLD_MS = 10_000
  let voiceHoldTimer = null
  function voiceKeepStart() {
    voiceKeepStop(false)
    const announce = () => { api.voiceHold().catch(() => {}) }
    announce()
    voiceHoldTimer = setInterval(announce, VOICE_HOLD_MS)
  }
  function voiceKeepStop(release = true) {
    if (!voiceHoldTimer) return
    clearInterval(voiceHoldTimer)
    voiceHoldTimer = null
    if (release) api.voiceRelease().catch(() => {})
  }
  $effect(() => {
    const leave = () => {
      voiceKeepStop()
      if (gespraechAn) aufnahmeSchliessen()
    }
    window.addEventListener('pagehide', leave)
    return () => {
      window.removeEventListener('pagehide', leave)
      leave()
    }
  })

  function gespraechBeenden() {
    gespraechAn = false
    gespraechUnterbrochenUm = 0
    // The reading first: a sentence still being made is called off before
    // the voice is given back, or it would arrive at a service that no
    // longer holds the voice and be spoken by a second program.
    vorlesungStoppen()
    voiceKeepStop()
    vadRundenUhrStoppen()
    // Frees the microphone the conversation held open, and drops a round
    // that was still listening on it.
    aufnahmeSchliessen()
  }

  // A chat switch mid-conversation would otherwise keep listening for one
  // chat and sending into whichever is on screen next — the same hazard a
  // typed send already guards against, here ended outright rather than
  // carried over: a conversation is a mode of ONE chat, not a draft that
  // waits. Only the chat is tracked: read outside `untrack`, `gespraechAn`
  // itself became a dependency, so switching the conversation on re-ran
  // this effect and switched it straight off again.
  //
  // `gespraechChat` is the chat the conversation belongs to. A conversation
  // begun in an empty page has none yet: its first sentence creates the
  // chat, and that is the conversation getting its chat, not a switch away
  // from it. So a first id is adopted only while that sentence is being
  // sent; any other change — a chat picked from the list — ends it.
  $effect(() => {
    const chat = zustand.aktiverChat
    untrack(() => {
      // Marked text read aloud belongs to the chat it was marked in.
      stopMarkedReading()
      if (!gespraechAn) return
      if (gespraechChat == null && chat != null && gespraechLegtChatAn) {
        gespraechChat = chat
        return
      }
      if (chat !== gespraechChat) gespraechBeenden()
    })
  })

  /* The conversation's microphone: opened once, before the voice is
     announced, and held open through every round until the conversation
     ends — a round only starts and stops collecting. Opening again is a
     no-op while it is open, and brings the device back if it went away.
     False when the conversation did not get its microphone or ended while
     it was opening. */
  async function gespraechMikroOeffnen() {
    try {
      await aufnahmeOeffnen()
    } catch (fehler) {
      melde(t(fehlerschluessel(fehler)), 'fehler')
      gespraechBeenden()
      return false
    }
    // Ended while the microphone was still opening (a chat switch, the
    // hold): `gespraechBeenden` found nothing open to free, so what has
    // just come up would be left without an owner.
    if (!gespraechAn) {
      aufnahmeSchliessen()
      return false
    }
    return true
  }

  async function gespraechZuhoeren() {
    if (!gespraechAn) return
    gespraechZustand = 'hoert'
    vadSprachMs = 0
    vadStilleMs = 0
    vadLetzteZeit = performance.now()
    vadRundenUhrStoppen()
    if (!(await gespraechMikroOeffnen())) return
    try {
      await aufnahmeStarten(gespraechSatzFertig, gespraechPegel)
    } catch (fehler) {
      melde(t(fehlerschluessel(fehler)), 'fehler')
      gespraechBeenden()
      return
    }
    if (!gespraechAn) {
      aufnahmeSchliessen()
      return
    }
    // The round's own clock: 15 seconds with too little speech end it, also
    // when the microphone delivers nothing at all.
    vadRundenUhr = setTimeout(gespraechRundeAblaufen, GESPRAECH_RUNDE_STILLE_MS)
  }

  function vadRundenUhrStoppen() {
    clearTimeout(vadRundenUhr)
    vadRundenUhr = null
  }

  function gespraechRundeAblaufen() {
    vadRundenUhr = null
    if (!gespraechAn || gespraechZustand !== 'hoert' || !aufnahme.laeuft) return
    if (vadSprachMs >= GESPRAECH_MIN_SPRACH_MS) return
    aufnahmeAbbrechen()
    gespraechRundeOhneSatz()
  }

  function gespraechPegel(pegel) {
    if (!gespraechAn || gespraechZustand !== 'hoert') return
    const jetzt = performance.now()
    const dt = jetzt - vadLetzteZeit
    vadLetzteZeit = jetzt
    if (pegel >= SPRACHPEGEL) {
      vadSprachMs += dt
      vadStilleMs = 0
    } else {
      vadStilleMs += dt
    }
    if (vadSprachMs >= GESPRAECH_MIN_SPRACH_MS && pauseElapsed(vadStilleMs, diktat.conversation_pause_seconds)) {
      gespraechSatzFertig(aufnahmeStoppen())
      return
    }
  }

  async function gespraechRundeOhneSatz() {
    if (!gespraechAn) return
    vadFehlrunden += 1
    if (vadFehlrunden >= GESPRAECH_RUNDEN_ENDE) {
      melde(t('sprache.gespraech_drei_runden'))
      gespraechBeenden()
      return
    }
    await gespraechZuhoeren()
  }

  async function gespraechSatzFertig(blob) {
    vadRundenUhrStoppen()
    if (!gespraechAn) return
    if (!blob) {
      await gespraechRundeOhneSatz()
      return
    }
    gespraechZustand = 'denkt'
    // Reset here, not only right before sending: a click while the sentence
    // is still being transcribed is also "my turn", and has to be seen below.
    gespraechAbbruch = false
    let text = ''
    try {
      const antwort = await api.spracheTranskribieren(blob)
      text = (antwort?.text || '').trim()
    } catch (fehler) {
      if (gespraechAbbruch) return
      melde(String(fehler.message || fehler), 'fehler')
      await gespraechZuhoeren()
      return
    }
    // The click already listens again; this sentence is dropped.
    if (!gespraechAn || gespraechAbbruch) return
    if (!text) {
      await gespraechRundeOhneSatz()
      return
    }
    vadFehlrunden = 0
    /* The chat's model is switched off: the sentence would go nowhere. The
       conversation ends and the words wait in the field, like typed ones. */
    if (chosenModelOff()) {
      gespraechBeenden()
      keepSentenceInField(text)
      return
    }
    // Reading starts with the answer, not after it: the first finished
    // sentence speaks while the model is still writing the rest.
    const v = vorlesungBeginnen()
    const pumpe = v ? vorlesungPumpe(v) : null
    gespraechLegtChatAn = gespraechChat == null
    const unterbrochen = gespraechUnterbrochenUm > 0
      && performance.now() - gespraechUnterbrochenUm < UNTERBRECHUNG_GILT_MS
    gespraechUnterbrochenUm = 0
    let gesendet = false
    try {
      await senden(text, null, null, null, null, unterbrochen ? { unterbrochen: true } : true)
      gesendet = true
    } finally {
      gespraechLegtChatAn = false
      if (!gesendet) vorlesungStoppen()
    }
    if (!gespraechAn || gespraechAbbruch) return
    if (v) {
      vorlesungFuettern(v, antwortVon(v), true)
      await pumpe
      if (vorlesung === v) vorlesung = null
      // An interrupt already listens again on its own.
      if (!gespraechAn || gespraechAbbruch) return
    }
    await gespraechZuhoeren()
  }

  /* --- Reading an answer aloud, piece by piece ------------------------------

     The answer is turned into a spoken script and cut into sentences while
     it is still being written (lib/sprechtext.js). The voice is one run of
     `llama-tts` per piece; while one piece speaks, the next one is already
     being rendered, and never more than that one — two renders at once
     would only fight over the same machine. */

  // The reading of the current answer; null while nothing is read. Raw
  // state: only whether there is one is watched, not what is inside it.
  let vorlesung = $state.raw(null)

  function vorlesungBeginnen() {
    if (!(diktat.vorlesen ?? true) || !diktat.stimme) return null
    const v = {
      // The answer is the last assistant row after this many rows.
      ab: nachrichtenAnzeige().length,
      script: '',
      gelesen: 0,
      stuecke: [],
      textFertig: false,
      aus: false,
      rechnet: false,
      wecken: null,
      // Ends a sentence still being made when the reading is stopped.
      abort: new AbortController(),
    }
    vorlesung = v
    return v
  }

  function antwortVon(v) {
    const antwort = nachrichtenAnzeige().slice(v.ab).findLast((m) => m.role === 'assistant')
    return antwort?.content || ''
  }

  // Every change to the answer while it is written feeds the reading.
  $effect(() => {
    const v = vorlesung
    if (!v) return
    const text = antwortVon(v)
    untrack(() => vorlesungFuettern(v, text, false))
  })

  function vorlesungFuettern(v, text, fertig) {
    if (v.aus || v.textFertig) return
    const stand = neuAusrichten(v.script, v.gelesen, sprechtextPutzen(text))
    v.script = stand.script
    v.gelesen = stand.gelesen
    const { stuecke, bis } = stueckeSchneiden(stand.script, v.gelesen, fertig)
    v.gelesen = bis
    if (fertig) v.textFertig = true
    for (const s of stuecke) v.stuecke.push({ text: s, wav: null })
    stueckVorbereiten(v)
    v.wecken?.()
  }

  function stueckVorbereiten(v) {
    const kopf = v.stuecke[0]
    if (v.aus || !kopf || kopf.wav || v.rechnet) return
    v.rechnet = true
    kopf.wav = api.spracheSprechen(kopf.text, { signal: v.abort.signal }).finally(() => {
      v.rechnet = false
      stueckVorbereiten(v)
    })
    // Awaited by the pump when its turn comes; a reading stopped before
    // then must not leave the failure unhandled.
    kopf.wav.catch(() => {})
  }

  async function vorlesungPumpe(v) {
    while (!v.aus) {
      if (!v.stuecke.length) {
        if (v.textFertig) break
        // Nothing to say until the model writes the next sentence: the
        // ring shows thinking, not speaking, while the voice is silent.
        if (gespraechAn) gespraechZustand = 'denkt'
        await new Promise((weiter) => { v.wecken = weiter })
        v.wecken = null
        continue
      }
      const stueck = v.stuecke[0]
      stueckVorbereiten(v)
      let wav
      try {
        wav = await stueck.wav
      } catch (fehler) {
        if (!v.aus) melde(String(fehler.message || fehler), 'fehler')
        v.aus = true
        break
      }
      v.stuecke.shift()
      if (v.aus) break
      // The next piece renders while this one speaks.
      stueckVorbereiten(v)
      gespraechZustand = 'spricht'
      await stueckAbspielen(wav)
    }
  }

  async function stueckAbspielen(wav) {
    const url = URL.createObjectURL(wav)
    const audioEl = new Audio(url)
    gespraechAudioEl = audioEl
    /* Through the analyser the voice's loudness reaches the line; when the
       route cannot be built the clip plays on its own, as it always did. */
    const route = await attachPlayback(audioEl)
    if (gespraechAudioEl !== audioEl) {
      /* Stopped while the route was being built: nothing is played. */
      route?.()
      URL.revokeObjectURL(url)
      return
    }
    try {
      await new Promise((fertig) => {
        gespraechAudioFertig = fertig
        audioEl.onended = fertig
        audioEl.onerror = fertig
        audioEl.play().catch(fertig)
      })
    } finally {
      route?.()
      URL.revokeObjectURL(url)
      gespraechAudioEl = null
      gespraechAudioFertig = null
    }
  }

  function vorlesungStoppen() {
    const v = vorlesung
    vorlesung = null
    if (v) {
      v.aus = true
      v.stuecke = []
      v.abort.abort()
      v.wecken?.()
    }
    gespraechAudioStoppen()
  }

  /* Called from App.svelte's Escape handler once it has thrown away a
     running recording — while a conversation owns that recording (it is
     still 'hoert'), `aufnahme.laeuft` alone would otherwise stay false
     with nothing to set it right, and the short click's own guard in
     `mikroKlick` below then does nothing at all: the button would stay
     dead until the one-second hold ends the whole conversation. Listening
     again keeps the click alive; a conversation ends only through that
     hold. */
  export function gespraechAufnahmeAbgebrochen() {
    // A dictation thrown away takes its interim text with it.
    if (spiegelTeile) {
      mitlesenBeenden()
      zwischenWeg()
    }
    if (gespraechAn && gespraechZustand === 'hoert') gespraechZuhoeren()
  }

  /* Marked text, read by the same voice on the same way an answer in a
     conversation is: cleaned into a spoken script, cut into pieces, the
     next piece rendered while the one before speaks. Not while a
     conversation runs — it owns the voice and the microphone, and a second
     reading would talk over it and into its own ear. A reading already
     going is stopped for the new one. */
  function textVorlesen(markiert) {
    if (aufnahme.laeuft || gespraechAn || gespraechStartet) return
    if (!String(markiert ?? '').trim()) return
    vorlesungStoppen()
    const v = {
      ab: nachrichtenAnzeige().length,
      script: '',
      gelesen: 0,
      stuecke: [],
      textFertig: false,
      aus: false,
      rechnet: false,
      wecken: null,
      // Ends a sentence still being made when the reading is stopped.
      abort: new AbortController(),
    }
    // Fed whole and finished before it becomes the reading, so the effect
    // that feeds a conversation's answer finds nothing left to feed.
    v.marked = true
    vorlesungFuettern(v, markiert, true)
    vorlesung = v
    vorlesungPumpe(v).finally(() => {
      if (vorlesung === v) vorlesung = null
    })
  }

  /* Escape (App.svelte) and a chat switch stop a reading of marked text,
     and only that one: a conversation's voice keeps its own interrupts. */
  export function readingMarked() {
    return Boolean(vorlesung?.marked)
  }

  export function stopMarkedReading() {
    if (vorlesung?.marked) vorlesungStoppen()
  }

  /* The button's short click: dictation as always outside a conversation,
     one of three interrupts inside it — send the sentence now while it is
     still listening, abort the answer while it is thinking, silence the
     voice while it is speaking. All three then listen again; only the hold
     ends the conversation itself. */
  async function mikroKlick() {
    if (!gespraechAn) {
      await mikroSchalten()
      return
    }
    if (gespraechZustand === 'hoert') {
      if (!aufnahme.laeuft) return
      await gespraechSatzFertig(aufnahmeStoppen())
    } else if (gespraechZustand === 'denkt' || gespraechZustand === 'spricht') {
      // Thinking or speaking, a click means "my turn": the voice stops,
      // and an answer still being written is stopped with it — the voice
      // now speaks while the model writes, so silencing one without the
      // other would leave the answer running on unheard. The waiting
      // `gespraechSatzFertig` sees `gespraechAbbruch` and does not listen
      // a second time.
      const schreibtNoch = gespraechZustand === 'denkt' || (vorlesung && !vorlesung.textFertig)
      if (gespraechZustand === 'spricht') gespraechUnterbrochenUm = performance.now()
      gespraechAbbruch = true
      vorlesungStoppen()
      if (schreibtNoch) abbrechen?.()
      await gespraechZuhoeren()
    }
  }
</script>

<!-- Dragging is caught by the WHOLE window: whoever
     aims off-target should not get a new browser window with the image
     but the attachment — dragging in anywhere suffices, as one is used
     to. Not while a page lies over the chat or the picture studio stands
     in its place: there it attaches nothing. -->
<svelte:window
  onresize={hoeheAnpassen}
  onpointerdowncapture={closeMenuOutside}
  onkeydowncapture={closeMenuOnEscape}
  ondragover={(e) => e.preventDefault()}
  ondrop={fallenlassen}
/>

<div class="zone">
  <!-- The one card for what waits on the user. It is written here, where
       its answers leave from, and hangs itself over the whole chat column.
       Only in the chat it belongs to: a question travelling into a foreign
       conversation reads as that conversation asking. -->
  {#if cardStands}
    <QuestionBox
      kind={standing.kind}
      question={standing.question}
      position={standing.position}
      total={standing.total}
      {modelName}
      {answerTool}
      {answerAsk}
      onLater={later}
    />
  {/if}

  <!-- The slash list hangs off a zero-height anchor as wide as the bar,
     growing upward into the history. -->
  <div class="menueplatz">
    {#if skillOffen}
      <Skillliste eintraege={skillTreffer} dran={skillDran} waehlen={skillWaehlen} />
    {/if}
  </div>

  <input
    type="file"
    accept={acceptedFiles}
    bind:this={dateiwahl}
    multiple
    onchange={(e) => { filesChosen([...(e.currentTarget.files || [])]); e.currentTarget.value = '' }}
    hidden
  />

  <!-- The mask that ADDS a folder, opened from the folder chip's list. -->
  <Arbeitsordner />

  <div class="eingabe">
    <!-- The bar's drawing, its first layer: the field stands on top. -->
    {#if vektoren}
      <Vektorfeld art={vektoren} />
    {/if}
    <!-- What is attached stands above the text: pictures as small previews,
         documents as tiles with their name, each with its ✕. -->
    {#if anhaenge.length || dokumentAnhaenge.length}
      <div class="attachments">
        {#each anhaenge as anhang, index (anhang.url)}
          <span class="attachment picture">
            <button class="face" onclick={() => bildOeffnen(index)}
                    title={anhang.datei.name}
                    aria-label={`${t('nachricht.bild_vergroessern')} — ${anhang.datei.name}`}>
              <img src={anhang.url} alt="" />
            </button>
            <button class="remove" onclick={() => anhangEntfernen(index)}
                    aria-label={t('eingabe.anhang_entfernen')} title={t('eingabe.anhang_entfernen')}>
              <Hauszeichen zeichen="kreuz" groesse={9} strich={2.6} />
            </button>
          </span>
        {/each}
        {#each dokumentAnhaenge as dokument, index (dokument.id)}
          <span class="attachment document" class:loading={!dokument.dokument}>
            <button class="face" onclick={() => dokumentOeffnen(index)}
                    title={dokument.datei.name}
                    aria-label={`${t('eingabe.dokument_oeffnen')} — ${dokument.datei.name}`}>
              <Hauszeichen zeichen="dokument" groesse={16} />
              <span class="doc-name">{dokument.datei.name}</span>
            </button>
            <button class="remove" onclick={() => dokumentEntfernen(index)}
                    aria-label={t('eingabe.dokument_entfernen')} title={t('eingabe.dokument_entfernen')}>
              <Hauszeichen zeichen="kreuz" groesse={9} strich={2.6} />
            </button>
          </span>
        {/each}
      </div>
    {/if}

    <!-- The words while they are still being spoken, laid over the field
         in the field's own lettering: settled in the text colour, the
         unsettled end grey. The field underneath keeps its text and turns
         its letters transparent for as long as this stands. -->
    {#if spiegelTeile}
      <div class="diktat-spiegel" bind:this={spiegel} aria-hidden="true">{spiegelTeile.davor}{spiegelTeile.fest}<span class="diktat-unsicher">{spiegelTeile.unsicher}</span>{spiegelTeile.danach}</div>
    {/if}
    <textarea
      bind:this={feld}
      bind:value={text}
      class:diktiert={spiegelTeile}
      readonly={spiegelTeile !== null}
      rows="1"
      placeholder={gruss || t('eingabe.platzhalter')}
      onkeydown={taste}
      onpaste={einfuegen}
      aria-label={t('eingabe.nachricht')}
    ></textarea>

    <!-- One row under the text: plus, folders and mode on the left; the
         model with its lamps and ring, the thinking switch, the microphone
         and send on the right. -->
    <div class="bar-row" class:narrow class:tight bind:this={row}>
      <!-- The left group and, over the same room, the line that shows what the
           voice hears while it is in use. The group never leaves the layout —
           it only fades — so the row's height and its measuring stay as they
           are. -->
      <div class="links-platz" class:stimme={Boolean(lineState)}>
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div class="linkegruppe" inert={Boolean(lineState)} onkeydown={modeListEscape}>
        <div class="menu-anchor" data-bar-menu="plus">
          <button
            class="round plus"
            class:offen={openMenu === 'plus'}
            aria-expanded={openMenu === 'plus'}
            aria-label={t('eingabe.attach_files')}
            onclick={() => toggleMenu('plus', openMenu !== 'plus')}
          >
            <Hauszeichen zeichen="plus" groesse={15} strich={2.4} />
          </button>
          {#if openMenu === 'plus'}
            <div class="klappmenue" role="menu">
              <button
                role="menuitem"
                class:gesperrt={!acceptedFiles}
                onclick={() => {
                  if (!acceptedFiles) return
                  openMenu = ''
                  dateiwahl?.click()
                }}
              >
                <Hauszeichen zeichen="dokument_zeilen" groesse={16} />
                <span>
                  {t('eingabe.attach_files')}
                  <span class="menuehinweis">{filesHint}</span>
                </span>
              </button>
              <!-- The picture made HERE, on this machine: the entry opens
                   the picture studio. The icon is a status light: green as
                   soon as the local picture server can draw, blue and
                   pulsing while Image-Turbo runs. -->
              <button
                role="menuitem"
                onclick={() => {
                  openMenu = ''
                  studioOeffnen()
                }}
              >
                <span class="bildicon" class:pulst={turboAn} style:color={bildIconFarbe}>
                  <Hauszeichen zeichen="bild" groesse={16} />
                </span>
                <span>
                  {t('bild.titel')}
                  <span class="menuehinweis">{t('bild.hier_hinweis')}</span>
                </span>
              </button>
            </div>
          {/if}
        </div>

        <FolderChip open={openMenu === 'folder'} onToggle={(open) => toggleMenu('folder', open)} {narrow} />

        <Klappwahl
          optionen={modeOptions}
          wert={berechtigungsmodus.chat}
          aufWahl={(neu) => berechtigungsmodusSetzen('chat', neu)}
          beschriftung={t('berechtigungen.modus_beschriftung')}
          nachOben
          schliessen={Boolean(zustand.frage) || eineSeiteOffen()}
          klasse={narrow ? 'modus narrow' : 'modus'}
        >
          {#snippet zeichen(wert)}
            <Leuchtpunkt farbe={MODE_COLOUR[wert] ?? 'still'} groesse={10} atmet={wert === 'auto'} />
          {/snippet}
        </Klappwahl>

        <!-- A question pushed away with "later" waits here: the dot and who
             is asking, and a click brings the card back. -->
        {#if pushedAway.length}
          <div class="later-chips">
            {#each pushedAway as item (questionKey(item))}
              <button class="later-chip" title={t('chat.wartet_auf_dich')}
                      onclick={() => resume(item)}>
                <span class="waiting-dot" aria-hidden="true"></span>{item.kind === 'agent' ? item.question.agentName : modelName}
              </button>
            {/each}
          </div>
        {/if}
      </div>
      <VoiceLine zustand={lineState} />
      </div>

      <div class="rechts">
        <Modellwahl open={openMenu === 'model'} onToggle={(open) => toggleMenu('model', open)} {narrow} {tight}
                    bind:label={modelLabel} />

        <!-- How deeply the model thinks, right beside the microphone: the
             bulb with its stage dots (Denkschalter.svelte). -->
        <Denkschalter {denkprofil} denken={denkStufe} {denkenSetzen} />

        <!-- Dictation. Press, speak, press — the text lands in the field and
             is not sent; Enter sends, as always. -->
        <Mikrofonknopf
          nimmt={aufnahme.laeuft}
          holt={holtText}
          gespraech={gespraechAn}
          gespraechZustand={gespraechAn ? gespraechZustand : null}
          onschalten={mikroKlick}
          onhalten={gespraechUmschalten}
        />

        <!-- One button, two jobs: send while nothing runs — otherwise
             stop. In the same spot so the hand doesn't wander, and both
             can never stand there at once. Applies equally to image
             generation: if it runs, it gets stopped.
             With something in the field it stays the send button even
             during a run: the message then lines up in the queue. Whoever
             types and then reaches for the arrow means to send, not to
             abort — and an empty field is the unmistakable sign for stop. -->
        <button
          class="aktion"
          class:stoppt={stoppt}
          class:leer={!laeuftGerade && leer}
          onclick={() => (stoppt ? abbrechen() : absenden())}
          disabled={gesperrtDurchModell}
          title={stoppt
            ? t('eingabe.abbrechen_tipp')
            : gesperrtDurchModell ? t('fehler.modell_deaktiviert') : t('eingabe.senden')}
          aria-label={stoppt
            ? t('eingabe.abbrechen')
            : gesperrtDurchModell ? t('fehler.modell_deaktiviert') : t('eingabe.senden')}
        >
          <span class="ring"></span>
          <svg class="pfeil" width="15" height="15" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 19V5M5 12l7-7 7 7" />
          </svg>
          <span class="wuerfel"></span>
        </button>
      </div>
    </div>
  </div>
</div>

<style>
  .zone {
    flex: none;
    padding: 8px 0 22px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
  }
  /* One width for the bar and everything that hangs off it. */
  .menueplatz,
  .eingabe {
    width: min(720px, 78%);
    max-width: 100%;
    min-width: 0;
  }
  /* The slash list's anchor: invisible and costing no space — the negative
     margin swallows the zone's gap. */
  .menueplatz {
    position: relative;
    height: 0;
    margin-bottom: -8px;
  }

  /* The bar: a card lifted off the chat by a shadow, no frame — the
     surfaces do the separating. */
  .eingabe {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 10px 10px 8px 12px;
    border-radius: 9px;
    /* The look may give the bar a lighter, see-through ground of its own;
       without one it keeps the raised surface. */
    background: var(--kachel-eingabe, var(--bg-erhoben));
    box-shadow: 0 14px 34px -14px rgba(0, 0, 0, 0.55), 0 2px 6px -2px rgba(0, 0, 0, 0.25);
    /* A stacking context for the drawing's own level (the rule below). */
    isolation: isolate;
  }
  /* The field's content is not layered, so the bar lifts the drawing
     behind it: one step down, inside its own stacking context, the
     drawing lands between the ground and the field. */
  .eingabe :global(.vektorfeld) {
    z-index: -1;
  }
  textarea {
    width: 100%;
    max-width: 100%;
    border: none;
    outline: none;
    resize: none;
    background: none;
    color: var(--text);
    font: inherit;
    font-size: 14px;
    line-height: 20px;
    padding: 4px 2px;
    display: block;
    overflow-x: hidden;
    overflow-y: hidden;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  textarea::placeholder {
    color: var(--text-still);
  }
  /* While the mirror stands over it, the field's own letters would show
     through beside the mirror's — they go transparent, the caret with
     them, because nothing can be typed until the dictation is done. */
  textarea.diktiert,
  textarea.diktiert::placeholder {
    color: transparent;
    caret-color: transparent;
  }
  .diktat-spiegel {
    position: absolute;
    pointer-events: none;
    overflow: hidden;
    color: var(--text);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .diktat-unsicher {
    color: var(--text-still);
  }

  /* Attachments above the text: pictures square, documents as a tile with
     the name, the ✕ riding on the corner. */
  .attachments {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    padding: 4px 2px 2px;
  }
  .attachment {
    position: relative;
    height: 44px;
    border-radius: 9px;
    background: var(--bg-hoch);
    animation: enter 0.25s ease-out both;
  }
  @keyframes enter { from { opacity: 0; transform: scale(0.94); } }
  .attachment .face {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    height: 100%;
    padding: 0 12px 0 10px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
    font: 400 12.5px var(--schrift);
    cursor: pointer;
  }
  .attachment.picture { width: 44px; overflow: visible; }
  .attachment.picture .face { width: 44px; padding: 0; overflow: hidden; }
  .attachment.picture img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .attachment.loading { opacity: 0.55; }
  .doc-name { max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .remove {
    position: absolute;
    top: -6px;
    right: -6px;
    width: 18px;
    height: 18px;
    display: grid;
    place-items: center;
    padding: 0;
    border: none;
    border-radius: 50%;
    background: var(--text);
    color: var(--bg-erhoben);
    box-shadow: 0 0 0 2px var(--bg-erhoben);
    cursor: pointer;
  }

  /* The row under the text. It never wraps: when it runs out of room the
     words drop out instead (`narrow`). */
  .bar-row {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }
  .bar-row.narrow { gap: 4px; }
  /* Neither group shrinks: their widths stay what their content needs,
     which is what the narrow form is measured by. */
  .linkegruppe,
  .rechts {
    display: flex;
    align-items: center;
    gap: 4px;
    flex: none;
  }
  .bar-row.narrow .linkegruppe,
  .bar-row.narrow .rechts { gap: 2px; }
  /* Tighter still: the buttons touch, and the model picker drops its lamps
     (Modellwahl.svelte). */
  .bar-row.tight { gap: 2px; }
  .bar-row.tight .linkegruppe,
  .bar-row.tight .rechts { gap: 0; }
  .rechts { margin-left: auto; }
  /* The room left of the model picker. The group inside keeps its own width;
     the voice line fills what is left of it. The two never show together:
     going in, the group fades first (160 ms) and the line follows; coming
     back, the line leaves first and the group follows. The transition sits
     on the state that is being reached. */
  .links-platz {
    position: relative;
    flex: 1 1 auto;
    min-width: 0;
    align-self: stretch;
    display: flex;
    align-items: center;
  }
  .links-platz > .linkegruppe { transition: opacity 0.22s ease-out 0.16s; }
  .links-platz.stimme > .linkegruppe {
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.16s ease-in;
  }
  /* The page-wide rule for less motion cuts every transition to a hundredth
     of a millisecond with `!important`; the group's fade is the exception —
     it still fades, softly, instead of switching. */
  @media (prefers-reduced-motion: reduce) {
    .links-platz > .linkegruppe { transition-duration: 0.22s !important; }
    .links-platz.stimme > .linkegruppe { transition-duration: 0.16s !important; }
  }
  .menu-anchor { position: relative; flex: none; }

  .round {
    width: 30px;
    height: 30px;
    display: grid;
    place-items: center;
    flex: none;
    padding: 0;
    border: none;
    border-radius: 50%;
    background: transparent;
    color: var(--text-leise);
    cursor: pointer;
    transition: background 0.15s, color 0.15s, transform 0.22s cubic-bezier(0.2, 0.9, 0.3, 1);
  }
  .round.plus {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
  }
  .round:hover { color: var(--text); }
  .round.plus.offen { transform: rotate(45deg); color: var(--text); }

  /* The permission mode, in the row's chip shape. The list itself is
     Klappwahl's; only the button is dressed here. */
  .linkegruppe :global(.klappwahl .knopf.modus) {
    min-width: 0;
    height: 30px;
    gap: 6px;
    padding: 0 9px;
    border: none;
    background: transparent;
    color: var(--text-leise);
    font: 400 12.5px var(--schrift);
    transition: background 0.15s, color 0.15s;
  }
  .linkegruppe :global(.klappwahl .knopf.modus:hover),
  .linkegruppe :global(.klappwahl .knopf.modus.offen) {
    background: var(--bg-hoch);
    color: var(--text);
  }
  .linkegruppe :global(.klappwahl .knopf.modus.narrow .text),
  .linkegruppe :global(.klappwahl .knopf.modus.narrow .pfeil) {
    display: none;
  }

  /* The chips of the questions pushed away with "later" share the room one
     chip had: with several, each is shortened, the bar does not grow. */
  .later-chips {
    display: flex;
    gap: 4px;
    flex: 0 1 auto;
    min-width: 0;
    max-width: 160px;
  }
  /* A question pushed away with "later": the dot keeps waiting in yellow. */
  .later-chip {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    flex: 0 1 auto;
    min-width: 0;
    max-width: 160px;
    padding: 4px 9px 4px 7px;
    border: none;
    border-radius: 9px;
    background: var(--bg-hoch);
    color: var(--text-leise);
    font: 400 12px/16px var(--schrift);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    cursor: pointer;
    animation: enter 0.3s ease-out both;
  }
  .later-chip:hover { color: var(--text); }
  .waiting-dot {
    flex: none;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--gelb);
    animation: breathe 1.1s ease-in-out infinite;
  }
  @keyframes breathe { 50% { opacity: 0.4; } }

  /* The plus menu grows out of the plus, flush with its left edge. */
  .klappmenue {
    position: absolute;
    left: 0;
    bottom: calc(100% + 12px);
    min-width: 240px;
    padding: 5px;
    border-radius: 9px;
    background: var(--bg-erhoben);
    box-shadow: 0 0 0 1px var(--linie), 0 16px 36px -8px rgba(0, 0, 0, 0.5);
    transform-origin: bottom left;
    animation: rise 0.16s cubic-bezier(0.2, 0.9, 0.3, 1) both;
    z-index: 30;
  }
  @keyframes rise { from { opacity: 0; transform: translateY(6px) scale(0.98); } }
  .klappmenue button {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    min-height: 34px;
    padding: 5px 8px 5px 10px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
    font: 400 13px var(--schrift);
    text-align: left;
    cursor: pointer;
  }
  .klappmenue button:hover {
    background: var(--bg-hoch);
    color: var(--text);
  }
  .menuehinweis {
    display: block;
    font-size: 11.5px;
    color: var(--text-still);
  }
  .klappmenue button.gesperrt {
    opacity: 0.45;
    cursor: default;
  }
  .klappmenue button.gesperrt:hover {
    background: none;
  }
  .bildicon { display: inline-flex; }
  /* The picture icon pulses while Image-Turbo runs. */
  .bildicon.pulst {
    animation: bildpuls 1.5s ease-in-out infinite;
  }
  @keyframes bildpuls {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
  }

  .aktion {
    width: 30px;
    height: 30px;
    flex: none;
    border-radius: 50%;
    border: none;
    padding: 0;
    cursor: pointer;
    display: grid;
    place-items: center;
    position: relative;
    background: var(--text);
    color: var(--bg);
    transition: opacity 0.16s ease, transform 0.1s ease, background 0.16s;
  }
  .aktion:hover { opacity: 0.88; }
  .aktion:active { transform: scale(0.94); }
  /* Shut while the chat's model is switched off: drawn like the empty
     field's button, the one look the house has for "nothing to send". */
  .aktion.leer, .aktion:disabled {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text-still);
    cursor: default;
  }
  .aktion.leer:hover, .aktion:disabled:hover { opacity: 1; }
  .aktion:disabled:active { transform: none; }
  .pfeil, .wuerfel {
    transition: opacity 0.14s ease, transform 0.18s cubic-bezier(0.2, 0.9, 0.3, 1);
  }
  .wuerfel {
    position: absolute;
    width: 10px;
    height: 10px;
    border-radius: 9px;
    background: currentColor;
    opacity: 0;
    transform: scale(0.6);
  }
  .aktion.stoppt { background: none; color: var(--text-leise); }
  .aktion.stoppt:hover { color: var(--text); }
  .aktion.stoppt .pfeil { opacity: 0; transform: scale(0.6); }
  .aktion.stoppt .wuerfel { opacity: 1; transform: none; }
  .ring {
    position: absolute;
    inset: 0;
    border-radius: 50%;
    border: 1.5px solid var(--linie-stark);
    border-top-color: var(--blau);
    opacity: 0;
    transition: opacity 0.16s;
  }
  .aktion.stoppt .ring {
    opacity: 1;
    animation: dreht 1.4s linear infinite;
  }
  @keyframes dreht {
    to { transform: rotate(360deg); }
  }

  @media (max-width: 720px) {
    .menueplatz,
    .eingabe { width: 92%; }
  }
  @media (prefers-reduced-motion: reduce) {
    .klappmenue, .attachment, .later-chip, .waiting-dot, .bildicon.pulst { animation: none; }
    .round { transition: none; }
  }
</style>
