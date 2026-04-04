# MOD 07: AI Summary on Extract

## Objective
When "Extract Content" is checked on a Main KB entry, the pipeline extracts full content via Parallel, writes it as page body blocks on the entry itself, generates a ~1000 word AI summary via one OpenAI call, and writes it to a new `AI Summary` property. Simple, no new databases, no data destruction.

---

## What changes

| File | Change |
|---|---|
| **Notion UI** | Manually add `AI Summary` (Text) property to Main KB |
| `extract.py` | Rewrite extract flow: extract → write body blocks → summarize → write AI Summary |
| `openai_client.py` | Add `summarize_content()` function |
| `notion_client.py` | No changes (append_blocks already exists) |

---

## MANUAL STEP (before handing to OpenCode)

Add one property to Main Knowledge Base in Notion:

1. Open Notion → Main Knowledge Base
2. Click `+` to add a property
3. Name: `AI Summary`
4. Type: Text (rich text)
5. Done

No other schema changes. No new databases. No re-running setup_notion.py.

---

## DESIGN

### Flow when Extract Content is checked

```
Entry has Extract Content = checked
    ↓
extract_url(url) → full content string
    ↓
append_blocks(entry_id, content_blocks) → write full article as page body
    ↓
summarize_content(content) → ~1000 word summary via gpt-4o-mini
    ↓
update_page(entry_id, {
    "AI Summary": summary text,
    "Full Content": "See page body",
    "Extract Content": False,
})
```

One checkbox in, everything happens automatically, checkbox unchecks when done.

### Where content lives

