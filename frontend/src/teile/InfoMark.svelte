<script>
  /* The small ⓘ beside a setting's name: pressed, it shows one short
     sentence on what the setting does, and a press anywhere else or Escape
     puts it away.

     A span with the button role, not a <button>: the mark sits inside the
     rows' <label>s, and a label names the first button inside it — a real
     button there would take the name away from the field the label is
     for. */
  import { t } from '../lib/texte.svelte.js'

  let { text } = $props()

  let open = $state(false)
  let node = $state(null)

  function toggle(event) {
    /* Inside a label: the press is the mark's, not the field's. It still
       travels on to the window, so another open mark or list closes. */
    event.preventDefault()
    open = !open
  }

  function keys(event) {
    if (event.key === 'Enter' || event.key === ' ') {
      toggle(event)
    } else if (event.key === 'Escape' && open) {
      event.stopPropagation()
      open = false
    }
  }

  function outside(event) {
    if (open && node && !node.contains(event.target)) open = false
  }

</script>

<svelte:window onclick={outside} />

<span class="info" bind:this={node}>
  <span class="mark" class:open role="button" tabindex="0"
        aria-label={t('bild.info')} aria-expanded={open}
        onclick={toggle} onkeydown={keys}>
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
         stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M12 8v5M12 16h.01" /></svg>
  </span>
  {#if open}
    <!-- A press on the sentence stays with it: inside a label it would
         otherwise go on to the field and close the sentence. -->
    <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
    <span class="bubble" role="note" onclick={(event) => event.preventDefault()}>{text}</span>
  {/if}
</span>

<style>
  /* No box of its own: the mark and the sentence are laid out by the row's
     label line, the mark at its right end and the sentence on a line of its
     own below. In the flow, not floating over it — nothing next to it or
     below it can cover it or cut it off. */
  .info {
    display: contents;
  }
  .mark {
    display: inline-flex;
    margin-left: auto;
    width: 14px;
    height: 14px;
    color: var(--text-still);
    cursor: pointer;
    border-radius: 99px;
  }
  .mark svg {
    width: 100%;
    height: 100%;
  }
  .mark:hover,
  .mark.open,
  .mark:focus-visible {
    color: var(--text);
  }
  .bubble {
    flex-basis: 100%;
    order: 99;
    padding: 8px 10px;
    border-radius: 9px;
    background: var(--bg-erhoben);
    border: 1px solid var(--linie-stark);
    color: var(--text);
    font-size: 12px;
    font-weight: 400;
    letter-spacing: normal;
    text-transform: none;
    line-height: 1.45;
    white-space: normal;
  }
</style>
