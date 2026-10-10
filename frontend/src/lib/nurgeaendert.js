/*
  What of a form's values is an answer this window actually gave.

  Both server pages hold their own copies of the stored numbers, because a
  slider drags through a hundred intermediate values on its way to one, and a
  watcher writes the value the hand came to rest on. Until now that watcher
  sent every field it watched, on every change of any of them, and that is
  wrong twice over:

    * **Against the second window.** Sending a field this window did not
      change means sending the copy it read when the page opened. Window A
      sets the context to 131072; window B, whose form still shows 32768,
      nudges the layers — and B's write carries its stale context out over
      A's. The PATCH route (app/db/repositories/einstellungen.py
      `zusammenlegen`) merges key by key, so it can only protect the keys that
      were left out of the request. That the two windows are on the same
      NUMBER rather than on two different keys is what the merge alone does
      not fix.

    * **Against the defaults.** A field the store has no answer for is filled
      in from what the server sends as `vorgaben`, so the form has something
      to show. Writing that back turns a default into a choice: the value is
      not lost, but a later change of the shipped default never reaches
      anybody who once opened the page. The port already had a brake against
      exactly this; the window and the layers did not.

  So the two rules here, and they are one sentence each:

    a pre-filled default that was never moved is not an answer
    a value equal to what this window last stored is not a change

  What is left is what the hand did, and only that goes out.
*/

/* Deep equality, because one of the fields is a set of levers rather than a
   number. Key order is not part of the answer: what comes back from the
   service is JSON, and the order it arrives in is nobody's decision.

   Asked one way round on purpose: does the form's value say anything the
   reference does not already say? A form holds only the levers it has a
   control for — the engine settings it shows carry no `flash_attention`,
   because no row on either page sets one — so a key the form does not have
   is a key the form cannot have changed. Comparing the two key sets as
   equals would call every such value "different" and write it back on the
   first poll, which is exactly the freezing this file exists to stop. */
function deckt(wert, bezug) {
  if (wert === bezug) return true
  if (wert === null || bezug === null) return false
  if (typeof wert !== 'object' || typeof bezug !== 'object') return false
  if (Array.isArray(wert) !== Array.isArray(bezug)) return false
  if (Array.isArray(wert)) {
    return wert.length === bezug.length && wert.every((x, i) => deckt(x, bezug[i]))
  }
  return Object.keys(wert).every((name) => name in bezug && deckt(wert[name], bezug[name]))
}

/**
 * The subset of `felder` worth writing.
 *
 * @param felder   what the form holds right now
 * @param stand    what this window knows is stored — `null`/`undefined` per
 *                 name means "nobody has chosen this yet"
 * @param vorgaben what the form filled a never-chosen field in with
 */
export function nurGeaendert(felder, stand, vorgaben = {}) {
  const nachtrag = {}
  for (const [name, wert] of Object.entries(felder)) {
    const gespeichert = stand?.[name]
    /* Never chosen and still showing what the form pre-filled: the value on
       screen is the fallback answering for a missing choice, not a choice. */
    if (
      (gespeichert === null || gespeichert === undefined) &&
      deckt(wert, vorgaben?.[name] ?? null)
    ) {
      continue
    }
    /* Unchanged since this window last stored it. Skipped not to save a
       request but to keep this window out of a value it has nothing to say
       about — see the header. */
    if (deckt(wert, gespeichert)) continue
    nachtrag[name] = wert
  }
  return nachtrag
}
