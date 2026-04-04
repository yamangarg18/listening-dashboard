"""
OpenAI API client.
Handles structured output calls for Stage 2 (reconciliation)
and Stage 3 (curation/brief generation).
"""

import json
import time
from typing import List, Dict

import openai
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import TOPIC
from logger import setup_logger

logger = setup_logger("openai_client")

client = OpenAI()

_strategic_context_cache = None


def get_strategic_context() -> str:
    """
    Load strategic context from the Strategic Context Notion database.
    
    Queries the database for entries where 'Not Using Anymore' = False,
    groups by Category, and concatenates as:
    [Category] Name: Content
    
    Cached for the lifetime of the process.
    """
    global _strategic_context_cache
    if _strategic_context_cache is None:
        from config import STRATEGIC_CONTEXT_DB_ID
        if not STRATEGIC_CONTEXT_DB_ID:
            _strategic_context_cache = ""
            return ""

        try:
            from notion_client import query_database, parse_page_properties
            pages = query_database(
                STRATEGIC_CONTEXT_DB_ID,
                filter={
                    "property": "Not Using Anymore",
                    "checkbox": {"equals": False}
                },
            )
            entries = [parse_page_properties(p) for p in pages]

            by_category = {}
            for entry in entries:
                cat = entry.get("Category", "Uncategorized")
                name = entry.get("Name", "")
                content = entry.get("Content", "")
                if cat and name and content:
                    if cat not in by_category:
                        by_category[cat] = []
                    by_category[cat].append(f"{name}: {content}")

            parts = []
            for cat in ["Framework", "Entity", "India Context", "Noise Filter", "Signal Indicator"]:
                if cat in by_category:
                    parts.append(f"=== {cat} ===")
                    parts.extend(by_category[cat])
                    parts.append("")

            _strategic_context_cache = "\n".join(parts)
            logger.info(f"Loaded strategic context: {len(_strategic_context_cache)} chars from {len(entries)} entries")
        except Exception as e:
            logger.warning(f"Failed to load strategic context: {e}")
            _strategic_context_cache = ""

    return _strategic_context_cache


def _load_signal_examples() -> str:
    """
    Load signal calibration examples from signal_examples.json.
    Returns formatted string for the system prompt, or empty string if not available.
    """
    try:
        with open("signal_examples.json", "r") as f:
            examples = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return ""

    parts = ["\n=== SIGNAL CALIBRATION EXAMPLES ===",
             "These are real articles classified by the user. Match this calibration.\n"]

    for level in ["high", "medium", "low"]:
        items = examples.get(level, [])
        if items:
            parts.append(f"{level.upper()} SIGNAL:")
            for item in items:
                parts.append(f'- "{item["title"]}" → {level.capitalize()} because: {item["reason"]}')
            parts.append("")

    return "\n".join(parts)


SYSTEM_PROMPT = """You are an intelligence analyst for a research monitoring system focused on a specific topic. Your job is to analyze a batch of newly discovered web articles and assess each one's strategic relevance.

For each article, you must determine:
1. A one-line summary (max 1 sentence)
2. Why it matters strategically
3. Signal level (High / Medium / Low)
4. Confidence score (0.0 to 1.0)
5. Category (one of: Competitor Move, Policy Change, Research, Funding, Partnership, Discourse, Other)
6. Key entities (companies, people, technologies, countries mentioned)
7. Topic tags (sub-topics this article relates to)
8. Framework mapping (which strategic frameworks this is relevant to, from: Four Schools, GTM, Tech Stack, Taxonomy, Policy, Academic, Industry Vertical)
9. Half-life class (how quickly this information decays: Policy, Research, Funding, Partnership, Discourse)

Be precise. Be concise. Do not invent information not present in the article excerpt.
Signal Level guidelines:
- High: Major funding round, significant policy change, breakthrough research, major partnership, or something that demands immediate attention
- Medium: Noteworthy development that adds to the knowledge base but doesn't require immediate action
- Low: Tangentially relevant, minor update, or low-impact discourse

Recency matters. Recent developments (published within the last 7 days) are inherently more actionable than older content. When two articles have similar strategic importance, the more recent one should receive a higher signal level. Articles older than 14 days should rarely receive "High" unless they represent a major, ongoing development."""


RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "articles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "one_line_summary": {"type": "string"},
                    "why_it_matters": {"type": "string"},
                    "signal_level": {"type": "string", "enum": ["High", "Medium", "Low"]},
                    "confidence_score": {"type": "number"},
                    "category": {"type": "string", "enum": ["Competitor Move", "Policy Change", "Research", "Funding", "Partnership", "Discourse", "Other"]},
                    "key_entities": {"type": "array", "items": {"type": "string"}},
                    "topic_tags": {"type": "array", "items": {"type": "string"}},
                    "framework_mapping": {"type": "array", "items": {"type": "string"}},
                    "half_life_class": {"type": "string", "enum": ["Policy", "Research", "Funding", "Partnership", "Discourse"]}
                },
                "required": ["title", "one_line_summary", "why_it_matters", "signal_level", "confidence_score", "category", "key_entities", "topic_tags", "framework_mapping", "half_life_class"],
                "additionalProperties": False
            }
        }
    },
    "required": ["articles"],
    "additionalProperties": False
}


def _build_user_prompt(articles: List[Dict], topic: str) -> str:
    """Format articles into the user prompt for OpenAI."""
    lines = [f"Topic: {topic}\n"]
    lines.append(f"Analyze the following {len(articles)} articles. "
                 f"Return a JSON object with an \"articles\" array containing "
                 f"one analysis object per article, in the same order as provided.\n")
    lines.append("Articles:")
    
    for i, article in enumerate(articles, 1):
        lines.append(f"---")
        lines.append(f"Article {i}:")
        lines.append(f"Title: {article.get('title', 'Unknown')}")
        lines.append(f"URL: {article.get('url', 'Unknown')}")
        lines.append(f"Published: {article.get('publish_date') or 'Unknown'}")
        lines.append(f"Source: {article.get('source_name', 'Unknown')}")
        lines.append(f"Excerpt: {article.get('excerpt_text', 'No excerpt available')}")
    
    lines.append("---")
    return "\n".join(lines)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception_type((openai.RateLimitError, openai.APITimeoutError)),
    reraise=True,
)
def analyze_articles(articles: List[Dict], topic: str) -> List[Dict]:
    """
    Send a batch of articles to GPT-5.4 mini for analysis.
    
    Each article is analyzed for strategic relevance and tagged
    with signal level, category, entities, etc.
    
    Args:
        articles: List of article dicts, each with:
                  - "title": str
                  - "url": str
                  - "publish_date": str or None
                  - "excerpt_text": str
                  - "source_name": str (optional, extracted from URL if missing)
        topic: The monitoring topic (e.g., "Physical AI")
    
    Returns:
        List of analysis dicts, one per article, in the same order.
        Each dict has fields defined in the response schema.
    
    Raises:
        Exception: If the API call fails or returns invalid JSON.
    """
    user_prompt = _build_user_prompt(articles, topic)

    max_tokens = 8000 if len(articles) > 10 else 4000

    system_with_context = SYSTEM_PROMPT
    strategic_context = get_strategic_context()
    if strategic_context:
        system_with_context += f"\n\n=== STRATEGIC CONTEXT ===\n{strategic_context}"

    signal_examples = _load_signal_examples()
    if signal_examples:
        system_with_context += f"\n{signal_examples}"

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_with_context},
            {"role": "user", "content": user_prompt},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "article_analysis",
                "strict": True,
                "schema": RESPONSE_SCHEMA,
            }
        },
        temperature=0.3,
        max_tokens=max_tokens,
    )
    
    finish_reason = response.choices[0].finish_reason
    if finish_reason == "length":
        logger.warning("Response was truncated (finish_reason=length)")
    
    content = response.choices[0].message.content
    if content is None:
        raise Exception("Empty response from OpenAI API (content is None)")
    
    try:
        result = json.loads(content)
    except json.JSONDecodeError as e:
        raise Exception(f"Failed to parse JSON response: {e}. Content: {content[:500]}")
    
    if finish_reason != "stop":
        logger.warning(f"Non-stop finish_reason: {finish_reason}")
    
    articles_result = result.get("articles", [])
    if len(articles_result) != len(articles):
        logger.warning(f"Article count mismatch: sent {len(articles)}, got {len(articles_result)}")
    
    usage = response.usage
    if usage is not None:
        logger.info(f"analyze_articles: analyzed {len(articles_result)} articles, "
                    f"prompt_tokens={usage.prompt_tokens}, completion_tokens={usage.completion_tokens}")
    
    return articles_result


