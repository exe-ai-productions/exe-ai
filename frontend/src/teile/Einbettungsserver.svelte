<script>
  /* The embedding server, switched from here.

     A sibling of the speech server's panel next door: the model card beside
     the llama.cpp section, under them a row of two columns — the storage
     numbers (the window, the layers on the graphics card, the CPU threads
     and what the start is planned to take of the wired memory) and the
     advanced levers (the pooling kind, the batch size, the memory lock, the
     parallel requests and the port) — then the log, open from the start and
     as tall as the window leaves room for. No draft model, no vision module,
     no experts and no conversation cache: it answers one text at a time
     with its vectors.

     Every value is kept as it is touched, in the row `embedding`
     (app/embedding_start_choice.py), read again when the window opens, and
     stands still while the server runs. Where the server is started from the
     window, it starts with what is stored.

     The state line says what a stopped server does — it loads the model on
     every question — because that is the one thing not obvious about it.
     Nothing breaks by leaving it off; somebody who does not know that reads
     a stopped server as a broken feature.

     The shape it stands in belongs to `Servertafel.svelte`, shared with
     the other server panels — this file only says what goes in it. */
  import { api } from '../lib/api.js'
  import { untrack } from 'svelte'
  import { t } from '../lib/texte.svelte.js'
  import { neuigkeit } from '../lib/ereignisstrom.svelte.js'
  import { katalogOeffnen, melde } from '../lib/zustand.svelte.js'
  import { createDelayedWriter } from '../lib/delayedWriter.js'
  import Servertafel from './Servertafel.svelte'
  import Serverreihe from './Serverreihe.svelte'
  import { serverHead } from '../lib/serverHead.svelte.js'
  import Serverregler from './Serverregler.svelte'
  import Startfehler from './Startfehler.svelte'
  import { fillToBottom } from '../lib/fillToBottom.js'
  import Serverlogkopf from './Serverlogkopf.svelte'
  import LlamaCppSection from './LlamaCppSection.svelte'
  import {
    protokollOffen,
    oeffneProtokoll,
    setzeProtokollZeilen,
  } from '../lib/protokollfenster.svelte.js'
  import { entryMark, entrySize } from '../lib/modelEntry.js'
  import { serverAnteil } from '../lib/speicherschaetzung.js'

  // The window's steps, and the most layers the track names.
  const kontextstufen = [2048, 4096, 8192, 16384, 32768]
  const MAX_SCHICHTEN = 99

  /* What this page hands up to the page head (ModelleLokal.svelte), which draws
     it: the start button, the short line beside the name and the port. */
  let { head = $bindable(null) } = $props()

  let auskunft = $state(null)
  let gewaehlt = $state('')
  let port = $state(8081)
  /* How the server runs, as stored: the window, the batch size (one number
     for the batch and the micro batch), the pooling kind ("" is the model's
     own), the layers (null: the engine places them), the CPU threads (0: the
     engine decides), the memory lock, the parallel requests (null: the
     engine picks its count) and the idle time in minutes (null: never). */
  let kontext = $state(2048)
  let batch = $state(2048)
  let pooling = $state('')
  let schichten = $state(null)
  let faeden = $state(0)
  let parallel = $state(null)
  let idle = $state(null)
  let fein = $state({ kv_cache: 'f16', moe_auf_cpu: false, festnageln: false })
  let arbeitet = $state(false)
  let protokoll = $state([])
  let protokollAuf = $state(true)

  // Keep the big log window fed while it is open.
  $effect(() => {
    if (protokollOffen()) setzeProtokollZeilen(protokoll)
  })

  /* What the idle server shows is what is stored for the next start (the
     answer says so), else the server's own. What the hand changes from there
     is written as it is touched — a beat after the last change, made at once
     when the window goes away and before "Start" — and only the values that
     changed, so a second window's change is not written over. */
  let ausgangsstand = null
  let werteGelesen = false
  const writer = createDelayedWriter(400)
  $effect(() => () => {
    writer.flush()
  })
  const stand = () => ({
    model: gewaehlt,
    port,
    context: kontext,
    batch,
    pooling,
    layers: schichten,
    threads: faeden,
    mlock: fein.festnageln,
    parallel,
    // An empty field and a zero both say never.
    idle_minutes: idle || null,
  })
  /* Puts the named values back to what they were (all of them where none is
     named): a write that failed takes back what it carried and not what was
     touched after it. */
  function uebernehmen(werte, namen = Object.keys(werte)) {
    const setzer = {
      model: (wert) => (gewaehlt = wert),
      port: (wert) => (port = wert),
      context: (wert) => (kontext = wert),
      batch: (wert) => (batch = wert),
      pooling: (wert) => (pooling = wert),
      layers: (wert) => (schichten = wert),
      threads: (wert) => (faeden = wert),
      mlock: (wert) => (fein.festnageln = wert),
      parallel: (wert) => (parallel = wert),
      idle_minutes: (wert) => (idle = wert),
    }
    for (const name of namen) setzer[name]?.(werte[name])
  }
  /* The batch is never larger than the window, as the service reads it: the
     field shows the smaller of the two and what is stored stays as it is, so
     a window raised again finds the batch it had. */
  const batchGezeigt = () => (kontext ? Math.min(batch, kontext) : batch)
  $effect(() => {
    const jetzt = stand()
    writer.cancel('embedding')
    if (!ausgangsstand || auskunft?.laeuft || !jetzt.model) return
    const geaendert = Object.fromEntries(
      Object.entries(jetzt).filter(([name, wert]) => wert !== ausgangsstand[name]),
    )
    if (!Object.keys(geaendert).length) return
    writer.plan('embedding', () =>
      api.einstellungMischen('global', 'embedding', geaendert).then(
        () => {
          ausgangsstand = { ...ausgangsstand, ...geaendert }
        },
        () => {
          melde(t('fehler.einstellung_speichern'), 'fehler')
          uebernehmen(ausgangsstand, Object.keys(geaendert))
        },
      ),
    )
  })

  /* What a failed read reported last, so a failure that lasts is said once
     and not every few seconds; a read that gets through clears it, so the
     same failure returning later is news again. The answer before it stays
     on the page — a server shown as stopped because one read failed is a
     wrong picture, not a quiet one. */
  let letzterFehler = null

  async function laden() {
    try {
      auskunft = await api.einbettungAuskunft()
      if (auskunft?.port) port = auskunft.port
      if (!gewaehlt || !auskunft.modelle.some((m) => m.name === gewaehlt)) {
        gewaehlt = auskunft.modell || auskunft.modelle[0]?.name || ''
      }
      /* The first answer sets the values the window shows, a running server
         included; the stand a change is measured against is taken once the
         server is idle. */
      if (!werteGelesen) {
        werteGelesen = true
        kontext = auskunft.context
        batch = auskunft.batch
        pooling = auskunft.pooling
        schichten = auskunft.layers ?? null
        faeden = auskunft.threads
        fein.festnageln = auskunft.mlock
        parallel = auskunft.parallel ?? null
        idle = auskunft.idle_minutes ?? null
      }
      if (!ausgangsstand && !auskunft.laeuft) ausgangsstand = stand()
      /* An open drawer is fed when this panel loads — it fetches on a
         change, not on a timer (unlike the other server windows), and the
         pop-out button fetches for itself below. A closed drawer costs no
         request at all. */
      if (protokollAuf || protokollOffen()) protokoll = await api.einbettungProtokoll()
      letzterFehler = null
    } catch (fehler) {
      if (fehler.message !== letzterFehler) melde(fehler.message, 'fehler')
      letzterFehler = fehler.message
    }
  }
  laden()

  /* This panel keeps no timer. Its server's own announcement is what makes
     it read again — a start that failed while nobody watched left its
     reason in the answer, and the page finds it there. */
  let gesehen = untrack(() => neuigkeit.einbettung)
  $effect(() => {
    const neu = neuigkeit.einbettung
    if (neu === gesehen) return
    gesehen = neu
    untrack(() => laden())
  })

  async function schalten() {
    if (arbeitet) return
    arbeitet = true
    try {
      await writer.flush()
      auskunft = auskunft?.laeuft
        ? await api.einbettungStoppen()
        : await api.einbettungStarten(gewaehlt, port)
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    } finally {
      arbeitet = false
    }
  }

  /* This panel has no timer of its own (the other server windows poll in
     two- and three-second beats); the log is fetched when somebody asks
     for it — opening the drawer, or opening the big window. */
  async function protokollZeigen() {
    protokollAuf = !protokollAuf
    if (!protokollAuf) return
    try {
      protokoll = await api.einbettungProtokoll()
    } catch {
      protokoll = []
    }
  }

  /* The pop-out window is fed from here, for the same reason: whoever
     opens it fetches the log at that very moment. */
  async function protokollAuskoppeln() {
    try {
      protokoll = await api.einbettungProtokoll()
    } catch {
      protokoll = []
    }
    oeffneProtokoll(t('modell.protokoll_titel'))
  }


  const laeuft = $derived(Boolean(auskunft?.laeuft))
  const bereit = $derived(Boolean(gewaehlt) && Boolean(auskunft?.programm))

  /* What the start is planned to take of the wired memory: the file chosen and
     the window that is set. */
  const schaetzung = $derived(
    serverAnteil(auskunft?.modelle, [], { modell: gewaehlt, kontext }),
  )

  const poolingauswahl = $derived([
    { wert: '', text: t('einbettungsserver.pooling_standard') },
    { wert: 'mean', text: t('einbettungsserver.pooling_mean') },
    { wert: 'cls', text: t('einbettungsserver.pooling_cls') },
    { wert: 'last', text: t('einbettungsserver.pooling_last') },
  ])

  const auswahl = $derived(
    (auskunft?.modelle ?? []).map((m) => ({
      wert: m.name,
      text: `${m.name} · ${entrySize(m.groesse_gb)}`,
      ...entryMark(m.name),
    })),
  )

  /* The server's one deed. The page head (ModelleLokal.svelte) draws its
     button; the page keeps what the button says and does. */
  const tat = $derived({
    text: laeuft ? t('modell.server_anhalten') : t('modell.server_starten'),
    punkt: laeuft ? 'gruen' : 'still',
    gesperrt: arbeitet || (!laeuft && !bereit),
    onTat: schalten,
  })

  serverHead('einbettung', (value) => (head = value), () => ({
    tat, line: '', port: laeuft ? auskunft.port : null,
  }))
