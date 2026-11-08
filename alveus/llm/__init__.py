"""LLM adapters, one per wire protocol, chosen by the resolved profile's ``api`` (see providers.py)."""
from .base import LLMBackend, LLMError, LLMEvent
from .openai_compat import OpenAICompatLLM
from .providers import PROVIDERS


def make_llm(profile) -> LLMBackend:
    """Adapter for a profile resolved by ``alveus.config.llm_profile``."""
    api = profile.get("api") or "openai_chat"
    if api == "openai_chat":
        return OpenAICompatLLM(profile)
    if api == "openai_responses":
        from .openai_responses import OpenAIResponsesLLM
        return OpenAIResponsesLLM(profile)
    if api == "anthropic_messages":
        from .anthropic_messages import AnthropicLLM
        return AnthropicLLM(profile)
    raise ValueError(f"Unknown LLM api: {api}")


__all__ = ["LLMBackend", "LLMError", "LLMEvent", "OpenAICompatLLM", "PROVIDERS", "make_llm"]
