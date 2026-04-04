# CHUNK 6: Parallel Search API — Single Search

## Objective
Build `parallel_client.py` with a `search()` function that calls Parallel's Search API with a single query and returns structured results. This is the foundation for Stage 1 ingestion.

## Dependencies
- Chunk 0 complete (config.py with PARALLEL_API_KEY)
- `.env` has `PARALLEL_API_KEY` set (get from https://platform.parallel.ai)

## What this chunk creates
- `parallel_client.py` — new file with `search()` function

---

## PARALLEL SEARCH API REFERENCE

### Endpoint

```
POST https://api.parallel.ai/v1beta/search
```

### Authentication

```python
headers = {
    "Content-Type": "application/json",
    "x-api-key": PARALLEL_API_KEY,
}
```

No version header needed. Auth is via `x-api-key` header (not Bearer token — different from Notion).

### Base URL

```
https://api.parallel.ai
```

### Request Body

```json
{
  "objective": "Natural language description of what to search for",
  "search_queries": ["keyword query 1", "keyword query 2"],
  "mode": "one-shot",
  "max_results": 10,
  "source_policy": {
    "after_date": "2026-04-01",
    "exclude_domains": ["pinterest.com"]
  },
  "excerpts": {
    "max_chars_per_result": 1500
  }
}
```

### Request Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `objective` | string | At least one of `objective` or `search_queries` | Natural language description of what the search is trying to find. Can include guidance about preferred sources or freshness. |
| `search_queries` | string[] | At least one of `objective` or `search_queries` | List of traditional keyword search queries. Can contain search operators. |
| `mode` | string | No (default: `"one-shot"`) | `"one-shot"` = comprehensive results, longer excerpts, single response. `"agentic"` = concise, token-efficient results for agentic loops. `"fast"` = lower latency, trades some quality. |
| `max_results` | integer | No (default: 10) | Upper bound on results to return. |
| `source_policy` | object | No | Controls domain and date filtering. See below. |
| `excerpts` | object | No | Controls excerpt generation. |
| `fetch_policy` | object | No | Controls cached vs live content. Default: cached (faster). |

### source_policy Object

```json
{
  "include_domains": ["reuters.com", "techcrunch.com"],
  "exclude_domains": ["pinterest.com", "quora.com"],
  "after_date": "2026-04-01"
}
```

| Parameter | Type | Description |
|---|---|---|
| `include_domains` | string[] | Only return results from these domains. Max 10. |
| `exclude_domains` | string[] | Exclude results from these domains. Max 10. |
| `after_date` | string | RFC 3339 date (`YYYY-MM-DD`). Only return content published on or after this date. **This is how we implement the time-window search pass.** |

Use either `include_domains` OR `exclude_domains`, not both. Domains should be apex form (`reuters.com`, not `www.reuters.com` or `https://reuters.com`).

### excerpts Object

```json
{
  "max_chars_per_result": 1500
}
```

Controls how much text is extracted per result. Default varies by mode. For our use case, 1500 chars is sufficient — we need enough for OpenAI to assess relevance, but not full articles.

### Response (200 OK)

```json
{
  "search_id": "search_fcb2b4f3-c75e-4186-87bc-caa1a8381331",
  "results": [
    {
      "url": "https://www.reuters.com/article/example",
      "title": "Sample Article Title",
      "publish_date": "2024-01-15",
      "excerpts": [
        "First excerpt of text from the article...",
        "Second excerpt of text from the article..."
      ]
    },
    {
      "url": "https://techcrunch.com/another-article",
      "title": "Another Article",
      "publish_date": "2024-01-14",
      "excerpts": [
        "Excerpt from this article..."
      ]
    }
  ],
  "warnings": null,
  "usage": [
    {
      "name": "sku_search",
      "count": 1
    }
  ]
}
```

### Response Fields (per result)

| Field | Type | Description |
|---|---|---|
| `url` | string | URL of the page |
| `title` | string | Page title |
| `publish_date` | string or null | Publication date in `YYYY-MM-DD` format. **Can be null** if Parallel can't determine the date. |
| `excerpts` | string[] | Array of text excerpts from the page. Usually 1–3 excerpts per result. |

### Error Responses

| Status | Meaning |
|---|---|
| 401 | Invalid API key |
| 422 | Validation error (bad request body) |
| 429 | Rate limited |
| 500 | Server error |

### Rate Limits

600 requests per minute. Not a concern for 4 searches/day, but relevant if running many variant queries in Chunk 7.

---

## IMPLEMENTATION SPEC

### File: `parallel_client.py`

```python
"""
Parallel Web Systems API client.
Handles Search API calls for Stage 1 ingestion.
"""
```

### Functions to implement:

#### `search(objective: str, search_queries: list[str] | None = None, max_results: int = 10, after_date: str | None = None, exclude_domains: list[str] | None = None, mode: str = "one-shot") -> list[dict]`

```python
def search(
    objective: str,
    search_queries: list[str] | None = None,
    max_results: int = 10,
    after_date: str | None = None,
    exclude_domains: list[str] | None = None,
    mode: str = "one-shot",
) -> list[dict]:
    """
    Search the web using Parallel's Search API.
    
    Args:
        objective: Natural language description of what to search for.
                   Example: "Recent developments in Physical AI and robotics in India"
        search_queries: Optional list of keyword queries to guide the search.
                       Example: ["Physical AI India robotics 2026", "India robot manufacturing"]
        max_results: Max results to return (default 10, max varies by plan).
        after_date: Only return results published on or after this date.
                   Format: "YYYY-MM-DD". Used for time-window searches.
                   None = no date filtering (for relevance-ranked searches).
        exclude_domains: Domains to exclude from results. Max 10.
                        Example: ["pinterest.com", "quora.com"]
        mode: Search mode. "one-shot" (default, comprehensive) or 
              "agentic" (concise) or "fast" (lower latency).
    
    Returns:
        List of result dicts, each with:
        - "url": str — page URL
        - "title": str — page title
        - "publish_date": str or None — publication date (YYYY-MM-DD)
        - "excerpts": list[str] — text excerpts from the page
        - "excerpt_text": str — all excerpts joined into a single string
                                (convenience field, not from API)
    
    Raises:
        Exception: If the API returns an error.
    
    Example:
        # Relevance-ranked search (no date filter)
        results = search(
            objective="Physical AI robotics companies in India",
            search_queries=["Physical AI India", "robotics startups India"],
        )
        
        # Time-window search (only results from last 24 hours)
        results = search(
            objective="Physical AI robotics latest news",
            after_date="2026-04-02",
        )
    """
```

Implementation requirements:
- Build the request body with `objective`, optionally `search_queries`, `max_results`, `mode`
- Add `source_policy` only if `after_date` or `exclude_domains` is provided
- Add `excerpts` with `max_chars_per_result: 1500`
- Send `POST /v1beta/search` with `x-api-key` header
- Check response status — raise exception with details on non-200
- Extract the `results` array from the response
- For each result, add a convenience field `excerpt_text` that joins all excerpts with `\n\n`:
  ```python
  result["excerpt_text"] = "\n\n".join(result.get("excerpts", []))
  ```
- Log the number of results found and the search_id
- Return the results list
- Use tenacity retry for 429 and 5xx errors (same pattern as Notion)

#### HTTP client setup:

```python
import httpx
from config import PARALLEL_API_KEY

PARALLEL_BASE_URL = "https://api.parallel.ai"
PARALLEL_HEADERS = {
    "Content-Type": "application/json",
    "x-api-key": PARALLEL_API_KEY,
}

def _get_client() -> httpx.Client:
    """Return a configured httpx client for Parallel API calls."""
    return httpx.Client(
        base_url=PARALLEL_BASE_URL,
        headers=PARALLEL_HEADERS,
        timeout=60.0,  # Parallel can take longer than Notion
    )
```

---

## IMPORTANT NOTE ON PARALLEL_API_KEY

The user needs to get an API key from https://platform.parallel.ai and add it to `.env`:

```
PARALLEL_API_KEY=your_parallel_api_key_here
```

This was already in `.env.example` from Chunk 0. But it needs a real value now.

Also add to `config.py` if not already there (it should be from Chunk 0):
```python
PARALLEL_API_KEY = os.getenv("PARALLEL_API_KEY")
```

---

## TEST BLOCK

```python
if __name__ == "__main__":
    import json
    
    # --- Test 1: Basic search ---
    print("Test 1: Basic search (relevance-ranked)...")
    results = search(
        objective="Recent developments in Physical AI and robotics",
        search_queries=["Physical AI robotics 2026"],
        max_results=5,
    )
    print(f"  Found {len(results)} results")
    for r in results:
        print(f"  - {r['title'][:80]}")
        print(f"    URL: {r['url'][:80]}")
        print(f"    Date: {r['publish_date']}")
        print(f"    Excerpt: {r['excerpt_text'][:150]}...")
        print()
    
    # --- Test 2: Search with date filter ---
    print("\nTest 2: Search with date filter (after_date)...")
    results_filtered = search(
        objective="Physical AI robotics latest news",
        after_date="2026-04-01",
        max_results=5,
    )
    print(f"  Found {len(results_filtered)} results after 2026-04-01")
    for r in results_filtered:
        print(f"  - {r['title'][:80]} (date: {r['publish_date']})")
    
    # --- Test 3: Verify result structure ---
    print("\nTest 3: Verify result structure...")
    if results:
        r = results[0]
        assert "url" in r, "Missing 'url' field"
        assert "title" in r, "Missing 'title' field"
        assert "publish_date" in r, "Missing 'publish_date' field"
        assert "excerpts" in r, "Missing 'excerpts' field"
        assert "excerpt_text" in r, "Missing 'excerpt_text' convenience field"
        assert isinstance(r["excerpts"], list), "'excerpts' should be a list"
        assert isinstance(r["excerpt_text"], str), "'excerpt_text' should be a string"
        print("  Result structure: PASSED")
    else:
        print("  WARNING: No results to verify structure (search returned empty)")
    
    print("\nAll search tests completed!")
```

---

## EDGE CASES

### Empty results
The API may return `{"results": []}` if nothing matches. Return an empty list, don't crash.

### publish_date is null
Some results have `"publish_date": null` — Parallel couldn't determine when the page was published. This is common for pages without meta date tags. The function must handle this — don't crash on null dates. Downstream code (Chunk 9) should treat null dates as "unknown" and still include the entry.

### Excerpts array is empty
Rare but possible. Some pages might have no extractable text. The `excerpt_text` convenience field should be an empty string in this case.

### Long excerpts
With `max_chars_per_result: 1500`, each result can have up to 1500 chars of excerpt text. This is fine for our use case — the excerpt goes into the Ingestion Queue's `Raw Summary` field (Notion rich text can hold up to ~100K chars).

### API key not set
If `PARALLEL_API_KEY` is not in `.env`, the request will fail with a 401. The function should raise a clear error. The test block should check for this before making calls.

### Rate limiting
600 req/min is generous. Even with variant queries in Chunk 7, we won't hit this. The tenacity retry handles any 429s.

### Timeout
Parallel's Search API typically responds in 1–5 seconds for `one-shot` mode. The 60-second timeout is generous but safe. If the API is slow, tenacity will retry after timeout errors.

### Search with only objective (no search_queries)
Valid. The API accepts either or both. When only `objective` is provided, Parallel generates its own keyword queries internally.

### Search with only search_queries (no objective)
Also valid. But for our use case, always provide an `objective` for better results — it tells Parallel what you're trying to learn, not just what to search for.