# CHUNK 7: Parallel Search — Multiple Queries with Variation

## Objective
Add `search_multiple()` and `generate_variant_queries()` to `parallel_client.py`. The pipeline needs more than 10 results per search cycle. Since Parallel returns max 10 per call, we generate 5–8 variant queries from different angles on the topic, run each one, collect all results, and return the combined set. This chunk also handles deduplication of results across queries (same URL appearing in multiple searches).

## Dependencies
- Chunk 6 complete (parallel_client.py with `search()` function)

## What this chunk adds to parallel_client.py
- `generate_variant_queries()` — public function
- `search_multiple()` — public function

---

## DESIGN

### Why multiple queries?

Parallel's Search API returns max 10 results per call. A single query like "Physical AI robotics India" returns one angle on the topic. To get comprehensive coverage, we need to search from multiple angles:

- Different sub-topics ("Physical AI policy India", "robotics funding India", "manufacturing automation India")
- Different entity focuses ("NVIDIA robotics", "Boston Dynamics", "Indian robotics startups")
- Different content types ("Physical AI research papers", "Physical AI news", "Physical AI government policy")

Each variant query brings back different results. Combined, they give 50–80 unique results per cycle instead of 10.

### Deduplication across queries

The same article may appear in multiple variant queries. Before returning results, `search_multiple()` deduplicates by URL — keeping the first occurrence and dropping subsequent ones.

### Rate awareness

Running 8 searches at ~$0.005 each = $0.04 per cycle. At 4 cycles/day = $0.16/day = ~$5/month. Affordable.

Each search takes 1–5 seconds. Running 8 sequentially = 8–40 seconds per cycle. Add `time.sleep(0.5)` between searches to be respectful, making each cycle ~12–45 seconds total. This is fine — cycles run every 5–6 hours.

---

## IMPLEMENTATION SPEC

### `generate_variant_queries(topic: str, num_variants: int = 6) -> list[dict]`

```python
def generate_variant_queries(topic: str, num_variants: int = 6) -> list[dict]:
    """
    Generate variant search configurations from a topic.
    
    Each variant has a different objective and search_queries to
    approach the topic from a different angle. This ensures broader
    coverage than a single search.
    
    Args:
        topic: The main topic to generate variants for.
               Example: "Physical AI"
        num_variants: Number of variants to generate (default 6).
    
    Returns:
        List of dicts, each with:
        - "objective": str — natural language search objective
        - "search_queries": list[str] — keyword queries
        - "label": str — human-readable label for logging
    
    Example:
        variants = generate_variant_queries("Physical AI")
        # Returns something like:
        [
            {
                "label": "core_news",
                "objective": "Latest news and developments in Physical AI",
                "search_queries": ["Physical AI news 2026", "Physical AI latest developments"]
            },
            {
                "label": "funding",
                "objective": "Funding rounds and investments in Physical AI and robotics companies",
                "search_queries": ["Physical AI funding round", "robotics startup investment 2026"]
            },
            ...
        ]
    """
```

Implementation requirements:

This function does NOT call any API. It generates a hardcoded but well-designed set of variant query configurations for a given topic. The variants should cover these angles:

1. **Core news** — latest news and developments on the topic
2. **Funding & investment** — funding rounds, acquisitions, investments in companies working on the topic
3. **Policy & regulation** — government policies, regulations, trade restrictions related to the topic
4. **Research & academia** — new research papers, academic breakthroughs, university work on the topic
5. **India-specific** — developments specifically in India related to the topic (this is a key geographic focus)
6. **Competitor & company moves** — product launches, partnerships, strategic moves by companies in the space

Each variant should have:
- An `objective` that is specific and directive (tells Parallel what you want, not just keywords)
- 2–3 `search_queries` with different keyword formulations
- A `label` for logging (e.g., "core_news", "funding", "policy", "research", "india", "companies")

The topic string is interpolated into each variant. For example, if topic is "Physical AI":
- Objective: f"Latest news and developments in {topic}"
- Search queries: [f"{topic} news 2026", f"{topic} latest developments"]

**The variant templates are hardcoded in the function.** This is intentional — we want consistent, well-designed query angles, not dynamic generation. The only dynamic part is interpolating the topic string.

