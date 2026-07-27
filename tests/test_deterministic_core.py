"""
tests/test_deterministic_core.py — kiểm thử TẦNG TẤT ĐỊNH.

Theo AGENTS.md R1, đây là phần KHÔNG ĐƯỢC PHÉP SAI: mọi con số chạm sổ sách, báo
giá và quyết định nhập hàng đều đi qua các module này, và LLM không được sửa chúng.

Chạy: pytest tests/test_deterministic_core.py -v
"""

import math

import pytest

from src.core import workflow_schema as ws
from src.core.carrier_selection import (
    Carrier, QuoteOffer, RouteRequest, haversine_km, select_carrier,
)
from src.core.forecasting import (
    classify_demand, croston, forecast_demand, mase, reorder_point,
)


# ===========================================================================
# workflow_schema — định dạng n8n
# ===========================================================================

def _good_workflow() -> dict:
    return {
        "action": "create_workflow",
        "name": "Cảnh báo tồn kho",
        "payload": {
            "nodes": [
                {
                    "name": "Mỗi 4 tiếng",
                    "type": "n8n-nodes-base.scheduleTrigger",
                    "typeVersion": 1.2,
                    "position": [0, 0],
                    "parameters": {},
                },
                {
                    "name": "Gọi API",
                    "type": "n8n-nodes-base.httpRequest",
                    "typeVersion": 4.2,
                    "position": [220, 0],
                    "parameters": {"url": "https://x/y", "method": "GET"},
                },
            ],
            "connections": {
                "Mỗi 4 tiếng": {"main": [[{"node": "Gọi API", "type": "main", "index": 0}]]}
            },
        },
    }


def test_valid_workflow_passes():
    ok, err = ws.validate_workflow(_good_workflow())
    assert ok, err


def test_few_shot_example_passes_its_own_validator():
    """
    Ví dụ ta DẠY model phải qua được lớp ta KIỂM. Nếu không, model học đúng theo
    ví dụ vẫn bị loại — đây chính là lớp lỗi mà workflow_schema sinh ra để diệt.
    """
    import json
    for example in ws._active()[1]:
        ok, err = ws.validate_workflow(example)
        assert ok, f"few-shot không qua validator: {err}"
        json.dumps(example, ensure_ascii=False)   # phải serialise được


def test_reject_duplicate_node_name():
    wf = _good_workflow()
    wf["payload"]["nodes"][1]["name"] = "Mỗi 4 tiếng"
    ok, err = ws.validate_workflow(wf)
    assert not ok and "trùng tên" in err


def test_reject_unknown_node_type():
    wf = _good_workflow()
    wf["payload"]["nodes"][1]["type"] = "n8n-nodes-base.doesNotExist"
    ok, err = ws.validate_workflow(wf)
    assert not ok and "không được phép" in err


def test_reject_code_node_even_if_requested():
    """Node code chạy JS tuỳ ý -> vượt qua mọi luật an toàn ở tầng trên."""
    wf = _good_workflow()
    wf["payload"]["nodes"][1]["type"] = "n8n-nodes-base.code"
    ok, err = ws.validate_workflow(wf)
    assert not ok and "bị chặn" in err


def test_reject_write_sql():
    wf = _good_workflow()
    wf["payload"]["nodes"][1] = {
        "name": "Xoá hàng",
        "type": "n8n-nodes-base.postgres",
        "typeVersion": 2.4,
        "position": [220, 0],
        "parameters": {"query": "DELETE FROM products WHERE id = 1"},
    }
    ok, err = ws.validate_workflow(wf)
    assert not ok and "ghi dữ liệu" in err


def test_reject_no_trigger():
    wf = _good_workflow()
    wf["payload"]["nodes"][0]["type"] = "n8n-nodes-base.httpRequest"
    wf["payload"]["nodes"][0]["typeVersion"] = 4.2
    ok, err = ws.validate_workflow(wf)
    assert not ok and "trigger" in err


def test_reject_two_triggers():
    wf = _good_workflow()
    wf["payload"]["nodes"][1]["type"] = "n8n-nodes-base.webhook"
    wf["payload"]["nodes"][1]["typeVersion"] = 2
    ok, err = ws.validate_workflow(wf)
    assert not ok and "2 node trigger" in err


