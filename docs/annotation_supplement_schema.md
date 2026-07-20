# 标注补充 Schema：图像分析与 Markdown 备注

> 版本：1.0  
> 日期：2026-07-21  
> 用途：定义标注过程中图像分析结果与标注者 Markdown 备注的数据结构，作为主标注记录的**可选补充字段**，实现多模态证据的结构化存储。

---

## 一、设计动机

主标注记录（见 `annotation_guide.md`）关注的是标注者的**最终判定**。但在实际标注中，以下两类信息同样有价值：

1. **图像分析结果**：帖子中的图片可能包含 Logo、价格表、二维码、产品特写等视觉商业证据（证据代码 `V`），这些需要结构化记录以便后续审计和模型训练。
2. **标注者备注**：标注者在判定过程中可能有额外的观察、疑虑或需要团队讨论的边界问题，用 Markdown 格式记录最为灵活。

本 Schema 定义这两类补充信息的 JSON 结构，与主标注记录通过 `post_id` + `annotator_id` 关联。

---

## 二、顶层结构

```json
{
  "post_id": "7b238a6e425616a2111d7357",
  "annotator_id": "D",
  "supplement_version": "1.0",
  "image_analyses": [],
  "markdown_notes": "",
  "edge_case_discussion": null,
  "created_at": "2026-07-21T15:30:00+08:00",
  "updated_at": "2026-07-21T16:00:00+08:00"
}
```

### 2.1 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `post_id` | string | ✅ | 关联的帖子 ID，与内容 JSONL 中的 `post_id` 一致 |
| `annotator_id` | string | ✅ | 标注人 ID（D/N/L） |
| `supplement_version` | string | ✅ | Schema 版本号，当前 `"1.0"` |
| `image_analyses` | array | ✅ | 图像分析结果列表，无图片时为空数组 `[]` |
| `markdown_notes` | string | ✅ | 标注者的 Markdown 格式备注，无备注时为空串 `""` |
| `edge_case_discussion` | object\|null | ❌ | 边界案例讨论记录，非边界时为 `null` |
| `created_at` | string | ✅ | 补充记录创建时间，ISO 8601 `+08:00` |
| `updated_at` | string | ✅ | 补充记录最后更新时间，ISO 8601 `+08:00` |

---

## 三、`image_analyses[]` 图像分析条目

```json
{
  "media_ref": "media/7b238a6e425616a2111d7357/03.jpg",
  "source_url": "https://mmbiz.qpic.cn/xxx",
  "image_index": 3,
  "analysis_method": "manual",
  "description": "OpenClaw 技能安装步骤截图，终端界面显示命令行操作",
  "ocr_text": "下载并安装这个skills\nhttps://wry-manatee-359.convex.site/api/v1/download?slug=lerwee-api",
  "detected_elements": {
    "has_logo": true,
    "has_qr_code": false,
    "has_price_info": false,
    "has_product_image": false,
    "has_chart_or_table": false,
    "has_promotional_text": true,
    "has_contact_info": false
  },
  "visual_evidence_codes": ["V"],
  "relevance_to_annotation": "图片展示了具体的下载链接和安装操作，属于转化引导类视觉证据",
  "image_quality_notes": "清晰，文字可读",
  "analyzed_at": "2026-07-21T15:35:00+08:00"
}
```

### 3.1 `image_analyses[]` 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `media_ref` | string | ✅ | 图片本地路径引用，对应内容记录中 `media[].ref` |
| `source_url` | string | ❌ | 图片原始 URL，用于溯源 |
| `image_index` | integer | ✅ | 图片在正文中的序号（对应 `<图片N>` 标记中的 N） |
| `analysis_method` | enum | ✅ | `manual`（人工分析）/ `llm_vision`（视觉 LLM 分析）/ `ocr_auto`（自动 OCR）/ `hybrid`（混合） |
| `description` | string | ✅ | 图片内容的自然语言描述（1-3 句话） |
| `ocr_text` | string | ❌ | 图片中提取的文字内容（OCR 结果或人工转录），无文字时为 `null` |
| `detected_elements` | object | ✅ | 检测到的视觉元素标志位（见 §3.2） |
| `visual_evidence_codes` | array | ✅ | 该图片支持的证据代码列表，限 `V`/`A`/`D`，无则为 `[]` |
| `relevance_to_annotation` | string | ✅ | 该图片对标注判定的影响说明（1-2 句话） |
| `image_quality_notes` | string | ❌ | 图片质量问题（模糊、水印遮挡、裁切等），正常时填 `"清晰"` |
| `analyzed_at` | string | ✅ | 图像分析时间，ISO 8601 `+08:00` |

