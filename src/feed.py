"""Fetch and parse the Dataconomy CN posts via WordPress REST API.

Why REST API instead of RSS:
- The RSS feed (/feed/) is blocked by Cloudflare's JS challenge for
  automated requests (both from GitHub Actions US IPs and our Worker).
- The WP REST API (/wp-json/wp/v2/posts) is NOT behind the challenge
  and returns clean JSON reliably from any IP.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import requests
from dateutil import parser as dateparser

logger = logging.getLogger(__name__)

# WordPress REST API endpoint (not blocked by Cloudflare challenge)
API_URL = "https://cn.dataconomy.com/wp-json/wp/v2/posts"
# Category endpoint for resolving IDs to names
CATEGORY_API_URL = "https://cn.dataconomy.com/wp-json/wp/v2/categories"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 30
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


def _request_with_retry(url: str, params: dict | None = None) -> requests.Response:
    """GET with retry and exponential backoff."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    backoff = 2
    last_exc: Optional[Exception] = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
            if resp.status_code >= 500:
                raise requests.HTTPError(f"{resp.status_code} server error")
            resp.raise_for_status()
            return resp
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
            last_exc = exc
            logger.warning("Attempt %d failed: %s", attempt, exc)
            if attempt < MAX_ATTEMPTS:
                time.sleep(backoff)
                backoff *= 3
    assert last_exc is not None
    raise last_exc


def _fetch_category_names(cat_ids: list[int]) -> dict[int, str]:
    """Resolve category IDs to names via WP API."""
    if not cat_ids:
        return {}
    unique_ids = list(set(cat_ids))
    try:
        resp = _request_with_retry(
            CATEGORY_API_URL,
            params={"include": ",".join(str(i) for i in unique_ids), "per_page": 100},
        )
        data = resp.json()
        return {item["id"]: item["name"] for item in data}
    except Exception as exc:
        logger.warning("Failed to fetch categories: %s", exc)
        return {}


def _parse_pub_date(raw: Optional[str]) -> datetime:
    """Parse WP date string (ISO 8601, usually UTC/GMT)."""
    if not raw:
        return datetime.now(timezone.utc)
    try:
        dt = dateparser.parse(raw)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_latest_items(limit: int = 10) -> list[FeedItem]:
    """Fetch latest posts from WP REST API and return as FeedItems."""
    resp = _request_with_retry(API_URL, params={"per_page": limit})
    posts = resp.json()
    logger.info("Fetched %d posts from WP REST API (%d bytes)", len(posts), len(resp.content))

    # Collect all category IDs for batch resolution
    all_cat_ids: list[int] = []
    for post in posts:
        all_cat_ids.extend(post.get("categories", []))
    cat_map = _fetch_category_names(all_cat_ids)

    items: list[FeedItem] = []
    for post in posts:
        link = post.get("link", "")
        guid = link or str(post.get("id", ""))
        if not guid:
            continue

        title_raw = post.get("title", {})
        title = (title_raw.get("rendered") or "(无标题)").strip()

        # content.rendered has full HTML; excerpt.rendered is summary
        content_obj = post.get("content", {})
        excerpt_obj = post.get("excerpt", {})
        summary_html = content_obj.get("rendered") or excerpt_obj.get("rendered") or ""

        # Use date_gmt for UTC time
        pub_date_str = post.get("date_gmt") or post.get("date") or ""

        # Resolve category names
        cat_ids = post.get("categories", [])
        categories = [cat_map[cid] for cid in cat_ids if cid in cat_map]

        items.append(
            FeedItem(
                id=guid,
                title=title,
                link=link,
                published=_parse_pub_date(pub_date_str),
                summary_html=summary_html,
                author=None,  # WP API returns author ID, not name
                categories=categories,
            )
        )

    logger.info("Parsed %d items", len(items))
    items.sort(key=lambda i: i.published, reverse=True)
    return items[:limit]
