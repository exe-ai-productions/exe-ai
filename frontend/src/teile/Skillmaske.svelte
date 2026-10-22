<script>
  /* The skill list in the settings: what exists, and which of them the model
     may reach for by itself.

     One list for both places. Where a skill comes from only matters here,
     where it decides what a change does — a shipped one is copied before it
     is touched, so the next update walks past the copy instead of taking it
     back. */
  import { api } from '../lib/api.js'
  import { t } from '../lib/texte.svelte.js'
  import { frage, melde } from '../lib/zustand.svelte.js'
  import { meldeText } from '../lib/meldewesen.svelte.js'
  import { skillsLaden } from '../lib/skills.svelte.js'
  import Hauszeichen from './Hauszeichen.svelte'
  import InfoMark from './InfoMark.svelte'
  import Schalter from './Schalter.svelte'
  import Werkzeugzeichen from './Werkzeugzeichen.svelte'

  let zeilen = $state([])
  let selbstWaehlen = $state(true)

  /* Writing a skill of one's own: a name and the file's text. The template
     is filled in, not empty, so nobody has to guess the shape. `description`
     is what the list shows; `auto` decides whether it may be reached for
     without being named. */
  let schreibt = $state(false)
  let neuName = $state('')
  let neuInhalt = $state('')
  /* Built when the form opens, so its two sentences are in the language the
     interface has at that moment. */
  const vorlage = () => `---
${t('skills.template_description')}
auto: false
---

${t('skills.template_instructions')}
`
  /* Editing reuses the same form. `bearbeitet` carries the name of the
     skill whose file is open — null while writing a fresh one. The name
     field is locked during an edit: the name IS the identity, and a
     changed name would quietly write a second skill instead. */
  let bearbeitet = $state(null)
  function neuAnfangen() {
    bearbeitet = null
    neuName = ''
    neuInhalt = vorlage()
    schreibt = true
  }
  async function bearbeiten(zeile) {
    try {
      const datei = await api.skillDatei(zeile.name)
      bearbeitet = zeile.name
      neuName = zeile.name
      neuInhalt = datei.inhalt
      schreibt = true
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    }
  }
  async function neuSpeichern() {
    const name = neuName.trim()
    if (!name || !neuInhalt.trim()) return
    try {
      if (bearbeitet) await api.skillSichern(bearbeitet, neuInhalt)
      else await api.skillSchreiben(name, neuInhalt)
      schreibt = false
      bearbeitet = null
      await laden()
      skillsLaden()
      meldeText('skills.geschrieben', { name }, 'erfolg')
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    }
  }

  /* Loaded here rather than by whoever shows the mask: the component does
     not exist yet at the moment the section is switched to, so a call from
     outside lands on nothing. */
  $effect(() => {
    laden()
  })

  async function laden() {
    try {
      zeilen = await api.skillsVerwaltung()
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    }
    try {
      const stand = await api.einstellungAufgeloest('skills_auto')
      if (stand?.wert && typeof stand.wert.an === 'boolean') selbstWaehlen = stand.wert.an
    } catch {
      /* No setting means the default, and the default is on. */
    }
  }

  async function selbstSchalten(an) {
    const vorher = selbstWaehlen
    selbstWaehlen = an
    try {
      await api.einstellungSetzen('global', 'skills_auto', { an })
    } catch (fehler) {
      selbstWaehlen = vorher
      melde(String(fehler.message || fehler), 'fehler')
    }
  }

  async function autoSchalten(zeile, an) {
    const vorher = zeile.auto
    zeile.auto = an
    try {
      const neu = await api.skillAuto(zeile.name, an)
      Object.assign(zeile, neu)
      skillsLaden()
    } catch (fehler) {
      zeile.auto = vorher
      melde(String(fehler.message || fehler), 'fehler')
    }
  }

  /* One route for both, and two different things to the user: a shipped
     skill comes back in its own version, a skill the user wrote is gone for
     good. The second one asks first — through the house's own prompt, never
     a browser box — and wears the colour of deleting. */
  async function entfernen(zeile) {
    const endgueltig = !zeile.mitgeliefert
    if (endgueltig) {
      const ja = await frage(t('skills.loeschen_frage', { name: zeile.name }), {
        okSchluessel: 'skills.loeschen',
        danger: true,
      })
      if (!ja) return
    }
    try {
      await api.skillZuruecksetzen(zeile.name)
      await laden()
      skillsLaden()
      meldeText(
        endgueltig ? 'skills.geloescht' : 'skills.zurueckgesetzt',
        { name: zeile.name },
        'erfolg',
      )
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    }
  }
