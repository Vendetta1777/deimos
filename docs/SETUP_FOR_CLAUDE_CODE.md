# SETUP INSTRUCTIONS FOR CLAUDE CODE

You are setting up a local voice assistant ("Deimos") on a Mac (Apple Silicon
M4, 16 GB, macOS Sequoia). The user has tried this a few times and ended up with
duplicate project folders and version confusion. Your job is to make ONE clean,
working copy and launch it. Explain what you're doing as you go, and stop to ask
only if you hit something you genuinely cannot resolve.

## Context you should know
- The newest, correct project files are in THIS folder (the one containing this
  file: server.py, main.py, requirements.txt, web/, and the deimos/ package).
- The user may already have older copies at ~/deimos and/or ~/Desktop/deimos.
- A Python virtual environment may already exist in one of those copies, along
  with a voices/ folder containing a downloaded Piper model
  (en_GB-alan-medium.onnx + .json). Preserve those if present — re-downloading
  is slow and wasteful.
- Long-term memory lives at ~/.deimos/memory.db (OUTSIDE the project). Never
  delete this; it is the user's accumulated memory.

## Goal
A single project folder at ~/deimos that contains THESE (newest) files, plus a
working .venv and the voices/ folder, with no leftover duplicate on the Desktop,
and the server running.

## Steps
1. Identify all existing deimos copies: check ~/deimos and ~/Desktop/deimos.
   Report what each contains (especially .venv and voices/).

2. Establish ~/deimos as the single home for the project:
   - Copy ALL files from this folder into ~/deimos, OVERWRITING older versions.
     (These files are the source of truth. Overwrite server.py, main.py,
     requirements.txt, README.md, and the entire web/ and deimos/ trees.)
   - If a .venv already exists in ~/deimos OR ~/Desktop/deimos, reuse the
     existing one (move it into ~/deimos if needed). Otherwise create a new
     venv: `python3 -m venv .venv`.
   - If a voices/ folder with the .onnx model exists anywhere, make sure it
     ends up at ~/deimos/voices/. Otherwise leave it; the app falls back to a
     system voice.

3. Activate the venv and install dependencies:
   `source .venv/bin/activate && pip install -r requirements.txt`
   Also ensure WebSocket support: `pip install "uvicorn[standard]"`.
   If a Piper model is present, ensure piper is installed: `pip install piper-tts`.

4. Remove the duplicate ONLY after ~/deimos is confirmed complete and working:
   delete ~/Desktop/deimos. Do NOT touch ~/.deimos (memory).

5. Verify the version is the NEWEST UI before declaring success:
   `grep -c textin ~/deimos/web/index.html` MUST print 0. (If it prints 1+, the
   old files are still in place — re-copy from this folder.)

6. Launch: from ~/deimos with the venv active, run `python server.py`.
   If port 8765 is busy, free it first: `lsof -ti:8765 | xargs kill -9`.
   Tell the user to open http://localhost:8765 and that the page should show
   NO text box — just the orb and "tap the orb or press space to speak."

## Things only the user can do (tell them to do these)
- Grant microphone permission when macOS and the browser prompt.
- For the most natural voice without Piper: System Settings -> Accessibility ->
  Spoken Content -> System Voice -> Manage Voices -> download an English
  "(Premium)" voice.

## Voice expectation
With the Piper model at ~/deimos/voices/en_GB-alan-medium.onnx and piper-tts
installed, replies use a deep, natural British voice. Without it, the app
auto-selects the best installed macOS voice and falls back to a default.
Confirm to the user which voice path is active.
