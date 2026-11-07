"""Qwen3-TTS (Alibaba Qwen, Apache-2.0): copies a voice from a short recording, in 10 languages
(Chinese, English, Japanese, Korean, German, French, Russian, Portuguese, Spanish, Italian).

The model runs in a worker process (alveus/tts/qwen3_worker.py) started with ``tts.qwen3.python``,
a small environment made by scripts/install_qwen3_tts.sh: qwen-tts pins transformers 4.57, Alveus
runs on 5.x, and the two cannot share a process. The worker shares torch with the main environment;
dropping the engine (another engine chosen, Alveus exiting) ends it and frees its VRAM.

Voices: the Base models have no built-in voice; they copy a recording from the voices folder. With
the recording's words in ``<name>.txt`` next to it, sentences in the recording's own language are
voiced by continuing the recording (closest copy); sentences in another language, and recordings
without a transcript, use the voice's timbre only (x-vector mode), which keeps the voice better
across languages. Measured on eight voices (speaker-embedding similarity to the recording): same
language with the transcript 0.88-0.94; English from a Japanese/Chinese recording 0.83-0.86 with
the transcript (worst take 0.72) against 0.87-0.92 timbre-only (worst 0.85).
"""
from __future__ import annotations

import json
import logging
import os
import select
import subprocess
import threading
from collections import deque
from pathlib import Path

import numpy as np

from ..config import REPO_ROOT
from .chatterbox_tts import resolve_voice_ref

log = logging.getLogger(__name__)

# model choice -> repository name (Hugging Face org Qwen); the keys avoid dots (they are config paths)
MODELS = {"1_7b": "Qwen3-TTS-12Hz-1.7B-Base", "0_6b": "Qwen3-TTS-12Hz-0.6B-Base"}
DEFAULT_MODEL = "1_7b"
LANGS = {"zh": "chinese", "en": "english", "ja": "japanese", "ko": "korean", "de": "german", "fr": "french",
         "ru": "russian", "pt": "portuguese", "es": "spanish", "it": "italian"}
DEFAULT_PYTHON = str(REPO_ROOT / ".venv-qwen3tts" / "bin" / "python")
AUDIO_EXT = (".wav", ".flac", ".mp3")


def transcript_for(voice: str | None) -> str | None:
    """The words spoken in a recording, from ``<recording>.txt`` beside it (None when absent or empty)."""
    if not voice:
        return None
    p = Path(voice).with_suffix(".txt")
    try:
        text = p.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return " ".join(text.split()) or None


def token_budget(text: str) -> int:
    """A cap on generated audio tokens (12 per second), about twice the slowest plausible reading,
    so a sentence the model fails to end cannot run on for minutes."""
    cjk = sum(1 for c in text if ord(c) >= 0x2E80)
    seconds = cjk / 3.5 + (len(text) - cjk) / 10
    return int(min(2048, max(96, 12 * (2 * seconds + 4))))


