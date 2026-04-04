"""
Notion API wrapper.
Functions for reading, writing, updating Notion pages and databases.
Implemented in Chunks 2-5.
"""

import httpx
import time
from typing import Optional, Dict, List
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from config import NOTION_API_KEY, NOTION_API_VERSION, NOTION_BASE_URL
from logger import setup_logger

logger = setup_logger("notion_client")


def _get_client() -> httpx.Client:
    """Return a configured httpx client for Notion API calls."""
    return httpx.Client(
        base_url=NOTION_BASE_URL,
        headers={
            "Authorization": f"Bearer {NOTION_API_KEY}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_API_VERSION,
        },
        timeout=30.0,
    )


def _handle_response(response: httpx.Response) -> dict:
    """
    Check response status. Return JSON body on success.
    Raise exception with details on failure.
    """
    if response.status_code == 200:
        return response.json()

    error_body = response.json()
    error_code = error_body.get("code", "unknown")
    error_message = error_body.get("message", "No message")

    raise httpx.HTTPStatusError(
        f"Notion API error {response.status_code}: "
        f"[{error_code}] {error_message}",
        request=response.request,
        response=response,
    )


def _format_rich_text(text: str) -> list:
    """
    Convert a plain string to Notion rich text array format.
    Splits into chunks of 2000 characters if needed.
    
    Args:
        text: Plain string to format
        
    Returns:
        List of rich text objects ready for Notion API
    """
    if not text:
        return []
    
    chunks = []
    for i in range(0, len(text), 2000):
        chunks.append({
            "type": "text",
            "text": {"content": text[i:i+2000]}
        })
    return chunks


