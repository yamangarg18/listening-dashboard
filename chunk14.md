# CHUNK 14: OpenAI Brief Prompt — Stage 3 Daily Brief Generation

## Objective
Add `generate_daily_brief()` to `openai_client.py` — a function that sends the full Main KB active entries + priorities document to GPT-5.4 (standard, not mini) and gets back a structured daily brief with executive summary, synthesis insights, priority-ranked entries, decay decisions, and archive notices.

## Dependencies
- Chunk 10: `openai_client.py` exists with `analyze_articles()` and helpers
- Chunk 5: `notion_client.read_page_content()` for reading priorities doc

## What this chunk adds to openai_client.py
- `generate_daily_brief()` — public function
- `_build_brief_prompt()` — private helper

---

## DESIGN

### Stage 3 vs Stage 2

| | Stage 2 (Chunk 10) | Stage 3 (this chunk) |
|---|---|---|
| Model | GPT-5.4 mini | GPT-5.4 (standard) |
| Purpose | Analyze individual articles | Synthesize across all entries, generate brief |
| Input | 10 articles at a time | ALL active entries + priorities doc |
| Output | Per-article analysis | Holistic daily brief |
| Runs | After each search cycle (4x/day) | Once daily (11 PM IST) |
| Cost | ~$0.008 per call | ~$0.05–0.15 per call (larger input) |

### Why GPT-5.4 standard (not mini)?

Synthesis — connecting dots across 100+ entries and producing strategic inferences — is the most cognitively demanding task in the pipeline. Mini is great for per-article analysis but standard produces better cross-referential reasoning and more coherent briefs.

---

## THE STAGE 3 PROMPT

### System Prompt

```
You are the chief intelligence analyst for a strategic monitoring system focused on {topic}. Your job is to produce a daily briefing from a knowledge base of entries collected throughout the day.

You will receive:
1. A list of ALL active entries in the knowledge base (each with title, URL, signal level, category, one-line summary, why it matters, entities, tags, discovered date, and other metadata)
2. A "Current Priorities" document describing the user's active workstreams and focus areas

Your daily brief must contain these sections:

## 1. Executive Summary (2–3 sentences)
The single most important takeaway from today. What should the reader know if they read nothing else?

## 2. Synthesis Insights
Look across ALL entries and identify convergence patterns — multiple independent signals from different sources, days, or regions that together point at the same strategic implication. For each synthesis:
- List the contributing entry titles
- Write the inference: what these entries TOGETHER suggest
- Explain relevance to the user's frameworks or priorities
Only include genuine patterns. If no convergence patterns exist today, say "No synthesis insights today."

## 3. High-Priority Entries
Rank the top entries by contextual relevance to the user's CURRENT PRIORITIES (not just signal level). Group by region: India, China, US/Global.
For each entry include: title, signal level, category, one-line summary, and why it's relevant to current priorities.
Include up to 15 entries. If fewer are relevant, include fewer.

## 4. Updated Entries
List any entries whose signal level, category, or assessment changed today (entries with Dedup Status = "Updated"). Briefly note what changed.
If none, say "No updates today."

## 5. Decay Recommendations
Review entries older than their half-life class threshold and recommend which should move from "Active" to "Aging" or from "Aging" to "Archived". Include the entry title and reason.

Half-life thresholds:
- Policy: Active for 30 days, Aging 30-60, Archive after 60
- Research: Active for 21 days, Aging 21-45, Archive after 45
- Funding: Active for 14 days, Aging 14-30, Archive after 30
- Partnership: Active for 14 days, Aging 14-30, Archive after 30
- Discourse: Active for 7 days, Aging 7-14, Archive after 14

If no entries need decay action, say "No decay recommendations today."

Be concise. Be specific. Reference actual entry titles. Do not invent entries that don't exist in the data.
```

### User Prompt Template

```
Today's date: {today_date}
Topic: {topic}

=== CURRENT PRIORITIES ===
{priorities_content}

=== KNOWLEDGE BASE ({entry_count} active entries) ===
{formatted_entries}
```

Where `formatted_entries` is each entry formatted as:

```
---
Title: {title}
URL: {url}
Signal: {signal_level} | Category: {category} | Confidence: {confidence_score}
Discovered: {discovered_date} | Published: {published_date}
Half-Life: {half_life_class} | Decay Status: {decay_status} | Dedup: {dedup_status}
Entities: {key_entities}
Tags: {topic_tags}
Frameworks: {framework_mapping}
Summary: {one_line_summary}
Why It Matters: {why_it_matters}
---
```

### Expected Output Schema

