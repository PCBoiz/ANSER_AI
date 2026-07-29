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
    cases = [_case("C1", "B", b_kw={"credit": 45, "on_time": 0.99, "discount": 20})]
    r = replay_carrier_choices(cases)
    assert any("sát nút" in w for w in r["warnings"]) or r["cases"][0]["khớp"]


def test_khop_trong_so_khong_duoc_roi_gia_dinh_qua_xa():
    cases = [_case(f"C{i}", "B", b_kw={"credit": 45}) for i in range(10)]
    f = fit_carrier_weights(cases, max_shift=0.10)
    for name, value in f["fitted"].items():
        assert abs(value - DEFAULT_WEIGHTS[name]) <= 0.10 + 1e-6


def test_bao_ca_do_chinh_xac_trong_mau_lan_kiem_cheo():
    cases = [_case(f"C{i}", "A") for i in range(9)]
    f = fit_carrier_weights(cases)
    assert "accuracy_in_sample_pct" in f and "accuracy_loo_pct" in f


def test_canh_bao_khi_khop_qua_khit():
    """Trong mẫu cao mà kiểm chéo thấp = học thuộc, không phải hiểu quy tắc."""
    # Các ca mâu thuẫn nhau: cùng cấu hình nhưng lựa chọn ngược nhau.
    cases = [_case(f"C{i}", "A" if i % 2 else "B") for i in range(10)]
    f = fit_carrier_weights(cases)
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
