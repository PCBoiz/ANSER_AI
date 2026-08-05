"""
tests/test_knowledge_api.py — đường NẠP tài liệu vào kho tri thức.

`KnowledgeBase` viết lại xong từ 03/08/2026 và chạy thật đúng 9/9 phép kiểm,
nhưng `add_document()` chưa từng được gọi từ bất kỳ đâu — kho tri thức không có
cửa vào. Khách gửi 10–30 tài liệu về thì không có chỗ nào đổ vào (05/08/2026).

Dùng `KnowledgeBase` thật với collection giả: kiểm ĐƯỜNG HTTP và hàng rào cách ly,
không kiểm chất lượng ngữ nghĩa của model.
"""

from __future__ import annotations

from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.core.knowledge import KnowledgeBase
from tests.test_knowledge import FakeCollection, FakeEmbedder, FakeReranker

docx = pytest.importorskip("docx")
client = TestClient(app)

HP = "hoang-phat"


@pytest.fixture(autouse=True)
def kho(monkeypatch):
    from src.api import dependencies as deps

    kb = KnowledgeBase(
        embedder=FakeEmbedder(), reranker=FakeReranker(), collection=FakeCollection(),
    )
    monkeypatch.setattr(deps.runtime, "kb", kb, raising=False)
    return kb


def _docx_bytes(doan: list[str]) -> bytes:
    d = docx.Document()
    for p in doan:
        d.add_paragraph(p)
    buf = BytesIO()
    d.save(buf)
    return buf.getvalue()


def _tai_len(ten="hop_dong.docx", noi_dung=None, workspace=HP, **form):
    data = noi_dung if noi_dung is not None else _docx_bytes(
        ["HỢP ĐỒNG VẬN CHUYỂN", "Điều 5. Bên B thanh toán trong 30 ngày."]
    )
    return client.post(
        "/knowledge/documents",
        files={"file": (ten, BytesIO(data), "application/octet-stream")},
        data={"workspace_id": workspace, **form},
    )


# ---------------------------------------------------------------------------
# Nạp
# ---------------------------------------------------------------------------

def test_nap_duoc_tai_lieu():
    body = _tai_len(effective_from="01/01/2026", doc_type="hop_dong").json()
    assert body["chunks"] > 0
    assert body["source"] == "hop_dong.docx"
    assert body["replaced"] is False


def test_nap_lai_noi_dung_khong_doi_thi_bo_qua():
    _tai_len()
    lai = _tai_len().json()
    assert lai["skipped_unchanged"] is True and lai["chunks"] == 0


def test_sua_tai_lieu_thi_ban_CU_bien_mat():
    """Bảng giá năm ngoái không được sống sót bên cạnh bảng giá mới."""
    _tai_len("bang_gia.docx", _docx_bytes(["BẢNG GIÁ 2025", "Hà Nội Đà Nẵng 9000000"]))
    lai = _tai_len("bang_gia.docx",
                   _docx_bytes(["BẢNG GIÁ 2026", "Hà Nội Đà Nẵng 12000000"])).json()
    assert lai["replaced"] is True

    kq = client.post("/knowledge/search",
                     json={"workspace_id": HP, "query": "Hà Nội Đà Nẵng giá", "top_k": 10}).json()
    noi = " ".join(p["text"] for p in kq["passages"])
    assert "12000000" in noi and "9000000" not in noi


def test_pdf_scan_bi_tu_choi_chu_khong_nap_rong():
    import pypdf

    w = pypdf.PdfWriter()
    for _ in range(3):
        w.add_blank_page(width=595, height=842)
    buf = BytesIO()
    w.write(buf)

    resp = _tai_len("scan.pdf", buf.getvalue())
    assert resp.status_code == 422
    assert "SCAN" in resp.json()["detail"].upper()


def test_file_sai_loai_bao_ro():
    resp = _tai_len("anh.jpg", b"khong phai tai lieu")
    assert resp.status_code == 422
    assert ".docx" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# CÁCH LY — hàng rào quan trọng nhất
