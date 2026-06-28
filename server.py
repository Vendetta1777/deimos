"""Local web server for the Deimos app.

Serves the orb UI and exposes a WebSocket that drives it. The browser sends an
action ("listen", "pause", or a typed message); the server runs the existing
voice pipeline and pushes state updates (idle, listening, thinking, speaking)
and transcript lines back so the orb reacts in real time.

Clicking the orb while it is listening sends "pause", which signals the
in-progress recording to stop and drops Deimos back to idle without
transcribing. To keep accepting that message while a recording is underway, the
pipeline runs as its own task and the receive loop stays free.

The blocking pieces (recording, transcription, the model, speech) run in worker
threads via asyncio.to_thread so the connection stays responsive. A lock keeps
requests from overlapping, since Deimos handles one conversation at a time.

Run with:  python server.py    then open http://localhost:8765
"""
import asyncio
import datetime
import re
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from deimos.audio.stt import SpeechToText
from deimos.audio.tts import TextToSpeech
from deimos.brain.llm import Brain
from deimos.config import CONFIG
from deimos.memory import memory
from deimos.progress import progress
from deimos.proactive import compose_briefing
from deimos.tools import personal
from deimos import telegram_bridge
from deimos import watchers
from deimos import wakeword
import deimos.tools.builtin  # noqa: F401  registers the built-in tools
import deimos.tools.memory_tools  # noqa: F401  registers remember/recall
import deimos.tools.skills  # noqa: F401  registers web/weather/system/notes/etc.
import deimos.tools.system_tools  # noqa: F401  registers open_url/media/volume/run_command
import deimos.tools.vision  # noqa: F401  registers see_screen
import deimos.tools.personal  # noqa: F401  registers reminders/calendar/messages
import deimos.tools.mac_control  # noqa: F401  registers mac_control
import deimos.tools.routines  # noqa: F401  registers run_routine
import deimos.tools.files  # noqa: F401  registers find_file/summarize_doc
import deimos.tools.code_tools  # noqa: F401  registers run_claude_code

WEB_DIR = Path(__file__).parent / "web"
PROJECTS_ROOT = Path("~/deimos-projects").expanduser()

@asynccontextmanager
async def _lifespan(app: "FastAPI"):
    # Start the proactive scheduler (morning briefing, event nudges) for the life
    # of the server; cancel it cleanly on shutdown.
    tasks = [asyncio.create_task(_watcher_loop())]
    if CONFIG.proactive_enabled:
        tasks.append(asyncio.create_task(_proactive_loop()))
    if CONFIG.telegram_enabled and telegram_bridge.is_configured():
        tasks.append(asyncio.create_task(_telegram_loop()))
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()


app = FastAPI(lifespan=_lifespan)


@app.middleware("http")
async def _no_cache(request: Request, call_next):
    """Stop the webview from serving stale HTML/CSS/JS after a UI change, so a
    plain reload always shows the latest."""
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-store, must-revalidate"
    return resp


stt = SpeechToText()
tts = TextToSpeech()
brain = Brain()
busy = asyncio.Lock()

# Wake-word state. The listener is created lazily on the first WebSocket
# connection (so we have the running loop) and only if a Picovoice key exists.
_loop = None
_trigger = None  # fn that starts a "listen" turn on the active connection
_wake = None


def _ensure_wakeword() -> None:
    global _loop, _wake
    if _wake is not None or not wakeword.is_configured():
        return
    _loop = asyncio.get_running_loop()

    def on_wake() -> None:
        # Detected in the wake thread (which paused itself); hop to the loop and
        # start a turn if there's a connection and nothing already running.
        # Otherwise resume the listener so it doesn't get stuck paused.
        if _trigger is not None and not busy.locked():
            _loop.call_soon_threadsafe(_trigger)
        elif _wake is not None:
            _wake.resume()

    _wake = wakeword.WakeWord(on_wake)
    _wake.start()


@asynccontextmanager
async def _wake_paused():
    """Release the wake-word mic for the duration of a turn, then resume."""
    if _wake is not None:
        _wake.pause()
    try:
        yield
    finally:
        if _wake is not None:
            _wake.resume()


