"""ToolHub: connects to many MCP servers (stdio or HTTP) and exposes their tools
to the LLM under namespaced names ``<server>__<tool>``."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

log = logging.getLogger(__name__)


@dataclass
class ToolInfo:
    server: str
    name: str            # original tool name on the server
    full_name: str       # namespaced name shown to the LLM
    description: str
    schema: dict[str, Any]
    destructive: bool = False
    read_only: bool = False
    annotations: dict[str, Any] = field(default_factory=dict)

    def as_openai(self) -> dict[str, Any]:
        params = self.schema or {"type": "object", "properties": {}}
        params.setdefault("type", "object")
        params.setdefault("properties", {})
        return {
            "type": "function",
            "function": {
                "name": self.full_name,
                "description": (self.description or "")[:1024],
                "parameters": params,
            },
        }


def secret_env_names() -> set[str]:
    """Variable names that hold LLM API keys (provider presets plus the common ones)."""
    from ..llm.providers import PROVIDERS
    names = {p["api_key_env"] for p in PROVIDERS.values() if p.get("api_key_env")}
    names |= {"ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY", "MISTRAL_API_KEY",
              "TOGETHER_API_KEY", "XAI_API_KEY"}
    return names


def hub_env(cfg) -> dict[str, str]:
    """Environment handed to every stdio MCP server: where Alveus lives and which LLM it runs."""
    from ..config import llm_profile
    env = {"ALVEUS_HOME": cfg._env["ALVEUS_HOME"]}
    api = cfg.get("api") or {}
    env["ALVEUS_API_URL"] = f"http://{api.get('host', '127.0.0.1')}:{api.get('port', 8765)}"
    try:
        prof = llm_profile(cfg)
        env["ALVEUS_LLM_PROFILE"] = str(prof.get("name", ""))
        env["ALVEUS_LLM_PROVIDER"] = str(prof.get("provider", ""))
        env["ALVEUS_LLM_MODEL"] = str(prof.get("model", ""))
        env["ALVEUS_LLM_BASE_URL"] = str(prof.get("base_url") or "")
        # what the coder tool's "auto" means: the same model in opencode's naming (provider/model).
        # Empty for local servers: coder.py then uses its local provider (bonsai) with ALVEUS_LLM_MODEL.
        oc = prof.get("opencode_model") or (
            f"{prof['opencode_provider']}/{prof.get('model')}" if prof.get("opencode_provider") else "")
        env["ALVEUS_OPENCODE_AUTO"] = str(oc)
    except KeyError:
        pass
    # API keys are deliberately not passed on (see alveus/credentials.py)
    return env


class ToolHub:
    SEP = "__"

    def __init__(self, servers_cfg: dict[str, Any], repo_root: str, env_extra: dict[str, str] | None = None):
        self.servers_cfg = servers_cfg or {}
        self.repo_root = repo_root
        self.env_extra = env_extra or {}
        self._stack = AsyncExitStack()
        self.sessions: dict[str, ClientSession] = {}
        self.tools: dict[str, ToolInfo] = {}
        self.errors: dict[str, str] = {}

    # ------------------------------------------------------------------ lifecycle
    async def __aenter__(self) -> ToolHub:
        await self.connect_all()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        try:
            await self._stack.aclose()
        except Exception as e:  # noqa: BLE001
            log.debug("ToolHub close: %s", e)
        self.sessions.clear()

    async def connect_all(self) -> None:
        for name, cfg in self.servers_cfg.items():
            if cfg.get("enabled", True) is False:
                continue
            try:
                await asyncio.wait_for(self._connect(name, cfg), timeout=float(cfg.get("timeout_s", 60)))
            except Exception as e:  # noqa: BLE001
                self.errors[name] = f"{type(e).__name__}: {e}"
                log.warning("MCP server '%s' failed to start: %s", name, self.errors[name])

    def server_env(self, cfg: dict[str, Any]) -> dict[str, str]:
        """Environment for a stdio server: ours, minus LLM API keys (the shell tool could print them;
        a server that needs them, coder -> opencode, sets inherit_api_keys), plus hub and server vars."""
        env = dict(os.environ)
        if not cfg.get("inherit_api_keys", False):
            for k in secret_env_names():
                env.pop(k, None)
        env.update({k: str(v) for k, v in self.env_extra.items()})
        env.update({k: os.path.expanduser(str(v)) for k, v in (cfg.get("env") or {}).items()})
        env.setdefault("PYTHONPATH", self.repo_root)
        return env

    async def _connect(self, name: str, cfg: dict[str, Any]) -> None:
        if cfg.get("command"):
            cmd = cfg["command"]
            if isinstance(cmd, str):
                cmd = shlex.split(cmd)
            cmd = list(cmd)
            if cmd[0] == "python":
                cmd[0] = sys.executable
            params = StdioServerParameters(command=cmd[0], args=cmd[1:], env=self.server_env(cfg),
                                           cwd=cfg.get("cwd") or self.repo_root)
            read, write = await self._stack.enter_async_context(stdio_client(params, errlog=sys.stderr))
        elif cfg.get("url"):
            url = cfg["url"]
            headers = cfg.get("headers") or None
            if url.rstrip("/").endswith("/sse"):
                from mcp.client.sse import sse_client
                read, write = await self._stack.enter_async_context(sse_client(url, headers=headers))
            else:
                from mcp.client.streamable_http import streamablehttp_client
                read, write, _ = await self._stack.enter_async_context(
                    streamablehttp_client(url, headers=headers))
        else:
            raise ValueError("server config needs 'command' or 'url'")

        session = await self._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self.sessions[name] = session
        result = await session.list_tools()
        for t in result.tools:
            ann = t.annotations.model_dump() if getattr(t, "annotations", None) else {}
            schema = getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {}
            info = ToolInfo(
                server=name,
                name=t.name,
                full_name=f"{name}{self.SEP}{t.name}",
                description=t.description or "",
                schema=dict(schema),
                destructive=bool(ann.get("destructive_hint", ann.get("destructiveHint", False))),
                read_only=bool(ann.get("read_only_hint", ann.get("readOnlyHint", False))),
                annotations=ann,
            )
            self.tools[info.full_name] = info
        log.info("MCP '%s': %d tools", name, len(result.tools))

    # ------------------------------------------------------------------ use
    def openai_tools(self, allow: set[str] | None = None) -> list[dict[str, Any]]:
        return [t.as_openai() for n, t in self.tools.items() if allow is None or n in allow]

    def get(self, full_name: str) -> ToolInfo | None:
        return self.tools.get(full_name)

    async def call(self, full_name: str, arguments: dict[str, Any] | str | None, timeout_s: float = 120) -> str:
        info = self.tools.get(full_name)
        if info is None:
            return json.dumps({"error": f"unknown tool '{full_name}'"})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError as e:
                return json.dumps({"error": f"invalid JSON arguments: {e}"})
        session = self.sessions[info.server]
        try:
            res = await asyncio.wait_for(session.call_tool(info.name, arguments or {}), timeout=timeout_s)
        except TimeoutError:
            return json.dumps({"error": f"tool '{full_name}' timed out after {timeout_s}s"})
        except Exception as e:  # noqa: BLE001
            return json.dumps({"error": f"{type(e).__name__}: {e}"})
        parts: list[str] = []
        for c in getattr(res, "content", None) or []:
            if getattr(c, "type", "") == "text":
                parts.append(c.text)
            elif getattr(c, "type", "") == "image":
                parts.append(f"[image {getattr(c, 'mimeType', '')} omitted]")
            else:
                parts.append(str(c))
        text = "\n".join(parts) if parts else "(no output)"
        if getattr(res, "is_error", False) or getattr(res, "isError", False):
            text = json.dumps({"error": text})
        return text
