"""
tests/test_training_pipeline_v3.py — phần TẤT ĐỊNH của pipeline fine-tune v3.

Chạy ở CI không GPU/API: seed generator, date resolution, chốt chặn số liệu,
converter v2, secret scan, và cặp n8n từ template thật.
"""

import json
from datetime import date
from pathlib import Path

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
# Seed đa lượt — dạy model kế thừa ngữ cảnh
# ===========================================================================


def test_followup_seeds_inherit_context():
    """
    Lượt 2 chỉ đổi ĐÚNG MỘT trường; mọi trường khác kế thừa từ lượt 1.
    Không có lịch sử thì bài toán này bất khả — đó là điều cần dạy.
    """
    train, _ = generate(200, 0, seed=7)
    followups = [s for s in train if s.get("kind") == "followup"]
    assert followups, "phải có seed nối tiếp"

    for seed in followups:
        gt1, gt2 = seed["ground_truth"], seed["ground_truth2"]
        QuoteExtraction(**gt2)
        changed = [f for f in gt1 if gt1.get(f) != gt2.get(f)]
        assert changed == [seed["changed_field"]], (
            f"{seed['_id']}: đổi {changed}, khai báo đổi {seed['changed_field']}"
        )
        # 3 trường bắt buộc của lượt 2 phải đủ (kế thừa hoặc vừa đổi)
        for field in QUOTE_REQUIRED_FIELDS:
            assert gt2[field], f"{seed['_id']}: lượt 2 thiếu {field}"


def test_followup_teacher_prompt_forbids_repeating_context():
    from offline_training.reverse_generate import build_followup_prompt

    train, _ = generate(200, 0, seed=7)
    seed = next(s for s in train if s.get("kind") == "followup")
    prompt = build_followup_prompt(seed)
    assert "LƯỢT 1:" in prompt and "LƯỢT 2:" in prompt
    assert "KHÔNG nhắc lại điểm lấy hàng" in prompt


def test_split_two_turns_parses_teacher_output():
    from offline_training.reverse_generate import split_two_turns

    t1, t2 = split_two_turns(
        "LƯỢT 1: Báo giá xe 5 tấn từ Hữu Nghị đi Hải Phòng\n"
        "LƯỢT 2: thế xe 3 tấn thì sao"
    )
    assert t1.startswith("Báo giá") and t2 == "thế xe 3 tấn thì sao"
    assert split_two_turns("không đúng mẫu") == (None, None)


def test_verify_followup_rejects_repeated_context():
    """Lượt 2 lặp lại tuyến đường -> mẫu không còn dạy được kỹ năng kế thừa."""
    from offline_training.reverse_generate import verify_followup

    seed = {
        "changed_field": "vehicle_type",
        "ground_truth": {"origin": "Hữu Nghị", "destination": "Hải Phòng",
                         "vehicle_type": "5T", "cargo_type": None,
                         "pickup_date": None, "customer_name": None,
                         "customer_email": None},
        "ground_truth2": {"origin": "Hữu Nghị", "destination": "Hải Phòng",
                          "vehicle_type": "3T", "cargo_type": None,
                          "pickup_date": None, "customer_name": None,
                          "customer_email": None},
    }
    turn1 = "Báo giá xe 5 tấn từ Hữu Nghị đi Hải Phòng giúp anh"
    assert verify_followup(turn1, "thế xe 3 tấn thì sao", seed) is None
    reason = verify_followup(turn1, "thế xe 3 tấn đi Hải Phòng thì sao", seed)
    assert reason and "lặp lại thông tin cũ" in reason


def test_multiturn_train_entry_has_five_messages():
    """train_v3 tính loss trên message cuối -> mẫu 5 message dạy đúng lượt 2."""
    from offline_training.reverse_generate import to_train_entry

    train, _ = generate(200, 0, seed=7)
    seed = next(s for s in train if s.get("kind") == "followup")
    entry = to_train_entry(seed, ("tin nhắn lượt 1", "thế xe 3 tấn thì sao"))
    roles = [m["role"] for m in entry["messages"]]
    assert roles == ["system", "user", "assistant", "user", "assistant"]
    assert json.loads(entry["messages"][-1]["content"]) == seed["ground_truth2"]
    assert entry["_source"] == "logistics_extract_multiturn"


# ===========================================================================
# Khớp train ↔ serve (P4) — lỗi âm thầm nguy hiểm nhất
# ===========================================================================


def test_multiturn_history_shape_matches_serving():
    """
    Lượt assistant trong data phải là CÂU XÁC NHẬN — đúng thứ lịch sử chứa lúc
    serve. Nếu là JSON trích xuất thì model học một hình dạng lịch sử không bao
    giờ xuất hiện thật.
    """
    from offline_training.reverse_generate import to_train_entry

    train, _ = generate(200, 0, seed=7)
    seed = next(s for s in train if s.get("kind") == "followup")
    entry = to_train_entry(seed, ("tin nhắn lượt 1", "thế xe 3 tấn"))

    assistant_turn1 = entry["messages"][2]["content"]
    assert not assistant_turn1.strip().startswith("{"), "không được là JSON"
    assert assistant_turn1 == Prompts.format_quote_confirmation(
        seed["ground_truth"], seed["_id"]
    )
    # câu xác nhận phải nêu tuyến để lượt sau kế thừa được
    assert seed["ground_truth"]["destination"] in assistant_turn1


