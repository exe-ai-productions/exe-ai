<script>
  /* A maker's mark standing bare in front of a model's name — no tile around
     it. `mark` is a vector out of lib/logos.js (`{ vb, html }`); a model of a
     family the house has no original vector for gets the first letter of its
     name in the same place, so a mark is never guessed. The quick picker and
     the picture server's lists share this one piece. */
  let { mark = null, name = '', groesse = 22 } = $props()
</script>

<span class="logo" style:width="{groesse}px" style:height="{groesse}px" aria-hidden="true">
  {#if mark}
    <svg viewBox={mark.vb} width={groesse} height={groesse}>{@html mark.html}</svg>
  {:else}
    <span class="letter">{String(name || '?').slice(0, 1).toUpperCase()}</span>
  {/if}
</span>

<style>
  .logo {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: var(--text);
  }
  .letter {
    font: 600 14px var(--schrift);
    color: var(--text-leise);
  }
</style>
