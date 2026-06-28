"""One general Mac-control tool — many system actions behind a single tool, so
the model's tool menu (and its reliability) doesn't balloon.

Everything here uses methods that need at most the Automation permission you
already grant for Calendar/Reminders (osascript -> app) or plain shell — NOT
Accessibility — so there's no new permission wall. Each action returns a short
spoken line and never raises into the tool loop.
"""
import subprocess
import time
from pathlib import Path

from deimos.tools.registry import registry


def _sh(cmd: list[str], timeout: float = 12.0) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def _osa(script: str, timeout: float = 12.0) -> subprocess.CompletedProcess:
    return _sh(["osascript", "-e", script], timeout)


def _esc(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace('"', '\\"')


def _wifi_device() -> str:
    """Best-effort Wi-Fi interface name (en0/en1), defaulting to en0."""
    r = _sh(["networksetup", "-listallhardwareports"])
    lines = (r.stdout or "").splitlines()
    for i, ln in enumerate(lines):
        if "Wi-Fi" in ln and i + 1 < len(lines):
            parts = lines[i + 1].split()
            if len(parts) >= 2:
                return parts[-1]
    return "en0"


# --- individual actions; each returns a speakable string ------------------- #
def _dark(mode: str):
    expr = {"on": "true", "off": "false"}.get(mode, "not dark mode")
    r = _osa('tell application "System Events" to tell appearance preferences '
             f'to set dark mode to {expr}')
    if r.returncode != 0:
        return "I couldn't change the appearance."
    return "Dark mode on." if mode == "on" else "Light mode on." if mode == "off" else "Toggled the appearance."


def _mute(on: bool):
    _osa(f"set volume {'with' if on else 'without'} output muted")
    return "Muted." if on else "Unmuted."


def _lock():
    # CGSession -suspend locks without needing Accessibility / synthetic keys.
    _sh(["/System/Library/CoreServices/Menu Extras/User.menu/Contents/Resources/CGSession",
         "-suspend"])
    return "Locking the screen."


def _sleep():
    _sh(["pmset", "sleepnow"])
    return "Going to sleep."


def _screensaver():
    _sh(["open", "-a", "ScreenSaverEngine"])
    return "Starting the screensaver."


def _keep_awake(secs: int = 3600):
    subprocess.Popen(["caffeinate", "-d", "-t", str(secs)],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return f"I'll keep the Mac awake for {secs // 60} minutes."


def _allow_sleep():
    _sh(["pkill", "caffeinate"])
    return "The Mac can sleep normally again."


def _empty_trash():
    r = _osa('tell application "Finder" to empty the trash')
    return "Trash emptied." if r.returncode == 0 else "I couldn't empty the trash."


def _screenshot():
    path = Path.home() / "Desktop" / f"Deimos-{time.strftime('%Y%m%d-%H%M%S')}.png"
    r = _sh(["screencapture", "-x", str(path)])
    return f"Screenshot saved to your Desktop." if r.returncode == 0 else "I couldn't take a screenshot."


def _quit_app(name: str):
    if not name:
        return "Which app should I quit?"
    r = _osa(f'tell application "{_esc(name)}" to quit')
    return f"Closed {name}." if r.returncode == 0 else f"I couldn't close {name}."


def _hide_others():
    # Hide every visible app except the frontmost — a reliable 'focus' move.
    # Never hide Deimos's own orb window (process "jarvis-window"/"Deimos"), or
    # it would hide itself mid-routine.
    _osa('tell application "System Events" to set visible of '
         '(every process whose visible is true and frontmost is false '
         'and name does not contain "jarvis" and name does not contain "eimos") '
         'to false')
    return "Hid the other apps."


def _wifi(on: bool):
    dev = _wifi_device()
    r = _sh(["networksetup", "-setairportpower", dev, "on" if on else "off"])
    if r.returncode != 0:
        return "I couldn't change Wi-Fi."
    return "Wi-Fi on." if on else "Wi-Fi off."


def _status():
    return registry.call("system_status", {})


def _close_distractions():
    from deimos.config import CONFIG
    if not Path("/Applications/Google Chrome.app").exists():
        return "Chrome isn't installed."
    sites = [s for s in CONFIG.distracting_sites if s]
    if not sites:
        return "No distracting sites are configured."
    conds = " or ".join(f'u contains "{_esc(s)}"' for s in sites)
    # Iterate tabs backwards so closing one doesn't shift the indexes we haven't
    # checked. Never launch Chrome just to do this.
    script = (
        'if application "Google Chrome" is running then\n'
        '  tell application "Google Chrome"\n'
        '    set n to 0\n'
        '    repeat with w in windows\n'
        '      set i to (count of tabs of w)\n'
        '      repeat while i is greater than 0\n'
        '        set u to URL of tab i of w\n'
        f'        if {conds} then\n'
        '          close tab i of w\n'
        '          set n to n + 1\n'
        '        end if\n'
        '        set i to i - 1\n'
        '      end repeat\n'
        '    end repeat\n'
        '    return n\n'
        '  end tell\n'
        'else\n'
        '  return -1\n'
        'end if'
    )
    r = _osa(script, timeout=15)
    if r.returncode != 0:
        return "I couldn't reach Chrome to close tabs."
    out = (r.stdout or "").strip()
    if out == "-1":
        return "Chrome isn't open."
    try:
        n = int(out)
    except ValueError:
        n = 0
    return f"Closed {n} distracting tab{'s' if n != 1 else ''}." if n else "No distracting tabs were open."


_ACTIONS = {
    "dark_mode": lambda v: _dark("toggle"),
    "dark_mode_on": lambda v: _dark("on"),
    "dark_mode_off": lambda v: _dark("off"),
    "mute": lambda v: _mute(True),
    "unmute": lambda v: _mute(False),
    "lock_screen": lambda v: _lock(),
    "sleep": lambda v: _sleep(),
    "screensaver": lambda v: _screensaver(),
    "keep_awake": lambda v: _keep_awake(),
    "allow_sleep": lambda v: _allow_sleep(),
    "empty_trash": lambda v: _empty_trash(),
    "screenshot": lambda v: _screenshot(),
    "quit_app": lambda v: _quit_app(v),
    "hide_others": lambda v: _hide_others(),
    "wifi_on": lambda v: _wifi(True),
    "wifi_off": lambda v: _wifi(False),
    "close_distractions": lambda v: _close_distractions(),
    "status": lambda v: _status(),
}


@registry.tool(
    name="mac_control",
    description=(
        "Control the Mac's system settings and state. The action is one of: "
        "dark_mode, dark_mode_on, dark_mode_off, mute, unmute, lock_screen, "
        "sleep, screensaver, keep_awake, allow_sleep, empty_trash, screenshot, "
        "quit_app (set value to the app name), hide_others, close_distractions "
        "(close distracting Chrome tabs), wifi_on, wifi_off, "
        "status. Use for 'lock my screen', 'go dark', 'mute', 'empty the trash', "
        "'keep my mac awake', 'close Discord', 'turn off wifi', etc."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "The action name (see list)."},
            "value": {"type": "string", "description": "Extra argument, e.g. the app name for quit_app."},
        },
        "required": ["action"],
    },
)
def mac_control(action: str, value: str = "") -> str:
    key = (action or "").strip().lower()
    fn = _ACTIONS.get(key)
    if not fn:
        return f"I don't have a '{action}' action."
    return fn((value or "").strip())
