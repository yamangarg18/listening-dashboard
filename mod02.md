# MOD 02: Search Configuration

## Objective
Make the variant query templates configurable without touching code. Right now, changing what Parallel searches for (adding a new angle, removing one, tweaking keywords) requires editing `generate_variant_queries()` in `parallel_client.py`. After this mod, search angles are defined in a JSON config file that you edit with any text editor.

## Execution Order
MOD 03 ✅ → MOD 07 ✅ → MOD 05 ✅ → MOD 06 ✅ → MOD 01 (running) → **MOD 02** → MOD 04

---

## What changes

| File | Change |
|---|---|
| `search_config.json` | NEW — JSON file defining variant query templates |
| `parallel_client.py` | Update `generate_variant_queries()` to read from JSON file, fall back to hardcoded defaults |
| `config.py` | Add `SEARCH_CONFIG_PATH` |

---

## DESIGN

### Why a JSON file (not Notion)?

- **Speed:** Loading a local file is instant. Loading from Notion adds 1–2 seconds per cycle (API call + parse).
- **Simplicity:** JSON is easy to edit, version-controllable, and doesn't require Notion API.
- **Reliability:** No dependency on Notion being reachable just to know what to search for.
- **Portability:** Copy the file to a VPS alongside the code.

Strategic Context is in Notion (MOD 01) because it changes rarely and benefits from rich text editing. Search queries change more often during tuning and benefit from fast local editing.

### File structure

```json
{
  "variants": [
    {
      "label": "breaking",
      "objective": "Breaking news published in the last 48 hours about {topic}, robotics, or autonomous systems",
      "search_queries": [
        "{topic} news today",
        "robotics announcement this week"
      ],
      "enabled": true
    },
    {
      "label": "funding",
      "objective": "Venture capital funding rounds, acquisitions, and IPOs for {topic} and robotics startups in {year}",
      "search_queries": [
        "{topic} series A B C funding {year}",
        "robotics startup acquisition {year}"
      ],
      "enabled": true
    }
  ]
}
```

### Interpolation variables

The JSON templates support these placeholders:
- `{topic}` — replaced with `TOPIC` from `.env`
- `{year}` — replaced with `datetime.now().year`

### Enabling/disabling variants

Each variant has an `"enabled": true/false` field. Set to `false` to skip a variant without deleting it. Useful for A/B testing search angles.

---

## IMPLEMENTATION SPEC

### New file: `search_config.json`

Create this file in the project root with the current MOD 06 templates plus interpolation placeholders:

```json
{
  "variants": [
    {
      "label": "breaking",
      "objective": "Breaking news published in the last 48 hours about {topic}, robotics, or autonomous systems",
      "search_queries": [
        "{topic} news today",
        "robotics announcement this week"
      ],
      "enabled": true
    },
    {
      "label": "funding",
      "objective": "Venture capital funding rounds, acquisitions, and IPOs for {topic} and robotics startups in {year}",
      "search_queries": [
        "{topic} series A B C funding {year}",
        "robotics startup acquisition {year}"
      ],
      "enabled": true
    },
    {
      "label": "policy",
      "objective": "Government regulations, export controls, trade policy, and legislative actions affecting {topic} and AI",
      "search_queries": [
        "AI robotics regulation {year}",
        "export controls autonomous systems policy"
      ],
      "enabled": true
    },
    {
      "label": "research",
      "objective": "Academic papers, university research, and technical breakthroughs in {topic}, embodied AI, and robot learning",
      "search_queries": [
        "{topic} research paper {year}",
        "embodied AI robot learning breakthrough"
      ],
      "enabled": true
    },
    {
      "label": "india",
      "objective": "India-specific developments in {topic}, robotics manufacturing, automation policy, and Make in India for robotics",
      "search_queries": [
        "India robotics {topic} {year}",
        "India manufacturing automation AI policy"
      ],
      "enabled": true
    },
    {
      "label": "ecosystem",
      "objective": "Industry analysis, market reports, competitive landscape, and ecosystem mapping for {topic} and robotics industry",
      "search_queries": [
        "{topic} market analysis report {year}",
        "robotics industry landscape competitive analysis"
      ],
      "enabled": true
    }
  ]
}
```

### In `config.py` — add:

```python
# Path to search configuration file
SEARCH_CONFIG_PATH = os.getenv("SEARCH_CONFIG_PATH", "search_config.json")
```

### In `parallel_client.py` — update `generate_variant_queries()`:

Replace the current implementation:

