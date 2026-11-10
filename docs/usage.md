# Usage

## Talking to Alveus / Aurea

With the `alveus` service running (or `alveus talk` in a terminal) the assistant is always
listening for its names. There are four ways to start a turn:

| how | what happens |
|---|---|
| **"Aurea, what's the weather?"** (name + request in one breath) | the request runs immediately, no chime |
| **"Alveus."** (name alone, then pause) | a rising chime plays; speak your request; a 700 ms pause ends it |
| **ctrl+alt+space** | same as the name alone; press again to end early |
| **follow-up** within 8 s of a reply | just keep talking, no name needed |

Say either name; the assistant does not care which. It replies with the name that matches
its voice (Aurea for the default female Kokoro voice).

Tips for reliable recognition:

- Speak the name at the start (or the very end) of the sentence. Names buried mid-sentence are
  not treated as addressing.
- A short pause is required to end an utterance (`audio.vad.end_silence_ms`, default 0.7 s).
  If the assistant cuts you off, raise it; if it feels slow, lower it to ~500.
- Interrupt a long answer with the hotkey or the GUI Listen button: generation and speech stop and it listens to you. (Interrupting by voice alone needs the openWakeWord mode.)
- Destructive requests get a spoken question, e.g. *"I am about to delete path with
  {"path": "…"}. Should I go ahead?"* Answer "yes", "go ahead", "do it" — anything else cancels.

### Example requests by tool group

**System** – "how hot is the GPU?", "how much memory is free?", "what's eating the CPU?", "is
there a process called zoom?", "kill process 4242" (confirmed), "which of my services are
running?", "restart the alveus-llm service" (confirmed), "what's my IP address?",
"suspend the computer" (confirmed), "lock the screen".

**Files & shell** – "what's in my Downloads folder?", "find all PDFs under Documents", "search
my repo folder for the word hypothalamus", "read the README in ~/local/repo/SAEM", "create a
file notes.txt on the desktop with today's plan", "run `nvidia-smi`", "how big is my home
directory?" (runs `du`).

**Desktop** – "open Firefox", "launch the terminal", "open ~/Downloads", "open github.com",
"volume to 30 percent", "turn it up a bit", "mute", "unmute", "pause the music", "next track",
"what's playing?", "take a screenshot", "switch to dark mode", "enable do not disturb", "copy
'hello world' to the clipboard", "what's on my clipboard?", "notify me: stand up in 20 minutes"
(shows a desktop notification now — it has no timer yet), "focus the Firefox window", "type
'hello' into the current window", "press ctrl s".

**Web** – "weather in Boston tomorrow?", "search for the latest CUDA toolkit release", "search
the news for Neuralink", "summarize https://example.com/article".

**Coding (opencode)** – "in ~/local/repo/SAEM, what does the training loop do?", "in
~/local/repo/foo, add type hints to utils.py and run the tests" (opencode edits files; can take
minutes), "what's the git status of ~/local/repo/alveus-ai?".

**Conversation** – anything else: explanations, drafting text, maths, planning. The model is
Bonsai-27B (Qwen3.6-derived); expect solid general knowledge with a 1-bit quality trade-off.

## Browser GUI

While the assistant runs (service, `alveus talk`, or `alveus api`), open **http://127.0.0.1:8765/**
or run `alveus ui`. The page is served by the assistant itself and is reachable from this machine
only.

