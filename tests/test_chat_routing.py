"""
tests/test_chat_routing.py — đường phục vụ của /chat: RAG và vòng agentic.

VÌ SAO CÓ FILE NÀY
------------------
Nhánh RETRIEVAL gọi `kb.search(user_msg, top_k=2)` trong khi chữ ký là
`search(workspace_id, query, top_k)`. Lời gọi đó ném TypeError, rơi vào
`except Exception` ngay dưới, ghi một dòng warning rồi im lặng chuyển sang tra
web. Kho tài liệu CHƯA TỪNG chạy ở đường phục vụ, và triệu chứng duy nhất là
"câu trả lời hơi chung chung" — không lỗi, không cảnh báo, không ai biết.

Không một test đơn vị nào của `KnowledgeBase` bắt được chuyện này: bản thân
`search()` luôn đúng. Chỗ hỏng nằm ở LỜI GỌI. Nên các test dưới đây kiểm đúng
mối nối giữa hai bên, và cố tình dùng KB giả có chữ ký THẬT.
"""

from __future__ import annotations

import inspect

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.core.knowledge import KnowledgeBase
from src.core.retrieval_policy import KHONG_CO_TAI_LIEU

client = TestClient(app)


class _KhoGia:
    """
    KB giả nhưng chữ ký `search` COPY TỪ BẢN THẬT.

    Nếu chỉ viết `def search(self, *args, **kwargs)` thì test này vẫn xanh với
    đúng con bug nó sinh ra để bắt. Ràng buộc dưới đây khoá điều đó lại.
    """

    def __init__(self, passages=None):
        self.passages = passages or []
        self.calls = []

    def search(self, workspace_id: str, query: str, top_k: int = 3, **kw):
        self.calls.append({"workspace_id": workspace_id, "query": query, "top_k": top_k})
        return self.passages

    def workspaces(self):
        return []


class _ManagerGia:
    def __init__(self, category="RETRIEVAL", answer="Trả lời từ tài liệu."):
        self.category = category
        self.answer = answer
        self.contexts = []
        self.decisions = []

    async def analyze_task(self, text):
        return {"category": self.category, "score": 1.0, "margin": 1.0,
                "method": "test"}

    async def answer_retrieval(self, task, context="", history=None):
        self.contexts.append(context)
        return self.answer

    async def answer_general(self, task, history=None):
        return self.answer

    async def answer_data(self, task, context="", history=None):
        self.contexts.append(context)
        return self.answer

    async def generate_chat(self, system, user, **kwargs):
        """Dùng cho vòng agentic — trả lần lượt các quyết định đã soạn."""
        import json
        return json.dumps(self.decisions.pop(0), ensure_ascii=False)


@pytest.fixture
def moi_truong(monkeypatch):
    """Dựng runtime tối thiểu để `/chat` chạy được mà không cần GPU."""
    from src.api import dependencies as deps
    from src.core.engine import ModelEngine

    async def khong_lam_gi():
        return None

    manager = _ManagerGia()
    monkeypatch.setattr(deps.runtime, "ensure_text_runtime", khong_lam_gi)
    monkeypatch.setattr(deps.runtime, "manager", manager, raising=False)
    monkeypatch.setattr(deps.runtime, "coder", object(), raising=False)
    monkeypatch.setattr(deps.runtime, "memory", None, raising=False)
    # `background_worker` là hàm thuần điều phối, không đụng GPU — mượn bản thật
    # để test đi qua đúng đường mà production đi.
    monkeypatch.setattr(
        deps.runtime, "engine",
        ModelEngine.__new__(ModelEngine), raising=False,
    )
    return manager


def _hoi(cau: str) -> str:
    """Gửi một câu vào /chat rồi lấy câu trả lời cuối."""
    resp = client.post("/chat", json={"user_id": 1, "store_id": 1, "message": cau})
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]
    ket_qua = client.get(f"/api/v1/task/{task_id}").json()
    assert ket_qua["status"] == "completed", ket_qua
    return ket_qua["result"]["answer"]


# ---------------------------------------------------------------------------
# Regression: lời gọi kho tri thức
# ---------------------------------------------------------------------------