def test_reject_connection_to_missing_node():
    wf = _good_workflow()
    wf["payload"]["connections"]["Mỗi 4 tiếng"]["main"][0][0]["node"] = "Không tồn tại"
    ok, err = ws.validate_workflow(wf)
    assert not ok and "không tồn tại" in err


def test_reject_orphan_node():
    wf = _good_workflow()
    wf["payload"]["nodes"].append({
        "name": "Mồ côi",
        "type": "n8n-nodes-base.noOp",
        "typeVersion": 1,
        "position": [440, 0],
        "parameters": {},
    })
    ok, err = ws.validate_workflow(wf)
    assert not ok and "không được nối" in err


def test_reject_edges_format_from_old_prompt():
    """
    Bản prompt cũ dạy "edges":[{from,to}] — KHÔNG PHẢI n8n. Workflow sinh theo
    bản cũ phải bị loại, nếu không nó lọt xuống Body rồi n8n từ chối import.
    """
    wf = _good_workflow()
    payload = wf["payload"]
    payload.pop("connections")
    payload["edges"] = [{"from": "Mỗi 4 tiếng", "to": "Gọi API"}]
    ok, err = ws.validate_workflow(wf)
    assert not ok


def test_json_schema_enum_matches_catalog():
    """guided_json và validate phải nhìn cùng một danh sách node."""
    schema = ws.build_workflow_schema()
    enum = schema["properties"]["payload"]["properties"]["nodes"]["items"]["properties"]["type"]["enum"]
    assert sorted(enum) == ws.allowed_types()


def test_catalog_loading_from_real_templates(tmp_path, monkeypatch):
    """Khi Body merge vào, catalog phải rút từ template thật chứ không dùng bản dự phòng."""
    import json
    (tmp_path / "demo.json").write_text(json.dumps({
        "name": "Demo",
        "nodes": [
            {"name": "T", "type": "n8n-nodes-base.scheduleTrigger",
             "typeVersion": 9.9, "position": [0, 0], "parameters": {}},
            {"name": "H", "type": "n8n-nodes-base.httpRequest",
             "typeVersion": 5.0, "position": [1, 0], "parameters": {"url": "u"}},
        ],
        "connections": {"T": {"main": [[{"node": "H", "type": "main", "index": 0}]]}},
    }), encoding="utf-8")

    monkeypatch.setenv("N8N_TEMPLATES_DIR", str(tmp_path))
    ws.reload_catalog()
    try:
        assert ws.is_using_real_templates()
        catalog = ws.get_node_catalog()
        # typeVersion phải lấy từ template thật, không phải hằng số ta bịa
        assert catalog["n8n-nodes-base.httpRequest"]["typeVersion"] == 5.0
        assert catalog["n8n-nodes-base.scheduleTrigger"]["trigger"] is True
    finally:
        monkeypatch.delenv("N8N_TEMPLATES_DIR", raising=False)
        ws.reload_catalog()


def test_blocked_nodes_never_enter_catalog(tmp_path, monkeypatch):
    import json
    (tmp_path / "risky.json").write_text(json.dumps({
        "name": "Risky",
        "nodes": [
            {"name": "T", "type": "n8n-nodes-base.scheduleTrigger",
             "typeVersion": 1.2, "position": [0, 0], "parameters": {}},
            {"name": "C", "type": "n8n-nodes-base.code",
             "typeVersion": 2, "position": [1, 0], "parameters": {"jsCode": "x"}},
        ],
        "connections": {},
    }), encoding="utf-8")

    monkeypatch.setenv("N8N_TEMPLATES_DIR", str(tmp_path))
    ws.reload_catalog()
    try:
        assert "n8n-nodes-base.code" not in ws.get_node_catalog()
    finally:
        monkeypatch.delenv("N8N_TEMPLATES_DIR", raising=False)
        ws.reload_catalog()


# ===========================================================================
# carrier_selection — chọn hãng xe
# ===========================================================================

