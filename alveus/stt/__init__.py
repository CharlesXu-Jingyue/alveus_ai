from .base import STTBackend


def make_stt(cfg) -> STTBackend:
    """The active STT engine with its options (engine block + the selected model's own block)."""
    from ..config import engine_opts

    backend = cfg.stt.get("backend", "faster_whisper")
    device = cfg.stt.get("device", "cuda")
    opts = engine_opts(cfg, "stt")
    if backend == "faster_whisper":
        from .faster_whisper_stt import FasterWhisperSTT
        return FasterWhisperSTT(opts, device)
    if backend == "parakeet":
        from .parakeet_stt import ParakeetSTT
        return ParakeetSTT(opts, device)
    if backend == "openai_http":
        from .openai_http_stt import OpenAIHttpSTT
        return OpenAIHttpSTT(opts)
    raise ValueError(f"Unknown STT backend: {backend}")


__all__ = ["STTBackend", "make_stt"]
