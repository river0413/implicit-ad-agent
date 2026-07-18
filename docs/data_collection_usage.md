# 公开内容采集与脱敏脚本使用说明

本说明针对 `scripts/data/crawl_public_posts.py` 编写，用于采集公开网页内容并对发布者名称与 ID 进行模糊化处理。

## 1. 目的

该脚本只做数据采集与脱敏，不做模型推断或标签生成。采集结果保存为 JSONL 文件，符合 P1 数据地基阶段的脱敏要求。

## 2. 依赖

请先安装项目依赖：

```bash
python -m pip install -r requirements.txt
```

## 3. 环境变量

在 `.env` 中添加并设置：

```text
ANONYMIZATION_SALT=your-secret-salt
```

该值用于生成稳定但不可逆的匿名 ID。

## 4. 输入文件格式

默认输入文件为 `data/raw/urls.txt`。每一行可以是：

- 仅 URL：
  ```text
  https://mp.weixin.qq.com/s/xxxxxxxxxxxx
  ```
- URL + 发布者名称 + 发布者 ID（用制表符分隔）：
  ```text
  https://mp.weixin.qq.com/s/xxxxxxxxxxxx	品牌实验室	weixin_user_123
  ```

脚本会尝试从 URL 抓取页面内容，并用发布者信息生成模糊化显示名与匿名 ID。

## 5. 默认输出

输出文件默认写入：

```text
data/interim/anonymized_posts.jsonl
```

每条记录示例：

```json
{
  "schema_version": "1.0",
  "post_id": "...",
  "platform": "wechat_official_account",
  "source_type": "manual_public_collection",
  "blogger_id": "...",
  "blogger_name": "B***g",
  "published_at": "2026-07-18T12:00:00+00:00",
  "text": "...",
  "media": [],
  "comments": [],
  "blogger_history_refs": [],
  "provenance": {
    "source_ref_hash": "...",
    "collected_at": "...",
    "collector": "D",
    "terms_checked_at": "2026-07-18"
  },
  "privacy": {
    "anonymized": true,
    "contains_sensitive_data": false
  }
}
```

## 6. 运行命令

### 6.1 使用默认输入/输出

```bash
python scripts/data/crawl_public_posts.py
```

### 6.2 指定输入输出与采集者

```bash
python scripts/data/crawl_public_posts.py --input data/raw/urls.txt --output data/interim/anonymized_posts.jsonl --collector D --terms-checked-at 2026-07-18
```

### 6.3 常见参数说明

- `--input`: 输入 URL 列表文件，默认 `data/raw/urls.txt`
- `--output`: 输出 JSONL 文件，默认 `data/interim/anonymized_posts.jsonl`
- `--collector`: 采集者标识，建议单字符如 `D` 或 `N`
- `--terms-checked-at`: 条款检查日期，格式 `YYYY-MM-DD`

## 7. 注意事项

- 脚本仅抓取公开页面内容，不处理登录、验证码或私密接口。
- 采集前请确认目标页面是否允许公开内容采集。
- `ANONYMIZATION_SALT` 必须设置，否则脚本会报错。
- 若页面抓取失败，会在 STDERR 打印失败信息，脚本继续处理下一条 URL。

## 8. 后续处理建议

- 使用 `scripts/data/validate_schema.py` 校验输出记录。
- 使用 `scripts/data/normalize_and_deduplicate.py` 做文本归一与去重。
- 采集结果可作为候选池数据进入下游标注流程。
