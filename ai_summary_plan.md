# AI Summary + Full Content Extracts — Implementation Plan

## Architecture Overview

### What We're Building
Auto-triggered AI summarization pipeline: when "Extract Content" is checked on a Main KB entry, the system:
1. Extracts full content via Parallel API → stores as a page in new `Full Content Extracts` Notion database
2. Sets `Full Content Available` checkbox
3. Auto-triggers a 3-step summary process:
   - **Summary 1**: Summarize stored full content via OpenAI (chunked for long content)
   - **Summary 2**: Fresh URL summary via Parallel Task API
   - **Meta Summary**: Combine best points from both → write to `AI Summary` property
4. Tracks progress via 4 checkboxes on the Main KB entry

### Notion Schema Changes

#### New Database: `Full Content Extracts`
| Property | Type | Notes |
|---|---|---|
| Title | title | From original Main KB entry |
| URL | url | Source URL |
| Source Entry | relation → Main KB | Links back to source entry |
| Extracted Date | date | When content was stored |
| Source | select: Original / Fresh | Distinguishes stored vs fresh extract |

#### Updated Main KB Schema
| Property | Type | Change |
|---|---|---|
| Extract Content | checkbox | No change |
| Full Content | **relation → Full Content Extracts** | **REPLACED** (was rich_text) |
| AI Summary | rich_text | **NEW** — final polished ~1000 word output |
| Full Content Available | checkbox | **NEW** |
| Summary 1 Available | checkbox | **NEW** |
| Summary 2 Available | checkbox | **NEW** |
| Meta Summary Available | checkbox | **NEW** |

### Data Flow

```
Main KB Entry (Extract Content = checked)
       ↓
   extract_url(url) → content
       ↓
   create_content_store_page() in Full Content Extracts DB
       ↓
   append_blocks() — write content as body blocks
       ↓
   update_page() — set Full Content relation on Main KB entry
       ↓
   update_page() — Full Content Available = True, Extract Content = False
       ↓
   AUTO-TRIGGER: generate_ai_summary(entry_id, url, store_page_id)
       ↓
   ┌─────────────────────────────────────────────┐
   │ STEP 1: Summary 1                            │
   │ read_page_content(store_page_id)            │
   │ → summarize_chunked() via OpenAI            │
   │ → ~1000 words                               │
   │ → update_page(Main KB, Summary 1 Available) │
   └─────────────────────────────────────────────┘
       ↓
   ┌─────────────────────────────────────────────┐
   │ STEP 2: Summary 2                           │
   │ summarize_url_via_task(url) via Parallel   │
   │ Task API (fresh AI analysis of URL)         │
   │ → ~1000 words                               │
   │ → update_page(Main KB, Summary 2 Available) │
   └─────────────────────────────────────────────┘
       ↓
   ┌─────────────────────────────────────────────┐
   │ STEP 3: Meta Summary                        │
   │ gpt-4o-mini combine(S1, S2) — best points   │
   │ → ~1000 words                               │
   │ → update_page(Main KB, AI Summary +         │
   │     Meta Summary Available = True)         │
   └─────────────────────────────────────────────┘
```

---

## Detailed Implementation

### PHASE 1: Database Setup (`setup_notion.py`)

#### 1.1 `build_full_content_store_properties(main_kb_id)` — NEW function

Add above `build_synthesis_properties()`:

```python
def build_full_content_store_properties(main_kb_id: str) -> dict:
    """Build properties for Full Content Extracts database (5 properties)."""
    return {
        "Title": {"title": {}},
        "URL": {"url": {}},
        "Source Entry": {
            "relation": {
                "database_id": main_kb_id,
                "single_property": {},
            }
        },
        "Extracted Date": {"date": {}},
        "Source": {
            "select": {
                "options": [
                    {"name": "Original", "color": "blue"},
                    {"name": "Fresh", "color": "green"},
                ]
            }
        },
    }
```

#### 1.2 `build_main_kb_properties()` — REPLACE Full Content field

Current lines 242-244:
```python
"Extract Content": {"checkbox": {}},
"Full Content": {"rich_text": {}},
```

