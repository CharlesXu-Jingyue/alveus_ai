from alveus.agent.loop import active_names, voice_is_female
from alveus.config import DotDict


def _cfg(tts):
    return DotDict({"assistant": {"name": "Alveus", "female_name": "Aurea"}, "tts": tts})


def test_kokoro_prefix():
    assert voice_is_female(_cfg({"backend": "kokoro", "kokoro": {"voice": "af_heart"}}))
    assert not voice_is_female(_cfg({"backend": "kokoro", "kokoro": {"voice": "am_michael"}}))


def test_chatterbox_sample_name():
    assert voice_is_female(_cfg({"backend": "chatterbox", "chatterbox": {"voice_ref": "/v/f_anna.wav"}}))
    assert not voice_is_female(_cfg({"backend": "chatterbox", "chatterbox": {"voice_ref": "/v/m_tom.wav"}}))
    assert not voice_is_female(_cfg({"backend": "chatterbox", "chatterbox": {"voice_ref": "/v/charles.wav"}}))
    assert not voice_is_female(_cfg({"backend": "chatterbox", "chatterbox": {"voice_ref": None}}))


def test_override_and_names():
    assert voice_is_female(_cfg({"backend": "chatterbox", "voice_gender": "female"}))
    assert active_names(_cfg({"backend": "chatterbox", "chatterbox": {"voice_ref": "f_x.wav"}})) == ("Aurea", "Alveus")
