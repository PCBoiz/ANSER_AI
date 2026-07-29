"""
Kiểm thử engine kiểm toán tồn kho (src/core/inventory.py).

DỮ LIỆU Ở ĐÂY LÀ TỔNG HỢP, KHÔNG PHẢI CỦA KHÁCH (P2).
Các con số được dựng lại để tái tạo ĐÚNG những quan hệ số học có trong bản
xuất thật của khách (TỔNG HỢP TỒN KHO, MISA), nhưng làm tròn cho dễ đọc:

  - tồn cuối âm (xuất nhiều hơn số có)
  - đơn giá tồn cuối cao hơn mọi giá đầu vào
  - FIFO và bình quân chạy song song trong cùng một kỳ
  - hàng chết, hàng bán chậm, giá nhập nhảy vọt
  - kho khuyến mại ghi số lượng nhưng giá trị bằng 0

Giá vốn thật của khách KHÔNG được commit vào repo.
"""

from __future__ import annotations

import pytest

from src.core.inventory import (
    InventoryLine,
    audit_inventory,
    fill_missing_cogs,
    unit_cost_table,
)
from src.core.reporting import ReportRequest, SaleLine, build_report

PERIOD = {"period_start": "2026-01-01", "period_end": "2026-07-24"}  # 204 ngày


def kinds(result, severity=None):
    return {
        f["kind"] for f in result["findings"]
        if severity is None or f["severity"] == severity
    }


def one(result, kind):
    hits = [f for f in result["findings"] if f["kind"] == kind]
    assert hits, f"không tìm thấy phát hiện '{kind}'; có: {kinds(result)}"
    return hits[0]


# --- một dòng hoàn toàn sạch: không được sinh phát hiện nào -----------------

CLEAN = InventoryLine(
    code="VT0001", name="Dầu động cơ A", unit="Lít",
    opening_qty=100, opening_value=6_000_000,      # 60.000/lít
    in_qty=400, in_value=24_800_000,               # 62.000/lít
    out_qty=300, out_value=18_480_000,             # 61.600 = bình quân cả kỳ
    closing_qty=200, closing_value=12_320_000,     # 61.600/lít
)


def test_dong_sach_khong_sinh_phat_hien():
    r = audit_inventory([CLEAN], **PERIOD)
    assert r["findings"] == []
    assert r["explain"]["confidence"] == "cao"


def test_can_doi_du_lieu_that_van_khop():
    """Bảng kế toán luôn cân đối — engine không được báo động giả ở đây."""
    r = audit_inventory([CLEAN], **PERIOD)
    assert "balance_mismatch" not in kinds(r)


# --- A. cân đối ------------------------------------------------------------

def test_lech_so_luong_bi_bat():
    ln = InventoryLine(code="X", opening_qty=10, in_qty=5, out_qty=3, closing_qty=99)
    f = one(audit_inventory([ln], **PERIOD), "balance_mismatch")
    assert f["severity"] == "cao"
    assert f["evidence"]["cuối_kỳ_phải_là"] == 12


def test_lech_gia_tri_bi_bat():
    ln = InventoryLine(
        code="X", opening_qty=10, opening_value=1000, in_qty=5, in_value=500,
        out_qty=3, out_value=300, closing_qty=12, closing_value=9999,
    )
    fs = [f for f in audit_inventory([ln], **PERIOD)["findings"]
          if f["kind"] == "balance_mismatch"]
    assert any(f["evidence"].get("cuối_kỳ_phải_là") == 1200 for f in fs)


def test_lam_tron_mot_dong_khong_bi_bao_dong_gia():
    """Phần mềm kế toán làm tròn đến đồng — chênh 1đ không phải lỗi."""
    ln = InventoryLine(
        code="X", opening_qty=10, opening_value=1000, in_qty=5, in_value=500,
        out_qty=3, out_value=300, closing_qty=12, closing_value=1201,
    )
    assert "balance_mismatch" not in kinds(audit_inventory([ln], **PERIOD))


# --- B. tồn âm -------------------------------------------------------------

def test_ton_am_bi_bat():
    """87 + 4400 − 4508 = −21: xuất nhiều hơn số thực có."""
    ln = InventoryLine(
        code="VT00059", name="Diesel 200L", unit="Lít",
        opening_qty=87, opening_value=5_000_000,
        in_qty=4400, in_value=254_000_000,
        out_qty=4508, out_value=260_200_000,
        closing_qty=-21, closing_value=-1_200_000,
    )
    f = one(audit_inventory([ln], **PERIOD), "negative_stock")
    assert f["severity"] == "cao"
    assert f["evidence"]["thiếu"] == 21
    assert f["money_impact"] == 1_200_000     # trị tuyệt đối, không âm


