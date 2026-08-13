"""
Kiểm thử src/core/vat_catalog.py — bảng tra thuế suất GTGT 8% / 10%.

ĐÂY LÀ FILE TEST CÓ RỦI RO PHÁP LÝ CAO NHẤT TRONG DỰ ÁN
-------------------------------------------------------
Bảng tra sai không làm chương trình đổ; nó làm doanh nghiệp xuất hoá đơn sai
thuế suất. Hai chiều sai không cùng giá:

* nói 10% cho mặt hàng thực ra 8% -> hoá đơn đắt hơn, phải điều chỉnh
* nói 8%  cho mặt hàng thực ra 10% -> bị truy thu, cộng tiền chậm nộp, phạt

Vì vậy phần lớn test ở đây kiểm chuyện KHÔNG kết luận: bảng tra phải biết im
khi không chắc, và phải xét quy tắc loại trừ trước quy tắc giảm.
"""

from __future__ import annotations

import pytest

from src.core.vat_catalog import (
    CHUA_XAC_DINH,
    DUOC_GIAM,
    KHONG_GIAM,
    SanPham,
    audit_vat_catalog,
    parse_product_table,
    phan_loai_thue_suat,
)


def sp(code, name, co="Chưa xác định", nhom="HH") -> SanPham:
    return SanPham(code=code, name=name, vat_flag=co, group=nhom, unit="Lít")


def kinds(kq) -> list[str]:
    return [f["kind"] for f in kq["findings"]]


# ---------------------------------------------------------------------------
# Được giảm — mặt hàng lõi của Hoàng Phát
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ten", [
    "Dầu nhớt động cơ 4 kỳ SJ-40 (0.8Lx24)",
    "Dầu nhớt động cơ xe máy 4 kỳ SJ 20W-40",
    "Dầu truyền động ENEOS Gear GL 590 (18L)",
    "Dầu bánh răng công nghiệp Bonnoc TS 150 (200L)",
    "Dầu cắt gọt pha nước ENEOS UNISOLUBLE EM-V (18L)",
    "Dầu chống gỉ dài hạn Antirust LS (20L)",
    "Dầu trợ lực Fluid Matic IID18(1L)",
    "Dầu Caltex Rando HD 46",
    "Dầu Caltex Delo Silver MG 15W40",
    "Dầu Mobilgear 600 XP 150, 20LT, PAIL",
    "Dầu TL AW68",
    "Mỡ bôi trơn đa năng chịu nhiệt 130 độ",
    "Mỡ Litium L3 (180kg)",
    "Mỡ Caltex Multifak EP3",
    "Mỡ số 0",
])
def test_dau_mo_boi_tron_duoc_giam_con_8(ten):
    """
    Nghị định 174/2025 đã bỏ 'sản phẩm dầu mỏ tinh chế' — trong đó ghi rõ dầu
    mỡ bôi trơn — khỏi danh mục loại trừ, hiệu lực 01/7/2025. Trước đó nhóm này
    chịu 10%, nên đây là thay đổi dễ bỏ sót nhất.
    """
    kq = phan_loai_thue_suat(ten)
    assert kq.ket_luan == DUOC_GIAM
    assert "174/2025" in kq.can_cu


def test_can_cu_luon_di_kem_ket_luan():
    kq = phan_loai_thue_suat("Dầu nhớt động cơ")
    assert kq.can_cu and "204/2025/QH15" in kq.can_cu


@pytest.mark.parametrize("ten", [
    "Cước vận chuyển hàng từ Hà Nội đến Huế",
    "Quạt điện ENEOS",
    "Dung dịch làm sạch buồng đốt động cơ ô tô",
])
def test_hang_dich_vu_thong_thuong_duoc_giam(ten):
    assert phan_loai_thue_suat(ten).ket_luan == DUOC_GIAM


# ---------------------------------------------------------------------------
# KHÔNG được giảm — xét trước, vì sai chiều này đắt hơn
# ---------------------------------------------------------------------------

def test_bia_trong_danh_muc_khuyen_mai_van_la_hang_chiu_TTDB():
    """
    Mã KM00025 'Bia 333' có thật trong danh mục của một nhà phân phối dầu nhớt —
    hàng tặng khách. Bia chịu thuế tiêu thụ đặc biệt nên KHÔNG được giảm, dù mọi
    mã xung quanh nó đều được.
    """
    kq = phan_loai_thue_suat("Bia 333")
    assert kq.ket_luan == KHONG_GIAM
    assert "tiêu thụ đặc biệt" in kq.can_cu


