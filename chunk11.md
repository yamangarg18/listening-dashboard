# CHUNK 11: Stage 2 — Reconciliation

## Objective
Build `reconciliation.py` — the complete Stage 2 pipeline that reads the Ingestion Queue, analyzes entries with OpenAI, deduplicates against the Main Knowledge Base, and either creates new entries or updates existing ones in the Main KB. Then clears the processed entries from the Ingestion Queue.

## Dependencies
- Chunk 2: `notion_client.create_page()`, `build_page_properties()`
- Chunk 3: `notion_client.query_database()`, `parse_page_properties()`
- Chunk 4: `notion_client.update_page()`, `archive_page()`
- Chunk 10: `openai_client.analyze_articles_batched()`

## What this chunk creates
- `reconciliation.py` — new file

---

## DESIGN

### What Stage 2 does

After each ingestion cycle writes raw entries to the Ingestion Queue, Stage 2 runs immediately and:

1. **Reads** all entries from the Ingestion Queue
2. **Sends** them to OpenAI GPT-5.4 mini for analysis (signal level, category, summary, etc.)
3. **Compares** each analyzed entry against the Main Knowledge Base:
   - If the URL already exists in Main KB → **update** the existing entry
   - If the URL is new → **create** a new entry in Main KB with all reasoning fields
4. **Archives** processed entries from the Ingestion Queue (clears it for the next cycle)

### Update logic for existing entries

When a URL already exists in Main KB, the model may have new information:
- Signal level might change (Medium → High if more sources confirm)
- New entities or tags might be added (merged with existing, not replaced)
- Category might shift
- Change Log gets appended with what changed and when

The update preserves the original entry's `Discovered Date` and `Retrieval Method` but updates the reasoning fields.

---

## PRE-TEST MANUAL STEP (do before handing to OpenCode)

**Change `Source Name` in the Main Knowledge Base from `select` to `rich text` (Text):**

1. Open Notion → Main Knowledge Base
2. Click the `Source Name` column header
3. Click "Edit property"
4. Change type from "Select" to "Text"
5. Confirm any data loss warning

This is needed because new source domains appear dynamically and select properties don't auto-create options (unlike multi-select). Rich text accepts any string.

---

## IMPLEMENTATION SPEC

### File: `reconciliation.py`

### Functions to implement:

#### `run_reconciliation() -> dict`

```python
def run_reconciliation() -> dict:
    """
    Execute Stage 2: process all entries in the Ingestion Queue.
    
    Returns:
        Dict with reconciliation summary:
        {
            "queue_entries": int,
            "analyzed": int,
            "new_entries": int,
            "updated_entries": int,
            "archived_from_queue": int,
            "errors": list[str],
        }
    """
```

Implementation — step by step:

**Step 1: Read Ingestion Queue**
```python
from notion_client import query_database, parse_page_properties, create_page, build_page_properties, update_page, archive_page, _format_rich_text
from config import get_database_id, TOPIC
from openai_client import analyze_articles_batched
from parallel_client import _normalize_url
from datetime import datetime, timezone, timedelta
import time

IST = timezone(timedelta(hours=5, minutes=30))

iq_id = get_database_id("ingestion_queue")
main_kb_id = get_database_id("main_kb")

raw_pages = query_database(iq_id)
parsed_entries = [parse_page_properties(p) for p in raw_pages]
```
If empty, return early with all zeros.

**Step 2: Prepare articles for OpenAI**
```python
articles_for_ai = []
for entry in parsed_entries:
    articles_for_ai.append({
        "title": entry.get("Title", ""),
        "url": entry.get("URL", ""),
        "publish_date": entry.get("Published Date"),
        "source_name": entry.get("Source Name", ""),
        "excerpt_text": entry.get("Raw Summary", ""),
    })
```

**Step 3: Analyze with OpenAI**
```python
analyses = analyze_articles_batched(articles_for_ai, TOPIC)
```
If OpenAI fails completely, log and raise.

**Step 4: Match analyses to queue entries**

Pair by index (same order). If count mismatch, pair what we can and log warning.

