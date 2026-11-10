"""Which models a provider offers, for the settings page's model picker.

  llama_server         GGUF files under ALVEUS_MODELS/llm (or ALVEUS_MODELS itself when it has no llm
                       folder); vision projectors (``mmproj*``) and draft models for speculative
                       decoding (DSpark, FastMTP, ``*draft*``) are skipped, they are not chat models
  cloud / servers      the provider's live list (``GET /models``; Anthropic through the SDK), with
                       the suggested notes from PROVIDER_INFO attached; when the list cannot be fetched
                       (no key yet, offline) the suggested models are returned instead

Listing models is free at every provider used here. Results are cached for 10 minutes.
"""
from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx

from .. import credentials
from .providers import PROVIDER_INFO, PROVIDERS

log = logging.getLogger(__name__)

_CACHE: dict[tuple, tuple[float, dict[str, Any]]] = {}
TTL = 600.0
# companion files next to a model: vision projectors and speculative-decoding drafters
_NOT_A_CHAT_MODEL = re.compile(r"(mmproj|dspark|fastmtp|draft)", re.I)
# OpenAI's /models also lists embedding, audio, image and moderation models
_OPENAI_SKIP = re.compile(r"(audio|realtime|tts|transcribe|image|embedding|moderation|whisper|dall-e|search|"
                          r"babbage|davinci|instruct|computer-use)", re.I)


def slug(s: str) -> str:
    """Profile / alias name from a model id or file name."""
    s = re.sub(r"[^a-z0-9._-]+", "-", str(s).lower()).strip("-.")
    return s or "model"


def llm_dir(models_dir: str) -> Path:
    """Where the GGUF files live: ALVEUS_MODELS/llm, or ALVEUS_MODELS itself (older layout)."""
    root = Path(os.path.expanduser(models_dir))
    return root / "llm" if (root / "llm").is_dir() else root


def local_files(models_dir: str) -> list[dict[str, Any]]:
    root = Path(os.path.expanduser(models_dir))
    out = []
    if not root.is_dir():
        return out
    for p in sorted(llm_dir(models_dir).rglob("*.gguf")):
        if _NOT_A_CHAT_MODEL.search(p.name) or not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        out.append({"id": slug(p.stem), "file": p.name, "path": str(p), "portable": f"${{ALVEUS_MODELS}}/{rel}",
                    "size_gb": round(p.stat().st_size / 1e9, 1)})
    return out


def _suggested(provider: str) -> list[dict[str, Any]]:
    return [dict(m) for m in PROVIDER_INFO.get(provider, {}).get("models") or []]


def _with_notes(provider: str, ids: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Live ids (with display names) in the order: suggested first, then the rest alphabetically."""
    notes = {m["id"]: m.get("note", "") for m in _suggested(provider)}
    order = {m["id"]: i for i, m in enumerate(_suggested(provider))}
    items = [{"id": i, "name": n if n and n != i else "", "note": notes.get(i, "")} for i, n in ids]
    return sorted(items, key=lambda m: (order.get(m["id"], 999), m["id"]))


async def _live(provider: str, base_url: str | None, key: str | None) -> list[tuple[str, str]]:
    if provider == "anthropic":
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=key, max_retries=1, timeout=10.0)
        return [(m.id, getattr(m, "display_name", "") or "") async for m in client.models.list(limit=100)]
    url = f"{str(base_url).rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(url, headers=headers)
    r.raise_for_status()
    data = r.json().get("data", [])
    if provider == "openrouter":   # only models that can call tools are useful to the assistant
        data = [m for m in data if "tools" in (m.get("supported_parameters") or [])]
    ids = [(m["id"], m.get("name") or "") for m in data if m.get("id")]
    if provider == "openai":
        ids = [(i, n) for i, n in ids if (i.startswith("gpt-") or re.match(r"^o\d", i)) and not _OPENAI_SKIP.search(i)]
    return ids


async def provider_models(cfg, provider: str, base_url: str | None = None,
                          api_key_env: str | None = None) -> dict[str, Any]:
    """{models: [{id, name, note, …}], source: files | live | suggested, error?}"""
    if provider == "llama_server":
        return {"models": local_files(cfg._env["ALVEUS_MODELS"]), "source": "files",
                "dir": str(llm_dir(cfg._env["ALVEUS_MODELS"]))}
    preset = PROVIDERS.get(provider, {})
    base_url = base_url or preset.get("base_url")
    env = api_key_env or preset.get("api_key_env")
    key = credentials.get(env) if env else (preset.get("api_key") or None)
    ck = (provider, base_url, env, bool(key))
    hit = _CACHE.get(ck)
    if hit and time.monotonic() - hit[0] < TTL:
        return hit[1]
    try:
        if provider == "anthropic" and not key:
            raise LookupError(f"set {env} to list the models")
        if provider not in ("anthropic",) and not base_url:
            raise LookupError("enter the server address first")
        if provider in ("openai", "deepseek") and not key:
            raise LookupError(f"set {env} to list the models")
        res = {"models": _with_notes(provider, await _live(provider, base_url, key)), "source": "live"}
    except Exception as e:  # noqa: BLE001 - offline, no key, wrong address: fall back to the suggestions
        msg = str(e) if isinstance(e, LookupError) else f"could not fetch the list ({type(e).__name__})"
        log.info("model list for %s: %s", provider, msg)
        return {"models": _suggested(provider), "source": "suggested", "error": msg}
    _CACHE[ck] = (time.monotonic(), res)
    return res
