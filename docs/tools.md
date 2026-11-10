# Tools (MCP)

Alveus gives the model tools through the **Model Context Protocol**. Each tool group is a
separate MCP server process started over stdio by `ToolHub` when the assistant starts (HTTP/SSE
servers are also supported). Tools are shown to the model as `server__tool` and executed with a
120 s timeout (per server: `call_timeout_s`; `images` uses 600 s); results are returned as text
(JSON from the built-in servers).

`alveus tools` prints the live list. Destructive tools (marked **!** below) require confirmation
when `tools.confirm_destructive` is on. `run_command` is additionally screened by a regex for
dangerous shell commands (`rm`, `kill`, `shutdown`, `dd`, `mkfs`, `git push --force`, …).
Any `run_command` that uses `sudo` always asks (regardless of `confirm_destructive`): the GUI card
takes the password for an "allow once", passes it to the tool as `sudo_password`, and the tool
rewrites the first `sudo` to `sudo -S -p ''` fed from stdin. The model cannot supply that argument
itself (it is stripped before the confirmation) and the password never enters the conversation
history or logs.

## `files` — `mcp_servers/files_shell.py`

Access is restricted to `ALVEUS_FS_ROOTS` (colon-separated; default `~`). Paths outside raise
`PermissionError`, which the model sees as an error message.

| tool | parameters | does |
|---|---|---|
| `list_dir` | `path="~"`, `show_hidden=false` | folders first, sizes, max 400 entries |
| `read_file` | `path`, `start_line=1`, `max_lines=400` | text with line range; 60 kB cap |
| `write_file` | `path`, `content`, `append=false` | creates parent folders |
| `find_files` | `pattern`, `path="~"`, `max_results=100` | recursive glob (`*.pdf`), skips dot-dirs/node_modules |
| `search_text` | `query`, `path="~"`, `file_glob="*"`, `max_results=50`, `regex=false` | grep-like, case-insensitive, skips files > 5 MB |
| `move_path` | `src`, `dst`, `overwrite=false` | rename/move; refuses to replace an existing file unless `overwrite`, which asks first |
| `delete_path` **!** | `path` | unlink file or remove empty dir |
| `run_command` | `command`, `cwd="~"`, `timeout_s=60` | bash, stdout/stderr/exit code; dangerous commands confirmed |

## `desktop` — `mcp_servers/desktop.py`

Uses stock GNOME/freedesktop tooling (`gio`, `gdbus`, `notify-send`, `wpctl`, `xdg-open`,
`gsettings`, `loginctl`). Window and input tools need `wmctrl`/`xdotool` (X11) and report what is
missing otherwise; `playerctl` improves media control but D-Bus MPRIS is used as fallback.

| tool | parameters | does |
|---|---|---|
| `list_apps` | `filter=""` | installed `.desktop` apps (system, user, snap, flatpak) |
| `launch_app` | `app`, `args=""` | match by desktop id or name, `gio launch`; falls back to a binary on PATH |
| `open_target` | `target` | `xdg-open` a URL, file or folder |
| `notify` | `title`, `body=""`, `urgency="normal"` | desktop notification |
| `clipboard_get` / `clipboard_set` | — / `text` | via `wl-paste`/`xclip`/`xsel` |
| `volume_get` | | `{volume 0-100, muted}` from `wpctl` |
| `volume_set` | `level`, `delta`, `mute` (all optional) | absolute, relative (±%), or mute toggle; capped at 100 % |
| `media_control` | `action` = play/pause/play_pause/next/previous/stop/status | MPRIS via playerctl or gdbus |
| `list_windows` | | `wmctrl -l` |
| `focus_window` | `title_substring` | raise window |
| `close_window` | `title_substring` | graceful close (apps with unsaved work ask themselves); no confirmation |
| `type_text` | `text` | `xdotool type` (X11 only) |
| `press_keys` | `keys` (xdotool syntax, e.g. `ctrl+s`) | `xdotool key` (X11 only) |
| `screenshot` | `path=""` | PNG via gnome-screenshot, GNOME Shell D-Bus, or ImageMagick `import` |
| `set_dark_mode` | `enabled` | GNOME colour scheme + Yaru theme |
| `do_not_disturb` | `enabled` | GNOME `show-banners` |
| `lock_screen` | | `loginctl lock-session` |

## `system` — `mcp_servers/system.py`

| tool | parameters | does |
|---|---|---|
| `system_status` | | host, OS, time, uptime, CPU %, load, CPU temp, RAM, root disk, GPUs, battery |
| `gpu_status` | | per-GPU name, temperature, utilisation, memory, power (NVML) |
| `top_processes` | `sort_by="cpu"|"memory"`, `limit=10` | heaviest processes |
| `find_process` | `name` | match on name or command line |
| `kill_process` **!** | `pid`, `force=false` | SIGTERM / SIGKILL |
| `list_services` | `scope="user"|"system"`, `state="running"|"failed"|"all"` | systemd units |
| `control_service` | `name`, `action` (start/stop/restart/enable/disable/status), `scope="user"` | systemctl; asks first only for stop/disable or system scope (which may also prompt polkit) |
| `network_info` | | IPv4 per interface, internet reachability (ping 1.1.1.1) |
| `power` **!** | `action` = suspend/hibernate/reboot/poweroff/lock | systemctl / loginctl |

