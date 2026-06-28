"""Watchers: background monitors that speak up when a condition becomes true.

The user arms one by voice ("tell me when my download finishes"); a background
loop in the server polls every few seconds and, when a watcher fires, has Deimos
announce it (aloud + orb + phone, via speak_now). Watchers are one-shot and live
in memory for the session.

Each watcher is a label (for listing) + a check() returning (fired, message).
"""
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from deimos.tools.registry import registry

_DOWNLOADS = Path.home() / "Downloads"
_TEMP_SUFFIXES = (".crdownload", ".download", ".part", ".partial", ".tmp")


def _num(value, default: int) -> int:
    m = re.search(r"\d+", str(value or ""))
    return int(m.group(0)) if m else default


# --------------------------------------------------------------------------- #
# Manager
# --------------------------------------------------------------------------- #
class _Watcher:
    def __init__(self, wid: int, label: str, check):
        self.id = wid
        self.label = label
        self.check = check
        self.created = time.time()


class Manager:
    def __init__(self):
        self._w: list[_Watcher] = []
        self._n = 0

    def add(self, label: str, check) -> int:
        self._n += 1
        self._w.append(_Watcher(self._n, label, check))
        return self._n

    def poll(self) -> list[str]:
        """Return the messages of any watchers that fired (and drop them)."""
        out = []
        for w in list(self._w):
            try:
                fired, msg = w.check()
            except Exception:
                fired, msg = False, ""
            if fired:
                out.append(msg)
                self._w.remove(w)
        return out

    def labels(self) -> list[str]:
        return [w.label for w in self._w]

    def clear(self) -> int:
        n = len(self._w)
        self._w.clear()
        return n


manager = Manager()


# --------------------------------------------------------------------------- #
# Watcher factories — each returns a check() -> (fired, message)
# --------------------------------------------------------------------------- #
def _downloads_accessible() -> bool:
    """macOS TCC blocks listing ~/Downloads without the user's permission."""
    try:
        next(iter(_DOWNLOADS.iterdir()), None)
        return True
    except Exception:
        return False


def _downloads_snapshot():
    inprog, done = set(), set()
    try:
        for p in _DOWNLOADS.iterdir():
            if p.name.startswith("."):
                continue
            (inprog if p.suffix.lower() in _TEMP_SUFFIXES else done).add(p.name)
    except Exception:
        pass
    return inprog, done


def _make_download():
    inprog0, done0 = _downloads_snapshot()

    def check():
        inprog, done = _downloads_snapshot()
        if inprog0:  # a download was already running — fire when it's gone
            if not (inprog & inprog0):
                return True, "Your download just finished."
            return False, ""
        # nothing running at arm time — fire on the next NEW completed file
        new = done - done0
        if new:
            return True, f"Your download finished: {sorted(new)[0]}."
        return False, ""

    return check


def _make_disk(threshold_gb: float = 5.0):
    def check():
        free = shutil.disk_usage("/").free / 1e9
        if free < threshold_gb:
            return True, f"Heads up — your disk is low, about {free:.0f} gigabytes free."
        return False, ""

    return check


def _battery():
    try:
        out = subprocess.run(["pmset", "-g", "batt"], capture_output=True,
                             text=True, timeout=8).stdout
    except Exception:
        return None, False
    m = re.search(r"(\d+)%", out)
    charging = "AC Power" in out or "charging" in out.lower()
    return (int(m.group(1)) if m else None), charging


def _make_battery(target: int = 100):
    def check():
        pct, _ = _battery()
        if pct is None:
            return False, ""
        if pct >= target:
            return True, f"Your battery's at {pct} percent."
        return False, ""

    return check


def _make_idle():
    cores = os.cpu_count() or 4
    state = {"was_busy": False}

    def check():
        load = os.getloadavg()[0]
        if load > cores * 0.9:
            state["was_busy"] = True
        if state["was_busy"] and load < cores * 0.5:
            return True, "Your Mac's settled down — it's free now."
        return False, ""

    return check


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
@registry.tool(
    name="add_watcher",
    description=(
        "Watch for something in the background and speak up when it happens. "
        "kind is one of: download (a download finishing), disk (free space "
        "getting low), battery (reaching a level — value = percent), idle (the "
        "Mac becoming free after being busy). Use for 'tell me when my download "
        "finishes', 'let me know when the battery's full', 'tell me when my mac "
        "is free'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "kind": {"type": "string", "description": "download, disk, battery, or idle."},
            "value": {"type": "string", "description": "For battery: target percent. For disk: GB threshold."},
        },
        "required": ["kind"],
    },
)
def add_watcher(kind: str, value: str = "") -> str:
    k = (kind or "").strip().lower()
    if k == "download":
        if not _downloads_accessible():
            return ("I can't see your Downloads folder yet — grant access under "
                    "System Settings, Privacy & Security, Files and Folders (or "
                    "Full Disk Access), then ask me again.")
        manager.add("a download finishing", _make_download())
        return "Got it — I'll tell you when your download finishes."
    if k == "disk":
        thr = _num(value, 5)
        manager.add(f"disk dropping below {thr} GB", _make_disk(thr))
        return f"Okay — I'll warn you if free disk drops below {thr} gigabytes."
    if k == "battery":
        tgt = _num(value, 100)
        manager.add(f"battery reaching {tgt}%", _make_battery(tgt))
        return f"Sure — I'll tell you when your battery reaches {tgt} percent."
    if k == "idle":
        manager.add("the Mac becoming free", _make_idle())
        return "Okay — I'll let you know when your Mac frees up."
    return ("I can watch for a download finishing, disk getting low, a battery "
            "level, or the Mac becoming free.")


@registry.tool(name="list_watchers", description="List what Deimos is currently watching for.")
def list_watchers() -> str:
    items = manager.labels()
    if not items:
        return "I'm not watching anything right now."
    return "I'm watching for: " + "; ".join(items) + "."


@registry.tool(name="clear_watchers", description="Stop and clear all active watchers.")
def clear_watchers() -> str:
    n = manager.clear()
    return f"Cleared {n} watcher{'s' if n != 1 else ''}." if n else "There was nothing to clear."