If `num_variants` is less than the number of defined templates, return only the first N. If more, return all defined templates (don't generate extras).

---

### `search_multiple(topic: str, after_date: str | None = None, max_results_per_query: int = 10, num_variants: int = 6, exclude_domains: list[str] | None = None) -> list[dict]`

```python
def search_multiple(
    topic: str,
    after_date: str | None = None,
    max_results_per_query: int = 10,
    num_variants: int = 6,
    exclude_domains: list[str] | None = None,
) -> list[dict]:
    """
    Run multiple variant searches on a topic and return deduplicated results.
    
    Generates variant queries from the topic, runs each one via search(),
    deduplicates by URL, and returns the combined result set.
    
    Args:
        topic: The main topic to search for. Example: "Physical AI"
        after_date: Only return results published on or after this date.
                   Format: "YYYY-MM-DD". None = no date filter.
                   Used for time-window pass (Pass A).
        max_results_per_query: Max results per individual search (default 10).
        num_variants: Number of variant queries to run (default 6).
        exclude_domains: Domains to exclude. Max 10.
    
    Returns:
        List of deduplicated result dicts (same format as search() output).
        Each result also includes:
        - "found_by": list[str] — labels of variant queries that found this URL
                                  (useful for seeing which angles surfaced it)
    
    Raises:
        Exception: If all searches fail. Individual search failures are
                   logged and skipped — partial results are returned.
    
    Example:
        # Pass A: Time-window (everything since last cycle)
        results_a = search_multiple(
            topic="Physical AI",
            after_date="2026-04-03",
        )
        
        # Pass B: Relevance-ranked (no date filter)
        results_b = search_multiple(
            topic="Physical AI",
        )
    """
```

Implementation requirements:

1. Call `generate_variant_queries(topic, num_variants)` to get variant configs
2. For each variant:
   a. Log which variant is being searched (label)
   b. Call `search()` with the variant's `objective` and `search_queries`, plus `after_date`, `max_results_per_query`, and `exclude_domains`
   c. If the search fails (exception), log the error and continue to the next variant. Do NOT abort the entire batch because one query failed.
   d. Add `time.sleep(0.5)` between queries to avoid hammering the API
3. Merge all results from all queries
4. Deduplicate by URL:
   - Normalize URLs before comparing: lowercase, strip trailing slashes, strip `www.` prefix, strip query parameters (everything after `?`), strip fragment (everything after `#`)
   - Keep the first occurrence of each unique URL
   - Track which variant labels found each URL in the `found_by` field
5. Log: total results before dedup, total after dedup, number of duplicates removed
6. Return the deduplicated list

### URL normalization function (private):

```python
def _normalize_url(url: str) -> str:
    """
    Normalize a URL for deduplication comparison.
    
    - Lowercase
    - Strip trailing slashes
    - Strip 'www.' prefix from domain
    - Strip query parameters (?...) 
    - Strip fragment (#...)
    
    Example:
        _normalize_url("https://WWW.Example.Com/Article/?ref=twitter#top")
        → "https://example.com/article"
    """
```

Use `urllib.parse.urlparse` and `urllib.parse.urlunparse` from Python's standard library. Do NOT add any new dependencies for this.

---

## TEST BLOCK

Replace the existing `if __name__ == "__main__":` block in `parallel_client.py`:

```python
if __name__ == "__main__":
    import json
    from config import TOPIC
    
    # --- Test 1: Generate variant queries ---
    print("Test 1: Generate variant queries...")
    variants = generate_variant_queries(TOPIC)
    print(f"  Generated {len(variants)} variants:")
    for v in variants:
        print(f"    [{v['label']}] {v['objective'][:70]}")
        print(f"      Queries: {v['search_queries']}")
    
    # --- Test 2: Run multiple searches (Pass B — relevance-ranked) ---
    print(f"\nTest 2: Running {len(variants)} variant searches (relevance-ranked)...")
    results = search_multiple(
        topic=TOPIC,
        max_results_per_query=5,  # Reduced for testing (saves API cost)
        num_variants=3,           # Reduced for testing
    )
    print(f"  Total unique results: {len(results)}")
    print(f"\n  Top 5 results:")
    for r in results[:5]:
        print(f"    - {r['title'][:70]}")
        print(f"      URL: {r['url'][:70]}")
        print(f"      Date: {r.get('publish_date')}")
        print(f"      Found by: {r.get('found_by', [])}")
        print()
    
    # --- Test 3: Check deduplication ---
    print("Test 3: Checking for duplicates...")
    urls = [r["url"] for r in results]
    normalized = [_normalize_url(u) for u in urls]
    unique_normalized = set(normalized)
    if len(normalized) == len(unique_normalized):
        print(f"  No duplicates found in {len(results)} results: PASSED")
    else:
        dupes = len(normalized) - len(unique_normalized)
        print(f"  WARNING: {dupes} duplicate URLs found after normalization!")
    
    # --- Test 4: Run with date filter (Pass A — time-window) ---
    from datetime import datetime, timedelta
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"\nTest 4: Time-window search (after {yesterday})...")
    results_tw = search_multiple(
        topic=TOPIC,
        after_date=yesterday,
        max_results_per_query=5,
        num_variants=2,  # Reduced for testing
    )
    print(f"  Time-window results: {len(results_tw)}")
    
    print("\nAll multi-search tests completed!")
```

---

## EDGE CASES

### All variant searches fail
If every single variant search raises an exception, `search_multiple()` should raise an exception with a summary of all failures. If at least one succeeds, return whatever results were found (partial results are better than nothing).

### Zero results across all variants
Possible for very niche topics or very restrictive date filters. Return an empty list.

### Duplicate URLs with different titles
Same URL, different titles from different search results. Keep the first occurrence. The title from the first result that found it is used.

### URL normalization edge cases
- URLs with ports: `https://example.com:8080/path` — keep the port, it's part of the identity
- URLs with encoding: `https://example.com/path%20with%20spaces` — leave as-is
- Protocol differences: `http://` vs `https://` — treat as different URLs (they may serve different content)
- Trailing slash: `https://example.com/path` and `https://example.com/path/` — treat as same (strip trailing slash)

### Topic string is empty
Guard against this. If `topic` is empty or None, raise a ValueError immediately.

### num_variants = 0
Return empty list. Don't call any searches.