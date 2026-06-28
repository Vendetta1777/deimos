"""Routines: one phrase runs a whole sequence of actions — the 'scenes' that
make Deimos feel like a real assistant ("study mode", "dev mode for money path").

A routine is an ordered list of (tool, args) steps plus a line to speak. Steps
run in order; a failing step is skipped so the routine always finishes. A
routine with a "timer" key also starts a timer (minutes overridable by voice,
e.g. "study mode for 45 minutes"). Edit ROUTINES freely.
"""
from deimos.tools.registry import registry

ROUTINES: dict[str, dict] = {
    "study": {
        # {min} is filled with the actual timer length.
        "say": "Study mode on — distractions closed, your playlist's on, and a "
               "{min}-minute timer is running. Lock in.",
        "timer": 25,  # default minutes; say "study mode for N minutes" to override
        "steps": [
            ("mac_control", {"action": "close_distractions"}),
            ("play_my_music", {}),
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
            ("add_reminder", {"text": "Pick up where I left off", "when": "tomorrow 9am"}),
        ],
    },
    # --- dev workspaces ---------------------------------------------------- #
    "dev_money_path": {
        "say": "Money Path dev mode — folder, the game, and a terminal are up. Let's build.",
        "steps": [
            ("run_command", {"command": "open ~/money-path"}),
            ("run_command", {"command": "open -a 'Google Chrome' ~/money-path/index.html"}),
            ("run_command", {"command": "open -a Terminal ~/money-path"}),
        ],
    },
    "dev_invoice": {
        "say": "Invoice dev mode — folder, a terminal, and the repo are open.",
        "steps": [
            ("run_command", {"command": "open ~/invoice-automation"}),
            ("run_command", {"command": "open -a Terminal ~/invoice-automation"}),
            ("open_url", {"url": "https://github.com/Vendetta1777/invoice-automation"}),
        ],
    },
}

# Spoken phrasings -> routine key.
_ALIASES = {
    "study": "study", "study mode": "study", "studying": "study", "homework": "study",
    "focus": "focus", "focus mode": "focus", "deep work": "focus", "lock in": "focus",
    "wind down": "wind_down", "winddown": "wind_down", "wind-down": "wind_down",
    "bedtime": "wind_down", "good night": "wind_down",
    "dev money path": "dev_money_path", "money path dev": "dev_money_path",
    "dev invoice": "dev_invoice", "invoice dev": "dev_invoice",
}


def resolve(name: str) -> str | None:
    n = (name or "").strip().lower()
    if n in ROUTINES:
        return n
    if n in _ALIASES:
        return _ALIASES[n]
    n2 = n.replace(" mode", "").strip()
    return (n2 if n2 in ROUTINES else None) or _ALIASES.get(n2)


@registry.tool(
    name="run_routine",
    description=(
        "Run a multi-step routine ('scene') by name. Known: study (close "
        "distracting tabs, play the user's playlist, start a timer), focus, "
        "wind_down, dev_money_path, dev_invoice. For 'study mode for 45 minutes' "
        "pass minutes=45. Use for 'study mode', 'focus mode', 'wind down', "
        "'dev mode for money path', 'work on the invoice'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Routine name, e.g. study, dev_money_path."},
            "minutes": {"type": "integer", "description": "Optional timer length for study, in minutes."},
        },
        "required": ["name"],
    },
)
def run_routine(name: str, minutes: int = 0) -> str:
    key = resolve(name)
    if not key:
        return (f"I don't have a '{name}' routine. I know study, focus, wind down, "
                "and dev mode for Money Path or the invoice app.")
    routine = ROUTINES[key]
    for tool, args in routine["steps"]:
        try:
            registry.call(tool, args)  # failures are non-fatal; keep going
        except Exception:
            pass
    say = routine["say"]
    if "timer" in routine:
        try:
            mins = int(minutes) if minutes and int(minutes) > 0 else routine["timer"]
        except (TypeError, ValueError):
            mins = routine["timer"]
        label = key.replace("_", " ").title() + " session"
        registry.call("set_timer", {"seconds": mins * 60, "label": label})
        say = say.replace("{min}", str(mins))
    return say
