<script>
  /* A fact on a line: its name on the left, its value on the right, in the
     quiet ink. Nothing here can be tapped. */
  let { label, value = '' } = $props()
</script>

<div class="line">
  <span class="label">{label}</span>
  <span class="value">{value}</span>
</div>

<style>
  .line {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 36px;
    padding: 4px 12px 4px 10px;
    font: 400 var(--schrift-text) var(--schrift);
  }
  .label {
    flex: 0 1 auto;
    min-width: 0;
    overflow-wrap: anywhere;
    color: var(--text-leise);
  }
  .value {
    flex: 1;
    min-width: 0;
    text-align: right;
    color: var(--text-still);
    font-variant-numeric: tabular-nums;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
