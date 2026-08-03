"""
tests/test_inventory_import_api.py — POST /tools/inventory-import (nạp .xlsx).

Đây là đường Body dùng để kiểm kho: khách xuất bảng tổng hợp N-X-T từ MISA,
người dùng tải file lên, Brain đọc + tự kiểm + kiểm sổ trong một lần gọi.

Test dựng file .xlsx THẬT bằng openpyxl rồi bắn qua HTTP, chứ không mock lớp
đọc — vì phần hay hỏng nhất chính là lớp đọc đó (30/07/2026: parser đọc đúng
tên kho và mã hàng nhưng không map được cột số nào mà vẫn báo ok).
"""

from __future__ import annotations

from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)
openpyxl = pytest.importorskip("openpyxl")

URL = "/tools/inventory-import"


# ---------------------------------------------------------------------------
# Dựng file .xlsx đúng hình dạng MISA xuất ra
# ---------------------------------------------------------------------------

def _xlsx(rows: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _misa_rows(data_rows: list[list], totals: list | None = None) -> list[list]:
    """
    Bố cục thật của MISA: nhóm cột nằm CÙNG dòng với 'Mã hàng', cột con ở dòng kế.

        | Mã hàng | Tên hàng | ĐVT | Đầu kỳ |     | Nhập kho |     | ...
        |         |          |     | SL     | GT  | SL       | GT  | ...
    """
    return [
        ["BÁO CÁO TỔNG HỢP TỒN KHO"],
        ["Kho: KHO HÀNG HÓA"],
        ["Từ ngày 01/01/2026 đến ngày 24/07/2026"],
        ["Mã hàng", "Tên hàng", "ĐVT",
         "Đầu kỳ", None, "Nhập kho", None, "Xuất kho", None, "Cuối kỳ", None],
        [None, None, None,
         "Số lượng", "Giá trị", "Số lượng", "Giá trị",
         "Số lượng", "Giá trị", "Số lượng", "Giá trị"],
        *data_rows,
        *([totals] if totals else []),
    ]


def _post(content: bytes, name: str = "ton_kho.xlsx", **kwargs):
    return client.post(
        URL,
        files={"file": (name, content,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Đường đi thuận
# ---------------------------------------------------------------------------

def test_doc_duoc_file_misa_va_kiem_luon():
    body = _post(_xlsx(_misa_rows([
        ["VT001", "Dầu CF-4 18L", "Lít", 100, 5_000_000, 400, 20_000_000,
         450, 22_500_000, 50, 2_500_000],
    ]))).json()

    imp = body["import"]
    assert imp["ok"] is True, imp
    assert imp["warehouse"] == "KHO HÀNG HÓA"
    assert imp["period_start"] == "2026-01-01"
    assert imp["period_end"] == "2026-07-24"
    assert imp["rows_parsed"] == 1
    assert imp["lines"][0]["code"] == "VT001"
    assert imp["lines"][0]["opening_value"] == 5_000_000
    assert body["audit"] is not None
    assert body["audit_skipped_reason"] is None


def test_suy_ra_gia_von_uu_tien_don_gia_xuat():
    """
    Giá vốn ưu tiên đơn giá XUẤT (giá vốn thật đã phát sinh), lùi về tồn cuối
    rồi tồn đầu. Body dùng bảng này điền cột giá vốn, nên nguồn phải nói rõ —
    "xuất" và "tồn đầu" không đáng tin như nhau.
    """
    body = _post(_xlsx(_misa_rows([
        # có xuất -> 22.500.000 / 450 = 50.000
        ["VT001", "Có xuất", "Lít", 100, 5_000_000, 400, 20_000_000,
         450, 22_500_000, 50, 2_500_000],
        # không xuất, có tồn cuối -> 6.000.000 / 100 = 60.000
        ["VT002", "Chỉ tồn cuối", "Lít", 0, 0, 100, 6_000_000, 0, 0, 100, 6_000_000],
        # xuất hết nhưng cột giá trị xuất bỏ trống -> phải lùi tận về tồn đầu:
        # 7.000.000 / 100 = 70.000 (tồn cuối = 0 nên không chia được)
        ["VT003", "Chỉ tồn đầu", "Lít", 100, 7_000_000, 0, 0, 100, None, 0, 0],
    ]))).json()

    costs = {c["code"]: c for c in body["unit_costs"]}
    assert costs["VT001"] == {"code": "VT001", "name": "Có xuất", "unit": "Lít",
                              "unit_cost": 50_000, "source": "xuất"}
    assert costs["VT002"]["unit_cost"] == 60_000
    assert costs["VT002"]["source"] == "tồn cuối"
    assert costs["VT003"]["unit_cost"] == 70_000
    assert costs["VT003"]["source"] == "tồn đầu"


def test_hang_khong_suy_duoc_gia_von_thi_KHONG_co_trong_bang():
    """Không có gì để chia thì bỏ hẳn ra, chứ không đưa vào với giá 0."""
    body = _post(_xlsx(_misa_rows([
        ["VT004", "Không có giá trị nào", "Cái", 10, None, 0, None, 0, None, 10, None],
    ]))).json()
    assert body["unit_costs"] == []


def test_doc_hong_thi_KHONG_tra_gia_von():
    """
    Cùng lý do với audit — nhưng nặng hơn: bản kiểm sai thì người ta đọc rồi bỏ,
    còn giá vốn sai thì nằm lại trong DB và chảy vào mọi báo cáo lãi lỗ về sau.
    """
    body = _post(_xlsx([["Doanh thu", "Chi phí"], [1, 2]])).json()
    assert body["import"]["ok"] is False
    assert body["unit_costs"] == []
    assert body["audit"] is None


def test_bat_ton_am_tren_file_that():
    body = _post(_xlsx(_misa_rows([
        ["VT059", "Diesel CI4/SL", "Lít", 87, 5_016_459, 4400, 254_755_000,
         4508, 260_989_815, -21, -1_218_356],
    ]))).json()
    assert body["import"]["ok"] is True, body["import"]
    kinds = {f["kind"] for f in body["audit"]["findings"]}
    assert "negative_stock" in kinds


def test_so_kieu_viet_nam_doc_dung():
    """'1.500.000' là một triệu rưỡi, không phải 1.5 — cột giá trị hay dính nhất."""
    body = _post(_xlsx(_misa_rows([
        ["VT002", "Mỡ bò L3", "Kg", "10", "1.500.000", "0", "0",
         "0", "0", "10", "1.500.000"],
    ]))).json()
    line = body["import"]["lines"][0]
    assert line["opening_value"] == 1_500_000
    assert line["closing_value"] == 1_500_000


def test_gia_tri_am_trong_ngoac_doc_ra_so_am():
    body = _post(_xlsx(_misa_rows([
        ["VT003", "Hàng lỗi", "Cái", "(5)", "(1.000.000)", "0", "0",
         "0", "0", "(5)", "(1.000.000)"],
    ]))).json()
    line = body["import"]["lines"][0]
    assert line["opening_qty"] == -5
    assert line["opening_value"] == -1_000_000


# ---------------------------------------------------------------------------
# Đọc hỏng thì KHÔNG kiểm — điểm quan trọng nhất của endpoint này
# ---------------------------------------------------------------------------

def test_bang_khong_co_tieu_de_thi_tu_choi_kiem():
    """
    Bảng sai định dạng: đọc ra 0 dòng. Nếu vẫn chạy kiểm thì kết quả là
    'không phát hiện lỗi nào' — nghe y như một bộ sổ sạch sẽ.
    """
    body = _post(_xlsx([["Doanh thu", "Chi phí"], [1, 2]])).json()
    assert body["import"]["ok"] is False
    assert body["audit"] is None
    assert body["audit_skipped_reason"]


def test_thieu_cot_so_luong_thi_tu_choi_kiem():
    """PDF/Excel nhiều trang hay bị cắt mất cụm 'Xuất kho' / 'Cuối kỳ'."""
    rows = [
        ["Kho: KHO A"],
        ["Mã hàng", "Tên hàng", "ĐVT", "Đầu kỳ", None, "Nhập kho", None],
        [None, None, None, "Số lượng", "Giá trị", "Số lượng", "Giá trị"],
        ["VT001", "Dầu", "Lít", 10, 500_000, 5, 250_000],
    ]
    body = _post(_xlsx(rows)).json()
    assert body["import"]["ok"] is False
    assert "out_qty" in body["import"]["checks"]["missing_columns"]
    assert body["audit"] is None


def test_lech_cot_bi_bat_qua_don_gia_va_khong_kiem():
    """
    Lớp tự kiểm 1: đơn giá BQ ghi trong file phải khớp giá_trị / số_lượng.
    Đây là cách duy nhất bắt được lệch cột — mọi con số vẫn 'hợp lý'.
    """
    rows = [
        ["Kho: KHO A"],
        ["Mã hàng", "Tên hàng", "ĐVT", "Đầu kỳ", None, None,
         "Nhập kho", None, None, "Xuất kho", None, "Cuối kỳ", None],
        [None, None, None, "Số lượng", "Đơn giá", "Giá trị",
         "Số lượng", "Đơn giá", "Giá trị", "Số lượng", "Giá trị",
         "Số lượng", "Giá trị"],
        # đơn giá ghi 50.000 nhưng 5.000.000/100 = 50.000 -> khớp ở dòng này
        ["VT001", "Dầu", "Lít", 100, 50_000, 5_000_000, 0, 0, 0, 0, 0, 100, 5_000_000],
        # đơn giá ghi 90.000 trong khi 5.000.000/100 = 50.000 -> LỆCH
        ["VT002", "Nhớt", "Lít", 100, 90_000, 5_000_000, 0, 0, 0, 0, 0, 100, 5_000_000],
    ]
    body = _post(_xlsx(rows)).json()
    assert body["import"]["ok"] is False
    assert body["import"]["checks"]["mismatches"], body["import"]["checks"]
    assert body["audit"] is None, "đọc lệch cột mà vẫn kiểm là tệ hơn không kiểm"


def test_tong_cong_lech_thi_tu_choi_kiem():
    """Lớp tự kiểm 2: dòng 'Tổng cộng' của chính file phải khớp tổng ta cộng."""
    body = _post(_xlsx(_misa_rows(
        [["VT001", "Dầu", "Lít", 100, 5_000_000, 0, 0, 0, 0, 100, 5_000_000],
         ["VT002", "Nhớt", "Lít", 100, 5_000_000, 0, 0, 0, 0, 100, 5_000_000]],
        totals=["Tổng cộng", None, None, 200, 99_999_999, 0, 0, 0, 0, 200, 10_000_000],
    ))).json()
    assert body["import"]["ok"] is False
    assert body["audit"] is None


# ---------------------------------------------------------------------------
# File hỏng / sai loại — thông báo phải nói được phải làm gì
# ---------------------------------------------------------------------------

def test_file_xls_doi_cu_bao_ro_cach_sua():
    resp = _post(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64, name="ton_kho.xls")
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert ".xls" in detail and "xlsx" in detail.lower()


def test_file_pdf_bao_xin_lai_ban_excel():
    resp = _post(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n", name="ton_kho.pdf")
    assert resp.status_code == 422
    assert "Excel" in resp.json()["detail"]


def test_file_rong_khong_no_500():
    resp = _post(b"", name="rong.xlsx")
    assert resp.status_code == 422
    assert "rỗng" in resp.json()["detail"]


def test_zip_khong_phai_xlsx_tra_422_chu_khong_500():
    """Bắt đầu bằng 'PK' nên qua được cửa magic-byte, openpyxl mới là chỗ nổ."""
    resp = _post(b"PK\x03\x04" + b"\x00" * 64, name="fake.xlsx")
    assert resp.status_code in (422, 400), resp.text
    assert resp.status_code != 500


def test_sheet_khong_ton_tai_bao_ten_sheet_co_that():
    resp = client.post(
        URL,
        files={"file": ("ton_kho.xlsx", _xlsx(_misa_rows(
            [["VT001", "Dầu", "Lít", 1, 1, 0, 0, 0, 0, 1, 1]])),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"sheet": "KhongCoSheetNay"},
    )
    assert resp.status_code == 422
    assert "Sheet" in resp.json()["detail"]


def test_thieu_file_tra_422_chu_khong_no():
    assert client.post(URL).status_code == 422


# ---------------------------------------------------------------------------
# Không nằm trong manifest — cố ý
# ---------------------------------------------------------------------------

def test_khong_quang_cao_trong_manifest_vi_model_khong_gui_duoc_file():
    """
    Endpoint này nhận multipart. Đưa vào manifest là hứa với MCP client một tool
    mà gọi kiểu gì cũng hỏng — `run_tool` dựng request bằng pydantic model.
    """
    names = {t["name"] for t in client.get("/tools").json()["tools"]}
    assert "inventory_import" not in names
    assert "inventory_audit" in names, "bản JSON thì vẫn phải còn"
