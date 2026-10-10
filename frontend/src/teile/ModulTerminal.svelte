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
  import { ansiZuHtml, withoutAnsi } from '../lib/ansi.js'
  import { hervorheben } from '../lib/einfaerben.js'
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
  import Werkzeugzeichen from './Werkzeugzeichen.svelte'
  import { nachrichtenAnzeige } from '../lib/zustand.svelte.js'

  /* Calls and runs in one list, in the order they happened. The messages
     carry the order; the runs are threaded in where they were started. */
  const eintraege = $derived(historie(nachrichtenAnzeige(), terminal.laeufe))

  let spur = $state(null)

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
      <div class="lauf">
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
            <button class="befehl klartext" class:umbruch={offene.has(`l${eintrag.lauf.lauf}`)}
                    onclick={() => klappen(`l${eintrag.lauf.lauf}`)}>{eintrag.lauf.befehl}</button>
          {:else}
            <!-- The command line is cut off at the edge like any single
                 line — a click lets it wrap, so the whole command can be
                 read. That is all the click does: the output already
                 stands below. -->
            <button class="befehl" class:umbruch={offene.has(`l${eintrag.lauf.lauf}`)}
                    onclick={() => klappen(`l${eintrag.lauf.lauf}`)}>{@html hervorheben(eintrag.lauf.befehl, 'bash')}</button>
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
        {#if eintrag.lauf.folder}
          <!-- Where it runs: a relative path in the command means nothing
               without it. Cut at the start, where a long path is least
               telling; the whole of it is the title. -->
          <div class="folder" title={eintrag.lauf.folder}><span>{eintrag.lauf.folder}</span></div>
        {/if}
        {#if eintrag.lauf.ausgabe}
          <!-- Capped, so a five-thousand-line build does not push the rest
               of the history out of the panel — and following its own tail,
               because a capped box nobody scrolls would simply hide
               everything past the first screen. The fade says there is more
               where the hidden scrollbar cannot. The copy sign takes the
               whole output, as the code blocks' sign does. -->
          <div class="output">
            <pre class="ausgabe" use:rollfade use:folgtUnten>{@html ansiZuHtml(eintrag.lauf.ausgabe)}</pre>
            <button class="copy" title={t('nachricht.kopieren')} aria-label={t('nachricht.kopieren')}
                    onclick={() => copyOutput(eintrag.lauf)}>{@html KOPIER_ZEICHEN}</button>
          </div>
        {/if}
        {#if eintrag.lauf.art === 'bild' && offene.has(`l${eintrag.lauf.lauf}`) && eintrag.lauf.regler}
          <!-- The same shape a tool call's own arguments already use
               (.aufruf-text/.wz-argumente, below) — a drawing job is a call
               too, field by field, not a paragraph of prose. -->
          <div class="aufruf-text" use:rollfade transition:slide={{ duration: 200 }}>
            <dl class="wz-argumente">
              {#each Object.entries(eintrag.lauf.regler) as [schluessel, wert] (schluessel)}
                <dt>{schluessel}</dt>
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
      <div class="werkzeugblock" class:misslungen={eintrag.fehlgeschlagen}>
        <button class="aufruf" class:offen={offene.has(`a${i}`)} onclick={() => klappen(`a${i}`)}>
          <span class="zeichen"><Werkzeugzeichen name={eintrag.name} server={eintrag.server} /></span>
          <span class="name werkzeugname">{eintrag.name}</span>
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
              <pre class="wz-ergebnis"><code>{@html hervorheben(eintrag.ergebnis)}</code></pre>
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
  .aufruf .zeichen {
    flex: none;
    display: inline-flex;
    /* No opacity of its own any more: it dimmed the tool colour to 80 %
       and made this the one place where a tool mark was a different
       shade than everywhere else. */
    /* Smaller than in the chat: here it identifies a line, there it heads
       a block. */
    --wz-groesse: 15px;
  }
  /* The call's own colour, not a hover highlight — it used to brighten from
     --text-still to --text on hover/open, but a colour that means "this is
     a call" must not fade the moment someone points at or opens the very
     row it names. The tool colour rather than blue since the house has a
     colour for a tool: blue is a STATE (a run is going), and one colour
     cannot carry both meanings in a window that shows the two side by
     side. */
  /* Only what is about THIS row: how a tool name is set lives in one place
     for the whole program (`.werkzeugname`, stil/global.css). */
  .aufruf .name {
    flex: none;
  }
  .aufruf .kurz {
    color: var(--text-still);
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
    color: var(--rot);
  }
  .werkzeugblock.misslungen .ausgang {
    color: var(--rot);
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
    padding: 0;
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
    color: var(--rot);
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