# --------------------------------------------------------------------------- #
# Proactivity: Deimos speaks up on its own (morning briefing, event nudges).
# The audio plays through the Mac's speakers via TTS; if the orb UI is open we
# also reflect it there. Unprompted speech always yields to an active turn.
# --------------------------------------------------------------------------- #
_ui_state_fn = None   # set to the live connection's state() while one is open
_ui_line_fn = None    # …and its line()
_cal = {"poll": None, "events": []}  # throttled cache of today's events


async def speak_now(text: str) -> bool:
    """Speak an unprompted line, but only if nothing else is talking/listening.
    Returns True if it actually spoke (so callers can mark it done)."""
    if not text or busy.locked():
        return False
    async with busy, _wake_paused():
        if _ui_line_fn is not None:
            await _ui_line_fn("deimos", text)
        if _ui_state_fn is not None:
            await _ui_state_fn("speaking")
        await asyncio.to_thread(tts.speak, text)
        if _ui_state_fn is not None:
            await _ui_state_fn("idle")
    # Mirror the briefing/nudge to the owner's phone so it reaches them when
    # they're away from the Mac.
    if CONFIG.telegram_enabled and telegram_bridge.is_configured():
        await asyncio.to_thread(telegram_bridge.push, text)
    return True


async def run_voice_turn() -> None:
    """One complete voice turn (listen → think → speak) that does NOT depend on
    a UI connection — this is what the push-to-talk hotkey (POST /talk) calls.
    Records from the mic, transcribes, answers, and speaks aloud; reflects in the
    orb if it's open. Yields if something is already talking/listening."""
    if busy.locked():
        return
    async with busy, _wake_paused():
        stop = threading.Event()
        if _ui_state_fn is not None:
            await _ui_state_fn("listening")
        audio = await asyncio.to_thread(stt.record, stop)
        if _ui_state_fn is not None:
            await _ui_state_fn("thinking")
        text = (await asyncio.to_thread(stt.transcribe, audio) or "").strip()
        if not text:
            if _ui_state_fn is not None:
                await _ui_state_fn("idle")
            return
        if _ui_line_fn is not None:
            await _ui_line_fn("you", text)
        reply = await asyncio.to_thread(brain.ask, text)
        if _ui_line_fn is not None:
            await _ui_line_fn("deimos", reply)
        if _ui_state_fn is not None:
            await _ui_state_fn("speaking")
        await asyncio.to_thread(tts.speak, reply)
        if _ui_state_fn is not None:
            await _ui_state_fn("idle")


async def _maybe_briefing(now: datetime.datetime) -> None:
    if not CONFIG.briefing_enabled:
        return
    try:
        bh, bm = (int(x) for x in CONFIG.briefing_time.split(":"))
    except Exception:
        return
    target = now.replace(hour=bh, minute=bm, second=0, microsecond=0)
    # Fire once, in a 30-min window after the target (covers a sleeping Mac that
    # wakes a little late), and never twice in a day.
    if not (target <= now < target + datetime.timedelta(minutes=30)):
        return
    if memory.get_state("last_briefing_date") == now.date().isoformat():
        return
    text = await asyncio.to_thread(compose_briefing)
    if await speak_now(text):
        memory.set_state("last_briefing_date", now.date().isoformat())


async def _maybe_event_nudge(now: datetime.datetime, announced: set) -> None:
    lead = CONFIG.event_nudge_lead_min
    if lead <= 0:
        return
    # The calendar read is slow, so refresh at most every 5 minutes.
    if _cal["poll"] is None or (now - _cal["poll"]).total_seconds() >= 300:
        _cal["events"] = await asyncio.to_thread(personal.todays_events_struct)
        _cal["poll"] = now
    for start, title in _cal["events"]:
        key = f"{start.isoformat()}|{title}"
        if key in announced:
            continue
        mins = (start - now).total_seconds() / 60.0
        if 0 < mins <= lead:
            m = round(mins)
            msg = f"Heads up — {title} starts in about {m} minute{'s' if m != 1 else ''}."
            if await speak_now(msg):
                announced.add(key)


