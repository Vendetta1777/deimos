"""Text to speech.

Picks the most natural voice available at startup:
  1. Piper (a local neural voice) if installed with a model -> cinematic
  2. the best matching macOS `say` voice from CONFIG.preferred_voices
  3. any installed Premium/Enhanced English voice
  4. a sensible default

Always falls back gracefully, so Jarvis never goes silent.
"""
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from jarvis.config import CONFIG


def _available_say_voices() -> list[tuple[str, str]]:
    """Return (name, locale) for every installed `say` voice."""
    try:
        out = subprocess.run(
            ["say", "-v", "?"], capture_output=True, text=True, check=False
        ).stdout
    except Exception:
        return []
    voices = []
    for line in out.splitlines():
        m = re.match(r"^(.+?)\s+([a-z]{2}[-_][A-Z]{2})", line)
        if m:
            voices.append((m.group(1).strip(), m.group(2)))
    return voices


def _choose_say_voice() -> str | None:
    voices = _available_say_voices()
    if not voices:
        return None
    names = [n for n, _ in voices]
    for pref in CONFIG.preferred_voices:
        if pref in names:
            return pref
    for n, loc in voices:
        if "Premium" in n and loc.startswith("en"):
            return n
    for n, loc in voices:
        if "Enhanced" in n and loc.startswith("en"):
            return n
    return CONFIG.tts_voice


class TextToSpeech:
    def __init__(self) -> None:
        model = Path(CONFIG.piper_model).expanduser()
        self.piper_ready = bool(shutil.which("piper")) and model.exists()
        self.model_path = str(model)
        self.say_voice = _choose_say_voice()

    def speak(self, text: str) -> None:
        if not text.strip():
            return
        if self.piper_ready:
            try:
                self._speak_piper(text)
                return
            except Exception:
                pass
        self._speak_say(text)

    def _speak_piper(self, text: str) -> None:
        wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        try:
            subprocess.run(
                [
                    "piper",
                    "--model", self.model_path,
                    "--length-scale", str(CONFIG.piper_length_scale),
                    "--sentence-silence", str(CONFIG.piper_sentence_silence),
                    "--output_file", wav,
                ],
                input=text.encode(),
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(["afplay", wav], check=False)
        finally:
            try:
                os.remove(wav)
            except OSError:
                pass

    def _speak_say(self, text: str) -> None:
        cmd = ["say", "-r", str(CONFIG.tts_rate)]
        if self.say_voice:
            cmd += ["-v", self.say_voice]
        cmd.append(text)
        subprocess.run(cmd, check=False)
