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
scripts/train_wakeword.sh alveus             # creates conda env 'alveus-wakeword', runs setup (~19 GB, once),
scripts/train_wakeword.sh aurea              # trains, and installs $ALVEUS_MODELS/wakeword/<name>.onnx
scripts/train_wakeword.sh "hey aurea" hey_aurea
```

What the script does, in order:

1. Creates the conda env `alveus-wakeword` and installs `livekit-wakeword`. It stays separate from
   `alveus` because it pins newer numpy/onnxruntime than the speech stack (~6 GB).
2. Makes sure the `espeak-ng` command exists (Piper's phonemizer shells out to it). `sudo apt install
   espeak-ng` is the normal way; without root, and if `libespeak-ng1` + `espeak-ng-data` are present
   (Ubuntu pulls them in for other packages), the script compiles the small CLI into the env instead.
3. Runs `livekit-wakeword setup` once into `$ALVEUS_MODELS/wakeword-train-data` (override with
   `ALVEUS_WAKEWORD_DATA`): ACAV100M negative features (16 GB), MUSAN backgrounds (1.1 GB), MIT room
   impulse responses, and the Piper LibriTTS voice. Keep 25 GB free the first time.
4. Writes `.wakeword-train/<name>/configs/<name>.yaml` (10,000 synthetic positives, small
   conv-attention model, 50,000 steps, target 0.2 false positives per hour) and runs the pipeline:
   synthesize the phrase with many voices and speeds, augment with noise/reverb, train, evaluate,
   export ONNX. 20–60 minutes per phrase on an RTX 4090; it shares the GPU with the running
   assistant, so expect it to be slower while the LLM is loaded.
5. Copies the model to `$ALVEUS_MODELS/wakeword/<name>.onnx`, where the GUI's wake-word model list
   picks it up.

Then in `config/local.yaml` (or GUI → Settings → Activation, tick both models):

```yaml
activation:
  wake_word:
    mode: both                 # names + neural wake words
    oww_model: [alveus, aurea] # several models listen at once
```

Training takes on the order of 20–60 minutes per phrase on the RTX 4090. Tips from the openWakeWord authors: 3+ syllables work best (both names qualify), and add a leading "hey" variant if you want "hey Alveus" too.

### B. openWakeWord's own notebook

`notebooks/automatic_model_training.ipynb` in the openWakeWord repo (Colab or local Jupyter). Same idea (piper-sample-generator for positives, ~30k h of negative audio features), a bit more manual. Output `.onnx` goes in the same folder.

### Results on this machine (2026-09-09)

Both names trained in about 15 minutes each on the RTX 4090 while the assistant kept running. The
trainer's own validation (2,000 synthetic positives, 32,000 negatives, 480,000 background clips):
`alveus` recall 99.2 %, `aurea` 99.6 %, 0 false positives per hour for both. With the assistant's Kokoro
voice, which the trainer never heard, the bare word scores 0.90 (`alveus`) and 0.66 (`aurea`); unrelated
speech, Mandarin and the pretrained phrases stay below 0.15, and neither model reacts to the other name.
"hey alveus" scores only 0.19: the models expect the bare name. Threshold 0.5 is the starting point; the
owner's own voice decides the final value.

## Tuning

- `alveus wakeword-test` prints live scores (per model) so you can set `activation.wake_word.threshold`.
- If Whisper hears your name oddly (`alveus stt test`), add the spelling to `name_aliases`.
