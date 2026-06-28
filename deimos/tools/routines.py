"""Routines: one phrase runs a whole sequence of actions — the 'scenes' that
make Deimos feel like a real assistant ("study mode", "wind down").

A routine is just an ordered list of (tool, args) steps plus a line to speak.
Steps run in order; a failing step is skipped so the routine always finishes.
Edit ROUTINES to taste — add your own apps, music, timers, reminders.
"""
from deimos.tools.registry import registry

ROUTINES: dict[str, dict] = {
    "study": {
        "say": "Study mode on — distractions cleared, lo-fi playing, and a "
               "25-minute timer running. Focus up.",
        "steps": [
            ("mac_control", {"action": "quit_app", "value": "Messages"}),
            ("mac_control", {"action": "quit_app", "value": "Discord"}),
            ("mac_control", {"action": "hide_others"}),
            ("open_app", {"app_name": "Notes"}),
            ("play_music", {"query": "lo-fi beats", "kind": "playlist"}),
            ("set_timer", {"seconds": 1500, "label": "Study session"}),
        ],
    },
    "focus": {
        "say": "Focus mode — chat apps closed and everything else hidden. Deep work time.",
        "steps": [
            ("mac_control", {"action": "quit_app", "value": "Messages"}),
            ("mac_control", {"action": "quit_app", "value": "Discord"}),
            ("mac_control", {"action": "hide_others"}),
        ],
    },
    "wind_down": {
        "say": "Winding down — music paused, screen dimmed to dark, and a reminder "
               "set to pick up tomorrow. Rest well.",
        "steps": [
            ("media_control", {"action": "pause"}),
            ("mac_control", {"action": "dark_mode_on"}),
            ("mac_control", {"action": "quit_app", "value": "Slack"}),
            ("add_reminder", {"text": "Pick up where I left off", "when": "tomorrow 9am"}),
        ],
    },
}

# Spoken phrasings -> routine key.
_ALIASES = {
    "study": "study", "study mode": "study", "studying": "study", "homework": "study",
    "focus": "focus", "focus mode": "focus", "deep work": "focus", "lock in": "focus",
    "wind down": "wind_down", "winddown": "wind_down", "wind-down": "wind_down",
    "bedtime": "wind_down", "good night": "wind_down",
}


def resolve(name: str) -> str | None:
    n = (name or "").strip().lower()
    if n in ROUTINES:
        return n
    if n in _ALIASES:
        return _ALIASES[n]
    n2 = n.replace(" mode", "").strip()
    return ROUTINES.get(n2) and n2 or _ALIASES.get(n2)


@registry.tool(
    name="run_routine",
    description=(
        "Run a multi-step routine ('scene') by name. Known routines: study (clear "
        "distractions, lo-fi, 25-min timer), focus (hide apps, close chat), "
        "wind_down (pause music, dark mode, reminder for tomorrow). Use for "
        "'study mode', 'focus mode', 'wind down', 'lock in', 'good night'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Routine name, e.g. study, focus, wind_down."}
        },
        "required": ["name"],
    },
)
def run_routine(name: str) -> str:
    key = resolve(name)
    if not key:
        return f"I don't have a '{name}' routine. I know study, focus, and wind down."
    routine = ROUTINES[key]
    for tool, args in routine["steps"]:
        try:
            registry.call(tool, args)  # failures are non-fatal; keep going
        except Exception:
            pass
    return routine["say"]
