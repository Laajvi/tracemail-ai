"""Deterministic indicator extraction (regex). The agent's LLM pass adds semantic indicators on top."""
import re
from urllib.parse import urlparse

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.I)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?)\d{3,4}[\s.-]?\d{3,4}(?!\d)")

def extract(sender: str, subject: str, body: str):
    text = f"{sender}\n{subject}\n{body}"
    out, seen = [], set()
    def add(kind, value, note=""):
        key = (kind, value.lower())
        if value and key not in seen:
            seen.add(key)
            out.append({"kind": kind, "value": value, "note": note})
    for e in EMAIL_RE.findall(text):
        add("email", e.lower())
        add("domain", e.split("@")[1].lower(), "email domain")
    for u in URL_RE.findall(text):
        u = u.rstrip(".,;")
        add("url", u)
        host = urlparse(u).hostname
        if host:
            add("domain", host.lower(), "url host")
    for p in PHONE_RE.findall(body or ""):
        digits = re.sub(r"\D", "", p)
        if 9 <= len(digits) <= 14:
            add("phone", p.strip())
    return out
