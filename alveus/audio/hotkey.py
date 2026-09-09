"""Global push-to-talk hotkey using pynput (X11; on Wayland use a DE shortcut that runs
`alveus trigger`, which pokes the running assistant through its HTTP API)."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)


class Hotkey:
    def __init__(self, combo: str, on_press: Callable[[], None], on_release: Callable[[], None] | None = None,
                 mode: str = "toggle"):
        self.combo = combo
        self.on_press = on_press
        self.on_release = on_release
        self.mode = mode
        self._listener = None

    def start(self) -> None:
        try:
            from pynput import keyboard
        except Exception as e:  # noqa: BLE001
            log.warning("hotkey disabled (pynput unavailable: %s)", e)
            return
        try:
            self._start(keyboard)
        except Exception as e:  # noqa: BLE001
            log.warning("hotkey disabled (bad combo %r or no display: %s)", self.combo, e)
            self._listener = None

    def _start(self, keyboard) -> None:  # noqa: ANN001
        if self.mode == "hold" and self.on_release:
            hk = keyboard.HotKey(keyboard.HotKey.parse(self.combo), self.on_press)
            release_keys = set(keyboard.HotKey.parse(self.combo))

            def on_release(k):
                hk.release(self._listener.canonical(k))
                if self._listener.canonical(k) in release_keys:
                    self.on_release()

            self._listener = keyboard.Listener(
                on_press=lambda k: hk.press(self._listener.canonical(k)), on_release=on_release)
        else:
            self._listener = keyboard.GlobalHotKeys({self.combo: self.on_press})
        self._listener.daemon = True
        self._listener.start()
        log.info("hotkey %s armed (%s)", self.combo, self.mode)

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()


class Trigger:
    """Thread-safe one-shot flag shared between hotkey / API and the voice loop."""

    def __init__(self):
        self._ev = threading.Event()
        self.on_fire = None   # optional callback, called on whichever thread fires (hotkey, API)

    def fire(self) -> None:
        self._ev.set()
        if self.on_fire:
            self.on_fire()

    def take(self) -> bool:
        if self._ev.is_set():
            self._ev.clear()
            return True
        return False
