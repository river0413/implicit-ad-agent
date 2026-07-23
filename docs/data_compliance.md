# 数据合规登记 (v1.1)

> 更新日期：2026-07-23  
> 变更：v1.0 → v1.1：从模板框架更新为真实来源台账，补充微信公众号采集记录和三层数据输出控制。

## 1. 目的

记录数据来源、采集边界、条款检查和使用风险，作为 P1 数据地基的合规依据。

## 2. 来源台账

### 2.1 微信公众号公开内容

| 字段 | 值 |
|------|-----|
| source_name | 微信公众号公开文章 |
| source_type | manual_public_collection |
| terms_or_license | 平台公开内容，仅作研究引用（合理使用），不保存个人隐私 |
| checked_at | 2026-07-23 |
| allowed_use | 数据标注、特征工程、论文分析（内部研究） |
| collection_method | 只读爬虫 + Playwright 渲染，保留文本、媒体哈希、元数据 |
| fields_collected | post_id, platform, blogger_id, published_at, title, text, media (ref/sha256/phash/ocr_text), comments, blogger_history_refs, provenance, privacy |
| risk | 中 — 可能含用户昵称/头像/联系方式；需脱敏并去除直接身份信息 |
| decision | 可用（仅限内部研究，raw 层不对外） |
| owner | D |
| notes | 采集结果先写受控 raw 层 → 脱敏后进入 interim → 经隐私扫描确认后进入 public |

### 2.2 公开许可数据集（规划中）

| 字段 | 值 |
|------|-----|
| source_name | 待定 |
| source_type | public_dataset |
| terms_or_license | 待确认 |
| checked_at | — |
| allowed_use | 研究用途 |
| collection_method | 直接下载 |
| fields_collected | 依数据集 schema 而定 |
| risk | 低（公开许可数据集） |
| decision | 待确认 |
| owner | D |

### 2.3 模拟/合成数据

| 字段 | 值 |
|------|-----|
| source_name | P1 团队合成数据 |
| source_type | synthetic |
| terms_or_license | 团队自有，无第三方权利限制 |
| checked_at | 2026-07-21 |
| allowed_use | 任意研究用途（含公开） |
| collection_method | 人工编写 |
| fields_collected | 同 v1.1 schema |
| risk | 无 — 不含任何真实个人信息 |
| decision | 可用（可对外公开） |
| owner | D |

## 3. 字段定义

| 字段 | 说明 |
|------|------|
| source_name | 数据集或平台名称 |
| source_type | public_dataset / manual_public_collection / authorized_export / synthetic |
| terms_or_license | 条款或许可证链接/来源 |
| checked_at | 实际检查日期（YYYY-MM-DD） |
| allowed_use | 允许用途，例如研究/展示 |
| collection_method | 下载 / 人工录入 / 只读脚本 / 浏览器渲染 |
| fields_collected | 实际采集字段列表 |
| risk | 低 / 中 / 高 及理由 |
| decision | 可用 / 限制使用 / 停用 |
| owner | 责任人 |

## 4. 三层数据输出控制

所有采集数据按以下三层管理：

| 层级 | 目录 | 说明 | 对外发布 |
|------|------|------|----------|
| raw | `data/raw/` | 原始采集结果，可能含未脱敏信息 | ❌ 禁止 |
| interim | `data/interim/` | 已脱敏但未经隐私扫描确认 | ❌ 禁止 |
| public | `data/public/` | 经隐私扫描确认，对外发布许可清单中 | ✅ 允许 |

## 5. 说明

- 所有来源必须至少对应一条记录。
- 条款不清楚时，默认不采集或仅保留统计特征。
- 真实原始内容若含身份信息，不直接提交 Git。
- 对外发布前必须运行 `scripts/data/privacy_scan.py` 确认。
- 采集结果不直接声称已脱敏；必须经过 raw → interim → public 三层处理。
