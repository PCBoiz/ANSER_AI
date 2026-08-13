"""
Kiểm thử src/core/period_diff.py — phát hiện sửa hồi tố.

Các con số trong file này lấy nguyên từ hai bản xuất thật của Hoàng Phát
(01/01/2026→24/07/2026 và 01/01/2026→11/08/2026). Chúng đối chiếu được bằng
tay với ô gốc trong hai file .xlsx.

Phần quan trọng nhất KHÔNG phải là "bắt được lỗi" mà là "im lặng đúng chỗ":
kỳ dài hơn thì số tăng lên là bình thường, và giá vốn bình quân được tính lại
cũng là bình thường. Một công cụ báo động cả hai thứ đó sẽ bị tắt sau một tuần.
"""

from __future__ import annotations

from src.core.inventory import InventoryLine
from src.core.inventory_import import ParseResult
from src.core.period_diff import doi_chieu_hai_lan_xuat


def _ky(lines, den, tu="2026-01-01", kho="KHO HÀNG HÓA") -> ParseResult:
    return ParseResult(lines=lines, warehouse=kho, period_start=tu, period_end=den)


def _dong(code, **kw) -> InventoryLine:
    goc = dict(name="Dầu nhớt thử", unit="Lít", opening_qty=0.0, opening_value=0.0,
               in_qty=0.0, in_value=0.0, out_qty=0.0, out_value=0.0,
               closing_qty=0.0, closing_value=0.0)
    goc.update(kw)
    return InventoryLine(code=code, **goc)


def _kinds(kq) -> list[str]:
    return [f["kind"] for f in kq["findings"]]


# ---------------------------------------------------------------------------
# Trường hợp thật: 108 lít chạy từ mã này sang mã kia
# ---------------------------------------------------------------------------

def _hai_ky_that():
    truoc = _ky([
        _dong("VT00059", opening_qty=87, opening_value=5016459,
              in_qty=4400, in_value=254755000,
              out_qty=4508, out_value=260989815,
              closing_qty=-21, closing_value=-1218356),
        _dong("VT00039", opening_qty=18, opening_value=1148000,
              in_qty=288, in_value=14924000,
              out_qty=306, out_value=16072000,
              closing_qty=0, closing_value=0),
    ], den="2026-07-24")
    sau = _ky([
        _dong("VT00059", opening_qty=87, opening_value=5016459,
              in_qty=4400, in_value=254755000,
              out_qty=4400, out_value=254723980,
              closing_qty=87, closing_value=5047479),
        _dong("VT00039", opening_qty=18, opening_value=1148000,
              in_qty=288, in_value=14924000,
              out_qty=414, out_value=16072000,
              closing_qty=-108, closing_value=0),
    ], den="2026-08-11")
    return truoc, sau


def test_bat_duoc_so_xuat_luy_ke_GIAM():
    """
    Kỳ dài hơn mà xuất luỹ kế giảm 4508 → 4400 là điều thời gian không cho phép.
    Đây là loại lỗi mà mọi phép kiểm trên MỘT bản báo cáo đều mù.
    """
    kq = doi_chieu_hai_lan_xuat(*_hai_ky_that())
    giam = [f for f in kq["findings"] if f["kind"] == "history_decreased"]
    assert len(giam) == 1
    f = giam[0]
    assert f["code"] == "VT00059"
    assert f["severity"] == "cao"
    assert f["evidence"]["chênh"] == -108.0
    assert f["money_impact"] == 260989815 - 254723980 == 6265835


def test_chi_dung_ma_nhan_dung_bang_luong_bi_mat():
    """Gợi ý điều tra chỉ có giá trị khi khớp ĐÚNG BẰNG, không xấp xỉ."""
    kq = doi_chieu_hai_lan_xuat(*_hai_ky_that())
    f = next(f for f in kq["findings"] if f["kind"] == "history_decreased")
    assert f["evidence"]["mã_tăng_đúng_bằng_lượng_này"] == ["VT00039"]
    assert "VT00039" in f["suggestion"]