**Step 5: Read Main KB for URL matching**
```python
existing_pages = query_database(main_kb_id)
existing_parsed = [parse_page_properties(p) for p in existing_pages]

# Build URL lookup: normalized_url → parsed entry
url_lookup = {}
for ep in existing_parsed:
    url = ep.get("URL")
    if url:
        url_lookup[_normalize_url(url)] = ep
```

**Step 6: Process each entry**

Track which queue entries were successfully processed (for archiving).

For each `(queue_entry, analysis)` pair:

**If URL is new → create in Main KB:**
```python
props = build_page_properties(
    title=queue_entry.get("Title", analysis.get("title", "")),
    url=queue_entry.get("URL"),
    rich_text_fields={
        "Source Name": queue_entry.get("Source Name", ""),
        "Raw Summary": queue_entry.get("Raw Summary", ""),
        "One-Line Summary": analysis["one_line_summary"],
        "Why It Matters": analysis["why_it_matters"],
    },
    select_fields={
        "Source Type": _infer_source_type(queue_entry.get("Source Name", "")),
        "Signal Level": analysis["signal_level"],
        "Category": analysis["category"],
        "Retrieval Method": queue_entry.get("Retrieval Method", ""),
        "Search Cycle": queue_entry.get("Search Cycle", ""),
        "Decay Status": "Active",
        "Half-Life Class": analysis["half_life_class"],
        "Dedup Status": "New",
    },
    multi_select_fields={
        "Key Entities": analysis["key_entities"],
        "Topic Tags": analysis["topic_tags"],
        "Framework Mapping": analysis["framework_mapping"],
    },
    date_fields={
        "Published Date": queue_entry.get("Published Date"),
        "Discovered Date": queue_entry.get("Discovered Date") or datetime.now(IST).isoformat(),
        "Last Updated": datetime.now(IST).isoformat(),
    },
    number_fields={
        "Confidence Score": analysis["confidence_score"],
        "Priority Score": 0,
    },
    checkbox_fields={
        "Seen By User": False,
        "Extract Content": False,
    },
)
create_page(main_kb_id, props)
time.sleep(0.35)
```

**If URL exists → update in Main KB:**
```python
existing_entry = url_lookup[normalized_url]
existing_id = existing_entry["id"]

# Detect changes for change log
changes = []
if existing_entry.get("Signal Level") != analysis["signal_level"]:
    changes.append(f"Signal: {existing_entry.get('Signal Level')} → {analysis['signal_level']}")
if existing_entry.get("Category") != analysis["category"]:
    changes.append(f"Category: {existing_entry.get('Category')} → {analysis['category']}")

# Build change log entry
old_log = existing_entry.get("Change Log", "") or ""
timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
new_log_entry = f"[{timestamp}] {'; '.join(changes)}" if changes else ""
updated_log = f"{old_log}\n{new_log_entry}".strip() if new_log_entry else old_log

# Build update properties (raw Notion format, not build_page_properties)
update_props = {
    "Signal Level": {"select": {"name": analysis["signal_level"]}},
    "Category": {"select": {"name": analysis["category"]}},
    "Confidence Score": {"number": analysis["confidence_score"]},
    "Half-Life Class": {"select": {"name": analysis["half_life_class"]}},
    "Dedup Status": {"select": {"name": "Updated"}},
    "Last Updated": {"date": {"start": datetime.now(IST).isoformat()}},
}

if new_log_entry:
    update_props["Change Log"] = {"rich_text": [{"type": "text", "text": {"content": updated_log}}]}

# Merge multi-selects (add new, keep existing)
merged_entities = list(set(existing_entry.get("Key Entities", []) + analysis["key_entities"]))
merged_tags = list(set(existing_entry.get("Topic Tags", []) + analysis["topic_tags"]))
update_props["Key Entities"] = {"multi_select": [{"name": e} for e in merged_entities]}
update_props["Topic Tags"] = {"multi_select": [{"name": t} for t in merged_tags]}

update_page(existing_id, update_props)
time.sleep(0.35)
```

**Wrap each entry processing in try/except.** If create or update fails, log the error, add to errors list, and do NOT mark that queue entry as processed.

