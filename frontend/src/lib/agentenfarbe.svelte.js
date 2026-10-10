/*
  One colour per agent, and the arithmetic that keeps it readable.

  THE CASE. Eight report rows under one another, all from `recherche`, all in
  the same blue — nothing on the screen says which line belongs to which run.
  The name is the only thing that could say it, so the name carries a colour.

  THREE RULES, and each of them is why a line here exists.

  1. THE FOUR STATE COLOURS ARE OUT. Green, yellow, blue and red mean a state
     everywhere in this program; an agent in red would read as a failed run.
     The picker moves a pick out of those four hues, and out of the two the
     program already spends on capabilities (`--violett` for vision,
     `--oliv` for tool use) — the free part of the wheel IS short.

  2. IT HAS TO STAY READABLE. A written name needs 4.5:1, the same figure the
     `--*-text` forms of the palette were cut to. One stored value has to
     hold in five appearances, from a cream ground to a violet night — so
     nothing is stored per appearance. The colour is LIFTED at the moment it
     is drawn: hue and saturation stay, lightness walks away from the ground
     until the ratio is reached. A colour that cannot carry is raised, never
     handed through.

  3. NO CHOICE MEANS NO CHANGE. An agent without a colour gets an empty
     answer here, and every caller falls back to what it drew before.

  The ground is measured from `--bg`, once per appearance rather than per
  name: the raised surfaces (`--bg-erhoben`, `--bg-hoch`) sit within a few
  percent of it, and a ratio computed against the page is the honest one for
  a name that may stand on any of the three.
*/

import { api } from './api.js'

/* The hues the program has already spent, each with the width it needs to
   stay unmistakable. Measured off the palette in both appearances — a state
   colour shifts a little between skins, and the band has to cover both — and
   then given twelve degrees to either side, which is about where two hues
   stop reading as the same colour at a glance.

   This is what keeps the picker free WITHOUT letting it lie: the hand may
   reach for any colour the system's panel offers, and one that lands in a
   spent stretch is turned to the nearest free hue on its way in. An agent in
   red would read as a failed run.

   Written as [from, to] in degrees; a band that crosses 0 is written across
   it and read that way. */
const RAND = 12
const BELEGT = [
  ['rot', 349, 5],      // failed, dangerous, deletes
  ['gelb', 45, 46],     // waiting, and careful
  ['oliv', 64, 66],     // tool use
  ['gruen', 127, 145],  // ready, done, connected
  ['blau', 209, 217],   // running, switched on
  ['violett', 258, 260],// vision
]

/* The spent bands, widened by the guard. Degrees, and a band may cross 0. */
const BELEGTE_TOENE = BELEGT.map(([name, von, bis]) => ({
  name,
  von: (von - RAND + 360) % 360,
  bis: (bis + RAND) % 360,
}))

function imBand(ton, { von, bis }) {
  return von <= bis ? ton >= von && ton <= bis : ton >= von || ton <= bis
}

function tonErlaubt(ton) {
  const t = ((ton % 360) + 360) % 360
  return !BELEGTE_TOENE.some((band) => imBand(t, band))
}

/**
 * A picked colour with its hue moved out of any stretch the program has
 * already spent, and everything else about it left alone.
 *
 * This is the rule the system's own picker cannot keep — it will happily
 * hand back a red — so it is kept here, on the way in. The hue walks
 * outwards to the nearest free degree; saturation and lightness are the
 * hand's and are not touched. What comes back is what gets stored, and the
 * preview beside the picker shows it, so the correction is never silent.
 */
export function tonGewahrt(farbe) {
  const teile = zerlegen(farbe)
  if (!teile) return ''
  const [h, s, l] = zuHsl(teile)
  const ton = h * 360
  if (tonErlaubt(ton)) return alsHex(teile)
  for (let weg = 1; weg <= 180; weg += 1) {
    for (const versuch of [ton + weg, ton - weg]) {
      if (tonErlaubt(versuch)) {
        return alsHex(ausHsl([(((versuch % 360) + 360) % 360) / 360, s, l]))
      }
    }
  }
  return alsHex(teile)
}

/* Which agent wears which colour. Filled from the agent list — by whoever
   already has one in hand, so the same answer is not fetched twice. */
const farben = $state({ nach_name: {} })

/* The page's own ground, re-measured whenever the appearance changes. Held
   as state so a lifted colour recomputes with the skin instead of standing
   in yesterday's arithmetic. */
const grund = $state({ wert: '' })

let beobachtet = false
let geladen = false

function grundMessen() {
  if (typeof document === 'undefined') return
  grund.wert = getComputedStyle(document.documentElement)
    .getPropertyValue('--bg')
    .trim()
}

/* One watcher for the ground these colours are read against: the attribute
   a skin is switched with, the one the own gradient turns light or dark
   with, and the device report the "auto" skin follows. */
function grundBeobachten() {
  if (beobachtet || typeof document === 'undefined') return
  beobachtet = true
  grundMessen()
  new MutationObserver(grundMessen).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-modus', 'data-eigen'],
  })
  window.matchMedia?.('(prefers-color-scheme: dark)')?.addEventListener?.(
    'change',
    grundMessen,
  )
}