# --- C. trôi giá vốn + mâu thuẫn dấu ---------------------------------------
#
# Nhóm test này canh một hồi quy CỤ THỂ: bản đầu của engine coi "đơn giá tồn
# cuối cao hơn mọi giá đầu vào" là bằng chứng sổ ghi sai, và gắn cờ oan 18/18
# mã trên bản xuất thật. Với FIFO + giá tăng trong kỳ, đó là kết quả ĐÚNG.

def test_fifo_gia_tang_KHONG_bi_coi_la_loi():
    """
    Hồi quy 30/07/2026. Chữ ký FIFO giá tăng: xuất < bình quân < tồn cuối.
    Không có giá từng lô thì không thể kết luận sổ sai — và không được kết luận.
    """
    ln = InventoryLine(
        code="VT00023", unit="Lít",
        opening_qty=100, opening_value=5_000_000,     # 50.000
        in_qty=900, in_value=54_000_000,              # 60.000 bình quân cả kỳ
        out_qty=900, out_value=52_000_000,            # 57.777 — bán lô cũ rẻ
        closing_qty=100, closing_value=7_000_000,     # 70.000 — còn lô mới đắt
    )
    ks = kinds(audit_inventory([ln], **PERIOD))
    assert "impossible_closing_cost" not in ks
    assert "impossible_out_cost" not in ks


def test_gia_von_ton_cao_hon_da_ban_thi_canh_bao_bien_ky_sau():
    """Con số đó nói chuyện của kỳ SAU, không phải lỗi của kỳ này."""
    ln = InventoryLine(
        code="VT00023", unit="Lít",
        opening_qty=100, opening_value=5_000_000,
        in_qty=900, in_value=54_000_000,
        out_qty=900, out_value=52_000_000,            # 57.777,78/lít
        closing_qty=100, closing_value=7_000_000,     # 70.000/lít
    )
    f = one(audit_inventory([ln], **PERIOD), "rising_cost_basis")
    assert f["severity"] == "trung bình"
    assert f["evidence"]["chênh_lệch_pct"] == pytest.approx(21.2, abs=0.3)
    assert f["money_impact"] == pytest.approx(1_222_222, abs=2)
    assert "biên lợi nhuận kỳ sau" in f["suggestion"]


def test_gia_von_ton_thap_hon_da_ban_la_co_hoi_khong_phai_loi():
    ln = InventoryLine(
        code="Y", opening_qty=100, opening_value=7_000_000,
        in_qty=100, in_value=5_000_000,
        out_qty=100, out_value=7_000_000,             # 70.000
        closing_qty=100, closing_value=5_000_000,     # 50.000
    )
    f = one(audit_inventory([ln], **PERIOD), "falling_cost_basis")
    assert f["severity"] == "thấp"


def test_troi_gia_von_nho_thi_im_lang():
    ln = InventoryLine(
        code="Y", opening_qty=100, opening_value=5_000_000,
        in_qty=100, in_value=5_100_000,
        out_qty=100, out_value=5_000_000,             # 50.000
        closing_qty=100, closing_value=5_100_000,     # 51.000 -> +2%
    )
    ks = kinds(audit_inventory([ln], **PERIOD))
    assert "rising_cost_basis" not in ks


def test_con_hang_ma_gia_tri_am_la_mau_thuan_that():
    ln = InventoryLine(code="Z", opening_qty=0, opening_value=0,
                       in_qty=100, in_value=1_000_000,
                       out_qty=40, out_value=2_000_000,
                       closing_qty=60, closing_value=-1_000_000)
    f = one(audit_inventory([ln], **PERIOD), "value_sign_conflict")
    assert f["severity"] == "cao"
    assert f["money_impact"] == 1_000_000


def test_het_hang_ma_con_gia_tri_treo_lai():
    ln = InventoryLine(code="Z", opening_qty=100, opening_value=5_000_000,
                       in_qty=0, in_value=0,
                       out_qty=100, out_value=3_000_000,
                       closing_qty=0, closing_value=2_000_000)
    f = one(audit_inventory([ln], **PERIOD), "value_sign_conflict")
    assert "treo lại" in f["suggestion"]


# --- D. phương pháp tính giá vốn -------------------------------------------

