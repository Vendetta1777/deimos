"""Built-in example tools.

These exist to prove the tool-calling loop end to end. Add your own here, or
create new modules and import them in main.py. Each tool is just a decorated
function — the local model decides when to call it.
"""
import subprocess
from datetime import datetime

from jarvis.tools.registry import registry


@registry.tool(
    name="get_current_time",
    description="Get the current local date and time.",
)
def get_current_time() -> str:
    return datetime.now().strftime("%A %d %B %Y, %I:%M %p")


@registry.tool(
    name="open_app",
    description="Open a macOS application by name, e.g. 'Safari' or 'Notes'.",
    parameters={
        "type": "object",
        "properties": {
            "app_name": {"type": "string", "description": "The application to open."}
        },
        "required": ["app_name"],
    },
)
def open_app(app_name: str) -> str:
    subprocess.run(["open", "-a", app_name], check=False)
    return f"Opened {app_name}."
