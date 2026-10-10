<!-- One row of any menu list — settings, local, cloud, catalogue. A sign, the
     name, a short quiet value at the right and, where a state is worth one,
     a dot at the far end. The row is the same height and type size in every
     list, because every list builds it here; a list that needs a differing
     inner (a model switch, a download count) hands it in as `rechts`.

     The explanatory line that used to stand under the name is gone: a
     value is one short word, the explanation belongs to the page. -->
<script>
  import Leuchtpunkt from './Leuchtpunkt.svelte'

  let { zeichen, titel, wert = '', punkt = null, gewaehlt = false, onclick, rechts, ...rest } = $props()
</script>

<button
  class="menuezeile"
  class:gewaehlt
  aria-current={gewaehlt ? 'true' : undefined}
  {onclick}
  {...rest}
>
  {#if zeichen}<span class="zeichen">{@render zeichen()}</span>{/if}
  <span class="titel">{titel}</span>
  {#if wert}<span class="wert">{wert}</span>{/if}
  {#if rechts}{@render rechts()}{/if}
  {#if punkt}<span class="punkt"><Leuchtpunkt farbe={punkt} groesse={11} /></span>{/if}
</button>

<style>
  .menuezeile {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    min-height: var(--menuezeile);
    box-sizing: border-box;
    padding: 6px 12px 6px 10px;
    text-align: left;
    border: none;
    border-radius: 9px;
    background: none;
    /* On the frame it wears the frame's ink; the chosen row brings its own
       ground and keeps the look's. */
    color: var(--rahmen-text, var(--text-leise));
    font: 500 var(--schrift-text) var(--schrift);
    cursor: pointer;
    transition: background 0.12s;
  }
  .menuezeile:hover {
    background: color-mix(in srgb, var(--text) 4%, transparent);
  }
  .menuezeile.gewaehlt {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
  }
  .zeichen {
    width: 24px;
    height: 24px;
    flex: none;
    display: flex;
    align-items: center;
    justify-content: center;
    color: inherit;
  }
  /* The name keeps its room; the value gives way first. */
  .titel {
    flex: 0 0 auto;
    max-width: 100%;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .wert {
    flex: 0 1 auto;
    min-width: 0;
    margin-left: auto;
    font-weight: 400;
    font-size: var(--schrift-hinweis);
    color: var(--rahmen-text, var(--text-still));
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  /* The chosen row has a ground of its own and keeps the look's ink. */
  .menuezeile.gewaehlt .wert {
    color: var(--text-still);
  }
  .punkt {
    flex: none;
    display: inline-flex;
    align-items: center;
  }
  /* With no value before it, the dot stands at the row's far end. */
  .titel + .punkt { margin-left: auto; }
</style>
