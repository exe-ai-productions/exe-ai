# Patch notes

## 0.6.50-r1 — Major Feature & Bugfix Update | + Smartphone Web App

### New

- Added a phone view: on a phone or tablet, or in a window narrower than 600 pixels, Exe AI shows a page made for touch, with sign-in, the chat list as a drawer, notices, questions, the first start and the designs Exe and Pearl.
- Added a sign in the menu bar, on Windows in the notification area: Exe AI keeps running after its window closes, the sign shows whether the service answers, and its menu offers "Open Window", "Stop Service" and "Quit Exe AI" in the language of the interface.
- Added a message when the service cannot be stopped from the sign in the menu bar.
- Added dictation from the keyboard shortcut while Exe AI runs only in the menu bar: a new window opens and the dictation begins in it.
- Added stopping a running answer by sending a new message: the answer stops and keeps its text so far, and your message goes out at once; while a tool runs, it first waits for the tool's result.
- Added a sound of its own for a finished agent or schedule, and for every kind of notice a switch for its sound and one for its popup.
- We improved the sounds, which are now soft synth tones.
- Added the settings page "Web App": it sets up access from your phone through Tailscale over https, with a QR code to scan, and every request that comes that way asks for the password; the password needs at least eight characters, and the page says so before you type.
- Added the settings page "Overview" under Servers: state, port and chosen model of the six local servers, with start and stop, the wired memory measured against the limit of the system, and the MCP connections as a table.
- Added the field "Idle TTL" to the six server pages: after that many minutes without a request, a server frees its model; the image server ends itself and starts again with the next picture, and the speech server uses it only while "Keep model loaded" is off.
- Added "list" and "stop" to the model's job tool: the model sees the helpers it started, including one that handed its work on to a continuation, and can stop them; its report comes into the chat marked as stopped.
- Added a watchdog for helpers started from a chat: a run that shows no sign of life for 450 seconds is ended as failed, and its report comes into the chat.
- Added PDF pages drawn by Exe AI itself: in the panel beside the chat, in the large view with the pages one under another, and as the first page in the tiles of the Doc folder.
- Added the voices of the system to the speech server: the field "Voice" lists them with name and language after the voice models, and from the start Exe AI speaks with Anna on the Mac and Microsoft Katja on Windows, without loading a voice model.
- Added any voice model in GGUF format to the speech server: the language and the five voice values can stay on "Auto", and a model without a language list speaks without one.
- Added the white design Snow; "Auto" now shows Snow on a light computer, and a first start follows the appearance of the computer and opens the right column on the CLI tab.
- Added a preview for every kind of file, beside the chat and in the large view: code with colors and line numbers, text, pictures, SVG drawings, video and sound with their controls, and Word, Excel and PowerPoint files.
- Added the block "Performance" to the pages of the model, agent, cleanup and speech servers: tokens per second right now, the average of the last five minutes and its course as a line.
- Added the tab "Video" to the catalog; every kind now shows ten cards and every kind of accessory six.

### Phone

- Added the chat to the phone view: the history, the input bar, the sheets for attachments (Camera, Photos, Files) and models, the tool approval card, and a history that follows the end of the answer.
- Added the button "Tools" to the head of the phone view; it opens six tools of the desktop column and shows a dot while one of them works.
- Added models and servers to the phone view: the servers with their state, start and stop, the cloud providers, the catalog search, downloads with their progress, and the tools.
- Added the curated cards and the model detail to the catalog of the phone view, and every field of the speech server window to its page there.
- Added the Images area, swiping through the pictures of the viewer, the large server log, the job windows and the manual to the phone view.
- Added the settings to the phone view: a grouped list with a page behind each row.
- Added the terminal to the phone view, which opens as a sheet over the chat when you tap a tool call.
- We improved the Images area on the phone, which now has a page of its own, a mask page where one finger paints and two fingers move, and pinch, double tap and swipe for the pictures.
- We improved the head of the phone view, which shows the house mark and, on every inner page, the way back with the name of the page before.
- We improved the plus sheet of the phone chat, which now holds the model choice; the green dot before the model shows only while the model is reachable.
- We improved the labels of the phone pages, which say every word once: a server names its state once, its memory under Memory and its port under Network, and a cloud provider shows its key in one line.
- We improved the catalog on the phone, which lists its kinds as rows and names Hugging Face once.
- We improved schedules on the phone: the form opens as a sheet from the bottom edge, the details stand two by two, and the buttons are full width, 44 pixels high and visible in every design.
- We improved the input bar on the phone: its controls line up, and the new chat buttons are dimmed while they would change nothing.
- We improved the buttons of the phone view: the head carries a plus, Cancel and Save are two signs, and the pause switch has no color of its own.
- Fixed an issue where the phone view did not attach to an answer that was still being written.
- We improved the approval card on the phone, which now shows the file a tool call is about instead of its content.
- Added Snow to the phone view; "Auto" shows Snow on a light phone.
- Fixed an issue where the field for the bubble color kept the color of the old design when a phone on "Auto" turned light or dark.
- Added the three steps "Add to Home Screen" with pictures to the settings page "Web App".
- We improved the row "Web App" in the settings list, which now shows the version of the web app.
- We improved the settings page "Web App", which now stands in three columns with the QR code large in a tile of its own.

