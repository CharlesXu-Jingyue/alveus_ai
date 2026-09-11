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
   image via `/view`, saves it under `~/local/data/alveus-ai/images` and opens it with the desktop
   tool. VRAM rule: Z-Image and SDXL fit next to the LLM; FLUX.1 dev and FLUX.2 klein 9B need
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
profile is a one-line patch; there is no effort dial, only llama-server's `--reasoning-budget`).

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