def test_chat_builds_extraction_history_same_way_as_training():
    """
    chat.py bọc lịch sử bằng format_extraction_history; data train bọc lượt
    user bằng format_extraction_user. Hai bên phải cho ra CÙNG chuỗi.
    """
    today = date(2026, 7, 27)
    raw_history = [
        {"role": "user", "content": "báo giá xe 5 tấn Hữu Nghị đi Hải Phòng"},
        {"role": "assistant", "content": "Đã tạo nháp báo giá QD-01..."},
    ]
    built = Prompts.format_extraction_history(raw_history, today)

    assert built[0]["content"] == Prompts.format_extraction_user(
        raw_history[0]["content"], today
    )
    assert built[1] == raw_history[1]          # assistant giữ nguyên


def test_extraction_history_ignores_malformed_records():
    out = Prompts.format_extraction_history(
        [{"role": "system", "content": "lậu"}, "rác", {"role": "user", "content": "ok"}],
        date(2026, 7, 27),
    )
    assert len(out) == 1 and out[0]["role"] == "user"


def test_benchmark_builds_same_chat_as_serving():
    """Benchmark phải đo trên ĐÚNG đường đi production, không phải biến thể."""
    from offline_training.benchmark_v3 import build_extraction_chat

    row = {
        "today": "2026-07-27",
        "kind": "followup",
        "history": [
            {"role": "user", "content": "báo giá xe 5 tấn Hữu Nghị đi Hải Phòng"},
            {"role": "assistant", "content": "Đã tạo nháp báo giá FU0001..."},
        ],
        "message": "thế xe 3 tấn thì sao",
    }
    chat = build_extraction_chat(row, Prompts)
    today = date(2026, 7, 27)

    assert chat[0]["content"] == Prompts.LOGISTICS_EXTRACT_SYSTEM
    assert chat[1:3] == Prompts.format_extraction_history(row["history"], today)
    assert chat[-1]["content"] == Prompts.format_extraction_user(row["message"], today)


def test_catalog_fingerprint_changes_with_catalog(monkeypatch, tmp_path):
    """Vân tay phải đổi khi catalog đổi — nếu không thì nó vô dụng."""
    from src.core.workflow_schema import catalog_fingerprint, reload_catalog

    reload_catalog()
    default_fp = catalog_fingerprint()
    assert len(default_fp) == 16

    staging = tmp_path / "cat"
    staging.mkdir()
    (staging / "wf.json").write_text(json.dumps({
        "name": "x",
        "nodes": [{"name": "A", "type": "n8n-nodes-base.webhook",
                   "typeVersion": 99, "position": [0, 0], "parameters": {}}],
        "connections": {},
    }), encoding="utf-8")
    monkeypatch.setenv("N8N_TEMPLATES_DIR", str(staging))
    reload_catalog()
    assert catalog_fingerprint() != default_fp

    monkeypatch.delenv("N8N_TEMPLATES_DIR", raising=False)
    reload_catalog()
    assert catalog_fingerprint() == default_fp


def test_benchmark_scores_followup_separately():
    """Điểm chung đẹp mà câu nối tiếp kém = hội thoại nhiều lượt chưa dùng được."""
    from offline_training.benchmark_v3 import score_extraction

    gt = {"origin": "Hữu Nghị", "destination": "Hải Phòng", "vehicle_type": "5T",
          "cargo_type": None, "pickup_date": None, "customer_name": None,
          "customer_email": None}
    rows = [
        {"kind": "single", "ground_truth": gt},
        {"kind": "followup", "ground_truth": gt},
    ]
    outputs = [json.dumps(gt), json.dumps({**gt, "origin": None})]  # nối tiếp sai
    result = score_extraction(rows, outputs)
    assert result["ready_by_kind"]["single"] == 1.0
    assert result["ready_by_kind"]["followup"] == 0.0


# ===========================================================================
# Nhánh REPORT — cứu mẫu văn dài thay vì vứt
# ===========================================================================


def test_long_consult_goes_to_report_branch():
    """436 mẫu distill R1 dài ~5.800 ký tự: đúng hợp đồng REPORT, không phải rác."""
    long_answer = "Phân tích chi tiết. " * 200          # ~4.000 ký tự
    obj = {"messages": [
        {"role": "system", "content": "You are Project A."},
        {"role": "user", "content": "Phân tích thị trường bán lẻ 2026"},
        {"role": "assistant", "content": f"<think>x</think>\n{long_answer}"},
    ]}
    entry, reason = convert_v2_entry(obj)
    assert reason == "report_ok"
    assert entry["_source"] == "v2_report"
    assert "DỮ LIỆU:" in entry["messages"][0]["content"]
    # context trống phải nói rõ là không có số liệu, để model không học bịa số
    assert "không có số liệu" in entry["messages"][0]["content"]


