<script>
  /* The speech server, switched and set from here.

     Two columns: on the left the two models it
     stands on — the one that hears (with its projector, which is not a
     choice but the other half of the model) and the one that speaks, each
     with its own memory numbers; on the right what the window is for —
     dictation, clean-up and conversation, each with its instruction. The
     voice's five generation values stand under both columns, full width.

     The clean-up server is NOT started from here any more: it is its own
     server with its own window (Bereinigungsserver.svelte), and one button
     starting two processes was exactly how a failure of one read as a
     failure of the other.

     All the dictation answers are settings on the service
     (app/diktatsprachewahl.py) — the service is what uses them, on every
     single request, and a copy kept in this page would be read by nobody. */
  import { api } from '../lib/api.js'
  import { pollWithoutOverlap } from '../lib/pollWithoutOverlap.js'
  import { t, texte } from '../lib/texte.svelte.js'
  import { fractionDigits, formatNumber } from '../lib/numberDisplay.js'
  import { katalogOeffnen, melde, frage } from '../lib/zustand.svelte.js'
  import { diktat, schreibenAbwarten, standLaden, werteSetzen } from '../lib/diktat.svelte.js'
  import { createDelayedWriter } from '../lib/delayedWriter.js'
  import { aufnahme, starten as aufnahmeStarten, stoppen as aufnahmeStoppen, fehlerschluessel } from '../lib/aufnahme.svelte.js'
  import { SPRACHEN } from '../lib/diktatsprachen.js'
  import { STIMMSPRACHEN } from '../lib/stimmsprachen.js'
  import Servertafel from './Servertafel.svelte'
  import { serverHead } from '../lib/serverHead.svelte.js'
  import Serverregler from './Serverregler.svelte'
  import Startfehler from './Startfehler.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import Serverabschnitt from './Serverabschnitt.svelte'
  import Serverreihe from './Serverreihe.svelte'
  import Serverlogkopf from './Serverlogkopf.svelte'
  import LlamaCppSection from './LlamaCppSection.svelte'
  import Auswahlfeld from './Auswahlfeld.svelte'
  import Schalter from './Schalter.svelte'
  import Schieberegler from './Schieberegler.svelte'
  import Zahlenfeld from './Zahlenfeld.svelte'
  import WachsendesFeld from './WachsendesFeld.svelte'
  import Speicherortzeile from './Speicherortzeile.svelte'
  import {
    protokollOffen,
    oeffneProtokoll,
    setzeProtokollZeilen,
  } from '../lib/protokollfenster.svelte.js'
  import { entryMark, entrySize } from '../lib/modelEntry.js'
  import { serverAnteil } from '../lib/speicherschaetzung.js'

  const kontextstufen = [2048, 4096, 8192, 16384, 32768]
  const MAX_SCHICHTEN = 99

  /* The five generation values of the voice, as stepped lists — the same
     shape the context above has, and the same reason: a value the service
     would clamp (app/parameter.py) is not a value worth offering. The
     temperature walks 0 to 1 in steps of 0.05, the range the voice's
     sliders offer. */
  const STUFEN = {
    temperatur: Array.from({ length: 21 }, (_, i) => Math.round(i * 5) / 100),
    top_k: Array.from({ length: 201 }, (_, i) => i),
    top_p: Array.from({ length: 101 }, (_, i) => i / 100),
    min_p: Array.from({ length: 101 }, (_, i) => i / 100),
    strafe: Array.from({ length: 101 }, (_, i) => (100 + i) / 100),
  }

  /* The five rows, once: which knob of the local copy belongs to which key
     of the setting, and how the number reads. */
  const PARAMETER = [
    { knopf: 'temperatur', schluessel: 'stimmtemperatur',
      stufen: STUFEN.temperatur, min: 0, max: 1, schritt: 0.05, ganzzahlig: false },
    { knopf: 'top_k', schluessel: 'stimmtop_k',
      stufen: STUFEN.top_k, min: 0, max: 200, schritt: 1, ganzzahlig: true },
    { knopf: 'top_p', schluessel: 'stimmtop_p',
      stufen: STUFEN.top_p, min: 0, max: 1, schritt: 0.01, ganzzahlig: false },
    { knopf: 'min_p', schluessel: 'stimmmin_p',
      stufen: STUFEN.min_p, min: 0, max: 1, schritt: 0.01, ganzzahlig: false },
    { knopf: 'strafe', schluessel: 'stimmstrafe',
      stufen: STUFEN.strafe, min: 1, max: 2, schritt: 0.01, ganzzahlig: false },
  ]

  /* The five labels, each fetched by its full key — the row loop above
     reads them by knob name. */
  const parameterlabels = $derived({
    temperatur: t('sprachserver.feld_temperatur'),
    top_k: t('sprachserver.feld_top_k'),
    top_p: t('sprachserver.feld_top_p'),
    min_p: t('sprachserver.feld_min_p'),
    strafe: t('sprachserver.feld_strafe'),
  })

  /* What this page hands up to the page head (ModelleLokal.svelte), which draws
     it: the start button, the short line beside the name and the port. */
  let { head = $bindable(null) } = $props()

  let auskunft = $state(null)
  let gewaehlt = $state('')
  let arbeitet = $state(false)
  let protokoll = $state([])
  let protokollAuf = $state(false)

  // Keep the big log window fed while it is open.
  $effect(() => {
    if (protokollOffen()) setzeProtokollZeilen(protokoll)
  })

  /* The four numbers the speech server starts with, beside its file. Shown
     from what is stored for the next start (the dictation setting) and sent
     with the start; while a server runs, the answer reports back what is
     actually running. */
  let port = $state(8084)
  let kontext = $state(4096)
  /* `null` is "Auto": no layer count is sent. */
  let schichten = $state(null)
  let faeden = $state(0)
  // Minutes without a request after which the server frees its model; null is never.
  let idle = $state(null)
  let werteGesetzt = false

  /* The dictation fields, mirrored into the page so the controls can bind to
     something. Filled once from the setting; every change writes back. */
  let sprachwahl = $state('auto')
  /* Which file the cleaner runs from — read straight from the setting, not
     mirrored: its picker lives in the clean-up window since the two
     servers got their own panels, and a mirrored copy here would go on
     saying "empty" after somebody chose a file over there. */
  const putzwahl = $derived(diktat.putzmodell ?? '')
  let bereinigungswahl = $state('aus')
  let anweisungstext = $state(null)
  let putzanweisungstext = $state(null)
  let vorlesenwahl = $state(true)
  let keepModelLoaded = $state(true)
  /* Seconds of silence before a spoken sentence is sent. `null`: nothing
     stored, the field says "Auto" and the service goes by its works number. */
  let pauseSeconds = $state(null)
  /* Seconds a round of the conversation waits for the first word, and how
     many rounds without one end it; `null` likewise means the works number. */
  let waitSeconds = $state(null)
  let silentRoundsCount = $state(null)
  let automatikwahl = $state(false)
  let stimmewahl = $state('')
  let stimmprobewahl = $state('')
  let stimmsprachwahl = $state('')
  let gespraechsanweisungstext = $state(null)

  /* The voice's own numbers, mirrored the same way: the stored value while
     one is stored, the works answer otherwise. The works numbers are frozen
     once (`werkStimm`) — the poll replaces `auskunft` every three seconds,
     and a value read from it while the hand is on a slider would move under
     it. */
  let stimmregler = $state({ temperatur: 0.9, top_k: 50, top_p: 1, min_p: 0, strafe: 1.05 })
  /* "Auto" is `null` in the field and the word in the setting: the program of
     the voice takes its own value, and the slider rests where that value is
     (`werkAuto`, from the service). */
  let werkAuto = $state({ temperatur: 0.8, top_k: 40, top_p: 0.95, min_p: 0.05, strafe: 1.05 })
  let stimmSchichten = $state(null)
  let stimmFaeden = $state(0)
  let werkStimm = null
  let werkSchichten = null
  let werkFaeden = 0
  /* The works answers of the start values, frozen when the fields are
     filled: the poll replaces `auskunft` every three seconds and a number
     read from it while the hand is on a field would move under it. */
  let werkStart = {}
  let gespiegelt = false

  /* A voice value as the field shows it: what is stored, else the works
     answer; the stored word "auto" is an empty field. */
  function reglerWert(gespeichert, werk) {
    return gespeichert === 'auto' ? null : (gespeichert ?? werk)
  }
  function reglerAusSpeicher() {
    return {
      temperatur: reglerWert(diktat.stimmtemperatur, werkStimm.temperatur),
      top_k: reglerWert(diktat.stimmtop_k, werkStimm.top_k),
      top_p: reglerWert(diktat.stimmtop_p, werkStimm.top_p),
      min_p: reglerWert(diktat.stimmmin_p, werkStimm.min_p),
      strafe: reglerWert(diktat.stimmstrafe, werkStimm.strafe),
    }
  }

  /* What a failed read reported last, so a failure that lasts is said once
     and not every few seconds; a read that gets through clears it, so the
     same failure returning later is news again. The answer before it stays
     on the page — a server shown as stopped because one read failed is a
     wrong picture, not a quiet one. */
  let letzterFehler = null

  async function laden() {
    try {
      auskunft = await api.spracheAuskunft()
      if (!gewaehlt || !auskunft.modelle.some((m) => m.name === gewaehlt)) {
        gewaehlt = auskunft.modell || auskunft.modelle[0]?.name || ''
      }
      /* From whatever is running, because that is the truth about this server;
         otherwise once, from the works answers it sends along. Re-reading on
         every poll would pull a slider out from under the hand. */
      if (auskunft.laeuft) {
        port = auskunft.port ?? port
        kontext = auskunft.kontext ?? kontext
        schichten = auskunft.schichten ?? null
        faeden = auskunft.threads ?? 0
        werteGesetzt = true
      } else if (!werteGesetzt) {
        const v = auskunft.vorgaben ?? {}
        port = auskunft.port ?? port
        kontext = v.kontext ?? kontext
        schichten = v.schichten ?? null
        faeden = v.threads ?? 0
        werteGesetzt = true
      }
      if (protokollAuf || protokollOffen()) {
        protokoll = await api.spracheProtokoll()
      }
      letzterFehler = null
    } catch (fehler) {
      if (fehler.message !== letzterFehler) melde(fehler.message, 'fehler')
      letzterFehler = fehler.message
    }
  }

  $effect(() => {
    standLaden()
    laden()
    return pollWithoutOverlap(laden, 3000)
  })

  /* Both halves have to be in before the fields can be filled: the stored
     answers come from the setting, the works answers from the server. A
     field filled from half of that would write the other half's placeholder
     back the moment somebody typed. */
  $effect(() => {
    if (gespiegelt || !diktat.geladen || !auskunft) return
    const werk = auskunft.diktat_vorgaben ?? {}
    sprachwahl = diktat.sprache || werk.sprache || 'auto'
    bereinigungswahl = diktat.bereinigung || werk.bereinigung || 'aus'
    anweisungstext = diktat.anweisung || werk.anweisung || ''
    putzanweisungstext = diktat.bereinigung_anweisung || werk.bereinigung_anweisung || ''
    // `??`, not `||`: an explicit `false` is a real choice, not a missing one.
    vorlesenwahl = diktat.vorlesen ?? werk.vorlesen ?? true
    // The service says what the works answer is (off on a small machine); nothing is assumed here.
    keepModelLoaded = diktat.keep_model_in_memory ?? werk.keep_model_in_memory ?? false
    pauseSeconds = diktat.conversation_pause_seconds
    waitSeconds = diktat.conversation_wait_seconds
    silentRoundsCount = diktat.conversation_silent_rounds
    automatikwahl = diktat.automatik ?? werk.automatik ?? false
    // `??`: a stored empty choice ("-") is an answer, nothing stored is the
    // voice of the system this machine starts with.
    stimmewahl = diktat.stimme ?? werk.stimme ?? ''
    stimmprobewahl = diktat.stimmprobe ?? ''
    stimmsprachwahl = diktat.stimmsprache ?? ''
    gespraechsanweisungstext = diktat.gespraechsanweisung || werk.gespraechsanweisung || ''
    werkStimm = {
      temperatur: werk.stimmtemperatur,
      top_k: werk.stimmtop_k,
      top_p: werk.stimmtop_p,
      min_p: werk.stimmmin_p,
      strafe: werk.stimmstrafe,
    }
    werkSchichten = werk.stimmschichten ?? null
    werkFaeden = werk.stimmfaeden
    const auto = werk.stimmauto ?? {}
    werkAuto = {
      temperatur: auto.stimmtemperatur ?? werkAuto.temperatur,
      top_k: auto.stimmtop_k ?? werkAuto.top_k,
      top_p: auto.stimmtop_p ?? werkAuto.top_p,
      min_p: auto.stimmmin_p ?? werkAuto.min_p,
      strafe: auto.stimmstrafe ?? werkAuto.strafe,
    }
    stimmregler = reglerAusSpeicher()
    stimmSchichten = diktat.stimmschichten ?? werkSchichten
    stimmFaeden = diktat.stimmfaeden ?? werkFaeden
    /* The server's start values: what is stored, else the works answer. A
       server that runs shows what runs (the poll above), and a stored file
       that has left the folder is not shown. */
    const v = auskunft.vorgaben ?? {}
    werkStart = {
      speech_model: auskunft.modelle[0]?.name ?? '',
      speech_context: v.kontext ?? 4096,
      speech_gpu_layers: v.schichten ?? null,
      speech_threads: v.threads ?? 0,
      speech_port: auskunft.port ?? 8084,
      speech_idle_minutes: null,
    }
    if (!auskunft.laeuft) {
      port = diktat.speech_port ?? werkStart.speech_port
      kontext = diktat.speech_context ?? werkStart.speech_context
      schichten = diktat.speech_gpu_layers ?? werkStart.speech_gpu_layers
      faeden = diktat.speech_threads ?? werkStart.speech_threads
      idle = diktat.speech_idle_minutes ?? werkStart.speech_idle_minutes
      if (diktat.speech_model && auskunft.modelle.some((m) => m.name === diktat.speech_model)) {
        gewaehlt = diktat.speech_model
      }
      werteGesetzt = true
    }
    gespiegelt = true
  })

  function sichern(werte) {
    return werteSetzen(werte).catch(() => melde(t('fehler.einstellung_speichern'), 'fehler'))
  }

  /* Every field here writes itself a beat after the last change. The beat is
     kept by key and made at once — when the window goes away, and before
     "Start" — so a value typed a moment before closing or starting is not
     dropped with its timer. */
  const writer = createDelayedWriter(400)
  async function alleSichern() {
    await writer.flush()
    await schreibenAbwarten()
  }
  $effect(() => () => {
    writer.flush()
  })

  /* The three instructions are typed rather than picked, so each is written
     a beat after the last keystroke instead of on every one. Its own timer
     per field — one shared timer would let the second field cancel the
     first field's write. */
  /* Cleared BEFORE the guards, not after them. Returning at a guard with a
     timer still pending is how a text typed and taken back inside the beat
     was written anyway: the change that undid it hit the guard, and the timer
     from the change before it went on to fire. The teardown carries the same
     rule past the panel closing. */
  $effect(() => {
    const text = anweisungstext
    writer.cancel('anweisung')
    if (text === null || !gespiegelt || text === diktat.anweisung) return
    /* A shipped text nobody moved is not an answer this panel gave. Storing
       it would turn the works text into a choice, and a later change of it
       would never reach anybody who once opened this panel. */
    if (!diktat.anweisung && text === werkAnweisung) return
    writer.plan('anweisung', () => sichern({ anweisung: text }), 600)
  })
  $effect(() => {
    const text = putzanweisungstext
    writer.cancel('putzanweisung')
    if (text === null || !gespiegelt || text === diktat.bereinigung_anweisung) return
    if (!diktat.bereinigung_anweisung && text === werkBereinigung) return
    writer.plan('putzanweisung', () => sichern({ bereinigung_anweisung: text }), 600)
  })
  $effect(() => {
    const text = gespraechsanweisungstext
    writer.cancel('gespraechsanweisung')
    if (text === null || !gespiegelt || text === diktat.gespraechsanweisung) return
    if (!diktat.gespraechsanweisung && text === werkGespraechsanweisung) return
    writer.plan('gespraechsanweisung', () => sichern({ gespraechsanweisung: text }), 600)
  })

  /* The five generation values, written a beat after the hand stops — a
     slider dragged across the track would otherwise write every step it
     passes. Only the values that really moved are sent; a value nobody
     moved off the works one is not stored. */
  $effect(() => {
    const _ = JSON.stringify(stimmregler)
    if (!gespiegelt) return
    writer.plan('stimmregler', () => {
      const nachtrag = {}
      for (const { knopf, schluessel } of PARAMETER) {
        // An empty field is "Auto", stored as the word.
        const wert = stimmregler[knopf] ?? 'auto'
        if (wert === diktat[schluessel]) continue
        if (diktat[schluessel] === null && wert === werkStimm[knopf]) continue
        nachtrag[schluessel] = wert
      }
      if (!Object.keys(nachtrag).length) return
      return werteSetzen(nachtrag).catch(() => {
        melde(t('fehler.einstellung_speichern'), 'fehler')
        // Back to what is stored: left standing, the value would differ
        // from the store again and the effect would retry for ever.
        stimmregler = reglerAusSpeicher()
      })
    })
  })

  /* The voice's layers and threads, the same beat and the same rule. Its
     own timer per value, like the instructions. */
  $effect(() => {
    const wert = stimmSchichten
    writer.cancel('stimmschichten')
    if (!gespiegelt || wert === diktat.stimmschichten) return
    if (diktat.stimmschichten === null && wert === werkSchichten) return
    writer.plan('stimmschichten', () =>
      werteSetzen({ stimmschichten: wert }).catch(() => {
        melde(t('fehler.einstellung_speichern'), 'fehler')
        stimmSchichten = diktat.stimmschichten ?? werkSchichten
      }),
    )
  })
  $effect(() => {
    const wert = stimmFaeden
    writer.cancel('stimmfaeden')
    if (!gespiegelt || wert === diktat.stimmfaeden) return
    if (diktat.stimmfaeden === null && wert === werkFaeden) return
    writer.plan('stimmfaeden', () =>
      werteSetzen({ stimmfaeden: wert }).catch(() => {
        melde(t('fehler.einstellung_speichern'), 'fehler')
        stimmFaeden = diktat.stimmfaeden ?? werkFaeden
      }),
    )
  })

  /* The pause before sending, written a beat after the hand stops. An empty
     field is `null`: the stored number is taken away and the works one
     stands. */
  $effect(() => {
    const wert = pauseSeconds
    writer.cancel('pause')
    if (!gespiegelt || wert === diktat.conversation_pause_seconds) return
    // The field shows tenths: what is kept is what it shows.
    if (wert !== null && Math.round(wert * 10) / 10 !== wert) {
      pauseSeconds = Math.round(wert * 10) / 10
      return
    }
    writer.plan('pause', () =>
      werteSetzen({ conversation_pause_seconds: wert }).catch(() => {
        melde(t('fehler.einstellung_speichern'), 'fehler')
        pauseSeconds = diktat.conversation_pause_seconds
      }),
    )
  })

  /* How long a round waits and how many silent rounds end the conversation,
     written the same way: an empty field takes the stored number away. */
  $effect(() => {
    const value = waitSeconds
    writer.cancel('wait')
    if (!gespiegelt || value === diktat.conversation_wait_seconds) return
    if (value !== null && Math.round(value * 10) / 10 !== value) {
      waitSeconds = Math.round(value * 10) / 10
      return
    }
    writer.plan('wait', () =>
      werteSetzen({ conversation_wait_seconds: value }).catch(() => {
        melde(t('fehler.einstellung_speichern'), 'fehler')
        waitSeconds = diktat.conversation_wait_seconds
      }),
    )
  })

  $effect(() => {
    const value = silentRoundsCount
    writer.cancel('rounds')
    if (!gespiegelt || value === diktat.conversation_silent_rounds) return
    writer.plan('rounds', () =>
      werteSetzen({ conversation_silent_rounds: value }).catch(() => {
        melde(t('fehler.einstellung_speichern'), 'fehler')
        silentRoundsCount = diktat.conversation_silent_rounds
      }),
    )
  })

  /* The server's start values — its file, context, GPU layers, threads and
     port — written as they are touched, one key each, so the next start and
     the next opening of this window find them. Only while the server is
     off: a running server's own numbers are not a choice made here. A value
     nobody moved off the works answer is not stored, and one that could not
     be stored goes back to what is. */
  const STARTWERTE = {
    speech_model: { aus: () => gewaehlt, zurueck: (w) => (gewaehlt = w) },
    speech_context: { aus: () => kontext, zurueck: (w) => (kontext = w) },
    speech_gpu_layers: { aus: () => schichten, zurueck: (w) => (schichten = w) },
    speech_threads: { aus: () => faeden, zurueck: (w) => (faeden = w) },
    speech_port: { aus: () => port, zurueck: (w) => (port = w) },
    speech_idle_minutes: { aus: () => idle, zurueck: (w) => (idle = w) },
  }
  $effect(() => {
    const jetzt = Object.fromEntries(Object.entries(STARTWERTE).map(([name, f]) => [name, f.aus()]))
    for (const name of Object.keys(STARTWERTE)) writer.cancel(`start:${name}`)
    if (!gespiegelt || auskunft?.laeuft) return
    for (const [name, wert] of Object.entries(jetzt)) {
      // `''` and `null` are the placeholders of "nothing stored"; a stored
      // zero (threads: automatic) is an answer.
      const stand = diktat[name] === '' ? null : (diktat[name] ?? null)
      if (wert === '' || wert === (stand ?? werkStart[name])) continue
      writer.plan(`start:${name}`, () =>
        werteSetzen({ [name]: wert }).catch(() => {
          melde(t('fehler.einstellung_speichern'), 'fehler')
          STARTWERTE[name].zurueck(stand ?? werkStart[name])
        }),
      )
    }
  })

  /* The log is read when it is asked for — opening the drawer fetches it
     at once, and only an open drawer or the big log window keeps it fed.
     Nothing runs on a timer for a drawer nobody opened. */
  async function protokollKlappen() {
    protokollAuf = !protokollAuf
    if (!protokollAuf) return
    try {
      protokoll = await api.spracheProtokoll()
    } catch {
      protokoll = []
    }
  }

  /* ——— The voice sample: recorded, played and deleted from here ———
     A recording is made with the dictation's own recorder
     (lib/aufnahme.svelte.js) and kept by the service in the speech model
     folder, which also chooses it. While the dictation holds the microphone
     the record button is locked. */
  let probeNimmtAuf = $state(false)
  /* True from the moment the recorder really runs for us. */
  let probeBegonnen = $state(false)
  let probeSpielt = $state(false)
  let probeAudio = null
  let probeUrl = null
  const diktatBelegt = $derived(aufnahme.laeuft && !probeNimmtAuf)
  const probeName = $derived(stimmprobewahl && (auskunft?.stimmproben ?? []).includes(stimmprobewahl) ? stimmprobewahl : '')

  /** Seconds as m:ss. */
  function minutenSekunden(sekunden) {
    const ganz = Math.round(sekunden)
    return `${Math.floor(ganz / 60)}:${String(ganz % 60).padStart(2, '0')}`
  }

  const probeZeile = $derived(
    probeNimmtAuf
      ? minutenSekunden(aufnahme.sekunden)
      : probeName
        ? `${probeName}${auskunft?.stimmproben_dauer?.[probeName] != null ? ` · ${minutenSekunden(auskunft.stimmproben_dauer[probeName])}` : ''}`
        : '-',
  )

  function probeGewaehlt(name) {
    stimmprobewahl = name
    diktat.stimmprobe = name
  }

  async function probeAufnehmen() {
    if (probeNimmtAuf || probeSpielt || diktatBelegt) return
    probeNimmtAuf = true
    try {
      await aufnahmeStarten(probeBeenden)
    } catch (fehler) {
      probeNimmtAuf = false
      melde(t(fehlerschluessel(fehler)), 'fehler')
      return
    }
    /* The recorder does nothing, without a word, while somebody else is
       just starting it: then no recording of ours runs. */
    if (aufnahme.laeuft) probeBegonnen = true
    else probeNimmtAuf = false
  }

  /* `ausserGrenze` is what the recorder hands over when it stops itself at
     its ceiling (the recording is already ended then); a press of the stop
     button hands over nothing. */
  async function probeBeenden(ausserGrenze) {
    if (!probeNimmtAuf) return
    const wav = ausserGrenze !== undefined ? ausserGrenze : aufnahmeStoppen()
    probeNimmtAuf = false
    probeBegonnen = false
    if (!wav) {
      melde(t('fehler.aufnahme_leer'), 'fehler')
      return
    }
    try {
      const gesichert = await api.voiceSampleSave(wav)
      probeGewaehlt(gesichert.name)
      await laden()
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    }
  }

  /* A recording that ended elsewhere — the dictation took the microphone
     and its own stop ended ours — leaves no running timer behind. */
  $effect(() => {
    if (probeBegonnen && !aufnahme.laeuft) {
      probeNimmtAuf = false
      probeBegonnen = false
    }
  })

  /* Counts the starts and stops of playing: an answer of the service that
     arrives after the stop button was pressed must not start the sound. */
  let probeLauf = 0

  function probeAbspielenEnde() {
    probeLauf += 1
    probeSpielt = false
    probeAudio = null
    if (probeUrl) URL.revokeObjectURL(probeUrl)
    probeUrl = null
  }

  async function probeAbspielen() {
    if (!probeName || probeSpielt || probeNimmtAuf) return
    probeSpielt = true
    const lauf = ++probeLauf
    try {
      const blob = await api.voiceSampleBlob(probeName)
      if (lauf !== probeLauf) return
      probeUrl = URL.createObjectURL(blob)
      probeAudio = new Audio(probeUrl)
      probeAudio.addEventListener('ended', probeAbspielenEnde)
      await probeAudio.play()
    } catch (fehler) {
      if (lauf === probeLauf) probeAbspielenEnde()
      melde(String(fehler.message || fehler), 'fehler')
    }
  }

  /** The stop button ends what runs: the recording, or the playback. */
  function probeStoppen() {
    if (probeNimmtAuf) {
      probeBeenden()
    } else if (probeSpielt) {
      probeAudio?.pause()
      probeAbspielenEnde()
    }
  }

  async function probeLoeschen() {
    if (!probeName) return
    if (!(await frage(t('sprachserver.sample_delete_question')))) return
    const name = probeName
    probeStoppen()
    try {
      auskunft = await api.voiceSampleDelete(name)
      probeGewaehlt('')
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    }
  }

  $effect(() => () => {
    probeAudio?.pause()
    if (probeUrl) URL.revokeObjectURL(probeUrl)
    if (probeNimmtAuf) aufnahmeStoppen()
  })

  /* The parameters stand folded: only the temperature shows until the row
     is opened. */
  let parameterOffen = $state(false)

  async function ordnerZeigen() {
    try {
      await api.spracheOrdnerOeffnen()
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    }
  }

  async function schalten() {
    if (arbeitet) return
    arbeitet = true
    try {
      /* What was typed a moment ago is written before the start is asked:
         the server reads its numbers from what is stored. */
      await alleSichern()
      auskunft = auskunft?.laeuft
        ? await api.spracheStoppen()
        : await api.spracheStarten(gewaehlt, { port, kontext, schichten, threads: faeden })
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    } finally {
      arbeitet = false
    }
  }

  const laeuft = $derived(Boolean(auskunft?.laeuft))
  const bereit = $derived(Boolean(gewaehlt) && Boolean(auskunft?.programm))
  const projektor = $derived(auskunft?.projektoren?.[gewaehlt] ?? null)
  /* What the start of the model that hears is planned to take: its file, the
     projector that belongs to it and the context that is set. */
  const schaetzung = $derived(
    serverAnteil(auskunft?.modelle, [], {
      modell: gewaehlt,
      kontext,
      vision: projektor ?? '',
      projectors: auskunft?.projector_size_gb,
    }),
  )

  /* The server's one deed. The page head (ModelleLokal.svelte) draws its
     button; the page keeps what the button says and does. */
  const tat = $derived({
    text: laeuft ? t('modell.server_anhalten') : t('modell.server_starten'),
    punkt: laeuft ? 'gruen' : 'still',
    gesperrt: arbeitet || (!laeuft && !bereit),
    onTat: schalten,
  })

  serverHead('sprache', (value) => (head = value), () => ({
    tat, line: '', port: laeuft ? auskunft.port : null,
  }))

  const modellauswahl = $derived(
    (auskunft?.modelle ?? []).map((m) => ({
      wert: m.name,
      text: `${m.name} · ${entrySize(m.groesse_gb)}`,
      ...entryMark(m.name),
    })),
  )

  /* A voice is a voice model of the speech folder or a voice of the system;
     which one speaks follows from the chosen name, so both stand in the one
     list, the voices of the system after the models, each with its language
     as the system names it. */
  const stimmeauswahl = $derived([
    { wert: '', text: '-' },
    ...modellauswahl,
    ...(auskunft?.system_voices ?? []).map((v) => ({ wert: v.name, text: `${v.name} · ${v.language}` })),
  ])
  /* A stored name the lists no longer carry (a voice that was uninstalled, a
     file that was moved away) still stands in the field under its own name,
     so the field never shows empty while a voice is stored. */
  const stimmeeintraege = $derived(
    stimmewahl && !stimmeauswahl.some((e) => e.wert === stimmewahl)
      ? [...stimmeauswahl, { wert: stimmewahl, text: stimmewahl }]
      : stimmeauswahl,
  )

  /* While a voice of the system is chosen the fields that act on a voice
     model — sample, language, the five values, layers and threads — stay
     visible but cannot be moved; they act again as soon as a voice model is
     chosen. */
  const systemStimme = $derived((auskunft?.system_voices ?? []).some((v) => v.name === stimmewahl))

  const stimmprobeauswahl = $derived([
    { wert: '', text: '-' },
    ...(auskunft?.stimmproben ?? []).map((name) => ({ wert: name, text: name })),
  ])

  const stimmsprachauswahl = $derived([
    { wert: '', text: '-' },
    ...STIMMSPRACHEN.map((code) => ({ wert: code, text: t(`sprache.name_${code}`) })),
  ])

  const sprachauswahl = $derived([
    { wert: 'auto', text: t('sprache.name_auto') },
    ...SPRACHEN.map((code) => ({ wert: code, text: t(`sprache.name_${code}`) })),
  ])

  /* The tidy-up model can only be chosen as the cleaner once a file stands
     in its own picker — without one there is nobody to ask, and an entry
     that cannot do anything is an entry that lies. */
  const bereinigungsauswahl = $derived([
    { wert: 'aus', text: t('sprachserver.bereinigung_aus') },
    {
      wert: 'putzmodell',
      text: putzwahl
        ? t('sprachserver.bereinigung_putzmodell')
        : t('sprachserver.bereinigung_putzmodell_leer'),
    },
    { wert: 'modell', text: t('sprachserver.bereinigung_modell') },
    { wert: 'agent', text: t('sprachserver.bereinigung_agent') },
  ])

  const werkAnweisung = $derived(auskunft?.diktat_vorgaben?.anweisung ?? '')
  const werkBereinigung = $derived(auskunft?.diktat_vorgaben?.bereinigung_anweisung ?? '')
  const werkGespraechsanweisung = $derived(auskunft?.diktat_vorgaben?.gespraechsanweisung ?? '')

  /* Three fields stand under the same visible name, and each has a reset
     button of the same name. For a screen reader every one of them carries
     the name of its group in front — the words the window already shows, in
     the order group, field. */
  const anweisungsname = $derived(
    `${t('sprachserver.gruppe_diktat')} ${t('sprachserver.feld_anweisung')}`,
  )
  const putzanweisungsname = $derived(
    `${t('sprachserver.gruppe_bereinigung')} ${t('sprachserver.feld_anweisung')}`,
  )
  const gespraechsanweisungsname = $derived(
    `${t('sprachserver.gruppe_gespraech')} ${t('sprachserver.feld_gespraechsanweisung')}`,
  )
  const zuruecksetzenName = (feldname) => `${t('sprachserver.zuruecksetzen')} ${feldname}`

  function anzeige(zahl, ganzzahlig, schritt) {
    return ganzzahlig ? String(zahl) : formatNumber(zahl, fractionDigits(schritt), texte.sprache)
  }
