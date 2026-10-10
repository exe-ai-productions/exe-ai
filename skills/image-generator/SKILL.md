---
description: Turns the rest of the line into a picture, without asking back
auto: true
---

The rest of this message is a picture to make. Call the `draw_image` tool
with it — that is the machine on this computer that actually draws. Do not
try programs or commands; the tool is the whole way.

Do not ask what style, what format, or whether they are sure. A short brief
is not an incomplete one — fill the gaps yourself and say in one line what
you decided, so it can be corrected afterwards rather than negotiated first.

Filling the gaps:

- **No style named** — go for a clean, realistic photograph. It is the least
  surprising thing to get back and the easiest to steer away from.
- **Words in the picture** — only if they were asked for. Image models spell
  badly, so keep any text short and say that it may come out wrong.

Write the `prompt` in English, whatever language the brief came in, and name
what the picture shows: subject, setting, light, mood and look. Vague
adjectives ("beautiful", "amazing") do nothing — what the picture shows
does. How to phrase it depends on the image model in use, and the tool's own
description says which way that model reads: short keyword phrases with the
most important first, whole flowing sentences, or a full description in
plain prose. Follow the description. Things that must stay out go into
`negative_prompt` — unless the description says it has no effect, as it does
at CFG 1; then leave it out.

In a chat the picture appears in your answer by itself. In a job nobody sees
it there: hand it on with `deliver_file`, passing the path the tool reports
for the picture. Either way, do not describe its contents afterwards — you
have not seen it.