def build_page_properties(
    title: str,
    url: Optional[str] = None,
    rich_text_fields: Optional[Dict[str, str]] = None,
    select_fields: Optional[Dict[str, str]] = None,
    multi_select_fields: Optional[Dict[str, List[str]]] = None,
    date_fields: Optional[Dict[str, str]] = None,
    number_fields: Optional[Dict[str, float]] = None,
    checkbox_fields: Optional[Dict[str, bool]] = None,
    relation_fields: Optional[Dict[str, List[str]]] = None,
    title_property_name: str = "Title",
) -> dict:
    """
    Build a Notion-formatted properties dict from simple Python values.
    
    Args:
        title: The page title (required)
        url: URL value for the "URL" property
        rich_text_fields: {"Property Name": "text content", ...}
        select_fields: {"Property Name": "Option Name", ...}
        multi_select_fields: {"Property Name": ["Tag1", "Tag2"], ...}
        date_fields: {"Property Name": "2026-04-03", ...}  (ISO 8601)
        number_fields: {"Property Name": 0.85, ...}
        checkbox_fields: {"Property Name": True, ...}
        relation_fields: {"Property Name": ["page-id-1", "page-id-2"], ...}
        title_property_name: Name of the title property (default "Title",
                            but some databases use different names like 
                            "Entry Title" or "Brief Title")
    
    Returns:
        Dict ready to pass to create_page() as the properties argument.
    
    Example:
        props = build_page_properties(
            title="New research paper on robotics",
            url="https://arxiv.org/abs/2026.12345",
            rich_text_fields={
                "One-Line Summary": "A new approach to...",
                "Why It Matters": "This could impact...",
            },
            select_fields={
                "Signal Level": "High",
                "Category": "Research",
            },
            multi_select_fields={
                "Topic Tags": ["Robotics", "AI"],
                "Key Entities": ["Boston Dynamics", "MIT"],
            },
            date_fields={
                "Published Date": "2026-04-03",
                "Discovered Date": "2026-04-03T14:30:00+05:30",
            },
            number_fields={"Confidence Score": 0.92},
            checkbox_fields={"Seen By User": False},
        )
        page_id = create_page(database_id, props)
    """
    properties = {}

    properties[title_property_name] = {
        "title": _format_rich_text(title)
    }

    if url is not None:
        properties["URL"] = {"url": url}

    if rich_text_fields:
        for key, value in rich_text_fields.items():
            properties[key] = {"rich_text": _format_rich_text(value)}

    if select_fields:
        for key, value in select_fields.items():
            properties[key] = {"select": {"name": value}}

    if multi_select_fields:
        for key, values in multi_select_fields.items():
            properties[key] = {"multi_select": [{"name": v} for v in values]}

    if date_fields:
        for key, value in date_fields.items():
            if value is not None:
                properties[key] = {"date": {"start": value}}

    if number_fields:
        for key, value in number_fields.items():
            properties[key] = {"number": value}

    if checkbox_fields:
        for key, value in checkbox_fields.items():
            properties[key] = {"checkbox": value}

    if relation_fields:
        for key, values in relation_fields.items():
            properties[key] = {"relation": [{"id": v} for v in values]}

    return properties


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception(lambda e: isinstance(e, httpx.HTTPStatusError) and (e.response.status_code == 429 or 500 <= e.response.status_code < 600)),
    reraise=True,
)
def create_page(database_id: str, properties: dict) -> str:
    """
    Create a new page in a Notion database.
    
    Args:
        database_id: UUID of the target database
        properties: Dict of property names to property value objects.
                    Values must be in Notion API format (see property 
                    value formats in CHUNK_02 spec).
    
    Returns:
        The page ID (UUID string) of the created page.
    
    Raises:
        Exception: If the Notion API returns an error.
    """
    client = _get_client()

    payload = {
        "parent": {
            "database_id": database_id
        },
        "properties": properties,
    }

    response = client.post("/pages", json=payload)
    result = _handle_response(response)

    title = ""
    if "Title" in result.get("properties", {}):
        title_texts = result["properties"]["Title"].get("title", [])
        if title_texts:
            title = title_texts[0]["plain_text"]

    page_id = result["id"]
    logger.info(f"Created page: '{title}' ({page_id})")

    return page_id


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception(lambda e: isinstance(e, httpx.HTTPStatusError) and (e.response.status_code == 429 or 500 <= e.response.status_code < 600)),
    reraise=True,
)
def update_page(page_id: str, properties: dict) -> dict:
    """
    Update properties on an existing Notion page.
    
    Only the properties included in the dict are modified.
    All other properties remain unchanged.
    
    Args:
        page_id: UUID of the page to update
        properties: Dict of property names to property value objects.
                    Same format as create_page() properties.
                    Use build_page_properties() to build this dict,
                    or pass raw Notion-formatted properties.
    
    Returns:
        The updated page object (full Notion API response dict).
    
    Raises:
        Exception: If the Notion API returns an error.
    
    Example:
        # Update signal level and add to change log
        update_page(page_id, build_page_properties(
            title="Updated Title",  # title can be updated too
            select_fields={"Signal Level": "High"},
            rich_text_fields={"Change Log": "Upgraded from Medium to High based on 3 new confirmations."},
            number_fields={"Priority Score": 95},
        ))
        
        # Clear a date field
        update_page(page_id, {"Last Updated": {"date": None}})
        
        # Mark as seen
        update_page(page_id, {"Seen By User": {"checkbox": True}})
    """
    client = _get_client()

    payload = {
        "properties": properties,
    }

    response = client.patch(f"/pages/{page_id}", json=payload)
    result = _handle_response(response)

    logger.info(f"Updated page: {page_id} ({len(properties)} properties changed)")
    return result


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception(lambda e: isinstance(e, httpx.HTTPStatusError) and (e.response.status_code == 429 or 500 <= e.response.status_code < 600)),
    reraise=True,
)
def archive_page(page_id: str) -> dict:
    """
    Archive (soft-delete) a Notion page.
    Moves the page to Notion's trash.
    
    Args:
        page_id: UUID of the page to archive
    
    Returns:
        The updated page object with archived=True.
    
    Raises:
        Exception: If the Notion API returns an error.
    """
    client = _get_client()

    payload = {"archived": True}

    response = client.patch(f"/pages/{page_id}", json=payload)
    result = _handle_response(response)

    logger.info(f"Archived page: {page_id}")
    return result


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception(lambda e: isinstance(e, httpx.HTTPStatusError) and (e.response.status_code == 429 or 500 <= e.response.status_code < 600)),
    reraise=True,
)
def read_page_content(page_id: str) -> str:
    """
    Read the text content of a Notion page.
    
    Retrieves all blocks from the page and extracts their text content
    into a single plain-text string. Headings are prefixed with '#'.
    List items are prefixed with '- ' or '1. '.
    
    This is used to read the "Current Priorities" document for Stage 3.
    
    Args:
        page_id: UUID of the page to read
    
    Returns:
        Plain text string of the page content. Blocks are separated
        by newlines. Empty blocks are skipped.
        Returns empty string if the page has no content.
    
    Raises:
        Exception: If the Notion API returns an error.
    """
    client = _get_client()
    all_blocks = []
    cursor = None

    while True:
        url = f"/blocks/{page_id}/children?page_size=100"
        if cursor:
            url += f"&start_cursor={cursor}"

        response = client.get(url)
        result = _handle_response(response)

        all_blocks.extend(result.get("results", []))

        if result.get("has_more", False):
            cursor = result.get("next_cursor")
            time.sleep(0.35)
        else:
            break

    lines = []
    for block in all_blocks:
        block_type = block.get("type", "")
        block_data = block.get(block_type, {})

        rich_text = block_data.get("rich_text")
        if rich_text is not None and len(rich_text) > 0:
            text = "".join([t.get("plain_text", "") for t in rich_text])
            if not text.strip():
                continue

            if block_type == "heading_1":
                lines.append(f"# {text}")
            elif block_type == "heading_2":
                lines.append(f"## {text}")
            elif block_type == "heading_3":
                lines.append(f"### {text}")
            elif block_type == "paragraph":
                lines.append(text)
            elif block_type == "bulleted_list_item":
                lines.append(f"- {text}")
            elif block_type == "numbered_list_item":
                lines.append(f"- {text}")
            elif block_type == "to_do":
                checked = block_data.get("checked", False)
                prefix = "[x] " if checked else "[ ] "
                lines.append(f"{prefix}{text}")
            elif block_type == "quote":
                lines.append(f"> {text}")
            elif block_type == "callout":
                lines.append(text)
            elif block_type == "code":
                lines.append(f"`{text}`")
            else:
                lines.append(text)
        elif block_type == "divider":
            lines.append("---")

    content = "\n".join(lines)
    logger.info(f"Read page {page_id}: {len(all_blocks)} blocks")
    return content.strip()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception(lambda e: isinstance(e, httpx.HTTPStatusError) and (e.response.status_code == 429 or 500 <= e.response.status_code < 600)),
    reraise=True,
)
def query_database(
    database_id: str,
    filter: Optional[Dict] = None,
    sorts: Optional[List] = None,
    page_size: int = 100,
) -> List[dict]:
    """
    Query a Notion database with optional filters and sorting.
    Automatically handles pagination — returns ALL matching pages.
    
    Args:
        database_id: UUID of the database to query
        filter: Notion filter object (see filter reference).
                None = return all pages.
        sorts: List of sort objects (see sort reference).
               None = no guaranteed order.
        page_size: Results per API call (1-100, default 100).
                   Always use 100 unless testing.
    
    Returns:
        List of page objects. Each page object is the raw Notion API 
        response dict with 'id', 'properties', 'created_time', etc.
        Returns empty list if no pages match.
    
    Raises:
        Exception: If the Notion API returns an error.
    """
    client = _get_client()
    all_results = []
    cursor = None

    while True:
        payload = {"page_size": page_size}
        if filter:
            payload["filter"] = filter
        if sorts:
            payload["sorts"] = sorts
        if cursor:
            payload["start_cursor"] = cursor

        response = client.post(f"/databases/{database_id}/query", json=payload)
        result = _handle_response(response)

        all_results.extend(result.get("results", []))

        if result.get("has_more", False):
            cursor = result.get("next_cursor")
            time.sleep(0.35)
        else:
            break

    logger.info(f"Query returned {len(all_results)} pages")
    return all_results


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception(lambda e: isinstance(e, httpx.HTTPStatusError) and (e.response.status_code == 429 or 500 <= e.response.status_code < 600)),
    reraise=True,
)
def update_database(database_id: str, properties: dict) -> None:
    """
    Update a Notion database to add or modify properties.

    Args:
        database_id: UUID of the database to update
        properties: Dict of property definitions to add/modify

    Raises:
        Exception: If the Notion API returns an error.
    """
    client = _get_client()
    response = client.patch(f"/databases/{database_id}", json={"properties": properties})
    _handle_response(response)
    logger.info(f"Updated database {database_id}")


