"""Send the digest email via Gmail SMTP over SSL."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
SMTP_TIMEOUT = 30


def send_email(
    subject: str,
    html_body: str,
    text_body: str,
    smtp_user: str,
    smtp_pass: str,
    mail_to: str,
    cc_list: list[str] | None = None,
) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = mail_to
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as smtp:
        smtp.login(smtp_user, smtp_pass)
        smtp.send_message(msg)
    logger.info("Sent email: %s (CC: %s)", msg.get("Message-ID", "(no-id)"),
                ", ".join(cc_list) if cc_list else "none")
