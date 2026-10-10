<script>
  /* Settings › Agents: the list on the left, one entry in full on the right.

     The left column starts with "Subagents" — the two limits that hold for
     every helper an agent hands work to — and under it the agents, one row
     each, a broken file marked with a red dot as on the old list. The right
     column shows what is chosen: an agent with its instruction, its tools
     and its limits, read-only, with "Edit" opening the agent mask;
     or the two subagent limits as fields that save the way they always did.

     Nothing here writes an agent file. Editing and deleting go through the
     settings page that owns the editor (`onbearbeiten`, `onloeschen`), so
     there is one way to save an agent and one way to remove it. The two
     limits arrive as the page's own field objects (`countSetting` in
     SystemPrompt.svelte); binding to them saves exactly as before. */
  import { api } from '../lib/api.js'
  import { t } from '../lib/texte.svelte.js'
  import Agentenmarke from './Agentenmarke.svelte'
  import Leuchtpunkt from './Leuchtpunkt.svelte'
  import Standpille from './Standpille.svelte'
  import Zahlenfeld from './Zahlenfeld.svelte'

  let {
    dateien = [],
    helpersAtOnce,
    helperSteps,
    onbearbeiten,
    onloeschen,
  } = $props()

  /* The row standing for the subagent limits — never an agent's name, which
     the service only accepts as letters, digits, dash and underscore. */
  const SUBAGENTEN = ':subagents'

  let gewaehlt = $state('')
  let agenten = $state([])
  let prompt = $state('')

  /* The front matter of every agent, in one answer; reread whenever the
     file list changes (a save or a delete hands the page a new one). */
  $effect(() => {
    void dateien
    api.agenten()
      .then((liste) => (agenten = liste ?? []))
      .catch(() => (agenten = []))
  })

  /* The first agent is chosen when the page opens, and again when the
     chosen one is gone. */
  $effect(() => {
    if (gewaehlt === SUBAGENTEN) return
    if (dateien.some((d) => d.name === gewaehlt)) return
    gewaehlt = dateien[0]?.name ?? SUBAGENTEN
  })

  const datei = $derived(dateien.find((d) => d.name === gewaehlt) ?? null)
  const agent = $derived(agenten.find((a) => a.name === gewaehlt) ?? null)

  /* The instruction travels only with the single file, not with the list. */
  $effect(() => {
    const name = datei && !datei.kaputt ? datei.name : ''
    prompt = ''
    if (!name) return
    let verworfen = false
    api.agentDatei(name)
      .then((antwort) => {
        if (!verworfen) prompt = antwort.prompt ?? ''
      })
      .catch(() => {})
    return () => {
      verworfen = true
    }
  })

  const auto = $derived(t('parameter.auto'))
  const grenzen = $derived(
    agent
      ? [
          [t('agenten.max_runden'), agent.max_rounds],
          [t('agenten.max_minuten'), agent.max_minutes],
          [t('agenten.max_token'), agent.max_tokens],
          [t('agenten.max_befehlssekunden'), agent.max_command_seconds == null ? null : `${agent.max_command_seconds} s`],
        ]
      : [],
  )
</script>

