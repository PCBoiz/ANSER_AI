"""
src/core/carrier_selection.py — chọn hãng xe cho một tuyến vận chuyển.

NGUYÊN TẮC P1 (deterministic-first): TOÀN BỘ việc chọn hãng làm bằng code thuần.
LLM không tham gia chấm điểm. LLM chỉ (a) chuyển yêu cầu tiếng Việt thành tham số,
và (b) đọc `explain` ở output rồi diễn giải cho người dùng.

VÌ SAO KHÔNG DÙNG LLM CHẤM ĐIỂM
--------------------------------
Khách xác nhận: các hãng xe đối tác là chỗ quen, không nổi trên mạng, nên tìm kiếm
web vô dụng. Mọi thông tin đều do khách nhập. Khi đã có đủ thuộc tính dạng số thì
đây là bài toán RA QUYẾT ĐỊNH ĐA TIÊU CHÍ CÓ TRỌNG SỐ — thuần số học. Giao cho LLM
chỉ tạo ra một lựa chọn không tái lập được và không giải thích được.

"ĐỘ THÂN THIẾT" KHÔNG CHẤM CẢM TÍNH
------------------------------------
Khách mô tả quan hệ lâu năm biểu hiện thành: "nhiều ưu đãi, công nợ thoải mái hơn".
Đó là các con số đo được (`discount_pct`, `credit_days`, `years_partner`), nên
không cần thang điểm chủ quan 1-5. Nhập một lần, dùng mãi.

RÀNG BUỘC CỨNG vs TIÊU CHÍ MỀM
-------------------------------
Loại xe và khả năng chạy tuyến là RÀNG BUỘC CỨNG — hãng không đáp ứng thì LOẠI,
không phải trừ điểm. Gợi ý một hãng không có xe phù hợp là gợi ý sai, dù điểm tổng
có cao đến đâu.

DỮ LIỆU THIẾU
-------------
SME hiếm khi có đủ mọi trường. Tiêu chí thiếu dữ liệu bị LOẠI KHỎI phép tính và
trọng số được chuẩn hoá lại trên các tiêu chí còn dùng được. Danh sách tiêu chí bị
bỏ luôn được trả ra trong `explain.missing` — người dùng phải biết quyết định này
dựa trên thông tin không đầy đủ.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

# ---------------------------------------------------------------------------
# Trọng số mặc định
# ---------------------------------------------------------------------------
# Đây chỉ là ĐIỂM KHỞI ĐẦU hợp lý, không phải chân lý. Mỗi doanh nghiệp cân nhắc
# khác nhau — có nơi ưu tiên giá, có nơi ưu tiên công nợ vì dòng tiền eo hẹp.
# Ghi đè bằng bảng `pricing_rules`/`selection_weights` của từng workspace.

DEFAULT_WEIGHTS: dict[str, float] = {
    "price":       0.30,   # giá chào cho tuyến này
    "proximity":   0.20,   # bãi xe gần điểm lấy hàng -> ít chạy rỗng, dễ điều xe gấp
    "credit":      0.20,   # số ngày công nợ cho phép -> ảnh hưởng trực tiếp dòng tiền
    "reliability": 0.15,   # tỷ lệ giao đúng hẹn, tính từ lịch sử chuyến
    "discount":    0.10,   # % ưu đãi thường xuyên
    "tenure":      0.05,   # số năm hợp tác
}

# Ngưỡng chuẩn hoá cho các tiêu chí có thang tuyệt đối.
MAX_USEFUL_DISTANCE_KM = 60.0   # xa hơn mức này coi như bất lợi tối đa
MAX_USEFUL_CREDIT_DAYS = 45.0
MAX_USEFUL_DISCOUNT_PCT = 20.0
MAX_USEFUL_TENURE_YEARS = 10.0

_CRITERION_LABELS_VI = {
    "price": "giá chào",
    "proximity": "khoảng cách bãi xe tới điểm lấy hàng",
    "credit": "số ngày công nợ",
    "reliability": "tỷ lệ giao đúng hẹn",
    "discount": "% ưu đãi",
    "tenure": "số năm hợp tác",
}


# ---------------------------------------------------------------------------
# Kiểu dữ liệu
# ---------------------------------------------------------------------------

@dataclass
class Carrier:
    """
    Hồ sơ hãng xe. Khách nhập MỘT LẦN, sau đó chỉ cập nhật khi có thay đổi.

    Trường Optional = chưa có dữ liệu. KHÔNG được thay bằng 0 — 0 nghĩa là
    "không cho nợ ngày nào", khác hẳn "chưa biết cho nợ bao nhiêu".
    """
    id: Any
    name: str
    vehicle_types: set[str] = field(default_factory=set)
    depot_lat: Optional[float] = None
    depot_lon: Optional[float] = None
    discount_pct: Optional[float] = None
    credit_days: Optional[int] = None
    years_partner: Optional[float] = None
    on_time_rate: Optional[float] = None      # 0..1, tính từ bảng trips
    notes: str = ""


@dataclass
class QuoteOffer:
    """Giá một hãng chào cho một tuyến + loại xe cụ thể."""
    carrier_id: Any
    price: float
    valid_to: Optional[str] = None


@dataclass
class RouteRequest:
    """Yêu cầu vận chuyển đã được LLM trích xuất thành tham số."""
    origin: str
    destination: str
    vehicle_type: str
    origin_lat: Optional[float] = None
    origin_lon: Optional[float] = None
    cargo_type: Optional[str] = None
    pickup_date: Optional[str] = None


# ---------------------------------------------------------------------------
# Tiện ích
# ---------------------------------------------------------------------------

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Khoảng cách đường chim bay (km). Đủ dùng để so sánh tương đối giữa các bãi xe."""
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _normalize_price(value: float, values: list[float]) -> float:
    """
    Giá: thấp hơn = tốt hơn. Chuẩn hoá theo TỶ LỆ so với giá thấp nhất trong nhóm.

        điểm = giá_thấp_nhất / giá_hãng_này

    Cố tình KHÔNG dùng min-max ((hi - v) / (hi - lo)). Min-max chỉ giữ lại THỨ HẠNG:
    với 2 ứng viên, hãng rẻ hơn luôn được 1.0 và hãng kia luôn được 0.0, bất kể
    chênh nhau 20 nghìn hay 500 nghìn. Cách đó thổi phồng một khác biệt không đáng
    kể thành khác biệt tuyệt đối.

    Tỷ lệ giữ được ĐỘ LỚN: chênh 2% cho 0.98, chênh 50% cho 0.67.
    """
    lo = min(values)
    if value <= 0:
        return 0.0
    return _clamp01(lo / value)


