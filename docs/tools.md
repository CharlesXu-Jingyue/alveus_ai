# Tools (MCP)

Alveus gives the model tools through the **Model Context Protocol**. Each tool group is a
separate MCP server process started over stdio by `ToolHub` when the assistant starts (HTTP/SSE
servers are also supported). Tools are shown to the model as `server__tool` and executed with a
120 s timeout; results are returned as text (JSON from the built-in servers).

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
| `move_path` **!** | `src`, `dst` | rename/move |
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
| `close_window` **!** | `title_substring` | graceful close |
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
| `control_service` **!** | `name`, `action` (start/stop/restart/enable/disable/status), `scope="user"` | systemctl; system scope may prompt polkit |
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
`auto` (default) requests the same local Bonsai model the assistant is running, via the `bonsai`
provider in `~/.config/opencode/opencode.jsonc`, so it follows `llm.profile`; `opencode-default` leaves
the choice to opencode; any `provider/model` id from `opencode models` (e.g. `deepseek/deepseek-v4-flash`)
sends the work to that model instead. `ALVEUS_CODE_DIR` is the project folder used when the request
names none.

Note on the local server: llama-server loads one model and answers to whatever model id a client
sends, so a client that asks for `bonsai-27b-1bit` while the ternary profile is running silently gets
the ternary model under the wrong label. `auto` avoids this for the coder by always requesting the
running profile's id.

| tool | parameters | does |
|---|---|---|
| `code_task` | `task`, `directory="~"`, `continue_last=false`, `timeout_s=900` | full agentic coding run in that directory (reads, edits, runs); returns opencode's final message, tools used, session id. `continue_last` resumes the previous session in the same directory |
| `code_question` | `question`, `directory="~"`, `timeout_s=300` | read-only analysis with opencode's `plan` agent |
| `git_status` | `directory="."` | `git status --short --branch` + last 5 commits |

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
