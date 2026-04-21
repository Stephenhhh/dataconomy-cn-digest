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
    bcc_list: list[str] | None = None,
) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = mail_to
    # BCC: not added to headers (invisible to recipients),
    # but included in smtp.send_message via envelope recipients
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    # Build full recipient list for SMTP envelope
    all_recipients = [mail_to]
    if bcc_list:
        all_recipients.extend(bcc_list)

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as smtp:
        smtp.login(smtp_user, smtp_pass)
        smtp.sendmail(smtp_user, all_recipients, msg.as_string())
    logger.info("Sent email: %s (BCC: %s)", msg.get("Message-ID", "(no-id)"),
                ", ".join(bcc_list) if bcc_list else "none")
