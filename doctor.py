"""Deimos doctor — one command to check the whole setup is wired up.

    python doctor.py

Prints a ✓/✗ checklist (models, deps, system tools, voice, hotkey, server) with
a fix hint for anything missing. Permissions (Microphone, Automation, etc.) can't
be read programmatically on macOS — they're listed at the end as a reminder.
"""
import json
import shutil
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

GREEN, RED, DIM, RESET = "\033[92m", "\033[91m", "\033[2m", "\033[0m"
rows: list[tuple[str, bool, str]] = []


def check(name: str, good: bool, hint: str = "") -> None:
    rows.append((name, good, hint))


# --- Ollama + models ---
models: list[str] = []
try:
    with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as r:
        models = [m["name"] for m in json.load(r).get("models", [])]
    check("Ollama running", True)
except Exception:
    check("Ollama running", False, "start the Ollama app — https://ollama.com")
for m in ("qwen2.5:3b", "qwen2.5:7b"):
    check(f"model {m}", any(m in n for n in models), f"ollama pull {m}")

# --- Python deps ---
for mod in ("faster_whisper", "sounddevice", "fastapi", "ollama", "piper",
            "dateparser", "pypdf"):
    try:
        __import__(mod)
        check(f"python: {mod}", True)
    except Exception:
        check(f"python: {mod}", False, "pip install -r requirements.txt")

# --- System tools ---
def _has(tool: str) -> bool:
    return bool(shutil.which(tool)) or Path(f"/opt/homebrew/bin/{tool}").exists()

check("sox (deep voice)", _has("sox"), "brew install sox")
check("skhd (hotkey)", _has("skhd"), "brew install koekeishiya/formulae/skhd")

# --- Voice model + hotkey config ---
try:
    from deimos.config import CONFIG
    check("voice model present", Path(CONFIG.piper_model).expanduser().exists(),
          "place the Piper .onnx in voices/")
except Exception as exc:
    check("config import", False, str(exc))

skhdrc = Path.home() / ".skhdrc"
check("push-to-talk bound", skhdrc.exists() and "talk" in skhdrc.read_text(errors="ignore"),
      "add a 'curl -X POST localhost:8765/talk' binding to ~/.skhdrc")

# --- Server ---
try:
    urllib.request.urlopen("http://localhost:8765/", timeout=3)
    check("server running", True)
except Exception:
    check("server running", False, "python server.py")

# --- Report ---
print("\n  Deimos doctor\n  " + "─" * 40)
passed = 0
for name, good, hint in rows:
    mark = f"{GREEN}✓{RESET}" if good else f"{RED}✗{RESET}"
    line = f"  {mark}  {name}"
    if not good and hint:
        line += f"\n       {DIM}→ {hint}{RESET}"
    print(line)
    passed += good
print("  " + "─" * 40)
print(f"  {passed}/{len(rows)} checks passed\n")
print(f"  {DIM}Permissions to grant in System Settings → Privacy & Security "
      f"(macOS won't report these):\n"
      f"   Microphone · Automation (Calendar/Reminders/Messages/Contacts) ·\n"
      f"   Accessibility (skhd) · Full Disk Access (read documents){RESET}\n")
