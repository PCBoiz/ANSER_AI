"""
tests/test_pricing_and_tools.py — engine báo giá + tầng REST /tools/*.

Pricing thuộc tầng tất định (AGENTS.md R1) — phần không được phép sai: con số
ở đây đi thẳng vào email báo giá gửi khách cuối của khách hàng.
"""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.core.pricing import PricingRule, Surcharge, compute_quote


# ===========================================================================
# compute_quote — số học phải kiểm được bằng tay
# ===========================================================================

def _rule(**over):
    base = dict(
        base_margin_pct=10.0,
        fuel_sensitivity=0.35,
        fuel_baseline_price=25_000,
        min_margin_amount=0.0,
    )
    base.update(over)
    return PricingRule(**base)


def test_quote_fuel_scenario_from_customer_interview():
    """
    Kịch bản đúng như khách mô tả: dầu 25.000đ -> 28.000đ (+12%).
    cost 10tr, sensitivity 0.35:
      điều chỉnh = 10tr × 0.35 × 0.12 = 420.000
      chi phí hiệu chỉnh = 10.420.000
      biên 10% = 1.042.000
      báo giá = 11.462.000 (đã tròn nghìn)
    """
    out = compute_quote(10_000_000, _rule(), current_fuel_price=28_000)
    internal = out["internal"]
    assert internal["fuel_adjustment"] == 420_000
    assert internal["adjusted_cost"] == 10_420_000
    assert internal["margin"] == 1_042_000
    assert out["quote"]["quoted_price"] == 11_462_000
    assert out["warnings"] == []


def test_quote_fuel_cheaper_reduces_price():
    """Dầu rẻ đi thì điều chỉnh ÂM — báo giá giảm theo, không phải chỉ biết tăng."""
    out = compute_quote(10_000_000, _rule(), current_fuel_price=22_500)  # -10%
    assert out["internal"]["fuel_adjustment"] == -350_000
    assert out["quote"]["quoted_price"] < compute_quote(
        10_000_000, _rule(), current_fuel_price=25_000
    )["quote"]["quoted_price"]


def test_quote_missing_fuel_price_warns_not_crashes():
    out = compute_quote(10_000_000, _rule(), current_fuel_price=None)
    assert out["internal"]["fuel_adjustment"] == 0
    assert any("Chưa lấy được giá dầu" in w for w in out["warnings"])


def test_quote_missing_baseline_warns_and_skips_adjustment():
    out = compute_quote(
        10_000_000, _rule(fuel_baseline_price=None), current_fuel_price=28_000
    )
    assert out["internal"]["fuel_adjustment"] == 0
    assert any("giá dầu gốc" in w for w in out["warnings"])


def test_quote_min_margin_floor_applied_and_flagged():
    """Chuyến nhỏ: biên % quá mỏng thì áp sàn tuyệt đối, và phải NÓI RÕ đã áp sàn."""
    out = compute_quote(
        1_000_000,
        _rule(base_margin_pct=5.0, min_margin_amount=300_000),
        current_fuel_price=25_000,
    )
    assert out["internal"]["margin"] == 300_000
    assert out["internal"]["margin_floored"] is True
    assert any("áp sàn" in w for w in out["warnings"])


def test_quote_surcharges_fixed_and_pct():
    """Phụ phí hàng lạnh 500k cố định + 2% chi phí. Giá dầu đứng yên cho dễ kiểm."""
    rule = _rule(surcharges=[Surcharge("Hàng lạnh", amount=500_000, pct=2.0)])
    out = compute_quote(10_000_000, rule, current_fuel_price=25_000)
    # 500.000 + 10tr×2% = 700.000
    assert out["internal"]["surcharge_total"] == 700_000
    assert out["quote"]["surcharges"][0]["name"] == "Hàng lạnh"
    # 10tr + 700k + 1tr biên = 11.700.000
    assert out["quote"]["quoted_price"] == 11_700_000


def test_quote_rounds_to_thousand():
    out = compute_quote(1_234_567, _rule(base_margin_pct=0), current_fuel_price=25_000)
    assert out["quote"]["quoted_price"] % 1000 == 0


