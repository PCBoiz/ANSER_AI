"""
tests/test_calibration.py — Giai đoạn 0: đối chiếu engine với giá thật.

Trọng tâm không phải "hàm chạy được" mà là **engine có chịu nói KHÔNG BIẾT
đúng lúc hay không**. Ba cách tự lừa mình mà module phải từ chối:

  1. Khớp `fuel_sensitivity` khi giá dầu trong dữ liệu không biến động.
  2. Khớp trọng số quá khít vào 15 ca rồi tưởng là đã hiểu quy tắc.
  3. Để sai lệch trung bình che mất một ca lệch 60%.
"""

from __future__ import annotations

import pytest

from src.core.calibration import (
    GATE_MAPE_PCT,
    CarrierChoiceCase,
    HistoricalQuote,
    fit_carrier_weights,
    fit_pricing_rule,
    replay_carrier_choices,
    replay_pricing,
)
from src.core.carrier_selection import DEFAULT_WEIGHTS, Carrier, QuoteOffer, RouteRequest
from src.core.pricing import PricingRule, Surcharge, compute_quote

BASELINE = 25_000


def rule(margin=10.0, fuel=0.35, floor=0.0):
    return PricingRule(base_margin_pct=margin, fuel_sensitivity=fuel,
                       fuel_baseline_price=BASELINE, min_margin_amount=floor)


def truth(cost, fuel_price, margin=10.0, fuel_sens=0.35):
    """Giá 'thật' sinh bằng CHÍNH engine — dùng để dựng dữ liệu đã biết đáp án."""
    return compute_quote(cost, rule(margin, fuel_sens), fuel_price)["quote"]["quoted_price"]


def perfect_rows(n=12, margin=10.0, fuel_sens=0.35, fuel_prices=None):
    prices = fuel_prices or [24_000 + i * 300 for i in range(n)]
    rows = []
    for i in range(n):
        cost = 10_000_000 + i * 1_000_000
        fp = prices[i % len(prices)]
        rows.append(HistoricalQuote(
            quote_id=f"BG{i:03d}", carrier_cost=cost, fuel_price=fp,
            actual_price=truth(cost, fp, margin, fuel_sens), route=f"tuyến {i}",
        ))
    return rows


# ---------------------------------------------------------------------------
# Đối chiếu công thức giá
# ---------------------------------------------------------------------------

def test_quy_tac_dung_thi_sai_lech_bang_0():
    r = replay_pricing(perfect_rows(), rule())
    assert r["summary"]["mape_pct"] == 0.0
    assert r["summary"]["passed"] is True
    assert "ĐẠT" in r["explain"]["gate"]


def test_bien_dat_sai_thi_bi_bat_va_noi_ro_huong_lech():
    rows = perfect_rows(margin=10.0)           # thực tế khách dùng biên 10%
    r = replay_pricing(rows, rule(margin=18.0))  # engine đang giả định 18%
    assert r["summary"]["passed"] is False
    assert r["summary"]["bias_pct"] > 0
    assert any("CAO hơn thực tế" in w for w in r["warnings"])


def test_bien_hep_hon_thuc_te_thi_canh_bao_an_vao_loi_nhuan():
    rows = perfect_rows(margin=15.0)
    r = replay_pricing(rows, rule(margin=8.0))
    assert r["summary"]["bias_pct"] < 0
    assert any("ăn vào lợi nhuận" in w for w in r["warnings"])


def test_trung_binh_khong_duoc_che_mat_ca_tham_hoa():
    """19 chuyến khớp hoàn hảo + 1 chuyến lệch nặng: p90/max phải phơi nó ra."""
    rows = perfect_rows(10)
    rows.append(HistoricalQuote(quote_id="XAU", carrier_cost=10_000_000,
                                fuel_price=25_000, actual_price=4_000_000,
                                route="ca bất thường"))
    s = replay_pricing(rows, rule())["summary"]
    assert s["median_abs_dev_pct"] == 0.0        # trung vị vẫn đẹp
    assert s["max_abs_dev_pct"] > 50             # nhưng ca tệ nhất lộ ra
    assert s["within_gate"] == 10


def test_ca_te_nhat_duoc_liet_ke_kem_so_lieu():
    rows = perfect_rows(10)
    rows.append(HistoricalQuote(quote_id="XAU", carrier_cost=10_000_000,
                                fuel_price=25_000, actual_price=4_000_000))
    worst = replay_pricing(rows, rule())["worst"]
    assert worst[0]["quote_id"] == "XAU"
    assert worst[0]["actual_price"] == 4_000_000


