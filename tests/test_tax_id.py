"""
Kiểm thử src/core/tax_id.py.

Giá trị mong đợi ở đây tính TAY từ công thức, và đối chiếu với mã số thuế thật
trong hồ sơ khách hàng — không lấy từ chính hàm đang kiểm.
"""

from __future__ import annotations

import pytest

from src.core.tax_id import chuan_hoa, kiem_ma_so_thue, ma_chu_quan

# Mã số thuế thật, lấy từ danh sách khách hàng / nhà cung cấp của Hoàng Phát.
THAT = [
    "0109527605",   # chính Hoàng Phát
    "2900325124",
    "0106733254",
    "0100100174",
    "0101912588",
    "0106172584",
    "0105307197",
]


def test_tinh_tay_so_kiem_tra_cua_hoang_phat():
    """
    0109527605 — chín chữ số đầu là 0,1,0,9,5,2,7,6,0.

        0·31 + 1·29 + 0·23 + 9·19 + 5·17 + 2·13 + 7·7 + 6·5 + 0·3
      =   0 +  29 +   0 + 171 +  85 +  26 +  49 +  30 +   0  = 390
        390 mod 11 = 5   ->   số kiểm tra = 10 − 5 = 5

    Chữ số cuối của mã thật đúng là 5.
    """
    kq = kiem_ma_so_thue("0109527605")
    assert kq.hop_le is True
    assert kq.chuan_hoa == "0109527605"
    assert not kq.la_chi_nhanh


@pytest.mark.parametrize("mst", THAT)
def test_moi_ma_so_thue_that_deu_qua(mst):
    assert kiem_ma_so_thue(mst).hop_le is True


def test_doi_mot_chu_so_thi_bat_duoc():
    """Đây là toàn bộ công dụng của số kiểm tra: gõ sai một số là lộ ngay."""
    assert kiem_ma_so_thue("0109527604").hop_le is False
    assert kiem_ma_so_thue("0119527605").hop_le is False


def test_doi_cho_hai_chu_so_lien_ke_cung_bat_duoc():
    """Trọng số khác nhau cho từng vị trí nên hoán vị cũng đổi tổng."""
    assert kiem_ma_so_thue("0190527605").hop_le is False


def test_ly_do_noi_ro_chu_so_dung_phai_la_bao_nhieu():
    kq = kiem_ma_so_thue("0109527604")
    assert "4" in kq.ly_do and "5" in kq.ly_do


# ---------------------------------------------------------------------------
# Chi nhánh 13 số
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mst", [
    "0111322034-001",       # Chi nhánh Đăng kiểm 29-06V
    "0302712571-001",       # Chi nhánh Mắt Bão
    "0105402531-002",       # Bảo hiểm PVI Đông Đô
    "0102721191-068",       # Golden Gate chi nhánh miền Bắc
    "0106536425-003",       # Thái Minh Group Hải Phòng
])
def test_ma_chi_nhanh_that_deu_qua(mst):
    kq = kiem_ma_so_thue(mst)
    assert kq.hop_le is True
    assert kq.la_chi_nhanh


def test_chap_nhan_13_so_lien_khong_gach():
    assert kiem_ma_so_thue("0111322034001").hop_le is True
    assert kiem_ma_so_thue("0111322034001").chuan_hoa == "0111322034-001"


def test_chi_nhanh_000_khong_hop_le():
    assert kiem_ma_so_thue("0111322034-000").hop_le is False


def test_chi_nhanh_sai_thi_phan_10_so_van_phai_dung():
    assert kiem_ma_so_thue("0111322035-001").hop_le is False


# ---------------------------------------------------------------------------
# 'Chưa biết' KHÁC 'sai'
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw", ["", "   ", None])
def test_o_rong_tra_None_chu_khong_tra_False(raw):
    """
    Danh sách khách hàng có 32 khách lẻ không có mã số thuế. Coi đó là 'sai'
    thì báo cáo sẽ buộc tội 32 dòng hoàn toàn bình thường.
    """
    assert kiem_ma_so_thue(raw).hop_le is None


@pytest.mark.parametrize("raw", ["123", "abcdefghij", "01095276050", "0109-527605"])
def test_khuon_la_thi_tra_None_kem_ly_do(raw):
    kq = kiem_ma_so_thue(raw)
    assert kq.hop_le is None
    assert kq.ly_do
    assert not kq.la_dinh_danh_ca_nhan


# ---------------------------------------------------------------------------
# Số định danh cá nhân 12 số — Thông tư 86/2024/TT-BTC
# ---------------------------------------------------------------------------

