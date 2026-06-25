"""Text to speech.

Picks the most natural voice available at startup:
  1. Piper (a local neural voice) if installed with a model -> cinematic
  2. the best matching macOS `say` voice from CONFIG.preferred_voices
  3. any installed Premium/Enhanced English voice
  4. a sensible default

Always falls back gracefully, so Deimos never goes silent.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from deimos.config import CONFIG


def _find_piper() -> str | None:
    """Locate the piper binary without depending on an activated venv.

    Prefer the piper that lives next to the running interpreter (i.e. this
    venv's own bin/piper) — that works even when launched with a minimal PATH,
    e.g. from the Deimos.app launcher. Fall back to whatever is on PATH.
    Returns the full path to the binary, or None if not found.
    """
    candidate = Path(sys.executable).parent / "piper"
    if candidate.exists():
        return str(candidate)
    return shutil.which("piper")


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


# Emoji and pictographic symbol ranges that should never be vocalized. Kept
# deliberately narrow so normal punctuation and apostrophes are untouched.
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"  # emoji, pictographs, flags (regional indicators)
    "\U00002600-\U000027BF"  # misc symbols + dingbats
    "\U00002B00-\U00002BFF"  # stars / misc symbols & arrows
    "\U00002190-\U000021FF"  # arrows (e.g. weather wind direction)
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"             # zero-width joiner (emoji sequences)
    "\U00002122\U00002139"   # trademark, info source
    "]+",
    flags=re.UNICODE,
)


def _clean_for_speech(text: str) -> str:
    """Strip anything that shouldn't be read aloud (markdown + symbols + emoji).

    Keeps the visible words and normal punctuation/apostrophes; removes only the
    formatting characters. Runs before any voice path so Piper and `say` agree.
    """
    if not text:
        return ""
    # Links/images: keep the visible text, drop the URL.
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)   # ![alt](url) -> alt
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)    # [text](url) -> text
    # Code fences (``` optionally with a language) then any inline backticks.
    text = re.sub(r"```[A-Za-z0-9_-]*\n?", "", text)
    text = text.replace("`", "")
    # Markdown headers at the start of a line.
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    # Bullet markers at the start of a line (-, *, +).
    text = re.sub(r"(?m)^\s*[-*+]\s+", "", text)
    # Bold/italic markers.
    text = re.sub(r"\*\*|__|\*|_", "", text)
    # Blockquote and tilde symbols.
    text = re.sub(r"[>~]", "", text)
    # Emoji / non-speech pictographs.
    text = _EMOJI_RE.sub("", text)
    # Collapse any leftover double spaces.
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


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
        self.model_path = str(model)
        self.say_voice = _choose_say_voice()
        self.piper_bin = _find_piper()

        # Load the Piper neural voice ONCE at startup and keep it resident, so
        # each utterance is fast. Reloading the ~120 MB model per sentence (the
        # old CLI approach) added several seconds of "speaking but silent" delay,
        # especially under memory pressure. Falls back to the CLI, then `say`.
        self.piper_voice = None
        if model.exists():
            try:
                from piper import PiperVoice
                self.piper_voice = PiperVoice.load(self.model_path)
            except Exception:
                self.piper_voice = None
        self.piper_ready = self.piper_voice is not None or (
            bool(self.piper_bin) and model.exists()
        )

    def speak(self, text: str) -> None:
        text = _clean_for_speech(text)
        if not text.strip():
            return
        if self.piper_voice is not None:
            try:
                self._speak_piper_inproc(text)
                return
            except Exception:
                pass
        if self.piper_bin and Path(self.model_path).exists():
            try:
                self._speak_piper_cli(text)
                return
            except Exception:
                pass
        self._speak_say(text)

    def _speak_piper_inproc(self, text: str) -> None:
        """Synthesize with the already-loaded voice — no per-utterance reload."""
        import wave
        from piper.config import SynthesisConfig

        wav_path = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        try:
            cfg = SynthesisConfig(length_scale=CONFIG.piper_length_scale)
            with wave.open(wav_path, "wb") as wf:
                self.piper_voice.synthesize_wav(text, wf, syn_config=cfg)
            subprocess.run(["afplay", wav_path], check=False)
        finally:
            try:
                os.remove(wav_path)
            except OSError:
                pass

    def _speak_piper_cli(self, text: str) -> None:
        wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        try:
            subprocess.run(
                [
                    self.piper_bin,
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