### Chat

- We improved waiting messages: a message typed during an answer now looks like its sent bubble, dimmed, with its pictures and documents, and on a touch screen a tap on its word shows the hint.
- We improved stopping an answer by hand: messages that wait come back into the input field, in front of what you have typed since, and the cross on a waiting bubble does the same for one message.
- We improved a message the service turns away, which now stays in line and goes out once the chat is free.
- Fixed an issue where a chat jumped while attached pictures loaded; their room is now kept from the start.
- Added a round button that takes you back to the end of the chat after you scrolled up.
- Fixed an issue where scrolling back down during a running answer never made the chat follow again; close to the end, it now follows again.
- Fixed an issue where the end of a running answer dipped at every new line and sprang back.
- We improved the foot of a running answer, which stays quiet until the first word appears.
- We improved the text of answers, which now shows nested lists, the start number of a list, continuation lines and task lists with boxes.
- We improved headings, quotes and code in answers: headings go down to the sixth level, quotes run over several paragraphs, code stays as written, and a wide table shows a thin scroll bar under the pointer.
- We improved the tool call rows of a chat, which now also carry the logo of the server that ran them and the name of the file the call is about.
- We improved long file names, which now wrap at slashes, hyphens, underscores and dots.
- We improved the model name in the input bar, which now uses the room the bar has left; in the narrow input bar the fixed thinking pill shows only the bulb, with the word in its tooltip.
- Added a sign in the head of the chat while a download runs; it stays after the window is reloaded.
- Fixed an issue where an answer that was attached again showed an activity before the stream named one.
- Fixed an issue where the cache share stood alone under an answer; a stopped answer now shows no speed and shows its line right after the stop.
- Fixed an issue where the dot on the line beside an answer sat off center, and the ring around today in the calendar was blurred on scaled displays.
- We improved the chat on touch screens, where buttons that otherwise show only under the pointer are now visible.
- We improved the chat by keyboard: the cross of a reference and the context ring can now be reached with the keyboard, and long names end with dots.
- We improved the notice card of a finished chat, which now shows its name and the beginning of its answer.
- We improved notices, which now begin under the head of the open page and under the bars of the Images area.
- Added a switch "Disable popups" that hides every notice card; the sound trial is now a loudspeaker button and the waiting notice is called "Waiting".
- Fixed an issue where a message on the empty start page was refused with "A response is already being generated" while another chat answered; chats now answer side by side.
- Added the switch for suspending your instructions to the plus menu of the input bar, where it can be set before the first message; it left the instructions page.
- Fixed an issue where a refusal of Claude showed as an empty answer; the chat and the CLI now say that the model declined, with the explanation of its maker where there is one.
- We improved the line under a stopped answer, which now says "This answer was stopped. Send a message to continue."
- Added a tick to the copy button of a code block: it shows for a second after the text is copied, also while the answer is still being written.
- We improved notices: a long sentence shows on two lines, every notice has the copy button of the code blocks, and a notice stays while the pointer is over it.
- We improved the files the model delivers: a page, a document or a code file now opens as a tab in the preview, and its card shows its kind.
- Added SVG files to the input bar: they can be dropped in as a document and opened from their card.
- Fixed an issue where a file card in the chat showed another size than the preview beside it.
- We improved the approval card of a command: the reason stands as one quiet line under the command, and the path it is about is marked in the command, in the window, on the phone and in the CLI.
- We improved the colors of the interface: links, the tick of the chosen model, chosen rows, the GGUF tag, the agent name in a report and the context bar now wear the text color of the design, and blue stays for states.
- We improved the focus ring, which now stands in the text color of the design.
- We improved the greeting on the start page, which now changes with every start.
- Added a grid for attached pictures: two or more stand two to a row across the chat column, and document cards stand in a row above your message.
- We improved the chat layout: it now starts with a 900 pixel column, 16 pixel text, 24 pixels between messages and pictures up to 512 pixels; code grows with the text, and the input bar is as wide as the column. Values you set yourself stay as they are.
- We improved your own messages in the design Exe, which now stand in a medium gray with light text.

