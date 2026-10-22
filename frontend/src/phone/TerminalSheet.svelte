<script>
  /* The terminal as a sheet over the chat — what the column is on the
     desktop. A tap on the line of a call in the answer
     (lib/callSelection.svelte.js) raises it; the tool inside is the same
     one the work bar holds, which unfolds and marks the call that was
     tapped and brings it into view.

     It closes with a tap on the veil, with the key, or with the head pulled
     down; the focus goes back to the line that was tapped. */
  import Sheet from './Sheet.svelte'
  import ModulTerminal from '../teile/ModulTerminal.svelte'
  import { t } from '../lib/texte.svelte.js'
  import { terminalSheet, closeTerminalSheet } from '../lib/callSelection.svelte.js'
  import { terminal, terminalGesehen } from '../lib/terminalfenster.svelte.js'

  /* How far the head has to go down before letting go closes the sheet. */
  const PULL = 72

  /* Looking at the terminal marks its runs as seen, as the open column does
     on the desktop; otherwise a finished run's dot would breathe for good. */
  $effect(() => {
    if (terminalSheet.open && terminal.laeufe) terminalGesehen()
  })

  /* The page going away (the window dragged across the phone width) takes
     the sheet with it: it must not stand open in the state for the next
     time the page is built. */
  $effect(() => () => {
    terminalSheet.open = false
  })

  let pulled = $state(0)
  let from = null

  function down(event) {
    from = event.clientY
    event.currentTarget.setPointerCapture?.(event.pointerId)
  }
  function move(event) {
    if (from == null) return
    pulled = Math.max(0, event.clientY - from)
  }
  function up() {
    if (from == null) return
    const far = pulled >= PULL
    from = null
    pulled = 0
    if (far) closeTerminalSheet()
  }
  function key(event) {
    if (terminalSheet.open && event.key === 'Escape') closeTerminalSheet()
  }
</script>

<svelte:window onkeydown={key} />

<Sheet open={terminalSheet.open} onclose={closeTerminalSheet} label={t('terminal.titel')}>
  <div class="content" style:transform={pulled ? `translateY(${pulled}px)` : null}>
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="head" onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={up}>
      {t('terminal.titel')}
    </div>
    <div class="body">
      <ModulTerminal />
    </div>
  </div>
</Sheet>

<style>
  .content {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .head {
    display: flex;
    align-items: center;
    min-height: 44px;
    padding: 0 2px;
    font: 600 15px var(--schrift);
    /* The finger that pulls the head down moves the sheet, not the page. */
    touch-action: none;
    user-select: none;
  }
  /* The sheet is as high as the list is long, up to a share of the screen;
     the tool brings its own scrolling beyond that. */
  .body {
    max-height: 64dvh;
    display: flex;
    flex-direction: column;
    min-height: 0;
    margin: 0 -18px;
  }
</style>
