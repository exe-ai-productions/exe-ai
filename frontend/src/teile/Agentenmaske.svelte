<script>
  /* The agent mask — every field an agent file carries, as real controls,
     so nothing has to be edited in raw markdown. Its one home is Settings ›
     Agents (SystemPrompt.svelte), for a new agent and for an existing one.
     It draws the fields, saves, and says when it is done. */
  import { api } from '../lib/api.js'
  import { t } from '../lib/texte.svelte.js'
  import { fade } from 'svelte/transition'
  import { untrack } from 'svelte'
  import { serverLogo } from '../lib/serverlogo.svelte.js'
  import { artFuer } from '../lib/werkzeugarten.js'
  import Hauszeichen from './Hauszeichen.svelte'
  import Schalter from './Schalter.svelte'
  import Werkzeugzeichen from './Werkzeugzeichen.svelte'
  import Startordnerpillen from './Startordnerpillen.svelte'
  import Agentenfarbwahl from './Agentenfarbwahl.svelte'
  import Auswahlfeld from './Auswahlfeld.svelte'
  import Zahlenfeld from './Zahlenfeld.svelte'
  import { melde, zustand } from '../lib/zustand.svelte.js'
  import { meldeText } from '../lib/meldewesen.svelte.js'
  import { rollfade } from '../lib/rollfade.js'

  let { agent = null, onfertig, onabbrechen, onunlesbar, geaendert = $bindable(false) } = $props()

  let neuName = $state('')
  let neuPrompt = $state('')
  let alleWerkzeuge = $state(true)
  let gewaehlteWerkzeuge = $state([])
  let werkzeuge = $state([])
  let sichert = $state(false)
  let laedt = $state(false)
  /* What the fields held when the agent was loaded — what "undo" restores.
     Kept as a plain object rather than re-fetching: a reset must work when
     the service is busy, and it must undo exactly what was typed, not
     whatever the file says by then. */
  let stand = $state(null)
  /* The rest of the front matter, as real controls — everything the file
     knows, so nothing has to be edited in raw markdown to be reachable.

     No model control (Stufe 8): which model a run uses is said in the model
     window's one field, or picked by hand for a single run in the start
     window. A control here would be a third, stored place saying it. */
  let ordner = $state([])
  let maxRunden = $state(30)
  let maxMinuten = $state(20)
  let maxTokens = $state(null) // empty: the settings cascade decides
  /* Empty: the settings cascade decides, exactly as the rows around it read
     an untouched field. A zero is a zero again here — the agent FILE accepts
     a stated zero meaning no thinking at all, and the field can now say that
     without it being mistaken for "untouched". */
  let denklaenge = $state(null)
  /* The stage a run asks for, a word of the chat's own scale. Empty: the file
     names none and no thinking field goes out. The stages are the scale of
     app/denkstufen.py; a model that lacks one drops it at the service. */
  let thinkingStage = $state('')
  const STAGES = ['off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max']
  const stageEntries = $derived([
    { wert: '', text: t('parameter.auto') },
    ...STAGES.map((stage) => ({ wert: stage, text: t('denken.stufe.' + stage) })),
  ])
  let maxBefehlssekunden = $state(null) // empty: the cascade decides, no ceiling of its own
  /* Empty means the agent picked none and keeps the shared default —
     which is exactly what every agent looked like before the field. */
  let farbe = $state('')
  /* The limits stand folded; the line says how many there are. */
  const GRENZEN_ANZAHL = 6
  let grenzenOffen = $state(false)
  /* What the agent is for, in a sentence the chat's model reads beside the
     name when it hands work off. Empty: the file says nothing. */
  let description = $state('')

  $effect(() => {
    api.werkzeuge()
      .then((antwort) => (werkzeuge = antwort.werkzeuge ?? []))
      .catch(() => (werkzeuge = []))
  })

  /* How many tools the list stays fully open for. A number, not an
     estimate: there are eighteen today, and the line sits just above them
     so the list stands open while it is still surveyable — and stops
     growing once tools keep arriving. Past it the list takes a height and
     scrolls, with the house's soft lower edge saying there is more. */
  const LISTE_OFFEN_BIS = 20
  const werkzeugeGedeckelt = $derived(werkzeuge.length > LISTE_OFFEN_BIS)

  /* The tools the list lets the agent use: all of them, or the picked ones
     by their saved names — so a file that still names tools stays warned
     while the list of tools is not loaded. The warning stands as soon as
     that holds a tool of the command kind and one of the web kind: what the
     agent reads from the web could then steer what it runs. */
  const allowed = $derived(
    alleWerkzeuge
      ? werkzeuge
      : gewaehlteWerkzeuge.map((name) => ({
          name,
          server: werkzeuge.find((w) => w.name === name)?.server ?? '',
        })),
  )
  const commandWebWarning = $derived(
    allowed.some((w) => artFuer(w.name, w.server) === 'terminal') &&
      allowed.some((w) => artFuer(w.name, w.server) === 'web'),
  )

  /* Filling the form from an agent that already exists.

     This is the whole point of the change: every control needed to run an
     agent was already here, but the mask only ever opened empty. Anyone who
     wanted to change a folder therefore ended up in the raw markdown, where
     a shared folder looks like a line of YAML.

     The list answer carries every front-matter field; the prompt does not
     travel with it (it can be long, and the list holds all agents), so the
     text comes from the file route, which now hands it out already split
     from the header. */
  /* Every field in one string, to tell whether anything moved since the
     mask was filled — whatever moved it, a key, a chevron, a dialog. */
  function schnappschuss() {
    return JSON.stringify([
      neuName, neuPrompt, alleWerkzeuge, gewaehlteWerkzeuge, ordner, maxRunden,
      maxMinuten, maxTokens, denklaenge, thinkingStage, maxBefehlssekunden, farbe, description,
    ])
  }
  let grund = $state(null)
  $effect(() => {
    geaendert = grund !== null && schnappschuss() !== grund
  })

  function felderSetzen(quelle, prompt) {
    neuName = quelle?.name ?? ''
    neuPrompt = prompt ?? ''
    alleWerkzeuge = !quelle || quelle.tools == null
    gewaehlteWerkzeuge = quelle?.tools ? [...quelle.tools] : []
    ordner = quelle?.folders ? [...quelle.folders] : []
    maxRunden = quelle?.max_rounds ?? 30
    maxMinuten = quelle?.max_minutes ?? 20
    maxTokens = quelle?.max_tokens ?? null
    denklaenge = quelle?.reasoning_budget ?? null
    thinkingStage = quelle?.reasoning_effort ?? ''
    maxBefehlssekunden = quelle?.max_command_seconds ?? null
    farbe = quelle?.color ?? ''
    description = quelle?.description ?? ''
    /* Read untracked: this runs inside the loading effect, which would
       otherwise depend on the very fields it just wrote and loop. */
    grund = untrack(schnappschuss)
  }

  $effect(() => {
    const name = agent?.name
    if (!name) {
      felderSetzen(null, '')
      stand = null
      return
    }
    laedt = true
    let verworfen = false
    api.agentDatei(name)
      .then((datei) => {
        if (verworfen) return
        /* A file whose head cannot be read comes back as a 200 with the
           sentence in `kaputt` and no prompt — the same case as a file that
           cannot be opened: the sentence is reported and the mask gives way
           to the list, with no fields opened over the stale list values. */
        if (datei.kaputt) {
          melde(datei.kaputt, 'fehler')
          onunlesbar ? onunlesbar() : onabbrechen?.()
          return
        }
        felderSetzen(agent, datei.prompt ?? '')
        stand = { agent, prompt: datei.prompt ?? '' }
      })
      .catch((fehler) => {
        if (verworfen) return
        /* The route's own sentence says WHY this file cannot be read — not
           UTF-8, unreadable, or gone — and names the file in those three
           cases. A failure with a sentence of its own reports it, the way
           other call sites report one (App.svelte, ModelleCloud.svelte);
           one without an answer or without a sentence falls back to the
           plain sentence. The settings page shows the same 422 sentence in
           its warning box (SettingsAgents.svelte). The fields that DO parse
           would be a half-truth on top, so the mask gives way to the list. */
        if (fehler?.status && fehler.message) melde(fehler.message, 'fehler')
        else meldeText('agenten.nicht_geladen', {}, 'fehler')
        onunlesbar ? onunlesbar() : onabbrechen?.()
      })
      .finally(() => {
        if (!verworfen) laedt = false
      })
    return () => (verworfen = true)
  })

  function zuruecksetzen() {
    felderSetzen(stand?.agent ?? null, stand?.prompt ?? '')
  }

  /* Whether a thinking length may be set here at all — asked of the service,
     not worked out in this file. The answer is the one the model window
     draws its slider from (`app/parameter.py` `unterstuetzte`: the backend
     has to be able to carry a number per request AND the model has to be
     able to think at all), and only the service can give it — it knows the
     dialect of the endpoint and the thinking profile of the model. Resolved
     for the model a run started NOW would take, because the mask has no
     model pick of its own (`/jobs/laufmodell`, the same answer the start
     window shows).

     `null` means nobody could say: then nothing has SAID the model cannot
     think, and "said nothing" may not be read as "cannot think" — the field
     stays as it was, exactly as the service reads it (`app/parameter.py`). */
  let denkreihe = $state(null)
  /* Which question is the youngest. Two switches in quick succession put two
     answers on the way, and the OLDER one may land last — it would then say
     what the model before the last click was, and the field would be locked
     or open for the wrong one until the next reload. Plain bookkeeping, not
     state: nothing draws it. */
  let denklauf = 0
  $effect(() => {
    /* Asked again whenever the reachable models change (App.svelte reloads
       that list on a clock) and whenever these two switches move: together
       they decide whether a run goes through tools at all, which is what
       moves it between the two servers (`app/agentenmodellwahl.py`). */
    void zustand.modelle.length
    const braucht = alleWerkzeuge || gewaehlteWerkzeuge.length > 0
    const moeglich = braucht && Boolean(zustand.features?.mcp)
    const meinlauf = ++denklauf
    api
      .laufmodell('', moeglich)
      .then((antwort) => {
        if (meinlauf === denklauf) denkreihe = antwort?.denklaenge ?? null
      })
      .catch(() => {
        if (meinlauf === denklauf) denkreihe = null
      })
  })
  const denkGesperrt = $derived(denkreihe?.aktiv === false)
  const denkGrund = $derived(denkGesperrt ? (denkreihe?.grund ?? null) : null)

  function werkzeugSchalten(name) {
    gewaehlteWerkzeuge = gewaehlteWerkzeuge.includes(name)
      ? gewaehlteWerkzeuge.filter((w) => w !== name)
      : [...gewaehlteWerkzeuge, name]
  }

  /* The fields the mask saves: front matter only where it says something.
     No tools field means "every approved tool" — the switch mirrors exactly
     that, so the file and the form tell the same truth. Saved as NAMED
     FIELDS, not as rebuilt text: the server touches only these and keeps
     whatever else the file already carries — a permissions block, comments,
     fields from a newer version. */
  function agentFelder() {
    return {
      color: farbe || null,
      description: description.trim() || null,
      tools: alleWerkzeuge ? null : gewaehlteWerkzeuge,
      folders: ordner.length ? ordner : null,
      max_rounds: maxRunden,
      max_minutes: maxMinuten,
      max_tokens: maxTokens ?? null,
      reasoning_budget: denklaenge ?? null,
      reasoning_effort: thinkingStage || null,
      max_command_seconds: maxBefehlssekunden ?? null,
      prompt: neuPrompt.trim(),
    }
  }

  async function sichern() {
    const name = neuName.trim()
    if (!/^[A-Za-z0-9_-]{1,100}$/.test(name)) {
      melde(t('fehler.agent_name_ungueltig'), 'fehler')
      return
    }
    if (!neuPrompt.trim()) return
    sichert = true
    try {
      await api.agentFelderSichern(name, agentFelder())
      meldeText('agenten.gesichert', { name }, 'erfolg')
      onfertig?.()
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    } finally {
      sichert = false
    }
  }
