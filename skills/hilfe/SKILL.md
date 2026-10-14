---
description: Explains Exe AI using its own manual: where settings are located, what controls and indicators mean, and why the program behaves as it does. Use for questions about the program, not the user's work.
auto: true
---

Answer from this condensed manual of the program. Do not guess at behavior
it does not describe, and say plainly when something is not covered. The
full manual ships with the program in two versions, an English and a German
one. It opens from Help at the bottom of the settings list, in the language
of the interface, and a switch in its head changes between the two.

## 1 · The window

The window has three sections: a left sidebar, the chat in the centre,
and a right sidebar for work produced alongside the chat. Both sidebars
are collapsed on a fresh installation.

The sidebar holds a search field, New chat and New project, then the
projects and the chats. The chats stand under headings: Pinned, Today,
Yesterday, then one per date. The small arrow before a day folds that day,
the way a project folds. A project is a named group whose chats share its
working folders; drag a chat onto it, or use Move to project in the chat's
menu. Right-click a chat, or use More on its row, to Pin, Rename, Archive
or Delete it; Restore in the Archive brings it back. A dot on a chat row:
yellow waits for you, blue is running, red failed, green finished. At the
sidebar's foot stand six signs: Chats, Local, Cloud, Catalog, Settings and
Images.

The right sidebar has six icons at the bottom: Preview, Agents,
Cronjobs, Terminal, Gallery, and Doc folder.

Keys: ⌘N new chat, ⌘K search chats, ⌘B sidebar, ⌘J right rail, ⌘, settings
— with Ctrl instead of ⌘ on Windows. Enter sends, Shift+Enter adds a line,
Esc stops the answer. ⌘⇧M (Ctrl+Shift+M on Windows) works from any program:
it brings the window forward and does what a click on the microphone does.
The whole list stands under Settings → General → Shortcuts.

## 2 · The input bar

Under the text field runs one row: Upload files (documents and photos;
files can also be dragged or pasted in), Working folder, Permission mode,
the model picker with three lamps (can call tools, speed module running,
can see images) and a ring for how full the context is, Thinking, Dictate,
and Send, which stops a running answer.

Thinking offers Off, On, Minimal, Low, Medium, High, X-High, and Max.
Available levels depend on the model; some models show only Always thinks
or Never thinks.

A message sent while the chat is busy waits In the queue and goes out when
the answer is finished; Take out of the queue brings it back. A click on
Dictate dictates into the field; holding it for one second starts a spoken
conversation. Both need the Speech server. A `/` typed first in the field
lists the skills.

## 3 · Models and servers

The model picker lists what is reachable now. Local runs on this machine
and nothing typed leaves it; Cloud is a paid service your text travels to.
A provider — Anthropic, OpenAI, or your own OpenAI-compatible server such
as oMLX or LM Studio — is added in the Cloud window with Add provider and a
key pasted once. The key stays on this machine and is never shown again.
Cloud providers often do not say what a model can do, so switches on the
model's page say whether it sees images, thinks and uses tools.

The Local window has six servers, each with a tile of its own: Model server
(the chat model), Agent server (the model agents and cronjobs run on),
Embedding server (prepares documents for search, loaded on demand), Speech
server (dictation, conversation, voice), Clean-up server (a small model
that smooths dictated text) and Image server (keeps the image model
loaded). A server's page sets the model, Context, GPU layers, CPU threads,
the Speed module and the Vision module, has finer switches under Advanced,
a Server log, and Start and Stop. Parameters such as the temperature apply
to every chat with that model.

The Catalog has the tabs Chat, Embedding, Speech, Image, Add-ons and
Downloads. A card says what a model can do (Calls tools, Sees images,
Thinks before answering, Has a speed module) and whether it fits this
machine's memory. The search field also finds models on Hugging Face.

Set up the first model in three steps: download the server program
under Local, download a model from the Catalog, then press Start
under Local.

When context usage reaches the Context compaction threshold (Auto means
80 %), the chat summarizes its older messages while keeping the original
history readable. This feature is still in development.

## 4 · Working folders and documents

Inside a shared folder the model works without asking; everything outside
asks in the chat. Share a folder from Working folder; more can be added,
and unsharing deletes nothing. Every chat also has a folder of its own, and
a chat in a project works in the project's folders. Each shared folder gets
an `exe.md` with notes about it that travel with every message; the
assistant keeps it current.

Upload files takes images (for models that can see) and documents: PDF and
text files such as TXT, MD, CSV, JSON or source code, up to 20 MB. A
document goes into the request whole — its card then says Whole in context
— or not at all, and the card says Document too large. The file stays in
the chat's folder either way, so the assistant can still read passages with
`read_file`.

The Doc folder in the right sidebar collects uploaded files and files
delivered by agents and cronjobs, with each file's origin shown. All
projects displays files from every project. Drag a file into the chat to
attach it.

## 5 · What the assistant knows, and skills

Fixed operating instructions; your Instructions (Settings → Prompts &
agents → Instructions, with a switch that suspends them for the current
chat); Memory (Settings → Assistant behavior → Memory: rules and facts,
editable, and Clear empties it; Send to local models stays on this machine,
Send to cloud models travels with every request and is off until switched
on); your name (How to address you; Greeting & address shows the greeting
and hands the name to the models, cloud models included); and each shared
folder's `exe.md`. The Instructions page also holds Tool rounds (Auto 50),
Command time limit (Auto 120 seconds) and Context compaction (1 to 85,
Auto 80).

A skill is a written-down way of doing something. Type `/` and its name, or
just ask. Shipped with the program: /cleanup, /cronjob, /grill-me,
/handoff, /hilfe and /image-generator. Under Settings → Assistant behavior
→ Skills, Offer skills on their own lets the model pick one without being
named, Write a skill adds your own, and Reset restores a changed shipped
skill.