def _normalize_absolute(value: float, ceiling: float, lower_better: bool = False) -> float:
    """Chuẩn hoá theo thang tuyệt đối, không phụ thuộc nhóm ứng viên."""
    ratio = _clamp01(value / ceiling) if ceiling else 0.0
    return 1.0 - ratio if lower_better else ratio


# ---------------------------------------------------------------------------
# Lọc cứng
# ---------------------------------------------------------------------------

def _hard_filter(
    carriers: Iterable[Carrier],
    offers_by_carrier: dict[Any, QuoteOffer],
    request: RouteRequest,
) -> tuple[list[Carrier], list[dict]]:
    """Trả (ứng viên hợp lệ, danh sách bị loại kèm lý do)."""
    eligible, rejected = [], []

    for carrier in carriers:
        if carrier.vehicle_types and request.vehicle_type not in carrier.vehicle_types:
            rejected.append({
                "carrier_id": carrier.id,
                "name": carrier.name,
                "reason": f"không có xe {request.vehicle_type}",
            })
            continue

        if carrier.id not in offers_by_carrier:
            rejected.append({
                "carrier_id": carrier.id,
                "name": carrier.name,
                "reason": f"chưa có giá chào cho tuyến {request.origin} → {request.destination}",
            })
            continue

        eligible.append(carrier)

    return eligible, rejected


# ---------------------------------------------------------------------------
# Chấm điểm
# ---------------------------------------------------------------------------

def _raw_criteria(
    carrier: Carrier,
    offer: QuoteOffer,
    request: RouteRequest,
) -> dict[str, Optional[float]]:
    """Giá trị thô từng tiêu chí. None = thiếu dữ liệu."""
    distance = None
    if (
        carrier.depot_lat is not None and carrier.depot_lon is not None
        and request.origin_lat is not None and request.origin_lon is not None
    ):
        distance = haversine_km(
            carrier.depot_lat, carrier.depot_lon,
            request.origin_lat, request.origin_lon,
        )

    return {
        "price": offer.price,
        "proximity": distance,
        "credit": None if carrier.credit_days is None else float(carrier.credit_days),
        "reliability": carrier.on_time_rate,
        "discount": carrier.discount_pct,
        "tenure": carrier.years_partner,
    }


def _score_criteria(
    raw: dict[str, Optional[float]],
    all_prices: list[float],
) -> dict[str, Optional[float]]:
    """Chuẩn hoá về 0..1, càng cao càng tốt. None giữ nguyên là None."""
    scored: dict[str, Optional[float]] = {}

    scored["price"] = (
        None if raw["price"] is None
        else _normalize_price(raw["price"], all_prices)
    )
    scored["proximity"] = (
        None if raw["proximity"] is None
        else _normalize_absolute(raw["proximity"], MAX_USEFUL_DISTANCE_KM, lower_better=True)
    )
    scored["credit"] = (
        None if raw["credit"] is None
        else _normalize_absolute(raw["credit"], MAX_USEFUL_CREDIT_DAYS)
    )
    scored["reliability"] = None if raw["reliability"] is None else _clamp01(raw["reliability"])
    scored["discount"] = (
        None if raw["discount"] is None
        else _normalize_absolute(raw["discount"], MAX_USEFUL_DISCOUNT_PCT)
    )
    scored["tenure"] = (
        None if raw["tenure"] is None
        else _normalize_absolute(raw["tenure"], MAX_USEFUL_TENURE_YEARS)
    )
    return scored


