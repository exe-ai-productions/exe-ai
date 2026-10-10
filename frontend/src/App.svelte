<script>
  import { tick, untrack } from 'svelte'
  import { fly } from 'svelte/transition'
  import { backOut } from 'svelte/easing'
  import Seitenleiste from './teile/Seitenleiste.svelte'
  import { ordnerstandPruefen, sharedByModel } from './lib/arbeitsordner.svelte.js'
  import Seitengriff from './teile/Seitengriff.svelte'
  import Arbeitsleiste from './teile/Arbeitsleiste.svelte'
  import Erststart from './teile/Erststart.svelte'
  import Updatekarte from './teile/Updatekarte.svelte'
  import Begruessungsecke from './teile/Begruessungsecke.svelte'
  import Nachricht from './teile/Nachricht.svelte'
  import Eingabeleiste from './teile/Eingabeleiste.svelte'
  import Wartezeile from './teile/Wartezeile.svelte'
  import { stoppuhr } from './lib/dauer.js'
  import { takt, taktHalten } from './lib/sekundentakt.svelte.js'
  import { taetigkeitSetzen } from './lib/taetigkeit.js'
  import SystemPrompt from './teile/SystemPrompt.svelte'
  import ModelleSeite from './teile/ModelleSeite.svelte'
  import Katalog from './teile/Katalog.svelte'
  import Frage from './teile/Frage.svelte'
  import Layoutmodus from './teile/Layoutmodus.svelte'
  import Protokollfenster from './teile/Protokollfenster.svelte'
  import Bildschau from './teile/Bildschau.svelte'
  import AuftragBestaetigen from './teile/AuftragBestaetigen.svelte'
  import Meldungen from './teile/Meldungen.svelte'
  import ImageStudio from './teile/ImageStudio.svelte'
  import { studioSichtbar } from './lib/studio.svelte.js'
  import Wortmarke from './teile/Wortmarke.svelte'
  import Vektorfeld from './teile/Vektorfeld.svelte'
  import AuftragStarten from './teile/AuftragStarten.svelte'
  import Agentenmarke from './teile/Agentenmarke.svelte'
  import Wasserzeichen from './teile/Wasserzeichen.svelte'
  /* Escape has to know about a running dictation — see the key handler. */
  import { aufnahme, abbrechen as aufnahmeAbbrechen } from './lib/aufnahme.svelte.js'
  import Bildwarteschlange from './teile/Bildwarteschlange.svelte'
  import Flashpunkt from './teile/Flashpunkt.svelte'
  import Serverpunkt from './teile/Serverpunkt.svelte'
  import Speicherpille from './teile/Speicherpille.svelte'
  import { api, antwortStrom, zusehenStrom } from './lib/api.js'
  import { t, texte } from './lib/texte.svelte.js'

  import {
    zustand, melde, aktualisiereMeldung, modelleLaden, featuresLaden, chatsLaden, aktuellerChat, neuerChat,
    benutzerfrageBeantworten, frageBeantworten, seitenleisteSchalten, sucheZeigen,
    chatFertigMerken, chatFertigGesehen, menueFensterOeffnen, laufVon,
    darstellungAnwenden, seitenleisteAnwenden, modellAnwenden, seitenSchliessen, seiteZeigen, eineSeiteOffen,
    rahmenNeuZeichnen, geraet,
  } from './lib/zustand.svelte.js'
  import { protokollOffen } from './lib/protokollfenster.svelte.js'
  import { deferQuestion, isDeferred, standingQuestion } from './lib/questionbox.svelte.js'
  import { VORGABE_MODUS, anzeigeLaden, modusSpeichern } from './lib/anzeige.js'
  import { chatanzeige, scrollstelleSpeichern } from './lib/chatanzeige.svelte.js'
  import { begruessung, begruessungLaden } from './lib/begruessung.svelte.js'
  import { updatesStart } from './lib/updates.svelte.js'
  import { verbinden as terminalVerbinden } from './lib/terminalfenster.svelte.js'
  import { klangwahlLaden } from './lib/klaenge.svelte.js'
  import {
    melden, meldewesenLaden, meldeText, schliesseMeldung, WERKZEUG_FEHLER_MS, werkzeugFertigDauer,
  } from './lib/meldewesen.svelte.js'
  import { auftraegeBeobachten } from './lib/auftragsmelder.js'
  import { verbinden as ereignisseVerbinden, trennen as ereignisseTrennen } from './lib/ereignisstrom.svelte.js'
  import { dateienAus, endsInFence, openFile } from './lib/markdown.js'
  import { seedlage } from './lib/bildseed.svelte.js'
  import { standLaden as agentenserverStandLaden } from './lib/agentenserver.svelte.js'
  import { tabWriter } from './lib/vorschautabs.svelte.js'
  import { leiste, leisteAnwenden, schalten as leisteSchalten } from './lib/arbeitsleiste.svelte.js'
  import Warteblasen from './teile/Warteblasen.svelte'
  import { anhalten, ausreihen, entfernen, haelt, loesen } from './lib/warteschlange.svelte.js'
  import { chatOeffnen, openNewChat, nachrichtenSetzen, nachrichtenAnzeige, eigeneZeilenSichern, eigeneZeilenZurueckgeben, bildlaufPlatzhalter, answerDrawingTile } from './lib/zustand.svelte.js'
  import { chosenModelOff } from './lib/modelle.svelte.js'
  import { chatFehlerGesehen, chatFehlerMerken, fragtNach } from './lib/chatringe.svelte.js'

  /* The terminal listens to the open chat: its runs, its lines. */
  $effect(() => {
    terminalVerbinden(zustand.aktiverChat)
  })

  /* Does this chat still find the folders it shares? Asked once, here, when
     a chat is opened — not on every keystroke and not in a loop: a folder
     moves while nobody is looking at this window, so the moment of opening
     is when the answer is worth anything. Nothing is run and nothing is
     removed; the window says it and the user decides. */
  $effect(() => {
    // The chat is read INSIDE, which is what makes this run again on a
    // switch — the same reading that decides whether the old answer is
    // thrown away (arbeitsordner.svelte.js).
    ordnerstandPruefen()
  })

  /* chatOeffnen found out the server is still writing an answer this window
     never heard of (C2) and left the word here — the actual reattachment
     needs antwortHolen's machinery, which lives in this component, not in
     the plain state module. Cleared right away so it fires exactly once.

     Only the entry for the chat now on screen is acted on: antwortHolen
     writes into `zustand.nachrichten`, which is the visible chat's list, so
     a reattachment for a chat nobody is looking at would land in the wrong
     conversation. A signal for another chat stays in the map untouched and
     is picked up the moment that chat is opened (this effect re-runs on
     `aktiverChat`). That is what makes the "open A, then very quickly B"
     case lose neither. */
  $effect(() => {
    const chatId = zustand.aktiverChat
    const wiederanhang = chatId ? zustand.wiederanhaengen[chatId] : null
    if (!wiederanhang) return
    delete zustand.wiederanhaengen[chatId]
    antwortWiederAnhaengen(wiederanhang)
  })

  /* Coming back to the window counts as seeing the open chat — its dot,
     if it earned one meanwhile, has said its piece. */
  $effect(() => {
    const zurueck = () => {
      chatFertigGesehen(zustand.aktiverChat)
      chatFehlerGesehen(zustand.aktiverChat)
    }
    window.addEventListener('focus', zurueck)
    return () => window.removeEventListener('focus', zurueck)
  })

  /* Opening a chat is looking at it: whatever its row was reporting has
     been reported. The green mark is cleared where the chat is opened
     (`chatOeffnen`); the red one lives one module further out and is
     cleared here, so the state module does not have to know about it.

     The clearing runs untracked, and that is not a detail. Reading the
     list of red chats inside the effect would make the effect depend on
     it — so a run that fails in the OPEN chat would mark the row, wake
     this effect, and have the mark wiped again in the same breath. The
     red dot would then never appear for the chat one is sitting in, which
     is precisely the chat one wants to be told about. Only the switch of
     chats may trigger this. */
  $effect(() => {
    const chatId = zustand.aktiverChat
    untrack(() => chatFehlerGesehen(chatId))
  })

  /* The mode lives here since the buttons moved from the menu bar into
     the settings window (3.11). It acts via an attribute on the root
     element — no component has to know which one currently applies. */
  let modus = $state(VORGABE_MODUS)
  begruessungLaden()
  /* What the shell found of a newer version of the program, and every
     change of it from here on. In a browser there is no shell to ask. */
  updatesStart()

  /* What the service last handed out or was last told. The mode is bound
     into two components, so there is no setter to hook — the effect below
     is where a change becomes visible, and comparing against this is what
     tells a change by the user apart from the one arriving at startup.
     Without that, the first read would write itself straight back. */
  let modusGespeichert = null

  /* The one look whose surfaces carry drawings; the window mounts them
     only while it stands. Every other look mounts none, and "auto" never
     resolves to this one. */
  const moune = $derived(modus === 'moune')
  /* Pearl carries four drawings on Moune's four surfaces; "auto" is Pearl
     while the device reports light. */
  const pearl = $derived(modus === 'hell' || (modus === 'auto' && !geraet.dunkel))
  /* Heaven carries four drawings on Moune's four surfaces: the frame, the
     right column, the chat tile and the input bar. The drawing a surface
     shows is named per look. */
  const heaven = $derived(modus === 'heaven')
  /* Exe carries one drawing, on the frame alone — the cubes under the side
     rails; "auto" is Exe while the device reports dark. The rails, the
     chat tile and the input bar take nothing: whatever stands on the
     frame is left as it is. */
  const exe = $derived(modus === 'dunkel' || (modus === 'auto' && geraet.dunkel))
  /* Dark Matter carries one drawing too, on the frame alone: the net of
     stars. */
  const darkmatter = $derived(modus === 'darkmatter')
  const leistenZeichnung = $derived(moune ? 'huegel' : heaven ? 'balloons' : pearl ? 'waves' : false)
  const eingabeZeichnung = $derived(moune ? 'pusteblume' : heaven ? 'paper-plane' : pearl ? 'oyster' : false)

  $effect(() => {
    const jetzt = modus
    /* While "auto" is on, the device's report is what the look resolves
       through — one query object, read live each run so a later switch to
       "auto" cannot paint through a stale report, and heard afterwards for
       a mid-run flip. */
    const abfrage = jetzt === 'auto'
      ? window.matchMedia('(prefers-color-scheme: dark)')
      : null
    if (abfrage) {
      geraet.dunkel = abfrage.matches
      document.documentElement.removeAttribute('data-modus')
    } else {
      document.documentElement.setAttribute('data-modus', jetzt)
    }
    if (modusGespeichert !== null && jetzt !== modusGespeichert) {
      modusGespeichert = jetzt
      modusSpeichern(jetzt)
    }
    /* The frame follows the look: every change of it redraws the gradient
       from the user's own choice, and "Auto" from the one it resolves to.
       Untracked — drawing reads the stored choice, and that read must not
       make this effect run again. */
    untrack(() => rahmenNeuZeichnen(jetzt))
    /* A device that turns dark (or light) mid-run changes which look
       "auto" resolves to: heard here, repainted at once — without this the
       previous look's colours would stay on the root element. */
    if (!abfrage) return
    const beiWechsel = (e) => {
      geraet.dunkel = e.matches
      rahmenNeuZeichnen('auto')
    }
    abfrage.addEventListener('change', beiWechsel)
    return () => abfrage.removeEventListener('change', beiWechsel)
  })

  /* The look, the two panel positions and the model last in use, in one
     read. Nothing may be written back on the way in — see above — and the
     model has to be known before modelleLaden() runs, or that would find
     none set and pick the first of the list instead. */
  async function anzeigeUebernehmen() {
    const geladen = await anzeigeLaden()
    if (geladen) {
      darstellungAnwenden(geladen.darstellung)
      seitenleisteAnwenden(geladen.layout)
      leisteAnwenden(geladen.layout)
      modellAnwenden(geladen.modell)
      modus = geladen.modus
      /* Draw after the flush: the attribute the look's sheet hangs on is
         written by the effect above, and drawing before it would read the
         previous look's defaults. */
      await tick()
      rahmenNeuZeichnen(modus)
    }
    modusGespeichert = geladen ? geladen.modus : modus
  }
  /* Empty chat: the input sits centered below the wordmark and glides
     down to its usual place on send. */
  const nochLeer = $derived(!nachrichtenAnzeige().length)
  /* The name the chat's head carries: the open chat's title from the list.
     The list is the search's result while somebody searches, and the open
     chat may not be in it — so the last title seen for this chat stands
     until the list carries it again. */
  let gemerkterTitel = $state({ id: null, titel: '' })
  const chatImVerzeichnis = $derived(
    zustand.chats.find((chat) => chat.id === zustand.aktiverChat) ?? null,
  )
  $effect(() => {
    if (chatImVerzeichnis) {
      gemerkterTitel = { id: chatImVerzeichnis.id, titel: chatImVerzeichnis.title }
    }
  })
  const chatTitel = $derived(
    chatImVerzeichnis?.title
      ?? (gemerkterTitel.id === zustand.aktiverChat ? gemerkterTitel.titel : ''),
  )
  let verlauf = $state(null)
  let eingabe = $state(null)
  // Running tool calls -> their notification, so the result rewrites the
  // same notification instead of creating a second one.
  const werkzeugMeldungen = new Map()

  /* Follow along, but only as long as the user is at the bottom. If they
     scroll up, following stops; once they reach the bottom again, it
     resumes.

     INTENT stops it, position resumes it. Only the reader can end the
     following: the first wheel tick upwards, a swipe, an arrow key. The
     position never does — because the position moves without the reader
     too. The browser keeps the content in view anchored while things
     above it change size (scroll anchoring): the "reading context" head
     giving way to the text, a document's reading mark vanishing, the
     compaction seam appearing — each one moves scrollTop by exactly that
     height and fires a scroll event for it. Judged by position, that
     event read as "the reader left", and following switched itself off
     mid-answer with nobody touching anything. Measured in the field: 36
     and 115 pixels, the very heights of those elements.

     The floor is the one place position may speak: whoever is back AT
     it, by any means, is following again.

     Our own snaps need no marking: they always land AT the floor, and the
     floor is where following is on anyway. A latch that flagged them used
     to stand here, and it was one edit away from swallowing the reader's
     next real scroll whenever a snap moved nothing. */
  let folgtMit = true
  let beruehrungY = 0
  /* Back at the floor means AT it, not near it — see scrollGeprueft(). A
     couple of pixels for the rounding a fractional layout leaves behind. */
  const AM_BODEN = 2
  /* Scrolling DOWN in the lower half of the window re-engages. While an
     answer streams, the floor runs away faster than a wheel can chase
     it: a reader who turned back down never caught it, so following
     never resumed — the field trace shows down-ticks of 200 pixels with
     the distance still growing, and a fixed band of 320 was missed by 26
     pixels. Half the window, measured at the moment of the tick: this
     far down a turn of the wheel can only mean "take me back". Higher
     up it is reading, and reading stays untouched. */
  const fangweite = () => verlauf.clientHeight / 2
  /* ...and only for a DELIBERATE turn. The tail of a trackpad flick
     upward emits a few small positive deltas; caught on a single tick,
     those teleported the reader to the floor right after they had
     scrolled up. Down-travel is summed per gesture (a pause or an
     up-tick resets it), and one real notch clears the bar on its own. */
  const FANG_WEG = 40
  let fangSumme = 0
  let fangZuletzt = 0
  /* How far a touch has dragged UP the page since it last turned — summed
     across move events, because one event is a few pixels — and how far
     back DOWN since then, so a real turn can be told from jitter. */
  let hochSumme = 0
  let runterSumme = 0

  function scrollGeprueft() {
    if (!verlauf) return
    const abstand = verlauf.scrollHeight - verlauf.scrollTop - verlauf.clientHeight
    /* Resume only. `wheel` fires BEFORE `scroll`, so a reader who nudged
       up a little is still close to the floor when this runs; a band that
       also STOPPED following by position once recomputed folgtMit as true
       here, right after radGedreht() had set it false, and the next chunk
       pulled them straight back down. Now nothing here can undo the
       reader's decision except the floor itself. */
    if (abstand <= AM_BODEN) folgtMit = true
    /* Still following, yet not at the floor: this scroll was not the
       reader's — theirs would have ended the following before the event
       arrived (wheel, touch and key all fire first). It is the browser
       moving the view: the clamp when a mark below the text gives way for
       a tick, an anchor adjustment, a focus. The floor is taken back IN
       THIS HANDLER, synchronously — the event runs before the browser
       paints, so the excursion never reaches the screen. runter() with
       its animation frame would be one visible frame too late here. */
    else if (folgtMit) verlauf.scrollTop = verlauf.scrollHeight
  }

  /* The scroll event, both jobs in order: decide whether we are still
     following, then remember where the reader is.

     `scrollGeprueft` is deliberately left doing only the first — it is
     lifted out of this file and run on its own in tests/test_chatscrollen.py,
     which is what keeps the follow rule from breaking a third time.

     The place is only worth keeping while it says something: a reader
     away from the floor, or the moment they come back to it. A streaming
     answer snaps to the floor several times a second, and following at
     the floor is what a chat comes back to by default — writing that
     every time would be a position nobody reads. */
  function gescrollt() {
    const folgteVorher = folgtMit
    scrollGeprueft()
    if (!folgtMit || !folgteVorher) stelleMerken()
  }

  /* Where this conversation is being read, kept with the conversation.
     Whether it is FOLLOWING is the part that carries: a chat left at the
     floor has to come back following along, whatever height its messages
     render at this time. The offset is only a wish beside it — pictures
     load late and rows re-measure, so the same number can mean a different
     place. Collected rather than written per scroll event; the store does
     the waiting (lib/chatanzeige.svelte.js). */
  function stelleMerken() {
    if (!verlauf) return
    scrollstelleSpeichern({
      am_boden: folgtMit,
      versatz: Math.max(0, Math.round(verlauf.scrollTop)),
    })
  }
  /* Where this chat was last read, put back on opening it.

     The place was written on every scroll, all the way into the database,
     and read back by nobody — so returning to a long conversation always
     landed at its end, however far up one had been. The store already
     fetches it when a chat opens (lib/chatanzeige.svelte.js); this is the
     half that was missing.

     Two values, and they do not weigh the same. `am_boden` is the one that
     carries: a chat left at the floor comes back following along, whatever
     height its messages happen to render at this time — and following is
     the default, so nothing changes for it. The offset is only a wish
     beside it: pictures load late and rows re-measure, so the same number
     can mean a different place. It is clamped to what actually exists
     rather than trusted.

     Once per chat. The message list keeps changing while an answer streams,
     and a restore that ran again would drag the reader back up mid-sentence. */
  let stelleGesetztFuer = null
  /* The mark of the hand is per chat: opening another one starts clean. */
  $effect(() => {
    const geoeffnet = zustand.aktiverChat
    void geoeffnet
    selbstGerolltChat = null
    nachsetzenZiel = null
  })
  $effect(() => {
    const chatId = zustand.aktiverChat
    const bereit = chatanzeige.geladen && chatanzeige.chatId === chatId
    const stehen = nachrichtenAnzeige().length
    /* No chat open: forget the place that was put back, so returning to the
       same chat puts it back again (the pages over the main area leave the
       active chat standing, a new chat sets it to nothing). */
    if (!chatId) {
      stelleGesetztFuer = null
      return
    }
    if (!bereit || !stehen || !verlauf) return
    if (stelleGesetztFuer === chatId) return
    /* Not into a running answer. The stored place loads over the network
       and can arrive seconds after the chat opened; by then an answer may
       be streaming, and this effect was the one thing left that could
       move the view up with nobody touching anything. A running chat
       opens following at the floor, which is where a live conversation
       is read anyway. */
    if (
      zustand.laufenderPlatzhalter[chatId] ||
      nachrichtenAnzeige().some((n) => n.zustand === 'laeuft')
    ) {
      stelleGesetztFuer = chatId
      folgtMit = true
      return
    }
    stelleGesetztFuer = chatId
    /* The reader scrolled by hand before the stored place arrived: it stays
       where they put it. */
    if (selbstGerolltChat === chatId) return
    stelleZurueck(untrack(() => chatanzeige.scrollstelle), chatId)
  })

  /* A chat left at the floor comes back following — said here, not left to
     whatever the previous chat was doing: a chat left at the very top
     stops following, and the list switching over to the next one moves
     nothing, so no scroll event would ever turn it back on.

     An offset of zero is not "nothing stored": left at the very top, a
     chat is saved as not following at offset zero, and that is a place
     too. A place that turns out to be the floor (the chat fits the window
     now) follows again, as a scroll that landed there would. */
  function stelleZurueck(stelle, chatId) {
    if (stelle.am_boden) {
      folgtMit = true
      return
    }
    folgtMit = false
    nachsetzenZiel = { chatId, versatz: stelle.versatz }
    requestAnimationFrame(stelleNachsetzen)
  }

  /* The place still waiting to be reached, and the chat the reader has
     scrolled by hand in. A late-arriving place must not move a view the
     reader already moved themselves; the program's own scrolling does not
     count, only the wheel, the finger and the keys do. */
  let nachsetzenZiel = null
  let selbstGerolltChat = null

  /* Puts the view at the wanted place — and again whenever the list has
     grown, until it is reached or the reader scrolls by hand. One frame is
     not enough: in a narrow column the rows are measured late and the list
     is still shorter than the place when the first frame comes, so the
     view landed at the end instead. Called by stelleZurueck and by the
     observer of the list's size. While the place is out of reach the view
     is held at what exists but does NOT follow: following would drag the
     reader to the floor when the list grows. */
  function stelleNachsetzen() {
    const ziel = nachsetzenZiel
    if (!ziel) return
    if (!verlauf || zustand.aktiverChat !== ziel.chatId || selbstGerolltChat === ziel.chatId) {
      nachsetzenZiel = null
      return
    }
    const hoechst = Math.max(0, verlauf.scrollHeight - verlauf.clientHeight)
    verlauf.scrollTop = Math.min(ziel.versatz, hoechst)
    /* Out of reach: the scroll event this write causes finds the view at
       the floor and would switch following on (scrollGeprueft), which the
       next growth would answer by dragging the reader to the end. Said
       again here, every time, until the place is reached. */
    if (hoechst < ziel.versatz) {
      folgtMit = false
      return
    }
    nachsetzenZiel = null
    folgtMit = verlauf.scrollHeight - verlauf.scrollTop - verlauf.clientHeight <= AM_BODEN
  }

  function radGedreht(ereignis) {
    selbstGerolltChat = zustand.aktiverChat
    if (ereignis.deltaY < 0) {
      folgtMit = false
      fangSumme = 0
    } else if (ereignis.deltaY > 0 && verlauf && !folgtMit) {
      const jetzt = performance.now()
      if (jetzt - fangZuletzt > 400) fangSumme = 0
      fangZuletzt = jetzt
      fangSumme += ereignis.deltaY
      const abstand = verlauf.scrollHeight - verlauf.scrollTop - verlauf.clientHeight
      if (fangSumme >= FANG_WEG && abstand <= fangweite()) runter(true)
    }
  }
  /* The keyboard's way up. Only while nothing is being typed: inside a
     field the arrow moves the caret, not the chat. */
  const TASTEN_HOCH = new Set(['ArrowUp', 'PageUp', 'Home'])
  function tasteHoch(ereignis) {
    if (!TASTEN_HOCH.has(ereignis.key)) return false
    if (ereignis.metaKey || ereignis.ctrlKey || ereignis.altKey) return false
    const ziel = ereignis.target
    if (ziel?.isContentEditable) return false
    const tag = ziel?.tagName
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return false
    /* The arrow is the chat's only when nothing else is being steered.
       The pickers are buttons and listboxes that walk their entries with
       ArrowUp and Home (Auswahlfeld, Klappwahl) — they preventDefault but
       the event still bubbles to the window, and walking a model list
       used to end the follow-along without the chat being touched. Named
       by what they ARE — the combobox and its frame, the drop-down's
       frame, any listbox — not by "any button": focus rests on whatever
       button was clicked last, a copy button or a tool card, and with
       every button excluded PageUp and Home stopped working for the chat
       the moment one had been clicked. */
    if (ziel?.closest?.('[role="listbox"], [role="combobox"], .feldplatz, .klappwahl')) return false
    return true
  }
  function beruehrungBeginnt(ereignis) {
    beruehrungY = ereignis.touches[0].clientY
    fangSumme = 0
    hochSumme = 0
    runterSumme = 0
  }
  function beruehrungZieht(ereignis) {
    /* Followed move by move, not measured against the touch's start: a
       drag that went up and turns around must count its way back down,
       and the old start-anchored compare made that reversal invisible
       until the finger lifted.

       Both directions are SUMMED, though. A single move event carries a
       few pixels, and a slow, deliberate drag up the page never reached
       the threshold in one of them — the follow-along stayed on and the
       next paint pulled the reader back to the floor under their finger.
       And only a REAL turn — more than the jitter a finger makes — starts
       the other direction over: a pixel of wobble inside a drag reset the
       catch-up sum every other event, and the follow-along could never be
       re-armed by hand. */
    selbstGerolltChat = zustand.aktiverChat
    const y = ereignis.touches[0].clientY
    const schritt = beruehrungY - y
    beruehrungY = y
    // Finger moving down = looking up.
    if (schritt < 0) {
      const vorher = hochSumme
      hochSumme -= schritt
      /* The moment the sum CROSSES the threshold is the turn — once. Reset
         on every step above it, a pixel of wobble inside a drag back down
         wiped the catch-up sum again and again. */
      if (vorher <= 8 && hochSumme > 8) {
        folgtMit = false
        fangSumme = 0
        runterSumme = 0
      }
    } else if (schritt > 0) {
      runterSumme += schritt
      /* Consumed with the turn it made: left standing, every further
         pixel of wobble past the threshold wiped the up sum again and
         again, and the follow-along could not be stopped for the rest of
         the touch. */
      if (runterSumme > 8) {
        hochSumme = 0
        runterSumme = 0
      }
      if (!folgtMit) fangSumme += schritt
    }
  }
  function beruehrungEndet() {
    /* The snap waits for the finger to lift: mid-drag it yanked the page
       under the reader's hand and the rest of the gesture scrolled from
       the wrong place. */
    if (!verlauf || folgtMit || fangSumme < FANG_WEG) return
    fangSumme = 0
    const abstand = verlauf.scrollHeight - verlauf.scrollTop - verlauf.clientHeight
    if (abstand <= fangweite()) runter(true)
  }
  function runter(erzwingen = false) {
    if (!verlauf) return
    if (erzwingen) folgtMit = true
    if (!folgtMit) return
    const schnappen = () => {
      /* Check again at execution time — the user may have bailed out in
         the meantime, and so may the restore of a chat's read position
         above, which turns following off before it puts the view back
         where the chat was left. Both ways below therefore ask again;
         neither may snap on a decision that was taken when it was
         scheduled rather than when it runs. */
      if (!folgtMit || !verlauf) return
      // Already at the floor: nothing to snap.
      if (verlauf.scrollHeight - verlauf.scrollTop - verlauf.clientHeight <= 0) return
      verlauf.scrollTop = verlauf.scrollHeight
    }
    /* Two ways to the same snap, and the frame is the better one: it runs
       once the new text has been laid out, so the view lands at the height
       the list will actually have.

       A hidden or backgrounded window runs no animation frames at all,
       though — and animation frames are what following along was made of
       here, so an answer written into a covered window came back standing
       at the line where the window was covered. The plain timer is the
       second way in, the same fallback runterGleiten() already keeps
       beside its own frames. A hidden window stretches such a timer to
       about a second, which is late for a frame and soon enough for a
       floor nobody is looking at.

       Only ONE of the two may act per call. Both carry the guards above,
       so a second run would find the floor already reached and leave
       again — but a covered window would otherwise park a frame per chunk
       and run the whole pile at once the moment it is uncovered. Whichever
       arrives first takes the snap and cancels the other. */
    let frame = 0
    const nachzuegler = setTimeout(() => {
      cancelAnimationFrame(frame)
      schnappen()
    }, 150)
    frame = requestAnimationFrame(() => {
      clearTimeout(nachzuegler)
      schnappen()
    })
  }

  /* Following means AT the floor — whenever box or content change size,
     not only when a chunk arrives.

     Two things move the floor without a chunk. The box: the input field
     grows with what is being typed and the box above it shrinks by the
     same amount. The content: a live head gives way to the text, a
     document's reading mark vanishes, the compaction seam appears, a
     tool row swaps its "still running" for its result — each one changes
     the content's height, and the browser then moves the view to keep
     what it had anchored in place. With nothing arriving, nothing called
     runter(), so the view stood a head's height above the floor until
     the next chunk — for as long as the model took to send one. Seen in
     the field as a 115-pixel gap under the answer, and as the last lines
     sliding under the field while typing.

     Both are watched here and the floor re-taken in the next frame.
     runter() carries the guards: not following, or already at the floor,
     and nothing happens — a reader who scrolled away is not touched. */
  $effect(() => {
    if (!verlauf || typeof ResizeObserver === 'undefined') return
    const beobachter = new ResizeObserver(() => {
      stelleNachsetzen()
      runter()
    })
    beobachter.observe(verlauf)
    const spur = verlauf.querySelector('.spur')
    if (spur) beobachter.observe(spur)
    return () => beobachter.disconnect()
  })

  /* Keeps the view's floor glued to the list's end for a little while —
     one snap per frame. Used while a message grows in place (the picture
     frame's 75%→100% growth): with the bottom standing still, the growth
     reads upward instead of sliding out below. Bails out the moment the
     reader scrolls away, exactly like runter(). */
  function runterGleiten(dauer = 750) {
    if (!verlauf) return
    folgtMit = true
    const ende = performance.now() + dauer
    const halten = () => {
      if (!folgtMit || !verlauf) return
      // Already at the floor: nothing to snap.
      if (verlauf.scrollHeight - verlauf.scrollTop - verlauf.clientHeight <= 0) return
      verlauf.scrollTop = verlauf.scrollHeight
    }
    const schritt = () => {
      halten()
      if (performance.now() < ende) requestAnimationFrame(schritt)
    }
    requestAnimationFrame(schritt)
    /* Animation frames stand still while the window is hidden; a few plain
       timers hold the floor there too, so a picture finishing in a covered
       window still ends at the floor instead of just above it. */
    for (const zeit of [150, 400, dauer, dauer + 400]) setTimeout(halten, zeit)
  }

  /* The chat's ONE live waiting mark.

     Every waiting mark used to stand in its own row — the document mark
     under the question, the working mark under the answer — and each
     appearing or vanishing changed a row's height, which is exactly the
     movement the follow-along then had to catch. Now one mark is decided
     HERE and drawn as the last entry on the line of the answer it waits
     for (`wartemarke`, below; Nachricht.svelte), in one row of one fixed
     height: a mark changing its face can technically not move the chat
     any more.

     It stands until the run ends — before the first word, under text
     already written, and through silent stretches: a server may hold a
     tool call back until it is complete and send nothing for minutes, and
     written text says nothing about whether the run still goes. Its words
     never repeat an entry above it (a waiting word or "reading the
     context", never the thinking head's or a tool row's text). While the
     run waits on the reader, the yellow entry of the question stands
     instead.

     What the mark says while it waits, in the language of the window. It
     used to be English whatever the window was set to, and said so: "English
     for every language, like the reasoning head". The comparison was already
     wrong when it was written — the reasoning head says Denken in a German
     window (`nachricht.gedankengang`) — and the rule itself is gone now:
     these are words a person reads while they wait, not names of states.

     Out of the catalogue rather than out of this file, which is what makes
     that possible at all, and how many there are is the catalogue's answer
     too (`wartewort` in app/locales). The keys are plain numbers, which are
     canonical array indices, so they are walked in ascending numeric order
     however the file happens to be written. `$derived`, so a change of
     language reaches this without a reload.

     Through `t()` and not out of the catalogue object, even though the keys
     come from there: the catalogue guard (tests/test_katalogwache.py) reads
     the fixed part of a composed key out of the source, and `wartewort.`
     written here is what lets it see these ten as used instead of dead. */
  const WARTEWORTE = $derived(
    Object.keys(texte.katalog.wartewort ?? {}).map((nummer) => t(`wartewort.${nummer}`)),
  )
  const laufMarke = $derived.by(() => {
    const zeile = [...nachrichtenAnzeige()]
      .reverse()
      .find((n) => n.zustand === 'laeuft' || (laufenderId && n.id === laufenderId))
    if (!zeile) return null
    // A run that has ended carries its closing word ('fertig',
    // 'abgebrochen', ...) while this window still holds its placeholder —
    // the end of a run can wait on a fresh history before letting go of it,
    // and the mark must not stand under a finished answer in the meantime.
    if (zeile.zustand && zeile.zustand !== 'laeuft') return null
    // A visible character found, not the whole text trimmed: this runs on
    // every streamed chunk, and the text only grows.
    const hatText = /\S/.test(zeile.content || '')
    // A running picture draws its own frame; a second mark would
    // contradict it.
    if (!hatText && zeile.bildLaeuft) return null
    // Waiting on the reader (a permission, a question, a job to confirm):
    // the yellow entry on the line says so, and nothing is being worked
    // on. Read off the question boxes themselves, which stand exactly as
    // long as the question does — after a reload too.
    if (fragtNach(zustand.aktiverChat)) return null
    const auge = Boolean(zeile.vision) && !hatText && !zeile.werkzeuge?.length
    const marke = { id: zeile.id, art: auge ? 'vision' : 'antwort', text: '', seit: zeile.taetigkeitSeit }
    if (zeile.taetigkeit === 'verdichtung')
      return { ...marke, art: 'verdichtung', text: t('status.komprimiert') }
    /* The model is working the context through (right after sending, and
       again after every tool result): the mark says so, with that
       stretch's own clock, in place of a waiting word — a sentence that
       carries its time, so only with a start to count from. */
    if (zeile.taetigkeit === 'kontext' && zeile.taetigkeitSeit != null) return { ...marke, kontext: true }
    return marke
  })
  /* ONE word per waiting stretch, picked when the mark appears and then
     left standing. Swapping it every few seconds would fidget — and it
     did: `laufMarke` is a fresh object on every recompute, and every
     streamed chunk recomputes it, so an effect watching the OBJECT drew a
     new word several times a second. The effect watches the bare yes/no
     instead, which only flips when a wait begins or ends. */
  const markeSteht = $derived(Boolean(laufMarke))
  /* WHERE in the list, not WHICH word: a fraction, drawn once when the mark
     appears. That keeps the rule above through a change of language — the
     lists are parallel, so the same place is the same sentence in the other
     one, and the mark translates instead of jumping to an unrelated word.
     Drawing the word itself would have meant drawing a NEW one, because the
     list is a different array after the change.

     `-1` is "no word": `Math.random()` can return 0, so zero cannot be the
     answer for "nothing". */
  let wartestelle = $state(-1)
  $effect(() => {
    wartestelle = markeSteht ? Math.random() : -1
  })
  /* The mark's running time: how long the run has been at its present
     activity (`taetigkeitSeit`, stamped by the stream whenever the activity
     changes, lib/taetigkeit.js) — a new stretch, a new clock from 0:00.
     A row with no start of its own (one this window did not send, before
     the stream is re-attached) shows no clock rather than one that never
     moves. It runs on the chat's one clock, held while a mark stands — the
     same one the thinking head above it reads (lib/sekundentakt.svelte.js). */
  const markeZaehlt = $derived(laufMarke?.seit != null)
  $effect(() => {
    if (!markeZaehlt) return
    return taktHalten()
  })
  const laufZeit = $derived(markeZaehlt ? stoppuhr(takt.jetzt - laufMarke.seit) : '')
  /* An empty list is a real state, not a mistake — a catalogue shipped
     without this group — and picking out of nothing would put the word
     `undefined` on the screen. Empty then, and the mark shows its own text,
     which is what it showed before there were words at all. (It is NOT the
     "catalogue not loaded yet" case: main.js awaits `texteLaden` before the
     window is mounted at all.) */
  const wartewort = $derived(
    wartestelle >= 0 && WARTEWORTE.length
      ? WARTEWORTE[Math.floor(wartestelle * WARTEWORTE.length)]
      : '',
  )

  /* The regenerate arrow, and the "send again" of the last question.

     Filtered by `art` as well as by role: a finished background command
     and a picture are assistant rows too, and whichever of them happened
     to land last used to pull the arrow onto itself — regenerating a tool
     report is not a thing, and "send again" would have DELETED it. Only an
     ordinary turn can be one of these. */
  /* How long the end-of-run reconcile may wait for the fresh page before
     the run is released without it. Generous for a page of five hundred
     rows over a slow link; short beside a chat that stays locked. */
  const NACHLADE_FRIST_MS = 15_000
  /* How often a send whose line broke asks the service where its answer
     went. Half a second, the tick the layout guard already uses: the fold
     in front of the answer is not observable any other way, and asking
     faster would only load the very service that is busy folding. */
  const HALTEPRUEFUNG_MS = 500
  /* How long the window waits before it tries the broken line again: one
     second, and twice as much after every further failure, up to half a
     minute. A stream that opens throws the wait away. The run outlives the
     line, so the window has to come back to it. */
  const WIEDERANHANG_PAUSE_MS = 1_000
  const WIEDERANHANG_PAUSE_MAX_MS = 30_000

  const letzteAntwort = $derived(
    [...nachrichtenAnzeige()]
      .reverse()
      .find((n) => n.role === 'assistant' && (n.art ?? 'nachricht') === 'nachricht'),
  )
  const letzteFrage = $derived(
    [...nachrichtenAnzeige()]
      .reverse()
      .find((n) => n.role === 'user' && (n.art ?? 'nachricht') === 'nachricht'),
  )

  /* The row a run in THIS window is writing — by id, never by position.
     `laufenderPlatzhalter` is the very object the stream writes into, so
     asking it is asking the run itself. The stored `zustand === 'laeuft'`
     covers the other direction: a run this window did not start, whose row
     the server already marks as live. */
  const laufenderId = $derived(
    zustand.laufenderPlatzhalter[zustand.aktiverChat]?.id ?? null,
  )

  // The tile size inside a run's row — the exact same card component as a
  // single picture, only told to draw itself smaller (see Nachricht.svelte's
  // bildDeckel prop). Two tiles at this width plus the row's own gap is the
  // row's max-width, so a third tile has nowhere to go but its own
  // centered line below — no per-count layout branches, just wrapping.
  /* Set by the user in the layout mode (lib/chatlayout.js). */
  const BILDLAUF_KACHEL = $derived(zustand.chatlayout.bildkachel)
  // The card's own 1px frame on each side (see Nachricht.svelte's .erzeugt)
  // makes a tile exactly these two pixels wider than bildDeckel. Without
  // them each tile's half of the row is that much short, and a picture
  // comes out two pixels under the size that was set.
  const BILDLAUF_KACHEL_RAHMEN = 2

  /* Images per run (Weg A, Schritt 3): a run's pictures all live in ONE
     message's own `bilder` array now — no more grouping several
     messages by a shared `stats.lauf`, no `eigeneFrage` exception for a
     recreated question, no per-row shortfall bookkeeping. A run splitting
     across rows, a foreign message landing between two of a run's own
     pictures, a recreated question being mistaken for a tile — every one
     of H1/H1b/H1d/H1e/H1h/H1i/H2 existed only because a run was ever
     more than one message. None of them have anything left to happen to.

     Returns the tile view for a message's own pictures, or `null` if it
     is not a run at all — `bilder` is only ever set by
     `lauf_bild_speichern` (Weg A Schritt 2), never by a single vision
     upload or an old Weg-B row. Each tile is a SYNTHETIC view of the one
     real message, built so `Nachricht.svelte` never has to learn that a
     list exists at all: it already renders "one message, one `bild`"
     correctly, save/enlarge/seed-copy included, and none of those
     actions are destructive per tile (K2 already strips the one that
     was, the regenerate arrow) — sharing the parent's own `id` across
     every tile is therefore safe. B14: a gap stays a gap, an empty
     string is not a name to ask the server for. */
  function bildKacheln(nachricht) {
    if (!Array.isArray(nachricht.bilder)) return null
    const seeds = nachricht.stats?.seeds
    return nachricht.bilder
      .map((datei, index) => (datei ? {
        ...nachricht,
        // C2 (Aufseher): every tile of this message deliberately shares
        // the SAME `id` — the actions Nachricht.svelte can take on a
        // tile are none of them destructive per tile (see above), so
        // there is nothing this `id` needs to tell apart. The template's
        // own #each key stays unique regardless (`kachel.id + '-' +
        // index`), which is what actually keeps Svelte from confusing
        // one tile for another — not this field.
        id: nachricht.id,
        bild: datei,
        stats: { ...nachricht.stats, seed: seeds?.[index] ?? null },
      } : null))
      .filter(Boolean)
  }

  /* Which run a row belongs to, asked in ONE place instead of at each of
     the six sites below that need it.

     The answer used to live in the stats blob as `stats.lauf`; it is a
     column of its own now (`lauf_id`), and the window kept reading the
     blob after the writers had stopped filling it. That failure is
     invisible from the reading side: `undefined !== 'lauf-x'` is exactly
     what a row belonging to a DIFFERENT run looks like, so every test
     below went on answering plausibly — the tiles simply stopped finding
     each other. One accessor is what makes the next such move a single
     edit rather than six, and it is why this is a function at all for
     what is otherwise a field read.

     The column alone, deliberately, with no fallback to the old key: the
     migration that added `lauf_id` backfilled it from `stats.lauf` for
     every row that carried one, so a stored row with the old key has the
     column too and a fallback could never fire on one. Where it WOULD
     have fired is the rows this window writes itself before the server
     has seen them — and keeping those on a second, no-longer-maintained
     shape is the exact split that produced this defect. They write
     `lauf_id` now, the same field the server sends back. */
  function laufKennung(nachricht) {
    return nachricht?.lauf_id ?? null
  }

  /* The "a picture is being drawn" frame belongs INSIDE the run's own
     grid, as the next cell — not underneath it. It is a message of its
     own (the `bildlauf-` placeholder pushed by `bildEinesZeichnen`), and
     standing next to the grid it moved every time the grid gained a line.
     As a cell it stands in the slot the picture is actually going to
     take, and the slot is a real one: that picture is being drawn at
     this very moment. When the run ends the cell is simply gone and
     leaves no hole — which is what separates it from a reserved empty
     slot, the thing this row deliberately never does.

     Returns the placeholder for THIS run's grid, or null. Only ever for
     the run currently being drawn, so a finished run below it never
     borrows the frame of one that started afterwards. A run that is an
     answer's takes the answer's own tile (`answerDrawingTile`), the
     picture window's run the window's — both can stand in one chat. */
  function laufendeKachel(nachricht, laufAktuell, alleNachrichten) {
    if (!laufAktuell || laufKennung(nachricht) !== laufAktuell) return null
    // An answer's run is keyed by the answer's own id, which stands in the list.
    const ofAnswer = alleNachrichten.some((n) => n.id === laufAktuell)
    return alleNachrichten.find(
      (n) => n.bildLaeuft && (ofAnswer ? n.answerId === laufAktuell : !n.answerId),
    ) ?? null
  }

  /* ...and the same placeholder must then NOT be drawn a second time as
     an ordinary message further down the list. Only once a grid exists
     to take it: the run's very first picture has no row to join yet, and
     draws as the full-width frame it always did. */
  function inKachelAufgegangen(nachricht, laufAktuell, alleNachrichten) {
    if (!nachricht.bildLaeuft || !laufAktuell) return false
    const raster = alleNachrichten.find(
      (n) => n !== nachricht && laufKennung(n) === laufAktuell && Array.isArray(n.bilder),
    )
    // Only the tile that grid really draws as its cell; another one still
    // stands where it is.
    return Boolean(raster) && laufendeKachel(raster, laufAktuell, alleNachrichten) === nachricht
  }

  /* B9/B15: the shortfall caption, one true number, no ceiling. Weg B
     had to cap this comparison at four (the chat's own old display
     limit) or a fully successful run of more than four read as missing
     ones it never had — B9. The same cap silently swallowed a REAL
     shortfall above four just as often — a run of six with five drawn
     compared "5 < min(6, 4)" and stayed quiet — B15. Both die from the
     same cause: there is no ceiling left to compare against. `von` is
     the run's own true total (`stats.von`, at most 8), the tile count is
     exactly how many of `bilder`'s own entries are real — nothing here
     ever counts past either number or falls back to counting tiles that
     do not exist. `null` while the run is still the one being drawn
     (`laufAktuell`): "still filling in" and "genuinely short by one"
     look identical from the message alone, and only the live queue
     knows which one this is. */
  function teilausfall(nachricht, laufAktuell, alleNachrichten) {
    // C5 (Aufseher): `bildEinesZeichnen`'s own end-of-run toast counts
    // the SAME shortfall from the in-flight request queue, not from
    // this saved row — the two cannot share one computation (this one
    // only sees what the server stored, that one only sees what was
    // asked for) but are kept in step by comment; a change here is a
    // prompt to check that one too.
    const von = nachricht.stats?.von
    const lauf = laufKennung(nachricht)
    // `lauf &&` is not decoration: this used to compare an ABSENT key,
    // and `undefined === null` is false, so a row with no run of its own
    // fell through to the count while nothing was being drawn. Reading a
    // real field, absence is `null` — the same value `laufAktuell` has
    // between runs — and the bare comparison would newly read "no run at
    // all" as "the run being drawn right now" and go silent forever.
    // Suppression belongs to the row that IS the live run, which a row
    // without a run id can never be.
    if (!von || (lauf && lauf === laufAktuell)) return null
    // C6 (Aufseher): a lauf is ONE row by construction (B3), but a
    // restart mid-run can still leave it split across two — the row
    // written before the restart and the one the next picture created
    // after, both carrying the same run id. Counting only THIS row's own
    // `bilder` then reads a picture sitting in the OTHER row, right next
    // to it on screen, as one that failed — B9's own defect
    // in a new shape, not a new mistake. Summed over every message that
    // shares this lauf, not just the one asked about, and reported only
    // once — on the LAST of them — so a split lauf does not report its
    // own true shortfall twice.
    const geteilteZeilen = alleNachrichten.filter((n) => laufKennung(n) === lauf)
    if (geteilteZeilen[geteilteZeilen.length - 1] !== nachricht) return null
    const gezeichnet = geteilteZeilen.reduce(
      (summe, n) => summe + bildDateien(n).length, 0,
    )
    const gescheitert = von - gezeichnet
    return gescheitert > 0 ? { gescheitert, von } : null
  }

  /* K4/K4b + C6 (Executor): a message carries its own pictures in one of
     two shapes — the old single upload (`bild`, a bare file name) or a
     Weg-A run's own list (`bilder`, one array entry per requested
     position, `null` where a picture has not finished or did not
     survive) — and more than one place in the window needs to know a
     row's real count regardless of which shape it is: `traegtBild`
     below, and `teilausfall`'s own sum across a lauf split by a mid-run
     restart. Both used to answer that question on their own; asking it
     here instead is what let `teilausfall` count a legacy `bild`-only
     row's picture at all instead of reading it as zero. Mirrors the
     server's own `Message.bild_dateien()`. */
  function bildDateien(nachricht) {
    if (Array.isArray(nachricht?.bilder)) {
      const echte = nachricht.bilder.filter(Boolean)
      if (echte.length) return echte
    }
    return nachricht?.bild ? [nachricht.bild] : []
  }

  /* A run that has not drawn a single picture yet still has a non-empty
     ARRAY of nulls, and in JavaScript that array is truthy same as a
     full one — `!nachricht.bilder` alone would call an all-null run "no
     picture" and let it through. Checked by content, via `bildDateien`,
     not by presence. */
  function traegtBild(nachricht) {
    return bildDateien(nachricht).length > 0
  }

  /* Send again beneath one's own bubble: same effect
     as regenerate beneath the answer — if an answer is there, it gets
     replaced; if it's missing (e.g. after an abort), it simply gets
     fetched. Fetching an answer only ever means asking the LANGUAGE
     model, so this only ever looks for a text answer to replace — K4:
     without the `!traegtBild(letzte)` guard, the chat's last message
     being a picture (this button sits under every question, a lauf's
     own included, and its own last message is one of that lauf's own
     tiles or its one Weg-A answer row) made this delete that picture
     through the same door H1b/K2 already had to close. Under a picture,
     "send again" simply fetches a fresh text answer instead of touching
     it. */
  async function frageNeuSenden() {
    if (laufVon(zustand.aktiverChat)) {
      melde(t('eingabe.laeuft_schon'))
      return
    }
    // A new answer, so the same rule as sending: none from a model that is off.
    if (chosenModelOff()) return
    /* `letzteAntwort`, not the last row: that one may be a finished
       background command, and `neuErzeugen` DELETES what it is given. The
       `traegtBild` test stays — it closed the same door for picture rows
       before `art` existed, and a row can still carry a picture without
       being one. */
    const letzte = letzteAntwort
    if (letzte && letzte.id && !traegtBild(letzte) && antwortAufLetzteFrage(zustand.nachrichten, letzte, letzteFrage)) {
      await neuErzeugen(letzte.id)
    } else {
      await antwortHolen(null)
    }
  }

  /* Is that answer the one that belongs to the last question?

     `letzteAntwort` picks the last ORDINARY answer, skipping reports and
     pictures — which is right for the arrow, and wrong on its own for a
     button that deletes: with a picture prompt and its picture standing
     last, the last ordinary answer belongs to the question BEFORE them,
     and "send again" would have deleted that one and regenerated it on a
     history that ends elsewhere. An answer may only be replaced when it
     stands behind the last question; otherwise the question simply gets
     an answer fetched, nothing removed. */
  function antwortAufLetzteFrage(nachrichten, antwort, frage) {
    if (!antwort || !frage) return false
    return nachrichten.indexOf(antwort) > nachrichten.indexOf(frage)
  }

  /* The one swap between thinking and answer, as the drawn stretches see it
     — the service side is `app/reasoning.denktext_als_antwort`, and this is
     what its verdict does to the bubble that is already standing there.

     A model that thought its answer instead of writing it leaves the pieces
     holding a thought as a thought and no answer at all, while the chat's
     own row says the other: the thought that changed sides is the END of
     what streamed in, word for word the answer. So the drawn thinking is
     cut back to the part that stayed thinking — `reasoning` is exactly that
     part — and the answer is drawn after all of it.

     The stretches keep their order, their times and the tool rows they
     carry; only their text is cut, and a stretch the cut emptied out steps
     aside, because an empty thinking head would stand there otherwise. The
     input is left alone — the caller gets a new list.

     One closing event per answer, and one answer per bubble: a run whose
     stream is picked up again clears the bubble and replays every event, so
     this never runs twice on what it already lifted.

     `content` is the whole row's answer. Where an earlier tool round wrote a
     sentence before its call, that sentence already stands drawn and
     `content` begins with it; only what follows it is drawn after the
     thinking, or the sentence would stand twice.
     */
  function liftAnswer(strecken, content, reasoning) {
    let left = reasoning ?? ''
    const kept = []
    for (const a of strecken) {
      if (a.art !== 'reasoning') {
        kept.push(a)
        continue
      }
      const take = Math.min(left.length, a.text.length)
      const text = left.slice(0, take)
      left = left.slice(take)
      if (text) kept.push({ ...a, text })
    }
    const drawn = strecken
      .filter((a) => a.art === 'content')
      .map((a) => a.text)
      .join('')
    const lifted = drawn && content.startsWith(drawn) ? content.slice(drawn.length) : content
    kept.push({ art: 'content', text: lifted })
    return kept
  }

  /* The live readings of a round end with that round. Called wherever the
     run comes to a stand at a tool — its call written (`tool_call`), a
     permission asked (`tool_confirm`), a question put (`user_ask`) or a
     task held for confirmation (`job_confirm`) — and at the answer's end,
     where the measured figure takes over (`stats`): what a round read of
     its own prompt and its own writing must not stand while nothing is
     written. A run without a tool never comes to such a stand, and a
     stream picked up again after a dropped connection keeps the reading —
     it is the same round, still writing. */
  function lesungenLeeren(platzhalter) {
    platzhalter.liveSpeed = null
    platzhalter.liveShare = null
  }

  async function senden(
    inhalt, anhaenge = null, dokumente = null, denken = null, skill = null, gespraech = false,
    messageId = null,
  ) {
    /* A question from the model is waiting: then what was typed IS the
       answer, not a new message. Free text always counts — the buttons are
       an offer, not a cage. */
    if (
      zustand.benutzerfrage[zustand.aktiverChat]
      && inhalt?.trim()
    ) {
      await benutzerfrageBeantworten(inhalt.trim())
      return
    }
    if (!zustand.modellId) {
      melde(t('fehler.kein_modell_verfuegbar'), 'fehler')
      return
    }
    // Switched off in the quick picker: nothing goes to it (lib/modelle).
    if (chosenModelOff()) return
    /* The images first: if an upload fails, the chat stays untouched and
       the input is still there. The chat is claimed for the uploads' sake
       already (see the send mark below): a queued entry with a picture
       uploaded first and claimed after, and in that stretch the queue,
       woken by the previous run's end, sent the NEXT entry into the same
       chat. A chat that does not exist yet has nothing to claim — and
       nothing queued for it either.

       Documents (4.1) need none of this here: each one is already
       uploaded and read by the time it reaches this function — Eingabeleiste
       uploads it the moment it is attached, not on send. `dokumentListe`
       below is real server meta, not files. */
    const bildDateien = [...(anhaenge || [])]
    const dokumentListe = [...(dokumente || [])]
    const bilder = []
    const ladeChat = zustand.aktiverChat
    if (ladeChat) zustand.sendet[ladeChat] = true
    try {
      for (const datei of bildDateien) {
        try {
          bilder.push((await api.bildHochladen(datei)).bild)
        } catch (fehler) {
          melde(String(fehler.message || fehler), 'fehler')
          return
        }
      }
    } finally {
      // Handed over to the mark below without an await in between.
      if (ladeChat) delete zustand.sendet[ladeChat]
    }
    /* The title says what the chat is about, not which instruction was used
       to get there — so a picked skill is cut off the front of it. */
    const fuerTitel = skill ? inhalt.slice(skill.length + 1).trim() || inhalt : inhalt
    const ersterTitel =
      fuerTitel.length > 40
        ? fuerTitel.slice(0, 40) + '…'
        : fuerTitel || dokumentListe[0]?.name || t('eingabe.bild_titel')
    if (!zustand.aktiverChat) {
      await openNewChat({ title: ersterTitel, endpoint_id: zustand.modellId })
    } else if (!nachrichtenAnzeige().length) {
      /* A chat can now exist before the first message — setting a working
         folder creates one. It is still untitled
         at that point, so the first message gives it its name here, exactly
         as it would have on creation. */
      const chat = aktuellerChat()
      if (chat && chat.title === t('chat.unbenannt')) {
        chat.title = ersterTitel
        api
          .chatAendern(chat.id, { title: ersterTitel })
          .then(chatsLaden)
          .catch(() => {})
      }
    }
    /* Busy from here to the run. `laufVon` is still empty in this stretch —
       a second enter used to call senden() again and bear a second answer
       row with the same placeholder id. The input bar queues while this
       stands (laeuftGerade), and the queue itself waits for it. Cleared
       in the finally: by then the run exists and `laufVon` guards, or
       the send failed and the chat is free again. After the chat
       creation above, so a brand-new chat rides on its real id. */
    const sendeChat = zustand.aktiverChat
    /* A chat open that lost its race leaves the list tagged
       for a foreign chat while this one shows empty. Sending here must not
       bury the new question in that foreign, hidden list. */
    if (zustand.nachrichtenChatId !== sendeChat) nachrichtenSetzen(sendeChat, [])
    zustand.sendet[sendeChat] = true
    try {
    /* Given to the service with the request below, so the row it becomes
       carries this same id — not `crypto.randomUUID()`: a service reached
       over plain HTTP from another machine is not a secure context, and
       there that function does not exist at all (see Eingabeleiste.svelte's
       document ids).
       The input bar brings its own: it is the key under which the bar keeps
       what this send took out of it, so a refusal gives back exactly that. */
    const frageKennung = messageId ?? Math.random().toString(36).slice(2, 9)
    /* The document's own card is real from the first frame — the meta IS
       the server's, read the moment it was attached, not a guess off the
       File that gets replaced later. Nothing here can fail any more: a
       document that made it into `dokumentListe` already exists. */
    zustand.nachrichten.push({
      id: 'eigen-' + frageKennung,
      role: 'user',
      content: inhalt,
      bild: bilder[0] ?? null,
      anhaenge: bilder.length > 1 ? bilder : null,
      dokument: dokumentListe.length === 1 ? dokumentListe[0] : null,
      dokumente: dokumentListe.length > 1 ? dokumentListe : null,
    })
    runter(true)
    const dokumentIds = dokumentListe.map((dokument) => dokument.id)
    await antwortHolen(inhalt, bilder, dokumentIds, denken, skill, null, gespraech, frageKennung)
    } finally {
      delete zustand.sendet[sendeChat]
    }
  }

  /* A picture made on this machine, from the click to the frame.

     The window is already gone by the time this runs — it shrank away, and
     the work continues here where it can be seen and stopped. The waiting
     message is the SAME one the picture server's mode uses: one waiting
     mark for pictures, whoever draws them.

     The pair in the history is written by the server, so when the picture
     lands there is nothing to assemble — only to catch up. */
  let bildLokalLaeuft = $state(false)
  /* Pictures asked for while one is drawing wait here and run one after the
     other — pressing "draw" three times queues three, it does not throw two
     away. Not $state: only the count in the store drives the badge. One GPU
     draws them serially; the queue stays one shared line regardless of how
     many chats fed it. */
  let bildQueue = []
  /* The wish being drawn right now, or null between wishes — kept out of
     `bildQueue` while it draws (it was shifted off), so the set of chats
     with something in flight has to add it back explicitly. */
  let bildLaufWunsch = null

  /* The count shown is every picture still to come — the one drawing now
     plus the ones queued behind it. The badge appears whenever it is at
     least one and vanishes when the last picture lands. */
  function bildZahlSetzen() {
    zustand.bildWarteschlange = bildQueue.length + (bildLokalLaeuft ? 1 : 0)
  }

  /* Which chats have a picture drawing or waiting, and the ordered size for
     each — rebuilt from the one live wish plus the shared queue whenever
     either changes. A chat drops out the moment it has nothing left in
     flight, the others stay; that is what keeps a filling frame with the
     chat it belongs to instead of the one on screen. */
  function bildChatsAktualisieren() {
    const menge = {}
    const masse = {}
    const merken = (w) => {
      menge[w.chat_id] = true
      masse[w.chat_id] = { breite: w.breite ?? 512, hoehe: w.hoehe ?? 512 }
    }
    for (const w of bildQueue) merken(w)
    if (bildLaufWunsch) merken(bildLaufWunsch)
    zustand.bildLaeuftChat = menge
    zustand.bildMasse = masse
    const entry = (w, running) => ({
      id: w.queue_id, chat_id: w.chat_id, prompt: w.prompt, running,
    })
    // A picture already drawn is no picture to come, even before the
    // chat has caught up with it.
    zustand.pictureQueue = [
      ...(bildLaufWunsch && !bildLaufWunsch.drawn ? [entry(bildLaufWunsch, true)] : []),
      ...bildQueue.map((w) => entry(w, false)),
    ]
  }

  /* The picture drawing now, and only that one — the stop on its tile in
     the picture window's gallery. The line behind it goes on: each waiting
     picture there has its own way out. Only while that very picture is the
     one drawing: the stop names no picture on the server, and a tile that
     had not caught up yet would otherwise stop the next one in line. */
  function stopOnePicture(id) {
    if (bildLaufWunsch?.queue_id === id && !bildLaufWunsch.drawn) {
      api.bildZeichnenStoppen().catch(() => {})
    }
  }

  /* One waiting picture taken out of the line — only a waiting one: the
     one drawing is stopped with its stop. The picture that writes its run's
     question hands that to the next one of the run; a run with nothing
     left of it, neither waiting nor drawing, ends here (it otherwise ends
     with its last picture, see `bildEinesZeichnen`'s `finally`). */
  function removeWaitingPicture(id) {
    const gone = bildQueue.find((w) => w.queue_id === id)
    if (!gone) return
    bildQueue = bildQueue.filter((w) => w !== gone)
    gone.settle(false)
    const run = gone.lauf_kennung
    if (run) {
      const rest = bildQueue.filter((w) => w.lauf_kennung === run)
      if (gone.frage_erstellen !== false && rest.length) rest[0].frage_erstellen = true
      if (!rest.length && bildLaufWunsch?.lauf_kennung !== run) {
        laufFehlerZahl.delete(run)
        if (laufAktuell === run) laufAktuell = null
      }
    }
    bildZahlSetzen()
    bildChatsAktualisieren()
  }

  /* Images per run, honest on screen (Schritt 3c, H2): the ONE lauf_kennung
     the local queue is working through right now, or null between runs.
     The tile row uses this — not a "finished laufs" memory — to tell
     "still filling in" from "genuinely short by one": a memory would only
     live as long as this page does and would have gone quiet on the very
     next reload, which is exactly the reload this house rule exists to
     survive. A historical lauf loaded fresh from the server is never the
     current one, so its shortfall (if any) shows immediately — no waiting
     for a completion event that already happened before this page ever
     loaded. */
  let laufAktuell = $state(null)
  /* How many requests of each in-flight lauf have failed so far — plain
     bookkeeping, not rendered directly, so it does not need to be
     reactive. One picture failing is not reported on its own; the whole
     run reports once, when its own last request finishes. */
  const laufFehlerZahl = new Map()

  /* Counted per page: the id only tells the wishes of this one line apart. */
  let queueCounter = 0
  /* Enqueue and, if nothing is drawing yet, start working the queue off.
     Answers how this one picture ended, once it has: true when it was
     drawn, false when it failed, was stopped or left the line undrawn. */
  function bildLokalZeichnen(wunsch) {
    queueCounter += 1
    let settle
    const outcome = new Promise((resolve) => { settle = resolve })
    bildQueue.push({ ...wunsch, queue_id: queueCounter, settle })
    bildZahlSetzen()
    bildChatsAktualisieren()
    if (!bildLokalLaeuft) workPictureLine()
    return outcome
  }

  async function workPictureLine() {
    bildLokalLaeuft = true
    try {
      while (bildQueue.length) {
        const naechste = bildQueue.shift()
        bildLaufWunsch = naechste
        bildZahlSetzen()
        bildChatsAktualisieren()
        await bildEinesZeichnen(naechste)
        // This wish is done — the chat it drew for drops out of the set
        // unless it still has more of its own waiting in the queue.
        bildLaufWunsch = null
        bildChatsAktualisieren()
        // Said only now: whoever hears it finds the line as it stands
        // without this picture.
        naechste.settle(Boolean(naechste.drawn))
      }
    } finally {
      bildLokalLaeuft = false
      bildLaufWunsch = null
      // Queue is empty here, so this clears the set and the size map.
      bildChatsAktualisieren()
      bildZahlSetzen()
    }
  }

  async function bildEinesZeichnen(wunsch) {
    const chatId = wunsch.chat_id
    const masse = { breite: wunsch.breite ?? 512, hoehe: wunsch.hoehe ?? 512 }
    if (wunsch.lauf_kennung) laufAktuell = wunsch.lauf_kennung
    /* The queue may reach this wish while ANOTHER chat is on screen. Then
       the visible list is a foreign one and gets nothing pushed into it —
       the working message belongs to the drawing chat and comes back
       through chatOeffnen the moment that chat is opened. Without this
       guard the pair appeared in whichever chat happened to be open. */
    let platzhalter = null
    if (zustand.aktiverChat === chatId) {
      /* A chat open that lost its race can leave the list
         tagged for a foreign chat while this one is the one on screen —
         pushing into it would be invisible, hidden by the tag mismatch. */
      if (zustand.nachrichtenChatId !== chatId) nachrichtenSetzen(chatId, [])
      // Images per run: pictures 2+ of a run share the first one's question
      // text on the server (see frage_erstellen), so the local list must not
      // grow a bubble for each of them either — one prompt shown, however
      // many pictures answer it.
      if (wunsch.frage_erstellen !== false) {
        zustand.nachrichten.push({ id: 'eigen-' + Date.now(), role: 'user', content: wunsch.prompt })
      }
      /* IMPORTANT: fetch the object back OUT of the list after the push —
         only the list's copy is reactive. Whoever keeps the raw object writes
         into the void, which is the bug where the picture only appeared after
         switching chats. `bildChatsAktualisieren` above already set
         `zustand.bildMasse[chatId]` to this same `masse` for this wish. */
      zustand.nachrichten.push(bildlaufPlatzhalter(chatId))
      platzhalter = zustand.nachrichten[zustand.nachrichten.length - 1]
      runter(true)
    }
    // Which chats have a picture in flight (and each one's ordered size) is
    // kept by `bildChatsAktualisieren` from the caller — switching away and
    // back reads it to put the working message and its filling frame back,
    // since neither is on the server yet.
    try {
      // The line's own marks stay here; the service takes no field it does
      // not know.
      const { queue_id: _, settle: _settle, ...request } = wunsch
      const antwort = await api.bildZeichnen(request)
      // Drawn: it leaves the line to come at once, not only once the chat
      // has caught up with it.
      wunsch.drawn = true
      bildChatsAktualisieren()
      // The seed the picture was ACTUALLY drawn with — also when the server
      // picked it. The picture window shows it and the seed plan continues
      // from it.
      if (Number.isInteger(antwort?.seed)) seedlage.letzter = antwort.seed
      /* Whoever switched chats meanwhile is looking at a foreign list —
         then touch nothing. The pair lives on the server and shows itself
         the next time the chat is opened. */
      if (zustand.aktiverChat !== chatId) return
      /* The finished picture first lands in the SAME working message: the
         frame stays the same element, so it can grow smoothly from the 75%
         working size to the full display size with the picture inside.
         Only after that little growth does the list reconcile with the
         server — same content, so nothing visibly changes.

         Resolve the working message from the CURRENT list first: leaving
         and re-entering the chat replaces the list and re-creates the
         placeholder, and a write into the discarded object would leave the
         visible one drawing forever. */
      const ziel = zustand.nachrichten.includes(platzhalter)
        ? platzhalter
        : zustand.nachrichten.find((n) => n.bildLaeuft && !n.answerId)
      if (ziel) {
        ziel.bildMasse = ziel.bildMasse ?? masse
        ziel.bildLaeuft = false
        // Images per run (Weg A): the server writes every picture of a
        // lauf into the SAME one row — the local, not-yet-reconciled view
        // follows that here instead of growing a standalone bubble per
        // picture. The run's own FIRST picture still grows in place as an
        // ordinary single-picture frame (no `bilder` yet, so `bildKacheln`
        // leaves it alone) — only from the SECOND picture on is there
        // already a shared row to fold into, and this working placeholder
        // then joins it instead of standing next to it as its own bubble.
        //
        // The row it looks for is normally the SERVER's — pictures are
        // drawn strictly one after the other, and each one's own reconcile
        // 700ms later replaces the list before the next begins. So this
        // asks for the run id the way the server sends it (`lauf_id`, via
        // `laufKennung`), and the two writes below hand the placeholder the
        // same field rather than the retired `stats.lauf` — a row the
        // window builds itself must be shaped like the row that replaces
        // it, or the next picture fails to recognise its own run and opens
        // a second tile wall beside the first.
        if (wunsch.lauf_kennung) {
          const geteilt = zustand.nachrichten.find(
            (n) => n !== ziel && n.role === 'assistant' && laufKennung(n) === wunsch.lauf_kennung,
          )
          if (geteilt) {
            geteilt.bilder = geteilt.bilder ?? new Array(wunsch.von).fill(null)
            geteilt.bilder[wunsch.nr - 1] = antwort.bild
            const seeds = geteilt.stats?.seeds ?? new Array(wunsch.von).fill(null)
            seeds[wunsch.nr - 1] = antwort.seed
            geteilt.lauf_id = wunsch.lauf_kennung
            geteilt.stats = { ...geteilt.stats, von: wunsch.von, seeds }
            const stelle = zustand.nachrichten.indexOf(ziel)
            if (stelle !== -1) zustand.nachrichten.splice(stelle, 1)
          } else {
            ziel.bilder = new Array(wunsch.von).fill(null)
            ziel.bilder[wunsch.nr - 1] = antwort.bild
            const seeds = new Array(wunsch.von).fill(null)
            seeds[wunsch.nr - 1] = antwort.seed
            ziel.lauf_id = wunsch.lauf_kennung
            ziel.stats = { von: wunsch.von, seeds }
          }
        } else {
          ziel.bild = antwort.bild
          ziel.stats = { ...ziel.stats, seed: antwort.seed }
        }
      }
      /* Glued to the floor for the growth's length: the frame's bottom
         stands, its top rises — the growth reads upward. */
      runterGleiten()
      /* From here on the picture is drawn and on screen. A reconcile that
         fails must not take it away again — the server has the pair, and
         the list heals on the next chat open. */
      try {
        await new Promise((frei) => setTimeout(frei, 700))
        if (zustand.aktiverChat !== chatId) return
        // The question bubble of a send still on its way — the same rescue
        // `chatOeffnen` runs before it replaces the list, missing here
        // until now: a question sent while this picture was still drawing
        // vanished until the upload finished.
        const eigeneZeilen = eigeneZeilenSichern(chatId)
        // Only the messages matter here — a picture finishing is not a text
        // run resuming, `laufend` (if any) is for chatOeffnen to act on.
        const frischeNachrichten = (await api.nachrichten(chatId)).nachrichten
        /* The user can have switched to and successfully opened a different
           chat during this fetch — that chat's own, already-correct list
           must not be overwritten by this one arriving late. */
        if (zustand.aktiverChat !== chatId) return
        nachrichtenSetzen(chatId, frischeNachrichten)
        /* But a text answer may be streaming into this same chat right now:
           sending is deliberately allowed while a picture is being drawn
           (Eingabeleiste.svelte). Replacing the list drops the object the
           stream writes into — the answer stops growing on screen, and the
           server row that takes its place still says `zustand: 'laeuft'`,
           which nothing in this window would ever clear again. The bubble
           then carries a waiting mark for the rest of the session and the
           context bar reads that frozen row.

           `chatOeffnen` puts the placeholder back for exactly this reason
           (zustand.svelte.js). The same rescue belongs here, because the
           same thing was replaced. Matched by identity first and by id
           second, like over there: the id is only there once the run's
           `start` event has arrived. */
        const meiner = zustand.laufenderPlatzhalter[chatId]
        if (zustand.laeuft[chatId] && meiner) {
          const stelle = zustand.nachrichten.findIndex(
            (n) => n === meiner || (meiner.id != null && n.id === meiner.id),
          )
          if (stelle === -1) zustand.nachrichten.push(meiner)
          else if (zustand.nachrichten[stelle] !== meiner) {
            zustand.nachrichten[stelle] = meiner
          }
        }
        eigeneZeilenZurueckgeben(eigeneZeilen)
        /* The server's copy of the message does not know the ordered size.
           Hand it over, so the sized stage stays after the reconcile and the
           picture keeps its exact geometry — a natural-size re-render would
           reflow on image load and yank the view away from the picture.
           For a run this sizes the WHOLE shared row's message once, not
           per tile — the individual tiles are synthetic views built fresh
           from it on every render (see `bildKacheln`).

           The list searched here is the one the fetch above just put in
           place, so the row to hand the size to is the SERVER's — which is
           why this lookup, alone among the six, could never have limped
           along on a local row still carrying the old key. Failing to find
           it costs precisely what this comment promises to prevent. */
        const frisch = wunsch.lauf_kennung
          ? zustand.nachrichten.find(
              (n) => n.role === 'assistant' && laufKennung(n) === wunsch.lauf_kennung,
            )
          : [...zustand.nachrichten].reverse()
              .find((n) => n.role === 'assistant' && n.bild === antwort.bild)
        if (frisch) frisch.bildMasse = masse
        /* A short glide, not one snap: the reconciled message renders its
           stats foot a frame later, and a single snap lands just above the
           true floor. */
        runterGleiten(300)
        await chatsLaden()
      } catch {
        /* the picture stands; the fresh list arrives with the next open */
      }
    } catch (fehler) {
      if (zustand.aktiverChat === chatId) {
        /* The visible placeholder may be a re-created twin of the captured
           one (chat left and re-entered) — remove whichever still claims to
           be drawing, or a dust frame stands in the chat forever. */
        const stelle = zustand.nachrichten.findIndex(
          (n) => n === platzhalter || (n.bildLaeuft && n.id === null),
        )
        if (stelle !== -1) zustand.nachrichten.splice(stelle, 1)
      }
      /* A stopped picture is not an error. It is what was just asked for,
         and the working message disappearing IS the answer. */
      if (fehler.status !== 499) {
        if (wunsch.lauf_kennung) {
          // Images per run: one picture failing is not news on its own —
          // the run's own last request (below) reports once for however
          // many failed, not once per failure.
          laufFehlerZahl.set(wunsch.lauf_kennung, (laufFehlerZahl.get(wunsch.lauf_kennung) ?? 0) + 1)
        } else {
          melde(String(fehler.message || fehler), 'fehler')
        }
      }
    } finally {
      // Images per run: the request carrying the run's own last position
      // is the one point that always runs, whichever pictures around it
      // succeeded or failed — the run is done exactly when it finishes,
      // never before. That is what lets the tile row tell "still filling
      // in" from "genuinely short by one": while laufAktuell still names
      // this lauf, its shortfall is not shown yet; clearing it here is
      // what un-hides a real gap.
      // The last picture left of its run ends it — by position, or
      // because the ones after it were taken out of the line.
      const lauf = wunsch.lauf_kennung
      if (lauf && (wunsch.nr === wunsch.von || !bildQueue.some((w) => w.lauf_kennung === lauf))) {
        // C5 (Aufseher): the SAME shortfall count exists twice — here,
        // computed from the in-flight request queue at the moment the
        // run's own last request finishes, and again in `teilausfall`,
        // computed from the saved message's own `bilder` once the run
        // is reloaded from the server. They cannot share one
        // computation (this one only knows the wish that was sent,
        // `teilausfall` only knows the row that was stored) — kept in
        // step by comment, not by one shared source, so a change to
        // either one's arithmetic is a prompt to check the other.
        const gescheitert = laufFehlerZahl.get(wunsch.lauf_kennung) ?? 0
        laufFehlerZahl.delete(wunsch.lauf_kennung)
        if (gescheitert > 0) {
          meldeText('bild.lauf_teilweise', { gescheitert, von: wunsch.von }, 'fehler')
        }
        if (laufAktuell === wunsch.lauf_kennung) laufAktuell = null
      }
    }
  }

  /* A picture the model draws while it answers (`draw_image`) goes the
     picture window's way on screen too: the same working tile while it is
     drawn, and the same run row its finished pictures stand in. The server
     writes that row itself, the answer's id is its run, and every result of
     a drawing call hands the row over as it stands (`bildlauf`) — so the
     window only puts it in place, it never builds a row of its own. Only
     on the drawing chat's own list: another chat's gets nothing, the row
     is on the server and comes with the next open. */
  function drawingStarted(chatId, answerId) {
    if (zustand.aktiverChat !== chatId || zustand.nachrichtenChatId !== chatId) return
    if (!zustand.nachrichten.some((n) => n.answerId === answerId)) {
      zustand.nachrichten.push(answerDrawingTile(chatId, answerId))
    }
    // The tile joins this answer's run as its next cell once the run has a
    // row — unless the picture window's queue is working through a run of
    // its own, which keeps the current one.
    if (!bildLokalLaeuft) laufAktuell = answerId
  }

  function drawingDone(chatId, answerId, row) {
    if (laufAktuell === answerId) laufAktuell = null
    if (zustand.aktiverChat !== chatId || zustand.nachrichtenChatId !== chatId) return
    const list = zustand.nachrichten
    const tile = list.findIndex((n) => n.answerId === answerId)
    const there = row ? list.findIndex((n) => n.id === row.id) : -1
    if (row && there !== -1) {
      list[there] = row
      if (tile !== -1) list.splice(tile, 1)
    } else if (row && tile !== -1) {
      // The run's first picture: its row takes the tile's place.
      list[tile] = row
    } else if (row) {
      list.push(row)
    } else if (tile !== -1) {
      list.splice(tile, 1)
    }
  }

  /* The stop button of image generation: tells the server, which
     interrupts the generator — the waiting request above resolves itself
     as a result. */
  function bildStoppen() {
    // Cancel everything, not only the one drawing: the queued ones were
    // asked for by the same hand and stopping means stopping.
    for (const waiting of bildQueue) waiting.settle(false)
    bildQueue = []
    bildZahlSetzen()
    // The queued chats drop from the set right away; the one still drawing
    // stays until its stopped request resolves and the loop's finally runs.
    bildChatsAktualisieren()
    // C4 (Aufseher): `laufAktuell` and `laufFehlerZahl` are otherwise
    // cleared only by the run's OWN last request finishing
    // (`bildEinesZeichnen`'s `finally`) or by `removeWaitingPicture`
    // taking the last one left — a stop mid-run means that
    // request never happens, so a run stopped at picture 5 of 8 left
    // `laufAktuell` stuck naming it. `teilausfall` reads that as "still
    // being drawn" and stays silent about the three that never came,
    // exactly the shortfall B15 exists to report, until either a NEW
    // run overwrites the same one value or a reload starts fresh.
    // Cleared here instead of waiting on either.
    laufAktuell = null
    laufFehlerZahl.clear()
    if (bildLokalLaeuft) api.bildZeichnenStoppen().catch(() => {})
  }

  /* Regenerate the answer (3.4): delete the old one and recompute on the
     remaining history, without sending the question again. */
  async function neuErzeugen(messageId) {
    if (laufVon(zustand.aktiverChat)) {
      melde(t('eingabe.laeuft_schon'))
      return
    }
    // Checked before the old answer is deleted: a switched-off model gives no
    // new one, so the old one stays.
    if (chosenModelOff()) return
    try {
      await api.nachrichtLoeschen(zustand.aktiverChat, messageId)
    } catch {
      melde(t('nachricht.nicht_entfernt'), 'fehler')
      return
    }
    const stelle = zustand.nachrichten.findIndex((n) => n.id === messageId)
    if (stelle !== -1) zustand.nachrichten.splice(stelle, 1)
    await antwortHolen(null)
  }

  /* The queue moves on: whenever nothing is running, the open chat gets
     the next message waiting in it.

     Deliberately NOT awaited by its caller: the next send starts a run of
     its own, and awaiting it would nest one run inside the last one's
     stack for as long as the queue is.

     It always asks about the OPEN chat, never about the one whose run just
     ended. `senden` writes into the open history, so firing into a
     conversation nobody is looking at would put the bubble in the wrong
     place — and asking about the finished chat instead would leave a queue
     standing forever in the case that matters most: a run started in one
     chat, a message typed in another, and no switch afterwards to wake
     anything up. */
  function warteschlangeWeiter() {
    const chatId = zustand.aktiverChat
    // Only THIS chat blocks its own queue now — a run in another chat does
    // not hold it back.
    if (!chatId || laufVon(chatId) || zustand.sendet[chatId] || haelt(chatId)) return
    // A switched-off model holds the queue too: the message stays in line
    // and goes once a model that is on is chosen (the queue's effect wakes
    // on that switch).
    if (chosenModelOff()) return
    const eintrag = ausreihen(chatId)
    if (!eintrag) return
    senden(eintrag.inhalt, eintrag.bilder, eintrag.dokumente, eintrag.denken, eintrag.skill)
  }

  /* The button on a held bubble. Sending by hand is also the answer to
     "and now?": the hold is lifted, and from here the line runs by itself
     again. */
  function warteschlangeLosschicken(eintrag) {
    // The same claim the queue and the input bar ask about: a send whose
    // pictures are still uploading holds the chat without a run to show,
    // and a second send into it took the first one's mark down with it.
    if (laufVon(eintrag.chatId) || zustand.sendet[eintrag.chatId]) return
    // A switched-off model: the entry stays in line instead of being taken
    // out and then not sent.
    if (chosenModelOff()) return
    entfernen(eintrag.id)
    loesen(eintrag.chatId)
    senden(eintrag.inhalt, eintrag.bilder, eintrag.dokumente, eintrag.denken, eintrag.skill)
  }

  /* `wiederanhang` (shape: { generationId, ab }) turns this into a resume
     instead of a new answer — used only by antwortWiederAnhaengen below.
     Everything past the very first stream source is shared: a resumed run
     drops and reconnects exactly like a freshly started one, through the
     same catch block a few lines down. */
  async function antwortHolen(
    inhalt, bilder = null, dokumente = null, denken = null, skill = null, wiederanhang = null,
    gespraech = false, nachrichtId = null,
  ) {
    /* The chat this run belongs to, fixed for its whole life. A fresh send
       and a visible reattachment both start with that chat on screen, so
       this is `aktiverChat` at entry — captured now because the user may
       switch away long before the run ends, and every place below that
       used to read `zustand.laeuft?.chatId ?? zustand.aktiverChat` means
       exactly this chat. */
    const zielChat = wiederanhang ? wiederanhang.chatId : zustand.aktiverChat

    /* A plain object is enough: as soon as it lies in a reactive list, it
       becomes reactive itself. Changes to it during streaming thus land
       in the window on their own. */
    /* Reattaching after a reload: the answer's row ALREADY stands in the
       list. The server writes it the moment the run starts
       (api/v1/generierung.py) and keeps it up to date WHILE the run goes,
       so `chatOeffnen`'s fetch from /messages brings it along — half
       written. Pushing a second placeholder here would put that one answer
       on screen twice: the stored half standing above the one growing out
       of the replayed stream.

       So on a resume that row is adopted instead — BY ITS ID, which the
       server now hands over with the run itself (`LaufendeGenerierung`).

       It used to be deduced, and that is what went wrong: the last row of
       the chat, of role assistant, whose stats carried no `abgebrochen`.
       The reasoning was that nothing is appended while a run lives, so the
       answer is necessarily last. Three writers append during a run — a
       finished background command, a picture from the picture window, a
       run's own picture row — and each of them matched all three tests.
       The wrong row was then adopted, blanked, and filled with the replayed
       stream, while the real answer stood untouched above it. The same text
       twice, and once more for every further reattach.

       Nothing is deduced any more: no id, no adoption. A row that cannot be
       found is not a candidate to guess at — the placeholder below is
       pushed instead, which is the same thing that happens for a run this
       window started itself.

       What IS adopted gets CLEARED, not kept: the stream is replayed from
       its very first event and delivers all of it again. The stored half is
       there for the case with no stream left to replay — a service that
       died in the middle of the run. */
    const uebernehmen = wiederanhang?.messageId
      ? zustand.nachrichten.find((n) => n.id === wiederanhang.messageId) ?? null
      : null
    if (uebernehmen) {
      uebernehmen.content = ''
      uebernehmen.reasoning = ''
      uebernehmen.werkzeuge = []
      uebernehmen.stats = {}
      uebernehmen.abschnitte = []
      uebernehmen.vision = wiederanhang ? frageTrugBild(uebernehmen) : Boolean(bilder?.length)
      taetigkeitSetzen(uebernehmen, 'kontext', undefined, true)
      uebernehmen.ziel = null
      /* Cleared too, and this one matters most: the row came from the
         server carrying `zustand: 'laeuft'`, and NOTHING in this window
         ever writes that field. Left standing, the bubble kept drawing
         itself as a running answer long after the run had ended — the
         waiting mark and its clock going, and the truncation notice
         suppressed, because that one is gated on `!laeuft`. The run this
         window is holding is known from `laufenderPlatzhalter` instead,
         which is cleared when it ends. */
      uebernehmen.zustand = null
      /* Cleared like the rest, and for the same reason: the replay hands out
         every `kontext` event of the run again, so it refills at once. Kept
         instead, a reading from before a compaction would stand as the
         current one until the next event happened to arrive. */
      uebernehmen.gesamt_tokens = null
    }
    if (!uebernehmen) zustand.nachrichten.push({
      // Stable key, same reason as the picture placeholder's `bildlauf-`
      // (see zustand.svelte.js): a message keyed by its POSITION is the
      // same message as whatever stood there before it. One running answer
      // per chat, so the chat's id is enough to tell them apart.
      id: `platzhalter-${zielChat}`,
      role: 'assistant', content: '', reasoning: '', stats: {}, werkzeuge: [],
      /* How full the context is, refilled by the `kontext` event below as
         the answer runs. Declared here for the same reason `ziel` is: the
         answer should start out plainly saying that nothing has been
         reported yet, rather than gaining the field halfway through. */
      gesamt_tokens: null,
      /* The reported goal, once the `goal` tool has named one (the SSE
         event `ziel` below). Declared here rather than only being set
         later, so the answer starts out saying plainly that nothing has
         been reported yet. */
      ziel: null,
      /* The live readings of the running round — set from the stream,
         ended by `lesungenLeeren`. Declared here like `ziel` above, so the
         answer starts out plainly saying that nothing has been reported
         yet. */
      liveSpeed: null,
      liveShare: null,
      /* The order things actually happened in. `content`, `reasoning` and
         `werkzeuge` above stay exactly as they were — they are the STORE,
         read by the stats foot, the copy button and the server reconcile.
         This list is the ORDER, and only that: each entry says which kind
         came next, so a second thinking block after a first paragraph is
         drawn where it happened instead of being folded back into the one
         reasoning string at the top.
         A message without it (every chat loaded from the server) falls back
         to the old fixed order in Nachricht.svelte — old chats must not
         change. */
      abschnitte: [],
      /* If the question carried an image, the waiting line shows the eye
         mark — image recognition is recognizable as its own state. Not
         guessed from `bilder` alone: a row pushed for a REATTACH has no
         send of its own to ask, and the question it answers is the last one
         in the list. */
      vision: wiederanhang ? frageTrugBild(null) : Boolean(bilder?.length),
      /* What the run is doing right now: 'kontext' right after sending and
         again after every tool result, 'denkt', 'werkzeug', 'schreibt' as
         the stream says. `taetigkeitSeit` is when the present activity
         began — the waiting mark's clock counts from it (laufMarke). */
      taetigkeit: 'kontext',
      taetigkeitSeit: Date.now(),
    })
    const platzhalter = uebernehmen ?? zustand.nachrichten[zustand.nachrichten.length - 1]
    /* Held here too, not just in the message list: switching chats while
       this runs replaces `zustand.nachrichten` wholesale with the server's
       fetch (zustand.svelte.js, chatOeffnen) — losing the array entry, but
       not this reference. chatOeffnen puts the SAME object back when
       reopening the chat this run belongs to, same as bildLaeuftChat
       already does for a running picture. Keyed by chat so a second run in
       another chat keeps its own placeholder. */
    zustand.laufenderPlatzhalter[zielChat] = platzhalter

    /* Text lands in the section that is already open, or opens a new one.
       Two thinking passes separated by a paragraph therefore stay two
       sections — which is the whole point — while one uninterrupted pass
       stays one, however many chunks it arrived in. */
    const textAnhaengen = (art, text, zeitpunktMs) => {
      const letzter = platzhalter.abschnitte[platzhalter.abschnitte.length - 1]
      if (letzter && letzter.art === art) {
        letzter.text += text
        // Thinking that goes on after a passing event is still one stretch.
        delete letzter.endedAt
      } else platzhalter.abschnitte.push({ art, text, seit: zeitpunktMs ?? Date.now() })
    }
    /* A thinking stretch ends with the first event that is not thinking,
       at that event's own time — not when the next section opens. A tool
       confirmation opens no section, and a stretch measured up to the next
       one counted the whole wait on the person as thinking. */
    const endThinking = (zeitpunktMs) => {
      const letzter = platzhalter.abschnitte[platzhalter.abschnitte.length - 1]
      if (letzter?.art === 'reasoning' && letzter.endedAt == null) {
        letzter.endedAt = zeitpunktMs ?? Date.now()
      }
    }
    /* A tool is referenced by its call id, never by the object: the entry in
       `werkzeuge` is filled in later by tool_result, and a copy taken here
       would keep showing the empty result. */
    const werkzeugAnhaengen = (aufrufId, zeitpunktMs) => {
      platzhalter.abschnitte.push({ art: 'werkzeug', aufruf_id: aufrufId, seit: zeitpunktMs ?? Date.now() })
    }
    /* A call has its row from the moment the model begins to write it, not
       only once it is complete: a long argument takes the model a minute,
       and all that while the answer showed a waiting word and no call.

       Such a row is a section without a call id — the id only exists once
       the call is complete — that says under `writing` which call of the
       round it is, its name and how many characters of it are written. The
       complete call takes the row over (`rowOfCall`), so it is one row from
       the first character to the result. */
    const dropRows = (which) => {
      if (platzhalter.abschnitte.some(which)) {
        platzhalter.abschnitte = platzhalter.abschnitte.filter((a) => !which(a))
      }
    }
    /* Whether rows stand that are written out and wait for their turn. A
       round that was cut off answers only the call it was cut at; the rows
       of its other calls never begin. They go the moment the model writes
       or thinks again — only then is it certain their turn will not come. */
    let rowsWaiting = false
    const modelGoesOn = () => {
      if (!rowsWaiting) return
      rowsWaiting = false
      dropRows((a) => a.writing?.written === null)
    }
    const callBeingWritten = (index, name, written, zeitpunktMs) => {
      modelGoesOn()
      const row = platzhalter.abschnitte.find((a) => a.writing?.index === index)
      if (row) row.writing = { index, name, written }
      else {
        platzhalter.abschnitte.push({
          art: 'werkzeug',
          aufruf_id: null,
          writing: { index, name, written },
          seit: zeitpunktMs ?? Date.now(),
        })
        runter()
      }
    }
    /* A complete call says the round's stream has ended, so every call of
       the round is written: the rows still waiting for their turn stop
       counting and keep their name. The call takes the row it was written
       in — the first of its name, calls begin in the order they were
       written. Handed back, or nothing for a call that was never reported
       while it was written. */
    const writtenRow = (aufrufId, name) => {
      for (const a of platzhalter.abschnitte) if (a.writing) a.writing.written = null
      const row = platzhalter.abschnitte.find((a) => a.writing?.name === name)
      if (row) {
        row.aufruf_id = aufrufId
        delete row.writing
      }
      rowsWaiting = platzhalter.abschnitte.some((a) => a.writing)
      return row
    }
    // The row of a call that is complete: the one it was written in, or a
    // new one at the end, as before.
    const rowOfCall = (aufrufId, name, zeitpunktMs) => {
      if (!writtenRow(aufrufId, name)) werkzeugAnhaengen(aufrufId, zeitpunktMs)
    }
    /* The run is over. A call still being written never became a call, and
       one that got its row at its permission question (`asked`) and was
       never answered never ran: their rows go, no half row stays. */
    const dropRowsNeverBegun = () => {
      for (const row of platzhalter.abschnitte.filter((a) => a.asked)) {
        const at = platzhalter.werkzeuge.findLastIndex(
          (w) => w.aufruf_id === row.aufruf_id && w.ergebnis === null,
        )
        if (at >= 0) platzhalter.werkzeuge.splice(at, 1)
      }
      dropRows((a) => a.writing || a.asked)
    }
    /* A question of this run that is settled comes down — keyed by call id,
       so only the one that was actually answered goes. */
    const frageAbnehmen = (aufrufId, ...kaesten) => {
      for (const kasten of kaesten) if (kasten[zielChat]?.aufrufId === aufrufId) delete kasten[zielChat]
    }

    /* ONE notice for the whole answer, rewritten as the work moves on.

       It used to be one per call and one per phase: a notice while the model
       was still typing the arguments, that one CLOSED and a second opened
       the moment the call really started, and a third state when the result
       came back. Two tools were six notices appearing and vanishing in a few
       seconds — and with three the most that stand at once, the stack shoved
       itself through the whole time.

       Rewriting was already how the result was reported; it simply was not
       used for the step before it. Now nothing is closed and reopened:
         write_file wird geschrieben → write_file … → write_file fertig
       and the next call continues in the same notice.

       Keyed per CHAT, not per call: two chats can run at once and each
       deserves its own line, but within one answer there is one. */
    const werkzeugToast = `werkzeug:${zielChat}`
    /* `dauer` is for the one state that may not keep the kind's own clock:
       zero everywhere else, so nothing but the caller that asks for it is
       touched. Handed to both paths below, because a notice that was pushed
       out and rebuilt has to stand exactly as long as one that was
       rewritten — otherwise the same event lasts two different times by a
       circumstance nobody can see. */
    const werkzeugSagen = (pfad, werte, art, dauerhaft, dauer = 0) => {
      const vorhanden = werkzeugMeldungen.get(werkzeugToast)
      if (
        vorhanden
        && aktualisiereMeldung(vorhanden, {
          text: t(pfad, werte), art, dauerhaft, dauer,
          schluessel: pfad, werte, werkzeug: werte.name ?? '',
        })
      ) return
      /* Nothing to rewrite — either the first call of this answer, or the
         notice was pushed out by newer ones. Either way a fresh one, and the
         key points at it from here on.

         Silent, always. A rewrite never rings, so without this a failed tool
         would ring only when its notice happened to have been pushed out —
         the same event sounding or not by a circumstance that has nothing to
         do with it. The chat's own failure sound is unaffected; this is the
         running commentary of one answer, and a commentary does not ring. */
      werkzeugMeldungen.set(
        werkzeugToast,
        meldeText(pfad, werte, art, {
          dauerhaft, dauer, werkzeug: werte.name ?? '', stumm: true,
        }),
      )
    }

    const abbruch = new AbortController()
    /* The local handle every branch below writes through and reads from —
       `zustand.laeuft[zielChat]` is the same object, but going through a
       local reference keeps a chat switch (which cannot touch this closure)
       from ever pointing these reads at another chat's run. */
    const lauf = {
      abbruch, generationId: wiederanhang?.generationId ?? null, chatId: zielChat,
    }
    zustand.laeuft[zielChat] = lauf
    /* Carries this answer's files into the rail: the first sight of a file
       opens its tab, every later one only follows it (tabWriter).

       A file is a fresh occasion for the rail — but only in the
       conversation the reader is actually in. A run finishing in the
       background must not reach over and open a panel on somebody else's
       chat, which is what clearing the dismissal unconditionally did. */
    const carryFile = tabWriter(zielChat, () => {
      const onScreen = zielChat === zustand.aktiverChat
      if (onScreen && leiste.nichtAufdraengen === 'vorschau') leiste.nichtAufdraengen = ''
      return onScreen
    })
    /* Whether a file is being written right now, and whether the text
       ended in a fence that was not settled yet — what lets the next piece
       of plain text be told apart from one that needs a look at all. */
    let fileGrowing = false
    let fenceUnsettled = false
    let abgebrochen = false
    /* Whether this run ended cleanly decides whether the queue moves on.
       A stream-level error counts as failed even when text had already
       arrived: what comes after it is half an answer, and the next message
       would be asked against a state nobody has looked at. */
    let gescheitert = false
    /* The service already holds this chat — an answer it started by itself
       is going. Not a failure of this send: the words go back into the
       field, the bubble comes down, and the window attaches to the run
       that is really going. */
    let belegt = false
    /* Whether a drawing call of this run is going: its working tile goes
       with the run when the run ends without the call's result (stopped,
       or the line broke). */
    let drawing = false
    /* The id of a summary this run folded, or null. Only the server knows:
       the fold happens before the stream opens, so nothing on screen would
       otherwise change until the chat is reopened. */
    let verdichtetZu = null
    /* Whether this answer's running tool notice is still standing on its own
       clock — set while the model is writing the call or the call itself is
       going, cleared the moment a result rewrites it into "fertig" or
       "fehlgeschlagen". Read in the `finally` below: a notice still open
       here means the answer ended with no result ever arriving for it. */
    let werkzeugOffen = false
    /* The notice that said "is being written" is out of date once the call is
       complete and asks for an answer — a permission, a question, a job to
       confirm. It comes down, and the card over the chat is what says
       "waiting". Only while it is still that notice: after a finished tool it
       is the "done" line running its own clock down. */
    function schreibendeMeldungSchliessen() {
      if (!werkzeugOffen) return
      const schreibend = werkzeugMeldungen.get(werkzeugToast)
      if (schreibend) schliesseMeldung(schreibend)
      werkzeugMeldungen.delete(werkzeugToast)
      werkzeugOffen = false
    }
    let schlussZustand = null
    let fremderLauf = null
    let heldWithoutRun = false
    /* Whether the stored row has to be fetched instead of replayed: a
       reattach the service refused, or a run it no longer knows. Both leave
       the window with a row and no stream behind it, and without the fetch
       that row stood empty ("nothing written") until the chat was opened
       again. Read once, in the reconcile at the foot of this `finally` —
       the one place allowed to replace the list. */
    let zeileNachladen = false

    /* A question about the run, bounded by the reconcile's deadline and
       still ended by the person's stop. Its running out is a TimeoutError,
       not an AbortError: the wait is over, nobody pressed stop. */
    function withDeadline(signal) {
      const deadline = AbortSignal.timeout(NACHLADE_FRIST_MS)
      if (!signal) return deadline
      // An engine without `AbortSignal.any` keeps the stop and goes without
      // the deadline, rather than failing every question.
      return typeof AbortSignal.any === 'function' ? AbortSignal.any([signal, deadline]) : signal
    }

    /* A pause that the person's stop cuts short. The stop's listener goes
       when the clock wins, so a wait of minutes does not pile one up on
       the signal for every tick. */
    function pauseOrStop(ms, signal) {
      if (signal?.aborted) return Promise.resolve()
      return new Promise((done) => {
        const clock = setTimeout(() => {
          signal?.removeEventListener('abort', onStop)
          done()
        }, ms)
        const onStop = () => {
          clearTimeout(clock)
          done()
        }
        signal?.addEventListener('abort', onStop, { once: true })
      })
    }

    /* Asks about the chat until a claim on it turns into a run or goes.
       Gives back the run the service names (`run`), or none — the chat is
       free — and whether the service answered at all (`reachable`). No
       clock of its own: a claim is released on every way out of the setup
       (app/generationen.py, `freigeben`), a service that stops answering
       ends the asking too, and every single question has the reconcile's
       deadline, so a proxy that holds one open cannot hold the chat with
       it. One row, not the whole page: the two flags this asks about are
       computed beside the page, and the page itself costs a JSON parse per
       row, a document lookup per document message and a count over the
       chat — twice a second, for a fold that lasts minutes
       (app/api/v1/chats.py, nachrichten_auflisten). */
    async function claimOutcome(chatId, signal) {
      while (true) {
        let answer
        try {
          answer = await api.nachrichten(chatId, { signal: withDeadline(signal), limit: 1 })
        } catch {
          return { run: null, reachable: false }
        }
        if (answer?.laufend?.generation_id) return { run: answer.laufend, reachable: true }
        if (!answer?.gehalten) return { run: null, reachable: true }
        /* Woken by the stop, not only by the clock: a wait that outlives
           the person's own stop would hold the chat with no run behind it
           (the next question then throws, and the asking ends). */
        await pauseOrStop(HALTEPRUEFUNG_MS, signal)
      }
    }

    /* Where the answer of a line that broke too early went. Broken BEFORE
       the service named the run, there is no id to reattach to — this is
       the stretch in which the service folds the history, and a fold costs
       a whole model request, seconds to minutes (app/chatverdichtung.py).
       Calling that a failed send was the defect: the answer came anyway,
       into a chat whose window had already written it off, and the stopped
       or broken send was drawn as failed while the service was still
       working.

       Asking about the chat answers one of three things, and each has its
       own way out: a run — "run", and the caller attaches to it from the
       first event, nothing of it has been seen here; a held chat with no
       run yet — wait, and ask again; neither — the run began and ended
       between two questions, or never began: the stored history decides.
       This send's own question stored with an answer behind it — "stored",
       and the stored history is fetched instead of a stream, with whatever
       the run left behind it and the state it ended in (the way
       `weiterZusehen` lets a run it lost stand); the question missing — the
       send never arrived — or stored with no answer behind it — the run
       broke after it stored the question (a fold that threw, a line that
       went) — and the caller fails it (false), which also holds the queue.
       Only an answer counts: a tool report or a fold's summary between the
       two is no answer to the question. The asking itself is
       `claimOutcome`'s. */
    async function nachholen(laufJetzt, chatId, signal) {
      const { run, reachable } = await claimOutcome(chatId, signal)
      if (!reachable) return false
      if (run) {
        laufJetzt.generationId = run.generation_id
        return 'run'
      }
      if (!nachrichtId) return false
      /* The newest rows, oldest first: is this send's question among them?
         Fifty leave room for a run that filed its pictures as rows of their
         own behind it. */
      let recent
      try {
        recent = await api.nachrichten(chatId, { signal: withDeadline(signal), limit: 50 })
      } catch {
        return false
      }
      const reihe = recent?.nachrichten ?? []
      const stelle = reihe.findIndex((n) => n.id === nachrichtId)
      if (stelle < 0) return false
      const beantwortet = reihe
        .slice(stelle + 1)
        .some((n) => n.role === 'assistant' && (n.art ?? 'nachricht') === 'nachricht')
      if (!beantwortet) return false
      zeileNachladen = true
      return 'stored'
    }

    try {
      const koerper = { chat_id: zielChat, endpoint_id: zustand.modellId }
      if (inhalt) koerper.content = inhalt
      // Names the row the service is about to store, before it stores it —
      // see `frageKennung` in senden() for why.
      if (nachrichtId) koerper.nachricht_id = nachrichtId
      if (bilder?.length) koerper.bilder = bilder
      if (dokumente?.length) koerper.dokumente = dokumente
      /* The thinking stage, as the key it is ("off", "low", "high" ...).
         Only sent when there is one: a model with nothing to set sends
         nothing, and the server keeps its own default. */
      if (typeof denken === 'string' && denken) koerper.thinking = denken
      // A picked skill: the service puts its instruction in front of this
      // message and keeps it with the message (app/verlaufsbau.py).
      if (skill) koerper.skill = skill
      // The spoken side of a live conversation — turns on the conversation
      // instruction server-side (app/verlaufsbau.py), never a typed chat.
      if (gespraech) koerper.gespraech = true
      // The user cut the previous spoken answer short: one line for the
      // model in this request only (app/diktatsprachewahl.py).
      if (gespraech?.unterbrochen) koerper.unterbrochen = true

      /* Counts every event actually handled — the position to resume from
         if the connection itself drops (below), not a byte offset. */
      let ereignisZahl = 0
      const ereignisVerarbeiten = async (strom) => {
      for await (const ereignis of strom) {
        ereignisZahl++
        // The speed reading arrives while the model thinks; it is no end.
        if (ereignis.typ !== 'reasoning' && ereignis.typ !== 'denktempo') {
          endThinking(ereignis.zeitpunkt_ms)
        }
        // The model thinks or writes again: the round before is over.
        if (ereignis.typ === 'reasoning' || ereignis.typ === 'content') modelGoesOn()
        if (ereignis.typ === 'start') {
          lauf.generationId = ereignis.generation_id
          platzhalter.id = ereignis.message_id
          /* The stream opens once the fold before it is over; a
             "compressing" the program's line put on this row has said its
             piece. Plain content sets no activity of its own, so it is
             taken back here rather than left standing under the answer. */
          if (platzhalter.taetigkeit === 'verdichtung') platzhalter.taetigkeit = 'kontext'
          /* The very first `kontext` stretch, before any tool result has
             set it its own way below: a reattach otherwise left it at the
             moment of the reload (set above, before this loop even starts),
             not at the moment the round actually began. */
          if (ereignis.zeitpunkt_ms != null) platzhalter.taetigkeitSeit = ereignis.zeitpunkt_ms
        } else if (ereignis.typ === 'reasoning') {
          /* The reasoning text itself carries no speed of its own — a
             separate `denktempo` event does that, only when the server
             actually names one. */
          platzhalter.reasoning += ereignis.text
          textAnhaengen('reasoning', ereignis.text, ereignis.zeitpunkt_ms)
          taetigkeitSetzen(platzhalter, 'denkt', ereignis.zeitpunkt_ms)
          runter()
        } else if (ereignis.typ === 'denktempo') {
          /* The server's own reading of how fast it is producing right now,
             while it thinks and while it writes the answer. It stands under
             the running answer (Nachricht.svelte) while the round that named
             it writes; that round ends at a tool or with the answer, and the
             reading goes with it (`lesungenLeeren`) — the finished answer's
             figure comes out of the stats. A server that names no reading
             sends none, and then nothing stands there. */
          /* Either half may be missing: a server that names a cache share but
             no usable speed has something to say under the running answer,
             and one that names only a speed says nothing about the cache. So
             each field is set when it is there and left alone when it is not
             — a reading with neither never leaves the provider at all.
             The share has its own field, like the speed beside it, and ends
             by the same rule as the speed. A stream that is picked up again
             after a dropped connection keeps it — it is the same chat and
             the same answer, and the reading belongs to them. */
          if (typeof ereignis.tokens_pro_sekunde === 'number') {
            platzhalter.liveSpeed = {
              wert: ereignis.tokens_pro_sekunde,
              quelle: ereignis.tempo_quelle,
            }
          }
          if (typeof ereignis.prompt_cache_percent === 'number') {
            platzhalter.liveShare = ereignis.prompt_cache_percent
          }
        } else if (ereignis.typ === 'content') {
          platzhalter.content += ereignis.text
          textAnhaengen('content', ereignis.text, ereignis.zeitpunkt_ms)
          /* Writing is an activity of its own: the thinking is over the
             moment the answer's text begins, bare line breaks included.
             The waiting mark stays under the text until the run ends
             (laufMarke). */
          taetigkeitSetzen(platzhalter, 'schreibt', ereignis.zeitpunkt_ms)
          /* A file opens its tab the moment its fence OPENS and grows in
             it from there — waiting for the closing fence meant the rail
             stayed empty for as long as a document was being written, and
             waiting for the whole answer meant nothing happened at all.

             The tab is opened ONCE per file. Every further piece, the
             last one included, only follows it: a tab the reader closed
             while the file was still being written stays closed, also when
             the fence closes (carryFile above).

             Only looked for when it can matter: a fence cannot open or
             close without a backtick, and a file that is growing grows
             with every piece. A fence the last piece left unsettled counts
             as well — "```" closes a file, and "bash" one piece later makes
             those same marks the opening of a block inside it, so the file
             is open again; and "markdown" behind them is where a document
             begins. Scanning the whole accumulated answer on every chunk
             of plain prose turns a long answer into quadratic work on the
             same tick that draws it. */
          const fenceMoved = ereignis.text.includes('`') || fenceUnsettled
          if (fenceMoved) {
            // A file that was open and has closed gets its last piece here;
            // one that arrived whole is seen for the first time.
            for (const file of dateienAus(platzhalter.content)) carryFile(file)
          }
          if (fenceMoved || fileGrowing) {
            const unfinished = openFile(platzhalter.content)
            fileGrowing = !!unfinished
            if (unfinished) carryFile(unfinished)
            fenceUnsettled = endsInFence(platzhalter.content)
          }
          runter()
        } else if (ereignis.typ === 'tool_confirm' && ereignis.settled) {
          /* A permission the service marks as settled: a reattach replays it
             long after the answer. Its call draws the line and nothing is
             waiting any more, so there is no box and no sound. */
        } else if (ereignis.typ === 'tool_confirm') {
          /* The server only ever sends this when Tor 3 itself says "fragen"
             for THIS call — a standing yes from an earlier "immer erlauben"
             (Schritt 12) is a real rule in berechtigungen.json by now, and
             Tor 3 already answered "ja" before this event could exist. No
             client-side memory left to check here. */
          /* The server halts and waits. No toast for this — the card over
             the chat is conspicuous enough, and two notices for the same
             thing is one too many. */
          /* The program is waiting for an answer — the one case where a
             sound is worth it, because nothing moves until somebody
             comes back. */
          melden({ was: 'wartet', von: 'chat' })
          schreibendeMeldungSchliessen()
          // The run stands at a tool now: the thinking is over.
          taetigkeitSetzen(platzhalter, 'werkzeug', ereignis.zeitpunkt_ms, true)
          lesungenLeeren(platzhalter)
          /* The call is complete and waits for a yes. The row it was
             written in is its row from here on, not a line that still says
             "being written" — marked `asked` until the call starts; a call
             without such a row gets its row when it starts, as before. */
          const asked = writtenRow(ereignis.aufruf_id, ereignis.name)
          if (asked) {
            asked.asked = true
            platzhalter.werkzeuge.push({
              aufruf_id: ereignis.aufruf_id,
              name: ereignis.name,
              server: '',
              argumente: ereignis.argumente,
              ergebnis: null,
              fehlgeschlagen: false,
            })
          }
          zustand.werkzeugfrage[zielChat] = {
            generationId: lauf.generationId,
            aufrufId: ereignis.aufruf_id,
            name: ereignis.name,
            argumente: ereignis.argumente,
            // The RUN's chat, not whatever is on screen: whoever switched
            // away must not find a foreign question hanging over their
            // input field.
            chatId: zielChat,
            // Why this call is being asked about — empty when the tool is
            // simply configured to always ask.
            grund: ereignis.grund || '',
            grundWert: ereignis.grund_wert || '',
          }
        } else if (ereignis.typ === 'user_ask') {
          /* The model wants a decision that belongs to the user. The run
             stands still until it gets one. A question the service marks as
             settled is only history on a reattach: its line goes into the
             answer, and nothing else — no sound, no box. */
          if (!ereignis.settled) {
            melden({ was: 'wartet', von: 'chat' })
            schreibendeMeldungSchliessen()
            // The run stands at a tool now: the thinking is over.
            taetigkeitSetzen(platzhalter, 'werkzeug', ereignis.zeitpunkt_ms, true)
            lesungenLeeren(platzhalter)
          }
          /* The question also lands in the history like any other tool
             call: the server sends no tool_call for ask_user, so the entry
             is created here — the tool_result later fills it, and question
             plus answer stay visible as a block instead of vanishing. */
          platzhalter.werkzeuge.push({
            aufruf_id: ereignis.aufruf_id,
            name: 'ask_user',
            server: '',
            argumente: { question: ereignis.frage },
            ergebnis: null,
            fehlgeschlagen: false,
          })
          rowOfCall(ereignis.aufruf_id, 'ask_user', ereignis.zeitpunkt_ms)
          if (!ereignis.settled) {
            zustand.benutzerfrage[zielChat] = {
              generationId: lauf.generationId,
              aufrufId: ereignis.aufruf_id,
              frage: ereignis.frage,
              optionen: ereignis.optionen || [],
              // The RUN's chat, not whatever is on screen — the sidebar
              // lights the right row by it, and the box only shows there.
              chatId: zielChat,
              // Which question of this run this is — the box wears the
              // count as a small pill.
              nummer: platzhalter.werkzeuge.filter((w) => w.name === 'ask_user').length,
            }
            /* The question is only ever asked once its permission was
               granted, so a permission still standing for this very call is
               one a reattach replayed from the run's start. Left standing, the
               box would show that old permission instead of the question, and
               a yes to it would land on the question's own wait. */
            frageAbnehmen(ereignis.aufruf_id, zustand.werkzeugfrage)
            runter()
          }
        } else if (ereignis.typ === 'job_confirm') {
          /* start_job: the task appears EDITABLE before the run begins —
             whatever the user confirms is what runs, and cancel starts
             nothing. Same standing-still as a user question — and, settled
             on a reattach, the same history-only line. */
          if (!ereignis.settled) {
            melden({ was: 'wartet', von: 'chat' })
            schreibendeMeldungSchliessen()
            // The run stands at a tool now: the thinking is over.
            taetigkeitSetzen(platzhalter, 'werkzeug', ereignis.zeitpunkt_ms, true)
            lesungenLeeren(platzhalter)
          }
          platzhalter.werkzeuge.push({
            aufruf_id: ereignis.aufruf_id,
            name: 'start_job',
            server: '',
            argumente: { agent: ereignis.agent, task: ereignis.task },
            ergebnis: null,
            fehlgeschlagen: false,
          })
          rowOfCall(ereignis.aufruf_id, 'start_job', ereignis.zeitpunkt_ms)
          if (!ereignis.settled) {
            zustand.jobfrage[zielChat] = {
              generationId: lauf.generationId,
              aufrufId: ereignis.aufruf_id,
              agent: ereignis.agent,
              task: ereignis.task,
              chatId: zielChat,
            }
            runter()
          }
        } else if (ereignis.typ === 'exemd_zu_gross') {
          /* A shared folder's exe.md has grown past the point where it eats
             the context of every single request. Quiet — this is a caution,
             not a failure, and the file still travels whole either way.
             Sent once per chat and folder, decided on the service side, so
             this needs no memory of its own. */
          meldeText(
            'ordnerwissen.zu_gross',
            { ordner: ereignis.ordner, zeichen: ereignis.zeichen },
            'warnung',
          )
        } else if (ereignis.typ === 'tool_call_laeuft') {
          /* The model is still WRITING the call. Nothing has run yet, so
             this is not the tool notification below — it is the answer to
             "is anything happening at all", during minutes in which the
             window otherwise shows nothing while data flows the whole time.

             Rewritten as the argument grows rather than stacked, and keyed
             by the call's index because the id only exists once the call is
             complete. The tool notification below replaces it the moment the
             call really starts. */
          werkzeugSagen(
            'werkzeug.schreibt',
            { name: ereignis.name, zeichen: ereignis.zeichen ?? 0 },
            'werkzeug',
            true,
          )
          werkzeugOffen = true
          // The same in the answer: the call's row, counting along.
          callBeingWritten(ereignis.index ?? 0, ereignis.name, ereignis.zeichen ?? 0, ereignis.zeitpunkt_ms)
          taetigkeitSetzen(platzhalter, 'werkzeug', ereignis.zeitpunkt_ms)
        } else if (ereignis.typ === 'tool_call') {
          /* The same notice moves on: it was reporting the argument being
             written, and now reports the call itself. Stays up until the
             result is in. */
          werkzeugSagen('werkzeug.laeuft', { name: ereignis.name }, 'werkzeug', true)
          werkzeugOffen = true
          // Also attached to the message: the notification disappears
          // again, but the history should keep a traceable record of what
          // ran.
          const asked = platzhalter.abschnitte.find(
            (a) => a.asked && a.aufruf_id === ereignis.aufruf_id,
          )
          if (asked) {
            // The row has stood since its permission was asked for.
            delete asked.asked
            const held = platzhalter.werkzeuge.findLast((w) => w.aufruf_id === ereignis.aufruf_id)
            held.server = ereignis.server || ''
            held.argumente = ereignis.argumente
          } else {
            platzhalter.werkzeuge.push({
              aufruf_id: ereignis.aufruf_id,
              name: ereignis.name,
              // Which server it came from — the catalogue picks the mark by it.
              server: ereignis.server || '',
              argumente: ereignis.argumente,
              ergebnis: null,
              fehlgeschlagen: false,
            })
            /* The row it was written in becomes its row — no second one —
               and a call that was never reported while being written gets
               its row here. */
            rowOfCall(ereignis.aufruf_id, ereignis.name, ereignis.zeitpunkt_ms)
          }
          // A picture being drawn: the picture window's working tile.
          if (ereignis.name === 'draw_image') {
            drawing = true
            drawingStarted(zielChat, platzhalter.id)
          }
          /* A permission is settled once its call runs. Live the box is
             gone already (the answer took it down); on a resume the replay
             put it back with its `tool_confirm`, and it would otherwise
             stand over a running tool until the tool's result. */
          frageAbnehmen(ereignis.aufruf_id, zustand.werkzeugfrage)
          // A tool runs: the waiting mark stays on the line with a waiting
          // word and a fresh clock, under the tool's own row — fresh even
          // after the arguments were written or a permission was given.
          taetigkeitSetzen(platzhalter, 'werkzeug', ereignis.zeitpunkt_ms, true)
          lesungenLeeren(platzhalter)
          runter()
        } else if (ereignis.typ === 'tool_result') {
          const eintrag = platzhalter.werkzeuge.find(
            (w) => w.aufruf_id === ereignis.aufruf_id,
          )
          if (eintrag) {
            eintrag.ergebnis = ereignis.text
            eintrag.fehlgeschlagen = ereignis.fehlgeschlagen
            // Absent on an older server or mid-migration, never a made-up
            // number — the row leaves the duration out rather than show a
            // guess.
            if (ereignis.dauer_sekunden != null) eintrag.dauer_sekunden = ereignis.dauer_sekunden
            /* A command sent to the background: the number of the run it
               started, by which the terminal stream fills this very card
               with the ending later (lib/terminalfenster.svelte.js). */
            if (ereignis.lauf_nummer != null) eintrag.lauf_nummer = ereignis.lauf_nummer
            /* A job this call started: the row turns into the agent's own
               row at the line (Nachricht.svelte), fed by the job list. */
            if (ereignis.auftrag_id) eintrag.auftrag_id = ereignis.auftrag_id
          }
          // A folder the model made and shared (lib/arbeitsordner.svelte.js).
          if (ereignis.name === 'create_folder' && !ereignis.fehlgeschlagen) sharedByModel()
          /* A question whose answer has just arrived is over — take the box
             down. This matters most on a resume: the replay hands out every
             `tool_confirm`, `user_ask` and `job_confirm` of the run again,
             including the ones that were answered long before the reload.
             Without this, a settled question stands over the input field
             again and a click on it goes nowhere, because the run is far
             past it. Keyed by call id, so only the one that was actually
             answered disappears. */
          frageAbnehmen(ereignis.aufruf_id, zustand.werkzeugfrage, zustand.benutzerfrage, zustand.jobfrage)
          // The result is in; the model still has to work the grown
          // context back through before anything new arrives — exactly the
          // stretch that used to show nothing at all.
          taetigkeitSetzen(platzhalter, 'kontext', ereignis.zeitpunkt_ms, true)
          // A tool has saved an image (Recraft & co.): attach it to the
          // answer immediately — same display as in image mode.
          if (ereignis.bild) platzhalter.bild = ereignis.bild
          /* A tool has handed a file into the chat: the answer's document
             cards as the service holds them now, in the shape a stored
             answer carries them — one as `dokument`, several as
             `dokumente` — so the card stands in the bubble without the
             chat being fetched again. */
          if (Array.isArray(ereignis.dokumente)) {
            platzhalter.dokument = ereignis.dokumente.length === 1 ? ereignis.dokumente[0] : null
            platzhalter.dokumente = ereignis.dokumente.length > 1 ? ereignis.dokumente : null
          }
          // A drawing call is over: its picture, if it came, stands in the
          // answer's run row the server hands over; the working tile goes.
          if (ereignis.name === 'draw_image') {
            drawing = false
            drawingDone(zielChat, platzhalter.id, ereignis.bildlauf ?? null)
          }
          /* The end of this call, in the notice that has been reporting it
             all along. Not `dauerhaft` any more: this is the one state that
             is finished, so it may fade on its own — and if another call
             follows, it is rewritten before the clock runs out.

             The tick's clock comes from `werkzeugFertigDauer()`: the
             notice-duration setting when the user set one, the house 1.5 s
             while that field stands on "Auto". A failure does not read that
             setting at all — it always stands `WERKZEUG_FEHLER_MS` (5 s),
             on every position of that field, "Auto" included. It is the one
             line of this commentary that has to be read; the rest is
             progress. */
          werkzeugSagen(
            ereignis.fehlgeschlagen ? 'werkzeug.fehlgeschlagen' : 'werkzeug.fertig',
            { name: ereignis.name },
            ereignis.fehlgeschlagen ? 'fehler' : 'erfolg',
            false,
            ereignis.fehlgeschlagen ? WERKZEUG_FEHLER_MS : werkzeugFertigDauer(),
          )
          werkzeugOffen = false
        } else if (ereignis.typ === 'ziel') {
          /* The model has reported a reached goal (the `goal` tool). The
             answer carries a quiet mark from this moment on — the point is
             to SEE that it is done without the model having to keep
             talking. The report itself is the mark's text: what was
             reached, not that something was.

             Set on the message, not shown as a notification: a
             notification goes away, and this is the one line of the answer
             that should still be there tomorrow. The server stores it
             alongside the tool log, so a reload shows the same mark. */
          platzhalter.ziel = ereignis.report
        } else if (ereignis.typ === 'error') {
          gescheitert = true
          melde(ereignis.text, 'fehler')
        } else if (ereignis.typ === 'kontext') {
          /* How full the context is, WHILE the answer is being written. It
             used to arrive once, in `stats`, one event before `done` — so
             the bar stood still for the whole answer and then jumped, which
             is exactly when it is least useful: the point of it is to see
             the room running out before the request that fails.

             Onto the message rather than into a variable of its own: the
             bar reads the reading off the row (zustand.svelte.js,
             `kontextStand`), and the running row is a row like any other.
             The server writes the same number into that row's column, so a
             window that opens the chat cold mid-run finds it there. */
          platzhalter.gesamt_tokens = ereignis.gesamt_tokens
        } else if (ereignis.typ === 'stats') {
          platzhalter.stats = ereignis.daten || {}
          /* The round is over and has measured itself: its figure stands
             until the next round's first live reading, not the last live
             reading of the round before. The cache share follows the same
             rule — from here on it comes out of the stats just handed in. */
          lesungenLeeren(platzhalter)
        } else if (ereignis.typ === 'done') {
          verdichtetZu = ereignis.verdichtet ?? null
          schlussZustand = ereignis.zustand ?? null
          /* Stopped on the service — from another window, or before the
             run began — is a stop here as well: no finished dot, and the
             queue holds as it does after a stop of this window's own.
             Stopped, failed and answered are three outcomes, not two. */
          if (ereignis.abgebrochen) abgebrochen = true
          /* The answer the run really ended with — it rides along only where
             it is NOT the one the streamed pieces spelled out, so the bubble
             that is standing there has to be lifted the same way the row
             was (see `liftAnswer` above). Without it the answer stayed in
             the thinking block until the chat was opened again. */
          if (typeof ereignis.content === 'string') {
            const reasoning = ereignis.reasoning ?? ''
            platzhalter.reasoning = reasoning
            platzhalter.content = ereignis.content
            platzhalter.abschnitte = liftAnswer(
              platzhalter.abschnitte,
              ereignis.content,
              reasoning,
            )
          }
          /* What this answer carried of each document: the word on the
             card of the question it hangs on. The service wrote the same
             words onto those rows before the answer went out, so a reload
             shows them again — this puts them there without one. Only on
             the chat on screen: any other chat is fetched afresh when it is
             opened, and its cards arrive with the word. Properties on the
             cards, nothing put into or taken out of the list.

             ROW BY ROW, by the ids the event names. It used to be one flat
             map of document id to word, laid over every card of the chat
             carrying that document — including the cards of rows this
             answer never sent. A folded row is the one that happens: the
             service leaves it out of the request, so it keeps in the table
             the word of the last answer that DID carry it, and the card
             here said what THIS answer carried until the next reload put
             the stored word back. */
          if (ereignis.dokumente && zielChat === zustand.aktiverChat) {
            /* One reading per document for the whole answer: the plan is
               made per DOCUMENT (generierung.py, `dokumentplan`), so every
               row of one request got the same word for the same document
               and the rows can be merged without anything being lost. For
               the one row below that has no server id to be named by. */
            const dieseAntwort = Object.assign({}, ...Object.values(ereignis.dokumente))
            /* The question THIS send put up a moment ago: the event names
               every OTHER row by the service's own id, and this one carries
               that same id already (see `frageKennung` in senden()) — but
               the event itself has no way to single it out among rows it
               names, so it is found here instead. Matched by the exact id
               this call was given, not merely the local `eigen-` shape:
               a reload racing the request replaces the row with the
               service's own copy of it before this ever runs, and only the
               id, not the prefix, still ties the two together. Found the
               way the bubble is found when a send fails (see below) — and
               only for a send that put a question up at all, never for a
               regenerate. */
            const eigeneFrage = inhalt != null && nachrichtId
              ? zustand.nachrichten.find(
                  (n) => n.role === 'user' && (n.id === nachrichtId || n.id === 'eigen-' + nachrichtId),
                ) ?? null
              : null
            for (const eintrag of zustand.nachrichten) {
              /* Every row but that one has to be NAMED, and that is the
                 point: a row the request left out keeps the word of the last
                 answer that did carry it. */
              const stand = eintrag === eigeneFrage
                ? dieseAntwort
                : ereignis.dokumente[eintrag.id]
              if (!stand) continue
              for (const karte of [eintrag.dokument, ...(eintrag.dokumente ?? [])]) {
                if (karte?.id && stand[karte.id]) karte.getragen = stand[karte.id]
              }
            }
          }
        }
      }
      }

      /* Watching the run again after its line broke. One attempt is not
         enough: a proxy that reaps idle connections, a laptop that wakes
         up — the run keeps going on the service, and the window has to come
         back to it instead of declaring the answer failed. Every further
         attempt waits twice as long as the one before (a stream that opens
         throws the wait away), and the loop ends where there is nothing
         left to watch: the service no longer names this run, the person
         stopped it, or the service stopped answering.
         `laufJetzt` says which run this is — the same one the requests
         above were made for, never another chat's. */
      async function weiterZusehen(laufJetzt, chatId, signal) {
        let pause = WIEDERANHANG_PAUSE_MS
        while (true) {
          const vorher = ereignisZahl
          try {
            await ereignisVerarbeiten(
              zusehenStrom(laufJetzt.generationId, ereignisZahl, signal),
            )
            return
          } catch (fehler) {
            /* Refused (a 404 for a run the service dropped between the two
               attempts): the row this window was filling stays as far as
               the stream got, and the stored one is fetched instead — for
               a fresh send as for a resume. */
            if (fehler.status) zeileNachladen = true
            if (fehler.name === 'AbortError' || fehler.status) throw fehler
          }
          /* A line that DID carry something before it broke has proved that
             the run is reachable: the wait starts over at a second instead
             of climbing on (the yardstick resets on a standing connection
             the same way). Only a run of attempts with nothing arriving
             between them keeps doubling. */
          if (ereignisZahl > vorher) pause = WIEDERANHANG_PAUSE_MS
          /* The run is written down on the service even while no window
             watches it — that is what makes coming back worth anything.
             Asks once, cheaply, and only then decides: still there, wait
             and try again; gone, the stored row is what stands; not
             answering at all, the same — a line that is gone cannot be
             waited for, and waiting on it would hold the chat for the rest
             of the session. */
          let frisch = null
          try {
            frisch = await api.nachrichten(chatId, { signal: withDeadline(signal), limit: 1 })
          } catch (fehler) {
            if (fehler.name === 'AbortError') throw fehler
          }
          if (frisch === null || (!frisch.laufend && !frisch.gehalten)) {
            /* The service does not know it any more — or does not answer:
               the stored row is the answer, with the state it ended in and
               no waiting mark. */
            zeileNachladen = true
            return
          }
          await pauseOrStop(pause, signal)
          pause = Math.min(pause * 2, WIEDERANHANG_PAUSE_MAX_MS)
        }
      }

      try {
        /* A resume never posts a new message — it attaches to the run the
           server already told us about, and from its very first event: the
           WHOLE run is replayed here, and that is deliberate. The message
           row in the database does carry the state so far these days (the
           run writes it along the way, so a service that dies leaves half
           an answer instead of none) — but that half is a fallback for
           when there is no stream left to replay, never a head start.
           Which is why the adopted row is cleared above: everything in it
           arrives here again. (`zusehenStrom` keeps its offset for the
           mid-stream reconnect below, which resumes at `ereignisZahl`
           instead of at the beginning.) */
        await ereignisVerarbeiten(
          wiederanhang
            ? zusehenStrom(wiederanhang.generationId, 0, abbruch.signal)
            : antwortStrom(koerper, abbruch.signal),
        )
      } catch (fehler) {
        /* A second attempt is for a stream that BROKE mid-answer — a dropped
           WiFi, a laptop that slept — never for a request the service itself
           refused: a refusal carries a status (404 for a run the service no
           longer has, a 401 whose page reloads itself), and asking that same
           run again would only be refused again. One refusal ends the run. A
           broken fetch carries no status while a refusal does (api.js
           errorFrom reads the number off the answer), so `fehler.status`
           separates the two. */
        if (fehler.name === 'AbortError' || fehler.status) throw fehler
        if (!lauf.generationId) {
          /* Broke before the service named this run — then the ordinary
             reattach below has nothing to attach to, and the send used to
             be declared failed on the spot. Ask where the answer went
             instead; `nachholen` waits while the service still holds the
             chat and returns false only where there is nothing left to
             wait for. */
          const found = await nachholen(lauf, zielChat, abbruch.signal)
          if (!found) throw fehler
          /* Found running: watched from its first event — nothing of it
             has been seen here — and through the same retry as any other
             line that breaks mid-answer. */
          if (found === 'run') {
            ereignisZahl = 0
            await weiterZusehen(lauf, zielChat, abbruch.signal)
          }
          return
        }
        /* The run is untouched: the server keeps working in the background
           and remembers every event since the start (api.js zusehenStrom).
           Back to it exactly where this stopped instead of declaring the
           answer failed — and back again if THIS line breaks too. */
        await weiterZusehen(lauf, zielChat, abbruch.signal)
      }
    } catch (fehler) {
      /* Stopped by hand counts as stopped, whoever ends the failure: while
         the window waits for a run that has not begun (nachholen above),
         the fetch shows up here as its own error, and a red dot with a
         failure line under a run the person just stopped would be a lie.
         A stop the service already reported (`done` above) stays a stop
         when the line breaks after it. */
      abgebrochen = abgebrochen || fehler.name === 'AbortError' || abbruch.signal.aborted
      belegt = !abgebrochen && !wiederanhang && fehler.status === 409
      gescheitert = !abgebrochen && !belegt
      /* A reattach the service refused: the run is not there any more (404
         for one it has dropped), and the row this window was about to fill
         from the stream stays empty — "nothing written", with the stored
         half answer showing only at the next open. The stored row is
         fetched instead; the refusal itself is reported as it always was. */
      if (wiederanhang && fehler.status) zeileNachladen = true
      if (gescheitert) melde(String(fehler.message || fehler), 'fehler')
    } finally {
      /* An answer that ends — finished, stopped, or failed — with a tool
         notice still standing on no clock of its own: nothing is coming
         for it any more, so it closes here instead of waiting for someone
         to notice and dismiss it, or for three later notices to push it
         out. A notice that already moved on to "fertig" or "fehlgeschlagen"
         runs its own clock down as before — this only ever touches the
         durable, still-running one. */
      if (werkzeugOffen) {
        const stehengeblieben = werkzeugMeldungen.get(werkzeugToast)
        if (stehengeblieben) schliesseMeldung(stehengeblieben)
      }
      // The same for the answer's rows of calls that never began.
      dropRowsNeverBegun()
      if (belegt) {
        /* The bubble and its placeholder come down — nothing was sent —
           and the words go back where they were typed. Then the chat is
           opened afresh: the fetch names the run that is going, and the
           reattachment shows it.

           Only while that chat is the one on screen: after a switch the
           list belongs to ANOTHER chat, and the search below would have
           taken that chat's last bubble down and the reopen dragged the
           view back here. A chat that is not on screen is fetched afresh
           when it is opened, which drops the pair by itself; its words go
           to its own draft. And only a bubble this very call put up — a
           regenerate sends no bubble, and the search would have found the
           question above instead. */
        if (zielChat === zustand.aktiverChat) {
          const eigene = inhalt != null && nachrichtId
            ? zustand.nachrichten.find(
                (n) => n.role === 'user' && (n.id === nachrichtId || n.id === 'eigen-' + nachrichtId),
              )
            : null
          zustand.nachrichten = zustand.nachrichten.filter(
            (n) => n !== platzhalter && n !== eigene,
          )
          void chatOeffnen(zielChat)
        }
        /* Words AND attachments — a send without a word (two pictures and
           a document) was refused just the same, and until now it got
           nothing back at all: `if (inhalt)` skipped the whole call, so the
           pictures were gone from the bar and never in the chat. But only a
           real SEND: a regenerate (`inhalt === null`) never went through the
           bar, so the bar has nothing of its own to hand back. The message
           id tells the bar which of its sends this was. */
        if (inhalt != null) eingabe?.zurueckgeben(inhalt, zielChat, nachrichtId)
      }
      // If the answer aborts while the confirmation stands, nobody is
      // waiting for it anymore — the box has to go, otherwise it points
      // into the void. Only THIS run's own pending box, though: a run in
      // another chat may have one standing that nothing here has answered.
      delete zustand.werkzeugfrage[zielChat]
      delete zustand.benutzerfrage[zielChat]
      delete zustand.jobfrage[zielChat]
      /* A document in the answer opens as a tab in the rail by itself —
         that is what the panel is for. This used to happen here, only once
         the whole answer was done; it happens as each file's fence closes
         now (the 'content' branch above), so a long answer does not leave
         the rail silent while it is still being written. Nothing is left
         to catch up on here — every closed file already has its tab. */
      /* The finished dot: only when nobody was watching — someone sitting
         in this chat with the window in front saw the answer arrive, and
         whoever hit stop is not waiting for anything. */
      const fertigerChat = zielChat
      if (
        !abgebrochen &&
        !belegt &&
        fertigerChat &&
        (fertigerChat !== zustand.aktiverChat || !document.hasFocus())
      ) {
        /* A run that fell over earns the same afterglow as one that came
           through, in the other colour: the list should say WHICH of the
           two happened over there, not merely that something did. */
        if (gescheitert) chatFehlerMerken(fertigerChat)
        else chatFertigMerken(fertigerChat)
      }
      /* Whatever this row still says about being live, it is not any more.
         Belt as well as braces to the clearing on adoption above: a row can
         also reach this point carrying the field straight from a fetch that
         happened while the run was going. The closing state is the word
         the server put on the `done` event — the same one it wrote into
         the row's column — so a live row and a reloaded row say the same
         thing; a run that ended without a `done` (the stream broke) is
         left with no word rather than a guessed one. A run this window
         stopped itself gets no `done` either, but its word is known: it
         was stopped — not an answer in which the model wrote nothing. */
      platzhalter.zustand = schlussZustand ?? (abgebrochen ? 'abgebrochen' : null)
      // A drawing call this run never saw the result of: its tile goes too.
      if (drawing) drawingDone(zielChat, platzhalter.id, null)
      /* A compaction folded the middle of the history away and left a
         summary row nobody here has seen. Fetched once, so the seam appears
         at all, instead of only at the next open. Guarded on the chat still
         being the one on screen, and failure-tolerant on purpose: the row
         is safely in the database either way, and the list heals the next
         time this chat is opened (the picture window's own reconcile
         reasons the same way).

         It runs BEFORE the release below, and that ordering is the whole
         point: the reconcile replaces `zustand.nachrichten` wholesale, so it
         has to be the last thing this run does to the list — with nothing
         else allowed to have put anything into it yet. */
      if (
        (verdichtetZu || zeileNachladen) &&
        zielChat &&
        zielChat === zustand.aktiverChat
      ) {
        try {
          /* Asked for before the await, assigned only after checking again:
             the guard above was true when this started, and a chat switch
             during the fetch would otherwise write THIS chat's history into
             the window showing another one — over whatever is streaming
             there. The picture window's reconcile re-reads `aktiverChat`
             after its own await for exactly that reason; this one only ever
             looked before it. */
          /* Bounded, because the release below waits on it. Unbounded, a
             fetch that never settled — a dropped connection, a proxy that
             holds the request — kept `zustand.laeuft` set for the rest of
             the session: input greyed, Stop offered for a run that was
             over, the queue never fired. A timeout lands in the catch,
             and the catch lets the release run. */
          const frisch = await api.nachrichten(zielChat, {
            signal: AbortSignal.timeout(NACHLADE_FRIST_MS),
          })
          if (zielChat === zustand.aktiverChat) {
            nachrichtenSetzen(zielChat, frisch.nachrichten)
            /* A picture can be drawing in this same chat right now — sending
               is deliberately allowed while one runs (Eingabeleiste.svelte).
               Its working row lives only here, not on the server, so this
               reload just as freely dropped it — the same rescue chatOeffnen
               already runs for its own reload (zustand.svelte.js). */
            if (zustand.bildLaeuftChat[zielChat]
                && !zustand.nachrichten.some((n) => n.bildLaeuft)) {
              zustand.nachrichten.push(bildlaufPlatzhalter(zielChat))
            }
            /* A run the service reports as going NOW has a live row in
               the list just fetched. Usually it is somebody else's — the
               service releases this run before it sends `done`, and a wake
               can start on its end (app/hintergrundwecken.py) — but it can
               be this very run too, when the line to it was refused while
               the run went on. Left alone, that row was drawn as running
               with no stream behind it, nothing ever cleared it, and the
               queue sent into a chat the service had already claimed.
               Noted here, acted on once this run has let go below. */
            fremderLauf = frisch.laufend ?? null
            /* Held with no run named yet: a send that claimed the chat is
               still folding its history. As taken as a running chat — the
               queue sending into it now only ran into a 409. */
            heldWithoutRun = !frisch.laufend && Boolean(frisch.gehalten)
          }
        } catch {
          /* the answer stands; the fresh list arrives with the next open */
        }
      }
      /* A clean end lets the line move; a failed or stopped run holds it
         and says so at the bubble. Nobody fires the next message into a
         state that has just gone wrong.

         Everything from here to the end of the block is the run LETTING GO
         of the chat, and the order inside it is not cosmetic.
         `delete zustand.laeuft[zielChat]` is not bookkeeping, it is the
         signal: the effect at the foot of this file watches exactly
         `Object.keys(zustand.laeuft).length`, so that one line arms the
         queue, and the very next await is enough to fire it. Whatever the
         queue is meant to be gated on must therefore be true BEFORE it, and
         whatever this run still means to write into the chat must already be
         written.

         Both were broken from here, in two separate ways, and both are
         fixed by the order rather than by a repair afterwards. The picture
         path's rescue is not the tool for this one: it puts the placeholder
         back AFTER the list was replaced, and it can only recognise its own
         row once the run's `start` event has handed the placeholder the
         service's id — which a run begun a few milliseconds ago has not
         got. Here it would land in that blind spot every time: a second row
         pushed beside the service's own, keeping `zustand: 'laeuft'` with
         nobody left to clear it, or the answer put back without the
         question it answers. Nothing needs putting back if nothing was
         taken away.

         `anhalten` used to stand at the bottom, past two awaits. So a run
         that failed or was stopped by hand released the line on its way out
         and only then said it should have held: the waiting message went
         out into the state that had just gone wrong — the one thing
         warteschlange.svelte.js says must never happen. It now marks the
         entries while the chat is still claimed, and the queue reads the
         mark instead of racing it.

         And the reconcile above replaces the message list. With the release
         still at the top of this block, the queue's `senden` ran during the
         awaits — as far as its own bubble and its placeholder without ever
         yielding, since a message with no attachments in a chat that already
         has a history reaches both synchronously — and the replacement then
         threw the pair away. The second question was simply gone from the
         screen, its answer streamed into an object nothing draws any more,
         and the bar kept offering a stop button for it. A fold is what
         turned that from a rarity into the ordinary case: folds happen in
         long chats, which is where `api.nachrichten` is slowest and where a
         message gets queued in the first place.

         So the claim on the chat is held for exactly as long as this run is
         still rewriting the chat's list, and dropped the moment it is not.
         `chatsLaden` sits below the release rather than above it because it
         refreshes the sidebar and touches no message at all: kept above, it
         would make every ordinary answer — the overwhelming majority, which
         never reconciles anything — wait a whole round trip before its queue
         could move. */
      /* The service still running THIS run: the line to it was refused or
         lost while the run went on. Not stopped from here, it has not
         failed either — it is attached again below, so the queue does not
         hold for it and the failure mark goes. Once per run: a line that
         keeps refusing would otherwise turn into a loop with a notice every
         round. Not attached — stopped from here, or attached once already —
         its row does not stand as running with no stream behind it: stopped
         says so, the other keeps no word rather than a guessed one. */
      const isOwnRun = fremderLauf != null && fremderLauf.generation_id === lauf.generationId
      const ownRunGoesOn = isOwnRun && !abgebrochen && !ownRunsReattached.has(lauf.generationId)
      if (isOwnRun && !ownRunGoesOn) {
        const row = zustand.nachrichten.find((n) => n.id === fremderLauf.message_id)
        if (row) row.zustand = abgebrochen ? 'abgebrochen' : null
        fremderLauf = null
      }
      if (ownRunGoesOn) {
        ownRunsReattached.add(lauf.generationId)
        chatFehlerGesehen(fertigerChat)
      }
      else if (fertigerChat && (abgebrochen || gescheitert)) anhalten(fertigerChat)
      /* A held chat keeps the queue's gate shut through the release: the
         same send-in-flight mark that holds the queue while a send of this
         window's own uploads — a send of this window still holds it
         anyway, and then it is left to that send to lift. */
      const holdMark = heldWithoutRun && !zustand.sendet[zielChat]
      if (holdMark) zustand.sendet[zielChat] = true
      delete zustand.laeuft[zielChat]
      if (zustand.laufenderPlatzhalter[zielChat] === platzhalter) {
        delete zustand.laufenderPlatzhalter[zielChat]
      }
      /* Straight after the release and before anything yields: the reattach
         registers the run synchronously, so the queue effect the release
         wakes finds the chat taken and holds, instead of sending into a 409.
         The same door a cold open uses (`chatOeffnen`). */
      if (fremderLauf) {
        // The list was fetched in the same breath; a row still missing is
        // no reason to fetch again, and returning without claiming the
        // chat is exactly what the release above must never see.
        void antwortWiederAnhaengen({
          chatId: zielChat,
          generationId: fremderLauf.generation_id,
          messageId: fremderLauf.message_id ?? null,
        }, { nachholen: false })
      }
      await chatsLaden()
      if (heldWithoutRun) {
        try {
          const { run, reachable } = await claimOutcome(zielChat)
          if (reachable && zielChat === zustand.aktiverChat && !laufVon(zielChat)) {
            /* The list was fetched while the chat was held: fetched again, so
               the other send's question and its answer are there — running,
               or already over — and a named run is claimed
               synchronously before the mark goes — waiting for a fetch inside
               the reattach would open the gate first. Not over a run that
               another open attached meanwhile, and with a picture drawing here
               put back the way the reconcile above puts it back. */
            let named = run
            try {
              const fresh = await api.nachrichten(zielChat, {
                signal: AbortSignal.timeout(NACHLADE_FRIST_MS),
              })
              // The fresher word: a run that began since the last question,
              // or none — the named one is already over, and replaying it
              // would only stream a finished answer again.
              named = fresh?.laufend?.generation_id ? fresh.laufend : null
              if (zielChat === zustand.aktiverChat && !laufVon(zielChat)) {
                nachrichtenSetzen(zielChat, fresh.nachrichten)
                if (zustand.bildLaeuftChat[zielChat]
                    && !zustand.nachrichten.some((n) => n.bildLaeuft)) {
                  zustand.nachrichten.push(bildlaufPlatzhalter(zielChat))
                }
              }
            } catch {
              /* No fresher word: a run the claim turned into is attached as
                 it stands, a claim that simply went attaches nothing, and
                 the list heals at the next open. */
            }
            if (named) {
              void antwortWiederAnhaengen({
                chatId: zielChat,
                generationId: named.generation_id,
                messageId: named.message_id ?? null,
              }, { nachholen: false })
            }
          }
        } finally {
          // Whatever happens in the wait, the gate does not stay shut.
          if (holdMark) delete zustand.sendet[zielChat]
        }
      }
      warteschlangeWeiter()
    }
  }

  /* Reattaches to a run the server said is still going for this chat — the
     case a plain reload used to leave stuck at "nothing happening" (C2):
     the generation kept working the whole time, only the window's own
     record of its id was gone. */
  /* The runs a reattachment has already reopened the chat for (see
     below). A set, not one slot: two runs naming each other in turn
     walked one slot back and forth and fetched for ever. */
  const nachgeholtFuer = new Set()
  /* The runs whose own end attached them again once (see the end of
     `antwortHolen`) — never a second time. */
  const ownRunsReattached = new Set()
  /* The run the LAST of those fetches was made for — whoever finds another
     name here has been overtaken and must not attach its own, older run. */
  let nachgeholtZuletzt = null
  async function antwortWiederAnhaengen(wiederanhang, { nachholen = true } = {}) {
    // The whole record is passed on, not two fields out of it. Taking them
    // apart here and putting them back together below is how `messageId`
    // went missing: the resume was rebuilt as `{ chatId, generationId }`,
    // so `antwortHolen` never saw the id the server had gone to the trouble
    // of sending, adopted nothing, and pushed a second placeholder beside
    // the stored answer — the exact doubling this was built to stop.
    const { chatId } = wiederanhang
    // Opening a second chat before this got here must not attach a stream
    // meant for the first one to whatever is now on screen — the same
    // stale-result guard the terminal window needed (B9). And not twice for
    // the same chat: `laufVon(chatId)` means one is already attached.
    if (zustand.aktiverChat !== chatId || laufVon(chatId)) return
    /* A second window on the same chat hears the start of an answer whose
       question it has not fetched: attached as it stands, the answer grew
       under no question at all. The chat is opened afresh instead — the
       fetch brings the question and names the run, and the reattachment
       follows from there through this very function, with the row in the
       list this time. Once per run: a run whose row the fetch still does
       not bring is attached as it is rather than fetched forever. And
       only for a caller that can wait: the end-of-run reconcile has just
       fetched the list itself and needs the claim on the chat made
       synchronously, so it passes `nachholen: false`. */
    if (
      nachholen
      && wiederanhang.messageId
      && !nachgeholtFuer.has(wiederanhang.generationId)
      && !zustand.nachrichten.some((n) => n.id === wiederanhang.messageId)
    ) {
      nachgeholtFuer.add(wiederanhang.generationId)
      nachgeholtZuletzt = wiederanhang.generationId
      await chatOeffnen(chatId)
      /* The fetch names the run and files the reattachment again (the
         effect above picks it up). A fetch that failed, or one that named
         no run, filed nothing — then the answer is attached as it stands
         rather than lost until the next open. Unless a LATER fetch was
         made for another run meanwhile: then this one is stale, and
         attaching it would hang a dead run on the screen. */
      if (zustand.aktiverChat !== chatId || laufVon(chatId) || zustand.wiederanhaengen[chatId]) return
      if (nachgeholtZuletzt !== wiederanhang.generationId) return
    }
    await antwortHolen(null, null, null, null, null, wiederanhang)
  }


  /* Whether the question a row answers carried a picture. The service does
     not store `vision` on a row, so a reattach — which adopts a row that
     came from there — would otherwise write `false` over a question that
     did carry one, and the eye mark of image recognition turned into an
     ordinary waiting mark. The question itself is in the list: the nearest
     row above with the role `user`, read the same way Nachricht.svelte
     reads a row's pictures (`anhaenge`, else `bild`). `null` asks for the
     question the LAST row answers — what a placeholder pushed at the end
     belongs to. */
  function frageTrugBild(zeile) {
    const liste = zustand.nachrichten ?? []
    const stelle = zeile ? liste.indexOf(zeile) : liste.length
    for (let i = (stelle === -1 ? liste.length : stelle) - 1; i >= 0; i -= 1) {
      const davor = liste[i]
      /* Only an ordinary question: a picture run writes its prompt as a
         `user` row too (app/api/v1/bild.py), and a fold's summary carries
         the same role — stopping at one of those would answer `false` for
         a question that did carry a picture. */
      if (davor?.role !== 'user') continue
      if ((davor.art ?? 'nachricht') !== 'nachricht') continue
      return Boolean(davor.anhaenge?.length || davor.bild)
    }
    return false
  }

  /* Always the run of the chat on screen — never one in the background, and
     never more than one. */
  async function abbrechen() {
    const lauf = laufVon(zustand.aktiverChat)
    if (!lauf) return
    /* Both handles, always: the run's id where the stream has named it, the
       chat's always. Before `start` there is no run id — the service is
       still folding its history — and the chat id is what reaches the claim
       the service took for this send (app/generationen.py). Sent only with
       the run id, the press reached nothing: no run was registered yet, so
       nothing was cancelled, and the answer began into the window that had
       just stopped it. */
    lauf.abbruch.abort()
    /* Told, not waited for: the press must not hang on a request that may
       never settle (the route runs in the service's worker pool and carries
       no timeout of its own). Nothing below this line needs the answer. */
    void api.abbrechen(lauf.generationId, lauf.chatId).catch(() => {})
  }

  /* A menu page lies over the chat and its tool surface. While it does, both
     are out of reach for keys as well as for the eye: a key typed on the
     page must not send, stop or answer anything in a chat nobody can see. */
  const seiteOffen = $derived(eineSeiteOffen())
  /* The picture studio lies over the chat tile (teile/ImageStudio.svelte):
     the chat stays mounted underneath, hidden and out of reach. */
  const studioAn = $derived(studioSichtbar())

  function tastatur(ereignis) {
    if (tasteHoch(ereignis)) {
      folgtMit = false
      selbstGerolltChat = zustand.aktiverChat
    }
    const halte = ereignis.metaKey || ereignis.ctrlKey
    if (halte && ereignis.key === 'n') {
      ereignis.preventDefault()
      /* A new chat is where the hand wants to be: the page over the main
         area gives way, and the field is focused once it is no longer
         inert — which is on the next update, not in this one. */
      seitenSchliessen()
      neuerChat()
      tick().then(() => eingabe?.fokus())
    } else if (halte && ereignis.key === ',') {
      ereignis.preventDefault()
      zustand.promptStart = 'darstellung'
      seiteZeigen('prompt')
    } else if (halte && ereignis.key === 'b') {
      // The sidebar handle is invisible on purpose; without a key it would
      // not exist for anyone who never brushes the seam.
      ereignis.preventDefault()
      seitenleisteSchalten()
    } else if (halte && ereignis.key === 'j') {
      // The mirror of ⌘B: the work rail on the right.
      ereignis.preventDefault()
      leisteSchalten()
    } else if (halte && ereignis.key === 'k') {
      ereignis.preventDefault()
      sucheZeigen()
    } else if (ereignis.key === 'Escape') {
      const standing = standingQuestion(zustand.aktiverChat)
      // The prompt dialog has right of way — it lies above everything.
      if (zustand.frage) frageBeantworten(zustand.frage.eingabe != null ? null : false)
      else if (zustand.auftragStartenOffen) zustand.auftragStartenOffen = false
      /* The page before anything of the chat under it: Escape leaves the
         page, and the chat's own business waits until it is in sight. The
         enlarged server log over the page closes on its own (its window
         listens for the same key) and takes the page with it no further. */
      else if (seiteOffen) {
        if (!protokollOffen()) seitenSchliessen()
      }
      /* The studio lies over the chat the same way: the chat's business
         waits until it is in sight again. */
      else if (studioAn) {
        /* Nothing of the hidden chat is stopped or pushed away. */
      }
      /* A question waiting on the user is pushed away, not answered: the
         card over the chat goes, a chip in the bar brings it back. */
      else if (standing && !isDeferred(zustand.aktiverChat, standing)) {
        deferQuestion(zustand.aktiverChat, standing)
      }
      /* Before the run: somebody speaking into the microphone while an
         answer is being written is doing two things at once, and Escape
         means the one they are doing right now. The recording is dropped —
         Escape throws away, it does not finish. A conversation that owned
         this recording goes back to listening right away, so its own
         button stays operable; it still ends only through the hold. */
      else if (aufnahme.laeuft) {
        aufnahmeAbbrechen()
        eingabe?.gespraechAufnahmeAbgebrochen?.()
      }
      /* The same for a dictation already stopped whose words are still
         being transcribed: a speech service that never answers would
         otherwise leave the mirror over a locked field until a reload. */
      else if (eingabe?.transcribing?.()) eingabe.cancelTranscription()
      /* Marked text being read aloud is silenced before the run: it is what
         is audible right now. Only that reading — a conversation's voice
         keeps its own interrupts, and Escape there stays as it was. */
      else if (eingabe?.readingMarked?.()) eingabe.stopMarkedReading()
      else if (laufVon(zustand.aktiverChat)) abbrechen()
    }
  }

  $effect(() => {
    anzeigeUebernehmen().then(modelleLaden)
    featuresLaden()
    chatsLaden()
    klangwahlLaden()
    meldewesenLaden()
    /* The model-server window draws the slot's state from the first frame,
       so it has to be known before anybody opens it. */
    agentenserverStandLaden()
    /* The live line for everything that is not one chat's business
       (lib/ereignisstrom.svelte.js). Opened once for the window, closed
       with it — the panels behind it no longer ask on their own. */
    ereignisseVerbinden()
    const uhr = setInterval(modelleLaden, 30000)
    return () => {
      clearInterval(uhr)
      ereignisseTrennen()
    }
  })

  /* A run that ended announces itself. The list is the rail's own, fetched
     on its slow tick whether any panel is open or not, so this needs no
     timer of its own — it only has to read the list to run again with it.
     Deciding what to say, and whether anything is said at all, belongs to
     the two modules behind this and not here. */
  $effect(() => {
    auftraegeBeobachten(zustand.auftraege)
  })

  /* Jump to the end when switching chats — and ONLY then. The effect used
     to re-run on anything reactive it touched while running, and what it
     runs is runter(true), whose whole job is to force following back on.
     Every such re-run threw away a reader who had scrolled up, which is why
     scrolling worked while nothing was being written and fought back the
     moment it was: a fresh chat gets its real id once the first answer
     lands, and that alone re-fired this. Compare the id and leave when it
     did not change. */
  let letzterChat = null
  $effect(() => {
    const id = zustand.aktiverChat
    if (id === letzterChat) return
    letzterChat = id
    runter(true)
  })

  /* Two moments put the line in motion: switching into a chat that has
     somebody waiting, and a run coming to an end. Both are watched here,
     so neither has to remember to call the other.

     Everything else is read untracked on purpose. Firing takes the entry
     OUT of the queue, so an effect that also watched the queue would be
     woken by its own write — the classic self-feeding loop. */
  $effect(() => {
    void zustand.aktiverChat
    // The set of running chats, not the container: a run starting or ending
    // adds or removes a key, and that is what has to wake this.
    void Object.keys(zustand.laeuft).length
    /* And the send-in-flight marks. `senden` holds its chat's mark until
       `antwortHolen` has returned — which is AFTER that run's own end has
       released `laeuft` and woken this effect once, into a chat still
       marked as sending. Without this line nothing woke it again when the
       mark went, and a message queued during an ordinary answer stayed in
       the queue until the next chat switch. */
    void Object.keys(zustand.sendet).length
    /* And the quick picker's switch: a model switched on again, or one that
       is on chosen, frees the queue a switched-off model was holding. */
    void chosenModelOff()
    untrack(warteschlangeWeiter)
  })
