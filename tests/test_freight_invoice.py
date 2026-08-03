"""
tests/test_freight_invoice.py — hoá đơn cước vận tải: lược đồ + kiểm số học.

Lớp kiểm số học là phòng thủ chính của cả nhánh VLM: nó bắt lỗi đọc mà không cần
người soi. Nên bài kiểm ở đây tập trung vào một câu hỏi — **một tờ hoá đơn bị đọc
sai có lọt qua được không?**
"""

from __future__ import annotations

import pytest

from src.core.freight_invoice import FreightCharge, FreightInvoice, json_schema, verify


def _hoa_don(**kwargs) -> FreightInvoice:
    mac_dinh = dict(
        carrier_name="Nhà xe Minh Thành",
        invoice_date="2026-03-14",
        origin="Hà Nội", destination="Đà Nẵng",
        vehicle_type="xe tải 5 tấn", plate_number="29H-123.45",
        charges=[
            FreightCharge(kind="cước", description="HN-ĐN", quantity=2, unit_price=12_000_000),
            FreightCharge(kind="bốc xếp", quantity=1, unit_price=500_000),
        ],
        vat_rate=8.0,
        subtotal=24_500_000,
        vat_amount=1_960_000,
        total=26_460_000,
    )
    mac_dinh.update(kwargs)
    return FreightInvoice(**mac_dinh)


# ---------------------------------------------------------------------------
# Hoá đơn đúng
# ---------------------------------------------------------------------------

def test_hoa_don_dung_thi_qua():
    kq = verify(_hoa_don())
    assert kq["ok"] is True, kq["issues"]
    assert set(kq["checks_performed"]) == {"cộng_tiền_hàng", "tiền_thuế", "tổng_cộng"}
    assert kq["missing_required"] == []


def test_tinh_lai_dung_con_so():
    kq = verify(_hoa_don())
    assert kq["computed"]["subtotal"] == 24_500_000   # 2×12.000.000 + 500.000
    assert kq["computed"]["vat_amount"] == 1_960_000  # 8% của 24.500.000
    assert kq["computed"]["total"] == 26_460_000


def test_chenh_lech_lam_tron_vai_tram_dong_khong_bi_bao_loi():
    """Kế toán làm tròn; báo lỗi vì lệch 300đ là biến lớp kiểm thành phiền nhiễu."""
    assert verify(_hoa_don(total=26_460_300))["ok"] is True


# ---------------------------------------------------------------------------
# Đọc SAI phải bị bắt — đây là lý do lớp này tồn tại
# ---------------------------------------------------------------------------

def test_doc_nham_mot_chu_so_o_don_gia_bi_bat():
    """`12.000.000` đọc thành `72.000.000` — tổng không còn khớp."""
    kq = verify(_hoa_don(charges=[
        FreightCharge(kind="cước", quantity=2, unit_price=72_000_000),
        FreightCharge(kind="bốc xếp", quantity=1, unit_price=500_000),
    ]))
    assert kq["ok"] is False
    assert any("Cộng tiền hàng lệch" in i for i in kq["issues"])


def test_doc_nham_TONG_CONG_bi_bat():
    kq = verify(_hoa_don(total=2_646_000))
    assert kq["ok"] is False
    assert any("Tổng cộng lệch" in i for i in kq["issues"])


def test_doc_nham_TIEN_THUE_bi_bat():
    kq = verify(_hoa_don(vat_amount=2_450_000))   # 10% trong khi ghi 8%
    assert kq["ok"] is False
    assert any("Tiền thuế lệch" in i for i in kq["issues"])


def test_bo_sot_mot_khoan_phi_bi_bat():
    """Phụ phí bốc xếp bị bỏ sót -> cộng tiền hàng thiếu."""
    kq = verify(_hoa_don(charges=[
        FreightCharge(kind="cước", quantity=2, unit_price=12_000_000),
    ]))
    assert kq["ok"] is False


