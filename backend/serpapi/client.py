"""Thin wrapper over the official SerpApi Python client. Every call is a real network request."""
import serpapi
from backend.config import SERPAPI_API_KEY

class SerpApiFailure(Exception):
    pass

def run_search(params: dict) -> dict:
    if not SERPAPI_API_KEY:
        raise SerpApiFailure("SERPAPI_API_KEY is not configured.")
    try:
        client = serpapi.Client(api_key=SERPAPI_API_KEY)
        return dict(client.search(params))
    except Exception as e:  # rate limits, invalid key, network errors all surface here
        msg = str(e)
        if "429" in msg or "rate" in msg.lower() or "limit" in msg.lower():
            raise SerpApiFailure(f"SerpApi rate/plan limit reached: {msg}")
        raise SerpApiFailure(f"SerpApi request failed: {msg}")
