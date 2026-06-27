"""Personal-life tools via the native macOS apps — no accounts, no OAuth.

Reminders, Calendar, and Messages are driven through AppleScript, so they use
whatever accounts you've already added to macOS (Google, iCloud, …). The first
time Deimos controls each app, macOS asks you to allow it (System Settings ->
Privacy & Security -> Automation) — approve once and it's set.

Sending a message is an outward, hard-to-undo action, so it asks for a native
confirmation first. Natural times ("tomorrow at 4pm") are parsed with dateparser.
"""
import re
import subprocess

import dateparser

from deimos.tools.registry import registry


def _osa(script: str, timeout: float = 25.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=timeout, check=False,
    )


def _esc(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace('"', '\\"')


def _parse_when(when: str):
    if not when or not when.strip():
        return None
    return dateparser.parse(when, settings={"PREFER_DATES_FROM": "future"})


def _date_lines(var: str, dt) -> str:
    # Build an AppleScript date by components (robust across locales). Set day to
    # 1 before changing month so a month change can't overflow the day.
    return "\n".join([
        f"set {var} to current date",
        f"set year of {var} to {dt.year}",
        f"set day of {var} to 1",
        f"set month of {var} to {dt.month}",
        f"set day of {var} to {dt.day}",
        f"set hours of {var} to {dt.hour}",
        f"set minutes of {var} to {dt.minute}",
        f"set seconds of {var} to 0",
    ])


# --------------------------------------------------------------------------- #
# Reminders
# --------------------------------------------------------------------------- #
@registry.tool(
    name="add_reminder",
    description=(
        "Add a reminder to the Reminders app, optionally with a due time. Use "
        "for 'remind me to <x>', 'remind me at <time> to <x>'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "What to be reminded about."},
            "when": {"type": "string", "description": "When, e.g. 'tomorrow 4pm', '8pm'. Optional."},
        },
        "required": ["text"],
    },
)
def add_reminder(text: str, when: str = "") -> str:
    text = (text or "").strip()
    if not text:
        return "What should I remind you about?"
    dt = _parse_when(when)
    safe = _esc(text)
    if dt:
        script = _date_lines("d", dt) + (
            f'\ntell application "Reminders" to make new reminder '
            f'with properties {{name:"{safe}", remind me date:d}}'
        )
        whenstr = dt.strftime("%-I:%M %p on %A")
    else:
        script = (
            f'tell application "Reminders" to make new reminder '
            f'with properties {{name:"{safe}"}}'
        )
        whenstr = ""
    r = _osa(script)
    if r.returncode != 0:
        return f"I couldn't add that reminder ({(r.stderr or '').strip()[:80]})."
    return f"Reminder set: {text}" + (f", {whenstr}." if whenstr else ".")


@registry.tool(
    name="list_reminders",
    description="Read back the user's open (incomplete) reminders.",
)
def list_reminders() -> str:
    script = (
        'set out to ""\n'
        'tell application "Reminders"\n'
        '  repeat with r in (reminders whose completed is false)\n'
        '    set out to out & (name of r) & linefeed\n'
        '  end repeat\n'
        'end tell\n'
        'return out'
    )
    r = _osa(script, timeout=30)
    if r.returncode != 0:
        return f"I couldn't read your reminders ({(r.stderr or '').strip()[:60]})."
    items = [s.strip() for s in (r.stdout or "").splitlines() if s.strip()]
    if not items:
        return "You have no open reminders."
    shown = "; ".join(items[:12])
    more = f", plus {len(items) - 12} more" if len(items) > 12 else ""
    return f"Your reminders: {shown}{more}."


# --------------------------------------------------------------------------- #
# Calendar
# --------------------------------------------------------------------------- #
@registry.tool(
    name="add_event",
    description=(
        "Add an event to the Calendar app at a given time. Use for 'add <x> at "
        "<time>', 'schedule <x> for <time>', 'put <x> on my calendar'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "The event title."},
            "when": {"type": "string", "description": "Start time, e.g. 'tomorrow 4pm', 'friday 3pm'."},
        },
        "required": ["title", "when"],
    },
)
def add_event(title: str, when: str = "") -> str:
    title = (title or "").strip()
    if not title:
        return "What's the event?"
    dt = _parse_when(when)
    if not dt:
        return f"When is '{title}'? I couldn't understand that time."
    safe = _esc(title)
    script = _date_lines("startD", dt) + (
        '\nset endD to startD + (60 * 60)\n'
        'tell application "Calendar"\n'
        '  tell calendar 1\n'
        f'    make new event with properties {{summary:"{safe}", start date:startD, end date:endD}}\n'
        '  end tell\n'
        'end tell'
    )
    r = _osa(script)
    if r.returncode != 0:
        return f"I couldn't add that event ({(r.stderr or '').strip()[:80]})."
    return f"Added '{title}' to your calendar for {dt.strftime('%-I:%M %p, %A %B %-d')}."


