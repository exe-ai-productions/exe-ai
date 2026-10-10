<script>
  /* A server window's one deed: start it or stop it.

     It stands at the right end of a section's head line, not in the window's
     head card — the drawing puts it in the line of the first group, flush
     with the card below it. Which group that is differs from window to
     window, so the button is its own small piece and each panel sets it
     where its drawing has it. */
  import Leuchtpunkt from './Leuchtpunkt.svelte'

  let {
    text = '',
    punkt = 'still',
    gesperrt = false,
    onTat = null,
  } = $props()
</script>

<button class="startknopf" disabled={gesperrt} onclick={onTat}>
  {#if punkt === 'gruen'}
    <Leuchtpunkt farbe="gruen" groesse={11} />
  {/if}
  {text}
</button>

<style>
  /* The primary button of a server window: glass with a fine edge, radius
     9 — 26 px tall, so it fits the 26 px head line of its section. */
  .startknopf {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    height: 26px;
    box-sizing: border-box;
    padding: 4px 14px;
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