def analyze_articles_batched(
    articles: List[Dict],
    topic: str,
    batch_size: int = 10,
) -> List[Dict]:
    """
    Analyze articles in batches.
    Splits the list into chunks of batch_size and calls analyze_articles
    for each chunk. Results are combined in order.
    
    Args:
        articles: Full list of articles to analyze
        topic: Monitoring topic
        batch_size: Max articles per API call (default 10)
    
    Returns:
        Combined list of analyses, in the same order as input articles.
    """
    all_analyses = []
    total_batches = (len(articles) + batch_size - 1) // batch_size
    
    for i in range(0, len(articles), batch_size):
        batch_num = i // batch_size + 1
        batch = articles[i:i + batch_size]
        logger.info(f"analyze_articles_batched: processing batch {batch_num}/{total_batches}")
        
        try:
            analyses = analyze_articles(batch, topic)
            all_analyses.extend(analyses)
        except Exception as e:
            logger.error(f"Batch {batch_num} failed: {e}")
        
        if i + batch_size < len(articles):
            time.sleep(1)
    
    logger.info(f"analyze_articles_batched: completed {len(all_analyses)}/{len(articles)} analyses")
    return all_analyses


BRIEF_SYSTEM_PROMPT = """You are the chief intelligence analyst for a strategic monitoring system focused on {topic}. Your job is to produce a daily briefing from a knowledge base of entries collected throughout the day.

You will receive:
1. A list of ALL active entries in the knowledge base (each with title, URL, signal level, category, one-line summary, why it matters, entities, tags, discovered date, and other metadata)
2. A "Current Priorities" document describing the user's active workstreams and focus areas

Your daily brief must contain these sections:

## 1. Executive Summary (2–3 sentences)
The single most important takeaway from today. What should the reader know if they read nothing else?
Lead with entries discovered TODAY (matching today's date in the Discovered Date field). Today's new discoveries should dominate the executive summary and the top of the high-priority list. Previously seen entries should only appear if their significance has genuinely increased.

## 2. Synthesis Insights
Look across ALL entries and identify convergence patterns — multiple independent signals from different sources, days, or regions that together point at the same strategic implication. For each synthesis:
- List the contributing entry titles
- Write the inference: what these entries TOGETHER suggest
- Explain relevance to the user's frameworks or priorities
Only include genuine patterns. If no convergence patterns exist today, say "No synthesis insights today."

## 3. High-Priority Entries
Sort primarily by discovery recency (today's entries first), then by relevance to current priorities. Entries discovered today should appear before older entries of similar importance. Rank the top entries by contextual relevance to the user's CURRENT PRIORITIES (not just signal level). Group by region: India, China, US/Global.
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

Be concise. Be specific. Reference actual entry titles. Do not invent entries that don't exist in the data."""


BRIEF_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "executive_summary": {"type": "string"},
        "synthesis_insights": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "contributing_entries": {"type": "array", "items": {"type": "string"}},
                    "inference": {"type": "string"},
                    "relevance": {"type": "string"}
                },
                "required": ["contributing_entries", "inference", "relevance"],
                "additionalProperties": False
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
                "additionalProperties": False
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
                "additionalProperties": False
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
                "additionalProperties": False
            }
        }
    },
    "required": ["executive_summary", "synthesis_insights", "high_priority_entries", "updated_entries", "decay_recommendations"],
    "additionalProperties": False
}


