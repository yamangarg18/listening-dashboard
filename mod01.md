# MOD 01: Strategic Context

## Objective
Create a "Strategic Context" Notion page that feeds YOUR frameworks, tracked entities, competitive landscape, and strategic lens into both Stage 2 and Stage 3 system prompts. Right now the model analyzes articles as a generic analyst. After this mod, it analyzes as YOUR analyst — knowing about the Four Schools framework, your GTM plays, specific companies you track, what constitutes noise vs signal for your specific work.

## Execution Order
MOD 03 ✅ → MOD 07 ✅ → MOD 05 ✅ → MOD 06 (running) → **MOD 01** → MOD 02 → MOD 04

---

## What changes

| File | Change |
|---|---|
| **Notion** | Create "Strategic Context" page under Listening Dashboard |
| `config.py` | Add `STRATEGIC_CONTEXT_PAGE_ID` |
| `.env` | Add `STRATEGIC_CONTEXT_PAGE_ID=<page_id>` |
| `.env.example` | Add `STRATEGIC_CONTEXT_PAGE_ID` |
| `openai_client.py` | Stage 2 system prompt reads and includes strategic context |
| `openai_client.py` | Stage 3 system prompt reads and includes strategic context |
| `reconciliation.py` | Pass strategic context to `analyze_articles_batched()` |
| `curation.py` | Pass strategic context to `generate_daily_brief()` |

---

## MANUAL STEP 1: Create the Strategic Context page

In Notion, under the "Listening Dashboard" parent page:

1. Click `+` to add a new page (NOT a database — a regular page, like Current Priorities)
2. Title: **Strategic Context**
3. Write the content below (or your own version — this is a starting template):

```
# Strategic Context — Physical AI Intelligence System

## Your Role
You are analyzing content for Yaman Garg, founder building in the Physical AI space in India. Everything should be evaluated through the lens of: what does this mean for building a Physical AI company in India?

## Frameworks to Map Against

### Four Schools of Physical AI
1. School 1: Simulation-first (NVIDIA Isaac, digital twins → physical deployment)
2. School 2: Data-first (Tesla FSD approach, massive real-world data collection)
3. School 3: Foundation model (Physical Intelligence π, general-purpose robot models)
4. School 4: Vertical-specific (Halter for livestock, specialized closed-loop systems)

### GTM Plays
- Play 1: Pick-and-place automation for Indian manufacturing
- Play 2: Autonomous inspection and quality control
- Play 3: Last-mile logistics robotics
- Play 4: Agriculture and food processing automation
- Play 5: Construction site automation
- Play 6: Warehouse robotics-as-a-service

### Tech Stack (9 layers)
Layer 1 (Sensors) through Layer 9 (Application). When an article mentions a component, note which layer it maps to.

## Entities to Track
### Companies (High Priority)
NVIDIA, Boston Dynamics, Physical Intelligence (π), Halter, Tesla (FSD/Optimus), Agility Robotics, Figure AI, 1X Technologies, Covariant, Symbotic, Locus Robotics

### Companies (India)
Addverb Technologies, Gridbots, Systemantics, Miko Robotics, Invento Robotics, hi-Tech Robotic Systemz

### Investors
Andreessen Horowitz, Khosla Ventures, Sequoia, Tiger Global, Accel India, Kalaari Capital

### Government Bodies
DPIIT, MoRTH, NITI Aayog, BIS (for robotics standards)

## India-Specific Context
- Robot density: ~7 per 10,000 manufacturing workers (global avg ~162)
- NDAA Section 889 creates opportunity for non-Chinese robotics suppliers
- MoRTH March 2024 directive on autonomous vehicle testing
- Closed-loop data flywheel is the core defensible moat thesis
- India manufacturing labor cost advantage makes ROI calculation different from US/China

## What Counts as Noise
- Generic "AI will change everything" opinion pieces
- AI ethics debates without policy/regulatory action
- Pure software AI (LLMs, chatbots) with no physical-world component
- Social media influencer hot takes
- Product reviews of consumer gadgets

## What Counts as High Signal
- Any funding round >$10M in Physical AI/robotics
- Government policy directly affecting robotics deployment
- New partnerships between tracked companies
- Research breakthroughs in sim-to-real transfer, manipulation, or locomotion
- India-specific robotics infrastructure developments
- Competitive moves by School 1-4 companies
```

4. Copy the page ID from the URL (the 32-character hex string at the end of the Notion URL)
5. Add to `.env`:
```
STRATEGIC_CONTEXT_PAGE_ID=paste-your-page-id-here
```

---

## IMPLEMENTATION SPEC

### In `config.py` — add:

```python
# Strategic Context page ID (optional but recommended)
STRATEGIC_CONTEXT_PAGE_ID = os.getenv("STRATEGIC_CONTEXT_PAGE_ID", "")
```

### In `.env.example` — add:

```bash
# Strategic Context page ID — provides frameworks and entity tracking to AI analysis
STRATEGIC_CONTEXT_PAGE_ID=
```

### In `openai_client.py`:

#### Add a helper to load strategic context:

```python
def _load_strategic_context() -> str:
    """
    Load strategic context from Notion page.
    Returns the page content as a string, or empty string if not configured.
    Cached for the lifetime of the process (reloaded on restart).
    """
    from config import STRATEGIC_CONTEXT_PAGE_ID
    
    if not STRATEGIC_CONTEXT_PAGE_ID:
        return ""
    
    try:
        from notion_client import read_page_content
        content = read_page_content(STRATEGIC_CONTEXT_PAGE_ID)
        logger.info(f"Loaded strategic context: {len(content)} chars")
        return content
    except Exception as e:
        logger.warning(f"Failed to load strategic context: {e}")
        return ""

# Module-level cache — loaded once per process
_strategic_context_cache = None

def get_strategic_context() -> str:
    """Get cached strategic context, loading if needed."""
    global _strategic_context_cache
    if _strategic_context_cache is None:
        _strategic_context_cache = _load_strategic_context()
    return _strategic_context_cache
```

#### Update Stage 2 system prompt in `analyze_articles()`:

Find where the system prompt is built for `analyze_articles()`. Add the strategic context after the existing system prompt text:

```python
def analyze_articles(articles: list[dict], topic: str) -> list[dict]:
    # Build system prompt
    system_prompt = SYSTEM_PROMPT.format(topic=topic)  # or however it's currently built
    
    # Append strategic context if available
    strategic_context = get_strategic_context()
    if strategic_context:
        system_prompt += f"\n\n=== STRATEGIC CONTEXT ===\n{strategic_context}"
    
    # ... rest of function unchanged
```

If the system prompt is a hardcoded string (not using `.format()`), adjust accordingly. The key is appending the strategic context to whatever system prompt already exists.

#### Update Stage 3 system prompt in `generate_daily_brief()`:

Same pattern:

```python
def generate_daily_brief(entries: list[dict], priorities_content: str, topic: str) -> dict:
    # Build system prompt
    system_prompt = BRIEF_SYSTEM_PROMPT.format(topic=topic)  # or however it's built
    
    # Append strategic context if available
    strategic_context = get_strategic_context()
    if strategic_context:
        system_prompt += f"\n\n=== STRATEGIC CONTEXT ===\n{strategic_context}"
    
    # ... rest of function unchanged
```

The strategic context appears in BOTH Stage 2 and Stage 3 system prompts. This means:
- **Stage 2** uses it to better classify articles (knowing what you track, what's noise, what's signal)
- **Stage 3** uses it to generate briefs aligned with your frameworks (Four Schools mapping, GTM relevance)

---

## HOW STRATEGIC CONTEXT IS USED BY THE MODEL

The model receives the strategic context as part of its system instructions. It doesn't need to be told "use this context" — it's in the system prompt, so the model naturally applies it when analyzing articles.

Example impact:
- **Before:** An article about Halter raising $50M gets `Category: Funding, Signal: Medium`
- **After:** The model sees Halter is a tracked entity in the "School 4: Vertical-specific" category. It assigns `Category: Funding, Signal: High` and maps it to the Four Schools framework.

- **Before:** A generic "AI will transform industries" opinion piece gets `Signal: Medium`
- **After:** The model sees this is listed under "What Counts as Noise" and assigns `Signal: Low`

---

## TOKEN IMPACT

The strategic context template above is ~600 words ≈ ~800 tokens. This gets added to:
- Every Stage 2 call: +800 tokens × ~12 calls/day = ~10K extra tokens/day → ~$0.008/day with gpt-4o-mini
- Every Stage 3 call: +800 tokens × 1 call/day = ~800 extra tokens/day → negligible with gpt-4o

Total extra cost: **<$0.01/day** — negligible.

---

## TEST BLOCK

No standalone test block needed. Test through the pipeline:

```bash
# Verify context loads
python3 -c "
from openai_client import get_strategic_context
ctx = get_strategic_context()
print(f'Strategic context: {len(ctx)} chars')
if ctx:
    print(f'First 200 chars: {ctx[:200]}...')
    print('PASSED')
else:
    print('WARNING: Empty — check STRATEGIC_CONTEXT_PAGE_ID in .env')
"

# Run a cycle and observe improved analysis
python main.py 1

# Run a brief and observe framework-aligned ranking
python main.py brief
```

---

## EDGE CASES

### STRATEGIC_CONTEXT_PAGE_ID not set
`get_strategic_context()` returns empty string. System prompts work exactly as before (no context appended). No crash, no warning — the feature is optional.

### Page exists but is empty
Returns empty string. Same as not set. No impact.

### Page content is very long (>5000 words)
The strategic context adds tokens to EVERY OpenAI call. If the page is 5000 words (~6500 tokens), that's significant. Keep the page focused — frameworks, entities, what's noise/signal. Not a full research document.

Recommend keeping the page under 1500 words for cost efficiency.

### User updates the page while pipeline is running
The context is cached per process (`_strategic_context_cache`). Changes to the Notion page don't take effect until the pipeline restarts. This is intentional — mid-cycle context changes could cause inconsistent analysis. Restart the scheduler to pick up changes.

### Context conflicts with system prompt
The strategic context is appended after the system prompt. If it contradicts something in the system prompt (e.g., "High signal means..." vs context saying "What counts as High Signal..."), the model sees both. In practice, the model integrates both naturally — the more specific guidance (your context) takes precedence over generic definitions.

### Multiple users with different contexts
Not supported — one context per pipeline instance. If you need different contexts for different topics, run separate pipeline instances with separate `.env` files.