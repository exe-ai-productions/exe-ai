<script>
  /* A switch of two or more tabs in one glass track: the one pressed is
     raised, the others are quiet words. The same track and the same raised
     half as the head's switch in the studio (Arbeitsleiste.svelte). */
  let { wert = $bindable(''), eintraege = [], label = '', gesperrt = false } = $props()
</script>

<div class="tab-switch" role="group" aria-label={label}>
  {#each eintraege as eintrag (eintrag.wert)}
    <button class:an={wert === eintrag.wert} aria-pressed={wert === eintrag.wert}
            disabled={gesperrt} onclick={() => (wert = eintrag.wert)}>{eintrag.text}</button>
  {/each}
</div>

<style>
  .tab-switch {
    display: flex;
    gap: 2px;
    padding: 3px;
    border-radius: 9px;
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
  }
  button {
    min-width: 64px;
    height: 28px;
    padding: 0 12px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
    font: 400 13px/18px var(--schrift);
    cursor: pointer;
  }
  button:hover:not(:disabled) {
    color: var(--text);
  }
  button.an {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    cursor: default;
  }
  button:disabled:not(.an) {
    cursor: default;
    opacity: 0.5;
  }
</style>
