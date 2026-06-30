# Deimos — 60-second demo script

A tight sequence that shows breadth + the "wow" moments. Record your screen
(QuickTime → File → New Screen Recording, capture system audio so Deimos's voice
is in the clip) with the orb visible. Hold **⌃⌥Space** and speak each line; pause
for the spoken reply before the next.

---

**0:00 — Cold open (the hook)**
Have the orb on screen. Say:
> "Good morning."

→ It speaks the full briefing: date, weather, your calendar, the S&P. *(One line, and it already feels alive.)*

**0:10 — It controls the Mac**
> "Go dark mode."  → screen flips to dark
> "Take a screenshot."  → shutter + "saved to your Desktop"

**0:20 — A routine (the showpiece)**
> "Study mode."

→ Distracting Chrome tabs close, your playlist starts, a 25-minute timer is set — all from one phrase. *Narrate over it.*

**0:30 — Finance (your angle)**
> "How's Apple doing?"  → live price + % move
> "What moved the market today?"  → indices + a one-line why

**0:38 — Reads your documents**
> "Summarize my [pick a doc]."

→ It finds the file and speaks a clean 2–3 sentence summary.

**0:48 — Watches for you (proactivity)**
> "Tell me when my download finishes."

→ "Got it." Start a download; seconds later it speaks up on its own: *"Your download just finished."*

**0:56 — Close**
> "What do you know about me?"

→ It recalls facts it learned about you during the session. End on that — it *knows* you.

---

## Talking points (for a caption or voiceover)
- **100% local** — speech, the LLM, and the voice all run on-device. Nothing leaves the Mac.
- **39 tools, ~5,000 lines**, built solo.
- The hard part wasn't the features — it was making a **3B local model reliable** (deterministic routing + model escalation).
- The deep voice is a **local neural model, pitch-shifted** — no cloud TTS.

## One-liner for applications
> "Deimos is a private, local-first voice assistant for the Mac — it controls my
> computer, manages my day, tracks markets, and reads my documents, all on-device.
> I built the reliability layer that makes a small local model behave like a
> dependable assistant."
