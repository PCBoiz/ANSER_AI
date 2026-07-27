"""
src/agents/manager.py — SemanticRouter + ManagerAgent.

Bản Ngày 7. Thay đổi so với bản cũ:

1. `consult()` bị tách thành 3 method riêng theo nhánh router
   (`answer_general` / `answer_retrieval` / `answer_data`).
   Lý do: dùng chung CONSULT_SYSTEM khiến model đọc lại bảng "4 loại giao thức"
   dù router đã phân nhánh xong, dẫn tới tự phân loại lần nữa và lặp vô hạn.

2. `route()` trả về cả điểm số và biên (margin) giữa nhánh nhất và nhánh nhì.
   Bản cũ luôn lấy argmax kể cả khi hai nhánh chênh 0.01 — câu thuế GTGT
   (RETRIEVAL) và câu tồn kho (DATA_INTERNAL) rất dễ nhầm nhau.
   Biên quá hẹp -> hạ về GENERAL thay vì đoán bừa.

3. Thêm lớp override bằng từ khoá chạy TRƯỚC embedding. Một số ý định có dấu
   hiệu từ vựng chắc chắn hơn ngữ nghĩa (ví dụ "tạo quy trình", "workflow"),
   không nên phó mặc cho cosine similarity.

4. Bổ sung ví dụ mẫu cho từng nhánh, đặc biệt các câu tính toán thuế vốn hay
   bị route nhầm sang DATA_INTERNAL.

5. `max_new_tokens` giảm 1024 -> 384/512. Budget nhỏ hạn chế không gian lặp.

Yêu cầu: dùng kèm bản prompts.py Ngày 7 (có GENERAL_SYSTEM / RETRIEVAL_SYSTEM /
DATA_SYSTEM). Nếu prompts.py còn là bản cũ, các method mới sẽ fallback về
CONSULT_SYSTEM — xem `_get_prompt()`.
"""

import logging
import re

import numpy as np

from src.agents.base import BaseAgent
from src.core.prompts import Prompts

logger = logging.getLogger("projecta.agents.manager")


# torch và sentence_transformers được import LƯỜI, ngay trước lúc thực sự cần.
#
# Bản cũ import cả hai ở đầu file. Hệ quả: ENV=LOCAL — chế độ được thiết kế để
# chạy và test toàn bộ tầng logic mà KHÔNG cần GPU — vẫn gãy ngay khi import nếu
# máy dev chưa cài torch (~2.5GB). Điều đó phá đúng mục đích tồn tại của LOCAL
# (AGENTS.md §3.1) và làm test tích hợp fail trên máy Windows dev.
#
# sklearn.metrics.pairwise.cosine_similarity cũng bị bỏ: nó kéo theo scipy chỉ để
# dùng một công thức 3 dòng. Hàm _cosine_sim bên dưới cho kết quả giống hệt.


def _cosine_sim(query_vec, matrix) -> np.ndarray:
    """
    Cosine similarity giữa 1 vector truy vấn và ma trận (n, d). Trả mảng (n,).

    Thay cho sklearn.metrics.pairwise.cosine_similarity(query, matrix)[0] —
    cùng công thức, không kéo thêm phụ thuộc.
    """
    q = np.asarray(query_vec, dtype=float).reshape(-1)
    m = np.asarray(matrix, dtype=float)
    if m.ndim == 1:
        m = m.reshape(1, -1)

    denom = np.linalg.norm(q) * np.linalg.norm(m, axis=1)
    denom = np.where(denom == 0, 1e-12, denom)   # vector rỗng -> tránh chia 0
    return (m @ q) / denom


# ---------------------------------------------------------------------------
# Từ khoá override — chạy trước embedding
# ---------------------------------------------------------------------------
# Chỉ đặt ở đây những cụm mang ý định RÕ RÀNG, không mơ hồ. Cụm nào có thể
# xuất hiện ở nhiều nhánh thì để embedding quyết định.

