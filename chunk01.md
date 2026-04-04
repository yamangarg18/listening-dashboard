# CHUNK 1: Create Notion Databases via API

## Objective
Build `setup_notion.py` — a script that creates all four Notion databases (Ingestion Queue, Main Knowledge Base, Synthesis DB, Brief Log) as children of the "Listening Dashboard" page, with every property pre-configured. Run once. Outputs database IDs to `database_ids.json`.

## Dependencies
- Chunk 0 must be complete (config.py, logger.py, .env with NOTION_API_KEY and LISTENING_DASHBOARD_PAGE_ID)

---

## NOTION API REFERENCE — EVERYTHING OPENCODE NEEDS

### Authentication

Every request to the Notion API must include these headers:

```
Authorization: Bearer {NOTION_API_KEY}
Content-Type: application/json
Notion-Version: 2022-06-28
```

The `Notion-Version` header is mandatory. Use `2022-06-28` — this is stable and widely supported. Newer versions (like `2025-09-03`) introduced "data sources" as a concept, but `2022-06-28` uses the simpler `database_id` pattern throughout. **Stick with `2022-06-28`.**

### Rate Limits

Notion allows **3 requests per second** per integration token. If you exceed this, you get a `429` response with a `Retry-After` header (integer, seconds). The setup script creates 4 databases, so rate limiting won't be an issue here — but later chunks that write many pages need to respect this.

### Base URL

```
https://api.notion.com/v1
```

---

### ENDPOINT: Create a Database

```
POST https://api.notion.com/v1/databases
```

**Request body:**

```json
{
  "parent": {
    "type": "page_id",
    "page_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
  },
  "title": [
    {
      "type": "text",
      "text": {
        "content": "Database Title"
      }
    }
  ],
  "properties": {
    "Property Name": {
      "property_type_key": { ...config... }
    }
  }
}
```

**Response (200 OK):**

```json
{
  "object": "database",
  "id": "bc1211ca-e3f1-4939-ae34-5260b16f627c",
  "created_time": "2021-07-08T23:50:00.000Z",
  "last_edited_time": "2021-07-08T23:50:00.000Z",
  "title": [...],
  "properties": {
    "Property Name": {
      "id": "PNEQ",
      "type": "property_type",
      ...
    }
  }
}
```

**The `id` field in the response is the database ID you need to save.**

**Error responses:**

| Status | Code | Meaning |
|--------|------|---------|
| 400 | `validation_error` | Invalid property config, missing title, bad parent ID |
| 401 | `unauthorized` | Bad API key |
| 403 | `restricted_resource` | Integration not shared with the parent page |
| 404 | `object_not_found` | Parent page ID doesn't exist |
| 429 | `rate_limited` | Too many requests. Check `Retry-After` header |

---

### PROPERTY TYPE DEFINITIONS

When creating a database, the `properties` object defines the columns. Each key is the property name (string), and the value is an object describing its type and optional config.

**CRITICAL RULE:** Every database must have exactly ONE property with type `"title"`. This is the primary column. You cannot have zero or more than one.

Below is the exact JSON format for every property type used in this project:

#### Title (required, exactly one per database)

```json
"Entry Title": {
  "title": {}
}
```

#### Rich Text

```json
"One-Line Summary": {
  "rich_text": {}
}
```

#### URL

```json
"URL": {
  "url": {}
}
```

#### Number

```json
"Confidence Score": {
  "number": {
    "format": "number"
  }
}
```

Valid number formats: `"number"`, `"number_with_commas"`, `"percent"`, `"dollar"`, `"canadian_dollar"`, `"euro"`, `"pound"`, `"yen"`, `"ruble"`, `"rupee"`, `"won"`, `"yuan"`, `"real"`, `"lira"`, `"swiss_franc"`, `"singapore_dollar"`, etc. For scores 0-100, use `"number"`. For currency, use the appropriate format.

#### Select

