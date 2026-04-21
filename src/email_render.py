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

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ subject }}</title>
</head>
<body style="margin:0;padding:0;background:#f5f5f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#f5f5f7;">
    <tr><td align="center" style="padding:24px 12px;">
      <table role="presentation" width="600" cellspacing="0" cellpadding="0" border="0" style="max-width:600px;background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,0.06);">
        <tr><td style="padding:24px 28px 8px 28px;">
          <h1 style="margin:0;font-size:20px;line-height:1.4;color:#111;">Dataconomy CN 每日资讯</h1>
          <p style="margin:4px 0 0 0;font-size:13px;color:#777;">{{ beijing_date }} · {{ items|length }} 条</p>
        </td></tr>
        {% if highlights %}
        <tr><td style="padding:16px 28px 8px 28px;border-top:1px solid #eee;">
          <div style="background:#f0f7ff;border-radius:6px;padding:14px 18px;">
            <div style="font-size:13px;font-weight:600;color:#0b66ff;margin-bottom:8px;">资讯速览</div>
            {% for h in highlights %}
            <div style="font-size:14px;line-height:1.6;color:#333;{% if not loop.last %}margin-bottom:6px;{% endif %}">• {{ h }}</div>
            {% endfor %}
          </div>
        </td></tr>
        {% endif %}
        {% for item in items %}
        <tr><td style="padding:20px 28px;border-top:1px solid #eee;">
          <a href="{{ item.link }}" style="color:#0b66ff;text-decoration:none;font-size:17px;font-weight:600;line-height:1.45;">{{ item.title }}</a>
          {% if item.dek %}
          <div style="margin:4px 0 0 0;font-size:14px;line-height:1.5;color:#555;">{{ item.dek }}</div>
          {% endif %}
          <div style="margin:6px 0 10px 0;font-size:12px;color:#888;">
            {{ item.pub_beijing }}{% if item.author %} · {{ item.author }}{% endif %}{% if item.categories %} · {{ item.categories|join('、') }}{% endif %}
          </div>
          <div style="font-size:14px;line-height:1.65;color:#333;">
            {{ item.summary_html|safe }}
          </div>
          <div style="margin-top:10px;">
            <a href="{{ item.link }}" style="font-size:13px;color:#0b66ff;text-decoration:none;">阅读原文 →</a>
          </div>
        </td></tr>
        {% endfor %}
        <tr><td style="padding:16px 28px 24px 28px;border-top:1px solid #eee;font-size:12px;color:#999;">
          来源：<a href="https://cn.dataconomy.com/" style="color:#999;">cn.dataconomy.com</a> · 生成于 {{ generated_at }}
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""


def _sanitize_summary(raw: str) -> str:
    """Remove script/style blocks and trailing junk; make images responsive."""
    if not raw:
        return ""
    cleaned = _SCRIPT_STYLE_RE.sub("", raw)
    # Remove trailing junk: <小时>, <hr>, and everything after
    cleaned = _TRAILING_JUNK_RE.sub("", cleaned)
    # Remove "精选图片来源" and everything after (sometimes without <hr>)
    cleaned = _FEATURED_IMAGE_RE.sub("", cleaned)
    # Make images responsive
    cleaned = re.sub(
        r"<img\b",
        '<img style="max-width:100%;height:auto;border-radius:4px;"',
        cleaned,
        flags=re.IGNORECASE,
    )
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
    deks: list[str] | None = None,
) -> str:
    from zoneinfo import ZoneInfo

    env = Environment(autoescape=select_autoescape(["html", "xml"]))
    template = env.from_string(HTML_TEMPLATE)
    deks = deks or []
    prepared = [
        {
            "title": it.title,
            "link": it.link,
            "author": it.author,
            "categories": it.categories,
            "pub_beijing": _beijing_str(it.published),
            "summary_html": _sanitize_summary(it.summary_html),
            "dek": deks[i] if i < len(deks) else "",
        }
        for i, it in enumerate(items)
    ]
    subject = build_subject(beijing_date, len(items))
    now_beijing = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M %Z")
    return template.render(
        subject=subject,
        beijing_date=beijing_date.isoformat(),
        items=prepared,
        highlights=highlights or [],
        generated_at=now_beijing,
    )


def render_text(
    items: list["FeedItem"],
    highlights: list[str] | None = None,
    deks: list[str] | None = None,
) -> str:
    lines: list[str] = ["Dataconomy CN 每日资讯", ""]

    if highlights:
        lines.append("资讯速览")
        for h in highlights:
            lines.append(f"• {h}")
        lines.append("")
        lines.append("---")
        lines.append("")

    deks = deks or []
    for i, it in enumerate(items, 1):
        summary_text = _TAG_RE.sub(" ", it.summary_html or "")
        summary_text = html.unescape(_WHITESPACE_RE.sub(" ", summary_text)).strip()
        if len(summary_text) > 200:
            summary_text = summary_text[:200].rstrip() + "…"
        lines.append(f"{i}. {it.title}")
        dek = deks[i - 1] if (i - 1) < len(deks) else ""
        if dek:
            lines.append(f"   >> {dek}")
        lines.append(f"   {it.link}")
        lines.append(f"   {_beijing_str(it.published)}")
        if summary_text:
            lines.append(f"   {summary_text}")
        lines.append("")
    lines.append("-- 来源：cn.dataconomy.com --")
    return "\n".join(lines)
