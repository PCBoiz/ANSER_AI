"""
Kiểm thử trình đọc bảng TỔNG HỢP TỒN KHO (src/core/inventory_import.py).

Trọng tâm là LỚP TỰ KIỂM. Lỗi nguy hiểm nhất của mọi trình đọc bảng không
phải "đọc hỏng" — hỏng thì thấy ngay. Nguy hiểm là LỆCH CỘT: mọi con số vẫn
đọc được, vẫn trông hợp lý, nhưng nằm sai chỗ. Các test dưới đây cố tình làm
lệch để chắc rằng parser BÁO chứ không nuốt.
"""

from __future__ import annotations

import pytest

from src.core.inventory import audit_inventory
from src.core.inventory_import import (
    parse_inventory_table,
    parse_vn_number,
)

# ---------------------------------------------------------------------------
# Số theo quy ước Việt Nam
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expect", [
    ("57.660,45", 57660.45),
    ("254.755.000", 254755000.0),
    ("0,00", 0.0),
    ("3.810,52", 3810.52),
    ("(21,00)", -21.0),               # âm ghi bằng ngoặc — chuẩn kế toán
    ("(1.218.356)", -1218356.0),
    ("-1.500", -1500.0),
    ("1.579,20", 1579.2),
    (12345, 12345.0),                 # openpyxl trả số sẵn
    (57660.45, 57660.45),
])
def test_doc_so_viet_nam(raw, expect):
    assert parse_vn_number(raw) == pytest.approx(expect)


@pytest.mark.parametrize("raw", ["", "   ", None, "—", "n/a", ")"])
def test_o_rong_tra_none_chu_khong_tra_0(raw):
    """Nhầm 'chưa biết' với 0 là cách nhanh nhất để bịa ra một con số tài chính."""
    assert parse_vn_number(raw) is None


def test_dau_ngoac_roi_vai_khong_bien_thanh_so_am():
    """Bản xuất PDF hay rơi vãi ')' thừa giữa các ô."""
    assert parse_vn_number("38,40)") == pytest.approx(38.40)
    assert parse_vn_number("(38,40") == pytest.approx(38.40)


# ---------------------------------------------------------------------------
# Bảng mẫu — đúng hình dạng bản xuất MISA (header hai tầng, ô gộp)
# ---------------------------------------------------------------------------

def make_table(rows_data, totals=None):
    table = [
        ["CÔNG TY TNHH ABC"],
        ["Mã số thuế: 0100000000"],
        ["TỔNG HỢP TỒN KHO"],
        ["Kho: KHO HÀNG HÓA, Từ ngày 01/01/2026 đến ngày 24/07/2026"],
        [],
        # tầng nhóm: ô gộp -> chỉ ô đầu mỗi nhóm có chữ
        ["", "", "", "", "Đầu kỳ", "", "", "Nhập kho", "", "",
         "Xuất kho", "", "", "Cuối kỳ", "", ""],
        ["Tên kho", "Mã hàng", "Tên hàng", "ĐVT",
         "Số lượng", "Giá trị", "Đơn giá BQ",
         "Số lượng", "Giá trị", "Đơn giá BQ",
         "Số lượng", "Giá trị", "Đơn giá BQ",
         "Số lượng", "Giá trị", "Đơn giá BQ"],
    ]
    table += rows_data
    if totals:
        table.append(totals)
    return table


ROW_OK = ["KHO HÀNG HÓA", "VT00004", "Dầu ô tô SP/CF 15W-40", "Lít",
          "100,00", "6.000.000", "60.000,00",
          "400,00", "24.800.000", "62.000,00",
          "300,00", "18.480.000", "61.600,00",
          "200,00", "12.320.000", "61.600,00"]

ROW_NEG = ["KHO HÀNG HÓA", "VT00059", "Diesel CI4/SL (200L)", "Lít",
           "87,00", "5.016.459", "57.660,45",
           "4.400,00", "254.755.000", "57.898,86",
           "4.508,00", "260.989.815", "57.894,81",
           "(21,00)", "(1.218.356)", "58.016,95"]


def test_doc_duoc_sieu_du_lieu():
    r = parse_inventory_table(make_table([ROW_OK]))
    assert r.warehouse == "KHO HÀNG HÓA"
    assert r.period_start == "2026-01-01"
    assert r.period_end == "2026-07-24"


def test_doc_dung_mot_dong():
    r = parse_inventory_table(make_table([ROW_OK]))
    assert r.ok
    ln = r.lines[0]
    assert ln.code == "VT00004"
    assert ln.unit == "Lít"
    assert ln.opening_qty == 100.0
    assert ln.in_value == 24_800_000
    assert ln.out_value == 18_480_000        # = giá vốn hàng bán
    assert ln.closing_qty == 200.0


def test_doc_dung_dong_ton_am():
    r = parse_inventory_table(make_table([ROW_NEG]))
    ln = r.lines[0]
    assert ln.closing_qty == -21.0
    assert ln.closing_value == -1_218_356.0


