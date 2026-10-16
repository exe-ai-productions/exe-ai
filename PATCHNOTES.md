# Patch notes

## 0.6.14 — Picture Studio

### New

- Added a picture studio of its own that keeps its picture, mask, model and values, draws without a chat and lists its own pictures.
- Added the switch "Keep model loaded" to the speech server window; it keeps the voice loaded for the length of a conversation, so it starts speaking sooner.
- Added the field "Pause before sending" to the speech server window; it sets how long you stay silent before what you said is sent.
- Added "Auto" for GPU layers in the llama.cpp server windows: an empty field leaves it to llama.cpp how much of the model goes on the graphics card.
- Added the switch "KV - Unified" under "Parallel requests"; with it, every request can use the whole context instead of a fixed share.
- Added the llama.cpp section, with its download and update, to every llama.cpp server window.
- Added a restart of the running llama.cpp servers after a new build is downloaded: they start again with the values they ran with, and the old build stays until every model is loaded and takes over if a start fails.
- Added a copy of llama.cpp of its own for the kept voice, downloaded by itself the first time it is needed, so a change of the server build never touches the voice.
- Added links for bare web addresses: an http or https address in an answer can now be clicked.
- Added the logo an MCP server sends along to its card, its tool rows and its notices.

### Chat

- We improved the flow of a running answer: text and thinking fade in, the text follows at most a quarter of a second behind, the view glides along, and thinking and tool calls form one block per run.
- We improved the line beside an answer, which now always ends at its mark: the mark keeps drawing itself without disappearing and stays still once the answer is done.
- Fixed an issue that pulled a running answer up when its first tool calls folded into a bundle.
- We improved the speed of the chat list with many chats.
- We improved the arrow of the Regenerate button.
- Fixed an issue where the model told you to look for delivered files in the Doc folder, which does not show them in a chat.
- Fixed an issue where the microphone did not start again from the second round of a conversation on some Macs; the microphone now opens once and stays open until the conversation ends.
- Fixed an issue that ended a conversation round with an error when the microphone had delivered no sound yet.
- We improved the error message of speech recognition, which now names the reason the speech server gave.
- We improved the start of the voice in a conversation, which now begins speaking at the first comma of an answer.
- Fixed an issue where the clean-up model answered a dictated question instead of tidying it.
- We improved the microphone button: while you dictate or talk, a line takes the place of the buttons on the left of the input bar and shows your voice, and the voice of the answer in blue; the timer beside the button is gone.
- Fixed an issue where the voice still spoke a sentence after a conversation had ended, loading a second voice model for it.
- Fixed an issue where a voice kept loaded could make a Mac with 8 GB of memory stop responding for about a minute; on such a computer "Keep model loaded" now starts switched off.

### Context and models

- Fixed an issue where the window could keep working with an older background service instead of starting its own.
- Fixed an issue where a new storage location for models only took effect after a restart.
- Fixed an issue where the model row did not name the file that is really running.
- Fixed an issue where the agent server forgot its speed and vision modules at every change of model.
- Fixed an issue where the vision row showed no projector although the server started with the one found next to the model.
- Fixed an issue where the memory estimate left out the 8-bit cache and the vision projector.
- Fixed an issue where a second window overwrote the advanced settings of the model server.
- Fixed an issue that lost a change made just before a server window was closed or started.
- Fixed an issue where the slider "MoE experts on CPU" could not be dragged while its field was empty.
- Fixed an issue that lost the model, context, GPU layers, CPU threads and port of the speech, clean-up and embedding servers.
- Fixed an issue where every sentence of the voice ended with "Speech generation failed." on computers with little memory.
- Fixed an issue that refused a voice sample saved in the extensible WAV format.

### Images and video

- We improved the studio, which now opens with the hand tool and with the mask switched off; a mask that is switched off is neither shown nor sent.
- Fixed an issue where brush and eraser left marks while the mask was switched off.
- We improved the studio row, which keeps the original picture on top, and the studio now shows the resolution of the picture in the area.
- Fixed an issue that loaded the image model a second time for the first picture after the image server was started by hand.
- Fixed an issue where upscaling ignored the device settings of the image server.
- Fixed an issue where a refused setting of the image server disappeared.
- Fixed an issue where the image server showed "inactive" instead of "error" when its server had stopped.
- Fixed an issue that reported a long picture in the chat as timed out.
- Fixed an issue that kept an enlarged picture with default values instead of those of its original.
- Fixed an issue that counted pictures you took out of a run as not generated after a reload.
- We improved the picture kits: the vision field offers only files with a vision encoder, a part the image program adds by itself counts as there, the kit of Qwen-Image 2.1 brings its vision part, and its Turbo files start with the eight steps of their model card.
- We improved the picture card in the Terminal panel, which shows the prompt once, leaves out empty values and uses the words of the app.

