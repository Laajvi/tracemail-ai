import hashlib, json, os, threading, uuid
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from backend.agent.agent import Investigator
from backend.models import db
from backend.serpapi.client import SerpApiFailure
from backend.services import indicators as ind
from backend.tools.search_tools import TOOLS

app = FastAPI(title="TraceMail AI")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
db.init()

class EmailIn(BaseModel):
    sender: str = ""
    subject: str = ""
    body: str

class SearchIn(BaseModel):
    tool: str = "web"
    query: str
    location: str = ""

def _validate(e: EmailIn):
    if len(e.body.strip()) < 20:
        raise HTTPException(400, "Email body is empty or too short to investigate.")
    if len(e.body) > 20000:
        raise HTTPException(400, "Email body too large (max 20,000 characters).")

@app.get("/api/health")
def health():
    from backend.config import SERPAPI_API_KEY, LLM_API_KEY
    return {"ok": True, "serpapi_configured": bool(SERPAPI_API_KEY), "llm_configured": bool(LLM_API_KEY)}

@app.get("/api/demo-email")
def demo_email():
    return json.loads((Path(__file__).resolve().parent.parent / "demo" / "demo_email.json").read_text())

@app.post("/api/analyze-email")
def analyze_email(e: EmailIn):
    _validate(e)
    return {"indicators": ind.extract(e.sender, e.subject, e.body)}

@app.post("/api/search")
def search(s: SearchIn):
    if s.tool not in TOOLS:
        raise HTTPException(400, f"Unknown tool. Use one of: {', '.join(TOOLS)}")
    try:
        return TOOLS[s.tool](query=s.query, location=s.location)
    except SerpApiFailure as ex:
        raise HTTPException(502, str(ex))

@app.post("/api/investigate")
def investigate(e: EmailIn):
    _validate(e)
    case_id = uuid.uuid4().hex[:10]
    db.create_case(case_id, e.sender, e.subject, hashlib.sha256(e.body.encode()).hexdigest())
    agent = Investigator(case_id, e.sender, e.subject, e.body)
    threading.Thread(target=agent.run, daemon=True).start()   # body lives only in memory
    return {"case_id": case_id, "status": "planning"}

def _case(case_id):
    c = db.get_case(case_id)
    if not c:
        raise HTTPException(404, "Case not found")
    return c

@app.get("/api/investigation/{case_id}")
def get_investigation(case_id: str):
    return _case(case_id)

@app.get("/api/investigation/{case_id}/timeline")
def get_timeline(case_id: str):
    c = _case(case_id)
    return {"status": c["status"], "next_action": c["next_action"], "timeline": c["timeline"]}

@app.get("/api/investigation/{case_id}/report")
def get_report(case_id: str):
    c = _case(case_id)
    if not c["report"]:
        raise HTTPException(409, f"Report not ready (status: {c['status']})")
    return c["report"]

@app.get("/api/investigation/{case_id}/search/{search_id}")
def get_search(case_id: str, search_id: int):
    s = db.get_search_results(case_id, search_id)
    if not s:
        raise HTTPException(404, "Search not found")
    return s

FRONT = Path(__file__).resolve().parent.parent / "frontend"

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(FRONT / "index.html")