</script>

{#if schreibt}
  <div class="schreibform">
    <input
      class="namensfeld"
      bind:value={neuName}
      placeholder={t('skills.neu_name')}
      spellcheck="false"
      autocapitalize="off"
      readonly={bearbeitet !== null}
    />
    <textarea class="inhaltsfeld" bind:value={neuInhalt} spellcheck="false"></textarea>
    <div class="formfuss">
      <button class="symbolknopf" onclick={() => (schreibt = false)}
              aria-label={t('app.abbrechen')} title={t('app.abbrechen')}>
        <Hauszeichen zeichen="kreuz" groesse={18} />
      </button>
      <button class="symbolknopf" disabled={!neuName.trim() || !neuInhalt.trim()} onclick={neuSpeichern}
              aria-label={t('app.sichern')} title={t('app.sichern')}>
        <Hauszeichen zeichen="save" groesse={18} />
      </button>
    </div>
  </div>
{:else}
<div class="schalterzeile">
  <div class="beschriftung mitmarke">{t('skills.selbst')}<InfoMark text={t('skills.info_selbst')} /></div>
  <Schalter an={selbstWaehlen} beschriftung={t('skills.selbst')} onschalten={selbstSchalten} />
</div>

{#each zeilen as zeile (zeile.name)}
  <div class="zeile">
    <!-- Through the server, exactly as the chat row resolves it: the answer
         has to be the same everywhere it is asked. -->
    <Werkzeugzeichen server="skills" />
    <div class="mitte">
      <div class="name">
        /{zeile.name}
        {#if zeile.mitgeliefert && zeile.eigen}
          <span class="vermerk">{t('skills.geaendert')}</span>
        {/if}
      </div>
      <div class="was">{zeile.beschreibung}</div>
    </div>
    <!-- Every skill can be opened and edited — a shipped one is quietly
         copied to the user's folder on save, so the change survives the
         next update. -->
    <button class="signbutton" onclick={() => bearbeiten(zeile)}
            aria-label={t('skills.bearbeiten')} title={t('skills.bearbeiten')}>
      <Hauszeichen zeichen="stift" groesse={16} />
    </button>
    <!-- Only what the user owns can go: a shipped skill would be back with
         the next update, so it stays switchable and nothing more. A changed
         shipped one gets its own version back (both ways round arrows); one
         the user wrote is deleted (the bin, in the colour of deleting). -->
    {#if zeile.eigen}
      <button
        class="signbutton"
        class:danger={!zeile.mitgeliefert}
        onclick={() => entfernen(zeile)}
        aria-label={t(zeile.mitgeliefert ? 'skills.zuruecksetzen' : 'skills.loeschen')}
        title={t(zeile.mitgeliefert ? 'skills.zuruecksetzen' : 'skills.loeschen')}
      >
        <Hauszeichen zeichen={zeile.mitgeliefert ? 'refresh' : 'trash'} groesse={16} />
      </button>
    {/if}
    <Schalter
      an={zeile.auto}
      beschriftung={t('skills.selbst')}
      onschalten={(an) => autoSchalten(zeile, an)}
    />
  </div>
{/each}

<button class="skillneu" onclick={neuAnfangen}>
  <Hauszeichen zeichen="plus" groesse={15} />
  {t('skills.schreiben')}
</button>
{/if}

<style>
  .schalterzeile {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 12px 16px;
    border-radius: 9px;
    /* A card on the page: card glass with its fine line. */
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    margin-bottom: 14px;
  }
  .schalterzeile + .zeile {
    border-top-color: transparent;
    border-top-left-radius: 9px;
    border-top-right-radius: 9px;
  }
  .beschriftung {
    flex: 1;
    font-size: 13.5px;
    min-width: 0;
  }
  /* The mark right after the name, 6 px away, and its sentence on a line of
     its own below the name when it is open. */
  .mitmarke {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
  }
  .mitmarke :global(.mark) {
    margin-left: 0;
  }
  .zeile {
    display: flex;
    align-items: center;
    gap: 11px;
    padding: 11px 16px;
    border-top: 1px solid var(--linie);
    background: var(--glass-card);
  }
  .zeile:has(+ .skillneu) {
    border-bottom-left-radius: 9px;
    border-bottom-right-radius: 9px;
  }
  .mitte {
    flex: 1;
    min-width: 0;
  }
  .name {
    font-size: 13px;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .was {
    font-size: 12px;
    color: var(--text-still);
    margin-top: 1px;
  }
  /* Having taken a shipped skill over is a fact about it, not a state it is
     in: plain quiet text behind the name, no badge. */
  .vermerk {
    font-size: 12.5px;
    color: var(--text-leise);
  }
  /* A sign button on a card: button glass with the field outline drawn as a
     ring ON the edge, so the button keeps the house's size. */
  .signbutton {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 30px;
    border: none;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    border-radius: 9px;
    color: var(--text);
    cursor: pointer;
    flex: none;
  }
  .signbutton:hover {
    background: var(--glass-hover);
  }
  /* Red means it deletes — the house colour for exactly this, and only on
     the button that really destroys something. */
  .signbutton.danger {
    color: var(--rot-text);
    background: color-mix(in srgb, var(--rot) 12%, var(--glass-button));
  }
  .signbutton.danger:hover {
    background: color-mix(in srgb, var(--rot) 18%, var(--glass-button));
  }

  /* The way to a skill of one's own: a dashed tile, plus and word, the same
     shape the agents list uses for a new agent. */
  .skillneu {
    display: flex;
    align-items: center;
    gap: 8px;
    width: fit-content;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
    font: 500 13px var(--schrift);
    padding: 0 12px;
    height: 36px;
    margin-top: 8px;
    cursor: pointer;
    transition: color 0.12s, background 0.12s;
  }
  .skillneu:hover {
    color: var(--text);
    background: var(--glass-hover);
  }

  .schreibform {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .namensfeld {
    font: 500 13px var(--schrift);
    color: var(--text);
    /* A field on glass: glass with the house's field outline. */
    background: var(--glass-button);
    border: 1px solid var(--feldstrich);
    border-radius: 9px;
    padding: 8px 12px;
    height: 32px;
  }
  /* The skill file as it lies on disk, front matter included — a source
     view, so the fixed face keeps its dashes and indentation in line. */
  .inhaltsfeld {
    font: 400 12.5px/1.6 var(--schrift-fest);
    color: var(--text);
    background: var(--glass-button);
    border: 1px solid var(--feldstrich);
    border-radius: 9px;
    padding: 10px 12px;
    min-height: 220px;
    resize: vertical;
    width: 100%;
  }
  .formfuss {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
  }
  .symbolknopf {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    color: var(--text);
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    border: none;
    border-radius: 9px;
    cursor: pointer;
  }
  .symbolknopf:hover:not(:disabled) {
    background: var(--glass-hover);
  }
  .symbolknopf:active:not(:disabled) {
    transform: scale(0.95);
  }
  .symbolknopf:disabled {
    opacity: 0.5;
    cursor: default;
  }
</style>
