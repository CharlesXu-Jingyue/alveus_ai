from .base import STTBackend


def make_stt(cfg) -> STTBackend:
    backend = cfg.stt.get("backend", "faster_whisper")
    device = cfg.stt.get("device", "cuda")
    if backend == "faster_whisper":
        from .faster_whisper_stt import FasterWhisperSTT
        return FasterWhisperSTT(cfg.stt.get("faster_whisper") or {}, device)
    if backend == "parakeet":
        from .parakeet_stt import ParakeetSTT
        return ParakeetSTT(cfg.stt.get("parakeet") or {}, device)
    if backend == "openai_http":
        from .openai_http_stt import OpenAIHttpSTT
        return OpenAIHttpSTT(cfg.stt.get("openai_http") or {})
    raise ValueError(f"Unknown STT backend: {backend}")


__all__ = ["STTBackend", "make_stt"]
