---
description: Examines a plan through focused questions until its decisions are settled.
auto: true
---

Question the user relentlessly about this plan or design until the two of
you share one understanding of it. Walk every branch of the decision tree
and resolve dependencies between decisions one at a time — a choice made
early often decides three questions further down, so take them in the order
they depend on each other.

Ask one question at a time, never a list of questions.

**Every question with choices MUST go through the `ask_user` tool** — never
as prose in your answer. Prose asking is not asking: it leaves the user
typing out what a click should have settled, and it does not stop the run
to wait for them. One question per call, at most two options, the one you
would recommend first and marked as recommended in its label. The reasoning
behind each option goes into that option's description, so the decision can
be made without asking back.

Ask in plain text only when a question cannot meaningfully be expressed
as choices, such as a request for a number, name, or free-form
sentence.

If the project's files can answer a question, look it up yourself. Ask the
user only about decisions that require their input.

Stop when every decision has been addressed and no unresolved questions
remain. Briefly summarize the decisions and their reasons.
