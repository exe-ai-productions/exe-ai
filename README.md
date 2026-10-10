<p align="center">
  <img src="docs/site/wordmark.svg" width="601" alt="Exe AI — AI systems reimagined.">
</p>
<p align="center"><b>Your models. Your machine.</b></p>
<p align="center">
  An AI workspace that brings your entire workflow into one window.<br>
  Work with text, documents, images and voice in a thoughtfully designed app<br>
  that stores your data locally.
</p>
<p align="center"><b>This is Exe AI.</b></p>
<p align="center">
  <a href="https://github.com/exe-ai-productions/exe-ai/releases/latest"><b>Download for macOS and Windows</b></a>
</p>
<p align="center">
  <a href="https://github.com/exe-ai-productions/exe-ai/releases/latest"><img src="https://img.shields.io/github/v/release/exe-ai-productions/exe-ai?style=flat-square&amp;label=release&amp;labelColor=1a1a18&amp;color=7d6cba" alt="Latest release"></a>
   <img src="https://img.shields.io/badge/macOS-available-b1a687?style=flat-square&amp;labelColor=1a1a18" alt="macOS: available">
   <img src="https://img.shields.io/badge/Windows-available-b1a687?style=flat-square&amp;labelColor=1a1a18" alt="Windows: available">
   <a href="LICENSE.md"><img src="https://img.shields.io/badge/license-PolyForm%20NC%201.0.0-8f8e86?style=flat-square&amp;labelColor=1a1a18" alt="License: PolyForm Noncommercial 1.0.0"></a>
</p>
<p align="center"><img src="docs/site/trenner.svg" width="100%" alt=""></p>
<p align="center">
  Download a model, start a chat, give your agents tools and schedule their work —<br>
  all without a terminal or configuration files. Local models are the default.<br>
  Connect a cloud provider with an API key whenever you choose.
</p>
<p align="center"><img src="docs/site/trenner.svg" width="100%" alt=""></p>

<h2><img src="docs/site/h-what-it-does.svg" height="36" alt="What it does"></h2>

