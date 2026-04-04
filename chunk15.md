# CHUNK 15: Stage 3 — Curation & Daily Brief Generation

## Objective
Build `curation.py` — the complete Stage 3 pipeline that reads the Main Knowledge Base, reads the priorities document, generates a daily brief via OpenAI, writes the brief as a Notion page in the Brief Log database, applies decay recommendations, creates synthesis records, and updates entry priority scores and "seen by user" flags.

## Dependencies
- Chunk 2: `notion_client.create_page()`, `build_page_properties()`
- Chunk 3: `notion_client.query_database()`, `parse_page_properties()`
- Chunk 4: `notion_client.update_page()`
- Chunk 5: `notion_client.read_page_content()`
- Chunk 14: `openai_client.generate_daily_brief()`

## What this chunk creates
- `curation.py` — new file
- Updates `main.py` — adds daily brief trigger

---

## DESIGN

### What Stage 3 does (once daily at 11 PM IST)

1. **Read** all active entries from Main KB
2. **Read** the Current Priorities document
3. **Call** `generate_daily_brief()` to get the structured brief from OpenAI
4. **Write** the brief as a new page in the Brief Log database
5. **Update** entries in Main KB:
   - Set `Priority Score` on high-priority entries (from the brief's scores)
   - Set `Seen By User = True` on entries that appeared in the brief
   - Apply decay recommendations (move entries from Active → Aging → Archived)
6. **Create** synthesis records in the Synthesis database (if any synthesis insights were found)
7. **Log** the summary

### Brief as a Notion page

The daily brief is written as a new page in the Brief Log database with:
- **Title:** "Daily Brief — 2026-04-03"
- **Brief Date:** today's date
- **Executive Summary:** the 2–3 sentence summary (as a rich text property)
- **Delivered At:** current timestamp
- **Entries Surfaced:** relation linking to the high-priority entry pages in Main KB
- **Syntheses Surfaced:** relation linking to synthesis records (created in step 6)

The full brief content (all sections) is written as the **page body** (block children), not just properties. This makes it readable when you open the page in Notion.

---

## NOTION API REFERENCE — APPEND BLOCK CHILDREN

To write content into a page body (not properties), use the Append Block Children endpoint.

### Endpoint

```
PATCH https://api.notion.com/v1/blocks/{page_id}/children
```

### Request Body

```json
{
  "children": [
    {
      "object": "block",
      "type": "heading_1",
      "heading_1": {
        "rich_text": [{"type": "text", "text": {"content": "Executive Summary"}}]
      }
    },
    {
      "object": "block",
      "type": "paragraph",
      "paragraph": {
        "rich_text": [{"type": "text", "text": {"content": "The main takeaway today..."}}]
      }
    },
    {
      "object": "block",
      "type": "heading_2",
      "heading_2": {
        "rich_text": [{"type": "text", "text": {"content": "Synthesis Insights"}}]
      }
    },
    {
      "object": "block",
      "type": "bulleted_list_item",
      "bulleted_list_item": {
        "rich_text": [{"type": "text", "text": {"content": "Bullet point text"}}]
      }
    },
    {
      "object": "block",
      "type": "divider",
      "divider": {}
    }
  ]
}
```

### Block Types for Writing

| Type | JSON key | Has rich_text? |
|---|---|---|
| `heading_1` | `heading_1` | Yes |
| `heading_2` | `heading_2` | Yes |
| `heading_3` | `heading_3` | Yes |
| `paragraph` | `paragraph` | Yes |
| `bulleted_list_item` | `bulleted_list_item` | Yes |
| `numbered_list_item` | `numbered_list_item` | Yes |
| `divider` | `divider` | No (empty object) |
| `quote` | `quote` | Yes |

### Rich Text in Blocks

Same format as page properties:
```json
{"rich_text": [{"type": "text", "text": {"content": "Your text here"}}]}
```

**Bold text:**
```json
{"rich_text": [{"type": "text", "text": {"content": "Bold text"}, "annotations": {"bold": true}}]}
```

### Limits

- Max 100 blocks per request. If brief has more than 100 blocks, split into multiple requests.
- Each rich text content has a 2000 character limit per text object (same as page properties).

### Response

Returns the appended blocks. Status 200 on success.

### Errors

Same as other Notion endpoints (400, 401, 404, 429).

---

## IMPLEMENTATION SPEC

### File: `curation.py`

### Functions to implement:

#### `run_daily_brief() -> dict`

```python
def run_daily_brief() -> dict:
    """
    Execute Stage 3: generate and publish the daily brief.
    
    Returns:
        Dict with summary:
        {
            "active_entries": int,
            "brief_generated": bool,
            "brief_page_id": str | None,
            "synthesis_records": int,
            "entries_scored": int,
            "entries_decayed": int,
            "entries_marked_seen": int,
            "errors": list[str],
        }
    """
```

Implementation — step by step:

**Step 1: Read active entries from Main KB**
```python
from notion_client import query_database, parse_page_properties, create_page, build_page_properties, update_page, read_page_content
from openai_client import generate_daily_brief
from config import get_database_id, TOPIC, PRIORITIES_PAGE_ID
from datetime import datetime, timezone, timedelta
import time

IST = timezone(timedelta(hours=5, minutes=30))

main_kb_id = get_database_id("main_kb")
synthesis_id = get_database_id("synthesis")
brief_log_id = get_database_id("brief_log")

# Only active entries for the brief
pages = query_database(
    main_kb_id,
    filter={"property": "Decay Status", "select": {"equals": "Active"}},
)
entries = [parse_page_properties(p) for p in pages]
```

If zero active entries, log warning and return early.

**Step 2: Read priorities document**
```python
priorities = ""
if PRIORITIES_PAGE_ID:
    priorities = read_page_content(PRIORITIES_PAGE_ID)
else:
    logger.warning("PRIORITIES_PAGE_ID not set — brief will use general ranking")
```

**Step 3: Generate brief via OpenAI**
```python
brief = generate_daily_brief(entries, priorities, TOPIC)
```
If this fails, log error and return early (can't proceed without the brief).

**Step 4: Create synthesis records**
For each synthesis insight in `brief["synthesis_insights"]`:
```python
synthesis_page_ids = []
for insight in brief["synthesis_insights"]:
    # Find page IDs for contributing entries (match by title)
    linked_ids = []
    for entry_title in insight["contributing_entries"]:
        for entry in entries:
            if entry.get("Title", "").strip() == entry_title.strip():
                linked_ids.append(entry["id"])
                break
    
    props = build_page_properties(
        title=insight["inference"][:80],  # Short title from inference
        title_property_name="Synthesis Title",
        rich_text_fields={
            "Inference": insight["inference"],
        },
        date_fields={
            "Generated Date": datetime.now(IST).strftime("%Y-%m-%d"),
        },
        select_fields={
            "Relevance Window": "2 Weeks",  # Default
        },
        relation_fields={
            "Linked Entries": linked_ids,
        } if linked_ids else None,
    )
    synth_page_id = create_page(synthesis_id, props)
    synthesis_page_ids.append(synth_page_id)
    time.sleep(0.35)
```

**Step 5: Create the Brief Log page**

Create the page with properties first:
```python
today = datetime.now(IST).strftime("%Y-%m-%d")

# Collect page IDs for high-priority entries (match by title)
surfaced_ids = []
for hp_entry in brief["high_priority_entries"]:
    for entry in entries:
        if entry.get("Title", "").strip() == hp_entry["title"].strip():
            surfaced_ids.append(entry["id"])
            break

brief_props = build_page_properties(
    title=f"Daily Brief — {today}",
    title_property_name="Brief Title",
    rich_text_fields={
        "Executive Summary": brief["executive_summary"],
    },
    date_fields={
        "Brief Date": today,
        "Delivered At": datetime.now(IST).isoformat(),
    },
    relation_fields={
        "Entries Surfaced": surfaced_ids,
        "Syntheses Surfaced": synthesis_page_ids,
    },
)
brief_page_id = create_page(brief_log_id, brief_props)
```

Then write the brief body as blocks:
```python
_write_brief_body(brief_page_id, brief, entries)
```

**Step 6: Update Main KB entries**

a) Set priority scores on high-priority entries:
```python
for hp_entry in brief["high_priority_entries"]:
    for entry in entries:
        if entry.get("Title", "").strip() == hp_entry["title"].strip():
            update_page(entry["id"], {
                "Priority Score": {"number": hp_entry["priority_score"]},
                "Seen By User": {"checkbox": True},
            })
            time.sleep(0.35)
            break
```

b) Apply decay recommendations:
```python
for rec in brief["decay_recommendations"]:
    for entry in entries:
        if entry.get("Title", "").strip() == rec["title"].strip():
            new_status = rec["recommended_status"]
            if new_status in ("Aging", "Archived"):
                update_props = {
                    "Decay Status": {"select": {"name": new_status}},
                }
                # If archiving, add archived summary
                if new_status == "Archived":
                    update_props["Archived Summary"] = {
                        "rich_text": [{"type": "text", "text": {"content": 
                            entry.get("One-Line Summary", "")[:200]
                        }}]
                    }
                update_page(entry["id"], update_props)
                time.sleep(0.35)
            break
```

