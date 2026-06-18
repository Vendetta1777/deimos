"""Local web server for the Jarvis app.

Serves the orb UI and exposes a WebSocket that drives it. The browser sends an
action ("listen", "pause", or a typed message); the server runs the existing
voice pipeline and pushes state updates (idle, listening, thinking, speaking)
and transcript lines back so the orb reacts in real time.

Clicking the orb while it is listening sends "pause", which signals the
in-progress recording to stop and drops Jarvis back to idle without
transcribing. To keep accepting that message while a recording is underway, the
pipeline runs as its own task and the receive loop stays free.

The blocking pieces (recording, transcription, the model, speech) run in worker
threads via asyncio.to_thread so the connection stays responsive. A lock keeps
requests from overlapping, since Jarvis handles one conversation at a time.

Run with:  python server.py    then open http://localhost:8765
"""
import asyncio
import threading
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from jarvis.audio.stt import SpeechToText
from jarvis.audio.tts import TextToSpeech
from jarvis.brain.llm import Brain
import jarvis.tools.builtin  # noqa: F401  registers the built-in tools
import jarvis.tools.memory_tools  # noqa: F401  registers remember/recall
import jarvis.tools.skills  # noqa: F401  registers web/weather/system/notes/etc.
import jarvis.tools.code_tools  # noqa: F401  registers run_claude_code

WEB_DIR = Path(__file__).parent / "web"

app = FastAPI()

stt = SpeechToText()
tts = TextToSpeech()
brain = Brain()
busy = asyncio.Lock()


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.websocket("/ws")
async def ws(socket: WebSocket) -> None:
    await socket.accept()

    stop_recording = threading.Event()

    async def state(name: str) -> None:
        await socket.send_json({"type": "state", "state": name})

    async def line(role: str, text: str) -> None:
        await socket.send_json({"type": "transcript", "role": role, "text": text})

    async def handle(action: str, text: str) -> None:
        async with busy:
            if action == "listen":
                stop_recording.clear()
                await state("listening")
                audio = await asyncio.to_thread(stt.record, stop_recording)
                if stop_recording.is_set():  # paused by the user, not by silence
                    await state("idle")
                    return
                await state("thinking")
                user_text = await asyncio.to_thread(stt.transcribe, audio)
            else:  # "text"
                user_text = text
                await state("thinking")

            if not user_text:
                await state("idle")
                return

            await line("you", user_text)
            reply = await asyncio.to_thread(brain.ask, user_text)
            await line("jarvis", reply)

            await state("speaking")
            await asyncio.to_thread(tts.speak, reply)
            await state("idle")

    try:
        await state("idle")
        while True:
            msg = await socket.receive_json()
            action = msg.get("action")

            # "pause" must work mid-recording, so handle it before the busy
            # check and signal the recording thread to stop.
            if action == "pause":
                stop_recording.set()
                continue

            if busy.locked():
                continue

            if action == "listen":
                asyncio.create_task(handle("listen", ""))
            elif action == "text":
                text = (msg.get("text") or "").strip()
                asyncio.create_task(handle("text", text))
            else:
                await state("idle")
    except WebSocketDisconnect:
        pass


app.mount("/", StaticFiles(directory=str(WEB_DIR)), name="static")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765)