def test_doc_nham_SO_CHUYEN_bi_bat():
    kq = verify(_hoa_don(charges=[
        FreightCharge(kind="cước", quantity=3, unit_price=12_000_000),
        FreightCharge(kind="bốc xếp", quantity=1, unit_price=500_000),
    ]))
    assert kq["ok"] is False


# ---------------------------------------------------------------------------
# "Không kiểm được" KHÁC "đã kiểm và đúng"
# ---------------------------------------------------------------------------

def test_doc_ra_rong_KHONG_duoc_coi_la_dat():
    """
    Gộp "không kiểm được" với "đúng" là cách nhanh nhất để một tờ sai đi lọt:
    ảnh mờ đọc ra rỗng sẽ hiện lên như một hoá đơn sạch.
    """
    kq = verify(FreightInvoice())
    assert kq["ok"] is False
    assert kq["checks_performed"] == []


def test_khong_doc_duoc_tong_cong_thi_khong_dat():
    kq = verify(_hoa_don(total=None))
    assert kq["ok"] is False
    assert any("TỔNG CỘNG" in i for i in kq["issues"])
    assert "total" in kq["missing_required"]


def test_thieu_ten_nha_xe_va_ngay_bi_liet_ke():
    kq = verify(_hoa_don(carrier_name=None, invoice_date=None))
    assert set(kq["missing_required"]) == {"carrier_name", "invoice_date"}


def test_khong_co_khoan_nao_thi_bao_ro():
    kq = verify(_hoa_don(charges=[], subtotal=None, vat_amount=None, total=26_460_000))
    assert kq["ok"] is False
    assert any("chưa có gì để kiểm" in i for i in kq["issues"])


# ---------------------------------------------------------------------------
# Thiếu một phần vẫn kiểm được phần còn lại
# ---------------------------------------------------------------------------

def test_khong_ghi_cong_tien_hang_van_kiem_duoc_tong():
    kq = verify(_hoa_don(subtotal=None))
    assert kq["ok"] is True, kq["issues"]
    assert "cộng_tiền_hàng" not in kq["checks_performed"]
    assert "tổng_cộng" in kq["checks_performed"]


def test_hoa_don_khong_VAT_van_kiem_duoc():
    kq = verify(_hoa_don(vat_rate=None, vat_amount=None, total=24_500_000))
    assert kq["ok"] is True, kq["issues"]
    assert kq["computed"]["vat_amount"] is None


# ---------------------------------------------------------------------------
# Lược đồ — đây là chỗ `InvoicePayload` bán lẻ không nhét vừa
# ---------------------------------------------------------------------------

def test_giu_duoc_thong_tin_nghiep_vu_van_tai():
    hd = _hoa_don()
    assert hd.origin == "Hà Nội" and hd.destination == "Đà Nẵng"
    assert hd.plate_number == "29H-123.45"
    assert hd.vehicle_type == "xe tải 5 tấn"


def test_phan_biet_cuoc_voi_phu_phi():
    """
    `InvoicePayload` chỉ có `items` chung, nên "2 chuyến × 12 triệu" và "1 lần bốc
    xếp 500k" trông giống nhau — không đối chiếu được với sổ chuyến.
    """
    hd = _hoa_don()
    assert [c.kind for c in hd.charges] == ["cước", "bốc xếp"]
    assert sum(c.amount for c in hd.charges if c.kind == "cước") == 24_000_000


def test_truong_chua_doc_duoc_la_None_khong_phai_0():
    hd = FreightInvoice(carrier_name="X")
    assert hd.total is None and hd.plate_number is None


def test_don_gia_am_bi_tu_choi():
    with pytest.raises(ValueError):
        FreightCharge(unit_price=-1)


def test_vat_ngoai_khoang_bi_tu_choi():
    with pytest.raises(ValueError):
        FreightInvoice(vat_rate=150.0)


def test_json_schema_dung_duoc_cho_guided_decoding():
    s = json_schema()
    assert s["type"] == "object"
    assert "charges" in s["properties"]
    assert "total" in s["properties"]
