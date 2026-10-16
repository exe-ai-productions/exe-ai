<script>
  /* The CLI tab of the column: the terminal client `exe` against this
     window's own service, drawn by xterm.js with no ground of its own, so
     the column's surface shows through. The drawing and the client outlive
     this component (lib/windowTerminal.js): folding the column or showing
     another tool takes the drawing out of view, coming back brings the
     same drawing back. The terminal tab beside it is something else: the
     log of the chat's tool calls (ModulTerminal.svelte).

     A plain browser has no shell to run a client in, and says so. */
  import '@xterm/xterm/css/xterm.css'
  import { onMount } from 'svelte'
  import { t } from '../lib/texte.svelte.js'
  import { bridge, show, typeDropped } from '../lib/windowTerminal.js'

  let root = $state(null)
  const inWindow = Boolean(bridge())

  onMount(() => (inWindow ? show(root) : undefined))

  /* A file dropped on the tab is typed as a path, the way a terminal of the
     computer types it. Only files: any other drag goes on as it did. A drop
     that was typed stops here: the window catches every drop for the chat's
     attachments, and the same file must not land in both places. One that
     could not be typed (no place on disk) goes on to the window as before. */
  const carriesFiles = (event) => event.dataTransfer?.types?.includes('Files')
  function overTab(event) {
    if (!carriesFiles(event)) return
    event.preventDefault()
    event.dataTransfer.dropEffect = 'copy'
  }
  function dropped(event) {
    if (!carriesFiles(event)) return
    event.preventDefault()
    if (typeDropped(event.dataTransfer.files)) event.stopPropagation()
  }
</script>

{#if inWindow}
  <div class="terminal" role="presentation" bind:this={root} ondragover={overTab} ondrop={dropped}></div>
{:else}
  <p class="hinweis">{t('cli.window.browser')}</p>
{/if}

<style>
  /* Fills the column down to the row of signs; the drawing inside takes
     the whole box. Air at the sides as every view of the column has. */
  .terminal {
    flex: 1;
    min-height: 0;
    padding: 0 var(--rand) 6px;
    overflow: hidden;
  }
  .terminal :global(.xterm-halter),
  .terminal :global(.xterm) {
    height: 100%;
  }
  /* No ground under the drawing in any of its layers: the surface of the
     column is the ground. */
  .terminal :global(.xterm),
  .terminal :global(.xterm .xterm-viewport),
  .terminal :global(.xterm .xterm-screen) {
    background: transparent !important;
  }
  /* The house shows no scrollbars. The drawing would show two: the one of
     its viewport, and a bar of its own at the right edge that fades in
     while it scrolls. Neither is drawn; the wheel and the keys scroll as
     before. */
  .terminal :global(.xterm .xterm-viewport) {
    scrollbar-width: none;
  }
  .terminal :global(.xterm .xterm-viewport::-webkit-scrollbar) {
    display: none;
  }
  .terminal :global(.xterm .xterm-scrollable-element > .scrollbar) {
    display: none;
  }
  .hinweis {
    margin: 14px var(--rand);
    font-size: 13px;
    color: var(--text-still);
  }
</style>
