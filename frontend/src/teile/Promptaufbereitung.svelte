<script>
  /* The picture server's "Prompt preparation": which server writes the
     picture prompts, and the instruction it gets for each picture family.

     The picture window's "Enhance" button and draw_image both ask the one
     route that reads this (app/api/v1/bildprompt.py), so what is set here is
     what both get. Kept at once, without a save button, the way the speech
     server keeps its clean-up; "reset" brings back the family's works text.

     The family list holds every family that draws from text, under the
     reader its prompt goes through. Which one applies to a picture is read
     from the picture model, not chosen here — this list only picks the
     instruction to read and rewrite. */
  import { api } from '../lib/api.js'
  import { t } from '../lib/texte.svelte.js'
  import { melde, zustand } from '../lib/zustand.svelte.js'
  import { familyOf } from '../lib/imageFamilies.svelte.js'
  import Serverabschnitt from './Serverabschnitt.svelte'
  import Auswahlfeld from './Auswahlfeld.svelte'
  import WachsendesFeld from './WachsendesFeld.svelte'

  const SCHLUESSEL = 'bildaufbereitung'
  const KENNUNG = 'kennung:'

  let stand = $state(null)
  let verbesserer = $state('agent')
  let familie = $state('sdxl')
  let text = $state('')

  async function laden() {
    try {
      stand = await api.bildAufbereitung()
      verbesserer = stand.verbesserer
      text = stand.anweisungen[familie] ?? ''
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    }
  }
  laden()

  /* The three servers of this program, then every cloud model the model
     list knows, under its own heading. */
  const serverauswahl = $derived([
    { wert: 'agent', text: t('agentserver.titel') },
    { wert: 'modell', text: t('modell.server') },
    { wert: 'putzmodell', text: t('bereinigungsserver.titel') },
    ...cloudmodelle,
  ])
  /* A cloud model chosen once and no longer in the model list stays in the
     list under its id, so the row says which server is asked. */
  const cloudmodelle = $derived.by(() => {
    const ids = zustand.modelle.filter((m) => m.group !== 'local').map((m) => m.id)
    const gewaehlt = verbesserer.startsWith(KENNUNG) ? verbesserer.slice(KENNUNG.length) : ''
    if (gewaehlt && !ids.includes(gewaehlt)) ids.unshift(gewaehlt)
    return ids.map((id) => ({ wert: `${KENNUNG}${id}`, text: id, group: t('modell.cloud') }))
  })

  const LESERNAMEN = $derived({ clip: 'CLIP', t5: 'T5', llm: t('bildserver.leser_llm') })
  const familienauswahl = $derived(
    Object.entries(stand?.leser ?? {}).flatMap(([leser, namen]) =>
      namen.map((name) => ({
        wert: name,
        text: familyOf(name)?.label ?? name,
        group: LESERNAMEN[leser],
      })),
    ),
  )

  async function sichern(wert) {
    try {
      const antwort = await api.einstellungMischen('global', SCHLUESSEL, wert)
      if (wert.anweisungen && stand) {
        const name = Object.keys(wert.anweisungen)[0]
        stand.anweisungen[name] = wert.anweisungen[name] ?? stand.ab_werk[name]
      }
      return antwort
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    }
  }

  function familieGewaehlt(neu) {
    /* An edit still waiting for its moment is kept for the family it was
       made in before the list moves on. */
    clearTimeout(stift)
    if (stand && text !== stand.anweisungen[familie]) anweisungSichern(familie, text)
    familie = neu
    text = stand?.anweisungen[neu] ?? ''
  }

  /* The instruction is kept a moment after the last keystroke. The works
     text travels as "none of the user's own", so a family set back to it
     follows the works text from then on. */
  let stift
  $effect(() => {
    const jetzt = text
    const name = familie
    if (!stand || jetzt === stand.anweisungen[name]) return
    clearTimeout(stift)
    stift = setTimeout(() => anweisungSichern(name, jetzt), 600)
    return () => clearTimeout(stift)
  })

  function anweisungSichern(name, jetzt) {
    const werk = stand.ab_werk[name]
    sichern({ anweisungen: { [name]: jetzt.trim() && jetzt !== werk ? jetzt : null } })
  }
</script>

<Serverabschnitt titel={t('bildserver.aufbereitung')}>
  <div class="zeile">
    <label class="name" for="bs-verbesserer">{t('bildserver.verbessert_von')}</label>
    <div class="wahl">
      <Auswahlfeld
        id="bs-verbesserer"
        bind:wert={verbesserer}
        eintraege={serverauswahl}
        beschriftung={t('bildserver.verbessert_von')}
        gewaehlt={(neu) => sichern({ verbesserer: neu })}
      />
    </div>
  </div>
  <div class="zeile">
    <label class="name" for="bs-bildfamilie">{t('bildserver.bildfamilie')}</label>
    <div class="wahl">
      <Auswahlfeld
        id="bs-bildfamilie"
        wert={familie}
        eintraege={familienauswahl}
        beschriftung={t('bildserver.bildfamilie')}
        gewaehlt={familieGewaehlt}
      />
    </div>
  </div>
  <div class="zeile stapel">
    <label class="name" for="bs-anweisung">{t('bildserver.anweisung')}</label>
    <WachsendesFeld knapp zeilen={3} bind:wert={text} beschriftung={t('bildserver.anweisung')} />
    <button class="stillknopf" onclick={() => (text = stand?.ab_werk[familie] ?? text)}>
      {t('sprachserver.zuruecksetzen')}
    </button>
  </div>
</Serverabschnitt>
