# Troubleshooting

Start with `alveus doctor --warm` and `journalctl --user -u alveus -n 200`.

## Startup / services

| symptom | cause | fix |
|---|---|---|
| `alveus.service` restarts in a loop, log shows `ValueError: space` | hotkey combo uses a bare key name | use pynput names in angle brackets: `<ctrl>+<alt>+<space>` |
| `hotkey disabled … Can't connect to display ":0"` | unit had a hard-coded `DISPLAY`; or the systemd user env lacks `DISPLAY`/`XAUTHORITY` | current unit inherits them; if still missing: `systemctl --user import-environment DISPLAY XAUTHORITY` then restart |
| `alveus.service` stuck in `ExecStartPre` | llama-server not healthy on :8080 | `systemctl --user status alveus-llm`, `journalctl --user -u alveus-llm`; check weights path in `alveus llm profiles` |
| Port 8080 in use | a manual `llama-server` is still running | `pkill llama-server` (careful with `pkill -f` matching your own shell), then start the unit |
| Two answers to every question | service **and** manual `alveus talk` both running | `systemctl --user stop alveus` before running by hand |

## Audio

| symptom | cause | fix |
|---|---|---|
| `PortAudioError: Invalid sample rate` / no devices | conda's PortAudio has no PipeWire/Pulse host API and PipeWire holds the ALSA devices | use `audio.backend: pipewire` (auto when `pw-record` exists) |
| `pw-record exited unexpectedly` | no `XDG_RUNTIME_DIR`/PipeWire socket (e.g. run from ssh) | run inside the desktop session (`systemd --user` service does) |
| Wrong mic / speaker | default PipeWire device | `wpctl status`, `wpctl set-default <id>`, or set `audio.input_device` to the node name |
| Assistant hears itself / random triggers | speaker output reaching the mic | lower speaker volume, raise `activation.wake_word.threshold`, keep `mode: names` (needs a name), or use a headset |
| Cuts you off mid-sentence | `end_silence_ms` too short | raise to 900–1200 |
| Slow to answer after you stop | `end_silence_ms` too long | lower to 500 |

## Recognition

| symptom | cause | fix |
|---|---|---|
| Doesn't react to "Aurea" | Whisper hears "Aria/Oria/Area" | check with `alveus stt test`; add the spelling to `activation.wake_word.name_aliases` |
| Reacts when nobody said the name | fuzzy match too loose | remove short aliases; raise `NameMatcher` cutoff (0.78) in `alveus/audio/names.py` |
| Transcript "Thank you." from silence | Whisper hallucination on near-silence | filtered (`JUNK` set in `voice.py`); extend the set if you see others |
| Non-English speech misrecognised | `stt.faster_whisper.language: en` | set to `null` for auto-detect |

## Model / tools

| symptom | cause | fix |
|---|---|---|
| `LLM endpoint FAIL … model 'x' not in served models` | profile `model` ≠ llama-server `--alias` | keep them equal; `alveus llm serve` sets the alias from the profile |
| Tool calls never happen | server started without `--jinja`, or model without tool template | profile `serve.args` include `--jinja`; check `curl :8080/v1/models` |
| Reply is empty but "thinking" long | `max_tokens` hit during reasoning | raise `llm.max_tokens` or set `thinking: false` |
| "I reached the tool-call limit" | model looping on a failing tool | check the tool's error in the log; raise `llm.max_tool_rounds` only if legitimately needed |
| `MCP server 'x' failed to start: Connection closed` | server crashed at import | run it directly: `python -m mcp_servers.x` to see the traceback |
| `ModuleNotFoundError: mcp.server.fastmcp` | mcp ≥ 2 renamed FastMCP | already handled by `mcp_servers/common.py`; use `from .common import FastMCP` |
| Desktop tools say "missing tools: xdotool…" | optional binaries absent | `sudo apt install xdotool wmctrl xclip playerctl` |
| `code_task` returns quickly with no summary | opencode not authenticated/configured | `opencode run "hi"` in a terminal; check `~/.config/opencode/opencode.jsonc` |

## Python environment

| symptom | cause | fix |
|---|---|---|
| `CUDAExecutionProvider is not in available provider names` | CPU `onnxruntime` shadows `onnxruntime-gpu` | `pip uninstall -y onnxruntime && pip install --force-reinstall --no-deps onnxruntime-gpu` |
| `chatterbox-tts requires numpy<2` / other pins broken | another package upgraded numpy/torch | `pip install "numpy<2"`; compare with `requirements-lock.txt`. Keep experimental tools (e.g. livekit-wakeword) in a separate env |
| `openwakeword requires tflite-runtime` in `pip check` | intentional (no py3.12 wheels) | ignore; ONNX runtime is used |
| faster-whisper `libcudnn` not found | cuDNN from torch wheels not loaded | the backend imports torch first; ensure torch is installed in the same env |

## Disk / downloads

- `hf download … --include "*.gguf"` on the Bonsai repos would fetch the 54 GB F16 files. Use the
  exact filenames (as `scripts/download_models.sh` does).
- Hugging Face downloads are unauthenticated and rate-limited; set `HF_TOKEN` for speed.

## Getting more detail

```bash
alveus talk -v                         # debug logging incl. ignored transcripts and VAD
tail -f ~/local/repo/alveus-ai/logs/alveus.log
python -m mcp_servers.system            # run a tool server alone; it waits on stdin
curl -s localhost:8080/health; curl -s localhost:8765/health
```
