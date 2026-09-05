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
- Interrupt a long answer with the hotkey. (Voice interruption needs the openWakeWord mode.)
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
can be shown with the "Show reasoning" toggle. Destructive actions pause the reply with an
**Allow / Deny** card. "Speak replies aloud" plays the answer through the speaker. Voice turns you
say out loud appear in the same log (tagged *voice*), because GUI and microphone share one
conversation. The header shows the live state (idle, listening, thinking, speaking), the LLM
health, a **Listen** button (same as the hotkey) and **Stop** (interrupt speech).

**Settings tab.** A form over every commonly changed option (names, model profile, speech engines and
voice, activation mode and names, hotkey, VAD timing, chimes, tool safety, log level). Each row shows
whether the value is overridden on this machine and offers *reset to default*. **Save** writes the
changes to `config/local.yaml`; nothing is applied until you press **Restart assistant** (or
**Restart LLM + assistant** when the model profile changed). The page reconnects by itself, usually
in 10–40 s while models reload. The *Advanced* section edits `local.yaml` and the persona prompt as
raw text.

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
| `alveus trigger` | make the running assistant listen now (bind to a keyboard shortcut) |
| `alveus say "text"` | speak through the running assistant (falls back to local synthesis) |
| `alveus tools` | connect every MCP server and list tools (destructive ones marked) |
| `alveus devices` | audio devices (`wpctl status` on PipeWire) |
| `alveus doctor [--warm]` | environment health check; `--warm` also loads STT/TTS/wake word |
| `alveus wakeword-test [--seconds N]` | live openWakeWord scores |
| `alveus llm profiles` | table of LLM profiles and whether their weights exist |
| `alveus llm serve [--profile P] [--host H] [--port N] [--extra "…"]` | launch llama-server for a profile (what the service runs) |
| `alveus llm test [--prompt "…"] [--profile P]` | stream a quick reply |
| `alveus tts say "text" [--out file.wav]` | synthesize and play / save |
| `alveus tts voices` | list voices of the active TTS backend |
| `alveus stt test [--seconds N] [--file x.wav]` | record (or read a WAV) and transcribe |
| `alveus version` | version and repo path |

All commands read the same configuration; `-v` on `talk`/`chat`/`api` enables debug logging.

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

## Changing the voice (and the name)

```yaml
tts:
  kokoro:
    voice: am_michael     # a male voice -> the assistant calls itself Alveus
```

`alveus tts voices` lists the 28 Kokoro voices; `alveus tts say "…"` previews one after editing
the config. For a cloned voice, switch `tts.backend` to `chatterbox` and set `chatterbox.voice_ref`
to a clean 5–15 s WAV of the speaker.

## Using Alveus from other programs

Everything the voice loop can do is reachable over HTTP on `127.0.0.1:8765` while
`alveus talk` (or `alveus api`) runs — see [api.md](api.md). Examples:

```bash
curl -s localhost:8765/chat -H 'content-type: application/json' -d '{"text":"what time is it?"}'
curl -s localhost:8765/speak -H 'content-type: application/json' -d '{"text":"Dinner is ready","play":true}'
curl -s -X POST localhost:8765/trigger        # start listening (Wayland shortcut, phone, Stream Deck…)
```
