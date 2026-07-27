"""
tests/test_training_pipeline_v3.py — phần TẤT ĐỊNH của pipeline fine-tune v3.

Chạy ở CI không GPU/API: seed generator, date resolution, chốt chặn số liệu,
converter v2, secret scan, và cặp n8n từ template thật.
"""

import json
from datetime import date

import pytest

from offline_training.build_dataset_v3 import convert_v2_entry, scan_secrets, strip_think
from offline_training.dgen_common import (
    customer_leak,
    fuzzy_contains,
    narration_numbers_ok,
    numbers_in,
)
from offline_training.make_extraction_seeds import generate, next_weekday
from src.core.prompts import Prompts
from src.core.schemas import QUOTE_REQUIRED_FIELDS, QuoteExtraction

# ===========================================================================
# format_extraction_user — hợp đồng train/serve (P4)
# ===========================================================================


def test_format_extraction_user_has_weekday_and_iso_date():
    out = Prompts.format_extraction_user("báo giá xe 5 tấn", date(2026, 7, 27))
    assert "thứ Hai" in out                    # 27/07/2026 là thứ Hai
    assert "2026-07-27" in out
    assert "báo giá xe 5 tấn" in out


# ===========================================================================
# make_extraction_seeds — ground truth tất định
# ===========================================================================


def test_next_weekday_resolves_correctly():
    monday = date(2026, 7, 27)
    assert next_weekday(monday, 1) == date(2026, 8, 4)    # thứ 3 tuần sau
    assert next_weekday(monday, 0) == date(2026, 8, 3)    # thứ 2 tuần sau
    sunday = date(2026, 8, 2)
    assert next_weekday(sunday, 0) == date(2026, 8, 3)    # từ CN -> thứ 2 ngay mai... vẫn là "tuần sau" theo lịch VN


def test_seeds_validate_against_runtime_schema():
    train, eval_ = generate(60, 15, seed=7)
    assert len(train) == 60 and len(eval_) == 15
    for seed in train + eval_:
        QuoteExtraction(**seed["ground_truth"])           # không được lệch schema
        assert set(seed["ground_truth"]) == set(QuoteExtraction.model_fields)


def test_seeds_cover_each_required_field_missing():
    train, eval_ = generate(200, 0, seed=7)
    for field in QUOTE_REQUIRED_FIELDS:
        assert any(field in s["must_not_mention"] for s in train), (
            f"200 seed mà không có seed nào thiếu {field} — nhánh hỏi-lại không được dạy"
        )


def test_seeds_include_ambiguous_dates_as_null():
    train, _ = generate(200, 0, seed=7)
    ambiguous = [
        s for s in train
        if "date_phrase" in s["facts"] and s["ground_truth"]["pickup_date"] is None
    ]
    assert ambiguous, "phải có cụm ngày mơ hồ với ground truth null (kỷ luật không đoán)"


def test_seeds_deterministic_by_seed():
    a, _ = generate(30, 0, seed=99)
    b, _ = generate(30, 0, seed=99)
    assert a == b


# ===========================================================================
# dgen_common — chốt chặn P1/P2
# ===========================================================================


def test_fuzzy_contains_ignores_diacritics():
    assert fuzzy_contains("can gap xe di hai phong t3", "Hải Phòng")
    assert not fuzzy_contains("can gap xe di hai phong", "Bắc Giang")


def test_numbers_in_normalizes_separators():
    assert "3450000" in numbers_in("giá chốt 3.450.000đ")
    assert "3450000" in numbers_in("total 3,450,000 VND")


def test_narration_numbers_ok_blocks_invented_numbers():
    context = json.dumps({"quoted_price": 3450000, "surcharges": []})
    ok, _ = narration_numbers_ok("Giá chốt là 3.450.000đ.", context)
    assert ok
    ok, bad = narration_numbers_ok("Giá chốt là 3.500.000đ.", context)   # số bịa
    assert not ok and bad == "3500000"


def test_customer_leak_catches_margin_words():
    assert customer_leak("Giá này đã gồm biên 12%")
    assert customer_leak("giá nhà xe là 3 triệu")
    # "lại" không được khớp nhầm "lãi" (so có dấu + word boundary)
    assert not customer_leak("Gửi lại anh báo giá tuyến Hải Phòng")