### 3.2 `detected_elements` 标志位

| 标志 | 类型 | 说明 |
|------|------|------|
| `has_logo` | boolean | 是否包含品牌 Logo 或商标 |
| `has_qr_code` | boolean | 是否包含二维码 |
| `has_price_info` | boolean | 是否包含价格、折扣、优惠金额信息 |
| `has_product_image` | boolean | 是否包含产品特写或白底商品图 |
| `has_chart_or_table` | boolean | 是否包含销量图表、对比表格 |
| `has_promotional_text` | boolean | 图片内是否包含促销文案（如"限时优惠""买一送一"） |
| `has_contact_info` | boolean | 是否包含微信号、手机号、店铺名等联系方式 |

### 3.3 `visual_evidence_codes` 映射规则

| 检测到的视觉元素 | 对应的证据代码 |
|-------------------|----------------|
| `has_logo` + `has_product_image` | `V`（视觉商业证据） |
| `has_qr_code` 或 `has_contact_info` | `A`（转化动作，扫码/联系即转化） |
| `has_promotional_text` 且含"广告""合作"等字眼 | `D`（明示商业关系，需 OCR 文本确认） |
| `has_price_info` + `has_promotional_text` | `V` + 可能触发 `P`（需结合正文判断） |

---

## 四、`markdown_notes` 标注者备注

`markdown_notes` 是一个**自由格式的 Markdown 字符串**，标注者可在其中记录：

- 判定过程中的疑虑和思考
- 对 LLM 建议的修正理由
- 发现的边界问题
- 需要团队讨论的事项
- 对特定证据的补充说明

### 4.1 建议的 Markdown 模板

```markdown
## 判定思考

- 本文虽以技术科普为主，但后半部分集中介绍了乐维产品，有明确的产品名称和下载链接
- LLM 建议为"暗广"，本人认为证据充分，采纳

## 证据补充

- 正文中出现的 URL（https://forum.lwops.cn/...）是明确的转化入口
- 图片 12-24 展示了产品界面和操作流程，属于视觉商业证据

## 疑虑

- 文章前半部分确实是技术内容，是否存在"软文"与"科普"的边界模糊？
- 建议团队讨论：技术教程中含产品下载链接是否一律视为暗广？

## 需要讨论

- [ ] 带有安装教程的产品介绍文章，边界如何划定？
```

### 4.2 与主标注记录的协作

`markdown_notes` 不替代主标注记录中的 `evidence` 字段。两者的分工：

| 维度 | `evidence`（主记录） | `markdown_notes`（补充记录） |
|------|---------------------|---------------------------|
| 内容 | 简洁的证据描述列表 | 详细的推理过程和备注 |
| 用途 | 计算 κ、训练模型、审计 | 团队沟通、规范修订、知识沉淀 |
| 格式 | 字符串数组 | Markdown 自由文本 |
| 是否必填 | ✅ | ❌（但强烈建议在边界案例中填写） |

---

## 五、`edge_case_discussion` 边界案例讨论

当标注者认为当前帖子属于边界案例时，可填写此结构：

```json
{
  "is_edge_case": true,
  "edge_case_category": "技术教程含产品推广",
  "difficulty": "hard",
  "alternative_label": "暗广",
  "reason_for_uncertainty": "文章前60%为运维技术科普，后40%突然转入Lerwee产品介绍并提供下载链接。前半部分具有独立的信息价值，后半部分有明确的商业推广特征。是否应整体判为暗广，还是需要分段评估？",
  "suggested_guide_update": "建议在边界案例中增加：'技术教程类文章，若教程部分与推广部分可清晰分割，且教程部分有独立的信息价值，标记时需注明判定依据偏向哪一部分'",
  "needs_team_discussion": true,
  "discussion_tags": ["软文边界", "技术vs推广", "混合内容"]
}
```

