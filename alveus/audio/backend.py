"""Audio capture/playback backends.

``pipewire``   - uses the pw-record / pw-play CLI tools (default on PipeWire desktops;
                 works with the session's default source/sink and needs no PortAudio).
``sounddevice`` - PortAudio via the sounddevice package (macOS, PulseAudio/ALSA-only setups).
"""
from __future__ import annotations

import logging
import os
import queue
import shutil
import subprocess
import threading
import time
from collections.abc import Iterator

import numpy as np

log = logging.getLogger(__name__)

FRAME = 512  # samples per frame at 16 kHz (32 ms) - what silero VAD wants


def pick_backend(cfg_backend: str | None) -> str:
    if cfg_backend and cfg_backend != "auto":
        return cfg_backend
    if shutil.which("pw-record") and shutil.which("pw-play") and os.environ.get("XDG_RUNTIME_DIR"):
        return "pipewire"
    return "sounddevice"


# ---------------------------------------------------------------------------- capture
class AudioIn:
    """Continuous 16 kHz mono float32 capture, delivered in FRAME-sized numpy chunks."""

    def __init__(self, sample_rate: int = 16000, device: str | None = None):
        self.sample_rate = sample_rate
        self.device = device
        self._q: queue.Queue[np.ndarray] = queue.Queue(maxsize=400)
        self._running = False

    def start(self) -> None: ...
    def stop(self) -> None: ...

    def frames(self) -> Iterator[np.ndarray]:
        while self._running:
            try:
                yield self._q.get(timeout=0.5)
            except queue.Empty:
                continue

    def read(self, timeout: float = 1.0) -> np.ndarray | None:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain(self) -> None:
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                return

    def _push(self, frame: np.ndarray) -> None:
        try:
            self._q.put_nowait(frame)
        except queue.Full:  # drop oldest
            try:
                self._q.get_nowait()
            except queue.Empty:
                pass
            self._q.put_nowait(frame)


class PipeWireIn(AudioIn):
    def start(self) -> None:
        if self._running:
            return
        cmd = ["pw-record", "--rate", str(self.sample_rate), "--channels", "1", "--format", "s16",
               "--latency", "32ms"]
        if self.device:
            cmd += ["--target", self.device]
        cmd.append("-")
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        self._running = True
        self._t = threading.Thread(target=self._reader, daemon=True)
        self._t.start()

    def _reader(self) -> None:
        nbytes = FRAME * 2
        buf = b""
        out = self._proc.stdout
        while self._running and out:
            chunk = out.read(nbytes - len(buf))
            if not chunk:
                if self._running:
                    log.error("pw-record exited unexpectedly")
                break
            buf += chunk
            if len(buf) == nbytes:
                self._push(np.frombuffer(buf, dtype=np.int16).astype(np.float32) / 32768.0)
                buf = b""

    def stop(self) -> None:
        self._running = False
        p = getattr(self, "_proc", None)
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(1)
            except subprocess.TimeoutExpired:
                p.kill()


class SoundDeviceIn(AudioIn):
    def start(self) -> None:
        if self._running:
            return
        import sounddevice as sd

        def cb(indata, frames, t, status):
            if status:
                log.debug("sd status %s", status)
            self._push(indata[:, 0].copy())

        dev = _sd_find(self.device, kind="input")
        self._stream = sd.InputStream(samplerate=self.sample_rate, channels=1, dtype="float32",
                                      blocksize=FRAME, device=dev, callback=cb)
        self._stream.start()
        self._running = True

    def stop(self) -> None:
        self._running = False
        s = getattr(self, "_stream", None)
        if s:
            s.stop()
            s.close()


