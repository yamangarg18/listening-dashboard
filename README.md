# Listening Pipeline

Autonomous intelligence monitoring system for Physical AI topic. Searches the web, reconciles findings against Notion, and produces daily briefings.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      SCHEDULER (APScheduler)               │
│  06:30 │ Cycle 1  │ 11:30 │ Cycle 2  │                     │
│  17:30 │ Cycle 3  │ 22:30 │ Cycle 4  │                     │
│  23:00 │ Daily Brief              │ 60s │ Extract Poll      │
└─────────────────────────────────────────────────────────────┘
         │                   │                 │
         ▼                   ▼                 ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ STAGE 1         │ │ STAGE 2         │ │ EXTRACT         │
│ Ingestion       │ │ Reconciliation  │ │ Extract Content │
│ (Parallel API)  │ │ (OpenAI)        │ │ (Parallel API)  │
└────────┬────────┘ └────────┬────────┘ └────────┬────────┘
         │                   │                 │
         ▼                   ▼                 ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ Ingestion Queue │ │ Main KB         │ │ Body blocks     │
│ (Notion DB)     │ │ (Notion DB)     │ │ AI Summary prop │
└─────────────────┘ └─────────────────┘ └─────────────────┘
```

### Three-stage flow

**Stage 1 — Ingestion (Parallel Search)**
- Pass A: Time-window search (last 5 hours, 4 variants)
- Pass B: Relevance-ranked search (last 30 days, 6 variants)
- Cross-variant dedup + quality filter + database dedup
- New entries → Ingestion Queue

**Stage 2 — Reconciliation (OpenAI Analysis)**
- Analyzes queue entries via `gpt-4o-mini`
- Assigns: Signal Level, Category, One-Line Summary, Why It Matters, Entities, Tags, Framework Mapping, Half-Life Class
- Escalation check → sends email for High signal entries
- Entries → Main KB

**Stage 3 — Curation (Daily Brief)**
- Generates briefing from active Main KB entries
- Groups by: Executive Summary, Synthesis Insights, High-Priority Entries, Updated Entries, Decay Recommendations
- Writes to Brief Log (Notion)

### Extract (parallel process)
- Polls Main KB for `Extract Content = checked`
- Extracts full content via Parallel API
- Writes as body blocks on the entry page
- Generates ~1000 word AI summary via `gpt-4o-mini`
- Writes to `AI Summary` property

---

## File Structure

```
PAI/
├── config.py              # Config loader (API keys, DB IDs, settings)
├── logger.py              # Structured logging setup
├── main.py                # CLI entry point + scheduler
├── notion_client.py       # Notion API wrapper
├── parallel_client.py     # Parallel Search/Extract API wrapper
├── openai_client.py       # OpenAI API wrapper (analysis + brief)
├── ingestion.py           # Stage 1: search + write to queue
├── reconciliation.py      # Stage 2: analyze + write to KB
├── curation.py            # Stage 3: daily brief generation
├── dedup.py               # Deduplication logic
├── escalation.py         # Email escalation for High signal
├── extract.py             # Extract full content + AI summary
├── scheduler.py           # APScheduler configuration
├── health.py              # Health check (6 service checks)
├── setup_notion.py        # One-time Notion DB setup
├── setup_strategic_context.py  # Seed Strategic Context DB
├── requirements.txt       # Python dependencies
├── .env                   # API keys + configuration
├── .env.example           # Template for .env
├── database_ids.json      # Notion database IDs (created by setup_notion.py)
├── state.json            # Cycle state tracking
├── search_config.json     # Search variant templates (configurable)
├── signal_examples.json  # Signal calibration examples
├── docker-compose.yml     # Docker deployment
├── Dockerfile             # Container build
└── ai_summary_plan.md    # MOD 07 implementation notes
```

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

**Required .env variables:**
```bash
NOTION_API_KEY=ntn_...
PARALLEL_API_KEY=...
OPENAI_API_KEY=sk-proj-...
LISTENING_DASHBOARD_PAGE_ID=...   # Parent page in Notion
PRIORITIES_PAGE_ID=...           # Current Priorities page
STRATEGIC_CONTEXT_DB_ID=...       # Strategic Context database ID
```

**Optional variables:**
```bash
TOPIC=Physical AI               # Monitoring topic (default: Physical AI)
PASS_B_LOOKBACK_DAYS=30          # Pass B date floor (default: 30)
SEARCH_CONFIG_PATH=search_config.json
EXTRA_EXCLUDE_DOMAINS=           # Comma-separated extra domains to block
```

### 3. Set up Notion databases

```bash
python setup_notion.py
```
Creates 4 databases: Main KB, Synthesis, Brief Log, Ingestion Queue

### 4. Set up Strategic Context (one-time)

```bash
python setup_strategic_context.py
```
Seeds the Strategic Context database with Framework, Entity, India Context, Noise Filter, and Signal Indicator entries.

### 5. Add to Notion manually

In **Main Knowledge Base**, add these properties:
- `AI Summary` (Text) — filled by extract.py
- `Extract Content` (Checkbox) — trigger extraction

In **Strategic Context** database, ensure properties:
- `Name` (Title)
- `Category` (Select: Framework, Entity, India Context, Noise Filter, Signal Indicator)
- `Content` (Text)
- `Not Using Anymore` (Checkbox)

---

## Usage

### Run a single cycle

```bash
python main.py 1          # Cycle 1 (06:30 schedule)
python main.py 2          # Cycle 2 (11:30 schedule)
python main.py 3          # Cycle 3 (17:30 schedule)
python main.py 4          # Cycle 4 (22:30 schedule)
```

### Run daily brief

```bash
python main.py brief
```

### Extract content from a URL

```bash
# Poll for checked entries
python main.py extract

