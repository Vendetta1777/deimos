"""Jarvis's everyday skills.

A batch of practical, robust tools that make Jarvis genuinely useful day to day:
the web, weather, the system it runs on, the clipboard, notes, timers, volume,
quick math, and light file inspection. Everything here uses only the standard
library plus macOS command-line tools, so there are no extra dependencies.

Design rules that keep the assistant stable:
  - Every network call has a timeout; a slow service can never hang the brain.
  - Every subprocess call has a timeout and never raises into the tool loop.
  - Tools return short, speakable strings — this is a *voice* assistant.
"""
import ast
import json
import operator
import ssl
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from jarvis.tools.registry import registry

_UA = "Mozilla/5.0 (Jarvis voice assistant)"
NOTES_PATH = Path("~/.jarvis/notes.md").expanduser()

# Building a trust store that works everywhere this app might run:
#   1. certifi's bundle (covers the public web; some Python installs, e.g.
#      Anaconda, otherwise lack a working CA bundle), plus
#   2. the macOS keychain roots, so HTTPS still verifies on networks that do
#      TLS inspection with a private root the OS already trusts (e.g. a school
#      or corporate proxy). We trust exactly what macOS trusts — verification
#      stays ON; we never fall back to an unverified connection.
def _build_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(cafile=certifi.where())
    except Exception:
        pass
    keychains = [
        "/Library/Keychains/System.keychain",
        "/System/Library/Keychains/SystemRootCertificates.keychain",
    ]
    for kc in keychains:
        try:
            pem = subprocess.run(
                ["security", "find-certificate", "-a", "-p", kc],
                capture_output=True, text=True, timeout=10, check=False,
            ).stdout
            for block in pem.split("-----END CERTIFICATE-----"):
                cert = block.strip()
                if cert:
                    try:
                        ctx.load_verify_locations(
                            cadata=cert + "\n-----END CERTIFICATE-----\n"
                        )
                    except Exception:
                        pass  # skip any single unparseable cert
        except Exception:
            pass
    return ctx


_SSL_CTX = _build_ssl_context()


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _get(url: str, timeout: float = 8.0, ua: str = _UA) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
        return resp.read().decode("utf-8", "replace")


def _run(cmd: list[str], timeout: float = 8.0, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, check=False, **kw
    )


# --------------------------------------------------------------------------- #
# the web
# --------------------------------------------------------------------------- #
@registry.tool(
    name="web_search",
    description=(
        "Search the web for a quick factual answer about people, places, "
        "definitions, or current topics. Returns a short summary."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to look up."}
        },
        "required": ["query"],
    },
)
def web_search(query: str) -> str:
    q = urllib.parse.quote(query)
    url = f"https://api.duckduckgo.com/?q={q}&format=json&no_html=1&skip_disambig=1"
    try:
        data = json.loads(_get(url))
    except Exception as exc:
        return f"Couldn't reach the web just now ({exc})."
    if data.get("AbstractText"):
        src = data.get("AbstractSource") or "the web"
        text = data["AbstractText"]
        if len(text) > 600:  # keep it speakable; the model can elaborate if asked
            text = text[:600].rsplit(" ", 1)[0] + "…"
        return f"{text} (via {src})"
    if data.get("Answer"):
        return str(data["Answer"])
    for topic in data.get("RelatedTopics", []):
        if isinstance(topic, dict) and topic.get("Text"):
            return topic["Text"]
    return f"I didn't find a clear answer for '{query}'."


@registry.tool(
    name="get_weather",
    description=(
        "Get the current weather. Pass a city/place, or leave it blank to use "
        "the current location."
    ),
    parameters={
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "City or place name. Optional.",
            }
        },
    },
)
def get_weather(location: str = "") -> str:
    place = urllib.parse.quote(location.strip())
    fmt = urllib.parse.quote("%l: %C %t (feels %f), %h humidity, wind %w")
    try:
        # wttr.in only returns plain text to curl-like clients.
        line = _get(f"https://wttr.in/{place}?format={fmt}&m", ua="curl/8.4.0").strip()
    except Exception as exc:
        return f"Couldn't get the weather just now ({exc})."
    return line or "No weather data came back."


@registry.tool(
    name="open_url",
    description="Open a web page in the default browser.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL to open."}
        },
        "required": ["url"],
    },
)
def open_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    _run(["open", url])
    return f"Opened {url}."


# --------------------------------------------------------------------------- #
# the machine
# --------------------------------------------------------------------------- #
@registry.tool(
    name="system_status",
    description=(
        "Report this Mac's status: battery level, free memory, and free disk "
        "space."
    ),
)
def system_status() -> str:
    parts = []
    batt = _run(["pmset", "-g", "batt"]).stdout
    for tok in batt.split(";"):
        if "%" in tok:
            parts.append(f"battery {tok.strip().split()[0]}")
            break
    # free disk on the root volume
    df = _run(["df", "-h", "/"]).stdout.splitlines()
    if len(df) >= 2:
        cols = df[1].split()
        if len(cols) >= 4:
            parts.append(f"{cols[3]} free disk")
    # memory: pages free from vm_stat (page size 16 KB on Apple Silicon)
    vm = _run(["vm_stat"]).stdout
    try:
        free_pages = int([l for l in vm.splitlines() if "Pages free" in l][0]
                         .split(":")[1].strip().rstrip("."))
        spec = int([l for l in vm.splitlines() if "Pages speculative" in l][0]
                   .split(":")[1].strip().rstrip("."))
        free_gb = (free_pages + spec) * 16384 / 1e9
        parts.append(f"{free_gb:.1f} GB free memory")
    except Exception:
        pass
    return "; ".join(parts) if parts else "Couldn't read system status."