**Step 7: Log and return summary.**

#### `_write_brief_body(page_id: str, brief: dict, entries: list[dict]) -> None`

```python
def _write_brief_body(page_id: str, brief: dict, entries: list[dict]) -> None:
    """
    Write the full brief content as blocks into a Notion page body.
    
    Formats the brief sections as headings, paragraphs, and lists.
    """
```

Implementation:
- Build a list of block objects for each section:
  - **Heading 1:** "Executive Summary"
  - **Paragraph:** the executive summary text
  - **Divider**
  - **Heading 1:** "Synthesis Insights"
  - For each insight: **Heading 3** with short title, **Paragraph** with inference, **Bulleted list** with contributing entries, **Paragraph** with relevance
  - **Divider**
  - **Heading 1:** "High-Priority Entries"
  - For each entry: **Bulleted list item** with `[Signal] [Region] Title — summary`
  - **Divider**
  - **Heading 1:** "Updated Entries"
  - For each: **Bulleted list item** or "No updates today" paragraph
  - **Divider**
  - **Heading 1:** "Decay Recommendations"
  - For each: **Bulleted list item** or "No recommendations today" paragraph

- Send blocks via `PATCH /v1/blocks/{page_id}/children`
- Handle the 100 block limit — split into multiple requests if needed
- Use `_format_rich_text()` from `notion_client` for text content in blocks, BUT block rich text objects don't need the 2000-char split handled separately (Notion handles it per block)
- Add `time.sleep(0.35)` between pagination requests

