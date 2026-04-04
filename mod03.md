# MOD 03: Source Quality Filtering

## Objective
Filter out low-quality sources (LinkedIn profiles, Pinterest, Quora, job boards, search/tag pages, etc.) BEFORE they enter the pipeline. This saves OpenAI tokens, keeps the Main KB clean, and improves signal-to-noise. Filtering at two levels: Parallel's `exclude_domains` parameter (pre-search) and a post-search Python filter on URL patterns.

## Execution Order
This is the **first mod** to execute. Order: 3 → 5 → 6 → 1 → 2 → 4.

---

## What changes

| File | Change |
|---|---|
| `config.py` | Add `DEFAULT_EXCLUDE_DOMAINS`, `EXTRA_EXCLUDE_DOMAINS`, `EXCLUDE_DOMAINS` |
| `.env.example` | Add `EXTRA_EXCLUDE_DOMAINS` |
| `parallel_client.py` | Update `search()` to use default exclude_domains |
| `parallel_client.py` | Add `EXCLUDE_URL_PATTERNS` list |
| `parallel_client.py` | Add `_is_quality_source()` function |
| `parallel_client.py` | Update `search_multiple()` to filter results after dedup |

---

## DESIGN

### Layer 1: Parallel's `exclude_domains` (pre-search)

Parallel accepts up to 10 domains to exclude per request. Use this for domains that NEVER produce useful results. Blocked at API level — you don't pay for them and they never appear in results.

Default list (8 domains, leaving 2 slots for user extras):

```python
DEFAULT_EXCLUDE_DOMAINS = [
    "pinterest.com",      # Image boards, no article content
    "quora.com",          # Q&A opinions, not primary sources
    "facebook.com",       # Social posts, not extractable
    "instagram.com",      # Images/reels only
    "tiktok.com",         # Video only
    "youtube.com",        # Video only, can't extract text
    "amazon.com",         # Product listings
    "ebay.com",           # Product listings
]
```

### Layer 2: Post-search URL pattern filter

For patterns within allowed domains — like LinkedIn profile pages (not articles), search result pages, tag/category pages, job boards. These pass Layer 1 (domain is allowed) but should still be rejected based on URL structure.

```python
EXCLUDE_URL_PATTERNS = [
    # LinkedIn profiles and company pages (keep pulse/posts/articles)
    r"linkedin\.com/in/",
    r"linkedin\.com/company/[^/]+/?$",
    
    # Search/tag/category pages (aggregation, not original content)
    r"/search\?",
    r"/tag/",
    r"/category/",
    r"/topics/",
    
    # File hosting / non-article
    r"slideshare\.net",
    r"issuu\.com",
    
    # Job boards
    r"/jobs/",
    r"/careers/",
    r"indeed\.com",
    r"glassdoor\.com",
]
```

### What passes through from LinkedIn

- `linkedin.com/pulse/physical-ai-trends` → Article ✅ Keep
- `linkedin.com/posts/someone_physical-ai` → Post ✅ Keep
- `linkedin.com/feed/update/urn:li:activity:123` → Feed ✅ Keep
- `linkedin.com/in/john-doe` → Profile ❌ Reject
- `linkedin.com/company/acme-corp` → Company page ❌ Reject

The patterns `linkedin\.com/in/` and `linkedin\.com/company/` catch profiles and company pages. Article/post URLs have different structures and pass through.

---

## IMPLEMENTATION SPEC

### In `config.py` — add these lines:

```python
# === Source Quality Filtering ===
DEFAULT_EXCLUDE_DOMAINS = [
    "pinterest.com",
    "quora.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "youtube.com",
    "amazon.com",
    "ebay.com",
]

# User-configured additional exclusions (comma-separated in .env)
_extra_excludes = os.getenv("EXTRA_EXCLUDE_DOMAINS", "")
EXTRA_EXCLUDE_DOMAINS = [d.strip() for d in _extra_excludes.split(",") if d.strip()]

# Combined (capped at 10 — Parallel API limit)
EXCLUDE_DOMAINS = (DEFAULT_EXCLUDE_DOMAINS + EXTRA_EXCLUDE_DOMAINS)[:10]
```

### In `.env.example` — add:

```bash
# Optional: extra domains to exclude from search (comma-separated, max 2)
EXTRA_EXCLUDE_DOMAINS=
```

### In `parallel_client.py`:

#### 1. Add imports at top (if not already):

```python
import re
```

#### 2. Add `EXCLUDE_URL_PATTERNS` as a module-level constant:

```python
EXCLUDE_URL_PATTERNS = [
    r"linkedin\.com/in/",
    r"linkedin\.com/company/[^/]+/?$",
    r"/search\?",
    r"/tag/",
    r"/category/",
    r"/topics/",
    r"slideshare\.net",
    r"issuu\.com",
    r"/jobs/",
    r"/careers/",
    r"indeed\.com",
    r"glassdoor\.com",
]
```

#### 3. Add `_is_quality_source()` function:

```python
def _is_quality_source(result: dict) -> bool:
    """
    Check if a search result is from a quality source.
    
    Returns True if the result should be kept.
    Returns False if it matches an exclusion pattern.
    """
    url = result.get("url", "")
    
    if not url:
        return False
    
    url_lower = url.lower()
    
    for pattern in EXCLUDE_URL_PATTERNS:
        if re.search(pattern, url_lower):
            return False
    
    return True
```

#### 4. Update `search()` — add default exclude_domains:

Find the `search()` function. At the beginning of the function body (after docstring, before building the request), add:

```python
# Default domain exclusions if none provided
if exclude_domains is None:
    from config import EXCLUDE_DOMAINS
    exclude_domains = EXCLUDE_DOMAINS
```

The rest of the `search()` function already passes `exclude_domains` to the API via `source_policy`. This change just sets a default so every call automatically excludes junk domains.

#### 5. Update `search_multiple()` — add quality filtering:

Find `search_multiple()`. After the existing cross-query URL deduplication (where duplicates between variant queries are removed), add quality filtering BEFORE returning results:

```python
# === ADD THIS after existing dedup, before return ===

# Layer 2: Post-search quality filter
before_quality = len(deduplicated_results)
quality_results = [r for r in deduplicated_results if _is_quality_source(r)]
quality_filtered = before_quality - len(quality_results)

if quality_filtered > 0:
    logger.info(f"Quality filter: removed {quality_filtered} low-quality results")
    # Log filtered URLs at DEBUG level for tuning
    for r in deduplicated_results:
        if not _is_quality_source(r):
            logger.debug(f"  Filtered: {r.get('url', '')[:80]}")

# Return quality results instead of deduplicated_results
return quality_results  # ← CHANGE: was returning deduplicated_results
```

Make sure the function returns `quality_results`, not the previous variable.

---

## TEST BLOCK

Replace the existing `if __name__ == "__main__":` block in `parallel_client.py`:

```python
if __name__ == "__main__":
    from config import TOPIC, EXCLUDE_DOMAINS
    
    # --- Test 1: Show exclude domains ---
    print(f"Test 1: Exclude domains ({len(EXCLUDE_DOMAINS)}):")
    for d in EXCLUDE_DOMAINS:
        print(f"  - {d}")
    assert len(EXCLUDE_DOMAINS) >= 8, f"Expected at least 8, got {len(EXCLUDE_DOMAINS)}"
    print("  Config: PASSED")
    
    # --- Test 2: Test quality filter patterns ---
    print("\nTest 2: Quality source filter...")
    
    keep_cases = [
        {"url": "https://reuters.com/article/ai-news", "title": "News"},
        {"url": "https://techcrunch.com/2026/04/startup", "title": "Startup"},
        {"url": "https://arxiv.org/abs/2026.1234", "title": "Paper"},
        {"url": "https://linkedin.com/pulse/ai-trends", "title": "AI Trends"},
        {"url": "https://linkedin.com/posts/someone_ai", "title": "Post"},
        {"url": "https://nvidia.com/blog/isaac", "title": "NVIDIA Blog"},
        {"url": "https://bbc.co.uk/news/tech-123", "title": "BBC News"},
    ]
    
    reject_cases = [
        {"url": "https://linkedin.com/in/john-doe", "title": "John Doe"},
        {"url": "https://linkedin.com/company/acme", "title": "Acme Corp"},
        {"url": "https://example.com/search?q=robots", "title": "Search"},
        {"url": "https://example.com/tag/robotics", "title": "Tag Page"},
        {"url": "https://example.com/category/tech", "title": "Category"},
        {"url": "https://indeed.com/jobs/ai-eng", "title": "Job"},
        {"url": "https://glassdoor.com/Reviews/co", "title": "Reviews"},
        {"url": "", "title": "No URL"},
    ]
    
    all_passed = True
    for r in keep_cases:
        ok = _is_quality_source(r)
        status = "✅" if ok else "❌"
        if not ok: all_passed = False
        print(f"  {status} KEEP: {r['url'][:60]}")
    
    for r in reject_cases:
        ok = not _is_quality_source(r)
        status = "✅" if ok else "❌"
        if not ok: all_passed = False
        print(f"  {status} REJECT: {r['url'][:60]}")
    
    if all_passed:
        print("  All filter tests: PASSED")
    else:
        print("  SOME TESTS FAILED")
    
    # --- Test 3: Real search with filtering ---
    print(f"\nTest 3: Running search with quality filter...")
    results = search_multiple(
        topic=TOPIC,
        max_results_per_query=10,
        num_variants=3,
    )
    
    for r in results:
        url_lower = r.get("url", "").lower()
        for domain in EXCLUDE_DOMAINS:
            assert domain not in url_lower, f"Excluded domain found: {domain} in {url_lower}"
        assert _is_quality_source(r), f"Low-quality result passed through: {r['url'][:60]}"
    
    print(f"  Results: {len(results)} (all quality sources)")
    print("  No excluded domains or patterns: PASSED")
    
    print("\nAll quality filter tests completed!")
```

---

## EDGE CASES

### Pinterest in both layers
Pinterest is in `exclude_domains` (blocked by Parallel) AND would be caught by URL patterns (Layer 2) if it somehow appeared. Double coverage is fine.

### User adds too many extra domains
`EXCLUDE_DOMAINS` is capped at 10 (Parallel's limit). Default 8 + max 2 extras = 10. If user adds more, the list is truncated.

### Quality filter removes ALL results
If every result from a variant is filtered, `search_multiple()` returns fewer results. If ALL results from ALL variants are filtered, it returns an empty list. The ingestion pipeline handles empty lists (logs "0 new entries"). This should be rare.

### False positives — good content filtered
Logged at DEBUG level. User can check logs and adjust patterns. Better to start aggressive and loosen than to let junk through.

### LinkedIn articles vs profiles
The regex `linkedin\.com/in/` catches profiles. LinkedIn articles (`/pulse/`), posts (`/posts/`), and feed updates (`/feed/`) have different URL structures and pass through correctly.

### exclude_domains in .env with spaces
`"reddit.com, medium.com"` → split by comma, stripped → `["reddit.com", "medium.com"]`. Handles spaces correctly.