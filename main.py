"""
Listening Pipeline — Entry Point
Run this file to start the pipeline.
"""

import sys

from config import validate_config, load_database_ids
from logger import setup_logger
from ingestion import run_ingestion
from reconciliation import run_reconciliation

logger = setup_logger()


def run_search_cycle(cycle_number: int) -> dict:
    """
    Execute one complete search cycle: ingestion + reconciliation.

    This is the primary function called by the scheduler.

    Args:
        cycle_number: Which cycle (1, 2, 3, or 4).

    Returns:
        Dict with combined summary:
        {
            "cycle": int,
            "ingestion": dict,      # summary from run_ingestion()
            "reconciliation": dict,  # summary from run_reconciliation()
            "success": bool,         # True if both stages completed
            "error": str | None,     # error message if failed
        }
    """
    result = {
        "cycle": cycle_number,
        "ingestion": None,
        "reconciliation": None,
        "success": False,
        "error": None,
    }

    logger.info(f"{'='*60}")
    logger.info(f"SEARCH CYCLE {cycle_number} STARTING")
    logger.info(f"{'='*60}")

    # Stage 1: Ingestion
    try:
        ingestion_summary = run_ingestion(cycle_number)
        result["ingestion"] = ingestion_summary
        logger.info(
            f"Stage 1 complete: {ingestion_summary['new_entries']} new entries ingested"
        )
    except Exception as e:
        logger.error(f"Stage 1 (Ingestion) failed: {e}")
        result["error"] = f"Ingestion failed: {e}"
        logger.info(f"Skipping Stage 2 — nothing to reconcile")
        return result

    # Stage 2: Reconciliation (includes escalation)
    try:
        recon_summary = run_reconciliation()
        result["reconciliation"] = recon_summary
        logger.info(
            f"Stage 2 complete: {recon_summary['new_entries']} new, "
            f"{recon_summary['updated_entries']} updated in Main KB"
        )
    except Exception as e:
        logger.error(f"Stage 2 (Reconciliation) failed: {e}")
        result["error"] = f"Reconciliation failed: {e}"
        logger.info(f"Queue entries preserved for next cycle")
        return result

    result["success"] = True

    logger.info(f"{'='*60}")
    logger.info(f"SEARCH CYCLE {cycle_number} COMPLETE")
    logger.info(f"{'='*60}")

    return result


def _print_cycle_summary(summary: dict):
    """Print a formatted summary of a completed cycle."""
    print(f"\n{'='*60}")
    print(f"CYCLE {summary['cycle']} — {'SUCCESS' if summary['success'] else 'FAILED'}")
    print(f"{'='*60}")

    if summary["ingestion"]:
        ing = summary["ingestion"]
        print(f"\nStage 1 (Ingestion):")
        print(f"  Pass A results:    {ing.get('pass_a_results', 'N/A')}")
        print(f"  Pass B results:    {ing.get('pass_b_results', 'N/A')}")
        print(f"  After dedup:       {ing.get('after_cross_dedup', 'N/A')}")
        print(f"  DB duplicates:     {ing.get('duplicates_db', 'N/A')}")
        print(f"  New in queue:     {ing.get('new_entries', 'N/A')}")

    if summary["reconciliation"]:
        rec = summary["reconciliation"]
        print(f"\nStage 2 (Reconciliation):")
        print(f"  Queue processed:   {rec.get('queue_entries', 'N/A')}")
        print(f"  Analyzed:          {rec.get('analyzed', 'N/A')}")
        print(f"  New in Main KB:    {rec.get('new_entries', 'N/A')}")
        print(f"  Updated in KB:     {rec.get('updated_entries', 'N/A')}")
        print(f"  Queue cleared:     {rec.get('archived_from_queue', 'N/A')}")

    if summary["error"]:
        print(f"\nError: {summary['error']}")

    print(f"{'='*60}")


def _print_brief_summary(summary: dict):
    """Print a formatted summary of a daily brief run."""
    print(f"\n{'='*60}")
    print(f"DAILY BRIEF — {'GENERATED' if summary['brief_generated'] else 'FAILED'}")
    print(f"{'='*60}")
    print(f"Active entries:      {summary['active_entries']}")
    print(f"Brief page ID:       {summary.get('brief_page_id', 'N/A')}")
    print(f"Synthesis records:   {summary['synthesis_records']}")
    print(f"Entries scored:      {summary['entries_scored']}")
    print(f"Entries decayed:     {summary['entries_decayed']}")
    print(f"Entries marked seen: {summary['entries_marked_seen']}")
    if summary['errors']:
        print(f"Errors:              {len(summary['errors'])}")
        for e in summary['errors']:
            print(f"  - {e}")
    print(f"{'='*60}")


