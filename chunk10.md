# CHUNK 10: OpenAI Structured Output — Stage 2 Test Prompt

## Objective
Build `openai_client.py` with a function that sends a batch of articles to GPT-5.4 mini and gets back structured JSON with reasoning fields (one-line summary, why it matters, signal level, category, etc.). This is the foundation for Stage 2 reconciliation (Chunk 11). This chunk focuses on getting the prompt and structured output parsing right before wiring it into the full pipeline.

## Dependencies
- Chunk 0 complete (config.py with OPENAI_API_KEY)
- `.env` has `OPENAI_API_KEY` set

## What this chunk creates
- `openai_client.py` — new file

---

## OPENAI API REFERENCE — CHAT COMPLETIONS WITH STRUCTURED OUTPUT

### SDK Setup

We use the official `openai` Python SDK (already in requirements.txt).

```python
from openai import OpenAI

client = OpenAI()  # Reads OPENAI_API_KEY from environment automatically
```

The SDK reads `OPENAI_API_KEY` from the environment. No need to pass it explicitly. The `.env` is loaded by `config.py` via `python-dotenv`, which sets environment variables.

**IMPORTANT:** Import and call `load_dotenv()` or import from `config` before creating the OpenAI client, to ensure the env var is set.

### Chat Completions with Structured Output

```python
response = client.chat.completions.create(
    model="gpt-5.4-mini",
    messages=[
        {"role": "system", "content": "System prompt here..."},
        {"role": "user", "content": "User message here..."},
    ],
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": "article_analysis",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "field_name": {"type": "string"},
                    ...
                },
                "required": ["field_name", ...],
                "additionalProperties": False,
            }
        }
    },
    temperature=0.3,
    max_tokens=4000,
)

# Extract the JSON string
json_string = response.choices[0].message.content

# Parse it
import json
result = json.loads(json_string)
```

### Key Parameters

| Parameter | Value | Purpose |
|---|---|---|
| `model` | `"gpt-5.4-mini"` | Stage 2 model — fast, affordable reasoning |
| `messages` | list of message dicts | System prompt + user content |
| `response_format` | json_schema object | Forces model to return valid JSON matching the schema |
| `temperature` | `0.3` | Low temperature for consistent, deterministic output |
| `max_tokens` | `4000` | Enough for analyzing 5–10 articles |
| `reasoning_effort` | `"high"` | GPT-5.4 mini reasoning parameter. Higher = more thorough. |

### Response Structure

```python
response.choices[0].message.content  # JSON string
response.choices[0].finish_reason    # "stop" = complete, "length" = truncated
response.usage.prompt_tokens         # input tokens used
response.usage.completion_tokens     # output tokens used
response.usage.total_tokens          # total
```

**CRITICAL:** Always check `finish_reason`. If it's `"length"`, the output was truncated and the JSON may be incomplete/invalid. Increase `max_tokens` or reduce the batch size.

### Error Handling

| Error | Cause | Action |
|---|---|---|
| `openai.AuthenticationError` | Bad API key | Check OPENAI_API_KEY |
| `openai.RateLimitError` | Too many requests or token limit | Wait and retry (tenacity) |
| `openai.APITimeoutError` | Request took too long | Retry with exponential backoff |
| `openai.BadRequestError` | Invalid schema or input | Fix the request, don't retry |
| `json.JSONDecodeError` | Model returned invalid JSON despite schema | Retry once, then raise |

### Pricing (GPT-5.4 mini)

- Input: $0.75 per 1M tokens
- Output: $4.50 per 1M tokens
- A typical Stage 2 call with 10 articles: ~2000 input tokens, ~1500 output tokens = ~$0.008 per call
- 4 cycles/day = ~$0.03/day = ~$1/month

---

## THE STAGE 2 PROMPT

### System Prompt

The system prompt tells the model what it is, what it's doing, and how to format its output.

```
You are an intelligence analyst for a research monitoring system focused on a specific topic. Your job is to analyze a batch of newly discovered web articles and assess each one's strategic relevance.

For each article, you must determine:
1. A one-line summary (max 1 sentence)
2. Why it matters strategically
3. Signal level (High / Medium / Low)
4. Confidence score (0.0 to 1.0)
5. Category (one of: Competitor Move, Policy Change, Research, Funding, Partnership, Discourse, Other)
6. Key entities (companies, people, technologies, countries mentioned)
7. Topic tags (sub-topics this article relates to)
8. Framework mapping (which strategic frameworks this is relevant to, from: Four Schools, GTM, Tech Stack, Taxonomy)
9. Half-life class (how quickly this information decays: Policy, Research, Funding, Partnership, Discourse)

Be precise. Be concise. Do not invent information not present in the article excerpt.
Signal Level guidelines:
- High: Major funding round, significant policy change, breakthrough research, major partnership, or something that demands immediate attention
- Medium: Noteworthy development that adds to the knowledge base but doesn't require immediate action
- Low: Tangentially relevant, minor update, or low-impact discourse
```