Replace with:
```python
"Extract Content": {"checkbox": {}},
"Full Content": {
    "relation": {
        "database_id": main_kb_id,  # temporary; PATCH after store created
        "single_property": {},
    }
},
"AI Summary": {"rich_text": {}},
"Full Content Available": {"checkbox": {}},
"Summary 1 Available": {"checkbox": {}},
"Summary 2 Available": {"checkbox": {}},
"Meta Summary Available": {"checkbox": {}},
```

**Note**: `database_id` in the relation is temporarily set to `main_kb_id` — it will be PATCHed to the actual `full_content_store_id` after creation.

#### 1.3 `main()` — Creation order update

Current order (lines 377-404):
1. Main KB
2. Synthesis
3. Brief Log
4. PATCH Synthesis (Surfaced In Brief)
5. Ingestion Queue

**New order**:
```python
main_kb_id = create_database(page_id, "Main Knowledge Base", build_main_kb_properties())
time.sleep(0.35)

full_content_store_id = create_database(page_id, "Full Content Extracts", build_full_content_store_properties(main_kb_id))
time.sleep(0.35)

synthesis_id = create_database(page_id, "Synthesis Database", build_synthesis_properties(main_kb_id))
time.sleep(0.35)

brief_log_id = create_database(page_id, "Brief Log", build_brief_log_properties(main_kb_id, synthesis_id))
time.sleep(0.35)

# PATCH Main KB to fix Full Content relation database_id
update_database(main_kb_id, {
    "Full Content": {
        "relation": {
            "database_id": full_content_store_id,
            "single_property": {},
        }
    }
})
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

ingestion_queue_id = create_database(page_id, "Ingestion Queue", build_ingestion_queue_properties())
```

#### 1.4 `database_ids` output dict — Add full_content_store

```python
database_ids = {
    "main_kb": main_kb_id,
    "full_content_store": full_content_store_id,
    "synthesis": synthesis_id,
    "brief_log": brief_log_id,
    "ingestion_queue": ingestion_queue_id,
}
```

#### 1.5 Execution note

⚠️ **WARNING**: Running `setup_notion.py` prompts "Database IDs already exist. Delete and recreate?" — answering "yes" DELETES all existing Notion data (202 Main KB entries, 5 synthesis, 5 brief log, queue).

**Alternative if data must be preserved**: Manually create `Full Content Extracts` DB in Notion UI, get its ID, add to `database_ids.json` manually, then PATCH Main KB via API to add new properties without deleting data.

---

### PHASE 2: `config.py` Changes

No structural changes needed — `load_database_ids()` and `save_database_ids()` handle arbitrary keys. After `setup_notion.py` runs, `get_database_id("full_content_store")` works automatically.

Optional constant (not required):
```python
FULL_CONTENT_STORE_DB_NAME = "full_content_store"
```

---

### PHASE 3: `notion_client.py` Changes

#### 3.1 New `create_content_store_page()` function

```python
def create_content_store_page(
    db_id: str,
    title: str,
    url: str,
    entry_id: str,
    extracted_date: Optional[str] = None,
    source: str = "Original",
) -> str:
    """
    Create a page in the Full Content Extracts database.

    Args:
        db_id: Database ID for Full Content Extracts
        title: Title from the original Main KB entry
        url: Source URL
        entry_id: Page ID of the source Main KB entry (for relation)
        extracted_date: ISO date string (default: now in IST)
        source: "Original" or "Fresh"

    Returns:
        The new page ID
    """
    from datetime import datetime, timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))

    if not extracted_date:
        extracted_date = datetime.now(IST).strftime("%Y-%m-%d")

    properties = build_page_properties(
        title=title,
        url=url,
        relation_fields={"Source Entry": [entry_id]},
        date_fields={"Extracted Date": extracted_date},
        select_fields={"Source": source},
        title_property_name="Title",
    )
    return create_page(db_id, properties)
```

**Note**: `build_page_properties()` already supports `relation_fields`, `date_fields`, `select_fields` — no changes needed to that function.

#### 3.2 Confirm existing functions

