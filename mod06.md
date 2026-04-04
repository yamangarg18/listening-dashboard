# MOD 06: Result Uniqueness

## Objective
Reduce duplicate and overlapping results from Parallel. Right now, multiple variant queries often return the same top articles from slightly different angles. This mod improves diversity by making variant objectives more distinct, adding cross-variant dedup at the search level, and dynamically excluding domains that already contributed results in earlier variants.

## Execution Order
MOD 03 ✅ → MOD 07 → MOD 05 (running) → **MOD 06** → MOD 01 → MOD 02 → MOD 04

---

## What changes

| File | Change |
|---|---|
| `parallel_client.py` | Rewrite variant query templates to be more distinct |
| `parallel_client.py` | Add progressive domain exclusion across variants |
| `parallel_client.py` | Improve logging to show overlap stats |

---

## PROBLEM

Looking at real pipeline logs:

```
search_multiple: 60 results, 10 duplicates removed, 50 unique
```

10 duplicates across 6 variants means ~17% overlap. The same NVIDIA article appears in "core_news", "companies", and "research" because all three variant objectives are broad enough to surface it.

After database dedup:
```
deduplicate_against_db: 67 results → 16 new, 51 dupes
```

Only 16 out of 67 combined results are actually new. That's 76% wasted API calls. While some waste is unavoidable (the DB grows), reducing cross-variant overlap means more unique results per cycle.

---

## CHANGE 1: More distinct variant objectives

### Problem
Current variant objectives are broad and overlap:
- "Latest news and developments in Physical AI" (core_news)
- "Product launches, partnerships, strategic moves by companies in Physical AI" (companies)

Both return NVIDIA press releases, Reuters articles, etc. The objectives aren't different enough for Parallel to return different result sets.

### Fix
Rewrite variant templates with sharper, more distinct objectives and keywords. Each variant should target a DIFFERENT type of source or content:

```python
def generate_variant_queries(topic: str, num_variants: int = 6) -> list[dict]:
    current_year = str(datetime.now().year)
    
    templates = [
        {
            "label": "breaking",
            "objective": f"Breaking news published in the last 48 hours about {topic}, robotics, or autonomous systems",
            "search_queries": [
                f"{topic} news today",
                f"robotics announcement this week",
            ],
        },
        {
            "label": "funding",
            "objective": f"Venture capital funding rounds, acquisitions, and IPOs for {topic} and robotics startups in {current_year}",
            "search_queries": [
                f"{topic} series A B C funding {current_year}",
                f"robotics startup acquisition {current_year}",
            ],
        },
        {
            "label": "policy",
            "objective": f"Government regulations, export controls, trade policy, and legislative actions affecting {topic} and AI",
            "search_queries": [
                f"AI robotics regulation {current_year}",
                f"export controls autonomous systems policy",
            ],
        },
        {
            "label": "research",
            "objective": f"Academic papers, university research, and technical breakthroughs in {topic}, embodied AI, and robot learning",
            "search_queries": [
                f"{topic} research paper {current_year}",
                f"embodied AI robot learning breakthrough",
            ],
        },
        {
            "label": "india",
            "objective": f"India-specific developments in {topic}, robotics manufacturing, automation policy, and Make in India for robotics",
            "search_queries": [
                f"India robotics {topic} {current_year}",
                f"India manufacturing automation AI policy",
            ],
        },
        {
            "label": "ecosystem",
            "objective": f"Industry analysis, market reports, competitive landscape, and ecosystem mapping for {topic} and robotics industry",
            "search_queries": [
                f"{topic} market analysis report {current_year}",
                f"robotics industry landscape competitive analysis",
            ],
        },
    ]
    
    return templates[:num_variants]
```

Key changes from old templates:
- **"core_news" → "breaking"** — specifically targets last 48 hours, reducing overlap with evergreen content
- **"companies" → "ecosystem"** — focuses on analysis/reports instead of company news (which overlaps with breaking/funding)
- **Keywords are more specific** — "series A B C funding" instead of "funding round", "embodied AI robot learning" instead of generic "research"
- **Each variant targets a different SOURCE TYPE** — news outlets (breaking), VC/finance press (funding), government/legal sources (policy), academic databases (research), Indian media (india), analyst reports (ecosystem)

---

## CHANGE 2: Progressive domain exclusion

### Problem
When variant 1 (breaking) returns results from reuters.com, nvidia.com, and techcrunch.com, variant 2 (funding) searches those same domains again and often returns the same articles.

### Fix
After each variant search, collect the domains that appeared in results. Add those domains to the exclude list for subsequent variants. This forces later variants to look at different sources.

In `search_multiple()`, update the variant loop:

```python
def search_multiple(
    topic: str,
    after_date: str | None = None,
    max_results_per_query: int = 10,
    num_variants: int = 6,
    exclude_domains: list[str] | None = None,
) -> list[dict]:
    
    variants = generate_variant_queries(topic, num_variants)
    
    # Start with config exclude domains
    if exclude_domains is None:
        from config import EXCLUDE_DOMAINS
        base_excludes = list(EXCLUDE_DOMAINS)
    else:
        base_excludes = list(exclude_domains)
    
    all_results = []
    seen_domains = set()  # Domains already seen in this cycle
    
    for variant in variants:
        # Build exclude list: base + domains already seen
        # Cap at 10 (Parallel limit)
        cycle_excludes = list(base_excludes)
        for domain in seen_domains:
            if domain not in cycle_excludes and len(cycle_excludes) < 10:
                cycle_excludes.append(domain)
        
        logger.info(f"Running variant search: [{variant['label']}] "
                    f"(excluding {len(cycle_excludes)} domains)")
        
        try:
            results = search(
                objective=variant["objective"],
                search_queries=variant["search_queries"],
                max_results=max_results_per_query,
                after_date=after_date,
                exclude_domains=cycle_excludes,
            )
            
            # Track domains from these results
            for r in results:
                domain = _extract_domain(r.get("url", ""))
                if domain:
                    seen_domains.add(domain)
            
            # Tag results with variant label
            for r in results:
                r["found_by"] = [variant["label"]]
            
            all_results.extend(results)
            
        except Exception as e:
            logger.error(f"Variant [{variant['label']}] failed: {e}")
        
        time.sleep(0.5)
    
    # ... rest of existing dedup + quality filter logic ...
```

