"""
One-time setup script.
Creates all 4 Notion databases under the Listening Dashboard page.
Saves database IDs to database_ids.json.

Usage:
    python setup_notion.py

Prerequisites:
    - .env file with NOTION_API_KEY and LISTENING_DASHBOARD_PAGE_ID
    - The Listening Dashboard page must be shared with the integration
"""

import httpx
import time
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import (
    NOTION_API_KEY,
    NOTION_API_VERSION,
    NOTION_BASE_URL,
    get_database_id,
    load_database_ids,
    save_database_ids,
    DATABASE_IDS_FILE,
)


HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": NOTION_API_VERSION,
}


@retry(
    retry=retry_if_exception_type(httpx.HTTPStatusError),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    reraise=True,
)
def _make_request(client: httpx.Client, method: str, url: str, **kwargs) -> httpx.Response:
    """Make HTTP request with retry on 429 rate limit."""
    response = client.request(method, url, **kwargs)
    if response.status_code == 429:
        raise httpx.HTTPStatusError(
            "Rate limited",
            request=response.request,
            response=response,
        )
    return response


def create_database(page_id: str, title: str, properties: dict) -> str:
    """Create a database and return its ID."""
    client = httpx.Client(base_url=NOTION_BASE_URL, headers=HEADERS, timeout=30.0)

    payload = {
        "parent": {
            "type": "page_id",
            "page_id": page_id,
        },
        "title": [
            {
                "type": "text",
                "text": {
                    "content": title,
                },
            }
        ],
        "properties": properties,
    }

    response = _make_request(client, "POST", "/databases", json=payload)

    if response.status_code != 200:
        error_body = response.json()
        error_code = error_body.get("code", "unknown")
        error_message = error_body.get("message", "No message")
        raise Exception(
            f"Notion API error {response.status_code}: [{error_code}] {error_message}"
        )

    database_id = response.json()["id"]
    print(f"  ✓ Created: {title} ({database_id})")
    return database_id


def update_database(database_id: str, properties: dict) -> None:
    """Update a database to add new properties."""
    client = httpx.Client(base_url=NOTION_BASE_URL, headers=HEADERS, timeout=30.0)

    payload = {
        "properties": properties,
    }

    response = _make_request(client, "PATCH", f"/databases/{database_id}", json=payload)

    if response.status_code != 200:
        error_body = response.json()
        error_code = error_body.get("code", "unknown")
        error_message = error_body.get("message", "No message")
        raise Exception(
            f"Notion API error {response.status_code}: [{error_code}] {error_message}"
        )

    print(f"  ✓ Updated database: {database_id}")


