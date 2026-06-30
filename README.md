# Deimos

**A private, local-first voice assistant for the Mac — a "Jarvis" that actually runs on your machine.**

Deimos listens, thinks, and acts entirely on-device. Your voice, your files, and
your data never leave your Mac for the everyday loop: speech-to-text, the
language model, and text-to-speech all run locally. Press one key, speak, and it
controls your computer, manages your day, watches the markets, and reads your
documents back to you — in a deep, custom voice.

> Built solo as a portfolio project: ~5,000 lines of Python, 39 voice-callable
> tools, and a reliability layer that makes a *3-billion-parameter* local model
> behave like a dependable assistant.

---

## What it can do

Talk to it by holding **⌃⌥Space** (push-to-talk) and speaking, or type in the orb.

| Area | Say something like… |
|------|---------------------|
| 🧠 **Knows you** | "what do you know about me?" — it auto-learns durable facts as you talk |
| ⏰ **Your day** | "remind me to submit my essay at 8pm" · "what's on my calendar?" · "text mom I'll be late" |
| 🖥️ **Controls the Mac** | "lock my screen" · "go dark" · "empty the trash" · "close Discord" · "take a screenshot" |
| 🎬 **Routines** | "study mode" (closes distracting tabs, plays your playlist, starts a timer) · "wind down" · "dev mode for Money Path" |
| 🔔 **Watches for things** | "tell me when my download finishes" · "let me know when the battery's full" — it speaks up on its own |
| 📁 **Files & docs** | "find my file about econ" · "summarize the budget pdf" (reads PDF/Word/text aloud) |
| 📈 **Finance** | "how's Apple?" · "what moved the market today?" · "how's my watchlist?" — live, never guessed |
| 🌅 **Proactive** | a spoken morning briefing (date, weather, calendar, markets) + event nudges, on its own |
| 🌐 **The basics** | web search, weather, math, timers, clipboard, notes, opens sites in your browser |
| 🛠️ **Builds things** | "build me a website about X" — drives Claude Code to write and ship real projects |

---

## Why it's interesting (the engineering)

Small local models are *fast and private* but **unreliable at tool-calling** —
a 3B model picks the wrong tool, or fakes an answer instead of checking. The
core of this project is making that reliable:

- **Deterministic intent routing.** Common requests (time, weather, math, "lock
  my screen", "study mode", "how's Apple") never touch the model's tool-picker —
  they're matched and dispatched directly. Instant, and impossible to mis-route.
- **Two-tier brain.** A fast `qwen2.5:3b` handles most turns; flaky or skipped
  tool-calls automatically **escalate** to a stronger `qwen2.5:7b`, with guaranteed
  fallbacks so time/weather/actions can never be faked.
- **Background memory.** A daemon thread quietly extracts durable facts about you
  with the 7B and injects them into every prompt — Deimos stays personal across
  sessions without you telling it to "remember."
- **One tool, many actions.** System control is a *single* `mac_control` tool with
  ~18 actions, so the model's menu stays small and accurate as capabilities grow.
- **Decoupled voice turn.** Push-to-talk hits a `/talk` endpoint that runs a full
  listen→think→speak turn with no UI attached, so the hotkey works from anywhere.

Everything is **local by default.** The only network calls are the ones you'd
expect a tool to make (weather, a stock price, a web search) — never your speech
or your documents.

---

## Architecture

```
   mic ──► faster-whisper (STT, local)
                  │
                  ▼
        ┌───────────────────┐  deterministic router ─► direct tool call
        │   Brain (Ollama)  │ ───────────────────────────────────────────►  tools/
        │  3b fast · 7b esc │  model tool-calling ──► tool ──► result ──►   (39 of them)
        └───────────────────┘
                  │
                  ▼
        Piper TTS (local) ──► sox pitch-shift ──► deep "Deimos" voice
```

- **`server.py`** — FastAPI on `localhost:8765`: the voice WebSocket, the orb UI,
  the `/talk` hotkey endpoint, and background loops (proactive briefings, watchers).
- **`deimos/brain/llm.py`** — the brain: deterministic routing, model escalation,
  background fact extraction, the tool loop.
- **`deimos/tools/`** — every capability as a registered tool (`@registry.tool`).
  Add a skill by writing one decorated function.
- **`deimos/memory.py`** — SQLite long-term memory (facts + full transcript),
  stored outside the repo so it survives reinstalls.
- **Orb UI** — a frameless, always-on-top Tauri window that expands on click.

**Stack:** Python · FastAPI · Ollama (qwen2.5 3b/7b) · faster-whisper · Piper +
sox · AppleScript · Yahoo Finance · pypdf · skhd (global hotkey) · Tauri.

---

## Quick start

Requires Apple Silicon + [Ollama](https://ollama.com) running.

```bash
# 1. models
ollama pull qwen2.5:3b && ollama pull qwen2.5:7b

# 2. system deps
brew install portaudio sox koekeishiya/formulae/skhd

# 3. python
cd ~/deimos && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 4. run
python server.py
```

Then bind a push-to-talk key: point an **skhd** shortcut at
`curl -X POST http://localhost:8765/talk` (see `~/.skhdrc`).

**Permissions** (macOS will prompt on first use — grant them):
Microphone · Automation (Calendar, Reminders, Messages, Contacts) ·
Accessibility (for the global hotkey) · Full Disk Access (to read documents).

**Optional:** add `~/deimos/.spotify.json` (Client ID/Secret) for music.

---

## Privacy

The everyday loop — hearing you, understanding you, and replying — is **100%
on-device**. Nothing is sent to a cloud LLM. Tools reach the network only for the
obvious things (a weather lookup, a stock quote, a web search), and credentials
live in gitignored files outside source control.