def _build_brief_prompt(
    entries: List[Dict],
    priorities_content: str,
    topic: str,
) -> str:
    """
    Build the user prompt for daily brief generation.
    Formats all entries and the priorities doc into a structured prompt.
    """
    from datetime import datetime, timezone, timedelta

    IST = timezone(timedelta(hours=5, minutes=30))
    today = datetime.now(IST).strftime("%Y-%m-%d")

    lines = [
        f"Today's date: {today}",
        f"Topic: {topic}",
        "",
        "=== CURRENT PRIORITIES ===",
        priorities_content or "No current priorities specified. Rank entries by general strategic importance.",
        "",
        f"=== KNOWLEDGE BASE ({len(entries)} active entries) ===",
    ]

    for entry in entries:
        lines.append("---")
        lines.append(f"Title: {entry.get('Title') or entry.get('title') or 'Unknown'}")
        lines.append(f"URL: {entry.get('URL') or entry.get('url') or 'N/A'}")
        sig = entry.get('Signal Level') or entry.get('signal_level') or 'N/A'
        cat = entry.get('Category') or entry.get('category') or 'N/A'
        conf = entry.get('Confidence Score') or entry.get('confidence_score') or 'N/A'
        lines.append(f"Signal: {sig} | Category: {cat} | Confidence: {conf}")
        disc = entry.get('Discovered Date') or entry.get('discovered_date') or 'N/A'
        pub = entry.get('Published Date') or entry.get('published_date') or 'N/A'
        lines.append(f"Discovered: {disc} | Published: {pub}")
        hl = entry.get('Half-Life Class') or entry.get('half_life_class') or 'N/A'
        ds = entry.get('Decay Status') or entry.get('decay_status') or 'N/A'
        dd = entry.get('Dedup Status') or entry.get('dedup_status') or 'N/A'
        lines.append(f"Half-Life: {hl} | Decay Status: {ds} | Dedup: {dd}")

        entities = entry.get('Key Entities') or entry.get('key_entities') or []
        if isinstance(entities, list):
            entities = ", ".join(str(e) for e in entities)
        lines.append(f"Entities: {entities or 'N/A'}")

        tags = entry.get('Topic Tags') or entry.get('topic_tags') or []
        if isinstance(tags, list):
            tags = ", ".join(str(t) for t in tags)
        lines.append(f"Tags: {tags or 'N/A'}")

        fw = entry.get('Framework Mapping') or entry.get('framework_mapping') or []
        if isinstance(fw, list):
            fw = ", ".join(str(f) for f in fw)
        lines.append(f"Frameworks: {fw or 'N/A'}")

        summary = entry.get('One-Line Summary') or entry.get('one_line_summary') or 'N/A'
        lines.append(f"Summary: {summary}")
        why = entry.get('Why It Matters') or entry.get('why_it_matters') or 'N/A'
        lines.append(f"Why It Matters: {why}")
        lines.append("---")

    return "\n".join(lines)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception_type((openai.RateLimitError, openai.APITimeoutError)),
    reraise=True,
)
def generate_daily_brief(
    entries: List[Dict],
    priorities_content: str,
    topic: str,
) -> dict:
    """
    Generate a daily brief from the knowledge base entries and priorities.

    Uses GPT-4o for higher-quality synthesis and reasoning.

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
            "synthesis_insights": [...],
            "high_priority_entries": [...],
            "updated_entries": [...],
            "decay_recommendations": [...],
        }

    Raises:
        Exception: If the API call fails or returns invalid JSON.
    """
    system_prompt = BRIEF_SYSTEM_PROMPT.format(topic=topic)
    strategic_context = get_strategic_context()
    if strategic_context:
        system_prompt += f"\n\n=== STRATEGIC CONTEXT ===\n{strategic_context}"

    user_prompt = _build_brief_prompt(entries, priorities_content, topic)

    # Safeguard: truncate to most recent entries if prompt exceeds 25K tokens
    MAX_ESTIMATED_TOKENS = 25000
    estimated_tokens = len(user_prompt) // 4
    if estimated_tokens > MAX_ESTIMATED_TOKENS:
        from datetime import datetime
        logger.warning(
            f"Brief prompt too large: ~{estimated_tokens} tokens "
            f"(limit {MAX_ESTIMATED_TOKENS}). Truncating to most recent entries."
        )
        def sort_key(e):
            disc = e.get("Discovered Date") or e.get("discovered_date") or ""
            try:
                return datetime.fromisoformat(disc.replace("Z", "+00:00"))
            except ValueError:
                return datetime.min
        sorted_entries = sorted(entries, key=sort_key, reverse=True)
        lo, hi = 1, len(sorted_entries)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            test_prompt = _build_brief_prompt(sorted_entries[:mid], priorities_content, topic)
            if len(test_prompt) // 4 <= MAX_ESTIMATED_TOKENS:
                lo = mid
            else:
                hi = mid - 1
        entries = sorted_entries[:lo]
        user_prompt = _build_brief_prompt(entries, priorities_content, topic)
        logger.info(
            f"Truncated to {len(entries)} entries ({len(user_prompt)//4} estimated tokens) "
            f"from original {len(sorted_entries)}"
        )

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "daily_brief",
                "strict": True,
                "schema": BRIEF_RESPONSE_SCHEMA,
            }
        },
        temperature=0.3,
        max_tokens=8000,
    )

    finish_reason = response.choices[0].finish_reason
    if finish_reason == "length":
        logger.warning("Brief response was truncated (finish_reason=length)")

    content = response.choices[0].message.content
    if content is None:
        raise Exception("Empty response from OpenAI API (content is None)")

    try:
        result = json.loads(content)
    except json.JSONDecodeError as e:
        raise Exception(f"Failed to parse JSON response: {e}. Content: {content[:500]}")

    if finish_reason != "stop":
        logger.warning(f"Non-stop finish_reason: {finish_reason}")

    usage = response.usage
    if usage is not None:
        logger.info(
            f"generate_daily_brief: synthesized {len(entries)} entries, "
            f"prompt_tokens={usage.prompt_tokens}, completion_tokens={usage.completion_tokens}"
        )

    return result


