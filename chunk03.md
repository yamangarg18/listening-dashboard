# CHUNK 3: Notion Read — Query a Database with Filters and Pagination

## Objective
Add `query_database()` to `notion_client.py` — a function that queries any Notion database with optional filters, sorting, and automatic pagination handling. This is how Stage 2 reads the Ingestion Queue and Main KB, and how Stage 3 reads entries for the daily brief.

## Dependencies
- Chunk 0 complete (config.py, logger.py)
- Chunk 1 complete (databases exist in Notion)
- Chunk 2 complete (notion_client.py exists with create_page, build_page_properties, helpers)

## What this chunk adds to notion_client.py
- `query_database()` — public function
- `parse_page_properties()` — public helper that converts Notion's verbose property format back to simple Python values

---

## NOTION API REFERENCE — QUERY A DATABASE

### Endpoint

```
POST https://api.notion.com/v1/databases/{database_id}/query
```

**Note:** This is a POST, not a GET. The filters and sorts go in the request body.

### Request Body

```json
{
  "filter": { ...filter object... },
  "sorts": [ ...sort objects... ],
  "page_size": 100,
  "start_cursor": "cursor-string-from-previous-response"
}
```

All fields are optional:
- **No filter** = return all pages in the database
- **No sorts** = no guaranteed order
- **page_size** = max results per request (1–100, default 100). Always use 100.
- **start_cursor** = for pagination. Omit on first request. Use `next_cursor` from previous response for subsequent requests.

### Response (200 OK)

```json
{
  "object": "list",
  "results": [
    {
      "object": "page",
      "id": "page-id-xxxx",
      "created_time": "2026-04-03T10:00:00.000Z",
      "last_edited_time": "2026-04-03T10:00:00.000Z",
      "archived": false,
      "url": "https://www.notion.so/...",
      "parent": {
        "type": "database_id",
        "database_id": "db-id-xxxx"
      },
      "properties": {
        "Title": {
          "id": "title",
          "type": "title",
          "title": [
            {
              "type": "text",
              "text": {"content": "Page Title"},
              "plain_text": "Page Title"
            }
          ]
        },
        "Signal Level": {
          "id": "abcd",
          "type": "select",
          "select": {
            "id": "xxxx",
            "name": "High",
            "color": "red"
          }
        },
        "Topic Tags": {
          "id": "efgh",
          "type": "multi_select",
          "multi_select": [
            {"id": "xxxx", "name": "Robotics", "color": "blue"},
            {"id": "yyyy", "name": "AI", "color": "green"}
          ]
        },
        "Published Date": {
          "id": "ijkl",
          "type": "date",
          "date": {
            "start": "2026-04-03",
            "end": null,
            "time_zone": null
          }
        },
        "Confidence Score": {
          "id": "mnop",
          "type": "number",
          "number": 0.85
        },
        "URL": {
          "id": "qrst",
          "type": "url",
          "url": "https://example.com"
        },
        "One-Line Summary": {
          "id": "uvwx",
          "type": "rich_text",
          "rich_text": [
            {
              "type": "text",
              "text": {"content": "Summary text here"},
              "plain_text": "Summary text here"
            }
          ]
        },
        "Seen By User": {
          "id": "yzab",
          "type": "checkbox",
          "checkbox": false
        }
      }
    }
  ],
  "has_more": true,
  "next_cursor": "cursor-string-for-next-page",
  "type": "page_or_database"
}
```

**PAGINATION:** If `has_more` is `true`, there are more results. Make another request with `start_cursor` set to `next_cursor`. Repeat until `has_more` is `false`. The function must handle this automatically.

### Reading Property Values from Response

When you READ a page from Notion, the property format is more verbose than when you WRITE. Here's how to extract simple Python values from each property type:

#### Title
```python
# Response format:
"Title": {"type": "title", "title": [{"plain_text": "Page Title"}]}

# Extract:
title = "".join([t["plain_text"] for t in prop["title"]])
```

