# MOD 05: Recency Controls

## Objective
Add recency awareness across the pipeline. Pass B currently has no date filter and returns content from any time period. Stage 2 doesn't weight recent content higher. Stage 3 doesn't prioritize today's discoveries. Variant queries have hardcoded year strings. This mod fixes all four issues.

## Execution Order
Order: MOD 03 ✅ → MOD 07 (running) → **MOD 05** → MOD 06 → MOD 01 → MOD 02 → MOD 04

---

## What changes

| File | Change |
|---|---|
| `config.py` | Add `PASS_B_LOOKBACK_DAYS` setting |
| `.env.example` | Add `PASS_B_LOOKBACK_DAYS` |
| `ingestion.py` | Pass B gets `after_date` set to 30 days ago |
| `parallel_client.py` | Replace hardcoded year in variant queries with `datetime.now().year` |
| `openai_client.py` | Stage 2 system prompt: add recency guidance |
| `openai_client.py` | Stage 3 system prompt: add "lead with today's discoveries" |

---

## CHANGE 1: Pass B date floor

### Problem
Pass B has `after_date=None` — Parallel can return a 2-year-old blog post that's topically relevant but strategically stale. This old content enters the pipeline, gets analyzed by OpenAI (wastes tokens), and clutters the Main KB.

### Fix

#### In `config.py` — add:

```python
# How far back Pass B (relevance-ranked) searches. Default 30 days.
PASS_B_LOOKBACK_DAYS = int(os.getenv("PASS_B_LOOKBACK_DAYS", "30"))
```

#### In `.env.example` — add:

```bash
# How far back Pass B (relevance-ranked) searches. Default 30 days.
PASS_B_LOOKBACK_DAYS=30
```

#### In `ingestion.py` — update `run_ingestion()`:

Find the Pass B call. Currently something like:
```python
results_b = search_multiple(
    topic=TOPIC,
    after_date=None,
    ...
)
```

Change to:
```python
from config import PASS_B_LOOKBACK_DAYS

pass_b_date = (datetime.now(IST) - timedelta(days=PASS_B_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

results_b = search_multiple(
    topic=TOPIC,
    after_date=pass_b_date,
    max_results_per_query=10,
    num_variants=6,
)

logger.info(f"Pass B (relevance-ranked, after {pass_b_date}): {len(results_b)} results")
```

Pass B still searches broadly (6 variants, no time-window constraint from last cycle) but won't return anything older than 30 days.

---

## CHANGE 2: Dynamic year in variant queries

### Problem
`generate_variant_queries()` in `parallel_client.py` may have hardcoded `"2026"` in search keywords. When 2027 arrives, these become stale.

### Fix

In `generate_variant_queries()`, find any hardcoded year string and replace with a dynamic value:

```python
from datetime import datetime

def generate_variant_queries(topic: str, num_variants: int = 6) -> list[dict]:
    current_year = str(datetime.now().year)
    
    templates = [
        {
            "label": "core_news",
            "objective": f"Latest news and developments in {topic}",
            "search_queries": [f"{topic} news {current_year}", f"{topic} latest developments"],
        },
        {
            "label": "funding",
            "objective": f"Funding rounds and investments in {topic} and robotics companies",
            "search_queries": [f"{topic} funding round {current_year}", f"robotics startup investment {current_year}"],
        },
        # ... same pattern for all other templates
    ]
```

Search through ALL templates in the function. Replace every instance of `"2026"` with `{current_year}`. If a query doesn't have a year, leave it — not every query needs one.

---

## CHANGE 3: Stage 2 recency guidance

### Problem
The Stage 2 system prompt (used by `analyze_articles()`) doesn't mention recency. A 25-day-old article gets the same signal assessment as today's breaking news.

### Fix

Find the Stage 2 system prompt in `openai_client.py` (the one used by `analyze_articles()`). Add this paragraph to the Signal Level guidelines section:

```
Recency matters. Recent developments (published within the last 7 days) are inherently more actionable than older content. When two articles have similar strategic importance, the more recent one should receive a higher signal level. Articles older than 14 days should rarely receive "High" unless they represent a major, ongoing development.
```

Add it after the existing Signal Level guidelines (High/Medium/Low definitions), before the closing of the system prompt.

---

## CHANGE 4: Stage 3 "lead with today" guidance

### Problem
The Stage 3 system prompt (used by `generate_daily_brief()`) doesn't tell the model to prioritize today's newly discovered entries. The brief may lead with a 2-week-old entry that hasn't changed.

### Fix

Find the Stage 3 system prompt in `openai_client.py` (the one used by `generate_daily_brief()`). Add this to the Executive Summary section instructions:

```
Lead with entries discovered TODAY (matching today's date in the Discovered Date field). Today's new discoveries should dominate the executive summary and the top of the high-priority list. Previously seen entries should only appear if their significance has genuinely increased.
```

Also add to the High-Priority Entries section:

```
Sort primarily by discovery recency (today's entries first), then by relevance to current priorities. Entries discovered today should appear before older entries of similar importance.
```

---

## WHAT THIS MOD DOES NOT CHANGE

- Pass A is unchanged (still uses last-cycle timestamp)
- The number of variants is unchanged (4 for Pass A, 6 for Pass B)
- The exclude domains and quality filter (MOD 03) are unchanged
- The decay thresholds in Stage 3 are unchanged
- No new files created

---

## TEST BLOCK

No standalone test block needed. Test through the pipeline:

```bash
# Run a cycle and observe the logs
python main.py 1
```

Check that:
1. Pass B log line shows `after {date}` (should be ~30 days ago, not "no date filter")
2. No `"2026"` appears in search query logs (should show current year)
3. Stage 2 analyses weight recent articles higher (check Main KB signal levels)
4. Daily brief leads with today's entries (run `python main.py brief` after the cycle)

---

## EDGE CASES

### PASS_B_LOOKBACK_DAYS set very low (e.g., 3)
Pass B returns very few results — only content from the last 3 days. Combined with Pass A (last 5 hours), you get narrow coverage. Fine if that's what the user wants, but 30 is a good default.

### PASS_B_LOOKBACK_DAYS set very high (e.g., 365)
Effectively removes the date floor — same as the old behavior. Not recommended but not harmful.

### Year transition (December 31 → January 1)
`datetime.now().year` updates automatically. Queries on Dec 31 use "2026", queries on Jan 1 use "2027". No edge case.

### No hardcoded year found in templates
If OpenCode already made the year dynamic or the templates don't have years, this change is a no-op. No harm.

### Stage 2 prompt change affects existing entries
Only new articles analyzed AFTER this mod get the recency-weighted signal. Existing Main KB entries keep their original signal levels. This is correct — re-analyzing old entries would be wasteful.

### Stage 3 brief has no entries from today
If no new entries were discovered today (all cycles returned duplicates), the brief still generates — it just doesn't have "today's entries" to lead with. The existing logic handles this.