<script>
  /* The house's prompt dialog: replaces the bare
     confirm()/prompt() boxes of the browser — those were the last
     foreign body in the interface.

     Two shapes, one component: question only (yes/no) or question with
     an input field (renaming). Answering runs through frageBeantworten —
     that resolves the promise from zustand.frage(). Escape and a click
     on the veil mean no, Enter means yes.

     Lies ABOVE the windows (z-index 80 against their 70): most prompts
     arise in the middle of the settings window. */
  import { fade, scale } from 'svelte/transition'
  import { zustand, frageBeantworten } from '../lib/zustand.svelte.js'
  import { t } from '../lib/texte.svelte.js'

  let eingabefeld = $state(null)
  let okKnopf = $state(null)
  let wert = $state('')

  const mitEingabe = $derived(zustand.frage?.eingabe != null)

  $effect(() => {
    if (!zustand.frage) return
    wert = zustand.frage.eingabe ?? ''
    // Focus where the answer comes into being: into the field or onto the yes.
    setTimeout(() => (eingabefeld ?? okKnopf)?.focus(), 40)
  })

  function ja() {
    frageBeantworten(mitEingabe ? wert : true)
  }
  function nein() {
    frageBeantworten(mitEingabe ? null : false)
  }
  function taste(ereignis) {
    if (ereignis.key === 'Enter') {
      ereignis.preventDefault()
      ja()
    }
  }
</script>

{#if zustand.frage}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="schleier" transition:fade={{ duration: 120 }} onclick={nein}>
    <div
      class="popup"
      role="alertdialog"
      aria-modal="true"
      aria-label={zustand.frage.text}
      transition:scale={{ start: 0.96, duration: 140 }}
      onclick={(e) => e.stopPropagation()}
    >
      <div class="frage">{zustand.frage.text}</div>
      {#if mitEingabe}
        <input
          class="feld"
          bind:this={eingabefeld}
          bind:value={wert}
          onkeydown={taste}
          spellcheck="false"
        />
      {/if}
      <div class="knoepfe">
        <button class="knopf" onclick={nein}>{t('app.abbrechen')}</button>
        <button class="knopf wichtig" bind:this={okKnopf} onclick={ja}>
          {t(zustand.frage.okSchluessel)}
        </button>
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
    align-items: flex-start;
    padding: 22vh 16px 0;
  }
  .popup {
    /* A floating layer: the dense glass of the dropdown lists, blurred. */
    background: var(--glass-dropdown);
    -webkit-backdrop-filter: blur(16px);
    backdrop-filter: blur(16px);
    /* 9 — one radius for every edge in the program. A window is no
       different from the controls in it. */
    border-radius: 9px;
    padding: 16px 18px 14px;
    width: min(400px, 92vw);
    /* The house's outer window frame — the notifications' vector stroke,
       a 2px ring hung off var(--text). Same frame the main windows wear. */
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--text) 70%, transparent),
      0 18px 48px rgba(0, 0, 0, 0.25);
  }
  .frage {
    font-size: 13.5px;
    line-height: 1.55;
  }
  .feld {
    width: 100%;
    margin-top: 12px;
    font: inherit;
    font-size: 13px;
    color: var(--text);
    /* A field on glass: glass with the house's field outline. */
    background: var(--glass-button);
    border: 1px solid var(--feldstrich);
    border-radius: 9px;
    padding: 7px 10px;
  }
  .knoepfe {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    margin-top: 14px;
  }
  .knopf {
    /* A quiet button: button glass with the field outline as a ring ON the
       edge; the main button beside it wears the glass edge. */
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
  }
  .wichtig:hover {
    background: color-mix(in srgb, var(--text) 6%, var(--glass-button));
  }
</style>