- **Full article text** → written as paragraph blocks in the page body (scroll down in Notion to read)
- **AI Summary** → written to the `AI Summary` rich text property (visible in table view)
- **Full Content property** → set to "See page body" (pointer text, since the old rich_text field can't hold 100K chars reliably)

### Why one summary call, not three

The extracted content IS the source of truth. One `gpt-4o-mini` call on that content produces a good summary. A second Parallel Task API call re-fetches the same URL through a different pipe — same content, extra cost, extra latency, marginal quality gain. If the first summary is good enough to act on (it is), one call is the right design.

---

## IMPLEMENTATION SPEC

### In `openai_client.py` — add:

#### `summarize_content(content: str, word_count: int = 1000) -> str`

```python
SUMMARIZE_SYSTEM_PROMPT = """You are a detail-oriented summarizer for a strategic intelligence system. Produce a comprehensive summary covering all major points, key findings, important details, and relevant context. Write in clear, professional prose. Prioritize completeness over brevity."""

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception_type((openai.RateLimitError, openai.APITimeoutError)),
    reraise=True,
)
def summarize_content(content: str, word_count: int = 1000) -> str:
    """
    Summarize text content using OpenAI gpt-4o-mini.
    
    For long content (>30K chars), splits into chunks, summarizes each,
    then combines with a final synthesis pass.
    
    Args:
        content: Full text content to summarize.
        word_count: Target word count (default 1000).
    
    Returns:
        Summary string of approximately word_count words.
    
    Raises:
        Exception if OpenAI call fails after retries.
    """
    CHUNK_SIZE = 30000
    
    # Short content — single call
    if len(content) <= CHUNK_SIZE:
        return _summarize_single(content, word_count)
    
    # Long content — chunk, summarize each, then synthesize
    chunks = [content[i:i+CHUNK_SIZE] for i in range(0, len(content), CHUNK_SIZE)]
    logger.info(f"summarize_content: {len(content)} chars → {len(chunks)} chunks")
    
    partials = []
    for i, chunk in enumerate(chunks):
        logger.info(f"  Summarizing chunk {i+1}/{len(chunks)}...")
        partial = _summarize_single(chunk, word_count=max(300, word_count // len(chunks)))
        partials.append(partial)
        if i < len(chunks) - 1:
            time.sleep(1)  # rate limit spacing
    
    # Final synthesis of all partials
    combined = "\n\n".join(f"Part {i+1}:\n{s}" for i, s in enumerate(partials))
    return _summarize_single(combined, word_count)


def _summarize_single(text: str, word_count: int) -> str:
    """Single OpenAI call to summarize text."""
    user_prompt = (
        f"Summarize the following content in approximately {word_count} words. "
        f"Be comprehensive — include key points, important details, and significant findings.\n\n"
        f"Content:\n{text[:25000]}"  # safety cap per call
    )
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SUMMARIZE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=1500,
    )
    
    result = response.choices[0].message.content
    if not result:
        raise Exception("Empty summary response from OpenAI")
    
    logger.info(f"  Summary: {len(result)} chars, "
               f"{response.usage.prompt_tokens}+{response.usage.completion_tokens} tokens")
    return result
```

### In `extract.py` — rewrite the inner loop of `run_extract_poll()`:

Replace the existing per-entry processing logic with:

```python
for entry in entries:
    url = entry.get("URL")
    entry_id = entry.get("id")
    title = entry.get("Title", "Unknown")
    
    if not url:
        logger.warning(f"Entry '{title}' has no URL — skipping")
        update_page(entry_id, {"Extract Content": {"checkbox": False}})
        summary["failed"] += 1
        continue
    
    logger.info(f"Processing: {title[:60]}...")
    
    # Step 1: Extract full content via Parallel
    content = extract_url(url)
    if not content:
        logger.warning(f"  Extraction failed for: {title[:60]}")
        update_page(entry_id, {"Extract Content": {"checkbox": False}})
        summary["failed"] += 1
        continue
    
    # Truncate very long content
    if len(content) > 95000:
        content = content[:95000] + "\n\n[Content truncated — full article at URL]"
    
    logger.info(f"  Extracted {len(content)} chars")
    
    # Step 2: Write full content as page body blocks
    try:
        blocks = _content_to_blocks(content)
        append_blocks(entry_id, blocks)
        logger.info(f"  Written as {len(blocks)} body blocks")
    except Exception as e:
        logger.error(f"  Failed to write body blocks: {e}")
        # Continue anyway — try to summarize what we have
    
    # Step 3: Generate AI summary via OpenAI
    ai_summary = None
    try:
        from openai_client import summarize_content
        ai_summary = summarize_content(content)
        logger.info(f"  AI summary: {len(ai_summary)} chars")
    except Exception as e:
        logger.error(f"  AI summary failed: {e}")
    
    # Step 4: Update the Main KB entry
    update_props = {
        "Extract Content": {"checkbox": False},
    }
    
    if ai_summary:
        update_props["AI Summary"] = {"rich_text": _format_rich_text(ai_summary)}
    
    # Mark Full Content field with pointer text
    update_props["Full Content"] = {"rich_text": _format_rich_text("See page body")}
    
    try:
        update_page(entry_id, update_props)
    except Exception as e:
        logger.error(f"  Failed to update entry: {e}")
        # At minimum uncheck the box
        try:
            update_page(entry_id, {"Extract Content": {"checkbox": False}})
        except:
            pass
        summary["failed"] += 1
        continue
    
    summary["extracted"] += 1
    logger.info(f"  Complete: {title[:60]}")
    
    time.sleep(0.5)
```

#### Add `_content_to_blocks()` helper to `extract.py`:

```python
def _content_to_blocks(content: str) -> list[dict]:
    """
    Convert plain text into Notion paragraph blocks.
    Each block max 2000 chars (Notion limit).
    """
    blocks = []
    for i in range(0, len(content), 2000):
        chunk = content[i:i+2000]
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": chunk}}]
            }
        })
    return blocks
```

#### Update imports in `extract.py`:

Make sure these are imported:
```python
from notion_client import update_page, query_database, parse_page_properties, append_blocks, _format_rich_text
from parallel_client import extract_url
from config import get_database_id
```

The `summarize_content` import from `openai_client` is done lazily inside the loop (so extract still works if OpenAI is down — it just skips the summary).

---

## TEST BLOCK

Replace the existing `if __name__ == "__main__":` block in `extract.py`:

```python
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "watch":
        run_extract_continuous(poll_interval=10)
    else:
        # --- Test 1: Direct extraction + summary ---
        print("Test 1: Extract and summarize a URL directly...")
        from parallel_client import extract_url
        from openai_client import summarize_content
        
        content = extract_url("https://en.wikipedia.org/wiki/Robotics")
        if content:
            print(f"  Extracted: {len(content)} chars")
            print(f"  Generating AI summary...")
            summary = summarize_content(content)
            print(f"  Summary: {len(summary)} chars")
            print(f"\n  First 500 chars of summary:")
            print(f"  {summary[:500]}...")
            print("\n  Direct extract+summarize: PASSED")
        else:
            print("  Extraction failed — check API key")
        
        # --- Test 2: Poll for checked entries ---
        print("\nTest 2: Polling Main KB for Extract Content = checked...")
        result = run_extract_poll()
        print(f"  Checked: {result['checked_entries']}")
        print(f"  Extracted: {result['extracted']}")
        print(f"  Failed: {result['failed']}")
        
        if result['checked_entries'] == 0:
            print("  No entries had Extract Content checked.")
            print("  To test: check the box on an entry in Notion, then run again.")
        
        print("\nAll extract tests completed!")
```

---

## WHAT THE USER SEES IN NOTION

After checking "Extract Content" and running `python main.py extract`:

1. **Extract Content** checkbox → automatically unchecked
2. **Full Content** property → shows "See page body"
3. **AI Summary** property → ~1000 word comprehensive summary (visible in table view)
4. **Page body** (scroll down inside the entry) → full article text as paragraphs

The AI Summary is scannable in the table. The full content is available if you want to dig deeper by opening the entry.

---

## EDGE CASES

### Content too short (<100 chars)
Some extractions return near-empty content (navigation only, paywalled). If content is under 100 chars, skip the summary and write "Content too short for summary" to AI Summary.

Add this check after Step 1:
```python
if len(content.strip()) < 100:
    logger.warning(f"  Content too short ({len(content)} chars) — skipping summary")
    update_page(entry_id, {
        "Extract Content": {"checkbox": False},
        "AI Summary": {"rich_text": _format_rich_text("Content too short for summary.")},
    })
    summary["failed"] += 1
    continue
```

### Body blocks already exist on entry
If you extract the same entry twice, body blocks are APPENDED (not replaced). This means duplicate content in the page body. Not harmful but messy. The user should only check the box once per entry.

### OpenAI fails but extraction succeeds
The full content is still written as body blocks. AI Summary field stays empty. The user has the full content to read manually. Not ideal, but nothing is lost.

### Very long content (>95K chars)
Truncated before processing. The summary covers the first 95K chars which is the vast majority of any article.

### Rate limiting
`time.sleep(0.5)` between entries. OpenAI retries handle TPM limits. For the chunked summarization path (content > 30K chars), `time.sleep(1)` between chunks.

---

## COST

- Parallel Extract: $0.001 per URL (negligible)
- OpenAI Summary: ~$0.005 per article (gpt-4o-mini, ~8K input tokens + 1.5K output)
- Total per extraction: ~$0.006