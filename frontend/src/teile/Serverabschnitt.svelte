<script>
  /* One section of a server window: a head line and one raised card under it.

     The head is 26 px tall — the section's sign and name on the left, then
     `count` (a quiet figure such as "3/9") and at its right end whatever the
     window puts there (its Start/Stop button). A card with no title, sign or
     right end of its own has no head at all. A
     section that can be folded wears a small arrow instead of a sign, and its
     card is only drawn while it stands open.

     The rows are styled here, not in each window. Every card of every server
     window shares one row height, one inset and one hairline between rows,
     and six copies of those numbers drifted apart before. A row is any direct
     child of the card with the class `zeile`; a row with the class `niedrig`
     is a switch row and starts four pixels lower, one with `duenn` is a thin
     line under the others, `liste` a row of a list, `kurz` a row of one
     quiet line, `stapel` a row that stacks its name, a box and a button,
     `regel` a slider row: its name and its number on one line (`kopfzeile`),
     the slider over the whole width under them. The version row of a program
     ends in its build number, a `versionsmarke`. A `stapel` row may open with
     an `obenzeile`: the name on the left and a `rowsign` (a sign button, no
     text) at the right end of one line, the field under both. A row whose
     picker (`wahl`) does not fit beside its name stacks it under the name,
     the full width of the row; a name that does not fit even alone ends in
     an ellipsis.

     Cards that stand side by side are equally tall. The row of the window
     (Serverreihe.svelte) stretches both columns to the taller one, and
     `gewicht` — the number of rows in this card — hands the extra height out
     by rows: every row of the shorter column grows by the same few pixels,
     instead of one card growing an empty strip at its foot.

     `bare`: the section's content stands under its head without a card of its
     own — for a section whose content is itself cards (the parameter panel's
     two). */
  import Hauszeichen from './Hauszeichen.svelte'
  import InfoMark from './InfoMark.svelte'

  let {
    zeichen = '',
    titel = '',
    // A sentence behind the name in the head: the small mark that shows it.
    info = '',
    rechts = null,
    count = '',
    klappbar = false,
    offen = $bindable(true),
    gewicht = 0,
    bare = false,
    children,
  } = $props()
</script>

