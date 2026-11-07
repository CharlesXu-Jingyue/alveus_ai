"""Provider presets: how to reach each kind of LLM service.

A profile in ``llm.profiles`` names a ``provider``; the preset below supplies the wire protocol
(``api``), the address, the environment variable holding the API key and the provider's quirks.
The profile itself then only needs ``model`` plus whatever it wants to tune. Any preset key can be
overridden in the profile, and a provider name that is not listed here works too when the profile
gives ``api`` and ``base_url`` itself (e.g. a company proxy).

Protocols (``api``):
  openai_chat         POST /chat/completions. llama-server, vLLM, SGLang, Ollama, LM Studio, DeepSeek,
                      OpenRouter, Groq, Together, Mistral, ... (alveus/llm/openai_compat.py)
  openai_responses    POST /responses. OpenAI's own models; their tool calling needs this API
                      (alveus/llm/openai_responses.py)
  anthropic_messages  Anthropic Messages API through the official SDK (alveus/llm/anthropic_messages.py)

Preset keys (all optional in a profile):
  label               shown in the GUI and logs
  api                 protocol, see above
  base_url            endpoint root (the SDK default is used when empty for anthropic_messages)
  api_key_env         variable holding the key, read from the environment or ~/.config/alveus/secrets.env
  api_key             a literal key (local servers that ignore it; avoid real keys in YAML)
  unsupported         request parameters the provider rejects; dropped unless the profile sets them
  thinking_param      openai_chat only: how thinking on/off is sent: chat_template_kwargs | deepseek | none
  reasoning_replay    openai_chat only: none | all. all = send each assistant message's reasoning back
                      as reasoning_content (DeepSeek requires it once tools are used)
  max_tokens_field    openai_chat only: name of the output-limit field (max_tokens / max_completion_tokens)
  reasoning_summary   openai_responses only: auto | concise | detailed | null
  thinking_display    anthropic_messages only: summarized | omitted
  fallbacks           anthropic_messages only: "default" = let Anthropic re-run a declined request on
                      another model (server-side fallback), null = off
  opencode_provider   provider id in opencode, so the coder tool's "auto" can use the same model
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

PROVIDERS: dict[str, dict[str, Any]] = {
    # ------------------------------------------------------------------ local servers
    "llama_server": {
        "label": "llama.cpp server",
        "api": "openai_chat",
        "base_url": "http://127.0.0.1:8080/v1",
        "api_key": "local",
        "thinking_param": "chat_template_kwargs",
    },
    "vllm": {
        "label": "vLLM server",
        "api": "openai_chat",
        "base_url": "http://127.0.0.1:8000/v1",
        "api_key": "local",
        "thinking_param": "chat_template_kwargs",
    },
    "ollama": {
        "label": "Ollama",
        "api": "openai_chat",
        "base_url": "http://127.0.0.1:11434/v1",
        "api_key": "ollama",
        "thinking_param": "none",
    },
    # anything else that speaks /v1/chat/completions; the profile must give base_url
    "openai_compat": {
        "label": "OpenAI-compatible server",
        "api": "openai_chat",
        "thinking_param": "chat_template_kwargs",
    },
    # ------------------------------------------------------------------ cloud APIs
    "openai": {
        "label": "OpenAI",
        "api": "openai_responses",
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "unsupported": ["temperature", "top_p"],
        "reasoning_summary": "auto",
        "opencode_provider": "openai",
    },
    "anthropic": {
        "label": "Anthropic",
        "api": "anthropic_messages",
        "api_key_env": "ANTHROPIC_API_KEY",
        # current API versions reject sampling parameters on every model
        "unsupported": ["temperature", "top_p", "top_k"],
        "thinking_display": "summarized",
        "fallbacks": "default",
        "opencode_provider": "anthropic",
    },
    "deepseek": {
        "label": "DeepSeek",
        "api": "openai_chat",
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        "thinking_param": "deepseek",
        "reasoning_replay": "all",
        "opencode_provider": "deepseek",
    },
    "openrouter": {
        "label": "OpenRouter",
        "api": "openai_chat",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "thinking_param": "none",
        "opencode_provider": "openrouter",
    },
}

APIS = ("openai_chat", "openai_responses", "anthropic_messages")

# old `backend:` values (before providers existed) -> provider
_LEGACY_BACKENDS = {
    "openai": "openai_compat", "openai_compat": "openai_compat", "llama_server": "openai_compat",
    "vllm": "openai_compat", "ollama": "openai_compat", "anthropic": "anthropic",
}

# llm-level settings every profile inherits unless it sets its own (null = do not send)
COMMON_KEYS = ("temperature", "top_p", "max_tokens", "max_tool_rounds", "effort")


def provider_of(raw: dict[str, Any]) -> str:
    """Provider name of a raw profile, mapping the old ``backend:`` key."""
    if raw.get("provider"):
        return str(raw["provider"])
    return _LEGACY_BACKENDS.get(str(raw.get("backend", "openai")), str(raw.get("backend", "openai_compat")))


def is_remote(base_url: str | None) -> bool:
    """True unless the endpoint is on this machine (no base_url = the provider's cloud default)."""
    if not base_url:
        return True
    host = (urlparse(str(base_url)).hostname or "").lower()
    return host not in ("127.0.0.1", "localhost", "::1", "0.0.0.0") and not host.startswith("127.")


def resolve(name: str, raw: dict[str, Any], llm_level: dict[str, Any]) -> dict[str, Any]:
    """Merge preset < llm-level common settings < the profile itself; add derived keys."""
    provider = provider_of(raw)
    preset = PROVIDERS.get(provider)
    if preset is None:
        if not (raw.get("api") and (raw.get("base_url") or raw.get("api") == "anthropic_messages")):
            raise KeyError(f"LLM profile '{name}': unknown provider '{provider}'. Known: {sorted(PROVIDERS)}; "
                           "or give api and base_url in the profile.")
        preset = {"label": provider}
    prof: dict[str, Any] = dict(preset)
    for k in COMMON_KEYS:
        if k in llm_level:
            prof[k] = llm_level[k]
    prof.update(raw)
    for k in preset.get("unsupported") or []:
        if k not in raw:
            prof.pop(k, None)
    if prof.get("api") not in APIS:
        raise KeyError(f"LLM profile '{name}': api must be one of {list(APIS)}, not {prof.get('api')!r}")
    prof["name"] = name
    prof["provider"] = provider
    prof["remote"] = is_remote(prof.get("base_url"))
    prof.setdefault("label", provider)
    return prof


def describe(prof: dict[str, Any]) -> str:
    """One line for the GUI: where the model runs and what it is."""
    where = "cloud" if prof.get("remote") else "this machine"
    return f"{prof.get('model', '?')} · {prof.get('label', prof.get('provider'))} ({where})"
