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
    deks: list[str]


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

    return f"""你是一位资深科技资讯编辑。以下是今日 {n} 条科技资讯，每条包含标题和全文。
请完成以下两项任务：

任务一：资讯速览
从所有资讯中提炼 {num_highlights} 条最重要的核心要点，帮助读者在 30 秒内掌握今日关键信息。
要求：
- 每条要点 15-30 字，聚焦"发生了什么"和"为什么重要"，带有洞察和点评视角
- 优先级：重大产品发布 > 行业趋势变化 > 安全/隐私事件 > 研究发现
- 各要点覆盖不同领域，避免重复同一话题
- 简洁中文，不用序号词

任务二：文章导语（Dek）
为每篇资讯各写一句导语（Dek），用于展示在标题下方。
要求：
- 每条 Dek 20-40 字，重点在于概括文章的核心观点和结论，让读者一眼了解核心内容
- 风格参考华尔街日报的文章副标题，信息密度高
- 不要简单重复标题内容，而是补充标题未涵盖的关键信息
- 严格按文章顺序输出，数量与输入文章数量一致

请严格以如下 JSON 格式输出，不要输出任何其他内容：
{{
  "highlights": ["要点一", "要点二", ...],
  "deks": ["文章1导语", "文章2导语", ...]
}}

资讯列表：
===
{article_block}
==="""


def _parse_response(text: str, n_items: int) -> SummaryResult | None:
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
    deks = data.get("deks")

    if not isinstance(highlights, list) or not highlights:
        logger.warning("Invalid highlights in LLM response")
        return None

    if not isinstance(deks, list):
        logger.warning("Invalid deks in LLM response")
        return None

    # Pad deks if shorter than expected
    while len(deks) < n_items:
        deks.append("")
    # Trim if longer
    deks = deks[:n_items]

    # Clean bullet prefixes from highlights
    highlights = [h.lstrip("•·- ").strip() for h in highlights]
    deks = [d.strip() for d in deks]

    return SummaryResult(highlights=highlights, deks=deks)


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

        client = genai.Client(api_key=api_key)

        prompt = _build_prompt(items)
        logger.info("Calling Gemini %s for %d items...", MODEL, len(items))

        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config={
                "temperature": 0.3,
                "max_output_tokens": 2048,
            },
        )

        text = response.text
        if not text:
            logger.warning("Gemini returned empty response")
            return None

        logger.info("Gemini response length: %d chars", len(text))
        result = _parse_response(text, len(items))
        if result:
            logger.info(
                "Generated %d highlights + %d deks",
                len(result.highlights),
                len(result.deks),
            )
        return result

    except Exception as exc:  # noqa: BLE001
        logger.warning("AI summary failed: %s: %s", type(exc).__name__, exc)
        return None