### Model catalogue and downloads

- We improved the choice of the image program's variant: the variant you picked is the one that starts.
- Fixed an issue where an update of the image program on a Mac used a variant left on disk, and on Windows a build that was still being unpacked; a new build is now put in place only once it is complete.

### Agents, jobs and schedules

- Added picture addresses to agent jobs: a job can take a picture from an http or https address, with a size limit and a safety check.
- Fixed an issue where a stop right after a handoff let the run continue.
- Fixed an issue that shrank the task field of the job windows to a single row.
- Fixed an issue that refused a helper at the wrong count when the limit was one.
- We improved the schedule form, which now says in a sentence what a typed schedule means and when it runs next.

### Tools, files and MCP

- We improved the detail card of a tool, which now says "active" or "inactive".

### Settings and layout

- We improved the cloud window, which now lists every provider you created, also the unreachable ones, with their state and a way to remove them.
- Fixed an issue that rewrote config.yaml without its comments when a provider was added, changed or removed.
- Fixed an issue where a cloud model named vendor/model could not keep its parameters.
- Fixed an issue that showed the Exe look for a moment before the chosen look at start.
- We improved long folder paths, which are now cut at the front so the folder name stays visible.
- Fixed an issue that painted the area under the first row of cards black when a card menu was open.
- Fixed an issue where the German manual called the appearance by two names.

### App, updates and Windows

- Fixed an issue that reported a failed download or installation of an update as a failed look.
- Fixed an issue where a script on Windows failed to start without saying why.

### CLI (still in development)

- Added /setup and exe setup, which guide through four steps, and a question at the first start whether to set up.
- Added /provider to add and remove cloud providers and set their context size, time limit and capabilities.
- Added /compact, and the skills in the list behind the slash.
- Added /memory and /system, which open the memory and the instructions in the text editor of the computer.
- Added /dir to show, share and stop sharing working folders.
- Added exe -p, which sends one message and writes only the answer, for scripts.
- Added @path to attach a file or an image, with Tab to complete the path; a file dropped on the terminal becomes a mention.
- Added /agents and /agents edit for the tasks of the agents and the agents themselves, and exe agents from outside.
- Added /cron for scheduled tasks, with weekly schedules, and exe cron from outside.
- Added search in the chat list, the archive, and /rename, /delete and /archive.
- Added /project and exe --continue.
- Added /tools and /ps.
- Added /mcp for MCP servers; their tools read "active", "asks" and "inactive".
- Added /skills for skills.
- Added /settings, which replaces /set.
- Added /files for the files of the open chat.
- Added /image and /server image.
- We improved the look of the CLI: the cursor and the mark carry the accent of the theme, and a selection in the CLI tab stays readable in Heaven and Moune.
- Fixed an issue that left empty rows in the CLI after a list closed.
- We improved the CLI tab in the window: addresses open in the browser, a dropped file types its path, and a missing client is named.

## 0.6.13 — Windows Hotfix

### Windows

- Fixed an issue that ran the model server on Windows on the processor only: the graphics card stayed idle, the GPU layers setting had no effect, and large models took minutes to read the context. The model server now offers the same builds of llama.cpp as the image server: CPU, CUDA, Vulkan and ROCm.

## 0.6.12 — Major Bugfix Update

### New

- Added the exe command, a chat client for the terminal that is still in development.
- Added a CLI tab in the right column that runs the exe command in the skin and language of the window.
- Added exe service start, run, stop and status to control the background service from the terminal.
- Added the /model, /server, /status and /download commands, which start local models, control the six local servers and fetch models from Hugging Face.
- Added remote access, where a service that other computers can reach asks for a password before it can be used.
- Added the exe command to the system path, placed by the app, the Windows installer and the Store.
- Added a background service that keeps running after the window closes, so the exe command can use it; exe service stop ends it.
- Added an upscaler choice of its own for upscaling in the studio, separate from the highres pass.
- Added a time limit for drawing pictures on the image server page; it is empty by default, which means no limit.

### Chat

