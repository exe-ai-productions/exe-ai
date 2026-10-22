<script>
  /* The question window of the phone page: the program asks something and
     waits — "Delete this chat?", or a name to type. It stands over a veil,
     a tap on the veil says no, Enter says yes.

     The answer goes through `frageBeantworten`, which resolves the promise
     `frage()` handed out. The window sits high enough that the keyboard of
     a name field does not cover it. */
  import { tick } from 'svelte'
  import { fade, scale } from 'svelte/transition'
  import { zustand, frageBeantworten } from '../lib/zustand.svelte.js'
  import { t } from '../lib/texte.svelte.js'
  import Hauszeichen from '../teile/Hauszeichen.svelte'

  let field = $state(null)
  let okButton = $state(null)
  let value = $state('')

  const withInput = $derived(zustand.frage?.eingabe != null)

  $effect(() => {
    if (!zustand.frage) return
    value = zustand.frage.eingabe ?? ''
    /* Focus where the answer comes into being: into the field or onto the
       yes. As soon as the window stands and not after a pause — a phone
       raises its keyboard only for a focus that follows the tap. */
    tick().then(() => (field ?? okButton)?.focus())
  })

  const yes = () => frageBeantworten(withInput ? value : true)
  const no = () => frageBeantworten(withInput ? null : false)
  function escape(event) {
    if (event.key === 'Escape' && zustand.frage) no()
  }
  function key(event) {
    // Enter that confirms a keyboard's candidate is not Enter for the question.
    if (event.key === 'Enter' && !event.isComposing) {
      event.preventDefault()
      yes()
    }
  }
</script>

<svelte:window onkeydown={escape} />

{#if zustand.frage}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="veil" transition:fade={{ duration: 120 }} onclick={no}>
    <div
      class="window"
      role="alertdialog"
      aria-modal="true"
      aria-label={zustand.frage.text}
      transition:scale={{ start: 0.96, duration: 140 }}
      onclick={(event) => event.stopPropagation()}
    >
      <div class="title">{zustand.frage.text}</div>
      {#if withInput}
        <input class="field" bind:this={field} bind:value onkeydown={key} spellcheck="false" />
      {/if}
      <div class="buttons">
        <button onclick={no}>{t('app.abbrechen')}</button>
        <button class="main" class:danger={zustand.frage.danger} bind:this={okButton} onclick={yes}>
          {#if zustand.frage.danger}<Hauszeichen zeichen="trash" groesse={15} />{/if}
          {t(zustand.frage.okSchluessel)}
        </button>
      </div>
    </div>
  </div>
{/if}

<style>
  .veil {
    position: fixed;
    inset: 0;
    z-index: 60;
    display: flex;
    justify-content: center;
    align-items: flex-start;
    padding: calc(12vh + env(safe-area-inset-top)) 16px 0;
    background: rgba(0, 0, 0, 0.45);
  }
  /* The "question" window of the house: the dense glass of the dropdown
     lists, blurred, with the ring ON the edge and the popup's soft fall. */
  .window {
    width: min(460px, 100%);
    padding: 18px 18px 6px;
    border-radius: 9px;
    background: var(--glass-dropdown);
    -webkit-backdrop-filter: blur(16px);
    backdrop-filter: blur(16px);
    box-shadow: 0 0 0 1px var(--glass-button-edge), 0 28px 70px -12px rgba(0, 0, 0, 0.55);
    color: var(--text);
  }
  .title {
    font: 600 16px/1.4 var(--schrift);
    overflow-wrap: anywhere;
  }
  .field {
    width: 100%;
    height: 44px;
    margin-top: 12px;
    padding: 0 12px;
    border: none;
    border-radius: 9px;
    outline: none;
    background: var(--kachel-eingabe);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    color: var(--text);
    /* 16 px: a smaller field makes the phone zoom the page in on focus. */
    font: 400 16px var(--schrift);
  }
  .buttons {
    display: flex;
    justify-content: flex-end;
    gap: 4px;
    margin-top: 6px;
  }
  .buttons button {
    min-width: 88px;
    height: 44px;
    padding: 0 14px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
    font: 500 14px var(--schrift);
  }
  .buttons button:active {
    background: var(--glass-hover);
  }
  .buttons .main {
    color: var(--text);
    font-weight: 600;
  }
  /* A question about deleting: the main button wears the colour of deleting
     and carries the bin. */
  .buttons .main.danger {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 7px;
    color: var(--rot-text);
  }
</style>
