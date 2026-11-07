from .base import TTSBackend


def make_tts(cfg) -> TTSBackend:
    """The active TTS engine with its options (engine block + the selected model's own block)."""
    from ..config import engine_opts

    backend = cfg.tts.get("backend", "kokoro")
    device = cfg.tts.get("device", "cuda")
    opts = engine_opts(cfg, "tts")
    if backend == "kokoro":
        from .kokoro_tts import KokoroTTS
        return KokoroTTS(opts, device)
    if backend == "chatterbox":
        from .chatterbox_tts import ChatterboxTTS
        return ChatterboxTTS(opts, device, voices_dir=opts.get("voices_dir"))
    if backend == "openai_http":
        from .openai_http_tts import OpenAIHttpTTS
        return OpenAIHttpTTS(opts)
    raise ValueError(f"Unknown TTS backend: {backend}")


__all__ = ["TTSBackend", "make_tts"]
