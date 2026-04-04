# CHUNK 18: Deployment — Docker, Health Monitoring, and Production Readiness

## Objective
Containerize the pipeline with Docker for reliable deployment. Add health monitoring so you know the pipeline is alive and running. Add a startup check that validates all services are reachable before starting the scheduler. This is the final chunk — after this, the pipeline is production-ready.

## Dependencies
- All chunks 0–17 complete
- Docker installed on your Mac (Docker Desktop: https://www.docker.com/products/docker-desktop/)

## What this chunk creates
- `Dockerfile`
- `docker-compose.yml`
- `.dockerignore`
- `health.py` — health check and service validation
- Updates `main.py` — adds "health" command

---

## DESIGN

### Why Docker?

Running `python main.py start` in a terminal works but:
- Close the terminal → pipeline stops
- Mac sleeps → jobs missed
- Crash → stays dead until you notice
- Dependencies tied to your Mac's Python

Docker fixes all of this:
- Runs in background, survives terminal closures
- Auto-restarts on crash (`restart: unless-stopped`)
- Isolated environment with locked dependencies
- Easy to move to a VPS later (just copy the files)

### What runs in the container

`python main.py start` — the scheduler with all 5 jobs.

### Files mounted into the container (not baked in)

- `.env` — secrets (API keys)
- `database_ids.json` — database IDs
- `state.json` — pipeline state (persists across restarts)
- `logs/` — log files (accessible from host)

---

## IMPLEMENTATION SPEC

### File: `Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY config.py .
COPY logger.py .
COPY main.py .
COPY setup_notion.py .
COPY notion_client.py .
COPY parallel_client.py .
COPY openai_client.py .
COPY ingestion.py .
COPY reconciliation.py .
COPY curation.py .
COPY escalation.py .
COPY dedup.py .
COPY scheduler.py .
COPY extract.py .
COPY health.py .

# Create logs directory
RUN mkdir -p /app/logs

# Default command
CMD ["python", "main.py", "start"]
```

**Why individual COPY instead of `COPY *.py .`?**
Docker's COPY with wildcards can behave unexpectedly. Explicit copies are safer and make the Dockerfile self-documenting — you see exactly what goes into the container.

### File: `.dockerignore`

```
venv/
__pycache__/
*.pyc
.env
.env.example
.git/
.gitignore
*.log
*.md
database_ids.json
state.json
logs/
CHUNK_*
TEST_*
OPENCODE.md
```

### File: `docker-compose.yml`

```yaml
version: "3.8"

services:
  pipeline:
    build: .
    container_name: listening-pipeline
    restart: unless-stopped
    env_file:
      - .env
    volumes:
      - ./database_ids.json:/app/database_ids.json
      - ./state.json:/app/state.json
      - ./logs:/app/logs
    environment:
      - TZ=Asia/Kolkata
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

**Key points:**
- `restart: unless-stopped` — restarts on crash but not on manual `docker compose stop`
- `env_file: .env` — injects API keys as environment variables
- Volumes mount `database_ids.json`, `state.json`, and `logs/` so they persist across container restarts
- `TZ=Asia/Kolkata` — sets container timezone to IST
- Log rotation: max 10MB per file, keep 3 files

### File: `health.py`

```python
"""
Health check and service validation module.
Verifies all external services are reachable before starting the pipeline.
"""
```

### Functions to implement:

#### `check_health() -> dict`

```python
def check_health() -> dict:
    """
    Check the health of all external services the pipeline depends on.
    
    Returns:
        Dict with health status:
        {
            "healthy": bool,
            "checks": {
                "notion_api": {"status": "ok"|"error", "message": str, "latency_ms": int},
                "parallel_api": {"status": "ok"|"error", "message": str, "latency_ms": int},
                "openai_api": {"status": "ok"|"error", "message": str, "latency_ms": int},
                "notion_databases": {"status": "ok"|"error", "message": str},
                "state_file": {"status": "ok"|"error", "message": str},
                "priorities_page": {"status": "ok"|"error", "message": str},
            }
        }
    """
```

Implementation:

**Check 1: Notion API reachable**
```python
import time
import httpx
from config import NOTION_API_KEY, NOTION_API_VERSION, NOTION_BASE_URL

start = time.time()
try:
    client = httpx.Client(
        base_url=NOTION_BASE_URL,
        headers={
            "Authorization": f"Bearer {NOTION_API_KEY}",
            "Notion-Version": NOTION_API_VERSION,
        },
        timeout=10.0,
    )
    response = client.get("/users/me")
    latency = int((time.time() - start) * 1000)
    if response.status_code == 200:
        result = {"status": "ok", "message": "Connected", "latency_ms": latency}
    else:
        result = {"status": "error", "message": f"Status {response.status_code}", "latency_ms": latency}
except Exception as e:
    result = {"status": "error", "message": str(e), "latency_ms": 0}
```

The `/users/me` endpoint returns the bot user info — lightweight, good for health checks.

**Check 2: Parallel API reachable**
```python
# Simple search with minimal results to verify API key works
start = time.time()
try:
    from parallel_client import search
    results = search(
        objective="test",
        max_results=1,
    )
    latency = int((time.time() - start) * 1000)
    result = {"status": "ok", "message": f"Connected ({len(results)} results)", "latency_ms": latency}
except Exception as e:
    latency = int((time.time() - start) * 1000)
    result = {"status": "error", "message": str(e), "latency_ms": latency}
```

**Check 3: OpenAI API reachable**
```python
start = time.time()
try:
    from openai import OpenAI
    client = OpenAI()
    # Minimal call to verify API key
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "ping"}],
        max_tokens=5,
    )
    latency = int((time.time() - start) * 1000)
    result = {"status": "ok", "message": "Connected", "latency_ms": latency}
except Exception as e:
    latency = int((time.time() - start) * 1000)
    result = {"status": "error", "message": str(e), "latency_ms": latency}
```

**Check 4: Notion databases accessible**
```python
from config import load_database_ids
from notion_client import query_database

db_ids = load_database_ids()
if not db_ids:
    result = {"status": "error", "message": "database_ids.json not found"}
else:
    missing = []
    for name, db_id in db_ids.items():
        try:
            query_database(db_id, page_size=1)  # Just check access, don't load everything
        except Exception:
            missing.append(name)
    
    if missing:
        result = {"status": "error", "message": f"Cannot access: {missing}"}
    else:
        result = {"status": "ok", "message": f"All {len(db_ids)} databases accessible"}
```

Note: `query_database` currently doesn't accept `page_size` as a separate parameter for minimal queries. For the health check, just call `query_database(db_id)` and accept the overhead, OR add a `limit` parameter to `query_database`. The simpler approach: make a raw API call with `page_size=1` directly in the health check.

**Check 5: State file**
```python
from config import load_state
import os

if os.path.exists("state.json"):
    state = load_state()
    result = {"status": "ok", "message": f"Keys: {list(state.keys())}"}
else:
    result = {"status": "ok", "message": "Not yet created (first run)"}
```

**Check 6: Priorities page**
```python
from config import PRIORITIES_PAGE_ID
from notion_client import read_page_content

if not PRIORITIES_PAGE_ID:
    result = {"status": "error", "message": "PRIORITIES_PAGE_ID not set in .env"}
else:
    try:
        content = read_page_content(PRIORITIES_PAGE_ID)
        result = {"status": "ok", "message": f"{len(content)} chars"}
    except Exception as e:
        result = {"status": "error", "message": str(e)}
```

**Final assembly:**
- `healthy` = True only if notion_api, parallel_api, openai_api, and notion_databases are all "ok"
- priorities_page and state_file are "warnings" not failures — pipeline can run without them

#### `print_health_report(health: dict) -> None`

```python
def print_health_report(health: dict) -> None:
    """Print a formatted health report."""
    status = "HEALTHY" if health["healthy"] else "UNHEALTHY"
    print(f"\n{'='*60}")
    print(f"PIPELINE HEALTH: {status}")
    print(f"{'='*60}")
    
    for name, check in health["checks"].items():
        icon = "✅" if check["status"] == "ok" else "❌"
        latency = f" ({check['latency_ms']}ms)" if "latency_ms" in check else ""
        print(f"  {icon} {name}: {check['message']}{latency}")
    
    print(f"{'='*60}")
```

---

## UPDATE main.py

Add "health" command:

```python
if arg == "health":
    from health import check_health, print_health_report
    health = check_health()
    print_health_report(health)
    return
```

Add usage line:
```python
logger.info("  python main.py health       Check all service connections")
```

Also add a health check before starting the scheduler:

```python
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
```

This ensures the scheduler doesn't start if any critical service is unreachable.

---

## DOCKER COMMANDS REFERENCE

Include these in the test block output and docs:

```bash
# Build the container
docker compose build

# Start the pipeline in background
docker compose up -d

# View logs
docker compose logs -f

# Stop the pipeline
docker compose stop

# Restart
docker compose restart

# Check if running
docker compose ps

# Run a manual cycle inside the container
docker compose exec pipeline python main.py 1

# Run health check
docker compose exec pipeline python main.py health

# Run daily brief manually
docker compose exec pipeline python main.py brief

# Rebuild after code changes
docker compose build && docker compose up -d
```

---

## TEST BLOCK

```python
if __name__ == "__main__":
    print("Running health checks...\n")
    
    health = check_health()
    print_health_report(health)
    
    if health["healthy"]:
        print("\nAll critical services are reachable.")
        print("The pipeline is ready for deployment.")
    else:
        print("\nSome services are unreachable.")
        print("Fix the issues above before deploying.")
    
    print("\nDocker commands:")
    print("  docker compose build          Build the container")
    print("  docker compose up -d          Start in background")
    print("  docker compose logs -f        View logs")
    print("  docker compose stop           Stop the pipeline")
    print("  docker compose ps             Check status")
```

---

## EDGE CASES

### Docker not installed
The health check and all non-Docker tests work without Docker. Docker is only needed for `docker compose` commands. The pipeline runs perfectly fine with `python main.py start` in a terminal.

### state.json doesn't exist yet
The volume mount in docker-compose expects the file to exist on the host. If it doesn't, Docker creates it as a directory (not a file). **Fix:** create an empty state.json before first Docker run:
```bash
echo "{}" > state.json
```

The test procedure covers this.

### .env not found by Docker
`env_file: .env` in docker-compose looks for `.env` in the same directory as `docker-compose.yml`. Since both are in `~/PAI/`, this works. If you move `docker-compose.yml` elsewhere, update the path.

### Container timezone
`TZ=Asia/Kolkata` in docker-compose sets the container's system timezone. APScheduler uses `Asia/Kolkata` in its CronTrigger, so both are aligned. Logs show IST timestamps.

### Code changes require rebuild
After modifying any `.py` file, run `docker compose build && docker compose up -d` to rebuild and restart. The old container is replaced.

### Health check costs
The Parallel check runs a minimal search (~$0.005). The OpenAI check sends a 1-token prompt (~$0.000001). Total health check cost: ~$0.005. Negligible.

### Running without Docker
Everything still works with `python main.py start`. Docker is optional — it's a deployment convenience, not a requirement.