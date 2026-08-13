"""
Kiểm thử src/core/receivables.py.

Số liệu dùng ở đây lấy từ hồ sơ thật của Hoàng Phát (11/08/2026): phải thu
3,96 tỷ · phải trả 1,41 tỷ · tồn kho 2,87 tỷ · giá vốn xuất 7,83 tỷ trong 223
ngày. Ba con số đó nói một điều mà không báo cáo kế toán nào nói thẳng: tiền
nằm ở khách nhiều hơn nằm ở kho.
"""

from __future__ import annotations

import pytest

from src.core.partner_import import KHACH_HANG, NHA_CUNG_CAP, Partner
from src.core.receivables import audit_partners, suc_khoe_von_luu_dong


def kh(code, name="CÔNG TY TNHH THỬ", so_du=0.0, mst="0109527605") -> Partner:
    return Partner(code=code, name=name, balance=so_du, tax_id=mst, role=KHACH_HANG)


def ncc(code, name="CÔNG TY TNHH NCC", so_du=0.0, mst="2900325124") -> Partner:
    return Partner(code=code, name=name, balance=so_du, tax_id=mst, role=NHA_CUNG_CAP)


def kinds(kq) -> list[str]:
    return [f["kind"] for f in kq["findings"]]


def lay(kq, kind) -> list[dict]:
    return [f for f in kq["findings"] if f["kind"] == kind]


# ---------------------------------------------------------------------------
# Số dư ngược dấu
# ---------------------------------------------------------------------------

def test_phai_thu_am_duoc_bao_va_quy_ra_tien():
    kq = audit_partners([kh("KH00053", "TRẦN ĐÌNH QUÂN", -1_296_000, "")])
    f = lay(kq, "negative_receivable")[0]
    assert f["money_impact"] == 1_296_000
    assert f["code"] == "KH00053"


def test_phai_tra_am_duoc_bao_rieng_khong_gop_voi_phai_thu():
    kq = audit_partners([], [ncc("NCC00003", "HATEK", -3_000)])
    assert kinds(kq) == ["negative_payable"]
    assert lay(kq, "negative_payable")[0]["money_impact"] == 3_000


def test_so_du_duong_khong_bi_bao():
    kq = audit_partners([kh("A", so_du=1_000_000)])
    assert lay(kq, "negative_receivable") == []


def test_so_du_None_khong_bi_coi_la_am():
    """`None` là CHƯA BIẾT. Coi nó là 0 hay số âm đều là bịa dữ liệu."""
    p = Partner(code="A", name="CÔNG TY A", balance=None, tax_id="0109527605")
    assert lay(audit_partners([p]), "negative_receivable") == []


# ---------------------------------------------------------------------------
# Tập trung khách hàng — rủi ro lớn nhất của doanh nghiệp nhỏ
# ---------------------------------------------------------------------------

def test_mot_khach_chiem_qua_mot_phan_nam_thi_bao():
    ds = [kh("A", so_du=300), kh("B", so_du=100), kh("C", so_du=100),
          kh("D", so_du=100), kh("E", so_du=100)]
    f = lay(audit_partners(ds), "customer_concentration")
    assert any(x["code"] == "A" for x in f)
    assert any("43%" in x["title"] for x in f)      # 300/700 = 42,86% -> làm tròn 43


def test_ba_khach_chiem_qua_mot_nua_thi_bao():
    ds = [kh(c, so_du=v) for c, v in
          [("A", 300), ("B", 200), ("C", 100), ("D", 100), ("E", 100),
           ("F", 100), ("G", 100)]]
    tieu_de = [x["title"] for x in lay(audit_partners(ds), "customer_concentration")]
    assert any("Ba khách lớn nhất" in t for t in tieu_de)


def test_phai_thu_deu_thi_khong_bao_tap_trung():
    ds = [kh(f"K{i}", so_du=100) for i in range(10)]
    assert lay(audit_partners(ds), "customer_concentration") == []