```python
import json
from datetime import datetime

# Hardcoded fallback (same as current MOD 06 templates)
_DEFAULT_VARIANTS = [
    {
        "label": "breaking",
        "objective": "Breaking news published in the last 48 hours about {topic}, robotics, or autonomous systems",
        "search_queries": ["{topic} news today", "robotics announcement this week"],
        "enabled": True,
    },
    {
        "label": "funding",
        "objective": "Venture capital funding rounds, acquisitions, and IPOs for {topic} and robotics startups in {year}",
        "search_queries": ["{topic} series A B C funding {year}", "robotics startup acquisition {year}"],
        "enabled": True,
    },
    {
        "label": "policy",
        "objective": "Government regulations, export controls, trade policy, and legislative actions affecting {topic} and AI",
        "search_queries": ["AI robotics regulation {year}", "export controls autonomous systems policy"],
        "enabled": True,
    },
    {
        "label": "research",
        "objective": "Academic papers, university research, and technical breakthroughs in {topic}, embodied AI, and robot learning",
        "search_queries": ["{topic} research paper {year}", "embodied AI robot learning breakthrough"],
        "enabled": True,
    },
    {
        "label": "india",
        "objective": "India-specific developments in {topic}, robotics manufacturing, automation policy, and Make in India for robotics",
        "search_queries": ["India robotics {topic} {year}", "India manufacturing automation AI policy"],
        "enabled": True,
    },
    {
        "label": "ecosystem",
        "objective": "Industry analysis, market reports, competitive landscape, and ecosystem mapping for {topic} and robotics industry",
        "search_queries": ["{topic} market analysis report {year}", "robotics industry landscape competitive analysis"],
        "enabled": True,
    },
]


def _load_search_config() -> list[dict]:
    """
    Load variant templates from search_config.json.
    Falls back to hardcoded defaults if file doesn't exist or is invalid.
    """
    from config import SEARCH_CONFIG_PATH
    
    try:
        with open(SEARCH_CONFIG_PATH, "r") as f:
            config = json.load(f)
        variants = config.get("variants", [])
        if not variants:
            logger.warning("search_config.json has no variants — using defaults")
            return _DEFAULT_VARIANTS
        logger.debug(f"Loaded {len(variants)} variants from {SEARCH_CONFIG_PATH}")
        return variants
    except FileNotFoundError:
        logger.info(f"{SEARCH_CONFIG_PATH} not found — using default variants")
        return _DEFAULT_VARIANTS
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {SEARCH_CONFIG_PATH}: {e} — using defaults")
        return _DEFAULT_VARIANTS


def generate_variant_queries(topic: str, num_variants: int = 6) -> list[dict]:
    """
    Generate variant search configurations from a topic.
    
    Reads from search_config.json if available, otherwise uses defaults.
    Interpolates {topic} and {year} placeholders.
    Filters out disabled variants (enabled=false).
    
    Args:
        topic: The main topic. Example: "Physical AI"
        num_variants: Max variants to return.
    
    Returns:
        List of variant dicts with label, objective, search_queries.
    """
    if not topic:
        raise ValueError("Topic cannot be empty")
    
    current_year = str(datetime.now().year)
    raw_variants = _load_search_config()
    
    # Filter to enabled only
    enabled = [v for v in raw_variants if v.get("enabled", True)]
    
    # Interpolate placeholders
    result = []
    for v in enabled[:num_variants]:
        result.append({
            "label": v["label"],
            "objective": v["objective"].replace("{topic}", topic).replace("{year}", current_year),
            "search_queries": [
                q.replace("{topic}", topic).replace("{year}", current_year)
                for q in v["search_queries"]
            ],
        })
    
    return result
```

---

## HOW TO USE

### Adding a new search angle

Edit `search_config.json`, add a new entry:

```json
{
    "label": "china",
    "objective": "China-specific developments in {topic}, robotics manufacturing, export restrictions, and competitive landscape",
    "search_queries": [
        "China robotics {topic} {year}",
        "China AI manufacturing automation"
    ],
    "enabled": true
}
```

Restart the pipeline. The next cycle includes the new variant.

### Disabling a variant temporarily

Set `"enabled": false` on the variant. It stays in the file but is skipped.

### Changing search keywords

Edit the `search_queries` array. Use `{topic}` and `{year}` as placeholders.

### No restart needed for config changes

`_load_search_config()` reads the file every time `generate_variant_queries()` is called. Changes take effect on the next cycle without restarting the scheduler.

---

## TEST BLOCK

No standalone test block needed. Verify through existing tests:

```bash
# Verify config loads
python3 -c "
from parallel_client import generate_variant_queries

variants = generate_variant_queries('Physical AI')
for v in variants:
    print(f'[{v[\"label\"]}] {v[\"objective\"][:70]}')
    print(f'  Queries: {v[\"search_queries\"]}')
print(f'\n{len(variants)} variants loaded')
print('PASSED')
"
```

---

## EDGE CASES

### search_config.json doesn't exist
Falls back to hardcoded defaults. Logged as info, not error. Pipeline works exactly as before.

### Invalid JSON
Falls back to defaults. Logged as error with parse details.

### Empty variants array
Falls back to defaults. Logged as warning.

### Missing fields in a variant
If a variant is missing `label`, `objective`, or `search_queries`, Python will raise a KeyError. The fix: `_load_search_config()` could validate each variant, but for now, keep it simple — the user is editing the file intentionally and will see the error immediately.

### {topic} or {year} not in a template
No error — `.replace()` on a string without the placeholder is a no-op. The query just doesn't have the topic/year interpolated, which may produce broader results.

### File changes between cycles
`_load_search_config()` reads the file on every call. If you edit `search_config.json` between Cycle 1 and Cycle 2, Cycle 2 uses the new config. No restart needed.

### Docker deployment
Add `search_config.json` to docker-compose volumes so it's editable from the host:
```yaml
volumes:
  - ./search_config.json:/app/search_config.json
```
Also add it to the Dockerfile COPY or the volumes list. Tell OpenCode to add this.