def test_dong_hong_bi_LOAI_chu_khong_lam_sap_ca_lan_chay():
    """
    Hồi quy audit 30/07/2026: `carrier_cost` âm ném ValueError từ compute_quote
    và giết cả lần chạy. Một ô đánh nhầm dấu trừ trong 20 dòng không được phép
    xoá sạch công sức nhập liệu của khách — nhưng cũng không được im lặng.
    """
    rows = perfect_rows(10)
    rows.append(HistoricalQuote(quote_id="AM", carrier_cost=-5_000_000,
                                fuel_price=25_000, actual_price=10_000_000))
    r = replay_pricing(rows, rule())
    assert r["summary"]["rows"] == 10
    assert r["summary"]["rows_dropped"] == 1
    assert r["dropped"][0]["quote_id"] == "AM"
    assert any("bị loại" in w for w in r["warnings"])


@pytest.mark.parametrize("bad,ly_do", [
    (HistoricalQuote(quote_id="A", carrier_cost=10_000_000, actual_price=-1),
     "giá đã chốt"),
    (HistoricalQuote(quote_id="B", carrier_cost=10_000_000, actual_price=0),
     "giá đã chốt"),
    (HistoricalQuote(quote_id="C", carrier_cost=0, actual_price=10_000_000),
     "giá nhà xe"),
    (HistoricalQuote(quote_id="D", carrier_cost=10_000_000, actual_price=10_000_000,
                     fuel_price=-1), "giá dầu"),
])
def test_moi_kieu_du_lieu_vo_ly_deu_bi_loai_kem_ly_do(bad, ly_do):
    r = replay_pricing(perfect_rows(9) + [bad], rule())
    assert r["summary"]["rows_dropped"] == 1
    assert ly_do in r["dropped"][0]["reason"]


def test_toan_dong_hong_thi_khong_no():
    bad = HistoricalQuote(quote_id="X", carrier_cost=-1, actual_price=-1)
    r = replay_pricing([bad], rule())
    assert r["summary"] == {}
    assert any("Không còn dòng hợp lệ" in w for w in r["warnings"])


@pytest.mark.parametrize("n", [2, 3, 4, 10, 17])
def test_p90_luon_nam_o_nua_TREN_cua_phan_bo(n):
    """
    Hồi quy audit 30/07/2026: chỉ số cũ `int(n*0.9)-1` trả về giá trị GẦN NHỎ
    NHẤT khi n bé (n=2 ra min, n=3 ra giá trị giữa). Đúng ngược hướng với lý do
    tồn tại của p90 — nó có mặt để phơi ca tệ ra, không phải để giấu đi.
    """
    rows = perfect_rows(n - 1)
    rows.append(HistoricalQuote(quote_id="XAU", carrier_cost=10_000_000,
                                fuel_price=25_000, actual_price=4_000_000))
    s = replay_pricing(rows, rule())["summary"]
    assert s["p90_abs_dev_pct"] >= s["median_abs_dev_pct"]
    # Ca tệ chiếm hơn 10% mẫu thì p90 phải thấy nó. Từ n=10 trở lên nó chỉ còn
    # <=10% nên p90 bỏ qua là ĐÚNG định nghĩa — lúc đó `max` mới là lớp bảo vệ.
    if n < 10:
        assert s["p90_abs_dev_pct"] == s["max_abs_dev_pct"]
    assert s["max_abs_dev_pct"] == pytest.approx(175.0, abs=1.0)


def test_qua_it_du_lieu_thi_noi_thang():
    r = replay_pricing(perfect_rows(3), rule())
    assert any("chưa đủ vững" in w for w in r["warnings"])


def test_khong_co_du_lieu_thi_khong_no():
    r = replay_pricing([], rule())
    assert r["summary"] == {} and r["warnings"]


def test_phu_phi_duoc_tinh_vao():
    cost, fp = 10_000_000, 25_000
    sur = [Surcharge(name="bốc xếp", amount=500_000)]
    actual = compute_quote(cost, rule(), fp, extra_surcharges=sur)["quote"]["quoted_price"]
    row = HistoricalQuote(quote_id="S1", carrier_cost=cost, fuel_price=fp,
                          actual_price=actual, surcharges=sur)
    assert replay_pricing([row], rule())["summary"]["mape_pct"] == 0.0


