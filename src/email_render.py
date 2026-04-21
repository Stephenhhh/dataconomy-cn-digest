"""Render HTML and plaintext email bodies for the daily digest."""
from __future__ import annotations

import html
import re
from datetime import date, datetime
from typing import TYPE_CHECKING

from jinja2 import Environment, select_autoescape

if TYPE_CHECKING:
    from .feed import FeedItem

_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL
)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

# Clean trailing junk from Dataconomy CN articles:
# - "<小时>" (mistranslated <hr>)
# - "精选图片来源" / "Featured image credit" links
_TRAILING_JUNK_RE = re.compile(
    r"(?:<小时>|<hr\b[^>]*>)"
    r".*$",
    re.IGNORECASE | re.DOTALL,
)
_FEATURED_IMAGE_RE = re.compile(
    r"\s*精选图片来源.*$",
    re.IGNORECASE | re.DOTALL,
)

_WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ subject }}</title>
</head>
<body style="margin:0;padding:0;background:#ffffff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
    <tr><td style="padding:24px 28px 8px 28px;">
      <h1 style="margin:0;font-size:20px;line-height:1.4;color:#1D1D1F;">Dataconomy CN 每日资讯</h1>
      <p style="margin:4px 0 0 0;font-size:13px;color:#AEAEB2;">{{ beijing_date }} {{ beijing_weekday }} · {{ items|length }} 条</p>
    </td></tr>
    {% if highlights %}
    <tr><td style="padding:20px 28px 0 28px;">
      <div style="font-size:13px;font-weight:600;color:#07C160;margin-bottom:14px;">资讯速览</div>
      <table role="presentation" cellspacing="0" cellpadding="0" border="0" style="width:100%;">
        {% for h in highlights %}
        <tr>
          <td valign="top" style="width:20px;padding:{% if not loop.first %}6px{% else %}0px{% endif %} 0 0 0;font-size:15px;font-weight:700;color:#07C160;line-height:1.6;">{{ loop.index }}.</td>
          <td valign="top" style="padding:{% if not loop.first %}6px{% else %}0px{% endif %} 0 0 0;font-size:15px;line-height:1.6;color:#1D1D1F;">{{ h }}</td>
        </tr>
        {% endfor %}
      </table>
    </td></tr>
    {% endif %}
    {% for item in items %}
    <tr><td style="padding:0 28px;">
      <div style="border-top:1px solid #F0F0F0;margin:32px 0;"></div>
    </td></tr>
    <tr><td style="padding:0 28px;">
      <a href="{{ item.link }}" style="color:#1D1D1F;text-decoration:none;font-size:18px;font-weight:700;line-height:1.45;display:block;margin-bottom:10px;">{{ item.title }}</a>
      <div style="margin:0 0 14px 0;font-size:12px;color:#AEAEB2;">
        {{ item.pub_beijing }}{% if item.author %} · {{ item.author }}{% endif %}{% if item.categories %} · {% for cat in item.categories %}<span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;color:#636366;{% if not loop.last %}margin-right:4px;{% endif %}">{{ cat }}</span>{% endfor %}{% endif %}
      </div>
      <div style="font-size:14px;line-height:1.8;color:#636366;">
        {{ item.summary_html|safe }}
      </div>
      <div style="margin-top:16px;">
        <a href="{{ item.link }}" style="font-size:14px;font-weight:500;color:#07C160;text-decoration:none;">阅读原文 →</a>
      </div>
    </td></tr>
    {% endfor %}
    <tr><td style="padding:0 28px;">
      <div style="border-top:1px solid #F0F0F0;margin:32px 0 0 0;"></div>
    </td></tr>
    <tr><td style="padding:0 28px 24px 28px;font-size:12px;color:#AEAEB2;">
      来源：<a href="https://cn.dataconomy.com/" style="color:#AEAEB2;">cn.dataconomy.com</a> · 生成于 {{ generated_at }}
    </td></tr>
  </table>
