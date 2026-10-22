<script>
  /* Settings › Web App: the one place that says how the app is reached from
     a phone. Three columns of the height of the phone: on the left the
     setup — status, Tailscale, password, address — and under it the three
     taps that put the app on the Home Screen; in the middle the code to
     scan, large and alone in a tile of glass; on the right the phone with a
     few shots of the phone page.

     Nothing here changes how Exe AI itself listens: the service shows the app
     over https through Tailscale, every request that comes that way needs the
     password, and "Stop service" takes the sharing away again. The address
     and its code exist only while the service runs, so the code's tile
     stands dimmed before that. */
  import { onMount, tick } from 'svelte'
  import { t } from '../lib/texte.svelte.js'
  import { pollWithoutOverlap } from '../lib/pollWithoutOverlap.js'
  import {
    openSignIn, webapp, webappLoad, webappReset, webappSetPassword, webappStartService,
    webappStartTailscale, webappStopService,
  } from '../lib/webapp.svelte.js'
  import Hauszeichen from './Hauszeichen.svelte'
  import Fensterzeichen from './Fensterzeichen.svelte'
  import WebAppPhone from './WebAppPhone.svelte'
  import stepShare from '../assets/web-app/step-share.webp'
  import stepAdd from '../assets/web-app/step-add-to-home-screen.webp'
  import stepOpen from '../assets/web-app/step-home-screen-app.webp'

  /* How the page on the phone becomes an app on its Home Screen: the three
     taps, in order. The caption of each is also the picture's text. The
     pictures are 700 x 982; the address, names and faces of the phone they
     were taken on are blurred out. */
  const HOME_STEPS = [
    { src: stepShare, text: 'webapp.step_share' },
    { src: stepAdd, text: 'webapp.step_add' },
    { src: stepOpen, text: 'webapp.step_open' },
  ]

  /* How often the state is asked for again: a sign-in done in the browser,
     or a Tailscale that went away, shows without anyone touching the page. */
  const POLL_MS = 4000
  /* How long "copied" stays on the copy button. */
  const COPIED_MS = 1600

  let typed = $state('')
  let revealed = $state(false)
  /* The field is locked while a password stands; the pen unlocks it. */
  let changing = $state(false)
  let copied = $state(false)
  let field = $state(null)
  let copiedTimer = null

  const locked = $derived(webapp.password && !changing)
  const connected = $derived(webapp.running && webapp.tailscale.connected)
  const waitingForSignIn = $derived(!webapp.tailscale.connected && !!webapp.tailscale.loginUrl)
  const busy = $derived(webapp.busy !== '')
  /* A refusal of the first read is shown, so it is not put behind the veil. */
  const ready = $derived(webapp.loaded || webapp.error.reason !== '')
  /* The service takes the password without its edges and counts its
     characters, not the halves some of them are written in. */
  const longEnough = $derived([...typed.trim()].length >= webapp.passwordMin)
  /* The rule is said under the open field before anything is typed, not only
     after a refusal. It waits for the service's first answer, which carries
     the number, and it goes while a password stands behind the lock. */
  const showMinimum = $derived(webapp.loaded && !locked && webapp.passwordMin > 0)

  onMount(() => {
    webappReset()
    webappLoad()
    const stop = pollWithoutOverlap(() => (webapp.busy ? undefined : webappLoad()), POLL_MS)
    return () => {
      stop()
      clearTimeout(copiedTimer)
    }
  })

  /* The field empty and hidden again, locked or open for a change. */
  function resetField(open) {
    changing = open
    typed = ''
    revealed = false
  }

  async function setPassword() {
    if (!longEnough || busy) return
    if (await webappSetPassword(typed)) resetField(false)
  }

  /* The pen opens the field with the cursor in it, so Escape is at hand. */
  async function startChange() {
    resetField(true)
    await tick()
    field?.focus()
  }

  /* Escape leaves the change: the field locks again with the password that
     stands. */
  function cancelChange() {
    if (webapp.password) resetField(false)
  }

  function onPasswordKey(event) {
    if (event.key === 'Enter') setPassword()
    else if (event.key === 'Escape' && webapp.password) {
      /* Only the change ends here; the window around the page stays. */
      event.stopPropagation()
      cancelChange()
    }
  }

  const toggleService = () => (webapp.running ? webappStopService() : webappStartService())

  async function copyAddress() {
    try {
      await navigator.clipboard.writeText(webapp.address)
      copied = true
      clearTimeout(copiedTimer)
      copiedTimer = setTimeout(() => (copied = false), COPIED_MS)
    } catch {
      /* The clipboard may be refused; the address stays selectable in the field. */
    }
  }

  /* The reasons the service gives, each with the sentence that says it. A
     reason not in here is still shown, in the general sentence. */
  const ERRORS = {
    no_password: 'webapp.error_no_password',
    password_too_short: 'webapp.error_password_too_short',
    not_available: 'webapp.error_not_available',
    not_answering: 'webapp.error_not_answering',
    not_connected: 'webapp.error_not_connected',
    no_login_address: 'webapp.error_no_login_address',
    port_taken: 'webapp.error_port_taken',
    serve_failed: 'webapp.error_serve_failed',
    failed: 'webapp.error_failed',
    from_this_machine_only: 'webapp.error_from_this_machine_only',
  }
  const errorText = $derived(
    webapp.error.reason
      ? t(ERRORS[webapp.error.reason] ?? 'webapp.error_unknown', { n: webapp.passwordMin })
      : '',
  )
