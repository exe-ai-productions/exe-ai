<script>
  import { kurz } from '../lib/tokenzahl.js'
  /* Local models: what runs on this machine, and how it is set — the local
     menu of the window row (ModelleSeite.svelte keeps its frame).

     The sections are the five servers, each with its state dot, and under
     them the quick picker; they stand in the sidebar while this menu is
     open (Menueseite hands them over). The page itself is what is chosen
     there, under the page head: the server (its form, its log, or the
     first-run steps) or the parameters of a model from the quick picker.
     The head carries the title, the facts of the machine and the one start
     button of whichever server is shown. */
  import Menueseite from './Menueseite.svelte'
  import Schalter from './Schalter.svelte'
  import Parametertafel from './Parametertafel.svelte'
  import Fensterkopf from './Fensterkopf.svelte'
  import Fenstertafel from './Fenstertafel.svelte'
  import Modellserver from './Modellserver.svelte'
  import Agentserver from './Agentserver.svelte'
  import Einbettungsserver from './Einbettungsserver.svelte'
  import Sprachserver from './Sprachserver.svelte'
  import Bereinigungsserver from './Bereinigungsserver.svelte'
  import Bildserver from './Bildserver.svelte'
  import Schriftzug from './Schriftzug.svelte'
  import Leuchtpunkt from './Leuchtpunkt.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import Menuezeile from './Menuezeile.svelte'
  import { api } from '../lib/api.js'
  import { t } from '../lib/texte.svelte.js'
  import { zustand } from '../lib/zustand.svelte.js'
  import { modellwahl, auswahlLaden, istAn, schalten, lokale } from '../lib/modelle.svelte.js'
  import { agentenmodell, HAUPTMODELL, SLOT_ENDPUNKT } from '../lib/agentenserver.svelte.js'
  import {
    gemerkteDatei,
    modulFuer,
    runnermodell,
    standLaden as runnermodellLaden,
  } from '../lib/runnermodell.svelte.js'
  import { serverAnteil } from '../lib/speicherschaetzung.js'

  /* `offen`: this menu is the one showing. The component stays mounted
     while it is not, so the chosen server survives a look at the cloud
     menu or at a chat; only its markup and its polling stop. */
  let { offen = false } = $props()

  /* Which the right half shows: the server, or a clicked model's
     parameters. Clicking left never changes what you are chatting with. */
  /* The kinds of server, each with its own row, its own folder and its
     own port. One entry for all of them was how an embedding model ended
     up in the language model's picker and its start ran against a port that
     was already taken. */
  const SERVER = 'server'
  /* The agent server, second in the list — right under the model server,
     because it is the other one that holds a chat model, and the two are
     read one after the other. */
  const AGENT = 'agent'
  const EINBETTUNG = 'einbettung'
  /* The speech server, between the embedding server and the picture one —
     it holds a model the same way the three above it do. */
  const SPRACHE = 'sprache'
  /* The clean-up server, right under the speech server: it is the small
     model that tidies what the speech server heard, and since it starts by
     hand it reads best beside the one it belongs to. */
  const BEREINIGUNG = 'bereinigung'
  const BILD = 'bild'
  let gezeigt = $state(SERVER)

  /* What the other servers' rows report. The panels behind them fetch for
     themselves and update live — a snapshot taken only at opening left
     the row saying "not running" while the panel next to it had long
     started the server. So the rows follow the same rhythm as the
     reachability loop instead of trusting one old glance. */
  /* The picture server's dot says whether sd-server runs — the same four
     states its own tile colours itself by; stopped draws none. */
  const BILDFARBE = { bereit: 'gruen', zeichnet: 'blau', fehler: 'rot' }
  let einbettungStand = $state(null)
  let spracheStand = $state(null)
  let bereinigungStand = $state(null)
  let bildStand = $state(null)
  let agentStand = $state(null)
  $effect(() => {
    if (!offen) return
    const holen = () => {
      api.einbettungAuskunft().then((a) => (einbettungStand = a)).catch(() => {})
      api.spracheAuskunft().then((a) => (spracheStand = a)).catch(() => {})
      api.bereinigungAuskunft().then((a) => (bereinigungStand = a)).catch(() => {})
      api.turboStand().then((a) => (bildStand = a)).catch(() => {})
      api.agentenmodellAuskunft().then((a) => (agentStand = a)).catch(() => {})
    }
    holen()
    const takt = setInterval(holen, 15_000)
    return () => clearInterval(takt)
  })

  /* The agent server's models have no group here: they are no model of the
     chat's choice, so there is nothing for a switch to switch. */
  const modelle = $derived(lokale().filter((m) => m.anbieter !== SLOT_ENDPUNKT))
  const modell = $derived(modelle.find((m) => m.id === gezeigt) ?? null)
  const anzahlAn = $derived(modelle.filter((m) => istAn(m.id)).length)
  const reise = $derived(modelle.length === 0)

  $effect(() => {
    if (!offen) return
    auswahlLaden()
  })


  /* The runner's report feeds the head and the server list: machine total,
     whether the server runs, on which port, with which speed module. */
  let auskunft = $state(null)
  const maschineGb = $derived(auskunft?.speicher_gb ?? null)
  const laeuft = $derived(Boolean(auskunft?.laeuft))

  /* --- What the next starts will take, both servers together --------------

     The model server and the agent server are two processes on two ports and
     nothing stops them being up at the same time — that is what the second
     one is FOR. The head said what one of them would take, whichever page
     happened to be open, so a pair that together bursts the machine looked
     fine from either side and the start was the first thing to say otherwise.

     What is counted: what a start would ADD. A file that is chosen but not
     started, plus the conversation it would hold. A server that is already
     running adds nothing here — what it holds is measured, and its own card
     says so in gigabytes; carrying it a second time in a figure labelled
     "expected" would count the same memory twice.

     Where each half comes from: from the page while it is open, live, so the
     head follows a slider under the hand; from the stored choice otherwise,
     because only one of the two pages is ever mounted (see the `{:else if}`
     below) and the half belonging to the closed one must not simply vanish.
     Both routes read the same numbers through the same function, so the
     figure does not change when the page does. */
  /* The one shape a measured share takes, wherever it is read from. `== null`
     rather than a plain falsy check — a server holding exactly 0.0 GB is
     still measured, and the house rule is explicit that zero is never the
     same as "not measured". */
  function gemessenerAnteil(gb) {
    return gb == null ? null : { gesamt: gb, gemessen: true }
  }
  function agentAnteilRuhe() {
    if (!agentStand) return null
    /* Running: what it actually holds, measured. Not nothing — see the note
       in Agentserver.svelte. The panel says the same thing while it is open;
       this is the reading for when it is not. */
    if (agentStand.laeuft) {
      return gemessenerAnteil(agentStand.belegt_gb)
    }
    if (!(agentenmodell.sorte === 'slot' && agentenmodell.wert)) {
      /* Nothing chosen, the main model, or somebody else's endpoint: no
         second process, so nothing to add. */
      return null
    }
    /* Exactly what the page puts into its own form (`werteUebernehmen`): the
       stored number, and where nothing was stored the slot's own fallback,
       sent along in its answer so there is one place that decides it. */
    const v = agentStand.vorgaben ?? {}
    return serverAnteil(agentStand.modelle, agentStand.mtp, {
      modell: agentenmodell.wert,
      kontext: agentenmodell.kontext ?? v.kontext,
      drafter: agentenmodell.drafter ?? v.drafter ?? '',
    })
  }
  function modellAnteilRuhe() {
    if (!auskunft) return null
    if (laeuft) {
      return gemessenerAnteil(auskunft.belegt_gb)
    }
    /* The same reading the server's own form does when it opens
       (Modellserver.svelte, `laden`): a running server first, then the model
       last started here if its file is still there, then the first in the
       list — and the module remembered for exactly that model, else the
       pairing the catalogue wrote down. The window comes from the same
       remembered key, with the same fallback. */
    const dateien = auskunft.modelle ?? []
    const modell = auskunft.modell || gemerkteDatei(dateien) || ''
    const modul = modulFuer(modell)
    return serverAnteil(dateien, auskunft.mtp, {
      /* The stored number, and where nothing was stored the server's own
         fallback — sent along in its answer (Stufe 11), so there is one place
         that decides it instead of a copy standing here as well. */
      modell,
      kontext: runnermodell.kontext ?? auskunft.vorgaben?.kontext,
      drafter:
        modul.drafter !== null ? modul.drafter : (auskunft.zuordnung?.[modell]?.mtp ?? ''),
    })
  }
  /* The speech and embedding servers carry no "next start" estimate — unlike
     the model and agent server, nothing here is chosen ahead of running it.
     A server that is not up adds nothing; one that is up counts with its
     measured share, same as the two above. */
  function spracheAnteilLaeuft() {
    return spracheStand?.laeuft ? gemessenerAnteil(spracheStand.belegt_gb) : null
  }
  /* The tidy-up server is a process of its own: its share is counted while
     it runs, and the answer carries no number when it does not. */
  function tidyUpShareRunning() {
    return gemessenerAnteil(spracheStand?.tidy_up_used_gb)
  }
  function einbettungAnteilLaeuft() {
    return einbettungStand?.laeuft ? gemessenerAnteil(einbettungStand.belegt_gb) : null
  }
  /* `zustand.serverPlan` is read first in both, so an open page wins and the
     resting reading is only asked for when there is no open page to ask. */
  const planTeile = $derived.by(() =>
    [
      zustand.serverPlan.modell ?? modellAnteilRuhe(),
      zustand.serverPlan.agent ?? agentAnteilRuhe(),
      spracheAnteilLaeuft(),
      tidyUpShareRunning(),
      einbettungAnteilLaeuft(),
    ].filter(Boolean),
  )
  const planGesamt = $derived(
    planTeile.length ? planTeile.reduce((summe, teil) => summe + teil.gesamt, 0) : null,
  )
  /* The ⌀ only belongs over a sum that guesses — once every part is a
     measurement of something actually running, the figure is not an average
     of anything anymore. */
  const geschaetzt = $derived(planTeile.some((teil) => !teil.gemessen))
  /* A fresh machine has nothing in the folder; a machine with files but no
     running server is a different, quieter state. The two get different
     words below. */
  const ordnerLeer = $derived((auskunft?.modelle?.length ?? 0) === 0)
  $effect(() => {
    if (!offen) return
    /* The resting figure below reads the stored start choice, which lives on
       the server since Stufe 11 — so it has to be in before the first frame
       that draws a number. */
    runnermodellLaden()
    const holen = () => api.runnerAuskunft().then((a) => (auskunft = a)).catch(() => {})
    holen()
    const takt = setInterval(holen, 3000)
    return () => clearInterval(takt)
  })

  /* The six servers of the left column, in their order: the model server
     first, the agent server right under it because it is the other one that
     holds a chat model, then embedding, speech with its clean-up beside it,
     and pictures. The dot is the state each one's own report gives, and
     only a server that runs (or failed) has one: six grey dots for six
     stopped servers said nothing the missing green does not. */
  const SERVERLISTE = $derived([
    { name: SERVER, titel: 'modell.server', zeichen: 'server', farbe: laeuft ? 'gruen' : null },
    { name: AGENT, titel: 'agentserver.titel', zeichen: 'agent', farbe: agentStand?.laeuft ? 'gruen' : null },
    {
      name: EINBETTUNG, titel: 'einbettungsserver.titel', zeichen: 'einbettung',
      farbe: einbettungStand?.laeuft ? 'gruen' : null,
    },
    {
      name: SPRACHE, titel: 'sprachserver.titel', zeichen: 'sprache_welle',
      farbe: spracheStand?.laeuft ? 'gruen' : null,
    },
    {
      name: BEREINIGUNG, titel: 'bereinigungsserver.titel', zeichen: 'besen',
      farbe: bereinigungStand?.laeuft ? 'gruen' : null,
    },
    { name: BILD, titel: 'bildserver.titel', zeichen: 'bild', farbe: BILDFARBE[bildStand?.zustand] ?? null },
  ])

  /* The quick picker, one group per server under its own heading: the model
     server first, any other local endpoint after it under its own name. The
     agent server has no group — its models are not offered to the chat, so
     there is nothing for a switch to switch. */
  const GRUPPENTITEL = { [HAUPTMODELL]: 'modell.server' }
  const RANG = { [HAUPTMODELL]: 0 }
  const gruppen = $derived.by(() => {
    const liste = []
    for (const m of modelle) {
      let gruppe = liste.find((g) => g.id === m.anbieter)
      if (!gruppe) {
        gruppe = { id: m.anbieter, name: m.anbieter_name || m.anbieter, modelle: [] }
        liste.push(gruppe)
      }
      gruppe.modelle.push(m)
    }
    return liste.sort((a, b) => (RANG[a.id] ?? 2) - (RANG[b.id] ?? 2))
  })

  const dialektName = (d) =>
    d === 'openai' ? t('modell.eigener_unter') : ({ llama_cpp: 'llama.cpp', mlx: 'MLX' }[d] ?? d)