_KEYWORD_RULES = [
    # Báo giá vận tải — nghiệp vụ logistics. Đặt TRƯỚC TECHNICAL vì "báo giá"
    # có thể dính regex "tự động ... gửi" của nhánh đó khi câu dài.
    ("LOGISTICS", re.compile(
        r"báo giá|bao gia|giá cước|cước phí|cước vận"
        r"|xe\s*\d+([.,]\d+)?\s*(tấn|t\b)|đầu kéo|dau keo|container|cont\b"
        r"|(chuyến|chuyen)\s+(xe|hàng)|thuê xe|gọi xe.*(tải|tấn)",
        re.IGNORECASE)),

    # Sinh workflow: động từ tạo lập + danh từ tự động hoá
    ("TECHNICAL", re.compile(
        r"(tạo|lập|thiết lập|setup|xây dựng|lên)\s+.{0,20}"
        r"(quy trình|workflow|tự động|automation|lịch chạy)"
        r"|workflow|n8n"
        r"|(tự động|định kỳ|mỗi (ngày|tuần|tháng|giờ|tiếng|sáng|tối))\s+.{0,30}"
        r"(gửi|báo|cảnh báo|thông báo|đồng bộ|xuất|kiểm tra)",
        re.IGNORECASE)),

    # Tra cứu luật / thuế / chính sách — gồm cả câu tính thuế
    ("RETRIEVAL", re.compile(
        r"thuế|vat|gtgt|hoá đơn đỏ|hóa đơn đỏ"
        r"|nghị định|thông tư|luật|quy định|điều khoản"
        r"|chính sách (đổi|trả|bảo hành|hoàn)"
        r"|hướng dẫn (sử dụng|tạo|cấu hình)",
        re.IGNORECASE)),
]


