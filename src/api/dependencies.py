"""
Shared dependencies for all API routes.
Contains RuntimeState, auth helpers, and text utilities.
"""

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from typing import Optional, Union

from fastapi import Header, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("projecta.api")

API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN", "").strip()
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(5 * 1024 * 1024)))
RUNTIME_PROFILE = os.getenv("RUNTIME_PROFILE", "full").strip().lower()


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    # int HOẶC chuỗi. Body bán lẻ (Flask) gửi số nguyên; Body logistics (Next.js)
    # dùng UUID cho `users.id` và `warehouses.id`. Ép `int` ở đây chặn thẳng
    # Body mới, trong khi bên dưới vốn đã coi hai trường này là ĐỊNH DANH MỜ —
    # `memory.py` còn để mặc định `workspace_id="1"`, một chuỗi.
    #
    # Cố ý KHÔNG ép hết về str: số nguyên 1 và chuỗi "1" là hai khoá khác nhau
    # trong bảng lịch sử, nên ép kiểu sẽ làm mồ côi hội thoại cũ của Body bán lẻ.
    user_id: Union[int, str]
    store_id: Union[int, str]
    message: str


# ---------------------------------------------------------------------------
# Concurrency Guards
# ---------------------------------------------------------------------------

# Prevents TOCTOU race when multiple concurrent requests trigger
# model loading simultaneously.  The lock is reentrant-safe: if
# _initialize completes (or raises), the lock is always released.
_model_load_lock = asyncio.Lock()
_vision_load_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Runtime State (lazy-loaded singletons)
# ---------------------------------------------------------------------------

@dataclass
class RuntimeState:
    memory: Optional[object] = None
    engine: Optional[object] = None
    kb: Optional[object] = None
    manager: Optional[object] = None
    coder: Optional[object] = None
    vision: Optional[object] = None
    engine_error: Optional[str] = None
    kb_error: Optional[str] = None
    vision_error: Optional[str] = None

    def _nap_text_runtime_dong_bo(self) -> None:
        """
        Phần nạp NẶNG của text runtime — hàm ĐỒNG BỘ, cố tình.

        Dựng `LLM(...)` của vLLM, nạp VLM và mở kho tri thức là công việc CPU/
        GPU chặn luồng, kéo dài 1–3 phút. Gọi thẳng trong coroutine thì suốt
        ngần ấy thời gian event loop KHÔNG chạy được callback nào: /health câm,
        mọi POST đang bay đông cứng, client báo Body timeout 180s ngay trên
        POST /chat (sự cố 23/08/2026). Vì vậy toàn bộ khối này nằm trong một
        hàm đồng bộ để `ensure_text_runtime` đẩy nó sang thread qua
        `run_in_executor` — loop còn thở trong lúc nạp.

        Chỉ được gọi khi ĐANG GIỮ `_model_load_lock`: hàm ghi thẳng vào state
        dùng chung, hai lượt chạy song song sẽ nạp model hai lần.
        """
        if not self.memory:
            from src.core.memory import MemoryManager
            self.memory = MemoryManager()

        if RUNTIME_PROFILE == "minimal":
            self.engine_error = "Text runtime disabled by RUNTIME_PROFILE=minimal"
            return

        try:
            from src.core.engine import ModelEngine
            self.engine = self.engine or ModelEngine()
        except Exception as exc:
            self.engine = None
            self.engine_error = str(exc)
            logger.error("Engine initialization failed: %s", exc)

        # KB phải tạo TRƯỚC manager để manager dùng chung embedder của KB
        # (tránh nạp MiniLM 2 lần lên VRAM — xem SemanticRouter(embedder=...)).
        try:
            if not self.kb:
                from src.core.knowledge import KnowledgeBase
                self.kb = KnowledgeBase()
        except Exception as exc:
            self.kb = None
            self.kb_error = str(exc)
            logger.warning("Knowledge base initialization failed: %s", exc)

        if self.engine:
            from src.agents.coder import CoderAgent
            from src.agents.manager import ManagerAgent
            self.manager = self.manager or ManagerAgent(self.engine, self.memory, kb=self.kb)
            self.coder = self.coder or CoderAgent(self.engine, self.memory)

    async def ensure_text_runtime(self) -> None:
        """Async, lock-guarded model initialization."""
        # Fast path: already loaded — no lock needed
        if self.manager and self.coder and self.memory:
            return

        async with _model_load_lock:
            # Double-check after acquiring lock (another coroutine may have finished)
            if self.manager and self.coder and self.memory:
                return

            # Khoá + double-check giữ NGUYÊN ngữ nghĩa cũ (hai request đầu đến
            # cùng lúc vẫn chỉ nạp một lần); chỉ khác ở chỗ phần nặng chạy
            # trong thread chứ không chặn event loop. `await` vẫn nằm trong
            # khoá nên không có cửa sổ nào cho lượt thứ hai chen vào nạp trùng.
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._nap_text_runtime_dong_bo)

    async def ensure_vision_runtime(self) -> None:
        """
        Async, lock-guarded vision initialization.

        Vision model (Qwen2-VL-2B) nay nằm TRONG ModelEngine -> VisionAgent chỉ là
        lớp mỏng dùng chung engine đó. Vì vậy phải đảm bảo engine sẵn sàng trước,
        rồi mới tạo VisionAgent(self.engine). (Đã bỏ Florence-2 tự-load.)
        """
        if self.vision:
            return

        async with _vision_load_lock:
            if self.vision:
                return
            if RUNTIME_PROFILE == "text-only":
                self.vision_error = "Vision runtime disabled by RUNTIME_PROFILE=text-only"
                return

            # Cùng lý do với text runtime: `ModelEngine()` nạp cả vLLM lẫn VLM,
            # chặn luồng hàng phút. Đẩy sang thread, khoá vẫn giữ nguyên.
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._nap_vision_runtime_dong_bo)

    def _nap_vision_runtime_dong_bo(self) -> None:
        """
        Phần nạp NẶNG của vision runtime — đồng bộ, chỉ gọi khi đang giữ
        `_vision_load_lock` (xem `_nap_text_runtime_dong_bo`).
        """
        # Engine sở hữu model vision -> tạo engine nếu chưa có (ModelEngine là singleton)
        if not self.engine:
            try:
                from src.core.engine import ModelEngine
                self.engine = ModelEngine()
            except Exception as exc:
                self.engine = None
                self.engine_error = str(exc)
                self.vision_error = self.engine_error
                logger.error("Engine init (for vision) failed: %s", exc)
                return

        try:
            from src.agents.vision import VisionAgent
            self.vision = VisionAgent(self.engine)   # <-- truyền engine vào (trước đây VisionAgent())
        except Exception as exc:
            self.vision = None
            self.vision_error = str(exc)
            logger.error("Vision initialization failed: %s", exc)