Add the domain extraction helper:

```python
def _extract_domain(url: str) -> str | None:
    """Extract domain from URL for progressive exclusion."""
    if not url:
        return None
    from urllib.parse import urlparse
    netloc = urlparse(url).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc if netloc else None
```

### Important limits

- Parallel allows max 10 `exclude_domains`. The base list (from MOD 03) uses 7 slots. Progressive exclusion can add up to 3 more domains per variant.
- After the first variant returns results from 10 domains, not all can be excluded in the next variant. This is fine — even excluding 2–3 top domains (e.g., nvidia.com, reuters.com) significantly diversifies later variants.
- The progressive exclusion resets each cycle. Domains excluded in Cycle 1 are NOT excluded in Cycle 2 — each cycle starts fresh.

---

## CHANGE 3: Better overlap logging

Update the logging after dedup to show overlap statistics:

```python
# After cross-query dedup
logger.info(f"search_multiple: {len(all_results)} raw, "
           f"{duplicates_removed} cross-variant duplicates, "
           f"{len(deduplicated_results)} unique, "
           f"{quality_filtered} quality-filtered, "
           f"{len(quality_results)} final")

# Log domain diversity
domains = set()
for r in quality_results:
    d = _extract_domain(r.get("url", ""))
    if d:
        domains.add(d)
logger.info(f"  Source diversity: {len(domains)} unique domains")
```

---

## WHAT THIS MOD DOES NOT CHANGE

- The number of variant queries (still 6 for Pass B, 4 for Pass A via num_variants parameter)
- The dedup-against-database logic (Chunk 8)
- The quality filter (MOD 03)
- The exclude_domains config defaults (MOD 03)
- Pass A vs Pass B structure
- No new files

---

## TEST BLOCK

Update the test block in `parallel_client.py` to verify uniqueness improvements:

```python
if __name__ == "__main__":
    from config import TOPIC, EXCLUDE_DOMAINS
    
    # --- Test 1: Verify variant objectives are distinct ---
    print("Test 1: Variant query diversity...")
    variants = generate_variant_queries(TOPIC)
    
    objectives = [v["objective"] for v in variants]
    for i, v in enumerate(variants):
        print(f"  [{v['label']}] {v['objective'][:70]}")
    
    # Check no two objectives share more than 3 words (crude distinctness check)
    for i in range(len(objectives)):
        for j in range(i+1, len(objectives)):
            words_i = set(objectives[i].lower().split())
            words_j = set(objectives[j].lower().split())
            shared = words_i & words_j - {"in", "and", "the", "of", "for", "a", "an", "to", TOPIC.lower()}
            if len(shared) > 5:
                print(f"  WARNING: [{variants[i]['label']}] and [{variants[j]['label']}] share {len(shared)} content words: {shared}")
    
    print("  Variant diversity: CHECK PASSED")
    
    # --- Test 2: Run search and check domain diversity ---
    print(f"\nTest 2: Running search with progressive domain exclusion...")
    results = search_multiple(
        topic=TOPIC,
        max_results_per_query=10,
        num_variants=4,
    )
    
    domains = set()
    for r in results:
        d = _extract_domain(r.get("url", ""))
        if d:
            domains.add(d)
    
    print(f"  Results: {len(results)}")
    print(f"  Unique domains: {len(domains)}")
    print(f"  Domain diversity ratio: {len(domains)/max(len(results),1):.1%}")
    
    if len(domains) >= 10:
        print("  Domain diversity: GOOD (10+ sources)")
    elif len(domains) >= 5:
        print("  Domain diversity: OK (5-9 sources)")
    else:
        print("  Domain diversity: LOW (<5 sources) — may need tuning")
    
    print("\nAll uniqueness tests completed!")
```

---

## EDGE CASES

### All 10 exclude slots filled by base list
If user configures many `EXTRA_EXCLUDE_DOMAINS` and the base list fills all 10 slots, progressive exclusion has no room. This is fine — the quality filter (MOD 03 Layer 2) still catches duplicates post-search.

### Same article, different domains (syndication)
Reuters publishes an article, Yahoo News and MSN syndicate it. Progressive domain exclusion blocks reuters.com for later variants, but Yahoo and MSN versions still appear. The title-similarity dedup (Chunk 8) catches these.

### Progressive exclusion blocks a domain that later variants need
If variant 1 gets results from arxiv.org and variant 4 (research) would benefit from arxiv.org, it's excluded. This is acceptable — variant 1 already captured those arxiv results. Variant 4 is forced to find OTHER research sources (university sites, IEEE, Nature), which increases diversity.

### Very niche topic with few sources
If only 3-4 domains cover the topic, progressive exclusion after variant 1 might make later variants return fewer results. The empty-results handling in search_multiple already handles this (partial results returned).

### _extract_domain returns None
URLs with no domain (malformed) return None, which is not added to seen_domains. No crash.