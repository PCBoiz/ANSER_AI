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


# ---------------------------------------------------------------------------
# Kho cho phép giá trị 0 — chống báo oan
# ---------------------------------------------------------------------------

def test_kho_cho_phep_gia_tri_0_thi_thoi_bao_oan(ket_qua):
    """
    Chạy trên bản xuất MISA THẬT: kho KHUYẾN MẠI có 29/38 dòng bị gắn cờ "có số
    lượng nhưng không ghi nhận giá trị". Với kho mà giá trị 0 là trạng thái BÌNH
    THƯỜNG (hàng nhà cung cấp tặng kèm), đó là tiếng ồn, không phải phát hiện.

    Bộ soi kêu ca gần như mọi dòng thì người dùng tắt nó đi — và mất luôn những
    lỗi thật nằm cùng bảng.
    """
    thuong = audit_inventory(ket_qua.lines, period_start="2026-01-01",
                             period_end="2026-06-30")
    kho_km = audit_inventory(ket_qua.lines, period_start="2026-01-01",
                             period_end="2026-06-30", allow_zero_value=True)

    def loai(kq):
        return {f["kind"] for f in kq["findings"]}

    assert "zero_valued_stock" in loai(thuong)
    assert "zero_valued_stock" not in loai(kho_km)


def test_tat_gia_tri_0_KHONG_lam_mat_cac_phep_kiem_khac(ket_qua):
    """
    Kho khuyến mại được phép không có giá vốn, KHÔNG được phép sai số học.
    Chính kho đó trong dữ liệu thật có một ca tồn âm −115,2 lít.
    """
    thuong = audit_inventory(ket_qua.lines, period_start="2026-01-01",
                             period_end="2026-06-30")
    kho_km = audit_inventory(ket_qua.lines, period_start="2026-01-01",
                             period_end="2026-06-30", allow_zero_value=True)

    con_lai = {f["kind"] for f in thuong["findings"]} - {"zero_valued_stock"}
    assert con_lai <= {f["kind"] for f in kho_km["findings"]}, (
        "tắt phép kiểm giá-trị-0 đã nuốt mất phép kiểm khác"
    )
    # Cụ thể: tồn âm và lệch cân đối vẫn phải còn.
    assert {"negative_stock", "balance_mismatch"} <= {f["kind"] for f in kho_km["findings"]}


def test_phuong_phap_tinh_gia_von_van_duoc_thu_thap(ket_qua):
    """
    Regression: bản đầu dùng `continue` để bỏ phép kiểm giá-trị-0, và bỏ luôn
    phần thu thập phương pháp tính giá vốn ngay dưới — `_check_method_consistency`
    mất dữ liệu mà không báo gì.
    """
    from src.core.inventory import _costing_method

    co_phuong_phap = any(_costing_method(d) for d in ket_qua.lines)
    if not co_phuong_phap:
        pytest.skip("bảng mẫu không có dòng nào suy ra được phương pháp tính giá vốn")

    kq = audit_inventory(ket_qua.lines, period_start="2026-01-01",
                         period_end="2026-06-30", allow_zero_value=True)
    assert kq["explain"]["costing_methods_detected"], (
        "mất dữ liệu phương pháp tính giá vốn khi tắt phép kiểm giá-trị-0"
    )
