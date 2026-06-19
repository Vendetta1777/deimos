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
import re
import subprocess
import time
from pathlib import Path

import ollama

from deimos.config import CONFIG
from deimos.memory import memory
from deimos.progress import progress
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

# When Deimos edits ITSELF and the request is about how it looks, the change
# belongs in the web/ frontend — not the Python brain/config. We detect that and
# steer Claude Code to the right files. Word boundaries keep "ui" from matching
# inside words like "build".
_VISUAL_RE = re.compile(
    r"\b(look|looks|looking|visual|visuals|visually|interface|orb|design|"
    r"redesign|colou?r|colou?rs|theme|themes|ui|ux|appearance|layout|style|"
    r"styling|animation|animations)\b",
    re.IGNORECASE,
)

VISUAL_SELF_NOTE = (
    "This is a VISUAL polish of Deimos's EXISTING voice-assistant interface. "
    "Improve the current look and feel of web/index.html, web/style.css, and "
    "web/app.js IN PLACE — refine the orb, colors, typography, layout, spacing, "
    "and animations. Do NOT turn Deimos into a website, landing page, or "
    "marketing/product site; do NOT add new pages, sections, or unrelated "
    "content; keep the existing element ids and the app.js wiring to the "
    "server working. Edit only those three web/ files; do not modify Python "
    "logic files. The user's request: "
)


def _is_visual_self_edit(instruction: str) -> bool:
    return bool(_VISUAL_RE.search(instruction or ""))


# Generic "glow-up" words. For a SELF edit, "make yourself better/nicer/cooler"
# almost always means "improve how you look", so bias these to the visual path.
_SELF_GLOWUP_RE = re.compile(
    r"\b(better|nicer|prettier|cooler|sleeker|slicker|cleaner|polish|fancy|"
    r"modern|moderni[sz]e|upgrade|glow.?up|spruce|revamp)\b",
    re.IGNORECASE,
)


def _wants_self_glowup(instruction: str) -> bool:
    return bool(_SELF_GLOWUP_RE.search(instruction or ""))


