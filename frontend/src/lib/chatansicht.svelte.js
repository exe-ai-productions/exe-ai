/*
  What the list of a chat shows of its run: which row is the one running, the
  waiting mark that stands at its end with its word and its clock, the clock
  of a fold in progress, the pictures of one run gathered into tiles, and
  how many files the messages before one carry.

  Called while a page is made, by the desktop page and by the phone page: it
  sets up the derived values and the clocks of that page, which end with it.
  It needs a component being made (it creates effects), and each call has its
  own waiting word and its own hold on the chat's clock; only one page shows
  the chat at a time.
*/

import { stoppuhr } from './dauer.js'
import { takt, taktHalten } from './sekundentakt.svelte.js'
import { t, texte } from './texte.svelte.js'
import { zustand, nachrichtenAnzeige } from './zustand.svelte.js'
import { dateienVorherJeNachricht } from './markdown.js'
import { fragtNach } from './chatringe.svelte.js'
import { chatRun } from './chatlauf.svelte.js'

export function useChatAnsicht() {
  const { compactSince, bildDateien } = chatRun



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
      .find(zeileLaeuft)
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
    /* The thinking head above counts this very stretch, and a second clock
       for the same seconds under it would only repeat it. The mark stays,
       with its word and its line's height, and counts nothing while the
       head does; with the first tool or text the activity changes and the
       clock starts again from that moment. The same reading the head makes
       of the row (teile/Nachricht.svelte, `denktJetzt`). */
    if (zeile.taetigkeit === 'denkt') return { ...marke, seit: null }
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

  const compactFrom = $derived(compactSince[zustand.aktiverChat] ?? null)

  $effect(() => {
    if (compactFrom === null) return
    return taktHalten()
  })

  const compactClock = $derived(
    compactFrom === null ? '' : stoppuhr(takt.jetzt - compactFrom),
  )

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

  /* Where each answer's file numbering stands: file names run across the
     whole chat (lib/markdown.js), so a message is told how many files the
     ones before it carry. */
  const dateienVorherKarte = $derived(dateienVorherJeNachricht(nachrichtenAnzeige()))

  /* The row a run in THIS window is writing — by id, never by position.
     `laufenderPlatzhalter` is the very object the stream writes into, so
     asking it is asking the run itself. The stored `zustand === 'laeuft'`
     covers the other direction: a run this window did not start, whose row
     the server already marks as live. */
  const laufenderId = $derived(
    zustand.laufenderPlatzhalter[zustand.aktiverChat]?.id ?? null,
  )

  /* Whether a row counts as running: the service names it so on the row, or
     it is the row of a run of this window that has not ended here. A run
     ends here with its closing event or with the break of its stream — what
     the window does after that (fetching the stored list, up to
     `NACHLADE_FRIST_MS`) is the run's own bookkeeping, and the row is no
     longer live during it. The mark and the bubble both read this one. */
  function zeileLaeuft(zeile) {
    return (
      zeile.zustand === 'laeuft' ||
      (Boolean(laufenderId) && zeile.id === laufenderId && !zeile.runEnded)
    )
  }

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
    // Pictures the user took out (a cross, a stop) were never going to be
    // drawn: they are not ones that "were not generated". The window's own
    // count is on the run's row (`stats.abgenommen`, written when the run
    // ended), so the reloaded row says the same as the toast did.
    const abgenommen = geteilteZeilen.reduce(
      (summe, n) => summe + (Number(n.stats?.abgenommen) || 0), 0,
    )
    const gescheitert = von - gezeichnet - abgenommen
    return gescheitert > 0 ? { gescheitert, von } : null
  }

  return {
    zeileLaeuft,
    bildKacheln,
    laufendeKachel,
    inKachelAufgegangen,
    teilausfall,
    BILDLAUF_KACHEL_RAHMEN,
    get BILDLAUF_KACHEL() {
      return BILDLAUF_KACHEL
    },
    get laufMarke() {
      return laufMarke
    },
    get laufZeit() {
      return laufZeit
    },
    get wartewort() {
      return wartewort
    },
    get compactFrom() {
      return compactFrom
    },
    get compactClock() {
      return compactClock
    },
    get dateienVorherKarte() {
      return dateienVorherKarte
    },
  }
}