```json
{
  "type": "object",
  "properties": {
    "executive_summary": {
      "type": "string"
    },
    "synthesis_insights": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "contributing_entries": {
            "type": "array",
            "items": {"type": "string"}
          },
          "inference": {"type": "string"},
          "relevance": {"type": "string"}
        },
        "required": ["contributing_entries", "inference", "relevance"],
        "additionalProperties": false
      }
    },
    "high_priority_entries": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "title": {"type": "string"},
          "signal_level": {"type": "string"},
          "category": {"type": "string"},
          "region": {"type": "string"},
          "summary": {"type": "string"},
          "priority_reason": {"type": "string"},
          "priority_score": {"type": "integer"}
        },
        "required": ["title", "signal_level", "category", "region", "summary", "priority_reason", "priority_score"],
        "additionalProperties": false
      }
    },
    "updated_entries": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "title": {"type": "string"},
          "change_description": {"type": "string"}
        },
        "required": ["title", "change_description"],
        "additionalProperties": false
      }
    },
    "decay_recommendations": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "title": {"type": "string"},
          "current_status": {"type": "string"},
          "recommended_status": {"type": "string"},
          "reason": {"type": "string"}
        },
        "required": ["title", "current_status", "recommended_status", "reason"],
        "additionalProperties": false
      }
    }
  },
  "required": ["executive_summary", "synthesis_insights", "high_priority_entries", "updated_entries", "decay_recommendations"],
  "additionalProperties": false
}
```

---

## IMPLEMENTATION SPEC

### Add to `openai_client.py`:

#### `generate_daily_brief(entries: list[dict], priorities_content: str, topic: str) -> dict`

```python
def generate_daily_brief(
    entries: list[dict],
    priorities_content: str,
    topic: str,
) -> dict:
    """
    Generate a daily brief from the knowledge base entries and priorities.
    
    Uses GPT-5.4 (standard) for higher-quality synthesis and reasoning.
    
    Args:
        entries: List of parsed Main KB entries (from parse_page_properties).
                 Each dict has: Title, URL, Signal Level, Category, 
                 One-Line Summary, Why It Matters, Key Entities, Topic Tags,
                 Framework Mapping, Confidence Score, Discovered Date,
                 Published Date, Half-Life Class, Decay Status, Dedup Status
        priorities_content: Plain text content of the Current Priorities 
                          Notion page (from read_page_content).
        topic: The monitoring topic.
    
    Returns:
        Dict with brief sections:
        {
            "executive_summary": str,
            "synthesis_insights": [
                {
                    "contributing_entries": [str, ...],
                    "inference": str,
                    "relevance": str,
                }
            ],
            "high_priority_entries": [
                {
                    "title": str,
                    "signal_level": str,
                    "category": str,
                    "region": str,
                    "summary": str,
                    "priority_reason": str,
                    "priority_score": int,
                }
            ],
            "updated_entries": [
                {
                    "title": str,
                    "change_description": str,
                }
            ],
            "decay_recommendations": [
                {
                    "title": str,
                    "current_status": str,
                    "recommended_status": str,
                    "reason": str,
                }
            ],
        }
    
    Raises:
        Exception: If the API call fails or returns invalid JSON.
    """
```

Implementation requirements:
- Build the system prompt (hardcoded, with `{topic}` interpolated)
- Build the user prompt via `_build_brief_prompt()`
- Send to `client.chat.completions.create()` with:
  - `model="gpt-5.4"` (standard, NOT mini)
  - `response_format` with the JSON schema defined above
  - `temperature=0.3`
  - `max_tokens=8000` (briefs can be long)
  - `reasoning_effort="medium"` (balance between quality and speed)
- Check `finish_reason` — warn if truncated
- Parse JSON response
- Log: model, tokens used, number of synthesis insights, number of high-priority entries
- Return the parsed dict
- Use tenacity retry for rate limit and timeout errors

#### `_build_brief_prompt(entries: list[dict], priorities_content: str, topic: str) -> str`

```python
def _build_brief_prompt(
    entries: list[dict],
    priorities_content: str,
    topic: str,
) -> str:
    """
    Build the user prompt for daily brief generation.
    
    Formats all entries and the priorities doc into a structured prompt.
    """
```

Implementation:
- Start with today's date and topic
- Add the priorities content
- Format each entry using the template shown in the prompt section above
- Handle missing fields gracefully (use "N/A" or "Unknown" for None values)
- For list fields (Key Entities, Topic Tags, Framework Mapping), join with ", "
- Return the full prompt string

---

## TOKEN MANAGEMENT

With 160+ entries, the prompt can be very large. Each entry is ~200 tokens formatted. 160 entries = ~32,000 input tokens. GPT-5.4 has a large context window so this fits, but costs more.

**Optimization:** Only include entries with `Decay Status = "Active"` in the prompt. Aging and Archived entries don't need to be in the daily brief input — they've already been seen. The calling code (Chunk 15) handles this filtering before calling `generate_daily_brief()`.

