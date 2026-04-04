"""
Parallel Web Systems API client.
Handles Search API calls for Stage 1 ingestion.
"""

import httpx
import json
import time
import urllib.parse
import re
from datetime import datetime
from typing import Optional, List, Dict
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from config import PARALLEL_API_KEY
from logger import setup_logger

logger = setup_logger("parallel_client")


PARALLEL_BASE_URL = "https://api.parallel.ai"
PARALLEL_HEADERS = {
    "Content-Type": "application/json",
    "x-api-key": PARALLEL_API_KEY,
}

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


def _get_client() -> httpx.Client:
    """Return a configured httpx client for Parallel API calls."""
    return httpx.Client(
        base_url=PARALLEL_BASE_URL,
        headers=PARALLEL_HEADERS,
        timeout=60.0,
    )


def _handle_response(response: httpx.Response) -> dict:
    """Check response status. Return JSON body on success. Raise exception on failure."""
    if response.status_code == 200:
        return response.json()

    error_message = f"Parallel API error {response.status_code}: {response.text}"
    raise httpx.HTTPStatusError(
        error_message,
        request=response.request,
        response=response,
    )


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception(lambda e: isinstance(e, httpx.HTTPStatusError) and (e.response.status_code == 429 or 500 <= e.response.status_code < 600)),
    reraise=True,
)
def search(
    objective: str,
    search_queries: Optional[List[str]] = None,
    max_results: int = 10,
    after_date: Optional[str] = None,
    exclude_domains: Optional[List[str]] = None,
    mode: str = "one-shot",
) -> List[dict]:
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
    """
    if exclude_domains is None:
        from config import EXCLUDE_DOMAINS
        exclude_domains = EXCLUDE_DOMAINS

    client = _get_client()

    payload: Dict = {
        "objective": objective,
        "max_results": max_results,
        "mode": mode,
        "excerpts": {
            "max_chars_per_result": 1500
        }
    }

    if search_queries:
        payload["search_queries"] = search_queries

    if after_date or exclude_domains:
        source_policy: Dict = {}
        if after_date:
            source_policy["after_date"] = after_date
        if exclude_domains:
            source_policy["exclude_domains"] = exclude_domains
        payload["source_policy"] = source_policy

    response = client.post("/v1beta/search", json=payload)
    result = _handle_response(response)

    results = result.get("results", [])
    search_id = result.get("search_id", "unknown")

    for r in results:
        r["excerpt_text"] = "\n\n".join(r.get("excerpts", []))
        if "publish_date" not in r:
            r["publish_date"] = None

    logger.info(f"Parallel search {search_id}: {len(results)} results")
    return results


def _normalize_url(url: str) -> str:
    """
    Normalize a URL for deduplication comparison.
    
    - Lowercase
    - Strip trailing slashes
    - Strip 'www.' prefix from domain
    - Strip query parameters (?...) 
    - Strip fragment (#...)
    """
    parsed = urllib.parse.urlparse(url)
    
    scheme = parsed.scheme.lower() if parsed.scheme else "https"
    netloc = parsed.netloc.lower()
    
    if netloc.startswith("www."):
        netloc = netloc[4:]
    
    path = parsed.path.rstrip("/")
    
    normalized = urllib.parse.urlunparse((scheme, netloc, path, "", "", ""))
    return normalized


def generate_variant_queries(topic: str, num_variants: int = 6) -> List[Dict]:
    """
    Generate variant search configurations from a topic.
    
    Each variant has a different objective and search_queries to
    approach the topic from a different angle.
    
    Args:
        topic: The main topic to generate variants for.
        num_variants: Number of variants to generate (default 6).
    
    Returns:
        List of dicts, each with:
        - "objective": str — natural language search objective
        - "search_queries": list[str] — keyword queries
        - "label": str — human-readable label for logging
    """
    if not topic:
        raise ValueError("topic cannot be empty")

    current_year = str(datetime.now().year)

    raw_variants = _load_search_config()
    enabled = [v for v in raw_variants if v.get("enabled", True)]

    result = []
    for v in enabled[:num_variants]:
        interpolated_obj = v["objective"].replace("{topic}", topic).replace("{year}", current_year)
        interpolated_queries = [q.replace("{topic}", topic).replace("{year}", current_year) for q in v["search_queries"]]
        result.append({
            "label": v["label"],
            "objective": interpolated_obj,
            "search_queries": interpolated_queries,
        })

    return result


_DEFAULT_VARIANTS = [
    {
        "label": "breaking",
        "objective": "Breaking news published in the last 48 hours about {topic}, robotics, or autonomous systems",
        "search_queries": ["{topic} news today", "robotics announcement this week"],
        "enabled": True,
    },
    {
        "label": "funding",
        "objective": "Venture capital funding rounds, acquisitions, and IPOs for {topic} and robotics startups in {year}",
        "search_queries": ["{topic} series A B C funding {year}", "robotics startup acquisition {year}"],
        "enabled": True,
    },
    {
        "label": "policy",
        "objective": "Government regulations, export controls, trade policy, and legislative actions affecting {topic} and AI",
        "search_queries": ["AI robotics regulation {year}", "export controls autonomous systems policy"],
        "enabled": True,
    },
    {
        "label": "research",
        "objective": "Academic papers, university research, and technical breakthroughs in {topic}, embodied AI, and robot learning",
        "search_queries": ["{topic} research paper {year}", "embodied AI robot learning breakthrough"],
        "enabled": True,
    },
    {
        "label": "india",
        "objective": "India-specific developments in {topic}, robotics manufacturing, automation policy, and Make in India for robotics",
        "search_queries": ["India robotics {topic} {year}", "India manufacturing automation AI policy"],
        "enabled": True,
    },
    {
        "label": "ecosystem",
        "objective": "Industry analysis, market reports, competitive landscape, and ecosystem mapping for {topic} and robotics industry",
        "search_queries": ["{topic} market analysis report {year}", "robotics industry landscape competitive analysis"],
        "enabled": True,
    },
]


def _load_search_config() -> List[Dict]:
    """
    Load variant templates from search_config.json.
    Falls back to hardcoded defaults if file doesn't exist or is invalid.
    """
    from config import SEARCH_CONFIG_PATH

    try:
        with open(SEARCH_CONFIG_PATH, "r") as f:
            config = json.load(f)
        variants = config.get("variants", [])
        if not variants:
            logger.warning("search_config.json has no variants — using defaults")
            return _DEFAULT_VARIANTS
        logger.debug(f"Loaded {len(variants)} variants from {SEARCH_CONFIG_PATH}")
        return variants
    except FileNotFoundError:
        logger.info(f"{SEARCH_CONFIG_PATH} not found — using default variants")
        return _DEFAULT_VARIANTS
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {SEARCH_CONFIG_PATH}: {e} — using defaults")
        return _DEFAULT_VARIANTS


def _extract_domain(url: str) -> Optional[str]:
    """Extract domain from URL for progressive exclusion."""
    if not url:
        return None
    from urllib.parse import urlparse
    netloc = urlparse(url).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc if netloc else None


def search_multiple(
    topic: str,
    after_date: Optional[str] = None,
    max_results_per_query: int = 10,
    num_variants: int = 6,
    exclude_domains: Optional[List[str]] = None,
) -> List[Dict]:
    """
    Run multiple variant searches on a topic and return deduplicated results.
    
    Generates variant queries from the topic, runs each one via search(),
    deduplicates by URL, and returns the combined result set.
    
    Args:
        topic: The main topic to search for.
        after_date: Only return results published on or after this date.
                   Format: "YYYY-MM-DD". None = no date filter.
        max_results_per_query: Max results per individual search (default 10).
        num_variants: Number of variant queries to run (default 6).
        exclude_domains: Domains to exclude. Max 10.
    
    Returns:
        List of deduplicated result dicts (same format as search() output).
        Each result also includes:
        - "found_by": list[str] — labels of variant queries that found this URL
    
    Raises:
        Exception: If all searches fail.
    """
    if not topic:
        raise ValueError("topic cannot be empty")
    
    if num_variants <= 0:
        return []
    
    variants = generate_variant_queries(topic, num_variants)
    
    # Start with config exclude domains
    if exclude_domains is None:
        from config import EXCLUDE_DOMAINS
        base_excludes = list(EXCLUDE_DOMAINS)
    else:
        base_excludes = list(exclude_domains)

    all_results = []
    seen_domains = set()
    errors = []

    for variant in variants:
        # Build exclude list: base + domains already seen (cap at 10)
        cycle_excludes = list(base_excludes)
        for domain in seen_domains:
            if domain not in cycle_excludes and len(cycle_excludes) < 10:
                cycle_excludes.append(domain)

        logger.info(f"Running variant search: [{variant['label']}] "
                    f"(excluding {len(cycle_excludes)} domains)")

        try:
            results = search(
                objective=variant["objective"],
                search_queries=variant["search_queries"],
                max_results=max_results_per_query,
                after_date=after_date,
                exclude_domains=cycle_excludes,
            )

            # Track domains from these results
            for r in results:
                domain = _extract_domain(r.get("url", ""))
                if domain:
                    seen_domains.add(domain)

            for r in results:
                r["found_by"] = [variant["label"]]

            all_results.extend(results)
        except Exception as e:
            logger.error(f"Variant [{variant['label']}] failed: {e}")
            errors.append((variant["label"], str(e)))

        time.sleep(0.5)
    
    if not all_results and errors:
        error_summary = "; ".join([f"{label}: {err}" for label, err in errors])
        raise Exception(f"All variant searches failed: {error_summary}")
    
    total_before = len(all_results)
    
    seen_urls = {}
    for r in all_results:
        normalized = _normalize_url(r["url"])
        if normalized not in seen_urls:
            seen_urls[normalized] = r
        else:
            seen_urls[normalized]["found_by"].extend(r["found_by"])
    
    deduplicated = list(seen_urls.values())
    total_after = len(deduplicated)
    duplicates_removed = total_before - total_after
    
    logger.info(f"search_multiple: {total_before} raw, "
                f"{duplicates_removed} cross-variant duplicates, "
                f"{total_after} unique")

    before_quality = len(deduplicated)
    quality_results = [r for r in deduplicated if _is_quality_source(r)]
    quality_filtered = before_quality - len(quality_results)

    if quality_filtered > 0:
        logger.info(f"Quality filter: removed {quality_filtered} low-quality results")

    # Domain diversity
    domains = set()
    for r in quality_results:
        d = _extract_domain(r.get("url", ""))
        if d:
            domains.add(d)
    logger.info(f"  Source diversity: {len(domains)} unique domains")

    return quality_results


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception(lambda e: isinstance(e, httpx.HTTPStatusError) and (e.response.status_code == 429 or 500 <= e.response.status_code < 600)),
    reraise=True,
)
def extract_url(url: str) -> Optional[str]:
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
    client = _get_client()
    client.timeout = 120.0

    try:
        response = client.post(
            "/v1beta/extract",
            json={
                "urls": [url],
                "full_content": True,
                "excerpts": False,
            },
        )

        if response.status_code != 200:
            logger.error(f"Extract API error {response.status_code}: {response.text[:200]}")
            return None

        result = response.json()

        errors = result.get("errors", [])
        if errors:
            for err in errors:
                logger.error(
                    f"Extract failed for {err.get('url', url)}: "
                    f"{err.get('error_type', 'unknown')} — {err.get('content', '')[:100]}"
                )
            return None

        results = result.get("results", [])
        if not results:
            logger.warning(f"Extract returned no results for {url}")
            return None

        return results[0].get("full_content", "")

    except Exception as e:
        logger.error(f"Extract failed for {url}: {e}")
        return None


if __name__ == "__main__":
    from config import TOPIC, EXCLUDE_DOMAINS

    # --- Test 1: Verify variant objectives are distinct ---
    print("Test 1: Variant query diversity...")
    variants = generate_variant_queries(TOPIC)

    objectives = [v["objective"] for v in variants]
    for i, v in enumerate(variants):
        print(f"  [{v['label']}] {v['objective'][:70]}")

    # Check no two objectives share more than 3 words (crude distinctness check)
    for i in range(len(objectives)):
        for j in range(i+1, len(objectives)):
            words_i = set(objectives[i].lower().split())
            words_j = set(objectives[j].lower().split())
            shared = words_i & words_j - {"in", "and", "the", "of", "for", "a", "an", "to", TOPIC.lower()}
            if len(shared) > 5:
                print(f"  WARNING: [{variants[i]['label']}] and [{variants[j]['label']}] share {len(shared)} content words: {shared}")

    print("  Variant diversity: CHECK PASSED")

    # --- Test 2: Run search and check domain diversity ---
    print(f"\nTest 2: Running search with progressive domain exclusion...")
    results = search_multiple(
        topic=TOPIC,
        max_results_per_query=10,
        num_variants=4,
    )

    domains = set()
    for r in results:
        d = _extract_domain(r.get("url", ""))
        if d:
            domains.add(d)

    print(f"  Results: {len(results)}")
    print(f"  Unique domains: {len(domains)}")
    print(f"  Domain diversity ratio: {len(domains)/max(len(results),1):.1%}")

    if len(domains) >= 10:
        print("  Domain diversity: GOOD (10+ sources)")
    elif len(domains) >= 5:
        print("  Domain diversity: OK (5-9 sources)")
    else:
        print("  Domain diversity: LOW (<5 sources) — may need tuning")

    print("\nAll uniqueness tests completed!")