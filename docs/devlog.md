# Development log

History and plans in one place. Newest entries first; each entry says what changed, why, and what was
learned. Commit hashes refer to `git log`. The **Plans** section at the top is the roadmap; AGENTS.md,
README and development.md point here instead of keeping their own copies.

## Plans (in priority order, agreed with the owner)

1. **Conversations and memory.** Persist conversations (list, resume, search), summarize long ones,
   and give the agent a memory store it can read and write across restarts (facts, preferences).
   Likely an MCP server plus a sidebar in the GUI; today history lives only in `Agent.history`.
2. **Image generation through ComfyUI.** ComfyUI is installed and running (see 2026-09-10) but not
   wired to Alveus. Design: `mcp_servers/comfy.py` exposes each exported workflow in `config/comfy/` as
   one tool with a few parameters (prompt, size, seed, steps), driven by a manifest that maps
   parameters to node inputs by node *title*. It POSTs `/prompt`, polls `/history/<id>`, fetches the
   image via `/view` or copies it from ComfyUI's own output folder (`~/local/lib/ComfyUI/output`,
   the default; the service no longer passes `--output-directory`) into Alveus's image folder
   (`~/local/data/alveus-ai/images`) and opens it with the desktop tool. Both paths are settings
   (`images.comfy_output` and `images.dir`, editable in the GUI) so the GUI's own renders stay in
   ComfyUI's folder while Alveus-made images live with the other Alveus data. VRAM rule: Z-Image and SDXL fit next to the LLM; FLUX.1 dev and FLUX.2 klein 9B need
   `alveus-llm` stopped for the render (then restarted) or a clear failure; free ComfyUI's memory
   after every job (`POST /free`). Later: `scripts/install_comfy.sh`, image-to-image, showing the
   image in the GUI.
3. **Vision input and video.** Bonsai's `mmproj` tower via llama-server `--mmproj` (screenshots,
   camera), video understanding and generation, each a pluggable backend like STT/TTS.
4. **Interrupt by speech.** (1) PipeWire echo cancellation (`module-echo-cancel`) so the mic no
   longer hears the assistant; select the cancelled source as `audio.input_device`; verify by
   recording while it speaks. (2) Name-triggered barge-in while speaking (the custom wake-word models
   already run during playback, so this is mostly tuning once echo cancellation works). (3) Optionally
   any-speech interruption.
5. **Wake-word tuning.** The trained models score the owner's voice at only ~0.25 (threshold 0.5)
   while the synthetic voices score 0.9. Options: retrain with a phonetic spelling that matches how the
   owner says the names (`scripts/train_wakeword.sh "al vay us" alveus`), add "hey Alveus" variants,
   or lower the threshold to ~0.25 and accept some false wakes. Sample clips of the trainer's
   pronunciation are in `~/local/model/wakeword/samples/`.

Smaller ideas: timers/reminders (`systemd-run --user --on-active` or an in-process timer that calls
`/speak`), Home Assistant, speaker identification, a reasoning on/off toggle (`thinking:` per
profile is a one-line patch; `llm.effort` exists for cloud models, local ones only have
llama-server's `--reasoning-budget`). LLM layer follow-ups (see 2026-11-07): a live run of each
cloud profile once keys exist, switching profiles without a restart, a Gemini preset.

## 2026-11-07 (night) — a confirmation that never heard the answer; settings apply without a restart; previews on the speaker

- **"Close it" was asked although the model chose not to ask, then counted as declined.** From the saved
  history (DeepSeek Flash): the model reasoned that closing a window it had just opened needs no
  question and called `desktop__close_window`; the agent's destructive gate asked anyway (by design:
  `close_window` is marked destructive, and the gate does not depend on the model). The spoken
  question was six seconds of raw JSON ("close window with {title_substring: Firefox}"); listening
  started at 03:25:22 and ended at 03:25:23 with no transcript: a sound shorter than `min_speech_ms`
  (the tail of its own question or a clipped answer) started a "speech" that 0.7 s of silence then
  ended, and `rec is None` was returned as `False`, so the model was told "the user declined, do not
  retry". Fixes: plain-words descriptions (`describe_action`: "close window: Firefox"), a chime before
  listening, a 0.15 s settle, `patient` recording (blips below `min_speech_ms` do not end the window),
  yes/no/unclear parsing with one repeat, and silence reported as `no_answer` (the model may ask again)
  instead of a refusal. GUI confirmations that time out are `no_answer` too. New `tools.no_confirm`
  (GUI: Don't ask for these) for risky tools the owner trusts; shell commands and sudo always ask.
  A unit test reproduces the old failure with a 64 ms click before the answer.
- **Previews could not be heard.** The endpoint answered in 0.2–1.2 s and a simulated click in a clean
  headless Chrome played; the owner's Chrome did not, cause unknown (tab or site sound, autoplay).
  ▶ now plays on the assistant's own speaker (`POST /tts/preview` with `play`, `POST /voices/play` for
  Chatterbox recordings), which is also what the voice will sound like; the browser is the fallback when
  there is no speaker. Each preview is logged.
