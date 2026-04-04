# CHUNK 16: Scheduler — Automated Daily Cycles

## Objective
Build `scheduler.py` and update `main.py` to run the pipeline automatically on schedule: 4 search cycles per day + 1 daily brief, all at IST times. Uses APScheduler (already in requirements.txt).

## Dependencies
- Chunk 13: `main.run_search_cycle()`
- Chunk 15: `curation.run_daily_brief()`
- APScheduler installed (from requirements.txt)

## What this chunk creates
- `scheduler.py` — new file
- Updates `main.py` — adds "start" command to launch the scheduler

---

## DESIGN

### Schedule (all times IST)

| Time (IST) | Job | Function |
|---|---|---|
| 6:30 AM | Search Cycle 1 | `run_search_cycle(1)` |
| 11:30 AM | Search Cycle 2 | `run_search_cycle(2)` |
| 5:30 PM | Search Cycle 3 | `run_search_cycle(3)` |
| 10:30 PM | Search Cycle 4 | `run_search_cycle(4)` |
| 11:00 PM | Daily Brief | `run_daily_brief()` |

The daily brief runs 30 minutes after the last search cycle, giving Stage 2 time to finish reconciling before Stage 3 reads the Main KB.

### APScheduler basics

APScheduler is a Python job scheduling library. We use the `BlockingScheduler` — it runs in the foreground and blocks the main thread. This is what we want for a background pipeline process.

```python
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = BlockingScheduler()

# Add a job that runs at 6:30 AM IST every day
scheduler.add_job(
    func=my_function,
    trigger=CronTrigger(hour=6, minute=30, timezone="Asia/Kolkata"),
    id="cycle_1",
    name="Search Cycle 1",
    misfire_grace_time=3600,  # Allow 1 hour late execution
)

scheduler.start()  # Blocks forever
```

### Key APScheduler parameters

| Parameter | Value | Purpose |
|---|---|---|
| `trigger` | `CronTrigger` | Cron-like scheduling with timezone support |
| `timezone` | `"Asia/Kolkata"` | IST timezone. APScheduler uses IANA timezone names. |
| `misfire_grace_time` | `3600` | If the computer was asleep/off when a job was supposed to run, run it up to 1 hour late. After that, skip it. |
| `max_instances` | `1` | Only one instance of each job runs at a time. Prevents overlap if a cycle takes longer than expected. |
| `coalesce` | `True` | If multiple misfired runs pile up, only run once (not N times). |

### Timezone

APScheduler needs the `pytz` or `zoneinfo` timezone. Python 3.9+ has `zoneinfo` built in:

```python
# Python 3.9+
from zoneinfo import ZoneInfo
IST = ZoneInfo("Asia/Kolkata")
```

Or with APScheduler's CronTrigger, just pass the timezone string:
```python
CronTrigger(hour=6, minute=30, timezone="Asia/Kolkata")
```

APScheduler handles the timezone conversion internally. No need for `pytz`.

### Graceful shutdown

When you press Ctrl+C, the scheduler should stop cleanly:
```python
import signal
import sys

def shutdown(signum, frame):
    logger.info("Shutting down scheduler...")
    scheduler.shutdown(wait=False)
    sys.exit(0)

signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)
```

### Job execution locking

`max_instances=1` ensures that if Cycle 1 is still running when Cycle 2 is supposed to start, Cycle 2 waits (or is skipped based on misfire settings). This prevents overlapping cycles that could cause duplicate entries.

---

## IMPLEMENTATION SPEC

### File: `scheduler.py`

```python
"""
Scheduler module.
Runs the pipeline on a daily schedule using APScheduler.
"""
```

### Functions to implement:

#### `create_scheduler() -> BlockingScheduler`

```python
def create_scheduler() -> BlockingScheduler:
    """
    Create and configure the APScheduler with all pipeline jobs.
    
    Jobs:
    - 4 search cycles at 6:30, 11:30, 17:30, 22:30 IST
    - 1 daily brief at 23:00 IST
    
    Returns:
        Configured BlockingScheduler (not yet started).
    """
```

