"""
Kiểm thử src/core/partner_import.py — đọc danh sách khách hàng / nhà cung cấp.

Cùng mối lo với trình đọc tồn kho: lỗi đáng sợ không phải "đọc hỏng" mà là
"đọc được nhưng lệch cột". Ở bảng này có một cái bẫy riêng — hai cột cùng bắt
đầu bằng chữ 'Mã': 'Mã khách hàng' và 'Mã số thuế'. Khớp tham lam sẽ lấy mã số
thuế làm mã đối tác, và mọi con số vẫn trông bình thường.
"""

from __future__ import annotations

from src.core.partner_import import (
    KHACH_HANG,
    NHA_CUNG_CAP,
    Partner,
    parse_partner_table,
)

TIEU_DE_KH = ["STT", "Mã khách hàng", "Tên khách hàng", "Địa chỉ", "Công nợ",
              "Mã số thuế", "Điện thoại"]
TIEU_DE_NCC = ["STT", "Mã nhà cung cấp", "Tên nhà cung cấp", "Địa chỉ", "Công nợ",
               "Mã số thuế", "Điện thoại"]


def _bang(tieu_de, *dong, tren=("Danh sách khách hàng",)):
    rows = [[t] + [""] * (len(tieu_de) - 1) for t in tren]
    rows.append([""] * len(tieu_de))
    rows.append(list(tieu_de))
    rows.extend([list(d) for d in dong])
    return rows


def test_doc_dung_bang_khach_hang_that():
    rows = _bang(
        TIEU_DE_KH,
        [1, "KH00001", "CÔNG TY CỔ PHẦN 479 HOÀ BÌNH", "Số 54, Nguyễn Du",
         1129540864, "2900325124", ""],
        [2, "KH00023", "Nguyễn Trung Kiên", "Hà Nội", 0, "", "0912345678"],
        ["", "Tổng", "", "", "", "", ""],
    )
    res = parse_partner_table(rows)
    assert res.ok and res.warnings == []
    assert len(res.partners) == 2
    a, b = res.partners
    assert a.code == "KH00001"
    assert a.tax_id == "2900325124"
    assert a.balance == 1129540864
    assert b.code == "KH00023" and b.tax_id == ""


def test_cot_ma_so_thue_KHONG_bi_nhan_nham_la_cot_ma():
    """
    Cái bẫy chính của bảng này. Nếu 'Mã' khớp tham lam vào 'Mã số thuế' thì mã
    đối tác trở thành mã số thuế — mọi dòng vẫn đọc được, chỉ là sai hết.
    """
    rows = _bang(TIEU_DE_KH,
                 [1, "KH00001", "CÔNG TY A", "HN", 1000, "2900325124", ""])
    p = parse_partner_table(rows).partners[0]
    assert p.code == "KH00001"
    assert p.tax_id == "2900325124"


def test_dong_Tong_khong_thanh_mot_doi_tac():
    rows = _bang(TIEU_DE_KH,
                 [1, "KH00001", "CÔNG TY A", "HN", 1000, "2900325124", ""],
                 ["", "Tổng", "", "", "", "", ""])
    assert [p.code for p in parse_partner_table(rows).partners] == ["KH00001"]


def test_tu_nhan_ra_vai_tro_tu_tieu_de():
    kh = parse_partner_table(_bang(TIEU_DE_KH, [1, "KH1", "A", "", 0, "", ""]))
    ncc = parse_partner_table(_bang(
        TIEU_DE_NCC, [1, "NCC1", "B", "", 0, "", ""], tren=("Danh sách nhà cung cấp",)))
    assert kh.role == KHACH_HANG
    assert ncc.role == NHA_CUNG_CAP


def test_vai_tro_truyen_vao_duoc_uu_tien():
    res = parse_partner_table(_bang(TIEU_DE_KH, [1, "X", "A", "", 0, "", ""]),
                              role=NHA_CUNG_CAP)
    assert res.role == NHA_CUNG_CAP
    assert res.partners[0].role == NHA_CUNG_CAP


# ---------------------------------------------------------------------------
# Lớp tự kiểm bằng STT
# ---------------------------------------------------------------------------

