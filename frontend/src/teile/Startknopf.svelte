<script>
  /* A server's one deed: start it or stop it.

     It is the same button everywhere — at the right end of a server page's
     head and in each row of the server overview: one size, one word with a
     dot in front of it. The dot is green while the server runs and the quiet
     grey of a fact while it does not, so the button says which of the two it
     is before it is read. */
  import Leuchtpunkt from './Leuchtpunkt.svelte'

  let {
    text = '',
    punkt = 'still',
    gesperrt = false,
    onTat = null,
  } = $props()
</script>

<button class="startknopf" disabled={gesperrt} onclick={onTat}>
  <Leuchtpunkt farbe={punkt === 'gruen' ? 'gruen' : 'still'} groesse={10} />
  {text}
</button>

<style>
  /* Glass with a fine edge, radius 9, 86 × 34 whatever the word. */
  .startknopf {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    width: 86px;
    height: 34px;
    flex: none;
    box-sizing: border-box;
    padding: 0 10px;
    line-height: 18px;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    font: inherit;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.12s, transform 0.08s;
  }
  .startknopf:not(:disabled):hover {
    background: color-mix(in srgb, var(--text) 6%, var(--glass-button));
  }
  .startknopf:not(:disabled):active {
    transform: scale(0.975);
  }
  .startknopf:disabled {
    opacity: 0.5;
    cursor: default;
  }
</style>
