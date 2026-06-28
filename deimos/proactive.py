"""Proactive behaviour: the things Deimos says without being asked.

Two pieces live here, both pure/composing logic (no audio, no scheduling — the
server owns those):
  - compose_briefing(): the spoken morning briefing (date, weather, calendar,
    reminders), also reachable on demand via "brief me".
  - greeting helpers used by the briefing.

The scheduler that decides WHEN to speak, and the actual speaking, live in
server.py where the TTS engine and the busy/ wake-word locks are.
"""
import datetime
import re

from deimos.config import CONFIG
from deimos.memory import memory
from deimos.tools.registry import registry


def time_greeting() -> str:
    h = datetime.datetime.now().hour
    if h < 12:
        part = "Good morning"
    elif h < 18:
        part = "Good afternoon"
    else:
        part = "Good evening"
    name = user_name()
    return f"{part}, {name}." if name else f"{part}."


def user_name() -> str | None:
    """Best-effort first name from stored facts, e.g. 'The user is named Ved.'"""
    for f in memory.all_facts():
        m = re.search(r"\b(?:is named|name is|named|i'?m|i am)\s+([A-Z][a-z]+)", f, re.I)
        if m:
            return m.group(1).capitalize()
    return None


def _clean(s: str) -> str:
    return (s or "").strip().rstrip(".")


def _ok(s: str) -> bool:
    """True if a tool result is a usable answer, not an error/failure string."""
    if not s:
        return False
    low = s.lower()
    bad = ("error", "couldn't", "could not", "timed out", "isn't responding",
           "no url", "not set up")
    return not any(b in low for b in bad)


def compose_briefing(greet: bool = True) -> str:
    """Build a short, speakable daily briefing. Each piece is best-effort: if a
    source fails it's simply left out, so the briefing always returns something."""
    parts: list[str] = []
    if greet:
        parts.append(time_greeting())

    now = datetime.datetime.now()
    parts.append(f"It's {now.strftime('%A, %B %-d')}.")

    # Weather (the tool returns a full spoken sentence).
    try:
        wx = registry.call("get_weather", {"location": ""})
        if _ok(wx):
            parts.append(_clean(wx) + ".")
    except Exception:
        pass

    # Calendar — today.
    try:
        cal = registry.call("calendar_events", {"when": "today"})
        if _ok(cal):
            parts.append(_clean(cal) + ".")
    except Exception:
        pass

    # Markets — a one-line read on the S&P (the user's a finance person).
    if getattr(CONFIG, "briefing_markets", False):
        try:
            from deimos.tools import finance
            q = finance._quote("^GSPC")
            if q and q.get("change") is not None:
                arrow = "up" if q["change"] >= 0 else "down"
                parts.append(f"The S&P 500 is {arrow} {abs(q['change']):.1f} percent.")
        except Exception:
            pass

    # Reminders — summarise (count, not the whole list, to keep it brief).
    try:
        from deimos.tools import personal
        rem = personal.list_reminders()
        if rem and rem.startswith("Your reminders"):
            n = rem.count(";") + 1
            parts.append(f"And you have {n} open reminder{'s' if n != 1 else ''}.")
        elif rem and "no open reminders" in rem.lower():
            pass
    except Exception:
        pass

    return " ".join(parts)