- **Restart-free settings.** `alveus/live.py` applies a saved configuration to the running process
  (GUI and YAML editor send `apply: true`): instant for names/persona/gender, model settings and
  switching profiles (new adapter; the history is provider-neutral, so the conversation continues),
  engine settings that `reconfigure()` takes in place (Kokoro voice/speed/accent on the loaded model,
  Chatterbox sample/expressiveness/language, Whisper language), VAD, wake names and sensitivity,
  the hotkey, log level; reload-and-swap for another engine or model (load the new one, swap, free the
  old; nothing preloaded); tool servers, audio devices and the API address are reported as restart-only.
  Persona saves rebuild the system prompt at once. Verified on an isolated instance: voice and speed
  changed in the running process, a microphone change reported for the restart. 74 tests.

## 2026-11-07 (evening) — settings page redesigned as a tree; a model choice per provider; per-model settings

- **Review (owner asked for one, with UX in mind).** Findings on the old page, worst first:
  (1) dependent fields never hid: `.field{display:grid}` beat the `hidden` attribute, so all three
  speech-to-text and all three voice engines' options showed at once (same bug hid nothing in the
  save bar); (2) flat where the settings are nested: engine → model → that model's voice, folder,
  gender and language, with gender and voices folder global although only one engine used each;
  (3) no way to pick a model within a provider (DeepSeek Flash, Claude Sonnet, a new GGUF): only
  predefined profiles; (4) typing where picking is possible: device names from `wpctl status`,
  language codes, `af_bella`-style voice ids, pynput shortcut syntax; (5) a paragraph of hint under
  every row (the page was 9,000 px); (6) no way to hear a voice before choosing it; (7) Kokoro's accent
  was a separate setting that silently mismatched British voices; (8) save, then a separate restart
  button, with nothing saying what a change restarts.
- **New structure.** `SECTIONS` is a tree: choices render as cards with one line each, and the
  chosen option's own settings open in a nested panel, recursively (Voice → Chatterbox → Multilingual
  → voice to copy / gender / language). Model-specific values are stored under
  `<engine>.models.<model>` and resolved by `config.engine_opts()` (engine block < model block, with
  `tts.voices_dir` / `tts.voice_gender` as fallbacks); every model keeps its own. Sections: Assistant,
  Language model, Listening, Voice, Activation, Audio, Tools & safety, System, Advanced.
- **Language model.** Provider cards (this computer, Anthropic, OpenAI, DeepSeek, OpenRouter, vLLM,
  Ollama, other server; key status on each), the API key in the provider's panel, then a model list
  from `GET /llm/models` (GGUF files under `ALVEUS_MODELS`; the provider's live list with a key, else
  suggestions; *another model id…*), then that model's settings, shown only where the provider
  supports them (`PROVIDER_INFO`: effort levels, thinking switch, sampling; context length and top-k
  for local files via `serve.context`). Picking an unknown model creates its profile on save; the
  preflight checks unsaved profiles too (`definition`).
- **Pickers.** PipeWire devices (`GET /audio/devices`), languages by name, Kokoro voices with accent
  and gender, ▶ for a Kokoro sample (`POST /tts/preview`, any accent on the loaded model) and for
  the Chatterbox recording (`GET /voices/file`), *Record* for the shortcut, the automatic gender shown
  with its reason. Kokoro's accent now follows the voice (`lang_code: null`).
- **Saving.** One *Save & restart* (restarts the LLM server too when the model changes), *Save
  without restart*, a warning when leaving with unsaved edits, *changed · reset* per row (reset =
  use the inherited value). One-line hints with *More*; the page is ~6,500 px with everything open.