# ---------------------------------------------------------------------------
# Khớp tham số — và từ chối khớp khi không nhận dạng được
# ---------------------------------------------------------------------------

def test_tim_lai_duoc_bien_that():
    rows = perfect_rows(14, margin=13.5)
    f = fit_pricing_rule(rows, rule(margin=10.0))
    assert f["fitted"]["base_margin_pct"] == pytest.approx(13.5, abs=0.25)
    assert f["mape_pct_fitted"] < f["mape_pct_current"]


def test_tim_lai_duoc_he_so_dau_khi_gia_dau_co_bien_dong():
    rows = perfect_rows(14, margin=12.0, fuel_sens=0.55)
    f = fit_pricing_rule(rows, rule(margin=10.0, fuel=0.35))
    assert f["fitted"]["fuel_sensitivity_was_fitted"] is True
    assert f["fitted"]["fuel_sensitivity"] == pytest.approx(0.55, abs=0.05)


def test_TU_CHOI_khop_he_so_dau_khi_gia_dau_khong_doi():
    """
    Điểm quan trọng nhất của module. Cùng một giá dầu ở mọi dòng thì mọi
    fuel_sensitivity cho kết quả y hệt — 'giá trị khớp nhất' chỉ là con số
    đầu tiên trong lưới. Trả về nó mà không nói gì là bịa ra bằng chứng.
    """
    rows = perfect_rows(14, margin=12.0, fuel_prices=[25_000])
    f = fit_pricing_rule(rows, rule(margin=10.0, fuel=0.35))
    assert f["fitted"]["fuel_sensitivity_was_fitted"] is False
    assert f["fitted"]["fuel_sensitivity"] == 0.35        # giữ nguyên giả định
    assert any("KHÔNG ước lượng được" in w for w in f["warnings"])


def test_gia_dau_bien_dong_qua_nho_cung_bi_tu_choi():
    rows = perfect_rows(14, margin=12.0, fuel_prices=[25_000, 25_200])  # ~0,8%
    f = fit_pricing_rule(rows, rule())
    assert f["fitted"]["fuel_sensitivity_was_fitted"] is False


def test_bien_van_khop_duoc_du_gia_dau_dung_yen():
    """Không ước lượng được hệ số dầu thì vẫn phải ước lượng được biên."""
    rows = perfect_rows(14, margin=16.0, fuel_prices=[25_000])
    f = fit_pricing_rule(rows, rule(margin=10.0))
    assert f["fitted"]["base_margin_pct"] == pytest.approx(16.0, abs=0.25)


def test_dat_gia_bi_vach_ra():
    """
    Cổng < 5% một mình không đủ. Quan sát khi chạy thử CLI: biên giả định 10%
    trong khi thật là 13,5% vẫn cho MAPE 4,62% -> "ĐẠT", mà hiệu chỉnh còn kéo
    xuống 1,68%. Lọt cổng không có nghĩa là tham số đúng.
    """
    rows = perfect_rows(16, margin=13.5, fuel_sens=0.5)
    current = rule(margin=10.0, fuel=0.35)
    assert replay_pricing(rows, current)["summary"]["passed"] is True   # lọt cổng
    f = fit_pricing_rule(rows, current)
    assert f["gate_false_pass"] is True
    assert any("ĐẠT GIẢ" in w for w in f["warnings"])


def test_khop_dung_roi_thi_khong_bao_dat_gia():
    rows = perfect_rows(14, margin=13.5, fuel_sens=0.5)
    f = fit_pricing_rule(rows, rule(margin=13.5, fuel=0.5))
    assert f["gate_false_pass"] is False


def test_bien_that_ngoai_luoi_thi_canh_bao_ket_mep():
    """
    Hồi quy audit 30/07/2026: lưới cũ dừng ở 30%, biên thật 42% bị kẹt ở mép và
    báo về đúng "30.0" — nghe như đáp án. Giờ lưới rộng tới 60%, và kẹt mép thì
    phải nói ra.
    """
    rows = perfect_rows(12, margin=42.0)
    f = fit_pricing_rule(rows, rule(margin=10.0))
    assert f["fitted"]["base_margin_pct"] == pytest.approx(42.0, abs=0.25)

    # Ép lưới hẹp lại để tái hiện đúng tình huống cũ
    hep = fit_pricing_rule(rows, rule(margin=10.0),
                           margin_grid=[x / 4 for x in range(0, 121)])
    assert hep["fitted"]["base_margin_pct"] == 30.0
    assert any("KẸT Ở MÉP LƯỚI" in w for w in hep["warnings"])