def test_khong_ghep_bua_khi_khong_co_ma_nao_khop():
    truoc, sau = _hai_ky_that()
    sau.lines[1].out_qty = 400          # tăng 94, không phải 108
    kq = doi_chieu_hai_lan_xuat(truoc, sau)
    f = next(f for f in kq["findings"] if f["kind"] == "history_decreased")
    assert "mã_tăng_đúng_bằng_lượng_này" not in f["evidence"]


def test_tom_tat_noi_ro_co_sua_hoi_to():
    kq = doi_chieu_hai_lan_xuat(*_hai_ky_that())
    assert kq["summary"]["có_sửa_hồi_tố"] is True
    assert kq["summary"]["số_mã_so_được"] == 2


# ---------------------------------------------------------------------------
# Im lặng đúng chỗ
# ---------------------------------------------------------------------------

def test_so_voi_chinh_no_thi_khong_co_phat_hien_nao():
    _, sau = _hai_ky_that()
    assert doi_chieu_hai_lan_xuat(sau, sau)["findings"] == []


def test_ky_dai_hon_ma_so_TANG_la_binh_thuong():
    truoc = _ky([_dong("A", in_qty=100, in_value=1000, out_qty=50, out_value=500)],
                den="2026-07-24")
    sau = _ky([_dong("A", in_qty=180, in_value=1800, out_qty=90, out_value=900)],
              den="2026-08-11")
    assert doi_chieu_hai_lan_xuat(truoc, sau)["findings"] == []


def test_gia_tri_XUAT_doi_ma_so_luong_giu_nguyen_thi_KHONG_bao():
    """
    Giá vốn bình quân cuối kỳ được tính lại trên kỳ dài hơn, nên giá trị xuất
    đổi trong khi số lượng xuất y nguyên là hệ quả bình thường của phương pháp
    tính giá. Bắt lỗi ở đây sẽ báo động trên gần như mọi mã hàng.
    """
    truoc = _ky([_dong("A", out_qty=100, out_value=6_000_000)], den="2026-07-24")
    sau = _ky([_dong("A", out_qty=100, out_value=6_350_000)], den="2026-08-11")
    assert doi_chieu_hai_lan_xuat(truoc, sau)["findings"] == []


def test_ma_moi_khong_co_ton_dau_ky_thi_khong_bao():
    """VT00125, VT00126 là hàng mới nhập lần đầu — không phải bất thường."""
    truoc = _ky([_dong("A")], den="2026-07-24")
    sau = _ky([_dong("A"), _dong("MOI", in_qty=4, in_value=7_360_000,
                                 closing_qty=4, closing_value=7_360_000)],
              den="2026-08-11")
    assert doi_chieu_hai_lan_xuat(truoc, sau)["findings"] == []


# ---------------------------------------------------------------------------
# Giá trị NHẬP đổi — không có cách giải thích lành nào
# ---------------------------------------------------------------------------

def test_gia_tri_NHAP_doi_ma_so_luong_giu_nguyen_thi_BAO():
    truoc = _ky([_dong("A", in_qty=100, in_value=6_000_000)], den="2026-07-24")
    sau = _ky([_dong("A", in_qty=100, in_value=6_500_000)], den="2026-08-11")
    kq = doi_chieu_hai_lan_xuat(truoc, sau)
    assert _kinds(kq) == ["purchase_value_changed"]
    assert kq["findings"][0]["money_impact"] == 500_000


# ---------------------------------------------------------------------------
# Tồn đầu kỳ — nặng nhất, vì kỳ trước đã nộp báo cáo
# ---------------------------------------------------------------------------

def test_ton_dau_ky_doi_thi_bao_muc_cao():
    truoc = _ky([_dong("A", opening_qty=100, opening_value=6_000_000)], den="2026-07-24")
    sau = _ky([_dong("A", opening_qty=90, opening_value=5_400_000)], den="2026-08-11")
    kq = doi_chieu_hai_lan_xuat(truoc, sau)
    assert _kinds(kq).count("opening_changed") == 2      # số lượng và giá trị
    assert all(f["severity"] == "cao" for f in kq["findings"])


