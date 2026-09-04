from .base import LLMBackend, LLMEvent
from .openai_compat import OpenAICompatLLM


def make_llm(profile) -> LLMBackend:
    backend = profile.get("backend", "openai")
    if backend in ("openai", "openai_compat", "llama_server", "vllm", "ollama"):
        return OpenAICompatLLM(profile)
    raise ValueError(f"Unknown LLM backend: {backend}")


__all__ = ["LLMBackend", "LLMEvent", "OpenAICompatLLM", "make_llm"]