@registry.tool(
    name="calendar_events",
    description=(
        "Read the user's calendar events for today, tomorrow, or this week. Use "
        "for 'what's on my calendar', 'what's my day', 'what's on tomorrow'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "when": {"type": "string", "description": "'today', 'tomorrow', or 'week'. Default today."}
        },
    },
)
def calendar_events(when: str = "today") -> str:
    w = (when or "today").lower()
    offset = 1 if "tomorrow" in w else 0
    days = 7 if ("week" in w or "upcoming" in w) else 1
    script = (
        "set startD to current date\n"
        "set hours of startD to 0\nset minutes of startD to 0\nset seconds of startD to 0\n"
        f"set startD to startD + ({offset} * days)\n"
        f"set endD to startD + ({days} * days)\n"
        'set out to ""\n'
        'tell application "Calendar"\n'
        "  repeat with c in calendars\n"
        "    repeat with e in (every event of c whose start date ≥ startD and start date < endD)\n"
        '      set out to out & (summary of e) & " at " & (time string of (start date of e)) & linefeed\n'
        "    end repeat\n"
        "  end repeat\n"
        "end tell\n"
        "return out"
    )
    r = _osa(script, timeout=35)
    if r.returncode != 0:
        return f"I couldn't read your calendar ({(r.stderr or '').strip()[:60]})."
    items = [s.strip() for s in (r.stdout or "").splitlines() if s.strip()]
    label = "tomorrow" if offset else ("this week" if days == 7 else "today")
    if not items:
        return f"Nothing on your calendar {label}."
    return f"On your calendar {label}: " + "; ".join(items[:10]) + "."


def todays_events_struct() -> list[tuple]:
    """Return today's events as (start datetime, title) pairs for the proactive
    nudger. Times are naive local. Returns [] on any failure (never raises)."""
    import datetime as _dt

    script = (
        "set d0 to current date\n"
        "set hours of d0 to 0\nset minutes of d0 to 0\nset seconds of d0 to 0\n"
        "set d1 to d0 + (1 * days)\n"
        'set out to ""\n'
        'tell application "Calendar"\n'
        "  repeat with c in calendars\n"
        "    repeat with e in (every event of c whose start date ≥ d0 and start date < d1)\n"
        "      set sd to start date of e\n"
        '      set out to out & (year of sd) & "/" & (month of sd as integer) & "/" '
        '& (day of sd) & "/" & (hours of sd) & "/" & (minutes of sd) & "|" '
        "& (summary of e) & linefeed\n"
        "    end repeat\n"
        "  end repeat\n"
        "end tell\n"
        "return out"
    )
    try:
        r = _osa(script, timeout=35)
    except Exception:
        return []
    if r.returncode != 0:
        return []
    out = []
    for ln in (r.stdout or "").splitlines():
        ln = ln.strip()
        if "|" not in ln:
            continue
        stamp, title = ln.split("|", 1)
        try:
            y, mo, da, hh, mm = (int(x) for x in stamp.split("/"))
            out.append((_dt.datetime(y, mo, da, hh, mm), title.strip()))
        except (ValueError, TypeError):
            continue
    return out


# --------------------------------------------------------------------------- #
# Messages (iMessage)
# --------------------------------------------------------------------------- #
def _resolve_handle(recipient: str) -> str | None:
    r = (recipient or "").strip()
    if not r:
        return None
    if "@" in r or re.match(r"^[+\d][\d\-\s()]{5,}$", r):
        return r  # already a phone/email handle
    safe = _esc(r)
    for field in ("phone", "email"):
        res = _osa(
            f'tell application "Contacts" to get value of (first {field} of '
            f'(first person whose name contains "{safe}"))',
            timeout=15,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    return None


def _confirm_send(name: str, handle: str, body: str) -> bool:
    prompt = _esc(f"Send to {name} ({handle}):\n\n{body}")
    r = _osa(
        f'display dialog "{prompt}" buttons {{"Cancel", "Send"}} '
        'default button "Cancel" with icon note giving up after 45',
        timeout=60,
    )
    return r.returncode == 0 and "Send" in r.stdout


@registry.tool(
    name="send_message",
    description=(
        "Send an iMessage to a contact (by name) or a phone number. Use for "
        "'text <person> <message>', 'message <person> saying <x>'. The user is "
        "asked to confirm before it sends."
    ),
    parameters={
        "type": "object",
        "properties": {
            "recipient": {"type": "string", "description": "Contact name or phone number."},
            "body": {"type": "string", "description": "The message text."},
        },
        "required": ["recipient", "body"],
    },
)
def send_message(recipient: str, body: str) -> str:
    recipient = (recipient or "").strip()
    body = (body or "").strip()
    if not recipient or not body:
        return "Who should I message, and what should I say?"
    handle = _resolve_handle(recipient)
    if not handle:
        return f"I couldn't find a contact or number for '{recipient}'."
    if not _confirm_send(recipient, handle, body):
        return "Cancelled — I didn't send it."
    script = (
        'tell application "Messages"\n'
        '  set svc to 1st service whose service type = iMessage\n'
        f'  send "{_esc(body)}" to participant "{_esc(handle)}" of svc\n'
        'end tell'
    )
    r = _osa(script, timeout=20)
    if r.returncode != 0:
        return f"I couldn't send that ({(r.stderr or '').strip()[:80]})."
    return f"Sent to {recipient}: {body}"
