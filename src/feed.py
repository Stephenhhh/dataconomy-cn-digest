"""Fetch and parse the Dataconomy CN RSS feed via rss2json proxy.
                                                                                                
Why proxy: GitHub Actions' US IP ranges are blocked by Cloudflare on
the origin site (cn.dataconomy.com). rss2json.com fetches the feed                              
server-side from a friendlier IP and returns clean JSON.      
                                                                                                
Public API, no key required, 10000 requests/day free tier (we use 1/day).        
Docs: https://rss2json.com/docs
"""                   
from __future__ import annotations
                                           
import logging            
import time                       
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote     
               
import requests
from dateutil import parser as dateparser                                                       

logger = logging.getLogger(__name__)                                                            
                                                                                 
FEED_URL = "https://cn.dataconomy.com/feed/"
PROXY_API = "https://api.rss2json.com/v1/api.json"
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


def fetch_feed_json(
    feed_url: str = FEED_URL,
    count: int = 10,
    timeout: int = REQUEST_TIMEOUT,
) -> dict[str, Any]:
    """Fetch the feed via rss2json and return the decoded JSON payload."""
    url = f"{PROXY_API}?rss_url={quote(feed_url, safe='')}&count={count}"
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    backoff = 2
    last_exc: Optional[Exception] = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            status = (data.get("status") or "").lower()
            if status != "ok":
                raise RuntimeError(
                    f"rss2json returned non-ok status: {status!r}, "
                    f"message={data.get('message')!r}"
                )
            items = data.get("items") or []
            logger.info(
                "Fetched feed via rss2json: %d items (attempt %d)",
                len(items),
                attempt,
            )
            return data
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError,
                ValueError, RuntimeError) as exc:
            last_exc = exc
            logger.warning("Attempt %d failed: %s", attempt, exc)
            if attempt < MAX_ATTEMPTS:
                time.sleep(backoff)
                backoff *= 3
    assert last_exc is not None
    raise last_exc


def _parse_pub_date(raw: Optional[str]) -> datetime:
    """Parse rss2json's pubDate (e.g. '2026-04-20 10:35:17', assumed UTC)."""
    if not raw:
        return datetime.now(timezone.utc)
    try:
        dt = dateparser.parse(raw)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        # rss2json returns naive strings; the source feed uses UTC (+0000).
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _pick_summary(item: dict[str, Any]) -> str:
    """Prefer 'content' (full HTML), fall back to 'description'."""
    content = item.get("content") or ""
    if content and len(content) > 50:
        return content
    return item.get("description") or content or ""


def _pick_categories(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(c).strip() for c in raw if c and str(c).strip()]
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    return []


def parse_feed(payload: dict[str, Any]) -> list[FeedItem]:
    """Convert rss2json JSON payload to a list of FeedItem."""
    items: list[FeedItem] = []
    for entry in payload.get("items") or []:
        link = (entry.get("link") or "").strip()
        guid = (entry.get("guid") or link).strip()
        if not guid:
            continue
        title = (entry.get("title") or "(无标题)").strip()
        items.append(
            FeedItem(
                id=guid,
                title=title,
                link=link,
                published=_parse_pub_date(entry.get("pubDate")),
                summary_html=_pick_summary(entry),
                author=(entry.get("author") or None),
                categories=_pick_categories(entry.get("categories")),
            )
        )
    logger.info("Parsed %d items", len(items))
    return items


def get_latest_items(limit: int = 10) -> list[FeedItem]:
    payload = fetch_feed_json(count=limit)
    items = parse_feed(payload)
    items.sort(key=lambda i: i.published, reverse=True)
    return items[:limit]

