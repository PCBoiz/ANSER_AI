"""
src/core/freight_invoice.py — hoá đơn CƯỚC VẬN TẢI: lược đồ + kiểm số học.

VÌ SAO KHÔNG DÙNG `InvoicePayload`
---------------------------------
`InvoicePayload` là `{items: [{name, price, qty}], total}` — lược đồ hoá đơn BÁN
LẺ. Hoá đơn nhà xe không có hình dạng đó. Nó có tuyến (điểm đi/điểm đến), loại
xe, biển số, số chuyến, và một loạt phụ phí đứng riêng: bốc xếp, lưu ca, cầu
đường, phí quay đầu. Nhét chúng vào `items` là mất hết ý nghĩa — không phân biệt
được "3 chuyến × 12 triệu" với "3 khoản phụ phí", nên không kiểm chéo được gì.

TẤT ĐỊNH TRƯỚC (P1)
-------------------
VLM chỉ ĐỌC CHỮ. Mọi phép cộng nhân đều tính lại ở đây bằng code thuần, rồi đối
chiếu với con số in trên tờ hoá đơn. Lệch thì báo — KHÔNG tự sửa, và KHÔNG âm
thầm dùng số mình tính.

Đây là lớp phòng thủ quan trọng nhất của cả nhánh VLM: nó bắt được lỗi đọc mà
không cần người ngồi soi. Đọc nhầm `12.000.000` thành `72.000.000` thì tổng
không khớp và hệ thống tự biết mình sai. Sai mà biết mình sai thì còn dùng được;
sai mà tự tin thì không.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

# Kế toán làm tròn đến đồng; đừng báo lệch vì chênh 1 đồng do làm tròn VAT.
ABS_TOL_VND = 1000.0
REL_TOL = 0.005     # 0,5%


class FreightCharge(BaseModel):
    """Một khoản trên hoá đơn: cước chuyến hoặc phụ phí."""
    kind: Literal["cước", "bốc xếp", "lưu ca", "cầu đường", "quay đầu", "khác"] = "khác"
    description: str = ""
    quantity: float = Field(1.0, ge=0, description="Số chuyến / số lần / số tấn")
    unit_price: float = Field(..., ge=0, description="Đơn giá (VND), CHƯA thuế")

    @property
    def amount(self) -> float:
        return self.quantity * self.unit_price


class FreightInvoice(BaseModel):
    """
    Hoá đơn cước vận tải do nhà xe phát hành.

    Trường `Optional` là CHƯA ĐỌC ĐƯỢC, không phải bằng 0 — cùng nguyên tắc với
    `reporting.py`. Hoá đơn viết tay mờ có thể không đọc ra biển số, nhưng vẫn
    đọc được tổng tiền; ép về 0 là bịa ra một khẳng định.
    """
    carrier_name: Optional[str] = Field(None, description="Tên nhà xe")
    carrier_tax_code: Optional[str] = Field(None, description="MST nhà xe")
    invoice_no: Optional[str] = None
    invoice_date: Optional[str] = Field(None, description="YYYY-MM-DD")

    origin: Optional[str] = Field(None, description="Điểm đi")
    destination: Optional[str] = Field(None, description="Điểm đến")
    vehicle_type: Optional[str] = Field(None, description="xe tải 5 tấn, container 20ft...")
    plate_number: Optional[str] = Field(None, description="Biển số xe")

    charges: list[FreightCharge] = Field(default_factory=list)

    vat_rate: Optional[float] = Field(None, ge=0, le=100, description="% VAT ghi trên hoá đơn")
    subtotal: Optional[float] = Field(None, ge=0, description="Cộng tiền hàng ghi trên hoá đơn")
    vat_amount: Optional[float] = Field(None, ge=0, description="Tiền thuế ghi trên hoá đơn")
    total: Optional[float] = Field(None, ge=0, description="TỔNG CỘNG ghi trên hoá đơn")

    @field_validator("invoice_date")
    @classmethod
    def _date_shape(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not v.strip():
            return None
        return v.strip()


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(ABS_TOL_VND, REL_TOL * max(abs(a), abs(b)))


def verify(invoice: FreightInvoice) -> dict[str, Any]:
    """
    Tính lại toàn bộ số tiền bằng code, đối chiếu với số in trên hoá đơn.

    Trả về `ok` CHỈ khi mọi phép đối chiếu làm được đều khớp. Thiếu dữ liệu để
    đối chiếu thì `ok` là False kèm lý do — "không kiểm được" khác hẳn "đã kiểm
    và đúng", và gộp hai thứ đó lại là cách nhanh nhất để một tờ hoá đơn sai đi
    lọt.
    """
    issues: list[str] = []
    checks: list[str] = []

    tinh_subtotal = sum(c.amount for c in invoice.charges)

    if not invoice.charges:
        issues.append("Không đọc được khoản nào — chưa có gì để kiểm.")

    # 1) Cộng tiền hàng
    if invoice.subtotal is not None and invoice.charges:
        checks.append("cộng_tiền_hàng")
        if not _close(tinh_subtotal, invoice.subtotal):
            issues.append(
                f"Cộng tiền hàng lệch: tính lại {tinh_subtotal:,.0f} nhưng hoá đơn ghi "
                f"{invoice.subtotal:,.0f} (chênh {abs(tinh_subtotal - invoice.subtotal):,.0f})"
            )

    goc = invoice.subtotal if invoice.subtotal is not None else tinh_subtotal

    # 2) Tiền thuế
    tinh_vat: Optional[float] = None
    if invoice.vat_rate is not None and goc:
        tinh_vat = goc * invoice.vat_rate / 100.0
        if invoice.vat_amount is not None:
            checks.append("tiền_thuế")
            if not _close(tinh_vat, invoice.vat_amount):
                issues.append(
                    f"Tiền thuế lệch: {invoice.vat_rate:g}% của {goc:,.0f} là "
                    f"{tinh_vat:,.0f} nhưng hoá đơn ghi {invoice.vat_amount:,.0f}"
                )

    # 3) Tổng cộng — trường quan trọng nhất
    vat_dung = invoice.vat_amount if invoice.vat_amount is not None else (tinh_vat or 0.0)
    tinh_total = goc + vat_dung
    if invoice.total is not None:
        checks.append("tổng_cộng")
        if not _close(tinh_total, invoice.total):
            issues.append(
                f"Tổng cộng lệch: tính lại {tinh_total:,.0f} nhưng hoá đơn ghi "
                f"{invoice.total:,.0f} (chênh {abs(tinh_total - invoice.total):,.0f})"
            )
    else:
        issues.append("Không đọc được TỔNG CỘNG — trường bắt buộc.")

    return {
        # `ok` đòi CẢ HAI: không có vấn đề nào, VÀ đã thật sự kiểm được ít nhất
        # một phép. Không có vế sau thì một tờ đọc ra rỗng cũng "ok".
        "ok": not issues and bool(checks),
        "checks_performed": checks,
        "issues": issues,
        "computed": {
            "subtotal": round(tinh_subtotal),
            "vat_amount": None if tinh_vat is None else round(tinh_vat),
            "total": round(tinh_total),
        },
        "stated": {
            "subtotal": invoice.subtotal,
            "vat_amount": invoice.vat_amount,
            "total": invoice.total,
        },
        # Trường bắt buộc đúng thì mới dùng được; thiếu thì phải người xem lại.
        "missing_required": [
            ten for ten, gt in (
                ("carrier_name", invoice.carrier_name),
                ("invoice_date", invoice.invoice_date),
                ("total", invoice.total),
            ) if gt in (None, "")
        ],
    }


def json_schema() -> dict[str, Any]:
    """Lược đồ cho `guided_json` — ép VLM sinh đúng hình dạng ngay lúc giải mã."""
    return FreightInvoice.model_json_schema()


__all__ = ["FreightCharge", "FreightInvoice", "json_schema", "verify"]
