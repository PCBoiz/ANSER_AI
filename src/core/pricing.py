"""
src/core/pricing.py — engine tính báo giá vận tải. CODE THUẦN, KHÔNG LLM (P1).

NGHIỆP VỤ (từ khảo sát khách logistics)
---------------------------------------
Khách là trung gian: hỏi giá nhà xe -> cộng biên -> báo lại khách của họ.
Giá cước đổi theo ngày vì giá dầu biến động ("dầu 25.000đ lên 28.000đ").
Hiện tại chủ doanh nghiệp tự tính tay ngoài MISA rồi nhập lại — chậm, và khi
đang lái xe thì không làm được. Engine này thay đúng phần "tự tính tay" đó.

CÔNG THỨC
---------
    điều_chỉnh_nhiên_liệu = giá_nhà_xe × fuel_sensitivity × (dầu_hiện_tại/dầu_gốc − 1)
    chi_phí_hiệu_chỉnh    = giá_nhà_xe + điều_chỉnh_nhiên_liệu
    phụ_phí               = tổng surcharge (hàng lạnh, bốc xếp, chờ...)
    biên                  = max(chi_phí_hiệu_chỉnh × base_margin_pct/100, min_margin_amount)
    báo_giá               = làm_tròn_1000₫(chi_phí_hiệu_chỉnh + phụ_phí + biên)

`fuel_sensitivity` = tỷ trọng nhiên liệu trong cơ cấu chi phí nhà xe (0..1).
Xe tải đường dài thường 0.30-0.40. Dầu tăng 12% với sensitivity 0.35 thì chi
phí tăng ~4.2% — không phải tăng cả 12%.

BẢO MẬT (P2): PricingRule chứa biên lợi nhuận — BÍ MẬT KINH DOANH CỐT LÕI của
khách. Kết quả trả về tách làm hai phần:
  - `quote`    : đưa được cho khách cuối (chỉ giá chốt + phụ phí công khai)
  - `internal` : breakdown đầy đủ có biên — CHỈ hiển thị nội bộ, không bao giờ
                 đưa vào email/Zalo gửi khách cuối, không đưa vào prompt gửi
                 ra ngoài hạ tầng.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

# Báo giá vận tải VN chốt theo bậc nghìn đồng.
_QUOTE_STEP_VND = 1000


def _round_step(amount: float, step: int = _QUOTE_STEP_VND) -> int:
    """Làm tròn về bậc `step` VND, round-half-up (không dùng banker's rounding)."""
    d = Decimal(str(amount)) / Decimal(step)
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP)) * step


@dataclass
class Surcharge:
    """Phụ phí một khoản: cố định (amount) hoặc theo % chi phí hiệu chỉnh (pct)."""
    name: str
    amount: float = 0.0     # VND cố định
    pct: float = 0.0        # % trên chi_phí_hiệu_chỉnh (0..100)


@dataclass
class PricingRule:
    """
    Quy tắc giá của MỘT khách hàng (workspace). Nhập một lần, dùng mãi.

    ⚠️ Bảng chứa dữ liệu này (`pricing_rules`) là bảng nhạy cảm nhất hệ thống —
    xem ARCHITECTURE.md §10.
    """
    base_margin_pct: float                 # biên chuẩn, % trên chi phí hiệu chỉnh
    fuel_sensitivity: float = 0.35         # tỷ trọng nhiên liệu trong chi phí (0..1)
    fuel_baseline_price: Optional[float] = None   # giá dầu lúc nhà xe chốt bảng giá
    min_margin_amount: float = 0.0         # sàn biên tuyệt đối (VND)
    surcharges: list[Surcharge] = field(default_factory=list)

    def __post_init__(self):
        if not 0 <= self.fuel_sensitivity <= 1:
            raise ValueError("fuel_sensitivity phải trong [0, 1]")
        if self.base_margin_pct < 0:
            raise ValueError("base_margin_pct không được âm")
        if self.min_margin_amount < 0:
            raise ValueError("min_margin_amount không được âm")


