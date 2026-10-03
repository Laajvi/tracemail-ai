"""SQLite persistence: cases, indicators, searches, evidence, agent_steps, reports.
Raw email bodies are never stored, only a hash, the sender and the subject."""
import json, sqlite3, threading, time
from backend.config import DB_PATH

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY, status TEXT, sender TEXT, subject TEXT,
  body_hash TEXT, confidence INTEGER DEFAULT 0, next_action TEXT, error TEXT, created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS indicators(id INTEGER PRIMARY KEY, case_id TEXT, kind TEXT, value TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS searches(id INTEGER PRIMARY KEY, case_id TEXT, step INTEGER, tool TEXT, engine TEXT,
  query TEXT, location TEXT, result_count INTEGER, results TEXT, error TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS evidence(id INTEGER PRIMARY KEY, case_id TEXT, search_id INTEGER, kind TEXT, source TEXT,
  title TEXT, url TEXT, query TEXT, engine TEXT, finding TEXT, relevance TEXT, supports TEXT, snippet TEXT, date TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS agent_steps(id INTEGER PRIMARY KEY, case_id TEXT, step INTEGER, phase TEXT, action TEXT,
  tool TEXT, query TEXT, reason TEXT, result TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS reports(case_id TEXT PRIMARY KEY, report TEXT, ts REAL);
"""

def _conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def init():
    with _lock:
        c = _conn()
        c.executescript(SCHEMA)
        c.commit()
        c.close()

def run(sql, args=()):
    with _lock:
        c = _conn()
        cur = c.execute(sql, args)
        c.commit()
        last = cur.lastrowid
        c.close()
        return last

def rows(sql, args=()):
    with _lock:
        c = _conn()
        out = [dict(r) for r in c.execute(sql, args).fetchall()]
        c.close()
        return out

def create_case(case_id, sender, subject, body_hash):
    now = time.time()
    run("INSERT INTO cases(id,status,sender,subject,body_hash,created,updated) VALUES(?,?,?,?,?,?,?)",
        (case_id, "planning", sender, subject, body_hash, now, now))

def update_case(case_id, **kw):
    kw["updated"] = time.time()
    cols = ",".join(f"{k}=?" for k in kw)
    run(f"UPDATE cases SET {cols} WHERE id=?", (*kw.values(), case_id))

def add_indicator(case_id, kind, value, note=""):
    run("INSERT INTO indicators(case_id,kind,value,note) VALUES(?,?,?,?)", (case_id, kind, value, note))

def add_step(case_id, step, phase, action, tool="", query="", reason="", result=""):
    return run("INSERT INTO agent_steps(case_id,step,phase,action,tool,query,reason,result,ts) VALUES(?,?,?,?,?,?,?,?,?)",
               (case_id, step, phase, action, tool, query, reason, result, time.time()))

def set_step_result(step_id, result):
    run("UPDATE agent_steps SET result=? WHERE id=?", (result, step_id))

def add_search(case_id, step, tool, engine, query, location, results, error=None):
    return run("INSERT INTO searches(case_id,step,tool,engine,query,location,result_count,results,error,ts) VALUES(?,?,?,?,?,?,?,?,?,?)",
               (case_id, step, tool, engine, query, location, len(results), json.dumps(results), error, time.time()))

def add_evidence(case_id, search_id, e):
    return run("""INSERT INTO evidence(case_id,search_id,kind,source,title,url,query,engine,finding,relevance,supports,snippet,date,ts)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
               (case_id, search_id, e["kind"], e["source"], e["title"], e["url"], e["query"], e["engine"],
                e["finding"], e["relevance"], e["supports"], e.get("snippet", ""), e.get("date", ""), time.time()))

def save_report(case_id, report):
    run("INSERT OR REPLACE INTO reports(case_id,report,ts) VALUES(?,?,?)", (case_id, json.dumps(report), time.time()))

def get_case(case_id):
    r = rows("SELECT * FROM cases WHERE id=?", (case_id,))
    if not r:
        return None
    case = r[0]
    case["indicators"] = rows("SELECT kind,value,note FROM indicators WHERE case_id=?", (case_id,))
    case["searches"] = rows("SELECT id,step,tool,engine,query,location,result_count,error,ts FROM searches WHERE case_id=? ORDER BY id", (case_id,))
    case["evidence"] = rows("SELECT * FROM evidence WHERE case_id=? ORDER BY id", (case_id,))
    case["timeline"] = rows("SELECT * FROM agent_steps WHERE case_id=? ORDER BY id", (case_id,))
    rep = rows("SELECT report FROM reports WHERE case_id=?", (case_id,))
    case["report"] = json.loads(rep[0]["report"]) if rep else None
    return case

def get_search_results(case_id, search_id):
    r = rows("SELECT * FROM searches WHERE case_id=? AND id=?", (case_id, search_id))
    if r:
        r[0]["results"] = json.loads(r[0]["results"] or "[]")
        return r[0]
    return None
