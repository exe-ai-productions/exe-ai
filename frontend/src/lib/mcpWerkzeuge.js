/*
  The MCP tool switch — three states a person clicks through, two lists the
  server actually reads (`allowed_tools`, `needs_confirmation`).

  Import-free so a test can run it exactly as it ships, without dragging the
  Svelte build behind it — the same convention frontend/src/lib/ringfarbe.js
  already uses for the same reason.
*/

const RUNDE = { an: 'fragt', fragt: 'aus', aus: 'an' }

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
    report it unreachable though the key was taken. */
export function grundfelder(quelle, eintrag, { mitSchluessel = false } = {}) {
  const felder = {
    type: 'http',
    url: quelle.url,
    enabled: mitSchluessel ? true : (eintrag?.enabled ?? true),
  }
  if (quelle.vorauswahl) felder.allowed_tools = quelle.vorauswahl
  return felder
}

/** The server refuses a variable name that starts with a digit, so a
    name typed as an address (`127-0-0-1`) gets a leading underscore. */
export function apiKeyUmgebungsname(kennung) {
  const name = `${kennung.toUpperCase().replace(/-/g, '_')}_API_KEY`
  return /^[0-9]/.test(name) ? `_${name}` : name
}
