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

MỘT NGOẠI LỆ: POST /tools/inventory-import nhận multipart file thay vì JSON, nên
CỐ Ý không nằm trong manifest — model không sinh ra được một file upload, và
`_TOOL_IMPL` gọi handler theo dạng `handler(model, token)` mà chữ ký của nó khác.
Đưa vào manifest là quảng cáo với MCP client một tool gọi kiểu gì cũng hỏng.
Đường đi của nó là Body -> Brain, không phải model -> Brain.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any, Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from src.api.dependencies import MAX_UPLOAD_BYTES, require_api_token
from src.core import carrier_selection as cs
from src.core import forecasting as fc
from src.core import inventory as inv
from src.core import inventory_import as inv_import
from src.core import partner_import as pi
from src.core import period_diff as pdiff
from src.core import receivables as rcv
from src.core import reporting as rp
from src.core import vat_catalog as vc
from src.core.mcp_server import MCPServer
from src.core.pricing import PricingRule, Surcharge, compute_quote

logger = logging.getLogger("projecta.api.tools")
router = APIRouter(prefix="/tools")


async def _doc_file(request: Request, file: UploadFile) -> bytes:
    """
    Đọc file tải lên vào bộ nhớ, chặn hai lần theo kích thước.

    Kiểm `content-length` trước để từ chối sớm, rồi kiểm lại độ dài thật vì
    header đó do client gửi và hoàn toàn có thể nói dối. File KHÔNG ghi ra đĩa:
    sổ sách của khách không nằm lại trên máy Brain (P2 — Brain có thể đang chạy
    trên GPU thuê).
    """
    if int(request.headers.get("content-length") or "0") > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File quá lớn")
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File quá lớn")
    return data


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
    """POST /tools/vat — tính lại tổng hoá đơn, bọc MCPServer sẵn có.

    `is_reduced_vat` là đầu vào của tool này. Muốn biết một mã hàng có thuộc
    diện giảm không thì hỏi `vat_catalog_audit` — nơi giữ bảng tra kèm căn cứ.
    """
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


class PartnerIn(BaseModel):
    """Một dòng DANH SÁCH KHÁCH HÀNG hoặc NHÀ CUNG CẤP."""
    code: str
    name: str = ""
    address: str = ""
    balance: Optional[float] = Field(
        None, description="Số dư công nợ. Bỏ trống = CHƯA BIẾT, không phải 0"
    )
    tax_id: str = ""
    phone: str = ""


class PartnerAuditRequest(BaseModel):
    """POST /tools/partner-audit — soi công nợ từ số dư đối tác."""
    customers: list[PartnerIn] = []
    suppliers: list[PartnerIn] = []
    cogs_per_day: Optional[float] = Field(
        None, gt=0,
        description="Giá vốn bán ra mỗi ngày, để quy phải thu ra số ngày. "
                    "Bỏ trống thì bỏ qua phép kiểm đó chứ không đoán.",
    )


class ProductIn(BaseModel):
    """Một dòng DANH SÁCH HÀNG HÓA, DỊCH VỤ."""
    code: str
    name: str = ""
    vat_flag: str = Field("", description="Cột 'Giảm 2% thuế suất thuế GTGT' của MISA")
    group: str = ""
    unit: str = ""
    qty: Optional[float] = None
    value: Optional[float] = None


class VatCatalogRequest(BaseModel):
    """POST /tools/vat-catalog-audit — đối chiếu cờ thuế với Nghị định 174/2025."""
    products: list[ProductIn]


class PeriodSideIn(BaseModel):
    """Một lần xuất báo cáo tồn kho, kèm kỳ và kho của chính nó."""
    lines: list[InventoryLineIn]
    warehouse: str = ""
    period_start: Optional[str] = Field(None, description="YYYY-MM-DD")
    period_end: Optional[str] = Field(None, description="YYYY-MM-DD")


class PeriodDiffRequest(BaseModel):
    """POST /tools/period-diff — so hai lần xuất CÙNG một kỳ."""
    truoc: PeriodSideIn = Field(..., description="Bản xuất SỚM hơn")
    sau: PeriodSideIn = Field(..., description="Bản xuất MUỘN hơn")


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