- **`append_blocks(page_id, blocks)`** — Already exists at line 539. Splits into batches of 100, appends to page body. Used in `curation.py` for brief writing. Confirmed working.
- **`update_page(page_id, properties)`** — Already exists. Handles relation property setting via standard Notion PATCH API.
- **`_format_rich_text(text)`** — Already exists at line 51. Splits into 2000-char chunks. Used in `extract.py` for AI Summary writing.

---

### PHASE 4: `parallel_client.py` Changes

#### 4.1 New `summarize_url_via_task()` function

```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception(lambda e: isinstance(e, httpx.HTTPStatusError) and (e.response.status_code == 429 or 500 <= e.response.status_code < 600)),
    reraise=True,
)
def summarize_url_via_task(url: str, processor: str = "base") -> Optional[str]:
    """
    Summarize a URL using Parallel's Task API.

    The Task API crawls the URL and uses AI inference to produce
    a structured summary — essentially "AI over any URL."

    Args:
        url: The URL to summarize
        processor: "lite", "base", "core", "pro", or "ultra" (default "base")
                  Higher = deeper research but slower/more expensive

    Returns:
        Summary text (approximately 500-1000 words), or None on failure
    """
    client = _get_client()

    payload = {
        "input": f"Summarize the following webpage in detail (approximately 1000 words): {url}",
        "processor": processor,
        "task_spec": {
            "output_schema": {
                "type": "text",
            }
        },
    }

    # Create the task run
    response = client.post("/v1/tasks/runs", json=payload)
    result = _handle_response(response)

    run_id = result.get("run_id")

    if not run_id:
        logger.error(f"Task API response missing run_id: {result}")
        return None

    logger.info(f"Task run created: {run_id} for URL: {url[:60]}")

    # Poll for result (blocking, with timeout)
    max_wait = 120  # seconds
    poll_interval = 3
    elapsed = 0

    while elapsed < max_wait:
        time.sleep(poll_interval)
        elapsed += poll_interval

        status_resp = client.get(f"/v1/tasks/runs/{run_id}")
        status_data = _handle_response(status_resp)

        status = status_data.get("status", "")
        if status == "completed":
            output = status_data.get("output", "")
            if isinstance(output, dict):
                output = output.get("text", "") or str(output)
            logger.info(f"Task completed for {url[:60]}: {len(output)} chars")
            return output
        elif status in ("failed", "cancelled", "expired"):
            logger.error(f"Task {run_id} ended with status: {status}")
            return None
        else:
            logger.debug(f"Task {run_id} status: {status} (waited {elapsed}s)")

    logger.error(f"Task {run_id} timed out after {max_wait}s")
    return None
```

**Key decisions**:
- `processor="base"` default (deep research uses "core" or "ultra" — more expensive)
- `output_schema.type="text"` gives plain text output
- `max_wait=120` seconds timeout
- `poll_interval=3` seconds between status checks

**API endpoints confirmed**:
- `POST /v1/tasks/runs` — create task run
- `GET /v1/tasks/runs/{run_id}` — poll for result

---

### PHASE 5: `openai_client.py` Changes

#### 5.1 Constants and prompts — Add above existing code

```python
SUMMARIZE_SYSTEM_PROMPT = """You are a detail-oriented summarizer. Your job is to produce a detailed, comprehensive summary of the provided text content. Cover all major points, key findings, important details, and relevant context. Write in a clear, professional style. Aim for depth over brevity while remaining focused and relevant."""

SUMMARIZE_USER_PROMPT_TEMPLATE = """Summarize the following content in approximately {word_count} words. Be comprehensive — include key points, important details, and significant findings. Do not omit critical information.

Content:
{content}

Summary:"""

META_SUMMARY_SYSTEM_PROMPT = """You are a senior intelligence analyst. Your job is to produce a polished, unified summary by combining two independent summaries of the same article. Select the BEST and most IMPORTANT points from BOTH summaries. Eliminate redundancy. Ensure the final output is comprehensive, accurate, and well-structured. Write approximately 1000 words."""
```

#### 5.2 New `summarize_chunked()` function

