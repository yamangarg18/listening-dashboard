"""
Deduplication module.
Filters search results against existing entries in Notion databases.
"""

import difflib
from typing import List, Dict, Set, Tuple

from notion_client import query_database, parse_page_properties
from parallel_client import _normalize_url
from logger import setup_logger

logger = setup_logger("dedup")


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
    a = title_a.strip().lower()
    b = title_b.strip().lower()
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def get_existing_entries(
    main_kb_id: str,
    ingestion_queue_id: str,
) -> Tuple[Set[str], List[str]]:
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
    """
    urls: Set[str] = set()
    titles: List[str] = []
    
    main_kb_pages = query_database(main_kb_id)
    iq_pages = query_database(ingestion_queue_id)
    
    for page in main_kb_pages:
        parsed = parse_page_properties(page)
        url = parsed.get("URL")
        title = parsed.get("Title", "")
        if url:
            urls.add(_normalize_url(url))
        if title:
            titles.append(title)
    
    for page in iq_pages:
        parsed = parse_page_properties(page)
        url = parsed.get("URL")
        title = parsed.get("Title", "")
        if url:
            urls.add(_normalize_url(url))
        if title:
            titles.append(title)
    
    logger.info(f"get_existing_entries: Main KB={len(main_kb_pages)}, IQ={len(iq_pages)}, URLs={len(urls)}, Titles={len(titles)}")
    
    return urls, titles


def deduplicate_against_db(
    results: List[Dict],
    existing_urls: Set[str],
    existing_titles: List[str],
    similarity_threshold: float = 0.85,
) -> Tuple[List[Dict], List[Dict]]:
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
        - duplicates: List of results that were filtered out, each with
                     an added "duplicate_reason" field.
    """
    new_results: List[Dict] = []
    duplicates: List[Dict] = []
    
    url_match_count = 0
    title_match_count = 0
    
    for result in results:
        url = result.get("url", "")
        title = result.get("title", "")
        
        if not url:
            new_results.append(result)
            continue
        
        normalized_url = _normalize_url(url)
        
        if normalized_url in existing_urls:
            result["duplicate_reason"] = "url_match"
            duplicates.append(result)
            url_match_count += 1
            continue
        
        is_title_duplicate = False
        if title and existing_titles:
            for existing_title in existing_titles:
                ratio = _title_similarity(title, existing_title)
                if ratio >= similarity_threshold:
                    result["duplicate_reason"] = f"title_similar: {existing_title} ({ratio:.0%})"
                    duplicates.append(result)
                    title_match_count += 1
                    is_title_duplicate = True
                    break
        
        if not is_title_duplicate:
            new_results.append(result)
    
    logger.info(f"deduplicate_against_db: {len(results)} results → {len(new_results)} new, {len(duplicates)} dupes (url_match={url_match_count}, title_match={title_match_count})")
    
    return new_results, duplicates


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