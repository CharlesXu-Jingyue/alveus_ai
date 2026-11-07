# Configuration reference

## Layers

Settings are merged in this order (later wins):

1. `config/alveus.yaml` – defaults, versioned.
2. `config/local.yaml` – this machine only, git-ignored, written by `install.sh` and the GUI
   (`$ALVEUS_LOCAL_CONFIG` points elsewhere, e.g. for a test instance).
3. `$ALVEUS_CONFIG` – optional extra file path.
4. Environment shortcuts: `ALVEUS_LLM_PROFILE`, `ALVEUS_STT_BACKEND`, `ALVEUS_TTS_BACKEND`.

Every string value is expanded: `~` → home, `${VAR}` → a variable. Variables come from the
process environment or from the YAML `env:` block (environment wins). Always defined:
`ALVEUS_HOME` (repo root), `ALVEUS_MODELS` (default `${ALVEUS_HOME}/models`),
`ALVEUS_LLAMA_SERVER` (default `llama-server` on PATH).

Only put in `local.yaml` what differs from the defaults, e.g.:

```yaml
env:
  ALVEUS_MODELS: ~/local/model
  ALVEUS_LLAMA_SERVER: ~/local/lib/llama.cpp-bonsai/build/bin/llama-server
assistant:
  user_name: Charles
audio:
  backend: pipewire
```

Changes take effect on the next start (`systemctl --user restart alveus`).

## `assistant`

| key | default | meaning |
|---|---|---|
| `name` | `Alveus` | name used with a male/neutral voice; always accepted as a wake name |
| `female_name` | `Aurea` | name used when the voice is female (see `tts.voice_gender`) |
| `user_name` | `Charles` | how the assistant addresses you; injected into the persona |
| `language` | `en` | informational (STT language is set per backend) |
| `persona_file` | `${ALVEUS_HOME}/config/persona.md` | system prompt template; placeholders `{name} {other_name} {voice_gender} {user_name} {date} {hostname} {os}` |
| `max_history_turns` | `30` | user turns kept in the conversation |
| `streaming_tts` | `true` | speak sentence by sentence while generating (voice loop and GUI "speak replies" alike; synthesis of the next sentence overlaps playback); `false` waits for the full reply. The journal logs `speech: … first audio after N s` per reply |

## `llm`