```python
def summarize_chunked(text: str, word_count: int = 1000) -> str:
    """
    Summarize long text by chunking and summarizing each piece.

    Splits text into ~30,000 character chunks (stays within context limits
    and TPM), summarizes each, and concatenates all partial summaries.
    For very long content, a final synthesis pass combines all parts.

    Args:
        text: Full content text to summarize
        word_count: Target word count for the summary (approximately)
                    Default 1000 words

    Returns:
        Summary text of approximately word_count words
    """
    CHUNK_SIZE = 30000

    if len(text) <= CHUNK_SIZE:
        return _summarize_single(text, word_count)

    chunks = []
    for i in range(0, len(text), CHUNK_SIZE):
        chunks.append(text[i:i+CHUNK_SIZE])

    logger.info(f"summarize_chunked: splitting {len(text)} chars into {len(chunks)} chunks")

    partial_summaries = []
    for idx, chunk in enumerate(chunks):
        logger.info(f"  Summarizing chunk {idx+1}/{len(chunks)} ({len(chunk)} chars)")
        summary = _summarize_single(chunk, word_count=word_count // len(chunks) + 100)
        partial_summaries.append(summary)
        if idx < len(chunks) - 1:
            time.sleep(1)

    if len(partial_summaries) == 1:
        return partial_summaries[0]

    combined = "\n\n".join(f"Part {i+1}:\n{s}" for i, s in enumerate(partial_summaries))
    final = _summarize_single(combined, word_count=word_count)
    return final


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception_type((openai.RateLimitError, openai.APITimeoutError)),
    reraise=True,
)
def _summarize_single(text: str, word_count: int) -> str:
    """Single LLM call to summarize text."""
    user_prompt = SUMMARIZE_USER_PROMPT_TEMPLATE.format(
        content=text[:25000],  # safety limit per call
        word_count=word_count,
    )

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SUMMARIZE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=1500,  # ~1000 words + buffer
    )

    content = response.choices[0].message.content
    if content is None:
        raise Exception("Empty summary response from OpenAI")

    logger.info(f"  Single summary: {len(content)} chars, "
                f"{response.usage.prompt_tokens} prompt / "
                f"{response.usage.completion_tokens} completion tokens")
    return content
```

**Key decisions**:
- `CHUNK_SIZE=30000` chars per chunk (safe within context and TPM limits)
- `max_tokens=1500` for ~1000 word output
- `time.sleep(1)` between chunks to prevent rate limiting

#### 5.3 New `generate_ai_summary()` function

