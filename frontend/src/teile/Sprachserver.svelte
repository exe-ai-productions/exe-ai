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
  import { t, texte } from '../lib/texte.svelte.js'
  import { fractionDigits, formatNumber } from '../lib/numberDisplay.js'
  import { katalogOeffnen, melde } from '../lib/zustand.svelte.js'
  import { diktat, standLaden, werteSetzen } from '../lib/diktat.svelte.js'
  import { SPRACHEN } from '../lib/diktatsprachen.js'
  import { STIMMSPRACHEN } from '../lib/stimmsprachen.js'
  import Servertafel from './Servertafel.svelte'
  import Serverregler from './Serverregler.svelte'
  import Startknopf from './Startknopf.svelte'
  import Startfehler from './Startfehler.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import Serverabschnitt from './Serverabschnitt.svelte'
  import Serverreihe from './Serverreihe.svelte'
  import Serverlogkopf from './Serverlogkopf.svelte'
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

  let auskunft = $state(null)
  let gewaehlt = $state('')
  let arbeitet = $state(false)
  let protokoll = $state([])
  let protokollAuf = $state(false)

  // Keep the big log window fed while it is open.
  $effect(() => {
    if (protokollOffen()) setzeProtokollZeilen(protokoll)
  })

  /* The four numbers the speech server starts with. Held in the page and
     sent with the start, the way the embedding panel holds its port: they
     describe one run, and the answer reports back what is actually
     running. */
  let port = $state(8084)
  let kontext = $state(4096)
  let schichten = $state(MAX_SCHICHTEN)
  let faeden = $state(0)
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
  let stimmSchichten = $state(MAX_SCHICHTEN)
  let stimmFaeden = $state(0)
  let werkStimm = null
  let werkSchichten = MAX_SCHICHTEN
  let werkFaeden = 0
  let gespiegelt = false

  async function laden() {
    try {
      auskunft = await api.spracheAuskunft()
    } catch {
      auskunft = null
      return
    }
    if (!gewaehlt || !auskunft.modelle.some((m) => m.name === gewaehlt)) {
      gewaehlt = auskunft.modell || auskunft.modelle[0]?.name || ''
    }
    /* From whatever is running, because that is the truth about this server;
       otherwise once, from the works answers it sends along. Re-reading on
       every poll would pull a slider out from under the hand. */
    if (auskunft.laeuft) {
      port = auskunft.port ?? port
      kontext = auskunft.kontext ?? kontext
      schichten = auskunft.schichten ?? schichten
      faeden = auskunft.threads ?? 0
      werteGesetzt = true
    } else if (!werteGesetzt) {
      const v = auskunft.vorgaben ?? {}
      port = auskunft.port ?? port
      kontext = v.kontext ?? kontext
      schichten = v.schichten ?? schichten
      faeden = v.threads ?? 0
      werteGesetzt = true
    }
    if (protokollAuf || protokollOffen()) {
      protokoll = await api.spracheProtokoll()
    }
  }

  $effect(() => {
    standLaden()
    laden()
    const takt = setInterval(laden, 3000)
    return () => clearInterval(takt)
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
    automatikwahl = diktat.automatik ?? werk.automatik ?? false
    stimmewahl = diktat.stimme ?? ''
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
    werkSchichten = werk.stimmschichten
    werkFaeden = werk.stimmfaeden
    stimmregler = {
      temperatur: diktat.stimmtemperatur ?? werkStimm.temperatur,
      top_k: diktat.stimmtop_k ?? werkStimm.top_k,
      top_p: diktat.stimmtop_p ?? werkStimm.top_p,
      min_p: diktat.stimmmin_p ?? werkStimm.min_p,
      strafe: diktat.stimmstrafe ?? werkStimm.strafe,
    }
    stimmSchichten = diktat.stimmschichten ?? werkSchichten
    stimmFaeden = diktat.stimmfaeden ?? werkFaeden
    gespiegelt = true
  })

  function sichern(werte) {
    werteSetzen(werte).catch(() => melde(t('fehler.einstellung_speichern'), 'fehler'))
  }

  /* The three instructions are typed rather than picked, so each is written
     a beat after the last keystroke instead of on every one. Its own timer
     per field — one shared timer would let the second field cancel the
     first field's write. */
  let stiftAnweisung = null
  let stiftPutz = null
  /* Cleared BEFORE the guards, not after them. Returning at a guard with a
     timer still pending is how a text typed and taken back inside the beat
     was written anyway: the change that undid it hit the guard, and the timer
     from the change before it went on to fire. The teardown carries the same
     rule past the panel closing. */
  $effect(() => {
    const text = anweisungstext
    if (stiftAnweisung) clearTimeout(stiftAnweisung)
    if (text === null || !gespiegelt || text === diktat.anweisung) return
    /* A shipped text nobody moved is not an answer this panel gave. Storing
       it would turn the works text into a choice, and a later change of it
       would never reach anybody who once opened this panel. */
    if (!diktat.anweisung && text === werkAnweisung) return
    stiftAnweisung = setTimeout(() => sichern({ anweisung: text }), 600)
    return () => clearTimeout(stiftAnweisung)
  })
  $effect(() => {
    const text = putzanweisungstext
    if (stiftPutz) clearTimeout(stiftPutz)
    if (text === null || !gespiegelt || text === diktat.bereinigung_anweisung) return
    if (!diktat.bereinigung_anweisung && text === werkBereinigung) return
    stiftPutz = setTimeout(() => sichern({ bereinigung_anweisung: text }), 600)
    return () => clearTimeout(stiftPutz)
  })
  let stiftGespraech = null
  $effect(() => {
    const text = gespraechsanweisungstext
    if (stiftGespraech) clearTimeout(stiftGespraech)
    if (text === null || !gespiegelt || text === diktat.gespraechsanweisung) return
    if (!diktat.gespraechsanweisung && text === werkGespraechsanweisung) return
    stiftGespraech = setTimeout(() => sichern({ gespraechsanweisung: text }), 600)
    return () => clearTimeout(stiftGespraech)
  })

  /* The five generation values, written a beat after the hand stops — a
     slider dragged across the track would otherwise write every step it
     passes. Only the values that really moved are sent; a value nobody
     moved off the works one is not stored. */
  $effect(() => {
    const _ = JSON.stringify(stimmregler)
    if (!gespiegelt) return
    const uhr = setTimeout(() => {
      const nachtrag = {}
      for (const { knopf, schluessel } of PARAMETER) {
        const wert = stimmregler[knopf]
        if (wert === diktat[schluessel]) continue
        if (diktat[schluessel] === null && wert === werkStimm[knopf]) continue
        nachtrag[schluessel] = wert
      }
      if (!Object.keys(nachtrag).length) return
      werteSetzen(nachtrag).catch(() => {
        melde(t('fehler.einstellung_speichern'), 'fehler')
        // Back to what is stored: left standing, the value would differ
        // from the store again and the effect would retry for ever.
        stimmregler = {
          temperatur: diktat.stimmtemperatur ?? werkStimm.temperatur,
          top_k: diktat.stimmtop_k ?? werkStimm.top_k,
          top_p: diktat.stimmtop_p ?? werkStimm.top_p,
          min_p: diktat.stimmmin_p ?? werkStimm.min_p,
          strafe: diktat.stimmstrafe ?? werkStimm.strafe,
        }
      })
    }, 400)
    return () => clearTimeout(uhr)
  })

  /* The voice's layers and threads, the same beat and the same rule. Its
     own timer per value, like the instructions. */
  let stiftStimmSchichten = null
  $effect(() => {
    const wert = stimmSchichten
    if (stiftStimmSchichten) clearTimeout(stiftStimmSchichten)
    if (!gespiegelt || wert === diktat.stimmschichten) return
    if (diktat.stimmschichten === null && wert === werkSchichten) return
    stiftStimmSchichten = setTimeout(() => {
      werteSetzen({ stimmschichten: wert }).catch(() => {
        melde(t('fehler.einstellung_speichern'), 'fehler')
        stimmSchichten = diktat.stimmschichten ?? werkSchichten
      })
    }, 400)
    return () => clearTimeout(stiftStimmSchichten)
  })
  let stiftStimmFaeden = null
  $effect(() => {
    const wert = stimmFaeden
    if (stiftStimmFaeden) clearTimeout(stiftStimmFaeden)
    if (!gespiegelt || wert === diktat.stimmfaeden) return
    if (diktat.stimmfaeden === null && wert === werkFaeden) return
    stiftStimmFaeden = setTimeout(() => {
      werteSetzen({ stimmfaeden: wert }).catch(() => {
        melde(t('fehler.einstellung_speichern'), 'fehler')
        stimmFaeden = diktat.stimmfaeden ?? werkFaeden
      })
    }, 400)
    return () => clearTimeout(stiftStimmFaeden)
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

  /* The window's one deed, handed to the dictation group's head line — the
     button stands in the line of the first group of the right
     column, flush with the card below it, not up in the head card. */
  const tat = $derived({
    text: laeuft ? t('modell.server_anhalten') : t('modell.server_starten'),
    punkt: laeuft ? 'gruen' : 'still',
    gesperrt: arbeitet || (!laeuft && !bereit),
    onTat: schalten,
  })

  const modellauswahl = $derived(
    (auskunft?.modelle ?? []).map((m) => ({
      wert: m.name,
      text: `${m.name} · ${m.groesse_gb} GB`,
    })),
  )

  const stimmeauswahl = $derived([
    { wert: '', text: t('sprachserver.stimme_keine') },
    ...modellauswahl,
  ])

  const stimmprobeauswahl = $derived([
    { wert: '', text: t('sprachserver.stimme_keine') },
    ...(auskunft?.stimmproben ?? []).map((name) => ({ wert: name, text: name })),
  ])

  const stimmsprachauswahl = $derived([
    { wert: '', text: t('sprachserver.stimme_keine') },
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
  titel={t('sprachserver.titel')}
  zeichen="sprache_welle"
  unter={laeuft ? t('sprachserver.laeuft', { port: auskunft.port }) : ''}
  standfarbe={laeuft ? 'gruen' : 'still'}
  standtext={laeuft ? t('status.aktiv') : t('status.inaktiv')}
  modelle={modellauswahl}
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
        />
        <Serverregler kennung="sp" teil="netzwerk" gesperrt={laeuft} bind:port />
      {/snippet}
      {#snippet rechts()}
        <Serverabschnitt zeichen="sprache" titel={t('sprachserver.gruppe_diktat')}>
          {#snippet rechts()}
            <Startknopf text={tat.text} punkt={tat.punkt} gesperrt={tat.gesperrt} onTat={tat.onTat} />
          {/snippet}
          <div class="zeile">
            <label class="name" for="sp-diktatsprache">{t('sprachserver.feld_sprache')}</label>
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
            <label class="name" for="sp-anweisung">{t('sprachserver.feld_anweisung')}</label>
            <WachsendesFeld
              knapp
              zeilen={3}
              bind:wert={anweisungstext}
              beschriftung={anweisungsname}
            />
            <button class="stillknopf" aria-label={zuruecksetzenName(anweisungsname)}
                    onclick={() => (anweisungstext = werkAnweisung)}>
              {t('sprachserver.zuruecksetzen')}
            </button>
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
            <label class="name" for="sp-bereinigung">{t('sprachserver.feld_bereinigung')}</label>
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
            <label class="name" for="sp-putzanweisung">{t('sprachserver.feld_anweisung')}</label>
            <WachsendesFeld
              knapp
              zeilen={3}
              bind:wert={putzanweisungstext}
              beschriftung={putzanweisungsname}
            />
            <button class="stillknopf" aria-label={zuruecksetzenName(putzanweisungsname)}
                    onclick={() => (putzanweisungstext = werkBereinigung)}>
              {t('sprachserver.zuruecksetzen')}
            </button>
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
                eintraege={stimmeauswahl}
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
        />
      {/snippet}
      {#snippet rechts()}
        <Serverabschnitt zeichen="sprache_welle" titel={t('sprachserver.gruppe_gespraech')}>
          <div class="zeile niedrig">
            <span class="name">{t('sprachserver.feld_vorlesen')}</span>
            <Schalter
              id="sp-vorlesen"
              an={vorlesenwahl}
              beschriftung={t('sprachserver.feld_vorlesen')}
              onschalten={(neu) => { vorlesenwahl = neu; sichern({ vorlesen: neu }) }}
            />
          </div>
          <div class="zeile probezeile">
            <label class="name" for="sp-stimmprobe">{t('sprachserver.feld_stimmprobe')}</label>
            <div class="probewahl">
              <Auswahlfeld
                id="sp-stimmprobe"
                bind:wert={stimmprobewahl}
                eintraege={stimmprobeauswahl}
                beschriftung={t('sprachserver.feld_stimmprobe')}
                gewaehlt={(neu) => sichern({ stimmprobe: neu })}
              />
            </div>
            <button class="feldknopf" onclick={ordnerZeigen}>{t('sprachserver.ordner_zeigen')}</button>
          </div>
          <div class="zeile">
            <label class="name" for="sp-stimmsprache">{t('sprachserver.feld_stimmsprache')}</label>
            <div class="wahl">
              <Auswahlfeld
                id="sp-stimmsprache"
                bind:wert={stimmsprachwahl}
                eintraege={stimmsprachauswahl}
                beschriftung={t('sprachserver.feld_stimmsprache')}
                gewaehlt={(neu) => sichern({ stimmsprache: neu })}
              />
            </div>
          </div>
          <div class="zeile stapel">
            <label class="name" for="sp-gespraechsanweisung">{t('sprachserver.feld_gespraechsanweisung')}</label>
            <WachsendesFeld
              knapp
              zeilen={3}
              bind:wert={gespraechsanweisungstext}
              beschriftung={gespraechsanweisungsname}
            />
            <button class="stillknopf" aria-label={zuruecksetzenName(gespraechsanweisungsname)}
                    onclick={() => (gespraechsanweisungstext = werkGespraechsanweisung)}>
              {t('sprachserver.zuruecksetzen')}
            </button>
          </div>
        </Serverabschnitt>
      {/snippet}
    </Serverreihe>

    <Serverabschnitt titel={t('sprachserver.gruppe_parameter')}>
      {#each PARAMETER as p (p.knopf)}
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
              />
            </div>
          </div>
          <Schieberegler
            id="sp-{p.knopf}"
            bind:wert={stimmregler[p.knopf]}
            stufen={p.stufen}
            beschriftung={parameterlabels[p.knopf]}
            anzeige={(w) => anzeige(w, p.ganzzahlig, p.schritt)}
            mit_zahl={false}
            fuellung
          />
        </div>
      {/each}
    </Serverabschnitt>
  {/snippet}

  {#snippet unten()}
    <div class="log">
      <Serverlogkopf offen={protokollAuf} onumschalten={protokollKlappen}
                     onauskoppeln={() => oeffneProtokoll(t('modell.protokoll_titel'))} />
      {#if protokollAuf}
        <pre class="protokoll">{protokoll.join('\n') || '—'}</pre>
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
  /* The sample picker, 168 wide, and the button that opens its folder. */
  .probezeile {
    gap: 12px;
  }
  .probewahl {
    flex: none;
    width: 168px;
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