def compute_quote(
    carrier_cost: float,
    rule: PricingRule,
    current_fuel_price: Optional[float] = None,
    extra_surcharges: Optional[list[Surcharge]] = None,
) -> dict[str, Any]:
    """
    Tính báo giá từ giá nhà xe + quy tắc giá + giá dầu hiện tại.

    Trả dict hai phần `quote` (đưa khách cuối được) và `internal` (có biên —
    nội bộ). LLM diễn giải từ `internal` cho CHỦ doanh nghiệp, nhưng nội dung
    gửi KHÁCH CUỐI chỉ được lấy từ `quote`.
    """
    if carrier_cost <= 0:
        raise ValueError("carrier_cost phải > 0")

    warnings: list[str] = []

    # ---- 1. Điều chỉnh nhiên liệu ----------------------------------------
    fuel_adjustment = 0.0
    fuel_ratio: Optional[float] = None
    if current_fuel_price is not None and rule.fuel_baseline_price:
        if current_fuel_price <= 0 or rule.fuel_baseline_price <= 0:
            raise ValueError("giá nhiên liệu phải > 0")
        fuel_ratio = current_fuel_price / rule.fuel_baseline_price
        fuel_adjustment = carrier_cost * rule.fuel_sensitivity * (fuel_ratio - 1)
    elif current_fuel_price is not None and not rule.fuel_baseline_price:
        warnings.append(
            "Có giá dầu hiện tại nhưng quy tắc giá chưa khai báo giá dầu gốc "
            "(fuel_baseline_price) — bỏ qua điều chỉnh nhiên liệu."
        )
    elif current_fuel_price is None and rule.fuel_baseline_price:
        warnings.append(
            "Chưa lấy được giá dầu hiện tại — báo giá KHÔNG có điều chỉnh "
            "nhiên liệu, có thể lệch nếu giá dầu đã biến động."
        )

    adjusted_cost = carrier_cost + fuel_adjustment

    # ---- 2. Phụ phí -------------------------------------------------------
    all_surcharges = list(rule.surcharges) + list(extra_surcharges or [])
    surcharge_lines = []
    surcharge_total = 0.0
    for s in all_surcharges:
        value = s.amount + adjusted_cost * (s.pct / 100.0)
        surcharge_total += value
        surcharge_lines.append({"name": s.name, "value": _round_step(value, 1)})

    # ---- 3. Biên ----------------------------------------------------------
    margin_by_pct = adjusted_cost * (rule.base_margin_pct / 100.0)
    margin = max(margin_by_pct, rule.min_margin_amount)
    margin_floored = margin > margin_by_pct
    if margin_floored:
        warnings.append(
            f"Biên theo % ({_round_step(margin_by_pct, 1):,}đ) thấp hơn sàn "
            f"{_round_step(rule.min_margin_amount, 1):,}đ — áp sàn."
        )

    # ---- 4. Chốt giá ------------------------------------------------------
    quoted_price = _round_step(adjusted_cost + surcharge_total + margin)

    return {
        # Phần ĐƯA ĐƯỢC cho khách cuối
        "quote": {
            "quoted_price": quoted_price,
            "surcharges": surcharge_lines,   # phụ phí là khoản công khai trên báo giá
            "currency": "VND",
        },
        # Phần NỘI BỘ — có biên, không gửi ra ngoài
        "internal": {
            "carrier_cost": _round_step(carrier_cost, 1),
            "fuel_ratio": None if fuel_ratio is None else round(fuel_ratio, 4),
            "fuel_adjustment": _round_step(fuel_adjustment, 1),
            "adjusted_cost": _round_step(adjusted_cost, 1),
            "surcharge_total": _round_step(surcharge_total, 1),
            "margin": _round_step(margin, 1),
            "margin_pct_effective": round(margin / adjusted_cost * 100, 2) if adjusted_cost else None,
            "margin_floored": margin_floored,
            "rounding_step": _QUOTE_STEP_VND,
        },
        "warnings": warnings,
    }


__all__ = ["Surcharge", "PricingRule", "compute_quote"]
