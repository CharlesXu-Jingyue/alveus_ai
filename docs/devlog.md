# Development log

History and plans in one place. Newest entries first; each entry says what changed, why, and what was
learned. Commit hashes refer to `git log`. The **Plans** section at the top is the roadmap; AGENTS.md,
README and development.md point here instead of keeping their own copies.

## Plans (in priority order, agreed with the owner)

1. **Conversations and memory.** Persist conversations (list, resume, search), summarize long ones,
   and give the agent a memory store it can read and write across restarts (facts, preferences).
   Likely an MCP server plus a sidebar in the GUI; today history lives only in `Agent.history`.
2. **Image generation follow-ups.** ComfyUI is wired in (2026-11-10). Next: a real instruction
   editor (Qwen-Image-Edit or FLUX.2 klein editing) for "remove the cup"-style changes, which the
   Canny ControlNet cannot do; picture upload/drag-and-drop in the GUI chat; the FLUX/Qwen-Image
   workflows as selectable alternatives (the 20 GB models need `alveus-llm` stopped for the render);
   `scripts/install_comfy.sh` for a fresh machine; letting the model see its result (plan 3).
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

## 2026-11-10 — pictures through ComfyUI (generate and redraw)

- New MCP server `images` (`mcp_servers/comfy.py`) with `generate_image`, `edit_image` and
  `recent_images`, over the two owner-exported API workflows: `txt2img_z_image_turbo_demo.json`
  and `img2img_z_image_turbo_fun_union_controlnet_demo.json` (Z-Image Turbo bf16 + Fun ControlNet
  Union on Canny edges). It POSTs `/prompt`, polls `/history/<id>`, fetches the picture with
  `/view` and saves it in `~/local/data/alveus-ai/images`.
- Parameters go in by node type rather than by id or title (the earlier plan was a manifest of
  node titles): prompt into the encoder feeding a sampler's positive input, seed/steps into samplers,
  size into the empty latent, picture into LoadImage, strength into the ControlNet. The same code
  fills the SDXL base+refiner and SDXL unCLIP exports correctly (tested), so swapping workflows is a
  setting, not code. `SaveImage` becomes `PreviewImage`, so ComfyUI's output folder keeps only its
  GUI's renders (this settles the "copy or not" question from 2026-09-10).
- GUI: a tool result with `image_url` shows the picture inside the tool card (also after a reload,
  from `/history`); `GET /images/file?name=` serves only file names inside the folder. Settings →
  Tools & safety → Image tools edits the folder, ComfyUI address, both workflows and the unload delay.
- `ToolHub` honours a per-server `call_timeout_s` (images: 600 s; the default 120 s is too short for
  a cold model load). Pillow is now a declared dependency (input pictures are scaled to 1024 on the
  long side, multiples of 16, before upload: the export has no resize node, and a 4000 px photo
  would become a 4000 px latent).
- Measured on the 4090 beside Whisper large-v3, Qwen3-TTS and LFM3 1.7B: 1024×768 in 4.5 s warm,
  12–14 s when the models must be reloaded from RAM; an edit 6.5–14 s; ComfyUI holds about 8 GB
  while loaded. End to end through LFM3: "draw a cozy cabin…" 14 s, "redraw it as a watercolour"
  11 s, both correct calls; the reply no longer reads the file path aloud once the result says the
  picture is already on screen.
- Lessons:
  - The edit workflow keeps outlines, not content. Watercolour, fox → wolf in the same pose, and
    night lighting all work; local edits (erase or add one object) do not, so the tool description
    tells the model to describe the whole result.
  - Unloading after every picture costs 2–3× the time. Instead the server unloads after 120 idle
    seconds. A series of edits stays fast, and the GPU is free again soon after.
  - ComfyUI's `/free` only sets a flag; memory drops a few seconds later.
  - An asyncio task can't be trusted to unload at exit: the event loop cancels it on shutdown. The
    server keeps a "models loaded" flag, unloads in an `atexit` hook, and turns SIGTERM into a
    normal exit so that hook runs.
  - Headless Chrome's `--virtual-time-budget` never finishes on the GUI (it keeps an SSE stream
    open); `--timeout=8000` works for screenshots. A tool card built for the history view isn't on
    the page yet, so the picture must go inside the card, not after it.

## 2026-11-09 — models on the data disk; six more local language models with aliases

- **Layout.** `ALVEUS_MODELS` is now `/mnt/data/models` (the 1.9 TB disk; the root disk was 96 %
  full): `llm/<model>/` for GGUF files, `tts/` for Qwen3-TTS (`tts.qwen3.weights_dir` defaults to
  `${ALVEUS_MODELS}/tts` now), `wakeword/`. The two Bonsai files and the wake words moved there
  (verified byte for byte, then `~/local/model` removed, 10 GB freed); the systemd units were
  re-rendered (`scripts/install_services.sh`) because their `Environment=ALVEUS_MODELS` wins over
  `local.yaml`. The model picker scans `llm/` and leaves out drafters (DSpark, FastMTP) like mmproj.
