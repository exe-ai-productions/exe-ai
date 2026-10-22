<script>
  /* One row of the chat list: the title, the door to the row's menu and,
     last, the dot that says what the conversation is doing — a question
     standing, an answer running, a run that fell over, an answer nobody has
     opened. A row with nothing to report shows no dot, and its box stays, so
     the titles do not shift.

     Two controls side by side and not one inside the other: the title opens
     the chat, the three dots open its menu. */
  import Leuchtpunkt from '../teile/Leuchtpunkt.svelte'
  import { t } from '../lib/texte.svelte.js'
  import { zustand } from '../lib/zustand.svelte.js'
  import { ringFarbe } from '../lib/chatringe.svelte.js'
  import { punktAtmet } from '../lib/meldewesen.svelte.js'

  const STATES = {
    gelb: 'chat.wartet_auf_dich',
    blau: 'chat.laeuft_gerade',
    rot: 'chat.lauf_gescheitert',
    gruen: 'chat.antwort_fertig',
  }

  /* `nested` indents the row under the project it lies in. */
  let { chat, open, more, nested = false } = $props()

  const color = $derived(ringFarbe(chat.id))
  const stateText = $derived(STATES[color] ? t(STATES[color]) : '')
</script>

<div class="row" class:active={chat.id === zustand.aktiverChat} class:nested>
  <button class="title" onclick={() => open(chat.id)}>{chat.title}</button>
  <button class="more" onclick={() => more(chat)} title={t('app.mehr')} aria-label={t('app.mehr')}>
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <circle cx="5" cy="12" r="1.7" /><circle cx="12" cy="12" r="1.7" /><circle cx="19" cy="12" r="1.7" />
    </svg>
  </button>
  <span class="dot" title={stateText || null} aria-label={stateText || null}>
    {#if stateText}
      <Leuchtpunkt farbe={color} groesse={11} atmet={punktAtmet('chat', color)} />
    {/if}
  </span>
</div>

<style>
  .row {
    display: flex;
    align-items: center;
    min-height: 44px;
    border-radius: 9px;
    color: var(--text-leise);
  }
  /* The chosen row wears glass with a fine edge, inset so the row keeps its
     height. */
  .row.active {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
  }
  .row.nested {
    padding-left: 24px;
  }
  .title {
    flex: 1;
    min-width: 0;
    align-self: stretch;
    padding: 0 6px 0 10px;
    border: none;
    background: none;
    color: inherit;
    font: inherit;
    font-size: var(--schrift-text);
    text-align: left;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .more {
    flex: none;
    display: grid;
    place-items: center;
    width: 36px;
    height: 36px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-still);
  }
  .more:active {
    background: var(--bg-hoch);
    color: var(--text);
  }
  .dot {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 14px;
    height: 14px;
    margin: 0 10px 0 2px;
  }
</style>
