"""Deimos entry point: a minimal but extensible voice loop.

Press Enter to talk (Deimos records until you go quiet), or just type a message
to test without a mic. Deimos transcribes locally, thinks with a local model
(calling tools when useful), and speaks the reply.

This is the spine. Wake word, the HUD, Google integrations, and Claude Code all
plug into the same tool registry and brain you see here.
"""
from deimos.audio.stt import SpeechToText
from deimos.audio.tts import TextToSpeech
from deimos.brain.llm import Brain
import deimos.tools.builtin  # noqa: F401  registers the built-in tools on import
import deimos.tools.memory_tools  # noqa: F401  registers remember/recall
import deimos.tools.skills  # noqa: F401  registers web/weather/system/notes/etc.
import deimos.tools.code_tools  # noqa: F401  registers run_claude_code


def main() -> None:
    print("Loading Deimos...")
    stt = SpeechToText()
    tts = TextToSpeech()
    brain = Brain()
    print("Ready. Press Enter to talk, or type a message. Type 'quit' to exit.\n")

    while True:
        try:
            typed = input("you > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if typed.lower() in {"quit", "exit"}:
            print("Goodbye.")
            break

        if typed:
            user_text = typed
        else:
            print("[listening... speak now]")
            user_text = stt.listen()
            print(f"you (voice) > {user_text}")

        if not user_text:
            continue

        reply = brain.ask(user_text)
        print(f"deimos > {reply}\n")
        tts.speak(reply)


if __name__ == "__main__":
    main()
