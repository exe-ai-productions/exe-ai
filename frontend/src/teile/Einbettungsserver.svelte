<script>
  /* The embedding server, switched from here.

     Built as a small sibling of the model server's panel next door, not as
     a second version of it: this server has one setting — which model — and
     a form with a context size, a layer count and a draft model would be
     four fields pretending to matter.

     The state line says what a stopped server does — it loads the model on
     every question — because that is the one thing not obvious about it.
     Nothing breaks by leaving it off; somebody who does not know that reads
     a stopped server as a broken feature.

     The shape it stands in belongs to `Servertafel.svelte`, shared with
     the other server panels — this file only says what goes in it: the
     model card, the network section with the port, and the log at the
     foot. */
  import { api } from '../lib/api.js'
  import { untrack } from 'svelte'
  import { t } from '../lib/texte.svelte.js'
  import { neuigkeit } from '../lib/ereignisstrom.svelte.js'
  import { katalogOeffnen, melde } from '../lib/zustand.svelte.js'
  import { createDelayedWriter } from '../lib/delayedWriter.js'
  import Servertafel from './Servertafel.svelte'
  import Serverregler from './Serverregler.svelte'
  import Startknopf from './Startknopf.svelte'
  import Startfehler from './Startfehler.svelte'
  import Serverlogkopf from './Serverlogkopf.svelte'
  import LlamaCppSection from './LlamaCppSection.svelte'
  import {
    protokollOffen,
    oeffneProtokoll,
    setzeProtokollZeilen,
  } from '../lib/protokollfenster.svelte.js'

  let auskunft = $state(null)
  let gewaehlt = $state('')
  /* The one number this panel has. Deliberately the only one: passages are
     small and fixed, so a context slider here would be knowledge that is not
     knowledge. */
  let port = $state(8081)
  let arbeitet = $state(false)
  let protokoll = $state([])
  let protokollAuf = $state(false)

  // Keep the big log window fed while it is open.
  $effect(() => {
    if (protokollOffen()) setzeProtokollZeilen(protokoll)
  })

  /* The file and the port the idle server shows are what is stored for the
     next start (the answer says so), else the server's own. What the hand
     changes from there is written as it is touched — a beat after the last
     change, made at once when the window goes away and before "Start". */
  let ausgangsstand = null
  const writer = createDelayedWriter(400)
  $effect(() => () => {
    writer.flush()
  })
  $effect(() => {
    const jetzt = { model: gewaehlt, port }
    writer.cancel('embedding')
    if (!ausgangsstand || auskunft?.laeuft || !jetzt.model) return
    if (jetzt.model === ausgangsstand.model && jetzt.port === ausgangsstand.port) return
    writer.plan('embedding', () =>
      api.einstellungMischen('global', 'embedding', jetzt).then(
        () => {
          ausgangsstand = jetzt
        },
        () => {
          melde(t('fehler.einstellung_speichern'), 'fehler')
          gewaehlt = ausgangsstand.model
          port = ausgangsstand.port
        },
      ),
    )
  })

  async function laden() {
    try {
      auskunft = await api.einbettungAuskunft()
      if (auskunft?.port) port = auskunft.port
      if (!gewaehlt || !auskunft.modelle.some((m) => m.name === gewaehlt)) {
        gewaehlt = auskunft.modell || auskunft.modelle[0]?.name || ''
      }
      if (!ausgangsstand && !auskunft.laeuft) ausgangsstand = { model: gewaehlt, port }
      /* An open drawer is fed when this panel loads — it fetches on a
         change, not on a timer (unlike the other server windows), and the
         pop-out button fetches for itself below. A closed drawer costs no
         request at all. */
      if (protokollAuf || protokollOffen()) protokoll = await api.einbettungProtokoll()
    } catch {
      auskunft = null
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

  const auswahl = $derived(
    (auskunft?.modelle ?? []).map((m) => ({
      wert: m.name,
      text: `${m.name} · ${m.groesse_gb} GB`,
    })),
  )

  /* The window's one deed, handed to the network group's head line — the
     button stands in the line of the group, flush with the card
     below it, not up in the head card. */
  const tat = $derived({
    text: laeuft ? t('modell.server_anhalten') : t('modell.server_starten'),
    punkt: laeuft ? 'gruen' : 'still',
    gesperrt: arbeitet || (!laeuft && !bereit),
    onTat: schalten,
  })
</script>

<Servertafel
  titel={t('einbettungsserver.titel')}
  zeichen="einbettung"
  unter={laeuft ? t('einbettungsserver.laeuft', { port: auskunft.port }) : t('einbettungsserver.aus')}
  standfarbe={laeuft ? 'gruen' : 'still'}
  standtext={laeuft ? t('status.aktiv') : t('status.inaktiv')}
  modelle={auswahl}
  bind:gewaehlt
  modellBeschriftung={t('einbettungsserver.modell')}
  modellGesperrt={laeuft}
  leerText={auskunft ? t('einbettungsserver.kein_modell') : ''}
  katalogTat={() => katalogOeffnen('einbettung')}
  speicherort="embedding_models"
>
  {#snippet mitte()}
    <Startfehler arch={auskunft?.unknown_architecture} />
    <Serverregler kennung="es" teil="netzwerk" gesperrt={laeuft} bind:port>
      {#snippet kopfrechts()}
        <Startknopf text={tat.text} punkt={tat.punkt} gesperrt={tat.gesperrt} onTat={tat.onTat} />
      {/snippet}
    </Serverregler>
    <LlamaCppSection {auskunft} onrefresh={laden} />
  {/snippet}

  {#snippet unten()}
    <div class="log">
      <Serverlogkopf offen={protokollAuf} onumschalten={protokollZeigen}
                     onauskoppeln={protokollAuskoppeln} />
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
