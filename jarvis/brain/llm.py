"""The brain: an Ollama chat loop with tool-calling and long-term memory.

The local model decides when to call a tool. We execute it, feed the result
back, and let the model produce the final answer. Before every turn we refresh
the system prompt with what Jarvis remembers about the user, and we log each
exchange to long-term memory.

Targets a recent ollama python client (>= 0.4) with typed responses.
"""
import ollama

from jarvis.config import CONFIG
from jarvis.memory import memory
from jarvis.tools.registry import registry


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
        return content

    def ask(self, user_text: str, max_tool_rounds: int = 6) -> str:
        memory.log("user", user_text)
        self.history[0] = {"role": "system", "content": self._system()}
        self.history.append({"role": "user", "content": user_text})
        self._trim()

        try:
            for _ in range(max_tool_rounds):
                response = self.client.chat(
                    model=CONFIG.llm_model,
                    messages=self.history,
                    tools=registry.schemas(),
                )
                message = response.message
                self.history.append(message)

                if not message.tool_calls:
                    reply = (message.content or "").strip()
                    memory.log("jarvis", reply)
                    return reply

                for call in message.tool_calls:
                    name = call.function.name
                    args = dict(call.function.arguments or {})
                    result = registry.call(name, args)
                    self.history.append(
                        {"role": "tool", "name": name, "content": result}
                    )

            final = self.client.chat(model=CONFIG.llm_model, messages=self.history)
            reply = (final.message.content or "").strip()
        except Exception as exc:
            # Never let a backend hiccup crash the conversation loop.
            reply = "Sorry, my thinking backend isn't responding right now."
            memory.log("error", f"{type(exc).__name__}: {exc}")

        memory.log("jarvis", reply)
        return reply

    def _trim(self) -> None:
        if len(self.history) > CONFIG.history_limit + 1:
            self.history = [self.history[0]] + self.history[-CONFIG.history_limit:]
