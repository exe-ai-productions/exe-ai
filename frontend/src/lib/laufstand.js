/*
  One run, two displays, one distinction between them.

  A run whose work was handed on to a continuation ends `unterbrochen` with
  a reason of its own — the context filled up, or the provider stopped
  answering, and the rest of the work went onto the clock as a new cron
  entry that is running or about to (app/api/v1/auftraege.py). Since e959e99
  that is the state such a run ends in, and there is nothing to walk over
  to: the work is still going.

  `unterbrochen` has exactly one other writer, the sweep at service start
  (`beim_start_aufraeumen`, app/db/repositories/auftraege.py), and its
  reason is `dienst_neustart`. Nothing was handed anywhere there — the run
  was simply cut off — so that one is a real ending.

  Two places read this and used to carry a copy each: the reports list
  (frontend/src/teile/ModulAgenten.svelte) and the dot on the rail
  (frontend/src/lib/agentenampel.svelte.js). They already disagreed about
  one run once — the list drew it grey while the dot painted it red, one
  glance apart — and cefa779 settled that by writing the same expression
  down a second time. Two copies with a guard each is how that comes back:
  widen one side to a set of reasons and both guards stay green, because
  each of them was measuring its own copy. So the expression stands here,
  once, and both sides import it.

  They do not USE it the same way, and that is on purpose. The list applies
  it conditionally: a handed-on link steps aside only when something newer
  of the same work exists, so the last link of a chain still stands there
  with its reason. The dot skips EVERY handed-on run, because none of them
  is an ending it could be reporting. What the two share is the
  distinction, not what they do with it.

  Import-free, like ringfarbe.js: a .svelte component, a .svelte.js module
  and a test in node all pull it in, and it depends on nothing but two
  fields of a job row.

  Known and deliberately left alone: a `dienst_neustart` run that had a
  saved status is resumed right after the sweep
  (`nach_neustart_fortsetzen`, app/zwischenstand.py), which makes it handed
  on as well — and this rule still counts it as an ending. Telling those
  two apart needs a field the jobs route does not hand out (`zwischenstand`
  is not on `AuftragAntwort`, app/api/v1/schemas.py), so it is reported
  rather than guessed at here.
*/

export function weitergereicht(auftrag) {
  return auftrag.state === 'unterbrochen' && auftrag.end_reason !== 'dienst_neustart'
}
