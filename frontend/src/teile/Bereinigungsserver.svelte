<script>
  /* The clean-up server, switched and set from here.

     Its own window beside the speech server's: the
     one that hears and the one that tidies are two processes with two
     lives, and one button starting both was exactly how a failure of one
     read as a failure of the other. So this window starts and stops its
     own server, by hand, and the speech panel only ever names it.

     The model card carries the file the panel's "bereinigt durch" entry
     means — the same setting, written from here now. The memory and the
     five generation values are settings the start reads; a value stored
     here is what the next start runs with, and the log at the foot is the
     same log window every other server panel has. */
  import { api } from '../lib/api.js'
  import { t } from '../lib/texte.svelte.js'
  import { katalogOeffnen, melde } from '../lib/zustand.svelte.js'
  import { diktat, standLaden, werteSetzen } from '../lib/diktat.svelte.js'
  import Servertafel from './Servertafel.svelte'
  import Serverregler from './Serverregler.svelte'
  import Startknopf from './Startknopf.svelte'
  import Serverabschnitt from './Serverabschnitt.svelte'
  import Serverlogkopf from './Serverlogkopf.svelte'
  import Schieberegler from './Schieberegler.svelte'
  import Zahlenfeld from './Zahlenfeld.svelte'
  import {
    protokollOffen,
    oeffneProtokoll,
    setzeProtokollZeilen,
  } from '../lib/protokollfenster.svelte.js'

  const kontextstufen = [2048, 4096, 8192, 16384, 32768]
  const MAX_SCHICHTEN = 99

  /* The five generation values as stepped lists, in the house's ranges
     (app/parameter.py) — the same shape the speech panel's parameter card
     has, and the same reason: a value the service would clamp is not a
     value worth offering. */
  const STUFEN = {
    temperatur: Array.from({ length: 41 }, (_, i) => Math.round(i * 5) / 100),
    top_k: Array.from({ length: 201 }, (_, i) => i),
    top_p: Array.from({ length: 101 }, (_, i) => i / 100),
    min_p: Array.from({ length: 101 }, (_, i) => i / 100),
    strafe: Array.from({ length: 101 }, (_, i) => (100 + i) / 100),
  }

  const PARAMETER = [
    { knopf: 'temperatur', schluessel: 'putztemperatur',
      stufen: STUFEN.temperatur, min: 0, max: 2, schritt: 0.05, ganzzahlig: false },
    { knopf: 'top_k', schluessel: 'putztop_k',
      stufen: STUFEN.top_k, min: 0, max: 200, schritt: 1, ganzzahlig: true },
    { knopf: 'top_p', schluessel: 'putztop_p',
      stufen: STUFEN.top_p, min: 0, max: 1, schritt: 0.01, ganzzahlig: false },
    { knopf: 'min_p', schluessel: 'putzmin_p',
      stufen: STUFEN.min_p, min: 0, max: 1, schritt: 0.01, ganzzahlig: false },
    { knopf: 'strafe', schluessel: 'putzstrafe',
      stufen: STUFEN.strafe, min: 1, max: 2, schritt: 0.01, ganzzahlig: false },
  ]

  /* The five labels, each fetched by its full key — the row loop below
     reads them by knob name. The same five words the speech panel's own
     parameter card carries. */
  const parameterlabels = $derived({
    temperatur: t('sprachserver.feld_temperatur'),
    top_k: t('sprachserver.feld_top_k'),
    top_p: t('sprachserver.feld_top_p'),
    min_p: t('sprachserver.feld_min_p'),
    strafe: t('sprachserver.feld_strafe'),
  })

  let auskunft = $state(null)
  let arbeitet = $state(false)
  let protokoll = $state([])
  let protokollAuf = $state(false)

  // Keep the big log window fed while it is open.
  $effect(() => {
    if (protokollOffen()) setzeProtokollZeilen(protokoll)
  })

  /* The one number this panel has, held in the page and sent with the
     start, the way the embedding panel holds its port. Taken from the
     server once, then left alone: every poll would otherwise put the
     default back over a number somebody just typed. */
  let port = $state(8085)
  let portGesetzt = false

  /* The file the panel's entry means, mirrored from the setting. */
  let putzwahl = $state('')

  /* The server's own numbers, mirrored the way the speech panel mirrors
     the voice's: the stored value while one is stored, the works answer
     otherwise. The works numbers are frozen once (`werkZahlen`) — the poll
     replaces `auskunft` every three seconds, and a value read from it while
     the hand is on a slider would move under it. */
  let regler = $state({ temperatur: 0, top_k: 0, top_p: 1, min_p: 0, strafe: 1 })
  let speicher = $state({ kontext: 2048, schichten: MAX_SCHICHTEN, faeden: 0 })
  let werkZahlen = null
  let werkSpeicher = null
  let gespiegelt = false

  async function laden() {
    try {
      auskunft = await api.bereinigungAuskunft()
    } catch {
      auskunft = null
      return
    }
    if (!portGesetzt && auskunft?.port) {
      port = auskunft.port
      portGesetzt = true
    }
    /* The field follows the setting (the mirror below); the run's own file
       only fills it while nothing is chosen, or when the chosen file has
       gone from the folder. An empty choice is a real answer here — "no
       cleaner chosen" — and is never overwritten by a default. */
    if (!putzwahl && auskunft.laeuft && auskunft.modell) {
      putzwahl = auskunft.modell
    } else if (putzwahl && !auskunft.modelle.some((m) => m.name === putzwahl)) {
      putzwahl = auskunft.laeuft ? (auskunft.modell ?? '') : ''
    }
    if (protokollAuf || protokollOffen()) {
      protokoll = await api.bereinigungProtokoll()
    }
  }

  $effect(() => {
    standLaden()
    laden()
    const takt = setInterval(laden, 3000)
    return () => clearInterval(takt)
  })

  /* Both halves have to be in before the fields can be filled: the stored
     answers come from the setting, the works answers from the server. */
  $effect(() => {
    if (gespiegelt || !diktat.geladen || !auskunft) return
    const werk = auskunft.diktat_vorgaben ?? {}
    putzwahl = diktat.putzmodell || werk.putzmodell || putzwahl
    werkZahlen = {
      temperatur: werk.putztemperatur,
      top_k: werk.putztop_k,
      top_p: werk.putztop_p,
      min_p: werk.putzmin_p,
      strafe: werk.putzstrafe,
    }
    werkSpeicher = {
      kontext: werk.putzkontext,
      schichten: werk.putzschichten,
      faeden: werk.putzfaeden,
    }
    regler = {
      temperatur: diktat.putztemperatur ?? werkZahlen.temperatur,
      top_k: diktat.putztop_k ?? werkZahlen.top_k,
      top_p: diktat.putztop_p ?? werkZahlen.top_p,
      min_p: diktat.putzmin_p ?? werkZahlen.min_p,
      strafe: diktat.putzstrafe ?? werkZahlen.strafe,
    }
    speicher = {
      kontext: diktat.putzkontext ?? werkSpeicher.kontext,
      schichten: diktat.putzschichten ?? werkSpeicher.schichten,
      faeden: diktat.putzfaeden ?? werkSpeicher.faeden,
    }
    gespiegelt = true
  })

  function sichern(werte) {
    werteSetzen(werte).catch(() => melde(t('fehler.einstellung_speichern'), 'fehler'))
  }

  /* The five generation values, written a beat after the hand stops — a
     slider dragged across the track would otherwise write every step it
     passes. Only the values that really moved are sent. */
  $effect(() => {
    const _ = JSON.stringify(regler)
    if (!gespiegelt) return
    const uhr = setTimeout(() => {
      const nachtrag = {}
      for (const { knopf, schluessel } of PARAMETER) {
        const wert = regler[knopf]
        if (wert === diktat[schluessel]) continue
        /* A works value nobody moved is not an answer this panel gave.
           Storing it would freeze the shipped value into a choice, and a
           later change of it would never reach anybody who once opened
           this window. */
        if (diktat[schluessel] === null && wert === werkZahlen[knopf]) continue
        nachtrag[schluessel] = wert
      }
      if (!Object.keys(nachtrag).length) return
      werteSetzen(nachtrag).catch(() => {
        melde(t('fehler.einstellung_speichern'), 'fehler')
        // Back to what is stored: left standing, the value would differ
        // from the store again and the effect would retry for ever.
        regler = {
          temperatur: diktat.putztemperatur ?? werkZahlen.temperatur,
          top_k: diktat.putztop_k ?? werkZahlen.top_k,
          top_p: diktat.putztop_p ?? werkZahlen.top_p,
          min_p: diktat.putzmin_p ?? werkZahlen.min_p,
          strafe: diktat.putzstrafe ?? werkZahlen.strafe,
        }
      })
    }, 400)
    return () => clearTimeout(uhr)
  })

  /* The memory numbers, the same beat and the same rule. Its own timer per
     value, and each keeps the works-answer guard: a value nobody moved is
     not stored. */
  let stiftKontext = null
  $effect(() => {
    const wert = speicher.kontext
    if (stiftKontext) clearTimeout(stiftKontext)
    if (!gespiegelt || wert === diktat.putzkontext) return
    if (diktat.putzkontext === null && wert === werkSpeicher.kontext) return
    stiftKontext = setTimeout(() => {
      werteSetzen({ putzkontext: wert }).catch(() => {
        melde(t('fehler.einstellung_speichern'), 'fehler')
        speicher.kontext = diktat.putzkontext ?? werkSpeicher.kontext
      })
    }, 400)
    return () => clearTimeout(stiftKontext)
  })
  let stiftSchichten = null
  $effect(() => {
    const wert = speicher.schichten
    if (stiftSchichten) clearTimeout(stiftSchichten)
    if (!gespiegelt || wert === diktat.putzschichten) return
    if (diktat.putzschichten === null && wert === werkSpeicher.schichten) return
    stiftSchichten = setTimeout(() => {
      werteSetzen({ putzschichten: wert }).catch(() => {
        melde(t('fehler.einstellung_speichern'), 'fehler')
        speicher.schichten = diktat.putzschichten ?? werkSpeicher.schichten
      })
    }, 400)
    return () => clearTimeout(stiftSchichten)
  })
  let stiftFaeden = null
  $effect(() => {
    const wert = speicher.faeden
    if (stiftFaeden) clearTimeout(stiftFaeden)
    if (!gespiegelt || wert === diktat.putzfaeden) return
    if (diktat.putzfaeden === null && wert === werkSpeicher.faeden) return
    stiftFaeden = setTimeout(() => {
      werteSetzen({ putzfaeden: wert }).catch(() => {
        melde(t('fehler.einstellung_speichern'), 'fehler')
        speicher.faeden = diktat.putzfaeden ?? werkSpeicher.faeden
      })
    }, 400)
    return () => clearTimeout(stiftFaeden)
  })

  /* The log is read when it is asked for — opening the drawer fetches it
     at once, and only an open drawer or the big log window keeps it fed.
     Nothing runs on a timer for a drawer nobody opened. */
  async function protokollKlappen() {
    protokollAuf = !protokollAuf
    if (!protokollAuf) return
    try {
      protokoll = await api.bereinigungProtokoll()
    } catch {
      protokoll = []
    }
  }

  async function schalten() {
    if (arbeitet) return
    arbeitet = true
    try {
      auskunft = auskunft?.laeuft
        ? await api.bereinigungStoppen()
        : await api.bereinigungStarten(putzwahl, port)
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    } finally {
      arbeitet = false
    }
  }

  const laeuft = $derived(Boolean(auskunft?.laeuft))
  const bereit = $derived(Boolean(putzwahl) && Boolean(auskunft?.programm))

  /* The window's one deed, handed to the network group's head line — the
     button stands in the line of the group, flush with the card
     below it, not up in the head card. */
  const tat = $derived({
    text: laeuft ? t('modell.server_anhalten') : t('modell.server_starten'),
    punkt: laeuft ? 'gruen' : 'still',
    gesperrt: arbeitet || (!laeuft && !bereit),
    onTat: schalten,
  })

  /* The empty entry, like the model server's own: a cleaner somebody
     switches off entirely, and the panel's "bereinigt durch" then says by
     itself that no file stands behind it. Only while the folder actually
     holds models — an empty folder keeps the plain sentence and the way
     to the catalogue instead. */
  const modellauswahl = $derived([
    ...(auskunft?.modelle?.length ? [{ wert: '', text: t('bereinigungsserver.leer') }] : []),
    ...(auskunft?.modelle ?? []).map((m) => ({
      wert: m.name,
      text: `${m.name} · ${m.groesse_gb} GB`,
    })),
  ])

  function anzeige(zahl, ganzzahlig) {
    return ganzzahlig ? String(zahl) : Number(zahl).toFixed(2)
  }
