"""
tests/test_eval_ke_toan.py — CỔNG CHẶN cho lớp kiểm kế toán.

Ba thứ file này canh, không thứ nào canh được bằng test đơn vị:

  1. HỒI QUY trên sổ thật — luật mới hôm nay có làm đổi kết quả trên bộ dữ liệu
     thật không. Đây là chỗ đã hỏng một lần: phép kiểm giá-trị-bằng-0 từng báo
     oan 29/38 dòng kho khuyến mại, mà mọi test đơn vị vẫn xanh vì từng hàm vẫn
     làm đúng thứ nó được viết ra để làm.
  2. GIEO LỖI — mười hai lỗi đặt vào chính sổ thật đó, đáp án biết trước. Đo bắt
     được bao nhiêu và báo oan bao nhiêu.
  3. RIÊNG TƯ — bộ dữ liệu trong repo phải luôn là bản ẩn danh. Một lần lỡ tay
     chép file gốc vào đây là danh sách khách của Hoàng Phát nằm trên GitHub.

Muốn đọc số đầy đủ kèm khoảng tin cậy:

    python -m offline_training.eval_ke_toan
"""

from __future__ import annotations

import json

import pytest

from offline_training.eval_ke_toan import (
    CAC_CA,
    DU_LIEU,
    MOC,
    cham_gieo_loi,
    so_voi_moc,
)

# Chạy một lần cho cả file — mỗi lần chạy phải nạp và soi lại 5 bộ dữ liệu.
GIEO = cham_gieo_loi()
HOI_QUY = so_voi_moc()


# ---------------------------------------------------------------------------
# 1. Hồi quy trên sổ thật
# ---------------------------------------------------------------------------

def test_co_moc_da_chot():
    assert MOC.exists(), (
        "Chưa có mốc. Chạy: python -m offline_training.eval_ke_toan --cap-nhat-moc"
    )


@pytest.mark.parametrize("lop", sorted(HOI_QUY.get("lớp", {})))
def test_ket_qua_tren_so_that_khong_doi(lop):
    """
    Đổi kết quả không phải lúc nào cũng sai — nhưng phải là CHỦ Ý.

    Test đỏ ở đây nghĩa là: đọc kỹ phần biến mất / mọc thêm. Nếu đúng là cải
    tiến thì chạy `--cap-nhat-moc` để chốt mốc mới, và nói rõ trong commit vì
    sao. Nếu không giải thích được thì đó là hồi quy.
    """
    v = HOI_QUY["lớp"][lop]
    assert not v["biến_mất"], (
        f"[{lop}] {len(v['biến_mất'])} phát hiện BIẾN MẤT so với mốc — "
        f"lớp kiểm đã thôi bắt được thứ nó từng bắt: {v['biến_mất'][:5]}"
    )
    assert not v["mọc_thêm"], (
        f"[{lop}] {len(v['mọc_thêm'])} phát hiện MỌC THÊM so với mốc — "
        f"có thể là báo oan mới: {v['mọc_thêm'][:5]}"
    )


def test_kho_khuyen_mai_khong_quay_lai_tran_bao_oan():
    """
    Khoá lại đúng ca đã hỏng. Kho khuyến mại có 38 dòng; bản cũ báo 29 dòng
    "có số lượng nhưng không ghi nhận giá trị" — gần như mọi dòng có hàng.

    Một bộ soi kêu ca gần hết bảng thì bị tắt, và khi bị tắt nó cũng thôi bắt
    được ca tồn âm −115,2 lít nằm cùng bảng đó.
    """
    km = HOI_QUY["lớp"]["ton_kho_km"]
    assert km["số_phát_hiện"] < 40, "kho khuyến mại đang báo gần như mọi dòng"

    moc = json.loads(MOC.read_text(encoding="utf-8"))
    loai = [x[0] for x in moc["ton_kho_km"]]
    assert loai.count("zero_valued_stock") == 0, (
        "phát hiện giá-trị-bằng-0 ở mức DÒNG đã quay lại; nó phải được gộp thành "
        "một phát hiện ở mức KHO"
    )
    assert "warehouse_zero_valued" in loai, (
        "gộp lại rồi thì vẫn phải nói MỘT lần — cả kho không ghi nhận giá vốn là "
        "chuyện chủ doanh nghiệp cần biết"
    )
    assert "negative_stock" in loai, "ca tồn âm thật trong kho đó phải còn nguyên"


