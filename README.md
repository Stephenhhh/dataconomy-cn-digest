# 🚀 Dataconomy CN Daily Digest

每天北京时间 10:30 左右，自动抓取 [Dataconomy CN](https://cn.dataconomy.com/) 最新 10 条科技资讯，通过 AI 生成摘要要点，渲染成精美邮件推送到指定邮箱。

**全程零成本，完全自动化。**

## 功能特性

- **资讯速览**：调用 Google Gemini 2.5 Flash 从当天资讯中提炼 2-3 条核心要点，30 秒掌握今日关键信息
- **智能排序**：文章按分类优先级排列（Tech > 研究 > 人工智能 > 消息 > 行业 > 网络安全），速览引用的文章置顶
- **内容清洁**：自动清理源站机翻残留（`<小时>`、"精选图片来源"等垃圾内容），正文超过 350 字自动截断
- **去重推送**：同一篇文章只推送一次，无新内容时自动跳过
- **抄送支持**：通过 `cc_list.txt` 配置抄送列表，每行一个邮箱
- **优雅降级**：AI 摘要生成失败时，邮件正常发送，不影响推送

## 架构

```
GitHub Actions 定时触发（每天 UTC 02:23 ≈ 北京 10:23）
  → 通过 Cloudflare Worker 代理抓取 RSS（绕过 Cloudflare WAF）
  → 过滤已发送文章（state.json 去重）
  → 按分类优先级排序
  → 调用 Gemini 2.5 Flash 生成资讯速览
  → 渲染 HTML + 纯文本双版本邮件
  → Gmail SMTP 发送（支持 CC 抄送）
  → 更新 state.json 并自动提交到仓库
```

## 技术栈

| 组件 | 方案 | 费用 |
|------|------|------|
| 定时运行 | GitHub Actions | 免费 |
| 数据来源 | Cloudflare Worker 代理 RSS | 免费 |
| AI 摘要 | Google Gemini 2.5 Flash | 免费 |
| 邮件发送 | Gmail SMTP（SSL 465） | 免费 |
| 模板渲染 | Jinja2 | — |
| RSS 解析 | feedparser | — |

## 项目结构

```
├── .github/workflows/daily-digest.yml   # GitHub Actions 定时工作流
├── src/
│   ├── main.py            # 主流程编排
│   ├── feed.py            # RSS 抓取与解析
│   ├── summarizer.py      # Gemini AI 摘要生成
│   ├── email_render.py    # HTML/纯文本邮件渲染
│   ├── mailer.py          # Gmail SMTP 发送
│   └── dedup.py           # 去重状态管理
├── cc_list.txt            # 抄送邮箱列表
├── state.json             # 去重持久化状态
└── requirements.txt       # Python 依赖
```

## 配置指南

### 1. Gmail 端

1. 开启 **两步验证**（Google 账户 → 安全）
2. 生成 **应用专用密码**（Google 账户 → 安全 → 应用专用密码），记下 16 位字符串

### 2. Gemini API Key

1. 打开 [Google AI Studio](https://aistudio.google.com/apikey)
2. 点击 **Create API Key** 生成

### 3. GitHub 端

1. 新建 **公共仓库**（免费 Actions 无限分钟）
2. Settings → Actions → General → **Workflow permissions** → 勾选 **Read and write permissions**
3. Settings → Secrets and variables → Actions，添加 4 个 Secret：

   | Name | 说明 |
   |------|------|
   | `SMTP_USER` | Gmail 地址 |
   | `SMTP_PASS` | Gmail 应用专用密码（16 位） |
   | `MAIL_TO` | 收件邮箱地址 |
   | `GEMINI_API_KEY` | Gemini API Key |

### 4. 抄送配置（可选）

编辑 `cc_list.txt`，每行一个邮箱地址，`#` 开头为注释：

```
alice@example.com
bob@example.com
```

### 5. 首次验证

1. Actions → **Run workflow** → 勾选「仅测试，不发邮件」→ 查看日志确认抓取正常
2. 再次 Run workflow → 勾选「忽略去重，强制发送」→ 确认收到邮件
3. 再跑一次（不勾选）→ 日志应显示 `No new items, skipping email.`

## 本地开发

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 只预览，不发邮件
python -m src.main --dry-run

# 真实发送
SMTP_USER=you@gmail.com SMTP_PASS=xxx MAIL_TO=to@example.com GEMINI_API_KEY=xxx \
  python -m src.main

# 跳过去重强制发送
python -m src.main --force-send
```

## 排障

| 问题 | 解决 |
|------|------|
| 收不到邮件 | 查 Actions 日志是否有 `Sent email`；检查垃圾邮件箱 |
| SMTP 登录失败 | 确认 Gmail 两步验证已开启，`SMTP_PASS` 是应用专用密码 |
| AI 摘要为空 | 查日志是否有 `GEMINI_API_KEY not set` 或 `AI summary failed`；确认 Secret 已配置 |
| Actions 不触发 | 公共仓库 60 天无活动会暂停 schedule，手动 Run workflow 一次即可恢复 |

## License

MIT