</script>

<!-- The house's server shape (Servertafel.svelte), in this order:
     the speech model, its storage and network beside dictation and clean-up;
     the voice and its storage beside the conversation; the sampling values
     of the voice across the full width; the log at the foot. -->
<Servertafel
  modelle={modellauswahl}
  throughput="speech"
  bind:gewaehlt
  modellBeschriftung={t('sprachserver.modell')}
  modellGesperrt={laeuft}
  leerText={auskunft ? t('sprachserver.kein_modell') : ''}
  katalogTat={() => katalogOeffnen('sprache')}
  speicherort="speech_models"
  modellGewicht={gewaehlt ? 3 : 2}
>
  {#snippet belowModel()}
    <!-- The projector, in words rather than as a row to pick from. A speech
         model without one does not run quieter, it does not hear at all —
         and the file that goes with it is not a choice anybody makes, it is
         the other half of the model. -->
    {#if gewaehlt}
      <div class="zeile kurz" class:fehlt={!projektor}>
        {projektor
          ? t('sprachserver.projektor', { datei: projektor })
          : t('sprachserver.kein_projektor')}
      </div>
    {/if}
  {/snippet}

  {#snippet inhalt(modellkarte)}
    <Startfehler arch={auskunft?.unknown_architecture} />
    <Serverreihe>
      {#snippet links()}
        {@render modellkarte()}
        <!-- The storage numbers of the model that hears. No experts row: a
             speech model has none. -->
        <Serverregler
          kennung="sp"
          teil="speicher"
          gesperrt={laeuft}
          moe={false}
          bind:kontext
          {kontextstufen}
          bind:schichten
          maxSchichten={MAX_SCHICHTEN}
          bind:faeden
          maxFaeden={auskunft?.kerne ?? 8}
          {schaetzung}
        />
        <Serverregler kennung="sp" teil="netzwerk" gesperrt={laeuft} bind:port />
        <Serverregler kennung="sp" teil="leerlauf" gesperrt={laeuft} bind:idle />
      {/snippet}
      {#snippet rechts()}
        <Serverabschnitt zeichen="sprache" titel={t('sprachserver.gruppe_diktat')}>
          <div class="zeile">
            <label class="name" for="sp-diktatsprache" title={t('sprachserver.feld_sprache')}>{t('sprachserver.feld_sprache')}</label>
            <div class="wahl">
              <Auswahlfeld
                id="sp-diktatsprache"
                bind:wert={sprachwahl}
                eintraege={sprachauswahl}
                beschriftung={t('sprachserver.feld_sprache')}
                gewaehlt={(neu) => sichern({ sprache: neu })}
              />
            </div>
          </div>
          <div class="zeile stapel">
            <div class="obenzeile">
              <label class="name" for="sp-anweisung">{t('sprachserver.feld_anweisung')}</label>
              <button class="rowsign" onclick={() => (anweisungstext = werkAnweisung)}
                      title={t('sprachserver.zuruecksetzen')}
                      aria-label={zuruecksetzenName(anweisungsname)}>
                <Hauszeichen zeichen="refresh" groesse={14} />
              </button>
            </div>
            <WachsendesFeld
              knapp
              zeilen={3}
              bind:wert={anweisungstext}
              beschriftung={anweisungsname}
            />
          </div>
          <!-- On: a finished dictation goes out the moment the recording is
               stopped, instead of waiting in the field for Enter. -->
          <div class="zeile niedrig">
            <span class="name">{t('sprachserver.feld_automatik')}</span>
            <Schalter
              id="sp-automatik"
              an={automatikwahl}
              beschriftung={t('sprachserver.feld_automatik')}
              onschalten={(neu) => {
                automatikwahl = neu
                // A switch that failed to store goes back, or it would show a
                // choice the service does not know about.
                werteSetzen({ automatik: neu }).catch(() => {
                  automatikwahl = !neu
                  melde(t('fehler.einstellung_speichern'), 'fehler')
                })
              }}
            />
          </div>
        </Serverabschnitt>

        <Serverabschnitt zeichen="besen" titel={t('sprachserver.gruppe_bereinigung')}>
          <div class="zeile">
            <label class="name" for="sp-bereinigung" title={t('sprachserver.feld_bereinigung')}>{t('sprachserver.feld_bereinigung')}</label>
            <div class="wahl">
              <Auswahlfeld
                id="sp-bereinigung"
                bind:wert={bereinigungswahl}
                eintraege={bereinigungsauswahl}
                beschriftung={t('sprachserver.feld_bereinigung')}
                gewaehlt={(neu) => sichern({ bereinigung: neu })}
              />
            </div>
          </div>
          <div class="zeile stapel">
            <div class="obenzeile">
              <label class="name" for="sp-putzanweisung">{t('sprachserver.feld_anweisung')}</label>
              <button class="rowsign" onclick={() => (putzanweisungstext = werkBereinigung)}
                      title={t('sprachserver.zuruecksetzen')}
                      aria-label={zuruecksetzenName(putzanweisungsname)}>
                <Hauszeichen zeichen="refresh" groesse={14} />
              </button>
            </div>
            <WachsendesFeld
              knapp
              zeilen={3}
              bind:wert={putzanweisungstext}
              beschriftung={putzanweisungsname}
            />
          </div>
        </Serverabschnitt>
      {/snippet}
    </Serverreihe>

    <Serverreihe>
      {#snippet links()}
        <!-- The voice, as a model card of its own: the same shape as the
             speech model's card above, and its own numbers below it. It is
             not a second process — a voice is one call per sentence — so its
             card stands still while the speech server runs. -->
        <Serverabschnitt zeichen="sprache_welle" titel={t('sprachserver.gruppe_gespraechsmodell')} gewicht={2}>
          <div class="zeile stimmzeile">
            <div class="feldplatz">
              <Auswahlfeld
                id="sp-stimmemodell"
                bind:wert={stimmewahl}
                eintraege={stimmeeintraege}
                beschriftung={t('sprachserver.feld_stimme')}
                gewaehlt={(neu) => sichern({ stimme: neu })}
              />
            </div>
            <svg class="weiter" width="15" height="15" viewBox="0 0 15 15" fill="none"
                 stroke="currentColor" stroke-width="1.2" stroke-linecap="round"
                 stroke-linejoin="round" aria-hidden="true">
              <path d="M3.125 7.5H11.875M7.5 11.875L11.875 7.5L7.5 3.125" />
            </svg>
            <button class="katalogtuer" onclick={() => katalogOeffnen('sprache')}
                    title={t('modell.zum_katalog')} aria-label={t('modell.zum_katalog')}>
              <Hauszeichen zeichen="raster" groesse="klein" />
            </button>
          </div>
          <Speicherortzeile name="speech_models" />
        </Serverabschnitt>
        <!-- The voice's layers and threads. No context row: a voice reads one
             answer and is done. Its own `kennung`: the two storage cards must
             not answer to the same field ids. -->
        <Serverregler
          kennung="sps"
          teil="speicher"
          kontextzeile={false}
          moe={false}
          bind:schichten={stimmSchichten}
          maxSchichten={MAX_SCHICHTEN}
          bind:faeden={stimmFaeden}
          maxFaeden={auskunft?.kerne ?? 8}
          gesperrt={systemStimme}
        />
      {/snippet}
      {#snippet rechts()}
        <Serverabschnitt zeichen="sprache_welle" titel={t('sprachserver.gruppe_gespraech')} gewicht={5}>
          <div class="zeile niedrig">
            <span class="name">{t('sprachserver.feld_vorlesen')}</span>
            <Schalter
              id="sp-vorlesen"
              an={vorlesenwahl}
              beschriftung={t('sprachserver.feld_vorlesen')}
              onschalten={(neu) => { vorlesenwahl = neu; sichern({ vorlesen: neu }) }}
            />
          </div>
          <div class="zeile niedrig">
            <span class="name">{t('sprachserver.keep_model_loaded')}</span>
            <Schalter
              id="sp-keep-model-loaded"
              an={keepModelLoaded}
              beschriftung={t('sprachserver.keep_model_loaded')}
              onschalten={(neu) => { keepModelLoaded = neu; sichern({ keep_model_in_memory: neu }) }}
            />
          </div>
          <div class="zeile">
            <label class="zahlname" for="sp-pause-before-sending">{t('sprachserver.pause_before_sending')}</label>
            <div class="zahlplatz">
              <Zahlenfeld
                id="sp-pause-before-sending"
                bind:wert={pauseSeconds}
                min={0.1}
                max={600}
                schritt={0.1}
                nullwort={t('parameter.auto')}
                beschriftung={t('sprachserver.pause_before_sending')}
              />
            </div>
          </div>
          <div class="zeile">
            <label class="zahlname" for="sp-wait-for-speech">{t('sprachserver.wait_for_speech')}</label>
            <div class="zahlplatz">
              <Zahlenfeld
                id="sp-wait-for-speech"
                bind:wert={waitSeconds}
                min={0.1}
                schritt={0.1}
                nullwort={t('parameter.auto')}
                beschriftung={t('sprachserver.wait_for_speech')}
              />
            </div>
          </div>
          <div class="zeile">
            <label class="zahlname" for="sp-rounds-without-speech">{t('sprachserver.rounds_without_speech')}</label>
            <div class="zahlplatz">
              <Zahlenfeld
                id="sp-rounds-without-speech"
                bind:wert={silentRoundsCount}
                min={1}
                schritt={1}
                ganzzahlig
                nullwort={t('parameter.auto')}
                beschriftung={t('sprachserver.rounds_without_speech')}
              />
            </div>
          </div>
          <div class="zeile">
            <label class="name" for="sp-stimmsprache" title={t('sprachserver.feld_stimmsprache')}>{t('sprachserver.feld_stimmsprache')}</label>
            <div class="wahl">
              <Auswahlfeld
                id="sp-stimmsprache"
                bind:wert={stimmsprachwahl}
                eintraege={stimmsprachauswahl}
                beschriftung={t('sprachserver.feld_stimmsprache')}
                gesperrt={systemStimme}
                gewaehlt={(neu) => sichern({ stimmsprache: neu })}
              />
            </div>
          </div>
          <div class="zeile stapel">
            <div class="obenzeile">
              <label class="name" for="sp-gespraechsanweisung">{t('sprachserver.feld_gespraechsanweisung')}</label>
              <button class="rowsign" onclick={() => (gespraechsanweisungstext = werkGespraechsanweisung)}
                      title={t('sprachserver.zuruecksetzen')}
                      aria-label={zuruecksetzenName(gespraechsanweisungsname)}>
                <Hauszeichen zeichen="refresh" groesse={14} />
              </button>
            </div>
            <WachsendesFeld
              knapp
              zeilen={3}
              bind:wert={gespraechsanweisungstext}
              beschriftung={gespraechsanweisungsname}
            />
          </div>
        </Serverabschnitt>
      {/snippet}
    </Serverreihe>

    <Serverabschnitt titel={t('sprachserver.feld_stimmprobe')}>
      <div class="zeile probezeile">
        <label class="name" for="sp-stimmprobe">{t('sprachserver.sample_file')}</label>
        <div class="probewahl">
          <Auswahlfeld
            id="sp-stimmprobe"
            bind:wert={stimmprobewahl}
            eintraege={stimmprobeauswahl}
            beschriftung={t('sprachserver.feld_stimmprobe')}
            gesperrt={systemStimme}
            gewaehlt={(neu) => sichern({ stimmprobe: neu })}
          />
        </div>
        <button class="zeichenknopf" onclick={ordnerZeigen}
                title={t('sprachserver.ordner_zeigen')} aria-label={t('sprachserver.ordner_zeigen')}>
          <Hauszeichen zeichen="ordner" groesse="klein" />
        </button>
      </div>
      <div class="zeile probeaktionen">
        <div class="aktionen">
          <button class="zeichenknopf" id="sp-probe-aufnehmen" onclick={probeAufnehmen}
                  disabled={probeNimmtAuf || probeSpielt || diktatBelegt || systemStimme}
                  title={diktatBelegt ? t('sprachserver.sample_dictation_busy') : t('sprachserver.sample_record')}
                  aria-label={t('sprachserver.sample_record')}>
            <Hauszeichen zeichen="microphone" groesse="klein" />
          </button>
          <button class="zeichenknopf" id="sp-probe-abspielen" onclick={probeAbspielen}
                  disabled={!probeName || probeSpielt || probeNimmtAuf || systemStimme}
                  title={t('sprachserver.sample_play')} aria-label={t('sprachserver.sample_play')}>
            <Hauszeichen zeichen="play" groesse="klein" />
          </button>
          <button class="zeichenknopf" id="sp-probe-stoppen" onclick={probeStoppen}
                  disabled={(!probeNimmtAuf && !probeSpielt) || systemStimme}
                  title={t('sprachserver.sample_stop')} aria-label={t('sprachserver.sample_stop')}>
            <Hauszeichen zeichen="stop" groesse="klein" />
          </button>
        </div>
        <span class="probename" class:laeuft={probeNimmtAuf}>{probeZeile}</span>
        <button class="zeichenknopf rechtsaussen" id="sp-probe-loeschen" onclick={probeLoeschen}
                disabled={!probeName || probeNimmtAuf || systemStimme}
                title={t('sprachserver.sample_delete')} aria-label={t('sprachserver.sample_delete')}>
          <Hauszeichen zeichen="trash" groesse="klein" />
        </button>
      </div>
    </Serverabschnitt>

    <div class="parameterblock">
      <button class="klappzeile tafelkopf" onclick={() => (parameterOffen = !parameterOffen)} aria-expanded={parameterOffen}>
        <svg class="winkel" class:auf={parameterOffen} width="14" height="14" viewBox="0 0 11 11" fill="none"
             stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"
             aria-hidden="true">
          <path d="M4.125 2.75L6.875 5.5L4.125 8.25" />
        </svg>
        <span>{t('sprachserver.gruppe_parameter')}</span>
      </button>
      <Serverabschnitt>
        {#each PARAMETER as p, i (p.knopf)}
          {#if i === 0 || parameterOffen}
            <div class="zeile regel">
              <div class="kopfzeile">
                <label class="regelname" for="sp-{p.knopf}">{parameterlabels[p.knopf]}</label>
                <div class="zahlplatz">
                  <Zahlenfeld
                    bind:wert={stimmregler[p.knopf]}
                    min={p.min}
                    max={p.max}
                    schritt={p.schritt}
                    ganzzahlig={p.ganzzahlig}
                    nullwort={t('parameter.auto')}
                    gesperrt={systemStimme}
                  />
                </div>
              </div>
              <Schieberegler
                id="sp-{p.knopf}"
                bind:wert={() => stimmregler[p.knopf] ?? werkAuto[p.knopf], (neu) => (stimmregler[p.knopf] = neu)}
                gesperrt={systemStimme}
                stufen={p.stufen}
                beschriftung={parameterlabels[p.knopf]}
                anzeige={(w) => anzeige(w, p.ganzzahlig, p.schritt)}
                mit_zahl={false}
                fuellung
              />
            </div>
          {/if}
        {/each}
      </Serverabschnitt>
    </div>
    <LlamaCppSection {auskunft} onrefresh={laden} />
  {/snippet}

  {#snippet unten()}
    <div class="log">
      <Serverlogkopf offen={protokollAuf} onumschalten={protokollKlappen}
                     onauskoppeln={() => oeffneProtokoll(t('modell.protokoll_titel'))} />
      {#if protokollAuf}
        <pre class="protokoll">{protokoll.join('\n') || '-'}</pre>
      {/if}
    </div>
  {/snippet}
</Servertafel>

<style>
  /* The rows and their parts are Serverabschnitt.svelte's; here only what
     this window adds. */
  /* The voice's picker row: the same shape as the speech model's above. */
  .stimmzeile {
    gap: 10px;
  }
  .feldplatz {
    flex: 1;
    min-width: 0;
  }
  .weiter {
    flex: none;
    color: var(--text-leise);
  }
  .katalogtuer {
    flex: none;
    width: 32px;
    height: 32px;
    padding: 0;
    display: grid;
    place-items: center;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text-leise);
    cursor: pointer;
    transition: background 0.12s, color 0.12s;
  }
  .katalogtuer:hover {
    background: color-mix(in srgb, var(--text) 6%, var(--glass-button));
    color: var(--text);
  }
  /* The sample block: the picker 200 wide and the folder button beside it,
     under them the buttons of the recording with the chosen file's name. */
  .probezeile {
    gap: 12px;
  }
  .probewahl {
    flex: none;
    width: 200px;
  }
  /* The three buttons of the recording, 10 apart. */
  .aktionen {
    flex: none;
    display: flex;
    gap: 10px;
  }
  .zeichenknopf {
    flex: none;
    width: 34px;
    height: 34px;
    padding: 0;
    display: grid;
    place-items: center;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text-leise);
    cursor: pointer;
    transition: background 0.12s, color 0.12s;
  }
  .zeichenknopf:hover:not(:disabled) {
    background: color-mix(in srgb, var(--text) 6%, var(--glass-button));
    color: var(--text);
  }
  .zeichenknopf:disabled {
    opacity: 0.45;
    cursor: default;
  }
  .rechtsaussen {
    margin-left: auto;
  }
  /* The chosen file and its length, or the running time of a recording. */
  .probename {
    min-width: 0;
    font-size: 12px;
    line-height: 16px;
    color: var(--text-leise);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  /* The parameters: a folding row of 34 over the card; folded, the card
     holds the first parameter only. */
  .parameterblock {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .klappzeile {
    height: 34px;
    padding: 0;
    display: flex;
    align-items: center;
    gap: 10px;
    border: none;
    background: none;
    cursor: pointer;
    text-align: left;
  }
  .klappzeile .winkel {
    flex: none;
    color: var(--text-still);
    transition: transform 0.15s;
  }
  .klappzeile .winkel.auf {
    transform: rotate(90deg);
  }
  @media (prefers-reduced-motion: reduce) {
    .klappzeile .winkel {
      transition: none;
    }
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
</style>