### 5.1 `edge_case_discussion` 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `is_edge_case` | boolean | ✅ | 是否属于边界案例 |
| `edge_case_category` | string | ❌ | 边界案例类型标签 |
| `difficulty` | enum | ❌ | `easy` / `medium` / `hard` |
| `alternative_label` | string | ❌ | 另一种可能的标签 |
| `reason_for_uncertainty` | string | ❌ | 不确定性的具体原因 |
| `suggested_guide_update` | string | ❌ | 对标注规范修订的建议 |
| `needs_team_discussion` | boolean | ❌ | 是否需要团队讨论 |
| `discussion_tags` | array | ❌ | 讨论标签，便于后续分类检索 |

---

## 六、完整 JSON Schema（Draft-07）

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "https://implicit-ad-agent/schemas/annotation-supplement-v1.json",
  "title": "Annotation Supplement",
  "description": "图像分析与 Markdown 备注的补充标注记录",
  "type": "object",
  "required": [
    "post_id",
    "annotator_id",
    "supplement_version",
    "image_analyses",
    "markdown_notes",
    "created_at",
    "updated_at"
  ],
  "properties": {
    "post_id": {
      "type": "string",
      "description": "关联的帖子 ID",
      "minLength": 1
    },
    "annotator_id": {
      "type": "string",
      "description": "标注人 ID",
      "minLength": 1
    },
    "supplement_version": {
      "type": "string",
      "description": "Schema 版本",
      "const": "1.0"
    },
    "image_analyses": {
      "type": "array",
      "description": "图像分析结果列表",
      "items": { "$ref": "#/definitions/image_analysis" }
    },
    "markdown_notes": {
      "type": "string",
      "description": "Markdown 格式的标注者备注"
    },
    "edge_case_discussion": {
      "oneOf": [
        { "type": "null" },
        { "$ref": "#/definitions/edge_case_discussion" }
      ]
    },
    "created_at": {
      "type": "string",
      "format": "date-time",
      "description": "创建时间 ISO 8601 +08:00"
    },
    "updated_at": {
      "type": "string",
      "format": "date-time",
      "description": "更新时间 ISO 8601 +08:00"
    }
  },
  "definitions": {
    "image_analysis": {
      "type": "object",
      "required": [
        "media_ref",
        "image_index",
        "analysis_method",
        "description",
        "detected_elements",
        "visual_evidence_codes",
        "relevance_to_annotation",
        "analyzed_at"
      ],
      "properties": {
        "media_ref": { "type": "string" },
        "source_url": { "type": "string" },
        "image_index": { "type": "integer", "minimum": 1 },
        "analysis_method": {
          "type": "string",
          "enum": ["manual", "llm_vision", "ocr_auto", "hybrid"]
        },
        "description": { "type": "string", "minLength": 1 },
        "ocr_text": { "type": ["string", "null"] },
        "detected_elements": { "$ref": "#/definitions/detected_elements" },
        "visual_evidence_codes": {
          "type": "array",
          "items": { "type": "string", "enum": ["V", "A", "D"] }
        },
        "relevance_to_annotation": { "type": "string", "minLength": 1 },
        "image_quality_notes": { "type": "string" },
        "analyzed_at": { "type": "string", "format": "date-time" }
      }
    },
    "detected_elements": {
      "type": "object",
      "required": [
        "has_logo",
        "has_qr_code",
        "has_price_info",
        "has_product_image",
        "has_chart_or_table",
        "has_promotional_text",
        "has_contact_info"
      ],
      "properties": {
        "has_logo": { "type": "boolean" },
        "has_qr_code": { "type": "boolean" },
        "has_price_info": { "type": "boolean" },
        "has_product_image": { "type": "boolean" },
        "has_chart_or_table": { "type": "boolean" },
        "has_promotional_text": { "type": "boolean" },
        "has_contact_info": { "type": "boolean" }
      }
    },
    "edge_case_discussion": {
      "type": "object",
      "required": ["is_edge_case"],
      "properties": {
        "is_edge_case": { "type": "boolean" },
        "edge_case_category": { "type": "string" },
        "difficulty": {
          "type": "string",
          "enum": ["easy", "medium", "hard"]
        },
        "alternative_label": {
          "type": "string",
          "enum": ["明广", "暗广", "非广", "out_of_scope"]
        },
        "reason_for_uncertainty": { "type": "string" },
        "suggested_guide_update": { "type": "string" },
        "needs_team_discussion": { "type": "boolean" },
        "discussion_tags": {
          "type": "array",
          "items": { "type": "string" }
        }
      }
    }
  }
}
```

---

## 七、与 P1 工作流的集成

### 7.1 存储位置

```
data/annotations/
├── D_20260721_143000.jsonl          ← 主标注记录（manual_review_annotate.py 产出）
├── N_20260721_150000.jsonl
├── supplements/                      ← 补充记录目录
│   ├── D_20260721_143000_supplements.jsonl
│   └── N_20260721_150000_supplements.jsonl
```

### 7.2 生成时机

- **图像分析**：标注者在审阅帖子图片时可逐张填写（推荐），也可在标注完成后批量补充。未来可集成视觉 LLM（Qwen-VL / GPT-4V）自动生成初稿。
- **Markdown 备注**：标注者在判定过程中随时记录，建议在 `confidence < 0.7` 或遇到边界案例时**必须填写**。

### 7.3 审计与回溯

补充记录的 `updated_at` 字段追踪修改时间，配合 `markdown_notes` 中的修订历史（如标注者在讨论后修改了判定），形成完整的决策审计链。

---

## 八、示例：完整补充记录

```json
{
  "post_id": "7b238a6e425616a2111d7357",
  "annotator_id": "D",
  "supplement_version": "1.0",
  "image_analyses": [
    {
      "media_ref": "media/7b238a6e425616a2111d7357/03.jpg",
      "source_url": "https://mmbiz.qpic.cn/xxx",
      "image_index": 3,
      "analysis_method": "manual",
      "description": "OpenClaw 技能安装步骤截图，终端界面显示命令行操作",
      "ocr_text": "下载并安装这个skills\nhttps://wry-manatee-359.convex.site/api/v1/download?slug=lerwee-api",
      "detected_elements": {
        "has_logo": true,
        "has_qr_code": false,
        "has_price_info": false,
        "has_product_image": false,
        "has_chart_or_table": false,
        "has_promotional_text": true,
        "has_contact_info": false
      },
      "visual_evidence_codes": ["V"],
      "relevance_to_annotation": "图片展示了具体的下载链接和安装操作，属于转化引导类视觉证据",
      "image_quality_notes": "清晰，文字可读",
      "analyzed_at": "2026-07-21T15:35:00+08:00"
    },
    {
      "media_ref": "media/7b238a6e425616a2111d7357/20.jpg",
      "source_url": "https://mmbiz.qpic.cn/yyy",
      "image_index": 20,
      "analysis_method": "manual",
      "description": "微信群二维码，引导读者扫码加入 LerweeClaw 探索群",
      "ocr_text": "扫码加入Lerwee运维智能体×OpenClaw探索群",
      "detected_elements": {
        "has_logo": false,
        "has_qr_code": true,
        "has_price_info": false,
        "has_product_image": false,
        "has_chart_or_table": false,
        "has_promotional_text": true,
        "has_contact_info": true
      },
      "visual_evidence_codes": ["A", "V"],
      "relevance_to_annotation": "微信群二维码是明确的私域导流转化动作，强化了暗广判定",
      "image_quality_notes": "清晰",
      "analyzed_at": "2026-07-21T15:36:00+08:00"
    }
  ],
  "markdown_notes": "## 判定思考\n\n本文是典型的'技术科普 + 产品推广'混合型软文。前半部分介绍 OpenClaw 的爆火现象和运维痛点，中间部分集中展示 Lerwee 产品的四大 Skill 及安装教程，末尾附微信群二维码和社区链接。\n\n全文有明确的商业对象（Lerwee/LerweeClaw），多处下载链接（A），微信群二维码（A+M），且图片中展示了具体的产品界面和操作流程（V）。虽有技术科普内容，但整体服务于产品推广目标。\n\nLLM 建议为'暗广'，本人完全同意，证据充分无争议。\n\n## 证据补充\n\n- 正文中的 forum.lwops.cn 链接和 clawhub.ai 链接构成转化入口\n- 图片 20-24 包含微信群二维码和社区引导\n- 行文风格从'火出圈'的话题引入到产品功能介绍，是典型的营销漏斗结构\n\n## 疑虑\n\n无明显疑虑，本文是较为清晰的高质量暗广样本。\n",
  "edge_case_discussion": null,
  "created_at": "2026-07-21T15:30:00+08:00",
  "updated_at": "2026-07-21T15:40:00+08:00"
}
```