class Qwen3TTS:
    name = "qwen3"
    sample_rate = 24000

    def __init__(self, opts: dict, device: str = "cuda", voices_dir: str | None = None):
        self.variant = str(opts.get("model") or DEFAULT_MODEL)
        self.python = os.path.expanduser(str(opts.get("python") or DEFAULT_PYTHON))
        self.weights_dir = opts.get("weights_dir")
        self.device = device
        self._model: subprocess.Popen | None = None     # the worker process holding the model
        self._lock = threading.Lock()
        self._tail: deque[str] = deque(maxlen=40)       # the worker's last log lines, for error messages
        self.worker = Path(__file__).with_name("qwen3_worker.py")
        self.warning: str | None = None
        self._apply(opts, voices_dir)

    # ------------------------------------------------------------------ settings
    def _apply(self, opts: dict, voices_dir: str | None) -> None:
        vd = voices_dir or opts.get("voices_dir")
        want = opts.get("voice_ref")
        ref = resolve_voice_ref(want, vd)
        self.warning = None
        if not ref:
            first = self._first_recording(vd)
            if want:
                self.warning = (f"voice sample not found: {want} (voices folder: {vd})"
                                + (f" — copying {Path(first).name} instead." if first else "."))
            elif not first:
                self.warning = ("Qwen3-TTS copies a voice from a recording: put a WAV in the voices folder and "
                                "choose it in Settings → Voice.")
            ref = first
            if self.warning:
                log.error(self.warning)
        self.voice_ref = ref
        self.ref_text = transcript_for(ref)
        self.ref_lang = self._lang_of(self.ref_text)
        self.language = str(opts.get("language") or "auto").lower()
        self.fallback_language = str(opts.get("fallback_language") or "en").lower()
        self.temperature = float(opts.get("temperature", 0.9))

    @staticmethod
    def _lang_of(text: str | None) -> str | None:
        if not text:
            return None
        from .langid import detect_language
        return detect_language(text, fallback="en", allowed=set(LANGS))

    @staticmethod
    def _first_recording(voices_dir: str | None) -> str | None:
        d = Path(os.path.expanduser(str(voices_dir))) if voices_dir else None
        if not d or not d.is_dir():
            return None
        files = sorted(f for f in d.iterdir() if f.suffix.lower() in AUDIO_EXT and f.is_file())
        return str(files[0]) if files else None

    def reconfigure(self, opts: dict, voices_dir: str | None = None) -> bool:
        """Voice, language and variation change in place; another model or environment needs a reload."""
        if (str(opts.get("model") or DEFAULT_MODEL) != self.variant
                or os.path.expanduser(str(opts.get("python") or DEFAULT_PYTHON)) != self.python
                or opts.get("weights_dir") != self.weights_dir):
            return False
        self._apply(opts, voices_dir)
        return True

    # ------------------------------------------------------------------ the worker
    def model_source(self) -> str:
        """A local folder when the weights are there (downloading them into weights_dir first if it
        is set), else the Hugging Face id (the worker then uses the Hugging Face cache)."""
        if os.path.isdir(os.path.expanduser(self.variant)):
            return os.path.expanduser(self.variant)
        repo = MODELS.get(self.variant, self.variant)
        repo_id = repo if "/" in repo else f"Qwen/{repo}"
        if not self.weights_dir:
            return repo_id
        local = Path(os.path.expanduser(str(self.weights_dir))) / repo_id.split("/")[-1]
        if not (local / "config.json").exists():
            from huggingface_hub import snapshot_download
            log.info("Downloading %s to %s (about %s GB, once)", repo_id, local, 4.5 if "1.7B" in repo_id else 2.5)
            snapshot_download(repo_id, local_dir=str(local))
        return str(local)

    def load(self) -> None:
        if self._model is not None and self._model.poll() is None:
            return
        if not Path(self.python).exists():
            raise RuntimeError(f"the Qwen3-TTS environment is missing ({self.python}); "
                               "run scripts/install_qwen3_tts.sh")
        src = self.model_source()
        worker = self.worker
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        log.info("Loading Qwen3-TTS %s on %s (worker: %s)", Path(src).name, self.device, self.python)
        proc = subprocess.Popen([self.python, "-u", str(worker), src, self.device], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=str(REPO_ROOT))
        threading.Thread(target=self._drain, args=(proc,), name="qwen3-tts-log", daemon=True).start()
        ready = self._read_line(proc, timeout=900)
        if not ready.get("ready"):
            proc.kill()
            raise RuntimeError(f"Qwen3-TTS did not start: {ready.get('error') or self._last_lines()}")
        self._model = proc
        log.info("Qwen3-TTS ready in %.1f s (%.1f GB VRAM)", ready.get("seconds", 0), ready.get("vram_gb", 0))

    def _drain(self, proc: subprocess.Popen) -> None:
        for raw in proc.stderr:            # library chatter; kept for error messages, logged at debug
            line = raw.decode(errors="replace").rstrip()
            if line:
                self._tail.append(line)
                log.debug("qwen3 worker: %s", line)

    def _last_lines(self) -> str:
        lines = [x for x in self._tail if x.strip("* ") and "flash-attn" not in x and "SoX" not in x]
        return " | ".join(lines[-4:]) or "no output"

    def _read_line(self, proc: subprocess.Popen, timeout: float | None = None) -> dict:
        if timeout is not None:
            ready, _, _ = select.select([proc.stdout], [], [], timeout)
            if not ready:
                raise TimeoutError(f"Qwen3-TTS gave no answer in {timeout:.0f} s")
        head = proc.stdout.readline()
        if not head:
            raise RuntimeError(f"the Qwen3-TTS worker stopped: {self._last_lines()}")
        return json.loads(head)

    def close(self) -> None:
        """End the worker (frees its VRAM). It also exits by itself when Alveus does (stdin closes)."""
        proc, self._model = self._model, None
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.stdin.close()
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            proc.kill()

    def __del__(self):
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ speech
    def language_for(self, text: str) -> str:
        if self.language != "auto":
            return self.language
        from .langid import detect_language
        return detect_language(text, fallback=self.fallback_language, allowed=set(LANGS))

    def synthesize(self, text: str, voice: str | None = None) -> np.ndarray:
        from ..agent.sentences import SentenceBuffer, has_speech

        if not has_speech(text):
            return np.zeros(0, dtype=np.float32)
        self.load()
        parts = [text]
        if self.language == "auto":          # mixed-language text: each sentence in its own language
            sb = SentenceBuffer(min_chars=1)
            parts = [p for p in sb.feed(text) + sb.flush() if has_speech(p)] or [text]
        gap = np.zeros(int(0.12 * self.sample_rate), dtype=np.float32)
        clips: list[np.ndarray] = []
        for part in parts:
            try:
                clips += [self._synth_one(part, voice), gap]
            except Exception as e:  # noqa: BLE001 - one bad sentence must not silence the reply
                log.warning("qwen3 could not voice %r: %s", part[:60], e)
        return np.concatenate(clips[:-1]) if clips else np.zeros(0, dtype=np.float32)

    def request(self, text: str, voice: str | None = None) -> dict:
        """What the worker is asked: the transcript goes along only for a sentence in the recording's
        own language (see the module notes)."""
        ref = resolve_voice_ref(voice, None) if voice else self.voice_ref
        if not ref:
            raise RuntimeError(self.warning or "no voice recording to copy")
        ref_text = transcript_for(ref) if voice else self.ref_text
        ref_lang = self._lang_of(ref_text) if voice else self.ref_lang
        lang = self.language_for(text)
        return {"op": "synth", "text": text, "language": LANGS.get(lang, "auto"), "voice": ref,
                "ref_text": ref_text if ref_text and ref_lang == lang else None,
                "temperature": self.temperature, "max_new_tokens": token_budget(text)}

    def _synth_one(self, text: str, voice: str | None = None) -> np.ndarray:
        req = self.request(text, voice)
        lang = req["language"]
        with self._lock:
            if self._model is None or self._model.poll() is not None:
                self._model = None
                self.load()
            proc = self._model
            try:
                proc.stdin.write((json.dumps(req, ensure_ascii=False) + "\n").encode())
                proc.stdin.flush()
                head = self._read_line(proc)
                if head.get("ok"):
                    n = int(head["n"]) * 4
                    buf = bytearray()
                    while len(buf) < n:
                        chunk = proc.stdout.read(n - len(buf))
                        if not chunk:
                            raise RuntimeError(f"the Qwen3-TTS worker stopped: {self._last_lines()}")
                        buf += chunk
            except (OSError, RuntimeError, ValueError):
                # the worker died or the stream is out of step: retire it; the next sentence starts a new one
                self._model = None
                proc.kill()
                raise
        if not head.get("ok"):
            raise RuntimeError(head.get("error") or "unknown error")
        self.sample_rate = int(head.get("sr") or self.sample_rate)
        log.debug("qwen3 %s: %.1f s audio in %.2f s <- %r", lang, len(buf) / 4 / self.sample_rate,
                  head.get("seconds", 0), text[:60])
        return np.frombuffer(bytes(buf), dtype=np.float32).copy()

    def voices(self) -> list[str]:
        return [self.voice_ref] if self.voice_ref else []
