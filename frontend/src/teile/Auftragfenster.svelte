<script>
  /* The frame both job windows stand in — "Neue Aufgabe" and the start_job
     confirmation.

     They ask the same thing in two situations: a task, in a field, with a
     button that sends it off. So they are one box: `art="lesen"`, 500 by
     650, the field growing into whatever height is left and the foot
     standing on the bottom edge. Written twice, the two drifted — one grew
     with its text and shoved its own button out from under the pointer
     while the other held still.

     What one of them has and the other does not comes in as snippets: the
     agent and model rows, the folder line, the permission mode. Everything
     the two share — the size, the field, the tool marks, the foot and its
     two buttons — is here and nowhere else.

     The tool marks say what the chosen agent may DO before a task is handed
     to it. One mark per KIND of tool (web, files, terminal …) with how many
     tools it covers, not one per tool. Only to look at: not a switch, no
     state. An agent with no tools shows no row at all rather than an empty
     one. */
  import Fenster from './Fenster.svelte'
  import WachsendesFeld from './WachsendesFeld.svelte'
  import Agentenmarke from './Agentenmarke.svelte'
  import Werkzeugzeichen from './Werkzeugzeichen.svelte'
  import { werkzeugarten } from '../lib/werkzeugarten.js'
  import { api } from '../lib/api.js'
  import { t } from '../lib/texte.svelte.js'

  let {
    offen = $bindable(false),
    titel = '',
    /* The agent's name, shown as a line of its own where the window has no
       picker for it. Empty where a picker comes in through `kopf`. */
    agent = '',
    /* Which tools the chosen agent may use: a list of names, or `null` for
       "every approved tool" — the same two answers the agent file gives
       (Agentenmaske.svelte). An empty list means none, and `[]` is also what
       to pass while no agent has been chosen yet. */
    werkzeugnamen = null,
    /* A sentence under the agent's name, where the window has one to say.
       "Agent losschicken" does — its field arrives already filled and the
       sentence says the text may be straightened. "Neue Aufgabe" starts
       empty and says nothing, because there is nothing to adjust yet. */
    hinweis = '',
    text = $bindable(''),
    platzhalter = '',
    feldbeschriftung = '',
    startbar = true,
    /* Nothing to start at all: no reachable model, or no agent on the
       machine. Then the window holds the reason and a way out, and leaves
       out the field and the start button — a field nobody can send and a
       button that cannot work would both be lying about the situation. */
    nurHinweis = false,
    aufStarten,
    aufAbbrechen,
    kopf,
    unterFeld,
    fussLinks,
  } = $props()

  /* The approved tools with the server each came from — the server is what
     makes a mark reliable, so the row asks for the whole list instead of
     guessing a mark from a name (lib/werkzeugkatalog.js). Loaded while the
     window is open and not before: closed, it shows nothing anyway. */
  let alle = $state([])
  $effect(() => {
    if (!offen) return
    api.werkzeuge()
      .then((antwort) => (alle = antwort.werkzeuge ?? []))
      .catch(() => (alle = []))
  })

  /* The server widens a non-empty tool list with the shelf on every run
     (app/tools/agentendock.py, WERKZEUG_NAME) — an agent that named its own
     tools without it would otherwise deliver into a folder nobody opens.
     `null` ("every approved tool") already includes it; `[]` is a
     deliberate "none" the server leaves untouched, so this must too. */
  const ABLAGE_WERKZEUG = 'deliver_file'
  const tatsaechlicheWerkzeugnamen = $derived(
    werkzeugnamen && werkzeugnamen.length && !werkzeugnamen.includes(ABLAGE_WERKZEUG)
      ? [...werkzeugnamen, ABLAGE_WERKZEUG]
      : werkzeugnamen,
  )

  const werkzeuge = $derived(
    tatsaechlicheWerkzeugnamen == null
      ? alle
      : alle.filter((werkzeug) => tatsaechlicheWerkzeugnamen.includes(werkzeug.name)),
  )
  const arten = $derived(werkzeugarten(werkzeuge))
</script>

