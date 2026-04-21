# Dataconomy CN Daily Digest — 项目交接文档

> **用途**：本文档供后续接手的 agent / 开发者使用，包含完整的需求背景、调试历程、架构决策、当前进度、待办步骤。阅读本文档后应能无障碍继续完成剩余工作。

---

## 1. 原始需求

**用户目标**：每天定时抓取 `https://cn.dataconomy.com/` 的新闻 feed（10 条），推送到用户的邮箱。

**硬约束**：
- **免费**：不能产生任何订阅费用
- **配置难度不大**：用户是非专职开发者，方案要易于一次性配置
- **中文内容**：源站是 Dataconomy 的中文机翻版，用户接受中文内容（非英文原版）

**用户已确认的参数**（通过 AskUserQuestion 收集）：
| 参数 | 值 |
|---|---|
| 发件邮箱 | `stephenhhh97@gmail.com`（Gmail SMTP，App Password 方式） |
| 收件邮箱 | `leohuo@tencent.com`（腾讯企业邮箱） |
| 推送时间 | 北京时间每天约 10:30（cron `23 2 * * *` UTC，考虑 GitHub Actions 常见 5-15 分钟延迟后落在 10:30 附近） |
| 去重 | **启用**（只推送新文章；若当日 RSS 无更新则跳过发送） |
| 每次条数 | 10 条 |

---

## 2. 技术验证关键发现

### 2.1 源站结构
- `https://cn.dataconomy.com/` 是 **WordPress** 站点
- 自带标准 RSS：`https://cn.dataconomy.com/feed/`（`application/rss+xml`）
- 同时暴露 WP REST API：`https://cn.dataconomy.com/wp-json/wp/v2/posts?per_page=10`
- RSS `<item>` 节点包含：`<title>`、`<link>`、`<pubDate>`、`<description>`（含缩略图 HTML）、`<content:encoded>`（正文 HTML）、`<dc:creator>`、`<category>`
- **源站受 Cloudflare 保护**（`server: cloudflare` 响应头）

### 2.2 IP 可达性矩阵（重要！）

| 客户端 IP | 抓取 `cn.dataconomy.com/feed/` | 抓取 rss2json.com |
|---|---|---|
| 本地开发机（中国 IP / 香港 IP） | ✅ 200 | 本地曾 200，后测 422 |
| **GitHub Actions 美国 IP 段** | ❌ **403 Forbidden**（Cloudflare WAF 拦截） | ❌ **502 Bad Gateway** |

**根本症结**：GitHub Actions 的美国 IP 段被 Cloudflare 视为可疑（被大量机器人滥用），源站的 Cloudflare WAF 直接 403；第三方 RSS→JSON 代理（rss2json）自身也不稳定。

---

## 3. 架构决策与方案演进

### 方案 A（**已废弃**）：GitHub Actions 直接抓源站
- 脚本：`src/feed.py` 使用 `requests` + `feedparser` 直抓 RSS
- 本地验证 ✅ 通过
- **GitHub Actions 上跑：403 Forbidden**（Cloudflare 拦截美国 IP）

### 方案 B（**已尝试，已废弃**）：经 rss2json 公共代理
- `src/feed.py` 改为调用 `https://api.rss2json.com/v1/api.json?rss_url=...`
- 本地验证 ✅ 通过（返回 JSON，字段完整）
- **GitHub Actions 上跑：502 Bad Gateway**（rss2json 自身对 US IP 不稳定）
- 后续本地再测也从 200 变成 422，说明 rss2json 可靠性差，不可依赖

### 方案 C（**最终方案，进行中**）：自建 Cloudflare Worker 作为代理

**原理**：
1. 在 Cloudflare 部署一个极简 Worker，接到请求后去抓 `https://cn.dataconomy.com/feed/` 原样返回
2. 关键优势：Cloudflare Worker 从 Cloudflare 边缘网络出站，Cloudflare 自家 WAF **不会拦自家 Worker**
3. GitHub Actions 不再直抓源站，而是抓用户自己的 Worker URL（稳定可控）

**Worker 代码**（已部署，见 Section 5.3）：
```javascript
const FEED_URL = "https://cn.dataconomy.com/feed/";

export default {
  async fetch(request, env, ctx) {
    const upstream = await fetch(FEED_URL, {
      headers: {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
      },
      cf: { cacheTtl: 600, cacheEverything: true },
    });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("Content-Type") || "application/rss+xml; charset=UTF-8",
        "Cache-Control": "public, max-age=600",
        "Access-Control-Allow-Origin": "*",
      },
    });
  },
};
```

