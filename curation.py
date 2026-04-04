"""
Stage 3 — Curation & Brief Generation.
Reads Main KB + priorities → OpenAI → write brief to Notion.
Implemented in Chunk 15.
"""

import time
from datetime import datetime, timezone, timedelta

from notion_client import (
    query_database,
    parse_page_properties,
    create_page,
    build_page_properties,
    update_page,
    read_page_content,
    append_blocks,
    _format_rich_text,
)
from openai_client import generate_daily_brief
from config import get_database_id, TOPIC, PRIORITIES_PAGE_ID
from logger import setup_logger

logger = setup_logger("curation")

IST = timezone(timedelta(hours=5, minutes=30))


def _build_block(block_type: str, text: str, bold: bool = False) -> dict:
    """
    Build a Notion block object.

    Args:
        block_type: heading_1, heading_2, heading_3, paragraph,
                   bulleted_list_item, numbered_list_item
        text: The text content
        bold: Whether to bold the text

    Returns:
        Block dict ready for the blocks API.
    """
    rich_text_obj = {"type": "text", "text": {"content": text}}
    if bold:
        rich_text_obj["annotations"] = {"bold": True}

    return {
        "object": "block",
        "type": block_type,
        block_type: {
            "rich_text": [rich_text_obj]
        }
    }


def _build_divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def _write_brief_body(page_id: str, brief: dict, entries: list) -> None:
    """
    Write the full brief content as blocks into a Notion page body.

    Formats the brief sections as headings, paragraphs, and lists.
    """
    blocks = []

    blocks.append(_build_block("heading_1", "Executive Summary"))
    blocks.append(_build_block("paragraph", brief.get("executive_summary", "")))
    blocks.append(_build_divider())

    blocks.append(_build_block("heading_1", "Synthesis Insights"))
    synth_insights = brief.get("synthesis_insights", [])
    if synth_insights:
        for i, insight in enumerate(synth_insights, 1):
            blocks.append(_build_block("heading_3", f"Synthesis {i}", bold=True))
            blocks.append(_build_block("paragraph", f"Inference: {insight.get('inference', '')}"))
            contrib = insight.get("contributing_entries", [])
            blocks.append(_build_block("bulleted_list_item", "Contributing entries: " + ", ".join(contrib)))
            blocks.append(_build_block("paragraph", f"Relevance: {insight.get('relevance', '')}"))
    else:
        blocks.append(_build_block("paragraph", "No synthesis insights today."))
    blocks.append(_build_divider())

    blocks.append(_build_block("heading_1", "High-Priority Entries"))
    hp_entries = brief.get("high_priority_entries", [])
    if hp_entries:
        for entry in hp_entries:
            text = (
                f"[{entry.get('signal_level', 'N/A')}] "
                f"[{entry.get('region', 'N/A')}] "
                f"{entry.get('title', 'Unknown')}: "
                f"{entry.get('summary', '')}"
            )
            blocks.append(_build_block("bulleted_list_item", text))
    else:
        blocks.append(_build_block("paragraph", "No high-priority entries today."))
    blocks.append(_build_divider())

    blocks.append(_build_block("heading_1", "Updated Entries"))
    updated = brief.get("updated_entries", [])
    if updated:
        for u in updated:
            text = f"{u.get('title', 'Unknown')}: {u.get('change_description', '')}"
            blocks.append(_build_block("bulleted_list_item", text))
    else:
        blocks.append(_build_block("paragraph", "No updates today."))
    blocks.append(_build_divider())

    blocks.append(_build_block("heading_1", "Decay Recommendations"))
    decay = brief.get("decay_recommendations", [])
    if decay:
        for d in decay:
            text = (
                f"{d.get('title', 'Unknown')}: "
                f"{d.get('current_status', '')} → {d.get('recommended_status', '')} "
                f"({d.get('reason', '')})"
            )
            blocks.append(_build_block("bulleted_list_item", text))
    else:
        blocks.append(_build_block("paragraph", "No decay recommendations today."))

    append_blocks(page_id, blocks)


