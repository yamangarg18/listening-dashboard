"""
Extract module.
Polls Main KB for entries with Extract Content checked,
extracts full content via Parallel, and writes it back.
Implemented in Chunk 17.
"""

import time

from notion_client import query_database, parse_page_properties, update_page, append_blocks, _format_rich_text
from parallel_client import extract_url
from config import get_database_id
from logger import setup_logger

logger = setup_logger("extract")

MAX_CONTENT_CHARS = 95000

MAX_BLOCK_CHARS = 2000


def _content_to_blocks(content: str) -> list:
    """
    Convert plain text into Notion paragraph blocks.
    Each block max 2000 chars (Notion limit).
    """
    blocks = []
    for i in range(0, len(content), MAX_BLOCK_CHARS):
        chunk = content[i:i+MAX_BLOCK_CHARS]
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": chunk}}]
            }
        })
    return blocks


def run_extract_poll() -> dict:
    """
    Poll Main KB for entries with Extract Content = checked.
    For each one, extract the full content and write it back.

    Returns:
        Dict with summary:
        {
            "checked_entries": int,    # entries with Extract Content checked
            "extracted": int,          # successful extractions
            "failed": int,             # failed extractions
            "errors": list[str],       # error details
        }
    """
    main_kb_id = get_database_id("main_kb")

    pages = query_database(
        main_kb_id,
        filter={"property": "Extract Content", "checkbox": {"equals": True}},
    )
    entries = [parse_page_properties(p) for p in pages]

    summary = {
        "checked_entries": len(entries),
        "extracted": 0,
        "failed": 0,
        "errors": [],
    }

    if not entries:
        logger.info("No entries with Extract Content checked")
        return summary

    logger.info(f"Found {len(entries)} entries with Extract Content checked")

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
        if len(content) > MAX_CONTENT_CHARS:
            content = content[:MAX_CONTENT_CHARS] + "\n\n[Content truncated — full article at URL]"

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
        if len(content.strip()) < 100:
            ai_summary = "Content too short for summary."
            logger.warning(f"  Content too short ({len(content)} chars) — skipping LLM")
        else:
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
            try:
                update_page(entry_id, {"Extract Content": {"checkbox": False}})
            except:
                pass
            summary["failed"] += 1
            continue

        summary["extracted"] += 1
        logger.info(f"  Complete: {title[:60]}")

        time.sleep(0.5)

    logger.info(
        f"Extract poll complete: {summary['extracted']} extracted, "
        f"{summary['failed']} failed"
    )
    return summary


def run_extract_continuous(poll_interval: int = 30) -> None:
    """
    Continuously poll for extract requests.

    Runs in a loop, checking every poll_interval seconds for entries
    with Extract Content checked. Designed to run alongside the scheduler.

    Args:
        poll_interval: Seconds between polls (default 30).
    """
    import signal
    import sys

    logger.info(f"Extract poller started (checking every {poll_interval}s)")
    logger.info("Check 'Extract Content' on any Main KB entry to trigger extraction.")
    logger.info("Press Ctrl+C to stop.")

    def shutdown(signum, frame):
        logger.info("Extract poller stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    while True:
        try:
            summary = run_extract_poll()
            if summary["checked_entries"] > 0:
                logger.info(
                    f"Extract poll: {summary['extracted']} extracted, "
                    f"{summary['failed']} failed"
                )
        except Exception as e:
            logger.error(f"Extract poll error: {e}")

        time.sleep(poll_interval)


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