```python
def generate_ai_summary(entry_id: str, url: str, store_page_id: str) -> dict:
    """
    Orchestrate the full 3-step summary pipeline for a Main KB entry.

    Steps:
    1. Summary 1: Read stored full content from full_content_store page,
       summarize via OpenAI gpt-4o-mini (chunked for long content)
    2. Summary 2: Fresh URL summary via Parallel Task API
    3. Meta Summary: Combine both summaries via OpenAI, write to AI Summary

    Progress tracked via checkboxes on the Main KB entry:
    - Summary 1 Available (set after S1 done)
    - Summary 2 Available (set after S2 done)
    - Meta Summary Available (set after meta done)
    - AI Summary (rich_text) — the final polished output

    Args:
        entry_id: Main KB entry page ID
        url: Source URL (for Summary 2 fresh call)
        store_page_id: Page ID of the full_content_store page

    Returns:
        Dict:
        {
            "success": bool,
            "summary_1_done": bool,
            "summary_2_done": bool,
            "meta_done": bool,
            "summary_1_text": str or None,
            "summary_2_text": str or None,
            "ai_summary": str or None,
            "errors": list[str],
        }
    """
    from notion_client import read_page_content, update_page, _format_rich_text

    result = {
        "success": False,
        "summary_1_done": False,
        "summary_2_done": False,
        "meta_done": False,
        "summary_1_text": None,
        "summary_2_text": None,
        "ai_summary": None,
        "errors": [],
    }

    # --- STEP 1: Summary 1 from stored content ---
    try:
        logger.info(f"Generating Summary 1 for entry {entry_id[:20]}...")
        stored_content = read_page_content(store_page_id)
        if stored_content and len(stored_content.strip()) > 100:
            summary_1 = summarize_chunked(stored_content, word_count=1000)
            result["summary_1_text"] = summary_1
            result["summary_1_done"] = True
            update_page(entry_id, {"Summary 1 Available": {"checkbox": True}})
            logger.info(f"  Summary 1 done: {len(summary_1)} chars")
        else:
            logger.warning(f"  Stored content empty or too short for entry {entry_id[:20]}")
            result["errors"].append("Stored content empty or too short")
    except Exception as e:
        logger.error(f"  Summary 1 failed: {e}")
        result["errors"].append(f"Summary 1 failed: {e}")

    # --- STEP 2: Summary 2 from fresh URL via Parallel Task API ---
    try:
        logger.info(f"Generating Summary 2 via Parallel Task API for {url[:60]}...")
        from parallel_client import summarize_url_via_task
        summary_2 = summarize_url_via_task(url, processor="base")
        if summary_2 and len(summary_2.strip()) > 50:
            result["summary_2_text"] = summary_2
            result["summary_2_done"] = True
            update_page(entry_id, {"Summary 2 Available": {"checkbox": True}})
            logger.info(f"  Summary 2 done: {len(summary_2)} chars")
        else:
            logger.warning(f"  Summary 2 returned empty for {url[:60]}")
            result["errors"].append("Summary 2 returned empty")
    except Exception as e:
        logger.error(f"  Summary 2 failed: {e}")
        result["errors"].append(f"Summary 2 failed: {e}")

    # --- STEP 3: Meta Summary combining both ---
    if not result["summary_1_done"] and not result["summary_2_done"]:
        # Nothing to combine — write error note
        error_note = "AI summary generation failed: both summaries unavailable."
        result["ai_summary"] = error_note
        update_page(entry_id, {"AI Summary": {"rich_text": _format_rich_text(error_note)}})
        logger.error(f"No summaries available for entry {entry_id[:20]}")
        return result

    try:
        logger.info("Generating Meta Summary...")

        if result["summary_1_done"] and result["summary_2_done"]:
            meta_prompt = f"""You are a senior intelligence analyst. Your job is to produce a polished, unified summary by combining two independent summaries of the same article. Select the BEST and most IMPORTANT points from BOTH summaries. Eliminate redundancy. Ensure the final output is comprehensive, accurate, and well-structured. Write approximately 1000 words.

Summary 1 (from stored full content):
{result['summary_1_text']}

Summary 2 (from fresh URL analysis):
{result['summary_2_text']}

Final Unified Summary:"""
        elif result["summary_1_done"]:
            meta_prompt = f"""You are a senior intelligence analyst. Only one summary was successfully generated. Polish and expand it into a comprehensive ~1000 word summary.

Summary (from stored content):
{result['summary_1_text']}

Final Summary:"""
        else:
            meta_prompt = f"""You are a senior intelligence analyst. Only one summary was successfully generated. Polish and expand it into a comprehensive ~1000 word summary.

Summary (from fresh URL analysis):
{result['summary_2_text']}

Final Summary:"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": META_SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": meta_prompt},
            ],
            temperature=0.3,
            max_tokens=1500,
        )

        ai_summary = response.choices[0].message.content
        if ai_summary is None:
            raise Exception("Empty meta summary response")

        result["ai_summary"] = ai_summary
        result["meta_done"] = True

        update_page(entry_id, {
            "AI Summary": {"rich_text": _format_rich_text(ai_summary)},
            "Meta Summary Available": {"checkbox": True},
        })
        logger.info(f"  Meta summary done: {len(ai_summary)} chars")

    except Exception as e:
        logger.error(f"  Meta summary failed: {e}")
        result["errors"].append(f"Meta summary failed: {e}")
        # Write what we have as fallback
        fallback = result["summary_1_text"] or result["summary_2_text"] or "Summary generation failed."
        if not result["summary_1_done"] and not result["summary_2_done"]:
            fallback += "\n\n[Note: Both summaries were unavailable]"
        elif not result["meta_done"]:
            fallback += "\n\n[Note: Meta-summary generation failed — this is a partial summary]"
        result["ai_summary"] = fallback
        update_page(entry_id, {"AI Summary": {"rich_text": _format_rich_text(fallback)}})

    result["success"] = result["meta_done"]
    return result
```

---

### PHASE 6: `extract.py` Changes

#### 6.1 New `_content_to_blocks()` helper