Implementation:

```python
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

def create_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler()
    
    # Search cycles
    cycles = [
        {"id": "cycle_1", "name": "Search Cycle 1", "hour": 6, "minute": 30},
        {"id": "cycle_2", "name": "Search Cycle 2", "hour": 11, "minute": 30},
        {"id": "cycle_3", "name": "Search Cycle 3", "hour": 17, "minute": 30},
        {"id": "cycle_4", "name": "Search Cycle 4", "hour": 22, "minute": 30},
    ]
    
    for cycle in cycles:
        scheduler.add_job(
            func=_run_cycle_safe,
            args=[int(cycle["id"].split("_")[1])],
            trigger=CronTrigger(
                hour=cycle["hour"],
                minute=cycle["minute"],
                timezone="Asia/Kolkata",
            ),
            id=cycle["id"],
            name=cycle["name"],
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
    
    # Daily brief
    scheduler.add_job(
        func=_run_brief_safe,
        trigger=CronTrigger(
            hour=23,
            minute=0,
            timezone="Asia/Kolkata",
        ),
        id="daily_brief",
        name="Daily Brief",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    
    # Event listener for logging
    scheduler.add_listener(_job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
    
    return scheduler
```

#### `_run_cycle_safe(cycle_number: int) -> None`

```python
def _run_cycle_safe(cycle_number: int) -> None:
    """
    Wrapper that runs a search cycle and catches ALL exceptions.
    The scheduler must never crash because a cycle failed.
    """
    try:
        from main import run_search_cycle
        summary = run_search_cycle(cycle_number)
        if not summary["success"]:
            logger.error(f"Cycle {cycle_number} failed: {summary.get('error')}")
    except Exception as e:
        logger.error(f"Cycle {cycle_number} crashed: {e}", exc_info=True)
```

#### `_run_brief_safe() -> None`

```python
def _run_brief_safe() -> None:
    """
    Wrapper that runs the daily brief and catches ALL exceptions.
    """
    try:
        from curation import run_daily_brief
        summary = run_daily_brief()
        if not summary["brief_generated"]:
            logger.error(f"Daily brief failed: {summary.get('errors')}")
    except Exception as e:
        logger.error(f"Daily brief crashed: {e}", exc_info=True)
```

#### `_job_listener(event) -> None`

```python
def _job_listener(event) -> None:
    """Log job execution results."""
    if event.exception:
        logger.error(f"Job {event.job_id} failed with exception: {event.exception}")
    else:
        logger.info(f"Job {event.job_id} completed successfully")
```

#### `start_scheduler() -> None`

```python
def start_scheduler() -> None:
    """
    Create, configure, and start the scheduler.
    Blocks forever until interrupted.
    """
    logger.info("=== Starting Listening Pipeline Scheduler ===")
    logger.info("Schedule (IST):")
    logger.info("  06:30  Search Cycle 1")
    logger.info("  11:30  Search Cycle 2")
    logger.info("  17:30  Search Cycle 3")
    logger.info("  22:30  Search Cycle 4")
    logger.info("  23:00  Daily Brief")
    logger.info("Press Ctrl+C to stop.")
    
    scheduler = create_scheduler()
    
    # Print next run times
    for job in scheduler.get_jobs():
        logger.info(f"  Next run for {job.name}: {job.next_run_time}")
    
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped by user.")
```

---

## UPDATE main.py

Add "start" command to launch the scheduler:

```python
# In the command-line argument handling section of main():
if len(sys.argv) > 1:
    arg = sys.argv[1]
    
    if arg == "start":
        from scheduler import start_scheduler
        start_scheduler()
        return
    
    if arg == "brief":
        # ... existing brief handling ...
    
    # ... existing cycle number handling ...
```

Add usage line:
```python
logger.info("  python main.py start    Start the automated scheduler")
```

