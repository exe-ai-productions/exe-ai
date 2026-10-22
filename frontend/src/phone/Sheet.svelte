<script>
  /* A sheet that rises from the bottom edge — the phone's way of showing a
     menu or a choice. It stands over a veil; a tap on the veil closes it.

     The sheet holds whatever it is given and nothing of its own beyond the
     grip, the glass and the room under the content that keeps the last row
     clear of the home bar. `layer` lifts it above something that lies over
     the whole page (the reader). */
  import { fade, fly } from 'svelte/transition'

  let { open = false, label = '', onclose, layer = 40, children } = $props()
</script>

{#if open}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="veil" style:z-index={layer} transition:fade={{ duration: 140 }} onclick={onclose}></div>
  <div class="sheet" style:z-index={layer + 1} role="dialog" aria-modal="true" aria-label={label}
       transition:fly={{ y: 360, duration: 240 }}>
    <div class="grip" aria-hidden="true"></div>
    {@render children?.()}
  </div>
{/if}

<style>
  .veil {
    position: fixed;
    inset: 0;
    z-index: 40;
    background: rgba(0, 0, 0, 0.45);
  }
  .sheet {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 41;
    max-height: 82dvh;
    overflow-y: auto;
    padding: 8px 18px calc(18px + env(safe-area-inset-bottom));
    /* The floating layer of the house: the dense glass of the dropdown
       lists, blurred, with its ring ON the edge. */
    background: var(--glass-dropdown);
    -webkit-backdrop-filter: blur(16px);
    backdrop-filter: blur(16px);
    border-radius: 9px 9px 0 0;
    box-shadow: 0 0 0 1px var(--glass-button-edge), 0 -18px 40px -8px rgba(0, 0, 0, 0.55);
    color: var(--text);
  }
  .grip {
    width: 36px;
    height: 4px;
    margin: 0 auto 10px;
    border-radius: 99px;
    background: var(--text-still);
    opacity: 0.5;
  }
</style>
