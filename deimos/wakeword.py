"""Wake word via openWakeWord — free, fully local, no account or key.

Default phrase: "Hey Jarvis" (a pre-trained model). An always-on background
listener reads the mic in small frames and fires a callback on detection (the
server then starts a normal voice turn). The listener releases the mic during a
turn and resumes after, so there's no device conflict with the recorder.

Gated by CONFIG.wake_word_enabled so it only runs when you want it. Set that to
False (or remove it) to turn the always-on mic off.
"""
import threading
import time

import numpy as np
import sounddevice as sd

from deimos.config import CONFIG

_SR = 16000
_CHUNK = 1280  # 80 ms at 16 kHz — openWakeWord's expected frame size


def is_configured() -> bool:
    return bool(getattr(CONFIG, "wake_word_enabled", False))


class WakeWord:
    def __init__(self, on_wake) -> None:
        self.on_wake = on_wake               # called (in this thread) on detection
        self._stop = threading.Event()
        self._paused = threading.Event()
        # Set whenever the listener is NOT holding the mic device. pause() blocks
        # on this so a turn's recorder never opens a second stream on the same
        # device (which fails on macOS with CoreAudio err -50). Starts set: the
        # listener isn't holding the mic until _run opens the stream.
        self._released = threading.Event()
        self._released.set()
        self._thread = None

    def start(self) -> bool:
        if not is_configured():
            return False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def pause(self) -> None:
        """Release the mic so a turn's recorder can use it, and WAIT until the
        device is actually closed before returning. Without this wait the
        recorder opens a second stream on the same device while ours is still
        closing, which fails with CoreAudio err -50 and breaks recording."""
        self._paused.set()
        self._released.wait(timeout=2.0)

    def resume(self) -> None:
        self._paused.clear()

    def _run(self) -> None:
        try:
            import openwakeword
            from openwakeword.model import Model
            try:
                openwakeword.utils.download_models()  # cached after first run
            except Exception:
                pass
            model = Model(
                wakeword_models=[CONFIG.wake_word], inference_framework="onnx"
            )
        except Exception as exc:
            print(f"[wakeword] disabled: {type(exc).__name__}: {exc}")
            return

        name = CONFIG.wake_word
        threshold = CONFIG.wake_word_threshold
        print(f"[wakeword] listening for: {name}")

        while not self._stop.is_set():
            if self._paused.is_set():
                self._released.set()  # we are not holding the mic device
                try:
                    model.reset()  # drop buffered audio so we don't fire on stale frames
                except Exception:
                    pass
                time.sleep(0.15)
                continue

            triggered = False
            self._released.clear()  # about to open the mic device
            try:
                with sd.InputStream(
                    samplerate=_SR, channels=1, dtype="int16", blocksize=_CHUNK
                ) as stream:
                    while not self._stop.is_set() and not self._paused.is_set():
                        data, _ = stream.read(_CHUNK)
                        scores = model.predict(data[:, 0])
                        if scores.get(name, 0.0) >= threshold:
                            triggered = True
                            break
            except Exception:
                time.sleep(0.2)
            finally:
                self._released.set()  # stream closed; mic is free for the recorder

            if triggered:
                try:
                    model.reset()
                except Exception:
                    pass
                self._paused.set()       # avoid re-trigger; the server resumes us
                try:
                    self.on_wake()
                except Exception:
                    pass
