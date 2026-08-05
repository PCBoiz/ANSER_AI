"""
tests/test_tool_planner.py — bảng luật chọn tool.

Đây là thứ THAY THẾ việc model tự chọn tool (đo được 26-33%). Nếu bảng luật này
sai thì cái thay thế còn tệ hơn cái bị thay, nên mỗi luật phải có ít nhất một ca
khớp và một ca KHÔNG được khớp.
"""

from src.core.tool_planner import (
    MAX_PLAN,
    NEEDS_SYSTEM_DATA,
    needs_system_data,
    plan_tools,
)

TAT_CA = ["quote", "carrier_selection", "forecast_reorder", "vat", "report",
          "inventory_audit"]


def ke_hoach(cau: str) -> list[str]:
    return plan_tools(cau, TAT_CA)


# --------------------------------------------------------------------------
# Câu nhiều bước — lý do vòng agentic tồn tại
# --------------------------------------------------------------------------

def test_cau_nhieu_buoc_ra_nhieu_tool():
    assert ke_hoach(
        "tháng này lãi bao nhiêu, mặt hàng nào lãi nhất, có nên nhập thêm không"
    ) == ["report", "forecast_reorder"]


def test_thu_tu_khong_phu_thuoc_thu_tu_chu_trong_cau():
    """Cùng một ý định thì cùng một đường đi, dù người dùng nói ngược lại."""
    xuoi = ke_hoach("tháng này lãi bao nhiêu, có nên nhập thêm hàng không")
    nguoc = ke_hoach("có nên nhập thêm hàng không, mà tháng này lãi bao nhiêu")
    assert xuoi == nguoc == ["report", "forecast_reorder"]


def test_tran_so_tool():
    cau = ("rà soát tồn kho giúp tôi, quý này lãi hay lỗ, có nên nhập thêm không, "
           "nhà xe nào rẻ nhất, tiền thuế 5 triệu là bao nhiêu")
    assert len(ke_hoach(cau)) == MAX_PLAN


# --------------------------------------------------------------------------
# vat — phân biệt câu TÍNH với câu TRA LUẬT
# --------------------------------------------------------------------------

def test_cau_tinh_thue_co_so_tien_ra_tool_vat():
    assert ke_hoach("bán 10 triệu thì tiền thuế phải nộp là bao nhiêu") == ["vat"]
    assert "vat" in ke_hoach("đơn hàng 3.500.000đ thuế GTGT 8% thì tổng bao nhiêu")


def test_cau_tra_luat_khong_ra_tool():
    """Không có số tiền -> đây là câu hỏi văn bản, thuộc về RAG chứ không phải tool."""
    assert ke_hoach("nghị định 72 quy định thuế suất bao nhiêu") == []
    assert ke_hoach("hộ kinh doanh doanh thu bao nhiêu thì phải đóng thuế") == []


def test_nam_khong_bi_tinh_la_so_tien():
    """
    "2026" là NĂM. Tính nó thành tiền thì câu tổng kết bị kéo thêm tool `vat`
    với tham số vô nghĩa.
    """
    assert ke_hoach("tổng kết kinh doanh năm 2026 và thuế đã nộp") == ["report"]


def test_hoi_mot_con_so_van_thuoc_ve_nhanh_du_lieu():
    """
    "Doanh thu hôm nay bao nhiêu" là MỘT con số, DATA_INTERNAL trả thẳng từ DB.
    Kéo vào vòng agentic chỉ đổi một câu trả lời được thành "chưa nối dữ liệu".
    """
    assert ke_hoach("doanh thu hôm nay là bao nhiêu") == []
    assert ke_hoach("hôm nay bán được mấy đơn") == []


# --------------------------------------------------------------------------
# Không khớp — quan trọng ngang khớp đúng
# --------------------------------------------------------------------------

def test_cau_chao_hoi_khong_kich_hoat_gi():
    for cau in ["xin chào", "cảm ơn bạn nhiều", "bạn làm được những gì",
                "tôi nên bắt đầu từ đâu", ""]:
        assert ke_hoach(cau) == [], cau


def test_cau_bao_gia_van_tai_khong_bi_keo_vao():
    """LOGISTICS có luồng struct riêng — bảng luật không được giành lấy."""
    assert ke_hoach("báo giá xe 5 tấn từ Hà Nội đi Hải Phòng") == []


# --------------------------------------------------------------------------
# Lọc theo manifest (P4)
# --------------------------------------------------------------------------

def test_loc_theo_tool_co_that():
    """Tool bị gỡ khỏi manifest thì bảng luật không được nhắc tới nữa."""
    assert plan_tools("quý này lãi hay lỗ", ["vat"]) == []
    assert plan_tools("quý này lãi hay lỗ", ["report", "vat"]) == ["report"]


def test_khong_truyen_available_thi_khong_loc():
    assert plan_tools("quý này lãi hay lỗ") == ["report"]


# --------------------------------------------------------------------------
# Tool nào cần dữ liệu hệ thống
# --------------------------------------------------------------------------

def test_tool_can_du_lieu_he_thong():
    assert needs_system_data("report")
    assert needs_system_data("inventory_audit")
    # `vat` suy được từ chính lời người dùng nên KHÔNG cần bơm dữ liệu.
    assert not needs_system_data("vat")


def test_moi_tool_can_du_lieu_deu_co_that_trong_manifest():
    """
    Chống lệch tên. `NEEDS_SYSTEM_DATA` chặn tool chạy khi thiếu nguồn — gõ sai
    một tên ở đây là mở lại đúng cánh cửa nó sinh ra để đóng.
    """
    from src.api.routes.tools import get_tool_defs

    ten_that = {t["name"] for t in get_tool_defs()}
    assert NEEDS_SYSTEM_DATA <= ten_that