@router.post("/inventory-import")
async def tool_inventory_import(
    request: Request,
    file: UploadFile = File(..., description="Bảng tổng hợp N-X-T do MISA/Fast/Bravo xuất (.xlsx)"),
    sheet: Optional[str] = Form(None),
    x_api_token: Optional[str] = Header(None),
):
    """
    Nạp bảng tổng hợp tồn kho từ .xlsx rồi kiểm luôn — một lần gửi file.

    Ngoại lệ có chủ ý so với phần còn lại của router: các endpoint khác nhận
    JSON thuần, endpoint này nhận file. Lý do là phần khó nhất của kiểm kho
    KHÔNG nằm ở phép kiểm mà ở chỗ đọc đúng bảng — bắt Body tự dựng lại ba lớp
    tự kiểm của `inventory_import` là chép logic sang ngôn ngữ thứ hai rồi để
    nó trôi khỏi bản gốc (P4).

    File KHÔNG được ghi ra đĩa: đọc thẳng từ bộ nhớ rồi thả (P2 — sổ kho của
    khách không nằm lại trên máy Brain, nhất là khi Brain chạy GPU thuê).

    Đọc hỏng thì KHÔNG kiểm. Một bảng bị lệch cột vẫn cho ra bản kiểm sạch bong
    trông rất thuyết phục — mọi con số đều sai nhưng không phép kiểm nào nhận ra,
    vì chúng vẫn cân đối với nhau ở cột bên cạnh.
    """
    require_api_token(x_api_token)
    data = await _doc_file(request, file)

    try:
        res = inv_import.load_xlsx_bytes(data, sheet=sheet)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:  # thiếu openpyxl — lỗi cài đặt, không phải lỗi file
        raise HTTPException(status_code=503, detail=str(exc))

    payload: dict[str, Any] = {
        "import": {
            "ok": res.ok,
            "file_name": file.filename,
            "warehouse": res.warehouse,
            "period_start": res.period_start,
            "period_end": res.period_end,
            "rows_parsed": len(res.lines),
            "warnings": res.warnings,
            "checks": res.checks,
            "lines": [asdict(ln) for ln in res.lines],
        },
        "unit_costs": [],
        "audit": None,
        "audit_skipped_reason": None,
    }

    if not res.ok:
        # `unit_costs` cũng để rỗng, cùng một lý do với `audit`: giá vốn suy ra
        # từ bảng đọc lệch cột là số sai, mà nó lại đi thẳng vào cột giá vốn của
        # từng mặt hàng rồi ở lại đó. Sai kiểu này còn khó lần ra hơn cả một bản
        # kiểm sai, vì bản kiểm thì người ta đọc rồi bỏ, còn giá vốn thì nằm lại
        # và âm thầm chảy vào mọi báo cáo lãi lỗ sau này.
        payload["audit_skipped_reason"] = (
            "Chưa đọc chắc chắn được bảng nên không kiểm và không lấy giá vốn — "
            "xem 'checks'. Kiểm trên dữ liệu đọc sai còn nguy hơn không kiểm: "
            "kết quả trông sạch sẽ và thuyết phục trong khi mọi con số đã lệch cột."
        )
        return payload

    # Giá vốn suy ra được cho từng mã, KÈM chỗ lấy ra. Body dùng bảng này để
    # điền cột giá vốn đang rỗng. Đưa kèm ở đây thay vì để Body tự chia
    # giá_trị/số_lượng: thứ tự ưu tiên (xuất -> tồn cuối -> tồn đầu) là quy tắc
    # nghiệp vụ, chép sang TypeScript là tạo bản sao thứ hai rồi để nó trôi khỏi
    # bản gốc (P4).
    payload["unit_costs"] = [
        {"code": ln.code, "name": ln.name, "unit": ln.unit,
         "unit_cost": round(cost), "source": source}
        for ln, (cost, source) in ((ln, inv.unit_cost_of(ln)) for ln in res.lines)
        if cost is not None
    ]

    payload["audit"] = inv.audit_inventory(
        res.lines,
        warehouse=res.warehouse,
        period_start=res.period_start,
        period_end=res.period_end,
    )
    return payload


