"""Long-term memory for Deimos, backed by a local SQLite database.

Two layers:
  - turns:  every exchange ever, logged verbatim (the full record)
  - facts:  durable things Deimos has learned about the user, injected into
            the system prompt each turn so he stays personal across sessions

Uses only the standard library. The database lives outside the project folder
(default ~/.deimos/memory.db) so it survives re-downloading the app.
"""
import sqlite3
import time
from pathlib import Path

from deimos.config import CONFIG


class Memory:
    def __init__(self) -> None:
        self.path = Path(CONFIG.memory_path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the brain runs in worker threads, and access
        # is serialised by the server's busy lock, so this is safe here.
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS turns "
            "(id INTEGER PRIMARY KEY, ts REAL, role TEXT, text TEXT)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS facts "
            "(id INTEGER PRIMARY KEY, ts REAL, fact TEXT UNIQUE)"
        )
        # Simple key/value store for small bits of working state (e.g. the
        # currently active project, so the user can iterate by voice).
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS state "
            "(key TEXT PRIMARY KEY, value TEXT, ts REAL)"
        )
        self.db.commit()

    def log(self, role: str, text: str) -> None:
        if not text:
            return
        self.db.execute(
            "INSERT INTO turns (ts, role, text) VALUES (?, ?, ?)",
            (time.time(), role, text),
        )
        self.db.commit()

    def add_fact(self, fact: str) -> str:
        fact = fact.strip()
        if not fact:
            return "Nothing to remember."
        self.db.execute(
            "INSERT OR IGNORE INTO facts (ts, fact) VALUES (?, ?)",
            (time.time(), fact),
        )
        self.db.commit()
        return f"Remembered: {fact}"

    def all_facts(self) -> list[str]:
        return [row[0] for row in self.db.execute("SELECT fact FROM facts ORDER BY id")]

    def search(self, query: str, limit: int = 5) -> str:
        rows = self.db.execute(
            "SELECT role, text FROM turns WHERE text LIKE ? ORDER BY id DESC LIMIT ?",
            (f"%{query}%", limit),
        ).fetchall()
        if not rows:
            return "No matching past messages."
        return "\n".join(f"{role}: {text}" for role, text in reversed(rows))

    def turn_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM turns").fetchone()[0]

    # --- small key/value working state ---
    def set_state(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO state (key, value, ts) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, ts = excluded.ts",
            (key, str(value), time.time()),
        )
        self.db.commit()

    def get_state(self, key: str, default: str | None = None) -> str | None:
        row = self.db.execute(
            "SELECT value FROM state WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else default

    def set_active_project(self, path: str) -> None:
        self.set_state("active_project", str(path))

    def get_active_project(self) -> str | None:
        return self.get_state("active_project")


memory = Memory()
