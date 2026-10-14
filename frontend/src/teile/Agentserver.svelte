<script>
  import { rollfade } from '../lib/rollfade.js'
  /* The agent server — the second model this program loads itself.

     It used to be a row in the model server's form, called the
     "Extended-Workflow module", sitting between the speed module and the
     vision module. That was honest about how it started and wrong about what
     it had become: it is not a module that plugs into the chat model, it is a
     server of its own, with its own process, its own port, its own log and
     its own model. Three servers had a page each and this one had a
     dropdown, so everything a server page offers — the window, the layers,
     the threads, the projector — it simply did not have. Its window was
     whatever the runner defaulted to, and nobody could change it.

     So it has a page, built from the same parts the model server's is
     (Serverregler.svelte, Servertafel.svelte). Deliberately not a copy: two
     copies drift apart the first time somebody adds a lever to one of them.

     Where the values live is the same arrangement on both pages: each
     server's start choice sits in a setting of its own
     (app/agentenmodellwahl.py here, app/runnermodellwahl.py next door). This
     one has to be that way — it comes up by itself at every program launch,
     when there is no browser at all — and the model server does the same for
     the same reason. See lib/agentenserver.svelte.js.

     The model row keeps the three kinds of answer the one field has left —
     the main model, a file of its own, a cloud endpoint — because the field
     is what everything unattended runs on, not just the slot. Only a file of
     its own starts a process, which is why the form below it stands quiet
     for the other two. */
  import { api } from '../lib/api.js'
  import { t } from '../lib/texte.svelte.js'
  import { katalogOeffnen, melde, modelleLaden, zustand } from '../lib/zustand.svelte.js'
  import { serverAnteil } from '../lib/speicherschaetzung.js'
  import { nurGeaendert } from '../lib/nurgeaendert.js'
  import {
    HAUPTMODELL,
    agentenmodell,
    alsWahl,
    slotStarten,
    slotStoppen,
    standLaden,
    waehlen as agentenmodellWaehlen,
    werteSetzen,
  } from '../lib/agentenserver.svelte.js'
  import Servertafel from './Servertafel.svelte'
  import Serverregler from './Serverregler.svelte'
  import Startknopf from './Startknopf.svelte'
  import Serverreihe from './Serverreihe.svelte'
  import Startfehler from './Startfehler.svelte'
  import Serverlogkopf from './Serverlogkopf.svelte'
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

  $effect(() => {
    void protokoll
    if (protokollKasten) protokollKasten.scrollTop = protokollKasten.scrollHeight
  })

  /* The form's own copies of the stored values. Held here rather than bound
     straight into the store because a slider drags through a hundred
     intermediate numbers on its way to one, and every one of them would
     otherwise be a write to the database. What the hand comes to rest on is
     written; see `sichern` below.

     Held back until the stored numbers are in — without it the watcher would
     write these placeholders over them on the very first pass. */
  let zahlenStehen = $state(false)
  /* The picker's own copy of the field. Mirrored from the store rather than
     read straight out of it, because the row below writes into what it is
     given — and what the store holds is the answer, not a scratch pad. */
  /* What the row stands on while the field names nothing of its own: the
     main model. Not written to the field by looking at it — the run takes
     the main model in that case anyway, so the row says what happens
     rather than deciding it. */
  const HAUPTMODELL_WAHL = `kennung:${HAUPTMODELL}`

  let wahl = $state(HAUPTMODELL_WAHL)
  let kontext = $state(0)
  let schichten = $state(99)
  let port = $state(0)
  let drafter = $state('')
  let vision = $state('')
  let vorladen = $state(true)
  let faeden = $state(0)
  /* Experts on the CPU as one number: empty means
     off, a count means that many layers. */
  let moeSchichten = $state(null)
  let parallel = $state(null)
  let fein = $state({ kv_cache: 'f16', moe_auf_cpu: false, festnageln: false })

  const feindaten = $derived({
    ...fein,
    /* The engine flag follows the number — above zero means on. */
    moe_auf_cpu: Boolean(moeSchichten && moeSchichten > 0),
    faeden: faeden || null,
    moe_schichten: moeSchichten || null,
    parallel: parallel ?? null,
  })

  const laeuft = $derived(Boolean(auskunft?.laeuft))
  /* Only a file of this program's own starts a process. The main model and a
     cloud endpoint are answers to "which model", not to "which server", and
     there is nothing to configure for them here. */
  const istSlot = $derived(agentenmodell.sorte === 'slot' && Boolean(agentenmodell.wert))
  const reglerGesperrt = $derived(laeuft || !istSlot)

  const maschineGb = $derived(auskunft?.speicher_gb ?? null)
  const MAX_FAEDEN = $derived(auskunft?.kerne ?? 8)
  /* The same ladder the model server offers, from the same reasoning: below
     4096 there is no conversation worth having, and above that the engine
     only understands these numbers. */
  const kontextstufen = [4096, 8192, 16384, 32768, 65536, 131072]
  const MAX_SCHICHTEN = 99
  const MAX_PARALLEL = 64

  const kurzK = (n) => (n ? Math.round(n / 1024) + 'k' : '')

  /* The same parameter-count rule the model server uses: an mtp module is
     trained for one exact model, so a 12B module must never draft a 31B
     file even when the names look alike. */
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

  const drafterKandidaten = $derived.by(() => {
    const haupt = (auskunft?.modelle ?? []).find((m) => m.name === agentenmodell.wert)
    if (!haupt) return []
    const hp = parameterzahl(haupt.name)
    const module = (auskunft?.mtp ?? []).filter((m) => {
      const basis = m.name.replace(/^mtp[-._]/i, '')
      if (gemeinsam(basis, haupt.name) < 5) return false
      const mp = parameterzahl(basis)
      return hp && mp ? mp === hp : true
    })
    const geschwister = (auskunft?.modelle ?? []).filter(
      (m) =>
        m.name !== haupt.name &&
        gemeinsam(m.name, haupt.name) >= 5 &&
        m.groesse_gb <= haupt.groesse_gb * 0.6,
    )
    return [...module, ...geschwister]
  })

  /* A remembered or declared module the candidate rule would not propose is
     still listed — as itself, ahead of the suggestions. The rule narrows what
     this row SUGGESTS; what a start really drafts against is decided in the
     process (app/modellrunner.py `starten`) and knows nothing of it. Blanking
     it out of the field said "none" about a command line carrying
     --model-draft, and made the choice unreachable on top, because picking
     "none" on a row that already reads "none" writes nothing
     (Auswahlfeld.svelte `waehlen`). Same wording on the model server's page,
     for the same reason. */
  const drafterauswahl = $derived([
    { wert: '', text: t('modell.drafter_keiner') },
    ...(drafter && !drafterKandidaten.some((m) => m.name === drafter)
      ? [{ wert: drafter, text: drafter }]
      : []),
    ...drafterKandidaten.map((m) => ({ wert: m.name, text: `${m.name} · ${m.groesse_gb} GB` })),
  ])

  /* Every projector in the vision folder, "without" first — not narrowed by
     name, for the same reason the model server does not narrow it: the whole
     point of the row is the companion the name heuristic cannot pair. */
  const visionauswahl = $derived([
    { wert: '', text: t('modell.vision_keiner') },
    ...(auskunft?.mmproj ?? []).map((name) => ({ wert: name, text: name })),
  ])

  /* The one field's list: one list, three kinds of answer, no second switch.
     The order is the order of the decision — the main model, a small one of
     its own, somebody else's.

     There is no "none" entry any more. It carried the empty value, which
     `waehlen` turned into the field switched off. Off never meant "no
     model": it meant the run took the first endpoint that answered, and
     that is how a continuation once landed on an embedding model.
     So the entry named a state the user could not recognise
     from its label, and the state it named is gone as well: a run without a
     choice takes the MAIN model (app/api/v1/auftraege.py), and when that
     server is not up, the next reachable LOCAL one.
     Nothing chosen IS the first entry here — the main model — and the row
     shows exactly that, with nothing left disagreeing underneath: the
     switch is out of the store and out of the settings, so a
     due schedule preloads the model its own run would land on.

     The value carries its kind (`slot:` / `kennung:`), so the field stays a
     single value while the groups stay distinguishable — a bare file name
     and a bare model id would otherwise be the same string. */
  const modellauswahl = $derived([
    { wert: HAUPTMODELL_WAHL, text: t('modell.agentenmodell_hauptmodell') },
    ...(auskunft?.modelle ?? []).map((m) => ({
      wert: `slot:${m.name}`,
      text: `${m.name} · ${m.groesse_gb} GB`,
    })),
    /* Everything the discovery knows. The slot itself is left out: while it
       runs it IS one of these entries, and offering it twice would let
       somebody pick the running slot as if it were a foreign endpoint. The
       main model is left out the same way, by its endpoint and not by the
       whole id: a runner answering with several models is handed out as
       `runner:<modell>` (app/discovery.py `modellkennung.bauen`), and each
       of those is the same server this row already names "Hauptmodell".
       With the bare id it is also the same VALUE, and the list is keyed by
       the value — Svelte throws `each_key_duplicate` and the list never
       opens at all. With `runner` in the discovery, the row said
       "Hauptmodell", reported itself open, and rendered an empty anchor
       where the entries belong. */
    ...zustand.modelle
      .filter((m) => !String(m.id).startsWith('agentenmodell'))
      .filter((m) => `kennung:${String(m.id).split(':')[0]}` !== HAUPTMODELL_WAHL)
      .map((m) => ({ wert: `kennung:${m.id}`, text: m.id })),
  ])

  const schaetzung = $derived(
    istSlot
      ? serverAnteil(auskunft?.modelle, auskunft?.mtp, {
          modell: agentenmodell.wert, kontext, drafter,
        })
      : null,
  )
  /* This server's own entry in the head's figure — its own, not the model
     server's, because both processes are up at once and the head shows what
     they cost TOGETHER. Live while this page is open; handed back when it
     goes away, and the head then works it out from the stored field.

     While it RUNS, what the process actually holds — see the same note in
     Modellserver.svelte. A running server counting as nothing is exactly how
     the pair that does not fit looked affordable. */
  $effect(() => {
    zustand.serverPlan.agent = laeuft
      ? (auskunft?.belegt_gb ? { gesamt: auskunft.belegt_gb, gemessen: true } : null)
      : schaetzung
    return () => (zustand.serverPlan.agent = null)
  })

  /* What the panel is doing, as the head card's one line — the same facts
     the model server's card carries, about the other process. */
  const laufzeile = $derived.by(() => {
    if (!laeuft || !auskunft) return ''
    const teile = [
      t('modell.laeuft_port', { port: auskunft.port }),
      t('modell.kontext_kurz', { n: kurzK(auskunft.kontext) }),
    ]
    if (auskunft.drafter) teile.push(`${t('modell.mtp_label')}: ${auskunft.drafter}`)
    if (auskunft.belegt_gb) teile.push(t('modell.im_speicher', { gb: auskunft.belegt_gb }))
    return teile.join(' · ')
  })

  /* The window's one deed, handed to the modules group's head line, the same
     way the model server's page does it. It travels with the slot's own
     sheet: without a slot there is no group to put it in, and nothing this
     program would start. */
  const tat = $derived({
    text: laeuft ? t('modell.server_anhalten') : t('modell.server_starten'),
    punkt: laeuft ? 'gruen' : 'still',
    gesperrt: arbeitet || agentenmodell.laedt || (!laeuft && !istSlot),
    onTat: laeuft ? anhalten : starten,
  })

  /* The two module rows: the remembered choice first — including a
     remembered "none" — and only then the pairing the folder manifest
     declared for this file. The model server's page has read them in exactly
     this order all along (Modellserver.svelte `modulUebernehmen`), and the
     order is the whole point of the row.

     Left out, the row said "none" about a start that attached the manifest's
     companion anyway — and worse, it made the choice unreachable: picking
     "none" on a row that already shows "none" changes nothing, so nothing
     was written, so the pairing came back at the next start. The page has to
     show what would actually run before "no thanks" can be an answer to it. */
  function moduleUebernehmen() {
    const v = auskunft?.vorgaben ?? {}
    const z = auskunft?.zuordnung?.[agentenmodell.wert]
    drafter = agentenmodell.drafter ?? z?.mtp ?? v.drafter ?? ''
    vision = agentenmodell.vision ?? z?.mmproj ?? v.vision ?? ''
  }

  /* The stored values, into the form. Taken once — this runs on a two-second
     poll and would otherwise fight the hand in the field. */
  function werteUebernehmen() {
    /* What was stored, and where nothing was stored the server's own
       fallback — sent in the answer rather than written down here, so the
       page cannot end up disagreeing with the process about what "unset"
       means. A field saved before these values existed carries none of them,
       which is the normal case on an install that predates this page. */
    const v = auskunft?.vorgaben ?? {}
    kontext = agentenmodell.kontext ?? v.kontext
    schichten = agentenmodell.schichten ?? v.schichten
    /* Null means "the slot's own port", and only the server knows what that
       is — it comes back in `port` while nothing runs. */
    port = agentenmodell.port ?? auskunft?.port ?? 0
    vorladen = agentenmodell.vorladen ?? v.vorladen
    moduleUebernehmen()
    const f = agentenmodell.fein ?? v.fein ?? {}
    fein = {
      /* The step an older version offered maps to the surviving saving step,
         exactly as the model server maps it — whoever stored q4_0 was saving
         memory on purpose. */
      kv_cache: f.kv_cache === 'q4_0' ? 'q8_0' : (f.kv_cache ?? 'f16'),
      moe_auf_cpu: Boolean(f.moe_auf_cpu),
      festnageln: Boolean(f.festnageln),
    }
    faeden = f.faeden || 0
    /* The stored kinds of "all experts on the CPU": the older switch
       without a count, and the backend's own zero (`--cpu-moe`); the
       slider says the same at its ceiling — same line, same reasoning as
       the model server's page. */
    moeSchichten = f.moe_schichten === 0
      ? 999
      : (f.moe_schichten ?? (f.moe_auf_cpu ? 999 : null))
    parallel = f.parallel ?? null
    zahlenStehen = true
  }

  /* Whether the last poll saw the slot running — so the end of a run can be
     told from the middle of one. The model server's page has kept this all
     along; see `laden`. */
  let liefVorher = false

  /* What this poll reported last, so a failure that lasts is reported once
     rather than once every two seconds. Same reason, same shape, on the
     model server's page. */
  let letzterFehler = null

  async function laden() {
    try {
      auskunft = await api.agentenmodellAuskunft()
      if (!agentenmodell.geladen) await standLaden()
      if (!zahlenStehen && agentenmodell.geladen) werteUebernehmen()
      if (auskunft.laeuft) {
        /* What the running process was actually started with beats what was
           once chosen — the same rule the model server follows, and the
           reason its form does not claim a window the server is not in. */
        kontext = auskunft.kontext
        schichten = auskunft.schichten
        port = auskunft.port
        drafter = auskunft.drafter || ''
        /* The projector is the one field the run does NOT report back
           resolved: `Lauf.vision` is the parameter that was handed in
           (app/modellrunner.py), and the manifest and the name heuristic are
           read later, in `befehl`. So a run started on a stored `null` with a
           declared projector attached says `vision: null` here while --mmproj
           stands on its command line. Falling that back to "" put "none" in
           the row about a projector that was running — and, because a row
           already reading "none" cannot be set to "none", left the user with
           no way to switch it off. What the row held stays.

           `??` and not `||`, and that is the whole of it: `""` is a running
           answer here, not a missing one. `slot_startwerte` hands the empty
           string straight through and `befehl` obeys it by leaving --mmproj
           off, so a run reporting `""` is a run that IS mute. `||` threw that
           report away and left this window's own copy of the row standing —
           so a second window went on naming a projector while the command
           line ran without one. */
        vision = auskunft.vision ?? vision
      } else if (liefVorher) {
        /* The run is over, so the values above are a report and not an answer
           any more — the stored choice takes the fields back, and with it the
           two module rows (`werteUebernehmen` reads them through
           `moduleUebernehmen`). Without this the row kept whatever the run
           had put in it: a slot model starts the moment it is picked, so the
           very first thing this page ever shows is a run's report, and after
           the stop it stood there for good. The model server's page has done
           this since the run's numbers were found in its fields.

           Read back from the server first, because "the stored choice" is not
           the same thing as this window's copy of it. `standLaden` runs once
           when a page opens; everything another window stored since then is
           news to this one. Taking the fields back from the stale copy is how
           a projector somebody else switched off came back into this row the
           moment the run ended — the run itself had reported the truth two
           seconds earlier.

           And that read is where the hole this closes was: `await` hands
           control back. Svelte flushes, the watcher below sees `laeuft`
           false, `zahlenStehen` true and the RUN's values still in the
           fields, and starts its 600 ms clock. A read that takes longer than
           that — a service busy stopping a process is exactly when it does —
           and the run's values are written as the choice, over whatever
           somebody else had stored. Measured on this page too: 131072/0
           replaced by the slot's 16384/99 on a stop.

           So the fields are handed back BEFORE the read as well, out of the
           copy this window already holds — nothing is locked for the wait,
           the wait is made harmless. The form then says what the store says,
           and the watcher only writes what the form says and the store does
           not (lib/nurgeaendert.js), so it finds nothing to say. A start in
           that same stretch sends only the file, and the service reads
           window, layers, port and levers out of the setting itself
           (app/agentenmodellwahl.py `slot_startwerte`). A failed read leaves
           the copy standing, writes nothing, locks nothing, and `liefVorher`
           keeps standing so the next poll tries again.

           The price is that the fields step twice on a stop — run value, this
           window's copy, then whatever the read brings. Visible and right
           beats invisible and wrong. What it buys is that there is no state
           left to be stuck in: the lock this replaced came down in this
           branch alone, so one refused read left it up through the whole of
           the NEXT run, with the stop button dead and nothing on the page
           saying why.

           Strict, for the same reason the model server's is: a read that did
           not reach the setting hands back the copy this window opened with,
           and that copy is what the hand-back exists to stop using. */
        werteUebernehmen()
        await standLaden(true)
        werteUebernehmen()
      }
      liefVorher = Boolean(auskunft.laeuft)
      agentenmodell.laeuft = Boolean(auskunft.laeuft)
      /* Not while a pick is in flight: the store is written before the
         process is asked, and re-reading it mid-flight would put the old
         answer back into the row under the hand that just moved it. */
      if (!arbeitet) wahl = alsWahl() || HAUPTMODELL_WAHL
      if (protokollAuf || protokollOffen() || auskunft.laeuft) {
        protokoll = await api.agentenmodellProtokoll()
      }
      letzterFehler = null
    } catch (fehler) {
      /* Once per streak, not once per tick — the same clock, the same noise
         and the same answer as on the model server's page. Measured there:
         15 red tiles and 15 sounds in 30 seconds of a refused settings read.
         The error stays visible; only its repetition stops. */
      if (fehler.message !== letzterFehler) melde(fehler.message, 'fehler')
      letzterFehler = fehler.message
    }
  }

  $effect(() => {
    laden()
    const takt = setInterval(laden, 2000)
    return () => clearInterval(takt)
  })

  /* Written when the levers come to rest, not on every drag of a slider —
     and never before they were read, or the first pass would store the
     placeholders over what was there.

     And only the levers the hand actually moved. Sending all six on every
     change sent five values this window had not touched — its copies, as old
     as the moment the page opened — so a second window's context was undone
     by the next drag of the layers slider over here. The PATCH route can
     only keep the keys a request leaves out; which keys those are is decided
     here (lib/nurgeaendert.js). The same rule keeps a pre-filled default
     from being written back as a choice, which is what the port already had
     a brake of its own for and the window, the layers and the engine levers
     did not.

     The two module rows are not in here at all any more. They write when
     they are picked (`drafterGewaehlt`, `visionGewaehlt`), exactly as the
     model server's do — a row nobody touched must stay unanswered, or the
     empty entry the form shows would be stored as a deliberate "none". */
  $effect(() => {
    const _ = JSON.stringify({ kontext, schichten, port, feindaten, vorladen })
    if (!zahlenStehen || laeuft) return
    const uhr = setTimeout(() => {
      /* The same fallbacks `werteUebernehmen` fills the form from — the slot
         owns its port, and the rest come from the one place that decides
         them (app/agentenmodellwahl.py `VORGABE`). */
      const nachtrag = nurGeaendert(
        { kontext, schichten, port, fein: feindaten, vorladen },
        agentenmodell,
        { ...(auskunft?.vorgaben ?? {}), port: auskunft?.port },
      )
      if (!Object.keys(nachtrag).length) return
      werteSetzen(nachtrag).catch(() => {})
    }, 600)
    return () => clearTimeout(uhr)
  })

  /* The speed module and the projector, stored the moment they are picked.

     Their own writers rather than two more fields in the watcher above, and
     the empty string travels as itself: `''` is "chosen: none" and `null` is
     "nobody said". The slot used to send `drafter || null` for both, which
     folded the first into the second — and `None` is what lets the folder
     manifest and the name heuristic step in (app/modellrunner.py). A
     projector switched off by hand therefore came back on the command line,
     while the row on this page went on saying "none". The main model server
     kept the two apart from the start (Modellserver.svelte `modulSetzen`);
     this is that same rule on the second page. */
  function drafterGewaehlt() {
    werteSetzen({ drafter }).catch(() => {})
  }
  function visionGewaehlt() {
    werteSetzen({ vision }).catch(() => {})
  }

  async function modellGewaehlt(wahl) {
    arbeitet = true
    try {
      /* A remembered module pair belongs to the file it was picked for, and
         this key holds exactly ONE pair — not a table per file, the way the
         model server's does (lib/runnermodell.svelte.js `module`). So a draft
         or a projector chosen by hand for one file went on standing in the
         row for the next one, and not only in the row: `slot_startwerte`
         reads that same single pair, so the next start really did put the
         first file's mtp module on the command line of the second. A 12B
         draft against a 31B model is the one pairing the candidate rule
         exists to prevent.

         Handing the pair back to `null` when the choice changes is the true
         statement about a file nobody has said anything about — and `null`
         is what lets the folder manifest declare the pairing for the file
         that was actually picked (app/modellrunner.py `starten`).

         Before the pick, not after: picking a slot model starts it at once
         (lib/agentenserver.svelte.js `waehlen`), and the process reads the stored
         choice on its way up.

         What this cannot do is REMEMBER the pair per file — that needs the
         key to become a table, on both sides. Until then switching away and
         back costs the pair, which is a forgotten answer rather than a wrong
         one. */
      if (wahl !== alsWahl() && (agentenmodell.drafter !== null || agentenmodell.vision !== null)) {
        await werteSetzen({ drafter: null, vision: null })
      }
      await agentenmodellWaehlen(wahl)
      /* Another file, so the rows are read again: what the manifest declares
         is declared for a file, and the file has just changed. */
      moduleUebernehmen()
      await modelleLaden(true)
    } catch (fehler) {
      melde(fehler.message ?? String(fehler), 'fehler')
    } finally {
      arbeitet = false
    }
  }

  async function starten() {
    arbeitet = true
    try {
      /* Stored first, then started — awaited, so the process comes up on the
         number that is in the field right now rather than on whatever the
         debounce above had got round to writing. Both the button and the
         autostart read that stored value; there is no second path.

         The same filter the watcher uses, for the same two reasons: a lever
         this window never moved is this window's stale copy, and a value the
         form only pre-filled is not a choice to freeze. The two module rows
         are left out because they write themselves when they are picked —
         and a row nobody picked has to stay `null`, or the manifest pairing
         this slot starts with would be switched off by the mere act of
         pressing start. */
      const nachtrag = nurGeaendert(
        { kontext, schichten, port, fein: feindaten, vorladen },
        agentenmodell,
        { ...(auskunft?.vorgaben ?? {}), port: auskunft?.port },
      )
      if (Object.keys(nachtrag).length) await werteSetzen(nachtrag)
      await slotStarten()
      protokollAuf = true
      await modelleLaden(true)
    } catch (fehler) {
      melde(fehler.message ?? String(fehler), 'fehler')
    } finally {
      arbeitet = false
    }
  }

  async function anhalten() {
    arbeitet = true
    try {
      await slotStoppen()
      await modelleLaden()
    } catch (fehler) {
      melde(fehler.message ?? String(fehler), 'fehler')
    } finally {
      arbeitet = false
    }
  }
