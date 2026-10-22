<script>
  /* The body of a window page: it fills the content column of the menu
     page and brings no width of its own, its blocks — head, sections, the
     button row — 28 px apart. The server windows and the cloud pages stand
     in it alike. `grow` lets it take the room that is left in a page that
     fills its area (a model's parameters under the quick picker). */
  let { children, grow = false } = $props()
</script>

<div class="tafel" class:grow>{@render children?.()}</div>

<style>
  .tafel {
    display: flex;
    flex-direction: column;
    gap: 28px;
  }
  .tafel.grow {
    flex: 1 1 auto;
  }
</style>
