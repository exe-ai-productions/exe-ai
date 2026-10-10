<script>
  /* The body of a window page: it fills the content column of the menu
     page and brings no width of its own, its blocks — head, sections, the
     button row — 28 px apart. The server windows and the cloud pages stand
     in it alike. */
  let { children } = $props()
</script>

<div class="tafel">{@render children?.()}</div>

<style>
  .tafel {
    display: flex;
    flex-direction: column;
    gap: 28px;
  }
</style>
