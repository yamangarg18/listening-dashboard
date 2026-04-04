# CHUNK 5: Notion Read Page — Read Block Content from a Regular Page

## Objective
Add `read_page_content()` to `notion_client.py` — a function that reads the text content of a regular Notion page (not a database entry). This is how Stage 3 reads the "Current Priorities" document that guides context-aware surfacing.

## Dependencies
- Chunks 0–4 complete
- `notion_client.py` has all previous functions

## What this chunk adds to notion_client.py
- `read_page_content()` — public function

---

## NOTION API REFERENCE — RETRIEVE BLOCK CHILDREN

A Notion page's content is stored as a list of "blocks" — paragraphs, headings, lists, etc. To read a page's content, you retrieve its block children.

### Endpoint

```
GET https://api.notion.com/v1/blocks/{block_id}/children?page_size=100
```

The `block_id` is the page ID. Every page is also a block.

### Query Parameters

| Parameter | Type | Description |
|---|---|---|
| `page_size` | integer (1–100) | Max blocks per response. Default 100. |
| `start_cursor` | string | Pagination cursor from previous response. |

### Response (200 OK)

```json
{
  "object": "list",
  "results": [
    {
      "object": "block",
      "id": "block-id-xxxx",
      "type": "paragraph",
      "paragraph": {
        "rich_text": [
          {
            "type": "text",
            "text": {"content": "This is a paragraph."},
            "plain_text": "This is a paragraph."
          }
        ]
      }
    },
    {
      "object": "block",
      "id": "block-id-yyyy",
      "type": "heading_1",
      "heading_1": {
        "rich_text": [
          {
            "type": "text",
            "text": {"content": "Section Title"},
            "plain_text": "Section Title"
          }
        ]
      }
    },
    {
      "object": "block",
      "id": "block-id-zzzz",
      "type": "bulleted_list_item",
      "bulleted_list_item": {
        "rich_text": [
          {
            "type": "text",
            "text": {"content": "A bullet point."},
            "plain_text": "A bullet point."
          }
        ]
      }
    },
    {
      "object": "block",
      "id": "block-id-aaaa",
      "type": "numbered_list_item",
      "numbered_list_item": {
        "rich_text": [
          {
            "type": "text",
            "text": {"content": "A numbered item."},
            "plain_text": "A numbered item."
          }
        ]
      }
    },
    {
      "object": "block",
      "id": "block-id-bbbb",
      "type": "to_do",
      "to_do": {
        "rich_text": [
          {
            "type": "text",
            "text": {"content": "A to-do item."},
            "plain_text": "A to-do item."
          }
        ],
        "checked": false
      }
    },
    {
      "object": "block",
      "id": "block-id-cccc",
      "type": "divider",
      "divider": {}
    }
  ],
  "has_more": false,
  "next_cursor": null
}
```

### Block Types and How to Extract Text

The pattern is consistent: `block[block_type]["rich_text"]` contains an array of text objects with `plain_text` fields.

| Block Type | Key | Has rich_text? | Notes |
|---|---|---|---|
| `paragraph` | `paragraph` | Yes | Regular text |
| `heading_1` | `heading_1` | Yes | Large heading |
| `heading_2` | `heading_2` | Yes | Medium heading |
| `heading_3` | `heading_3` | Yes | Small heading |
| `bulleted_list_item` | `bulleted_list_item` | Yes | Bullet point |
| `numbered_list_item` | `numbered_list_item` | Yes | Numbered item |
| `to_do` | `to_do` | Yes | Checkbox item (also has `checked` bool) |
| `toggle` | `toggle` | Yes | Collapsible block |
| `quote` | `quote` | Yes | Blockquote |
| `callout` | `callout` | Yes | Callout box (also has `icon`) |
| `code` | `code` | Yes | Code block (also has `language`) |
| `divider` | `divider` | No | Horizontal rule, no text |
| `image` | `image` | No | Image, no extractable text |
| `bookmark` | `bookmark` | No | Has `url` but no rich_text |
| `child_page` | `child_page` | No | Has `title` string only |
| `child_database` | `child_database` | No | Has `title` string only |
| `table_of_contents` | `table_of_contents` | No | No text |
| `breadcrumb` | `breadcrumb` | No | No text |
| `column_list` | `column_list` | No | Container, has children |
| `column` | `column` | No | Container, has children |

### Extracting text from a block

```python
def _extract_block_text(block: dict) -> str | None:
    block_type = block["type"]
    block_data = block.get(block_type, {})
    
    # Most text blocks have rich_text
    rich_text = block_data.get("rich_text", None)
    if rich_text is not None:
        return "".join([t["plain_text"] for t in rich_text])
    
    # Some blocks have no text
    return None
```

### Pagination

Same pattern as database queries. If `has_more` is `true`, make another GET request with `start_cursor` query parameter set to `next_cursor`. Repeat until `has_more` is `false`.

### Error Responses

| Status | Code | Meaning |
|---|---|---|
| 400 | `validation_error` | Invalid block/page ID |
| 401 | `unauthorized` | Bad API key |
| 404 | `object_not_found` | Page doesn't exist or not shared with integration |
| 429 | `rate_limited` | Too many requests |

---

## IMPLEMENTATION SPEC

### Add to `notion_client.py`:

#### `read_page_content(page_id: str) -> str`

