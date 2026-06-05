"""Fetch and parse the Dataconomy CN posts via WordPress REST API.

Strategy:
- Primary: Direct WP REST API call (works from most IPs)
- Fallback: Cloudflare Worker proxy (for GitHub Actions US IPs blocked by WAF)

The Worker proxies requests to cn.dataconomy.com from Cloudflare's edge
network, which is trusted by the origin's own Cloudflare WAF.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import requests
from dateutil import parser as dateparser

logger = logging.getLogger(__name__)

# Direct WP REST API (works from non-blocked IPs)
API_URL = "https://cn.dataconomy.com/wp-json/wp/v2/posts"
CATEGORY_API_URL = "https://cn.dataconomy.com/wp-json/wp/v2/categories"

# Cloudflare Worker proxy (fallback for blocked IPs like GitHub Actions)
# Worker passes through requests to cn.dataconomy.com WP API
WORKER_API_URL = "https://dataconomy-proxy.stephenhhh97.workers.dev/wp-json/wp/v2/posts"
WORKER_CATEGORY_URL = "https://dataconomy-proxy.stephenhhh97.workers.dev/wp-json/wp/v2/categories"

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


def _request_single(url: str, params: dict | None = None) -> requests.Response:
    """Single GET request with timeout."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    resp = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
    if resp.status_code >= 500:
        raise requests.HTTPError(f"{resp.status_code} server error")
    resp.raise_for_status()
    return resp


def _request_with_fallback(
    primary_url: str,
    fallback_url: str,
    params: dict | None = None,
) -> requests.Response:
    """Try primary URL first; on 403/failure, fall back to Worker proxy."""
    # Try primary (direct)
    try:
        resp = _request_single(primary_url, params)
        logger.info("Direct request succeeded: %s", primary_url)
        return resp
    except requests.HTTPError as exc:
        if "403" in str(exc):
            logger.warning("Direct 403, falling back to Worker proxy: %s", exc)
        else:
            logger.warning("Direct request failed: %s", exc)
    except (requests.ConnectionError, requests.Timeout) as exc:
        logger.warning("Direct request failed: %s", exc)

    # Fallback to Worker proxy with retries
    backoff = 2
    last_exc: Optional[Exception] = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = _request_single(fallback_url, params)
            logger.info("Worker proxy succeeded (attempt %d): %s", attempt, fallback_url)
            return resp
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
            last_exc = exc
            logger.warning("Worker attempt %d failed: %s", attempt, exc)
            if attempt < MAX_ATTEMPTS:
                time.sleep(backoff)
                backoff *= 3
    assert last_exc is not None
    raise last_exc


def _fetch_category_names(cat_ids: list[int]) -> dict[int, str]:
    """Resolve category IDs to names via WP API (with Worker fallback)."""
    if not cat_ids:
        return {}
    unique_ids = list(set(cat_ids))
    try:
        resp = _request_with_fallback(
            CATEGORY_API_URL,
            WORKER_CATEGORY_URL,
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


# --- Spam / SEO parasite content filter ---
# Keywords strongly associated with gambling/casino spam injections.
# Matching is case-insensitive against title + raw HTML content.
_SPAM_KEYWORDS: list[str] = [
    # English
    "casino", "gambling", "slot machine", "sports betting", "poker room",
    "welcome bonus", "free spins", "wagering", "bookmaker", "sportsbook",
    "jackpot", "roulette", "blackjack", "baccarat", "no deposit",
    # German
    "spieler", "spielothek", "freispiele", "einzahlung", "wettanbieter",
    # Finnish
    "kasino", "pelaa", "ilmaiskierrokset", "kasinobonukset", "pelaajalle",
    # Spanish
    "tragamonedas", "apuestas", "bono de bienvenida",
    # Polish
    "bonusy", "rejestracja", "graczy", "zakłady", "kasyno", "hazard",
    "przewodnik dla graczy",
    # Chinese
    "赌场", "博彩", "老虎机", "真人赌场", "体育博彩", "欢迎奖金",
    "投注", "牌照", "兹罗提", "免费投注", "赌博", "开玩笑吗",
    # Known spam brand names (gambling sites seen in attack)
    "MGA牌照", "MGA 牌照", "fezbet", "diva spin", "zoccer",
    "cleobetra", "alterspin", "pistolo", "berriez",
]

# Pre-compile a single regex for speed
_SPAM_RE = re.compile(
    "|".join(re.escape(kw) for kw in _SPAM_KEYWORDS),
    re.IGNORECASE,
)


def _is_spam(post: dict) -> bool:
    """Heuristic check: return True if a WP post looks like injected spam.

    Signals:
    1. Post has NO categories → always spam (legit articles always have ≥1)
    2. Title or content matches known spam keywords (≥1 match → spam)
    3. Title contains non-Chinese/non-English foreign language text mixed with Chinese
    """
    has_categories = bool(post.get("categories"))

    # Rule 1: No category = spam (all legitimate Dataconomy CN articles have categories)
    if not has_categories:
        return True

    title = (post.get("title", {}).get("rendered") or "").strip()
    content = (post.get("content", {}).get("rendered") or "")[:2000]  # first 2k chars
    text = f"{title} {content}"

    # Rule 2: Any spam keyword match → spam
    matches = _SPAM_RE.findall(text)
    if matches:
        return True

    # Rule 3: Title with mixed CJK + non-English Latin chars (Polish/German/Finnish spam)
    # Legit titles are purely Chinese or Chinese+English
    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", title))
    # Detect non-ASCII Latin chars (ą, ö, ü, ń, etc.) which indicate foreign spam
    has_foreign_latin = bool(re.search(r"[à-öø-ÿĀ-žƀ-ɏ]", title))
    if has_cjk and has_foreign_latin:
        return True

    return False


def get_latest_items(limit: int = 10) -> list[FeedItem]:
    """Fetch latest posts from WP REST API and return as FeedItems."""
    # Fetch more posts to account for spam filtering
    fetch_limit = min(limit * 3, 30)
    resp = _request_with_fallback(API_URL, WORKER_API_URL, params={"per_page": fetch_limit})
    posts = resp.json()
    logger.info("Fetched %d posts from WP REST API (%d bytes)", len(posts), len(resp.content))

    # Filter out spam/SEO parasite content
    clean_posts = []
    spam_count = 0
    for post in posts:
        if _is_spam(post):
            spam_count += 1
            spam_title = (post.get("title", {}).get("rendered") or "?")[:60]
            logger.warning("Filtered spam post: %s", spam_title)
        else:
            clean_posts.append(post)
    if spam_count:
        logger.warning("Filtered %d spam posts out of %d total", spam_count, len(posts))
    posts = clean_posts

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
