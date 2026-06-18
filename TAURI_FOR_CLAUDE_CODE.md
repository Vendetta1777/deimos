# TAURI WINDOW INSTRUCTIONS FOR CLAUDE CODE

Goal: turn the user's Jarvis (a local web app served at http://localhost:8765)
into a standalone macOS desktop window — its own app icon, no browser, no tabs.
The Python server keeps running the brain; Tauri is only the window that loads it.

Platform: Apple Silicon Mac, macOS Sequoia. Node is already installed. Rust is
NOT yet installed (a previous attempt failed with a permission error writing to
~/.bash_profile). Narrate as you go; only stop if truly blocked.

## Steps

1. Install Rust, working around the earlier permission error:
   - Run: `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y`
   - If it errors amending the shell profile, that's non-fatal. Fix PATH for the
     current and future sessions:
       `source "$HOME/.cargo/env"`
     and ensure this line is in ~/.zshrc (the user's shell is zsh; the failing
     file was .bash_profile, which zsh doesn't use):
       `. "$HOME/.cargo/env"`
   - Verify: `cargo --version` should print a version.
   - If ~/.bash_profile is owned by root (the cause of the earlier error), do NOT
     chown system files; just rely on ~/.zshrc as above.

2. Scaffold a Tauri v2 app in the user's home folder:
   - `cd ~ && npm create tauri-app@latest jarvis-window -- --template vanilla --manager npm`
   - If the CLI is interactive, choose: vanilla template, TypeScript = No.
   - `cd jarvis-window && npm install`

3. Point the main window at the running Jarvis server and theme it. Edit
   `src-tauri/tauri.conf.json` so the primary window object includes:
       "title": "Jarvis",
       "url": "http://localhost:8765",
       "width": 1000,
       "height": 760,
       "resizable": true,
       "decorations": true,
       "theme": "Dark"
   (Match the exact schema of the installed Tauri version — the key is that the
   window loads the external URL http://localhost:8765.)

4. Microphone in the webview: the orb's voice-reactivity uses getUserMedia inside
   the webview. On macOS this needs a usage description. Add an
   NSMicrophoneUsageDescription ("Jarvis listens to your voice") to the macOS
   bundle/Info.plist via the Tauri config so the webview can access the mic. If
   the Tauri version makes this awkward, note it and continue — transcription
   still works server-side; only the orb's visual reaction depends on it.

5. Run it (the Python server must be running first):
   - In one terminal: `cd ~/jarvis && source .venv/bin/activate && python server.py`
   - In another: `cd ~/jarvis-window && npm run tauri dev`
   - A native Jarvis window should open showing the orb. The first build compiles
     Rust and may take several minutes — that's normal.

6. Report: confirm the window opened, whether mic reactivity works in it, and how
   to launch it next time. (A production build is `npm run tauri build`, which
   produces a .app — mention this but don't build it unless asked.)

## Notes
- Do not modify ~/jarvis itself or ~/.jarvis (the memory DB).
- If the window is blank, the server isn't running or isn't on port 8765.
