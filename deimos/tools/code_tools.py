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

import ollama

from deimos.config import CONFIG
from deimos.memory import memory
from deimos.tools.registry import registry

# Project root = the folder that contains the `deimos` package (…/deimos).
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Standing instructions prepended to every Claude Code run, to lift build
# quality regardless of project type. The user's own request follows.
QUALITY_PREAMBLE = (
    "Build to a production-quality standard. Follow any CLAUDE.md in this "
    "project. If anything is ambiguous, make strong, modern default choices "
    "rather than asking. Request: "
)


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


def _expand_spec(instruction: str) -> str:
    """Use the larger coder model to turn the request into a detailed build spec.

    Runs only here (not in everyday chat) and lets the coder model unload when
    idle. Falls back to the raw instruction if the ollama call fails for any
    reason, so a coding run never depends on this step succeeding.
    """
    try:
        client = ollama.Client(host=CONFIG.ollama_host)
        resp = client.chat(
            model=CONFIG.coder_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior engineer. Rewrite the user's request "
                        "into a precise, detailed, actionable build/edit spec for "
                        "a coding agent. Be concrete about structure, features, "
                        "and quality. Output only the spec."
                    ),
                },
                {"role": "user", "content": instruction},
            ],
            keep_alive=CONFIG.coder_keep_alive,
        )
        spec = (resp.message.content or "").strip()
        return spec or instruction
    except Exception:
        return instruction


def _open_index(cwd: Path) -> bool:
    """Open the project's root index.html in a clean window. Returns True if it
    found one and launched the opener."""
    index = cwd / "index.html"
    if not index.exists():
        return False
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    try:
        if Path(chrome).exists():
            subprocess.Popen(
                [chrome, f"--app=file://{index.resolve()}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen(
                ["open", str(index)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        return True
    except Exception:
        return False


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
    is_self = cwd == PROJECT_ROOT

    snapshot = _snapshot(cwd)
    snap_note = f" Snapshot {snapshot[:8]} saved (undo: git -C {cwd} reset --hard {snapshot[:8]})." if snapshot else ""

    # Expand the request into a detailed spec with the coder model, then prepend
    # the standing quality preamble. Spec expansion falls back to the raw text.
    spec = _expand_spec(instruction)
    full_instruction = QUALITY_PREAMBLE + spec
    try:
        result = subprocess.run(
            ["claude", "-p", full_instruction, "--dangerously-skip-permissions"],
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
    target = "myself" if is_self else cwd.name

    # For real projects (not self-edits): remember it as the active project so
    # the user can iterate by voice, and open its index.html if it built a site.
    opened_note = ""
    if not is_self:
        memory.set_active_project(str(cwd))
        if _open_index(cwd):
            opened_note = " I opened it in a window so you can see it."

    return f"Ran your request on {target}.{snap_note}{opened_note}\n\n{summary}"