```python
MAX_BLOCK_CHARS = 2000

def _content_to_blocks(content: str) -> list:
    """
    Convert plain text content into Notion paragraph blocks.
    Splits into 2000-char chunks for Notion's block limit.

    Args:
        content: Full text content to convert

    Returns:
        List of Notion block objects ready for append_blocks()
    """
    blocks = []
    for i in range(0, len(content), MAX_BLOCK_CHARS):
        chunk = content[i:i+MAX_BLOCK_CHARS]
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": chunk}}]
            }
        })
    return blocks
```

#### 6.2 Rewire `run_extract_poll()` — New flow

Replace the inner loop (current lines 55-89) with:

```python
for entry in entries:
    url = entry.get("URL")
    entry_id = entry.get("id")
    title = entry.get("Title", "Unknown")

    if not url:
        update_page(entry_id, {"Extract Content": {"checkbox": False}})
        summary["failed"] += 1
        summary["errors"].append(f"Entry '{title}': no URL")
        continue

    # Step 1: Extract full content
    content = extract_url(url)
    if not content:
        update_page(entry_id, {"Extract Content": {"checkbox": False}})
        summary["failed"] += 1
        summary["errors"].append(f"Extract failed for '{title}'")
        continue

    if len(content) > MAX_CONTENT_CHARS:
        content = content[:MAX_CONTENT_CHARS] + "\n\n[Content truncated]"

    # Step 2: Create full_content_store page
    try:
        full_content_store_db = get_database_id("full_content_store")
        store_page_id = create_content_store_page(
            db_id=full_content_store_db,
            title=title,
            url=url,
            entry_id=entry_id,
            source="Original",
        )
    except Exception as e:
        logger.error(f"  Failed to create content store page for '{title}': {e}")
        update_page(entry_id, {"Extract Content": {"checkbox": False}})
        summary["failed"] += 1
        summary["errors"].append(f"Content store creation failed for '{title}': {e}")
        continue

    # Step 3: Write content as body blocks
    try:
        blocks = _content_to_blocks(content)
        append_blocks(store_page_id, blocks)
    except Exception as e:
        logger.error(f"  Failed to write content blocks for '{title}': {e}")
        summary["errors"].append(f"Content block write failed for '{title}': {e}")
        # Continue anyway — content is already in store page

    # Step 4: Set Full Content relation on Main KB entry
    try:
        update_page(entry_id, {
            "Full Content": {"relation": [{"id": store_page_id}]},
            "Extract Content": {"checkbox": False},
            "Full Content Available": {"checkbox": True},
        })
    except Exception as e:
        logger.error(f"  Failed to update Main KB entry relation for '{title}': {e}")
        update_page(entry_id, {"Extract Content": {"checkbox": False}})
        summary["failed"] += 1
        summary["errors"].append(f"Relation update failed for '{title}': {e}")
        continue

    summary["extracted"] += 1
    logger.info(f"  Extracted and stored {len(content)} chars for: {title[:60]}")

    # Step 5: Auto-trigger AI summary generation
    try:
        from openai_client import generate_ai_summary
        logger.info(f"  Auto-triggering AI summary for: {title[:60]}...")
        summary_result = generate_ai_summary(entry_id, url, store_page_id)
        if summary_result["success"]:
            logger.info(f"  AI summary complete for: {title[:60]}")
        else:
            logger.warning(f"  AI summary partial with errors: {summary_result['errors']}")
    except Exception as e:
        logger.error(f"  AI summary generation failed for '{title}': {e}")
        summary["errors"].append(f"AI summary failed for '{title}': {e}")

    time.sleep(0.5)
```

#### 6.3 Update imports

```python
from notion_client import (
    query_database,
    parse_page_properties,
    update_page,
    create_content_store_page,
    append_blocks,
    _format_rich_text,
)
from parallel_client import extract_url
# generate_ai_summary imported inside the function body (lazy import)
```

#### 6.4 Remove/update `MAX_CONTENT_CHARS`

The 95K char limit was for writing to a rich_text property. For body blocks via `append_blocks()`, the limit is much higher (handled by batching). Keep `MAX_CONTENT_CHARS = 95000` for the extract step — content is still truncated before storing, which is fine for AI summarization.

