# CHUNK 13: Full Search Cycle — Wire Ingestion + Reconciliation + Escalation

## Objective
Wire `ingestion.py` (Chunk 9) and `reconciliation.py` (Chunk 11, which now includes escalation from Chunk 12) into a single `run_search_cycle()` function. This is the function the scheduler (Chunk 16) will call 4 times a day. One button press = one complete cycle: search → dedupe → write to queue → analyze → reconcile → escalate → clear queue.

## Dependencies
- Chunk 9: `ingestion.run_ingestion()`
- Chunk 11: `reconciliation.run_reconciliation()`
- Chunk 12: escalation integrated into reconciliation

## What this chunk adds
- Updates `main.py` — adds `run_search_cycle()` function and manual trigger capability

---

## DESIGN

### Why a wrapper function?

Ingestion and reconciliation are currently separate scripts you run manually. In production, they run back-to-back as a single unit — you never want to ingest without reconciling. The wrapper:

1. Runs ingestion (Stage 1)
2. Immediately runs reconciliation (Stage 2, which includes escalation)
3. Logs the combined summary
4. Handles errors — if ingestion fails, don't run reconciliation. If reconciliation fails, the queue entries are preserved for next cycle.

### What the scheduler calls

The scheduler (Chunk 16) will call:
```python
run_search_cycle(cycle_number=1)  # at 6:30 AM IST
run_search_cycle(cycle_number=2)  # at 11:30 AM IST
run_search_cycle(cycle_number=3)  # at 5:30 PM IST
run_search_cycle(cycle_number=4)  # at 10:30 PM IST
```

For now, it's triggered manually from the command line.

---

## IMPLEMENTATION SPEC

### Update `main.py`

Add these to `main.py` (keep existing code — add new functions and update the `__main__` block):

#### `run_search_cycle(cycle_number: int) -> dict`

```python
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
    
    Does NOT raise exceptions. Catches all errors and returns them
    in the summary. The scheduler should never crash because of a
    failed cycle — it logs the failure and waits for the next cycle.
    """
```

Implementation:

```python
from ingestion import run_ingestion
from reconciliation import run_reconciliation

def run_search_cycle(cycle_number: int) -> dict:
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
        logger.info(f"Stage 1 complete: {ingestion_summary['new_entries']} new entries ingested")
    except Exception as e:
        logger.error(f"Stage 1 (Ingestion) failed: {e}")
        result["error"] = f"Ingestion failed: {e}"
        logger.info(f"Skipping Stage 2 — nothing to reconcile")
        return result
    
    # If no new entries were ingested, still run reconciliation
    # (there might be leftover entries in the queue from a previous failed cycle)
    
    # Stage 2: Reconciliation (includes escalation)
    try:
        recon_summary = run_reconciliation()
        result["reconciliation"] = recon_summary
        logger.info(f"Stage 2 complete: {recon_summary['new_entries']} new, "
                    f"{recon_summary['updated_entries']} updated in Main KB")
    except Exception as e:
        logger.error(f"Stage 2 (Reconciliation) failed: {e}")
        result["error"] = f"Reconciliation failed: {e}"
        # Ingestion succeeded, so entries are in the queue
        # They'll be processed in the next cycle
        logger.info(f"Queue entries preserved for next cycle")
        return result
    
    result["success"] = True
    
    # Print combined summary
    logger.info(f"{'='*60}")
    logger.info(f"SEARCH CYCLE {cycle_number} COMPLETE")
    logger.info(f"{'='*60}")
    
    return result
```

#### Update `main()` and `__main__` block

Replace the existing `main()` function and `__main__` block:

```python
import sys

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
        logger.warning("No database IDs found. Run setup_notion.py first.")
        return
    
    logger.info(f"Database IDs loaded: {list(db_ids.keys())}")
    
    # Check for command-line cycle trigger
    if len(sys.argv) > 1:
        try:
            cycle = int(sys.argv[1])
            if cycle not in (1, 2, 3, 4):
                logger.error(f"Invalid cycle number: {cycle}. Must be 1, 2, 3, or 4.")
                return
            
            summary = run_search_cycle(cycle)
            _print_cycle_summary(summary)
        except ValueError:
            logger.error(f"Invalid argument: {sys.argv[1]}. Pass a cycle number (1-4).")
        return
    
    # No arguments — show status
    logger.info("Pipeline is ready.")
    logger.info("Usage:")
    logger.info("  python main.py 1        Run search cycle 1 manually")
    logger.info("  python main.py 2        Run search cycle 2 manually")
    logger.info("  python main.py 3        Run search cycle 3 manually")
    logger.info("  python main.py 4        Run search cycle 4 manually")
    logger.info("Scheduler will be added in a future chunk.")
    logger.info("=== Listening Pipeline Stopped ===")


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
        print(f"  New in queue:      {ing.get('new_entries', 'N/A')}")
    
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


if __name__ == "__main__":
    main()
```

---

## WHAT THIS CHUNK DOES NOT DO

- Does NOT add the scheduler (that's Chunk 16)
- Does NOT add the daily brief (that's Chunks 14–15)
- Does NOT create any new files — only updates `main.py`

---

## TEST BLOCK

The test is `main.py` itself. Running `python main.py 1` triggers a full cycle.

---

## EDGE CASES

### Ingestion fails
Reconciliation is skipped. Queue entries from previous cycles (if any) are preserved. Error is logged and returned in summary. Pipeline doesn't crash.

### Reconciliation fails
Ingestion succeeded, so new entries are in the queue. They'll be processed when reconciliation runs next (either next cycle or manual retry). Error logged.

### Both stages succeed but zero new entries
This is normal — dedup filtered everything because the database is already up to date. `success: True` with zeros across the board.

### Invalid cycle number
Prints error, exits. No API calls.

### No command-line arguments
Prints usage instructions. No API calls.

### Running during a previous cycle
No locking mechanism. If two cycles overlap (shouldn't happen with 5-hour gaps), they'll both read the same queue and potentially create duplicates. The scheduler (Chunk 16) will add a lock to prevent this. For now, don't run two cycles simultaneously.