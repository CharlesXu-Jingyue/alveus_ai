"""Web MCP server: search (DuckDuckGo) and page fetch -> readable text."""
from __future__ import annotations

import httpx

from .common import FastMCP, annot, j

mcp = FastMCP("web")
UA = "Mozilla/5.0 (X11; Linux x86_64) AlveusAssistant/0.1"


@mcp.tool(annotations=annot(read_only=True))
def web_search(query: str, max_results: int = 6, kind: str = "text") -> str:
    """Search the web. kind: text | news."""
    try:
        from ddgs import DDGS

        with DDGS() as d:
            fn = d.news if kind == "news" else d.text
            rows = list(fn(query, max_results=max_results))
        out = [{"title": r.get("title"), "url": r.get("href") or r.get("url"),
                "snippet": (r.get("body") or r.get("excerpt") or "")[:300]} for r in rows]
        return j({"query": query, "results": out})
    except Exception as e:  # noqa: BLE001
        return j({"error": f"search failed: {e}"})


@mcp.tool(annotations=annot(read_only=True))
def fetch_page(url: str, max_chars: int = 6000) -> str:
    """Fetch a web page and return its main readable text."""
    try:
        with httpx.Client(follow_redirects=True, timeout=20, headers={"User-Agent": UA}) as c:
            r = c.get(url)
            r.raise_for_status()
            ctype = r.headers.get("content-type", "")
        if "json" in ctype:
            return j({"url": str(r.url), "json": r.text[:max_chars]})
        text = None
        try:
            import trafilatura

            text = trafilatura.extract(r.text, include_links=False, include_tables=True, favor_recall=True)
        except Exception:  # noqa: BLE001
            text = None
        if not text:
            import re

            text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", r.text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text)
        return j({"url": str(r.url), "chars": len(text), "text": text[:max_chars]})
    except Exception as e:  # noqa: BLE001
        return j({"error": f"fetch failed: {e}"})


@mcp.tool(annotations=annot(read_only=True))
def weather(location: str = "") -> str:
    """Current weather and short forecast (wttr.in). Empty location = auto by IP."""
    try:
        with httpx.Client(timeout=15, headers={"User-Agent": "curl/8"}) as c:
            r = c.get(f"https://wttr.in/{location}?format=j1")
            r.raise_for_status()
            d = r.json()
        cur = d["current_condition"][0]
        days = [{"date": x["date"], "max_c": x["maxtempC"], "min_c": x["mintempC"],
                 "desc": x["hourly"][4]["weatherDesc"][0]["value"]} for x in d["weather"][:3]]
        area = d.get("nearest_area", [{}])[0]
        return j({"location": area.get("areaName", [{}])[0].get("value", location),
                  "now": {"temp_c": cur["temp_C"], "feels_c": cur["FeelsLikeC"], "desc": cur["weatherDesc"][0]["value"],
                          "humidity": cur["humidity"], "wind_kmph": cur["windspeedKmph"]}, "forecast": days})
    except Exception as e:  # noqa: BLE001
        return j({"error": f"weather failed: {e}"})


if __name__ == "__main__":
    mcp.run()