# ---------------------------------------------------------------------------
# 2. Gieo lỗi — đáp án biết trước
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ca", GIEO["ca"], ids=lambda c: c["ma"])
def test_gieo_loi_nao_cung_bat_duoc(ca):
    assert ca["bắt_được"], (
        f"gieo '{ca['mô_tả']}' mà không ra {ca['mong_đợi']} — "
        f"lớp kiểm bỏ sót đúng thứ nó sinh ra để bắt"
    )


@pytest.mark.parametrize("ca", GIEO["ca"], ids=lambda c: c["ma"])
def test_gieo_mot_loi_khong_lam_moc_them_phat_hien_la(ca):
    """
    Báo oan đắt hơn bỏ sót ở sản phẩm này: một báo cáo có năm phát hiện sai
    trong hai mươi thì khách thôi tin cả mười lăm cái đúng.
    """
    assert not ca["báo_oan"], (
        f"gieo '{ca['mô_tả']}' làm mọc thêm phát hiện không liên quan: {ca['báo_oan']}"
    )


def test_du_bon_lop_kiem_deu_co_ca_gieo():
    """Một lớp không có ca nào thì nó không được đo, dù bảng kết quả vẫn đẹp."""
    assert {c.lop for c in CAC_CA} == {"ton_kho", "doi_tac", "thue", "hai_ky"}


def test_moi_ca_gieo_deu_nham_mot_phep_kiem_co_that():
    """Chống gõ sai tên `kind` — ca nhắm vào một phép kiểm không tồn tại sẽ luôn
    'bỏ sót' và không ai biết là do gõ sai."""
    from offline_training.eval_ke_toan import chay_tat_ca

    co_that = {f["kind"] for fs in chay_tat_ca().values() for f in fs}
    # Những kind chỉ xuất hiện KHI có lỗi nên không nằm trong bộ dữ liệu sạch.
    chi_khi_co_loi = {"balance_mismatch", "value_sign_conflict", "invalid_tax_id",
                      "duplicate_partner", "missing_tax_id", "vat_rate_review",
                      "opening_changed"}
    for c in CAC_CA:
        assert c.mong_doi_kind in (co_that | chi_khi_co_loi), (
            f"ca '{c.ma}' nhắm vào kind '{c.mong_doi_kind}' không phép kiểm nào sinh ra"
        )


# ---------------------------------------------------------------------------
# 3. Riêng tư — dữ liệu trong repo phải luôn là bản ẩn danh
# ---------------------------------------------------------------------------

# KHÔNG liệt kê tên và mã số thuế thật ở đây.
#
# Bản đầu của mục này giữ sẵn một danh sách tên công ty và mã số thuế THẬT để
# khẳng định chúng vắng mặt khỏi bộ dữ liệu. Nhưng làm vậy thì chính danh sách
# đó đưa tên khách và mã số thuế thật lên GitHub — đúng thứ nó sinh ra để ngăn.
# Một phép kiểm riêng tư mà phải chép dữ liệu riêng tư vào mới chạy được thì
# không phải phép kiểm riêng tư.
#
# Thay bằng phép kiểm NGƯỢC LẠI, mạnh hơn và không cần biết dữ liệu thật: mọi
# tên đối tác trong bộ eval phải sinh ra từ ĐÚNG bộ từ vựng của `an_danh.py`, và
# mọi mã số thuế phải nằm trong dãy mà `_muoi_so()` sinh ra. Bất cứ thứ gì lọt
# vào từ file gốc đều rơi ra ngoài hai tập đó.

@pytest.fixture(scope="module")
def toan_bo_du_lieu() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in DU_LIEU.glob("*.json"))