</script>

{#if offen}
  <Menueseite beschriftung={t('menue.lokal')}>
    {#snippet liste()}
      <div class="menuegruppe">{t('modell.einrichten')}</div>
      {#each SERVERLISTE as eintrag (eintrag.name)}
        <Menuezeile
          titel={t(eintrag.titel)}
          punkt={eintrag.farbe}
          gewaehlt={gezeigt === eintrag.name}
          onclick={() => (gezeigt = eintrag.name)}
        >
          {#snippet zeichen()}<Hauszeichen zeichen={eintrag.zeichen} groesse="gross" />{/snippet}
        </Menuezeile>
      {/each}

      <div class="menuegruppe">{t('modell.schnellwahl_titel')}</div>
      {#if reise}
        <!-- A single dash while nothing is loaded: the heading already says
             what this place is for, and a sentence explaining the absence
             takes more room than the absence is worth. -->
        <p class="leerzeile" aria-label={t(ordnerLeer ? 'modell.kein_modell_satz' : 'modell.nichts_laeuft')}>—</p>
      {:else}
        {#each gruppen as gruppe (gruppe.id)}
          {@const titel = GRUPPENTITEL[gruppe.id] ? t(GRUPPENTITEL[gruppe.id]) : gruppe.name}
          <div class="servergruppe" role="group" aria-label={titel}>
            <div class="servertitel" aria-hidden="true">{titel}</div>
            {#each gruppe.modelle as m (m.id)}
              <!-- The row is two controls side by side, never one inside the
                   other: the name shows the model's parameters, the switch puts
                   it in or out of the picker. -->
              <div class="eintrag modell" class:gewaehlt={m.id === gezeigt}>
                <button class="modellknopf" onclick={() => (gezeigt = m.id)} aria-label={m.name}>
                  <Leuchtpunkt farbe={m.erreichbar ? 'gruen' : 'still'} groesse={11} />
                  <span class="mtext">
                    <span class="ename">{m.name}</span>
                    <span class="munter">
                      {#if m.context_tokens}{kurz(m.context_tokens)} ·{' '}{/if}{dialektName(m.dialekt)}
                    </span>
                  </span>
                </button>
                <Schalter an={istAn(m.id)} beschriftung={m.name} onschalten={(an) => schalten(m.id, an)} />
              </div>
            {/each}
          </div>
        {/each}
      {/if}
    {/snippet}

    {#snippet kopf()}
      <!-- The page head: what this tab is, what the machine has and holds.
           The start of whichever server is shown is not here — it stands in
           the window itself, in the line of its first group. -->
      <div class="titelblock">
        <div class="markenzeile" role="heading" aria-level="2" aria-label={t('menue.lokal')}>
          <svg viewBox="0 0 100 100" width="36" height="36" fill="none" stroke="currentColor"
               stroke-width="6.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <rect x="23.5" y="28.5" width="53" height="43" rx="11" />
            <path d="M34.7 42.2 L47.8 50 L34.7 57.8" />
            <path d="M51 57.5 H64.5" />
          </svg>
          <Schriftzug zug="lokale_modelle" hoehe={17} />
        </div>
        {#if !reise}
          <div class="zaehler">{t('modell.aktiv_zahl').replace('{zahl}', anzahlAn)}</div>
        {/if}
      </div>
      <!-- Three facts in one line of text: what the machine has, what the
           planned starts would take, and where the server answers. A dash
           for the port while nothing runs, so the line does not jump when a
           server comes up. -->
      <div class="aktionen">
        <div class="fakten">
          {#if maschineGb}
            <span>{t('modell.vram_label')}: {maschineGb} GB</span>
            <span class="trenner" aria-hidden="true">·</span>
          {/if}
          {#if planGesamt !== null}
            <span>{#if geschaetzt}<span class="mittel" aria-hidden="true">⌀</span>{/if}{t('modell.vram_erwartet')}: {planGesamt.toFixed(1)} GB</span>
            <span class="trenner" aria-hidden="true">·</span>
          {/if}
          <span>{t('kopf.port')}: {laeuft ? (auskunft?.port ?? '—') : '—'}</span>
        </div>
      </div>
    {/snippet}

    {#snippet inhalt()}
      {#if modell}
        <Fenstertafel>
          <Fensterkopf
            zeichen="paket"
            titel={modell.name}
            unter={(modell.context_tokens ? `${kurz(modell.context_tokens)} ${t('modell.kontext')} · ` : '')
              + dialektName(modell.dialekt)}
            standfarbe={modell.erreichbar ? 'gruen' : 'still'}
            standtext={modell.erreichbar ? t('status.erreichbar') : t('status.nicht_erreichbar')}
          />
          <!-- One line, and brightness only. The mismatch is a fact about
               this entry, not a state of the server — the server is
               answering perfectly well. Nothing is offered to fix it either:
               the configuration is the user's own file, and a program that
               edits it behind their back is worse than one that points at
               the mistake. -->
          {#if modell.dialekt_verdacht}
            <p class="verdachtszeile">{t('modell.dialekt_verdacht')}</p>
          {/if}
          <Parametertafel {modell} />
        </Fenstertafel>
      {:else if gezeigt === AGENT}
        <Agentserver />
      {:else if gezeigt === EINBETTUNG}
        <Einbettungsserver />
      {:else if gezeigt === SPRACHE}
        <Sprachserver />
      {:else if gezeigt === BEREINIGUNG}
        <Bereinigungsserver />
      {:else if gezeigt === BILD}
        <Bildserver />
      {:else}
        <Modellserver />
      {/if}
    {/snippet}
  </Menueseite>
{/if}

<style>

  /* One row of the column: the house's sidebar row — quiet at rest, a
     lighter ground under the hand, the filled ground when chosen. */
  .eintrag {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    box-sizing: border-box;
    min-height: var(--menuezeile);
    padding: 7px 10px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
    font: inherit;
    font-size: var(--schrift-text);
    text-align: left;
    cursor: pointer;
    transition: background 0.12s, color 0.12s;
  }
  .eintrag + .eintrag {
    margin-top: 2px;
  }
  .eintrag:hover {
    background: var(--bg-erhoben);
    color: var(--text);
  }
  .eintrag.gewaehlt {
    background: var(--bg-hoch);
    color: var(--text);
  }
  .ename {
    flex: 1;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  /* A quick-picker row holds its own switch, so the row itself is no
     button: the name part is. */
  .eintrag.modell {
    cursor: default;
    padding-right: 8px;
  }
  .modellknopf {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 0;
    border: none;
    background: none;
    color: inherit;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .mtext {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
  }
  .munter {
    font-size: 11.5px;
    color: var(--text-still);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  /* A server's heading inside the quick picker: quieter than the picker's
     own heading above it, on the rows' left edge. */
  .servertitel {
    padding: 8px 10px 2px;
    font-size: 11.5px;
    color: var(--text-still);
  }
  .leerzeile {
    font-size: 12px;
    color: var(--text-still);
    padding: 4px 10px 8px;
    line-height: 1.5;
  }

  .titelblock {
    flex: 1 1 260px;
    min-width: 0;
  }
  .markenzeile {
    display: flex;
    align-items: center;
    gap: 12px;
    color: var(--text);
  }
  .zaehler {
    font-size: 11.5px;
    color: var(--text-still);
    margin-top: 4px;
  }
  .aktionen {
    flex: none;
    display: flex;
    align-items: center;
    gap: 18px;
  }
  .fakten {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12.5px;
    color: var(--text-leise);
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }
  .trenner {
    color: var(--text-still);
  }
  /* The average sign is the whole difference between two readings, and at
     the text's size it reads as a smudge — it gets a step of its own. */
  .mittel {
    font-size: 15px;
    line-height: 1;
    margin-right: 2px;
  }

  /* No colour word anywhere in here. Yellow would read as "wait", red as
     "broken", and this is neither — it is a fact about the entry, which the
     house answers with brightness. */
  .verdachtszeile {
    margin: -16px 0 0;
    font-size: 11.5px;
    line-height: 1.5;
    color: var(--text-still);
  }

  @media (max-width: 720px) {
    .aktionen {
      flex-wrap: wrap;
    }
  }
</style>