```json
"Signal Level": {
  "select": {
    "options": [
      {"name": "High", "color": "red"},
      {"name": "Medium", "color": "yellow"},
      {"name": "Low", "color": "green"}
    ]
  }
}
```

Valid colors: `"default"`, `"gray"`, `"brown"`, `"orange"`, `"yellow"`, `"green"`, `"blue"`, `"purple"`, `"pink"`, `"red"`.

#### Multi-Select

```json
"Topic Tags": {
  "multi_select": {
    "options": [
      {"name": "Robotics", "color": "blue"},
      {"name": "Policy", "color": "purple"},
      {"name": "Funding", "color": "green"}
    ]
  }
}
```

Same color options as Select. You can pre-define options, but Notion also auto-creates new options when a page is created with a value that doesn't exist yet. So you don't need to pre-define every possible tag — just seed with common ones.

#### Date

```json
"Published Date": {
  "date": {}
}
```

No additional config needed. When writing page values, dates use ISO 8601 format: `"2026-04-03"` or `"2026-04-03T14:30:00.000+05:30"`.

#### Checkbox

```json
"Seen By User": {
  "checkbox": {}
}
```

#### Relation

```json
"Synthesis Group": {
  "relation": {
    "database_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    "single_property": {}
  }
}
```

**IMPORTANT:** Relations require the `database_id` of the related database. This means you must create databases in the right order — you can't reference a database that doesn't exist yet. The setup script must:
1. Create Main Knowledge Base first
2. Create Synthesis DB second (it needs Main KB's ID for the `Linked Entries` relation)
3. Create Brief Log third (it needs Main KB's ID and Synthesis DB's ID for relations)
4. Create Ingestion Queue last (no relations needed)

The `single_property` variant creates a one-way relation. For two-way relations, use `"dual_property": {}` instead — this auto-creates a corresponding relation property in the related database. **Use `single_property` for this project** to keep things simple and avoid auto-created columns cluttering the related databases.

---

## DATABASE SCHEMAS

### Database 1: Main Knowledge Base

Parent: Listening Dashboard page

| Property Name | Type | Config | Purpose |
|---|---|---|---|
| Title | title | — | Entry title / headline |
| URL | url | — | Canonical link to the content |
| Source Name | select | seed: Reuters, Bloomberg, TechCrunch, Economic Times, SCMP, arXiv, LinkedIn, X, Reddit, Hacker News, Other | Publication or platform |
| Source Type | select | options: News, Blog, Academic, Social Media, Forum, Government, Other | Category of source |
| Author | rich_text | — | Author name if available |
| Published Date | date | — | When content was published |
| Discovered Date | date | — | When system first found it |
| Last Updated | date | — | When Stage 2 last touched this entry |
| Retrieval Method | select | options: Time-window, Relevance-ranked, Both | Which search pass found it |
| Search Cycle | select | options: 1, 2, 3, 4 | Which daily cycle found it |
| Raw Summary | rich_text | — | Parallel's extracted snippet |
| One-Line Summary | rich_text | — | Stage 2 model's distilled sentence |
| Why It Matters | rich_text | — | Strategic relevance assessment |
| Key Entities | multi_select | seed: leave empty (auto-populated by model) | Companies, people, technologies, countries |
| Topic Tags | multi_select | seed: leave empty (auto-populated by model) | Sub-topics |
| Signal Level | select | options: High, Medium, Low | Urgency/importance |
| Confidence Score | number | format: number | 0-1 confidence in signal assessment |
| Category | select | options: Competitor Move, Policy Change, Research, Funding, Partnership, Discourse, Other | Type of development |
| Framework Mapping | multi_select | seed: Four Schools, GTM, Tech Stack, Taxonomy | Strategic frameworks |
| Priority Score | number | format: number | 0-100 contextual ranking |
| Decay Status | select | options: Active, Aging, Archived | Lifecycle stage |
| Half-Life Class | select | options: Policy, Research, Funding, Partnership, Discourse | Decay rate category |
| Seen By User | checkbox | — | Whether this appeared in a brief |
| Archived Summary | rich_text | — | Compressed one-liner when archived |
| Change Log | rich_text | — | What changed and why on each update |
| Dedup Status | select | options: New, Updated, Duplicate | Stage 2 deduplication result |
| Extract Content | checkbox | — | Check to trigger Extract API (Chunk 17) |
| Full Content | rich_text | — | Extracted full page content |

### Database 2: Synthesis Database

Parent: Listening Dashboard page

| Property Name | Type | Config | Purpose |
|---|---|---|---|
| Synthesis Title | title | — | Short description of the insight |
| Linked Entries | relation | database_id: Main KB ID, single_property | Contributing entries |
| Inference | rich_text | — | Written strategic implication |
| Generated Date | date | — | When synthesis was produced |
| Relevance Window | select | options: 1 Week, 2 Weeks, 1 Month, Ongoing | How long this stays active |
| Surfaced In Brief | relation | database_id: Brief Log ID, single_property | Which brief included this |

**NOTE:** The `Surfaced In Brief` relation requires Brief Log's ID. But Brief Log also has a relation back to Synthesis DB. This is a circular dependency. **Solution:** Create Synthesis DB first WITHOUT the `Surfaced In Brief` property. Create Brief Log. Then update Synthesis DB to add the `Surfaced In Brief` relation using the Update Database endpoint (see below).

### Database 3: Brief Log

Parent: Listening Dashboard page

| Property Name | Type | Config | Purpose |
|---|---|---|---|
| Brief Title | title | — | E.g., "Daily Brief — 2026-04-03" |
| Brief Date | date | — | Date of the brief |
| Executive Summary | rich_text | — | 2-3 line top-level takeaway |
| Entries Surfaced | relation | database_id: Main KB ID, single_property | Entries included |
| Syntheses Surfaced | relation | database_id: Synthesis DB ID, single_property | Synthesis insights included |
| Entries Archived | relation | database_id: Main KB ID, single_property | Entries that aged out |
| Delivered At | date | — | Timestamp of delivery |

### Database 4: Ingestion Queue

Parent: Listening Dashboard page

| Property Name | Type | Config | Purpose |
|---|---|---|---|
| Title | title | — | Headline of discovered content |
| URL | url | — | Canonical link |
| Source Name | rich_text | — | Publication or platform |
| Published Date | date | — | When content was published |
| Discovered Date | date | — | When system found it |
| Raw Summary | rich_text | — | Parallel's snippet |
| Retrieval Method | select | options: Time-window, Relevance-ranked, Both | Which pass found it |
| Search Cycle | select | options: 1, 2, 3, 4 | Which cycle |

---

## ENDPOINT: Update a Database (for adding properties after creation)

Needed to add the `Surfaced In Brief` relation to Synthesis DB after Brief Log is created.

```
PATCH https://api.notion.com/v1/databases/{database_id}
```

**Request body (to add a new property):**

```json
{
  "properties": {
    "Surfaced In Brief": {
      "relation": {
        "database_id": "brief_log_database_id_here",
        "single_property": {}
      }
    }
  }
}
```

**Response:** Returns the updated database object (same shape as Create response).

**You can only add or modify properties with this endpoint. To delete a property, set its value to `null`:**

```json
{
  "properties": {
    "Property To Delete": null
  }
}
```

---

## IMPLEMENTATION SPEC

### File: `setup_notion.py`

```python
"""
One-time setup script.
Creates all 4 Notion databases under the Listening Dashboard page.
Saves database IDs to database_ids.json.

Usage:
    python setup_notion.py

Prerequisites:
    - .env file with NOTION_API_KEY and LISTENING_DASHBOARD_PAGE_ID
    - The Listening Dashboard page must be shared with the integration
"""
```

### Functions to implement:

#### `create_database(page_id: str, title: str, properties: dict) -> str`

- Sends `POST /v1/databases` with the given parent page_id, title, and properties
- Returns the database ID from the response
- Raises an exception with the full error body if the request fails
- Logs the database name and ID on success

#### `update_database(database_id: str, properties: dict) -> None`

- Sends `PATCH /v1/databases/{database_id}` with the given properties
- Used to add the `Surfaced In Brief` relation to Synthesis DB after Brief Log is created
- Logs success or raises exception on failure

#### `build_main_kb_properties() -> dict`

- Returns the full properties dict for Main Knowledge Base
- Every property defined exactly as specified in the schema above

#### `build_synthesis_properties(main_kb_id: str) -> dict`

- Returns properties dict for Synthesis DB
- Includes the `Linked Entries` relation pointing to `main_kb_id`
- Does NOT include `Surfaced In Brief` (added later via update)

#### `build_brief_log_properties(main_kb_id: str, synthesis_id: str) -> dict`

- Returns properties dict for Brief Log
- Includes relations to both Main KB and Synthesis DB

#### `build_ingestion_queue_properties() -> dict`

- Returns properties dict for Ingestion Queue
- No relations

#### `main()`

- Validates config (NOTION_API_KEY and PAGE_ID must be set)
- Checks if `database_ids.json` already exists — if yes, asks for confirmation before overwriting (prevents accidental duplicate databases)
- Creates databases in order:
  1. Main Knowledge Base → saves ID
  2. Synthesis DB (with Linked Entries relation to Main KB) → saves ID
  3. Brief Log (with relations to Main KB and Synthesis DB) → saves ID
  4. Update Synthesis DB to add `Surfaced In Brief` relation to Brief Log
  5. Ingestion Queue → saves ID
- Saves all 4 IDs to `database_ids.json`:
  ```json
  {
    "main_kb": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    "synthesis": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    "brief_log": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    "ingestion_queue": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
  }
  ```
- Logs a summary of all created databases with their IDs

### HTTP client setup:

```python
import httpx
from config import NOTION_API_KEY, NOTION_API_VERSION, NOTION_BASE_URL

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": NOTION_API_VERSION,
}

# Use a timeout of 30 seconds for all Notion API calls
client = httpx.Client(
    base_url=NOTION_BASE_URL,
    headers=HEADERS,
    timeout=30.0,
)
```

### Error handling pattern:

```python
response = client.post("/databases", json=payload)

if response.status_code != 200:
    error_body = response.json()
    error_code = error_body.get("code", "unknown")
    error_message = error_body.get("message", "No message")
    raise Exception(
        f"Notion API error {response.status_code}: "
        f"[{error_code}] {error_message}"
    )

database_id = response.json()["id"]
```

---

## COMPLETE EXAMPLE: Creating a database with multiple property types

This is a full working example showing the exact JSON format Notion expects. Use this as a reference for building the property dicts:

```python
payload = {
    "parent": {
        "type": "page_id",
        "page_id": "98ad959b-2b6a-4774-80ee-00246fb0ea9b"
    },
    "title": [
        {
            "type": "text",
            "text": {
                "content": "Main Knowledge Base"
            }
        }
    ],
    "properties": {
        "Title": {
            "title": {}
        },
        "URL": {
            "url": {}
        },
        "Source Type": {
            "select": {
                "options": [
                    {"name": "News", "color": "blue"},
                    {"name": "Blog", "color": "green"},
                    {"name": "Academic", "color": "purple"},
                    {"name": "Social Media", "color": "pink"},
                    {"name": "Forum", "color": "orange"},
                    {"name": "Government", "color": "red"},
                    {"name": "Other", "color": "gray"}
                ]
            }
        },
        "Published Date": {
            "date": {}
        },
        "Signal Level": {
            "select": {
                "options": [
                    {"name": "High", "color": "red"},
                    {"name": "Medium", "color": "yellow"},
                    {"name": "Low", "color": "green"}
                ]
            }
        },
        "Confidence Score": {
            "number": {
                "format": "number"
            }
        },
        "Topic Tags": {
            "multi_select": {
                "options": []
            }
        },
        "Seen By User": {
            "checkbox": {}
        },
        "One-Line Summary": {
            "rich_text": {}
        },
        "Related Entries": {
            "relation": {
                "database_id": "some-other-database-id-here",
                "single_property": {}
            }
        }
    }
}

response = client.post("/databases", json=payload)
```

---

## TESTING CHECKPOINT

After OpenCode builds `setup_notion.py`:

### Test 1: Dry run validation
```bash
python setup_notion.py
```
Before creating anything, the script should:
- Print "Checking config..." and confirm NOTION_API_KEY and PAGE_ID are present
- Check if `database_ids.json` exists (it shouldn't on first run)
- Print "Creating databases..." and proceed

### Test 2: Verify databases in Notion
After the script runs successfully:
1. Open your "Listening Dashboard" page in Notion
2. You should see 4 new databases appear as sub-pages:
   - Ingestion Queue
   - Main Knowledge Base
   - Synthesis Database
   - Brief Log
3. Click into each one and verify:
   - **Main KB**: Open the properties panel (click `+` next to the last column header). All 27 properties should be listed with correct types.
   - **Synthesis DB**: Should have 6 properties including `Linked Entries` (relation to Main KB) and `Surfaced In Brief` (relation to Brief Log)
   - **Brief Log**: Should have 7 properties including relations to Main KB and Synthesis DB
   - **Ingestion Queue**: Should have 8 properties, no relations

### Test 3: Verify database_ids.json
```bash
cat database_ids.json
```
Should contain 4 UUIDs:
```json
{
  "main_kb": "...",
  "synthesis": "...",
  "brief_log": "...",
  "ingestion_queue": "..."
}
```

### Test 4: Re-run safety
```bash
python setup_notion.py
```
Running again should warn that `database_ids.json` already exists and ask for confirmation before creating duplicate databases.

### Test 5: Config validation
Remove `NOTION_API_KEY` from `.env` and run:
```bash
python setup_notion.py
```
Should print a clear error: "NOTION_API_KEY is not set in .env" and exit without making any API calls.

---

## EDGE CASES

### Parent page not shared with integration
**Symptom:** 403 error with code `restricted_resource`
**Message to show:** "The Listening Dashboard page is not shared with your integration. Open the page in Notion → ••• menu → Add connections → select your integration."

### Invalid page ID format
**Symptom:** 400 error with code `validation_error`
**Message to show:** "LISTENING_DASHBOARD_PAGE_ID in .env is not a valid UUID. It should look like: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

### Page ID doesn't exist
**Symptom:** 404 error with code `object_not_found`
**Message to show:** "No Notion page found with ID {page_id}. Check LISTENING_DASHBOARD_PAGE_ID in .env."

### Database already exists (re-run)
The Notion API does not check for duplicate database names. Running the script twice creates duplicate databases. The script must check for `database_ids.json` and warn the user.

### Property name with special characters
Notion property names are case-sensitive strings. "Signal Level" and "signal level" are different properties. **Use exact casing as defined in the schemas above.** Do not use leading/trailing spaces in property names.

### Relation database_id format
The `database_id` in a relation property must be a UUID string with hyphens: `"xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"`. Notion returns IDs in this format from the Create Database response, so just use the `id` field directly.

### Multi-select with empty options
Setting `"options": []` for multi_select is valid. Notion will auto-create options when pages are written with new values. This is the correct approach for Key Entities and Topic Tags, which are populated dynamically by the model.

### Rate limiting during setup
Creating 4 databases + 1 update = 5 API calls. At 3 req/sec, this completes in under 2 seconds. No rate limiting concerns. But add a `time.sleep(0.35)` between calls as a safety margin.