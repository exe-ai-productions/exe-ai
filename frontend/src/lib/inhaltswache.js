/*
  One content watcher per element, however many want telling.

  Two `use:` actions can sit on the same node and both need to hear the same
  thing. The terminal's output box wears `rollfade` (the fade mask has to
  follow the content, not just the box) and `folgtUnten` (a growing box keeps
  its own tail in view) at once — and each used to open a MutationObserver of
  its own. That is the browser walking the same subtree twice on every
  arriving chunk, on the busiest streaming node in the program, to answer one
  and the same question: did the content change?

  So the node keeps ONE observer and a list of who asked. The last one to
  leave takes it down again, and the node itself is held weakly — an element
  that goes away takes its entry with it.

  The watched options are the union of what any caller could want, not a
  per-caller setting: a callback that fires a little more often costs one
  extra call, while options per caller would be an observer per caller all
  over again.
*/

const wachen = new WeakMap()

/**
 * Calls `rueckruf` whenever the node's content changes. Returns the
 * unsubscribe — call it in the action's `destroy`.
 */
export function inhaltBeobachten(knoten, rueckruf) {
  let wache = wachen.get(knoten)
  if (!wache) {
    const hoerer = new Set()
    const beobachter = new MutationObserver(() => {
      // Iterated directly rather than over a copy: this runs on every
      // mutation batch of a streaming node, and a Set tolerates being
      // changed while it is walked — an entry removed before its turn is
      // simply skipped.
      for (const h of hoerer) h()
    })
    beobachter.observe(knoten, { childList: true, characterData: true, subtree: true })
    wache = { hoerer, beobachter }
    wachen.set(knoten, wache)
  }
  // A Set deduplicates by identity: subscribing the SAME function twice
  // for one node collapses into one entry, and the first unsubscribe would
  // silently deafen the other party. Every caller must pass its own fresh
  // closure per subscription — today's callers (rollfade, folgtunten)
  // all do.
  wache.hoerer.add(rueckruf)

  let beendet = false
  return () => {
    // Guarded: an action whose `destroy` runs twice must not take the
    // observer down while somebody else is still listening.
    if (beendet) return
    beendet = true
    wache.hoerer.delete(rueckruf)
    if (wache.hoerer.size) return
    wache.beobachter.disconnect()
    wachen.delete(knoten)
  }
}
