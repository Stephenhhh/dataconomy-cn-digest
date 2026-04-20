"""CLI entry point for the daily digest job.

Usage:
    python -m src.main [--dry-run] [--force-send] [--limit N]

Env vars (required unless --dry-run):
    SMTP_USER  Gmail address used for login and From:
    SMTP_PASS  Gmail App Password (16 chars)
    MAIL_TO    Recipient email address
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

from . import dedup, email_render, feed, mailer

logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Dataconomy CN daily email digest")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch, filter, render — but do NOT send and do NOT write state.",
    )
    p.add_argument(
        "--force-send",
        action="store_true",
        help="Skip dedup filtering; send the latest N items regardless of state.",
    )
    p.add_argument("--limit", type=int, default=10, help="Max items to include (default 10).")
    return p.parse_args(argv)


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def run(args: argparse.Namespace) -> int:
    items = feed.get_latest_items(limit=args.limit)
    if not items:
        logger.warning("Feed returned 0 items; nothing to do.")
        return 0

    state = dedup.load_state()
    new_items = items if args.force_send else dedup.filter_new(items, state)
    if not new_items:
        logger.info("No new items, skipping email.")
        return 0

    beijing_date = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    subject = email_render.build_subject(beijing_date, len(new_items))
    html_body = email_render.render_html(new_items, beijing_date)
    text_body = email_render.render_text(new_items)
    logger.info("Subject: %s", subject)
    logger.info("HTML length: %d chars", len(html_body))

    if args.dry_run:
        logger.info("[dry-run] Would send %d items:", len(new_items))
        for it in new_items:
            logger.info("  - %s  |  %s", it.title, it.link)
        return 0

    smtp_user = _require_env("SMTP_USER")
    smtp_pass = _require_env("SMTP_PASS")
    mail_to = _require_env("MAIL_TO")

    mailer.send_email(
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        smtp_user=smtp_user,
        smtp_pass=smtp_pass,
        mail_to=mail_to,
    )

    if not args.force_send:
        dedup.update_state(state, new_items)
        dedup.save_state(state)
    else:
        # Even in force-send mode, remember what we sent so future dedup works.
        dedup.update_state(state, new_items)
        dedup.save_state(state)

    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = _parse_args(argv)
    try:
        return run(args)
    except Exception as exc:  # noqa: BLE001
        logger.error("Digest job failed: %s", exc)
        logger.error("Traceback:\n%s", traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
