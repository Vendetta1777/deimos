"""Claude API client for high-quality vision and reasoning.

Deimos stays local-first; this is the optional cloud brain used where a frontier
model is clearly better (reading a dense screen, hard reasoning). The API key is
read from ~/deimos/.anthropic.json (gitignored) or the ANTHROPIC_API_KEY env var.

HTTPS to api.anthropic.com is routed through the same trust store skills.py
builds (certifi + macOS keychain), so it verifies behind a TLS-inspecting
network. Falls back to a default client if a custom one can't be built.
"""
import base64
import json
import os
from pathlib import Path

from deimos.config import CONFIG
from deimos.tools.skills import _SSL_CTX  # certifi + macOS keychain roots

_KEY_PATH = Path("~/deimos/.anthropic.json").expanduser()
_client = None  # cached Anthropic client


def _api_key() -> str | None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    try:
        return json.loads(_KEY_PATH.read_text("utf-8")).get("api_key") or None
    except Exception:
        return None


def is_configured() -> bool:
    return bool(_api_key())


def _get_client():
    global _client
    if _client is not None:
        return _client
    key = _api_key()
    if not key:
        return None
    try:
        from anthropic import Anthropic, DefaultHttpxClient
        try:
            http = DefaultHttpxClient(verify=_SSL_CTX)
            _client = Anthropic(api_key=key, http_client=http)
        except Exception:
            _client = Anthropic(api_key=key)  # default TLS (may fail behind proxy)
    except Exception:
        _client = None
    return _client


def describe_image(image_path: str, question: str, media_type: str = "image/png") -> str | None:
    """Ask Claude about an image. Returns text, or None on any failure."""
    client = _get_client()
    if client is None:
        return None
    try:
        data = base64.standard_b64encode(Path(image_path).read_bytes()).decode("utf-8")
        resp = client.messages.create(
            model=CONFIG.cloud_model,
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": media_type, "data": data}},
                    {"type": "text", "text": question},
                ],
            }],
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        return text or None
    except Exception:
        return None
