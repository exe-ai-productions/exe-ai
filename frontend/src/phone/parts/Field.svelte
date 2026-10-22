<script>
  /* A field with its name above it. The text is 16 px: a smaller field
     makes the phone zoom the page in the moment it is touched. */
  let {
    label,
    value = $bindable(),
    type = 'text',
    inputmode = undefined,
    disabled = false,
    secret = false,
    onchange = null,
    oninput = null,
    placeholder = undefined,
    ariaLabel = undefined,
  } = $props()
</script>

<label class="field">
  <span class="label">{label}</span>
  <input
    class="input"
    type={secret ? 'password' : type}
    {inputmode}
    {disabled}
    {placeholder}
    aria-label={ariaLabel}
    bind:value
    {onchange}
    {oninput}
    autocomplete="off"
    autocapitalize="off"
    spellcheck="false"
  />
</label>

<style>
  .field {
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
    height: 44px;
    box-sizing: border-box;
    padding: 0 12px;
    border: 1px solid var(--feldstrich);
    border-radius: 9px;
    background: var(--glass-button);
    color: var(--text);
    font: 400 16px var(--schrift);
  }
  .input:focus {
    outline: 2px solid var(--linie-stark);
    outline-offset: -2px;
  }
  .input:disabled {
    opacity: 0.6;
  }
</style>
