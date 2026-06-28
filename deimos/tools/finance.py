"""Finance & econ: live quotes, a market snapshot, and a watchlist — Deimos's
fintech brain. Uses the same free Yahoo Finance endpoint as the UI's market
rail (no API key), via the certifi+keychain SSL getter from skills.
"""
import json
import urllib.parse

from deimos.config import CONFIG
from deimos.tools.registry import registry
from deimos.tools.skills import _get

# Spoken names / tickers -> Yahoo symbol.
_ALIASES = {
    "apple": "AAPL", "tesla": "TSLA", "nvidia": "NVDA", "google": "GOOGL",
    "alphabet": "GOOGL", "amazon": "AMZN", "microsoft": "MSFT", "meta": "META",
    "facebook": "META", "netflix": "NFLX", "amd": "AMD", "intel": "INTC",
    "bitcoin": "BTC-USD", "btc": "BTC-USD", "ethereum": "ETH-USD", "eth": "ETH-USD",
    "the s&p": "^GSPC", "s&p": "^GSPC", "s&p 500": "^GSPC", "sp500": "^GSPC",
    "the nasdaq": "^IXIC", "nasdaq": "^IXIC", "the dow": "^DJI", "dow": "^DJI",
    "dow jones": "^DJI", "the market": "^GSPC",
}
# Yahoo symbol -> friendly spoken name.
_DISPLAY = {
    "AAPL": "Apple", "TSLA": "Tesla", "NVDA": "Nvidia", "GOOGL": "Alphabet",
    "AMZN": "Amazon", "MSFT": "Microsoft", "META": "Meta", "NFLX": "Netflix",
    "AMD": "AMD", "INTC": "Intel", "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum",
    "^GSPC": "the S&P 500", "^IXIC": "the Nasdaq", "^DJI": "the Dow",
}


def find_symbols(text: str) -> list[str]:
    """Pull tickers/known names out of a spoken phrase, for routing quotes."""
    import re
    low = (text or "").lower()
    found: list[str] = []
    for name in sorted(_ALIASES, key=len, reverse=True):  # 's&p 500' before 's&p'
        if name in low and _ALIASES[name] not in found:
            found.append(_ALIASES[name])
    _STOP = {"THE", "HOW", "WHAT", "USD", "IS", "MY", "AT", "DOING", "STOCK", "PRICE"}
    for m in re.findall(r"\b[A-Z]{2,5}\b", text or ""):
        if m not in found and m not in _STOP:
            found.append(m)
    return found


def _symbolize(token: str) -> str:
    t = (token or "").strip().lower()
    if t in _ALIASES:
        return _ALIASES[t]
    return token.strip().upper()


def _quote(symbol: str) -> dict | None:
    try:
        url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
               + urllib.parse.quote(symbol) + "?interval=1d&range=1d")
        j = json.loads(_get(url, ua="Mozilla/5.0"))
        meta = j["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice")
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        if price is None:
            return None
        chg = ((price - prev) / prev * 100.0) if prev else None
        return {"symbol": symbol, "price": price, "change": chg,
                "currency": meta.get("currency", "")}
    except Exception:
        return None


def _say_one(symbol: str, q: dict) -> str:
    name = _DISPLAY.get(symbol, symbol)
    price = q["price"]
    p = f"${price:,.2f}" if price < 1000 else f"${price:,.0f}"
    if q["change"] is None:
        return f"{name} is at {p}"
    arrow = "up" if q["change"] >= 0 else "down"
    return f"{name} is at {p}, {arrow} {abs(q['change']):.1f} percent"


@registry.tool(
    name="market_quote",
    description=(
        "Get live prices for stocks, indices, or crypto. Use for 'how's Apple', "
        "'what's Tesla at', 'how's Bitcoin doing', 'price of NVDA'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "symbols": {"type": "string", "description": "Comma- or space-separated names/tickers, e.g. 'apple, tesla'."}
        },
        "required": ["symbols"],
    },
)
def market_quote(symbols: str) -> str:
    raw = [s for s in re_split(symbols) if s]
    if not raw:
        return "Which stock or ticker?"
    parts = []
    for tok in raw[:5]:
        sym = _symbolize(tok)
        q = _quote(sym)
        parts.append(_say_one(sym, q) if q else f"I couldn't get a price for {tok}")
    return "; ".join(parts) + "."


def re_split(s: str) -> list[str]:
    import re
    return [x.strip() for x in re.split(r"[,/]|\band\b", s or "", flags=re.I) if x.strip()]


@registry.tool(
    name="market_today",
    description=(
        "Summarize how the market did today — the major US indices. Use for "
        "'what moved the market today', 'how's the market', 'how are stocks'."
    ),
)
def market_today() -> str:
    out = []
    for sym in ("^GSPC", "^IXIC", "^DJI"):
        q = _quote(sym)
        if q and q["change"] is not None:
            arrow = "up" if q["change"] >= 0 else "down"
            out.append(f"{_DISPLAY[sym]} is {arrow} {abs(q['change']):.1f} percent")
    if not out:
        return "I couldn't reach the markets just now."
    lead = "Markets today: " + "; ".join(out) + "."
    # Best-effort one-line "why" from the news — only if it's actually useful.
    try:
        why = registry.call("web_search", {"query": "stock market news today"})
        low = (why or "").lower()
        if why and len(why) > 30 and not any(
                b in low for b in ("didn't find", "couldn't", "no result", "error")):
            lead += " " + why.strip().split("\n")[0][:200]
    except Exception:
        pass
    return lead


@registry.tool(
    name="watchlist",
    description=(
        "Report the user's watchlist — the tickers they follow. Use for 'how's "
        "my watchlist', 'how's my portfolio', 'check my stocks'."
    ),
)
def watchlist() -> str:
    syms = [s for s in getattr(CONFIG, "watchlist", ()) if s]
    if not syms:
        return "Your watchlist is empty. Add tickers to CONFIG.watchlist."
    parts = []
    for sym in syms[:8]:
        q = _quote(sym)
        if q:
            parts.append(_say_one(sym, q))
    return ("Your watchlist: " + "; ".join(parts) + ".") if parts else "I couldn't reach the markets just now."