</script>

<!-- The house's server shape (Servertafel.svelte), in the same two rows as
     the model server: models beside the modules, storage beside the
     advanced drawer, the log at the foot. -->
<Servertafel
  titel={t('agentserver.titel')}
  zeichen="agent"
  unter={laufzeile}
  standfarbe={laeuft ? 'gruen' : 'still'}
  standtext={laeuft ? t('status.aktiv') : t('status.inaktiv')}
  modelle={modellauswahl}
  bind:gewaehlt={wahl}
  modellBeschriftung={t('modell.feld_agentenmodell')}
  modellGesperrt={laeuft}
  modellGeaendert={modellGewaehlt}
  leerText={t('modell.kein_modell_da')}
  katalogTat={() => katalogOeffnen('chat')}
  speicherort="models"
>
  {#snippet inhalt(modellkarte)}
    <!-- The same levers the model server's page carries, from the same
         component, always in view. Locked while the field points at something
         this program does not start — the main model or somebody else's
         server — because there they would set nothing, and locked while the
         slot runs, as on the model server's page. -->
    <Serverreihe>
      {#snippet links()}{@render modellkarte()}{/snippet}
      {#snippet rechts()}
        <Serverregler
          kennung="as"
          teil="module"
          gesperrt={reglerGesperrt}
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
        <Startfehler arch={auskunft?.unknown_architecture} />
        <Serverregler
          kennung="as"
          teil="speicher"
          gesperrt={reglerGesperrt}
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
          kennung="as"
          teil="fein"
          gesperrt={reglerGesperrt}
          bind:vorladen
          bind:fein
          bind:parallel
          maxParallel={MAX_PARALLEL}
          bind:port
        />
      {/snippet}
    </Serverreihe>
  {/snippet}
  {#snippet unten()}
    <div class="log">
      <Serverlogkopf offen={protokollAuf}
                     onumschalten={() => (protokollAuf = !protokollAuf)}
                     onauskoppeln={() => oeffneProtokoll(t('agentserver.protokoll_titel'))} />
      {#if protokollAuf}
        <pre class="protokoll" use:rollfade bind:this={protokollKasten}>{protokoll.join('\n') || '—'}</pre>
      {/if}
    </div>
  {/snippet}
</Servertafel>

<style>
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
</style>
