"""Tools that let Deimos write to and read from long-term memory."""
from deimos.memory import memory
from deimos.tools.registry import registry


@registry.tool(
    name="remember",
    description=(
        "Save a durable fact about the user so you recall it in future "
        "conversations. Use for their name, preferences, ongoing projects, "
        "important people, and goals."
    ),
    parameters={
        "type": "object",
        "properties": {
            "fact": {
                "type": "string",
                "description": "A short, self-contained fact about the user.",
            }
        },
        "required": ["fact"],
    },
)
def remember(fact: str) -> str:
    return memory.add_fact(fact)


@registry.tool(
    name="recall",
    description="Search past conversations for what the user said about a topic.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "A word or phrase to look for."}
        },
        "required": ["query"],
    },
)
def recall(query: str) -> str:
    return memory.search(query)
