<script>
  /* The terminal module: everything this chat has had done for it.

     It used to show shell commands and nothing else, which meant a
     conversation spent reading and writing files reported "no command has
     run yet" — empty and wrong. Now every tool call of the chat stands
     here, whatever its source: the five built-in ones, the question tool,
     the memory, and every server in the tool window.

     Two weights, and the difference is deliberate. A run with live output
     is a big entry — there is something to watch. Every other call is one
     quiet line: which tool, what about, and how it ended. Together they
     are the chat's small history.


     Why beside the conversation and not inside it: output scrolls faster
     than anyone reads, and a chat that jumps with it cannot be read at all.
     The folded box in the message stays what it was — the record of what
     came out at the end. This is the run itself while it happens.

     Commands are coloured by the bash grammar, program output by its own
     ANSI codes (lib/ansi.js) — one look for everything that shows code. */
  import Hauszeichen from './Hauszeichen.svelte'
  import Leuchtpunkt from './Leuchtpunkt.svelte'
  import { slide } from 'svelte/transition'
  import { tick, untrack } from 'svelte'
  import { callSelection } from '../lib/callSelection.svelte.js'
  import { slideIfDrawn } from '../lib/slideIfDrawn.js'
  import { ansiZuHtml, withoutAnsi } from '../lib/ansi.js'
  import { hervorheben } from '../lib/einfaerben.js'
  import { werkzeugErgebnisHtml } from '../lib/toolResult.js'
  import { KOPIER_ZEICHEN } from '../lib/markdown.js'
  import { melde } from '../lib/zustand.svelte.js'
  import { rollfade } from '../lib/rollfade.js'
  import { folgtUnten, NAH } from '../lib/folgtunten.js'
  import { t } from '../lib/texte.svelte.js'
  import { dauerText, TERMINAL } from '../lib/dauer.js'
  import { laufampel } from '../lib/laufampel.js'
  import { laufWach } from '../lib/terminalfenster.svelte.js'
  import { punktAtmet } from '../lib/meldewesen.svelte.js'
  import { stopRun, terminal } from '../lib/terminalfenster.svelte.js'
  import { historie } from '../lib/werkzeughistorie.js'
  import { displayPath } from '../lib/paths.js'
  import Werkzeugzeichen from './Werkzeugzeichen.svelte'
  import { serverLogo } from '../lib/serverlogo.svelte.js'
  import { nachrichtenAnzeige } from '../lib/zustand.svelte.js'
  import { pictureFieldName } from '../lib/pictureFieldNames.js'

  /* Calls and runs in one list, in the order they happened. The messages
     carry the order; the runs are threaded in where they were started. */
  const eintraege = $derived(historie(nachrichtenAnzeige(), terminal.laeufe))

  let spur = $state(null)

  /* The call that was clicked in the answer (lib/callSelection.svelte.js):
     its line stands open and marked, in view, with the focus on it. The key
     is the one the list gives a call (`lib/werkzeughistorie.js`): a shell
     command with a run by the run's number, every other call by its
     message and its place there. */
  let selected = $state(null)
  $effect(() => {
    const counter = callSelection.counter
    const key = callSelection.key
    if (!key || !counter) return
    untrack(() => {
      // Read once: coming back to this tool later does not unfold it again.
      callSelection.key = null
      showCall(key)
    })
  })
  const keyOf = (eintrag) =>
    eintrag.art === 'aufruf' ? eintrag.schluessel : eintrag.art === 'lauf' ? `l${eintrag.lauf.lauf}` : null
  async function showCall(key) {
    /* A shell call is asked for as `l` and its run's number; with the run
       gone (the service was restarted) its line stands as a plain call and
       is found by the number it still carries. */
    const at = eintraege.findIndex(
      (eintrag) =>
        keyOf(eintrag) === key ||
        (eintrag.art === 'aufruf' && eintrag.lauf_nummer != null && `l${eintrag.lauf_nummer}` === key),
    )
    if (at === -1) {
      selected = null
      return
    }
    selected = keyOf(eintraege[at])
    if (eintraege[at].art === 'aufruf') {
      if (!offene.has(`a${at}`)) klappen(`a${at}`)
    } else {
      const lauf = eintraege[at].lauf
      if (!isBlockOpen(lauf)) toggleBlock(lauf)
    }
    // The list stays where the reader put it; the call is brought into view.
    terminal.klebt = false
    await tick()
    // A list that fits has no end to jump to: the button stays away.
    if (spur && spur.scrollHeight <= spur.clientHeight + 1) terminal.klebt = true
    const button = spur?.querySelector(`[data-key="${CSS.escape(selected)}"]`)
    button?.scrollIntoView({ block: 'nearest' })
    button?.focus({ preventScroll: true })
  }

  /* Which lines are unfolded — the same construction the chat's tool rows
     use (Nachricht.svelte, werkzeugKlappen): a Set, renewed on every
     change so Svelte notices. Keyed by the entry's list key, so a line
     stays open while entries are appended below it.

     Why the lines open at all: a refused download used to look like a
     crash here — the address cut at sixty characters, the error nowhere.
     The history now carries the full arguments and the result
     (lib/werkzeughistorie.js), and a click shows them. */
  let offene = $state(new Set())
  function klappen(schluessel) {
    const naechste = new Set(offene)
    naechste.has(schluessel) ? naechste.delete(schluessel) : naechste.add(schluessel)
    offene = naechste
  }

  /* A run's block — the command with its folder and its output — stands
     open while the run goes and folded once it is over, so a long history
     of finished commands is a list of lines and not a wall of boxes. A
     click on the command is the reader's own say, and it holds: a block
     opened by hand stays open when the run ends, one folded by hand stays
     folded while it still goes. Key → open or folded, only where somebody
     clicked; renewed on every change like `offene`. */
  let blockChoice = $state(new Map())
  function isBlockOpen(lauf) {
    const choice = blockChoice.get(`l${lauf.lauf}`)
    return choice !== undefined ? choice : lauf.zustand === 'laeuft'
  }
  function toggleBlock(lauf) {
    const next = new Map(blockChoice)
    next.set(`l${lauf.lauf}`, !isBlockOpen(lauf))
    blockChoice = next
  }

  /* Sticks to the end while nobody scrolls. The moment somebody scrolls up
     it lets go — reading beats watching — and a small button offers the way
     back down. */
  function gerollt() {
    if (!spur) return
    const unten = spur.scrollHeight - spur.scrollTop - spur.clientHeight
    terminal.klebt = unten < NAH
  }

  function ansEnde() {
    terminal.klebt = true
    if (spur) spur.scrollTop = spur.scrollHeight
  }

  /* Runs at every new line, because the text of the last run is what
     changes — the effect reads it, so it re-runs with it. */
  $effect(() => {
    const _ = terminal.laeufe.map((l) => l.ausgabe).join('').length + eintraege.length
    if (terminal.klebt && spur) spur.scrollTop = spur.scrollHeight
  })

  const punktfarbe = (lauf) => laufampel(lauf.zustand)

  async function stop(nummer) {
    try {
      await stopRun(nummer)
    } catch (error) {
      melde(error.message || t('fehler.allgemein'), 'fehler')
    }
  }

  /* The output as the program wrote it, without its colour codes — the
     same text the box shows, ready to paste. */
  async function copyOutput(lauf) {
    try {
      await navigator.clipboard.writeText(withoutAnsi(lauf.ausgabe))
      melde(t('nachricht.kopiert'), 'erfolg')
    } catch {
      melde(t('fehler.allgemein'), 'fehler')
    }
  }

  /* Same rule as the chat's own tool rows (Nachricht.svelte): a string
     argument stays plain, since no language is known for it — an object
     or number goes through as the JSON it actually is. */
  function wertHtml(wert) {
    return typeof wert === 'string'
      ? hervorheben(wert)
      : hervorheben(JSON.stringify(wert), 'json')
  }