_BINH_QUAN = InventoryLine(
    code="BQ1", opening_qty=100, opening_value=5_000_000,   # 50.000
    in_qty=100, in_value=7_000_000,                         # 70.000
    out_qty=100, out_value=6_000_000,                       # 60.000 = bình quân
    closing_qty=100, closing_value=6_000_000,
)
_FIFO = InventoryLine(
    code="FF1", opening_qty=140, opening_value=9_800_000,   # 70.000
    in_qty=320, in_value=29_760_000,                        # 93.000
    out_qty=105, out_value=7_350_000,                       # 70.000 = giá lô đầu kỳ
    closing_qty=355, closing_value=32_210_000,
)


def test_mot_phuong_phap_thi_khong_canh_bao():
    assert "costing_method_mixed" not in kinds(audit_inventory([_BINH_QUAN], **PERIOD))


def test_hai_phuong_phap_song_song_bi_bat():
    r = audit_inventory([_BINH_QUAN, _BINH_QUAN, _FIFO], **PERIOD)
    f = one(r, "costing_method_mixed")
    assert f["severity"] == "cao"
    assert set(f["evidence"]["phương_pháp"]) == {"bình quân", "fifo"}
    assert f["evidence"]["đa_số"] == "bình quân"
    # FIFO là thiểu số -> báo chênh nếu quy về bình quân:
    # bq = (9.8tr + 29.76tr)/460 = 86.000/lít; 105 lít -> 9.03tr so với 7.35tr ghi sổ
    assert f["evidence"]["chi_tiết_thiểu_số"][0]["mã"] == "FF1"
    assert f["money_impact"] == pytest.approx(1_680_000, abs=5_000)


def test_khong_doan_phuong_phap_khi_thieu_bang_chung():
    """Giá đầu kỳ trùng giá nhập -> FIFO và bình quân cho cùng kết quả."""
    ln = InventoryLine(
        code="A", opening_qty=100, opening_value=5_000_000,
        in_qty=100, in_value=5_000_000, out_qty=50, out_value=2_500_000,
        closing_qty=150, closing_value=7_500_000,
    )
    r = audit_inventory([ln], **PERIOD)
    assert r["explain"]["costing_methods_detected"] == {}


def test_bien_gia_qua_hep_thi_khong_ket_luan_phuong_phap():
    """
    Hồi quy 30/07/2026: trên bản xuất thật, VT00016 lệch 5đ và VT00036 lệch
    209đ giữa giá đầu kỳ và giá nhập. Ở biên đó FIFO và bình quân cho cùng con
    số, nên mọi kết luận về phương pháp đều là nhiễu.
    """
    ln = InventoryLine(
        code="VT00016", opening_qty=252, opening_value=252 * 59_395,
        in_qty=1000, in_value=1000 * 59_400,
        out_qty=1000, out_value=1000 * 59_399,
        closing_qty=252, closing_value=252 * 59_399,
    )
    assert audit_inventory([ln], **PERIOD)["explain"]["costing_methods_detected"] == {}


def test_binh_quan_doi_ca_hang_xuat_lan_hang_ton_cung_don_gia():
    """
    Chữ ký bình quân là CẢ BA trùng nhau (xuất = tồn = bình quân). Chỉ so đơn
    giá xuất với bình quân là không đủ — đó là lỗi của bản đầu, khiến FIFO giá
    tăng bị nhận nhầm thành bình quân trên dữ liệu thật.
    """
    fifo_gia_tang = InventoryLine(
        code="VT00013", opening_qty=432, opening_value=432 * 64_889,
        in_qty=200, in_value=200 * 72_199,
        out_qty=101, out_value=101 * 64_889,        # đúng giá lô đầu kỳ
        closing_qty=531,
        closing_value=432 * 64_889 + 200 * 72_199 - 101 * 64_889,
    )
    detected = audit_inventory([fifo_gia_tang], **PERIOD)["explain"]["costing_methods_detected"]
    assert list(detected) == ["fifo"]


# --- E. hàng chết / bán chậm -----------------------------------------------

def test_hang_chet_bi_bat_khi_ky_du_dai():
    ln = InventoryLine(code="D", opening_qty=50, opening_value=3_000_000,
                       closing_qty=50, closing_value=3_000_000)
    f = one(audit_inventory([ln], **PERIOD), "dead_stock")
    assert f["money_impact"] == 3_000_000


def test_ky_ngan_thi_chua_xuat_la_binh_thuong():
    ln = InventoryLine(code="D", opening_qty=50, opening_value=3_000_000,
                       closing_qty=50, closing_value=3_000_000)
    r = audit_inventory([ln], period_start="2026-07-01", period_end="2026-07-24")
    assert "dead_stock" not in kinds(r)