**免费额度**：Cloudflare Workers 免费套餐 10 万请求/天，每天跑 1 次远远够用。

---

## 4. 完整项目结构

### 4.1 仓库 & 运行环境
- **GitHub 仓库**：<https://github.com/Stephenhhh/dataconomy-cn-digest>（public，免费 Actions 无限分钟）
- **本地目录**：`/Users/huojialei/Desktop/dataconomy-cn-digest/`
- **Cloudflare Worker**：`https://dataconomy-proxy.stephenhhh97.workers.dev`（已部署）

### 4.2 文件树
```
dataconomy-cn-digest/
├── .github/workflows/daily-digest.yml   # GitHub Actions 工作流
├── src/
│   ├── __init__.py
│   ├── main.py            # CLI 编排（argparse：--dry-run / --force-send / --limit）
│   ├── feed.py            # RSS 抓取 + 解析（**当前用 rss2json，需改为 Worker URL**）
│   ├── dedup.py           # state.json 读写 + filter_new
│   ├── email_render.py    # Jinja2 HTML + 纯文本双版本渲染
│   └── mailer.py          # smtplib.SMTP_SSL Gmail 发送
├── state.json             # 受版本控制的去重状态：{"seen_ids": [...], "last_run_utc": "..."}
├── requirements.txt       # requests, python-dateutil, Jinja2（feedparser 已移除）
├── .gitignore
├── README.md
└── HANDOFF.md             # 本文档
```

### 4.3 GitHub 仓库已完成的配置
- ✅ **Settings → Actions → General → Workflow permissions** 设为 **Read and write permissions**（工作流需要自动 commit 回 state.json）
- ✅ **3 个 Repository Secrets 已添加**：
  - `SMTP_USER` = `stephenhhh97@gmail.com`
  - `SMTP_PASS` = Gmail App Password（16 位无空格；**用户知道，不在本文档**）
  - `MAIL_TO` = `leohuo@tencent.com`
- ✅ Git 身份：`user.name=stephenhhh97`, `user.email=stephenhhh97@gmail.com`（`--global`）

### 4.4 Gmail 端
- ✅ 已开启 2-Step Verification
- ✅ 已生成 App Password（名为 `dataconomy-digest`），16 位字符串已粘贴进 GitHub Secret `SMTP_PASS`

---

## 5. 当前进度与下一步

### 5.1 已完成
- [x] 本地代码骨架（6 个 Python 模块 + workflow yml + state.json 初始空 + requirements）
- [x] 本地 dry-run 验证通过（用 rss2json 本地能跑）
- [x] 代码推送到 GitHub（main 分支）
- [x] GitHub Actions 工作流权限配置
- [x] 3 个 Secrets 配置完毕
- [x] 诊断出 Cloudflare 拦截 GitHub Actions IP 的根因
- [x] **Cloudflare 账号注册 + Worker 创建完毕**
  - Worker 名称：`dataconomy-proxy`
  - Subdomain：`stephenhhh97.workers.dev`
  - 完整 URL：`https://dataconomy-proxy.stephenhhh97.workers.dev`
- [x] Worker 代码已粘贴到 Cloudflare Dashboard 并 Deploy

### 5.2 正在进行
- [ ] **验证 Worker 工作正常**（用户需在终端执行 curl 命令确认 200）

### 5.3 待办 Step 4~6

**Step 4：验证 Worker（用户手动操作）**
```bash
curl -sI "https://dataconomy-proxy.stephenhhh97.workers.dev" | head -5
curl -s "https://dataconomy-proxy.stephenhhh97.workers.dev" | head -20
```
期望：HTTP 200，Content-Type 是 `application/rss+xml`，内容以 `<?xml version="1.0" encoding="UTF-8"?><rss ...` 开头。

**Step 5：修改 `src/feed.py` 指向 Worker**
- 把 `FEED_URL` 常量改为 `https://dataconomy-proxy.stephenhhh97.workers.dev`
- 把当前 rss2json 的 JSON 解析逻辑**切换回标准 RSS XML 解析**（用 `feedparser`），因为 Worker 返回的是原生 RSS，不是 JSON
- `requirements.txt` **重新加回** `feedparser==6.0.11`
- **注意**：用户目前的 `src/feed.py` 是"rss2json JSON 版本"，需要恢复到"feedparser XML 版本"但把源 URL 指向 Worker

