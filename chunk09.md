# CHUNK 9: Ingestion Pipeline — Search → Dedupe → Write to Ingestion Queue

## Objective
Build `ingestion.py` — the complete Stage 1 pipeline that wires together search (Chunk 7), deduplication (Chunk 8), and writing to Notion (Chunk 2). This is the function that runs during each of the 4 daily search cycles. It also handles the dual retrieval strategy (Pass A: time-window, Pass B: relevance-ranked) and state tracking (last run timestamps).

## Dependencies
- Chunk 2 complete (notion_client.py with `create_page()`, `build_page_properties()`)
- Chunk 3 complete (notion_client.py with `query_database()`)
- Chunk 7 complete (parallel_client.py with `search_multiple()`)
- Chunk 8 complete (dedup.py with `deduplicate_against_db()`, `get_existing_entries()`)

## What this chunk creates
- `ingestion.py` — new file

---

## DESIGN

### The dual retrieval strategy

Each search cycle runs two passes:

**Pass A — Time-window sweep:**
- Uses `after_date` parameter set to the timestamp of the last completed search cycle
- Catches everything published since the last run
- Ensures completeness — nothing is missed between cycles

**Pass B — Relevance-ranked sweep:**
- No `after_date` filter
- Pulls the top results by topic relevance regardless of publish date
- Catches evergreen content, recently indexed older content, or items the time-window missed

The two passes are merged and deduplicated (against each other AND against the existing database) before writing to the Ingestion Queue.

### First run handling

On the very first run ever, there's no "last cycle" timestamp. The function detects this from `state.json` and:
- **Pass A:** Uses `after_date` = 7 days ago (a reasonable lookback for the first run)
- **Pass B:** Runs normally (no date filter)

After the first successful run, `state.json` is updated with the cycle timestamp.

### Cycle numbering

The 4 daily cycles are numbered 1–4:
- Cycle 1: 6:30 AM IST
- Cycle 2: 11:30 AM IST
- Cycle 3: 5:30 PM IST
- Cycle 4: 10:30 PM IST

During testing, the cycle number is passed as an argument. The scheduler (Chunk 16) will pass the correct number automatically.

---

## IMPLEMENTATION SPEC

### File: `ingestion.py`

```python
"""
Stage 1: Ingestion Pipeline.
Searches the web, deduplicates against existing entries,
and writes new entries to the Notion Ingestion Queue.
"""
```

### Functions to implement:

#### `run_ingestion(cycle_number: int) -> dict`

```python
def run_ingestion(cycle_number: int) -> dict:
    """
    Execute one complete ingestion cycle.
    
    Runs the dual retrieval strategy (Pass A + Pass B),
    deduplicates results against existing entries,
    and writes new entries to the Ingestion Queue.
    
    Args:
        cycle_number: Which cycle this is (1, 2, 3, or 4).
                     Used for logging and state tracking.
    
    Returns:
        Dict with cycle summary:
        {
            "cycle": int,
            "pass_a_results": int,     # results from time-window pass
            "pass_b_results": int,     # results from relevance pass
            "combined_raw": int,       # total before any dedup
            "after_cross_dedup": int,  # after deduping A vs B
            "duplicates_db": int,      # filtered by database dedup
            "new_entries": int,        # written to Ingestion Queue
            "errors": list[str],       # any non-fatal errors
        }
    
    Raises:
        Exception: Only if both passes fail completely.
                   Partial results from one pass are still written.
    """
```

Implementation requirements — step by step:

1. **Log cycle start:** `"=== Ingestion Cycle {cycle_number} Starting ==="`

2. **Load state:** Read `state.json` via `config.load_state()`. Get the last run timestamp for this cycle: `state.get("last_run", {}).get(f"cycle_{cycle_number}")`. If None, this is the first run for this cycle.

3. **Determine Pass A date filter:**
   - If last run timestamp exists: use it as `after_date` (the search should find content published after the last cycle)
   - If no last run (first run ever): use `(today - 7 days)` as `after_date`
   - Format as `YYYY-MM-DD` string

