"""Central configuration for Jarvis.

Tuned for a 16 GB M4: a single 8B model stays resident as the everyday brain.
Edit the values here; everything else reads from CONFIG.
"""
from dataclasses import dataclass


@dataclass
class Config:
    # --- Local LLM (Ollama) ---
    # The everyday brain. On 16 GB, an 8B Q4 model is the sweet spot:
    # smart enough for routing + tool use, ~5 GB resident, fast.
    # Alternatives that support tool-calling: "llama3.1:8b".
    llm_model: str = "qwen2.5:7b"
    ollama_host: str = "http://localhost:11434"
    system_prompt: str = (
        "You are Jarvis, a concise, helpful, personal voice assistant with a "
        "calm, refined manner. Keep spoken replies short and natural, one or "
        "two sentences. Use the available tools when they help. "
        "For anything about the current time or date, ALWAYS call "
        "get_current_time and use its fresh result; never answer time or date "
        "questions from memory. "
        "When the user shares something durable about themselves — their name, "
        "preferences, ongoing projects, important people, or goals — call the "
        "remember tool to save it. Use what you already know about the user to "
        "make your replies personal, and greet returning users naturally. "
        "When the user asks you to build, edit, or fix code, a website, or a "
        "project, call the run_claude_code tool with their full request as the "
        "instruction. Use project_path 'self' when they ask you to change "
        "yourself. Briefly tell them what you set in motion. "
        "You can also search the web, check the weather, open web pages, report "
        "this Mac's battery/memory/disk, set the volume, read and write the "
        "clipboard, take and read notes, set timers, show notifications, do "
        "quick math, and list folders or read text files. Reach for the right "
        "tool instead of guessing, and never read tool output verbatim — answer "
        "in your own concise, natural voice."
    )

    # How many recent messages to keep (plus the system prompt). A wider window
    # gives the model more conversational context for follow-up questions.
    history_limit: int = 16

    # Long-term memory database. Kept OUTSIDE the project folder so it survives
    # re-downloading or re-unzipping the app.
    memory_path: str = "~/.jarvis/memory.db"

    # --- Speech to text (faster-whisper) ---
    whisper_model: str = "base.en"   # tiny.en (fastest) / base.en / small.en (best)
    whisper_compute: str = "int8"    # int8 is fast and light on Apple Silicon

    # --- Audio capture ---
    sample_rate: int = 16000
    silence_threshold: float = 0.01  # RMS below this counts as silence
    silence_duration: float = 1.0    # seconds of silence that ends a turn
    max_record_seconds: float = 15.0

    # --- Text to speech ---
    # Jarvis auto-picks the most natural voice available, in this order:
    # Piper (if installed) -> the best of these `say` voices that exists ->
    # any installed Premium/Enhanced English voice -> a sensible default.
    # Install a Premium voice for a big quality jump (see README).
    preferred_voices: tuple = (
        "Jamie (Premium)", "Serena (Premium)", "Stephanie (Premium)",
        "Oliver (Enhanced)", "Daniel (Enhanced)", "Serena (Enhanced)",
        "Zoe (Premium)", "Ava (Premium)", "Daniel", "Serena", "Samantha",
    )
    tts_voice: str = "Daniel"        # last-resort fallback; run `say -v ?` to list
    tts_rate: int = 178              # words per minute (calmer pace)

    # Piper: cinematic local neural voice. If this model file exists and the
    # `piper` command is installed, Jarvis uses it (see README). en_GB-alan is a
    # deep, natural British voice.
    piper_model: str = "~/jarvis/voices/en_GB-alan-medium.onnx"
    # Pacing makes Piper sound more human: >1.0 is slower/calmer; sentence
    # silence adds a natural pause between sentences.
    piper_length_scale: float = 1.08
    piper_sentence_silence: float = 0.3

    # --- Claude Code tool (autonomous coding by voice) ---
    # Folder that project names are resolved against (e.g. "trading-game").
    projects_dir: str = "~"
    # How long a single Claude Code run may take before we give up (seconds).
    code_timeout: int = 600
    # Auto git-snapshot a project before editing it, so any run is undoable.
    code_auto_snapshot: bool = True


CONFIG = Config()