#### Rich Text
```python
# Response format:
"Summary": {"type": "rich_text", "rich_text": [{"plain_text": "Text here"}]}

# Extract:
text = "".join([t["plain_text"] for t in prop["rich_text"]])
```

#### URL
```python
# Response format:
"URL": {"type": "url", "url": "https://example.com"}

# Extract:
url = prop["url"]  # string or None
```

#### Number
```python
# Response format:
"Score": {"type": "number", "number": 0.85}

# Extract:
number = prop["number"]  # float/int or None
```

#### Select
```python
# Response format:
"Signal Level": {"type": "select", "select": {"name": "High", "color": "red"}}
# Or if empty:
"Signal Level": {"type": "select", "select": null}

# Extract:
select_value = prop["select"]["name"] if prop["select"] else None
```

#### Multi-Select
```python
# Response format:
"Tags": {"type": "multi_select", "multi_select": [{"name": "AI"}, {"name": "Robotics"}]}

# Extract:
tags = [item["name"] for item in prop["multi_select"]]
```

#### Date
```python
# Response format:
"Published Date": {"type": "date", "date": {"start": "2026-04-03", "end": null}}
# Or if empty:
"Published Date": {"type": "date", "date": null}

# Extract:
date_value = prop["date"]["start"] if prop["date"] else None
```

#### Checkbox
```python
# Response format:
"Done": {"type": "checkbox", "checkbox": false}

# Extract:
checked = prop["checkbox"]  # bool
```

#### Relation
```python
# Response format:
"Linked Entries": {"type": "relation", "relation": [{"id": "page-id-1"}, {"id": "page-id-2"}]}

# Extract:
related_ids = [item["id"] for item in prop["relation"]]
```

**NOTE on relations:** When querying a database, Notion only returns the first 25 related page IDs. If a relation has more than 25 items, the response includes `"has_more": true` inside the relation property. For this project, 25 is more than enough — no need to handle this edge case.

---

## FILTER REFERENCE

### Single property filter

```json
{
  "filter": {
    "property": "Property Name",
    "property_type": {
      "condition": "value"
    }
  }
}
```

Where `property_type` matches the type of the property, and `condition` is the comparison operator.

### Filter conditions by property type:

#### Checkbox
```json
{"property": "Seen By User", "checkbox": {"equals": true}}
{"property": "Seen By User", "checkbox": {"equals": false}}
```

#### Select
```json
{"property": "Signal Level", "select": {"equals": "High"}}
{"property": "Signal Level", "select": {"does_not_equal": "Low"}}
{"property": "Decay Status", "select": {"is_empty": true}}
{"property": "Decay Status", "select": {"is_not_empty": true}}
```

#### Multi-Select
```json
{"property": "Topic Tags", "multi_select": {"contains": "Robotics"}}
{"property": "Topic Tags", "multi_select": {"does_not_contain": "Robotics"}}
{"property": "Topic Tags", "multi_select": {"is_empty": true}}
{"property": "Topic Tags", "multi_select": {"is_not_empty": true}}
```

#### Date
```json
{"property": "Published Date", "date": {"equals": "2026-04-03"}}
{"property": "Published Date", "date": {"before": "2026-04-03"}}
{"property": "Published Date", "date": {"after": "2026-04-03"}}
{"property": "Published Date", "date": {"on_or_before": "2026-04-03"}}
{"property": "Published Date", "date": {"on_or_after": "2026-04-03"}}
{"property": "Published Date", "date": {"past_week": {}}}
{"property": "Published Date", "date": {"is_empty": true}}
{"property": "Published Date", "date": {"is_not_empty": true}}
```

Date values accept ISO 8601 format: `"2026-04-03"` or `"2026-04-03T14:30:00+05:30"`. Comparisons with time are millisecond precision. Without timezone, defaults to UTC.

**Relative date filters:** `past_week`, `this_week`, `next_week`, `past_month`, `this_month`, `next_month`, `past_year`, `this_year`, `next_year` — these take an empty object `{}` as the value.

