"""
Health check and service validation module.
Verifies all external services are reachable before starting the pipeline.
Implemented in Chunk 18.
"""

import time
import httpx

from config import (
    NOTION_API_KEY,
    NOTION_API_VERSION,
    NOTION_BASE_URL,
    PRIORITIES_PAGE_ID,
    load_database_ids,
    load_state,
)
from notion_client import query_database, read_page_content, count_database
from logger import setup_logger

logger = setup_logger("health")


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
    checks = {}

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
            checks["notion_api"] = {"status": "ok", "message": "Connected", "latency_ms": latency}
        else:
            checks["notion_api"] = {"status": "error", "message": f"Status {response.status_code}", "latency_ms": latency}
    except Exception as e:
        latency = int((time.time() - start) * 1000)
        checks["notion_api"] = {"status": "error", "message": str(e), "latency_ms": latency}

    start = time.time()
    try:
        from parallel_client import search
        results = search(objective="test", max_results=1)
        latency = int((time.time() - start) * 1000)
        checks["parallel_api"] = {"status": "ok", "message": f"Connected ({len(results)} results)", "latency_ms": latency}
    except Exception as e:
        latency = int((time.time() - start) * 1000)
        checks["parallel_api"] = {"status": "error", "message": str(e), "latency_ms": latency}

    start = time.time()
    try:
        from openai import OpenAI
        client = OpenAI()
        client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
        )
        latency = int((time.time() - start) * 1000)
        checks["openai_api"] = {"status": "ok", "message": "Connected", "latency_ms": latency}
    except Exception as e:
        latency = int((time.time() - start) * 1000)
        checks["openai_api"] = {"status": "error", "message": str(e), "latency_ms": latency}

    db_ids = load_database_ids()
    if not db_ids:
        checks["notion_databases"] = {"status": "error", "message": "database_ids.json not found"}
    else:
        client = httpx.Client(
            base_url=NOTION_BASE_URL,
            headers={
                "Authorization": f"Bearer {NOTION_API_KEY}",
                "Notion-Version": NOTION_API_VERSION,
            },
            timeout=10.0,
        )
        missing = []
        for name, db_id in db_ids.items():
            try:
                resp = client.post(
                    f"/databases/{db_id}/query",
                    json={"page_size": 1}
                )
                if resp.status_code != 200:
                    missing.append(f"{name} ({resp.status_code})")
            except Exception:
                missing.append(name)
        if missing:
            checks["notion_databases"] = {"status": "error", "message": f"Cannot access: {missing}"}
        else:
            checks["notion_databases"] = {"status": "ok", "message": f"All {len(db_ids)} databases accessible"}

    import os
    if os.path.exists("state.json"):
        try:
            state = load_state()
            checks["state_file"] = {"status": "ok", "message": f"Keys: {list(state.keys())}"}
        except Exception as e:
            checks["state_file"] = {"status": "error", "message": str(e)}
    else:
        checks["state_file"] = {"status": "ok", "message": "Not yet created (first run)"}

    if not PRIORITIES_PAGE_ID:
        checks["priorities_page"] = {"status": "error", "message": "PRIORITIES_PAGE_ID not set in .env"}
    else:
        try:
            content = read_page_content(PRIORITIES_PAGE_ID)
            checks["priorities_page"] = {"status": "ok", "message": f"{len(content)} chars"}
        except Exception as e:
            checks["priorities_page"] = {"status": "error", "message": str(e)}

    critical = ["notion_api", "parallel_api", "openai_api", "notion_databases"]
    healthy = all(checks.get(name, {}).get("status") == "ok" for name in critical)

    counts = {}
    if db_ids:
        for name, db_id in db_ids.items():
            try:
                counts[name] = count_database(db_id)
            except Exception:
                counts[name] = "error"

    return {"healthy": healthy, "checks": checks, "counts": counts}


def print_health_report(health: dict) -> None:
    """Print a formatted health report."""
    status = "HEALTHY" if health["healthy"] else "UNHEALTHY"
    print(f"\n{'='*60}")
    print(f"PIPELINE HEALTH: {status}")
    print(f"{'='*60}")

    for name, check in health["checks"].items():
        icon = "ok" if check["status"] == "ok" else "ERROR"
        latency = f" ({check['latency_ms']}ms)" if "latency_ms" in check else ""
        print(f"  [{icon}] {name}: {check['message']}{latency}")

    if health.get("counts"):
        print(f"{'─'*60}")
        print("  --- Counts ---")
        for db_name, count in health["counts"].items():
            print(f"  {db_name}: {count}")

    print(f"{'='*60}")


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
    print("  docker compose ps            Check status")
