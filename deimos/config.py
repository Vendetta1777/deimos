"""Central configuration for Deimos.

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
    llm_model: str = "qwen2.5:3b"
    ollama_host: str = "http://localhost:11434"
    # Keep the model resident in memory between requests (-1 = never unload),
    # so it doesn't pay model-reload latency on each turn.
    keep_alive: int = -1
    # Context window for the chat model. Qwen defaults to 32k, whose large KV
    # cache wastes RAM and slows replies on a 16 GB Mac. 8k is plenty for the
    # system prompt + recent history and keeps memory pressure (and latency) low.
    llm_num_ctx: int = 8192
    # Cap reply length — spoken answers are short, so this prevents runaway gen.
    llm_num_predict: int = 512
    # Lower temperature = more deterministic, far more reliable tool-calling on a
    # small model (less likely to fake an answer instead of calling a tool).
    llm_temperature: float = 0.2
    # When the fast model flakes (skips a tool it clearly needed, or fakes an
    # answer), the turn is re-run on this stronger model. Reuses the 7B so it's
    # only loaded when needed (coder_keep_alive controls how long it stays warm).
    escalation_model: str = "qwen2.5:7b"
    # Local vision model for screen sight (see_screen). Small + fast; loaded only
    # when used and unloaded soon after, to stay light on RAM.
    vision_model: str = "moondream"
    vision_keep_alive: str = "1m"
    # Cloud model (Claude API) for high-quality vision + hard reasoning. Used
    # only when an API key is configured (~/deimos/.anthropic.json). Defaults to
    # the strongest model; switch to a cheaper one here if you want to save cost.
    cloud_model: str = "claude-opus-4-8"
    # A larger model used ONLY to compose detailed build specs for Claude Code
    # (not for everyday chat), so coding quality is high without slowing chat.
    coder_model: str = "qwen2.5:7b"
    # Unload the coder model after it's idle, to free RAM on 16 GB machines.
    coder_keep_alive: str = "5m"
    system_prompt: str = (
        "You are Deimos, a concise, helpful, personal voice assistant with a "
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
        "Any request to build, create, edit, change, redesign, improve, or fix "
        "code, a website, a project, OR YOURSELF is an ACTION, not a discussion. "
        "You MUST call run_claude_code to do it — never reply with suggestions, "
        "plans, or ideas instead of calling the tool. For changes to yourself, "
        "pass project_path='self'. Examples that MUST call the tool: 'upgrade "
        "yourself visually', 'redesign your interface', 'make yourself look "
        "better', 'add a feature to yourself', 'build me a site', 'change the "
        "colors of X'. "
        "Your VISUAL appearance — your interface, orb, colors, layout, "
        "animations — is defined ENTIRELY in your web/ folder: web/index.html, "
        "web/style.css, and web/app.js. When asked to change how you look, "
        "upgrade your visuals, redesign your interface, or anything about your "
        "appearance, call run_claude_code with project_path='self' and an "
        "instruction that explicitly says to edit web/index.html, web/style.css, "
        "and web/app.js. Never change your appearance by editing brain/ or "
        "config.py. "
        "Choose project_path carefully: use 'self' ONLY to change Deimos's own "
        "app, interface, or behavior. To build a website, app, or project FOR "
        "THE USER (for example 'make me a website about X'), pass a short "
        "descriptive project name like 'max-verstappen-site', never 'self'. "
        "When calling run_claude_code, pass the user's full, exact request as "
        "the instruction — do not summarize or shorten it. If the request is "
        "vague, expand it into a clear, detailed spec before passing it. "
        "You can also search the web, check the weather, open web pages, report "
        "this Mac's battery/memory/disk, set the volume, read and write the "
        "clipboard, take and read notes, set timers, show notifications, do "
        "quick math, and list folders or read text files. Reach for the right "
        "tool instead of guessing, and never read tool output verbatim — answer "
        "in your own concise, natural voice. "
        "You can control this Mac. To open an app use open_app; to open a "
        "website use open_url; to see what's on the user's screen (read text, "
        "describe it, answer questions about what's displayed) use see_screen; "
        "to play a specific song, artist, or playlist use "
        "play_music; to play, pause, or skip use media_control; to set volume "
        "use set_volume. All music is on Spotify — never use Apple Music. For "
        "anything else on the computer, use run_command with "
        "a shell command. Destructive or system-level commands will ask the user "
        "for confirmation automatically — still attempt them; don't refuse. "
        "You manage the user's day through their Mac's own apps. To set a "
        "reminder use add_reminder (pass what and, if given, when); to read their "
        "reminders use list_reminders. To add a calendar event use add_event "
        "(title and when); to read their schedule use calendar_events. To send an "
        "iMessage use send_message (recipient name or number, and the body) — the "
        "user is asked to confirm before it sends. These are ACTIONS: when the "
        "user says 'remind me to…', 'add … to my calendar', or 'text … that …', "
        "call the matching tool; never just say you will. "
        "Reply in plain spoken sentences. Do not use markdown, asterisks, bullet "
        "points, headings, or emoji — your replies are read aloud. "
        "ALWAYS respond in English only — never use Chinese or any other language, "
        "not even a single word or character."
    )

    # How many recent messages to keep (plus the system prompt). A wider window
    # gives the model more conversational context for follow-up questions.
    history_limit: int = 16

    # Long-term memory database. Kept OUTSIDE the project folder so it survives
    # re-downloading or re-unzipping the app.
    memory_path: str = "~/.deimos/memory.db"

    # --- Speech to text (faster-whisper) ---
    whisper_model: str = "tiny.en"   # tiny.en (fastest) / base.en / small.en (best)
    whisper_compute: str = "int8"    # int8 is fast and light on Apple Silicon

    # --- Audio capture ---
    sample_rate: int = 16000
    silence_threshold: float = 0.006  # RMS below this counts as silence (less twitchy)
    silence_duration: float = 2.5     # seconds of silence that ends a turn (allow pauses)
    max_record_seconds: float = 45.0  # room for long, detailed instructions

    # --- Hands-free conversation ---
    # After a spoken reply, reopen the mic so you can follow up without tapping.
    # Staying quiet (no speech within the follow-up window) ends the exchange.
    conversation_mode: bool = True
    conversation_followup_timeout: float = 6.0  # secs to wait for you to start talking

    # --- Wake word (openWakeWord, fully local, no account) ---
    # When enabled, an always-on listener starts a turn when it hears the phrase.
    # "hey_jarvis" is a free pre-trained model. Set enabled False to stop the
    # always-on mic. Raise the threshold if it false-triggers; lower if it misses.
    # NOTE: disabled — openWakeWord 0.6 + onnxruntime 1.27 don't score in this
    # environment (verified: synth + live audio both flat 0.0). Use tap-to-talk;
    # a push-to-talk hotkey is the planned hands-free replacement.
    wake_word_enabled: bool = False
    wake_word: str = "hey_jarvis"
    wake_word_threshold: float = 0.5

    # --- Text to speech ---
    # Deimos auto-picks the most natural voice available, in this order:
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
    # `piper` command is installed, Deimos uses it (see README). en_US-ryan-high
    # is a smooth, deep, high-quality US voice.
    piper_model: str = "/Users/shrinivas46608/deimos/voices/en_US-ryan-high.onnx"
    # Fallback option (deep British, medium quality):
    #   "~/deimos/voices/en_GB-alan-medium.onnx"
    # Pacing makes Piper sound more human: >1.0 is slower/calmer; sentence
    # silence adds a natural pause between sentences. The high-quality model
    # sounds natural at full speed, so 1.0.
    piper_length_scale: float = 1.0
    piper_sentence_silence: float = 0.3

    # --- Claude Code tool (autonomous coding by voice) ---
    # Folder that project names are resolved against (e.g. "trading-game").
    projects_dir: str = "~/deimos-projects"
    # How long a single Claude Code run may take before we give up (seconds).
    # 1200 = 20 min, so large builds aren't cut off mid-way.
    code_timeout: int = 1200
    # Auto-publish each built project (not 'self') to a PUBLIC GitHub repo and,
    # for websites, deploy via GitHub Pages. Set False to disable.
    auto_publish: bool = True
    # Auto git-snapshot a project before editing it, so any run is undoable.
    code_auto_snapshot: bool = True

    # --- Preferences ---
    # Browser Deimos opens websites in (your signed-in one), not the system
    # default. Falls back to the default browser if this isn't installed.
    browser: str = "Google Chrome"

    # --- Proactivity (Deimos speaks up on its own) ---
    # Master switch for all unprompted speech.
    proactive_enabled: bool = True
    # Spoken morning briefing (date, weather, calendar, reminders) once a day at
    # this local time (24h "HH:MM"). Also available on demand ("brief me").
    briefing_enabled: bool = True
    briefing_time: str = "08:00"
    # Quiet hours — Deimos never speaks unprompted before/after these (24h).
    proactive_quiet_before: int = 7    # no proactive speech before 7am
    proactive_quiet_after: int = 22    # …or after 10pm
    # Heads-up before a calendar event starts (minutes). 0 disables nudges.
    event_nudge_lead_min: int = 10
    # How often the proactive scheduler checks, in seconds.
    proactive_tick_seconds: int = 45

    # --- Telegram bridge (talk to Deimos from your phone) ---
    # Active only when ~/deimos/.telegram.json holds a bot token. Briefings and
    # nudges are also pushed to the owner's chat.
    telegram_enabled: bool = True


CONFIG = Config()
