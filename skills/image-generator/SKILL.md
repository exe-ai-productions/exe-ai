---
description: Generates an image from the rest of the user's message without asking follow-up questions.
auto: true
---

Treat the rest of this message as the image brief. Use `draw_image` to
generate it on this computer. Do not use alternative programs or commands.

Do not ask for a style, format, or confirmation. A brief request can still
be complete. Resolve unspecified details yourself and state your choices in
one line so the user can request adjustments afterward.

Filling the gaps:

- If no style is specified, use a clean, realistic photographic style. This
  provides a straightforward starting point for later adjustments.
- Include text in the image only when requested. Keep it short and explain
  that the model may render it incorrectly.

Write the `prompt` in English, whatever language the brief came in, and name
what the picture shows: subject, setting, light, mood and look. Vague
adjectives ("beautiful", "amazing") do nothing — what the picture shows
does. How to phrase it depends on the image model in use, and the tool's own
description says which way that model reads: short keyword phrases with the
most important first, whole flowing sentences, or a full description in
plain prose. Follow the description. Things that must stay out go into
`negative_prompt` — unless the description says it has no effect, as it does
at CFG 1; then leave it out.

In a chat, the image appears automatically in your response. In a job,
deliver it with `deliver_file` using the path returned by the image tool. In
either case, do not describe its contents afterward, because you have not
seen it.