# Global singleton
runtime = RuntimeState()


# ---------------------------------------------------------------------------
# Auth & Identity Helpers
# ---------------------------------------------------------------------------

def require_api_token(x_api_token: Optional[str]) -> None:
    if not API_AUTH_TOKEN:
        return
    if x_api_token != API_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


async def auth_guard(x_api_token: Optional[str] = Header(None)) -> None:
    """
    CỔNG XÁC THỰC THẬT — gắn ở tầng router, không phải trong từng handler.

    VÌ SAO ĐỔI (15/08/2026). Trước đây mỗi handler tự gọi `require_api_token`.
    Cách đó hỏng theo hai kiểu, cả hai đều lộ ra khi quét từng endpoint qua HTTP
    thật chứ không phải bằng TestClient:

    1. QUÊN LÀ KHÔNG AI BÁO. `GET /tools` và `GET /api/v1/task/{id}` không hề
       gọi, nên mở công khai. Cái đầu trả 16,6KB lược đồ nội bộ; cái sau trả
       CÂU TRẢ LỜI của AI — tên khách, mã số thuế, số công nợ. Hai mươi endpoint
       kia đều đúng, nên không có gì cho thấy hai cái này sai.

    2. SAI THỨ TỰ. Gọi trong thân handler nghĩa là FastAPI đã validate xong thân
       request trước đó, nên người CHƯA xác thực nhận 422 kèm tên từng trường
       bắt buộc thay vì 401. Dò được lược đồ mà không cần token.

    Là dependency thì cả hai biến mất: FastAPI giải dependency TRƯỚC khi validate
    thân request (401 chạy trước 422), và endpoint mới không thể quên vì nó không
    phải nhớ gì cả.

    Lời gọi `require_api_token` trong các handler giữ nguyên — chúng vô hại và
    thành lớp thứ hai. Cổng thật nằm ở đây; `tests/test_auth_bao_phu.py` canh
    rằng KHÔNG endpoint nào thoát ra ngoài cổng này.
    """
    require_api_token(x_api_token)


