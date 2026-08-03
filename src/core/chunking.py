"""
src/core/chunking.py — cắt tài liệu thành đoạn, GIỮ NGUYÊN cấu trúc.

VÌ SAO TÁCH RA MODULE RIÊNG
---------------------------
Bản cũ cắt đoạn ngay trong `knowledge.py` bằng:

    words = word_tokenize(text)        # xoá sạch xuống dòng
    chunk = " ".join(words[i:j])       # nối lại bằng dấu cách

`word_tokenize` chạy trên CẢ tài liệu rồi nối lại bằng dấu cách làm biến mất mọi
ký tự xuống dòng và ranh giới ô bảng — TRƯỚC khi cắt một chữ nào. Nên bảng giá
cước vào RAG là mất hẳn cấu trúc:

    Hà Nội  Đà Nẵng  xe tải 5 tấn  12.000.000  Hà Nội  TP.HCM  container  31.500.000

Cắt ở giữa dải đó thì một đoạn giữ tuyến, đoạn kia giữ số tiền. Model nhận được
"12.000.000" mà không biết của tuyến nào — và bảng giá lại chính là tài liệu giá
trị nhất của khách.

Ở đây KHÔNG tách từ. Tách từ chỉ dùng cho BM25, nơi duy nhất thật sự cần.

NGUYÊN TẮC
----------
1. Không bao giờ cắt giữa một dòng. Dòng là đơn vị nhỏ nhất.
2. Dòng bảng đi cùng tiêu đề bảng của nó — mất tiêu đề là mất ý nghĩa các cột.
3. Đoạn dài quá thì cắt ở ranh giới dòng gần nhất, không cắt giữa chừng.
4. Chồng lấn tính bằng DÒNG, không bằng từ.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Đoạn mục tiêu ~1200 ký tự. Chọn theo ký tự chứ không theo từ vì đó là thứ ta
# đo được chắc chắn; số token thì tuỳ tokenizer. bge-m3 nhận 8192 token nên
# 1200 ký tự (~400-600 token tiếng Việt) rất thoải mái, không có nguy cơ bị cắt
# cụt im lặng như embedder cũ (giới hạn 128 token).
MAX_CHARS = 1200
OVERLAP_LINES = 2

# Dòng bảng: có ít nhất hai cụm ngăn bằng tab, |, hoặc >=2 khoảng trắng liên tiếp.
_TABLE_ROW = re.compile(r"^\s*\S.*?(?:\t|\s{2,}|\s*\|\s*)\S")
# Tiêu đề: dòng ngắn, không kết thúc bằng dấu câu, hoặc kiểu markdown/số thứ tự.
_HEADING = re.compile(r"^\s*(#{1,6}\s|\d+(\.\d+)*[.)]\s|[IVX]+[.)]\s)")


@dataclass
class Chunk:
    text: str
    """Số thứ tự đoạn trong tài liệu — để dẫn nguồn 'đoạn 3/12'."""
    index: int
    """Tiêu đề gần nhất phía trên đoạn này, nếu có."""
    heading: str = ""


def _is_table_row(line: str) -> bool:
    return bool(_TABLE_ROW.match(line)) and not _HEADING.match(line)


def _is_heading(line: str) -> bool:
    """
    Nhận dạng tiêu đề — CỐ Ý chặt tay.

    Bản đầu nhận "dòng ngắn không kết thúc bằng dấu câu" là tiêu đề. Trên một
    bảng giá thì MỌI dòng đều ngắn và không có dấu câu, nên mọi dòng thành tiêu
    đề, và mỗi dòng lại chốt một đoạn — bảng vỡ vụn thành từng dòng rời.

    Chỉ nhận hai dạng chắc chắn: dấu hiệu tường minh (`#`, `1.`, `II)`), hoặc
    dòng ngắn VIẾT HOA — cách viết tiêu đề phổ biến trong văn bản tiếng Việt
    ("BẢNG GIÁ CƯỚC VẬN TẢI 2026", "PHỤ LỤC I"). Đoán sai theo hướng bỏ sót thì
    chỉ mất một nhãn; đoán sai theo hướng nhận bừa thì vỡ cả bảng.
    """
    stripped = line.strip()
    if not stripped or _is_table_row(line):
        return False
    if _HEADING.match(line):
        return True
    if len(stripped) > 80:
        return False
    chu_cai = [c for c in stripped if c.isalpha()]
    if not chu_cai:
        return False
    return sum(1 for c in chu_cai if c.isupper()) / len(chu_cai) >= 0.6


def split_lines(text: str) -> list[str]:
    """Giữ nguyên dòng, chỉ bỏ dòng trắng thừa ở hai đầu."""
    return [ln.rstrip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]


def chunk_document(text: str, max_chars: int = MAX_CHARS,
                   overlap_lines: int = OVERLAP_LINES) -> list[Chunk]:
    """
    Cắt tài liệu thành đoạn, không bao giờ cắt giữa một dòng.

    Bám theo tiêu đề gần nhất: mỗi đoạn mang theo tiêu đề của nó, nên một đoạn
    giữa bảng giá vẫn biết mình thuộc "Bảng giá cước 2026" chứ không trôi nổi.
    """
    lines = split_lines(text)
    if not any(ln.strip() for ln in lines):
        return []

    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_chars = 0
    heading = ""
    # Tiêu đề của đoạn ĐANG gom, chốt lúc đoạn bắt đầu — không phải tiêu đề mới
    # nhất, vì tiêu đề xuất hiện giữa chừng thuộc về đoạn sau.
    buf_heading = ""

    def flush() -> None:
        nonlocal buf, buf_chars, buf_heading
        body = "\n".join(buf).strip()
        if body:
            chunks.append(Chunk(text=body, index=len(chunks), heading=buf_heading))
        buf, buf_chars = [], 0

    for line in lines:
        if _is_heading(line) and line.strip():
            heading = line.strip()
            # Tiêu đề mới bắt đầu một phần mới -> chốt đoạn đang gom nếu đã đủ dài.
            # Đủ dài = quá nửa hạn mức; ngắn hơn thì gộp vào để tránh đoạn vụn.
            if buf_chars > max_chars // 2:
                flush()

        if not buf:
            buf_heading = heading

        # Vượt hạn mức -> chốt TRƯỚC khi thêm dòng này, để không cắt giữa dòng.
        if buf and buf_chars + len(line) + 1 > max_chars:
            tail = buf[-overlap_lines:] if overlap_lines else []
            flush()
            # Chồng lấn theo DÒNG: dòng bảng cuối của đoạn trước lặp sang đoạn
            # sau, nên một dòng giá nằm đúng ranh giới vẫn còn nguyên ở một bên.
            buf = list(tail)
            buf_chars = sum(len(x) + 1 for x in buf)
            buf_heading = heading

        buf.append(line)
        buf_chars += len(line) + 1

    flush()
    return chunks


def looks_tabular(text: str) -> bool:
    """
    Tài liệu này có phải bảng không (bảng giá, danh mục)?

    Dùng để cảnh báo lúc nạp: bảng mà bị đọc thành một dải chữ thì mọi con số
    trong đó đều mất ngữ cảnh, và người nạp cần biết ngay chứ không phải phát
    hiện qua một câu trả lời sai ba tuần sau.
    """
    lines = [ln for ln in split_lines(text) if ln.strip()]
    if len(lines) < 3:
        return False
    return sum(1 for ln in lines if _is_table_row(ln)) / len(lines) >= 0.3
