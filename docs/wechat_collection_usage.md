# 按公众号名称批量收集文章 URL 使用说明

此工具通过搜狗微信搜索（weixin.sogou.com）检索指定公众号名称的相关文章 URL，并将结果写成 `data/raw/urls_from_account.txt` 供 `crawl_public_posts.py` 继续抓取并脱敏。

## 重要合规提醒
- 仅对公开可访问且符合平台条款的公众号进行采集。若条款或许可不清晰，请勿采集或先咨询法务/合规。 
- 不使用登录、模拟登录或绕过平台访问控制手段。脚本会对搜狗公开搜索结果进行抓取。
- 控制请求速率，避免对目标服务器造成高并发压力。

## 依赖
- `requests`
- `beautifulsoup4`

安装依赖：

```bash
python -m pip install requests beautifulsoup4
```

## 运行示例

默认示例（最多翻 5 页）：

```bash
python scripts/data/crawl_wechat_account.py --account "品牌实验室" --output data/raw/urls_from_account.txt
```

指定最大翻页数并带上发布者名：

```bash
python scripts/data/crawl_wechat_account.py --account "品牌实验室" --max-pages 10 --publisher-name "品牌实验室" --output data/raw/urls_brandlab.txt
```

运行完后，使用 `crawl_public_posts.py` 抓取并脱敏：

```bash
export ANONYMIZATION_SALT=your-secret-salt
python scripts/data/crawl_public_posts.py --input data/raw/urls_from_account.txt --output data/interim/anonymized_posts.jsonl --collector D --terms-checked-at 2026-07-18
```

（Windows PowerShell 用法）：

```powershell
$env:ANONYMIZATION_SALT = "your-secret-salt"
python scripts/data/crawl_public_posts.py --input data/raw/urls_from_account.txt --output data/interim/anonymized_posts.jsonl --collector D --terms-checked-at 2026-07-18
```

## 注意事项与故障排查
- 若搜狗返回反爬页面或无结果，尝试降低并发、增大延迟，或手工确认该公众号公开主页是否存在。
- 搜索结果可能包含跳转链接，`crawl_wechat_account.py` 尽可能提取 `mp.weixin.qq.com/s` 链接，但在某些情况下需要人工复核。
- 若需要更可靠的抓取（异步、浏览器渲染、验证码处理），考虑使用带人审合规批准的 Selenium 自动化或第三方抓取服务，并获得相应授权。

## 后续改进建议
- 使用缓存与断点续传，避免重复抓取。
- 对文章时间戳做去重和增量抓取，支持只抓取新文章。
- 在合规允许下，按 `__biz` 参数分组抓取公众号历史页，减少依赖第三方搜索。