### Context and models

- We improved the settings page "Local models", which now has a server head with the start button and its own port, the wired memory bar, the quick pick table and the parameters in two cards.
- We improved the head of local models, which shows the maker's logo of the chosen model and the count of the quick pick beside the title.
- We improved the server pages, which now each have one head with the start button and the server's own port; the second memory figure in the head is gone.
- We improved every memory card, which now shows the row "Wired Memory" with what the server's own model needs; for the speech model the projector is counted and named as at its start.
- Added the maker's logo, or the first letter, before each model file in the choice fields of the servers; sizes and speed use the decimal sign of the language, and Occamy files carry the Accio logo.
- Added the block "Voice sample" to the speech server page: record, play and delete; the parameters are folded.
- Fixed an issue where the embedding server did not start with its stored context, batch size, pooling, layers, threads, memory lock and parallel requests; its page now has a memory card and an advanced card with "Pooling" and "Batch size".
- Fixed an issue where a server page emptied when reading it failed; it now keeps its last answer and says why once.
- Fixed an issue where the model server page offered the setup before the service had answered; it now says "Loading" until then.
- Removed the sentence that said which chats the parameters of a model apply to.
- We improved the model's knowledge of Exe AI: it knows the storage folders and the folder each kind of file belongs in, can add an MCP server with the command line client, asks before a command starts that client, and loads the help skill first for a question about the program.
- We improved the memory, which now travels to cloud models and custom servers from the start, saves, changes and deletes without asking, and holds at most 3,575 characters.
- Added the fields "Wait for speech input" and "Speech input rounds" to the conversation settings of the speech server; a conversation that hears nothing now ends after the rounds you set.
- Fixed an issue where the server pages of a second Exe AI service on the same data folder showed its running servers as off; they now show them with port and model, and start and stop say "Another Exe AI service uses this data folder and holds its servers."
- Fixed an issue where a second Exe AI service on the same data folder ended the model servers of the first at its start.
- Fixed an issue where a cloud provider that refused the check said only "Saved, but not reachable"; the save mask, the table, the card and the phone page now show the provider's own reason.
- Fixed an issue where the heading of the provider list stood lower than the heading beside it on the cloud providers page.
- Added dropdowns for the KV cache, flash attention and the chat template on the chat server pages.

### Images and video

