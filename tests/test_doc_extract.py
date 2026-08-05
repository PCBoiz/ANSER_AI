"""
tests/test_doc_extract.py — bóc chữ từ tài liệu khách gửi.

Dựng file .docx / .pdf THẬT rồi bóc, không mock lớp đọc — vì chỗ hay hỏng nhất
chính là lớp đọc đó, và hỏng theo kiểu im lặng.
"""

from __future__ import annotations

from io import BytesIO

import pytest

from src.core.doc_extract import SUPPORTED, extract

docx = pytest.importorskip("docx")
pypdf = pytest.importorskip("pypdf")


def _docx(doan: list[str], bang: list[list[str]] | None = None) -> bytes:
    d = docx.Document()
    for p in doan:
        d.add_paragraph(p)
    if bang:
        t = d.add_table(rows=len(bang), cols=len(bang[0]))
        for i, hang in enumerate(bang):
            for j, o in enumerate(hang):
                t.cell(i, j).text = o
    buf = BytesIO()
    d.save(buf)
    return buf.getvalue()


def _pdf_trong(so_trang: int = 3) -> bytes:
    """PDF hợp lệ nhưng KHÔNG có lớp chữ — đúng hình dạng một bản scan."""
    w = pypdf.PdfWriter()
    for _ in range(so_trang):
        w.add_blank_page(width=595, height=842)
    buf = BytesIO()
    w.write(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Đường đi thuận
# ---------------------------------------------------------------------------

def test_doc_duoc_docx():
    data = _docx(["HỢP ĐỒNG VẬN CHUYỂN", "Điều 5. Thanh toán trong 30 ngày."])
    res = extract(data, "hop_dong.docx")
    assert res.ok
    assert "HỢP ĐỒNG VẬN CHUYỂN" in res.text
    assert "30 ngày" in res.text


def test_BANG_trong_docx_khong_bi_bo_sot():
    """
    Bảng trong .docx nằm NGOÀI `paragraphs`. Bảng giá cước của khách gần như luôn
    là một bảng Word — đọc mỗi paragraphs là mất đúng phần giá trị nhất, mà vẫn
    "nạp thành công" nên không ai biết.
    """
    data = _docx(
        ["BẢNG GIÁ CƯỚC 2026"],
        bang=[["Điểm đi", "Điểm đến", "Đơn giá"],
              ["Hà Nội", "Đà Nẵng", "12.000.000"]],
    )
    res = extract(data, "bang_gia.docx")
    assert "12.000.000" in res.text, "mất số tiền trong bảng"
    assert "Đà Nẵng" in res.text
    assert "Hà Nội\tĐà Nẵng\t12.000.000" in res.text, "mất ranh giới cột"


@pytest.mark.parametrize("ten", ["ghi_chu.txt", "ghi_chu.md"])
def test_doc_duoc_van_ban_thuong(ten):
    res = extract("Nhà xe Minh Thành cho nợ 30 ngày.".encode("utf-8"), ten)
    assert res.ok and "Minh Thành" in res.text


# ---------------------------------------------------------------------------
# PDF SCAN — chỗ hỏng im lặng nguy hiểm nhất
# ---------------------------------------------------------------------------

def test_pdf_scan_bi_TU_CHOI_chu_khong_nap_rong():
    """
    `pypdf` đọc PDF scan ra chuỗi rỗng và KHÔNG báo lỗi gì. Nạp trót lọt, hiện
    "0 đoạn", rồi ba tuần sau người dùng hỏi về hợp đồng đó và hệ thống trả lời
    "không có trong tài liệu" — trong khi file rành rành nằm trong danh sách.
    """
    with pytest.raises(ValueError) as e:
        extract(_pdf_trong(3), "hop_dong_scan.pdf")
    loi = str(e.value)
    assert "SCAN" in loi.upper()
    assert "docx" in loi.lower() or "OCR" in loi, "phải nói được PHẢI LÀM GÌ"


def test_docx_rong_cung_bi_tu_choi():
    with pytest.raises(ValueError):
        extract(_docx([]), "rong.docx")


# ---------------------------------------------------------------------------
# File sai loại / hỏng — thông báo phải nói được cách sửa
# ---------------------------------------------------------------------------

def test_doc_doi_cu_bao_ro_cach_sua():
    with pytest.raises(ValueError) as e:
        extract(b"\xd0\xcf\x11\xe0" + b"\x00" * 32, "hop_dong.doc")
    assert ".docx" in str(e.value)


def test_duoi_la_bi_tu_choi_kem_danh_sach_nhan_duoc():
    with pytest.raises(ValueError) as e:
        extract(b"noi dung", "anh.jpg")
    for duoi in SUPPORTED:
        assert duoi in str(e.value)


def test_file_hong_tra_ValueError_chu_khong_no():
    with pytest.raises(ValueError) as e:
        extract(b"%PDF-1.7\nrac rac rac", "hong.pdf")
    assert "hỏng" in str(e.value) or "Không mở được" in str(e.value)


def test_file_rong():
    with pytest.raises(ValueError) as e:
        extract(b"", "rong.pdf")
    assert "rỗng" in str(e.value)


def test_khong_co_duoi_file():
    with pytest.raises(ValueError):
        extract(b"noi dung", "khong_duoi")