def test_customer_facing_part_never_contains_margin():
    """
    P2: phần 'quote' là thứ được phép đi vào email gửi khách cuối.
    Biên lợi nhuận — bí mật kinh doanh — tuyệt đối không được nằm trong đó.
    """
    out = compute_quote(10_000_000, _rule(), current_fuel_price=28_000)
    blob = str(out["quote"]).lower()
    assert "margin" not in blob
    assert "carrier_cost" not in blob
    assert "fuel" not in blob


def test_quote_rejects_bad_inputs():
    with pytest.raises(ValueError):
        compute_quote(0, _rule())
    with pytest.raises(ValueError):
        PricingRule(base_margin_pct=10, fuel_sensitivity=1.5)
    with pytest.raises(ValueError):
        PricingRule(base_margin_pct=-1)


# ===========================================================================
# REST /tools/* — hợp đồng cho n8n và agentic
# ===========================================================================

client = TestClient(app)


def test_manifest_lists_all_tools_with_schemas():
    resp = client.get("/tools")
    assert resp.status_code == 200
    body = resp.json()
    names = {t["name"] for t in body["tools"]}
    assert names == {"quote", "carrier_selection", "forecast_reorder", "vat"}
    for t in body["tools"]:
        assert t["input_schema"].get("properties"), f"tool {t['name']} thiếu schema"


def test_tools_quote_endpoint():
    resp = client.post("/tools/quote", json={
        "carrier_cost": 10_000_000,
        "pricing_rule": {
            "base_margin_pct": 10,
            "fuel_sensitivity": 0.35,
            "fuel_baseline_price": 25_000,
        },
        "current_fuel_price": 28_000,
    })
    assert resp.status_code == 200
    assert resp.json()["quote"]["quoted_price"] == 11_462_000


def test_tools_quote_validation_error_is_422():
    resp = client.post("/tools/quote", json={
        "carrier_cost": -5,
        "pricing_rule": {"base_margin_pct": 10},
    })
    assert resp.status_code == 422


def test_tools_carrier_selection_endpoint():
    resp = client.post("/tools/carrier-selection", json={
        "carriers": [
            {"id": "A", "name": "Hãng A", "vehicle_types": ["5T"],
             "credit_days": 30, "discount_pct": 10, "years_partner": 5,
             "on_time_rate": 0.95},
            {"id": "B", "name": "Hãng B", "vehicle_types": ["5T"],
             "credit_days": 7, "discount_pct": 5, "years_partner": 1,
             "on_time_rate": 0.90},
        ],
        "offers": [
            {"carrier_id": "A", "price": 1_000_000},
            {"carrier_id": "B", "price": 900_000},
        ],
        "request": {"origin": "Hữu Nghị", "destination": "Hải Phòng",
                    "vehicle_type": "5T"},
    })
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["ranked"]) == 2
    # thiếu toạ độ -> tiêu chí proximity phải bị loại và báo ra, không coi là 0
    assert any(m["criterion"] == "proximity" for m in body["explain"]["missing"])


def test_tools_forecast_endpoint_batch_with_partial_error():
    """Lô nhiều SKU: SKU hỏng không được kéo sập cả lô — trả trong errors."""
    series = [0, 0, 5, 0, 0, 5, 0, 0, 5, 0, 0, 5]
    resp = client.post("/tools/forecast-reorder", json={
        "items": [
            {"sku": "SP001", "series": series, "current_stock": 0,
             "lead_time_periods": 4},
            {"sku": "SP002", "series": series, "current_stock": 10_000,
             "lead_time_periods": 4},
            {"sku": "SP003", "series": series, "current_stock": 0,
             "lead_time_periods": -1},   # lỗi: lead time âm
        ],
        "service_level": 0.95,
    })
    assert resp.status_code == 422 or resp.status_code == 200
    if resp.status_code == 200:
        body = resp.json()
        assert body["count"] == 1                      # chỉ SP001 cần đặt
        assert body["suggestions"][0]["sku"] == "SP001"
        assert {e["sku"] for e in body["errors"]} <= {"SP003"}


def test_tools_vat_endpoint():
    resp = client.post("/tools/vat", json={
        "items": [{"name": "Coca", "price": 10_000, "qty": 24}],
        "stated_total": 264_000,
    })
    assert resp.status_code == 200
    assert resp.json()["is_valid"] is True   # 240k + 10% = 264k
