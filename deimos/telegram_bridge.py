"""Telegram bridge — talk to Deimos from your phone, anywhere.

Uses Telegram's long-polling (getUpdates), so it works from behind the user's
home/school network with NO public server, webhook, or port-forwarding. The
server's background loop pulls messages, runs them through the same Brain as
voice, and replies; proactive briefings/nudges are pushed here too.

Credentials live OUTSIDE source control, in ~/deimos/.telegram.json:
    {"token": "123456:ABC...", "allowed_chat_id": null}

Security: only ONE chat may command Deimos. If allowed_chat_id is null, the
first person to message it becomes the owner (trust-on-first-use) and is saved;
everyone else is refused. To lock it to a known chat up front, set the id.
"""
import json
import urllib.parse
import urllib.request
from pathlib import Path

# Reuse the certifi + macOS-keychain trust store (school network does TLS
# inspection), same as spotify.py.
from deimos.tools.skills import _SSL_CTX

_CREDS_PATH = Path("~/deimos/.telegram.json").expanduser()
_API = "https://api.telegram.org/bot{token}/{method}"


def _creds() -> dict:
    try:
        return json.loads(_CREDS_PATH.read_text("utf-8"))
    except Exception:
        return {}


def get_token() -> str | None:
    return _creds().get("token") or None


def is_configured() -> bool:
    return bool(get_token())


def _owner() -> str | None:
    cid = _creds().get("allowed_chat_id")
    return str(cid) if cid not in (None, "") else None


def _set_owner(chat_id) -> None:
    """Persist the owner chat id, preserving the rest of the file."""
    data = _creds()
    data["allowed_chat_id"] = chat_id
    try:
        _CREDS_PATH.write_text(json.dumps(data, indent=2), "utf-8")
    except Exception:
        pass


def authorize(chat_id) -> bool:
    """True if this chat may command Deimos. First messager claims ownership."""
    owner = _owner()
    if owner is None:
        _set_owner(chat_id)
        return True
    return str(chat_id) == owner


def get_updates(offset: int | None = None, long_poll: int = 50) -> list[dict]:
    token = get_token()
    if not token:
        return []
    params = {"timeout": long_poll, "allowed_updates": '["message"]'}
    if offset is not None:
        params["offset"] = offset
    url = _API.format(token=token, method="getUpdates") + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=long_poll + 15, context=_SSL_CTX) as r:
            return (json.load(r) or {}).get("result") or []
    except Exception:
        return []


def send_message(chat_id, text: str) -> bool:
    token = get_token()
    if not token or chat_id is None or not text:
        return False
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": text[:4000]}).encode()
    url = _API.format(token=token, method="sendMessage")
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, data=body), timeout=15, context=_SSL_CTX
        ) as r:
            return (json.load(r) or {}).get("ok", False)
    except Exception:
        return False


def push(text: str) -> bool:
    """Send an unprompted message (briefing/nudge) to the owner's phone."""
    owner = _owner()
    return send_message(owner, text) if owner else False
