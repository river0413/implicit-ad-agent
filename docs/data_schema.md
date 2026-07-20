# 数据 Schema（v1.0，已废弃）

> ⚠️ **本文档为旧版 v1.0，已不再使用。**  
> 新版 v2.0 schema 定义及设计讨论请参见：[`资料/Schema设计讨论与字段取舍.md`](../资料/Schema设计讨论与字段取舍.md)

## 1. 版本与文件说明

- `schema_version`: 当前版本号，例如 `1.0`
- 内容数据与标注数据分离，标注文件只通过 `post_id` 关联。

## 2. 内容记录字段

```json
{
  "schema_version": "1.0",
  "post_id": "post_000001",
  "platform": "wechat_official_account",
  "source_type": "manual_public_collection",
  "blogger_id": "blogger_7b32...",
  "blogger_name": "B***g",
  "published_at": "2026-07-01T10:00:00+08:00",
  "text": "...",
  "media": [],
  "comments": [],
  "blogger_history_refs": [],
  "provenance": {},
  "privacy": {}
}
```

### 2.1 必填字段

- `schema_version`
- `post_id`
- `platform`
- `source_type`
- `blogger_id`
- `blogger_name`
- `text`
- `media`
- `provenance`
- `privacy`

### 2.2 规范说明

- `blogger_id` 使用带项目私有盐的稳定哈希生成，不包含真实昵称。
- `blogger_name` 为模糊化显示名，避免直接保存真实用户名或 ID。
- `media` 内只保留局部引用、SHA-256、感知哈希等脱敏信息。
- `provenance` 必须包含 `source_ref_hash`、`collected_at`、`collector`、`terms_checked_at`。
- 未知值使用 `null` 或空数组，不使用“未知”“无”等混合占位字符串。

## 3. 标注记录字段

```json
{
  "post_id": "post_000001",
  "annotator_id": "N",
  "guide_version": "1.0",
  "label": "暗广",
  "confidence": 0.8,
  "evidence_codes": ["C", "P", "A"],
  "evidence": [],
  "uncertain_reason": null,
  "annotated_at": "2026-07-28T14:30:00+08:00"
}
```

### 3.1 标注字段说明

- `confidence` 表示标注者对规则适用性的把握，不参与标签投票。
- 置信度低于 0.6 的样本自动进入复核队列。
- `evidence_codes` 应与 `annotation_guide.md` 中的证据编码一致。
