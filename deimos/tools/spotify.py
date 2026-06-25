"""Spotify control: search the catalog via the Web API, play via the desktop app.

We use the simple client-credentials flow (just a Client ID + Secret, no user
login, no Premium) to turn a name like "Bohemian Rhapsody" into a Spotify URI,
then tell the local Spotify desktop app to play it with AppleScript.

Credentials live OUTSIDE source control, in ~/deimos/.spotify.json:
    {"client_id": "...", "client_secret": "..."}

Catalog search covers tracks, artists, albums, and PUBLIC playlists. Private
playlists need user login (a later upgrade).
"""
import base64
import json
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

# Reuse the trust store skills.py builds (certifi + macOS keychain) so HTTPS
# verifies even behind a TLS-inspecting network.
from deimos.tools.skills import _SSL_CTX

_CREDS_PATH = Path("~/deimos/.spotify.json").expanduser()
_token: dict = {"value": None, "expires": 0.0}


def _creds() -> tuple[str, str] | None:
    try:
        data = json.loads(_CREDS_PATH.read_text("utf-8"))
        cid, secret = data.get("client_id"), data.get("client_secret")
        if cid and secret:
            return cid, secret
    except Exception:
        pass
    return None


def is_configured() -> bool:
    return _creds() is not None


def _get_token() -> str | None:
    if _token["value"] and time.time() < _token["expires"]:
        return _token["value"]
    creds = _creds()
    if not creds:
        return None
    cid, secret = creds
    auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=body,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as r:
            j = json.load(r)
    except Exception:
        return None
    tok = j.get("access_token")
    if tok:
        _token["value"] = tok
        _token["expires"] = time.time() + j.get("expires_in", 3600) - 60
    return tok


_KIND_TO_TYPE = {
    "song": "track", "track": "track", "tune": "track",
    "artist": "artist", "album": "album", "playlist": "playlist",
}


def _search(query: str, qtype: str) -> tuple[str, str, str] | None:
    """Return (uri, name, who) for the top match, or None."""
    token = _get_token()
    if not token:
        return None
    url = (
        "https://api.spotify.com/v1/search?"
        + urllib.parse.urlencode({"q": query, "type": qtype, "limit": 1})
    )
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as r:
            j = json.load(r)
    except Exception:
        return None
    items = (j.get(qtype + "s") or {}).get("items") or []
    if not items:
        return None
    it = items[0]
    name = it.get("name", query)
    if qtype in ("track", "album"):
        who = ", ".join(a.get("name", "") for a in it.get("artists", []))
    elif qtype == "playlist":
        who = (it.get("owner") or {}).get("display_name", "")
    else:
        who = ""
    return it.get("uri"), name, who


def _play_uri(uri: str) -> bool:
    script = f'tell application "Spotify"\n  activate\n  play track "{uri}"\nend tell'
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=20, check=False,
        )
        return r.returncode == 0
    except Exception:
        return False


def play(query: str, kind: str = "song") -> str | None:
    """Search Spotify and play the top match on the desktop app.

    Returns a short spoken confirmation, or None if it couldn't (so the caller
    can fall back to another player).
    """
    qtype = _KIND_TO_TYPE.get((kind or "song").lower(), "track")
    hit = _search(query, qtype)
    if not hit:
        return None
    uri, name, who = hit
    if not _play_uri(uri):
        return None
    if who and qtype in ("track", "album"):
        return f"Playing {name} by {who} on Spotify."
    if qtype == "playlist":
        return f"Playing the {name} playlist on Spotify."
    return f"Playing {name} on Spotify."
