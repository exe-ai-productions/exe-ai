<script>
  /* The program's newer version, offered at the start — in the form of the
     first-start window: the same veil, the same window, the wordmark on
     top, and it grows out of the middle of the chat the same way.

     It stands while the shell says a newer version was found, is being
     fetched or lies ready (lib/updates.svelte.js), and nothing in it acts
     on its own: fetching and installing each take a click. "Later" closes
     it for this start. In a browser there is no shell, so there is no card
     — and while the first-start window still stands, or it is not yet known
     whether it is due, this one waits. */
  import { t, texte } from '../lib/texte.svelte.js'
  import { meldeText } from '../lib/meldewesen.svelte.js'
  import wordmark from '../stil/wordmark.svg'
  import { begruessung, erststartNoetig } from '../lib/begruessung.svelte.js'
  import { releaseNotesHtml } from '../lib/releaseNotes.js'
  import {
    updates, cardShown, chooseLater, downloadUpdate, installUpdate, releaseDate,
  } from '../lib/updates.svelte.js'

  const wanted = $derived(cardShown() && begruessung.geladen && !erststartNoetig())

  /* A step that fails takes the card away: error is no state the card
     stands for. The reason is then said as a notice, in the words the
     settings row uses for it — whichever step it was, a click must not end
     in silence. "Later" takes the card away too, and says nothing. */
  let stood = false
  $effect(() => {
    const stands = cardShown()
    if (stood && !stands && updates.state === 'error') {
      meldeText('updates.failed', { reason: updates.reason }, 'fehler')
    }
    stood = stands
  })
  let phase = $state('off') // off | small | open | closing

  $effect(() => {
    if (wanted && phase === 'off') {
      phase = 'small'
      requestAnimationFrame(() => requestAnimationFrame(() => (phase = 'open')))
    } else if (!wanted && phase === 'open') {
      phase = 'closing'
      setTimeout(() => (phase = 'off'), 600)
    }
  })

  /* The window stands in the middle of the chat, not of the whole screen:
     the veil covers everything, and its padding leaves exactly the chat's
     surface to centre in. Measured again whenever the chat changes size. */
  const shown = $derived(phase !== 'off')
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

  const date = $derived(releaseDate(texte.sprache === 'de' ? 'de-DE' : 'en-GB'))
  /* The notes are somebody else's HTML: only formatted text is let through
     (lib/releaseNotes.js) — no script, no picture, no address. */
  const notes = $derived(releaseNotesHtml(updates.notes))
</script>

{#if shown}
  <div class="veil" class:there={phase === 'open'} style:padding={chatInset}>
    <div class="window" class:small={phase !== 'open'} role="dialog" aria-label={t('updates.title')}>
      <div class="head">
        <img class="wordmark" src={wordmark} width="601" height="180" alt="Exe AI" />
        <div class="title">{t('updates.title')}</div>
        <p class="line">
          {date
            ? t('updates.version_line', { version: updates.found, date })
            : t('updates.version', { version: updates.found })}
        </p>
      </div>
      {#if notes}
        <div class="notes">{@html notes}</div>
      {/if}
      <div class="foot">
        <button class="choice quiet" onclick={chooseLater}>{t('updates.later')}</button>
        {#if updates.state === 'downloaded'}
          <button class="choice" onclick={installUpdate}>{t('updates.install')}</button>
        {:else if updates.state === 'downloading'}
          <div class="progress" role="progressbar" aria-valuemin="0" aria-valuemax="100"
               aria-valuenow={updates.percent} style:--done="{updates.percent}%">
            <span>{t('updates.downloading', { percent: updates.percent })}</span>
          </div>
        {:else}
          <button class="choice" onclick={downloadUpdate}>{t('updates.download')}</button>
        {/if}
      </div>
    </div>
  </div>
{/if}

<style>
  .veil {
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
  .veil.there {
    background: color-mix(in srgb, var(--bg) 55%, transparent);
  }
  .window {
    width: min(440px, calc(100vw - 48px));
    border: 1px solid transparent;
    border-radius: 9px;
    /* The look's own raised surface, solid, as the first-start window
       wears it. */
    background: var(--bg-erhoben);
    box-shadow: 0 0 0 1px var(--linie), 0 28px 70px -12px rgba(0, 0, 0, 0.55);
    padding: 22px 22px 18px;
    transition: transform 0.62s cubic-bezier(0.3, 1.18, 0.35, 1), opacity 0.4s ease;
    transform: none;
    transform-origin: center;
  }
  /* Collapsed it sits as a point on the house mark, a hair above centre. */
  .window.small {
    transform: translateY(-26px) scale(0.03);
    opacity: 0;
    pointer-events: none;
    transition: transform 0.5s cubic-bezier(0.6, 0, 0.8, 0.4), opacity 0.34s 0.14s ease;
  }
  .head { display: flex; flex-direction: column; align-items: center; gap: 7px; margin-bottom: 16px; }
  .wordmark { display: block; width: 100%; height: auto; }
  .title { font: 600 18px var(--schrift); letter-spacing: -0.01em; }
  .line { color: var(--text-still); font-size: 12.5px; margin: 0; }

  /* The notes: one card a step above the window, scrolling in itself where
     a release has much to say, so the two buttons stay in reach. */
  .notes {
    max-height: min(280px, 38vh);
    overflow-y: auto;
    border-radius: 9px;
    background: var(--bg-hoch);
    padding: 12px 16px;
    font-size: 13px;
    line-height: 1.5;
    color: var(--text-leise);
    overflow-wrap: anywhere;
  }
  .notes :global(:first-child) { margin-top: 0; }
  .notes :global(:last-child) { margin-bottom: 0; }
  .notes :global(:is(h1, h2, h3, h4, h5, h6)) {
    font: 600 13.5px var(--schrift);
    color: var(--text);
    margin: 14px 0 6px;
  }
  .notes :global(p) { margin: 0 0 8px; }
  .notes :global(:is(ul, ol)) { margin: 0 0 8px; padding-left: 20px; }
  .notes :global(li) { margin: 2px 0; }
  .notes :global(:is(strong, b)) { font-weight: 600; color: var(--text); }
  .notes :global(code) { font: 12px var(--schrift-fest); }
  .notes :global(pre) { margin: 0 0 8px; white-space: pre-wrap; }
  .notes :global(blockquote) { margin: 0 0 8px; padding-left: 12px; border-left: 2px solid var(--linie); }
  .notes :global(hr) { border: none; border-top: 1px solid var(--linie); margin: 12px 0; }

  /* Two places of the same size, side by side: what closes the card and
     what goes on with the version. */
  .foot { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 14px; }
  .choice,
  .progress {
    box-sizing: border-box;
    min-height: 34px;
    border-radius: 9px;
    font: 500 13px var(--schrift);
    padding: 7px 12px;
  }
  .choice {
    border: 1px solid transparent;
    background: var(--text);
    color: var(--bg);
    cursor: pointer;
  }
  .choice:hover { opacity: 0.88; }
  .choice.quiet {
    background: var(--bg-hoch);
    color: var(--text);
  }
  /* Fetching: running, so blue — quiet on the ground, never the full
     colour behind the words. */
  .progress {
    position: relative;
    overflow: hidden;
    display: grid;
    place-items: center;
    background: color-mix(in srgb, var(--blau) 10%, var(--bg-hoch));
    color: var(--text);
  }
  .progress::before {
    content: '';
    position: absolute;
    inset: 0 auto 0 0;
    width: var(--done);
    background: color-mix(in srgb, var(--blau) 26%, var(--bg-hoch));
    transition: width 0.3s ease;
  }
  .progress span { position: relative; }
</style>