#### Number
```json
{"property": "Confidence Score", "number": {"equals": 0.85}}
{"property": "Confidence Score", "number": {"greater_than": 0.5}}
{"property": "Confidence Score", "number": {"less_than": 1.0}}
{"property": "Confidence Score", "number": {"greater_than_or_equal_to": 0.5}}
{"property": "Confidence Score", "number": {"less_than_or_equal_to": 1.0}}
```

#### Rich Text
```json
{"property": "One-Line Summary", "rich_text": {"contains": "robotics"}}
{"property": "One-Line Summary", "rich_text": {"does_not_contain": "test"}}
{"property": "One-Line Summary", "rich_text": {"starts_with": "Breaking"}}
{"property": "One-Line Summary", "rich_text": {"is_empty": true}}
{"property": "One-Line Summary", "rich_text": {"is_not_empty": true}}
```

#### Timestamp (works on any database, even without a date property)
```json
{"timestamp": "created_time", "created_time": {"after": "2026-04-01"}}
{"timestamp": "last_edited_time", "last_edited_time": {"past_week": {}}}
```

### Compound filters (AND / OR)

```json
{
  "filter": {
    "and": [
      {"property": "Decay Status", "select": {"equals": "Active"}},
      {"property": "Discovered Date", "date": {"after": "2026-03-27"}}
    ]
  }
}
```

```json
{
  "filter": {
    "or": [
      {"property": "Signal Level", "select": {"equals": "High"}},
      {"property": "Signal Level", "select": {"equals": "Medium"}}
    ]
  }
}
```

**Nesting:** You can nest up to 2 levels deep:
```json
{
  "filter": {
    "and": [
      {"property": "Decay Status", "select": {"equals": "Active"}},
      {
        "or": [
          {"property": "Signal Level", "select": {"equals": "High"}},
          {"property": "Signal Level", "select": {"equals": "Medium"}}
        ]
      }
    ]
  }
}
```

---

## SORT REFERENCE

```json
{
  "sorts": [
    {
      "property": "Published Date",
      "direction": "descending"
    }
  ]
}
```

Direction: `"ascending"` or `"descending"`.

Sort by timestamp (without a property):
```json
{
  "sorts": [
    {
      "timestamp": "created_time",
      "direction": "descending"
    }
  ]
}
```

Multiple sorts (first takes precedence):
```json
{
  "sorts": [
    {"property": "Signal Level", "direction": "ascending"},
    {"property": "Published Date", "direction": "descending"}
  ]
}
```

---

## IMPLEMENTATION SPEC

### Add to `notion_client.py` (do NOT replace existing code — add these functions):

#### `query_database(database_id: str, filter: dict | None = None, sorts: list | None = None, page_size: int = 100) -> list[dict]`

```python
def query_database(
    database_id: str,
    filter: dict | None = None,
    sorts: list | None = None,
    page_size: int = 100,
) -> list[dict]:
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
    
    Example:
        # Get all active entries from Main KB
        pages = query_database(
            database_id=main_kb_id,
            filter={
                "property": "Decay Status",
                "select": {"equals": "Active"}
            },
            sorts=[{"property": "Published Date", "direction": "descending"}],
        )
        
        # Get all pages (no filter)
        all_pages = query_database(database_id=iq_id)
    """
```

Implementation requirements:
- Build the request body with `page_size` and optionally `filter` and `sorts`
- Send `POST /v1/databases/{database_id}/query`
- Check response with `_handle_response()`
- Collect `results` from the response
- If `has_more` is `true`, make another request with `start_cursor` set to `next_cursor`
- Repeat until `has_more` is `false`
- Return the combined list of all page objects
- Log the total number of pages found
- Add `time.sleep(0.35)` between pagination requests to respect rate limits
- Use tenacity retry decorator (same as create_page) for 429 and 5xx errors

#### `parse_page_properties(page: dict) -> dict`

