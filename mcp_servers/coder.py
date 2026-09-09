"""Coder MCP server: delegates programming tasks to opencode (headless `opencode run`)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .common import FastMCP, annot, j

mcp = FastMCP("coder")
OPENCODE = shutil.which("opencode") or os.path.expanduser("~/.opencode/bin/opencode")
LOCAL_PROVIDER = os.environ.get("ALVEUS_OPENCODE_LOCAL_PROVIDER", "bonsai")  # provider id in opencode.jsonc
DEFAULT_DIR = os.environ.get("ALVEUS_CODE_DIR") or "~"
_last_session: dict[str, str] = {}


def _model() -> str:
    """Which opencode model to request (provider/model), from ALVEUS_OPENCODE_MODEL:
    auto (or empty)   -> the same local model Alveus itself is running (ALVEUS_LLM_MODEL, set by the
                         tool hub), so switching the assistant's profile switches the coder too
    opencode-default  -> whatever opencode.jsonc / the desktop app has as default (no --model)
    provider/model    -> that model, e.g. deepseek/deepseek-v4-flash (needs opencode auth for it)
    """
    v = os.environ.get("ALVEUS_OPENCODE_MODEL", "auto").strip()
    if v in ("", "auto"):
        local = os.environ.get("ALVEUS_LLM_MODEL", "").strip()
        return f"{LOCAL_PROVIDER}/{local}" if local else ""
    if v == "opencode-default":
        return ""
    return v


MODEL = _model()


def _run(args: list[str], cwd: str, timeout: int) -> dict:
    try:
        p = subprocess.run([OPENCODE, *args, "--dir", cwd], cwd=cwd, capture_output=True, text=True,
                           timeout=timeout, env={**os.environ, "NO_COLOR": "1", "PWD": cwd})
        return {"exit_code": p.returncode, "stdout": p.stdout[-15000:], "stderr": p.stderr[-3000:]}
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "error": f"opencode timed out after {timeout}s"}
    except FileNotFoundError:
        return {"exit_code": -1, "error": "opencode is not installed (https://opencode.ai)"}


@mcp.tool()
def code_task(task: str, directory: str = "", continue_last: bool = False, timeout_s: int = 900) -> str:
    """Delegate a coding task to the opencode agent in a project directory (it can read, write
    and run code there). Returns opencode's final summary. Use continue_last to follow up.
    directory defaults to the configured coding folder."""
    cwd = os.path.expanduser(directory or DEFAULT_DIR)
    if not Path(cwd).is_dir():
        return j({"error": f"{cwd} is not a directory"})
    args = ["run", "--format", "json"]
    if MODEL:
        args += ["--model", MODEL]
    if continue_last and _last_session.get(cwd):
        args += ["--session", _last_session[cwd]]
    args.append(task)
    res = _run(args, cwd, timeout_s)
    if res.get("exit_code") not in (0, None) and not res.get("stdout"):
        return j({"error": res.get("error") or res.get("stderr", "")[-800:], "model": MODEL or "opencode default"})
    texts, session_id, tools = [], None, []
    for line in res.get("stdout", "").splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        session_id = session_id or ev.get("sessionID") or (ev.get("properties") or {}).get("sessionID")
        t = ev.get("type", "")
        part = ev.get("part") or (ev.get("properties") or {}).get("part") or {}
        if t in ("text", "message.part.updated") and part.get("type") == "text" and part.get("text"):
            texts.append(part["text"])
        elif part.get("type") == "tool":
            tools.append(part.get("tool"))
    if session_id:
        _last_session[cwd] = session_id
    summary = texts[-1] if texts else res.get("stdout", "")[-3000:]
    return j({"exit_code": res.get("exit_code"), "model": MODEL or "opencode default", "summary": summary, "tools_used": sorted({t for t in tools if t}),
              "session": session_id, "stderr": res.get("stderr", "")[-800:] if res.get("exit_code") else ""})


@mcp.tool(annotations=annot(read_only=True))
def code_question(question: str, directory: str = "", timeout_s: int = 300) -> str:
    """Ask opencode a read-only question about a codebase (explain, find, review).
    directory defaults to the configured coding folder."""
    cwd = os.path.expanduser(directory or DEFAULT_DIR)
    args = ["run", "--format", "json", "--agent", "plan"]
    if MODEL:
        args += ["--model", MODEL]
    args.append(question)
    res = _run(args, cwd, timeout_s)
    texts = []
    for line in res.get("stdout", "").splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        part = ev.get("part") or (ev.get("properties") or {}).get("part") or {}
        if part.get("type") == "text" and part.get("text"):
            texts.append(part["text"])
    return j({"answer": texts[-1] if texts else res.get("stdout", "")[-3000:], "exit_code": res.get("exit_code")})


@mcp.tool(annotations=annot(read_only=True))
def git_status(directory: str = ".") -> str:
    """Short git status + last 5 commits for a repo."""
    cwd = os.path.expanduser(directory)
    st = subprocess.run(["git", "status", "--short", "--branch"], cwd=cwd, capture_output=True, text=True)
    lg = subprocess.run(["git", "log", "--oneline", "-5"], cwd=cwd, capture_output=True, text=True)
    return j({"status": st.stdout or st.stderr, "log": lg.stdout})


if __name__ == "__main__":
    mcp.run()