def _carrier_a() -> Carrier:
    return Carrier(
        id="A", name="Hãng A", vehicle_types={"5T"},
        depot_lat=21.000, depot_lon=105.850,      # ~5km từ điểm lấy hàng
        discount_pct=10, credit_days=30, years_partner=5, on_time_rate=0.95,
    )


def _carrier_b() -> Carrier:
    return Carrier(
        id="B", name="Hãng B", vehicle_types={"5T"},
        depot_lat=21.400, depot_lon=105.850,      # ~44km
        discount_pct=5, credit_days=7, years_partner=1, on_time_rate=0.90,
    )


def _request() -> RouteRequest:
    return RouteRequest(
        origin="Hữu Nghị", destination="Hải Phòng", vehicle_type="5T",
        origin_lat=21.045, origin_lon=105.850,
    )


def test_relationship_beats_slightly_cheaper_price():
    """
    Hãng A đắt hơn ~11% nhưng gần hơn nhiều, cho nợ 30 ngày thay vì 7, giao đúng
    hẹn tốt hơn. Đây chính là điều khách mô tả: quan hệ lâu năm đáng giá hơn vài
    phần trăm giá.
    """
    result = select_carrier(
        [_carrier_a(), _carrier_b()],
        [QuoteOffer("A", 1_000_000), QuoteOffer("B", 900_000)],
        _request(),
    )
    assert result["ranked"][0]["carrier_id"] == "A"


def test_price_normalization_preserves_magnitude():
    """
    Chuẩn hoá giá theo TỶ LỆ, không phải min-max. Chênh 2% phải cho điểm gần
    nhau; min-max sẽ cho 1.0 và 0.0 bất kể chênh bao nhiêu.
    """
    result = select_carrier(
        [_carrier_a(), _carrier_b()],
        [QuoteOffer("A", 1_000_000), QuoteOffer("B", 980_000)],
        _request(),
    )
    prices = {
        r["carrier_id"]: next(c for c in r["criteria"] if c["criterion"] == "price")
        for r in result["ranked"]
    }
    assert prices["B"]["normalized"] == pytest.approx(1.0)
    assert prices["A"]["normalized"] == pytest.approx(0.98, abs=0.005)


def test_wrong_vehicle_type_is_excluded_not_penalised():
    """Ràng buộc cứng: không có xe phù hợp thì LOẠI, dù mọi tiêu chí khác đều tốt."""
    a = _carrier_a()
    a.vehicle_types = {"1.5T"}
    result = select_carrier(
        [a, _carrier_b()],
        [QuoteOffer("A", 1), QuoteOffer("B", 900_000)],
        _request(),
    )
    assert [r["carrier_id"] for r in result["ranked"]] == ["B"]
    assert result["rejected"][0]["carrier_id"] == "A"
    assert "không có xe 5T" in result["rejected"][0]["reason"]


def test_carrier_without_offer_is_excluded():
    result = select_carrier(
        [_carrier_a(), _carrier_b()], [QuoteOffer("A", 1_000_000)], _request()
    )
    assert [r["carrier_id"] for r in result["ranked"]] == ["A"]
    assert "chưa có giá chào" in result["rejected"][0]["reason"]


def test_missing_criterion_is_dropped_not_treated_as_zero():
    """
    Hãng thiếu on_time_rate KHÔNG được coi như đúng hẹn 0%. Tiêu chí đó phải bị
    loại khỏi phép tính cho CẢ NHÓM và được báo ra.
    """
    b = _carrier_b()
    b.on_time_rate = None
    result = select_carrier(
        [_carrier_a(), b],
        [QuoteOffer("A", 1_000_000), QuoteOffer("B", 900_000)],
        _request(),
    )
    used = result["explain"]["weights_used"]
    assert "reliability" not in used
    assert any(m["criterion"] == "reliability" for m in result["explain"]["missing"])
    # Trọng số còn lại phải được chuẩn hoá về tổng 1.
    # Dung sai 1e-3 vì output làm tròn 4 chữ số thập phân cho dễ đọc.
    assert sum(used.values()) == pytest.approx(1.0, abs=1e-3)