| key | default | meaning |
|---|---|---|
| `profile` | `bonsai-1bit` | active profile (override: `ALVEUS_LLM_PROFILE`, `alveus talk --profile`) |
| `temperature`, `top_p`, `max_tokens` | `0.7`, `0.95`, `4096` | request defaults for every profile; a profile's own value wins; `null` = not sent. Never sent to providers that reject them (Claude, OpenAI) unless the profile sets them |
| `effort` | `null` | reasoning depth for models that have it: `low` \| `medium` \| `high` \| `xhigh` \| `max` (Claude `output_config.effort`, OpenAI `reasoning.effort`, DeepSeek `reasoning_effort`); `null` = model default |
| `max_tool_rounds` | `12` | maximum LLM↔tool iterations in one turn |
| `manage_local_server` | `true` | when the assistant starts, align the `alveus-llm` unit with the profile: stop it for a profile without `serve:` (cloud, external server), start it if it is down, restart it if it serves another model. Skipped for one-off overrides (`--profile`, `ALVEUS_LLM_PROFILE`) and when the unit is not installed |
| `profiles.<name>.provider` | | preset from `alveus/llm/providers.py`: `llama_server`, `vllm`, `ollama`, `openai_compat`, `openai`, `anthropic`, `deepseek`, `openrouter` (or any name, with `api` + `base_url`). Old profiles with `backend: openai` still work (= `openai_compat`) |
| `profiles.<name>.model` | | model id; for local servers it must equal an id in `GET /v1/models` (llama-server: set with `--alias`) |
| `profiles.<name>.api` | from provider | protocol: `openai_chat` \| `openai_responses` \| `anthropic_messages` |
| `profiles.<name>.base_url` | from provider | e.g. `http://127.0.0.1:8080/v1`; required for `openai_compat` |
| `profiles.<name>.api_key_env` | from provider | variable holding the key (environment or `~/.config/alveus/secrets.env`) |
| `profiles.<name>.api_key` | | literal key, for local servers that want any string; do not put real keys in YAML |
| `profiles.<name>.max_tokens`, `temperature`, `top_p`, `effort` | | per-profile overrides of the llm-level values |
| `profiles.<name>.thinking` | unset | `true`/`false` forces thinking on/off where the provider has a switch (llama-server: `chat_template_kwargs.enable_thinking`; DeepSeek: `thinking.type`; Claude: `false` = send no thinking setting, for older models) |
| `profiles.<name>.extra_body` | `{}` | merged into the request JSON (`top_k`, `min_p`, `repetition_penalty`, …) |
| `profiles.<name>.headers` | `{}` | extra HTTP headers (e.g. OpenRouter's `HTTP-Referer`) |
| `profiles.<name>.opencode_model` | derived | what the coder tool's `auto` means for this profile (`provider/model` in opencode); derived from the preset's `opencode_provider` |
| `profiles.<name>.serve.command` | | server binary for `alveus llm serve`; a profile without `serve` needs no local server (`alveus-llm` then exits and frees the GPU) |
| `profiles.<name>.serve.model_path` | | GGUF path (checked by `doctor`) |
| `profiles.<name>.serve.args` | | extra llama-server args; `--host/--port/-m/--alias` are added automatically |
| `profiles.<name>.serve.context`, `.gpu_layers` | | context length (`-c`) and GPU layers (`-ngl`); win over the same flags in `args` (the GUI's *Context length* writes `context`) |
| preset keys | | `thinking_param`, `reasoning_replay`, `max_tokens_field` (openai_chat); `reasoning_summary`, `store` (openai_responses); `thinking_display`, `fallbacks`, `prompt_cache` (anthropic_messages); see `providers.py` and backends.md |

Shipped profiles: local `bonsai-1bit` (default), `bonsai-ternary`, `qwen-local` (weights not
downloaded), and cloud `claude`, `chatgpt`, `deepseek`. The local ones all serve on port 8080, so
only one runs at a time; switch with `llm.profile` and restart `alveus-llm` (the GUI does both).
API keys never go in this file: see [backends.md](backends.md#api-keys).

llama-server flags used and why: `-ngl 99` all layers on GPU; `-c 32768` context (raise up to
262144 if you need long documents, VRAM permitting); `--jinja` real chat template (required for
tool calling); `--reasoning-format deepseek` separates thinking; `-fa on` flash attention;
sampling `--temp 0.7 --top-p 0.95 --top-k 20` as recommended by the model card.

## Engines with several models: `<engine>.models.<model>`

In `stt` and `tts`, each engine has its own block (`tts.kokoro`, `tts.chatterbox`, …). An engine with
several models (Whisper sizes, Chatterbox Turbo/Standard/Multilingual) can also keep settings per
model in `<engine>.models.<model>`; they win over the engine block, which wins over section-wide
fallbacks (`tts.voices_dir`, `tts.voice_gender`). An explicit `null` counts (e.g. `voice_ref: null`
= the built-in voice for that model only). The GUI stores model-specific choices this way:

```yaml
tts:
  backend: chatterbox
  chatterbox:
    model: multilingual
    voices_dir: ~/local/data/alveus-ai/voices    # shared by all Chatterbox models
    voice_ref: m_charles_demo.wav                 # used by models that set none
    models:
      multilingual: { voice_ref: f_mei.wav, language: auto }
      turbo: { voice_gender: male }
stt:
  faster_whisper:
    model: large-v3
    models:
      large-v3: { compute_type: int8_float16 }   # the big model in half the VRAM
```

## `stt`

| key | default | meaning |
|---|---|---|
| `backend` | `faster_whisper` | `faster_whisper` \| `parakeet` \| `openai_http` (override: `ALVEUS_STT_BACKEND`) |
| `device` | `cuda` | `cuda` or `cpu` |
| `faster_whisper.model` | `large-v3-turbo` | any faster-whisper model id or local CTranslate2 dir (`distil-large-v3`, `medium`, `small`) |
| `faster_whisper.compute_type` | `float16` | `int8_float16` halves VRAM |
| `faster_whisper.beam_size` | `1` | greedy is fastest; 5 for tougher audio |
| `faster_whisper.language` | `en` | `null` = auto-detect per utterance (needed to speak other languages; a fixed language makes Whisper *translate* into it) |
| `parakeet.model` | `nemo-parakeet-tdt-0.6b-v3` | onnx-asr model id |
| `openai_http.base_url`, `.model`, `.language` | | any `/v1/audio/transcriptions` server |

## `tts`

| key | default | meaning |
|---|---|---|
| `backend` | `kokoro` | `kokoro` \| `chatterbox` \| `openai_http` (override: `ALVEUS_TTS_BACKEND`) |
| `device` | `cuda` | `cuda` or `cpu` |
| `voice_gender` | `auto` | fallback for engines/models that set no `voice_gender` of their own. `auto` infers from the voice: Kokoro voice prefix (`af_`/`bf_` female, `am_`/`bm_` male), or for Chatterbox the cloned sample's file name (`f_*.wav` / `m_*.wav`); or `female`/`male`. Decides Alveus vs Aurea |
| `<engine>.voice_gender`, `<engine>.models.<model>.voice_gender` | | the same per engine or model (the GUI sets these) |
| `kokoro.voice` | `af_heart` | see `alveus tts voices` (28 English voices) |
| `kokoro.speed` | `1.0` | |
| `kokoro.lang_code` | `null` | `null` follows the voice (`af_`/`am_` American, `bf_`/`bm_` British); or force `a` / `b` |
| `chatterbox.model` | `turbo` | `turbo` (English, fastest), `standard` (English, expressive), `multilingual` (23 languages) |
| `voices_dir`, `chatterbox.voices_dir` | `${ALVEUS_HOME}/voices` | folder of WAV samples for cloning; the GUI's sample picker lists its files (set per machine in `local.yaml`) |
| `chatterbox.voice_ref` | `null` | a file name inside the voices folder, or an absolute path, of a 5–15 s WAV to clone; name it `f_…wav` or `m_…wav` so the gender (and name) is inferred. A missing file falls back to the built-in voice with a warning |
| `chatterbox.language`, `.fallback_language` | `auto`, `en` | multilingual only: `auto` detects each sentence's language |
| `chatterbox.exaggeration`, `.cfg_weight` | `0.5`, `0.5` | standard and multilingual: expressiveness and pacing |
| `openai_http.base_url`, `.model`, `.voice` | | any `/v1/audio/speech` server (e.g. Kokoro-FastAPI on :8880) |

## `audio`

| key | default | meaning |
|---|---|---|
| `backend` | `auto` | `auto` picks `pipewire` when `pw-record`/`pw-play` exist, else `sounddevice` |
| `input_device` / `output_device` | `null` | PipeWire: node name or serial for `--target` (see `wpctl status`); sounddevice: index or name substring |
| `sample_rate` | `16000` | capture rate (VAD/STT expect 16 kHz) |
| `vad.threshold` | `0.5` | Silero speech probability threshold |
| `vad.min_speech_ms` | `250` | shorter segments are ignored |
| `vad.end_silence_ms` | `700` | pause length that ends an utterance |
| `vad.max_utterance_s` | `60` | hard cap |
| `chimes` | `true` | play a chime when the assistant starts listening |
| `barge_in` | `true` | hotkey, Listen button, `/trigger` (and openWakeWord, if enabled) interrupt a reply in progress: generation, pending tool calls and speech, then listen |

## `activation`

| key | default | meaning |
|---|---|---|
| `wake_word.enabled` | `true` | |
| `wake_word.mode` | `names` | `names` (transcript-based), `oww` (openWakeWord), `both` |
| `wake_word.names` | `[Alveus, Aurea]` | names that address the assistant |
| `wake_word.name_aliases` | `[alvius, …, aria, oria, …]` | STT misspellings that also count |
| `wake_word.oww_model` | `hey_jarvis` | one model, or a list (`[alveus, aurea]` / `"alveus, aurea"`) that all listen at once: pretrained ids or the stem of a custom `.onnx` in `${ALVEUS_MODELS}/wakeword/` |
| `wake_word.threshold` | `0.5` | openWakeWord score threshold |
| `wake_word.name_segment_s` | `12` | max length of a speech segment checked for a name |
| `wake_word.follow_up_window_s` | `8` | seconds after a reply during which no name is needed (`0` disables) |
| `hotkey.enabled` | `true` | |
| `hotkey.combo` | `<ctrl>+<alt>+<space>` | pynput syntax: `<ctrl>+<shift>+a`, `<cmd>+<space>`, … |
| `hotkey.mode` | `toggle` | `toggle` (press to start, silence/press ends) or `hold` (push-to-talk) |

## `tools`

| key | default | meaning |
|---|---|---|
| `confirm_destructive` | `true` | ask before destructive tools / dangerous shell commands |
| `no_confirm` | `[]` | risky tools that may run without asking, by full name (e.g. `desktop__close_window`); shell commands and sudo still ask (GUI: Tools & safety → Don't ask for these) |
| `servers.<name>.command` | | argv list for a stdio MCP server; `python` is replaced by the env's interpreter |
| `servers.<name>.url` | | HTTP MCP server (`…/sse` uses SSE transport, otherwise streamable HTTP) |
| `servers.<name>.headers` | | HTTP headers (e.g. `Authorization`) |
| `servers.<name>.env` | | extra environment for stdio servers (`ALVEUS_FS_ROOTS` for `files`) |
| `servers.<name>.cwd` | repo root | |
| `servers.<name>.enabled` | `true` | |
| `servers.<name>.timeout_s` | `60` | startup timeout |
| `servers.<name>.inherit_api_keys` | `false` | pass LLM API-key variables (`ANTHROPIC_API_KEY`, …) from the environment to this stdio server; only the coder needs it (opencode) |

Built-in servers: `files`, `desktop`, `system`, `web`, `coder`. The coder server honours
`ALVEUS_OPENCODE_MODEL` (`auto` = the assistant's own local model, `opencode-default`, or a
`provider/model` id such as `deepseek/deepseek-v4-flash`) and `ALVEUS_CODE_DIR` (default project folder).
Every stdio server also receives `ALVEUS_HOME`, `ALVEUS_LLM_PROFILE`, `ALVEUS_LLM_MODEL`, `ALVEUS_LLM_BASE_URL`.

## `api`

| key | default | meaning |
|---|---|---|
| `enabled` | `true` | start the browser GUI + HTTP API inside `alveus talk` |
| `host`, `port` | `127.0.0.1`, `8765` | bind address (keep localhost; tunnel with SSH for remote use) |

Most keys above can also be edited in the GUI's Settings tab, which writes `config/local.yaml`.

## `logging`

| key | default | meaning |
|---|---|---|
| `level` | `INFO` | `DEBUG` shows ignored (non-addressed) transcripts, VAD decisions, MCP traffic |
| `dir` | `${ALVEUS_HOME}/logs` | `alveus.log` is written here in addition to the console/journal |
