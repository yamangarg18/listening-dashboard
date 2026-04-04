# CHUNK 8: Deduplication — Filter Out Already-Known Entries

## Objective
Build `dedup.py` — a module that takes the combined search results from `search_multiple()` and filters out entries that already exist in the Main Knowledge Base or Ingestion Queue. This prevents the pipeline from re-ingesting the same article every cycle. Also adds title similarity checking to catch the same article from different URL formats (e.g., AMP URLs vs regular URLs).

## Dependencies
- Chunk 3 complete (notion_client.py with `query_database()`, `parse_page_properties()`)
- Chunk 7 complete (parallel_client.py with `search_multiple()`, `_normalize_url()`)

## What this chunk creates
- `dedup.py` — new file

---

## DESIGN

### The problem

Every search cycle runs 6 variant queries and returns ~50–80 results. Many of these will be articles the pipeline already found in a previous cycle. Without deduplication against the database, Stage 2 would waste OpenAI tokens re-evaluating the same articles repeatedly, and the Ingestion Queue would fill with duplicates.

### Two layers of deduplication

**Layer 1 (already done in Chunk 7):** `search_multiple()` deduplicates within a single batch — if the same URL appears in multiple variant queries, it's kept only once.

**Layer 2 (this chunk):** Check each result against what's already in the Main KB and Ingestion Queue. If a URL already exists in either database, skip it.

### Three matching strategies

1. **Exact URL match** — normalize both the search result URL and the stored URL, then compare. Catches identical articles.

2. **Title similarity** — if the URLs don't match but the titles are very similar (>85% similar), flag it as a likely duplicate. This catches the same article from different URL formats: AMP pages, syndicated copies, URL shorteners that resolved differently. Title similarity uses a simple approach — not a heavy NLP library, just `difflib.SequenceMatcher` from Python's standard library.

3. **URL domain + path match** — sometimes the same article has slightly different query parameters that survived normalization, or http vs https differences. Compare just the domain + path portion.

---

## IMPLEMENTATION SPEC

### File: `dedup.py`

```python
"""
Deduplication module.
Filters search results against existing entries in Notion databases.
"""
```

### Functions to implement:

#### `deduplicate_against_db(results: list[dict], existing_urls: set[str], existing_titles: list[str], similarity_threshold: float = 0.85) -> tuple[list[dict], list[dict]]`

```python
def deduplicate_against_db(
    results: list[dict],
    existing_urls: set[str],
    existing_titles: list[str],
    similarity_threshold: float = 0.85,
) -> tuple[list[dict], list[dict]]:
    """
    Filter search results against already-known entries.
    
    Args:
        results: List of search result dicts from search_multiple().
                 Each must have "url" and "title" fields.
        existing_urls: Set of normalized URLs already in Main KB and 
                      Ingestion Queue. Pre-normalized for fast lookup.
        existing_titles: List of titles from existing entries. Used for
                        similarity matching.
        similarity_threshold: Minimum similarity ratio (0-1) for title
                            matching. Default 0.85 (85% similar).
    
    Returns:
        Tuple of (new_results, duplicates):
        - new_results: List of results that are NOT in the database.
                      These should be written to the Ingestion Queue.
        - duplicates: List of results that were filtered out, each with
                     an added "duplicate_reason" field explaining why
                     (for logging/debugging).
    
    Example:
        new, dupes = deduplicate_against_db(
            results=search_results,
            existing_urls=known_urls,
            existing_titles=known_titles,
        )
        print(f"{len(new)} new entries, {len(dupes)} duplicates filtered")
    """
```

Implementation requirements:
- For each result in `results`:
  1. Normalize the result's URL using `_normalize_url()` from `parallel_client.py`
  2. **URL check:** If the normalized URL is in `existing_urls`, mark as duplicate with reason `"url_match"`
  3. **Title check:** If the URL didn't match, compare the result's title against every title in `existing_titles` using `difflib.SequenceMatcher`. If any comparison exceeds `similarity_threshold`, mark as duplicate with reason `"title_similar: {matched_title} ({ratio:.0%})"`
  4. If neither check matched, it's a new entry