#### Helper: `_build_block(block_type: str, text: str, bold: bool = False) -> dict`

```python
def _build_block(block_type: str, text: str, bold: bool = False) -> dict:
    """
    Build a Notion block object.
    
    Args:
        block_type: heading_1, heading_2, heading_3, paragraph, 
                   bulleted_list_item, numbered_list_item
        text: The text content
        bold: Whether to bold the text
    
    Returns:
        Block dict ready for the blocks API.
    """
    annotations = {}
    if bold:
        annotations["bold"] = True
    
    rich_text_obj = {"type": "text", "text": {"content": text}}
    if annotations:
        rich_text_obj["annotations"] = annotations
    
    return {
        "object": "block",
        "type": block_type,
        block_type: {
            "rich_text": [rich_text_obj]
        }
    }
```

For dividers:
```python
def _build_divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}
```

---

## ADD TO notion_client.py

Add this function to `notion_client.py` (OpenCode should do this as part of this chunk):

#### `append_blocks(page_id: str, blocks: list[dict]) -> None`

```python
def append_blocks(page_id: str, blocks: list[dict]) -> None:
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
```

---

## UPDATE main.py

Add daily brief trigger to `main.py`. Update the `main()` function to accept a "brief" argument:

```python
# In the command-line argument handling section of main():
if len(sys.argv) > 1:
    arg = sys.argv[1]
    
    if arg == "brief":
        from curation import run_daily_brief
        summary = run_daily_brief()
        _print_brief_summary(summary)
        return
    
    try:
        cycle = int(arg)
        # ... existing cycle handling ...
```

