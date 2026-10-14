---
description: Inspects a folder before removing unnecessary files.
auto: true
---

Cleaning up a folder requires deciding what can be removed. Do not make
that decision without informing the user.

First, list the folder and inspect its contents. Filenames alone are
unreliable: `new2.txt` may be the only copy of important work, while
`backup/` may contain years of redundant files.

Group the findings into the following three categories and present them to the user:

- **Rubbish** — system-generated or reproducible content: `.DS_Store`,
  `Thumbs.db`, `__pycache__`, `node_modules`, reproducible build output, and
  empty folders.
- **Probably rubbish** — abandoned attempts, duplicates, or downloads used
  only once. Explain why each item appears unnecessary.
- **Keep** — any content that cannot be replaced.

Delete the first group. Ask about the second group in a single consolidated
message, rather than asking separately about each file. Never modify the
third group.

Do not empty a folder merely because it looks disorganized or delete an item
you have not inspected. Explain the issue to the user instead.

The user's instructions in the same message take precedence. If they
explicitly ask to "just delete all of it", do so and report what was
removed.