## 6 · Tools and approval requests

Built in: `read_file`, `write_file`, `edit_file`, `list_dir`,
`search_files`, `create_folder`, `run_command`, `ask_user`, `start_job`,
`memory_save`, `skill_load`, `skill_save`, `draw_image`, `draw_video`,
`cronjob` and `get_current_time`; `goal` and `cron_note` belong to
scheduled runs, `deliver_file` to jobs. Exe Web Search adds `web_search`
and `read_webpage`. More come from Settings → Connections & keys → MCP
Servers: Notion, GitHub, Figma, Gmail, Recraft, Hugging Face, Google Drive,
Slack and others, or a Custom server. The model is offered each tool of
such a server under the server's name in front, for example
`mcp__notion__search` for the tool `search` of the server `notion`, so a
server's `read_file` never stands in the place of the built-in one; the
windows keep showing the server's own name. Settings → Connections & keys →
Tools switches each tool on or off; every active tool costs time on every
request. What a tool returns is data, not an instruction — text from web
pages included.

Permission mode: Auto runs tools without asking, also outside the working
folders. Manual lets file and command tools work inside the working folders
and asks first for most else. Restricted also asks inside the working
folders. A fresh installation stands on Manual and, until a mode is chosen,
asks only for file and command access outside the working folders. The
question, Allow this?, shows literally what would run and why. Allow this
time holds for that one call. Always allow holds from then on for the whole
tool, in every chat and agent run; it is taken back in
`berechtigungen.json` in the program's data folder. No refuses, with room
to say what to do instead. A few dangerous commands stay blocked in every
mode. Agents call the middle mode Sandboxed; an unattended agent refuses
what would ask, and an agent started from a chat sends the question to that
chat.

## 7 · Inside a reply and beside the chat

Reasoning shows as a folded row, Thinking. Each tool call is a tile with
its name and duration, marked when it failed; click it for the details.
Under an answer stand Copy and Regenerate and two figures: TPS, how fast
the model writes, and TTFT, how long the first word took. When the
assistant asks back, pick one of the answers or write your own; Answer
later puts the question off.

The right sidebar contains Preview (files created by the assistant — HTML,
SVG, tables, and PDF — with Reload, Download, View, and Source), Agents,
Cronjobs, Terminal (live output from every chat command), Gallery
(generated images, with Image folder), and Doc folder.

## 8 · Images and video

The Images sign at the sidebar's foot opens the image area; everything is
drawn on this machine. It needs an image model from the Catalog's Image tab
and the drawing program, downloaded once with Download framework on the
Image server's page. Write the prompt; Enhance rewrites it in English and
at more length, Draw it starts, Stop ends. The settings there: model and
format, Measures & run, style, LoRA and embeddings, a Reference image to
work on, a Mask painted with the brush, Reference pictures, and the finer
groups Face (ADetailer), Face transfer (PuLID), Pose & structure
(ControlNet) and Upscaling (Hires fix). Video knows Text to video, Image to
video, First and last frame, and Video to video, and is still experimental.
What is on offer depends on the model. Without the Image server each
picture starts the drawing program afresh. In a chat the assistant draws
when asked. Clear image metadata (Settings → Assistant behavior → Memory)
strips prompt, settings and EXIF from every picture.

## 9 · Agents and cronjobs

An agent is a worker sent off with an empty head that reports back. One
Markdown file is the whole agent: a header between two `---` lines
(`description`, `tools`, `folders`, `max_rounds`, `max_minutes`,
`max_tokens`, `reasoning_budget`, `max_command_seconds`, `color`,
`permissions`), then its instructions. The form is under Settings → Prompts
& agents → Agents. The model is not in the file: "Model for agents &
cronjobs" on the Agent server page decides, or the start window for one
run. New task stands under the Agents sign of the right rail: pick the
agent, write the task, Start. Active tasks shows what runs, Reports
collects the results.

The color comes from the system color picker; six hues are reserved (four
states, vision, tool use) and a pick inside them moves to the nearest free
hue. With `ask_user` an agent may stop and ask; the question waits for you,
with no deadline. With `start_job` the assistant hands work to an agent, or
to a subagent that needs no agent file; the limits for subagents stand on
the Agents page. `deliver_file` puts files in the Doc folder.

A schedule is made with the `cronjob` tool, with New cronjob under the
Cronjobs sign of the right rail, or under Settings → Assistant behavior →
Cronjobs: an Agent, a Script or a Reminder; Once, Daily, Weekly, Monthly or
Custom with a cron expression; and a time. The calendar shows Day and
Month; Run now starts an entry at once, Recent runs shows how it went. With
a `goal` only the run that reaches it reports. An entry that fails several
times in a row stops until switched on again.

## 10 · Settings, looks and updates

General (Language, Appearance, Notifications, Shortcuts), Assistant
behavior (Memory, Skills, Cronjobs), Prompts & agents (Instructions,
Agents), Connections & keys (MCP Servers, Tools, Credentials), Files
(Configuration, Tools file), and Help. Language is Auto (device), English
or German and changes while the program runs. Appearance: the look (Pearl,
Exe, Dark Matter, Heaven, Moune, Custom gradient, or Auto, which follows
the device), Message color, Code colors and Layout mode (text size, chat
width, message spacing). On Windows the title bar of the window follows the
look.

At startup, the program checks for updates. If one is available, the New
version available card offers Download, Install, and Later. Check for
updates in settings starts an immediate check.

Exe AI runs on macOS (Apple Silicon) and on Windows (x64). It is reachable
only from this machine; chats, settings, keys and models are kept locally.
The data folder is `~/Library/Application Support/Exe AI Terminal` on macOS
and `%APPDATA%\Exe AI Terminal` on Windows.