async def _handle_telegram(update: dict) -> None:
    msg = update.get("message") or {}
    text = (msg.get("text") or "").strip()
    chat = (msg.get("chat") or {}).get("id")
    if not text or chat is None:
        return
    if not telegram_bridge.authorize(chat):
        await asyncio.to_thread(
            telegram_bridge.send_message, chat,
            "Sorry — I only answer to my owner.",
        )
        return
    # Share the Brain with voice, and serialise on the same lock so the two
    # never run the model concurrently or scramble history.
    async with busy:
        if _ui_line_fn is not None:
            await _ui_line_fn("you", text)
        reply = await asyncio.to_thread(brain.ask, text)
        if _ui_line_fn is not None:
            await _ui_line_fn("deimos", reply)
    await asyncio.to_thread(telegram_bridge.send_message, chat, reply)


async def _telegram_loop() -> None:
    """Long-poll Telegram and answer messages from the owner's phone."""
    # Drain any backlog first so stale commands (sent while the server was down)
    # don't execute on startup — advance the offset past them without handling.
    offset = None
    try:
        backlog = await asyncio.to_thread(telegram_bridge.get_updates, None, 0)
        if backlog:
            offset = backlog[-1]["update_id"] + 1
    except Exception:
        pass
    while True:
        try:
            updates = await asyncio.to_thread(telegram_bridge.get_updates, offset, 50)
        except Exception:
            await asyncio.sleep(5)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            try:
                await _handle_telegram(u)
            except Exception:
                pass


async def _watcher_loop() -> None:
    """Poll background watchers and announce any that fire. Held-back messages
    (spoken while busy) are retried on the next tick instead of being lost."""
    pending: list = []
    while True:
        await asyncio.sleep(CONFIG.watcher_tick_seconds)
        try:
            pending.extend(watchers.manager.poll())
        except Exception:
            pass
        while pending:
            if await speak_now(pending[0]):
                pending.pop(0)
            else:
                break  # something's talking; retry next tick


async def _proactive_loop() -> None:
    """Background scheduler for all unprompted speech."""
    announced: set = set()
    day = None
    while True:
        await asyncio.sleep(CONFIG.proactive_tick_seconds)
        if not CONFIG.proactive_enabled:
            continue
        now = datetime.datetime.now()
        if not (CONFIG.proactive_quiet_before <= now.hour < CONFIG.proactive_quiet_after):
            continue
        if day != now.date():        # new day → forget yesterday's nudges
            announced.clear()
            day = now.date()
        try:
            await _maybe_briefing(now)
            await _maybe_event_nudge(now, announced)
        except Exception:
            pass




@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/mini")
async def mini() -> FileResponse:
    return FileResponse(WEB_DIR / "mini.html")


@app.post("/talk")
async def talk() -> JSONResponse:
    """Push-to-talk trigger: start a voice turn now. Bind a global keyboard
    shortcut to `curl -X POST http://localhost:8765/talk` (e.g. via the macOS
    Shortcuts app) to talk to Deimos from anywhere. Fire-and-forget so the key
    returns instantly."""
    asyncio.create_task(run_voice_turn())
    return JSONResponse({"ok": True})


