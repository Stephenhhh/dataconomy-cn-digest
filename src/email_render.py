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
        {% for item in items %}
        <tr><td style="padding:20px 28px;border-top:1px solid #eee;">
          <a href="{{ item.link }}" style="color:#0b66ff;text-decoration:none;font-size:17px;font-weight:600;line-height:1.45;">{{ item.title }}</a>
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
    """Remove script/style blocks; let Gmail sandbox the rest.

    Also constrains images to be responsive via a wrapping style tweak —
    we do it with a simple regex on <img> tags.
    """
    if not raw:
        return ""
    cleaned = _SCRIPT_STYLE_RE.sub("", raw)
    # Make images responsive.
    cleaned = re.sub(
        r"<img\b",
        '<img style="max-width:100%;height:auto;border-radius:4px;"',
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned


def _beijing_str(dt: datetime) -> str:
    from zoneinfo import ZoneInfo

    return dt.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")


def build_subject(beijing_date: date, n_items: int) -> str:
    short_date = beijing_date.strftime("%m-%d")
    return f"Dataconomy {short_date} 日报 · {n_items} 条"


def render_html(items: list["FeedItem"], beijing_date: date) -> str:
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
        items=prepared,
        generated_at=now_beijing,
    )


def render_text(items: list["FeedItem"]) -> str:
    lines: list[str] = ["Dataconomy CN 每日资讯", ""]
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
