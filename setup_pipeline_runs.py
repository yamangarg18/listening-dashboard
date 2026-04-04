"""
One-time setup script for Pipeline Runs database.
Creates the database under the Listening Dashboard page.
Saves the database ID to database_ids.json.

Usage:
    python setup_pipeline_runs.py
"""

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import (
    NOTION_API_KEY,
    NOTION_API_VERSION,
    NOTION_BASE_URL,
    get_database_id,
    load_database_ids,
    save_database_ids,
    DATABASE_IDS_FILE,
    LISTENING_DASHBOARD_PAGE_ID,
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
    print(f"  Created: {title} ({database_id})")
    return database_id


def build_pipeline_runs_properties() -> dict:
    """Build properties for Pipeline Runs database (15 properties)."""
    return {
        "Run Title": {"title": {}},
        "Run Type": {
            "select": {
                "options": [
                    {"name": "Cycle 1", "color": "blue"},
                    {"name": "Cycle 2", "color": "green"},
                    {"name": "Cycle 3", "color": "yellow"},
                    {"name": "Cycle 4", "color": "orange"},
                    {"name": "Daily Brief", "color": "purple"},
                ]
            }
        },
        "Run Date": {"date": {}},
        "Pass A Results": {"number": {"format": "number"}},
        "Pass B Results": {"number": {"format": "number"}},
        "After Dedup": {"number": {"format": "number"}},
        "DB Duplicates": {"number": {"format": "number"}},
        "New In Queue": {"number": {"format": "number"}},
        "Analyzed": {"number": {"format": "number"}},
        "New In KB": {"number": {"format": "number"}},
        "Updated In KB": {"number": {"format": "number"}},
        "Escalations Sent": {"number": {"format": "number"}},
        "Errors": {"rich_text": {}},
        "Status": {
            "select": {
                "options": [
                    {"name": "Success", "color": "green"},
                    {"name": "Failed", "color": "red"},
                ]
            }
        },
        "Duration Seconds": {"number": {"format": "number"}},
    }


def main():
    print("=== Pipeline Runs Database Setup ===\n")

    if not LISTENING_DASHBOARD_PAGE_ID:
        print("Error: LISTENING_DASHBOARD_PAGE_ID is not set in .env")
        return

    if not NOTION_API_KEY:
        print("Error: NOTION_API_KEY is not set in .env")
        return

    print(f"Using parent page ID: {LISTENING_DASHBOARD_PAGE_ID}\n")

    existing_ids = load_database_ids()
    if "pipeline_runs" in existing_ids:
        print(f"Warning: pipeline_runs already exists in {DATABASE_IDS_FILE}.")
        print(f"  Existing ID: {existing_ids['pipeline_runs']}")
        response = input("Recreate? (yes/no): ")
        if response.lower() != "yes":
            print("Aborted.")
            return
        print()

    print("Creating Pipeline Runs database...")
    pipeline_runs_id = create_database(
        LISTENING_DASHBOARD_PAGE_ID,
        "Pipeline Runs",
        build_pipeline_runs_properties(),
    )

    database_ids = load_database_ids()
    database_ids["pipeline_runs"] = pipeline_runs_id
    save_database_ids(database_ids)

    print()
    print("=== Setup Complete ===")
    print(f"Database ID saved to {DATABASE_IDS_FILE}")
    print(f"  pipeline_runs: {pipeline_runs_id}")


if __name__ == "__main__":
    main()