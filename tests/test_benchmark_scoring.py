"""
tests/test_benchmark_scoring.py — chấm điểm benchmark phải đo ĐÚNG THỨ ĐANG ĐO.

Buổi đo 05/08/2026 cho ra ba con số sai lệch, cả ba đều do khung đo chứ không do
model. Nguy hiểm ở chỗ chúng trông y hệt số thật, và nếu tin thì sẽ đi train lại
một model vốn không có vấn đề đó.

Mẫu dùng ở đây lấy NGUYÊN VĂN từ báo cáo hỏng, không phải bịa ra cho vừa test.
"""

from __future__ import annotations

import pytest

from offline_training.benchmark_v3 import (
    parse_outputs,
    score_agent,
    score_narration,
    score_planner,
    tach_tool_tu_json_cut,
)

# Nguyên văn hai mẫu trong tuned_report — JSON hợp lệ, đứt giữa chừng vì chạm
# trần token khi model nhét cả mảng dòng bán vào `arguments`.
CAT_CUT_REPORT = (
    '{"thought": "Dữ liệu đầy đủ, gọi công cụ report để tính toán.", '
    '"tool": "report", "arguments": {"granularity": "half_year", '
    '"periods_back": 1, "sales": [{"date": "2024-04-15", "revenue": 45000000, '
    '"cost_of_sales": 33825862}, {"d'
)
CAT_CUT_CARRIER = (
    '{"thought": "Câu hỏi có đủ thông tin, gọi công cụ để trả lời.", '
    '"tool": "carrier_selection", "arguments": {"carriers": [{"name": "Đại An", '
    '"price": 9400000, "discount": 5, "credit_days": 15}, {"name": "Tân Cảng Bắc"'
)


# ---------------------------------------------------------------------------
# Moi tên tool ra khỏi JSON cắt cụt
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,mong_doi", [
    (CAT_CUT_REPORT, "report"),
    (CAT_CUT_CARRIER, "carrier_selection"),
    ('{"tool": "vat", "arguments": {}}', "vat"),
    ('{"thought": "x", "tool": "quote"', "quote"),
])
def test_moi_duoc_ten_tool_du_json_dut_giua_chung(raw, mong_doi):
    assert tach_tool_tu_json_cut(raw) == mong_doi


@pytest.mark.parametrize("raw", [
    "",
    '{"answer": "Anh cho em xin thêm điểm đến ạ."}',
    "không phải json",
])
def test_khong_co_tool_thi_KHONG_bia_ra_mot_cai(raw):
    """Moi nhầm ra một tool là biến 'model không chọn gì' thành 'model chọn sai'."""
    assert tach_tool_tu_json_cut(raw) is None


# ---------------------------------------------------------------------------
# Agentic: cắt cụt KHÔNG được tính thành "chọn None"
# ---------------------------------------------------------------------------

def test_cat_cut_khong_con_bi_tinh_la_khong_goi_tool():
    """
    Bản cũ: JSON cắt cụt -> json.loads hỏng -> dict rỗng -> `chose = None` ->
    "chọn None". Model ĐÃ chọn, chỉ chưa viết xong phần tham số.

    Hai mẫu này đều là tool CẦN DỮ LIỆU HỆ THỐNG. Từ 05/08/2026 `arguments` của
    chúng bị bỏ hẳn `sales`/`carriers` khỏi lược đồ nên chuyện cắt cụt gần như
    không còn xảy ra — nhưng phần cứu vẫn phải giữ, vì đây là mẫu THẬT từ báo
    cáo hỏng và nó chứng minh việc chấm không đổ lỗi nhầm cho model.
    """
    rows = [
        {"_id": "AG0000", "tool": "report"},
        {"_id": "AG0002", "tool": "carrier_selection"},
    ]
    kq = score_agent(rows, [CAT_CUT_REPORT, CAT_CUT_CARRIER])
    assert kq["call_rate"] == 1.0
    assert kq["cuu_tu_json_cut"] == 2
    assert kq["failures"] == []
    # Tham số của tool cần dữ liệu hệ thống KHÔNG được chấm: production ghi đè
    # chúng, nên chấm ở đây là chấm thứ bị vứt đi.
    assert kq["n_arg"] == 0


def test_tham_so_cat_cut_van_bi_tinh_truot_voi_tool_model_phai_dien():
    """
    Cứu tên tool KHÔNG được biến thành cứu điểm. `quote` là tool model PHẢI tự
    điền tham số (suy từ lời người dùng), nên `arguments` đứt giữa chừng là
    trượt thật — production sẽ trả 422.
    """
    rows = [{"_id": "AG0003", "tool": "quote"}]
    kq = score_agent(rows, ['{"thought": "x", "tool": "quote", "arguments": {"a'])
    assert kq["call_rate"] == 1.0          # có gọi tool
    assert kq["arg_fill_rate"] == 0.0      # nhưng tham số không dùng được
    assert "quote" in kq["failures"][0][1]