# ---------------------------------------------------------------------------- playback
class AudioOut:
    """Queue-based, interruptible playback of float32 mono clips."""

    def __init__(self, device: str | None = None):
        self.device = device
        self._q: queue.Queue[tuple[np.ndarray, int] | None] = queue.Queue()
        self._stop = threading.Event()
        self._playing = threading.Event()
        self._t = threading.Thread(target=self._worker, daemon=True)
        self._t.start()

    def play(self, audio: np.ndarray, sample_rate: int) -> None:
        if audio is None or len(audio) == 0:
            return
        self._q.put((np.asarray(audio, dtype=np.float32), int(sample_rate)))

    def play_blocking(self, audio: np.ndarray, sample_rate: int) -> None:
        self.play(audio, sample_rate)
        self.wait()

    def wait(self, poll: float = 0.02) -> None:
        while not self._q.empty() or self._playing.is_set():
            time.sleep(poll)

    @property
    def busy(self) -> bool:
        return self._playing.is_set() or not self._q.empty()

    def stop(self) -> None:
        """Abort current clip and drop queued ones."""
        self._stop.set()
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
        self._abort_current()
        time.sleep(0.05)
        self._stop.clear()

    def _worker(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                return
            if self._stop.is_set():
                continue
            audio, sr = item
            self._playing.set()
            try:
                self._play_clip(audio, sr)
            except Exception as e:  # noqa: BLE001
                log.error("playback failed: %s", e)
            finally:
                self._playing.clear()

    def _play_clip(self, audio: np.ndarray, sr: int) -> None: ...
    def _abort_current(self) -> None: ...


class PipeWireOut(AudioOut):
    _proc: subprocess.Popen | None = None

    def _play_clip(self, audio: np.ndarray, sr: int) -> None:
        cmd = ["pw-play", "--rate", str(sr), "--channels", "1", "--format", "f32", "--latency", "64ms"]
        if self.device:
            cmd += ["--target", self.device]
        cmd.append("-")
        self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            data = np.clip(audio, -1, 1).astype(np.float32).tobytes()
            step = sr * 4 // 10  # 100 ms
            for i in range(0, len(data), step):
                if self._stop.is_set():
                    break
                self._proc.stdin.write(data[i:i + step])
            self._proc.stdin.close()
            self._proc.wait()
        except (BrokenPipeError, ValueError):
            pass
        finally:
            self._proc = None

    def _abort_current(self) -> None:
        p = self._proc
        if p and p.poll() is None:
            p.kill()


class SoundDeviceOut(AudioOut):
    def _play_clip(self, audio: np.ndarray, sr: int) -> None:
        import sounddevice as sd

        dev = _sd_find(self.device, kind="output")
        with sd.OutputStream(samplerate=sr, channels=1, dtype="float32", device=dev) as s:
            step = sr // 10
            for i in range(0, len(audio), step):
                if self._stop.is_set():
                    break
                s.write(np.ascontiguousarray(audio[i:i + step]).reshape(-1, 1))

    def _abort_current(self) -> None:
        return None


# ---------------------------------------------------------------------------- factories
def make_audio_in(cfg) -> AudioIn:
    a = cfg.audio
    b = pick_backend(a.get("backend"))
    dev = a.get("input_device") or None
    return PipeWireIn(int(a.get("sample_rate", 16000)), dev) if b == "pipewire" else SoundDeviceIn(int(a.get("sample_rate", 16000)), dev)


def make_audio_out(cfg) -> AudioOut:
    a = cfg.audio
    b = pick_backend(a.get("backend"))
    dev = a.get("output_device") or None
    return PipeWireOut(dev) if b == "pipewire" else SoundDeviceOut(dev)


def list_devices(cfg=None) -> str:
    b = pick_backend(cfg.audio.get("backend") if cfg else None)
    if b == "pipewire":
        try:
            return "backend: pipewire\n" + subprocess.run(["wpctl", "status"], capture_output=True, text=True).stdout
        except FileNotFoundError:
            return "backend: pipewire (wpctl not found)"
    import sounddevice as sd
    return "backend: sounddevice\n" + str(sd.query_devices())


def _sd_find(name: str | None, kind: str):
    if not name:
        return None
    import sounddevice as sd
    if name.isdigit():
        return int(name)
    for i, d in enumerate(sd.query_devices()):
        ch = d["max_input_channels"] if kind == "input" else d["max_output_channels"]
        if ch > 0 and name.lower() in d["name"].lower():
            return i
    raise ValueError(f"no {kind} device matching '{name}'")
