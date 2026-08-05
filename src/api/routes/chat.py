"""
src/api/routes/chat.py — Chat endpoint và task polling.

Bản Ngày 7. Thay đổi so với bản cũ:

1. Ba nhánh GENERAL / RETRIEVAL / DATA_INTERNAL không còn dùng chung
   `manager.consult()`. Mỗi nhánh gọi method riêng với prompt riêng.
   Đây là fix cho lỗi model lặp vô hạn bảng "4 loại giao thức".

2. Nhánh TECHNICAL validate JSON TRƯỚC KHI trả về. Nếu model sinh JSON hỏng
   (ngoặc lệch, expression sai) thì retry 1 lần với feedback cụ thể; vẫn hỏng
   thì trả thông báo tiếng Việt thay vì đẩy rác xuống Body.

3. Log kèm score/margin của router để đo chất lượng định tuyến.

Ghi chú: nhánh FINANCIAL đã gỡ — validate hoá đơn đi qua /ocr (documents.py).
"""

import json
import logging
import os
import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from src.api.dependencies import (
    ChatRequest,
    clean_output,
    extract_user_content,
    require_api_token,
    resolve_identity,
    runtime,
    web_search_fallback,
)
from src.core import metrics
from src.core.config import Config
from src.core.engine import TASK_REGISTRY
from src.core.grounding import guard_answer
from src.core.retrieval_policy import KHONG_CO_TAI_LIEU, decide_web_fallback
from src.core.schemas import RetailChatResponse
from src.core.tool_planner import plan_tools
from src.core.utils import extract_json_block
from src.core.workflow_schema import validate_workflow

logger = logging.getLogger("projecta.api.chat")

router = APIRouter()

# SaasAPI singleton nhẹ (tạo engine 1 lần) — dùng cho route DATA_INTERNAL
_saas = None

# Thông báo khi không sinh nổi workflow hợp lệ
_WORKFLOW_FAILED_MSG = (
    "Tôi chưa dựng được quy trình hợp lệ cho yêu cầu này. "
    "Bạn mô tả rõ hơn giúp tôi 3 điểm: chạy vào lúc nào, "
    "lấy dữ liệu từ đâu, và gửi kết quả đi đâu."
)


def _get_saas():
    global _saas
    if _saas is None:
        from src.core.saas_api import SaasAPI
        _saas = SaasAPI()
    return _saas


def _kb_workspace() -> str:
    """
    Khoá phạm vi kho tri thức — CỐ TÌNH không phải `store_id`.

    Hợp đồng và bảng giá cước là của cả công ty. Lấy kho đang chọn làm khoá thì
    tài liệu nạp lúc đứng ở kho A trở nên vô hình khi hỏi lúc đứng ở kho B, mà
    biểu hiện duy nhất là "không tìm thấy" — không lỗi, không cảnh báo.
    """
    return Config().kb_workspace_id


def _canh_bao_lech_pham_vi(kb_ws: str, request_id: str) -> None:
    """
    Tra không ra gì mà kho lại CÓ tài liệu dưới phạm vi khác -> nói to lên.

    Đây đúng là kiểu hỏng không để lại dấu vết: khách nạp 30 tài liệu, giao diện
    hiện đủ 30, chat vẫn trả lời "chưa tìm thấy tài liệu nào". Không lỗi, không
    ngoại lệ, chỉ là hai bên dùng hai khoá khác nhau. Một dòng log ở đây biến
    nhiều ngày mò mẫm thành một câu trả lời.
    """
    kb = getattr(runtime, "kb", None)
    liet_ke = getattr(kb, "workspaces", None)
    if not callable(liet_ke):
        return
    try:
        khac = [w for w in liet_ke() if w != kb_ws]
    except Exception:
        return
    if khac:
        logger.warning(
            "Kho tri thức KHÔNG có tài liệu nào dưới phạm vi %r, nhưng có dưới %s. "
            "Đường nạp và đường tra đang dùng hai khoá khác nhau — kiểm tra "
            "KB_WORKSPACE_ID (Brain) và BRAIN_KB_WORKSPACE (Body).",
            kb_ws, khac,
            extra={"request_id": request_id},
        )