def test_chu_ky_kho_gia_khop_ban_that():
    """Khoá KB giả vào chữ ký thật — nếu không, test dưới vô nghĩa."""
    that = inspect.signature(KnowledgeBase.search)
    gia = inspect.signature(_KhoGia.search)
    assert list(that.parameters)[:4] == list(gia.parameters)[:4]


def test_retrieval_goi_kho_dung_pham_vi_va_cau_hoi(moi_truong, monkeypatch):
    from src.api import dependencies as deps

    kho = _KhoGia(passages=[])
    monkeypatch.setattr(deps.runtime, "kb", kho, raising=False)
    _hoi("nghị định 72 quy định thuế suất bao nhiêu")

    assert len(kho.calls) == 1, "kho tri thức phải được hỏi, không được bỏ qua"
    goi = kho.calls[0]
    assert goi["query"] == "nghị định 72 quy định thuế suất bao nhiêu"
    # Phạm vi KHÔNG phải store_id: hợp đồng là của cả công ty, không của kho hàng.
    assert goi["workspace_id"] and goi["workspace_id"] != "1"


def test_tim_thay_tai_lieu_thi_dua_vao_ngu_canh(moi_truong, monkeypatch):
    from src.api import dependencies as deps
    from src.core.knowledge import Passage

    doan = Passage(
        text="Bên B thanh toán trong 30 ngày kể từ ngày nhận hàng.",
        source="hop_dong.docx", score=0.9, heading="Điều 5",
    )
    monkeypatch.setattr(deps.runtime, "kb", _KhoGia(passages=[doan]), raising=False)
    _hoi("quy định thanh toán trong hợp đồng thế nào")

    assert moi_truong.contexts, "phải gọi answer_retrieval với ngữ cảnh"
    ctx = moi_truong.contexts[0]
    assert "TÀI LIỆU NỘI BỘ" in ctx and "30 ngày" in ctx
    assert "hop_dong.docx" in ctx, "phải dẫn được nguồn"


# ---------------------------------------------------------------------------
# Chính sách tra web
# ---------------------------------------------------------------------------

def test_cau_hoi_noi_bo_khong_thay_tai_lieu_thi_khong_tra_web(
    moi_truong, monkeypatch
):
    """
    Trả một trang trên mạng cho câu "chính sách công nợ bên mình" là trình bày
    thông tin của công ty khác như thể là quy định của họ.
    """
    from src.api import dependencies as deps
    from src.api.routes import chat as chat_mod

    da_tra_web = []
    monkeypatch.setattr(deps.runtime, "kb", _KhoGia(passages=[]), raising=False)
    monkeypatch.setattr(
        chat_mod, "web_search_fallback",
        lambda q: da_tra_web.append(q) or "kết quả web",
    )

    tra_loi = _hoi("chính sách công nợ bên mình quy định thế nào")

    assert da_tra_web == [], "không được tra web cho câu hỏi tài liệu nội bộ"
    assert tra_loi == KHONG_CO_TAI_LIEU


def test_cau_hoi_luat_thi_van_duoc_tra_web(moi_truong, monkeypatch):
    from src.api import dependencies as deps
    from src.api.routes import chat as chat_mod

    da_tra_web = []
    monkeypatch.setattr(deps.runtime, "kb", _KhoGia(passages=[]), raising=False)
    monkeypatch.setattr(
        chat_mod, "web_search_fallback",
        lambda q: da_tra_web.append(q) or "Nghị định 72/2024 quy định...",
    )

    _hoi("nghị định 72 quy định thuế suất bao nhiêu")

    assert len(da_tra_web) == 1
    assert "KẾT QUẢ TÌM KIẾM" in moi_truong.contexts[0]


# ---------------------------------------------------------------------------
# Khép vòng: nạp qua HTTP -> hỏi qua /chat
# ---------------------------------------------------------------------------