<div class="zweispaltig">
  <div class="liste">
    <button class="zeile" class:gewaehlt={gewaehlt === SUBAGENTEN} onclick={() => (gewaehlt = SUBAGENTEN)}>
      <span class="marke">
        <!-- The branch sign of the house catalogue (static/zeichen), unchanged. -->
        <svg viewBox="0 0 64 64" width="15" height="15" fill="none" stroke="currentColor"
             stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M20 15 V49" stroke-width="5" /><path d="M20 32 H33 C39 32 44 27 44 21" stroke-width="4.5" />
          <circle cx="44" cy="16" r="4.5" stroke-width="4.5" />
        </svg>
      </span>
      <span class="name">{t('agenten.subagenten')}</span>
      <span class="zahl">{helpersAtOnce.value ?? auto}</span>
    </button>

    <div class="gruppe"><span>{t('agenten.titel')}</span><i></i><span class="zahl">{dateien.length}</span></div>
    {#each dateien as eintrag (eintrag.name)}
      <button class="zeile" class:gewaehlt={gewaehlt === eintrag.name} onclick={() => (gewaehlt = eintrag.name)}>
        <span class="marke"><Agentenmarke groesse={18} /></span>
        <span class="name">{eintrag.name}</span>
        {#if eintrag.kaputt}<span class="punkt" title={eintrag.kaputt}><Leuchtpunkt farbe="rot" groesse={9} /></span>{/if}
      </button>
    {/each}
  </div>

  <div class="einzel">
    {#if gewaehlt === SUBAGENTEN}
      <div class="kopf">
        <span class="kasten">
          <svg viewBox="0 0 64 64" width="20" height="20" fill="none" stroke="currentColor"
               stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M20 15 V49" stroke-width="5" /><path d="M20 32 H33 C39 32 44 27 44 21" stroke-width="4.5" />
            <circle cx="44" cy="16" r="4.5" stroke-width="4.5" />
          </svg>
        </span>
        <div class="titel"><strong>{t('agenten.subagenten')}</strong></div>
      </div>
      <div class="karte">
        <div class="feldzeile">
          <span>{t('editor.helpers_at_once')}</span>
          <div class="zahlfeld">
            <Zahlenfeld bind:wert={helpersAtOnce.value} min={1} ganzzahlig nullwort={t('parameter.auto')} />
          </div>
        </div>
        <div class="feldzeile">
          <span>{t('editor.helper_steps')}</span>
          <div class="zahlfeld">
            <Zahlenfeld bind:wert={helperSteps.value} min={1} ganzzahlig nullwort={t('parameter.auto')} />
          </div>
        </div>
      </div>
    {:else if datei}
      <div class="kopf">
        <span class="kasten"><Agentenmarke groesse={22} /></span>
        <div class="titel">
          <strong>{datei.name}</strong>
          {#if agent?.description}<span class="unter" title={agent.description}>{agent.description}</span>{/if}
        </div>
        <div class="knoepfe">
          <button class="knopf" onclick={() => onbearbeiten?.(agent ?? { name: datei.name })}>
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"
                 stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 3l4 4L8 20l-5 1 1-5L17 3z" /></svg>
            {t('skills.bearbeiten')}
          </button>
          <button class="knopf gefahr" onclick={() => onloeschen?.(datei.name)}>
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"
                 stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M3 6h18" /><path d="M8 6V4h8v2" /><path d="M6 6l1 14h10l1-14" />
            </svg>
            {t('jobs.loeschen')}
          </button>
        </div>
      </div>

      {#if datei.kaputt}
        <div class="warnung">{t('agenten.kaputt', { grund: datei.kaputt })}</div>
      {:else}
        <div class="abschnitt"><span>{t('agenten.anweisung')}</span><i></i></div>
        <div class="kasten-text">{prompt}</div>

        <div class="abschnitt"><span>{t('werkzeuge.titel')}</span><i></i></div>
        <div class="chips">
          {#if !agent}
            <!-- The front matter is still on its way: nothing rather than a
                 guess that might say "all tools". -->
          {:else if agent.tools == null}
            <span class="leise">{t('agenten.alle_werkzeuge')}</span>
          {:else if !agent.tools.length}
            <span class="leise">{t('agenten.keine_werkzeuge')}</span>
          {:else}
            {#each agent.tools as werkzeug (werkzeug)}
              <Standpille farbe="werkzeug">{werkzeug}</Standpille>
            {/each}
          {/if}
        </div>

        <div class="abschnitt"><span>{t('agenten.grenzen')}</span><i></i></div>
        <div class="karte raster">
          {#each grenzen as [name, wert] (name)}
            <div class="zelle">
              <span class="klein">{name}</span>
              <span>{wert ?? auto}</span>
            </div>
          {/each}
        </div>
      {/if}
    {/if}
  </div>
</div>

<style>
  /* Two columns: the list keeps its width, the chosen entry takes the rest. */
  .zweispaltig {
    display: grid;
    grid-template-columns: minmax(200px, 280px) 1fr;
    gap: 28px;
    align-items: start;
  }
  @media (max-width: 860px) {
    .zweispaltig {
      grid-template-columns: 1fr;
    }
  }
  .liste {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .zeile {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    min-height: 40px;
    padding: 6px 12px;
    box-sizing: border-box;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text);
    font: 400 var(--schrift-text) var(--schrift);
    text-align: left;
    cursor: pointer;
    transition: background 0.12s;
  }
  .zeile:hover {
    background: color-mix(in srgb, var(--text) 4%, transparent);
  }
  .zeile.gewaehlt {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    font-weight: 500;
  }
  .marke {
    width: 20px;
    flex: none;
    display: flex;
    justify-content: center;
    color: var(--text-leise);
  }
  .name {
    flex: 1;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .zahl {
    font-size: var(--schrift-hinweis);
    color: var(--text-still);
  }
  .punkt {
    display: inline-flex;
  }
  /* A group's head: its word, a hairline to the count. */
  .gruppe,
  .abschnitt {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .gruppe {
    margin: 14px 12px 4px;
    font: 500 var(--schrift-hinweis) var(--schrift);
    color: var(--text-still);
  }
  .gruppe i,
  .abschnitt i {
    flex: 1;
    border-top: 1px solid var(--linie);
  }
  .abschnitt {
    margin: 20px 0 10px;
    font: 600 var(--schrift-abschnitt) var(--schrift);
    color: var(--text);
  }

  .einzel {
    min-width: 0;
  }
  .kopf {
    display: flex;
    align-items: center;
    gap: 14px;
  }
  .kasten {
    width: 44px;
    height: 44px;
    flex: none;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 9px;
    background: var(--glass-card);
    color: var(--text);
  }
  .titel {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .titel strong {
    font-size: 17px;
    font-weight: 600;
  }
  .unter {
    font-size: var(--schrift-hinweis);
    color: var(--text-still);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  /* Side by side, one size: the wider label sets the width of both. */
  .knoepfe {
    flex: none;
    display: grid;
    grid-auto-columns: 1fr;
    grid-auto-flow: column;
    gap: 12px;
  }
  .knopf {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    min-width: 140px;
    height: 36px;
    padding: 0 16px;
    border: none;
    border-radius: 9px;
    background: var(--glass-card);
    color: var(--text);
    font: 500 13px var(--schrift);
    cursor: pointer;
    transition: background 0.12s;
  }
  .knopf:hover {
    background: color-mix(in srgb, var(--text) 8%, var(--glass-card));
  }
  .knopf.gefahr {
    color: var(--rot-text);
  }

  /* The instruction is a block of its own height that scrolls inside
     itself, so a long prompt never stretches the page; the corner drags it
     taller. */
  .kasten-text {
    height: 320px;
    overflow-y: auto;
    resize: vertical;
    padding: 14px 16px;
    border-radius: 9px;
    background: var(--glass-card);
    font-size: 13px;
    line-height: 1.6;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .leise {
    font-size: 13px;
    color: var(--text-still);
  }
  .karte {
    border-radius: 9px;
    background: var(--glass-card);
  }
  .feldzeile {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 10px 16px;
    font-size: 13px;
  }
  .feldzeile span {
    flex: 1;
  }
  .feldzeile + .feldzeile {
    border-top: 1px solid var(--linie);
  }
  .kopf + .karte {
    margin-top: 22px;
  }
  .zahlfeld {
    width: 108px;
    flex: none;
  }
  .raster {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    padding: 14px 16px;
  }
  .zelle {
    display: flex;
    flex-direction: column;
    gap: 3px;
    font-size: 14px;
  }
  .klein {
    font-size: var(--schrift-hinweis);
    color: var(--text-still);
  }
  .warnung {
    margin-top: 18px;
    border-radius: 9px;
    /* A state surface mixes its colour over the card glass. */
    background: color-mix(in srgb, var(--rot) 12%, var(--glass-card));
    color: var(--rot-text);
    font-size: 12.5px;
    line-height: 1.5;
    padding: 8px 12px;
  }
</style>
