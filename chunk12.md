# CHUNK 12: Escalation Email

## Objective
Build `escalation.py` — a module that sends an immediate email alert when Stage 2 detects a high-signal entry. High-signal entries (major funding, policy changes, competitor launches) shouldn't wait for the daily brief — they get flagged immediately.

## Dependencies
- Chunk 0: config.py with SMTP settings
- Chunk 11: reconciliation.py (will call escalation after processing)

## What this chunk creates
- `escalation.py` — new file

---

## DESIGN

### When escalation triggers

After Stage 2 creates or updates an entry in the Main KB with `Signal Level = "High"`, it passes that entry to the escalation module. The module sends an email with the entry's title, one-line summary, why it matters, URL, and category.

### What the email looks like

```
Subject: 🔴 HIGH SIGNAL: NVIDIA Launches New Isaac Platform for Robotics

---
HIGH SIGNAL ALERT — Physical AI
---

Title: NVIDIA Launches New Isaac Platform for Robotics
Category: Competitor Move
Signal Level: High
Confidence: 0.92

Summary:
NVIDIA launched Isaac, a comprehensive platform for developing 
and deploying AI-powered robots.

Why It Matters:
This positions NVIDIA as the dominant platform provider for 
Physical AI development, directly impacting the tech stack 
analysis and School 1 GTM framework.

Source: nvidia.com
Published: 2026-04-01
URL: https://nvidia.com/isaac-launch

---
Listening Pipeline — Automated Alert
```

### SMTP Configuration

The pipeline uses standard SMTP to send email. Gmail is the default but any SMTP provider works.

**For Gmail:** You need an App Password, not your regular password:
1. Go to myaccount.google.com → Security → 2-Step Verification (must be enabled)
2. At the bottom, click "App passwords"
3. Generate one for "Mail" → "Other (Custom name)" → "Listening Pipeline"
4. Use that 16-character password as `SMTP_PASSWORD` in `.env`

---

## PYTHON SMTP REFERENCE

```python
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def send_email(subject: str, body: str, to_email: str,
               smtp_host: str, smtp_port: int, 
               smtp_user: str, smtp_password: str):
    
    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = to_email
    msg["Subject"] = subject
    
    msg.attach(MIMEText(body, "plain", "utf-8"))
    
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()  # Upgrade to TLS
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
```

### Key points:
- `smtplib` is in Python's standard library — no pip install needed
- `email.mime` is also standard library
- Use `SMTP` (not `SMTP_SSL`) with `starttls()` for port 587
- Use `SMTP_SSL` for port 465
- Gmail, Outlook, Yahoo all support port 587 with STARTTLS
- Timeout: default is no timeout. Set `timeout=30` in the SMTP constructor.

### Error handling:
| Error | Cause |
|---|---|
| `smtplib.SMTPAuthenticationError` | Wrong username/password or app password not set up |
| `smtplib.SMTPConnectError` | Can't reach SMTP server (network issue) |
| `smtplib.SMTPRecipientsRefused` | Invalid recipient email |
| `socket.timeout` | Server didn't respond in time |
| `ConnectionRefusedError` | Wrong host/port |

---

## IMPLEMENTATION SPEC

### File: `escalation.py`

```python
"""
Escalation module.
Sends immediate email alerts for high-signal entries.
"""
```

### Functions to implement:

#### `send_escalation_email(entry: dict) -> bool`

```python
def send_escalation_email(entry: dict) -> bool:
    """
    Send an email alert for a high-signal entry.
    
    Args:
        entry: Dict with entry details. Expected keys:
            - "title": str
            - "one_line_summary": str
            - "why_it_matters": str
            - "url": str
            - "category": str
            - "signal_level": str
            - "confidence_score": float
            - "source_name": str (optional)
            - "publish_date": str (optional)
    
    Returns:
        True if email was sent successfully, False if it failed.
        Does NOT raise exceptions — failures are logged and returned
        as False. Email failures should never crash the pipeline.
    
    Example:
        success = send_escalation_email({
            "title": "NVIDIA Launches New Isaac Platform",
            "one_line_summary": "NVIDIA launched Isaac...",
            "why_it_matters": "Positions NVIDIA as...",
            "url": "https://nvidia.com/isaac-launch",
            "category": "Competitor Move",
            "signal_level": "High",
            "confidence_score": 0.92,
            "source_name": "nvidia.com",
            "publish_date": "2026-04-01",
        })
    """
```

