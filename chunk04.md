# CHUNK 4: Notion Update — Modify a Page's Properties

## Objective
Add `update_page()` to `notion_client.py` — a function that updates specific properties on an existing Notion page without touching the other properties. This is how Stage 2 updates existing entries (change signal level, append to change log) and how Stage 3 updates priority scores, decay statuses, and "seen by user" flags.

## Dependencies
- Chunks 0–3 complete
- `notion_client.py` has: `create_page()`, `build_page_properties()`, `query_database()`, `parse_page_properties()`, and all helpers

## What this chunk adds to notion_client.py
- `update_page()` — public function
- `archive_page()` — public function (archives/deletes a page)

---

## NOTION API REFERENCE — UPDATE A PAGE

### Endpoint

```
PATCH https://api.notion.com/v1/pages/{page_id}
```

### Request Body

```json
{
  "properties": {
    "Property Name": {
      ...property value object...
    }
  }
}
```

**CRITICAL RULES:**
- Only include properties you want to change. Omitted properties are left unchanged.
- Property value formats are IDENTICAL to the Create Page formats (Chunk 2). Same JSON structure for title, rich_text, url, number, select, multi_select, date, checkbox, relation.
- To CLEAR a property value, set it to its empty/null form:
  - Select: `{"select": null}`
  - Date: `{"date": null}`
  - URL: `{"url": null}`
  - Number: `{"number": null}`
  - Rich text: `{"rich_text": []}`
  - Multi-select: `{"multi_select": []}`
  - Relation: `{"relation": []}`
  - Checkbox: `{"checkbox": false}` (checkboxes can't be null — only true/false)
- You CANNOT update auto-generated properties (`created_time`, `created_by`, `last_edited_time`, `last_edited_by`). Notion updates `last_edited_time` automatically when you modify any property.
- The `title` property CAN be updated — just pass the new title value.

### Response (200 OK)

Returns the full updated page object (same format as Create Page response):

```json
{
  "object": "page",
  "id": "page-id-xxxx",
  "created_time": "2026-04-03T10:00:00.000Z",
  "last_edited_time": "2026-04-03T12:00:00.000Z",
  "archived": false,
  "properties": { ...all properties with current values... }
}
```

### Error Responses

| Status | Code | Meaning |
|--------|------|---------|
| 400 | `validation_error` | Property name doesn't exist, wrong value format, or tried to set auto-generated property |
| 401 | `unauthorized` | Bad API key |
| 404 | `object_not_found` | Page ID doesn't exist or not accessible |
| 409 | `conflict_error` | Transaction conflict (retry-safe) |
| 429 | `rate_limited` | Too many requests |

---

## NOTION API REFERENCE — ARCHIVE A PAGE

To "delete" a page via the API, you archive it. Same endpoint, different body:

### Endpoint

```
PATCH https://api.notion.com/v1/pages/{page_id}
```

### Request Body

```json
{
  "archived": true
}
```

This moves the page to Notion's trash. It can be restored manually in Notion. To fully delete, a user must empty the trash in the Notion UI.

To unarchive:
```json
{
  "archived": false
}
```

---

## IMPLEMENTATION SPEC

### Add to `notion_client.py`:

#### `update_page(page_id: str, properties: dict) -> dict`

```python
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
```

Implementation requirements:
- Send `PATCH /v1/pages/{page_id}` with `{"properties": properties}`
- Use `_handle_response()` to check for errors
- Log the page ID and number of updated properties on success
- Return the full updated page object
- Use tenacity retry decorator (same pattern as create_page) for 429 and 5xx errors

**IMPORTANT NOTE on build_page_properties():** When updating, you often want to change just one or two fields. `build_page_properties()` requires `title` as a mandatory argument, but when updating you might not want to change the title. Two approaches:

Option A: Pass the existing title (wasteful but works).
Option B: Build the properties dict manually for small updates:
```python
update_page(page_id, {
    "Signal Level": {"select": {"name": "High"}},
    "Seen By User": {"checkbox": True},
})
```

Both are valid. For small updates (1–3 fields), Option B is cleaner. For large updates, use `build_page_properties()`. The function should accept either format — it just passes the dict through to the API.

#### `archive_page(page_id: str) -> dict`

```python
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
```

Implementation requirements:
- Send `PATCH /v1/pages/{page_id}` with `{"archived": True}`
- Use `_handle_response()`
- Log the page ID and "archived" on success
- Return the response
- Use tenacity retry decorator

---

## TEST BLOCK

Replace the existing `if __name__ == "__main__":` block in `notion_client.py` with:

```python
if __name__ == "__main__":
    from config import get_database_id
    import time
    
    iq_id = get_database_id("ingestion_queue")
    
    # --- Setup: Create a test entry ---
    print("Creating test entry...")
    props = build_page_properties(
        title="UPDATE TEST — Delete Me",
        url="https://example.com/update-test",
        rich_text_fields={"Raw Summary": "Original summary."},
        select_fields={
            "Retrieval Method": "Time-window",
            "Search Cycle": "1",
        },
        date_fields={"Discovered Date": "2026-04-03"},
    )
    page_id = create_page(iq_id, props)
    print(f"Created: {page_id}")
    time.sleep(1)
    
    # --- Test 1: Update select and rich_text ---
    print("\nUpdating Retrieval Method and Raw Summary...")
    update_page(page_id, {
        "Retrieval Method": {"select": {"name": "Relevance-ranked"}},
        "Raw Summary": {"rich_text": [{"type": "text", "text": {"content": "Updated summary."}}]},
    })
    
    # Verify
    time.sleep(0.5)
    pages = query_database(iq_id, filter={"property": "Title", "title": {"equals": "UPDATE TEST — Delete Me"}})
    parsed = parse_page_properties(pages[0])
    assert parsed["Retrieval Method"] == "Relevance-ranked", f"Expected Relevance-ranked, got {parsed['Retrieval Method']}"
    assert parsed["Raw Summary"] == "Updated summary.", f"Expected 'Updated summary.', got {parsed['Raw Summary']}"
    print("  Select + Rich text update: PASSED")
    
    # --- Test 2: Update using build_page_properties ---
    print("\nUpdating via build_page_properties...")
    update_page(page_id, build_page_properties(
        title="UPDATE TEST — Delete Me",  # unchanged but required by builder
        select_fields={"Search Cycle": "4"},
        date_fields={"Published Date": "2026-04-01"},
    ))
    
    time.sleep(0.5)
    pages = query_database(iq_id, filter={"property": "Title", "title": {"equals": "UPDATE TEST — Delete Me"}})
    parsed = parse_page_properties(pages[0])
    assert parsed["Search Cycle"] == "4", f"Expected 4, got {parsed['Search Cycle']}"
    assert parsed["Published Date"] == "2026-04-01", f"Expected 2026-04-01, got {parsed['Published Date']}"
    # Verify previous updates still intact
    assert parsed["Retrieval Method"] == "Relevance-ranked", "Previous update was overwritten!"
    print("  build_page_properties update: PASSED")
    print("  Previous updates preserved: PASSED")
    
    # --- Test 3: Clear a field ---
    print("\nClearing Published Date...")
    update_page(page_id, {"Published Date": {"date": None}})
    
    time.sleep(0.5)
    pages = query_database(iq_id, filter={"property": "Title", "title": {"equals": "UPDATE TEST — Delete Me"}})
    parsed = parse_page_properties(pages[0])
    assert parsed["Published Date"] is None, f"Expected None, got {parsed['Published Date']}"
    print("  Clear date field: PASSED")
    
    # --- Test 4: Archive the page ---
    print("\nArchiving page...")
    archive_page(page_id)
    
    time.sleep(0.5)
    pages = query_database(iq_id, filter={"property": "Title", "title": {"equals": "UPDATE TEST — Delete Me"}})
    assert len(pages) == 0, f"Archived page should not appear in query, but got {len(pages)} results"
    print("  Archive: PASSED (page no longer appears in query)")
    
    print("\nAll update tests passed!")
```

---

## EDGE CASES

### Updating a property that doesn't exist
Returns `400 validation_error` with a message like "Property Name is not a property that exists." Same error handling as create_page.

### Updating with empty properties dict
Sending `{"properties": {}}` is valid — Notion accepts it and does nothing. The `last_edited_time` does NOT change. No need to guard against this, but no need to call it either.

### Concurrent updates
If two processes update the same page simultaneously, Notion uses last-write-wins. No locking mechanism. For this project, only one pipeline process runs at a time, so this isn't a concern.

### Updating archived pages
You CAN update properties on an archived page. The page stays archived but its properties change. This is valid and sometimes useful (e.g., adding an "Archived Summary" before archiving).

### Large change log appending
The Change Log field will accumulate text over time as entries get updated. Each update should APPEND to the existing change log, not overwrite it. However, this requires reading the current value first (using query_database + parse_page_properties from Chunk 3), then concatenating the new text, then writing back. The `update_page()` function itself doesn't need to handle this — it's the calling code's responsibility (Stage 2 in Chunk 11).

### Rate limiting
Same as create_page — tenacity retry handles 429s. When updating many pages in a loop, the calling code should add `time.sleep(0.35)` between calls.