def test_he_so_dau_kich_tran_thi_canh_bao():
    """fuel_sensitivity = 1.0 nghĩa là chuyển toàn bộ biến động dầu sang khách."""
    rows = perfect_rows(14, margin=12.0, fuel_sens=1.0)
    f = fit_pricing_rule(rows, rule(margin=10.0))
    assert f["fitted"]["fuel_sensitivity"] == 1.0
    assert any("kịch trần" in w for w in f["warnings"])


def test_khop_dung_giua_luoi_thi_khong_canh_bao_ket_mep():
    f = fit_pricing_rule(perfect_rows(12, margin=15.0), rule(margin=10.0))
    assert not any("KẸT Ở MÉP" in w for w in f["warnings"])


def test_khop_khong_tot_hon_thi_noi_that():
    """Sai lệch đến từ chỗ khác thì đừng vờ như đã hiệu chỉnh xong."""
    rows = perfect_rows(12, margin=10.0)
    rows[0].actual_price *= 3          # nhiễu không giải thích được bằng biên
    rows[1].actual_price *= 0.4
    f = fit_pricing_rule(rows, rule(margin=10.0))
    assert f["mape_pct_fitted"] > 0


# ---------------------------------------------------------------------------
# Trọng số chọn nhà xe
# ---------------------------------------------------------------------------

def _carrier(cid, price, credit=30, on_time=0.9, discount=5, years=5):
    return Carrier(id=cid, name=f"Nhà xe {cid}", vehicle_types={"xe tải 5 tấn"},
                   credit_days=credit, on_time_rate=on_time,
                   discount_pct=discount, years_partner=years), \
        QuoteOffer(carrier_id=cid, price=price)


def _case(case_id, chosen, a_kw=None, b_kw=None):
    ca, oa = _carrier("A", 10_000_000, **(a_kw or {}))
    cb, ob = _carrier("B", 11_000_000, **(b_kw or {}))
    return CarrierChoiceCase(
        case_id=case_id,
        request=RouteRequest(origin="HN", destination="DN", vehicle_type="xe tải 5 tấn"),
        carriers=[ca, cb], offers=[oa, ob], chosen_carrier_id=chosen,
    )


def test_trong_so_hien_tai_chon_dung_thi_bao_dung():
    cases = [_case(f"C{i}", "A") for i in range(10)]
    s = replay_carrier_choices(cases)["summary"]
    assert s["top1_accuracy_pct"] == 100.0


def test_ca_chon_sai_duoc_mo_xe_thua_o_tieu_chi_nao():
    """Khách chọn bên đắt hơn -> phải chỉ ra bên đó thua ở 'giá chào'."""
    cases = [_case("C1", "B")]
    miss = [c for c in replay_carrier_choices(cases)["cases"] if not c["khớp"]]
    assert miss and miss[0]["khách_chọn"] == "B"
    assert any(g["criterion"] == "price" for g in miss[0]["thua_ở"])


def test_canh_bao_ca_sat_nut():
    """Hai nhà xe giống hệt nhau, chỉ chênh 1% giá -> chênh điểm dưới 0,05."""
    ca, oa = _carrier("A", 10_000_000)
    cb, _ = _carrier("B", 10_000_000)
    ob = QuoteOffer(carrier_id="B", price=10_100_000)
    case = CarrierChoiceCase(
        case_id="SATNUT",
        request=RouteRequest(origin="HN", destination="DN", vehicle_type="xe tải 5 tấn"),
        carriers=[ca, cb], offers=[oa, ob], chosen_carrier_id="B")
    r = replay_carrier_choices([case])
    assert r["cases"][0]["is_close_call"] is True
    assert any("sát nút" in w for w in r["warnings"])


def test_ca_chi_co_MOT_nha_xe_khong_duoc_tinh_vao_do_tin_cay():
    """
    Hồi quy audit 30/07/2026: 10 ca chỉ có một ứng viên cho 100% độ chính xác
    mà không học được gì — không có bên thứ hai thì không có thông tin nào về
    trọng số cả.
    """
    c, o = _carrier("A", 1_000_000)
    solo = CarrierChoiceCase(
        case_id="SOLO",
        request=RouteRequest(origin="HN", destination="DN", vehicle_type="xe tải 5 tấn"),
        carriers=[c], offers=[o], chosen_carrier_id="A")
    r = replay_carrier_choices([solo] * 10)
    assert r["summary"]["top1_accuracy_pct"] == 100.0        # con số ngây thơ
    assert r["summary"]["informative_cases"] == 0            # sự thật
    assert r["summary"]["top1_accuracy_informative_pct"] is None
    assert any("chỉ có MỘT nhà xe" in w for w in r["warnings"])
    assert any("KHÔNG ca nào" in w for w in r["warnings"])