- We improved the image server, which now runs sd.cpp build 975 with the switches "Flash attention", "Direct convolution" and "Batched CFG"; an older sd.cpp is replaced by itself when Exe AI starts.
- Fixed an issue where SD 1.5 and SDXL drew a plain white picture on the Mac with sd.cpp build 975, and the SDXL Lightning LoRA drew noise; "Batched CFG" now starts switched off.
- Added FLUX.3 Klein, MOSS-Image and Iris-3B: they are recognized and get their kit and their start values.
- We improved Qwen-Image 2.1 Turbo, which now also starts with the sigma schedule of its documentation.
- We improved the live preview, which the image server now draws itself; only the noisy preview and a preview drawn by a tiny autoencoder alone still go through sd-cli.
- Added the tiny autoencoders to the VAE choice, only those of the model's own family, with the label "TAE (fast)"; the finished picture is decoded with the chosen one.
- Added "Repeats" and "Tile size" to upscaling, and "Final size", which says how large the picture will be before you start; only upscalers sd.cpp can read are offered, and a result over 8192 pixels goes through sd-cli.
- We improved enlarged pictures, which keep their factor and their new size with their values; the infos card shows both under "Upscaled".
- Fixed an issue where a picture that came into the Images area changed the chosen mode; now only the strength is set.
- We improved the image server page, which follows the order of its drawing; the values of a model sit in two cards, "Parameters" and "Model", and "Parts · n" counts its parts.
- Added a button that saves a model's values on the image server page, and a question before unsaved changes are thrown away.
- Added the block "Convert to GGUF" to the image server page, with an Imatrix switch that is stored and on from the start, and a table of the model files in the folder with their state.
- We improved the block for the image model, with its choice and a button to the catalog, and the folder under it.
- Added the tab "FP16" to the conversion block of the image server page: a model file whose weights are mostly BF16 is written again as FP16, with a progress bar and a cross to cancel.
- We improved converting to GGUF: a progress bar with a cross to cancel shows while a file is converted, the GGUF tag stands on the new file, and the model choices of the page list it at once.
- We improved the image server page: the values of a model stand at the top with a choice of the folder's models, the list of files is folded, and the maker's mark stands before every file.
- Added the marks of the picture and video makers to the list of files, the model choice and the catalog.
- We improved the studio's model choice, which offers only models whose parts are all there and names the missing part of the default model.
- Added "Frames" and "Frames per second" to the parameters of a video model; Wan 2.2 S2V shows only "Frames", since its rate is fixed.
- Added every part of the video families: the audio VAE and the connectors of LTX-2.3, the audio VAE of MiniMax-H3, "CLIP vision" for Wan 2.1 I2V and FLF2V and the audio encoder of Wan 2.2 S2V; they come with the download and are set from the folder.
- We improved the Wan models, which show and send a part only where the model takes it.
- Fixed an issue where an LTX-2.3 checkpoint without its own text encoder did not start; it now starts with Gemma and the parts of its folder.
- Fixed an issue where the studio started a family chosen by hand with the values of the family instead of those of its variant, such as Qwen-Image 2.1 Turbo with 20 steps instead of 8.
- Fixed an issue where a crashed image server left only a general sentence; the studio now shows the reason from its log, without progress bars.
- Fixed an issue where a saved part whose file was gone made every drawing fail; the field now shows "-" and the picture is drawn without it, and the upscaler can be set back to "-".
- Fixed an issue where a picture given to the model in the chat was painted over completely; it now goes out at the strength of the studio.
- Fixed an issue where draw_image drew silently with another sampler or scheduler when the model sent an unknown name; it now refuses and lists the valid names.
- Fixed an issue where the brush bar and the rows over the generation area ran under the zoom and the row of pictures in a narrow window.
- Fixed an issue where a long prompt let the prompt bar grow over the generation area; its fields now scroll inside.
- Fixed an issue where the search field of the studio's model choice covered the first entry of the list.
- We improved the head of a studio group, which stays on one line; the last seed is a button beside the dice.

### Model catalog and downloads

- We improved the catalog, where the maker's logo or picture now stands before every hit, accessory and card.
- Fixed an issue where catalog cards lost their facts and stretched while they loaded; a waiting download now shows in the file rows and the cards.
- We improved the catalog, which now calls the machine's memory "memory" instead of "VRAM".
- We improved the downloads page, which now shows the maker's logo, the download row of the catalog and a small Hugging Face mark.
- Fixed an issue where the catalog and the downloads said "empty" or "downloaded" before the service had answered.
- We improved the version rows of llama.cpp and sd.cpp: the builds stand as rows with a download button, "Installed" stands in green, and a failed download says why in red on the card and in the list of builds.
- Added an update sign to the version row of llama.cpp and sd.cpp: the first click only checks, the sign turns yellow when a newer build exists, and the second click downloads it.
- Fixed an issue where the download size of the sd.cpp build "cuda12" left out the CUDA runtime.
- Fixed an issue where the first row of the list stood higher than the head of the page beside it in the catalog and the downloads.
- We improved the server pages, where the lowest card of a column reaches the foot of the column.
- Added speaking models to the speech tab of the model search.

### Agents, jobs and schedules

- Fixed an issue where the background service played a sound for schedules, reminders and reached goals even with sounds switched off; it now follows the same switches and volume as the window.
- Fixed an issue where the agent sign stayed red after its notice was closed; closing the notice now counts as seen, and a run that still needs a look carries a red dot in the agents window.
- Fixed an issue where words were cut and buttons ran out of the schedule view in a narrow pane; its facts and buttons now wrap to its width.
- We improved the notifications of a schedule, whose parts are now joined by a hyphen.
- We improved the agents page: descriptions, sign buttons, tool marks, a form in two columns, a warning for command and web access, and "Delete" on the red button with a red question before it.
- We improved the cronjobs page: the month with its name, the choice of the day as a pop-up, and the scripts as tiles.
- We improved the agents and cronjobs pages, which lay themselves out by their own width; their bars stand in one column at every width.
- Fixed an issue where a single failed run was named in the plural in the sentence about a stopped schedule.
- We improved an unseen failure in the agents column, which now shows a red bar and a strong title, and the list opens down to it.
- We improved the head of a report, which shows the tile on top and the task in two lines with a fold.
- Fixed an issue where the first entry of the new task window did not mean the model of the field "Model for agents & cronjobs"; the window now shows only once the list of agents and the answers are there.
- We improved the schedule form, whose day opens a month to pick from and whose time of day opens a list of times; a typed time is read, and a wrong one is marked.
- We improved the month of cron jobs in the left bar, which now shows the calendar week.
- Added a thinking stage to agent files: an agent can name its own stage, and it runs through the chat's thinking switch.
- Added a fallback for runs: a run can switch to a cloud model you marked "Use for agents".