@pytest.mark.parametrize("assistant", [
    # think không đóng thẻ (bị cắt vì hết token budget)
    "<think>\nTôi cần phân tích yêu cầu này rất kỹ vì nó liên quan tới",
    # think đóng thẻ nhưng không còn gì phía sau
    "<think>\nlập luận dài\n</think>",
    "<think>lập luận</think>   \n  ",
])
def test_answer_empty_after_stripping_think_is_dropped(assistant):
    """
    Mẫu v2 mà phần assistant TOÀN BỘ là khối <think> -> sau khi cắt còn rỗng.
    Giữ lại là dạy model trả lời rỗng — thứ tệ nhất có thể dạy.
    """
    obj = {"messages": [
        {"role": "system", "content": "You are Project A."},
        {"role": "user", "content": "Phân tích giúp tôi"},
        {"role": "assistant", "content": assistant},
    ]}
    entry, reason = convert_v2_entry(obj)
    assert entry is None and reason == "empty_after_strip"


def test_absurdly_long_still_dropped():
    obj = {"messages": [
        {"role": "system", "content": "You are Project A."},
        {"role": "user", "content": "Viết sách"},
        {"role": "assistant", "content": "x" * 20_000},
    ]}
    entry, reason = convert_v2_entry(obj)
    assert entry is None and reason == "too_long"


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


def test_strip_think_drops_unterminated_reasoning():
    """
    Thẻ mở không đóng = model hết token budget giữa lúc suy luận. Phần còn lại
    là mảnh suy luận cụt, không phải câu trả lời — cùng luật với clean_output.
    """
    assert strip_think("<think>\nTôi cần phân tích rất kỹ vì nó liên quan") == ""
    assert strip_think("Trả lời trước.\n<think>rồi nghĩ tiếp") == "Trả lời trước."
    assert strip_think("Không có thẻ nào.") == "Không có thẻ nào."


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
    assert scan_secrets("postgresql://admin:npg_abc123XYZ@host.neon.tech/db")
    assert scan_secrets("api_key = 'sk-" + "a" * 32 + "'")
    assert not scan_secrets("giá 25.000đ/lít, tuyến Hải Phòng")


def test_scan_secrets_allows_teaching_placeholders():
    """
    train_final.jsonl có mẫu dạy disaster-recovery chứa
    postgres://read_replica_user:pass@replica_host — mật khẩu là chữ 'pass'.
    Chặn nó là chặn oan cả file; nhưng mật khẩu THẬT vẫn phải bị bắt.
    """
    assert not scan_secrets("postgres://read_replica_user:pass@replica_host:5432/db")
    assert not scan_secrets("postgresql://user:password@example.com/db")
    assert scan_secrets("postgresql://admin:Xk9$mQ2pLw@ep-cool-1.neon.tech/db")


def test_convert_v2_keeps_raw_n8n_export_shape(staged_catalog):
    """
    module_c lưu workflow ở dạng export gốc {name, nodes, connections} chứ
    không phải envelope {action, payload} — 170/190 mẫu. Converter phải nhận.
    """
    workflow = json.loads(Path("workflows/logistics/logistics_debt_reminder.json")
                          .read_text(encoding="utf-8"))
    obj = {"messages": [
        {"role": "system", "content": "Bạn là ANSER Brain — sinh workflow n8n."},
        {"role": "user", "content": "Nhắc công nợ mỗi thứ 2"},
        {"role": "assistant",
         "content": "<think>x</think>\n```json\n"
                    + json.dumps(workflow, ensure_ascii=False) + "\n```"},
    ]}
    entry, reason = convert_v2_entry(obj)
    assert reason == "workflow_ok", reason
    answer = json.loads(entry["messages"][-1]["content"])
    assert answer["action"] == "create_workflow"
    assert answer["payload"]["nodes"]
    # system prompt phải là bản CODER runtime, không phải prompt v2 cũ
    assert "connections" in entry["messages"][0]["content"]


def test_convert_v2_prose_mentioning_nodes_is_not_treated_as_json():
    """Bài tư vấn kiến trúc có nhắc chữ "nodes" không được xếp nhầm loại JSON."""
    prose = ("## Thiết kế Event-Driven\n\nHệ thống nên tách các consumer thành "
             'nhiều "nodes" độc lập để chịu tải tốt hơn.')
    obj = {"messages": [
        {"role": "system", "content": "You are Project A."},
        {"role": "user", "content": "Thiết kế event-driven thế nào?"},
        {"role": "assistant", "content": prose},
    ]}
    entry, reason = convert_v2_entry(obj)
    assert reason == "ok" and entry["_source"] == "v2_consult"


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
