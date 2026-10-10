<script module>
  /* Browser first, then the agents and the schedules, each a tool of its
     own, the terminal, the pictures and — right beside them, because they
     are both walls of files — the doc folder. */
  export const ORDER = ['vorschau', 'agenten', 'cronjobs', 'terminal', 'bilder', 'docfolder']
</script>

<script>
  /* The signs of the tools on the right — the row at the foot of the open
     column, and the bar of signs of the folded one (Arbeitsleiste.svelte).
     A click shows that tool; a folded column opens on it. The signs that
     report carry their state in their colour, so a command running behind
     a folded column is visible without opening anything.

     `names` says which signs stand here, in order; `gapBefore` is the
     index a free space stands before, so the folded bar can split its signs between
     top and foot the way the bar on the left does. */
  import Agentenmarke from './Agentenmarke.svelte'
  import Modulzeichen from './Modulzeichen.svelte'
  import { leiste, modulWaehlen } from '../lib/arbeitsleiste.svelte.js'
  import { studio, studioSichtbar } from '../lib/studio.svelte.js'
  import { t } from '../lib/texte.svelte.js'
  import { laufampel } from '../lib/laufampel.js'
  import { laufWach, terminal, terminalGesehen } from '../lib/terminalfenster.svelte.js'
  import { historie } from '../lib/werkzeughistorie.js'
  import { punktAtmet } from '../lib/meldewesen.svelte.js'
  import { punktfarbe as agentenPunktfarbe } from '../lib/agentenampel.svelte.js'
  import { punktfarbe as cronjobPunktfarbe } from '../lib/cronjobampel.svelte.js'
  import { nachrichtenAnzeige } from '../lib/zustand.svelte.js'

  let { names = ORDER, gapBefore = -1 } = $props()

  /* One size for every stroke sign in this row. Numbers rather than feel:
     the row reads as a row only while the signs are the same. */
  const ZEICHEN_GROESSE = 24

  const LABELS = {
    vorschau: 'vorschau.titel',
    agenten: 'agenten.titel',
    cronjobs: 'cronjobs.titel',
    terminal: 'terminal.titel',
    bilder: 'bilder.titel',
    docfolder: 'docfolder.title',
  }

  /* What the two job signs have to say, each in one dot — the decision
     itself lives beside the facts it reads, not here. `still` is a colour
     like the others: a grey disc, so both signs carry a dot in every state
     instead of one of them vanishing while the other stays put. */
  const agentenfarbe = $derived(agentenPunktfarbe())
  const cronfarbe = $derived(cronjobPunktfarbe())

  /* The two lists behind the signs used to be fetched here on a timer,
     every fifteen seconds, whether anything had happened or not — which is
     also how long an agent could be finished before its sign said so. The
     service says it now (lib/ereignisstrom.svelte.js), and the same module
     does the one fetch that follows. Nothing is asked from here anymore. */

  /* Seen, while you are looking at it — here only the terminal's runs. The
     schedules are cleared where their runs stand in view
     (ModulCronjobs.svelte), and the agents' runs answer for themselves
     (agentenampel.svelte.js): each has a report to open, so opening the
     view says nothing about whether any of them was read. */
  $effect(() => {
    if (!leiste.offen) return
    if (leiste.modul === 'terminal' && terminal.laeufe) terminalGesehen()
  })

  /* The sign wears the last RUN's state — and turns red when the last
     thing the panel lists is a tool call that FAILED without becoming a
     run: a shell call refused before it started (no shared folder), or
     any other tool's call that came back failed — every call the panel
     lists as a line, the same lines the reader sees when they open it.
     Read from the runs first, not from the panel's pairing: the pairing
     is drawing, and a sign that hung on it went dark the moment a row
     paired oddly. Blue outranks red: a command still running is the one
     state that changes what the reader does next, and a refusal after it
     started must not hide that. */
  const eintraege = $derived(
    historie(nachrichtenAnzeige(), terminal.laeufe).filter((e) => e.art !== 'trennung'),
  )
  const letzterEintrag = $derived(eintraege[eintraege.length - 1] ?? null)
  const letzterLauf = $derived(terminal.laeufe[terminal.laeufe.length - 1] ?? null)
  const laufGeht = $derived(terminal.laeufe.some((l) => l.zustand === 'laeuft'))
  const abgelehnterAufruf = $derived(
    letzterEintrag?.art === 'aufruf' && Boolean(letzterEintrag.fehlgeschlagen),
  )
  const laufzustand = $derived(
    laufGeht
      ? 'blau'
      : abgelehnterAufruf
        ? 'rot'
        : letzterLauf
          ? laufampel(letzterLauf.zustand)
          : null,
  )

  /* Which state a sign carries. Four signs report; every other one is a
     plain button. `still` and `leer` are the two the ampeln use for "nothing
     to say" and become no colour at all here: on a dot they were a grey
     disc, but the sign IS the drawing, and a grey drawing is what a sign
     that says nothing already looks like. */
  function zustandVon(name) {
    /* Blue while a run goes, and red for as long as the last thing that
       ran or was asked for FAILED — a failure is a state, not news, and it
       stands until the next call. Green is news: it stands only until
       somebody has looked, then steps back — a sign green for the whole
       session said nothing. */
    if (name === 'terminal') {
      if (laufzustand === 'blau' || laufzustand === 'rot') return laufzustand
      return laufWachsam ? laufzustand : null
    }
    if (name === 'agenten' || name === 'cronjobs') return eigeneFarbe(name)
    return null
  }

  /* The agents and the schedules each wear their own colour: red before
     yellow before blue before green is the order the two ampeln already
     speak in; the sign shows exactly what its ampel says. */
  const DRINGLICHKEIT = ['rot', 'gelb', 'blau', 'gruen']
  function eigeneFarbe(name) {
    const farbe = name === 'agenten' ? agentenfarbe : cronfarbe
    return DRINGLICHKEIT.includes(farbe) ? farbe : null
  }

  /* Whether it may move. Each sign asks its own switch BY NAME rather than
     through a lookup table: the switch a mark hangs on has to be findable by
     searching for the mark, or nobody can prove a mark can be quieted. */
  function atmetVon(name) {
    if (name === 'terminal') return laufWachsam && punktAtmet('terminal', laufzustand)
    if (name === 'agenten') {
      const farbe = eigeneFarbe('agenten')
      return Boolean(farbe) && punktAtmet('agenten', farbe)
    }
    if (name === 'cronjobs') {
      const farbe = eigeneFarbe('cronjobs')
      return Boolean(farbe) && punktAtmet('cronjob', farbe)
    }
    return false
  }
  /* The terminal is the one dot whose colour says nothing about whether
     anybody has looked — a finished run stays green for the rest of the
     session. So the mark is asked separately here. */
  const laufWachsam = $derived(
    abgelehnterAufruf
      ? letzterEintrag.schluessel !== terminal.gesehenerAufruf
      : laufWach(letzterLauf),
  )

  /* Whether a tool is what the column shows. In the picture studio the
     column shows the studio's details until a tool is picked there, and the
     tool behind them is not on show. */
  const detailsShown = $derived(studioSichtbar() && studio.rechts === 'feinheiten')
  const shown = (name) => leiste.offen && leiste.modul === name && !detailsShown
