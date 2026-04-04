# CHUNK 17: Extract API — Full Content Extraction Triggered from Notion

## Objective
Build `extract.py` — a module that polls the Main Knowledge Base for entries where `Extract Content = checked`, calls Parallel's Extract API to get the full page content for that entry's URL, writes the content back to the `Full Content` field, and unchecks `Extract Content`. This gives you a "button" in Notion: check the box on any entry, and the full article content appears.

## Dependencies
- Chunk 3: `notion_client.query_database()`, `parse_page_properties()`
- Chunk 4: `notion_client.update_page()`
- Chunk 6: `parallel_client` (for API key and httpx pattern)

## What this chunk creates
- `extract.py` — new file
- Adds `extract()` function to `parallel_client.py`
- Updates `main.py` — adds "extract" command

---

## PARALLEL EXTRACT API REFERENCE

### Endpoint

```
POST https://api.parallel.ai/v1beta/extract
```

### Authentication

Same as Search API:
```python
headers = {
    "Content-Type": "application/json",
    "x-api-key": PARALLEL_API_KEY,
}
```

### Request Body

```json
{
  "urls": ["https://example.com/article"],
  "full_content": true,
  "excerpts": false
}
```

### Request Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `urls` | string[] | Yes | List of URLs to extract content from. Can be 1 or more. |
| `full_content` | boolean | No (default: false) | Include full page content. **Set to true for our use case.** |
| `excerpts` | boolean | No (default: true) | Include excerpts. Set to false since we want full content, not excerpts. |
| `objective` | string | No | If provided, focuses extraction on content relevant to this objective. |
| `fetch_policy` | object | No | Controls cached vs live fetching. |

### Response (200 OK)

```json
{
  "extract_id": "extract_8a911eb27c7a4afaa20d0d9dc98d07c0",
  "results": [
    {
      "url": "https://example.com/article",
      "title": "Article Title",
      "full_content": "Full text content of the page...\n\nParagraph 2...\n\nMore content..."
    }
  ],
  "errors": [
    {
      "url": "https://example.com/failed-url",
      "error_type": "fetch_error",
      "http_status_code": 500,
      "content": "Error fetching content from https://example.com/failed-url"
    }
  ]
}
```

### Response Fields

**results** (per URL):
| Field | Type | Description |
|---|---|---|
| `url` | string | The requested URL |
| `title` | string | Page title |
| `full_content` | string | Full extracted text content of the page |

**errors** (per failed URL):
| Field | Type | Description |
|---|---|---|
| `url` | string | The URL that failed |
| `error_type` | string | Type of error (e.g., `fetch_error`) |
| `http_status_code` | int | HTTP status from the target page |
| `content` | string | Error description |

A single request can have both results AND errors (some URLs succeed, some fail).

### Pricing

$1 per 1,000 URLs extracted. At single-entry usage (checking a box), cost is $0.001 per extraction — negligible.

### Latency

- Cached content: 1–3 seconds
- Live fetch: up to 60–90 seconds (if content isn't in Parallel's index)

---

## IMPLEMENTATION SPEC

### Add to `parallel_client.py`:

#### `extract_url(url: str) -> str | None`

```python
def extract_url(url: str) -> str | None:
    """
    Extract full page content from a URL using Parallel's Extract API.
    
    Args:
        url: The URL to extract content from.
    
    Returns:
        Full text content of the page as a string.
        None if extraction failed.
    
    Raises:
        Does NOT raise. Returns None on failure and logs the error.
    """
```

Implementation:
- Send `POST /v1beta/extract` with `{"urls": [url], "full_content": true, "excerpts": false}`
- Check response status
- If `results` array is non-empty, return `results[0]["full_content"]`
- If `errors` array is non-empty, log the error and return None
- If both are empty, return None
- Use tenacity retry for 429 and 5xx errors
- Timeout: 120 seconds (live fetches can be slow)

### File: `extract.py`

```python
"""
Extract module.
Polls Main KB for entries with Extract Content checked,
extracts full content via Parallel, and writes it back.
"""
```

### Functions to implement:

#### `run_extract_poll() -> dict`

```python
def run_extract_poll() -> dict:
    """
    Poll Main KB for entries with Extract Content = checked.
    For each one, extract the full content and write it back.
    
    Returns:
        Dict with summary:
        {
            "checked_entries": int,    # entries with Extract Content checked
            "extracted": int,          # successful extractions
            "failed": int,             # failed extractions
            "errors": list[str],       # error details
        }
    """
```

Implementation — step by step:

**Step 1: Query Main KB for entries with Extract Content checked**
```python
from notion_client import query_database, parse_page_properties, update_page
from parallel_client import extract_url
from config import get_database_id
import time

main_kb_id = get_database_id("main_kb")

pages = query_database(
    main_kb_id,
    filter={"property": "Extract Content", "checkbox": {"equals": True}},
)
entries = [parse_page_properties(p) for p in pages]
```

If no entries have the box checked, log and return early.