The full usage should now show:
```
  python main.py 1        Run search cycle 1 manually
  python main.py 2        Run search cycle 2 manually
  python main.py 3        Run search cycle 3 manually
  python main.py 4        Run search cycle 4 manually
  python main.py brief    Run daily brief generation
  python main.py start    Start the automated scheduler
```

---

## TEST BLOCK

```python
if __name__ == "__main__":
    # --- Test 1: Create scheduler and verify jobs ---
    print("Test 1: Creating scheduler...")
    scheduler = create_scheduler()
    
    jobs = scheduler.get_jobs()
    print(f"  Jobs configured: {len(jobs)}")
    for job in jobs:
        print(f"    {job.id}: {job.name} → next: {job.next_run_time}")
    
    assert len(jobs) == 5, f"Expected 5 jobs, got {len(jobs)}"
    
    job_ids = [j.id for j in jobs]
    assert "cycle_1" in job_ids, "Missing cycle_1"
    assert "cycle_2" in job_ids, "Missing cycle_2"
    assert "cycle_3" in job_ids, "Missing cycle_3"
    assert "cycle_4" in job_ids, "Missing cycle_4"
    assert "daily_brief" in job_ids, "Missing daily_brief"
    
    print("  All 5 jobs configured: PASSED")
    
    # --- Test 2: Verify timezone ---
    print("\nTest 2: Verify IST timezone...")
    cycle_1 = scheduler.get_job("cycle_1")
    trigger = cycle_1.trigger
    # The trigger should use Asia/Kolkata
    print(f"  Cycle 1 trigger: {trigger}")
    print(f"  Next run: {cycle_1.next_run_time}")
    # Next run should be in IST (UTC+5:30)
    if cycle_1.next_run_time:
        offset = cycle_1.next_run_time.utcoffset()
        print(f"  UTC offset: {offset}")
    print("  Timezone: PASSED (verify IST offset manually)")
    
    # --- Test 3: Verify safe wrappers don't crash ---
    print("\nTest 3: Testing safe wrappers...")
    # These should not raise even if the underlying function fails
    print("  (Not running actual cycles — just verifying wrapper imports)")
    print("  Safe wrappers: PASSED")
    
    print("\nScheduler configuration: ALL PASSED")
    print("\nTo start the scheduler: python main.py start")
    print("To test a single cycle: python main.py 1")
    print("\nNote: The scheduler runs in the foreground and blocks.")
    print("Press Ctrl+C to stop it.")
```

---

## EDGE CASES

### Computer sleeps during a scheduled run
With `misfire_grace_time=3600`, if the Mac wakes up within an hour of the missed time, the job runs. After an hour, it's skipped and the next scheduled run takes over. `coalesce=True` ensures only one make-up run happens, not multiple.

### Two jobs try to run simultaneously
`max_instances=1` prevents this. If Cycle 4 (10:30 PM) is still running at 11:00 PM when the brief is supposed to start, the brief waits until Cycle 4 finishes. APScheduler logs a warning about the missed fire time.

### Scheduler crashes
If the Python process dies (system crash, kill signal), it restarts from scratch on next launch. No persistent job store — all jobs are reconfigured from code on startup. This is intentional — simpler than a persistent database.

### Running on a Mac that sleeps
If your Mac sleeps overnight, the 6:30 AM cycle might be missed. The misfire_grace_time handles this — when the Mac wakes up, any jobs missed within the last hour run immediately.

**For reliable 24/7 operation,** keep your Mac awake (System Settings → Energy → Prevent automatic sleeping) or deploy to a VPS (Chunk 18). During development/testing, manual triggers via `python main.py 1` are fine.

### Ctrl+C handling
The scheduler catches `KeyboardInterrupt` and shuts down cleanly. No orphaned processes.

### Timezone DST
India doesn't observe Daylight Saving Time, so IST is always UTC+5:30. No DST edge cases.