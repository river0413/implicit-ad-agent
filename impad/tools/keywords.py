"""广告信号关键词清单 + 6 维可解释特征。

两层用途：
1. 明广标识 / 软广信号词：供 NLP 专家的规则降级路径与占位专家做零成本快速判断。
2. 6 维关键词权重：把文案量化成一个可解释向量（促销/价格/紧迫/品牌/行动/自然），
   既能给 Judge 多一路证据、给前端画雷达图，也能进论文的可解释性分析。

权重是确定性计算（不依赖 LLM），因此零 Key、零联网也能产出，且可单测。
后续按《说明书》A~H 八大类关键词清单继续扩充；真实判定仍以 LLM 专家为主，
这里只做兜底信号与可解释特征。
"""
from __future__ import annotations

# ── 快速判定用的信号词 ────────────────────────────────────────────────
# 明广标识：出现即基本可判明广
EXPLICIT_AD_MARKERS = ("广告", "赞助", "推广", "合作", "#ad", "恰饭", "商务", "品牌方")

# 软广信号词：命中越多越可疑（hello_graph 与 nlp 规则降级共用同一份）
SOFT_AD_SIGNALS = ("亲测", "无限回购", "谁用谁知道", "求同款", "码住", "链接在评论",
                   "评论区", "被问爆", "闭眼入", "自留款", "相见恨晚", "空瓶记录")

# ── 6 维可解释特征的词表 ──────────────────────────────────────────────
# 维度字段名固定为英文（与训练管线 / 论文特征对齐，勿翻译）。
PROMOTION_WORDS = ("种草", "安利", "必买", "回购", "强烈推荐", "推荐", "爆款", "热卖",
                   "超赞", "真香", "宝藏", "好用到哭", "值得入", "闭眼入", "无限回购")
PRICE_WORDS = ("价格", "多少钱", "性价比", "划算", "超值", "便宜", "实惠", "优惠",
               "折扣", "特价", "促销", "满减", "到手价", "直降", "原价", "秒杀", "领券")
URGENCY_WORDS = ("限时", "抢购", "赶紧", "快来", "马上", "立刻", "立即", "不要错过",
                 "仅剩", "名额有限", "最后一天", "手慢无", "库存告急", "冲鸭")
BRAND_WORDS = ("品牌", "官方", "正品", "旗舰店", "专营", "授权", "代理", "招商",
               "加盟", "货源", "批发", "一件代发", "赞助", "恰饭")
ACTION_WORDS = ("点击", "扫码", "链接", "私信", "购买", "下单", "加购", "购物车",
                "小黄车", "点上方", "戳这里", "领取", "蹲一个", "冲同款")
NATURAL_WORDS = ("我觉得", "我认为", "感受", "体验", "心情", "日记", "分享", "记录",
                 "吐槽", "生活", "学习", "朋友", "家人", "今天", "昨天", "周末",
                 "假期", "随手记", "碎碎念")

# 维度顺序（外部消费方按此顺序渲染）
WEIGHT_DIMENSIONS = ("promotion_words", "price_mentions", "urgency_expressions",
                     "brand_mentions", "action_words", "natural_expression")

# 维度 → 词表
_CATEGORY_WORDS = {
    "promotion_words": PROMOTION_WORDS,
    "price_mentions": PRICE_WORDS,
    "urgency_expressions": URGENCY_WORDS,
    "brand_mentions": BRAND_WORDS,
    "action_words": ACTION_WORDS,
    "natural_expression": NATURAL_WORDS,
}

# 每维命中多少个不同词即饱和到 1.0（命中数越少即饱和 = 该维越敏感）
_SATURATION = {
    "promotion_words": 4,
    "price_mentions": 4,
    "urgency_expressions": 3,
    "brand_mentions": 3,
    "action_words": 3,
    "natural_expression": 5,
}

# 维度中文标签，仅用于报告/前端展示
WEIGHT_LABELS_ZH = {
    "promotion_words": "促销种草",
    "price_mentions": "价格提及",
    "urgency_expressions": "紧迫感",
    "brand_mentions": "品牌商务",
    "action_words": "行动召唤",
    "natural_expression": "自然表达",
}


def keyword_hits(text: str) -> dict[str, list[str]]:
    """返回每个维度命中的关键词（去重、保序），供证据展示。"""
    return {dim: [w for w in words if w in text]
            for dim, words in _CATEGORY_WORDS.items()}


def compute_keyword_weights(text: str) -> dict[str, float]:
    """把文案量化成 6 维 0~1 权重向量（确定性，无需 LLM）。

    每维 = min(该维命中的不同词数 / 饱和阈值, 1.0)，保留两位小数。
    """
    hits = keyword_hits(text)
    return {dim: round(min(len(hits[dim]) / _SATURATION[dim], 1.0), 2)
            for dim in WEIGHT_DIMENSIONS}


def ad_pressure(weights: dict[str, float]) -> float:
    """导购压力分：促销/价格/紧迫/行动四维的均值（不含品牌与自然表达）。

    用作规则降级里"未命中软广词但整体很像带货"的兜底信号。
    """
    keys = ("promotion_words", "price_mentions", "urgency_expressions", "action_words")
    return round(sum(weights.get(k, 0.0) for k in keys) / len(keys), 2)


def summarize_weights(weights: dict[str, float], top_k: int = 3) -> str:
    """挑权重最高的若干维拼成一句中文摘要，用于证据链/报告展示。"""
    ranked = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
    parts = [f"{WEIGHT_LABELS_ZH[k]} {v:.2f}" for k, v in ranked if v > 0][:top_k]
    return "、".join(parts) if parts else "无显著关键词信号"