Add usage line:
```python
logger.info("  python main.py brief    Run daily brief generation")
```

Add summary printer:
```python
def _print_brief_summary(summary: dict):
    print(f"\n{'='*60}")
    print(f"DAILY BRIEF — {'GENERATED' if summary['brief_generated'] else 'FAILED'}")
    print(f"{'='*60}")
    print(f"Active entries:      {summary['active_entries']}")
    print(f"Brief page ID:       {summary.get('brief_page_id', 'N/A')}")
    print(f"Synthesis records:   {summary['synthesis_records']}")
    print(f"Entries scored:      {summary['entries_scored']}")
    print(f"Entries decayed:     {summary['entries_decayed']}")
    print(f"Entries marked seen: {summary['entries_marked_seen']}")
    if summary['errors']:
        print(f"Errors:              {len(summary['errors'])}")
        for e in summary['errors']:
            print(f"  - {e}")
    print(f"{'='*60}")
```

---

## TEST BLOCK

```python
if __name__ == "__main__":
    print("Running Stage 3: Daily Brief Generation...")
    print("This reads Main KB, calls GPT-5.4, writes to Notion.")
    print("Cost: ~$0.10-0.15 for OpenAI call.\n")
    
    summary = run_daily_brief()
    
    print(f"\n{'='*60}")
    print(f"DAILY BRIEF SUMMARY")
    print(f"{'='*60}")
    print(f"Active entries:      {summary['active_entries']}")
    print(f"Brief generated:     {summary['brief_generated']}")
    print(f"Brief page ID:       {summary.get('brief_page_id', 'N/A')}")
    print(f"Synthesis records:   {summary['synthesis_records']}")
    print(f"Entries scored:      {summary['entries_scored']}")
    print(f"Entries decayed:     {summary['entries_decayed']}")
    print(f"Entries marked seen: {summary['entries_marked_seen']}")
    if summary['errors']:
        print(f"Errors:")
        for e in summary['errors']:
            print(f"  - {e}")
    print(f"{'='*60}")
    print(f"\nCheck Notion → Brief Log for the generated brief page.")
    print(f"Check Notion → Synthesis Database for any synthesis records.")
```

---

## EDGE CASES

### No active entries
Return early with `brief_generated: False`. No OpenAI call.

### Priorities page not set
Brief generates with general ranking (no priority context). Log warning.

### Title matching fails for some entries
The brief references entry titles from the model output. If a title doesn't match any Main KB entry (model hallucinated or slightly modified the title), skip that entry silently and log a warning. Don't crash.

### Brief body exceeds 100 blocks
Split into multiple append requests. The `append_blocks` function handles this.

### Synthesis insight has no matchable entries
If none of the contributing entry titles match, create the synthesis record without the `Linked Entries` relation (empty relation). The inference text is still valuable.

### Decay recommendation for already-archived entry
Skip it. Check `Decay Status` before applying. Only move Active → Aging or Aging → Archived.

### OpenAI call fails
Return early with `brief_generated: False`. Log the error. Entries in Main KB are unchanged.

### Re-running the same day
Creates a second brief page for the same date. This is fine — no harm. The Brief Log shows the history.

### Rich text in blocks exceeding 2000 chars
Split long text blocks (e.g., a very long inference) into multiple text objects within the same block's rich_text array, same as `_format_rich_text()` does.