@pytest.mark.parametrize("ten", [
    "Thép hộp mạ kẽm",
    "Tôn lạnh mạ màu",
    "Rượu vang Đà Lạt",
    "Thuốc lá Vinataba",
    "Cước viễn thông tháng 8",
    "Phí bảo hiểm hàng hoá",
    "Quặng sắt loại 1",
])
def test_nhom_loai_tru_giu_nguyen_10(ten):
    assert phan_loai_thue_suat(ten).ket_luan == KHONG_GIAM


def test_xang_la_NGOAI_LE_cua_nhom_chiu_TTDB():
    """
    Hàng chịu thuế TTĐB không được giảm, nhưng xăng được nêu đích danh là ngoại
    lệ trong Nghị quyết 204/2025 — nên xăng vẫn 8%.
    """
    assert phan_loai_thue_suat("Xăng RON 95").ket_luan == DUOC_GIAM


def test_loai_tru_duoc_xet_TRUOC_duoc_giam():
    """
    'Dầu' khớp quy tắc được giảm, 'rượu' khớp quy tắc loại trừ. Tên chứa cả hai
    thì phải ra kết luận AN TOÀN, tức là không giảm.
    """
    assert phan_loai_thue_suat("Dầu ngâm rượu thuốc").ket_luan == KHONG_GIAM


# ---------------------------------------------------------------------------
# Biết im khi không chắc
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ten", [
    "Dầu ăn Neptune",
    "Dầu gội đầu Clear",
    "Dầu cá Omega 3",
    "Mỡ heo tinh luyện",
])
def test_dau_mo_THUC_PHAM_va_MY_PHAM_thi_khong_ket_luan(ten):
    """
    Quy tắc 'tên bắt đầu bằng Dầu/Mỡ' đúng trong danh mục một nhà phân phối dầu
    nhớt, nhưng sẽ đi lạc nếu đem sang ngành thực phẩm. Chặn tường minh, để
    người quyết định, thay vì gắn cho nó căn cứ 'dầu mỡ bôi trơn'.
    """
    assert phan_loai_thue_suat(ten).ket_luan == CHUA_XAC_DINH


@pytest.mark.parametrize("ten", [
    "LONG ĐEN ỐC XẢ DẦU",
    "Clarion MVF501 (Camera lùi)",
    "",
    "   ",
])
def test_khong_khop_quy_tac_nao_thi_tra_chua_xac_dinh(ten):
    kq = phan_loai_thue_suat(ten)
    assert kq.ket_luan == CHUA_XAC_DINH
    assert not kq.chac_chan


def test_chua_xac_dinh_la_mac_dinh_chu_khong_phai_loi():
    assert phan_loai_thue_suat("Một mặt hàng hoàn toàn lạ").ket_luan == CHUA_XAC_DINH


# ---------------------------------------------------------------------------
# Soi cả danh mục
# ---------------------------------------------------------------------------

def test_ca_danh_muc_chua_gan_co_thi_bao_MOT_lan_chu_khong_161_lan():
    """161 phát hiện giống nhau thì không ai đọc — gộp thành một."""
    ds = [sp(f"VT{i:05d}", "Dầu nhớt động cơ") for i in range(161)]
    kq = audit_vat_catalog(ds)
    assert kinds(kq).count("vat_flag_unset_all") == 1
    assert "vat_flag_unset" not in kinds(kq)
    assert kq["findings"][0]["evidence"]["số_mã"] == 161


def test_chi_MOT_SO_ma_chua_gan_co_thi_bao_kieu_khac():
    ds = [sp("A", "Dầu nhớt động cơ", co="Được giảm"),
          sp("B", "Dầu nhớt động cơ")]
    k = kinds(audit_vat_catalog(ds))
    assert "vat_flag_unset" in k and "vat_flag_unset_all" not in k


def test_bao_rieng_nhom_dang_le_duoc_giam_ma_chua_gan_co():
    ds = [sp("A", "Dầu nhớt động cơ"), sp("B", "Mỡ bôi trơn đa năng")]
    f = next(x for x in audit_vat_catalog(ds)["findings"]
             if x["kind"] == "vat_reduction_missed")
    assert f["severity"] == "cao"
    assert f["evidence"]["số_mã"] == 2
    assert "01/7/2025" in f["suggestion"]