**Step 2: For each entry, extract and update**
```python
for entry in entries:
    url = entry.get("URL")
    if not url:
        logger.warning(f"Entry '{entry.get('Title')}' has no URL — skipping")
        continue
    
    logger.info(f"Extracting: {entry.get('Title', '')[:60]}...")
    
    # Call Parallel Extract API
    content = extract_url(url)
    
    if content:
        # Write content to Full Content field and uncheck Extract Content
        # Handle rich text 2000-char limit
        from notion_client import _format_rich_text
        rich_text_chunks = _format_rich_text(content)
        
        update_page(entry["id"], {
            "Full Content": {"rich_text": rich_text_chunks},
            "Extract Content": {"checkbox": False},
        })
        logger.info(f"  Extracted {len(content)} chars for: {entry.get('Title', '')[:60]}")
    else:
        # Extraction failed — uncheck anyway so it doesn't retry forever
        update_page(entry["id"], {
            "Extract Content": {"checkbox": False},
        })
        logger.warning(f"  Extraction failed for: {entry.get('Title', '')[:60]}")
    
    time.sleep(0.5)  # Rate limit between extractions
```

**Step 3: Return summary.**

#### `run_extract_continuous(poll_interval: int = 30) -> None`

```python
def run_extract_continuous(poll_interval: int = 30) -> None:
    """
    Continuously poll for extract requests.
    
    Runs in a loop, checking every poll_interval seconds for entries
    with Extract Content checked. Designed to run alongside the scheduler.
    
    Args:
        poll_interval: Seconds between polls (default 30).
    """
    logger.info(f"Extract poller started (checking every {poll_interval}s)")
    logger.info("Check 'Extract Content' on any Main KB entry to trigger extraction.")
    logger.info("Press Ctrl+C to stop.")
    
    while True:
        try:
            summary = run_extract_poll()
            if summary["checked_entries"] > 0:
                logger.info(f"Extract poll: {summary['extracted']} extracted, "
                           f"{summary['failed']} failed")
        except Exception as e:
            logger.error(f"Extract poll error: {e}")
        
        time.sleep(poll_interval)
```

---

## UPDATE main.py

Add "extract" command:

```python
if arg == "extract":
    from extract import run_extract_poll
    summary = run_extract_poll()
    print(f"\nExtract: {summary['extracted']} extracted, "
          f"{summary['failed']} failed out of "
          f"{summary['checked_entries']} checked entries")
    return

if arg == "extract-watch":
    from extract import run_extract_continuous
    run_extract_continuous()
    return
```

Add usage lines:
```python
logger.info("  python main.py extract       Run extract for checked entries")
logger.info("  python main.py extract-watch  Continuously poll for extract requests")
```

---

## HOW IT WORKS FOR THE USER

1. Open Main Knowledge Base in Notion
2. Find an entry you want to read the full article for
3. Check the "Extract Content" checkbox
4. Run `python main.py extract` (or have `extract-watch` running)
5. Within seconds, the "Full Content" field fills with the article text
6. The checkbox automatically unchecks

For continuous operation, run `python main.py extract-watch` in a separate terminal — it polls every 30 seconds.

---

## TEST BLOCK

```python
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "watch":
        run_extract_continuous(poll_interval=10)  # Faster polling for testing
    else:
        # --- Test 1: Extract a single URL ---
        print("Test 1: Extract a URL directly...")
        from parallel_client import extract_url
        
        content = extract_url("https://en.wikipedia.org/wiki/Robotics")
        if content:
            print(f"  Extracted {len(content)} chars")
            print(f"  First 200 chars: {content[:200]}...")
            print("  Direct extraction: PASSED")
        else:
            print("  Extraction returned None — API may be slow or URL inaccessible")
            print("  Direct extraction: FAILED")
        
        # --- Test 2: Run poll (check Main KB for flagged entries) ---
        print("\nTest 2: Polling Main KB for Extract Content = checked...")
        summary = run_extract_poll()
        print(f"  Checked entries: {summary['checked_entries']}")
        print(f"  Extracted: {summary['extracted']}")
        print(f"  Failed: {summary['failed']}")
        
        if summary['checked_entries'] == 0:
            print("  No entries had Extract Content checked.")
            print("  To test: check the box on an entry in Notion, then run again.")
        
        print("\nAll extract tests completed!")
```

---

## EDGE CASES

### No entries have Extract Content checked
Return immediately with zeros. Normal state — most of the time nobody is requesting extraction.

### URL is None or empty
Skip the entry, uncheck the box, log warning.

### Extraction returns very long content (>100K chars)
Notion rich text has a limit of approximately 100,000 characters per property. If content exceeds this, truncate to 95,000 characters and append "\n\n[Content truncated — full article at URL]". The `_format_rich_text()` function handles the 2000-char-per-chunk splitting.

### Extraction fails (URL unreachable, paywall, etc.)
Uncheck the box anyway so it doesn't retry forever. Log the failure. The user can check the box again to retry manually.

### Multiple entries checked simultaneously
Process them sequentially with `time.sleep(0.5)` between each. No parallelism needed.

### Entry deleted while extraction is running
`update_page()` will fail with 404. Catch and log, continue to next entry.

### Rate limiting
Extract API: $1/1K URLs, generous limits. At single-entry manual usage, rate limiting won't happen. The `time.sleep(0.5)` between entries is sufficient.

### Content includes HTML tags or markdown
Parallel's Extract API returns clean text, not raw HTML. But some pages may have residual formatting. The content is stored as-is in the rich text field.