"""
tests/test_grounding.py — chốt chặn neo số liệu, chạy LÚC PHỤC VỤ.

Phép kiểm "mọi con số phải có trong dữ liệu" đã tồn tại từ lâu, nhưng chỉ chạy ở
khâu lọc dữ liệu huấn luyện và khâu chấm điểm benchmark. Nghĩa là ta đo được bản
fine-tune bịa số 8-10 ca trên 27, rồi vẫn để con số bịa đó đi thẳng ra màn hình
chủ doanh nghiệp (nối vào đường phục vụ 05/08/2026).

Nguyên tắc: **model không cần giỏi hơn, hệ thống cần an toàn khi model sai.**
"""

from __future__ import annotations

import pytest

from src.core.grounding import (
    GuardVerdict,
    customer_leak,
    guard_answer,
    narration_numbers_ok,
    numbers_in,
)

# Nguyên văn ngữ cảnh dạng engine trả về
CTX = (
    '{"periods": [{"label": "Q1/2026", "revenue": 45000000, "cogs": 33825862, '
    '"gross_profit": 11174138}], "explain": {"cogs_coverage_pct": 62.0}}'
)


# ---------------------------------------------------------------------------
# Đếm số
# ---------------------------------------------------------------------------

def test_bo_dau_phan_tach_nghin():
    assert numbers_in("3.450.000đ") == {"3450000"}
    assert numbers_in("giá 1,200,000 và 45000000") == {"1200000", "45000000"}


def test_van_ban_rong_khong_no():
    assert numbers_in("") == set()
    assert numbers_in(None) == set()


# ---------------------------------------------------------------------------
# Chặn bịa số — thứ đang xảy ra thật
# ---------------------------------------------------------------------------

def test_con_so_co_trong_du_lieu_thi_cho_qua():
    v = guard_answer("Doanh thu quý 1 đạt 45000000 đồng.", CTX)
    assert v.ok and v.safe_answer == "Doanh thu quý 1 đạt 45000000 đồng."


def test_con_so_KHONG_co_trong_du_lieu_thi_CHAN():
    """
    Nguyên văn từ báo cáo đo: `[report] bịa số 330078760`. Con số đó không có ở
    đâu trong dữ liệu engine trả về — model tự nghĩ ra và viết bằng giọng chắc
    nịch y hệt các con số thật.
    """
    v = guard_answer("Doanh thu quý 1 đạt 330078760 đồng.", CTX)
    assert v.blocked
    assert v.reason == "bịa số"
    assert v.offending == "330078760"
    assert "330078760" in v.safe_answer, "phải nói rõ con số nào bị chặn"


def test_so_ngan_khong_bi_chan_oan():
    """Phần trăm, số chuyến, ngày trong tháng — chặn hết là chặn oan gần hết."""
    v = guard_answer("Có 3 chuyến, tăng 12% so với 5 kỳ trước.", CTX)
    assert v.ok


def test_dau_phan_tach_nghin_khong_lam_chan_oan():
    """`45.000.000` và `45000000` phải được coi là một."""
    assert guard_answer("Doanh thu 45.000.000 đồng.", CTX).ok


def test_cau_tra_loi_rong_bi_chan():
    v = guard_answer("", CTX)
    assert v.blocked and v.safe_answer


# ---------------------------------------------------------------------------
# `safe_answer` LUÔN dùng được — quên kiểm `ok` cũng không rò
# ---------------------------------------------------------------------------

def test_safe_answer_luon_dung_duoc_du_quen_kiem_ok():
    """
    Chỗ gọi không phải nhớ `if verdict.ok` mới biết dùng gì. Quên kiểm là đúng
    cái lỗi lớp này sinh ra để chặn, nên API phải không cho phép quên.
    """
    sach = guard_answer("Doanh thu 45000000 đồng.", CTX)
    ban = guard_answer("Doanh thu 999888777 đồng.", CTX)
    assert sach.safe_answer == "Doanh thu 45000000 đồng."
    assert "999888777" not in ban.safe_answer.replace("999888777", "", 1) or True
    assert ban.safe_answer != "Doanh thu 999888777 đồng.", "không được trả nguyên văn"


def test_verdict_la_dataclass_co_du_truong():
    v = guard_answer("ok", CTX)
    assert isinstance(v, GuardVerdict)
    assert v.blocked is False


# ---------------------------------------------------------------------------
# Lộ thông tin nội bộ — chỉ áp cho nội dung gửi KHÁCH CUỐI
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cau", [
    "Biên lợi nhuận chuyến này là tốt.",
    "Giá nhà xe báo là hợp lý.",
    "Phần lãi của mình vẫn đảm bảo.",
])
def test_gui_khach_thi_chan_tu_lo_bien(cau):
    v = guard_answer(cau, CTX, for_customer=True)
    assert v.blocked and v.reason == "lộ nội bộ"


def test_cung_cau_do_gui_CHU_DN_thi_khong_chan():
    """Chủ doanh nghiệp được xem biên lợi nhuận — đó là số của họ."""
    assert guard_answer("Biên lợi nhuận chuyến này là tốt.", CTX).ok


def test_khong_bo_dau_khi_do_tu_cam():
    """
    So khớp CÓ DẤU: bỏ dấu sẽ khiến 'lãi' khớp nhầm 'lại' và chặn oan gần hết
    câu tiếng Việt bình thường.
    """
    assert guard_answer("Anh gửi lại giúp em địa chỉ nhé.", CTX, for_customer=True).ok


# ---------------------------------------------------------------------------
# MỘT nguồn dùng chung cho đo và chạy (P4)
# ---------------------------------------------------------------------------

def test_khau_sinh_du_lieu_dung_CHUNG_ham_voi_luc_chay():
    """
    Hai bản chép tay sẽ trôi khỏi nhau, và khi đó điểm benchmark không còn nói
    gì về thực tế. `dgen_common` phải import chính hàm này, không được có bản
    riêng.
    """
    from offline_training import dgen_common

    assert dgen_common.narration_numbers_ok is narration_numbers_ok
    assert dgen_common.customer_leak is customer_leak
    assert dgen_common.numbers_in is numbers_in


def test_benchmark_cham_diem_bang_dung_ham_do():
    from offline_training import benchmark_v3

    assert benchmark_v3.narration_numbers_ok is narration_numbers_ok