def run_daily_brief() -> dict:
    """
    Execute Stage 3: generate and publish the daily brief.

    Returns:
        Dict with summary:
        {
            "active_entries": int,
            "brief_generated": bool,
            "brief_page_id": str | None,
            "synthesis_records": int,
            "entries_scored": int,
            "entries_decayed": int,
            "entries_marked_seen": int,
            "errors": list[str],
        }
    """
    main_kb_id = get_database_id("main_kb")
    synthesis_id = get_database_id("synthesis")
    brief_log_id = get_database_id("brief_log")

    summary = {
        "active_entries": 0,
        "brief_generated": False,
        "brief_page_id": None,
        "synthesis_records": 0,
        "entries_scored": 0,
        "entries_decayed": 0,
        "entries_marked_seen": 0,
        "errors": [],
    }

    pages = query_database(
        main_kb_id,
        filter={"property": "Decay Status", "select": {"equals": "Active"}},
    )
    entries = [parse_page_properties(p) for p in pages]
    summary["active_entries"] = len(entries)

    if not entries:
        logger.warning("No active entries in Main KB — skipping daily brief")
        return summary

    priorities = ""
    if PRIORITIES_PAGE_ID:
        priorities = read_page_content(PRIORITIES_PAGE_ID)
    else:
        logger.warning("PRIORITIES_PAGE_ID not set — brief will use general ranking")

    brief = generate_daily_brief(entries, priorities, TOPIC)
    summary["brief_generated"] = True

    synthesis_page_ids = []
    for insight in brief.get("synthesis_insights", []):
        linked_ids = []
        for entry_title in insight.get("contributing_entries", []):
            for entry in entries:
                if entry.get("Title", "").strip() == entry_title.strip():
                    linked_ids.append(entry["id"])
                    break

        inference_text = insight.get("inference", "")
        props = build_page_properties(
            title=inference_text[:80],
            title_property_name="Synthesis Title",
            rich_text_fields={
                "Inference": inference_text,
            },
            date_fields={
                "Generated Date": datetime.now(IST).strftime("%Y-%m-%d"),
            },
            select_fields={
                "Relevance Window": "2 Weeks",
            },
            relation_fields={
                "Linked Entries": linked_ids,
            } if linked_ids else {},
        )
        try:
            synth_page_id = create_page(synthesis_id, props)
            synthesis_page_ids.append(synth_page_id)
            time.sleep(0.35)
        except Exception as e:
            logger.error(f"Failed to create synthesis record: {e}")
            summary["errors"].append(f"Synthesis record creation failed: {e}")

    summary["synthesis_records"] = len(synthesis_page_ids)

    surfaced_ids = []
    for hp_entry in brief.get("high_priority_entries", []):
        for entry in entries:
            if entry.get("Title", "").strip() == hp_entry.get("title", "").strip():
                surfaced_ids.append(entry["id"])
                break

    today = datetime.now(IST).strftime("%Y-%m-%d")
    brief_props = build_page_properties(
        title=f"Daily Brief — {today}",
        title_property_name="Brief Title",
        rich_text_fields={
            "Executive Summary": brief.get("executive_summary", ""),
        },
        date_fields={
            "Brief Date": today,
            "Delivered At": datetime.now(IST).isoformat(),
        },
        relation_fields={
            "Entries Surfaced": surfaced_ids,
            "Syntheses Surfaced": synthesis_page_ids,
        },
    )
    try:
        brief_page_id = create_page(brief_log_id, brief_props)
        summary["brief_page_id"] = brief_page_id
        time.sleep(0.35)
        _write_brief_body(brief_page_id, brief, entries)
    except Exception as e:
        logger.error(f"Failed to create brief page: {e}")
        summary["errors"].append(f"Brief page creation failed: {e}")
        return summary

    entries_scored = 0
    for hp_entry in brief.get("high_priority_entries", []):
        for entry in entries:
            if entry.get("Title", "").strip() == hp_entry.get("title", "").strip():
                try:
                    update_page(entry["id"], {
                        "Priority Score": {"number": hp_entry.get("priority_score", 0)},
                        "Seen By User": {"checkbox": True},
                    })
                    entries_scored += 1
                    time.sleep(0.35)
                except Exception as e:
                    logger.error(f"Failed to update priority score: {e}")
                    summary["errors"].append(f"Priority score update failed for {entry.get('Title', 'unknown')}: {e}")
                break

    summary["entries_scored"] = entries_scored
    summary["entries_marked_seen"] = entries_scored

    entries_decayed = 0
    for rec in brief.get("decay_recommendations", []):
        for entry in entries:
            if entry.get("Title", "").strip() == rec.get("title", "").strip():
                current = entry.get("Decay Status", "")
                recommended = rec.get("recommended_status", "")
                if recommended in ("Aging", "Archived") and current != recommended:
                    try:
                        update_props = {
                            "Decay Status": {"select": {"name": recommended}},
                        }
                        if recommended == "Archived":
                            update_props["Archived Summary"] = {
                                "rich_text": [{"type": "text", "text": {"content": entry.get("One-Line Summary", "")[:200]}}]
                            }
                        update_page(entry["id"], update_props)
                        entries_decayed += 1
                        time.sleep(0.35)
                    except Exception as e:
                        logger.error(f"Failed to apply decay: {e}")
                        summary["errors"].append(f"Decay update failed for {entry.get('Title', 'unknown')}: {e}")
                break

    summary["entries_decayed"] = entries_decayed

    logger.info(
        f"Daily brief complete: {summary['entries_scored']} entries scored, "
        f"{summary['entries_decayed']} decayed, {summary['synthesis_records']} syntheses"
    )

    return summary


if __name__ == "__main__":
    print("Running Stage 3: Daily Brief Generation...")
    print("This reads Main KB, calls GPT-4o, writes to Notion.")
    print("Cost: ~$0.10-0.15 for OpenAI call.\n")

    summary = run_daily_brief()

    print(f"\n{'='*60}")
    print(f"DAILY BRIEF SUMMARY")
    print(f"{'='*60}")
    print(f"Active entries:      {summary['active_entries']}")
    print(f"Brief generated:     {summary['brief_generated']}")
    print(f"Brief page ID:       {summary.get('brief_page_id', 'N/A')}")
    print(f"Synthesis records:   {summary['synthesis_records']}")
    print(f"Entries scored:      {summary['entries_scored']}")
    print(f"Entries decayed:     {summary['entries_decayed']}")
    print(f"Entries marked seen: {summary['entries_marked_seen']}")
    if summary['errors']:
        print(f"Errors:")
        for e in summary['errors']:
            print(f"  - {e}")
    print(f"{'='*60}")
    print(f"\nCheck Notion → Brief Log for the generated brief page.")
    print(f"Check Notion → Synthesis Database for any synthesis records.")