def test_tham_so_dung_kieu_thi_qua():
    """Chấm bằng ĐÚNG pydantic của endpoint — không phải một bản kiểm riêng."""
    rows = [{"_id": "AG0004", "tool": "vat"}]
    kq = score_agent(rows, [
        '{"thought": "x", "tool": "vat", "arguments": '
        '{"items": [{"name": "A", "price": 100000, "qty": 1}], "stated_total": 110000}}'
    ])
    assert kq["arg_fill_rate"] == 1.0
    assert kq["failures"] == []


# ---------------------------------------------------------------------------
# Bảng luật: chỗ "chọn đúng tool" nay được quyết định
# ---------------------------------------------------------------------------

def test_bang_luat_cham_duoc_ma_khong_can_gpu():
    rows = [
        {"_id": "P1", "tool": "report", "question": "quý này lãi hay lỗ"},
        {"_id": "P2", "tool": "forecast_reorder",
         "question": "có nên nhập thêm hàng không"},
    ]
    kq = score_planner(rows)
    assert kq["tool_rate"] == 1.0 and kq["coverage"] == 1.0
    assert kq["failures"] == []


def test_bang_luat_bao_truot_khi_khong_luat_nao_khop():
    """
    Không khớp luật nào thì câu rơi về nhánh router cũ — vẫn trả lời được, nhưng
    KHÔNG dùng tool tất định. Tính là trượt, nếu không thì bảng luật rỗng cũng
    được 100%.
    """
    rows = [{"_id": "P3", "tool": "report", "question": "hôm nay trời đẹp nhỉ"}]
    kq = score_planner(rows)
    assert kq["tool_rate"] == 0.0 and kq["coverage"] == 0.0
    assert "không luật nào khớp" in kq["failures"][0][1]


def test_bang_luat_cham_ca_ca_hoi_lai():
    """
    Ca HỎI LẠI có `expected_tool = None`, nhưng bảng luật VẪN phải nhận ra ý
    định — chính vì đã lên kế hoạch mà thiếu tham số nên model mới hỏi lại được.
    """
    rows = [{"_id": "P4", "tool": "report", "expected_tool": None,
             "ask_back": True, "question": "quý vừa rồi lãi hay lỗ"}]
    assert score_planner(rows)["tool_rate"] == 1.0


def test_cham_duoc_tren_DUNG_hinh_dang_file_that():
    """
    REGRESSION. `eval_agent.jsonl` chỉ ghi `_id / question / ask_back /
    expected_tool` — KHÔNG có `tool`. Bản đầu của `score_planner` đọc
    `row["tool"]` nên mọi dòng ra None, trượt sạch, `tool_rate` = 0.0, và cổng
    chặn đánh trượt cả buổi đo trong khi bảng luật không hề sai.

    Hàng thật, chép đúng khoá mà `make_agent_traces.py` ghi ra.
    """
    rows = [
        {"_id": "AG0001", "question": "quý này lãi hay lỗ",
         "ask_back": False, "expected_tool": "report"},
        {"_id": "AG0002", "question": "có nên nhập thêm hàng không",
         "ask_back": False, "expected_tool": "forecast_reorder"},
    ]
    kq = score_planner(rows)
    assert kq["tool_rate"] == 1.0, "phải chấm được bằng `expected_tool`"
    assert kq["n_cham"] == 2


def test_dong_khong_co_dap_an_thi_BO_QUA_chu_khong_tinh_truot():
    """
    File cũ trên Drive: ca hỏi lại có `expected_tool = None` và không có `tool`.
    Đánh trượt những dòng đó là đổ lỗi cho bảng luật vì một chuyện của bộ sinh
    dữ liệu — và làm cổng chặn nổ oan.
    """
    rows = [
        {"_id": "AG0003", "question": "quý này lãi hay lỗ",
         "ask_back": False, "expected_tool": "report"},
        {"_id": "AG0004", "question": "làm báo cáo giúp tôi",
         "ask_back": True, "expected_tool": None},          # không có đáp án
    ]
    kq = score_planner(rows)
    assert kq["n"] == 2 and kq["n_cham"] == 1
    assert kq["tool_rate"] == 1.0
    assert kq["failures"] == []


def test_khong_co_dap_an_nao_thi_bao_None_chu_khong_bao_0():
    """0.0 nghĩa là "bảng luật sai hết"; None nghĩa là "không đo được". Khác nhau."""
    rows = [{"_id": "X", "question": "quý này lãi hay lỗ", "ask_back": True,
             "expected_tool": None}]
    assert score_planner(rows)["tool_rate"] is None


