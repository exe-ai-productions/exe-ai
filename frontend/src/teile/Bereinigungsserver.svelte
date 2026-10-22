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
     same log window every other server panel has. The page stands in rows
     of two columns: the model card beside the network, the advanced drawer
     over the full width, the memory beside the generation values. */
  import { api } from '../lib/api.js'
  import { pollWithoutOverlap } from '../lib/pollWithoutOverlap.js'
  import { t, texte } from '../lib/texte.svelte.js'
  import { fractionDigits, formatNumber } from '../lib/numberDisplay.js'
  import { entryMark, entrySize } from '../lib/modelEntry.js'
  import { serverAnteil } from '../lib/speicherschaetzung.js'
  import { katalogOeffnen, melde } from '../lib/zustand.svelte.js'
  import { diktat, schreibenAbwarten, standLaden, werteSetzen } from '../lib/diktat.svelte.js'
  import { createDelayedWriter } from '../lib/delayedWriter.js'
  import Servertafel from './Servertafel.svelte'
  import Serverreihe from './Serverreihe.svelte'
  import { serverHead } from '../lib/serverHead.svelte.js'
  import Serverregler from './Serverregler.svelte'
  import Startfehler from './Startfehler.svelte'
  import Serverabschnitt from './Serverabschnitt.svelte'
  import Serverlogkopf from './Serverlogkopf.svelte'
  import LlamaCppSection from './LlamaCppSection.svelte'
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

  /* What this page hands up to the page head (ModelleLokal.svelte), which draws
     it: the start button, the short line beside the name and the port. */
  let { head = $bindable(null) } = $props()

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
  // Minutes without a request after which the server frees its model; null is never.
  let idle = $state(null)
  let portGesetzt = false
  /* The server's own port, frozen when the field is filled. */
  let werkPort = 8085

  /* The file the panel's entry means, mirrored from the setting. */
  let putzwahl = $state('')

  /* The server's own numbers, mirrored the way the speech panel mirrors
     the voice's: the stored value while one is stored, the works answer
     otherwise. The works numbers are frozen once (`werkZahlen`) — the poll
     replaces `auskunft` every three seconds, and a value read from it while
     the hand is on a slider would move under it. */
  let regler = $state({ temperatur: 0, top_k: 0, top_p: 1, min_p: 0, strafe: 1 })
  let speicher = $state({ kontext: 2048, schichten: null, faeden: 0 })
  let werkZahlen = null
  let werkSpeicher = null
  let gespiegelt = false

  /* What a failed read reported last, so a failure that lasts is said once
     and not every few seconds; a read that gets through clears it, so the
     same failure returning later is news again. The answer before it stays
     on the page — a server shown as stopped because one read failed is a
     wrong picture, not a quiet one. */
  let letzterFehler = null

  async function laden() {
    try {
      auskunft = await api.bereinigungAuskunft()
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
     answers come from the setting, the works answers from the server. */
  $effect(() => {
    if (gespiegelt || !diktat.geladen || !auskunft) return
    const werk = auskunft.diktat_vorgaben ?? {}
    putzwahl = diktat.putzmodell || werk.putzmodell || putzwahl
    /* The port: what is stored, else what the server answers idle — and
       from now on the field is the hand's, the poll leaves it alone. */
    werkPort = auskunft.port ?? 8085
    if (!auskunft.laeuft) port = diktat.cleanup_port ?? werkPort
    idle = diktat.cleanup_idle_minutes ?? null
    portGesetzt = true
    werkZahlen = {
      temperatur: werk.putztemperatur,
      top_k: werk.putztop_k,
      top_p: werk.putztop_p,
      min_p: werk.putzmin_p,
      strafe: werk.putzstrafe,
    }
    werkSpeicher = {
      kontext: werk.putzkontext,
      schichten: werk.putzschichten ?? null,
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

  /* The port, written as it is touched; a value nobody moved off the
     server's own is not stored, and one that could not be stored goes back. */
  $effect(() => {
    const wert = port
    writer.cancel('port')
    if (!gespiegelt || auskunft?.laeuft) return
    const stand = diktat.cleanup_port
    if (wert === (stand ?? werkPort)) return
    writer.plan('port', () =>
      werteSetzen({ cleanup_port: wert }).catch(() => {
        melde(t('fehler.einstellung_speichern'), 'fehler')
        port = stand ?? werkPort
      }),
    )
  })

  /* The idle time, written as it is touched; empty and zero both mean never,
     and a value that could not be stored goes back to what is. */
  $effect(() => {
    const wert = idle
    writer.cancel('idle')
    if (!gespiegelt || auskunft?.laeuft) return
    const stand = diktat.cleanup_idle_minutes ?? null
    if ((wert || null) === stand || (!wert && stand === null)) return
    writer.plan('idle', () =>
      werteSetzen({ cleanup_idle_minutes: wert || null }).catch(() => {
        melde(t('fehler.einstellung_speichern'), 'fehler')
        idle = stand
      }),
    )
  })

  /* The five generation values, written a beat after the hand stops — a
     slider dragged across the track would otherwise write every step it
     passes. Only the values that really moved are sent. */
  $effect(() => {
    const _ = JSON.stringify(regler)
    if (!gespiegelt) return
    writer.plan('regler', () => {
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
      return werteSetzen(nachtrag).catch(() => {
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
    })
  })

  /* The memory numbers, the same beat and the same rule. Its own timer per
     value, and each keeps the works-answer guard: a value nobody moved is
     not stored. */
  $effect(() => {
    const wert = speicher.kontext
    writer.cancel('kontext')
    if (!gespiegelt || wert === diktat.putzkontext) return
    if (diktat.putzkontext === null && wert === werkSpeicher.kontext) return
    writer.plan('kontext', () =>
      werteSetzen({ putzkontext: wert }).catch(() => {
        melde(t('fehler.einstellung_speichern'), 'fehler')
        speicher.kontext = diktat.putzkontext ?? werkSpeicher.kontext
      }),
    )
  })
  $effect(() => {
    const wert = speicher.schichten
    writer.cancel('schichten')
    if (!gespiegelt || wert === diktat.putzschichten) return
    if (diktat.putzschichten === null && wert === werkSpeicher.schichten) return
    writer.plan('schichten', () =>
      werteSetzen({ putzschichten: wert }).catch(() => {
        melde(t('fehler.einstellung_speichern'), 'fehler')
        speicher.schichten = diktat.putzschichten ?? werkSpeicher.schichten
      }),
    )
  })
  $effect(() => {
    const wert = speicher.faeden
    writer.cancel('faeden')
    if (!gespiegelt || wert === diktat.putzfaeden) return
    if (diktat.putzfaeden === null && wert === werkSpeicher.faeden) return
    writer.plan('faeden', () =>
      werteSetzen({ putzfaeden: wert }).catch(() => {
        melde(t('fehler.einstellung_speichern'), 'fehler')
        speicher.faeden = diktat.putzfaeden ?? werkSpeicher.faeden
      }),
    )
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
      /* What was typed a moment ago is written before the start is asked:
         the server reads its numbers from what is stored. */
      await alleSichern()
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

  /* The server's one deed. The page head (ModelleLokal.svelte) draws its
     button; the page keeps what the button says and does. */
  const tat = $derived({
    text: laeuft ? t('modell.server_anhalten') : t('modell.server_starten'),
    punkt: laeuft ? 'gruen' : 'still',
    gesperrt: arbeitet || (!laeuft && !bereit),
    onTat: schalten,
  })

  serverHead('bereinigung', (value) => (head = value), () => ({
    tat, line: '', port: laeuft ? auskunft.port : null,
  }))

  /* The empty entry, like the model server's own: a cleaner somebody
     switches off entirely, and the panel's "bereinigt durch" then says by
     itself that no file stands behind it. Only while the folder actually
     holds models — an empty folder keeps the plain sentence and the way
     to the catalogue instead. */
  const modellauswahl = $derived([
    ...(auskunft?.modelle?.length ? [{ wert: '', text: t('bereinigungsserver.leer') }] : []),
    ...(auskunft?.modelle ?? []).map((m) => ({
      wert: m.name,
      text: `${m.name} · ${entrySize(m.groesse_gb)}`,
      ...entryMark(m.name),
    })),
  ])

  /* What the start of the chosen model is planned to take: its file and the
     context that is set. */
  const schaetzung = $derived(
    serverAnteil(auskunft?.modelle, [], { modell: putzwahl, kontext: speicher.kontext }),
  )

  function anzeige(zahl, ganzzahlig, schritt) {
    return ganzzahlig ? String(zahl) : formatNumber(zahl, fractionDigits(schritt), texte.sprache)
  }
</script>

<Servertafel
  modelle={modellauswahl}
  throughput="cleanup"
  bind:gewaehlt={putzwahl}
  modellBeschriftung={t('bereinigungsserver.modell')}
  modellGesperrt={laeuft}
  modellGeaendert={(neu) => sichern({ putzmodell: neu })}
  leerText={auskunft ? t('bereinigungsserver.kein_modell') : ''}
  katalogTat={() => katalogOeffnen('sprache')}
  speicherort="speech_models"
>
  {#snippet inhalt(modellkarte)}
    <Serverreihe>
      {#snippet links()}{@render modellkarte()}{/snippet}
      {#snippet rechts()}
        <Serverregler kennung="bs" teil="netzwerk" gesperrt={laeuft} bind:port />
      {/snippet}
    </Serverreihe>
    <Startfehler arch={auskunft?.unknown_architecture} />
    <Serverregler kennung="bs" teil="leerlauf" gesperrt={laeuft} bind:idle />
    <Serverreihe>
      {#snippet links()}
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
          {schaetzung}
        />
      {/snippet}
      {#snippet rechts()}
        <Serverabschnitt zeichen="settings_two" titel={t('sprachserver.gruppe_parameter')}>
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
                anzeige={(w) => anzeige(w, p.ganzzahlig, p.schritt)}
                mit_zahl={false}
                fuellung
              />
            </div>
          {/each}
        </Serverabschnitt>
      {/snippet}
    </Serverreihe>
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
