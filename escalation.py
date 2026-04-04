"""
Email escalation on high-signal detection.
Sends immediate email alert when Stage 2 detects major events.
Implemented in Chunk 12.
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, ESCALATION_TO_EMAIL, TOPIC
from logger import setup_logger

logger = setup_logger("escalation")


def _build_email_body(entry: dict, topic: str) -> str:
    """Format the email body from entry data."""
    return f"""---
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
"""


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
    """
    if not all([SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, ESCALATION_TO_EMAIL]):
        logger.warning(
            "SMTP not fully configured — skipping escalation email. "
            "Set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, ESCALATION_TO_EMAIL in .env"
        )
        return False

    smtp_port = int(SMTP_PORT)  # type: ignore[arg-type]

    subject = f"🔴 HIGH SIGNAL: {entry.get('title', 'Unknown')[:80]}"
    body = _build_email_body(entry, TOPIC)

    msg = MIMEMultipart()
    msg["From"] = str(SMTP_USER)
    msg["To"] = str(ESCALATION_TO_EMAIL)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP(str(SMTP_HOST), smtp_port, timeout=30) as server:
            server.starttls()
            server.login(str(SMTP_USER), str(SMTP_PASSWORD))
            server.send_message(msg)
        logger.info(f"Escalation email sent: {entry.get('title', 'Unknown')[:50]}")
        return True
    except Exception as e:
        logger.error(f"Failed to send escalation email '{entry.get('title', 'Unknown')[:50]}': {e}")
        return False


def check_and_escalate(entries_with_analyses: list) -> int:
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
    """
    high_signal = [e for e in entries_with_analyses if e.get("signal_level") == "High"]
    logger.info(f"Found {len(high_signal)} high-signal entries")

    sent = 0
    for entry in high_signal:
        if send_escalation_email(entry):
            sent += 1

    logger.info(f"Sent {sent} escalation emails")
    return sent


if __name__ == "__main__":
    from config import SMTP_HOST, SMTP_USER, SMTP_PASSWORD, ESCALATION_TO_EMAIL

    missing = []
    if not SMTP_HOST:
        missing.append("SMTP_HOST")
    if not SMTP_USER:
        missing.append("SMTP_USER")
    if not SMTP_PASSWORD:
        missing.append("SMTP_PASSWORD")
    if not ESCALATION_TO_EMAIL:
        missing.append("ESCALATION_TO_EMAIL")

    if missing:
        print(f"Missing SMTP config: {missing}")
        print("Set these in .env to test email sending.")
        print("\nTesting email body building only...\n")

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
        high_count = sum(1 for e in mixed_entries if e.get("signal_level") == "High")
        print(f"  Would send {high_count} emails (SMTP not configured for actual send)")

    print("\nAll escalation tests completed!")
