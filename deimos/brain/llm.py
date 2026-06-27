"""The brain: an Ollama chat loop with tool-calling and long-term memory.

The local model decides when to call a tool. We execute it, feed the result
back, and let the model produce the final answer. Before every turn we refresh
the system prompt with what Deimos remembers about the user, and we log each
exchange to long-term memory.

Targets a recent ollama python client (>= 0.4) with typed responses.
"""
import re
import threading
from pathlib import Path

import ollama

from deimos.config import CONFIG
from deimos.memory import memory
from deimos.tools.registry import registry

# Build/edit-intent verbs. If the user uses one of these and the model answered
# WITHOUT calling a tool, we treat it as a likely missed action and nudge once.
_BUILD_INTENT = re.compile(
    r"\b(build|make|create|redesign|improve|upgrade|change|fix|add|edit|rebuild)\w*\b",
    re.I,
)
# Signals the request is about Deimos itself (so project_path should be 'self').
_SELF_REF = re.compile(r"\b(yourself|your|deimos)\b", re.I)

# Tell-tale signs the model FAKED an answer or refused instead of using a tool:
# a written-out function call like "[get_current_time()]", or "I don't have
# access / can't check / I'm unable".
_FAIL_MARKERS = re.compile(
    r"\[\s*\w+\s*\([^\]]*\)\s*\]"
    r"|do(n'?t| not) have (access|the ability)"
    r"|can'?t (check|access|do|help with that)"
    r"|cannot (check|access|do)"
    r"|i'?m unable|i am unable|i don'?t have real[- ]?time",
    re.I,
)
# Questions that REQUIRE a tool to answer truthfully — if the model answered one
# of these without calling a tool, it made the answer up.
_TIME_Q = re.compile(
    r"\b(what'?s?( the)? (time|date|day)|what time|current (time|date)|"
    r"today'?s date|what day is)\b", re.I,
)
_WEATHER_Q = re.compile(
    r"\b(weather|temperature|forecast|how (hot|cold|warm))\b", re.I,
)


def _has_build_intent(text: str) -> bool:
    return bool(_BUILD_INTENT.search(text or ""))


def _is_self_directed(text: str) -> bool:
    return bool(_SELF_REF.search(text or ""))


def _query_needs_tool(text: str) -> bool:
    t = text or ""
    return bool(_TIME_Q.search(t) or _WEATHER_Q.search(t) or _ACTION_Q.search(t))


def _should_escalate(user_text: str, reply: str) -> bool:
    """True if a no-tool turn looks like a failure worth re-running on the 7B."""
    return (
        _has_build_intent(user_text)
        or bool(_FAIL_MARKERS.search(reply or ""))
        or _query_needs_tool(user_text)
    )


_WX_LOC = re.compile(r"\b(?:in|for|at)\s+([a-z][a-z .'\-]{1,40})", re.I)
# System-status questions (battery / memory / disk).
_SYS_Q = re.compile(
    r"\b(my battery|battery (level|percentage|life|status)|how much (battery|"
    r"memory|ram|disk|storage|space|free space)|free (memory|ram|disk|storage|"
    r"space)|system status|how('?s| is) my (mac|computer|system) doing|disk space)\b",
    re.I,
)
# Memory questions — answered deterministically from the store.
_MEM_FACTS_Q = re.compile(
    r"\b(what do you (know|remember) about me|do you remember (me|anything about "
    r"me)|what have you learned about me|who am i)\b", re.I,
)
_MEM_RECENT_Q = re.compile(
    r"\b(what did we (talk|chat|discuss)|what (did|have) (i|we) (talk|chat|"
    r"discuss)|remind me what we|recap (our|the) (chat|conversation)|what were "
    r"we (talking|chatting) about)\b", re.I,
)
# Calendar / reminder READ questions — answered by calling the native app directly.
_CAL_Q = re.compile(
    r"\b(what'?s? (on |in )?my (calendar|schedule|agenda)|my (calendar|schedule|"
    r"agenda) (for|today|tomorrow|this week)|anything (on|in) my (calendar|"
    r"schedule)|do i have (any )?(events|meetings|plans)|what('?s| does) my day "
    r"look|what'?s on (today|tomorrow))\b", re.I,
)
_REM_Q = re.compile(
    r"\b(what (are|do i have for) my reminders|list (my )?reminders|show (me )?my "
    r"reminders|my reminders|what'?s on my (to-?do|todo)|what do i (have|need) to do)\b",
    re.I,
)
# Action intents that REQUIRE a tool (create a reminder/event, send a text, play
# music). If the small model answers one of these without calling a tool, it
# probably faked the action — escalate so it actually happens.
_ACTION_Q = re.compile(
    r"\b(remind me|set (a |up a )?reminder|add (a )?reminder|schedule |put .{1,40}"
    r"on my calendar|add .{1,40}to my (calendar|schedule)|text (her|him|them|my |"
    r"mom|dad|[A-Z]\w+)|send .{1,40}(a )?(text|message|imessage)|message (her|him|"
    r"them|my |mom|dad)|^play |\bplay \w)\b", re.I,
)
# On-demand daily briefing — same content Deimos speaks each morning.
_BRIEF_Q = re.compile(
    r"\b(brief me|my (daily |morning )?briefing|(give|run) me (my|the) briefing|"
    r"catch me up|good morning|morning briefing|daily briefing|what'?s my briefing|"
    r"how('?s| is) my day looking)\b", re.I,
)
# Gate for background fact extraction: only run when the message is first-person.
_PERSONAL = re.compile(r"\b(i|i'?m|i'?ve|i'?ll|my|me|mine|myself)\b", re.I)


