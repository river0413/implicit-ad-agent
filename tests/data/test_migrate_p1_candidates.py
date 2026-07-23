"""P1 候选数据迁移的单元测试。

使用固定的小 fixture 验证迁移逻辑，不加载真实数据。
"""
import json
import tempfile
from pathlib import Path
from typing import Dict, List

import pytest

# 将被测模块的路径加入
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def old_format_record() -> Dict:
    """一条典型的旧格式候选记录。"""
    return {
        "post_id": "7b238a6e425616a2111d7357",
        "platform": "wechat_official_account",
        "blogger_id": "20869c1e01481203e363a877",
        "published_at": "2026-03-24T08:58:00+08:00",
        "title": "测试文章标题",
        "text": "这是正文内容，包含<图片1>标记。",
        "media": [
            {
                "ref": "media/7b238a6e425616a2111d7357/00.jpg",
                "source_url": "https://example.com/img/00.jpg",
                "caption": "图片标注文字",
                "is_content": True,
            },
            {
                "ref": "media/7b238a6e425616a2111d7357/01.jpg",
                "source_url": "https://example.com/img/01.jpg",
                "caption": None,
                "is_content": True,
            },
        ],
        "comments": [],
        "blogger_history_refs": [],
        "_collected": {
            "source_url": "https://mp.weixin.qq.com/s/test",
            "collected_at": "2026-07-21T12:00:00+08:00",
            "collector": "P1_team",
            "terms_checked_at": None,
        },
    }


@pytest.fixture
def old_format_record_no_collected() -> Dict:
    """没有 _collected 字段的记录。"""
    return {
        "post_id": "abcdef1234567890abcdef12",
        "platform": "wechat",
        "blogger_id": "test_blogger_001",
        "text": "纯文本帖子，无图片。",
        "media": [],
        "comments": [],
        "blogger_history_refs": [],
    }


@pytest.fixture
def old_format_record_llm_review() -> Dict:
    """LLM 标记需复核的记录。"""
    return {
        "post_id": "llm_review_post_001",
        "platform": "wechat_official_account",
        "blogger_id": "blogger_test_002",
        "text": "需要LLM复核的帖子内容。",
        "media": [],
        "comments": [],
        "blogger_history_refs": [],
        "_collected": {
            "source_url": "https://example.com/post",
            "collected_at": "2026-07-21T12:00:00+08:00",
            "collector": "P1_team",
            "llm_needs_review": True,
            "llm_confidence": 0.3,
        },
    }


# ═══════════════════════════════════════════════════════════════
# 导入被测函数
# ═══════════════════════════════════════════════════════════════

from scripts.data.migrate_p1_candidates_to_v1 import (
    generate_stable_post_id,
    infer_media_type,
    migrate_media,
    migrate_provenance,
    migrate_privacy,
    migrate_record,
    load_jsonl,
    write_jsonl,
)


# ═══════════════════════════════════════════════════════════════
# Tests: post_id 生成
# ═══════════════════════════════════════════════════════════════

class TestPostIdGeneration:
    def test_generates_post_prefix(self):
        """生成的 post_id 应以 post_ 开头。"""
        new_id = generate_stable_post_id("test_hash_001")
        assert new_id.startswith("post_"), f"Expected post_ prefix, got {new_id}"

    def test_stable_mapping(self):
        """同一输入应始终产生同一输出。"""
        id1 = generate_stable_post_id("same_input", "salt")
        id2 = generate_stable_post_id("same_input", "salt")
        assert id1 == id2, "Same input should yield same output"

    def test_different_inputs_different_outputs(self):
        """不同输入应产生不同输出。"""
        id1 = generate_stable_post_id("input_a")
        id2 = generate_stable_post_id("input_b")
        assert id1 != id2, "Different inputs should yield different outputs"

    def test_different_salts_different_outputs(self):
        """不同盐值应产生不同输出。"""
        id1 = generate_stable_post_id("input", "salt_a")
        id2 = generate_stable_post_id("input", "salt_b")
        assert id1 != id2, "Different salts should yield different outputs"


# ═══════════════════════════════════════════════════════════════
# Tests: media 类型推断
# ═══════════════════════════════════════════════════════════════

