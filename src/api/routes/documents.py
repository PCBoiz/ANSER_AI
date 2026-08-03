"""
src/api/routes/documents.py — Upload (caption) & OCR (hóa đơn) endpoints.

Vision = Qwen2-VL-2B duy nhất (qua ModelEngine). Đã bỏ Florence-2 và mọi
tham chiếu liên quan. /ocr áp dụng nguyên tắc deterministic-first: số tiền
do VLM trích xuất PHẢI được MCPServer tính lại bằng code thuần trước khi tin.
"""
import logging
import os
import tempfile
from typing import Optional

from fastapi import APIRouter, File, Header, HTTPException, Request, UploadFile

from src.api.dependencies import MAX_UPLOAD_BYTES, require_api_token, runtime
from src.core.config import Config
from src.core.mcp_server import MCPServer
from src.core.schemas import InvoicePayload

logger = logging.getLogger("projecta.api.documents")
router = APIRouter()


def _vision_backend() -> str:
    """
    Tên model vision ĐANG chạy, đọc từ config chứ không ghi cứng.

    Bốn chỗ trong file này từng ghi cứng "qwen2-vl-2b". Đổi model (03/08/2026:
    lên Qwen2.5-VL-3B) là nhãn thành sai — mà nhãn này chính là thứ dùng để so
    kết quả OCR giữa hai lần chạy. Nhãn sai thì không lần ra được con số nào do
    model nào đọc.
    """
    return Config().vision_model_id


def _safe_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


async def _read_upload_to_tmp(request: Request, file: UploadFile) -> str:
    content_length = int(request.headers.get("content-length") or "0")
    if content_length > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large")
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large")
    if not data:
        raise HTTPException(status_code=400, detail="Empty file received")
    suffix = os.path.splitext(file.filename or ".png")[1]
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(data)
    tmp.close()
    return tmp.name


@router.post("/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    x_api_token: Optional[str] = Header(None),
):
    """Vai trò 1: caption ảnh (mô tả chi tiết)."""
    require_api_token(x_api_token)
    await runtime.ensure_vision_runtime()
    if not runtime.vision:
        raise HTTPException(status_code=503, detail="Vision runtime unavailable")

    path = await _read_upload_to_tmp(request, file)
    try:
        caption = await runtime.vision.analyze_image(path, task_hint="caption")
        return {"status": "success", "backend": _vision_backend(), "vision_analysis": caption}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Upload endpoint failed: %s", exc)
        return {"status": "error", "error": str(exc)}
    finally:
        _safe_unlink(path)


@router.post("/ocr")
async def ocr_endpoint(
    request: Request,
    file: UploadFile = File(...),
    x_api_token: Optional[str] = Header(None),
):
    """
    Vai trò 2: OCR hóa đơn -> JSON có cấu trúc, rồi VALIDATE bằng MCPServer.
    Không bước nào để số liệu VLM đi thẳng ra ngoài mà chưa tính lại.
    """
    require_api_token(x_api_token)
    await runtime.ensure_vision_runtime()
    if not runtime.vision:
        raise HTTPException(status_code=503, detail="Vision runtime unavailable")

    path = await _read_upload_to_tmp(request, file)
    try:
        extracted = await runtime.vision.extract_invoice(path)
        if "error" in extracted:
            return {
                "success": False,
                "backend": _vision_backend(),
                "error": extracted["error"],
                "raw": extracted.get("raw", ""),
            }

        # 1) Ép schema (bắt JSON sai cấu trúc ngay)
        try:
            invoice = InvoicePayload(**extracted)
        except Exception as exc:
            return {
                "success": False,
                "backend": _vision_backend(),
                "error": f"schema_invalid: {exc}",
                "raw_json": extracted,
            }

        # 2) DETERMINISTIC-FIRST: tính lại tổng bằng code thuần (MCPServer)
        items = [it.model_dump() for it in invoice.items]
        validation = MCPServer.validate_invoice_total(items, invoice.total)

        return {
            "success": True,
            "backend": _vision_backend(),
            "invoice": invoice.model_dump(),
            "validation": validation,                 # is_valid / calculated_total / difference
            "needs_manual_review": not validation["is_valid"],
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("OCR endpoint failed: %s", exc)
        return {"success": False, "error": str(exc)}
    finally:
        _safe_unlink(path)