# ===========================================================================
# build_dataset_v3 — converter v2 + secret scan
# ===========================================================================


def test_strip_think_keeps_answer_only():
    text = "<think>suy nghĩ dài</think>\nCâu trả lời thật."
    assert strip_think(text) == "Câu trả lời thật."


def test_convert_v2_drops_make_com():
    obj = {"messages": [
        {"role": "system", "content": "You generate strict Make.com JSON blueprints."},
        {"role": "user", "content": "Tạo quy trình"},
        {"role": "assistant", "content": '{"flow": [{"module": "gateway"}]}'},
    ]}
    entry, reason = convert_v2_entry(obj)
    assert entry is None and reason == "make_com"


def test_convert_v2_drops_old_sql_action():
    obj = {"messages": [
        {"role": "system", "content": "You are Project A."},
        {"role": "user", "content": "Doanh thu 14 ngày"},
        {"role": "assistant",
         "content": '<think>x</think>{"action": "query_db", "sql": "SELECT 1"}'},
    ]}
    entry, reason = convert_v2_entry(obj)
    assert entry is None and reason == "sql_action"


def test_convert_v2_consult_gets_runtime_system_prompt():
    obj = {"messages": [
        {"role": "system", "content": "You are Project A, an expert Retail Consultant."},
        {"role": "user", "content": "Nên nhập hàng Tết thế nào?"},
        {"role": "assistant",
         "content": "<think>lập luận</think>\nNên nhập sớm 6 tuần."},
    ]}
    entry, reason = convert_v2_entry(obj)
    assert reason == "ok"
    assert entry["messages"][0]["content"] == Prompts.GENERAL_SYSTEM
    assert "<think>" not in entry["messages"][-1]["content"]
    assert entry["messages"][-1]["content"] == "Nên nhập sớm 6 tuần."


def test_scan_secrets_catches_connection_strings_and_keys():
    assert scan_secrets("postgresql://user:npg_abc123XYZ@host.neon.tech/db")
    assert scan_secrets("api_key = 'sk-" + "a" * 32 + "'")
    assert not scan_secrets("giá 25.000đ/lít, tuyến Hải Phòng")


# ===========================================================================
# make_n8n_pairs — cặp từ template thật phải qua validator runtime
# ===========================================================================


@pytest.fixture()
def staged_catalog(monkeypatch, tmp_path):
    """Catalog gộp từ data/n8n_templates + workflows/logistics như lúc build."""
    import shutil

    from offline_training.make_n8n_pairs import TEMPLATE_DIRS

    staging = tmp_path / "catalog"
    staging.mkdir()
    for src_dir in TEMPLATE_DIRS:
        if src_dir.is_dir():
            for f in src_dir.glob("*.json"):
                shutil.copy2(f, staging / f"{src_dir.name}__{f.name}")
    monkeypatch.setenv("N8N_TEMPLATES_DIR", str(staging))
    from src.core.workflow_schema import reload_catalog
    reload_catalog()
    yield staging
    monkeypatch.delenv("N8N_TEMPLATES_DIR", raising=False)
    reload_catalog()


def test_n8n_pair_from_real_logistics_template_is_valid(staged_catalog):
    from pathlib import Path

    from offline_training.make_n8n_pairs import build_pair_from_template
    from src.core.workflow_schema import validate_workflow

    built = 0
    for path in sorted(Path("workflows/logistics").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        pair, reason = build_pair_from_template(path, data)
        if pair is None:
            continue                      # template quá lớn thì bỏ qua hợp lệ
        built += 1
        ok, why = validate_workflow(pair["answer"])
        assert ok, f"{path.name}: {why}"
        assert pair["task"] and pair["plan"].startswith("[PLAN]")
        # node bị chặn phải đã bị thay bằng noOp
        types = {n["type"] for n in pair["answer"]["payload"]["nodes"]}
        assert "n8n-nodes-base.code" not in types

    assert built >= 1, "không dựng được cặp nào từ workflows/logistics"