class TestMediaTypeInference:
    def test_image_extensions(self):
        assert infer_media_type("photo.jpg") == "image"
        assert infer_media_type("photo.JPEG") == "image"
        assert infer_media_type("photo.PNG") == "image"
        assert infer_media_type("photo.gif") == "image"
        assert infer_media_type("photo.webp") == "image"

    def test_video_extensions(self):
        assert infer_media_type("video.mp4") == "video"
        assert infer_media_type("clip.mov") == "video"

    def test_unknown_extension(self):
        assert infer_media_type("file.xyz") == "other"
        assert infer_media_type("noextension") == "other"


# ═══════════════════════════════════════════════════════════════
# Tests: media 迁移
# ═══════════════════════════════════════════════════════════════

class TestMediaMigration:
    def test_migrates_format(self, old_format_record):
        """旧 media 格式应迁移到新格式。"""
        new_media = migrate_media(old_format_record["media"], Path("data"))
        assert len(new_media) == 2
        for item in new_media:
            assert "media_id" in item
            assert "type" in item
            assert "ref" in item
            assert "sha256" in item
            assert "phash" in item
            assert "ocr_text" in item

    def test_preserves_caption_as_ocr(self, old_format_record):
        """旧 caption 应迁移为 ocr_text。"""
        new_media = migrate_media(old_format_record["media"], Path("data"))
        assert new_media[0]["ocr_text"] == "图片标注文字"
        assert new_media[1]["ocr_text"] is None

    def test_empty_media(self):
        """空 media 列表返回空列表。"""
        result = migrate_media([], Path("data"))
        assert result == []

    def test_none_media(self):
        """None media 返回空列表。"""
        result = migrate_media(None, Path("data"))
        assert result == []

    def test_media_ids_are_sequential(self):
        """media_id 应按顺序生成。"""
        result = migrate_media([{"ref": "a.jpg"}, {"ref": "b.jpg"}], Path("data"))
        assert result[0]["media_id"] == "media_0000"
        assert result[1]["media_id"] == "media_0001"


# ═══════════════════════════════════════════════════════════════
# Tests: provenance 迁移
# ═══════════════════════════════════════════════════════════════

class TestProvenanceMigration:
    def test_migrates_from_collected(self, old_format_record):
        """_collected 应迁移到 provenance。"""
        prov = migrate_provenance(old_format_record)
        assert prov["source_ref_hash"] is not None
        assert prov["collected_at"] is not None
        assert prov["collector"] == "P1_team"
        assert prov["terms_checked_at"] is None  # 原始为 None

    def test_no_collected_field(self, old_format_record_no_collected):
        """无 _collected 时提供默认值。"""
        prov = migrate_provenance(old_format_record_no_collected)
        assert prov["source_ref_hash"] is not None
        assert prov["collector"] == "P1_migration"


# ═══════════════════════════════════════════════════════════════
# Tests: privacy 迁移
# ═══════════════════════════════════════════════════════════════

class TestPrivacyMigration:
    def test_default_privacy(self, old_format_record):
        """隐私字段应有默认值。"""
        priv = migrate_privacy(old_format_record)
        assert "anonymized" in priv
        assert "contains_sensitive_data" in priv


# ═══════════════════════════════════════════════════════════════
# Tests: 完整记录迁移
# ═══════════════════════════════════════════════════════════════