def test_so_du_am_khong_lam_meo_ty_le_tap_trung():
    """
    Mẫu số phải là tổng các số dư DƯƠNG.

    Cộng cả số âm vào sẽ làm mẫu số teo lại (1.200 thành 200) và đẩy tỷ lệ lên
    150% — một con số vô nghĩa nhưng vẫn qua được mọi ngưỡng, nên sẽ không ai
    phát hiện ra là sai.
    """
    ds = [kh("A", so_du=300), kh("B", so_du=300), kh("C", so_du=300),
          kh("D", so_du=300), kh("E", so_du=-1_000_000)]
    mot = next(x for x in lay(audit_partners(ds), "customer_concentration")
               if x["code"] == "A")
    assert mot["evidence"]["tổng_phải_thu"] == 1200
    assert mot["evidence"]["tỷ_lệ_%"] == 25.0


def test_khong_co_khach_nao_thi_khong_no_ra_loi():
    kq = audit_partners([])
    assert kq["findings"] == []
    assert kq["summary"]["tổng_phải_thu"] == 0


# ---------------------------------------------------------------------------
# Vừa là khách vừa là nhà cung cấp
# ---------------------------------------------------------------------------

def test_ca_hai_chieu_cung_duong_thi_de_xuat_bu_tru():
    a = kh("KH00021", "CÔNG TY PHƯƠNG", 50_000_000, "0106172584")
    b = ncc("KH00021", "CÔNG TY PHƯƠNG", 30_000_000, "0106172584")
    f = lay(audit_partners([a], [b]), "partner_both_roles")[0]
    assert f["money_impact"] == 30_000_000, "bù trừ được bằng số NHỎ HƠN"
    assert f["evidence"]["bù_trừ_được"] == 30_000_000


def test_khach_am_ma_cung_la_ncc_thi_bao_muc_cao():
    """
    Trường hợp thật KH00021: số dư phải thu −28.962.041 trong khi cùng đối tác
    đó cũng là nhà cung cấp. Dấu hiệu nghiệp vụ mua bị ghi vào tài khoản phải thu.
    """
    a = kh("KH00021", "CÔNG TY PHƯƠNG", -28_962_041, "0106172584")
    b = ncc("KH00021", "CÔNG TY PHƯƠNG", 0, "0106172584")
    f = lay(audit_partners([a], [b]), "partner_both_roles")[0]
    assert f["severity"] == "cao"
    assert f["money_impact"] == 28_962_041


def test_ca_hai_chieu_bang_khong_thi_khong_bao():
    a = kh("KH00022", "YÊN HƯNG", 0, "0101912588")
    b = ncc("KH00022", "YÊN HƯNG", 0, "0101912588")
    assert lay(audit_partners([a], [b]), "partner_both_roles") == []


def test_gop_theo_ma_so_thue_ke_ca_khi_ma_doi_tac_khac_nhau():
    a = kh("KH00099", "CÔNG TY X", 10_000_000, "0106172584")
    b = ncc("NCC00099", "CÔNG TY X", 4_000_000, "0106172584")
    assert len(lay(audit_partners([a], [b]), "partner_both_roles")) == 1


def test_khong_co_mst_thi_gop_theo_ma_doi_tac():
    a = kh("X1", "Ông A", 10_000, "")
    b = ncc("X1", "Ông A", 4_000, "")
    assert len(lay(audit_partners([a], [b]), "partner_both_roles")) == 1


# ---------------------------------------------------------------------------
# Mã số thuế
# ---------------------------------------------------------------------------

def test_mst_sai_so_kiem_tra_bao_muc_cao():
    kq = audit_partners([kh("A", "CÔNG TY A", 0, "0109527604")])
    f = lay(kq, "invalid_tax_id")[0]
    assert f["severity"] == "cao"
    assert "khấu trừ" in f["suggestion"]


