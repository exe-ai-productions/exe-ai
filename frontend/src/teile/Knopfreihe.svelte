<script>
  /* The buttons of a page, in one row at its foot, right-aligned — where
     the eye ends after the last card. A page may bring its own buttons
     (the house's main button keeps its one form, wherever it stands); the
     two quiet ones are drawn here, 34 px tall like the buttons inside the
     cards (Serverabschnitt.svelte):

       stillknopf   quiet, without a ground until the pointer comes
       loeschknopf  quiet and red: it removes something */
  let { children } = $props()
</script>

<div class="knopfreihe">{@render children?.()}</div>

<style>
  .knopfreihe {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: 10px;
  }
  .knopfreihe :global(:is(.stillknopf, .loeschknopf)) {
    flex: none;
    height: 34px;
    box-sizing: border-box;
    padding: 0 14px;
    border: none;
    border-radius: 9px;
    font: 500 13px/18px var(--schrift);
    white-space: nowrap;
    cursor: pointer;
    transition: background 0.12s, color 0.12s;
    background: none;
    color: var(--text-leise);
  }
  .knopfreihe :global(.loeschknopf) {
    color: var(--rot-text);
  }
  .knopfreihe :global(.stillknopf:hover:not(:disabled)) {
    background: color-mix(in srgb, var(--text) 6%, var(--glass-button));
    color: var(--text);
  }
  .knopfreihe :global(.loeschknopf:hover:not(:disabled)) {
    background: color-mix(in srgb, var(--rot) 12%, var(--bg));
  }
  .knopfreihe :global(:is(.stillknopf, .loeschknopf):disabled) {
    cursor: default;
    opacity: 0.5;
  }
</style>
