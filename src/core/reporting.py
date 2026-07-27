"""
src/core/reporting.py — engine báo cáo DT/CP/LN theo kỳ. CODE THUẦN, KHÔNG LLM (P1).

NGHIỆP VỤ
---------
Chủ DN cần biết theo quý / nửa năm / năm: doanh thu bao nhiêu, chi phí bao
nhiêu, lãi bao nhiêu, mặt hàng nào lãi nhất, mặt hàng nào bán chạy nhất.
Hiện họ xuất MISA rồi cộng tay trên Excel.

VÌ SAO KHÔNG ĐỂ LLM VIẾT SQL (quyết định 27/07/2026)
----------------------------------------------------
Con số tài chính sai mà *nghe có vẻ đúng* là loại lỗi tệ nhất: không ai phát
hiện cho tới lúc quyết toán. LLM viết SQL tự do có thể join sai, tính trùng
dòng, hoặc lọc thiếu kỳ — tất cả đều trả về một con số trông bình thường.
Engine này tính bằng code, LLM chỉ diễn giải (P1). Mọi con số trong lời diễn
giải đều truy ngược được về `periods[]`/`products[]` ở đây.

TRUNG THỰC VỀ DỮ LIỆU THIẾU
---------------------------
Giá vốn (COGS) thường thiếu ở một phần dòng bán. Engine KHÔNG coi thiếu là 0 —
nó tính `cogs_coverage_pct` và hạ `confidence`, kèm cảnh báo. Thà nói "lãi gộp
chỉ tính được trên 62% doanh thu" còn hơn đưa một con số lãi sai.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

# Ngưỡng phủ giá vốn: dưới mức này thì lãi gộp không đáng tin để ra quyết định.
_COGS_COVERAGE_GOOD = 0.95
_COGS_COVERAGE_FAIR = 0.70

GRANULARITIES = ("month", "quarter", "half", "year")


@dataclass
class SaleLine:
    """Một dòng bán hàng. `cogs=None` nghĩa là CHƯA BIẾT giá vốn, không phải 0."""
    date: str                       # YYYY-MM-DD
    revenue: float                  # tiền thu về, đã trừ chiết khấu
    product: str = ""
    quantity: float = 0.0
    cogs: Optional[float] = None    # giá vốn hàng bán


@dataclass
class ExpenseLine:
    """Chi phí vận hành (KHÔNG gồm giá vốn — giá vốn nằm trong SaleLine.cogs)."""
    date: str
    amount: float
    category: str = "khác"


@dataclass
class ReportRequest:
    granularity: str = "quarter"
    periods_back: int = 4           # số kỳ gần nhất giữ lại trong báo cáo
    top_n: int = 10                 # số mặt hàng trong bảng xếp hạng
    today: Optional[str] = None     # mốc "hôm nay"; None = date.today()
    sales: list[SaleLine] = field(default_factory=list)
    expenses: list[ExpenseLine] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Khoá kỳ
# ---------------------------------------------------------------------------

def period_key(day: date, granularity: str) -> str:
    """
    Nhãn kỳ theo lịch DƯƠNG (năm tài chính = năm dương lịch, đúng thông lệ VN).

    month -> 2026-07 | quarter -> 2026-Q3 | half -> 2026-H2 | year -> 2026
    """
    if granularity == "month":
        return f"{day.year}-{day.month:02d}"
    if granularity == "quarter":
        return f"{day.year}-Q{(day.month - 1) // 3 + 1}"
    if granularity == "half":
        return f"{day.year}-H{1 if day.month <= 6 else 2}"
    if granularity == "year":
        return str(day.year)
    raise ValueError(f"granularity phải thuộc {GRANULARITIES}, nhận '{granularity}'")


def _parse_day(value: str) -> Optional[date]:
    """Chấp YYYY-MM-DD (có thể kèm giờ). Sai định dạng -> None, đếm vào cảnh báo."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _pct(part: float, whole: float) -> Optional[float]:
    return round(part / whole * 100, 2) if whole else None


# ---------------------------------------------------------------------------
# Báo cáo theo kỳ
# ---------------------------------------------------------------------------

