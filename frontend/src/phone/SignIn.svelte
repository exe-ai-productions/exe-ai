<script>
  /* The sign-in of the phone page: shown before the page has a key, when the
     service stands beyond the loopback address and hands its key out only
     against the password.

     One page, one field, one button — the phone's way of pairing with a
     machine. Mounted alone by main.js before the catalogue is loaded (the
     catalogue itself is behind the key), so every word here comes with the
     page (`window.__TEXTE__`). The page goes on the moment the key is
     there. */
  import Wortmarke from '../teile/Wortmarke.svelte'
  import { api } from '../lib/api.js'

  let { texts = {}, done } = $props()

  let field = $state(null)
  let value = $state('')
  let error = $state('')
  let busy = $state(false)

  // Which service is asking — the address this page was loaded from.
  const address = typeof window !== 'undefined' ? window.location.origin : ''

  async function signIn(event) {
    event.preventDefault()
    if (busy || !value.trim()) return
    busy = true
    error = ''
    try {
      await api.signIn(value)
    } catch (reason) {
      error = reason?.message ?? String(reason)
      field?.select()
      return
    } finally {
      busy = false
    }
    // The key is kept by the API module; the page only needs to know it is there.
    done()
  }
</script>

<form class="page" autocomplete="off" onsubmit={signIn} aria-labelledby="signin-title">
  <div class="badge" aria-hidden="true"><Wortmarke mitText={false} hoehe={34} /></div>
  <h1 id="signin-title">{texts.anmeldung_titel ?? 'anmeldung.titel'}</h1>
  <p class="address">{address}</p>
  <label for="signin-password">{texts.anmeldung_passwort ?? 'anmeldung.passwort'}</label>
  <input
    id="signin-password"
    type="password"
    autocomplete="current-password"
    bind:this={field}
    bind:value
    disabled={busy}
  />
  {#if error}
    <p class="error" role="alert">{error}</p>
  {/if}
  <button type="submit" disabled={busy || !value.trim()}>
    {texts.anmeldung_knopf ?? 'anmeldung.knopf'}
  </button>
</form>

<style>
  .page {
    position: fixed;
    inset: 0;
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding: calc(24px + env(safe-area-inset-top)) 24px calc(24px + env(safe-area-inset-bottom));
    background: var(--bg);
    color: var(--text);
    -webkit-tap-highlight-color: transparent;
  }
  /* The house mark on a round glass badge, in the text's colour. */
  .badge {
    align-self: center;
    display: grid;
    place-items: center;
    width: 52px;
    height: 52px;
    margin-bottom: 12px;
    border-radius: 50%;
    background: var(--glass-button);
  }
  h1 {
    margin: 0 0 6px;
    font: 600 22px/1.3 var(--schrift);
    letter-spacing: -0.01em;
    text-align: center;
  }
  /* Which service is asking, in the fixed face an address is read in. */
  .address {
    margin: 0 0 24px;
    font: 12.5px var(--schrift-fest);
    color: var(--text-still);
    text-align: center;
    overflow-wrap: anywhere;
  }
  label {
    margin: 0 0 6px;
    font: 500 var(--schrift-hinweis) var(--schrift);
    color: var(--text-leise);
  }
  input {
    width: 100%;
    height: 48px;
    padding: 0 14px;
    border: none;
    border-radius: 9px;
    outline: none;
    background: var(--kachel-eingabe);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    color: var(--text);
    /* 16 px: a smaller field makes the phone zoom the page in on focus. */
    font: 400 16px var(--schrift);
  }
  input:focus {
    box-shadow: inset 0 0 0 1.5px var(--text-leise);
  }
  .error {
    margin: 8px 0 0;
    font-size: var(--schrift-hinweis);
    color: var(--rot-text);
  }
  button {
    height: 48px;
    margin-top: 16px;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    font: 500 14px var(--schrift);
  }
  button:active:not(:disabled) {
    background: var(--glass-hover);
  }
  button:disabled {
    opacity: 0.5;
  }
</style>