def test_ma_moi_ma_da_co_ton_dau_ky_thi_bao():
    truoc = _ky([_dong("A")], den="2026-07-24")
    sau = _ky([_dong("A"), _dong("LA", opening_qty=50, opening_value=3_000_000)],
              den="2026-08-11")
    kq = doi_chieu_hai_lan_xuat(truoc, sau)
    assert _kinds(kq) == ["opening_appeared"]
    assert kq["findings"][0]["money_impact"] == 3_000_000


def test_ma_bien_mat_thi_bao():
    truoc = _ky([_dong("A", closing_qty=10, closing_value=600_000), _dong("B")],
                den="2026-07-24")
    sau = _ky([_dong("B")], den="2026-08-11")
    kq = doi_chieu_hai_lan_xuat(truoc, sau)
    assert _kinds(kq) == ["line_disappeared"]
    assert kq["findings"][0]["code"] == "A"


# ---------------------------------------------------------------------------
# Từ chối so khi hai bản không so được
# ---------------------------------------------------------------------------

def test_khac_kho_thi_tu_choi_so():
    a = _ky([_dong("A")], den="2026-07-24", kho="KHO KHUYẾN MẠI")
    b = _ky([_dong("A", out_qty=-999)], den="2026-08-11", kho="KHO HÀNG HÓA")
    kq = doi_chieu_hai_lan_xuat(a, b)
    assert kq["findings"] == []
    assert any("khác kho" in w for w in kq["warnings"])
    assert kq["summary"]["so_sánh_được"] is False


def test_khac_ngay_bat_dau_thi_tu_choi_so():
    a = _ky([_dong("A", out_qty=500)], tu="2026-01-01", den="2026-07-24")
    b = _ky([_dong("A", out_qty=100)], tu="2026-04-01", den="2026-08-11")
    kq = doi_chieu_hai_lan_xuat(a, b)
    assert kq["findings"] == []
    assert any("ngày bắt đầu" in w for w in kq["warnings"])


def test_truyen_nham_thu_tu_thi_noi_ro_la_nham_thu_tu():
    truoc, sau = _hai_ky_that()
    kq = doi_chieu_hai_lan_xuat(sau, truoc)
    assert kq["findings"] == []
    assert any("nhầm thứ tự" in w for w in kq["warnings"])


def test_thieu_ngay_bat_dau_thi_tu_choi_so():
    a = _ky([_dong("A")], den="2026-07-24", tu=None)
    b = _ky([_dong("A")], den="2026-08-11")
    assert any("Thiếu ngày bắt đầu" in w for w in doi_chieu_hai_lan_xuat(a, b)["warnings"])


# ---------------------------------------------------------------------------
# Hình dạng kết quả
# ---------------------------------------------------------------------------

def test_phat_hien_cung_hinh_dang_voi_audit_inventory():
    kq = doi_chieu_hai_lan_xuat(*_hai_ky_that())
    for f in kq["findings"]:
        assert set(f) == {"kind", "severity", "code", "product", "unit",
                          "title", "evidence", "money_impact", "suggestion"}
        assert f["severity"] in ("cao", "trung bình", "thấp")


def test_nang_truoc_nhieu_tien_truoc():
    truoc = _ky([
        _dong("NHE", in_qty=10, in_value=1_000),
        _dong("NANG", opening_qty=100, opening_value=9_000_000),
    ], den="2026-07-24")
    sau = _ky([
        _dong("NHE", in_qty=10, in_value=1_500),
        _dong("NANG", opening_qty=50, opening_value=4_000_000),
    ], den="2026-08-11")
    kinds = _kinds(doi_chieu_hai_lan_xuat(truoc, sau))
    assert kinds[0] == "opening_changed"
    assert kinds[-1] == "purchase_value_changed"