def test_tai_lieu_nap_qua_http_thi_chat_tra_cuu_duoc(moi_truong, monkeypatch):
    """
    Phép kiểm duy nhất chứng minh hai đầu KHỚP NHAU.

    Đường nạp và đường tra dùng hai khoá phạm vi khác nhau là hỏng câm: giao
    diện vẫn liệt kê đủ tài liệu, chat vẫn trả lời trôi chảy, chỉ là chưa bao
    giờ đọc tới file nào. Không test nào ở một phía bắt được — nên test này
    dùng `KnowledgeBase` THẬT và đi qua đúng endpoint mà Body gọi.
    """
    from io import BytesIO

    docx = pytest.importorskip("docx")
    from src.api import dependencies as deps
    from src.core.config import Config
    from tests.test_knowledge import FakeCollection, FakeEmbedder, FakeReranker

    kb = KnowledgeBase(
        embedder=FakeEmbedder(), reranker=FakeReranker(), collection=FakeCollection(),
    )
    monkeypatch.setattr(deps.runtime, "kb", kb, raising=False)

    d = docx.Document()
    d.add_paragraph("QUY ĐỊNH CÔNG NỢ")
    d.add_paragraph("Khách hàng thanh toán trong 30 ngày kể từ ngày nhận hàng.")
    buf = BytesIO()
    d.save(buf)

    # Nạp bằng ĐÚNG khoá mà Body dùng (BRAIN_KB_WORKSPACE, mặc định "default").
    nap = client.post(
        "/knowledge/documents",
        files={"file": ("quy_dinh.docx", BytesIO(buf.getvalue()),
                        "application/octet-stream")},
        data={"workspace_id": Config().kb_workspace_id},
    )
    assert nap.status_code == 200, nap.text
    assert nap.json()["chunks"] > 0

    _hoi("quy định công nợ thanh toán bao nhiêu ngày")

    assert moi_truong.contexts, "chat phải hỏi kho tri thức"
    ctx = moi_truong.contexts[0]
    assert "TÀI LIỆU NỘI BỘ" in ctx, f"chat không đọc tới tài liệu đã nạp: {ctx!r}"
    assert "30 ngày" in ctx and "quy_dinh.docx" in ctx


# ---------------------------------------------------------------------------
# Vòng agentic
# ---------------------------------------------------------------------------

def test_cau_nhieu_buoc_di_vao_vong_agentic(moi_truong, monkeypatch):
    """
    Câu ba bước phải đi vào vòng agentic, và vì chưa có nguồn dữ liệu bán hàng
    thì nói thẳng — KHÔNG để model tự nghĩ ra doanh thu rồi báo cáo trên số đó.
    """
    from src.api import dependencies as deps

    monkeypatch.setattr(deps.runtime, "kb", None, raising=False)
    moi_truong.category = "REPORT"
    moi_truong.decisions = [
        {"thought": "cần số liệu", "tool": "report", "arguments": {"sales": []}},
    ]

    tra_loi = _hoi("quý này lãi hay lỗ, mặt hàng nào lãi nhất")

    assert "chưa nối được" in tra_loi or "chưa lấy được" in tra_loi
    assert moi_truong.decisions == [], "vòng agentic phải thực sự chạy"


def test_cau_chao_hoi_khong_bi_keo_vao_vong_agentic(moi_truong, monkeypatch):
    from src.api import dependencies as deps

    monkeypatch.setattr(deps.runtime, "kb", None, raising=False)
    moi_truong.category = "GENERAL"
    moi_truong.answer = "Chào bạn, tôi giúp được gì?"

    assert _hoi("xin chào") == "Chào bạn, tôi giúp được gì?"


def test_nhanh_logistics_khong_bi_vong_agentic_giành_mat(moi_truong, monkeypatch):
    """
    LOGISTICS đã có luồng struct riêng và đang chạy được. Bảng luật tool không
    được giành lấy nó.
    """
    from src.api import dependencies as deps
    from src.core.tool_planner import plan_tools

    monkeypatch.setattr(deps.runtime, "kb", None, raising=False)
    assert plan_tools("nhà xe nào rẻ nhất cho chuyến này") == ["carrier_selection"]

    moi_truong.category = "LOGISTICS"

    async def trich_xuat(*a, **kw):
        return '{"origin": null}'

    moi_truong.extract_quote_request = trich_xuat
    tra_loi = _hoi("nhà xe nào rẻ nhất cho chuyến này")

    # Đi vào nhánh báo giá (hỏi thêm trường thiếu), KHÔNG vào vòng agentic.
    assert "tôi cần thêm" in tra_loi.lower()