def _load_history(user_id) -> list[dict]:
    """
    Lịch sử hội thoại của user, dạng messages.

    Suy giảm mềm: chưa nối DB hoặc DB lỗi thì trả [] — Brain vẫn trả lời được,
    chỉ mất ngữ cảnh. Không bao giờ để việc đọc lịch sử làm hỏng một câu hỏi.
    """
    memory = getattr(runtime, "memory", None)
    if memory is None or not hasattr(memory, "get_history_messages"):
        return []
    try:
        return memory.get_history_messages(user_id)
    except Exception as exc:
        logger.warning("Không đọc được lịch sử hội thoại: %s", exc)
        return []


def _save_turn(user_id, store_id, user_msg: str, answer: str) -> None:
    """Lưu lượt vừa xong để lượt sau có ngữ cảnh. Lỗi lưu không làm hỏng câu trả lời."""
    memory = getattr(runtime, "memory", None)
    if memory is None or not hasattr(memory, "add_message"):
        return
    try:
        memory.add_message(user_id, store_id, "user", user_msg)
        memory.add_message(user_id, store_id, "assistant", answer)
    except Exception as exc:
        logger.warning("Không lưu được lượt hội thoại: %s", exc)


# Hàm THUẦN, đã chuyển sang `src/core/utils.py` (03/08/2026). Giữ alias để 5 chỗ
# gọi trong file này không phải sửa.
#
# Vì sao chuyển: `agents/agentic.py` phải import ngược lên module route này chỉ
# để dùng nó — một hàm đếm ngoặc trên chuỗi, chẳng liên quan gì HTTP. Import đặt
# trong thân hàm nên né được vòng lặp import và KHÔNG AI THẤY GÌ.
_extract_json_block = extract_json_block


# Validate workflow nay nằm ở src/core/workflow_schema.py — NGUỒN SỰ THẬT DUY NHẤT
# dùng chung với prompt CoderAgent và JSON Schema của guided decoding.
#
# Bản cũ định nghĩa lại luật ngay tại đây và kiểm theo "edges" + "id", trong khi
# prompt dạy n8n và dữ liệu train lại là Make.com — ba định dạng mâu thuẫn
# (ARCHITECTURE.md §11.1). Xoá bản sao ở đây là một phần của việc sửa lỗi đó.
_validate_workflow = validate_workflow


async def _fetch_report_lines(store_id, request_id: str):
    """
    Dòng bán hàng + chi phí THÔ từ hệ thống bán hàng.

    Trả (sales, expenses, thông_báo_lỗi). Tách riêng khỏi `_build_report_context`
    vì vòng agentic cần chính những dòng thô này làm `arguments` cho tool
    `report`, còn nhánh REPORT cần bản đã tính. Một nguồn, hai chỗ dùng (P4).
    """
    saas = _get_saas()
    fetch = getattr(saas, "get_report_lines", None)
    if fetch is None:
        return None, None, (
            "Tôi chưa nối được với dữ liệu bán hàng để dựng báo cáo. "
            "Cần bên hệ thống bán hàng mở API xuất dòng bán + chi phí theo kỳ "
            "(hoặc đưa file MISA xuất ra) thì tôi tính được ngay."
        )
    try:
        raw = fetch(workspace_id=store_id) or {}
        sales = list(raw.get("sales") or [])
        expenses = list(raw.get("expenses") or [])
    except Exception as exc:
        logger.warning(
            "REPORT: không lấy được dữ liệu: %s", exc,
            extra={"request_id": request_id},
        )
        return None, None, (
            "Tôi chưa lấy được số liệu bán hàng để dựng báo cáo. "
            "Thử lại sau ít phút hoặc báo quản trị viên kiểm tra kết nối."
        )

    if not sales:
        return None, None, (
            "Chưa có dòng bán hàng nào trong dữ liệu nên tôi chưa dựng được "
            "báo cáo. Kiểm tra giúp tôi kỳ cần xem đã có dữ liệu chưa."
        )
    return sales, expenses, None


