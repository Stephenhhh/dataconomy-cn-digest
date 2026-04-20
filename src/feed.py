"""Fetch and parse the Dataconomy CN RSS feed."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import feedparser
import requests
from dateutil import parser as dateparser

logger = logging.getLogger(__name__)

FEED_URL = "https://cn.dataconomy.com/feed/"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 20
MAX_ATTEMPTS = 3


@dataclass
class FeedItem:
    id: str
    title: str
    link: str
    published: datetime  # tz-aware UTC
    summary_html: str
    author: Optional[str] = None
    categories: list[str] = field(default_factory=list)


def fetch_feed_bytes(url: str = FEED_URL, timeout: int = REQUEST_TIMEOUT) -> bytes:
    """GET the feed with a browser-like UA and exponential-backoff retry."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    backoff = 1
    last_exc: Optional[Exception] = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code >= 500:
                raise requests.HTTPError(f"{resp.status_code} server error")
            resp.raise_for_status()
            logger.info("Fetched feed: %d bytes (attempt %d)", len(resp.content), attempt)
            return resp.content
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
            last_exc = exc
            logger.warning("Attempt %d failed: %s", attempt, exc)
            if attempt < MAX_ATTEMPTS:
                time.sleep(backoff)
                backoff *= 3
    assert last_exc is not None
    raise last_exc


def _parse_pub_date(raw: Optional[str]) -> datetime:
    if not raw:
        return datetime.now(timezone.utc)
    try:
        dt = dateparser.parse(raw)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _extract_summary(entry) -> str:
    # Prefer <content:encoded>, fall back to <description>/<summary>.
    content_list = entry.get("content") or []
    if content_list:
        value = content_list[0].get("value")
        if value:
            return value
    return entry.get("summary") or entry.get("description") or ""


def _extract_categories(entry) -> list[str]:
    tags = entry.get("tags") or []
    cats = [t.get("term") for t in tags if t.get("term")]
    return [c for c in cats if c]


def parse_feed(raw: bytes) -> list[FeedItem]:
    parsed = feedparser.parse(raw)
    items: list[FeedItem] = []
    for entry in parsed.entries:
        link = entry.get("link") or ""
        guid = entry.get("id") or link
        if not guid:
            continue  # skip malformed entries
        items.append(
            FeedItem(
                id=guid,
                title=(entry.get("title") or "(无标题)").strip(),
                link=link,
                published=_parse_pub_date(entry.get("published") or entry.get("updated")),
                summary_html=_extract_summary(entry),
                author=entry.get("author"),
                categories=_extract_categories(entry),
            )
        )
    logger.info("Parsed %d items", len(items))
    return items


def get_latest_items(limit: int = 10) -> list[FeedItem]:
    raw = fetch_feed_bytes()
    items = parse_feed(raw)
    items.sort(key=lambda i: i.published, reverse=True)
    return items[:limit]
