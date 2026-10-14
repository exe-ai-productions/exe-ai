<script>
  /* The history of one running agent, in the shape of the chat's line.

     In view stand the agent's sentences and, for each stretch between two of
     them, one row that names the tools it used — "2 tools", while one runs
     "1 tool · write_file" and "running" in blue. Thinking, the call that is
     still being written, the context reading and the raw data of a call
     stand behind a click on that row; a call's raw data opens once more
     behind its own line (lib/agentenverlauf.js says what the run writes).

     A line with a dot on it, as in the chat: the sentence wears the empty
     ring, a row of tools the dot of its worst state. */
  import { slide } from 'svelte/transition'
  import { slideIfDrawn } from '../lib/slideIfDrawn.js'
  import Leuchtpunkt from './Leuchtpunkt.svelte'
  import { rohText, verlaufBauen } from '../lib/agentenverlauf.js'
  import { t } from '../lib/texte.svelte.js'

  let { schritte = [], laeuft = false } = $props()

  const eintraege = $derived(verlaufBauen(schritte, laeuft))

  /* Which rows are open, by the number of their first step, and which calls
     show their raw data, by the number of their step. */
  let offeneRunden = $state(new Set())
  let offeneRohdaten = $state(new Set())

  function umschalten(menge, schluessel) {
    const neu = new Set(menge)
    if (neu.has(schluessel)) neu.delete(schluessel)
    else neu.add(schluessel)
    return neu
  }

  function rundenText(runde) {
    if (runde.anzahl >= 2) return t('werkzeug.buendel', { zahl: runde.anzahl })
    if (runde.anzahl === 1) return t('jobs.runde_werkzeug_eins')
    return t('jobs.runde_schritte', { zahl: runde.schritte.length })
  }

  const hatRohdaten = (schritt) => schritt.typ === 'tool_call' || schritt.typ === 'tool_result'
</script>

