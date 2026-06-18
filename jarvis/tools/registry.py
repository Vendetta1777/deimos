"""A tiny tool registry. Decorate a function with @registry.tool and the local
model can call it.

This is the whole extensibility story: to give Jarvis a new skill, write a
function, decorate it, and import the module. The brain handles the rest. Later,
MCP servers can be wrapped as tools and registered here too.
"""
from dataclasses import dataclass
from typing import Callable


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    func: Callable[..., object]

    @property
    def schema(self) -> dict:
        """Ollama-compatible function schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class Registry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def tool(self, name: str, description: str, parameters: dict | None = None):
        def decorator(func: Callable[..., object]):
            self._tools[name] = Tool(
                name=name,
                description=description,
                parameters=parameters or {"type": "object", "properties": {}},
                func=func,
            )
            return func

        return decorator

    def schemas(self) -> list[dict]:
        return [t.schema for t in self._tools.values()]

    def call(self, name: str, arguments: dict) -> str:
        """Run a tool by name. Tools must never crash the main loop."""
        if name not in self._tools:
            return f"Error: unknown tool '{name}'."
        try:
            return str(self._tools[name].func(**arguments))
        except Exception as exc:
            return f"Error running {name}: {exc}"


registry = Registry()
