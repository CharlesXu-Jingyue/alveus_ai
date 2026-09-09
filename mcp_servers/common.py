from __future__ import annotations

import functools
import inspect
import json
import shutil
import subprocess
from typing import Any

try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as _BaseMCP
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _BaseMCP  # type: ignore
from mcp.types import ToolAnnotations


class FastMCP(_BaseMCP):
    """MCPServer whose tools return the real error text.

    The SDK turns an exception inside a tool into the bare message "Error executing tool X", which
    tells the model nothing and makes it retry the same call. Every tool registered through this
    class is wrapped so an exception comes back as {"error": "ExceptionType: message"} instead.
    """

    def tool(self, *args, **kwargs):
        deco = super().tool(*args, **kwargs)

        def register(fn):
            if inspect.iscoroutinefunction(fn):
                @functools.wraps(fn)
                async def safe(*a, **kw):
                    try:
                        return await fn(*a, **kw)
                    except Exception as e:  # noqa: BLE001
                        return j({"error": f"{type(e).__name__}: {e}"})
            else:
                @functools.wraps(fn)
                def safe(*a, **kw):
                    try:
                        return fn(*a, **kw)
                    except Exception as e:  # noqa: BLE001
                        return j({"error": f"{type(e).__name__}: {e}"})
            return deco(safe)

        return register


def annot(read_only: bool = False, destructive: bool = False) -> ToolAnnotations:
    """ToolAnnotations that work on mcp 1.x (camelCase) and 2.x (snake_case)."""
    try:
        return ToolAnnotations(read_only_hint=read_only, destructive_hint=destructive)
    except Exception:  # noqa: BLE001
        return ToolAnnotations(readOnlyHint=read_only, destructiveHint=destructive)


def run(cmd: list[str] | str, timeout: int = 30, shell: bool = False, cwd: str | None = None,
        input_text: str | None = None) -> dict[str, Any]:
    try:
        p = subprocess.run(cmd, shell=shell, capture_output=True, text=True, timeout=timeout, cwd=cwd,
                           input=input_text)
        out = p.stdout[-12000:]
        err = p.stderr[-4000:]
        return {"exit_code": p.returncode, "stdout": out, "stderr": err}
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "error": f"timed out after {timeout}s"}
    except FileNotFoundError as e:
        return {"exit_code": -1, "error": f"command not found: {e.filename}"}


def have(binary: str) -> bool:
    return shutil.which(binary) is not None


def j(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def missing(*bins: str) -> str | None:
    m = [b for b in bins if not have(b)]
    return f"missing tools: {', '.join(m)} (install with your package manager)" if m else None
