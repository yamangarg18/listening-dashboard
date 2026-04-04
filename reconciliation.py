"""
Stage 2 — Reconciliation.
Reads Ingestion Queue + Main KB → OpenAI → update Notion.
Implemented in Chunk 11.
"""

import time
from datetime import datetime, timezone, timedelta
from typing import List

from notion_client import (
    query_database,
    parse_page_properties,
    create_page,
    build_page_properties,
    update_page,
    archive_page,
    _format_rich_text,
)
from config import get_database_id, TOPIC
from openai_client import analyze_articles_batched
from parallel_client import _normalize_url
from escalation import check_and_escalate
from logger import setup_logger

logger = setup_logger("reconciliation")

IST = timezone(timedelta(hours=5, minutes=30))


def _sanitize_multi_select(values: List[str]) -> List[str]:
    """Remove commas from multi-select option names (Notion doesn't allow commas in select options)."""
    return [v.replace(",", "") for v in values]


def _infer_source_type(source_name: str) -> str:
    """
    Infer source type from domain name.
    Returns: News, Blog, Academic, Social Media, Forum, Government, or Other
    """
    if not source_name:
        return "Other"

    source_lower = source_name.lower()

    academic = ["arxiv", "ieee", "scholar", "nature", "science", "springer",
                "wiley", "acm", "researchgate", "ssrn", "pubmed", "biorxiv"]
    social = ["linkedin", "twitter", "x.com", "reddit", "facebook", "instagram"]
    forum = ["hackernews", "ycombinator", "stackoverflow", "quora", "slashdot"]
    gov = ["gov", "pib", "niti", "dpiit", "whitehouse", "europa", "congress"]
    blog = ["medium", "substack", "wordpress", "blogger", "ghost", "hashnode"]

    # Check TLD first — "gov", "edu", "org", "mil" domains are government/academic/org, not news
    tld = source_lower.split(".")[-1] if "." in source_lower else ""
    if tld in ("gov", "edu", "mil"):
        return "Government"
    if tld in ("org",):
        return "Academic"

    # Check specific domains (these take priority over keyword matches)
    news = ["reuters", "bloomberg", "techcrunch", "bbc", "cnn", "nytimes",
            "wsj", "ft", "economictimes", "scmp", "politico", "businessinsider",
            "theverge", "wired", "arstechnica", "cnbc", "forbes", "guardian",
            "washingtonpost", "apnews", "aljazeera", "newsroom"]
    for domain in news:
        if domain in source_lower:
            return "News"

    for domain in academic:
        if domain in source_lower:
            return "Academic"
    for domain in social:
        if domain in source_lower:
            return "Social Media"
    for domain in forum:
        if domain in source_lower:
            return "Forum"
    for domain in gov:
        if domain in source_lower:
            return "Government"
    for domain in blog:
        if domain in source_lower:
            return "Blog"

    return "Other"