/** The colours out of an agent list somebody already fetched. */
export function farbenSetzen(agenten) {
  geladen = true
  farben.nach_name = Object.fromEntries(
    (agenten || []).map((agent) => [agent.name, agent.color || '']),
  )
}

/** For the places that show an agent's name without holding the list —
 *  the schedules panel, the notices. Asks once; a failure leaves what is
 *  already known standing. */
export async function farbenLaden() {
  grundBeobachten()
  if (geladen) return
  geladen = true
  try {
    farbenSetzen(await api.agenten())
  } catch {
    geladen = false
  }
}

/** The colour this agent picked, or '' — which means "draw it as before". */
export function farbeVon(name) {
  return farben.nach_name[name] || ''
}

/* --- the arithmetic --------------------------------------------------- */

function zerlegen(farbe) {
  const text = String(farbe || '').trim()
  const kurz = /^#([0-9a-f])([0-9a-f])([0-9a-f])$/i.exec(text)
  if (kurz) return kurz.slice(1).map((c) => parseInt(c + c, 16))
  const lang = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(text)
  if (lang) return lang.slice(1).map((c) => parseInt(c, 16))
  const rgb = /^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)/i.exec(text)
  if (rgb) return rgb.slice(1).map((c) => Math.round(Number(c)))
  return null
}

/* WCAG relative luminance — the same measure the palette's text forms were
   cut against, so both halves of the house use one yardstick. */
function leuchtkraft([r, g, b]) {
  const kanal = (roh) => {
    const c = roh / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * kanal(r) + 0.7152 * kanal(g) + 0.0722 * kanal(b)
}

function abstand(a, b) {
  const hell = Math.max(leuchtkraft(a), leuchtkraft(b))
  const dunkel = Math.min(leuchtkraft(a), leuchtkraft(b))
  return (hell + 0.05) / (dunkel + 0.05)
}

function zuHsl([r, g, b]) {
  const rr = r / 255
  const gg = g / 255
  const bb = b / 255
  const hoch = Math.max(rr, gg, bb)
  const tief = Math.min(rr, gg, bb)
  const l = (hoch + tief) / 2
  if (hoch === tief) return [0, 0, l]
  const spanne = hoch - tief
  const s = l > 0.5 ? spanne / (2 - hoch - tief) : spanne / (hoch + tief)
  let h
  if (hoch === rr) h = (gg - bb) / spanne + (gg < bb ? 6 : 0)
  else if (hoch === gg) h = (bb - rr) / spanne + 2
  else h = (rr - gg) / spanne + 4
  return [h / 6, s, l]
}

function ausHsl([h, s, l]) {
  if (s === 0) {
    const wert = Math.round(l * 255)
    return [wert, wert, wert]
  }
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s
  const p = 2 * l - q
  const kanal = (t) => {
    let v = t
    if (v < 0) v += 1
    if (v > 1) v -= 1
    if (v < 1 / 6) return p + (q - p) * 6 * v
    if (v < 1 / 2) return q
    if (v < 2 / 3) return p + (q - p) * (2 / 3 - v) * 6
    return p
  }
  return [kanal(h + 1 / 3), kanal(h), kanal(h - 1 / 3)].map((c) =>
    Math.round(c * 255),
  )
}

function alsHex([r, g, b]) {
  return '#' + [r, g, b].map((c) => c.toString(16).padStart(2, '0')).join('')
}

/** One colour turned `grad` degrees around the wheel: only the hue moves,
 *  saturation and lightness stay (the frame gradient's own rule). */
export function farbtonDrehen(farbe, grad) {
  if (!grad) return farbe
  const teile = zerlegen(farbe)
  if (!teile) return farbe
  const [h, s, l] = zuHsl(teile)
  return alsHex(ausHsl([(((h + grad / 360) % 1) + 1) % 1, s, l]))
}

/* What a written name needs, and what the palette's own text forms were cut
   to. A dot would do at 3:1; this is not a dot. */
const NOETIG = 4.5

/**
 * The colour as it may actually be drawn on the current ground: unchanged
 * when it already carries, lifted away from the ground when it does not.
 * Empty in, empty out — that is how a caller falls back to what it drew
 * before.
 */
export function lesbar(farbe) {
  if (!farbe) return ''
  grundBeobachten()
  const gewaehlt = zerlegen(farbe)
  const boden = zerlegen(grund.wert)
  if (!gewaehlt) return ''
  if (!boden) return farbe
  if (abstand(gewaehlt, boden) >= NOETIG) return farbe

  /* Away from the ground, never towards it: on a dark page the colour goes
     up, on a light one down. Hue and saturation are what tell two agents
     apart, so only lightness moves. */
  const [h, s, l] = zuHsl(gewaehlt)
  const hinauf = leuchtkraft(boden) < 0.5
  let hell = l
  for (let schritt = 0; schritt < 50; schritt += 1) {
    hell = hinauf ? hell + 0.02 : hell - 0.02
    if (hell <= 0 || hell >= 1) break
    const versuch = ausHsl([h, s, hell])
    if (abstand(versuch, boden) >= NOETIG) return alsHex(versuch)
  }
  /* The end of the road: black or white in that direction. A colour that
     needs this is one nobody should pick, and the picker does not offer
     one — but a hand-written file may. */
  return hinauf ? '#ffffff' : '#000000'
}
