"""The brain: an Ollama chat loop with tool-calling and long-term memory.

The local model decides when to call a tool. We execute it, feed the result
back, and let the model produce the final answer. Before every turn we refresh
the system prompt with what Deimos remembers about the user, and we log each
exchange to long-term memory.

Targets a recent ollama python client (>= 0.4) with typed responses.
"""
import re
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


def _has_build_intent(text: str) -> bool:
    return bool(_BUILD_INTENT.search(text or ""))


def _is_self_directed(text: str) -> bool:
    return bool(_SELF_REF.search(text or ""))


class Brain:
    def __init__(self) -> None:
        self.client = ollama.Client(host=CONFIG.ollama_host)
        self.history: list = [{"role": "system", "content": self._system()}]

    def _system(self) -> str:
        content = CONFIG.system_prompt
        facts = memory.all_facts()
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

        reply, tool_called = self._chat_loop(max_tool_rounds)

        # Backstop: a build/edit request that came back as plain text (no tool)
        # almost always means the small model described instead of acting.
        if not tool_called and _has_build_intent(user_text):
            reply = self._force_action(user_text, reply)

        memory.log("deimos", reply)
        return reply

    def _chat_loop(self, max_tool_rounds: int) -> tuple[str, bool]:
        """Run the chat/tool loop. Returns (reply, whether any tool was called)."""
        tool_called = False
        try:
            for _ in range(max_tool_rounds):
                response = self.client.chat(
                    model=CONFIG.llm_model,
                    messages=self.history,
                    tools=registry.schemas(),
                    keep_alive=CONFIG.keep_alive,
                    options={
                        "num_ctx": CONFIG.llm_num_ctx,
                        "num_predict": CONFIG.llm_num_predict,
                    },
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
                model=CONFIG.llm_model,
                messages=self.history,
                keep_alive=CONFIG.keep_alive,
                options={
                    "num_ctx": CONFIG.llm_num_ctx,
                    "num_predict": CONFIG.llm_num_predict,
                },
            )
            return (final.message.content or "").strip(), tool_called
        except Exception as exc:
            # Never let a backend hiccup crash the conversation loop.
            memory.log("error", f"{type(exc).__name__}: {exc}")
            return "Sorry, my thinking backend isn't responding right now.", tool_called

    def _force_action(self, user_text: str, prior_reply: str) -> str:
        """One forceful retry to make the model actually call run_claude_code.

        If it still won't, and the request is clearly about Deimos itself, call
        the tool directly (project_path='self') as a last resort. For non-self
        requests we don't guess a project path — we return the model's reply.
        """
        nudge_idx = len(self.history)
        self.history.append({
            "role": "system",
            "content": (
                "The user's last message asks you to build, change, improve, or "
                "fix something. If it is a real request to build or modify code, "
                "a website, a project, or yourself, you MUST call run_claude_code "
                "now — pass the user's request as 'instruction', and "
                "project_path='self' for changes to Deimos itself, otherwise the "
                "project name. Do not describe what you would do. If the message "
                "was only a question, answer it briefly instead."
            ),
        })
        reply, tool_called = self._chat_loop(2)
        # Remove just the nudge so it doesn't bias later turns.
        try:
            del self.history[nudge_idx]
        except IndexError:
            pass

        if tool_called:
            return reply
        if _is_self_directed(user_text):
            result = registry.call(
                "run_claude_code",
                {"instruction": user_text, "project_path": "self"},
            )
            # Keep the spoken reply short: the tool's status line, not the dump.
            return result.split("\n\n", 1)[0].strip() or "On it — updating myself now."
        return prior_reply

    def _trim(self) -> None:
        if len(self.history) > CONFIG.history_limit + 1:
            self.history = [self.history[0]] + self.history[-CONFIG.history_limit:]