Implementation requirements:
- Read SMTP config from `config.py`: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `ESCALATION_TO_EMAIL`, `TOPIC`
- Check that all SMTP settings are configured. If any are missing, log a warning and return False (don't crash).
- Build the email subject: `f"🔴 HIGH SIGNAL: {entry['title'][:80]}"`
- Build the email body using the template shown in the design section above
- Send via SMTP with a 30-second timeout
- Log success: `"Escalation email sent: {title}"`
- On any exception, log the error and return False
- Never raise — email failures should not crash the pipeline

#### `check_and_escalate(entries_with_analyses: list[dict]) -> int`

```python
def check_and_escalate(entries_with_analyses: list[dict]) -> int:
    """
    Check a list of analyzed entries and send escalation emails
    for any with Signal Level = "High".
    
    Args:
        entries_with_analyses: List of dicts, each with both the
            queue entry data and the OpenAI analysis merged together.
            Must have at least: "title", "signal_level", "one_line_summary",
            "why_it_matters", "url", "category", "confidence_score"
    
    Returns:
        Number of escalation emails sent successfully.
    
    Example:
        # Called from reconciliation.py after analyzing entries
        count = check_and_escalate(analyzed_entries)
        logger.info(f"Sent {count} escalation emails")
    """
```

Implementation:
- Filter entries where `signal_level == "High"`
- For each high-signal entry, call `send_escalation_email()`
- Log how many high-signal entries found and how many emails sent
- Return the count of successfully sent emails

#### `_build_email_body(entry: dict, topic: str) -> str`

Private helper that formats the email body.

```python
def _build_email_body(entry: dict, topic: str) -> str:
    """Format the email body from entry data."""
    return f"""
---
HIGH SIGNAL ALERT — {topic}
---

Title: {entry.get('title', 'Unknown')}
Category: {entry.get('category', 'Unknown')}
Signal Level: {entry.get('signal_level', 'Unknown')}
Confidence: {entry.get('confidence_score', 'N/A')}

Summary:
{entry.get('one_line_summary', 'No summary available.')}

Why It Matters:
{entry.get('why_it_matters', 'No assessment available.')}

Source: {entry.get('source_name', 'Unknown')}
Published: {entry.get('publish_date', 'Unknown')}
URL: {entry.get('url', 'No URL')}

---
Listening Pipeline — Automated Alert
""".strip()
```

---

## INTEGRATION WITH RECONCILIATION (Chunk 11)

After this chunk is built, `reconciliation.py` needs a small update to call escalation after processing entries. This integration will be done by telling OpenCode to add a few lines to `run_reconciliation()`:

After Step 6 (processing entries), before Step 7 (archiving):

```python
from escalation import check_and_escalate

# Build the list of entries with analyses for escalation check
entries_for_escalation = []
for queue_entry, analysis in successfully_processed_pairs:
    merged = {**analysis}
    merged["url"] = queue_entry.get("URL", "")
    merged["source_name"] = queue_entry.get("Source Name", "")
    merged["publish_date"] = queue_entry.get("Published Date")
    entries_for_escalation.append(merged)

escalation_count = check_and_escalate(entries_for_escalation)
```

**OpenCode should add this integration to reconciliation.py as part of this chunk.**

---

## .env UPDATES

The SMTP fields were already in `.env.example` from Chunk 0. The user needs to fill them in with real values:

```bash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_16_char_app_password
ESCALATION_TO_EMAIL=your_email@gmail.com
```

`SMTP_USER` and `ESCALATION_TO_EMAIL` can be the same email — you're sending alerts to yourself.

---

## TEST BLOCK

```python
if __name__ == "__main__":
    from config import SMTP_HOST, SMTP_USER, SMTP_PASSWORD, ESCALATION_TO_EMAIL
    
    # --- Check SMTP config ---
    print("Checking SMTP configuration...")
    missing = []
    if not SMTP_HOST: missing.append("SMTP_HOST")
    if not SMTP_USER: missing.append("SMTP_USER")
    if not SMTP_PASSWORD: missing.append("SMTP_PASSWORD")
    if not ESCALATION_TO_EMAIL: missing.append("ESCALATION_TO_EMAIL")
    
    if missing:
        print(f"Missing SMTP config: {missing}")
        print("Set these in .env to test email sending.")
        print("\nTesting email body building only...\n")
    
    # --- Test 1: Build email body ---
    print("Test 1: Build email body...")
    test_entry = {
        "title": "TEST: Physical AI Startup Raises $50M Series B",
        "one_line_summary": "A stealth Physical AI startup raised $50M in Series B funding.",
        "why_it_matters": "Signals growing investor confidence in Physical AI commercialization.",
        "url": "https://techcrunch.com/physical-ai-series-b",
        "category": "Funding",
        "signal_level": "High",
        "confidence_score": 0.92,
        "source_name": "techcrunch.com",
        "publish_date": "2026-04-02",
    }
    
    body = _build_email_body(test_entry, "Physical AI")
    print(body)
    print("\n  Email body: PASSED")
    
    # --- Test 2: check_and_escalate with mixed signals ---
    print("\nTest 2: check_and_escalate filtering...")
    mixed_entries = [
        {**test_entry, "signal_level": "High"},
        {**test_entry, "title": "Minor Update", "signal_level": "Low"},
        {**test_entry, "title": "Medium News", "signal_level": "Medium"},
        {**test_entry, "title": "Another High Signal", "signal_level": "High"},
    ]
    
    if not missing:
        print("  Sending test emails (2 high-signal entries)...")
        count = check_and_escalate(mixed_entries)
        print(f"  Emails sent: {count}")
        print(f"  Expected: 2 (only High signal entries)")
        print(f"  Check your inbox at {ESCALATION_TO_EMAIL}!")
    else:
        # Count without sending
        high_count = sum(1 for e in mixed_entries if e.get("signal_level") == "High")
        print(f"  Would send {high_count} emails (SMTP not configured for actual send)")
    
    print("\nAll escalation tests completed!")
```

---

## EDGE CASES

### SMTP not configured
If any SMTP setting is missing, `send_escalation_email()` logs a warning and returns False. The pipeline continues normally — escalation is a nice-to-have, not critical path.

### Email send fails
Network issues, wrong credentials, Gmail blocking the connection — all caught, logged, returned as False. Never crashes the pipeline.

### No high-signal entries
`check_and_escalate()` returns 0. No emails sent. This is the normal case — most search cycles won't find truly high-signal content.

### Multiple high-signal entries in one cycle
Each gets its own email. No batching — you want each alert to be standalone and immediately actionable.

### Very long title
Subject line truncates title to 80 characters. The full title is in the email body.

### Special characters in title or summary
`MIMEText` with `utf-8` charset handles Unicode correctly. Emojis, accented characters, Chinese/Japanese text — all fine.

### Gmail rate limits
Gmail allows ~500 emails/day for regular accounts. With 4 cycles/day and typically 0–2 high-signal entries per cycle, you'll never hit this.