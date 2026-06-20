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
import re
import subprocess
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from deimos.audio.stt import SpeechToText
from deimos.audio.tts import TextToSpeech
from deimos.brain.llm import Brain
from deimos.progress import progress
import deimos.tools.builtin  # noqa: F401  registers the built-in tools
import deimos.tools.memory_tools  # noqa: F401  registers remember/recall
import deimos.tools.skills  # noqa: F401  registers web/weather/system/notes/etc.
import deimos.tools.system_tools  # noqa: F401  registers open_url/media/volume/run_command
import deimos.tools.code_tools  # noqa: F401  registers run_claude_code

WEB_DIR = Path(__file__).parent / "web"
PROJECTS_ROOT = Path("~/deimos-projects").expanduser()

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

            # Stream live progress (phase + elapsed) while the turn runs in a
            # worker thread, so the UI isn't frozen on "thinking" during builds.
            progress.start()

            async def push_progress() -> None:
                try:
                    while True:
                        phase, elapsed = progress.snapshot()
                        await socket.send_json({
                            "type": "progress",
                            "phase": phase or "Thinking",
                            "elapsed": elapsed,
                            "estimate": progress.estimate,
                        })
                        await asyncio.sleep(1)
                except asyncio.CancelledError:
                    pass

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


app.mount("/", StaticFiles(directory=str(WEB_DIR)), name="static")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765)