## `web` — `mcp_servers/web.py`

| tool | parameters | does |
|---|---|---|
| `web_search` | `query`, `max_results=6`, `kind="text"|"news"` | DuckDuckGo via `ddgs` (title, url, snippet) |
| `fetch_page` | `url`, `max_chars=6000` | HTTP GET + `trafilatura` readable-text extraction (HTML-strip fallback); JSON passthrough |
| `weather` | `location=""` | wttr.in current conditions + 3-day forecast; empty = geo-IP |

These are the only tools that contact the internet.

## `coder` — `mcp_servers/coder.py`

Delegates programming work to **opencode** (`opencode run --format json`, headless; the desktop app
is not involved, but it shares opencode's config and credentials). Which model opencode uses is set by
`tools.servers.coder.env.ALVEUS_OPENCODE_MODEL` (GUI: Tools & safety → Coding model):
`auto` (default) requests the same model the assistant is running, so it follows `llm.profile`: for a
local profile via the `bonsai` provider in `~/.config/opencode/opencode.jsonc` (a new local model's id,
e.g. `qwen3.8-27b`, must be listed under that provider too), for a cloud profile as
`<opencode provider>/<model>` (e.g. `anthropic/claude-opus-5-5`; opencode must be signed in to that
provider with `opencode auth login`, or the profile sets `opencode_model`); `opencode-default` leaves
the choice to opencode; any `provider/model` id from `opencode models` (e.g. `deepseek/deepseek-v4-flash`)
sends the work to that model instead. The files/shell tools refuse the folder holding the API keys (`~/.config/alveus/`: reading,
listing, searching into it, and shell commands naming it); a casual-leak guard, not a sandbox.
The coder is the only tool server that sees API-key variables
from the environment (`inherit_api_keys: true`), since opencode may use them to sign in. `ALVEUS_CODE_DIR` is the coding folder: the tools' descriptions quote it so the model knows it, and
`directory` is resolved against it: empty, `~`, `.` or `default` mean the folder itself; a bare name
(`repo`, `repo/foo`) is looked up inside it (then under `~`); absolute and `~/…` paths are used as given.
An unknown name returns an error listing the folder's subdirectories so the model can pick one.

Note on the local server: llama-server loads one model and answers to whatever model id a client
sends, so a client that asks for `bonsai-27b-1bit` while the ternary profile is running silently gets
the ternary model under the wrong label. `auto` avoids this for the coder by always requesting the
running profile's id.

| tool | parameters | does |
|---|---|---|
| `code_task` | `task`, `directory=""`, `continue_last=false`, `timeout_s=900` | full agentic coding run in that directory (reads, edits, runs); returns opencode's final message, tools used, session id. `continue_last` resumes the previous session in the same directory |
| `code_question` | `question`, `directory=""`, `timeout_s=300` | read-only analysis with opencode's `plan` agent |
| `git_status` | `directory=""` | `git status --short --branch` + last 5 commits |

## `images` — `mcp_servers/comfy.py`

Makes and redraws pictures by running ComfyUI workflows over its HTTP API (ComfyUI must be running:
here the user unit `comfyui.service` on `http://127.0.0.1:8188`). The pictures are saved in
`ALVEUS_IMAGES_DIR` (default `~/local/data/alveus-ai/images`) and shown in the GUI chat under the
tool card (click for full size); the GUI serves them at `/images/file?name=…`.

| tool | parameters | does |
|---|---|---|
| `generate_image` | `prompt`, `width=1024`, `height=1024`, `seed=-1`, `steps=0` | text to image with `ALVEUS_COMFY_GENERATE` (default Z-Image Turbo, 8 steps); sizes are rounded to multiples of 16 (256–2048); returns path, `image_url`, seed, seconds |
| `edit_image` | `prompt`, `image=""`, `strength=0.75`, `size=1024`, `seed=-1` | image to image with `ALVEUS_COMFY_EDIT` (default Z-Image Turbo + Fun ControlNet Union on Canny edges): keeps the outlines, repaints the rest from the prompt. `image` is a path, a name in the image folder, or empty for the newest picture; it is scaled to `size` on the long side. `strength` = how strictly the edges are followed |
| `recent_images` | `limit=10` | the newest pictures in the folder |

**Workflows.** Both are API-format exports (ComfyUI GUI: Workflow → Export (API)) in `config/comfy/`;
a GUI-format file is refused with that hint. Parameters are placed by node type, not node id: the
prompt into every text encoder that feeds a sampler's *positive* input (followed through
ControlNet/unCLIP conditioning nodes; negatives are left alone), seed and steps into the samplers,
width/height into the `Empty…Latent…` node, the picture into `LoadImage`, strength into the
ControlNet node (or, in a plain image-to-image export whose latent comes from `VAEEncode`, into the
sampler's denoise). So other exports in `config/comfy/` (SDXL, Qwen-Image 2512) work by pointing
the setting at them. `SaveImage` nodes become `PreviewImage` and other previews are dropped, so
ComfyUI's own `output/` folder only holds what its GUI made; Alveus fetches the result from
ComfyUI's temp folder via `/view`. Input pictures are uploaded to ComfyUI's `input/alveus/input.png`.

**What editing can do.** The Fun ControlNet redraws from the Canny edge map: style, colours,
materials, lighting, season, or another animal/person in the same pose all work; erasing or adding
one object does not (that needs an inpainting or instruction-editing model such as Qwen-Image-Edit).
The tool description tells the model to describe the whole result, not the change.

**Stopping.** Interrupt, the header Stop button, the hotkey or the wake word cancel the tool call
(Alveus's agent cancels it and the MCP client sends `notifications/cancelled`); the server then
deletes its own job from ComfyUI's queue or interrupts it by `prompt_id`, so a job started in
ComfyUI's GUI keeps running. The model gets `{"cancelled": true, "message": "Stopped by the user…"}`.

**GPU memory.** Z-Image Turbo bf16 + its Qwen3-4B text encoder take about 8 GB on the GPU while
loaded (ComfyUI offloads the rest to RAM). After `ALVEUS_COMFY_UNLOAD_AFTER_S` idle seconds (default
120; 0 = after each picture, -1 = never) the server calls ComfyUI's `POST /free`, and it also does so
when Alveus stops before the delay is up. Measured beside Whisper large-v3 + Qwen3-TTS + LFM3:
1024×768 in 4.5 s with the model loaded, 12–14 s when it has to load again; an edit 6.5–14 s.

| env (`tools.servers.images.env`) | default |
|---|---|
| `ALVEUS_COMFY_URL` | `http://127.0.0.1:8188` |
| `ALVEUS_IMAGES_DIR` | `~/local/data/alveus-ai/images` |
| `ALVEUS_COMFY_GENERATE` | `${ALVEUS_HOME}/config/comfy/txt2img_z_image_turbo_demo.json` |
| `ALVEUS_COMFY_EDIT` | `${ALVEUS_HOME}/config/comfy/img2img_z_image_turbo_fun_union_controlnet_demo.json` |
| `ALVEUS_COMFY_UNLOAD_AFTER_S` | `120` |
| `ALVEUS_COMFY_TIMEOUT_S` | `540` (one job; it is interrupted after that) |

All are in the GUI under Settings → Tools & safety → Image tools.

## Adding third-party MCP servers

Anything that speaks MCP works. In `config/local.yaml`:

```yaml
tools:
  servers:
    home-assistant:                     # remote SSE server
      url: http://homeassistant.local:8123/mcp_server/sse
      headers: { Authorization: "Bearer ${HASS_TOKEN}" }
    github:                             # stdio server from npm
      command: [npx, -y, "@modelcontextprotocol/server-github"]
      env: { GITHUB_PERSONAL_ACCESS_TOKEN: "${GITHUB_TOKEN}" }
    obsidian:
      command: [uvx, mcp-obsidian]
      env: { OBSIDIAN_API_KEY: "${OBSIDIAN_KEY}" }
      enabled: false
```

`${VAR}` values are taken from the environment of the `alveus` process (add
`Environment=` lines to the systemd unit or export before `alveus talk`). Restart the assistant
and run `alveus tools` to confirm the new tools appear. Keep the total tool count reasonable
(the schemas are sent with every request; ~40–60 tools is fine for a 32k context).

## Writing your own server

Copy any file in `mcp_servers/`, e.g.:

```python
from .common import FastMCP, annot, j, run

mcp = FastMCP("lights")

@mcp.tool(annotations=annot(read_only=True))
def light_status(room: str) -> str:
    """Report whether the lights in a room are on."""
    return j({"room": room, "on": True})

@mcp.tool(annotations=annot(destructive=True))
def all_off() -> str:
    """Turn every light off. (Confirmed with the user.)"""
    return j(run(["my-lights", "off"]))

if __name__ == "__main__":
    mcp.run()
```

Register it: `tools.servers.lights.command: [python, -m, mcp_servers.lights]`.
Guidelines: keep docstrings short and concrete (the model reads them), return JSON text, mark
irreversible tools destructive, never block for long without a timeout, and prefer
parameters with defaults so the model can call tools with few arguments. `common.py`
wraps `MCPServer`/`FastMCP` and `ToolAnnotations` so the same code runs on mcp 1.x and 2.x.