def run_reconciliation() -> dict:
    """
    Execute Stage 2: process all entries in the Ingestion Queue.

    Returns:
        Dict with reconciliation summary:
        {
            "queue_entries": int,
            "analyzed": int,
            "new_entries": int,
            "updated_entries": int,
            "archived_from_queue": int,
            "errors": list[str],
        }
    """
    iq_id = get_database_id("ingestion_queue")
    main_kb_id = get_database_id("main_kb")

    # Step 1: Read Ingestion Queue
    raw_pages = query_database(iq_id)
    parsed_entries = [parse_page_properties(p) for p in raw_pages]

    if not parsed_entries:
        logger.info("Ingestion Queue is empty — nothing to reconcile")
        return {
            "queue_entries": 0,
            "analyzed": 0,
            "new_entries": 0,
            "updated_entries": 0,
            "archived_from_queue": 0,
            "errors": [],
        }

    logger.info(f"Found {len(parsed_entries)} entries in Ingestion Queue")

    # Step 2: Prepare articles for OpenAI
    articles_for_ai = []
    for entry in parsed_entries:
        articles_for_ai.append({
            "title": entry.get("Title", ""),
            "url": entry.get("URL", ""),
            "publish_date": entry.get("Published Date"),
            "source_name": entry.get("Source Name", ""),
            "excerpt_text": entry.get("Raw Summary", ""),
        })

    # Step 3: Analyze with OpenAI
    analyses = analyze_articles_batched(articles_for_ai, TOPIC)
    logger.info(f"OpenAI returned {len(analyses)} analyses for {len(articles_for_ai)} articles")

    # Step 4: Match analyses to queue entries by index
    paired = []
    for i, entry in enumerate(parsed_entries):
        if i < len(analyses):
            paired.append((entry, analyses[i]))
        else:
            logger.warning(f"No analysis for entry {i} ({entry.get('Title', 'unknown')}) — skipping")
            paired.append((entry, None))

    # Step 5: Read Main KB for URL matching
    existing_pages = query_database(main_kb_id)
    existing_parsed = [parse_page_properties(p) for p in existing_pages]

    url_lookup = {}
    for ep in existing_parsed:
        url = ep.get("URL")
        if url:
            url_lookup[_normalize_url(url)] = ep

    logger.info(f"Main KB has {len(url_lookup)} entries for URL matching")

    # Step 6: Process each entry
    successfully_processed_ids = []
    new_entries = 0
    updated_entries = 0
    errors = []

    for entry, analysis in paired:
        entry_id = entry.get("id")
        url = entry.get("URL", "")
        normalized_url = _normalize_url(url) if url else None

        if analysis is None:
            errors.append(f"Entry '{entry.get('Title', 'unknown')}' has no analysis — skipped")
            continue

        try:
            if normalized_url and normalized_url in url_lookup:
                # --- Update existing entry ---
                existing_entry = url_lookup[normalized_url]
                existing_id = existing_entry["id"]

                changes = []
                if existing_entry.get("Signal Level") != analysis.get("signal_level"):
                    changes.append(
                        f"Signal: {existing_entry.get('Signal Level')} → {analysis.get('signal_level')}"
                    )
                if existing_entry.get("Category") != analysis.get("category"):
                    changes.append(
                        f"Category: {existing_entry.get('Category')} → {analysis.get('category')}"
                    )

                old_log = existing_entry.get("Change Log", "") or ""
                timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
                new_log_entry = f"[{timestamp}] {'; '.join(changes)}" if changes else ""
                updated_log = f"{old_log}\n{new_log_entry}".strip() if new_log_entry else old_log

                update_props = {
                    "Signal Level": {"select": {"name": analysis.get("signal_level", "Low")}},
                    "Category": {"select": {"name": analysis.get("category", "Other")}},
                    "Confidence Score": {"number": analysis.get("confidence_score", 0.5)},
                    "Half-Life Class": {"select": {"name": analysis.get("half_life_class", "Discourse")}},
                    "Dedup Status": {"select": {"name": "Updated"}},
                    "Last Updated": {"date": {"start": datetime.now(IST).isoformat()}},
                }

                if new_log_entry:
                    update_props["Change Log"] = {
                        "rich_text": [{"type": "text", "text": {"content": updated_log}}]
                    }

                merged_entities = list(set(existing_entry.get("Key Entities", []) + _sanitize_multi_select(analysis.get("key_entities", []))))
                merged_tags = list(set(existing_entry.get("Topic Tags", []) + _sanitize_multi_select(analysis.get("topic_tags", []))))
                update_props["Key Entities"] = {"multi_select": [{"name": e} for e in merged_entities]}
                update_props["Topic Tags"] = {"multi_select": [{"name": t} for t in merged_tags]}

                update_page(existing_id, update_props)
                time.sleep(0.35)
                updated_entries += 1
                successfully_processed_ids.append(entry_id)
                logger.info(f"Updated existing entry: {existing_entry.get('Title', 'unknown')[:50]}")
            else:
                # --- Create new entry in Main KB ---
                discovered = entry.get("Discovered Date") or datetime.now(IST).isoformat()
                props = build_page_properties(
                    title=entry.get("Title") or analysis.get("title", "Untitled"),
                    url=url or None,
                    rich_text_fields={
                        "Source Name": entry.get("Source Name", ""),
                        "Raw Summary": entry.get("Raw Summary", ""),
                        "One-Line Summary": analysis.get("one_line_summary", ""),
                        "Why It Matters": analysis.get("why_it_matters", ""),
                    },
                    select_fields={
                        "Source Type": _infer_source_type(entry.get("Source Name", "")),
                        "Signal Level": analysis.get("signal_level", "Low"),
                        "Category": analysis.get("category", "Other"),
                        "Retrieval Method": entry.get("Retrieval Method", ""),
                        "Search Cycle": entry.get("Search Cycle", ""),
                        "Decay Status": "Active",
                        "Half-Life Class": analysis.get("half_life_class", "Discourse"),
                        "Dedup Status": "New",
                    },
                    multi_select_fields={
                        "Key Entities": _sanitize_multi_select(analysis.get("key_entities", [])),
                        "Topic Tags": _sanitize_multi_select(analysis.get("topic_tags", [])),
                        "Framework Mapping": _sanitize_multi_select(analysis.get("framework_mapping", [])),
                    },
                    date_fields={
                        "Published Date": entry.get("Published Date"),
                        "Discovered Date": discovered,
                        "Last Updated": datetime.now(IST).isoformat(),
                    },
                    number_fields={
                        "Confidence Score": analysis.get("confidence_score", 0.5),
                        "Priority Score": 0,
                    },
                    checkbox_fields={
                        "Seen By User": False,
                        "Extract Content": False,
                    },
                )
                create_page(main_kb_id, props)
                time.sleep(0.35)
                new_entries += 1
                successfully_processed_ids.append(entry_id)
                logger.info(f"Created new entry: {entry.get('Title', 'unknown')[:50]}")
        except Exception as e:
            logger.error(f"Failed to process entry '{entry.get('Title', 'unknown')}': {e}")
            errors.append(f"Entry '{entry.get('Title', 'unknown')}': {e}")
            continue

    # Escalation: send emails for high-signal entries
    entries_for_escalation = []
    for queue_entry, analysis in paired:
        if queue_entry.get("id") in successfully_processed_ids and analysis is not None:
            merged = {**analysis}
            merged["url"] = queue_entry.get("URL", "")
            merged["source_name"] = queue_entry.get("Source Name", "")
            merged["publish_date"] = queue_entry.get("Published Date")
            entries_for_escalation.append(merged)

    escalation_count = check_and_escalate(entries_for_escalation)
    logger.info(f"Escalation: sent {escalation_count} high-signal alerts")

    # Step 7: Archive processed queue entries
    archived_from_queue = 0
    for entry_id in successfully_processed_ids:
        try:
            archive_page(entry_id)
            time.sleep(0.35)
            archived_from_queue += 1
        except Exception as e:
            logger.error(f"Failed to archive queue entry {entry_id}: {e}")
            errors.append(f"Archive failed for {entry_id}: {e}")

    # Step 8: Log summary and return
    summary = {
        "queue_entries": len(parsed_entries),
        "analyzed": len(analyses),
        "new_entries": new_entries,
        "updated_entries": updated_entries,
        "archived_from_queue": archived_from_queue,
        "escalations_sent": escalation_count,
        "errors": errors,
    }

    logger.info(
        f"Reconciliation complete: {new_entries} new, {updated_entries} updated, "
        f"{archived_from_queue} archived, {len(errors)} errors"
    )

    return summary


if __name__ == "__main__":
    print("Running Stage 2 Reconciliation manually...")
    print("Make sure Ingestion Queue has entries (run ingestion.py first).\n")

    summary = run_reconciliation()

    print(f"\n{'='*60}")
    print(f"RECONCILIATION SUMMARY")
    print(f"{'='*60}")
    print(f"Queue entries:        {summary['queue_entries']}")
    print(f"Analyzed by OpenAI:   {summary['analyzed']}")
    print(f"New in Main KB:       {summary['new_entries']}")
    print(f"Updated in Main KB:   {summary['updated_entries']}")
    print(f"Archived from queue:  {summary['archived_from_queue']}")
    if summary['errors']:
        print(f"Errors:               {len(summary['errors'])}")
        for e in summary['errors']:
            print(f"  - {e}")
    print(f"{'='*60}")
