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
from pathlib import Path
from zoneinfo import ZoneInfo

from . import dedup, email_render, feed, mailer, summarizer

logger = logging.getLogger(__name__)

# cc_list.txt lives at project root
_CC_LIST_PATH = Path(__file__).resolve().parent.parent / "cc_list.txt"


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


def _load_cc_list() -> list[str]:
    """Read CC recipients from cc_list.txt (one email per line, # comments)."""
    if not _CC_LIST_PATH.exists():
        return []
    emails: list[str] = []
    for line in _CC_LIST_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            emails.append(line)
    if emails:
        logger.info("CC list: %s", ", ".join(emails))
    return emails


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

    # Log categories for analysis
    all_cats: set[str] = set()
    for it in new_items:
        all_cats.update(it.categories)
    if all_cats:
        logger.info("Categories in this batch: %s", ", ".join(sorted(all_cats)))

    # AI summary generation (graceful degradation)
    summary_result = summarizer.generate_summary(new_items)
    highlights = summary_result.highlights if summary_result else []
    deks = summary_result.deks if summary_result else []

    beijing_date = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    subject = email_render.build_subject(beijing_date, len(new_items))
    html_body = email_render.render_html(new_items, beijing_date, highlights=highlights, deks=deks)
    text_body = email_render.render_text(new_items, highlights=highlights, deks=deks)
    logger.info("Subject: %s", subject)
    logger.info("HTML length: %d chars", len(html_body))

    if args.dry_run:
        logger.info("[dry-run] Would send %d items:", len(new_items))
        for it in new_items:
            logger.info("  - %s  |  %s", it.title, it.link)
        if highlights:
            logger.info("[dry-run] Highlights:")
            for h in highlights:
                logger.info("  • %s", h)
        if deks:
            logger.info("[dry-run] Deks:")
            for i, d in enumerate(deks):
                logger.info("  %d: %s", i + 1, d)
        return 0

    smtp_user = _require_env("SMTP_USER")
    smtp_pass = _require_env("SMTP_PASS")
    mail_to = _require_env("MAIL_TO")
    cc_list = _load_cc_list()

    mailer.send_email(
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        smtp_user=smtp_user,
        smtp_pass=smtp_pass,
        mail_to=mail_to,
        cc_list=cc_list,
    )

    if not args.force_send:
        dedup.update_state(state, new_items)
        dedup.save_state(state)
    else:
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