def test_close_call_is_flagged():
    """Hai hãng ngang nhau -> phải nói rõ, không đưa khuyến nghị nghe chắc nịch."""
    a, b = _carrier_a(), _carrier_b()
    b.depot_lat, b.depot_lon = a.depot_lat, a.depot_lon
    b.discount_pct, b.credit_days = a.discount_pct, a.credit_days
    b.years_partner, b.on_time_rate = a.years_partner, a.on_time_rate
    result = select_carrier(
        [a, b], [QuoteOffer("A", 1_000_000), QuoteOffer("B", 995_000)], _request()
    )
    assert result["explain"]["is_close_call"] is True


def test_contributions_sum_to_total_score():
    """XAI: mọi con số LLM nói ra phải truy ngược được. Tổng đóng góp = điểm tổng."""
    result = select_carrier(
        [_carrier_a(), _carrier_b()],
        [QuoteOffer("A", 1_000_000), QuoteOffer("B", 900_000)],
        _request(),
    )
    for row in result["ranked"]:
        assert sum(c["contribution"] for c in row["criteria"]) == pytest.approx(
            row["total_score"], abs=1e-3
        )


def test_no_eligible_carrier_returns_empty_not_crash():
    result = select_carrier([], [], _request())
    assert result["ranked"] == []
    assert "Không có hãng xe nào" in result["explain"]["note"]


def test_haversine_known_distance():
    # Hà Nội -> Hải Phòng, khoảng 100km đường chim bay
    d = haversine_km(21.0278, 105.8342, 20.8449, 106.6881)
    assert 85 < d < 105


# ===========================================================================
# forecasting — Croston / SBA / reorder point
# ===========================================================================

def test_classify_intermittent():
    p = classify_demand([0, 0, 5, 0, 0, 5, 0, 0, 5])
    assert p.pattern == "intermittent"
    assert p.adi == pytest.approx(3.0)


def test_classify_smooth():
    assert classify_demand([10, 12, 11, 13, 10, 12]).pattern == "smooth"


def test_classify_lumpy():
    # ADI = 3 (gián đoạn) VÀ lượng dao động cực mạnh 200/1/5/150 -> CV² > 0.49.
    # Lưu ý: [100, 1, 50] cho CV² ≈ 0.42, vẫn dưới ngưỡng -> chỉ là "intermittent".
    # Ranh giới lumpy hẹp hơn trực giác, nên chọn dữ liệu test có chủ đích.
    assert classify_demand([0, 0, 200, 0, 0, 1, 0, 0, 5, 0, 0, 150]).pattern == "lumpy"


def test_classify_erratic():
    assert classify_demand([10, 1, 50, 2, 30, 3]).pattern == "erratic"


def test_classify_no_demand():
    p = classify_demand([0, 0, 0, 0])
    assert p.pattern == "no_demand" and p.adi is None


def test_croston_regular_intermittent_series():
    """Nhu cầu 5 đơn vị đều đặn mỗi 3 kỳ -> kỳ vọng 5/3 mỗi kỳ."""
    series = [0, 0, 5, 0, 0, 5, 0, 0, 5]
    assert croston(series, alpha=0.1, variant="classic") == pytest.approx(5 / 3, abs=1e-6)


def test_sba_corrects_croston_upward_bias():
    """SBA = Croston * (1 - alpha/2). Croston gốc ước lượng dư 15-20%."""
    series = [0, 0, 5, 0, 0, 5, 0, 0, 5]
    alpha = 0.1
    classic = croston(series, alpha=alpha, variant="classic")
    sba = croston(series, alpha=alpha, variant="sba")
    assert sba == pytest.approx(classic * (1 - alpha / 2), abs=1e-9)
    assert sba < classic


def test_croston_all_zeros_returns_zero():
    assert croston([0, 0, 0, 0]) == 0.0


def test_croston_rejects_bad_alpha():
    with pytest.raises(ValueError):
        croston([0, 1, 0], alpha=0)
    with pytest.raises(ValueError):
        croston([0, 1, 0], alpha=1)