{#snippet marke()}
  <Agentenmarke groesse={17} />
{/snippet}

{#snippet kopfblock()}
  {@render kopf?.()}
  {#if agent}
    <div class="agentzeile">
      <span class="wer">{agent}</span>
    </div>
  {/if}
  {#if hinweis}
    <p class="hinweis">{hinweis}</p>
  {/if}
  {#if arten.length}
    <!-- What the agent may do, one mark per kind of tool: the drawing in the
         tool colour, the kind's name in grey, and the count only from two
         on. The row has a place of its own above the field and wraps: an
         agent that may use every tool has more kinds than one line holds.
         The pointer and a screen reader get the names of the tools behind
         the kind — they are the tools', not texts invented here. -->
    <div class="werkzeugblock">
      <span class="tafelkopf">{t('werkzeuge.titel')}</span>
      <div class="werkzeugreihe">
        {#each arten as eintrag (eintrag.art)}
          <span class="artmarke" role="img" title={eintrag.namen.join(', ')}
                aria-label="{t(`werkzeug.art_${eintrag.art}`)}: {eintrag.namen.join(', ')}">
            <span class="wzzeichen" class:weitere={eintrag.art === 'weitere'}>
              <Werkzeugzeichen name={eintrag.zeichen.name} server={eintrag.zeichen.server} />
            </span>
            <span class="artname">{t(`werkzeug.art_${eintrag.art}`)}</span>
            {#if eintrag.anzahl >= 2}
              <span class="artzahl">{eintrag.anzahl}</span>
            {/if}
          </span>
        {/each}
      </div>
    </div>
  {/if}
{/snippet}

<!-- `lesen` rather than `frage`: one box, 500 by 650, the same one a report
     is read in. A task can be a line or a paragraph, and a window that
     changed height with it moved its own button around under the pointer.
     Both numbers stand in Fenster.svelte; neither is repeated here. -->
<Fenster bind:offen {titel} art="lesen" symbol={marke}>
  {#if nurHinweis}
    <!-- A dead end is not a field nobody can send: the window keeps its
         usual size, and the reason stands where a body would — centred in
         the space between the head and the foot, not stranded at the top of
         an otherwise empty box. -->
    <div class="hinweismitte">
      {@render kopfblock()}
    </div>
  {:else}
    {@render kopfblock()}
    <!-- `volleHoehe`, because the window now HOLDS a height: the field takes
         whatever is left of it and the foot stands on the bottom edge. The
         field's own growing would leave a box of one line under a 650 px
         window and move the buttons on every keystroke. The mechanism is
         the one the prompt window already uses — none is invented here. -->
    <WachsendesFeld
      bind:wert={text}
      {platzhalter}
      beschriftung={feldbeschriftung}
      volleHoehe
    />
    {@render unterFeld?.()}
  {/if}
  <div class="fuss">
    <div class="fusslinks">{@render fussLinks?.()}</div>
    <div class="fussrechts">
      <button class="button" onclick={aufAbbrechen}>{t('app.abbrechen')}</button>
      {#if !nurHinweis}
        <!-- Its own word, not the one the window title carries: the title
             names the THING being made, this names the act of sending it. -->
        <button class="button primary" onclick={aufStarten} disabled={!startbar}>
          {t('jobs.los')}
        </button>
      {/if}
    </div>
  </div>
</Fenster>

<style>
  .agentzeile {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 4px;
  }
  .wer {
    font: 600 13px var(--schrift);
    color: var(--text);
  }
  .hinweis {
    margin: 0 0 8px;
    font-size: 12px;
    line-height: 1.45;
    color: var(--text-still);
  }
  /* The row of marks has its own room: it never shrinks, so the field below
     is pushed down instead of running over it. */
  .werkzeugblock {
    flex: none;
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 10px 0 8px;
  }
  .werkzeugreihe {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .artmarke {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 9px;
    border-radius: 9px;
    background: var(--bg-hoch);
    font-size: 12px;
  }
  .artname { color: var(--text-leise); }
  .artzahl {
    color: var(--text-still);
    font-variant-numeric: tabular-nums;
  }
  /* A mark draws itself at the size of its box, so the size is said here
     once instead of inside every icon (Werkzeugzeichen.svelte); the chevron
     of the unknown kind is smaller than its box and is centred in it. The
     tool colour belongs to a tool; the kind for everything unknown stays
     grey. */
  .wzzeichen {
    display: grid;
    place-items: center;
    --wz-groesse: 17px;
    width: 17px;
    height: 17px;
    color: var(--werkzeug);
  }
  .wzzeichen.weitere { color: var(--text-still); }
  /* The dead-end case: no field, no tool row below it — so this is the
     whole body, and it takes the whole space between the head and the
     foot rather than sitting wherever its content happens to start. */
  .hinweismitte {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    gap: 8px;
  }
  /* The window holds a height, so its body has a foot to stand on: the field
     grows into whatever is left and the buttons sit at the bottom edge
     instead of following the text up and down. */
  .fuss {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
    margin-top: auto;
    padding-top: 12px;
  }
  .fusslinks {
    display: flex;
    align-items: center;
  }
  .fussrechts {
    display: flex;
    gap: 8px;
  }
  /* Cancel and Go are the house button (`.button`, stil/global.css): Go is
     its main form, glass like every main button but Send. */
</style>