async def _build_report_context(store_id, request_id: str):
    """
    Lấy số liệu bán hàng/chi phí rồi cho engine TẤT ĐỊNH tính (P1).

    Trả (context_json, thông_báo_lỗi). Chưa nối được nguồn dữ liệu thì trả
    thông báo thay vì để model bịa một báo cáo nghe hợp lý — báo cáo tài chính
    sai mà trông bình thường là loại lỗi không ai phát hiện tới lúc quyết toán.
    """
    from src.core import reporting as rp

    sales, expenses, err = await _fetch_report_lines(store_id, request_id)
    if err:
        return None, err

    report = rp.build_report(rp.ReportRequest(
        sales=[rp.SaleLine(**s) for s in sales],
        expenses=[rp.ExpenseLine(**e) for e in expenses],
    ))
    return json.dumps(report, ensure_ascii=False), None


# Tool cần dữ liệu hệ thống mà hiện chưa có nguồn. Câu chữ nói rõ NGƯỜI DÙNG
# phải làm gì, không phải "lỗi hệ thống" — với khách 4-5 người thì việc cần làm
# thường là xuất một file từ phần mềm kế toán rồi tải lên.
_CHUA_CO_NGUON = {
    "inventory_audit": (
        "Tôi chưa có bảng tổng hợp tồn kho để soi. Bạn xuất bảng Tổng hợp "
        "Nhập-Xuất-Tồn từ phần mềm kế toán (MISA/Fast/Bravo) ra file Excel rồi "
        "tải lên mục Tồn kho — tôi soi ngay và chỉ ra từng dòng nghi sai."
    ),
    "forecast_reorder": (
        "Tôi chưa có lịch sử bán theo kỳ của mặt hàng nên chưa dự báo được. "
        "Cần số lượng bán từng tháng của ít nhất 6 tháng gần đây, kèm tồn hiện "
        "tại và thời gian đặt hàng về, thì tôi tính được điểm cần đặt lại."
    ),
    "carrier_selection": (
        "Tôi chưa có danh sách nhà xe kèm giá chào cho chuyến này. Bạn cho tôi "
        "biết các nhà xe đang cân nhắc và giá mỗi bên báo, tôi xếp hạng theo "
        "giá, khoảng cách bãi, công nợ, tỷ lệ đúng hẹn."
    ),
}


async def _provide_tool_data(name: str, args: dict, store_id, request_id: str):
    """
    Bơm dữ liệu hệ thống vào `arguments` TRƯỚC khi tool chạy.

    Trả (arguments, thiếu_gì|None). Đây là hàng rào chống bịa DỮ LIỆU ĐẦU VÀO:
    chốt chặn neo số liệu chỉ soi được câu trả lời so với kết quả tool, nên nếu
    model tự nghĩ ra doanh thu rồi đưa vào tool, mọi con số sau đó đều "có
    nguồn" và đi lọt hết. Ghi đè, không hợp nhất — số của model không được
    quyền sống sót cạnh số thật.
    """
    if name == "report":
        sales, expenses, err = await _fetch_report_lines(store_id, request_id)
        if err:
            return args, err
        return {**args, "sales": sales, "expenses": expenses}, None

    thieu = _CHUA_CO_NGUON.get(name)
    if thieu:
        return args, thieu

    # `vat` và `quote`: tham số đến từ chính lời người dùng ("đơn hàng 3 triệu
    # rưỡi, thuế 8%"), không có dữ liệu hệ thống nào để bơm vào.
    return args, None