### User Prompt Template

```
Topic: {topic}

Analyze the following {count} articles. Return a JSON object with an "articles" array containing one analysis object per article, in the same order as provided.

Articles:
---
Article 1:
Title: {title}
URL: {url}
Published: {publish_date}
Source: {source_name}
Excerpt: {excerpt_text}
---
Article 2:
...
```

### Expected Output Schema

```json
{
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
        "additionalProperties": false
      }
    }
  },
  "required": ["articles"],
  "additionalProperties": false
}
```

---

## IMPLEMENTATION SPEC

### File: `openai_client.py`

```python
"""
OpenAI API client.
Handles structured output calls for Stage 2 (reconciliation)
and Stage 3 (curation/brief generation).
"""
```

### Functions to implement:

#### `analyze_articles(articles: list[dict], topic: str) -> list[dict]`

```python
def analyze_articles(articles: list[dict], topic: str) -> list[dict]:
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
        Each dict has:
        - "title": str
        - "one_line_summary": str
        - "why_it_matters": str
        - "signal_level": str ("High", "Medium", "Low")
        - "confidence_score": float (0.0-1.0)
        - "category": str
        - "key_entities": list[str]
        - "topic_tags": list[str]
        - "framework_mapping": list[str]
        - "half_life_class": str
    
    Raises:
        Exception: If the API call fails or returns invalid JSON.
    
    Example:
        analyses = analyze_articles(
            articles=[
                {"title": "...", "url": "...", "excerpt_text": "...", 
                 "publish_date": "2026-04-03", "source_name": "reuters.com"}
            ],
            topic="Physical AI"
        )
        print(analyses[0]["signal_level"])  # "High"
    """
```

Implementation requirements:
- Build the system prompt (hardcoded string from above)
- Build the user prompt by formatting each article into the template
- For articles missing `source_name`, extract it from the URL (domain name)
- For articles missing `publish_date`, use `"Unknown"` in the prompt
- Send to `client.chat.completions.create()` with:
  - `model="gpt-5.4-mini"`
  - `response_format` with the JSON schema defined above
  - `temperature=0.3`
  - `max_tokens=4000` (increase to 8000 if batch is large)
  - `reasoning_effort="high"`
- Check `finish_reason` — if `"length"`, log a warning
- Parse the JSON response
- Validate that the response has an `"articles"` array with the same count as input
- If count mismatch, log a warning but return what we got
- Log: model used, tokens used (prompt + completion), number of articles analyzed
- Return the `"articles"` array
- Use tenacity retry for rate limit and timeout errors (NOT for bad request errors)

#### Retry decorator:

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import openai

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception_type((openai.RateLimitError, openai.APITimeoutError)),
    reraise=True,
)
def analyze_articles(...):
    ...
