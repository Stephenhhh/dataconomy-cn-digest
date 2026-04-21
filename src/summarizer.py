"""Generate AI-powered highlights and deks using Google Gemini 2.5 Flash."""
from __future__ import annotations

import html as html_mod
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .feed import FeedItem

logger = logging.getLogger(__name__)

MODEL = "gemini-2.5-flash"

_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL
)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class SummaryResult:
    highlights: list[str]


def _strip_html(raw: str) -> str:
    """Convert HTML to plain text."""
    if not raw:
        return ""
    text = _SCRIPT_STYLE_RE.sub("", raw)
    text = _TAG_RE.sub(" ", text)
    text = html_mod.unescape(_WHITESPACE_RE.sub(" ", text)).strip()
    return text


def _build_prompt(items: list["FeedItem"]) -> str:
    n = len(items)
    num_highlights = 2 if n < 5 else 3

    articles = []
    for i, it in enumerate(items, 1):
        plaintext = _strip_html(it.summary_html)
        articles.append(f"第{i}篇\n标题：{it.title}\n全文：{plaintext}")

    article_block = "\n===\n".join(articles)

    return f"""你是一位资深科技资讯编辑，擅长用简洁自然的中文撰写新闻摘要。

从以下 {n} 条资讯中提炼 {num_highlights} 条核心要点（资讯速览）。

要求：
- 每条 10-20 字，一句话直击要点，不要冗余修饰
- 带有洞察视角，不是简单复述标题
- 覆盖不同领域，不重复同一话题
- 优先级：重大产品发布 > 行业趋势 > 安全事件 > 研究发现

语言规范（非常重要）：
- 中英文之间必须加一个半角空格（如"Apple 发布""AI 模型""Claude Mythos 架构"）
- 数字与中文之间也加空格（如"3 个月""100 万"）
- 使用自然、平实、口语化的中文，避免翻译腔和生硬表述
- 不编造原文中没有的信息

请严格以如下 JSON 格式输出：
{{
  "highlights": ["要点一", "要点二"]
}}

资讯列表：
===
{article_block}
==="""


def _parse_response(text: str) -> SummaryResult | None:
    """Parse LLM response text into SummaryResult."""
    cleaned = text.strip()
    # Strip markdown code block if present
    if cleaned.startswith("```"):
        first_nl = cleaned.index("\n") if "\n" in cleaned else 3
        cleaned = cleaned[first_nl + 1 :]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

    data = json.loads(cleaned)

    highlights = data.get("highlights")

    if not isinstance(highlights, list) or not highlights:
        logger.warning("Invalid highlights in LLM response")
        return None

    # Clean bullet prefixes from highlights
    highlights = [h.lstrip("•·- ").strip() for h in highlights]

    return SummaryResult(highlights=highlights)


def generate_summary(items: list["FeedItem"]) -> SummaryResult | None:
    """Generate highlights and deks via Gemini 2.5 Flash.

    Returns SummaryResult on success, or None if unavailable/failed.
    Never raises.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        logger.info("GEMINI_API_KEY not set, skipping AI summary.")
        return None

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        prompt = _build_prompt(items)
        logger.info("Calling Gemini %s for %d items...", MODEL, len(items))

        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=8192,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
                response_mime_type="application/json",
            ),
        )

        text = response.text
        if not text:
            logger.warning("Gemini returned empty response")
            return None

        logger.info("Gemini response length: %d chars", len(text))
        logger.info("Gemini raw response: %s", text[:500])
        result = _parse_response(text)
        if result:
            logger.info("Generated %d highlights", len(result.highlights))
        return result

    except Exception as exc:  # noqa: BLE001
        logger.warning("AI summary failed: %s: %s", type(exc).__name__, exc)
        return None