**Cost estimate at 160 entries:**
- Input: ~35,000 tokens × $2.50/1M = ~$0.09
- Output: ~3,000 tokens × $15/1M = ~$0.045
- Total: ~$0.13 per brief
- Daily cost: ~$0.13/day = ~$4/month

---

## TEST BLOCK

Replace the existing `if __name__ == "__main__":` block in `openai_client.py`:

```python
if __name__ == "__main__":
    from config import TOPIC, PRIORITIES_PAGE_ID
    from notion_client import query_database, parse_page_properties, read_page_content
    from config import get_database_id
    
    # --- Test 1: Build brief prompt ---
    print("Test 1: Building brief prompt from real data...")
    
    main_kb_id = get_database_id("main_kb")
    pages = query_database(
        main_kb_id,
        filter={"property": "Decay Status", "select": {"equals": "Active"}},
    )
    entries = [parse_page_properties(p) for p in pages]
    print(f"  Active entries in Main KB: {len(entries)}")
    
    priorities = ""
    if PRIORITIES_PAGE_ID:
        priorities = read_page_content(PRIORITIES_PAGE_ID)
        print(f"  Priorities doc: {len(priorities)} chars")
    else:
        print("  WARNING: PRIORITIES_PAGE_ID not set — using empty priorities")
    
    prompt = _build_brief_prompt(entries, priorities, TOPIC)
    print(f"  Brief prompt: {len(prompt)} chars (~{len(prompt)//4} tokens)")
    
    # --- Test 2: Generate daily brief (real API call) ---
    print(f"\nTest 2: Generating daily brief with GPT-5.4...")
    print(f"  (This calls GPT-5.4 standard — costs ~$0.10-0.15)")
    print(f"  (May take 30-60 seconds)")
    
    brief = generate_daily_brief(entries, priorities, TOPIC)
    
    print(f"\n{'='*60}")
    print(f"DAILY BRIEF — {TOPIC}")
    print(f"{'='*60}")
    
    print(f"\n## Executive Summary")
    print(brief["executive_summary"])
    
    print(f"\n## Synthesis Insights ({len(brief['synthesis_insights'])} found)")
    for i, s in enumerate(brief["synthesis_insights"], 1):
        print(f"\n  Insight {i}:")
        print(f"    Entries: {', '.join(s['contributing_entries'][:3])}{'...' if len(s['contributing_entries']) > 3 else ''}")
        print(f"    Inference: {s['inference'][:150]}...")
        print(f"    Relevance: {s['relevance'][:100]}...")
    
    print(f"\n## High-Priority Entries ({len(brief['high_priority_entries'])} entries)")
    for e in brief["high_priority_entries"][:5]:
        print(f"  [{e['signal_level']}] [{e['region']}] {e['title'][:60]}")
        print(f"    Score: {e['priority_score']} | {e['category']}")
        print(f"    Why: {e['priority_reason'][:80]}...")
    if len(brief["high_priority_entries"]) > 5:
        print(f"  ... and {len(brief['high_priority_entries']) - 5} more")
    
    print(f"\n## Updated Entries ({len(brief['updated_entries'])})")
    if brief["updated_entries"]:
        for u in brief["updated_entries"]:
            print(f"  - {u['title'][:50]}: {u['change_description'][:60]}")
    else:
        print("  No updates today.")
    
    print(f"\n## Decay Recommendations ({len(brief['decay_recommendations'])})")
    if brief["decay_recommendations"]:
        for d in brief["decay_recommendations"]:
            print(f"  - {d['title'][:50]}: {d['current_status']} → {d['recommended_status']}")
    else:
        print("  No decay recommendations today.")
    
    print(f"\n{'='*60}")
    print("Daily brief generation: COMPLETE")
```

---

## EDGE CASES

### Empty entries list
If Main KB has no active entries, the brief should still generate with "No entries to analyze" in the executive summary and empty arrays for all sections. Don't crash.

### No priorities document
If `PRIORITIES_PAGE_ID` is not set or the page is empty, use a default message: "No current priorities specified. Rank entries by general strategic importance." The brief still generates — priorities influence ranking but aren't required.

### Very large knowledge base (500+ entries)
The prompt gets very long. GPT-5.4 can handle it (large context window) but costs increase. If this becomes an issue, filter to only the last 14 days of active entries.

### Model returns fewer high_priority_entries than exist
The prompt says "up to 15." The model may return fewer if it judges fewer are relevant. This is correct behavior.

### Synthesis insights are empty
Valid — not every day has convergence patterns. The model should return an empty array, not hallucinate patterns.

### Decay recommendations reference entries not in the input
The system prompt says "do not invent entries that don't exist in the data." But the model might still hallucinate an entry title. The calling code (Chunk 15) should verify that recommended entries actually exist before applying decay changes.

### finish_reason = "length"
Output was truncated. The JSON may be invalid. Retry with higher `max_tokens` (12000). If still truncating, reduce input size (fewer entries or shorter formatting).