/*
  The MCP tool switch — three states a person clicks through, two lists the
  server actually reads (`allowed_tools`, `needs_confirmation`).

  Import-free so a test can run it exactly as it ships, without dragging the
  Svelte build behind it — the same convention frontend/src/lib/ringfarbe.js
  already uses for the same reason.
*/

const RUNDE = { an: 'fragt', fragt: 'aus', aus: 'an' }

// The catalogue key of the word that stands beside a tool in each state: the
// same words the terminal client uses — active, asks, inactive.
const STATE_WORDS = { an: 'status.aktiv', fragt: 'werkzeuge.fragt', aus: 'status.inaktiv' }

/** The key of the word beside a tool in that state; a state this module does
    not know reads as "on", the way `naechsterZustand` takes it. */
export function stateWordKey(zustand) {
  return STATE_WORDS[zustand] ?? STATE_WORDS.an
}

/** Clicking a tool cycles it: on → asks first → off → on. */
export function naechsterZustand(zustand) {
  return RUNDE[zustand] ?? 'an'
}

/** The tool's starting state, read back from a server entry. `allowed_tools:
    null` means "offer everything" — every tool starts on.

    Exclusion is checked first, on purpose: the registry drops a tool that
    fell out of `allowed_tools` before it ever looks at `needs_confirmation`
    (app/tools/registry.py) — a name that somehow stands in both a name
    could reach by editing the raw file by hand is truly off, not
    "asks first", and the switch has to agree with what actually runs. */
export function zustandAusEintrag(name, eintrag) {
  const angeboten = eintrag.allowed_tools == null || eintrag.allowed_tools.includes(name)
  if (!angeboten) return 'aus'
  if ((eintrag.needs_confirmation || []).includes(name)) return 'fragt'
  return 'an'
}

/** The reverse: what `PUT /tools/servers/{name}` should be told once the
    switches stand where the user left them. A tool asking first has to
    land in BOTH lists — offered, but not run without a yes — or the
    server would either hide it entirely or run it silently. */
export function listenAusZustaenden(werkzeuge) {
  const allowed_tools = []
  const needs_confirmation = []
  for (const werkzeug of werkzeuge) {
    if (werkzeug.zustand === 'aus') continue
    allowed_tools.push(werkzeug.name)
    if (werkzeug.zustand === 'fragt') needs_confirmation.push(werkzeug.name)
  }
  return { allowed_tools, needs_confirmation }
}

/** A typed server name becomes the file's JSON key and, from it, the name
    of the .env variable that holds its key — the same alphabet and the
    same `_API_KEY` suffix app/api/v1/anbieter.py already uses for a custom
    cloud provider, so the two forms in the program agree. */
export function serverKennung(name) {
  return name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 30)
}

/** What a known tile's sheet writes before it connects: its address, its
    preselected tools, and whether it is on. A key typed in and sent with
    "connect" switches the server on — that is what the button names. Left
    as it was, a switched-off server would never start, and the sheet would
    report it unreachable though the key was taken.

    A tile without an address is a server that starts a program here: it
    writes no kind and no address, so the kind it has stays the kind it has
    — written as `http` it would be an address-less server the registry
    refuses. One that names its program (`command`) has no entry anywhere
    until this write, so — with no entry on file — it writes the program as
    well, and the address the person typed, which the program reads from the
    variable the tile names (`address_env`), into the entry's own
    environment. An entry already on file keeps its program and its
    environment. */
export function grundfelder(quelle, eintrag, { mitSchluessel = false, adresse = '' } = {}) {
  const felder = { enabled: mitSchluessel ? true : (eintrag?.enabled ?? true) }
  if (quelle.url) {
    felder.type = 'http'
    felder.url = quelle.url
  }
  if (quelle.command && !eintrag) {
    felder.type = 'stdio'
    felder.command = quelle.command
    felder.args = quelle.args ?? []
    if (quelle.address_env && adresse) felder.env = { [quelle.address_env]: adresse }
  }
  if (quelle.vorauswahl) felder.allowed_tools = quelle.vorauswahl
  return felder
}

/** What a typed key writes into the entry: the header it goes in, holding
    the variable of the .env — never the key. `Authorization` carries it as
    `Bearer …`, any other header as it is (a server that wants
    `X-Goog-Api-Key` rejects a Bearer). The two other ways the entry may have
    had are cleared: the old `api_key_env` would send a second key, and
    `auth: oauth` would put a stored sign-in before the header. Headers the
    entry has that carry no key of their own (`existing`, name → value) stay;
    those that carried a key are replaced by this one. */
export function headerFields(variable, headerName, existing = {}) {
  const name = String(headerName ?? '').trim() || 'Authorization'
  const value = name.toLowerCase() === 'authorization'
    ? `Bearer \${${variable}}`
    : `\${${variable}}`
  const headers = {}
  for (const [other, otherValue] of Object.entries(existing)) {
    if (!String(otherValue).includes('${')) headers[other] = otherValue
  }
  for (const other of Object.keys(headers)) {
    if (other.toLowerCase() === name.toLowerCase()) delete headers[other]
  }
  headers[name] = value
  return { headers, api_key_env: null, auth: null }
}

/** The variable a header of an entry reads for its key (`${NAME}`), or
    `undefined` where none does. */
export function keyVariableOf(headers) {
  for (const value of Object.values(headers ?? {})) {
    const name = /\$\{([^}]+)\}/.exec(String(value))?.[1]
    if (name) return name
  }
  return undefined
}

/** The headers of an entry without the ones that carry a key — what stays
    when the entry signs in through the browser instead — or `null` where
    nothing is left (which takes the field out of the entry). */
export function headersWithoutKey(headers) {
  const kept = Object.fromEntries(
    Object.entries(headers ?? {}).filter(([, value]) => !String(value).includes('${')),
  )
  return Object.keys(kept).length ? kept : null
}

/** The server refuses a variable name that starts with a digit, so a
    name typed as an address (`127-0-0-1`) gets a leading underscore. */
export function apiKeyUmgebungsname(kennung) {
  const name = `${kennung.toUpperCase().replace(/-/g, '_')}_API_KEY`
  return /^[0-9]/.test(name) ? `_${name}` : name
}

/** What the model calls a server's tool by: `mcp__<server>__<tool>`, a
    character outside letters, digits and the underscore becoming `_`. The
    same name app/tools/mcp_names.py makes — the switches and the lists of an
    agent are written by it. */
export function modelName(server, tool) {
  const clean = (part) => String(part).replace(/[^A-Za-z0-9_]/g, '_')
  return `mcp__${clean(server)}__${clean(tool)}`
}

/** The server's own word for a tool: `read_file` for `mcp__fs__read_file`
    of the server `fs`. A name that does not carry the server's prefix is
    returned as it is. The catalogue marks are looked up by this word. */
export function ownName(name, server) {
  const prefix = modelName(server ?? '', '')
  return server && typeof name === 'string' && name.startsWith(prefix)
    ? name.slice(prefix.length)
    : name
}

/** The seconds a field holds: a number above zero, else `null` — which
    removes the field from the entry, so the default holds again. */
export function timeLimitFromField(value) {
  const seconds = typeof value === 'number' ? value : Number(String(value ?? '').trim())
  return Number.isFinite(seconds) && seconds > 0 ? seconds : null
}
