"""TraceMail investigation agent: extract -> plan -> (decide -> SerpApi tool -> observe -> analyze)* -> correlate -> report."""
import json, re, traceback
from urllib.parse import urlparse
from backend.config import MAX_SEARCHES
from backend.models import db
from backend.services import indicators as ind
from backend.services.llm import complete_json, LLMError
from backend.serpapi.client import SerpApiFailure
from backend.tools.search_tools import TOOLS, TOOL_LABELS
from backend.agent import prompts as P

def D(x, key):
    """Gemini sometimes returns a bare list instead of an object; normalise to a dict."""
    if isinstance(x, dict):
        return x
    if isinstance(x, list):
        if len(x) == 1 and isinstance(x[0], dict) and key in x[0]:
            return x[0]
        return {key: x}
    return {}

def cj(key, *a, **kw):
    return D(complete_json(*a, **kw), key)

def _j(x):
    return json.dumps(x, ensure_ascii=False)

class Investigator:
    def __init__(self, case_id, sender, subject, body):
        self.id, self.sender, self.subject, self.body = case_id, sender, subject, body
        self.n = 0
        self.indicators, self.hypotheses, self.red_flags = [], [], []
        self.searched = set()
        self.history = []   # compact observations fed back into the decision loop
        self.confidence = 0

    def step(self, phase, action, tool="", query="", reason="", result=""):
        self.n += 1
        db.update_case(self.id, status=phase.lower(), next_action=action)
        return db.add_step(self.id, self.n, phase, action, tool, query, reason, result)

    def run(self):
        try:
            self._run()
        except (LLMError, SerpApiFailure) as e:
            db.update_case(self.id, status="failed", error=str(e))
        except Exception as e:
            traceback.print_exc()
            db.update_case(self.id, status="failed", error=f"Unexpected error: {e}")

    def _email_text(self):
        return f"From: {self.sender}\nSubject: {self.subject}\n\n{self.body[:6000]}"

    def _run(self):
        # 1. Extract indicators (regex + LLM)
        sid = self.step("PLANNING", "Analyze email and extract indicators", reason="Identify what is worth investigating")
        self.indicators = ind.extract(self.sender, self.subject, self.body)
        ex = D(complete_json(P.SYSTEM, f"{P.EXTRACT}\n\nEMAIL:\n{self._email_text()}"), "indicators")
        for i in ex.get("indicators", []):
            if i.get("value"):
                self.indicators.append({"kind": i.get("kind", "other"), "value": i["value"], "note": i.get("note", "")})
        self.hypotheses = ex.get("impersonation_hypotheses", [])
        self.red_flags = ex.get("email_red_flags", [])
        for i in self.indicators:
            db.add_indicator(self.id, i["kind"], i["value"], i["note"])
        db.set_step_result(sid, f"{len(self.indicators)} indicators extracted")

        # 2. Plan
        sid = self.step("PLANNING", "Create investigation plan", reason="Decide which indicators need public-web investigation")
        plan = D(complete_json(P.SYSTEM, f"{P.PLAN}\n\nINDICATORS:\n{_j(self.indicators)}\nHYPOTHESES:\n{_j(self.hypotheses)}"), "plan").get("plan", [])
        pending = [s for s in plan if s.get("tool") in TOOLS and s.get("query")]
        db.set_step_result(sid, f"{len(pending)} investigation steps planned: " + "; ".join(s.get("goal", "") for s in pending))

        # 3. Investigation loop (bounded)
        searches_done = 0
        next_action = pending.pop(0) if pending else None
        while next_action and searches_done < MAX_SEARCHES:
            tool, query = next_action["tool"], next_action["query"].strip()
            if tool not in TOOLS or not query or query.lower() in self.searched:
                next_action = self._decide(pending, searches_done)
                continue
            self.searched.add(query.lower())
            searches_done += 1
            self._execute(tool, query, next_action.get("location", ""), next_action.get("reason") or next_action.get("goal", ""))
            if searches_done >= MAX_SEARCHES:
                break
            next_action = self._decide(pending, searches_done)

        # 4. Correlate + report
        self.step("CORRELATING", "Correlate evidence across searches", reason="Cross-check findings and assess confidence")
        evidence = db.rows("SELECT id,kind,source,title,url,query,engine,finding,relevance,supports,date FROM evidence WHERE case_id=?", (self.id,))
        searches = db.rows("SELECT id,tool,engine,query,result_count,error FROM searches WHERE case_id=?", (self.id,))
        report = cj("executive_summary", P.SYSTEM, f"{P.REPORT}\n\nINDICATORS:\n{_j(self.indicators)}\nEMAIL RED FLAGS:\n{_j(self.red_flags)}\n"
                               f"SEARCHES:\n{_j(searches)}\nEVIDENCE:\n{_j(evidence)}", max_tokens=3500)
        hosts = {urlparse(e["url"]).hostname for e in evidence if e["kind"] == "DIRECT" and e["url"]}
        cap = 85 if len(hosts) >= 2 else 55
        raw = int(report.get("confidence_pct", 0) or 0)
        conf = min(raw, cap)
        if raw > cap:  # the model's own wording would contradict the capped score, so replace it
            report["confidence_explanation"] = ("Public evidence is mostly contextual (training pages, tutorials, scanner listings), "
                                                "so the rating relies mainly on the email's own red flags.")
        report["confidence_pct"] = conf
        report["confidence_note"] = f"Confidence capped at {cap}% ({len(hosts)} independent source(s) directly reference the indicators)."
        report["searches_performed"] = len(searches)
        report["evidence_count"] = len(evidence)
        db.save_report(self.id, report)
        db.update_case(self.id, confidence=conf)
        self.step("COMPLETED", "Investigation complete", result=f"{len(searches)} SerpApi searches, {len(evidence)} evidence items")
        db.update_case(self.id, status="completed", next_action="done")

    def _decide(self, pending, done):
        """Agent decides what to do next, informed by observations. Falls back to the remaining plan."""
        d = cj("action", P.SYSTEM, f"{P.DECIDE}\n\nINDICATORS:\n{_j(self.indicators)}\nREMAINING PLAN:\n{_j(pending)}\n"
                          f"OBSERVATIONS SO FAR:\n{_j(self.history)}\nSEARCHES USED: {done}/{MAX_SEARCHES}\n"
                          f"PREVIOUS QUERIES: {_j(sorted(self.searched))}")
        if d.get("action") == "finish":
            self.step("ANALYZING", "Agent decided evidence is sufficient", reason=d.get("reason", ""))
            return None
        if d.get("tool") in TOOLS and d.get("query") and d["query"].strip().lower() not in self.searched:
            pending[:] = [p for p in pending if p.get("query", "").lower() != d["query"].strip().lower()]
            return d
        return pending.pop(0) if pending else None

    def _execute(self, tool, query, location, reason):
        label = TOOL_LABELS[tool]
        sid = self.step("INVESTIGATING", f"Investigating via {label}", tool=label, query=query, reason=reason)
        try:
            out = TOOLS[tool](query=query, location=location)
        except SerpApiFailure as e:
            db.add_search(self.id, self.n, tool, tool, query, location, [], error=str(e))
            db.set_step_result(sid, f"Search failed: {e}")
            self.history.append({"query": query, "tool": tool, "outcome": f"failed: {e}"})
            if "limit" in str(e).lower() or "not configured" in str(e).lower():
                raise
            return
        results, engine = out["results"], out["engine"]
        search_id = db.add_search(self.id, self.n, tool, engine, query, location, results)
        if not results:
            db.set_step_result(sid, "No relevant public evidence was found (search returned 0 results).")
            self.history.append({"query": query, "tool": tool, "outcome": "no results"})
            return
        self.step("ANALYZING", "Analyzing search results", tool=label, query=query, reason="Extract evidence and decide what to do next")
        numbered = [{"index": i, **{k: r[k] for k in ("title", "url", "source", "snippet", "date")}} for i, r in enumerate(results)]
        an = cj("evidence", P.SYSTEM, f"{P.ANALYZE}\n\nINDICATORS:\n{_j(self.indicators)}\nHYPOTHESES:\n{_j(self.hypotheses)}\n"
                           f"SEARCH QUERY: {query} (tool: {tool})\nRESULTS:\n{_j(numbered)}", max_tokens=3000)
        kept = 0
        for e in an.get("evidence", []):
            idx = e.get("index")
            if not isinstance(idx, int) or not (0 <= idx < len(results)):
                continue  # ungrounded reference: dropped, never fabricated
            r = results[idx]
            kind = e.get("kind") if e.get("kind") in ("DIRECT", "SUPPORTING") else "SUPPORTING"
            # Guard: DIRECT must literally mention an investigated indicator and not come from a bare-IP host
            hay = f"{r['title']} {r['snippet']} {r['url']}".lower()
            needles = [i["value"].lower() for i in self.indicators if i["kind"] in ("domain", "phone", "email")]
            host = urlparse(r["url"]).hostname or ""
            if kind == "DIRECT" and (not any(n in hay for n in needles) or re.fullmatch(r"[\d.]+", host)):
                kind = "SUPPORTING"
            db.add_evidence(self.id, search_id, {"kind": kind, "source": r["source"], "title": r["title"], "url": r["url"],
                            "query": query, "engine": engine, "finding": e.get("finding", ""), "relevance": e.get("relevance", ""),
                            "supports": e.get("supports", ""), "snippet": r["snippet"], "date": r["date"]})
            kept += 1
        if an.get("no_relevant_evidence") or kept == 0:
            summary = "No relevant public evidence was found in these results."
        else:
            summary = an.get("summary", "")
        self.confidence = int(an.get("confidence_that_email_is_malicious", self.confidence) or 0)
        db.update_case(self.id, confidence=self.confidence)
        db.set_step_result(sid, f"{len(results)} results returned, {kept} relevant. {summary}")
        self.history.append({"query": query, "tool": tool, "outcome": summary, "relevant": kept, "total": len(results)})