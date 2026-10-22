<script>
  /* The section "llama.cpp" of a server window: the build of the program
     the server starts, and what can be done about it, in the order it is
     done — look for a newer build, fetch the one that was found, go back to
     the tested one. Without a program the section holds the one button that
     fetches it.

     Every server of this program starts the same llama.cpp, so the section
     is one piece that stands in the window of each of them. A press in one
     window is a press for all: the routes it uses are the program's, not a
     server's (`/runner/programm`).

     `auskunft` is the window's own answer about its server; this section
     reads only `programm`, `version`, `updatable` and `restorable` from it —
     the same four fields every server answers (`ProgramState`). The window
     keeps its answer fresh, and `onrefresh` asks it to read once more at the
     end of a fetch — a window that keeps no beat of its own would otherwise
     go on naming the build that was there.

     Asked only when a button is pressed, never on opening and never on a
     timer: nothing looks for updates by itself. */
  import { api } from '../lib/api.js'
  import { pollWithoutOverlap } from '../lib/pollWithoutOverlap.js'
  import { t } from '../lib/texte.svelte.js'
  import { melde } from '../lib/zustand.svelte.js'
  import BuildRows from './BuildRows.svelte'
  import Serverabschnitt from './Serverabschnitt.svelte'
  import UpToDateMark from './UpToDateMark.svelte'
  import UpdateButton from './UpdateButton.svelte'

  let { auskunft = null, onrefresh = null } = $props()

  const hasProgram = $derived(Boolean(auskunft?.programm))

  /* The fetch in progress, as the server reports it. Read once on opening —
     a fetch another window started shows its bar here too — and then every
     two seconds, but only while a fetch is on its way. */
  let programState = $state(null)
  const fetching = $derived(
    Boolean(programState) && !programState.fertig && !programState.fehler,
  )

  async function readState() {
    try {
      programState = await api.serverProgrammStand()
    } catch {
      /* The window's own reading says when the server is unreachable. */
    }
  }
  readState()

  $effect(() => {
    if (!fetching) return
    return pollWithoutOverlap(readState, 2000)
  })

  /* The builds of the server this machine could fetch — a list only on
     Windows on x64, empty everywhere else — the one that was fetched, and
     the builds it cannot run, which a Mac names so that they are seen. Read
     once and again whenever a fetch ends. */
  let variants = $state(null)
  async function loadVariants() {
    try {
      variants = await api.serverProgrammVarianten()
    } catch {
      variants = null
    }
  }
  loadVariants()

  /* The list stands where the server is ours to choose: with no program at
     all, or where the fetched copy is the one that starts. Beside a program
     the settings name, or an installed one that comes first, a fetched
     build would never run — nothing is offered. */
  const showVariants = $derived(
    Boolean(variants?.varianten?.length) && (!hasProgram || Boolean(auskunft?.updatable)),
  )

  /* The rows drawn: the list to fetch from, or the greyed builds where
     none can be fetched. */
  const locked = $derived(!showVariants && Boolean(variants?.unavailable?.length))
  const builds = $derived(showVariants ? variants.varianten : (variants?.unavailable ?? []))

  function fetchProgram(variant) {
    api
      .serverProgrammHolen(variant)
      .then((s) => (programState = s))
      .catch((f) => melde(f.message, 'fehler'))
  }

  /* Whether a newer build of the server program exists. */
  let updateAnswer = $state(null)
  let checking = $state(false)

  // Only the newest check may answer: a fetch landing meanwhile clears the
  // answer, and an older one arriving after that must not bring it back.
  let checkRun = 0

  async function checkForUpdate() {
    const run = ++checkRun
    checking = true
    // The last answer goes while the new one is asked, so it cannot stand
    // beside the running check as if it were its result.
    updateAnswer = null
    try {
      const answer = await api.serverProgramUpdateCheck()
      if (run === checkRun) {
        updateAnswer = answer
        // A list that could not be read compares nothing: said at the top,
        // so the button does not look as if it did nothing.
        if (answer.unreadable) melde(t('bildserver.updates_nicht_pruefbar'), 'fehler')
      }
    } catch (fehler) {
      if (run === checkRun) melde(fehler.message, 'fehler')
    } finally {
      if (run === checkRun) checking = false
    }
  }

  /* Once a fetch actually FINISHES the last answer is cleared — it spoke of
     the build before, and the next press asks again. A fetch that failed
     says so: the version row still names the build that was there, and
     without a word it would look as if nothing had been tried. */
  let fetchingBefore = false
  $effect(() => {
    if (fetchingBefore && !fetching) {
      updateAnswer = null
      checkRun += 1
      checking = false
      if (programState?.fehler) melde(t('bildserver.generator_fehler'), 'fehler')
      loadVariants()
      onrefresh?.()
    }
    fetchingBefore = fetching
  })

  /* The server reads the release list again itself rather than trust the
     build this window showed a moment ago, so a stale offer never fetches
     what is already there. */
  function updateProgram() {
    api.serverProgramUpdate().then((s) => (programState = s)).catch((f) => melde(f.message, 'fehler'))
  }

  /* The way back from an update: the tested build takes the place of the
     newer one. Offered only while a fetched build other than the tested one
     runs (`auskunft.restorable`). */
  function restoreProgram() {
    api.serverProgramRestore().then((s) => (programState = s)).catch((f) => melde(f.message, 'fehler'))
  }