def build_report(req: ReportRequest) -> dict[str, Any]:
    """
    Doanh thu / giá vốn / lãi gộp / chi phí / lãi ròng theo từng kỳ.

    Trả dict đã cấu trúc hoá để LLM diễn giải — mọi con số đều có nguồn.
    """
    if req.granularity not in GRANULARITIES:
        raise ValueError(f"granularity phải thuộc {GRANULARITIES}")
    if req.periods_back < 1:
        raise ValueError("periods_back phải >= 1")

    warnings: list[str] = []
    bad_dates = 0

    buckets: dict[str, dict[str, float]] = defaultdict(
        lambda: {"revenue": 0.0, "cogs": 0.0, "revenue_with_cogs": 0.0,
                 "expenses": 0.0, "orders": 0.0}
    )

    for line in req.sales:
        day = _parse_day(line.date)
        if day is None:
            bad_dates += 1
            continue
        bucket = buckets[period_key(day, req.granularity)]
        bucket["revenue"] += line.revenue
        bucket["orders"] += 1
        if line.cogs is not None:
            bucket["cogs"] += line.cogs
            # Chỉ doanh thu CÓ giá vốn mới được dùng để tính lãi gộp
            bucket["revenue_with_cogs"] += line.revenue

    for exp in req.expenses:
        day = _parse_day(exp.date)
        if day is None:
            bad_dates += 1
            continue
        buckets[period_key(day, req.granularity)]["expenses"] += exp.amount

    if bad_dates:
        warnings.append(
            f"{bad_dates} dòng có ngày sai định dạng (cần YYYY-MM-DD) — đã bỏ qua."
        )
    if not buckets:
        return {
            "granularity": req.granularity,
            "periods": [],
            "products": [],
            "explain": {"note": "Không có dữ liệu hợp lệ trong khoảng yêu cầu."},
            "warnings": warnings,
        }

    # Kỳ gần nhất trước, cắt theo periods_back, rồi trả về thứ tự thời gian
    ordered = sorted(buckets, reverse=True)[: req.periods_back]
    ordered.reverse()

    periods = []
    prev_revenue: Optional[float] = None
    prev_net: Optional[float] = None

    for key in ordered:
        b = buckets[key]
        gross_profit = b["revenue_with_cogs"] - b["cogs"]
        net_profit = gross_profit - b["expenses"]
        coverage = b["revenue_with_cogs"] / b["revenue"] if b["revenue"] else 0.0

        periods.append({
            "period": key,
            "revenue": round(b["revenue"]),
            "cogs": round(b["cogs"]),
            "gross_profit": round(gross_profit),
            "operating_expenses": round(b["expenses"]),
            "net_profit": round(net_profit),
            "gross_margin_pct": _pct(gross_profit, b["revenue_with_cogs"]),
            "net_margin_pct": _pct(net_profit, b["revenue"]),
            "orders": int(b["orders"]),
            "cogs_coverage_pct": round(coverage * 100, 1),
            # Tăng trưởng so với kỳ LIỀN TRƯỚC trong chính báo cáo này
            "revenue_growth_pct": _pct(b["revenue"] - prev_revenue, prev_revenue)
            if prev_revenue else None,
            "net_profit_growth_pct": _pct(net_profit - prev_net, abs(prev_net))
            if prev_net else None,
        })
        prev_revenue, prev_net = b["revenue"], net_profit

    # --- độ tin cậy dựa trên phủ giá vốn của TOÀN báo cáo -------------------
    total_revenue = sum(p["revenue"] for p in periods)
    total_with_cogs = sum(buckets[k]["revenue_with_cogs"] for k in ordered)
    coverage = total_with_cogs / total_revenue if total_revenue else 0.0

    if coverage >= _COGS_COVERAGE_GOOD:
        confidence = "cao"
    elif coverage >= _COGS_COVERAGE_FAIR:
        confidence = "trung bình"
        warnings.append(
            f"Chỉ {coverage * 100:.0f}% doanh thu có giá vốn — lãi gộp tính trên "
            "phần đó, số thực có thể thấp hơn."
        )
    else:
        confidence = "thấp"
        warnings.append(
            f"Chỉ {coverage * 100:.0f}% doanh thu có giá vốn — CHƯA đủ để kết luận "
            "về lãi. Cần bổ sung giá vốn cho các mặt hàng còn thiếu."
        )

    if not req.expenses:
        warnings.append(
            "Chưa có dữ liệu chi phí vận hành — 'lãi ròng' đang bằng lãi gộp, "
            "chưa trừ lương/thuê kho/nhiên liệu."
        )

    return {
        "granularity": req.granularity,
        "periods": periods,
        "products": product_profitability(req.sales, top_n=req.top_n),
        "explain": {
            "cogs_coverage_pct": round(coverage * 100, 1),
            "confidence": confidence,
            "formula": (
                "lãi_gộp = doanh_thu_có_giá_vốn − giá_vốn; "
                "lãi_ròng = lãi_gộp − chi_phí_vận_hành"
            ),
            "period_count": len(periods),
        },
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Phân tích mặt hàng
# ---------------------------------------------------------------------------

def product_profitability(sales: list[SaleLine], top_n: int = 10) -> list[dict[str, Any]]:
    """
    Xếp hạng mặt hàng theo lãi gộp, kèm sản lượng để nhìn ra "bán chạy nhưng
    lãi mỏng" — đúng câu hỏi chủ DN hay hỏi.

    Mặt hàng thiếu giá vốn vẫn xuất hiện (có doanh thu, có sản lượng) nhưng
    `gross_profit=None` và `missing_cogs=True` — KHÔNG bị coi là lãi 0 rồi tụt
    xuống đáy bảng một cách sai lệch.
    """
    agg: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"revenue": 0.0, "cogs": 0.0, "quantity": 0.0,
                 "lines": 0, "lines_with_cogs": 0}
    )

    for line in sales:
        name = (line.product or "").strip() or "(không rõ tên)"
        a = agg[name]
        a["revenue"] += line.revenue
        a["quantity"] += line.quantity
        a["lines"] += 1
        if line.cogs is not None:
            a["cogs"] += line.cogs
            a["lines_with_cogs"] += 1

    total_revenue = sum(a["revenue"] for a in agg.values())

    rows = []
    for name, a in agg.items():
        has_cogs = a["lines_with_cogs"] == a["lines"] and a["lines"] > 0
        gross = a["revenue"] - a["cogs"] if has_cogs else None
        rows.append({
            "product": name,
            "revenue": round(a["revenue"]),
            "quantity": round(a["quantity"], 2),
            "gross_profit": None if gross is None else round(gross),
            "gross_margin_pct": None if gross is None else _pct(gross, a["revenue"]),
            "revenue_share_pct": _pct(a["revenue"], total_revenue),
            "missing_cogs": not has_cogs,
        })

    # Có lãi tính được xếp trước (theo lãi giảm dần); thiếu giá vốn xếp sau
    # (theo doanh thu) — không trộn lẫn hai loại vào một thang đo.
    rows.sort(key=lambda r: (r["gross_profit"] is None,
                             -(r["gross_profit"] or 0),
                             -r["revenue"]))
    return rows[:top_n]


__all__ = [
    "SaleLine",
    "ExpenseLine",
    "ReportRequest",
    "GRANULARITIES",
    "period_key",
    "build_report",
    "product_profitability",
]