@app.websocket("/ws")
async def ws(socket: WebSocket) -> None:
    await socket.accept()

    stop_recording = threading.Event()
    current: "asyncio.Task | None" = None  # the in-flight turn, so we can cancel it

    async def state(name: str) -> None:
        try:
            await socket.send_json({"type": "state", "state": name})
        except Exception:
            pass  # socket closed mid-turn; nothing to send to

    async def line(role: str, text: str) -> None:
        try:
            await socket.send_json({"type": "transcript", "role": role, "text": text})
        except Exception:
            pass

    async def push_progress() -> None:
        # Stream live progress (phase + elapsed) while a turn runs in a worker
        # thread, so the UI isn't frozen on "thinking" during builds.
        try:
            while True:
                phase, elapsed = progress.snapshot()
                try:
                    await socket.send_json({
                        "type": "progress",
                        "phase": phase or "Thinking",
                        "elapsed": elapsed,
                        "estimate": progress.estimate,
                    })
                except Exception:
                    return  # socket closed
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    async def handle(action: str, text: str) -> None:
        async with busy, _wake_paused():
            # First user input for this exchange.
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

            # Voice turns can continue hands-free: after each spoken reply we
            # reopen the mic for a brief follow-up window. Silence ends it.
            voice = action == "listen"
            for _ in range(40):  # safety cap on consecutive auto follow-ups
                if not user_text:
                    await state("idle")
                    return

                await line("you", user_text)

                progress.start()
                prog_task = asyncio.create_task(push_progress())
                try:
                    reply = await asyncio.to_thread(brain.ask, user_text)
                finally:
                    prog_task.cancel()
                    progress.stop()

                await line("deimos", reply)

                await state("speaking")
                await asyncio.to_thread(tts.speak, reply)
                await state("idle")

                if not (voice and CONFIG.conversation_mode):
                    return

                # Hands-free follow-up: reopen the mic; quiet = end conversation.
                stop_recording.clear()
                await state("listening")
                audio = await asyncio.to_thread(
                    stt.record, stop_recording, CONFIG.conversation_followup_timeout
                )
                if stop_recording.is_set():
                    await state("idle")
                    return
                await state("thinking")
                user_text = await asyncio.to_thread(stt.transcribe, audio)

            await state("idle")

    def launch(action: str, text: str = "") -> None:
        nonlocal current
        current = asyncio.create_task(handle(action, text))

    # Let the wake word start a turn on this connection ("Hey Deimos").
    global _trigger, _ui_state_fn, _ui_line_fn
    _trigger = lambda: launch("listen", "")
    # Let proactive speech reflect in this connection's orb UI.
    _ui_state_fn, _ui_line_fn = state, line
    _ensure_wakeword()

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
                launch("listen", "")
            elif action == "text":
                launch("text", (msg.get("text") or "").strip())
            else:
                await state("idle")
    except WebSocketDisconnect:
        pass
    finally:
        _trigger = None  # this connection is gone; wake has nowhere to fire
        _ui_state_fn = _ui_line_fn = None  # no UI to reflect proactive speech in
        # The browser closed mid-turn: stop any in-flight recording and cancel the
        # turn task, so it can't keep holding the global busy lock or the mic and
        # wedge the next connection's tap-to-talk. Resume the wake listener too.
        stop_recording.set()
        if current is not None and not current.done():
            current.cancel()
        if _wake is not None:
            _wake.resume()


# --------------------------------------------------------------------------- #
# Live "edit on the page" layer for built projects.
#
# Built sites are served same-origin through /preview/{project}/... so the
# injected editor can POST edits back to /save/{project}. The <base> tag and the
# editor markup are added to the RESPONSE ONLY — never written to disk.
# --------------------------------------------------------------------------- #
_BASE_TAG = '<base id="__deimos_base__" href="/preview/__PROJECT__/">'

