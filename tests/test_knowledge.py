"""
tests/test_knowledge.py — kho tri thức: cách ly khách, dẫn nguồn, ngày hiệu lực.

Dùng embedder/reranker/collection GIẢ tiêm từ ngoài, nên chạy được mà không tải
600MB model. Thứ đang kiểm là LOGIC — cách ly, lọc hiệu lực, khử trùng lặp, dẫn
nguồn — chứ không phải chất lượng ngữ nghĩa của model.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.core.knowledge import (
    KnowledgeBase,
    Passage,
    content_hash,
    format_for_prompt,
    is_effective,
    merge_candidates,
    select_relevant,
    sigmoid,
    to_date_int,
)

# ---------------------------------------------------------------------------
# Đồ giả
# ---------------------------------------------------------------------------

class FakeEmbedder:
    def encode(self, texts, **kwargs):
        return [[float(len(t) % 7), 1.0] for t in texts]


class FakeReranker:
    """Điểm = số từ khoá truy vấn xuất hiện trong đoạn (logit thô)."""
    def predict(self, pairs, **kwargs):
        out = []
        for query, doc in pairs:
            tu = [w for w in query.lower().split() if len(w) > 2]
            trung = sum(1 for w in tu if w in doc.lower())
            out.append(float(trung * 2 - 1))
        return out


class FakeCollection:
    """Chroma tối giản: đủ `add` / `get` / `delete` / `query` với `where`."""

    def __init__(self):
        self.rows: dict[str, dict] = {}

    def add(self, ids, documents, embeddings, metadatas):
        for i, d, m in zip(ids, documents, metadatas):
            self.rows[i] = {"doc": d, "meta": dict(m)}

    @staticmethod
    def _match(meta, where) -> bool:
        if not where:
            return True
        if "$and" in where:
            return all(FakeCollection._match(meta, c) for c in where["$and"])
        for key, cond in where.items():
            got = meta.get(key)
            if isinstance(cond, dict):
                if "$lte" in cond and not (got is not None and got <= cond["$lte"]):
                    return False
                if "$gte" in cond and not (got is not None and got >= cond["$gte"]):
                    return False
            elif got != cond:
                return False
        return True

    def get(self, where=None, **kwargs):
        hit = [(i, r) for i, r in self.rows.items() if self._match(r["meta"], where)]
        return {
            "ids": [i for i, _ in hit],
            "documents": [r["doc"] for _, r in hit],
            "metadatas": [r["meta"] for _, r in hit],
        }

    def delete(self, ids):
        for i in ids:
            self.rows.pop(i, None)

    def query(self, query_embeddings, n_results, where=None, **kwargs):
        hit = [r for r in self.rows.values() if self._match(r["meta"], where)][:n_results]
        return {
            "documents": [[r["doc"] for r in hit]],
            "metadatas": [[r["meta"] for r in hit]],
        }


@pytest.fixture
def kb():
    return KnowledgeBase(
        embedder=FakeEmbedder(), reranker=FakeReranker(), collection=FakeCollection(),
    )


BANG_GIA_2026 = (
    "BẢNG GIÁ CƯỚC 2026\n"
    "Hà Nội\tĐà Nẵng\txe tải 5 tấn\t12.000.000\n"
    "Hà Nội\tTP.HCM\tcontainer 20ft\t31.500.000\n"
)
BANG_GIA_2025 = (
    "BẢNG GIÁ CƯỚC 2025\n"
    "Hà Nội\tĐà Nẵng\txe tải 5 tấn\t9.000.000\n"
)


# ---------------------------------------------------------------------------
# Cách ly theo khách — lỗ hổng CHẶN của bản cũ
# ---------------------------------------------------------------------------

def test_khach_nay_khong_thay_tai_lieu_cua_khach_kia(kb):
    kb.add_document("hoang-phat", BANG_GIA_2026, source="bang_gia.txt")
    kb.add_document("khach-khac", "BẢNG GIÁ MẬT\nHà Nội\tĐà Nẵng\t999.000.000\n",
                    source="bang_gia.txt")

    kq = kb.search("hoang-phat", "giá cước Hà Nội Đà Nẵng", top_k=5)
    assert kq, "phải tìm được tài liệu của chính khách này"
    assert all("999.000.000" not in p.text for p in kq), "RÒ dữ liệu sang khách khác"


def test_thieu_workspace_id_thi_no_ngay_khong_am_tham(kb):
    """Quên truyền phải hỏng ngay lúc gọi, không phải rò lặng lẽ ba tháng sau."""
    with pytest.raises(ValueError):
        kb.search("", "giá cước")
    with pytest.raises(ValueError):
        kb.add_document("", "nội dung", source="x.txt")
    with pytest.raises(ValueError):
        kb.delete_document("", "x.txt")


def test_cung_ten_file_o_hai_khach_la_hai_tai_lieu_doc_lap(kb):
    kb.add_document("a", BANG_GIA_2026, source="bang_gia.txt")
    kb.add_document("b", BANG_GIA_2025, source="bang_gia.txt")
    assert len(kb.list_documents("a")) == 1
    assert len(kb.list_documents("b")) == 1
    kb.delete_document("a", "bang_gia.txt")
    assert kb.list_documents("a") == []
    assert len(kb.list_documents("b")) == 1, "xoá của khách A không được đụng khách B"


# ---------------------------------------------------------------------------
# Dẫn nguồn — bản cũ trả chuỗi nối nên không truy ngược được
# ---------------------------------------------------------------------------

def test_ket_qua_mang_theo_nguon(kb):
    kb.add_document("hp", BANG_GIA_2026, source="bang_gia_2026.txt",
                    effective_from="2026-01-01")
    p = kb.search("hp", "giá cước Hà Nội Đà Nẵng")[0]
    assert isinstance(p, Passage)
    assert p.source == "bang_gia_2026.txt"
    assert p.effective_from == "2026-01-01"
    assert "bang_gia_2026.txt" in p.cite()
    assert "2026-01-01" in p.cite()


def test_khoi_prompt_co_danh_so_nguon():
    ps = [
        Passage(text="nội dung một", source="a.pdf", score=0.9),
        Passage(text="nội dung hai", source="b.docx", score=0.8, heading="Phụ lục"),
    ]
    khoi = format_for_prompt(ps)
    assert "[1] a.pdf" in khoi
    assert "[2] b.docx (Phụ lục)" in khoi


def test_khong_co_gi_thi_khoi_prompt_rong():
    assert format_for_prompt([]) == ""


def test_search_text_van_chay_cho_cho_goi_cu(kb):
    kb.add_document("hp", BANG_GIA_2026, source="bang_gia.txt")
    s = kb.search_text("hp", "giá cước Hà Nội Đà Nẵng")
    assert "[1] bang_gia.txt" in s


# ---------------------------------------------------------------------------
# Ngày hiệu lực — bảng giá cũ KHÔNG được trả lời câu hỏi hôm nay
# ---------------------------------------------------------------------------

def test_bang_gia_het_hieu_luc_bi_LOAI_khong_phai_xep_hang_thap(kb):
    kb.add_document("hp", BANG_GIA_2025, source="gia_2025.txt",
                    effective_from="2025-01-01", effective_to="2025-12-31")
    kb.add_document("hp", BANG_GIA_2026, source="gia_2026.txt",
                    effective_from="2026-01-01")

    kq = kb.search("hp", "giá cước Hà Nội Đà Nẵng", top_k=5, on_date=date(2026, 6, 1))
    nguon = {p.source for p in kq}
    assert "gia_2026.txt" in nguon
    assert "gia_2025.txt" not in nguon, "bảng giá hết hiệu lực vẫn lọt vào câu trả lời"


def test_hoi_ve_qua_khu_thi_van_tra_duoc_ban_cu(kb):
    """Không xoá tài liệu hết hiệu lực — chỉ không dùng cho câu hỏi hôm nay."""
    kb.add_document("hp", BANG_GIA_2025, source="gia_2025.txt",
                    effective_from="2025-01-01", effective_to="2025-12-31")
    kq = kb.search("hp", "giá cước Hà Nội Đà Nẵng", on_date=date(2025, 6, 1))
    assert [p.source for p in kq] == ["gia_2025.txt"]


def test_khong_ghi_ngay_thi_coi_la_con_hieu_luc(kb):
    """Tài liệu nội bộ thường không ghi ngày — loại hết là kho rỗng."""
    kb.add_document("hp", BANG_GIA_2026, source="noi_bo.txt")
    assert kb.search("hp", "giá cước Hà Nội Đà Nẵng")


@pytest.mark.parametrize("value,expect", [
    ("2026-01-01", 20260101),
    ("2026-12-31", 20261231),
    # Kiểu Việt Nam — đây là thứ người dùng gõ ra tự nhiên nhất.
    ("01/01/2026", 20260101),
    ("31/12/2026", 20261231),
    ("1/1/2026", 20260101),
    ("01.01.2026", 20260101),
    ("", 12345678),
    (None, 12345678),
    ("linh tinh", 12345678),
    ("2026-13-01", 12345678),    # tháng 13 không tồn tại
    ("32/01/2026", 12345678),    # ngày 32 không tồn tại
    ("2026", 12345678),
])
def test_to_date_int(value, expect):
    assert to_date_int(value, 12345678) == expect


def test_ngay_kieu_viet_nam_KHONG_lam_hong_tang_loc_hieu_luc():
    """
    Bản đầu gom chữ số rồi ép int, nên '01/01/2026' ra 1012026 — năm 101. Tài
    liệu ghi ngày kiểu Việt Nam khi đó thành 'hiệu lực từ hai nghìn năm trước',
    không bao giờ bị loại. Cả tầng lọc hiệu lực vô hiệu, mà không có gì báo.
    """
    assert not is_effective({"effective_to": "31/12/2025"}, 20260803)
    assert is_effective({"effective_from": "01/01/2026"}, 20260803)
    assert not is_effective({"effective_from": "01/01/2027"}, 20260803)


def test_is_effective_thieu_metadata_thi_van_dung():
    assert is_effective({}, 20260803)
    assert is_effective({"effective_from": "2026-01-01"}, 20260803)
    assert not is_effective({"effective_to": "2025-12-31"}, 20260803)
    assert not is_effective({"effective_from": "2027-01-01"}, 20260803)


# ---------------------------------------------------------------------------
# Cập nhật tài liệu — bản cũ KHÔNG cập nhật được
# ---------------------------------------------------------------------------

def test_noi_dung_khong_doi_thi_bo_qua(kb):
    kb.add_document("hp", BANG_GIA_2026, source="gia.txt")
    lai = kb.add_document("hp", BANG_GIA_2026, source="gia.txt")
    assert lai.skipped_unchanged is True
    assert lai.chunks == 0


def test_sua_bang_gia_thi_gia_CU_bien_mat_han(kb):
    """
    Đây là lỗi tệ nhất của bản cũ: id cố định + `add` (không phải `upsert`) nên
    nạp lại không đổi gì, và bản mới ít đoạn hơn để lại đoạn thừa mồ côi. Giá cũ
    tiếp tục được trả lời với giọng chắc nịch y hệt.
    """
    kb.add_document("hp", BANG_GIA_2025, source="gia.txt")
    kq = kb.search("hp", "giá cước Hà Nội Đà Nẵng")
    assert any("9.000.000" in p.text for p in kq)

    lai = kb.add_document("hp", BANG_GIA_2026, source="gia.txt")
    assert lai.replaced is True

    kq = kb.search("hp", "giá cước Hà Nội Đà Nẵng", top_k=10)
    noi = "\n".join(p.text for p in kq)
    assert "12.000.000" in noi, "giá mới phải có"
    assert "9.000.000" not in noi, "giá CŨ vẫn sống trong kho"


def test_ban_moi_ngan_hon_khong_de_lai_doan_mo_coi(kb):
    dai = "PHẦN A\n" + "\n".join(f"dòng cước {i} giá {i}00.000" for i in range(200))
    kb.add_document("hp", dai, source="gia.txt")
    nhieu_doan = kb.list_documents("hp")[0]["chunks"]
    assert nhieu_doan > 1

    kb.add_document("hp", "PHẦN A\nchỉ một dòng cước", source="gia.txt")
    assert kb.list_documents("hp")[0]["chunks"] == 1


def test_content_hash_on_dinh_va_doi_khi_noi_dung_doi():
    assert content_hash("abc") == content_hash("abc")
    assert content_hash("abc") != content_hash("abd")


# ---------------------------------------------------------------------------
# Khử trùng lặp giữ metadata — bản cũ dùng set() nên mất sạch
# ---------------------------------------------------------------------------

def test_merge_giu_metadata_va_giu_thu_tu():
    dense = [("A", {"source": "x", "chunk_index": 0}),
             ("B", {"source": "x", "chunk_index": 1})]
    lexical = [("B", {"source": "x", "chunk_index": 1}),
               ("C", {"source": "y", "chunk_index": 0})]
    out = merge_candidates(dense, lexical)
    assert [t for t, _ in out] == ["A", "B", "C"]
    assert all(isinstance(m, dict) and "source" in m for _, m in out)


def test_merge_hai_doan_TRUNG_NOI_DUNG_khac_nguon_deu_duoc_giu():
    """
    Bản cũ khử theo chuỗi thô, nên hai tài liệu khác nhau có một đoạn giống hệt
    (điều khoản mẫu, tiêu đề chung) bị gộp làm một — mất một nguồn.
    """
    out = merge_candidates(
        [("điều khoản chung", {"source": "hd_a.docx", "chunk_index": 0})],
        [("điều khoản chung", {"source": "hd_b.docx", "chunk_index": 0})],
    )
    assert len(out) == 2
    assert {m["source"] for _, m in out} == {"hd_a.docx", "hd_b.docx"}


# ---------------------------------------------------------------------------
# Ngưỡng liên quan — giờ mới có nghĩa
# ---------------------------------------------------------------------------

def test_sigmoid_dua_diem_ve_0_1_va_khong_tran_so():
    assert sigmoid(0.0) == pytest.approx(0.5)
    assert sigmoid(-1000.0) == 0.0
    assert sigmoid(1000.0) == 1.0
    assert 0.0 <= sigmoid(-3.2) <= 1.0


def test_khong_gi_vuot_nguong_thi_tra_RONG_khong_tra_bua():
    scored = [(0.1, "lạc đề", {"source": "a"}), (0.2, "cũng lạc đề", {"source": "b"})]
    assert select_relevant(scored, threshold=0.5, top_k=3) == []


def test_select_xep_theo_diem_giam_dan_va_cat_dung_top_k():
    scored = [(0.6, "b", {"source": "b"}), (0.9, "a", {"source": "a"}),
              (0.7, "c", {"source": "c"})]
    out = select_relevant(scored, threshold=0.5, top_k=2)
    assert [p.source for p in out] == ["a", "c"]


def test_cau_hoi_lac_de_khong_nhan_duoc_tai_lieu_ngau_nhien(kb):
    kb.add_document("hp", BANG_GIA_2026, source="gia.txt")
    assert kb.search("hp", "công thức nấu phở bò gia truyền") == []


# ---------------------------------------------------------------------------
# Biên
# ---------------------------------------------------------------------------

def test_truy_van_rong_tra_rong(kb):
    assert kb.search("hp", "   ") == []


def test_kho_rong_tra_rong_khong_no(kb):
    assert kb.search("chua-co-gi", "giá cước") == []


def test_tai_lieu_rong_bao_canh_bao_chu_khong_no(kb):
    res = kb.add_document("hp", "   \n\n  ", source="rong.txt")
    assert res.chunks == 0
    assert res.warnings


def test_khoi_tao_KHONG_doc_dia_khong_nap_model():
    """
    Bản cũ gọi `ingest_folder()` trong `__init__` — dựng đối tượng là quét đĩa và
    nhúng toàn bộ kho, chặn startup. Ở đây dựng phải rẻ và không chạm gì.
    """
    kb = KnowledgeBase(embedder=None, reranker=None, collection=FakeCollection())
    assert kb._embedder is None and kb._reranker is None