async def _run_agentic(user_msg, plan, store_id, history, request_id, metric):
    """
    Vòng agentic với TOOL ĐÃ ĐƯỢC CHỌN SẴN bằng luật.

    Trả (câu_trả_lời, dữ_liệu_neo). Dữ liệu neo là kết quả tool — mọi con số
    trong câu trả lời phải có ở đó, và chốt chặn ở cuối `process_chat` kiểm
    đúng điều đó.
    """
    from src.agents.agentic import AgenticLoop
    from src.api.routes.tools import get_tool_defs, run_tool

    async def provider(ten: str, args: dict):
        return await _provide_tool_data(ten, args, store_id, request_id)

    out = await AgenticLoop(
        runtime.manager,
        get_tool_defs(),
        run_tool,
        planner=lambda q, names: list(plan),
        data_provider=provider,
    ).run(user_msg, history=history)

    metric.tool_calls = out.get("tool_calls")
    metric.tool_plan = ",".join(plan)
    metric.asked_back = bool(out.get("data_missing"))
    logger.info(
        "Agentic: kế hoạch=%s, đã gọi %s tool, chạm trần=%s",
        plan, out.get("tool_calls"), out.get("hit_limit"),
        extra={"request_id": request_id},
    )

    quan_sat = out.get("observations") or []
    neo = json.dumps(quan_sat, ensure_ascii=False, default=str) if quan_sat else ""
    return out["answer"], neo


# Khoá nhận biết một lượt cũ có khối giải thích được. Engine nào cũng trả
# `explain`/`warnings`, nên tìm theo cấu trúc thay vì đoán theo câu chữ.
_EXPLAINABLE_KEYS = ("explain", "ranked", "internal", "periods", "warnings")


def _find_explainable(history: Optional[list]) -> Optional[str]:
    """
    Tìm khối kết quả engine gần nhất trong lịch sử để giải thích.

    Chỉ nhận JSON có cấu trúc của engine — không nhận văn xuôi, vì giải thích
    dựa trên văn xuôi của chính model là bịa lý do cho một kết luận đã bịa.
    """
    for item in reversed(history or []):
        if item.get("role") != "assistant":
            continue
        obj, _err = _extract_json_block(item.get("content", ""))
        if isinstance(obj, dict) and any(k in obj for k in _EXPLAINABLE_KEYS):
            # P2: khối `internal` chứa biên lợi nhuận — giải thích cho CHỦ DN
            # thì được, nhưng không để nó lọt vào ngữ cảnh nào khác.
            return json.dumps(obj, ensure_ascii=False)
    return None


async def _handle_logistics_quote(
    user_msg: str, request_id: str, history: Optional[list] = None
) -> str:
    """
    Nhánh LOGISTICS: trích xuất -> kiểm tra đủ trường -> gọi webhook n8n.

    Thiết kế cho tình huống thật của khách: chủ DN nhắn khi ĐANG LÁI XE.
    Vì vậy mọi nhánh lỗi đều trả câu tiếng Việt ngắn, nói rõ cần bổ sung gì —
    không bao giờ trả stack trace hay im lặng.

    `history` cho phép câu nối tiếp: sau "báo giá HN đi Hải Phòng xe 5 tấn",
    câu "thế xe 3 tấn thì sao?" phải giữ lại tuyến từ lượt trước.
    """
    from src.api.dependencies import runtime
    from src.core.prompts import Prompts
    from src.core.schemas import QUOTE_REQUIRED_FIELDS, QuoteExtraction

    # 1) Trích xuất (LLM, guided_json)
    #    Lịch sử phải được bọc y hệt lúc train (P4) — xem
    #    Prompts.format_extraction_history.
    raw = await runtime.manager.extract_quote_request(
        user_msg, history=Prompts.format_extraction_history(history)
    )
    obj, err = _extract_json_block(raw)
    if obj is None:
        logger.warning(
            "LOGISTICS: không parse được trích xuất (%s)", err,
            extra={"request_id": request_id},
        )
        return (
            "Tôi chưa đọc được yêu cầu báo giá. Bạn nhắn giúp theo dạng: "
            "\"Báo giá xe 5 tấn từ [điểm lấy] đi [điểm giao], hàng [loại], "
            "ngày [ngày], gửi [email khách]\"."
        )

    try:
        extracted = QuoteExtraction(**obj)
    except Exception as exc:
        logger.warning(
            "LOGISTICS: trích xuất sai schema: %s", exc,
            extra={"request_id": request_id},
        )
        return "Tôi chưa đọc được yêu cầu báo giá. Bạn mô tả lại tuyến, loại xe giúp tôi nhé."

    # 2) Đủ trường bắt buộc chưa? Thiếu thì HỎI, không đoán (P1).
    data = extracted.model_dump()
    missing = [label for f, label in QUOTE_REQUIRED_FIELDS.items() if not data.get(f)]
    if missing:
        return (
            "Để làm báo giá tôi cần thêm: " + ", ".join(missing) + ". "
            "Bạn bổ sung giúp nhé."
        )

    # 3) Kích hoạt workflow n8n
    webhook_url = os.getenv("N8N_QUOTE_WEBHOOK_URL", "").strip()
    if not webhook_url:
        logger.error(
            "LOGISTICS: chưa cấu hình N8N_QUOTE_WEBHOOK_URL",
            extra={"request_id": request_id},
        )
        return (
            "Hệ thống báo giá chưa được nối với n8n (thiếu N8N_QUOTE_WEBHOOK_URL). "
            "Báo quản trị viên cấu hình rồi thử lại."
        )

    try:
        from src.core.utils import HttpClientPool
        client = HttpClientPool.get_client()
        r = await client.post(webhook_url, json=data, timeout=30.0)
        r.raise_for_status()
        body = r.json()
        draft_id = body.get("draft_id", "?")
    except Exception as exc:
        logger.error(
            "LOGISTICS: gọi webhook n8n thất bại: %s", exc,
            extra={"request_id": request_id},
        )
        return (
            "Tôi đã hiểu yêu cầu nhưng chưa kích hoạt được quy trình báo giá "
            "(lỗi kết nối n8n). Thử lại sau ít phút hoặc báo quản trị viên."
        )

    # Câu xác nhận dựng bằng hàm DÙNG CHUNG với dữ liệu train đa lượt (P4):
    # lượt assistant trong data chính là câu này, nên lịch sử lúc serve có đúng
    # hình dạng mà model đã học.
    return Prompts.format_quote_confirmation(data, draft_id)