**Step 5 需要替换的完整 `src/feed.py` 内容**（请让用户复制粘贴）：

```python
"""Fetch and parse the Dataconomy CN RSS feed via Cloudflare Worker proxy.

Why proxy: GitHub Actions' US IP ranges are blocked by Cloudflare WAF
on the origin site (cn.dataconomy.com). A user-owned Cloudflare Worker
fetches the feed from Cloudflare's edge (trusted) and returns it as-is.
"""
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

# Cloudflare Worker that proxies https://cn.dataconomy.com/feed/
FEED_URL = "https://dataconomy-proxy.stephenhhh97.workers.dev"
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


def fetch_feed_bytes(url: str = FEED_URL, timeout: int = REQUEST_TIMEOUT) -> bytes:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    backoff = 2
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
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _extract_summary(entry) -> str:
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
            continue
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
```

**Step 5 同时修改 `requirements.txt`**：
```
feedparser==6.0.11
requests==2.32.3
python-dateutil==2.9.0
Jinja2==3.1.4
```
（把 `feedparser==6.0.11` 加回第一行）

**Step 6：本地 dry-run 验证**
```bash
cd ~/Desktop/dataconomy-cn-digest
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python -m src.main --dry-run
```
期望输出：`Fetched feed: XXXXX bytes`、`Parsed 10 items`、`Would send 10 items:` 等。

**Step 7：推送 + GitHub Actions 重跑**
```bash
git add src/feed.py requirements.txt
git commit -m "fix(feed): switch proxy to self-hosted Cloudflare Worker"
git push
```
然后去 Actions 页手动 Run workflow（两个 input 都不勾），观察：
- `Run digest` 步骤绿色 ✓
- 日志含 `Sent email: <Message-ID>`
- 仓库自动产生 commit `chore: update state.json [skip ci]`
- 收件箱 `leohuo@tencent.com` 收到邮件（**也要查垃圾邮件箱**，腾讯对外部邮件判严）

**Step 8：去重验证**
立即再手动触发一次 workflow（同样不勾任何 input），期望：
- 日志显示 `Filtered to 0 new items (of 10)` → `No new items, skipping email.`
- 不产生新 commit
- 不发新邮件

**Step 9（可选）：收件人的过滤规则**
在 `leohuo@tencent.com` 邮箱里设过滤规则：
- 条件：Subject 含 `Dataconomy CN`
- 动作：自动加星 / 标为重要 / 永不进垃圾箱 / 贴特定标签

---

## 6. 代码架构要点（给接手者快速上手）

### 6.1 数据流
```
Cron / Manual Trigger
  → src/main.py:run()
    → src/feed.py:get_latest_items(10)
        → fetch_feed_bytes() [via Cloudflare Worker]
        → feedparser.parse() → FeedItem dataclass × 10
    → src/dedup.py:load_state() / filter_new()
        → 若无新条目：exit 0，不发邮件不写 state
    → src/email_render.py:render_html() / render_text() / build_subject()
    → src/mailer.py:send_email() [smtplib.SMTP_SSL:465 to smtp.gmail.com]
    → src/dedup.py:update_state() / save_state()
  → stefanzweifel/git-auto-commit-action 回写 state.json（无改动时 no-op）
```

### 6.2 FeedItem dataclass（所有模块间的数据契约）
```python
@dataclass
class FeedItem:
    id: str                     # GUID，去重 key，降级用 link
    title: str
    link: str
    published: datetime         # tz-aware UTC
    summary_html: str           # 优先 content:encoded，降级 description
    author: Optional[str] = None
    categories: list[str] = field(default_factory=list)
```
替换 `feed.py` 的抓取实现时，**必须保持这个 dataclass 结构不变**，其它模块才能继续工作。

### 6.3 dedup.state.json 结构
```json
{
  "seen_ids": ["guid1", "guid2", ...],   // 最新优先，最多 200 个
  "last_run_utc": "2026-04-20T02:23:15Z"
}
```
`seen_ids` 空 = bootstrap 首次运行 → 把当前 top 10 全当新条目一次性发出并 seed 到 state。