- **Verified** on a text-only instance with its own `local.yaml` copy (`ALVEUS_LOCAL_CONFIG`, new) and
  `INVOCATION_ID` unset, in headless Chrome over DevTools: no JS errors; engine/model switching shows
  the right nested settings; a Chinese language set for Chatterbox Multilingual lands in
  `tts.chatterbox.models.multilingual.language`; picking DeepSeek Flash with low effort saved a new
  `deepseek-flash` profile after a passing preflight, and one real request with it succeeded; the
  local list shows both GGUF files and the missing Qwen file; Kokoro preview of a British voice
  while an American one was loaded (3.4 s WAV); path traversal on `/voices/file` refused; phone width
  without horizontal scroll; light theme. 65 tests.

## 2026-11-07 (later) — first live cloud runs (DeepSeek); the local server follows the profile; key hygiene

- **Live DeepSeek.** With the owner's disposable key (entered by them; never seen by the session):
  `alveus llm test --profile deepseek` with thinking on (reasoning streamed to the GUI channel) and
  `--no-thinking` (`thinking: {type: disabled}` accepted, no reasoning returned); a two-turn
  `alveus chat --profile deepseek` with a tool call in each turn (the second turn carries the first
  turn's `reasoning_content`, which DeepSeek demands); one turn through the running assistant.
  Replies took 2–5 s per turn including the tool round. About a dozen requests in total; the
  account showed $17.56 afterwards (`GET /user/balance`).
- **Gap found and closed.** The owner had switched to DeepSeek and restarted only the assistant
  (old code), so llama-server kept ~10 GB of VRAM. Now `alveus/llm/service.py` runs first in
  `VoiceAssistant.start()`: a profile without `serve:` stops `alveus-llm`, a local profile starts it
  if down and restarts it if it serves another model (`llm.manage_local_server`, default on;
  skipped for `--profile` overrides because the unit serves the saved profile). Verified on the
  real services: local → DeepSeek (restart both) and DeepSeek → local → DeepSeek with
  assistant-only restarts; GPU memory 13.9 GB → 3.7 GB, and the profile survives restarts because
  it is saved in `config/local.yaml`. `--no-block` systemctl calls, since the caller is itself a unit.
- **Key hygiene.** AGENTS.md has a rule section for sessions (never read the key file or dump
  environments, check keys only by source, warn before paid test series). The files/shell tools
  refuse `~/.config/alveus/` (read, list, find, search, and shell commands naming it). The
  `anthropic` and `httpx2` loggers are held at WARNING like `openai`/`httpx`, so DEBUG logs do not
  copy whole conversations. Fixed `--show-thinking` and the tool lines in `alveus chat` / `llm
  test` printing literal `[dim]` tags.

## 2026-11-07 — swappable language model: providers, three protocols, cloud keys (branch `llm-providers`)

- **Why.** The owner wants the central model swappable: the local Bonsai server today, but also
  cloud APIs (DeepSeek, ChatGPT, Claude) or another local model (Qwen 3.8 27B), without code changes.
  The old layer was one OpenAI-compatible client, which cannot serve Claude, nor current OpenAI
  models (they call tools only through the Responses API).
- **Design.** A profile is now a *provider* plus a *model*. Providers are presets
  (`alveus/llm/providers.py`: protocol, address, key variable, quirks, parameters the provider
  rejects), not classes; resolution is preset < llm-level defaults < profile. One adapter per wire
  protocol: `openai_chat` (llama-server, vLLM, Ollama, DeepSeek, OpenRouter, anything compatible;
  the old client, extended), `openai_responses` (OpenAI, stateless `store: false`, encrypted
  reasoning replayed), `anthropic_messages` (Claude via the official `anthropic` SDK, adaptive
  thinking with summaries for the GUI, prompt caching, server-side refusal fallback). The agent's
  history stays provider-neutral; whatever a provider needs back verbatim (Claude's signed thinking
  blocks, OpenAI's reasoning items) is stored per message as `_replay` and only that provider's
  adapter reads it. Old `backend: openai` profiles keep working.
- **Agent changes that every provider needed.** Normalized finish reasons; a tool call cut off by
  the output limit is never run, and both that case and the tool-round limit now answer every
  pending call (a dangling `tool_use` is a hard error for Claude and OpenAI); a refusal without
  text is reported; `LLMError` messages are short enough to be spoken.
- **Keys and privacy.** Keys live in the environment or `~/.config/alveus/secrets.env` (mode 600,
  outside the repo), set in the GUI (write-only fields right under the profile) or with
  `alveus llm key`. They are read per request (no restart), never exported to `os.environ`, and
  API-key variables are stripped from tool servers' environments except the coder's
  (`inherit_api_keys`). Docs and the GUI hint state plainly that a cloud profile sends the
  conversation, tool results included, to the provider.
- **Services.** `alveus llm serve` exits 0 for a profile without `serve:`, so choosing a cloud
  profile stops `alveus-llm` and frees the GPU; `/health` only reports the unit for local-server
  profiles, and the GUI preflight checks key and model for cloud profiles instead of loading weights.
  The coder's `auto` follows cloud profiles too (`anthropic/claude-opus-5-5` in opencode terms).
- **Learned.** DeepSeek returns HTTP 400 unless earlier `reasoning_content` is sent back once tools
  are involved (preset `reasoning_replay: all`), and its thinking switch is `thinking: {type}` plus
  `reasoning_effort`. Claude's thinking signatures cover everything before them, so trimming old
  turns invalidates them: the agent drops that replay data when it trims (`prefix_bound`) and the
  messages are rebuilt without thinking. The current Anthropic API version rejects
  `temperature`/`top_p`/`top_k` on every model, and Claude Opus 5.5 cannot turn thinking off
  (only `effort`, default `medium`); its notes between tool calls arrive as thinking blocks, which
  `display: summarized` makes visible in the GUI. OpenAI's flagship ids are now `gpt-6*`.
- **Verified.** 51 tests (adapters against recorded-style streams, including the SDK through a mock
  transport and an interrupted Claude stream closing its connection). Local end to end: `alveus chat`
  with tools on Bonsai through the new adapter. A text-only API instance on port 8799: key storage
  (file mode 600, values never returned), and the preflight against the real Anthropic, OpenAI and
  DeepSeek endpoints with a deliberately invalid key (each answered 401 and produced a readable
  message, which also confirms the URLs). GUI rendered in headless Chrome over the DevTools
  protocol: no JS errors, labelled profiles, effort choices, key rows. **Not verified:** an actual
  generation from any cloud model; no keys are stored on this machine yet.
- **Not done on purpose.** The Qwen 3.8 27B weights were not downloaded (profile `qwen-local` points
  at the expected path); opencode's `bonsai` provider would need that model id added for `auto`.

## 2026-09-11 — reasoning for spoken turns and across reloads

- The GUI showed the model's reasoning only for turns typed into the page: `VoiceAssistant.respond`
  (spoken turns, and `/chat` with `speak`) never published reasoning deltas, and `/history` had no
  reasoning at all, so a reload dropped every reasoning block. Now the agent keeps each assistant
  message's reasoning under a private `_reasoning` key in `Agent.history` (the LLM client strips
  keys starting with `_` before sending, so the model never re-reads its own thoughts), `/history`
  exposes it as `reasoning` per turn, the voice path publishes `assistant_reasoning` events, and the
  page renders all three sources through one `thinkBlock()` helper. Tests cover the normalisation
  and the payload stripping. Note for the record: llama-server itself always returned
  `reasoning_content`, with and without tools; the drop was entirely in Alveus.

## 2026-09-10 (evening) — persona against false refusals; GUI power menu

- `config/persona.md` gained a paragraph stating the setting Bonsai (Qwen3.6 post-training) is
  missing: a private machine, an adult owner and administrator as the only user, requests are their
  own decisions; no refusals, hedging, disclaimers or moralizing; comply the first time. The owner's
  earlier line ("comply when asked repeatedly or with a strong tone") was dropped because it implied
  the first ask may be refused. Next levers if a hard refusal remains: prefill the assistant turn
  in `Agent.run`, then abliterated weights. Persona edits apply after an assistant restart (383fe3b).
- GUI header: **⏻ Power** menu to stop the assistant, the LLM server, or both, via the new
  `POST /services/stop` (`what: assistant | llm | both`, systemd only, detached `systemctl --user
  stop`). Stopping the assistant shows an overlay with the start command and polls `/health` until
  the service is back; other open tabs get the same overlay through the `stopping` SSE event.
  The "Stop LLM" case exists for ComfyUI: the 24 GB card cannot hold Bonsai and a 20 GB image
  model at once. Verified with headless Chrome (menu opens, Escape closes, screenshot).
- ComfyUI's service dropped `--output-directory`: renders from the ComfyUI GUI land in its default
  `~/local/lib/ComfyUI/output` again. Decision: when Alveus generates images it copies the result
  into its own folder; both paths become editable settings once the image tool exists (plan 2).
- Persona: the speaking-style paragraph now asks for conversational speech (everyday words,
  contractions, answer first, varied openings, no filler, items strung into a sentence, numbers
  said aloud, tool results described in plain terms, one short question when ambiguous). The
  "always introduce yourself" wording became "introduce yourself when asked", which reads less
  like a greeting on every turn.
- `config/comfy/` now holds seven API-format workflows exported by the owner from the ComfyUI GUI,
  all with plain node ids and every model file present on the Data drive: text-to-image for
  Z-Image Turbo, Qwen-Image 2512, SDXL base, SDXL base + refiner (two variants); image-to-image
  for SDXL and Z-Image Turbo with the Fun ControlNet Union (Canny). These are the candidates for the
  image tool's manifest. ComfyUI's `extra_model_paths.yaml` gained `controlnet` and
  `model_patches` (the Fun ControlNet loads through ModelPatchLoader, not ControlNetLoader).
- Answered for the record: ComfyUI's prompt queue and `/history` are in-memory and lost on restart
  (images on disk survive); Alveus history is `Agent.history` only (plan item 1); Qwen-Image
  instructions given (fp8 files from `Comfy-Org/Qwen-Image_ComfyUI`, 2512 refresh, no quantizing
  needed; nvfp4 or GGUF via ComfyUI-GGUF if smaller is wanted).

## 2026-09-10 — ComfyUI installed next to Alveus

- Windows C: shrunk from 735 GB to 500 GB (from Windows), the 1.8 TB NTFS "Data" drive mounted at
  `/mnt/data` by label with `ntfs3` (`ntfsfix -d` was needed once because Windows left it dirty;
  Fast Startup must stay off). Root partition is 195 GB with ~10 GB free, so models live on Data.
- ComfyUI 0.35 in conda env `comfy` (torch 2.14 + cu130) at `~/local/lib/ComfyUI`, user unit
  `comfyui.service` on 127.0.0.1:8188 with `RequiresMountsFor=/mnt/data`, output folder
  `~/local/data/alveus-ai/images`, models through `extra_model_paths.yaml` from
  `/mnt/data/comfy/models`. Downloaded: SDXL base, FLUX.1 dev fp8 (Kijai repack + T5/CLIP encoders,
  FLUX VAE from the Z-Image repack), Z-Image Turbo (bf16/int8/nvfp4 + Qwen3-4B encoders), FLUX.2 klein
  9B (gated black-forest-labs repo, auto-approved; Comfy-Org repack only holds encoders and VAE).
- First workflow exported in API format: `config/comfy/z_image_turbo_demo.json`. Its node ids came
  out as `57:27` (node 27 inside subgraph 57) because it was built inside a subgraph; renumbered to
  plain ids and verified by submitting it to ComfyUI (6 s render, no node errors).
- Measured VRAM at idle: llama-server 9.8 GB, assistant 7 GB, ComfyUI 3.3 GB after a Z-Image render.
- Docs: AGENTS runtime layout and roadmap; this dev log created; roadmap moved here (9153e63).

## 2026-09-09 (evening) — reboot fix, wake words, Chinese, GUI, coder

- **Service did not start at login** (b45f5b1): `alveus-llm.service` had `After=default.target`
  while being `WantedBy=default.target` — an ordering cycle; systemd silently dropped
  `alveus.service`'s start job. Removed the line in the template and the installed unit.
- **openWakeWord phrases never fired in `mode: both`** (a23ba42): VAD started recording on the first
  speech frame and the recorder consumed every following frame without scoring it; the model only ever
  saw 32 ms. The recorder now keeps scoring and a detection acts like the hotkey. `alveus
  wakeword-test` also read a non-existent config key and always tested `hey_jarvis`.
- **Microphone silent after the reboot**: the SC-GN01 mic delivered digital silence while `wpctl`
  looked fine (hardware mute). Diagnosed by recording with `pw-record` and measuring the peak.
- **Chinese was translated to English** (6ee3486): `stt.faster_whisper.language: en` makes Whisper
  translate; set to `null` (auto-detect) in local.yaml. Verified with real Mandarin recordings.
  Kokoro cannot speak CJK (reads characters as "Chinese letter"); Chatterbox multilingual can, and
  the owner switched to it.
- **GUI chat scrolling** (e328cb3, fb4705a): the log follows generation only while the reader is at
  the bottom; a "newer messages" button resumes. Two subtleties: streamed deltas arrive faster than
  scroll events, so a wheel movement was undone by the next delta — detected by comparing the position
  with the last auto-scroll; and an author `display:flex` beat the `hidden` attribute, so the button
  was always visible. Verified in headless Chrome via the DevTools protocol.
- **Custom wake words trained** (161e395, f27c71d): `scripts/train_wakeword.sh alveus` / `aurea` with
  livekit-wakeword in its own conda env. Obstacles: piper's phonemizer needs the `espeak-ng` binary
  (no apt rights, no conda package) — compiled the small CLI against the system `libespeak-ng` and
  taught the script to do so; the 19 GB dataset landed inside the repo — moved to
  `$ALVEUS_MODELS/wakeword-train-data`; the GPU was 97 % full while the trainer shared it with the
  services. Results: recall 99.2 % / 99.6 %, 0 false positives per hour on the synthetic validation
  set; the assistant's Kokoro voice scores 0.90 / 0.66; the owner's own voice only ~0.25 (see Plans).
  `oww_model` accepts a list, GUI shows models as checkboxes, both models are active in `mode: both`.
- **coder tool used `~` instead of the coding folder** (d392f28): the model filled `directory` with
  `"~"` or `"repo"`. The tools now resolve those against `ALVEUS_CODE_DIR`, quote the folder in their
  descriptions and list its subfolders on an unknown name.
- **GUI** (9edf26f): "speak replies" and "show reasoning" on by default; settings search box.
- Traps recorded in AGENTS.md: `pkill -f` killed the working shell again; loopback tests through the
  SC-GN01 do not work; keep big downloads off the root partition.

## 2026-09-09 (night before) — voice UX and robustness

- Coder tool follows the assistant's model by default; model and folder editable in Settings (a62f4bc).
- One `StreamSpeaker` for the voice loop and GUI; GUI speech honours `streaming_tts` (c82a65e).
- Listen beside Send, Stop beside Speak, Interrupt while replying; sudo "allow once" password card
  (ff88629). Stop aborts the whole reply's speech; clean SIGTERM shutdown (`systemctl stop` used to
  hang 90 s); `/debug/tasks` shows where asyncio tasks are stuck (7e018c0, 9216f02).