- **Aliases.** A profile's `alias` is what the settings page shows (model list, header, "Running"),
  editable as "Name in the list"; `alveus llm profiles` lists it. The owner asked for names without
  the uploaders and without their claims ("Heretic", "TURBO", "MAX"), keeping what tells the models
  apart; then that the modified Bonsai and LFM ones say "· uncensored" so they are not taken for the
  stock models (the Qwen3.8 names already say how they differ). Profile keys have no dots (`qwen38-direct`), because the settings page
  splits config paths on dots; the served model ids keep them.
- **Six models** (`scripts/download_models.sh --extra`, ~76 GB). Each was started on a spare port with
  its profile's own flags while the assistant ran (Whisper large-v3 4.7 GB + Qwen3-TTS 6.5 GB on the
  4090), asked one question with thinking off and one needing a tool with thinking on:

  | alias | file | result |
  |---|---|---|
  | Ternary Bonsai 27B · uncensored | PQ2_0, 7.2 GB (no Q4 exists; ternary is the format) | loads in 3 s, 8.3 GB VRAM, ~70 tok/s, tool call correct |
  | LFM2.5 24B-A2B MoE · uncensored | IQ4_XS 13.8 GB (the 4-bit file) + DSpark Q8_0 drafter | ~105–119 tok/s, 55–70 % of drafts accepted; reasons even with thinking off and reaches for tools eagerly (called the clock for "why is the sky blue") |
  | LFM3 1.7B · uncensored | Q6_K, 1.6 GB | the Prism fork says `unknown model architecture: 'lfm3'`; on upstream llama.cpp (master @ 6122b56, built by the owner) it loads in 2 s, 2.4 GB VRAM, ~320 tok/s, tool call correct |
  | Qwen3.8 27B · direct | Q4_K_P, 17.9 GB | correct, tool call correct, **8 tok/s**: only ~9 GB of it fits beside the speech models |
  | Qwen3.8 27B · coder merge | MTP Q4_K_M, 18.5 GB | the same, 9 tok/s, 85 % of MTP drafts accepted |
  | Qwen3.8 27B · abliterated | Q4_K_M, 16.8 GB | correct, tool call correct, 12–14 tok/s (the smallest of the three, a little more on the GPU); the repo became gated during the download, the owner accepted its terms |

- **Stock Qwen3.8 27B** too, at the owner's request (`qwen-local`, which had been a template without a
  file): unsloth's `UD-Q4_K_M` (16.5 GB; there is no official Qwen GGUF). Its MTP head is a separate
  file (`MTP/mtp-Qwen3.8-27B-Q4_0.gguf`, 1.4 GB, passed with `-md`); 7 tok/s beside the speech models,
  71–78 % of drafts accepted. The Bonsai and LFM aliases end in "· uncensored" so they are not taken
  for stock models; the owner dropped the "2" from Ternary Bonsai 2's.
- **What was learned.** The Prism fork (built 2026-09-04) already runs Qwen3.8 (`qwen35`), LFM2.5
  (`lfm2moe`), MTP and DSpark drafting and `--fit`; only LFM3 needs upstream (`scripts/build_llama.sh
  --upstream`, `ALVEUS_LLAMA_SERVER_UPSTREAM`, which defaults to the fork until set; this machine sets it
  in `local.yaml`). The owner ran the build: a session may not fetch and build outside code. `--fit` sizes the layers without the drafter: LFM2.5 with DSpark crashed with
  "failed to allocate compute pp buffers" until `-fitt 2048` left room. A 27B Q4 model and Qwen3-TTS
  do not fit on 24 GB together; for voice use, the Qwen3.8 models need the GPU to themselves or the
  lighter speech engines (Kokoro, Whisper large-v3-turbo), or a 3-bit file. A stalled `hf download`
  (0 % CPU for 28 min, no file) was the gated repo; plain HTTP returned 401.

## 2026-11-07 (late afternoon) — Qwen3-TTS as a third voice engine; curated female voices

- Follow-up: the owner listened and removed Xiaoyu and Wanqing (TTS-SCDuFSC): not good enough. They
  were three short read sentences (cycling-forum lines, 2–5 s each) joined with pauses, so the
  prosody was flat and choppy; better sources are single continuous 8–12 s utterances. Six voices
  remain: Ayaka, Hina, Yuzu, Mio, Shiori, Feiyu.

- Owner: add Qwen3-TTS 1.7B as a TTS engine; download and curate female voice samples from 朱花
  (aiseiyou.com), japanese-anime-speech, da-fei-yu-girl-voice-zh and TTS-SCDuFSC, and name them.