4. **Load topic:** Read `TOPIC` from `config.py`

5. **Run Pass A (time-window):**
   ```python
   results_a = search_multiple(
       topic=TOPIC,
       after_date=pass_a_date,
       max_results_per_query=10,
       num_variants=4,  # fewer variants for time-window (speed)
   )
   ```
   - If Pass A fails (exception), log the error, set `results_a = []`, continue to Pass B
   - Log: `"Pass A (time-window after {date}): {count} results"`

6. **Run Pass B (relevance-ranked):**
   ```python
   results_b = search_multiple(
       topic=TOPIC,
       after_date=None,  # no date filter
       max_results_per_query=10,
       num_variants=6,  # full variants for relevance
   )
   ```
   - If Pass B fails, log the error, set `results_b = []`
   - If BOTH passes failed, raise an exception
   - Log: `"Pass B (relevance-ranked): {count} results"`

7. **Merge Pass A and Pass B:**
   - Combine both lists
   - Deduplicate between them by URL (using `_normalize_url()` from parallel_client). Keep the Pass A version if a URL appears in both (it has the date-filtered context).
   - Add a `"retrieval_method"` field to each result: `"Time-window"` for Pass A results, `"Relevance-ranked"` for Pass B results, `"Both"` if found in both passes
   - Log: `"Combined: {raw_count} → {deduped_count} after cross-dedup"`

8. **Deduplicate against database:**
   ```python
   existing_urls, existing_titles = get_existing_entries(main_kb_id, iq_id)
   new_results, duplicates = deduplicate_against_db(
       combined_results, existing_urls, existing_titles
   )
   ```
   - Log: `"Database dedup: {len(duplicates)} duplicates filtered, {len(new_results)} new entries"`

9. **Write new entries to Ingestion Queue:**
   - For each new result, build properties and call `create_page()`:
     ```python
     props = build_page_properties(
         title=result["title"],
         url=result["url"],
         rich_text_fields={
             "Source Name": extract_source_name(result["url"]),
             "Raw Summary": result["excerpt_text"],
         },
         select_fields={
             "Retrieval Method": result["retrieval_method"],
             "Search Cycle": str(cycle_number),
         },
         date_fields={
             "Published Date": result.get("publish_date"),  # may be None
             "Discovered Date": datetime.now(IST).isoformat(),
         },
     )
     create_page(iq_id, props)
     ```
   - Add `time.sleep(0.35)` between writes to respect Notion rate limit
   - If a write fails, log the error and continue to the next entry. Don't abort the whole batch.
   - Track how many writes succeeded vs failed

10. **Update state:** Save the current timestamp to `state.json` for this cycle:
    ```python
    state = load_state()
    if "last_run" not in state:
        state["last_run"] = {}
    state["last_run"][f"cycle_{cycle_number}"] = datetime.now(IST).isoformat()
    if not state.get("first_run_complete"):
        state["first_run_complete"] = True
    save_state(state)
    ```

11. **Log cycle summary and return the summary dict**

#### `extract_source_name(url: str) -> str`

```python
def extract_source_name(url: str) -> str:
    """
    Extract a human-readable source name from a URL.
    
    Examples:
        "https://www.reuters.com/article/xyz" → "reuters.com"
        "https://techcrunch.com/2026/04/..." → "techcrunch.com"
        "https://arxiv.org/abs/2026.1234" → "arxiv.org"
    
    Returns the domain name without 'www.' prefix.
    """
```

Implementation: Use `urllib.parse.urlparse(url).netloc` and strip `www.` prefix. If URL is None or empty, return `"Unknown"`.

#### `_merge_passes(results_a: list[dict], results_b: list[dict]) -> list[dict]`

```python
def _merge_passes(results_a: list[dict], results_b: list[dict]) -> list[dict]:
    """
    Merge Pass A and Pass B results, deduplicate by URL,
    and tag each result with its retrieval method.
    
    If a URL appears in both passes, keep the Pass A version
    and tag it as "Both".
    
    Args:
        results_a: Results from time-window pass
        results_b: Results from relevance-ranked pass
    
    Returns:
        Merged and deduplicated list with "retrieval_method" field added.
    """
```