class SemanticRouter:
    """
    Định tuyến câu hỏi vào 1 trong 4 nhánh: TECHNICAL / DATA_INTERNAL /
    RETRIEVAL / GENERAL.

    Thứ tự quyết định:
      1. Luật từ khoá (chắc chắn nhất, rẻ nhất)
      2. Cosine similarity trên ví dụ mẫu tiếng Việt
      3. Kiểm tra biên giữa nhánh nhất và nhì; biên hẹp -> GENERAL
    """

    # Ngưỡng tương đồng tối thiểu để tin kết quả embedding
    DEFAULT_THRESHOLD = 0.40
    # Biên tối thiểu giữa nhánh nhất và nhánh nhì
    DEFAULT_MARGIN = 0.05

    @staticmethod
    def _try_load_embedder(model_name: str):
        """
        Nạp embedder; trả None nếu môi trường không có (thay vì làm sập cả router).

        VÌ SAO ĐƯỢC PHÉP TRẢ None: ENV=LOCAL tồn tại để chạy và test toàn bộ tầng
        logic mà không cần GPU (AGENTS.md §3.1). Bản cũ import torch ở đầu file nên
        chỉ riêng việc KHỞI TẠO router đã đòi ~2.5GB phụ thuộc — LOCAL gãy ngay từ
        import, đúng thứ nó sinh ra để tránh.

        Không có embedder thì router lùi về LỚP 1 (luật từ khoá) — vẫn tất định,
        vẫn test được, và tự nhận là mình đang chạy hạn chế qua `method`.
        """
        try:
            import torch
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            logger.warning(
                "Không nạp được embedder (%s) — SemanticRouter chạy CHẾ ĐỘ TỪ KHOÁ. "
                "Câu không khớp từ khoá nào sẽ về GENERAL. "
                "Chấp nhận được ở ENV=LOCAL; KHÔNG chấp nhận được ở production.",
                exc,
            )
            return None

        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info("SemanticRouter tự nạp embedder (device=%s)", device)
        return SentenceTransformer(model_name, device=device)

    def __init__(
        self,
        model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        embedder=None,
    ):
        # Tái sử dụng embedder của KnowledgeBase để khỏi nạp trùng MiniLM lên VRAM.
        if embedder is not None:
            self.embedder = embedder
            logger.info("SemanticRouter dùng chung embedder có sẵn")
        else:
            self.embedder = self._try_load_embedder(model_name)

        self.routes = {
            # Báo giá / điều xe vận tải -> luồng logistics (n8n + /tools)
            "LOGISTICS": [
                "báo giá xe 5 tấn từ Hữu Nghị đi Hải Phòng",
                "cho tôi giá cước chuyến hàng lạnh đi Bắc Giang",
                "khách hỏi giá thuê xe 3 tấn đi Bắc Ninh ngày mai",
                "cần một đầu kéo đi Hải Phòng thứ 3 tuần sau",
                "giá cước tuyến Hà Nội Hải Phòng giờ bao nhiêu",
                "làm báo giá gửi anh Tuấn công ty Minh Long",
                "chuyến 1.5 tấn nội thành hôm nay giá thế nào",
                "gọi xe tải chở hàng đông lạnh đi Bắc Giang",
            ],
            # Sinh workflow tự động hoá -> CoderAgent
            "TECHNICAL": [
                "tạo quy trình tự động hóa gửi báo cáo doanh số mỗi tối",
                "tự động đọc file google sheet rồi gửi email",
                "khi tồn kho dưới ngưỡng thì cảnh báo qua Discord",
                "lên lịch tự động nhập hàng hàng tuần",
                "tạo workflow đồng bộ đơn hàng sang google sheet",
                "gửi thông báo Discord khi có đơn hàng mới",
                "thiết lập tự động hóa xuất báo cáo cuối ngày",
                "mỗi 4 tiếng kiểm tra kho rồi báo lên Discord",
                "cứ 8 giờ sáng gửi tôi tổng doanh thu hôm qua",
                "tạo quy trình nhắc nhở khi hàng sắp hết hạn",
            ],
            # Truy vấn dữ liệu nội bộ (DB cửa hàng) -> SaasAPI
            "DATA_INTERNAL": [
                "còn bao nhiêu hàng tồn kho sản phẩm sữa",
                "doanh thu hôm nay là bao nhiêu",
                "giá bán hiện tại của sản phẩm này là bao nhiêu",
                "tổng số đơn hàng trong tuần này",
                "sản phẩm nào bán chạy nhất tháng này",
                "kiểm tra tồn kho mặt hàng bỉm",
                "báo cáo doanh số tháng trước",
                "khách hàng nào mua nhiều nhất",
                "hôm nay bán được mấy đơn",
                "kho còn bao nhiêu thùng nước ngọt",
            ],
            # Tra cứu tài liệu / luật / hướng dẫn -> RAG (KnowledgeBase)
            "RETRIEVAL": [
                "quy định về thuế VAT theo nghị định 72 là gì",
                "cách tính thuế giá trị gia tăng cho hàng hóa",
                "chính sách đổi trả hàng của cửa hàng như thế nào",
                "hướng dẫn sử dụng tính năng ví điện tử",
                "điều kiện áp dụng thuế suất 8 phần trăm",
                "tài liệu hướng dẫn tạo phiếu nhập kho",
                # Câu tính thuế cụ thể — bản cũ hay route nhầm sang DATA_INTERNAL
                "đơn hàng 3 triệu 500 nghìn thuế GTGT 8 phần trăm nộp bao nhiêu",
                "bán 10 triệu thì tiền thuế phải nộp là bao nhiêu",
                "hộ kinh doanh doanh thu bao nhiêu thì phải đóng thuế",
                "thủ tục đăng ký hộ kinh doanh cá thể gồm những gì",
            ],
            # Hội thoại tự do
            "GENERAL": [
                "xin chào",
                "bạn có khỏe không",
                "cảm ơn bạn nhiều",
                "hôm nay thời tiết thế nào",
                "bạn tên là gì",
                "giúp tôi một chút",
                "bạn làm được những gì",
                "tôi nên bắt đầu từ đâu",
            ],
        }

        # Precompute embeddings cho tất cả ví dụ (bỏ qua khi chạy chế độ từ khoá)
        self.route_embeddings = (
            {
                route: self.embedder.encode(examples)
                for route, examples in self.routes.items()
            }
            if self.embedder is not None
            else {}
        )
        logger.info(
            "SemanticRouter sẵn sàng: %d nhánh, %d ví dụ, chế độ=%s",
            len(self.routes),
            sum(len(v) for v in self.routes.values()),
            "đầy đủ" if self.embedder is not None else "chỉ từ khoá",
        )

    @property
    def is_degraded(self) -> bool:
        """True = đang chạy chế độ từ khoá, không có embedding. Cho /health biết."""
        return self.embedder is None

    # -- lớp 1: từ khoá ----------------------------------------------------

    @staticmethod
    def _keyword_route(query: str):
        for route, pattern in _KEYWORD_RULES:
            if pattern.search(query):
                return route
        return None

    # -- lớp 2 + 3: embedding + biên ---------------------------------------

    def route_with_score(
        self,
        query: str,
        threshold: float = None,
        margin: float = None,
    ) -> dict:
        """
        Trả về dict: {route, score, margin, method}
        `method` cho biết quyết định đến từ đâu — hữu ích khi debug log.
        """
        threshold = self.DEFAULT_THRESHOLD if threshold is None else threshold
        margin = self.DEFAULT_MARGIN if margin is None else margin

        q = (query or "").strip()
        if not q:
            return {"route": "GENERAL", "score": 0.0, "margin": 0.0, "method": "empty"}

        # Lớp 1 — từ khoá
        kw = self._keyword_route(q)
        if kw:
            logger.info("Router: %s (từ khoá)", kw)
            return {"route": kw, "score": 1.0, "margin": 1.0, "method": "keyword"}

        # Không có embedder -> dừng ở lớp 1. GENERAL an toàn hơn đoán bừa vì nó
        # chỉ trả văn xuôi, không sinh JSON hay truy vấn DB sai.
        if self.embedder is None:
            logger.info("Router: GENERAL (chế độ từ khoá, không khớp luật nào)")
            return {
                "route": "GENERAL", "score": 0.0,
                "margin": 0.0, "method": "keyword_only_degraded",
            }

        # Lớp 2 — cosine similarity
        query_vec = self.embedder.encode([q])
        scores = {}
        for route, embeddings in self.route_embeddings.items():
            sims = _cosine_sim(query_vec, embeddings)
            scores[route] = float(np.max(sims))

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        best_route, best_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        gap = best_score - second_score

        # Lớp 3 — kiểm tra ngưỡng và biên
        if best_score < threshold:
            logger.info(
                "Router: GENERAL (điểm %.2f dưới ngưỡng %.2f, ứng viên %s)",
                best_score, threshold, best_route,
            )
            return {
                "route": "GENERAL", "score": best_score,
                "margin": gap, "method": "below_threshold",
            }

        if gap < margin:
            # Hai nhánh sát nhau -> không đủ tin cậy để đi nhánh chuyên biệt.
            # GENERAL an toàn hơn vì nó chỉ trả lời văn xuôi, không sinh JSON
            # hay truy vấn DB sai.
            logger.info(
                "Router: GENERAL (biên hẹp %.3f giữa %s và %s)",
                gap, best_route, ranked[1][0],
            )
            return {
                "route": "GENERAL", "score": best_score,
                "margin": gap, "method": "narrow_margin",
            }

        logger.info("Router: %s (điểm %.2f, biên %.3f)", best_route, best_score, gap)
        return {
            "route": best_route, "score": best_score,
            "margin": gap, "method": "embedding",
        }

    def route(self, query: str, threshold: float = None) -> str:
        """Giữ chữ ký cũ để code hiện có không gãy."""
        return self.route_with_score(query, threshold=threshold)["route"]