- Fixed an issue that deleted the previous answer before a new answer was finished.
- We improved the handling of failed answers with a Try again button.
- Fixed an issue that lost the thinking of tool rounds when an answer was generated again.
- Fixed an issue that lost an answer when the service ended during a regeneration.
- Fixed an issue that kept a finished answer marked as running.
- Fixed an issue that ignored the stop button right after a message was sent.
- Fixed an issue that kept summarising a chat after you pressed stop.
- Fixed an issue that showed an error notice when you stopped an answer while a question was open.
- Fixed an issue that lost your text and attachments when a message could not be sent.
- Fixed an issue that lost a queued message when the service turned it away.
- Fixed an issue that showed tool results under the wrong tool call while an answer was running.
- Fixed an issue that could attach a chat to the wrong answer after a broken connection.
- Fixed an issue that left a mixed view behind when switching to another chat failed.
- Fixed an issue that could write into a chat after it was deleted.
- Fixed an issue that hid chats beyond the newest hundred in the sidebar.
- Fixed an issue that showed images from tools as plain files.
- Fixed an issue that showed an empty space for a delivered image that could not be loaded.
- We improved the display of videos made by the model, which now appear in the chat like images.
- Showing Markdown images in answers now works as expected.
- Fixed an issue that cut documents with code blocks short.
- Clicking links in your own messages now works as expected.
- We improved the display of the model's thinking while an answer is running.
- We improved the naming of new chats, which now take the first line of the first message.
- We improved the search of chat titles, which now ignores capitals and accents.
- We improved the handling of several open questions from the model, which now wait in one row.
- Keyboard navigation in the question card now works as expected.
- We improved the send button of the input bar, which now says why it is locked.
- Fixed an issue that made the empty input field two lines high at some window widths.
- We improved the look of queued messages.
- Fixed an issue that showed a grey placeholder instead of a server's icon in tool notices.
- Fixed an issue that showed a wrong speed under answers with tool calls.
- Fixed an issue that showed the added-up figures of earlier rounds under a running answer.
- Fixed an issue that silently dropped image attachments that could not be read.
- Fixed an issue that saved the same uploaded image again and again.

### Context and models

- We improved the handling of long chats with a /compact command that summarises a chat on request.
- We improved the behaviour of the model in chats with tools, which now says clearly when it cannot get any further and stops.
- Fixed an issue that let a chat full of images overflow the context window before it was summarised.
- Fixed an issue that made the model forget images it had just looked at with a tool.
- We improved the handling of images from tools in long chats, which now stay in the request up to 20 images or 24 MB.
- Fixed an issue that made Try again forget the images the failed answer had read.
- Fixed an issue that let one model's context limit lower the limit of other models.
- Fixed an issue that kept a provisional context size from before the model was loaded.
- Fixed an issue that summarised a chat three times in a row on vLLM servers.
- Fixed an issue that showed a wrong context figure when the server sent no usage data.
- Fixed an issue that miscounted the context of Anthropic models with thinking.
- Fixed an issue that showed an outdated model list after the server changed its models.
- Fixed an issue that showed outdated model capabilities after the model on a server changed.
- Fixed an issue that switched to another model while the chosen model's server was away.
- Fixed an issue that offered the agent server's models in the chat's model choice.
- We improved the thinking switch of the input bar, which now shows the stage the model really receives.
- Fixed an issue that turned off thinking for some models because of a word in their name.
- Fixed an issue that made requests fail at providers that refuse the max_tokens field.
- We improved the parameter settings of OpenAI models, which now show the values the host does not accept as locked.
- Fixed an issue that broke endpoints entered without http://.
- Fixed an issue that cut off long answers from local servers after a timeout.
- Fixed an issue that failed to load the chat template of some MLX models.
- We improved the support of DeepSeek V4 models, whose context size is now built in.
- We improved the speed of follow-up messages with local models, which now reuse the cached start of the chat.
- Fixed an issue that kept a draft model in the model folder from being used.
- We improved the display of the model server state, which now reads active, idle or offline.
- We improved the error display of local servers, which now name the model architecture they could not load.
- Fixed an issue that showed outdated model switches in a second window.

### Images and video