def test_ma_co_dau_hieu_KHONG_duoc_giam_thi_bao_rieng_tung_ma():
    """Nhóm này ít nhưng đắt — mỗi mã một phát hiện để không ai lướt qua."""
    ds = [sp("KM00025", "Bia 333"), sp("A", "Dầu nhớt động cơ")]
    f = [x for x in audit_vat_catalog(ds)["findings"] if x["kind"] == "vat_rate_review"]
    assert len(f) == 1 and f[0]["code"] == "KM00025"
    assert f[0]["severity"] == "cao"
    assert "truy thu" in f[0]["suggestion"]


def test_ma_khong_tra_duoc_thi_noi_thang_la_can_nguoi():
    ds = [sp("A", "Dầu nhớt động cơ"), sp("X", "Vật gì đó không rõ")]
    f = next(x for x in audit_vat_catalog(ds)["findings"]
             if x["kind"] == "vat_needs_human")
    assert f["evidence"]["các_mã"] == ["X"]
    assert "đừng suy" in f["suggestion"]


def test_ma_da_gan_co_roi_thi_khong_bi_de_xuat_lai():
    ds = [sp("A", "Dầu nhớt động cơ", co="Được giảm"),
          sp("B", "Dầu nhớt động cơ", co="Được giảm")]
    assert audit_vat_catalog(ds)["findings"] == []


def test_chi_phi_mua_hang_khong_phai_hang_hoa_nen_bi_loai_khoi_pham_vi():
    """CPMH là khoản phân bổ chi phí, không có thuế suất để bàn."""
    ds = [sp("CPMH", "Chi phí mua hàng"), sp("A", "Dầu nhớt động cơ")]
    kq = audit_vat_catalog(ds)
    assert kq["summary"]["số_mã"] == 1
    assert "vat_needs_human" not in kinds(kq)


def test_tom_tat_luon_nhac_ke_toan_chiu_trach_nhiem_cuoi_cung():
    kq = audit_vat_catalog([sp("A", "Dầu nhớt động cơ")])
    assert "kế toán" in kq["summary"]["lưu_ý"]
    assert kq["summary"]["hiệu_lực_đến"] == "2026-12-31"


def test_danh_muc_rong_khong_no_ra_loi():
    kq = audit_vat_catalog([])
    assert kq["findings"] == [] and kq["summary"]["số_mã"] == 0


# ---------------------------------------------------------------------------
# Đọc file danh mục
# ---------------------------------------------------------------------------

TIEU_DE = ["STT", "Mã", "Tên", "Giảm 2% thuế suất thuế GTGT", "Nhóm VTHH",
           "Đơn vị tính chính", "Số lượng tồn", "Giá trị tồn"]


def _bang(*dong):
    return [["DANH SÁCH HÀNG HÓA, DỊCH VỤ"] + [""] * 7,
            [""] * 8, list(TIEU_DE)] + [list(d) for d in dong]


def test_doc_dung_bang_danh_muc_that():
    rows = _bang(
        [1, "CPMH", "Chi phí mua hàng", "Chưa xác định", "", "", 0, 0],
        [2, "VT00125", "Dầu Mobilgear 600 XP 150", "Chưa xác định", "HH", "Xô", 4, 7360000],
        ["", "", "Tổng", "", "", "", "", 2874073721],
    )
    res = parse_product_table(rows)
    assert res.ok and len(res.products) == 2
    p = res.products[1]
    assert p.code == "VT00125" and p.group == "HH" and p.unit == "Xô"
    assert p.qty == 4 and p.value == 7360000
    assert p.chua_gan_co()


def test_cot_ma_khong_nuot_cot_ten():
    res = parse_product_table(_bang([1, "VT1", "Dầu nhớt", "Chưa xác định", "HH", "Lít", 1, 2]))
    assert res.products[0].code == "VT1"
    assert res.products[0].name == "Dầu nhớt"


def test_thieu_cot_co_thue_thi_van_doc_duoc_nhung_canh_bao():
    rows = [["STT", "Mã", "Tên"], [1, "A", "Dầu nhớt"]]
    res = parse_product_table(rows)
    assert len(res.products) == 1
    assert any("Giảm 2%" in w for w in res.warnings)


def test_o_co_thue_rong_cung_la_chua_gan_co():
    assert SanPham(code="A", name="x", vat_flag="").chua_gan_co()
    assert SanPham(code="A", name="x", vat_flag="Chưa xác định").chua_gan_co()
    assert not SanPham(code="A", name="x", vat_flag="Được giảm").chua_gan_co()


def test_thieu_cot_bat_buoc_thi_tu_choi_doc():
    res = parse_product_table([["STT", "Địa chỉ"], [1, "HN"]])
    assert not res.ok and res.products == []
