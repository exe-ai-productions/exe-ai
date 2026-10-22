<script>
  /* The sign-in a page shows before it has a key: the service stands
     beyond the loopback address and hands its key out only against the
     password (app/anmeldung.py, app/api/v1/anmeldung.py).

     Mounted alone by main.js, before the catalogue is loaded — the
     catalogue itself is behind the key — so every word here comes with the
     page (`window.__TEXTE__`, app/main.py). The card is the house's
     question card (QuestionBox.svelte): a veil over the whole page, the
     glass card of the raised ground with the house mark on top, the title,
     the address, the field with the round send button, and the service's
     refusal under the row. Enter sends the field, and the page goes on the
     moment the key is there. */
  import Wortmarke from './Wortmarke.svelte'
  import { api } from '../lib/api.js'

  let { texts = {}, done } = $props()

  let field = $state(null)
  let value = $state('')
  let error = $state('')
  let busy = $state(false)

  // Which service is asking — the address this page was loaded from.
  const address = typeof window !== 'undefined' ? window.location.origin : ''

  $effect(() => {
    setTimeout(() => field?.focus(), 40)
  })

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

<div class="veil">
  <form class="card" autocomplete="off" onsubmit={signIn} aria-labelledby="signin-title">
    <div class="badge" aria-hidden="true"><Wortmarke mitText={false} hoehe={34} /></div>
    <h1 class="title" id="signin-title">{texts.anmeldung_titel ?? 'anmeldung.titel'}</h1>
    <p class="address">{address}</p>
    <label class="label" for="signin-password">{texts.anmeldung_passwort ?? 'anmeldung.passwort'}</label>
    <div class="row">
      <input
        id="signin-password"
        class="field"
        type="password"
        autocomplete="current-password"
        bind:this={field}
        bind:value
        disabled={busy}
      />
      <button class="send" type="submit" disabled={busy || !value.trim()}
              aria-label={texts.anmeldung_knopf ?? 'anmeldung.knopf'}
              title={texts.anmeldung_knopf ?? 'anmeldung.knopf'}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M12 19V5M5 12l7-7 7 7" />
        </svg>
      </button>
    </div>
    {#if error}
      <p class="error" role="alert">{error}</p>
    {/if}
  </form>
</div>

<style>
  /* The veil over the empty page: the look's ground at 45 % with the
     house frost, as the question card's veil over the chat. The card
     stands at the height a window of the house opens at, not centred. */
  .veil {
    position: fixed;
    inset: 0;
    z-index: 70;
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding: 18vh 24px 24px;
    background: color-mix(in srgb, var(--bg) 45%, transparent);
    -webkit-backdrop-filter: var(--kachel-frost);
    backdrop-filter: var(--kachel-frost);
    animation: dawn 0.3s ease both;
  }
  @keyframes dawn { from { opacity: 0; } }

  /* The card: glass in the look's raised ground, one radius like every
     edge in the program, the two soft shadows and no edge line. */
  .card {
    width: min(100%, 520px);
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 28px 28px 36px;
    border-radius: 9px;
    background: color-mix(in srgb, var(--bg-erhoben) 72%, transparent);
    -webkit-backdrop-filter: var(--kachel-frost);
    backdrop-filter: var(--kachel-frost);
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.25), 0 14px 34px rgba(0, 0, 0, 0.55);
    color: var(--text);
    animation: rise 0.46s cubic-bezier(0.32, 0.72, 0.2, 1) both;
  }
  @keyframes rise { from { opacity: 0; transform: translateY(14px) scale(0.97); } }

  /* The house mark on a round glass badge, in the text's colour. */
  .badge {
    display: grid;
    place-items: center;
    width: 52px;
    height: 52px;
    margin: 0 0 12px;
    border-radius: 50%;
    background: var(--glass-button);
    color: var(--text);
  }
  .title {
    margin: 0 0 6px;
    font-size: 22px;
    font-weight: 600;
    letter-spacing: -0.01em;
    line-height: 1.3;
    text-align: center;
    overflow-wrap: anywhere;
  }
  /* Which service is asking, in the fixed face an address is read in. */
  .address {
    margin: 0 0 20px;
    font: 12.5px var(--schrift-fest);
    color: var(--text-still);
    text-align: center;
    overflow-wrap: anywhere;
  }
  .label {
    align-self: stretch;
    margin: 0 0 6px;
    font-size: 12px;
    color: var(--text-leise);
  }
  /* The field and the round button that sends it, as the question card's
     own row: the field on the input glass, no border, the button on
     button glass. */
  .row {
    align-self: stretch;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .field {
    flex: 1;
    min-width: 0;
    height: 40px;
    padding: 0 14px;
    border: none;
    border-radius: 9px;
    outline: none;
    background: var(--kachel-eingabe);
    color: var(--text);
    font: 400 13.5px var(--schrift);
    transition: box-shadow 0.16s;
  }
  .field:focus { box-shadow: inset 0 0 0 1.5px var(--text-leise); }
  .send {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 40px;
    height: 40px;
    border: none;
    border-radius: 50%;
    background: var(--glass-button);
    color: var(--text);
    cursor: pointer;
    transition: background 0.16s, opacity 0.16s, transform 0.16s;
  }
  .send:hover:not(:disabled) { background: var(--glass-hover); transform: translateY(-1px); }
  .send:disabled { opacity: 0.35; cursor: default; }
  /* The refusal, in the state colour for "failed", under the row. */
  .error {
    align-self: stretch;
    margin: 8px 0 0;
    font-size: 12.5px;
    color: var(--rot-text);
  }

  @media (prefers-reduced-motion: reduce) {
    .veil, .card { animation: none; }
    .send, .field { transition: none; }
  }
</style>
