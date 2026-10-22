<script>
  /* The button of a phone page: as wide as the page, as tall as a row.
     `kind` is `primary` for the one thing the page is for, `danger` for what
     takes something away, and nothing for the rest. */
  let { label, onclick, kind = '', disabled = false } = $props()
</script>

<div class="slot">
  <button class="button {kind}" class:danger={kind === 'danger'} {onclick} {disabled}>{label}</button>
</div>

<style>
  .slot {
    padding: 4px 10px;
  }
  .button {
    width: 100%;
    height: 44px;
  }
  .danger {
    color: var(--rot-text);
  }
</style>
