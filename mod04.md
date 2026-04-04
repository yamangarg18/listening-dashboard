# MOD 04: Signal Calibration

## Objective
The model's signal level assignments (High/Medium/Low) may not match YOUR sense of importance. This mod adds calibration examples to the Stage 2 system prompt — real articles you've already classified, showing the model what YOU consider High vs Medium vs Low. Few-shot learning for signal calibration.

## Execution Order
MOD 03 ✅ → MOD 07 ✅ → MOD 05 ✅ → MOD 06 ✅ → MOD 01 → MOD 02 → **MOD 04** (last)

---

## What changes

| File | Change |
|---|---|
| `signal_examples.json` | NEW — JSON file with your calibration examples |
| `openai_client.py` | Stage 2 system prompt appends calibration examples |

---

## DESIGN

### How calibration works

The model sees your examples in the system prompt before analyzing new articles. This is "few-shot learning" — the model learns your calibration from examples and applies it to new content.

Without examples:
```
Signal Level guidelines:
- High: Major funding round, significant policy change...
- Medium: Noteworthy development...
- Low: Tangentially relevant...
```

With examples (after this mod):
```
Signal Level guidelines:
- High: Major funding round, significant policy change...
- Medium: Noteworthy development...
- Low: Tangentially relevant...

=== CALIBRATION EXAMPLES ===
These are real articles classified by the user. Match this calibration.

HIGH SIGNAL:
- "Arm launches 'Physical AI' unit, joining rush to robotics" → High because: Major competitor entering Physical AI directly, affects competitive landscape
- "India's DPIIT Announces New Robotics Manufacturing Policy" → High because: Government policy directly affecting robotics deployment in India

MEDIUM SIGNAL:
- "5 AI Architects Share What Worries and Excites Them" → Medium because: Industry discourse, useful context but no direct action trigger
- "Physical AI Made Waves At CES 2026. What Is It?" → Medium because: Awareness article, validates the space but no new information

LOW SIGNAL:
- "AI data centres and the law: What you need to know" → Low because: Generic AI compliance topic, no Physical AI or robotics component
- "Generative AI Publication | LinkedIn" → Low because: Pure software AI content, no physical-world relevance
```

### Where examples come from

YOU provide them. Look through your Main KB, pick 2–3 entries for each signal level that you agree with (or would reclassify), and add them to `signal_examples.json`. Over time, add more examples as you notice miscalibrations.

### File structure

```json
{
  "high": [
    {
      "title": "Article title",
      "reason": "Why this is High signal"
    }
  ],
  "medium": [
    {
      "title": "Article title",
      "reason": "Why this is Medium signal"
    }
  ],
  "low": [
    {
      "title": "Article title",
      "reason": "Why this is Low signal"
    }
  ]
}
```

Keep it to 2–4 examples per level. More than that adds tokens without proportional benefit.

---

## IMPLEMENTATION SPEC

### New file: `signal_examples.json`

Create with starter examples (you should customize these based on your actual Main KB entries):

```json
{
  "high": [
    {
      "title": "Arm launches 'Physical AI' unit, joining rush to robotics",
      "reason": "Major competitor entering Physical AI directly, affects competitive landscape and School 1-4 dynamics"
    },
    {
      "title": "Physical AI Startup Raises $50M Series B",
      "reason": "Significant funding in the space, signals investor confidence in Physical AI commercialization"
    }
  ],
  "medium": [
    {
      "title": "5 AI Architects Share What Worries and Excites Them About Next-Gen AI",
      "reason": "Industry discourse, useful context but no direct action trigger or new information"
    },
    {
      "title": "Physical AI Made Waves At CES 2026. What Is It?",
      "reason": "Awareness and validation article, no new technical or business information"
    }
  ],
  "low": [
    {
      "title": "AI data centres and the law: What you need to know",
      "reason": "Generic AI compliance topic with no Physical AI or robotics component"
    },
    {
      "title": "What to Know About AI and Campus Mental Health",
      "reason": "Completely unrelated to Physical AI, robotics, or manufacturing — pure software AI application"
    }
  ]
}
```

### In `openai_client.py`:

#### Add a helper to load calibration examples:

```python
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
```

#### Update Stage 2 system prompt in `analyze_articles()`:

After appending strategic context (MOD 01), also append calibration examples:

```python
def analyze_articles(articles: list[dict], topic: str) -> list[dict]:
    system_prompt = SYSTEM_PROMPT  # existing
    
    # MOD 01: Strategic context
    strategic_context = get_strategic_context()
    if strategic_context:
        system_prompt += f"\n\n=== STRATEGIC CONTEXT ===\n{strategic_context}"
    
    # MOD 04: Signal calibration examples
    signal_examples = _load_signal_examples()
    if signal_examples:
        system_prompt += f"\n{signal_examples}"
    
    # ... rest of function unchanged
```

Calibration examples are ONLY added to Stage 2 (article analysis), not Stage 3 (daily brief). Stage 3 consumes signal levels that are already assigned — it doesn't need to know how to assign them.

---

## HOW TO USE

### Initial setup

1. Open your Main KB in Notion
2. Find 2 entries you think are correctly classified as High signal
3. Find 2 entries correctly classified as Medium
4. Find 2 entries correctly classified as Low
5. Copy their titles and your reasoning into `signal_examples.json`

### Ongoing calibration

When you notice a miscalibration (e.g., a generic article gets High when it should be Low):
1. Open `signal_examples.json`
2. Add the article to the correct level with a reason explaining why
3. The next cycle uses the updated examples — no restart needed

### How many examples?

- **Minimum:** 1 per level (3 total)
- **Recommended:** 2–3 per level (6–9 total)
- **Maximum practical:** 5 per level (15 total) — more adds tokens without much benefit

### Token impact

6 examples ≈ ~300 tokens added to every Stage 2 call.
- 12 Stage 2 calls/day × 300 tokens = 3,600 tokens/day → ~$0.003/day
- Negligible cost.

---

## TEST BLOCK

No standalone test block. Verify through the pipeline:

```bash
# Verify examples load
python3 -c "
from openai_client import _load_signal_examples

examples = _load_signal_examples()
if examples:
    print(f'Loaded calibration examples ({len(examples)} chars):')
    print(examples[:500])
    print('PASSED')
else:
    print('No examples loaded — check signal_examples.json')
"

# Run a cycle and observe signal assignments
python main.py 1
```

---

## EDGE CASES

### signal_examples.json doesn't exist
`_load_signal_examples()` returns empty string. System prompt works exactly as before. No crash.

### Invalid JSON
Returns empty string. Logged at debug level. Falls back to no examples.

### Empty arrays
If `"high": []`, that level is skipped. Other levels still included.

### Very long reasons
Keep reasons to 1–2 sentences. Long reasons add tokens without benefit. The model needs the gist, not an essay.

### Examples contradict strategic context
If your examples say "generic AI articles are Low" but the strategic context doesn't mention this, the model sees both. The examples are more specific and carry more weight in practice.

### Stale examples
If an example references an article that no longer exists in the Main KB, the model still uses it as a calibration point. The title and reasoning are what matter, not whether the entry still exists.

### File changes between cycles
`_load_signal_examples()` reads the file on every call. Changes take effect on the next cycle without restart.