- Add a `"duplicate_reason"` field to each duplicate result
- Log the counts: new vs duplicates, broken down by reason
- Return the tuple

#### `get_existing_entries(main_kb_id: str, ingestion_queue_id: str) -> tuple[set[str], list[str]]`

```python
def get_existing_entries(
    main_kb_id: str,
    ingestion_queue_id: str,
) -> tuple[set[str], list[str]]:
    """
    Fetch all URLs and titles from Main KB and Ingestion Queue.
    
    Queries both databases and collects:
    - All URLs (normalized) into a set for fast lookup
    - All titles into a list for similarity matching
    
    Args:
        main_kb_id: Database ID of Main Knowledge Base
        ingestion_queue_id: Database ID of Ingestion Queue
    
    Returns:
        Tuple of (urls_set, titles_list):
        - urls_set: Set of normalized URL strings
        - titles_list: List of title strings
    
    Example:
        urls, titles = get_existing_entries(main_kb_id, iq_id)
        print(f"Known URLs: {len(urls)}, Known titles: {len(titles)}")
    """
```

Implementation requirements:
- Query Main KB (all pages, no filter) using `query_database()` from `notion_client.py`
- Query Ingestion Queue (all pages, no filter)
- For each page from both databases, parse with `parse_page_properties()`
- Collect URLs: normalize each URL using `_normalize_url()`, add to a set. Skip entries with no URL (None or empty).
- Collect titles: add each title to a list. Skip empty titles.
- Log: number of entries from Main KB, number from Ingestion Queue, total unique URLs, total titles
- Return the tuple

#### `_title_similarity(title_a: str, title_b: str) -> float`

```python
def _title_similarity(title_a: str, title_b: str) -> float:
    """
    Calculate similarity ratio between two titles.
    Uses difflib.SequenceMatcher (standard library, no extra deps).
    
    Both titles are lowercased and stripped before comparison.
    
    Args:
        title_a: First title
        title_b: Second title
    
    Returns:
        Float between 0.0 (completely different) and 1.0 (identical).
    """
```

Implementation: 
```python
from difflib import SequenceMatcher

def _title_similarity(title_a: str, title_b: str) -> float:
    a = title_a.strip().lower()
    b = title_b.strip().lower()
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()
```

---

## PERFORMANCE NOTE

