<script>
  import { rollfade } from '../lib/rollfade.js'
  import { slide } from 'svelte/transition'
  import { codeKopierKlick, dateiTeile, dateienZahl } from '../lib/markdown.js'
  import { lebendHtml } from '../lib/lebendhtml.js'
  import { hervorheben, maskieren } from '../lib/einfaerben.js'
  import { dateiFakten, dateizeichen, writingFacts } from '../lib/dateiarten.js'
  import { api } from '../lib/api.js'
  import { melde, zustand } from '../lib/zustand.svelte.js'
  import { studioWithPicture } from '../lib/studio.svelte.js'
  import { t, texte } from '../lib/texte.svelte.js'
  import { stoppuhr } from '../lib/dauer.js'
  import { aufrufZahl, buendeln, laufenderAufruf, schlechtesterPunkt } from '../lib/werkzeugbuendel.js'
  import { tempoGemessen, tempoTitelSchluessel } from '../lib/tempoquelle.js'
  import { takt, taktHalten } from '../lib/sekundentakt.svelte.js'
  import { skillAmAnfang } from '../lib/skills.svelte.js'
  import { bildZeigen } from '../lib/bildschau.svelte.js'
  import Leuchtpunkt from './Leuchtpunkt.svelte'
  import { terminal } from '../lib/terminalfenster.svelte.js'
  import { laufampel } from '../lib/laufampel.js'
  import { punktAtmet, punktPulsiert } from '../lib/meldewesen.svelte.js'
  import Bildfuellung from './Bildfuellung.svelte'
  import PictureMenu from './PictureMenu.svelte'
  import Videokachel from './Videokachel.svelte'
  import { isVideo } from '../lib/media.js'
  import Dateikarte from './Dateikarte.svelte'
  import Agentenmarke from './Agentenmarke.svelte'
  import { chatJob, openTranscript } from '../lib/agentchat.svelte.js'

  /* `marke`: the chat's live waiting mark (App.svelte, `wartemarke`), handed
     only to the answer it waits for. It stands as that answer's last entry
     on the line, in the place the next entry's dot will take. */
  let {
    nachricht, istLetzte = false, laeuft = false, neuErzeugen,
    istLetzteFrage = false, neuSenden, bildDeckel = 540, marke = null,
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
      const rest = dokumentKarten.filter((k) => k.id !== karte.id)
      nachricht.dokument = rest.length === 1 ? rest[0] : null
      nachricht.dokumente = rest.length > 1 ? rest : null
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    }
  }
  const hatInhalt = $derived(Boolean((nachricht.content || '').trim()))
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
    let bisher = 0
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
     before the column existed keeps saying what it always said. */
  const laufzustand = $derived(
    nachricht.zustand
      ?? (stats.fehler ? 'fehler' : stats.abgebrochen ? 'abgebrochen' : null),
  )

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

  /* How long a finished thinking stretch took: from its own start to its
     own end — the first event after it that was not thinking (App.svelte,
     `endThinking`), so a wait on a tool confirmation after it is not
     counted. Thinking that goes on after such an event takes the end back
     (`textAnhaengen`). Without a recorded end, the start of whatever came
     next. A message loaded from the server has its stretches back from
     its stored sections, with the same ends; one written before those
     existed has none, and a stretch with neither has no end — both stay
     without a length rather than show an invented one. */
  function denkDauer(i) {
    const beginn = teile[i]?.seit
    const ende = teile[i]?.endedAt ?? teile[i + 1]?.seit
    return beginn != null && ende != null ? stoppuhr(ende - beginn) : null
  }

  /* The newest thought, for the one line under a running thinking head:
     the last sentence, or the one still being written. */
  function letzterGedanke(text) {
    const saetze = String(text || '').split(/(?<=[.!?])\s+|\n+/)
    for (let i = saetze.length - 1; i >= 0; i--) {
      if (saetze[i].trim()) return saetze[i].trim()
    }
    return ''
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
    if (wartetAufNutzer(werkzeug.aufruf_id)) return { farbe: 'gelb', atmet: punktPulsiert('chat') }
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
      /* A stored section takes the first entry with its call id that no
         section before it took: a server without ids numbers every round
         from zero, so the same id can stand for several calls. A stored
         entry keeps its call id as `kennung`. The live list keeps the
         first match by `aufruf_id`, the entry its results are written into
         (App.svelte, `tool_result`), exactly as before. */
      if (live) {
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
            a.art === 'werkzeug'
              ? { ...a, werkzeug: werkzeuge.find((w) => w?.aufruf_id === a.aufruf_id) }
              : a,
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


  /* The same parts, with runs of two or more tool calls bundled into one
     entry (lib/werkzeugbuendel.js). */
  const anzeige = $derived(buendeln(teile))

  /* The bundle's dot: the worst state among its calls. The thinking in it
     has no say — its blue would outrank every finished call. */
  function buendelPunkt(eintrag) {
    return schlechtesterPunkt(
      eintrag.eintraege
        .filter(({ teil }) => teil.art === 'werkzeug')
        .map(({ teil }) => werkzeugPunkt(teil.werkzeug, hintergrundStand(teil.werkzeug))),
    )
  }

  /* A foretaste in the header, so you don't have to unfold every row to
     see what was searched for. The first value suffices for that. */
  function vorschau(argumente) {
    const werte = Object.values(argumente ?? {})
    if (!werte.length) return ''
    const erster = typeof werte[0] === 'string' ? werte[0] : JSON.stringify(werte[0])
    return erster.length > 60 ? erster.slice(0, 60) + '…' : erster
  }

  /* An argument value in the same colours as a real code block — a string
     stays plain (no language is known, and guessing one has burned this
     house before), an object or number goes through as the JSON it
     actually is, since stringifying it here is what makes it one. */
  function wertHtml(wert) {
    return typeof wert === 'string'
      ? hervorheben(wert)
      : hervorheben(JSON.stringify(wert), 'json')
  }

  /* A tool's result carries its change block, if any, straight after the
     one-sentence summary — app/tools/aenderungsblock.py joins them with a
     blank line, then the first hunk. That blank line followed by a hunk
     header is the mark: ordinary tool output never happens to start a line
     with it. */
  function aenderungAufteilen(text) {
    const stelle = String(text || '').indexOf('\n\n@@ ')
    if (stelle === -1) return null
    return { kurz: text.slice(0, stelle), diff: text.slice(stelle + 2) }
  }

  /* Coloured line by line instead of through hervorheben(): a diff is not a
     programming language, it is `+`/`-`/context rows, and highlight.js has
     no grammar registered for it (einfaerben.js). Kept to what B4 already
     draws a tool's result with — no new colour file, no syntax palette on
     top of a line that is already carrying red or green. */
  function aenderungHtml(diff) {
    return diff
      .split('\n')
      .map((zeile) => {
        let art = 'kontext'
        if (zeile.startsWith('@@')) art = 'kopf'
        else if (zeile.startsWith('+')) art = 'hinzu'
        else if (zeile.startsWith('-')) art = 'entfernt'
        else if (zeile.startsWith('… ')) art = 'hinweis'
        return `<span class="diff-zeile diff-${art}">${maskieren(zeile)}</span>`
      })
      .join('\n')
  }

  /* One tool result, either as plain highlighted text or, when it carries a
     change block, as the short sentence plus the coloured diff below it —
     the same <pre> either way, so nothing about the surrounding block has
     to know which one it got. */
  function werkzeugErgebnisHtml(text) {
    const aenderung = aenderungAufteilen(text)
    if (!aenderung) return hervorheben(text)
    return maskieren(aenderung.kurz) + '\n\n' + aenderungHtml(aenderung.diff)
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
  const speedReading = $derived(
    laeuft && nachricht.liveSpeed?.wert
      ? nachricht.liveSpeed
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
    laeuft && typeof nachricht.liveShare === 'number'
      ? nachricht.liveShare
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

<!-- One tool call: the name, a background run's number, a foretaste of
     the arguments. On its own it has its dot on the line;
     inside a bundle (`imBuendel`) the bundle's dot stands for all of them
     and the row has none. -->
{#snippet werkzeugEintrag(teil, i, imBuendel)}
  {@const stand = hintergrundStand(teil.werkzeug)}
  {@const wzPunkt = werkzeugPunkt(teil.werkzeug, stand)}
  <!-- A tool call is one row at the line: the name, a background
       run's number, a foretaste of the arguments, and on the right
       "running", an exit code or "failed". No card and no
       sign of its own — the dot on the line carries its state
       (werkzeugPunkt). Unfolded, arguments and result stand quietly
       at the line in fixed width. -->
  <div class="werkzeugzeile" class:ereignis={!imBuendel} class:im-buendel={imBuendel}>
    {#if !imBuendel}
      {@render punkt(wzPunkt.farbe, wzPunkt.atmet)}
    {/if}
    <button
      class="werkzeug-kopf"
      class:offen={offeneTeile.has(i)}
      aria-expanded={offeneTeile.has(i)}
      title={stand?.laeuft
        ? t('werkzeug.hintergrund_laeuft')
        : stand?.atmet ? t('werkzeug.hintergrund_ungelesen') : null}
      onclick={() => {
        teilKlappen(i)
        /* Opening the row is reading it: the dot of a finished
           background run stops moving here as well as when the next
           answer has read the report. Only a FINISHED run's — opened
           while the run still goes, the row would count the ending
           as read before it had happened, and green or red would
           never show. */
        if (stand && !stand.laeuft) teil.werkzeug.gesehen = true
      }}
    >
      <span class="wz-name werkzeugname">{teil.werkzeug.name}</span>
      <!-- WHICH run this was. Only a background run has a number;
           every other call is one of one and would be told nothing by
           a "#1". Quiet, because it identifies rather than reports. -->
      {#if teil.werkzeug.lauf_nummer != null}
        <span class="wz-nummer">#{teil.werkzeug.lauf_nummer}</span>
      {/if}
      {#if vorschau(teil.werkzeug.argumente)}
        <span class="wz-vorschau">{vorschau(teil.werkzeug.argumente)}</span>
      {/if}
      <!-- The row's far end says only what the reader acts on: a run that
           is still going, or a call that went wrong. How long a call took
           is left out — a number that changes with every call and moves
           the row's end with it is noise in a conversation. -->
      {#if stand?.laeuft}
        <span class="wz-rechts">
          <span class="wz-dauer">{t('werkzeug.hintergrund_laeuft')}</span>
        </span>
      {:else if teil.werkzeug.exit_code || teil.werkzeug.fehlgeschlagen}
        <span class="wz-rechts">
          <!-- The exit code says everything the word "failed"
               says AND which code it was, so it takes the word's
               place rather than standing next to it — three items at
               the far end of a 12.5px row is where a line stops being
               readable. Only where there IS one: an ordinary tool
               call has no exit code and keeps the word.

               Zero is deliberately not drawn. It is the absence of
               trouble, and a green "exit 0" on every finished command
               would be a badge for the normal case. Falsy covers both
               0 and the null of a run whose code nobody knows -- and
               that null then falls through to the word, which is the
               honest thing to say about it. -->
          {#if teil.werkzeug.exit_code}
            <span class="wz-code">{t('werkzeug.exit', { code: teil.werkzeug.exit_code })}</span>
          {:else if teil.werkzeug.fehlgeschlagen}
            <span class="wz-marke">{t('werkzeug.marke_fehlgeschlagen')}</span>
          {/if}
        </span>
      {/if}
    </button>
    {#if offeneTeile.has(i)}
      <div class="werkzeug-text" use:rollfade transition:slide={{ duration: 200 }}>
        {#if Object.keys(teil.werkzeug.argumente ?? {}).length}
          <dl class="wz-argumente">
            {#each Object.entries(teil.werkzeug.argumente) as [schluessel, wert] (schluessel)}
              <dt>{schluessel}</dt>
              <dd>{@html wertHtml(wert)}</dd>
            {/each}
          </dl>
        {/if}
        {#if teil.werkzeug.ergebnis}
          <pre class="wz-ergebnis"><code>{@html werkzeugErgebnisHtml(teil.werkzeug.ergebnis)}</code></pre>
        {:else}
          <p class="wz-leer">
            {teil.werkzeug.ergebnis === null ? t('werkzeug.laeuft_noch') : t('werkzeug.nichts_mitgeschrieben')}
          </p>
        {/if}
      </div>
    {/if}
  </div>
{/snippet}

<!-- One entry's dot on the answer's line. The house's own state dot
     (Leuchtpunkt.svelte), breathing while its entry is still going — the
     caller says so, as far as the pulse settings allow. The answer's own
     text wears an empty ring instead: it is no state, it is what everything
     else led to. -->
<!-- One thinking stretch: its head with the time it took, the whole text
     when unfolded, the newest thought while it runs. On its own it has its
     dot on the line; inside a bundle (`imBuendel`) it has none. A stretch in
     a bundle is never the running one — the bundle ends at its last call. -->
{#snippet gedankeEintrag(teil, i, imBuendel)}
  {@const laeuftHier = i === teile.length - 1 && denktJetzt}
  {@const dauer = laeuftHier ? null : denkDauer(i)}
  <div class:ereignis={!imBuendel} class:im-buendel={imBuendel}>
    {#if !imBuendel}
      {@render punkt('blau', laeuftHier && punktPulsiert('chat'))}
    {/if}
    <button class="gedanke-kopf" class:offen={offeneTeile.has(i)}
            aria-expanded={offeneTeile.has(i)} onclick={() => teilKlappen(i)}>
      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
        <path d="M9 6l6 6-6 6" />
      </svg>
      <span class:leucht={laeuftHier}>
        {laeuftHier
          ? t('nachricht.gedankengang_laeuft', { zeit: verstricheneZeit })
          : dauer
            ? t('nachricht.gedankengang_laeuft', { zeit: dauer })
            : t('nachricht.gedankengang')}
      </span>
    </button>
    {#if offeneTeile.has(i)}
      <!-- The whole text, quietly, at the line: at most ten lines
           high, the rest melting out at the bottom and scrolling
           inside without a bar (lib/rollfade.js). -->
      <div class="gedanke-text" use:rollfade transition:slide={{ duration: 200 }}>{teil.text}</div>
    {:else if laeuftHier}
      <div class="mitlesen">{letzterGedanke(teil.text)}</div>
    {/if}
  </div>
{/snippet}

{#snippet punkt(farbe, atmet = false)}
  <span class="punkt" aria-hidden="true">
    {#if farbe === 'antwort'}
      <span class="ring"></span>
    {:else}
      <Leuchtpunkt {farbe} groesse={9} {atmet} />
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
      {#if nachricht.content}<div class="bildtext">{nachricht.content}</div>{/if}
    {:else if skillTeil}
      <!-- Brightness only, no colour: which instruction was used is a fact
           about the message, not a state it is in. -->
      <span class="skillpille">/{skillTeil.name}</span>{#if ohneSkill}{' '}{ohneSkill}{/if}
    {:else}{nachricht.content}{/if}
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
             stroke-width="2" stroke-linecap="round">
          <path d="M20 11a8 8 0 10-2.3 5.7M20 5v6h-6" />
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
    <div class="antwortlinie">
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
                  <span class="bild-kopf">{t('nachricht.bild_laeuft')}</span>
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
          {@const offen = offeneTeile.has(eintrag.schluessel)}
          {@const punktStand = buendelPunkt(eintrag)}
          {@const laufend = laufenderAufruf(eintrag.eintraege)}
          <!-- Two or more tool calls in a row, with the thinking before and
               between them: one row, always closed. It names the number of
               calls — while one runs, that call's name and "running" — and
               its dot is the worst state among the calls. Opened, the calls
               and the thinking stand as they always did, without a dot
               each. -->
          <div class="ereignis werkzeugzeile buendel">
            {@render punkt(punktStand.farbe, punktStand.atmet)}
            <button
              class="werkzeug-kopf"
              class:offen
              aria-expanded={offen}
              onclick={() => teilKlappen(eintrag.schluessel)}
            >
              <!-- In the tool colour like every call's name: the row stands
                   for calls, and the drawing gives it the same face. -->
              <span class="wz-name werkzeugname">{t('werkzeug.buendel', { zahl: aufrufZahl(eintrag.eintraege) })}</span>
              <svg class="wz-pfeil" width="10" height="10" viewBox="0 0 24 24" fill="none"
                   stroke="currentColor" stroke-width="2.5" aria-hidden="true">
                <path d="M9 6l6 6-6 6" />
              </svg>
              {#if laufend}
                <span class="wz-vorschau werkzeugname">{laufend.name}</span>
                <span class="wz-rechts"><span class="wz-dauer">{t('werkzeug.buendel_laeuft')}</span></span>
              {/if}
            </button>
            {#if offen}
              <div class="buendel-inhalt" transition:slide={{ duration: 200 }}>
                {#each eintrag.eintraege as aufruf (aufruf.i)}
                  {#if aufruf.teil.art === 'reasoning'}
                    {@render gedankeEintrag(aufruf.teil, aufruf.i, true)}
                  {:else}
                    {@render werkzeugEintrag(aufruf.teil, aufruf.i, true)}
                  {/if}
                {/each}
              </div>
            {/if}
          </div>
        {:else}
        {@const teil = eintrag.teil}
        {@const i = eintrag.i}
        <!-- Every thinking stretch is its own entry with its own head, from
             the very first second, always unfoldable. While it is the one
             running, the word glows with the clock beside it and one line
             under it carries the newest thought; once it is over it folds to
             the head alone, with the time it took.

             NOT summarised across stretches on purpose: thinking → tool →
             thinking stays TWO entries with the tool between them, inside a
             bundle as well. -->
        {#if teil.art === 'reasoning'}
          {@render gedankeEintrag(teil, i, false)}

        {:else if teil.art === 'werkzeug' && teil.werkzeug.name === 'start_job' && teil.werkzeug.auftrag_id}
          {@const job = chatJob(teil.werkzeug.auftrag_id)}
          <!-- An agent this answer started: a quiet row at the line, the
               agent's sign where a call has its dot — so it reads at once
               as the agent's — then its name, how long it has been at work
               and the tool it called last; no card. Once it has stopped,
               the row keeps its name, the time it took and how it ended.
               Its transcript is one click away, in the agents view. -->
          <div class="ereignis agent-row">
            <span class="punkt agent-mark" aria-hidden="true"><Agentenmarke groesse={13} /></span>
            <span class="agent-name">{job?.agent ?? teil.werkzeug.argumente?.agent}</span>
            {#if job}
              <span class="agent-time">{agentRuntime(job)}</span>
              {#if job.state === 'laeuft'}
                {#if job.last_tool}<span class="agent-step werkzeugname">{job.last_tool}</span>{/if}
              {:else}
                <span class="agent-state" class:wartet={job.state === 'wartet'}>{t('jobs.zustand.' + job.state)}</span>
              {/if}
            {/if}
            <button class="agent-transcript" onclick={() => openTranscript(job?.id ?? teil.werkzeug.auftrag_id)}>
              {t('agent_row.transcript')}
            </button>
          </div>

        {:else if teil.art === 'werkzeug'}
          {@render werkzeugEintrag(teil, i, false)}

        {:else if teil.text.trim()}
          <div class="ereignis textzeile">
            {@render punkt('antwort')}
            <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
            <div class="antwort" onclick={antwortKlick}>
              {#each cardRows(dateiTeile(teil.text, versaetze[i])) as stueck, j (j)}
                {#if stueck.art === 'html'}
                  <!-- Drawn in place, not through {@html}: that one tears the
                       whole answer out on every chunk, and the scroll area's
                       dip threw the reader back (lib/lebendhtml.js). -->
                  <div class="fliesstext" use:lebendHtml={stueck.wert}></div>
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

      <!-- The files a tool handed into the chat with this answer: the same
           card a written file and an attachment wear, in a row that wraps.
           They belong to the answer, so each files its tab under this
           chat. Their text is the file itself, and saving one saves that
           file. Nothing of its own for this branch. -->
      {#if dokumentKarten.length}
        <div class="ereignis textzeile">
          {@render punkt('antwort')}
          <div class="antwort">
            <div class="file-row">
              {#each dokumentKarten as karte (karte.id || karte.name)}
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
           one fixed height, so a mark changing its face never moves the chat. -->
      {#if marke}
        <div class="ereignis">{@render marke()}</div>
      {/if}

      <!-- The notes below are entries on the line like everything else,
           standing where the thing happened — at the end, because that is
           where a run stops. Their dot says the state, so the row itself is
           only quiet text. -->
      {#if !hatInhalt && !laeuft && !nachricht.bild && !nachricht.bildLaeuft && !abgeschnitten}
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

    <div class="fuss">
      {#if messungen.length}
        <!-- One row of its own: the dot between two readings belongs to
             them (8 px apart), and the 14 px the footer keeps between its
             children would otherwise sit around the dot too. The dot wears
             the footer's ink as it is: dimmed, it fell under the contrast
             text needs. -->
        <span class="messungen">
          {#each messungen as messung, nummer}
            {#if nummer > 0}<span class="trenner" aria-hidden="true">·</span>{/if}
            <span class="messung" title={messung.titel}>
              <span class="zahl">{messung.zahl}</span> {messung.wort}
            </span>
          {/each}
        </span>
      {/if}
      {#each hinweise as wert}<span>{wert}</span>{/each}
      {#if laeuft}<span class="platzhalter"></span>{/if}
      <button class="tat" title={t('nachricht.kopieren')} aria-label={t('nachricht.kopieren')} onclick={kopieren}>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V5a2 2 0 012-2h10" />
        </svg>
      </button>
      <!-- Regenerate exists only on the last answer: recomputing one in
           the middle would invalidate everything after it (3.4). -->
      {#if istLetzte && nachricht.id}
        <button class="tat" title={t('nachricht.neu_erzeugen')} aria-label={t('nachricht.neu_erzeugen')}
                onclick={() => neuErzeugen(nachricht.id)}>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2" stroke-linecap="round">
            <path d="M20 11a8 8 0 10-2.3 5.7M20 5v6h-6" />
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
    --luecke-von: calc(1lh / 2 - 4.5px);
    --luecke-bis: calc(1lh / 2 + 4.5px);
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
  /* The waiting mark is the last entry and stands on the line itself: the
     line comes down to the top of its row and ends there. A lone mark has
     no line at all. */
  .ereignis:has(> :global(.wartet))::before {
    bottom: auto;
    height: calc(0px - var(--linie-oben));
  }
  .ereignis:has(> :global(.wartet)):first-child::before { display: none; }
  /* A thinking row's head is `inline-flex` and would sink by half a
     leading inside a taller line box; giving the row exactly one head
     line keeps it — and the dot's line (below) — in place. The tool row
     gets the same line, so its dot reads the same 19px. */
  .ereignis:has(> .gedanke-kopf),
  .ereignis:has(> .werkzeug-kopf) {
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
    width: 9px;
    height: 9px;
    box-sizing: border-box;
    border-radius: 50%;
    border: 1.5px solid var(--text-still);
  }
  /* The answer's text sets a larger line: its dot follows it — the same
     1.65 the answer text stands in. */
  .ereignis.textzeile {
    line-height: 1.65;
  }
  .textzeile > .punkt { top: 8px; top: calc(1lh / 2 - 5.5px); }

  /* An agent's row: as quiet as a tool call's, its sign in the dot's place. */
  .agent-row {
    display: flex;
    align-items: center;
    gap: 8px;
    min-height: 22px;
    font-size: 12.5px;
    color: var(--text-leise);
  }
  .punkt.agent-mark {
    width: 15px;
    height: 15px;
    left: -24px;
    top: 3px;
    color: var(--text-leise);
  }
  .agent-name { color: var(--text); font-weight: 500; }
  .agent-time { font-variant-numeric: tabular-nums; color: var(--text-still); }
  .agent-step {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--werkzeug);
    font: 12px var(--schrift-fest);
  }
  .agent-state { color: var(--text-still); }
  .agent-state.wartet { color: var(--gelb-text); }
  .agent-transcript {
    margin-left: auto;
    flex: none;
    padding: 2px 8px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-still);
    font: inherit;
    font-size: 12px;
    cursor: pointer;
  }
  .agent-transcript:hover { background: var(--bg-hoch); color: var(--text); }
  /* A picture in an image run's grid is a tile, not an answer — no line
     and no dot there. The grid is App.svelte's (`.bildlauf-platz`). */
  :global(.bildlauf-platz) .antwortlinie { padding-left: 0; }
  :global(.bildlauf-platz) .ereignis::before,
  :global(.bildlauf-platz) .punkt { display: none; }

  /* The mark that says "this answer thought first", in the house blue: the
     one colour the interface already spends on "something is running", and
     the reason it is not a colour of its own is that a fifth state colour
     beside blue, yellow, green and red would have to earn its meaning
     first. What it may NOT be is the still grey of a subtitle — that is the
     tone for something you may skip, and this line is the opposite.
     The unfolded thought below keeps its own quieter tone: the mark says
     something IS there, the text is what it says. */
  .gedanke-kopf {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font: inherit;
    font-size: 12.5px;
    line-height: 19px;
    color: var(--blau-text);
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
  }
  .gedanke-kopf svg {
    flex: none;
    transition: transform 0.18s;
  }
  .gedanke-kopf.offen svg {
    transform: rotate(90deg);
  }
  /* While the stretch runs, the word glows: a lighter band of the same blue
     sweeps across it. Held still for whoever asks for less motion. */
  .leucht {
    background: linear-gradient(90deg, var(--blau-text) 0%, var(--blau-text) 35%,
      color-mix(in srgb, var(--blau-text) 40%, white) 50%, var(--blau-text) 65%, var(--blau-text) 100%);
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
  /* One line with the newest thought while the stretch runs. */
  .mitlesen {
    font-size: 12.5px;
    line-height: 20px;
    color: var(--text-still);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  /* The whole text, unfolded: quiet, at the line, no card and no rule of
     its own. Ten lines at most; the rest scrolls inside without a bar and
     melts out at the edge (lib/rollfade.js). */
  .gedanke-text {
    font-size: 12.5px;
    line-height: 1.6;
    color: var(--text-leise);
    margin-top: 4px;
    max-height: calc(10 * 1.6em);
    overflow-y: auto;
    white-space: pre-wrap;
  }
  /* A tool call is one row at the line: no tile, no sign. The dot on the
     line carries the state (werkzeugPunkt), the row only says what ran —
     name, run number, a preview of the arguments, and at the far end the
     duration or what broke. What does not fit is cut with an ellipsis;
     the row unfolds and shows it whole. */
  .werkzeug-kopf {
    display: flex;
    align-items: center;
    gap: 7px;
    width: 100%;
    max-width: 100%;
    min-width: 0;
    font-family: var(--schrift-fest);
    font-size: 12px;
    line-height: 19px;
    color: var(--text-still);
    text-align: left;
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
  }
  /* Only the layout: how a tool name is set is one rule for the whole
     program (`.werkzeugname`, stil/global.css). `flex: none` keeps it
     whole — the preview beside it is the one built to give way. */
  .werkzeug-kopf .wz-name {
    flex: none;
  }
  /* The arrow after the bundle's count: it turns when the bundle is open. */
  .werkzeug-kopf .wz-pfeil {
    flex: none;
    transition: transform 0.15s;
  }
  .werkzeug-kopf.offen .wz-pfeil {
    transform: rotate(90deg);
  }
  /* The calls inside an open bundle: the same rows, one under the other,
     without a dot each. */
  .buendel-inhalt {
    margin-top: 6px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .im-buendel {
    min-width: 0;
  }
  .werkzeug-kopf .wz-vorschau {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }
  .werkzeug-kopf:hover .wz-vorschau {
    color: var(--text-leise);
  }
  /* "Running" and the failure mark share the row's far end — one item
     pushed right, not two competing auto margins. They are words, not
     code, so they leave the fixed face. */
  .werkzeug-kopf .wz-rechts {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 8px;
    flex: none;
    font-family: var(--schrift);
    white-space: nowrap;
  }
  .werkzeug-kopf .wz-dauer {
    color: var(--text-still);
  }
  .werkzeug-kopf .wz-marke,
  .werkzeug-kopf .wz-code {
    flex: none;
    color: var(--rot);
  }
  /* The run number identifies, it does not report — a step quieter still.
     `flex: none` for the same reason the name has it: a number that gives
     up a digit is a different number. */
  .werkzeug-kopf .wz-nummer {
    flex: none;
    opacity: 0.8;
  }
  /* The unfolded arguments and result stand quietly at the line in the
     fixed face — no card, at most ten lines high. The rest scrolls without
     a visible bar and melts out at the edge while more lies beyond it
     (`use:rollfade`). */
  .werkzeug-text {
    margin-top: 6px;
    font-family: var(--schrift-fest);
    font-size: 11.8px;
    line-height: 1.55;
    color: var(--text-leise);
    max-height: calc(11.8px * 1.55 * 10);
    overflow-y: auto;
    overflow-x: hidden;
  }
  .wz-argumente {
    margin: 0 0 6px;
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 1px 10px;
  }
  .wz-argumente dt {
    color: var(--text-still);
    white-space: nowrap;
  }
  .wz-argumente dd {
    margin: 0;
    min-width: 0;
    overflow-wrap: anywhere;
  }
  /* The result is a tool's raw text, not prose — it keeps its own line
     breaks, and a wide table or long path wraps instead of pushing the
     page sideways. */
  .wz-ergebnis {
    margin: 0;
    font: inherit;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  /* A change block's own rows, inside the same .wz-ergebnis <pre> — the
     block-level element is what lets the tinted background reach the full
     width of the box instead of hugging just the text. */
  .wz-ergebnis :global(.diff-zeile) {
    display: block;
  }
  .wz-ergebnis :global(.diff-entfernt) {
    color: var(--rot);
    background: color-mix(in srgb, var(--rot) 12%, var(--bg));
  }
  .wz-ergebnis :global(.diff-hinzu) {
    color: var(--gruen);
    background: color-mix(in srgb, var(--gruen) 12%, var(--bg));
  }
  .wz-ergebnis :global(.diff-kopf) {
    color: var(--code-komm);
  }
  .wz-ergebnis :global(.diff-hinweis) {
    color: var(--code-komm);
    font-style: italic;
  }
  .wz-leer {
    margin: 0;
    color: var(--text-still);
  }

  .antwort {
    line-height: 1.65;
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
  /* The readings of an answer: number bright, word quiet. The fixed font
     gives every digit the same width, so the line does not wobble while the
     figures change during a run. */
  .messungen {
    display: inline-flex;
    align-items: baseline;
    gap: 8px;
  }
  .messung {
    font-family: var(--schrift-fest);
  }
  .messung .zahl {
    color: var(--text);
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
