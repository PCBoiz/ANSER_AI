# src/agents/vision.py
"""
VisionAgent — lớp mỏng bọc quanh ModelEngine.generate_vision (Qwen2-VL-2B).

MỘT model VLM duy nhất cho cả 3 vai trò (đã LOẠI BỎ Florence-2):
  1. caption  — mô tả ảnh bằng tiếng Việt
  2. ocr      — trích xuất văn bản thô
  3. invoice  — trích xuất hóa đơn ra JSON có cấu trúc (cho luồng nhập kho)

VisionAgent KHÔNG tự load model; nó dùng chung Qwen2-VL-2B do ModelEngine sở hữu,
nên không còn cảnh nạp 2 model vision song song.
"""
import logging

from json_repair import repair_json

logger = logging.getLogger("projecta.agents.vision")


class VisionAgent:
    PROMPTS = {
        "caption": "Mô tả chi tiết nội dung hình ảnh này bằng tiếng Việt.",
        "ocr": (
            "Trích xuất TOÀN BỘ văn bản xuất hiện trong ảnh. "
            "Giữ nguyên thứ tự dòng và dấu tiếng Việt. "
            "Chỉ trả về văn bản, không thêm giải thích."
        ),
        "invoice": (
            "Bạn là hệ thống trích xuất hóa đơn. Đọc ảnh hóa đơn và trả về DUY NHẤT "
            "một JSON hợp lệ, KHÔNG kèm giải thích, đúng schema:\n"
            '{"items": [{"name": "string", "price": 0, "qty": 1}], "total": 0}\n'
            "Quy tắc: 'price' là ĐƠN GIÁ trước thuế; 'total' là tổng tiền ghi trên hóa đơn "
            "(đã gồm thuế). Mọi số tiền là số nguyên VND, không dùng dấu phân cách hàng nghìn. "
            "Bỏ qua dòng nào không đọc được."
        ),
        # Hoá đơn CƯỚC VẬN TẢI — hình dạng khác hẳn hoá đơn bán lẻ ở trên.
        # Giữ cả hai: công ty vừa phân phối dầu nhớt (nhập hàng -> hoá đơn bán lẻ)
        # vừa làm vận tải (thuê nhà xe -> hoá đơn cước).
        "freight": (
            "Bạn là hệ thống đọc HOÁ ĐƠN CƯỚC VẬN TẢI của nhà xe. Đọc ảnh và trả về "
            "DUY NHẤT một JSON hợp lệ, KHÔNG kèm giải thích.\n"
            "Các trường: carrier_name, carrier_tax_code, invoice_no, invoice_date "
            "(YYYY-MM-DD), origin (điểm đi), destination (điểm đến), vehicle_type, "
            "plate_number (biển số), charges (danh sách khoản), vat_rate, subtotal, "
            "vat_amount, total.\n"
            "Mỗi khoản trong 'charges' gồm: kind (một trong: cước, bốc xếp, lưu ca, "
            "cầu đường, quay đầu, khác), description, quantity (số chuyến/số lần), "
            "unit_price (đơn giá CHƯA thuế).\n"
            "QUAN TRỌNG: trường nào KHÔNG ĐỌC ĐƯỢC thì để null — TUYỆT ĐỐI không "
            "đoán, không điền 0. Số tiền là số nguyên VND, không dấu phân cách."
        ),
    }

    def __init__(self, engine):
        if engine is None:
            raise ValueError("VisionAgent cần một ModelEngine instance")
        self.engine = engine
        logger.info("VisionAgent ready (dùng chung Qwen2-VL-2B của ModelEngine)")

    def _prompt_for(self, task_hint: str) -> str:
        task_hint = (task_hint or "").lower()
        # "freight" phải xét TRƯỚC "invoice": chuỗi "freight_invoice" chứa cả hai,
        # xét sau là mọi hoá đơn vận tải rơi vào nhánh bán lẻ.
        if "freight" in task_hint or "van_tai" in task_hint or "vận tải" in task_hint:
            return self.PROMPTS["freight"]
        if "invoice" in task_hint or "hoa_don" in task_hint or "hóa đơn" in task_hint:
            return self.PROMPTS["invoice"]
        if "ocr" in task_hint:
            return self.PROMPTS["ocr"]
        return self.PROMPTS["caption"]

    async def analyze_image(self, image_path: str, task_hint: str = "caption",
                            json_schema: dict | None = None) -> str:
        """Trả về text. task_hint ∈ {'caption', 'ocr', 'invoice', 'freight'}."""
        prompt = self._prompt_for(task_hint)
        th = (task_hint or "").lower()
        max_tokens = 1024 if any(k in th for k in ("ocr", "invoice", "freight")) else 512
        try:
            return await self.engine.generate_vision(
                image_path, prompt, max_new_tokens=max_tokens, json_schema=json_schema
            )
        except Exception as exc:
            logger.exception("Vision inference failed: %s", exc)
            return f"Error analyzing image: {exc}"

    async def extract_invoice(self, image_path: str) -> dict:
        """
        Vai trò 2 (OCR hóa đơn): trả dict {items, total} đã parse từ JSON của VLM.
        Trả {'error': ...} nếu không đọc/parse được — KHÔNG bịa số.
        """
        return await self._extract_json(image_path, task_hint="invoice")

    async def extract_freight_invoice(self, image_path: str) -> dict:
        """
        Hoá đơn CƯỚC VẬN TẢI của nhà xe -> dict theo lược đồ `FreightInvoice`.

        Có ràng buộc giải mã theo lược đồ: model chỉ sinh được token nào giữ cho
        chuỗi hợp lệ. Khác hẳn `extract_invoice` — đường bán lẻ sinh tự do rồi
        vá cú pháp bằng `json_repair`, mà vá cú pháp không dựng lại được trường
        bị thiếu.

        Con số ở đây CHƯA đáng tin: `freight_invoice.verify()` mới là chỗ tính
        lại toàn bộ bằng code và đối chiếu với số in trên tờ giấy.
        """
        from src.core.freight_invoice import json_schema

        return await self._extract_json(
            image_path, task_hint="freight", json_schema=json_schema()
        )

    async def _extract_json(self, image_path: str, task_hint: str,
                            json_schema: dict | None = None) -> dict:
        """Đọc ảnh -> dict. Trả {'error': ...} nếu hỏng — KHÔNG bịa số."""
        raw = await self.analyze_image(image_path, task_hint=task_hint,
                                       json_schema=json_schema)
        if isinstance(raw, str) and raw.startswith("Error"):
            return {"error": raw}
        try:
            parsed = repair_json(raw, return_objects=True)
            if isinstance(parsed, dict):
                return parsed
            return {"error": "VLM không trả JSON object", "raw": raw}
        except Exception as exc:
            return {"error": f"parse_failed: {exc}", "raw": raw}