def _ten_doi_tac(ten_file: str) -> list[str]:
    luoi = json.loads((DU_LIEU / f"{ten_file}.json").read_text(encoding="utf-8"))
    i_hdr = next(i for i, r in enumerate(luoi)
                 if any(str(c or "").strip().lower().startswith("mã ") for c in r))
    i_ten = next(i for i, c in enumerate(luoi[i_hdr])
                 if str(c or "").strip().lower().startswith("tên"))
    return [str(r[i_ten]).strip() for r in luoi[i_hdr + 1:]
            if len(r) > i_ten and r[i_ten] and str(r[i_ten]).strip().lower() != "tổng"]


@pytest.mark.parametrize("ten_file", ["khach_hang", "nha_cung_cap"])
def test_moi_ten_doi_tac_deu_do_bo_an_danh_sinh_ra(ten_file):
    from sample_data.an_danh import _DEM, _HO, _TEN, _TIEN_TO, _TU_DAT_TEN

    tu_vung = set(_TU_DAT_TEN)
    nguoi = set(_HO) | set(_DEM) | set(_TEN)

    for ten in _ten_doi_tac(ten_file):
        tien_to = next((t for t in _TIEN_TO if ten.upper().startswith(t)), None)
        if tien_to:
            con = ten[len(tien_to):].strip()
            con = con.rsplit(" ", 1)[0] if con.rsplit(" ", 1)[-1].isdigit() else con
            assert con in tu_vung, (
                f"'{ten}' trong {ten_file} không sinh từ bộ từ vựng ẩn danh — "
                f"nhiều khả năng là tên THẬT lọt vào. Chạy lại sample_data/an_danh.py"
            )
        else:
            phan = [p for p in ten.split() if not p.isdigit()]
            assert phan and all(p in nguoi for p in phan), (
                f"'{ten}' trong {ten_file} không sinh từ bộ tên người ẩn danh"
            )


def test_moi_ma_so_thue_deu_do_bo_an_danh_sinh_ra(toan_bo_du_lieu):
    """
    Dãy `_muoi_so()` là tất định, nên tái tạo lại rồi đối chiếu được. Mã số thuế
    thật lọt vào sẽ không nằm trong dãy đó.
    """
    import re

    from sample_data.an_danh import KhoTen

    kho = KhoTen()
    hop_le = {kho._muoi_so() for _ in range(400)}
    trong_file = set(re.findall(r'"(\d{10})(?:-\d{3})?"', toan_bo_du_lieu))
    la = sorted(trong_file - hop_le)
    assert not la, (
        f"{len(la)} mã số thuế không do bộ ẩn danh sinh ra: {la[:5]} — "
        f"nhiều khả năng là mã THẬT lọt vào repo"
    )


def test_khong_co_file_xlsx_nao_trong_thu_muc_eval():
    """Bản xuất MISA gốc không được nằm ở đây dưới bất kỳ dạng nào."""
    la = [p.name for p in DU_LIEU.iterdir() if p.suffix.lower() in (".xlsx", ".xls")]
    assert not la, f"file gốc lọt vào thư mục eval: {la}"


def test_du_lieu_eval_van_giu_duoc_thu_can_do(toan_bo_du_lieu):
    """
    Ẩn danh quá tay cũng hỏng: từng có lần bộ ẩn danh thay nhầm tên ba mặt hàng
    thành 'Địa chỉ đã ẩn', và bảng tra thuế tụt từ 157 xuống 154 mã mà không ai
    biết vì sao.
    """
    assert "VT00059" in toan_bo_du_lieu, "mã hàng phải giữ nguyên"
    assert "Dầu nhớt động cơ" in toan_bo_du_lieu, "tên hàng phải giữ — bảng tra thuế cần"
    assert "CÔNG TY TNHH" in toan_bo_du_lieu, "dạng pháp nhân phải giữ"
    assert "Địa chỉ đã ẩn" not in json.dumps(
        json.loads((DU_LIEU / "hang_hoa.json").read_text(encoding="utf-8"))[3:],
        ensure_ascii=False,
    ), "bộ ẩn danh đã ăn vào dòng dữ liệu của danh mục hàng hoá"