def parse_page_properties(page: dict) -> dict:
    """
    Convert a Notion page object into a simple flat Python dict.
    
    Extracts the page ID and converts each property from Notion's 
    verbose format to simple Python values.
    
    Args:
        page: Raw page object from query_database() results
    
    Returns:
        Dict with:
        - "id": page ID string
        - "created_time": ISO timestamp string
        - "last_edited_time": ISO timestamp string
        - "url": Notion page URL
        - One key per property, with simple Python values:
          - title -> str
          - rich_text -> str
          - url -> str or None
          - number -> float/int or None
          - select -> str or None
          - multi_select -> list[str]
          - date -> str or None (the start date)
          - checkbox -> bool
          - relation -> list[str] (list of page IDs)
    """
    parsed = {
        "id": page["id"],
        "created_time": page["created_time"],
        "last_edited_time": page["last_edited_time"],
        "url": page.get("url", ""),
    }

    for prop_name, prop in page.get("properties", {}).items():
        prop_type = prop.get("type", "")

        if prop_type == "title":
            parsed[prop_name] = "".join(t.get("plain_text", "") for t in prop.get("title", []))
        elif prop_type == "rich_text":
            parsed[prop_name] = "".join(t.get("plain_text", "") for t in prop.get("rich_text", []))
        elif prop_type == "url":
            parsed[prop_name] = prop.get("url")
        elif prop_type == "number":
            parsed[prop_name] = prop.get("number")
        elif prop_type == "select":
            select_val = prop.get("select")
            parsed[prop_name] = select_val["name"] if select_val else None
        elif prop_type == "multi_select":
            parsed[prop_name] = [item["name"] for item in prop.get("multi_select", [])]
        elif prop_type == "date":
            date_val = prop.get("date")
            parsed[prop_name] = date_val["start"] if date_val else None
        elif prop_type == "checkbox":
            parsed[prop_name] = prop.get("checkbox", False)
        elif prop_type == "relation":
            parsed[prop_name] = [item["id"] for item in prop.get("relation", [])]
        else:
            parsed[prop_name] = prop
            logger.warning(f"Unknown property type '{prop_type}' for '{prop_name}'")

    return parsed