**Step 7: Archive processed queue entries**

Only archive entries that were successfully processed (created or updated without errors):
```python
for entry_id in successfully_processed_ids:
    try:
        archive_page(entry_id)
        time.sleep(0.35)
    except Exception as e:
        logger.error(f"Failed to archive queue entry {entry_id}: {e}")
```

**Step 8: Log summary and return.**

#### `_infer_source_type(source_name: str) -> str`

```python
def _infer_source_type(source_name: str) -> str:
    """
    Infer source type from domain name.
    Returns: News, Blog, Academic, Social Media, Forum, Government, or Other
    """
    if not source_name:
        return "Other"
    
    source_lower = source_name.lower()
    
    news = ["reuters", "bloomberg", "techcrunch", "bbc", "cnn", "nytimes",
            "wsj", "ft", "economictimes", "scmp", "politico", "businessinsider",
            "theverge", "wired", "arstechnica", "cnbc", "forbes", "guardian",
            "washingtonpost", "apnews", "aljazeera", "newsroom", "news"]
    academic = ["arxiv", "ieee", "scholar", "nature", "science", "springer",
                "wiley", "acm", "researchgate", "ssrn", "pubmed", "biorxiv"]
    social = ["linkedin", "twitter", "x.com", "reddit", "facebook", "instagram"]
    forum = ["hackernews", "ycombinator", "stackoverflow", "quora", "slashdot"]
    gov = ["gov", "pib", "niti", "dpiit", "whitehouse", "europa", "congress"]
    blog = ["medium", "substack", "wordpress", "blogger", "ghost", "hashnode"]
    
    for domain in news:
        if domain in source_lower:
            return "News"
    for domain in academic:
        if domain in source_lower:
            return "Academic"
    for domain in social:
        if domain in source_lower:
            return "Social Media"
    for domain in forum:
        if domain in source_lower:
            return "Forum"
    for domain in gov:
        if domain in source_lower:
            return "Government"
    for domain in blog:
        if domain in source_lower:
            return "Blog"
    
    return "Other"
```

---

## TEST BLOCK

```python
if __name__ == "__main__":
    print("Running Stage 2 Reconciliation manually...")
    print("Make sure Ingestion Queue has entries (run ingestion.py first).")
    print("Make sure Source Name in Main KB is changed to 'Text' type.\n")
    
    summary = run_reconciliation()
    
    print(f"\n{'='*60}")
    print(f"RECONCILIATION SUMMARY")
    print(f"{'='*60}")
    print(f"Queue entries:        {summary['queue_entries']}")
    print(f"Analyzed by OpenAI:   {summary['analyzed']}")
    print(f"New in Main KB:       {summary['new_entries']}")
    print(f"Updated in Main KB:   {summary['updated_entries']}")
    print(f"Archived from queue:  {summary['archived_from_queue']}")
    if summary['errors']:
        print(f"Errors:               {len(summary['errors'])}")
        for e in summary['errors']:
            print(f"  - {e}")
    print(f"{'='*60}")
```

---

## EDGE CASES

### Empty Ingestion Queue
Return immediately with all zeros. No OpenAI or Notion API calls.

### OpenAI returns fewer analyses than input
Match by index for what we have. Log warning. Unmatched queue entries stay in the queue (not archived) for retry next cycle.

### Create/update fails for individual entry
Log error, continue to next entry. Don't archive the failed entry — it stays in the queue for retry.

### URL is None or empty
Treat as new entry (can't match against Main KB without a URL). Create in Main KB without URL field.

### Very large queue (100+ entries)
OpenAI batching handles the analysis. Notion writes are sequential with `time.sleep(0.35)`. Processing 100 entries takes ~3-5 minutes. This is fine.

### Re-running reconciliation on empty queue
Returns immediately. No side effects. Safe to run multiple times.

### Change log gets very long
Notion rich text supports ~100K characters. Not a practical concern. If needed later, truncate old entries.

### Multi-select merge produces duplicates
`set()` deduplicates entity and tag names. Order may change but values are unique.