### Tools, files and MCP

- Added one sheet with every way to connect an MCP server: a key in a header, a sign-in through the browser or "Own app", with the redirect address shown to copy.
- Added the field "Own https redirect address" for providers that accept only an https address.
- Added hosted MCP servers without a sign-in, and keys sent in any header the server asks for.
- We improved the tools in the MCP sheet, which now read "active", "asks" or "inactive".
- We improved the MCP servers page: installed servers are cards and the others tiles under "Not installed", and a card names the keys that are missing.
- We improved the MCP sheet, whose buttons stand under both columns, and the question before removing a server, which names its card.
- Fixed an issue where a custom server that wants a sign-in through the browser looked connected; it now shows as disconnected.
- We improved the tools page, which follows its design: every built-in tool has its own mark, list_dir and create_folder show an open folder, and list and chosen source end on one line.
- We improved tools, which no longer have a color of their own: their marks and names stand in the text color of the design.
- We improved the tools file page: under "Keys" it shows only ".env", with a tick or a cross for each key written as ${NAME}, and the live list shows one row for each server with its tools as pills.
- Added a warning box over the field of a configuration or tools file that has an error.
- We improved the file pages: the fields run down to the foot of the page, and the answer after saving stands in the footer beside the two signs instead of above the chat.
- Fixed an issue where commands, scripts and MCP servers started by the model received the API keys of every provider; a server gets only the keys its entry names.
- Fixed an issue where a command of the model could speak to Exe AI's own service; such a command is now refused.
- Fixed an issue where a search for a word like "shutdown" or "systemctl" was refused as dangerous; these words now stop a command only where a command begins.
- Fixed an issue where the web search answered as if nothing was found when every search engine was down; it now says that the search did not run and why.
- We improved the manual and the help skill, which now describe the program as it is today: the settings groups, the signs of both bars, the storage locations, the keys, snapshots, standing permissions, agent limits and pictures in the chat.
- We improved the start of MCP servers: they start side by side behind the service, so the built-in tools are ready at once and each server's tools follow when it is ready.
- Fixed an issue where a preview document could not run eval, WebAssembly or blob workers.

### Settings and layout

- We improved empty values and an empty choice, which now show a hyphen, and the texts of the interface no longer use a long dash.
- We improved the settings sidebar, which is now one searchable list with a dot for each server, and says "No matches" when a search finds nothing.
- We improved the pages of local models, servers, the catalog, downloads and cloud providers, which now show the same settings list beside them.
- We improved the page "Appearance", which is now a row of design cards, and switches, which stand in white and gray.
- We improved the left sidebar, which opens 285 pixels wide; its foot holds five signs, the settings sign is a cog and the new project sign a plus.
- We improved the head of every settings page, with the page's sign in a box and the title in the normal weight.
- We improved the controls: parameters stand in two cards, every slider shows its whole track, large text fields have the frame of the other fields, and state words and error sentences stay readable in the light designs.
- Added an info mark with a sentence that explains the switches of notifications, skills, instructions and memory, and the cronjobs page.
- We improved the instructions page, which is reordered; "Cancel" and "Save" are two signs.
- We improved the memory switches, which are now called "Exe AI Memory" and "Send to cloud models and custom servers".
- We improved the skills page: sign buttons, the switch "Load skills automatically", a red question before deleting, and a changed shipped skill marked "User".
- We improved the shipped skill that explains Exe AI, which is now called help instead of hilfe, and the manual, which is called "Help" in the German settings list too.
- We improved the cloud providers page: a button in the head, a table of the providers, a card with the parameters and a pop-up to add a provider.
- We improved the catalog of a cloud provider, which now shows its models as rows with a search and a green tick for each model you use.
- We improved a cloud provider that does not answer, which now shows a quiet dot and "Not responding".
- We improved the wording of the interface, where texts now follow one list of words in both languages.
- We improved small details: large fields use the glass of the cards, the Hugging Face token field fills its row, the overview has a sign of its own, and the answer of an update check stands in its row.
- Added number fields to the sliders of the layout mode, so a value can be typed exactly.
- We improved the page of notifications: the group of sounds is called "Notification sounds", the test button is a loudspeaker, and the popup switches stand in a block of their own.
- We improved six settings pages (Appearance, Keyboard shortcuts, Instructions, Memory, Embedding server and Cleanup server), which now use the width of the window in columns of equal height.
- We improved the menu pages, which now fill their frame; the catalog shows five cards in a row, all of one height.