def build_main_kb_properties() -> dict:
    """Build properties for Main Knowledge Base (27 properties)."""
    return {
        "Title": {"title": {}},
        "URL": {"url": {}},
        "Source Name": {
            "select": {
                "options": [
                    {"name": "Reuters", "color": "blue"},
                    {"name": "Bloomberg", "color": "green"},
                    {"name": "TechCrunch", "color": "purple"},
                    {"name": "Economic Times", "color": "yellow"},
                    {"name": "SCMP", "color": "pink"},
                    {"name": "arXiv", "color": "orange"},
                    {"name": "LinkedIn", "color": "gray"},
                    {"name": "X", "color": "red"},
                    {"name": "Reddit", "color": "brown"},
                    {"name": "Hacker News", "color": "default"},
                    {"name": "Other", "color": "gray"},
                ]
            }
        },
        "Source Type": {
            "select": {
                "options": [
                    {"name": "News", "color": "blue"},
                    {"name": "Blog", "color": "green"},
                    {"name": "Academic", "color": "purple"},
                    {"name": "Social Media", "color": "pink"},
                    {"name": "Forum", "color": "orange"},
                    {"name": "Government", "color": "red"},
                    {"name": "Other", "color": "gray"},
                ]
            }
        },
        "Author": {"rich_text": {}},
        "Published Date": {"date": {}},
        "Discovered Date": {"date": {}},
        "Last Updated": {"date": {}},
        "Retrieval Method": {
            "select": {
                "options": [
                    {"name": "Time-window", "color": "blue"},
                    {"name": "Relevance-ranked", "color": "green"},
                    {"name": "Both", "color": "yellow"},
                ]
            }
        },
        "Search Cycle": {
            "select": {
                "options": [
                    {"name": "1", "color": "blue"},
                    {"name": "2", "color": "green"},
                    {"name": "3", "color": "yellow"},
                    {"name": "4", "color": "orange"},
                ]
            }
        },
        "Raw Summary": {"rich_text": {}},
        "One-Line Summary": {"rich_text": {}},
        "Why It Matters": {"rich_text": {}},
        "Key Entities": {"multi_select": {"options": []}},
        "Topic Tags": {"multi_select": {"options": []}},
        "Signal Level": {
            "select": {
                "options": [
                    {"name": "High", "color": "red"},
                    {"name": "Medium", "color": "yellow"},
                    {"name": "Low", "color": "green"},
                ]
            }
        },
        "Confidence Score": {"number": {"format": "number"}},
        "Category": {
            "select": {
                "options": [
                    {"name": "Competitor Move", "color": "red"},
                    {"name": "Policy Change", "color": "orange"},
                    {"name": "Research", "color": "purple"},
                    {"name": "Funding", "color": "green"},
                    {"name": "Partnership", "color": "blue"},
                    {"name": "Discourse", "color": "yellow"},
                    {"name": "Other", "color": "gray"},
                ]
            }
        },
        "Framework Mapping": {
            "multi_select": {
                "options": [
                    {"name": "Four Schools", "color": "blue"},
                    {"name": "GTM", "color": "green"},
                    {"name": "Tech Stack", "color": "purple"},
                    {"name": "Taxonomy", "color": "orange"},
                    {"name": "Policy", "color": "red"},
                    {"name": "Academic", "color": "yellow"},
                    {"name": "Industry Vertical", "color": "gray"},
                ]
            }
        },
        "Priority Score": {"number": {"format": "number"}},
        "Decay Status": {
            "select": {
                "options": [
                    {"name": "Active", "color": "green"},
                    {"name": "Aging", "color": "yellow"},
                    {"name": "Archived", "color": "gray"},
                ]
            }
        },
        "Half-Life Class": {
            "select": {
                "options": [
                    {"name": "Policy", "color": "red"},
                    {"name": "Research", "color": "purple"},
                    {"name": "Funding", "color": "green"},
                    {"name": "Partnership", "color": "blue"},
                    {"name": "Discourse", "color": "yellow"},
                ]
            }
        },
        "Seen By User": {"checkbox": {}},
        "Archived Summary": {"rich_text": {}},
        "Change Log": {"rich_text": {}},
        "Dedup Status": {
            "select": {
                "options": [
                    {"name": "New", "color": "green"},
                    {"name": "Updated", "color": "yellow"},
                    {"name": "Duplicate", "color": "gray"},
                ]
            }
        },
        "Extract Content": {"checkbox": {}},
        "Full Content": {"rich_text": {}},
    }


def build_synthesis_properties(main_kb_id: str) -> dict:
    """Build properties for Synthesis Database (6 properties)."""
    return {
        "Synthesis Title": {"title": {}},
        "Linked Entries": {
            "relation": {
                "database_id": main_kb_id,
                "single_property": {},
            }
        },
        "Inference": {"rich_text": {}},
        "Generated Date": {"date": {}},
        "Relevance Window": {
            "select": {
                "options": [
                    {"name": "1 Week", "color": "blue"},
                    {"name": "2 Weeks", "color": "green"},
                    {"name": "1 Month", "color": "yellow"},
                    {"name": "Ongoing", "color": "purple"},
                ]
            }
        },
    }