def test_bo_qua_dong_tong_cong_nhung_dung_lam_doi_chieu():
    totals = ["Tổng cộng", "", "", "",
              "187,00", "11.016.459", "",
              "4.800,00", "279.555.000", "",
              "4.808,00", "279.469.815", "",
              "179,00", "11.101.644", ""]
    r = parse_inventory_table(make_table([ROW_OK, ROW_NEG], totals=totals))
    assert len(r.lines) == 2                       # dòng tổng KHÔNG thành hàng hoá
    assert r.checks["mismatches"] == []
    assert r.checks["totals"]["out_value"]["trong_file"] == 279_469_815


def test_tong_cong_lech_thi_bao_ngay():
    """Đây là lớp chặn LỆCH CỘT — file tự tố cáo chính nó."""
    totals = ["Tổng cộng", "", "", "",
              "187,00", "11.016.459", "",
              "4.800,00", "279.555.000", "",
              "4.808,00", "999.999.999", "",     # cố tình sai
              "179,00", "11.101.644", ""]
    r = parse_inventory_table(make_table([ROW_OK, ROW_NEG], totals=totals))
    assert not r.ok
    bad = [m for m in r.checks["mismatches"] if m["loại"] == "tổng_cộng"]
    assert bad and bad[0]["cột"] == "out_value"
    assert any("LỆCH CỘT" in w for w in r.warnings)


def test_don_gia_trong_file_lech_thi_bao():
    """Lớp chặn thứ hai: đơn giá BQ có sẵn phải khớp giá_trị / số_lượng."""
    row = list(ROW_OK)
    row[6] = "99.999,00"                            # đơn giá đầu kỳ sai
    r = parse_inventory_table(make_table([row]))
    assert not r.ok
    bad = [m for m in r.checks["mismatches"] if m["loại"] == "đơn_giá"]
    assert bad[0]["cột"] == "opening"
    assert bad[0]["đơn_giá_tính_lại"] == 60_000.0


def test_don_gia_lech_do_lam_tron_thi_bo_qua():
    row = list(ROW_OK)
    row[6] = "60.000,50"                            # lệch 0,5đ — kế toán làm tròn
    assert parse_inventory_table(make_table([row])).ok


# ---------------------------------------------------------------------------
# Hỏng định dạng
# ---------------------------------------------------------------------------

def test_khong_co_tieu_de_thi_bao_chu_khong_no():
    r = parse_inventory_table([["linh tinh"], ["1", "2", "3"]])
    assert r.lines == []
    assert any("Mã hàng" in w for w in r.warnings)
    assert not r.ok


def test_thieu_cot_bi_cat_thi_bao():
    """PDF nhiều trang hay tách Xuất kho / Cuối kỳ sang trang riêng."""
    table = [
        ["Kho: KHO KM, Từ ngày 01/01/2026 đến ngày 24/07/2026"],
        ["", "", "", "", "Đầu kỳ", "", ""],
        ["Tên kho", "Mã hàng", "Tên hàng", "ĐVT", "Số lượng", "Giá trị", "Đơn giá BQ"],
        ["KHO KM", "KM00001", "Dầu xe máy KM", "Lít", "836,80", "0", ""],
    ]
    r = parse_inventory_table(table)
    assert len(r.lines) == 1
    assert any("bị cắt cột" in w for w in r.warnings)


def test_khong_co_ngay_thi_noi_ro_hau_qua():
    table = make_table([ROW_OK])
    table[3] = ["Kho: KHO HÀNG HÓA"]
    r = parse_inventory_table(table)
    assert r.period_start is None
    assert any("hàng chết" in w for w in r.warnings)


def test_o_gia_tri_rong_giu_nguyen_none():
    row = list(ROW_OK)
    row[5] = row[8] = row[11] = row[14] = ""       # xoá hết cột giá trị
    ln = parse_inventory_table(make_table([row])).lines[0]
    assert ln.opening_value is None and ln.out_value is None
    assert ln.opening_qty == 100.0                 # số lượng vẫn đọc được


# ---------------------------------------------------------------------------
# Nối thẳng sang engine kiểm toán — đường đi thật từ file tới phát hiện
# ---------------------------------------------------------------------------

def test_doc_xong_kiem_toan_ra_dung_phat_hien():
    r = parse_inventory_table(make_table([ROW_OK, ROW_NEG]))
    audit = audit_inventory(r.lines, warehouse=r.warehouse,
                            period_start=r.period_start, period_end=r.period_end)
    assert audit["period"]["days"] == 204
    assert audit["warehouse"] == "KHO HÀNG HÓA"
    neg = [f for f in audit["findings"] if f["kind"] == "negative_stock"]
    assert neg and neg[0]["code"] == "VT00059"
    assert audit["summary"]["out_value"] == 18_480_000 + 260_989_815


def test_thieu_gia_tri_thi_bao_cao_dem_rieng_khong_coi_la_0():
    row = list(ROW_OK)
    row[5] = row[8] = row[11] = row[14] = ""
    r = parse_inventory_table(make_table([row, ROW_NEG]))
    audit = audit_inventory(r.lines, period_start=r.period_start,
                            period_end=r.period_end)
    assert any("thiếu cột giá trị" in w for w in audit["warnings"])
