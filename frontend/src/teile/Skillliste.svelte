<script>
  import { rollfade } from '../lib/rollfade.js'
  /* The slash list above the input field. Opens when a slash is the FIRST
     character — mid-sentence a slash stays a slash. Per entry: the name to
     type on one line and the description that says when it applies, at most
     two lines and then an ellipsis (the whole one stands in the skill's own
     sheet). */
  let { eintraege = [], dran = 0, waehlen } = $props()

  let kasten = $state(null)

  /* Keep the highlighted row in view while walking with the arrow keys.
     The list scrolls without a visible bar, so nothing hints at what lies
     below — the row has to come to the eye by itself. */
  $effect(() => {
    void dran
    kasten?.querySelector('.dran')?.scrollIntoView({ block: 'nearest' })
  })
</script>

<div class="skillliste" bind:this={kasten} role="listbox" tabindex="-1" use:rollfade>
  {#each eintraege as eintrag, i (eintrag.name)}
    <button
      type="button"
      class="zeile"
      class:dran={i === dran}
      role="option"
      aria-selected={i === dran}
      onmousedown={(e) => e.preventDefault()}
      onclick={() => waehlen(eintrag)}
    >
      <div class="zname">{eintrag.name}</div>
      <div class="zwas">{eintrag.beschreibung}</div>
    </button>
  {/each}
</div>

<style>
  .skillliste {
    position: absolute;
    left: -1px;
    bottom: calc(100% + 8px);
    width: 340px;
    max-width: 100%;
    background: var(--bg-erhoben);
    border: 1px solid transparent;
    border-radius: 9px;
    padding: 5px;
    box-shadow: 0 0 0 1px var(--linie), 0 18px 40px -8px rgba(0, 0, 0, 0.55);
    /* Eight rows and a bit, so it is visible that the list goes on. */
    max-height: 296px;
    overflow-y: auto;
    z-index: 30;
  }
  .zeile {
    display: block;
    width: 100%;
    text-align: left;
    border: none;
    background: none;
    font: inherit;
    color: var(--text);
    padding: 6px 9px 7px;
    border-radius: 9px;
    cursor: pointer;
  }
  .zeile:hover {
    background: color-mix(in srgb, var(--bg-hoch) 60%, transparent);
  }
  .zeile.dran {
    background: var(--bg-hoch);
  }
  .zname {
    font-size: 13px;
    line-height: 1.3;
  }
  .zwas {
    font-size: 12px;
    color: var(--text-still);
    line-height: 1.35;
    margin-top: 1px;
    /* A description may be 1024 characters: two lines, then an ellipsis. */
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    overflow: hidden;
  }
  .zeile.dran .zwas {
    color: var(--text-leise);
  }
</style>
