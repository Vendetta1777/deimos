"""Let Deimos run Claude Code on your behalf.

The model calls run_claude_code with a plain-language instruction and a target
project. We resolve the folder, take an automatic git snapshot (so any change
is undoable), then run the `claude` CLI there non-interactively and read back
what it did.

Safety net: every run is preceded by a git commit. If a run makes a mess —
including Deimos editing itself — you can undo it with:
    git -C <project> reset --hard <snapshot-hash>
The snapshot hash is included in the tool's reply.
"""
import subprocess
import time
from pathlib import Path

from deimos.config import CONFIG
from deimos.tools.registry import registry

# Project root = the folder that contains the `deimos` package (…/deimos).
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resolve_project(project_path: str) -> Path:
    if not project_path or project_path.lower() in {"self", "deimos", "yourself"}:
        return PROJECT_ROOT
    p = Path(project_path).expanduser()
    if not p.is_absolute():
        p = Path(CONFIG.projects_dir).expanduser() / project_path
    return p


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    base = ["git", "-c", "user.name=Deimos", "-c", "user.email=deimos@local", "-C", str(cwd)]
    return subprocess.run(base + list(args), capture_output=True, text=True)


def _snapshot(cwd: Path) -> str | None:
    """Commit the current state so the upcoming change can be undone."""
    if not CONFIG.code_auto_snapshot:
        return None
    if not (cwd / ".git").exists():
        _git(cwd, "init")
    _git(cwd, "add", "-A")
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    _git(cwd, "commit", "-m", f"deimos snapshot before edit {stamp}", "--allow-empty")
    rev = _git(cwd, "rev-parse", "HEAD")
    return rev.stdout.strip() or None


@registry.tool(
    name="run_claude_code",
    description=(
        "Build, edit, or fix code, websites, or projects by running Claude Code. "
        "Pass the user's full request as 'instruction'. Set 'project_path' to the "
        "project folder name or path, or 'self' to modify Deimos itself."
    ),
    parameters={
        "type": "object",
        "properties": {
            "instruction": {
                "type": "string",
                "description": "The full task to carry out, in plain language.",
            },
            "project_path": {
                "type": "string",
                "description": "Project folder name/path, or 'self' for Deimos itself.",
            },
        },
        "required": ["instruction", "project_path"],
    },
)
def run_claude_code(instruction: str, project_path: str = "self") -> str:
    cwd = _resolve_project(project_path)
    cwd.mkdir(parents=True, exist_ok=True)

    snapshot = _snapshot(cwd)
    snap_note = f" Snapshot {snapshot[:8]} saved (undo: git -C {cwd} reset --hard {snapshot[:8]})." if snapshot else ""

    try:
        result = subprocess.run(
            ["claude", "-p", instruction, "--dangerously-skip-permissions"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=CONFIG.code_timeout,
        )
    except FileNotFoundError:
        return "Claude Code isn't installed or not on PATH, so I couldn't run that."
    except subprocess.TimeoutExpired:
        return f"That task ran past the time limit and was stopped.{snap_note}"

    out = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    summary = out[-1200:] if out else (err[-600:] if err else "Done, no output returned.")
    target = "myself" if cwd == PROJECT_ROOT else cwd.name
    return f"Ran your request on {target}.{snap_note}\n\n{summary}"