### App, updates and Windows

- We improved stopping the background service, which no longer needs the system tools ps or PowerShell.
- Fixed an issue where the window stopped reloading after the service had been restarted several times in a short while.
- Fixed an issue where the window kept playing the old sounds for hours after an update.
- Fixed an issue where the service left its servers running when the system asked it to end.
- Fixed an issue where a relative storage location was taken; it is now refused before anything is created, with "Enter an absolute folder path".
- Fixed an issue where a path in quotation marks was refused; every path in the interface is now shown with forward slashes.
- Fixed an issue on Windows where the voice answered "llama-tts not found" although the program lay beside the server.
- Fixed an issue on Windows where an orphaned server, the image server too, was never ended.
- We improved the fonts on Windows: code blocks and the terminal use the fixed-width font of the house; the manual shows Ctrl K beside its search.
- We improved the app window, which now runs on Electron 44.
- Fixed an issue where a web page in the browser could read the interface of Exe AI through another host name; the interface now answers only to the names of this computer.
- We improved the window on the Mac: the gray bar of the system is gone, and the three window buttons sit in the first row of the sidebar.

### CLI (still in development)

- Added /rollback, which restores files the model changed from snapshots of the working folder and keeps your own later changes apart; snapshots are switched on with /settings global.checkpoints.enabled true.
- We improved the speed of snapshots, which now read only the files that changed.
- Added /download image, which downloads image models together with their kit.
- Added the choice of the default image model to /server image; /image now says where to choose one when none is set.
- Added stopping a running answer by typing a new message in the CLI; while a tool runs, the message waits in the hint line, and Escape takes it back.
- We improved the light themes of the CLI, which are now readable at a contrast of at least 4.5:1, and the automatic theme now asks the Mac for its appearance.
- Fixed an issue where a file mentioned with @ at the end of a sentence was sent under the wrong name on Windows, so a picture could arrive as a document.
- Fixed an issue where a model with a very long name was found missing at every start of the CLI.
- Fixed an issue where the CLI did not name the text editor it could not start.
- Fixed an issue where the CLI tab in the window held back what you typed when it ran a program other than the Exe AI client.
- Fixed an issue where the CLI tab started before its box had its size.
- We improved the CLI tab, which keeps the Ctrl shortcuts of the page; outside the Mac, copy and paste stay with the browser. In the Images area on Windows, Ctrl+Y steps forward.
- We improved the tool lines of the CLI, which show the argument the call touches, in the text color of the theme.
- Fixed an issue where the CLI kept waiting for a service whose interface was missing; it now ends it and says why.
- We improved the CLI, which now runs full screen: the history scrolls alone above a fixed block, and a click on an address opens it.
- We improved the CLI tab in the window, which shows Exe AI in block letters also when it is too narrow for the whole mark.
- We improved snapshots, which are now also taken before tee, find -delete, rsync with a deleting option and scripts.
- Fixed an issue where exe without a command waited until its time limit when it had no terminal; it now ends at once and says why.

## 0.6.14 — Feature Update

### New

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
- We improved the line beside an answer, which now grows smoothly with the text and always ends at its mark: the mark keeps drawing itself without disappearing and stays still once the answer is done.
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
- Fixed an issue where a model could still save to the memory after the memory was switched off for it; it no longer gets the memory tool.
- Fixed an issue where a heading you wrote yourself in the memory file was turned into an entry; it now stays as you wrote it.

### Images and video

- We improved the Images area, which no longer belongs to a chat: it keeps its own picture, mask, model and values, draws without a chat and lists only its own pictures.
- We improved the Images area, which now opens with the hand tool and with the mask switched off; a mask that is switched off is neither shown nor sent.
- Fixed an issue where brush and eraser left marks while the mask was switched off.
- We improved the row of pictures in the Images area, which keeps the original picture on top, and the area now shows the resolution of the picture.
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
- Fixed an issue where a running job did not show how full its context is or how fast it thinks; it now shows both, as the chat does.
- Fixed an issue where a job on a model without a catalogue entry showed the name of its endpoint instead of the model's name.

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
