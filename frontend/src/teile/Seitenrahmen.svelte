<script>
  /* The frame a menu page stands in — Models, Catalogue, Settings.

     It lies over everything right of the sidebar, the chat and the tool
     surface beside it, instead of replacing them: both stay mounted
     underneath, so opening a page and going back costs nothing — no
     reload, no lost scroll position, no half-typed message thrown away, no
     terminal cut off. Its left edge is the chat's; the sum comes from the
     `--seite-links` the window body sets (App.svelte).

     The frame stays mounted while its page is closed and is only hidden,
     so a page keeps what was chosen in it the way the windows it replaces
     kept it. */
  let { offen = false, beschriftung = '', children } = $props()
</script>

<section class="seite" hidden={!offen} aria-label={beschriftung}>
  {@render children?.()}
</section>

<style>
  /* The chat's ground and corner. Above the chat's head and the tool
     surface (5), below the notifications (25, they must still
     be read over the page), the status strip (80) and every window's veil
     (70). */
  .seite {
    position: absolute;
    top: 8px;
    right: 8px;
    bottom: 8px;
    left: var(--seite-links, 8px);
    z-index: 20;
    display: flex;
    flex-direction: column;
    /* The chat's glass, its edge and its shadow: the same ground — the
       look's gradient mixed with the glass and fixed to the window where
       it names one, see-through otherwise — and the same lift off the
       frame. */
    background: var(--kachel-verlauf, var(--kachel-chat, var(--bg)));
    background-attachment: fixed;
    box-shadow: var(--chat-edge, none);
    border-radius: 9px;
    overflow: hidden;
    /* Inside the page only, the raised grounds and the hairline turn to
       the cards' glass: every card, field and filled control of a page
       reads them, and the input bar and the chat list outside stay as
       they are. */
    --bg-erhoben: var(--glass-card);
    --bg-hoch: var(--glass-card);
    --linie: var(--glass-card-line);
  }
  /* The blur on a layer of its own under the page's content (the page is a
     stacking context, so -1 lies above its ground and below everything in
     it). */
  .seite::before {
    content: '';
    position: absolute;
    /* One pixel inside the page: the fine rim of the edge lies outside
       the layer and stays as sharp as the chat tile's. */
    inset: 1px;
    z-index: -1;
    border-radius: inherit;
    /* Frosted where the page is see-through — a flat frame or drawings
       lie behind it, and Moune's chat tile, which carries no blur, must
       not lend the page its sharpness. A look that mixes its gradient
       into the ground turns the frost off: nothing lies behind the page
       there, and the blur would smooth away the grain the gradient is
       drawn with. */
    -webkit-backdrop-filter: var(--page-frost, none);
    backdrop-filter: var(--page-frost, none);
    pointer-events: none;
  }
  .seite[hidden] {
    display: none;
  }

  /* Narrow: the icon bar stays on the left and the sidebar comes as a
     drawer over it (40) — the page starts beside the bar, as the status
     strip does, and stays under the drawer so a chat can still be reached.
     An open tool sheet (Arbeitsleiste.svelte, 45 on its own) slips under
     the page while it is open, so the page is never hidden behind it. */
  @media (width < 760px) {
    .seite {
      left: 60px;
    }
  }
</style>
