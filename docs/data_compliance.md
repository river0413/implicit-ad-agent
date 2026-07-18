# 数据合规登记

## 1. 目的

记录数据来源、采集边界、条款检查和使用风险，作为 P1 数据地基的合规依据。

## 2. 最小字段

| 字段 | 说明 |
| --- | --- |
| source_name | 数据集或平台名称 |
| source_type | public_dataset / manual_public_collection / authorized_export |
| terms_or_license | 条款或许可证链接/来源 |
| checked_at | 实际检查日期 |
| allowed_use | 允许用途，例如研究/展示 |
| collection_method | 下载 / 人工录入 / 只读脚本 |
| fields_collected | 实际采集字段列表 |
| risk | 低 / 中 / 高 及理由 |
| decision | 可用 / 限制使用 / 停用 |
| owner | 责任人 |

## 3. 记录示例

- `source_name`: 微信公众号“品牌实验室”
- `source_type`: manual_public_collection
- `terms_or_license`: 平台公开内容，仅作研究引用，不保存个人隐私
- `checked_at`: 2026-07-18
- `allowed_use`: 数据标注、特征工程、论文分析
- `collection_method`: 只读爬虫，保留文本、媒体哈希、元数据
- `fields_collected`: post_id、platform、blogger_id、text、media、provenance
- `risk`: 中，可能含用户昵称/头像；已脱敏并去除直接身份信息
- `decision`: 可用（仅限内部研究）
- `owner`: D

## 4. 说明

- 所有来源必须至少对应一条记录。
- 条款不清楚时，默认不采集或仅保留统计特征。
- 真实原始内容若含身份信息，不直接提交 Git。
