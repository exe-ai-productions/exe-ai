<script>
  /* The phone page: what Exe AI shows in a window under 600 px wide or on a
     device whose short side is under 500 px (device.js). It drives the same
     service as the desktop page — the same state, the same ways to the
     machine — and brings only its own views: the head, the chat list as a
     drawer, the sheets, the notices and the question window.

     It starts what the desktop page starts: the look and the model last in
     use, the models, the chats, the notices and the live line. */
  import { untrack } from 'svelte'
  import { t } from '../lib/texte.svelte.js'
  import Meldungen from '../teile/Meldungen.svelte'
  import Bildschau from '../teile/Bildschau.svelte'
  import Header from './Header.svelte'
  import ChatView from './ChatView.svelte'
  import PageFrame from './PageFrame.svelte'
  import WorkBar from './WorkBar.svelte'
  import AuftragBestaetigen from '../teile/AuftragBestaetigen.svelte'
  import AuftragStarten from '../teile/AuftragStarten.svelte'
  import Protokollfenster from '../teile/Protokollfenster.svelte'
  import { work, workClose } from './workbar.svelte.js'
  import { verbinden as followTerminal } from '../lib/terminalfenster.svelte.js'
  import Drawer from './Drawer.svelte'
  import Ask from './Ask.svelte'
  import FirstStart from './FirstStart.svelte'
  import { phone, drawerSet, lookPick } from './phone.svelte.js'
  import { openPage, pageClose } from './pages.svelte.js'
  import { phoneLook } from './look.js'
  import { listenForSwipes } from './swipe.js'
  import {
    zustand, melde, modelleLaden, featuresLaden, chatsLaden, auftraegeStillLaden,
    darstellungAnwenden, modellAnwenden, rahmenNeuZeichnen,
  } from '../lib/zustand.svelte.js'
  import { anzeigeLaden, modusSpeichern, startModus } from '../lib/anzeige.js'
  import { begruessungLaden } from '../lib/begruessung.svelte.js'
  import { klangwahlLaden } from '../lib/klaenge.svelte.js'
  import { meldewesenLaden } from '../lib/meldewesen.svelte.js'
  import { auftraegeBeobachten } from '../lib/auftragsmelder.js'
  import { verbinden as connectEvents, trennen as disconnectEvents } from '../lib/ereignisstrom.svelte.js'

  /* The look the desktop stands on, as the service handed it out. The phone
     page narrows it to Exe, Pearl or Snow for what it draws (look.js) and writes
     back only what the person chose here. */
  let mode = $state(startModus())
  let savedMode = null
  let deviceDark = $state(window.matchMedia('(prefers-color-scheme: dark)').matches)
  const look = $derived(phoneLook(mode, deviceDark))

  $effect(() => {
    document.documentElement.setAttribute('data-modus', look)
    /* The desktop page may have left the own gradient's marks on the root
       (its attribute and colours); drawing the frame for Exe or Pearl takes
       them away, so only the look's own values stand. */
    untrack(() => rahmenNeuZeichnen(look))
  })
  $effect(() => {
    const query = window.matchMedia('(prefers-color-scheme: dark)')
    const change = (event) => (deviceDark = event.matches)
    query.addEventListener('change', change)
    return () => query.removeEventListener('change', change)
  })

  /* The terminal's runs follow the open chat, so the work bar and the dot on
     its button have something to show. */
  $effect(() => {
    followTerminal(zustand.aktiverChat)
  })

  /* Nothing is written before the first read has come back, and what comes
     back is not written straight back either: only a change made here goes
     out. */
  $effect(() => {
    const now = mode
    if (savedMode !== null && now !== savedMode) {
      savedMode = now
      modusSpeichern(now)
    }
  })
  /* A look picked before the first read has come back is the person's word
     and wins over what that read brings. */
  let picked = false
  function chooseLook(value) {
    picked = true
    mode = value
  }
  /* The settings page picks a look and reads the one standing; this page
     holds it. */
  $effect(() => {
    lookPick.mode = mode
  })
  /* The look drawn changes with the device too, not only with the choice. */
  $effect(() => {
    lookPick.drawn = look
  })
  $effect(() => {
    if (lookPick.count) untrack(() => chooseLook(lookPick.value))
  })

  /* The look, the model last in use, in one read. The model has to be known
     before modelleLaden() runs, or that would find none set and pick the
     first of the list instead. */
  async function adoptDisplay() {
    const loaded = await anzeigeLaden()
    if (loaded) {
      darstellungAnwenden(loaded.darstellung)
      modellAnwenden(loaded.modell)
      if (!picked) mode = loaded.modus
    }
    savedMode = mode
    if (picked) modusSpeichern(mode)
  }

  begruessungLaden()

  $effect(() => {
    /* Untracked: the loaders read state (the chat list reads the search
       text), and a start that ran again on every keystroke would reload the
       page's whole state each time. */
    untrack(() => {
      adoptDisplay().then(modelleLaden)
      featuresLaden()
      chatsLaden()
      auftraegeStillLaden()
      klangwahlLaden()
      meldewesenLaden()
      /* The live line for everything that is not one chat's business. */
      connectEvents()
    })
    const clock = setInterval(modelleLaden, 30000)
    return () => {
      clearInterval(clock)
      disconnectEvents()
    }
  })

  /* A run that ended announces itself; what to say, and whether anything is
     said at all, belongs to the modules behind this. */
  $effect(() => {
    auftraegeBeobachten(zustand.auftraege)
  })

  /* A window standing over the page — a sheet, the question, the first
     start — takes the finger's swipes for itself. */
  const windowStands = () => Boolean(document.querySelector('[aria-modal="true"]'))
  $effect(() =>
    listenForSwipes(
      () => phone.drawer,
      (direction) => {
        if (!windowStands()) drawerSet(direction === 'open')
      },
    ),
  )

  const page = $derived(openPage())

  /* The keyboard on a phone does not shrink the page, it covers it. The page
     is therefore sized to what is seen (the visual viewport), so the bar
     stays on top of the keyboard and the history keeps the room that is
     left. */
  let seen = $state({ top: 0, height: null, zoomed: false })
  const keyboard = $derived(
    seen.height !== null && !seen.zoomed && window.innerHeight - seen.height - seen.top > 80,
  )
  $effect(() => {
    const viewport = window.visualViewport
    if (!viewport) return
    const measure = () => {
      // A pinch-zoom shrinks the visible area too; it is not a keyboard.
      seen = { top: viewport.offsetTop, height: viewport.height, zoomed: viewport.scale > 1.01 }
    }
    measure()
    viewport.addEventListener('resize', measure)
    viewport.addEventListener('scroll', measure)
    return () => {
      viewport.removeEventListener('resize', measure)
      viewport.removeEventListener('scroll', measure)
    }
  })
  $effect(() => {
    document.documentElement.toggleAttribute('data-keyboard', keyboard)
    return () => document.documentElement.removeAttribute('data-keyboard')
  })
  /* The mark the field rule below hangs on: everything that stands on this
     page, the windows and pop-ups of the desktop's parts included. */
  $effect(() => {
    document.documentElement.setAttribute('data-phone', '')
    return () => document.documentElement.removeAttribute('data-phone')
  })

  /* Picking another chat or a page from the drawer ends the work bar's turn:
     it stands over the chat, and what was picked must be what shows. */
  $effect(() => {
    void zustand.aktiverChat
    void page
    untrack(workClose)
  })