---

## TIMEZONE HANDLING

All timestamps in this pipeline use IST (India Standard Time, UTC+5:30). Use `datetime.timezone` from the standard library:

```python
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

# Current time in IST
now_ist = datetime.now(IST)

# Format for Notion date field
now_ist.isoformat()  # "2026-04-03T18:30:00+05:30"

# Format for Parallel after_date
now_ist.strftime("%Y-%m-%d")  # "2026-04-03"
```

Do NOT install `pytz` or any timezone library. The standard library `datetime.timezone` is sufficient.

---

## HANDLING NULL DATES

Parallel's Search API sometimes returns `publish_date: null`. When writing to Notion:
- If `publish_date` is None, skip the "Published Date" property entirely (don't pass it to `build_page_properties`). Notion will leave the field empty.
- The `date_fields` parameter in `build_page_properties` should handle None values: if a date value is None, don't include that field in the output dict.

Check if `build_page_properties()` already handles None dates. If not, add a guard:
```python
if date_fields:
    for field_name, date_value in date_fields.items():
        if date_value is not None:
            properties[field_name] = {"date": {"start": date_value}}
```

If `build_page_properties` from Chunk 2 doesn't handle this, update it. The spec for this chunk allows modifying `notion_client.py` to add None-handling to `build_page_properties`.

---

## TEST BLOCK

```python
if __name__ == "__main__":
    import sys
    
    # Accept optional cycle number from command line
    cycle = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    
    print(f"Running ingestion cycle {cycle} manually...")
    print(f"This will make real API calls to Parallel and write to Notion.")
    print()
    
    summary = run_ingestion(cycle)
    
    print(f"\n{'='*60}")
    print(f"CYCLE {summary['cycle']} SUMMARY")
    print(f"{'='*60}")
    print(f"Pass A (time-window): {summary['pass_a_results']} results")
    print(f"Pass B (relevance):   {summary['pass_b_results']} results")
    print(f"Combined raw:         {summary['combined_raw']}")
    print(f"After cross-dedup:    {summary['after_cross_dedup']}")
    print(f"DB duplicates:        {summary['duplicates_db']}")
    print(f"New entries written:  {summary['new_entries']}")
    if summary['errors']:
        print(f"Errors:               {len(summary['errors'])}")
        for e in summary['errors']:
            print(f"  - {e}")
    print(f"{'='*60}")
```

---

## EDGE CASES

### First run — no state.json
`load_state()` returns `{}`. The function defaults to 7-day lookback for Pass A. After the run, `state.json` is created with the first timestamp.

### Both passes fail
If both `search_multiple()` calls raise exceptions, `run_ingestion()` should raise an exception with a message like "Both search passes failed. Pass A: {error}. Pass B: {error}."

### All results are duplicates
After dedup, zero new entries. The function writes nothing to Notion, logs a warning, and returns `new_entries: 0`. This is not an error — it means the database is already up to date.

### Write failures during batch
If `create_page()` fails for some entries (e.g., Notion rate limit despite sleep), log each failure and continue. The summary should show how many writes succeeded vs failed. The non-written entries are lost — they'll be found again in the next cycle.

### Null publish_date
Handled by skipping the date field when building page properties. The entry still gets written to Notion, just without a publish date.

### Very long excerpt_text
Some results have very long excerpts (1500+ chars). The `_format_rich_text()` function in `notion_client.py` handles the 2000-char split. No issues expected.

### State file corruption
If `state.json` has invalid JSON, `load_state()` will raise `json.JSONDecodeError`. This should crash — corrupted state needs manual attention, not silent recovery.

### Re-running the same cycle
If you run cycle 1 twice in a row, the second run's Pass A uses the first run's timestamp. Results from the first run are already in the Ingestion Queue or Main KB, so they'll be filtered by dedup. Zero new entries on the second run is the expected behavior.