<script>
  import { rollfade } from '../lib/rollfade.js'
  import { slide } from 'svelte/transition'
  import { adressTeile, codeKopierKlick, dateiTeile, dateienZahl } from '../lib/markdown.js'
  import { setContext, untrack } from 'svelte'
  import { lebendHtml } from '../lib/lebendhtml.js'
  import { maskieren } from '../lib/einfaerben.js'
  import { dateiFakten, dateizeichen, writingFacts } from '../lib/dateiarten.js'
  import { api } from '../lib/api.js'
  import { drawingMakesVideo, melde, zustand } from '../lib/zustand.svelte.js'
  import { studioWithPicture } from '../lib/studio.svelte.js'
  import { t, teile as textPieces, texte } from '../lib/texte.svelte.js'
  import { stoppuhr } from '../lib/dauer.js'
  import { aufrufZahl, blockDot, buendeln, lastCall } from '../lib/werkzeugbuendel.js'
  import { makeTextFlow } from '../lib/textFlow.js'
  import { SWITCH_MS, reducedMotion } from '../lib/softSwitch.js'
  import { folgtUnten } from '../lib/folgtunten.js'
  import { lineFloor } from '../lib/lineFloor.js'
  import { tempoGemessen, tempoTitelSchluessel } from '../lib/tempoquelle.js'
  import { takt, taktHalten } from '../lib/sekundentakt.svelte.js'
  import { skillAmAnfang } from '../lib/skills.svelte.js'
  import { bildZeigen } from '../lib/bildschau.svelte.js'
  import Leuchtpunkt from './Leuchtpunkt.svelte'
  import Wartezeile from './Wartezeile.svelte'
  import { terminal } from '../lib/terminalfenster.svelte.js'
  import { tabRemoveByAddress } from '../lib/vorschautabs.svelte.js'
  import { laufampel } from '../lib/laufampel.js'
  import { answerEnding } from '../lib/answerEnding.js'
  import { punktAtmet, punktPulsiert } from '../lib/meldewesen.svelte.js'
  import Bildfuellung from './Bildfuellung.svelte'
  import PictureMenu from './PictureMenu.svelte'
  import Videokachel from './Videokachel.svelte'
  import { isPicture, isVideo } from '../lib/media.js'
  import Dateikarte from './Dateikarte.svelte'
  import Agentenmarke from './Agentenmarke.svelte'
  import { chatJob, openTranscript } from '../lib/agentchat.svelte.js'
  import { openCall, rememberTrigger } from '../lib/callSelection.svelte.js'

  /* `marke`: the chat's live waiting mark (App.svelte, `wartemarke`), handed
     only to the answer it waits for. It stands as that answer's last entry
     on the line, in the place the next entry's dot will take. */
  let {
    nachricht, istLetzte = false, laeuft = false, neuErzeugen,
    istLetzteFrage = false, neuSenden, bildDeckel = 540, marke = null,
    /* How many files the answers before this one carry (`dateienDavor` in
       lib/markdown.js): file names count across the whole chat, so a
       second answer's first document is not "markdown-1.md" again. */
    dateienVorher = 0,
  } = $props()

  /* Which sections are unfolded, by position in the drawn list — thinking
     blocks and tool rows share one set, because they are now one list. A
     message can hold several thinking blocks, so a single boolean for "the"
     thinking block no longer says enough. */
  let offeneTeile = $state(new Set())

  /* What this row IS, beyond who said it. A finished background command
     and a compaction summary are both stored under a role that does not
     describe them — the report as `assistant` because the model has to read
     it back, the summary as `user` because that is how a model takes a
     recap of its own earlier work. Drawn by role alone, the first looked
     like something the model said and the second like something the reader
     typed. `art` is missing on rows written before the column existed;
     those read as ordinary messages, exactly as they always did. */
  const art = $derived(nachricht.art ?? 'nachricht')
  const istWerkzeugmeldung = $derived(art === 'werkzeugmeldung')
  const istVerdichtung = $derived(art === 'verdichtung')

  const istVonMir = $derived(nachricht.role === 'user' && !istVerdichtung)

  /* The seam is shut when the chat opens. What it hides is a summary of
     things the reader has RIGHT THERE, unfolded, a few rows up — the
     summary exists for the model, not for them. Open by default it would
     make a compaction cost more room than the compaction saved. */
  let verdichtungOffen = $state(false)

  /* Which conversation this message stands in — passed down to every file
     card below, which files its preview tab there and nowhere else.
     A message fetched from the server says so itself; one this window just
     pushed does not carry the field yet and is, by construction, in the
     chat that was open the moment it was pushed.

     Read ONCE, on purpose: `chatOeffnen()` sets the active chat before the
     new message list arrives, so a card still mounted from the chat being
     LEFT would otherwise re-read this mid-switch and hand its file to the
     chat being entered. The message it belongs to never moves house. */
  // svelte-ignore state_referenced_locally
  const chatId = nachricht.chat_id ?? zustand.aktiverChat

  /* The generated picture's display size, known BEFORE the picture exists:
     the ordered dimensions scaled into the `bildDeckel` cap (540 alone,
     smaller inside an images-per-run tile row — the caller's call, this
     component only ever draws the one size it is told). While the painter
     works the frame stands at 75% of that; the moment the picture is there
     the same frame grows to the full size. Without known dimensions
     (messages from the server's history) the picture renders at its
     natural size as before and nothing animates. */
  const bildFlaeche = $derived.by(() => {
    const b = nachricht.bildMasse?.breite, h = nachricht.bildMasse?.hoehe
    if (!b || !h) {
      if (!nachricht.bildLaeuft) return null
      // Working frame without known dimensions: 75% of the square cap.
      return { breite: Math.round(bildDeckel * 0.75), seite: '1 / 1' }
    }
    const faktor = Math.min(1, bildDeckel / b, bildDeckel / h)
    const voll = Math.round(b * faktor)
    return {
      breite: nachricht.bildLaeuft ? Math.round(voll * 0.75) : voll,
      seite: `${b} / ${h}`,
    }
  })

  /* A picked skill stands in the text as it was typed, so it is stored and
     survives a reload. Here it is only drawn apart: the name as a pill, the
     rest as the request. Checked against the list — a slash that hits
     nothing was a slash, not a skill. */
  const skillTeil = $derived(istVonMir ? skillAmAnfang(nachricht.content) : null)
  const ohneSkill = $derived(
    skillTeil ? (nachricht.content || '').slice(skillTeil.name.length + 1).trim() : ''
  )

  /* The document meta cards (4.1): come ready-built from the server —
     only the facts line is assembled here (kind · size · pages). The list
     wins over the scalar twin, exactly like on the message row itself. */
  const dokument = $derived(nachricht.dokument || null)
  const dokumentKarten = $derived(
    nachricht.dokumente?.length ? nachricht.dokumente : dokument ? [dokument] : [],
  )
  const anhangBilder = $derived(
    nachricht.role === 'user'
      ? (nachricht.anhaenge?.length ? nachricht.anhaenge : nachricht.bild ? [nachricht.bild] : [])
      : [],
  )
  /* What the file is, and stays: kind, size, pages — one page said as one. */
  function pageCount(pages) {
    if (!pages) return null
    return pages === 1
      ? t('nachricht.dokument_seiten_eins')
      : t('nachricht.dokument_seiten', { zahl: pages })
  }
  function fileFacts(karte) {
    return [(karte.typ || '').toUpperCase(), karte.kb ? `${karte.kb} KB` : null, pageCount(karte.seiten)]
      .filter(Boolean)
      .join(' · ')
  }
  /* The card's line: those facts, and — only where there is one — the word
     that the document did not reach the model. */
  function faktenZeile(karte) {
    return [fileFacts(karte), getragen(karte)?.wort ?? null].filter(Boolean).join(' · ')
  }

  /* What the latest answer carried of this document — the whole text, or
     no more than its name. The service writes it onto the message per
     answer, so it follows a model change or a regenerate. A fact, not a
     state, with no colour of its own. That the whole document travelled is
     the ordinary case: it is said under the pointer, and the card's line
     stays what the file is. That it did NOT travel stands in the line — the
     card is the one place that says so.
     Spelled out key by key rather than glued together, so the catalogue
     check sees every key. */
  function getragen(karte) {
    if (karte.getragen === 'ganz') {
      return { hinweis: `${t('nachricht.dokument_ganz')}\n${t('nachricht.dokument_ganz_hinweis')}` }
    }
    if (karte.getragen === 'kein_platz') {
      /* No second sentence under this one: the card already says the
         document was too large, and the sentence that used to stand there
         said the window "was full" — which is not what happened to a
         document that never fits into any window at all. */
      return { wort: t('nachricht.dokument_kein_platz') }
    }
    if (karte.getragen === 'abgelehnt') {
      /* Written after the answer came back refused: the plan said the whole
         document travelled, the provider said the request was too large.
         The wording is the one `dokument_kein_platz` carries: to the reader it is the same state — the document did not fit — and two sentences for one state would be two answers to one question. */
      return { wort: t('nachricht.dokument_abgelehnt') }
    }
    return null
  }

  /* An attachment's text is not IN the message — the card holds only the
     id, and Dateikarte.svelte fetches the text as soon as it stands open.
     Thrown errors are Dateikarte's to show inline, not this component's
     to toast: the card that asked is the card that failed.

     Fetched ONCE per document for the life of the page: the cards used to
     mount open, so every switch back into a chat fired one request per
     attachment for text that cannot have changed. They ship folded now and
     fetch on the first click instead, and the module-level memo keeps every
     later reopen from paying again. Capped — extracted documents can be
     big, and a day of chats must not keep them all. */
  const dokumentSpeicher = new Map()
  /* `fromFile` for a file a tool handed into the chat: its row holds no
     extracted text — the text is the file itself. */
  async function dokumentLesen(karte, fromFile = false) {
    let text = dokumentSpeicher.get(karte.id)
    if (text === undefined) {
      text = fromFile
        ? await api.documentFileText(karte.id)
        : (await api.dokumentLesen(karte.id)).text
      if (dokumentSpeicher.size > 24) dokumentSpeicher.clear()
      dokumentSpeicher.set(karte.id, text)
    }
    return text
  }
  /* A PDF is not text: the browser's own viewer draws its pages from the
     file itself, in the reader and in the rail beside the chat. Its card
     gets the file's address, and files its tab under this chat. */
  const isPdf = (karte) => String(karte.typ || '').toLowerCase() === 'pdf'
  const fileAddressOf = (karte) => (karte.id ? api.documentFileAddress(karte.id) : null)
  /* The working tile says what is being made: its answer's running drawing
     call is the video tool, or a picture is on its way. */
  const drawingWord = $derived(
    drawingMakesVideo(nachricht.answerId) ? t('nachricht.video_laeuft') : t('nachricht.bild_laeuft'),
  )
  // The filling inside the tile reads the same word for readers of a screen.
  setContext('tileWord', () => drawingWord)
  /* The files whose picture would not load (a text under a picture's name,
     a file that is gone): they stand as the card every other file wears,
     with name, kind and size and the way into the reader. */
  let pictureFailed = $state({})
  /* A picture a tool handed into the chat stands as a picture, the way a
     generated one does; every other file keeps its card. The picture is
     drawn from the file's address, so a row without one stays a card. */
  const isDeliveredPicture = (karte) =>
    Boolean(karte.id) && isPicture(karte.name) && !pictureFailed[karte.id]
  const deliveredPictures = $derived(dokumentKarten.filter(isDeliveredPicture))
  const deliveredFiles = $derived(dokumentKarten.filter((karte) => !isDeliveredPicture(karte)))
  const DOK_ZEICHEN =
    '<svg class="dok-zeichen" width="22" height="22" viewBox="0 0 64 64" fill="none" ' +
    'stroke="currentColor" stroke-width="5" stroke-linecap="round" stroke-linejoin="round">' +
    '<path d="M16 8 H38 L48 18 V56 H16 Z" />' +
    '<path d="M38 8 V18 H48" stroke-width="4.5" />' +
    '<path d="M25 34 H39 M25 44 H39" stroke-width="4.5" />' +
    '</svg>'

  /* The ✕ on a chat attachment: gone from the message, and with it from
     the context the next request rebuilds. Only for rows the server
     knows — an optimistic bubble still carries its local id. */
  const echteZeile = $derived(!String(nachricht.id || '').startsWith('eigen-'))
  async function bildAnhangWeg(name) {
    try {
      await api.anhangEntfernen(zustand.aktiverChat, nachricht.id, { bild: name })
      const rest = anhangBilder.filter((b) => b !== name)
      nachricht.bild = rest[0] ?? null
      nachricht.anhaenge = rest.length > 1 ? rest : null
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    }
  }
  async function dokumentAnhangWeg(karte) {
    if (!karte.id) return
    try {
      await api.anhangEntfernen(zustand.aktiverChat, nachricht.id, { dokument: karte.id })
      /* The file is gone: a PDF's tab in the rail would only show the
         service's refusal. Removed after the call went through, so a failed
         removal leaves the tab as it is. */
      tabRemoveByAddress(chatId, fileAddressOf(karte))
      const rest = dokumentKarten.filter((k) => k.id !== karte.id)
      nachricht.dokument = rest.length === 1 ? rest[0] : null
      nachricht.dokumente = rest.length > 1 ? rest : null
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    }
  }
  const hatInhalt = $derived(Boolean((nachricht.content || '').trim()))
  /* While the answer's text is under way the line below it holds only the
     mark: no word, no clock, no readings, no buttons. They would move down
     with every new line of text. The footer keeps its height, invisible, so
     that the end of the run lets nothing jump. Until the first word stands
     the wait row speaks as it always did. */
  const markeRuhig = $derived(laeuft && hatInhalt)
  /* Markdown is rendered once per distinct text, not once per chunk.

     While an answer streams, only the LAST section grows — every section
     before it is finished and its text never changes again. Keyed by the
     text itself, those keep hitting the cache and only the growing one is
     re-rendered. Without this, every arriving chunk would re-render every
     section of the message, and a long answer would get slower the longer
     it got — the very thing this rebuild is meant to fix.

     The cap keeps a very long conversation from holding every intermediate
     state of every answer; clearing outright is fine, the next draw simply
     renders again. */
  /* The pieces a message is drawn from — rendered HTML with the file cards
     standing between them. dateiTeile() memoises in lib/markdown.js now,
     shared with the agents panel: only the streaming section's text ever
     changes, so every finished section keeps hitting that cache instead
     of being rebuilt on each chunk. */

  /* The pieces of one section, with the files that follow one another
     gathered into a row: several cards in a row stand side by side and
     wrap, and the blank bit of text between two fences must not put each
     on a line of its own. A piece of text with something in it ends the
     row. */
  function cardRows(pieces) {
    const rows = []
    for (const piece of pieces) {
      const last = rows[rows.length - 1]
      if (piece.art === 'datei') {
        if (!piece.wert) continue
        if (last?.art === 'files') last.files.push(piece.wert)
        else rows.push({ art: 'files', files: [piece.wert] })
      } else if (piece.wert.trim() || last?.art !== 'files') {
        rows.push(piece)
      }
    }
    return rows
  }

  /* Still being written: the fence is open AND the answer is running. A
     message that was cut short ends in the same open fence, and its file is
     simply as far as it got — it is there, and says so like any other. */
  const isWriting = (file) => Boolean(file.open && laeuft)

  /* How many files stand in the sections BEFORE each one.

     File names are numbered across the whole message, but a message is
     drawn section by section — so each section has to be told where the
     count already stood. Without it every section restarts at one and two
     different files end up sharing a name, until a reload (which has no
     sections) renames them again.

     Counted with `dateienZahl` (memoised in lib/markdown.js): this derived
     re-runs on EVERY streamed chunk, and finished sections are immutable —
     scanning them again each time was a regex pass over the whole message
     on the tick that draws it. The LAST section is not counted at all: no
     section stands after it, so its count was pushed into a sum nobody
     ever read — and it is the one section that grows under the scan. */
  const versaetze = $derived.by(() => {
    const liste = []
    let bisher = dateienVorher
    for (let i = 0; i < teile.length; i++) {
      liste.push(bisher)
      const teil = teile[i]
      if (
        i < teile.length - 1 &&
        teil.art !== 'reasoning' && teil.art !== 'werkzeug' && teil.text
      ) {
        bisher += dateienZahl(teil.text)
      }
    }
    return liste
  })
  const stats = $derived(nachricht.stats || {})

  /* What this row IS, beyond who said it. A finished background command is
     an assistant row — the model has to read it in the next request — but
     it is not an answer, and drawing it as one is what put the same output
     in the chat twice. `art` is missing on rows written before the column
     existed; those read as ordinary messages, exactly as they always did. */

  /* How the run behind this message ended: `fertig`, `abgebrochen` or
     `fehler` — `laeuft` while it is still going. Its own column since the
     database learned to say so; before that it had to be read back out of
     which keys the metrics blob happened to carry, which is also why every
     row written by somebody else looked like an answer in progress.

     The blob is still read where the column is empty, so a message stored
     before the column existed keeps saying what it always said — the one
     reading the arrow under the last answer shares (lib/answerEnding.js). */
  const laufzustand = $derived(answerEnding(nachricht))

  /* The finished mark: the model has called the `goal` tool and said what
     it reached. Live it arrives on the message itself (App.svelte, SSE
     event `ziel`); after a reload it comes back out of the stored metrics,
     where the run writes it next to the tool log. One reading, two
     sources, and the live one wins — it is the newer of the two. */
  const ziel = $derived(nachricht.ziel ?? stats.ziel ?? null)

  /* The run ended at its token ceiling. The provider reads the backend's
     own word for it and the metrics carry the one boolean, so this asks a
     question instead of interpreting a vocabulary. Not while running: an
     answer still being written has not been cut off, it is unfinished. */
  const abgeschnitten = $derived(!laeuft && stats.abgeschnitten === true)

  /* The narrower case inside `abgeschnitten`: the model's whole context
     window ran out, not the answer's own length setting. Same boolean
     shape, read from its own field so the hint below can tell the two
     apart without guessing from the raw end reason. */
  const kontextfensterVoll = $derived(!laeuft && stats.kontextfenster_voll === true)

  /* The third case in the same family: the answer ended at a limit of the
     PROVIDER's while the window still had room — a maker's number, a cap
     learned from a refusal, or a server that decides the length itself.
     Its own field, because pointing at the answer-length setting would send
     the reader to a slider they never touched. */
  const anbietergrenze = $derived(!laeuft && stats.anbietergrenze === true)

  /* The thinking pass used up the whole answer length and left nothing
     visible. The field carries the catalogue key, because which of the two
     sentences is true depends on whose length ran out — one the user set,
     or the provider's own — and the service is where that is known. */
  /* The provider refused the request because the answer length the user set
     is as large as the whole window. Nothing folding can fix — the line says
     what to change. */
  const antwortlaengeZuGross = $derived(!laeuft && stats.antwortlaenge_zu_gross === true)

  const denkenAufgebraucht = $derived(
    !laeuft && typeof stats.denken_aufgebraucht === 'string'
      ? stats.denken_aufgebraucht
      : null,
  )

  /* Two compactions in a row failed, so automatic
     compaction is off for this chat. A line of its own beside the one above
     rather than instead of it: those two rule each other out — either the
     provider cut the answer or the window was full — while this one does
     not. An answer can be cut short AND have lost its compaction. */
  const komprimierenFehlgeschlagen = $derived(
    !laeuft && stats.komprimieren_fehlgeschlagen === true,
  )

  /* A summary row that was built without a model, because summarizing
     failed. Nothing writes such a row any more — a failed summary folds
     nothing — but the rows already stored keep their mark, and the seam
     still says so: they are mechanical, they have holes, and a reader
     wondering why the model below lost the thread should see that here. */
  const istNotfall = $derived(istVerdichtung && stats.notfall === true)

  /* A thinking stretch is running right now. App.svelte sets 'denkt' on
     every reasoning chunk and moves the reading on ('werkzeug', 'kontext',
     'schreibt') the moment anything else takes over, so this only ever
     holds while the LAST section is the reasoning one being written.

     Deliberately WITHOUT the old `!hatInhalt` test: that test was what made
     the first thinking stretch of a run behave differently from every later
     one — no head, no arrow, no way to the text. */
  const denktJetzt = $derived(laeuft && nachricht.taetigkeit === 'denkt')

  /* The line of the answer keeps its greatest height for as long as the
     answer runs (lib/lineFloor.js): a tool bundle folds the thinking and
     the calls before it into one row, and without a floor the answer would
     fall by that much and grow again with the next thinking. */
  let lineHeight = $state(0)
  let floorHeight = $state(0)
  $effect(() => {
    const floor = lineFloor(laeuft, lineHeight, untrack(() => floorHeight))
    if (floor !== untrack(() => floorHeight)) floorHeight = floor
  })

  /* The moment the CURRENT reasoning stretch began — the last section's own
     `seit` (App.svelte's textAnhaengen sets it once, when the section is
     opened, not on every chunk). The waiting mark's clock normally starts
     at the same moment; only thinking that resumes into a section left
     open over a started tool call keeps the section's older start here,
     while the mark counts the new stretch. Reasoning after a tool call therefore times
     itself from when THAT stretch started, not from the run's very start. */
  const denkSeit = $derived.by(() => {
    const letzter = nachricht.abschnitte?.[nachricht.abschnitte.length - 1]
    return letzter?.art === 'reasoning' ? letzter.seit : null
  })

  // Ticks only while a thinking stretch runs, on the chat's one clock — the
  // waiting mark below reads the same one (lib/sekundentakt.svelte.js).
  $effect(() => {
    if (!denktJetzt) return
    return taktHalten()
  })
  const verstricheneZeit = $derived(stoppuhr(takt.jetzt - (denkSeit ?? takt.jetzt)))

  /* An agent this answer started counts its time on the same clock while it
     works or waits; once it has stopped, the time it took. */
  const agentAtWork = $derived(
    teile.some((teil) => {
      const state = teil.art === 'werkzeug' ? chatJob(teil.werkzeug?.auftrag_id)?.state : null
      return state === 'laeuft' || state === 'wartet'
    }),
  )
  $effect(() => {
    if (!agentAtWork) return
    return taktHalten()
  })
  function agentRuntime(job) {
    const open = job.state === 'laeuft' || job.state === 'wartet'
    return stoppuhr((open ? takt.jetzt : Date.parse(job.updated_at)) - Date.parse(job.created_at))
  }
  // The call that started an agent: it is drawn as that agent's row.
  const startsAgent = (teil) =>
    teil.art === 'werkzeug' && teil.werkzeug?.name === 'start_job' && Boolean(teil.werkzeug.auftrag_id)
  /* The names of the agents this answer started. Every agent row keeps room
     for the longest of them, so what stands after the name begins at the
     same place in each row. */
  const agentNames = $derived([
    ...new Set(
      teile
        .filter(startsAgent)
        .map((teil) => chatJob(teil.werkzeug.auftrag_id)?.agent ?? teil.werkzeug.argumente?.agent ?? ''),
    ),
  ])

  /* How long a thinking stretch took, in milliseconds: from its own start to
     its own end — the first event after it that was not thinking (App.svelte,
     `endThinking`), so a wait on a tool confirmation after it is not
     counted. Thinking that goes on after such an event takes the end back
     (`textAnhaengen`). Without a recorded end, the start of whatever came
     next. A message loaded from the server has its stretches back from
     its stored sections, with the same ends; one written before those
     existed has none, and a stretch with neither has no end — both stay
     without a length rather than show an invented one. */
  function thinkMillis(i) {
    const beginn = teile[i]?.seit
    const ende = teile[i]?.endedAt ?? teile[i + 1]?.seit
    return beginn != null && ende != null ? ende - beginn : null
  }

  /* How long the thinking of one block took: its finished stretches by their
     own times, the one that runs by the clock. Null where no stretch has a
     length. */
  function blockThinkTime(eintrag) {
    let sum = 0
    let counted = false
    for (const { teil, i } of eintrag.eintraege) {
      if (teil.art !== 'reasoning') continue
      const laeuftHier = i === teile.length - 1 && denktJetzt
      const ms = laeuftHier ? takt.jetzt - (denkSeit ?? takt.jetzt) : thinkMillis(i)
      if (ms == null) continue
      sum += Math.max(0, ms)
      counted = true
    }
    return counted ? stoppuhr(sum) : null
  }

  /* A tool call's dot on the line — it carries the call's whole state, the
     row has no sign of its own. Red once it failed, yellow while it stands
     waiting for the reader (a permission, a question, a job to confirm — the
     three boxes over the input field), blue while it runs. A background run
     it started takes over from there: blue while the run goes, then the
     run's own green or red, breathing until somebody has read the report
     (`hintergrundStand`, the terminal's pulse switch). Everything else is
     green once it has run. */
  function werkzeugPunkt(werkzeug, stand) {
    if (werkzeug.fehlgeschlagen) return { farbe: 'rot', atmet: false }
    /* Only a call without a result waits: one id can stand for several
       calls, and the finished ones of that id are not the one asked about. */
    if (werkzeug.ergebnis === null && wartetAufNutzer(werkzeug.aufruf_id)) {
      return { farbe: 'gelb', atmet: punktPulsiert('chat') }
    }
    if (werkzeug.ergebnis === null) return { farbe: 'blau', atmet: punktPulsiert('chat') }
    if (stand) return { farbe: stand.farbe, atmet: stand.atmet && punktAtmet('terminal', stand.farbe) }
    /* A background run keeps how it ended, now steady — red if it broke,
       grey if somebody stopped it (over, not broken: the reading the panel
       and the rail give it, lib/laufampel.js). A run the service no longer
       holds (it was restarted) leaves nothing to read, so the call itself
       answers: it ran. A foreground call that returned a non-zero exit code
       is done, not failed: its code stands red in the row. */
    const lauf = werkzeug.lauf_nummer == null
      ? null
      : terminal.laeufe.find((l) => l.lauf === werkzeug.lauf_nummer)
    const ende = lauf ? laufampel(lauf.zustand) : null
    return { farbe: ende === 'rot' || ende === 'still' ? ende : 'gruen', atmet: false }
  }

  /* The permission question standing in this chat, if any — read for the
     running answer only, the one it belongs to. */
  const freigabe = $derived(zustand.werkzeugfrage[chatId] ?? null)
  function wartetAufNutzer(aufrufId) {
    return [zustand.werkzeugfrage, zustand.benutzerfrage, zustand.jobfrage].some(
      (fragen) => aufrufId && fragen?.[chatId]?.aufrufId === aufrufId,
    )
  }

  /* Whether anything at all came of this answer: thinking, a tool row,
     text, a picture or a file. A stopped answer that has one of them is said
     to be stopped by the foot alone — the red line below is for the answer
     of which nothing came. */
  const etwasKam = $derived(
    Boolean(
      (nachricht.reasoning || '').trim()
        || teile.some((teil) => teil.art === 'werkzeug' || teil.text?.trim?.())
        || nachricht.bild
        || nachricht.bildLaeuft
        || dokumentKarten.length,
    ),
  )
  /* The red line under an answer with no text: failed, silent, or stopped
     before ANYTHING came. Not an image answer (its text is empty by nature),
     not one cut off at the ceiling (the line below says that), and not a
     stopped answer that got somewhere — the foot says "abgebrochen". */
  const leereAntwort = $derived(
    !hatInhalt && !laeuft && !nachricht.bild && !nachricht.bildLaeuft && !abgeschnitten
      && !(laufzustand === 'abgebrochen' && etwasKam),
  )

  /* An aborted or failed answer must not remain standing as an empty
     box (3.7) — it says what happened. */
  const grund = $derived(
    laufzustand === 'fehler'
      ? t('nachricht.fehlgeschlagen')
      : laufzustand === 'abgebrochen'
        ? t('nachricht.abgebrochen_leer')
        : t('nachricht.stumm'),
  )

  /* Tools that ran for this answer.

     During the answer, the event stream fills `nachricht.werkzeuge`;
     after a reload the same comes from the stored measurements. Older
     messages have no `ergebnis` there — then it just says the tool
     ran. */
  const werkzeuge = $derived(
    nachricht.werkzeuge?.length ? nachricht.werkzeuge : (stats.werkzeuge ?? []),
  )

  /* What to draw, in the order it happened.

     A message streamed since the section list exists carries `abschnitte`:
     each entry says which kind came next, so a second thinking pass after a
     first paragraph is drawn where it belongs instead of being folded back
     into the one reasoning string at the top.

     A message loaded from the server gets the same list back from its
     stored metrics (`storedSections` below). One WITHOUT them — every
     message written before they were stored — falls back to the old fixed
     order: reasoning, then tools, then text. Old chats therefore look
     exactly as they did.

     Tools are looked up by call id rather than carried along, because
     `tool_result` fills the entry in `werkzeuge` afterwards; a copy taken
     at push time would keep showing an empty result. */
  /* A background run's state, for the card of the call that started it.

     Read off the run while the service still holds it (`terminal.laeufe`,
     live and after a reload alike — the panel's snapshot carries
     `gelesen`), and off the entry's stored ending once the run is gone
     from memory. Blue while it goes, green or red once it ended; the dot
     moves only until an answer has started that read the run's report,
     and never for blue — the house rule the rail's dot follows too
     (lib/meldewesen.svelte.js). */
  function hintergrundStand(werkzeug) {
    if (werkzeug.lauf_nummer == null) return null
    const lauf = terminal.laeufe.find((l) => l.lauf === werkzeug.lauf_nummer)
    /* No run in the service's memory means no run: the service was
       restarted, or the panel's snapshot has not arrived yet. Neither is
       "still going" — a card that read a missing exit code as blue kept
       saying "runs in the background" forever for a run stopped at the
       time limit, cut off by a shutdown, or simply older than the
       service. Nothing is drawn until a run is there to read. */
    if (!lauf) return null
    if (lauf.zustand === 'laeuft') return { farbe: 'blau', laeuft: true, atmet: false }
    /* Read — by the next answer, or by opening the card — the dot steps
       back entirely: green and red exist only while nobody has looked,
       the way the agents' sign reads. */
    if (lauf.gelesen || werkzeug.gesehen) return null
    /* The same reading the panel and the rail give the run (laufampel):
       a run somebody stopped is over, not broken, and gets no dot at all
       — the three places used to disagree about exactly that run. */
    const farbe = laufampel(lauf.zustand)
    if (farbe === 'still' || farbe === 'leer') return null
    return { farbe, laeuft: false, atmet: true }
  }

  // A stored time is a whole number of milliseconds or absent — anything
  // else would draw a nonsense duration.
  const isTime = (value) => value == null || Number.isInteger(value)

  /* A stored answer carries the same sections in its metrics: their order,
     and lengths into its `reasoning` and `content` (app/answer_sections.py).
     Rebuilt only when they add up to exactly the stored strings — anything
     else falls back to the fixed order below rather than cutting the text
     in the wrong places. */
  function storedSections() {
    const list = stats.sections
    if (!Array.isArray(list) || !list.length) return null
    const source = { reasoning: nachricht.reasoning ?? '', content: nachricht.content ?? '' }
    const position = { reasoning: 0, content: 0 }
    const sections = []
    for (const section of list) {
      if (section?.kind === 'tool') {
        if (typeof section.call_id !== 'string') return null
        sections.push({ art: 'werkzeug', aufruf_id: section.call_id })
        continue
      }
      if (!Object.hasOwn(position, section?.kind) || !Number.isInteger(section.length) || section.length < 0) {
        return null
      }
      if (!isTime(section.begin_ms) || !isTime(section.end_ms)) return null
      const start = position[section.kind]
      position[section.kind] = start + section.length
      const text = source[section.kind].slice(start, position[section.kind])
      sections.push(
        section.kind === 'reasoning'
          ? { art: 'reasoning', text, seit: section.begin_ms, endedAt: section.end_ms }
          : { art: 'content', text },
      )
    }
    if (position.reasoning !== source.reasoning.length || position.content !== source.content.length) {
      return null
    }
    return sections
  }

  const teile = $derived.by(() => {
    const live = nachricht.abschnitte?.length > 0
    const eigene = live ? nachricht.abschnitte : storedSections()
    if (eigene?.length) {
      /* A section takes the first entry with its call id that no section
         before it took: a server without ids numbers every round from zero,
         so the same id can stand for several calls. A stored entry keeps
         its call id as `kennung`. The live list does the same with
         `aufruf_id`, in the order the entries are written into
         (App.svelte, `tool_result`), so a running answer shows each row
         with its own result. */
      if (live) {
        const takenLive = new Set()
        const entryOf = (aufrufId) => {
          const werkzeug = werkzeuge.find(
            (w) => w && !takenLive.has(w) && w.aufruf_id === aufrufId,
          )
          if (werkzeug) takenLive.add(werkzeug)
          return werkzeug
        }
        return eigene
          /* The stored answer's rule for blank sections, so a running answer
             bundles the way it does after reload: blank thinking and blank
             text draw nothing and end no run of calls. The last section stays
             even blank — it is the one being written right now, and running
             thinking has to show its clock. */
          .filter(
            (a, k) =>
              k === eigene.length - 1 ||
              ((a.art !== 'reasoning' || a.text) && (a.art !== 'content' || a.text?.trim())),
          )
          .map((a) =>
            a.art !== 'werkzeug'
              ? a
              : a.writing
                ? { ...a, werkzeug: unbegunCall(a.writing) }
                : { ...a, werkzeug: entryOf(a.aufruf_id) },
          )
          // A live tool section whose entry is missing draws nothing rather
          // than an empty row — can only happen if the two lists drift apart.
          .filter((a) => a.art !== 'werkzeug' || a.werkzeug)
      }
      const taken = new Set()
      const gespeichert = eigene
        .map((a) => {
          if (a.art !== 'werkzeug') return a
          const werkzeug = werkzeuge.find(
            (w) => w && !taken.has(w) && (w.aufruf_id ?? w.kennung) === a.aufruf_id,
          )
          if (werkzeug) taken.add(werkzeug)
          return { ...a, werkzeug }
        })
        // A section whose entry is missing (a save taken while the tool was
        // still running) draws nothing, the way it does live.
        .filter((a) => a.art !== 'werkzeug' || a.werkzeug)
        // The fixed order's rules for text: blank thinking and blank text
        // draw nothing, and a tool report shows its output once, in the card.
        .filter((a) => a.art !== 'reasoning' || a.text)
        .filter(
          (a) => a.art !== 'content' || (a.text.trim() && !(istWerkzeugmeldung && werkzeuge.length)),
        )
      /* An entry of the tool log no section took still gets its card, after
         the ordered ones: losing a card on reload is worse than drawing it
         out of place. */
      const uebrig = werkzeuge
        .filter((w) => w && !taken.has(w))
        .map((w) => ({ art: 'werkzeug', werkzeug: w, aufruf_id: w.aufruf_id }))
      return [...gespeichert, ...uebrig]
    }
    return [
      ...(nachricht.reasoning ? [{ art: 'reasoning', text: nachricht.reasoning }] : []),
      ...werkzeuge.map((w) => ({ art: 'werkzeug', werkzeug: w, aufruf_id: w.aufruf_id })),
      /* A tool report says the same thing twice: the card carries the
         command and its output, and the text below repeats both. Both are
         written on purpose — the model reads only `content`, never the
         tool log (api/v1/generierung.py) — but the READER should see it
         once, in the card every other tool call already uses.

         Only when the card actually exists. A stored report whose tool log
         is missing would otherwise show nothing at all, and losing the
         output is worse than showing it twice. */
      ...(hatInhalt && !(istWerkzeugmeldung && werkzeuge.length)
        ? [{ art: 'content', text: nachricht.content }]
        : []),
    ]
  })


  /* A call that has not begun: the model is still writing it, or has
     written it and its turn has not come (App.svelte, `callBeingWritten`).
     It has no entry in the tool log yet and is drawn as a running call's
     row from what is known of it: its name and, while it is written, the
     number of characters so far — `written` is null once it is written. */
  function unbegunCall(writing) {
    return {
      name: writing.name,
      written: writing.written,
      unbegun: true,
      argumente: {},
      ergebnis: null,
      fehlgeschlagen: false,
    }
  }

  /* The same parts, with every run of thinking and calls between two pieces
     of text gathered into one block (lib/werkzeugbuendel.js). */
  const anzeige = $derived(buendeln(teile))

  /* The block that still goes: the answer runs and nothing stands after it on
     the line. Its head ticks, its dot breathes, and below its closed head
     stands the newest step. */
  const lastEntry = $derived(anzeige.length ? anzeige[anzeige.length - 1] : null)
  const blockRuns = (eintrag) => laeuft && eintrag === lastEntry

  /* The block's dot follows the last call, as the terminal's last line does
     (lib/werkzeugbuendel.js, `blockDot`). */
  function blockState(eintrag) {
    return blockDot(
      eintrag.eintraege,
      blockRuns(eintrag),
      (werkzeug) => werkzeugPunkt(werkzeug, hintergrundStand(werkzeug)),
      punktPulsiert('chat'),
    )
  }

  /* The key a call has in the terminal's list (lib/werkzeughistorie.js): a
     shell command with a run number stands there as its run, every other
     call by its message and its place in the message's tool log. */
  function callKey(werkzeug) {
    if (werkzeug.name === 'run_command' && werkzeug.lauf_nummer != null) {
      return `l${werkzeug.lauf_nummer}`
    }
    return `${nachricht.id ?? ''}#${werkzeuge.indexOf(werkzeug)}`
  }

  /* A click on the row of a helper: its card unfolds in the agents view, and
     closing the column gives the focus back to the row. */
  function openHelper(jobId, row) {
    rememberTrigger(row)
    openTranscript(jobId)
  }

  /* What the line of a call says to somebody who does not see it: the words
     that no longer stand at its end — running, running in the background,
     waiting for the reader, the exit code or "failed". */
  function callWord(werkzeug, stand) {
    if (stand?.laeuft) return t('werkzeug.hintergrund_laeuft')
    if (stand?.atmet) return t('werkzeug.hintergrund_ungelesen')
    if (werkzeug.exit_code) return t('werkzeug.exit', { code: werkzeug.exit_code })
    if (werkzeug.fehlgeschlagen) return t('werkzeug.marke_fehlgeschlagen')
    if (werkzeug.ergebnis === null && wartetAufNutzer(werkzeug.aufruf_id)) return t('jobs.zustand.wartet')
    if (werkzeug.ergebnis === null) return t('werkzeug.buendel_laeuft')
    return ''
  }
  function callLabel(werkzeug, stand) {
    return [werkzeug.name, vorschau(werkzeug.argumente), callWord(werkzeug, stand)]
      .filter(Boolean)
      .join(', ')
  }

  /* How the text of the running answer comes up (lib/textFlow.js): the
     answer's last piece of text is let out evenly and its new characters
     fade in. Only this piece flows; every other stands whole. A stored
     answer and any text that was there when this window came stand whole at
     once. */
  const flowIndex = $derived.by(() => {
    for (let k = teile.length - 1; k >= 0; k -= 1) {
      if (teile[k].art === 'content') return k
    }
    return -1
  })
  const flowTarget = $derived(flowIndex >= 0 ? teile[flowIndex].text.length : 0)
  let flowLength = $state(0)
  let flowOn = $state(false)
  const flow = makeTextFlow({
    set: (length, flowing) => {
      flowLength = length
      flowOn = flowing
    },
    raf: (fn) => requestAnimationFrame(fn),
    caf: (id) => cancelAnimationFrame(id),
    reducedMotion,
  })
  $effect(() => {
    const index = flowIndex
    const target = flowTarget
    const going = laeuft
    untrack(() => flow.follow(index, target, going))
  })
  $effect(() => () => flow.cancel())
  /* The first `length` characters of `text`; a cut never falls between the
     two halves of one character. */
  function cutAt(text, length) {
    let end = length
    const code = text.charCodeAt(end - 1)
    if (code >= 0xd800 && code <= 0xdbff) end += 1
    return text.slice(0, end)
  }
  /* The text of part `i` as it stands now. */
  const textShown = (teil, i) =>
    flowOn && i === flowIndex ? cutAt(teil.text, flowLength) : teil.text

  /* The thinking comes in the same way: its last stretch flows and fades in,
     in the open block's window. A stored answer and what was there when the
     window came stand whole. */
  const thinkIndex = $derived.by(() => {
    for (let k = teile.length - 1; k >= 0; k -= 1) {
      if (teile[k].art === 'reasoning') return k
    }
    return -1
  })
  const thinkTarget = $derived(thinkIndex >= 0 ? teile[thinkIndex].text.length : 0)
  let thinkLength = $state(0)
  let thinkFlowing = $state(false)
  const thinkFlow = makeTextFlow({
    set: (length, flowing) => {
      thinkLength = length
      thinkFlowing = flowing
    },
    raf: (fn) => requestAnimationFrame(fn),
    caf: (id) => cancelAnimationFrame(id),
    reducedMotion,
  })
  $effect(() => {
    const index = thinkIndex
    const target = thinkTarget
    const going = laeuft
    untrack(() => thinkFlow.follow(index, target, going))
  })
  $effect(() => () => thinkFlow.cancel())
  const thinkShown = (teil, i) =>
    thinkFlowing && i === thinkIndex ? cutAt(teil.text, thinkLength) : teil.text

  /* How long a window or a row takes to come: one character's time. */
  const switchMs = () => (reducedMotion() ? 0 : SWITCH_MS)
  /* A new call row in the open window fades in and rises a little. */
  function rowIn() {
    return {
      duration: switchMs(),
      css: (t) => `opacity: ${t}; transform: translateY(${(1 - t) * 6}px)`,
    }
  }

  /* The follow-along of an open block: it keeps to its end while the block
     goes and lets go when it is over. */
  function followAlong(node, active) {
    let follower = active ? folgtUnten(node) : null
    return {
      update(next) {
        if (next && !follower) follower = folgtUnten(node)
        else if (!next && follower) {
          follower.destroy()
          follower = null
        }
      },
      destroy() {
        follower?.destroy()
      },
    }
  }

  /* The row at the end of the line keeps its place: while the answer runs the
     waiting mark stands in it, and when the answer is over the readings stand
     in the same row. Once an answer has run in this window the row stays,
     even where nothing was measured, so nothing below it moves when the mark
     goes. A stored answer has the row only where it has readings. */
  let hasRun = $state(false)
  $effect(() => {
    if (laeuft) hasRun = true
  })

  /* A foretaste in the header, so you don't have to unfold every row to
     see what was searched for. The first value suffices for that. */
  function vorschau(argumente) {
    const werte = Object.values(argumente ?? {})
    if (!werte.length) return ''
    const erster = typeof werte[0] === 'string' ? werte[0] : JSON.stringify(werte[0])
    return erster.length > 60 ? erster.slice(0, 60) + '…' : erster
  }

  function teilKlappen(i) {
    // A new Set, otherwise Svelte doesn't notice the change.
    const naechste = new Set(offeneTeile)
    naechste.has(i) ? naechste.delete(i) : naechste.add(i)
    offeneTeile = naechste
  }

  /* The numbers: how fast it wrote, how much of the prompt the server
     already had, and how long it took to the first token. The total
     duration used to be here too — removed: it is only the sum of the two
     operations anyway, and it said nothing the two beside it do not.

     The wait time deliberately stands as its OWN number next to it and
     not inside the speed — exactly how llama.cpp, mlx and LM Studio
     separate it. It is the processing of the prompt: the longer the
     chat, the larger it gets, while the speed stays the same. Stirring
     both into one value was a calculation error, since fixed. */
  /* One decimal place suffices: three places read
     like measurement equipment, not like a footnote under an answer. */
  const zahl = (wert) => Number(wert).toFixed(1)

  /* The speed of THIS answer stands first under it, live while it runs:
     the server's own reading of the moment (`liveSpeed`, set from the
     stream in App.svelte), and once the answer is done the figure the
     service measured over it. Only a reading the service MEASURED is shown,
     with what it counted as its hint (lib/tempoquelle.js). Whole numbers. */
  /* While the answer runs, ONLY the reading of the running round stands
     here, and with none there is no number. The `stats` a row carries
     while it runs are the service's snapshot of the rounds so far added
     together (a window that fetched the row fresh holds exactly that), so
     they are not this round's speed and must not read as if they were. */
  const speedReading = $derived(
    laeuft
      ? nachricht.liveSpeed?.wert
        ? nachricht.liveSpeed
        : { wert: null, quelle: null }
      : { wert: stats.tokens_pro_sekunde, quelle: stats.tempo_quelle },
  )
  /* A measured zero is a measurement: `0 TPS` is what a stalled answer
     reads, and only a missing reading may leave the line out — the same
     rule the cache share below spells out. */
  const tempoWert = $derived(
    typeof speedReading.wert === 'number' && tempoGemessen(speedReading.quelle)
      ? Math.round(speedReading.wert)
      : null,
  )
  const tempoTitel = $derived(
    tempoWert === null ? null : t(tempoTitelSchluessel(speedReading.quelle)),
  )
  /* How much of this prompt the server already had: while the answer runs,
     the reading it named on the way (App.svelte, `liveShare`); once the
     answer is done, the share its stats carry. An answer stored before that
     share existed falls back to the two halves — the cached one over both,
     which is the prompt wherever both are named, and only where the read-in
     half is missing over `prompt_tokens`, the whole prompt on the OpenAI
     form (app/providers/openai_kompatibel.py, `_prompt_cache_percent`).
     No reading, no part; a server that really reports nothing gets no
     share, and one that reports a zero gets a real "0 %". */
  const cachePercent = $derived(
    laeuft
      ? typeof nachricht.liveShare === 'number'
        ? nachricht.liveShare
        : null
      : typeof stats.prompt_cache_percent === 'number'
        ? stats.prompt_cache_percent
        : typeof stats.cache_tokens !== 'number'
          ? null
          : stats.eingelesen_tokens
            ? Math.round(
                (stats.cache_tokens / (stats.cache_tokens + stats.eingelesen_tokens)) * 100,
              )
            : stats.prompt_tokens
              ? Math.round((stats.cache_tokens / stats.prompt_tokens) * 100)
              : null,
  )
  /* The three readings of an answer, in the order speed, wait, cache. Each
     is a number with the word that says what it is: the number is what one
     reads, the word only names it. Both travel as one entry so the template
     can set them apart — the number in `--text`, the word in
     `--text-still`. */
  const messungen = $derived(
    [
      tempoWert === null
        ? null
        : { zahl: String(tempoWert), wort: t('nachricht.tps'), titel: tempoTitel },
      typeof stats.erstes_token_nach_sekunden === 'number'
        ? {
            zahl: `${zahl(stats.erstes_token_nach_sekunden)} s`,
            wort: t('nachricht.ttft'),
            titel: null,
          }
        : null,
      cachePercent === null
        ? null
        : { zahl: `${cachePercent} %`, wort: t('nachricht.cache'), titel: null },
    ].filter(Boolean),
  )
  /* The row of readings keeps its place while the answer runs, once it has
     stood. At every round border the live readings are cleared and the row
     would be gone — and copy and regenerate beside it slid left by its
     width, to jump back with the first new reading. So the last row stays,
     invisible and as wide as it was, until a new reading comes; it shows no
     number that is no longer true. Before the first reading there is no row
     to keep, and a finished answer shows what was measured, as it always
     did. */
  let zuletztGemessen = []
  const fussMessungen = $derived.by(() => {
    if (!laeuft) {
      zuletztGemessen = []
      return messungen
    }
    if (messungen.length) {
      zuletztGemessen = messungen
      return messungen
    }
    return zuletztGemessen
  })
  const messungenHaelt = $derived(laeuft && !messungen.length && fussMessungen.length > 0)
  /* The last row of the line is there while the mark goes and, once the
     answer is over, for the finished mark and its readings — in the same
     place and at the same height, so nothing moves when the running mark
     gives way (see `hasRun`). An answer that was stored has the row too,
     with or without readings: the line always ends on the mark. */
  const placeHeld = $derived(
    !laeuft && (fussMessungen.length > 0 || hasRun || (etwasKam && !nachricht.bild)),
  )
  /* What is not a reading: how the run ended, and the error it died of.
     Through `laufzustand`, the one reading of how the run ended, and not the
     blob: a row the service stamped aborted after a crash carries the column
     and no key in the blob, and this line said nothing while the bubble
     above said "aborted". */
  const hinweise = $derived(
    [
      laufzustand === 'abgebrochen' ? t('nachricht.abgebrochen_kurz') : null,
      laufzustand === 'fehler' ? t('nachricht.fehler_kurz', { text: stats.fehler ?? '' }) : null,
    ].filter(Boolean),
  )


  function kopieren() {
    navigator.clipboard
      .writeText(nachricht.content || '')
      .then(() => melde(t('nachricht.kopiert'), 'erfolg'))
  }

  function seedKopieren(seed) {
    navigator.clipboard
      .writeText(String(seed))
      .then(() => melde(t('nachricht.seed_kopiert'), 'erfolg'))
  }

  /* The generated picture's "···" (PictureMenu.svelte): the options every
     finished picture carries, plus what only the chat has to say about it —
     save it, copy its seed. */
  const pictureMenuEntries = $derived(nachricht.bild ? [
    // A video is no picture to start one from.
    ...(isVideo(nachricht.bild)
      ? []
      : [{ text: t('bild.als_eingabe'), action: () => studioWithPicture(nachricht.bild) }]),
    { text: t('nachricht.bild_sichern'), href: api.bildAdresse(nachricht.bild), download: '' },
    ...(nachricht.stats?.seed != null
      ? [{ text: t('nachricht.seed_kopieren'), value: nachricht.stats.seed,
           action: () => seedKopieren(nachricht.stats.seed) }]
      : []),
  ] : [])

  /* The attachment's "···": save it, and while the message is still being
     written, take it back — the two marks that used to sit in the
     picture's corners, now in the one menu every picture carries. */
  function anhangMenue(bildname) {
    const eintraege = [
      { text: t('nachricht.bild_sichern'), href: api.bildAdresse(bildname), download: '' },
    ]
    if (echteZeile) {
      eintraege.push({ text: t('nachricht.anhang_entfernen'), action: () => bildAnhangWeg(bildname) })
    }
    return eintraege
  }

  /* Buttons inside a rendered answer only come into being at render time,
     hence one delegated listener instead of individual bindings. A file's
     own card is no longer among them — Dateikarte.svelte handles its own
     clicks — so this is only ever the code block's copy button now. */
  function antwortKlick(ereignis) {
    codeKopierKlick(ereignis, () => melde(t('nachricht.code_kopiert'), 'erfolg'))
  }