_EDITOR_TEMPLATE = """
<style id="__deimos_editor_style__">
#__deimos_editor__{position:fixed;top:12px;right:12px;z-index:2147483647;display:flex;gap:8px;align-items:center;
  background:rgba(11,15,26,.94);color:#d6ecf7;font:13px/1.2 system-ui,-apple-system,sans-serif;
  padding:8px 10px;border:1px solid #2a3a4f;border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.55);}
#__deimos_editor__ button{cursor:pointer;background:#1b2740;color:#d6ecf7;border:1px solid #34507a;border-radius:6px;padding:5px 10px;font:inherit;}
#__deimos_editor__ button:hover{background:#243456;}
#__deimos_editor__ label{display:flex;align-items:center;gap:4px;opacity:.85;}
#__deimos_editor__ input[type=color]{width:26px;height:22px;border:none;background:none;padding:0;cursor:pointer;}
#__deimos_editor__ #__de_status{opacity:.7;min-width:52px;}
.__deimos_sel__{outline:2px dashed #5fd0e6 !important;outline-offset:2px;}
</style>
<div id="__deimos_editor__">
  <button id="__de_edit" type="button">Edit</button>
  <label>Text <input type="color" id="__de_fg" value="#000000"></label>
  <label>BG <input type="color" id="__de_bg" value="#ffffff"></label>
  <button id="__de_save" type="button">Save</button>
  <span id="__de_status"></span>
</div>
<script id="__deimos_editor_script__">
(function(){
  var PROJECT="__PROJECT__";
  var TEXT="h1,h2,h3,h4,h5,h6,p,span,a,li,button,blockquote,figcaption,label,td,th,strong,em,small,div";
  var editing=false, sel=null;
  function texts(fn){document.querySelectorAll(TEXT).forEach(function(el){if(el.closest('#__deimos_editor__'))return;fn(el);});}
  function rgb2hex(c){var m=(c||'').match(/\\d+/g);if(!m)return '#000000';return '#'+m.slice(0,3).map(function(x){return ('0'+parseInt(x).toString(16)).slice(-2);}).join('');}
  document.getElementById('__de_edit').addEventListener('click',function(){
    editing=!editing; this.textContent=editing?'Editing…':'Edit';
    texts(function(el){if(editing){el.setAttribute('contenteditable','true');}else{el.removeAttribute('contenteditable');}});
  });
  document.addEventListener('click',function(e){
    if(!editing)return; if(e.target.closest('#__deimos_editor__'))return;
    if(sel)sel.classList.remove('__deimos_sel__'); sel=e.target; sel.classList.add('__deimos_sel__');
    try{document.getElementById('__de_fg').value=rgb2hex(getComputedStyle(sel).color);}catch(_){}
  },true);
  document.getElementById('__de_fg').addEventListener('input',function(){if(sel)sel.style.color=this.value;});
  document.getElementById('__de_bg').addEventListener('input',function(){if(sel)sel.style.backgroundColor=this.value;});
  document.getElementById('__de_save').addEventListener('click',function(){
    var st=document.getElementById('__de_status'); st.textContent='Saving…';
    if(sel)sel.classList.remove('__deimos_sel__');
    var clone=document.documentElement.cloneNode(true);
    ['__deimos_editor__','__deimos_editor_style__','__deimos_editor_script__','__deimos_base__'].forEach(function(id){
      var n=clone.querySelector('#'+id); if(n)n.remove();
    });
    clone.querySelectorAll('[contenteditable]').forEach(function(el){el.removeAttribute('contenteditable');});
    clone.querySelectorAll('.__deimos_sel__').forEach(function(el){el.classList.remove('__deimos_sel__');});
    clone.querySelectorAll('[class=""]').forEach(function(el){el.removeAttribute('class');});
    var html='<!DOCTYPE html>\\n'+clone.outerHTML;
    fetch('/save/'+PROJECT,{method:'POST',headers:{'Content-Type':'text/html'},body:html})
      .then(function(r){return r.json();})
      .then(function(d){st.textContent=d.ok?'Saved \\u2713':'Error';})
      .catch(function(){st.textContent='Error';});
  });
})();
</script>
"""


def _inject_editor(html: str, project: str) -> str:
    base = _BASE_TAG.replace("__PROJECT__", project)
    editor = _EDITOR_TEMPLATE.replace("__PROJECT__", project)
    if re.search(r"<head[^>]*>", html, re.I):
        html = re.sub(r"<head[^>]*>", lambda m: m.group(0) + base, html, count=1, flags=re.I)
    elif re.search(r"<html[^>]*>", html, re.I):
        html = re.sub(r"<html[^>]*>", lambda m: m.group(0) + "<head>" + base + "</head>", html, count=1, flags=re.I)
    else:
        html = base + html
    if re.search(r"</body>", html, re.I):
        html = re.sub(r"</body>", lambda m: editor + "</body>", html, count=1, flags=re.I)
    else:
        html = html + editor
    return html


