# Wake words

Alveus can be activated three ways (all configurable under `activation:` in `config/alveus.yaml`):

| mode | how it works | latency | setup |
|---|---|---|---|
| `names` (default) | VAD detects speech, the segment is transcribed, and the transcript is checked for **Alveus** / **Aurea** (fuzzy: "Alvius", "Aria", "Oria"...). The rest of the sentence is executed directly: *"Aurea, what's the weather?"* | reply starts after you finish the sentence | none |
| `oww` | an openWakeWord neural model listens for a fixed phrase, then Alveus chimes and records your request | ~0.2 s after the phrase | pretrained phrase, or train your own |
| `both` | either of the above | | |

In `both` mode the phrase is scored continuously, including while VAD is already recording a sentence, so
"hey Jarvis, what's the weather?" works as one utterance (the phrase triggers the chime and the rest is recorded).

Plus the global hotkey (`ctrl+alt+space` by default) and `POST /trigger` on the local API.

## Pretrained openWakeWord phrases

openWakeWord ships six English models; set `activation.wake_word.oww_model` to one of:

| model id | phrase |
|---|---|
| `hey_jarvis` | "hey Jarvis" |
| `alexa` | "Alexa" |
| `hey_mycroft` | "hey Mycroft" |
| `hey_rhasspy` | "hey Rhasspy" |
| `weather` | "what's the weather" |
| `timer` | "set a … minute timer" |

More community-trained phrases: https://openwakeword.com/library (drop the `.onnx` into `$ALVEUS_MODELS/wakeword/` and set `oww_model` to the file stem).

## Training your own ("Alveus", "Aurea")

Yes. Two options, both fully local:

### A. livekit-wakeword (recommended, 2026)

One-command pipeline: synthesizes thousands of TTS samples of the phrase, augments them with noise/reverb, trains, and exports an `.onnx` that **loads in openWakeWord unchanged**. It reports ~100x fewer false positives than the classic openWakeWord training notebook.

```bash
scripts/train_wakeword.sh alveus             # creates conda env 'alveus-wakeword', runs setup (several GB, once),
scripts/train_wakeword.sh aurea              # trains, and installs $ALVEUS_MODELS/wakeword/<name>.onnx
scripts/train_wakeword.sh "hey aurea" hey_aurea
```

The trainer lives in its own conda env because it pins newer numpy/onnxruntime than the speech stack.

Then in `config/local.yaml`:

```yaml
activation:
  wake_word:
    mode: both            # names + neural wake word
    oww_model: alveus     # or aurea; a second model can be listed later
```

Training takes on the order of 20–60 minutes per phrase on the RTX 4090. Tips from the openWakeWord authors: 3+ syllables work best (both names qualify), and add a leading "hey" variant if you want "hey Alveus" too.

### B. openWakeWord's own notebook

`notebooks/automatic_model_training.ipynb` in the openWakeWord repo (Colab or local Jupyter). Same idea (piper-sample-generator for positives, ~30k h of negative audio features), a bit more manual. Output `.onnx` goes in the same folder.

## Tuning

- `alveus wakeword-test` prints live scores so you can set `activation.wake_word.threshold`.
- If Whisper hears your name oddly (`alveus stt test`), add the spelling to `name_aliases`.