</script>

<Servertafel
  titel={t('bereinigungsserver.titel')}
  zeichen="besen"
  standfarbe={laeuft ? 'gruen' : 'still'}
  standtext={laeuft ? t('status.aktiv') : t('status.inaktiv')}
  modelle={modellauswahl}
  bind:gewaehlt={putzwahl}
  modellBeschriftung={t('bereinigungsserver.modell')}
  modellGesperrt={laeuft}
  modellGeaendert={(neu) => sichern({ putzmodell: neu })}
  leerText={auskunft ? t('bereinigungsserver.kein_modell') : ''}
  katalogTat={() => katalogOeffnen('sprache')}
  speicherort="speech_models"
>
  {#snippet mitte()}
    <!-- One column: network with the window's one
         deed, storage and the sampling values across the full width. -->
    <Serverregler kennung="bs" teil="netzwerk" gesperrt={laeuft} bind:port>
      {#snippet kopfrechts()}
        <Startknopf text={tat.text} punkt={tat.punkt} gesperrt={tat.gesperrt} onTat={tat.onTat} />
      {/snippet}
    </Serverregler>

    <Serverregler
      kennung="bs"
      teil="speicher"
      gesperrt={laeuft}
      moe={false}
      bind:kontext={speicher.kontext}
      {kontextstufen}
      bind:schichten={speicher.schichten}
      maxSchichten={MAX_SCHICHTEN}
      bind:faeden={speicher.faeden}
      maxFaeden={auskunft?.kerne ?? 8}
    />

    <Serverabschnitt titel={t('sprachserver.gruppe_parameter')}>
      {#each PARAMETER as p (p.knopf)}
        <div class="zeile regel">
          <div class="kopfzeile">
            <label class="regelname" for="bs-{p.knopf}">{parameterlabels[p.knopf]}</label>
            <div class="zahlplatz">
              <Zahlenfeld
                bind:wert={regler[p.knopf]}
                gesperrt={laeuft}
                min={p.min}
                max={p.max}
                schritt={p.schritt}
                ganzzahlig={p.ganzzahlig}
              />
            </div>
          </div>
          <Schieberegler
            id="bs-{p.knopf}"
            bind:wert={regler[p.knopf]}
            stufen={p.stufen}
            gesperrt={laeuft}
            beschriftung={parameterlabels[p.knopf]}
            anzeige={(w) => anzeige(w, p.ganzzahlig)}
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
