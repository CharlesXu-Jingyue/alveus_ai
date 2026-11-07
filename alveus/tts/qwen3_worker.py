"""Qwen3-TTS worker: loads the model and voices sentences, one request at a time.

Runs in its own Python environment (``tts.qwen3.python``, made by scripts/install_qwen3_tts.sh),
because qwen-tts needs transformers 4.57 while Alveus runs on 5.x. It imports nothing from Alveus.

    python qwen3_worker.py MODEL DEVICE        MODEL = a local folder or a Hugging Face id

Protocol (the parent is alveus/tts/qwen3_tts.py): one JSON request per line on stdin; each answer
is one JSON line on the original stdout, followed by ``n`` float32 samples for a synthesis. Library
output (prints, warnings) is moved to stderr so it cannot corrupt the stream. The worker exits when
stdin closes, i.e. when Alveus exits or drops the engine.

    -> {"op": "synth", "text": ..., "language": "japanese", "voice": "/path.wav", "ref_text": str|null,
        "temperature": 0.9, "max_new_tokens": 600}
    <- {"ok": true, "sr": 24000, "n": 52800, "seconds": 1.4}  + 4*n bytes
    <- {"ok": false, "error": "..."}
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback

OUT = os.fdopen(os.dup(1), "wb", buffering=0)   # the protocol channel
os.dup2(2, 1)                                     # anything printed by libraries goes to stderr
sys.stdout = sys.stderr


def send(obj: dict, payload: bytes = b"") -> None:
    OUT.write((json.dumps(obj) + "\n").encode() + payload)


def main() -> None:
    model_id, device = sys.argv[1], sys.argv[2]
    t0 = time.time()
    try:
        import numpy as np
        import torch
        from qwen_tts import Qwen3TTSModel

        dtype = torch.bfloat16 if device.startswith("cuda") else torch.float32
        model = Qwen3TTSModel.from_pretrained(model_id, device_map=device if device != "cuda" else "cuda:0",
                                              dtype=dtype, attn_implementation="sdpa")
    except Exception as e:  # noqa: BLE001
        send({"ready": False, "error": f"{type(e).__name__}: {e}"[:600]})
        traceback.print_exc()
        return
    vram = torch.cuda.memory_allocated() / 2**30 if torch.cuda.is_available() else 0.0
    send({"ready": True, "seconds": round(time.time() - t0, 1), "vram_gb": round(vram, 2),
          "languages": [str(x) for x in (model.get_supported_languages() or [])]})
    prompts: dict = {}          # (voice file, its mtime, transcript) -> reusable voice-clone prompt

    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
            if req.get("op") == "ping":
                send({"ok": True})
                continue
            voice, ref_text = req.get("voice"), req.get("ref_text") or None
            if not voice:
                raise ValueError("no voice recording to copy")
            key = (voice, os.path.getmtime(voice), ref_text)
            if key not in prompts:
                prompts[key] = model.create_voice_clone_prompt(ref_audio=voice, ref_text=ref_text,
                                                               x_vector_only_mode=ref_text is None)
            t = time.time()
            wavs, sr = model.generate_voice_clone(
                text=req["text"], language=req.get("language") or "auto", voice_clone_prompt=prompts[key],
                temperature=float(req.get("temperature", 0.9)), max_new_tokens=int(req.get("max_new_tokens", 2048)))
            audio = np.asarray(wavs[0], dtype=np.float32).reshape(-1)
            send({"ok": True, "sr": int(sr), "n": int(audio.size), "seconds": round(time.time() - t, 2)},
                 audio.tobytes())
        except Exception as e:  # noqa: BLE001 - report it and keep serving
            traceback.print_exc()
            send({"ok": False, "error": f"{type(e).__name__}: {e}"[:600]})


if __name__ == "__main__":
    main()
