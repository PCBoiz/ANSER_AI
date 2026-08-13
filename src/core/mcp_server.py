"""
MCPServer — lớp tính toán tài chính DETERMINISTIC (KHÔNG dùng LLM).

Tính VAT và đối chiếu tổng hóa đơn bằng code thuần. Nguyên tắc
deterministic-first: mọi số tiền dùng cho sổ sách phải đi qua đây; không tin số
do LLM/VLM sinh ra mà không tính lại.

MODULE NÀY CHỈ TÍNH, KHÔNG QUYẾT ĐỊNH DIỆN THUẾ
-----------------------------------------------
`is_reduced` là ĐẦU VÀO, không phải thứ suy ra ở đây. Việc một mặt hàng có
thuộc diện giảm hay không là câu hỏi pháp lý theo từng mã hàng — thuộc về
`src/core/vat_catalog.py`, nơi có bảng tra kèm căn cứ và biết trả lời "chưa
xác định". Nhét bảng tra vào đây sẽ tạo bản sao thứ hai rồi để nó trôi khỏi bản
gốc mỗi lần luật đổi (P4).
"""
from decimal import ROUND_HALF_UP, Decimal

# Thuế suất GTGT (VAT).
#
# Mức giảm 2% hiện hành theo Nghị quyết 204/2025/QH15 và Nghị định
# 174/2025/NĐ-CP, áp dụng 01/7/2025 → 31/12/2026. Trước đó là Nghị định
# 180/2024/NĐ-CP (và 72/2024 trước nữa) — hai bản đó có danh mục LOẠI TRỪ khác
# hẳn bản hiện hành, nên đừng dùng lại căn cứ cũ cho hoá đơn của năm 2026.
VAT_STANDARD = 0.10   # mức chuẩn (mặc định)
VAT_REDUCED = 0.08    # mức giảm 2%


def _round_vnd(amount: float) -> int:
    """Làm tròn về số nguyên VND theo round-half-up (không dùng banker's rounding của round())."""
    return int(Decimal(str(amount)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class MCPServer:
    @staticmethod
    def calculate_vat(base_price: float, is_reduced: bool = False) -> dict:
        """
        Tính VAT cho một khoản tiền trước thuế.
        MẶC ĐỊNH 10% (mức chuẩn); chỉ 8% khi is_reduced=True. Diện giảm do
        `vat_catalog.phan_loai_thue_suat` xác định, không suy ở đây.
        """
        tax_rate = VAT_REDUCED if is_reduced else VAT_STANDARD
        base = _round_vnd(base_price)
        tax_amount = _round_vnd(base_price * tax_rate)
        return {
            "base_price": base,
            "tax_rate": tax_rate,
            "tax_amount": tax_amount,
            "total_price": base + tax_amount,
        }

    @staticmethod
    def validate_invoice_total(
        items: list[dict],
        stated_total: float,
        default_is_reduced: bool = False,
        rel_tol: float = 0.001,
        abs_tol: float = 10.0,
    ) -> dict:
        """
        Tính lại tổng hóa đơn từ danh sách item rồi đối chiếu với tổng ghi trên hóa đơn.

        items: [{"name": str, "price": float (đơn giá trước thuế), "qty": int,
                 "is_reduced_vat": bool | None (tùy chọn)}]

        Diện thuế mỗi dòng: nếu item KHÔNG nói rõ (None/khuyết) -> dùng default_is_reduced
        (mặc định False = 10% chuẩn cho cả hóa đơn).

        Hợp lệ khi: |calculated - stated| <= max(abs_tol, rel_tol * stated_total)
          - rel_tol=0.1%  bắt lỗi OCR đọc nhầm chữ số (sai lệch lớn).
          - abs_tol=10 VND bỏ qua nhiễu làm tròn từng dòng.
        2 ngưỡng này nên tinh chỉnh theo quy mô hóa đơn (xem spec Phụ lục, câu hỏi mở #4 —
        hóa đơn sản xuất giá trị lớn có thể cần rel_tol khác hóa đơn bán lẻ).
        """
        calculated_total = 0
        line_breakdown = []

        for item in items:
            price = float(item.get("price", 0) or 0)
            # `int(qty or 1)` có hai lỗi trong một dòng:
            #  - qty = 0 (dòng huỷ trên hoá đơn nhà xe) bị biến thành 1 -> tính
            #    tiền cho một dòng lẽ ra không tính.
            #  - int(2.5) = 2 -> dầu nhờn bán theo lít bị cắt cụt, tính THIẾU
            #    tiền, mà tính thiếu thì không bên nào kêu.
            # Khuyết/None mới là "không ghi số lượng" và mới mặc định thành 1.
            qty_raw = item.get("qty", 1)
            qty = 1.0 if qty_raw is None else float(qty_raw)
            base = price * qty

            is_reduced = item.get("is_reduced_vat")
            if is_reduced is None:
                is_reduced = default_is_reduced

            vat = MCPServer.calculate_vat(base, bool(is_reduced))
            calculated_total += vat["total_price"]
            line_breakdown.append({
                "name": item.get("name", "Unknown"),
                "base": vat["base_price"],
                "tax_rate": vat["tax_rate"],
                "line_total": vat["total_price"],
            })

        stated_total = float(stated_total or 0)
        tolerance = max(abs_tol, rel_tol * stated_total)
        difference = abs(calculated_total - stated_total)
        is_valid = difference <= tolerance

        return {
            "calculated_total": calculated_total,
            "stated_total": _round_vnd(stated_total),
            "difference": _round_vnd(difference),
            "tolerance": _round_vnd(tolerance),
            "is_valid": is_valid,
            "lines": line_breakdown,
        }
