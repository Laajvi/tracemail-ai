import os
from dotenv import load_dotenv

load_dotenv()
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.5-flash")
DB_PATH = os.getenv("DATABASE_URL", "sqlite:///./tracemail.db").replace("sqlite:///", "")
MAX_SEARCHES = int(os.getenv("MAX_SEARCHES", "6"))