class TestFullRecordMigration:
    def test_migrate_success(self, old_format_record):
        """正常记录应成功迁移。"""
        id_map = {}
        new_record, status = migrate_record(
            old_format_record, id_map, "test_salt", Path("data"), "1.1"
        )
        assert status == "success"
        assert new_record is not None
        assert new_record["schema_version"] == "1.1"
        assert new_record["post_id"].startswith("post_")
        assert new_record["title"] == "测试文章标题"
        assert new_record["content_group_id"] is None  # v1.1 新增
        assert "provenance" in new_record
        assert "privacy" in new_record
        assert "_migration_meta" in new_record

    def test_migrate_degraded_llm_review(self, old_format_record_llm_review):
        """LLM 需复核的记录应标记为 degraded。"""
        id_map = {}
        new_record, status = migrate_record(
            old_format_record_llm_review, id_map, "test_salt", Path("data"), "1.1"
        )
        assert status == "degraded"
        assert new_record["_migration_meta"]["llm_needs_review"] is True

    def test_migrate_rejected_no_post_id(self):
        """无 post_id 的记录应被拒绝。"""
        id_map = {}
        new_record, status = migrate_record(
            {"text": "no id"}, id_map, "test_salt", Path("data"), "1.1"
        )
        assert status == "rejected"
        assert new_record is None

    def test_id_mapping_populated(self, old_format_record):
        """ID 映射表应被填充。"""
        id_map = {}
        migrate_record(old_format_record, id_map, "test_salt", Path("data"), "1.1")
        old_id = old_format_record["post_id"]
        assert old_id in id_map
        assert id_map[old_id].startswith("post_")

    def test_platform_wechat_normalized(self, old_format_record_no_collected):
        """平台 'wechat' 应标准化为 'wechat_official_account'。"""
        id_map = {}
        new_record, _ = migrate_record(
            old_format_record_no_collected, id_map, "test_salt", Path("data"), "1.1"
        )
        assert new_record["platform"] == "wechat_official_account"

    def test_v1_0_schema_has_no_title(self, old_format_record):
        """v1.0 目标不应有 title 和 content_group_id。"""
        id_map = {}
        new_record, _ = migrate_record(
            old_format_record, id_map, "test_salt", Path("data"), "1.0"
        )
        assert "title" not in new_record
        assert "content_group_id" not in new_record


# ═══════════════════════════════════════════════════════════════
# Tests: JSONL 读写
# ═══════════════════════════════════════════════════════════════

class TestJsonlIO:
    def test_write_and_read_jsonl(self):
        """写入后应能正确读取。"""
        records = [
            {"post_id": "post_001", "text": "hello"},
            {"post_id": "post_002", "text": "world"},
        ]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as f:
            tmp_path = Path(f.name)

        try:
            write_jsonl(records, tmp_path)
            loaded = load_jsonl(tmp_path)
            assert len(loaded) == 2
            assert loaded[0]["post_id"] == "post_001"
            assert loaded[1]["post_id"] == "post_002"
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_load_empty_file(self):
        """空文件应返回空列表。"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as f:
            tmp_path = Path(f.name)

        try:
            loaded = load_jsonl(tmp_path)
            assert loaded == []
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_load_multiline_json(self):
        """应能读取美化打印的多行 JSON（非标准 JSONL）。"""
        content = """{
  "post_id": "post_001",
  "text": "hello"
}
{
  "post_id": "post_002",
  "text": "world"
}"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as f:
            f.write(content)
            tmp_path = Path(f.name)

        try:
            loaded = load_jsonl(tmp_path)
            assert len(loaded) == 2
        finally:
            tmp_path.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════
# Tests: Schema 合规性
# ═══════════════════════════════════════════════════════════════

class TestSchemaCompliance:
    def test_v1_0_required_fields(self, old_format_record):
        """迁移后的 v1.0 记录应包含所有必填字段。"""
        id_map = {}
        new_record, _ = migrate_record(
            old_format_record, id_map, "test_salt", Path("data"), "1.0"
        )
        required_v1_0 = [
            "schema_version", "post_id", "platform", "source_type",
            "blogger_id", "text", "media", "provenance", "privacy",
        ]
        for field in required_v1_0:
            assert field in new_record, f"Missing required field: {field}"

    def test_v1_1_optional_fields(self, old_format_record):
        """迁移后的 v1.1 记录应包含新增可选字段。"""
        id_map = {}
        new_record, _ = migrate_record(
            old_format_record, id_map, "test_salt", Path("data"), "1.1"
        )
        assert "title" in new_record
        assert "content_group_id" in new_record

    def test_post_id_pattern(self, old_format_record):
        """post_id 应符合 ^post_[A-Za-z0-9_-]+$ 模式。"""
        import re
        id_map = {}
        new_record, _ = migrate_record(
            old_format_record, id_map, "test_salt", Path("data"), "1.1"
        )
        pattern = r"^post_[A-Za-z0-9_-]+$"
        assert re.match(pattern, new_record["post_id"]), \
            f"post_id '{new_record['post_id']}' does not match pattern"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
