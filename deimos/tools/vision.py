"""Screen sight: let Deimos see what's currently on the screen.

Captures the screen and asks a small local vision model about it, so requests
like "what's on my screen", "read this", or "what does this error say" work.
The vision model is loaded only when used and unloads quickly (keep_alive),
to stay light on RAM.
"""
import os
import subprocess
import tempfile

import ollama

from deimos.config import CONFIG
from deimos.tools.registry import registry


@registry.tool(
    name="see_screen",
    description=(
        "Look at what is currently on the user's screen and answer about it. "
        "Use for 'what's on my screen', 'read this', 'what does this say', "
        "'describe what you see', or any question about what's displayed."
    ),
    parameters={
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "What to find out about the screen. Optional.",
            }
        },
    },
)
def see_screen(question: str = "") -> str:
    q = (question or "").strip() or "Describe what is on the screen, concisely."
    png = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
    small = png.replace(".png", "_s.png")
    try:
        subprocess.run(["screencapture", "-x", png], capture_output=True, timeout=15)
        if not os.path.exists(png) or os.path.getsize(png) == 0:
            return "I couldn't capture the screen."
        # Downscale so a 5K Retina grab doesn't waste tokens / overwhelm a model.
        subprocess.run(["sips", "-Z", "1600", png, "--out", small],
                       capture_output=True, timeout=15)
        shot = small if os.path.exists(small) else png

        # Prefer Claude vision when configured — far better at reading screens.
        from deimos import cloud
        if cloud.is_configured():
            answer = cloud.describe_image(shot, q)
            if answer:
                return answer

        # Local fallback (small model — rough, but private and offline).
        client = ollama.Client(host=CONFIG.ollama_host)
        resp = client.chat(
            model=CONFIG.vision_model,
            messages=[{"role": "user", "content": q, "images": [shot]}],
            keep_alive=CONFIG.vision_keep_alive,
        )
        return (resp.message.content or "").strip() or "I couldn't make out the screen."
    except Exception as exc:
        return f"I couldn't read the screen ({type(exc).__name__})."
    finally:
        for f in (png, small):
            try:
                os.remove(f)
            except OSError:
                pass