def test_mst_sai_khuon_bao_muc_thap_hon_sai_so_kiem_tra():
    """Sai khuôn có thể chỉ là gõ thiếu; sai số kiểm tra thì chắc chắn sai."""
    khuon = lay(audit_partners([kh("A", "CÔNG TY A", 0, "12345")]), "invalid_tax_id")[0]
    kiem = lay(audit_partners([kh("B", "CÔNG TY B", 0, "0109527604")]), "invalid_tax_id")[0]
    assert khuon["severity"] == "trung bình"
    assert kiem["severity"] == "cao"


def test_so_dinh_danh_ca_nhan_12_so_KHONG_bi_bao_la_sai():
    """
    Năm khách thật của Hoàng Phát dùng số định danh cá nhân. Báo chúng là "mã số
    thuế không đúng khuôn" là năm phát hiện sai trên một báo cáo có hai mươi —
    đủ để người đọc thôi tin phần còn lại.
    """
    ds = [kh("KH00071", "HỘ KINH DOANH NGÔ VĂN NGÂN 1983", 5_000_000, "001083006805"),
          kh("KH00086", "HÀ ĐƯƠNG", 1_000_000, "034052005581")]
    assert lay(audit_partners(ds), "invalid_tax_id") == []


def test_hai_khach_dung_chung_mot_so_dinh_danh_thi_van_bao_trung():
    ds = [kh("A", "NGÔ VĂN NGÂN", 1_000, "001083006805"),
          kh("B", "NGO VAN NGAN", 2_000, "001083006805")]
    assert len(lay(audit_partners(ds), "duplicate_partner")) == 1


def test_ca_nhan_khong_co_mst_thi_KHONG_bao():
    """32/104 khách của Hoàng Phát là khách lẻ. Báo hết thì báo cáo thành rác."""
    kq = audit_partners([kh("KH00023", "Nguyễn Trung Kiên", 500_000, "")])
    assert lay(kq, "missing_tax_id") == []
    assert lay(kq, "invalid_tax_id") == []


def test_to_chuc_khong_co_mst_thi_BAO():
    kq = audit_partners([kh("A", "CÔNG TY TNHH KHÔNG MST", 500_000, "")])
    assert len(lay(kq, "missing_tax_id")) == 1


def test_mot_mst_dung_cho_hai_ma_khach_thi_bao_trung():
    ds = [kh("KH00010", "CÔNG TY A", 5_000_000, "0109527605"),
          kh("KH00088", "CTY A", 3_000_000, "0109527605")]
    f = lay(audit_partners(ds), "duplicate_partner")[0]
    assert f["evidence"]["các_mã"] == ["KH00010", "KH00088"]
    assert f["evidence"]["tổng_số_dư"] == 8_000_000
    assert "chia nhỏ" in f["suggestion"]


def test_chi_nhanh_va_cong_ty_me_KHONG_bi_coi_la_trung():
    """13 số và 10 số là hai pháp nhân khác nhau khi xuất hoá đơn."""
    ds = [kh("A", "CÔNG TY MẸ", 0, "0111322034"),
          kh("B", "CHI NHÁNH", 0, "0111322034-001")]
    assert lay(audit_partners(ds), "duplicate_partner") == []


# ---------------------------------------------------------------------------
# Phải thu quy ra số ngày
# ---------------------------------------------------------------------------

def test_phai_thu_qua_nhieu_ngay_thi_bao():
    gia_von_ngay = 7_833_688_922 / 223          # 35.128.650 đ/ngày, số thật
    kq = audit_partners([kh("A", so_du=3_962_266_920)],
                        gia_von_moi_ngay=gia_von_ngay)
    f = lay(kq, "receivable_days_high")[0]
    assert f["evidence"]["số_ngày"] == pytest.approx(112.8, abs=0.2)
    assert kq["summary"]["phải_thu_quy_ra_ngày"] == pytest.approx(112.8, abs=0.2)