def test_bo_sinh_du_lieu_ghi_du_khoa_cho_bo_cham():
    """
    Chống lệch giữa bộ SINH và bộ CHẤM. Hai file, hai người sửa, không có gì nối
    chúng lại ngoài test này.
    """
    import inspect

    from offline_training import make_agent_traces

    src = inspect.getsource(make_agent_traces)
    for khoa in ('"_id"', '"question"', '"ask_back"', '"expected_tool"', '"tool"'):
        assert khoa in src, f"make_agent_traces.py không còn ghi {khoa}"


def test_thieu_du_kien_ma_goi_tool_van_bi_bat_du_json_cat_cut():
    """Lỗi nguy hiểm nhất — gọi tool với tham số bịa — không được lọt."""
    rows = [{"_id": "AG0010", "ask_back": True, "expected_tool": None}]
    kq = score_agent(rows, [CAT_CUT_REPORT])
    assert kq["ask_back_rate"] == 0.0
    assert "report" in kq["failures"][0][1]


def test_biet_hoi_lai_van_duoc_tinh_dung():
    rows = [{"_id": "AG0011", "ask_back": True, "expected_tool": None}]
    kq = score_agent(rows, ['{"answer": "Anh cho em xin điểm đến ạ."}'])
    assert kq["ask_back_rate"] == 1.0


# ---------------------------------------------------------------------------
# Narration: CẮT CỤT khác BỊA SỐ
# ---------------------------------------------------------------------------

def test_cau_bi_chat_doi_KHONG_bi_goi_la_bia_so():
    """
    Báo cáo thật có dòng `[carrier] bịa số 0006`. "0006" không phải một con số
    bịa — đó là mảnh vụn của một con số bị chặt đôi giữa chừng. Gộp nó vào tỷ lệ
    bịa số là chỉ người đi sửa sang nhầm hướng: họ sẽ đi sửa dữ liệu huấn luyện
    trong khi việc cần làm chỉ là nới trần token.
    """
    rows = [{"_id": "NA0025", "kind": "carrier", "context": "giá 12000000 đồng"}]
    kq = score_narration(rows, ["Cước tuyến này là 000"], ["length"])
    assert kq["n_cat_cut"] == 1
    assert "CẮT CỤT" in kq["failures"][0][1]
    assert "bịa số" not in kq["failures"][0][1]


def test_bia_so_that_van_bi_bat():
    """Tách cắt cụt ra KHÔNG được làm lỗi bịa số biến mất."""
    rows = [{"_id": "NA0000", "kind": "report", "context": "doanh thu 12000000"}]
    kq = score_narration(rows, ["Doanh thu là 330078760 đồng."], ["stop"])
    assert kq["n_cat_cut"] == 0
    assert "bịa số" in kq["failures"][0][1]
    assert kq["pass_rate"] == 0.0


def test_ty_le_tren_phan_do_duoc_bo_ca_cat_cut_ra_khoi_mau_so():
    rows = [
        {"_id": "A", "kind": "quote", "context": "giá 12000000"},
        {"_id": "B", "kind": "quote", "context": "giá 12000000"},
        {"_id": "C", "kind": "quote", "context": "giá 12000000"},
    ]
    outs = ["Giá 12000000 đồng.", "Giá 12000000 đồng.", "Giá 120"]
    kq = score_narration(rows, outs, ["stop", "stop", "length"])
    assert kq["pass_rate"] == pytest.approx(2 / 3)
    assert kq["pass_rate_do_duoc"] == 1.0, "hai câu viết xong đều sạch"
    assert kq["n_cat_cut"] == 1


def test_khong_truyen_finish_thi_van_chay_nhu_cu():
    """Gọi cũ không có `finishes` — không được vỡ."""
    rows = [{"_id": "A", "kind": "quote", "context": "giá 12000000"}]
    kq = score_narration(rows, ["Giá 12000000 đồng."])
    assert kq["pass_rate"] == 1.0
    assert kq["n_cat_cut"] == 0


# ---------------------------------------------------------------------------
# parse_outputs: đếm đúng, giữ mẫu để nhìn tận mắt
# ---------------------------------------------------------------------------

def test_dem_dung_so_dau_ra_hong_va_giu_mau():
    preds, tk = parse_outputs(['{"a": 1}', "rác", CAT_CUT_REPORT], "thử")
    assert tk["parse_fail"] == 2
    assert preds[0] == {"a": 1} and preds[1] == {} and preds[2] == {}
    assert len(tk["mau"]) == 2, "phải giữ mẫu thô, không thì lại đoán mò"


def test_JSON_khong_phai_object_cung_tinh_la_hong():
    """`json.loads('[1,2]')` chạy được nhưng `.get()` thì không."""
    preds, tk = parse_outputs(["[1, 2]", '"chuỗi"'], "thử")
    assert tk["parse_fail"] == 2
    assert preds == [{}, {}]
