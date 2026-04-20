# Dataconomy CN Daily Digest

每天北京时间 10:30 左右，从 <https://cn.dataconomy.com/feed/> 抓取最新 10 条资讯，
通过 Gmail SMTP 推送到指定邮箱。带去重（只发新文章），无服务器，全程免费。

## 架构

- 数据源：`https://cn.dataconomy.com/feed/`（WordPress RSS）
- 运行平台：GitHub Actions 定时触发（免费）
- 发件：Gmail SMTP（`smtp.gmail.com:465`，需 App Password）
- 去重：仓库内 `state.json` 保存已发送 GUID（最多 200 条），由 Action 自动回写

## 一次性配置

### 1. Gmail 端

1. 开启 **两步验证**（Google 账户 → 安全）
2. 生成 **应用专用密码**（Google 账户 → 安全 → 应用专用密码 → Mail / 其他）
   - 记下 16 位字符串（去掉空格）

### 2. GitHub 端

1. 新建 **公共仓库**（公共仓库 Actions 分钟数无上限）
2. 把本目录推送上去
3. Settings → Actions → General → **Workflow permissions** → 勾选 **Read and write permissions**
4. Settings → Secrets and variables → Actions → New repository secret，添加 3 个：

   | Name | 值 |
   |---|---|
   | `SMTP_USER` | 你的 Gmail 地址，如 `you@gmail.com` |
   | `SMTP_PASS` | 上一步的 16 位应用专用密码（无空格） |
   | `MAIL_TO`   | 收件邮箱地址 |

### 3. 首次联调

1. Actions 页 → `Daily Dataconomy CN Digest` → **Run workflow**
   - 勾选 `dry_run: true`，看日志 `Parsed 10 items` / `Subject: ...` / `HTML length: ...`
2. 再次 Run workflow，默认参数（不勾选）
   - 确认收到邮件；仓库根部自动多出一条 `chore: update state.json` commit
3. 立刻再 Run 一次
   - 日志应显示 `No new items, skipping email.`，且不产生新 commit

之后每天 UTC 02:23 自动触发（≈ 北京 10:23，加上 Actions 常见延迟约 10:30 到达）。

## 本地开发

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 只预览，不发邮件
python -m src.main --dry-run

# 真实发送（需要三个环境变量）
SMTP_USER=you@gmail.com SMTP_PASS=xxxxxxxxxxxxxxxx MAIL_TO=to@example.com \
  python -m src.main

# 跳过去重强制发 top 10
python -m src.main --force-send
```

## 排障

- **收不到邮件**：先查 Actions 日志是否出现 `Sent email: <Message-ID>`。收到了就查收件箱垃圾邮件 / 过滤规则。
- **SMTP 登录失败**：确认 Gmail 两步验证已开启，`SMTP_PASS` 是 App Password 而不是账号密码。
- **抓取 403**：代码已使用浏览器 UA + 重试。若 Cloudflare 持续拒绝，可把 `src/feed.py` 切到 WP REST API（`/wp-json/wp/v2/posts?per_page=10`）。
- **长期没有新文章**：Action 会跳过发送也不 commit state.json；公共仓库 60 天无活动会暂停 schedule。若遇到，改一下任意文件或手动 Run workflow 一次即可恢复。