def _route_intent(user_text: str) -> str | None:
    """Deterministically handle the common, unambiguous assistant requests by
    calling the right tool directly — small models mis-pick tools, so we don't
    let them choose for these. Returns a speakable reply, or None to let the
    model handle it normally."""
    t = user_text or ""
    if _TIME_Q.search(t):
        res = registry.call("get_current_time", {})
        return f"It's {res}." if res and "Error" not in res else None
    if _WEATHER_Q.search(t):
        m = _WX_LOC.search(t)
        loc = m.group(1).strip().rstrip(" .?!,") if m else ""
        res = registry.call("get_weather", {"location": loc})
        return res if res and "Error" not in res else None
    if _SYS_Q.search(t):
        res = registry.call("system_status", {})
        return res if res and "Error" not in res else None
    if _BRIEF_Q.search(t):
        from deimos.proactive import compose_briefing
        return compose_briefing()
    if _MEM_FACTS_Q.search(t):
        facts = memory.all_facts()
        if not facts:
            return "I don't know much about you yet — tell me about yourself and I'll remember."
        return "Here's what I know about you: " + "; ".join(facts[-12:]) + "."
    if _MEM_RECENT_Q.search(t):
        return memory.recent_topics()
    if _REM_Q.search(t):
        res = registry.call("list_reminders", {})
        return res if res and "couldn't" not in res.lower() else None
    if _CAL_Q.search(t):
        when = ("tomorrow" if re.search(r"\btomorrow\b", t, re.I)
                else "week" if re.search(r"\b(this week|upcoming|week)\b", t, re.I)
                else "today")
        res = registry.call("calendar_events", {"when": when})
        return res if res and "couldn't" not in res.lower() else None
    return None


def _force_known_tool(user_text: str) -> str | None:
    """Guaranteed net for must-use-a-tool questions: if the model still didn't
    call a tool for a time/weather query, invoke it directly so the answer is
    always real (never faked or stalled)."""
    t = user_text or ""
    if _TIME_Q.search(t):
        res = registry.call("get_current_time", {})
        return f"It's {res}." if res and "Error" not in res else None
    if _WEATHER_Q.search(t):
        m = _WX_LOC.search(t)
        loc = m.group(1).strip().rstrip(" .?!,") if m else ""
        res = registry.call("get_weather", {"location": loc})
        return res if res and "Error" not in res else None
    return None