<table>
  <tbody><tr>
    <td width="50%" valign="top">
      <p><b>Local models, end to end</b></p>
      <p>Browse a curated GGUF catalogue matched to your computer's memory, or search Hugging Face. Download a model with one click and run it with the built-in <code>llama-server</code>. Download, start, chat — no shell or scripts required.</p>
    </td>
    <td width="50%" valign="top">
      <p><b>Images and video, generated locally</b></p>
      <p>Create images, edit existing pictures and generate video in the image workspace with compatible local models, powered by stable-diffusion.cpp. Adjust generation settings, combine LoRAs, work with masks and keep your results in the gallery. Available workflows depend on the selected model. Video generation is still experimental.</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <p><b>Context compression — in development</b></p>
      <p>Exe AI uses its own approach to context compression: it first reduces older tool output, then summarises the middle of the conversation when needed, keeping the opening and recent messages. The original chat remains readable. This feature is still in development.</p>
    </td>
    <td width="50%" valign="top">
      <p><b>A memory that grows with you</b></p>
      <p>Keep rules and facts for future conversations in an editable local memory file. Memory is enabled by default for the models Exe AI runs itself and is shared with other servers and cloud models only if you enable that option.</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <p><b>Agents, jobs and schedules</b></p>
      <p>Define reusable agents in Markdown files with front matter. Run them from a chat or on a schedule, with progress updates and reports. Schedule agents, scripts or reminders, and view past runs and upcoming work in a calendar.</p>
    </td>
    <td width="50%" valign="top">
      <p><b>Tools with adjustable permissions</b></p>
      <p>Use built-in tools or connect MCP servers. Choose Auto, Manual or Restricted to control approval requests. Allow a tool to run once, or save a permission that applies across chats and agent runs.</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <p><b>It knows who it works for</b></p>
      <p>On first launch, enter your name, choose your language and select a look for the app. New chats then greet you by name. A single switch turns name-based personalisation off throughout the app.</p>
    </td>
    <td width="50%" valign="top">
      <p><b>Two languages, original logos</b></p>
      <p>Switch between English and German while using the app. The interface and error messages use your selected language. Model catalogue cards display original vector logos from the model providers.</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <p><b>Dictation, with live text</b></p>
      <p>Dictate into the chat and see a provisional transcript as you speak. Optional text clean-up runs through a small clean-up model or a model you choose. Send the result yourself, or enable automatic sending when dictation ends.</p>
    </td>
    <td width="50%" valign="top">
      <p><b>A voice assistant you can talk to</b></p>
      <p>Have a spoken conversation with automatic pause detection. With speech output enabled, hear replies sentence by sentence as they are generated. Speech recognition and speech output run locally; the conversation uses your chosen chat model.</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <p><b>Projects that keep your work together</b></p>
      <p>Group chats into projects and share working folders across their conversations. Archive individual chats or entire projects when you are done.</p>
    </td>
    <td width="50%" valign="top">
      <p><b>Your files, together</b></p>
      <p>Find uploaded documents and files delivered by agents in one place. View the current chat’s files, browse across projects from the start page and drag documents into a conversation.</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <p><b>Reusable skills</b></p>
      <p>Run a skill with a slash command, let the assistant select eligible skills automatically, or create and edit your own instructions in the app.</p>
    </td>
    <td width="50%" valign="top">
      <p><b>Helpers for individual tasks</b></p>
      <p>Let the assistant delegate a task to a helper without creating an agent file first. Follow its progress and receive its report in the conversation.</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <p><b>See the work as it happens</b></p>
      <p>Follow live command output and tool activity beside the chat. Preview generated HTML and SVG, inspect tables and download results without leaving the conversation.</p>
    </td>
    <td width="50%" valign="top">
      <p><b>Documents with clear context limits</b></p>
      <p>Attach PDFs, text files or source files. Documents are included in full when they fit the available document budget. Larger files stay available for targeted reading through tools, and the interface shows when they are too large for the context.</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <p><b>Updates itself</b></p>
      <p>At startup, the app checks for a newer release, shows what is new and installs it with a click.</p>
    </td>
    <td width="50%" valign="top">
      <p><b>One app, two systems</b></p>
      <p>The same app with the same features is available for macOS (Apple Silicon) and Windows (x64); keyboard shortcut labels match your operating system.</p>
    </td>
  </tr>
</tbody></table>
<p align="center"><img src="docs/site/trenner.svg" width="100%" alt=""></p>

<h2><img src="docs/site/h-five-worlds.svg" height="36" alt="One program, five worlds"></h2>

Choose one of five skins — **Exe**, **Pearl**, **Dark Matter**, **Heaven** or **Moune** — to change the look of the entire interface, including the frame, lines, chat bubbles and code blocks.

Choose a code colour scheme — Exe, Tokyo Night, One Light, GitHub, GitHub Dark, Dracula, Nord, Solarized Light or Solarized Dark — and customise your chat bubble colour. The text automatically switches between light and dark to stay readable. You can also customise the frame gradient.

<p align="center"><img src="docs/site/trenner.svg" width="100%" alt=""></p>

<h2><img src="docs/site/h-models.svg" height="36" alt="Models"></h2>

The curated catalogue brings together models from the open model ecosystem. Before being added, each model was tested for startup, tool use and, where supported, image input. Use the built-in llama.cpp runner for full compatibility.

Already running a model server? Connections to **oMLX** and **LM Studio** have been tested. You can also connect to Anthropic, OpenAI or an OpenAI-compatible endpoint using an API key.

The speech catalogue includes **Qwen3-ASR** and **Voxtral** for local speech recognition, plus **Qwen3-TTS** for speech output. Recognition runs through `llama-server`; speech output uses `llama-tts`, with optional voice samples.

<p align="center"><img src="docs/site/trenner.svg" width="100%" alt=""></p>

<h2><img src="docs/site/h-tools.svg" height="36" alt="Tools with adjustable permissions"></h2>

Share your own working folders or let the chat use its own workspace. Choose how tools can act:

- **Auto** — tools run without routine approval prompts, including access outside the working folders.
- **Manual** — file and command tools can work within the working folders without asking. Access outside them and other tool calls generally require approval.
- **Restricted** — approval is also required for file and command operations within the working folders.

