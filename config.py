"""
Configuration loader.
Reads API keys from .env, database IDs from database_ids.json.
"""

import os
import json
from dotenv import load_dotenv

load_dotenv(override=True)


# --- API Keys ---
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
PARALLEL_API_KEY = os.getenv("PARALLEL_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# --- Notion ---
LISTENING_DASHBOARD_PAGE_ID = os.getenv("LISTENING_DASHBOARD_PAGE_ID")
PRIORITIES_PAGE_ID = os.getenv("PRIORITIES_PAGE_ID")
NOTION_API_VERSION = "2022-06-28"
NOTION_BASE_URL = "https://api.notion.com/v1"

# --- Email ---
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
ESCALATION_TO_EMAIL = os.getenv("ESCALATION_TO_EMAIL")

# --- Topic ---
TOPIC = os.getenv("TOPIC", "Physical AI")

# --- Strategic Context ---
STRATEGIC_CONTEXT_DB_ID = os.getenv("STRATEGIC_CONTEXT_DB_ID", "")

# --- Search Configuration ---
SEARCH_CONFIG_PATH = os.getenv("SEARCH_CONFIG_PATH", "search_config.json")

# --- Source Quality Filtering ---
DEFAULT_EXCLUDE_DOMAINS = [
    "pinterest.com",
    "quora.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "amazon.com",
    "ebay.com",
]

_extra_excludes = os.getenv("EXTRA_EXCLUDE_DOMAINS", "")
EXTRA_EXCLUDE_DOMAINS = [d.strip() for d in _extra_excludes.split(",") if d.strip()]

EXCLUDE_DOMAINS = (DEFAULT_EXCLUDE_DOMAINS + EXTRA_EXCLUDE_DOMAINS)[:10]

# --- Recency Controls ---
PASS_B_LOOKBACK_DAYS = int(os.getenv("PASS_B_LOOKBACK_DAYS", "30"))

# --- Database IDs (loaded after setup_notion.py runs) ---
DATABASE_IDS_FILE = "database_ids.json"

def load_database_ids() -> dict:
    """Load database IDs from the auto-generated JSON file."""
    if not os.path.exists(DATABASE_IDS_FILE):
        return {}
    with open(DATABASE_IDS_FILE, "r") as f:
        return json.load(f)

def save_database_ids(ids: dict) -> None:
    """Save database IDs to the JSON file."""
    with open(DATABASE_IDS_FILE, "w") as f:
        json.dump(ids, f, indent=2)

def get_database_id(name: str) -> str:
    """
    Get a specific database ID by name.
    Valid names: 'ingestion_queue', 'main_kb', 'synthesis', 'brief_log'
    Raises ValueError if database_ids.json doesn't exist or name not found.
    """
    ids = load_database_ids()
    if not ids:
        raise ValueError(
            "database_ids.json not found. Run setup_notion.py first."
        )
    if name not in ids:
        raise ValueError(
            f"Database '{name}' not found in database_ids.json. "
            f"Available: {list(ids.keys())}"
        )
    return ids[name]


# --- State tracking ---
STATE_FILE = "state.json"

def load_state() -> dict:
    """Load pipeline state (last run timestamps, etc.)."""
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, "r") as f:
        return json.load(f)

def save_state(state: dict) -> None:
    """Save pipeline state."""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# --- Validation ---
def validate_config() -> list[str]:
    """
    Check that all required config values are set.
    Returns a list of error messages. Empty list = all good.
    """
    errors = []
    if not NOTION_API_KEY:
        errors.append("NOTION_API_KEY is not set in .env")
    if not LISTENING_DASHBOARD_PAGE_ID:
        errors.append("LISTENING_DASHBOARD_PAGE_ID is not set in .env")
    if not PARALLEL_API_KEY:
        errors.append("PARALLEL_API_KEY is not set in .env")
    if not OPENAI_API_KEY:
        errors.append("OPENAI_API_KEY is not set in .env")
    return errors