<script>
  /* One row, one fixed height — the house's shape of a navigation row:
     sign, name, and the state lamp at the far end.

     Its own component because "tiles of one group are exactly the same
     height" is a house rule, and the only way to guarantee it across
     files is to draw the row in one place. Every row is 36px tall, the
     height of a navigation row; the text adapts (one line, ellipsis), the
     shape never.

     What fills the row is brought by the caller as snippets:
       zeichen  a sign on the left, 20px, without a frame
       marke    an alternative left mark (a status dot) shown bare
       unter    the subtitle line under the title
       rechts   what sits at the right edge (a warning dot, a switch)

     `titel` is the one always-present line. Passing `onclick` turns the
     tile into a button (keyboard-reachable); leaving it off keeps it a
     plain statement, which is what a row carrying its own switch wants —
     a tile must not be a button that swallows the switch inside it. */
  let {
    titel = '',
    gewaehlt = false,
    onclick = null,
    ariaLabel = '',
    zeichen,
    /* A state lamp at the far end of the name's line. The sign says WHAT
       this is, the name says which one, and the lamp says how it stands; a
       lamp under the name, on a line of its own, made the row twice as tall
       to carry one dot. */
    lampe,
    marke,
    unter,
    rechts,
  } = $props()

  const klickbar = $derived(typeof onclick === 'function')
</script>

<!-- svelte-ignore a11y_no_static_element_interactions, a11y_no_noninteractive_tabindex -->
<div
  class="kachel"
  class:gewaehlt
  class:klickbar
  role={klickbar ? 'button' : undefined}
  tabindex={klickbar ? 0 : undefined}
  aria-label={ariaLabel || undefined}
  {onclick}
  onkeydown={klickbar ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onclick(e) } } : undefined}
>
  {#if zeichen}
    <span class="zbox">{@render zeichen()}</span>
  {:else if marke}
    <span class="marke">{@render marke()}</span>
  {/if}

  <div class="mitte">
    <div class="titel">{#if lampe}<span class="lampe">{@render lampe()}</span>{/if}{titel}</div>
    {#if unter}<div class="unter">{@render unter()}</div>{/if}
  </div>

  {#if rechts}<div class="rechts">{@render rechts()}</div>{/if}
</div>

<style>
  .kachel {
    display: flex;
    align-items: center;
    gap: 10px;
    height: 36px;
    padding: 0 12px 0 10px;
    border: 1px solid transparent;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
    text-align: left;
    width: 100%;
    transition: background 0.12s, border-color 0.12s;
  }
  .kachel.klickbar {
    cursor: pointer;
  }
  .kachel.klickbar:hover {
    border-color: transparent;
    background: color-mix(in srgb, var(--text) 4%, transparent);
  }
  /* The chosen row: a filled ground and the full text colour, no colour
     of the palette — being selected is not a state the palette speaks
     for. */
  .kachel.gewaehlt {
    border-color: transparent;
    background: var(--bg-hoch);
    color: var(--text);
  }
  .kachel.gewaehlt .titel {
    font-weight: 500;
  }

  /* No frame around the sign: a sign large enough to be read needs no box
     to be found, and a box around every row drew rectangles that said
     nothing the sign did not already say. The width is fixed, so the names
     beside them still start on one line. */
  .zbox {
    width: 20px;
    height: 20px;
    flex: none;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-leise);
  }
  .marke {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }

  .mitte {
    flex: 1;
    min-width: 0;
  }
  .titel {
    display: flex;
    align-items: center;
    gap: 7px;
    font: 400 13px var(--schrift);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .lampe {
    flex: none;
    display: inline-flex;
    order: 2;
    margin-left: auto;
  }
  .unter {
    font-size: 11px;
    color: var(--text-still);
    margin-top: 1px;
    display: flex;
    align-items: center;
    gap: 5px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .rechts {
    margin-left: auto;
    flex: none;
    display: inline-flex;
    align-items: center;
    color: var(--text-still);
    font-size: 12px;
  }
</style>
