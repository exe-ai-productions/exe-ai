---
description: Schedules future actions: one-off reminders ("remind me in 10 minutes", "Friday at nine"), recurring jobs, scheduled scripts, or monitoring that reports only when the specified event occurs.
auto: true
---

Use the `cronjob` tool for future actions: a one-off reminder, a
recurring job that continues until removed, a scheduled script, or
monitoring that reports only when a specified event occurs.

Ask for whatever is missing before calling: when it should fire, and what
should happen when it does. Offer to name a specific agent to run it; if the
user has no preference, leave `agent` out.

The `time` field accepts three formats. Choose the format that matches
the request and tell the user which one you used:

| What was asked for | `time` |
|---|---|
| every day at 08:00 | `08:00` — a daily time, 24-hour `HH:MM` |
| every fifteen minutes | `*/15 * * * *` — a five-field cron expression |
| every hour | `0 * * * *` |
| weekdays at 09:00 | `0 9 * * 1-5` |
| the first of every month, 03:00 | `0 3 1 * *` |
| once, next Friday at 09:00 | that Friday's date, `YYYY-MM-DDT09:00` — one fixed instant |
| once, in ten minutes | the current time plus ten minutes, as an instant |

A cron expression contains five fields: `minute hour day-of-month month
day-of-week`. It must not schedule runs more than once per minute.

For a relative time ("in ten minutes", "in two hours"), first read the
current time with `get_current_time`, then add the requested interval.
Never guess the time or date.

Use the separate `date` field only with a daily `HH:MM` time. Cron
expressions and timestamps already specify the day. Prefer a timestamp for a
one-off action on a named day.

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

Define a goal through the evidence that would confirm it, rather than the
outcome you merely hope for:

| loose | firm |
|---|---|
| the mail from Smith is there | an unread mail from Smith in the inbox — name the sender and the subject |
| the build is green | the latest run on `main` reports success — name the commit and the duration |
| disk space is fine again | free space on `/` above 20 GB — name the figure |

Set `stop_when_reached: true` when no further monitoring is needed after
the event ("tell me when the mail arrives"). Leave it disabled for ongoing
checks that should report whenever they find something relevant.

## Work that is already a script: use `script`

If the requested work already exists as a `script`, such as a backup,
synchronization, or cleanup, schedule that script directly. Pass its
filename as script instead of specifying `task` and `agent`.

A script entry starts no model, avoiding the overhead of loading one solely
to request script execution. The script's exit code determines the result:
`0` indicates success; any other value indicates failure and counts toward
`max_failures`.

Check these three requirements before suggesting a script entry:

* The script must already exist in the **scripts folder** and be executable.
  The folder's path appears below the schedule list in settings. The user
  opens that folder and edits the file in their own editor. Pass only the
  filename, without a path or `..`.
* Use `max_seconds` to increase the runtime limit for lengthy scripts, such
  as backups. If omitted, the standard command limit applies. A script
  exceeding the limit is stopped and its run is marked as failed.
* A script entry takes **no `goal` and no `agent`**, and it can only be set
  up **from a chat** — never from inside an agent's own run. That refusal is
  deliberate and there is no way around it: a script runs with the user's
  full rights and nobody is asked before it starts, so a person has to have
  seen which file it is.

## Only a reminder: use `reminder`

For a reminder such as "remind me to hand in the tax return on Friday at
nine", no work is required beyond notifying the user. Set `reminder: true`,
put the notification text in `task`, and specify `time`, with `once` and
`date` for a single day as usual.

A reminder starts neither a model nor a `script`. When due, it plays a sound
and displays its text once. Omit `agent`, script, `goal`, `stop_when_reached`,
and `max_seconds`. Updates can change its text and time, but cannot convert it
into an executable task.

## Calling it

To create one, call the tool with `action: "create"`, `time`, `task`, and
optionally `agent`, `goal` and `stop_when_reached` — or with `time` and
`script` (plus `max_seconds`) for a script entry, or with `time`, `task` and
`reminder: true` for a reminder. To show existing ones,
`action: "list"`. To remove, pause, resume, or change one, use
`action: "remove"` / `"pause"` / `"resume"` / `"update"` together with its
`id`. On `update`, an empty `goal` removes the goal again.

Never invent an `id`. Use only an identifier returned by `create` or
`action: "list"`. If no verified identifier is available in the current
context, call action: "list" first; do not guess or rely on an earlier turn.

Confirm in one line what was scheduled, when it will run, and which agent
or script will execute it. If a goal is set, explain that a notification
will be sent only when it is reached.