class ManagerAgent(BaseAgent):
    def __init__(self, engine, memory, kb=None):
        super().__init__(engine, "manager")
        self.kb = kb
        # Dùng chung embedder của KB nếu có -> tránh nạp MiniLM 2 lần lên VRAM
        shared_embedder = getattr(kb, "embedder", None) if kb else None
        self.router = SemanticRouter(embedder=shared_embedder)

    # -- định tuyến --------------------------------------------------------

    async def analyze_task(self, clean_text: str) -> dict:
        """
        Trả về {category, score, margin, method}.
        `chat.py` chỉ đọc `category` nên vẫn tương thích ngược; các khoá còn lại
        dùng để ghi log và đo chất lượng router.
        """
        result = self.router.route_with_score((clean_text or "").strip())
        return {
            "category": result["route"],
            "score": result["score"],
            "margin": result["margin"],
            "method": result["method"],
        }

    # -- helper chọn prompt ------------------------------------------------

    @staticmethod
    def _get_prompt(name: str, fallback_context: str = ""):
        """
        Lấy prompt theo tên; nếu prompts.py còn là bản cũ (chưa có prompt tách
        nhánh) thì lùi về CONSULT_SYSTEM để không vỡ runtime.
        """
        prompt = getattr(Prompts, name, None)
        if prompt is not None:
            return prompt
        logger.warning("Prompts.%s không tồn tại — dùng CONSULT_SYSTEM thay thế", name)
        return Prompts.CONSULT_SYSTEM

    # -- nhánh LOGISTICS ---------------------------------------------------

    async def extract_quote_request(self, message: str):
        """
        Trích xuất yêu cầu báo giá vận tải thành JSON theo schema QuoteExtraction.
        Cấu trúc do guided_json ép; trường thiếu là null — KHÔNG đoán (P1:
        đây là 1 trong 2 việc duy nhất LLM làm trong luồng báo giá).
        """
        from src.core.schemas import QuoteExtraction
        return await self.generate_chat(
            system=self._get_prompt("LOGISTICS_EXTRACT_SYSTEM"),
            user=message,
            max_new_tokens=256,
            temperature=0.0,   # trích xuất cần xác định tuyệt đối
            json_schema=QuoteExtraction.model_json_schema(),
        )

    # -- nhánh TECHNICAL ---------------------------------------------------

    async def plan_or_ask(self, full_context: str):
        """Prompt sạch (không ChatML) -> để apply_chat_template lo định dạng."""
        return await self.generate_chat(
            system=Prompts.PLANNER_SYSTEM,
            user=full_context,
            max_new_tokens=256,
            temperature=0.1,
        )

    # -- nhánh GENERAL -----------------------------------------------------

    async def answer_general(self, task: str):
        """Hội thoại tự do, tính toán đơn giản, giải thích ngắn."""
        system = self._get_prompt("GENERAL_SYSTEM")
        if "{context}" in system:      # trường hợp fallback về CONSULT_SYSTEM
            system = system.format(schema=Prompts.DB_SCHEMA, context="")
        return await self.generate_chat(
            system=system,
            user=task,
            max_new_tokens=384,
            temperature=0.3,
        )

    # -- nhánh RETRIEVAL ---------------------------------------------------

    async def answer_retrieval(self, task: str, context: str = ""):
        """Trả lời dựa trên tài liệu nội bộ hoặc kết quả tìm kiếm web."""
        system = self._get_prompt("RETRIEVAL_SYSTEM")
        ctx = context or "(không có tài liệu liên quan)"
        try:
            system = system.format(context=ctx)
        except KeyError:
            # CONSULT_SYSTEM cũ cần thêm {schema}
            system = system.format(schema=Prompts.DB_SCHEMA, context=ctx)
        return await self.generate_chat(
            system=system,
            user=task,
            max_new_tokens=512,
            temperature=0.2,
        )

    # -- nhánh DATA_INTERNAL -----------------------------------------------

    async def answer_data(self, task: str, context: str = ""):
        """Trả lời CHỈ dựa trên dữ liệu thật lấy từ DB cửa hàng."""
        system = self._get_prompt("DATA_SYSTEM")
        ctx = context or "(chưa có dữ liệu)"
        try:
            system = system.format(context=ctx)
        except KeyError:
            system = system.format(schema=Prompts.DB_SCHEMA, context=ctx)
        return await self.generate_chat(
            system=system,
            user=task,
            max_new_tokens=384,
            temperature=0.1,   # thấp nhất: dữ liệu thật, không được bịa
        )

    # -- tương thích ngược -------------------------------------------------

    async def consult(self, task: str, context: str = "", history: str = ""):
        """
        Giữ lại cho code cũ (và cho src/api/routes/chat.py nếu chưa kịp sửa).
        Mặc định đi nhánh RETRIEVAL vì đó là hành vi gần nhất với bản cũ.
        """
        user = task if not history else f"{history}\n\n{task}"
        return await self.answer_retrieval(user, context=context)