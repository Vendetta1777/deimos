"""Speech to text: record from the mic and transcribe with faster-whisper.

faster-whisper runs on CPU via Accelerate on Apple Silicon. For the short
command-length clips Jarvis deals with, int8 is quick and uses little memory.
"""
import threading

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

from jarvis.config import CONFIG


class SpeechToText:
    def __init__(self) -> None:
        self.model = WhisperModel(
            CONFIG.whisper_model,
            device="cpu",
            compute_type=CONFIG.whisper_compute,
        )

    def record(self, stop_event: threading.Event | None = None) -> np.ndarray:
        """Record until the speaker goes quiet, then return mono float32 audio.

        If ``stop_event`` is provided, recording bails out as soon as it is set,
        so a caller (e.g. the web UI) can pause listening on demand.
        """
        sr = CONFIG.sample_rate
        block = int(sr * 0.1)  # 100 ms blocks
        silent_blocks_needed = int(CONFIG.silence_duration / 0.1)
        max_blocks = int(CONFIG.max_record_seconds / 0.1)

        frames: list[np.ndarray] = []
        silent_run = 0
        has_spoken = False

        with sd.InputStream(
            samplerate=sr, channels=1, dtype="float32", blocksize=block
        ) as stream:
            for _ in range(max_blocks):
                if stop_event is not None and stop_event.is_set():
                    break
                data, _ = stream.read(block)
                mono = data[:, 0]
                frames.append(mono)
                rms = float(np.sqrt(np.mean(mono ** 2)))
                if rms >= CONFIG.silence_threshold:
                    has_spoken = True
                    silent_run = 0
                elif has_spoken:
                    silent_run += 1
                    if silent_run >= silent_blocks_needed:
                        break

        if not frames:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(frames)

    def transcribe(self, audio: np.ndarray) -> str:
        if audio.size == 0:
            return ""
        segments, _ = self.model.transcribe(audio, language="en", beam_size=1)
        return " ".join(seg.text for seg in segments).strip()

    def listen(self) -> str:
        """Record one utterance and return the transcribed text."""
        return self.transcribe(self.record())