@router.post("/partner-audit")
async def tool_partner_audit(
    req: PartnerAuditRequest, x_api_token: Optional[str] = Header(None)
):
    """
    Soi công nợ từ số dư khách hàng và nhà cung cấp.

    Với doanh nghiệp phân phối, tiền nằm ở khách thường NHIỀU HƠN tiền nằm ở
    kho — số thật của khách đầu tiên: phải thu 3,96 tỷ so với tồn kho 2,87 tỷ.
    Phần mềm kế toán trình bày công nợ dưới dạng danh sách, mà danh sách thì
    không cho thấy hai khách đang giữ 56% số tiền chưa về.

    Không tính được tuổi nợ vì số dư không kèm ngày hoá đơn; giới hạn đó được
    ghi thẳng trong `summary.không_phân_tích_được`.
    """
    require_api_token(x_api_token)
    try:
        return rcv.audit_partners(
            [pi.Partner(**p.model_dump(), role=pi.KHACH_HANG) for p in req.customers],
            [pi.Partner(**p.model_dump(), role=pi.NHA_CUNG_CAP) for p in req.suppliers],
            gia_von_moi_ngay=req.cogs_per_day,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/vat-catalog-audit")
async def tool_vat_catalog_audit(
    req: VatCatalogRequest, x_api_token: Optional[str] = Header(None)
):
    """
    Đối chiếu cờ 'Giảm 2% thuế suất thuế GTGT' trong danh mục với quy định hiện hành.

    Nghị định 174/2025/NĐ-CP đã bỏ 'sản phẩm dầu mỏ tinh chế' — trong đó có dầu
    mỡ bôi trơn — khỏi danh mục KHÔNG được giảm, hiệu lực 01/7/2025 đến hết
    31/12/2026. Nhiều năm trước nhóm này chịu 10%, nên thói quen cũ đang dẫn
    tới thuế suất sai.

    Tool ĐỀ XUẤT, không quyết định: mã nào bảng tra không chắc thì nói thẳng là
    cần kế toán xác nhận, và mọi kết luận đều kèm căn cứ để kiểm lại.
    """
    require_api_token(x_api_token)
    try:
        return vc.audit_vat_catalog([vc.SanPham(**p.model_dump()) for p in req.products])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/period-diff")
async def tool_period_diff(
    req: PeriodDiffRequest, x_api_token: Optional[str] = Header(None)
):
    """
    So HAI lần xuất cùng một kỳ để tìm chứng từ bị sửa sau khi đã báo cáo.

    CỐ Ý KHÔNG NẰM TRONG MANIFEST, cùng lý do với /tools/inventory-import: tool
    này cần hai bản báo cáo của hai thời điểm khác nhau. Model trong vòng
    agentic không có cách nào lấy được bản xuất tháng trước — đưa vào manifest
    là quảng cáo một tool mà mọi lần gọi đều thiếu dữ liệu.

    Đường đi của nó là Body -> Brain: người dùng chọn hai file đã tải lên.
    """
    require_api_token(x_api_token)

    def _dung(side: PeriodSideIn) -> inv_import.ParseResult:
        return inv_import.ParseResult(
            lines=[inv.InventoryLine(**ln.model_dump()) for ln in side.lines],
            warehouse=side.warehouse,
            period_start=side.period_start,
            period_end=side.period_end,
        )

    try:
        return pdiff.doi_chieu_hai_lan_xuat(_dung(req.truoc), _dung(req.sau))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/partner-import")
async def tool_partner_import(
    request: Request,
    file: UploadFile = File(..., description="Danh sách khách hàng / nhà cung cấp MISA (.xlsx)"),
    sheet: Optional[str] = Form(None),
    role: str = Form("", description="Bỏ trống thì tự đoán từ tiêu đề file"),
    x_api_token: Optional[str] = Header(None),
):
    """
    Nạp danh sách đối tác từ .xlsx rồi soi công nợ luôn — một lần gửi file.

    Cùng nguyên tắc với inventory-import: file KHÔNG ghi ra đĩa (P2), và đọc
    hỏng thì KHÔNG soi. Ở bảng này lớp tự kiểm là cột STT, vì dòng 'Tổng' của
    MISA bỏ trống mọi cột số nên không đối chiếu tổng được.
    """
    require_api_token(x_api_token)
    data = await _doc_file(request, file)
    try:
        res = pi.load_partners_xlsx_bytes(data, sheet=sheet, role=role.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    payload: dict[str, Any] = {
        "import": {
            "ok": res.ok, "file_name": file.filename, "role": res.role,
            "rows_parsed": len(res.partners), "warnings": res.warnings,
            "checks": res.checks,
            "partners": [asdict(p) for p in res.partners],
        },
        "audit": None,
        "audit_skipped_reason": None,
    }
    if not res.ok:
        payload["audit_skipped_reason"] = (
            "Chưa đọc chắc chắn được danh sách nên không soi công nợ — xem 'checks'. "
            "Soi trên dữ liệu thiếu dòng sẽ cho ra tỷ lệ tập trung sai mà vẫn trông hợp lý."
        )
        return payload

    khach = res.partners if res.role != pi.NHA_CUNG_CAP else []
    ncc = res.partners if res.role == pi.NHA_CUNG_CAP else []
    payload["audit"] = rcv.audit_partners(khach, ncc)
    return payload


@router.post("/product-import")
async def tool_product_import(
    request: Request,
    file: UploadFile = File(..., description="Danh sách hàng hóa, dịch vụ MISA (.xlsx)"),
    sheet: Optional[str] = Form(None),
    x_api_token: Optional[str] = Header(None),
):
    """Nạp danh mục hàng hoá từ .xlsx rồi đối chiếu cờ thuế GTGT luôn."""
    require_api_token(x_api_token)
    data = await _doc_file(request, file)
    try:
        res = vc.load_products_xlsx_bytes(data, sheet=sheet)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    payload: dict[str, Any] = {
        "import": {
            "ok": res.ok, "file_name": file.filename,
            "rows_parsed": len(res.products), "warnings": res.warnings,
            "checks": res.checks,
            "products": [asdict(p) for p in res.products],
        },
        "audit": None,
        "audit_skipped_reason": None,
    }
    if not res.ok:
        payload["audit_skipped_reason"] = (
            "Chưa đọc chắc chắn được danh mục nên không đối chiếu thuế suất — xem 'checks'."
        )
        return payload
    payload["audit"] = vc.audit_vat_catalog(res.products)
    return payload


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
        "description": (
            "Tính lại tổng hoá đơn + VAT bằng code thuần từ đơn giá, số lượng và "
            "diện thuế của từng dòng. Diện thuế là ĐẦU VÀO — dùng vat_catalog_audit "
            "để biết mã hàng nào thuộc diện 8%."
        ),
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
    {
        "name": "partner_audit",
        "method": "POST",
        "path": "/tools/partner-audit",
        "description": (
            "Soi công nợ từ số dư khách hàng và nhà cung cấp: mức độ tập trung "
            "(một khách giữ bao nhiêu phần trăm tiền chưa về), số dư ngược dấu, "
            "đối tác vừa mua vừa bán có thể bù trừ, mã số thuế sai hoặc trùng, "
            "phải thu quy ra bao nhiêu ngày giá vốn. KHÔNG tính được tuổi nợ vì "
            "số dư không kèm ngày hoá đơn."
        ),
        "input_schema": PartnerAuditRequest.model_json_schema(),
    },
    {
        "name": "vat_catalog_audit",
        "method": "POST",
        "path": "/tools/vat-catalog-audit",
        "description": (
            "Đối chiếu cờ 'Giảm 2% thuế suất thuế GTGT' của từng mã hàng với "
            "Nghị quyết 204/2025/QH15 và Nghị định 174/2025/NĐ-CP (hiệu lực "
            "01/7/2025 đến 31/12/2026). Chỉ ra mã nào thuộc diện 8%, mã nào giữ "
            "10%, mã nào cần kế toán xác nhận. Là ĐỀ XUẤT kèm căn cứ, không phải "
            "quyết định thay kế toán."
        ),
        "input_schema": VatCatalogRequest.model_json_schema(),
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
    "partner_audit": (PartnerAuditRequest, tool_partner_audit),
    "vat_catalog_audit": (VatCatalogRequest, tool_vat_catalog_audit),
}


def get_tool_request_model(name: str) -> type[BaseModel] | None:
    """
    Pydantic model của tham số một tool. None = không có tool đó.

    Có mặt để benchmark chấm được "model điền tham số đúng kiểu chưa" bằng ĐÚNG
    lớp validate mà endpoint dùng lúc chạy thật — chấm bằng một bản kiểm riêng
    thì điểm đẹp mà production vẫn 422 (P4).
    """
    entry = _TOOL_IMPL.get(name)
    return entry[0] if entry else None


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