<section class="abschnitt" class:weighted={gewicht} style:flex-grow={gewicht || null}>
  {#if klappbar}
    <button class="kopf klapp tafelkopf" onclick={() => (offen = !offen)} aria-expanded={offen}>
      <svg class="winkel" class:auf={offen} width="14" height="14" viewBox="0 0 11 11" fill="none"
           stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"
           aria-hidden="true">
        <path d="M4.125 2.75L6.875 5.5L4.125 8.25" />
      </svg>
      <span class="name">{titel}</span>
    </button>
  {:else if zeichen || titel || rechts}
    <div class="kopf tafelkopf" class:mitinfo={info}>
      {#if zeichen}
        <span class="zeichen"><Hauszeichen {zeichen} groesse="klein" /></span>
      {/if}
      <span class="name">{titel}</span>
      {#if info}
        <InfoMark text={info} />
      {/if}
      {#if count}
        <span class="count-figure">{count}</span>
      {/if}
      {#if rechts}
        <span class="rechts">{@render rechts()}</span>
      {/if}
    </div>
  {/if}
  {#if !klappbar || offen}
    {#if bare}
      <div class="bare">{@render children?.()}</div>
    {:else}
      <div class="karte">{@render children?.()}</div>
    {/if}
  {/if}
</section>

<style>
  .abschnitt {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  /* Text itself: global.css, .tafelkopf. */
  .kopf {
    flex: none;
    height: 26px;
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }
  /* A head with a mark: the mark stands right behind the name, and its
     sentence, when open, on a line of its own below (the mark's own rule). */
  .kopf.mitinfo {
    flex-wrap: wrap;
    height: auto;
    min-height: 26px;
  }
  .kopf.mitinfo :global(.mark) {
    margin-left: 0;
  }
  .zeichen {
    flex: none;
    display: inline-flex;
    color: var(--text-leise);
  }
  .name {
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .count-figure {
    flex: none;
    font-size: 12px;
    font-weight: 400;
    color: var(--text-still);
    font-variant-numeric: tabular-nums;
  }
  .rechts {
    margin-left: auto;
    flex: none;
    display: inline-flex;
    align-items: center;
  }
  /* The folding head is a row you press: the whole line is the target. */
  .klapp {
    width: 100%;
    padding: 0;
    border: none;
    background: none;
    cursor: pointer;
    gap: 10px;
    font-weight: 500;
  }
  .winkel {
    flex: none;
    color: var(--text-still);
    transition: transform 0.15s;
  }
  .winkel.auf {
    transform: rotate(90deg);
  }
  @media (prefers-reduced-motion: reduce) {
    .winkel {
      transition: none;
    }
  }
  .bare {
    min-width: 0;
  }
  /* A raised card, never a frame: the ground step alone sets it apart. */
  /* Not clipped: a list that opens in a row of the card lays itself over
     the window, the sections below included, instead of ending at the
     card's lower edge. Nothing in a row paints a ground out to the card's
     corners, so the rounding needs no clip either. */
  .karte {
    flex: 1 1 auto;
    min-width: 0;
    display: flex;
    flex-direction: column;
    /* A card on the page: card glass with its fine line. */
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    border-radius: 9px;
    /* The folder path in this card reads one step larger than in the small
       places that row also stands in (Speicherortzeile.svelte). */
    --pfad-schrift: 12px;
    /* Its folder buttons are 34 px, like the other buttons of a card. */
    --ordnerknopf: 34px;
  }
  /* One setting per row: 56 px with its hairline, 16 px in from both
     sides, a hairline above every row but the first. The row grows with its
     column (see above). */
  .karte > :global(.zeile) {
    flex: 1 1 auto;
    box-sizing: border-box;
    min-height: 56px;
    padding: 10px 16px;
    display: flex;
    align-items: center;
    gap: 16px;
    min-width: 0;
  }
  .karte > :global(.zeile.niedrig) {
    min-height: 52px;
    padding-top: 8px;
    padding-bottom: 8px;
  }
  /* A thin row under the others (the storage plan): it keeps its height when
     the card grows. */
  .karte > :global(.zeile.duenn) {
    flex-grow: 0;
    min-height: 39px;
    padding-top: 10px;
    padding-bottom: 12px;
  }
  .karte > :global(.zeile + .zeile) {
    border-top: 1px solid var(--linie);
  }
  /* A row of a list (a model file, the device list): 48 px. */
  .karte > :global(.zeile.liste) {
    min-height: 48px;
    padding-top: 8px;
    padding-bottom: 8px;
    gap: 12px;
  }
  /* A row of one quiet line of text (the projector under a speech model). */
  .karte > :global(.zeile.kurz) {
    min-height: 40px;
    font-size: 12px;
    line-height: 16px;
    color: var(--text-still);
  }
  /* Unless what it says is that something is missing: a failed state. */
  .karte > :global(.zeile.kurz.fehlt) {
    color: var(--rot-text);
  }
  /* A row whose control is a box of its own: its name above, the field full
     width under it, a quiet button at the right end. */
  .karte > :global(.zeile.stapel) {
    padding-top: 12px;
    padding-bottom: 12px;
    flex-direction: column;
    align-items: stretch;
    gap: 10px;
  }
  .karte > :global(.zeile.stapel) > :global(:is(.feldknopf, .stillknopf)) {
    align-self: flex-end;
  }
  /* The name of a stacked row on the left and a sign button at the right end
     of the same line. */
  .karte :global(.obenzeile) {
    display: flex;
    align-items: center;
    gap: 16px;
    min-width: 0;
  }
  /* A sign button of 30 px: button glass with its fine edge. */
  .karte :global(.rowsign) {
    width: 30px;
    height: 30px;
    flex: none;
    display: inline-grid;
    place-items: center;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    cursor: pointer;
    transition: background 0.12s;
  }
  .karte :global(.rowsign:hover) {
    background: var(--glass-hover);
  }
  /* A slider row: the name on the left and the number at the right end of
     one line, the slider under both. */
  .karte > :global(.zeile.regel) {
    flex-direction: column;
    align-items: stretch;
    justify-content: center;
    gap: 2px;
  }
  .karte :global(.kopfzeile) {
    display: flex;
    align-items: center;
    gap: 16px;
    min-width: 0;
  }
  /* The two buttons of a card, 34 px tall: filled on the field ground
     (`feldknopf`), or quiet without a ground until the pointer comes
     (`stillknopf`). */
  .karte :global(:is(.feldknopf, .stillknopf)) {
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
  }
  .karte :global(.feldknopf) {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    color: var(--text);
  }
  .karte :global(.stillknopf) {
    background: none;
    color: var(--text-leise);
  }
  .karte :global(:is(.feldknopf, .stillknopf):hover:not(:disabled)) {
    background: var(--glass-hover);
    color: var(--text);
  }
  .karte :global(:is(.feldknopf, .stillknopf):disabled) {
    cursor: default;
    opacity: 0.5;
  }
  /* Buttons that stand side by side at the end of a row are equally wide:
     the widest one sets the width of them all. */
  .karte :global(.buttons) {
    flex: none;
    display: grid;
    grid-auto-flow: column;
    grid-auto-columns: 1fr;
    gap: 8px;
  }
  /* The parts of a row, the same in every window: a name that takes the room
     up to its control (`name`, `zahlname`, and `regelname` over a slider),
     a number field 84 wide (`zahlplatz`) — over a slider as short as its
     number — and a picker 232 wide (`wahl`) at the right end. A `regelname`
     outside a slider row is 188 wide and the field beside it takes what is
     left. */
  .karte :global(:is(.name, .regelname, .zahlname)) {
    font-size: 13px;
    font-weight: 600;
    line-height: 18px;
    color: var(--text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  /* A row whose only child is its name carries a message, not a setting
     (a state like "loading", an error): it is not a name to read the row by
     and stays regular. The version line is the one name that is a name even
     when it stands alone (it keeps its own weight), and the names a part sets
     in the weight of its own row (a catalogue row) are not touched: the
     rule is written with `:where`, so those rules, which carry a class more,
     win. */
  .karte :global(.zeile > :where(.name:not(.build), .regelname, .zahlname):only-child) {
    font-weight: 400;
  }
  .karte :global(:is(.name, .zahlname)) {
    flex: 1;
    min-width: 0;
  }
  .karte :global(.regelname) {
    flex: none;
    width: 188px;
  }
  .karte :global(.zahlplatz) {
    flex: none;
    width: 84px;
  }
  /* The number of a build at the end of the version row of a program: a
     quiet mark, tabular figures. */
  .karte :global(.versionsmarke) {
    flex: none;
    padding: 2px 8px;
    border-radius: 9px;
    background: color-mix(in srgb, var(--text) 8%, transparent);
    color: var(--text-leise);
    font: 500 12px/16px var(--schrift);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .karte :global(.wahl) {
    flex: none;
    width: 232px;
    max-width: 100%;
    min-width: 0;
  }
  /* A row with a picker wraps: where the name and the picker do not both fit
     in the line, the picker stands under the name and takes the whole line.
     The name grows enormously more than the picker, so beside the name the
     picker stays as wide as it is drawn, and alone in its line it takes the
     row; a name wider than the row alone is cut with an ellipsis. */
  .karte > :global(.zeile:has(> .wahl)) {
    flex-wrap: wrap;
    row-gap: 8px;
    align-content: center;
  }
  .karte > :global(.zeile:has(> .wahl) > .name) {
    flex: 100000 1 auto;
    min-width: 0;
    max-width: 100%;
  }
  .karte > :global(.zeile:has(> .wahl) > .wahl) {
    flex: 1 0 auto;
  }
  .karte :global(.kopfzeile .regelname) {
    flex: 1;
    width: auto;
    min-width: 0;
  }
  .karte :global(.kopfzeile .zahlplatz) {
    width: auto;
  }
</style>