```

#### `_build_user_prompt(articles: list[dict], topic: str) -> str`

Private helper that formats the article list into the user prompt string.

```python
def _build_user_prompt(articles: list[dict], topic: str) -> str:
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
```

#### Batch size management

GPT-5.4 mini has a context window of 400K tokens, so batch size isn't a hard constraint. But for cost and quality, limit batches to **10 articles** per call. If the ingestion cycle produces 50 new articles, split them into 5 batches of 10 and call `analyze_articles()` for each batch.

#### `analyze_articles_batched(articles: list[dict], topic: str, batch_size: int = 10) -> list[dict]`

```python
def analyze_articles_batched(
    articles: list[dict], 
    topic: str, 
    batch_size: int = 10,
) -> list[dict]:
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
```

Implementation:
- Split articles into chunks of `batch_size`
- Call `analyze_articles()` for each chunk
- Add `time.sleep(1)` between batches to avoid rate limits
- Combine results in order
- If a batch fails, log the error and continue with the next batch. Return partial results.
- Log: total articles, number of batches, total tokens used

---

## TEST BLOCK

```python
if __name__ == "__main__":
    from config import TOPIC
    
    # --- Test 1: Build user prompt ---
    print("Test 1: Build user prompt...")
    test_articles = [
        {
            "title": "NVIDIA Launches New Isaac Platform for Robotics",
            "url": "https://nvidia.com/isaac-launch",
            "publish_date": "2026-04-01",
            "source_name": "nvidia.com",
            "excerpt_text": "NVIDIA today announced the launch of Isaac, a comprehensive platform for developing and deploying AI-powered robots. The platform includes simulation tools, pre-trained models, and edge inference capabilities designed for manufacturing and logistics applications.",
        },
        {
            "title": "India's DPIIT Announces New Robotics Manufacturing Policy",
            "url": "https://pib.gov.in/robotics-policy-2026",
            "publish_date": "2026-03-28",
            "source_name": "pib.gov.in",
            "excerpt_text": "The Department for Promotion of Industry and Internal Trade has released a comprehensive policy framework for robotics manufacturing in India, including tax incentives for domestic production and a target of 50,000 industrial robots deployed by 2030.",
        },
        {
            "title": "Physical AI Startup Raises $50M Series B",
            "url": "https://techcrunch.com/physical-ai-series-b",
            "publish_date": "2026-04-02",
            "source_name": "techcrunch.com",
            "excerpt_text": "A stealth Physical AI startup has raised $50 million in Series B funding led by Andreessen Horowitz, with participation from NVIDIA and Toyota Ventures. The company is building autonomous manipulation systems for warehouse logistics.",
        },
    ]
    
    prompt = _build_user_prompt(test_articles, TOPIC)
    print(prompt[:500])
    print("...")
    print(f"Prompt length: {len(prompt)} chars")
    print("  Build prompt: PASSED")
    
    # --- Test 2: Analyze articles (real API call) ---
    print(f"\nTest 2: Analyzing {len(test_articles)} articles with GPT-5.4 mini...")
    print("  (This makes a real API call — costs ~$0.01)")
    
    analyses = analyze_articles(test_articles, TOPIC)
    
    print(f"\n  Received {len(analyses)} analyses")
    assert len(analyses) == len(test_articles), \
        f"Expected {len(test_articles)} analyses, got {len(analyses)}"
    
    for i, a in enumerate(analyses):
        print(f"\n  Article {i+1}: {a['title'][:50]}")
        print(f"    Summary: {a['one_line_summary']}")
        print(f"    Signal: {a['signal_level']} (confidence: {a['confidence_score']})")
        print(f"    Category: {a['category']}")
        print(f"    Entities: {a['key_entities']}")
        print(f"    Tags: {a['topic_tags']}")
        print(f"    Framework: {a['framework_mapping']}")
        print(f"    Half-life: {a['half_life_class']}")
        print(f"    Why it matters: {a['why_it_matters'][:100]}...")
        
        # Validate field types
        assert isinstance(a['one_line_summary'], str) and len(a['one_line_summary']) > 0
        assert a['signal_level'] in ('High', 'Medium', 'Low')
        assert 0 <= a['confidence_score'] <= 1
        assert isinstance(a['key_entities'], list)
        assert isinstance(a['topic_tags'], list)
        assert isinstance(a['framework_mapping'], list)
        assert a['category'] in ('Competitor Move', 'Policy Change', 'Research', 'Funding', 'Partnership', 'Discourse', 'Other')
        assert a['half_life_class'] in ('Policy', 'Research', 'Funding', 'Partnership', 'Discourse')
    
    print(f"\n  All field validations: PASSED")
    
    # --- Test 3: Verify consistency ---
    print("\nTest 3: Running same analysis again for consistency...")
    analyses2 = analyze_articles(test_articles, TOPIC)
    
    # Signal levels should be the same (temperature=0.3 is low)
    for i in range(len(analyses)):
        if analyses[i]['signal_level'] != analyses2[i]['signal_level']:
            print(f"  WARNING: Signal level changed for article {i+1}: "
                  f"{analyses[i]['signal_level']} → {analyses2[i]['signal_level']}")
        else:
            print(f"  Article {i+1}: consistent signal level ({analyses[i]['signal_level']})")
    
    print("\nAll OpenAI tests completed!")
```

---

## EDGE CASES

### Model returns different count than input
If you send 10 articles but get 9 analyses back, log a warning. The calling code (Chunk 11) must handle the mismatch by matching on title.

### JSON parse failure despite schema
With `strict: true` in the schema, this should be rare. But if the response is truncated (`finish_reason: "length"`), the JSON will be invalid. Retry with a larger `max_tokens` or smaller batch.

### Very long excerpt
Some excerpts are 1500+ chars. The prompt can get long with 10 articles. GPT-5.4 mini has a 400K context window, so this isn't a problem. But keep an eye on token usage in logs.

### Article with no excerpt
If `excerpt_text` is empty, the model has nothing to analyze. It should still return a valid analysis with low confidence. Don't skip articles without excerpts.

### Rate limits
GPT-5.4 mini has generous rate limits. The tenacity retry handles `RateLimitError`. The `time.sleep(1)` between batches in `analyze_articles_batched` prevents hitting limits during large ingestion cycles.

### API key not set
The OpenAI SDK raises `openai.AuthenticationError` immediately. Log a clear error.

### Cost awareness
Each call to `analyze_articles` with 10 articles costs ~$0.008. Running 5 batches = $0.04. At 4 cycles/day, worst case is $0.64/day. Log token usage so you can track costs.