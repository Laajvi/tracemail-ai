"""LLM service (Google Gemini). Returns parsed JSON; retries on free-tier rate limits."""
import json, re, time
from google import genai
from google.genai import types
from backend.config import LLM_API_KEY, LLM_MODEL

class LLMError(Exception):
    pass

def complete_json(system: str, user: str, max_tokens: int = 2500):
    if not LLM_API_KEY:
        raise LLMError("LLM_API_KEY is not configured.")
    client = genai.Client(api_key=LLM_API_KEY)
    cfg = types.GenerateContentConfig(system_instruction=system, response_mime_type="application/json",
                                      max_output_tokens=max(max_tokens, 4096), temperature=0.2)
    text, last = "", None
    for attempt in range(4):
        try:
            resp = client.models.generate_content(model=LLM_MODEL, contents=user, config=cfg)
            text = resp.text or ""
            break
        except Exception as e:
            last = str(e)
            if "429" in last or "RESOURCE_EXHAUSTED" in last or "503" in last:
                time.sleep(15 * (attempt + 1))   # free-tier rate limit: wait and retry
                continue
            raise LLMError(f"LLM request failed: {last}")
    else:
        raise LLMError(f"LLM rate limit persisted after retries: {last}")
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        raise LLMError("LLM returned malformed JSON.")
