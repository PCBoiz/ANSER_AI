"""
src/api/routes/knowledge.py — nạp và tra cứu kho tri thức (RAG).

VÌ SAO CÓ FILE NÀY
------------------
`KnowledgeBase` được viết lại xong từ 03/08/2026 và chạy thật đúng 9/9 phép kiểm,
nhưng `add_document()` **chưa từng được gọi từ bất kỳ đâu** — nó chỉ được dựng
trong `dependencies.py` rồi để đó. Nghĩa là kho tri thức không có cửa vào: khách
gửi 10–30 tài liệu nội bộ về thì không có chỗ nào đổ vào (05/08/2026).

VÌ SAO KHÔNG NHÉT VÀO `tools.py`
-------------------------------
`tools.py` là tầng tool TẤT ĐỊNH: hàm thuần, không trạng thái, không đọc DB, và
mọi endpoint ở đó nằm trong manifest cho vòng agentic gọi. RAG thì ngược lại —
có trạng thái (vector DB trên đĩa), nhận file, và chuyện nạp tài liệu không phải
việc model được tự quyết.

`workspace_id` BẮT BUỘC ở mọi lối vào, không có mặc định. Đó là toàn bộ hàng rào
ngăn hợp đồng khách A lọt vào câu trả lời cho khách B — loại lỗi không sửa được
sau khi đã xảy ra.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from src.api.dependencies import MAX_UPLOAD_BYTES, require_api_token, runtime
from src.core import doc_extract

logger = logging.getLogger("projecta.api.knowledge")
router = APIRouter(prefix="/knowledge")


async def _kb():
    """
    Kho tri thức, khởi tạo LƯỜI nếu chưa có.

    Bản đầu chỉ đọc `runtime.kb` mà không gọi `ensure_text_runtime()`, nên `kb`
    không bao giờ được dựng và mọi endpoint ở đây trả 503 — trong khi thư viện
    đã cài đủ và `kb_error` rỗng. Không có gì cho thấy vì sao (05/08/2026).
    """
    await runtime.ensure_text_runtime()
    kb = getattr(runtime, "kb", None)
    if kb is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Kho tri thức chưa sẵn sàng. Thường là thiếu thư viện: "
                "pip install chromadb sentence-transformers rank_bm25 underthesea"
            ),
        )
    return kb


@router.post("/documents")
async def upload_document(
    request: Request,
    file: UploadFile = File(..., description=".pdf, .docx, .txt, .md"),
    workspace_id: str = Form(..., description="Mã khách hàng — BẮT BUỘC"),
    effective_from: Optional[str] = Form(None, description="YYYY-MM-DD hoặc DD/MM/YYYY"),
    effective_to: Optional[str] = Form(None),
    doc_type: str = Form(""),
    x_api_token: Optional[str] = Header(None),
):
    """
    Nạp một tài liệu nội bộ vào kho tri thức của MỘT khách hàng.

    File KHÔNG ghi ra đĩa: bóc chữ trong bộ nhớ rồi thả. Hợp đồng và bảng giá của
    khách không nằm lại trên máy Brain, nhất là khi Brain chạy GPU thuê (P2).

    Nạp lại cùng `file_name` mà nội dung đổi thì đoạn cũ bị XOÁ SẠCH trước khi ghi
    mới — không để bảng giá năm ngoái sống sót bên cạnh bảng giá mới.
    """
    require_api_token(x_api_token)
    if not workspace_id.strip():
        raise HTTPException(status_code=422, detail="Thiếu workspace_id.")

    content_length = int(request.headers.get("content-length") or "0")
    if content_length > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File quá lớn")
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File quá lớn")

    try:
        boc = doc_extract.extract(data, file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:  # thiếu thư viện — lỗi cài đặt, không phải lỗi file
        raise HTTPException(status_code=503, detail=str(exc))

    kb = await _kb()
    try:
        res = kb.add_document(
            workspace_id.strip(),
            boc.text,
            source=file.filename or "khong_ten",
            effective_from=effective_from,
            effective_to=effective_to,
            doc_type=doc_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {
        "source": res.source,
        "chunks": res.chunks,
        "replaced": res.replaced,
        "skipped_unchanged": res.skipped_unchanged,
        # Gộp cảnh báo lúc bóc chữ với cảnh báo lúc cắt đoạn: người nạp cần thấy
        # CẢ HAI. "Đọc được nhưng mất cấu trúc bảng" cũng nguy như "không đọc được".
        "warnings": boc.warnings + res.warnings,
        "pages": boc.pages or None,
    }


@router.get("/documents")
async def list_documents(
    workspace_id: str = Query(..., description="Mã khách hàng — BẮT BUỘC"),
    x_api_token: Optional[str] = Header(None),
):
    """Tài liệu đang có trong kho của một khách, kèm ngày hiệu lực."""
    require_api_token(x_api_token)
    if not workspace_id.strip():
        raise HTTPException(status_code=422, detail="Thiếu workspace_id.")
    return {"documents": (await _kb()).list_documents(workspace_id.strip())}


@router.delete("/documents")
async def delete_document(
    workspace_id: str = Query(...),
    source: str = Query(..., description="Tên file đúng như lúc nạp"),
    x_api_token: Optional[str] = Header(None),
):
    """Xoá hẳn một tài liệu khỏi kho."""
    require_api_token(x_api_token)
    if not workspace_id.strip() or not source.strip():
        raise HTTPException(status_code=422, detail="Thiếu workspace_id hoặc source.")
    n = (await _kb()).delete_document(workspace_id.strip(), source.strip())
    if n == 0:
        raise HTTPException(status_code=404, detail=f"Không có tài liệu tên {source!r}.")
    return {"source": source, "deleted_chunks": n}


class SearchRequest(BaseModel):
    workspace_id: str = Field(..., description="Mã khách hàng — BẮT BUỘC")
    query: str
    top_k: int = Field(3, ge=1, le=20)
    on_date: Optional[str] = Field(
        None, description="YYYY-MM-DD. Bỏ trống = hôm nay. Dùng để tra cứu quá khứ."
    )


@router.post("/search")
async def search(req: SearchRequest, x_api_token: Optional[str] = Header(None)):
    """
    Tra cứu — trả về ĐOẠN KÈM NGUỒN, không phải một chuỗi đã nối.

    Có endpoint riêng để Body xem thử kho tri thức trả về gì trước khi tin vào
    câu trả lời của model. Không dẫn được nguồn thì không kiểm chứng được.
    """
    require_api_token(x_api_token)
    if not req.workspace_id.strip():
        raise HTTPException(status_code=422, detail="Thiếu workspace_id.")

    on = None
    if req.on_date:
        from datetime import date as _date
        try:
            on = _date.fromisoformat(req.on_date)
        except ValueError:
            raise HTTPException(status_code=422, detail="on_date phải dạng YYYY-MM-DD.")

    passages = (await _kb()).search(req.workspace_id.strip(), req.query, req.top_k, on_date=on)
    return {
        "passages": [
            {
                "text": p.text, "source": p.source, "score": p.score,
                "heading": p.heading, "cite": p.cite(),
                "effective_from": p.effective_from, "effective_to": p.effective_to,
            }
            for p in passages
        ],
        # Rỗng KHÔNG phải lỗi — nó nghĩa là không tài liệu nào đủ liên quan. Nói
        # rõ ra để giao diện phân biệt được với "kho chưa có gì".
        "empty_reason": None if passages else (
            "Không đoạn nào vượt ngưỡng liên quan, hoặc kho chưa có tài liệu nào "
            "còn hiệu lực cho ngày này."
        ),
    }


__all__: list[Any] = ["router"]
