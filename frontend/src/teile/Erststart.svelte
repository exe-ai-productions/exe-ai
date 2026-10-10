<script>
  /* The first start — the one window that makes the terminal yours.

     It grows straight out of the house mark in the middle of the empty
     chat and shrinks back into it on Done: the program does not open a
     dialog, its own mark comes toward you. Shown once per installation;
     everything it asks lives in the settings afterwards. */
  import { t, texte, spracheWaehlen } from '../lib/texte.svelte.js'
  import wordmark from '../stil/wordmark.svg'
  import Klappwahl from './Klappwahl.svelte'
  import {
    begruessung, anredeSpeichern, erststartNoetig, erststartErledigt,
  } from '../lib/begruessung.svelte.js'

  let { modus = $bindable('dunkel') } = $props()

  const MODI = [
    ['auto', 'einstellungen.auto'],
    ['hell', 'einstellungen.hell'],
    ['dunkel', 'einstellungen.dunkel'],
    ['darkmatter', 'einstellungen.darkmatter'],
    ['heaven', 'einstellungen.heaven'],
    ['moune', 'einstellungen.moune'],
    ['eigen', 'einstellungen.eigen'],
  ]

  let phase = $state('aus') // aus | klein | auf | zu
  let name = $state('')
  /* The click shows the wish at once, so the pill follows the hand — and it
     falls back to the language that is really loaded the moment the wish is
     gone. `null` means: no switch on its way, the window's own language
     stands. Never a guess: a pill that claims German over an English window
     would lie. */
  let wunsch = $state(null)
  const sprachwahl = $derived(wunsch ?? texte.sprache)
  /* Which attempt is the current one: a click made while an earlier one is
     still on its way takes over, and the earlier one must not report a
     failure for a switch nobody is waiting for anymore. */
  let versuch = 0
  /* What the last switch did — shown IN here: this window's own veil covers
     the toast layer (Meldungen.svelte z-index 25 against the veil's 60), so
     a toast about it would appear dimmed and could not even be closed. */
  let fehler = $state(false)

  /* The window stands in the middle of the chat, not of the whole screen:
     the veil still covers everything, but its padding leaves exactly the
     chat's surface for the grid to centre in. Measured again whenever the
     chat changes size (a column opens or closes) or the window does. */
  const shown = $derived(phase !== 'aus')
  let chatInset = $state('0px')

  $effect(() => {
    if (!shown) return
    const chat = document.querySelector('main')
    if (!chat) return
    const measure = () => {
      const box = chat.getBoundingClientRect()
      const page = document.documentElement
      chatInset = `${box.top}px ${page.clientWidth - box.right}px ${page.clientHeight - box.bottom}px ${box.left}px`
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(chat)
    addEventListener('resize', measure)
    return () => {
      observer.disconnect()
      removeEventListener('resize', measure)
    }
  })

  $effect(() => {
    if (phase === 'aus' && erststartNoetig()) {
      name = begruessung.vorschlag
      phase = 'klein'
      requestAnimationFrame(() => requestAnimationFrame(() => (phase = 'auf')))
    }
  })

  async function spracheStellen(wert) {
    const meiner = ++versuch
    wunsch = wert
    fehler = false
    try {
      await spracheWaehlen(wert)
    } catch {
      /* A switch whose catalogue does not arrive never happens: the wish is
         dropped below, so the pill stands on the language the window
         really speaks — and this says so. */
      if (meiner === versuch) fehler = true
    } finally {
      if (meiner === versuch) wunsch = null
    }
  }

  async function fertig() {
    /* Both of these write the SAME row, and writing a row replaces it —
       so they have to go one after the other. Fired off together, the one
       carrying the name could land first and be overwritten by the one that
       still has none. */
    await erststartErledigt()
    phase = 'zu'
    await anredeSpeichern(name || begruessung.vorschlag, true)
    setTimeout(() => (phase = 'aus'), 600)
  }
</script>

{#if shown}
  <div class="schleier" class:da={phase === 'auf'} style:padding={chatInset}>
    <div class="fenster" class:klein={phase !== 'auf'}>
      <div class="kopf">
        <img class="wordmark" src={wordmark} width="601" height="180" alt="Exe AI" />
        <div class="titel">{t('erststart.titel')}</div>
        <p class="satz">{t('erststart.satz')}</p>
      </div>
      <div class="kachel">
        <span class="strich"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3l4 4L8 20l-5 1 1-5L17 3z" /></svg></span>
        <div class="w"><div class="t">{t('erststart.anrede')}</div><div class="u">{t('erststart.anrede_unter')}</div></div>
        <input class="feld" bind:value={name} placeholder={begruessung.vorschlag} aria-label={t('erststart.anrede')} />
      </div>
      <div class="kachel">
        <span class="strich"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a8 8 0 1 1-4-6.9" /><path d="M15 2l6 1-4 4" /></svg></span>
        <div class="w"><div class="t">{t('erststart.sprache')}</div></div>
        <div class="segment">
          <button aria-pressed={sprachwahl === 'de'} onclick={() => spracheStellen('de')}>{t('einstellungen.sprache_deutsch')}</button>
          <button aria-pressed={sprachwahl === 'en'} onclick={() => spracheStellen('en')}>{t('einstellungen.sprache_englisch')}</button>
        </div>
      </div>
      {#if fehler}
        <!-- IN here, not as a toast: this window's own veil lies over the
             toast layer (Meldungen.svelte z-index 25 against the veil's 60),
             so a toast about this very window would appear dimmed and could
             not even be closed. Same shape as the two other windows that
             report their own failure. -->
        <p class="sprachfehler">{t('fehler.allgemein')}</p>
      {/if}
      <div class="kachel">
        <span class="strich"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9L17 7M7 17l-2.1 2.1" /></svg></span>
        <div class="w"><div class="t">{t('erststart.erscheinung')}</div></div>
        <Klappwahl
          optionen={MODI.map(([wert, schluessel]) => [wert, t(schluessel)])}
          bind:wert={modus}
          beschriftung={t('erststart.erscheinung')}
        />
      </div>
      <div class="fuss">
        <span class="lokal"><span class="punkt"><i></i><em></em></span> {t('erststart.bereit')}</span>
        <button class="button primary" onclick={fertig}>{t('erststart.fertig')}</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .schleier {
    position: fixed;
    inset: 0;
    z-index: 60;
    display: grid;
    place-items: center;
    /* Centred even where the chat is narrower than the window. */
    place-content: center;
    background: transparent;
    transition: background 0.4s ease;
  }
  .schleier.da {
    background: color-mix(in srgb, var(--bg) 55%, transparent);
  }
  .fenster {
    width: min(440px, calc(100vw - 48px));
    border: 1px solid transparent;
    /* 9 — one radius for every edge in the program. A window is no
       different from the controls in it. */
    border-radius: 9px;
    /* The look's own raised surface, solid: the window wears whatever look
       is chosen, so a pick under Appearance shows at once. No backdrop
       filter and, once open, no transform — either one makes this window
       the frame a fixed descendant is placed in, and the Appearance list
       (position: fixed, Klappwahl.svelte) was drawn off the card, out of
       sight. */
    background: var(--bg-erhoben);
    box-shadow: 0 0 0 1px var(--linie), 0 28px 70px -12px rgba(0, 0, 0, 0.55);
    padding: 22px 22px 18px;
    transition: transform 0.62s cubic-bezier(0.3, 1.18, 0.35, 1), opacity 0.4s ease;
    transform: none;
    transform-origin: center;
  }
  /* Collapsed it sits as a point on the house mark, a hair above centre —
     the window breathes out of the mark and back into it. */
  .fenster.klein {
    transform: translateY(-26px) scale(0.03);
    opacity: 0;
    pointer-events: none;
    transition: transform 0.5s cubic-bezier(0.6, 0, 0.8, 0.4), opacity 0.34s 0.14s ease;
  }
  .kopf { display: flex; flex-direction: column; align-items: center; gap: 7px; margin-bottom: 16px; }
  /* As wide as the cards below it. */
  .wordmark { display: block; width: 100%; height: auto; }
  .kopf + .kachel { border-top-left-radius: 9px; border-top-right-radius: 9px; }
  .titel { font: 600 18px var(--schrift); letter-spacing: -0.01em; }
  .satz { color: var(--text-still); font-size: 12.5px; margin: 0; }
  .sprachfehler {
    /* The colour of something that failed (Repo-CLAUDE.md), on the quiet
       surface every other notice sits on — not the full colour behind text. */
    color: var(--rot);
    background: color-mix(in srgb, var(--rot) 12%, var(--bg));
    font-size: 12.5px;
    margin: 0 0 8px;
    padding: 6px 10px;
    border-radius: 9px;
  }
  .kachel {
    /* A step above the window, and the fields in it a step above that —
       all three read from the look, so every look draws its own card. */
    --feld: color-mix(in srgb, var(--text) 7%, var(--bg-hoch));
    display: flex; align-items: center; gap: 12px;
    border: none; border-radius: 0; background: var(--bg-hoch);
    padding: 0 16px; height: 54px; margin-bottom: 0;
  }
  .kachel:has(+ .fuss) {
    border-bottom-left-radius: 9px;
    border-bottom-right-radius: 9px;
  }
  /* The window's own ground between two rows: a line every look draws,
     where the look's --linie sank into the dark rows. */
  .kachel + .kachel {
    border-top: 1px solid var(--bg-erhoben);
  }
  .strich { flex: none; color: var(--text-still); display: grid; place-items: center; }
  .kachel .w { flex: 1; min-width: 0; }
  .kachel .t { font-weight: 600; font-size: 13px; }
  .kachel .u { font-size: 11.5px; color: var(--text-still); }
  /* The Appearance button reads --bg-hoch for its face; inside the card
     that is the card itself, so it takes the field's step instead. */
  .kachel :global(.klappwahl) { --bg-hoch: var(--feld); }
  .feld {
    border: none; border-radius: 9px; background: var(--feld);
    color: var(--text); font: 13px var(--schrift); padding: 6px 11px; width: 130px;
    height: 32px;
  }
  .segment {
    display: flex; border: none; border-radius: 9px;
    background: var(--feld); padding: 3px;
  }
  .segment button {
    border: none; background: none; color: var(--text-leise);
    font: 400 12.5px var(--schrift); padding: 4px 10px; border-radius: 9px; cursor: pointer;
  }
  .segment button[aria-pressed='true'] { background: color-mix(in srgb, var(--text) 14%, var(--feld)); color: var(--text); }
  .fuss { display: flex; align-items: center; gap: 10px; margin-top: 14px; }
  .lokal { display: flex; align-items: center; gap: 7px; font-size: 11.5px; color: var(--text-still); flex: 1; }
  .punkt { display: inline-grid; place-items: center; width: 12px; height: 12px; flex: none; }
  .punkt i { grid-area: 1/1; width: 7px; height: 7px; border-radius: 99px; background: var(--gruen); }
  .punkt em { grid-area: 1/1; width: 11px; height: 11px; border-radius: 99px; border: 1.2px solid var(--text); }
  /* The one button of the window is the house button in its main form
     (`.button.primary`, stil/global.css). */
</style>
