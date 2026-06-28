"""Files & documents: find files by name/content, and summarize a document.

Search uses Spotlight (mdfind), which works without Full Disk Access. READING a
file's contents (to summarize) needs access — fine for most of the home folder,
but macOS protects Desktop/Documents/Downloads, so summarizing a file there
needs Full Disk Access; we say so clearly instead of failing silently.
"""
import subprocess
from pathlib import Path

import ollama

from deimos.config import CONFIG
from deimos.tools.registry import registry

_HOME = str(Path.home())
_DOC_EXTS = {
    ".pdf", ".docx", ".doc", ".rtf", ".txt", ".md", ".markdown", ".pages",
    ".html", ".htm", ".csv", ".key", ".pptx", ".odt",
}
_RICH_EXTS = {".docx", ".doc", ".rtf", ".html", ".htm", ".odt"}


def _mdfind(expr: str) -> list[str]:
    try:
        r = subprocess.run(["mdfind", "-onlyin", _HOME, expr],
                           capture_output=True, text=True, timeout=12, check=False)
        return [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
    except Exception:
        return []


def _find_paths(query: str) -> list[str]:
    q = (query or "").replace("'", "").replace('"', "").strip()
    if not q:
        return []
    # Name match first (most intuitive), then full-text/content.
    return _mdfind(f"kMDItemDisplayName == '*{q}*'cd") or _mdfind(q)


def _resolve_doc(query: str) -> str | None:
    q = (query or "").strip().strip('"\'')
    p = Path(q).expanduser()
    if p.is_file():
        return str(p)
    hits = _find_paths(q)
    docs = [h for h in hits if Path(h).suffix.lower() in _DOC_EXTS]
    return (docs or hits or [None])[0]


def _extract_text(path: str) -> str:
    """Return a document's text, '' if unreadable, or '__PERMISSION__' if blocked."""
    p = Path(path)
    suf = p.suffix.lower()
    try:
        if suf == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(str(p))
            return "\n".join((pg.extract_text() or "") for pg in reader.pages[:40])
        if suf in _RICH_EXTS:
            r = subprocess.run(["textutil", "-convert", "txt", "-stdout", str(p)],
                               capture_output=True, text=True, timeout=20, check=False)
            return r.stdout or ""
        return p.read_text("utf-8", errors="ignore")
    except PermissionError:
        return "__PERMISSION__"
    except Exception:
        return ""


def _summarize(text: str, name: str) -> str:
    try:
        client = ollama.Client(host=CONFIG.ollama_host)
        resp = client.chat(
            model=CONFIG.escalation_model,
            messages=[
                {"role": "system", "content": (
                    "You summarize documents in 2 to 4 clear, plain spoken "
                    "sentences. No markdown, no lists. English only.")},
                {"role": "user", "content": f"Summarize this document ({name}):\n\n{text}"},
            ],
            keep_alive=CONFIG.coder_keep_alive,
            options={"temperature": 0.2, "num_ctx": 8192, "num_predict": 320},
        )
        return (resp.message.content or "").strip() or f"I read {name} but couldn't summarize it."
    except Exception as exc:
        return f"I couldn't summarize that ({exc})."


@registry.tool(
    name="find_file",
    description=(
        "Find files on the Mac by name or contents using Spotlight. Use for "
        "'find my file about X', 'where's the Y document', 'find the Z pdf'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for (name or topic)."}
        },
        "required": ["query"],
    },
)
def find_file(query: str) -> str:
    query = (query or "").strip()
    if not query:
        return "What should I look for?"
    hits = _find_paths(query)
    if not hits:
        return f"I couldn't find anything matching '{query}'."
    lines = [f"{Path(h).name} (in {Path(h).parent.name})" for h in hits[:5]]
    more = f", and {len(hits) - 5} more" if len(hits) > 5 else ""
    return f"I found: {'; '.join(lines)}{more}."


@registry.tool(
    name="summarize_doc",
    description=(
        "Find a document and summarize its contents out loud. Use for 'summarize "
        "X', 'what's in the Y doc', 'give me the gist of Z'. Handles PDF, Word, "
        "and text files."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The document name, path, or topic."}
        },
        "required": ["query"],
    },
)
def summarize_doc(query: str) -> str:
    query = (query or "").strip()
    if not query:
        return "Which document should I summarize?"
    path = _resolve_doc(query)
    if not path:
        return f"I couldn't find a document matching '{query}'."
    text = _extract_text(path)
    if text == "__PERMISSION__":
        return ("I found it but can't read it — grant Deimos Full Disk Access in "
                "System Settings, Privacy & Security, then ask again.")
    text = (text or "").strip()
    if not text:
        return f"I found {Path(path).name}, but couldn't read any text from it."
    return _summarize(text[:12000], Path(path).name)
