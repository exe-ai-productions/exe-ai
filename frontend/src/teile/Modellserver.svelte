<script>
  import { rollfade } from '../lib/rollfade.js'
  /* The model server — switched from here instead of from a terminal.

     One truth on top: a status card that says whether the server runs,
     which model, which speed module by name, and how much memory it holds.
     Below it the form, in named groups instead of a bare field list, and
     locked while the server runs — a running server is not edited, it is
     stopped first. On a fresh machine none of that shows yet; instead the
     three steps to a first model stand here.

     The speed module is not guessed. When the catalogue fetched the model
     it wrote which module belongs to it; the runner reads that and this
     form pre-picks it. The name heuristic is only a fallback for
     hand-placed files, and a tightened one: an mtp module must match the
     model's family AND its parameter count, so a 12B module never drafts a
     31B model. */
  import { api } from '../lib/api.js'
  import { t } from '../lib/texte.svelte.js'
  import { katalogOeffnen, melde, modelleLaden, zustand } from '../lib/zustand.svelte.js'
  import { serverAnteil } from '../lib/speicherschaetzung.js'
  import { empfehlungFuer } from '../lib/modellempfehlungen.js'
  import { FEINEINSTELLUNGEN } from '../lib/feineinstellungen.js'
  import { nurGeaendert } from '../lib/nurgeaendert.js'
  import {
    gemerkteDatei,
    modulFuer,
    modulSetzen,
    runnermodell,
    standLaden,
    werteSetzen,
  } from '../lib/runnermodell.svelte.js'
  import { HAUPTMODELL } from '../lib/agentenserver.svelte.js'
  import Servertafel from './Servertafel.svelte'
  import Serverregler from './Serverregler.svelte'
  import Startknopf from './Startknopf.svelte'
  import Leuchtpunkt from './Leuchtpunkt.svelte'
  import Serverreihe from './Serverreihe.svelte'
  import Serverabschnitt from './Serverabschnitt.svelte'
  import Serverlogkopf from './Serverlogkopf.svelte'
  import UpToDateMark from './UpToDateMark.svelte'
  import {
    protokollOffen,
    oeffneProtokoll,
    setzeProtokollZeilen,
  } from '../lib/protokollfenster.svelte.js'

  let auskunft = $state(null)
  let protokoll = $state([])
  let protokollAuf = $state(false)
  let arbeitet = $state(false)
  let protokollKasten = $state(null)

  // Keep the big log window fed while it is open.
  $effect(() => {
    if (protokollOffen()) setzeProtokollZeilen(protokoll)
  })
  let programmStand = $state(null)
  const programmLaedt = $derived(
    Boolean(programmStand) && !programmStand.fertig && !programmStand.fehler,
  )

  let tempo = $state(0)
  let messung = null
  function tempoMessen(neu) {
    const jetzt = Date.now()
    if (neu && messung && jetzt > messung.zeit) {
      const frisch = ((neu.geladen - messung.geladen) / (jetzt - messung.zeit)) * 1000
      tempo = tempo ? tempo * 0.4 + frisch * 0.6 : frisch
    } else {
      tempo = 0
    }
    messung = neu ? { geladen: neu.geladen, zeit: jetzt } : null
  }
  const mbs = $derived(tempo > 50_000 ? (tempo / 1e6).toFixed(1) + ' MB/s' : '')

  $effect(() => {
    void protokoll
    if (protokollKasten) protokollKasten.scrollTop = protokollKasten.scrollHeight
  })

  /* Held back until the stored numbers are in: without it the watcher below
     would write these placeholders over them on the very first pass.

     They are placeholders and nothing else — what an unset choice falls back
     to is decided in one place on the server (app/runnermodellwahl.py) and
     arrives in `auskunft.vorgaben`. A number written down here as well would
     agree with it right up until somebody changed one of the two. */
  let zahlenStehen = $state(false)
  let kontext = $state(0)
  let schichten = $state(0)
  let port = $state(0)
  let modell = $state('')
  let drafter = $state('')
  let vision = $state('')
  let vorladen = $state(true)

  /* The parameter count in a model name — "12B", "31b", "1.7B". Two models
     of one family but different sizes must not draft one another with an
     mtp module, which is trained for one exact model. */
  function parameterzahl(name) {
    const treffer = name.toLowerCase().match(/(\d+(?:\.\d+)?)\s*b\b/)
    return treffer ? treffer[1] : null
  }
  function gemeinsam(a, b) {
    const x = a.toLowerCase()
    const y = b.toLowerCase()
    let i = 0
    while (i < x.length && i < y.length && x[i] === y[i]) i++
    return i
  }

  /* Draft candidates: same family, clearly smaller. A prediction module
     (mtp) comes first — trained alongside its model, a few hundred
     megabytes, the best draft there is — and it must match the parameter
     count exactly. A tiny sibling model is the fallback, capped at sixty
     percent of the size. Most models rightly end up with none. */
  const drafterKandidaten = $derived.by(() => {
    const haupt = (auskunft?.modelle ?? []).find((m) => m.name === modell)
    if (!haupt) return []
    const hp = parameterzahl(haupt.name)
    const module = (auskunft?.mtp ?? []).filter((m) => {
      const basis = m.name.replace(/^mtp[-._]/i, '')
      if (gemeinsam(basis, haupt.name) < 5) return false
      const mp = parameterzahl(basis)
      // Both sized and different means a wrong pairing; only equal (or an
      // unlabelled one) may draft.
      return hp && mp ? mp === hp : true
    })
    const geschwister = (auskunft?.modelle ?? []).filter(
      (m) =>
        m.name !== modell &&
        gemeinsam(m.name, haupt.name) >= 5 &&
        m.groesse_gb <= haupt.groesse_gb * 0.6,
    )
    return [...module, ...geschwister]
  })

  const schaetzung = $derived(
    serverAnteil(auskunft?.modelle, auskunft?.mtp, { modell, kontext, drafter }),
  )
  /* This server's entry in the head's figure, live while the page is open —
     the hand moves the window slider here, and the head must move with it
     rather than wait for the next poll. The head fills this entry itself
     while the page is closed, from the same stored choice this form reads
     back on opening, so the number does not change when the page does.

     While it RUNS, this entry is what the process actually holds, measured.
     Nothing was the old answer, on the reasoning that a running server's
     hold already stands on its own card — but the head's figure is what says
     whether the NEXT start fits, and the commonest way through is to start
     the main model first and the agent slot after it. So the number that had
     to carry the pair carried one of them: 20.4 GB shown where the truth was
     68.4, the start then failed, and the line had said nothing. Measured and
     planned are both real gigabytes off the same machine, and the row is
     headed "memory", not "expected". */
  $effect(() => {
    zustand.serverPlan.modell = laeuft
      ? (auskunft?.belegt_gb ? { gesamt: auskunft.belegt_gb, gemessen: true } : null)
      : schaetzung
    /* Handed back when the page goes away — the head then works the entry
       out for itself. Left standing instead, a stale plan would outlive the
       choice that made it, and the head would be right only by luck. */
    return () => (zustand.serverPlan.modell = null)
  })

  const laeuft = $derived(Boolean(auskunft?.laeuft))

  /* The window's one deed, handed to the modules group's head line — the
     button stands in the line of the first group, flush with the
     card below it, not up in the head card. */
  const tat = $derived({
    text: laeuft ? t('modell.server_anhalten') : t('modell.server_starten'),
    punkt: laeuft ? 'gruen' : 'still',
    gesperrt: arbeitet || (!laeuft && !modell),
    onTat: laeuft ? anhalten : starten,
  })

  const hatProgramm = $derived(Boolean(auskunft?.programm))
  const hatModelle = $derived((auskunft?.modelle?.length ?? 0) > 0)
  const maschineGb = $derived(auskunft?.speicher_gb ?? null)
  /* The first-run guidance stands in place of the form until a model lies
     in the folder. */
  const erststart = $derived(!laeuft && !hatModelle)
  const vorschlag = $derived(maschineGb ? empfehlungFuer(maschineGb) : null)

  const kurzK = (n) => (n ? Math.round(n / 1024) + 'k' : '')

  /* The steps a context really comes in. Below 4096 there is no conversation
     worth having, and above that the engine only understands these numbers —
     a field that silently accepts 33000 and then behaves like 32768 teaches
     nobody anything.

     What a given model can actually hold is not asked here, because nothing
     in the program knows it yet: it stands in the model file's own header,
     and reading that is a job of its own. Until then the list is the same
     everywhere, and a model that cannot hold the chosen size says so when it
     starts — which is where it said so before as well. */
  const kontextstufen = [4096, 8192, 16384, 32768, 65536, 131072]
  /* 99 is llama.cpp's own way of saying "all of them", and the right-hand
     stop of the slider says the same thing in words. */
  const MAX_SCHICHTEN = 99
  /* The machine's own core count, read from the server. More threads than
     cores makes a run SLOWER — they fight for the same cores — so the track
     stops where the machine does instead of offering a value that only
     hurts. The fallback is a small, safe number for the moment before the
     first answer arrives. */
  const MAX_FAEDEN = $derived(auskunft?.kerne ?? 8)

  /* flash_attention is deliberately NOT in here any more: there is no
     control for it, the engine's "auto" decides — and a stored "off" from
     an older version must not keep riding along with every start. */
  const FEIN_VORGABE = {
    kv_cache: 'f16',
    moe_auf_cpu: false,
    festnageln: false,
  }
  let fein = $state({ ...FEIN_VORGABE })
  /* Kept as plain numbers here because the number field speaks numbers; 0
     means "let the engine decide" and travels as nothing. */
  let faeden = $state(0)
  /* Experts on the CPU as one number: empty means
     off, a count means that many layers. */
  let moeSchichten = $state(null)
  /* Server slots (--parallel): how many requests compute at once. 0 means
     the engine's own "auto" and travels as nothing — the silent half must
     produce the exact command every start produced before this lever
     existed. Ceiling mirrors the backend's MAX_PARALLEL: the engine names
     none itself, but every slot gets an equal share of the context. */
  let parallel = $state(null)
  const MAX_PARALLEL = 64

  const feindaten = $derived({
    ...fein,
    /* The switch and its count became one slider; the engine flag follows
       the number — above zero means on. */
    moe_auf_cpu: Boolean(moeSchichten && moeSchichten > 0),
    faeden: faeden || null,
    moe_schichten: moeSchichten || null,
    parallel: parallel ?? null,
  })

  /* The levers used to live only here, in this form. Reloading the window
     put every one of them back to its default while the server kept running
     with what it was given — so the drawer said f16 about a server holding
     q4_0, and the next start went out without the settings that were the
     only reason the model fitted at all.

     Loaded once: the running server first, the stored choice otherwise. */
  let feinGeladen = $state(false)

  /* What this window knows is stored under the levers' own key — `null` while
     nothing is. The levers are a THIRD key with a writer of its own
     (app/feineinstellungenwahl.py, written with PUT), and without this it had
     the freezing the numbers were cured of: merely opening this page wrote
     the shipped levers into the setting as a choice, so a later change of a
     shipped default never reached anybody who once opened the page. Measured,
     not argued — see the report of 02.09.

     What this does NOT fix is the second window on this key: PUT replaces the
     whole row, so the only real cure is a merging write, and that needs the
     key's own module to accept a partial value. Reported. */
  let feinStand = null

  /* The levers the form ships with, as the form itself sends them. */
  const feinVorgabewerte = {
    ...FEIN_VORGABE,
    faeden: null,
    moe_schichten: null,
    parallel: null,
  }

  /* Whether the levers say anything that is not already stored — the same
     filter, and the same two rules, the numbers go through
     (lib/nurgeaendert.js). */
  function feinNachzutragen() {
    return Object.keys(
      nurGeaendert({ fein: feindaten }, { fein: feinStand }, { fein: feinVorgabewerte }),
    ).length > 0
  }

  async function feinSchreiben() {
    const werte = { ...feindaten }
    await api.einstellungSetzen('global', FEINEINSTELLUNGEN, werte)
    feinStand = werte
  }

  function feinUebernehmen(daten) {
    fein = {
      /* The step an older version offered maps to the surviving saving
         step — whoever stored q4_0 was saving memory on purpose. Same rule
         as the backend's KV_ALT. */
      kv_cache: daten.kv_cache === 'q4_0' ? 'q8_0' : (daten.kv_cache ?? fein.kv_cache),
      moe_auf_cpu: Boolean(daten.moe_auf_cpu),
      festnageln: Boolean(daten.festnageln),
    }
    faeden = daten.faeden || 0
    /* The stored kinds of "all experts on the CPU": the older switch
       without a count (`moe_auf_cpu: true`, no `moe_schichten`), and the
       backend's own zero — `moe_schichten: 0` turns into `--cpu-moe`, all
       of them. The slider says the same thing at its ceiling. Read any of
       the three, so an older choice survives the ride: without this the
       "all" was recomputed as "off" and quietly written back as a choice
       nobody made. The agent page carries the same line. */
    moeSchichten = daten.moe_schichten === 0
      ? 999
      : (daten.moe_schichten ?? (daten.moe_auf_cpu ? 999 : null))
    parallel = daten.parallel ?? null
    feinGeladen = true
  }

  async function feinLaden() {
    try {
      const antwort = await api.einstellungAufgeloest(FEINEINSTELLUNGEN)
      if (antwort?.wert && typeof antwort.wert === 'object') {
        /* Nothing stored comes back as an EMPTY object from this route, not
           as an error and not as the defaults — measured, after the first
           attempt at this brake wrote anyway. An empty answer is "nobody has
           chosen", which is exactly the `null` the filter's first rule looks
           for; handing the empty object on instead made every lever look
           changed and put the freezing straight back. */
        feinStand = Object.keys(antwort.wert).length ? antwort.wert : null
        feinUebernehmen(antwort.wert)
      }
    } catch {
      /* Nothing stored yet is the normal first case, not an error. */
    } finally {
      feinGeladen = true
    }
  }

  /* Written when the levers come to rest, not on every click — and never
     before they were read, or the first poll would store the defaults over
     whatever was there.

     And only when they say something that is not already stored. Writing
     unconditionally is what froze the shipped levers into a choice on the
     mere opening of this page; see `feinStand`.

     `laeuft` for the same reason the numbers below carry it: while a server
     runs, the poll pushes the RUNNING process's levers into this form every
     two seconds, and without the guard the mere opening of the page on a
     running server wrote those back as the choice — over the levers the user
     had actually picked, with every control locked the whole time. The form
     is a readout then, not an answer. */
  $effect(() => {
    const _ = JSON.stringify(feindaten)
    if (!feinGeladen || laeuft) return
    const uhr = setTimeout(() => {
      if (!feinNachzutragen()) return
      feinSchreiben().catch(() => {})
    }, 600)
    return () => clearTimeout(uhr)
  })

  /* What the panel is doing, as the head card's one line: the facts that
     used to be spread over a status card, joined by the same separator the
     rest of the house uses. The speed module is named here too — it is the
     one running fact the form below does not repeat while locked. */
  const laufzeile = $derived.by(() => {
    if (!laeuft) return ''
    const teile = [
      t('modell.laeuft_port', { port: auskunft.port }),
      t('modell.kontext_kurz', { n: kurzK(auskunft.kontext) }),
    ]
    if (auskunft.drafter) teile.push(`${t('modell.mtp_label')}: ${auskunft.drafter}`)
    if (auskunft.belegt_gb) teile.push(t('modell.im_speicher', { gb: auskunft.belegt_gb }))
    return teile.join(' · ')
  })

  /* The candidate rule above narrows what this row SUGGESTS. It never was an
     answer about what is attached: what a start really drafts against is
     decided in the process, from the remembered choice and the folder
     manifest (app/modellrunner.py `starten`), and neither of those knows this
     rule. So a remembered or declared module the rule would not propose is
     still listed — as itself, ahead of the suggestions.

     It used to be blanked out of the field instead, and that was wrong twice:
     the row said "none" about a command line carrying --model-draft, and it
     made the choice unreachable, because picking "none" on a row that already
     reads "none" writes nothing (Auswahlfeld.svelte `waehlen`). The page has
     to show what would actually run before "no thanks" can be an answer to
     it — the same reasoning the slot's module rows stand on. */
  const drafterauswahl = $derived([
    { wert: '', text: t('modell.drafter_keiner') },
    ...(drafter && !drafterKandidaten.some((m) => m.name === drafter)
      ? [{ wert: drafter, text: drafter }]
      : []),
    ...drafterKandidaten.map((m) => ({ wert: m.name, text: `${m.name} · ${m.groesse_gb} GB` })),
  ])

  /* Every projector in the vision folder, "without" first. Not narrowed by
     name: the whole point of this row is the companion the name heuristic
     cannot pair — so the choice is the user's, across the full list. */
  const visionauswahl = $derived([
    { wert: '', text: t('modell.vision_keiner') },
    ...(auskunft?.mmproj ?? []).map((name) => ({ wert: name, text: name })),
  ])

  /* An empty choice at the top, like the three module rows have: a fresh
     install ships with nothing loaded, and a list that cannot be set back to
     nothing would make "no model" a state only the first start ever sees. */
  const modellauswahl = $derived([
    { wert: '', text: t('modell.modell_keiner') },
    ...(auskunft?.modelle ?? []).map((m) => ({ wert: m.name, text: `${m.name} · ${m.groesse_gb} GB` })),
  ])

  /* The stored numbers, into the form. Taken once — this runs on a
     two-second poll and would otherwise fight the hand in the field. */
  function werteUebernehmen() {
    const v = auskunft?.vorgaben ?? {}
    kontext = runnermodell.kontext ?? v.kontext
    schichten = runnermodell.schichten ?? v.schichten
    /* Null means "the server's own port", and only the server knows what
       that is — it comes back in `port` while nothing runs. */
    port = runnermodell.port ?? auskunft?.port
    vorladen = runnermodell.vorladen ?? v.vorladen
    zahlenStehen = true
  }

  /* Whether the last poll saw a server running — so the end of a run can be
     told from the middle of one. See `laden`. */
  let liefVorher = false

  /* What this poll reported last, so a failure that lasts is reported once
     rather than once every two seconds. See the catch in `laden`. */
  let letzterFehler = null

  /* The module pair for one file, into the two rows: the remembered choice
     first — including a remembered "none" — and only then the pairing the
     folder manifest declared. */
  function modulUebernehmen(datei) {
    const modul = modulFuer(datei)
    const z = auskunft?.zuordnung?.[datei]
    if (modul.drafter !== null) drafter = modul.drafter
    else if (z?.mtp) drafter = z.mtp
    if (modul.vision !== null) vision = modul.vision
    else if (z?.mmproj) vision = z.mmproj
  }

  async function laden() {
    try {
      auskunft = await api.runnerAuskunft()
      if (!runnermodell.geladen) await standLaden()
      if (!zahlenStehen && runnermodell.geladen) werteUebernehmen()
      if (!modell) {
        /* The mask remembers the hand: a running server wins, then the model
           last STARTED here (if its file is still in the folder), then the
           first in the list. The drafter follows the remembered per-model
           choice — including a remembered "none" — before the catalogue's
           recorded pairing gets to guess. */
        modell = auskunft.modell || gemerkteDatei(auskunft.modelle) || ''
        modulUebernehmen(modell)
      }
      if (auskunft.laeuft) {
        kontext = auskunft.kontext
        schichten = auskunft.schichten
        port = auskunft.port
        drafter = auskunft.drafter || ''
        /* `??` and not `||`: `""` is a running answer here, not a missing
           one. `Lauf.vision` is the parameter that was handed in, so `null`
           means "the run says nothing about it" — the manifest and the name
           heuristic are resolved later, in `befehl` — while `""` means the
           run was started mute and its command line carries no --mmproj.
           `||` threw the second one away with the first and left this
           window's own copy of the row standing, so a projector another
           window had just switched off went on being named here. Same line,
           same reasoning, on the slot's page. */
        vision = auskunft.vision ?? vision
        /* What the running server was actually started with beats what was
           once chosen — and it is taken only once, because this runs every
           two seconds and would otherwise fight the hand in the drawer. */
        if (!feinGeladen && auskunft.fein) feinUebernehmen(auskunft.fein)
      } else if (liefVorher) {
        /* The run is over, so the numbers above are a report and not an
           answer any more — the stored choice takes the fields back.

           Without this the run's numbers stayed in the form and the watcher
           below wrote them into the choice the moment the lock came off. A
           start from anywhere but this page then rewrote what the user had
           set: fetch a model, start it from the catalogue on the defaults,
           stop it again, and 32768/99 stood where 131072 and 0 layers had
           been. The one path that never noticed is the one where both are
           the same — a start FROM this page, which stores the fields first.

           The two module rows come back for the same reason. Nothing writes
           them any more except the hand that picks them — the start button
           stopped doing it in 7c49647 — but a row left on what the run
           reported goes on saying "none" about the pairing the NEXT start
           would attach, and a row already reading "none" cannot be set to
           "none" (Auswahlfeld.svelte `waehlen`).

           Read back from the server first: "the stored choice" is not this
           window's copy of it. `standLaden` reads once when a page opens, so
           everything another window stored since then is news to this one —
           and taking the fields back from the stale copy is exactly how a
           projector somebody else switched off walked back into this row the
           moment the run ended.

           And that read is where the hole this closes was: `await` hands
           control back. Svelte flushes, the watcher below sees `laeuft`
           false, `zahlenStehen` true and the RUN's numbers still in the
           fields, and starts its 600 ms clock. A read that takes longer than
           that — a service busy stopping a process is exactly when it does —
           and the run's numbers are written as the choice, over whatever
           somebody else had stored. Measured: 131072/0 replaced by 32768/99
           on a stop, which is word for word the loss this hand-back was
           built against.

           So the fields are handed back BEFORE the read as well, out of the
           copy this window already holds. Nothing is locked for the wait;
           the wait is simply made harmless. What stands in the form while
           the read is out is the store's own value, and the watcher only
           writes what the form says and the store does not (nurGeaendert) —
           so it finds nothing to say. A start pressed in that same stretch
           sends only the file, because that filter empties its supplement
           too, and the service reads window, layers and port out of the
           setting itself (app/runnermodellwahl.py `startwerte`). A failed
           read leaves the copy standing in the fields, writes nothing, locks
           nothing, and `liefVorher` keeps standing so the next poll tries
           again.

           The price is that the fields step twice on a stop — run value,
           this window's copy, then whatever the read brings. Visible and
           right beats invisible and wrong. What it buys is that there is no
           state to be stuck in: the lock this replaced came down in this
           branch alone, so one refused read left it up — through the whole
           of the NEXT run, with the stop button dead and nothing on the page
           saying why. Measured: 15 seconds into a second run, still locked. */
        werteUebernehmen()
        if (modell) modulUebernehmen(modell)
        await standLaden(true)
        werteUebernehmen()
        if (modell) modulUebernehmen(modell)
      }
      liefVorher = auskunft.laeuft
      if (!feinGeladen && !auskunft.laeuft) await feinLaden()
      if (protokollAuf || protokollOffen() || auskunft.laeuft) protokoll = await api.runnerProtokoll()
      /* While the program is missing — and while a fetch runs beside a
         program that is there: an update starts with the program in place,
         and nothing else would ever see it end. */
      if (!auskunft.programm || programmLaedt) {
        programmStand = await api.serverProgrammStand()
        tempoMessen(
          programmStand && !programmStand.fertig && !programmStand.fehler ? programmStand : null,
        )
      }
      if (auskunft.laeuft && !zustand.modelle.some((m) => m.anbieter === HAUPTMODELL && m.erreichbar)) {
        await modelleLaden(true)
      }
      letzterFehler = null
    } catch (fehler) {
      /* Once per streak, not once per tick. This runs every two seconds, and
         a failure that lasts — a refused settings read is the ordinary case
         — put a red tile and a sound on the screen every single time:
         measured, 15 of each in 30 seconds, on both server pages. A repeated
         error must still be SEEN, so it is reported the moment it starts and
         again the moment it says something else; what stops is the repetition
         of an answer already given. Cleared by a tick that gets through, so
         the same failure returning later is news again. */
      if (fehler.message !== letzterFehler) melde(fehler.message, 'fehler')
      letzterFehler = fehler.message
    }
  }

  $effect(() => {
    laden()
    const takt = setInterval(laden, 2000)
    return () => clearInterval(takt)
  })

  /* Written when the numbers come to rest, not on every drag of a slider —
     and never before they were read, or the first pass would store the
     placeholders over what was there.

     And never while the server is running, the way the slot's page has it
     (Agentserver.svelte). The fields are locked then, so no hand can have
     moved them — but the poll above pushes the RUNNING server's numbers into
     them every two seconds, and this would write those back as the user's
     choice. That is how a hand-over could still be lost: start something from
     outside this page, open the page, and the choice just carried over from
     the browser was replaced by whatever the running process happened to get.

     And only the fields the hand actually moved. Sending the whole trio on
     every change sent two values this window had not touched — its copies,
     as old as the moment the page opened — so a second window's context was
     undone by the next drag of the layers slider over here. The PATCH route
     can only keep the keys a request leaves out; which keys those are is
     decided here (lib/nurgeaendert.js). The same rule keeps a pre-filled
     default from being written back as a choice, which is what the port
     already had a brake of its own for and the window and the layers did
     not. */
  $effect(() => {
    const _ = JSON.stringify({ kontext, schichten, port, vorladen })
    if (!zahlenStehen || laeuft) return
    const uhr = setTimeout(() => {
      /* The same fallbacks `werteUebernehmen` fills the form from — the
         server owns its port, and the rest come from the one place that
         decides them (app/runnermodellwahl.py `vorgaben`). */
      const nachtrag = nurGeaendert(
        { kontext, schichten, port, vorladen },
        runnermodell,
        { ...(auskunft?.vorgaben ?? {}), port: auskunft?.port },
      )
      if (!Object.keys(nachtrag).length) return
      werteSetzen(nachtrag).catch(() => {})
    }, 600)
    return () => clearTimeout(uhr)
  })

  /* Picking a model pre-picks its speed module: first the choice the hand
     made last time for THIS model (a remembered "none" counts), then the
     association the catalogue wrote when it fetched them. */
  /* What the hand set stays set. Every control in this panel writes its
     choice down the moment it is made, and the panel reads it back when it
     opens — a value that only survived a start would be a value the reload
     two seconds later throws away.

     It goes to the server now, not into this browser (Stufe 11, see
     lib/runnermodell.svelte.js). The empty string keeps its meaning through
     the move: it is a chosen "none" and must not fold into "never chosen",
     or a pairing somebody switched off walks back in on the next reload. */
  function drafterGewaehlt() {
    modulSetzen(modell, { drafter }).catch(() => {})
  }
  function visionGewaehlt() {
    modulSetzen(modell, { vision }).catch(() => {})
  }

  function modellGewaehlt() {
    /* Remembered the moment it is picked, not only when a server starts:
       an empty choice never starts anything, and without this the reload a
       second later would find no model and pre-pick one again — the choice
       would not survive its own row. The empty string is a remembered
       "none", exactly as it is for the modules below. */
    werteSetzen({ modell }).catch(() => {})
    const modul = modulFuer(modell)
    drafter =
      modul.drafter !== null ? modul.drafter : (auskunft?.zuordnung?.[modell]?.mtp ?? '')
    vision =
      modul.vision !== null ? modul.vision : (auskunft?.zuordnung?.[modell]?.mmproj ?? '')
  }

  async function starten() {
    arbeitet = true
    try {
      /* Stored first, then started — awaited, so the process comes up on the
         numbers that stand in the fields right now rather than on whatever
         the debounce above had got round to writing. The request carries only
         the file: every start path reads the same stored choice, so no two of
         them can bring this server up differently (app/runnermodellwahl.py).

         Through the same filter the watcher uses, and for the same two
         reasons (lib/nurgeaendert.js). This button used to hand the store all
         three numbers by hand, which undid both of the watcher's rules the
         moment anybody pressed it: a second window's context was overwritten
         by this window's stale copy, and on a fresh install the pre-filled
         window and layers were frozen into the setting as a choice. Only the
         port had a brake of its own, which was the special case of the
         general rule.

         `modell` goes out either way: this button is the answer to "which
         file", and the file it started is the file this server is on.

         The levers have their own key and were already on the server; they
         are flushed here for the same reason, because their watcher waits
         600 ms too — and, like the numbers, only when they say something the
         setting does not already say. */
      const nachtrag = nurGeaendert(
        { kontext, schichten, port, vorladen },
        runnermodell,
        { ...(auskunft?.vorgaben ?? {}), port: auskunft?.port },
      )
      await werteSetzen({ modell, ...nachtrag })
      /* The two module rows are deliberately NOT written here. They write
         themselves the moment they are picked (`drafterGewaehlt`,
         `visionGewaehlt`), exactly as the slot's page has it, and a row
         nobody picked has to stay `null` — `null` is what lets the folder
         manifest and the name heuristic step in (app/modellrunner.py).

         Writing them here stored whatever the row happened to show, as a
         deliberate answer. That froze the manifest's pairing into a choice
         nobody made, and where the row showed "none" about a projector the
         name heuristic had attached (the heuristic is not in `zuordnung`, so
         the row cannot know about it), the first press of start DELETED that
         projector: `vision: ""` is "chosen: none", and the next start went
         out mute. Losing a user's module on a button that says "start" is
         the worst of the three. */
      if (feinGeladen && feinNachzutragen()) await feinSchreiben()
      auskunft = await api.runnerStarten({ modell })
      protokollAuf = true
      await modelleLaden(true)
    } catch (fehler) {
      melde(fehler.message, 'fehler')
    } finally {
      arbeitet = false
    }
  }

  async function anhalten() {
    arbeitet = true
    try {
      /* The answer is deliberately NOT taken into `auskunft`, and the slot's
         page has never taken it (Agentserver.svelte `anhalten`). It carries
         `laeuft: false`, so assigning it ended the run for this window one
         statement after the click — with the RUN's numbers still in the
         fields, because the hand-back lives in the poll and the poll was up
         to two seconds away. The 600 ms watcher fits inside that gap every
         single time: measured seven stops out of seven, the stored 131072/0
         was replaced by the run's 32768/99 at +750 ms.

         The poll is what learns that a run has ended, on this page as on the
         slot's, and it is the one place that hands the fields back in the
         same breath. Until it comes round the form goes on showing the run
         it was showing — for at most two seconds, and honestly. */
      await api.runnerStoppen()
      await modelleLaden()
    } catch (fehler) {
      melde(fehler.message, 'fehler')
    } finally {
      arbeitet = false
    }
  }

  function programmHolen() {
    api.serverProgrammHolen().then((s) => (programmStand = s)).catch((f) => melde(f.message, 'fehler'))
  }

  /* Whether a newer build of the server program exists — asked only when
     the button is pressed, never on opening and never inside the poll
     above: nothing looks for updates by itself. */
  let updateAnswer = $state(null)
  let checking = $state(false)

  // Only the newest check may answer: a fetch landing meanwhile clears the
  // answer, and an older one arriving after that must not bring it back.
  let checkRun = 0

  async function checkForUpdate() {
    const run = ++checkRun
    checking = true
    // The last answer goes while the new one is asked, so it cannot stand
    // beside the running check as if it were its result.
    updateAnswer = null
    try {
      const answer = await api.serverProgramUpdateCheck()
      if (run === checkRun) updateAnswer = answer
    } catch (fehler) {
      if (run === checkRun) melde(fehler.message, 'fehler')
    } finally {
      if (run === checkRun) checking = false
    }
  }

  /* Once a fetch actually FINISHES the last answer is cleared — it spoke of
     the build before, and the next press asks again. A fetch that failed
     says so: the version row still names the build that was there, and
     without a word it would look as if nothing had been tried. */
  let fetchingBefore = false
  $effect(() => {
    if (fetchingBefore && !programmLaedt) {
      updateAnswer = null
      checkRun += 1
      checking = false
      if (programmStand?.fehler) melde(t('bildserver.generator_fehler'), 'fehler')
    }
    fetchingBefore = programmLaedt
  })

  /* The server reads the release list again itself rather than trust the
     build this window showed a moment ago, so a stale offer never fetches
     what is already there. */
  function updateProgram() {
    api.serverProgramUpdate().then((s) => (programmStand = s)).catch((f) => melde(f.message, 'fehler'))
  }

  /* The way back from an update: the tested build takes the place of the
     newer one. Offered only while a fetched build other than the tested one
     runs (`auskunft.restorable`). */
  function restoreProgram() {
    api.serverProgramRestore().then((s) => (programmStand = s)).catch((f) => melde(f.message, 'fehler'))
  }