```python
def read_page_content(page_id: str) -> str:
    """
    Read the text content of a Notion page.
    
    Retrieves all blocks from the page and extracts their text content
    into a single plain-text string. Headings are prefixed with '#'.
    List items are prefixed with '- ' or '1. '.
    
    This is used to read the "Current Priorities" document for Stage 3.
    
    Args:
        page_id: UUID of the page to read
    
    Returns:
        Plain text string of the page content. Blocks are separated
        by newlines. Empty blocks are skipped.
        Returns empty string if the page has no content.
    
    Raises:
        Exception: If the Notion API returns an error.
    
    Example:
        content = read_page_content("xxxx-xxxx-xxxx")
        print(content)
        # Output:
        # # Current Priorities
        # 
        # ## Active Workstreams
        # - Preparing Sanjay Lodha briefing
        # - Refining GTM framework for School 1
        # 
        # Focus this week is on...
    """
```

Implementation requirements:
- Send `GET /v1/blocks/{page_id}/children?page_size=100`
- Handle pagination (loop until `has_more` is `false`)
- For each block, extract text based on its type:
  - `heading_1` → prefix with `# `
  - `heading_2` → prefix with `## `
  - `heading_3` → prefix with `### `
  - `paragraph` → text as-is
  - `bulleted_list_item` → prefix with `- `
  - `numbered_list_item` → prefix with `- ` (use dash, don't try to track numbering)
  - `to_do` → prefix with `[x] ` if checked, `[ ] ` if unchecked
  - `quote` → prefix with `> `
  - `callout` → text as-is
  - `code` → wrap with backticks or include as-is
  - `divider` → insert `---`
  - All other types (image, bookmark, child_page, etc.) → skip silently
- Join all extracted lines with `\n`
- Strip trailing whitespace
- Log the page ID and number of blocks read
- Use tenacity retry decorator for 429 and 5xx errors
- Add `time.sleep(0.35)` between pagination requests

**NOTE:** This function reads only top-level blocks. Nested blocks (e.g., text inside a toggle, items inside a column) require recursive retrieval (fetching children of each block that has `has_children: true`). For the priorities document, top-level content is sufficient. Do NOT implement recursive block fetching — it adds complexity and API calls that aren't needed.

---

## TEST SETUP — MANUAL STEP REQUIRED

Before running the tests, you need to create a test page in Notion:

1. Open Notion → go to "Listening Dashboard"
2. Click `+ New page` inside the Listening Dashboard page (NOT inside a database — a regular sub-page)
3. Title it: **Current Priorities**
4. Add this content to the page:

```
# Active Workstreams

- Preparing Physical AI India report v2
- Refining GTM framework for School 1
- Tracking NVIDIA ecosystem developments

## Focus This Week

The primary focus is on finalizing the 33-industry taxonomy and mapping it against the tech stack layers. Secondary priority is monitoring funding rounds in the India robotics ecosystem.

## Key Meetings

- Sanjay Lodha briefing on April 7
- EF application deadline April 10

---

Notes: Keep an eye on any DPIIT policy announcements related to robotics manufacturing.
```

5. Share this page with your integration (it should already be shared if it's inside Listening Dashboard, but verify)
6. Copy the page ID from the URL

7. Add this to your `.env` file:
```
PRIORITIES_PAGE_ID=your-priorities-page-id-here
```

8. Add this to `config.py` (OpenCode should do this):
```python
PRIORITIES_PAGE_ID = os.getenv("PRIORITIES_PAGE_ID")
```

And add to `validate_config()` — but as an OPTIONAL check, not required. Stage 3 needs it but earlier chunks don't:
```python
# Optional: only needed for Stage 3
if not os.getenv("PRIORITIES_PAGE_ID"):
    errors.append("PRIORITIES_PAGE_ID is not set in .env (needed for Stage 3)")
```

Also add to `.env.example`:
```
PRIORITIES_PAGE_ID=your-priorities-page-id-here
```

---

## TEST BLOCK

Replace the existing `if __name__ == "__main__":` block in `notion_client.py` with:

```python
if __name__ == "__main__":
    from config import PRIORITIES_PAGE_ID
    
    if not PRIORITIES_PAGE_ID:
        print("PRIORITIES_PAGE_ID not set in .env")
        print("Create a 'Current Priorities' page in Notion, add content,")
        print("and set PRIORITIES_PAGE_ID in .env to the page ID.")
        exit(1)
    
    print(f"Reading page: {PRIORITIES_PAGE_ID}")
    content = read_page_content(PRIORITIES_PAGE_ID)
    
    print(f"\n{'='*60}")
    print("PAGE CONTENT:")
    print(f"{'='*60}")
    print(content)
    print(f"{'='*60}")
    print(f"\nTotal length: {len(content)} characters")
    print(f"Total lines: {len(content.splitlines())}")
```

---

## EDGE CASES

### Empty page
A page with no content returns `{"results": [], "has_more": false}`. The function should return an empty string.

### Page with only images/embeds
If every block is an image or embed with no text, the function returns an empty string. This is correct — we only care about text content.

### Very long page
If the page has more than 100 blocks, pagination handles it. Unlikely for a priorities document, but the function must handle it.

### Blocks with empty rich_text
Some blocks have `"rich_text": []` (empty paragraph). Skip these — don't add blank lines for empty paragraphs.

### Bold/italic/code formatting within text
The `plain_text` field strips all formatting. "**bold text**" becomes "bold text". This is the correct behavior — we want plain text for the OpenAI prompt.

### Page not shared with integration
Returns 404. The error message from `_handle_response()` will say "object_not_found". The test setup instructions tell the user to share the page.

### Nested content (toggles, columns)
Not handled. The function only reads top-level blocks. Content inside toggles or columns is invisible to this function. The priorities document should use flat structure only — no toggles.