</script>

<div class="maske">
 <div class="spalten">
  <!-- The left column: what the agent IS — its name, what it is for, its
       instruction. The right one: what it MAY do and where. One column
       under 860 px and on the phone. -->
  <div class="spalte">
  <!-- The name first, across the whole width under its label: it says
       WHICH agent this is. The name is the file's identity, and saving
       writes by name. Renaming an existing agent would quietly make a second
       one, so the field is shown but held while an agent is loaded. -->
  <div class="reihe stacked">
    <span class="etikett">{t('agenten.name')}</span>
    <input
      class="feld name"
      bind:value={neuName}
      disabled={Boolean(agent)}
      aria-label={t('agenten.name')}
    />
  </div>
  <!-- Right under the name: it says what the agent is FOR, which is what
       the chat's model picks by. A sentence, so the field takes the whole
       width under its label rather than the remainder beside it. -->
  <div class="reihe stacked">
    <span class="etikett">{t('agenten.purpose')}</span>
    <input class="feld purpose" bind:value={description}
           aria-label={t('agenten.purpose')} />
  </div>
  <!-- The instruction, under its own label like the two fields above and
       empty when empty. A prompt is prose, not a value: it was a one-line
       field, which made every agent look like it had one sentence in it. -->
  <div class="reihe stacked grow">
    <span class="etikett">{t('agenten.anweisung')}</span>
    <textarea
      class="feld prompt"
      bind:value={neuPrompt}
      aria-label={t('agenten.anweisung')}
    ></textarea>
  </div>
  </div>
  <div class="spalte">
  <!-- The tool selection, as a surface: the switch mirrors the file
       truth that NO list means "every approved tool", and only with
       it off does the list of picks appear. -->
  <div class="heading">{t('werkzeuge.titel')}</div>
  <div class="wzkopf">
    <span>{t('agenten.alle_werkzeuge')}</span>
    <Schalter
      an={alleWerkzeuge}
      beschriftung={t('agenten.alle_werkzeuge')}
      onschalten={() => (alleWerkzeuge = !alleWerkzeuge)}
    />
  </div>
  {#if !alleWerkzeuge}
    <div
      class="wzliste"
      class:gedeckelt={werkzeugeGedeckelt}
      use:rollfade
      transition:fade={{ duration: 120 }}
    >
      {#each werkzeuge as werkzeug (werkzeug.name)}
        <label class="wz">
          <input
            type="checkbox"
            checked={gewaehlteWerkzeuge.includes(werkzeug.name)}
            onchange={() => werkzeugSchalten(werkzeug.name)}
          />
          <span class="wzzeichen">
            <Werkzeugzeichen name={werkzeug.name} server={werkzeug.server} eingebaut={werkzeug.builtin}
                             logo={werkzeug.builtin ? null : serverLogo(werkzeug.server)} />
          </span>
          <span class="wzname werkzeugname">{werkzeug.anzeige ?? werkzeug.name}</span>
        </label>
      {:else}
        <span class="wzleer">{t('agenten.keine_werkzeuge')}</span>
      {/each}
    </div>
  {/if}
  {#if commandWebWarning}
    <p class="tool-warning" role="note">{t('agenten.command_web_warning')}</p>
  {/if}
  <!-- Above the limits, because a colour says WHICH agent this is rather
       than what it may do — and it is pickable while the agent is being
       created, not only afterwards. One round swatch, no list of quick picks;
       centred on the label's line like every other row. -->
  <div class="reihe">
    <span class="etikett">{t('agenten.farbe')}</span>
    <Agentenfarbwahl bind:farbe />
  </div>
  <div class="reihe hoch">
    <span class="etikett">{t('agenten.ordner')}</span>
    <Startordnerpillen bind:ordner />
  </div>
  <!-- The five limits stand behind one folded line with their count: they
       are set once and rarely touched, and five open number fields pushed the
       foot of the mask out of reach. -->
  <button class="grenzenkopf" aria-expanded={grenzenOffen}
          onclick={() => (grenzenOffen = !grenzenOffen)}>
    <span class="winkel" class:auf={grenzenOffen}><Hauszeichen zeichen="chevron_right" groesse={11} /></span>
    <span>{t('agenten.grenzen')}</span>
    <span class="grenzenzahl">{GRENZEN_ANZAHL}</span>
  </button>
  {#if grenzenOffen}
    <div class="grenzen" transition:fade={{ duration: 120 }}>
      <div class="reihe">
        <span class="etikett">{t('agenten.max_runden')}</span>
        <Zahlenfeld bind:wert={maxRunden} min={1} max={999} ganzzahlig />
      </div>
      <div class="reihe">
        <span class="etikett">{t('agenten.max_minuten')}</span>
        <Zahlenfeld bind:wert={maxMinuten} min={1} max={1440} ganzzahlig />
      </div>
      <div class="reihe">
        <span class="etikett">{t('agenten.max_token')}</span>
        <!-- A count starts at 1, as the agent file and the run read it: a zero
             here would be refused on save. Empty is how "Auto" is said. -->
        <Zahlenfeld bind:wert={maxTokens} min={1} max={1000000} schritt={1000}
                    ganzzahlig nullwort={t('parameter.auto')} />
      </div>
      <div class="reihe" class:gesperrt={denkGesperrt} title={denkGrund}>
        <span class="etikett">{t('agenten.denklaenge')}</span>
        <!-- Locked like the model window's slider and with the same two reasons:
             this backend cannot carry a number per request, or this model cannot
             think. The reason is the row's title and nothing else — one sentence
             that belongs ON the thing it is about. A saved value stays where it
             is; it is only not changed here. -->
        <Zahlenfeld bind:wert={denklaenge} min={0} max={1000000} schritt={256}
                    ganzzahlig nullwort={t('parameter.auto')} gesperrt={denkGesperrt} />
      </div>
      <div class="reihe">
        <span class="etikett">{t('agenten.denkstufe')}</span>
        <Auswahlfeld bind:wert={thinkingStage} eintraege={stageEntries} />
      </div>
      <div class="reihe">
        <span class="etikett">{t('agenten.max_befehlssekunden')}</span>
        <!-- Starts at 1 for the same reason as the answer length above. -->
        <Zahlenfeld bind:wert={maxBefehlssekunden} min={1}
                    ganzzahlig nullwort={t('parameter.auto')} />
      </div>
    </div>
  {/if}
  </div>
 </div>
  <!-- No time field here any more (Stufe 6): when an agent runs is said in
       the cron table, in one place, and nowhere else. -->
  <div class="fuss">
    <!-- The one way out that THROWS AWAY what was typed: the cross, in the
         colour that means "this discards". -->
    <button class="signbutton verwirft" onclick={() => onabbrechen?.()}
            aria-label={t('app.abbrechen')} title={t('app.abbrechen')}>
      <Hauszeichen zeichen="kreuz" groesse={16} />
    </button>
    <!-- Only where there is something to go back TO: on a new agent the
         empty fields already are the reset, and a control that undoes
         nothing is worse than none. -->
    {#if stand}
      <button class="signbutton" onclick={zuruecksetzen} disabled={sichert}
              aria-label={t('agenten.zuruecksetzen')} title={t('agenten.zuruecksetzen')}>
        <Hauszeichen zeichen="refresh" groesse={16} />
      </button>
    {/if}
    <button
      class="signbutton sichern"
      onclick={sichern}
      disabled={sichert || laedt || !neuName.trim() || !neuPrompt.trim()}
      title={t('app.sichern')}
      aria-label={t('app.sichern')}
    >
      <Hauszeichen zeichen="save" groesse={16} />
    </button>
  </div>
</div>

<style>
  /* The same column the turning tile's back face was — it just fills a
     window now instead of a tile. */
  .maske {
    --etikettspalte: 108px;
    /* Takes the room the page leaves, so the instruction can grow down to
       the foot instead of leaving the page's lower part empty; and it is
       its own width the two columns are measured by, not the window's. */
    flex: 1 1 auto;
    container: maske / inline-size;
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 12px 14px 16px;
  }
  /* Two columns: what the agent is on the left, what it may do on the
     right; one column under 860 px, where the window itself is narrow. */
  .spalten {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 14px 28px;
    align-items: stretch;
    flex: 1 1 auto;
  }
  .spalte {
    display: flex;
    flex-direction: column;
    gap: 10px;
    min-width: 0;
  }
  @media (max-width: 860px) {
    .spalten { grid-template-columns: minmax(0, 1fr); grid-template-rows: 1fr auto; }
  }
  /* Two columns need room of their own: where the mask itself is narrow,
     the colour code and the bin would be pushed out of the right one. */
  @container maske (max-width: 640px) {
    .spalten { grid-template-columns: minmax(0, 1fr); grid-template-rows: 1fr auto; }
  }
  :global(html[data-phone]) .spalten { grid-template-columns: minmax(0, 1fr); grid-template-rows: 1fr auto; }
  /* A fingertip is taller than a pointer. */
  :global(html[data-phone]) .signbutton {
    width: 44px;
    height: 44px;
  }
  /* Caution, not failure: the quiet yellow form of the house, colour on the
     text and the line, never the full colour behind the words. */
  .tool-warning {
    margin: 0;
    padding: 9px 12px;
    border: 1px solid color-mix(in srgb, var(--gelb) 45%, var(--linie-stark));
    background: color-mix(in srgb, var(--gelb) 8%, var(--bg));
    border-radius: 9px;
    font-size: 12.5px;
    line-height: 1.45;
    color: var(--gelb-text);
  }
  /* The tools' own heading, over the switch of "all approved tools". */
  .heading {
    font-size: 13px;
    font-weight: 600;
    color: var(--text);
  }
  .feld {
    width: 100%;
    /* A field on glass: glass with the house's field outline. */
    border: 1px solid var(--feldstrich);
    background: var(--glass-button);
    color: var(--text);
    font: inherit;
    font-size: 13px;
    outline: none;
    padding: 7px 12px;
    border-radius: 9px;
  }
  /* The name heads everything below it, so it reads like a heading and not
     like the first of eight equal rows. */
  .feld.name {
    font-size: 15px;
    font-weight: 600;
    color: var(--text);
    padding: 6px 12px;
  }
  /* Held, not hidden: the name of a loaded agent is worth seeing, and the
     reason it cannot be typed over is that saving writes by it. */
  .feld.name:disabled {
    color: var(--text);
    -webkit-text-fill-color: var(--text);
    opacity: 1;
  }
  /* The instruction is a block of its own height that scrolls inside
     itself, so a long prompt never stretches the mask; the corner still
     drags it taller. */
  .feld.prompt {
    font: 400 13px/1.55 var(--schrift);
    resize: vertical;
    flex: 1 1 auto;
    height: auto;
    min-height: 320px;
    overflow-y: auto;
    padding: 9px 12px;
  }
  /* One label, one control — the quiet rows of the mask.

     The label column is a NUMBER, not "as wide as the longest word". A
     column measured by its content is a different column in every language,
     and one new word in the catalogue moves every field in the mask. With a
     fixed width the catalogue cannot reach the layout at all.

     108 px carries the longest label either catalogue holds today and still
     leaves the control its width at the rail's narrowest (260 px of
     content). What does not fit wraps — the column is never torn open. */
  .reihe {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 12px;
    color: var(--text-leise);
  }
  .reihe.hoch { align-items: flex-start; }
  .reihe.stacked { flex-direction: column; align-items: stretch; gap: 4px; }
  .reihe.stacked .etikett { flex: none; width: auto; }
  /* The instruction's row takes what is left of the column. */
  .reihe.stacked.grow { flex: 1 1 auto; }
  /* A locked row steps back the way the model window's locked row does, and
     the reason stands in the title. The number field dims its own input on
     top of that, so the field itself reads a shade quieter than the model
     window's slider — the same lock, drawn with the two means each form has. */
  .reihe.gesperrt { opacity: 0.45; cursor: not-allowed; }
  .etikett {
    flex: 0 0 var(--etikettspalte);
    width: var(--etikettspalte);
    min-width: 0;
    padding-top: 2px;
    /* A word longer than the column breaks inside itself rather than
       pushing the column wider — the one case wrapping alone cannot hold. */
    overflow-wrap: anywhere;
  }
  /* The control takes the whole remainder, so every field in the mask
     starts and ends on the same edge. */
  .reihe > :global(:not(.etikett)) {
    flex: 1 1 auto;
    min-width: 0;
  }
  /* The folded line of the limits: a quiet row, the count at the far end. */
  .grenzenkopf {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    padding: 4px 0;
    border: none;
    background: none;
    font: inherit;
    font-size: 12px;
    color: var(--text-leise);
    text-align: left;
    cursor: pointer;
  }
  .grenzenkopf:hover { color: var(--text); }
  .grenzenzahl {
    margin-left: auto;
    color: var(--text-still);
    font-variant-numeric: tabular-nums;
  }
  .winkel {
    display: inline-flex;
    flex: none;
    transition: transform 0.15s;
  }
  .winkel.auf { transform: rotate(90deg); }
  .grenzen {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  @media (prefers-reduced-motion: reduce) {
    .winkel { transition: none; }
  }
  .wzkopf {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    font-size: 12px;
    color: var(--text-leise);
    padding-top: 2px;
  }
  /* The list spreads downwards rather than rolling in a box of five while
     free space stands under it. Only once it is capped does it scroll, and
     then the soft lower edge is what says there is more — the house has no
     scrollbars to say it with (lib/rollfade.js). */
  .wzliste {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .wzliste.gedeckelt {
    max-height: 300px;
    overflow-y: auto;
  }
  /* Every mark of the list in one box, whatever the mark draws: the plain
     chevron a tool without a mark of its own gets is smaller than the
     others and would pull its name to the left. */
  .wzzeichen {
    --wz-groesse: 18px;
    flex: none;
    width: 18px;
    height: 18px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  .wz {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;
    color: var(--text-leise);
    padding: 3px 2px;
    border-radius: 9px;
    cursor: pointer;
  }
  .wz:hover { background: var(--glass-hover); color: var(--text); }
  .wz input { accent-color: var(--text); }
  /* Nothing: how a tool name is set is one rule for the whole program
     (`.werkzeugname`, stil/global.css). */
  .wzleer {
    font-size: 11.5px;
    color: var(--text-still);
    padding: 2px;
  }
  .fuss {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: 2px;
    padding-top: 6px;
    border-top: none;
  }
  /* The foot's signs: button glass with the field outline as a ring ON the
     edge, so the button keeps the house's size. */
  .signbutton {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    color: var(--text);
    cursor: pointer;
  }
  .signbutton:hover:not(:disabled) { background: var(--glass-hover); }
  .signbutton:disabled { opacity: 0.5; cursor: default; }
  /* Throws the typed text away: a state surface mixes its colour over the
     button glass, the full colour never goes behind a sign. */
  .signbutton.verwirft {
    color: var(--rot-text);
    background: color-mix(in srgb, var(--rot) 12%, var(--glass-button));
  }
  .signbutton.verwirft:hover:not(:disabled) {
    background: color-mix(in srgb, var(--rot) 18%, var(--glass-button));
  }
  .signbutton.sichern { margin-left: auto; }
</style>