</script>

<!-- The program every server of this program starts, in one row: the word
     "Version" on the left, what can be done about the build in the middle
     — the sign that asks for a newer one and then fetches it, and the answer
     "up to date" beside it — and at the end the build that starts, a dash for
     a program that does not say which build it is.

     The check stands only where a fetched copy would be the program that
     starts; beside a program the settings name, or an installed one that
     comes first, the build is named and nothing is offered.

     The section stands whether the program is there or not: without it the
     row holds the one button that fetches it. -->
<Serverabschnitt zeichen="server" titel="llama.cpp">
  <div class="zeile">
    <span class="name">{t('bildserver.version_label')}</span>
    {#if hasProgram}
      {#if auskunft.updatable}
        {#if updateAnswer?.aktuell}
          <UpToDateMark />
        {/if}
        <UpdateButton found={Boolean(updateAnswer?.verfuegbar)} locked={checking || fetching}
                      oncheck={checkForUpdate} onupdate={updateProgram} />
      {/if}
    {:else if showVariants}
      <!-- The list below is the way to fetch it. -->
    {:else if fetching}
      <!-- The program on its way down: the bar and its share after the
           dash, where the sign stands otherwise. -->
      <span class="balken"><i style="width:{Math.round(programState.anteil * 100)}%"></i></span>
      <span class="balkenzahl">{Math.round(programState.anteil * 100)} %</span>
    {:else}
      <!-- No program: the one button that fetches it, at the right end of
           the row where the check stands once there is one. A fetch that
           ended in an error says so beside the button that tries again;
           without it the button simply stood there again, as if nothing had
           been tried. -->
      {#if programState?.fehler}
        <span class="v_fehler">{t('bildserver.generator_fehler')}</span>
      {/if}
      <span class="buttons">
        <button class="feldknopf" onclick={() => fetchProgram()}>{t('modell.server_download')}</button>
      </span>
    {/if}
    <span class="versionsmarke">{auskunft?.version ?? '-'}</span>
  </div>
  <!-- The builds of the server, as the picture generator lists its own — the
       CPU build runs everywhere and is the one a first fetch brings; the
       others use the graphics card. On a Mac they stand greyed, and the way
       back to the tested build stands under a fold. -->
  <BuildRows {builds} installed={variants?.installiert} {locked} busy={fetching}
             restorable={hasProgram && Boolean(auskunft?.restorable)}
             onDownload={fetchProgram} onRestore={restoreProgram}>
    {#snippet status()}
      {#if showVariants}
        {#if fetching}
          <div class="zeile">
            <span class="balken"><i style="width:{Math.round(programState.anteil * 100)}%"></i></span>
            <span class="balkenzahl">{Math.round(programState.anteil * 100)} %</span>
          </div>
        {:else if programState?.fehler}
          <div class="zeile"><span class="name v_fehler">{t('bildserver.generator_fehler')}</span></div>
        {/if}
      {/if}
    {/snippet}
  </BuildRows>
</Serverabschnitt>

<style>
  /* A fetch that failed, in the colour of a failure — the red of a sentence,
     beside the button and in the list of the builds. In the list the sentence
     is also a name, and the card's rule for names (Serverabschnitt.svelte)
     weighs as much as a lone class rule here, so the order of the built
     styles would decide; the second class of the `:is` makes this rule the
     heavier one. */
  .zeile :is(.v_fehler, .name.v_fehler) {
    color: var(--rot-text);
  }
  .balken {
    flex: 1;
    height: 5px;
    border-radius: 9px;
    background: var(--linie);
    overflow: hidden;
  }
  .balken i {
    display: block;
    height: 100%;
    background: var(--blau);
    transition: width 0.3s;
  }
  .balkenzahl {
    font: 400 11px var(--schrift-fest);
    color: var(--text-still);
    white-space: nowrap;
  }
</style>