def count_database(database_id: str) -> int:
    """
    Count total pages in a Notion database using cursor-based pagination.

    Args:
        database_id: UUID of the database to count

    Returns:
        Total number of pages in the database.
    """
    client = _get_client()
    total = 0
    cursor = None

    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor

        response = client.post(f"/databases/{database_id}/query", json=payload)
        result = _handle_response(response)

        total += len(result.get("results", []))

        if result.get("has_more", False):
            cursor = result.get("next_cursor")
            time.sleep(0.35)
        else:
            break

    logger.info(f"Counted {total} pages in database {database_id}")
    return total


if __name__ == "__main__":
    from config import PRIORITIES_PAGE_ID

    if not PRIORITIES_PAGE_ID:
        print("PRIORITIES_PAGE_ID not set in .env")
        print("Create a 'Current Priorities' page in Notion, add content,")
        print("and set PRIORITIES_PAGE_ID in .env to the page ID.")
        exit(1)

    print(f"Reading page: {PRIORITIES_PAGE_ID}")
    content = read_page_content(PRIORITIES_PAGE_ID)

    print(f"\n{'='*60}")
    print("PAGE CONTENT:")
    print(f"{'='*60}")
    print(content)
    print(f"{'='*60}")
    print(f"\nTotal length: {len(content)} characters")
    print(f"Total lines: {len(content.splitlines())}")


def append_blocks(page_id: str, blocks: list) -> None:
    """
    Append block children to a Notion page.

    Handles the 100 block limit by splitting into multiple requests.

    Args:
        page_id: UUID of the page to append blocks to
        blocks: List of block objects
    """
    BATCH_SIZE = 100
    client = _get_client()

    for i in range(0, len(blocks), BATCH_SIZE):
        batch = blocks[i:i + BATCH_SIZE]
        response = client.patch(
            f"/blocks/{page_id}/children",
            json={"children": batch},
        )
        _handle_response(response)
        if i + BATCH_SIZE < len(blocks):
            time.sleep(0.35)