- Fixed an issue that cleared the image studio when a chat was opened.
- Fixed an issue that made Repair faces fail when the prompt bar was empty.
- Fixed an issue that sent the menu entry as the prompt when upscaling a picture in the studio.
- Fixed an issue that deleted a chat and its reference pictures when a picture in the studio failed or was stopped.
- Fixed an issue that stopped long pictures and videos after 15 minutes.
- Fixed an issue that ignored a painted mask when an image was edited.
- Fixed an issue that kept the drawing area from opening the file dialog after a chat change.
- Fixed an issue that started image models without the VAE they need.
- Fixed an issue that showed pose settings for image models that cannot use them.
- Fixed an issue that listed Draw Things database files as image models.
- Fixed an issue that let the image server and a studio image compete for memory.
- Fixed an issue that kept the progress counter of an image from moving on a busy server.
- Fixed an issue that put see-through areas of images on black for the model.
- Drawing with Qwen-Image 2.1, also from a start image, now works as expected.
- We improved the look of an image while it is being drawn.

### Model catalogue and downloads

- Resuming interrupted model downloads now works as expected.
- Fixed an issue that showed a split model as downloaded when only its first part was there.
- Fixed an issue that treated a different file with the same name as an already downloaded model.
- We improved the detection of model families in the catalogue, which now reads each file's header.
- We improved the file list of image models in the catalogue, which now says what each file is.
- We improved the error message of failed downloads, which now appears at the top.
- Fixed an issue that let long model names overflow the catalogue detail page.

### Agents, jobs and schedules

- Fixed an issue that could leave an agent file half written when saving failed.
- We improved the safety of agent files, which now keep their previous version beside them on every save.
- Fixed an issue that opened an empty form for an agent file with a broken header.
- Fixed an issue that drew empty steps in an agent's history.
- Fixed an issue that kept an agent with folders of its own from reaching the folder of the chat it works for.
- We improved the display of questions from waiting tasks in the agents column.
- Fixed an issue that let a new task start while no model was answering.
- Fixed an issue that let a job retry a failed request again and again.
- Fixed an issue that could run the same schedule twice at the same time.
- Running schedules across daylight saving time changes now works as expected.
- Fixed an issue that refused valid cron expressions with irregular gaps.
- Fixed an issue that made a schedule started by hand fail while the model was still loading.
- Fixed an issue that started a schedule by hand in the wrong language.
- Fixed an issue that left the calendar out of date after a schedule changed.
- Fixed an issue that cut off lists in the schedule form.
- Scrolling in the schedule pop-up now works as expected.
- Fixed an issue that showed a light calendar in the schedule form in dark skins.
- We improved the notice of failed schedules, which now names why the last run failed.
- Fixed an issue that made the model promise a built-in reminder agent for schedules without an agent.

### Tools, files and MCP

- Fixed an issue that let tools reach the program's private folders.
- Fixed an issue that broke some commands on Windows because they ran in two shells.
- Fixed an issue that made the model use curl for web searches instead of the search tool.
- Fixed an issue that made the model read a file as a PDF only because of its name.
- Fixed an issue that let the model save plain text under a file name such as .pdf or .png.
- Fixed an issue that made the model add a link below an image it had just drawn.
- Fixed an issue that told the model the wrong folder for relative paths in chats without a shared folder.
- Fixed an issue that made the model expect a private working folder for new folders when no folder was shared.
- Fixed an issue that made the model ask for a shared folder when a file was missing in a chat without one.
- Fixed an issue that pulled the terminal to the front every time the model started a command.
- We improved the command list of the right column, where finished commands now fold away.
- Fixed an issue that showed the output of a script run as one long line.
- Fixed an issue that kept a PDF open in the preview after its attachment was removed.
- Closing the PDF reader with Escape now works as expected.
- Fixed an issue that cut off the file name of a long path in the address field of the side box.
- Fixed an issue that listed hidden files, node_modules and system leftovers such as .DS_Store in the Doc folder.
- Fixed an issue that showed the same file twice in the Doc folder.
- Fixed an issue that showed images as plain files in the Doc folder.
- Opening PDFs from the Doc folder now works as expected.
- Fixed an issue that offered to save a document's preview picture as an image in the Doc folder.
- We improved the drag and drop of files from the Doc folder into the chat.
- We improved the handling of slow MCP servers, which now get up to 300 seconds per call, with a setting for each server.
- Fixed an issue that showed the MCP client secret in plain text.
- We improved the labels of the MCP sign-in fields.
- Fixed an issue that created a broken MCP server entry from a card without an address.
- Fixed an issue that merged your own MCP server with a shipped server of the same name.
- Fixed an issue that squeezed the button on MCP cards with an expired sign-in.
- We improved the setup of SearXNG, which now asks for the address of your own instance.
- Fixed an issue that ignored skills whose header could not be read.
- Fixed an issue that could damage a skill file when it was switched on or off.
- We improved the descriptions of skills in the slash list, which now show two lines.
- Fixed an issue that tried to run Python scripts on Windows with the Store placeholder instead of a real Python.
- Fixed an issue that copied a file the model delivered from the chat's own folder, so it showed twice in the Doc folder.