def test_khong_co_gia_von_thi_bo_qua_chu_khong_doan():
    kq = audit_partners([kh("A", so_du=3_962_266_920)])
    assert lay(kq, "receivable_days_high") == []
    assert "phải_thu_quy_ra_ngày" not in kq["summary"]


def test_gia_von_bang_0_khong_lam_chia_cho_khong():
    kq = audit_partners([kh("A", so_du=1_000)], gia_von_moi_ngay=0)
    assert lay(kq, "receivable_days_high") == []


def test_duoi_nguong_thi_khong_bao():
    kq = audit_partners([kh("A", so_du=100)], gia_von_moi_ngay=100)   # 1 ngày
    assert lay(kq, "receivable_days_high") == []


# ---------------------------------------------------------------------------
# Nói thẳng cái KHÔNG làm được
# ---------------------------------------------------------------------------

def test_tom_tat_noi_ro_khong_tinh_duoc_tuoi_no():
    """
    Số dư không kèm ngày hoá đơn. Nếu không viết ra, người đọc sẽ tưởng phần
    phân tích công nợ này đã bao gồm nợ quá hạn.
    """
    kq = audit_partners([kh("A", so_du=1)])
    ghi_chu = " ".join(kq["summary"]["không_phân_tích_được"])
    assert "Tuổi nợ" in ghi_chu and "Sổ chi tiết công nợ" in ghi_chu


# ---------------------------------------------------------------------------
# Vốn lưu động
# ---------------------------------------------------------------------------

def test_von_luu_dong_ket_tren_so_that():
    sk = suc_khoe_von_luu_dong(
        phai_thu=3_962_266_920, phai_tra=1_410_141_691, ton_kho=2_874_073_721,
        gia_von_moi_ngay=7_833_688_922 / 223,
    )
    assert sk["vốn_lưu_động_kẹt"] == 3_962_266_920 + 2_874_073_721 - 1_410_141_691
    assert sk["phải_thu_ngày"] == pytest.approx(112.8, abs=0.2)
    assert sk["tồn_kho_ngày"] == pytest.approx(81.8, abs=0.2)
    assert sk["chu_kỳ_tiền_mặt_ngày"] == pytest.approx(154.5, abs=0.3)


def test_khong_co_gia_von_thi_chi_tra_ba_so_tuyet_doi():
    sk = suc_khoe_von_luu_dong(phai_thu=100, phai_tra=30, ton_kho=50)
    assert sk["vốn_lưu_động_kẹt"] == 120
    assert "phải_thu_ngày" not in sk


def test_phai_tra_lon_hon_thi_von_ket_am():
    """Được nhà cung cấp cho nợ nhiều hơn phần mình bị chiếm dụng — điều tốt."""
    sk = suc_khoe_von_luu_dong(phai_thu=100, phai_tra=500, ton_kho=50)
    assert sk["vốn_lưu_động_kẹt"] == -350


# ---------------------------------------------------------------------------
# Hình dạng
# ---------------------------------------------------------------------------

def test_moi_phat_hien_cung_hinh_dang_voi_cac_module_khac():
    ds = [kh("A", "CÔNG TY A", -5_000, "0109527604"), kh("B", so_du=900_000)]
    for f in audit_partners(ds, [ncc("N", so_du=-100)])["findings"]:
        assert set(f) == {"kind", "severity", "code", "product", "unit",
                          "title", "evidence", "money_impact", "suggestion"}
        assert f["severity"] in ("cao", "trung bình", "thấp")


def test_nang_truoc_nhieu_tien_truoc():
    ds = [kh("NHO", "CÔNG TY NHỎ", -1_000), kh("A", so_du=900_000),
          kh("B", so_du=50_000), kh("C", so_du=50_000)]
    fs = audit_partners(ds)["findings"]
    assert fs[0]["severity"] == "cao"