<div class="verlauf">
  {#each eintraege as e (e.art + e.schluessel)}
    {#if e.art === 'satz'}
      <div class="vzeile">
        <span class="vpunkt" aria-hidden="true"><span class="ring"></span></span>
        <p class="satz">{e.text}</p>
      </div>
    {:else}
      <div class="vzeile">
        <span class="vpunkt" aria-hidden="true">
          <Leuchtpunkt farbe={e.zustand} groesse={9} atmet={false} />
        </span>
        <button
          class="runde"
          class:offen={offeneRunden.has(e.schluessel)}
          aria-expanded={offeneRunden.has(e.schluessel)}
          onclick={() => (offeneRunden = umschalten(offeneRunden, e.schluessel))}
        >
          <span class="rname">{rundenText(e)}</span>
          <svg class="pfeil" width="10" height="10" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="2.5" aria-hidden="true">
            <path d="M9 6l6 6-6 6" />
          </svg>
          {#if e.laufend}
            <span class="vorschau werkzeugname">{e.laufend}</span>
            <span class="rechts">{t('werkzeug.buendel_laeuft')}</span>
          {/if}
        </button>
        {#if offeneRunden.has(e.schluessel)}
          <div class="schritte" transition:slide={{ duration: 200 }}>
            {#each e.schritte as schritt (schritt.nummer)}
              {#if hatRohdaten(schritt)}
                <button
                  class="schritt roh-knopf"
                  aria-expanded={offeneRohdaten.has(schritt.nummer)}
                  title={schritt.inhalt}
                  onclick={() => (offeneRohdaten = umschalten(offeneRohdaten, schritt.nummer))}
                >
                  <span class="snr">{schritt.nummer}</span>
                  <span class="styp">{schritt.typ}</span>
                  <span class="sinhalt">{schritt.inhalt}</span>
                </button>
                {#if offeneRohdaten.has(schritt.nummer)}
                  <pre class="roh" transition:slideIfDrawn={{ duration: 200 }}>{rohText(schritt.inhalt)}</pre>
                {/if}
              {:else}
                <div class="schritt" title={schritt.inhalt}>
                  <span class="snr">{schritt.nummer}</span>
                  <span class="styp">{schritt.typ}</span>
                  <span class="sinhalt">{schritt.inhalt}</span>
                </div>
              {/if}
            {/each}
          </div>
        {/if}
      </div>
    {/if}
  {/each}
</div>

<style>
  /* The chat's line: a hairline down the left, a dot on it for every entry.
     It is drawn row by row — each row's piece reaches up through the gap to
     the row before — so the piece of a sentence can leave a gap for its
     hollow ring. The transcript lies on glass, and a ring with a ground of
     its own to cover the line would stand on it as a small plate. */
  .verlauf {
    position: relative;
    margin: 10px 0 2px;
    padding-left: 20px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .vzeile {
    position: relative;
    min-width: 0;
    --line-top: -8px;
    --line-bottom: 0px;
  }
  /* The line begins inside the first dot and ends eight pixels above the
     list's lower edge, as the one line did. */
  .vzeile:first-child { --line-top: 8px; }
  .vzeile:last-child { --line-bottom: 8px; }
  .vzeile::before {
    content: '';
    position: absolute;
    left: -15px;
    top: var(--line-top);
    bottom: var(--line-bottom);
    width: 1px;
    background: var(--linie-stark);
  }
  /* The ring stands from 6 to 15 pixels down its row (`.vpunkt`, `.ring`). */
  .vzeile:has(> .vpunkt > .ring)::before {
    background: linear-gradient(
      to bottom,
      var(--linie-stark) calc(6px - var(--line-top)),
      transparent calc(6px - var(--line-top)),
      transparent calc(15px - var(--line-top)),
      var(--linie-stark) calc(15px - var(--line-top))
    );
  }
  .vpunkt {
    position: absolute;
    left: -20px;
    top: 5px;
    width: 11px;
    height: 11px;
    display: grid;
    place-items: center;
  }
  .ring {
    width: 9px;
    height: 9px;
    box-sizing: border-box;
    border-radius: 50%;
    border: 1.5px solid var(--text-still);
  }
  /* The agent's own sentences: bright, in the reading size. */
  .satz {
    margin: 0;
    font-size: 14.5px;
    line-height: 22px;
    color: var(--text);
    overflow-wrap: anywhere;
  }
  .runde {
    display: flex;
    align-items: center;
    gap: 7px;
    width: 100%;
    min-width: 0;
    padding: 0;
    border: none;
    background: none;
    font-family: var(--schrift-fest);
    font-size: 12px;
    line-height: 19px;
    color: var(--text-still);
    text-align: left;
    cursor: pointer;
  }
  .runde:hover .rname { color: var(--text-leise); }
  .rname { flex: none; }
  .pfeil {
    flex: none;
    transition: transform 0.15s;
  }
  .runde.offen .pfeil { transform: rotate(90deg); }
  .vorschau {
    flex: 1;
    min-width: 0;
    padding-right: 12px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .rechts {
    margin-left: auto;
    flex: none;
    font-family: var(--schrift);
    color: var(--blau);
  }
  /* Behind the click: the lines the run wrote, as they always stood. */
  .schritte {
    margin: 6px 0 2px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .schritt {
    display: flex;
    align-items: baseline;
    gap: 6px;
    font-size: 11.5px;
    color: var(--text-still);
    min-width: 0;
    text-align: left;
  }
  button.schritt {
    width: 100%;
    padding: 0;
    border: none;
    background: none;
    font: inherit;
    font-size: 11.5px;
    cursor: pointer;
  }
  button.schritt:hover { color: var(--text-leise); }
  .snr { flex: none; min-width: 16px; text-align: right; }
  .styp { flex: none; color: var(--text-leise); }
  .sinhalt {
    flex: 1;
    min-width: 0;
    padding-right: 12px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  /* A call's raw data, in the fixed face on a glass card of its own. */
  .roh {
    margin: 4px 0 6px 22px;
    padding: 8px 10px;
    border-radius: 9px;
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    font-family: var(--schrift-fest);
    font-size: 11.5px;
    line-height: 1.5;
    color: var(--text-leise);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    max-height: 240px;
    overflow-y: auto;
  }
</style>
