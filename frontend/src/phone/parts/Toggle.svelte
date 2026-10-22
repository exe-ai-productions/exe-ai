<script>
  /* A named switch on a line: the name on the left, the house switch on the
     right. The line answers to a tap too, so a thumb does not have to find
     the small switch; the switch is the one element a keyboard reaches. */
  import Schalter from '../../teile/Schalter.svelte'

  let { label, on = false, onswitch, disabled = false } = $props()
</script>

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
<div class="toggle" class:disabled onclick={() => !disabled && onswitch?.()}>
  <span class="label">{label}</span>
  <Schalter an={on} beschriftung={label} gesperrt={disabled} onschalten={() => onswitch?.()} />
</div>

<style>
  .toggle {
    display: flex;
    align-items: center;
    gap: 12px;
    width: 100%;
    min-height: var(--menuezeile);
    box-sizing: border-box;
    padding: 6px 12px 6px 10px;
    border-radius: 9px;
    color: var(--text-leise);
    font: 500 var(--schrift-text) var(--schrift);
  }
  .toggle:active:not(.disabled) {
    background: color-mix(in srgb, var(--text) 4%, transparent);
  }
  .label {
    flex: 1;
    min-width: 0;
    overflow-wrap: anywhere;
  }
</style>