def select_carrier(
    carriers: Iterable[Carrier],
    offers: Iterable[QuoteOffer],
    request: RouteRequest,
    weights: Optional[dict[str, float]] = None,
) -> dict[str, Any]:
    """
    Xếp hạng hãng xe cho một yêu cầu vận chuyển.

    Trả về dict đã cấu trúc hoá, KHÔNG phải văn xuôi. LLM nhận dict này rồi diễn
    giải. Mọi con số trong lời giải thích của LLM đều truy ngược được về đây.

    Cấu trúc trả về:
      {
        "ranked":   [ {carrier_id, name, total_score, criteria:[...], offer_price}, ... ],
        "rejected": [ {carrier_id, name, reason}, ... ],
        "explain":  {"weights_used", "missing", "criteria_labels", "runner_up_gap"},
      }
    """
    weights = dict(weights or DEFAULT_WEIGHTS)
    offers_by_carrier = {o.carrier_id: o for o in offers}

    eligible, rejected = _hard_filter(carriers, offers_by_carrier, request)
    if not eligible:
        return {
            "ranked": [],
            "rejected": rejected,
            "explain": {
                "weights_used": {},
                "missing": [],
                "criteria_labels": _CRITERION_LABELS_VI,
                "runner_up_gap": None,
                "note": "Không có hãng xe nào đáp ứng yêu cầu.",
            },
        }

    all_prices = [offers_by_carrier[c.id].price for c in eligible]

    # --- tiêu chí nào dùng được trên TOÀN BỘ nhóm ứng viên -----------------
    # Chỉ chấm bằng tiêu chí mà MỌI ứng viên đều có dữ liệu. Nếu hãng A có
    # on_time_rate còn hãng B không, chấm bằng tiêu chí đó là phạt oan hãng B vì
    # thiếu dữ liệu chứ không phải vì kém.
    per_carrier_raw = {
        c.id: _raw_criteria(c, offers_by_carrier[c.id], request) for c in eligible
    }
    usable = [
        name for name in weights
        if all(per_carrier_raw[c.id].get(name) is not None for c in eligible)
    ]
    missing = [
        {"criterion": name, "label": _CRITERION_LABELS_VI.get(name, name)}
        for name in weights if name not in usable
    ]

    # --- chuẩn hoá lại trọng số trên tiêu chí dùng được --------------------
    total_weight = sum(weights[name] for name in usable)
    if total_weight <= 0:
        return {
            "ranked": [],
            "rejected": rejected,
            "explain": {
                "weights_used": {},
                "missing": missing,
                "criteria_labels": _CRITERION_LABELS_VI,
                "runner_up_gap": None,
                "note": (
                    "Không đủ dữ liệu để xếp hạng. Cần nhập ít nhất giá chào cho "
                    "tuyến này ở từng hãng."
                ),
            },
        }
    effective = {name: weights[name] / total_weight for name in usable}

    # --- chấm điểm ---------------------------------------------------------
    ranked = []
    for carrier in eligible:
        raw = per_carrier_raw[carrier.id]
        scored = _score_criteria(raw, all_prices)

        breakdown, total = [], 0.0
        for name in usable:
            norm = scored[name] or 0.0
            contribution = norm * effective[name]
            total += contribution
            breakdown.append({
                "criterion": name,
                "label": _CRITERION_LABELS_VI.get(name, name),
                "raw_value": raw[name],
                "normalized": round(norm, 4),
                "weight": round(effective[name], 4),
                "contribution": round(contribution, 4),
            })

        breakdown.sort(key=lambda b: b["contribution"], reverse=True)
        ranked.append({
            "carrier_id": carrier.id,
            "name": carrier.name,
            "offer_price": offers_by_carrier[carrier.id].price,
            "total_score": round(total, 4),
            "criteria": breakdown,
        })

    ranked.sort(key=lambda r: r["total_score"], reverse=True)

    gap = (
        round(ranked[0]["total_score"] - ranked[1]["total_score"], 4)
        if len(ranked) > 1 else None
    )

    return {
        "ranked": ranked,
        "rejected": rejected,
        "explain": {
            "weights_used": {k: round(v, 4) for k, v in effective.items()},
            "missing": missing,
            "criteria_labels": _CRITERION_LABELS_VI,
            "runner_up_gap": gap,
            # Biên hẹp = hai hãng gần ngang nhau. Người quyết định nên biết điều
            # đó thay vì nhận một khuyến nghị nghe chắc nịch.
            "is_close_call": gap is not None and gap < 0.05,
        },
    }


__all__ = [
    "Carrier",
    "QuoteOffer",
    "RouteRequest",
    "DEFAULT_WEIGHTS",
    "haversine_km",
    "select_carrier",
]