def test_do_chinh_xac_dang_tin_chi_dem_ca_co_tu_2_ung_vien():
    c, o = _carrier("A", 1_000_000)
    solo = CarrierChoiceCase(
        case_id="SOLO",
        request=RouteRequest(origin="HN", destination="DN", vehicle_type="xe tải 5 tấn"),
        carriers=[c], offers=[o], chosen_carrier_id="A")
    cases = [solo] * 8 + [_case("C1", "B")]     # ca thật duy nhất thì engine chọn sai
    s = replay_carrier_choices(cases)["summary"]
    assert s["top1_accuracy_pct"] == pytest.approx(88.9, abs=0.2)   # nghe rất đẹp
    assert s["informative_cases"] == 1
    assert s["top1_accuracy_informative_pct"] == 0.0               # sự thật


def test_khop_trong_so_khong_duoc_roi_gia_dinh_qua_xa():
    cases = [_case(f"C{i}", "B", b_kw={"credit": 45}) for i in range(10)]
    f = fit_carrier_weights(cases, max_shift=0.10)
    for name, value in f["fitted"].items():
        assert abs(value - DEFAULT_WEIGHTS[name]) <= 0.10 + 1e-6


def test_bao_ca_do_chinh_xac_trong_mau_lan_kiem_cheo():
    cases = [_case(f"C{i}", "A") for i in range(9)]
    f = fit_carrier_weights(cases)
    assert "accuracy_in_sample_pct" in f and "accuracy_loo_pct" in f


def test_kiem_cheo_bo_mot_la_that_chu_khong_phai_copy_so_trong_mau():
    """
    Với rounds=0 thì không leo đồi, mọi lần khớp đều trả về đúng base -> hai con
    số phải BẰNG nhau. Đây là phép thử máy móc của LOO: nếu nó chỉ chép lại độ
    chính xác trong mẫu thì test kia (dữ liệu mâu thuẫn) cũng không phát hiện ra.
    """
    cases = [_case(f"C{i}", "A" if i % 2 else "B") for i in range(10)]
    f = fit_carrier_weights(cases, rounds=0)
    assert f["moved"] == {}
    assert f["accuracy_loo_pct"] == f["accuracy_in_sample_pct"]


def test_du_lieu_mau_thuan_thi_khong_the_dat_do_chinh_xac_cao():
    """Cùng cấu hình nhưng lựa chọn ngược nhau — không bộ trọng số nào giải được."""
    cases = [_case(f"C{i}", "A" if i % 2 else "B") for i in range(10)]
    f = fit_carrier_weights(cases)
    assert f["accuracy_in_sample_pct"] <= 60.0
    gap = f["accuracy_in_sample_pct"] - f["accuracy_loo_pct"]
    assert gap < 15 or any("HỌC THUỘC" in w for w in f["warnings"])


def test_qua_it_ca_thi_canh_bao():
    f = fit_carrier_weights([_case("C1", "A")])
    assert any("quá ít" in w for w in f["warnings"])


def test_khong_co_ca_nao_thi_khong_no():
    assert fit_carrier_weights([])["fitted"] is None
    assert replay_carrier_choices([])["warnings"]


# ---------------------------------------------------------------------------
# Cổng ra Giai đoạn 0
# ---------------------------------------------------------------------------

def test_cong_ra_dung_5_phan_tram():
    assert GATE_MAPE_PCT == 5.0


def test_dung_dung_engine_production_khong_viet_lai_cong_thuc():
    """
    P4: nếu calibration tự tính giá theo công thức riêng thì ta đang hiệu chỉnh
    một engine KHÁC với engine chạy thật — vô nghĩa.
    """
    cost, fp = 15_000_000, 26_000
    expected = compute_quote(cost, rule(), fp)["quote"]["quoted_price"]
    row = HistoricalQuote(quote_id="X", carrier_cost=cost, fuel_price=fp,
                          actual_price=expected)
    assert replay_pricing([row], rule())["rows"][0]["predicted_price"] == expected
