#!/bin/bash
# Deimos one-click launcher.
#
# Safe to run repeatedly: it never starts a second server or a second Ollama.
# It makes sure Ollama is up, starts the Deimos server if the port is free,
# waits for it to answer, then opens a clean app-style window.

# GUI launches (double-clicking an .app) start with a minimal PATH, so add the
# usual locations where Homebrew, npm, and cargo install tools.
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.npm-global/bin:$HOME/.cargo/bin:$PATH"

DEIMOS_DIR="$HOME/deimos"
PY="$DEIMOS_DIR/.venv/bin/python"
URL="http://localhost:8765"

# 1. Ensure Ollama is running (the brain). If nothing answers on 11434, start it.
if ! curl -s -o /dev/null --max-time 2 "http://localhost:11434/"; then
  if ! open -a "Ollama" 2>/dev/null; then
    nohup ollama serve >/tmp/ollama_serve.log 2>&1 &
  fi
  sleep 3
fi

# 2. Start the Deimos server only if port 8765 is free (no duplicate servers).
if [ -z "$(lsof -ti:8765)" ]; then
  cd "$DEIMOS_DIR" && nohup "$PY" server.py >/tmp/deimos_server.log 2>&1 &
fi

# 3. Wait (up to ~15s) for the server to answer.
for _ in $(seq 1 30); do
  if curl -s -o /dev/null --max-time 1 "$URL/"; then
    break
  fi
  sleep 0.5
done

# 4. Open a clean, chrome-less app window if Google Chrome is installed,
#    otherwise fall back to the default browser.
CHROME="/Applications/Google Chrome.app"
if [ -d "$CHROME" ]; then
  "$CHROME/Contents/MacOS/Google Chrome" --app="$URL" --new-window >/dev/null 2>&1 &
else
  open "$URL"
fi