def build_brief_log_properties(main_kb_id: str, synthesis_id: str) -> dict:
    """Build properties for Brief Log (7 properties)."""
    return {
        "Brief Title": {"title": {}},
        "Brief Date": {"date": {}},
        "Executive Summary": {"rich_text": {}},
        "Entries Surfaced": {
            "relation": {
                "database_id": main_kb_id,
                "single_property": {},
            }
        },
        "Syntheses Surfaced": {
            "relation": {
                "database_id": synthesis_id,
                "single_property": {},
            }
        },
        "Entries Archived": {
            "relation": {
                "database_id": main_kb_id,
                "single_property": {},
            }
        },
        "Delivered At": {"date": {}},
    }


def build_ingestion_queue_properties() -> dict:
    """Build properties for Ingestion Queue (8 properties)."""
    return {
        "Title": {"title": {}},
        "URL": {"url": {}},
        "Source Name": {"rich_text": {}},
        "Published Date": {"date": {}},
        "Discovered Date": {"date": {}},
        "Raw Summary": {"rich_text": {}},
        "Retrieval Method": {
            "select": {
                "options": [
                    {"name": "Time-window", "color": "blue"},
                    {"name": "Relevance-ranked", "color": "green"},
                    {"name": "Both", "color": "yellow"},
                ]
            }
        },
        "Search Cycle": {
            "select": {
                "options": [
                    {"name": "1", "color": "blue"},
                    {"name": "2", "color": "green"},
                    {"name": "3", "color": "yellow"},
                    {"name": "4", "color": "orange"},
                ]
            }
        },
    }


def validate_config() -> list[str]:
    """Check that required config values are set for setup."""
    errors = []
    if not NOTION_API_KEY:
        errors.append("NOTION_API_KEY is not set in .env")
    if not NOTION_BASE_URL:
        errors.append("LISTENING_DASHBOARD_PAGE_ID is not set in .env")
    return errors


def main():
    print("=== Notion Database Setup ===\n")

    errors = validate_config()
    if errors:
        for error in errors:
            print(f"Config error: {error}")
        return

    from config import LISTENING_DASHBOARD_PAGE_ID

    page_id = LISTENING_DASHBOARD_PAGE_ID
    if not page_id:
        print("Error: LISTENING_DASHBOARD_PAGE_ID is not set in .env")
        return

    print(f"Using parent page ID: {page_id}\n")

    existing_ids = load_database_ids()
    if existing_ids:
        print(f"Warning: {DATABASE_IDS_FILE} already exists.")
        print("Existing database IDs:")
        for name, db_id in existing_ids.items():
            print(f"  {name}: {db_id}")
        print()
        response = input("Database IDs already exist. Delete and recreate? (yes/no): ")
        if response.lower() != "yes":
            print("Aborted.")
            return
        print()

    print("Creating databases...")
    print()

    time.sleep(0.35)

    main_kb_id = create_database(
        page_id, "Main Knowledge Base", build_main_kb_properties()
    )
    time.sleep(0.35)

    synthesis_id = create_database(
        page_id, "Synthesis Database", build_synthesis_properties(main_kb_id)
    )
    time.sleep(0.35)

    brief_log_id = create_database(
        page_id, "Brief Log", build_brief_log_properties(main_kb_id, synthesis_id)
    )
    time.sleep(0.35)

    update_database(synthesis_id, {
        "Surfaced In Brief": {
            "relation": {
                "database_id": brief_log_id,
                "single_property": {},
            }
        }
    })
    time.sleep(0.35)

    ingestion_queue_id = create_database(
        page_id, "Ingestion Queue", build_ingestion_queue_properties()
    )

    database_ids = {
        "main_kb": main_kb_id,
        "synthesis": synthesis_id,
        "brief_log": brief_log_id,
        "ingestion_queue": ingestion_queue_id,
    }

    save_database_ids(database_ids)

    print()
    print("=== Setup Complete ===")
    print(f"Database IDs saved to {DATABASE_IDS_FILE}")
    print()
    print("Database IDs:")
    for name, db_id in database_ids.items():
        print(f"  {name}: {db_id}")


if __name__ == "__main__":
    main()