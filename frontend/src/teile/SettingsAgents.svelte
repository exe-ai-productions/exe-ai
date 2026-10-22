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
  import { serverLogo } from '../lib/serverlogo.svelte.js'
  import Agentenmarke from './Agentenmarke.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import Leuchtpunkt from './Leuchtpunkt.svelte'
  import Standpille from './Standpille.svelte'
  import Werkzeugzeichen from './Werkzeugzeichen.svelte'
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

  /* The sentence under an agent's name in the list: what it is for. */
  const purposes = $derived(new Map(agenten.map((a) => [a.name, a.description ?? ''])))
  const purposeOf = (name) => purposes.get(name) ?? ''

  /* Which server a tool belongs to and whether it is a built-in one, as the
     tools list says it. The name alone cannot: a server's tool is named
     `mcp__<server>__<tool>` with every odd character of the server's name
     turned into an underscore. */
  let toolInfo = $state(new Map())
  $effect(() => {
    api.werkzeuge()
      .then((antwort) => {
        toolInfo = new Map((antwort.werkzeuge ?? []).map((w) => [w.name, w]))
      })
      .catch(() => (toolInfo = new Map()))
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

<div class="agents-page">
<div class="zweispaltig">
  <div class="liste">
    <button class="zeile" class:gewaehlt={gewaehlt === SUBAGENTEN} onclick={() => (gewaehlt = SUBAGENTEN)}>
      <span class="marke"><Hauszeichen zeichen="branch" groesse={15} /></span>
      <span class="name">{t('agenten.subagenten')}</span>
      <span class="zahl">{helpersAtOnce.value ?? auto}</span>
    </button>

    <div class="gruppe"><span>{t('agenten.titel')}</span><i></i><span class="zahl">{dateien.length}</span></div>
    {#each dateien as eintrag (eintrag.name)}
      <button class="zeile" class:gewaehlt={gewaehlt === eintrag.name} onclick={() => (gewaehlt = eintrag.name)}>
        <span class="marke"><Agentenmarke groesse={18} /></span>
        <span class="mitte">
          <span class="name">{eintrag.name}</span>
          {#if purposeOf(eintrag.name)}
            <span class="unter" title={purposeOf(eintrag.name)}>{purposeOf(eintrag.name)}</span>
          {/if}
        </span>
        {#if eintrag.kaputt}<span class="punkt" title={eintrag.kaputt}><Leuchtpunkt farbe="rot" groesse={9} /></span>{/if}
      </button>
    {/each}
  </div>

  <div class="einzel">
    {#if gewaehlt === SUBAGENTEN}
      <div class="kopf">
        <span class="kasten"><Hauszeichen zeichen="branch" groesse={20} /></span>
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
          <button class="signbutton" onclick={() => onbearbeiten?.(agent ?? { name: datei.name })}
                  aria-label={t('agenten.bearbeiten')} title={t('agenten.bearbeiten')}>
            <Hauszeichen zeichen="stift" groesse={16} />
          </button>
          <button class="signbutton danger" onclick={() => onloeschen?.(datei.name)}
                  aria-label={t('agenten.loeschen')} title={t('agenten.loeschen')}>
            <Hauszeichen zeichen="trash" groesse={16} />
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
              <Standpille farbe="werkzeug">
                {@const info = toolInfo.get(werkzeug)}
                <span class="wzzeichen">
                  <Werkzeugzeichen name={werkzeug} server={info?.server ?? ''} eingebaut={info?.builtin ?? null}
                                   logo={info && !info.builtin ? serverLogo(info.server) : null} />
                </span>
                {werkzeug}
              </Standpille>
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
</div>

<style>
  /* The page asks for its own width, not the window's: it stands beside a
     bar whose width changes, so the window says little about the room it
     has. It takes the room the page leaves, like the grid inside it. */
  .agents-page {
    container: agents-page / inline-size;
    flex: 1 1 auto;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  /* Two columns: the list keeps its width, the chosen entry takes the rest. */
  .zweispaltig {
    display: grid;
    grid-template-columns: minmax(200px, 280px) 1fr;
    gap: 28px;
    align-items: stretch;
    /* As tall as the page leaves room, the list and the chosen agent each
       scrolling inside themselves: the page has no empty foot, and the
       instruction grows down to it. */
    flex: 1 1 auto;
    min-height: 0;
    grid-template-rows: minmax(0, 1fr);
  }
  :global(html[data-phone]) .kasten-text {
    flex: none;
    height: 320px;
    min-height: 0;
  }
  /* A fingertip is taller than a pointer. */
  :global(html[data-phone]) .signbutton {
    width: 44px;
    height: 44px;
  }
  .liste {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-height: 0;
    overflow-y: auto;
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
  /* The name over what the agent is for, the second line quiet and cut at
     the row's edge. */
  .mitte {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .mitte .unter {
    font-size: var(--schrift-hinweis);
    font-weight: 400;
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
    min-height: 0;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
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
  /* The pen and the bin: sign buttons of one size, the bin in the colour of
     deleting and nowhere else. */
  .knoepfe {
    flex: none;
    display: flex;
    gap: 8px;
  }
  .signbutton {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    color: var(--text);
    cursor: pointer;
    transition: background 0.12s;
  }
  .signbutton:hover {
    background: var(--glass-hover);
  }
  .signbutton.danger {
    color: var(--rot-text);
    background: color-mix(in srgb, var(--rot) 12%, var(--glass-button));
  }
  .signbutton.danger:hover {
    background: color-mix(in srgb, var(--rot) 18%, var(--glass-button));
  }

  /* The instruction is a block of its own height that scrolls inside
     itself, so a long prompt never stretches the page; the corner drags it
     taller. */
  .kasten-text {
    flex: 1 1 auto;
    min-height: 320px;
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
  /* Every mark of the pills in one box, whatever the mark draws. */
  .wzzeichen {
    --wz-groesse: 18px;
    flex: none;
    width: 18px;
    height: 18px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
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
  /* Narrow page: the chosen entry under the list. Written last, after the
     rules it overrides, so source order does not undo it. */
  @container agents-page (max-width: 640px) {
    .zweispaltig {
      grid-template-columns: 1fr;
      grid-template-rows: none;
      overflow-y: auto;
    }
    .liste,
    .einzel {
      overflow: visible;
    }
    /* Not tied to a page height any more: back to a box of its own height
       that scrolls inside itself, so a long prompt never stretches the page. */
    .kasten-text {
      flex: none;
      height: 320px;
      min-height: 0;
    }
  }
</style>
