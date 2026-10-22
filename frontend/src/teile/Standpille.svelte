<script>
  /* The small filled pill that names a state: connected, on, running,
     failed.

     Its own component because the same fourteen lines stood in three files
     word for word, and a fourth had drifted a little already. A shape that
     appears in four places and is corrected in one of them is how a house
     style comes apart.

     `farbe` follows the house rule — colour means state, never decoration:

       gruen  done, ready, connected
       blau   running, active, switched on
       gelb   waiting, and caution
       rot    failed, dangerous
       still  no state worth a colour: off, unreachable, unset

     And two that are NOT a state:

       werkzeug  a tool — its name, in the tool face and the text colour
       count     a number in words (the tools in use) — no dot, the quiet
                 text colour

     Nothing here positions the pill. Where it sits belongs to whoever puts
     it somewhere. */
  let { farbe = 'still', children } = $props()
</script>

<span class="pille" data-farbe={farbe}>{@render children?.()}</span>

<style>
  .pille {
    /* inline-flex and line-height 1, so the text is centred against the box
       instead of hanging in an inherited line height. */
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 7px;
    flex: none;
    line-height: 1;
    font-size: 12px;
    font-weight: 500;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    /* A glass pill with the house's separator line as its rim, drawn ON the
       edge so the pill keeps its size: the state colour sits in the dot
       alone, the word stays in the reading colour. */
    --punkt: var(--text-still);
    border: none;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--linie);
    /* A control's corner, not a pill's: it reports a state beside a heading,
       and every other control in these panels wears this radius. */
    border-radius: 9px;
    color: var(--text);
    padding: 5px 11px 5px 10px;
  }
  .pille::before {
    content: '';
    flex: none;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--punkt);
  }

  /* No state worth a colour: the word steps back with its grey dot. */
  .pille[data-farbe='still'] {
    color: var(--text-leise);
  }
  /* The one entry that names a thing rather than a state. It carries the
     tool face as well, so a name in a pill reads like the same name in a
     row (`.werkzeugname`, stil/global.css), and it wears no state dot. */
  .pille[data-farbe='werkzeug'] {
    font-family: var(--schrift-fest);
    font-size: 12px;
    font-weight: 600;
  }
  .pille[data-farbe='werkzeug']::before,
  .pille[data-farbe='count']::before {
    display: none;
  }
  /* A figure in words beside a heading: no dot to say a state, the word
     steps back like the fact it is. */
  .pille[data-farbe='count'] {
    color: var(--text-leise);
    padding: 5px 11px;
  }
  .pille[data-farbe='gruen'] {
    --punkt: var(--gruen);
  }
  .pille[data-farbe='blau'] {
    --punkt: var(--blau);
  }
  .pille[data-farbe='gelb'] {
    --punkt: var(--gelb);
  }
  .pille[data-farbe='rot'] {
    --punkt: var(--rot);
  }
</style>
