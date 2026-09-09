# Configuration reference

## Layers

Settings are merged in this order (later wins):

1. `config/alveus.yaml` – defaults, versioned.
2. `config/local.yaml` – this machine only, git-ignored, written by `install.sh`.
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
| `streaming_tts` | `true` | speak sentence by sentence while generating; `false` waits for the full reply |

## `llm`

| key | default | meaning |
|---|---|---|
| `profile` | `bonsai-1bit` | active profile (override: `ALVEUS_LLM_PROFILE`, `alveus talk --profile`) |
| `temperature`, `top_p`, `max_tokens` | `0.7`, `0.95`, `4096` | request defaults, overridable per profile |
| `max_tool_rounds` | `12` | maximum LLM↔tool iterations in one turn |
| `profiles.<name>.backend` | `openai` | only OpenAI-compatible is implemented (aliases: `llama_server`, `vllm`, `ollama`) |
| `profiles.<name>.base_url` | | e.g. `http://127.0.0.1:8080/v1` |
| `profiles.<name>.api_key` | `local` | sent as Bearer token |
| `profiles.<name>.model` | | must equal an id in `GET /v1/models` (llama-server: set with `--alias`) |
| `profiles.<name>.reasoning` | `false` | model emits `reasoning_content` (informational) |
| `profiles.<name>.thinking` | unset | `true`/`false` forces `chat_template_kwargs.enable_thinking` |
| `profiles.<name>.extra_body` | `{}` | merged into the request JSON (`top_k`, `min_p`, `repetition_penalty`, …) |
| `profiles.<name>.serve.command` | | server binary for `alveus llm serve` |
| `profiles.<name>.serve.model_path` | | GGUF path (checked by `doctor`) |
| `profiles.<name>.serve.args` | | extra llama-server args; `--host/--port/-m/--alias` are added automatically |

Shipped profiles: `bonsai-1bit` (default) and `bonsai-ternary`. Both serve on port 8080, so only
one runs at a time; switch with `llm.profile` and restart `alveus-llm`.

llama-server flags used and why: `-ngl 99` all layers on GPU; `-c 32768` context (raise up to
262144 if you need long documents, VRAM permitting); `--jinja` real chat template (required for
tool calling); `--reasoning-format deepseek` separates thinking; `-fa on` flash attention;
sampling `--temp 0.7 --top-p 0.95 --top-k 20` as recommended by the model card.

## `stt`

| key | default | meaning |
|---|---|---|
| `backend` | `faster_whisper` | `faster_whisper` \| `parakeet` \| `openai_http` (override: `ALVEUS_STT_BACKEND`) |
| `device` | `cuda` | `cuda` or `cpu` |
| `faster_whisper.model` | `large-v3-turbo` | any faster-whisper model id or local CTranslate2 dir (`distil-large-v3`, `medium`, `small`) |
| `faster_whisper.compute_type` | `float16` | `int8_float16` halves VRAM |
| `faster_whisper.beam_size` | `1` | greedy is fastest; 5 for tougher audio |
| `faster_whisper.language` | `en` | `null` = auto-detect (slower, needed for multilingual) |
| `parakeet.model` | `nemo-parakeet-tdt-0.6b-v3` | onnx-asr model id |
| `openai_http.base_url`, `.model`, `.language` | | any `/v1/audio/transcriptions` server |

## `tts`

| key | default | meaning |
|---|---|---|
| `backend` | `kokoro` | `kokoro` \| `chatterbox` \| `openai_http` (override: `ALVEUS_TTS_BACKEND`) |
| `device` | `cuda` | |
| `voice_gender` | `auto` | `auto` infers from the voice: Kokoro voice prefix (`af_`/`bf_` female, `am_`/`bm_` male), or for Chatterbox the cloned sample's file name (`f_*.wav` / `m_*.wav`); or `female`/`male`. Decides Alveus vs Aurea |
| `kokoro.voice` | `af_heart` | see `alveus tts voices` (28 English voices) |
| `kokoro.speed` | `1.0` | |
| `kokoro.lang_code` | `a` | `a` American, `b` British English |
| `chatterbox.model` | `turbo` | `turbo` or `standard` |
| `voices_dir` | `${ALVEUS_HOME}/voices` | folder of WAV samples for cloning; the GUI's sample picker lists its files (set per machine in `local.yaml`) |
| `chatterbox.voice_ref` | `null` | a file name inside `voices_dir`, or an absolute path, of a 5–15 s WAV to clone; name it `f_…wav` or `m_…wav` so the gender (and name) is inferred. A missing file falls back to the built-in voice with a warning |
| `chatterbox.exaggeration`, `.cfg_weight` | `0.5`, `0.5` | standard model only |
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
| `barge_in` | `true` | hotkey (and openWakeWord, if enabled) interrupt playback |

## `activation`

| key | default | meaning |
|---|---|---|
| `wake_word.enabled` | `true` | |
| `wake_word.mode` | `names` | `names` (transcript-based), `oww` (openWakeWord), `both` |
| `wake_word.names` | `[Alveus, Aurea]` | names that address the assistant |
| `wake_word.name_aliases` | `[alvius, …, aria, oria, …]` | STT misspellings that also count |
| `wake_word.oww_model` | `hey_jarvis` | pretrained id or the stem of a custom `.onnx` in `${ALVEUS_MODELS}/wakeword/` |
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
| `servers.<name>.command` | | argv list for a stdio MCP server; `python` is replaced by the env's interpreter |
| `servers.<name>.url` | | HTTP MCP server (`…/sse` uses SSE transport, otherwise streamable HTTP) |
| `servers.<name>.headers` | | HTTP headers (e.g. `Authorization`) |
| `servers.<name>.env` | | extra environment for stdio servers (`ALVEUS_FS_ROOTS` for `files`) |
| `servers.<name>.cwd` | repo root | |
| `servers.<name>.enabled` | `true` | |
| `servers.<name>.timeout_s` | `60` | startup timeout |

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