</script>

<Servertafel
  modelle={auswahl}
  bind:gewaehlt
  modellBeschriftung={t('einbettungsserver.modell')}
  modellGesperrt={laeuft}
  leerText={auskunft ? t('einbettungsserver.kein_modell') : ''}
  katalogTat={() => katalogOeffnen('einbettung')}
  speicherort="embedding_models"
>
  {#snippet inhalt(modellkarte)}
    <Serverreihe>
      {#snippet links()}{@render modellkarte()}{/snippet}
      {#snippet rechts()}<LlamaCppSection {auskunft} onrefresh={laden} />{/snippet}
    </Serverreihe>
    <Startfehler arch={auskunft?.unknown_architecture} />
    <Serverreihe>
      {#snippet links()}
        <Serverregler
          kennung="es"
          teil="speicher"
          gesperrt={laeuft}
          moe={false}
          bind:kontext
          {kontextstufen}
          kontextMin={2048}
          kontextMax={32768}
          bind:schichten
          maxSchichten={MAX_SCHICHTEN}
          bind:faeden
          maxFaeden={auskunft?.kerne ?? 8}
          {schaetzung}
        />
      {/snippet}
      {#snippet rechts()}
        <Serverregler
          kennung="es"
          teil="fein"
          gesperrt={laeuft}
          kvZeilen={false}
          bind:pooling
          {poolingauswahl}
          bind:batch={batchGezeigt, (wert) => (batch = wert)}
          {kontext}
          bind:fein
          bind:parallel
          bind:idle
          bind:port
        />
      {/snippet}
    </Serverreihe>
  {/snippet}

  {#snippet unten()}
    <div class="log">
      <Serverlogkopf offen={protokollAuf} onumschalten={protokollZeigen}
                     onauskoppeln={protokollAuskoppeln} />
      {#if protokollAuf}
        <pre class="protokoll" use:fillToBottom>{protokoll.join('\n') || '-'}</pre>
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
    overflow: auto;
    white-space: pre-wrap;
  }
</style>
