<script>
  /* A heading and the rows under it, as the lists of a phone page are laid
     out: the heading quiet above, the rows one under the other. */
  let { title = '', children } = $props()
</script>

{#if title}<div class="heading">{title}</div>{/if}
<div class="group">{@render children?.()}</div>

<style>
  .heading {
    margin: 16px 10px 4px;
    font: 500 var(--schrift-hinweis) var(--schrift);
    color: var(--text-still);
  }
  .group {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
</style>
