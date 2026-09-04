"""GNOME / Linux desktop control MCP server.

Uses freedesktop + GNOME tooling that is present on stock Ubuntu (gio, gdbus, notify-send,
wpctl, xdg-open, gsettings). Window management / key injection use xdotool + wmctrl on X11 when
installed; on Wayland those tools report what is missing instead of failing silently.
"""
from __future__ import annotations

import datetime as dt
import os
import shlex
import subprocess
import tempfile
from pathlib import Path

from .common import FastMCP, annot, have, j, missing, run

mcp = FastMCP("desktop")
IS_WAYLAND = os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"


# ------------------------------------------------------------------ apps & files
@mcp.tool(annotations=annot(read_only=True))
def list_apps(filter: str = "") -> str:
    """List installed desktop applications (name -> desktop id). Optional substring filter."""
    apps = {}
    for d in (Path("/usr/share/applications"), Path.home() / ".local/share/applications",
              Path("/var/lib/snapd/desktop/applications"), Path("/var/lib/flatpak/exports/share/applications")):
        if not d.is_dir():
            continue
        for f in d.glob("*.desktop"):
            try:
                txt = f.read_text(errors="ignore")
            except OSError:
                continue
            if "NoDisplay=true" in txt:
                continue
            name = next((ln[5:] for ln in txt.splitlines() if ln.startswith("Name=")), f.stem)
            if not filter or filter.lower() in name.lower() or filter.lower() in f.stem.lower():
                apps[name] = f.name
    return j(dict(sorted(apps.items())[:300]))


@mcp.tool()
def launch_app(app: str, args: str = "") -> str:
    """Launch an application by name (e.g. 'firefox', 'Files', 'terminal') or desktop id."""
    # 1) desktop entry match
    cands = []
    for d in (Path("/usr/share/applications"), Path.home() / ".local/share/applications",
              Path("/var/lib/snapd/desktop/applications")):
        if d.is_dir():
            cands += list(d.glob("*.desktop"))
    low = app.lower()
    match = None
    for f in cands:
        if f.stem.lower() == low or f.name.lower() == low:
            match = f
            break
    if match is None:
        for f in cands:
            try:
                txt = f.read_text(errors="ignore")
            except OSError:
                continue
            name = next((ln[5:] for ln in txt.splitlines() if ln.startswith("Name=")), "")
            if name.lower() == low or low in f.stem.lower() or low in name.lower():
                if "NoDisplay=true" not in txt:
                    match = f
                    break
    if match is not None:
        cmd = ["gio", "launch", str(match)] + (shlex.split(args) if args else [])
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return j({"launched": match.name})
    if have(app.split()[0]):
        subprocess.Popen(shlex.split(app) + (shlex.split(args) if args else []),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return j({"launched": app})
    return j({"error": f"no application matching '{app}'"})


@mcp.tool()
def open_target(target: str) -> str:
    """Open a URL, file or folder with the default application (xdg-open)."""
    t = os.path.expanduser(target)
    subprocess.Popen(["xdg-open", t], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return j({"opened": t})


# ------------------------------------------------------------------ notifications / clipboard
@mcp.tool()
def notify(title: str, body: str = "", urgency: str = "normal") -> str:
    """Show a desktop notification."""
    return j(run(["notify-send", "-u", urgency, "-a", "Alveus", title, body]))


@mcp.tool(annotations=annot(read_only=True))
def clipboard_get() -> str:
    """Read the current clipboard text."""
    for cmd in (["wl-paste", "--no-newline"], ["xclip", "-selection", "clipboard", "-o"], ["xsel", "-b", "-o"]):
        if have(cmd[0]):
            r = run(cmd, timeout=5)
            if r.get("exit_code") == 0:
                return j({"text": r["stdout"][:10000]})
    return j({"error": missing("xclip") or "clipboard read failed"})


@mcp.tool()
def clipboard_set(text: str) -> str:
    """Put text on the clipboard."""
    for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "-b", "-i"]):
        if have(cmd[0]):
            r = run(cmd, timeout=5, input_text=text)
            if r.get("exit_code") == 0:
                return j({"copied_chars": len(text)})
    return j({"error": missing("xclip") or "clipboard write failed"})


# ------------------------------------------------------------------ audio / media
@mcp.tool(annotations=annot(read_only=True))
def volume_get() -> str:
    """Current output volume (0-100) and mute state."""
    r = run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
    out = r.get("stdout", "")
    try:
        vol = int(round(float(out.split()[1]) * 100))
    except (IndexError, ValueError):
        return j(r)
    return j({"volume": vol, "muted": "[MUTED]" in out})


@mcp.tool()
def volume_set(level: int | None = None, delta: int | None = None, mute: bool | None = None) -> str:
    """Set output volume to `level` (0-100), change it by `delta` (+/-), or (un)mute."""
    if mute is not None:
        run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if mute else "0"])
    if level is not None:
        run(["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", f"{max(0, min(100, level))}%"])
    elif delta is not None:
        run(["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", f"{abs(delta)}%{'+' if delta >= 0 else '-'}"])
    return volume_get()