</body>
</html>
"""


_MAX_CHINESE_CHARS = 350


def _truncate_html(html_str: str, max_chars: int = _MAX_CHINESE_CHARS) -> str:
    """Truncate HTML content to approximately max_chars of visible Chinese text.

    Strips tags to count characters, then truncates the original HTML at the
    corresponding point, closing any open tags and appending an ellipsis.
    """
    # Get plain text (no whitespace) for counting
    plain = _TAG_RE.sub("", html_str)
    plain = re.sub(r"\s+", "", plain)
    if len(plain) <= max_chars:
        return html_str

    # Walk through HTML, counting visible chars
    count = 0
    i = 0
    while i < len(html_str) and count < max_chars:
        if html_str[i] == "<":
            # Skip entire tag
            end = html_str.find(">", i)
            if end == -1:
                break
            i = end + 1
        elif html_str[i] in (" ", "\n", "\r", "\t"):
            i += 1
        else:
            count += 1
            i += 1

    # Find a reasonable cut point (end of current paragraph or sentence)
    # Try to cut at </p> within the next 100 chars
    cut_search = html_str[i : i + 200]
    p_end = cut_search.find("</p>")
    if p_end != -1 and p_end < 150:
        i = i + p_end + 4  # include the </p>
    else:
        # Cut at current position, try not to break a tag
        if "<" in html_str[max(0, i - 10) : i]:
            tag_start = html_str.rfind("<", 0, i)
            if tag_start > 0:
                i = tag_start

    truncated = html_str[:i].rstrip()
    return truncated + '<p style="color:#999;font-size:13px;">……</p>'


def _sanitize_summary(raw: str) -> str:
    """Remove script/style blocks and trailing junk; style images, paragraphs, blockquotes; truncate."""
    if not raw:
        return ""
    cleaned = _SCRIPT_STYLE_RE.sub("", raw)
    # Remove trailing junk: <小时>, <hr>, and everything after
    cleaned = _TRAILING_JUNK_RE.sub("", cleaned)
    # Remove "精选图片来源" and everything after (sometimes without <hr>)
    cleaned = _FEATURED_IMAGE_RE.sub("", cleaned)
    # Style images: 8px rounded corners, border, margin, responsive
    cleaned = re.sub(
        r"<img\b",
        '<img style="max-width:100%;height:auto;border-radius:8px;border:1px solid #EDEDED;margin:14px 0;display:block;"',
        cleaned,
        flags=re.IGNORECASE,
    )
    # Style paragraphs: add margin-bottom for breathing room
    cleaned = re.sub(
        r"<p\b([^>]*)>",
        r'<p style="margin:0 0 14px 0;"\1>',
        cleaned,
        flags=re.IGNORECASE,
    )
    # Style blockquotes: grey left border + light background
    cleaned = re.sub(
        r"<blockquote\b[^>]*>",
        '<blockquote style="margin:14px 0;padding:14px 18px;border-left:3px solid #E5E5EA;background:#FAFAFA;border-radius:0 8px 8px 0;">',
        cleaned,
        flags=re.IGNORECASE,
    )
    # Truncate if too long
    cleaned = _truncate_html(cleaned)
    return cleaned.rstrip()


def _beijing_str(dt: datetime) -> str:
    from zoneinfo import ZoneInfo

    return dt.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")


def build_subject(beijing_date: date, n_items: int) -> str:
    short_date = beijing_date.strftime("%m-%d")
    return f"🚀Dataconomy 早报：{n_items} 条看点"


def render_html(
    items: list["FeedItem"],
    beijing_date: date,
    highlights: list[str] | None = None,
) -> str:
    from zoneinfo import ZoneInfo

    env = Environment(autoescape=select_autoescape(["html", "xml"]))
    template = env.from_string(HTML_TEMPLATE)
    prepared = [
        {
            "title": it.title,
            "link": it.link,
            "author": it.author,
            "categories": it.categories,
            "pub_beijing": _beijing_str(it.published),
            "summary_html": _sanitize_summary(it.summary_html),
        }
        for it in items
    ]
    subject = build_subject(beijing_date, len(items))
    now_beijing = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M %Z")
    return template.render(
        subject=subject,
        beijing_date=beijing_date.isoformat(),
        beijing_weekday=_WEEKDAYS[beijing_date.weekday()],
        items=prepared,
        highlights=highlights or [],
        generated_at=now_beijing,
    )


def render_text(
    items: list["FeedItem"],
    highlights: list[str] | None = None,
) -> str:
    lines: list[str] = ["Dataconomy CN 每日资讯", ""]

    if highlights:
        lines.append("资讯速览")
        for i, h in enumerate(highlights, 1):
            lines.append(f"{i}. {h}")
        lines.append("")
        lines.append("---")
        lines.append("")

    for i, it in enumerate(items, 1):
        summary_text = _TAG_RE.sub(" ", it.summary_html or "")
        summary_text = html.unescape(_WHITESPACE_RE.sub(" ", summary_text)).strip()
        if len(summary_text) > 200:
            summary_text = summary_text[:200].rstrip() + "…"
        lines.append(f"{i}. {it.title}")
        lines.append(f"   {it.link}")
        lines.append(f"   {_beijing_str(it.published)}")
        if summary_text:
            lines.append(f"   {summary_text}")
        lines.append("")
    lines.append("-- 来源：cn.dataconomy.com --")
    return "\n".join(lines)