# Năm mã có thật trong danh sách khách hàng của Hoàng Phát: hộ kinh doanh và
# cá nhân. Bản đầu của module báo cả năm là "không đúng khuôn".
DINH_DANH_THAT = [
    "001083006805",   # HỘ KINH DOANH NGÔ VĂN NGÂN 1983
    "034052005581",   # HÀ ĐƯƠNG
    "010083007998",   # HỘ KINH DOANH NGUYỄN VĂN THÀNH 1983
    "001089049240",   # HỘ KINH DOANH HỒNG QUANG MOTOR
    "008088004475",   # VŨ XUÂN BẰNG
]


@pytest.mark.parametrize("so", DINH_DANH_THAT)
def test_so_dinh_danh_12_so_KHONG_bi_coi_la_sai_khuon(so):
    """
    Từ 01/7/2025, cá nhân và hộ kinh doanh dùng số định danh cá nhân thay mã số
    thuế. Coi chúng là mã số thuế hỏng là buộc tội năm dòng hoàn toàn hợp lệ —
    và là kiểu lỗi sẽ xuất hiện ở MỌI khách hàng bán lẻ, không riêng Hoàng Phát.
    """
    kq = kiem_ma_so_thue(so)
    assert kq.la_dinh_danh_ca_nhan
    assert kq.chuan_hoa == so
    assert "86/2024" in kq.ly_do


@pytest.mark.parametrize("so", DINH_DANH_THAT)
def test_so_dinh_danh_KHONG_khang_dinh_la_hop_le(so):
    """
    Số định danh không có chữ số kiểm tra như mã số thuế. Đúng khuôn nhưng
    không đối chiếu được — nói 'hợp lệ' là hứa một thứ ta không kiểm được.
    """
    assert kiem_ma_so_thue(so).hop_le is None
    assert not bool(kiem_ma_so_thue(so))


def test_khong_nham_dinh_danh_voi_ma_so_thue_chi_nhanh():
    """12 số là định danh cá nhân; 13 số là chi nhánh. Lệch một số là hai thứ khác nhau."""
    assert kiem_ma_so_thue("001083006805").la_dinh_danh_ca_nhan
    assert not kiem_ma_so_thue("0111322034-001").la_dinh_danh_ca_nhan
    assert kiem_ma_so_thue("0111322034001").la_chi_nhanh


def test_ma_chu_quan_giu_nguyen_12_so_cua_dinh_danh():
    """Cắt 10 số đầu sẽ tạo khoá vô nghĩa và có thể gom nhầm hai người."""
    assert ma_chu_quan("001083006805") == "001083006805"


def test_bool_cua_ket_qua_chi_True_khi_thuc_su_hop_le():
    assert bool(kiem_ma_so_thue("0109527605"))
    assert not bool(kiem_ma_so_thue("0109527604"))
    assert not bool(kiem_ma_so_thue(""))


# ---------------------------------------------------------------------------
# Chuẩn hoá
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,mong", [
    (" 0109527605 ", "0109527605"),
    ("0109.527.605", "0109527605"),
    ("0111322034 001", "0111322034001"),
])
def test_chuan_hoa_bo_khoang_trang_va_dau_cham(raw, mong):
    assert chuan_hoa(raw) == mong


def test_ma_chu_quan_gom_chi_nhanh_ve_phap_nhan_me():
    assert ma_chu_quan("0111322034-001") == "0111322034"
    assert ma_chu_quan("0109527605") == "0109527605"
    assert ma_chu_quan("sai") == ""


def test_excel_nuot_so_0_dau_thi_bu_lai():
    """
    Ô định dạng kiểu SỐ làm '0109527605' về tay ta thành 109527605. Không bù
    lại thì mọi mã số thuế bắt đầu bằng 0 — phần lớn mã ở Việt Nam — đều bị báo
    'sai khuôn'.
    """
    assert chuan_hoa(109527605) == "0109527605"
    assert kiem_ma_so_thue(109527605).hop_le is True
    assert chuan_hoa(111322034001) == "0111322034001"
    assert kiem_ma_so_thue(111322034001).hop_le is True


def test_khong_bu_so_0_cho_CHUOI_chin_ky_tu():
    """
    Chuỗi 9 ký tự là dữ liệu sai, không phải bị Excel cắt. Bù số 0 ở đây sẽ
    biến rác thành mã hợp lệ một cách ngẫu nhiên.
    """
    assert chuan_hoa("109527605") == "109527605"
    assert kiem_ma_so_thue("109527605").hop_le is None


def test_so_nguyen_du_10_chu_so_thi_giu_nguyen():
    assert chuan_hoa(2900325124) == "2900325124"
    assert kiem_ma_so_thue(2900325124).hop_le is True