</script>

<div class="phone" style:top={keyboard ? `${seen.top}px` : null}
     style:height={keyboard ? `${seen.height}px` : null}>
  {#if page}
    {@const View = page.view}
    <PageFrame title={t(page.title)} onback={pageClose}>
      <View />
    </PageFrame>
  {:else if work.open}
    <WorkBar />
  {:else}
    <Header />
    <ChatView />
  {/if}
</div>

<Drawer />

<!-- The notices lie over everything but the question window, under the
     status bar: the card stack of the desktop page, moved up to the edge. -->
<div class="notices">
  <Meldungen />
</div>

<Ask />
<Bildschau />
<AuftragBestaetigen />
<AuftragStarten bind:offen={zustand.auftragStartenOffen} />
<Protokollfenster />
<FirstStart {look} onlook={chooseLook} />

<style>
  /* A phone zooms the page in when a field with text smaller than 16 px takes
     the focus, and the page stays zoomed. The desktop's parts (forms, masks)
     set their own sizes, so on this page every text field is raised to 16 px,
     whatever its part says. */
  :global(html[data-phone] input:not([type='checkbox'], [type='radio'], [type='range'], [type='color'], [type='file'])),
  :global(html[data-phone] textarea),
  :global(html[data-phone] select) {
    font-size: 16px !important;
  }
  .phone {
    position: fixed;
    inset: 0;
    display: flex;
    flex-direction: column;
    /* The frame: the head stands on it and the chat lies on it as a tile. */
    background: var(--frame, var(--bg));
    color: var(--text);
    font-size: var(--schrift-text);
    -webkit-tap-highlight-color: transparent;
    touch-action: manipulation;
    overscroll-behavior: none;
  }
  .notices {
    position: fixed;
    inset: 0;
    z-index: 55;
    pointer-events: none;
  }
  .notices :global(.stapel) {
    padding-top: calc(env(safe-area-inset-top) + 8px);
  }
</style>