**Chat tab.** Type a request (Enter sends, Shift+Enter for a newline). Replies stream in; tool calls
appear as expandable chips above the answer with their arguments and results; the model's reasoning
can be shown with the "Show reasoning" toggle (it is on by default). Reasoning appears for typed and spoken turns alike, and it is kept with the conversation, so it is still there after a page reload. Local models never see their old reasoning again; cloud models that need it get their own back (DeepSeek, and Claude and ChatGPT in the provider's signed or encrypted form). Destructive actions pause the reply with an
**Allow / Deny** card. "Speak replies aloud" plays the answer through the speaker. Voice turns you
say out loud appear in the same log (tagged *voice*) and stream live, with their tool cards and any
question asked aloud ("I am about to … Should I go ahead?"), because GUI and microphone share one
conversation. The header shows the live state (idle, listening, thinking, speaking) and the LLM
health. Next to the message box, **Listen** starts a voice turn (same as the hotkey); pressed while it is thinking or speaking, it cuts that reply off first. While a reply
is running the **Send** button turns into **Interrupt**, which stops generation, skips pending tool
calls, cuts speech and denies any open confirmation. Under each answer: **Copy**, **Speak** (say it
again), **Stop** (stop speaking) and **Retry** (ask the same question again).

**Header buttons.** **■ Stop** cuts speech. **↻ Restart** restarts the assistant service (the
conversation is cleared, the LLM server keeps running). **⏻ Power** opens a menu to stop the
assistant, the LLM server, or both; each asks for confirmation. Stopping the LLM server alone frees
its VRAM for ComfyUI while the page stays up (the LLM light turns red until the server is started
again). Stopping the assistant takes this page with it: an overlay shows the `systemctl --user
start` command, and the page reloads by itself once the assistant is back. Nothing restarts from
the overlay, so start the services from a terminal (or log in again, as both units are enabled).
The Restart and Power buttons appear only when Alveus runs under systemd.

While a reply streams in, the log follows the newest text only as long as you are at the bottom. Scroll up to read
earlier parts and it stops following; a **↓ newer messages** button appears and takes you back, or scroll to
the bottom yourself. Your own messages and confirmation questions always scroll into view.

**Commands that need sudo.** Any shell command using `sudo` is held until you allow it. The
confirmation card shows a password field: enter your password and press **Allow once**. The
password is handed to that one `sudo` on its standard input and is neither stored nor logged (it
travels only over the local loopback connection to the assistant process). Leave the field empty
if your account has passwordless sudo. A voice request that needs sudo says so aloud and shows the
same card in the browser, since a password cannot be spoken.

**Settings tab.** The form follows how the parts depend on each other. A choice (speech engine,
voice engine, model, wake mode, language-model provider) shows its options as cards with one line
each; the chosen option's own settings open in a panel right below it, and inside that the next
level: *Voice → Chatterbox → Multilingual → voice to copy, gender, language*. Settings that belong to
one model are stored for that model only (`<engine>.models.<model>.…`), so you can give Turbo one
voice and Multilingual another, and switching back restores them. Each row has a one-line hint;
*More* opens the details. Rows changed on this machine say *changed · reset*; reset removes the
machine's value, after which the inherited one applies (the engine's setting, or the default).

- **Language model:** pick where the model runs (this computer, Anthropic, OpenAI, DeepSeek,
  OpenRouter, or your own vLLM / Ollama / OpenAI-compatible server), then the model. For this
  computer the list is the GGUF files in the models folder (`$ALVEUS_MODELS/llm`, one folder per
  model); drop another file there and it appears. Models with a profile show its alias (e.g. *Qwen3.8
  27B · coder merge*), editable as *Name in the list* in that model's settings. For cloud providers it is the provider's live list once the key is in, otherwise a
  short suggested list; *another model id…* takes anything. Each model keeps its own settings
  (thinking, reasoning effort, reply length, temperature, context length for local models), shown only
  where that provider supports them. Picking a model that was never set up creates its profile on save
  (e.g. `deepseek-flash`). The API key field sits in the provider's panel and saves at once.
- **Pickers instead of typing:** microphones and speakers come from PipeWire; languages by name;
  Kokoro voices with accent and gender; ▶ plays a Kokoro voice (while Kokoro is the running engine)
  or the recording a Chatterbox or Qwen3-TTS model copies; *Record* captures a keyboard shortcut.
- **Saving applies right away, without a restart, and the conversation continues.** Voices, voice
  samples, speed, expressiveness, languages, names, model settings and switching between models,
  listening timing, wake-word names and sensitivity, the keyboard shortcut and the instructions take
  effect immediately. Another voice or speech-recognition engine or model is loaded first, swapped in,
  and the old one freed (a few seconds; nothing is kept loaded in advance); a different local language
  model restarts only the LLM server (20–40 s). Only tool servers, audio devices and the web address wait
  for a restart; the page then says which and offers the restart button. Changing the model first runs a
  check (local: a load test of the weights, 5–40 s; cloud: whether the key and model are accepted); if it
  fails, nothing is saved. Leaving the page with unsaved changes asks first. The *Advanced* section edits
  `local.yaml` and the instructions as raw text (both also applied right away).