SUMMARIZE_SYSTEM_PROMPT = """You are a detail-oriented summarizer for a strategic intelligence system. Produce a comprehensive summary covering all major points, key findings, important details, and relevant context. Write in clear, professional prose. Prioritize completeness over brevity."""


def summarize_content(content: str, word_count: int = 1000) -> str:
    """
    Summarize text content using OpenAI gpt-4o-mini.

    For long content (>30K chars), splits into chunks, summarizes each,
    then combines with a final synthesis pass.

    Args:
        content: Full text content to summarize.
        word_count: Target word count (default 1000).

    Returns:
        Summary string of approximately word_count words.

    Raises:
        Exception if OpenAI call fails after retries.
    """
    CHUNK_SIZE = 30000

    if len(content) <= CHUNK_SIZE:
        return _summarize_single(content, word_count)

    chunks = [content[i:i+CHUNK_SIZE] for i in range(0, len(content), CHUNK_SIZE)]
    logger.info(f"summarize_content: {len(content)} chars → {len(chunks)} chunks")

    partials = []
    for i, chunk in enumerate(chunks):
        logger.info(f"  Summarizing chunk {i+1}/{len(chunks)}...")
        partial = _summarize_single(chunk, word_count=max(300, word_count // len(chunks)))
        partials.append(partial)
        if i < len(chunks) - 1:
            time.sleep(1)

    combined = "\n\n".join(f"Part {i+1}:\n{s}" for i, s in enumerate(partials))
    return _summarize_single(combined, word_count)


def _summarize_single(text: str, word_count: int) -> str:
    """Single OpenAI call to summarize text."""
    user_prompt = (
        f"Summarize the following content in approximately {word_count} words. "
        f"Be comprehensive — include key points, important details, and significant findings.\n\n"
        f"Content:\n{text[:25000]}"
    )

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SUMMARIZE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=1500,
    )

    result = response.choices[0].message.content
    if not result:
        raise Exception("Empty summary response from OpenAI")

    logger.info(f"  Summary: {len(result)} chars, "
                f"{response.usage.prompt_tokens}+{response.usage.completion_tokens} tokens")
    return result


if __name__ == "__main__":
    from config import TOPIC, PRIORITIES_PAGE_ID
    from notion_client import query_database, parse_page_properties, read_page_content
    from config import get_database_id

    main_kb_id = get_database_id("main_kb")
    pages = query_database(
        main_kb_id,
        filter={"property": "Decay Status", "select": {"equals": "Active"}},
    )
    entries = [parse_page_properties(p) for p in pages]
    print(f"  Active entries in Main KB: {len(entries)}")

    # Limit to most recent 80 entries to stay within TPM limit
    entries = entries[:80]
    print(f"  Using {len(entries)} most recent entries for brief")

    priorities = ""
    if PRIORITIES_PAGE_ID:
        priorities = read_page_content(PRIORITIES_PAGE_ID)
        print(f"  Priorities doc: {len(priorities)} chars")
    else:
        print("  WARNING: PRIORITIES_PAGE_ID not set — using empty priorities")

    prompt = _build_brief_prompt(entries, priorities, TOPIC)
    print(f"  Brief prompt: {len(prompt)} chars (~{len(prompt)//4} tokens)")

    # --- Test 2: Generate daily brief (real API call) ---
    print(f"\nTest 2: Generating daily brief with GPT-4o...")
    print(f"  (This calls GPT-4o standard — costs ~$0.10-0.15)")
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