class Brain:
    def __init__(self) -> None:
        self.client = ollama.Client(host=CONFIG.ollama_host)
        self.history: list = [{"role": "system", "content": self._system()}]

    def _system(self) -> str:
        content = CONFIG.system_prompt
        facts = memory.all_facts()[-40:]  # cap so the prompt can't bloat over time
        if facts:
            content += "\n\nWhat you already know about the user:\n" + "\n".join(
                f"- {f}" for f in facts
            )
        active = memory.get_active_project()
        if active:
            content += (
                f"\n\nCurrent project: {Path(active).name} ({active}). For "
                "follow-up requests like 'add…', 'change…', 'make it…' that don't "
                "name a project, pass this path as project_path."
            )
        return content

    def ask(self, user_text: str, max_tool_rounds: int = 6) -> str:
        memory.log("user", user_text)
        self.history[0] = {"role": "system", "content": self._system()}
        self.history.append({"role": "user", "content": user_text})
        self._trim()

        # Deterministic routing for common requests the model mis-handles.
        routed = _route_intent(user_text)
        if routed is not None:
            self.history.append({"role": "assistant", "content": routed})
            memory.log("deimos", routed)
            return routed

        base_len = len(self.history)  # everything after this is one turn's work

        # Fast pass on the small model.
        reply, tool_called = self._chat_loop(
            max_tool_rounds, CONFIG.llm_model, CONFIG.keep_alive
        )

        # Escalate flaky no-tool turns (faked answers, skipped tools, build
        # requests) to the stronger model — re-run the turn cleanly.
        if not tool_called and _should_escalate(user_text, reply):
            del self.history[base_len:]  # discard the weak model's attempt
            reply, tool_called = self._chat_loop(
                max_tool_rounds, CONFIG.escalation_model, CONFIG.coder_keep_alive
            )

        # Guaranteed net for time/weather questions the model still faked/stalled.
        if not tool_called:
            forced = _force_known_tool(user_text)
            if forced:
                reply, tool_called = forced, True

        # Last resort: a self-directed build the model still won't act on — do it.
        if not tool_called and _has_build_intent(user_text) and _is_self_directed(user_text):
            result = registry.call(
                "run_claude_code",
                {"instruction": user_text, "project_path": "self"},
            )
            reply = result.split("\n\n", 1)[0].strip() or "On it — updating myself now."

        # Learn durable facts about the user in the background (non-blocking).
        self._remember_from(user_text)

        memory.log("deimos", reply)
        return reply

    def _remember_from(self, user_text: str) -> None:
        """Kick off background fact extraction for first-person messages."""
        if not _PERSONAL.search(user_text or "") or len((user_text or "").split()) < 3:
            return
        threading.Thread(
            target=self._extract_facts, args=(user_text,), daemon=True
        ).start()

    def _extract_facts(self, user_text: str) -> None:
        """Pull durable facts about the user out of their message and save them.
        Runs in a background thread so it never slows the conversation."""
        try:
            known = "; ".join(memory.all_facts()[-30:]) or "(nothing yet)"
            resp = self.client.chat(
                # Use the reliable 7B — extraction is background, so the extra
                # latency is invisible, and the 3B misses obvious facts.
                model=CONFIG.escalation_model,
                messages=[
                    {"role": "system", "content": (
                        "You extract durable facts about the user from their message "
                        "— their name, lasting preferences, ongoing projects, "
                        "important people, goals, or commitments. Output each NEW "
                        "fact on its own line, starting with 'The user'. Only durable "
                        "personal facts — never one-off requests, questions, "
                        "commands, or transient tasks. If nothing durable and new, "
                        "output exactly: NONE.")},
                    {"role": "user", "content": (
                        f"Already known about the user: {known}\n\n"
                        f'The user just said: "{user_text}"\n\nNew durable facts:')},
                ],
                keep_alive=CONFIG.coder_keep_alive,
                options={"temperature": 0.1, "num_ctx": 4096, "num_predict": 200},
            )
            text = (resp.message.content or "").strip()
            if not text or text.upper().startswith("NONE"):
                return
            facts = []
            for line in text.splitlines():
                line = line.strip().lstrip("-*•0123456789. ").strip()
                if (line and line.upper() != "NONE" and 8 <= len(line) <= 200
                        and line.lower().startswith("the user")):
                    facts.append(line)
            if facts:
                memory.add_facts_bg(facts[:5])
        except Exception:
            pass

    def _chat_loop(self, max_tool_rounds: int, model: str, keep_alive) -> tuple[str, bool]:
        """Run the chat/tool loop on `model`. Returns (reply, any_tool_called)."""
        tool_called = False
        opts = {
            "num_ctx": CONFIG.llm_num_ctx,
            "num_predict": CONFIG.llm_num_predict,
            "temperature": CONFIG.llm_temperature,
        }
        try:
            for _ in range(max_tool_rounds):
                response = self.client.chat(
                    model=model, messages=self.history, tools=registry.schemas(),
                    keep_alive=keep_alive, options=opts,
                )
                message = response.message
                self.history.append(message)

                if not message.tool_calls:
                    return (message.content or "").strip(), tool_called

                tool_called = True
                for call in message.tool_calls:
                    name = call.function.name
                    args = dict(call.function.arguments or {})
                    result = registry.call(name, args)
                    self.history.append(
                        {"role": "tool", "name": name, "content": result}
                    )

            final = self.client.chat(
                model=model, messages=self.history,
                keep_alive=keep_alive, options=opts,
            )
            return (final.message.content or "").strip(), tool_called
        except Exception as exc:
            # Never let a backend hiccup crash the conversation loop.
            memory.log("error", f"{type(exc).__name__}: {exc}")
            return "Sorry, my thinking backend isn't responding right now.", tool_called

    def _trim(self) -> None:
        if len(self.history) > CONFIG.history_limit + 1:
            self.history = [self.history[0]] + self.history[-CONFIG.history_limit:]