# ---------------------------------------------------------------------------

def test_thieu_workspace_id_thi_TU_CHOI():
    """Quên truyền phải hỏng ngay, không phải rò lặng lẽ."""
    assert _tai_len(workspace="").status_code == 422
    assert client.get("/knowledge/documents", params={"workspace_id": ""}).status_code == 422
    assert client.post("/knowledge/search",
                       json={"workspace_id": "", "query": "x"}).status_code == 422


def test_khong_truyen_workspace_id_thi_422_chu_khong_dung_mac_dinh():
    resp = client.post(
        "/knowledge/documents",
        files={"file": ("x.txt", BytesIO(b"noi dung"), "text/plain")},
    )
    assert resp.status_code == 422


def test_khach_nay_khong_thay_tai_lieu_cua_khach_kia():
    _tai_len("gia.docx", _docx_bytes(["BẢNG GIÁ", "Hà Nội Đà Nẵng 12000000"]))
    _tai_len("gia.docx", _docx_bytes(["BẢNG GIÁ MẬT", "Hà Nội Đà Nẵng 999000000"]),
             workspace="khach-khac")

    kq = client.post("/knowledge/search",
                     json={"workspace_id": HP, "query": "Hà Nội Đà Nẵng giá",
                           "top_k": 10}).json()
    assert all("999000000" not in p["text"] for p in kq["passages"])


def test_xoa_cua_khach_nay_khong_dung_khach_kia():
    _tai_len("gia.docx")
    _tai_len("gia.docx", workspace="khach-khac")
    assert client.request("DELETE", "/knowledge/documents",
                          params={"workspace_id": HP, "source": "gia.docx"}).status_code == 200
    con = client.get("/knowledge/documents", params={"workspace_id": "khach-khac"}).json()
    assert len(con["documents"]) == 1


# ---------------------------------------------------------------------------
# Liệt kê / xoá / tra cứu
# ---------------------------------------------------------------------------

def test_liet_ke_kem_ngay_hieu_luc():
    _tai_len("gia_2026.docx", effective_from="01/01/2026")
    ds = client.get("/knowledge/documents", params={"workspace_id": HP}).json()["documents"]
    assert ds[0]["source"] == "gia_2026.docx"
    assert ds[0]["effective_from"] == "01/01/2026"


def test_xoa_tai_lieu_khong_ton_tai_tra_404():
    resp = client.request("DELETE", "/knowledge/documents",
                          params={"workspace_id": HP, "source": "khong_co.docx"})
    assert resp.status_code == 404


def test_tra_cuu_tra_ve_NGUON_de_dan_lai():
    _tai_len("hop_dong.docx")
    p = client.post("/knowledge/search",
                    json={"workspace_id": HP, "query": "thanh toán 30 ngày"}).json()["passages"]
    assert p and p[0]["source"] == "hop_dong.docx"
    assert "hop_dong.docx" in p[0]["cite"]


def test_khong_tim_thay_thi_noi_RO_LY_DO():
    """Rỗng KHÔNG phải lỗi — giao diện phải phân biệt được với 'kho chưa có gì'."""
    _tai_len()
    body = client.post("/knowledge/search",
                       json={"workspace_id": HP, "query": "công thức nấu phở"}).json()
    assert body["passages"] == []
    assert body["empty_reason"]


def test_on_date_sai_dinh_dang_tra_422():
    assert client.post("/knowledge/search",
                       json={"workspace_id": HP, "query": "x",
                             "on_date": "01/01/2026"}).status_code == 422


def test_kho_chua_san_sang_tra_503_chu_khong_no(monkeypatch):
    """Thiếu chromadb là lỗi CÀI ĐẶT — phải nói thẳng cách cài, không nổ 500."""
    from src.api import dependencies as deps

    monkeypatch.setattr(deps.runtime, "kb", None, raising=False)
    resp = client.get("/knowledge/documents", params={"workspace_id": HP})
    assert resp.status_code == 503
    assert "pip install" in resp.json()["detail"]
