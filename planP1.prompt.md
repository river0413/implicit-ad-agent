## P1 数据地基与标注规范执行方案

TL;DR: 按照 P1 文档，执行一个 4 周的数据基线和标注规范建设流程，从合规与 Schema 定义起步，经两轮试标、正式双标、仲裁与切分，最终交付 v1 金标数据与数据卡。该计划优先保证可追溯、可复现、可审计，并严格避免在本阶段训练模型或公开真实个人信息。

步骤
1. 初始化仓库交付结构
   - 在仓库内确认并逐步建立目录：`docs/`、`data/raw/`、`data/interim/`、`data/annotations/`、`data/splits/`、`data/reports/`、`scripts/data/`
   - 创建关键文档框架：`docs/data_compliance.md`、`docs/data_schema.md`、`docs/annotation_guide.md`、`docs/annotation_changelog.md`、`docs/dataset_card_v1.md`
   - 规划脚本模板：`validate_schema.py`、`normalize_and_deduplicate.py`、`calculate_agreement.py`、`build_gold_dataset.py`、`split_by_blogger.py`

2. 第 1 周：合规与候选池搭建
   - 建立来源台账与合规登记，记录来源、条款、检查日期、允许用途、采集方式、字段范围、风险结论、责任人
   - 确认数据来源优先级：公开许可数据集 > 公开内容人工收集 > 受控只读采集
   - 冻结 `data_schema` v0.1，准备至少 30 条脱敏样本覆盖文本/图片/评论/历史信息
   - 制定去重规则与 provenance 要求；每条候选样本必须保留可追溯 provenance 信息
   - 收集第一批 300–500 条候选样本
   - 周末检查：随机 30 条样本可追溯来源，通过 Schema 校验，不含直接身份信息

3. 第 2 周：标注规范与试标
   - N 起草标签判定树和证据编码；D 起草标注表单、冲突记录、κ 脚本
   - 进行第一轮盲标 100 条，覆盖显性和边界样本，两人独立完成
   - 计算原始一致率、Cohen’s κ、3×3 混淆矩阵，分析分歧集中区域
   - 复盘分歧并修订规范；只把达成共识的规则写入文档
   - 进行第二轮盲标 150 条；如果 κ≥0.6 且没有单一类别系统性崩坏，则冻结 `annotation_guide v1.0`
   - 周末检查：标注规范 v1.0、≥20 个边界案例、第二轮 κ≥0.6

4. 第 3 周：扩池与正式双标
   - 扩充候选池到 ≥3000 条，并根据类别缺口定向补采
   - 每天用 10 条校准题检查标注标准漂移，校准题不计入正式 κ
   - 两人独立对正式样本双标，提交后才允许查看对方标签
   - 每 300 条计算滚动 κ，重点复盘 `明广↔暗广` 和 `暗广↔非广` 混淆
   - 记录并分类冲突原因：`guide_gap`、`evidence_missed`、`scope_dispute`、`threshold_dispute`、`data_quality`、`human_error`
   - 规范每周最大修改一次，修订后保留旧样本的 `guide_version`
   - 目标完成约 900–1100 条正式双标

5. 第 4 周：仲裁、划分与数据卡
   - 完成正式双标，生成冲突样本盲审仲裁包
   - 仲裁包仅含样本、两方标签、证据，不提 annotator 姓名；L 每周一次盲审仲裁
   - 无法确定的样本进入 `uncertain_pool`，不入 `gold_v1`
   - 生成 `data/annotations/gold_v1.jsonl`，并按 `blogger_id`/`content_group_id` 做 train/dev/test 划分，目标 70/15/15
   - 做三类泄漏检查：同博主、近重复文本、近重复图片/同图；确认 test 集锁定且未用于规则调整
   - 产出最终报告：`quality_report_v1.json`、`source_distribution.csv`、`label_distribution.csv`、`leakage_report.txt`、`docs/dataset_card_v1.md`
   - 计算最终 κ，并保留两人原始标注、冲突与仲裁记录

6. 验收交付物
   - `docs/data_compliance.md`
   - `docs/data_schema.md` + ≥3 条脱敏样例
   - `docs/annotation_guide.md`（含 ≥20 个边界案例）
   - ≥1500 条仲裁后的金标数据
   - 两人独立原始标注记录、κ 计算结果、冲突与仲裁文件
   - `data/splits/train_ids.txt`、`dev_ids.txt`、`test_ids.txt`
   - `docs/dataset_card_v1.md`

关键原则
- 保留数据可追溯性，避免提交真实个人信息到仓库
- 独立标注与正式 κ 计算都基于两人原始标签
- 不能用模型预测或标签修正来凑类别数量
- 仲裁样本只在需要时启用，无法确认则归入 `uncertain_pool`
- 划分按博主/内容组做组级切分，防止泄漏

进一步建议
1. 将合规登记写成可审核的数据源台账，并明确采集边界和风险结论
2. 在 `docs/annotation_changelog.md` 中记录每次规范修订原因与版本
3. 用脚本自动生成统计报告，避免手工维护两套数字

验证方式
- 随机抽查候选样本追溯来源与脱敏结果
- 试标后计算 κ ≥0.6，并分析混淆矩阵
- 冲突样本是否有仲裁记录，无法确认样本是否进入 `uncertain_pool`
- 划分后检查是否存在博主、文本或图片泄漏