# Fallback note for NON-visual self-edits (e.g. "add a timer to yourself"): keep
# Claude Code editing Deimos's real files and never let a self-edit become a site.
SELF_NOTE = (
    "You are editing Deimos ITSELF — a local Python voice assistant (a FastAPI "
    "server plus a web/ frontend). Make the requested change to the appropriate "
    "existing files. Do NOT turn Deimos into a website, landing page, or "
    "marketing/product site, and do not scaffold a new project. The user's "
    "request: "
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
                        "You are a senior product designer and engineer. Turn the "
                        "user's request into a precise build spec that includes: "
                        "the subject, audience, and the page's single job; a "
                        "palette of 4–6 hex values; a deliberate display + body "
                        "type pairing; a distinctive layout concept; and ONE "
                        "signature element the page is remembered by. Explicitly "
                        "avoid generic AI-default looks (cream+serif+terracotta; "
                        "near-black+acid accent; broadsheet hairline). Specify "
                        "responsive behavior, accessibility (keyboard focus, "
                        "reduced motion), and real example copy (no lorem ipsum). "
                        "The finished site must live at index.html in the project "
                        "root. Output only the spec."
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
    found one and launched the opener.

    Projects under ~/deimos-projects are opened through the Deimos server
    (same-origin /preview URL) so the injected in-page editor's Save can write
    back; anything else falls back to opening the file directly.
    """
    index = cwd / "index.html"
    if not index.exists():
        return False
    projects_root = Path(CONFIG.projects_dir).expanduser().resolve()
    try:
        rel = cwd.resolve().relative_to(projects_root)
        url = f"http://localhost:8765/preview/{rel.as_posix()}/index.html"
    except ValueError:
        url = f"file://{index.resolve()}"
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    try:
        if Path(chrome).exists():
            subprocess.Popen(
                [chrome, f"--app={url}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen(
                ["open", url],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        return True
    except Exception:
        return False


_GITIGNORE = """\
# Dependencies / build output
node_modules/
dist/
build/
.cache/
__pycache__/
*.pyc

# Secrets — never commit these
.env
.env.*
*.key
*.pem
credentials.json
client_secret*.json
token.json

# OS cruft
.DS_Store
"""

# Patterns that look like real secrets; if present in tracked files we refuse to
# publish, so an auto-public push can never leak a key.
_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9]{20})|(ghp_[A-Za-z0-9]{20})|(gho_[A-Za-z0-9]{20})"
    r"|(AKIA[0-9A-Z]{16})|(xox[baprs]-)|(-----BEGIN (RSA |OPENSSH |)PRIVATE KEY-----)"
)


def _ensure_gitignore(cwd: Path) -> None:
    gi = cwd / ".gitignore"
    if not gi.exists():
        gi.write_text(_GITIGNORE)


def _has_secrets(cwd: Path) -> bool:
    """Scan files git would track for obvious secrets."""
    tracked = _git(cwd, "ls-files")
    for rel in tracked.stdout.splitlines():
        f = cwd / rel
        try:
            if f.stat().st_size > 2_000_000:
                continue
            if _SECRET_RE.search(f.read_text("utf-8", "ignore")):
                return True
        except Exception:
            continue
    return False


def _commit_message(instruction: str) -> str:
    msg = " ".join(instruction.split())[:60].strip()
    return msg or "Update project"


def _gh(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)


def _gh_owner() -> str | None:
    r = _gh("api", "user", "--jq", ".login", timeout=30)
    return r.stdout.strip() or None


def _enable_pages(owner: str, name: str) -> str | None:
    """Best-effort: enable GitHub Pages from the main branch root; return URL."""
    body = '{"source":{"branch":"main","path":"/"}}'
    try:
        subprocess.run(
            ["gh", "api", "--method", "POST", f"repos/{owner}/{name}/pages",
             "--input", "-"],
            input=body, capture_output=True, text=True, timeout=60,
        )
        # Whether it just got created or already existed, read back the URL.
        g = _gh("api", f"repos/{owner}/{name}/pages", "--jq", ".html_url", timeout=30)
        url = g.stdout.strip()
        return url or f"https://{owner.lower()}.github.io/{name}/"
    except Exception:
        return None


def _publish_project(cwd: Path, instruction: str) -> str:
    """Commit and publish a real project to a PUBLIC GitHub repo (+ Pages for
    sites). Best-effort: returns a short note for the spoken reply and never
    raises — a publish failure must not fail the build."""
    if not CONFIG.auto_publish:
        return ""
    # Guard: only publish things that live inside the projects dir.
    projects_root = Path(CONFIG.projects_dir).expanduser().resolve()
    try:
        cwd.resolve().relative_to(projects_root)
    except ValueError:
        return ""
    try:
        _ensure_gitignore(cwd)
        _git(cwd, "add", "-A")
        if _has_secrets(cwd):
            return " I didn't publish it — it looks like it contains secrets."
        _git(cwd, "commit", "-m", _commit_message(instruction), "--allow-empty")

        name = cwd.name
        has_remote = _git(cwd, "remote", "get-url", "origin").returncode == 0
        if not has_remote:
            r = _gh("repo", "create", name, "--public", "--source", str(cwd),
                    "--remote=origin", "--push")
            if r.returncode != 0:
                detail = (r.stderr or "").strip().splitlines()[-1:] or [""]
                return f" (Couldn't publish to GitHub: {detail[0][:80]})"
        else:
            p = _git(cwd, "push", "origin", "HEAD")
            if p.returncode != 0:
                return " (Couldn't push the latest changes to GitHub.)"

        owner = _gh_owner()
        note = ""
        if owner:
            note = f" Published to github.com/{owner}/{name}."
            if (cwd / "index.html").exists():
                pages = _enable_pages(owner, name)
                if pages:
                    note += f" Live at {pages}"
        return note
    except Exception as exc:
        return f" (Publish step skipped: {type(exc).__name__}.)"


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

    # Offer a rough ETA from past builds while this one runs.
    progress.set_estimate(memory.avg_build_seconds())

    snapshot = _snapshot(cwd)
    snap_note = f" Snapshot {snapshot[:8]} saved (undo: git -C {cwd} reset --hard {snapshot[:8]})." if snapshot else ""

    # Expand the request into a detailed spec with the coder model, then prepend
    # the standing quality preamble. Spec expansion falls back to the raw text.
    progress.set_phase("Understanding your request")
    # Self-edits NEVER go through the website-oriented spec expansion — it would
    # reframe Deimos as a brand-new website. Visual (or generic "make yourself
    # better") requests refine web/ in place; other self-edits get a scoped note
    # that keeps Claude Code in Deimos's real files. Only real external projects
    # get the full website/product spec expansion.
    if is_self:
        if _is_visual_self_edit(instruction) or _wants_self_glowup(instruction):
            spec = VISUAL_SELF_NOTE + instruction
        else:
            spec = SELF_NOTE + instruction
    else:
        spec = _expand_spec(instruction)
    full_instruction = QUALITY_PREAMBLE + spec

    progress.set_phase("Building with Claude Code")
    build_start = time.monotonic()
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

    # Record how long the build took, for future ETAs.
    memory.log_build(int(time.monotonic() - build_start), _commit_message(instruction))

    out = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    summary = out[-1200:] if out else (err[-600:] if err else "Done, no output returned.")
    target = "myself" if is_self else cwd.name

    # For real projects (not self-edits): remember it as the active project so
    # the user can iterate by voice, publish it, and open a built site.
    opened_note = ""
    publish_note = ""
    if not is_self:
        memory.set_active_project(str(cwd))
        progress.set_phase("Publishing to GitHub")
        publish_note = _publish_project(cwd, instruction)
        if _open_index(cwd):
            opened_note = " I opened it in a window so you can see it."

    return f"Ran your request on {target}.{snap_note}{publish_note}{opened_note}\n\n{summary}"