@registry.tool(
    name="set_volume",
    description="Set the Mac's output volume, 0 (mute) to 100 (max).",
    parameters={
        "type": "object",
        "properties": {
            "level": {"type": "integer", "description": "Volume 0-100."}
        },
        "required": ["level"],
    },
)
def set_volume(level: int) -> str:
    level = max(0, min(100, int(level)))
    _run(["osascript", "-e", f"set volume output volume {level}"])
    return f"Volume set to {level}."


@registry.tool(
    name="clipboard_get",
    description="Read whatever text is currently on the clipboard.",
)
def clipboard_get() -> str:
    text = _run(["pbpaste"]).stdout
    return text.strip() or "The clipboard is empty."


@registry.tool(
    name="clipboard_set",
    description="Copy text to the clipboard so the user can paste it.",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to copy."}
        },
        "required": ["text"],
    },
)
def clipboard_set(text: str) -> str:
    try:
        subprocess.run(["pbcopy"], input=text.encode(), timeout=8, check=False)
    except Exception as exc:
        return f"Couldn't copy that ({exc})."
    return "Copied to the clipboard."


@registry.tool(
    name="notify",
    description="Show a macOS notification banner.",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Notification title."},
            "message": {"type": "string", "description": "Notification body."},
        },
        "required": ["message"],
    },
)
def notify(message: str, title: str = "Jarvis") -> str:
    t = title.replace('"', "'")
    m = message.replace('"', "'")
    _run(["osascript", "-e", f'display notification "{m}" with title "{t}"'])
    return "Notification shown."


@registry.tool(
    name="set_timer",
    description=(
        "Set a timer. After the given number of seconds, Jarvis shows a "
        "notification and speaks the label."
    ),
    parameters={
        "type": "object",
        "properties": {
            "seconds": {"type": "integer", "description": "Delay in seconds."},
            "label": {"type": "string", "description": "What the timer is for."},
        },
        "required": ["seconds"],
    },
)
def set_timer(seconds: int, label: str = "Timer") -> str:
    seconds = max(1, int(seconds))

    def _fire() -> None:
        time.sleep(seconds)
        msg = f"{label} is up."
        _run(["osascript", "-e",
              f'display notification "{msg}" with title "Jarvis timer"'])
        _run(["say", msg], timeout=20)

    threading.Thread(target=_fire, daemon=True).start()
    mins = seconds / 60
    when = f"{seconds} seconds" if seconds < 60 else f"{mins:.0f} minutes"
    return f"Timer set for {when}: {label}."


# --------------------------------------------------------------------------- #
# notes
# --------------------------------------------------------------------------- #
@registry.tool(
    name="take_note",
    description="Save a quick note to the user's notes file for later.",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The note to save."}
        },
        "required": ["text"],
    },
)
def take_note(text: str) -> str:
    NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    with NOTES_PATH.open("a", encoding="utf-8") as fh:
        fh.write(f"- [{stamp}] {text.strip()}\n")
    return "Noted."


@registry.tool(
    name="read_notes",
    description="Read back the most recent saved notes.",
    parameters={
        "type": "object",
        "properties": {
            "count": {"type": "integer", "description": "How many recent notes."}
        },
    },
)
def read_notes(count: int = 5) -> str:
    if not NOTES_PATH.exists():
        return "There are no notes yet."
    lines = [l.strip() for l in NOTES_PATH.read_text("utf-8").splitlines() if l.strip()]
    if not lines:
        return "There are no notes yet."
    return "\n".join(lines[-max(1, int(count)):])


# --------------------------------------------------------------------------- #
# quick math
# --------------------------------------------------------------------------- #
_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv, ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def _eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("unsupported expression")


@registry.tool(
    name="calculate",
    description="Evaluate a basic arithmetic expression, e.g. '18 * 7 + 3'.",
    parameters={
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "The math to compute."}
        },
        "required": ["expression"],
    },
)
def calculate(expression: str) -> str:
    try:
        result = _eval(ast.parse(expression, mode="eval").body)
    except Exception:
        return f"I couldn't compute '{expression}'."
    if isinstance(result, float) and result.is_integer():
        result = int(result)
    return f"{expression} = {result}"


# --------------------------------------------------------------------------- #
# light file inspection
# --------------------------------------------------------------------------- #
@registry.tool(
    name="list_directory",
    description="List the files in a folder. Defaults to the home folder.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Folder path. Optional."}
        },
    },
)
def list_directory(path: str = "~") -> str:
    p = Path(path).expanduser()
    if not p.is_dir():
        return f"{p} isn't a folder."
    entries = sorted(e.name + ("/" if e.is_dir() else "") for e in p.iterdir())
    if not entries:
        return f"{p} is empty."
    shown = entries[:40]
    more = f" (+{len(entries) - 40} more)" if len(entries) > 40 else ""
    return ", ".join(shown) + more


@registry.tool(
    name="read_text_file",
    description="Read the contents of a small text file.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the text file."}
        },
        "required": ["path"],
    },
)
def read_text_file(path: str) -> str:
    p = Path(path).expanduser()
    if not p.is_file():
        return f"{p} isn't a file."
    try:
        text = p.read_text("utf-8", "replace")
    except Exception as exc:
        return f"Couldn't read {p} ({exc})."
    return text[:2000] + ("…" if len(text) > 2000 else "")
