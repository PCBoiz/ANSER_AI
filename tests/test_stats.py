"""
tests/test_stats.py — hai phép thống kê dùng để ĐỌC kết quả benchmark.

Mọi giá trị mong đợi ở đây đối chiếu được với nguồn ngoài (bảng Wilson chuẩn,
phép thử nhị thức tính tay). Một bài kiểm thống kê mà giá trị mong đợi lấy từ
chính hàm đang kiểm thì không kiểm được gì.
"""

from __future__ import annotations

import math

import pytest

from offline_training.stats import Khoang, cong_chan, mcnemar, wilson

# ---------------------------------------------------------------------------
# Wilson
# ---------------------------------------------------------------------------

def test_wilson_khop_gia_tri_tinh_tay():
    """
    k=84, n=100, z=1.95996 -> Wilson TRẦN = [0.755797, 0.899047].

    Tính tay từng bước:
        p = 0.84,  z²/n = 0.0384158
        tâm  = (0.84 + 0.0192079) / 1.0384158 = 0.827425
        nửa  = (1.95996 / 1.0384158) · √(0.84·0.16/100 + 0.0384158/400)
             = 1.887474 · 0.0379479 = 0.0716245

    Lưu ý: bản đầu của test này ghi [0.7566, 0.8963] — đó là Wilson CÓ HIỆU
    CHỈNH LIÊN TỤC, không phải bản đang dùng. Sai hằng số trong bài kiểm thống
    kê là kiểu sai tệ nhất: nó làm ta đi sửa một công thức vốn đúng.
    """
    kq = wilson(84, 100)
    assert kq.thap == pytest.approx(0.755797, abs=1e-5)
    assert kq.cao == pytest.approx(0.899047, abs=1e-5)


def test_dung_het_KHONG_cho_khoang_rong_bang_khong():
    """
    Đây là lý do dùng Wilson thay vì công thức chuẩn. Với k=n, công thức chuẩn
    (Wald) cho [1.0, 1.0] — tức là khẳng định "chắc chắn 100%" từ 27 mẫu.
    """
    kq = wilson(27, 27)
    assert kq.ty_le == 1.0
    assert kq.cao == 1.0
    assert kq.thap < 0.90, "27 mẫu đúng hết KHÔNG chứng minh được tỷ lệ trên 90%"
    assert kq.thap > 0.80


def test_sai_het_cung_khong_cho_khoang_rong_bang_khong():
    kq = wilson(0, 20)
    assert kq.ty_le == 0.0 and kq.thap == 0.0
    assert kq.cao > 0.10, "0/20 không chứng minh được tỷ lệ dưới 10%"


def test_n_cang_nho_khoang_cang_rong():
    """Cùng một tỷ lệ, ít mẫu hơn thì biết ít hơn — và phải nói ra."""
    rong = [wilson(round(0.85 * n), n).do_rong for n in (20, 50, 100, 400)]
    assert rong == sorted(rong, reverse=True), rong


def test_bo_eval_27_cau_co_khoang_rat_rong():
    """
    Con số thật trong báo cáo: 84.8% trên bộ agentic. Với n=27 thì đó là một
    khoảng rộng ~27 điểm — in mỗi "84.8%" là làm ra vẻ chính xác hơn thực tế.
    """
    kq = wilson(23, 27)
    assert kq.do_rong > 0.20
    assert kq.thap < 0.75 and kq.cao > 0.93