def test_STT_lech_so_dong_thi_BAO():
    """
    MISA đánh STT liên tục 1..N. Đọc ra 2 dòng mà STT lớn nhất là 5 nghĩa là ba
    dòng đã bị nuốt — không có dòng tổng nào để đối chiếu, nên STT là lớp kiểm
    duy nhất còn lại.
    """
    rows = _bang(TIEU_DE_KH,
                 [1, "KH00001", "A", "", 0, "", ""],
                 [5, "KH00005", "B", "", 0, "", ""])
    res = parse_partner_table(rows)
    assert not res.ok
    assert res.checks["stt_mismatch"] == {"stt_lớn_nhất": 5, "số_dòng_đọc": 2}
    assert any("bỏ sót" in w for w in res.warnings)


def test_STT_khop_thi_khong_bao():
    rows = _bang(TIEU_DE_KH,
                 [1, "KH00001", "A", "", 0, "", ""],
                 [2, "KH00002", "B", "", 0, "", ""])
    res = parse_partner_table(rows)
    assert res.ok and "stt_mismatch" not in res.checks


def test_ma_doi_tac_lap_thi_BAO():
    rows = _bang(TIEU_DE_KH,
                 [1, "KH00001", "A", "", 0, "", ""],
                 [2, "KH00001", "A lần hai", "", 0, "", ""])
    res = parse_partner_table(rows)
    assert res.checks["duplicate_codes"] == ["KH00001"]


def test_thieu_cot_bat_buoc_thi_tu_choi_doc():
    rows = [["STT", "Địa chỉ", "Công nợ"], [1, "HN", 100]]
    res = parse_partner_table(rows)
    assert not res.ok
    assert res.checks["missing_columns"]
    assert res.partners == []


def test_khong_co_tieu_de_thi_tu_choi_doc():
    res = parse_partner_table([["gì đó", "linh tinh"], [1, 2]])
    assert not res.ok and res.partners == []


def test_thieu_cot_cong_no_thi_van_doc_duoc_nhung_canh_bao():
    rows = [["STT", "Mã khách hàng", "Tên khách hàng"], [1, "KH1", "A"]]
    res = parse_partner_table(rows)
    assert len(res.partners) == 1
    assert res.partners[0].balance is None
    assert any("Công nợ" in w for w in res.warnings)


# ---------------------------------------------------------------------------
# 'Chưa biết' khác 0
# ---------------------------------------------------------------------------

def test_o_cong_no_rong_tra_None_chu_khong_tra_0():
    rows = _bang(TIEU_DE_KH, [1, "KH1", "A", "", "", "", ""])
    assert parse_partner_table(rows).partners[0].balance is None


def test_cong_no_am_ghi_bang_ngoac_doc_dung():
    rows = _bang(TIEU_DE_KH, [1, "KH1", "A", "", "(28.962.041)", "", ""])
    assert parse_partner_table(rows).partners[0].balance == -28962041


def test_ma_so_thue_dang_SO_khong_mat_so_0_dau():
    """Ô định dạng kiểu số làm '0106733254' thành 106733254."""
    rows = _bang(TIEU_DE_KH, [1, "KH1", "CÔNG TY A", "", 0, 106733254, ""])
    assert parse_partner_table(rows).partners[0].tax_id == "0106733254"


# ---------------------------------------------------------------------------
# Phân biệt tổ chức với cá nhân
# ---------------------------------------------------------------------------

def test_nhan_ra_to_chuc_de_biet_khi_nao_thieu_mst_la_loi():
    assert Partner(code="1", name="CÔNG TY TNHH ABC").la_phap_nhan()
    assert Partner(code="2", name="Chi nhánh Công ty Cổ phần Mắt Bão").la_phap_nhan()
    assert Partner(code="3", name="HỢP TÁC XÃ VẬN TẢI").la_phap_nhan()
    assert not Partner(code="4", name="Nguyễn Trung Kiên").la_phap_nhan()
    assert not Partner(code="5", name="ĐẶNG XUÂN TIẾN").la_phap_nhan()
    assert not Partner(code="6", name="").la_phap_nhan()