A fresh installation starts in Manual mode but asks for approval only for file and command access outside the working folders; other tools run without asking until you choose a mode yourself.

These are the mode defaults. Explicit tool rules and MCP confirmation settings can change when approval is required. The middle mode is labelled **Sandboxed** in the agent settings.

Choose **Always allow** to save a permission for the entire tool across all chats and agent runs, not just the current file or command. You can revoke saved permissions. Commands matching the built-in blocked shell patterns remain blocked in every mode.

Unattended agents refuse actions that require approval. Agents running from a chat can send approval requests back to that conversation.

Connect additional tools through **MCP**: Notion, GitHub, Figma, Gmail, Recraft, Hugging Face or your own server. Tool output is treated as **data, not instructions**, including content retrieved from web pages.

<p align="center"><img src="docs/site/trenner.svg" width="100%" alt=""></p>

<h2><img src="docs/site/h-privacy.svg" height="36" alt="Built for privacy"></h2>

- The service listens on **127.0.0.1**. Chats, settings, keys and models are stored locally, in files and a SQLite database.
- API keys are stored in a local file with restricted permissions and are never displayed again. The interface receives only a status indicating *whether* a key has been set.
- Saved memories are shared with cloud providers only if you enable that option. Your name is sent with each conversation, including to cloud providers, as long as name-based personalisation is on.
- Models are downloaded directly from huggingface.co. Model searches go through the local service, so your browser does not contact Hugging Face directly for search requests.
- The model server receives a new key each time it starts. The app also protects its API with a key generated for each session and rejects cross-origin write requests from web pages.

<p align="center"><img src="docs/site/trenner.svg" width="100%" alt=""></p>

<h2><img src="docs/site/h-quick-start.svg" height="36" alt="Quick start"></h2>

### Download the app

