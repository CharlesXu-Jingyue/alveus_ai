from .base import TTSBackend


def make_tts(cfg) -> TTSBackend:
    backend = cfg.tts.get("backend", "kokoro")
    device = cfg.tts.get("device", "cuda")
    if backend == "kokoro":
        from .kokoro_tts import KokoroTTS
        return KokoroTTS(cfg.tts.get("kokoro") or {}, device)
    if backend == "chatterbox":
        from .chatterbox_tts import ChatterboxTTS
        return ChatterboxTTS(cfg.tts.get("chatterbox") or {}, device, voices_dir=cfg.tts.get("voices_dir"))
    if backend == "openai_http":
        from .openai_http_tts import OpenAIHttpTTS
        return OpenAIHttpTTS(cfg.tts.get("openai_http") or {})
    raise ValueError(f"Unknown TTS backend: {backend}")


__all__ = ["TTSBackend", "make_tts"]