- **Engine** (`tts.backend: qwen3`): qwen-tts 0.1.1 pins transformers 4.57.3 and fails on Alveus's
  5.2 (`check_model_inputs` was removed), so it runs in a worker process with its own venv
  (`.venv-qwen3tts`, on top of the alveus Python, 139 MB; `scripts/install_qwen3_tts.sh`,
  `install.sh --with-qwen3-tts`). JSON request per sentence over a pipe, float32 audio back; the
  worker ends with Alveus (stdin closes) or when the engine is swapped (`live._engine` calls
  `close()`). Weights in `/mnt/data/models/tts` (root disk at 94 %). Measured: ready in 3.4 s,
  3.9 GB VRAM, ~2 s per sentence (sdpa, no flash-attn); live swap Kokoro → Qwen3 → Kokoro works and
  frees the worker. Models `1_7b` (downloaded) and `0_6b` (downloads on first use); per-model voice,
  gender, language, variation in the settings tree; *Its words* shows whether the recording has a
  transcript and *Write it down* (`POST /voices/transcribe`) makes one with the running STT.
- **Cloning mode per sentence** (measured, see backends.md): with the transcript, in-context
  cloning is best in the recording's own language (0.88–0.94 speaker similarity) but drifts for
  English from a Japanese/Chinese voice (as low as 0.70; Yuzu came out at 155 Hz against a 396 Hz
  recording); the x-vector mode holds at 0.87–0.92 there. The engine sends the transcript only
  for sentences in the recording's language.
- **Voices** (`voices/`, `SOURCES.md` with sources and terms): Ayaka/朱花 (official 8 s sample from the
  AI声優 YouTube channel; free use, credit "AI声優-朱花"; her creator calls her a cheeky tsundere, which
  pairs with the Tsundere personality), Hina, Yuzu, Mio, Shiori (one line each from four characters
  of japanese-anime-speech shard 0, CC0; file names carry character codes `0fem_aia` etc.; lines with
  adult or awkward content skipped), Feiyu/大肥鱼 (ModelScope, CC-BY-NC), Xiaoyu and Wanqing
  (TTS-SCDuFSC speakers F004/F003, three sentences joined, CC-BY-NC-ND; the speakers read different
  scripts after the first lines, so sentences are matched by text). All trimmed, mono 24 kHz,
  -20 LUFS, with `.txt` words; chosen by noise floor, pauses, pitch and Whisper agreement with the
  given text (0–0.08 apart from 朱花's spelling), then cloned with Qwen3-TTS in their language and in
  English: Whisper understood every output.
- Fixes on the way: a dead worker is retired at once (a race let the next sentence write to it);
  with no voice chosen the gender (and name) follows the recording that is actually copied.

## 2026-11-07 (afternoon) — instructions and personalities are separate; four personalities ship

- Owner: separate personality from instructions (instructions = directions and boundaries,
  personality = how it sounds), store several personalities and choose one; the calm, warm one is
  the default, plus a sweet one (honest, intimate, a bit whimsical), a playful, slightly flirtatious
  tsundere, and a genki one (proactive, attentive, optimistic).
- `config/persona.md` became `config/instructions.md` (`assistant.instructions_file`; the old
  `persona_file` key is still read) with a `{personality}` slot and a paragraph saying a personality
  never changes what the assistant does or is a reason to refuse, delay or pad. The style lines that
  were in it ("direct, warm, and unhurried", using the name now and then, everyday words) moved into
  `config/personalities/calm.md`. One new direction for every personality: offer a further step
  rather than taking it (genki's proactiveness stays an offer).
- `alveus/personality.py`: shipped personalities in `config/personalities/` are read-only; the
  owner's own and edited copies live in `assistant.personalities_dir` (`personalities/`, git-ignored)
  and override by id; deleting a copy restores the original. Placeholders are filled by name only, so
  a stray brace in hand-written text no longer breaks the prompt (`str.format` did).
- API `GET/PUT /instructions` (replaces `/persona`), `GET /personalities`, `PUT`/`DELETE
  /personalities/{id}`; switching is an ordinary setting (`assistant.personality`, applied live;
  the report says "personality: Sweet"). The instructions path no longer needs a restart.
- GUI: Assistant → Personality cards with an editor for the chosen one (name, description, words;
  Save, Save as new…, Restore original, Delete); Advanced → Instructions. Settings search now also
  matches the names on choice cards ("tsundere", "kokoro").
- Live check on DeepSeek Flash, same question under each ("Long day. What is 15 percent of 80? And
  should I bother finishing the analysis tonight?"): all answered "twelve" first and kept to two or
  three sentences; calm was even, sweet called them "love" and offered to help tomorrow, tsundere
  covered its concern with "don't get used to it", genki offered to note where they left off.

## 2026-11-07 (late night) — confirmations follow the conversation; fewer of them

- Owner: no chime before answering (keep the flow natural); silence was intentional; wait longer
  after the question. The chime is gone; the wait is `activation.confirm_wait_s` (15 s, was a fixed
  6 s); silence now ends the question (no automatic re-ask) and the model is told the user did not
  answer and not to ask again; an unclear reply still gets one shorter question.
- Relaxed what asks: `close_window` is no longer marked destructive; `move_path` refuses to overwrite
  and asks only with `overwrite=true`; `control_service` asks only for stop/disable or system scope
  (`ASK_WHEN` in `agent/loop.py`); `rmdir` left the risky-shell pattern. Delete, kill, power and risky
  shell commands still ask. The persona no longer tells the model to ask for confirmation itself
  (the system does), so the model and the gate do not both ask.

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