---

### PHASE 7: `health.py` Changes

**No code changes required.** Both `check_health()` and `print_health_report()` iterate over `db_ids.items()` from `load_database_ids()` — after `setup_notion.py` runs, `database_ids.json` will include `full_content_store` and it will be auto-included in all checks and counts.

The counts section will show:
```
--- Counts ---
main_kb: 202 | full_content_store: 0 | synthesis: 5 | brief_log: 5 | ingestion_queue: 0
```

---

### PHASE 8: `main.py` Changes

**No code changes required.** The `extract` and `extract-watch` commands already call `run_extract_poll()` and `run_extract_continuous()`. The new flow is transparent to the CLI.

---

## Error Handling

| Failure Point | Behavior |
|---|---|
| `extract_url()` returns None | Uncheck Extract Content, log error, skip to next entry |
| `create_content_store_page()` fails | Uncheck Extract Content, log error, skip |
| `append_blocks()` fails | Retry once, if still fails continue (content still in store page) |
| `update_page()` for relation fails | Retry once, if still fails uncheck Extract Content and log |
| `read_page_content()` for S1 fails | Set `Summary 1 Available = False`, proceed to S2 if available |
| `summarize_url_via_task()` for S2 fails | Set `Summary 2 Available = False`, proceed to meta with S1 only |
| `summarize_chunked()` fails | Set `Summary 1 Available = False`, proceed to S2 |
| Meta summary LLM call fails | Write S1+S2 raw as fallback to `AI Summary`, note failure |

---

## Execution Order

1. **PHASE 1**: Modify `setup_notion.py`
   - Add `build_full_content_store_properties()`
   - Update `build_main_kb_properties()` — replace Full Content rich_text with relation + 6 new fields
   - Update `main()` creation order
   - Add PATCH for Main KB Full Content relation after full_content_store creation

2. **Run setup_notion.py** (⚠️ prompts for deletion — see warning above)
   ```bash
   python3 setup_notion.py
   ```

3. **PHASE 3**: Modify `notion_client.py`
   - Add `create_content_store_page()`

4. **PHASE 4**: Modify `parallel_client.py`
   - Add `summarize_url_via_task()`

5. **PHASE 5**: Modify `openai_client.py`
   - Add SUMMARIZE prompts and `summarize_chunked()`
   - Add `generate_ai_summary()`

6. **PHASE 6**: Modify `extract.py`
   - Add `_content_to_blocks()` helper
   - Rewire `run_extract_poll()` to new flow
   - Update imports

7. **PHASE 7**: Verify `health.py` (no changes needed)

8. **TEST**: Find an entry with `Extract Content` checked (or manually check one), run:
   ```bash
   python3 main.py extract
   ```
   Verify:
   - `Full Content Extracts` page created with body content
   - Main KB entry has `Full Content` relation set
   - `Full Content Available` checkbox = True
   - `Summary 1 Available` checkbox = True
   - `Summary 2 Available` checkbox = True
   - `Meta Summary Available` checkbox = True
   - `AI Summary` rich_text property populated (~1000 words)

---

## Files to Modify

| File | Changes |
|---|---|
| `setup_notion.py` | Create `full_content_store` DB; update Main KB schema (6 new fields + relation) |
| `notion_client.py` | Add `create_content_store_page()` |
| `parallel_client.py` | Add `summarize_url_via_task()` |
| `openai_client.py` | Add `summarize_chunked()`, `generate_ai_summary()`, prompt constants |
| `extract.py` | Rewire to new flow: store → relation → auto-trigger summaries |

---

## Pending Confirmations

1. **setup_notion.py re-run**: Acceptable to delete and recreate (losing all existing data), or need manual approach?
2. **Parallel Task API endpoint**: Confirm `POST /v1/tasks/runs` + `GET /v1/tasks/runs/{run_id}` — should I verify with a live test before building?
3. **Task API processor level**: "base" as default, or "core"/"ultra" for better quality?
4. **Chunk size for summarize_chunked()**: 30,000 chars — acceptable?
5. **max_tokens for summaries**: 1500 for ~1000 word output — acceptable?