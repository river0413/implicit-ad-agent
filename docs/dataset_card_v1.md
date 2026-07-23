# Dataset Card v1.1

> 更新日期：2026-07-23  
> 变更：v1.0 → v1.1：从目标描述更新为可执行统计模板，补充三层数据输出和隐私扫描说明。

## 1. 数据集概述

- 名称：隐性广告三元标签数据集 v1
- 版本：1.1（对应 data_schema v1.1）
- 标签：明广 / 暗广 / 非广
- 架构：内容记录与标注记录分离，通过 `post_id` 关联
- 语言：中文（简体）
- 许可证：内部研究使用；公开样例为 CC BY-NC-SA 4.0

## 2. 数据来源与合规

| 来源 | 类型 | 合规状态 | 备注 |
|------|------|----------|------|
| 微信公众号公开文章 | manual_public_collection | ✅ 已登记 | 仅内部研究使用 |
| 公开许可数据集 | public_dataset | ⏳ 待确认 | — |
| 团队合成数据 | synthetic | ✅ 可公开 | 不含真实个人信息 |

详见 `docs/data_compliance.md`（v1.1 来源台账）。

## 3. 数据划分

- 划分比例：train 70% / dev 15% / test 15%
- 划分原则：按 `blogger_id` + `content_group_id` 双重约束分组，避免同博主/同内容组跨集泄漏
- 划分脚本：`scripts/data/split_by_blogger.py`

## 4. Schema

- 权威 Schema：`data/schema/data_schema_v1_1.json`
- 内容记录必填字段：`schema_version`, `post_id`, `platform`, `source_type`, `blogger_id`, `text`, `media`, `provenance`, `privacy`
- v1.1 新增可选字段：`title`, `content_group_id`
- v1.1 新增平台枚举：`bilibili`

## 5. 数据输出层级

| 层级 | 目录 | 可对外 | 说明 |
|------|------|--------|------|
| raw | `data/raw/` | ❌ | 原始采集，可能含 PII |
| interim | `data/interim/` | ❌ | 脱敏后，未完成隐私扫描 |
| public | `data/public/` | ✅ | 通过隐私扫描，不含可识别信息 |

## 6. 质量与限制

- 仅保留脱敏内容与结构化特征
- 不使用模型预测标签代替人工标注
- `test` 集未参与规则调试
- LLM 抽取结果保留 `needs_review` 标记，不自动成为正式内容
- 标注分歧必须仲裁后才进入金标
- `uncertain` / `out_of_scope` 默认不进 gold

## 7. 统计字段（由脚本自动生成）

以下统计由 `scripts/data/report_p1_migration.py` 自动计算：

- 总样本量
- 标签分布（明广 / 暗广 / 非广）
- 平台分布
- 标注者间 Cohen's κ
- 仲裁样本数
- 排除样本数及原因分布

## 8. 伦理与使用说明

- 保持真实身份信息脱敏
- 对外发布仅提供脱敏样例与统计信息
- 不公开含个人手机号、昵称、头像、精确地址等敏感信息
- 对外发布前运行 `scripts/data/privacy_scan.py` 生成许可清单