### 6.4 GitHub Actions workflow 要点
- Trigger: `schedule: cron: "23 2 * * *"`（UTC 02:23 ≈ 北京 10:23-10:38）+ `workflow_dispatch`
- `permissions: contents: write`（push state.json 必需）
- `concurrency: group: daily-digest, cancel-in-progress: false`（防 race）
- Dry-run 步骤条件：`if: ${{ inputs.dry_run != true }}` 跳过 commit 步骤
- 使用 `stefanzweifel/git-auto-commit-action@v5`（无改动自动 no-op）

---

## 7. 已知风险与兜底

| 风险 | 概率 | 应对 |
|---|---|---|
| Worker 免费额度超限（10 万/天） | 极低（每天只用 2 次） | 监控即可 |
| Worker URL 泄漏被人滥用 | 低 | 可在 Worker 加简单鉴权 header，Python 端同步加 |
| Gmail 阻止 SMTP 登录（异常地点） | 中 | App Password 绕开；必要时在 Google 安全页点"是我本人" |
| 腾讯企业邮箱判 Gmail 为垃圾 | 中 | 用户在收件端设白名单过滤规则 |
| GitHub Actions schedule 被延迟/跳过 | 常见（5-15 分钟） | 选择 `:23` 非整点 cron；workflow_dispatch + --force-send 作手动恢复 |
| 公共仓库 60 天无 commit 导致 schedule 被禁 | 低（每次新条目会 commit state.json） | 若触发，手动 Run workflow 即可恢复 |
| Cloudflare 未来封锁 Worker 抓自家 CDN 内容 | 极低 | 兜底可换用户自己的 VPS / 购买付费 API |

---

## 8. 环境信息

- **操作系统**：macOS（LeoHuo-MC1）
- **Python 版本**：本地 3.9（系统自带） / venv 3.9；GitHub Actions runner 3.12
- **Git 全局配置**：`user.name=stephenhhh97`, `user.email=stephenhhh97@gmail.com`
- **GitHub PAT**：已在 Keychain 保存（fine-grained token，仓库限定 `Stephenhhh/dataconomy-cn-digest`，权限 Contents: Read/Write + Workflows: Read/Write，90 天有效）
- **Cloudflare 账号**：`stephenhhh97@gmail.com`，subdomain `stephenhhh97.workers.dev`

---

## 9. 关键 URL 清单

| 用途 | URL |
|---|---|
| GitHub 仓库 | <https://github.com/Stephenhhh/dataconomy-cn-digest> |
| GitHub Actions | <https://github.com/Stephenhhh/dataconomy-cn-digest/actions> |
| GitHub Secrets 配置 | <https://github.com/Stephenhhh/dataconomy-cn-digest/settings/secrets/actions> |
| Cloudflare Workers Dashboard | <https://dash.cloudflare.com/> → Workers & Pages → `dataconomy-proxy` |
| Cloudflare Worker URL（数据源） | `https://dataconomy-proxy.stephenhhh97.workers.dev` |
| 原始源站 RSS | `https://cn.dataconomy.com/feed/` |
| 备用源站 API | `https://cn.dataconomy.com/wp-json/wp/v2/posts?per_page=10` |
| Gmail App Password 管理 | <https://myaccount.google.com/apppasswords> |

---

## 10. 下一位 agent 的立即行动项（按顺序）

1. **让用户验证 Worker** 是否返回 200（Step 4 的两个 curl 命令）
2. 如果 Worker 没问题 → **指导用户替换 `src/feed.py`** 为本文档 Section 5.3 的代码
3. 同时**更新 `requirements.txt`** 加回 `feedparser==6.0.11`
4. 本地 dry-run → 推送 → GitHub Actions 手动 Run → 确认邮件送达
5. 立即再 Run 一次验证去重
6. 指导用户在腾讯邮箱设过滤规则（避免日后判垃圾）

**特殊注意**：
- 用户是非专职开发者，每一步要给明确的"在哪里点 / 填什么 / 成功的标志是什么"
- 用户偏好**分步引导**（发现批量步骤会出错后反馈过"不要一次性把所有步骤吐给我"）
- 用户粘贴代码后曾出现"整块被额外缩进 2 空格"导致 IndentationError，建议用户用 VS Code / Sublime 而不是 TextEdit
- 每次修改代码后，必须在本地跑一次 `python -m src.main --dry-run` 再 push，避免 Actions 反复试错
- 敏感信息处理：用户曾把 App Password 粘在聊天里，要提醒作废重生；**不要把任何 token / password 写入任何文件**

祝顺利。