def test_khong_bao_gio_ra_ngoai_khoang_0_1():
    for n in (1, 3, 7, 30, 250):
        for k in (0, 1, n // 2, n):
            kq = wilson(k, n)
            assert 0.0 <= kq.thap <= kq.ty_le <= kq.cao <= 1.0, (k, n, kq)


def test_n_bang_khong_khong_lam_sap():
    kq = wilson(0, 0)
    assert kq.n == 0 and (kq.thap, kq.cao) == (0.0, 1.0)


def test_hien_thi_co_ca_diem_va_khoang():
    assert "84." in str(wilson(84, 100))
    assert "–" in str(wilson(84, 100)), "phải in cả khoảng, không chỉ điểm"


# ---------------------------------------------------------------------------
# McNemar
# ---------------------------------------------------------------------------

def test_hai_ban_giong_het_thi_p_bang_1():
    """
    Không có ca nào khác nhau = không có bằng chứng bản nào hơn. p = 1.
    Trả p = 0 ở đây là kết luận ngược hoàn toàn.
    """
    a = [True, True, False, False]
    kq = mcnemar(a, list(a))
    assert kq.khac_biet == 0 and kq.p_value == 1.0
    assert not kq.dang_ke


def test_dem_dung_bon_o():
    a = [True,  True,  False, False, True]
    b = [True,  False, True,  False, False]
    kq = mcnemar(a, b)
    assert kq.ca_hai_dung == 1
    assert kq.chi_A_dung == 2      # A đúng, B sai -> B LÀM HỎNG
    assert kq.chi_B_dung == 1      # A sai, B đúng -> B SỬA ĐƯỢC
    assert kq.ca_hai_sai == 1


def test_p_value_khop_phep_thu_nhi_thuc_tinh_tay():
    """
    10 ca khác biệt, B sửa được cả 10. Phép thử hai phía trên Binom(10, 0.5):
    p = 2 * P(X <= 0) = 2 * (1/1024) = 1/512.
    """
    a = [False] * 10
    b = [True] * 10
    kq = mcnemar(a, b)
    assert kq.chi_B_dung == 10 and kq.chi_A_dung == 0
    assert kq.p_value == pytest.approx(2 / 1024)
    assert kq.dang_ke


def test_cai_thien_nho_tren_n_nho_thi_KHONG_dang_ke():
    """
    Chỗ này là toàn bộ lý do file tồn tại. B sửa 3, làm hỏng 1 — trung bình
    "tăng 2 câu", nghe như tiến bộ. Nhưng p = 2*P(X<=1) với Binom(4, 0.5)
    = 2 * 5/16 = 0.625. Không phân biệt được với tung đồng xu.
    """
    a = [True] + [False] * 3 + [True] * 6
    b = [False] + [True] * 3 + [True] * 6
    kq = mcnemar(a, b)
    assert kq.chi_B_dung == 3 and kq.chi_A_dung == 1
    assert kq.p_value == pytest.approx(0.625)
    assert not kq.dang_ke, "3 sửa / 1 hỏng trên n nhỏ KHÔNG chứng minh được gì"


def test_bat_duoc_vung_thoai_lui_ma_diem_trung_binh_giau():
    """
    Điểm trung bình BẰNG NHAU (7/10 cả hai) nhưng hai bản khác nhau ở 6 câu.
    Nhìn hai con số 70% và 70% thì tưởng không đổi gì.
    """
    a = [True] * 7 + [False] * 3
    b = [False] * 3 + [True] * 4 + [True] * 3
    assert sum(a) == sum(b) == 7
    kq = mcnemar(a, b)
    assert kq.chi_A_dung == 3, "3 câu bản mới LÀM HỎNG"
    assert kq.chi_B_dung == 3, "3 câu bản mới sửa được"


def test_do_dai_lech_thi_bao_loi():
    with pytest.raises(ValueError, match="cùng độ dài"):
        mcnemar([True, False], [True])


def test_doi_cho_hai_ban_thi_p_khong_doi():
    """Phép thử hai phía — đổi vai không đổi kết luận."""
    a = [True, False, True, False, True, True]
    b = [False, True, True, False, False, True]
    assert mcnemar(a, b).p_value == pytest.approx(mcnemar(b, a).p_value)


# ---------------------------------------------------------------------------
# Cổng chặn
# ---------------------------------------------------------------------------

def test_cong_chan_canh_bao_khi_khoang_vat_qua_nguong():
    """
    23/27 = 85.2%, ngưỡng 85%. Qua — nhưng khoảng [66%, 94%] vắt qua ngưỡng,
    nên "qua" lần này không phân biệt được với nhiễu.
    """
    qua, ghi_chu = cong_chan(wilson(23, 27), 0.85)
    assert qua
    assert "KHÔNG PHÂN BIỆT" in ghi_chu


def test_cong_chan_khong_canh_bao_khi_ket_luan_ro_rang():
    """95/100 so với ngưỡng 60% — khoảng nằm hẳn trên ngưỡng."""
    qua, ghi_chu = cong_chan(wilson(95, 100), 0.60)
    assert qua and ghi_chu == ""


def test_cong_chan_van_truot_khi_kem_ro_rang():
    qua, ghi_chu = cong_chan(wilson(10, 100), 0.80)
    assert not qua and ghi_chu == ""


def test_cong_chan_van_theo_diem_uoc_luong_chu_khong_theo_can_duoi():
    """
    Đổi sang chặn theo cận dưới sẽ làm mọi cổng trượt trên bộ eval nhỏ, và một
    cổng lúc nào cũng đỏ thì bị tắt — mất luôn tác dụng.
    """
    kq = wilson(23, 27)          # điểm 85.2%, cận dưới ~66%
    assert kq.thap < 0.80 < kq.ty_le
    qua, _ = cong_chan(kq, 0.80)
    assert qua, "phải qua theo điểm ước lượng, chỉ cảnh báo về độ rộng"


def test_n_bang_khong_noi_ro_la_khong_do_duoc():
    _, ghi_chu = cong_chan(wilson(0, 0), 0.80)
    assert "n=0" in ghi_chu


# ---------------------------------------------------------------------------
# Đối chiếu chéo: hai phép phải nhất quán với nhau
# ---------------------------------------------------------------------------

def test_wilson_va_mcnemar_nhat_quan_tren_cung_du_lieu():
    """
    Bộ 27 câu, baseline 15 đúng, tuned 23 đúng. Khoảng của hai bên chồng nhau
    rất nhiều, nhưng so THEO CẶP vẫn kết luận được — đó chính là lý do phải so
    theo cặp thay vì so hai khoảng.
    """
    a = [True] * 15 + [False] * 12
    b = [True] * 15 + [True] * 8 + [False] * 4
    assert sum(a) == 15 and sum(b) == 23

    ka, kb = wilson(15, 27), wilson(23, 27)
    assert ka.cao > kb.thap, "hai khoảng chồng nhau — nhìn riêng thì không kết luận được"

    kq = mcnemar(a, b)
    assert kq.chi_B_dung == 8 and kq.chi_A_dung == 0
    assert kq.dang_ke, "so theo cặp thì kết luận được"
    assert kq.p_value == pytest.approx(2 / (2 ** 8))


def test_tinh_tay_lai_cong_thuc_wilson():
    """Kiểm công thức, không kiểm bằng chính nó."""
    k, n = 7, 12
    z = 1.959963984540054
    p = k / n
    z2n = z * z / n
    tam = (p + z2n / 2) / (1 + z2n)
    nua = (z / (1 + z2n)) * math.sqrt(p * (1 - p) / n + z2n / (4 * n))

    kq = wilson(k, n)
    assert kq.thap == pytest.approx(tam - nua)
    assert kq.cao == pytest.approx(tam + nua)


def test_kieu_tra_ve_dung_dataclass():
    assert isinstance(wilson(1, 2), Khoang)
