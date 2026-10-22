<script>
  /* The house's log viewer: the server protocol shown large in a standard
     popup, in the same veil-and-frame the prompt dialog wears. Escape or a
     click on the veil closes it; nothing here acts, so there is only a
     close button.

     Drawn at the app root and fed from `protokollfenster.svelte.js`, because
     a fixed-position window rendered inside a scrolling window lands clipped
     and misplaced — the prompt dialog stands here for the same reason. */
  import { fade, scale } from 'svelte/transition'
  import { t } from '../lib/texte.svelte.js'
  import {
    protokollOffen,
    protokollZeilen,
    protokollTitel,
    schliesseProtokoll,
  } from '../lib/protokollfenster.svelte.js'

  let kasten = $state(null)

  // Keep the newest lines in view while the window is open.
  $effect(() => {
    if (!protokollOffen()) return
    void protokollZeilen()
    if (kasten) kasten.scrollTop = kasten.scrollHeight
  })

  function taste(ereignis) {
    if (protokollOffen() && ereignis.key === 'Escape') schliesseProtokoll()
  }
</script>

<svelte:window onkeydown={taste} />

{#if protokollOffen()}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="schleier" transition:fade={{ duration: 120 }} onclick={schliesseProtokoll}>
    <div
      class="popup"
      role="dialog"
      aria-modal="true"
      aria-label={protokollTitel()}
      transition:scale={{ start: 0.96, duration: 140 }}
      onclick={(e) => e.stopPropagation()}
    >
      <div class="kopf">{protokollTitel()}</div>
      <pre class="protokoll" bind:this={kasten}>{protokollZeilen().join('\n') || '-'}</pre>
      <div class="knoepfe">
        <button class="knopf wichtig" onclick={schliesseProtokoll}>{t('app.schliessen')}</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .schleier {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.45);
    z-index: 80;
    display: flex;
    justify-content: center;
    align-items: center;
    padding: 6vh 16px;
  }
  .popup {
    display: flex;
    flex-direction: column;
    /* A floating layer: the dense glass of the dropdown lists, blurred. */
    background: var(--glass-dropdown);
    -webkit-backdrop-filter: blur(16px);
    backdrop-filter: blur(16px);
    /* 9 — one radius for every edge in the program. A window is no
       different from the controls in it. */
    border-radius: 9px;
    padding: 16px 18px 14px;
    width: min(900px, 94vw);
    height: min(680px, 88vh);
    /* The glass edge as a ring ON the edge and a soft fall, the frame the
       main windows wear. */
    box-shadow: 0 0 0 1px var(--glass-button-edge), 0 28px 70px -12px rgba(0, 0, 0, 0.55);
  }
  /* On a narrow screen the window is the whole screen. */
  @media (max-width: 720px) {
    .schleier {
      padding: 0;
    }
    .popup {
      width: 100vw;
      height: 100dvh;
      border-radius: 0;
      padding: calc(16px + env(safe-area-inset-top)) 14px calc(14px + env(safe-area-inset-bottom));
    }
  }
  .kopf {
    flex: none;
    font-size: 13.5px;
    line-height: 1.55;
    color: var(--text);
  }
  .protokoll {
    flex: 1;
    min-height: 0;
    margin: 12px 0 0;
    padding: 12px 14px;
    background: var(--code-bg);
    border: 1px solid transparent;
    border-radius: 9px;
    font: 400 12px/1.6 var(--schrift-fest);
    color: var(--text-leise);
    overflow: auto;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .knoepfe {
    flex: none;
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    margin-top: 14px;
  }
  .knopf {
    /* Button glass with the field outline as a ring ON the edge; the main
       button beside it wears the glass edge and is told by its weight. */
    border: none;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    color: var(--text);
    font: inherit;
    font-size: 13px;
    padding: 7px 15px;
    border-radius: 9px;
    cursor: pointer;
    transition: background 0.12s, transform 0.08s;
  }
  .knopf:hover {
    background: var(--glass-hover);
  }
  .knopf:active {
    transform: scale(0.975);
  }
  /* The main button is button glass with its fine edge, like the start
     button; only Send stays filled. */
  .wichtig {
    background: var(--glass-button);
    color: var(--text);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    font-weight: 500;
  }
  .wichtig:hover {
    background: color-mix(in srgb, var(--text) 6%, var(--glass-button));
    font-weight: 500;
  }
</style>