@router.get("/api/v1/task/{task_id}")
async def get_task_status(task_id: str):
    task = TASK_REGISTRY.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    task.pop("_created_at", None)
    return task


@router.post("/chat")
async def chat_endpoint(
    req: ChatRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    x_api_token: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
    x_store_id: Optional[str] = Header(None),
):
    require_api_token(x_api_token)
    user_id, store_id = resolve_identity(req, x_user_id, x_store_id)
    await runtime.ensure_text_runtime()
    if not runtime.manager or not runtime.coder:
        raise HTTPException(status_code=503, detail="Text runtime unavailable")

    user_msg = extract_user_content(req.message)
    request_id = request.state.request_id
    logger.info(
        "Chat request received",
        extra={"request_id": request_id, "user_id": user_id, "store_id": store_id},
    )

    task_id = str(uuid.uuid4())

    async def process_chat():
        timer = metrics.Timer().__enter__()
        metric = metrics.TurnMetric(
            request_id=request_id, route="?", ok=False, latency_ms=0,
            user_id=user_id, store_id=store_id, message_chars=len(user_msg),
        )

        # Lịch sử hội thoại — thiếu nó thì mọi tin nhắn là một phiên độc lập,
        # "thế xe 3 tấn thì sao?" không thể hiểu được.
        history = _load_history(user_id)
        metric.history_turns = len(history)

        decision = await runtime.manager.analyze_task(user_msg)
        cat = decision.get("category", "GENERAL")
        metric.route = cat
        metric.router_score = decision.get("score")
        metric.router_margin = decision.get("margin")
        metric.router_method = decision.get("method")
        logger.info(
            "Route selected: %s (score=%.2f margin=%.3f method=%s, history=%d lượt)",
            cat,
            decision.get("score", 0.0),
            decision.get("margin", 0.0),
            decision.get("method", "?"),
            len(history),
            extra={"request_id": request_id, "route": cat},
        )

        resp = ""
        # Dữ liệu TẤT ĐỊNH mà câu trả lời phải neo vào. Nhánh nào có thì gán;
        # rỗng nghĩa là không có gì để đối chiếu, và khi đó KHÔNG chặn.
        grounding_ctx = ""

        # ------------------------------------------------------------------
        # VÒNG AGENTIC — tool do LUẬT chọn, không phải model
        # ------------------------------------------------------------------
        # Chạy TRƯỚC bảng rẽ nhánh vì nó cắt ngang các nhánh cũ: "tháng này lãi
        # bao nhiêu, mặt hàng nào lãi nhất, có nên nhập thêm không" là ba bước
        # nối tiếp, kiến trúc một-lần-gọi của các nhánh dưới không làm được.
        #
        # LOGISTICS và TECHNICAL đứng ngoài: cả hai đã có luồng struct riêng
        # (trích xuất báo giá -> n8n; sinh workflow -> validate), đều tất định
        # và đều đang chạy được. Không đụng vào thứ đang chạy được.
        from src.api.routes.tools import get_tool_defs

        plan = plan_tools(user_msg, [t["name"] for t in get_tool_defs()])
        if plan and cat not in ("LOGISTICS", "TECHNICAL"):
            resp, grounding_ctx = await _run_agentic(
                user_msg, plan, store_id, history, request_id, metric
            )

        # ------------------------------------------------------------------
        # LOGISTICS — trích xuất yêu cầu báo giá -> kích hoạt workflow n8n
        # ------------------------------------------------------------------
        # Brain CHỈ làm: (1) tiếng Việt tự do -> struct có schema, (2) trả lời
        # xác nhận. Toàn bộ đọc Sheet + tính giá + nháp + duyệt nằm bên n8n +
        # /tools (luồng logistics_quote_request -> logistics_quote_approve).
        elif cat == "LOGISTICS":
            resp = await _handle_logistics_quote(user_msg, request_id, history=history)
            metric.asked_back = "tôi cần thêm" in resp.lower()

        # ------------------------------------------------------------------
        # TECHNICAL — sinh workflow n8n, validate trước khi trả
        # ------------------------------------------------------------------
        # ------------------------------------------------------------------
        # REPORT — báo cáo/phân tích nhiều kỳ, văn dài
        # ------------------------------------------------------------------
        # Số do engine tất định (reporting.build_report qua /tools/report) tính;
        # LLM chỉ diễn giải (P1). Dữ liệu bán hàng đến từ Body — chưa nối thì
        # nói thẳng là chưa có, KHÔNG bịa một báo cáo nghe hợp lý.
        elif cat == "REPORT":
            report_ctx, report_err = await _build_report_context(store_id, request_id)
            grounding_ctx = report_ctx or ""
            if report_err:
                resp = report_err
                metric.asked_back = True
            else:
                resp = await runtime.manager.answer_report(
                    user_msg, context=report_ctx, history=history
                )

        # ------------------------------------------------------------------
        # EXPLAIN — xAI: giải thích kết quả vừa đưa ra
        # ------------------------------------------------------------------
        # Khối `explain` của lần tính gần nhất nằm trong lịch sử hội thoại.
        # Không có gì để giải thích thì nói rõ, không bịa lý do.
        elif cat == "EXPLAIN":
            explain_ctx = _find_explainable(history)
            if explain_ctx is None:
                resp = (
                    "Tôi chưa có kết quả nào gần đây để giải thích. "
                    "Bạn hỏi lại ngay sau khi tôi đưa ra báo giá, gợi ý hãng xe "
                    "hoặc báo cáo nhé — khi đó tôi nói rõ được từng yếu tố."
                )
                metric.asked_back = True
            else:
                grounding_ctx = explain_ctx
                resp = await runtime.manager.explain_result(
                    user_msg, context=explain_ctx, history=history
                )

        elif cat == "TECHNICAL":
            plan = await runtime.manager.plan_or_ask(req.message)

            if "[PLAN]" not in plan:
                # Model hỏi lại cho rõ yêu cầu -> trả nguyên câu hỏi
                resp = clean_output(plan)
                metric.asked_back = True
            else:
                raw = await runtime.coder.write_code(user_msg, plan)
                obj, err = _extract_json_block(raw)

                ok = False
                if obj is not None:
                    ok, err = _validate_workflow(obj)

                metric.workflow_retried = not ok
                if not ok:
                    # Retry đúng 1 lần, đưa lỗi cụ thể làm feedback
                    logger.warning(
                        "Workflow JSON không hợp lệ (%s) — thử lại",
                        err, extra={"request_id": request_id},
                    )
                    feedback = (
                        f"Lần trước JSON bị lỗi: {err}. "
                        "Sửa lại và chỉ xuất JSON hợp lệ, không thêm chữ nào khác."
                    )
                    raw = await runtime.coder.write_code(user_msg, plan, feedback=feedback)
                    obj, err = _extract_json_block(raw)
                    if obj is not None:
                        ok, err = _validate_workflow(obj)

                metric.workflow_valid = ok
                if ok:
                    # Trả JSON đã chuẩn hoá — Body parse chắc chắn được
                    resp = json.dumps(obj, ensure_ascii=False)
                    logger.info(
                        "Workflow hợp lệ: %d node",
                        len(obj["payload"]["nodes"]),
                        extra={"request_id": request_id},
                    )
                else:
                    logger.error(
                        "Workflow vẫn hỏng sau retry: %s",
                        err, extra={"request_id": request_id},
                    )
                    resp = _WORKFLOW_FAILED_MSG

        # ------------------------------------------------------------------
        # DATA_INTERNAL — dữ liệu thật từ DB cửa hàng
        # ------------------------------------------------------------------
        elif cat == "DATA_INTERNAL":
            saas = _get_saas()
            try:
                products = saas.lookup_product(user_msg, workspace_id=store_id)
                sales = saas.get_sales_report(workspace_id=store_id, period="today")
                db_context = (
                    f"[SẢN PHẨM KHỚP TRUY VẤN]\n{products}\n\n"
                    f"[DOANH SỐ HÔM NAY]\n{json.dumps(sales, ensure_ascii=False)}"
                )
            except Exception as exc:
                logger.warning(
                    "Truy vấn DB thất bại: %s", exc,
                    extra={"request_id": request_id},
                )
                db_context = "(không lấy được dữ liệu từ cơ sở dữ liệu)"

            grounding_ctx = db_context
            resp = await runtime.manager.answer_data(
                user_msg, context=db_context, history=history
            )

        # ------------------------------------------------------------------
        # RETRIEVAL — RAG tài liệu nội bộ, fallback web
        # ------------------------------------------------------------------
        elif cat == "RETRIEVAL":
            # Lời gọi cũ là `kb.search(user_msg, top_k=2)`, trong khi chữ ký là
            # `search(workspace_id, query, top_k)`. Nó ném TypeError, rơi đúng
            # vào `except Exception` ngay dưới, ghi một dòng warning rồi im lặng
            # nhảy sang tra web. Nghĩa là kho tài liệu CHƯA TỪNG được dùng ở
            # đường phục vụ, và không có triệu chứng nào ngoài "câu trả lời hơi
            # chung chung" (sửa 05/08/2026).
            context_docs = ""
            found_internal = False
            kb_ws = _kb_workspace()

            if runtime.kb:
                try:
                    passages = runtime.kb.search(kb_ws, user_msg, top_k=2)
                    if passages:
                        from src.core.knowledge import format_for_prompt
                        context_docs = f"[TÀI LIỆU NỘI BỘ]\n{format_for_prompt(passages)}"
                        found_internal = True
                        logger.info(
                            "Tìm thấy %d đoạn tài liệu nội bộ", len(passages),
                            extra={"request_id": request_id},
                        )
                    else:
                        _canh_bao_lech_pham_vi(kb_ws, request_id)
                except Exception as exc:
                    logger.warning(
                        "KB search lỗi: %s", exc,
                        extra={"request_id": request_id},
                    )

            if not found_internal:
                # Không thấy trong tài liệu thì KHÔNG mặc nhiên tra web. Trả một
                # bài viết trên mạng cho câu "chính sách công nợ bên mình thế
                # nào" là loại sai tệ nhất: nghe hợp lý, không dấu hiệu nghi ngờ,
                # người đọc đang cần ra quyết định.
                quyet = decide_web_fallback(user_msg)
                metric.web_fallback = quyet.allow
                logger.info(
                    "RETRIEVAL: web=%s (%s)", quyet.allow, quyet.reason,
                    extra={"request_id": request_id},
                )
                if quyet.allow:
                    web_results = web_search_fallback(user_msg)
                    context_docs = (
                        f"[KẾT QUẢ TÌM KIẾM]\n{web_results}" if web_results else ""
                    )
                else:
                    # Câu tất định — đây là lúc hệ thống thú nhận không biết, và
                    # câu thú nhận đó không được nhờ model diễn đạt lại.
                    resp = KHONG_CO_TAI_LIEU
                    metric.asked_back = True

            if not resp:
                grounding_ctx = context_docs
                resp = await runtime.manager.answer_retrieval(
                    user_msg, context=context_docs, history=history
                )

        # ------------------------------------------------------------------
        # GENERAL — hội thoại, tính toán, giải thích
        # ------------------------------------------------------------------
        else:
            resp = await runtime.manager.answer_general(user_msg, history=history)

        cleaned = clean_output(resp)

        # CHỐT CHẶN NEO SỐ LIỆU — chạy TRƯỚC khi câu trả lời ra ngoài.
        #
        # `narration_numbers_ok` đã tồn tại từ lâu và chạy ở hai chỗ: lọc dữ
        # liệu huấn luyện, và chấm điểm benchmark. Nhưng KHÔNG chạy ở chỗ thứ
        # ba, chỗ quan trọng nhất — lúc phục vụ. Nghĩa là ta đo được model bịa
        # số 8-10 ca trên 27, rồi vẫn để con số bịa đó đi thẳng ra màn hình chủ
        # doanh nghiệp (nối vào 05/08/2026).
        #
        # CHỈ chặn khi CÓ dữ liệu gốc để đối chiếu. Nhánh GENERAL và LOGISTICS
        # không có `grounding_ctx`; chặn ở đó là chặn oan mọi con số >= 4 chữ số,
        # kể cả số người dùng vừa tự nhắc trong câu hỏi.
        if grounding_ctx:
            verdict = guard_answer(cleaned, grounding_ctx)
            if verdict.blocked:
                logger.warning(
                    "Chặn câu trả lời (%s: %s)", verdict.reason, verdict.offending,
                    extra={"request_id": request_id},
                )
                metric.blocked_reason = verdict.reason
                cleaned = verdict.safe_answer


        # Lưu lượt để câu sau có ngữ cảnh + ghi nhật ký đo lường
        _save_turn(user_id, store_id, user_msg, cleaned)

        timer.__exit__(None, None, None)
        metric.latency_ms = timer.ms
        metric.answer_chars = len(cleaned)
        metric.ok = cleaned != _WORKFLOW_FAILED_MSG
        metrics.record(metric)

        chat_response = RetailChatResponse(answer=cleaned, sources=None)

        # Proactive Webhook Dispatcher
        callback_url = os.getenv("BODY_CALLBACK_URL")
        if callback_url:
            try:
                from src.core.utils import HttpClientPool

                # Chỉ parse JSON nếu output THỰC SỰ là JSON (nhánh TECHNICAL).
                # Bản cũ repair_json mọi output, kể cả văn xuôi -> tạo rác.
                parsed, _ = _extract_json_block(cleaned)
                payload = {"task_id": task_id, "result": parsed or cleaned}

                api_token = os.getenv("API_AUTH_TOKEN", "default-secret")
                headers = {
                    "Content-Type": "application/json",
                    "X-Webhook-Token": api_token,
                    "X-Task-ID": task_id,
                }

                client = HttpClientPool.get_client()
                await client.post(callback_url, json=payload, headers=headers)
                logger.info("Webhook dispatched for task %s", task_id)
            except Exception as exc:
                logger.error("Webhook dispatch failed for task %s: %s", task_id, exc)

        return chat_response.model_dump()

    background_tasks.add_task(runtime.engine.background_worker, task_id, process_chat)
    return {"task_id": task_id, "status": "processing"}