def main():
    logger.info("=== Listening Pipeline Starting ===")

    # Validate config
    errors = validate_config()
    if errors:
        for error in errors:
            logger.error(f"Config error: {error}")
        logger.error("Fix the above errors in .env and try again.")
        return

    logger.info("Config validated — all API keys present.")

    # Check databases
    db_ids = load_database_ids()
    if not db_ids:
        logger.warning(
            "No database IDs found. Run setup_notion.py first."
        )
        return

    logger.info(f"Database IDs loaded: {list(db_ids.keys())}")

    # Check for command-line cycle trigger
    if len(sys.argv) > 1:
        arg = sys.argv[1]

        if arg == "start":
            from health import check_health, print_health_report
            health = check_health()
            print_health_report(health)
            if not health["healthy"]:
                logger.error("Cannot start scheduler — fix the above issues first.")
                return
            from scheduler import start_scheduler
            start_scheduler()
            return

        if arg == "health":
            from health import check_health, print_health_report
            health = check_health()
            print_health_report(health)
            return

        if arg == "brief":
            from curation import run_daily_brief
            summary = run_daily_brief()
            _print_brief_summary(summary)
            return

        if arg == "extract":
            from extract import run_extract_poll
            summary = run_extract_poll()
            print(f"\nExtract: {summary['extracted']} extracted, "
                  f"{summary['failed']} failed out of "
                  f"{summary['checked_entries']} checked entries")
            return

        if arg == "extract-watch":
            from extract import run_extract_continuous
            run_extract_continuous()
            return

        if arg == "counts":
            from notion_client import count_database
            db_ids = load_database_ids()
            print(f"\n{'='*60}")
            print("DATABASE COUNTS")
            print(f"{'='*60}")
            for name, db_id in db_ids.items():
                try:
                    count = count_database(db_id)
                    print(f"  {name}: {count}")
                except Exception as e:
                    print(f"  {name}: error — {e}")
            print(f"{'='*60}")
            return

        if arg == "test-scheduler":
            import signal
            from datetime import datetime, timedelta
            from apscheduler.schedulers.blocking import BlockingScheduler
            from apscheduler.triggers.date import DateTrigger

            test_logger = setup_logger("test_scheduler")
            test_logger.info("=== Scheduler Test Starting ===")

            scheduler = BlockingScheduler()

            fire_time = datetime.now() + timedelta(minutes=1)
            test_logger.info(f"Test job will fire at ~{fire_time.strftime('%H:%M:%S')}")

            def test_job():
                test_logger.info("TEST JOB FIRED")
                scheduler.shutdown(wait=False)

            scheduler.add_job(
                func=test_job,
                trigger=DateTrigger(fire_time),
                id="test_job",
                name="Test Job",
            )

            def shutdown(signum, frame):
                test_logger.info("Shutting down test scheduler...")
                scheduler.shutdown(wait=False)
                sys.exit(0)

            signal.signal(signal.SIGINT, shutdown)
            signal.signal(signal.SIGTERM, shutdown)

            print(f"Scheduler test — job fires at {fire_time.strftime('%H:%M:%S')} (1 min)")
            print("Waiting... Press Ctrl+C to cancel.")
            scheduler.start()
            print("Scheduler test complete.")
            return

        try:
            cycle = int(arg)
            if cycle not in (1, 2, 3, 4):
                logger.error(f"Invalid cycle number: {cycle}. Must be 1, 2, 3, or 4.")
                return

            summary = run_search_cycle(cycle)
            _print_cycle_summary(summary)
        except ValueError:
            logger.error(f"Invalid argument: {sys.argv[1]}. Pass a cycle number (1-4), 'brief', 'extract', 'health', or 'start'.")
        return

    # No arguments — show status
    logger.info("Pipeline is ready.")
    logger.info("Usage:")
    logger.info("  python main.py 1        Run search cycle 1 manually")
    logger.info("  python main.py 2        Run search cycle 2 manually")
    logger.info("  python main.py 3        Run search cycle 3 manually")
    logger.info("  python main.py 4        Run search cycle 4 manually")
    logger.info("  python main.py brief    Run daily brief generation")
    logger.info("  python main.py extract      Extract full content for checked entries")
    logger.info("  python main.py extract-watch  Continuously poll for extract requests")
    logger.info("  python main.py health     Check all service connections")
    logger.info("  python main.py start    Start the automated scheduler")
    logger.info("=== Listening Pipeline Stopped ===")


if __name__ == "__main__":
    main()