# Continuous polling (for scheduler)
python main.py extract-watch
```

### Health check

```bash
python main.py health
# Shows: Notion API, Parallel API, OpenAI API, DB accessibility, entry counts
```

### Database counts

```bash
python main.py counts
# Shows: Main KB, Synthesis, Brief Log, Ingestion Queue entry counts
```

### Start scheduler

```bash
python main.py start
# Runs 24/7 with cycles at 06:30, 11:30, 17:30, 22:30 IST + brief at 23:00 + extract poll every 60s
```

### Test scheduler

```bash
python main.py test-scheduler
# Verifies APScheduler fires a test job after 1 minute
```

---

## Configuration Files

### `search_config.json`

Configures search variant templates. No code changes needed to add/remove/search angles.

```json
{
  "variants": [
    {
      "label": "breaking",
      "objective": "Breaking news published in the last 48 hours about {topic}...",
      "search_queries": ["{topic} news today", "..."],
      "enabled": true
    }
  ]
}
```

Placeholders: `{topic}` (from .env TOPIC), `{year}` (current year)

### `signal_examples.json`

Few-shot calibration examples for signal level assignment (High/Medium/Low).

```json
{
  "high": [{"title": "...", "reason": "..."}],
  "medium": [...],
  "low": [...]
}
```

Changes take effect on next cycle without restart.

---

## Mods (Enhancements Applied)

| Mod | Description |
|---|---|
| MOD 01 | Strategic Context — DB-driven context injected into AI prompts |
| MOD 02 | Search Configuration — JSON-configurable variant templates |
| MOD 03 | Source Quality Filtering — exclude low-quality domains/URLs |
| MOD 04 | Signal Calibration — few-shot examples for signal level calibration |
| MOD 05 | Recency Controls — date floors, dynamic year, recency-weighted prompts |
| MOD 06 | Result Uniqueness — distinct variants + progressive domain exclusion |
| MOD 07 | AI Summary on Extract — gpt-4o-mini summarizes extracted content |

---

## Docker Deployment

```bash
docker-compose up -d
```

The container runs `python main.py start` (scheduler mode). Logs persist to `./logs`.

---

## Cost Estimate

| Operation | Cost |
|---|---|
| Parallel Search (1 cycle, 10 variants) | ~$0.05 |
| Parallel Extract (per URL) | ~$0.001 |
| OpenAI Stage 2 analysis (per article) | ~$0.005 |
| OpenAI Daily Brief (gpt-4o) | ~$0.10 |
| OpenAI AI Summary (per article, gpt-4o-mini) | ~$0.005 |
| **4 cycles + brief per day** | **~$0.50** |

---

## Notion Database Schema

**Main Knowledge Base**
| Property | Type | Notes |
|---|---|---|
| Title | title | Article title |
| URL | url | Source URL |
| Signal Level | select | High / Medium / Low |
| Category | select | Competitor Move, Policy Change, Research, Funding... |
| One-Line Summary | rich_text | 1-sentence summary |
| Why It Matters | rich_text | Strategic significance |
| Key Entities | multi_select | Companies, people, technologies |
| Topic Tags | multi_select | Sub-topics |
| Framework Mapping | multi_select | Four Schools, GTM, Tech Stack... |
| Confidence Score | number | 0.0–1.0 |
| Discovered Date | date | |
| Published Date | date | |
| Half-Life Class | select | Policy / Research / Funding / Partnership / Discourse |
| Decay Status | select | Active / Aging / Archived |
| Dedup Status | select | New / Same / Updated |
| AI Summary | rich_text | ~1000 word summary (from extract) |
| Full Content | rich_text | "See page body" (after extract) |
| Extract Content | checkbox | Trigger extraction |

**Ingestion Queue** — pending analysis entries waiting for Stage 2 reconciliation

| Property | Type | Notes |
|---|---|---|
| Title | title | Article title |
| URL | url | Source URL |
| Source Name | rich_text | Publisher/outlet |
| Published Date | date | Article publication date |
| Discovered Date | date | When pipeline found this |
| Raw Summary | rich_text | Brief description from search |
| Retrieval Method | select | Time-window / Relevance-ranked / Both |
| Search Cycle | select | 1 / 2 / 3 / 4 |

**Brief Log** — generated daily briefings delivered to stakeholders

| Property | Type | Notes |
|---|---|---|
| Brief Title | title | "Daily Briefing — {date}" |
| Brief Date | date | Briefing date |
| Executive Summary | rich_text | 3-5 sentence overview |
| Entries Surfaced | relation | → Main KB entries surfaced |
| Syntheses Surfaced | relation | → Synthesis entries surfaced |
| Entries Archived | relation | → Main KB entries archived |
| Delivered At | date | Timestamp of delivery |

**Synthesis Database** — cross-entry strategic inferences and pattern detection

| Property | Type | Notes |
|---|---|---|
| Synthesis Title | title | Pattern or inference title |
| Linked Entries | relation | → Main KB entries this derives from |
| Inference | rich_text | Strategic conclusion drawn |
| Generated Date | date | When synthesis was created |
| Relevance Window | select | 1 Week / 2 Weeks / 1 Month / Ongoing |
| Surfaced In Brief | relation | → Brief Log entries this appeared in |

**Full Content Extracts** (MOD 07) — stores extracted article content for audit/reference

| Property | Type | Notes |
|---|---|---|
| Title | title | Article title |
| Source URL | url | Original article URL |
| Extracted At | date | When content was extracted |
| Source Domain | rich_text | Publisher domain |
| Word Count | number | Article word count |
| Status | select | Extracted / Failed / Skipped |
| Extracted By | select | Cycle 1 / Cycle 2 / Cycle 3 / Cycle 4 |

**Strategic Context** — Framework, Entity, India Context, Noise Filter, Signal Indicator definitions

| Property | Type | Notes |
|---|---|---|
| Name | title | Entry name (e.g., "Four Schools of Physical AI") |
| Category | select | Framework / Entity / India Context / Noise Filter / Signal Indicator |
| Content | rich_text | Detailed definition or description |
| Not Using Anymore | checkbox | Mark inactive entries |