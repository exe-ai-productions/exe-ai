<script>
  /* The right half of both tabs of the Models page: the settings of one
     model.

     One component, used by the local tab and the cloud one. A parameter is
     a parameter no matter where the model computes — two copies would drift
     apart the moment somebody changed a slider in one of them.

     Which knobs appear is decided by the backend, not here: the model brings
     its own list, and it only contains what the dialect really evaluates. */
  import { t, texte } from '../lib/texte.svelte.js'
  import { fractionDigits, formatNumber, parseNumber } from '../lib/numberDisplay.js'
  import { melde } from '../lib/zustand.svelte.js'
  import Serverabschnitt from './Serverabschnitt.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import {
    einstellungen, parameterLaden, parameterSetzen, parameterZuruecksetzen,
  } from '../lib/einstellungen.svelte.js'

  /* `withName`: the model's name stands in the title ("Parameter · name") —
     for the page that shows the parameters of one model among several. */
  let { modell, withName = false } = $props()

  let werte = $state({})
  let geladenesModell = null
  let sicherZeit

  /* What applies when nobody has set anything. Not sent to the server — this
     is only what the slider stands at before the first touch.

     The two LENGTHS are deliberately absent: an untouched response length
     and an untouched thinking length are not a resting number but "Auto",
     and the field says that word instead of standing somewhere. Any number
     here would have been the same one for a model with eight thousand
     tokens of room and one with a million. */
  const VORGABEN = {
    temperature: 0.7, top_p: 0.95, top_k: 40, min_p: 0.05,
    repeat_penalty: 1, repeat_last_n: 64, presence_penalty: 0, frequency_penalty: 0,
    typical_p: 1, seed: -1,
  }

  $effect(() => {
    const kennung = modell?.id ?? null
    if (!kennung || kennung === geladenesModell) return
    geladenesModell = kennung
    parameterLaden(kennung)
  })

  $effect(() => {
    if (einstellungen.fuerModell !== modell?.id) return
    const frisch = {}
    for (const p of modell?.parameter ?? []) frisch[p.name] = gespeicherterWert(p)
    werte = frisch
  })

  /* What the knob stands at: the stored value, then its resting position —
     and `null` for the two with none, which is what the field draws the word
     for. */
  function gespeicherterWert(p) {
    const gesetzt = einstellungen.parameter?.[p.name]
    if (gesetzt !== undefined && gesetzt !== null) return gesetzt
    return VORGABEN[p.name] ?? null
  }

  function wertVon(p) {
    const eigen = werte[p.name]
    return eigen === undefined ? gespeicherterWert(p) : eigen
  }

  /* Nothing set. Written out rather than tested with `!wert`, which would
     read a real zero — Top-K's "0 disables it" — as an empty field. */
  const leer = (wert) => wert === null || wert === undefined || wert === ''

  /* Where a value comes from. Without this the number stands there and nobody
     knows why — the cascade delivers the answer, so it may as well be shown. */
  function herkunftVon(p) {
    const woher = einstellungen.herkunft?.[p.name]
    if (!woher) return t('parameter.aus_vorgabe')
    if (woher.startsWith('modell:')) return t('parameter.aus_modell')
    if (woher.startsWith('chat:')) return t('parameter.aus_chat')
    return t('parameter.aus_global')
  }

  function setzen(p, wert) {
    werte[p.name] = wert
    if (!modell) return
    clearTimeout(sicherZeit)
    sicherZeit = setTimeout(async () => {
      try {
        await parameterSetzen(modell.id, p.name, wert)
      } catch {
        melde(t('parameter.nicht_gesichert'), 'fehler')
      }
    }, 350)
  }

  async function zuruecksetzen() {
    if (!modell) return
    try {
      await parameterZuruecksetzen(modell.id)
      const frisch = {}
      for (const p of modell?.parameter ?? []) frisch[p.name] = VORGABEN[p.name] ?? null
      werte = frisch
      melde(t('parameter.zurueckgesetzt'), 'erfolg')
    } catch {
      melde(t('parameter.nicht_gesichert'), 'fehler')
    }
  }

  const sectionTitle = $derived(
    withName && modell?.name ? `${t('parameter.titel')} · ${modell.name}` : t('parameter.titel'),
  )
  /* Two cards, one rule for local, cloud and phone: what picks the next
     word on the left, the lengths and the brakes on the right, each in this
     order. What a model does not offer is missing; a knob that has no place
     in either list goes to the end of the right card; a card without a row
     is not drawn. */
  const SAMPLING_ORDER = ['temperature', 'top_p', 'top_k', 'min_p', 'typical_p', 'seed']
  const LENGTH_ORDER = [
    'max_tokens', 'reasoning_budget', 'repeat_penalty', 'repeat_last_n',
    'presence_penalty', 'frequency_penalty',
  ]
  const offered = $derived(modell?.parameter || [])
  const inOrder = (order) => order.map((name) => offered.find((p) => p.name === name)).filter(Boolean)
  const sampling = $derived(inOrder(SAMPLING_ORDER))
  const lengths = $derived([
    ...inOrder(LENGTH_ORDER),
    ...offered.filter((p) => !SAMPLING_ORDER.includes(p.name) && !LENGTH_ORDER.includes(p.name)),
  ])
