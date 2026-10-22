/*
  What the MCP server gallery says about a server, worked out in one place.

  The page of the MCP servers draws a card for each server and the server
  overview draws a row for each; both ask here for the same three things — the
  state, the name and the logo — so a card and its row cannot disagree.

  A card is `{ katalog, eintrag }`: the shipped server the card belongs to
  (null for a server of one's own) and the entry the file holds for it (null
  while it is not set up). The sign-in state of the servers is handed in
  (`status`, by server name) because it comes from its own answer of the
  service. Nothing in here is reactive and nothing reads a text catalogue
  itself: `t` is handed in where a word is made.
*/
import { LOGOS } from './logos.js'
import { SERVERKATALOG as KATALOG, gehoertZurKachel, serverTitel } from './serverkatalog.js'

/** The union of the shipped catalogue and everything in the file, one card each. */
export function cardsOf(entries) {
  return [
    ...KATALOG.map((k) => ({
      katalog: k,
      eintrag: entries.find((e) => gehoertZurKachel(k, e)) || null,
    })),
    ...entries
      .filter((e) => !KATALOG.some((k) => gehoertZurKachel(k, e)))
      .map((e) => ({ katalog: null, eintrag: e })),
  ]
}

/** The state of a card: `frei` (no entry), `schluessel_fehlt`, `aus`,
 *  `getrennt` (wants a sign-in and has none), `verbunden` or `wartet`. */
export function zustand(kachel, status) {
  const { katalog, eintrag } = kachel
  if (!eintrag) return 'frei'
  /* `schluessel_gesetzt` is null where the entry names no key — in
     `api_key_env` or as a ${NAME} in a header of its own. */
  if (eintrag.schluessel_gesetzt === false) return 'schluessel_fehlt'
  if (!eintrag.enabled) return 'aus'
  const oertlich = katalog && katalog.anmeldung === 'keine'
  /* The browser sign-in is a question for a server reached over the
     network. An entry that starts a program on this machine has nothing
     to sign in to, whatever it is called — it runs or it does not, and
     a name it shares with a shipped server must not turn it into one
     that waits for a sign-in. */
  /* A shipped server says so in the catalogue; a server of one's own, in its
     entry (`auth: 'oauth'`, written when the sheet connected it). */
  const wantsSignIn = katalog
    ? !oertlich && katalog.anmeldung !== 'schluessel'
    : eintrag.auth === 'oauth'
  const oauthKachel =
    wantsSignIn && eintrag.schluessel_gesetzt == null && eintrag.type === 'http'
  if (oauthKachel && !status[eintrag.name]?.verbunden) return 'getrennt'
  if (eintrag.laeuft) return 'verbunden'
  return 'wartet'
}

const isConnected = (stand) => ['verbunden', 'wartet'].includes(stand)

/** The cards with an entry, the connected and starting ones first; each half
 *  keeps the order of the list it was taken from. */
export function setUpCards(cards, status) {
  const onFile = cards.filter((k) => zustand(k, status) !== 'frei')
  return [
    ...onFile.filter((k) => isConnected(zustand(k, status))),
    ...onFile.filter((k) => !isConnected(zustand(k, status))),
  ]
}

/** The shipped servers without an entry. */
export const notSetUpCards = (cards, status) => cards.filter((k) => zustand(k, status) === 'frei')

/** The state alone, without the colon that announces names: the head of the
 *  small menu has no room for them, and a card with no name to give must
 *  not end in an empty colon. */
export function stateHead(stand, t) {
  return t(`verbindungen.stand_${stand}`).replace(/\s*:\s*$/, '')
}

/** What the state says on the card: for a missing key, the names of the
 *  missing variables stand behind it (never a value). */
export function stateText(k, stand, t) {
  const names = stand === 'schluessel_fehlt' ? k.eintrag?.missing_keys : null
  return names?.length
    ? `${t(`verbindungen.stand_${stand}`)} ${names.join(', ')}`
    : stateHead(stand, t)
}

/** The colour of a state's dot, and of its word where the word stands alone. */
export const punktFarbe = (stand) =>
  stand === 'verbunden' || stand === 'wartet' ? 'gruen'
  : stand === 'getrennt' || stand === 'schluessel_fehlt' ? 'rot'
  : 'still'

export const nameVon = (k) => k.katalog?.name || k.eintrag.name

/** What tells two cards apart: the name alone is not enough once a server of
 *  one's own carries the name of a shipped one. */
export const schluesselVon = (k) => `${k.katalog ? 'katalog' : 'eigen'}:${nameVon(k)}`

const katalogNamen = new Set(KATALOG.map((k) => k.name))
/* The shipped title and logo belong to the shipped server. A server of
   one's own under its name has its own name as the title and the house's
   plug as its sign, as every server of one's own has. */
const istKatalogName = (k) => k.katalog || !katalogNamen.has(nameVon(k))

export const titelVon = (k) => (istKatalogName(k) ? serverTitel(nameVon(k)) : nameVon(k))

/** The maker's logo, or nothing — then the house's plug stands in. Asked for
 *  the table's own entries only: a server may be called any word, also one
 *  every object answers to. */
export const logoVon = (k) =>
  istKatalogName(k) && Object.hasOwn(LOGOS, nameVon(k)) ? LOGOS[nameVon(k)] : null

/** The logo a server of one's own sent along (checked by the service, a data
 *  URL), or nothing. Never for a shipped server's card: that one wears its
 *  maker's vector. */
export const eigenLogoVon = (k) => (!k.katalog && k.eintrag?.logo) || null