def test_mase_perfect_forecast_is_zero():
    assert mase([1, 2, 3, 4], [1, 2, 3, 4]) == 0.0


def test_mase_undefined_on_flat_series():
    """Chuỗi phẳng -> dự báo ngây thơ sai số 0 -> MASE chia cho 0, không định nghĩa."""
    assert mase([5, 5, 5, 5], [4, 4, 4, 4]) is None


def test_forecast_smooth_uses_moving_average_not_croston():
    r = forecast_demand([10, 12, 11, 13, 10, 12, 11, 12, 10, 11, 12, 13])
    assert r.method == "moving_average"
    assert r.confidence == "cao"


def test_forecast_lumpy_is_low_confidence_with_warning():
    r = forecast_demand([0, 0, 200, 0, 0, 1, 0, 0, 5, 0, 0, 150])
    assert r.profile.pattern == "lumpy"
    assert r.confidence == "thấp"
    assert any("tồn an toàn" in w for w in r.warnings)


def test_forecast_short_history_flagged():
    r = forecast_demand([0, 5, 0, 5])
    assert r.confidence == "thấp"
    assert any("12 kỳ" in w for w in r.warnings)


def test_forecast_no_demand():
    r = forecast_demand([0] * 12)
    assert r.per_period == 0.0 and r.method == "none"


def test_reorder_point_formula():
    """ROP = nhu cầu trong thời gian chờ + tồn an toàn. Kiểm từng thành phần."""
    series = [0, 0, 5, 0, 0, 5, 0, 0, 5, 0, 0, 5]
    out = reorder_point(series, lead_time_periods=4, service_level=0.95)

    assert out["lead_time_demand"] == pytest.approx(out["demand_per_period"] * 4, abs=0.01)
    expected_ss = 1.6449 * out["demand_std_per_period"] * math.sqrt(4)
    assert out["safety_stock"] == pytest.approx(expected_ss, abs=0.01)
    assert out["reorder_point"] == pytest.approx(
        out["lead_time_demand"] + out["safety_stock"], abs=0.01
    )


def test_reorder_point_suggests_order_when_below():
    series = [0, 0, 5, 0, 0, 5, 0, 0, 5, 0, 0, 5]
    out = reorder_point(series, lead_time_periods=4, current_stock=0)
    assert out["should_order"] is True
    assert out["suggested_qty"] > 0


def test_reorder_point_no_order_when_stocked():
    series = [0, 0, 5, 0, 0, 5, 0, 0, 5, 0, 0, 5]
    out = reorder_point(series, lead_time_periods=4, current_stock=10_000)
    assert out["should_order"] is False
    assert out["suggested_qty"] == 0.0


def test_higher_service_level_raises_safety_stock():
    series = [0, 0, 5, 0, 0, 5, 0, 0, 5, 0, 0, 5]
    low = reorder_point(series, lead_time_periods=4, service_level=0.90)
    high = reorder_point(series, lead_time_periods=4, service_level=0.99)
    assert high["safety_stock"] > low["safety_stock"]


def test_review_period_increases_reorder_point():
    """Chỉ xem xét đặt hàng mỗi tuần -> phải phòng thêm nhu cầu phát sinh trong tuần đó."""
    series = [0, 0, 5, 0, 0, 5, 0, 0, 5, 0, 0, 5]
    continuous = reorder_point(series, lead_time_periods=4, review_periods=0)
    periodic = reorder_point(series, lead_time_periods=4, review_periods=7)
    assert periodic["reorder_point"] > continuous["reorder_point"]


def test_reorder_point_rejects_unknown_service_level():
    with pytest.raises(ValueError):
        reorder_point([1, 2, 3], lead_time_periods=1, service_level=0.777)


def test_reorder_point_carries_explanation_fields():
    """LLM phải có đủ dữ liệu để diễn giải mà không cần tự suy ra con số nào."""
    out = reorder_point([0, 0, 5, 0, 0, 5, 0, 0, 5, 0, 0, 5], lead_time_periods=4)
    for key in ("method", "confidence", "pattern_vi", "adi", "cv2", "n_periods"):
        assert key in out["forecast"]