- Listen from any source interrupts a reply before listening (6129f37). Voice turns stream live into
  the GUI, including spoken confirmation questions (df4ba9c). Tool cards show the command being run;
  tools return real error text; persona told to read errors and not repeat calls (1797d0d, a9804f9).
- Code blocks: copy button, language tag, blank lines kept (3365687).

## 2026-09-08 — multilingual speech, settings semantics

- Settings: an empty text field saves an explicit `null` (e.g. STT language auto-detect) instead of
  reverting to the default; clearer field explanations (b1f579b).
- Chatterbox Multilingual: 23 languages with per-sentence language detection and CJK splitting
  (5997929, f9fe755). TTS strips emoji/symbols, skips unpronounceable fragments, survives a failing
  sentence, reports speech errors in the GUI (90149a0).
- `voice_gender: auto` infers from the cloned sample's `f_`/`m_` prefix, deciding Alveus vs Aurea
  (4d3aa7e). Copy / speak again / retry under replies; voices folder (`tts.voices_dir`) with a live
  sample picker and a visible warning when a sample is missing (fa089dd, d57dfa0). AGENTS.md written.

## 2026-09-04 / 05 — first version

- Alveus created: Bonsai-27B via the PrismML llama.cpp fork (prism branch, PQ2_0 kernels),
  faster-whisper / Parakeet STT, Kokoro / Chatterbox TTS, Silero VAD, openWakeWord, pynput hotkey,
  MCP tool servers (files/shell, desktop, system, web, coder→opencode), Typer CLI, systemd units,
  `install.sh` (f6ada82).
- Full documentation set and the offline handbook (`scripts/build_handbook.py`, `/handbook`), the
  ultraviolet theme, browser GUI with streamed chat, tool cards, confirmations, settings editor and
  restart (196aa5e, 12c3bf7, 1104264, eba7e27).
- Build traps: moved cmake build dirs break RPATH (`-DCMAKE_BUILD_RPATH_USE_ORIGIN=ON`); `master` of
  the fork lacks the PQ2_0 kernels (196544f). Units inherit DISPLAY/XAUTHORITY from the session.