### Settings and layout

- We improved the layout of narrow windows, where the side columns now fold away and come back by themselves.
- We improved the clarity of the settings pages, which no longer carry explanatory lines under every row.
- We improved the rows of the settings menu, which now show values as numbers and as active or inactive.
- Fixed an issue that let long credentials and tool files stretch the settings page.
- We improved the header of the right column.
- We improved the animation of cards in the side columns.
- We improved the look of the Pearl, Heaven, Exe and Dark Matter skins, which no longer draw shapes behind their surfaces.
- We improved the contrast of fields and buttons in the light skins.
- We improved the contrast of switches in the light skins, whose knob is now white when switched on.
- Fixed an issue that showed a mix of languages after the language was switched.
- Fixed an issue that rejected decimal numbers typed with a comma.
- Fixed an issue that closed an open selection list when another area scrolled by itself.
- Fixed an issue that showed a wrong colour behind the start window with a custom gradient.
- Fixed an issue that showed a Mac example path on Windows in the working folder window.
- We improved the screen reader support of the speech server window.
- Fixed an issue that kept the API key of a removed cloud provider on disk.
- Fixed an issue that stopped dictation from starting on some systems.
- We improved the wording of texts throughout the app, the help and the manual.

### App, updates and Windows

- We improved the start time of the macOS app, which no longer unpacks the service on every start.
- Fixed an issue that kept the service of the previous version running after an update.
- Fixed an issue that let an update install while an older service was still running.
- We improved the error handling of the update check, which now says when it could not reach the release list.
- Stopping the service on Windows now works as expected.
- Fixed an issue that let web pages open the browser without a click.
- Fixed an issue that let a document in its own window open any number of browser tabs.
- Fixed an issue that opened the manual a second time instead of bringing it to the front.
- We improved the context menu of images, which now offers Copy Image.
- We improved the licence information of the Mac app, which now includes Electron and Chromium.

## 0.6.11 — hotfix

- **Web search works on Windows.** On Windows, the built-in web search stopped
  as soon as a result contained a character outside the old Windows character
  set, such as an emoji or Chinese or Cyrillic text, and the searches after it
  failed as well. Accented letters like ä, ö or é also arrived garbled. Search
  results now arrive with every character intact.

## 0.6.10 — hotfix

- **The model server page always shows the llama.cpp row.** When llama-server is
  missing, the row offers a **Download** button that fetches the tested build.
  Before, that button only existed while no model was in the model folder, so a
  computer with a model but without the server had no way to get one, and
  starting a model ended with "llama-server not found".

## 0.6.9 — the first public release

Exe AI is available for macOS on Apple Silicon and as an installer for
Windows (x64). The macOS app is signed and has been notarised by Apple.
The Windows build is not code-signed yet, so SmartScreen may display a
prompt once: choose "More info", then "Run anyway".

**Included features**

- **Local models from start to finish.** A tested catalogue matched to your
  computer's memory, one-click downloads and the built-in llama.cpp runner.
  You can also connect to oMLX, LM Studio, Anthropic, OpenAI or any
  OpenAI-compatible endpoint.
- **Images and video**, made on your own computer with stable-diffusion.cpp:
  an image studio with a drawing area, masks, LoRAs, styles and the settings
  used to create each picture. Video generation is still experimental.
- **Agents, jobs and schedules**, with reports, a calendar and helpers for
  single tasks.
- **Tools you stay in charge of**: three permission modes, saved permissions
  and MCP servers. Questions from the model appear as a card over the chat.
- **A local memory and reusable skills.**
- **Dictation with live text and spoken conversations.** Speech recognition
  and speech output run on your computer.
- **Projects, a Doc folder for your files, five skins, English and German.**
- **Automatic updates.** At startup, the app checks for a newer release,
  shows what is new and installs it with a click. "Check for updates" is
  available in the settings.
- **Windows.** The same app is available as an installer, with shortcut
  labels that match your operating system and no console windows. Files
  are written in full even while another program has them open.

**Still in development**

- Context compression and video generation are experimental and still in
  development.
