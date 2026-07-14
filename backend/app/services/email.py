"""Send a quote PDF to the client over SMTP, using the Email Setup master.

If no Email Setup row is configured, returns a dry-run result describing the
message instead of sending — so the flow is testable without a live SMTP server.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.models import EmailSetup

logger = logging.getLogger(__name__)


def send_quote_email(setup: EmailSetup | None, *, to_email: str, subject: str,
                     body: str, pdf_bytes: bytes, pdf_name: str) -> dict:
    if setup is None:
        logger.warning("Email dry-run (no Email Setup configured): to=%s subject=%r",
                       to_email, subject)
        return {"sent": False, "dry_run": True, "to": to_email, "subject": subject,
                "reason": "No Email Setup configured — set one up under Masters > Email Setup.",
                "attachment_bytes": len(pdf_bytes)}

    msg = EmailMessage()
    msg["From"] = setup.from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)
    msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=pdf_name)

    try:
        if setup.use_tls:
            with smtplib.SMTP(setup.smtp_host, setup.smtp_port, timeout=20) as s:
                s.starttls()
                if setup.username:
                    s.login(setup.username, setup.password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(setup.smtp_host, setup.smtp_port, timeout=20) as s:
                if setup.username:
                    s.login(setup.username, setup.password)
                s.send_message(msg)
    except Exception:
        logger.exception("Email send failed: to=%s subject=%r", to_email, subject)
        raise
    logger.info("Email sent: to=%s subject=%r", to_email, subject)
    return {"sent": True, "dry_run": False, "to": to_email, "subject": subject}