- **Personality:** Assistant → Personality picks how it sounds: *Calm* (warm, steady, the default),
  *Sweet* (honest, close, a little whimsical), *Tsundere* (teasing and prickly outside, caring
  inside), *Genki* (upbeat, attentive, offers the next step). The panel below the cards edits the
  chosen one's name, description and words; *Save as new…* keeps the words as another personality,
  *Restore original* undoes your edits to a shipped one, *Delete* removes one of your own. What it may
  do, the shape of its replies and the confirmations are in the instructions and stay the same for
  every personality.
- **Listening to voices:** ▶ next to a Kokoro voice speaks a sample sentence, and ▶ next to a
  Chatterbox voice plays the recording it copies, both on the assistant's speaker (in the browser when
  there is no speaker, e.g. `alveus api`). Kokoro previews need Kokoro to be the running engine.

**On another machine.** After `./install.sh` there, the GUI is available the same way at
`http://127.0.0.1:8765/` whenever `systemctl --user start alveus`, `alveus talk`, or `alveus api`
(GUI without microphone) is running; `alveus ui` opens it in the default browser. To reach a remote
machine's GUI from your laptop, tunnel the port rather than exposing it:
`ssh -L 8765:127.0.0.1:8765 user@that-machine`, then browse to `http://127.0.0.1:8765/` locally.

## Text mode

```bash
conda activate alveus
alveus chat                  # REPL with tools; /tools lists them, /reset clears history, /quit exits
alveus chat --speak          # replies are also spoken
alveus chat --show-thinking  # print the model's reasoning stream in grey
alveus chat --no-tools       # pure conversation
alveus chat --profile bonsai-ternary
```

In text mode destructive confirmations are terminal `[y/N]` prompts.

## CLI reference

| command | purpose |
|---|---|
| `alveus talk [-v] [--no-api] [--profile P]` | full voice assistant + HTTP API |
| `alveus chat [--speak] [--no-tools] [--show-thinking] [--profile P]` | text REPL |
| `alveus api` | HTTP API only (no microphone), for other frontends |
| `alveus ui` | open the browser GUI of the running assistant |
| `alveus handbook [--rebuild]` | open the offline documentation (`docs/handbook.html`) |
| `alveus trigger` | make the running assistant listen now (bind to a keyboard shortcut) |
| `alveus say "text"` | speak through the running assistant (falls back to local synthesis) |
| `alveus tools` | connect every MCP server and list tools (destructive ones marked) |
| `alveus devices` | audio devices (`wpctl status` on PipeWire) |
| `alveus doctor [--warm]` | environment health check; `--warm` also loads STT/TTS/wake word |
| `alveus wakeword-test [--seconds N]` | live openWakeWord scores |
| `alveus llm profiles` | table of LLM profiles: provider, protocol, local/cloud, and whether the weights or the API key are present |
| `alveus llm key NAME [--remove]` | store an API key (asked without echo) in `~/.config/alveus/secrets.env` |
| `alveus llm serve [--profile P] [--host H] [--port N] [--extra "…"]` | launch llama-server for a profile (what the service runs); exits 0 for profiles without a local server |
| `alveus llm test [--prompt "…"] [--profile P] [--show-thinking] [--thinking/--no-thinking]` | stream a quick reply (one paid request for a cloud profile) |
| `alveus tts say "text" [--out file.wav]` | synthesize and play / save |
| `alveus tts voices` | list voices of the active TTS backend |
| `alveus stt test [--seconds N] [--file x.wav]` | record (or read a WAV) and transcribe |
| `alveus version` | version and repo path |

All commands read the same configuration; `-v` on `talk`/`chat`/`api` enables debug logging.

## Starting and stopping

Both services are **enabled**, so after a reboot (or logging in) they start by themselves: the LLM
server first, then the assistant with its GUI at `http://127.0.0.1:8765/`. Allow about a minute for
the models to load. Nothing needs to be typed.

```bash
systemctl --user stop alveus alveus-llm      # stop everything
systemctl --user start alveus-llm alveus     # start everything
systemctl --user restart alveus              # restart only the assistant (after config changes)
systemctl --user status alveus alveus-llm    # current state
journalctl --user -u alveus -f               # live log
systemctl --user disable alveus alveus-llm   # turn off autostart (enable to turn it back on)
```

## Running as a service vs. by hand

The systemd units start both the LLM server and the assistant at login. To iterate manually,
stop the assistant unit first so two instances do not both answer the microphone:

```bash
systemctl --user stop alveus
alveus talk -v
systemctl --user start alveus
```

The LLM unit can stay running; `alveus talk`, `alveus chat` and opencode all share it.

## Switching the model

```bash
# one-off
ALVEUS_LLM_PROFILE=bonsai-ternary alveus llm serve      # in one terminal
ALVEUS_LLM_PROFILE=bonsai-ternary alveus chat            # in another

# permanent: config/local.yaml
llm:
  profile: bonsai-ternary
# then: systemctl --user restart alveus-llm alveus
```

The Ternary model is ~7 GB (vs 3.8 GB), keeps ~95 % of full-precision quality (vs ~90 %) and
scores higher on tool use; generation is somewhat slower.

Cloud models work the same way: `ALVEUS_LLM_PROFILE=claude alveus chat` for a try (the key must
be set first, see [backends.md](backends.md#api-keys)), or choose `claude`, `chatgpt` or `deepseek`
in Settings → Language model → Model profile, where the key fields are right below. Saving checks
the key and model, then restarts both services; `alveus-llm` stops by itself because a cloud
profile needs no local server, and the assistant keeps it stopped at every start until you choose
a local profile again. The last chosen profile is what starts after a reboot. Everything said in the conversation, and what the tools read for
it, then goes to that provider. To add your own (another model, OpenRouter, a vLLM box on the
network), add a profile; the keys are described in [configuration.md](configuration.md#llm).

## Changing the voice (and the name)

```yaml
tts:
  kokoro:
    voice: am_michael     # a male voice -> the assistant calls itself Alveus
```

`alveus tts voices` lists the 28 Kokoro voices; `alveus tts say "…"` previews one after editing
the config. For a cloned voice, switch `tts.backend` to `chatterbox` (or `qwen3`) and set
`chatterbox.voice_ref` (`qwen3.voice_ref`) to a clean 5–15 s WAV of the speaker.

**Voices that come ready to copy** (this machine's `voices/`, details and terms in `voices/SOURCES.md`),
all female, each with its words in a `.txt` file:

| file | voice | from |
|---|---|---|
| `f_ayaka_ja` | Ayaka (朱花), Japanese; cheeky, tsundere-style | AI声優-朱花 official sample (free use; credit "AI声優-朱花" if you publish) |
| `f_hina_ja` | Hina, Japanese; high, soft, a little wistful | japanese-anime-speech (CC0) |
| `f_yuzu_ja` | Yuzu, Japanese; high and playful | japanese-anime-speech (CC0) |
| `f_mio_ja` | Mio, Japanese; gentle, mid pitch | japanese-anime-speech (CC0) |
| `f_shiori_ja` | Shiori, Japanese; lower, calm, polite | japanese-anime-speech (CC0) |
| `f_feiyu_zh` | Feiyu (大肥鱼), Chinese; young, warm, caring | da-fei-yu-girl-voice-zh (CC-BY-NC 4.0) |

They copy best with Qwen3-TTS, which speaks all of them in English too; Chatterbox Multilingual
copies them as well. With your own recording, *Write it down* (Settings → Voice → Qwen3-TTS → Its
words) saves what it says so Qwen3-TTS can copy it closely.

## Speaking other languages

1. Settings → Voice: engine *Qwen3-TTS* (10 languages) or *Chatterbox* → *Multilingual* (23), spoken
   language *automatic* (or fix one, e.g. `zh`).
2. Settings → Speech: clear *Spoken language* so Whisper detects the language you speak.
3. Save, restart. Speak Chinese (or German, Japanese…) and the assistant hears, thinks and answers in
   that language; each sentence is voiced in the language it is written in, so mixed replies work.
   The wake names still have to be said as "Alveus"/"Aurea" (add local spellings to *Name aliases*
   if Whisper writes them differently in your language).

## Using Alveus from other programs

Everything the voice loop can do is reachable over HTTP on `127.0.0.1:8765` while
`alveus talk` (or `alveus api`) runs — see [api.md](api.md). Examples:

```bash
curl -s localhost:8765/chat -H 'content-type: application/json' -d '{"text":"what time is it?"}'
curl -s localhost:8765/speak -H 'content-type: application/json' -d '{"text":"Dinner is ready","play":true}'
curl -s -X POST localhost:8765/trigger        # start listening (Wayland shortcut, phone, Stream Deck…)
```
