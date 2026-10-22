<script>
  /* A text area with its name above it, for the instructions a person types
     at length. The text is 16 px, like the field: a smaller one makes the
     phone zoom the page in the moment it is touched. `onchange` fires when
     the focus leaves it. */
  let { label, value = $bindable(''), rows = 4, onchange = null } = $props()
</script>

<label class="area">
  <span class="label">{label}</span>
  <textarea class="input" {rows} bind:value {onchange} spellcheck="false"></textarea>
</label>

<style>
  .area {
    display: block;
    padding: 4px 10px;
  }
  .label {
    display: block;
    margin-bottom: 4px;
    font: 500 var(--schrift-hinweis) var(--schrift);
    color: var(--text-still);
  }
  .input {
    display: block;
    width: 100%;
    box-sizing: border-box;
    padding: 10px 12px;
    border: 1px solid var(--feldstrich);
    border-radius: 9px;
    background: var(--glass-button);
    color: var(--text);
    font: 400 16px var(--schrift);
    line-height: 1.4;
    resize: vertical;
  }
  .input:focus {
    outline: 2px solid var(--linie-stark);
    outline-offset: -2px;
  }
</style>