</script>

{#snippet modulKnopf(name)}
  <!-- A sign is on while its tool is what the column shows. -->
  <!-- The state is the SIGN's colour, not a dot in its corner. The dot was
       6 px on a 38 px button — under three percent of it — and it went
       unread in front of an audience. The whole mark carries it now: same
       four colours, same meanings. -->
  <button
    class="zeichen"
    class:aktiv={shown(name)}
    class:atmet={atmetVon(name)}
    data-zustand={zustandVon(name) || null}
    onclick={() => modulWaehlen(name)}
    title={t(LABELS[name])}
    aria-label={t(LABELS[name])}
    aria-pressed={shown(name)}
  >
    {#if name === 'agenten'}
      <!-- The agent mark the job cards already wear — the same figure says
           "agent" wherever agents appear. -->
      <Agentenmarke groesse={ZEICHEN_GROESSE} />
    {:else}
      <Modulzeichen modul={name} groesse={ZEICHEN_GROESSE} />
    {/if}
    <!-- Two rings out of the button, the breath the microphone wears. They
         end on the button's own edge: a ring grown past it would crowd the
         neighbouring sign. -->
    <span class="atem" aria-hidden="true"></span>
    <span class="atem zwei" aria-hidden="true"></span>
  </button>
{/snippet}

{#each names as name, i (name)}
  {#if i === gapBefore}
    <span class="frei"></span>
  {/if}
  {@render modulKnopf(name)}
{/each}

<style>
  .frei { flex: 1; }
  /* One square for every sign, the house's sign button — the same one the
     sidebar's bar and row wear on the left. */
  .zeichen {
    position: relative;
    width: 40px;
    height: 40px;
    flex: none;
    display: grid;
    place-items: center;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--rahmen-text, var(--text-still));
    padding: 0;
    cursor: pointer;
    transition: background 0.12s, color 0.12s;
  }
  .zeichen:hover { background: var(--glass-hover); color: var(--text-leise); }
  /* Glass with a fine edge, inset so the sign keeps its 40 px. */
  .zeichen.aktiv {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
  }
  /* The four states, on the sign itself. Colour means state, as everywhere
     else in the house — and the sign is the biggest surface the row has to
     say it with. The active sign's own brightness gives way to it: a state
     outranks "this is the tool you are looking at". */
  .zeichen[data-zustand='gruen'] { color: var(--gruen); }
  .zeichen[data-zustand='blau'] { color: var(--blau); }
  .zeichen[data-zustand='gelb'] { color: var(--gelb); }
  .zeichen[data-zustand='rot'] { color: var(--rot); }

  /* The breath, and only for the three that want a hand. Blue is left out
     on purpose — see RUHIG in lib/meldewesen.svelte.js: a run can go for an
     hour, and an hour of pulsing in the corner of the eye teaches the eye
     to ignore it, which is the opposite of the point. */
  .atem {
    position: absolute;
    inset: 0;
    border-radius: 9px;
    border: 1.5px solid currentColor;
    opacity: 0;
    pointer-events: none;
  }
  .zeichen.atmet .atem {
    animation: atmen 2.4s cubic-bezier(0.25, 0.6, 0.3, 1) infinite;
  }
  .zeichen.atmet .atem.zwei { animation-delay: 1.2s; }
  @keyframes atmen {
    0% { transform: scale(0.55); opacity: 0; }
    20% { opacity: 0.55; }
    100% { transform: scale(1); opacity: 0; }
  }
  /* Asked for calm, the colour stays and only the ring goes — the state is
     still readable, which is what the mark is for. */
  @media (prefers-reduced-motion: reduce) {
    .zeichen.atmet .atem { animation: none; }
  }
</style>