</script>

{#if erststart}
  <div class="erstetafel">
    <!-- The three steps to a first model: fetch the engine, pick a model,
         start it. The status card above says honestly where one stands. -->
    <div class="statuskarte">
      <Leuchtpunkt farbe="still" groesse={11} />
      <div class="skmitte">
        <div class="sktitel">{t('modell.reise_titel')}</div>
        <div class="skdetails">
          <span>{t(hatProgramm ? 'modell.reise_stand_programm_da' : 'modell.reise_stand_programm_fehlt')}</span>
        </div>
      </div>
    </div>

    <div class="reisekarten">
      <div class="reisekarte" class:fertig={hatProgramm} class:dran={!hatProgramm}>
        <div class="nr">{#if hatProgramm}✓{:else}1{/if}</div>
        <h3>{t('modell.server_holen')}</h3>
        <div class="rsatz">{t('modell.reise_server_satz')}</div>
        {#if hatProgramm}
          <span class="pille gruen">{t('modell.reise_da')}</span>
        {:else if programmLaedt}
          <div class="balkenzeile">
            <span class="balken"><i style="width:{Math.round(programmStand.anteil * 100)}%"></i></span>
            <span class="balkenzahl">{Math.round(programmStand.anteil * 100)} %{mbs ? ' · ' + mbs : ''}</span>
          </div>
        {:else}
          <button class="knopf wichtig" onclick={programmHolen}>{t('modell.server_holen')}</button>
        {/if}
      </div>

      <div class="reisekarte" class:dran={hatProgramm}>
        <div class="nr">2</div>
        <h3>{t('modell.reise_modell_titel')}</h3>
        <div class="rsatz">
          {vorschlag
            ? t('modell.reise_modell_satz').replace('{gb}', maschineGb)
            : t('modell.reise_modell_satz_neutral')}
        </div>
        <button class="knopf wichtig" disabled={!hatProgramm} onclick={() => katalogOeffnen('chat')}>
          {t('modell.katalog_oeffnen')}
        </button>
      </div>

      <div class="reisekarte">
        <div class="nr">3</div>
        <h3>{t('modell.reise_start')}</h3>
        <div class="rsatz">{t('modell.reise_start_satz')}</div>
        <span class="knopf still gesperrt">{t('modell.server_starten_kurz')}</span>
      </div>
    </div>
  </div>
{:else}
    <!-- The house's server shape (Servertafel.svelte), in two rows: models beside the modules, storage beside the
         advanced drawer, the log at the foot. -->
    <Servertafel
      titel={t('modell.server')}
      zeichen="server"
      unter={laufzeile || t('modell.nichts_laeuft')}
      standfarbe={laeuft ? 'gruen' : 'still'}
      standtext={laeuft ? t('status.aktiv') : t('status.inaktiv')}
      modelle={modellauswahl}
      bind:gewaehlt={modell}
      modellBeschriftung={t('modell.feld_modell')}
      modellGesperrt={laeuft}
      modellGeaendert={modellGewaehlt}
      leerText={t('modell.kein_modell_da')}
      katalogTat={() => katalogOeffnen('chat')}
      speicherort="models"
    >
      {#snippet inhalt(modellkarte)}
        <Serverreihe>
          {#snippet links()}{@render modellkarte()}{/snippet}
          {#snippet rechts()}
            <Serverregler
              kennung="rs"
              teil="module"
              gesperrt={laeuft}
              bind:drafter
              {drafterauswahl}
              {drafterGewaehlt}
              bind:vision
              {visionauswahl}
              {visionGewaehlt}
            >
              {#snippet kopfrechts()}
                <Startknopf text={tat.text} punkt={tat.punkt} gesperrt={tat.gesperrt} onTat={tat.onTat} />
              {/snippet}
            </Serverregler>
          {/snippet}
        </Serverreihe>
        <Serverreihe>
          {#snippet links()}
            <!-- Why the last start failed, while that is the server's state:
                 an architecture the server's build does not know. A line that
                 stands, not a notice that passes. -->
            {#if auskunft?.unknown_architecture}
              <p class="start-error">{t('modell.unknown_architecture', { arch: auskunft.unknown_architecture })}</p>
            {/if}
            <Serverregler
              kennung="rs"
              teil="speicher"
              gesperrt={laeuft}
              bind:kontext
              {kontextstufen}
              bind:schichten
              maxSchichten={MAX_SCHICHTEN}
              bind:faeden
              maxFaeden={MAX_FAEDEN}
              bind:moeSchichten
              {schaetzung}
              {maschineGb}
            />
          {/snippet}
          {#snippet rechts()}
            <Serverregler
              kennung="rs"
              teil="fein"
              gesperrt={laeuft}
              bind:vorladen
              bind:fein
              bind:parallel
              maxParallel={MAX_PARALLEL}
              bind:port
            />
          {/snippet}
        </Serverreihe>
        <!-- The program every server of this page starts, in one row: the
             build that starts on the left — a dash for a program that does
             not say which build it is — and on the right what can be done
             about it, in the order it is done: look for a newer build,
             fetch the one that was found, go back to the tested one. The
             answer "up to date" stands beside the button that asked.

             The check stands only where a fetched copy would be the program
             that starts; beside a program the settings name, or an
             installed one that comes first, the build is named and nothing
             is offered. -->
        {#if hatProgramm}
          <Serverabschnitt zeichen="server" titel="llama.cpp">
            <div class="zeile">
              <span class="name build">{t('bildserver.version_zeile', { bau: auskunft.version ?? '—' })}</span>
              {#if auskunft.updatable && updateAnswer?.aktuell}
                <UpToDateMark />
              {/if}
              {#if auskunft.updatable || auskunft.restorable}
                <span class="buttons">
                  {#if auskunft.updatable}
                    <button class="feldknopf" disabled={checking || programmLaedt} onclick={checkForUpdate}>
                      {t('bildserver.nach_updates_suchen')}
                    </button>
                    {#if updateAnswer?.verfuegbar}
                      <button class="feldknopf" disabled={programmLaedt} onclick={updateProgram}>
                        {t('bildserver.generator_aktualisieren')}
                      </button>
                    {/if}
                  {/if}
                  {#if auskunft.restorable}
                    <button class="feldknopf" disabled={programmLaedt} onclick={restoreProgram}>
                      {t('bildserver.restore_tested_build')}
                    </button>
                  {/if}
                </span>
              {/if}
            </div>
          </Serverabschnitt>
        {/if}
      {/snippet}
      {#snippet unten()}
        <div class="log">
          <Serverlogkopf offen={protokollAuf}
                         onumschalten={() => (protokollAuf = !protokollAuf)}
                         onauskoppeln={() => oeffneProtokoll(t('modell.protokoll_titel'))} />
          {#if protokollAuf}
            <pre class="protokoll" use:rollfade bind:this={protokollKasten}>{protokoll.join('\n') || '—'}</pre>
          {/if}
        </div>
      {/snippet}
    </Servertafel>
{/if}

<style>
  /* Only the first-run journey still brings its own frame; the panel proper
     stands in the shared one. */
  .erstetafel {
    display: flex;
    flex-direction: column;
  }

  /* Where one stands on the way to a first model. */
  .statuskarte {
    display: flex;
    align-items: center;
    gap: 14px;
    border: 1px solid var(--glass-card-line);
    border-radius: 9px;
    background: var(--glass-card);
    padding: 14px 16px;
    margin-bottom: 16px;
  }
  .skmitte {
    min-width: 0;
    flex: 1;
  }
  .sktitel {
    font: 600 14px var(--schrift-fest);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .skdetails {
    font-size: 12px;
    color: var(--text-leise);
    margin-top: 3px;
    display: flex;
    gap: 14px;
    flex-wrap: wrap;
    align-items: center;
  }

  .start-error {
    margin: 0;
    color: var(--rot);
    font-size: 13px;
  }

  .protokoll {
    margin: 0;
    padding: 10px 12px;
    background: var(--code-bg);
    border: 1px solid var(--linie);
    border-radius: 9px;
    font: 400 11px/1.55 var(--schrift-fest);
    color: var(--text-leise);
    max-height: 150px;
    overflow: auto;
    white-space: pre-wrap;
  }

  /* The first-run journey: three cards side by side. */
  .reisekarten {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
    margin-top: 2px;
  }
  @media (max-width: 720px) {
    .reisekarten {
      grid-template-columns: 1fr;
    }
  }
  .reisekarte {
    border: 1px solid var(--glass-card-line);
    border-radius: 9px;
    padding: 14px;
    background: var(--glass-card);
    display: flex;
    flex-direction: column;
    align-items: flex-start;
  }
  .reisekarte .nr {
    width: 26px;
    height: 26px;
    border-radius: 99px;
    border: 1.5px solid var(--linie-stark);
    display: flex;
    align-items: center;
    justify-content: center;
    font: 600 12px var(--schrift-fest);
    color: var(--text-still);
    margin-bottom: 10px;
  }
  .reisekarte.fertig .nr {
    border-color: var(--gruen);
    color: var(--gruen);
  }
  .reisekarte.dran .nr {
    border-color: var(--blau);
    color: var(--blau);
  }
  .reisekarte h3 {
    font-size: 13.5px;
    font-weight: 600;
    margin: 0 0 4px;
  }
  .rsatz {
    font-size: 12px;
    color: var(--text-leise);
    line-height: 1.5;
    min-height: 54px;
    margin-bottom: 10px;
  }
  .balkenzeile {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
  }
  .balken {
    flex: 1;
    height: 5px;
    border-radius: 9px;
    background: var(--linie);
    overflow: hidden;
  }
  .balken i {
    display: block;
    height: 100%;
    background: var(--blau);
    transition: width 0.3s;
  }
  .balkenzahl {
    font: 400 11px var(--schrift-fest);
    color: var(--text-still);
    white-space: nowrap;
  }

  .pille {
    display: inline-flex;
    align-items: center;
    border: 1px solid var(--linie-stark);
    border-radius: 9px;
    padding: 3px 10px;
    font: 600 11px var(--schrift);
    color: var(--text-still);
  }
  .pille.gruen {
    color: var(--gruen);
    border-color: color-mix(in srgb, var(--gruen) 45%, transparent);
  }
  .knopf {
    border: 1px solid var(--linie-stark);
    background: none;
    color: var(--text);
    font: 600 12.5px var(--schrift);
    padding: 6px 13px;
    border-radius: 9px;
    cursor: pointer;
    transition: background 0.12s, opacity 0.12s, transform 0.08s;
  }
  .knopf:hover:not(:disabled) {
    background: var(--linie);
  }
  .knopf:active:not(:disabled) {
    transform: scale(0.975);
  }
  /* The main button is button glass with its fine edge, like the start
     button; only Send stays filled. */
  .knopf.wichtig {
    background: var(--glass-button);
    color: var(--text);
    border-color: var(--glass-button-edge);
    font-size: 13px;
    padding: 7px 15px;
  }
  .knopf.wichtig:hover:not(:disabled) {
    background: color-mix(in srgb, var(--text) 6%, var(--glass-button));
  }
  .knopf.still {
    color: var(--text-still);
    border-color: var(--linie);
  }
  .knopf:disabled {
    opacity: 0.5;
    cursor: default;
  }
  .knopf.gesperrt {
    opacity: 0.5;
    cursor: default;
  }

  /* The build number in digits of one width: the row keeps its place when
     an update changes the number. */
  .build {
    font-variant-numeric: tabular-nums;
  }
</style>
