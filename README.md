# Deimos

A local, private voice assistant for Apple Silicon. The everyday brain runs
on-device (Ollama), so your speech and tool data never leave your Mac. The
design is built to grow: new abilities are just tools you register.

This starter is the **spine** — a working voice loop plus the tool-registry
pattern that Google integrations, Claude Code, a wake word, and a HUD will plug
into next.

## What works right now

- Press Enter to talk (or type) → local transcription → local LLM → spoken reply
- Tool-calling: the model can call `get_current_time` and `open_app` on its own
- Add a new skill by writing one decorated function

## Setup (one time)

1. **Install Ollama** and pull a model that supports tool-calling:
   ```bash
   # install from https://ollama.com, then:
   ollama pull qwen2.5:7b
   ```
   Keep the Ollama app running in the background.

2. **Install PortAudio** (needed by the mic library):
   ```bash
   brew install portaudio
   ```

3. **Create a virtual environment and install deps:**
   ```bash
   cd deimos
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

4. **Grant microphone permission.** The first run that uses the mic will prompt
   macOS for Microphone access for your terminal app — allow it. (System
   Settings → Privacy & Security → Microphone.)

## Run the app (orb UI)

With Ollama running and your venv active:

```bash
python server.py
```

Then open **http://localhost:8765** in your browser. You'll see the orb.

- Type a message and press Enter, or press **Space** to talk.
- Watch the orb: it breathes when idle, ripples when listening, spins while
  thinking, and pulses while speaking. The reply is also spoken aloud.
- First time you talk, macOS asks for microphone permission — allow it.

## Run (terminal only)

If you just want the plain terminal loop without the UI:

```bash
python main.py
```

## Project layout

```
main.py                 # entry point + voice loop
requirements.txt
deimos/
  config.py             # all settings (model, voice, audio thresholds)
  audio/
    stt.py              # mic recording + faster-whisper transcription
    tts.py              # macOS `say` (swap for Piper later)
  brain/
    llm.py              # Ollama chat loop with tool-calling (the orchestrator)
  tools/
    registry.py         # the plugin system
    builtin.py          # example tools
```

## Adding a skill

```python
from deimos.tools.registry import registry

@registry.tool(
    name="flip_coin",
    description="Flip a coin and return heads or tails.",
)
def flip_coin() -> str:
    import random
    return random.choice(["heads", "tails"])
```

Import the module once (e.g. in `main.py`) and the model can call it.

## What's next (build order)

1. ~~Voice loop + tool registry~~ (this starter)
2. Google Calendar + Gmail tools (OAuth, read-only first)
3. Email send + proactive reminder poller (with confirmation gates)
4. A `run_claude_code` tool that shells out to the `claude` CLI in a project dir
5. Swap the press-to-talk for an `openWakeWord` "Hey Deimos" trigger
6. A Tauri HUD overlay (status orb + live transcript)

## Notes

- Tuned for 16 GB: one 8B model stays resident as the local brain. Heavy
  reasoning and coding escalate to Claude (via Claude Code) rather than a second
  large local model.
- `llm.py` targets a recent `ollama` python client (>= 0.4) with typed responses.

## Cinematic voice (Piper) — optional

Deimos sounds decent out of the box using the British `Daniel` voice. For a
richer neural voice, set up Piper. Until you do, it automatically falls back to
`Daniel`, so nothing breaks.

```bash
# 1. install Piper into your venv
pip install piper-tts

# 2. download a voice into ~/deimos/voices/
mkdir -p ~/deimos/voices
cd ~/deimos/voices
curl -L -O https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx
curl -L -O https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx.json
```

Restart `python server.py`. If the model file and the `piper` command are both
present, Deimos uses Piper automatically. To try other voices, browse
huggingface.co/rhasspy/piper-voices and update `piper_model` in `deimos/config.py`.

## Standalone window (Tauri) — optional

This wraps the UI in a real macOS window (its own icon, no browser, no tabs).
The Python server still runs the brain; Tauri is just the window.

```bash
# 1. install Rust (the one new toolchain)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
#    then restart your terminal so `cargo` is on your PATH

# 2. scaffold a Tauri app (choose: vanilla / TypeScript: No)
cd ~
npm create tauri-app@latest jarvis-window
cd jarvis-window
```

Then point the window at the running Deimos server. In
`src-tauri/tauri.conf.json`, set the main window so it loads the local server
and looks the part:

```json
{
  "app": {
    "windows": [
      {
        "title": "Deimos",
        "url": "http://localhost:8765",
        "width": 900,
        "height": 700,
        "resizable": true,
        "decorations": true,
        "theme": "Dark"
      }
    ]
  }
}
```

Run it (with `python server.py` already running in another tab):

```bash
npm run tauri dev
```

A native Deimos window opens. Later we can have Tauri auto-start the Python
server so you launch just one thing.

## Most natural voice (one-time, recommended)

Deimos automatically uses the best voice installed on your Mac. The built-in
compact voices sound robotic; a **Premium** voice sounds close to human:

1. System Settings -> Accessibility -> Spoken Content -> System Voice -> Manage Voices
2. Find an English voice marked **(Premium)** (e.g. Jamie, Serena, Zoe) and download it.
3. Restart `python server.py`. Deimos detects and uses it automatically.

For an even richer neural voice, set up Piper (see the Piper section above).

## Voice-first interface

The interface is now voice-only: tap the orb or press Space to speak. The first
time you do, your **browser** will ask for microphone access (separate from the
macOS terminal prompt) — allow it. This lets the orb react to your voice in real
time while listening.

## Memory (he learns about you)

Deimos now keeps long-term memory in a local SQLite database at `~/.deimos/memory.db`
(outside the project, so it survives re-downloads). Two layers:

- every exchange is logged verbatim (your full chat history)
- durable facts about you are saved via the `remember` tool and read back into
  every conversation, so he stays personal across sessions

Tell him things like "my name is …", "I'm working on …", "I prefer …" and he'll
save them and use them later. He can also `recall` past topics. To wipe memory,
delete `~/.deimos/memory.db`. To inspect it: `sqlite3 ~/.deimos/memory.db "select * from facts;"`

## Making the voice more human

Piper sounds best with a little pacing. `config.py` exposes:
- `piper_length_scale` (default 1.08) — higher is slower/calmer
- `piper_sentence_silence` (default 0.3) — pause between sentences

For a different character, download another model into `~/deimos/voices/` and set
`piper_model` to it. Natural options to try:
- `en_GB-jenny_dioco-medium` (warm British)
- `en_US-ryan-high` (deep American, very natural)
Browse all at huggingface.co/rhasspy/piper-voices.

## Autonomous coding (run_claude_code)

Deimos can build, edit, and fix code by running Claude Code for you. Say things
like "build me a landing page for my band" or "fix the bug in my trading-game
project" or "add a wake word to yourself". It calls the `claude` CLI in the
target folder.

Safety net: before every run, Deimos takes an automatic git snapshot of that
project. If a run makes a mess, undo it with the hash it reports:
    git -C <project> reset --hard <hash>
Self-edits ("change yourself") run against the Deimos project with the same net;
restart the server after a self-edit to load the new code.

Settings in `config.py`: `projects_dir` (where project names resolve),
`code_timeout`, `code_auto_snapshot`.

## Standalone window (Tauri)

Hand `TAURI_FOR_CLAUDE_CODE.md` to Claude Code to build a native macOS window
around Deimos (its own icon, no browser). It installs Rust, scaffolds the app,
points it at your running server, and launches it.
