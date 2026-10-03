# TraceMail AI
**Autonomous Cybersecurity Email Investigation Agent Powered by SerpApi** — SerpApi India Hackathon 2026, Track 1 (AI Agents)

Paste a suspicious email. TraceMail extracts indicators, plans an investigation, and autonomously runs live SerpApi searches
(Google Search, Google News, Google Maps), reading each result before deciding what to search next, then correlates the
evidence into an explainable report. It is not a verdict engine: every finding links to the search result that supports it.

## How the agent works
1. **Extract**: regex (emails, URLs, domains, phones) + LLM (organizations, brands, claims, impersonation hypotheses).
2. **Plan**: the LLM picks which indicators to investigate and which tool fits (web / news / local).
3. **Loop** (max `MAX_SEARCHES`): execute a SerpApi tool → normalize results → LLM classifies evidence (DIRECT / SUPPORTING; unrelated dropped) → LLM decides the next search or finishes. Duplicate queries are blocked.
4. **Correlate + report**: risk level, impersonation analysis, confidence, limitations, recommended verification steps.

**Grounding:** the LLM only references results by index; titles, URLs and sources are copied from the real SerpApi response, and
out-of-range references are discarded. Zero results are reported as "No relevant public evidence was found."

## How SerpApi is used
| Agent tool | SerpApi call | Used for |
|---|---|---|
| `search_web` | `engine=google` | domain/brand presence, legitimate-vs-lookalike comparison |
| `search_news` | `engine=google, tbm=nws` | recent scam reports / incidents |
| `search_local` | `engine=google_maps` | verifying a claimed physical business/address |

## Setup
```bash
cp .env.example .env        # add SERPAPI_API_KEY and LLM_API_KEY (Gemini key from aistudio.google.com)
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --port 8000   # run from the repo root
```
**Open the dashboard:** http://localhost:8000 (served by FastAPI, no Node needed). Click *View Demo Case*.

API quick test (demo email): 
```bash
curl localhost:8000/api/demo-email | curl -X POST localhost:8000/api/investigate -H 'content-type: application/json' -d @-
curl localhost:8000/api/investigation/<case_id>   # poll: timeline, evidence, report
```

## API
`POST /api/investigate` · `POST /api/analyze-email` · `POST /api/search` · `GET /api/investigation/{id}` · `/timeline` · `/report` · `/search/{search_id}` · `GET /api/demo-email` · `GET /api/health`

## Privacy & safety
Raw email bodies are processed in memory and never stored (only a hash, sender, subject, indicators). Defensive use only.
Secrets come from environment variables.

## AI tools used
Google Gemini for agent reasoning at runtime; Claude (Anthropic) for AI-assisted development.

## Limitations
Search-based public evidence only; new or obscure domains may have no public footprint. Output is decision support, not a guaranteed verdict.