</script>

<div class="spur" bind:this={spur} onscroll={gerollt} use:rollfade>
  {#if !eintraege.length}
    <p class="leer">{t('terminal.leer')}</p>
  {/if}
  {#each eintraege as eintrag, i (eintrag.art === 'lauf' ? `l${eintrag.lauf.lauf}` : `a${i}`)}
    {#if eintrag.art === 'trennung'}
      <div class="trennung"></div>
    {:else if eintrag.art === 'lauf'}
      <div class="lauf" class:selected={selected === `l${eintrag.lauf.lauf}`}>
        <div class="lkopf">
          <Leuchtpunkt
            farbe={punktfarbe(eintrag.lauf)}
            groesse={11}
            atmet={punktAtmet('terminal', punktfarbe(eintrag.lauf)) && laufWach(eintrag.lauf)}
          />
          {#if eintrag.lauf.art === 'bild'}
            <!-- A drawing job wears the sign the plus menu offers it under, so
                 the eye finds it in the list without reading. Its text is a
                 prompt and not a command, so it is not syntax-coloured. -->
            <span class="bildzeichen"><Hauszeichen zeichen="bild" groesse="klein" /></span>
            <button class="befehl klartext" class:umbruch={isBlockOpen(eintrag.lauf)}
                    data-key={`l${eintrag.lauf.lauf}`}
                    aria-expanded={isBlockOpen(eintrag.lauf)}
                    onclick={() => toggleBlock(eintrag.lauf)}>{eintrag.lauf.befehl}</button>
          {:else}
            <!-- The command line is cut off at the edge like any single
                 line. A click opens the whole block — the command wraps,
                 and its folder and output stand below — or folds it to
                 this one line again. -->
            <button class="befehl" class:umbruch={isBlockOpen(eintrag.lauf)}
                    data-key={`l${eintrag.lauf.lauf}`}
                    aria-expanded={isBlockOpen(eintrag.lauf)}
                    onclick={() => toggleBlock(eintrag.lauf)}>{@html hervorheben(eintrag.lauf.befehl, 'bash')}</button>
          {/if}
          {#if eintrag.lauf.hintergrund}
            <span class="marke">{t('terminal.hintergrund')}</span>
            <!-- WHICH run. Only a background run is ever referred to by
                 number ("run #3 finished"), so only that one shows one. -->
            <span class="lauf-nr">#{eintrag.lauf.lauf}</span>
          {/if}
          <!-- How long it took, once it is over. A picture has no exit code;
               the duration is the one number worth keeping about it. -->
          {#if eintrag.lauf.dauer_sekunden != null}
            <span class="dauer">{dauerText(t, eintrag.lauf.dauer_sekunden, TERMINAL)}</span>
          {/if}
          <!-- And what it exited with. Same rule the chat's tool card
               follows: zero is not drawn, because it is the absence of
               trouble rather than a badge, and a run whose code nobody
               knows says nothing instead of inventing one. -->
          {#if eintrag.lauf.code}
            <span class="exit-code">{t('werkzeug.exit', { code: eintrag.lauf.code })}</span>
          {/if}
          <!-- A command that is still running can be stopped here, with
               everything it started — in the foreground as in the
               background. A picture has its own way to be stopped. -->
          {#if eintrag.lauf.zustand === 'laeuft' && eintrag.lauf.art !== 'bild'}
            <button class="stop" disabled={eintrag.lauf.stopping}
                    onclick={() => stop(eintrag.lauf.lauf)}>{t('terminal.stop')}</button>
          {/if}
        </div>
        {#if isBlockOpen(eintrag.lauf) && eintrag.lauf.folder}
          <!-- Where it runs: a relative path in the command means nothing
               without it. Cut at the start, where a long path is least
               telling; the whole of it is the title. -->
          <div class="folder" title={displayPath(eintrag.lauf.folder)} transition:slideIfDrawn={{ duration: 200 }}>
            <span>{displayPath(eintrag.lauf.folder)}</span>
          </div>
        {/if}
        {#if isBlockOpen(eintrag.lauf) && eintrag.lauf.ausgabe}
          <!-- Capped, so a five-thousand-line build does not push the rest
               of the history out of the panel — and following its own tail,
               because a capped box nobody scrolls would simply hide
               everything past the first screen. The fade says there is more
               where the hidden scrollbar cannot. The copy sign takes the
               whole output, as the code blocks' sign does. -->
          <div class="output" transition:slideIfDrawn={{ duration: 200 }}>
            <pre class="ausgabe" use:rollfade use:folgtUnten>{@html ansiZuHtml(eintrag.lauf.ausgabe)}</pre>
            <button class="copy" title={t('nachricht.kopieren')} aria-label={t('nachricht.kopieren')}
                    onclick={() => copyOutput(eintrag.lauf)}>{@html KOPIER_ZEICHEN}</button>
          </div>
        {/if}
        {#if eintrag.lauf.art === 'bild' && isBlockOpen(eintrag.lauf) && eintrag.lauf.regler}
          <!-- The same shape a tool call's own arguments already use
               (.aufruf-text/.wz-argumente, below) — a drawing job is a call
               too, field by field, not a paragraph of prose. -->
          <!-- Every line shows in full: the card is as tall as its dials
               and the history around it scrolls, so no box of its own cuts
               the lower ones off. The names are the words the studio and
               the picture server carry for the same fields. -->
          <div class="aufruf-text picture-values" transition:slide={{ duration: 200 }}>
            <dl class="wz-argumente">
              {#each Object.entries(eintrag.lauf.regler) as [schluessel, wert] (schluessel)}
                <dt>{pictureFieldName(schluessel, t)}</dt>
                <dd>{@html wertHtml(wert)}</dd>
              {/each}
            </dl>
          </div>
        {/if}
      </div>
    {:else}
      <!-- The same tile the chat draws for a tool call (B4, Nachricht.svelte)
           — its mark, its name, what it was about, and a blue bar that says
           "work", red the moment it failed. A click unfolds the full
           arguments and the result, coloured the same way any code block
           in the program is. -->
      <div class="werkzeugblock" class:misslungen={eintrag.fehlgeschlagen}
           class:selected={selected === eintrag.schluessel}>
        <button class="aufruf" class:offen={offene.has(`a${i}`)} data-key={eintrag.schluessel}
                aria-expanded={offene.has(`a${i}`)} onclick={() => klappen(`a${i}`)}>
          <span class="zeichen"><Werkzeugzeichen name={eintrag.name} server={eintrag.server} logo={serverLogo(eintrag.server)} /></span>
          <span class="name werkzeugname" title={eintrag.name}>{eintrag.name}</span>
          {#if eintrag.kurz}<span class="kurz">{eintrag.kurz}</span>{/if}
          <!-- Duration and the outcome mark share the row's far end — one
               pushed group, not two competing auto margins (same pitfall
               already solved for the chat's own tool row, Nachricht.svelte
               .wz-rechts). -->
          <span class="aufruf-rechts">
            {#if eintrag.dauer_sekunden != null}
              <span class="dauer">{dauerText(t, eintrag.dauer_sekunden, TERMINAL)}</span>
            {/if}
            <span class="ausgang">{eintrag.fehlgeschlagen ? '✗' : '✓'}</span>
          </span>
        </button>
        {#if offene.has(`a${i}`)}
          <div class="aufruf-text" use:rollfade transition:slide={{ duration: 200 }}>
            {#if Object.keys(eintrag.argumente ?? {}).length}
              <dl class="wz-argumente">
                {#each Object.entries(eintrag.argumente) as [schluessel, wert] (schluessel)}
                  <dt>{schluessel}</dt>
                  <dd>{@html wertHtml(wert)}</dd>
                {/each}
              </dl>
            {/if}
            {#if eintrag.ergebnis}
              <pre class="wz-ergebnis"><code>{@html werkzeugErgebnisHtml(eintrag.ergebnis)}</code></pre>
            {:else}
              <p class="wz-leer">
                {eintrag.ergebnis === null ? t('werkzeug.laeuft_noch') : t('werkzeug.nichts_mitgeschrieben')}
              </p>
            {/if}
          </div>
        {/if}
      </div>
    {/if}
  {/each}
</div>

{#if !terminal.klebt}
  <button class="runter" onclick={ansEnde}>{t('terminal.ans_ende')}</button>
{/if}

<style>
  .spur {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 10px 12px 16px;
  }
  /* Flat: a call is one quiet line between the runs, not a card of its
     own — the runs are the cards. It opens on a click as before. */
  .werkzeugblock {
    margin-bottom: 2px;
    border-radius: 9px;
    overflow: hidden;
  }
  .aufruf {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 10px;
    font-size: 12.5px;
    color: var(--text-leise);
    min-width: 0;
    /* Button reset — the row must look exactly like the line it was. */
    width: 100%;
    background: none;
    border: none;
    font-family: inherit;
    text-align: left;
    cursor: pointer;
  }
  /* A quiet invitation, not a state — none of the four meaning-colours
     belong here, so the row just takes the hover glass. The parent tile's
     own radius and `overflow: hidden` clip it, so this needs no radius of
     its own. */
  .aufruf:hover {
    background: var(--glass-hover);
  }
  /* The unfolded line: full arguments field by field, then the result —
     the same colours every code block in the program uses
     (codefarben.css), same as the chat's own tool rows (Nachricht.svelte). */
  .aufruf-text {
    padding: 9px 10px;
    background: var(--code-grund);
    color: var(--code-vordergrund);
    border-top: 1px solid var(--linie);
    max-height: 40vh;
    overflow-y: auto;
    overflow-x: hidden;
    font-size: 12px;
  }
  /* A picture's dials are the whole of the card, not a part of a longer
     answer: no height cap, no scrolling box inside the scrolling list. */
  .aufruf-text.picture-values {
    max-height: none;
    overflow-y: visible;
  }
  .wz-argumente {
    margin: 0 0 8px;
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 1px 10px;
    font-size: 12px;
  }
  .wz-argumente dt {
    color: var(--code-typ);
    font-family: var(--schrift-fest);
    font-size: 11px;
    white-space: nowrap;
  }
  .wz-argumente dd {
    margin: 0;
    min-width: 0;
    overflow-wrap: anywhere;
    font-family: var(--schrift-fest);
  }
  /* The result is a tool's raw text, not prose — its own scrolling box so
     a wide table or long path never pushes the page itself sideways. */
  .wz-ergebnis {
    margin: 0;
    font-family: var(--schrift-fest);
    font-size: 11.8px;
    line-height: 1.55;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    overflow-x: auto;
    padding-top: 8px;
    border-top: 1px solid var(--linie);
  }
  .wz-argumente + .wz-ergebnis {
    margin-top: 0;
  }
  .wz-leer {
    margin: 0;
    color: var(--text-still);
  }
  /* A change block's own rows, inside the same <pre> — the block-level
     element is what lets the tinted ground reach the full width. */
  .wz-ergebnis :global(.diff-zeile) {
    display: block;
  }
  .wz-ergebnis :global(.diff-entfernt) {
    color: var(--rot-text);
    background: color-mix(in srgb, var(--rot) 12%, transparent);
  }
  .wz-ergebnis :global(.diff-hinzu) {
    color: var(--gruen-text);
    background: color-mix(in srgb, var(--gruen) 12%, transparent);
  }
  .wz-ergebnis :global(.diff-kopf) {
    color: var(--code-komm);
  }
  .wz-ergebnis :global(.diff-hinweis) {
    color: var(--code-komm);
    font-style: italic;
  }
  /* The call that was clicked in the answer stands marked: the glass
     under the pointer and its fine edge, no colour of its own. */
  .werkzeugblock.selected,
  .lauf.selected {
    background: var(--glass-hover);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
  }
  .aufruf .zeichen {
    flex: none;
    display: inline-flex;
    /* No opacity of its own: it dimmed the mark and made this the one place
       where a tool mark was a different shade than everywhere else. */
    /* Smaller than in the chat: here it identifies a line, there it heads
       a block. */
    --wz-groesse: 15px;
  }
  /* Only what is about THIS row: how a tool name is set lives in one place
     for the whole program (`.werkzeugname`, stil/global.css). */
  .aufruf .name {
    flex: 0 1 auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .aufruf .kurz {
    color: var(--text-still);
    padding-right: 12px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }
  .aufruf-rechts {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 8px;
    flex: none;
  }
  /* Overrides the bare .dauer rule's own margin-left: auto (below) — inside
     this group the push belongs to the group, not to one of its two
     members. */
  .aufruf-rechts .dauer {
    margin-left: 0;
  }
  .aufruf .ausgang {
    flex: none;
    color: var(--text-still);
  }
  /* The name carries pass or fail now that the frame no longer does
     (same rule as the chat's own .wz-name) — .ausgang just repeats it in
     the one spot that stays readable at a glance. */
  .werkzeugblock.misslungen .name {
    color: var(--rot-text);
  }
  .werkzeugblock.misslungen .ausgang {
    color: var(--rot-text);
  }
  .leer {
    margin: 6px 2px;
    font-size: 13px;
    color: var(--text-still);
  }
  /* Marks where one message's calls end and the next one's begin — a
     boundary the eye can follow without reading every line. */
  .trennung {
    border-top: 1px solid var(--linie);
    margin: 8px 2px;
  }
  /* A run is a glass card with its fine edge. */
  .lauf {
    border-radius: 9px;
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    padding: 9px 11px;
    margin-bottom: 8px;
  }
  /* The marks wrap below the command when the rail is narrow: the command
     is what the row is about, and squeezed beside four marks it was cut
     down to its first letter. */
  .lkopf {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px 8px;
  }
  .befehl {
    flex: 1 1 9em;
    min-width: 0;
    font-family: var(--schrift-fest);
    font-size: 12px;
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    /* Button reset — the header line must look exactly as before. */
    background: none;
    border: none;
    /* The cut line ends with "…" a little before the card's edge. */
    padding: 0 12px 0 0;
    text-align: left;
    cursor: pointer;
  }
  /* Same quiet lift as .aufruf above — a fact about the row (something
     here can be clicked), not a state. */
  .befehl:hover {
    background: var(--glass-hover);
  }
  /* Unfolded: the line may wrap, and the whole command can be read. A
     four-hundred-character download address is a command too. */
  .befehl.umbruch {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  /* The sign takes the quiet grey of the line it stands in — it marks the
     kind of run, it does not announce it. */
  .bildzeichen {
    flex: none;
    display: inline-flex;
    color: var(--text-still);
  }
  /* A prompt is prose. Syntax colours on it would claim a structure it
     does not have. */
  .befehl.klartext {
    color: var(--text-leise);
  }
  .dauer {
    flex: none;
    margin-left: auto;
    font-family: var(--schrift-fest);
    font-size: 10.5px;
    color: var(--text-still);
  }
  .marke {
    flex: none;
    font-size: 11px;
    color: var(--text-still);
  }
  /* Identifies, does not report — the duration's typeface, a step quieter
     still, exactly as `.wz-nummer` sits in the chat's tool card. */
  .lauf-nr {
    flex: none;
    font-family: var(--schrift-fest);
    font-size: 10.5px;
    color: var(--text-still);
    opacity: 0.8;
  }
  /* What broke outranks what it was, here as in the card. It follows the
     duration, which carries the row's one `margin-left: auto` — a second
     one would be two items fighting over the same edge. */
  .exit-code {
    flex: none;
    font-family: var(--schrift-fest);
    font-size: 10.5px;
    color: var(--rot-text);
  }
  /* The folder under the command: a fact, so brightness only. */
  .folder {
    margin-top: 5px;
    font-family: var(--schrift-fest);
    font-size: 11px;
    color: var(--text-still);
    overflow: hidden;
    white-space: nowrap;
    /* Cut at the start: the end of a path says where it is. */
    direction: rtl;
    text-align: left;
    text-overflow: ellipsis;
  }
  .folder span {
    direction: ltr;
    unicode-bidi: bidi-override;
  }
  .stop {
    flex: none;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    font: inherit;
    font-size: 11px;
    padding: 1px 8px;
    cursor: pointer;
  }
  .stop:hover { background: var(--glass-hover); }
  .stop:disabled { opacity: 0.5; cursor: default; }
  /* The output in a box of its own, a second layer of card glass on the
     run's card, with the copy sign in its corner — the code blocks' sign
     and place. */
  .output {
    position: relative;
    margin-top: 8px;
    border-radius: 9px;
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    padding: 8px 30px 8px 10px;
  }
  .copy {
    position: absolute;
    right: 5px;
    top: 5px;
    width: 22px;
    height: 22px;
    display: grid;
    place-items: center;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-still);
    cursor: pointer;
  }
  .copy:hover { background: var(--glass-hover); color: var(--text); }
  .copy :global(svg) { width: 13px; height: 13px; }
  /* Same lid as the tool call's own unfolded text just above (.aufruf-text)
     — a command's output can run to thousands of lines just as easily as a
     tool's result, and it deserves the same scrolling box instead of
     pushing the whole rail out of view. */
  .ausgabe {
    margin: 0;
    font-family: var(--schrift-fest);
    font-size: 12px;
    line-height: 1.45;
    color: var(--text-leise);
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 40vh;
    overflow-y: auto;
    overflow-x: hidden;
  }
  .runter {
    position: absolute;
    left: 50%;
    bottom: 58px;
    transform: translateX(-50%);
    /* It floats over the runs: dense glass with a blur and a fine edge,
       like every floating layer. */
    border: 1px solid var(--glass-button-edge);
    background: var(--glass-dropdown);
    -webkit-backdrop-filter: blur(16px);
    backdrop-filter: blur(16px);
    color: var(--text-leise);
    font: inherit;
    font-size: 12px;
    padding: 5px 12px;
    border-radius: 9px;
    cursor: pointer;
  }
  .runter:hover { color: var(--text); }
</style>