</script>

<svelte:window onkeydown={tastatur} />

<!-- The live waiting mark, drawn by the answer it waits for (Nachricht.svelte,
     `marke`). -->
{#snippet wartemarke()}
  {#if laufMarke}
    <Wartezeile
      art={laufMarke.art}
      text={laufMarke.kontext
        ? t('nachricht.verarbeitet_kontext', { zeit: laufZeit })
        : laufMarke.text || wartewort}
      zeit={laufMarke.kontext ? '' : laufZeit}
      beschriftung={laufMarke.kontext ? '' : laufMarke.text || t('status.erzeugt_antwort')}
    />
  {/if}
{/snippet}

<div class="fenster">
  <!-- The drawing on the frame, behind everything that stands on it: the
       gradient stays the ground, the drawing lies on top of it. -->
  {#if moune}
    <Vektorfeld art="gras" />
  {:else if heaven}
    <Vektorfeld art="clouds" />
  {:else if pearl}
    <Vektorfeld art="dunes" />
  {:else if exe}
    <Vektorfeld art="wuerfel" />
  {:else if darkmatter}
    <Vektorfeld art="sternnetz" />
  {/if}
  <!-- `--seite-links`: where the chat surface starts, the left edge every
       menu page takes (Seitenrahmen.svelte) — the same sum the status strip
       below uses. -->
  <div class="rumpf" style:--seite-links="{(zustand.seitenleisteEingeklappt ? 52 : zustand.seitenBreite) + 8}px">
    <Seitenleiste />
    <!-- Sits on the seam and belongs to neither side. Invisible at rest. -->
    <Seitengriff />

    <main class:covered={seiteOffen} class:studio={studioAn}>
      <!-- The chat tile's drawing, the first layer of the surface. -->
      {#if moune}
        <Vektorfeld art="farn" />
      {:else if heaven}
        <Vektorfeld art="birds" />
      {:else if pearl}
        <Vektorfeld art="shell" />
      {/if}
      <!-- The chat's own head: its name. The tools have their signs in the
           column on the right. It lies over the top of the surface rather
           than pushing the history down, so the empty chat keeps its
           centred input. -->
      <div class="chatkopf" inert={seiteOffen || studioAn}>
        {#if !nochLeer && chatTitel}
          <span class="chatname">{chatTitel}</span>
        {/if}
      </div>
      <!-- Slides out from under the header — anchored in the CHAT area,
           not in the window: the center of the notification sits on the
           center of the chat column. -->
      <Meldungen />
      {#if studioAn}
        <ImageStudio zeichnen={bildLokalZeichnen} stopEins={stopOnePicture} entfernen={removeWaitingPicture} />
      {/if}
      <!-- The wordmark doesn't just fold away on send: its symbol
           simultaneously grows large into the background and stays there.
           Same size and opacity as behind the
           agents — both sections carry their mark the same way. -->
      <Wasserzeichen blass sichtbar={!nochLeer}>
        <Wortmarke mitText={false} />
      </Wasserzeichen>

      <div class="verlauf" class:under-head={!nochLeer} bind:this={verlauf} onscroll={gescrollt}
           onwheel={radGedreht} ontouchstart={beruehrungBeginnt} ontouchmove={beruehrungZieht}
           ontouchend={beruehrungEndet} inert={seiteOffen || studioAn}>
        <div class="spur">
          <!-- Keyed by `id` alone, deliberately without a fallback to `i`.
               That fallback was the bug, not the safety net it looked like:
               every message that reached the list without an id — the two
               running placeholders — keyed on its POSITION instead, so the
               next one to take that slot counted as the SAME message and
               Svelte refilled the old node rather than building a new one.
               A second picture appeared inside the first one's tile.
               Both placeholders carry their own id now (`bildlauf-` and
               `platzhalter-`, both from the chat's id), and everything else
               comes from the server, which never writes a row without one.
               Should a message ever arrive here without an id after all,
               this now fails loudly on the duplicate key — which is the
               point: silently showing the wrong picture is worse. -->
          {#each nachrichtenAnzeige() as nachricht, i (nachricht.id)}
            {@const kacheln = bildKacheln(nachricht)}
            {@const laufKachel = kacheln
              ? laufendeKachel(nachricht, laufAktuell, nachrichtenAnzeige())
              : null}
            {#if kacheln}
              <!-- Images per run (Weg A, Schritt 3): every tile comes from
                   this ONE message's own `bilder` — exactly as many as
                   have actually finished so far, wrapping at two per row —
                   a third or fourth tile lands on its own centered line
                   below rather than a reserved empty slot waiting for it.
                   A lone surviving tile still renders here, not as an
                   ordinary single message — the run it came from asked
                   for more than one, and the caption below is how that
                   shows even when only one made it. -->
              <div class="bildlauf-raster"
                   style={`--bildlauf-kachel-deckel:${(BILDLAUF_KACHEL + BILDLAUF_KACHEL_RAHMEN) * 2 + 12}px`}>
                {#each kacheln as kachel, kachelIndex (kachel.id + '-' + kachelIndex)}
                  <div class="bildlauf-platz" in:fly={{ y: 12, duration: 420, easing: backOut }}>
                    <!-- K2: no tile ever carries the regenerate arrow, not
                         even the run's own last one. Nachricht.svelte's
                         `neuErzeugen` deletes the message and then asks
                         the LANGUAGE model for a fresh answer — meaningless
                         for a picture.

                         C2 (Aufseher): `istLetzteFrage` and `laeuft` used
                         to read `letzteFrage`/`zustand.laeuft` against the
                         OUTER `nachricht` and `i` — the lauf message and
                         its own index, not the tile's. Both were always
                         false anyway (the outer message is never the
                         chat's own last question, and `senden` appends
                         its placeholder before `zustand.laeuft` is ever
                         set), which is exactly why nobody had noticed:
                         an accident standing in for an intended value
                         looks identical to that value until something
                         nearby changes. Written as `false` outright, so
                         the next person to touch this reads what is
                         actually meant instead of re-deriving it. -->
                    <Nachricht
                      nachricht={kachel}
                      istLetzte={false}
                      istLetzteFrage={false}
                      laeuft={false}
                      bildDeckel={BILDLAUF_KACHEL}
                      {neuErzeugen}
                      neuSenden={frageNeuSenden}
                    />
                  </div>
                {/each}
                {#if laufKachel}
                  <!-- The picture being drawn right now, in the slot it is
                       going to take. Same wrapper as a finished tile, so
                       the frame inside it (Nachricht.svelte draws it at
                       75% of the tile size while the painter works) does
                       not change the row's layout when it fills. -->
                  <div class="bildlauf-platz">
                    <Nachricht
                      nachricht={laufKachel}
                      istLetzte={false}
                      istLetzteFrage={false}
                      laeuft={false}
                      bildDeckel={BILDLAUF_KACHEL}
                      {neuErzeugen}
                      neuSenden={frageNeuSenden}
                    />
                  </div>
                {/if}
              </div>
              <!-- B9/B15 (Schritt 3): the run's own true total against the
                   run's own true count of finished pictures — see
                   `teilausfall` for why neither Weg B's per-row splitting
                   nor its four-picture ceiling have anything left to
                   compare against. Shown only once `laufAktuell` no
                   longer names this lauf, i.e. it is not the one
                   currently being drawn. -->
              {@const fehlbetrag = teilausfall(nachricht, laufAktuell, nachrichtenAnzeige())}
              {#if fehlbetrag}
                <p class="bildlauf-teilweise">
                  {t('bild.lauf_teilweise', fehlbetrag)}
                </p>
              {/if}
            {:else}
              <!-- The one message this branch does NOT draw is the
                   "picture is being drawn" frame of a run that already
                   has a grid above: that grid shows it as its next cell,
                   and drawing it here as well would put it on screen
                   twice. Written as a nested `{#if}` rather than as a
                   condition on the `{:else}` on purpose — the house-rule
                   test for K2 (no regenerate arrow on a tile) finds the
                   tile branch by the plain `{:else}` that closes it. -->
              <!-- A finished background run's report row is for the model
                   and the wake, not for the reader: its output stands on
                   the card of the call that started it (terminalfenster
                   .svelte.js, app/hintergrundmeldung.py), and a row under
                   the growing answer that never moves reads as a hung
                   call. The row stays in the list — the model's history
                   and the terminal panel still count on it. -->
              {#if (nachricht.art ?? 'nachricht') !== 'werkzeugmeldung'
                   && !inKachelAufgegangen(nachricht, laufAktuell, nachrichtenAnzeige())}
                <!-- "Feathering" entrance (3.11): rises and briefly overshoots
                     the target. Same motion language as the notifications. -->
                <div in:fly={{ y: 12, duration: 420, easing: backOut }}>
                  <Nachricht
                    {nachricht}
                    istLetzte={letzteAntwort && nachricht.id === letzteAntwort.id}
                    istLetzteFrage={letzteFrage && nachricht.id === letzteFrage.id}
                    laeuft={nachricht.zustand === 'laeuft'
                      || (Boolean(laufVon(zustand.aktiverChat))
                          && nachricht.id === laufenderId)}
                    marke={laufMarke && laufMarke.id === nachricht.id ? wartemarke : null}
                    {neuErzeugen}
                    neuSenden={frageNeuSenden}
                  />
                </div>
              {/if}
            {/if}
          {/each}
          <!-- What has been typed but not yet said. Sits at the end of the
               track, exactly where it will land once the line moves on. -->
          <Warteblasen losschicken={warteschlangeLosschicken} />
        </div>
      </div>

      <!-- Wordmark and input are ONE group in normal flow. Nothing is
           absolutely positioned: the empty space below shares the room
           with the history, which puts the group exactly in the middle.
           On send it shrinks to zero and pushes the group down. -->
      <div class="anlauf" inert={seiteOffen || studioAn}>
        <div class="marke" class:weg={!nochLeer} aria-hidden={!nochLeer}>
          <div class="wortmarke"><Wortmarke hoehe={55} zentriert /></div>
          <!-- Mounted afresh whenever a chat turns empty, so greeting and
               date are those of that moment, not of the program's start. -->
          {#key nochLeer}<Begruessungsecke />{/key}
        </div>
        <Eingabeleiste bind:this={eingabe} {senden} {abbrechen} {bildStoppen} {bildLokalLaeuft}
          vektoren={eingabeZeichnung}
          gruss={nochLeer && begruessung.an ? t('eingabe.los') : null} />
      </div>

      <div class="unterraum" class:zu={!nochLeer}></div>
    </main>

    <!-- The column right of the chat: browser, agents, schedules,
         terminal, pictures, doc folder. Comes forward by itself when one of
         them has something to show. -->
    <div class="untermseite" class:covered={seiteOffen} inert={seiteOffen}>
      <!-- The same handle on the seam as on the left. -->
      <Seitengriff side="right" />
      <Arbeitsleiste vektoren={leistenZeichnung} />
    </div>

    <!-- The menu pages: everything right of the sidebar, over the chat and
         its tool surface rather than instead of them — both stay as they
         are underneath. Mounted always and hidden while closed, so each
         keeps what was chosen in it. Settings hold appearance, prompts,
         agents, connections with the tools, and the two files. -->
    <ModelleSeite />
    <Katalog bind:offen={zustand.katalogOffen} />
    <SystemPrompt bind:offen={zustand.promptOffen} bind:modus />
  </div>
</div>

<Erststart bind:modus />
<Updatekarte />

<!-- A picture at full size. It hangs here and not inside the message that
     owns it: a window covers the whole program, and fixed positioning only
     reaches that far when nothing above it holds it. -->
<Bildschau />
<AuftragBestaetigen />
<AuftragStarten bind:offen={zustand.auftragStartenOffen} />

<!-- The layout mode's window, over the chat (teile/Layoutmodus.svelte). -->
{#if zustand.layoutModusOffen}
  <Layoutmodus />
{/if}
<!-- The house's prompt dialog — lies above everything, even the windows. -->
<Frage />

<!-- The server log, shown large. At the root for the same reason as the
     prompt: a window that must lie over everything cannot sit inside one. -->
<Protokollfenster />

<!-- What the program reports about itself, in the one strip that already
     had the shape for it: a hairline of quiet text under the input field,
     anchored to the sidebar on the left and the module rail on the right.

     It carried the version and the credit; those move into the settings,
     where a fact one reads once belongs. The readings that stood crowded
     into the header's right corner stand here instead, and the header keeps
     the room for what it is actually about — which folders this chat works
     in.

     Not `aria-hidden` any more, and taking pointer events again: a version
     number is decoration, live readings are not, and their explanations
     hang on hovering them. The permission mode left the strip for its chip
     in the input bar's row. -->
{#if !seiteOffen}
<div
  class="fussstreifen"
  style:--fuss-links="{(zustand.seitenleisteEingeklappt ? 52 : zustand.seitenBreite) + 8}px"
  style:--fuss-rechts="{(leiste.offen ? leiste.breite : 52) + 8}px"
>
  <!-- The picture count reflows in here on its own: it shows only while
       pictures are being made. -->
  <Bildwarteschlange />
  <!-- In the studio the strip speaks of the picture server instead
       (Serverpunkt.svelte); the language model's flash attention says
       nothing about a picture. -->
  {#if !studioAn}
    <Flashpunkt />
    <span class="statustrenner" aria-hidden="true"></span>
  {/if}
  <Serverpunkt />
  <span class="statustrenner" aria-hidden="true"></span>
  <!-- The figures name themselves, like the two readings before them. -->
  <span class="wort">{t('kopf.speicher')}</span>
  <Speicherpille />
</div>
{/if}

<style>
  /* The frame: the ground the sidebar lies on and the surfaces sit on. It
     wears the appearance's gradient over the whole window; the sidebar
     lies on it without a ground of its own, and a menu page's left column
     takes it up again, fixed to the window, so it runs on without a seam. */
  .fenster {
    height: 100%;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    background: var(--frame);
    /* Anchor for the drawing lying on the frame: it stays under `.rumpf`,
       which is positioned and comes later in the tree. */
    position: relative;
  }
  /* The word beside a reading — "Speicher" before the figures. Never
     wraps and never shrinks: it names what follows, and a name broken over
     two lines in a 10.5px strip is worse than one that overflows. */
  .fussstreifen .wort {
    flex: none;
    white-space: nowrap;
  }
  /* A hairline between two readouts that report different things: without
     it the dots and words run together into one sentence. */
  .statustrenner {
    flex: none;
    width: 1px;
    /* Well short of the line's own height, with air on both sides: a mark
       between two readings, not a rule drawn through the header. */
    height: 9px;
    margin: 0 4px;
    background: var(--linie-stark);
  }
  /* The chat sits on the frame, 8px from its edges; the two columns lie on
     the frame itself, one on either side. */
  .rumpf {
    flex: 1;
    display: flex;
    min-height: 0;
    position: relative;
    padding: 8px 0;
  }
  /* Only there to carry `inert` over the tool surface while the Models page
     lies over it; takes no box of its own. */
  .untermseite {
    display: contents;
  }
  /* While a menu page is open, the chat and the column right of it are not
     drawn at all — nothing of them shows through the page — yet they stay
     loaded: history, scroll position and input are all there on return. */
  main.covered,
  .untermseite.covered {
    visibility: hidden;
  }
  /* The studio over the chat tile: the chat's own layers and its drawing
     step out of sight but stay where they are, so the history keeps its
     scroll position and the bar what was typed into it. */
  main.studio > :is(.chatkopf, .verlauf, .anlauf, .unterraum),
  main.studio > :global(:is(.wasserzeichen, .vektorfeld)) {
    visibility: hidden;
  }
  /* The chat: its own surface, the content ground with the house corner. */
  main {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
    margin: 0 8px;
    border-radius: 9px;
    /* Glass: every look gives this tile a ground of its own. Where the
       frame is a gradient, the look names that gradient already mixed
       with the glass and the tile draws it itself, fixed to the window
       as the frame is, so the two run on without a seam; elsewhere the
       ground is see-through. The edge and the shadow lift the tile off
       the frame. */
    background: var(--kachel-verlauf, var(--kachel-chat, var(--bg)));
    background-attachment: fixed;
    box-shadow: var(--chat-edge, none);
    /* Anchor for the watermark and the drawing behind it: the chat's own
       layers carry their levels (`.verlauf`/`.anlauf` at 1, `.chatkopf`
       at 3), so the unlayered drawing stays underneath. */
    position: relative;
  }
  /* The chat's head lies over the top of the surface: the chat's name.
     Only its children take the pointer, so the history under its empty
     middle stays reachable. */
  .chatkopf {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    z-index: 3;
    display: flex;
    align-items: center;
    gap: 10px;
    height: 44px;
    padding: 0 8px 0 18px;
    border-radius: 9px 9px 0 0;
    pointer-events: none;
  }
  .chatkopf > :global(*) {
    pointer-events: auto;
  }
  .chatname {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 13px;
    font-weight: 500;
    color: var(--text);
  }
  /* History and input lie above the symbol — otherwise it swallows
     clicks and the text would sit behind it instead of in front. */
  .verlauf,
  .anlauf {
    position: relative;
    z-index: 1;
  }
  .verlauf {
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
    /* The browser's scroll anchoring is switched OFF. It moves scrollTop
       on its own whenever an element above the anchored content changes
       size — a live head giving way to text, a reading mark vanishing,
       the seam appearing — and every follow-along bug in the field was
       exactly such a move: the view jumped up without the reader doing
       anything. Nothing in this program scrolls up on purpose, and the
       follow-along below owns the floor; the browser is not a second
       hand on the same wheel. */
    overflow-anchor: none;
    /* K3: the picture row breaks out of the text column (see
       .bildlauf-raster) up to the WIDTH THIS ELEMENT HAS — never the
       viewport's, which would run under the sidebar. Container query
       units resolve against the nearest ancestor with a container-type,
       so this is that ancestor: already the exact box a picture row may
       fill, sidebar already excluded by the app's own layout. */
    container-type: inline-size;
    /* The paddings sit in the track, not here: with flex-basis 0,
       paddings count toward the minimum size, so the history would get
       52 pixels more than the space below and the centered group would
       sit 26 pixels too low. */
    /* Fade-out instead of a hard edge: the messages
       don't end abruptly above the input field but dissolve in a soft
       gradient. The mask sits on the container, not the content — when
       scrolling, the text emerges from the mist. */
    --auslauf: 64px;
    /* The head has no ground of its own, so the glass of the chat shows
       through it: while there are messages they melt out over the head's
       height instead, and a message scrolled up disappears under the name.
       Both edges live in this one mask and hold while scrolling — no
       scroll fade writes a mask of its own over it. */
    --head-fade: 0px;
    -webkit-mask-image: linear-gradient(
      to bottom, transparent, #000 var(--head-fade),
      #000 calc(100% - var(--auslauf)), transparent
    );
    mask-image: linear-gradient(
      to bottom, transparent, #000 var(--head-fade),
      #000 calc(100% - var(--auslauf)), transparent
    );
  }
  .verlauf.under-head {
    --head-fade: 44px;
  }
  /* The measuring point for anything that wants to be wider than the text
     column. A code block may reach past the reading width, but only where
     there is actually room for it — with the rail open the chat area gets
     narrow, and an overhang that ignores that would run under the rail.
     Asking the scroll area itself is the only honest way to know. */
  .verlauf { container-type: inline-size; }
  .spur {
    max-width: var(--chat-breite, 1400px);
    margin: 0 auto;
    font-size: var(--chat-schrift, 17px);
    /* More air at the bottom than at the top: the last bubble has to be
       able to stand above the fade-out, otherwise its end would hang in
       the gradient permanently.

       The top clears the chat's head, which lies over this field. Without it
       the first message would start underneath the head and be read
       through it. */
    padding: 46px 28px 84px;
    display: flex;
    flex-direction: column;
    /* The room between two messages, set in the layout mode. */
    gap: var(--chat-abstand, 40px);
    min-width: 0;
  }
  .spur > :global(div) {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  /* Images per run: a row that wraps, not a fixed grid — two tiles fit
     side by side, a third has nowhere to go but its own line below,
     which `justify-content: center` then centers on its own regardless
     of how many tiles share it. Exactly two per row comes from each
     tile's own wrapper claiming half the row (see .bildlauf-platz),
     not from a fixed row width; nothing here is aware of the actual
     tile count.

     K3: the row is not bound to the text column's own width — a
     picture has none of the readability reason that column is capped
     for (see the comment on --chat-breite), so it may fill up to
     --bildlauf-kachel-deckel (two tiles' worth, set inline from
     BILDLAUF_KACHEL) of the surrounding `.verlauf`, container query
     units rather than viewport ones so it stops at the sidebar, never
     under it. `min()` against 100cqw covers both directions of the
     acceptance for this: capped at the tile ceiling when there is
     room, shrunk to fit when there is not — a narrow window scales the
     row down instead of overflowing it.

     K5 (Aufseher): the breakout itself is `width: min(...)` together
     with `align-self: center` below — measured, 8 of 8 font/window
     combinations identical with or without a pair of equal left/right
     margins, because equal margins on a centered, width-capped flex
     item cancel out and move nothing. Removed rather than left standing
     as dead weight next to the real mechanism — the comment describing
     it as THE mechanism was itself the trap: whoever touches this next
     reads the wrong line as load-bearing and keeps it while trimming
     something that matters. */
  .spur > .bildlauf-raster {
    flex-direction: row;
    flex-wrap: wrap;
    /* Packed from the LEFT, not centred. The row's own width is fixed
       (two tiles plus the gap, below) and the row itself is centred in
       the column by `align-self` — so left-packing changes nothing about
       where the row sits, only that a tile stays where it landed. With
       `center` the row re-centred its CONTENT on every new picture: one
       picture stood in the middle, the second shoved it left, the third
       centred itself alone on the next line. Nothing is reserved here
       either way — an empty slot for a picture that may never come is
       exactly what this row does not do (see the comment above). */
    justify-content: flex-start;
    align-self: center;
    gap: 12px;
    width: min(var(--bildlauf-kachel-deckel), calc(100cqw - 40px));
  }
  /* Each tile's actual pixel size (Nachricht.svelte's `--bild-deckel`,
     set from the same BILDLAUF_KACHEL) only ever shrinks an image DOWN
     to fit its own box — it never grows the box to fit the image. This
     wrapper is that box: exactly half the row per tile (the 6px is
     half the row's own 12px gap), so on a narrow window the row itself
     shrinks (see .bildlauf-raster) and every tile shrinks in step with
     it, still two per line, instead of the fixed-size tiles forcing an
     overflow or a fall back to one per line. */
  .bildlauf-platz {
    /* As wide as the picture is, never wider than half the row. The
       basis used to be that half outright, so a picture narrower than
       its box — a portrait one, whose height hits the cap first, or a
       tile size set below half the row — left the remainder standing
       INSIDE the box, and with two tiles that remainder collected in
       the middle as a gap that matched nothing. The cap stays: it is
       what keeps a narrow window shrinking the row and its tiles in
       step, two per line, instead of leaving fixed tiles to overflow or
       fall back to one per line. */
    flex: 0 1 auto;
    max-width: calc(50% - 6px);
    /* A tile is not a chat bubble. `Nachricht.svelte` caps every answer
       at `--blase-ki-breite` and places it by `--blase-ki-stelle` —
       both belong to the reading column and are meaningless for a
       picture in a grid, but they applied here all the same, and once
       the box above stopped forcing half a row they became the thing
       that decided a tile's width: measured at 226px inside a 395px
       box, three tiles to a line instead of two. Pinned locally, so
       the tile is exactly as wide as its picture (which
       `--bild-deckel` already caps) and sits at its cell's own left
       edge, whatever the two sliders are set to. */
    --blase-ki-breite: 100%;
    --blase-ki-stelle: 0;
  }
  /* A run that finished short of its own count — the house colour for
     "failed", same as a tool's own failed marker (Nachricht.svelte's
     .werkzeug.misslungen). Quiet by size, not by colour: a fact worth
     seeing, not an alarm. */
  .bildlauf-teilweise {
    align-self: center;
    margin: -4px 0 0;
    font-size: 12.5px;
    color: var(--rot);
  }
  .anlauf {
    flex: none;
    display: flex;
    flex-direction: column;
  }
  .marke {
    /* Full width, otherwise the box shrinks to content width and the
       wordmark's optical compensation runs out of it — overflow then
       clips the drawing on the left. The greeting stands under the
       wordmark and folds away with it. */
    width: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    overflow: hidden;
    max-height: 180px;
    margin-bottom: 28px;
    transition: max-height var(--anlauf-dauer) var(--anlauf-schwung),
                opacity calc(var(--anlauf-dauer) * 0.5) ease,
                margin-bottom var(--anlauf-dauer) var(--anlauf-schwung);
  }
  .marke.weg {
    max-height: 0;
    opacity: 0;
    margin-bottom: 0;
  }
  /* The wordmark alone is dimmed; the greeting under it keeps its own
     quiet ink. */
  .marke .wortmarke {
    width: 100%;
    display: flex;
    justify-content: center;
    opacity: 0.5;
  }
  .unterraum {
    flex: 1 1 0;
    transition: flex-grow var(--anlauf-dauer) var(--anlauf-schwung);
  }
  .unterraum.zu {
    flex-grow: 0;
  }
  @media (prefers-reduced-motion: reduce) {
    .marke,
    .unterraum {
      transition: none;
    }
  }

  @media (max-width: 720px) {
    .spur {
      padding: 46px 18px 26px;
    }
  }

  /* Centred under the CHAT column, not under the window: the column's
     middle travels with the sidebar and the work rail, so the strip stays
     centred while both open and close instead of drifting into a corner.
     Fixed to the bottom edge, so it never scrolls with the conversation. */
  /* The foot strip. Same anchoring and the same 10.5px the signature had —
     it is the flattest line in the program and stays that way; a reading
     that shouts down here would be shouting under the field somebody is
     typing in.

     No `opacity` any more: the signature was dimmed because it was a
     credit, and these are live readings. A dimmed reading is a reading one
     doubts.

     And `--text-leise`, not the quieter `--text-still` this first carried.
     Contrast is a property of the colour, not of the size — the readings
     may be small AND readable, and they were not: measured against each
     ground, `--text-still` gives 3.39:1 on light, 3.59:1 on dark, 3.55:1 on
     heaven, all under the 4.5:1 a sentence needs. `--text-leise` is what
     they carried in the header and puts them back at 4.76 and 7.12. The
     size stays where it is; the colour was the wrong half to save on.

     Above the windows (70) so it never disappears under one — and the BOX
     still takes no clicks, only the readings inside it do.

     That distinction is the whole point and was nearly lost here. The
     signature could be click-through as a whole because nothing in it
     wanted a pointer. The readings do: their explanations live in a
     `title` and nowhere else. But the box is a band the full width of the
     chat column at z-index 80, and every window's scrim sits at 70 — so a
     box that takes clicks swallows every click on the scrim in the bottom
     twenty pixels, and the window does not close. Measured: settings,
     tools and catalogue share that scrim
     (`Fenster.svelte`), and it closes on a click that reaches IT.

     `pointer-events: none` on the strip, `auto` on the children: the gaps
     between the readings stay transparent to the pointer, each reading
     answers a hover, and the scrim keeps its clicks. */
  /* Inside the chat's surface: from its left edge to its right, 4px above
     its foot, so it keeps clear of the input bar above it. The two edges
     follow the sidebar and the tool surface. */
  .fussstreifen {
    position: fixed;
    bottom: 12px;
    left: var(--fuss-links);
    right: var(--fuss-rechts);
    z-index: 80;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 7px;
    font-size: 10.5px;
    letter-spacing: 0.02em;
    /* The strip lies on the bare frame, like the two columns, so it wears
       their ink: the frame's gradient darkens towards the corners, and the
       quiet ink fell under the contrast text needs there. */
    color: var(--rahmen-text, var(--text-leise));
    user-select: none;
    pointer-events: none;
  }
  /* `:global`, and it is load-bearing: four of the five readings are
     components of their own, so Svelte's scoped `>` selector never reaches
     their root elements. Without it the rule matches nothing, every reading
     stays click-through, and the `title` that is the whole reason for this
     pair of rules never opens. Measured before it was written: the memory
     figures reported `pointer-events: none` with no window in the way. */
  .fussstreifen > :global(*) {
    pointer-events: auto;
  }
  /* On a narrow window the bars of signs stand on both sides and the tool
     sheet lies over the chat, so the strip spans the chat between the bars
     — and it goes under the sidebar drawer (40) and the tool sheet (45)
     laid over it, because the readings belong to the chat. After the rule
     above, or that rule's own edges would win. */
  @media (width < 760px) {
    .fussstreifen {
      left: 60px;
      right: 60px;
      z-index: 35;
    }
  }
</style>
