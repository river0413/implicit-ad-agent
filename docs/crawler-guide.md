# 微信文章爬虫使用说明

> 基于 Playwright 的微信公众号文章抓取工具，支持 Sogou 搜索回退。

---

## 依赖环境

### Python 版本

`>= 3.10`

### 第三方库

| 库 | 版本 | 用途 |
|----|------|------|
| `requests` | ≥2.31 | HTTP 请求（抓取文章 HTML、调用微信 API） |
| `beautifulsoup4` | ≥4.12 | HTML 解析（提取 `__biz`、发布者名、文章链接） |
| `playwright` | ≥1.45 | 浏览器渲染（Sogou 页面渲染、加密链接跳转） |

### 浏览器依赖

`playwright` 需要下载 Chromium 浏览器二进制文件（约 300 MB）：

```bash
python -m playwright install chromium
```

> 💡 **国内网络镜像加速**（推荐）：
> ```powershell
> $env:PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright/"
> python -m playwright install chromium
> ```

### 一键安装

```bash
# 安装全部爬虫依赖
pip install requests beautifulsoup4 playwright
python -m playwright install chromium
```

### requirements.txt

项目的 `requirements.txt` 已包含爬虫依赖块：

```
# ---- 爬虫 / 数据采集 ----
requests>=2.31
beautifulsoup4>=4.12
playwright>=1.45            # 浏览器渲染（Sogou 回退 + 微信文章渲染）
```

### 环境变量（`.env`）

| 变量 | 说明 | 是否必需 |
|------|------|----------|
| `ANONYMIZATION_SALT` | 脱敏哈希盐值（用于内容匿名化） | 仅采集后处理时需要 |
| Cookie（`uin`/`key`/`pass_ticket`） | 微信文章阅读会话 | 可选，用于突破 `profile_ext` 限制 |

---

## 架构总览

```
crawl_wechat_from_article.py          ← 入口：传入一篇文章 URL
  │
  ├── ① 解析 __biz → 访问公众号主页 (profile_ext)
  │     ├── 解析 var msgList / app_msg_list
  │     └── 受限时自动提示（需微信 session）
  │
  ├── ② AJAX 分页接口 (getmsg)
  │     └── 需 uin / key / pass_ticket（手机微信 → 浏览器打开可获取）
  │
  └── ③ 🆕 Sogou + Playwright 回退
        └── sogou_wechat_crawler.py
              ├── 搜狗 type=2 文章搜索
              ├── 按 <span class="all-time-y2"> 过滤发布者
              └── 跟踪 /link?url= 加密跳转 → 真实微信 URL
```

---

## 快速开始

### 1. 环境准备

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

> 💡 国内网络：先设 `$env:PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright/"` 再安装。

### 2. 运行

```bash
# 方式 A：完整流程（自动回退到 Sogou）
python scripts/data/crawl_wechat_from_article.py \
  --url "https://mp.weixin.qq.com/s/xxxx" \
  --output data/raw/urls.txt \
  --render

# 方式 B：直接使用 Sogou 爬虫（推荐，跳过无效尝试）
python scripts/data/sogou_wechat_crawler.py \
  --account "公众号名称" \
  --max-articles 50 \
  --output data/raw/urls.txt
```

### 3. 输出格式

```
https://mp.weixin.qq.com/s?signature=xxxx	文章标题	公众号名称
https://mp.weixin.qq.com/s?signature=xxxx	文章标题	公众号名称
```

---

## Sogou + Playwright 爬虫详解

**文件**：`scripts/data/sogou_wechat_crawler.py`

### 工作原理

| 步骤 | 说明 |
|------|------|
| 1 | 用 Playwright 打开搜狗微信搜索 `type=2`（文章搜索） |
| 2 | 等待 JS 渲染完成，解析 HTML |
| 3 | 提取 `<span class="all-time-y2">` 获取发布者名 |
| 4 | 筛选发布者名匹配目标公众号的条目 |
| 5 | 在新标签页中跟随搜狗加密链接 `/link?url=...` |
| 6 | 等待 JS 重定向到 `mp.weixin.qq.com` |
| 7 | 清洗 URL（仅保留 `signature` 参数） |

### 命令行参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--account` | 必填 | 公众号名称（中文） |
| `--max-articles` | 50 | 最多收集文章数 |
| `--max-pages` | 10 | 最多搜索页数 |
| `--output` | `data/run_outputs/urls_from_sogou.txt` | 输出路径 |

### 实测数据

对"洲更的第二大脑"抓取结果（2026-07-18）：

| # | 标题 |
|---|------|
| 1 | wolai推出了我日思夜想的MCP,那么如何用呢? |
| 2 | 花了上亿token我开发了一个文献图片管理工具 |
| 3 | 分享图片 |
| 4 | 想用 Kindle Vibe,结果绕了一大圈 |

---

## Cookie 说明（可选，用于突破微信 session 限制）

### 需要哪些 Cookie

从手机微信"在浏览器中打开"文章后，需要三个参数：

| 字段 | 出现位置 | 说明 |
|------|----------|------|
| `uin` | API query string | 用户 ID |
| `key` | API query string | 会话密钥 |
| `pass_ticket` | API query string | 通行票据 |

### 获取方式

1. **手机微信** → 打开目标公众号任意文章
2. 点击右上角 `···` → **"在浏览器中打开"**
3. 浏览器中 `F12` → **Network** → 任意 `mp.weixin.qq.com` 请求
4. 看 **Query String Parameters**，找到上面三个值

### 使用方式

```bash
# 将 cookie 写入 .env
echo "uin=你的uin值" >> .env
echo "key=你的key值" >> .env
echo "pass_ticket=你的pass_ticket值" >> .env

# 运行
python scripts/data/crawl_wechat_from_article.py \
  --url "文章URL" \
  --cookies-env .env
```

> ⚠️ Cookie 有效期通常几小时，过期需重新获取。仅对同一公众号有效。

---

## 文件清单

| 文件 | 说明 |
|------|------|
| `scripts/data/crawl_wechat_from_article.py` | 主入口：从文章 URL 出发 |
| `scripts/data/sogou_wechat_crawler.py` | 🆕 Sogou + Playwright 爬虫 |
| `scripts/data/crawl_wechat_account.py` | 旧版搜狗回退（已停用） |
| `scripts/data/crawl_public_posts.py` | 单篇文章内容抓取 + 匿名化 |
| `scripts/data/normalize_and_deduplicate.py` | 文本规范化 + 去重 |
| `scripts/data/run_full_pipeline.py` | 端到端流水线 runner |
| `scripts/__init__.py` | 包初始化 |
| `scripts/data/__init__.py` | 子包初始化 |

---

## 已知限制

| 限制 | 影响 | 缓解方案 |
|------|------|----------|
| 微信 `profile_ext` 需 session | 无法直接从公众号主页获取文章 | Sogou 回退 |
| 搜狗搜索是基于关键词的 | 可能混入其他公众号文章 | 发布者名过滤 |
| Sogou 仅收录部分历史文章 | 无法获取全部文章 | — |
| Cookie 短期有效 | 需频繁重新获取 | Sogou 回退无需 cookie |
| Playwright 需额外安装 | 首次配置耗时 | 国内镜像加速 |
