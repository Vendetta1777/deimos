"""Mac control tools: open URLs, media, volume, and an arbitrary shell command.

This is the "do anything on the computer" layer. The everyday, clearly-safe
actions (open a URL, set volume, control playback) run directly. The catch-all
`run_command` runs an arbitrary shell command through a login shell — but first
classifies it, and if it looks destructive or system-level, asks the user to
approve it in a NATIVE confirmation dialog before running. When in doubt, it
treats a command as dangerous and asks.

Design rules (shared with the other tool modules):
  - Every subprocess call has a timeout and never raises into the tool loop.
  - Tools return short, speakable strings — this is a voice assistant.
"""
import re
import subprocess

from deimos.tools.registry import registry


def _run(cmd: list[str], timeout: float = 15.0) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


# --------------------------------------------------------------------------- #
# Simple, always-safe controls
# --------------------------------------------------------------------------- #
@registry.tool(
    name="open_url",
    description="Open a website in the default browser.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL or domain to open."}
        },
        "required": ["url"],
    },
)
def open_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return "No URL was given."
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        _run(["open", url])
    except Exception as exc:
        return f"Couldn't open that ({exc})."
    return f"Opened {url}."


@registry.tool(
    name="set_volume",
    description="Set the Mac's output volume, 0 (mute) to 100 (max).",
    parameters={
        "type": "object",
        "properties": {
            "level": {"type": "integer", "description": "Volume 0-100."}
        },
        "required": ["level"],
    },
)
def set_volume(level: int) -> str:
    try:
        level = int(level)
    except (TypeError, ValueError):
        return "Give me a volume between 0 and 100."
    level = max(0, min(100, level))
    try:
        _run(["osascript", "-e", f"set volume output volume {level}"])
    except Exception as exc:
        return f"Couldn't set the volume ({exc})."
    return f"Volume set to {level}."


@registry.tool(
    name="media_control",
    description=(
        "Control music playback: play, pause, next, or previous. Targets "
        "Spotify if it's running, otherwise the Music app."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "One of: play, pause, next, previous.",
            }
        },
        "required": ["action"],
    },
)
def media_control(action: str) -> str:
    action = (action or "").strip().lower()
    verbs = {
        "play": "play",
        "pause": "pause",
        "playpause": "playpause",
        "toggle": "playpause",
        "next": "next track",
        "skip": "next track",
        "previous": "previous track",
        "prev": "previous track",
        "back": "previous track",
    }
    if action not in verbs:
        return "I can play, pause, skip to next, or go to previous."
    cmd = verbs[action]

    # Prefer whichever player is already running; Spotify first, else Music.
    script = f'''
    tell application "System Events"
        set hasSpotify to (exists (processes where name is "Spotify"))
        set hasMusic to (exists (processes where name is "Music"))
    end tell
    if hasSpotify then
        tell application "Spotify" to {cmd}
        return "Spotify"
    else if hasMusic then
        tell application "Music" to {cmd}
        return "Music"
    else
        return "none"
    end if
    '''
    try:
        result = _run(["osascript", "-e", script])
    except Exception as exc:
        return f"Couldn't control playback ({exc})."
    app = (result.stdout or "").strip()
    if app == "none":
        return "Neither Spotify nor Music is running."
    if result.returncode != 0:
        return f"Couldn't control playback ({(result.stderr or '').strip()[:80]})."
    pretty = {
        "play": "Playing",
        "pause": "Paused",
        "playpause": "Toggled playback on",
        "next track": "Skipped ahead on",
        "previous track": "Went back on",
    }.get(cmd, "Did that on")
    return f"{pretty} {app}."


def _osa_escape(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace('"', '\\"')


@registry.tool(
    name="play_music",
    description=(
        "Play a specific song, artist, album, or playlist by name. Use for "
        "requests like 'play <song>', 'play <artist>', 'play my <name> "
        "playlist'. Plays from the Apple Music library; if it isn't there, "
        "opens a search. For plain play/pause/skip use media_control instead."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The song, artist, album, or playlist name.",
            },
            "kind": {
                "type": "string",
                "description": "One of: song, artist, album, playlist. Default song.",
            },
        },
        "required": ["query"],
    },
)
def play_music(query: str, kind: str = "song") -> str:
    query = (query or "").strip()
    if not query:
        return "What would you like me to play?"

    # If Spotify is set up (credentials present), search + play it for real.
    # Falls through to Apple Music on any failure.
    from deimos.tools import spotify
    if spotify.is_configured():
        played = spotify.play(query, kind)
        if played:
            return played

    q = _osa_escape(query)
    kind = (kind or "song").strip().lower()
    if kind in ("track", "tune"):
        kind = "song"

    # Build the Apple Music search/play body for the requested kind.
    if kind == "playlist":
        find = (
            f'if (exists playlist "{q}") then\n'
            f'  play playlist "{q}"\n'
            f'  return "Playing your " & "{q}" & " playlist"\n'
            f'else\n'
            f'  set pls to (every playlist whose name contains "{q}")\n'
            f'  if pls is {{}} then return "notfound"\n'
            f'  play (item 1 of pls)\n'
            f'  return "Playing the " & (name of item 1 of pls) & " playlist"\n'
            f'end if'
        )
    else:
        field = {"artist": "artist", "album": "album"}.get(kind, "name")
        find = (
            f'set matches to (every track whose {field} contains "{q}")\n'
            f'if matches is {{}} then return "notfound"\n'
            f'play (item 1 of matches)\n'
            f'return "Playing " & (name of item 1 of matches) & " by " & '
            f'(artist of item 1 of matches)'
        )

    script = f'tell application "Music"\n  launch\n  {find}\nend tell'
    try:
        result = _run(["osascript", "-e", script], timeout=20)
    except Exception as exc:
        return f"Couldn't reach Apple Music ({exc})."

    out = (result.stdout or "").strip()
    if result.returncode == 0 and out and out != "notfound":
        return out + "."

    # Not in the Apple Music library: fall back to opening a search.
    import urllib.parse
    term = urllib.parse.quote(query)
    try:
        if subprocess.run(["test", "-d", "/Applications/Spotify.app"]).returncode == 0:
            _run(["open", f"spotify:search:{term}"])
            return f"I couldn't find '{query}' in your Apple Music library, so I opened a Spotify search — say play to start it."
        _run(["open", f"https://music.apple.com/search?term={term}"])
        return f"I couldn't find '{query}' in your library, so I opened an Apple Music search."
    except Exception:
        return f"I couldn't find '{query}' to play."