`get_existing_entries()` queries ALL pages from both databases. As the Main KB grows to hundreds or thousands of entries, this gets slower. For now (early operation), this is fine — querying 500 pages takes ~5 pagination calls, under 3 seconds. If performance becomes an issue later, we can optimize by:
- Only querying entries from the last 30 days (since older entries are archived and won't match new results anyway)
- Caching URLs in a local set between cycles (refresh every Nth cycle)

But don't optimize now. Keep it simple.

---

## TEST BLOCK

```python
if __name__ == "__main__":
    from parallel_client import _normalize_url
    
    # --- Test 1: Title similarity ---
    print("Test 1: Title similarity...")
    
    assert _title_similarity("Physical AI in India", "Physical AI in India") == 1.0
    assert _title_similarity("Physical AI in India", "physical ai in india") == 1.0
    assert _title_similarity("", "") == 0.0
    assert _title_similarity("Physical AI in India", "Quantum Computing in Japan") < 0.5
    
    # Similar but not identical
    ratio = _title_similarity(
        "India launches new robotics policy framework",
        "India launches new robotics policy framework for manufacturing"
    )
    print(f"  Similar titles ratio: {ratio:.2f}")
    assert ratio > 0.8, f"Expected > 0.8 for similar titles, got {ratio}"
    
    # Very different
    ratio = _title_similarity(
        "Stock market crashes amid trade war",
        "New species of butterfly discovered in Amazon"
    )
    print(f"  Different titles ratio: {ratio:.2f}")
    assert ratio < 0.4, f"Expected < 0.4 for different titles, got {ratio}"
    
    print("  Title similarity: PASSED")
    
    # --- Test 2: Deduplication logic ---
    print("\nTest 2: Deduplication against known entries...")
    
    # Simulated search results
    fake_results = [
        {"url": "https://example.com/article-1", "title": "New Robotics Funding Round"},
        {"url": "https://example.com/article-2", "title": "Physical AI Policy Update"},
        {"url": "https://example.com/article-3", "title": "Totally New Article"},
        {"url": "https://different.com/article-1", "title": "New Robotics Funding Round Announced"},  # similar title
        {"url": "https://example.com/article-4", "title": "Another Unique Article"},
    ]
    
    # Simulated existing entries
    existing_urls = {
        _normalize_url("https://example.com/article-1"),
        _normalize_url("https://example.com/article-2"),
    }
    existing_titles = [
        "New Robotics Funding Round",
        "Physical AI Policy Update",
    ]
    
    new, dupes = deduplicate_against_db(
        results=fake_results,
        existing_urls=existing_urls,
        existing_titles=existing_titles,
    )
    
    print(f"  New: {len(new)}, Duplicates: {len(dupes)}")
    
    # article-1 and article-2 should be URL duplicates
    dupe_urls = [d["url"] for d in dupes]
    assert "https://example.com/article-1" in dupe_urls, "article-1 should be a URL duplicate"
    assert "https://example.com/article-2" in dupe_urls, "article-2 should be a URL duplicate"
    
    # article-3 should be new
    new_urls = [n["url"] for n in new]
    assert "https://example.com/article-3" in new_urls, "article-3 should be new"
    assert "https://example.com/article-4" in new_urls, "article-4 should be new"
    
    # different.com/article-1 has similar title to existing — may be flagged
    # (depends on whether "New Robotics Funding Round" vs "New Robotics Funding Round Announced" exceeds 0.85)
    for d in dupes:
        if d["url"] == "https://different.com/article-1":
            print(f"  Title-similar duplicate caught: {d.get('duplicate_reason')}")
    
    # Check duplicate_reason field exists on all duplicates
    for d in dupes:
        assert "duplicate_reason" in d, f"Missing duplicate_reason on {d['url']}"
    
    print("  Deduplication logic: PASSED")
    
    # --- Test 3: get_existing_entries (real Notion call) ---
    print("\nTest 3: Fetching existing entries from Notion...")
    from config import get_database_id
    
    main_kb_id = get_database_id("main_kb")
    iq_id = get_database_id("ingestion_queue")
    
    urls, titles = get_existing_entries(main_kb_id, iq_id)
    print(f"  Known URLs: {len(urls)}")
    print(f"  Known titles: {len(titles)}")
    print(f"  Types: urls={type(urls).__name__}, titles={type(titles).__name__}")
    assert isinstance(urls, set), "urls should be a set"
    assert isinstance(titles, list), "titles should be a list"
    print("  get_existing_entries: PASSED")
    
    print("\nAll dedup tests passed!")
```

---

## EDGE CASES

### Empty databases (first run)
On the very first run, both Main KB and Ingestion Queue are empty. `get_existing_entries()` returns an empty set and empty list. `deduplicate_against_db()` should treat all results as new. This is the correct behavior.

### Result with no URL
Some search results might have a weird or empty URL. If `url` is None or empty, treat the result as new (can't deduplicate without a URL). Don't crash.

### Result with no title
If `title` is empty, skip the title similarity check for that result. Don't crash on empty strings.

### Very large Main KB
If the Main KB has 1000+ entries, `get_existing_entries()` will make multiple pagination calls. This is handled by `query_database()` (Chunk 3). The title similarity check loops through all existing titles for each new result — this is O(n*m) but fine for n=80 results * m=1000 titles = 80,000 comparisons. `SequenceMatcher` is fast enough for this.

### Case sensitivity in titles
Title comparison is case-insensitive (both lowercased before comparison). "Physical AI" and "physical ai" are treated as identical.

### Duplicate reason logging
The `duplicate_reason` field is for debugging only — it helps you understand why entries were filtered. It's not written to Notion.