def _project_dir(project: str) -> Path | None:
    """Resolve a safe project directory under PROJECTS_ROOT, or None."""
    if not project or "/" in project or "\\" in project or ".." in project:
        return None
    base = (PROJECTS_ROOT / project).resolve()
    try:
        base.relative_to(PROJECTS_ROOT.resolve())
    except ValueError:
        return None
    return base if base.is_dir() else None


@app.get("/preview/{project}/{path:path}")
async def preview(project: str, path: str = "") -> Response:
    base = _project_dir(project)
    if base is None or ".." in path:
        return Response(status_code=404)
    target = (base / (path or "index.html")).resolve()
    try:
        target.relative_to(base)  # block path traversal out of the project
    except ValueError:
        return Response(status_code=403)
    if not target.is_file():
        return Response(status_code=404)
    if target.name == "index.html":
        return HTMLResponse(_inject_editor(target.read_text("utf-8", "replace"), project))
    return FileResponse(str(target))


@app.post("/save/{project}")
async def save(project: str, request: Request) -> Response:
    base = _project_dir(project)
    if base is None:
        return JSONResponse({"ok": False, "error": "unknown project"}, status_code=404)
    html = (await request.body()).decode("utf-8", "replace")
    # Commit the CURRENT (pre-edit) state first, so every save is undoable.
    if not (base / ".git").exists():
        subprocess.run(["git", "-C", str(base), "init"], capture_output=True)
    git = ["git", "-C", str(base), "-c", "user.name=Deimos", "-c", "user.email=deimos@local"]
    subprocess.run(["git", "-C", str(base), "add", "-A"], capture_output=True)
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    subprocess.run(git + ["commit", "-m", f"live edit {ts}", "--allow-empty"], capture_output=True)
    (base / "index.html").write_text(html, encoding="utf-8")
    return JSONResponse({"ok": True, "note": f"Saved {project}/index.html and snapshotted."})


# --------------------------------------------------------------------------- #
# HUD data endpoints for the side rails (weather + markets). Both reuse the
# trust store skills.py builds so HTTPS verifies behind a TLS-inspecting network,
# and both degrade gracefully (empty/None) so the UI never breaks.
# --------------------------------------------------------------------------- #
import json as _json
import urllib.parse as _uparse
from deimos.tools.skills import _get as _http_get


def _weather_json() -> dict:
    try:
        fmt = _uparse.quote("%t|%C|%l")
        line = _http_get(f"https://wttr.in/?format={fmt}&m", ua="curl/8.4.0").strip()
        temp, cond, loc = (line.split("|") + ["", "", ""])[:3]
        return {"temp": temp.strip(), "condition": cond.strip(), "location": loc.strip()}
    except Exception:
        return {"temp": "", "condition": "", "location": ""}


def _stocks_json(symbols: str) -> dict:
    out = []
    for sym in [s.strip() for s in symbols.split(",") if s.strip()][:6]:
        row = {"symbol": sym, "price": None, "change": None}
        try:
            url = (
                "https://query1.finance.yahoo.com/v8/finance/chart/"
                + _uparse.quote(sym) + "?interval=1d&range=1d"
            )
            j = _json.loads(_http_get(url, ua="Mozilla/5.0"))
            meta = j["chart"]["result"][0]["meta"]
            price = meta.get("regularMarketPrice")
            prev = meta.get("chartPreviousClose") or meta.get("previousClose")
            row["price"] = price
            if price is not None and prev:
                row["change"] = (price - prev) / prev * 100.0
        except Exception:
            pass
        out.append(row)
    return {"stocks": out}


@app.get("/api/weather")
async def api_weather() -> JSONResponse:
    return JSONResponse(await asyncio.to_thread(_weather_json))


@app.get("/api/stocks")
async def api_stocks(symbols: str = "AAPL,TSLA,NVDA,BTC-USD") -> JSONResponse:
    return JSONResponse(await asyncio.to_thread(_stocks_json, symbols))


app.mount("/", StaticFiles(directory=str(WEB_DIR)), name="static")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765)
