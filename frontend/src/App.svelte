<script>
  import { tick, untrack } from 'svelte'
  import { fly } from 'svelte/transition'
  import { backOut } from 'svelte/easing'
  import Seitenleiste from './teile/Seitenleiste.svelte'
  import { ordnerstandPruefen } from './lib/arbeitsordner.svelte.js'
  import Seitengriff from './teile/Seitengriff.svelte'
  import Arbeitsleiste from './teile/Arbeitsleiste.svelte'
  import Erststart from './teile/Erststart.svelte'
  import Updatekarte from './teile/Updatekarte.svelte'
  import Begruessungsecke from './teile/Begruessungsecke.svelte'
  import Nachricht from './teile/Nachricht.svelte'
  import Eingabeleiste from './teile/Eingabeleiste.svelte'
  import Wartezeile from './teile/Wartezeile.svelte'
  import SystemPrompt from './teile/SystemPrompt.svelte'
  import ModelleSeite from './teile/ModelleSeite.svelte'
  import Katalog from './teile/Katalog.svelte'
  import DownloadIndicator from './teile/DownloadIndicator.svelte'
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
  import { t } from './lib/texte.svelte.js'

  import {
    zustand,
    modelleLaden,
    featuresLaden,
    chatsLaden,
    neuerChat,
    frageBeantworten,
    seitenleisteSchalten,
    sucheZeigen,
    chatFertigGesehen,
    menueFensterOeffnen,
    laufVon,
    darstellungAnwenden,
    seitenleisteAnwenden,
    modellAnwenden,
    seitenSchliessen,
    seiteZeigen,
    eineSeiteOffen,
    rahmenNeuZeichnen,
    geraet,
  } from './lib/zustand.svelte.js'
  import { protokollOffen } from './lib/protokollfenster.svelte.js'
  import { deferQuestion, isDeferred, questionCardStands, standingQuestion } from './lib/questionbox.svelte.js'
  import { anzeigeLaden, modusSpeichern, startModus } from './lib/anzeige.js'
  import { chatanzeige, scrollstelleSpeichern } from './lib/chatanzeige.svelte.js'
  import { begruessung, begruessungLaden } from './lib/begruessung.svelte.js'
  import { updatesStart } from './lib/updates.svelte.js'
  import { tellShellWords } from './lib/shellWords.js'
  import { verbinden as terminalVerbinden, STUDIO_RUNS } from './lib/terminalfenster.svelte.js'
  import { klangwahlLaden } from './lib/klaenge.svelte.js'
  import { meldewesenLaden } from './lib/meldewesen.svelte.js'
  import { auftraegeBeobachten } from './lib/auftragsmelder.js'
  import { verbinden as ereignisseVerbinden, trennen as ereignisseTrennen } from './lib/ereignisstrom.svelte.js'
  import { bildLokalZeichnen, stopOnePicture, removeWaitingPicture } from './lib/bildlinie.svelte.js'
  import { standLaden as agentenserverStandLaden } from './lib/agentenserver.svelte.js'
  import {
    leiste, leisteAnwenden, moduleShow, schalten as leisteSchalten, schliessen as leisteSchliessen,
  } from './lib/arbeitsleiste.svelte.js'
  import Warteblasen from './teile/Warteblasen.svelte'
  import Hauszeichen from './teile/Hauszeichen.svelte'
  import { entfernen } from './lib/warteschlange.svelte.js'
  import {
    nachrichtenAnzeige,
    eigeneZeilenSichern,
    eigeneZeilenZurueckgeben,
  } from './lib/zustand.svelte.js'
  import { fitColumns, watchWindowWidth } from './lib/columnRoom.svelte.js'
  import { chatFehlerGesehen } from './lib/chatringe.svelte.js'
  import { glideStep } from './lib/glide.js'

  import { chatRun } from './lib/chatlauf.svelte.js'
  import { useChatAnsicht } from './lib/chatansicht.svelte.js'
  import { useQueueDrive } from './lib/queueDrive.svelte.js'

  import { windowButtonsInPage, RAIL_WIDTH, narrow, reportRail } from './lib/windowButtons.svelte.js'

  /* The window buttons stand in the first row of the sidebar (the Mac, in the
     program's own window): the page says to the shell which shape the sidebar
     has, the open one or the narrow bar of signs, and the shell puts them
     where that shape wants them. */
  $effect(() => {
    reportRail(zustand.seitenleisteEingeklappt || narrow.now)
  })

  /* The run of the chat — sending, the answer, stopping, the queue — lives in
     lib/chatlauf.svelte.js and is shared with the phone page. This window
     hands the run its view (see `ansicht` below) and reads its state. */
  const {
    senden,
    abbrechenVonHand,
    neuErzeugen,
    frageNeuSenden,
    takeBackQueued,
    antwortWiederAnhaengen,
    bildDateien,
    anspruchWarten,
    compactSince,
  } = chatRun
  const laufAktuell = $derived(chatRun.laufAktuell)

  /* What the list shows of the run — the waiting mark, the clocks, the picture
     tiles — is set up in lib/chatansicht.svelte.js, the same for the phone page. */
  const ansicht = useChatAnsicht()
  useQueueDrive()
  const { zeileLaeuft, bildKacheln, laufendeKachel, inKachelAufgegangen, teilausfall, BILDLAUF_KACHEL_RAHMEN } = ansicht
  const BILDLAUF_KACHEL = $derived(ansicht.BILDLAUF_KACHEL)
  const laufMarke = $derived(ansicht.laufMarke)
  const laufZeit = $derived(ansicht.laufZeit)
  const wartewort = $derived(ansicht.wartewort)
  const compactFrom = $derived(ansicht.compactFrom)
  const compactClock = $derived(ansicht.compactClock)
  const dateienVorherKarte = $derived(ansicht.dateienVorherKarte)
  const letzteAntwort = $derived(chatRun.letzteAntwort)
  const letzteFrage = $derived(chatRun.letzteFrage)


  /* The window gives the chat its minimum width before it gives a column its
     own: when the room runs short the tools fold first, then the sidebar,
     and each comes back by itself when the room returns. */
  $effect(() => watchWindowWidth())
  $effect(() => fitColumns())

  /* The terminal listens to the open chat — its runs, its lines — and to the
     studio's own list while the studio is what the window shows. */
  $effect(() => {
    terminalVerbinden(studioSichtbar() ? STUDIO_RUNS : zustand.aktiverChat)
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
     element — no component has to know which one currently applies. It
     begins with the look the page painted before the first frame, so the
     service's answer finds the look in place instead of Exe. */
  let modus = $state(startModus())
  begruessungLaden()
  /* What the shell found of a newer version of the program, and every
     change of it from here on. In a browser there is no shell to ask. */
  updatesStart()
  /* The shell's own words — the right-click entries for a link and a
     picture — come from this page's catalogue, at the start and again
     whenever the language changes. */
  $effect(() => tellShellWords())

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
  const leistenZeichnung = $derived(moune ? 'huegel' : false)
  const eingabeZeichnung = $derived(moune ? 'pusteblume' : false)

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
  /* The run asks the window to scroll to the floor and to focus the field. */
  $effect.pre(() => chatRun.ansicht({ runter, eingabe }))

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
  /* Scrolling DOWN close to the floor re-engages. While an answer streams,
     the floor runs away faster than a wheel can chase it: a reader who
     turned back down never caught it, so following never resumed. Close
     means 70 pixels, measured at the moment of the tick: this near the
     floor a turn of the wheel can only mean "take me back". Higher up it
     is reading, and reading stays untouched — a finished chat as much as a
     running one. */
  const NEAR_FLOOR_PX = 70
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

  /* The view runs to the floor on a spring while the answer grows under a
     reader who stands there (`gleiteZumBoden`): the scroll events of that
     run are the program's own, so `scrollGeprueft` does not snap the view
     to the floor in the middle of it. */
  let gleitet = false

  /* Whether the round button that takes the reader back to the floor
     stands: only for a reader who has left it. While the view follows, the
     floor running away for a moment is not a reader who left. */
  let scrolledAway = $state(false)
  function checkScrolledAway() {
    if (!verlauf) return
    const abstand = verlauf.scrollHeight - verlauf.scrollTop - verlauf.clientHeight
    scrolledAway = !folgtMit && abstand > AM_BODEN
  }

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
    else if (folgtMit && !gleitet) verlauf.scrollTop = verlauf.scrollHeight
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
    checkScrolledAway()
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
    const ziel = { chatId, versatz: stelle.versatz, bilder: 0 }
    nachsetzenZiel = ziel
    requestAnimationFrame(() => stelleBild(ziel))
  }

  /* How long a place is waited for: this many animation frames from the
     moment it was set. A chat that is shorter than the place it was left at
     (messages taken out since) never reaches it, and waiting on for ever
     meant that a list growing past the old place much later set the view
     there again, away from the end, with following switched off. */
  const STELLE_BILDER_MAX = 30

  /* One frame of the wait: the place is set again (the list may have grown
     since), and after the last frame the view stays where it can stand, the
     remembered place is brought to it, and following depends on where that
     is — the floor follows again. Frames are counted here and nowhere else;
     the observer of the list's size calls `stelleNachsetzen` as often as it
     likes without costing any. A target that was reached, dropped or
     replaced by another chat's ends this chain. */
  function stelleBild(ziel) {
    if (nachsetzenZiel !== ziel) return
    stelleNachsetzen()
    if (nachsetzenZiel !== ziel) return
    ziel.bilder += 1
    if (ziel.bilder < STELLE_BILDER_MAX) {
      requestAnimationFrame(() => stelleBild(ziel))
      return
    }
    nachsetzenZiel = null
    if (!verlauf) return
    folgtMit = verlauf.scrollHeight - verlauf.scrollTop - verlauf.clientHeight <= AM_BODEN
    stelleMerken()
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
      if (fangSumme >= FANG_WEG && abstand <= NEAR_FLOOR_PX) runter(true)
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
    if (abstand <= NEAR_FLOOR_PX) runter(true)
  }
  function runter(erzwingen = false) {
    if (!verlauf) return
    if (erzwingen) folgtMit = true
    if (!folgtMit) return
    const schnappen = (sofort = false) => {
      /* Check again at execution time — the user may have bailed out in
         the meantime, and so may the restore of a chat's read position
         above, which turns following off before it puts the view back
         where the chat was left. Both ways below therefore ask again;
         neither may snap on a decision that was taken when it was
         scheduled rather than when it runs. */
      if (!folgtMit || !verlauf) return
      // Already at the floor: nothing to snap.
      if (verlauf.scrollHeight - verlauf.scrollTop - verlauf.clientHeight <= 0) return
      /* A new line moves the floor by a line's height at once; the view
         follows it on a spring instead of in one step. Where the reader
         asked for less motion, and from the timer below (a window nobody
         sees draws no frames), it is one step. */
      if (sofort || bewegungReduziert()) verlauf.scrollTop = verlauf.scrollHeight
      else gleiteZumBoden()
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
      schnappen(true)
    }, 150)
    frame = requestAnimationFrame(() => {
      clearTimeout(nachzuegler)
      schnappen()
    })
  }

  /* The spring (lib/glide.js, the same one the growing text of a running
     answer moves on): each frame the view covers the share of the way to the
     floor that the frame's time earns — the distance halves every
     `GLEIT_HALB_MS` — and at least a pixel, so it arrives. The floor is read
     again every frame, so lines that arrive while the view runs are part of
     the same run. It ends at the floor, or the moment the reader's wheel,
     finger or key has ended the following. */
  function gleiteZumBoden() {
    if (gleitet) return
    gleitet = true
    // The first step is taken as one frame's worth (16 ms).
    let zuletzt = performance.now() - 16
    const bild = () => {
      if (!folgtMit || !verlauf) {
        gleitet = false
        return
      }
      const abstand = verlauf.scrollHeight - verlauf.scrollTop - verlauf.clientHeight
      if (abstand <= 0) {
        gleitet = false
        return
      }
      const jetzt = performance.now()
      const dt = Math.min(100, jetzt - zuletzt)
      zuletzt = jetzt
      const weg = glideStep(abstand, dt)
      const vorher = verlauf.scrollTop
      verlauf.scrollTop = vorher + weg
      // A write that moves nothing (a rounding of the browser) ends the run at the floor.
      if (verlauf.scrollTop === vorher) {
        verlauf.scrollTop = verlauf.scrollHeight
        gleitet = false
        return
      }
      requestAnimationFrame(bild)
    }
    bild()
  }

  /* The text of a running answer lets its room out on its own spring
     (lib/glide.js) and says so in every frame it does. A reader who stands
     at the floor takes the floor in that very frame: following it a frame
     later on a second spring made the end of the answer dip at every new
     line and spring back. A new line of the chat (a question, a tool) still
     glides; the moment text grows under that glide, the floor is held, since
     a spring chasing growing text stays a fixed distance behind it. */
  function holdFloor() {
    if (!folgtMit || !verlauf) return
    if (verlauf.scrollHeight - verlauf.scrollTop - verlauf.clientHeight <= 0) return
    verlauf.scrollTop = verlauf.scrollHeight
  }
  const bewegungReduziert = () =>
    typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches

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
      checkScrolledAway()
    })
    beobachter.observe(verlauf)
    const spur = verlauf.querySelector('.spur')
    if (spur) beobachter.observe(spur)
    return () => beobachter.disconnect()
  })

  /* The button's click: back to the floor, and the view follows again. */
  function backToFloor() {
    runter(true)
    scrolledAway = false
    // The button goes with the click: the typing place takes the focus.
    eingabe?.fokus()
  }

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

  /* A menu page lies over the chat and its tool surface. While it does, both
     are out of reach for keys as well as for the eye: a key typed on the
     page must not send, stop or answer anything in a chat nobody can see. */
  const seiteOffen = $derived(eineSeiteOffen())
  /* The picture studio lies over the chat tile (teile/ImageStudio.svelte):
     the chat stays mounted underneath, hidden and out of reach. */
  const studioAn = $derived(studioSichtbar())
  /* The question card lies over the chat column: head, history and the part
     with the bar are out of reach for Tab while it stands, the card and its
     veil (moved into the column) stay operable. */
  const kartenSteht = $derived(questionCardStands(zustand.aktiverChat))
  /* Whether a veil of the card, the prompt dialog or the log window lies
     over the chat: the status strip then goes under it — as dark as the chat
     behind, out of reach for the pointer and for Tab. Over the windows it
     stays, as it always did. */
  const schleierSteht = $derived(kartenSteht || Boolean(zustand.frage) || protokollOffen())

  /* The CLI on the right: shown, or folded away while it is what the
     column shows. Folded, the client keeps running (teile/Terminal.svelte). */
  const cliOffen = $derived(leiste.offen && leiste.modul === 'cli')
  function cliSchalten() {
    if (cliOffen) leisteSchliessen()
    else moduleShow('cli')
  }

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
    } else if (ereignis.ctrlKey && !ereignis.metaKey && !ereignis.altKey && ereignis.key === '`') {
      // The CLI on the right, in and out of view — the same key the
      // editors with a built-in terminal answer to.
      ereignis.preventDefault()
      cliSchalten()
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
      else if (laufVon(zustand.aktiverChat) || anspruchWarten.has(zustand.aktiverChat) || compactSince[zustand.aktiverChat]) abbrechenVonHand()
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
</script>

<svelte:window onkeydown={tastatur} />

<!-- The live waiting mark, drawn by the answer it waits for (Nachricht.svelte,
     `marke`). -->
{#snippet wartemarke(nurMarke = false)}
  {#if laufMarke}
    <Wartezeile
      {nurMarke}
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
  {/if}
  <!-- `--seite-links`: where the chat surface starts, the left edge every
       menu page takes (Seitenrahmen.svelte) — the same sum the status strip
       below uses. -->
  <div class="rumpf" style:--seite-links="{(zustand.seitenleisteEingeklappt ? RAIL_WIDTH : zustand.seitenBreite) + 8}px">
    <Seitenleiste />
    <!-- Sits on the seam and belongs to neither side. Invisible at rest. -->
    <Seitengriff />

    <main class:covered={seiteOffen} class:studio={studioAn}>
      <!-- The chat tile's drawing, the first layer of the surface. -->
      {#if moune}
        <Vektorfeld art="farn" />
      {/if}
      <!-- The chat's own head: its name, and at the right end the sign of a
           running download. The tools have their signs in the
           column on the right. It lies over the top of the surface rather
           than pushing the history down, so the empty chat keeps its
           centred input. -->
      <div class="chatkopf" inert={seiteOffen || studioAn || kartenSteht}>
        {#if !nochLeer && chatTitel}
          <span class="chatname">{chatTitel}</span>
        {/if}
        <DownloadIndicator />
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
           onglidegrow={holdFloor} onwheel={radGedreht} ontouchstart={beruehrungBeginnt} ontouchmove={beruehrungZieht}
           ontouchend={beruehrungEndet} inert={seiteOffen || studioAn || kartenSteht}>
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
                <div class:from-queue={nachricht.fromQueue}
                     in:fly={nachricht.fromQueue ? { y: 0, duration: 0 } : { y: 12, duration: 420, easing: backOut }}>
                  <Nachricht
                    {nachricht}
                    dateienVorher={dateienVorherKarte.get(nachricht.id) ?? 0}
                    istLetzte={letzteAntwort && nachricht.id === letzteAntwort.id}
                    istLetzteFrage={letzteFrage && nachricht.id === letzteFrage.id}
                    laeuft={zeileLaeuft(nachricht)
                      && (nachricht.zustand === 'laeuft'
                          || Boolean(laufVon(zustand.aktiverChat)))}
                    marke={laufMarke && laufMarke.id === nachricht.id ? wartemarke : null}
                    bildDeckel={BILDLAUF_KACHEL}
                    {neuErzeugen}
                    neuSenden={frageNeuSenden}
                  />
                </div>
              {/if}
            {/if}
          {/each}
          <!-- A compaction asked for by hand is running: the same mark the
               fold in front of an answer wears, standing at the end of the
               track because no answer is there to carry it. -->
          {#if compactFrom !== null}
            <div class="komprimiert">
              <Wartezeile
                art="verdichtung"
                text={t('status.komprimiert')}
                zeit={compactClock}
              />
            </div>
          {/if}
          <!-- What has been typed but not yet said. Sits at the end of the
               track, exactly where it will land once the line moves on. -->
          <Warteblasen takeBack={takeBackQueued} />
        </div>
      </div>

      <!-- Wordmark and input are ONE group in normal flow. Nothing is
           absolutely positioned: the empty space below shares the room
           with the history, which puts the group exactly in the middle.
           On send it shrinks to zero and pushes the group down. -->
      <div class="anlauf" inert={seiteOffen || studioAn || kartenSteht}>
        {#if scrolledAway && !nochLeer}
          <button class="to-floor" onclick={backToFloor} aria-label={t('terminal.ans_ende')}
                  title={t('terminal.ans_ende')}>
            <Hauszeichen zeichen="pfeil_unten" groesse={14} strich={2.2} />
          </button>
        {/if}
        <div class="marke" class:weg={!nochLeer} aria-hidden={!nochLeer}>
          <div class="wortmarke"><Wortmarke hoehe={55} zentriert /></div>
          <!-- Mounted afresh whenever a chat turns empty, so greeting and
               date are those of that moment, not of the program's start. -->
          {#key nochLeer}<Begruessungsecke />{/key}
        </div>
        <Eingabeleiste bind:this={eingabe} {senden} abbrechen={abbrechenVonHand}
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
  class:unter={schleierSteht}
  inert={schleierSteht}
  style:--fuss-links="{(zustand.seitenleisteEingeklappt ? RAIL_WIDTH : zustand.seitenBreite) + 8}px"
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
  /* The waiting mark of a hand-made compaction, indented the way an
     answer's line is (Nachricht.svelte, `.antwortlinie`) so the mark sits
     where it sits under an answer. */
  .komprimiert {
    padding: 6px 0 6px 22px;
  }
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
    --head-clear: 0px;
    --head-fade: 0px;
    -webkit-mask-image: linear-gradient(
      to bottom, transparent, transparent var(--head-clear), #000 var(--head-fade),
      #000 calc(100% - var(--auslauf)), transparent
    );
    mask-image: linear-gradient(
      to bottom, transparent, transparent var(--head-clear), #000 var(--head-fade),
      #000 calc(100% - var(--auslauf)), transparent
    );
  }
  /* Over the height of the chat's name the text is not there at all, the
     way it is in every chat app that has a name on top; only below the name
     it melts in. `--head-clear` is the name's lower edge (the 44 px head,
     the 13 px name centred in it). */
  .verlauf.under-head {
    --head-clear: 32px;
    --head-fade: 56px;
  }
  /* The measuring point for anything that wants to be wider than the text
     column. A code block may reach past the reading width, but only where
     there is actually room for it — with the rail open the chat area gets
     narrow, and an overhang that ignores that would run under the rail.
     Asking the scroll area itself is the only honest way to know. */
  .verlauf { container-type: inline-size; }
  .spur {
    max-width: var(--chat-breite, 900px);
    margin: 0 auto;
    font-size: var(--chat-schrift, 16px);
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
    gap: var(--chat-abstand, 24px);
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
    color: var(--rot-text);
  }
  .anlauf {
    flex: none;
    display: flex;
    flex-direction: column;
  }
  /* The way back to the end of the chat: a round button over the middle of
     the input bar, in the house's round button (the bar's `+`). */
  .to-floor {
    position: absolute;
    left: 50%;
    top: -40px;
    z-index: 2;
    width: 30px;
    height: 30px;
    display: grid;
    place-items: center;
    padding: 0;
    border: none;
    border-radius: 50%;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text-leise);
    cursor: pointer;
    transform: translateX(-50%);
    animation: to-floor-in 0.15s ease-out;
    transition: color 0.15s;
  }
  .to-floor:hover {
    color: var(--text);
  }
  @keyframes to-floor-in {
    from { opacity: 0; }
  }
  @media (prefers-reduced-motion: reduce) {
    .to-floor { animation: none; }
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
  /* Under a veil: below the card's (4) and the dialogs' (80), above the
     chat's own layers. */
  .fussstreifen.unter {
    z-index: 3;
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
