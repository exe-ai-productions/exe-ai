---
description: Sets up anything that should happen at a later time — a one-off reminder ("remind me in 10 minutes", "Friday at nine"), a job that repeats on a schedule, a script on a timer, or a watch that only reports when something happens
auto: true
---

Use the `cronjob` tool for anything that should happen at a later time: a
reminder that fires once, a job that repeats until removed, a script on a
timer, or a watch that reports only when something happens.

Ask for whatever is missing before calling: when it should fire, and what
should happen when it does. Offer to name a specific agent to run it; if the
user has no preference, leave `agent` out — it then goes to the shipped
reminder agent, which has no tools and no folders.

`time` takes one of three forms. Pick the one that matches what was asked
for, and say back which one you used:

| What was asked for | `time` |
|---|---|
| every day at 08:00 | `08:00` — a daily time, 24-hour `HH:MM` |
| every fifteen minutes | `*/15 * * * *` — a five-field cron expression |
| every hour | `0 * * * *` |
| weekdays at 09:00 | `0 9 * * 1-5` |
| the first of every month, 03:00 | `0 3 1 * *` |
| once, next Friday at 09:00 | that Friday's date, `YYYY-MM-DDT09:00` — one fixed instant |
| once, in ten minutes | the current time plus ten minutes, as an instant |

A cron expression is `minute hour day-of-month month day-of-week`, five
fields, and must not come due more often than once a minute.

For a time counted from now ("in ten minutes", "in two hours"), read the
current time with `get_current_time` first and add to it. Never guess the
time or the date.

The separate `date` field belongs only next to a daily `HH:MM` time. A cron
expression and an instant already say which day they mean — for a one-off on
a named day, prefer the instant form.

## Waiting for something: give it a `goal`

Ask yourself which of the two this is:

* **"Report every time"** — a daily summary, a nightly backup. No `goal`.
* **"Tell me when X happens"** — the mail arrives, the build goes green,
  the price drops. That is a `goal`, and it belongs in the `goal` field.

With a `goal` set, a run that does not reach it says nothing at all: no
sound, no notification. Fourteen quiet passes, and on the fifteenth "it is
here". Without one, a schedule checked every fifteen minutes announces
itself ninety-six times a day, and the one message that mattered drowns in
the other ninety-five.

**A good goal names its own evidence.** Not what you hope for — what would
prove it:

| loose | firm |
|---|---|
| the mail from Smith is there | an unread mail from Smith in the inbox — name the sender and the subject |
| the build is green | the latest run on `main` reports success — name the commit and the duration |
| disk space is fine again | free space on `/` above 20 GB — name the figure |

Add `stop_when_reached: true` when there is nothing left to watch once it
happens ("tell me when the mail arrives"). Leave it off for something that
should keep going and report on the days it finds something.

## Work that is already a script: use `script`

If what should happen is a script that already exists — a backup, a sync, a
cleanup — schedule the script itself instead of an agent: pass `script` with
its file name in place of `task` and `agent`.

Such an entry starts **no model at all**. That is the whole point: loading a
language model in order to say "run the backup" costs minutes of loading and
adds nothing. The script's exit code is the answer — `0` is a good run,
anything else a failed one that counts towards `max_failures`.

Three things to know before you offer it:

* The script must already lie in the **scripts folder** and be executable.
  Its path is shown under the schedule list in the settings window; the user
  opens that folder and edits the file in their own editor. Pass a plain
  file name — no path, no `..`.
* `max_seconds` raises the time limit for a long one (a backup). Left out,
  the standard command limit applies, and a script still running past it is
  stopped and the run counts as failed.
* A script entry takes **no `goal` and no `agent`**, and it can only be set
  up **from a chat** — never from inside an agent's own run. That refusal is
  deliberate and there is no way around it: a script runs with the user's
  full rights and nobody is asked before it starts, so a person has to have
  seen which file it is.

## Only a reminder: use `reminder`

When the person only wants to be reminded — "remind me to hand in the tax
return on Friday at nine" — nothing has to be done at that moment except to
tell them. Pass `reminder: true`, put the words the notification should show
in `task`, and set `time` (with `once` and `date` for a single day, as
usual).

Such an entry starts **no model and no script**: when it comes due, the
system plays its sound and shows the text, once. So it takes no `agent`, no
`script`, no `goal`, no `stop_when_reached` and no `max_seconds`, and it stays
a reminder — an `update` can change its text and its time, never turn it
into a run.

## Calling it

To create one, call the tool with `action: "create"`, `time`, `task`, and
optionally `agent`, `goal` and `stop_when_reached` — or with `time` and
`script` (plus `max_seconds`) for a script entry, or with `time`, `task` and
`reminder: true` for a reminder. To show existing ones,
`action: "list"`. To remove, pause, resume, or change one, use
`action: "remove"` / `"pause"` / `"resume"` / `"update"` together with its
`id`. On `update`, an empty `goal` removes the goal again.

Never invent an `id`. The only source for one is the tool's own output: the
line `create` returns, or an entry from `action: "list"`. If you do not have
it in front of you, call `action: "list"` first — do not guess or reuse one
from memory of an earlier turn.

Confirm back in one line what was scheduled, for what time, and which agent
or script runs it — and, where there is one, that it will report only once
the goal is met.
