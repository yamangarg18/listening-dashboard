"""
Stage 1: Ingestion Pipeline.
Searches the web, deduplicates against existing entries,
and writes new entries to the Notion Ingestion Queue.
"""

import time
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Tuple

from notion_client import create_page, build_page_properties, query_database, parse_page_properties
from parallel_client import search_multiple, _normalize_url
from dedup import deduplicate_against_db, get_existing_entries
from config import get_database_id, load_state, save_state, TOPIC, PASS_B_LOOKBACK_DAYS
from logger import setup_logger

logger = setup_logger("ingestion")

IST = timezone(timedelta(hours=5, minutes=30))


def extract_source_name(url: str) -> str:
    """
    Extract a human-readable source name from a URL.
    
    Examples:
        "https://www.reuters.com/article/xyz" → "reuters.com"
        "https://techcrunch.com/2026/04/..." → "techcrunch.com"
        "https://arxiv.org/abs/2026.1234" → "arxiv.org"
    
    Returns the domain name without 'www.' prefix.
    """
    if not url:
        return "Unknown"
    
    netloc = urllib.parse.urlparse(url).netloc
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc or "Unknown"


def _merge_passes(results_a: List[Dict], results_b: List[Dict]) -> List[Dict]:
    """
    Merge Pass A and Pass B results, deduplicate by URL,
    and tag each result with its retrieval method.
    
    If a URL appears in both passes, keep the Pass A version
    and tag it as "Both".
    """
    seen_urls: Dict[str, Dict] = {}
    
    for r in results_a:
        normalized = _normalize_url(r["url"])
        if normalized not in seen_urls:
            r["retrieval_method"] = "Time-window"
            seen_urls[normalized] = r
        else:
            seen_urls[normalized]["retrieval_method"] = "Both"
    
    for r in results_b:
        normalized = _normalize_url(r["url"])
        if normalized not in seen_urls:
            r["retrieval_method"] = "Relevance-ranked"
            seen_urls[normalized] = r
        else:
            if seen_urls[normalized]["retrieval_method"] == "Time-window":
                seen_urls[normalized]["retrieval_method"] = "Both"
    
    return list(seen_urls.values())


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
            "pass_a_results": int,
            "pass_b_results": int,
            "combined_raw": int,
            "after_cross_dedup": int,
            "duplicates_db": int,
            "new_entries": int,
            "errors": list[str],
        }
    """
    logger.info(f"=== Ingestion Cycle {cycle_number} Starting ===")
    
    state = load_state()
    last_run_key = f"cycle_{cycle_number}"
    last_run_timestamp = state.get("last_run", {}).get(last_run_key)
    
    main_kb_id = get_database_id("main_kb")
    iq_id = get_database_id("ingestion_queue")
    
    pass_a_date = None
    if last_run_timestamp:
        pass_a_dt = datetime.fromisoformat(last_run_timestamp)
        pass_a_date = pass_a_dt.strftime("%Y-%m-%d")
    else:
        seven_days_ago = datetime.now(IST) - timedelta(days=7)
        pass_a_date = seven_days_ago.strftime("%Y-%m-%d")
    
    logger.info(f"Pass A date filter: {pass_a_date}")
    
    results_a = []
    pass_a_error = None
    try:
        results_a = search_multiple(
            topic=TOPIC,
            after_date=pass_a_date,
            max_results_per_query=10,
            num_variants=4,
        )
    except Exception as e:
        pass_a_error = str(e)
        logger.error(f"Pass A failed: {e}")
    
    logger.info(f"Pass A (time-window after {pass_a_date}): {len(results_a)} results")
    
    results_b = []
    pass_b_error = None
    pass_b_date = (datetime.now(IST) - timedelta(days=PASS_B_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    try:
        results_b = search_multiple(
            topic=TOPIC,
            after_date=pass_b_date,
            max_results_per_query=10,
            num_variants=6,
        )
    except Exception as e:
        pass_b_error = str(e)
        logger.error(f"Pass B failed: {e}")

    logger.info(f"Pass B (relevance-ranked after {pass_b_date}): {len(results_b)} results")
    
    if not results_a and not results_b:
        raise Exception(f"Both search passes failed. Pass A: {pass_a_error}. Pass B: {pass_b_error}.")
    
    combined = _merge_passes(results_a, results_b)
    raw_count = len(results_a) + len(results_b)
    logger.info(f"Combined: {raw_count} → {len(combined)} after cross-dedup")
    
    existing_urls, existing_titles = get_existing_entries(main_kb_id, iq_id)
    new_results, duplicates = deduplicate_against_db(
        combined, existing_urls, existing_titles
    )
    logger.info(f"Database dedup: {len(duplicates)} duplicates filtered, {len(new_results)} new entries")
    
    written = 0
    write_errors = []
    
    for result in new_results:
        source = extract_source_name(result.get("url", ""))
        discovered = datetime.now(IST).isoformat()
        
        date_fields = {"Discovered Date": discovered}
        if result.get("publish_date"):
            date_fields["Published Date"] = result["publish_date"]
        
        props = build_page_properties(
            title=result.get("title", "Untitled"),
            url=result.get("url"),
            rich_text_fields={
                "Source Name": source,
                "Raw Summary": result.get("excerpt_text", ""),
            },
            select_fields={
                "Retrieval Method": result.get("retrieval_method", "Relevance-ranked"),
                "Search Cycle": str(cycle_number),
            },
            date_fields=date_fields,
        )
        
        try:
            create_page(iq_id, props)
            written += 1
            time.sleep(0.35)
        except Exception as e:
            logger.error(f"Failed to write {result.get('url')}: {e}")
            write_errors.append(f"{result.get('url')}: {e}")
    
    now_ist = datetime.now(IST)
    state = load_state()
    if "last_run" not in state:
        state["last_run"] = {}
    state["last_run"][last_run_key] = now_ist.isoformat()
    if not state.get("first_run_complete"):
        state["first_run_complete"] = True
    save_state(state)
    
    summary = {
        "cycle": cycle_number,
        "pass_a_results": len(results_a),
        "pass_b_results": len(results_b),
        "combined_raw": raw_count,
        "after_cross_dedup": len(combined),
        "duplicates_db": len(duplicates),
        "new_entries": written,
        "errors": write_errors,
    }
    
    logger.info(f"=== Ingestion Cycle {cycle_number} Complete ===")
    logger.info(f"Summary: {written} new entries written, {len(write_errors)} errors")
    
    return summary


if __name__ == "__main__":
    import sys
    
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