# --------------------------------------------------------------------------- #
# The catch-all: arbitrary shell command, gated on danger
# --------------------------------------------------------------------------- #

# Program names that are destructive/system-level as the command of any segment.
_DANGER_CMDS = {
    "rm", "rmdir", "unlink", "srm", "shred", "dd", "mkfs", "newfs", "fdisk",
    "sudo", "su", "shutdown", "reboot", "halt", "pmset", "systemsetup",
    "kill", "killall", "pkill", "launchctl", "networksetup", "scutil",
    "nvram", "csrutil", "chflags",
}

# System locations we never let mv/cp/chmod/chown/ln or > redirection touch.
_SYS_PATHS = r"(?:/system|/usr|/bin|/sbin|/etc|/library|/private)"


def _is_dangerous(command: str) -> bool:
    """True if a command looks destructive or system-level. Errs toward True."""
    if not command or not command.strip():
        return False
    c = command.lower()

    # diskutil is only dangerous for destructive subcommands.
    if re.search(r"\bdiskutil\b.*\b(erase|reformat|partition)", c):
        return True
    # Mutating system/app preferences.
    if re.search(r"\bdefaults\s+write\b", c):
        return True
    # Piping a download straight into a shell (classic remote-exec footgun).
    if re.search(r"\b(curl|wget)\b.*\|\s*(?:sudo\s+)?(?:sh|bash|zsh)\b", c):
        return True
    # mv/cp/chmod/chown/ln touching a protected system path.
    if re.search(rf"\b(?:mv|cp|chmod|chown|ln)\b[^;|&]*{_SYS_PATHS}(?:/|\b)", c):
        return True
    # Output redirection into a system path or a device node.
    if re.search(rf">>?\s*(?:{_SYS_PATHS}|/dev)\b", c):
        return True

    # Inspect the first token (the program) of every command segment, splitting
    # on ; && || | & newlines and command-substitution boundaries $() and ``.
    segments = re.split(r"&&|\|\||[;|&\n]|\$\(|\)|`", c)
    for seg in segments:
        tokens = seg.split()
        # Skip leading VAR=value env assignments to reach the real program.
        i = 0
        while i < len(tokens) and re.match(r"^[a-z_][a-z0-9_]*=", tokens[i]):
            i += 1
        if i >= len(tokens):
            continue
        prog = tokens[i].rsplit("/", 1)[-1]  # basename, so /bin/rm -> rm
        if prog in _DANGER_CMDS or prog.startswith(("mkfs", "newfs")):
            return True

    return False


def _confirm(command: str) -> bool:
    """Show a native Allow/Cancel dialog. True only if the user clicks Allow."""
    safe = command.replace("\\", "\\\\").replace('"', '\\"')
    dialog = (
        'display dialog "Deimos wants to run:\\n\\n' + safe + '" '
        'buttons {"Cancel", "Allow"} default button "Cancel" '
        "with icon caution giving up after 45"
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", dialog],
            capture_output=True, text=True, timeout=60, check=False,
        )
    except Exception:
        return False  # if the dialog can't run, treat as "not approved"
    return result.returncode == 0 and "Allow" in result.stdout


@registry.tool(
    name="run_command",
    description=(
        "Run a shell command on this Mac to do anything not covered by another "
        "tool — list/inspect files, launch things, query the system, automate "
        "tasks. Destructive or system-level commands prompt the user to confirm "
        "first; still call this for them."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to run.",
            }
        },
        "required": ["command"],
    },
)
def run_command(command: str) -> str:
    if not command or not command.strip():
        return "No command was given."

    if _is_dangerous(command) and not _confirm(command):
        return "Cancelled — that command wasn't approved."

    try:
        result = subprocess.run(
            ["/bin/zsh", "-lc", command],
            capture_output=True, text=True, timeout=120, check=False,
        )
    except subprocess.TimeoutExpired:
        return "That command took too long and was stopped."
    except Exception as exc:
        return f"Couldn't run that command ({exc})."

    out = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    body = out or err or f"Done (exit {result.returncode}, no output)."
    if len(body) > 1000:
        body = body[:1000] + "…"
    return body