def test_hang_ban_cham_bi_bat():
    """Bán 105 trong 204 ngày, tồn 355 -> đủ bán ~690 ngày."""
    r = audit_inventory([_FIFO], **PERIOD)
    f = one(r, "slow_moving")
    assert f["evidence"]["số_ngày_đủ_bán"] == pytest.approx(690, abs=15)


# --- F. giá nhập nhảy vọt ---------------------------------------------------

def test_gia_nhap_tang_manh_bi_canh_bao():
    f = one(audit_inventory([_FIFO], **PERIOD), "price_jump")
    assert f["evidence"]["thay_đổi_pct"] == pytest.approx(32.9, abs=0.5)
    assert "bán lỗ" in f["suggestion"]


def test_gia_nhap_giam_la_muc_thap():
    ln = InventoryLine(code="G", opening_qty=10, opening_value=1_000_000,
                       in_qty=10, in_value=700_000, out_qty=20, out_value=1_700_000,
                       closing_qty=0, closing_value=0)
    f = one(audit_inventory([ln], **PERIOD), "price_jump")
    assert f["severity"] == "thấp"


# --- G. kho khuyến mại: có số lượng, không có giá trị -----------------------

def test_hang_khong_ghi_nhan_gia_tri():
    ln = InventoryLine(code="KM00001", name="Dầu xe máy KM", unit="Lít",
                       opening_qty=836.8, opening_value=0,
                       in_qty=2092.8, in_value=0,
                       out_qty=1497.6, out_value=0,
                       closing_qty=1432.0, closing_value=0)
    f = one(audit_inventory([ln], warehouse="KHO KHUYẾN MẠI", **PERIOD),
            "zero_valued_stock")
    assert f["severity"] == "cao"
    assert "bỏ ngoài sổ" in f["suggestion"]


def test_hang_ton_khong_phat_sinh_thi_khong_bao_gia_tri_0():
    """Chưa nhập chưa xuất thì giá trị 0 không nói lên điều gì."""
    ln = InventoryLine(code="K", opening_qty=5, opening_value=0, closing_qty=5,
                       closing_value=0)
    assert "zero_valued_stock" not in kinds(audit_inventory([ln], **PERIOD))


# --- H. tổng hợp & xếp hạng -------------------------------------------------

def test_tong_hop_va_vong_quay():
    r = audit_inventory([CLEAN], **PERIOD)
    s = r["summary"]
    assert s["out_value"] == 18_480_000          # = giá vốn hàng bán của kỳ
    assert s["closing_value"] == 12_320_000
    # tồn bình quân (6tr + 12,32tr)/2 = 9,16tr -> vòng quay 18,48/9,16
    assert s["turnover"] == pytest.approx(2.02, abs=0.05)
    assert s["days_on_hand"] == pytest.approx(101, abs=3)


def test_nhan_dien_mua_dut_ban_doan():
    cd = InventoryLine(code="CD", in_qty=100, in_value=6_000_000,
                       out_qty=100, out_value=6_000_000,
                       closing_qty=0, closing_value=0)
    s = audit_inventory([cd, CLEAN], **PERIOD)["summary"]
    assert s["cross_dock_skus"] == 1
    assert s["cross_dock_value"] == 6_000_000


def test_thieu_cot_gia_tri_duoc_dem_rieng_khong_coi_la_0():
    ln = InventoryLine(code="M", opening_qty=10, in_qty=5, out_qty=5, closing_qty=10)
    r = audit_inventory([ln, CLEAN], **PERIOD)
    assert any("thiếu cột giá trị" in w for w in r["warnings"])
    assert r["summary"]["out_value"] == CLEAN.out_value   # không cộng None như 0


def test_phat_hien_xep_theo_muc_do_nghiem_trong():
    ln_cao = InventoryLine(code="A", opening_qty=1, in_qty=0, out_qty=5,
                           closing_qty=-4, closing_value=-100)
    ln_tb = InventoryLine(code="B", opening_qty=50, opening_value=3_000_000,
                          closing_qty=50, closing_value=3_000_000)
    r = audit_inventory([ln_tb, ln_cao], **PERIOD)
    assert r["findings"][0]["severity"] == "cao"
    assert r["explain"]["confidence"] == "trung bình"
    assert any("mức CAO" in w for w in r["warnings"])


# --- I. cầu nối sang reporting.py ------------------------------------------

def test_bang_tra_don_gia_uu_tien_gia_xuat():
    t = unit_cost_table([CLEAN])
    assert t["VT0001"] == pytest.approx(61_600)
    assert t["Dầu động cơ A"] == pytest.approx(61_600)   # tra được cả bằng tên