</script>

<!-- The own message as it was typed. An address with http:// or https:// in
     it is a link that opens like one in an answer (in the shell's window in
     the system's browser, in the browser in a new tab); everything else
     stays text, character for character. -->
{#snippet eigenerText(inhalt)}{#each adressTeile(inhalt) as teil}{#if teil.href}<a class="eigenlink" href={teil.href} target="_blank" rel="noopener noreferrer">{teil.text}</a>{:else}{teil.text}{/if}{/each}{/snippet}

{#snippet callRow(teil, i)}
  {@const werkzeug = teil.werkzeug}
  {@const stand = hintergrundStand(werkzeug)}
  {@const wzPunkt = werkzeugPunkt(werkzeug, stand)}
  <!-- A call is one row in the block's window: a small dot in a column of its
       own, the name, a background run's number and a foretaste of the
       arguments. Nothing stands at its end — no "running", no exit code, no
       "failed": the dot says it, and for somebody who does not see it the
       label says the word. A click opens the call in the terminal tool,
       where its arguments and its result stand. -->
  <button
    class="aufruf"
    disabled={werkzeug.unbegun}
    aria-label={callLabel(werkzeug, stand)}
    in:rowIn
    onclick={(event) => {
      /* Opening the call is reading it: the dot of a finished background
         run stops moving here as well as when the next answer has read the
         report. Only a FINISHED run's — opened while the run still goes,
         the row would count the ending as read before it had happened. */
      if (stand && !stand.laeuft) werkzeug.gesehen = true
      openCall(callKey(werkzeug), event.currentTarget)
    }}
  >
    <span class="call-column" aria-hidden="true">
      <Leuchtpunkt farbe={wzPunkt.farbe} groesse={6} atmet={wzPunkt.atmet} quiet />
    </span>
    {#if werkzeug.written != null}
      {@render beingWritten(werkzeug)}
    {:else}
      <span class="wz-name">{werkzeug.name}</span>
    {/if}
    <!-- WHICH run this was. Only a background run has a number; every
         other call is one of one and would be told nothing by a "#1". -->
    {#if werkzeug.lauf_nummer != null}
      <span class="wz-nummer">#{werkzeug.lauf_nummer}</span>
    {/if}
    {#if vorschau(werkzeug.argumente)}
      <span class="wz-vorschau">{vorschau(werkzeug.argumente)}</span>
    {/if}
  </button>
{/snippet}

<!-- A call the model is still writing: the sentence the notice over the
     input says, in the row. The name stands in the tool face, where a
     call's name always stands, so nothing moves when the call is complete
     and its arguments take the words' place. The number of characters runs
     along in the fixed face: its digits are all one width. -->
{#snippet beingWritten(werkzeug)}
  <span class="wz-writing">{#each textPieces('werkzeug.schreibt', { name: werkzeug.name, zeichen: werkzeug.written }) as piece}{#if piece.wert === werkzeug.name}<span class="wz-name">{piece.wert}</span>{:else if piece.wert}<span class="wz-count">{piece.wert}</span>{:else}{piece.fest}{/if}{/each}</span>
{/snippet}

<!-- The block: everything the answer thought and did between two pieces of
     text. A head with an arrow, the time it thought and the number of tools;
     one dot on the line, which follows the last call. Closed it is the head
     and nothing else, running or not: the thinking and the calls appear
     with the click. Opened, the thinking and the calls
     stand in their order in a window of ten lines at most; the rest scrolls
     inside without a bar and melts out at the edge, and while the block goes
     the window keeps to its end. -->
{#snippet block(eintrag)}
  {@const offen = offeneTeile.has(eintrag.schluessel)}
  {@const going = blockRuns(eintrag)}
  {@const stand = blockState(eintrag)}
  {@const hasThinking = eintrag.eintraege.some(({ teil }) => teil.art === 'reasoning')}
  {@const zeit = blockThinkTime(eintrag)}
  {@const zahl = aufrufZahl(eintrag.eintraege)}
  {@const single = zahl === 1 ? lastCall(eintrag.eintraege) : null}
  <div class="ereignis block">
    {@render punkt(stand.farbe, stand.atmet)}
    <button class="block-head" class:offen aria-expanded={offen}
            onclick={() => teilKlappen(eintrag.schluessel)}>
      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true">
        <path d="M9 6l6 6-6 6" />
      </svg>
      <span class="head-text" class:leucht={going}>
        {#if hasThinking}
          {zeit ? t('nachricht.gedankengang_laeuft', { zeit }) : t('nachricht.gedankengang')}
        {:else if zahl > 1}
          {t('werkzeug.buendel', { zahl })}
        {:else if single}
          <span class="head-name">{single.name}</span>
        {/if}
      </span>
      {#if hasThinking && zahl > 1}
        <span class="head-count">· {t('werkzeug.buendel', { zahl })}</span>
      {:else if hasThinking && single}
        <span class="head-count">· <span class="head-name">{single.name}</span></span>
      {/if}
    </button>
    {#if offen}
      <div class="block-window" use:rollfade use:followAlong={going}
           transition:slide={{ duration: switchMs() }}>
        {#each eintrag.eintraege as step (step.i)}
          {#if step.teil.art === 'reasoning'}
            {#if step.i === thinkIndex && step.teil.text}
              <p class="step-thought"
                 use:lebendHtml={{ html: maskieren(thinkShown(step.teil, step.i)), fadeIn: thinkFlowing }}></p>
            {:else if step.teil.text}
              <p class="step-thought">{step.teil.text}</p>
            {/if}
          {:else}
            {@render callRow(step.teil, step.i)}
          {/if}
        {/each}
      </div>
    {/if}
  </div>
{/snippet}

<!-- The readings of an answer. One row of its own: the dot between two
     readings belongs to them (8 px apart), and the 14 px the footer keeps
     between its children would otherwise sit around the dot too. The dot
     wears the footer's ink as it is: dimmed, it fell under the contrast text
     needs. While the answer runs they stand in the footer, kept invisible
     between two rounds (see `haelt`); once it is over they stand in the last
     row of the line, where the waiting mark stood. -->
{#snippet readings()}
  {#if fussMessungen.length}
    <span class="messungen" class:haelt={messungenHaelt}
          aria-hidden={messungenHaelt ? 'true' : undefined}>
      {#each fussMessungen as messung, nummer}
        {#if nummer > 0}<span class="trenner" aria-hidden="true">·</span>{/if}
        <span class="messung" title={messung.titel}>
          <span class="zahl">{messung.zahl}</span> {messung.wort}
        </span>
      {/each}
    </span>
  {/if}
{/snippet}

<!-- One entry's dot on the answer's line. The house's own state dot
     (Leuchtpunkt.svelte), small and quiet — six pixels, no standing glow —
     breathing while its entry is still going: the caller says so, as far as
     the pulse settings allow. The answer's own text wears an empty ring
     instead: it is no state, it is what everything else led to. -->
{#snippet punkt(farbe, atmet = false)}
  <span class="punkt" aria-hidden="true">
    {#if farbe === 'antwort'}
      <span class="ring"></span>
    {:else}
      <Leuchtpunkt {farbe} groesse={6} {atmet} quiet />
    {/if}
  </span>
{/snippet}

<!-- A compaction is not a message and must not be drawn as one. It is a
     SEAM in the history: above it the conversation was folded together,
     below it goes on. A bubble in the message column says "somebody said
     this"; a line across says "here something was taken out", which is what
     happened. Nothing was deleted — every folded row still stands above,
     readable; they are only no longer sent.

     The summary itself is one click away rather than gone: it is what the
     model now reads in their place, and being able to check that is the
     whole reason the fold is visible at all. -->
{#if istVerdichtung}
  <div class="naht">
    <button
      class="naht-knopf"
      aria-expanded={verdichtungOffen}
      onclick={() => (verdichtungOffen = !verdichtungOffen)}
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M4 7 H20 M7 12 H17 M10 17 H14" />
      </svg>
      <span>
        {#if istNotfall}
          {nachricht.verdichtete_anzahl
            ? t('nachricht.verdichtet_notfall', { anzahl: nachricht.verdichtete_anzahl })
            : t('nachricht.verdichtet_notfall_ohne_zahl')}
        {:else}
          {nachricht.verdichtete_anzahl
            ? t('nachricht.verdichtet', { anzahl: nachricht.verdichtete_anzahl })
            : t('nachricht.verdichtet_ohne_zahl')}
        {/if}
      </span>
    </button>
  </div>
  {#if verdichtungOffen}
    <div class="naht-text" transition:slide={{ duration: 200 }}>{nachricht.content}</div>
  {/if}
{:else if istVonMir}
  <div class="von-mir" class:mit-bild={anhangBilder.length} class:mit-dokument={dokumentKarten.length}>
    {#if dokumentKarten.length}<div class="dok-reihe">{#each dokumentKarten as karte (karte.id || karte.name)}
      <!-- Document (4.1): one card, the same one a written file uses
           (Dateikarte.svelte) — the dog-ear is familiar from the Notion
           tools. The ✕ removes this one attachment from the message and
           stays outside the shared card, since it does not apply to a file
           the model wrote itself. The text is fetched on the click that
           opens the card rather than at mount (memoised above, so only the
           first visit pays).

           No `chatId` for a document that is text, deliberately: an
           attachment is the USER'S document, not something the answer
           produced — it has no business filing itself into the preview
           rail. Without the prop the card files nothing (md used to slip
           through as the one type with a recognised sprache). A PDF is the
           exception: its pages can only be seen in a frame, so its card
           carries the file's address and may stand in the rail. -->
      <div class="dok-zeile">
        <Dateikarte
          zeichenHtml={DOK_ZEICHEN}
          name={karte.name}
          fakten={faktenZeile(karte)}
          hinweis={getragen(karte)?.hinweis ?? null}
          sprache={['md', 'markdown'].includes(karte.typ) ? 'md' : ''}
          ladeInhalt={karte.id ? () => dokumentLesen(karte) : null}
          fileAddress={isPdf(karte) ? fileAddressOf(karte) : null}
          framed={isPdf(karte)}
          fileFacts={fileFacts(karte)}
          filePath={karte.pfad || ''}
          chatId={isPdf(karte) ? chatId : null}
        />
        {#if echteZeile && karte.id}
          <button class="anhang-weg" onclick={() => dokumentAnhangWeg(karte)}
                  title={t('nachricht.anhang_entfernen')} aria-label={t('nachricht.anhang_entfernen')}>✕</button>
        {/if}
      </div>
    {/each}</div>{/if}{#each anhangBilder as bildname (bildname)}
      <!-- The attachment travels into the speech bubble (vision): the
           picture alone, no frame and no edge — one click enlarges it,
           and "···" in the corner offers to save it and, while the
           message is still being written, to take it back. -->
      <div class="bildrahmen">
        <button class="bildknopf" onclick={() => bildZeigen(api.bildAdresse(bildname))}
                aria-label={t('nachricht.bild_vergroessern')}>
          <img class="bildanhang" src={api.bildAdresse(bildname)} alt="" loading="lazy" />
        </button>
        <PictureMenu entries={anhangMenue(bildname)} />
      </div>
    {/each}{#if anhangBilder.length || dokumentKarten.length}
      {#if nachricht.content}<div class="bildtext">{@render eigenerText(nachricht.content)}</div>{/if}
    {:else if skillTeil}
      <!-- Brightness only, no colour: which instruction was used is a fact
           about the message, not a state it is in. -->
      <span class="skillpille">/{skillTeil.name}</span>{#if ohneSkill}{' '}{@render eigenerText(ohneSkill)}{/if}
    {:else}{@render eigenerText(nachricht.content)}{/if}
  </div>
  <!-- The same actions as under the answers, just under one's own
       bubble: copy, and send-again only on the last question — in the
       middle it would devalue the history after it. They show only while
       the pointer is on the bubble (or on them, or a key has reached them);
       otherwise nothing stands there. -->
  <div class="fuss meine">
    <button class="tat" title={t('nachricht.kopieren')} aria-label={t('nachricht.kopieren')} onclick={kopieren}>
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V5a2 2 0 012-2h10" />
      </svg>
    </button>
    {#if istLetzteFrage}
      <button class="tat" title={t('nachricht.neu_senden')} aria-label={t('nachricht.neu_senden')}
              onclick={() => neuSenden?.()}>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8" />
          <path d="M21 3v5h-5" />
        </svg>
      </button>
    {/if}
  </div>
{:else}
  <div class="von-ki" style={`--bild-deckel:${bildDeckel}px`}>
    <!-- The line. Everything this answer did stands on it as an entry, in
         the order it happened, each with a dot in the colour of its state
         (house rule "colour means state"): blue thinking, green a tool that
         is done, red a failed tool, an abort or a limit, yellow waiting on
         the reader, grey the fold, an empty ring the answer's own text. The
         dot that is still going breathes. It is the only line in the chat —
         the entries themselves carry no rule or bar of their own. -->
    <div class="antwortlinie" bind:offsetHeight={lineHeight}
         style:min-height={floorHeight ? `${floorHeight}px` : null}>
      {#if nachricht.bild || nachricht.bildLaeuft}
        <div class="ereignis">
          {@render punkt('antwort')}
          <!-- A generated image: the light-edge frame and the picture rounded
               into it. A click on the picture enlarges it; "···" in its top
               right corner opens what else it offers — save, and copy the
               seed (from the message's own stats). Nothing stands under it.
               The SAME frame already stands while the painter works: the
               liquid fill inside at 75% size, growing to the full size with
               the picture the moment it is finished — one element, so the
               growth is smooth. What is happening is said inside that
               frame, not above it: a tile being drawn then starts level
               with a finished one beside it. -->
          <div class="erzeugt">
            {#if bildFlaeche}
              <div class="erzeugt-flaeche"
                   style={`width:${bildFlaeche.breite}px;aspect-ratio:${bildFlaeche.seite}`}>
                {#if nachricht.bild}
                  <button class="erzeugt-bild gefuellt" onclick={() => bildZeigen(api.bildAdresse(nachricht.bild))}
                          aria-label={t('nachricht.bild_vergroessern')}>
                    {#if isVideo(nachricht.bild)}
                      <!-- A video stands as its first frame with its length;
                           a click plays it at full size. -->
                      <Videokachel src={api.bildAdresse(nachricht.bild)} />
                    {:else}
                    <!-- The painter may snap ordered dimensions to its grid; the
                         stage follows the REAL picture once it is here, so cover
                         never crops a sliver off a rounded edge. -->
                    <img class="gemalt" src={api.bildAdresse(nachricht.bild)} alt="" loading="lazy"
                         onload={(e) => {
                           const b = e.currentTarget.naturalWidth, h = e.currentTarget.naturalHeight
                           if (b && h && nachricht.bildMasse
                               && (nachricht.bildMasse.breite !== b || nachricht.bildMasse.hoehe !== h)) {
                             nachricht.bildMasse = { breite: b, hoehe: h }
                           }
                         }} />
                    {/if}
                  </button>
                {:else}
                  <Bildfuellung fuellen />
                {/if}
                {#if nachricht.bildLaeuft}
                  <span class="bild-kopf">{drawingWord}</span>
                {/if}
              </div>
            {:else}
              <button class="erzeugt-bild" onclick={() => bildZeigen(api.bildAdresse(nachricht.bild))}
                      aria-label={t('nachricht.bild_vergroessern')}>
                {#if isVideo(nachricht.bild)}
                  <span class="videoanhang"><Videokachel src={api.bildAdresse(nachricht.bild)} ownShape /></span>
                {:else}
                  <img class="bildanhang" src={api.bildAdresse(nachricht.bild)} alt="" loading="lazy" />
                {/if}
              </button>
            {/if}
            {#if nachricht.bild}
              <PictureMenu entries={pictureMenuEntries} />
            {/if}
          </div>
        </div>
      {/if}
      <!-- Thinking, tools and text in the order they actually happened.
           One loop, not three fixed blocks: a second thinking pass after a
           first paragraph therefore stands under that paragraph instead of
           being drawn back up at the top. A message loaded from the server
           rebuilds the same list from its stored sections; one without them
           (written before they were stored) gets the old fixed order from
           `teile`. -->
      {#each anzeige as eintrag (eintrag.art === 'buendel' ? eintrag.schluessel : eintrag.i)}
        {#if eintrag.art === 'buendel'}
          {@render block(eintrag)}
        {:else}
        {@const teil = eintrag.teil}
        {@const i = eintrag.i}
        {#if startsAgent(teil)}
          {@const job = chatJob(teil.werkzeug.auftrag_id)}
          {@const helper = job?.agent ?? teil.werkzeug.argumente?.agent}
          {@const word = job && job.state !== 'laeuft' ? t('jobs.zustand.' + job.state) : ''}
          <!-- An agent this answer started: a quiet row at the line, the
               agent's sign where a call has its dot — so it reads at once
               as the agent's — then its name, how long it has been at work
               and the tool it called last; no card. Once it has stopped,
               the row keeps its name, the time it took and how it ended.
               The whole row is the way to its card in the agents view.

               The pieces stand in columns: the name's is as wide as the
               longest name among this answer's agents — the other names
               lie under it unseen and only lend their width — and the
               clock's and the state's are there in every row, also while
               they are empty. -->
          <div class="ereignis helper">
            <span class="punkt agent-mark" aria-hidden="true"><Agentenmarke groesse={13} /></span>
            <button
              class="agent-row"
              title={t('agent_row.transcript')}
              aria-label={[helper, word || t('jobs.zustand.laeuft'), job ? agentRuntime(job) : '', t('agent_row.transcript')].filter(Boolean).join(', ')}
              onclick={(event) => openHelper(job?.id ?? teil.werkzeug.auftrag_id, event.currentTarget)}
            >
              <span class="agent-name">
                <span>{helper}</span>
                {#each agentNames as other (other)}
                  <span class="agent-name-room" aria-hidden="true">{other}</span>
                {/each}
              </span>
              <span class="agent-time">{job ? agentRuntime(job) : ''}</span>
              <span class="agent-status">
                {#if job?.state === 'laeuft'}
                  {#if job.last_tool}<span class="agent-step werkzeugname">{job.last_tool}</span>{/if}
                {:else if job}
                  <span class="agent-state" class:wartet={job.state === 'wartet'}>{word}</span>
                {/if}
              </span>
            </button>
          </div>

        {:else if teil.art === 'content' && teil.text.trim()}
          {@const quelle = textShown(teil, i)}
          <div class="ereignis textzeile">
            {@render punkt('antwort')}
            <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
            <div class="antwort" onclick={antwortKlick}>
              {#each cardRows(dateiTeile(quelle, versaetze[i])) as stueck, j (j)}
                {#if stueck.art === 'html'}
                  <!-- Drawn in place, not through {@html}: that one tears the
                       whole answer out on every chunk, and the scroll area's
                       dip threw the reader back (lib/lebendhtml.js). While
                       the text flows, its new characters fade in. -->
                  <div class="fliesstext"
                       use:lebendHtml={{ html: stueck.wert, fadeIn: flowOn && i === flowIndex }}></div>
                {:else}
                  <!-- A file stands as its card from the first line of its
                       fence: blue while it is written, green once it is
                       there. Its source never shows in the answer. -->
                  <div class="file-row">
                    {#each stueck.files as file (file.name)}
                      <Dateikarte
                        zeichenHtml={dateizeichen(file.art)}
                        name={file.name}
                        fakten={isWriting(file)
                          ? writingFacts(file, t('datei.wird_geschrieben'), texte.sprache)
                          : dateiFakten(file)}
                        sprache={file.art}
                        inhalt={file.inhalt}
                        writing={isWriting(file)}
                        {chatId}
                      />
                    {/each}
                  </div>
                {/if}
              {/each}
            </div>
          </div>
        {/if}
        {/if}
      {/each}

      <!-- The pictures a tool handed into the chat with this answer: each
           in the frame of a generated picture, side by side in a row that
           wraps. A click enlarges the picture under its own name; "···"
           saves the file. The name is what a screen reader hears at the
           picture and at its click face — nothing of it is seen. A picture
           that will not load goes back to the file card. -->
      {#if deliveredPictures.length}
        <div class="ereignis">
          {@render punkt('antwort')}
          <div class="picture-row">
            {#each deliveredPictures as karte (karte.id)}
              {@const address = fileAddressOf(karte)}
              <div class="erzeugt">
                <button class="erzeugt-bild" onclick={() => bildZeigen(address, { name: karte.name })}
                        aria-label={karte.name}>
                  <img class="bildanhang" src={address} alt={karte.name} loading="lazy"
                       onerror={() => (pictureFailed[karte.id] = true)} />
                </button>
                <PictureMenu entries={[{ text: t('nachricht.bild_sichern'), href: address, download: karte.name }]} />
              </div>
            {/each}
          </div>
        </div>
      {/if}

      <!-- The other files a tool handed into the chat with this answer: the
           same card a written file and an attachment wear, in a row that
           wraps. They belong to the answer, so each files its tab under
           this chat. Their text is the file itself, and saving one saves
           that file. Nothing of its own for this branch. -->
      {#if deliveredFiles.length}
        <div class="ereignis textzeile">
          {@render punkt('antwort')}
          <div class="antwort">
            <div class="file-row">
              {#each deliveredFiles as karte (karte.id || karte.name)}
                <Dateikarte
                  zeichenHtml={DOK_ZEICHEN}
                  name={karte.name}
                  fakten={faktenZeile(karte)}
                  sprache={['md', 'markdown'].includes(karte.typ) ? 'md' : ''}
                  ladeInhalt={karte.id ? () => dokumentLesen(karte, true) : null}
                  fileAddress={fileAddressOf(karte)}
                  framed={isPdf(karte)}
                  fileFacts={fileFacts(karte)}
                  filePath={karte.pfad || ''}
                  {chatId}
                />
              {/each}
            </div>
          </div>
        </div>
      {/if}

      <!-- A tool call standing at the permission gate. The call has no entry
           of its own yet — the service reports the call only once it may
           run — so the wait is an entry here: yellow, breathing, named the
           way the box over the input field names it. Gone the moment the
           call's own entry exists, which then carries the yellow itself. -->
      {#if laeuft && freigabe && !teile.some((teil) => teil.aufruf_id === freigabe.aufrufId)}
        <div class="ereignis">
          {@render punkt('gelb', punktPulsiert('chat'))}
          <div class="hinweis">
            {t('werkzeug.frage_vor')}<span class="werkzeugname">{freigabe.name}</span>{t('werkzeug.frage_nach')}
          </div>
        </div>
      {/if}

      <!-- The waiting mark, while this answer is being waited for: the last
           entry on the line, the mark itself sitting where the next dot will
           (Wartezeile.svelte), the word and the clock beside it. Its row has
           one fixed height, so a mark changing its face never moves the chat.
           When the answer is over the readings stand in the same row, at the
           place the mark had: the answer keeps its height and nothing below
           it jumps. -->
      {#if marke || placeHeld}
        <div class="ereignis place" class:done={!marke}>
          {#if marke}
            {@render marke(markeRuhig)}
          {:else if nachricht.bild}
            {@render readings()}
          {:else}
            <!-- Over: the mark stands completely drawn and still at the end
                 of the line, the readings beside it. -->
            <Wartezeile art="antwort" finished>{@render readings()}</Wartezeile>
          {/if}
        </div>
      {/if}

      <!-- The notes below are entries on the line like everything else,
           standing where the thing happened — at the end, because that is
           where a run stops. Their dot says the state, so the row itself is
           only quiet text. -->
      {#if leereAntwort}
        <!-- An image answer has empty text — that is its normal state, not
             a "wrote nothing". The frame of a running picture stands above
             already; it needs no second word down here.

             An answer cut off at the ceiling has empty text too, and the
             line right below says exactly that. Both at once read as two
             problems instead of one, and this one reads as a fault while the
             other already explains the case — so where the answer was cut
             off, this line stays away and the one below speaks. -->
        <div class="ereignis">
          {@render punkt('rot')}
          <div class="hinweis">{grund}</div>
        </div>
      {/if}

      <!-- The answer ran into a limit. Said out loud, because the silence
           was the whole problem: a thinking model cut off mid-thought never
           closes its reasoning block, so the entire unfinished trace lands
           in the visible text and reads as a broken model. Only on a
           finished answer: while one is still running, nothing has been cut
           off yet. A provider refusing the request as too long for the
           context carries the same flag on a failed answer, and gets the
           same line over its error. -->
      {#if abgeschnitten || kontextfensterVoll || anbietergrenze || denkenAufgebraucht || antwortlaengeZuGross}
        <div class="ereignis">
          {@render punkt('rot')}
          <div class="hinweis">
            {antwortlaengeZuGross
              ? t('nachricht.antwortlaenge_zu_gross')
              : kontextfensterVoll
              ? t('nachricht.kontextfenster_voll')
              : denkenAufgebraucht
                ? t(`nachricht.${denkenAufgebraucht}`)
                : anbietergrenze
                  ? t('nachricht.anbietergrenze')
                  : t('nachricht.abgeschnitten')}
          </div>
        </div>
      {/if}

      <!-- Compaction failed twice in a row, so it is off for this chat until
           it earns one attempt back. Its own entry, under the one above
           rather than in place of it: the two above are alternatives, this
           one is not, and an answer can carry both. It wears the house's
           compaction sign on the line instead of a dot — the same narrowing
           stack as the seam above — in red. -->
      {#if komprimierenFehlgeschlagen}
        <div class="ereignis">
          <span class="zeichen rot" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M4 7 H20 M7 12 H17 M10 17 H14" />
            </svg>
          </span>
          <div class="hinweis">{t('nachricht.komprimieren_fehlgeschlagen')}</div>
        </div>
      {/if}

      <!-- Reached, and this is what was reached. An entry of its own rather
           than a sentence inside the text: the model said it with a tool
           call, not with a sentence, and the mark should read as the
           program speaking, not as more prose. Its circle with the tick
           stands on the line in green, in place of a dot. -->
      {#if ziel}
        <div class="ereignis">
          <span class="zeichen gruen" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="9" /><path d="M8 12.5 L11 15.5 L16.5 9" />
            </svg>
          </span>
          <div class="zielmarke"><b>{t('nachricht.ziel_erreicht')}</b> {ziel}</div>
        </div>
      {/if}
    </div>

    <div class="fuss" class:ruhig={markeRuhig}>
      {#if laeuft && fussMessungen.length}
        {@render readings()}
      {/if}
      {#each hinweise as wert}<span>{wert}</span>{/each}
      {#if laeuft}<span class="platzhalter"></span>{/if}
      <button class="tat" title={t('nachricht.kopieren')} aria-label={t('nachricht.kopieren')} onclick={kopieren}>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V5a2 2 0 012-2h10" />
        </svg>
      </button>
      <!-- Regenerate exists only on the last answer: recomputing one in
           the middle would invalidate everything after it (3.4). Under a
           failed answer the same arrow asks the failed call again and says
           so; what a press does is decided where it lands (App.svelte,
           `neuErzeugen`), by the same reading of how the run ended. -->
      {#if istLetzte && nachricht.id}
        {@const arrowLabel = laufzustand === 'fehler'
          ? t('nachricht.erneut_versuchen')
          : t('nachricht.neu_erzeugen')}
        <button class="tat" title={arrowLabel} aria-label={arrowLabel}
                onclick={() => neuErzeugen(nachricht.id)}>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8" />
            <path d="M21 3v5h-5" />
          </svg>
        </button>
      {/if}
    </div>
  </div>
{/if}


<style>
  .von-mir {
    /* Width and side ride on variables the layout mode sets
       (lib/chatlayout.js). The fallbacks are its factory values.

       Continuous rather than three notches: `--blase-eigen-stelle` runs from
       0 (hard left) to 1 (hard right), measured against the room left over
       beside the bubble. 1 is where it stood before. */
    /* The place is measured against the TRACK, and the bubble is then
       pulled back by its OWN width — the two percentages deliberately
       refer to two different boxes (100% in the margin is the track,
       100% in the translate is the bubble). Anything that took the
       place out of the max-width instead measured a box that a short
       message never fills: `jojo` began where a LONG message would
       begin and stopped right there, i.e. in the middle of the chat
       instead of at the right edge. This way place 0 is flush left,
       0.5 is centred and 1 is flush right, whatever the bubble is
       actually as wide as. `max-width` keeps capping next to it.

       The shift is `left`, NOT `margin-left`: a margin takes part in
       the layout, so `margin-left: 100%` leaves the bubble zero width
       to live in and it collapses to one character per line (measured:
       `jojo` rendered as a 40px column of single letters). `left` on a
       relatively positioned box moves it without touching its size. */
    align-self: flex-start;
    max-width: var(--blase-eigen-breite, 80%);
    position: relative;
    left: calc(var(--blase-eigen-stelle, 1) * 100%);
    transform: translateX(calc(var(--blase-eigen-stelle, 1) * -100%));
    /* The one surface the user may recolour; the ink flips with the
       ground's luminance so no choice can make it unreadable. The chain:
       the user's own pick wins, else a theme's own default (Dark Matter ships
       a lavender here), else the plain house bubble. */
    background: var(--blase-eigen, var(--blase-eigen-standard, var(--blase)));
    color: var(--blase-eigen-text, var(--blase-eigen-text-standard, inherit));
    border-radius: 9px;
    padding: 10px 15px;
    line-height: 1.55;
    /* The bubble keeps the whitespace of what was typed. That is why its
       blocks in the markup touch ({/each}{#each …}): the one space Svelte
       leaves between two blocks would stand in front of the text. */
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    min-width: 0;
  }
  /* The picked instruction, marked off from the request. Its own background
     rather than a colour: colour means state, and this is a fact. */
  .skillpille {
    display: inline-block;
    background: color-mix(in srgb, var(--text) 10%, transparent);
    border-radius: 9px;
    padding: 1px 8px 2px;
    font-size: 0.88em;
    line-height: 1.35;
    white-space: nowrap;
  }
  /* With a picture, the bubble drops its padding and ground: the picture
     stands flush in it, and there is no second edge around the one the
     picture brings itself. */
  .von-mir.mit-bild {
    padding: 0;
    background: none;
  }
  /* Document bubble (4.1): the card carries the border, the bubble only
     gives a narrow frame — same logic as with the image. */
  .von-mir.mit-dokument {
    padding: 6px;
  }
  /* The card itself is Dateikarte.svelte now (shared with a file the model
     writes) — this row only places the ✕ beside it, and undoes the card's
     own answer-text spacing (0.95em) back to the tighter gap attachments
     always had, kept alive on the row itself for several in a row. */
  .dok-zeile {
    display: flex;
    align-items: flex-start;
    gap: 4px;
    min-width: 0;
    /* Without this the row is as wide as its content, and the card's own
       `max-width: 100%` then refers to itself: in a narrow bubble the card
       stayed 300 wide and ran out on the right. */
    max-width: 100%;
  }
  .dok-zeile :global(.dateikarte) {
    margin: 0;
  }
  /* Several documents stand side by side and wrap, each at the card's own
     fixed size. `white-space: normal`: the bubble keeps its line breaks for
     the user's text, and they are not this row's to draw. */
  .dok-reihe {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    white-space: normal;
  }
  .anhang-weg {
    border: none;
    background: none;
    color: var(--text-still);
    font: inherit;
    font-size: 12px;
    padding: 2px 5px;
    border-radius: 9px;
    cursor: pointer;
    flex: none;
  }
  .anhang-weg:hover {
    background: var(--linie);
    color: var(--text);
  }
  /* The picture alone: no frame and no edge, the box hugs the picture, and
     the corner rides on the picture's own click face — not on the box, so
     the "···" menu can hang out of the box (PictureMenu). A picture is
     inline by default and then sits on a text baseline, which leaves a gap
     of a few pixels under it; a picture set to `block` starts at the first
     pixel instead. */
  .bildrahmen + .bildrahmen { margin-top: 6px; }
  .bildrahmen {
    position: relative;
    /* Flex, so the whitespace between the picture and the dots generates
       no line box of its own (a block box would grow by one line). */
    display: flex;
    width: fit-content;
    /* The size cap sits here as well as on the picture: a picture wider
       than the cap must not stretch the box to the bubble's whole width. */
    max-width: min(100%, var(--bild-deckel, 540px));
  }
  /* While a menu hangs out of the picture it must stay above the bubble
     next door — the same lift the picture window gives its tiles. Global
     on purpose: the dots live in PictureMenu, so a local selector would
     read as unused and be dropped. */
  :global(.von-mir:has(.more[aria-expanded='true'])) {
    z-index: 3;
  }
  .bildknopf {
    display: block;
    border: none;
    background: none;
    padding: 0;
    line-height: 0;
    cursor: zoom-in;
    /* The picture's corner and its clipping live on the click face. */
    border-radius: 9px;
    overflow: hidden;
  }
  /* A video loaded fresh, its size not known yet: as wide as a picture of
     this chat, in the video's own proportions. */
  .videoanhang {
    display: block;
    width: min(var(--bild-deckel, 540px), 100%);
  }
  .bildanhang {
    display: block;
    /* Larger preview (L): min() keeps it within the bubble on a narrow
       window, so it grows on a wide screen but never overflows. The cap
       itself comes from --bild-deckel (set on .von-ki, see bildDeckel) so
       a generated picture without a known bildMasse yet — every one
       loaded fresh from the server rather than just drawn — still lands
       at the SAME size as a sibling still carrying its live-drawn one;
       .von-mir never sets the variable, so an uploaded picture in a
       user bubble keeps the plain 540px default regardless. */
    max-width: min(var(--bild-deckel, 540px), 100%);
    max-height: var(--bild-deckel, 540px);
    /* Square on purpose: the click face around it is what carries the
       corner and clips this to shape (.bildknopf above). */
    border-radius: 0;
  }

  /* Standing under a picture without the bubble around it, the caption
     needs its own quiet ground — otherwise it floats on the page. */
  .bildtext {
    margin-top: 6px;
    padding: 7px 12px;
    background: var(--blase);
    /* The box wears the house bubble, so it needs the house ink — the
       surrounding user bubble's ink follows the user's chosen ground and
       can be dark on a light bubble, which made this text vanish. */
    color: var(--text);
    border-radius: 9px;
  }
  /* The generated picture's frame: a one-pixel light edge (brighter at the
     top, as if lit from above) and the picture rounded into it.
     fit-content so the frame hugs the picture at whatever size it came
     out, up to the image's cap. It anchors the "···" and its menu.

     The cap stands here too, with the edge of one pixel on either side: a
     picture whose size is not known yet carries its cap as a percentage,
     and a percentage does not count while the frame's own width is worked
     out — the frame then took all the room there was and stood wider than
     a landscape picture, grey beside it. */
  .erzeugt {
    position: relative;
    width: fit-content;
    max-width: min(100%, calc(var(--bild-deckel, 540px) + 2px));
    margin-bottom: 6px;
    padding: 1px;
    border-radius: 9px;
    background: linear-gradient(180deg, rgba(255, 255, 255, 0.15), rgba(255, 255, 255, 0.02) 42%, rgba(0, 0, 0, 0.4));
    box-shadow: 0 14px 34px -16px rgba(0, 0, 0, 0.6);
  }
  /* Pictures handed into the chat: their frames side by side, the gap
     between two the one between two file cards. A frame keeps its own
     height, and the room it leaves under itself is the room between two
     lines of the row. */
  .picture-row {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-start;
    gap: 0 8px;
  }
  .erzeugt-bild {
    display: block;
    border: none;
    background: none;
    padding: 0;
    line-height: 0;
    cursor: zoom-in;
    /* The same cap an ATTACHED picture has carried all along
       (.bildanhang below) — a generated one had none, so the tile size
       set in the layout panel simply did not reach it and every drawn
       picture filled whatever the bubble allowed. The variable was
       being handed down correctly the whole time (--bild-deckel on
       .von-ki, from the bildDeckel prop); this rule just never read it. */
    max-width: min(var(--bild-deckel, 540px), 100%);
    /* overflow clips the picture into the radius, trimming just the
       corner. */
    border-radius: 9px;
    overflow: hidden;
  }
  /* The sized stage inside the frame, same element in both states: liquid
     fill while the painter works, the picture when it is done. Its width is
     set inline (75% growing to 100%), the height follows the ordered aspect
     ratio — so the one transition on width IS the whole growth. */
  .erzeugt-flaeche {
    position: relative;
    max-width: 100%;
    border-radius: 9px;
    overflow: hidden;
    background: var(--bg-erhoben);
    transition: width 0.55s ease, border-radius 0.3s ease;
  }
  .erzeugt-bild.gefuellt {
    width: 100%;
    height: 100%;
    border-radius: 0;
  }
  .gemalt {
    display: block;
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  @media (prefers-reduced-motion: reduce) {
    .erzeugt-flaeche { transition: none; }
  }
  .von-ki {
    /* Width and side on variables, same as above, set in the layout mode
       (lib/chatlayout.js).

       The variables live HERE and not in a rule of their own below: Svelte
       hangs its own class hash on a rule inside a component, and that beats
       any extra :global rule of the same name. A second rule never got a
       turn.

       The same continuous placement for the answer side. 0 is where it stood
       before. */
    /* Same arithmetic as `.von-mir` above, and for the same reason —
       see the comment there. The absolutely positioned things inside
       this bubble (the picture corners, the generated picture's foot
       strip) each sit in their own `position: relative` box already
       (`.bildrahmen`, `.erzeugt-flaeche`), so the containing block the
       transform introduces here does not reach them. */
    align-self: flex-start;
    max-width: var(--blase-ki-breite, 100%);
    position: relative;
    left: calc(var(--blase-ki-stelle, 0) * 100%);
    transform: translateX(calc(var(--blase-ki-stelle, 0) * -100%));
    overflow-wrap: anywhere;
    min-width: 0;
  }
  /* The line and its entries. One hairline down the left of the answer —
     the only line in the chat — and every entry's dot sitting on it, its
     centre on the line's own centre (the dot's box is 11px wide at the
     column's left edge, the line 1px at 5px). The entries stand 10px apart;
     the blocks inside carry no outer margin of their own any more. */
  .antwortlinie {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding-left: 22px;
  }
  .ereignis {
    position: relative;
    min-width: 0;
    --linie-oben: -5px;
    --linie-unten: -5px;
  }
  /* The line is drawn in pieces, one per entry, each reaching half the gap
     into its neighbours so the pieces meet. Nothing is painted over the line
     to hide it: an entry whose sign is hollow leaves a gap in its own piece
     where the sign stands, so the glass behind the chat shows through the
     sign and the gap alike. The first piece starts and the last one ends
     8px inside the column. */
  .ereignis:first-child { --linie-oben: 8px; }
  .ereignis:last-child { --linie-unten: 8px; }
  .ereignis::before {
    content: '';
    position: absolute;
    left: -17px;
    top: var(--linie-oben);
    bottom: var(--linie-unten);
    width: 1px;
    background: var(--linie-stark);
  }
  /* The answer's ring: the gap is the ring's own height, centred where the
     dot would sit (`.punkt`, one half line down). */
  .ereignis:has(> .punkt > .ring) {
    --luecke-von: calc(1lh / 2 - 3.5px);
    --luecke-bis: calc(1lh / 2 + 3.5px);
  }
  /* A sign standing on the line (`.zeichen`: 15px box, 2px from the entry's
     top): the gap is the whole box. */
  .ereignis:has(> .zeichen) {
    --luecke-von: 2px;
    --luecke-bis: 17px;
  }
  .ereignis:has(> .punkt > .ring)::before,
  .ereignis:has(> .zeichen)::before {
    background: linear-gradient(
      to bottom,
      var(--linie-stark) calc(var(--luecke-von) - var(--linie-oben)),
      transparent calc(var(--luecke-von) - var(--linie-oben)),
      transparent calc(var(--luecke-bis) - var(--linie-oben)),
      var(--linie-stark) calc(var(--luecke-bis) - var(--linie-oben))
    );
  }
  /* The mark stands on the line itself: the line comes down and ends INSIDE
     the stroke of the mark's outer form, never above it. The distance from
     the row's top edge to that stroke (the outer form's centre line at the
     line's x, in the mark's 24 × 20 box) is a little different for each
     face: the frame of an answer 1.6 px, a document's web 2.5 px, an image's
     eye 5.3 px, a compaction's upper line 5.8 px. A lone mark has no line at
     all. */
  .ereignis:has(> :global(.wartet))::before {
    bottom: auto;
    height: calc(1.6px - var(--linie-oben));
  }
  .ereignis:has(> :global(.wartet[data-art='einbettung']))::before {
    height: calc(2.5px - var(--linie-oben));
  }
  .ereignis:has(> :global(.wartet[data-art='vision']))::before {
    height: calc(5.3px - var(--linie-oben));
  }
  .ereignis:has(> :global(.wartet[data-art='verdichtung']))::before {
    height: calc(5.8px - var(--linie-oben));
  }
  .ereignis:has(> :global(.wartet)):first-child::before { display: none; }
  /* A finished mark with a note under it (cancelled, a limit): the line goes
     on below the mark, down to the note's own piece. */
  .ereignis:has(> :global(.wartet.fertig)):not(:last-child)::after {
    content: '';
    position: absolute;
    left: -17px;
    top: 100%;
    height: 5px;
    width: 1px;
    background: var(--linie-stark);
  }
  /* The same row once the answer is over: the finished mark stands where the
     running one stood, at the same height, the readings beside it, and the
     line ends on it. */
  .place {
    height: 20px;
    line-height: 20px;
  }
  .place.done:not(:has(> :global(.wartet)))::before { display: none; }
  .place.done {
    display: flex;
    align-items: center;
    font-size: 12px;
    color: var(--text-still);
  }
  /* A thinking row's head is `inline-flex` and would sink by half a
     leading inside a taller line box; giving the row exactly one head
     line keeps it — and the dot's line (below) — in place. The tool row
     gets the same line, so its dot reads the same 19px. */
  .ereignis.block {
    line-height: 19px;
  }
  /* The dot sits in the middle of its entry's first line. The height is
     no fixed number: the dot reads `lh`, the line height that reaches it
     from here — 19px for heads, the answer's own 1.65 for text. The
     `4px` before it is only what a browser without `lh` falls back to. */
  .punkt {
    position: absolute;
    left: -22px;
    top: 4px;
    top: calc(1lh / 2 - 5.5px);
    width: 11px;
    height: 11px;
    display: grid;
    place-items: center;
  }
  /* The disc covers the line where they meet; the ring of the answer is
     hollow and the line leaves a gap for it (`.ereignis::before`). */
  .ring {
    width: 7px;
    height: 7px;
    box-sizing: border-box;
    border-radius: 50%;
    border: 1.25px solid var(--text-still);
  }
  /* The answer's text sets a larger line: its dot follows it — the same
     1.65 the answer text stands in. */
  .ereignis.textzeile {
    line-height: 1.65;
  }
  .textzeile > .punkt { top: 8px; top: calc(1lh / 2 - 5.5px); }

  /* An agent's row: as quiet as a tool call's, its sign in the dot's place;
     the whole row is the button to its card. */
  .helper {
    line-height: 22px;
  }
  .agent-row {
    display: flex;
    align-items: center;
    gap: 8px;
    width: calc(100% + 4px);
    min-height: 22px;
    margin-left: -4px;
    padding: 0 6px 0 4px;
    border: none;
    border-radius: 9px;
    background: none;
    font: inherit;
    font-size: 12.5px;
    color: var(--text-leise);
    text-align: left;
    cursor: pointer;
  }
  .agent-row:hover { background: var(--bg-hoch); }
  .punkt.agent-mark {
    width: 15px;
    height: 15px;
    left: -24px;
    top: 3px;
    color: var(--text-leise);
  }
  /* The row's pieces keep their places: from row to row, while the clock
     runs and while the last tool changes. An answer is only as wide as its
     widest row, so a piece that grew moved everything at the far end of
     every row with it.

     The name: all the names of this answer's agents lie in one cell, only
     the row's own is seen — the cell is as wide as the longest. */
  .agent-name {
    display: inline-grid;
    grid-template-columns: minmax(0, max-content);
    min-width: 0;
    color: var(--text);
    font-weight: 500;
  }
  .agent-name > span {
    grid-area: 1 / 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .agent-name-room {
    height: 0;
    visibility: hidden;
    user-select: none;
  }
  /* The clock: room for five characters, minutes and seconds up to 99:59 —
     an agent's own time limit starts at twenty minutes. A longer clock
     widens it, it is never cut. */
  .agent-time {
    flex: none;
    min-width: 5ch;
    font-variant-numeric: tabular-nums;
    color: var(--text-still);
  }
  /* How it ended, or the tool it called last: sixteen characters of the
     fixed face, the longest name among the program's own tools. A longer
     name ends in an ellipsis; the transcript has it whole. Where the
     answer is narrower than the row, this cell and the name give way. */
  .agent-status {
    width: 16ch;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font: 12px var(--schrift-fest);
  }
  .agent-step { color: var(--werkzeug); }
  .agent-state { font: 12.5px var(--schrift); color: var(--text-still); }
  .agent-state.wartet { color: var(--gelb-text); }
  /* A picture in an image run's grid is a tile, not an answer — no line
     and no dot there. The grid is App.svelte's (`.bildlauf-platz`). */
  :global(.bildlauf-platz) .antwortlinie { padding-left: 0; }
  :global(.bildlauf-platz) .ereignis::before,
  :global(.bildlauf-platz) .punkt { display: none; }

  /* The block's head: an arrow, the time it thought and the number of tools,
     in the quietest step of the program's text (`--text-neben`) — the dot on
     the line carries the state, not the head. The block's thinking and its
     calls stand in the same step, so there is one brightness in the block and
     the answer is the only thing that stands bright. While the block goes, a
     lighter band of the same colour runs across the word. */
  .block-head {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    max-width: 100%;
    margin: 0;
    padding: 0 6px 0 0;
    font: inherit;
    font-size: 12.5px;
    line-height: 19px;
    color: var(--text-neben);
    background: none;
    border: none;
    border-radius: 9px;
    white-space: nowrap;
    cursor: pointer;
  }
  .block-head:hover { color: var(--text); }
  /* The name of a single call stands in the head as it stands in the row:
     the fixed face, in the block's colour, no weight of its own. */
  .head-name { font-family: var(--schrift-fest); }
  .block-head svg {
    flex: none;
    transition: transform 0.18s;
  }
  .block-head.offen svg {
    transform: rotate(90deg);
  }
  .head-text,
  .head-count {
    font-variant-numeric: tabular-nums;
  }
  .leucht {
    background: linear-gradient(90deg, var(--text-neben) 0%, var(--text-neben) 35%,
      color-mix(in srgb, var(--text-neben) 45%, white) 50%, var(--text-neben) 65%, var(--text-neben) 100%);
    background-size: 250% 100%;
    -webkit-background-clip: text;
    background-clip: text;
    color: transparent;
    animation: glanz 1.8s linear infinite;
  }
  @keyframes glanz {
    from { background-position: 100% 0; }
    to { background-position: -150% 0; }
  }
  @media (prefers-reduced-motion: reduce) {
    .leucht { animation: none; background: none; color: inherit; }
  }
  /* The open block's window: the thinking and the calls in their order, ten
     lines at most. The rest scrolls inside without a bar and melts out at
     the edge while more lies beyond it (`use:rollfade`). */
  .block-window {
    margin-top: 4px;
    max-height: calc(10 * 20px);
    overflow-y: auto;
    overscroll-behavior: contain;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .step-thought {
    margin: 0;
    flex: none;
    font-size: 12.5px;
    line-height: 1.6;
    color: var(--text-neben);
    white-space: pre-wrap;
  }
  /* A call is one row: a small dot in its own column, the name, a run's
     number, a foretaste of the arguments — and nothing at its end. What does
     not fit is cut with an ellipsis; the whole of it stands in the terminal
     tool, one click away. */
  .aufruf {
    display: flex;
    align-items: center;
    gap: 8px;
    flex: none;
    width: calc(100% + 4px);
    min-width: 0;
    margin-left: -4px;
    padding: 0 6px 0 4px;
    font-family: var(--schrift-fest);
    font-size: 12px;
    line-height: 19px;
    color: var(--text-neben);
    text-align: left;
    background: none;
    border: none;
    border-radius: 9px;
    cursor: pointer;
  }
  .aufruf:hover { background: var(--bg-hoch); }
  .aufruf:hover .wz-vorschau { color: var(--text-leise); }
  /* A call that has not begun has nothing to open. */
  .aufruf:disabled { cursor: default; }
  .aufruf:disabled:hover { background: none; }
  .call-column {
    flex: none;
    width: 10px;
    display: grid;
    place-items: center;
  }
  /* The name of a call in the block: the fixed face of the row, in the
     block's colour and weight — the sand and the bold of `.werkzeugname`
     (stil/global.css) stay where the terminal tab shows names. `flex: none`
     keeps it whole — the preview beside it is the one built to give way. */
  .aufruf .wz-name { flex: none; }
  .wz-writing .wz-name { font-family: var(--schrift-fest); }
  .aufruf .wz-vorschau {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  /* "… is being written — n characters": words, so they leave the fixed
     face; the name in them and the running number keep it. It gives way
     like the preview it stands for. */
  .aufruf .wz-writing {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-family: var(--schrift);
  }
  .wz-count {
    font-family: var(--schrift-fest);
    font-variant-numeric: tabular-nums;
  }
  /* The run number identifies, it does not report. `flex: none` for the
     same reason the name has it: a number that gives up a digit is a
     different number. */
  .aufruf .wz-nummer {
    flex: none;
  }

  .antwort {
    line-height: 1.65;
  }
  /* A new character of the flowing text comes up in 280 ms; the span carries
     a negative delay of its age, so a span made afresh goes on from where
     the last one was (lib/lebendhtml.js). */
  .antwort :global(.flow-char),
  .step-thought :global(.flow-char) {
    animation: fade-in 280ms cubic-bezier(0.33, 0, 0.67, 1) both;
  }
  @keyframes fade-in {
    from { opacity: 0; }
    to { opacity: 1; }
  }
  @media (prefers-reduced-motion: reduce) {
    .antwort :global(.flow-char),
    .step-thought :global(.flow-char) { animation: none; }
  }
  /* The waiting indicators (logo and image sign alike) live in the
     Wartezeile — row, size, timing and spot are set only there. */

  /* The image-generation status, in the type of the reasoning text. It
     stands inside the frame of the picture being drawn, centred in the
     band under the sketch's horizon, clear of the lines the grains settle
     into. Laid over the stage, so it takes no room from the fill. */
  .bild-kopf {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 7%;
    font-size: 12.5px;
    line-height: 1.3;
    color: var(--text-still);
    text-align: center;
    pointer-events: none;
  }

  /* Keeps the footer at height so the text doesn't jump when finishing. */
  .platzhalter {
    display: inline-block;
    height: 1em;
  }

  /* A note on the line — cancelled, cut off, a limit, the fold. Quiet text
     only: the dot in front of it already carries the state. */
  .hinweis {
    font-size: 12.5px;
    line-height: 19px;
    color: var(--text-still);
  }
  /* The seam. The two rules across are the whole drawing: a hairline in
     the same colour every other divider in the program uses, parted around
     what it says. It takes one row of height where the folded stretch took
     dozens — a compaction that costs a tile would be a strange thing. */
  .naht {
    display: flex;
    align-items: center;
    gap: 10px;
    margin: 16px 0;
    font-size: 12.5px;
    color: var(--text-still);
  }
  .naht::before,
  .naht::after {
    content: '';
    flex: 1 1 auto;
    height: 1px;
    background: var(--linie);
  }
  .naht-knopf {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    flex: none;
    font: inherit;
    color: inherit;
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
  }
  .naht-knopf:hover {
    color: var(--text-leise);
  }
  .naht-knopf svg {
    flex: none;
  }
  /* The summary itself, unfolded: the program's own text, not either
     party's — a quiet ground of its own and, like everything in the chat,
     no frame. */
  .naht-text {
    margin: -6px 0 16px;
    padding: 10px 12px;
    font-size: 13px;
    line-height: 1.5;
    white-space: pre-wrap;
    color: var(--text-leise);
    background: var(--bg-erhoben);
    border-radius: 9px;
  }
  /* A sign that stands on the line in place of a dot — the goal's circle
     with the tick in green, the failed compaction's stack in red. The line
     leaves a gap for its box (`.ereignis::before`). */
  .zeichen {
    position: absolute;
    left: -24px;
    top: 2px;
    width: 15px;
    height: 15px;
    display: grid;
    place-items: center;
  }
  .zeichen svg {
    width: 15px;
    height: 15px;
  }
  .zeichen.gruen { color: var(--gruen); }
  .zeichen.rot { color: var(--rot); }
  /* Reached, and this is what was reached: a quiet sentence like every note
     on the line, its first words set half-bold. It is a sentence and may
     wrap. */
  .zielmarke {
    font-size: 12.5px;
    line-height: 19px;
    color: var(--text-leise);
    overflow-wrap: anywhere;
  }
  .zielmarke b {
    font-weight: 600;
    color: var(--text);
  }
  .fuss {
    display: flex;
    align-items: center;
    gap: 14px;
    margin-top: 10px;
    font-size: 12px;
    color: var(--text-still);
  }
  /* The readings of an answer: number, word and dot in the one quietest
     text step, like the head, the text and the calls of the thinking block.
     The fixed font gives every digit the same width, so the line does not
     wobble while the figures change during a run. */
  .messungen {
    display: inline-flex;
    align-items: baseline;
    gap: 8px;
    color: var(--text-neben);
  }
  /* Between two rounds: the place of the last reading, none of its ink. */
  .messungen.haelt {
    visibility: hidden;
  }
  .messung {
    font-family: var(--schrift-fest);
  }
  /* Under the running text only the mark stands: the footer keeps its
     room and its place in the line, none of its ink and none of its
     reach, so the end of the run changes no height. */
  .fuss.ruhig {
    visibility: hidden;
  }
  /* The returning working mark needs air to the interim text. */
  .fuss .tat {
    border: none;
    background: none;
    color: var(--text-still);
    cursor: pointer;
    padding: 4px;
    border-radius: 9px;
    display: inline-flex;
  }
  /* Under one's own bubble: right-aligned like the bubble itself, a bit
     closer — there are no measurements here, only the actions. They keep
     their room and only turn visible, so nothing below moves when the
     pointer comes by. The gap to the bubble is padding, not margin: the
     pointer on its way down never leaves both and the row stays put. A
     screen without a pointer to hover shows them always. */
  .fuss.meine {
    align-self: flex-end;
    margin-top: 0;
    padding-top: 6px;
    gap: 6px;
    opacity: 0;
    transition: opacity 0.15s;
  }
  .von-mir:hover + .fuss.meine,
  .fuss.meine:hover,
  .fuss.meine:focus-within {
    opacity: 1;
  }
  @media (hover: none) {
    .fuss.meine { opacity: 1; }
  }
  .fuss .tat:hover {
    background: var(--linie);
    color: var(--text);
  }

  /* Markdown output. :global, because the HTML comes into being at
     runtime and Svelte only hands its classes to the markup it sees at
     build time. */
  .antwort :global(> *:first-child) { margin-top: 0; }
  .antwort :global(> *:last-child) { margin-bottom: 0; }
  /* The written text stands in its own box (`.fliesstext`, drawn in
     place); the two edge rules above reach through it to the first and
     last block inside, so an answer still starts flush and ends without
     dangling whitespace. */
  .antwort > .fliesstext:first-child > :global(:first-child) { margin-top: 0; }
  .antwort > .fliesstext:last-child > :global(:last-child) { margin-bottom: 0; }
  .antwort :global(p) { margin: 0 0 0.85em; }
  .antwort :global(h2) { font-size: 1.22em; font-weight: 600; margin: 1.4em 0 0.5em; letter-spacing: -0.01em; }
  .antwort :global(h3) { font-size: 1.08em; font-weight: 600; margin: 1.3em 0 0.45em; }
  .antwort :global(h4), .antwort :global(h5) { font-size: 1em; font-weight: 600; margin: 1.2em 0 0.4em; }
  .antwort :global(ul), .antwort :global(ol) { margin: 0 0 0.85em; padding-left: 1.35em; }
  .antwort :global(li) { margin: 0.22em 0; }
  .antwort :global(blockquote) {
    margin: 0 0 0.85em; padding: 0.1em 0 0.1em 0.9em;
    border-left: 2px solid var(--linie-stark); color: var(--text-leise);
  }
  .antwort :global(hr) { border: none; border-top: 1px solid var(--linie); margin: 1.4em 0; }
  /* A markdown image is at most as wide as the text it stands in. */
  .antwort :global(img.md-bild) { max-width: 100%; height: auto; }
  /* The files of an answer: cards side by side, wrapping, with the room
     below that a paragraph has. The card's own spacing is the row's. */
  .file-row {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin: 0 0 0.95em;
  }
  .file-row :global(.dateikarte) {
    margin: 0;
  }
  /* A link has to read as one: the blue of the look, and the line under it
     in the same blue (the colour the text itself wears). */
  .antwort :global(a) { color: var(--blau); text-underline-offset: 3px; }
  /* The same link in one's own bubble. */
  .eigenlink { color: var(--blau); text-underline-offset: 3px; }
  .antwort :global(table) {
    border-collapse: collapse; margin: 0 0 0.95em; font-size: 0.94em; display: block; overflow-x: auto;
  }
  /* No boxes: only a fine rule between the rows, and a half-bold head. */
  .antwort :global(th), .antwort :global(td) { border-bottom: 1px solid var(--linie); padding: 6px 11px; text-align: left; }
  /* A cell never breaks inside a word. The answer around it may
     (`overflow-wrap: anywhere`), and a cell that inherits that counts every
     letter as a place to wrap, so a narrow chat squeezes the columns until
     words fall apart. Here only a long word (ten letters and more, four
     on either side of the break) is hyphenated at a syllable — without that
     limit every short word counts its syllables as places to wrap and the
     squeeze returns with hyphens — and a table still wider than the answer
     scrolls on its own. */
  .antwort :global(th), .antwort :global(td) {
    overflow-wrap: normal; hyphens: auto; hyphenate-limit-chars: 10 4 4;
  }
  .antwort :global(tr:last-child > td) { border-bottom: none; }
  .antwort :global(th) { font-weight: 600; }
  /* Inline code only — a word in a sentence, which is what the pill is
     for. `<pre>` is excluded by the selector rather than by weight: the
     block's own rules live in stil/codeblock.css and are one class lighter
     than anything scoped here, so any overlap would silently hand a whole
     code block the inline pill. */
  .antwort :global(:not(pre) > code) {
    font-family: var(--schrift-fest); font-size: 0.9em;
    background: var(--blase); padding: 1.5px 5px; border-radius: 9px;
  }
  /* The frame itself (.codeblock, the copy mark, the numbered rows, the
     scrollbar) lives in stil/codeblock.css now, loaded globally — the file
     card (Dateikarte.svelte) wears the same frame around its own embedded
     source, not a second copy of it. */
  /* A block still being written: it stands there from its first line and
     grows, instead of appearing all at once when the closing fence arrives.
     The only difference to a finished one is the writing mark at the end —
     the frame, the numbers and the colours are already the final ones, so
     nothing jumps when the fence closes. */
  /* A numbered block ends in a row, so the mark goes at the end of the last
     row's text rather than below all of them. */
  .antwort :global(.codeblock.offen:not(.nummeriert) code::after),
  .antwort :global(.codeblock.offen .code-zeile:last-child > span::after) {
    content: ''; display: inline-block; width: 7px; height: 0.95em;
    margin-left: 2px; vertical-align: -2px;
    background: var(--gelb, var(--text-still));
    animation: schreibmarke 1s steps(2, start) infinite;
  }
  @keyframes schreibmarke { 0%, 100% { opacity: 0.15 } 50% { opacity: 1 } }

  /* The file card (a code block whose language is a recognised document
     type) is now Dateikarte.svelte, a component of its own used here and
     by the document-attachment card above — its styling lives there, not
     duplicated here. */

  /* The colours themselves live in stil/codefarben.css — one set of rules
     for every place that shows code, so the chat and the tool prompt can
     never drift apart. */
</style>
