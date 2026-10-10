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
  const VORLAGE = `---
description: What this skill does, in one line.
auto: false
---

Write the instruction here. When this skill is chosen, the model follows
what stands below.
`
  /* Editing reuses the same form. `bearbeitet` carries the name of the
     skill whose file is open — null while writing a fresh one. The name
     field is locked during an edit: the name IS the identity, and a
     changed name would quietly write a second skill instead. */
  let bearbeitet = $state(null)
  function neuAnfangen() {
    bearbeitet = null
    neuName = ''
    neuInhalt = VORLAGE
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

  /* Only the automatic ones cost anything, and only they are counted. The
     number is here because the cost is invisible otherwise: it is paid on
     every request, in a place nobody looks. */
  const automatisch = $derived(zeilen.filter((z) => z.auto).length)

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
      <button class="textknopf" onclick={() => (schreibt = false)}>{t('app.abbrechen')}</button>
      <button class="knopf wichtig" disabled={!neuName.trim() || !neuInhalt.trim()} onclick={neuSpeichern}>
        {t('app.sichern')}
      </button>
    </div>
  </div>
{:else}
<div class="kopf">
  <span>{t('skills.wieviele', { anzahl: automatisch })}</span>
</div>

<div class="schalterzeile">
  <div class="beschriftung">
    {t('skills.selbst')}
    <span class="hinweis">{t('skills.selbst_hinweis')}</span>
  </div>
  <Schalter an={selbstWaehlen} beschriftung={t('skills.selbst')} onschalten={selbstSchalten} />
</div>

{#if !zeilen.length}
  <p class="leer">{t('skills.keine')}</p>
{/if}

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
    <button class="zurueck" onclick={() => bearbeiten(zeile)}>
      {t('skills.bearbeiten')}
    </button>
    <!-- Only what the user owns can go: a shipped skill would be back with
         the next update, so it stays switchable and nothing more. -->
    {#if zeile.eigen}
      <button
        class="zurueck"
        class:gefahr={!zeile.mitgeliefert}
        onclick={() => entfernen(zeile)}
      >
        {t(zeile.mitgeliefert ? 'skills.zuruecksetzen' : 'skills.loeschen')}
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
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       stroke-width="2.2" stroke-linecap="round"><path d="M12 5 V19 M5 12 H19" /></svg>
  {t('skills.schreiben')}
</button>
{/if}

<style>
  .kopf {
    font-size: 12.5px;
    color: var(--text-still);
    padding: 0 2px 12px;
  }
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
    font-size: 13.5px;
    min-width: 0;
  }
  .hinweis {
    display: block;
    font-size: 12px;
    color: var(--text-still);
    margin-top: 2px;
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
  /* Brightness, not colour: having taken a shipped skill over is a fact
     about it, not a state it is in. */
  .vermerk {
    font-size: 11px;
    color: var(--text-leise);
    /* A fact badge wears the divider line, not the field outline; one pixel
       of edge is taken from the padding so the mark keeps its size. */
    border: 1px solid var(--linie);
    border-radius: 9px;
    padding: 0 7px 1px;
    background: var(--glass-button);
  }
  /* The field outline is the edge of a quiet button on a card, drawn as a
     ring ON the edge so the button keeps the house's size: the line colour
     darkened to 3 : 1 on the light grounds, the glass edge on the dark. */
  .zurueck {
    border: none;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    border-radius: 9px;
    color: var(--text);
    font: inherit;
    font-size: 12px;
    padding: 5px 11px;
    cursor: pointer;
    flex: none;
  }
  /* Red means it deletes — the house colour for exactly this, and only on
     the button that really destroys something. */
  .zurueck.gefahr {
    color: var(--rot-text);
    background: color-mix(in srgb, var(--rot) 12%, var(--glass-button));
  }
  .zurueck.gefahr:hover {
    background: color-mix(in srgb, var(--rot) 18%, var(--glass-button));
  }
  .zurueck:hover {
    background: var(--glass-hover);
  }
  .leer {
    font-size: 13px;
    color: var(--text-still);
    padding: 4px 2px 0;
    margin: 0;
  }

  /* The way to a skill of one's own: a dashed tile, plus and word, the same
     shape the agents list uses for a new agent. */
  .skillneu {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
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
  .knopf {
    border: none;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    color: var(--text);
    font: inherit;
    font-size: 13px;
    padding: 7px 15px;
    border-radius: 9px;
    cursor: pointer;
    transition: background 0.12s;
  }
  .knopf:hover:not(:disabled) {
    background: var(--glass-hover);
  }
  /* The main button is button glass with its fine edge, like the start
     button; only Send stays filled. */
  .knopf.wichtig {
    background: var(--glass-button);
    color: var(--text);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    font-weight: 500;
  }
  .knopf.wichtig:hover:not(:disabled) {
    background: color-mix(in srgb, var(--text) 6%, var(--glass-button));
  }
  .knopf:disabled {
    opacity: 0.5;
    cursor: default;
  }
  .textknopf {
    border: none;
    background: none;
    color: var(--text-leise);
    font: inherit;
    font-size: 12.5px;
    cursor: pointer;
    padding: 4px 8px;
    border-radius: 9px;
  }
  .textknopf:hover {
    background: var(--glass-hover);
    color: var(--text);
  }
</style>