Download the app for your operating system from the [latest release](https://github.com/exe-ai-productions/exe-ai/releases/latest). No account is needed.

- **macOS (Apple Silicon)** — open the `.dmg` and drag the app into your Applications folder. The app is signed and has been notarised by Apple.
- **Windows (x64)** — run the installer. It is not code-signed yet, so Windows SmartScreen may show "Windows protected your PC": choose *More info*, then *Run anyway*.

The app checks for a newer release when it starts and displays it in a card, where you can download and install it with a click. *Check for updates* is available in the settings.

### From source

You need Python 3.11 or 3.12 and Node.js 22.

```bash
git clone https://github.com/exe-ai-productions/exe-ai
cd exe-ai
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd frontend && npm ci && npm run build && cd ..
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8090
```

Then open `http://127.0.0.1:8090/app/` in your browser. If the Exe AI app is running, quit it first — it uses the same port. To run local models, install [llama.cpp](https://github.com/ggml-org/llama.cpp) or let the Local view download `llama-server`, just as it does in the packaged app. Run the test suite with `.venv/bin/pytest`.

<p align="center"><img src="docs/site/trenner.svg" width="100%" alt=""></p>

<h2><img src="docs/site/h-http-api.svg" height="36" alt="HTTP API"></h2>

The app uses a local HTTP API. Requests to the routes listed below that begin with `/api/v1` require the current session key in the `X-Sitzungsschluessel` header. The table lists selected routes and route families.

<table>
<thead><tr><th>Method</th><th>Address</th><th>Purpose</th></tr></thead>
<tbody>
<tr><td>GET</td><td><code>/health</code></td><td>Service and database status</td></tr>
<tr><td>GET</td><td><code>/api/v1/meta</code></td><td>Features, languages and version</td></tr>
<tr><td>GET</td><td><code>/api/v1/models</code></td><td>Connected model endpoints and their reported model names</td></tr>
<tr><td>GET, POST</td><td><code>/api/v1/chats</code></td><td>List and create chats; individual chat routes handle updates and deletion</td></tr>
<tr><td>POST</td><td><code>/api/v1/chat/completions</code></td><td>Generate a response through Server-Sent Events</td></tr>
<tr><td>POST</td><td><code>/api/v1/chat/confirm</code></td><td>Answer a pending tool approval request</td></tr>
<tr><td>GET</td><td><code>/api/v1/tools</code></td><td>List connected tools</td></tr>
<tr><td>GET</td><td><code>/api/v1/agents</code><br><code>/api/v1/jobs</code></td><td>List reusable agents and their jobs</td></tr>
<tr><td>GET, POST</td><td><code>/api/v1/projects</code></td><td>List and create projects</td></tr>
<tr><td>GET, POST</td><td><code>/api/v1/cronjobs</code></td><td>List and create scheduled work</td></tr>
<tr><td>GET</td><td><code>/api/v1/cronjobs/calendar</code></td><td>Scheduled occurrences within a calendar range</td></tr>
<tr><td>GET, PUT</td><td><code>/api/v1/memory</code><br><code>/api/v1/system-prompt</code></td><td>Read and edit memory and the system prompt</td></tr>
<tr><td>GET, POST</td><td><code>/api/v1/skills</code></td><td>List and create skills; individual skill routes support editing</td></tr>
<tr><td>POST</td><td><code>/api/v1/documents</code></td><td>Upload a document and extract its text</td></tr>
<tr><td>GET, DELETE</td><td><code>/api/v1/documents/{dokument_id}</code></td><td>Inspect or remove a document</td></tr>
<tr><td>GET</td><td><code>/api/v1/runner</code></td><td>Local language model server status</td></tr>
<tr><td>POST</td><td><code>/api/v1/runner/start</code><br><code>/api/v1/runner/stop</code></td><td>Start or stop the local language model server</td></tr>
<tr><td>GET</td><td><code>/api/v1/models/search</code><br><code>/api/v1/models/files</code></td><td>Search models and inspect repository files</td></tr>
<tr><td>GET, POST, DELETE</td><td><code>/api/v1/runner/download</code></td><td>Monitor, start or cancel a model download</td></tr>
<tr><td>POST</td><td><code>/api/v1/bild</code></td><td>Start image or video generation with a compatible model</td></tr>
<tr><td>GET</td><td><code>/api/v1/bild/fortschritt</code></td><td>Image and video generation progress</td></tr>
<tr><td>POST</td><td><code>/api/v1/bild/stop</code></td><td>Cancel image or video generation</td></tr>
<tr><td>GET</td><td><code>/api/v1/sprachserver</code></td><td>Speech models and server status</td></tr>
<tr><td>POST</td><td><code>/api/v1/sprachserver/start</code><br><code>/api/v1/sprachserver/stop</code></td><td>Start or stop the local speech recognition server</td></tr>
<tr><td>POST</td><td><code>/api/v1/sprachserver/transkribieren</code></td><td>Transcribe WAV audio, with optional text clean-up</td></tr>
<tr><td>POST</td><td><code>/api/v1/sprachserver/sprechen</code></td><td>Convert text to speech and return WAV audio</td></tr>
<tr><td>GET</td><td><code>/api/v1/einbettungsserver</code></td><td>Embedding models and server status</td></tr>
<tr><td>POST</td><td><code>/api/v1/einbettungsserver/start</code><br><code>/api/v1/einbettungsserver/stop</code></td><td>Start or stop the local embedding server</td></tr>
<tr><td>GET</td><td><code>/api/v1/events/stream</code></td><td>Receive application events through Server-Sent Events</td></tr>
</tbody>
</table>
<p align="center"><img src="docs/site/trenner.svg" width="100%" alt=""></p>

<h2><img src="docs/site/h-license.svg" height="36" alt="License"></h2>

[PolyForm Noncommercial 1.0.0](LICENSE.md) — in plain language: use, modify and share it for personal, educational or other noncommercial purposes. Commercial use — such as use within a company or for paid work — requires a commercial license. Contact **[dev@exe-hq.net](mailto:dev@exe-hq.net)**.

<p align="center"><img src="docs/site/trenner.svg" width="100%" alt=""></p>
<p align="center">
  <img src="docs/site/mark-grey.svg" width="80" alt="">
</p>
<p align="center">
  <a href="https://github.com/exe-ai-productions/exe-ai/releases">Releases</a>
</p>
<p align="center"><sub>© 2026 Exe AI Productions</sub></p>