def test_bang_tra_lui_ve_ton_cuoi_khi_khong_co_xuat():
    ln = InventoryLine(code="P", opening_qty=0, in_qty=10, in_value=500_000,
                       out_qty=0, out_value=0, closing_qty=10, closing_value=500_000)
    assert unit_cost_table([ln])["P"] == pytest.approx(50_000)


def test_dien_gia_von_con_thieu():
    sales = [
        SaleLine(date="2026-03-01", revenue=1_000_000, product="VT0001", quantity=10),
        SaleLine(date="2026-03-02", revenue=500_000, product="Dầu động cơ A", quantity=5),
    ]
    stats = fill_missing_cogs(sales, unit_cost_table([CLEAN]))
    assert stats["filled"] == 2
    assert stats["coverage_pct"] == 100.0
    assert sales[0].cogs == pytest.approx(616_000)
    assert any("ƯỚC TÍNH" in n for n in stats["notes"])


def test_khong_ghi_de_gia_von_da_co():
    sales = [SaleLine(date="2026-03-01", revenue=1_000_000, product="VT0001",
                      quantity=10, cogs=123_456)]
    stats = fill_missing_cogs(sales, unit_cost_table([CLEAN]))
    assert sales[0].cogs == 123_456
    assert stats["filled"] == 0 and stats["already_had_cogs"] == 1


def test_thieu_so_luong_thi_bo_qua_chu_khong_doan():
    sales = [SaleLine(date="2026-03-01", revenue=1_000_000, product="VT0001")]
    stats = fill_missing_cogs(sales, unit_cost_table([CLEAN]))
    assert sales[0].cogs is None
    assert stats["skipped_no_quantity"] == 1


def test_khong_khop_ten_thi_bao_ro():
    sales = [SaleLine(date="2026-03-01", revenue=1_000_000, product="Hàng lạ",
                      quantity=3)]
    stats = fill_missing_cogs(sales, unit_cost_table([CLEAN]))
    assert stats["skipped_no_match"] == 1
    assert sales[0].cogs is None


def test_cau_noi_nang_do_phu_gia_von_cua_bao_cao():
    """Đây là lý do tồn tại của cả module: báo cáo lãi lỗ hết phải nói 'chưa đủ'."""
    sales = [
        SaleLine(date="2026-03-01", revenue=1_000_000, product="VT0001", quantity=10),
        SaleLine(date="2026-04-01", revenue=2_000_000, product="VT0001", quantity=20),
    ]
    truoc = build_report(ReportRequest(granularity="quarter", sales=list(sales)))
    assert truoc["explain"]["cogs_coverage_pct"] == 0.0
    assert truoc["explain"]["confidence"] == "thấp"

    fill_missing_cogs(sales, unit_cost_table([CLEAN]))
    sau = build_report(ReportRequest(granularity="quarter", sales=sales))
    assert sau["explain"]["cogs_coverage_pct"] == 100.0
    assert sau["explain"]["confidence"] == "cao"


# --- J. tầng REST + vòng agentic -------------------------------------------

_LINE_JSON = {
    "code": "VT00023", "name": "Diesel CF-4", "unit": "Lít",
    "opening_qty": 100, "opening_value": 5_000_000,
    "in_qty": 900, "in_value": 54_000_000,
    "out_qty": 900, "out_value": 52_000_000,
    "closing_qty": 100, "closing_value": 7_000_000,
}


def test_endpoint_inventory_audit():
    from fastapi.testclient import TestClient

    from src.api.main import app

    resp = TestClient(app).post("/tools/inventory-audit", json={
        "lines": [_LINE_JSON], "warehouse": "KHO HÀNG HÓA",
        "period_start": "2026-01-01", "period_end": "2026-07-24",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["warehouse"] == "KHO HÀNG HÓA"
    assert body["period"]["days"] == 204
    assert "rising_cost_basis" in {f["kind"] for f in body["findings"]}


@pytest.mark.asyncio
async def test_vong_agentic_goi_duoc_tool():
    """Tool phải gọi được qua run_tool — cùng một định nghĩa, ba nơi dùng (P4)."""
    from src.api.routes.tools import get_tool_defs, run_tool

    assert "inventory_audit" in {t["name"] for t in get_tool_defs()}
    out = await run_tool("inventory_audit", {"lines": [_LINE_JSON]})
    assert "findings" in out and "error" not in out


@pytest.mark.asyncio
async def test_tham_so_sai_tra_loi_co_cau_truc_khong_nem_ngoai_le():
    from src.api.routes.tools import run_tool

    out = await run_tool("inventory_audit", {"lines": [{"name": "thiếu mã"}]})
    assert out["error"] == "tham số không hợp lệ"
