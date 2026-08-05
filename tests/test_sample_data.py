"""
tests/test_sample_data.py — bảng tồn kho mẫu phải là ĐỀ BÀI CÓ ĐÁP ÁN.

Dữ liệu giả dựng đại thì bộ soi không tìm ra gì, và ta kết luận nhầm rằng nó
"chạy tốt". Nên bảng mẫu gieo lỗi có chủ đích, và test này đối chiếu hai chiều:

  - thiếu một lỗi gieo  -> bộ soi HỎNG
  - thừa một phát hiện  -> bộ soi BÁO OAN

Chiều thứ hai quan trọng ngang chiều thứ nhất. Một bộ soi gắn cờ 18/18 mã đã
từng xảy ra ở đây (30/07/2026, luật `cost_drift` cũ), và bộ soi kêu ca liên tục
thì người dùng tắt nó đi — tệ hơn là không có.

Test đi qua ĐÚNG đường thật: ghi .xlsx, đọc lại bằng bộ nạp, rồi soi.
"""

from __future__ import annotations

from io import BytesIO

import pytest

from sample_data.make_sample_data import DONG, LOI_GIEO, bang, ghi_xlsx
from src.core.inventory import audit_inventory
from src.core.inventory_import import parse_inventory_table

pytest.importorskip("openpyxl")


@pytest.fixture(scope="module")
def ket_qua():
    """Đọc bảng mẫu qua đúng bộ nạp mà Body dùng."""
    return parse_inventory_table(bang())


@pytest.fixture(scope="module")
def phat_hien(ket_qua):
    kq = audit_inventory(
        ket_qua.lines, warehouse="Kho Hà Nội",
        period_start="2026-01-01", period_end="2026-06-30",
    )
    theo_ma: dict[str, set[str]] = {}
    for f in kq["findings"]:
        theo_ma.setdefault(f.get("code") or "?", set()).add(f["kind"])
    return theo_ma


# ---------------------------------------------------------------------------
# Bộ nạp
# ---------------------------------------------------------------------------

def test_doc_duoc_moi_dong(ket_qua):
    assert ket_qua.ok, ket_qua.checks
    assert len(ket_qua.lines) == len(DONG)


def test_doc_duoc_so_dinh_dang_viet_nam(ket_qua):
    """
    "24.000.000" phải ra 24 triệu, không phải 24. Bản xuất thật đôi khi ra chuỗi
    thay vì số, và nhầm chỗ này thì mọi con số tiền nhỏ đi một triệu lần.
    """
    dong = next(d for d in ket_qua.lines if d.code == "DN-TL-46")
    assert dong.opening_value == pytest.approx(24_000_000)
    assert dong.opening_qty == pytest.approx(80)


def test_doc_dung_ten_kho_va_don_vi(ket_qua):
    dong = next(d for d in ket_qua.lines if d.code == "MO-EP2-15")
    assert dong.unit == "xô"
    assert "Mỡ bò" in dong.name


# ---------------------------------------------------------------------------
# Bộ soi — chiều thứ nhất: có tìm ra lỗi đã gieo không
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code,loi", sorted(LOI_GIEO.items()))
def test_tim_ra_loi_da_gieo(phat_hien, code, loi):
    thay = phat_hien.get(code, set())
    thieu = set(loi) - thay
    assert not thieu, f"{code}: không tìm ra {thieu} (chỉ thấy {thay or 'không gì'})"


# ---------------------------------------------------------------------------
# Bộ soi — chiều thứ hai: có báo oan không
# ---------------------------------------------------------------------------

def test_khong_bao_oan_dong_sach(phat_hien):
    """
    Dòng sạch là dòng bình thường của một nhà phân phối: nhập đều, bán đều, giá
    nhích nhẹ. Gắn cờ chúng là dạy người dùng bỏ qua cảnh báo.
    """
    sach = [d.code for d in DONG if not d.loi_gieo]
    oan = {code: phat_hien[code] for code in sach if phat_hien.get(code)}
    assert not oan, f"báo oan trên dòng sạch: {oan}"


def test_khong_gan_them_co_ngoai_du_kien(phat_hien):
    """Dòng gieo lỗi cũng không được nhận thêm cờ nào ngoài lỗi đã gieo."""
    thua = {}
    for code, loi in LOI_GIEO.items():
        du = phat_hien.get(code, set()) - set(loi)
        if du:
            thua[code] = du
    assert not thua, f"phát hiện ngoài dự kiến: {thua}"


# ---------------------------------------------------------------------------
# Ghi file thật
# ---------------------------------------------------------------------------

def test_ghi_va_doc_lai_duoc_xlsx(tmp_path):
    """File .xlsx thật phải đọc lại được y như ma trận ô — đó là thứ sẽ tải lên."""
    from src.core.inventory_import import load_xlsx_bytes

    path = ghi_xlsx(tmp_path / "ton_kho_mau.xlsx")
    kq = load_xlsx_bytes(BytesIO(path.read_bytes()).getvalue())
    assert kq.ok, kq.checks
    assert {d.code for d in kq.lines} == {d.code for d in DONG}