</script>

<div class="content">
  <div class="column">
    <!-- Before the service has answered nothing is known, so nothing can be
         pressed and nothing is claimed. -->
    <section class="section" class:dimmed={!ready} inert={!ready}>
      <div class="tafelkopf">{t('webapp.setup')}</div>
      <div class="group">
        <div class="row">
          <span class="label"><span class="row-icon"><Hauszeichen zeichen="server" groesse={18} /></span>{t('webapp.status')}</span>
          <span class="controls">
            <span class="word" class:green={connected} class:red={!connected}>
              {connected ? t('webapp.connected') : t('webapp.not_connected')}
            </span>
            <button
              class="action"
              disabled={(!webapp.password && !webapp.running) || busy}
              onclick={toggleService}
            >
              {webapp.running ? t('webapp.stop_service') : t('webapp.start_service')}
            </button>
          </span>
        </div>

        <div class="row">
          <span class="label"><span class="row-icon"><Fensterzeichen name="cloud" groesse={18} /></span>{t('webapp.tailscale')}</span>
          <span class="controls">
            {#if webapp.tailscale.connected}
              <span class="word green">{t('webapp.connected')}</span>
            {:else if waitingForSignIn}
              <span class="word yellow">{t('webapp.waiting_for_sign_in')}</span>
              <button class="action" onclick={() => openSignIn(true)}>{t('webapp.sign_in')}</button>
            {:else}
              <span class="word red">{t('webapp.not_connected')}</span>
              <button class="action" disabled={busy} onclick={webappStartTailscale}>
                {t('webapp.start_tailscale')}
              </button>
            {/if}
          </span>
        </div>

        <div class="row">
          <span class="label"><span class="row-icon"><Hauszeichen zeichen="schluessel" groesse={18} /></span>{t('webapp.password')}</span>
          <span class="controls">
            <span class="box">
              {#if locked}
                <input class="input" type="password" value="••••••••" disabled aria-label={t('webapp.password')} />
              {:else}
                <input
                  class="input"
                  type={revealed ? 'text' : 'password'}
                  placeholder={t('webapp.new_password')}
                  aria-label={t('webapp.password')}
                  autocomplete="new-password"
                  aria-describedby={showMinimum ? 'password-minimum' : undefined}
                  bind:this={field}
                  bind:value={typed}
                  onkeydown={onPasswordKey}
                />
                <button
                  class="small"
                  title={revealed ? t('webapp.hide') : t('webapp.show')}
                  aria-label={revealed ? t('webapp.hide') : t('webapp.show')}
                  onclick={() => (revealed = !revealed)}
                >
                  <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"
                       stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M2.5 12C6 6.5 18 6.5 21.5 12 18 17.5 6 17.5 2.5 12Z" /><circle cx="12" cy="12" r="3" />
                    {#if revealed}<path d="M4 4l16 16" />{/if}
                  </svg>
                </button>
              {/if}
            </span>
            {#if locked}
              <button class="square" title={t('webapp.change')} aria-label={t('webapp.change')} onclick={startChange}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                     stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <path d="M17 3l4 4L8 20l-5 1 1-5L17 3z" />
                </svg>
              </button>
            {:else}
              <button class="action" disabled={!longEnough || busy} onclick={setPassword}>{t('webapp.set')}</button>
            {/if}
          </span>
        </div>

        {#if showMinimum}
          <div class="row minimum">
            <span class="label"></span>
            <span class="controls note" id="password-minimum">
              {t('webapp.error_password_too_short', { n: webapp.passwordMin })}
            </span>
          </div>
        {/if}

        <div class="row">
          <span class="label"><span class="row-icon"><Hauszeichen zeichen="handy" groesse={18} /></span>{t('webapp.address')}</span>
          <span class="controls">
            <span class="box address">
              <span class="mono" title={webapp.address}>{webapp.address}</span>
              {#if webapp.running}<span class="network">{t('webapp.tailscale')}</span>{/if}
              <button
                class="small"
                disabled={!webapp.running}
                title={copied ? t('webapp.copied') : t('webapp.copy')}
                aria-label={t('webapp.copy')}
                onclick={copyAddress}
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                     stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  {#if copied}
                    <path d="M20 6L9 17l-5-5" />
                  {:else}
                    <rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V5a2 2 0 012-2h10" />
                  {/if}
                </svg>
              </button>
            </span>
          </span>
        </div>

        {#if errorText}
          <div class="row failure" role="alert">
            <span class="sentence">{errorText}</span>
            {#if webapp.error.detail}<span class="mono detail">{webapp.error.detail}</span>{/if}
          </div>
        {/if}
      </div>
    </section>

    <!-- The steps hold whether the service runs or not, so no veil. -->
    <section class="section grow">
      <div class="tafelkopf">{t('webapp.add_to_home')}</div>
      <ol class="steps">
        {#each HOME_STEPS as step, index}
          <li class="step group">
            <span class="frame">
              <img class="shot" src={step.src} alt={t(step.text)} width="700" height="982" />
            </span>
            <span class="step-caption">
              <span class="number">{index + 1}</span>
              <span class="caption">{t(step.text)}</span>
            </span>
          </li>
        {/each}
      </ol>
    </section>
  </div>

  <section class="qr-tile" class:dimmed={!webapp.running}>
    <div class="tafelkopf">{t('webapp.scan_qr')}</div>
    {#if webapp.qr}
      <div class="code" role="img" aria-label={t('webapp.qr_label')}>
        <!-- The service draws it from the address with the same code that
             shows the address, so nothing the page could be handed lands here. -->
        {@html webapp.qr}
      </div>
    {:else}
      <div class="code" aria-hidden="true"></div>
    {/if}
  </section>

  <WebAppPhone />
</div>

<style>
  /* Three columns as high as the phone, standing together in the middle of
     the page; where they do not fit side by side the page wraps. */
  .content {
    flex: 1;
    display: flex;
    flex-wrap: wrap;
    align-items: stretch;
    align-content: center;
    gap: 40px;
  }
  .column {
    flex: 1;
    min-width: 340px;
    display: flex;
    flex-direction: column;
    gap: 32px;
  }
  .section {
    display: flex;
    flex-direction: column;
    gap: 10px;
    transition: opacity 0.14s;
  }
  /* The last section takes the height that is left. */
  .section.grow {
    flex: 1;
  }
  .section.dimmed {
    opacity: 0.45;
  }
  /* The same card as the other settings pages: card glass with its fine
     line, rows of 56 px divided by a hairline. */
  .group {
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    border-radius: 9px;
  }
  .row {
    min-height: 56px;
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 0 16px;
  }
  .row + .row {
    border-top: 1px solid var(--linie);
  }
  .label {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 12px;
    font: 500 var(--schrift-text) / 1.4 var(--schrift);
    color: var(--text);
  }
  /* The sign before a row's name: 18 px in a field of 20. */
  .row-icon {
    flex: none;
    width: 20px;
    height: 20px;
    display: grid;
    place-items: center;
    color: var(--text-leise);
  }
  .controls {
    flex: 0 1 380px;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .word {
    flex: 1;
    font-size: 13px;
    font-weight: 500;
  }
  /* Colour means state: connected is green, waiting yellow, not connected
     red — the words in the form made for type. */
  .word.green {
    color: var(--gruen-text);
  }
  .word.yellow {
    color: var(--gelb-text);
  }
  .word.red {
    color: var(--rot-text);
  }
  .action {
    flex: none;
    height: 32px;
    padding: 0 14px;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    color: var(--text-leise);
    font: inherit;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.14s, color 0.14s;
  }
  .action:hover:not(:disabled) {
    background: var(--glass-hover);
    color: var(--text);
  }
  .action:disabled,
  .small:disabled {
    opacity: 0.45;
    cursor: default;
  }
  .square {
    flex: none;
    width: 32px;
    height: 32px;
    display: grid;
    place-items: center;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    color: var(--text-leise);
    cursor: pointer;
  }
  .square:hover {
    background: var(--glass-hover);
    color: var(--text);
  }
  .box {
    flex: 1;
    min-width: 0;
    height: 32px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 0 4px 0 10px;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
  }
  .input {
    flex: 1;
    min-width: 0;
    padding: 0;
    border: none;
    outline: none;
    background: none;
    color: var(--text);
    font: inherit;
    font-size: 13px;
  }
  .input::placeholder {
    color: var(--text-still);
  }
  .input:disabled {
    color: var(--text-leise);
  }
  .small {
    flex: none;
    width: 26px;
    height: 26px;
    display: grid;
    place-items: center;
    border: none;
    border-radius: 6px;
    background: none;
    color: var(--text-still);
    cursor: pointer;
  }
  .small:hover:not(:disabled) {
    color: var(--text);
  }
  .address {
    color: var(--text-leise);
  }
  .mono {
    font-family: var(--schrift-fest);
    font-size: 12.5px;
  }
  .address .mono {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .network {
    flex: none;
    padding: 0 4px;
    font-size: 12px;
    color: var(--text-still);
  }
  /* Under the password row, in the column of its field, without a line of its
     own: the sentence belongs to that row. */
  .row.minimum {
    min-height: 0;
    margin-top: -8px;
    padding-bottom: 12px;
    border-top: none;
  }
  .note {
    font-size: 13px;
    line-height: 1.5;
    color: var(--text-still);
  }
  .failure {
    flex-direction: column;
    align-items: flex-start;
    justify-content: center;
    gap: 2px;
    padding: 10px 16px;
  }
  .sentence {
    font-size: 13px;
    color: var(--rot-text);
  }
  .detail {
    color: var(--text-leise);
    user-select: text;
    overflow-wrap: anywhere;
  }
  /* The code to scan: large and alone in a tile of glass, its head at the
     upper left. A code is read in dark on light whatever the look is, so the
     square keeps its own two values; the light edge round it is the quiet
     zone the code itself does not carry. */
  .qr-tile {
    position: relative;
    flex: none;
    box-sizing: border-box;
    width: 440px;
    max-width: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 18px 20px;
    border-radius: 16px;
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    backdrop-filter: blur(18px);
    transition: opacity 0.14s;
  }
  .qr-tile.dimmed {
    opacity: 0.45;
  }
  .qr-tile .tafelkopf {
    position: absolute;
    top: 18px;
    left: 20px;
    margin: 0;
  }
  .code {
    box-sizing: content-box;
    flex: none;
    width: 320px;
    height: 320px;
    padding: 10px;
    border-radius: 14px;
    background: #f4f3ee;
  }
  .code :global(svg) {
    display: block;
    width: 100%;
    height: 100%;
    shape-rendering: crispEdges;
  }
  /* Three equal tiles of glass in a row, as high as the room that is left;
     each holds a picture and, under it, its number and its sentence. */
  .steps {
    flex: 1;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 16px;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .step {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 14px;
    min-width: 0;
    padding: 18px 12px 16px;
    border-radius: 16px;
  }
  /* The picture whole and in its proportions, 322 px high where the tile has
     the room and smaller where it has not, in the dark body of a phone that
     is the same in every look. */
  .frame {
    box-sizing: border-box;
    width: min(100%, calc(322px * 700 / 982 + 10px));
    padding: 5px;
    border-radius: 22px;
    background: #0b0b0b;
    box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.1), 0 10px 26px rgba(0, 0, 0, 0.45);
  }
  .shot {
    display: block;
    width: 100%;
    height: auto;
    aspect-ratio: 700 / 982;
    border-radius: 17px;
  }
  .step-caption {
    max-width: 100%;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .number {
    flex: none;
    width: 22px;
    height: 22px;
    display: grid;
    place-items: center;
    border-radius: 50%;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    font-size: 12px;
    font-weight: 600;
    line-height: 1;
    color: var(--text-leise);
  }
  .caption {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 13px;
    color: var(--text-leise);
  }
</style>
