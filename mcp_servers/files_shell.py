"""Filesystem + shell MCP server. Access is limited to ALVEUS_FS_ROOTS (colon separated)."""
from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from .common import FastMCP, annot, j, run

mcp = FastMCP("files")
ROOTS = [Path(os.path.expanduser(p)).resolve() for p in os.environ.get("ALVEUS_FS_ROOTS", "~").split(":") if p]
MAX_READ = 60_000


def _safe(path: str) -> Path:
    p = Path(os.path.expanduser(path)).resolve()
    if not any(p == r or r in p.parents for r in ROOTS):
        raise PermissionError(f"{p} is outside allowed roots {[str(r) for r in ROOTS]}")
    return p


@mcp.tool(annotations=annot(read_only=True))
def list_dir(path: str = "~", show_hidden: bool = False) -> str:
    """List files and folders in a directory with sizes."""
    p = _safe(path)
    if not p.is_dir():
        return j({"error": f"{p} is not a directory"})
    items = []
    for c in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        if not show_hidden and c.name.startswith("."):
            continue
        try:
            items.append({"name": c.name + ("/" if c.is_dir() else ""), "size": c.stat().st_size if c.is_file() else None})
        except OSError:
            continue
    return j({"path": str(p), "count": len(items), "items": items[:400]})


@mcp.tool(annotations=annot(read_only=True))
def read_file(path: str, start_line: int = 1, max_lines: int = 400) -> str:
    """Read a text file (optionally a line range)."""
    p = _safe(path)
    try:
        lines = p.read_text(errors="replace").splitlines()
    except Exception as e:  # noqa: BLE001
        return j({"error": str(e)})
    sel = lines[start_line - 1: start_line - 1 + max_lines]
    text = "\n".join(sel)
    return j({"path": str(p), "total_lines": len(lines), "from": start_line, "text": text[:MAX_READ]})


@mcp.tool()
def write_file(path: str, content: str, append: bool = False) -> str:
    """Create or overwrite (or append to) a text file. Parent folders are created."""
    p = _safe(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a" if append else "w") as f:
        f.write(content)
    return j({"written": str(p), "bytes": len(content.encode())})


@mcp.tool(annotations=annot(read_only=True))
def find_files(pattern: str, path: str = "~", max_results: int = 100) -> str:
    """Find files by glob pattern (e.g. '*.pdf', 'report*') under a folder, recursively."""
    root = _safe(path)
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("node_modules", "__pycache__")]
        for fn in filenames:
            if fnmatch.fnmatch(fn, pattern):
                out.append(str(Path(dirpath, fn)))
                if len(out) >= max_results:
                    return j({"results": out, "truncated": True})
    return j({"results": out, "truncated": False})


@mcp.tool(annotations=annot(read_only=True))
def search_text(query: str, path: str = "~", file_glob: str = "*", max_results: int = 50, regex: bool = False) -> str:
    """Search for text inside files (like grep -rn)."""
    root = _safe(path)
    rx = re.compile(query if regex else re.escape(query), re.IGNORECASE)
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("node_modules", "__pycache__")]
        for fn in filenames:
            if not fnmatch.fnmatch(fn, file_glob):
                continue
            fp = Path(dirpath, fn)
            try:
                if fp.stat().st_size > 5_000_000:
                    continue
                for i, line in enumerate(fp.read_text(errors="ignore").splitlines(), 1):
                    if rx.search(line):
                        hits.append({"file": str(fp), "line": i, "text": line.strip()[:200]})
                        if len(hits) >= max_results:
                            return j({"hits": hits, "truncated": True})
            except (OSError, UnicodeDecodeError):
                continue
    return j({"hits": hits, "truncated": False})


@mcp.tool(annotations=annot(destructive=True))
def move_path(src: str, dst: str) -> str:
    """Move or rename a file or folder."""
    s, d = _safe(src), _safe(dst)
    s.rename(d)
    return j({"moved": str(s), "to": str(d)})


@mcp.tool(annotations=annot(destructive=True))
def delete_path(path: str) -> str:
    """Delete a file or an empty folder. (Asks for confirmation.)"""
    p = _safe(path)
    if p.is_dir():
        p.rmdir()
    else:
        p.unlink()
    return j({"deleted": str(p)})


@mcp.tool()
def run_command(command: str, cwd: str = "~", timeout_s: int = 60) -> str:
    """Run a shell command (bash) and return its output. Destructive commands require confirmation."""
    c = _safe(cwd)
    res = run(command, timeout=timeout_s, shell=True, cwd=str(c))
    return j(res)


if __name__ == "__main__":
    mcp.run()
