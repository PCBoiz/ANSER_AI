"""
src/api/routes/tools.py — tầng tool TẤT ĐỊNH của Brain, expose qua REST.

KIẾN TRÚC (chốt 27/07/2026, xem ARCHITECTURE.md §7)
---------------------------------------------------
"Lai: tính ở Brain, DB ở rag_service" — mọi endpoint ở đây là HÀM THUẦN qua HTTP:
dữ liệu vào trong request body, kết quả cấu trúc trong response. KHÔNG đọc DB,
KHÔNG giữ trạng thái, KHÔNG gọi LLM. Phần chở dữ liệu (đọc Google Sheet, ghi qua
rag_service) do n8n workflow hoặc vòng agentic đảm nhiệm — cùng một endpoint phục
vụ cả hai (mẫu y hệt rag_service:8001 mà đội đã dùng trong 32 workflow thật).

Stateless đem lại: test không cần DB, không rò dữ liệu khách qua Brain host (P2
khi thuê GPU), và n8n gọi bằng node httpRequest — node phổ biến nhất (84/262)
trong template thật.

GET /tools trả manifest (tên + mô tả + JSON Schema vào/ra) — vòng agentic dùng
làm danh mục tool-calling, và lớp MCP sau này bọc đúng manifest này ("MCP bọc
REST"). Định nghĩa MỘT lần ở đây, ba nơi dùng chung (P4).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from src.api.dependencies import require_api_token
from src.core import carrier_selection as cs
from src.core import forecasting as fc
from src.core import inventory as inv
from src.core import reporting as rp
from src.core.mcp_server import MCPServer
from src.core.pricing import PricingRule, Surcharge, compute_quote

logger = logging.getLogger("projecta.api.tools")
router = APIRouter(prefix="/tools")


# ===========================================================================
# Schemas vào/ra
# ===========================================================================

class SurchargeIn(BaseModel):
    name: str
    amount: float = 0.0
    pct: float = Field(0.0, ge=0, le=100)


class PricingRuleIn(BaseModel):
    base_margin_pct: float = Field(..., ge=0)
    fuel_sensitivity: float = Field(0.35, ge=0, le=1)
    fuel_baseline_price: Optional[float] = Field(None, gt=0)
    min_margin_amount: float = Field(0.0, ge=0)
    surcharges: list[SurchargeIn] = []


class QuoteRequest(BaseModel):
    """POST /tools/quote — tính báo giá từ giá nhà xe + quy tắc + giá dầu."""
    carrier_cost: float = Field(..., gt=0, description="Giá nhà xe chào (VND)")
    pricing_rule: PricingRuleIn
    current_fuel_price: Optional[float] = Field(None, gt=0)
    extra_surcharges: list[SurchargeIn] = []


class CarrierIn(BaseModel):
    id: str | int
    name: str
    vehicle_types: list[str] = []
    depot_lat: Optional[float] = None
    depot_lon: Optional[float] = None
    discount_pct: Optional[float] = None
    credit_days: Optional[int] = None
    years_partner: Optional[float] = None
    on_time_rate: Optional[float] = Field(None, ge=0, le=1)


class OfferIn(BaseModel):
    carrier_id: str | int
    price: float = Field(..., gt=0)
    valid_to: Optional[str] = None


class RouteRequestIn(BaseModel):
    origin: str
    destination: str
    vehicle_type: str
    origin_lat: Optional[float] = None
    origin_lon: Optional[float] = None
    cargo_type: Optional[str] = None
    pickup_date: Optional[str] = None


class CarrierSelectionRequest(BaseModel):
    """POST /tools/carrier-selection — xếp hạng hãng xe cho một chuyến."""
    carriers: list[CarrierIn]
    offers: list[OfferIn]
    request: RouteRequestIn
    weights: Optional[dict[str, float]] = None


class ForecastItem(BaseModel):
    sku: str
    series: list[float] = Field(..., description="Nhu cầu theo kỳ, cũ -> mới")
    current_stock: Optional[float] = None
    lead_time_periods: float = Field(..., ge=0)


class ForecastRequest(BaseModel):
    """POST /tools/forecast-reorder — Croston/SBA + điểm đặt hàng lại theo lô."""
    items: list[ForecastItem]
    service_level: float = 0.95
    review_periods: float = Field(0.0, ge=0)


class VatRequest(BaseModel):
    """POST /tools/vat — VAT NĐ 72/2024, bọc MCPServer sẵn có."""
    items: list[dict]
    stated_total: float
    default_is_reduced: bool = False


class SaleLineIn(BaseModel):
    date: str = Field(..., description="Ngày bán, YYYY-MM-DD")
    revenue: float = Field(..., description="Tiền thu về, đã trừ chiết khấu (VND)")
    product: str = ""
    quantity: float = 0.0
    cogs: Optional[float] = Field(
        None, description="Giá vốn hàng bán. Bỏ trống = CHƯA BIẾT, không phải 0"
    )


class ExpenseLineIn(BaseModel):
    date: str = Field(..., description="Ngày phát sinh, YYYY-MM-DD")
    amount: float
    category: str = "khác"


class ReportRequestIn(BaseModel):
    """POST /tools/report — DT/CP/LN theo kỳ + xếp hạng mặt hàng."""
    granularity: str = Field("quarter", description="month | quarter | half | year")
    periods_back: int = Field(4, ge=1, le=40)
    top_n: int = Field(10, ge=1, le=100)
    sales: list[SaleLineIn] = []
    expenses: list[ExpenseLineIn] = []


class InventoryLineIn(BaseModel):
    """Một dòng bảng TỔNG HỢP TỒN KHO (bản xuất MISA/Fast/Bravo)."""
    code: str
    name: str = ""
    unit: str = ""
    opening_qty: float = 0.0
    opening_value: Optional[float] = Field(None, description="Bỏ trống = CHƯA BIẾT, không phải 0")
    in_qty: float = 0.0
    in_value: Optional[float] = None
    out_qty: float = 0.0
    out_value: Optional[float] = Field(None, description="Giá trị xuất kho = giá vốn hàng bán")
    closing_qty: float = 0.0
    closing_value: Optional[float] = None


class InventoryAuditRequest(BaseModel):
    """POST /tools/inventory-audit — soi lỗi sổ sách trên bảng tổng hợp tồn kho."""
    lines: list[InventoryLineIn]
    warehouse: str = ""
    period_start: Optional[str] = Field(None, description="YYYY-MM-DD")
    period_end: Optional[str] = Field(None, description="YYYY-MM-DD")


# ===========================================================================
# Endpoints
# ===========================================================================

@router.post("/quote")
async def tool_quote(req: QuoteRequest, x_api_token: Optional[str] = Header(None)):
    require_api_token(x_api_token)
    try:
        rule = PricingRule(
            base_margin_pct=req.pricing_rule.base_margin_pct,
            fuel_sensitivity=req.pricing_rule.fuel_sensitivity,
            fuel_baseline_price=req.pricing_rule.fuel_baseline_price,
            min_margin_amount=req.pricing_rule.min_margin_amount,
            surcharges=[Surcharge(**s.model_dump()) for s in req.pricing_rule.surcharges],
        )
        return compute_quote(
            carrier_cost=req.carrier_cost,
            rule=rule,
            current_fuel_price=req.current_fuel_price,
            extra_surcharges=[Surcharge(**s.model_dump()) for s in req.extra_surcharges],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/carrier-selection")
async def tool_carrier_selection(
    req: CarrierSelectionRequest, x_api_token: Optional[str] = Header(None)
):
    require_api_token(x_api_token)
    carriers = [
        cs.Carrier(
            id=c.id, name=c.name, vehicle_types=set(c.vehicle_types),
            depot_lat=c.depot_lat, depot_lon=c.depot_lon,
            discount_pct=c.discount_pct, credit_days=c.credit_days,
            years_partner=c.years_partner, on_time_rate=c.on_time_rate,
        )
        for c in req.carriers
    ]
    offers = [
        cs.QuoteOffer(carrier_id=o.carrier_id, price=o.price, valid_to=o.valid_to)
        for o in req.offers
    ]
    route = cs.RouteRequest(**req.request.model_dump())
    return cs.select_carrier(carriers, offers, route, weights=req.weights)


@router.post("/forecast-reorder")
async def tool_forecast_reorder(
    req: ForecastRequest, x_api_token: Optional[str] = Header(None)
):
    """
    Bản nâng cấp của rag_service /forecast-reorder (trung bình trượt trần):
    Croston/SBA cho nhu cầu gián đoạn + tồn an toàn theo mức phục vụ + MASE +
    mức tin cậy. Workflow chỉ cần đổi env var từ RAG_BASE_URL sang
    BRAIN_BASE_URL để chuyển; rollback = đổi lại.
    """
    require_api_token(x_api_token)
    results, errors = [], []
    for item in req.items:
        try:
            out = fc.reorder_point(
                item.series,
                lead_time_periods=item.lead_time_periods,
                service_level=req.service_level,
                current_stock=item.current_stock,
                review_periods=req.review_periods,
            )
            out["sku"] = item.sku
            results.append(out)
        except ValueError as exc:
            errors.append({"sku": item.sku, "error": str(exc)})

    suggestions = [r for r in results if r.get("should_order")]
    return {
        "count": len(suggestions),
        "suggestions": suggestions,     # giữ tên trường giống rag_service để n8n if-node dùng lại
        "all_items": results,
        "errors": errors,
        "service_level": req.service_level,
    }


@router.post("/vat")
async def tool_vat(req: VatRequest, x_api_token: Optional[str] = Header(None)):
    require_api_token(x_api_token)
    return MCPServer.validate_invoice_total(
        req.items, req.stated_total, default_is_reduced=req.default_is_reduced
    )


@router.post("/report")
async def tool_report(req: ReportRequestIn, x_api_token: Optional[str] = Header(None)):
    """
    Báo cáo doanh thu / giá vốn / lãi theo kỳ + xếp hạng mặt hàng.

    Thay cho đường "LLM viết SQL": số tài chính sai mà nghe có vẻ đúng là loại
    lỗi không ai phát hiện cho tới lúc quyết toán (quyết định 27/07/2026).
    """
    require_api_token(x_api_token)
    try:
        return rp.build_report(rp.ReportRequest(
            granularity=req.granularity,
            periods_back=req.periods_back,
            top_n=req.top_n,
            sales=[rp.SaleLine(**s.model_dump()) for s in req.sales],
            expenses=[rp.ExpenseLine(**e.model_dump()) for e in req.expenses],
        ))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/inventory-audit")
async def tool_inventory_audit(
    req: InventoryAuditRequest, x_api_token: Optional[str] = Header(None)
):
    """
    Soi lỗi sổ sách trên bảng TỔNG HỢP TỒN KHO.

    Bảng kế toán xuất ra LUÔN cân đối về cộng trừ — phần mềm tự tính. Cân đối
    không có nghĩa là đúng: tồn âm, đơn giá tồn cuối vượt mọi giá đầu vào, và
    hai phương pháp tính giá vốn chạy song song đều nằm dưới lớp cân đối đó.
    Mỗi phát hiện ở đây là một bất đẳng thức số học kèm bằng chứng, không suy đoán.
    """
    require_api_token(x_api_token)
    try:
        return inv.audit_inventory(
            [inv.InventoryLine(**ln.model_dump()) for ln in req.lines],
            warehouse=req.warehouse,
            period_start=req.period_start,
            period_end=req.period_end,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ===========================================================================
# Manifest — nguồn cho agentic tool-calling và lớp MCP sau này
# ===========================================================================

_TOOL_DEFS: list[dict[str, Any]] = [
    {
        "name": "quote",
        "method": "POST",
        "path": "/tools/quote",
        "description": (
            "Tính báo giá vận tải: giá nhà xe + điều chỉnh nhiên liệu theo giá dầu "
            "+ phụ phí + biên. Trả 'quote' (đưa khách cuối) và 'internal' (nội bộ, có biên)."
        ),
        "input_schema": QuoteRequest.model_json_schema(),
    },
    {
        "name": "carrier_selection",
        "method": "POST",
        "path": "/tools/carrier-selection",
        "description": (
            "Xếp hạng hãng xe cho một chuyến theo 6 tiêu chí có trọng số "
            "(giá, gần bãi, công nợ, đúng hẹn, ưu đãi, năm hợp tác). "
            "Trả breakdown truy vết được từng tiêu chí."
        ),
        "input_schema": CarrierSelectionRequest.model_json_schema(),
    },
    {
        "name": "forecast_reorder",
        "method": "POST",
        "path": "/tools/forecast-reorder",
        "description": (
            "Dự báo nhu cầu (Croston/SBA cho nhu cầu gián đoạn) + điểm đặt hàng lại "
            "có tồn an toàn theo mức phục vụ. Kèm mức tin cậy và cảnh báo."
        ),
        "input_schema": ForecastRequest.model_json_schema(),
    },
    {
        "name": "vat",
        "method": "POST",
        "path": "/tools/vat",
        "description": "Tính lại tổng hoá đơn + VAT theo NĐ 72/2024 bằng code thuần.",
        "input_schema": VatRequest.model_json_schema(),
    },
    {
        "name": "report",
        "method": "POST",
        "path": "/tools/report",
        "description": (
            "Báo cáo doanh thu / giá vốn / lãi gộp / lãi ròng theo kỳ "
            "(tháng, quý, nửa năm, năm) kèm tăng trưởng so với kỳ trước và "
            "xếp hạng mặt hàng theo lãi. Báo rõ phần doanh thu chưa có giá vốn."
        ),
        "input_schema": ReportRequestIn.model_json_schema(),
    },
    {
        "name": "inventory_audit",
        "method": "POST",
        "path": "/tools/inventory-audit",
        "description": (
            "Soi lỗi sổ sách trên bảng tổng hợp tồn kho: tồn âm, đơn giá tồn cuối "
            "vượt mọi giá đầu vào, hai phương pháp tính giá vốn chạy song song, "
            "hàng chết, hàng bán chậm, giá nhập nhảy vọt, hàng không ghi nhận giá trị. "
            "Mỗi phát hiện kèm bằng chứng số và ước lượng tiền bị ghi sai chỗ."
        ),
        "input_schema": InventoryAuditRequest.model_json_schema(),
    },
]


@router.get("")
async def tool_manifest():
    """Danh mục tool. Vòng agentic và lớp MCP đọc từ đây — không định nghĩa lại."""
    return {"tools": _TOOL_DEFS, "count": len(_TOOL_DEFS)}


def get_tool_defs() -> list[dict[str, Any]]:
    """Manifest cho vòng agentic + lớp MCP. MỘT định nghĩa, ba nơi dùng (P4)."""
    return _TOOL_DEFS


# Ánh xạ tên tool -> (model request, hàm xử lý). Vòng agentic và MCP gọi THẲNG
# hàm Python ở đây thay vì tự HTTP về chính mình: cùng process nên đi vòng qua
# mạng chỉ thêm độ trễ, thêm một chỗ hỏng, và cần token cho chính mình.
_TOOL_IMPL: dict[str, tuple[type[BaseModel], Any]] = {
    "quote": (QuoteRequest, tool_quote),
    "carrier_selection": (CarrierSelectionRequest, tool_carrier_selection),
    "forecast_reorder": (ForecastRequest, tool_forecast_reorder),
    "vat": (VatRequest, tool_vat),
    "report": (ReportRequestIn, tool_report),
    "inventory_audit": (InventoryAuditRequest, tool_inventory_audit),
}


async def run_tool(name: str, arguments: dict) -> Any:
    """
    Chạy một tool theo tên + tham số thô (từ model hoặc từ MCP client).

    Tham số được validate bằng ĐÚNG pydantic model của endpoint REST — model
    điền thiếu/sai kiểu thì báo lỗi có cấu trúc để vòng agentic sửa ở bước sau,
    thay vì ném ngoại lệ ra ngoài.
    """
    entry = _TOOL_IMPL.get(name)
    if entry is None:
        return {"error": f"không có tool tên '{name}'",
                "available": sorted(_TOOL_IMPL)}
    model_cls, handler = entry
    try:
        req = model_cls(**(arguments or {}))
    except Exception as exc:
        return {"error": "tham số không hợp lệ", "detail": str(exc)}
    try:
        # x_api_token=None: gọi nội bộ, đã qua kiểm tra token ở tầng /chat
        return await handler(req, None)
    except HTTPException as exc:
        return {"error": exc.detail}
    except Exception as exc:
        logger.warning("Tool %s lỗi: %s", name, exc)
        return {"error": str(exc)}


# ===========================================================================
# Lớp MCP — bọc đúng manifest trên ("MCP bọc REST", quyết định 27/07/2026)
# ===========================================================================
# Không định nghĩa lại tool. Chỉ dịch manifest sang hình dạng MCP để n8n
# (node MCP Client Tool) và mọi MCP host khác dùng được cùng bộ tool.

mcp_router = APIRouter(prefix="/mcp")


@mcp_router.get("/tools/list")
async def mcp_tools_list(x_api_token: Optional[str] = Header(None)):
    """tools/list của MCP — tên trường theo đúng đặc tả (inputSchema camelCase)."""
    require_api_token(x_api_token)
    return {
        "tools": [
            {
                "name": t["name"],
                "description": t["description"],
                "inputSchema": t["input_schema"],
            }
            for t in _TOOL_DEFS
        ]
    }


class MCPCallRequest(BaseModel):
    name: str
    arguments: dict = {}


@mcp_router.post("/tools/call")
async def mcp_tools_call(
    req: MCPCallRequest, x_api_token: Optional[str] = Header(None)
):
    """
    tools/call của MCP. Kết quả bọc trong `content` dạng text (JSON đã seri hoá)
    — đúng hình dạng MCP client mong đợi.

    `isError` bật khi tool trả về khối lỗi, để client phân biệt được "chạy xong
    nhưng thất bại" với "chạy thành công".
    """
    require_api_token(x_api_token)
    result = await run_tool(req.name, req.arguments)
    is_error = isinstance(result, dict) and "error" in result
    import json as _json
    return {
        "content": [{"type": "text",
                     "text": _json.dumps(result, ensure_ascii=False, default=str)}],
        "isError": is_error,
    }