```python
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
    
    Example:
        pages = query_database(db_id)
        for page in pages:
            data = parse_page_properties(page)
            print(data["id"])              # "xxxx-xxxx-..."
            print(data["Title"])           # "Article Title"
            print(data["Signal Level"])    # "High"
            print(data["Topic Tags"])      # ["Robotics", "AI"]
            print(data["Confidence Score"])# 0.85
    """
```

Implementation requirements:
- Start with `{"id": page["id"], "created_time": page["created_time"], "last_edited_time": page["last_edited_time"], "url": page.get("url", "")}`
- Loop through `page["properties"]` items
- For each property, check its `type` field and extract the value using the patterns in the "Reading Property Values from Response" section above
- Handle None/empty values gracefully (don't crash if a select is null or rich_text is empty)
- Unknown property types should be stored as the raw value with a warning log
- Return the flat dict

---

## TEST BLOCK

Add this at the bottom of `notion_client.py`, replacing the existing `if __name__ == "__main__":` block:

```python
if __name__ == "__main__":
    from config import get_database_id
    
    iq_id = get_database_id("ingestion_queue")
    main_kb_id = get_database_id("main_kb")
    
    # --- Test 1: Create test entries ---
    print("Creating 3 test entries in Ingestion Queue...")
    
    test_entries = [
        {"title": "TEST READ 1 — Delete Me", "method": "Time-window", "cycle": "1"},
        {"title": "TEST READ 2 — Delete Me", "method": "Relevance-ranked", "cycle": "2"},
        {"title": "TEST READ 3 — Delete Me", "method": "Time-window", "cycle": "3"},
    ]
    
    created_ids = []
    for entry in test_entries:
        import time
        props = build_page_properties(
            title=entry["title"],
            select_fields={
                "Retrieval Method": entry["method"],
                "Search Cycle": entry["cycle"],
            },
            date_fields={"Discovered Date": "2026-04-03"},
        )
        page_id = create_page(iq_id, props)
        created_ids.append(page_id)
        print(f"  Created: {entry['title']} ({page_id})")
        time.sleep(0.35)
    
    # --- Test 2: Query all pages ---
    print("\nQuerying all pages in Ingestion Queue...")
    pages = query_database(iq_id)
    print(f"  Found {len(pages)} pages")
    
    # --- Test 3: Query with filter ---
    print("\nQuerying with filter: Retrieval Method = Time-window...")
    filtered = query_database(
        iq_id,
        filter={"property": "Retrieval Method", "select": {"equals": "Time-window"}},
    )
    print(f"  Found {len(filtered)} pages with Time-window")
    
    # --- Test 4: Parse properties ---
    print("\nParsing first page properties...")
    if pages:
        parsed = parse_page_properties(pages[0])
        for key, value in sorted(parsed.items()):
            print(f"  {key}: {value}")
    
    # --- Cleanup reminder ---
    print(f"\nDone! Delete the 3 test entries from Ingestion Queue in Notion.")
    print(f"Page IDs: {created_ids}")
```

---

## EDGE CASES

### Empty database
Querying a database with no pages returns `{"results": [], "has_more": false}`. The function should return an empty list, not crash.

### Filter matches nothing
Same as empty database — returns empty results. Return empty list.

### Pagination
If the database has more than 100 pages, the first response has `has_more: true`. The function must loop, passing `start_cursor` each time, until `has_more` is `false`. For this project, databases are unlikely to exceed 100 entries initially, but the function must handle it correctly for when they grow.

### Property type not handled
If Notion adds a new property type in the future, `parse_page_properties()` should log a warning and store the raw value rather than crashing.

### Archived/trashed pages
By default, Notion's query endpoint does NOT return archived or trashed pages. This is the correct behavior — no special handling needed.

### Rate limiting during pagination
Each pagination request counts toward the 3 req/sec limit. The `time.sleep(0.35)` between requests prevents hitting this. The tenacity retry handles any 429s that slip through.

### Relation has_more
When a relation property has more than 25 linked pages, the response includes `"has_more": true` inside the relation object. For this project, ignore this — 25 is sufficient. Extract only the IDs returned in the first response.