</script>

{#snippet regler(p)}
  {@const wert = wertVon(p)}
  {@const nachkomma = p.ganzzahl ? 0 : fractionDigits(p.schritt)}
  {@const gesperrt = p.aktiv === false}
  {@const anteil = leer(wert) || p.maximum === p.minimum
    ? 0
    : Math.min(100, Math.max(0, ((wert - p.minimum) / (p.maximum - p.minimum)) * 100))}
  <!-- One row per knob, as the server windows draw theirs: the name and
       the number on one line, the track under them. What the knob does
       rides on the row as its title — and a locked row carries its reason
       there instead: a line of explanation under a control is a house rule
       away. -->
  <div class="zeile regel" class:gesperrt title={gesperrt ? p.grund : p.hinweis}>
    <div class="kopfzeile">
      <label class="regelname" for="pt-{p.name}">{p.label}</label>
      <!-- Where the value comes from is the box's title: the cascade knows,
           so it shows — on the number it is about. -->
      <input
        class="zahl"
        class:zahl-unversendet={!einstellungen.herkunft?.[p.name]}
        value={leer(wert) ? t('parameter.auto') : formatNumber(wert, nachkomma, texte.sprache)}
        disabled={gesperrt}
        title={gesperrt ? null : herkunftVon(p)}
        onchange={(e) => {
          const eingabe = e.currentTarget.value.trim()
          if (!eingabe) {
            // Cleared by hand: back to "Auto", and nothing is sent for it.
            e.currentTarget.value = t('parameter.auto')
            setzen(p, null)
            return
          }
          const zahl = Math.min(p.maximum, Math.max(p.minimum, parseNumber(eingabe) || 0))
          e.currentTarget.value = formatNumber(zahl, nachkomma, texte.sprache)
          setzen(p, zahl)
        }}
        aria-label={p.label}
      />
    </div>
    <!-- Nothing set: the handle sits at the low end and the box above it
         says the word instead of a number. The slider cannot show "unset" —
         it has no position for it — so the box is what says so, and the
         first drag of the handle is what turns the word into a number. -->
    <input
      id="pt-{p.name}"
      class="regelspur"
      type="range"
      min={p.minimum}
      max={p.maximum}
      step={p.schritt}
      value={leer(wert) ? p.minimum : wert}
      disabled={gesperrt}
      style:--anteil="{anteil}%"
      oninput={(e) => setzen(p, Number(e.currentTarget.value))}
    />
  </div>
{/snippet}

{#snippet card(list)}
  {#if list.length}
    <Serverabschnitt>
      {#each list as p (p.name)}
        {@render regler(p)}
      {/each}
    </Serverabschnitt>
  {/if}
{/snippet}

<!-- All of them at once. The show-more button made the window jump in
     height every time you switched between a model and a provider; the panel
     scrolls instead. Under the head stand two cards of the same width, each as
     high as its rows. -->
<div class="parameter">
  <Serverabschnitt
    zeichen="settings_two"
    gewicht={1}
    titel={sectionTitle}
    bare
  >
    {#snippet rechts()}
      <!-- The reset is a sign at the right end of the head. -->
      <button
        class="signbutton"
        onclick={zuruecksetzen}
        aria-label={t('parameter.zuruecksetzen')}
        title={t('parameter.zuruecksetzen')}
      >
        <Hauszeichen zeichen="refresh" groesse={16} />
      </button>
    {/snippet}
    <div class="param-cards">
      {@render card(sampling)}
      {@render card(lengths)}
    </div>
  </Serverabschnitt>
</div>

<style>
  .parameter {
    display: flex;
    flex-direction: column;
    gap: 28px;
    flex: 1 1 auto;
    container: params / inline-size;
  }
  /* Two cards of the same width share the panel, 24 px apart, level at the
     top and each as high as its rows; the hairlines between rows are the
     card's own. Narrow: one under the other. */
  .param-cards {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 24px;
    align-items: start;
  }
  @container params (max-width: 560px) {
    .param-cards {
      grid-template-columns: minmax(0, 1fr);
    }
  }
  /* The reset is a sign: the two arrows, in a square of the buttons' ground.
     It stands in the 26 px head and is taller than it; the negative margin
     keeps the head as high as every other section's. */
  .signbutton {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex: none;
    width: 34px;
    height: 34px;
    margin: -4px 0;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    color: var(--text);
    cursor: pointer;
  }
  .signbutton:hover {
    background: var(--glass-hover);
  }
  :global(html[data-phone]) .signbutton {
    width: 44px;
    height: 44px;
    margin: -9px 0;
  }
  /* Offered but not usable here. Dimmed as a whole rather than hidden: the
     panel then keeps the same rows for every model, and the row itself says
     what this backend cannot do. Its title carries the sentence. */
  .zeile.gesperrt { opacity: 0.45; cursor: not-allowed; }
  .zeile.gesperrt input { pointer-events: none; }

  /* The track runs over the whole row: the part up to the grip in the text
     colour, the rest in the strong line colour, so the empty part shows as
     far as it goes; the room above and below it is the grip's. */
  .regelspur {
    -webkit-appearance: none;
    appearance: none;
    flex: none;
    height: 4px;
    margin: 9px 0;
    border-radius: 9px;
    background: linear-gradient(to right, var(--text) var(--anteil), var(--linie-stark) var(--anteil));
    outline: none;
  }
  .regelspur::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: var(--text);
    border: none;
    cursor: pointer;
    transition: transform 0.12s ease;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.45);
  }
  .regelspur:active::-webkit-slider-thumb {
    transform: scale(1.18);
  }
  .regelspur::-moz-range-thumb {
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: var(--text);
    border: none;
    cursor: pointer;
  }
  /* As wide as what stands in it, the number in its middle, like the
     number fields of the other slider rows. */
  .zahl {
    flex: none;
    field-sizing: content;
    min-width: 5ch;
    height: 32px;
    box-sizing: content-box;
    border: none;
    border-radius: 9px;
    background: var(--bg-hoch);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    color: var(--text);
    font: 400 13px/18px var(--schrift);
    font-variant-numeric: tabular-nums;
    text-align: center;
    padding: 0 12px;
    outline: none;
  }
  .zahl:focus { background: color-mix(in srgb, var(--text) 5%, var(--bg-hoch)); }
  /* Nothing is actually sent for this one — the server decides. Dimming the
     number says so without a second label. */
  .zahl-unversendet { color: var(--text-still); }
</style>
