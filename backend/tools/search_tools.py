"""Agent tools. Each takes a structured query, calls SerpApi, and returns normalized results."""
from backend.serpapi.client import run_search

def _src(s):
    return s.get("name") if isinstance(s, dict) else (s or "")

def search_web(query: str, **_):
    raw = run_search({"engine": "google", "q": query, "num": 10})
    out = []
    kg = raw.get("knowledge_graph")
    if kg:
        out.append({"title": kg.get("title", ""), "url": kg.get("website") or (kg.get("source") or {}).get("link", ""),
                    "source": "knowledge_graph", "snippet": (kg.get("description") or kg.get("type") or "")[:300], "date": ""})
    for r in raw.get("organic_results", [])[:10]:
        out.append({"title": r.get("title", ""), "url": r.get("link", ""), "source": r.get("displayed_link") or r.get("source", ""),
                    "snippet": (r.get("snippet") or "")[:300], "date": r.get("date", "")})
    return {"engine": "google", "results": [r for r in out if r["url"] or r["title"]]}

def search_news(query: str, **_):
    raw = run_search({"engine": "google", "q": query, "tbm": "nws", "num": 10})
    out = [{"title": r.get("title", ""), "url": r.get("link", ""), "source": _src(r.get("source")),
            "snippet": (r.get("snippet") or "")[:300], "date": r.get("date", "")}
           for r in raw.get("news_results", [])[:10]]
    return {"engine": "google (news)", "results": out}

def search_local(query: str, location: str = "", **_):
    q = f"{query} {location}".strip()
    raw = run_search({"engine": "google_maps", "q": q, "type": "search"})
    out = []
    for r in raw.get("local_results", [])[:10]:
        bits = [r.get("type", ""), r.get("address", ""), f"rating {r['rating']}" if r.get("rating") else "",
                f"{r['reviews']} reviews" if r.get("reviews") else ""]
        out.append({"title": r.get("title", ""), "url": r.get("website", "") or "", "source": "google_maps",
                    "snippet": " | ".join(b for b in bits if b), "date": ""})
    return {"engine": "google_maps", "results": out}

TOOLS = {"web": search_web, "news": search_news, "local": search_local}
TOOL_LABELS = {"web": "SerpApi → Google Search", "news": "SerpApi → Google News", "local": "SerpApi → Google Maps"}
