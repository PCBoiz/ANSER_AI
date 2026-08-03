"""
src/core/knowledge.py — kho tri thức (RAG). Viết lại 03/08/2026.

VÌ SAO VIẾT LẠI CHỨ KHÔNG VÁ
----------------------------
Bản cũ 164 dòng có tám lỗi, và bảy trong số đó đều nằm trong cùng một hàm
`search()` hoặc trong cách dữ liệu được ghi vào — vá từng chỗ thì phải sửa gần
hết số dòng, mà vẫn giữ lại kiến trúc gây ra chúng.

Bốn lỗi nặng nhất, mỗi lỗi đều IM LẶNG:

1. **Không tách theo khách.** Một collection `project_a_docs` dùng chung, metadata
   chỉ có `{"source": tên_file}`. Hai khách dùng chung Brain là bảng giá của khách
   A trả lời câu hỏi của khách B. Đây là vi phạm P2 ngay ở lõi.

2. **`search()` trả về một chuỗi đã nối** (`"\\n---\\n".join(docs)`), mất sạch
   nguồn — vì ứng viên bị hạ xuống chuỗi thô ngay từ lúc lấy ra. Nên
   `RetailChatResponse.sources` không bao giờ điền thật được, và câu trả lời
   "cước Hà Nội – Đà Nẵng là 12 triệu" không kiểm chứng được.

3. **Cập nhật tài liệu KHÔNG có tác dụng.** `ingest_folder` bỏ qua file đã có mặt
   trong DB, và `add_document` dùng id cố định `f"{source}_{i}"`. Sửa bảng giá rồi
   nạp lại = không có gì đổi. Bảng giá năm ngoái sống mãi, và model trả lời bằng
   nó với giọng chắc nịch y hệt.

4. **Reranker tiếng Anh chấm điểm tiếng Việt, rồi điểm đó dùng làm ngưỡng lọc.**
   Tầng chống lạc đề đang lọc bằng một con số gần như ngẫu nhiên.

Thêm hai lỗi về chất lượng: embedder cũ cắt cụt ở 128 token (đoạn 150 từ tiếng
Việt là 225–300 token, tức quá nửa mỗi đoạn chưa từng được nhúng), và cắt đoạn
làm phẳng cấu trúc bảng — xem `src/core/chunking.py`.

THIẾT KẾ MỚI
------------
- `workspace_id` là THAM SỐ BẮT BUỘC ở mọi lối vào. Không có giá trị mặc định:
  quên truyền là lỗi ngay lúc gọi, không phải rò dữ liệu lặng lẽ ba tháng sau.
- `search()` trả `list[Passage]` — có `source`, `heading`, `score`, ngày hiệu lực.
- Tài liệu hết hiệu lực bị LOẠI, không phải xếp hạng thấp. Giữ lại trong kho để
  trả lời câu hỏi về quá khứ, nhưng không bao giờ lọt vào câu trả lời hôm nay.
- Nạp lại theo `content_hash`: nội dung đổi thì xoá sạch đoạn cũ rồi ghi mới.
- Embedder/reranker chạy CPU mặc định (xem RAG_VLM_KE_HOACH.md §B.2.4: nhét cả
  VLM 3B lẫn hai model RAG lên L4 22,5GB là tràn).
- `__init__` KHÔNG đọc đĩa, KHÔNG nhúng gì. Nạp là việc gọi tường minh.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional, Protocol

from src.core.chunking import chunk_document, looks_tabular

logger = logging.getLogger("projecta.knowledge")

# Ngày dạng số để so sánh khoảng trong Chroma (where numeric).
_DATE_MIN = 10000101
_DATE_MAX = 99991231

# Giá trị mặc định — đổi bằng env, KHÔNG sửa code.
EMBEDDER_ID = os.getenv("KB_EMBEDDER_ID", "BAAI/bge-m3")
# ViRanker: chuyên tiếng Việt, nền BGE-M3, giấy phép Apache-2.0.
# KHÔNG dùng jina-reranker-v2: CC-BY-NC-4.0, cấm dùng thương mại.
RERANKER_ID = os.getenv("KB_RERANKER_ID", "namdp-ptit/ViRanker")
# 0..1 sau sigmoid — lần đầu tiên ngưỡng này có nghĩa. Reranker cũ trả logit thô
# của một model tiếng Anh, ngưỡng 0.0 trên đó chỉ là con số cho có.
RELEVANCE_THRESHOLD = float(os.getenv("KB_RELEVANCE_THRESHOLD", "0.5"))


# ---------------------------------------------------------------------------
# Kiểu dữ liệu
# ---------------------------------------------------------------------------

@dataclass
class Passage:
    """
    Một đoạn tài liệu kèm ĐỦ thứ để dẫn nguồn.

    Bản cũ trả chuỗi nối, nên không câu trả lời nào truy ngược được. Với câu hỏi
    nghiệp vụ, "theo Bảng giá cước 2026, hiệu lực 01/01/2026" khác hẳn "theo tôi
    biết" — người đọc phải mở đúng tài liệu đó ra đối chiếu được.
    """
    text: str
    source: str
    score: float
    chunk_index: int = 0
    heading: str = ""
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None

    def cite(self) -> str:
        """Chuỗi dẫn nguồn ngắn để chèn vào prompt."""
        phan = f" ({self.heading})" if self.heading else ""
        hieu_luc = f", hiệu lực từ {self.effective_from}" if self.effective_from else ""
        return f"{self.source}{phan}{hieu_luc}"


@dataclass
class IngestResult:
    source: str
    chunks: int = 0
    replaced: bool = False
    skipped_unchanged: bool = False
    warnings: list[str] = field(default_factory=list)


class Embedder(Protocol):
    def encode(self, texts: list[str], **kwargs: Any) -> Any: ...


class Reranker(Protocol):
    def predict(self, pairs: list[list[str]], **kwargs: Any) -> Any: ...


# ---------------------------------------------------------------------------
# Hàm thuần — kiểm được không cần model, không cần DB
# ---------------------------------------------------------------------------

def to_date_int(value: Optional[str], default: int) -> int:
    """
    Ngày -> số YYYYMMDD để so sánh khoảng. Rỗng/sai định dạng -> `default`.

    Nhận CẢ HAI định dạng: ISO `2026-01-01` và kiểu Việt Nam `01/01/2026`.

    Bản đầu chỉ gom chữ số rồi ép sang int, nên `01/01/2026` ra `1012026` — năm
    101. Tài liệu ghi ngày kiểu Việt Nam khi đó thành "có hiệu lực từ hai nghìn
    năm trước", tức không bao giờ bị loại. Đúng thứ người dùng Việt gõ ra tự
    nhiên nhất lại là thứ vô hiệu hoá cả tầng lọc hiệu lực (03/08/2026).
    """
    if not value:
        return default
    text = str(value).strip()

    for sep, order in (("-", "ymd"), ("/", "dmy"), (".", "dmy")):
        parts = text.split(sep)
        if len(parts) != 3 or not all(p.strip().isdigit() for p in parts):
            continue
        a, b, c = (int(p) for p in parts)
        y, m, d = (a, b, c) if order == "ymd" else (c, b, a)
        try:
            return int(date(y, m, d).strftime("%Y%m%d"))
        except ValueError:
            break

    logger.warning(
        "Ngày hiệu lực không đọc được: %r — bỏ qua (dùng YYYY-MM-DD hoặc DD/MM/YYYY)",
        value,
    )
    return default


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def sigmoid(x: float) -> float:
    # Chặn biên trước khi exp: logit rất âm làm exp tràn số.
    if x < -30:
        return 0.0
    if x > 30:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))


def is_effective(meta: dict[str, Any], on: int) -> bool:
    """
    Đoạn này còn hiệu lực vào ngày `on` (dạng YYYYMMDD) không?

    Thiếu metadata thì coi là CÒN hiệu lực — tài liệu nội bộ thường không ghi
    ngày, loại hết chúng đi là kho rỗng. Chỉ loại khi có ngày và ngày đã qua.
    """
    return (
        to_date_int(meta.get("effective_from"), _DATE_MIN) <= on
        <= to_date_int(meta.get("effective_to"), _DATE_MAX)
    )


def merge_candidates(
    dense: list[tuple[str, dict[str, Any]]],
    lexical: list[tuple[str, dict[str, Any]]],
) -> list[tuple[str, dict[str, Any]]]:
    """
    Gộp ứng viên hai tầng, khử trùng lặp mà GIỮ metadata.

    Bản cũ dùng `list(set(candidates))` trên chuỗi thô — vừa mất metadata (nên
    không dẫn nguồn được), vừa làm thứ tự đổi mỗi lần chạy vì `set` của Python
    không ổn định giữa các phiên. Ở đây khử theo `(source, chunk_index)` và giữ
    nguyên thứ tự xuất hiện.
    """
    out: list[tuple[str, dict[str, Any]]] = []
    seen: set[tuple[str, int]] = set()
    for text, meta in [*dense, *lexical]:
        key = (str(meta.get("source", "")), int(meta.get("chunk_index", 0)))
        if key in seen:
            continue
        seen.add(key)
        out.append((text, meta))
    return out


def select_relevant(
    scored: list[tuple[float, str, dict[str, Any]]],
    threshold: float,
    top_k: int,
) -> list[Passage]:
    """Lọc theo ngưỡng rồi lấy top_k. Không có gì vượt ngưỡng thì trả RỖNG."""
    scored = sorted(scored, key=lambda x: x[0], reverse=True)
    ket_qua = [
        Passage(
            text=text,
            source=str(meta.get("source", "?")),
            score=round(float(score), 4),
            chunk_index=int(meta.get("chunk_index", 0)),
            heading=str(meta.get("heading", "")),
            effective_from=meta.get("effective_from") or None,
            effective_to=meta.get("effective_to") or None,
        )
        for score, text, meta in scored
        if score >= threshold
    ]
    return ket_qua[:top_k]


def format_for_prompt(passages: list[Passage]) -> str:
    """
    Dựng khối ngữ cảnh có ĐÁNH SỐ NGUỒN để model dẫn lại được.

    Đánh số chứ không chỉ ghi tên file: model dẫn "[1]" ngắn gọn và ta ánh xạ
    ngược ra tài liệu, thay vì để nó chép lại tên file dài rồi chép sai.
    """
    if not passages:
        return ""
    khoi = []
    for i, p in enumerate(passages, start=1):
        khoi.append(f"[{i}] {p.cite()}\n{p.text}")
    return "\n\n---\n\n".join(khoi)


# ---------------------------------------------------------------------------
# Kho tri thức
# ---------------------------------------------------------------------------

class KnowledgeBase:
    """
    Kho tri thức có CÁCH LY THEO KHÁCH.

    Mọi phương thức đọc/ghi đều đòi `workspace_id`. Không có giá trị mặc định và
    không có đường vòng: đó là toàn bộ hàng rào ngăn dữ liệu khách này chảy sang
    câu trả lời của khách kia.
    """

    def __init__(
        self,
        persist_dir: str = "./data/vector_db",
        *,
        embedder: Optional[Embedder] = None,
        reranker: Optional[Reranker] = None,
        collection: Any = None,
        device: Optional[str] = None,
    ):
        # Tiêm được từ ngoài -> test chạy không cần tải 600MB model, và đổi model
        # không phải sửa code. `None` thì nạp lười ở lần dùng đầu tiên.
        self._embedder = embedder
        self._reranker = reranker
        self._collection = collection
        self.persist_dir = persist_dir
        # CPU mặc định: xem RAG_VLM_KE_HOACH.md §B.2.4 — cộng cả VLM 3B thì L4
        # 22,5GB không đủ chỗ. Truy vấn RAG thưa, đổi độ trễ lấy VRAM là hời.
        self.device = device or os.getenv("KB_DEVICE", "cpu")
        self._bm25_cache: dict[str, Any] = {}

        # KHÔNG nạp tài liệu ở đây. Bản cũ gọi `ingest_folder()` trong __init__,
        # tức dựng đối tượng là quét đĩa + nhúng toàn bộ kho -> chặn startup.

    # -- nạp lười -----------------------------------------------------------

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            from sentence_transformers import SentenceTransformer
            logger.info("Nạp embedder %s trên %s", EMBEDDER_ID, self.device)
            self._embedder = SentenceTransformer(EMBEDDER_ID, device=self.device)
        return self._embedder

    def loaded_embedder(self) -> Optional[Embedder]:
        """
        Embedder NẾU đã nạp — không ép nạp.

        Có riêng hàm này vì `SemanticRouter` dùng chung embedder của KB để khỏi
        nạp trùng lên VRAM, nhưng nó hỏi lúc dựng đối tượng. Đọc thẳng thuộc
        tính `embedder` ở đó sẽ kéo 600MB model xuống ngay lúc khởi động — đúng
        thứ việc nạp lười sinh ra để tránh.
        """
        return self._embedder

    @property
    def reranker(self) -> Reranker:
        if self._reranker is None:
            from sentence_transformers import CrossEncoder
            logger.info("Nạp reranker %s trên %s", RERANKER_ID, self.device)
            self._reranker = CrossEncoder(RERANKER_ID, device=self.device)
        return self._reranker

    @property
    def collection(self) -> Any:
        if self._collection is None:
            import chromadb
            os.makedirs(self.persist_dir, exist_ok=True)
            client = chromadb.PersistentClient(path=self.persist_dir)
            self._collection = client.get_or_create_collection(name="anser_docs")
        return self._collection

    # -- ghi ----------------------------------------------------------------

    def add_document(
        self,
        workspace_id: str,
        text: str,
        source: str,
        *,
        effective_from: Optional[str] = None,
        effective_to: Optional[str] = None,
        doc_type: str = "",
    ) -> IngestResult:
        """
        Nạp (hoặc nạp lại) một tài liệu.

        Nội dung không đổi thì bỏ qua. Đổi thì XOÁ SẠCH đoạn cũ rồi ghi mới —
        bản cũ chỉ ghi thêm với id cố định, nên bản mới ít đoạn hơn để lại đoạn
        thừa mồ côi của bản cũ, và giá cũ tiếp tục được trả lời.
        """
        if not workspace_id:
            raise ValueError("Thiếu workspace_id — không được nạp tài liệu vào kho chung.")
        if not source:
            raise ValueError("Thiếu tên nguồn (source) — không dẫn nguồn được.")

        res = IngestResult(source=source)
        digest = content_hash(text)

        cu = self.collection.get(where={"$and": [
            {"workspace_id": workspace_id}, {"source": source},
        ]})
        ids_cu = cu.get("ids") or []
        if ids_cu:
            metas = cu.get("metadatas") or []
            if metas and metas[0].get("content_hash") == digest:
                res.skipped_unchanged = True
                return res
            self.collection.delete(ids=ids_cu)
            res.replaced = True

        chunks = chunk_document(text)
        if not chunks:
            res.warnings.append("Tài liệu rỗng hoặc không đọc được nội dung.")
            return res

        if looks_tabular(text) and not any("\t" in c.text or "|" in c.text for c in chunks):
            res.warnings.append(
                "Trông như bảng nhưng cấu trúc cột đã mất khi đọc file — "
                "số liệu trong đó sẽ mất ngữ cảnh. Kiểm tra lại bản xuất."
            )

        meta_chung = {
            "workspace_id": workspace_id,
            "source": source,
            "content_hash": digest,
            "doc_type": doc_type,
            "effective_from": effective_from or "",
            "effective_to": effective_to or "",
            "eff_from_int": to_date_int(effective_from, _DATE_MIN),
            "eff_to_int": to_date_int(effective_to, _DATE_MAX),
        }

        texts = [c.text for c in chunks]
        self.collection.add(
            ids=[f"{workspace_id}:{source}:{digest}:{c.index}" for c in chunks],
            documents=texts,
            embeddings=[list(v) for v in self.embedder.encode(texts)],
            metadatas=[{**meta_chung, "chunk_index": c.index, "heading": c.heading}
                       for c in chunks],
        )
        self._bm25_cache.pop(workspace_id, None)
        res.chunks = len(chunks)
        logger.info("Nạp %s (%s): %d đoạn%s",
                    source, workspace_id, len(chunks), " — thay bản cũ" if res.replaced else "")
        return res

    def delete_document(self, workspace_id: str, source: str) -> int:
        if not workspace_id:
            raise ValueError("Thiếu workspace_id.")
        got = self.collection.get(where={"$and": [
            {"workspace_id": workspace_id}, {"source": source},
        ]})
        ids = got.get("ids") or []
        if ids:
            self.collection.delete(ids=ids)
            self._bm25_cache.pop(workspace_id, None)
        return len(ids)

    def list_documents(self, workspace_id: str) -> list[dict[str, Any]]:
        """Tài liệu đang có, kèm ngày hiệu lực — để người dùng thấy cái gì đã cũ."""
        got = self.collection.get(where={"workspace_id": workspace_id})
        theo_nguon: dict[str, dict[str, Any]] = {}
        for meta in got.get("metadatas") or []:
            src = meta.get("source", "?")
            entry = theo_nguon.setdefault(src, {
                "source": src,
                "doc_type": meta.get("doc_type", ""),
                "effective_from": meta.get("effective_from") or None,
                "effective_to": meta.get("effective_to") or None,
                "chunks": 0,
            })
            entry["chunks"] += 1
        return sorted(theo_nguon.values(), key=lambda d: d["source"])

    # -- đọc ----------------------------------------------------------------

    def _bm25_for(self, workspace_id: str) -> tuple[Any, list[tuple[str, dict[str, Any]]]]:
        """BM25 dựng THEO WORKSPACE. Bản cũ kéo cả kho vào RAM mỗi lần dựng lại."""
        if workspace_id in self._bm25_cache:
            return self._bm25_cache[workspace_id]

        from rank_bm25 import BM25Okapi
        from underthesea import word_tokenize

        got = self.collection.get(where={"workspace_id": workspace_id})
        docs = got.get("documents") or []
        metas = got.get("metadatas") or []
        pairs = list(zip(docs, metas))
        bm25 = BM25Okapi([word_tokenize(d.lower()) for d in docs]) if docs else None
        self._bm25_cache[workspace_id] = (bm25, pairs)
        return bm25, pairs

    def search(
        self,
        workspace_id: str,
        query: str,
        top_k: int = 3,
        *,
        on_date: Optional[date] = None,
        n_candidates: int = 10,
    ) -> list[Passage]:
        """
        Tìm đoạn liên quan TRONG PHẠM VI một khách hàng.

        Trả `list[Passage]` có nguồn, không phải chuỗi nối — đó là điều kiện để
        câu trả lời dẫn được nguồn.
        """
        if not workspace_id:
            raise ValueError("Thiếu workspace_id — tìm kiếm không phạm vi là rò dữ liệu.")
        if not query.strip():
            return []

        ngay = int((on_date or date.today()).strftime("%Y%m%d"))
        # Lọc hiệu lực NGAY TRONG TRUY VẤN, không lọc sau khi xếp hạng: tài liệu
        # hết hiệu lực không được chiếm chỗ trong danh sách ứng viên rồi mới bị
        # loại, vì như thế tài liệu còn hiệu lực bị đẩy ra ngoài top-N.
        dieu_kien = {"$and": [
            {"workspace_id": workspace_id},
            {"eff_from_int": {"$lte": ngay}},
            {"eff_to_int": {"$gte": ngay}},
        ]}

        dense: list[tuple[str, dict[str, Any]]] = []
        kq = self.collection.query(
            query_embeddings=[list(v) for v in self.embedder.encode([query])],
            n_results=n_candidates,
            where=dieu_kien,
        )
        docs = (kq.get("documents") or [[]])[0]
        metas = (kq.get("metadatas") or [[]])[0]
        dense = list(zip(docs, metas))

        lexical: list[tuple[str, dict[str, Any]]] = []
        try:
            bm25, pairs = self._bm25_for(workspace_id)
            if bm25 and pairs:
                from underthesea import word_tokenize
                diem = bm25.get_scores(word_tokenize(query.lower()))
                xep = sorted(zip(diem, pairs), key=lambda x: x[0], reverse=True)
                lexical = [p for _, p in xep[:5] if is_effective(p[1], ngay)]
        except Exception as exc:  # BM25 hỏng không được làm chết cả tìm kiếm
            logger.warning("BM25 lỗi, chỉ dùng dense: %s", exc)

        candidates = merge_candidates(dense, lexical)
        if not candidates:
            logger.info("KB[%s]: không có ứng viên nào còn hiệu lực ngày %d", workspace_id, ngay)
            return []

        raw = self.reranker.predict([[query, text] for text, _ in candidates])
        # Chuẩn hoá về 0..1: bge-m3/ViRanker trả logit, ngưỡng chỉ có nghĩa sau
        # sigmoid. Model nào đã trả sẵn 0..1 thì sigmoid gần như giữ nguyên thứ
        # tự, nên không sai lệch xếp hạng.
        scored = [
            (sigmoid(float(s)), text, meta)
            for s, (text, meta) in zip(list(raw), candidates)
        ]

        passages = select_relevant(scored, RELEVANCE_THRESHOLD, top_k)
        if not passages:
            cao_nhat = max((s for s, _, _ in scored), default=float("nan"))
            logger.info("KB[%s]: không đoạn nào vượt ngưỡng %.2f (cao nhất %.2f)",
                        workspace_id, RELEVANCE_THRESHOLD, cao_nhat)
        return passages

    def search_text(self, workspace_id: str, query: str, top_k: int = 3, **kwargs: Any) -> str:
        """
        Bản trả chuỗi cho chỗ gọi cũ — nhưng CÓ đánh số nguồn.

        Giữ lại để `ManagerAgent` không phải sửa cùng lúc, nhưng chỗ gọi mới nên
        dùng `search()` để còn dẫn nguồn được.
        """
        return format_for_prompt(self.search(workspace_id, query, top_k, **kwargs))


__all__ = [
    "IngestResult",
    "KnowledgeBase",
    "Passage",
    "content_hash",
    "format_for_prompt",
    "is_effective",
    "merge_candidates",
    "select_relevant",
    "sigmoid",
    "to_date_int",
]
