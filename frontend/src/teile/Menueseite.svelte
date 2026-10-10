<script>
  /* The frame a menu page's content stands in: on top the head of what is
     chosen, under it its content.

     The page's sections do NOT stand here: they belong to the sidebar,
     which shows them in place of the chat list while a menu is open. This
     frame hands the section snippet over to it (`zustand.menuSections`)
     and takes it down again when the page goes — the sidebar draws it
     above the window row. One snippet in, one snippet out, so the pages
     themselves see no difference.

     `beschriftung` names the section column for assistive technology.
     `fuellen` makes the content a column at least as tall as the page, for
     a page whose editor takes the room that is left (the settings).
     `festeHoehe` makes it exactly as tall, for a part that scrolls inside
     itself instead of with the page (the tools list beside its detail). */
  import { rollfade } from '../lib/rollfade.js'
  import { zustand } from '../lib/zustand.svelte.js'

  let { offen = true, liste, kopf, inhalt, beschriftung = '', fuellen = false, festeHoehe = false } = $props()

  /* `offen` is what keeps this honest for a page whose frame stays mounted
     while its menu is closed (the catalogue, whose version choice and
     scroll must survive a look away): the slot follows it. Pages that
     mount their frame inside `{#if offen}` need no prop — mounting is
     opening. */
  $effect(() => {
    if (offen) {
      zustand.menuSections = { snippet: liste, label: beschriftung }
      return () => {
        /* Only take down what this frame put up: by the time two frames
           swap places the slot may already hold a younger one. */
        if (zustand.menuSections?.snippet === liste) zustand.menuSections = null
      }
    }
    /* A frame that is mounted but closed takes down nothing that is not
       its own: the next menu's frame may already stand in the slot — the
       catalogue's frame runs its effect in the same flush as the younger
       menu's, just later in tree order, and an unguarded write here wiped
       the fresh sections away (measured: catalogue to cloud). */
    if (zustand.menuSections?.snippet === liste) zustand.menuSections = null
  })
</script>

<div class="rechts">
  <header class="kopf">
    {@render kopf?.()}
  </header>
  <div class="inhalt" use:rollfade>
    <div class="breite" class:fuellen class:festeHoehe>
      {@render inhalt?.()}
    </div>
  </div>
</div>

<style>
  /* The content's ground and its rounded corners come from the frame that
     encloses the page (Seitenrahmen.svelte, radius 9 all around): the
     sections no longer stand beside the content inside the page, so
     nothing joins its left edge and no corner rule is needed here. */
  .rechts {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .kopf,
  .breite {
    width: 100%;
    /* 1336 of content between the two side paddings. */
    max-width: 1400px;
    margin: 0 auto;
    padding-left: 32px;
    padding-right: 32px;
    box-sizing: border-box;
  }
  /* What stands in the head sits side by side and goes under one another
     where the room runs out. */
  .kopf {
    flex: none;
    display: flex;
    flex-wrap: wrap;
    align-items: flex-start;
    gap: 12px 18px;
    padding-top: 26px;
    padding-bottom: 18px;
  }
  /* The content scrolls under a head that stays; the room at its foot keeps
     the last row clear of the status strip that lies over the bottom edge. */
  .inhalt {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
  }
  .breite {
    padding-top: 4px;
    padding-bottom: 56px;
  }
  .breite.fuellen {
    display: flex;
    flex-direction: column;
    min-height: 100%;
  }
  .breite.festeHoehe {
    height: 100%;
  }

  /* Narrow: the content keeps its card, only its side room shrinks. */
  @media (max-width: 720px) {
    .kopf,
    .breite {
      padding-left: 16px;
      padding-right: 16px;
    }
  }
</style>