@mcp.tool()
def media_control(action: str) -> str:
    """Control the active media player via MPRIS: play | pause | play_pause | next | previous | stop | status."""
    if have("playerctl"):
        if action == "status":
            r = run(["playerctl", "metadata", "--format", "{{playerName}}: {{status}} - {{artist}} - {{title}}"])
        else:
            r = run(["playerctl", action.replace("play_pause", "play-pause")])
        return j(r)
    # fallback: raw D-Bus to the first MPRIS player
    names = run(["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus", "--object-path", "/org/freedesktop/DBus",
                 "--method", "org.freedesktop.DBus.ListNames"]).get("stdout", "")
    players = [n.strip("'\" ") for n in names.strip("()\n").split(",") if "org.mpris.MediaPlayer2." in n]
    if not players:
        return j({"error": "no media player running"})
    p = players[0].strip("'")
    meth = {"play": "Play", "pause": "Pause", "play_pause": "PlayPause", "next": "Next", "previous": "Previous", "stop": "Stop"}
    if action == "status":
        r = run(["gdbus", "call", "--session", "--dest", p, "--object-path", "/org/mpris/MediaPlayer2", "--method",
                 "org.freedesktop.DBus.Properties.Get", "org.mpris.MediaPlayer2.Player", "PlaybackStatus"])
        return j({"player": p, **r})
    if action not in meth:
        return j({"error": "bad action"})
    return j({"player": p, **run(["gdbus", "call", "--session", "--dest", p, "--object-path", "/org/mpris/MediaPlayer2",
                                  "--method", f"org.mpris.MediaPlayer2.Player.{meth[action]}"])})


# ------------------------------------------------------------------ windows / input (X11: xdotool, wmctrl)
@mcp.tool(annotations=annot(read_only=True))
def list_windows() -> str:
    """List open windows (title, id, desktop)."""
    if have("wmctrl"):
        r = run(["wmctrl", "-l"])
        wins = []
        for ln in r.get("stdout", "").splitlines():
            parts = ln.split(None, 3)
            if len(parts) == 4:
                wins.append({"id": parts[0], "desktop": parts[1], "title": parts[3]})
        return j(wins)
    return j({"error": missing("wmctrl") or "unsupported"})


@mcp.tool()
def focus_window(title_substring: str) -> str:
    """Bring the first window whose title contains the text to the front."""
    if have("wmctrl"):
        return j(run(["wmctrl", "-a", title_substring]))
    if have("xdotool"):
        return j(run(["xdotool", "search", "--name", title_substring, "windowactivate"]))
    return j({"error": missing("wmctrl", "xdotool")})


@mcp.tool(annotations=annot(destructive=True))
def close_window(title_substring: str) -> str:
    """Close the first window whose title contains the text."""
    if have("wmctrl"):
        return j(run(["wmctrl", "-c", title_substring]))
    return j({"error": missing("wmctrl")})


@mcp.tool()
def type_text(text: str) -> str:
    """Type text into the focused window (X11 via xdotool)."""
    if have("xdotool") and not IS_WAYLAND:
        return j(run(["xdotool", "type", "--delay", "12", "--", text]))
    return j({"error": missing("xdotool") or "typing not supported on Wayland without ydotool"})


@mcp.tool()
def press_keys(keys: str) -> str:
    """Send a key combination to the focused window, e.g. 'ctrl+s', 'alt+F4', 'super' (xdotool syntax)."""
    if have("xdotool") and not IS_WAYLAND:
        return j(run(["xdotool", "key", "--", keys]))
    return j({"error": missing("xdotool") or "key injection not supported on Wayland"})


@mcp.tool(annotations=annot(read_only=True))
def screenshot(path: str = "") -> str:
    """Take a screenshot of the whole screen and return the PNG path."""
    out = os.path.expanduser(path) if path else str(Path(tempfile.gettempdir()) / f"alveus-{dt.datetime.now():%Y%m%d-%H%M%S}.png")
    if have("gnome-screenshot"):
        r = run(["gnome-screenshot", "-f", out])
    else:
        r = run(["gdbus", "call", "--session", "--dest", "org.gnome.Shell.Screenshot", "--object-path",
                 "/org/gnome/Shell/Screenshot", "--method", "org.gnome.Shell.Screenshot.Screenshot", "false", "false", out])
        if r.get("exit_code") != 0 and have("import"):
            r = run(["import", "-window", "root", out])
    return j({"path": out} if Path(out).exists() else {"error": r})


# ------------------------------------------------------------------ settings
@mcp.tool()
def set_dark_mode(enabled: bool) -> str:
    """Switch GNOME between dark and light appearance."""
    scheme = "prefer-dark" if enabled else "default"
    run(["gsettings", "set", "org.gnome.desktop.interface", "color-scheme", scheme])
    run(["gsettings", "set", "org.gnome.desktop.interface", "gtk-theme", "Yaru-dark" if enabled else "Yaru"])
    return j({"color_scheme": scheme})


@mcp.tool()
def do_not_disturb(enabled: bool) -> str:
    """Enable or disable GNOME notification banners (Do Not Disturb)."""
    r = run(["gsettings", "set", "org.gnome.desktop.notifications", "show-banners", "false" if enabled else "true"])
    return j({"do_not_disturb": enabled, **r})


@mcp.tool()
def lock_screen() -> str:
    """Lock the screen."""
    return j(run(["loginctl", "lock-session"]))


if __name__ == "__main__":
    mcp.run()