def _coerce_identity(raw: str) -> Union[int, str]:
    """Giữ nguyên hình dạng: '7' -> 7, còn UUID thì để nguyên chuỗi."""
    try:
        return int(raw)
    except ValueError:
        return raw


def resolve_identity(
    req: ChatRequest, x_user_id: Optional[str], x_store_id: Optional[str]
) -> tuple[Union[int, str], Union[int, str]]:
    """
    Header thắng thân request khi có đủ cả hai.

    Trước đây header bắt buộc phải parse được thành int, nên UUID của Body
    logistics bị trả 400 ngay ở cửa. Giờ chấp cả hai dạng — cái nào vào thì
    giữ nguyên dạng đó, không ép qua lại.
    """
    if x_user_id and x_store_id:
        return _coerce_identity(x_user_id), _coerce_identity(x_store_id)
    return req.user_id, req.store_id


# ---------------------------------------------------------------------------
# Text Utilities
# ---------------------------------------------------------------------------

def clean_output(text: str) -> str:
    """
    Làm sạch output của model trước khi trả về Body.

    Bản Ngày 7 — sửa 3 lỗi của bản cũ:
      1. Regex <think>.*?</think> cần THẺ ĐÓNG. Khi model lặp tới hết token
         budget nó không kịp viết </think> -> regex không khớp -> toàn bộ nội
         suy lọt ra màn hình. Nay cắt cả trường hợp thẻ không đóng.
      2. Không chống lặp. Model lặp nguyên câu 12 lần vẫn đi thẳng ra ngoài.
      3. Trả chuỗi rỗng khi output toàn <think> -> Body hiện bong bóng trống.
    """
    if not text:
        return _EMPTY_FALLBACK

    # 1) Cắt khối <think> có đóng thẻ đầy đủ
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # 2) Cắt <think> KHÔNG đóng thẻ (bị cắt giữa chừng vì hết token budget)
    text = re.sub(r"<think>.*$", "", text, flags=re.DOTALL | re.IGNORECASE)
    # 3) Cắt </think> mồ côi (model quên mở thẻ)
    text = re.sub(r"^.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)

    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```", "", text)
    text = text.strip()

    text = _dedupe_lines(text)

    return text.strip() or _EMPTY_FALLBACK


_EMPTY_FALLBACK = (
    "Xin lỗi, tôi chưa tạo được câu trả lời cho câu này. "
    "Bạn thử hỏi lại ngắn gọn hơn giúp tôi nhé."
)

# Câu ngắn hơn ngưỡng này được phép lặp (ví dụ "Cảm ơn bạn.", dấu phân cách)
_DEDUPE_MIN_LEN = 40


def _dedupe_lines(text: str) -> str:
    """
    Bỏ dòng dài bị lặp. Giữ nguyên thứ tự, chỉ giữ lần xuất hiện đầu tiên.

    Không đụng tới output JSON (nhánh TECHNICAL) vì JSON có thể có dòng giống
    nhau hợp lệ.
    """
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return text

    seen = set()
    out = []
    for line in text.split("\n"):
        key = line.strip()
        if len(key) >= _DEDUPE_MIN_LEN:
            if key in seen:
                continue
            seen.add(key)
        out.append(line)
    return "\n".join(out)


def extract_user_content(full_text: str) -> str:
    match = re.search(r"\[USER REQUEST\]\s*(.*?)(?=\[|$)", full_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return full_text


def web_search_fallback(query: str, max_results: int = 3) -> str:
    logger.info("Web fallback search started", extra={"query": query[:120]})
    try:
        from ddgs import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results, region="vn-vi"))
        if not results:
            return ""
        formatted_results = ""
        for i, res in enumerate(results):
            title = res.get("title", "No Title")
            body = res.get("body", "No snippet")
            formatted_results += f"[{i+1}] {title}\nSnippet: {body}\n\n"
        return formatted_results
    except Exception as exc:
        logger.warning("Web fallback search failed: %s", exc)
        return ""
