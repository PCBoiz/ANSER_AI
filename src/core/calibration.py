"""
src/core/calibration.py — đối chiếu engine với giá khách ĐÃ CHỐT trong quá khứ.

VÌ SAO ĐÂY LÀ VIỆC ĐẦU TIÊN, TRƯỚC MỌI THỨ KHÁC
------------------------------------------------
`PricingRule.fuel_sensitivity = 0.35` và `DEFAULT_WEIGHTS` là GIẢ ĐỊNH đọc từ
bản ghi phỏng vấn, chưa một con số thật nào chạy qua. Fine-tune giỏi mấy cũng
không cứu được một công thức giá sai: model sẽ học cách gọi tool rất thuần
thục để trả về một con số sai.

Nếu công thức sai mà phát hiện ở tuần 10 thì mất toàn bộ dữ liệu đo, toàn bộ
lần fine-tune, và niềm tin của khách. Cùng sai lầm đó phát hiện ở tuần 1 chỉ
tốn một buổi ngồi với khách.

CÁCH LÀM
--------
Lấy 15-20 báo giá khách ĐÃ GỬI và ĐÃ CHỐT, chạy ngược qua chính `compute_quote`
của production (P4 — không viết lại công thức ở đây, sai lệch giữa hai bản là
tự lừa mình), rồi đo sai lệch. Cổng ra: sai lệch tuyệt đối trung bình < 5%.

BA CÁCH TỰ LỪA MÌNH MÀ MODULE NÀY TỪ CHỐI
------------------------------------------
1. Khớp tham số không nhận dạng được. Muốn ước lượng `fuel_sensitivity` thì giá
   dầu trong dữ liệu PHẢI biến động. Toàn bộ 20 chuyến cùng một giá dầu thì mọi
   giá trị 0..1 đều cho kết quả y hệt — con số "khớp nhất" lúc đó là ngẫu nhiên.
2. Khớp quá khít. 6 trọng số trên 15 ca thì bịa ra bộ trọng số đúng 100% là
   chuyện dễ. Nên luôn báo kèm độ chính xác kiểm chéo bỏ-một (LOO).
3. Trung bình che mất thảm hoạ. Sai lệch trung bình 4% nghe đạt, nhưng có thể
   là 19 chuyến lệch 1% và 1 chuyến lệch 60%. Nên báo cả phân vị và ca tệ nhất.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Any, Iterable, Optional

from src.core.carrier_selection import (
    DEFAULT_WEIGHTS,
    Carrier,
    QuoteOffer,
    RouteRequest,
    select_carrier,
)
from src.core.pricing import PricingRule, Surcharge, compute_quote

# Cổng ra của Giai đoạn 0 (ROADMAP.md).
GATE_MAPE_PCT = 5.0

# Giá dầu phải biến động ít nhất ngần này thì `fuel_sensitivity` mới ước lượng
# được. Dưới ngưỡng, hệ số nhiên liệu không hiện ra trong dữ liệu.
_MIN_FUEL_SPREAD_PCT = 3.0

# Số ca tối thiểu để một kết luận có nghĩa.
_MIN_ROWS = 8


@dataclass
class HistoricalQuote:
    """
    Một báo giá khách ĐÃ GỬI và ĐÃ CHỐT trong quá khứ.

    `actual_price` là sự thật cần khớp — giá khách thật sự thu, không phải giá
    dự tính. `carrier_cost` là giá nhà xe báo cho khách hôm đó.
    """
    quote_id: str
    carrier_cost: float
    actual_price: float
    date: str = ""
    route: str = ""
    vehicle_type: str = ""
    fuel_price: Optional[float] = None      # giá dầu ngày báo giá
    surcharges: list[Surcharge] = field(default_factory=list)
    note: str = ""


@dataclass
class CarrierChoiceCase:
    """Một lần khách ĐÃ CHỌN nhà xe, kèm đúng các ứng viên lúc đó."""
    case_id: str
    request: RouteRequest
    carriers: list[Carrier]
    offers: list[QuoteOffer]
    chosen_carrier_id: Any
    note: str = ""


# ---------------------------------------------------------------------------
# Phần 1 — công thức giá
# ---------------------------------------------------------------------------

def _predict(row: HistoricalQuote, rule: PricingRule) -> int:
    """Gọi ĐÚNG hàm production. Không viết lại công thức ở đây (P4)."""
    result = compute_quote(
        carrier_cost=row.carrier_cost,
        rule=rule,
        current_fuel_price=row.fuel_price,
        extra_surcharges=row.surcharges or None,
    )
    return int(result["quote"]["quoted_price"])


def _deviations(rows: list[HistoricalQuote], rule: PricingRule) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        predicted = _predict(row, rule)
        diff = predicted - row.actual_price
        out.append({
            "quote_id": row.quote_id,
            "route": row.route,
            "carrier_cost": row.carrier_cost,
            "fuel_price": row.fuel_price,
            "actual_price": row.actual_price,
            "predicted_price": predicted,
            "diff": round(diff),
            "deviation_pct": round(diff / row.actual_price * 100, 2) if row.actual_price else None,
        })
    return out


def _mape(devs: list[dict[str, Any]]) -> Optional[float]:
    vals = [abs(d["deviation_pct"]) for d in devs if d["deviation_pct"] is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def _fuel_spread_pct(rows: list[HistoricalQuote]) -> Optional[float]:
    prices = [r.fuel_price for r in rows if r.fuel_price]
    if len(prices) < 2:
        return None
    lo, hi = min(prices), max(prices)
    return round((hi - lo) / lo * 100, 2) if lo else None


def replay_pricing(
    rows: list[HistoricalQuote], rule: PricingRule
) -> dict[str, Any]:
    """
    Chạy lại các báo giá lịch sử qua quy tắc giá hiện tại và đo sai lệch.

    Báo cả trung bình LẪN phân vị và ca tệ nhất — trung bình một mình có thể
    che mất một chuyến lệch 60%.
    """
    warnings: list[str] = []
    if not rows:
        return {"summary": {}, "rows": [], "explain": {},
                "warnings": ["Chưa có báo giá lịch sử nào để đối chiếu."]}
    if len(rows) < _MIN_ROWS:
        warnings.append(
            f"Chỉ có {len(rows)} báo giá — dưới {_MIN_ROWS} ca thì kết luận chưa "
            "đủ vững. Cần thêm dữ liệu trước khi tin con số dưới đây."
        )

    devs = _deviations(rows, rule)
    abs_devs = sorted(abs(d["deviation_pct"]) for d in devs if d["deviation_pct"] is not None)
    mape = _mape(devs)
    bias = round(
        sum(d["deviation_pct"] for d in devs if d["deviation_pct"] is not None)
        / max(1, len(abs_devs)), 2
    )
    within = sum(1 for v in abs_devs if v <= GATE_MAPE_PCT)
    worst = sorted(devs, key=lambda d: -abs(d["deviation_pct"] or 0))[:5]

    if bias > 1.0:
        warnings.append(
            f"Engine báo giá CAO hơn thực tế trung bình {bias:.1f}% — biên đang "
            "đặt rộng hơn khách vẫn dùng, dễ mất đơn."
        )
    elif bias < -1.0:
        warnings.append(
            f"Engine báo giá THẤP hơn thực tế trung bình {abs(bias):.1f}% — biên "
            "đang đặt hẹp hơn khách vẫn dùng, ăn vào lợi nhuận."
        )

    passed = mape is not None and mape < GATE_MAPE_PCT
    return {
        "summary": {
            "rows": len(rows),
            "mape_pct": mape,
            "bias_pct": bias,
            "median_abs_dev_pct": round(median(abs_devs), 2) if abs_devs else None,
            "p90_abs_dev_pct": round(abs_devs[int(len(abs_devs) * 0.9) - 1], 2)
            if len(abs_devs) >= 2 else None,
            "max_abs_dev_pct": round(abs_devs[-1], 2) if abs_devs else None,
            "within_gate": within,
            "gate_pct": GATE_MAPE_PCT,
            "passed": passed,
        },
        "rows": devs,
        "worst": worst,
        "explain": {
            "rule_used": {
                "base_margin_pct": rule.base_margin_pct,
                "fuel_sensitivity": rule.fuel_sensitivity,
                "fuel_baseline_price": rule.fuel_baseline_price,
                "min_margin_amount": rule.min_margin_amount,
            },
            "gate": (
                f"Cổng ra Giai đoạn 0: sai lệch tuyệt đối trung bình < {GATE_MAPE_PCT}%. "
                + ("ĐẠT." if passed else "CHƯA ĐẠT.")
            ),
            "note": (
                "bias dương = engine báo cao hơn giá khách đã chốt. Trung bình có "
                "thể che mất ca cực đoan, xem thêm p90 và danh sách 'worst'."
            ),
        },
        "warnings": warnings,
    }


def fit_pricing_rule(
    rows: list[HistoricalQuote],
    base: PricingRule,
    margin_grid: Optional[Iterable[float]] = None,
    fuel_grid: Optional[Iterable[float]] = None,
) -> dict[str, Any]:
    """
    Tìm `base_margin_pct` / `fuel_sensitivity` khớp dữ liệu lịch sử nhất.

    Quét lưới đầy đủ chứ không tối ưu lặp: không gian hai chiều nhỏ, quét hết
    thì kết quả TÁI LẬP ĐƯỢC và không phụ thuộc điểm khởi đầu.

    TỪ CHỐI khớp `fuel_sensitivity` khi giá dầu trong dữ liệu gần như không đổi
    — lúc đó mọi giá trị đều cho cùng sai lệch, và con số "tốt nhất" chỉ là
    nhiễu. Giữ nguyên giả định cũ và nói rõ vì sao, tốt hơn là trả về một con số
    trông có vẻ đã được hiệu chỉnh.
    """
    if not rows:
        return {"fitted": None, "warnings": ["Không có dữ liệu để khớp."]}

    warnings: list[str] = []
    spread = _fuel_spread_pct(rows)
    fuel_identifiable = spread is not None and spread >= _MIN_FUEL_SPREAD_PCT
    if not fuel_identifiable:
        warnings.append(
            "Giá dầu trong dữ liệu "
            + (f"chỉ biến động {spread}%" if spread is not None else "không có hoặc chỉ có một mức")
            + f" (cần ≥ {_MIN_FUEL_SPREAD_PCT}%) — KHÔNG ước lượng được "
            f"fuel_sensitivity. Giữ nguyên giả định {base.fuel_sensitivity}. "
            "Muốn hiệu chỉnh hệ số này thì cần báo giá ở nhiều mức giá dầu khác nhau."
        )

    margins = list(margin_grid) if margin_grid is not None else [x / 4 for x in range(0, 121)]
    fuels = (
        list(fuel_grid) if fuel_grid is not None
        else ([x / 20 for x in range(0, 21)] if fuel_identifiable else [base.fuel_sensitivity])
    )

    best: Optional[tuple[float, float, float]] = None   # (mape, margin, fuel)
    for margin in margins:
        for fuel in fuels:
            trial = PricingRule(
                base_margin_pct=margin,
                fuel_sensitivity=fuel,
                fuel_baseline_price=base.fuel_baseline_price,
                min_margin_amount=base.min_margin_amount,
                surcharges=list(base.surcharges),
            )
            score = _mape(_deviations(rows, trial))
            if score is None:
                continue
            if best is None or score < best[0]:
                best = (score, margin, fuel)

    if best is None:
        return {"fitted": None, "warnings": warnings + ["Không tính được sai lệch."]}

    score, margin, fuel = best
    current = _mape(_deviations(rows, base))
    fitted = PricingRule(
        base_margin_pct=margin,
        fuel_sensitivity=fuel,
        fuel_baseline_price=base.fuel_baseline_price,
        min_margin_amount=base.min_margin_amount,
        surcharges=list(base.surcharges),
    )

    if current is not None and score >= current - 0.1:
        warnings.append(
            "Bộ tham số khớp nhất không tốt hơn bộ hiện tại đáng kể — sai lệch "
            "còn lại nhiều khả năng đến từ chỗ khác (phụ phí chưa khai báo, giá "
            "thương lượng theo từng khách), không phải từ biên hay hệ số dầu."
        )

    # Cổng < 5% một mình có thể ĐẠT với tham số sai hẳn. Quan sát trên dữ liệu
    # dựng thử: biên giả định 10% (thật là 13,5%) vẫn cho MAPE 4,62% -> "ĐẠT".
    # Đạt cổng mà vẫn còn chỗ cải thiện rõ rệt thì đó là ĐẠT GIẢ.
    improvement = None if current is None else round(current - score, 2)
    false_pass = (
        current is not None and current < GATE_MAPE_PCT
        and improvement is not None and improvement >= 1.5
    )
    if false_pass:
        warnings.append(
            f"ĐẠT GIẢ: quy tắc hiện tại lọt cổng ({current}% < {GATE_MAPE_PCT}%) "
            f"nhưng bộ tham số hiệu chỉnh còn giảm được xuống {score}%. Lọt cổng "
            "không có nghĩa là tham số đúng — hãy dùng bộ hiệu chỉnh."
        )

    return {
        "fitted": {
            "base_margin_pct": margin,
            "fuel_sensitivity": fuel,
            "fuel_sensitivity_was_fitted": fuel_identifiable,
        },
        "mape_pct_fitted": score,
        "mape_pct_current": current,
        "improvement_pct_points": improvement,
        "gate_false_pass": false_pass,
        "fuel_spread_pct": spread,
        "replay_with_fitted": replay_pricing(rows, fitted),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Phần 2 — trọng số chọn nhà xe
# ---------------------------------------------------------------------------

def _picked(case: CarrierChoiceCase, weights: dict[str, float]) -> Optional[Any]:
    ranked = select_carrier(case.carriers, case.offers, case.request, weights)["ranked"]
    return ranked[0]["carrier_id"] if ranked else None


def replay_carrier_choices(
    cases: list[CarrierChoiceCase], weights: Optional[dict[str, float]] = None
) -> dict[str, Any]:
    """
    Bộ trọng số hiện tại có chọn đúng nhà xe khách đã chọn không?

    Ca chọn sai được mổ xẻ: nhà xe khách chọn thua ở tiêu chí nào. Đó là dữ kiện
    để hỏi khách "vì sao hôm đó anh chọn bên kia", chứ không phải để tự vặn
    trọng số cho khớp.
    """
    weights = dict(weights or DEFAULT_WEIGHTS)
    if not cases:
        return {"summary": {}, "cases": [], "warnings": ["Chưa có ca chọn nhà xe nào."]}

    details, hits = [], 0
    for case in cases:
        result = select_carrier(case.carriers, case.offers, case.request, weights)
        ranked = result["ranked"]
        top = ranked[0] if ranked else None
        ok = top is not None and top["carrier_id"] == case.chosen_carrier_id
        hits += ok

        chosen_row = next(
            (r for r in ranked if r["carrier_id"] == case.chosen_carrier_id), None
        )
        gap_detail = []
        if not ok and chosen_row and top:
            by_crit = {c["criterion"]: c for c in chosen_row["criteria"]}
            for c in top["criteria"]:
                mine = by_crit.get(c["criterion"])
                if mine is None:
                    continue
                loss = c["contribution"] - mine["contribution"]
                if loss > 0.001:
                    gap_detail.append({
                        "criterion": c["criterion"], "label": c["label"],
                        "thua_diem": round(loss, 4),
                        "giá_trị_bên_khách_chọn": mine["raw_value"],
                        "giá_trị_bên_engine_chọn": c["raw_value"],
                    })
            gap_detail.sort(key=lambda g: -g["thua_diem"])

        details.append({
            "case_id": case.case_id,
            "khách_chọn": case.chosen_carrier_id,
            "engine_chọn": top["carrier_id"] if top else None,
            "khớp": ok,
            "is_close_call": result["explain"].get("is_close_call"),
            "xếp_hạng_bên_khách_chọn": (
                next((i + 1 for i, r in enumerate(ranked)
                      if r["carrier_id"] == case.chosen_carrier_id), None)
            ),
            "thua_ở": gap_detail[:3],
            "note": case.note,
        })

    acc = round(hits / len(cases) * 100, 1)
    warnings = []
    if len(cases) < _MIN_ROWS:
        warnings.append(
            f"Chỉ có {len(cases)} ca — quá ít để kết luận về trọng số."
        )
    close = sum(1 for d in details if d["is_close_call"])
    if close:
        warnings.append(
            f"{close} ca sát nút (chênh điểm < 0.05). Ở những ca đó engine chọn "
            "khác khách không có nghĩa là engine sai — hai bên gần ngang nhau."
        )

    return {
        "summary": {"cases": len(cases), "top1_hits": hits, "top1_accuracy_pct": acc},
        "cases": details,
        "explain": {"weights_used": weights},
        "warnings": warnings,
    }


def fit_carrier_weights(
    cases: list[CarrierChoiceCase],
    base: Optional[dict[str, float]] = None,
    step: float = 0.05,
    max_shift: float = 0.20,
    rounds: int = 3,
) -> dict[str, Any]:
    """
    Chỉnh trọng số theo lựa chọn thật của khách — có phanh chống khớp quá khít.

    Ba cái phanh:
      - `max_shift`: mỗi trọng số không được rời giả định ban đầu quá xa. Dữ
        liệu 15-20 ca không đủ tư cách lật ngược hoàn toàn một giả định nghiệp vụ.
      - Leo đồi theo toạ độ từ DEFAULT_WEIGHTS, không phải quét mù — kết quả
        nằm gần điểm xuất phát và giải thích được.
      - Kiểm chéo bỏ-một (LOO): khớp lại trên n−1 ca rồi đoán ca bị bỏ. Chênh
        lệch lớn giữa độ chính xác trong mẫu và LOO chính là dấu hiệu bịa số.
    """
    base = dict(base or DEFAULT_WEIGHTS)
    if not cases:
        return {"fitted": None, "warnings": ["Không có ca nào để khớp."]}

    fitted = _hill_climb(cases, base, step, max_shift, rounds)
    in_sample = replay_carrier_choices(cases, fitted)["summary"]["top1_accuracy_pct"]

    loo_hits = 0
    for i in range(len(cases)):
        rest = cases[:i] + cases[i + 1:]
        if not rest:
            continue
        w = _hill_climb(rest, base, step, max_shift, rounds)
        loo_hits += _picked(cases[i], w) == cases[i].chosen_carrier_id
    loo = round(loo_hits / len(cases) * 100, 1)

    warnings: list[str] = []
    if in_sample - loo >= 15:
        warnings.append(
            f"Trong mẫu {in_sample}% nhưng kiểm chéo chỉ {loo}% — bộ trọng số này "
            "đang HỌC THUỘC các ca đã cho chứ không nắm được quy tắc. Đừng dùng; "
            "hãy hỏi khách trực tiếp về thứ tự ưu tiên."
        )
    if len(cases) < _MIN_ROWS:
        warnings.append(f"Chỉ {len(cases)} ca — quá ít để tin bộ trọng số khớp được.")

    moved = {
        k: round(fitted[k] - base[k], 4)
        for k in fitted if abs(fitted[k] - base[k]) > 1e-9
    }
    return {
        "fitted": fitted,
        "base": base,
        "moved": moved,
        "accuracy_in_sample_pct": in_sample,
        "accuracy_loo_pct": loo,
        "warnings": warnings,
    }


def _hill_climb(
    cases: list[CarrierChoiceCase],
    base: dict[str, float],
    step: float,
    max_shift: float,
    rounds: int,
) -> dict[str, float]:
    """Leo đồi theo toạ độ, luôn chuẩn hoá về tổng 1, không rời base quá max_shift."""
    def score(w: dict[str, float]) -> int:
        return sum(_picked(c, w) == c.chosen_carrier_id for c in cases)

    def normalize(w: dict[str, float]) -> dict[str, float]:
        total = sum(w.values())
        return {k: v / total for k, v in w.items()} if total > 0 else dict(base)

    current = dict(base)
    best = score(current)
    for _ in range(rounds):
        improved = False
        for name in sorted(base):
            for delta in (step, -step):
                trial = dict(current)
                value = trial[name] + delta
                if value < 0 or abs(value - base[name]) > max_shift + 1e-9:
                    continue
                trial[name] = value
                trial = normalize(trial)
                s = score(trial)
                if s > best:
                    best, current, improved = s, trial, True
        if not improved:
            break
    return {k: round(v, 4) for k, v in current.items()}


__all__ = [
    "GATE_MAPE_PCT",
    "HistoricalQuote",
    "CarrierChoiceCase",
    "replay_pricing",
    "fit_pricing_rule",
    "replay_carrier_choices",
    "fit_carrier_weights",
]
